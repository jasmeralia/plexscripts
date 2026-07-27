from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from plexadm.dupes_report import (
    DEFAULT_DUPES_BASE_DIR,
    DupeFile,
    _build_groups,
    _build_recommendation,
    _dupe_files,
    _format_duration,
    _format_size,
    _translate_path,
    dupes_report,
)


def _file(path: str, *, duration_ms: int = 60_000, size_bytes: int = 1_000_000, height: int = 1080) -> DupeFile:
    return DupeFile(path=path, duration_ms=duration_ms, size_bytes=size_bytes, resolution=str(height), height=height)


class TestTranslatePath:
    def test_replaces_default_prefix_with_default_base_dir(self) -> None:
        assert (
            _translate_path("/data/NSFW Scenes/Alice/foo.mp4", DEFAULT_DUPES_BASE_DIR)
            == "/mnt/myzmirror/plexdata/NSFW Scenes/Alice/foo.mp4"
        )

    def test_normalizes_a_base_dir_missing_a_trailing_slash(self) -> None:
        assert _translate_path("/data/Alice/foo.mp4", "/other/mount") == "/other/mount/Alice/foo.mp4"

    def test_leaves_a_path_without_the_prefix_unchanged(self) -> None:
        assert _translate_path("/elsewhere/Alice/foo.mp4", DEFAULT_DUPES_BASE_DIR) == "/elsewhere/Alice/foo.mp4"


class TestFormatDuration:
    def test_formats_minutes_and_seconds(self) -> None:
        assert _format_duration(150_400) == "2:30"

    def test_formats_hours_when_present(self) -> None:
        assert _format_duration(3_661_000) == "1:01:01"

    def test_zero_duration(self) -> None:
        assert _format_duration(0) == "0:00"


class TestFormatSize:
    def test_bytes(self) -> None:
        assert _format_size(500) == "500 B"

    def test_megabytes(self) -> None:
        assert _format_size(115_763_303) == "110.4 MB"

    def test_gigabytes(self) -> None:
        assert _format_size(2_147_483_648) == "2.0 GB"


class TestBuildRecommendation:
    def test_duration_mismatch_needs_manual_review(self) -> None:
        files = [_file("/a.mp4", duration_ms=60_000), _file("/b.mp4", duration_ms=90_000)]
        rec = _build_recommendation(files)
        assert rec.category == "manual-review"
        assert "durations do not match" in rec.message.lower()
        assert rec.to_delete == []

    def test_duration_within_tolerance_is_not_a_mismatch(self) -> None:
        # Real duplicate pairs differ by tens of ms of mux jitter, not more - and differ in
        # size here too, so this isolates the duration-tolerance behavior from the separate
        # "files are otherwise identical" edge case covered below.
        files = [
            _file("/a.mp4", duration_ms=150_400, size_bytes=288_252_490),
            _file("/b.mp4", duration_ms=150_433, size_bytes=115_763_303),
        ]
        rec = _build_recommendation(files)
        assert rec.category == "delete-lowest"

    def test_ppv_file_at_highest_resolution_recommends_deleting_non_ppv(self) -> None:
        files = [
            _file("/writer/Scene.mp4", height=1080),
            _file("/writer/Scene - PPV Message.mp4", height=1080),
        ]
        rec = _build_recommendation(files)
        assert rec.category == "delete-non-ppv"
        assert rec.to_delete == ["/writer/Scene.mp4"]

    def test_ppv_file_present_but_not_highest_resolution_needs_manual_review(self) -> None:
        files = [
            _file("/writer/Scene.mp4", height=1080),
            _file("/writer/Scene - PPV Message.mp4", height=720),
        ]
        rec = _build_recommendation(files)
        assert rec.category == "manual-review"
        assert "not the highest resolution" in rec.message

    def test_all_files_are_ppv_recommends_nothing(self) -> None:
        files = [
            _file("/writer/Scene - PPV Message A.mp4", height=1080),
            _file("/writer/Scene - PPV Message B.mp4", height=1080),
        ]
        rec = _build_recommendation(files)
        assert rec.category == "delete-non-ppv"
        assert rec.to_delete == []

    def test_no_ppv_recommends_deleting_lowest_resolution(self) -> None:
        files = [_file("/high.mp4", height=1080), _file("/low.mp4", height=480)]
        rec = _build_recommendation(files)
        assert rec.category == "delete-lowest"
        assert rec.to_delete == ["/low.mp4"]

    def test_no_ppv_ties_on_resolution_breaks_by_size(self) -> None:
        files = [
            _file("/big.mp4", height=1080, size_bytes=288_252_490),
            _file("/small.mp4", height=1080, size_bytes=115_763_303),
        ]
        rec = _build_recommendation(files)
        assert rec.category == "delete-lowest"
        assert rec.to_delete == ["/small.mp4"]

    def test_identical_files_keep_one_instead_of_recommending_deleting_all(self) -> None:
        files = [_file("/b.mp4", height=1080, size_bytes=1_000), _file("/a.mp4", height=1080, size_bytes=1_000)]
        rec = _build_recommendation(files)
        assert rec.category == "manual-review"
        # Deterministic keep-one, chosen by path - never recommends deleting every copy.
        assert rec.to_delete == ["/b.mp4"]
        assert "/a.mp4" in rec.message

    def test_single_file_needs_manual_review(self) -> None:
        rec = _build_recommendation([_file("/only.mp4")])
        assert rec.category == "manual-review"
        assert rec.to_delete == []


class TestDupeFiles:
    def test_extracts_path_duration_size_resolution_per_part(self) -> None:
        part = SimpleNamespace(file="/data/Alice/foo.mp4", size=123, duration=None)
        media = SimpleNamespace(videoResolution="1080", height=1080, duration=60_000, parts=[part])
        video = SimpleNamespace(media=[media])
        files = _dupe_files(video, DEFAULT_DUPES_BASE_DIR)
        assert len(files) == 1
        assert files[0].path == "/mnt/myzmirror/plexdata/Alice/foo.mp4"
        assert files[0].size_bytes == 123
        # Part duration falls back to the parent media's duration when unset.
        assert files[0].duration_ms == 60_000
        assert files[0].resolution == "1080"
        assert files[0].height == 1080

    def test_skips_parts_with_no_file(self) -> None:
        part = SimpleNamespace(file=None, size=0, duration=0)
        media = SimpleNamespace(videoResolution="1080", height=1080, duration=0, parts=[part])
        video = SimpleNamespace(media=[media])
        assert _dupe_files(video, DEFAULT_DUPES_BASE_DIR) == []


def _mock_video(
    title: str, files: list[tuple[str, int, int, int]], *, title_locked: bool = True, sort_locked: bool = True
) -> SimpleNamespace:
    media = []
    for path, duration, size, height in files:
        part = SimpleNamespace(file=path, size=size, duration=duration)
        media.append(SimpleNamespace(videoResolution=str(height), height=height, duration=duration, parts=[part]))
    return SimpleNamespace(
        title=title,
        media=media,
        isLocked=MagicMock(side_effect=lambda field: title_locked if field == "title" else sort_locked),
    )


class TestBuildGroups:
    def test_builds_one_group_per_video_with_locked_flags(self) -> None:
        video = _mock_video(
            "Writer - Scene",
            [("/data/a.mp4", 60_000, 100, 1080), ("/data/b.mp4", 60_000, 50, 1080)],
            title_locked=True,
            sort_locked=False,
        )
        groups = _build_groups([video], DEFAULT_DUPES_BASE_DIR)
        assert len(groups) == 1
        group = groups[0]
        assert group.title == "Writer - Scene"
        assert group.title_locked is True
        assert group.sort_title_locked is False
        assert len(group.files) == 2
        assert group.recommendation.category == "delete-lowest"

    def test_skips_videos_with_no_files(self) -> None:
        video = SimpleNamespace(title="No Media", media=[], isLocked=MagicMock(return_value=False))
        assert _build_groups([video], DEFAULT_DUPES_BASE_DIR) == []


class TestDupesReportCommand:
    def test_writes_report_and_returns_zero(self, tmp_path: Path) -> None:
        video_a = _mock_video(
            "Alice - PPV Scene", [("/data/a.mp4", 60_000, 100, 1080), ("/data/a - PPV.mp4", 60_000, 100, 1080)]
        )
        video_b = _mock_video(
            "Bob - Mismatch", [("/data/b1.mp4", 60_000, 100, 1080), ("/data/b2.mp4", 90_000, 100, 720)]
        )
        plex_ctx = MagicMock()
        plex_ctx.section.search.return_value = [video_a, video_b]
        output = tmp_path / "dupes.md"
        args = SimpleNamespace(config="config.ini", output=output, base_dir=DEFAULT_DUPES_BASE_DIR)

        with (
            patch("plexadm.dupes_report.load_config", return_value=SimpleNamespace()),
            patch("plexadm.dupes_report.PlexContext", return_value=plex_ctx),
        ):
            assert dupes_report(args) == 0

        plex_ctx.section.search.assert_called_once_with(duplicate=True)
        report = output.read_text(encoding="utf-8")
        assert "Found 2 duplicate-flagged videos." in report
        assert "## Recommended Deletions - PPV Kept (1)" in report
        assert "## Needs Manual Review (1)" in report
        assert "Alice - PPV Scene" in report
        assert "Bob - Mismatch" in report
