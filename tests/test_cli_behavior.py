from __future__ import annotations

import argparse
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest

from plexadm import cli


def _args(**overrides: object) -> argparse.Namespace:
    defaults: dict[str, object] = {"config": None, "dry_run": False}
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _video(title: str, **overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "title": title,
        "writers": [],
        "studio": None,
        "collections": [],
        "locations": [],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class TestSmallHelpers:
    def test_context_and_matching_helpers(self, capsys: pytest.CaptureFixture[str]) -> None:
        args = _args(config="plex.yaml")
        video = _video("Writer A - Example (Scene #1)", writers=["Writer A"])

        with patch.object(cli.PlexContext, "from_config", return_value="context") as from_config:
            assert cli.build_context(args) == "context"

        from_config.assert_called_once_with("plex.yaml")
        cli.print_title(video)
        assert capsys.readouterr().out == "Title: Writer A - Example (Scene #1)\n"
        assert cli.is_scene(video) is True
        assert cli.video_matches_text(video, "example") is True
        assert cli.video_matches_text(video, "writer a", startswith=True) is True
        assert cli.video_matches_text(video, "example", startswith=True) is False
        assert cli.video_has_exact_writer(video, "writer a") is True
        assert cli.video_has_exact_writer(video, "Writer") is False


class TestCollectionHandlers:
    def test_add_matching_titles_skips_scenes_and_existing_members(self, capsys: pytest.CaptureFixture[str]) -> None:
        collection = SimpleNamespace(title="Target")
        needed = _video("Writer A - Wanted")
        existing = _video("Writer B - Wanted")
        scene = _video("Writer C - Wanted (Scene #1)")
        unrelated = _video("Writer D - Other")
        ctx = MagicMock()
        ctx.collection.return_value = collection
        ctx.all_videos.return_value = [needed, existing, scene, unrelated]
        args = _args(collection="Target", pattern="wanted", startswith=False, skip_scenes=True, dry_run=True)

        with (
            patch.object(cli, "build_context", return_value=ctx),
            patch.object(cli, "reload_if_partial") as reload_item,
            patch.object(cli, "has_collection", side_effect=lambda video, _title: video is existing),
            patch.object(cli, "add_items", return_value=1) as add_items,
        ):
            assert cli.add_matching_titles(args) == 0

        assert reload_item.call_args_list == [call(needed, force=True), call(existing, force=True)]
        add_items.assert_called_once_with(collection, [needed], dry_run=True)
        output = capsys.readouterr().out
        assert "2 matches found, 1 collections added" in output
        assert "dry run" in output

    def test_add_writer_matches_requires_an_exact_writer(self) -> None:
        collection = SimpleNamespace(title="Target")
        exact = _video("Writer A - Exact", writers=["WRITER A"])
        partial = _video("Writer A - Partial", writers=["Writer Alpha"])
        existing = _video("Writer A - Existing", writers=["Writer A"])
        ctx = MagicMock()
        ctx.collection.return_value = collection
        ctx.all_videos.return_value = [exact, partial, existing, _video("Writer B - Other")]
        args = _args(collection="Target", pattern="Writer A")

        with (
            patch.object(cli, "build_context", return_value=ctx),
            patch.object(cli, "reload_if_partial"),
            patch.object(cli, "has_collection", side_effect=lambda video, _title: video is existing),
            patch.object(cli, "add_items", return_value=1) as add_items,
        ):
            assert cli.add_writer_matches(args) == 0

        add_items.assert_called_once_with(collection, [exact], dry_run=False)

    @pytest.mark.parametrize(
        ("handler", "handler_args", "expected_filters"),
        [
            (
                cli.copy_collection,
                _args(source="Source", target="Target"),
                {"and": [{"collection": "Source"}, {"collection!": "Target"}]},
            ),
            (
                cli.copy_studio,
                _args(studio="Example Studio", collection="Target"),
                {"and": [{"studio": "Example Studio"}, {"collection!": "Target"}]},
            ),
        ],
    )
    def test_copy_handlers_build_filters_and_add_results(
        self,
        handler: object,
        handler_args: argparse.Namespace,
        expected_filters: dict[str, object],
    ) -> None:
        source = SimpleNamespace(title="Source")
        target = SimpleNamespace(title="Target")
        result = _video("Writer A - Example")
        ctx = MagicMock()
        ctx.collection.side_effect = lambda title: source if title == "Source" else target
        ctx.search.return_value = [result]

        with (
            patch.object(cli, "build_context", return_value=ctx),
            patch.object(cli, "add_items", return_value=1) as add_items,
        ):
            assert handler(handler_args) == 0  # type: ignore[operator]

        ctx.search.assert_called_once_with(filters=expected_filters, reload=True)
        add_items.assert_called_once_with(target, [result], dry_run=False)

    def test_remove_matching_titles_only_removes_current_members(self) -> None:
        collection = SimpleNamespace(title="Target")
        member = _video("Writer A - Remove Me")
        outsider = _video("Writer B - Remove Me")
        ctx = MagicMock()
        ctx.collection.return_value = collection
        ctx.all_videos.return_value = [member, outsider, _video("Writer C - Keep")]
        args = _args(collection="Target", pattern="remove")

        with (
            patch.object(cli, "build_context", return_value=ctx),
            patch.object(cli, "reload_if_partial"),
            patch.object(cli, "has_collection", side_effect=lambda video, _title: video is member),
            patch.object(cli, "remove_items", return_value=1) as remove_items,
        ):
            assert cli.remove_matching_titles(args) == 0

        remove_items.assert_called_once_with(collection, [member], dry_run=False)

    def test_add_orgy_uses_writer_count_threshold(self) -> None:
        collection = SimpleNamespace(title="Group")
        match = _video("Group Example", writers=["Writer A", "Writer B", "Writer C"])
        below = _video("Pair Example", writers=["Writer A", "Writer B"])
        ctx = MagicMock()
        ctx.collection.return_value = collection
        ctx.search.return_value = [match, below]

        with (
            patch.object(cli, "build_context", return_value=ctx),
            patch.object(cli, "add_items", return_value=1) as add_items,
        ):
            assert cli.add_orgy_collection(_args(collection="Group", min_writers=3)) == 0

        add_items.assert_called_once_with(collection, [match], dry_run=False)

    def test_add_vertical_uses_first_media_dimensions(self) -> None:
        collection = SimpleNamespace(title="Vertical")
        vertical = _video("Portrait", media=[SimpleNamespace(width=1080, height=1920)])
        landscape = _video("Landscape", media=[SimpleNamespace(width=1920, height=1080)])
        missing = _video("No Media", media=[])
        ctx = MagicMock()
        ctx.collection.return_value = collection
        ctx.search.return_value = [vertical, landscape, missing]

        with (
            patch.object(cli, "build_context", return_value=ctx),
            patch.object(cli, "add_items", return_value=1) as add_items,
        ):
            assert cli.add_vertical_collection(_args(collection="Vertical")) == 0

        add_items.assert_called_once_with(collection, [vertical], dry_run=False)

    def test_add_duration_reports_each_matching_video(self, capsys: pytest.CaptureFixture[str]) -> None:
        collection = SimpleNamespace(title="Short")
        matching = _video("Short Example")
        ctx = MagicMock()
        ctx.collection.return_value = collection
        ctx.search.return_value = [matching]

        with (
            patch.object(cli, "build_context", return_value=ctx),
            patch.object(cli, "add_items", return_value=1) as add_items,
        ):
            assert (
                cli.add_duration_collection(
                    _args(
                        collection="Short",
                        max_duration_ms=60_000,
                        min_duration_ms=None,
                        filters=None,
                    )
                )
                == 0
            )

        add_items.assert_called_once_with(collection, [matching], dry_run=False)
        assert "'Short Example' needs to be added to 'Short'" in capsys.readouterr().out

    def test_sync_unrated_adds_unrated_and_removes_rated_members(self) -> None:
        collection = SimpleNamespace(title="Unrated")
        unrated_video = _video("Unrated Example")
        rated_video = _video("Rated Example")
        ctx = MagicMock()
        ctx.collection.return_value = collection
        ctx.search.side_effect = [[unrated_video], [rated_video]]

        with (
            patch.object(cli, "build_context", return_value=ctx),
            patch.object(cli, "add_items", return_value=1) as add_items,
            patch.object(cli, "remove_items", return_value=1) as remove_items,
        ):
            assert cli.sync_unrated(_args(collection="Unrated")) == 0

        assert ctx.search.call_args_list == [
            call(filters={"and": [{"userRating": -1}, {"collection!": "Unrated"}]}, reload=True),
            call(filters={"and": [{"userRating>>": 0}, {"collection=": "Unrated"}]}, reload=True),
        ]
        add_items.assert_called_once_with(collection, [unrated_video], dry_run=False)
        remove_items.assert_called_once_with(collection, [rated_video], dry_run=False)

    def test_sync_no_studio_reports_new_members(self, capsys: pytest.CaptureFixture[str]) -> None:
        collection = SimpleNamespace(title="No Studio")
        new_member = _video("Missing Studio")
        ctx = MagicMock()
        ctx.collection.return_value = collection
        ctx.search.side_effect = [[new_member], []]

        with (
            patch.object(cli, "build_context", return_value=ctx),
            patch.object(cli, "has_collection", return_value=False),
            patch.object(cli, "add_items", return_value=1) as add_items,
            patch.object(cli, "remove_items", return_value=0),
        ):
            assert cli.sync_no_studio(_args(collection="No Studio")) == 0

        add_items.assert_called_once_with(collection, [new_member], dry_run=False)
        assert "'Missing Studio' needs to be added to 'No Studio'" in capsys.readouterr().out

    def test_lock_collection_titles_counts_successful_locks(self, capsys: pytest.CaptureFixture[str]) -> None:
        first = _video("First")
        second = _video("Second")
        collection = MagicMock(title="Target")
        collection.items.return_value = [first, second]
        ctx = MagicMock()
        ctx.collection.return_value = collection

        with (
            patch.object(cli, "build_context", return_value=ctx),
            patch.object(cli, "reload_if_partial") as reload_item,
            patch.object(cli, "lock_title_and_sort_title", side_effect=[True, False]) as lock,
        ):
            assert cli.lock_collection_titles(_args(collection="Target", dry_run=True)) == 0

        assert reload_item.call_args_list == [call(first, force=True), call(second, force=True)]
        assert lock.call_args_list == [call(first, dry_run=True), call(second, dry_run=True)]
        assert "1 of 2 items" in capsys.readouterr().out

    def test_rename_categories_skips_composition_by_default(self, capsys: pytest.CaptureFixture[str]) -> None:
        activity = SimpleNamespace(title="Old Activity")
        composition = SimpleNamespace(title="Old Composition")
        ctx = MagicMock()
        ctx.section.collections.return_value = [activity, composition]
        renames = {
            "Missing": "New Missing",
            "Old Activity": "New Activity",
            "Old Composition": "New Composition",
            "Same": "Same",
        }

        with (
            patch.object(cli, "build_context", return_value=ctx),
            patch("plexadm.stash_backfill_tags._EXISTING_CATEGORY_RENAMES", renames),
            patch("plexadm.stash_backfill_tags.COMPOSITION_COLLECTIONS", {"Old Composition"}),
            patch.object(cli, "rename_collection") as rename_collection,
        ):
            assert cli.rename_categories(_args(include_composition=False)) == 0

        rename_collection.assert_called_once_with(activity, "New Activity", dry_run=False)
        assert "1 composition collections skipped" in capsys.readouterr().out

    def test_sync_review_collections_add_and_remove_expected_members(self) -> None:
        target = SimpleNamespace(title="Review")
        matching = _video("Single", writers=["Writer A"], ratingKey="1")
        already = _video("Already", writers=["Writer B"], ratingKey="2", collections=["Review"])
        stale = _video("Stale", ratingKey="3")
        ctx = MagicMock()
        ctx.collection.return_value = target
        ctx.search.side_effect = [[matching, already], [already, stale]]

        with (
            patch.object(cli, "build_context", return_value=ctx),
            patch.object(cli, "has_collection", side_effect=lambda video, _title: video is already),
            patch.object(cli, "add_items", return_value=1) as add_items,
            patch.object(cli, "remove_items", return_value=1) as remove_items,
        ):
            assert cli.sync_lesbian_single_writer(_args(collection="Review")) == 0

        add_items.assert_called_once_with(target, [matching], dry_run=False)
        remove_items.assert_called_once_with(target, [stale], dry_run=False)

    def test_sync_cumshot_absent_removes_newly_excluded_members(self) -> None:
        target = SimpleNamespace(title="Review")
        missing = _video("Missing")
        excluded = _video("Excluded", collections=["Excluded Category"])
        retained = _video("Retained", collections=["Review"])
        ctx = MagicMock()
        ctx.collection.return_value = target
        ctx.search.side_effect = [[missing], [excluded, retained]]

        with (
            patch.object(cli, "_cumshot_absent_exclusion_names", return_value={"Excluded Category"}),
            patch.object(cli, "build_context", return_value=ctx),
            patch.object(cli, "add_items", return_value=1) as add_items,
            patch.object(cli, "remove_items", return_value=1) as remove_items,
        ):
            assert cli.sync_cumshot_absent(_args(collection="Review")) == 0

        add_items.assert_called_once_with(target, [missing], dry_run=False)
        remove_items.assert_called_once_with(target, [excluded], dry_run=False)


class TestStudioAndWriterHandlers:
    def test_set_studio_for_title_matches_handles_validation_and_existing_values(self) -> None:
        unrelated = _video("Writer B - Other")
        wrong_writer = _video("Writer A - Wrong Writer", writers=["Writer B"])
        scene = _video("Writer A - Feature (Scene #1)", writers=["Writer A"])
        blank = _video("Writer A - Blank", writers=["Writer A"])
        same = _video("Writer A - Same", writers=["Writer A"], studio="New Studio")
        other = _video("Writer A - Other", writers=["Writer A"], studio="Old Studio")
        ctx = MagicMock()
        ctx.all_videos.return_value = [unrelated, wrong_writer, scene, blank, same, other]
        args = _args(pattern="Writer A", studio="New Studio", require_writer=True, skip_scenes=True)

        with (
            patch.object(cli, "build_context", return_value=ctx),
            patch.object(cli, "reload_if_partial"),
            patch.object(cli, "set_studio", return_value=True) as set_studio,
        ):
            assert cli.set_studio_for_title_matches(args) == 0

        set_studio.assert_called_once_with(blank, "New Studio", dry_run=False)

    def test_set_independent_requires_title_and_exact_writer_and_skips_scenes(self) -> None:
        exact = _video("Writer A - Exact", writers=["Writer A"])
        wrong = _video("Writer A - Wrong", writers=["Writer B"])
        scene = _video("Writer A - Scene (Scene #1)", writers=["Writer A"])
        unrelated = _video("Writer B - Other", writers=["Writer B"])
        ctx = MagicMock()
        ctx.search.return_value = [exact, wrong, scene, unrelated]

        with (
            patch.object(cli, "build_context", return_value=ctx),
            patch.object(cli, "read_writer_file", return_value=["Writer A"]),
            patch.object(cli, "reload_if_partial"),
            patch.object(cli, "set_studio", return_value=True) as set_studio,
        ):
            assert cli.set_independent_for_writers_file(_args(file="writers.txt")) == 0

        set_studio.assert_called_once_with(exact, cli.INDEPENDENT_STUDIO, dry_run=False)

    def test_rename_studio_updates_every_exact_match(self) -> None:
        first = _video("First")
        second = _video("Second")
        ctx = MagicMock()
        ctx.search.return_value = [first, second]

        with (
            patch.object(cli, "build_context", return_value=ctx),
            patch.object(cli, "set_studio", side_effect=[True, False]) as set_studio,
        ):
            assert cli.rename_studio(_args(old="Old", new="New", dry_run=True)) == 0

        ctx.search.assert_called_once_with(studio__exact="Old", sort="titleSort", reload=True)
        assert set_studio.call_args_list == [call(first, "New", dry_run=True), call(second, "New", dry_run=True)]

    def test_set_writers_from_titles_adds_all_title_writers_when_any_are_missing(self) -> None:
        changed = _video("Writer A, Writer B - Example")
        complete = _video("Writer C - Complete")
        ctx = MagicMock()
        ctx.all_videos.return_value = [changed, complete]

        with (
            patch.object(cli, "build_context", return_value=ctx),
            patch.object(cli, "reload_if_partial"),
            patch.object(cli, "missing_title_writers", side_effect=[["Writer B"], []]),
            patch.object(cli, "writers_from_title", return_value=["Writer A", "Writer B"]),
            patch.object(cli, "add_writer", return_value=True) as add_writer,
        ):
            assert cli.set_writers_from_titles(_args()) == 0

        add_writer.assert_called_once_with(changed, ["Writer A", "Writer B"], dry_run=False)

    def test_set_writers_and_sync_runs_both_steps(self) -> None:
        args = _args()
        with (
            patch.object(cli, "set_writers_from_titles", return_value=0) as set_writers,
            patch.object(cli, "sync_smart_collections", return_value=7) as sync,
        ):
            assert cli.set_writers_and_sync(args) == 7

        set_writers.assert_called_once_with(args)
        sync.assert_called_once_with(args)


class TestListHandlers:
    @pytest.mark.parametrize("source", ["search", "collection", "studio", "writer", "no_studio", "all"])
    def test_list_videos_selects_the_requested_source(self, source: str, capsys: pytest.CaptureFixture[str]) -> None:
        video = _video("Writer A - Example")
        ctx = MagicMock()
        ctx.search.return_value = [video]
        ctx.collection.return_value.items.return_value = [video]
        ctx.all_videos.return_value = [video]
        values: dict[str, object] = {
            "search_title": None,
            "collection": None,
            "studio": None,
            "writer": None,
            "no_studio": False,
            "reload": True,
            "title": None,
            "startswith": None,
            "regex": None,
            "no_title_spaces": False,
        }
        if source == "search":
            values["search_title"] = "Example"
        elif source == "collection":
            values["collection"] = "Target"
        elif source == "studio":
            values["studio"] = "Example Studio"
        elif source == "writer":
            values["writer"] = "Writer A"
        elif source == "no_studio":
            values["no_studio"] = True

        with patch.object(cli, "build_context", return_value=ctx), patch.object(cli, "reload_if_partial"):
            assert cli.list_videos(_args(**values)) == 0

        assert "Title: Writer A - Example" in capsys.readouterr().out
        if source == "search":
            ctx.search.assert_called_once_with(filters={"title": "Example"}, reload=True)
        elif source == "collection":
            ctx.collection.assert_called_once_with("Target")
        elif source == "studio":
            ctx.search.assert_called_once_with(studio__exact="Example Studio", sort="titleSort", reload=True)
        elif source == "writer":
            ctx.search.assert_called_once_with(filters={"writer": "Writer A"}, reload=True)
        elif source == "no_studio":
            ctx.search.assert_called_once_with(studio__exact="", sort="titleSort", reload=False)
        else:
            ctx.all_videos.assert_called_once_with(reload=True)

    def test_list_videos_composes_client_side_title_filters(self, capsys: pytest.CaptureFixture[str]) -> None:
        accepted = _video("Writer A - Target Example")
        wrong_title = _video("Writer A - Other")
        wrong_prefix = _video("Writer B - Target Example")
        wrong_regex = _video("Writer A - Target Different")
        ctx = MagicMock()
        ctx.all_videos.return_value = [accepted, wrong_title, wrong_prefix, wrong_regex]
        args = _args(
            search_title=None,
            collection=None,
            studio=None,
            writer=None,
            no_studio=False,
            reload=False,
            title="target",
            startswith="writer a",
            regex="example$",
            no_title_spaces=False,
        )

        with patch.object(cli, "build_context", return_value=ctx):
            assert cli.list_videos(args) == 0

        assert capsys.readouterr().out == "Title: Writer A - Target Example\n"

    def test_list_collections_filters_and_tolerates_item_errors(self, capsys: pytest.CaptureFixture[str]) -> None:
        good = MagicMock(title="Keep Good")
        good.items.return_value = [1, 2]
        broken = MagicMock(title="Keep Broken")
        broken.items.side_effect = RuntimeError("unavailable")
        skipped = MagicMock(title="Other")
        ctx = MagicMock()
        ctx.section.collections.return_value = [good, broken, skipped]

        with patch.object(cli, "build_context", return_value=ctx), patch.object(cli, "reload_if_partial"):
            assert cli.list_collections(_args(pattern="keep")) == 0

        output = capsys.readouterr().out
        assert "   2: Keep Good" in output
        assert "   0: Keep Broken" in output
        assert "Other" not in output

    def test_list_studios_counts_and_filters(self, capsys: pytest.CaptureFixture[str]) -> None:
        ctx = MagicMock()
        ctx.all_videos.return_value = [
            _video("One", studio="Example Studio"),
            _video("Two", studio="Example Studio"),
            _video("Three", studio="Other Studio"),
            _video("Four"),
        ]

        with patch.object(cli, "build_context", return_value=ctx), patch.object(cli, "reload_if_partial"):
            assert cli.list_studios(_args(pattern="example")) == 0

        output = capsys.readouterr().out
        assert "   2: Example Studio" in output
        assert "Other Studio" not in output

    def test_writer_lists_count_repeated_values(self, capsys: pytest.CaptureFixture[str]) -> None:
        first = _video("One", writers=["Writer A", "Writer B"])
        second = _video("Two", writers=["Writer A"])
        ctx = MagicMock()
        ctx.collection.return_value.items.return_value = [first, second]
        ctx.search.return_value = [first, second]

        with patch.object(cli, "build_context", return_value=ctx), patch.object(cli, "reload_if_partial"):
            assert cli.list_writers(_args(collection="Target")) == 0
            assert cli.list_studio_writers(_args(studio="Example Studio")) == 0

        output = capsys.readouterr().out
        assert output.count("   2: Writer A") == 2
        ctx.search.assert_called_once_with(studio__exact="Example Studio", sort="titleSort", reload=True)

    @pytest.mark.parametrize(
        ("kind", "video"),
        [
            ("uncategorized", _video("Uncategorized")),
            ("no-hair", _video("No Hair")),
            ("uncollected", _video("Uncollected")),
            ("merged", _video("Merged", guids=["one", "two"])),
            ("potential-indie", _video("Writer A - Example")),
            ("multi-f-without-category", _video("Writer A, Writer B - Example")),
        ],
    )
    def test_list_special_kinds_report_matching_videos(
        self, kind: str, video: SimpleNamespace, capsys: pytest.CaptureFixture[str]
    ) -> None:
        ctx = MagicMock()
        ctx.search.return_value = [video]
        ctx.all_videos.return_value = [video]
        with (
            patch.object(cli, "build_context", return_value=ctx),
            patch.object(cli, "collection_titles", return_value=set()),
            patch.object(cli, "writers_from_title", return_value=["Writer A", "Writer B"]),
        ):
            assert cli.list_special(_args(kind=kind, base_dir="/media")) == 0

        assert f"Title: {video.title}" in capsys.readouterr().out

    def test_list_special_rejects_an_unknown_kind(self) -> None:
        with patch.object(cli, "build_context"), pytest.raises(ValueError, match="Unsupported special list kind"):
            cli.list_special(_args(kind="unknown", base_dir="/media"))


class TestSmartCollectionsAndInventory:
    def test_generated_studio_filters_ignore_invalid_collections(self, capsys: pytest.CaptureFixture[str]) -> None:
        unrelated = MagicMock(title="Manual")
        nonsmart = MagicMock(title="02: Studio: Manual", smart=False)
        broken = MagicMock(title="02: Studio: Broken", smart=True)
        broken.filters.side_effect = RuntimeError("bad filter")
        compound = MagicMock(title="02: Studio: Compound", smart=True)
        compound.filters.return_value = {"filters": {"and": [{"studio": "Compound"}]}}
        valid = MagicMock(title="02: Studio: Example", smart=True)
        valid.filters.return_value = {"filters": {"studio": "Example Studio"}}

        with patch.object(cli, "reload_if_partial"):
            assert cli._generated_studio_filter_values([unrelated, nonsmart, broken, compound, valid]) == {
                "example studio": {"Example Studio"}
            }

        assert "Unable to read smart collection filters" in capsys.readouterr().out

    def test_conflicting_generated_studio_filters_without_a_majority_are_unresolved(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        videos = [_video("One", studio="EXAMPLE"), _video("Two", studio="Example")]
        upper = MagicMock(title="02: Studio: EXAMPLE", smart=True)
        upper.filters.return_value = {"filters": {"studio": "EXAMPLE"}}
        mixed = MagicMock(title="02: Studio: Example", smart=True)
        mixed.filters.return_value = {"filters": {"studio": "Example"}}

        with patch.object(cli, "reload_if_partial"):
            canonical, unresolved = cli._canonical_studio_spellings(videos, [upper, mixed])

        assert canonical == {}
        assert unresolved == {"example"}
        assert "no unique library majority" in capsys.readouterr().out

    def test_sync_smart_collections_creates_writer_collection(self) -> None:
        video = _video("Writer A - Example", writers=["Writer A"])
        ctx = MagicMock()
        ctx.all_videos.return_value = [video]
        ctx.section.collections.return_value = []

        with (
            patch.object(cli, "build_context", return_value=ctx),
            patch.object(cli, "create_smart_collection") as create,
        ):
            assert cli.sync_smart_collections(_args()) == 0

        create.assert_called_once_with(
            ctx.section,
            title="03: Star: Writer A",
            sort="titleSort:asc",
            filters={"writer": "Writer A"},
            dry_run=False,
        )

    def test_require_inventory_config_rejects_missing_section(self) -> None:
        with (
            patch.object(cli, "load_inventory_config", return_value=None),
            pytest.raises(ValueError, match=r"No \[inventory\] section configured"),
        ):
            cli._require_inventory_config(_args(config="plex.yaml"))

    def test_require_inventory_config_returns_configured_section(self) -> None:
        config = SimpleNamespace(index="inventory")
        with patch.object(cli, "load_inventory_config", return_value=config):
            assert cli._require_inventory_config(_args(config="plex.yaml")) is config

    def test_inventory_diff_reports_attributed_and_unattributed_changes(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        config = SimpleNamespace(index="inventory")
        audit_config = SimpleNamespace(sink="opensearch", opensearch=SimpleNamespace(index="audit-index"))
        changes = [
            SimpleNamespace(title="B", added=["New"], removed=[], attributed=True),
            SimpleNamespace(title="A", added=[], removed=["Old"], attributed=False),
        ]
        args = _args(run_a="run-1", run_b="run-2", no_attribution=False)

        with (
            patch.object(cli, "_require_inventory_config", return_value=config),
            patch.object(cli, "load_logging_config", return_value=audit_config),
            patch("plexadm.inventory.diff_snapshots", return_value=("run-1", "run-2", changes)) as diff,
        ):
            assert cli.inventory_diff(args) == 0

        diff.assert_called_once_with(config, run_a="run-1", run_b="run-2", audit_index="audit-index")
        output = capsys.readouterr().out
        assert "'A' lost: Old [UNATTRIBUTED" in output
        assert "'B' gained: New" in output
        assert "2 videos changed, 1 with at least one unattributed change" in output

    def test_inventory_diff_without_changes_skips_audit_lookup(self, capsys: pytest.CaptureFixture[str]) -> None:
        config = SimpleNamespace(index="inventory")
        args = _args(run_a=None, run_b=None, no_attribution=True)

        with (
            patch.object(cli, "_require_inventory_config", return_value=config),
            patch.object(cli, "load_logging_config") as load_logging,
            patch("plexadm.inventory.diff_snapshots", return_value=("first", "second", [])) as diff,
        ):
            assert cli.inventory_diff(args) == 0

        load_logging.assert_not_called()
        diff.assert_called_once_with(config, run_a=None, run_b=None, audit_index=None)
        assert "No collection membership changes" in capsys.readouterr().out


class TestCollectionMaintenance:
    def test_retarget_writer_ppv_updates_only_simple_matching_smart_collection(self) -> None:
        old = MagicMock(title="Old PPV")
        new = MagicMock(title="New PPV")
        item = _video("Writer A - Example")
        old.items.return_value = [item]
        simple = MagicMock(title="Writer A Picks", smart=True)
        simple.filters.return_value = {"sort": "titleSort:asc", "filters": {"collection": "old-key"}}
        compound = MagicMock(title="Writer A Compound", smart=True)
        compound.filters.return_value = {"filters": {"collection": "old-key", "writer": "Writer A"}}
        no_reference = MagicMock(title="Writer A Other", smart=True)
        no_reference.filters.return_value = {"filters": {"collection": "different-key"}}
        unrelated = MagicMock(title="Other Picks", smart=True)
        ctx = MagicMock()
        ctx.collection.side_effect = lambda title: old if title == "Old PPV" else new
        ctx.section.collections.return_value = [simple, compound, no_reference, unrelated]
        args = _args(
            old_collection="Old PPV",
            new_collection="New PPV",
            name_contains="Writer A",
            writer="Writer A",
        )

        with (
            patch.object(cli, "build_context", return_value=ctx),
            patch.object(cli, "collection_filter_key", return_value="old-key"),
            patch.object(cli, "has_collection", return_value=False),
            patch.object(cli, "reload_if_partial"),
            patch.object(cli, "add_items", return_value=1),
            patch.object(cli, "remove_items", return_value=1),
            patch.object(cli, "update_smart_collection_filters") as update,
        ):
            assert cli.retarget_writer_ppv(args) == 0

        update.assert_called_once_with(
            simple,
            section=ctx.section,
            sort="titleSort:asc",
            filters={"and": [{"collection": "New PPV"}, {"writer": "Writer A"}]},
            dry_run=False,
        )

    def test_rename_collections_applies_regex_only_to_changed_titles(self) -> None:
        changed = MagicMock(title="Old Prefix: Example")
        unchanged = MagicMock(title="Other")
        ctx = MagicMock()
        ctx.section.collections.return_value = [changed, unchanged]

        with (
            patch.object(cli, "build_context", return_value=ctx),
            patch.object(cli, "reload_if_partial"),
            patch.object(cli, "rename_collection") as rename,
        ):
            assert cli.rename_collections(_args(pattern="^Old Prefix", replacement="New Prefix")) == 0

        rename.assert_called_once_with(changed, "New Prefix: Example", dry_run=False)


class TestToolsAndTop:
    @pytest.mark.parametrize(
        "title, location",
        [
            ("Writer A - Message 1", "/media/different - Message 1.mp4"),
            ("Writer A - Question?", "/media/different.mp4"),
            ("Writer A - Café", "/media/different.mp4"),
        ],
    )
    def test_rename_candidates_ignore_intentionally_nonstandard_filenames(self, title: str, location: str) -> None:
        ctx = MagicMock()
        ctx.all_videos.return_value = [_video(title, locations=[location])]
        assert list(cli._rename_candidates(ctx, None)) == []

    def test_find_missing_file_reports_matches_and_failure(self, capsys: pytest.CaptureFixture[str]) -> None:
        ctx = MagicMock()
        ctx.all_videos.return_value = [_video("Found", locations=["/media/found.mp4"])]

        with patch.object(cli, "build_context", return_value=ctx):
            assert cli.find_missing_file(_args(path="/media/found.mp4")) == 0
            assert cli.find_missing_file(_args(path="/media/missing.mp4")) == 1

        output = capsys.readouterr().out
        assert "Title: Found" in output
        assert "No Plex item found for /media/missing.mp4" in output

    def test_filename_formatters_and_mapping_output(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        mapping = tmp_path / "map.json"
        mapping.write_text('{"b": "two", "a": "one"}', encoding="utf-8")

        assert cli.fix_dl_scene_name(_args(filename="clip.mp4", prefix=None)) == 0
        assert cli.fix_dl_scene_name(_args(filename="clip.mp4", prefix="Writer A")) == 0
        assert cli.fix_ultrafilms_name(_args(filename="example_writer.mp4")) == 0
        assert cli.gen_ofdl_names(_args(map_file=str(mapping))) == 0

        output = capsys.readouterr().out.splitlines()
        assert output == [
            "TBD - clip.mp4",
            "Writer A - clip.mp4",
            "Example Writer.mp4",
            "a: one",
            "b: two",
        ]
        assert cli.ultrafilms_titleize("black_angel") == "Black Angel aka Kate Rose"

    def test_ofdl_rsync_returns_subprocess_status(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch.object(cli.subprocess, "call", return_value=23) as subprocess_call:
            assert cli.ofdl_rsync(_args(source="source/", destination="host:dest/")) == 23

        subprocess_call.assert_called_once_with(["rsync", "-avh", "--progress", "source/", "host:dest/"])
        assert "rsync -avh --progress source/ host:dest/" in capsys.readouterr().out

    def test_remove_fps_title_moves_to_clean_name(self) -> None:
        with patch.object(cli.shutil, "move") as move:
            assert cli.remove_fps_title(_args(filename="/media/example_24fps.mp4")) == 0

        move.assert_called_once_with("/media/example_24fps.mp4", "/media/example.mp4")

    def test_upload_vids_uses_temporary_remote_name_then_unlinks(self, tmp_path: Path) -> None:
        first = tmp_path / "Writer A - First.mp4"
        second = tmp_path / "Writer B, Writer C - Second.mp4"
        first.touch()
        second.touch()

        with (
            patch.object(cli.Path, "cwd", return_value=tmp_path),
            patch.object(cli.subprocess, "run") as run,
            patch.object(cli.Path, "unlink") as unlink,
        ):
            assert cli.upload_vids(_args(upload_path="/uploads", remote_host="media-host")) == 0

        expected_calls = [
            call(["ssh", "media-host", "mkdir", "/uploads/Writer A"], check=False),
            call(
                ["scp", str(first), "media-host:/uploads/Writer A/Writer A - First.mp4.tmp"],
                check=True,
            ),
            call(
                [
                    "ssh",
                    "media-host",
                    "mv",
                    "/uploads/Writer A/Writer A - First.mp4.tmp",
                    "/uploads/Writer A/Writer A - First.mp4",
                ],
                check=True,
            ),
            call(["ssh", "media-host", "mkdir", "/uploads/Writer B"], check=False),
            call(
                ["scp", str(second), "media-host:/uploads/Writer B/Writer B, Writer C - Second.mp4.tmp"],
                check=True,
            ),
            call(
                [
                    "ssh",
                    "media-host",
                    "mv",
                    "/uploads/Writer B/Writer B, Writer C - Second.mp4.tmp",
                    "/uploads/Writer B/Writer B, Writer C - Second.mp4",
                ],
                check=True,
            ),
        ]
        assert run.call_count == len(expected_calls)
        run.assert_has_calls(expected_calls, any_order=True)
        assert unlink.call_count == 2

    @pytest.mark.parametrize("source", ["categories", "studios", "writers-without-studios"])
    def test_print_top_sources(self, source: str, capsys: pytest.CaptureFixture[str]) -> None:
        ctx = MagicMock()
        collection = MagicMock(title="01: Activity: Example")
        collection.items.return_value = [1, 2]
        ctx.section.collections.return_value = [collection, MagicMock(title="Unrelated")]
        ctx.all_videos.return_value = [
            _video("Writer A - One", studio="Example Studio"),
            _video("Writer A - Two", studio="Example Studio"),
            _video("Writer B - Three", studio="Other Studio"),
        ]
        ctx.search.return_value = [_video("Writer A - One"), _video("Writer A - Two")]
        args = _args(source=source, limit=5, collection=None, scenes=False)

        with patch.object(cli, "build_context", return_value=ctx), patch.object(cli, "reload_if_partial"):
            assert cli.print_top(args) == 0

        output = capsys.readouterr().out
        if source == "categories":
            assert "   2: 01: Activity: Example" in output
        elif source == "studios":
            assert "   2: Example Studio" in output
        else:
            assert "   2: Writer A" in output

    def test_print_top_scene_filter_excludes_non_scene_titles(self, capsys: pytest.CaptureFixture[str]) -> None:
        ctx = MagicMock()
        ctx.search.return_value = [
            _video("Writer A - Feature (Scene #1)"),
            _video("Writer B - Standalone"),
        ]

        with patch.object(cli, "build_context", return_value=ctx):
            assert (
                cli.print_top(
                    _args(
                        source="scenes-without-studios",
                        limit=5,
                        collection=None,
                        scenes=True,
                    )
                )
                == 0
            )

        output = capsys.readouterr().out
        assert "Writer A" in output
        assert "Writer B" not in output


class TestArgumentDispatch:
    @pytest.mark.parametrize(
        ("argv", "handler", "attribute", "value"),
        [
            (["list", "videos", "--writer", "Writer A"], cli.list_videos, "writer", "Writer A"),
            (["collection", "add-title", "Target", "needle"], cli.add_matching_titles, "pattern", "needle"),
            (["studio", "rename", "Old", "New"], cli.rename_studio, "new", "New"),
            (["writers", "set-from-titles"], cli.set_writers_from_titles, "writers_command", "set-from-titles"),
            (["smart-collections", "sync"], cli.sync_smart_collections, "smart_command", "sync"),
            (["tools", "fix-dl-scene-name", "clip.mp4"], cli.fix_dl_scene_name, "filename", "clip.mp4"),
            (["top", "studios", "--limit", "3"], cli.print_top, "limit", 3),
            (["stash", "reconcile", "--limit", "2"], cli.stash_reconcile, "limit", 2),
            (["inventory", "diff", "--run-a", "one"], cli.inventory_diff, "run_a", "one"),
        ],
    )
    def test_parser_routes_command_families(
        self, argv: list[str], handler: object, attribute: str, value: object
    ) -> None:
        args = cli.build_parser().parse_args(argv)
        assert args.func is handler
        assert getattr(args, attribute) == value

    def test_main_marks_scene_top_sources_and_returns_audit_failure(self, capsys: pytest.CaptureFixture[str]) -> None:
        seen: list[argparse.Namespace] = []

        def handler(args: argparse.Namespace) -> int:
            seen.append(args)
            return 0

        parser = MagicMock()
        parser.parse_args.return_value = _args(
            func=handler,
            command="top",
            source="unrated-scenes",
            scenes=False,
        )
        with (
            patch.object(cli, "build_parser", return_value=parser),
            patch.object(cli, "load_logging_config", return_value=SimpleNamespace()),
            patch.object(cli.audit, "configure"),
            patch.object(cli.audit, "set_invocation_context"),
            patch.object(cli.audit, "log_event"),
            patch.object(cli.audit, "has_failures", return_value=True),
        ):
            assert cli.main([]) == 1

        assert seen[0].scenes is True
        assert "audit log writes failed" in capsys.readouterr().out
