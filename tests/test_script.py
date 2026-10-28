"""Script lines: `<id> "<text>"` per line; word matching used by the Whisper checks."""
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
