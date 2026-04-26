from __future__ import annotations

from pathlib import Path
from typing import Any


def normalize_title(title: str) -> str:
    return title.replace(" - ", " - ").replace(" – ", " - ").replace("\xa0", " ")


def writers_from_title(title: str) -> list[str]:
    writer_segment = normalize_title(title).split(" - ", 1)[0]
    return sorted({writer.strip() for writer in writer_segment.split(",") if writer.strip()})


def read_writer_file(path: str | Path) -> list[str]:
    return [line.strip() for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def writer_names(video: Any) -> set[str]:
    return {str(writer).strip().lower() for writer in getattr(video, "writers", []) or []}


def missing_title_writers(video: Any) -> list[str]:
    existing = writer_names(video)
    return [writer for writer in writers_from_title(video.title) if writer.lower() not in existing]
