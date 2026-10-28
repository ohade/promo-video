"""Punctuation separates numbers; supported word hyphens and acronym marks still match."""
import pytest

from promovideo import script


@pytest.mark.parametrize("expected, heard", [
    ("Choose twenty / eight seats.", "Choose 28 seats."),
    ("Choose twenty [eight] seats.", "Choose 28 seats."),
    ("Choose twenty + eight seats.", "Choose 28 seats."),
    ("Choose twenty - eight seats.", "Choose 28 seats."),
    ("Buy X Y (360) today.", "Buy XY360 today."),
    ("Buy X Y_360 today.", "Buy XY360 today."),
    ("Buy X Y/360 today.", "Buy XY360 today."),
    ("Buy X Y-360 today.", "Buy XY360 today."),
])
def test_punctuation_cannot_build_a_number_or_attach_acronym_digits(expected, heard):
    assert script.match_ratio(expected, heard) < 1.0


@pytest.mark.parametrize("expected, heard", [
    ("Day one-hundred-and-twenty-first.", "Day 121st."),
    ("Book a 100-second spot.", "Book a hundred-second spot."),
    ("Book a thirty-second spot.", "Book a 30-second spot."),
    ("Buy X/Y/360 today.", "Buy XY360 today."),
    ("Buy X-Y-360 today.", "Buy XY360 today."),
    ("Buy X.Y.360 today.", "Buy XY360 today."),
])
def test_supported_number_hyphens_and_marked_acronyms_stay_equal(expected, heard):
    assert script.match_ratio(expected, heard) == 1.0
