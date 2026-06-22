from __future__ import annotations

import base64
import csv
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests

from plexadm.config import PlexConfig, load_config
from plexadm.console import info, ok, warn
from plexadm.plex import PlexContext, reload_if_partial
from plexadm.stash import StashClient

log = logging.getLogger(__name__)

_TAG_PREFIX = "01: "


def _collection_to_tag(title: str) -> str | None:
    """Return the tag name for a '01: ...' Plex collection title, or None to skip."""
    if title.startswith(_TAG_PREFIX):
        return title[len(_TAG_PREFIX) :]
    return None


def _has_usable_metadata(video: Any) -> bool:
    if getattr(video, "studio", None):
        return True
    if getattr(video, "writers", None):
        return True
    if getattr(video, "userRating", None):
        return True
    if getattr(video, "directors", None):
        return True
    collections = getattr(video, "collections", None) or []
    return any(_collection_to_tag(str(c)) for c in collections)


def _fetch_plex_cover(video: Any, cfg: PlexConfig) -> str | None:
    thumb = getattr(video, "thumb", None)
    if not thumb:
        return None
    url = f"{cfg.base_url}{thumb}?X-Plex-Token={cfg.token}"
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "image/jpeg")
        data = base64.b64encode(resp.content).decode("ascii")
        return f"data:{content_type};base64,{data}"
    except Exception as exc:
        log.warning("Failed to fetch Plex cover for '%s': %s", video.title, exc)
        return None


@dataclass
class _Stats:
    updated: int = 0
    matched_no_data: list[dict[str, Any]] = field(default_factory=list)


def reconcile(args: Any) -> int:
    log_level = getattr(args, "log_level", "WARNING").upper()
    logging.basicConfig(level=getattr(logging, log_level, logging.WARNING), format="%(levelname)s: %(message)s")

    cfg = load_config(args.config)
    endpoint = getattr(args, "stash_endpoint", None) or cfg.stash_endpoint
    if not endpoint:
        raise ValueError(
            "No Stash endpoint configured. Add stashEndpoint to your config file or pass --stash-endpoint."
        )

    print(info("Connecting to Stash and building scene index..."))
    stash = StashClient(endpoint)
    stash_index = stash.all_scenes()  # path -> scene dict
    stash_scenes_by_id: dict[str, dict[str, Any]] = {s["id"]: s for s in stash_index.values()}
    print(info(f"Stash: {len(stash_scenes_by_id)} scenes across {len(stash_index)} paths"))

    plex_ctx = PlexContext(cfg)
    limit: int | None = getattr(args, "limit", None)
    path_filter: str | None = getattr(args, "path", None)
    stats = _Stats()
    matched_stash_ids: set[str] = set()
    processed = 0

    print(info("Scanning Plex library..."))
    for video in plex_ctx.all_videos():
        if limit is not None and processed >= limit:
            break

        reload_if_partial(video)
        locations = list(getattr(video, "locations", None) or [])
        if not locations:
            continue

        if path_filter and not any(loc.startswith(path_filter) for loc in locations):
            continue

        matched: dict[str, dict[str, Any]] = {}
        for path in locations:
            scene = stash_index.get(path)
            if scene:
                matched[scene["id"]] = scene

        processed += 1

        if not matched:
            log.debug("UNMATCHED Plex item: %s", video.title)
            continue

        for scene_id in matched:
            matched_stash_ids.add(scene_id)

        if not _has_usable_metadata(video):
            log.debug("MATCHED-NO-DATA: %s", video.title)
            for scene_id, scene in matched.items():
                stats.matched_no_data.append({"id": scene_id, "paths": [f["path"] for f in (scene.get("files") or [])]})
            continue

        # Resolve entity IDs once — shared across all matched scenes for this Plex item
        studio = getattr(video, "studio", None)
        studio_id = stash.find_or_create_studio(studio) if studio else None

        writers = [str(w) for w in (getattr(video, "writers", None) or [])]
        new_performer_ids = [stash.find_or_create_performer(w) for w in writers]

        directors = [str(d) for d in (getattr(video, "directors", None) or [])]

        raw_collections = getattr(video, "collections", None) or []
        tag_names = [t for c in raw_collections if (t := _collection_to_tag(str(c)))]
        new_tag_ids = [stash.find_or_create_tag(t) for t in tag_names]

        user_rating = getattr(video, "userRating", None)
        view_count = getattr(video, "viewCount", None) or 0
        cover_image = _fetch_plex_cover(video, cfg)
        play_timestamps: list[str] = []
        if view_count:
            play_timestamps = [
                h.viewedAt.strftime("%Y-%m-%dT%H:%M:%SZ") for h in video.history() if getattr(h, "viewedAt", None)
            ]

        # Build update merging existing performer/tag IDs across all matched scenes
        update: dict[str, Any] = {"title": video.title}

        if studio_id:
            update["studio_id"] = studio_id

        if directors:
            update["director"] = ", ".join(directors)

        if user_rating:
            update["rating100"] = round(float(user_rating) * 10)

        if cover_image:
            update["cover_image"] = cover_image

        if new_performer_ids:
            existing_performer_ids = {p["id"] for s in matched.values() for p in (s.get("performers") or [])}
            update["performer_ids"] = list(existing_performer_ids | set(new_performer_ids))

        if new_tag_ids:
            existing_tag_ids = {t["id"] for s in matched.values() for t in (s.get("tags") or [])}
            update["tag_ids"] = list(existing_tag_ids | set(new_tag_ids))

        if len(matched) > 1:
            scene_ids = sorted(matched.keys(), key=lambda x: int(x))
            destination_id, source_ids = scene_ids[0], scene_ids[1:]
            log.info("MERGE %s → scene %s ('%s')", source_ids, destination_id, video.title)
            stash.merge_scenes(source_ids, destination_id, update)
            if play_timestamps:
                stash.sync_play_history(destination_id, play_timestamps)
            print(warn(f"  Merged {len(source_ids) + 1} scenes → {destination_id}: {video.title}"))
        else:
            scene_id = next(iter(matched))
            log.info("UPDATE scene %s ('%s'): %s", scene_id, video.title, sorted(update.keys()))
            stash.update_scene(scene_id, update)
            if play_timestamps:
                stash.sync_play_history(scene_id, play_timestamps)
            print(warn(f"  Updated scene {scene_id}: {video.title}"))

        stats.updated += 1

    # Stash scenes with no matching Plex item — only meaningful without --limit
    unmatched_stash: list[dict[str, Any]] = []
    if limit is None:
        for scene_id, scene in stash_scenes_by_id.items():
            if scene_id not in matched_stash_ids:
                unmatched_stash.append(scene)

    print(ok(f"Scenes updated: {stats.updated}"))
    print(info(f"Matched but no usable Plex metadata: {len(stats.matched_no_data)}"))
    if limit is not None:
        print(info("(Stash scenes with no Plex match: skipped — run without --limit for complete scope)"))
    else:
        print(info(f"Stash scenes with no Plex match: {len(unmatched_stash)}"))

    csv_path = Path(getattr(args, "csv_output", "stash_scope.csv"))
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["bucket", "stash_scene_id", "path"])
        for entry in stats.matched_no_data:
            for p in entry["paths"]:
                writer.writerow(["matched_no_data", entry["id"], p])
        for scene in unmatched_stash:
            for f in scene.get("files") or []:
                writer.writerow(["unmatched", scene["id"], f["path"]])

    print(info(f"Scope exported to {csv_path}"))
    return 0
