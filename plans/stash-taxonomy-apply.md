# Plan: Apply the full-taxonomy Stash tag classifier (Phase 2 of the Stash → Plex tag backfill)

## Summary

`plexadm stash unmapped-tags` classifies every unmapped Stash tag as Add/Merge/Skip via
`_suggested_action()` in `plexadm/stash_backfill_tags.py`, writing `reference/stash_unmapped_tags.md`
for human review. That classifier is correct and has been extensively fixed/reviewed this session
(Anal/Blowjob position clusters, the SKIP-list reclassification round). **But nothing applies its
decisions.** `plexadm stash backfill-tags` (`backfill_tags()`) only ever handles the Composition
axis (Solo/MF Only/MMF/.../Lesbian) and Hair color, via its own deterministic `classify_scene()`
conflict logic - unrelated to `_suggested_action`. This was `plans/stash-to-plex-tag-backfill.md`'s
own explicit "Phase 2 (separate, later effort, not designed here)" - scoped out of v1, never
built.

**This plan extends `backfill_tags()` in place** - same command (`plexadm stash backfill-tags`),
same report file, same review file - to *also* materialize exactly what `unmapped-tags`' `## Merge`
section (plus accepted bare-`## Add` suggestions) already says: creating new Plex collections
where needed and adding the matching videos, in the same scan pass that already handles
Composition/Hair. This is explicitly **not** a new/separate command - do not add one.
**Additions only, never removals**, for this new taxonomy scope - there's no established
mutual-exclusion structure for it the way Composition has (`GROUP_SINGLE_FEMALE` etc.), so removal
logic stays out of scope, consistent with the original plan's own reasoning for restricting itself
to Composition. Composition/Hair keep their existing removal-via-review-file behavior unchanged.

## 1. Refactor `_suggested_action` to expose its resolved target list (behavior-preserving)

File: `plexadm/stash_backfill_tags.py`. `_suggested_action()` currently computes a fully-resolved
target list internally (in four separate branches: exact-match, multi-target, category, and the
tagalong-only fallback) but only returns the joined display string (`f"merge -> {' + '.join(...)}"`).
The new code in `backfill_tags()` needs the raw list, not a string to re-parse (target names are
not guaranteed free of `" + "` as a substring forever, and re-parsing a display string is
fragile). Extract two helpers and have `_suggested_action` delegate to them - **the full existing
`tests/test_stash_backfill_tags.py` suite must pass unchanged after this refactor**, since it
already exercises `_suggested_action` exhaustively; that's the acceptance check for "this refactor
didn't change behavior."

```python
def _is_skip_tag(tag_name: str) -> bool:
    """Extracted from _suggested_action's skip check - also needed standalone by
    _apply_targets, which must not apply a tag whose name happens to collide with an
    accepted collection name but is still skip-listed."""
    lower_name = tag_name.lower()
    words = set(re.findall(r"[a-z0-9]+", lower_name))
    return lower_name in _SKIP_EXACT_TAG_NAMES or bool(
        words & (_SKIP_MARKER_WORDS | _SKIP_GENERIC_BODY_WORDS | _SKIP_EYE_COLOR_WORDS | _SKIP_AGE_WORDS)
    )


def _resolved_merge_targets(tag_name: str, existing_titles: set[str]) -> list[str] | None:
    """Return the resolved target list if tag_name fully resolves to a merge (every listed
    target exists in existing_titles), mirroring _suggested_action's matching order exactly:
    skip check, then exact/multi/category phrases, then the hair-color path, then the
    tagalong-only fallback. Returns None if the tag is skip-listed or nothing resolves (would
    fall through to plain "add" in _suggested_action)."""
    if _is_skip_tag(tag_name):
        return None
    lower_name = tag_name.lower()
    words = set(re.findall(r"[a-z0-9]+", lower_name))

    exact_target = _EXACT_MATCH_MERGE_PHRASES.get(lower_name)
    if exact_target:
        resolved = [_resolve_existing(t, existing_titles) for t in _with_tagalong(tag_name, [exact_target])]
        if all(resolved):
            return resolved  # type: ignore[return-value]
    for phrase, targets in _MULTI_TARGET_MERGE_PHRASES.items():
        if phrase in lower_name:
            resolved = [_resolve_existing(t, existing_titles) for t in _with_tagalong(tag_name, targets)]
            if all(resolved):
                return resolved  # type: ignore[return-value]
    for phrase, target in _CATEGORY_MERGE_PHRASES.items():
        if phrase in lower_name:
            resolved = [_resolve_existing(t, existing_titles) for t in _with_tagalong(tag_name, [target])]
            if all(resolved):
                return resolved  # type: ignore[return-value]
    if words & _HAIR_CONTEXT_WORDS:
        for word in words:
            hair_target = _HAIR_MERGE_KEYWORDS.get(word)
            if hair_target and hair_target in existing_titles:
                return [hair_target]
    tagalong = _tagalong_targets(tag_name)
    if tagalong:
        resolved = [
            _resolve_existing(t, existing_titles)
            for t in _with_tagalong(tag_name, [_suggest_new_collection_name(tag_name)])
        ]
        if all(resolved):
            return resolved  # type: ignore[return-value]
    return None


def _suggested_action(tag_name: str, existing_titles: set[str]) -> str:
    """... (existing docstring unchanged) ..."""
    if _is_skip_tag(tag_name):
        return "skip"
    resolved = _resolved_merge_targets(tag_name, existing_titles)
    if resolved is not None:
        return f"merge -> {' + '.join(resolved)}"
    return "add"
```

Note `_potential_merge_targets` is a **separate, pre-existing function** for its own reasons (it
ignores the existence gate entirely, for the report's "Pending Collections" section) - do not
merge it with `_resolved_merge_targets`, which is existence-gated by design. Leave it untouched.

## 2. New function: `_apply_targets`

Same file. Combines `_resolved_merge_targets` with the "bare Add tag whose own suggested name has
already been accepted" case (e.g. a tag like `"Missionary"` itself, with no merge rule at all,
whose suggested name `"01: Activity: Missionary"` is in `_ACCEPTED_ADD_COLLECTIONS`):

```python
def _apply_targets(tag_name: str, resolve_titles: set[str]) -> list[str] | None:
    """The full list of collection titles a tag should be applied to during backfill_tags'
    taxonomy pass, or None if it shouldn't be touched at all (skip-listed, or an Add suggestion
    that hasn't been accepted yet - see _ACCEPTED_ADD_COLLECTIONS). `resolve_titles` must be
    `existing_titles | _ACCEPTED_ADD_COLLECTIONS`, exactly like _write_unmapped_tags_report's
    resolve_titles - this function exists specifically to keep backfill_tags' taxonomy behavior
    identical to what the unmapped-tags report's `## Merge` section already shows, not to
    introduce new judgment calls.
    """
    resolved = _resolved_merge_targets(tag_name, resolve_titles)
    if resolved is not None:
        return resolved
    if _is_skip_tag(tag_name):
        return None
    suggested = _suggest_new_collection_name(tag_name)
    if suggested in _ACCEPTED_ADD_COLLECTIONS:
        return _with_tagalong(tag_name, [suggested])
    return None
```

## 3. Extend `backfill_tags()` in place - do not add a new command

Same file, in the existing `backfill_tags(args)` function. New imports needed at the top of the
file: `create_collection` from `plexadm.plex` (already exists, already tested in
`tests/test_plex.py`, currently has zero callers in any command - this is its first real use).
`_has_existing_plex_match` and `_ACCEPTED_ADD_COLLECTIONS` are already defined in this same file.

**Before the existing scan loop**, add:

```python
    print(info("Fetching Stash tags..."))
    tags = stash.all_tags()  # `stash` already exists at this point in the function

    existing_titles = {str(collection.title) for collection in plex_ctx.section.collections()}
    resolve_titles = existing_titles | _ACCEPTED_ADD_COLLECTIONS

    # Same "unmapped, non-local" scope as unmapped_tags() - local tags (no stash_ids) are
    # already reflected in Plex via plexadm stash sync-tags, nothing to apply for them.
    candidates = [tag for tag in tags if not _has_existing_plex_match(tag, existing_titles)]
    unmapped = [tag for tag in candidates if tag.get("stash_ids") or []]
    apply_map: dict[str, list[str]] = {}
    for tag in unmapped:
        targets = _apply_targets(str(tag["name"]), resolve_titles)
        if targets:
            apply_map[str(tag["name"])] = targets
```

(`plex_ctx` is created slightly later in the current function, right after the Stash-index log
line - either move that one line earlier or compute `existing_titles`/`resolve_titles`/
`apply_map` right after `plex_ctx = PlexContext(cfg)` instead of before it; either ordering is
fine, just keep `tags = stash.all_tags()` grouped with the existing `print(info("Connecting to
Stash and building scene index..."))` / `stash_index = stash.all_scenes()` block so the Stash
round-trips are visually grouped, matching this file's existing style.)

Add a `taxonomy_additions: dict[str, list[Any]] = defaultdict(list)` alongside the existing
`additions`/`hair_additions` accumulator declarations.

**Inside the existing per-video loop**, after the existing hair/composition blocks (right after
`review_entries.extend(_decision_entries(decision, stash_tags, plex_tags))`), add:

<!-- fmt: off -->
```python
        video_stash_tags = {
            str(t["name"]) for scene in matched.values() for t in (scene.get("tags") or []) if t.get("name")
        }
        video_plex_collections = {str(c) for c in getattr(video, "collections", None) or []}
        for tag_name in video_stash_tags & apply_map.keys():
            for target in apply_map[tag_name]:
                if target not in video_plex_collections:
                    taxonomy_additions[target].append(video)
```
<!-- fmt: on -->

`matched` here is the same `dict[str, dict[str, Any]]` of matched Stash scenes the existing hair/
composition code already builds and iterates (`matched.values()`) - reuse it, don't refetch or
recompute scene matching.

**After the loop, alongside the existing composition/hair apply blocks**, add:

```python
    new_collections: list[str] = []
    taxonomy_added_count = 0
    for target, videos in sorted(taxonomy_additions.items()):
        if target in existing_titles:
            collection = plex_ctx.collection(target)
            taxonomy_added_count += add_items(collection, videos, dry_run=args.dry_run)
        else:
            new_collections.append(target)
            create_collection(plex_ctx.section, title=target, items=videos, dry_run=args.dry_run)
            taxonomy_added_count += len(videos)
```

Notes on why each piece is shaped this way:
- `video_stash_tags & apply_map.keys()` only visits tags actually relevant to this video, not
  every unmapped tag in the library, per video.
- `if target not in video_plex_collections` skips a video that (per its live Plex collection
  membership right now) is already in the target - avoids a redundant `add_items` call. Both
  `add_items` and `create_collection` already de-duplicate/no-op safely on their own, so this is
  an optimization, not a correctness requirement - keep it, but it is not load-bearing.
- New-collection creation happens in the same "accumulate everything for this target across the
  whole scan, then create once" shape this function already uses for existing collections -
  required because Plex's `createCollection` needs at least one item and there's no
  "create-empty-then-add" path for manual collections (see `create_collection`'s own docstring
  in `plexadm/plex.py`).
- `99: LOCKED` is respected automatically: both `add_items` and `create_collection` call
  `_drop_locked()` internally already (see `plexadm/plex.py`) - no special handling needed here.
- No removals for the taxonomy scope anywhere in this addition - out of scope per the Summary.
  Composition/Hair keep their existing removal-via-review-file behavior completely unchanged.

Extend the function's final `print(...)` summary block with two more lines (after the existing
"Hair memberships added" line): `Taxonomy memberships added: {taxonomy_added_count}` and
`New collections created: {len(new_collections)}`.

## 4. Extend `_write_backfill_report` in place - do not add a new report writer

Same file. Add three new keyword-only parameters: `taxonomy_additions: dict[str, list[Any]]`,
`new_collections: list[str]`, `taxonomy_added_count: int`. Add them to the `## Summary` bullet
list (after the existing "Hair memberships added" line, same style: `- Taxonomy memberships
added: {taxonomy_added_count}` and `- New collections created: {len(new_collections)}`). Add a
new `## Taxonomy additions by collection` section, same table shape as the existing `## Hair
additions by collection` section immediately above it in the file, but mark which rows are
brand-new collections (e.g. append `" (new)"` to the collection name, or add a third `New?`
column - match whichever is less disruptive to the existing table-building code style). Update
every call site of `_write_backfill_report` (there is exactly one, inside `backfill_tags()`) to
pass the three new arguments.

## 5. CLI

File: `plexadm/cli.py`. No new subcommand, no new flags - `backfill-tags`'s existing argument set
(`--limit`, `--path`, `--log-level`, `--stash-endpoint`, `--review-output`, `--report-output`,
plus common `--config`/`--dry-run`) already covers everything this extension needs, since it's the
same command with expanded scope. Update `backfill_parser`'s `description=` text (search for
`"backfill-tags"` in `_build_stash_commands`, or similar) to mention the new taxonomy scope
alongside the existing Composition/Hair description - read the current description text first and
extend it in the same voice, don't replace it wholesale.

## 6. Tests

File: `tests/test_stash_backfill_tags.py` (existing file, already large - add new test classes/
cases, don't create a second test file for this module).

**Existing tests will break without a mock update - fix this first.** `backfill_tags()` now also
calls `stash.all_tags()` (see section 3). Every existing test that mocks `stash = MagicMock()` and
calls `backfill_tags(args)` (`TestHairBackfill`, `TestBackfillIntegration`, and any others found
by grepping this file for `backfill_tags(args)`) needs `stash.all_tags.return_value = []` added
(empty list is fine and keeps those tests scoped to Composition/Hair only, as they already are) -
otherwise `stash.all_tags()` returns an unconfigured `MagicMock`, which is not iterable, and every
one of those tests will fail with a `TypeError` on the new `for tag in tags` (or equivalent) line,
not because of a real regression.

New coverage needed:
- `_resolved_merge_targets`: a couple of direct calls confirming it returns the raw list (e.g.
  `_resolved_merge_targets("Anal Missionary", {"01: Category: Anal", "01: Activity: Missionary"}) == ["01: Category: Anal", "01: Activity: Missionary"]`)
  and that it returns `None` for a skip-listed tag even when its name coincidentally matches
  something resolvable.
- `_apply_targets`: tests covering (a) a tag with an explicit merge rule, (b) a bare-name tag
  whose suggested name is in `_ACCEPTED_ADD_COLLECTIONS`, (c) a bare-name tag whose suggested name
  is *not* accepted (must return `None` - this is the "leave unreviewed Add suggestions alone"
  guarantee, the most important behavior to pin down with a test), (d) a skip-listed tag whose
  name happens to equal an accepted collection's suggested name (must still return `None`).
- `backfill_tags()` taxonomy scope, in the style of the existing `TestBackfillIntegration` class:
  (a) a Stash tag merging into an existing (already-real) Plex collection adds the matching video
  via `add_items`; (b) a Stash tag whose target doesn't exist yet but is accepted creates it via
  `create_collection` seeded with the matching video(s); (c) a Stash tag classified skip is never
  touched; (d) a bare unaccepted Add tag is never touched; (e) `--dry-run` makes no Plex calls
  that mutate state (assert on the mocked `add_items`/`create_collection` args, matching how
  `TestBackfillIntegration`'s existing dry-run test already asserts this for Composition); (f) the
  report includes the new `## Taxonomy additions by collection` section with correct counts; (g)
  existing Composition/Hair behavior is unaffected by any of the above (i.e. a single test with
  both a Composition tag and an unrelated taxonomy tag present on the same scene, asserting both
  get applied correctly and independently).

File: `tests/test_plex.py` needs no changes - `create_collection` is already fully tested there.

## 7. Docs

File: `AGENTS.md`. Find wherever `backfill-tags`/`unmapped-tags` are currently documented (grep
for `backfill-tags` first) and extend that section's description of scope: `backfill-tags` now
also applies exactly what `unmapped-tags`' `## Merge` section (plus accepted bare-`## Add`
suggestions) already resolves, in the same run as the existing Composition/Hair pass - additions
only for this new scope, creates new collections as needed, safe to re-run (idempotent - a video
already in a target collection is simply skipped). If neither command is currently documented in
AGENTS.md, add a new section rather than assuming - grep first.

## Non-goals (explicitly out of scope for this change)

- No removals of any kind for the taxonomy scope - mirrors the "safe, reversible" framing the
  original Composition backfill plan used for its own additions. Composition/Hair's existing
  removal-via-review-file behavior is completely unchanged.
- No handling of un-accepted `## Add` suggestions - a tag whose suggested collection name isn't
  in `_ACCEPTED_ADD_COLLECTIONS` is left alone, full stop. Accepting new taxonomy decisions stays
  a manual step (editing `_ACCEPTED_ADD_COLLECTIONS`), not something this command infers.
- No handling of `## Existing "01: Category:" Rename Suggestions` or `_EXISTING_CATEGORY_RENAMES`
  - those are a separate, already-existing manual/semi-manual process (`plexadm collection
  rename-categories`), untouched by this plan.
- No new command, no new CLI flags, no new report/review file paths - this is purely an in-place
  extension of `backfill_tags()`, `_write_backfill_report()`, and the existing `backfill-tags`
  subcommand. Do not create `apply_taxonomy()` or any other new top-level command function.
- No concurrency/locking against another plexadm process running at the same time - same
  assumption every other command in this codebase already makes.

## Acceptance criteria

1. `uv run pytest -q` passes in full, including the full existing `tests/test_stash_backfill_tags.py`
   suite (with the `stash.all_tags.return_value` mock fixes from section 6 applied - proves the
   `_suggested_action` refactor is behavior-preserving and the extension doesn't break Composition/
   Hair) plus the new tests from section 6.
2. `uv run ruff format --check` and `uv run ruff check` both pass clean on every changed file.
3. `plexadm stash backfill-tags --help` still renders correctly, with description text mentioning
   the expanded taxonomy scope.
4. `plexadm stash backfill-tags --dry-run --limit 25` runs against a real config without error
   (manual smoke check, not an automated test - Claude will run this after Codex reports done).
