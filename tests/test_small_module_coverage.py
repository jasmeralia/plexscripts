from __future__ import annotations

import logging
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from plexadm import audit
from plexadm.config import (
    InventoryConfig,
    LoggingConfig,
    OpenSearchSinkConfig,
    PlexConfig,
    SyslogSinkConfig,
    load_config,
    load_logging_config,
)
from plexadm.dupes_report import _format_size
from plexadm.filters import in_collection, no_studio, not_in_collection, or_filter, rated, title_contains, unrated
from plexadm.inventory import _client, diff_snapshots
from plexadm.plex import PlexContext, reload_if_partial
from plexadm.progress import progress_prefix
from plexadm.writers import missing_title_writers, read_writer_file, writer_names


def test_raw_formatter_returns_only_message() -> None:
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "hello %s", ("world",), None)
    assert audit._RawFormatter().format(record) == "hello world"


def test_opensearch_handler_indexes_json_and_handles_client_error() -> None:
    fake_client = MagicMock()
    fake_module = SimpleNamespace(OpenSearch=MagicMock(return_value=fake_client))
    cfg = OpenSearchSinkConfig(
        url="http://search:9200", username="user", password="pass", verify_tls=False, index="audit"
    )
    with patch.dict(sys.modules, {"opensearchpy": fake_module}):
        handler = audit.OpenSearchHandler(cfg)

    record = logging.LogRecord("test", logging.INFO, __file__, 1, '{"action": "add"}', (), None)
    handler.emit(record)
    fake_client.index.assert_called_once_with(index="audit", body={"action": "add"})

    fake_client.index.side_effect = RuntimeError("unavailable")
    with patch.object(handler, "handleError") as mock_handle_error:
        handler.emit(record)
    mock_handle_error.assert_called_once_with(record)


def test_syslog_handler_parses_network_address_and_wraps_socket_error() -> None:
    cfg = LoggingConfig(sink="syslog", syslog=SyslogSinkConfig(address="logs.example:1514", facility="local0"))
    with patch.object(logging.handlers, "SysLogHandler", return_value=MagicMock()) as mock_handler:
        audit._build_handler(cfg)
    mock_handler.assert_called_once_with(address=("logs.example", 1514), facility="local0")

    with (
        patch.object(logging.handlers, "SysLogHandler", side_effect=OSError("missing socket")),
        pytest.raises(RuntimeError, match="Could not reach syslog"),
    ):
        audit._build_handler(LoggingConfig(sink="syslog"))


def test_journal_handler_success_and_socket_failure() -> None:
    journal_handler = MagicMock(return_value=MagicMock())
    with patch.dict(
        sys.modules, {"systemd": SimpleNamespace(), "systemd.journal": SimpleNamespace(JournalHandler=journal_handler)}
    ):
        audit._build_handler(LoggingConfig(sink="journal"))
    journal_handler.assert_called_once_with(SYSLOG_IDENTIFIER="plexadm")

    failing = MagicMock(side_effect=OSError("no journal"))
    with (
        patch.dict(
            sys.modules, {"systemd": SimpleNamespace(), "systemd.journal": SimpleNamespace(JournalHandler=failing)}
        ),
        pytest.raises(RuntimeError, match="journal socket"),
    ):
        audit._build_handler(LoggingConfig(sink="journal"))


def test_load_config_success_and_validation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "plex.ini"
    config_path.write_text(
        "[default]\nplexHost=host\nplexPort=32400\nplexToken=token\nplexSectionName=Videos\n"
        "plexSection=4\nstashEndpoint=http://stash:9999\n",
        encoding="utf-8",
    )
    cfg = load_config(config_path)
    assert cfg == PlexConfig("host", "32400", "token", "Videos", "4", "http://stash:9999")
    assert cfg.base_url == "http://host:32400"

    monkeypatch.setenv("PLEXADM_CONFIG", str(config_path))
    assert load_config() == cfg

    with pytest.raises(FileNotFoundError, match="Unable to read"):
        load_config(tmp_path / "missing.ini")

    config_path.write_text("[other]\nvalue=x\n", encoding="utf-8")
    with pytest.raises(KeyError, match=r"Missing \[default\]"):
        load_config(config_path)

    config_path.write_text("[default]\nplexHost=host\n", encoding="utf-8")
    with pytest.raises(KeyError, match="plexPort, plexToken, plexSectionName"):
        load_config(config_path)


def test_load_logging_config_rejects_invalid_sink_and_missing_opensearch_url(tmp_path: Path) -> None:
    path = tmp_path / "config.ini"
    path.write_text("[logging]\nsink=bogus\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"Unknown \[logging\] sink"):
        load_logging_config(path)

    path.write_text("[logging]\nsink=file\n[logging.opensearch]\nindex=audit\n", encoding="utf-8")
    with pytest.raises(KeyError, match="requires 'url'"):
        load_logging_config(path)


def test_filter_writer_progress_and_size_helpers(tmp_path: Path) -> None:
    assert or_filter({"title": "x"}, {}) == {"or": [{"title": "x"}]}
    assert title_contains("needle") == {"title": "needle"}
    assert in_collection("Included") == {"collection": "Included"}
    assert not_in_collection("Excluded") == {"collection!": "Excluded"}
    assert no_studio() == {"studio__exact": ""}
    assert unrated() == {"userRating": -1}
    assert rated() == {"userRating>>": 0}
    assert progress_prefix(3, 0) == "[0/0] "
    assert _format_size(2 * 1024**4) == "2.0 TB"

    writer_file = tmp_path / "writers.txt"
    writer_file.write_text(" Example Writer \n\nSecond Writer\n", encoding="utf-8")
    assert read_writer_file(writer_file) == ["Example Writer", "Second Writer"]
    video = SimpleNamespace(title="Example Writer, Missing Writer - Scene", writers=[" example writer "])
    assert writer_names(video) == {"example writer"}
    assert missing_title_writers(video) == ["Missing Writer"]
    assert writer_names(SimpleNamespace(writers=None)) == set()


def test_inventory_client_and_diff_validation() -> None:
    fake_open_search = MagicMock()
    with patch("opensearchpy.OpenSearch", fake_open_search):
        _client(InventoryConfig(url="http://search:9200", username="user", password="pass", verify_tls=False))
    fake_open_search.assert_called_once_with(
        hosts=["http://search:9200"], http_auth=("user", "pass"), verify_certs=False
    )

    cfg = InventoryConfig(url="http://search:9200")
    with (
        patch("plexadm.inventory._fetch_run_ids", return_value=["only-one"]),
        pytest.raises(ValueError, match="only found 1"),
    ):
        diff_snapshots(cfg)
    with pytest.raises(ValueError, match="run_a is required"):
        diff_snapshots(cfg, run_b="new")


def test_diff_skips_unchanged_and_checks_removed_audit_event() -> None:
    cfg = InventoryConfig(url="http://search:9200")
    older = {1: {"title": "Video", "collections": ["Old"]}, 2: {"title": "Same", "collections": []}}
    newer = {1: {"title": "Video", "collections": []}, 2: {"title": "Same", "collections": []}}
    client = MagicMock()
    client.search.return_value = {"hits": {"total": {"value": 0}}}
    with (
        patch("plexadm.inventory._fetch_run", side_effect=[older, newer]),
        patch("plexadm.inventory._client", return_value=client),
    ):
        _, _, changes = diff_snapshots(cfg, run_a="old", run_b="new", audit_index="audit")
    assert len(changes) == 1
    assert changes[0].removed == ["Old"]
    assert changes[0].attributed is False
    filters = client.search.call_args.kwargs["body"]["query"]["bool"]["filter"]
    assert {"term": {"action": "remove"}} in filters


def test_plex_context_constructs_searches_and_reloads() -> None:
    server = MagicMock()
    section = server.library.section.return_value
    cfg = PlexConfig("host", "32400", "token", "Videos")
    with patch("plexadm.plex.PlexServer", return_value=server):
        ctx = PlexContext(cfg)
    server.library.section.assert_called_once_with("Videos")

    exact = SimpleNamespace(title="videos")
    section.collection.return_value = exact
    assert ctx.collection("Videos") is exact
    section.collection.return_value = SimpleNamespace(title="Wrong")
    with pytest.raises(LookupError, match="not found"):
        ctx.collection("Videos")

    first = MagicMock()
    section.all.return_value = [first]
    assert ctx.all_videos(reload=True) == [first]
    first.reload.assert_called_once_with()

    partial = MagicMock()
    partial.isPartialObject.return_value = True
    section.search.return_value = [partial]
    assert ctx.search(filters={"title": "x"}, reload=True, unwatched=True) == [partial]
    section.search.assert_called_once_with(filters={"title": "x"}, sort="titleSort", unwatched=True)
    partial.reload.assert_called_once_with()


def test_plex_context_from_config_and_non_partial_reload() -> None:
    cfg = PlexConfig("host", "32400", "token", "Videos")
    with (
        patch("plexadm.plex.load_config", return_value=cfg) as mock_load,
        patch.object(PlexContext, "__init__", return_value=None),
    ):
        ctx = PlexContext.from_config("custom.ini")
    mock_load.assert_called_once_with("custom.ini")
    assert isinstance(ctx, PlexContext)

    item = MagicMock()
    item.isPartialObject.return_value = False
    assert reload_if_partial(item) is item
    item.reload.assert_not_called()
