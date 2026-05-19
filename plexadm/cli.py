from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

from plexadm import __version__
from plexadm.console import fail, info, ok, warn
from plexadm.filters import and_filter, in_collection, not_in_collection, rated, title_contains, unrated, writer_any
from plexadm.plex import PlexContext, add_items, collection_titles, has_collection, reload_if_partial, remove_items
from plexadm.progress import progress_prefix
from plexadm.writers import missing_title_writers, read_writer_file, writers_from_title

NO_STUDIO_COLLECTION = "00A: NO STUDIO2"
UNRATED_COLLECTION = "00C: Unrated"
INDEPENDENT_STUDIO = "Independent Content"
LOCKED_COLLECTION = "99: LOCKED"

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
    "01: Category: Trans MTF",
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

EXCLUDED_MONEYSHOT_COLLECTIONS = [
    "01: Category: Creampie",
    "01: Category: Cum Swap",
    "01: Category: Facial",
    "01: Category: Internal",
    "01: Category: Non-Sexual",
    "01: Category: Swallow",
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
    added = add_items(collection, matches)
    print(info(f"{matched_count} matches found, {added} collections added."))
    return 0


def add_search_results(args: argparse.Namespace) -> int:
    ctx = build_context(args)
    collection = ctx.collection(args.collection)
    filters = and_filter(not_in_collection(collection.title), title_contains(args.pattern))
    print(info(f"Search filters: {filters}"))
    results = ctx.search(filters=filters, reload=True)
    for index, video in enumerate(results, 1):
        print(warn(f"{progress_prefix(index, len(results))}'{video.title}' needs to be added to '{collection.title}'"))
    added = add_items(collection, results)
    print(info(f"{len(results)} matches found, {added} collections added."))
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
    added = add_items(collection, matches)
    print(info(f"{matched_count} matches found, {added} collections added."))
    return 0


def add_writers_file(args: argparse.Namespace) -> int:
    ctx = build_context(args)
    collection = ctx.collection(args.collection)
    writers = read_writer_file(args.file)
    filters = and_filter(not_in_collection(collection.title), not_in_collection(LOCKED_COLLECTION), writer_any(writers))
    print(info(f"Search filters: {filters}"))
    results = ctx.search(filters=filters, reload=True)
    for index, video in enumerate(results, 1):
        print(warn(f"{progress_prefix(index, len(results))}'{video.title}' needs to be added to '{collection.title}'"))
    added = add_items(collection, results)
    print(info(f"{len(results)} matches found, {added} collections added."))
    return 0


def copy_collection(args: argparse.Namespace) -> int:
    ctx = build_context(args)
    source = ctx.collection(args.source)
    target = ctx.collection(args.target)
    filters = and_filter(in_collection(source.title), not_in_collection(target.title))
    results = ctx.search(filters=filters, reload=True)
    for index, video in enumerate(results, 1):
        print(warn(f"{progress_prefix(index, len(results))}'{video.title}' needs to be added to '{target.title}'"))
    added = add_items(target, results)
    print(info(f"{len(results)} matches found, {added} collections added."))
    return 0


def copy_studio(args: argparse.Namespace) -> int:
    ctx = build_context(args)
    target = ctx.collection(args.collection)
    filters = and_filter({"studio": args.studio}, not_in_collection(target.title))
    results = ctx.search(filters=filters, reload=True)
    for index, video in enumerate(results, 1):
        print(warn(f"{progress_prefix(index, len(results))}'{video.title}' needs to be added to '{target.title}'"))
    added = add_items(target, results)
    print(info(f"{len(results)} matches found, {added} collections added."))
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
    removed = remove_items(collection, matches)
    print(info(f"{len(matches)} matches found, {removed} collections removed."))
    return 0


def add_duration_collection(args: argparse.Namespace) -> int:
    ctx = build_context(args)
    collection = ctx.collection(args.collection)
    filters = and_filter({"duration<<": args.max_duration_ms}, not_in_collection(collection.title))
    results = ctx.search(filters=filters, reload=True)
    for video in results:
        print(warn(f"'{video.title}' needs to be added to '{collection.title}'"))
    added = add_items(collection, results)
    print(info(f"{added} videos added to '{collection.title}'."))
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
    added = add_items(collection, matches)
    print(info(f"{added} vertical videos added to '{collection.title}'."))
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
    added = add_items(collection, to_add)
    removed = remove_items(collection, to_remove)
    print(info(f"{added} collections added."))
    print(info(f"{removed} collections removed."))
    return 0


def sync_no_studio(args: argparse.Namespace) -> int:
    ctx = build_context(args)
    collection = ctx.collection(args.collection)
    to_add = ctx.search(studio__exact="", sort="titleSort", reload=True)
    to_add = [video for video in to_add if not has_collection(video, collection.title)]
    to_remove = ctx.search(filters=and_filter({"studio!": ""}, {"collection=": collection.title}), reload=True)
    for video in to_add:
        print(warn(f"'{video.title}' needs to be added to '{collection.title}'"))
    for video in to_remove:
        print(warn(f"'{video.title}' needs to be removed from '{collection.title}'"))
    added = add_items(collection, to_add)
    removed = remove_items(collection, to_remove)
    print(info(f"{added} collections added."))
    print(info(f"{removed} collections removed."))
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
            video.edit(**{"studio.value": args.studio, "label.locked": 1})
            changed += 1
        elif video.studio == args.studio:
            print(info(f"'{video.title}' is already part of '{args.studio}'"))
        else:
            print(warn(f"'{video.title}' already belongs to studio '{video.studio}', skipping."))
    print(info(f"{matched} matches found, {changed} studios added."))
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
            video.edit(**{"studio.value": INDEPENDENT_STUDIO, "label.locked": 1})
            changed += 1
    print(info(f"{changed} studios added."))
    return 0


def rename_studio(args: argparse.Namespace) -> int:
    ctx = build_context(args)
    results = ctx.search(studio__exact=args.old, sort="titleSort", reload=True)
    for video in results:
        print(warn(f"'{video.title}' needs studio rename '{args.old}' -> '{args.new}'"))
        video.edit(**{"studio.value": args.new, "label.locked": 1})
    print(info(f"{len(results)} videos updated."))
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
    elif args.kind == "no-moneyshot":
        excluded = [not_in_collection(name) for name in EXCLUDED_MONEYSHOT_COLLECTIONS]
        videos = ctx.search(filters=and_filter(*excluded), reload=False)
    elif args.kind == "uncollected":
        videos = [video for video in ctx.all_videos(reload=True) if not collection_titles(video)]
    elif args.kind == "multipart":
        videos = [
            video
            for video in ctx.all_videos(reload=True)
            if len(getattr(video, "media", []) or []) > 1
            or any(len(getattr(media, "parts", []) or []) > 1 for media in getattr(video, "media", []) or [])
        ]
    elif args.kind == "merged":
        videos = [video for video in ctx.all_videos(reload=True) if len(getattr(video, "guids", []) or []) > 1]
    elif args.kind == "potential-indie":
        videos = [
            video
            for video in ctx.all_videos()
            if not is_scene(video) and not getattr(video, "studio", None) and " - " in video.title
        ]
    elif args.kind == "multi-f-without-category":
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
            video.addWriter(writers_from_title(video.title), True)
            changed += 1
    print(ok(f"{changed} videos updated."))
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
            ctx.section.createCollection(title=title, smart=True, sort="titleSort:asc", filters={"studio": studio})
            created += 1
    for writer in sorted(writers):
        title = f"03: Star: {writer}"
        if title.lower() not in existing:
            print(warn(f"Creating smart collection '{title}'"))
            ctx.section.createCollection(title=title, smart=True, sort="titleSort:asc", filters={"writer": writer})
            created += 1
    print(ok(f"Newly created smart collections: {created}"))
    return 0


def set_writers_and_sync(args: argparse.Namespace) -> int:
    set_writers_from_titles(args)
    return sync_smart_collections(args)


def rename_collections(args: argparse.Namespace) -> int:
    ctx = build_context(args)
    pattern = re.compile(args.pattern)
    changed = 0
    for collection in ctx.section.collections():
        reload_if_partial(collection)
        new_title = pattern.sub(args.replacement, collection.title)
        if new_title != collection.title:
            print(warn(f"Renaming '{collection.title}' to '{new_title}'"))
            collection.editTitle(new_title)
            changed += 1
    print(info(f"{changed} collections renamed."))
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

        filename = Path(locations[0]).name
        match_found = any(video.title in location for location in locations)

        if (
            " - Message " in filename
            or " - Post " in filename
            or "PPV" in filename
            or " PPV " in locations[0]
            or "?" in video.title
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
            if "01: Category: " in collection.title:
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


def add_common_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", help="Path to Plex config file")


def set_func(parser: argparse.ArgumentParser, func: Any) -> None:
    add_common_parser(parser)
    parser.set_defaults(func=func)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="plexadm")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    list_parser = sub.add_parser("list")
    list_sub = list_parser.add_subparsers(dest="list_command", required=True)
    videos = list_sub.add_parser("videos")
    videos.add_argument("--title")
    videos.add_argument("--startswith")
    videos.add_argument("--regex")
    videos.add_argument("--search-title")
    videos.add_argument("--collection")
    videos.add_argument("--studio")
    videos.add_argument("--writer")
    videos.add_argument("--no-studio", action="store_true")
    videos.add_argument("--no-title-spaces", action="store_true")
    videos.add_argument("--reload", action="store_true")
    set_func(videos, list_videos)
    collections = list_sub.add_parser("collections")
    collections.add_argument("pattern", nargs="?")
    set_func(collections, list_collections)
    studios = list_sub.add_parser("studios")
    studios.add_argument("pattern", nargs="?")
    set_func(studios, list_studios)
    writers = list_sub.add_parser("writers")
    writers.add_argument("--collection")
    set_func(writers, list_writers)
    studio_writers = list_sub.add_parser("studio-writers")
    studio_writers.add_argument("studio")
    set_func(studio_writers, list_studio_writers)
    renames = list_sub.add_parser("renames")
    renames.add_argument(
        "filter_text", nargs="?", help="Only include videos where title or file path contains this text."
    )
    renames.add_argument("--script", action="store_true", help="Output mv commands instead of human-readable diff.")
    renames.add_argument("--base-dir", default=SCENE_BASE_DIR, help="Base directory prefix to strip from file paths.")
    set_func(renames, list_renames)
    special = list_sub.add_parser("special")
    special.add_argument(
        "kind",
        choices=[
            "uncategorized",
            "uncollected",
            "multipart",
            "merged",
            "potential-indie",
            "multi-f-without-category",
            "no-composition",
            "no-hair",
            "no-moneyshot",
        ],
    )
    set_func(special, list_special)

    collection = sub.add_parser("collection")
    collection_sub = collection.add_subparsers(dest="collection_command", required=True)
    add_title = collection_sub.add_parser("add-title")
    add_title.add_argument("collection")
    add_title.add_argument("pattern")
    add_title.add_argument("--startswith", action="store_true")
    add_title.add_argument("--skip-scenes", action="store_true")
    set_func(add_title, add_matching_titles)
    add_search = collection_sub.add_parser("add-search")
    add_search.add_argument("collection")
    add_search.add_argument("pattern")
    set_func(add_search, add_search_results)
    add_writer = collection_sub.add_parser("add-writer")
    add_writer.add_argument("collection")
    add_writer.add_argument("pattern")
    set_func(add_writer, add_writer_matches)
    add_writers = collection_sub.add_parser("add-writers")
    add_writers.add_argument("collection")
    add_writers.add_argument("file")
    set_func(add_writers, add_writers_file)
    copy = collection_sub.add_parser("copy")
    copy.add_argument("source")
    copy.add_argument("target")
    set_func(copy, copy_collection)
    copy_studio_parser = collection_sub.add_parser("copy-studio")
    copy_studio_parser.add_argument("studio")
    copy_studio_parser.add_argument("collection")
    set_func(copy_studio_parser, copy_studio)
    remove_title = collection_sub.add_parser("remove-title")
    remove_title.add_argument("collection")
    remove_title.add_argument("pattern")
    set_func(remove_title, remove_matching_titles)
    add_short = collection_sub.add_parser("add-short")
    add_short.add_argument("collection")
    add_short.add_argument("--max-duration-ms", type=int, default=90_000)
    set_func(add_short, add_duration_collection)
    add_vertical = collection_sub.add_parser("add-vertical")
    add_vertical.add_argument("collection")
    set_func(add_vertical, add_vertical_collection)
    sync_unrated_parser = collection_sub.add_parser("sync-unrated")
    sync_unrated_parser.add_argument("collection", nargs="?", default=UNRATED_COLLECTION)
    set_func(sync_unrated_parser, sync_unrated)
    sync_no_studio_parser = collection_sub.add_parser("sync-no-studio")
    sync_no_studio_parser.add_argument("collection", nargs="?", default=NO_STUDIO_COLLECTION)
    set_func(sync_no_studio_parser, sync_no_studio)

    studio = sub.add_parser("studio")
    studio_sub = studio.add_subparsers(dest="studio_command", required=True)
    set_title = studio_sub.add_parser("set-title")
    set_title.add_argument("studio")
    set_title.add_argument("pattern")
    set_title.add_argument("--require-writer", action="store_true")
    set_title.add_argument("--skip-scenes", action="store_true")
    set_func(set_title, set_studio_for_title_matches)
    set_independent = studio_sub.add_parser("set-independent")
    set_independent.add_argument("pattern")
    set_independent.set_defaults(studio=INDEPENDENT_STUDIO, require_writer=True, skip_scenes=True)
    set_func(set_independent, set_studio_for_title_matches)
    bulk_independent = studio_sub.add_parser("bulk-independent")
    bulk_independent.add_argument("file")
    set_func(bulk_independent, set_independent_for_writers_file)
    rename_studio_parser = studio_sub.add_parser("rename")
    rename_studio_parser.add_argument("old")
    rename_studio_parser.add_argument("new")
    set_func(rename_studio_parser, rename_studio)

    writers_parser = sub.add_parser("writers")
    writers_sub = writers_parser.add_subparsers(dest="writers_command", required=True)
    set_from_titles = writers_sub.add_parser("set-from-titles")
    set_func(set_from_titles, set_writers_from_titles)
    set_and_sync = writers_sub.add_parser("set-and-sync")
    set_func(set_and_sync, set_writers_and_sync)

    smart = sub.add_parser("smart-collections")
    smart_sub = smart.add_subparsers(dest="smart_command", required=True)
    sync = smart_sub.add_parser("sync")
    set_func(sync, sync_smart_collections)
    rename_collection_parser = smart_sub.add_parser("rename")
    rename_collection_parser.add_argument("pattern")
    rename_collection_parser.add_argument("replacement")
    set_func(rename_collection_parser, rename_collections)

    tools = sub.add_parser("tools")
    tools_sub = tools.add_subparsers(dest="tools_command", required=True)
    missing = tools_sub.add_parser("find-missing-file")
    missing.add_argument("path")
    set_func(missing, find_missing_file)
    dl = tools_sub.add_parser("fix-dl-scene-name")
    dl.add_argument("filename")
    dl.add_argument("--prefix")
    dl.set_defaults(func=fix_dl_scene_name)
    ultra = tools_sub.add_parser("fix-ultrafilms-name")
    ultra.add_argument("filename")
    ultra.set_defaults(func=fix_ultrafilms_name)
    ofdl_names = tools_sub.add_parser("ofdl-gen-names")
    ofdl_names.add_argument("--map-file", default="indie_usernames_to_map.json")
    ofdl_names.set_defaults(func=gen_ofdl_names)
    rsync = tools_sub.add_parser("ofdl-rsync")
    rsync.add_argument("source")
    rsync.add_argument("destination")
    rsync.set_defaults(func=ofdl_rsync)
    fps = tools_sub.add_parser("remove-fps-title")
    fps.add_argument("filename")
    fps.set_defaults(func=remove_fps_title)
    upload = tools_sub.add_parser("upload-vids")
    upload.add_argument("--remote-host", default="truenas")
    upload.add_argument("--upload-path", default="/mnt/myzmirror/plexdata/NSFW Scenes")
    upload.set_defaults(func=upload_vids)

    top = sub.add_parser("top")
    top.add_argument(
        "source",
        choices=[
            "categories",
            "studios",
            "writers-without-studios",
            "scenes-without-studios",
            "unrated-writers",
            "unrated-scenes",
        ],
    )
    top.add_argument("--limit", type=int, default=15)
    top.add_argument("--collection")
    top.add_argument("--scenes", action="store_true")
    set_func(top, print_top)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "top" and args.source in {"scenes-without-studios", "unrated-scenes"}:
        args.scenes = True
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        print(fail("Interrupted."))
        return 130
    except Exception as exc:
        print(fail(str(exc)))
        return 1
