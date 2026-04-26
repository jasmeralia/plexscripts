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
