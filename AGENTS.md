# Agent Instructions

This repository contains Python and shell tooling for Plex library administration.

Normal development flow:

```bash
make lintfix && make lint && make test
```

Use the unified `plexadm` CLI for new Plex automation. Keep mutation behavior consistent with the current scripts: commands apply changes immediately unless a command explicitly documents another mode.

Do not add new top-level one-off scripts when a `plexadm` subcommand or helper module can cover the behavior.

## The '99: LOCKED' collection

Any video tagged `99: LOCKED` must never have its collection memberships changed by plexadm - neither additions nor removals - regardless of which command is operating. This is enforced once, centrally, in `plexadm.plex.add_items`/`remove_items`/`create_collection` (all three silently drop locked videos from the item list before touching the Plex API, unless the target collection *is* `99: LOCKED` itself, since adding/removing the lock is how you set/unset it). Do not re-implement this check per-command; if you add a new mutating command, it gets this protection for free by going through `add_items`/`remove_items`.

`plexadm.plex.lock_title_and_sort_title` is a deliberate exception to this guard: it locks the `title`/`titleSort` fields to whatever value they already have, so it preserves existing metadata rather than altering it - the thing the guard exists to prevent doesn't apply. `rename_title` (which does change the title's value) still respects the guard as normal.

`plexadm.plex.LOCK_BYPASS_COLLECTIONS` lists collections exempt from this guard: `01: Category: Short Videos`, `01: Category: Vertical Video`, `00C: Unrated`, `00A: NO STUDIO`, `01: Category: PPV`. These describe a fact about the file itself (duration, orientation, rating, studio presence, filename) rather than a judgment call about the content, so locked videos still get tagged into them like any other video. Only add a collection to this set if it's similarly a format/technical property, not a content descriptor - anything content-related stays subject to the full lock.

## Persistent audit logging

Every real, non-dry-run Plex mutation must go through the centralized helpers in `plexadm.plex`, which write a structured event only after the Plex API call succeeds. Do not call Plex mutation methods directly from commands; add or extend a `plexadm.plex` helper instead. This includes studio and writer edits, collection renames, and smart-collection creation: centralizing those formerly direct `cli.py` call sites also closes their old gap where they bypassed the `99: LOCKED` guard entirely. Audit logging uses one separately configured, non-propagating logger and must not be connected to the root logger or the Stash debug logging.

Every `AuditEvent` carries a `level` (`INFO`/`WARNING`/`ERROR`), which is dispatched through the matching Python `logging` level so syslog/journal severity reflects it natively. Mutations are `INFO`. `plexadm.cli.main` also logs uncaught command exceptions (`audit.log_error`, `ERROR`) and `Ctrl-C` interrupts (`WARNING`) to the same sink, so a crashed or aborted run is traceable, not just a mutation history.

### Quiet OpenSearch client logging

The `stash_*.py` command functions (`reconcile`, `backfill-tags`, `unmapped-tags`, `rename-tags`, `apply-review`, `sync-tags`) share one `plexadm.logging_setup.configure_command_logging` helper instead of each repeating `logging.basicConfig` directly. Under `--log-level INFO` with an `opensearch` audit sink, opensearch-py's own client logger (`opensearch`, plus `urllib3` underneath it) otherwise logs a `POST .../_doc [status:201 request:...s]` line for every single audit event - noise that drowns out plexadm's own progress messages. This is suppressed by default (`LoggingConfig.quiet_opensearch_log`); override with the `PLEXADM_QUIET_OPENSEARCH_LOG` environment variable or `[logging] quiet_opensearch_log` in the config file, env var takes precedence when both are set. Same `resolve_bool_setting` precedence helper `--dry-run`/`PLEXADM_DRY_RUN` uses.

## Stash taxonomy backfill

`plexadm stash backfill-tags` applies exactly what `plexadm stash unmapped-tags` resolves in its `## Merge` section, plus accepted bare-`## Add` suggestions, in the same run as the existing Composition/Hair pass. The full-taxonomy scope only adds memberships, creates new collections as needed, and is safe to re-run: videos already in a target collection are skipped. Composition/Hair retain their existing review-file behavior for potential removals.

## Inventory snapshots (`plexadm.inventory`)

Audit logging only ever records what plexadm itself did - it cannot show drift from any other source (a stray Plex Web edit, a metadata agent, anything outside this repo). `plexadm inventory snapshot` closes that gap by recording one document per video - rating key, both title fields (`title`/`title_sort`), date added, studio, writers, directors, its full current collection membership, and its file path(s) - to a dedicated OpenSearch index (`[inventory]` config section, independent of the `[logging]` sink choice). `plexadm inventory diff` compares two snapshots and, when an OpenSearch audit sink is configured, cross-checks each changed video's audit trail in that window - a change with no matching event is flagged `UNATTRIBUTED` (diffing currently only looks at collection membership, not the other tracked fields). This pairing (periodic ground-truth snapshot + existing audit trail) is what should be reached for first when investigating unexplained collection membership, rather than reconstructing it from Plex server logs after the fact.

`plexadm inventory snapshot` additionally correlates each video's file path(s) against Stash's own path index (same by-path matching `plexadm stash reconcile` uses) and records the matching Stash scene id(s), by default - it pages the entire Stash library over GraphQL, so this is ~15-20% slower than skipping it; pass `--no-stash-ids` to skip. If the config file has no `[stash]` endpoint configured, Stash correlation is always skipped regardless of flags - `--stash-endpoint` can only override which endpoint to use when one is already configured, it can't conjure Stash correlation into existence when the config file has none at all; passing it in that situation prints a warning and is otherwise ignored.

## Running Scripts

Always run `scripts/mass_process.sh` in the background (e.g. `bash scripts/mass_process.sh &> /tmp/mass_process.log &`). It takes several minutes and should not block the terminal.

## Task Tracking

Tasks, bugs, and follow-ups for this repository are filed in Odoo under the project **Plex Management** (`project.project` id `6`). This is the default project for anything filed from this repo — use it unless explicitly told otherwise for a specific task.

## No indie performer/writer names in git

Never commit a real indie/independent performer or writer name anywhere in this repo - source code, docstrings, help/epilog text, test fixtures, commit messages, docs, plan files, or any other tracked file. Use a generic placeholder instead (e.g. "WRITER NAME", "Example Writer", "00A: Star (PPVs)").

Industry (studio-affiliated) performer names are fine to use as real examples - this rule is specifically about indie/self-published creators, who are more personally identifying. Plex's `Independent Content` studio tag (`INDEPENDENT_STUDIO` in `plexadm/cli.py`) is *not* a reliable signal for this by itself - some writers tagged that way are actually industry performers whose content is just sold direct-download rather than through a mainstream studio site. Judge by whether the person is a genuinely self-published/amateur creator, not by which Plex studio field a video happens to carry.

## Git Workflow

- Never push commits directly to `master`. Always open a pull request from a feature/fix branch.
- Use squash merge strategy when merging pull requests.
- After merging any pull request, monitor the GitHub Actions workflow runs to confirm CI passes.
