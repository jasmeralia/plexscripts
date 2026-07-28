from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from plexadm.config import load_config
from plexadm.console import info, ok, warn
from plexadm.plex import PlexContext, reload_if_partial

# Path prefix Plex reports internally (the library section is mounted at /data inside the
# container) - always replaced with --base-dir's value, which defaults to the real host path
# below. Not itself configurable: it's a fact about how the section is mounted, not a
# preference.
DUPES_PATH_PREFIX = "/data/"
DEFAULT_DUPES_BASE_DIR = "/mnt/myzmirror/plexdata/"

# Duplicate "versions" of the same scene are frequently two independent encodes/imports of the
# same source, whose durations differ by tens of milliseconds (container/mux jitter) rather than
# matching exactly - confirmed against the live library, e.g. 150400ms vs 150433ms for one real
# duplicate pair. 1 second comfortably absorbs that jitter while still catching genuinely
# different cuts/lengths.
DURATION_MATCH_TOLERANCE_MS = 1000


@dataclass
class DupeFile:
    path: str
    duration_ms: int
    size_bytes: int
    resolution: str
    height: int


@dataclass
class Recommendation:
    category: str  # "delete-non-ppv" | "delete-lowest" | "manual-review"
    message: str
    to_delete: list[str] = field(default_factory=list)


@dataclass
class DupeGroup:
    title: str
    title_locked: bool
    sort_title_locked: bool
    files: list[DupeFile]
    recommendation: Recommendation


_CATEGORY_ORDER = ["delete-non-ppv", "delete-lowest", "manual-review"]
_CATEGORY_HEADINGS = {
    "delete-non-ppv": "Recommended Deletions - PPV Kept",
    "delete-lowest": "Recommended Deletions - Lowest Resolution/Size",
    "manual-review": "Needs Manual Review",
}


def _translate_path(path: str, base_dir: str) -> str:
    target = base_dir if base_dir.endswith("/") else f"{base_dir}/"
    if path.startswith(DUPES_PATH_PREFIX):
        return target + path[len(DUPES_PATH_PREFIX) :]
    return path


def _format_duration(ms: int) -> str:
    total_seconds = max(ms, 0) // 1000
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def _format_size(num_bytes: int) -> str:
    size = float(max(num_bytes, 0))
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _dupe_files(video: Any, base_dir: str) -> list[DupeFile]:
    files: list[DupeFile] = []
    for media in getattr(video, "media", None) or []:
        resolution = str(media.videoResolution or "unknown")
        height = media.height or 0
        for part in getattr(media, "parts", None) or []:
            if not part.file:
                continue
            duration = part.duration if part.duration is not None else media.duration
            files.append(
                DupeFile(
                    path=_translate_path(str(part.file), base_dir),
                    duration_ms=int(duration or 0),
                    size_bytes=int(part.size or 0),
                    resolution=resolution,
                    height=height,
                )
            )
    return files


def _durations_match(files: list[DupeFile]) -> bool:
    durations = [f.duration_ms for f in files]
    return (max(durations) - min(durations)) <= DURATION_MATCH_TOLERANCE_MS


def _build_recommendation(files: list[DupeFile]) -> Recommendation:
    if len(files) < 2:
        return Recommendation("manual-review", "Only one file found for this duplicate-flagged video.")

    if not _durations_match(files):
        return Recommendation("manual-review", "Durations do not match across files - needs manual review.")

    max_height = max(f.height for f in files)
    ppv_files = [f for f in files if "PPV" in f.path]
    ppv_at_max_res = [f for f in ppv_files if f.height == max_height]

    if ppv_at_max_res:
        to_delete = [f.path for f in files if "PPV" not in f.path]
        if not to_delete:
            return Recommendation("delete-non-ppv", "All files already contain 'PPV' - nothing to delete.")
        return Recommendation(
            "delete-non-ppv",
            "A PPV file is the highest resolution and durations match - delete the non-PPV file(s).",
            to_delete,
        )

    if not ppv_files:
        min_height = min(f.height for f in files)
        lowest = [f for f in files if f.height == min_height]
        candidates = lowest
        if len(lowest) > 1:
            min_size = min(f.size_bytes for f in lowest)
            candidates = [f for f in lowest if f.size_bytes == min_size]
        if len(candidates) == len(files):
            # Every file ties on both resolution and size - there's no criterion left to pick a
            # "worse" copy, and recommending deletion of every copy would leave nothing behind.
            # Keep one (chosen deterministically, not by any real quality signal) and flag the
            # rest for a human to actually verify.
            keep, *rest = sorted(files, key=lambda f: f.path)
            return Recommendation(
                "manual-review",
                f"All files match in resolution and size - keeping '{keep.path}' arbitrarily; "
                "verify before deleting the rest.",
                [f.path for f in rest],
            )
        return Recommendation(
            "delete-lowest",
            "Durations match and no PPV file is present - delete the lowest-resolution/size file(s).",
            [f.path for f in candidates],
        )

    return Recommendation(
        "manual-review", "A PPV file is present but is not the highest resolution - needs manual review."
    )


def _build_groups(videos: list[Any], base_dir: str) -> list[DupeGroup]:
    groups = []
    for video in videos:
        files = _dupe_files(video, base_dir)
        if not files:
            continue
        groups.append(
            DupeGroup(
                title=str(video.title),
                title_locked=bool(video.isLocked("title")),
                sort_title_locked=bool(video.isLocked("titleSort")),
                files=files,
                recommendation=_build_recommendation(files),
            )
        )
    return groups


def _escape_cell(value: object) -> str:
    return str(value).replace("|", "\\|")


def _write_group_lines(lines: list[str], group: DupeGroup) -> None:
    lines.append(f"### {group.title}")
    lines.append("")
    lines.append(f"- Title locked: {'Yes' if group.title_locked else 'No'}")
    lines.append(f"- Sort title locked: {'Yes' if group.sort_title_locked else 'No'}")
    lines.append(f"- Recommendation: {group.recommendation.message}")
    if group.recommendation.to_delete:
        lines.append("- Suggested deletions:")
        lines.extend(f"  - `{path}`" for path in group.recommendation.to_delete)
    lines.append("")
    lines.append("| File | Duration | Size | Resolution |")
    lines.append("|---|---|---:|---:|")
    lines.extend(
        f"| `{_escape_cell(file.path)}` | {_format_duration(file.duration_ms)} | "
        f"{_format_size(file.size_bytes)} | {_escape_cell(file.resolution)} |"
        for file in group.files
    )
    lines.append("")


def _write_dupes_report(path: str | Path, groups: list[DupeGroup], *, generated_at: str) -> None:
    by_category: dict[str, list[DupeGroup]] = defaultdict(list)
    for group in groups:
        by_category[group.recommendation.category].append(group)

    lines = [
        "# Plex Duplicate Videos Report",
        "",
        f"Generated: {generated_at}",
        "",
        f"Found {len(groups)} duplicate-flagged videos.",
        "",
        "A heuristic starting point for manual review, not an instruction to delete anything "
        "automatically - verify each recommendation before removing a file.",
    ]
    for category in _CATEGORY_ORDER:
        rows = sorted(by_category.get(category, []), key=lambda g: g.title)
        lines.extend(["", f"## {_CATEGORY_HEADINGS[category]} ({len(rows)})", ""])
        if not rows:
            lines.append("_None._")
            continue
        for group in rows:
            _write_group_lines(lines, group)

    report_path = Path(path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def dupes_report(args: Any) -> int:
    cfg = load_config(args.config)
    ctx = PlexContext(cfg)

    print(info("Searching for duplicate-flagged videos..."))
    videos = ctx.section.search(duplicate=True)
    for video in videos:
        reload_if_partial(video)

    groups = _build_groups(videos, args.base_dir)
    generated_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    report_path = Path(args.output)
    _write_dupes_report(report_path, groups, generated_at=generated_at)

    counts = Counter(group.recommendation.category for group in groups)
    print(ok(f"Duplicate-flagged videos: {len(groups)}"))
    print(info(f"  Safe to delete (PPV kept): {counts.get('delete-non-ppv', 0)}"))
    print(info(f"  Safe to delete (lowest resolution/size): {counts.get('delete-lowest', 0)}"))
    print(warn(f"  Needs manual review: {counts.get('manual-review', 0)}"))
    print(info(f"Report written to {report_path}"))
    return 0
