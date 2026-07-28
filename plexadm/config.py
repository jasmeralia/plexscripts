from __future__ import annotations

import configparser
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def resolve_bool_setting(env_name: str, config_value: bool) -> bool:
    """Environment variable overrides the config-file/default value when set; falls through to
    config_value otherwise - same env-wins-over-config precedence PLEXADM_CONFIG already has
    over the config file's own default path. Accepts the usual truthy/falsy spellings
    ("1"/"true"/"yes"/"on" and their opposites), not just "1"/"0", since shell scripts set these
    inconsistently in practice.
    """
    raw = os.environ.get(env_name)
    if raw is None:
        return config_value
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class PlexConfig:
    host: str
    port: str
    token: str
    section_name: str
    section_id: str | None = None
    stash_endpoint: str | None = None

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


@dataclass(frozen=True)
class FileSinkConfig:
    path: Path = field(default_factory=lambda: Path.home() / ".plexadm" / "audit.jsonl")
    max_bytes: int = 10_485_760
    backup_count: int = 10


@dataclass(frozen=True)
class SyslogSinkConfig:
    address: str = "/dev/log"
    facility: str = "user"


@dataclass(frozen=True)
class JournalSinkConfig:
    identifier: str = "plexadm"


@dataclass(frozen=True)
class OpenSearchSinkConfig:
    url: str
    index: str = "plexadm-audit"
    username: str | None = None
    password: str | None = None
    verify_tls: bool = True


@dataclass(frozen=True)
class LoggingConfig:
    sink: str = "file"
    file: FileSinkConfig = field(default_factory=FileSinkConfig)
    syslog: SyslogSinkConfig = field(default_factory=SyslogSinkConfig)
    journal: JournalSinkConfig = field(default_factory=JournalSinkConfig)
    opensearch: OpenSearchSinkConfig | None = None
    # Third-party client libraries (opensearch-py, urllib3) log their own per-request/connection
    # details at INFO, which floods any `--log-level INFO` run once root logging is at INFO -
    # confirmed live: a stash backfill-tags run against an opensearch audit sink produced a "POST
    # .../_doc [status:201 request:...s]" line for every single audit event, drowning out
    # plexadm's own progress messages. On by default; PLEXADM_QUIET_OPENSEARCH_LOG env var takes
    # precedence over [logging] quiet_opensearch_log in the config file when both are set.
    quiet_opensearch_log: bool = True


@dataclass(frozen=True)
class InventoryConfig:
    url: str
    index: str = "plexadm-inventory"
    username: str | None = None
    password: str | None = None
    verify_tls: bool = True


def default_config_path() -> Path:
    return Path(os.environ.get("PLEXADM_CONFIG", Path.home() / ".plexconfig.ini")).expanduser()


def load_config(path: str | Path | None = None) -> PlexConfig:
    config_path = Path(path).expanduser() if path else default_config_path()
    parser = configparser.ConfigParser()
    read_files = parser.read(config_path)
    if not read_files:
        raise FileNotFoundError(f"Unable to read Plex config at {config_path}")
    if "default" not in parser:
        raise KeyError(f"Missing [default] section in {config_path}")

    section = parser["default"]
    required = ("plexHost", "plexPort", "plexToken", "plexSectionName")
    missing = [key for key in required if key not in section]
    if missing:
        raise KeyError(f"Missing required Plex config keys: {', '.join(missing)}")

    return PlexConfig(
        host=section["plexHost"],
        port=section["plexPort"],
        token=section["plexToken"],
        section_name=section["plexSectionName"],
        section_id=section.get("plexSection"),
        stash_endpoint=section.get("stashEndpoint"),
    )


def load_logging_config(path: str | Path | None = None) -> LoggingConfig:
    config_path = Path(path).expanduser() if path else default_config_path()
    parser = configparser.ConfigParser()
    parser.read(config_path)
    sink = parser.get("logging", "sink", fallback="file")
    if sink not in {"file", "syslog", "journal", "opensearch"}:
        raise ValueError(f"Unknown [logging] sink: {sink!r}")

    opensearch_cfg = None
    if parser.has_section("logging.opensearch"):
        section = parser["logging.opensearch"]
        if "url" not in section:
            raise KeyError("[logging.opensearch] requires 'url'")
        opensearch_cfg = OpenSearchSinkConfig(
            url=section["url"],
            index=section.get("index", "plexadm-audit"),
            username=section.get("username"),
            password=section.get("password"),
            verify_tls=section.getboolean("verify_tls", fallback=True),
        )
    elif sink == "opensearch":
        raise KeyError("sink = opensearch requires a [logging.opensearch] section")

    file_defaults = FileSinkConfig()
    return LoggingConfig(
        sink=sink,
        file=FileSinkConfig(
            path=Path(parser.get("logging.file", "path", fallback=str(file_defaults.path))).expanduser(),
            max_bytes=parser.getint("logging.file", "max_bytes", fallback=file_defaults.max_bytes),
            backup_count=parser.getint("logging.file", "backup_count", fallback=file_defaults.backup_count),
        ),
        syslog=SyslogSinkConfig(
            address=parser.get("logging.syslog", "address", fallback="/dev/log"),
            facility=parser.get("logging.syslog", "facility", fallback="user"),
        ),
        journal=JournalSinkConfig(identifier=parser.get("logging.journal", "identifier", fallback="plexadm")),
        opensearch=opensearch_cfg,
        quiet_opensearch_log=resolve_bool_setting(
            "PLEXADM_QUIET_OPENSEARCH_LOG",
            parser.getboolean("logging", "quiet_opensearch_log", fallback=True),
        ),
    )


def load_inventory_config(path: str | Path | None = None) -> InventoryConfig | None:
    """Independent of the [logging] sink choice - audit logging can stay on file/syslog/journal
    while inventory snapshots still go to OpenSearch (or vice versa), since they answer different
    questions: audit is "what did plexadm do", inventory is "what does the state actually look
    like right now, regardless of what changed it"."""
    config_path = Path(path).expanduser() if path else default_config_path()
    parser = configparser.ConfigParser()
    parser.read(config_path)
    if not parser.has_section("inventory"):
        return None
    section = parser["inventory"]
    if "url" not in section:
        raise KeyError("[inventory] section requires 'url'")
    return InventoryConfig(
        url=section["url"],
        index=section.get("index", "plexadm-inventory"),
        username=section.get("username"),
        password=section.get("password"),
        verify_tls=section.getboolean("verify_tls", fallback=True),
    )
