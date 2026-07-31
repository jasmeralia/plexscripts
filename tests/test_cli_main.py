from __future__ import annotations

import argparse
from unittest.mock import MagicMock, patch

import pytest

from plexadm import audit, cli
from plexadm.audit import AuditEvent


def _fake_parser(args: argparse.Namespace) -> MagicMock:
    parser = MagicMock()
    parser.parse_args.return_value = args
    return parser


def _events_by_action(mock_log_event: MagicMock, action: str) -> list[AuditEvent]:
    return [call.args[0] for call in mock_log_event.call_args_list if call.args[0].action == action]


class TestDryRunFlagHonorsEnvVar:
    # Real gap found live (2026-07-28): --dry-run's help text has always claimed
    # PLEXADM_DRY_RUN=1 was honored, but nothing ever actually read the env var - confirmed by
    # checking argparse's own default before the fix.
    def test_defaults_to_false_when_env_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PLEXADM_DRY_RUN", raising=False)
        args = cli.build_parser().parse_args(["inventory", "snapshot"])
        assert args.dry_run is False

    def test_env_var_sets_the_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PLEXADM_DRY_RUN", "1")
        args = cli.build_parser().parse_args(["inventory", "snapshot"])
        assert args.dry_run is True

    def test_explicit_flag_still_wins_when_env_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PLEXADM_DRY_RUN", raising=False)
        args = cli.build_parser().parse_args(["inventory", "snapshot", "--dry-run"])
        assert args.dry_run is True


class TestMainErrorAndInterruptLogging:
    def test_exception_from_command_is_logged_as_error(self) -> None:
        def failing_command(_args: argparse.Namespace) -> int:
            raise RuntimeError("boom")

        args = argparse.Namespace(func=failing_command, config=None, dry_run=False, command="list")

        with (
            patch.object(cli, "build_parser", return_value=_fake_parser(args)),
            patch.object(audit, "log_event") as mock_log_event,
        ):
            result = cli.main([])

        assert result == 1
        errors = _events_by_action(mock_log_event, "error")
        assert len(errors) == 1
        assert errors[0].level == "ERROR"
        assert errors[0].title == "boom"
        assert errors[0].details == {"exception_type": "RuntimeError"}

    def test_keyboard_interrupt_is_logged_as_warning(self) -> None:
        def interrupted_command(_args: argparse.Namespace) -> int:
            raise KeyboardInterrupt

        args = argparse.Namespace(func=interrupted_command, config=None, dry_run=False, command="list")

        with (
            patch.object(cli, "build_parser", return_value=_fake_parser(args)),
            patch.object(audit, "log_event") as mock_log_event,
        ):
            result = cli.main([])

        assert result == 130
        interruptions = _events_by_action(mock_log_event, "interrupted")
        assert len(interruptions) == 1
        assert interruptions[0].level == "WARNING"
        assert "interrupted_command" in interruptions[0].title

    def test_successful_command_does_not_log_error_or_interrupt(self) -> None:
        audit._FAILURE_COUNT = 0
        args = argparse.Namespace(func=lambda _args: 0, config=None, dry_run=False, command="list")

        with (
            patch.object(cli, "build_parser", return_value=_fake_parser(args)),
            patch.object(audit, "log_event") as mock_log_event,
        ):
            result = cli.main([])

        assert result == 0
        assert _events_by_action(mock_log_event, "error") == []
        assert _events_by_action(mock_log_event, "interrupted") == []


class TestMainTimingEvent:
    def test_successful_command_logs_timing_at_info(self) -> None:
        args = argparse.Namespace(func=lambda _args: 0, config=None, dry_run=False, command="list")

        with (
            patch.object(cli, "build_parser", return_value=_fake_parser(args)),
            patch.object(audit, "log_event") as mock_log_event,
        ):
            cli.main([])

        timings = _events_by_action(mock_log_event, "timing")
        assert len(timings) == 1
        assert timings[0].level == "INFO"
        assert "<lambda>" in timings[0].title
        assert isinstance(timings[0].details["duration_seconds"], float)
        assert timings[0].details["duration_seconds"] >= 0

    def test_timing_is_still_logged_when_command_raises(self) -> None:
        def failing_command(_args: argparse.Namespace) -> int:
            raise RuntimeError("boom")

        args = argparse.Namespace(func=failing_command, config=None, dry_run=False, command="list")

        with (
            patch.object(cli, "build_parser", return_value=_fake_parser(args)),
            patch.object(audit, "log_event") as mock_log_event,
        ):
            cli.main([])

        timings = _events_by_action(mock_log_event, "timing")
        assert len(timings) == 1
        assert timings[0].details["duration_seconds"] >= 0


class TestSyncNoStudio:
    def test_removal_query_uses_the_working_kwarg_filter_not_the_broken_dict_one(self) -> None:
        # Real bug found on a live run: the dict-style advanced filter {"studio!": ""} silently
        # returns zero results for every video regardless of whether studio is actually set -
        # confirmed against the real library, where it missed real videos a studio__ne=""
        # kwarg-style query correctly found. A video (Independent Content) sat in "00A: NO
        # STUDIO" indefinitely because of this - sync_no_studio always reported "0 removed".
        collection = MagicMock()
        collection.title = "00A: NO STUDIO"
        stale_member = MagicMock(title="Has A Studio Now")

        ctx = MagicMock()
        ctx.collection.return_value = collection
        ctx.search.side_effect = [[], [stale_member]]

        args = argparse.Namespace(config=None, collection="00A: NO STUDIO", dry_run=False)

        with (
            patch.object(cli, "build_context", return_value=ctx),
            patch.object(cli, "add_items", return_value=0) as mock_add_items,
            patch.object(cli, "remove_items", return_value=1) as mock_remove_items,
        ):
            assert cli.sync_no_studio(args) == 0

        removal_call = ctx.search.call_args_list[1]
        assert removal_call.kwargs.get("studio__ne") == ""
        assert removal_call.kwargs.get("filters") == {"collection=": "00A: NO STUDIO"}
        assert "studio!" not in str(removal_call.kwargs.get("filters"))
        mock_remove_items.assert_called_once_with(collection, [stale_member], dry_run=False)
        mock_add_items.assert_called_once_with(collection, [], dry_run=False)


class TestAddDurationCollection:
    def test_defaults_to_short_video_bound_when_no_bounds_given(self) -> None:
        collection = MagicMock(title="01: Category: Short Videos")
        ctx = MagicMock()
        ctx.collection.return_value = collection
        ctx.search.return_value = []

        args = argparse.Namespace(
            config=None,
            dry_run=False,
            collection="01: Category: Short Videos",
            max_duration_ms=None,
            min_duration_ms=None,
            filters=None,
        )

        with patch.object(cli, "build_context", return_value=ctx), patch.object(cli, "add_items", return_value=0):
            assert cli.add_duration_collection(args) == 0

        used = ctx.search.call_args.kwargs["filters"]["and"]
        assert {"duration<<": cli.DEFAULT_SHORT_VIDEO_MAX_DURATION_MS} in used
        assert not any("duration>>" in part for part in used)

    def test_min_only_does_not_apply_the_short_video_default(self) -> None:
        # Real risk: silently keeping the old 90s default max bound alongside an explicit
        # --min-duration-ms would make min > max, so the query would always return nothing.
        collection = MagicMock(title="00D: Review: Indie Long No Livestream")
        ctx = MagicMock()
        ctx.collection.return_value = collection
        ctx.search.return_value = []

        args = argparse.Namespace(
            config=None,
            dry_run=False,
            collection="00D: Review: Indie Long No Livestream",
            max_duration_ms=None,
            min_duration_ms=3_600_000,
            filters=None,
        )

        with patch.object(cli, "build_context", return_value=ctx), patch.object(cli, "add_items", return_value=0):
            assert cli.add_duration_collection(args) == 0

        used = ctx.search.call_args.kwargs["filters"]["and"]
        assert {"duration>>": 3_600_000} in used
        assert not any("duration<<" in part for part in used)

    def test_ad_hoc_filters_json_is_and_combined_with_the_duration_bound(self) -> None:
        collection = MagicMock(title="00D: Review: Indie Long No Livestream")
        ctx = MagicMock()
        ctx.collection.return_value = collection
        ctx.search.return_value = []

        args = argparse.Namespace(
            config=None,
            dry_run=False,
            collection="00D: Review: Indie Long No Livestream",
            max_duration_ms=None,
            min_duration_ms=3_600_000,
            filters='{"studio": "Independent Content", "collection!": "01: Theme: Live Stream"}',
        )

        with patch.object(cli, "build_context", return_value=ctx), patch.object(cli, "add_items", return_value=0):
            assert cli.add_duration_collection(args) == 0

        used = ctx.search.call_args.kwargs["filters"]["and"]
        assert {"studio": "Independent Content"} in used
        assert {"collection!": "01: Theme: Live Stream"} in used
        assert {"duration>>": 3_600_000} in used


class TestCumshotAbsentExclusionNames:
    def test_excludes_compilations(self) -> None:
        # A compilation aggregates clips from many separate sources/scenes, so it isn't expected
        # to carry one single cumshot tag the way a normal scene would.
        assert "01: Category: Compilation" in cli._cumshot_absent_exclusion_names()


class TestSyncSmartCollections:
    @staticmethod
    def _video(title: str, studio: str) -> MagicMock:
        return MagicMock(title=title, studio=studio, writers=[])

    @staticmethod
    def _studio_collection(title: str, studio_filter: str) -> MagicMock:
        collection = MagicMock(title=title, smart=True)
        collection.filters.return_value = {"filters": {"studio": studio_filter}}
        return collection

    def test_existing_collection_filter_is_the_canonical_studio_spelling(self) -> None:
        canonical = self._video("Canonical", "EXAMPLE STUDIO")
        variant = self._video("Variant", "Example Studio")
        collection = self._studio_collection("02: Studio: EXAMPLE STUDIO", "EXAMPLE STUDIO")
        ctx = MagicMock()
        ctx.all_videos.return_value = [canonical, variant]
        ctx.section.collections.return_value = [collection]
        args = argparse.Namespace(config=None, dry_run=False)

        with (
            patch.object(cli, "build_context", return_value=ctx),
            patch.object(cli, "set_studio", return_value=True) as mock_set_studio,
            patch.object(cli, "create_smart_collection") as mock_create,
        ):
            assert cli.sync_smart_collections(args) == 0

        mock_set_studio.assert_called_once_with(variant, "EXAMPLE STUDIO", dry_run=False)
        mock_create.assert_not_called()

    def test_special_independent_collection_uses_its_filter_not_its_title(self) -> None:
        variant = self._video("Variant", "independent content")
        collection = self._studio_collection("02: Independent Content", "Independent Content")
        ctx = MagicMock()
        ctx.all_videos.return_value = [variant]
        ctx.section.collections.return_value = [collection]
        args = argparse.Namespace(config=None, dry_run=True)

        with (
            patch.object(cli, "build_context", return_value=ctx),
            patch.object(cli, "set_studio", return_value=True) as mock_set_studio,
            patch.object(cli, "create_smart_collection") as mock_create,
        ):
            assert cli.sync_smart_collections(args) == 0

        mock_set_studio.assert_called_once_with(variant, "Independent Content", dry_run=True)
        mock_create.assert_not_called()

    def test_new_case_variants_use_unique_majority_and_create_one_collection(self) -> None:
        first = self._video("First", "Example Studio")
        second = self._video("Second", "Example Studio")
        variant = self._video("Variant", "example studio")
        ctx = MagicMock()
        ctx.all_videos.return_value = [first, second, variant]
        ctx.section.collections.return_value = []
        args = argparse.Namespace(config=None, dry_run=False)

        with (
            patch.object(cli, "build_context", return_value=ctx),
            patch.object(cli, "set_studio", return_value=True) as mock_set_studio,
            patch.object(cli, "create_smart_collection") as mock_create,
        ):
            assert cli.sync_smart_collections(args) == 0

        mock_set_studio.assert_called_once_with(variant, "Example Studio", dry_run=False)
        mock_create.assert_called_once_with(
            ctx.section,
            title="02: Studio: Example Studio",
            sort="titleSort:asc",
            filters={"studio": "Example Studio"},
            dry_run=False,
        )

    def test_library_majority_resolves_conflicting_existing_filter_spellings(self) -> None:
        first = self._video("First", "EXAMPLE STUDIO")
        second = self._video("Second", "EXAMPLE STUDIO")
        variant = self._video("Variant", "Example Studio")
        upper_collection = self._studio_collection("02: Studio: EXAMPLE STUDIO", "EXAMPLE STUDIO")
        mixed_collection = self._studio_collection("02: Studio: Example Studio", "Example Studio")
        ctx = MagicMock()
        ctx.all_videos.return_value = [first, second, variant]
        ctx.section.collections.return_value = [upper_collection, mixed_collection]
        args = argparse.Namespace(config=None, dry_run=False)

        with (
            patch.object(cli, "build_context", return_value=ctx),
            patch.object(cli, "set_studio", return_value=True) as mock_set_studio,
            patch.object(cli, "create_smart_collection") as mock_create,
        ):
            assert cli.sync_smart_collections(args) == 0

        mock_set_studio.assert_called_once_with(variant, "EXAMPLE STUDIO", dry_run=False)
        mock_create.assert_not_called()

    def test_new_case_variants_with_tied_counts_are_left_for_review(self) -> None:
        upper = self._video("Upper", "EXAMPLE STUDIO")
        mixed = self._video("Mixed", "Example Studio")
        ctx = MagicMock()
        ctx.all_videos.return_value = [upper, mixed]
        ctx.section.collections.return_value = []
        args = argparse.Namespace(config=None, dry_run=False)

        with (
            patch.object(cli, "build_context", return_value=ctx),
            patch.object(cli, "set_studio") as mock_set_studio,
            patch.object(cli, "create_smart_collection") as mock_create,
        ):
            assert cli.sync_smart_collections(args) == 0

        mock_set_studio.assert_not_called()
        mock_create.assert_not_called()


class TestAddSearchResults:
    def test_exclude_collection_adds_plex_side_filters(self) -> None:
        collection = MagicMock(title="01: Composition: Solo")
        ctx = MagicMock()
        ctx.collection.return_value = collection
        ctx.search.return_value = []

        args = argparse.Namespace(
            config=None,
            dry_run=False,
            collection="01: Composition: Solo",
            pattern="myself",
            exclude_collection=["01: Composition: MF Only"],
            exclude_collection_prefix=None,
        )

        with patch.object(cli, "build_context", return_value=ctx), patch.object(cli, "add_items", return_value=0):
            assert cli.add_search_results(args) == 0

        used = ctx.search.call_args.kwargs["filters"]["and"]
        assert {"collection!": "01: Composition: MF Only"} in used

    def test_exclude_collection_prefix_filters_client_side(self) -> None:
        # Real bug found live: a title match for "myself" added a video already tagged
        # '01: Composition: MF Only' to Solo - Plex's filter DSL can only exclude one exact
        # collection at a time, so a whole-family exclusion has to happen after the search,
        # against each video's already-reloaded collection list.
        collection = MagicMock(title="01: Composition: Solo")
        mf_only_video = MagicMock(title="Serika - Want Him All To Myself", collections=["01: Composition: MF Only"])
        clean_video = MagicMock(title="Someone - By Myself", collections=[])

        ctx = MagicMock()
        ctx.collection.return_value = collection
        ctx.search.return_value = [mf_only_video, clean_video]

        args = argparse.Namespace(
            config=None,
            dry_run=False,
            collection="01: Composition: Solo",
            pattern="myself",
            exclude_collection=None,
            exclude_collection_prefix=["01: Composition:"],
        )

        with (
            patch.object(cli, "build_context", return_value=ctx),
            patch.object(cli, "add_items", return_value=1) as mock_add_items,
        ):
            assert cli.add_search_results(args) == 0

        mock_add_items.assert_called_once_with(collection, [clean_video], dry_run=False)


class TestAddPpv:
    def test_only_adds_never_removes(self) -> None:
        # Real bug found live: filename-based removal was dropping genuinely valid PPV videos
        # whose files had since been renamed away from the raw platform export naming (e.g. to
        # a cleaner descriptive title), even though the content itself was still PPV. Fixed to
        # be add-only - a filename no longer matching never removes an existing member.
        collection = MagicMock(title="01: Category: PPV")
        matching = MagicMock(
            title="Some Writer - PPV - 123456_789012_2020-01-01",
            locations=["/media/Some Writer - PPV - 123456_789012_2020-01-01.mp4"],
        )
        non_matching = MagicMock(
            title="Some Writer - Renamed Title", locations=["/media/Some Writer - Renamed Title.mp4"]
        )

        ctx = MagicMock()
        ctx.collection.return_value = collection
        ctx.search.return_value = [matching, non_matching]

        args = argparse.Namespace(config=None, collection="01: Category: PPV", dry_run=False)

        with (
            patch.object(cli, "build_context", return_value=ctx),
            patch.object(cli, "add_items", return_value=1) as mock_add_items,
            patch.object(cli, "remove_items") as mock_remove_items,
        ):
            assert cli.add_ppv(args) == 0

        assert ctx.search.call_count == 1
        mock_add_items.assert_called_once_with(collection, [matching], dry_run=False)
        mock_remove_items.assert_not_called()


class TestAddWritersFile:
    def test_single_writer_only_skips_multi_writer_matches(self) -> None:
        # Real bug found live: a listed Solo performer co-starring in someone else's scene
        # got that multi-writer scene tagged Solo too, since add-writers only checks whether
        # any listed writer matches, not how many writers the video has in total.
        collection = MagicMock(title="01: Composition: Solo")
        solo_video = MagicMock(title="00 Rin - Eve", writers=["00 Rin"])
        multi_writer_video = MagicMock(title="00 Rin, Nixy - Second Breakfast #2", writers=["00 Rin", "Nixy"])

        ctx = MagicMock()
        ctx.collection.return_value = collection
        ctx.search.return_value = [solo_video, multi_writer_video]

        args = argparse.Namespace(
            config=None,
            collection="01: Composition: Solo",
            file="writers_solo.txt",
            single_writer_only=True,
            dry_run=False,
        )

        with (
            patch.object(cli, "build_context", return_value=ctx),
            patch.object(cli, "read_writer_file", return_value=["00 Rin"]),
            patch.object(cli, "add_items", return_value=1) as mock_add_items,
        ):
            assert cli.add_writers_file(args) == 0

        mock_add_items.assert_called_once_with(collection, [solo_video], dry_run=False)

    def test_single_writer_only_false_keeps_multi_writer_matches(self) -> None:
        collection = MagicMock(title="01: Attributes: Asian")
        multi_writer_video = MagicMock(title="Writer A, Writer B - Scene", writers=["Writer A", "Writer B"])

        ctx = MagicMock()
        ctx.collection.return_value = collection
        ctx.search.return_value = [multi_writer_video]

        args = argparse.Namespace(
            config=None,
            collection="01: Attributes: Asian",
            file="writers_asian.txt",
            single_writer_only=False,
            dry_run=False,
        )

        with (
            patch.object(cli, "build_context", return_value=ctx),
            patch.object(cli, "read_writer_file", return_value=["Writer A"]),
            patch.object(cli, "add_items", return_value=1) as mock_add_items,
        ):
            assert cli.add_writers_file(args) == 0

        mock_add_items.assert_called_once_with(collection, [multi_writer_video], dry_run=False)


class TestRetargetWriterPpv:
    def test_resolves_old_collection_filter_key_before_emptying_it(self) -> None:
        # Real bug found live: resolving OLD's smart-filter ID via collection_filter_key()
        # AFTER remove_items() had already emptied OLD failed outright - Plex stops offering an
        # empty collection as a "collection" filter choice at all, so a smart collection
        # referencing OLD could never be retargeted once OLD had already been drained mid-run.
        # The fix resolves the key first, while OLD still has members.
        call_order: list[str] = []

        old = MagicMock(title="01: Rin PPV")
        new = MagicMock(title="01: Category: PPV")
        video = MagicMock(title="00 Rin - Example", collections=[])
        old.items.return_value = [video]

        ctx = MagicMock()
        ctx.collection.side_effect = lambda name: old if name == "01: Rin PPV" else new
        ctx.section.collections.return_value = []

        def fake_collection_filter_key(_section: object, title: str) -> str:
            call_order.append(f"resolve:{title}")
            return "169711"

        def fake_remove_items(_collection: object, items: list[object], *, dry_run: bool = False) -> int:
            call_order.append("remove")
            return len(list(items))

        args = argparse.Namespace(
            config=None,
            dry_run=False,
            writer="00 Rin",
            old_collection="01: Rin PPV",
            new_collection="01: Category: PPV",
            name_contains="Rin",
        )

        with (
            patch.object(cli, "build_context", return_value=ctx),
            patch.object(cli, "add_items", return_value=0),
            patch.object(cli, "remove_items", side_effect=fake_remove_items),
            patch.object(cli, "collection_filter_key", side_effect=fake_collection_filter_key),
        ):
            assert cli.retarget_writer_ppv(args) == 0

        assert call_order == ["resolve:01: Rin PPV", "remove"]


class TestCloneSmartCollection:
    def test_and_combines_source_filters_with_add_filter(self) -> None:
        source = MagicMock(title="00D: Review: No Hair Color", smart=True)
        source.filters.return_value = {
            "sort": ["movie.titleSort"],
            "filters": {"and": [{"collection!": "129138"}]},
        }

        ctx = MagicMock()
        ctx.collection.return_value = source

        args = argparse.Namespace(
            config=None,
            dry_run=False,
            source="00D: Review: No Hair Color",
            target="00D: Review: No Hair Color (Indie)",
            add_filter='{"studio": "Independent"}',
        )

        with (
            patch.object(cli, "build_context", return_value=ctx),
            patch.object(cli, "create_smart_collection") as mock_create,
        ):
            assert cli.clone_smart_collection(args) == 0

        mock_create.assert_called_once_with(
            ctx.section,
            title="00D: Review: No Hair Color (Indie)",
            sort=["movie.titleSort"],
            filters={"and": [{"and": [{"collection!": "129138"}]}, {"studio": "Independent"}]},
            dry_run=False,
        )

    def test_rejects_non_smart_source(self) -> None:
        source = MagicMock(title="00A: NO STUDIO", smart=False)
        ctx = MagicMock()
        ctx.collection.return_value = source

        args = argparse.Namespace(
            config=None,
            dry_run=False,
            source="00A: NO STUDIO",
            target="Whatever",
            add_filter='{"studio": "Independent"}',
        )

        with (
            patch.object(cli, "build_context", return_value=ctx),
            patch.object(cli, "create_smart_collection") as mock_create,
        ):
            assert cli.clone_smart_collection(args) == 1

        mock_create.assert_not_called()
