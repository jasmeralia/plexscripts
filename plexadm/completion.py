from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

COMPLETION_CACHE = Path(".plexadm/completion-cache.json")


def completion_cache_path() -> Path:
    return Path.home() / COMPLETION_CACHE


def load_completion_cache() -> dict[str, list[str]]:
    """Read cached Plex names without ever making shell completion fail."""
    try:
        data = json.loads(completion_cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {key: value for key, value in data.items() if isinstance(value, list)}


def _complete_names(kind: str, prefix: str) -> list[str]:
    needle = prefix.casefold()
    return [
        name
        for name in load_completion_cache().get(kind, [])
        if isinstance(name, str) and name.casefold().startswith(needle)
    ]


def complete_collections(prefix: str, **_: Any) -> list[str]:
    return _complete_names("collections", prefix)


def complete_studios(prefix: str, **_: Any) -> list[str]:
    return _complete_names("studios", prefix)


def complete_writers(prefix: str, **_: Any) -> list[str]:
    return _complete_names("writers", prefix)


def write_completion_cache(ctx: Any) -> Path:
    collections = {
        str(collection.title) for collection in ctx.section.collections() if getattr(collection, "title", None)
    }
    studios: set[str] = set()
    writers: set[str] = set()
    for video in ctx.all_videos():
        studio = getattr(video, "studio", None)
        if studio:
            studios.add(str(studio))
        writers.update(str(writer) for writer in (getattr(video, "writers", None) or []) if writer)

    data = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "collections": sorted(collections, key=str.casefold),
        "studios": sorted(studios, key=str.casefold),
        "writers": sorted(writers, key=str.casefold),
    }
    path = completion_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path
