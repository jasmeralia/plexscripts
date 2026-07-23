from __future__ import annotations

import argparse
from unittest.mock import MagicMock, patch

from plexadm import audit, cli
from plexadm.audit import AuditEvent


def _fake_parser(args: argparse.Namespace) -> MagicMock:
    parser = MagicMock()
    parser.parse_args.return_value = args
    return parser


def _events_by_action(mock_log_event: MagicMock, action: str) -> list[AuditEvent]:
    return [call.args[0] for call in mock_log_event.call_args_list if call.args[0].action == action]


class TestMainErrorAndInterruptLogging:
    def test_exception_from_command_is_logged_as_error(self) -> None:
        def failing_command(_args: argparse.Namespace) -> int:
            raise RuntimeError("boom")

        args = argparse.Namespace(func=failing_command, config=None, dry_run=False, command="list")

        with (
            patch.object(cli, "build_parser", return_value=_fake_parser(args)),
            patch.object(audit, "log_event") as mock_log_event,
        ):
            result = cli.main([])

        assert result == 1
        errors = _events_by_action(mock_log_event, "error")
        assert len(errors) == 1
        assert errors[0].level == "ERROR"
        assert errors[0].title == "boom"
        assert errors[0].details == {"exception_type": "RuntimeError"}

    def test_keyboard_interrupt_is_logged_as_warning(self) -> None:
        def interrupted_command(_args: argparse.Namespace) -> int:
            raise KeyboardInterrupt

        args = argparse.Namespace(func=interrupted_command, config=None, dry_run=False, command="list")

        with (
            patch.object(cli, "build_parser", return_value=_fake_parser(args)),
            patch.object(audit, "log_event") as mock_log_event,
        ):
            result = cli.main([])

        assert result == 130
        interruptions = _events_by_action(mock_log_event, "interrupted")
        assert len(interruptions) == 1
        assert interruptions[0].level == "WARNING"
        assert "interrupted_command" in interruptions[0].title

    def test_successful_command_does_not_log_error_or_interrupt(self) -> None:
        audit._FAILURE_COUNT = 0
        args = argparse.Namespace(func=lambda _args: 0, config=None, dry_run=False, command="list")

        with (
            patch.object(cli, "build_parser", return_value=_fake_parser(args)),
            patch.object(audit, "log_event") as mock_log_event,
        ):
            result = cli.main([])

        assert result == 0
        assert _events_by_action(mock_log_event, "error") == []
        assert _events_by_action(mock_log_event, "interrupted") == []


class TestMainTimingEvent:
    def test_successful_command_logs_timing_at_info(self) -> None:
        args = argparse.Namespace(func=lambda _args: 0, config=None, dry_run=False, command="list")

        with (
            patch.object(cli, "build_parser", return_value=_fake_parser(args)),
            patch.object(audit, "log_event") as mock_log_event,
        ):
            cli.main([])

        timings = _events_by_action(mock_log_event, "timing")
        assert len(timings) == 1
        assert timings[0].level == "INFO"
        assert "<lambda>" in timings[0].title
        assert isinstance(timings[0].details["duration_seconds"], float)
        assert timings[0].details["duration_seconds"] >= 0

    def test_timing_is_still_logged_when_command_raises(self) -> None:
        def failing_command(_args: argparse.Namespace) -> int:
            raise RuntimeError("boom")

        args = argparse.Namespace(func=failing_command, config=None, dry_run=False, command="list")

        with (
            patch.object(cli, "build_parser", return_value=_fake_parser(args)),
            patch.object(audit, "log_event") as mock_log_event,
        ):
            cli.main([])

        timings = _events_by_action(mock_log_event, "timing")
        assert len(timings) == 1
        assert timings[0].details["duration_seconds"] >= 0


class TestSyncNoStudio:
    def test_removal_query_uses_the_working_kwarg_filter_not_the_broken_dict_one(self) -> None:
        # Real bug found on a live run: the dict-style advanced filter {"studio!": ""} silently
        # returns zero results for every video regardless of whether studio is actually set -
        # confirmed against the real library, where it missed real videos a studio__ne=""
        # kwarg-style query correctly found. A video (Independent Content) sat in "00A: NO
        # STUDIO" indefinitely because of this - sync_no_studio always reported "0 removed".
        collection = MagicMock()
        collection.title = "00A: NO STUDIO"
        stale_member = MagicMock(title="Has A Studio Now")

        ctx = MagicMock()
        ctx.collection.return_value = collection
        ctx.search.side_effect = [[], [stale_member]]

        args = argparse.Namespace(config=None, collection="00A: NO STUDIO", dry_run=False)

        with (
            patch.object(cli, "build_context", return_value=ctx),
            patch.object(cli, "add_items", return_value=0) as mock_add_items,
            patch.object(cli, "remove_items", return_value=1) as mock_remove_items,
        ):
            assert cli.sync_no_studio(args) == 0

        removal_call = ctx.search.call_args_list[1]
        assert removal_call.kwargs.get("studio__ne") == ""
        assert removal_call.kwargs.get("filters") == {"collection=": "00A: NO STUDIO"}
        assert "studio!" not in str(removal_call.kwargs.get("filters"))
        mock_remove_items.assert_called_once_with(collection, [stale_member], dry_run=False)
        mock_add_items.assert_called_once_with(collection, [], dry_run=False)


class TestAddDurationCollection:
    def test_defaults_to_short_video_bound_when_no_bounds_given(self) -> None:
        collection = MagicMock(title="01: Category: Short Videos")
        ctx = MagicMock()
        ctx.collection.return_value = collection
        ctx.search.return_value = []

        args = argparse.Namespace(
            config=None,
            dry_run=False,
            collection="01: Category: Short Videos",
            max_duration_ms=None,
            min_duration_ms=None,
            filters=None,
        )

        with patch.object(cli, "build_context", return_value=ctx), patch.object(cli, "add_items", return_value=0):
            assert cli.add_duration_collection(args) == 0

        used = ctx.search.call_args.kwargs["filters"]["and"]
        assert {"duration<<": cli.DEFAULT_SHORT_VIDEO_MAX_DURATION_MS} in used
        assert not any("duration>>" in part for part in used)

    def test_min_only_does_not_apply_the_short_video_default(self) -> None:
        # Real risk: silently keeping the old 90s default max bound alongside an explicit
        # --min-duration-ms would make min > max, so the query would always return nothing.
        collection = MagicMock(title="00D: Review: Indie Long No Livestream")
        ctx = MagicMock()
        ctx.collection.return_value = collection
        ctx.search.return_value = []

        args = argparse.Namespace(
            config=None,
            dry_run=False,
            collection="00D: Review: Indie Long No Livestream",
            max_duration_ms=None,
            min_duration_ms=3_600_000,
            filters=None,
        )

        with patch.object(cli, "build_context", return_value=ctx), patch.object(cli, "add_items", return_value=0):
            assert cli.add_duration_collection(args) == 0

        used = ctx.search.call_args.kwargs["filters"]["and"]
        assert {"duration>>": 3_600_000} in used
        assert not any("duration<<" in part for part in used)

    def test_ad_hoc_filters_json_is_and_combined_with_the_duration_bound(self) -> None:
        collection = MagicMock(title="00D: Review: Indie Long No Livestream")
        ctx = MagicMock()
        ctx.collection.return_value = collection
        ctx.search.return_value = []

        args = argparse.Namespace(
            config=None,
            dry_run=False,
            collection="00D: Review: Indie Long No Livestream",
            max_duration_ms=None,
            min_duration_ms=3_600_000,
            filters='{"studio": "Independent Content", "collection!": "01: Theme: Live Stream"}',
        )

        with patch.object(cli, "build_context", return_value=ctx), patch.object(cli, "add_items", return_value=0):
            assert cli.add_duration_collection(args) == 0

        used = ctx.search.call_args.kwargs["filters"]["and"]
        assert {"studio": "Independent Content"} in used
        assert {"collection!": "01: Theme: Live Stream"} in used
        assert {"duration>>": 3_600_000} in used


class TestRetargetWriterPpv:
    def test_resolves_old_collection_filter_key_before_emptying_it(self) -> None:
        # Real bug found live: resolving OLD's smart-filter ID via collection_filter_key()
        # AFTER remove_items() had already emptied OLD failed outright - Plex stops offering an
        # empty collection as a "collection" filter choice at all, so a smart collection
        # referencing OLD could never be retargeted once OLD had already been drained mid-run.
        # The fix resolves the key first, while OLD still has members.
        call_order: list[str] = []

        old = MagicMock(title="01: Rin PPV")
        new = MagicMock(title="01: Category: PPV")
        video = MagicMock(title="00 Rin - Example", collections=[])
        old.items.return_value = [video]

        ctx = MagicMock()
        ctx.collection.side_effect = lambda name: old if name == "01: Rin PPV" else new
        ctx.section.collections.return_value = []

        def fake_collection_filter_key(_section: object, title: str) -> str:
            call_order.append(f"resolve:{title}")
            return "169711"

        def fake_remove_items(_collection: object, items: list[object], *, dry_run: bool = False) -> int:
            call_order.append("remove")
            return len(list(items))

        args = argparse.Namespace(
            config=None,
            dry_run=False,
            writer="00 Rin",
            old_collection="01: Rin PPV",
            new_collection="01: Category: PPV",
            name_contains="Rin",
        )

        with (
            patch.object(cli, "build_context", return_value=ctx),
            patch.object(cli, "add_items", return_value=0),
            patch.object(cli, "remove_items", side_effect=fake_remove_items),
            patch.object(cli, "collection_filter_key", side_effect=fake_collection_filter_key),
        ):
            assert cli.retarget_writer_ppv(args) == 0

        assert call_order == ["resolve:01: Rin PPV", "remove"]
