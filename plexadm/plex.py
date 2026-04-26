from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from plexapi.server import PlexServer

from plexadm.config import PlexConfig, load_config


class PlexContext:
    def __init__(self, config: PlexConfig):
        self.config = config
        self.server = PlexServer(config.base_url, config.token)
        self.section = self.server.library.section(config.section_name)

    @classmethod
    def from_config(cls, config_path: str | None = None) -> PlexContext:
        return cls(load_config(config_path))

    def collection(self, name: str) -> Any:
        collection = self.section.collection(name)
        if str(collection.title).lower() != name.lower():
            raise LookupError(f"Collection '{name}' not found")
        return collection

    def all_videos(self, *, reload: bool = False) -> list[Any]:
        videos = list(self.section.all())
        if reload:
            for video in videos:
                reload_if_partial(video, force=True)
        return videos

    def search(
        self, *, filters: dict[str, Any] | None = None, sort: str = "titleSort", reload: bool = False, **kwargs: Any
    ) -> list[Any]:
        videos = list(self.section.search(filters=filters, sort=sort, **kwargs))
        if reload:
            for video in videos:
                reload_if_partial(video)
        return videos


def reload_if_partial(item: Any, *, force: bool = False) -> Any:
    if force:
        item.reload()
        return item
    is_partial = getattr(item, "isPartialObject", None)
    if callable(is_partial) and is_partial():
        item.reload()
    return item


def collection_titles(video: Any) -> set[str]:
    return {str(collection) for collection in getattr(video, "collections", []) or []}


def has_collection(video: Any, name: str) -> bool:
    wanted = name.lower()
    return any(title.lower() == wanted for title in collection_titles(video))


def add_items(collection: Any, items: Iterable[Any]) -> int:
    item_list = list(items)
    if item_list:
        collection.addItems(item_list)
    return len(item_list)


def remove_items(collection: Any, items: Iterable[Any]) -> int:
    item_list = list(items)
    if item_list:
        collection.removeItems(item_list)
    return len(item_list)
