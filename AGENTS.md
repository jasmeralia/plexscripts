# Agent Instructions

This repository contains Python and shell tooling for Plex library administration.

Normal development flow:

```bash
make lintfix && make lint && make test
```

Use the unified `plexadm` CLI for new Plex automation. Keep mutation behavior consistent with the current scripts: commands apply changes immediately unless a command explicitly documents another mode.

Do not add new top-level one-off scripts when a `plexadm` subcommand or helper module can cover the behavior.

## The '99: LOCKED' collection

Any video tagged `99: LOCKED` must never have its collection memberships changed by plexadm - neither additions nor removals - regardless of which command is operating. This is enforced once, centrally, in `plexadm.plex.add_items`/`remove_items` (both silently drop locked videos from the item list before touching the Plex API, unless the target collection *is* `99: LOCKED` itself, since adding/removing the lock is how you set/unset it). Do not re-implement this check per-command; if you add a new mutating command, it gets this protection for free by going through `add_items`/`remove_items`.

## Running Scripts

Always run `scripts/mass_process.sh` in the background (e.g. `bash scripts/mass_process.sh &> /tmp/mass_process.log &`). It takes several minutes and should not block the terminal.

## Task Tracking

Tasks, bugs, and follow-ups for this repository are filed in Odoo under the project **Plex Management** (`project.project` id `6`).

## Git Workflow

- Never push commits directly to `master`. Always open a pull request from a feature/fix branch.
- Use squash merge strategy when merging pull requests.
- After merging any pull request, monitor the GitHub Actions workflow runs to confirm CI passes.
