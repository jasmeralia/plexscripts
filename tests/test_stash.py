from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from plexadm.stash import StashClient


class TestScan:
    def test_scan_sends_phash_generation_by_default(self) -> None:
        client = StashClient("http://localhost:9999")
        client._gql = MagicMock(  # type: ignore[method-assign]
            side_effect=[
                {"metadataScan": "1"},
                {"findJob": {"id": "1", "status": "FINISHED", "error": None}},
            ]
        )
        client.scan(poll_interval=0)

        scan_call = client._gql.call_args_list[0]
        assert scan_call.args[1] == {"input": {"paths": [], "scanGeneratePhashes": True}}

    def test_scan_can_disable_phash_generation(self) -> None:
        client = StashClient("http://localhost:9999")
        client._gql = MagicMock(  # type: ignore[method-assign]
            side_effect=[
                {"metadataScan": "2"},
                {"findJob": {"id": "2", "status": "FINISHED", "error": None}},
            ]
        )
        client.scan(generate_phashes=False, poll_interval=0)

        scan_call = client._gql.call_args_list[0]
        assert scan_call.args[1] == {"input": {"paths": [], "scanGeneratePhashes": False}}

    def test_scan_passes_explicit_paths(self) -> None:
        client = StashClient("http://localhost:9999")
        client._gql = MagicMock(  # type: ignore[method-assign]
            side_effect=[
                {"metadataScan": "3"},
                {"findJob": {"id": "3", "status": "FINISHED", "error": None}},
            ]
        )
        client.scan(paths=["/data/NSFW Scenes"], poll_interval=0)

        scan_call = client._gql.call_args_list[0]
        assert scan_call.args[1]["input"]["paths"] == ["/data/NSFW Scenes"]


class TestClean:
    def test_clean_sends_mutation_and_waits_for_job(self) -> None:
        client = StashClient("http://localhost:9999")
        client._gql = MagicMock(  # type: ignore[method-assign]
            side_effect=[
                {"metadataClean": "4"},
                {"findJob": {"id": "4", "status": "FINISHED", "error": None}},
            ]
        )

        client.clean(poll_interval=0)

        assert client._gql.call_args_list[0].args[1] == {"input": {"dryRun": False}}
        assert client._gql.call_args_list[1].args[1] == {"id": "4"}


class TestReconcileSupport:
    def test_reconcile_scenes_uses_sorted_pages_and_keeps_custom_fields(self) -> None:
        client = StashClient("http://localhost:9999")
        client._gql = MagicMock(  # type: ignore[method-assign]
            return_value={
                "findScenes": {
                    "count": 1,
                    "scenes": [{"id": "7", "files": [{"path": "/a.mp4"}], "custom_fields": {"plex_rating_key": "4"}}],
                }
            }
        )
        scenes = client.reconcile_scenes()

        assert scenes[0]["custom_fields"] == {"plex_rating_key": "4"}
        query, variables = client._gql.call_args.args
        assert 'filter: { page: $page, per_page: $per_page, sort: "id", direction: ASC }' in query
        assert variables == {"page": 1, "per_page": 200}

    def test_reconcile_scenes_rejects_incomplete_page(self) -> None:
        client = StashClient("http://localhost:9999")
        client._gql = MagicMock(  # type: ignore[method-assign]
            return_value={"findScenes": {"count": 2, "scenes": [{"id": "1", "files": []}]}}
        )
        with pytest.raises(RuntimeError, match="ended early"):
            client.reconcile_scenes()

    def test_reconcile_capability_check_requires_custom_fields_and_merge(self) -> None:
        client = StashClient("http://localhost:9999")
        client._gql = MagicMock(  # type: ignore[method-assign]
            side_effect=[
                {
                    "scene": {"fields": [{"name": "custom_fields"}]},
                    "update": {
                        "inputFields": [
                            {"name": "custom_fields", "type": {"name": "CustomFieldsInput"}},
                        ]
                    },
                    "merge": {"inputFields": [{"name": "source"}, {"name": "destination"}, {"name": "values"}]},
                    "mergeValues": {"inputFields": [{"name": "custom_fields"}]},
                    "query": {
                        "fields": [
                            {
                                "name": "findScenes",
                                "args": [
                                    {"name": "filter", "type": {"name": "FindFilterType"}},
                                    {"name": "scene_filter", "type": {"name": "SceneFilterType"}},
                                ],
                            }
                        ]
                    },
                },
                {"input": {"kind": "INPUT_OBJECT", "inputFields": [{"name": "partial"}]}},
                {
                    "input": {
                        "kind": "INPUT_OBJECT",
                        "inputFields": [
                            {"name": "page"},
                            {"name": "per_page"},
                            {"name": "sort"},
                            {"name": "direction"},
                        ],
                    }
                },
                {
                    "input": {
                        "kind": "INPUT_OBJECT",
                        "inputFields": [{"name": "custom_fields", "type": {"name": "SceneCustomFieldFilter"}}],
                    }
                },
                {
                    "input": {
                        "kind": "INPUT_OBJECT",
                        "inputFields": [{"name": "field"}, {"name": "value"}, {"name": "modifier"}],
                    }
                },
            ]
        )
        client.check_reconcile_capabilities()
        assert client._gql.call_count == 5

    def test_scene_key_update_uses_partial_custom_fields(self) -> None:
        client = StashClient("http://localhost:9999")
        client._gql = MagicMock(return_value={"sceneUpdate": {"id": "7"}})  # type: ignore[method-assign]

        client.update_scene("7", {"custom_fields": {"partial": {"plex_rating_key": "42"}}})

        assert client._gql.call_args.args[1] == {
            "input": {"id": "7", "custom_fields": {"partial": {"plex_rating_key": "42"}}}
        }


class TestWaitForJob:
    def test_polls_until_finished(self) -> None:
        client = StashClient("http://localhost:9999")
        client._gql = MagicMock(  # type: ignore[method-assign]
            side_effect=[
                {"findJob": {"id": "1", "status": "RUNNING", "error": None}},
                {"findJob": {"id": "1", "status": "RUNNING", "error": None}},
                {"findJob": {"id": "1", "status": "FINISHED", "error": None}},
            ]
        )
        client._wait_for_job("1", timeout=10, poll_interval=0)
        assert client._gql.call_count == 3

    def test_raises_on_failed_status(self) -> None:
        client = StashClient("http://localhost:9999")
        client._gql = MagicMock(  # type: ignore[method-assign]
            return_value={"findJob": {"id": "1", "status": "FAILED", "error": "boom"}}
        )
        with pytest.raises(RuntimeError, match="FAILED.*boom"):
            client._wait_for_job("1", timeout=10, poll_interval=0)

    def test_raises_on_cancelled_status(self) -> None:
        client = StashClient("http://localhost:9999")
        client._gql = MagicMock(  # type: ignore[method-assign]
            return_value={"findJob": {"id": "1", "status": "CANCELLED", "error": None}}
        )
        with pytest.raises(RuntimeError, match="CANCELLED"):
            client._wait_for_job("1", timeout=10, poll_interval=0)

    def test_raises_timeout_error_when_deadline_exceeded(self) -> None:
        client = StashClient("http://localhost:9999")
        client._gql = MagicMock(  # type: ignore[method-assign]
            return_value={"findJob": {"id": "1", "status": "RUNNING", "error": None}}
        )
        with pytest.raises(TimeoutError):
            client._wait_for_job("1", timeout=0, poll_interval=0)
