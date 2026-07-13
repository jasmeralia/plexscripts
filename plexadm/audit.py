from __future__ import annotations

import json
import logging
import logging.handlers
import shlex
import sys
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from plexadm.config import LoggingConfig, OpenSearchSinkConfig
from plexadm.console import fail


@dataclass(frozen=True)
class InvocationContext:
    rule: str
    invocation: str


_CURRENT_INVOCATION: ContextVar[InvocationContext | None] = ContextVar("plexadm_invocation", default=None)


@dataclass(frozen=True)
class MutationEvent:
    action: str
    title: str
    rating_key: int | None = None
    collection: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        ctx = _CURRENT_INVOCATION.get()
        return {
            "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
            "action": self.action,
            "title": self.title,
            "rating_key": self.rating_key,
            "collection": self.collection,
            "rule": ctx.rule if ctx else "unknown",
            "invocation": ctx.invocation if ctx else "",
            "details": self.details,
        }


def set_invocation_context(*, rule: str, argv: list[str] | None = None) -> None:
    _CURRENT_INVOCATION.set(InvocationContext(rule=rule, invocation=shlex.join(argv or sys.argv)))


class _RawFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return record.getMessage()


class OpenSearchHandler(logging.Handler):
    def __init__(self, config: OpenSearchSinkConfig):
        super().__init__()
        from opensearchpy import OpenSearch

        self._client = OpenSearch(
            hosts=[config.url],
            http_auth=(config.username, config.password) if config.username else None,
            verify_certs=config.verify_tls,
        )
        self._index = config.index

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._client.index(index=self._index, body=json.loads(record.getMessage()))
        except Exception:
            self.handleError(record)


def _build_handler(config: LoggingConfig) -> logging.Handler:
    if config.sink == "file":
        config.file.path.parent.mkdir(parents=True, exist_ok=True)
        handler: logging.Handler = logging.handlers.RotatingFileHandler(
            config.file.path,
            maxBytes=config.file.max_bytes,
            backupCount=config.file.backup_count,
            encoding="utf-8",
        )
    elif config.sink == "syslog":
        address = config.syslog.address
        target: str | tuple[str, int] = address
        if ":" in address and not address.startswith("/"):
            host, port = address.rsplit(":", 1)
            target = (host, int(port))
        try:
            handler = logging.handlers.SysLogHandler(address=target, facility=config.syslog.facility)
        except OSError as exc:
            raise RuntimeError(
                f"Could not reach syslog at {address!r}. Inside Docker, /dev/log usually doesn't exist - "
                "set [logging.syslog] address to a remote host:port instead."
            ) from exc
    elif config.sink == "journal":
        try:
            from systemd.journal import JournalHandler
        except ImportError as exc:
            raise RuntimeError(
                "sink = journal requires the optional 'systemd-python' package: pip install systemd-python"
            ) from exc
        try:
            handler = JournalHandler(SYSLOG_IDENTIFIER=config.journal.identifier)
        except OSError as exc:
            raise RuntimeError(
                "Could not reach the systemd journal socket. Inside Docker this usually needs "
                "/run/systemd/journal bind-mounted from the host - journal is best suited to bare-metal runs."
            ) from exc
    elif config.sink == "opensearch":
        if config.opensearch is None:
            raise RuntimeError("sink = opensearch requires a [logging.opensearch] section with at least 'url'.")
        handler = OpenSearchHandler(config.opensearch)
    else:
        raise ValueError(f"Unknown logging sink: {config.sink!r}")
    handler.setFormatter(_RawFormatter())
    return handler


_CONFIG: LoggingConfig | None = None
_LOGGER: logging.Logger | None = None
_FAILURE_COUNT = 0


def configure(config: LoggingConfig) -> None:
    global _CONFIG, _LOGGER
    _CONFIG = config
    _LOGGER = None


def _logger() -> logging.Logger:
    global _LOGGER
    if _LOGGER is None:
        logger = logging.getLogger("plexadm.audit")
        logger.propagate = False
        logger.setLevel(logging.INFO)
        logger.handlers.clear()
        logger.addHandler(_build_handler(_CONFIG or LoggingConfig()))
        _LOGGER = logger
    return _LOGGER


def log_mutation(event: MutationEvent) -> None:
    global _FAILURE_COUNT
    try:
        _logger().info(json.dumps(event.to_record(), sort_keys=True))
    except Exception as exc:
        _FAILURE_COUNT += 1
        sink = (_CONFIG or LoggingConfig()).sink
        print(fail(f"AUDIT LOG WRITE FAILED ({sink}): {exc}"), file=sys.stderr)


def has_failures() -> bool:
    return _FAILURE_COUNT > 0
