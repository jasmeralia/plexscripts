from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from plexadm.config import InventoryConfig
from plexadm.plex import PlexContext, collection_titles


def _client(config: InventoryConfig) -> Any:
    from opensearchpy import OpenSearch

    return OpenSearch(
        hosts=[config.url],
        http_auth=(config.username, config.password) if config.username else None,
        verify_certs=config.verify_tls,
    )


def take_snapshot(ctx: PlexContext, config: InventoryConfig, *, dry_run: bool = False) -> int:
    """Record one document per video, capturing its full current collection membership.

    Distinct purpose from plexadm.audit: audit records "what did plexadm do"; this records "what
    does the state actually look like right now, regardless of what changed it" - the ground
    truth needed to notice and pinpoint drift from any source, not just plexadm's own mutations.
    """
    run_id = datetime.now(UTC).isoformat(timespec="seconds")
    videos = ctx.all_videos(reload=True)
    actions = [
        {
            "_index": config.index,
            "_source": {
                "run_id": run_id,
                "timestamp": run_id,
                "rating_key": video.ratingKey,
                "title": str(video.title),
                "studio": getattr(video, "studio", None),
                "writers": sorted(str(w) for w in getattr(video, "writers", None) or []),
                "collections": sorted(collection_titles(video)),
            },
        }
        for video in videos
    ]
    if dry_run:
        return len(actions)

    from opensearchpy.helpers import bulk

    success, _ = bulk(_client(config), actions)
    return int(success)


def _fetch_run_ids(config: InventoryConfig, *, size: int = 2) -> list[str]:
    # run_id is an ISO8601 string, but OpenSearch's dynamic mapping date-detects it as a `date`
    # field rather than `text`/`keyword` - so there's no `.keyword` sub-field to aggregate on.
    # Querying the field directly still works for exact match/terms aggs (date fields support
    # both), and keeping it date-typed rather than forcing keyword is deliberate: diff_snapshots
    # reuses run_id values as a time range when cross-checking the audit trail.
    response = _client(config).search(
        index=config.index,
        body={
            "size": 0,
            "aggs": {"runs": {"terms": {"field": "run_id", "order": {"_key": "desc"}, "size": size}}},
        },
    )
    return [bucket["key_as_string"] for bucket in response["aggregations"]["runs"]["buckets"]]


def _fetch_run(config: InventoryConfig, run_id: str) -> dict[int, dict[str, Any]]:
    from opensearchpy.helpers import scan

    docs = scan(_client(config), index=config.index, query={"query": {"term": {"run_id": run_id}}})
    return {doc["_source"]["rating_key"]: doc["_source"] for doc in docs}


@dataclass(frozen=True)
class VideoChange:
    rating_key: int
    title: str
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    attributed: bool = False


def _has_matching_audit_event(
    audit_client: Any, audit_index: str, *, rating_key: int, collection: str, action: str, since: str, until: str
) -> bool:
    # The plexadm-audit index maps "collection" as `type: keyword` directly (see plexadm.audit),
    # not `text` with a `.keyword` multi-field - querying "collection.keyword" hits a field that
    # doesn't exist and OpenSearch silently returns zero hits rather than erroring. Real bug found
    # live: this made every single diffed change report UNATTRIBUTED regardless of whether
    # plexadm itself made it - confirmed by querying the real cluster directly, which found 763
    # matching "01: Hair: Blonde" add events that this lookup was reporting as absent.
    response = audit_client.search(
        index=audit_index,
        body={
            "size": 0,
            "track_total_hits": True,
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"rating_key": rating_key}},
                        {"term": {"action": action}},
                        {"term": {"collection": collection}},
                        {"range": {"timestamp": {"gte": since, "lte": until}}},
                    ]
                }
            },
        },
    )
    return bool(response["hits"]["total"]["value"])


def diff_snapshots(
    config: InventoryConfig,
    *,
    run_a: str | None = None,
    run_b: str | None = None,
    audit_index: str | None = None,
) -> tuple[str, str, list[VideoChange]]:
    """Compare two snapshots (default: the two most recent) and report every video whose
    collection membership changed between them. When audit_index is given, each change is
    cross-checked against plexadm's own audit trail in that same window - a change with no
    matching audit event is exactly the "something else touched this" case this system exists
    to catch precisely, instead of reconstructing it from server logs after the fact.
    """
    if run_b is None:
        run_ids = _fetch_run_ids(config, size=2)
        if len(run_ids) < 2:
            raise ValueError(f"Need at least 2 snapshots to diff - only found {len(run_ids)}.")
        run_b, run_a = run_ids[0], run_ids[1]
    elif run_a is None:
        raise ValueError("run_a is required when run_b is given explicitly.")

    older = _fetch_run(config, run_a)
    newer = _fetch_run(config, run_b)

    audit_client = _client(config) if audit_index else None
    changes: list[VideoChange] = []
    for rating_key, new_doc in newer.items():
        old_doc = older.get(rating_key)
        old_cols = set(old_doc["collections"]) if old_doc else set()
        new_cols = set(new_doc["collections"])
        added = sorted(new_cols - old_cols)
        removed = sorted(old_cols - new_cols)
        if not added and not removed:
            continue
        attributed = True
        if audit_client is not None:
            assert audit_index is not None  # audit_client is only set when audit_index is truthy
            for collection in added:
                if not _has_matching_audit_event(
                    audit_client,
                    audit_index,
                    rating_key=rating_key,
                    collection=collection,
                    action="add",
                    since=run_a,
                    until=run_b,
                ):
                    attributed = False
            for collection in removed:
                if not _has_matching_audit_event(
                    audit_client,
                    audit_index,
                    rating_key=rating_key,
                    collection=collection,
                    action="remove",
                    since=run_a,
                    until=run_b,
                ):
                    attributed = False
        changes.append(
            VideoChange(
                rating_key=rating_key,
                title=str(new_doc["title"]),
                added=added,
                removed=removed,
                attributed=attributed,
            )
        )
    return run_a, run_b, changes
