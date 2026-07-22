from types import SimpleNamespace

from plexadm.cli import _cumshot_absent_exclusion_names, _filters_reference_collection, _matches_ppv_filename
from plexadm.filters import and_filter, writer_any
from plexadm.progress import count_digits, progress_prefix
from plexadm.writers import writers_from_title


def test_writers_from_title_handles_commas_and_dash_variants() -> None:
    assert writers_from_title("Alice, Bob – Example Title") == ["Alice", "Bob"]


def test_writer_any_ignores_empty_names() -> None:
    assert writer_any(["Alice", "", "Bob"]) == {"or": [{"writer": "Alice"}, {"writer": "Bob"}]}


def test_and_filter_ignores_empty_parts() -> None:
    assert and_filter({"title": "x"}, {}) == {"and": [{"title": "x"}]}


def test_progress_helpers() -> None:
    assert count_digits(100) == 3
    assert progress_prefix(2, 10).endswith("2/10] ")


def test_matches_ppv_filename_matches_the_dash_ppv_dash_pattern() -> None:
    video = SimpleNamespace(locations=["/data/NSFW Scenes/Studio - PPV 2024-01-01 - Title.mp4"])
    assert _matches_ppv_filename(video) is True


def test_matches_ppv_filename_requires_spaces_around_ppv() -> None:
    # "PPV" fused into another word (no surrounding spaces) must not match.
    video = SimpleNamespace(locations=["/data/NSFW Scenes/Studio - NOTPPV 2024-01-01 - Title.mp4"])
    assert _matches_ppv_filename(video) is False


def test_matches_ppv_filename_only_checks_the_basename() -> None:
    # A parent directory coincidentally containing "- PPV " must not cause a false match if the
    # actual filename doesn't.
    video = SimpleNamespace(locations=["/data/NSFW Scenes/Studio - PPV Releases/Title.mp4"])
    assert _matches_ppv_filename(video) is False


def test_matches_ppv_filename_checks_every_location() -> None:
    video = SimpleNamespace(
        locations=[
            "/data/NSFW Scenes/Studio - Title (part 1).mp4",
            "/data/NSFW Scenes/Studio - PPV 2024-01-01 - Title (part 2).mp4",
        ]
    )
    assert _matches_ppv_filename(video) is True


def test_matches_ppv_filename_handles_no_locations() -> None:
    assert _matches_ppv_filename(SimpleNamespace(locations=[])) is False
    assert _matches_ppv_filename(SimpleNamespace()) is False


def test_cumshot_absent_exclusion_names_covers_both_pre_and_post_rename_forms() -> None:
    names = _cumshot_absent_exclusion_names()
    # A real Cumshot collection: both the pre- and post-rename_categories() name must be
    # present, so this works whether or not that migration has run yet.
    assert "01: Category: Facial" in names
    assert "01: Cumshot: Facial" in names
    # Female-only exclusions: the two real, populated ones today, plus the not-yet-existing
    # ones so this starts excluding them automatically once they're created.
    assert "01: Category: Solo" in names
    assert "01: Category: Lesbian" in names
    assert "01: Composition: FF Only" in names
    assert "01: Composition: Female Only" in names
    assert "01: Category: Non-Sexual" in names
    # Collections that DO imply a male performer (and so should still be flagged if missing
    # a cumshot tag) must not be excluded.
    assert "01: Category: MF Only" not in names
    assert "01: Category: MMF" not in names


def test_filters_reference_collection_matches_a_top_level_condition() -> None:
    assert _filters_reference_collection({"collection": "169711"}, "169711") is True


def test_filters_reference_collection_matches_nested_inside_and_or() -> None:
    node = {"and": [{"collection!": "126256"}, {"or": [{"collection": "169711"}, {"writer": "130688"}]}]}
    assert _filters_reference_collection(node, "169711") is True


def test_filters_reference_collection_returns_false_when_absent() -> None:
    node = {"and": [{"collection": "72220"}, {"writer": "130688"}]}
    assert _filters_reference_collection(node, "169711") is False
