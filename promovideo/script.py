"""Script lines: one `<id> "<text>"` per row in script.txt; blank lines and # comments are ignored."""
import difflib
import re
from pathlib import Path

LINE = re.compile(r'^\s*([A-Za-z][\w-]*)\s+"(.*)"\s*$')


def parse_script(text):
    out, seen = [], set()
    for n, raw in enumerate(text.splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        m = LINE.match(raw)
        if not m:
            raise ValueError(f"script line {n}: expected <id> \"<text>\", got {raw.strip()[:60]!r}")
        if m.group(1) in seen:
            raise ValueError(f"script line {n}: duplicate id {m.group(1)}")
        seen.add(m.group(1))
        out.append((m.group(1), m.group(2)))
    return out


def load_script(project_dir):
    return parse_script((Path(project_dir) / "script.txt").read_text())


def words(s):
    return re.sub(r"[^a-z0-9 ]", " ", s.lower().replace("-", " ")).split()


UNITS = "zero one two three four five six seven eight nine".split()
TEENS = "ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
TENS = {w: 10 * i for i, w in enumerate("twenty thirty forty fifty sixty seventy eighty ninety".split(), 2)}
SMALL = {w: i for i, w in enumerate(UNITS + TEENS)}
ORDINAL_SMALL = {w: i for i, w in enumerate(
    "zeroth first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth thirteenth fourteenth "
    "fifteenth sixteenth seventeenth eighteenth nineteenth".split())}
ORDINAL_TENS = {w[:-1] + "ieth": n for w, n in TENS.items()}
NUMBER_WORDS = (frozenset(SMALL) | frozenset(ORDINAL_SMALL) | frozenset(TENS) | frozenset(ORDINAL_TENS)
                | {"hundred", "hundredth", "and", "a"})
NUMBER_HYPHEN = re.compile(r"([A-Za-z0-9]+)-(?=([A-Za-z0-9]+))")


def _unit_ordinal(tok):
    """1-9 for a unit ordinal word ("first" ... "ninth") that completes a tens number, else 0."""
    n = ORDINAL_SMALL.get(tok, 0)
    return n if n < 10 else 0


ORDINAL_SUFFIX = {1: "st", 2: "nd", 3: "rd"}


def _ordinal(n):
    """Digit ordinal as Whisper writes it: 1st, 2nd, 3rd, 11th, 28th, 100th."""
    suffix = "th" if n % 100 in (11, 12, 13) else ORDINAL_SUFFIX.get(n % 10, "th")
    return f"{n}{suffix}"


def _below_hundred(toks, i):
    """(value, ordinal, next index) for a number word 0-99 at toks[i], or None."""
    w = toks[i]
    if w in SMALL:
        return SMALL[w], False, i + 1
    if w in ORDINAL_SMALL:
        return ORDINAL_SMALL[w], True, i + 1
    if w in ORDINAL_TENS:
        return ORDINAL_TENS[w], True, i + 1
    if w not in TENS:
        return None
    nxt = toks[i + 1] if i + 1 < len(toks) else None
    if nxt in UNITS[1:]:
        return TENS[w] + SMALL[nxt], False, i + 2
    if _unit_ordinal(nxt):
        return TENS[w] + _unit_ordinal(nxt), True, i + 2
    return TENS[w], False, i + 1


HUNDRED = ("hundred", "hundredth")
DIGIT_HUNDREDS = {str(100 * n): n for n in range(1, 10)}


def _hundreds_prefix(toks, i):
    """(hundreds, index of the hundred token) for "[unit|a] hundred[th]" or "a 100", else None."""
    if toks[i] in HUNDRED:
        return 1, i
    nxt = toks[i + 1] if i + 1 < len(toks) else None
    if toks[i] == "a" and (nxt == "hundred" or nxt in DIGIT_HUNDREDS):
        return DIGIT_HUNDREDS.get(nxt, 1), i + 1
    if nxt in HUNDRED and toks[i] in UNITS[1:]:
        return SMALL[toks[i]], i + 1
    return None


def _digits(value, ordinal, end):
    return (_ordinal(value) if ordinal else str(value)), end


def _number(toks, i):
    """(digits token, next index) for a spoken number 0-999 at toks[i] ("one hundred and five" -> "105"), or None."""
    prefix = _hundreds_prefix(toks, i)
    if prefix is None:
        rest = _below_hundred(toks, i)
        return None if rest is None else _digits(*rest)
    hundreds, j = prefix
    if toks[j] == "hundredth":
        return _ordinal(100 * hundreds), j + 1
    j += 1
    k = j + 1 if j < len(toks) and toks[j] == "and" else j
    rest = _below_hundred(toks, k) if k < len(toks) else None
    if rest is None or rest[0] == 0:
        return str(100 * hundreds), j
    value, ordinal, end = rest
    return _digits(value + 100 * hundreds, ordinal, end)


# Letters the raw text writes with dots, hyphens or slashes between them ("X.Y.360", "T.V.", "A/B", "X-Y-360"), plus at
# most one number written directly after them; this is how Whisper spells an acronym.
MARKED_LETTERS = re.compile(r"(?<![A-Za-z0-9])([A-Za-z](?:[./-][A-Za-z])+)(?![A-Za-z])(?:[./-]?(\d+)(?![A-Za-z0-9]))?")
TOKEN_BREAK = re.compile(r"[^A-Za-z0-9\s,]")
COMMA = ","
LONE_WORD_LETTERS = ("a", "i")


def _join_marked_letters(text):
    return MARKED_LETTERS.sub(lambda m: f" {re.sub('[^A-Za-z]', '', m.group(1)).lower()}{m.group(2) or ''} ", text)


def _number_hyphen(match):
    """A word-internal number hyphen acts as a space; other hyphens remain punctuation boundaries."""
    left, right = match.group(1, 2)
    if all(token.lower() in NUMBER_WORDS or token.isdigit() for token in (left, right)):
        return left + " "
    return match.group(0)


def _single_letter(tok):
    return len(tok) == 1 and tok.isalpha()


# A digit tens number (20-90, or a hundreds number ending in 20-90 such as 120). Round hundreds also fold below.
DIGIT_TENS = re.compile(r"[1-9]?[2-9]0")


def _digit_tens_ordinal(toks, i):
    """(compound ordinal, next index) for a digit tens token followed by a unit ordinal word ("30 second" -> "32nd",
    as "thirty second" gives), or None."""
    nxt = toks[i + 1] if i + 1 < len(toks) else None
    if (DIGIT_TENS.fullmatch(toks[i]) or toks[i] in DIGIT_HUNDREDS) and _unit_ordinal(nxt):
        return _ordinal(int(toks[i]) + _unit_ordinal(nxt)), i + 2
    return None


def _fold_numbers(toks):
    out, i = [], 0
    while i < len(toks):
        num = _digit_tens_ordinal(toks, i) or _number(toks, i)
        out.append(num[0] if num else toks[i])
        i = num[1] if num else i + 1
    return out


def _clause_tokens(clause):
    """Tokens of a clause with numbers folded inside each comma-separated span and a COMMA token between the spans."""
    toks = []
    for span in clause.split(COMMA):
        tokens = words(span)
        if tokens:
            toks.extend(_fold_numbers(tokens) + [COMMA])
    return toks[:-1]


def _isolated_letter(tokens, index):
    """Whether this letter is a one-letter item rather than the edge of a longer run."""
    return (_single_letter(tokens[index])
            and (index == 0 or not _single_letter(tokens[index - 1]))
            and (index == len(tokens) - 1 or not _single_letter(tokens[index + 1])))


def _between_letters(toks, k):
    return 0 < k < len(toks) - 1 and _isolated_letter(toks, k - 1) and _isolated_letter(toks, k + 1)


def _drop_commas_in_letter_lists(toks):
    """Drop commas only between one-letter items: "S, M" joins, but "C, T V" keeps its boundary."""
    return [tok for k, tok in enumerate(toks) if tok != COMMA or not _between_letters(toks, k)]


def _letter_run(toks, i):
    """Tokens for the run of single letters starting at toks[i], and the index after it. The run joins into one token
    when two or more letters remain after leaving out a leading and a trailing "a" or "i", which stay words; a number
    token directly after the joined letters joins too (one at most)."""
    j = i
    while j < len(toks) and _single_letter(toks[j]):
        j += 1
    first = i + 1 if toks[i] in LONE_WORD_LETTERS else i
    stop = j - 1 if j - 1 >= first and toks[j - 1] in LONE_WORD_LETTERS else j
    if stop - first < 2:
        return toks[i:j], j
    core, tail = "".join(toks[first:stop]), toks[stop:j]
    if not tail and j < len(toks) and toks[j].isdigit():
        core, j = core + toks[j], j + 1
    return toks[i:first] + [core] + tail, j


def _join_letter_runs(toks):
    out, i = [], 0
    while i < len(toks):
        if _single_letter(toks[i]):
            part, i = _letter_run(toks, i)
            out.extend(part)
        else:
            out.append(toks[i])
            i += 1
    return out


def match_words(s):
    """words(s) with spoken numbers as digits ("twenty-eighth" -> "28th", "30 second" -> "32nd") and spelled letter
    runs joined ("X.Y.360" -> "xy360"), so a transcript that only writes them differently matches. Numbers are folded
    only inside a span with no punctuation between the words. One-letter list items join across commas ("S, M" and
    "S M" both give "sm"), but longer letter runs stay separate. Other punctuation ends a run, except supported
    word-internal number hyphens and marked acronyms. Used by match_ratio only."""
    out = []
    text = NUMBER_HYPHEN.sub(_number_hyphen, _join_marked_letters(s))
    for clause in TOKEN_BREAK.split(text):
        toks = _join_letter_runs(_drop_commas_in_letter_lists(_clause_tokens(clause)))
        out.extend(tok for tok in toks if tok != COMMA)
    return out


def match_ratio(expected, heard):
    return difflib.SequenceMatcher(None, match_words(expected), match_words(heard)).ratio()
