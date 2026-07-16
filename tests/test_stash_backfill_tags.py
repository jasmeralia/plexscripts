from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from plexadm.stash import StashClient
from plexadm.stash_backfill_tags import (
    COMPOSITION_COLLECTIONS,
    COMPOSITION_TAGS,
    _has_existing_plex_match,
    _load_review,
    _plex_tags_in_scope,
    _stash_tags_in_scope,
    _suggest_new_collection_name,
    _suggested_action,
    _tag_source,
    _tag_to_collection,
    _write_review,
    apply_review,
    backfill_tags,
    classify_scene,
    unmapped_tags,
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

        assert _stash_tags_in_scope(scene, COMPOSITION_TAGS) == {"Category: Solo"}

    def test_plex_collections_are_limited_to_composition_scope(self) -> None:
        video = _mock_video(collections=["01: Category: Solo", "01: Category: Blowjob", "99: LOCKED"])

        assert _plex_tags_in_scope(video, COMPOSITION_TAGS) == {"Category: Solo"}


class TestHairBackfill:
    def test_adds_only_missing_hair_tags_with_dry_run(self, tmp_path: Path) -> None:
        path = "/data/NSFW Scenes/Test/test.mp4"
        video = _mock_video(locations=[path], collections=["01: Hair: Red"])
        scene = {
            "id": "7",
            "files": [{"path": path}],
            "tags": [
                {"id": "1", "name": "Hair: Red"},
                {"id": "2", "name": "Hair: Blonde"},
            ],
        }
        stash = MagicMock()
        stash.all_scenes.return_value = {path: scene}
        collection = SimpleNamespace(title="01: Hair: Blonde")
        plex_ctx = MagicMock()
        plex_ctx.all_videos.return_value = [video]
        plex_ctx.collection.return_value = collection
        args = SimpleNamespace(
            config="config.ini",
            dry_run=True,
            limit=None,
            path=None,
            log_level="WARNING",
            report_output=tmp_path / "report.md",
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
        plex_ctx.collection.assert_called_once_with("01: Hair: Blonde")
        assert _load_review(args.review_output) == []

    def test_matching_hair_tags_do_not_add_memberships(self, tmp_path: Path) -> None:
        path = "/data/NSFW Scenes/Test/test.mp4"
        video = _mock_video(locations=[path], collections=["01: Hair: Red"])
        scene = {
            "id": "7",
            "files": [{"path": path}],
            "tags": [{"id": "1", "name": "Hair: Red"}],
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
            report_output=tmp_path / "report.md",
            review_output=tmp_path / "review.json",
            stash_endpoint="http://stash:9999",
        )

        with (
            patch("plexadm.stash_backfill_tags.load_config", return_value=SimpleNamespace(stash_endpoint=None)),
            patch("plexadm.stash_backfill_tags.StashClient", return_value=stash),
            patch("plexadm.stash_backfill_tags.PlexContext", return_value=plex_ctx),
            patch("plexadm.stash_backfill_tags.add_items") as add_items,
        ):
            assert backfill_tags(args) == 0

        add_items.assert_not_called()
        assert _load_review(args.review_output) == []


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


class TestStashClientAllTags:
    def test_returns_all_tags_from_graphql(self) -> None:
        tags = [{"id": "1", "name": "Category: Solo", "scene_count": 12, "stash_ids": []}]
        client = StashClient("http://stash:9999")

        with patch.object(client, "_gql", return_value={"allTags": tags}) as gql:
            assert client.all_tags() == tags

        gql.assert_called_once()
        assert "stash_ids" in gql.call_args.args[0]

    def test_configured_stash_boxes_returns_name_and_endpoint(self) -> None:
        boxes = [{"name": "StashDB", "endpoint": "https://stashdb.org/graphql"}]
        client = StashClient("http://stash:9999")

        with patch.object(client, "_gql", return_value={"configuration": {"general": {"stashBoxes": boxes}}}) as gql:
            assert client.configured_stash_boxes() == boxes

        gql.assert_called_once()


class TestHasExistingPlexMatch:
    def test_direct_match_via_category_prefix(self) -> None:
        tag = {"name": "Category: Solo", "stash_ids": []}
        assert _has_existing_plex_match(tag, {"01: Category: Solo"}) is True

    def test_category_prefixed_tag_with_no_match_is_not_broadened(self) -> None:
        tag = {"name": "Category: Blowjob", "stash_ids": []}
        assert _has_existing_plex_match(tag, {"01: Category: Fingering"}) is False

    def test_unprefixed_stash_box_tag_matches_existing_category_collection(self) -> None:
        tag = {"name": "Fingering", "stash_ids": [{"endpoint": "https://stashdb.org/graphql", "stash_id": "x"}]}
        assert _has_existing_plex_match(tag, {"01: Category: Fingering"}) is True

    def test_unprefixed_stash_box_tag_matches_existing_hair_collection(self) -> None:
        tag = {"name": "Red", "stash_ids": [{"endpoint": "https://stashdb.org/graphql", "stash_id": "x"}]}
        assert _has_existing_plex_match(tag, {"01: Hair: Red"}) is True

    def test_unprefixed_stash_box_tag_with_no_match_stays_unmapped(self) -> None:
        tag = {"name": "Masturbation", "stash_ids": [{"endpoint": "https://stashdb.org/graphql", "stash_id": "x"}]}
        assert _has_existing_plex_match(tag, {"01: Category: Fingering"}) is False

    def test_local_unprefixed_tag_does_not_get_the_broader_check(self) -> None:
        # "FAVORITES" is local and really does map to "00A: FAVORITES" in Plex, but that's a
        # different prefix family this check deliberately doesn't attempt to cover.
        tag = {"name": "FAVORITES", "stash_ids": []}
        assert _has_existing_plex_match(tag, {"01: Category: FAVORITES", "00A: FAVORITES"}) is False


class TestSuggestedAction:
    def test_recommends_merge_when_hair_keyword_matches_existing_collection(self) -> None:
        assert _suggested_action("Red Hair (Male)", {"01: Hair: Red"}) == "merge -> 01: Hair: Red"

    def test_matches_word_regardless_of_position_or_case(self) -> None:
        assert _suggested_action("Natural Blonde Hair Bombshell", {"01: Hair: Blonde"}) == "merge -> 01: Hair: Blonde"

    def test_color_word_alone_without_hair_context_does_not_merge(self) -> None:
        # Real false positives found on a live run before this requirement was added: color
        # words alone match plenty of tags that have nothing to do with hair. "White Woman" is
        # excluded here since it's since been added to _SKIP_EXACT_TAG_NAMES (ethnicity, not
        # hair) - covered instead by TestSkipSignals.
        targets = {
            "01: Hair: Blue",
            "01: Hair: Brunette",
            "01: Hair: Pink",
            "01: Hair: Red",
        }
        for tag_name in ("Blue Eyes", "Brown Eyes", "Pink Labia", "Red Lipstick"):
            assert _suggested_action(tag_name, targets) == "add"

    def test_redhead_is_caught_via_the_curated_phrase_list(self) -> None:
        # Unlike the generic whole-word hair heuristic, "Redhead"/"Red head" are explicitly
        # curated in _CATEGORY_MERGE_PHRASES - confirmed by scripts/set_tags_based_on_title.sh's
        # own already-validated title-matching rule, not guessed.
        assert _suggested_action("Redhead", {"01: Hair: Red"}) == "merge -> 01: Hair: Red"
        assert _suggested_action("Red head", {"01: Hair: Red"}) == "merge -> 01: Hair: Red"

    def test_does_not_catch_fused_compounds_outside_the_curated_phrase_list(self) -> None:
        # "Blackhair" is one token with no word boundary before "hair" and isn't in the curated
        # phrase list - catching it generically would require substring matching that produces
        # real false positives elsewhere (e.g. "Hundred" contains "red").
        assert _suggested_action("Blackhair", {"01: Hair: Black"}) == "add"

    def test_does_not_recommend_merge_when_target_collection_does_not_exist(self) -> None:
        assert _suggested_action("Redhead", set()) == "add"

    def test_does_not_false_positive_on_substring_only_match(self) -> None:
        # "Chair" contains "hair" as a substring but not "red"/"blue"/etc. as a whole word.
        assert _suggested_action("Chair", {"01: Hair: Red"}) == "add"

    def test_recommends_skip_for_technical_metadata_tags(self) -> None:
        assert _suggested_action("4K Available", set()) == "skip"
        assert _suggested_action("60 FPS", set()) == "skip"

    def test_skip_takes_priority_over_merge(self) -> None:
        assert _suggested_action("4K Red Something", {"01: Hair: Red"}) == "skip"

    def test_defaults_to_add_for_ordinary_tags(self) -> None:
        assert _suggested_action("Masturbation", {"01: Hair: Red"}) == "add"

    def test_category_merge_phrase_requires_target_to_exist(self) -> None:
        assert _suggested_action("Blackmail Fantasy", set()) == "add"
        assert _suggested_action("Blackmail Fantasy", {"01: Category: Blackmail"}) == "merge -> 01: Category: Blackmail"

    def test_pussy_licking_merges_into_pussy_eating(self) -> None:
        assert (
            _suggested_action("Pussy Licking", {"01: Category: Pussy Eating"}) == "merge -> 01: Category: Pussy Eating"
        )
        # Variants of the same act are also caught by the phrase match.
        assert (
            _suggested_action("Standing Pussy Licking", {"01: Category: Pussy Eating"})
            == "merge -> 01: Category: Pussy Eating"
        )

    def test_cum_on_pussy_merges_into_cum_on_vagina(self) -> None:
        assert (
            _suggested_action("Cum on Pussy", {"01: Category: Cum On Vagina"}) == "merge -> 01: Category: Cum On Vagina"
        )

    def test_threesome_bbg_merges_into_mmf(self) -> None:
        assert _suggested_action("Threesome (BBG)", {"01: Category: MMF"}) == "merge -> 01: Category: MMF"

    def test_open_mouth_facial_merges_into_both_targets(self) -> None:
        targets = {"01: Category: Cum In Mouth", "01: Category: Facial"}
        assert (
            _suggested_action("Open Mouth Facial", targets)
            == "merge -> 01: Category: Cum In Mouth + 01: Category: Facial"
        )

    def test_open_mouth_facial_requires_both_targets_to_exist(self) -> None:
        assert _suggested_action("Open Mouth Facial", {"01: Category: Facial"}) == "add"


class TestSkipSignals:
    def test_exact_tag_names_are_skipped(self) -> None:
        for tag_name in ("Hardcore", "Indoors", "European", "White Woman", "Bed", "Russian", "Gonzo", "Exclusive"):
            assert _suggested_action(tag_name, set()) == "skip"

    def test_exact_skip_does_not_catch_more_specific_variants(self) -> None:
        # "Cumshot"/"Threesome" alone are too broad to be useful, but specific variants are not.
        assert _suggested_action("Cumshot", set()) == "skip"
        assert _suggested_action("Massive Cumshot", set()) == "add"
        assert _suggested_action("Threesome", set()) == "skip"
        assert _suggested_action("Threesome (GTT)", set()) == "add"

    def test_generic_body_descriptor_words_are_skipped(self) -> None:
        for tag_name in ("Slim", "Medium Ass", "Athletic Woman", "Average Height Man", "Medium Hair"):
            assert _suggested_action(tag_name, set()) == "skip"


class TestTagSource:
    def test_local_tag_has_no_stash_ids(self) -> None:
        assert _tag_source({"name": "FAVORITES", "stash_ids": []}, {}) == "local"

    def test_resolves_configured_stash_box_name(self) -> None:
        tag = {"name": "Big Tits", "stash_ids": [{"endpoint": "https://stashdb.org/graphql", "stash_id": "x"}]}
        assert _tag_source(tag, {"https://stashdb.org/graphql": "StashDB"}) == "StashDB"

    def test_falls_back_to_raw_endpoint_for_unconfigured_box(self) -> None:
        tag = {"name": "Old Tag", "stash_ids": [{"endpoint": "https://retired.example/graphql", "stash_id": "x"}]}
        assert _tag_source(tag, {}) == "https://retired.example/graphql"


class TestSuggestNewCollectionName:
    def test_cumshot_keyword(self) -> None:
        assert _suggest_new_collection_name("Creampie Surprise") == "01: Cumshot: Creampie Surprise"

    def test_composition_keyword(self) -> None:
        assert _suggest_new_collection_name("Backyard Gangbang") == "01: Composition: Backyard Gangbang"

    def test_prop_keyword(self) -> None:
        assert _suggest_new_collection_name("Pink Dildo") == "01: Prop: Pink Dildo"

    def test_prop_keyword_covers_worn_fetish_attire_and_bondage_gear(self) -> None:
        for tag_name in ("Black Stockings", "Woman's Heels", "Handcuffs", "Sybian", "Gags"):
            assert _suggest_new_collection_name(tag_name).startswith("01: Prop: ")

    def test_activity_keyword(self) -> None:
        assert _suggest_new_collection_name("Rough Anal") == "01: Activity: Rough Anal"

    def test_theme_keyword(self) -> None:
        assert _suggest_new_collection_name("Hot Cosplay") == "01: Theme: Hot Cosplay"

    def test_falls_back_to_category_when_no_keyword_matches(self) -> None:
        assert _suggest_new_collection_name("Masturbation") == "01: Category: Masturbation"

    def test_cumshot_takes_priority_over_other_matches(self) -> None:
        # Contains both a cumshot word ("creampie") and a composition word ("gangbang").
        assert _suggest_new_collection_name("Gangbang Creampie") == "01: Cumshot: Gangbang Creampie"


class TestUnmappedTags:
    def test_unprefixed_tag_covered_by_a_differently_named_stash_tag_is_excluded(self, tmp_path: Path) -> None:
        tags = [
            {
                "id": "1",
                "name": "Fingering",
                "scene_count": 132,
                "stash_ids": [{"endpoint": "https://stashdb.org/graphql", "stash_id": "x"}],
            },
            {
                "id": "2",
                "name": "Category: Fingering",
                "scene_count": 578,
                "stash_ids": [],
            },
        ]
        stash = MagicMock()
        stash.all_tags.return_value = tags
        stash.configured_stash_boxes.return_value = [{"name": "StashDB", "endpoint": "https://stashdb.org/graphql"}]
        plex_ctx = MagicMock()
        plex_ctx.section.collections.return_value = [SimpleNamespace(title="01: Category: Fingering")]
        output = tmp_path / "unmapped.md"
        args = SimpleNamespace(
            config="config.ini",
            log_level="WARNING",
            output=output,
            stash_endpoint="http://stash:9999",
        )

        with (
            patch("plexadm.stash_backfill_tags.load_config", return_value=SimpleNamespace(stash_endpoint=None)),
            patch("plexadm.stash_backfill_tags.StashClient", return_value=stash),
            patch("plexadm.stash_backfill_tags.PlexContext", return_value=plex_ctx),
        ):
            assert unmapped_tags(args) == 0

        report = output.read_text(encoding="utf-8")
        assert "Found 0 unmapped tags out of 2 total Stash tags" in report
        assert "| 132 | Fingering |" not in report
        assert "| 578 | Category: Fingering |" not in report

    def test_local_tags_are_excluded_entirely(self, tmp_path: Path) -> None:
        tags = [
            {"id": "1", "name": "FAVORITES", "scene_count": 684, "stash_ids": []},
            {
                "id": "2",
                "name": "Big Tits",
                "scene_count": 5,
                "stash_ids": [{"endpoint": "https://stashdb.org/graphql", "stash_id": "abc"}],
            },
        ]
        stash = MagicMock()
        stash.all_tags.return_value = tags
        stash.configured_stash_boxes.return_value = [{"name": "StashDB", "endpoint": "https://stashdb.org/graphql"}]
        plex_ctx = MagicMock()
        plex_ctx.section.collections.return_value = []
        output = tmp_path / "unmapped.md"
        args = SimpleNamespace(
            config="config.ini",
            log_level="WARNING",
            output=output,
            stash_endpoint="http://stash:9999",
        )

        with (
            patch("plexadm.stash_backfill_tags.load_config", return_value=SimpleNamespace(stash_endpoint=None)),
            patch("plexadm.stash_backfill_tags.StashClient", return_value=stash),
            patch("plexadm.stash_backfill_tags.PlexContext", return_value=plex_ctx),
        ):
            assert unmapped_tags(args) == 0

        report = output.read_text(encoding="utf-8")
        assert "Found 1 unmapped tags out of 2 total Stash tags (1 local tags excluded" in report
        assert "FAVORITES" not in report
        assert "Big Tits" in report

    def test_reports_real_collection_gaps_sorted_by_scene_count(self, tmp_path: Path) -> None:
        tags = [
            {
                "id": "1",
                "name": "Category: Solo",
                "scene_count": 30,
                "stash_ids": [{"endpoint": "https://stashdb.org/graphql", "stash_id": "x"}],
            },
            {
                "id": "2",
                "name": "Category: Blowjob",
                "scene_count": 20,
                "stash_ids": [{"endpoint": "https://stashdb.org/graphql", "stash_id": "y"}],
            },
            {
                "id": "3",
                "name": "Free | Text",
                "scene_count": 40,
                "stash_ids": [{"endpoint": "https://stashdb.org/graphql", "stash_id": "z"}],
            },
        ]
        stash = MagicMock()
        stash.all_tags.return_value = tags
        stash.configured_stash_boxes.return_value = [{"name": "StashDB", "endpoint": "https://stashdb.org/graphql"}]
        plex_ctx = MagicMock()
        plex_ctx.section.collections.return_value = [
            SimpleNamespace(title="01: Category: Solo"),
            SimpleNamespace(title="01: Existing Manual Tag"),
        ]
        output = tmp_path / "nested" / "unmapped.md"
        args = SimpleNamespace(
            config="config.ini",
            log_level="WARNING",
            output=output,
            stash_endpoint="https://stash.example.test/graphql",
        )

        with (
            patch("plexadm.stash_backfill_tags.load_config", return_value=SimpleNamespace(stash_endpoint=None)),
            patch("plexadm.stash_backfill_tags.StashClient", return_value=stash),
            patch("plexadm.stash_backfill_tags.PlexContext", return_value=plex_ctx),
        ):
            assert unmapped_tags(args) == 0

        report = output.read_text(encoding="utf-8")
        assert "Found 2 unmapped tags out of 3 total Stash tags" in report
        assert "| 30 | Category: Solo |" not in report
        # Both remaining tags land in the "Add" section, sorted by scene count descending.
        assert report.index("Free \\| Text") < report.index("Category: Blowjob")
        assert "[view](https://stash.example.test/tags/3)" in report
        assert "[view](https://stash.example.test/tags/2)" in report
        assert "/graphql/tags/" not in report

    def test_source_column_distinguishes_stash_box_tags(self, tmp_path: Path) -> None:
        tags = [
            {
                "id": "2",
                "name": "Big Tits",
                "scene_count": 5,
                "stash_ids": [{"endpoint": "https://stashdb.org/graphql", "stash_id": "abc"}],
            },
            {
                "id": "3",
                "name": "Some Retired Box Tag",
                "scene_count": 1,
                "stash_ids": [{"endpoint": "https://retired-box.example/graphql", "stash_id": "xyz"}],
            },
        ]
        stash = MagicMock()
        stash.all_tags.return_value = tags
        stash.configured_stash_boxes.return_value = [{"name": "StashDB", "endpoint": "https://stashdb.org/graphql"}]
        plex_ctx = MagicMock()
        plex_ctx.section.collections.return_value = []
        output = tmp_path / "unmapped.md"
        args = SimpleNamespace(
            config="config.ini",
            log_level="WARNING",
            output=output,
            stash_endpoint="http://stash:9999",
        )

        with (
            patch("plexadm.stash_backfill_tags.load_config", return_value=SimpleNamespace(stash_endpoint=None)),
            patch("plexadm.stash_backfill_tags.StashClient", return_value=stash),
            patch("plexadm.stash_backfill_tags.PlexContext", return_value=plex_ctx),
        ):
            assert unmapped_tags(args) == 0

        report = output.read_text(encoding="utf-8")
        assert "| 5 | Big Tits | StashDB | " in report
        assert "| 1 | Some Retired Box Tag | https://retired-box.example/graphql | " in report
        assert "| 5 | Big Tits | StashDB | " in report
        assert "| 1 | Some Retired Box Tag | https://retired-box.example/graphql | " in report


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
            report_output=tmp_path / "report.md",
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
        report = args.report_output.read_text(encoding="utf-8")
        assert "Mode: DRY RUN (no Plex changes made)" in report
        assert "| 01: Category: Solo | 1 |" in report
        assert "_No ambiguous scenes this run._" in report

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
            report_output=tmp_path / "report.md",
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
        report = args.report_output.read_text(encoding="utf-8")
        assert "Mode: APPLIED" in report
        assert "## Composition additions by collection" not in report
        assert "## Hair additions by collection" not in report

    def test_ambiguous_scene_is_in_markdown_report(self, tmp_path: Path) -> None:
        path = "/data/NSFW Scenes/Test/test.mp4"
        video = _mock_video(title="Scene | One", locations=[path])
        scene = {
            "id": "7",
            "files": [{"path": path}],
            "tags": [
                {"id": "1", "name": "Category: Solo"},
                {"id": "2", "name": "Category: FFM"},
            ],
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
            report_output=tmp_path / "report.md",
            review_output=tmp_path / "review.json",
            stash_endpoint="http://stash:9999",
        )

        with (
            patch("plexadm.stash_backfill_tags.load_config", return_value=SimpleNamespace(stash_endpoint=None)),
            patch("plexadm.stash_backfill_tags.StashClient", return_value=stash),
            patch("plexadm.stash_backfill_tags.PlexContext", return_value=plex_ctx),
            patch("plexadm.stash_backfill_tags.add_items") as add_items,
        ):
            assert backfill_tags(args) == 0

        add_items.assert_not_called()
        report = args.report_output.read_text(encoding="utf-8")
        assert "| Title | Reason |" in report
        assert "| Scene \\| One | cross-axis: ['Category: Solo'] + ['Category: FFM'] |" in report
        assert "Ambiguous matches staged for review: 1" in report

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
