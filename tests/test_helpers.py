from types import SimpleNamespace

from plexadm.cli import _cumshot_absent_exclusion_names, _filters_reference_collection, _matches_ppv_filename
from plexadm.filters import and_filter, writer_any
from plexadm.progress import count_digits, progress_prefix
from plexadm.writers import replace_writer_in_title, writers_from_title


def test_writers_from_title_handles_commas_and_dash_variants() -> None:
    assert writers_from_title("Alice, Bob – Example Title") == ["Alice", "Bob"]


def test_replace_writer_in_title_replaces_exact_case_insensitive_match() -> None:
    assert replace_writer_in_title("Alice, TBD - Example Title", "TBD", "Bob") == "Alice, Bob - Example Title"
    assert replace_writer_in_title("Alice, tbd - Example Title", "TBD", "Bob") == "Alice, Bob - Example Title"


def test_replace_writer_in_title_leaves_rest_of_title_untouched() -> None:
    assert replace_writer_in_title("TBD - PPV Message - 123", "TBD", "Alice") == "Alice - PPV Message - 123"


def test_replace_writer_in_title_only_touches_writer_segment() -> None:
    # "TBD" appearing after the writer/title separator must not be touched.
    assert replace_writer_in_title("Alice, Bob - Notes about TBD", "TBD", "Carol") == "Alice, Bob - Notes about TBD"


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


def test_cumshot_absent_exclusion_names_covers_every_live_cumshot_collection() -> None:
    # Live prefix match, not a static/historical name list - a Cumshot collection never present
    # in the old rename table (e.g. one created directly, not renamed from "01: Category:")
    # must still be picked up.
    section = SimpleNamespace(
        collections=lambda: [
            SimpleNamespace(title="01: Cumshot: Facial"),
            SimpleNamespace(title="01: Cumshot: Creampie"),
            SimpleNamespace(title="01: Composition: MMF"),
        ]
    )
    names = _cumshot_absent_exclusion_names(section)
    assert "01: Cumshot: Facial" in names
    assert "01: Cumshot: Creampie" in names
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
