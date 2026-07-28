from __future__ import annotations

import logging
import re
from typing import Any

from plexadm.config import load_config, load_logging_config
from plexadm.console import info, ok
from plexadm.logging_setup import configure_command_logging
from plexadm.plex import PlexContext, reload_if_partial
from plexadm.stash import StashClient

log = logging.getLogger(__name__)

_SKIP_COLLECTIONS = {"00A: BROKEN", "00D: Review: CORRUPT?"}
_SKIP_PREFIXES = ("01: Category:", "01: Hair:", "02: Studio:", "03: Star:", "99:")
_PREFIX_RE = re.compile(r"^\d{2}[A-Z]?: ")


def _tag_name(title: str) -> str:
    return _PREFIX_RE.sub("", title, count=1)


def sync_tags(args: Any) -> int:
    log_level = getattr(args, "log_level", "WARNING").upper()
    configure_command_logging(log_level, load_logging_config(args.config))

    cfg = load_config(args.config)
    endpoint = getattr(args, "stash_endpoint", None) or cfg.stash_endpoint
    if not endpoint:
        raise ValueError("No Stash endpoint configured. Add stashEndpoint to config or pass --stash-endpoint.")

    print(info("Connecting to Stash and building scene index..."))
    stash = StashClient(endpoint)
    stash_index = stash.all_scenes()
    unique_scenes = len({s["id"] for s in stash_index.values()})
    print(info(f"Stash: {unique_scenes} scenes across {len(stash_index)} paths"))

    plex_ctx = PlexContext(cfg)
    total_tagged = 0

    for collection in plex_ctx.section.collections():
        reload_if_partial(collection)
        title = str(collection.title)

        if collection.smart:
            continue
        if title in _SKIP_COLLECTIONS:
            log.debug("Skipping excluded collection: %s", title)
            continue
        if any(title.startswith(p) for p in _SKIP_PREFIXES):
            log.debug("Skipping prefix-excluded collection: %s", title)
            continue

        tag_name = _tag_name(title)
        tag_id = stash.find_or_create_tag(tag_name)
        count = 0

        for item in collection.items():
            reload_if_partial(item)
            locations = list(getattr(item, "locations", None) or [])
            updated_ids: set[str] = set()
            for path in locations:
                scene = stash_index.get(path)
                if not scene:
                    log.debug("No Stash scene for path: %s", path)
                    continue
                scene_id = scene["id"]
                if scene_id in updated_ids:
                    continue
                existing_tag_ids = {t["id"] for t in (scene.get("tags") or [])}
                if tag_id in existing_tag_ids:
                    updated_ids.add(scene_id)
                    continue
                stash.update_scene(scene_id, {"tag_ids": list(existing_tag_ids | {tag_id})})
                scene.setdefault("tags", []).append({"id": tag_id, "name": tag_name})
                updated_ids.add(scene_id)
                count += 1

        total_tagged += count
        print(info(f"  '{tag_name}': {count} scenes tagged"))

    print(ok(f"Total scenes tagged: {total_tagged}"))
    return 0
