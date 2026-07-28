from __future__ import annotations

import logging

from plexadm.config import LoggingConfig

# opensearch-py's own "opensearch" logger (and urllib3, which it sits on top of) logs every
# single HTTP request/connection event at INFO - useful for debugging connectivity, but pure
# noise mixed into plexadm's own --log-level INFO progress output. Both loggers propagate to
# root and inherit whatever level logging.basicConfig sets, with no way to quiet just them short
# of doing this explicitly.
_NOISY_LIBRARY_LOGGERS = ("opensearch", "opensearchpy.trace", "urllib3")


def configure_command_logging(log_level: str, logging_config: LoggingConfig | None = None) -> None:
    """Set up root logging for a plexadm CLI command, once, consistently.

    Every stash_*.py command function used to repeat the logging.basicConfig call verbatim -
    factored out here so LoggingConfig.quiet_opensearch_log (on by default; see
    PLEXADM_QUIET_OPENSEARCH_LOG / [logging] quiet_opensearch_log) applies everywhere
    automatically instead of needing to be remembered at each call site.
    """
    logging.basicConfig(level=getattr(logging, log_level.upper(), logging.WARNING), format="%(levelname)s: %(message)s")
    quiet = logging_config.quiet_opensearch_log if logging_config is not None else True
    if quiet:
        for name in _NOISY_LIBRARY_LOGGERS:
            logging.getLogger(name).setLevel(logging.WARNING)
