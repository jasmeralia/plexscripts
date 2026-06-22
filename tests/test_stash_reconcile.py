from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from plexadm.stash_reconcile import _collection_to_tag, _has_usable_metadata


def _mock_video(**kwargs: object) -> SimpleNamespace:
    defaults: dict[str, object] = {
        "title": "Test Scene",
        "studio": None,
        "writers": [],
        "directors": [],
        "collections": [],
        "userRating": None,
        "viewCount": None,
        "locations": ["/data/NSFW Scenes/Test/test.mp4"],
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestCollectionToTag:
    def test_strips_01_prefix_from_category(self) -> None:
        assert _collection_to_tag("01: Category: Blowjob") == "Category: Blowjob"

    def test_strips_01_prefix_from_hair(self) -> None:
        assert _collection_to_tag("01: Hair: Red") == "Hair: Red"

    def test_returns_none_for_02_prefix(self) -> None:
        assert _collection_to_tag("02: Studio: Brazzers") is None

    def test_returns_none_for_03_prefix(self) -> None:
        assert _collection_to_tag("03: Star: Alice") is None

    def test_returns_none_for_99_prefix(self) -> None:
        assert _collection_to_tag("99: LOCKED") is None

    def test_returns_none_for_unprefixed(self) -> None:
        assert _collection_to_tag("Some Collection") is None


class TestHasUsableMetadata:
    def test_true_when_studio(self) -> None:
        assert _has_usable_metadata(_mock_video(studio="Brazzers")) is True

    def test_true_when_writers(self) -> None:
        assert _has_usable_metadata(_mock_video(writers=["Alice"])) is True

    def test_true_when_rating(self) -> None:
        assert _has_usable_metadata(_mock_video(userRating=8.5)) is True

    def test_true_when_directors(self) -> None:
        assert _has_usable_metadata(_mock_video(directors=["Bob"])) is True

    def test_true_when_01_collection(self) -> None:
        assert _has_usable_metadata(_mock_video(collections=["01: Category: Solo"])) is True

    def test_false_when_all_empty(self) -> None:
        assert _has_usable_metadata(_mock_video()) is False

    def test_false_when_only_non_01_collections(self) -> None:
        assert _has_usable_metadata(_mock_video(collections=["02: Studio: Brazzers", "99: LOCKED"])) is False

    def test_false_when_rating_is_zero(self) -> None:
        assert _has_usable_metadata(_mock_video(userRating=0.0)) is False


class TestStashClientCaching:
    def test_find_or_create_performer_uses_cache(self) -> None:
        from plexadm.stash import StashClient

        client = StashClient("http://localhost:9999")
        client._performer_cache["Alice"] = "42"
        with patch.object(client, "_gql") as mock_gql:
            result = client.find_or_create_performer("Alice")
            mock_gql.assert_not_called()
        assert result == "42"

    def test_find_or_create_studio_uses_cache(self) -> None:
        from plexadm.stash import StashClient

        client = StashClient("http://localhost:9999")
        client._studio_cache["Brazzers"] = "99"
        with patch.object(client, "_gql") as mock_gql:
            result = client.find_or_create_studio("Brazzers")
            mock_gql.assert_not_called()
        assert result == "99"

    def test_find_or_create_tag_uses_cache(self) -> None:
        from plexadm.stash import StashClient

        client = StashClient("http://localhost:9999")
        client._tag_cache["Category: Solo"] = "7"
        with patch.object(client, "_gql") as mock_gql:
            result = client.find_or_create_tag("Category: Solo")
            mock_gql.assert_not_called()
        assert result == "7"

    def test_find_or_create_performer_populates_cache_on_miss(self) -> None:
        from plexadm.stash import StashClient

        client = StashClient("http://localhost:9999")
        client._gql = MagicMock(  # type: ignore[method-assign]
            return_value={"findPerformers": {"performers": [{"id": "55"}]}}
        )
        result = client.find_or_create_performer("Bob")
        assert result == "55"
        assert client._performer_cache["Bob"] == "55"

    def test_find_or_create_performer_creates_when_missing(self) -> None:
        from plexadm.stash import StashClient

        client = StashClient("http://localhost:9999")
        responses = [
            {"findPerformers": {"performers": []}},
            {"performerCreate": {"id": "88"}},
        ]
        client._gql = MagicMock(side_effect=responses)  # type: ignore[method-assign]
        result = client.find_or_create_performer("New Star")
        assert result == "88"
        assert client._performer_cache["New Star"] == "88"


class TestRatingConversion:
    def test_8_becomes_80(self) -> None:
        assert round(8.0 * 10) == 80

    def test_7_5_becomes_75(self) -> None:
        assert round(7.5 * 10) == 75

    def test_10_becomes_100(self) -> None:
        assert round(10.0 * 10) == 100

    def test_1_becomes_10(self) -> None:
        assert round(1.0 * 10) == 10
