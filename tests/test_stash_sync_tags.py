from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from plexadm import stash_sync_tags


def _collection(title: str, *, smart: bool = False, items: list[object] | None = None) -> SimpleNamespace:
    return SimpleNamespace(title=title, smart=smart, items=MagicMock(return_value=items or []))


def test_tag_name_removes_one_numeric_prefix() -> None:
    assert stash_sync_tags._tag_name("00B: Review Later") == "Review Later"
    assert stash_sync_tags._tag_name("Unprefixed") == "Unprefixed"


def test_sync_tags_requires_endpoint() -> None:
    args = SimpleNamespace(config=None, stash_endpoint=None, log_level="info")
    with (
        patch.object(stash_sync_tags, "load_logging_config"),
        patch.object(stash_sync_tags, "configure_command_logging"),
        patch.object(stash_sync_tags, "load_config", return_value=SimpleNamespace(stash_endpoint=None)),
        pytest.raises(ValueError, match="No Stash endpoint"),
    ):
        stash_sync_tags.sync_tags(args)


def test_sync_tags_filters_collections_and_updates_each_scene_once(
    capsys: pytest.CaptureFixture[str],
) -> None:
    scene_one = {"id": "1", "tags": [{"id": "old", "name": "Existing"}]}
    scene_two = {"id": "2", "tags": [{"id": "new", "name": "Review Later"}]}
    stash = MagicMock()
    stash.all_scenes.return_value = {
        "/matched.mp4": scene_one,
        "/matched-alt.mp4": scene_one,
        "/already.mp4": scene_two,
    }
    stash.find_or_create_tag.return_value = "new"

    item = SimpleNamespace(locations=["/missing.mp4", "/matched.mp4", "/matched-alt.mp4", "/already.mp4"])
    eligible = _collection("00B: Review Later", items=[item])
    collections = [
        _collection("Smart Collection", smart=True),
        _collection("00A: BROKEN"),
        _collection("01: Category: Excluded"),
        _collection("99: LOCKED"),
        eligible,
    ]
    plex = MagicMock()
    plex.section.collections.return_value = collections
    args = SimpleNamespace(config="config.ini", stash_endpoint="http://override:9999", log_level="info")

    with (
        patch.object(stash_sync_tags, "load_logging_config", return_value=MagicMock()),
        patch.object(stash_sync_tags, "configure_command_logging") as mock_logging,
        patch.object(stash_sync_tags, "load_config", return_value=SimpleNamespace(stash_endpoint="http://configured")),
        patch.object(stash_sync_tags, "StashClient", return_value=stash) as mock_client,
        patch.object(stash_sync_tags, "PlexContext", return_value=plex),
        patch.object(stash_sync_tags, "reload_if_partial") as mock_reload,
    ):
        assert stash_sync_tags.sync_tags(args) == 0

    mock_logging.assert_called_once()
    mock_client.assert_called_once_with("http://override:9999")
    stash.find_or_create_tag.assert_called_once_with("Review Later")
    assert stash.update_scene.call_count == 1
    assert stash.update_scene.call_args.args[0] == "1"
    assert set(stash.update_scene.call_args.args[1]["tag_ids"]) == {"new", "old"}
    assert scene_one["tags"][-1] == {"id": "new", "name": "Review Later"}
    assert mock_reload.call_count == len(collections) + 1
    output = capsys.readouterr().out
    assert "2 scenes across 3 paths" in output
    assert "'Review Later': 1 scenes tagged" in output
    assert "Total scenes tagged: 1" in output
