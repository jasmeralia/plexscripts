# Plan: Stash → Plex Composition-Category Backfill

## Summary of the design

A new module `plexadm/stash_backfill_tags.py` implementing a new subcommand `plexadm stash backfill-tags`, which mirrors `stash_reconcile.py`'s Plex-iteration/path-matching structure but works in the opposite direction: for each Plex video, look at the Stash tags on its matched scene(s), and propose/apply changes to Plex's `01: Category: *` composition collections. Scope is the composition category subset for v1 (not the full `01: Category:` namespace — 106 Stash `Category:` tags currently exist vs. 12 composition collections). Additions are auto-applied (safe, reversible, consistent with the "mutations apply immediately" convention in AGENTS.md); removals and ambiguous cases are written to a JSON review file for a human, mirroring the workflow already used manually this session for `reference/lesbian_collection_corrections.json`.

## 1. Tag name mapping and scope

Reuse the existing prefix-stripping convention:
- `stash_sync_tags.py::_tag_name` strips a numeric sort prefix (`^\d{2}[A-Z]?: `) — general purpose.
- `stash_reconcile.py::_collection_to_tag` strips exactly `"01: "` and returns `None` for anything else — this is the one to mirror, since we're deliberately scoped to `01:` collections.

For the new module, define the inverse and reuse `_collection_to_tag`'s semantics rather than reinventing it:

```python
from plexadm.stash_reconcile import _collection_to_tag  # "01: Category: MF Only" -> "Category: MF Only"

def _tag_to_collection(tag_name: str) -> str:
    return f"01: {tag_name}"  # "Category: MF Only" -> "01: Category: MF Only"
```

**Scope decision: composition categories only for v1.** Define in `plexadm/stash_backfill_tags.py`:

```python
COMPOSITION_COLLECTIONS = frozenset(EXCLUDED_COMPOSITION_COLLECTIONS) | {"01: Category: Lesbian"}
```

importing `EXCLUDED_COMPOSITION_COLLECTIONS` from `plexadm/cli.py` (line ~26) rather than duplicating the list — that constant already enumerates the canonical 12 composition collections (FFF+, FFFM, FFM, FFT, Gangbang, MF Only, MMF, Non-Sexual, Orgy, Reverse Gangbang, Solo, Trans MTF). Note it does **not** include Lesbian (confirmed by reading `cli.py`) — Lesbian is deliberately added here because it's the collection this session's corrections were about and it participates in the conflict-detection groups below. Convert to Stash tag names once via `_collection_to_tag`.

**Why not the full `01: Category:` namespace now:** the other ~90 categories (Anal, Blowjob, Facial, etc.) have no established mutual-exclusion structure, so all of them would degrade to pure "Stash has it, Plex doesn't → add" with no conflict logic — much higher volume, and Stash's ground-truth reliability for non-composition tags hasn't been validated this session the way composition tags have. Recommend a **Phase 2** (separate, later effort, not designed here) that reuses the same scanning loop but drops the conflict logic entirely, since `_collection_to_tag` already generalizes to any `01: ` collection — the mapping mechanism doesn't need to change, only the scope list and the fact that Phase 2 has no groups (every match is `unambiguous_add`).

## 2. Conflict detection logic (precise rules)

Build directly on the two groups used this session, but split Group B into its headcount-bearing members and the orthogonal "Lesbian" activity tag, since FFM and Lesbian legitimately coexist, but the headcount tags don't coexist with each other.

```python
# Stash tag names (post "01: " strip)
GROUP_SINGLE_FEMALE = {
    "Category: Solo", "Category: MF Only", "Category: MMF", "Category: Gangbang",
}  # exactly one female performer present; pairwise mutually exclusive (each encodes
   # a distinct exact partner arrangement: 0, 1 male, 2 males, 3+ people)

GROUP_MULTI_FEMALE_HEADCOUNT = {
    "Category: FFM", "Category: FFFM", "Category: Reverse Gangbang", "Category: FFF+",
}  # 2+ females present; pairwise mutually exclusive (each encodes a distinct headcount)

GROUP_MULTI_FEMALE_ACTIVITY = {"Category: Lesbian"}  # girl-girl activity; compatible with
   # any single GROUP_MULTI_FEMALE_HEADCOUNT tag, but incompatible with GROUP_SINGLE_FEMALE

COMPOSITION_TAGS = GROUP_SINGLE_FEMALE | GROUP_MULTI_FEMALE_HEADCOUNT | GROUP_MULTI_FEMALE_ACTIVITY
```

Per scene, let `S` = Stash tags on the matched scene(s) ∩ `COMPOSITION_TAGS`, and `P` = the video's current Plex collection titles, mapped to tag names, ∩ `COMPOSITION_TAGS`.

```python
@dataclass
class SceneDecision:
    rating_key: str
    title: str
    file_paths: list[str]
    adds: list[str] = field(default_factory=list)              # tag names to add to Plex (safe)
    remove_candidates: list[str] = field(default_factory=list) # tag names to flag for removal (review)
    ambiguous_reason: str | None = None                        # set => stash itself is unreliable here


def classify_scene(stash_tags: set[str], plex_tags: set[str]) -> SceneDecision | None:
    s = stash_tags & COMPOSITION_TAGS
    p = plex_tags & COMPOSITION_TAGS
    if not s:
        return None  # no composition signal from Stash; nothing to do

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
        return SceneDecision(..., ambiguous_reason="; ".join(conflicts))

    # Stash is internally clean on this axis -> it's a trustworthy signal for this scene.
    adds = sorted(s - p)

    if single:
        contradicting = (GROUP_MULTI_FEMALE_HEADCOUNT | GROUP_MULTI_FEMALE_ACTIVITY
                          | (GROUP_SINGLE_FEMALE - single))
    else:
        contradicting = set(GROUP_SINGLE_FEMALE)
        if headcount:
            contradicting |= (GROUP_MULTI_FEMALE_HEADCOUNT - headcount)
        # note: lesbian alone (no headcount tag) does NOT mark other headcount tags as
        # contradicting, since headcount is simply unspecified in that case.

    remove_candidates = sorted(p & contradicting)

    if not adds and not remove_candidates:
        return None  # Plex already agrees with Stash; nothing to report

    return SceneDecision(..., adds=adds, remove_candidates=remove_candidates)
```

This exactly reproduces the logic already validated this session (the `root_cause_note`/`criteria` fields in `reference/lesbian_collection_corrections.json` describe precisely this Group-A vs. Group-B contradiction check) while avoiding the oversimplification of treating Lesbian as a headcount tag: Lesbian-only Stash signal does **not** flag other headcount tags as contradicting, and a scene tagged both FFM and Lesbian in Stash is correctly treated as clean (not ambiguous).

Note also: this function is pure and takes plain string sets — no Plex/Stash object dependencies — so it's trivially unit-testable without mocks.

## 3. Review process design (recommendation)

Weighing the three options against the asymmetric risk of additions vs. removals demonstrated this session (Stash is a better signal than Plex's current composition collections, but is not infallible — 4/405 internally-conflicting scenes found):

**Recommended: hybrid — auto-apply unambiguous additions immediately; stage removals and ambiguous cases in a JSON review file for a separate, explicit apply step.**

- Pure dry-run-report-only doesn't scale for an ongoing tool — a human re-issuing `plexadm collection add-title` by hand for hundreds of scenes per run isn't sustainable.
- Pure auto-apply-everything-unambiguous is too aggressive for removals: removing an existing Plex collection membership is destructive to curated data, and this session's own findings (Stash internal conflicts) prove Stash isn't a fully trusted oracle either. Symmetric auto-apply risks reintroducing exactly the kind of silent, hard-to-audit bulk corruption this session spent time fixing.
- Additions carry materially lower risk: adding a collection membership is purely additive, reversible, and matches AGENTS.md's stated norm ("apply changes immediately unless documented otherwise"). So additions get immediate-apply treatment; removals and conflicts get staged-review treatment.

Concretely:

1. `plexadm stash backfill-tags` (default): computes `adds` and `remove_candidates`/`ambiguous_reason` per scene. Only `adds` are applied immediately via `add_items`, respecting `--dry-run`. `remove_candidates` and `ambiguous_reason` entries are written to a JSON review file (default `reference/stash_backfill_review.json`, matching the precedent of `lesbian_collection_corrections.json`), **never auto-removed**.
2. A human inspects/edits the review file (spot-checks a sample, deletes entries they disagree with — same manual workflow already used this session).
3. `plexadm stash apply-review reference/stash_backfill_review.json [--include-ambiguous]` — a second small subcommand that reads the (possibly human-edited) file and calls `remove_items` for each surviving `remove_candidate` entry (skipping `ambiguous` entries by default). Respects `--dry-run`.

Review file schema (reuse the field names from `reference/lesbian_collection_corrections.json` for continuity/tooling reuse, generalized to be pre-application rather than a post-hoc audit log):

```json
{
  "generated_at": "2026-07-12T10:30:44Z",
  "action": "remove_candidate | ambiguous",
  "rating_key": "126146",
  "title": "Example Writer - AVNSocial Events #1",
  "file_paths": ["/data/NSFW Scenes/Example Writer/Example Writer - AVNSocial Events #1.mp4"],
  "stash_tags": ["Category: Solo"],
  "plex_tags": ["01: Category: Solo", "01: Category: Lesbian"],
  "collection_to_remove": "01: Category: Lesbian",
  "reason": "tagged 'Category: Solo' (single performer) in Stash - no second performer present, so 'Lesbian' membership is a logical contradiction",
  "status": "proposed"
}
```
(`ambiguous` entries omit `collection_to_remove` and instead carry `ambiguous_reason`.)

## 4. Where this lives

- New module: `plexadm/stash_backfill_tags.py` — one module per stash subcommand, matching the existing `stash_reconcile.py` / `stash_sync_tags.py` pattern. Public entry points: `backfill_tags(args) -> int` and `apply_review(args) -> int`. Internals: `classify_scene`, `_stash_composition_tags(scene)`, `_plex_composition_tags(video)`, `_write_review(path, entries)`, `_load_review(path)`.
- `plexadm/cli.py`:
  - Import `backfill_tags as stash_backfill_tags, apply_review as stash_apply_review` from the new module (same style as the existing `from plexadm.stash_reconcile import reconcile as stash_reconcile` line).
  - Extend `_build_stash_commands` with two new subparsers (`backfill-tags`, `apply-review`), following the existing pattern: `--limit`, `--path`, `--log-level`, `--stash-endpoint` args copied from `reconcile_parser`, plus `--review-output` (default `reference/stash_backfill_review.json`) for `backfill-tags`, and a positional `review_file` for `apply-review`. Both call `set_func(...)` so they inherit `--config`/`--dry-run` via `add_common_parser`.
  - **Important existing gap to avoid repeating:** `stash_reconcile.reconcile()` and `stash_sync_tags.sync_tags()` accept `--dry-run` (via `set_func`) but never actually check `args.dry_run` before calling `stash.update_scene` — the flag is silently ignored for those two commands today. `backfill_tags`/`apply_review` must not repeat this: since their mutations target **Plex** (via `plexadm.plex.add_items`/`remove_items`, both of which already accept a `dry_run` kwarg), just thread `dry_run=args.dry_run` through exactly like `sync_unrated`/`copy_collection` do elsewhere in `cli.py`.
- `plexadm/stash_reconcile.py`: import `_collection_to_tag` from here into the new module (or promote it to a small shared helper if that feels cleaner — a one-line `from plexadm.stash_reconcile import _collection_to_tag` is fine and keeps the diff small, but if leading-underscore cross-module imports feel wrong, move it to `plexadm/stash.py` as a public `collection_to_tag`/`tag_to_collection` pair used by both reconcile and backfill). Given the goal of not touching the existing Plex→Stash direction's design, prefer the import over a refactor unless mypy/ruff object to importing a private name across modules (in which case rename with a leading-underscore-free public alias — a 2-line change, not a redesign).
- `EXCLUDED_COMPOSITION_COLLECTIONS` (cli.py ~line 26): import, don't duplicate.

## 5. Ongoing operation

**Recommend: stay a manually-invoked audit tool, not wired into `scripts/mass_process.sh`.**

Reasoning:
- `mass_process.sh` currently contains no Stash-touching steps at all — Stash sync is already a separate, manually-run concern, and this preserves that boundary.
- The additive half (`backfill-tags` adds) is low-risk and could arguably run unattended, but it still depends on Stash tag data quality, which this session showed can regress or be internally inconsistent — an automated regular run would keep re-adding whatever a careless bulk Stash edit introduces, with no human checkpoint. Because `mass_process.sh` is unattended and its output isn't reviewed line-by-line each run, silently accumulating a growing correction backlog there is worse than running the backfill deliberately.
- The removal half is explicitly designed to require a human step (`apply-review`) — that's incompatible with unattended automation by construction.
- Recommend instead: document it in `AGENTS.md`/README as a periodic manual audit (e.g. "run monthly or after a Stash bulk-tagging pass"), run standalone (`plexadm stash backfill-tags`), with its own log, and leave `mass_process.sh` untouched. If in the future the additive-only, no-conflict-groups Phase 2 (full `01: Category:` namespace) is built and proves reliable over several manual runs, promoting *only that additive path* into `mass_process.sh` could be reconsidered then — but not as part of this plan.

## 6. Testing

Follow `tests/test_stash_reconcile.py`'s style: pure-function unit tests with no live server access, plus `SimpleNamespace`-mocked Plex objects and `MagicMock`/`patch.object` for `StashClient._gql`.

New file `tests/test_stash_backfill_tags.py`:
- `TestClassifyScene`: pure unit tests against `classify_scene(stash_tags, plex_tags)` — no mocking needed since it's a pure function of two `set[str]`. Cover:
  - empty Stash signal → `None`.
  - clean single-group Stash signal, Plex missing it → `adds` populated, `remove_candidates` empty.
  - clean signal, Plex already has it, plus a contradicting Group-A tag present → `remove_candidates` populated, `adds` empty (regression test reproducing the exact Solo+Lesbian case from `lesbian_collection_corrections.json`).
  - FFM + Lesbian both in Stash, both in Plex → treated as clean, no conflict, no changes (the "don't oversimplify" case).
  - Solo + MF Only both in Stash → `ambiguous_reason` set (multiple single-female tags).
  - Solo + FFM both in Stash → `ambiguous_reason` set (cross-axis).
  - Plex already fully agrees with Stash → `None` returned (no-op) — pick a convention and test it.
- `TestTagCollectionMapping`: round-trip tests for `_collection_to_tag`/`_tag_to_collection` against the real `COMPOSITION_COLLECTIONS` set.
- `TestReviewFileIO`: `_write_review`/`_load_review` round-trip using `tmp_path` (pytest fixture) — no network needed.
- `TestBackfillIntegration` (optional, higher-value): construct 2-3 `SimpleNamespace` fake Plex videos (mirroring `_mock_video` helper in `test_stash_reconcile.py`) plus a fake `stash_index` dict and a `StashClient` with `_gql` patched, then call `backfill_tags` end-to-end with a fake `PlexContext`/`ctx.section.collections()`/`add_items` — likely requires patching `plexadm.stash_backfill_tags.PlexContext` similarly to how `StashClient` is patched elsewhere. If wiring a full fake `PlexContext` is too heavy, keep this test focused on the classify/mapping layer (which carries all the actual logic) and cover the CLI plumbing with a thinner smoke test that just checks `add_items(collection, matches, dry_run=...)` is called with the expected `matches` for a couple of scenes, using `unittest.mock.MagicMock` collections.

Run `make lintfix && make lint && make test` before considering the implementation done, per AGENTS.md.

### Critical files for implementation
- `plexadm/stash_backfill_tags.py` (new — core logic: `classify_scene`, scan loop, review file I/O)
- `plexadm/cli.py` (add `backfill-tags`/`apply-review` subparsers in `_build_stash_commands`, reuse `EXCLUDED_COMPOSITION_COLLECTIONS`)
- `plexadm/stash_reconcile.py` (reuse `_collection_to_tag`; pattern reference for Plex↔Stash path matching)
- `plexadm/plex.py` (`add_items`/`remove_items` with `dry_run` — reuse as-is)
- `tests/test_stash_reconcile.py` (style/mocking reference for the new test file)
- `reference/lesbian_collection_corrections.json` (schema reference for the review-file format)
