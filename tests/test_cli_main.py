from __future__ import annotations

import argparse
from unittest.mock import MagicMock, patch

from plexadm import audit, cli


def _fake_parser(args: argparse.Namespace) -> MagicMock:
    parser = MagicMock()
    parser.parse_args.return_value = args
    return parser


class TestMainErrorAndInterruptLogging:
    def test_exception_from_command_is_logged_as_error(self) -> None:
        def failing_command(_args: argparse.Namespace) -> int:
            raise RuntimeError("boom")

        args = argparse.Namespace(func=failing_command, config=None, dry_run=False, command="list")

        with (
            patch.object(cli, "build_parser", return_value=_fake_parser(args)),
            patch.object(audit, "log_error") as mock_log_error,
        ):
            result = cli.main([])

        assert result == 1
        mock_log_error.assert_called_once()
        message, kwargs = mock_log_error.call_args.args[0], mock_log_error.call_args.kwargs
        assert message == "boom"
        assert isinstance(kwargs["exc"], RuntimeError)

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
        event = mock_log_event.call_args.args[0]
        assert event.action == "interrupted"
        assert event.level == "WARNING"
        assert "interrupted_command" in event.title

    def test_successful_command_does_not_log_error_or_interrupt(self) -> None:
        audit._FAILURE_COUNT = 0
        args = argparse.Namespace(func=lambda _args: 0, config=None, dry_run=False, command="list")

        with (
            patch.object(cli, "build_parser", return_value=_fake_parser(args)),
            patch.object(audit, "log_error") as mock_log_error,
            patch.object(audit, "log_event") as mock_log_event,
        ):
            result = cli.main([])

        assert result == 0
        mock_log_error.assert_not_called()
        mock_log_event.assert_not_called()
