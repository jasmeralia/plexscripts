from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from plexadm.audit import AuditEvent
from plexadm.plex import (
    LOCKED_COLLECTION,
    add_items,
    add_writer,
    create_smart_collection,
    lock_title_and_sort_title,
    remove_items,
    rename_collection,
    set_studio,
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

    def test_lock_title_and_sort_title_skips_locked_video(self) -> None:
        video = _video(collections=[LOCKED_COLLECTION])

        with patch("plexadm.plex.log_event") as mock_log:
            assert lock_title_and_sort_title(video) is False

        video.edit.assert_not_called()
        mock_log.assert_not_called()

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

    def test_rename_collection_dry_run_makes_no_edit_but_logs_at_debug(self) -> None:
        collection = _collection("Old Title")

        with patch("plexadm.plex.log_event") as mock_log:
            rename_collection(collection, "New Title", dry_run=True)

        collection.editTitle.assert_not_called()
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
