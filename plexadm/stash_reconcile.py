from __future__ import annotations

import base64
import csv
import json
import logging
import math
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests

from plexadm.config import PlexConfig, load_config, load_logging_config
from plexadm.console import info, ok, warn
from plexadm.logging_setup import configure_command_logging
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
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        error = f"HTTP {status_code}" if status_code is not None else type(exc).__name__
        log.warning("Failed to fetch Plex cover for '%s' (%s)", video.title, error)
        return None


@dataclass
class _Stats:
    updated: int = 0
    matched_no_data: list[dict[str, Any]] = field(default_factory=list)
    keys_added: int = 0
    keys_changed: int = 0
    keys_current: int = 0
    missing_key: int = 0
    ambiguous: int = 0
    custom_field_conflicts: int = 0


def _rating_key(video: Any) -> str | None:
    value = getattr(video, "ratingKey", None)
    if isinstance(value, bool):
        return None
    text = str(value) if value is not None else ""
    return str(int(text)) if re.fullmatch(r"[0-9]+", text) else None


def _custom_fields(scene: dict[str, Any]) -> dict[str, Any]:
    fields = scene.get("custom_fields") or {}
    if isinstance(fields, dict):
        return dict(fields)
    if isinstance(fields, list):
        result = {}
        for entry in fields:
            if isinstance(entry, dict):
                name = entry.get("field", entry.get("key"))
                if name is not None:
                    result[str(name)] = entry.get("value")
        return result
    return {}


def _key_is_current(stored: Any, key: str) -> bool:
    if isinstance(stored, bool):
        return False
    if isinstance(stored, int):
        return str(stored) == key
    if isinstance(stored, float):
        return math.isfinite(stored) and stored.is_integer() and str(int(stored)) == key
    if not isinstance(stored, str):
        return False
    return str(stored).isdecimal() and str(int(stored)) == key


def _file_paths(scene: dict[str, Any]) -> set[str]:
    return {str(file["path"]) for file in scene.get("files") or [] if file.get("path")}


def _json_equal(left: Any, right: Any) -> bool:
    return json.dumps(left, sort_keys=True, separators=(",", ":")) == json.dumps(
        right, sort_keys=True, separators=(",", ":")
    )


def _scene_key_update(scene: dict[str, Any], key: str) -> dict[str, Any]:
    stored = _custom_fields(scene).get("plex_rating_key")
    if _key_is_current(stored, key):
        return {}
    return {"custom_fields": {"partial": {"plex_rating_key": key}}}


def _record_key_write(scene: dict[str, Any], key: str, stats: _Stats) -> None:
    stored = _custom_fields(scene).get("plex_rating_key")
    if _key_is_current(stored, key):
        stats.keys_current += 1
    elif stored is None or stored == "":
        stats.keys_added += 1
    else:
        stats.keys_changed += 1


def reconcile(args: Any) -> int:
    log_level = getattr(args, "log_level", "WARNING").upper()
    configure_command_logging(log_level, load_logging_config(args.config))

    cfg = load_config(args.config)
    endpoint = getattr(args, "stash_endpoint", None) or cfg.stash_endpoint
    if not endpoint:
        raise ValueError(
            "No Stash endpoint configured. Add stashEndpoint to your config file or pass --stash-endpoint."
        )

    limit: int | None = getattr(args, "limit", None)
    path_filter: str | None = getattr(args, "path", None)
    if path_filter == "":
        raise ValueError("--path must not be empty when supplied.")

    added_in_last_days: int | None = getattr(args, "added_in_last_days", None)
    partial_scan = limit is not None or path_filter is not None or added_in_last_days is not None
    stash = StashClient(endpoint)

    # Validate the supported field and merge inputs before any operation that can mutate Stash.
    stash.check_reconcile_capabilities()
    print(
        warn(
            "Keep the Plex library unchanged until stash reconcile completes; do not add, remove, move, merge, or edit Plex items during this run."
        )
    )

    if not getattr(args, "skip_scan", False):
        print(info("Scanning Stash library (with phash generation) before reconciling..."))
        stash.scan()
        print(ok("Stash scan complete."))

    if partial_scan:
        print(info("Skipping Stash Clean for a partial Plex scan; Clean affects the entire Stash library."))
    else:
        print(info("Cleaning Stash records for files no longer present..."))
        stash.clean()
        print(ok("Stash clean complete."))

    print(info("Connecting to Stash and building scene index..."))
    stash_scenes = stash.reconcile_scenes()
    stash_scenes_by_id = {str(scene["id"]): scene for scene in stash_scenes}
    stash_path_index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for scene in stash_scenes:
        for path in _file_paths(scene):
            stash_path_index[path].append(scene)
    print(info(f"Stash: {len(stash_scenes_by_id)} scenes across {len(stash_path_index)} paths"))

    plex_ctx = PlexContext(cfg)
    stats = _Stats()
    matched_stash_ids: set[str] = set()
    processed = 0

    print(info("Building a complete Plex path index (also required for partial scopes)..."))
    all_videos = plex_ctx.all_videos()
    section_count = getattr(plex_ctx.section, "totalSize", None)
    if section_count is not None and int(section_count) != len(all_videos):
        raise RuntimeError(f"Plex library listing is incomplete: got {len(all_videos)} of {section_count} items")
    if section_count is None:
        raise RuntimeError("Plex library section did not provide totalSize; cannot verify the complete path index")

    item_by_key: dict[str, Any] = {}
    paths_by_key: dict[str, list[str]] = {}
    keyless: list[tuple[Any, list[str]]] = []
    plex_path_owners: dict[str, set[str]] = defaultdict(set)
    for item in all_videos:
        key = _rating_key(item)
        locations = list(getattr(item, "locations", None) or [])
        if key is None:
            keyless.append((item, locations))
            continue
        if not locations:
            raise RuntimeError(
                f"Plex listing omitted file locations for ratingKey {key}; refusing an incomplete path index"
            )
        if key in item_by_key:
            raise RuntimeError(f"Plex returned duplicate ratingKey {key}; refusing to reconcile an unstable inventory")
        item_by_key[key] = item
        paths_by_key[key] = locations
        for path in locations:
            plex_path_owners[path].add(key)
    for item_index, (_, locations) in enumerate(keyless):
        for path in locations:
            plex_path_owners[path].add(f"missing-ratingKey:{item_index}")
    path_scenes = stash_path_index
    scene_owners: dict[str, set[str]] = defaultdict(set)
    key_to_scene_ids: dict[str, set[str]] = defaultdict(set)
    for key, locations in paths_by_key.items():
        for path in locations:
            for scene in path_scenes.get(path, []):
                scene_id = str(scene["id"])
                scene_owners[scene_id].add(key)
                key_to_scene_ids[key].add(scene_id)
    for item_index, (_, locations) in enumerate(keyless):
        for path in locations:
            for scene in path_scenes.get(path, []):
                scene_owners[str(scene["id"])].add(f"missing-ratingKey:{item_index}")

    if partial_scan:
        print(
            info(
                f"Full Plex path index loaded for {len(all_videos)} items; this adds one library-wide read to partial runs."
            )
        )
    if added_in_last_days is not None:
        print(info(f"Selecting Plex items added in the last {added_in_last_days} day(s)..."))
        selected = plex_ctx.search(filters={"addedAt>>": f"{added_in_last_days}d"})
        selected_keys: list[str] = []
        for item in selected:
            selected_key = _rating_key(item)
            if selected_key is not None and selected_key not in selected_keys:
                selected_keys.append(selected_key)
        missing_from_inventory = [key for key in selected_keys if key not in item_by_key]
        if missing_from_inventory:
            raise RuntimeError(
                "Plex recent-item query returned ratingKeys absent from the complete library index: "
                + ", ".join(missing_from_inventory)
            )
        videos = [item_by_key[key] for key in selected_keys if key in item_by_key]
        videos.extend(item for item in selected if _rating_key(item) is None)
    else:
        videos = all_videos
    total = len(videos)
    last_progress_at = time.monotonic()
    progress_interval = float(getattr(args, "progress_interval", 60) or 60)

    for loop_index, video in enumerate(videos, start=1):
        if limit is not None and processed >= limit:
            break
        now = time.monotonic()
        if now - last_progress_at >= progress_interval:
            percent = (loop_index / total * 100) if total else 0.0
            print(info(f"{loop_index}/{total} - {percent:.1f}%"))
            last_progress_at = now

        locations = list(getattr(video, "locations", None) or [])
        if not locations:
            if _rating_key(video) is None:
                stats.missing_key += 1
                log.warning("Skipping Plex item with no usable ratingKey and no file locations")
            continue
        if path_filter and not any(loc.startswith(path_filter) for loc in locations):
            continue
        processed += 1
        key = _rating_key(video)
        if key is None:
            stats.missing_key += 1
            blockers = sorted({str(scene["id"]) for path in locations for scene in path_scenes.get(path, [])}, key=int)
            matched_stash_ids.update(blockers)
            log.warning("Skipping Plex item with no usable ratingKey; matching Stash scene IDs=%s", blockers)
            continue
        matched = {scene_id: stash_scenes_by_id[scene_id] for scene_id in key_to_scene_ids.get(key, set())}
        if not matched:
            log.debug("UNMATCHED Plex ratingKey=%s: %s", key, getattr(video, "title", ""))
            continue
        for scene_id in matched:
            matched_stash_ids.add(scene_id)

        ambiguous_scenes = [scene_id for scene_id in matched if len(scene_owners[scene_id]) > 1]
        if ambiguous_scenes:
            stats.ambiguous += 1
            log.warning(
                "Skipping ambiguous Plex ratingKey=%s; Stash scene IDs=%s", key, sorted(ambiguous_scenes, key=int)
            )
            continue

        # Only selected videos need descriptive fields. Full inventory entries already expose ratingKey and locations.
        reload_if_partial(video)
        key_updates = {scene_id: _scene_key_update(scene, key) for scene_id, scene in matched.items()}
        has_metadata = _has_usable_metadata(video)
        if not has_metadata:
            log.debug("MATCHED-NO-DATA ratingKey=%s scenes=%s", key, sorted(matched, key=int))
            for scene_id, scene in matched.items():
                stats.matched_no_data.append({"id": scene_id, "paths": sorted(_file_paths(scene))})
                if key_updates[scene_id]:
                    stash.update_scene(scene_id, key_updates[scene_id])
                _record_key_write(scene, key, stats)
            continue

        fresh_scenes: dict[str, dict[str, Any]] = {}
        if len(matched) > 1:
            scene_ids = sorted(matched, key=int)
            stale = False
            for scene_id in scene_ids:
                fresh = stash.reconcile_scene_by_id(scene_id)
                if fresh is None or _file_paths(fresh) != _file_paths(matched[scene_id]):
                    stale = True
                    break
                fresh_scenes[scene_id] = fresh
            for fresh in fresh_scenes.values():
                if any(owner != key for path in _file_paths(fresh) for owner in plex_path_owners.get(path, set())):
                    stale = True
                    break
            if stale:
                stats.ambiguous += 1
                log.warning("Skipping stale merge plan for Plex ratingKey=%s; Stash scene IDs=%s", key, scene_ids)
                continue

            field_values: dict[str, Any] = {}
            conflicting_fields: set[str] = set()
            for fresh in fresh_scenes.values():
                for field_name, value in _custom_fields(fresh).items():
                    if field_name == "plex_rating_key":
                        continue
                    if field_name in field_values and not _json_equal(field_values[field_name], value):
                        conflicting_fields.add(field_name)
                    else:
                        field_values[field_name] = value
            if conflicting_fields:
                stats.custom_field_conflicts += 1
                log.warning(
                    "Custom field conflict for Plex ratingKey=%s scenes=%s fields=%s",
                    key,
                    scene_ids,
                    sorted(conflicting_fields),
                )
                for scene_id, fresh in fresh_scenes.items():
                    fields = _scene_key_update(fresh, key)
                    if fields:
                        stash.update_scene(scene_id, fields)
                    _record_key_write(fresh, key, stats)
                continue

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
            existing_performer_ids = {p["id"] for scene in matched.values() for p in (scene.get("performers") or [])}
            update["performer_ids"] = list(existing_performer_ids | set(new_performer_ids))
        if new_tag_ids:
            existing_tag_ids = {t["id"] for scene in matched.values() for t in (scene.get("tags") or [])}
            update["tag_ids"] = list(existing_tag_ids | set(new_tag_ids))

        if len(matched) > 1:
            scene_ids = sorted(matched, key=int)
            destination_id, source_ids = scene_ids[0], scene_ids[1:]
            # Re-read participants immediately before the destructive merge as a final stale-plan check.
            latest_scenes: dict[str, dict[str, Any]] = {}
            stale = False
            for scene_id in scene_ids:
                latest = stash.reconcile_scene_by_id(scene_id)
                if latest is None or _file_paths(latest) != _file_paths(matched[scene_id]):
                    stale = True
                    break
                latest_scenes[scene_id] = latest
            for latest in latest_scenes.values():
                if any(owner != key for path in _file_paths(latest) for owner in plex_path_owners.get(path, set())):
                    stale = True
                    break
            if stale:
                stats.ambiguous += 1
                log.warning("Skipping stale merge plan for Plex ratingKey=%s; Stash scene IDs=%s", key, scene_ids)
                continue
            latest_field_values: dict[str, Any] = {}
            conflicts: set[str] = set()
            for latest in latest_scenes.values():
                for field_name, value in _custom_fields(latest).items():
                    if field_name == "plex_rating_key":
                        continue
                    if field_name in latest_field_values and not _json_equal(latest_field_values[field_name], value):
                        conflicts.add(field_name)
                    else:
                        latest_field_values[field_name] = value
            if conflicts:
                stats.custom_field_conflicts += 1
                log.warning(
                    "Custom field conflict before merge for Plex ratingKey=%s scenes=%s fields=%s",
                    key,
                    scene_ids,
                    sorted(conflicts),
                )
                for scene_id, latest in latest_scenes.items():
                    fields = _scene_key_update(latest, key)
                    if fields:
                        stash.update_scene(scene_id, fields)
                    _record_key_write(latest, key, stats)
                continue
            fresh_scenes = latest_scenes
            existing_performer_ids = {
                performer["id"] for scene in fresh_scenes.values() for performer in (scene.get("performers") or [])
            }
            existing_tag_ids = {tag["id"] for scene in fresh_scenes.values() for tag in (scene.get("tags") or [])}
            if existing_performer_ids or new_performer_ids:
                update["performer_ids"] = list(existing_performer_ids | set(new_performer_ids))
            if existing_tag_ids or new_tag_ids:
                update["tag_ids"] = list(existing_tag_ids | set(new_tag_ids))

            partial_fields = dict(latest_field_values)
            partial_fields["plex_rating_key"] = key
            update["custom_fields"] = {"partial": partial_fields}
            log.info("MERGE Plex ratingKey=%s sources=%s destination=%s", key, source_ids, destination_id)
            try:
                stash.merge_scenes(source_ids, destination_id, update)
            except Exception:
                log.exception(
                    "Scene merge failed for Plex ratingKey=%s sources=%s destination=%s; stopping without retry",
                    key,
                    source_ids,
                    destination_id,
                )
                raise
            _record_key_write(fresh_scenes[destination_id], key, stats)
            if play_timestamps:
                stash.sync_play_history(destination_id, play_timestamps)
            print(warn(f"  Merged {len(source_ids) + 1} scenes → {destination_id}: {video.title}"))
        else:
            scene_id = next(iter(matched))
            update.update(key_updates[scene_id])
            if update:
                log.info("UPDATE Plex ratingKey=%s scene=%s fields=%s", key, scene_id, sorted(update.keys()))
                stash.update_scene(scene_id, update)
            _record_key_write(matched[scene_id], key, stats)
            if play_timestamps:
                stash.sync_play_history(scene_id, play_timestamps)
            print(warn(f"  Updated scene {scene_id}: {video.title}"))

        stats.updated += 1

    # Stash scenes with no matching Plex item — only meaningful for a full-library scan
    unmatched_stash: list[dict[str, Any]] = []
    if not partial_scan:
        for scene_id, scene in stash_scenes_by_id.items():
            if scene_id not in matched_stash_ids:
                unmatched_stash.append(scene)

    print(ok(f"Scenes updated: {stats.updated}"))
    print(info(f"Matched but no usable Plex metadata: {len(stats.matched_no_data)}"))
    print(
        info(
            f"Plex rating keys: {stats.keys_added} added, {stats.keys_changed} changed, {stats.keys_current} already current"
        )
    )
    print(
        info(
            f"Skipped: {stats.missing_key} missing ratingKey, {stats.ambiguous} ambiguous item(s), {stats.custom_field_conflicts} custom-field conflict(s)"
        )
    )
    if partial_scan:
        print(
            info(
                "(Stash scenes with no Plex match: skipped — run without --limit, --path, or "
                "--added-in-last-days for complete scope)"
            )
        )
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
