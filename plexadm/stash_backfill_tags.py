from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from plexadm.cli import EXCLUDED_COMPOSITION_COLLECTIONS, EXCLUDED_HAIR_COLLECTIONS
from plexadm.config import load_config
from plexadm.console import info, ok, warn
from plexadm.plex import PlexContext, add_items, reload_if_partial, remove_items
from plexadm.stash import StashClient
from plexadm.stash_reconcile import _collection_to_tag

log = logging.getLogger(__name__)

COMPOSITION_COLLECTIONS = frozenset(EXCLUDED_COMPOSITION_COLLECTIONS) | {"01: Category: Lesbian"}
HAIR_COLLECTIONS = frozenset(EXCLUDED_HAIR_COLLECTIONS)
HAIR_TAGS = frozenset(tag for collection in HAIR_COLLECTIONS if (tag := _collection_to_tag(collection)) is not None)

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
COMPOSITION_TAGS = frozenset(GROUP_SINGLE_FEMALE | GROUP_MULTI_FEMALE_HEADCOUNT | GROUP_MULTI_FEMALE_ACTIVITY)


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


def _stash_tags_in_scope(scene: dict[str, Any], scope: frozenset[str]) -> set[str]:
    return {str(tag["name"]) for tag in scene.get("tags") or [] if tag.get("name") and str(tag["name"]) in scope}


def _plex_tags_in_scope(video: Any, scope: frozenset[str]) -> set[str]:
    tags = {_collection_to_tag(str(collection)) for collection in getattr(video, "collections", None) or []}
    return {tag for tag in tags if tag in scope}


def _write_review(path: str | Path, entries: list[dict[str, Any]]) -> None:
    review_path = Path(path)
    review_path.parent.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = [{"generated_at": generated_at, **entry} for entry in entries]
    with review_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
        fh.write("\n")


def _escape_markdown_table_cell(value: object) -> str:
    return str(value).replace("|", "\\|")


def _tag_source(tag: dict[str, Any], stash_box_names: dict[str, str]) -> str:
    """Return where a tag came from: 'local' (no external link) or the stash-box name(s) it's linked to.

    A tag with no stash_ids is purely local to this Stash instance - that includes tags
    synced in from Plex via `plexadm stash sync-tags`, since Stash has no way to record
    that provenance beyond "not linked to an external stash-box". Falls back to the raw
    endpoint URL if a stash_id references a box that isn't in the currently configured list
    (e.g. a box that was since removed from Settings).
    """
    stash_ids = tag.get("stash_ids") or []
    if not stash_ids:
        return "local"
    sources = {
        stash_box_names.get(sid.get("endpoint", ""), sid.get("endpoint") or "unknown stash-box") for sid in stash_ids
    }
    return ", ".join(sorted(sources))


def _write_unmapped_tags_report(
    path: str | Path,
    unmapped: list[dict[str, Any]],
    web_base: str,
    stash_box_names: dict[str, str],
    *,
    total_tag_count: int,
) -> None:
    report_path = Path(path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        "# Stash Tags With No Matching Plex Collection",
        "",
        f"Generated: {generated_at}",
        "",
        f"Found {len(unmapped)} unmapped tags out of {total_tag_count} total Stash tags.",
        "",
        "| Scenes | Tag | Source | Link |",
        "|---:|---|---|---|",
    ]
    lines.extend(
        f"| {tag.get('scene_count') or 0} | {_escape_markdown_table_cell(tag['name'])} | "
        f"{_escape_markdown_table_cell(_tag_source(tag, stash_box_names))} | "
        f"[view]({web_base}/tags/{tag['id']}) |"
        for tag in unmapped
    )
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_backfill_report(
    path: str | Path,
    *,
    dry_run: bool,
    processed: int,
    matched_count: int,
    composition_additions: dict[str, list[Any]],
    hair_additions: dict[str, list[Any]],
    composition_added_count: int,
    hair_added_count: int,
    ambiguous_entries: list[tuple[str, str]],
    review_path: str | Path,
    review_entry_count: int,
) -> None:
    report_path = Path(path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    mode = "DRY RUN (no Plex changes made)" if dry_run else "APPLIED"
    lines = [
        "# Stash -> Plex Backfill Report",
        "",
        f"Generated: {generated_at}",
        f"Mode: {mode}",
        "",
        "## Summary",
        "",
        f"- Plex videos scanned: {processed}",
        f"- Matched to Stash: {matched_count}",
        f"- Composition memberships added: {composition_added_count}",
        f"- Hair memberships added: {hair_added_count}",
        f"- Ambiguous matches staged for review: {len(ambiguous_entries)}",
        f"- Review entries written: {review_entry_count} -> {review_path}",
    ]

    if composition_additions:
        lines.extend(
            [
                "",
                "## Composition additions by collection",
                "",
                "| Collection | Videos added |",
                "|---|---:|",
            ]
        )
        lines.extend(
            f"| {_escape_markdown_table_cell(_tag_to_collection(tag))} | {len(videos)} |"
            for tag, videos in sorted(composition_additions.items())
        )

    if hair_additions:
        lines.extend(
            [
                "",
                "## Hair additions by collection",
                "",
                "| Collection | Videos added |",
                "|---|---:|",
            ]
        )
        lines.extend(
            f"| {_escape_markdown_table_cell(_tag_to_collection(tag))} | {len(videos)} |"
            for tag, videos in sorted(hair_additions.items())
        )

    lines.extend(["", "## Ambiguous scenes (staged for review, not applied)", ""])
    if ambiguous_entries:
        lines.extend(["| Title | Reason |", "|---|---|"])
        lines.extend(
            f"| {_escape_markdown_table_cell(title)} | {_escape_markdown_table_cell(reason)} |"
            for title, reason in ambiguous_entries
        )
    else:
        lines.append("_No ambiguous scenes this run._")

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


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
    hair_additions: dict[str, list[Any]] = defaultdict(list)
    review_entries: list[dict[str, Any]] = []
    ambiguous_entries: list[tuple[str, str]] = []
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
        stash_hair_tags = set().union(*(_stash_tags_in_scope(scene, HAIR_TAGS) for scene in matched.values()))
        plex_hair_tags = _plex_tags_in_scope(video, HAIR_TAGS)
        for tag in sorted(stash_hair_tags - plex_hair_tags):
            hair_additions[tag].append(video)

        stash_tags = set().union(*(_stash_tags_in_scope(scene, COMPOSITION_TAGS) for scene in matched.values()))
        plex_tags = _plex_tags_in_scope(video, COMPOSITION_TAGS)
        decision = classify_scene(stash_tags, plex_tags)
        if decision is None:
            continue

        decision.rating_key = str(video.ratingKey)
        decision.title = str(video.title)
        decision.file_paths = locations

        if decision.ambiguous_reason:
            ambiguous_count += 1
            ambiguous_entries.append((decision.title, decision.ambiguous_reason))
        else:
            for tag in decision.adds:
                additions[tag].append(video)
        review_entries.extend(_decision_entries(decision, stash_tags, plex_tags))

    review_path = Path(getattr(args, "review_output", "reference/stash_backfill_review.json"))
    _write_review(review_path, review_entries)

    composition_added_count = 0
    for tag, videos in sorted(additions.items()):
        collection = plex_ctx.collection(_tag_to_collection(tag))
        composition_added_count += add_items(collection, videos, dry_run=args.dry_run)

    hair_added_count = 0
    for tag, videos in sorted(hair_additions.items()):
        collection = plex_ctx.collection(_tag_to_collection(tag))
        hair_added_count += add_items(collection, videos, dry_run=args.dry_run)

    report_path = Path(getattr(args, "report_output", "reference/stash_backfill_report.md"))
    _write_backfill_report(
        report_path,
        dry_run=args.dry_run,
        processed=processed,
        matched_count=matched_count,
        composition_additions=additions,
        hair_additions=hair_additions,
        composition_added_count=composition_added_count,
        hair_added_count=hair_added_count,
        ambiguous_entries=ambiguous_entries,
        review_path=review_path,
        review_entry_count=len(review_entries),
    )

    print(ok(f"Plex videos scanned: {processed}"))
    print(info(f"Matched to Stash: {matched_count}"))
    print(info(f"Composition memberships added: {composition_added_count}"))
    print(info(f"Hair memberships added: {hair_added_count}"))
    print(info(f"Ambiguous matches staged: {ambiguous_count}"))
    print(info(f"Review entries written: {len(review_entries)} → {review_path}"))
    print(info(f"Report written to {report_path}"))
    if args.dry_run:
        print(warn("Dry run - no Plex changes made."))
    return 0


def unmapped_tags(args: Any) -> int:
    log_level = getattr(args, "log_level", "WARNING").upper()
    logging.basicConfig(level=getattr(logging, log_level, logging.WARNING), format="%(levelname)s: %(message)s")

    cfg = load_config(args.config)
    endpoint = getattr(args, "stash_endpoint", None) or cfg.stash_endpoint
    if not endpoint:
        raise ValueError(
            "No Stash endpoint configured. Add stashEndpoint to your config file or pass --stash-endpoint."
        )
    web_base = endpoint.rstrip("/")
    if web_base.endswith("/graphql"):
        web_base = web_base[: -len("/graphql")]

    print(info("Fetching Stash tags..."))
    stash = StashClient(endpoint)
    tags = stash.all_tags()
    stash_box_names = {box["endpoint"]: str(box["name"]) for box in stash.configured_stash_boxes()}

    print(info("Fetching Plex collections..."))
    plex_ctx = PlexContext(cfg)
    existing_titles = {str(collection.title) for collection in plex_ctx.section.collections()}

    unmapped = [tag for tag in tags if _tag_to_collection(str(tag["name"])) not in existing_titles]
    unmapped.sort(key=lambda tag: tag.get("scene_count") or 0, reverse=True)

    report_path = Path(getattr(args, "output", "reference/stash_unmapped_tags.md"))
    _write_unmapped_tags_report(report_path, unmapped, web_base, stash_box_names, total_tag_count=len(tags))

    print(ok(f"Unmapped tags: {len(unmapped)} of {len(tags)} total"))
    print(info(f"Report written to {report_path}"))
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
