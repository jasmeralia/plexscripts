from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from plexadm.config import InventoryConfig
from plexadm.inventory import _fetch_run_ids, diff_snapshots, take_snapshot


def _video(**kwargs: object) -> SimpleNamespace:
    defaults: dict[str, object] = {
        "title": "Test Video",
        "ratingKey": 1,
        "studio": None,
        "writers": [],
        "collections": [],
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestTakeSnapshot:
    def test_writes_one_document_per_video_with_full_collection_list(self) -> None:
        ctx = MagicMock()
        ctx.all_videos.return_value = [
            _video(
                title="A",
                ratingKey=1,
                studio="Independent Content",
                writers=["Alice"],
                collections=["01: Composition: Solo", "01: Theme: Cosplay"],
            ),
            _video(title="B", ratingKey=2, collections=[]),
        ]
        config = InventoryConfig(url="http://localhost:9200")

        with patch("plexadm.inventory._client"), patch("opensearchpy.helpers.bulk", return_value=(2, [])) as mock_bulk:
            count = take_snapshot(ctx, config)

        assert count == 2
        actions = mock_bulk.call_args.args[1]
        assert actions[0]["_index"] == "plexadm-inventory"
        assert actions[0]["_source"]["rating_key"] == 1
        assert actions[0]["_source"]["collections"] == ["01: Composition: Solo", "01: Theme: Cosplay"]
        assert actions[0]["_source"]["writers"] == ["Alice"]

    def test_dry_run_does_not_write(self) -> None:
        ctx = MagicMock()
        ctx.all_videos.return_value = [_video()]
        config = InventoryConfig(url="http://localhost:9200")

        with patch("opensearchpy.helpers.bulk") as mock_bulk:
            count = take_snapshot(ctx, config, dry_run=True)

        assert count == 1
        mock_bulk.assert_not_called()


class TestFetchRunIds:
    def test_reads_key_as_string_not_key(self) -> None:
        # Real bug found live: run_id is an ISO8601 string, but OpenSearch's dynamic mapping
        # date-detects it as a `date` field rather than text/keyword - so aggregation buckets
        # come back keyed by epoch-millis `key`, with the ISO string only in `key_as_string`.
        # Reading `key` directly against a real cluster silently returned a query that matched
        # nothing downstream, since real run_id values were never epoch-millis integers.
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "aggregations": {
                "runs": {
                    "buckets": [
                        {"key": 1784808910000, "key_as_string": "2026-07-23T12:15:10.000Z"},
                        {"key": 1784807643000, "key_as_string": "2026-07-23T11:54:03.000Z"},
                    ]
                }
            }
        }
        config = InventoryConfig(url="http://localhost:9200")

        with patch("plexadm.inventory._client", return_value=mock_client):
            run_ids = _fetch_run_ids(config)

        assert run_ids == ["2026-07-23T12:15:10.000Z", "2026-07-23T11:54:03.000Z"]


class TestDiffSnapshots:
    def test_reports_added_and_removed_collections_per_video(self) -> None:
        config = InventoryConfig(url="http://localhost:9200")
        older_docs = [{"_source": {"rating_key": 1, "title": "A", "collections": ["01: Composition: Solo"]}}]
        newer_docs = [
            {"_source": {"rating_key": 1, "title": "A", "collections": ["01: Composition: Solo", "01: Theme: Cosplay"]}}
        ]

        with (
            patch("plexadm.inventory._client"),
            patch("plexadm.inventory._fetch_run_ids", return_value=["run-b", "run-a"]),
            patch("opensearchpy.helpers.scan", side_effect=[older_docs, newer_docs]),
        ):
            run_a, run_b, changes = diff_snapshots(config)

        assert (run_a, run_b) == ("run-a", "run-b")
        assert len(changes) == 1
        assert changes[0].added == ["01: Theme: Cosplay"]
        assert changes[0].removed == []
        assert changes[0].attributed is True  # no audit_index given, so nothing to flag

    def test_flags_unattributed_change_when_no_matching_audit_event(self) -> None:
        config = InventoryConfig(url="http://localhost:9200")
        older_docs = [{"_source": {"rating_key": 1, "title": "A", "collections": []}}]
        newer_docs = [{"_source": {"rating_key": 1, "title": "A", "collections": ["01: Theme: Cosplay"]}}]

        mock_client = MagicMock()
        mock_client.search.return_value = {"hits": {"total": {"value": 0}}}

        with (
            patch("plexadm.inventory._client", return_value=mock_client),
            patch("opensearchpy.helpers.scan", side_effect=[older_docs, newer_docs]),
        ):
            _, _, changes = diff_snapshots(config, run_a="run-a", run_b="run-b", audit_index="plexadm-audit")

        assert changes[0].attributed is False

    def test_attributed_when_matching_audit_event_exists(self) -> None:
        config = InventoryConfig(url="http://localhost:9200")
        older_docs = [{"_source": {"rating_key": 1, "title": "A", "collections": []}}]
        newer_docs = [{"_source": {"rating_key": 1, "title": "A", "collections": ["01: Theme: Cosplay"]}}]

        mock_client = MagicMock()
        mock_client.search.return_value = {"hits": {"total": {"value": 1}}}

        with (
            patch("plexadm.inventory._client", return_value=mock_client),
            patch("opensearchpy.helpers.scan", side_effect=[older_docs, newer_docs]),
        ):
            _, _, changes = diff_snapshots(config, run_a="run-a", run_b="run-b", audit_index="plexadm-audit")

        assert changes[0].attributed is True

    def test_queries_bare_collection_field_not_a_nonexistent_keyword_subfield(self) -> None:
        # Real bug found live: plexadm-audit maps "collection" as `type: keyword` directly (see
        # plexadm.audit), not `text` with a `.keyword` multi-field. Querying "collection.keyword"
        # hits a field that doesn't exist - OpenSearch returns zero hits rather than erroring, so
        # every diffed change reported UNATTRIBUTED regardless of whether plexadm made it.
        # Confirmed live: 763 real "01: Hair: Blonde" add events were being reported as absent.
        config = InventoryConfig(url="http://localhost:9200")
        older_docs = [{"_source": {"rating_key": 1, "title": "A", "collections": []}}]
        newer_docs = [{"_source": {"rating_key": 1, "title": "A", "collections": ["01: Theme: Cosplay"]}}]

        mock_client = MagicMock()
        mock_client.search.return_value = {"hits": {"total": {"value": 1}}}

        with (
            patch("plexadm.inventory._client", return_value=mock_client),
            patch("opensearchpy.helpers.scan", side_effect=[older_docs, newer_docs]),
        ):
            diff_snapshots(config, run_a="run-a", run_b="run-b", audit_index="plexadm-audit")

        query_filters = mock_client.search.call_args.kwargs["body"]["query"]["bool"]["filter"]
        assert {"term": {"collection": "01: Theme: Cosplay"}} in query_filters
        assert not any("collection.keyword" in condition.get("term", {}) for condition in query_filters)
