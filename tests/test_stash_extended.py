from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from plexadm.stash import StashClient


def test_gql_posts_payload_and_returns_data() -> None:
    client = StashClient("http://stash:9999/")
    response = MagicMock()
    response.json.return_value = {"data": {"value": 7}}
    client._session.post = MagicMock(return_value=response)  # type: ignore[method-assign]

    assert client.endpoint == "http://stash:9999/graphql"
    assert client._gql("query Example", {"id": "1"}) == {"value": 7}
    client._session.post.assert_called_once_with(
        "http://stash:9999/graphql", json={"query": "query Example", "variables": {"id": "1"}}, timeout=30
    )
    response.raise_for_status.assert_called_once_with()


def test_gql_omits_empty_variables_and_raises_graphql_errors() -> None:
    client = StashClient("http://stash:9999")
    response = MagicMock()
    response.json.return_value = {"errors": [{"message": "bad query"}]}
    client._session.post = MagicMock(return_value=response)  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="bad query"):
        client._gql("query Broken")
    assert client._session.post.call_args.kwargs["json"] == {"query": "query Broken"}


def test_all_scenes_pages_and_indexes_each_file() -> None:
    client = StashClient("http://stash:9999")
    scene_one = {"id": "1", "files": [{"path": "/one.mp4"}, {"path": "/one-alt.mp4"}]}
    scene_two = {"id": "2", "files": None}
    client._gql = MagicMock(  # type: ignore[method-assign]
        side_effect=[
            {"findScenes": {"count": 3, "scenes": [scene_one, scene_two]}},
            {"findScenes": {"count": 3, "scenes": []}},
        ]
    )

    assert client.all_scenes() == {"/one.mp4": scene_one, "/one-alt.mp4": scene_one}
    assert client._gql.call_args_list[1].args[1] == {"page": 2, "per_page": 200}


def test_all_scenes_stops_when_reported_count_is_reached() -> None:
    client = StashClient("http://stash:9999")
    scene = {"id": "1", "files": [{"path": "/one.mp4"}]}
    client._gql = MagicMock(return_value={"findScenes": {"count": 1, "scenes": [scene]}})  # type: ignore[method-assign]
    assert client.all_scenes() == {"/one.mp4": scene}
    client._gql.assert_called_once()


def test_tag_and_stash_box_listing() -> None:
    client = StashClient("http://stash:9999")
    client._gql = MagicMock(  # type: ignore[method-assign]
        side_effect=[
            {"allTags": [{"id": "4", "name": "Theme"}]},
            {"configuration": {"general": {"stashBoxes": [{"name": "Box", "endpoint": "https://box/graphql"}]}}},
        ]
    )
    assert client.all_tags() == [{"id": "4", "name": "Theme"}]
    assert client.configured_stash_boxes() == [{"name": "Box", "endpoint": "https://box/graphql"}]


@pytest.mark.parametrize(
    ("method", "cache_name", "find_key", "create_key"),
    [
        ("find_or_create_studio", "_studio_cache", "findStudios", "studioCreate"),
        ("find_or_create_tag", "_tag_cache", "findTags", "tagCreate"),
    ],
)
def test_find_or_create_entities_find_create_and_cache(
    method: str, cache_name: str, find_key: str, create_key: str
) -> None:
    client = StashClient("http://stash:9999")
    plural = "studios" if find_key == "findStudios" else "tags"
    client._gql = MagicMock(return_value={find_key: {plural: [{"id": "5"}]}})  # type: ignore[method-assign]
    assert getattr(client, method)("Example") == "5"
    assert getattr(client, cache_name)["Example"] == "5"

    getattr(client, cache_name).clear()
    client._gql = MagicMock(side_effect=[{find_key: {plural: []}}, {create_key: {"id": "9"}}])  # type: ignore[method-assign]
    assert getattr(client, method)("New Example") == "9"
    assert getattr(client, method)("New Example") == "9"
    assert client._gql.call_count == 2


def test_scene_tag_history_and_merge_mutations_preserve_inputs() -> None:
    client = StashClient("http://stash:9999")
    client._gql = MagicMock()  # type: ignore[method-assign]

    fields = {"title": "Updated"}
    client.update_scene("10", fields)
    assert fields == {"title": "Updated"}
    assert client._gql.call_args.args[1] == {"input": {"title": "Updated", "id": "10"}}

    client.rename_tag("4", "Renamed")
    assert client._gql.call_args.args[1] == {"input": {"id": "4", "name": "Renamed"}}

    client.sync_play_history("10", [])
    assert client._gql.call_args.args[1] == {"id": "10"}
    calls_before = client._gql.call_count
    client.sync_play_history("10", ["2026-01-01T00:00:00Z"])
    assert client._gql.call_count == calls_before + 2
    assert client._gql.call_args.args[1] == {"id": "10", "times": ["2026-01-01T00:00:00Z"]}

    merge_fields = {"title": "Merged"}
    client.merge_scenes(["11", "12"], "10", merge_fields)
    assert merge_fields == {"title": "Merged"}
    assert client._gql.call_args.args[1] == {
        "input": {
            "source": ["11", "12"],
            "destination": "10",
            "play_history": True,
            "values": {"title": "Merged", "id": "10"},
        }
    }
