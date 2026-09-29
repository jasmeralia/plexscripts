from __future__ import annotations

from datetime import datetime
from itertools import count
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests

from plexadm import stash_reconcile
from plexadm.config import PlexConfig

_VIDEO_KEYS = count(1)


def _video(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "ratingKey": str(next(_VIDEO_KEYS)),
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


def _scene_list(path_index: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    scenes: dict[str, dict[str, Any]] = {}
    for scene in path_index.values():
        scenes[str(scene["id"])] = scene
    return list(scenes.values())


def _set_plex_inventory(plex: MagicMock, videos: list[SimpleNamespace]) -> None:
    plex.all_videos.return_value = videos
    plex.section.totalSize = len(videos)


def _execute_reconcile(
    stash: MagicMock, videos: list[SimpleNamespace], tmp_path: Path, **overrides: object
) -> tuple[int, MagicMock]:
    plex = MagicMock()
    _set_plex_inventory(plex, videos)
    cfg = PlexConfig("plex", "32400", "token", "Videos", stash_endpoint="http://stash:9999")
    with (
        patch.object(stash_reconcile, "load_logging_config", return_value=MagicMock()),
        patch.object(stash_reconcile, "configure_command_logging"),
        patch.object(stash_reconcile, "load_config", return_value=cfg),
        patch.object(stash_reconcile, "StashClient", return_value=stash),
        patch.object(stash_reconcile, "PlexContext", return_value=plex),
        patch.object(stash_reconcile, "_fetch_plex_cover", return_value=None),
        patch.object(stash_reconcile, "reload_if_partial"),
    ):
        result = stash_reconcile.reconcile(_args(tmp_path, **overrides))
    return result, plex


def _args(tmp_path: Path, **overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "config": "config.ini",
        "stash_endpoint": None,
        "limit": None,
        "path": None,
        "added_in_last_days": None,
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


@pytest.mark.parametrize("stored", [42, 42.0, "42", "042"])
def test_rating_key_comparison_normalizes_numeric_and_string_values(stored: object) -> None:
    assert stash_reconcile._key_is_current(stored, "42")


def test_rating_key_comparison_rejects_non_decimal_values() -> None:
    assert not stash_reconcile._key_is_current(True, "1")
    assert not stash_reconcile._key_is_current("42x", "42")
    assert not stash_reconcile._key_is_current(42.5, "42")


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
    stash.reconcile_scenes.return_value = _scene_list(stash_index)
    stash.reconcile_scene_by_id.side_effect = {"10": scene_10, "11": scene_11}.get
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
    videos = [
        _video(title="No Stash Match Without Data", locations=["/no-file.mp4"]),
        _video(title="No Stash Match", locations=["/missing.mp4"]),
        merge_video,
        single_video,
        no_data_video,
    ]
    _set_plex_inventory(plex, videos)
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
    assert mock_reload.call_count == 3
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
    assert stash.update_scene.call_count == 2
    stash.update_scene.assert_any_call(
        "12",
        {
            "title": "Single Example",
            "director": "Second Director",
            "custom_fields": {"partial": {"plex_rating_key": single_video.ratingKey}},
        },
    )
    stash.update_scene.assert_any_call(
        "14", {"custom_fields": {"partial": {"plex_rating_key": no_data_video.ratingKey}}}
    )

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
    stash.reconcile_scenes.return_value = [scene]
    plex = MagicMock()
    videos = [
        _video(title="Filtered", directors=["Director"], locations=["/other/zero.mp4"]),
        _video(title="Wanted", directors=["Director"], locations=["/wanted/one.mp4"]),
        _video(title="Beyond Limit", directors=["Director"], locations=["/wanted/two.mp4"]),
    ]
    _set_plex_inventory(plex, videos)
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

    wanted = videos[1]
    stash.update_scene.assert_called_once_with(
        "1",
        {
            "title": "Wanted",
            "director": "Director",
            "custom_fields": {"partial": {"plex_rating_key": wanted.ratingKey}},
        },
    )
    stash.clean.assert_not_called()
    assert "skipped" in capsys.readouterr().out
    assert (tmp_path / "scope.csv").read_text(encoding="utf-8").splitlines() == ["bucket,stash_scene_id,path"]


def test_reconcile_added_in_last_days_uses_server_side_filter_and_skips_unmatched_scope(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    scene = {"id": "1", "files": [{"path": "/wanted/one.mp4"}], "performers": [], "tags": []}
    unmatched_scene = {"id": "2", "files": [{"path": "/other/unmatched.mp4"}], "performers": [], "tags": []}
    stash = MagicMock()
    stash.reconcile_scenes.return_value = [scene, unmatched_scene]
    plex = MagicMock()
    recent = _video(title="Recent", directors=["Director"], locations=["/wanted/one.mp4"])
    _set_plex_inventory(plex, [recent])
    plex.search.return_value = [recent]
    cfg = PlexConfig("plex", "32400", "token", "Videos", stash_endpoint="http://stash:9999")

    with (
        patch.object(stash_reconcile, "load_logging_config", return_value=MagicMock()),
        patch.object(stash_reconcile, "configure_command_logging"),
        patch.object(stash_reconcile, "load_config", return_value=cfg),
        patch.object(stash_reconcile, "StashClient", return_value=stash),
        patch.object(stash_reconcile, "PlexContext", return_value=plex),
        patch.object(stash_reconcile, "_fetch_plex_cover", return_value=None),
    ):
        assert stash_reconcile.reconcile(_args(tmp_path, added_in_last_days=7)) == 0

    plex.search.assert_called_once_with(filters={"addedAt>>": "7d"})
    plex.all_videos.assert_called_once_with()
    stash.clean.assert_not_called()
    stash.update_scene.assert_called_once_with(
        "1",
        {
            "title": "Recent",
            "director": "Director",
            "custom_fields": {"partial": {"plex_rating_key": recent.ratingKey}},
        },
    )
    output = capsys.readouterr().out
    assert "added in the last 7 day(s)" in output
    assert "skipped" in output
    assert (tmp_path / "scope.csv").read_text(encoding="utf-8").splitlines() == ["bucket,stash_scene_id,path"]


def test_reconcile_single_scene_with_view_history_syncs_play_history(tmp_path: Path) -> None:
    scene = {"id": "1", "files": [{"path": "/watched.mp4"}], "performers": [], "tags": []}
    stash = MagicMock()
    stash.reconcile_scenes.return_value = [scene]
    history = [SimpleNamespace(viewedAt=datetime(2026, 3, 4, 5, 6, 7))]
    plex = MagicMock()
    videos = [
        _video(
            title="Watched",
            studio="Example Studio",
            viewCount=1,
            locations=["/watched.mp4"],
            history=MagicMock(return_value=history),
        )
    ]
    _set_plex_inventory(plex, videos)
    cfg = PlexConfig("plex", "32400", "token", "Videos", stash_endpoint="http://stash:9999")

    with (
        patch.object(stash_reconcile, "load_logging_config", return_value=MagicMock()),
        patch.object(stash_reconcile, "configure_command_logging"),
        patch.object(stash_reconcile, "load_config", return_value=cfg),
        patch.object(stash_reconcile, "StashClient", return_value=stash),
        patch.object(stash_reconcile, "PlexContext", return_value=plex),
        patch.object(stash_reconcile, "_fetch_plex_cover", return_value=None),
    ):
        assert stash_reconcile.reconcile(_args(tmp_path)) == 0

    stash.sync_play_history.assert_called_once_with("1", ["2026-03-04T05:06:07Z"])


def test_reconcile_writes_and_replaces_rating_key_without_replacing_other_custom_fields(tmp_path: Path) -> None:
    scene = {
        "id": "31",
        "files": [{"path": "/key.mp4"}],
        "custom_fields": {"plex_rating_key": "999", "review_note": "keep"},
        "performers": [],
        "tags": [],
    }
    stash = MagicMock()
    stash.reconcile_scenes.return_value = [scene]
    video = _video(directors=["Example Director"], locations=["/key.mp4"], ratingKey="42")

    result, _ = _execute_reconcile(stash, [video], tmp_path)

    assert result == 0
    stash.update_scene.assert_called_once_with(
        "31",
        {
            "title": "Example Scene",
            "director": "Example Director",
            "custom_fields": {"partial": {"plex_rating_key": "42"}},
        },
    )


def test_reconcile_skips_shared_path_ownership_and_preserves_existing_key(tmp_path: Path) -> None:
    scene = {
        "id": "32",
        "files": [{"path": "/shared.mp4"}],
        "custom_fields": {"plex_rating_key": "77"},
        "performers": [],
        "tags": [],
    }
    stash = MagicMock()
    stash.reconcile_scenes.return_value = [scene]
    videos = [
        _video(directors=["Example One"], locations=["/shared.mp4"], ratingKey="42"),
        _video(directors=["Example Two"], locations=["/shared.mp4"], ratingKey="43"),
    ]

    result, _ = _execute_reconcile(stash, videos, tmp_path)

    assert result == 0
    stash.update_scene.assert_not_called()
    stash.merge_scenes.assert_not_called()


def test_missing_key_path_blocks_valid_item_from_updating_scene(tmp_path: Path) -> None:
    scene = {
        "id": "33",
        "files": [{"path": "/shared.mp4"}],
        "custom_fields": {"plex_rating_key": "77"},
        "performers": [],
        "tags": [],
    }
    stash = MagicMock()
    stash.reconcile_scenes.return_value = [scene]
    videos = [
        _video(directors=["Example"], locations=["/shared.mp4"], ratingKey="42"),
        _video(directors=["Unknown"], locations=["/shared.mp4"], ratingKey=None),
    ]

    result, _ = _execute_reconcile(stash, videos, tmp_path)

    assert result == 0
    stash.update_scene.assert_not_called()


def test_merge_unions_compatible_custom_fields_and_writes_key(tmp_path: Path) -> None:
    destination = {
        "id": "34",
        "files": [{"path": "/merge-a.mp4"}],
        "custom_fields": {"review_note": "keep", "plex_rating_key": "1"},
        "performers": [],
        "tags": [],
    }
    source = {
        "id": "35",
        "files": [{"path": "/merge-b.mp4"}],
        "custom_fields": {"source_note": "also keep"},
        "performers": [],
        "tags": [],
    }
    stash = MagicMock()
    stash.reconcile_scenes.return_value = [destination, source]
    stash.reconcile_scene_by_id.side_effect = {"34": destination, "35": source}.get
    video = _video(directors=["Example"], locations=["/merge-a.mp4", "/merge-b.mp4"], ratingKey="42")

    result, _ = _execute_reconcile(stash, [video], tmp_path)

    assert result == 0
    merge_update = stash.merge_scenes.call_args.args[2]
    assert merge_update["custom_fields"] == {
        "partial": {"review_note": "keep", "source_note": "also keep", "plex_rating_key": "42"}
    }


def test_merge_custom_field_conflict_keeps_scenes_separate_but_sets_key(tmp_path: Path) -> None:
    destination = {
        "id": "36",
        "files": [{"path": "/conflict-a.mp4"}],
        "custom_fields": {"note": "first"},
        "performers": [],
        "tags": [],
    }
    source = {
        "id": "37",
        "files": [{"path": "/conflict-b.mp4"}],
        "custom_fields": {"note": "second"},
        "performers": [],
        "tags": [],
    }
    stash = MagicMock()
    stash.reconcile_scenes.return_value = [destination, source]
    stash.reconcile_scene_by_id.side_effect = {"36": destination, "37": source}.get
    video = _video(
        writers=["Example Writer"],
        directors=["Example"],
        locations=["/conflict-a.mp4", "/conflict-b.mp4"],
        ratingKey="42",
    )

    result, _ = _execute_reconcile(stash, [video], tmp_path)

    assert result == 0
    stash.merge_scenes.assert_not_called()
    stash.find_or_create_performer.assert_not_called()
    assert stash.update_scene.call_count == 2
    stash.update_scene.assert_any_call("36", {"custom_fields": {"partial": {"plex_rating_key": "42"}}})
    stash.update_scene.assert_any_call("37", {"custom_fields": {"partial": {"plex_rating_key": "42"}}})
