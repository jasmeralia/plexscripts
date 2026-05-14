# Agent Instructions

This repository contains Python and shell tooling for Plex library administration.

Normal development flow:

```bash
make lintfix && make lint && make test
```

Use the unified `plexadm` CLI for new Plex automation. Keep mutation behavior consistent with the current scripts: commands apply changes immediately unless a command explicitly documents another mode.

Do not add new top-level one-off scripts when a `plexadm` subcommand or helper module can cover the behavior.

## Git Workflow

- Never push commits directly to `master`. Always open a pull request from a feature/fix branch.
- Use squash merge strategy when merging pull requests.
