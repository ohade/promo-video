"""Script lines: `<id> "<text>"` per line; word matching used by the Whisper checks."""
import pytest

from promovideo import script


def test_script_parse_lines():
    text = '# comment\n\nl01 "Hello there."\nl02 "It\'s a promo, really."\n'
    assert script.parse_script(text) == [("l01", "Hello there."), ("l02", "It's a promo, really.")]


def test_script_rejects_duplicate_ids(raises):
    err = raises(ValueError, lambda: script.parse_script('a01 "x"\na01 "y"\n'))
    assert err is not None and "a01" in str(err)


def test_script_words_and_match():
    assert script.words("Promo-it, NOW!") == ["promo", "it", "now"]
    assert script.match_ratio("one two three", "One, two three.") == 1.0
    assert script.match_ratio("one two three", "four five six") == 0.0


def _plain_ratio(a, b):
    """The ratio on plain words, with no number or acronym folding: what a real difference costs."""
    import difflib
    return difflib.SequenceMatcher(None, script.words(a), script.words(b)).ratio()


@pytest.mark.parametrize("heard", ["Buy it in X.Y.360 today.", "Buy it in X Y 360 today.", "Buy it in X-Y-360 today."])
def test_script_match_spelled_acronym_equals_joined(heard):
    assert script.match_ratio("Buy it in XY360 today.", heard) == 1.0


def test_script_match_letter_run_without_number_equals_joined():
    assert script.match_ratio("Ask the AB team.", "Ask the A.B. team.") == 1.0


def test_script_match_lone_single_letter_is_a_word():
    assert script.match_ratio("buy a car", "buy car") == _plain_ratio("buy a car", "buy car")
    assert script.match_ratio("buy a 360", "buy a360") == _plain_ratio("buy a 360", "buy a360")


@pytest.mark.parametrize("spoken, written", [("eighteen", "18"), ("twenty-eighth", "28th"), ("twenty eighth", "28th"),
                                             ("one hundred and five", "105"), ("one hundred five", "105"),
                                             ("first", "1st"), ("zero", "0"), ("nine hundred ninety-nine", "999"),
                                             ("second", "2nd"), ("third", "3rd"), ("twelfth", "12th"),
                                             ("seventy", "70"), ("hundredth", "100th"), ("two hundredth", "200th"),
                                             ("forty-two", "42")])
def test_script_match_number_words_equal_digits(spoken, written):
    assert script.match_ratio(f"Day {spoken} now.", f"Day {written} now.") == 1.0


def test_script_match_spoken_date_and_count_equal_digits():
    assert script.match_ratio("On March third, twelve new crates.", "On March 3rd, 12 new crates.") == 1.0


def test_script_match_wrong_number_costs_one_word():
    got = script.match_ratio("On March second, twelve new crates.", "On March 3rd, 12 new crates.")
    assert got == pytest.approx(2 * 5 / 12)
    got = script.match_ratio("March third, twelve new crates", "March 3rd, 13 new crates")
    assert got == pytest.approx(2 * 4 / 10)


def test_script_match_wrong_acronym_costs_one_word():
    assert script.match_ratio("Buy it in XY360 today.", "Buy it in X.Z.360 today.") == pytest.approx(2 * 4 / 10)


def test_script_match_omitted_word_costs_as_before():
    line, heard = "Two roads meet at the river bend.", "Two roads meet at river bend."
    assert script.match_ratio(line, heard) == _plain_ratio(line, heard) < 1.0
    got = script.match_ratio("On March third, twelve new crates.", "On March 3rd, new crates.")
    assert got == pytest.approx(2 * 5 / 11)


def test_script_match_counting_words_stay_separate():
    assert script.match_ratio("one two three", "1 2 3") == 1.0
    assert script.match_ratio("one two three", "123") == 0.0


def test_script_words_keep_spoken_numbers_for_length():
    assert script.words("Twenty-eighth") == ["twenty", "eighth"]
    assert script.words("Buy X.Y.360") == ["buy", "x", "y", "360"]


@pytest.mark.parametrize("line, heard", [("Run a BZ360 deal now.", "Run a B.Z.360 deal now."),
                                         ("Then I A/B test the new page with real people.",
                                          "Then I AB test the new page with real people."),
                                         ("Book a TV slot", "Book a T.V. slot"),
                                         ("the AI a task", "the A.I. a task"),
                                         ("Book a TV slot", "Book a T V slot"),
                                         ("Give XY a try", "Give X Y a try")])
def test_script_match_lone_a_or_i_beside_acronym_stays_a_word(line, heard):
    assert script.match_ratio(line, heard) == 1.0


def test_script_match_a_or_i_with_one_letter_is_not_joined():
    assert script.match_ratio("Pick a B now", "Pick AB now") == _plain_ratio("Pick a B now", "Pick AB now") < 1.0


def test_script_match_letter_run_takes_at_most_one_number():
    assert script.match_ratio("Buy XY360 2026 now", "Buy X Y 360 2026 now") == 1.0
    assert script.match_ratio("Buy XY360 2026 now", "Buy X.Y.360 2026 now") == 1.0


def test_script_match_numbers_do_not_fold_across_punctuation():
    assert script.match_ratio("We waited twenty. First, we go.", "We waited 20. 1st, we go.") == 1.0
    assert script.match_ratio("Sizes twenty, eight and four.", "Sizes 20, 8 and 4.") == 1.0
    assert script.match_ratio("Sizes twenty, eight and four.", "Sizes 28 and 4.") < 1.0


@pytest.mark.parametrize("spoken, written", [("a hundred", "100"), ("a hundred and five", "105")])
def test_script_match_a_hundred_reads_as_digits(spoken, written):
    assert script.match_ratio(f"Save {spoken} hours.", f"Save {written} hours.") == 1.0


@pytest.mark.parametrize("spoken, written", [("one hundred zero", "100 0"), ("twenty zero", "20 0"),
                                             ("twenty tenth", "20 10th"), ("twenty zeroth", "20 0th")])
def test_script_match_number_corners_stay_separate(spoken, written):
    assert script.match_ratio(f"Day {spoken} now.", f"Day {written} now.") == 1.0


@pytest.mark.parametrize("line, heard", [("Ask the YX team.", "Ask the Y X team."), ("Run AB now", "Run A/B now"),
                                         ("Buy XY360 2026 now", "Buy X-Y-360-2026 now")])
def test_script_match_letter_join_keeps_order_and_marks(line, heard):
    assert script.match_ratio(line, heard) == 1.0


def test_script_match_one_letter_and_a_number_stay_apart():
    assert script.match_ratio("Plan B 2", "Plan B2") == _plain_ratio("Plan B 2", "Plan B2") < 1.0
