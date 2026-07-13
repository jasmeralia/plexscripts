from __future__ import annotations

import logging.handlers
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from plexadm import audit
from plexadm.audit import MutationEvent
from plexadm.config import (
    FileSinkConfig,
    LoggingConfig,
    OpenSearchSinkConfig,
    load_logging_config,
)


class TestMutationEventToRecord:
    def test_defaults_without_invocation_context(self) -> None:
        audit._CURRENT_INVOCATION.set(None)

        record = MutationEvent(action="add", title="Example").to_record()

        assert record["rule"] == "unknown"
        assert record["invocation"] == ""
        timestamp = datetime.fromisoformat(record["timestamp"])
        assert timestamp.utcoffset() == timedelta(0)

    def test_uses_invocation_context(self) -> None:
        audit.set_invocation_context(rule="add_matching_titles", argv=["plexadm", "collection", "add-title", "A B"])

        record = MutationEvent(action="add", title="Example").to_record()

        assert record["rule"] == "add_matching_titles"
        assert record["invocation"] == "plexadm collection add-title 'A B'"


class TestBuildHandler:
    def test_file_sink_builds_rotating_handler(self, tmp_path: Path) -> None:
        path = tmp_path / "logs" / "audit.jsonl"
        config = LoggingConfig(file=FileSinkConfig(path=path, max_bytes=1234, backup_count=3))

        handler = audit._build_handler(config)
        try:
            assert isinstance(handler, logging.handlers.RotatingFileHandler)
            assert handler.baseFilename == str(path)
            assert handler.maxBytes == 1234
            assert handler.backupCount == 3
        finally:
            handler.close()

    def test_opensearch_without_config_raises(self) -> None:
        with pytest.raises(RuntimeError, match=r"\[logging\.opensearch\]"):
            audit._build_handler(LoggingConfig(sink="opensearch"))

    def test_journal_without_optional_dependency_raises(self) -> None:
        with (
            patch.dict(sys.modules, {"systemd": None, "systemd.journal": None}),
            pytest.raises(RuntimeError, match="pip install systemd-python"),
        ):
            audit._build_handler(LoggingConfig(sink="journal"))

    def test_unknown_sink_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown logging sink"):
            audit._build_handler(LoggingConfig(sink="unknown"))


class TestLogMutationFailureHandling:
    def test_emit_failure_is_recorded_and_printed(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        audit._FAILURE_COUNT = 0
        audit.configure(LoggingConfig(file=FileSinkConfig(path=tmp_path / "audit.jsonl")))
        logger = audit._logger()
        handler = logger.handlers[0]

        with patch.object(handler, "emit", side_effect=OSError("disk full")):
            audit.log_mutation(MutationEvent(action="add", title="Example"))

        assert audit.has_failures() is True
        assert "AUDIT LOG WRITE FAILED (file): disk full" in capsys.readouterr().err
        handler.close()


class TestLoadLoggingConfig:
    def test_missing_logging_section_uses_defaults(self, tmp_path: Path) -> None:
        config_path = tmp_path / "plex.ini"
        config_path.write_text("[default]\nplexHost = localhost\n", encoding="utf-8")

        config = load_logging_config(config_path)

        assert config.sink == "file"
        assert config.file == FileSinkConfig()
        assert config.opensearch is None

    def test_all_explicit_values_round_trip(self, tmp_path: Path) -> None:
        config_path = tmp_path / "plex.ini"
        config_path.write_text(
            """[logging]
sink = opensearch

[logging.file]
path = ~/custom-audit.jsonl
max_bytes = 99
backup_count = 4

[logging.syslog]
address = logs.example.com:1514
facility = local0

[logging.journal]
identifier = custom-plexadm

[logging.opensearch]
url = https://search.example.com:9200
index = custom-index
username = audit-user
password = secret
verify_tls = false
""",
            encoding="utf-8",
        )

        config = load_logging_config(config_path)

        assert config.sink == "opensearch"
        assert config.file == FileSinkConfig(path=Path.home() / "custom-audit.jsonl", max_bytes=99, backup_count=4)
        assert config.syslog.address == "logs.example.com:1514"
        assert config.syslog.facility == "local0"
        assert config.journal.identifier == "custom-plexadm"
        assert config.opensearch == OpenSearchSinkConfig(
            url="https://search.example.com:9200",
            index="custom-index",
            username="audit-user",
            password="secret",
            verify_tls=False,
        )

    def test_opensearch_sink_requires_section(self, tmp_path: Path) -> None:
        config_path = tmp_path / "plex.ini"
        config_path.write_text("[logging]\nsink = opensearch\n", encoding="utf-8")

        with pytest.raises(KeyError, match=r"\[logging\.opensearch\]"):
            load_logging_config(config_path)
