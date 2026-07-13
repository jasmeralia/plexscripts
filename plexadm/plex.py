from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from plexapi.server import PlexServer

from plexadm.audit import AuditEvent, log_event
from plexadm.config import PlexConfig, load_config
from plexadm.console import warn

LOCKED_COLLECTION = "99: LOCKED"


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


def _drop_locked(items: list[Any]) -> list[Any]:
    """Filter out videos tagged '99: LOCKED' - that tag means plexadm must never add or
    remove any of the video's collection memberships, regardless of which command is
    asking. Checked once here rather than per-command so the guarantee holds for every
    caller, present and future."""
    kept = []
    for item in items:
        reload_if_partial(item)
        if has_collection(item, LOCKED_COLLECTION):
            print(warn(f"Skipping '{item.title}' - locked ('{LOCKED_COLLECTION}')"))
            continue
        kept.append(item)
    return kept


def add_items(collection: Any, items: Iterable[Any], *, dry_run: bool = False) -> int:
    item_list = list(items)
    if str(collection.title) != LOCKED_COLLECTION:
        item_list = _drop_locked(item_list)
    if item_list and not dry_run:
        collection.addItems(item_list)
        for item in item_list:
            log_event(
                AuditEvent(
                    action="add",
                    title=item.title,
                    rating_key=getattr(item, "ratingKey", None),
                    collection=str(collection.title),
                )
            )
    return len(item_list)


def remove_items(collection: Any, items: Iterable[Any], *, dry_run: bool = False) -> int:
    item_list = list(items)
    if str(collection.title) != LOCKED_COLLECTION:
        item_list = _drop_locked(item_list)
    if item_list and not dry_run:
        collection.removeItems(item_list)
        for item in item_list:
            log_event(
                AuditEvent(
                    action="remove",
                    title=item.title,
                    rating_key=getattr(item, "ratingKey", None),
                    collection=str(collection.title),
                )
            )
    return len(item_list)


def set_studio(video: Any, studio: str, *, dry_run: bool = False) -> bool:
    if has_collection(video, LOCKED_COLLECTION):
        print(warn(f"Skipping '{video.title}' - locked ('{LOCKED_COLLECTION}')"))
        return False
    if dry_run:
        return True
    old_studio = getattr(video, "studio", None)
    video.edit(**{"studio.value": studio, "label.locked": 1})
    log_event(
        AuditEvent(
            action="edit_studio",
            title=video.title,
            rating_key=getattr(video, "ratingKey", None),
            details={"old_studio": old_studio, "new_studio": studio},
        )
    )
    return True


def add_writer(video: Any, writer_names: list[str], *, dry_run: bool = False) -> bool:
    if has_collection(video, LOCKED_COLLECTION):
        print(warn(f"Skipping '{video.title}' - locked ('{LOCKED_COLLECTION}')"))
        return False
    if dry_run:
        return True
    video.addWriter(writer_names, True)
    log_event(
        AuditEvent(
            action="add_writer",
            title=video.title,
            rating_key=getattr(video, "ratingKey", None),
            details={"writers": writer_names},
        )
    )
    return True


def rename_collection(collection: Any, new_title: str, *, dry_run: bool = False) -> None:
    old_title = str(collection.title)
    if dry_run:
        return
    collection.editTitle(new_title)
    log_event(AuditEvent(action="rename_collection", title=new_title, details={"old_title": old_title}))


def create_smart_collection(
    section: Any,
    *,
    title: str,
    sort: str,
    filters: dict[str, Any],
    dry_run: bool = False,
) -> None:
    if dry_run:
        return
    section.createCollection(title=title, smart=True, sort=sort, filters=filters)
    log_event(AuditEvent(action="create_collection", title=title, details={"filters": filters}))
