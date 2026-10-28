"""Formatting changes match without crossing acronym or number boundaries."""
import pytest

from promovideo import script


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("expected, heard", [
    ("Pick option C, T V spots ship today.", "Pick option C, TV spots ship today."),
    ("Choose plan B, X Y ships today.", "Choose plan B, XY ships today."),
    ("Take option B, I'm sure it fits.", "Take option B. I'm sure it fits."),
    ("We can't, I'm afraid.", "We can't. I'm afraid."),
    ("Use plan B, I'd say.", "Use plan B; I'd say."),
    ("Sizes S, M, L ship.", "Sizes S,, M, L ship."),
    ("We welcomed one hundred first-time buyers.", "We welcomed 100 first-time buyers."),
    ("Book a hundred-second spot.", "Book a 100-second spot."),
])
def test_formatting_keeps_letter_items_and_hundreds_equal(expected, heard, reverse):
    if reverse:
        expected, heard = heard, expected
    assert script.match_ratio(expected, heard) == 1.0


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("expected, heard", [
    ("Book a ten-second spot.", "Book a 10-second spot."),
    ("Run a one hundred ten-second test.", "Run a 110-second test."),
    ("We built X Y; three teams use it.", "We built XY; three teams use it."),
    ("Rooms X Y: 2 left.", "Rooms XY: 2 left."),
])
def test_ten_and_sentence_boundaries_keep_their_meaning(expected, heard, reverse):
    if reverse:
        expected, heard = heard, expected
    assert script.match_ratio(expected, heard) == 1.0


@pytest.mark.parametrize("expected, heard", [
    ("Join on the one hundred first day.", "Join on the 100th day."),
    ("We welcomed one hundred first-time buyers.", "We welcomed 10 first-time buyers."),
    ("Book a hundred-second spot.", "Book a 10-second spot."),
    ("Sizes S, M, L ship.", "Sizes S, M, L, X ship."),
    ("Sizes S; M ship.", "Sizes SM ship."),
])
def test_formatting_does_not_hide_changed_numbers_or_letters(expected, heard):
    assert script.match_ratio(expected, heard) < 1.0
