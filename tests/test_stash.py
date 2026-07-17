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
