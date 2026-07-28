from __future__ import annotations

import logging

from plexadm.config import LoggingConfig
from plexadm.logging_setup import _NOISY_LIBRARY_LOGGERS, configure_command_logging


def _reset_noisy_loggers() -> None:
    for name in _NOISY_LIBRARY_LOGGERS:
        logging.getLogger(name).setLevel(logging.NOTSET)


class TestConfigureCommandLogging:
    def test_quiets_noisy_library_loggers_by_default(self) -> None:
        _reset_noisy_loggers()
        try:
            configure_command_logging("INFO", LoggingConfig())
            for name in _NOISY_LIBRARY_LOGGERS:
                assert logging.getLogger(name).level == logging.WARNING
        finally:
            _reset_noisy_loggers()

    def test_leaves_noisy_loggers_alone_when_disabled(self) -> None:
        _reset_noisy_loggers()
        try:
            configure_command_logging("INFO", LoggingConfig(quiet_opensearch_log=False))
            for name in _NOISY_LIBRARY_LOGGERS:
                assert logging.getLogger(name).level == logging.NOTSET
        finally:
            _reset_noisy_loggers()

    def test_defaults_to_quiet_when_no_logging_config_given(self) -> None:
        # `logging_config=None` happens if a caller ever skips loading the real config - stays
        # quiet by default rather than silently reverting to the noisy behavior.
        _reset_noisy_loggers()
        try:
            configure_command_logging("INFO", None)
            for name in _NOISY_LIBRARY_LOGGERS:
                assert logging.getLogger(name).level == logging.WARNING
        finally:
            _reset_noisy_loggers()
