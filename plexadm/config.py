from __future__ import annotations

import configparser
import os
from dataclasses import dataclass
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
