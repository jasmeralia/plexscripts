# Plan: Hair-color backfill, unmapped-tag discovery, and markdown reporting

Extends `plexadm/stash_backfill_tags.py` (from `plans/stash-to-plex-tag-backfill.md`, implemented in PR #31, not yet merged — build on top of that same branch/module). Three additions, in this order of dependency:

1. Hair-color tags become a second, purely-additive mapped scope alongside composition.
2. A new `plexadm stash unmapped-tags` subcommand audits every real Stash tag against the *actual* Plex collection list and reports gaps as markdown, sorted by scene count, each linking to the tag's Stash page.
3. `plexadm stash backfill-tags` gains a markdown report (in addition to the existing JSON review file), written in both dry-run and real-apply modes.

## 1. Hair-color backfill

**Semantics decision: additive-only, no conflict/removal logic.** Composition tags (`Solo`/`FFM`/`Gangbang`/etc.) describe the *scene's arrangement* and are mutually exclusive by construction — that's why `classify_scene` has conflict groups and proposes removals. Hair color describes *individual performers*, and a single scene can legitimately have multiple simultaneous hair-color tags (e.g. an FFM scene with a blonde and a brunette) without any contradiction. This tool has no per-performer granularity, so there is no reliable way to detect a hair-color "contradiction" the way composition contradictions are detected. Do not attempt one. Hair tags are simply: present in Stash, missing in Plex → add. Never proposed for removal, never staged as ambiguous, never routed through the review file.

**Do not touch `classify_scene` or any of its existing tests.** It stays composition-only, exactly as shipped in PR #31. Hair gets its own, much simpler code path.

In `plexadm/stash_backfill_tags.py`, add:

```python
from plexadm.cli import EXCLUDED_COMPOSITION_COLLECTIONS, EXCLUDED_HAIR_COLLECTIONS  # both already exist in cli.py

HAIR_COLLECTIONS = frozenset(EXCLUDED_HAIR_COLLECTIONS)  # "01: Hair: Black", "01: Hair: Blonde", ... (11 entries)
HAIR_TAGS = frozenset(tag for c in HAIR_COLLECTIONS if (tag := _collection_to_tag(c)) is not None)
```

(`EXCLUDED_HAIR_COLLECTIONS` is defined at `plexadm/cli.py` around line 57 — reuse it, don't duplicate the list. Note it includes `"01: Hair: Black"` and `"01: Hair: Unknown"`, which as of 2026-07-16 have no matching Stash tag — that's fine, they just never produce any adds; no special-casing needed.)

**Generalize the existing tag-extraction helpers to take an explicit scope**, rather than adding parallel hair-specific copies:

```python
def _stash_tags_in_scope(scene: dict[str, Any], scope: frozenset[str]) -> set[str]:
    return {str(tag["name"]) for tag in scene.get("tags") or [] if tag.get("name") and str(tag["name"]) in scope}


def _plex_tags_in_scope(video: Any, scope: frozenset[str]) -> set[str]:
    tags = {_collection_to_tag(str(collection)) for collection in getattr(video, "collections", None) or []}
    return {tag for tag in tags if tag in scope}
```

Rename the two existing composition-specific functions (`_stash_composition_tags`, `_plex_composition_tags`) to these generalized names, and update their two call sites in `backfill_tags()` to pass `COMPOSITION_TAGS` explicitly (`_stash_tags_in_scope(scene, COMPOSITION_TAGS)`, etc.) — this is a pure rename plus one added parameter, no behavior change for the composition path. Update the corresponding tests in `tests/test_stash_backfill_tags.py` (`TestTagCollectionMapping`) to match the new names/signatures.

**Wire hair into `backfill_tags()`'s existing per-video loop**, alongside the existing composition `classify_scene` call:

```python
stash_hair_tags = _stash_tags_in_scope(scene, HAIR_TAGS)  # union across matched.values(), same pattern as composition
plex_hair_tags = _plex_tags_in_scope(video, HAIR_TAGS)
hair_adds = sorted(stash_hair_tags - plex_hair_tags)
for tag in hair_adds:
    hair_additions[tag].append(video)
```

`hair_additions: dict[str, list[Any]] = defaultdict(list)` — a second accumulator dict, separate from the existing composition `additions` dict, so the two can be reported separately (see §3). Apply both through the same `add_items(collection, videos, dry_run=args.dry_run)` call pattern already used for composition, one loop after the other over `sorted(hair_additions.items())`, exactly mirroring the existing composition-apply loop. Track a `hair_added_count` separate from the existing `added_count` (rename that variable to `composition_added_count` for clarity, update its console print label accordingly — currently prints `"Composition memberships added: {added_count}"`, keep that label but rename the underlying variable).

Add a new console line: `print(info(f"Hair memberships added: {hair_added_count}"))`.

### Tests to add (`tests/test_stash_backfill_tags.py`)

- `TestHairBackfill` (new class): a scene with Stash tags `{"Hair: Red", "Hair: Blonde"}` and Plex collections `["01: Hair: Red"]` → hair adds `["Hair: Blonde"]` only (Red already present, not re-added). A scene where Stash and Plex already agree → no hair adds. Confirm via an integration-style test (same mocking pattern as `TestBackfillIntegration`) that `add_items` gets called for the hair collection with `dry_run=args.dry_run` propagated, and that hair tags never appear in the JSON review file (since they're never removed/ambiguous).
- Update `TestTagCollectionMapping` for the renamed `_stash_tags_in_scope`/`_plex_tags_in_scope` signatures.

## 2. `plexadm stash unmapped-tags`

**What "unmapped" means, precisely**: a Stash tag is "mapped" if `_tag_to_collection(tag.name)` is the exact title of a collection that actually exists in the configured Plex library section right now — not "is it in `COMPOSITION_TAGS`/`HAIR_TAGS`" (those are just the tags this tool actively *manages*; plenty of other tags could already have a manually-created matching Plex collection that this tool doesn't touch, and those should count as mapped too, not show up as a gap). Query Plex's real collection list once (`ctx.section.collections()`, `.title` per collection — same access pattern already used in `plexadm/cli.py::rename_collections`) and build `existing_titles = {str(c.title) for c in ctx.section.collections()}`. A Stash tag is unmapped iff `_tag_to_collection(tag.name) not in existing_titles`.

**Data source**: Stash's GraphQL schema exposes `scene_count` directly on the `Tag` type (confirmed via introspection against the live instance) — no need to compute it via per-tag scene queries. Add one method to `StashClient` (`plexadm/stash.py`):

```python
_ALL_TAGS = """
query AllTags {
  allTags { id name scene_count }
}
"""


def all_tags(self) -> list[dict[str, Any]]:
    """Return every Stash tag with its id, name, and scene_count."""
    return self._gql(_ALL_TAGS)["allTags"]  # _gql's variables arg defaults to None; no variables needed for this query
```
(`_gql(self, query, variables=None)` — confirmed from the existing `plexadm/stash.py` signature; omit the variables argument entirely for this no-argument query, matching how `variables=None` is already the default. Match the existing naming convention for query constants, e.g. `_FIND_SCENES`/`_FIND_PERFORMER` — name this one `_ALL_TAGS`, defined at module level alongside the others.)

**No count/limit filtering flag** — report every unmapped tag, sorted descending by `scene_count`; the sort order alone makes the report usable without needing a cutoff flag. Do not add a `--min-count` or similar flag; keep the CLI surface minimal.

**Link format — use the tag detail page, not a filtered scene-list deep link.** Stash's scene-list page uses complex, version-fragile client-side-encoded filter state in its URL (confirmed problematic earlier this session with a structurally similar OpenSearch Dashboards deep link that failed to parse). The tag detail page is a simple, stable, path-based route: `{endpoint}/tags/{tag_id}` (confirmed reachable: `https://stash.jasmer.tools/tags/1` returns HTTP 200). Build the link from the resolved Stash `endpoint` (already available as a local variable in every function in this module that talks to Stash — do not hardcode `stash.jasmer.tools`), stripping any trailing `/graphql` the same way `StashClient.__init__` does (`endpoint.rstrip("/")` then append `/tags/{id}` — do NOT append `/graphql` for this link, that's the API endpoint not the web UI).

**New function** in `plexadm/stash_backfill_tags.py`:

```python
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

    print(info("Fetching Plex collections..."))
    plex_ctx = PlexContext(cfg)
    existing_titles = {str(c.title) for c in plex_ctx.section.collections()}

    unmapped = [t for t in tags if _tag_to_collection(str(t["name"])) not in existing_titles]
    unmapped.sort(key=lambda t: t.get("scene_count") or 0, reverse=True)

    report_path = Path(getattr(args, "output", "reference/stash_unmapped_tags.md"))
    _write_unmapped_tags_report(report_path, unmapped, web_base, total_tag_count=len(tags))

    print(ok(f"Unmapped tags: {len(unmapped)} of {len(tags)} total"))
    print(info(f"Report written to {report_path}"))
    return 0
```

`_write_unmapped_tags_report(path, unmapped, web_base, *, total_tag_count)` writes markdown:

```markdown
# Stash Tags With No Matching Plex Collection

Generated: 2026-07-16T18:04:00Z

Found 1043 unmapped tags out of 1070 total Stash tags.

| Scenes | Tag | Link |
|---:|---|---|
| 2838 | Category: Blowjob | [view](https://stash.jasmer.tools/tags/12) |
| ... | ... | ... |
```

Tag names go through a small markdown-table-cell escape (replace literal `|` with `\|`; wrap the whole cell in backticks is NOT necessary unless the name contains `|` — just escape it) since Stash tag names are free text and could theoretically contain a pipe character. `generated_at` uses the same UTC `strftime("%Y-%m-%dT%H:%M:%SZ")` pattern as `_write_review`.

### CLI wiring (`plexadm/cli.py`)

New subparser `unmapped-tags` under `_build_stash_commands`, following the existing `backfill-tags`/`apply-review` pattern (import inside the function body alongside the other two, same circular-import workaround already in place):

```
plexadm stash unmapped-tags [--output PATH] [--stash-endpoint URL] [--log-level LEVEL]
```

- `--output` (default `reference/stash_unmapped_tags.md`)
- `--stash-endpoint`, `--log-level`: same as the other stash subcommands.
- No `--limit`/`--path` (this command isn't scoped to a Plex path subset — it's a whole-library tag audit).

### Tests to add

`TestUnmappedTags` in `tests/test_stash_backfill_tags.py`: mock `StashClient.all_tags` to return a small fixed tag list (some matching an existing mocked Plex collection title, some not), mock `plex_ctx.section.collections()` to return a couple of `SimpleNamespace(title=...)` objects, call `unmapped_tags(args)`, and assert: (a) the correctly-computed unmapped subset excludes the tag whose mapped title exists in Plex, (b) the written markdown file (via `tmp_path`) contains the expected tag names sorted descending by `scene_count`, (c) the link URL is built from `web_base` correctly (test with an endpoint ending in `/graphql` to confirm the strip logic works) and does NOT include `/graphql` in the final link.

## 3. Markdown report for `backfill-tags`

Applies in **both** dry-run and real-apply modes — the report reflects "what happened" (or "what would have happened" in dry-run), not just "what got written to Plex". Written unconditionally at the end of `backfill_tags()`, alongside the existing JSON review file (which is unchanged — this is an additional output, not a replacement).

New CLI flag on `backfill-tags`: `--report-output` (default `reference/stash_backfill_report.md`).

New function `_write_backfill_report(path, *, dry_run, processed, matched_count, composition_additions, hair_additions, composition_added_count, hair_added_count, ambiguous_entries, review_path, review_entry_count)` writing:

```markdown
# Stash -> Plex Backfill Report

Generated: 2026-07-16T18:10:00Z
Mode: DRY RUN (no Plex changes made)

## Summary

- Plex videos scanned: 6623
- Matched to Stash: 6605
- Composition memberships added: 42
- Hair memberships added: 18
- Ambiguous matches staged for review: 3
- Review entries written: 3 -> reference/stash_backfill_review.json

## Composition additions by collection

| Collection | Videos added |
|---|---:|
| 01: Category: Solo | 12 |
| 01: Category: Lesbian | 30 |

## Hair additions by collection

| Collection | Videos added |
|---|---:|
| 01: Hair: Red | 18 |

## Ambiguous scenes (staged for review, not applied)

| Title | Reason |
|---|---|
| Example Writer - Post - 2023-01-16... | cross-axis: ['Category: Solo'] + ['Category: Lesbian'] |
```

`Mode:` line reads `Mode: DRY RUN (no Plex changes made)` when `args.dry_run` else `Mode: APPLIED`. Omit the "Composition additions by collection" / "Hair additions by collection" tables entirely (not an empty table) when their respective dict is empty; same for the ambiguous-scenes table when there are zero ambiguous entries — print a plain `_No ambiguous scenes this run._` line instead of an empty table, matching how the review file already treats zero-entries as a legitimate outcome. Escape `|` in titles and reasons the same way as the unmapped-tags report.

This reuses the same per-video loop already iterating in `backfill_tags()` — no second pass over the library. Accumulate `ambiguous_entries: list[tuple[str, str]]` (title, ambiguous_reason) inline where `ambiguous_count` is already incremented, rather than a separate collection pass.

### Tests to add

Extend `TestBackfillIntegration`: assert the markdown report file (via `tmp_path`, new `report_output` arg on the fake `args`) contains the right `Mode:` line for both a `dry_run=True` and a `dry_run=False` case, and that an ambiguous-producing scenario produces the ambiguous-scenes table with the expected title/reason.

## Non-goals (explicitly out of scope for this task)

- Do not extend `apply_review` with a markdown report — the task only asked for one on `backfill-tags`.
- Do not add conflict/removal detection for hair colors, or any cross-checking between composition and hair scope (e.g. "single performer + 2 hair tags = contradiction") — deliberately out of scope per §1's reasoning; this tool has no per-performer data to make that call safely.
- Do not touch `classify_scene`, its dataclass, or its existing tests — hair is additive-only and doesn't need the conflict-group machinery at all.
- Do not add a min-count/limit flag to `unmapped-tags` — sort order alone is sufficient per the design above.
- Do not wire any of this into `scripts/mass_process.sh` — matches the existing non-goal already established for `backfill-tags` itself in `plans/stash-to-plex-tag-backfill.md`.

## Acceptance criteria

- `make lintfix && make lint && make test` all pass.
- All new/changed functions have test coverage matching the patterns above.
- Real dry-run smoke test (`plexadm stash backfill-tags --dry-run --limit 200`) still runs cleanly against the live Plex/Stash servers and now additionally reports hair additions and writes both a JSON review file and a markdown report.
- `plexadm stash unmapped-tags` run against the live servers produces a markdown file with real tag names, real scene counts in descending order, and working `/tags/{id}` links built from the configured endpoint.

## Critical files

- `plexadm/stash_backfill_tags.py` (extend: hair scope, generalized extraction helpers, `unmapped_tags`, `_write_unmapped_tags_report`, `_write_backfill_report`)
- `plexadm/stash.py` (extend: `StashClient.all_tags`)
- `plexadm/cli.py` (extend: `unmapped-tags` subparser, `--report-output` flag on `backfill-tags`)
- `tests/test_stash_backfill_tags.py` (extend: `TestHairBackfill`, `TestUnmappedTags`, report-content assertions in `TestBackfillIntegration`)
- `tests/test_stash.py` does **not** exist on this branch (confirmed: `feat/stash-backfill-tags` was branched from master before PR #30, which added that file, was merged). Add `all_tags` test coverage as a new small test class inside `tests/test_stash_backfill_tags.py` instead of creating a new file for one method.
