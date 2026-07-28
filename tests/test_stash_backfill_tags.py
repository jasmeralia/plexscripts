from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from plexadm.stash import StashClient
from plexadm.stash_backfill_tags import (
    _COMPOSITION_TAG_RENAMES,
    _EXISTING_CATEGORY_RENAMES,
    COMPOSITION_COLLECTIONS,
    COMPOSITION_TAGS,
    _apply_targets,
    _has_existing_plex_match,
    _load_review,
    _plex_tags_in_scope,
    _potential_merge_targets,
    _resolve_existing,
    _resolved_merge_targets,
    _stash_tags_in_scope,
    _suggest_new_collection_name,
    _suggested_action,
    _tag_source,
    _tag_to_collection,
    _tagalong_targets,
    _with_tagalong,
    _write_review,
    apply_review,
    backfill_tags,
    classify_scene,
    rename_tags,
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
        assert classify_scene(set(), {"Composition: Solo"}) is None

    def test_clean_single_group_signal_adds_missing_tag(self) -> None:
        decision = classify_scene({"Composition: Solo"}, set())

        assert decision is not None
        assert decision.adds == ["Composition: Solo"]
        assert decision.remove_candidates == []
        assert decision.ambiguous_reason is None

    def test_solo_signal_flags_existing_lesbian_membership(self) -> None:
        decision = classify_scene(
            {"Composition: Solo"},
            {"Composition: Solo", "Composition: Lesbian"},
        )

        assert decision is not None
        assert decision.adds == []
        assert decision.remove_candidates == ["Composition: Lesbian"]
        assert decision.ambiguous_reason is None

    def test_ffm_and_lesbian_are_compatible(self) -> None:
        assert (
            classify_scene(
                {"Composition: FFM", "Composition: Lesbian"},
                {"Composition: FFM", "Composition: Lesbian"},
            )
            is None
        )

    def test_multiple_single_female_tags_are_ambiguous(self) -> None:
        decision = classify_scene({"Composition: Solo", "Composition: MF Only"}, set())

        assert decision is not None
        assert decision.adds == []
        assert decision.remove_candidates == []
        assert decision.ambiguous_reason == (
            "multiple single-female tags: ['Composition: MF Only', 'Composition: Solo']"
        )

    def test_cross_axis_tags_are_ambiguous(self) -> None:
        decision = classify_scene({"Composition: Solo", "Composition: FFM"}, set())

        assert decision is not None
        assert decision.adds == []
        assert decision.remove_candidates == []
        assert decision.ambiguous_reason == "cross-axis: ['Composition: Solo'] + ['Composition: FFM']"

    def test_multiple_headcount_tags_are_ambiguous(self) -> None:
        decision = classify_scene({"Composition: FFM", "Composition: FFFM"}, set())

        assert decision is not None
        assert decision.ambiguous_reason == (
            "multiple multi-female headcount tags: ['Composition: FFFM', 'Composition: FFM']"
        )

    def test_matching_stash_and_plex_tags_return_none(self) -> None:
        assert classify_scene({"Composition: MF Only"}, {"Composition: MF Only"}) is None

    def test_lesbian_only_does_not_contradict_plex_headcount(self) -> None:
        decision = classify_scene({"Composition: Lesbian"}, {"Composition: FFM"})

        assert decision is not None
        assert decision.adds == ["Composition: Lesbian"]
        assert decision.remove_candidates == []

    def test_headcount_signal_replaces_other_plex_headcount(self) -> None:
        decision = classify_scene({"Composition: FFM"}, {"Composition: FFFM"})

        assert decision is not None
        assert decision.adds == ["Composition: FFM"]
        assert decision.remove_candidates == ["Composition: FFFM"]


class TestTagCollectionMapping:
    def test_all_composition_collections_round_trip(self) -> None:
        for collection in COMPOSITION_COLLECTIONS:
            tag = _collection_to_tag(collection)
            assert tag is not None
            assert _tag_to_collection(tag) == collection

    def test_stash_tags_are_limited_to_composition_scope(self) -> None:
        scene = {
            "tags": [
                {"id": "1", "name": "Composition: Solo"},
                {"id": "2", "name": "Category: Blowjob"},
            ]
        }

        assert _stash_tags_in_scope(scene, COMPOSITION_TAGS) == {"Composition: Solo"}

    def test_plex_collections_are_limited_to_composition_scope(self) -> None:
        video = _mock_video(collections=["01: Composition: Solo", "01: Category: Blowjob", "99: LOCKED"])

        assert _plex_tags_in_scope(video, COMPOSITION_TAGS) == {"Composition: Solo"}


class TestCompositionTagRenames:
    def test_covers_exactly_the_composition_tags_classify_scene_reads(self) -> None:
        # Derived from _EXISTING_CATEGORY_RENAMES, restricted by the *new* name landing in
        # COMPOSITION_TAGS - must never drift from the set classify_scene() actually intersects
        # against.
        assert set(_COMPOSITION_TAG_RENAMES.values()) == COMPOSITION_TAGS

    def test_excludes_composition_collections_outside_classify_scene_scope(self) -> None:
        # FFT and Orgy are deferred alongside the real composition tags in
        # EXCLUDED_COMPOSITION_COLLECTIONS, but classify_scene() never reads them, so they don't
        # need a Stash tag rename.
        assert "Category: FFT" not in _COMPOSITION_TAG_RENAMES
        assert "Category: Orgy" not in _COMPOSITION_TAG_RENAMES

    def test_maps_to_the_composition_prefix(self) -> None:
        assert _COMPOSITION_TAG_RENAMES["Category: Solo"] == "Composition: Solo"
        assert _COMPOSITION_TAG_RENAMES["Category: Lesbian"] == "Composition: Lesbian"


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
        stash.all_tags.return_value = []
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
        stash.all_tags.return_value = []
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

    def test_rename_tag_sends_id_and_new_name(self) -> None:
        client = StashClient("http://stash:9999")

        with patch.object(client, "_gql", return_value={"tagUpdate": {"id": "1", "name": "Composition: Solo"}}) as gql:
            client.rename_tag("1", "Composition: Solo")

        gql.assert_called_once()
        assert gql.call_args.args[1] == {"input": {"id": "1", "name": "Composition: Solo"}}


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

    def test_broader_check_is_case_insensitive(self) -> None:
        # Real gap found on a live run: "Cum on Hands" only differed from the actual collection
        # "01: Category: Cum On Hands" by case.
        tag = {"name": "Cum on Hands", "stash_ids": [{"endpoint": "https://stashdb.org/graphql", "stash_id": "x"}]}
        assert _has_existing_plex_match(tag, {"01: Category: Cum On Hands"}) is True

    def test_direct_match_survives_rename_categories(self) -> None:
        # Real regression found right after running `rename-categories` for real: a Stash tag
        # that used to match "01: Category: Anal" directly wrongly started reporting as
        # unmapped once that collection was actually renamed to "01: Activity: Anal".
        tag = {"name": "Category: Anal", "stash_ids": []}
        assert _has_existing_plex_match(tag, {"01: Activity: Anal"}) is True

    def test_broader_check_survives_rename_categories(self) -> None:
        tag = {"name": "Facial", "stash_ids": [{"endpoint": "https://stashdb.org/graphql", "stash_id": "x"}]}
        assert _has_existing_plex_match(tag, {"01: Cumshot: Facial"}) is True


class TestResolveExisting:
    def test_returns_the_name_itself_when_already_real(self) -> None:
        assert _resolve_existing("01: Category: Anal", {"01: Category: Anal"}) == "01: Category: Anal"

    def test_returns_the_renamed_form_when_that_is_what_is_real(self) -> None:
        assert _resolve_existing("01: Category: Anal", {"01: Activity: Anal"}) == "01: Activity: Anal"

    def test_returns_none_when_neither_form_exists(self) -> None:
        assert _resolve_existing("01: Category: Anal", set()) is None

    def test_returns_none_for_a_name_with_no_rename_entry_at_all(self) -> None:
        # "01: Theme: POV" was never a "01: Category:" collection - not in the renames table.
        assert _resolve_existing("01: Theme: POV", set()) is None


class TestAcceptedCumshotAndThemeSuggestions:
    def test_accepted_suggestions_merge_once_the_collection_is_real(self) -> None:
        # Confirmed by direct user request ("Accept the cumshot and theme add suggestions"):
        # these were plain generic-keyword suggestions with no merge rule at all until wired up
        # explicitly - otherwise creating the real collection wouldn't stop the report from
        # suggesting "add" forever.
        for tag_name, target in (
            ("Male - POV", "01: Theme: POV: His"),
            ("Creampie", "01: Cumshot: Creampie"),
            ("Cum Swallowing", "01: Cumshot: Cum Swallowing"),
            ("Public Sex", "01: Theme: Public Sex"),
            ("Roleplay", "01: Theme: Roleplay"),
        ):
            assert _suggested_action(tag_name, {target}) == f"merge -> {target}"
            assert _suggested_action(tag_name, set()) == "add"


class TestSuggestedAction:
    def test_recommends_merge_when_hair_keyword_matches_existing_collection(self) -> None:
        assert _suggested_action("Red Hair (Male)", {"01: Hair: Red"}) == "merge -> 01: Hair: Red"

    def test_matches_word_regardless_of_position_or_case(self) -> None:
        assert _suggested_action("Natural Blonde Hair Bombshell", {"01: Hair: Blonde"}) == "merge -> 01: Hair: Blonde"

    def test_color_word_alone_without_hair_context_does_not_merge(self) -> None:
        # Real false positives found on a live run before this requirement was added: color
        # words alone match plenty of tags that have nothing to do with hair. "White Woman" is
        # excluded here since it's since been added to _SKIP_EXACT_TAG_NAMES (ethnicity, not
        # hair), and "Blue Eyes"/"Brown Eyes" since eye color is now skipped outright - both
        # covered instead by TestSkipSignals. Synthetic (not real report tags) so a future bulk
        # low-count skip-list pass doesn't collide with these again.
        targets = {
            "01: Hair: Blue",
            "01: Hair: Brunette",
            "01: Hair: Pink",
            "01: Hair: Red",
        }
        for tag_name in ("Blue Bikini", "Brown Boots", "Pink Wallpaper", "Red Curtain"):
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
        # "Chairman" contains "hair" as a substring but not "red"/"blue"/etc. as a whole word.
        assert _suggested_action("Chairman", {"01: Hair: Red"}) == "add"

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


class TestResolvedMergeTargets:
    def test_returns_raw_multi_target_list(self) -> None:
        assert _resolved_merge_targets(
            "Anal Missionary",
            {"01: Category: Anal", "01: Activity: Missionary"},
        ) == ["01: Category: Anal", "01: Activity: Missionary"]

    def test_skip_list_takes_priority_over_resolvable_targets(self) -> None:
        assert (
            _resolved_merge_targets(
                "4K Anal Missionary",
                {"01: Category: Anal", "01: Activity: Missionary"},
            )
            is None
        )


class TestApplyTargets:
    def test_applies_explicit_merge_rule(self) -> None:
        assert _apply_targets(
            "Anal Missionary",
            {"01: Category: Anal", "01: Activity: Missionary"},
        ) == ["01: Category: Anal", "01: Activity: Missionary"]

    def test_applies_accepted_bare_add(self) -> None:
        assert _apply_targets("Missionary", {"01: Activity: Missionary"}) == ["01: Activity: Missionary"]

    def test_leaves_unaccepted_bare_add_alone(self) -> None:
        assert _apply_targets("Ordinary Unreviewed Tag", set()) is None

    def test_skip_list_takes_priority_over_accepted_bare_add(self) -> None:
        tag_name = "Prolapse"
        suggested = _suggest_new_collection_name(tag_name)
        with patch(
            "plexadm.stash_backfill_tags._ACCEPTED_ADD_COLLECTIONS",
            frozenset({suggested}),
        ):
            assert _apply_targets(tag_name, {suggested}) is None


class TestTagalongTargets:
    def test_anal_word_adds_anal_target(self) -> None:
        assert _tagalong_targets("Anal Fisting") == ["01: Category: Anal"]

    def test_toy_words_add_sex_toys_target(self) -> None:
        assert _tagalong_targets("Sybian") == ["01: Prop: Sex Toys"]
        assert _tagalong_targets("Glass Dildo") == ["01: Prop: Sex Toys"]
        assert _tagalong_targets("Nipple Toys") == ["01: Prop: Sex Toys"]

    def test_both_can_apply_at_once(self) -> None:
        assert _tagalong_targets("Anal Dildo") == ["01: Category: Anal", "01: Prop: Sex Toys"]

    def test_clothing_and_generic_objects_get_no_tagalong(self) -> None:
        for tag_name in ("Lingerie", "Stockings", "Skirt", "Mirror"):
            assert _tagalong_targets(tag_name) == []

    def test_bdsm_gear_words_add_fetish_target(self) -> None:
        # Confirmed by direct user request: Handcuffs/Leash/Whip each "ADD as a Prop, and MERGE
        # it to <Prop> + Fetish" - unlike the plain clothing/generic-object props above.
        assert _tagalong_targets("Handcuffs") == ["01: Category: Fetish"]
        assert _tagalong_targets("Leash") == ["01: Category: Fetish"]
        assert _tagalong_targets("Whip") == ["01: Category: Fetish"]
        # "Gags" was only asked to become its own Prop ("Gag"), not also tagged into Fetish.
        assert _tagalong_targets("Gags") == []

    def test_with_tagalong_does_not_duplicate_an_already_present_target(self) -> None:
        assert _with_tagalong("Anal Missionary", ["01: Category: Anal"]) == ["01: Category: Anal"]

    def test_with_tagalong_appends_after_existing_targets(self) -> None:
        assert _with_tagalong("Anal Dildo", ["01: Prop: Anal Dildo"]) == [
            "01: Prop: Anal Dildo",
            "01: Category: Anal",
            "01: Prop: Sex Toys",
        ]


class TestSuggestedActionTagalong:
    def test_stays_add_until_both_primary_and_tagalong_exist(self) -> None:
        # "Sybian" has no explicit merge-phrase entry at all - its own generic Prop suggestion
        # ("01: Prop: Sybian") is the implicit primary target.
        assert _suggested_action("Sybian", set()) == "add"
        assert _suggested_action("Sybian", {"01: Prop: Sybian"}) == "add"
        assert (
            _suggested_action("Sybian", {"01: Prop: Sybian", "01: Prop: Sex Toys"})
            == "merge -> 01: Prop: Sybian + 01: Prop: Sex Toys"
        )

    def test_pure_tagalong_tag_with_no_toy_or_anal_word_is_unaffected(self) -> None:
        assert _suggested_action("Lingerie", set()) == "add"

    def test_toy_masturbation_merges_into_masturbation_and_sex_toys(self) -> None:
        targets = {"01: Activity: Masturbation", "01: Prop: Sex Toys"}
        assert (
            _suggested_action("Toy Masturbation", targets) == "merge -> 01: Activity: Masturbation + 01: Prop: Sex Toys"
        )
        assert _suggested_action("Toy Masturbation", {"01: Activity: Masturbation"}) == "add"

    def test_toy_penetration_by_partner_merges_into_toy_penetration_and_sex_toys(self) -> None:
        targets = {"01: Activity: Toy Penetration", "01: Prop: Sex Toys"}
        assert (
            _suggested_action("Toy Penetration by Partner", targets)
            == "merge -> 01: Activity: Toy Penetration + 01: Prop: Sex Toys"
        )


class TestDildoVariantsCollapseIntoTheSharedDildoCollection:
    def test_bare_dildo_merges_into_dildo_and_sex_toys(self) -> None:
        targets = {"01: Prop: Dildo", "01: Prop: Sex Toys"}
        assert _suggested_action("Dildo", targets) == "merge -> 01: Prop: Dildo + 01: Prop: Sex Toys"

    def test_qualified_variants_merge_into_the_same_shared_collection(self) -> None:
        targets = {"01: Prop: Dildo", "01: Prop: Sex Toys"}
        for tag_name in ("Glass Dildo", "Double Dildo", "Face Dildo", "Huge Dildo", "Strapless Dildo", "Suction Dildo"):
            assert _suggested_action(tag_name, targets) == "merge -> 01: Prop: Dildo + 01: Prop: Sex Toys"

    def test_anal_dildo_also_picks_up_the_anal_tagalong(self) -> None:
        targets = {"01: Prop: Dildo", "01: Prop: Sex Toys", "01: Category: Anal"}
        assert (
            _suggested_action("Anal Dildo", targets)
            == "merge -> 01: Prop: Dildo + 01: Category: Anal + 01: Prop: Sex Toys"
        )
        # Stays "add" until every one of the three targets is real, not just two of them.
        assert _suggested_action("Anal Dildo", {"01: Prop: Dildo", "01: Prop: Sex Toys"}) == "add"

    def test_dildo_blowjob_is_unaffected_by_the_generic_dildo_rule(self) -> None:
        # "dildo blowjob" is checked first in _CATEGORY_MERGE_PHRASES - it must keep resolving
        # to plain Blowjob, not get swallowed by the newer generic "dildo" phrase.
        assert _suggested_action("Dildo Blowjob", {"01: Category: Blowjob"}) == "add"
        assert (
            _suggested_action("Dildo Blowjob", {"01: Category: Blowjob", "01: Prop: Sex Toys"})
            == "merge -> 01: Category: Blowjob + 01: Prop: Sex Toys"
        )

    def test_add_display_name_is_consistent_with_the_eventual_merge_target(self) -> None:
        for tag_name in ("Dildo", "Anal Dildo", "Glass Dildo", "Vaginal Dildo"):
            assert _suggest_new_collection_name(tag_name) == "01: Prop: Dildo"


class TestPotentialMergeTargetsTagalong:
    def test_returns_none_for_a_skip_tag_even_with_a_tagalong_word(self) -> None:
        # "4k" is a skip-marker word - the skip check must still win even though "dildo" would
        # otherwise make this tagalong-eligible.
        assert _suggested_action("4K Dildo", set()) == "skip"
        assert _potential_merge_targets("4K Dildo") is None

    def test_surfaces_the_implicit_primary_plus_tagalong_for_an_unclassified_toy_tag(self) -> None:
        assert _potential_merge_targets("Sybian") == ["01: Prop: Sybian", "01: Prop: Sex Toys"]

    def test_returns_none_for_a_tag_with_no_tagalong_word_and_no_merge_rule(self) -> None:
        assert _potential_merge_targets("Lingerie") is None


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

    def test_furniture_is_skipped_but_settings_and_bondage_are_not(self) -> None:
        for tag_name in ("Bedroom", "Chair", "Couch", "Table", "Blanket", "Ottoman", "Desk", "Lounger"):
            assert _suggested_action(tag_name, set()) == "skip"
        # Locations (not literal furniture) and the general bondage genre were confirmed as
        # worth keeping, so they must not be caught by the furniture skip. "Countertop" was
        # deliberately excluded here after a later bulk pass legitimately skipped it for an
        # unrelated reason (a real report tag with under 10 scenes) - see TestBulkLowCountSkip.
        for tag_name in ("Bathroom", "Shower", "Poolside", "Bondage", "Massage Table"):
            assert _suggested_action(tag_name, set()) == "add"

    def test_eye_color_is_skipped(self) -> None:
        for tag_name in ("Blue Eyes", "Brown Eyes", "Green Eyes", "Grey Eyes", "Hazel Eyes"):
            assert _suggested_action(tag_name, set()) == "skip"
        # "Eye"/"Eyebrow" as different words must not be caught. Synthetic (not real report
        # tags) so a future bulk low-count skip-list pass doesn't collide with these again.
        assert _suggested_action("Eye Roll", set()) == "add"
        assert _suggested_action("Eyebrow Threading", set()) == "add"


class TestAdditionalCategorySynonyms:
    # Found via a systematic pass cross-referencing every real "01: Category:" collection
    # against the live Add-section list for differently-worded StashDB synonyms of the same
    # concept, confirmed by direct user review.
    def test_synonym_phrases_merge_into_their_existing_collection(self) -> None:
        cases = {
            "Mouth Creampie": "01: Category: Cum In Mouth",
            "Throat Creampie": "01: Category: Throatpie",
            "Cum on Asshole": "01: Category: Cum On Ass",
            "Peeing": "01: Category: Pee",
            "No Sex": "01: Category: Non-Sexual",
            "Jerk Off Instruction": "01: Category: JOI",
            "Behind the Scenes": "01: Category: BTS",
            "Nipple Piercing": "01: Category: Pierced Nipples",
            "Tongue Piercing": "01: Category: Pierced Tongue",
            "Pussy Piercing": "01: Category: Pierced Vagina",
            "Twosome (Trans-Female)": "01: Category: TF Only",
        }
        for tag_name, target in cases.items():
            assert _suggested_action(tag_name, {target}) == f"merge -> {target}"

    def test_fauxcest_relation_tags_collapse_into_the_coarse_category(self) -> None:
        target = "01: Category: Fauxcest"
        for tag_name in (
            "Family Roleplay",
            "Step Dad",
            "Step Daughter",
            "Step Sister",
            "Step Mother",
            "Step Brother",
            "Step Cousin",
            "Step Siblings",
        ):
            assert _suggested_action(tag_name, {target}) == f"merge -> {target}"

    def test_teacher_tutor_variants_merge_into_the_existing_collection(self) -> None:
        target = "01: Category: Teacher/Tutor"
        for tag_name in ("Teacher", "Male Teacher", "Teaching Sex", "Tutoring"):
            assert _suggested_action(tag_name, {target}) == f"merge -> {target}"

    def test_headcount_above_threesome_merges_by_gender_ratio(self) -> None:
        cases = {
            "Foursome (BGGG)": "01: Category: Reverse Gangbang",
            "Foursome (BBBG)": "01: Category: Gangbang",
            "Foursome (BBGG)": "01: Category: Orgy",
            "Fivesome (BBBGG)": "01: Category: Orgy",
            "Sixsome (BBBBGG)": "01: Category: Orgy",
        }
        for tag_name, target in cases.items():
            assert _suggested_action(tag_name, {target}) == f"merge -> {target}"

    def test_blowbang_merges_into_all_three_targets(self) -> None:
        targets = {"01: Category: Gangbang", "01: Category: Blowjob", "01: Category: Orgy"}
        assert _suggested_action("Blowbang", targets) == (
            "merge -> 01: Category: Gangbang + 01: Category: Blowjob + 01: Category: Orgy"
        )

    def test_ethnicity_merges_are_limited_to_asian_and_ebony(self) -> None:
        assert _suggested_action("Asian Woman", {"01: Category: Asian"}) == "merge -> 01: Category: Asian"
        assert _suggested_action("Black Woman", {"01: Category: Ebony"}) == "merge -> 01: Category: Ebony"
        assert _suggested_action("Black", {"01: Category: Ebony"}) == "merge -> 01: Category: Ebony"

    def test_black_exact_match_does_not_catch_hair_or_clothing_tags(self) -> None:
        # "black" alone would be a dangerous substring match against these - must go through
        # their own hair-context/prop checks instead, not the ethnicity merge.
        targets = {"01: Category: Ebony", "01: Hair: Black"}
        assert _suggested_action("Black Hair (Female)", targets) == "merge -> 01: Hair: Black"
        assert _suggested_action("Black Stockings", targets) == "add"

    def test_other_nationalities_are_skipped_not_merged(self) -> None:
        for tag_name in ("Latina Woman", "Latino Man", "Mixed Race Woman", "German", "American Porn", "White Man"):
            assert _suggested_action(tag_name, set()) == "skip"


class TestQualifiedVariantsCollapseIntoTheBaseCollection:
    # Confirmed by direct user review: "many of these are just '<adjective> <existing tag>'" -
    # position/qualifier-prefixed or -suffixed variants of an already-tracked act collapse into
    # it rather than becoming their own new suggested collection.
    def test_blowjob_cluster(self) -> None:
        target = "01: Category: Blowjob"
        for tag_name in (
            "Standing Blowjob",
            "Sloppy Blowjob",
            "Chipmunk Blowjob",
            "Head Pushing Blowjob",
            "Hands-free Blowjob",
            "Triple Blowjob",
            "Blowjob Only",
            "Blowjob - POV",
            "Blowjob Nose Pinch",
            "Dick Licking",
        ):
            assert _suggested_action(tag_name, {target}) == f"merge -> {target}"

    def test_blowjob_position_cluster_needs_both_blowjob_and_the_position(self) -> None:
        # "Missionary Blowjob"/"Cowgirl Blowjob"/"Side Fuck Blowjob"/"Spooning Blowjob"/"Ball
        # Sucking During Blowjob" - the qualifier is itself an independently-tracked Activity
        # (same upgrade as the Anal cluster below), so these need both legs, not just Blowjob.
        blowjob = "01: Category: Blowjob"
        cases = {
            "Missionary Blowjob": "01: Activity: Missionary",
            "Cowgirl Blowjob": "01: Activity: Cowgirl",
            "Side Fuck Blowjob": "01: Activity: Side Fuck",
            "Spooning Blowjob": "01: Activity: Spooning",
            "Ball Sucking During Blowjob": "01: Activity: Ball Sucking",
        }
        for tag_name, position in cases.items():
            assert _suggested_action(tag_name, {blowjob, position}) == f"merge -> {blowjob} + {position}"
            # Stays "add" until both legs are real, not just Blowjob.
            assert _suggested_action(tag_name, {blowjob}) == "add"

    def test_inverted_blowjob_promotes_to_its_own_collection_plus_blowjob(self) -> None:
        # Unlike the qualifier-only variants above, "Inverted Blowjob" gets its own new Activity
        # collection (confirmed by direct user request) as well as landing in base Blowjob.
        inverted = "01: Activity: Inverted Blowjob"
        blowjob = "01: Category: Blowjob"
        assert _suggested_action("Inverted Blowjob", {inverted, blowjob}) == f"merge -> {inverted} + {blowjob}"
        assert _suggest_new_collection_name("Inverted Blowjob") == inverted
        assert _suggested_action("Inverted Blowjob", {blowjob}) == "add"

    def test_dildo_blowjob_also_needs_sex_toys(self) -> None:
        # "Dildo Blowjob" contains the toy tag-along word "dildo" - it must also require
        # "01: Prop: Sex Toys" before it fires as a merge, unlike its plain Blowjob siblings.
        assert _suggested_action("Dildo Blowjob", {"01: Category: Blowjob"}) == "add"
        assert (
            _suggested_action("Dildo Blowjob", {"01: Category: Blowjob", "01: Prop: Sex Toys"})
            == "merge -> 01: Category: Blowjob + 01: Prop: Sex Toys"
        )

    def test_rimming_cluster(self) -> None:
        target = "01: Category: Rimming"
        for tag_name in ("Rimming Her", "Rimming Him", "Rimming During Sex"):
            assert _suggested_action(tag_name, {target}) == f"merge -> {target}"

    def test_massage_cluster(self) -> None:
        target = "01: Category: Massage"
        for tag_name in ("Massage Table", "Massage Parlor"):
            assert _suggested_action(tag_name, {target}) == f"merge -> {target}"

    def test_69_cluster(self) -> None:
        target = "01: Category: 69"
        for tag_name in ("69 Breast Licking", "Standing 69"):
            assert _suggested_action(tag_name, {target}) == f"merge -> {target}"

    def test_lesbian_cluster(self) -> None:
        target = "01: Category: Lesbian"
        for tag_name in ("Lesbian Action", "Lesbian Character"):
            assert _suggested_action(tag_name, {target}) == f"merge -> {target}"

    def test_ass_smacking_merges_into_spanking(self) -> None:
        assert _suggested_action("Ass Smacking", {"01: Category: Spanking"}) == "merge -> 01: Category: Spanking"

    def test_pussy_smacking_is_unaffected_and_keeps_its_own_activity_suggestion(self) -> None:
        # Only "Ass Smacking" was confirmed - "Pussy Smacking" wasn't mentioned and keeps
        # going through the generic "smacking" Activity keyword instead.
        assert _suggested_action("Pussy Smacking", {"01: Category: Spanking"}) == "add"

    def test_double_x_cluster(self) -> None:
        assert (
            _suggested_action("Double Blowjob (2 Mouths)", {"01: Category: Double Blowjob"})
            == "merge -> 01: Category: Double Blowjob"
        )
        assert (
            _suggested_action("Double Blowjob (2 Penises)", {"01: Category: Double Blowjob"})
            == "merge -> 01: Category: Double Blowjob"
        )
        for tag_name in ("Double Facial", "Double Facial (2 Penises)", "Double Facial (2 Targets)"):
            assert _suggested_action(tag_name, {"01: Category: Facial"}) == "merge -> 01: Category: Facial"
        assert (
            _suggested_action("Double Vaginal Penetration (DVP)", {"01: Category: Double Vaginal"})
            == "merge -> 01: Category: Double Vaginal"
        )

    def test_anal_cluster_merges_into_bare_anal(self) -> None:
        # These stay Anal-only: no independently-tracked Activity counterpart exists for any of
        # them (unlike the Missionary/Cowgirl/etc. cluster below).
        target = "01: Category: Anal"
        for tag_name in (
            "All Anal",
            "Anal Gape",
            "Anal Bulldog",
            "Anal Full Nelson",
            "Anal Orgasm",
            "Anal Loophole",
            "Anal Winking",
            "Anal Hooks",
            "Anal Stretching",
        ):
            assert _suggested_action(tag_name, {target}) == f"merge -> {target}"

    def test_anal_position_cluster_needs_both_anal_and_the_position(self) -> None:
        # "Anal Missionary"/"Anal Cowgirl"/etc. - the position is itself an independently-tracked
        # Activity, so these need both legs, not just Anal. Confirmed by direct user correction:
        # these used to collapse into Anal alone even after their position became a tracked
        # Activity Add candidate in its own right.
        anal = "01: Category: Anal"
        cases = {
            "Anal Missionary": "01: Activity: Missionary",
            "Anal Reverse Cowgirl": "01: Activity: Reverse Cowgirl",
            "Anal Lazy Reverse Cowgirl": "01: Activity: Reverse Cowgirl",
            "Anal Squatting Reverse Cowgirl": "01: Activity: Reverse Cowgirl",
            "Anal Doggy Style": "01: Activity: Doggy Style",
            "Anal Cowgirl": "01: Activity: Cowgirl",
            "Anal Spooning": "01: Activity: Spooning",
            "Anal Side Fuck": "01: Activity: Side Fuck",
            "Anal Piledriver": "01: Activity: Piledriver",
            "Anal Spit Roast": "01: Activity: Spit Roast",
        }
        for tag_name, position in cases.items():
            assert _suggested_action(tag_name, {anal, position}) == f"merge -> {anal} + {position}"
            # Stays "add" until both legs are real, not just Anal.
            assert _suggested_action(tag_name, {anal}) == "add"

    def test_anal_tags_with_their_own_good_suggestion_are_not_merged(self) -> None:
        # These already get a specific Activity/Prop suggestion via keyword match - merging them
        # into bare "Anal" would only lose that specificity, and wasn't part of what was
        # confirmed.
        for tag_name in ("Anal Fingering", "Anal Toys", "Anal Fisting", "Anal Squirting", "Anal Dildo"):
            assert _suggested_action(tag_name, {"01: Category: Anal"}) == "add"

    def test_multi_target_pairs(self) -> None:
        assert (
            _suggested_action("Rimming (Lesbian)", {"01: Category: Lesbian", "01: Category: Rimming"})
            == "merge -> 01: Category: Lesbian + 01: Category: Rimming"
        )
        assert (
            _suggested_action("Rimming During Blowjob", {"01: Category: Rimming", "01: Category: Blowjob"})
            == "merge -> 01: Category: Rimming + 01: Category: Blowjob"
        )
        assert (
            _suggested_action("Anal Prone Bone", {"01: Category: Anal", "01: Category: Prone Bone"})
            == "merge -> 01: Category: Anal + 01: Category: Prone Bone"
        )

    def test_forward_declared_multi_targets_do_not_fire_until_masturbation_is_real(self) -> None:
        # "Masturbation" isn't a real collection yet - these stay "add" until it is, then
        # activate automatically on a future run.
        assert _suggested_action("Anal Masturbation", {"01: Category: Anal"}) == "add"
        assert _suggested_action("Self Pussy Fingering", {"01: Category: Fingering"}) == "add"
        assert (
            _suggested_action("Anal Masturbation", {"01: Category: Anal", "01: Activity: Masturbation"})
            == "merge -> 01: Category: Anal + 01: Activity: Masturbation"
        )
        assert (
            _suggested_action("Self Pussy Fingering", {"01: Activity: Masturbation", "01: Category: Fingering"})
            == "merge -> 01: Activity: Masturbation + 01: Category: Fingering"
        )
        # Substring match also covers the "During Sex" sibling for free.
        assert (
            _suggested_action(
                "Self Pussy Fingering During Sex", {"01: Activity: Masturbation", "01: Category: Fingering"}
            )
            == "merge -> 01: Activity: Masturbation + 01: Category: Fingering"
        )

    def test_bare_foursome_merges_into_orgy_without_catching_variants(self) -> None:
        assert _suggested_action("Foursome", {"01: Category: Orgy"}) == "merge -> 01: Category: Orgy"
        # Exact match only - the specific gender-ratio variants must not be caught by this.
        assert _suggested_action("Foursome (BBGG)", {"01: Category: Orgy"}) == "merge -> 01: Category: Orgy"
        # "Foursome (BBBG)" has its own target (Gangbang) - if only Orgy exists, it stays "add"
        # rather than wrongly falling back to the bare "Foursome" -> Orgy rule.
        assert _suggested_action("Foursome (BBBG)", {"01: Category: Orgy"}) == "add"


class TestNewSkipsThisRound:
    def test_prolapse_is_skipped_not_activity(self) -> None:
        assert _suggested_action("Prolapse", set()) == "skip"

    def test_award_winner_is_skipped_regardless_of_year(self) -> None:
        for tag_name in (
            "Award Winner (AVN Award 2016)",
            "Award Winner (AVN Award 2025)",
        ):
            assert _suggested_action(tag_name, set()) == "skip"
        # "Award Winning" is a different word/tag and wasn't asked to be excluded.
        assert _suggested_action("Award Winning", set()) == "add"

    def test_armpit_fetish_is_skipped(self) -> None:
        assert _suggested_action("Armpit Fetish", set()) == "skip"

    def test_ass_to_mouth_is_skipped(self) -> None:
        assert _suggested_action("Ass to Mouth", set()) == "skip"
        # A different, unrelated tag containing "ass"/"mouth" separately must not be caught.
        assert _suggested_action("Ass to Other's Mouth", set()) == "add"

    def test_bare_nude_is_skipped_but_nude_stockings_is_not(self) -> None:
        assert _suggested_action("Nude", set()) == "skip"
        assert _suggested_action("Nude Stockings", set()) == "add"
        # Synthetic (not a real report tag) so a future bulk low-count skip-list pass doesn't
        # collide with this again - "Non-Nude" itself is now independently skipped that way.
        assert _suggested_action("Semi-Nude", set()) == "add"

    def test_age_references_are_skipped(self) -> None:
        for tag_name in (
            "Teen Girl (18–22)",
            "MILF (30+)",
            "Young Woman (22–30)",
            "Experienced Man (30–40)",
            "Middle-aged Man (40–60)",
            "Older Man / Younger Woman",
            "DILF (30+)",
            "18+",
            "20+",
            "30+",
        ):
            assert _suggested_action(tag_name, set()) == "skip"

    def test_dropped_licking_grinding_touching_kissing_variants(self) -> None:
        for tag_name in (
            "Ball Licking",
            "Breast Licking",
            "Licking",
            "Grinding",
            "Breast Touching",
            "Kissing",
        ):
            assert _suggested_action(tag_name, set()) == "skip"
        # Reclassified from Skip - "Nipple Touching"/"Nipple Pinching" -> Nipple Play (confirmed
        # by direct user request, 2026-07-27 skip-list review).
        nipple_play = "01: Category: Nipple Play"
        for tag_name in ("Nipple Touching", "Nipple Pinching"):
            assert _suggested_action(tag_name, {nipple_play}) == f"merge -> {nipple_play}"

    def test_foot_licking_merges_into_foot_fetish_instead_of_being_dropped(self) -> None:
        assert _suggested_action("Foot Licking", {"01: Category: Foot Fetish"}) == "merge -> 01: Category: Foot Fetish"

    def test_grinding_on_face_merges_into_face_sitting(self) -> None:
        assert (
            _suggested_action("Grinding on Face", {"01: Category: Face Sitting"})
            == "merge -> 01: Category: Face Sitting"
        )


class TestFifthRoundMergesAndAttributes:
    def test_pussy_smacking_merges_into_pussy_spanking(self) -> None:
        assert (
            _suggested_action("Pussy Smacking", {"01: Category: Pussy Spanking"})
            == "merge -> 01: Category: Pussy Spanking"
        )

    def test_anal_fingering_during_sex_forward_declares_into_anal_fingering(self) -> None:
        target = "01: Activity: Anal Fingering"
        assert _suggested_action("Anal Fingering During Sex", set()) == "add"
        # Also needs the anal tag-along target before it fires as a merge.
        assert _suggested_action("Anal Fingering During Sex", {target}) == "add"
        assert (
            _suggested_action("Anal Fingering During Sex", {target, "01: Category: Anal"})
            == f"merge -> {target} + 01: Category: Anal"
        )

    def test_vaginal_insertion_forward_declares_into_vaginal_penetration(self) -> None:
        target = "01: Activity: Vaginal Penetration"
        assert _suggested_action("Vaginal Insertion", set()) == "add"
        assert _suggested_action("Vaginal Insertion", {target}) == f"merge -> {target}"

    def test_face_fuck_is_respelled_facefuck(self) -> None:
        assert _suggest_new_collection_name("Face Fuck") == "01: Activity: Facefuck"

    def test_side_fuck_is_activity_without_a_bare_fuck_keyword(self) -> None:
        assert _suggest_new_collection_name("Side Fuck") == "01: Activity: Side Fuck"
        # A bare "fuck" keyword would still wrongly sweep in unrelated tags - confirms it wasn't
        # added. Hard Fuck/Deep Fuck reach Activity via their own individual name overrides
        # instead (2026-07-25 review), not a shared keyword.
        assert _suggest_new_collection_name("Hard Fuck") == "01: Activity: Hard Fuck"
        assert _suggest_new_collection_name("Deep Fuck") == "01: Activity: Deep Fuck"

    def test_pov_gender_direction_tags_get_dedicated_names(self) -> None:
        assert _suggest_new_collection_name("Male - POV") == "01: Theme: POV: His"
        assert _suggest_new_collection_name("Female - POV") == "01: Theme: POV: Hers"
        assert _suggest_new_collection_name("Mixed - POV") == "01: Theme: POV: Mixed"

    def test_act_pov_tags_split_once_pov_exists(self) -> None:
        pov = "01: Theme: POV"
        cases = {
            "Blowjob - POV": "01: Category: Blowjob",
            "Cowgirl - POV": "01: Activity: Cowgirl",
            "Reverse Cowgirl - POV": "01: Activity: Reverse Cowgirl",
            "Missionary - POV": "01: Activity: Missionary",
            "Facial - POV": "01: Category: Facial",
            "Handjob - POV": "01: Category: Handjob",
            "Footjob - POV": "01: Category: Footjob",
            "Titjob - POV": "01: Category: Tit Fucking",
            "Doggy Style - POV": "01: Activity: Doggy Style",
        }
        for tag_name, act_target in cases.items():
            assert _suggested_action(tag_name, {act_target, pov}) == f"merge -> {act_target} + {pov}"

    def test_act_pov_tags_fall_back_before_pov_exists(self) -> None:
        # "Blowjob - POV" has an established single-target fallback from an earlier round.
        assert _suggested_action("Blowjob - POV", {"01: Category: Blowjob"}) == "merge -> 01: Category: Blowjob"
        # "Titjob - POV" gets one too now that Titjob collapses into the real Tit Fucking
        # collection - a substring match via the bare "titjob" merge phrase.
        assert _suggested_action("Titjob - POV", {"01: Category: Tit Fucking"}) == "merge -> 01: Category: Tit Fucking"
        # The others have no such fallback and stay "add" (with their own keyword suggestion).
        assert _suggested_action("Cowgirl - POV", set()) == "add"
        assert _suggest_new_collection_name("Cowgirl - POV") == "01: Activity: Cowgirl - POV"

    def test_anal_pov_variants_prefer_the_more_specific_split_over_the_bare_anal_merge(self) -> None:
        anal = "01: Category: Anal"
        pov = "01: Theme: POV"
        cases = {
            "Anal Cowgirl - POV": "01: Activity: Cowgirl",
            "Anal Doggy Style - POV": "01: Activity: Doggy Style",
            "Anal Missionary - POV": "01: Activity: Missionary",
            "Anal Reverse Cowgirl - POV": "01: Activity: Reverse Cowgirl",
        }
        for tag_name, position in cases.items():
            # Needs all three legs - Anal + the position + POV - confirmed by direct user
            # correction (the position leg used to be missing here even when the position was
            # separately tracked for the bare "anal X" entries).
            assert _suggested_action(tag_name, {anal, position, pov}) == f"merge -> {anal} + {position} + {pov}"
            # Before POV exists (but the position does), falls back to the bare "anal X" 2-leg
            # merge from the cluster above, dropping POV.
            assert _suggested_action(tag_name, {anal, position}) == f"merge -> {anal} + {position}"
            # Before the position exists at all, there's no single-target Anal-only fallback
            # left (unlike the old behavior) - stays "add".
            assert _suggested_action(tag_name, {anal}) == "add"
            assert _suggested_action(tag_name, {anal, pov}) == "add"

    def test_attributes_body_descriptors(self) -> None:
        for tag_name in ("Hairless Pussy", "Natural Tits", "Big Tits", "Hairy Pussy", "Big Dick", "Long Hair"):
            assert _suggest_new_collection_name(tag_name).startswith("01: Attributes: ")

    def test_named_positions_are_activities(self) -> None:
        for tag_name in ("Reverse Cowgirl", "Cowgirl", "Missionary"):
            assert _suggest_new_collection_name(tag_name).startswith("01: Activity: ")

    def test_tit_wording_is_normalized_from_breast(self) -> None:
        # "Breast Play" -> Activity (reclassified from Category in the 2026-07-25 review); the
        # override key is matched against the normalized "Tit Play" name, not the raw tag name.
        assert _suggest_new_collection_name("Breast Play") == "01: Activity: Tit Play"
        assert _suggest_new_collection_name("Breast Squeezing") == "01: Activity: Tit Squeezing"
        assert _suggest_new_collection_name("Close Up Breasts") == "01: Attributes: Close Up Tits"

    def test_titjob_collapses_into_tit_fucking(self) -> None:
        target = "01: Category: Tit Fucking"
        for tag_name in ("Titjob", "Titjob - POV"):
            assert _suggested_action(tag_name, {target}) == f"merge -> {target}"
        # No longer a keyword in its own right - stays "add" with no Tit Fucking collection
        # present, rather than suggesting a standalone "01: Activity: Titjob".
        assert _suggested_action("Titjob", set()) == "add"
        assert _suggest_new_collection_name("Titjob") == "01: Category: Titjob"

    def test_water_is_a_prop_not_an_activity(self) -> None:
        assert _EXISTING_CATEGORY_RENAMES["01: Category: Water"] == "01: Prop: Water"
        # "Sex in the Water" is a setting, not the same substance/prop concept - must stay
        # unaffected.
        assert _suggest_new_collection_name("Sex in the Water") == "01: Category: Sex in the Water"


class TestCompositionNewCollectionOverrides:
    def test_lesbian_headcount_variants_route_to_new_dedicated_collections(self) -> None:
        assert _suggest_new_collection_name("Twosome (Lesbian)") == "01: Composition: FF Only"
        assert _suggest_new_collection_name("Foursome (Lesbian)") == "01: Composition: Female Only"
        assert _suggest_new_collection_name("Sixsome (Lesbian)") == "01: Composition: Female Only"
        assert _suggest_new_collection_name("Orgy (Lesbian)") == "01: Composition: Female Only"

    def test_plain_lesbian_composition_tags_are_unaffected(self) -> None:
        # Confirms the override is scoped to the specific tag names above, not "lesbian" broadly.
        assert _suggest_new_collection_name("Lesbian Anal") == "01: Activity: Lesbian Anal"

    def test_bare_twosome_is_composition(self) -> None:
        assert _suggest_new_collection_name("Twosome") == "01: Composition: Twosome"


class TestSixthRoundHairAndDpSplit:
    """2026-07-25 review: hair-length gender wording, and (DP)-suffixed positions split into
    the base position plus Double Penetration rather than getting their own collection."""

    def test_long_hair_female_avoids_parenthetical_gender(self) -> None:
        assert _suggest_new_collection_name("Long Hair (Female)") == "01: Attributes: Long Haired Woman"
        # Bare "Long Hair" (no gender qualifier) is unaffected.
        assert _suggest_new_collection_name("Long Hair") == "01: Attributes: Long Hair"

    def test_cowgirl_dp_splits_into_base_position_and_double_penetration(self) -> None:
        targets = ["01: Activity: Cowgirl", "01: Activity: Double Penetration"]
        assert _suggested_action("Cowgirl (DP)", set(targets)) == f"merge -> {' + '.join(targets)}"
        # Neither target exists yet in the live report - stays "add" until both are real.
        assert _suggested_action("Cowgirl (DP)", set()) == "add"

    def test_reverse_cowgirl_dp_is_matched_before_the_bare_cowgirl_dp_phrase(self) -> None:
        targets = ["01: Activity: Reverse Cowgirl", "01: Activity: Double Penetration"]
        assert _suggested_action("Reverse Cowgirl (DP)", set(targets)) == f"merge -> {' + '.join(targets)}"


class TestSixthRoundCategoryReclassification:
    """2026-07-25 review: most "01: Category:" Add suggestions reclassified into Activity/
    Attributes/Prop/Theme/Composition after a full tag-by-tag pass."""

    def test_activity_reclassifications(self) -> None:
        assert _suggest_new_collection_name("Vaginal Sex") == "01: Activity: Vaginal Sex"
        assert _suggest_new_collection_name("Orgasm") == "01: Activity: Orgasm"
        assert _suggest_new_collection_name("Ass Play") == "01: Activity: Ass Play"

    def test_attribute_reclassifications(self) -> None:
        assert _suggest_new_collection_name("Short Woman") == "01: Attributes: Short Woman"
        assert _suggest_new_collection_name("Big Ass") == "01: Attributes: Big Ass"

    def test_bwc_bbc_drop_the_parenthetical_acronym(self) -> None:
        assert _suggest_new_collection_name("Big White Cock (BWC)") == "01: Attributes: Big White Cock"
        assert _suggest_new_collection_name("Big Black Cock (BBC)") == "01: Attributes: Big Black Cock"

    def test_prop_reclassifications(self) -> None:
        assert _suggest_new_collection_name("Earrings") == "01: Prop: Earrings"
        assert _suggest_new_collection_name("Lube") == "01: Prop: Lube"

    def test_theme_reclassifications(self) -> None:
        assert _suggest_new_collection_name("College") == "01: Theme: College"
        assert _suggest_new_collection_name("Bondage") == "01: Theme: Bondage"

    def test_ambiguous_relational_and_meta_tags_stay_category(self) -> None:
        # Reviewed and deliberately left alone - see the comment block in
        # _SUGGESTED_NAME_OVERRIDES for the reasoning per tag.
        assert _suggest_new_collection_name("Interracial") == "01: Category: Interracial"
        assert _suggest_new_collection_name("Pornstar") == "01: Category: Pornstar"
        assert _suggest_new_collection_name("Series") == "01: Category: Series"

    def test_facesitting_on_her_merges_into_the_existing_face_sitting_collection(self) -> None:
        target = "01: Category: Face Sitting"
        assert _suggested_action("Facesitting on Her", {target}) == f"merge -> {target}"
        # "Facesitting on Him" is a separate, already-skip-listed exact tag name, unaffected.

    def test_all_vaginal_forward_declares_into_vaginal_sex(self) -> None:
        target = "01: Activity: Vaginal Sex"
        assert _suggested_action("All Vaginal", {target}) == f"merge -> {target}"
        assert _suggested_action("All Vaginal", set()) == "add"


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
        assert _suggest_new_collection_name("Pink Handcuffs") == "01: Prop: Pink Handcuffs"

    def test_prop_keyword_covers_worn_fetish_attire_and_bondage_gear(self) -> None:
        for tag_name in ("Black Stockings", "Woman's Heels", "Handcuffs", "Sybian", "Gags"):
            assert _suggest_new_collection_name(tag_name).startswith("01: Prop: ")

    def test_activity_keyword(self) -> None:
        assert _suggest_new_collection_name("Rough Anal") == "01: Activity: Rough Anal"

    def test_activity_keyword_covers_verb_shaped_act_tags(self) -> None:
        # Found via direct user review: verb/gerund act tags were wrongly falling to the
        # "01: Category:" fallback. "Kissing" was the original flagged example, but is now
        # dropped outright per a later round instead (see TestNewSkipsThisRound).
        for tag_name in ("Riding", "Ball Sucking", "Gagging", "Ass Worship", "Tickling"):
            assert _suggest_new_collection_name(tag_name).startswith("01: Activity: ")

    def test_named_positions_are_now_activities(self) -> None:
        # Reversed by a later direct user correction: named positions are activities after all.
        for tag_name in ("Cowgirl", "Missionary", "Doggy Style"):
            assert _suggest_new_collection_name(tag_name).startswith("01: Activity: ")

    def test_more_named_positions_are_activities(self) -> None:
        # Confirmed by direct user correction: many more Category-catch-all tags were also
        # named positions.
        for tag_name in (
            "Spooning",
            "Piledriver",
            "Reverse Piledriver",
            "Spit Roast",
            "Standing Sex",
            "Standing Sex (DP)",
            "Ballerina Position",
            "Airplane Position",
            "Squatting",
            "The Pose",
            "Bulldog",
            "Stand and Carry",
            "Stand and Carry (DP)",
            "Full Nelson",
        ):
            assert _suggest_new_collection_name(tag_name).startswith("01: Activity: ")

    def test_position_overrides_for_words_too_generic_to_be_keywords(self) -> None:
        # "split"/"down"/"ass"/"up"/"side"/"leaning"/"forward" are all too generic or already
        # mean something else elsewhere (e.g. "split" also appears in "Split Tongue") to be safe
        # standalone keywords - these need an explicit override instead.
        assert _suggest_new_collection_name("Face Down Ass Up") == "01: Activity: Face Down Ass Up"
        assert _suggest_new_collection_name("Side Winder") == "01: Activity: Side Winder"
        assert _suggest_new_collection_name("Split Leaning Forward") == "01: Activity: Split Leaning Forward"
        assert _suggest_new_collection_name("Split Tongue") != "01: Activity: Split Tongue"

    def test_hairstyle_is_an_attribute_not_a_category(self) -> None:
        # Confirmed by direct user correction: hairstyle (as opposed to hair color, which merges
        # into the existing "01: Hair:" collections) is a performer attribute.
        for tag_name in ("Bald Head", "Bangs", "Braids", "Ponytail", "Dreadlocks", "Pigtails"):
            assert _suggest_new_collection_name(tag_name).startswith("01: Attributes: ")

    def test_theme_keyword(self) -> None:
        assert _suggest_new_collection_name("Hot Cosplay") == "01: Theme: Hot Cosplay"

    def test_falls_back_to_category_when_no_keyword_matches(self) -> None:
        assert _suggest_new_collection_name("Beautiful Agony") == "01: Category: Beautiful Agony"

    def test_cumshot_takes_priority_over_other_matches(self) -> None:
        # Contains both a cumshot word ("creampie") and a composition word ("gangbang").
        assert _suggest_new_collection_name("Gangbang Creampie") == "01: Cumshot: Gangbang Creampie"

    def test_attributes_keyword(self) -> None:
        for tag_name in ("Navel Piercing", "Tattoos & Piercings", "Tanned Skin", "Heavily Tattooed"):
            assert _suggest_new_collection_name(tag_name).startswith("01: Attributes: ")

    def test_daisy_chain_is_activity_not_composition(self) -> None:
        assert _suggest_new_collection_name("Daisy Chain") == "01: Activity: Daisy Chain"

    def test_skirt_is_prop(self) -> None:
        for tag_name in ("Plaid Skirt", "Short Skirt", "Pleated Skirt"):
            assert _suggest_new_collection_name(tag_name).startswith("01: Prop: ")


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
                "name": "Category: Trivia",
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
        # Both remaining tags land in the "### Category" Add subsection, sorted by scene count.
        assert report.index("Free \\| Text") < report.index("Category: Trivia")
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

    def test_add_section_is_grouped_into_taxonomy_subsections(self, tmp_path: Path) -> None:
        tags = [
            {
                "id": "1",
                "name": "Gagging",
                "scene_count": 5,
                "stash_ids": [{"endpoint": "https://stashdb.org/graphql", "stash_id": "a"}],
            },
            {
                "id": "2",
                "name": "Beautiful Agony",
                "scene_count": 3,
                "stash_ids": [{"endpoint": "https://stashdb.org/graphql", "stash_id": "b"}],
            },
            {
                "id": "3",
                "name": "Pink Handcuffs",
                "scene_count": 1,
                "stash_ids": [{"endpoint": "https://stashdb.org/graphql", "stash_id": "c"}],
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
        # Subsections are sorted alphabetically: Activity, then Category, then Prop.
        assert report.index("### Activity") < report.index("### Category") < report.index("### Prop")
        assert report.index("### Activity") < report.index("Gagging")
        assert report.index("### Category") < report.index("Beautiful Agony") < report.index("### Prop")
        assert report.index("### Prop") < report.index("Pink Handcuffs")

    def test_pending_collections_section_tracks_add_and_upgrade_candidates(self, tmp_path: Path) -> None:
        tags = [
            {
                "id": "1",
                "name": "Anal Cowgirl - POV",
                "scene_count": 2,
                "stash_ids": [{"endpoint": "https://stashdb.org/graphql", "stash_id": "a"}],
            },
            {
                "id": "2",
                "name": "Cowgirl - POV",
                "scene_count": 5,
                "stash_ids": [{"endpoint": "https://stashdb.org/graphql", "stash_id": "b"}],
            },
        ]
        stash = MagicMock()
        stash.all_tags.return_value = tags
        stash.configured_stash_boxes.return_value = [{"name": "StashDB", "endpoint": "https://stashdb.org/graphql"}]
        plex_ctx = MagicMock()
        plex_ctx.section.collections.return_value = [SimpleNamespace(title="01: Category: Anal")]
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
        assert "## Pending Collections" in report
        # "Anal Cowgirl - POV" already merges into Anal + Cowgirl today (falls back to the 2-leg
        # "anal cowgirl" rule since POV isn't real - "01: Activity: Cowgirl" resolves via the
        # accepted-collections snapshot even though it isn't a real Plex collection either) - it
        # must still show up here as an upgrade candidate, annotated with its current target, not
        # just tags that are fully stuck in "add".
        assert "Anal Cowgirl - POV (currently -> 01: Category: Anal + 01: Activity: Cowgirl)" in report
        assert "Cowgirl - POV" in report
        # "01: Activity: Cowgirl" no longer appears as its own pending row: it's one of the
        # 2026-07-25 accepted Add suggestions (_ACCEPTED_ADD_COLLECTIONS), so it now resolves as
        # a valid merge target even though it isn't a real Plex collection yet. Only "01: Theme:
        # POV" (not accepted) is still genuinely pending, waited on by both tags.
        pending_section = report[report.index("## Pending Collections") :]
        assert "| 01: Theme: POV |" in pending_section
        assert "01: Activity: Cowgirl |" not in pending_section

    def test_accepted_add_collection_promotes_pending_tag_into_merge(self, tmp_path: Path) -> None:
        # "All Vaginal" forward-merges into "01: Activity: Vaginal Sex" (_CATEGORY_MERGE_PHRASES),
        # and that target is one of the 2026-07-25 accepted Add suggestions
        # (_ACCEPTED_ADD_COLLECTIONS) - even though it isn't a real Plex collection, it should
        # resolve as a full "## Merge" row rather than sitting in "## Add" / "## Pending
        # Collections".
        tags = [
            {
                "id": "1",
                "name": "All Vaginal",
                "scene_count": 49,
                "stash_ids": [{"endpoint": "https://stashdb.org/graphql", "stash_id": "a"}],
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
        # No forward-declared merge is left unresolved for this single tag, so "## Pending
        # Collections" is omitted entirely (same zero-rows convention as elsewhere in this
        # report) - slice against "## Skip", which is always present, instead.
        add_section = report[report.index("## Add") : report.index("## Merge")]
        merge_section = report[report.index("## Merge") : report.index("## Skip")]
        assert "## Pending Collections" not in report
        assert "All Vaginal" not in add_section
        assert "All Vaginal" in merge_section
        assert "01: Activity: Vaginal Sex" in merge_section


class TestRenameTags:
    def _stash(self, existing_names: list[str]) -> MagicMock:
        stash = MagicMock()
        stash.all_tags.return_value = [
            {"id": str(i), "name": name, "scene_count": 1, "stash_ids": []}
            for i, name in enumerate(existing_names, start=1)
        ]
        return stash

    def test_dry_run_reports_without_calling_rename_tag(self) -> None:
        stash = self._stash(["Category: Solo", "Category: Lesbian"])
        args = SimpleNamespace(
            config="config.ini", log_level="WARNING", stash_endpoint="http://stash:9999", dry_run=True
        )

        with (
            patch("plexadm.stash_backfill_tags.load_config", return_value=SimpleNamespace(stash_endpoint=None)),
            patch("plexadm.stash_backfill_tags.StashClient", return_value=stash),
        ):
            assert rename_tags(args) == 0

        stash.rename_tag.assert_not_called()

    def test_real_run_renames_every_matching_tag(self) -> None:
        stash = self._stash(["Category: Solo", "Category: Lesbian", "Category: Blowjob"])
        args = SimpleNamespace(
            config="config.ini", log_level="WARNING", stash_endpoint="http://stash:9999", dry_run=False
        )

        with (
            patch("plexadm.stash_backfill_tags.load_config", return_value=SimpleNamespace(stash_endpoint=None)),
            patch("plexadm.stash_backfill_tags.StashClient", return_value=stash),
        ):
            assert rename_tags(args) == 0

        # "Category: Blowjob" isn't in COMPOSITION_TAGS, so it must be left untouched.
        stash.rename_tag.assert_any_call("1", "Composition: Solo")
        stash.rename_tag.assert_any_call("2", "Composition: Lesbian")
        assert stash.rename_tag.call_count == 2

    def test_skips_a_tag_not_present_in_stash(self) -> None:
        stash = self._stash(["Category: Solo"])
        args = SimpleNamespace(
            config="config.ini", log_level="WARNING", stash_endpoint="http://stash:9999", dry_run=False
        )

        with (
            patch("plexadm.stash_backfill_tags.load_config", return_value=SimpleNamespace(stash_endpoint=None)),
            patch("plexadm.stash_backfill_tags.StashClient", return_value=stash),
        ):
            assert rename_tags(args) == 0

        stash.rename_tag.assert_called_once_with("1", "Composition: Solo")

    def test_skips_on_a_name_collision(self) -> None:
        # Both the old and new name already exist as separate tags - renaming would collide,
        # so this must be left for manual resolution in Stash rather than silently merged.
        stash = self._stash(["Category: Solo", "Composition: Solo"])
        args = SimpleNamespace(
            config="config.ini", log_level="WARNING", stash_endpoint="http://stash:9999", dry_run=False
        )

        with (
            patch("plexadm.stash_backfill_tags.load_config", return_value=SimpleNamespace(stash_endpoint=None)),
            patch("plexadm.stash_backfill_tags.StashClient", return_value=stash),
        ):
            assert rename_tags(args) == 0

        stash.rename_tag.assert_not_called()


class TestBackfillIntegration:
    def test_adds_are_applied_through_helper_with_dry_run(self, tmp_path: Path) -> None:
        path = "/data/NSFW Scenes/Test/test.mp4"
        video = _mock_video(locations=[path])
        scene = {
            "id": "7",
            "files": [{"path": path}],
            "tags": [{"id": "1", "name": "Composition: Solo"}],
        }
        stash = MagicMock()
        stash.all_scenes.return_value = {path: scene}
        stash.all_tags.return_value = []
        collection = SimpleNamespace(title="01: Composition: Solo")
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
        assert "| 01: Composition: Solo | 1 |" in report
        assert "_No ambiguous scenes this run._" in report

    def test_remove_candidates_are_only_written_to_review(self, tmp_path: Path) -> None:
        path = "/data/NSFW Scenes/Test/test.mp4"
        video = _mock_video(
            locations=[path],
            collections=["01: Composition: Solo", "01: Composition: Lesbian"],
        )
        scene = {
            "id": "7",
            "files": [{"path": path}],
            "tags": [{"id": "1", "name": "Composition: Solo"}],
        }
        stash = MagicMock()
        stash.all_scenes.return_value = {path: scene}
        stash.all_tags.return_value = []
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
        assert review[0]["collection_to_remove"] == "01: Composition: Lesbian"
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
                {"id": "1", "name": "Composition: Solo"},
                {"id": "2", "name": "Composition: FFM"},
            ],
        }
        stash = MagicMock()
        stash.all_scenes.return_value = {path: scene}
        stash.all_tags.return_value = []
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
        assert "| Scene \\| One | cross-axis: ['Composition: Solo'] + ['Composition: FFM'] |" in report
        assert "Ambiguous matches staged for review: 1" in report

    def test_taxonomy_merge_adds_to_existing_collection_with_dry_run(self, tmp_path: Path) -> None:
        path = "/data/NSFW Scenes/Test/test.mp4"
        video = _mock_video(locations=[path])
        tag = {
            "id": "10",
            "name": "Blackmail Fantasy",
            "stash_ids": [{"endpoint": "https://stashdb.org/graphql", "stash_id": "abc"}],
        }
        scene = {
            "id": "7",
            "files": [{"path": path}],
            "tags": [{"id": tag["id"], "name": tag["name"]}],
        }
        stash = MagicMock()
        stash.all_scenes.return_value = {path: scene}
        stash.all_tags.return_value = [tag]
        collection = SimpleNamespace(title="01: Category: Blackmail")
        plex_ctx = MagicMock()
        plex_ctx.section.collections.return_value = [collection]
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
            patch("plexadm.stash_backfill_tags.create_collection") as create_collection,
        ):
            assert backfill_tags(args) == 0

        add_items.assert_called_once_with(collection, [video], dry_run=True)
        create_collection.assert_not_called()
        report = args.report_output.read_text(encoding="utf-8")
        assert "- Taxonomy memberships added: 1" in report
        assert "- New collections created: 0" in report
        assert "## Taxonomy additions by collection" in report
        assert "| 01: Category: Blackmail | 1 |" in report

    def test_taxonomy_accepted_add_creates_collection_with_dry_run(self, tmp_path: Path) -> None:
        path = "/data/NSFW Scenes/Test/test.mp4"
        video = _mock_video(locations=[path])
        tag = {
            "id": "10",
            "name": "Missionary",
            "stash_ids": [{"endpoint": "https://stashdb.org/graphql", "stash_id": "abc"}],
        }
        scene = {
            "id": "7",
            "files": [{"path": path}],
            "tags": [{"id": tag["id"], "name": tag["name"]}],
        }
        stash = MagicMock()
        stash.all_scenes.return_value = {path: scene}
        stash.all_tags.return_value = [tag]
        plex_ctx = MagicMock()
        plex_ctx.section.collections.return_value = []
        plex_ctx.all_videos.return_value = [video]
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
            patch("plexadm.stash_backfill_tags.add_items") as add_items,
            patch("plexadm.stash_backfill_tags.create_collection") as create_collection,
        ):
            assert backfill_tags(args) == 0

        add_items.assert_not_called()
        create_collection.assert_called_once_with(
            plex_ctx.section,
            title="01: Activity: Missionary",
            items=[video],
            dry_run=True,
        )
        report = args.report_output.read_text(encoding="utf-8")
        assert "- Taxonomy memberships added: 1" in report
        assert "- New collections created: 1" in report
        assert "| 01: Activity: Missionary (new) | 1 |" in report

    def test_taxonomy_skips_excluded_and_unaccepted_tags(self, tmp_path: Path) -> None:
        path = "/data/NSFW Scenes/Test/test.mp4"
        video = _mock_video(locations=[path])
        tags = [
            {
                "id": "10",
                "name": "4K Available",
                "stash_ids": [{"endpoint": "https://stashdb.org/graphql", "stash_id": "abc"}],
            },
            {
                "id": "11",
                "name": "Ordinary Unreviewed Tag",
                "stash_ids": [{"endpoint": "https://stashdb.org/graphql", "stash_id": "def"}],
            },
        ]
        scene = {
            "id": "7",
            "files": [{"path": path}],
            "tags": [{"id": tag["id"], "name": tag["name"]} for tag in tags],
        }
        stash = MagicMock()
        stash.all_scenes.return_value = {path: scene}
        stash.all_tags.return_value = tags
        plex_ctx = MagicMock()
        plex_ctx.section.collections.return_value = []
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
            patch("plexadm.stash_backfill_tags.create_collection") as create_collection,
        ):
            assert backfill_tags(args) == 0

        add_items.assert_not_called()
        create_collection.assert_not_called()
        report = args.report_output.read_text(encoding="utf-8")
        assert "- Taxonomy memberships added: 0" in report
        assert "## Taxonomy additions by collection" not in report

    def test_composition_and_taxonomy_apply_independently(self, tmp_path: Path) -> None:
        path = "/data/NSFW Scenes/Test/test.mp4"
        video = _mock_video(locations=[path])
        taxonomy_tag = {
            "id": "10",
            "name": "Blackmail Fantasy",
            "stash_ids": [{"endpoint": "https://stashdb.org/graphql", "stash_id": "abc"}],
        }
        scene = {
            "id": "7",
            "files": [{"path": path}],
            "tags": [
                {"id": "1", "name": "Composition: Solo"},
                {"id": taxonomy_tag["id"], "name": taxonomy_tag["name"]},
            ],
        }
        stash = MagicMock()
        stash.all_scenes.return_value = {path: scene}
        stash.all_tags.return_value = [taxonomy_tag]
        composition_collection = SimpleNamespace(title="01: Composition: Solo")
        taxonomy_collection = SimpleNamespace(title="01: Category: Blackmail")
        plex_ctx = MagicMock()
        plex_ctx.section.collections.return_value = [composition_collection, taxonomy_collection]
        plex_ctx.all_videos.return_value = [video]
        plex_ctx.collection.side_effect = {
            composition_collection.title: composition_collection,
            taxonomy_collection.title: taxonomy_collection,
        }.__getitem__
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
            patch("plexadm.stash_backfill_tags.add_items", return_value=1) as add_items,
            patch("plexadm.stash_backfill_tags.create_collection") as create_collection,
        ):
            assert backfill_tags(args) == 0

        assert add_items.call_count == 2
        add_items.assert_any_call(composition_collection, [video], dry_run=False)
        add_items.assert_any_call(taxonomy_collection, [video], dry_run=False)
        create_collection.assert_not_called()
        report = args.report_output.read_text(encoding="utf-8")
        assert "- Composition memberships added: 1" in report
        assert "- Taxonomy memberships added: 1" in report

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
