from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def and_filter(*parts: dict[str, Any]) -> dict[str, Any]:
    return {"and": [part for part in parts if part]}


def or_filter(*parts: dict[str, Any]) -> dict[str, Any]:
    return {"or": [part for part in parts if part]}


def writer_any(names: Iterable[str]) -> dict[str, Any]:
    return or_filter(*({"writer": name} for name in names if name))


def title_contains(pattern: str) -> dict[str, str]:
    return {"title": pattern}


def in_collection(name: str) -> dict[str, str]:
    return {"collection": name}


def not_in_collection(name: str) -> dict[str, str]:
    return {"collection!": name}


def no_studio() -> dict[str, str]:
    return {"studio__exact": ""}


def unrated() -> dict[str, int]:
    return {"userRating": -1}


def rated() -> dict[str, int]:
    return {"userRating>>": 0}
