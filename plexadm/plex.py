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


def _mutation_level_and_details(dry_run: bool, details: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if dry_run:
        return "DEBUG", {**details, "dry_run": True}
    return "INFO", details


def add_items(collection: Any, items: Iterable[Any], *, dry_run: bool = False) -> int:
    item_list = list(items)
    if str(collection.title) != LOCKED_COLLECTION:
        item_list = _drop_locked(item_list)
    if item_list:
        if not dry_run:
            collection.addItems(item_list)
        level, details = _mutation_level_and_details(dry_run, {})
        for item in item_list:
            log_event(
                AuditEvent(
                    action="add",
                    level=level,
                    title=item.title,
                    rating_key=getattr(item, "ratingKey", None),
                    collection=str(collection.title),
                    details=details,
                )
            )
    return len(item_list)


def remove_items(collection: Any, items: Iterable[Any], *, dry_run: bool = False) -> int:
    item_list = list(items)
    if str(collection.title) != LOCKED_COLLECTION:
        item_list = _drop_locked(item_list)
    if item_list:
        if not dry_run:
            collection.removeItems(item_list)
        level, details = _mutation_level_and_details(dry_run, {})
        for item in item_list:
            log_event(
                AuditEvent(
                    action="remove",
                    level=level,
                    title=item.title,
                    rating_key=getattr(item, "ratingKey", None),
                    collection=str(collection.title),
                    details=details,
                )
            )
    return len(item_list)


def set_studio(video: Any, studio: str, *, dry_run: bool = False) -> bool:
    if has_collection(video, LOCKED_COLLECTION):
        print(warn(f"Skipping '{video.title}' - locked ('{LOCKED_COLLECTION}')"))
        return False
    old_studio = getattr(video, "studio", None)
    if not dry_run:
        video.edit(**{"studio.value": studio, "label.locked": 1})
    level, details = _mutation_level_and_details(dry_run, {"old_studio": old_studio, "new_studio": studio})
    log_event(
        AuditEvent(
            action="edit_studio",
            level=level,
            title=video.title,
            rating_key=getattr(video, "ratingKey", None),
            details=details,
        )
    )
    return True


def lock_title_and_sort_title(video: Any, *, dry_run: bool = False) -> bool:
    """Lock title and sort title to their current values, so agent refresh/matching can't
    silently overwrite manually-curated titles (e.g. merged-duplicate items whose title was
    picked by hand from among several release names)."""
    if has_collection(video, LOCKED_COLLECTION):
        print(warn(f"Skipping '{video.title}' - locked ('{LOCKED_COLLECTION}')"))
        return False
    title = str(video.title)
    sort_title = str(getattr(video, "titleSort", None) or title)
    if not dry_run:
        video.edit(**{"title.value": title, "title.locked": 1, "titleSort.value": sort_title, "titleSort.locked": 1})
    level, details = _mutation_level_and_details(dry_run, {"title": title, "sort_title": sort_title})
    log_event(
        AuditEvent(
            action="lock_title",
            level=level,
            title=video.title,
            rating_key=getattr(video, "ratingKey", None),
            details=details,
        )
    )
    return True


def add_writer(video: Any, writer_names: list[str], *, dry_run: bool = False) -> bool:
    if has_collection(video, LOCKED_COLLECTION):
        print(warn(f"Skipping '{video.title}' - locked ('{LOCKED_COLLECTION}')"))
        return False
    if not dry_run:
        video.addWriter(writer_names, True)
    level, details = _mutation_level_and_details(dry_run, {"writers": writer_names})
    log_event(
        AuditEvent(
            action="add_writer",
            level=level,
            title=video.title,
            rating_key=getattr(video, "ratingKey", None),
            details=details,
        )
    )
    return True


def rename_collection(collection: Any, new_title: str, *, dry_run: bool = False) -> None:
    """Rename a collection's title AND sort title together.

    Real bug found live: the taxonomy migration's bulk rename only ever called editTitle(),
    leaving every renamed collection's titleSort pointing at its old name - e.g. "01: Activity:
    Anal" sorted as "01: Category: Anal", grouping it with collections it no longer belongs
    with. A rename with no sort_title override always means "this is now called X", so title and
    sort title should always move together unless a caller explicitly wants something else.
    """
    old_title = str(collection.title)
    if not dry_run:
        collection.editTitle(new_title)
        collection.editSortTitle(new_title)
    level, details = _mutation_level_and_details(dry_run, {"old_title": old_title})
    log_event(AuditEvent(action="rename_collection", level=level, title=new_title, details=details))


def _resolve_collection_filter(section: Any, filters: dict[str, Any]) -> dict[str, Any]:
    """Resolve a "collection" smart-filter value given as a title string to the ID Plex's smart
    filter query language actually expects.

    That ID comes from `section.listFilterChoices("collection")` - a *different* ID space from
    the collection's own `.ratingKey`. Confirmed live: passing `.ratingKey` doesn't error, it
    silently matches a different, unrelated collection instead (a 5-item one instead of the
    intended 1985-item one), which is a much worse failure mode than a clear error. Callers
    should always pass the collection's title as a plain string here, the same way "writer" and
    "studio" filters already take plain name strings elsewhere in this file - if a caller passes
    an int, it's trusted as already-resolved and left untouched.
    """
    if "collection" not in filters or not isinstance(filters["collection"], str):
        return filters
    title = filters["collection"]
    matches = [choice.key for choice in section.listFilterChoices("collection") if choice.title == title]
    if not matches:
        raise ValueError(f"No collection filter choice found for {title!r} - check the title is exact.")
    if len(matches) > 1:
        raise ValueError(f"Multiple collection filter choices found for {title!r} - expected exactly one.")
    return {**filters, "collection": matches[0]}


def create_smart_collection(
    section: Any,
    *,
    title: str,
    sort: str,
    filters: dict[str, Any],
    dry_run: bool = False,
) -> None:
    filters = _resolve_collection_filter(section, filters)
    if not dry_run:
        section.createCollection(title=title, smart=True, sort=sort, filters=filters)
    level, details = _mutation_level_and_details(dry_run, {"filters": filters})
    log_event(AuditEvent(action="create_collection", level=level, title=title, details=details))
