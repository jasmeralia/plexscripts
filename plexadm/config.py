from __future__ import annotations

import configparser
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


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
    )
