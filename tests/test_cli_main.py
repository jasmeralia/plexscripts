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
