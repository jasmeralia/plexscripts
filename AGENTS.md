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

`plexadm.plex.LOCK_BYPASS_COLLECTIONS` lists collections exempt from this guard: `01: Category: Short Videos`, `01: Category: Vertical Video`, `00C: Unrated`, `00A: NO STUDIO`, `01: Category: PPV`. These describe a fact about the file itself (duration, orientation, rating, studio presence, filename) rather than a judgment call about the content, so locked videos still get tagged into them like any other video. Only add a collection to this set if it's similarly a format/technical property, not a content descriptor - anything content-related stays subject to the full lock.

## Persistent audit logging

Every real, non-dry-run Plex mutation must go through the centralized helpers in `plexadm.plex`, which write a structured event only after the Plex API call succeeds. Do not call Plex mutation methods directly from commands; add or extend a `plexadm.plex` helper instead. This includes studio and writer edits, collection renames, and smart-collection creation: centralizing those formerly direct `cli.py` call sites also closes their old gap where they bypassed the `99: LOCKED` guard entirely. Audit logging uses one separately configured, non-propagating logger and must not be connected to the root logger or the Stash debug logging.

Every `AuditEvent` carries a `level` (`INFO`/`WARNING`/`ERROR`), which is dispatched through the matching Python `logging` level so syslog/journal severity reflects it natively. Mutations are `INFO`. `plexadm.cli.main` also logs uncaught command exceptions (`audit.log_error`, `ERROR`) and `Ctrl-C` interrupts (`WARNING`) to the same sink, so a crashed or aborted run is traceable, not just a mutation history.

## Inventory snapshots (`plexadm.inventory`)

Audit logging only ever records what plexadm itself did - it cannot show drift from any other source (a stray Plex Web edit, a metadata agent, anything outside this repo). `plexadm inventory snapshot` closes that gap by recording one document per video with its full current collection membership to a dedicated OpenSearch index (`[inventory]` config section, independent of the `[logging]` sink choice). `plexadm inventory diff` compares two snapshots and, when an OpenSearch audit sink is configured, cross-checks each changed video's audit trail in that window - a change with no matching event is flagged `UNATTRIBUTED`. This pairing (periodic ground-truth snapshot + existing audit trail) is what should be reached for first when investigating unexplained collection membership, rather than reconstructing it from Plex server logs after the fact.

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
