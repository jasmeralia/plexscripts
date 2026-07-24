from __future__ import annotations

import argparse
import fnmatch
import json
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

from plexadm import __version__, audit
from plexadm.config import load_inventory_config, load_logging_config
from plexadm.console import fail, info, ok, warn
from plexadm.filters import and_filter, in_collection, not_in_collection, rated, title_contains, unrated, writer_any
from plexadm.plex import (
    LOCKED_COLLECTION,
    PlexContext,
    add_items,
    add_writer,
    collection_filter_key,
    collection_titles,
    create_smart_collection,
    has_collection,
    lock_title_and_sort_title,
    reload_if_partial,
    remove_items,
    rename_collection,
    set_studio,
    update_smart_collection_filters,
)
from plexadm.progress import progress_prefix
from plexadm.stash_reconcile import reconcile as stash_reconcile
from plexadm.stash_sync_tags import sync_tags as stash_sync_tags
from plexadm.writers import missing_title_writers, read_writer_file, writers_from_title

NO_STUDIO_COLLECTION = "00A: NO STUDIO"
UNRATED_COLLECTION = "00C: Unrated"
INDEPENDENT_STUDIO = "Independent Content"
LESBIAN_COLLECTION = "01: Composition: Lesbian"
LESBIAN_SINGLE_WRITER_REVIEW_COLLECTION = "00D: Review: Lesbian Single-Writer"
CUMSHOT_ABSENT_REVIEW_COLLECTION = "00D: Review: Cumshot Absent"
PPV_COLLECTION = "01: Category: PPV"
PPV_FILENAME_PATTERN = "*- PPV *"
DEFAULT_SHORT_VIDEO_MAX_DURATION_MS = 90_000

# The "01: Category:" taxonomy is being split into narrower prefixes (see
# `plexadm collection rename-categories` / stash_backfill_tags._EXISTING_CATEGORY_RENAMES).
# Anything that used to recognize a collection as "a category" by checking for a literal
# "01: Category:" substring needs to check this whole family instead, or it'll silently stop
# seeing most collections once they're renamed. Deliberately excludes "01: Hair:" - hair is a
# separate axis, not part of the category taxonomy, same as before the rename.
CATEGORY_TAXONOMY_PREFIXES = (
    "01: Category:",
    "01: Activity:",
    "01: Attributes:",
    "01: Composition:",
    "01: Cumshot:",
    "01: Prop:",
    "01: Theme:",
)

EXCLUDED_COMPOSITION_COLLECTIONS = [
    "01: Category: FFF+",
    "01: Category: FFFM",
    "01: Category: FFM",
    "01: Category: FFT",
    "01: Category: Gangbang",
    "01: Category: MF Only",
    "01: Category: MMF",
    "01: Category: Non-Sexual",
    "01: Category: Orgy",
    "01: Category: Reverse Gangbang",
    "01: Category: Solo",
]

EXCLUDED_HAIR_COLLECTIONS = [
    "01: Hair: Black",
    "01: Hair: Blonde",
    "01: Hair: Blue",
    "01: Hair: Brunette",
    "01: Hair: Green",
    "01: Hair: Pink",
    "01: Hair: Purple",
    "01: Hair: Red",
    "01: Hair: Silver",
    "01: Hair: White",
    "01: Hair: Unknown",
]


def build_context(args: argparse.Namespace) -> PlexContext:
    return PlexContext.from_config(args.config)


def print_title(video: Any) -> None:
    print(f"Title: {video.title}")


def is_scene(video: Any) -> bool:
    return " (Scene #" in video.title


def video_matches_text(video: Any, pattern: str, *, startswith: bool = False) -> bool:
    title = video.title.lower()
    needle = pattern.lower()
    return title.startswith(needle) if startswith else needle in title


def video_has_exact_writer(video: Any, name: str) -> bool:
    return any(str(writer).lower() == name.lower() for writer in getattr(video, "writers", []) or [])


def add_matching_titles(args: argparse.Namespace) -> int:
    ctx = build_context(args)
    collection = ctx.collection(args.collection)
    matches = []
    matched_count = 0
    for video in ctx.all_videos():
        if args.skip_scenes and is_scene(video):
            continue
        if video_matches_text(video, args.pattern, startswith=args.startswith):
            reload_if_partial(video, force=True)
            matched_count += 1
            if not has_collection(video, collection.title):
                print(warn(f"'{video.title}' needs to be added to '{collection.title}'"))
                matches.append(video)
            else:
                print(info(f"'{video.title}' is already part of '{collection.title}'"))
    added = add_items(collection, matches, dry_run=args.dry_run)
    print(info(f"{matched_count} matches found, {added} collections added.{dry_run_note(args)}"))
    return 0


def add_search_results(args: argparse.Namespace) -> int:
    ctx = build_context(args)
    collection = ctx.collection(args.collection)
    exclusions = [not_in_collection(name) for name in args.exclude_collection or []]
    filters = and_filter(not_in_collection(collection.title), title_contains(args.pattern), *exclusions)
    print(info(f"Search filters: {filters}"))
    results = ctx.search(filters=filters, reload=True)
    prefixes = tuple(args.exclude_collection_prefix or [])
    if prefixes:
        # Plex's smart-filter DSL matches one specific collection at a time, not a text prefix -
        # there's no "collection! " filter that works across a whole family at once, so this has
        # to happen client-side against each video's already-reloaded collection list.
        results = [
            video for video in results if not any(title.startswith(prefixes) for title in collection_titles(video))
        ]
    for index, video in enumerate(results, 1):
        print(warn(f"{progress_prefix(index, len(results))}'{video.title}' needs to be added to '{collection.title}'"))
    added = add_items(collection, results, dry_run=args.dry_run)
    print(info(f"{len(results)} matches found, {added} collections added.{dry_run_note(args)}"))
    return 0


def add_writer_matches(args: argparse.Namespace) -> int:
    ctx = build_context(args)
    collection = ctx.collection(args.collection)
    matches = []
    matched_count = 0
    for video in ctx.all_videos():
        if args.pattern.lower() in video.title.lower():
            reload_if_partial(video, force=True)
            if video_has_exact_writer(video, args.pattern):
                matched_count += 1
                if not has_collection(video, collection.title):
                    print(warn(f"'{video.title}' needs to be added to '{collection.title}'"))
                    matches.append(video)
    added = add_items(collection, matches, dry_run=args.dry_run)
    print(info(f"{matched_count} matches found, {added} collections added.{dry_run_note(args)}"))
    return 0


def add_writers_file(args: argparse.Namespace) -> int:
    ctx = build_context(args)
    collection = ctx.collection(args.collection)
    writers = read_writer_file(args.file)
    filters = and_filter(not_in_collection(collection.title), not_in_collection(LOCKED_COLLECTION), writer_any(writers))
    print(info(f"Search filters: {filters}"))
    results = ctx.search(filters=filters, reload=True)
    if args.single_writer_only:
        # Plex has no "writer count" smart filter, so a listed writer (e.g. a Solo performer)
        # who happens to co-star in a multi-writer scene would otherwise get that scene tagged
        # Solo too - filter it out here in Python instead.
        results = [video for video in results if len(getattr(video, "writers", None) or []) == 1]
    for index, video in enumerate(results, 1):
        print(warn(f"{progress_prefix(index, len(results))}'{video.title}' needs to be added to '{collection.title}'"))
    added = add_items(collection, results, dry_run=args.dry_run)
    print(info(f"{len(results)} matches found, {added} collections added.{dry_run_note(args)}"))
    return 0


def copy_collection(args: argparse.Namespace) -> int:
    ctx = build_context(args)
    source = ctx.collection(args.source)
    target = ctx.collection(args.target)
    filters = and_filter(in_collection(source.title), not_in_collection(target.title))
    results = ctx.search(filters=filters, reload=True)
    for index, video in enumerate(results, 1):
        print(warn(f"{progress_prefix(index, len(results))}'{video.title}' needs to be added to '{target.title}'"))
    added = add_items(target, results, dry_run=args.dry_run)
    print(info(f"{len(results)} matches found, {added} collections added.{dry_run_note(args)}"))
    return 0


def copy_studio(args: argparse.Namespace) -> int:
    ctx = build_context(args)
    target = ctx.collection(args.collection)
    filters = and_filter({"studio": args.studio}, not_in_collection(target.title))
    results = ctx.search(filters=filters, reload=True)
    for index, video in enumerate(results, 1):
        print(warn(f"{progress_prefix(index, len(results))}'{video.title}' needs to be added to '{target.title}'"))
    added = add_items(target, results, dry_run=args.dry_run)
    print(info(f"{len(results)} matches found, {added} collections added.{dry_run_note(args)}"))
    return 0


def remove_matching_titles(args: argparse.Namespace) -> int:
    ctx = build_context(args)
    collection = ctx.collection(args.collection)
    matches = []
    for video in ctx.all_videos():
        if video_matches_text(video, args.pattern):
            reload_if_partial(video, force=True)
            if has_collection(video, collection.title):
                print(warn(f"'{video.title}' needs to be removed from '{collection.title}'"))
                matches.append(video)
    removed = remove_items(collection, matches, dry_run=args.dry_run)
    print(info(f"{len(matches)} matches found, {removed} collections removed.{dry_run_note(args)}"))
    return 0


def add_duration_collection(args: argparse.Namespace) -> int:
    ctx = build_context(args)
    collection = ctx.collection(args.collection)
    max_duration_ms = args.max_duration_ms
    min_duration_ms = args.min_duration_ms
    if max_duration_ms is None and min_duration_ms is None:
        # Neither bound given: preserve add-short's original behavior (short videos only).
        max_duration_ms = DEFAULT_SHORT_VIDEO_MAX_DURATION_MS
    extra_filters = json.loads(args.filters) if args.filters else {}
    parts: list[dict[str, Any]] = []
    if max_duration_ms is not None:
        parts.append({"duration<<": max_duration_ms})
    if min_duration_ms is not None:
        parts.append({"duration>>": min_duration_ms})
    parts.extend({key: value} for key, value in extra_filters.items())
    parts.append(not_in_collection(collection.title))
    results = ctx.search(filters=and_filter(*parts), reload=True)
    for video in results:
        print(warn(f"'{video.title}' needs to be added to '{collection.title}'"))
    added = add_items(collection, results, dry_run=args.dry_run)
    print(info(f"{added} videos added to '{collection.title}'.{dry_run_note(args)}"))
    return 0


def add_orgy_collection(args: argparse.Namespace) -> int:
    ctx = build_context(args)
    collection = ctx.collection(args.collection)
    results = ctx.search(filters=not_in_collection(collection.title), reload=True)
    matches = []
    for video in results:
        writers = getattr(video, "writers", None) or []
        if len(writers) >= args.min_writers:
            print(warn(f"'{video.title}' needs to be added to '{collection.title}'"))
            matches.append(video)
    added = add_items(collection, matches, dry_run=args.dry_run)
    print(info(f"{added} videos added to '{collection.title}'.{dry_run_note(args)}"))
    return 0


def add_vertical_collection(args: argparse.Namespace) -> int:
    ctx = build_context(args)
    collection = ctx.collection(args.collection)
    results = ctx.search(filters=not_in_collection(collection.title), reload=True)
    matches = []
    for video in results:
        media = (getattr(video, "media", None) or [None])[0]
        width = getattr(media, "width", 0) or 0
        height = getattr(media, "height", 0) or 0
        if height > width:
            print(warn(f"'{video.title}' needs to be added to '{collection.title}'"))
            matches.append(video)
    added = add_items(collection, matches, dry_run=args.dry_run)
    print(info(f"{added} vertical videos added to '{collection.title}'.{dry_run_note(args)}"))
    return 0


def sync_unrated(args: argparse.Namespace) -> int:
    ctx = build_context(args)
    collection = ctx.collection(args.collection)
    to_add = ctx.search(filters=and_filter(unrated(), not_in_collection(collection.title)), reload=True)
    to_remove = ctx.search(filters=and_filter(rated(), {"collection=": collection.title}), reload=True)
    for video in to_add:
        print(warn(f"'{video.title}' needs to be added to '{collection.title}'"))
    for video in to_remove:
        print(warn(f"'{video.title}' needs to be removed from '{collection.title}'"))
    added = add_items(collection, to_add, dry_run=args.dry_run)
    removed = remove_items(collection, to_remove, dry_run=args.dry_run)
    print(info(f"{added} collections added.{dry_run_note(args)}"))
    print(info(f"{removed} collections removed.{dry_run_note(args)}"))
    return 0


def sync_no_studio(args: argparse.Namespace) -> int:
    ctx = build_context(args)
    collection = ctx.collection(args.collection)
    to_add = ctx.search(studio__exact="", sort="titleSort", reload=True)
    to_add = [video for video in to_add if not has_collection(video, collection.title)]
    # Plex's advanced dict-filter syntax ("studio!": "") silently returns zero results for this
    # field, regardless of how many videos actually have a studio set - confirmed live against
    # the real library (a kwarg-style studio__ne="" query correctly found real victims that the
    # dict form missed). Use the kwarg form instead; it can be combined with the dict-style
    # collection filter in the same search() call.
    to_remove = ctx.search(filters={"collection=": collection.title}, studio__ne="", reload=True)
    for video in to_add:
        print(warn(f"'{video.title}' needs to be added to '{collection.title}'"))
    for video in to_remove:
        print(warn(f"'{video.title}' needs to be removed from '{collection.title}'"))
    added = add_items(collection, to_add, dry_run=args.dry_run)
    removed = remove_items(collection, to_remove, dry_run=args.dry_run)
    print(info(f"{added} collections added.{dry_run_note(args)}"))
    print(info(f"{removed} collections removed.{dry_run_note(args)}"))
    return 0


def _matches_ppv_filename(video: Any) -> bool:
    """Plex has no native filter for filename/file path, only metadata fields - so unlike
    the other sync-* commands, this check has to happen in Python against each media part's
    filename rather than being expressible as a search filter."""
    locations = list(getattr(video, "locations", None) or [])
    return any(fnmatch.fnmatchcase(Path(location).name, PPV_FILENAME_PATTERN) for location in locations)


def add_ppv(args: argparse.Namespace) -> int:
    """Add-only: a filename that stops matching the PPV pattern (e.g. after a manual rename
    away from a platform's raw export name) does not mean the content stopped being valid PPV
    content - some legitimate PPV sources (e.g. MFC) just don't get exported with that naming
    convention. Removing on filename-mismatch alone was flagging real PPV videos for removal,
    so this only ever adds, never removes."""
    ctx = build_context(args)
    collection = ctx.collection(args.collection)
    to_add = ctx.search(filters=not_in_collection(collection.title), reload=True)
    to_add = [video for video in to_add if _matches_ppv_filename(video)]
    for video in to_add:
        print(warn(f"'{video.title}' needs to be added to '{collection.title}'"))
    added = add_items(collection, to_add, dry_run=args.dry_run)
    print(info(f"{added} collections added.{dry_run_note(args)}"))
    return 0


def lock_collection_titles(args: argparse.Namespace) -> int:
    ctx = build_context(args)
    collection = ctx.collection(args.collection)
    items = collection.items()
    for video in items:
        reload_if_partial(video, force=True)
    locked = 0
    for video in items:
        print(warn(f"'{video.title}' needs title/sort title locked"))
        if lock_title_and_sort_title(video, dry_run=args.dry_run):
            locked += 1
    print(info(f"{locked} of {len(items)} items had title/sort title locked.{dry_run_note(args)}"))
    return 0


def rename_categories(args: argparse.Namespace) -> int:
    # Local import: stash_backfill_tags imports EXCLUDED_COMPOSITION_COLLECTIONS/
    # EXCLUDED_HAIR_COLLECTIONS from this module, so a top-level import here would be circular.
    from plexadm.stash_backfill_tags import _EXISTING_CATEGORY_RENAMES, COMPOSITION_COLLECTIONS

    ctx = build_context(args)
    existing = {str(collection.title): collection for collection in ctx.section.collections()}
    renamed = 0
    skipped_composition = 0
    for old, new in sorted(_EXISTING_CATEGORY_RENAMES.items()):
        if old == new or old not in existing:
            continue
        if old in COMPOSITION_COLLECTIONS and not args.include_composition:
            skipped_composition += 1
            continue
        print(warn(f"'{old}' needs to be renamed to '{new}'"))
        rename_collection(existing[old], new, dry_run=args.dry_run)
        renamed += 1
    print(info(f"{renamed} collections renamed.{dry_run_note(args)}"))
    if skipped_composition:
        print(
            warn(
                f"{skipped_composition} composition collections skipped (Stash tags aren't renamed "
                "yet, so backfill-tags matching would break - pass --include-composition once "
                "that's handled)."
            )
        )
    return 0


def sync_lesbian_single_writer(args: argparse.Namespace) -> int:
    """Flag '01: Composition: Lesbian' members with exactly one credited writer - a lone
    credited performer is a strong signal the 'Lesbian' tag is wrong, since lesbian
    content normally credits two or more female performers in the title. Applies
    regardless of studio, including Independent Content: solo indie creators are
    exactly the kind of single-writer/no-partner case this should also catch. This is
    a review/cataloging collection only: it never touches '01: Composition: Lesbian'
    membership itself."""
    ctx = build_context(args)
    collection = ctx.collection(args.collection)
    lesbian_members = ctx.search(filters=in_collection(LESBIAN_COLLECTION), reload=True)
    matches = [video for video in lesbian_members if len(getattr(video, "writers", None) or []) == 1]
    match_keys = {video.ratingKey for video in matches}
    to_add = [video for video in matches if not has_collection(video, collection.title)]
    current_members = ctx.search(filters=in_collection(collection.title), reload=True)
    to_remove = [video for video in current_members if video.ratingKey not in match_keys]
    for video in to_add:
        print(warn(f"'{video.title}' needs to be added to '{collection.title}'"))
    for video in to_remove:
        print(warn(f"'{video.title}' needs to be removed from '{collection.title}'"))
    added = add_items(collection, to_add, dry_run=args.dry_run)
    removed = remove_items(collection, to_remove, dry_run=args.dry_run)
    print(info(f"{added} collections added.{dry_run_note(args)}"))
    print(info(f"{removed} collections removed.{dry_run_note(args)}"))
    return 0


def _cumshot_absent_exclusion_names() -> set[str]:
    # Local import: stash_backfill_tags imports EXCLUDED_COMPOSITION_COLLECTIONS/
    # EXCLUDED_HAIR_COLLECTIONS from this module, so a top-level import here would be circular.
    from plexadm.stash_backfill_tags import _EXISTING_CATEGORY_RENAMES

    # Both the pre- and post-rename_categories() name for every Cumshot collection, so this
    # works correctly whether or not that migration has run yet.
    cumshot_names = {
        name
        for old, new in _EXISTING_CATEGORY_RENAMES.items()
        if new.startswith("01: Cumshot: ")
        for name in (old, new)
    }
    # "No male performer present" - a cumshot (in the sense this review collection cares
    # about) structurally can't happen. Solo/Lesbian are real, populated collections today;
    # FF Only/Female Only don't exist yet (no backfill logic populates them yet) but are
    # included so this starts excluding them automatically once they do.
    female_only_names = {
        "01: Category: Solo",
        "01: Category: Lesbian",
        "01: Composition: Solo",
        "01: Composition: Lesbian",
        "01: Composition: FF Only",
        "01: Composition: Female Only",
    }
    non_sexual_names = {"01: Category: Non-Sexual"}
    # A compilation aggregates clips from many separate sources/scenes, so it isn't expected to
    # carry one single cumshot tag the way a normal scene would.
    compilation_names = {"01: Category: Compilation"}
    return cumshot_names | female_only_names | non_sexual_names | compilation_names


def sync_cumshot_absent(args: argparse.Namespace) -> int:
    """Flag sexual, non-female-only videos with no Cumshot-collection membership for review -
    likely either missing a cumshot tag entirely or a case the exclusions below should have
    caught but didn't. This is a review/cataloging collection only: it never touches Cumshot
    collection membership itself."""
    excluded_names = _cumshot_absent_exclusion_names()
    ctx = build_context(args)
    collection = ctx.collection(args.collection)
    exclusion_filters = [not_in_collection(name) for name in sorted(excluded_names)]
    to_add = ctx.search(filters=and_filter(*exclusion_filters, not_in_collection(collection.title)), reload=True)
    current_members = ctx.search(filters=in_collection(collection.title), reload=True)
    to_remove = [video for video in current_members if collection_titles(video) & excluded_names]
    for video in to_add:
        print(warn(f"'{video.title}' needs to be added to '{collection.title}'"))
    for video in to_remove:
        print(warn(f"'{video.title}' needs to be removed from '{collection.title}'"))
    added = add_items(collection, to_add, dry_run=args.dry_run)
    removed = remove_items(collection, to_remove, dry_run=args.dry_run)
    print(info(f"{added} collections added.{dry_run_note(args)}"))
    print(info(f"{removed} collections removed.{dry_run_note(args)}"))
    return 0


def set_studio_for_title_matches(args: argparse.Namespace) -> int:
    ctx = build_context(args)
    changed = 0
    matched = 0
    for video in ctx.all_videos():
        if args.pattern.lower() not in video.title.lower():
            continue
        reload_if_partial(video, force=True)
        if args.require_writer and not video_has_exact_writer(video, args.pattern):
            continue
        if args.skip_scenes and is_scene(video):
            continue
        matched += 1
        if not getattr(video, "studio", None):
            print(warn(f"'{video.title}' needs to be added to '{args.studio}'"))
            if set_studio(video, args.studio, dry_run=args.dry_run):
                changed += 1
        elif video.studio == args.studio:
            print(info(f"'{video.title}' is already part of '{args.studio}'"))
        else:
            print(warn(f"'{video.title}' already belongs to studio '{video.studio}', skipping."))
    print(info(f"{matched} matches found, {changed} studios added.{dry_run_note(args)}"))
    return 0


def set_independent_for_writers_file(args: argparse.Namespace) -> int:
    ctx = build_context(args)
    writers = read_writer_file(args.file)
    results = ctx.search(studio__exact="", sort="titleSort", reload=False)
    changed = 0
    for video in results:
        if not any(writer.lower() in video.title.lower() for writer in writers):
            continue
        reload_if_partial(video)
        if is_scene(video):
            continue
        matched_writer = next((writer for writer in writers if video_has_exact_writer(video, writer)), None)
        if matched_writer:
            print(
                warn(f"'{video.title}' needs to be added to '{INDEPENDENT_STUDIO}' based on writer '{matched_writer}'")
            )
            if set_studio(video, INDEPENDENT_STUDIO, dry_run=args.dry_run):
                changed += 1
    print(info(f"{changed} studios added.{dry_run_note(args)}"))
    return 0


def rename_studio(args: argparse.Namespace) -> int:
    ctx = build_context(args)
    results = ctx.search(studio__exact=args.old, sort="titleSort", reload=True)
    changed = 0
    for video in results:
        print(warn(f"'{video.title}' needs studio rename '{args.old}' -> '{args.new}'"))
        if set_studio(video, args.new, dry_run=args.dry_run):
            changed += 1
    print(info(f"{changed} videos updated.{dry_run_note(args)}"))
    return 0


def list_videos(args: argparse.Namespace) -> int:
    ctx = build_context(args)
    videos: list[Any]
    if args.search_title:
        videos = ctx.search(filters=title_contains(args.search_title), reload=True)
    elif args.collection:
        videos = list(ctx.collection(args.collection).items())
        for video in videos:
            reload_if_partial(video)
    elif args.studio:
        videos = ctx.search(studio__exact=args.studio, sort="titleSort", reload=True)
    elif args.writer:
        videos = ctx.search(filters={"writer": args.writer}, reload=True)
    elif args.no_studio:
        videos = ctx.search(studio__exact="", sort="titleSort", reload=False)
    else:
        videos = ctx.all_videos(reload=args.reload)

    regex = re.compile(args.regex, re.IGNORECASE) if args.regex else None
    for video in videos:
        if args.title and args.title.lower() not in video.title.lower():
            continue
        if args.startswith and not video.title.lower().startswith(args.startswith.lower()):
            continue
        if regex and not regex.search(video.title):
            continue
        if args.no_title_spaces and " - " not in video.title or not args.no_title_spaces:
            print_title(video)
    return 0


def list_collections(args: argparse.Namespace) -> int:
    ctx = build_context(args)
    for collection in ctx.section.collections():
        reload_if_partial(collection)
        title = str(collection.title)
        if args.pattern and args.pattern.lower() not in title.lower():
            continue
        try:
            count = len(collection.items())
        except Exception:
            count = 0
        print(f"{count:4}: {title}")
    return 0


def list_studios(args: argparse.Namespace) -> int:
    ctx = build_context(args)
    counts: Counter[str] = Counter()
    for video in ctx.all_videos():
        reload_if_partial(video)
        studio = getattr(video, "studio", None) or ""
        if studio:
            counts[studio] += 1
    for studio, count in sorted(counts.items()):
        if args.pattern and args.pattern.lower() not in studio.lower():
            continue
        print(f"{count:4}: {studio}")
    return 0


def list_writers(args: argparse.Namespace) -> int:
    ctx = build_context(args)
    counts: Counter[str] = Counter()
    videos = list(ctx.collection(args.collection).items()) if args.collection else ctx.all_videos()
    for video in videos:
        reload_if_partial(video)
        for writer in getattr(video, "writers", []) or []:
            counts[str(writer)] += 1
    for writer, count in sorted(counts.items()):
        print(f"{count:4}: {writer}")
    return 0


def list_studio_writers(args: argparse.Namespace) -> int:
    ctx = build_context(args)
    counts: Counter[str] = Counter()
    for video in ctx.search(studio__exact=args.studio, sort="titleSort", reload=True):
        for writer in getattr(video, "writers", []) or []:
            counts[str(writer)] += 1
    for writer, count in sorted(counts.items()):
        print(f"{count:4}: {writer}")
    return 0


def list_special(args: argparse.Namespace) -> int:
    ctx = build_context(args)
    if args.kind == "uncategorized" or args.kind == "no-composition":
        excluded = [not_in_collection(name) for name in EXCLUDED_COMPOSITION_COLLECTIONS]
        videos = ctx.search(filters=and_filter(*excluded), reload=False)
    elif args.kind == "no-hair":
        excluded = [not_in_collection(name) for name in EXCLUDED_HAIR_COLLECTIONS]
        videos = ctx.search(filters=and_filter(*excluded), reload=False)
    elif args.kind == "uncollected":
        videos = [video for video in ctx.all_videos(reload=True) if not collection_titles(video)]
    elif args.kind == "merged":
        videos = [video for video in ctx.all_videos(reload=True) if len(getattr(video, "guids", []) or []) > 1]
    elif args.kind == "potential-indie":
        videos = [
            video
            for video in ctx.all_videos()
            if not is_scene(video) and not getattr(video, "studio", None) and " - " in video.title
        ]
    elif args.kind == "multi-f-without-category":
        # Deliberately still checks "01: Category:" specifically rather than the full
        # CATEGORY_TAXONOMY_PREFIXES family: this is really asking "no composition tag yet"
        # (Solo/FFM/MMF/etc.), and those are intentionally still "01: Category:" - see
        # EXCLUDED_COMPOSITION_COLLECTIONS and rename_categories()'s composition deferral.
        videos = [
            video
            for video in ctx.all_videos(reload=True)
            if len(writers_from_title(video.title)) > 1
            and not any("01: Category:" in title for title in collection_titles(video))
        ]
    else:
        raise ValueError(f"Unsupported special list kind: {args.kind}")

    for video in videos:
        print_title(video)
    return 0


def set_writers_from_titles(args: argparse.Namespace) -> int:
    ctx = build_context(args)
    changed = 0
    videos = ctx.all_videos()
    for index, video in enumerate(videos, 1):
        reload_if_partial(video)
        missing = missing_title_writers(video)
        if missing:
            print(warn(f"{progress_prefix(index, len(videos))}Adding writers to '{video.title}': {', '.join(missing)}"))
            if add_writer(video, writers_from_title(video.title), dry_run=args.dry_run):
                changed += 1
    print(ok(f"{changed} videos updated.{dry_run_note(args)}"))
    return 0


def sync_smart_collections(args: argparse.Namespace) -> int:
    ctx = build_context(args)
    studios: set[str] = set()
    writers: set[str] = set()
    for video in ctx.all_videos(reload=True):
        if getattr(video, "studio", None):
            studios.add(video.studio)
        for writer in getattr(video, "writers", []) or []:
            writers.add(str(writer).strip())
    existing = {str(collection.title).lower() for collection in ctx.section.collections()}
    created = 0
    for studio in sorted(studios):
        title = f"02: {studio}" if studio == INDEPENDENT_STUDIO else f"02: Studio: {studio}"
        if title.lower() not in existing:
            print(warn(f"Creating smart collection '{title}'"))
            create_smart_collection(
                ctx.section,
                title=title,
                sort="titleSort:asc",
                filters={"studio": studio},
                dry_run=args.dry_run,
            )
            created += 1
    for writer in sorted(writers):
        title = f"03: Star: {writer}"
        if title.lower() not in existing:
            print(warn(f"Creating smart collection '{title}'"))
            create_smart_collection(
                ctx.section,
                title=title,
                sort="titleSort:asc",
                filters={"writer": writer},
                dry_run=args.dry_run,
            )
            created += 1
    print(ok(f"Newly created smart collections: {created}{dry_run_note(args)}"))
    return 0


def set_writers_and_sync(args: argparse.Namespace) -> int:
    set_writers_from_titles(args)
    return sync_smart_collections(args)


def _require_inventory_config(args: argparse.Namespace) -> Any:
    config = load_inventory_config(args.config)
    if config is None:
        raise ValueError(
            "No [inventory] section configured. Add an [inventory] section with at least "
            "'url' to the config file to use inventory commands."
        )
    return config


def inventory_snapshot(args: argparse.Namespace) -> int:
    from plexadm.inventory import take_snapshot

    ctx = build_context(args)
    config = _require_inventory_config(args)
    count = take_snapshot(ctx, config, dry_run=args.dry_run)
    print(ok(f"{count} video snapshots written to '{config.index}'.{dry_run_note(args)}"))
    return 0


def inventory_diff(args: argparse.Namespace) -> int:
    from plexadm.inventory import diff_snapshots

    config = _require_inventory_config(args)
    audit_index = None
    if not args.no_attribution:
        logging_config = load_logging_config(args.config)
        if logging_config.sink == "opensearch" and logging_config.opensearch is not None:
            audit_index = logging_config.opensearch.index

    run_a, run_b, changes = diff_snapshots(config, run_a=args.run_a, run_b=args.run_b, audit_index=audit_index)
    print(info(f"Comparing snapshot '{run_a}' -> '{run_b}'"))
    if not changes:
        print(ok("No collection membership changes between these snapshots."))
        return 0

    for change in sorted(changes, key=lambda c: c.title):
        marker = "" if change.attributed else " [UNATTRIBUTED - no matching plexadm-audit event]"
        if change.added:
            print(warn(f"'{change.title}' gained: {', '.join(change.added)}{marker}"))
        if change.removed:
            print(warn(f"'{change.title}' lost: {', '.join(change.removed)}{marker}"))
    unattributed = sum(1 for change in changes if not change.attributed)
    print(info(f"{len(changes)} videos changed, {unattributed} with at least one unattributed change."))
    return 0


def _filters_reference_collection(node: Any, target_key: str) -> bool:
    """Recursively check whether a smart collection's parsed filter tree (as returned by
    plexapi's `Collection.filters()`) contains a "collection" condition matching target_key,
    however deep it's nested inside "and"/"or" groups."""
    if isinstance(node, dict):
        if str(node.get("collection")) == target_key:
            return True
        return any(_filters_reference_collection(value, target_key) for value in node.values())
    if isinstance(node, list):
        return any(_filters_reference_collection(item, target_key) for item in node)
    return False


def retarget_writer_ppv(args: argparse.Namespace) -> int:
    ctx = build_context(args)
    old = ctx.collection(args.old_collection)
    new = ctx.collection(args.new_collection)

    # Resolve OLD's smart-filter ID before mutating anything below. Plex stops offering an
    # empty collection as a "collection" filter choice at all - confirmed live: emptying "01:
    # Rin PPV" via the removal step further down made this same lookup fail immediately
    # afterward with "No collection filter choice found". Resolving it first, while OLD still
    # has members, is what makes the later smart-collection retarget step possible at all.
    old_key = collection_filter_key(ctx.section, old.title)

    items = list(old.items())
    to_add = [video for video in items if not has_collection(video, new.title)]
    for video in to_add:
        print(warn(f"'{video.title}' needs to be added to '{new.title}'"))
    added = add_items(new, to_add, dry_run=args.dry_run)
    for video in items:
        print(warn(f"'{video.title}' needs to be removed from '{old.title}'"))
    removed = remove_items(old, items, dry_run=args.dry_run)
    print(
        info(f"{added} videos added to '{new.title}', {removed} videos removed from '{old.title}'.{dry_run_note(args)}")
    )

    name_needle = args.name_contains.lower()
    retargeted = 0
    for collection in ctx.section.collections():
        reload_if_partial(collection)
        if not collection.smart or name_needle not in str(collection.title).lower():
            continue
        spec = collection.filters()
        conditions = spec.get("filters", {})
        if not _filters_reference_collection(conditions, old_key):
            continue
        if set(conditions.keys()) != {"collection"}:
            print(
                warn(
                    f"'{collection.title}' filter references '{old.title}' but has other "
                    "conditions too - skipping, retarget it by hand."
                )
            )
            continue
        new_filters = {"and": [{"collection": new.title}, {"writer": args.writer}]}
        print(warn(f"Retargeting '{collection.title}' to '{new.title}' + writer '{args.writer}'"))
        update_smart_collection_filters(
            collection, section=ctx.section, sort=spec.get("sort"), filters=new_filters, dry_run=args.dry_run
        )
        retargeted += 1
    print(info(f"{retargeted} smart collections retargeted.{dry_run_note(args)}"))
    return 0


def clone_smart_collection(args: argparse.Namespace) -> int:
    ctx = build_context(args)
    source = ctx.collection(args.source)
    if not source.smart:
        print(fail(f"'{source.title}' is not a smart collection - clone only supports smart collections."))
        return 1
    spec = source.filters()
    conditions = spec.get("filters", {})
    extra = json.loads(args.add_filter)
    combined = and_filter(conditions, extra) if conditions else extra
    print(info(f"Cloning '{source.title}' -> '{args.target}' with extra filter {extra}"))
    create_smart_collection(
        ctx.section, title=args.target, sort=spec.get("sort"), filters=combined, dry_run=args.dry_run
    )
    print(info(f"Created smart collection '{args.target}'.{dry_run_note(args)}"))
    return 0


def rename_collections(args: argparse.Namespace) -> int:
    ctx = build_context(args)
    pattern = re.compile(args.pattern)
    changed = 0
    for collection in ctx.section.collections():
        reload_if_partial(collection)
        new_title = pattern.sub(args.replacement, collection.title)
        if new_title != collection.title:
            print(warn(f"Renaming '{collection.title}' to '{new_title}'"))
            rename_collection(collection, new_title, dry_run=args.dry_run)
            changed += 1
    print(info(f"{changed} collections renamed.{dry_run_note(args)}"))
    return 0


SCENE_BASE_DIR = "/data/NSFW Scenes/"


def list_renames(args: argparse.Namespace) -> int:
    ctx = build_context(args)
    filter_text = args.filter_text

    for video in ctx.all_videos():
        locations = getattr(video, "locations", []) or []
        if not locations:
            continue

        if filter_text:
            haystack = [video.title] + locations
            if not any(filter_text in entry for entry in haystack):
                continue

        if args.script and len(locations) > 1:
            continue

        filename = Path(locations[0]).name
        match_found = any(video.title in location for location in locations)

        if (
            " - Message " in filename
            or " - Post " in filename
            or "PPV" in filename
            or " PPV " in locations[0]
            or "?" in video.title
            or not video.title.isascii()
        ):
            match_found = True

        has_location_mismatch = any(video.title not in location for location in locations)
        needs_review = not args.script and len(locations) > 1 and has_location_mismatch

        if not match_found or needs_review:
            old_location = locations[0].replace(args.base_dir, "")
            new_fname = f"{video.title}.mp4"
            first_writer = new_fname.split(" - ", 1)[0].split(",")[0]
            if args.script:
                print(f'mv "{old_location}" "{first_writer}/{new_fname}"')
            else:
                if len(locations) > 1:
                    print(f"WARNING: {video.title} has multiple locations!")
                    for location in locations:
                        print(f"  {location}")
                    print("")
                else:
                    print(f"{old_location} -> {first_writer}/{new_fname}")

    return 0


def find_missing_file(args: argparse.Namespace) -> int:
    ctx = build_context(args)
    target = Path(args.path)
    found = False
    for video in ctx.all_videos():
        for location in getattr(video, "locations", []) or []:
            if Path(location) == target:
                found = True
                print_title(video)
    if not found:
        print(fail(f"No Plex item found for {target}"))
        return 1
    return 0


def fix_dl_scene_name(args: argparse.Namespace) -> int:
    start_name = "TBD - " if not args.prefix else f"{args.prefix} - "
    path = Path(args.filename)
    new_name = start_name + path.name
    print(new_name)
    return 0


def ultrafilms_titleize(text: str) -> str:
    aliases = {
        "Black Angel": "Black Angel aka Kate Rose",
        "Kate Rose": "Black Angel aka Kate Rose",
    }
    titled = " ".join(part.capitalize() for part in re.split(r"[_\s]+", text.strip()))
    return aliases.get(titled, titled)


def fix_ultrafilms_name(args: argparse.Namespace) -> int:
    path = Path(args.filename)
    stem = path.stem
    print(f"{ultrafilms_titleize(stem)}{path.suffix}")
    return 0


def gen_ofdl_names(args: argparse.Namespace) -> int:
    mapping = json.loads(Path(args.map_file).read_text(encoding="utf-8"))
    for source, target in sorted(mapping.items()):
        print(f"{source}: {target}")
    return 0


def ofdl_rsync(args: argparse.Namespace) -> int:
    command = ["rsync", "-avh", "--progress", args.source, args.destination]
    print(" ".join(command))
    return subprocess.call(command)


def remove_fps_title(args: argparse.Namespace) -> int:
    source = Path(args.filename)
    target = source.with_name(re.sub(r"_[236][450]fps", "", source.name))
    print(f"Renaming '{source}' to '{target}'...")
    shutil.move(str(source), str(target))
    return 0


def upload_vids(args: argparse.Namespace) -> int:
    for filename in Path.cwd().glob("*.mp4"):
        star_name = filename.name.split("-", 1)[0].split(",", 1)[0].removesuffix(".mp4").strip()
        remote_dir = f"{args.upload_path}/{star_name}"
        remote_file = f"{remote_dir}/{filename.name}"
        subprocess.run(["ssh", args.remote_host, "mkdir", remote_dir], check=False)
        tmp_remote = f"{args.remote_host}:{remote_file}.tmp"
        print(f"Uploading to {tmp_remote} ...")
        subprocess.run(["scp", str(filename), tmp_remote], check=True)
        subprocess.run(["ssh", args.remote_host, "mv", f"{remote_file}.tmp", remote_file], check=True)
        filename.unlink()
    return 0


def print_top(args: argparse.Namespace) -> int:
    ctx = build_context(args)
    if args.source == "categories":
        rows = []
        for collection in ctx.section.collections():
            if any(prefix in collection.title for prefix in CATEGORY_TAXONOMY_PREFIXES):
                reload_if_partial(collection)
                rows.append((len(collection.items()), collection.title))
        for count, title in sorted(rows)[-args.limit :]:
            print(f"{count:4}: {title}")
        return 0

    if args.source == "studios":
        studio_counts: Counter[str] = Counter()
        for video in ctx.all_videos(reload=True):
            if getattr(video, "studio", None):
                studio_counts[video.studio] += 1
        for studio, count in studio_counts.most_common(args.limit):
            print(f"{count:4}: {studio}")
        return 0

    collection = args.collection or (
        UNRATED_COLLECTION if args.source in {"unrated-writers", "unrated-scenes"} else None
    )
    videos = list(ctx.collection(collection).items()) if collection else ctx.search(studio__exact="", sort="titleSort")
    counts: Counter[str] = Counter()
    for video in videos:
        title = video.title
        if args.scenes and "Scene #" not in title:
            continue
        key = title.split(",", 1)[0].split("-", 1)[0].replace("Title: ", "").strip()
        counts[key] += 1
    rows = sorted((count, key) for key, count in counts.items())
    for count, key in rows[-args.limit :]:
        print(f"{count:4}: {key}")
    return 0


FORMATTER = argparse.RawDescriptionHelpFormatter


def add_common_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--config",
        metavar="PATH",
        help=(
            "Path to the Plex config file. "
            "If omitted, plexadm searches the default locations "
            "(~/.config/plexadm/config.yaml, /etc/plexadm/config.yaml)."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Report what would be added, removed, or edited without changing Plex. "
            "Also honored via the PLEXADM_DRY_RUN=1 environment variable, so it can be "
            "applied to a whole shell script's worth of plexadm invocations at once."
        ),
    )


def dry_run_note(args: argparse.Namespace) -> str:
    return " (dry run - no changes made)" if getattr(args, "dry_run", False) else ""


def set_func(parser: argparse.ArgumentParser, func: Any) -> None:
    add_common_parser(parser)
    parser.set_defaults(func=func)


def _make_sub(
    sub: Any,
    name: str,
    *,
    help: str,
    description: str | None = None,
    epilog: str | None = None,
) -> argparse.ArgumentParser:
    """Add a subparser with consistent formatting and required descriptions.

    ``help`` is the one-line summary shown in the parent command's listing.
    ``description`` is the longer prose shown when running ``<command> -h``;
    if omitted, ``help`` is reused so the per-command page still has context.
    """
    return sub.add_parser(
        name,
        help=help,
        description=description or help,
        epilog=epilog,
        formatter_class=FORMATTER,
    )


def _add_subparsers(parser: argparse.ArgumentParser, *, dest: str, title: str) -> Any:
    return parser.add_subparsers(
        dest=dest,
        required=True,
        title=title,
        metavar="<command>",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="plexadm",
        formatter_class=FORMATTER,
        description=(
            "plexadm administers a Plex video library: listing items, building and\n"
            "maintaining collections, normalising studios and writers, and running\n"
            "miscellaneous file-system tools.\n"
            "\n"
            "All mutation subcommands apply changes immediately unless the subcommand\n"
            "documents another mode. Use `plexadm <command> -h` for command-specific\n"
            "help, or `plexadm <command> <subcommand> -h` to drill down further."
        ),
        epilog=(
            "Examples:\n"
            "  plexadm list videos --collection '01: Composition: Solo'\n"
            "  plexadm collection add-search '01: Prop: Oil' 'Oily'\n"
            "  plexadm studio rename 'Old Studio' 'New Studio'\n"
            "  plexadm smart-collections sync\n"
            "  plexadm top categories --limit 25\n"
            "\n"
            "Run `plexadm <command> -h` for details on any command."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
        help="Show the installed plexadm version and exit.",
    )
    sub = _add_subparsers(parser, dest="command", title="commands")

    _build_list_commands(sub)
    _build_collection_commands(sub)
    _build_studio_commands(sub)
    _build_writers_commands(sub)
    _build_smart_collection_commands(sub)
    _build_tools_commands(sub)
    _build_top_command(sub)
    _build_stash_commands(sub)
    _build_inventory_commands(sub)

    return parser


def _build_list_commands(sub: Any) -> None:
    list_parser = _make_sub(
        sub,
        "list",
        help="Read-only inventory commands (videos, collections, studios, writers, renames).",
        description=(
            "Read-only commands that report what is currently in the Plex library.\n"
            "Nothing under `list` mutates Plex state."
        ),
        epilog=(
            "Examples:\n"
            "  plexadm list videos --title 'oil'\n"
            "  plexadm list collections '01: Category'\n"
            "  plexadm list studios\n"
            "  plexadm list writers --collection '01: Composition: Solo'\n"
            "  plexadm list renames --script > rename.sh\n"
            "  plexadm list special uncategorized"
        ),
    )
    list_sub = _add_subparsers(list_parser, dest="list_command", title="list subcommands")

    videos = _make_sub(
        list_sub,
        "videos",
        help="List videos, optionally filtered by title, collection, studio, or writer.",
        description=(
            "Print one line per video that matches the given filters.\n"
            "\n"
            "Filters compose: provide one source filter (--collection, --studio,\n"
            "--writer, --search-title, or --no-studio) and any number of title\n"
            "filters (--title, --startswith, --regex) to narrow the results.\n"
            "With no source filter the entire library is scanned."
        ),
        epilog=(
            "Examples:\n"
            "  plexadm list videos --collection '01: Composition: Solo'\n"
            "  plexadm list videos --studio 'Brazzers' --regex '(?i)\\bpov\\b'\n"
            "  plexadm list videos --writer 'Alice' --no-title-spaces"
        ),
    )
    videos.add_argument(
        "--title",
        metavar="SUBSTRING",
        help="Keep only videos whose title contains this substring (case-insensitive).",
    )
    videos.add_argument(
        "--startswith",
        metavar="PREFIX",
        help="Keep only videos whose title starts with PREFIX (case-insensitive).",
    )
    videos.add_argument(
        "--regex",
        metavar="REGEX",
        help="Keep only videos whose title matches this Python regex (case-insensitive).",
    )
    videos.add_argument(
        "--search-title",
        metavar="TEXT",
        help="Use a Plex server-side title search for TEXT instead of scanning all videos.",
    )
    videos.add_argument(
        "--collection",
        metavar="NAME",
        help="List videos that belong to the named collection.",
    )
    videos.add_argument(
        "--studio",
        metavar="NAME",
        help="List videos with this exact studio.",
    )
    videos.add_argument(
        "--writer",
        metavar="NAME",
        help="List videos with this writer/star.",
    )
    videos.add_argument(
        "--no-studio",
        action="store_true",
        help="List videos that have no studio assigned.",
    )
    videos.add_argument(
        "--no-title-spaces",
        action="store_true",
        help="Skip videos whose title contains ' - ' (the writer/title separator).",
    )
    videos.add_argument(
        "--reload",
        action="store_true",
        help="Force-reload each video's metadata from the Plex server before filtering.",
    )
    set_func(videos, list_videos)

    collections = _make_sub(
        list_sub,
        "collections",
        help="List collections in the library, with item counts.",
        description=(
            "Print '<count>: <name>' for every collection in the library.\n"
            "Pass a substring to filter the collection name (case-insensitive)."
        ),
        epilog="Example:\n  plexadm list collections '01: Category'",
    )
    collections.add_argument(
        "pattern",
        nargs="?",
        metavar="PATTERN",
        help="Optional case-insensitive substring filter on collection name.",
    )
    set_func(collections, list_collections)

    studios = _make_sub(
        list_sub,
        "studios",
        help="List studios in the library with the number of videos for each.",
        description=(
            "Print '<count>: <studio>' for every studio that has at least one video.\n"
            "Pass a substring to filter the studio name (case-insensitive)."
        ),
        epilog="Example:\n  plexadm list studios brazzers",
    )
    studios.add_argument(
        "pattern",
        nargs="?",
        metavar="PATTERN",
        help="Optional case-insensitive substring filter on studio name.",
    )
    set_func(studios, list_studios)

    writers = _make_sub(
        list_sub,
        "writers",
        help="List writers/stars with their video counts.",
        description=(
            "Print '<count>: <writer>' for every distinct writer.\n"
            "By default this scans the whole library; restrict it to a single\n"
            "collection with --collection."
        ),
        epilog="Example:\n  plexadm list writers --collection '01: Composition: Solo'",
    )
    writers.add_argument(
        "--collection",
        metavar="NAME",
        help="Restrict the writer count to videos inside this collection.",
    )
    set_func(writers, list_writers)

    studio_writers = _make_sub(
        list_sub,
        "studio-writers",
        help="List writers/stars for videos belonging to a given studio.",
        description="Print '<count>: <writer>' for every writer appearing on videos of the given studio.",
        epilog="Example:\n  plexadm list studio-writers 'Brazzers'",
    )
    studio_writers.add_argument(
        "studio",
        metavar="STUDIO",
        help="Exact studio name to filter on.",
    )
    set_func(studio_writers, list_studio_writers)

    renames = _make_sub(
        list_sub,
        "renames",
        help="Report file renames needed so on-disk filenames match Plex titles.",
        description=(
            "For each video whose filename does not match its Plex title, print either\n"
            "a human-readable diff (default) or a `mv` script (--script).\n"
            "\n"
            "Videos with multiple file locations are skipped in --script mode and\n"
            "flagged with a WARNING in human-readable mode."
        ),
        epilog=(
            "Examples:\n"
            "  plexadm list renames\n"
            "  plexadm list renames 'Brazzers'\n"
            "  plexadm list renames --script > rename.sh"
        ),
    )
    renames.add_argument(
        "filter_text",
        nargs="?",
        metavar="FILTER",
        help="Only include videos whose title or file path contains this substring.",
    )
    renames.add_argument(
        "--script",
        action="store_true",
        help="Output `mv` commands instead of a human-readable diff.",
    )
    renames.add_argument(
        "--base-dir",
        default=SCENE_BASE_DIR,
        metavar="DIR",
        help=f"Base directory prefix to strip from file paths (default: {SCENE_BASE_DIR}).",
    )
    set_func(renames, list_renames)

    special_help = {
        "uncategorized": "videos missing all '01: Category:' collections (alias of no-composition)",
        "uncollected": "videos that are not in any collection at all",
        "merged": "videos with more than one external GUID (likely merged)",
        "potential-indie": "non-scene videos with no studio whose title contains ' - '",
        "multi-f-without-category": "videos with multiple title-derived writers but no category collection",
        "no-composition": "videos missing every composition category (FFM, MMF, ...)",
        "no-hair": "videos missing every hair-colour collection",
    }
    special = _make_sub(
        list_sub,
        "special",
        help="Run one of the built-in special-case audits over the library.",
        description=(
            "Audit the library for a specific class of metadata gap. Pick one KIND:\n\n"
            + "\n".join(f"  {kind:<28}{desc}" for kind, desc in special_help.items())
        ),
        epilog=(
            "Examples:\n"
            "  plexadm list special uncategorized\n"
            "  plexadm list special no-hair\n"
            "  plexadm list special uncollected"
        ),
    )
    special.add_argument(
        "kind",
        choices=list(special_help),
        metavar="KIND",
        help="Which audit to run (see description for the list).",
    )
    set_func(special, list_special)


def _build_collection_commands(sub: Any) -> None:
    collection = _make_sub(
        sub,
        "collection",
        help="Mutate a manual collection (add/remove videos, copy, sync helpers).",
        description=(
            "Commands that mutate manual collections. Membership changes are written\nto the Plex server immediately."
        ),
        epilog=(
            "Examples:\n"
            "  plexadm collection add-title '01: Composition: Solo' 'masturbation' --skip-scenes\n"
            "  plexadm collection add-search '01: Prop: Oil' 'Oily'\n"
            "  plexadm collection copy 'Old Name' 'New Name'\n"
            "  plexadm collection sync-unrated"
        ),
    )
    collection_sub = _add_subparsers(collection, dest="collection_command", title="collection subcommands")

    add_title = _make_sub(
        collection_sub,
        "add-title",
        help="Add videos whose title matches PATTERN to COLLECTION.",
        description=(
            "Walk every video and add the ones whose title contains PATTERN\n"
            "(case-insensitive substring match) to COLLECTION."
        ),
        epilog="Example:\n  plexadm collection add-title '01: Prop: Oil' 'oily' --skip-scenes",
    )
    add_title.add_argument("collection", metavar="COLLECTION", help="Target collection name.")
    add_title.add_argument("pattern", metavar="PATTERN", help="Substring to match in the video title.")
    add_title.add_argument(
        "--startswith",
        action="store_true",
        help="Require the title to START with PATTERN rather than contain it.",
    )
    add_title.add_argument(
        "--skip-scenes",
        action="store_true",
        help="Skip videos whose title contains ' (Scene #' (typically multi-scene rips).",
    )
    set_func(add_title, add_matching_titles)

    add_search = _make_sub(
        collection_sub,
        "add-search",
        help="Add videos to COLLECTION via a Plex server-side title search.",
        description=(
            "Use Plex's server-side title search for PATTERN and add any matches that\n"
            "are not already in COLLECTION. Faster than `add-title` for big libraries\n"
            "but matches per Plex's search semantics, not a pure substring."
        ),
        epilog="Example:\n  plexadm collection add-search '01: Prop: Fuck Machine' 'fuckmachine'",
    )
    add_search.add_argument("collection", metavar="COLLECTION", help="Target collection name.")
    add_search.add_argument("pattern", metavar="PATTERN", help="Text passed to the Plex title search.")
    add_search.add_argument(
        "--exclude-collection",
        action="append",
        metavar="COLLECTION",
        help="Skip matches already in COLLECTION (repeatable). Use for keyword matches that "
        "would otherwise conflict with an existing, more reliable tag - e.g. a title-text match "
        "for Solo should not override a video already tagged '01: Composition: MF Only'.",
    )
    add_search.add_argument(
        "--exclude-collection-prefix",
        action="append",
        metavar="PREFIX",
        help="Skip matches already in any collection whose title starts with PREFIX (repeatable, "
        "checked client-side). Use to exclude a whole family at once - e.g. "
        "--exclude-collection-prefix '01: Composition:' for Solo, instead of listing every "
        "individual composition collection with --exclude-collection.",
    )
    set_func(add_search, add_search_results)

    add_writer = _make_sub(
        collection_sub,
        "add-writer",
        help="Add videos with an exact writer match to COLLECTION.",
        description=(
            "Walk every video and add the ones whose writer list contains an exact\n"
            "(case-insensitive) match for PATTERN to COLLECTION."
        ),
        epilog="Example:\n  plexadm collection add-writer '01: Activity: Extreme Throating' 'Tiptobase69'",
    )
    add_writer.add_argument("collection", metavar="COLLECTION", help="Target collection name.")
    add_writer.add_argument("pattern", metavar="WRITER", help="Exact writer name to match (case-insensitive).")
    set_func(add_writer, add_writer_matches)

    add_writers = _make_sub(
        collection_sub,
        "add-writers",
        help="Add videos for every writer listed in FILE to COLLECTION.",
        description=(
            "Read writer names from FILE (one per line) and add every video matching\n"
            "any of those writers to COLLECTION. Videos already in the LOCKED\n"
            "collection are skipped."
        ),
        epilog="Example:\n  plexadm collection add-writers '01: Hair: Blonde' /usr/local/share/plexadm/reference/writers_blonde.txt",
    )
    add_writers.add_argument("collection", metavar="COLLECTION", help="Target collection name.")
    add_writers.add_argument("file", metavar="FILE", help="Path to a writer-list file (one name per line).")
    add_writers.add_argument(
        "--single-writer-only",
        action="store_true",
        help="Skip videos with more than one credited writer (e.g. for Solo, where a listed "
        "performer co-starring in a multi-writer scene should not tag that scene Solo).",
    )
    set_func(add_writers, add_writers_file)

    copy = _make_sub(
        collection_sub,
        "copy",
        help="Copy all videos from SOURCE collection into TARGET collection.",
        description="Add every video in SOURCE to TARGET. SOURCE is left unchanged.",
        epilog="Example:\n  plexadm collection copy 'Old Smart Collection' 'New Manual Collection'",
    )
    copy.add_argument("source", metavar="SOURCE", help="Collection to read from.")
    copy.add_argument("target", metavar="TARGET", help="Collection to write to.")
    set_func(copy, copy_collection)

    copy_studio_parser = _make_sub(
        collection_sub,
        "copy-studio",
        help="Add every video with the given studio to COLLECTION.",
        description="Find videos whose studio equals STUDIO and add any missing ones to COLLECTION.",
        epilog="Example:\n  plexadm collection copy-studio 'Brazzers' '02: Studio: Brazzers'",
    )
    copy_studio_parser.add_argument("studio", metavar="STUDIO", help="Studio name to filter by.")
    copy_studio_parser.add_argument("collection", metavar="COLLECTION", help="Target collection name.")
    set_func(copy_studio_parser, copy_studio)

    remove_title = _make_sub(
        collection_sub,
        "remove-title",
        help="Remove videos whose title matches PATTERN from COLLECTION.",
        description="Walk COLLECTION and remove every video whose title contains PATTERN (case-insensitive).",
        epilog="Example:\n  plexadm collection remove-title '01: Composition: Solo' 'duo'",
    )
    remove_title.add_argument("collection", metavar="COLLECTION", help="Collection to remove from.")
    remove_title.add_argument("pattern", metavar="PATTERN", help="Substring to match in the video title.")
    set_func(remove_title, remove_matching_titles)

    add_duration = _make_sub(
        collection_sub,
        "add-duration",
        help="Add every video matching a duration bound (and optional ad hoc filters) to COLLECTION.",
        description=(
            "Add every video whose duration is below --max-duration-ms and/or above\n"
            "--min-duration-ms to COLLECTION. If neither bound is given, defaults to\n"
            f"--max-duration-ms {DEFAULT_SHORT_VIDEO_MAX_DURATION_MS} (short videos), matching this\n"
            "command's old name/behavior as 'add-short'.\n\n"
            "--filters takes a JSON object of additional Plex advanced-search conditions,\n"
            "AND-combined with the duration bound(s) - the same dict shape accepted by\n"
            '`LibrarySection.search(filters=...)` (e.g. \'{"studio": "Independent Content", '
            '"collection!": "01: Theme: Live Stream"}\').'
        ),
        epilog=(
            "Examples:\n"
            "  plexadm collection add-duration '01: Duration: Short' --max-duration-ms 60000\n"
            "  plexadm collection add-duration '00D: Review: Indie Long No Livestream' "
            "--min-duration-ms 3600000 "
            '--filters \'{"studio": "Independent Content", "collection!": "01: Theme: Live Stream"}\''
        ),
    )
    add_duration.add_argument("collection", metavar="COLLECTION", help="Target collection name.")
    add_duration.add_argument(
        "--max-duration-ms",
        type=int,
        default=None,
        metavar="MS",
        help=f"Maximum video duration in milliseconds (default: {DEFAULT_SHORT_VIDEO_MAX_DURATION_MS} if "
        "--min-duration-ms is also omitted; otherwise unbounded).",
    )
    add_duration.add_argument(
        "--min-duration-ms",
        type=int,
        default=None,
        metavar="MS",
        help="Minimum video duration in milliseconds (default: unbounded).",
    )
    add_duration.add_argument(
        "--filters",
        metavar="JSON",
        help="Extra Plex advanced-search filters as a JSON object, AND-combined with the duration bound(s).",
    )
    set_func(add_duration, add_duration_collection)

    add_orgy = _make_sub(
        collection_sub,
        "add-orgy",
        help="Add videos with 4+ writers to COLLECTION.",
        description="Add every video with at least --min-writers writers to COLLECTION.",
        epilog="Example:\n  plexadm collection add-orgy '01: Composition: Orgy'",
    )
    add_orgy.add_argument("collection", metavar="COLLECTION", help="Target collection name.")
    add_orgy.add_argument(
        "--min-writers",
        type=int,
        default=4,
        metavar="N",
        help="Minimum number of writers to qualify (default: 4).",
    )
    set_func(add_orgy, add_orgy_collection)

    add_vertical = _make_sub(
        collection_sub,
        "add-vertical",
        help="Add every vertically-oriented video to COLLECTION.",
        description="Add every video whose first media is taller than it is wide (height > width) to COLLECTION.",
        epilog="Example:\n  plexadm collection add-vertical '01: Category: Vertical Video'",
    )
    add_vertical.add_argument("collection", metavar="COLLECTION", help="Target collection name.")
    set_func(add_vertical, add_vertical_collection)

    sync_unrated_parser = _make_sub(
        collection_sub,
        "sync-unrated",
        help=f"Keep COLLECTION in sync with the set of unrated videos (default: '{UNRATED_COLLECTION}').",
        description=(
            "Add every unrated video that is not already in COLLECTION and remove\n"
            f"every rated video that is. Defaults to '{UNRATED_COLLECTION}'."
        ),
        epilog="Example:\n  plexadm collection sync-unrated",
    )
    sync_unrated_parser.add_argument(
        "collection",
        nargs="?",
        default=UNRATED_COLLECTION,
        metavar="COLLECTION",
        help=f"Target collection name (default: '{UNRATED_COLLECTION}').",
    )
    set_func(sync_unrated_parser, sync_unrated)

    sync_no_studio_parser = _make_sub(
        collection_sub,
        "sync-no-studio",
        help=f"Keep COLLECTION in sync with the set of studio-less videos (default: '{NO_STUDIO_COLLECTION}').",
        description=(
            "Add every video with no studio that is missing from COLLECTION and remove\n"
            f"every video that now has a studio assigned. Defaults to '{NO_STUDIO_COLLECTION}'."
        ),
        epilog="Example:\n  plexadm collection sync-no-studio",
    )
    sync_no_studio_parser.add_argument(
        "collection",
        nargs="?",
        default=NO_STUDIO_COLLECTION,
        metavar="COLLECTION",
        help=f"Target collection name (default: '{NO_STUDIO_COLLECTION}').",
    )
    set_func(sync_no_studio_parser, sync_no_studio)

    add_ppv_parser = _make_sub(
        collection_sub,
        "add-ppv",
        help=f"Add videos whose filename matches '{PPV_FILENAME_PATTERN}' to COLLECTION (default: '{PPV_COLLECTION}').",
        description=(
            "Add every video whose filename matches "
            f"'{PPV_FILENAME_PATTERN}' that is missing from COLLECTION. Defaults to '{PPV_COLLECTION}'. Plex has "
            "no native filename filter, so matching happens in Python, not as a Plex search. Add-only: a "
            "filename no longer matching the pattern (e.g. after a manual rename) doesn't mean the video "
            "stopped being valid PPV content, so this never removes existing members."
        ),
        epilog="Example:\n  plexadm collection add-ppv",
    )
    add_ppv_parser.add_argument(
        "collection",
        nargs="?",
        default=PPV_COLLECTION,
        metavar="COLLECTION",
        help=f"Target collection name (default: '{PPV_COLLECTION}').",
    )
    set_func(add_ppv_parser, add_ppv)

    lock_titles_parser = _make_sub(
        collection_sub,
        "lock-titles",
        help="Lock title and sort title for every item in COLLECTION to their current values.",
        description=(
            "Lock the title and sort title fields for every item in COLLECTION, so agent\n"
            "refresh/matching can't silently overwrite a manually-picked title (e.g. merged-\n"
            "duplicate items whose title was chosen by hand from among several release names)."
        ),
        epilog="Example:\n  plexadm collection lock-titles '00A: DUPES'",
    )
    lock_titles_parser.add_argument("collection", metavar="COLLECTION", help="Target collection name.")
    set_func(lock_titles_parser, lock_collection_titles)

    rename_categories_parser = _make_sub(
        collection_sub,
        "rename-categories",
        help="Rename existing '01: Category:' collections into the Activity/Composition/"
        "Cumshot/Prop/Theme/Attributes taxonomy.",
        description=(
            "Renames every real '01: Category:' collection per the hand-classified table in\n"
            "plexadm.stash_backfill_tags._EXISTING_CATEGORY_RENAMES (the same table the\n"
            "'plexadm stash unmapped-tags' report's rename-suggestions section is built from).\n"
            "Only renames collections that actually exist today; anything left unclassified\n"
            "(format tags, a likely studio name, etc.) is untouched.\n\n"
            "Composition collections (Solo, MMF, FFM, Lesbian, Orgy, ...) are skipped by\n"
            "default: 'plexadm stash backfill-tags' matches these against Stash tags by exact\n"
            "name, and the Stash side isn't renamed by this command, so renaming them here\n"
            "would silently break that matching. Pass --include-composition once the Stash\n"
            "tags have a matching rename in place.\n\n"
            "Run every other script that references a renamed collection by its old name\n"
            "(set_tags_based_on_title.sh, copy_collections.sh, set_tags_based_on_writers.sh,\n"
            "mass_process.sh) needs to already be updated before running this for real, or\n"
            "they'll start failing to find their target collections."
        ),
        epilog="Example:\n  plexadm collection rename-categories --dry-run",
    )
    rename_categories_parser.add_argument(
        "--include-composition",
        action="store_true",
        help="Also rename composition collections (Solo, MMF, FFM, Lesbian, Orgy, ...) - only "
        "safe once the corresponding Stash tags have been renamed to match.",
    )
    set_func(rename_categories_parser, rename_categories)

    sync_lesbian_single_writer_parser = _make_sub(
        collection_sub,
        "sync-lesbian-single-writer",
        help=(
            f"Flag likely-mistagged '{LESBIAN_COLLECTION}' members in COLLECTION "
            f"(default: '{LESBIAN_SINGLE_WRITER_REVIEW_COLLECTION}')."
        ),
        description=(
            f"Add every '{LESBIAN_COLLECTION}' member with exactly one credited writer to "
            "COLLECTION (any studio, including Independent Content), and remove anything in "
            "COLLECTION that no longer matches (left '01: Composition: Lesbian' or gained a second "
            "writer). This is a review/cataloging collection only - it "
            f"never removes anything from '{LESBIAN_COLLECTION}' itself.\n"
            f"Defaults to '{LESBIAN_SINGLE_WRITER_REVIEW_COLLECTION}'."
        ),
        epilog="Example:\n  plexadm collection sync-lesbian-single-writer",
    )
    sync_lesbian_single_writer_parser.add_argument(
        "collection",
        nargs="?",
        default=LESBIAN_SINGLE_WRITER_REVIEW_COLLECTION,
        metavar="COLLECTION",
        help=f"Target collection name (default: '{LESBIAN_SINGLE_WRITER_REVIEW_COLLECTION}').",
    )
    set_func(sync_lesbian_single_writer_parser, sync_lesbian_single_writer)

    sync_cumshot_absent_parser = _make_sub(
        collection_sub,
        "sync-cumshot-absent",
        help=f"Flag sexual, non-female-only videos with no Cumshot collection in COLLECTION "
        f"(default: '{CUMSHOT_ABSENT_REVIEW_COLLECTION}').",
        description=(
            "Add every video that isn't in any Cumshot collection (Facial, Bukkake, Cum In "
            "Mouth, ...), isn't Solo/Lesbian/FF Only/Female Only (no male performer present, "
            "so no cumshot to have), and isn't Non-Sexual, to COLLECTION - and remove anything "
            "in COLLECTION that no longer matches. This is a review/cataloging collection "
            "only - it never touches Cumshot collection membership itself.\n\n"
            "Checks both the pre- and post-rename_categories() collection names, so this "
            "works whether or not that migration has run yet. FF Only/Female Only aren't "
            "populated by anything today, so the female-only exclusion currently only "
            "actually excludes Solo/Lesbian.\n\n"
            f"Defaults to '{CUMSHOT_ABSENT_REVIEW_COLLECTION}'."
        ),
        epilog="Example:\n  plexadm collection sync-cumshot-absent",
    )
    sync_cumshot_absent_parser.add_argument(
        "collection",
        nargs="?",
        default=CUMSHOT_ABSENT_REVIEW_COLLECTION,
        metavar="COLLECTION",
        help=f"Target collection name (default: '{CUMSHOT_ABSENT_REVIEW_COLLECTION}').",
    )
    set_func(sync_cumshot_absent_parser, sync_cumshot_absent)


def _build_studio_commands(sub: Any) -> None:
    studio = _make_sub(
        sub,
        "studio",
        help="Mutate the studio field on videos.",
        description="Commands that set or rename the studio metadata on videos.",
        epilog=(
            "Examples:\n"
            "  plexadm studio set-title 'New Sensations' 'new sensations'\n"
            "  plexadm studio set-independent 'Alice'\n"
            "  plexadm studio rename 'Old Studio' 'New Studio'"
        ),
    )
    studio_sub = _add_subparsers(studio, dest="studio_command", title="studio subcommands")

    set_title = _make_sub(
        studio_sub,
        "set-title",
        help="Set the studio on every video whose title matches PATTERN.",
        description=(
            "For every video whose title contains PATTERN (case-insensitive), set the\n"
            "studio to STUDIO unless one is already set. Locks the studio label.\n"
            "Skips videos with a different studio already assigned."
        ),
        epilog="Example:\n  plexadm studio set-title 'New Sensations' 'new sensations' --skip-scenes",
    )
    set_title.add_argument("studio", metavar="STUDIO", help="Studio name to assign.")
    set_title.add_argument("pattern", metavar="PATTERN", help="Title substring to match (case-insensitive).")
    set_title.add_argument(
        "--require-writer",
        action="store_true",
        help="Additionally require that PATTERN appears as an exact writer on the video.",
    )
    set_title.add_argument(
        "--skip-scenes",
        action="store_true",
        help="Skip videos whose title contains ' (Scene #'.",
    )
    set_func(set_title, set_studio_for_title_matches)

    set_independent = _make_sub(
        studio_sub,
        "set-independent",
        help=f"Mark videos as '{INDEPENDENT_STUDIO}' when title matches PATTERN and the writer is exact.",
        description=(
            f"Shortcut for `studio set-title '{INDEPENDENT_STUDIO}' PATTERN --require-writer --skip-scenes`.\n"
            "Used to bulk-tag indie content where the writer name appears in the title."
        ),
        epilog="Example:\n  plexadm studio set-independent 'Alice'",
    )
    set_independent.add_argument(
        "pattern",
        metavar="PATTERN",
        help="Writer/title substring to match (case-insensitive).",
    )
    set_independent.set_defaults(studio=INDEPENDENT_STUDIO, require_writer=True, skip_scenes=True)
    set_func(set_independent, set_studio_for_title_matches)

    bulk_independent = _make_sub(
        studio_sub,
        "bulk-independent",
        help="Mark videos as Independent based on a writer-list file.",
        description=(
            "Read writer names from FILE (one per line). For every studio-less video\n"
            f"whose title contains one of those writers AND who is an exact writer on\n"
            f"the video, set the studio to '{INDEPENDENT_STUDIO}' (skipping scenes)."
        ),
        epilog="Example:\n  plexadm studio bulk-independent /usr/local/share/plexadm/reference/independent_writers.txt",
    )
    bulk_independent.add_argument("file", metavar="FILE", help="Path to writer-list file (one name per line).")
    set_func(bulk_independent, set_independent_for_writers_file)

    rename_studio_parser = _make_sub(
        studio_sub,
        "rename",
        help="Rename a studio across every video that has it.",
        description="Find every video whose studio equals OLD and update it to NEW. Locks the label after editing.",
        epilog="Example:\n  plexadm studio rename 'Old Studio' 'New Studio'",
    )
    rename_studio_parser.add_argument("old", metavar="OLD", help="Existing studio name.")
    rename_studio_parser.add_argument("new", metavar="NEW", help="Replacement studio name.")
    set_func(rename_studio_parser, rename_studio)


def _build_writers_commands(sub: Any) -> None:
    writers_parser = _make_sub(
        sub,
        "writers",
        help="Mutate the writer field on videos based on their titles.",
        description=(
            "Commands that derive writers from video titles using the project's\n"
            "title-parsing rules (comma- and dash-separated names)."
        ),
        epilog=("Examples:\n  plexadm writers set-from-titles\n  plexadm writers set-and-sync"),
    )
    writers_sub = _add_subparsers(writers_parser, dest="writers_command", title="writers subcommands")

    set_from_titles = _make_sub(
        writers_sub,
        "set-from-titles",
        help="Add writers parsed from each video's title to that video.",
        description=(
            "For every video, parse writer names out of the title (e.g.\n"
            "'Alice, Bob - Foo') and add any that are missing from the writer list."
        ),
        epilog="Example:\n  plexadm writers set-from-titles",
    )
    set_func(set_from_titles, set_writers_from_titles)

    set_and_sync = _make_sub(
        writers_sub,
        "set-and-sync",
        help="Run `writers set-from-titles` then `smart-collections sync`.",
        description=(
            "Convenience for the common end-of-import flow: derive writers from\n"
            "titles, then create any missing studio/writer smart collections."
        ),
        epilog="Example:\n  plexadm writers set-and-sync",
    )
    set_func(set_and_sync, set_writers_and_sync)


def _build_smart_collection_commands(sub: Any) -> None:
    smart = _make_sub(
        sub,
        "smart-collections",
        help="Manage auto-generated smart collections for studios and writers.",
        description="Create or rename the smart collections that mirror the studio/writer taxonomy.",
        epilog=(
            "Examples:\n  plexadm smart-collections sync\n  plexadm smart-collections rename '^02: Studio: ' '02: '"
        ),
    )
    smart_sub = _add_subparsers(smart, dest="smart_command", title="smart-collections subcommands")

    sync = _make_sub(
        smart_sub,
        "sync",
        help="Create missing '02: Studio:' and '03: Star:' smart collections.",
        description=(
            "Scan every video and create any missing smart collection of the form\n"
            f"'02: Studio: <studio>' (or '02: {INDEPENDENT_STUDIO}' for indie) and\n"
            "'03: Star: <writer>'. Existing collections are left alone."
        ),
        epilog="Example:\n  plexadm smart-collections sync",
    )
    set_func(sync, sync_smart_collections)

    clone = _make_sub(
        smart_sub,
        "clone",
        help="Clone a smart collection under a new name, AND-combined with an extra filter.",
        description=(
            "Read SOURCE's existing smart-filter tree and create TARGET as a new smart\n"
            "collection with the same conditions plus --add-filter AND-combined in.\n"
            "SOURCE must be a smart collection; TARGET must not already exist."
        ),
        epilog=(
            "Example:\n"
            "  plexadm smart-collections clone '00D: Review: No Hair Color' "
            "'00D: Review: No Hair Color (Indie)' --add-filter '{\"studio\": \"Independent\"}'"
        ),
    )
    clone.add_argument("source", metavar="SOURCE", help="Existing smart collection to clone from.")
    clone.add_argument("target", metavar="TARGET", help="New smart collection name to create.")
    clone.add_argument(
        "--add-filter",
        required=True,
        metavar="JSON",
        help="Extra Plex advanced-search filter as a JSON object, AND-combined with SOURCE's filters.",
    )
    set_func(clone, clone_smart_collection)

    rename_collection_parser = _make_sub(
        smart_sub,
        "rename",
        help="Bulk-rename collections using a regex substitution.",
        description=(
            "For every collection whose title matches the Python regex PATTERN,\n"
            "rename it by applying re.sub(PATTERN, REPLACEMENT, title). Both smart\n"
            "and manual collections are affected."
        ),
        epilog=(
            "Examples:\n"
            "  plexadm smart-collections rename '^02: Studio: ' '02: '\n"
            "  plexadm smart-collections rename '01: Hair:' '01: Hair Color:'"
        ),
    )
    rename_collection_parser.add_argument("pattern", metavar="PATTERN", help="Python regex to match.")
    rename_collection_parser.add_argument(
        "replacement",
        metavar="REPLACEMENT",
        help="Replacement string passed to re.sub (supports backrefs like \\1).",
    )
    set_func(rename_collection_parser, rename_collections)

    retarget_ppv_parser = _make_sub(
        smart_sub,
        "retarget-ppv",
        help="Retire a writer-specific PPV collection in favor of a shared PPV collection.",
        description=(
            "Move every video in --old-collection into --new-collection (skipping ones\n"
            "already there, then removing them all from --old-collection). Then find\n"
            "every smart collection whose title contains --name-contains and whose filter\n"
            "is exactly 'collection = OLD', and repoint it at\n"
            "'collection = NEW AND writer = WRITER'. Smart collections that reference\n"
            "OLD alongside other conditions are left alone and reported for manual review."
        ),
        epilog=(
            "Example:\n"
            "  plexadm smart-collections retarget-ppv --writer 'WRITER NAME' "
            f"--old-collection 'WRITER PPV COLLECTION' --new-collection '{PPV_COLLECTION}' --name-contains 'WRITER'"
        ),
    )
    retarget_ppv_parser.add_argument(
        "--writer", required=True, metavar="WRITER", help="Writer name to combine with NEW in the retargeted filter."
    )
    retarget_ppv_parser.add_argument(
        "--old-collection", required=True, metavar="OLD", help="Writer-specific PPV collection to retire."
    )
    retarget_ppv_parser.add_argument(
        "--new-collection", required=True, metavar="NEW", help="Shared PPV collection to move videos into."
    )
    retarget_ppv_parser.add_argument(
        "--name-contains",
        required=True,
        metavar="TEXT",
        help="Only retarget smart collections whose title contains this text (case-insensitive).",
    )
    set_func(retarget_ppv_parser, retarget_writer_ppv)


def _build_tools_commands(sub: Any) -> None:
    tools = _make_sub(
        sub,
        "tools",
        help="Miscellaneous file-system helpers (renaming, missing-file lookups, uploads).",
        description="One-off helpers that operate on files on disk rather than on Plex metadata.",
        epilog=(
            "Examples:\n"
            "  plexadm tools find-missing-file '/data/NSFW Scenes/Alice/foo.mp4'\n"
            "  plexadm tools fix-dl-scene-name 'scene.mp4' --prefix 'Alice'\n"
            "  plexadm tools upload-vids --remote-host truenas"
        ),
    )
    tools_sub = _add_subparsers(tools, dest="tools_command", title="tools subcommands")

    missing = _make_sub(
        tools_sub,
        "find-missing-file",
        help="Find the Plex item that owns a given on-disk file.",
        description="Walk every video and print the title of any whose locations contain PATH. Exits non-zero if none match.",
        epilog="Example:\n  plexadm tools find-missing-file '/data/NSFW Scenes/Alice/foo.mp4'",
    )
    missing.add_argument("path", metavar="PATH", help="Absolute on-disk path to look up.")
    set_func(missing, find_missing_file)

    dl = _make_sub(
        tools_sub,
        "fix-dl-scene-name",
        help="Prefix a downloaded scene filename so it sorts under a known writer.",
        description=(
            "Print FILENAME prefixed with 'TBD - ' (or '<prefix> - ' if --prefix is given).\n"
            "This is a pure transform; it does not move the file."
        ),
        epilog="Example:\n  plexadm tools fix-dl-scene-name 'scene.mp4' --prefix 'Alice'",
    )
    dl.add_argument("filename", metavar="FILENAME", help="Source filename to prefix.")
    dl.add_argument(
        "--prefix",
        metavar="PREFIX",
        help="Writer/studio prefix to insert before the filename (default: 'TBD').",
    )
    dl.set_defaults(func=fix_dl_scene_name)

    ultra = _make_sub(
        tools_sub,
        "fix-ultrafilms-name",
        help="Titleise an UltraFilms-style underscored filename.",
        description=(
            "Split FILENAME on whitespace/underscores, title-case every part, apply\n"
            "the project's writer-name aliases, and print the result with the original\n"
            "extension preserved."
        ),
        epilog="Example:\n  plexadm tools fix-ultrafilms-name 'kate_rose_scene.mp4'",
    )
    ultra.add_argument("filename", metavar="FILENAME", help="Source filename to titleise.")
    ultra.set_defaults(func=fix_ultrafilms_name)

    ofdl_names = _make_sub(
        tools_sub,
        "ofdl-gen-names",
        help="Dump the indie-username-to-writer-name mapping from a JSON file.",
        description="Read the mapping JSON file and print `<source>: <target>` lines sorted by source.",
        epilog="Example:\n  plexadm tools ofdl-gen-names --map-file indie_usernames_to_map.json",
    )
    ofdl_names.add_argument(
        "--map-file",
        default="indie_usernames_to_map.json",
        metavar="FILE",
        help="Path to the mapping JSON file (default: indie_usernames_to_map.json).",
    )
    ofdl_names.set_defaults(func=gen_ofdl_names)

    rsync = _make_sub(
        tools_sub,
        "ofdl-rsync",
        help="Run `rsync -avh --progress SOURCE DESTINATION` and return its exit code.",
        description="Thin wrapper that prints the rsync command then executes it.",
        epilog="Example:\n  plexadm tools ofdl-rsync ./downloads/ truenas:/mnt/data/incoming/",
    )
    rsync.add_argument("source", metavar="SOURCE", help="rsync source path.")
    rsync.add_argument("destination", metavar="DESTINATION", help="rsync destination path.")
    rsync.set_defaults(func=ofdl_rsync)

    fps = _make_sub(
        tools_sub,
        "remove-fps-title",
        help="Rename FILENAME on disk to strip embedded fps suffixes (_24fps, _30fps, ...).",
        description=(
            "Rename FILENAME, removing any `_{24,25,30,35,40,45,50,60,65,...}fps` suffix\n"
            "in the basename. The rename uses shutil.move; the file is modified in place."
        ),
        epilog="Example:\n  plexadm tools remove-fps-title 'scene_60fps.mp4'",
    )
    fps.add_argument("filename", metavar="FILENAME", help="File to rename.")
    fps.set_defaults(func=remove_fps_title)

    upload = _make_sub(
        tools_sub,
        "upload-vids",
        help="scp every *.mp4 in the cwd to the configured Plex host, then delete locally.",
        description=(
            "For every *.mp4 in the current directory, derive the star/writer name from\n"
            "the filename (first segment before ',' or '-'), ensure the destination\n"
            "directory exists on the remote host, scp the file as `<name>.tmp`, then\n"
            "rename it into place and delete the local copy."
        ),
        epilog="Example:\n  plexadm tools upload-vids --remote-host truenas",
    )
    upload.add_argument(
        "--remote-host",
        default="truenas",
        metavar="HOST",
        help="SSH host to upload to (default: truenas).",
    )
    upload.add_argument(
        "--upload-path",
        default="/mnt/myzmirror/plexdata/NSFW Scenes",
        metavar="PATH",
        help="Remote base directory under which '<star>/<file>' will be placed (default: /mnt/myzmirror/plexdata/NSFW Scenes).",
    )
    upload.set_defaults(func=upload_vids)


def _build_top_command(sub: Any) -> None:
    top_help = {
        "categories": "count of videos per '01: Category:' collection, ranked low to high",
        "studios": "most common studios, ranked high to low",
        "writers-without-studios": "most common writer names among studio-less videos",
        "scenes-without-studios": "most common writer names among studio-less SCENES",
        "unrated-writers": f"most common writer names inside '{UNRATED_COLLECTION}'",
        "unrated-scenes": f"most common writer names inside '{UNRATED_COLLECTION}' for SCENES",
    }
    top = _make_sub(
        sub,
        "top",
        help="Print the top N items for one of the built-in rankings.",
        description=(
            "Rank library content by one of these SOURCES:\n\n"
            + "\n".join(f"  {key:<28}{desc}" for key, desc in top_help.items())
            + "\n\nUse --limit to control how many rows are printed. `scenes-without-studios`"
            "\nand `unrated-scenes` imply --scenes."
        ),
        epilog=(
            "Examples:\n"
            "  plexadm top categories --limit 25\n"
            "  plexadm top studios\n"
            "  plexadm top unrated-writers --limit 50"
        ),
    )
    top.add_argument(
        "source",
        choices=list(top_help),
        metavar="SOURCE",
        help="Ranking to print (see description for the list).",
    )
    top.add_argument(
        "--limit",
        type=int,
        default=15,
        metavar="N",
        help="Maximum number of rows to print (default: 15).",
    )
    top.add_argument(
        "--collection",
        metavar="NAME",
        help="Override the collection used for writer-name rankings.",
    )
    top.add_argument(
        "--scenes",
        action="store_true",
        help="Only count rows whose title contains 'Scene #' (implied by *-scenes sources).",
    )
    set_func(top, print_top)


def _build_stash_commands(sub: Any) -> None:
    from plexadm.stash_backfill_tags import (
        apply_review as stash_apply_review,
    )
    from plexadm.stash_backfill_tags import (
        backfill_tags as stash_backfill_tags,
    )
    from plexadm.stash_backfill_tags import (
        rename_tags as stash_rename_tags,
    )
    from plexadm.stash_backfill_tags import (
        unmapped_tags as stash_unmapped_tags,
    )

    stash_parser = _make_sub(
        sub,
        "stash",
        help="Commands that sync Plex metadata into a Stash library.",
        description=(
            "Commands that read from Plex and write metadata into a Stash instance.\n"
            "The Stash endpoint is read from the config file (stashEndpoint key)\n"
            "or overridden with --stash-endpoint."
        ),
        epilog="Example:\n  plexadm stash reconcile --limit 25",
    )
    stash_sub = _add_subparsers(stash_parser, dest="stash_command", title="stash subcommands")

    reconcile_parser = _make_sub(
        stash_sub,
        "reconcile",
        help="Backfill Stash scenes with Plex metadata (title, performers, studio, tags, rating).",
        description=(
            "Reads every Plex item in the configured library section, finds the\n"
            "corresponding Stash scene(s) by file path, and writes Plex metadata\n"
            "(title, writers→performers, studio, collections→tags, director,\n"
            "rating, play count) to each matched Stash scene.\n"
            "\n"
            "Only Plex collections prefixed '01: ' are mapped to Stash tags;\n"
            "the prefix is stripped (e.g. '01: Activity: Blowjob' → 'Activity: Blowjob').\n"
            "\n"
            "Outputs a per-scene change log and exports a CSV listing scenes that\n"
            "still need enrichment (matched with no Plex data, or Stash scenes with\n"
            "no Plex match at all).\n"
            "\n"
            "By default, triggers a Stash library scan (with phash generation) first\n"
            "and waits for it to finish, so newly-added Plex content is guaranteed to\n"
            "already be visible in Stash before matching starts. Use --skip-scan if\n"
            "you already scanned Stash yourself and want a faster run.\n"
            "\n"
            "Writes are applied immediately. Use --limit for a test run against a\n"
            "small subset before pointing this at the full library."
        ),
        epilog=(
            "Examples:\n"
            "  plexadm stash reconcile --limit 25\n"
            "  plexadm stash reconcile --log-level INFO\n"
            "  plexadm stash reconcile --csv-output scope.csv\n"
            "  plexadm stash reconcile --skip-scan"
        ),
    )
    reconcile_parser.add_argument(
        "--limit",
        metavar="N",
        type=int,
        help="Stop after processing N Plex items (useful for test runs before a full run).",
    )
    reconcile_parser.add_argument(
        "--path",
        metavar="PREFIX",
        help="Only process Plex items whose file path starts with PREFIX (e.g. /data/NSFW Scenes/Studio Name).",
    )
    reconcile_parser.add_argument(
        "--log-level",
        metavar="LEVEL",
        default="WARNING",
        dest="log_level",
        help="Python logging level: DEBUG, INFO, WARNING (default), ERROR.",
    )
    reconcile_parser.add_argument(
        "--stash-endpoint",
        metavar="URL",
        dest="stash_endpoint",
        default=None,
        help="Override the Stash base URL from config (e.g. http://localhost:9999).",
    )
    reconcile_parser.add_argument(
        "--csv-output",
        metavar="PATH",
        default="stash_scope.csv",
        dest="csv_output",
        help="Path for the scope CSV export (default: stash_scope.csv).",
    )
    reconcile_parser.add_argument(
        "--skip-scan",
        action="store_true",
        dest="skip_scan",
        help="Skip the automatic Stash library scan (with phash generation) that normally "
        "runs before reconciling. Use if you already scanned Stash yourself.",
    )
    set_func(reconcile_parser, stash_reconcile)

    backfill_parser = _make_sub(
        stash_sub,
        "backfill-tags",
        help="Backfill Plex composition collections from matched Stash scene tags.",
        description=(
            "Reads every Plex item in the configured library section, matches Stash\n"
            "scenes by file path, and immediately adds missing, unambiguous\n"
            "composition-category memberships to Plex. Potential removals and\n"
            "internally ambiguous Stash tags are written to a JSON review file and\n"
            "are never removed by this command."
        ),
        epilog=(
            "Examples:\n"
            "  plexadm stash backfill-tags --dry-run --limit 25\n"
            "  plexadm stash backfill-tags --review-output reference/stash_backfill_review.json"
        ),
    )
    backfill_parser.add_argument(
        "--limit",
        metavar="N",
        type=int,
        help="Stop after processing N Plex items (useful for test runs before a full run).",
    )
    backfill_parser.add_argument(
        "--path",
        metavar="PREFIX",
        help="Only process Plex items whose file path starts with PREFIX.",
    )
    backfill_parser.add_argument(
        "--log-level",
        metavar="LEVEL",
        default="WARNING",
        dest="log_level",
        help="Python logging level: DEBUG, INFO, WARNING (default), ERROR.",
    )
    backfill_parser.add_argument(
        "--stash-endpoint",
        metavar="URL",
        dest="stash_endpoint",
        default=None,
        help="Override the Stash base URL from config.",
    )
    backfill_parser.add_argument(
        "--review-output",
        metavar="PATH",
        default="reference/stash_backfill_review.json",
        dest="review_output",
        help="Path for staged removals and ambiguous entries (default: reference/stash_backfill_review.json).",
    )
    backfill_parser.add_argument(
        "--report-output",
        metavar="PATH",
        default="reference/stash_backfill_report.md",
        dest="report_output",
        help="Markdown run report path (default: reference/stash_backfill_report.md).",
    )
    set_func(backfill_parser, stash_backfill_tags)

    unmapped_tags_parser = _make_sub(
        stash_sub,
        "unmapped-tags",
        help="Report Stash tags that have no matching Plex collection.",
        description=(
            "Fetches every Stash tag and compares its mapped collection title\n"
            "against the collections that currently exist in the configured Plex\n"
            "library. Writes every gap to a markdown report sorted by scene count."
        ),
        epilog="Example:\n  plexadm stash unmapped-tags --output reference/stash_unmapped_tags.md",
    )
    unmapped_tags_parser.add_argument(
        "--output",
        metavar="PATH",
        default="reference/stash_unmapped_tags.md",
        help="Markdown report path (default: reference/stash_unmapped_tags.md).",
    )
    unmapped_tags_parser.add_argument(
        "--stash-endpoint",
        metavar="URL",
        dest="stash_endpoint",
        default=None,
        help="Override the Stash base URL from config.",
    )
    unmapped_tags_parser.add_argument(
        "--log-level",
        metavar="LEVEL",
        default="WARNING",
        dest="log_level",
        help="Python logging level: DEBUG, INFO, WARNING (default), ERROR.",
    )
    set_func(unmapped_tags_parser, stash_unmapped_tags)

    rename_tags_parser = _make_sub(
        stash_sub,
        "rename-tags",
        help="Rename the Stash tags backing the composition taxonomy (Solo, FFM, Lesbian, etc.).",
        description=(
            "Renames the Stash tags that classify_scene() reads for composition backfill\n"
            "(e.g. 'Category: Solo' -> 'Composition: Solo') to match the new Plex taxonomy.\n"
            "\n"
            "This is a prerequisite for `plexadm collection rename-categories\n"
            "--include-composition`: composition matching compares Stash tag names and\n"
            "Plex-collection-derived tag names by exact string, so renaming the Plex\n"
            "collections without also renaming these Stash tags breaks that matching.\n"
            "Run this first, update GROUP_SINGLE_FEMALE/GROUP_MULTI_FEMALE_HEADCOUNT/\n"
            "GROUP_MULTI_FEMALE_ACTIVITY in stash_backfill_tags.py to the new names in the\n"
            "same change, then run rename-categories --include-composition."
        ),
        epilog="Example:\n  plexadm stash rename-tags --dry-run",
    )
    rename_tags_parser.add_argument(
        "--stash-endpoint",
        metavar="URL",
        dest="stash_endpoint",
        default=None,
        help="Override the Stash base URL from config.",
    )
    rename_tags_parser.add_argument(
        "--log-level",
        metavar="LEVEL",
        default="WARNING",
        dest="log_level",
        help="Python logging level: DEBUG, INFO, WARNING (default), ERROR.",
    )
    set_func(rename_tags_parser, stash_rename_tags)

    apply_review_parser = _make_sub(
        stash_sub,
        "apply-review",
        help="Apply human-reviewed composition-category removals to Plex.",
        description=(
            "Reads a JSON review file produced by `stash backfill-tags` and removes\n"
            "the surviving remove-candidate memberships. Ambiguous entries are\n"
            "skipped unless --include-ambiguous is supplied and the human reviewer\n"
            "has added a collection_to_remove field."
        ),
        epilog="Example:\n  plexadm stash apply-review reference/stash_backfill_review.json --dry-run",
    )
    apply_review_parser.add_argument(
        "review_file",
        metavar="REVIEW_FILE",
        help="Human-reviewed JSON file produced by `stash backfill-tags`.",
    )
    apply_review_parser.add_argument(
        "--include-ambiguous",
        action="store_true",
        help="Also apply ambiguous entries that a reviewer gave a collection_to_remove field.",
    )
    apply_review_parser.add_argument(
        "--log-level",
        metavar="LEVEL",
        default="WARNING",
        dest="log_level",
        help="Python logging level: DEBUG, INFO, WARNING (default), ERROR.",
    )
    set_func(apply_review_parser, stash_apply_review)

    sync_tags_parser = _make_sub(
        stash_sub,
        "sync-tags",
        help="Sync manual Plex collection membership as Stash tags.",
        description=(
            "Walks every non-smart Plex collection (excluding BROKEN, CORRUPT,\n"
            "and auto-managed prefixes like '01: Category:', '02: Studio:', etc.)\n"
            "and tags the corresponding Stash scenes with the derived tag name\n"
            "(leading sort prefix stripped, e.g. '00A: FAVORITES' → 'FAVORITES').\n"
            "\n"
            "Safe to re-run: existing tags are preserved and duplicates are skipped."
        ),
        epilog="Example:\n  plexadm stash sync-tags",
    )
    sync_tags_parser.add_argument(
        "--log-level",
        metavar="LEVEL",
        default="WARNING",
        dest="log_level",
        help="Python logging level: DEBUG, INFO, WARNING (default), ERROR.",
    )
    sync_tags_parser.add_argument(
        "--stash-endpoint",
        metavar="URL",
        dest="stash_endpoint",
        default=None,
        help="Override the Stash base URL from config.",
    )
    set_func(sync_tags_parser, stash_sync_tags)


def _build_inventory_commands(sub: Any) -> None:
    inventory_parser = _make_sub(
        sub,
        "inventory",
        help="Snapshot and diff every video's full collection membership over time.",
        description=(
            "Distinct from plexadm's own audit trail (which only records what plexadm itself\n"
            "did): this records what the state actually looks like right now, regardless of\n"
            "what changed it - so drift from any source (a stray Plex Web edit, an agent, "
            "anything) can be pinpointed by diffing snapshots, rather than reconstructed after\n"
            "the fact from server logs. Requires an [inventory] section (at least 'url') in\n"
            "the config file, pointing at an OpenSearch cluster."
        ),
        epilog=("Examples:\n  plexadm inventory snapshot\n  plexadm inventory diff"),
    )
    inventory_sub = _add_subparsers(inventory_parser, dest="inventory_command", title="inventory subcommands")

    snapshot_parser = _make_sub(
        inventory_sub,
        "snapshot",
        help="Record one document per video with its current full collection membership.",
        description=(
            "Write one document per video to the configured OpenSearch index, capturing\n"
            "rating_key, title, studio, writers, and the full sorted list of collections it\n"
            "currently belongs to, tagged with a shared run_id/timestamp for this run."
        ),
        epilog="Example:\n  plexadm inventory snapshot",
    )
    set_func(snapshot_parser, inventory_snapshot)

    diff_parser = _make_sub(
        inventory_sub,
        "diff",
        help="Compare two snapshots and report every video whose collections changed.",
        description=(
            "Defaults to the two most recent snapshots. For each video whose collection set\n"
            "changed, cross-checks plexadm's own audit trail (when it's configured with an\n"
            "OpenSearch sink) for a matching add/remove event in that time window, and flags\n"
            "any change with none as UNATTRIBUTED - the case where something other than\n"
            "plexadm changed it."
        ),
        epilog="Example:\n  plexadm inventory diff",
    )
    diff_parser.add_argument("--run-a", dest="run_a", metavar="RUN_ID", default=None, help="Older snapshot run_id.")
    diff_parser.add_argument("--run-b", dest="run_b", metavar="RUN_ID", default=None, help="Newer snapshot run_id.")
    diff_parser.add_argument(
        "--no-attribution",
        action="store_true",
        help="Skip cross-checking the plexadm-audit trail; just report raw changes.",
    )
    set_func(diff_parser, inventory_diff)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    audit.configure(load_logging_config(args.config))
    audit.set_invocation_context(rule=args.func.__name__, argv=sys.argv)
    if args.command == "top" and args.source in {"scenes-without-studios", "unrated-scenes"}:
        args.scenes = True
    start = time.monotonic()
    try:
        result = int(args.func(args) or 0)
    except KeyboardInterrupt:
        audit.log_event(
            audit.AuditEvent(action="interrupted", level="WARNING", title=f"Interrupted during '{args.func.__name__}'")
        )
        print(fail("Interrupted."))
        return 130
    except Exception as exc:
        audit.log_error(str(exc), exc=exc)
        print(fail(str(exc)))
        return 1
    finally:
        audit.log_event(
            audit.AuditEvent(
                action="timing",
                title=f"'{args.func.__name__}' finished",
                details={"duration_seconds": round(time.monotonic() - start, 3)},
            )
        )
    if audit.has_failures():
        print(fail("One or more audit log writes failed during this run - see above."))
        return 1
    return result
