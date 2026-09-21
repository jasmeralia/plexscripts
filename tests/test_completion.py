from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from plexadm import cli, completion


def _write_cache(home: Path, content: str) -> None:
    path = home / ".plexadm" / "completion-cache.json"
    path.parent.mkdir(parents=True)
    path.write_text(content, encoding="utf-8")


def test_name_completers_filter_case_insensitively(tmp_path: Path) -> None:
    _write_cache(
        tmp_path,
        json.dumps(
            {
                "collections": ["01: Activity: Example", "02: Studio: Example"],
                "studios": ["Example Studio", "Other Studio"],
                "writers": ["Example Writer", "Another Writer"],
            }
        ),
    )

    with patch.object(completion.Path, "home", return_value=tmp_path):
        assert completion.complete_collections("01:") == ["01: Activity: Example"]
        assert completion.complete_studios("example") == ["Example Studio"]
        assert completion.complete_writers("missing") == []


def test_name_completers_tolerate_missing_and_corrupt_caches(tmp_path: Path) -> None:
    with patch.object(completion.Path, "home", return_value=tmp_path):
        assert completion.complete_collections("") == []
        _write_cache(tmp_path, "not json")
        assert completion.complete_studios("") == []


def _find_action(parser: argparse.ArgumentParser, command_path: tuple[str, ...], dest: str) -> argparse.Action:
    current = parser
    for command in command_path:
        subparsers = next(action for action in current._actions if isinstance(action, argparse._SubParsersAction))
        current = subparsers.choices[command]
    return next(action for action in current._actions if action.dest == dest)


def test_parser_attaches_dynamic_completers_by_metavar() -> None:
    parser = cli.build_parser()

    collection = _find_action(parser, ("collection", "add-title"), "collection")
    studio = _find_action(parser, ("studio", "set-title"), "studio")
    writer = _find_action(parser, ("collection", "add-writer"), "pattern")

    assert collection.completer is completion.complete_collections  # type: ignore[attr-defined]
    assert studio.completer is completion.complete_studios  # type: ignore[attr-defined]
    assert writer.completer is completion.complete_writers  # type: ignore[attr-defined]


def test_refresh_completion_cache_writes_distinct_sorted_names(tmp_path: Path) -> None:
    ctx = MagicMock()
    ctx.section.collections.return_value = [
        SimpleNamespace(title="Zulu Collection"),
        SimpleNamespace(title="alpha Collection"),
        SimpleNamespace(title="Zulu Collection"),
    ]
    ctx.all_videos.return_value = [
        SimpleNamespace(studio="Zulu Studio", writers=["Writer Two", "Writer One"]),
        SimpleNamespace(studio="alpha Studio", writers=["Writer One"]),
        SimpleNamespace(studio=None, writers=None),
    ]

    with (
        patch.object(cli, "build_context", return_value=ctx),
        patch.object(completion.Path, "home", return_value=tmp_path),
    ):
        assert cli.refresh_completion_cache(argparse.Namespace(config=None)) == 0

    data = json.loads((tmp_path / ".plexadm" / "completion-cache.json").read_text(encoding="utf-8"))
    assert data["generated_at"].endswith("+00:00")
    assert data["collections"] == ["alpha Collection", "Zulu Collection"]
    assert data["studios"] == ["alpha Studio", "Zulu Studio"]
    assert data["writers"] == ["Writer One", "Writer Two"]


def test_completion_refresh_cache_dispatches() -> None:
    args = cli.build_parser().parse_args(["completion", "refresh-cache"])

    assert args.func is cli.refresh_completion_cache
    assert args.completion_command == "refresh-cache"


def test_main_enables_argcomplete() -> None:
    parser = MagicMock()
    parser.parse_args.return_value = argparse.Namespace(
        command="completion",
        completion_command="refresh-cache",
        config=None,
        dry_run=False,
        func=lambda _args: 0,
    )
    with (
        patch.object(cli, "build_parser", return_value=parser),
        patch.object(cli.argcomplete, "autocomplete") as autocomplete,
        patch.object(cli, "load_logging_config", return_value=MagicMock()),
        patch.object(cli.audit, "configure"),
        patch.object(cli.audit, "set_invocation_context"),
        patch.object(cli.audit, "log_event"),
        patch.object(cli.audit, "has_failures", return_value=False),
    ):
        assert cli.main([]) == 0

    autocomplete.assert_called_once_with(parser)
