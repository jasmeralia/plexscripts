# Plan: Persistent Audit Logging for plexadm Mutations

Odoo task #331. Scope per that task and follow-up clarification: design (not yet implement) structured, append-only logging of every real (non-dry-run) Plex mutation plexadm makes, with a pluggable sink chosen via config. Four backends in scope: local JSONL file (default, with NLog-style size-based rotation/retention), systemd journal, syslog, OpenSearch. Exactly one sink is active at a time (no fan-out). Rotation/retention for journal/syslog/OpenSearch is the user's own infrastructure to manage; only the file sink self-manages rotation/retention. Config lives in the existing `~/.plexconfig.ini` (or `$PLEXADM_CONFIG`) file as a new `[logging]` section family — no new config file, no pydantic-settings (confirmed unused anywhere in the codebase despite being a listed dependency).

## 1. Motivating gaps this closes

- stdout-only output vanished irrecoverably during a real audit run (a nested-subprocess/backgrounding redirect quirk lost one script's output twice, reproducibly) — nothing was persisted independent of the shell.
- A mis-tagged video (added to `01: Category: Lesbian` incorrectly) had no record of which run or rule caused it — unexplainable after the fact, fixed by hand.
- Six direct-mutation call sites in `cli.py` (`video.edit()` for studio, `video.addWriter()`, `collection.editTitle()`, `section.createCollection()`) bypass `plexadm.plex.add_items`/`remove_items` entirely today, so they get neither the `99: LOCKED` guard nor (currently) any audit trail. Centralizing them through new `plex.py` helpers (§4) closes both gaps in one pass, consistent with AGENTS.md's existing precedent: "This is enforced once, centrally... Do not re-implement this check per-command."

## 2. Event schema

New module `plexadm/audit.py`:

```python
@dataclass(frozen=True)
class MutationEvent:
    action: str  # "add" | "remove" | "edit_studio" | "add_writer"
    # | "rename_collection" | "create_collection"
    title: str
    rating_key: int | None = None
    collection: str | None = None
    details: dict[str, Any] = field(default_factory=dict)  # action-specific extra context

    def to_record(self) -> dict[str, Any]:
        ctx = _CURRENT_INVOCATION.get()
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "action": self.action,
            "title": self.title,
            "rating_key": self.rating_key,
            "collection": self.collection,
            "rule": ctx.rule if ctx else "unknown",
            "invocation": ctx.invocation if ctx else "",
            "details": self.details,
        }
```

This covers the task's stated minimum (timestamp, collection, ratingKey, title, action, triggering command/rule) plus `invocation` (the full sanitized argv) and `details` (a free-form dict for action-specific context, e.g. `{"old_studio": ..., "new_studio": ...}`).

**Rule/invocation capture — ambient context, not threaded through every call site.** There's no existing unified "rule name" concept (confirmed: the closest analog is the handler function bound via `set_func`/`args.func`). Rather than adding a `rule=` kwarg to every one of the ~30 call sites of `add_items`/`remove_items`, use a `contextvars.ContextVar` set once per CLI invocation:

```python
_CURRENT_INVOCATION: ContextVar[InvocationContext | None] = ContextVar("plexadm_invocation", default=None)


@dataclass(frozen=True)
class InvocationContext:
    rule: str
    invocation: str


def set_invocation_context(*, rule: str, argv: list[str] | None = None) -> None:
    _CURRENT_INVOCATION.set(InvocationContext(rule=rule, invocation=shlex.join(argv or sys.argv)))
```

`plexadm/cli.py::main()` calls this once, right after `parser.parse_args`, before dispatching:

```python
args = parser.parse_args(argv)
audit.set_invocation_context(rule=args.func.__name__, argv=sys.argv)
```

`args.func.__name__` (e.g. `set_studio_for_title_matches`, `rename_studio`, `add_matching_titles`) is stable, already unique per handler, and requires no new argparse plumbing. `sys.argv` is safe to log verbatim — the Plex token lives in `~/.plexconfig.ini`, never on the CLI.

## 3. Config surface

Extend `plexadm/config.py` with new dataclasses and a `load_logging_config()` function, parsed from the same INI file `load_config()` already reads (new sections, existing file — no new file, no new format):

```ini
[default]
plexHost = 192.168.1.25
plexPort = 32400
plexToken = ...
plexSectionName = NSFW Scenes

[logging]
sink = file                        ; file (default) | syslog | journal | opensearch

[logging.file]
path = ~/.plexadm/audit.jsonl
max_bytes = 10485760               ; 10 MiB, rotate when exceeded
backup_count = 10                  ; keep 10 rotated files (~100 MiB ceiling)

[logging.syslog]
address = /dev/log                 ; unix socket path, or "host:port" for a remote collector
facility = user

[logging.journal]
identifier = plexadm               ; SYSLOG_IDENTIFIER field

[logging.opensearch]
url = https://opensearch.example.com:9200
index = plexadm-audit
username = plexadm
password = ...
verify_tls = true
```

If `[logging]` is absent entirely, defaults to `sink = file` with the defaults above — existing `.plexconfig.ini` files (including Morgan's) keep working unmodified. `[logging.opensearch]` has no default `url`; selecting `sink = opensearch` without it is a startup-time config error (fail fast, not on first mutation).

```python
@dataclass(frozen=True)
class FileSinkConfig:
    path: Path = field(default_factory=lambda: Path.home() / ".plexadm" / "audit.jsonl")
    max_bytes: int = 10_485_760
    backup_count: int = 10


@dataclass(frozen=True)
class SyslogSinkConfig:
    address: str = "/dev/log"
    facility: str = "user"


@dataclass(frozen=True)
class JournalSinkConfig:
    identifier: str = "plexadm"


@dataclass(frozen=True)
class OpenSearchSinkConfig:
    url: str
    index: str = "plexadm-audit"
    username: str | None = None
    password: str | None = None
    verify_tls: bool = True


@dataclass(frozen=True)
class LoggingConfig:
    sink: str = "file"
    file: FileSinkConfig = field(default_factory=FileSinkConfig)
    syslog: SyslogSinkConfig = field(default_factory=SyslogSinkConfig)
    journal: JournalSinkConfig = field(default_factory=JournalSinkConfig)
    opensearch: OpenSearchSinkConfig | None = None


def load_logging_config(path: str | Path | None = None) -> LoggingConfig:
    config_path = Path(path).expanduser() if path else default_config_path()
    parser = configparser.ConfigParser()
    parser.read(config_path)  # missing file/section -> fall through to all-defaults
    sink = parser.get("logging", "sink", fallback="file")
    if sink not in {"file", "syslog", "journal", "opensearch"}:
        raise ValueError(f"Unknown [logging] sink: {sink!r}")
    opensearch_cfg = None
    if parser.has_section("logging.opensearch"):
        section = parser["logging.opensearch"]
        if "url" not in section:
            raise KeyError("[logging.opensearch] requires 'url'")
        opensearch_cfg = OpenSearchSinkConfig(
            url=section["url"],
            index=section.get("index", "plexadm-audit"),
            username=section.get("username"),
            password=section.get("password"),
            verify_tls=section.getboolean("verify_tls", fallback=True),
        )
    elif sink == "opensearch":
        raise KeyError("sink = opensearch requires a [logging.opensearch] section")
    return LoggingConfig(
        sink=sink,
        file=FileSinkConfig(
            path=Path(parser.get("logging.file", "path", fallback=str(FileSinkConfig().path))).expanduser(),
            max_bytes=parser.getint("logging.file", "max_bytes", fallback=FileSinkConfig().max_bytes),
            backup_count=parser.getint("logging.file", "backup_count", fallback=FileSinkConfig().backup_count),
        ),
        syslog=SyslogSinkConfig(
            address=parser.get("logging.syslog", "address", fallback="/dev/log"),
            facility=parser.get("logging.syslog", "facility", fallback="user"),
        ),
        journal=JournalSinkConfig(identifier=parser.get("logging.journal", "identifier", fallback="plexadm")),
        opensearch=opensearch_cfg,
    )
```

`configparser` section names support dots natively (`[logging.file]` is a perfectly ordinary section name), so no new parsing machinery is needed.

## 4. Sink implementations (`plexadm/audit.py`)

All four sinks are built as `logging.Handler` instances attached to one dedicated, non-propagating logger (`logging.getLogger("plexadm.audit")`). This deliberately does **not** touch the root logger — `stash.py`/`stash_reconcile.py`/`stash_sync_tags.py`'s existing ad-hoc `logging.basicConfig()` calls configure the root logger for unrelated debug output; keeping the audit logger separate and non-propagating avoids any interaction between the two. Messages are pre-serialized JSON strings; a passthrough formatter just returns `record.getMessage()` unchanged, so file/syslog/journal all receive the same JSON-line text.

```python
class _RawFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return record.getMessage()


def _build_handler(config: LoggingConfig) -> logging.Handler:
    if config.sink == "file":
        config.file.path.parent.mkdir(parents=True, exist_ok=True)
        handler: logging.Handler = logging.handlers.RotatingFileHandler(
            config.file.path, maxBytes=config.file.max_bytes, backupCount=config.file.backup_count, encoding="utf-8"
        )
    elif config.sink == "syslog":
        address = config.syslog.address
        target: str | tuple[str, int] = address
        if ":" in address and not address.startswith("/"):
            host, port = address.rsplit(":", 1)
            target = (host, int(port))
        try:
            handler = logging.handlers.SysLogHandler(address=target, facility=config.syslog.facility)
        except OSError as exc:
            raise RuntimeError(
                f"Could not reach syslog at {address!r}. Inside Docker, /dev/log usually doesn't exist - "
                "set [logging.syslog] address to a remote host:port instead."
            ) from exc
    elif config.sink == "journal":
        try:
            from systemd.journal import JournalHandler
        except ImportError as exc:
            raise RuntimeError(
                "sink = journal requires the optional 'systemd-python' package: pip install systemd-python"
            ) from exc
        try:
            handler = JournalHandler(SYSLOG_IDENTIFIER=config.journal.identifier)
        except OSError as exc:
            raise RuntimeError(
                "Could not reach the systemd journal socket. Inside Docker this usually needs "
                "/run/systemd/journal bind-mounted from the host - journal is best suited to bare-metal runs."
            ) from exc
    elif config.sink == "opensearch":
        if config.opensearch is None:
            raise RuntimeError("sink = opensearch requires a [logging.opensearch] section with at least 'url'.")
        handler = OpenSearchHandler(config.opensearch)
    else:
        raise ValueError(f"Unknown logging sink: {config.sink!r}")
    handler.setFormatter(_RawFormatter())
    return handler


class OpenSearchHandler(logging.Handler):
    def __init__(self, config: OpenSearchSinkConfig):
        super().__init__()
        from opensearchpy import OpenSearch  # base dependency (see §6); imported lazily to keep module import cheap

        self._client = OpenSearch(
            hosts=[config.url],
            http_auth=(config.username, config.password) if config.username else None,
            verify_certs=config.verify_tls,
        )
        self._index = config.index

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._client.index(index=self._index, body=json.loads(record.getMessage()))
        except Exception:
            self.handleError(record)
```

Handler construction happens lazily on first mutation and is cached module-globally (`configure()` resets the cache so tests can reconfigure between cases):

```python
_CONFIG: LoggingConfig | None = None
_LOGGER: logging.Logger | None = None
_FAILURE_COUNT = 0


def configure(config: LoggingConfig) -> None:
    global _CONFIG, _LOGGER
    _CONFIG = config
    _LOGGER = None


def _logger() -> logging.Logger:
    global _LOGGER
    if _LOGGER is None:
        logger = logging.getLogger("plexadm.audit")
        logger.propagate = False
        logger.setLevel(logging.INFO)
        logger.handlers.clear()
        logger.addHandler(_build_handler(_CONFIG or LoggingConfig()))
        _LOGGER = logger
    return _LOGGER


def log_mutation(event: MutationEvent) -> None:
    global _FAILURE_COUNT
    try:
        _logger().info(json.dumps(event.to_record(), sort_keys=True))
    except Exception as exc:
        _FAILURE_COUNT += 1
        print(fail(f"AUDIT LOG WRITE FAILED ({(_CONFIG or LoggingConfig()).sink}): {exc}"), file=sys.stderr)


def has_failures() -> bool:
    return _FAILURE_COUNT > 0
```

**Never silently swallow a write failure** — that's the exact failure mode that motivated this task (output vanishing with no trace). Every failed `emit` prints immediately to stderr via `console.fail`, synchronously, regardless of stdout redirection quirks, and increments a counter that `main()` checks at exit.

## 5. Wiring into `main()` and exit behavior

`plexadm/cli.py::main()`:

```python
def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    audit.configure(load_logging_config(args.config))
    audit.set_invocation_context(rule=args.func.__name__, argv=sys.argv)
    if args.command == "top" and args.source in {"scenes-without-studios", "unrated-scenes"}:
        args.scenes = True
    try:
        result = int(args.func(args) or 0)
    except KeyboardInterrupt:
        print(fail("Interrupted."))
        return 130
    except Exception as exc:
        print(fail(str(exc)))
        return 1
    if audit.has_failures():
        print(fail("One or more audit log writes failed during this run - see above."))
        return 1
    return result
```

A run where every Plex mutation succeeded but the audit sink was unreachable partway through still exits non-zero — important since `scripts/mass_process.sh` runs unattended and its own exit code is the only thing anyone checks after the fact.

## 6. Central mutation choke points (`plexadm/plex.py`)

Extend `add_items`/`remove_items` to log after a successful (non-dry-run) API call, and add four new centralized helpers for the mutation types that currently bypass this module entirely. Moving those call sites here also gives them the `99: LOCKED` guard for free — today `video.edit()`/`addWriter()` calls in `cli.py` do not check for the locked tag at all, which is an existing gap this refactor incidentally closes (flagged here deliberately, not smuggled in silently).

```python
def add_items(collection: Any, items: Iterable[Any], *, dry_run: bool = False) -> int:
    item_list = list(items)
    if str(collection.title) != LOCKED_COLLECTION:
        item_list = _drop_locked(item_list)
    if item_list and not dry_run:
        collection.addItems(item_list)
        for item in item_list:
            log_mutation(
                MutationEvent(
                    action="add",
                    title=item.title,
                    rating_key=getattr(item, "ratingKey", None),
                    collection=str(collection.title),
                )
            )
    return len(item_list)


def remove_items(collection: Any, items: Iterable[Any], *, dry_run: bool = False) -> int:
    item_list = list(items)
    if str(collection.title) != LOCKED_COLLECTION:
        item_list = _drop_locked(item_list)
    if item_list and not dry_run:
        collection.removeItems(item_list)
        for item in item_list:
            log_mutation(
                MutationEvent(
                    action="remove",
                    title=item.title,
                    rating_key=getattr(item, "ratingKey", None),
                    collection=str(collection.title),
                )
            )
    return len(item_list)


def set_studio(video: Any, studio: str, *, dry_run: bool = False) -> bool:
    if has_collection(video, LOCKED_COLLECTION):
        print(warn(f"Skipping '{video.title}' - locked ('{LOCKED_COLLECTION}')"))
        return False
    if dry_run:
        return True
    old_studio = getattr(video, "studio", None)
    video.edit(**{"studio.value": studio, "label.locked": 1})
    log_mutation(
        MutationEvent(
            action="edit_studio",
            title=video.title,
            rating_key=getattr(video, "ratingKey", None),
            details={"old_studio": old_studio, "new_studio": studio},
        )
    )
    return True


def add_writer(video: Any, writer_names: list[str], *, dry_run: bool = False) -> bool:
    if has_collection(video, LOCKED_COLLECTION):
        print(warn(f"Skipping '{video.title}' - locked ('{LOCKED_COLLECTION}')"))
        return False
    if dry_run:
        return True
    video.addWriter(writer_names, True)
    log_mutation(
        MutationEvent(
            action="add_writer",
            title=video.title,
            rating_key=getattr(video, "ratingKey", None),
            details={"writers": writer_names},
        )
    )
    return True


def rename_collection(collection: Any, new_title: str, *, dry_run: bool = False) -> None:
    old_title = str(collection.title)
    if dry_run:
        return
    collection.editTitle(new_title)
    log_mutation(MutationEvent(action="rename_collection", title=new_title, details={"old_title": old_title}))


def create_smart_collection(
    section: Any, *, title: str, sort: str, filters: dict[str, Any], dry_run: bool = False
) -> None:
    if dry_run:
        return
    section.createCollection(title=title, smart=True, sort=sort, filters=filters)
    log_mutation(MutationEvent(action="create_collection", title=title, details={"filters": filters}))
```

`plexadm/cli.py` call-site changes (mechanical, 6 sites):
- `set_studio_for_title_matches` (line 322), `set_independent_for_writers_file` (line 349), `rename_studio` (line 361): replace the `if not args.dry_run: video.edit(...)` block with `set_studio(video, <target studio>, dry_run=args.dry_run)`.
- `set_writers_from_titles` (line 504): replace with `add_writer(video, writers_from_title(video.title), dry_run=args.dry_run)`.
- `sync_smart_collections` (lines 526, 533): replace both `ctx.section.createCollection(...)` blocks with `create_smart_collection(ctx.section, title=title, sort="titleSort:asc", filters={...}, dry_run=args.dry_run)`.
- `rename_collections` (line 554): replace with `rename_collection(collection, new_title, dry_run=args.dry_run)`.

Each site's existing `changed += 1` / `matched += 1` counters key off the new helper's return value (or, for `rename_collection`/`create_smart_collection` which returns `None`, keep counting in the loop as before — only the mutation call itself changes).

## 7. Non-goals (explicitly out of scope for this design)

- **Fan-out to multiple simultaneous sinks.** One active sink per the config's `sink` key, per the earlier decision — simpler config, simpler failure handling (one thing that can fail, one clear error).
- **Time-based rotation for the file sink.** Size-based only (`RotatingFileHandler`, `max_bytes`/`backup_count`), matching what NLog calls `archiveAboveSize`. Daily/time-based archiving is a plausible future addition but isn't needed to satisfy the task and shouldn't be built speculatively.
- **Rotation/retention tooling for syslog/journal/OpenSearch.** Explicitly the user's own infrastructure per the original ask — `journald.conf`'s `SystemMaxUse`, the syslog receiver's own log rotation, OpenSearch ISM/index-lifecycle policies. plexadm sends events; it doesn't manage those backends' storage.
- **Unifying with the existing ad-hoc stdlib `logging`/`--log-level` debug output** in `stash.py`/`stash_reconcile.py`/`stash_sync_tags.py`. Different purpose (developer debug output vs. an audit trail), different lifecycle; conflating them risks exactly the root-logger collisions §4 deliberately avoids.
- **Auditing Stash-side mutations** (`plexadm/stash.py`'s `update_scene`/`merge_scenes`/`sync_play_history`, invoked from `stash_reconcile.py`/`stash_sync_tags.py`). Separate system from Plex, and those call sites have no `dry_run` support at all today (a pre-existing, unrelated gap). The Odoo task is explicitly scoped to Plex mutation choke points; Stash auditing is reasonable future follow-up, not part of this design.
- **Severity/level filtering of audit events.** This is an audit trail, not a debug log — every real mutation is always recorded; there's no `level` config key to suppress some of them.

## 8. Docker considerations

- **File sink** (the default): `docker-compose.yml` needs a new volume mount for `~/.plexadm/` (container path `/root/.plexadm`, matching how `.plexconfig.ini` and `reference/` are already bind-mounted) or the audit trail is lost whenever the container is removed — exactly the durability problem this feature exists to solve. Add to `docker-compose.yml`:
  ```yaml
  volumes:
    - /mnt/myzmirror/plexscripts/audit:/root/.plexadm:rw
  ```
- **Syslog**: the default `/dev/log` unix socket generally does not exist in the slim container image (no local syslog daemon). `[logging.syslog] address` must point at a reachable `host:port` for Docker deployments; `_build_handler` raises a clear, docker-aware `RuntimeError` at startup rather than failing silently mid-run.
- **Journal**: needs `/run/systemd/journal` from the host bind-mounted in; effectively bare-metal-oriented. Document it as such rather than trying to make it Docker-transparent.
- **OpenSearch**: a plain HTTPS client, works identically in both environments — this is why it's the natural choice for Morgan's own Docker deployment, matching the stated intent to use it there.

## 9. Dependencies

- `opensearch-py` added to `requirements.txt` as a base dependency (not optional) — it's the sink the primary deployment actually uses, and the project has no extras/optional-dependency mechanism (plain `requirements.txt`, no `pyproject.toml` `[project]` table) to gate it behind a flag without adding new packaging machinery.
- `systemd-python` is **not** added to `requirements.txt` — it requires `libsystemd-dev` at build time (a C extension), which would bloat every Docker build including the majority of users who'll never select `sink = journal` (a bare-metal-oriented sink to begin with, per §8). Imported lazily inside `_build_handler`; selecting `sink = journal` without it installed raises a clear `RuntimeError` naming the exact `pip install` command. Document the manual install step in the README.
- `syslog` needs no new dependency (`logging.handlers.SysLogHandler` is stdlib).

## 10. Testing

No test file for `plexadm/plex.py` exists today (confirmed: `tests/` only has `test_helpers.py` and `test_stash_reconcile.py`) — the `99: LOCKED` guard and `add_items`/`remove_items` are currently untested. This work should add `tests/test_plex.py`, following `test_stash_reconcile.py`'s style (plain functions/classes, `SimpleNamespace`-mocked Plex objects, no live server):

- `TestAddRemoveItems`: LOCKED items are dropped and not passed to `collection.addItems`/`removeItems`; dry-run makes no API call and logs nothing (patch `plexadm.plex.log_mutation`, assert not called); a real add/remove calls `log_mutation` once per surviving item with the expected `action`/`title`/`rating_key`/`collection`.
- `TestSetStudioAddWriterRenameCreate`: each new helper (`set_studio`, `add_writer`, `rename_collection`, `create_smart_collection`) — LOCKED-skip behavior (for the two that check it), dry-run no-ops with no `log_mutation` call, real call invokes the underlying `plexapi` method and `log_mutation` with correct `details`.

New `tests/test_audit.py`:
- `TestMutationEventToRecord`: with and without an active `set_invocation_context`, verifies `rule`/`invocation` default to `"unknown"`/`""` vs. populated values; `timestamp` is UTC ISO-8601.
- `TestBuildHandler`: `sink="file"` produces a `RotatingFileHandler` with the configured path/size/backup_count (using `tmp_path`); `sink="opensearch"` without a `[logging.opensearch]` section raises `RuntimeError`; `sink="journal"` with `systemd` import mocked-missing raises a `RuntimeError` naming `pip install systemd-python`; unknown sink raises `ValueError`.
- `TestLogMutationFailureHandling`: monkeypatch the built handler's `emit` to raise, call `log_mutation`, assert `has_failures()` becomes `True` and the failure is printed to stderr (via `capsys`) rather than raised out of `log_mutation` (mutations must never fail *because* logging failed — the Plex API call already succeeded by the time logging happens).
- `TestLoadLoggingConfig`: absent `[logging]` section defaults to `sink="file"` with `FileSinkConfig()` defaults; explicit `[logging.file]`/`[logging.syslog]`/`[logging.journal]`/`[logging.opensearch]` values round-trip correctly; `sink="opensearch"` with no `[logging.opensearch]` section raises `KeyError`.

Run `make lintfix && make lint && make test` before considering implementation done, per AGENTS.md.

### Critical files for implementation
- `plexadm/audit.py` (new — `MutationEvent`, `InvocationContext`/`set_invocation_context`, sink handlers, `configure`/`log_mutation`/`has_failures`)
- `plexadm/config.py` (extend — `FileSinkConfig`/`SyslogSinkConfig`/`JournalSinkConfig`/`OpenSearchSinkConfig`/`LoggingConfig`, `load_logging_config`)
- `plexadm/plex.py` (extend — `log_mutation` calls in `add_items`/`remove_items`; new `set_studio`/`add_writer`/`rename_collection`/`create_smart_collection`)
- `plexadm/cli.py` (`main()` calls `audit.configure`/`audit.set_invocation_context`; 6 call sites switched to the new `plex.py` helpers)
- `requirements.txt` (add `opensearch-py`)
- `AGENTS.md` (document the audit-logging invariant analogous to the existing `99: LOCKED` section)
- `docker-compose.yml` / README (document `[logging]` config, add the audit-log volume mount example)
- `tests/test_plex.py` (new)
- `tests/test_audit.py` (new)
