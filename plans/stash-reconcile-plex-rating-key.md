# Design: persist Plex rating keys on matched Stash scenes

## Goal and scope

Odoo task 575 asks `plexadm stash reconcile` to record the matched Plex video's `ratingKey` in a supported, queryable Stash field. Reconcile must update a changed key, handle a Plex item that matches multiple Stash scenes, preserve unrelated Stash metadata, and document the behavior. This is a design for that feature; this PR does not change runtime behavior.

Use the Stash scene custom field `plex_rating_key`, storing the decimal Plex rating key as a string. The key belongs to the configured Plex server and is a lookup hint, not a global media identity. Matching remains based on current file paths; a stored key must never be used to decide that a scene matches a Plex item. A lookup by key may return more than one scene until those scenes are merged.

Global removal of keys from unmatched scenes, a new cross-host locking service, and a persistent merge-recovery journal are outside task 575. The existing risk from overlapping plexadm Stash scene writes is tracked separately in Odoo task 581. Existing full reconciles continue to run Stash Scan and Clean. Partial reconciles continue to skip Clean. These operational behaviors must not change for this feature.

**Operating condition:** the Plex library stays unchanged throughout a reconcile run. In this deployment, the operator controls Plex content changes and does not add, remove, move, merge, or edit Plex items until reconcile finishes. At invocation, before Scan/Clean or either inventory read, print: “Keep the Plex library unchanged until stash reconcile completes; do not add, remove, move, merge, or edit Plex items during this run.” This is an explicit operator responsibility, not a snapshot guarantee enforced by the APIs. If the condition is violated, stop and rerun after the library is stable. The Plex inventory count and unique-key checks below detect observable retrieval errors; they do not prove consistency under concurrent Plex changes.

## Stash capability and merge behavior

The deployed Stash v0.31.1 exposes `Scene.custom_fields`, `SceneUpdateInput.custom_fields.partial`, `SceneMergeInput.values.custom_fields.partial`, and a custom-field scene filter. Check these read-only schema capabilities before Scan/Clean; fail clearly if they are unavailable. A partial custom-field update changes only named keys and preserves unrelated fields.

Stash v0.31.1 executes `sceneMerge` and the supplied `values.custom_fields` update in one repository transaction. Source deletion and the destination custom-field update therefore commit or roll back together at the database level. Stash does not automatically union custom fields from source scenes during a merge, so plexadm must calculate that union and supply it in the merge input. Confirm both behaviors in integration coverage against the supported Stash version before rollout.

## Reconcile flow

1. Keep `StashClient.all_scenes()` and its existing path-to-single-scene return contract unchanged for other callers. Add a reconcile-specific paged scene query that includes current file paths, `custom_fields`, performers, and tags, with `sort: "id"` and `direction: ASC` (confirmed supported by the live Stash API). Build a path-to-scenes multimap and an ID-to-scene map, retaining every scene even when paths collide. Capture `findScenes.count` from the first page and require the same count on every page, strictly increasing scene IDs with no repeats, and a final number of collected IDs equal to that count. An early empty or short page, changed count, duplicate/out-of-order ID, or final count mismatch aborts before any per-video metadata update, key write, or merge. A partial or unstable index must never drive a merge decision.

2. Before any per-video writes, build a Plex path-to-items multimap for the whole library, including on a run scoped by `--limit`, `--path`, or `--added-in-last-days`. Retain every distinct Plex item sharing a path; never overwrite one with another in a single-value dictionary. Only selected videos receive updates in a partial run; the complete read-only multimap detects a scene matched by more than one Plex item. Reload partial Plex objects as needed to obtain their `locations` and `ratingKey`. Verify that the number of returned library items equals the section's `totalSize` and that usable rating keys are unique. Use a valid `ratingKey` as each item's stable identity. If an item has no usable key, warn and skip that item entirely, including its metadata, key, play-history, and merge writes; retain its paths only to block writes to any scene it might match. Do not use an item URI or inventory position as a fallback identity. If the full map cannot be verified, abort before any per-video metadata update, key write, or merge. Report the additional full-library read cost in progress output for partial runs.

3. Match Plex paths to Stash file paths. Deduplicate a scene reached by several paths of the same Plex item. If a Stash scene is matched by distinct Plex items or by a skipped missing-key item's path, report the uncertain ownership and skip all metadata, key, and play-history writes to that scene, as well as any merge involving it. Do not choose a key from title, writer, or the value already stored in Stash.

4. Normalize a valid Plex `ratingKey` to a nonempty decimal string. For a single matched, non-ambiguous scene, include `custom_fields: {partial: {plex_rating_key: key}}` in the normal `sceneUpdate`, or issue a field-only update when that Plex item has no usable descriptive metadata. When a no-metadata item matches several non-ambiguous scenes, keep the existing no-merge rule and make a field-only update to each scene. If the stored key is current, omit the custom-field write while allowing any ordinary metadata update to proceed. A later valid path match replaces a changed key.

5. When one Plex item matches several Stash scenes and the existing reconcile rules permit a merge, collect their non-plexadm custom fields before mutation. If the same field name has conflicting values, leave the scenes separate, report the conflict, and follow the separate-scene rule below. Otherwise, pass the union of non-owned fields and the target `plex_rating_key` in `sceneMerge.values.custom_fields.partial`, together with the existing reconcile metadata update. Read the destination back and verify the key and non-owned field union. Do not delete an unexpected field during readback: it may be a concurrent Stash edit. Report and stop on a mismatch.

When a merge is withheld for uncertain ownership, conflicting custom fields, or missing metadata, process each unblocked scene independently. Build its ordinary metadata update from that scene's own performers and tags plus the Plex item's values; never union performer or tag IDs from scenes that remain separate. With usable Plex metadata, apply that scene's update and sync the item's play history to that scene. Include the valid key through a partial custom-field update. Without usable metadata, keep the existing no-data behavior: write only the key and do not sync play history. Scenes with uncertain ownership receive no writes.

6. A lost or timed-out merge response has an uncertain result. Read the destination and recorded source IDs before doing anything else. If the sources are gone and the destination has the expected files and custom fields, treat the transactional merge as completed. If all sources remain, report that the merge did not complete and let the next reconcile replan it. If the observed state fits neither case, stop with a scene-ID report for manual investigation. Do not retry a merge blindly or run new key mutations after an unresolved result.

`plex_rating_key` is owned by plexadm. This feature does not remove it from a Stash scene that has no current Plex path match. Such a value can become stale when Plex removes a still-existing file from its library; callers should resolve the key against Plex and verify the file path when correctness matters. Global orphan-key cleanup can be considered separately after the basic link is working.

## Lookup and reporting

A Stash-to-Plex lookup reads `Scene.custom_fields.plex_rating_key`, then resolves that key on the configured Plex server. A Plex-to-Stash lookup uses the deployed Stash custom-field scene filter with the decimal key passed as a **string**:

```graphql
query ScenesByPlexRatingKey($key: Any!, $page: Int!) {
  findScenes(
    scene_filter: {
      custom_fields: [{field: "plex_rating_key", value: [$key], modifier: EQUALS}]
    }
    filter: {page: $page, per_page: 200}
  ) {
    count
    scenes { id custom_fields }
  }
}
```

Page through all results; a key may match multiple scenes. Warn when Plex no longer has the referenced item. A live read/write/lookup spike against the configured Stash instance on 2026-09-28 stored a synthetic decimal string in this field, found exactly that scene with `EQUALS`, found no scenes for a different string, then removed the field and confirmed zero scenes retained it. The numeric-value probe also matched the string field, but callers should use the documented string representation.

Report counts for keys added, changed, already current, and skipped for missing keys, ambiguous matches, or custom-field conflicts. Preserve the existing reconcile scope CSV and scene update/merge counts. Log scene IDs and rating keys for investigation without adding media titles or paths to committed reports.

## Implementation and validation

- Add the reconcile-specific Stash query and partial custom-field input support in `plexadm.stash`. Keep other Stash callers' query contract intact.
- Add the read-only match plan, startup warning, and key writes within `plexadm.stash_reconcile`. Retain current Scan/Clean ordering and the existing `scripts/mass_process.sh` reconcile stage; no new environment variable or stage is required.
- Verify that full and partial reconciles display the warning before Scan/Clean or inventory reads.
- Cover unchanged, missing, and changed rating keys; one Plex item matching several paths or scenes; two Plex items sharing a path or matching one scene; no-metadata items; a missing-key item skipped with a warning and no writes, including when its path also matches a valid-key item; conflicting and compatible source custom fields; a lost merge response; partial-run ambiguity; and incomplete or unstable Stash pagination (changed count, repeated/out-of-order ID, early short page) aborting before all per-video mutations. For withheld merges, cover a blocked scene left untouched while an unblocked scene gets its own update, and separate scenes retaining their own performers/tags while receiving the appropriate metadata, key, and play history. An integration test on Stash v0.31.1 must verify that a stored string key is returned by the custom-field `EQUALS` filter, that custom fields supplied with `sceneMerge` survive, and that source deletion and destination field update share a transaction.
- Update CLI help and the README's Stash Reconcile section with the new field, lookup method, stable-library operating condition, partial-run read cost, and the absence of global stale-key cleanup.
