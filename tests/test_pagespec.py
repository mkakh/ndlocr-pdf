"""Unit tests for pagespec.parse_pages (§5.2, acceptance #5)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pagespec import PageSpecError, parse_pages  # noqa: E402


# --- "all pages" sentinel -------------------------------------------------

@pytest.mark.parametrize("spec", ["", "   ", "\t", "\n  \n"])
def test_blank_returns_none(spec):
    assert parse_pages(spec, total=10) is None


def test_none_spec_returns_none():
    assert parse_pages(None, total=10) is None


# --- normal cases ---------------------------------------------------------

def test_single_page():
    assert parse_pages("1", total=10) == [1]


def test_comma_list():
    assert parse_pages("1,3,5", total=10) == [1, 3, 5]


def test_range_inclusive():
    assert parse_pages("5-8", total=10) == [5, 6, 7, 8]


def test_combined_spec():
    assert parse_pages("1,3,5-8", total=10) == [1, 3, 5, 6, 7, 8]


def test_whitespace_ignored():
    assert parse_pages(" 1 , 3 , 5 - 8 ", total=10) == [1, 3, 5, 6, 7, 8]


def test_dedup_and_sort():
    assert parse_pages("8,1,3,3,5-7,6", total=10) == [1, 3, 5, 6, 7, 8]


def test_single_page_range():
    assert parse_pages("4-4", total=10) == [4]


def test_boundary_equal_total():
    assert parse_pages("10", total=10) == [10]


# --- error cases ----------------------------------------------------------

def test_reversed_range():
    with pytest.raises(PageSpecError):
        parse_pages("5-2", total=10)


def test_zero_page():
    with pytest.raises(PageSpecError):
        parse_pages("0", total=10)


def test_out_of_range():
    with pytest.raises(PageSpecError):
        parse_pages("999", total=10)


def test_out_of_range_in_range_expr():
    with pytest.raises(PageSpecError):
        parse_pages("5-999", total=10)


def test_non_numeric():
    with pytest.raises(PageSpecError):
        parse_pages("a", total=10)


def test_non_numeric_in_range():
    with pytest.raises(PageSpecError):
        parse_pages("1-b", total=10)


def test_trailing_comma():
    with pytest.raises(PageSpecError):
        parse_pages("1,", total=10)


def test_leading_comma():
    with pytest.raises(PageSpecError):
        parse_pages(",2", total=10)


def test_double_comma():
    with pytest.raises(PageSpecError):
        parse_pages("1,,2", total=10)


def test_malformed_range_too_many_dashes():
    with pytest.raises(PageSpecError):
        parse_pages("1-2-3", total=10)


def test_open_range():
    with pytest.raises(PageSpecError):
        parse_pages("5-", total=10)


def test_negative_via_open_range():
    with pytest.raises(PageSpecError):
        parse_pages("-5", total=10)


def test_zero_total_raises():
    with pytest.raises(PageSpecError):
        parse_pages("1", total=0)
