from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from plexadm.cli import EXCLUDED_COMPOSITION_COLLECTIONS
from plexadm.config import load_config
from plexadm.console import info, ok, warn
from plexadm.plex import PlexContext, add_items, reload_if_partial, remove_items
from plexadm.stash import StashClient
from plexadm.stash_reconcile import _collection_to_tag

log = logging.getLogger(__name__)

COMPOSITION_COLLECTIONS = frozenset(EXCLUDED_COMPOSITION_COLLECTIONS) | {"01: Category: Lesbian"}

GROUP_SINGLE_FEMALE = {
    "Category: Solo",
    "Category: MF Only",
    "Category: MMF",
    "Category: Gangbang",
}
GROUP_MULTI_FEMALE_HEADCOUNT = {
    "Category: FFM",
    "Category: FFFM",
    "Category: Reverse Gangbang",
    "Category: FFF+",
}
GROUP_MULTI_FEMALE_ACTIVITY = {"Category: Lesbian"}
COMPOSITION_TAGS = GROUP_SINGLE_FEMALE | GROUP_MULTI_FEMALE_HEADCOUNT | GROUP_MULTI_FEMALE_ACTIVITY


@dataclass
class SceneDecision:
    rating_key: str
    title: str
    file_paths: list[str]
    adds: list[str] = field(default_factory=list)
    remove_candidates: list[str] = field(default_factory=list)
    ambiguous_reason: str | None = None


def _tag_to_collection(tag_name: str) -> str:
    return f"01: {tag_name}"


def classify_scene(stash_tags: set[str], plex_tags: set[str]) -> SceneDecision | None:
    s = stash_tags & COMPOSITION_TAGS
    p = plex_tags & COMPOSITION_TAGS
    if not s:
        return None

    single = s & GROUP_SINGLE_FEMALE
    headcount = s & GROUP_MULTI_FEMALE_HEADCOUNT
    lesbian = s & GROUP_MULTI_FEMALE_ACTIVITY

    conflicts = []
    if len(single) > 1:
        conflicts.append(f"multiple single-female tags: {sorted(single)}")
    if len(headcount) > 1:
        conflicts.append(f"multiple multi-female headcount tags: {sorted(headcount)}")
    if single and (headcount or lesbian):
        conflicts.append(f"cross-axis: {sorted(single)} + {sorted(headcount | lesbian)}")

    if conflicts:
        return SceneDecision(rating_key="", title="", file_paths=[], ambiguous_reason="; ".join(conflicts))

    adds = sorted(s - p)

    if single:
        contradicting = GROUP_MULTI_FEMALE_HEADCOUNT | GROUP_MULTI_FEMALE_ACTIVITY | (GROUP_SINGLE_FEMALE - single)
    else:
        contradicting = set(GROUP_SINGLE_FEMALE)
        if headcount:
            contradicting |= GROUP_MULTI_FEMALE_HEADCOUNT - headcount

    remove_candidates = sorted(p & contradicting)
    if not adds and not remove_candidates:
        return None

    return SceneDecision(rating_key="", title="", file_paths=[], adds=adds, remove_candidates=remove_candidates)


def _stash_composition_tags(scene: dict[str, Any]) -> set[str]:
    return {
        str(tag["name"]) for tag in scene.get("tags") or [] if tag.get("name") and str(tag["name"]) in COMPOSITION_TAGS
    }


def _plex_composition_tags(video: Any) -> set[str]:
    tags = {_collection_to_tag(str(collection)) for collection in getattr(video, "collections", None) or []}
    return {tag for tag in tags if tag in COMPOSITION_TAGS}


def _write_review(path: str | Path, entries: list[dict[str, Any]]) -> None:
    review_path = Path(path)
    review_path.parent.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = [{"generated_at": generated_at, **entry} for entry in entries]
    with review_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
        fh.write("\n")


def _load_review(path: str | Path) -> list[dict[str, Any]]:
    with Path(path).open(encoding="utf-8") as fh:
        payload = json.load(fh)
    if not isinstance(payload, list) or not all(isinstance(entry, dict) for entry in payload):
        raise ValueError("Review file must contain a JSON array of objects")
    return payload


def _decision_entries(
    decision: SceneDecision,
    stash_tags: set[str],
    plex_tags: set[str],
) -> list[dict[str, Any]]:
    common = {
        "rating_key": decision.rating_key,
        "title": decision.title,
        "file_paths": decision.file_paths,
        "stash_tags": sorted(stash_tags),
        "plex_tags": sorted(_tag_to_collection(tag) for tag in plex_tags),
        "status": "proposed",
    }
    if decision.ambiguous_reason:
        return [
            {
                **common,
                "action": "ambiguous",
                "ambiguous_reason": decision.ambiguous_reason,
            }
        ]

    return [
        {
            **common,
            "action": "remove_candidate",
            "collection_to_remove": _tag_to_collection(tag),
            "reason": f"Stash composition tags {sorted(stash_tags)} contradict Plex tag {tag!r}",
        }
        for tag in decision.remove_candidates
    ]


def backfill_tags(args: Any) -> int:
    log_level = getattr(args, "log_level", "WARNING").upper()
    logging.basicConfig(level=getattr(logging, log_level, logging.WARNING), format="%(levelname)s: %(message)s")

    cfg = load_config(args.config)
    endpoint = getattr(args, "stash_endpoint", None) or cfg.stash_endpoint
    if not endpoint:
        raise ValueError(
            "No Stash endpoint configured. Add stashEndpoint to your config file or pass --stash-endpoint."
        )

    print(info("Connecting to Stash and building scene index..."))
    stash_index = StashClient(endpoint).all_scenes()
    print(info(f"Stash: {len({scene['id'] for scene in stash_index.values()})} scenes across {len(stash_index)} paths"))

    plex_ctx = PlexContext(cfg)
    limit: int | None = getattr(args, "limit", None)
    path_filter: str | None = getattr(args, "path", None)
    additions: dict[str, list[Any]] = defaultdict(list)
    review_entries: list[dict[str, Any]] = []
    processed = 0
    matched_count = 0
    ambiguous_count = 0

    print(info("Scanning Plex library..."))
    for video in plex_ctx.all_videos():
        if limit is not None and processed >= limit:
            break

        reload_if_partial(video)
        locations = list(getattr(video, "locations", None) or [])
        if not locations:
            continue
        if path_filter and not any(location.startswith(path_filter) for location in locations):
            continue

        processed += 1
        matched: dict[str, dict[str, Any]] = {}
        for location in locations:
            scene = stash_index.get(location)
            if scene:
                matched[str(scene["id"])] = scene
        if not matched:
            log.debug("UNMATCHED Plex item: %s", video.title)
            continue

        matched_count += 1
        stash_tags = set().union(*(_stash_composition_tags(scene) for scene in matched.values()))
        plex_tags = _plex_composition_tags(video)
        decision = classify_scene(stash_tags, plex_tags)
        if decision is None:
            continue

        decision.rating_key = str(video.ratingKey)
        decision.title = str(video.title)
        decision.file_paths = locations

        if decision.ambiguous_reason:
            ambiguous_count += 1
        else:
            for tag in decision.adds:
                additions[tag].append(video)
        review_entries.extend(_decision_entries(decision, stash_tags, plex_tags))

    review_path = Path(getattr(args, "review_output", "reference/stash_backfill_review.json"))
    _write_review(review_path, review_entries)

    added_count = 0
    for tag, videos in sorted(additions.items()):
        collection = plex_ctx.collection(_tag_to_collection(tag))
        added_count += add_items(collection, videos, dry_run=args.dry_run)

    print(ok(f"Plex videos scanned: {processed}"))
    print(info(f"Matched to Stash: {matched_count}"))
    print(info(f"Composition memberships added: {added_count}"))
    print(info(f"Ambiguous matches staged: {ambiguous_count}"))
    print(info(f"Review entries written: {len(review_entries)} → {review_path}"))
    if args.dry_run:
        print(warn("Dry run - no Plex changes made."))
    return 0


def apply_review(args: Any) -> int:
    log_level = getattr(args, "log_level", "WARNING").upper()
    logging.basicConfig(level=getattr(logging, log_level, logging.WARNING), format="%(levelname)s: %(message)s")

    entries = _load_review(args.review_file)
    include_ambiguous = getattr(args, "include_ambiguous", False)
    selected = [
        entry
        for entry in entries
        if entry.get("action") == "remove_candidate" or (include_ambiguous and entry.get("action") == "ambiguous")
    ]

    missing_collection = [entry for entry in selected if not entry.get("collection_to_remove")]
    if missing_collection:
        print(warn(f"Skipping {len(missing_collection)} entries without collection_to_remove."))
    selected = [entry for entry in selected if entry.get("collection_to_remove")]

    invalid_collections = sorted(
        {
            str(entry["collection_to_remove"])
            for entry in selected
            if entry["collection_to_remove"] not in COMPOSITION_COLLECTIONS
        }
    )
    if invalid_collections:
        raise ValueError(f"Review file contains out-of-scope collections: {invalid_collections}")

    cfg = load_config(args.config)
    plex_ctx = PlexContext(cfg)
    videos_by_key = {str(video.ratingKey): video for video in plex_ctx.all_videos()}
    removals: dict[str, list[Any]] = defaultdict(list)
    missing_keys: list[str] = []
    seen: set[tuple[str, str]] = set()

    for entry in selected:
        rating_key = str(entry.get("rating_key", ""))
        collection_title = str(entry["collection_to_remove"])
        key = (collection_title, rating_key)
        if key in seen:
            continue
        seen.add(key)
        video = videos_by_key.get(rating_key)
        if video is None:
            missing_keys.append(rating_key)
            continue
        reload_if_partial(video)
        removals[collection_title].append(video)

    removed_count = 0
    for collection_title, videos in sorted(removals.items()):
        collection = plex_ctx.collection(collection_title)
        removed_count += remove_items(collection, videos, dry_run=args.dry_run)

    if missing_keys:
        print(warn(f"Skipped missing Plex rating keys: {sorted(set(missing_keys))}"))
    print(ok(f"Review entries selected: {len(selected)}"))
    print(info(f"Composition memberships removed: {removed_count}"))
    if args.dry_run:
        print(warn("Dry run - no Plex changes made."))
    return 0
