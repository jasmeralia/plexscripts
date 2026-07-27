from __future__ import annotations

import argparse
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from plexadm import cli


def _video(title: str, locations: list[str]) -> SimpleNamespace:
    return SimpleNamespace(title=title, locations=locations)


class TestRenameCandidates:
    def test_flags_a_video_whose_filename_does_not_contain_the_title(self) -> None:
        ctx = MagicMock()
        ctx.all_videos.return_value = [_video("Alice - Scene One", ["/data/Alice/wrong_name.mp4"])]
        candidates = list(cli._rename_candidates(ctx, None))
        assert len(candidates) == 1
        assert candidates[0][0].title == "Alice - Scene One"

    def test_does_not_flag_a_video_whose_filename_matches_the_title(self) -> None:
        ctx = MagicMock()
        ctx.all_videos.return_value = [_video("Alice - Scene One", ["/data/Alice/Alice - Scene One.mp4"])]
        assert list(cli._rename_candidates(ctx, None)) == []

    def test_skips_videos_with_no_locations(self) -> None:
        ctx = MagicMock()
        ctx.all_videos.return_value = [_video("No File", [])]
        assert list(cli._rename_candidates(ctx, None)) == []

    def test_filter_text_matches_title_or_location(self) -> None:
        ctx = MagicMock()
        ctx.all_videos.return_value = [
            _video("Alice - Scene One", ["/data/Alice/wrong_name.mp4"]),
            _video("Bob - Scene One", ["/data/Bob/wrong_name.mp4"]),
        ]
        candidates = list(cli._rename_candidates(ctx, "Alice"))
        assert len(candidates) == 1
        assert candidates[0][0].title == "Alice - Scene One"

    def test_multi_location_mismatch_is_flagged_for_review(self) -> None:
        ctx = MagicMock()
        ctx.all_videos.return_value = [
            _video(
                "Alice - Scene One",
                ["/data/Alice/Alice - Scene One.mp4", "/data/Alice/some_other_file.mp4"],
            )
        ]
        candidates = list(cli._rename_candidates(ctx, None))
        assert len(candidates) == 1


class TestListRenames:
    def test_prints_a_rename_diff_for_a_mismatched_video(self, capsys: pytest.CaptureFixture[str]) -> None:
        video = _video("Alice - Scene One", ["/data/NSFW Scenes/Alice/wrong_name.mp4"])
        args = argparse.Namespace(config=None, filter_text=None, base_dir=cli.SCENE_BASE_DIR)

        with patch.object(cli, "build_context") as mock_build_context:
            mock_build_context.return_value.all_videos.return_value = [video]
            assert cli.list_renames(args) == 0

        out = capsys.readouterr().out
        assert "Alice/wrong_name.mp4 -> Alice/Alice - Scene One.mp4" in out

    def test_multi_location_video_prints_a_warning_not_an_mv_command(self, capsys: pytest.CaptureFixture[str]) -> None:
        video = _video(
            "Alice - Scene One",
            ["/data/NSFW Scenes/Alice/Alice - Scene One.mp4", "/data/NSFW Scenes/Alice/other.mp4"],
        )
        args = argparse.Namespace(config=None, filter_text=None, base_dir=cli.SCENE_BASE_DIR)

        with patch.object(cli, "build_context") as mock_build_context:
            mock_build_context.return_value.all_videos.return_value = [video]
            assert cli.list_renames(args) == 0

        out = capsys.readouterr().out
        assert "WARNING: Alice - Scene One has multiple locations!" in out
        assert "mv " not in out

    def test_has_no_script_argument_anymore(self) -> None:
        # `list renames` is report-only now - script generation moved to
        # `tools rename-gen-script`.
        assert not hasattr(argparse.Namespace(), "script")
        with pytest.raises(SystemExit):
            cli.build_parser().parse_args(["list", "renames", "--script"])


class TestRenameGenScript:
    def test_prints_an_mv_command_for_a_mismatched_single_location_video(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        video = _video("Alice - Scene One", ["/data/NSFW Scenes/Alice/wrong_name.mp4"])
        args = argparse.Namespace(config=None, filter_text=None, base_dir=cli.SCENE_BASE_DIR)

        with patch.object(cli, "build_context") as mock_build_context:
            mock_build_context.return_value.all_videos.return_value = [video]
            assert cli.rename_gen_script(args) == 0

        out = capsys.readouterr().out
        assert out.strip() == 'mv "Alice/wrong_name.mp4" "Alice/Alice - Scene One.mp4"'

    def test_skips_multi_location_videos_entirely(self, capsys: pytest.CaptureFixture[str]) -> None:
        video = _video(
            "Alice - Scene One",
            ["/data/NSFW Scenes/Alice/Alice - Scene One.mp4", "/data/NSFW Scenes/Alice/other.mp4"],
        )
        args = argparse.Namespace(config=None, filter_text=None, base_dir=cli.SCENE_BASE_DIR)

        with patch.object(cli, "build_context") as mock_build_context:
            mock_build_context.return_value.all_videos.return_value = [video]
            assert cli.rename_gen_script(args) == 0

        assert capsys.readouterr().out == ""


class TestListSpecialDuplicates:
    def test_prints_title_and_translated_file_paths(self, capsys: pytest.CaptureFixture[str]) -> None:
        part = SimpleNamespace(file="/data/Alice/a.mp4")
        media = SimpleNamespace(parts=[part])
        video = SimpleNamespace(title="Alice - Dupe", media=[media])
        args = argparse.Namespace(config=None, kind="duplicates", base_dir="/mnt/myzmirror/plexdata/")

        with patch.object(cli, "build_context") as mock_build_context, patch.object(cli, "reload_if_partial"):
            mock_build_context.return_value.section.search.return_value = [video]
            assert cli.list_special(args) == 0

        mock_build_context.return_value.section.search.assert_called_once_with(duplicate=True)
        out = capsys.readouterr().out
        assert "Alice - Dupe:" in out
        assert "/mnt/myzmirror/plexdata/Alice/a.mp4" in out

    def test_skips_a_duplicate_flagged_video_with_no_files(self, capsys: pytest.CaptureFixture[str]) -> None:
        video = SimpleNamespace(title="No Files", media=[])
        args = argparse.Namespace(config=None, kind="duplicates", base_dir="/mnt/myzmirror/plexdata/")

        with patch.object(cli, "build_context") as mock_build_context, patch.object(cli, "reload_if_partial"):
            mock_build_context.return_value.section.search.return_value = [video]
            assert cli.list_special(args) == 0

        assert capsys.readouterr().out == ""
