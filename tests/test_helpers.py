from types import SimpleNamespace

from plexadm.cli import _matches_ppv_filename
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
