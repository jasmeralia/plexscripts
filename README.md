# plexscripts

`plexscripts` is a collection of Plex library administration tools consolidated around the `plexadm` CLI. The tool reads Plex connection details from `~/.plexconfig.ini`, connects with `plexapi`, and performs listing, tagging, collection maintenance, studio updates, writer updates, and batch processing for one Plex library.

Most commands mutate Plex immediately. There is no global dry-run mode yet.

## Configuration

Create `~/.plexconfig.ini` with a `[default]` section:

```ini
[default]
plexHost = 192.168.1.10
plexPort = 32400
plexToken = your-token
plexSectionName = Your Library Name
plexSection = optional-section-id

[logging]
sink = file

[logging.file]
path = ~/.plexadm/audit.jsonl
max_bytes = 10485760
backup_count = 10
```

You can use another config file with `--config PATH` on Plex-backed subcommands.

Every successful, non-dry-run Plex mutation is appended as a structured audit event. Exactly one audit sink is active. The default `file` sink uses size-based rotation and works without adding a `[logging]` section to an existing config. Available sinks are `file`, `syslog`, `journal`, and `opensearch`:

```ini
[logging]
sink = opensearch

[logging.syslog]
address = /dev/log
facility = user

[logging.journal]
identifier = plexadm

[logging.opensearch]
url = https://opensearch.example.com:9200
index = plexadm-audit
username = plexadm
password = your-password
verify_tls = true
```

For remote syslog, set `address = host:port`; Docker containers generally do not have `/dev/log`. The journal sink is primarily for bare-metal runs and may need the host's `/run/systemd/journal` mounted in a container. It also requires the optional dependency `pip install systemd-python`, which is intentionally not installed by default. Journal, syslog, and OpenSearch retention are managed by those systems; only the file sink handles its own rotation and retention.

Every audit event carries a `level` (`INFO`, `WARNING`, or `ERROR`), which is mapped to the matching native severity on the syslog and journal sinks (e.g. an `ERROR` event reaches syslog at the `err` priority, not `info`). Plex mutations are logged at `INFO`. In addition to mutations, plexadm logs two non-mutation event types to the same sink: any uncaught exception during a command is logged at `ERROR` (`action = "error"`), and a `Ctrl-C` interrupt is logged at `WARNING` (`action = "interrupted"`) — both so a crashed or aborted run leaves a trace instead of only a stderr message.

## Install

Install local development dependencies into `.venv/`:

```bash
make install
```

Run the CLI from the repository:

```bash
./bin/plexadm --help
```

Install the command, shell helpers, and reference data under `/usr/local`:

```bash
sudo make install-system
```

That installs:

- `/usr/local/bin/plexadm`
- `/usr/local/bin/plexadm-scripts/*.sh`
- `/usr/local/share/plexadm/reference`

## Docker

Build and run the default mass process:

```bash
docker compose up --build
```

The compose file mounts:

- `~/.plexconfig.ini:/root/.plexconfig.ini:ro`
- `/mnt/myzmirror/plexscripts/audit:/root/.plexadm:rw`
- `./reference:/app/reference:rw`

The audit mount preserves the default file sink's JSONL files when a container is removed. Adjust the host path to suit the deployment.

Override the default command with a shell:

```bash
docker compose run --rm plexadm bash
```

Run one command directly:

```bash
docker compose run --rm plexadm plexadm list collections
docker compose run --rm plexadm bash scripts/set_tags_based_on_title.sh
```

`restart` is set to `"no"`.

## Development

Normal validation flow:

```bash
make lintfix && make lint && make test
```

Targets:

- `make install`: create `.venv/` and install `requirements-dev.txt`
- `make lintfix`: run `ruff format` and `ruff check --fix`
- `make lint`: run ruff, mypy, shell syntax checks, shellcheck if installed, and hadolint. If hadolint is not installed, it runs via Docker.
- `make test`: run pytest with coverage and write `coverage.xml` for Codecov
- `make install-system`: install command and scripts to `/usr/local`

The GitHub Actions Docker workflow builds on pull requests and pushes to GHCR on `main`, version tags, and manual dispatch.

## Command Overview

Top-level command groups:

```bash
plexadm list ...
plexadm collection ...
plexadm studio ...
plexadm writers ...
plexadm smart-collections ...
plexadm tools ...
plexadm top ...
```

All Plex-backed subcommands support:

```bash
--config PATH
```

## Listing Commands

### Videos

List all videos:

```bash
plexadm list videos
```

Filter videos by title text, prefix, or regex:

```bash
plexadm list videos --title "pattern"
plexadm list videos --startswith "Alice"
plexadm list videos --regex "Scene #[0-9]+"
```

Use Plex search by title:

```bash
plexadm list videos --search-title "pattern"
```

List videos by collection, studio, writer, or missing studio:

```bash
plexadm list videos --collection "00C: Unrated"
plexadm list videos --studio "Studio Name"
plexadm list videos --writer "Writer Name"
plexadm list videos --no-studio
```

Find titles that do not contain the expected ` - ` separator:

```bash
plexadm list videos --no-title-spaces
```

Force reload while listing all videos:

```bash
plexadm list videos --reload
```

### Collections

List collections with item counts:

```bash
plexadm list collections
```

Filter collection titles:

```bash
plexadm list collections "01: Category:"
plexadm list collections "03: Star:"
```

### Studios

List studios with counts:

```bash
plexadm list studios
```

Filter studios:

```bash
plexadm list studios "Tushy"
```

### Writers

List writers with counts across the library:

```bash
plexadm list writers
```

List writers appearing in a collection:

```bash
plexadm list writers --collection "01: Category: Solo"
```

List writers appearing under a studio:

```bash
plexadm list studio-writers "Studio Name"
```

### Special Lists

Special list kinds:

- `uncategorized`
- `uncollected`
- `merged`
- `potential-indie`
- `multi-f-without-category`
- `no-composition`
- `no-hair`

Examples:

```bash
plexadm list special uncategorized
plexadm list special no-hair
plexadm list special uncollected
```

### Renames

List videos whose filename does not match their Plex title:

```bash
plexadm list renames
plexadm list renames "TUSHY"
```

Output shell `mv` commands instead of a human-readable diff:

```bash
plexadm list renames --script
plexadm list renames --script "TUSHY"
```

Override the base directory prefix stripped from file paths (default: `/data/NSFW Scenes/`):

```bash
plexadm list renames --base-dir "/other/path/"
```

Message, Post, PPV, and titles containing `?` are excluded automatically.

## Collection Commands

These commands add or remove collection membership immediately.

### Add By Title Scan

Scan every title locally and add matching videos to a collection:

```bash
plexadm collection add-title "01: Category: Anal" "Anal"
```

Match title prefix instead of substring:

```bash
plexadm collection add-title "02: Independent Content" "Alice" --startswith
```

Skip scene-style titles:

```bash
plexadm collection add-title "02: Independent Content" "Alice" --skip-scenes
```

### Add By Plex Search

Use Plex search filters to add title matches not already in the collection:

```bash
plexadm collection add-search "01: Category: Anal" "Anal"
```

This is what `scripts/set_tags_based_on_title.sh` uses.

### Add By Writer

Scan titles for a writer pattern, confirm the Plex writer exactly matches, then add to a collection:

```bash
plexadm collection add-writer "01: Composition: Solo" "Writer Name"
```

Add all videos matching any writer in a file:

```bash
plexadm collection add-writers "01: Composition: Solo" reference/writers_solo.txt
```

Writer files are newline-delimited. Pass `--single-writer-only` to skip videos with more than one
credited writer - use this for Solo, so a listed performer co-starring in someone else's scene
doesn't get that scene tagged Solo too:

```bash
plexadm collection add-writers --single-writer-only "01: Composition: Solo" reference/writers_solo.txt
```

### Copy Between Collections

Copy membership from one collection to another:

```bash
plexadm collection copy "01: Category: Deepthroat" "01: Category: Blowjob"
```

Only videos not already in the target collection are added.

### Copy Studio To Collection

Add all videos from a studio to a collection:

```bash
plexadm collection copy-studio "Tushy" "01: Category: Anal"
```

### Remove By Title

Remove matching videos from a collection:

```bash
plexadm collection remove-title "01: Category: Example" "pattern"
```

### Add Short Videos

Add videos shorter than 90 seconds by default:

```bash
plexadm collection add-short "01: Category: Short Videos"
```

Set a different duration threshold in milliseconds:

```bash
plexadm collection add-short "01: Category: Short Videos" --max-duration-ms 120000
```

### Add Vertical Videos

Add videos where media height is greater than width:

```bash
plexadm collection add-vertical "01: Category: Vertical Video"
```

### Sync Unrated Collection

Add unrated videos and remove rated videos:

```bash
plexadm collection sync-unrated "00C: Unrated"
```

The default collection is `00C: Unrated`:

```bash
plexadm collection sync-unrated
```

### Sync No-Studio Collection

Add videos with empty studio and remove videos that now have a studio:

```bash
plexadm collection sync-no-studio "00A: NO STUDIO"
```

The default collection is `00A: NO STUDIO`:

```bash
plexadm collection sync-no-studio
```

### Add PPV Collection

Add videos whose filename matches `*- PPV *`. Plex has no native filter for filename/file path, so
the match happens in Python against each media part's filename rather than as a Plex search
filter. Add-only: a filename no longer matching the pattern (e.g. after a manual rename) doesn't
mean the video stopped being valid PPV content, so existing members are never removed:

```bash
plexadm collection add-ppv "01: Category: PPV"
```

The default collection is `01: Category: PPV`:

```bash
plexadm collection add-ppv
```

### Lock Titles

Lock the title and sort title fields for every item in a collection to their current values, so
agent refresh/matching can't silently overwrite a manually-picked title (e.g. merged-duplicate
items whose title was chosen by hand from among several release names):

```bash
plexadm collection lock-titles "00A: DUPES"
```

### Rename Categories (one-time taxonomy migration)

Renames existing `01: Category:` collections into the emerging Activity/Composition/Cumshot/
Prop/Theme/Attributes taxonomy, per the hand-classified table in
`plexadm.stash_backfill_tags._EXISTING_CATEGORY_RENAMES` (the same table
`plexadm stash unmapped-tags`'s rename-suggestions section is built from). Only renames
collections that actually exist; anything left unclassified (format tags, a likely studio name,
etc.) is untouched.

Composition collections (Solo, MMF, FFM, Lesbian, Orgy, ...) are skipped by default -
`plexadm stash backfill-tags` matches these against Stash tags by exact name, so renaming them
here without also renaming the matching Stash tags would silently break that matching:

```bash
plexadm collection rename-categories --dry-run
plexadm collection rename-categories
```

Pass `--include-composition` once the corresponding Stash tags have a matching rename in place.
`plexadm stash rename-tags` renames the Stash side (`Category: Solo` → `Composition: Solo`, etc.)
via GraphQL - run it, then update `GROUP_SINGLE_FEMALE`/`GROUP_MULTI_FEMALE_HEADCOUNT`/
`GROUP_MULTI_FEMALE_ACTIVITY` in `stash_backfill_tags.py` to the new names in the same change,
before passing `--include-composition` here:

```bash
plexadm stash rename-tags --dry-run
plexadm stash rename-tags
```

**Status: complete.** All `01: Category:` collections have been migrated except the 4 left
deliberately unclassified (Beautiful Agony, Non-Sexual, Short Videos, Vertical Video) and PPV.
The commands above remain as the documented procedure in case a newly-added collection ever
needs the same treatment.

**This is a one-time migration, not part of `mass_process.sh`.** `scripts/rename_categories.sh`
wraps it with logging (defaults to a dry-run preview; pass `--apply` to actually rename). Every
other script that references a renamed collection by its old name
(`set_tags_based_on_title.sh`, `copy_collections.sh`, `set_tags_based_on_writers.sh`,
`mass_process.sh`) was updated to the new names in the same change that added this command - run
the rename before the next `mass_process.sh` run, or those will fail to find their target
collections.

### Sync Cumshot Absent Review Collection

Add every sexual, non-female-only video with no Cumshot collection (Facial, Bukkake, Cum In
Mouth, ...) to a review collection, and remove anything that no longer matches. "Non-female-only"
excludes Solo/Lesbian/FF Only/Female Only - no male performer present, so no cumshot to have -
and Non-Sexual content is excluded too. Checks both the pre- and post-`rename-categories` name
for every Cumshot collection, so it works whether or not that migration has run yet:

```bash
plexadm collection sync-cumshot-absent "00D: Review: Cumshot Absent"
```

The default collection is `00D: Review: Cumshot Absent`:

```bash
plexadm collection sync-cumshot-absent
```

## Studio Commands

These commands update Plex studio fields immediately.

### Set Studio By Title Pattern

Set a studio on title matches that do not already have a studio:

```bash
plexadm studio set-title "Studio Name" "pattern"
```

Require the pattern to match an exact Plex writer too:

```bash
plexadm studio set-title "Independent Content" "Writer Name" --require-writer
```

Skip scene-style titles:

```bash
plexadm studio set-title "Independent Content" "Writer Name" --skip-scenes
```

### Set Independent Studio

Shortcut for independent content. It requires exact writer match and skips scenes:

```bash
plexadm studio set-independent "Writer Name"
```

### Bulk Set Independent

Use a newline-delimited writer file:

```bash
plexadm studio bulk-independent reference/writers_indie.txt
```

### Rename Studio

Rename studio values across matching videos:

```bash
plexadm studio rename "Old Studio" "New Studio"
```

## Writer Commands

### Set Writers From Titles

Parse writer names from the title prefix before the first ` - ` and add missing Plex writers:

```bash
plexadm writers set-from-titles
```

Example title format:

```text
Alice, Bob - Example Title
```

### Set Writers And Sync Smart Collections

Set missing writers from titles, then create missing smart collections for studios and writers:

```bash
plexadm writers set-and-sync
```

This is the first step in `scripts/mass_process.sh`.

## Smart Collection Commands

### Sync Smart Collections

Create missing smart collections for all discovered studios and writers:

```bash
plexadm smart-collections sync
```

Studio smart collections are named:

```text
02: Studio: Studio Name
```

Writer smart collections are named:

```text
03: Star: Writer Name
```

`Independent Content` is named:

```text
02: Independent Content
```

### Rename Collections

Rename collections using a Python regular expression replacement:

```bash
plexadm smart-collections rename "^Old Prefix: " "New Prefix: "
```

## Top Reports

Show top category collections:

```bash
plexadm top categories
plexadm top categories --limit 25
```

Show top studios:

```bash
plexadm top studios
```

Show top writers or scenes missing studios:

```bash
plexadm top writers-without-studios
plexadm top scenes-without-studios
```

Show unrated writer or scene counts:

```bash
plexadm top unrated-writers
plexadm top unrated-scenes
```

Override the collection used by top reports where applicable:

```bash
plexadm top unrated-writers --collection "00C: Unrated"
```

## Tools

Find which Plex item references a file path:

```bash
plexadm tools find-missing-file "/path/to/file.mp4"
```

Generate a download scene name:

```bash
plexadm tools fix-dl-scene-name "original.mp4"
plexadm tools fix-dl-scene-name "original.mp4" --prefix "Alice"
```

Generate an UltraFilms-style filename:

```bash
plexadm tools fix-ultrafilms-name "some_file_name.mp4"
```

Print OFDL name mappings from JSON:

```bash
plexadm tools ofdl-gen-names --map-file reference/indie_usernames_to_map.json
```

Run rsync:

```bash
plexadm tools ofdl-rsync SOURCE DESTINATION
```

Remove `_23fps`, `_24fps`, `_25fps`, `_30fps`, `_50fps`, or `_60fps` style title suffixes:

```bash
plexadm tools remove-fps-title "Video_60fps.mp4"
```

Upload local `*.mp4` files to a remote host:

```bash
plexadm tools upload-vids
plexadm tools upload-vids --remote-host truenas --upload-path "/mnt/myzmirror/plexdata/NSFW Scenes"
```

## Shell Scripts

The `scripts/` directory contains batch wrappers around `plexadm`.

Important scripts:

- `scripts/mass_process.sh`: full batch process
- `scripts/set_tags_based_on_title.sh`: title-search category tagging
- `scripts/set_tags_based_on_writers.sh`: writer-file tagging and independent content updates
- `scripts/copy_collections.sh`: collection and studio propagation rules
- `scripts/set_unrated.sh`: unrated collection sync with log output
- `scripts/set_ppv.sh`: PPV filename-pattern collection sync with log output
- `scripts/rename_categories.sh`: one-time taxonomy rename migration - NOT part of mass_process.sh
- `scripts/top_*.sh`: convenience reports

Run the full batch:

```bash
bash scripts/mass_process.sh
```

## Reference Data

`reference/` is for local runtime data, writer lists, logs, and notes. Files such as `reference/*.txt`, `reference/*.log`, `reference/*.md`, and `reference/*.json` are ignored by git.

`reference/legacy-python/` contains the archived pre-refactor Python scripts for comparison.

## Naming Scheme

See [docs/naming-scheme.md](./docs/naming-scheme.md).

## Using a .env file

Rather than embedding credentials in your `docker-compose.yml`, you can store them in a `.env` file and bind-mount it into the container:

```bash
cp .env.example .env
# edit .env with your values
```

```yaml
services:
  app:
    image: ghcr.io/jasmeralia/plexscripts:latest
    volumes:
      - /path/to/your/.env:/app/.env:ro
```

The app loads `/app/.env` automatically on startup. Any value in `.env` can still be overridden by an explicit `environment:` entry in your Compose file.
