from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from plexadm.stash_backfill_tags import (
    COMPOSITION_COLLECTIONS,
    _load_review,
    _plex_composition_tags,
    _stash_composition_tags,
    _tag_to_collection,
    _write_review,
    apply_review,
    backfill_tags,
    classify_scene,
)
from plexadm.stash_reconcile import _collection_to_tag


def _mock_video(**kwargs: object) -> SimpleNamespace:
    defaults: dict[str, object] = {
        "ratingKey": "42",
        "title": "Test Scene",
        "collections": [],
        "locations": ["/data/NSFW Scenes/Test/test.mp4"],
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestClassifyScene:
    def test_empty_stash_signal_returns_none(self) -> None:
        assert classify_scene(set(), {"Category: Solo"}) is None

    def test_clean_single_group_signal_adds_missing_tag(self) -> None:
        decision = classify_scene({"Category: Solo"}, set())

        assert decision is not None
        assert decision.adds == ["Category: Solo"]
        assert decision.remove_candidates == []
        assert decision.ambiguous_reason is None

    def test_solo_signal_flags_existing_lesbian_membership(self) -> None:
        decision = classify_scene(
            {"Category: Solo"},
            {"Category: Solo", "Category: Lesbian"},
        )

        assert decision is not None
        assert decision.adds == []
        assert decision.remove_candidates == ["Category: Lesbian"]
        assert decision.ambiguous_reason is None

    def test_ffm_and_lesbian_are_compatible(self) -> None:
        assert (
            classify_scene(
                {"Category: FFM", "Category: Lesbian"},
                {"Category: FFM", "Category: Lesbian"},
            )
            is None
        )

    def test_multiple_single_female_tags_are_ambiguous(self) -> None:
        decision = classify_scene({"Category: Solo", "Category: MF Only"}, set())

        assert decision is not None
        assert decision.adds == []
        assert decision.remove_candidates == []
        assert decision.ambiguous_reason == ("multiple single-female tags: ['Category: MF Only', 'Category: Solo']")

    def test_cross_axis_tags_are_ambiguous(self) -> None:
        decision = classify_scene({"Category: Solo", "Category: FFM"}, set())

        assert decision is not None
        assert decision.adds == []
        assert decision.remove_candidates == []
        assert decision.ambiguous_reason == "cross-axis: ['Category: Solo'] + ['Category: FFM']"

    def test_multiple_headcount_tags_are_ambiguous(self) -> None:
        decision = classify_scene({"Category: FFM", "Category: FFFM"}, set())

        assert decision is not None
        assert decision.ambiguous_reason == (
            "multiple multi-female headcount tags: ['Category: FFFM', 'Category: FFM']"
        )

    def test_matching_stash_and_plex_tags_return_none(self) -> None:
        assert classify_scene({"Category: MF Only"}, {"Category: MF Only"}) is None

    def test_lesbian_only_does_not_contradict_plex_headcount(self) -> None:
        decision = classify_scene({"Category: Lesbian"}, {"Category: FFM"})

        assert decision is not None
        assert decision.adds == ["Category: Lesbian"]
        assert decision.remove_candidates == []

    def test_headcount_signal_replaces_other_plex_headcount(self) -> None:
        decision = classify_scene({"Category: FFM"}, {"Category: FFFM"})

        assert decision is not None
        assert decision.adds == ["Category: FFM"]
        assert decision.remove_candidates == ["Category: FFFM"]


class TestTagCollectionMapping:
    def test_all_composition_collections_round_trip(self) -> None:
        for collection in COMPOSITION_COLLECTIONS:
            tag = _collection_to_tag(collection)
            assert tag is not None
            assert _tag_to_collection(tag) == collection

    def test_stash_tags_are_limited_to_composition_scope(self) -> None:
        scene = {
            "tags": [
                {"id": "1", "name": "Category: Solo"},
                {"id": "2", "name": "Category: Blowjob"},
            ]
        }

        assert _stash_composition_tags(scene) == {"Category: Solo"}

    def test_plex_collections_are_limited_to_composition_scope(self) -> None:
        video = _mock_video(collections=["01: Category: Solo", "01: Category: Blowjob", "99: LOCKED"])

        assert _plex_composition_tags(video) == {"Category: Solo"}


class TestReviewFileIO:
    def test_write_and_load_round_trip(self, tmp_path: Path) -> None:
        review_path = tmp_path / "nested" / "review.json"
        entries = [
            {
                "action": "remove_candidate",
                "rating_key": "42",
                "title": "Test Scene",
                "file_paths": ["/data/test.mp4"],
                "stash_tags": ["Category: Solo"],
                "plex_tags": ["01: Category: Lesbian", "01: Category: Solo"],
                "collection_to_remove": "01: Category: Lesbian",
                "reason": "contradiction",
                "status": "proposed",
            }
        ]

        _write_review(review_path, entries)
        loaded = _load_review(review_path)

        assert len(loaded) == 1
        assert loaded[0]["generated_at"].endswith("Z")
        assert {key: value for key, value in loaded[0].items() if key != "generated_at"} == entries[0]


class TestBackfillIntegration:
    def test_adds_are_applied_through_helper_with_dry_run(self, tmp_path: Path) -> None:
        path = "/data/NSFW Scenes/Test/test.mp4"
        video = _mock_video(locations=[path])
        scene = {
            "id": "7",
            "files": [{"path": path}],
            "tags": [{"id": "1", "name": "Category: Solo"}],
        }
        stash = MagicMock()
        stash.all_scenes.return_value = {path: scene}
        collection = SimpleNamespace(title="01: Category: Solo")
        plex_ctx = MagicMock()
        plex_ctx.all_videos.return_value = [video]
        plex_ctx.collection.return_value = collection
        args = SimpleNamespace(
            config="config.ini",
            dry_run=True,
            limit=None,
            path=None,
            log_level="WARNING",
            review_output=tmp_path / "review.json",
            stash_endpoint="http://stash:9999",
        )

        with (
            patch("plexadm.stash_backfill_tags.load_config", return_value=SimpleNamespace(stash_endpoint=None)),
            patch("plexadm.stash_backfill_tags.StashClient", return_value=stash),
            patch("plexadm.stash_backfill_tags.PlexContext", return_value=plex_ctx),
            patch("plexadm.stash_backfill_tags.add_items", return_value=1) as add_items,
        ):
            assert backfill_tags(args) == 0

        add_items.assert_called_once_with(collection, [video], dry_run=True)
        assert _load_review(args.review_output) == []

    def test_remove_candidates_are_only_written_to_review(self, tmp_path: Path) -> None:
        path = "/data/NSFW Scenes/Test/test.mp4"
        video = _mock_video(
            locations=[path],
            collections=["01: Category: Solo", "01: Category: Lesbian"],
        )
        scene = {
            "id": "7",
            "files": [{"path": path}],
            "tags": [{"id": "1", "name": "Category: Solo"}],
        }
        stash = MagicMock()
        stash.all_scenes.return_value = {path: scene}
        plex_ctx = MagicMock()
        plex_ctx.all_videos.return_value = [video]
        args = SimpleNamespace(
            config="config.ini",
            dry_run=False,
            limit=None,
            path=None,
            log_level="WARNING",
            review_output=tmp_path / "review.json",
            stash_endpoint="http://stash:9999",
        )

        with (
            patch("plexadm.stash_backfill_tags.load_config", return_value=SimpleNamespace(stash_endpoint=None)),
            patch("plexadm.stash_backfill_tags.StashClient", return_value=stash),
            patch("plexadm.stash_backfill_tags.PlexContext", return_value=plex_ctx),
            patch("plexadm.stash_backfill_tags.add_items") as add_items,
            patch("plexadm.stash_backfill_tags.remove_items") as remove_items,
        ):
            assert backfill_tags(args) == 0

        add_items.assert_not_called()
        remove_items.assert_not_called()
        review = _load_review(args.review_output)
        assert len(review) == 1
        assert review[0]["action"] == "remove_candidate"
        assert review[0]["collection_to_remove"] == "01: Category: Lesbian"

    def test_apply_review_uses_remove_helper_with_dry_run(self, tmp_path: Path) -> None:
        review_path = tmp_path / "review.json"
        _write_review(
            review_path,
            [
                {
                    "action": "remove_candidate",
                    "rating_key": "42",
                    "collection_to_remove": "01: Category: Lesbian",
                }
            ],
        )
        video = _mock_video(collections=["01: Category: Lesbian"])
        collection = SimpleNamespace(title="01: Category: Lesbian")
        plex_ctx = MagicMock()
        plex_ctx.all_videos.return_value = [video]
        plex_ctx.collection.return_value = collection
        args = SimpleNamespace(
            config="config.ini",
            dry_run=True,
            include_ambiguous=False,
            log_level="WARNING",
            review_file=review_path,
        )

        with (
            patch("plexadm.stash_backfill_tags.load_config", return_value=SimpleNamespace()),
            patch("plexadm.stash_backfill_tags.PlexContext", return_value=plex_ctx),
            patch("plexadm.stash_backfill_tags.remove_items", return_value=1) as remove_items,
        ):
            assert apply_review(args) == 0

        remove_items.assert_called_once_with(collection, [video], dry_run=True)

    def test_apply_review_skips_ambiguous_entries_by_default(self, tmp_path: Path) -> None:
        review_path = tmp_path / "review.json"
        _write_review(
            review_path,
            [
                {
                    "action": "ambiguous",
                    "rating_key": "42",
                    "collection_to_remove": "01: Category: Lesbian",
                }
            ],
        )
        plex_ctx = MagicMock()
        plex_ctx.all_videos.return_value = [_mock_video()]
        args = SimpleNamespace(
            config="config.ini",
            dry_run=False,
            include_ambiguous=False,
            log_level="WARNING",
            review_file=review_path,
        )

        with (
            patch("plexadm.stash_backfill_tags.load_config", return_value=SimpleNamespace()),
            patch("plexadm.stash_backfill_tags.PlexContext", return_value=plex_ctx),
            patch("plexadm.stash_backfill_tags.remove_items") as remove_items,
        ):
            assert apply_review(args) == 0

        remove_items.assert_not_called()
