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


@pytest.mark.parametrize("line, heard", [("Book a thirty-second spot today.", "Book a 30-second spot today."),
                                         ("We connect twenty third-party apps for you.",
                                          "We connect 20 third-party apps for you."),
                                         ("Run a sixty-second ad on every new channel.",
                                          "Run a 60-second ad on every new channel."),
                                         ("We welcomed twenty first-time buyers this week.",
                                          "We welcomed 20 first-time buyers this week.")])
def test_script_match_tens_before_an_ordinal_word_equals_digits(line, heard):
    assert script.match_ratio(line, heard) == 1.0


def test_script_match_compound_ordinal_still_checks_its_unit():
    assert script.match_ratio("Day twenty-eighth now.", "Day 28th now.") == 1.0
    assert script.match_ratio("Day twenty-seventh now.", "Day 28th now.") < 1.0


def test_script_match_letter_list_ignores_punctuation_between_letters():
    assert script.match_ratio("Sizes S, M and L ship today.", "Sizes S M and L ship today.") == 1.0


@pytest.mark.parametrize("line, heard", [("Wear a T-shirt today.", "Wear a T shirt today."),
                                         ("Buy XY360 today.", "Buy X.Y360 today.")])
def test_script_match_marked_letter_edges(line, heard):
    assert script.match_ratio(line, heard) == 1.0


@pytest.mark.parametrize("line, heard", [("Book the X Y thirty-second spot.", "Book the X Y 30-second spot."),
                                         ("Book the X Y thirty-second spot.", "Book the XY 30-second spot."),
                                         ("Run a one hundred thirty-second test.", "Run a 130-second test.")])
def test_script_match_digit_tens_and_an_ordinal_word_fold_together(line, heard):
    assert script.match_ratio(line, heard) == 1.0


@pytest.mark.parametrize("line, heard", [("On the twenty-first we ship.", "On the 20 1st we ship."),
                                         ("We ship on the twenty-eighth.", "We ship on the 20. 8th."),
                                         ("The twenty-third floor is open.", "The 20, 3rd floor is open."),
                                         ("Day one hundred twenty-eighth.", "Day 120. 8th."),
                                         ("Day one hundred twenty-first.", "Day 120 1st."),
                                         ("We welcomed twenty-one first-time buyers.", "We welcomed 21st time buyers."),
                                         ("Run a sixty-second ad.", "Run a 60 seconds ad."),
                                         ("The twenty-second of May.", "The 20 2 of May.")])
def test_script_match_split_digit_ordinal_still_differs(line, heard):
    assert script.match_ratio(line, heard) < 1.0


@pytest.mark.parametrize("line, heard", [("We built X Y. Three teams use it.", "We built XY. Three teams use it."),
                                         ("Rooms X Y, 2 left.", "Rooms XY, 2 left."),
                                         ("Rooms X Y, 2 left.", "Rooms X.Y., 2 left."),
                                         ("Pick option C. T V spots ship today.", "Pick option C. TV spots ship today."),
                                         ("Choose plan B. X Y ships today.", "Choose plan B. XY ships today."),
                                         ("Sizes S, M, L. Two left.", "Sizes S, M, L. 2 left.")])
def test_script_match_letter_run_joins_across_commas_only(line, heard):
    assert script.match_ratio(line, heard) == 1.0


@pytest.mark.parametrize("line, heard", [("Sizes S, M, L ship.", "Sizes S, L ship."),
                                         ("Plan X Y, 3 seats.", "Plan X Y, 30 seats."),
                                         ("Sizes S, M and L ship today.", "Sizes M, S and L ship today.")])
def test_script_match_letter_list_across_commas_still_checks_letters(line, heard):
    assert script.match_ratio(line, heard) < 1.0
