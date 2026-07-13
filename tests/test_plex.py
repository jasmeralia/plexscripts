from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from plexadm.audit import MutationEvent
from plexadm.plex import (
    LOCKED_COLLECTION,
    add_items,
    add_writer,
    create_smart_collection,
    remove_items,
    rename_collection,
    set_studio,
)


def _video(**kwargs: object) -> SimpleNamespace:
    defaults: dict[str, object] = {
        "title": "Test Video",
        "ratingKey": 42,
        "studio": None,
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

        with patch("plexadm.plex.log_mutation") as mock_log:
            count = add_items(collection, [locked, unlocked])

        assert count == 1
        collection.addItems.assert_called_once_with([unlocked])
        mock_log.assert_called_once()

    def test_remove_drops_locked_items(self) -> None:
        collection = _collection()
        locked = _video(collections=[LOCKED_COLLECTION])
        unlocked = _video(title="Unlocked", ratingKey=7)

        with patch("plexadm.plex.log_mutation") as mock_log:
            count = remove_items(collection, [locked, unlocked])

        assert count == 1
        collection.removeItems.assert_called_once_with([unlocked])
        mock_log.assert_called_once()

    def test_locked_target_does_not_drop_locked_item(self) -> None:
        collection = _collection(LOCKED_COLLECTION)
        locked = _video(collections=[LOCKED_COLLECTION])

        with patch("plexadm.plex.log_mutation"):
            count = remove_items(collection, [locked])

        assert count == 1
        collection.removeItems.assert_called_once_with([locked])

    def test_dry_run_makes_no_api_calls_or_logs(self) -> None:
        collection = _collection()
        video = _video()

        with patch("plexadm.plex.log_mutation") as mock_log:
            assert add_items(collection, [video], dry_run=True) == 1
            assert remove_items(collection, [video], dry_run=True) == 1

        collection.addItems.assert_not_called()
        collection.removeItems.assert_not_called()
        mock_log.assert_not_called()

    def test_real_add_logs_each_surviving_item(self) -> None:
        collection = _collection()
        first = _video(title="First", ratingKey=1)
        second = _video(title="Second", ratingKey=2)

        with patch("plexadm.plex.log_mutation") as mock_log:
            assert add_items(collection, [first, second]) == 2

        events = [call.args[0] for call in mock_log.call_args_list]
        assert events == [
            MutationEvent(action="add", title="First", rating_key=1, collection=collection.title),
            MutationEvent(action="add", title="Second", rating_key=2, collection=collection.title),
        ]

    def test_real_remove_logs_each_surviving_item(self) -> None:
        collection = _collection()
        video = _video(title="Removed", ratingKey=9)

        with patch("plexadm.plex.log_mutation") as mock_log:
            assert remove_items(collection, [video]) == 1

        mock_log.assert_called_once_with(
            MutationEvent(action="remove", title="Removed", rating_key=9, collection=collection.title)
        )


class TestSetStudioAddWriterRenameCreate:
    def test_set_studio_skips_locked_video(self) -> None:
        video = _video(collections=[LOCKED_COLLECTION])

        with patch("plexadm.plex.log_mutation") as mock_log:
            assert set_studio(video, "New Studio") is False

        video.edit.assert_not_called()
        mock_log.assert_not_called()

    def test_set_studio_dry_run_is_noop(self) -> None:
        video = _video(studio="Old Studio")

        with patch("plexadm.plex.log_mutation") as mock_log:
            assert set_studio(video, "New Studio", dry_run=True) is True

        video.edit.assert_not_called()
        mock_log.assert_not_called()

    def test_set_studio_edits_and_logs(self) -> None:
        video = _video(studio="Old Studio")

        with patch("plexadm.plex.log_mutation") as mock_log:
            assert set_studio(video, "New Studio") is True

        video.edit.assert_called_once_with(**{"studio.value": "New Studio", "label.locked": 1})
        mock_log.assert_called_once_with(
            MutationEvent(
                action="edit_studio",
                title=video.title,
                rating_key=video.ratingKey,
                details={"old_studio": "Old Studio", "new_studio": "New Studio"},
            )
        )

    def test_add_writer_skips_locked_video(self) -> None:
        video = _video(collections=[LOCKED_COLLECTION])

        with patch("plexadm.plex.log_mutation") as mock_log:
            assert add_writer(video, ["Alice"]) is False

        video.addWriter.assert_not_called()
        mock_log.assert_not_called()

    def test_add_writer_dry_run_is_noop(self) -> None:
        video = _video()

        with patch("plexadm.plex.log_mutation") as mock_log:
            assert add_writer(video, ["Alice"], dry_run=True) is True

        video.addWriter.assert_not_called()
        mock_log.assert_not_called()

    def test_add_writer_edits_and_logs(self) -> None:
        video = _video()

        with patch("plexadm.plex.log_mutation") as mock_log:
            assert add_writer(video, ["Alice", "Bob"]) is True

        video.addWriter.assert_called_once_with(["Alice", "Bob"], True)
        mock_log.assert_called_once_with(
            MutationEvent(
                action="add_writer",
                title=video.title,
                rating_key=video.ratingKey,
                details={"writers": ["Alice", "Bob"]},
            )
        )

    def test_rename_collection_dry_run_is_noop(self) -> None:
        collection = _collection("Old Title")

        with patch("plexadm.plex.log_mutation") as mock_log:
            rename_collection(collection, "New Title", dry_run=True)

        collection.editTitle.assert_not_called()
        mock_log.assert_not_called()

    def test_rename_collection_edits_and_logs(self) -> None:
        collection = _collection("Old Title")

        with patch("plexadm.plex.log_mutation") as mock_log:
            rename_collection(collection, "New Title")

        collection.editTitle.assert_called_once_with("New Title")
        mock_log.assert_called_once_with(
            MutationEvent(action="rename_collection", title="New Title", details={"old_title": "Old Title"})
        )

    def test_create_smart_collection_dry_run_is_noop(self) -> None:
        section = SimpleNamespace(createCollection=MagicMock())

        with patch("plexadm.plex.log_mutation") as mock_log:
            create_smart_collection(
                section,
                title="Smart",
                sort="titleSort:asc",
                filters={"writer": "Alice"},
                dry_run=True,
            )

        section.createCollection.assert_not_called()
        mock_log.assert_not_called()

    def test_create_smart_collection_creates_and_logs(self) -> None:
        section = SimpleNamespace(createCollection=MagicMock())
        filters = {"writer": "Alice"}

        with patch("plexadm.plex.log_mutation") as mock_log:
            create_smart_collection(section, title="Smart", sort="titleSort:asc", filters=filters)

        section.createCollection.assert_called_once_with(
            title="Smart", smart=True, sort="titleSort:asc", filters=filters
        )
        mock_log.assert_called_once_with(
            MutationEvent(action="create_collection", title="Smart", details={"filters": filters})
        )
