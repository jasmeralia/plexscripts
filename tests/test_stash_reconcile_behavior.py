from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import requests

from plexadm import stash_reconcile
from plexadm.config import PlexConfig


def _video(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "title": "Example Scene",
        "studio": None,
        "writers": [],
        "directors": [],
        "collections": [],
        "userRating": None,
        "viewCount": 0,
        "locations": [],
        "history": MagicMock(return_value=[]),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _args(tmp_path: Path, **overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "config": "config.ini",
        "stash_endpoint": None,
        "limit": None,
        "path": None,
        "log_level": "info",
        "csv_output": str(tmp_path / "scope.csv"),
        "skip_scan": True,
        "progress_interval": 60,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_fetch_plex_cover_handles_missing_success_and_request_failure(caplog: pytest.LogCaptureFixture) -> None:
    cfg = PlexConfig("plex", "32400", "token", "Videos")
    assert stash_reconcile._fetch_plex_cover(SimpleNamespace(title="No Cover", thumb=None), cfg) is None

    response = MagicMock(content=b"image")
    response.headers = {"Content-Type": "image/png"}
    with patch.object(stash_reconcile.requests, "get", return_value=response) as mock_get:
        result = stash_reconcile._fetch_plex_cover(SimpleNamespace(title="Covered", thumb="/thumb/1"), cfg)
    assert result == "data:image/png;base64,aW1hZ2U="
    mock_get.assert_called_once_with("http://plex:32400/thumb/1?X-Plex-Token=token", timeout=15)
    response.raise_for_status.assert_called_once_with()

    with patch.object(stash_reconcile.requests, "get", side_effect=requests.RequestException("offline")):
        assert stash_reconcile._fetch_plex_cover(SimpleNamespace(title="Broken Cover", thumb="/thumb/2"), cfg) is None
    assert "Failed to fetch Plex cover for 'Broken Cover'" in caplog.text


def test_reconcile_requires_configured_endpoint(tmp_path: Path) -> None:
    with (
        patch.object(stash_reconcile, "load_logging_config"),
        patch.object(stash_reconcile, "configure_command_logging"),
        patch.object(stash_reconcile, "load_config", return_value=SimpleNamespace(stash_endpoint=None)),
        pytest.raises(ValueError, match="No Stash endpoint"),
    ):
        stash_reconcile.reconcile(_args(tmp_path))


def test_reconcile_merges_updates_preserves_existing_metadata_and_exports_scope(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    scene_10 = {
        "id": "10",
        "files": [{"path": "/merge-a.mp4"}],
        "performers": [{"id": "existing-performer"}],
        "tags": [{"id": "existing-tag"}],
    }
    scene_11 = {
        "id": "11",
        "files": [{"path": "/merge-b.mp4"}],
        "performers": [],
        "tags": [],
    }
    scene_12 = {"id": "12", "files": [{"path": "/single.mp4"}], "performers": [], "tags": []}
    scene_13 = {"id": "13", "files": [{"path": "/unmatched-stash.mp4"}], "performers": [], "tags": []}
    scene_14 = {"id": "14", "files": [{"path": "/no-data.mp4"}], "performers": [], "tags": []}
    stash_index = {
        "/merge-a.mp4": scene_10,
        "/merge-b.mp4": scene_11,
        "/single.mp4": scene_12,
        "/unmatched-stash.mp4": scene_13,
        "/no-data.mp4": scene_14,
    }
    stash = MagicMock()
    stash.all_scenes.return_value = stash_index
    stash.find_or_create_studio.return_value = "studio-id"
    stash.find_or_create_performer.return_value = "writer-id"
    stash.find_or_create_tag.return_value = "tag-id"

    history = [SimpleNamespace(viewedAt=datetime(2026, 1, 2, 3, 4, 5)), SimpleNamespace(viewedAt=None)]
    merge_video = _video(
        title="Merged Example",
        studio="Example Studio",
        writers=["Example Writer"],
        directors=["Example Director"],
        collections=["01: Theme: Example", "02: Studio: Ignored"],
        userRating=8.5,
        viewCount=2,
        locations=["/merge-a.mp4", "/merge-b.mp4"],
        history=MagicMock(return_value=history),
    )
    single_video = _video(title="Single Example", directors=["Second Director"], locations=["/single.mp4"])
    no_data_video = _video(title="No Data", locations=["/no-data.mp4"])
    plex = MagicMock()
    plex.all_videos.return_value = [
        _video(title="No File"),
        _video(title="No Stash Match", locations=["/missing.mp4"]),
        merge_video,
        single_video,
        no_data_video,
    ]
    cfg = PlexConfig("plex", "32400", "token", "Videos", stash_endpoint="http://stash:9999")

    with (
        patch.object(stash_reconcile, "load_logging_config", return_value=MagicMock()),
        patch.object(stash_reconcile, "configure_command_logging") as mock_logging,
        patch.object(stash_reconcile, "load_config", return_value=cfg),
        patch.object(stash_reconcile, "StashClient", return_value=stash),
        patch.object(stash_reconcile, "PlexContext", return_value=plex),
        patch.object(stash_reconcile, "reload_if_partial") as mock_reload,
        patch.object(stash_reconcile, "_fetch_plex_cover", side_effect=["data:image/jpeg;base64,YQ==", None]),
    ):
        assert stash_reconcile.reconcile(_args(tmp_path)) == 0

    mock_logging.assert_called_once()
    assert mock_reload.call_count == 5
    stash.find_or_create_studio.assert_called_once_with("Example Studio")
    stash.find_or_create_performer.assert_called_once_with("Example Writer")
    stash.find_or_create_tag.assert_called_once_with("Theme: Example")

    merge_update = stash.merge_scenes.call_args.args[2]
    assert stash.merge_scenes.call_args.args[:2] == (["11"], "10")
    assert merge_update["title"] == "Merged Example"
    assert merge_update["studio_id"] == "studio-id"
    assert merge_update["director"] == "Example Director"
    assert merge_update["rating100"] == 85
    assert merge_update["cover_image"] == "data:image/jpeg;base64,YQ=="
    assert set(merge_update["performer_ids"]) == {"existing-performer", "writer-id"}
    assert set(merge_update["tag_ids"]) == {"existing-tag", "tag-id"}
    stash.sync_play_history.assert_called_once_with("10", ["2026-01-02T03:04:05Z"])
    stash.update_scene.assert_called_once_with("12", {"title": "Single Example", "director": "Second Director"})

    csv_text = (tmp_path / "scope.csv").read_text(encoding="utf-8")
    assert "matched_no_data,14,/no-data.mp4" in csv_text
    assert "unmatched,13,/unmatched-stash.mp4" in csv_text
    output = capsys.readouterr().out
    assert "Scenes updated: 2" in output
    assert "Matched but no usable Plex metadata: 1" in output
    assert "Stash scenes with no Plex match: 1" in output


def test_reconcile_path_filter_and_limit_stop_processing_and_skip_unmatched_scope(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    scene = {"id": "1", "files": [{"path": "/wanted/one.mp4"}], "performers": [], "tags": []}
    stash = MagicMock()
    stash.all_scenes.return_value = {"/wanted/one.mp4": scene}
    plex = MagicMock()
    plex.all_videos.return_value = [
        _video(title="Filtered", directors=["Director"], locations=["/other/zero.mp4"]),
        _video(title="Wanted", directors=["Director"], locations=["/wanted/one.mp4"]),
        _video(title="Beyond Limit", directors=["Director"], locations=["/wanted/two.mp4"]),
    ]
    cfg = PlexConfig("plex", "32400", "token", "Videos", stash_endpoint="http://stash:9999")

    with (
        patch.object(stash_reconcile, "load_logging_config", return_value=MagicMock()),
        patch.object(stash_reconcile, "configure_command_logging"),
        patch.object(stash_reconcile, "load_config", return_value=cfg),
        patch.object(stash_reconcile, "StashClient", return_value=stash),
        patch.object(stash_reconcile, "PlexContext", return_value=plex),
        patch.object(stash_reconcile, "_fetch_plex_cover", return_value=None),
    ):
        assert stash_reconcile.reconcile(_args(tmp_path, path="/wanted", limit=1)) == 0

    stash.update_scene.assert_called_once_with("1", {"title": "Wanted", "director": "Director"})
    assert "skipped" in capsys.readouterr().out
    assert (tmp_path / "scope.csv").read_text(encoding="utf-8").splitlines() == ["bucket,stash_scene_id,path"]
