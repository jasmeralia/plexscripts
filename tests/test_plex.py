from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from plexadm.audit import AuditEvent
from plexadm.plex import (
    LOCKED_COLLECTION,
    add_items,
    add_writer,
    create_collection,
    create_smart_collection,
    delete_collection,
    lock_title_and_sort_title,
    remove_items,
    rename_collection,
    rename_title,
    set_studio,
    update_smart_collection_filters,
)


def _filter_choice(title: str, key: str) -> SimpleNamespace:
    return SimpleNamespace(title=title, key=key)


def _video(**kwargs: object) -> SimpleNamespace:
    defaults: dict[str, object] = {
        "title": "Test Video",
        "ratingKey": 42,
        "studio": None,
        "titleSort": None,
        "collections": [],
        "edit": MagicMock(),
        "addWriter": MagicMock(),
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _collection(title: str = "01: Category: Test") -> SimpleNamespace:
    return SimpleNamespace(
        title=title,
        addItems=MagicMock(),
        removeItems=MagicMock(),
        editTitle=MagicMock(),
        editSortTitle=MagicMock(),
        delete=MagicMock(),
    )


class TestAddRemoveItems:
    def test_add_drops_locked_items(self) -> None:
        collection = _collection()
        locked = _video(collections=[LOCKED_COLLECTION])
        unlocked = _video(title="Unlocked", ratingKey=7)

        with patch("plexadm.plex.log_event") as mock_log:
            count = add_items(collection, [locked, unlocked])

        assert count == 1
        collection.addItems.assert_called_once_with([unlocked])
        mock_log.assert_called_once()

    def test_remove_drops_locked_items(self) -> None:
        collection = _collection()
        locked = _video(collections=[LOCKED_COLLECTION])
        unlocked = _video(title="Unlocked", ratingKey=7)

        with patch("plexadm.plex.log_event") as mock_log:
            count = remove_items(collection, [locked, unlocked])

        assert count == 1
        collection.removeItems.assert_called_once_with([unlocked])
        mock_log.assert_called_once()

    def test_locked_target_does_not_drop_locked_item(self) -> None:
        collection = _collection(LOCKED_COLLECTION)
        locked = _video(collections=[LOCKED_COLLECTION])

        with patch("plexadm.plex.log_event"):
            count = remove_items(collection, [locked])

        assert count == 1
        collection.removeItems.assert_called_once_with([locked])

    @pytest.mark.parametrize(
        "bypass_title",
        [
            "01: Category: Short Videos",
            "01: Category: Vertical Video",
            "00C: Unrated",
            "00A: NO STUDIO",
            "01: Category: PPV",
        ],
    )
    def test_add_and_remove_bypass_lock_for_format_collections(self, bypass_title: str) -> None:
        # These describe a fact about the file itself (duration, orientation, rating, studio
        # presence), not a content judgment call, so locked videos should still get tagged.
        collection = _collection(bypass_title)
        locked = _video(collections=[LOCKED_COLLECTION])

        with patch("plexadm.plex.log_event"):
            assert add_items(collection, [locked]) == 1
            assert remove_items(collection, [locked]) == 1

        collection.addItems.assert_called_once_with([locked])
        collection.removeItems.assert_called_once_with([locked])

    def test_dry_run_makes_no_api_calls_but_logs_at_debug(self) -> None:
        collection = _collection()
        video = _video()

        with patch("plexadm.plex.log_event") as mock_log:
            assert add_items(collection, [video], dry_run=True) == 1
            assert remove_items(collection, [video], dry_run=True) == 1

        collection.addItems.assert_not_called()
        collection.removeItems.assert_not_called()
        events = [call.args[0] for call in mock_log.call_args_list]
        assert events == [
            AuditEvent(
                action="add",
                level="DEBUG",
                title=video.title,
                rating_key=video.ratingKey,
                collection=collection.title,
                details={"dry_run": True},
            ),
            AuditEvent(
                action="remove",
                level="DEBUG",
                title=video.title,
                rating_key=video.ratingKey,
                collection=collection.title,
                details={"dry_run": True},
            ),
        ]

    def test_real_add_logs_each_surviving_item(self) -> None:
        collection = _collection()
        first = _video(title="First", ratingKey=1)
        second = _video(title="Second", ratingKey=2)

        with patch("plexadm.plex.log_event") as mock_log:
            assert add_items(collection, [first, second]) == 2

        events = [call.args[0] for call in mock_log.call_args_list]
        assert events == [
            AuditEvent(action="add", title="First", rating_key=1, collection=collection.title),
            AuditEvent(action="add", title="Second", rating_key=2, collection=collection.title),
        ]

    def test_real_remove_logs_each_surviving_item(self) -> None:
        collection = _collection()
        video = _video(title="Removed", ratingKey=9)

        with patch("plexadm.plex.log_event") as mock_log:
            assert remove_items(collection, [video]) == 1

        mock_log.assert_called_once_with(
            AuditEvent(action="remove", title="Removed", rating_key=9, collection=collection.title)
        )


class TestSetStudioAddWriterRenameCreate:
    def test_set_studio_skips_locked_video(self) -> None:
        video = _video(collections=[LOCKED_COLLECTION])

        with patch("plexadm.plex.log_event") as mock_log:
            assert set_studio(video, "New Studio") is False

        video.edit.assert_not_called()
        mock_log.assert_not_called()

    def test_set_studio_dry_run_makes_no_edit_but_logs_at_debug(self) -> None:
        video = _video(studio="Old Studio")

        with patch("plexadm.plex.log_event") as mock_log:
            assert set_studio(video, "New Studio", dry_run=True) is True

        video.edit.assert_not_called()
        mock_log.assert_called_once_with(
            AuditEvent(
                action="edit_studio",
                level="DEBUG",
                title=video.title,
                rating_key=video.ratingKey,
                details={"old_studio": "Old Studio", "new_studio": "New Studio", "dry_run": True},
            )
        )

    def test_set_studio_edits_and_logs(self) -> None:
        video = _video(studio="Old Studio")

        with patch("plexadm.plex.log_event") as mock_log:
            assert set_studio(video, "New Studio") is True

        video.edit.assert_called_once_with(**{"studio.value": "New Studio", "label.locked": 1})
        mock_log.assert_called_once_with(
            AuditEvent(
                action="edit_studio",
                title=video.title,
                rating_key=video.ratingKey,
                details={"old_studio": "Old Studio", "new_studio": "New Studio"},
            )
        )

    def test_add_writer_skips_locked_video(self) -> None:
        video = _video(collections=[LOCKED_COLLECTION])

        with patch("plexadm.plex.log_event") as mock_log:
            assert add_writer(video, ["Alice"]) is False

        video.addWriter.assert_not_called()
        mock_log.assert_not_called()

    def test_add_writer_dry_run_makes_no_edit_but_logs_at_debug(self) -> None:
        video = _video()

        with patch("plexadm.plex.log_event") as mock_log:
            assert add_writer(video, ["Alice"], dry_run=True) is True

        video.addWriter.assert_not_called()
        mock_log.assert_called_once_with(
            AuditEvent(
                action="add_writer",
                level="DEBUG",
                title=video.title,
                rating_key=video.ratingKey,
                details={"writers": ["Alice"], "dry_run": True},
            )
        )

    def test_add_writer_edits_and_logs(self) -> None:
        video = _video()

        with patch("plexadm.plex.log_event") as mock_log:
            assert add_writer(video, ["Alice", "Bob"]) is True

        video.addWriter.assert_called_once_with(["Alice", "Bob"], True)
        mock_log.assert_called_once_with(
            AuditEvent(
                action="add_writer",
                title=video.title,
                rating_key=video.ratingKey,
                details={"writers": ["Alice", "Bob"]},
            )
        )

    def test_lock_title_and_sort_title_is_not_skipped_for_a_locked_video(self) -> None:
        # Unlike rename_title, this only locks each field to its own current value - it
        # preserves existing metadata rather than altering it, so the 99: LOCKED
        # collection-membership guard doesn't apply here.
        video = _video(title="My Title", titleSort="My Title", collections=[LOCKED_COLLECTION])

        with patch("plexadm.plex.log_event") as mock_log:
            assert lock_title_and_sort_title(video) is True

        video.edit.assert_called_once_with(
            **{"title.value": "My Title", "title.locked": 1, "titleSort.value": "My Title", "titleSort.locked": 1}
        )
        mock_log.assert_called_once()

    def test_lock_title_and_sort_title_dry_run_makes_no_edit_but_logs_at_debug(self) -> None:
        video = _video(title="My Title", titleSort="My Title")

        with patch("plexadm.plex.log_event") as mock_log:
            assert lock_title_and_sort_title(video, dry_run=True) is True

        video.edit.assert_not_called()
        mock_log.assert_called_once_with(
            AuditEvent(
                action="lock_title",
                level="DEBUG",
                title=video.title,
                rating_key=video.ratingKey,
                details={"title": "My Title", "sort_title": "My Title", "dry_run": True},
            )
        )

    def test_lock_title_and_sort_title_edits_and_logs(self) -> None:
        video = _video(title="My Title", titleSort="My Title")

        with patch("plexadm.plex.log_event") as mock_log:
            assert lock_title_and_sort_title(video) is True

        video.edit.assert_called_once_with(
            **{"title.value": "My Title", "title.locked": 1, "titleSort.value": "My Title", "titleSort.locked": 1}
        )
        mock_log.assert_called_once_with(
            AuditEvent(
                action="lock_title",
                title=video.title,
                rating_key=video.ratingKey,
                details={"title": "My Title", "sort_title": "My Title"},
            )
        )

    def test_lock_title_and_sort_title_falls_back_to_title_when_sort_title_missing(self) -> None:
        # titleSort is None when Plex hasn't set an explicit sort title yet.
        video = _video(title="My Title", titleSort=None)

        with patch("plexadm.plex.log_event"):
            assert lock_title_and_sort_title(video) is True

        video.edit.assert_called_once_with(
            **{"title.value": "My Title", "title.locked": 1, "titleSort.value": "My Title", "titleSort.locked": 1}
        )

    def test_rename_title_skips_locked_video(self) -> None:
        video = _video(collections=[LOCKED_COLLECTION])

        with patch("plexadm.plex.log_event") as mock_log:
            assert rename_title(video, "New Title") is False

        video.edit.assert_not_called()
        mock_log.assert_not_called()

    def test_rename_title_dry_run_makes_no_edit_but_logs_at_debug(self) -> None:
        video = _video(title="Old Title")

        with patch("plexadm.plex.log_event") as mock_log:
            assert rename_title(video, "New Title", dry_run=True) is True

        video.edit.assert_not_called()
        mock_log.assert_called_once_with(
            AuditEvent(
                action="rename_title",
                level="DEBUG",
                title="New Title",
                rating_key=video.ratingKey,
                details={"old_title": "Old Title", "dry_run": True},
            )
        )

    def test_rename_title_edits_title_and_sort_title_and_locks_both(self) -> None:
        video = _video(title="Old Title")

        with patch("plexadm.plex.log_event") as mock_log:
            assert rename_title(video, "New Title") is True

        video.edit.assert_called_once_with(
            **{"title.value": "New Title", "title.locked": 1, "titleSort.value": "New Title", "titleSort.locked": 1}
        )
        mock_log.assert_called_once_with(
            AuditEvent(
                action="rename_title",
                title="New Title",
                rating_key=video.ratingKey,
                details={"old_title": "Old Title"},
            )
        )

    def test_rename_collection_dry_run_makes_no_edit_but_logs_at_debug(self) -> None:
        collection = _collection("Old Title")

        with patch("plexadm.plex.log_event") as mock_log:
            rename_collection(collection, "New Title", dry_run=True)

        collection.editTitle.assert_not_called()
        collection.editSortTitle.assert_not_called()
        mock_log.assert_called_once_with(
            AuditEvent(
                action="rename_collection",
                level="DEBUG",
                title="New Title",
                details={"old_title": "Old Title", "dry_run": True},
            )
        )

    def test_rename_collection_edits_and_logs(self) -> None:
        collection = _collection("Old Title")

        with patch("plexadm.plex.log_event") as mock_log:
            rename_collection(collection, "New Title")

        collection.editTitle.assert_called_once_with("New Title")
        mock_log.assert_called_once_with(
            AuditEvent(action="rename_collection", title="New Title", details={"old_title": "Old Title"})
        )

    def test_rename_collection_also_syncs_the_sort_title(self) -> None:
        # Real bug found live: the taxonomy migration's bulk rename only called editTitle(),
        # leaving titleSort stale (e.g. "01: Activity: Anal" still sorting as "01: Category:
        # Anal") - a rename always means title and sort title move together.
        collection = _collection("Old Title")

        with patch("plexadm.plex.log_event"):
            rename_collection(collection, "New Title")

        collection.editSortTitle.assert_called_once_with("New Title")

    def test_create_collection_creates_with_seed_items_and_logs(self) -> None:
        section = SimpleNamespace(createCollection=MagicMock())
        video = _video(title="Seed Video", ratingKey=99)

        with patch("plexadm.plex.log_event") as mock_log:
            create_collection(section, title="00D: Review: New", items=[video])

        section.createCollection.assert_called_once_with(title="00D: Review: New", items=[video])
        mock_log.assert_called_once_with(
            AuditEvent(action="create_manual_collection", title="00D: Review: New", details={"item_count": 1})
        )

    def test_create_collection_drops_locked_items(self) -> None:
        # Real gap found in review: create_collection() bypassed _drop_locked() entirely, so
        # seeding a brand-new review collection could silently add a '99: LOCKED' video's
        # membership - exactly what the LOCKED guard exists to prevent, regardless of which
        # command is doing the adding.
        section = SimpleNamespace(createCollection=MagicMock())
        locked = _video(title="Locked Video", ratingKey=1, collections=[LOCKED_COLLECTION])
        unlocked = _video(title="Unlocked Video", ratingKey=2)

        with patch("plexadm.plex.log_event"):
            create_collection(section, title="00D: Review: New", items=[locked, unlocked])

        section.createCollection.assert_called_once_with(title="00D: Review: New", items=[unlocked])

    def test_create_collection_bypasses_lock_for_format_collections(self) -> None:
        section = SimpleNamespace(createCollection=MagicMock())
        locked = _video(title="Locked Video", ratingKey=1, collections=[LOCKED_COLLECTION])

        with patch("plexadm.plex.log_event"):
            create_collection(section, title="01: Category: Vertical Video", items=[locked])

        section.createCollection.assert_called_once_with(title="01: Category: Vertical Video", items=[locked])

    def test_create_collection_dry_run_makes_no_call_but_logs_at_debug(self) -> None:
        section = SimpleNamespace(createCollection=MagicMock())
        video = _video(title="Seed Video", ratingKey=99)

        with patch("plexadm.plex.log_event") as mock_log:
            create_collection(section, title="00D: Review: New", items=[video], dry_run=True)

        section.createCollection.assert_not_called()
        mock_log.assert_called_once_with(
            AuditEvent(
                action="create_manual_collection",
                level="DEBUG",
                title="00D: Review: New",
                details={"item_count": 1, "dry_run": True},
            )
        )

    def test_delete_collection_deletes_and_logs(self) -> None:
        collection = _collection("00A: Rin (PPVs)")

        with patch("plexadm.plex.log_event") as mock_log:
            delete_collection(collection)

        collection.delete.assert_called_once_with()
        mock_log.assert_called_once_with(AuditEvent(action="delete_collection", title="00A: Rin (PPVs)", details={}))

    def test_delete_collection_dry_run_makes_no_call_but_logs_at_debug(self) -> None:
        collection = _collection("00A: Rin (PPVs)")

        with patch("plexadm.plex.log_event") as mock_log:
            delete_collection(collection, dry_run=True)

        collection.delete.assert_not_called()
        mock_log.assert_called_once_with(
            AuditEvent(action="delete_collection", level="DEBUG", title="00A: Rin (PPVs)", details={"dry_run": True})
        )

    def test_create_smart_collection_dry_run_makes_no_call_but_logs_at_debug(self) -> None:
        section = SimpleNamespace(createCollection=MagicMock())
        filters = {"writer": "Alice"}

        with patch("plexadm.plex.log_event") as mock_log:
            create_smart_collection(
                section,
                title="Smart",
                sort="titleSort:asc",
                filters=filters,
                dry_run=True,
            )

        section.createCollection.assert_not_called()
        mock_log.assert_called_once_with(
            AuditEvent(
                action="create_collection",
                level="DEBUG",
                title="Smart",
                details={"filters": filters, "dry_run": True},
            )
        )

    def test_create_smart_collection_creates_and_logs(self) -> None:
        section = SimpleNamespace(createCollection=MagicMock())
        filters = {"writer": "Alice"}

        with patch("plexadm.plex.log_event") as mock_log:
            create_smart_collection(section, title="Smart", sort="titleSort:asc", filters=filters)

        section.createCollection.assert_called_once_with(
            title="Smart", smart=True, sort="titleSort:asc", filters=filters
        )
        mock_log.assert_called_once_with(
            AuditEvent(action="create_collection", title="Smart", details={"filters": filters})
        )

    def test_create_smart_collection_resolves_a_collection_title_to_its_filter_choice_id(self) -> None:
        # Real bug found on a live run: the collection's own .ratingKey is a *different* ID
        # space from what the "collection" smart-filter parameter expects - passing .ratingKey
        # doesn't error, it silently matches a different, unrelated collection instead. Callers
        # must be able to just pass the title, the same way "writer"/"studio" already take plain
        # names - this is what makes that safe.
        section = SimpleNamespace(
            createCollection=MagicMock(),
            listFilterChoices=MagicMock(
                return_value=[_filter_choice("01: Activity: Anal", "27385"), _filter_choice("Other", "1")]
            ),
        )

        with patch("plexadm.plex.log_event"):
            create_smart_collection(
                section,
                title="00C: Anal Favorite Models (Alice)",
                sort="viewCount:desc",
                filters={"collection": "01: Activity: Anal", "writer": "Alice"},
            )

        section.listFilterChoices.assert_called_once_with("collection")
        section.createCollection.assert_called_once_with(
            title="00C: Anal Favorite Models (Alice)",
            smart=True,
            sort="viewCount:desc",
            filters={"collection": "27385", "writer": "Alice"},
        )

    def test_create_smart_collection_leaves_an_already_resolved_int_untouched(self) -> None:
        section = SimpleNamespace(createCollection=MagicMock(), listFilterChoices=MagicMock())

        with patch("plexadm.plex.log_event"):
            create_smart_collection(
                section, title="Smart", sort="titleSort:asc", filters={"collection": 27385, "writer": "Alice"}
            )

        section.listFilterChoices.assert_not_called()
        section.createCollection.assert_called_once_with(
            title="Smart", smart=True, sort="titleSort:asc", filters={"collection": 27385, "writer": "Alice"}
        )

    def test_create_smart_collection_raises_when_the_collection_title_does_not_match(self) -> None:
        section = SimpleNamespace(createCollection=MagicMock(), listFilterChoices=MagicMock(return_value=[]))

        with patch("plexadm.plex.log_event"), pytest.raises(ValueError, match="No collection filter choice"):
            create_smart_collection(
                section, title="Smart", sort="titleSort:asc", filters={"collection": "Does Not Exist"}
            )

        section.createCollection.assert_not_called()

    def test_create_smart_collection_raises_on_an_ambiguous_collection_title(self) -> None:
        section = SimpleNamespace(
            createCollection=MagicMock(),
            listFilterChoices=MagicMock(return_value=[_filter_choice("Dup", "1"), _filter_choice("Dup", "2")]),
        )

        with patch("plexadm.plex.log_event"), pytest.raises(ValueError, match="Multiple collection filter choices"):
            create_smart_collection(section, title="Smart", sort="titleSort:asc", filters={"collection": "Dup"})

        section.createCollection.assert_not_called()

    def test_create_smart_collection_resolution_also_applies_to_dry_run(self) -> None:
        section = SimpleNamespace(
            createCollection=MagicMock(),
            listFilterChoices=MagicMock(return_value=[_filter_choice("01: Activity: Anal", "27385")]),
        )

        with patch("plexadm.plex.log_event") as mock_log:
            create_smart_collection(
                section,
                title="Smart",
                sort="viewCount:desc",
                filters={"collection": "01: Activity: Anal"},
                dry_run=True,
            )

        section.createCollection.assert_not_called()
        mock_log.assert_called_once_with(
            AuditEvent(
                action="create_collection",
                level="DEBUG",
                title="Smart",
                details={"filters": {"collection": "27385"}, "dry_run": True},
            )
        )

    def test_update_smart_collection_filters_deletes_and_recreates(self) -> None:
        # Real bug found live: plexapi's Collection.updateFilters() can leave an existing smart
        # collection's cached membership index stuck at 0 items even though the new filter is
        # valid - survives both collection.refresh() and a full Plex server restart. Delete +
        # recreate is what actually fixed it, since a freshly created smart collection builds
        # its index at creation time like every other one already does.
        section = SimpleNamespace(createCollection=MagicMock())
        collection = SimpleNamespace(title="00A: Star (PPVs)", delete=MagicMock())
        filters = {"and": [{"collection": "01: Category: PPV"}, {"writer": "Star"}]}

        with patch("plexadm.plex.log_event") as mock_log:
            update_smart_collection_filters(collection, section=section, sort="viewCount:desc", filters=filters)

        collection.delete.assert_called_once_with()
        section.createCollection.assert_called_once_with(
            title="00A: Star (PPVs)", smart=True, sort="viewCount:desc", filters=filters
        )
        events = [call.args[0] for call in mock_log.call_args_list]
        assert events == [
            AuditEvent(action="delete_collection", title="00A: Star (PPVs)", details={}),
            AuditEvent(action="create_collection", title="00A: Star (PPVs)", details={"filters": filters}),
        ]

    def test_update_smart_collection_filters_resolves_a_top_level_collection_title_on_recreate(self) -> None:
        section = SimpleNamespace(
            createCollection=MagicMock(),
            listFilterChoices=MagicMock(return_value=[_filter_choice("01: Category: PPV", "226728")]),
        )
        collection = SimpleNamespace(title="Smart", delete=MagicMock())

        with patch("plexadm.plex.log_event"):
            update_smart_collection_filters(
                collection, section=section, sort=None, filters={"collection": "01: Category: PPV"}
            )

        section.createCollection.assert_called_once_with(
            title="Smart", smart=True, sort=None, filters={"collection": "226728"}
        )

    def test_update_smart_collection_filters_dry_run_makes_no_calls_but_logs_at_debug(self) -> None:
        section = SimpleNamespace(createCollection=MagicMock())
        collection = SimpleNamespace(title="Smart", delete=MagicMock())
        filters = {"writer": "Alice"}

        with patch("plexadm.plex.log_event") as mock_log:
            update_smart_collection_filters(collection, section=section, sort=None, filters=filters, dry_run=True)

        collection.delete.assert_not_called()
        section.createCollection.assert_not_called()
        events = [call.args[0] for call in mock_log.call_args_list]
        assert events == [
            AuditEvent(action="delete_collection", level="DEBUG", title="Smart", details={"dry_run": True}),
            AuditEvent(
                action="create_collection",
                level="DEBUG",
                title="Smart",
                details={"filters": filters, "dry_run": True},
            ),
        ]
