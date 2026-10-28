"""Privacy checks.

1. Public safety of the repository: every entry git would publish is scanned (its path, a symlink's own target text,
   and the file's bytes) for this machine's home path and user name, the owner's installed skill names (all computed
   at runtime), the lines of the untracked .public-denylist.local (literal, or a regex after `re:`), generic home,
   macOS private and home-relative paths (tilde, $HOME, ${HOME}), token shapes (Google, GitHub, Slack, OpenAI,
   Anthropic, AWS), PEM private-key headers, secret-like assignments (keys, tokens, secrets, passwords), and e-mail
   addresses outside the example.com/org/net placeholder domains. Bytes that are not UTF-8 are read as latin-1 and as
   UTF-16; gzip data, compressed PNG text, zip members and PDF Flate streams are inflated, and one that cannot be
   fully inflated is a finding. Findings carry the entry, line and pattern name only, never the matched text.
2. OCR scan of a rendered video (local tesseract, optional): frames whose text matches a forbidden pattern.
"""
import getpass
import io
import lzma
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

DENYLIST = ".public-denylist.local"
SELF_SKILL = "promo-video"
SKILL_DIRS = (".claude/skills", ".codex/skills")
# Common words that are also installed skill names on some machines; they are ordinary words in this repo.
COMMON_WORDS = frozenset({"capture", "freeze", "git", "note", "review", "start", "sync", "track", "update", "verify",
                          "voice"})
INFLATE_LIMIT = 64 << 20                     # bytes of inflated data scanned per compressed stream
MAX_DEPTH = 3                                # containers opened inside one another; a deeper one is undecodable
_EDGE = r"[A-Za-z0-9._-]"                    # characters that continue a path or a host name

GOOGLE_KEY = re.compile(r"AIza[0-9A-Za-z_-]{35}")
PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@(?!(?:[A-Za-z0-9-]+\.)*example\.(?:com|org|net)(?!\.?[A-Za-z0-9-]))"
                   r"(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}")
USER_HOME_PATH = re.compile(rf"(?<!{_EDGE})/(?:Users|home)/[A-Za-z0-9._-]+")
MAC_PRIVATE_PATH = re.compile(rf"(?<!{_EDGE})/(?:var/folders|private/(?:var|tmp)|Volumes)/")
HOME_TILDE_PATH = re.compile(r"(?<![A-Za-z0-9_])(?:[~]|\$HOME|\$\{HOME\})/"
                             r"(?!(?:\.claude/skills|\.config)/promo-video(?![A-Za-z0-9_-]))")
GITHUB_TOKEN = re.compile(r"(?<![A-Za-z0-9_])(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})")
SLACK_TOKEN = re.compile(r"(?<![A-Za-z0-9])xox[abprs]-[A-Za-z0-9-]{10,}")
OPENAI_KEY = re.compile(r"(?<![A-Za-z0-9_-])sk-(?!ant-)[A-Za-z0-9_-]{20,}")
ANTHROPIC_KEY = re.compile(r"(?<![A-Za-z0-9_-])sk-ant-[A-Za-z0-9_-]{20,}")
AWS_KEY = re.compile(r"(?<![A-Z0-9])(?:AKIA|ASIA)[0-9A-Z]{16}(?![A-Z0-9])")
_SECRET_NAME = r"[A-Za-z0-9_.-]*(?:[_-]key|apikey|token|secret|password|passwd|pwd)[\"']?\s*[:=]\s*"
_SECRET_VALUE = re.compile(rf"(?i){_SECRET_NAME}(?:([\"'])([^\"'\s]{{8,}})\1|([A-Za-z0-9_+/-]{{20,}})\s*$)")
_PLACEHOLDER = re.compile(r"(?i)your|example|placeholder|changeme|dummy|fake|redacted|xxx|\.\.\.|^<|^\$|\{\{")


class SecretAssignment:
    """A `*_key` / `*token` / `*secret` / `*password` / `*passwd` / `*pwd` assignment whose value looks real: 8+
    characters with a letter and a digit, and no placeholder marker (your, example, xxx, ..., <...>, ${...})."""

    def search(self, line):
        for m in _SECRET_VALUE.finditer(line):
            value = m.group(2) or m.group(3)
            if re.search(r"[A-Za-z]", value) and re.search(r"[0-9]", value) and not _PLACEHOLDER.search(value):
                return m
        return None


def denylist_lines(repo_root):
    path = Path(repo_root) / DENYLIST
    if not path.exists():
        return []
    return [ln.strip() for ln in path.read_text().splitlines() if ln.strip() and not ln.lstrip().startswith("#")]


def denylist_pattern(line, n=0):
    """`re:<regex>` is used as written (add (?i) for case-insensitive); any other line is a case-insensitive literal."""
    if not line.startswith("re:"):
        return re.compile(re.escape(line), re.I)
    try:
        return re.compile(line[3:])
    except re.error as e:                    # re.error names a position, never the pattern text
        raise ValueError(f"{DENYLIST} entry {n}: invalid regular expression after re: ({e.msg})") from e


def machine_patterns(repo_root, home=None, user=None):
    """Home path, user name and denylist lines: the patterns that identify this machine or its owner."""
    home = home or os.path.expanduser("~")
    user = user or getpass.getuser()
    pats = [("home-path", re.compile(re.escape(home)))]
    if len(user) >= 3:                      # very short names would match ordinary words
        pats.append(("user-name", re.compile(r"(?<![A-Za-z0-9])" + re.escape(user) + r"(?![A-Za-z0-9])", re.I)))
    pats += [("denylist", denylist_pattern(line, n)) for n, line in enumerate(denylist_lines(repo_root), 1)]
    return pats


def skill_names(home):
    """Names of the skills installed under <home> for Claude Code and Codex, except this repo's own skill."""
    names = set()
    for rel in SKILL_DIRS:
        root = Path(home) / rel
        if not root.is_dir():
            continue
        for entry in root.iterdir():
            if not entry.name.startswith(".") and entry.name != SELF_SKILL and entry.is_dir():
                names.add(entry.name)
    return sorted(names - COMMON_WORDS, key=lambda n: (-len(n), n))


def skill_pattern(home):
    """One whole-word, case-insensitive pattern for every installed skill name; None when there are none."""
    names = skill_names(home)
    if not names:
        return None
    words = "|".join(re.escape(n) for n in names)
    return re.compile(rf"(?<![A-Za-z0-9_-])(?:{words})(?![A-Za-z0-9_-])", re.I)


def public_patterns(repo_root, home=None, user=None):
    home = home or os.path.expanduser("~")
    pats = machine_patterns(repo_root, home, user)
    skills = skill_pattern(home)
    if skills is not None:
        pats.append(("skill-name", skills))
    return pats + [("user-home-path", USER_HOME_PATH), ("mac-private-path", MAC_PRIVATE_PATH),
                   ("home-tilde-path", HOME_TILDE_PATH), ("google-key", GOOGLE_KEY), ("github-token", GITHUB_TOKEN),
                   ("slack-token", SLACK_TOKEN), ("openai-key", OPENAI_KEY), ("anthropic-key", ANTHROPIC_KEY),
                   ("aws-key", AWS_KEY), ("private-key", PRIVATE_KEY), ("secret-assignment", SecretAssignment()),
                   ("email", EMAIL)]


def scan_text(text, patterns):
    """[(pattern name, line number)] for every line a pattern matches; the matched text is not returned."""
    hits = []
    for n, line in enumerate(text.splitlines(), 1):
        for name, pat in patterns:
            if pat.search(line) and (name, n) not in hits:
                hits.append((name, n))
    return hits


def _inflate(data, wbits):
    """Every member of a zlib or gzip stream. A truncated stream or one over INFLATE_LIMIT raises: never a silent cut."""
    out = b""
    while data:
        room = INFLATE_LIMIT - len(out)
        if room <= 0:
            raise ValueError("compressed data inflates past the scan limit")
        stream = zlib.decompressobj(wbits)
        out += stream.decompress(data, room)
        if stream.unconsumed_tail or not stream.eof:
            raise ValueError("compressed data is truncated or inflates past the scan limit")
        data = stream.unused_data if wbits > zlib.MAX_WBITS else b""
    return out


def _png_texts(data):
    """Inflated payloads of a PNG's compressed text chunks (zTXt, and iTXt with the compression flag set)."""
    pos, out = 8, []
    while pos + 8 <= len(data):
        size, kind = int.from_bytes(data[pos:pos + 4], "big"), data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + size]
        pos += 12 + size
        if kind == b"zTXt":
            out.append(_inflate(body[body.index(b"\0") + 2:], zlib.MAX_WBITS))
        elif kind == b"iTXt":
            _, rest = body.split(b"\0", 1)
            if rest[:1] == b"\1":
                _, _, text = rest[2:].split(b"\0", 2)
                out.append(_inflate(text, zlib.MAX_WBITS))
    return out


def _zip_members(data):
    """Inflated bytes of every zip member, one at a time. A damaged archive or a member over INFLATE_LIMIT raises."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for info in archive.infolist():
            with archive.open(info) as member:
                blob = member.read(INFLATE_LIMIT + 1)
            if len(blob) > INFLATE_LIMIT:
                raise ValueError("zip member inflates past the scan limit")
            yield blob


_PDF_STREAM = re.compile(rb"(?<![A-Za-z])stream\r?\n")


def _pdf_flate_streams(data):
    """Inflated bytes of every PDF stream whose object dictionary names /FlateDecode. A truncated or oversized stream
    raises, and so does a file that names /FlateDecode but has no such stream: never a silent skip."""
    view, found = memoryview(data), 0
    for m in _PDF_STREAM.finditer(data):
        if b"/FlateDecode" not in data[max(0, data.rfind(b"obj", 0, m.start())):m.start()]:
            continue
        found += 1
        yield _inflate(view[m.end():], zlib.MAX_WBITS)     # stops at the stream's end; endstream is left unread
    if not found:
        raise ValueError("PDF names /FlateDecode but has no Flate stream to inflate")


def _decodings(data, depth=0):
    """Every text view of the bytes worth scanning: UTF-8 (else latin-1), UTF-16 in both byte orders, and inflated
    gzip, compressed PNG text, zip members or PDF Flate streams, MAX_DEPTH containers deep. A container at that depth
    that still holds compressed data raises: never a silent pass."""
    try:
        yield data.decode("utf-8")
    except UnicodeDecodeError:
        yield data.decode("latin-1")
    if b"\0" in data:
        yield data.decode("utf-16-le", "ignore")
        yield data[1:].decode("utf-16-le", "ignore")
    inner = []
    if data[:2] == b"\x1f\x8b":
        inner = [_inflate(data, 16 + zlib.MAX_WBITS)]
    elif data[:8] == b"\x89PNG\r\n\x1a\n":
        inner = _png_texts(data)
    elif data[:4] == b"PK\x03\x04":
        inner = _zip_members(data)
    elif b"%PDF-" in data[:1024] and b"/FlateDecode" in data:
        inner = _pdf_flate_streams(data)
    for blob in inner:
        if depth >= MAX_DEPTH:
            raise ValueError("compressed data nested deeper than the scan opens")
        yield from _decodings(blob, depth + 1)


def scan_bytes(data, patterns):
    """scan_text over every decoding of `data`; an unreadable compressed stream is a finding, not a skip."""
    hits = []
    try:
        for text in _decodings(data):
            hits += [h for h in scan_text(text, patterns) if h not in hits]
    except (zlib.error, zipfile.BadZipFile, ValueError, IndexError, EOFError, OSError,
            lzma.LZMAError, RuntimeError, NotImplementedError):
        hits.append(("undecodable", 0))
    return hits


def publish_list(repo_root):
    """Relative paths git would publish: tracked plus untracked-but-not-ignored, in git's order."""
    out = subprocess.run(["git", "-C", str(repo_root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                         capture_output=True, check=True).stdout.decode("utf-8", "surrogateescape")
    return sorted(set(p for p in out.split("\0") if p))


def scan_repo(repo_root, patterns=None):
    """['<entry>:<line> <pattern>'] for every hit in what git would publish: the path (`:name`), a symlink's target
    text (`:link-target`, never followed), or the bytes. An entry whose path itself hits is shown as `entry <n>`, its
    position in publish_list, so no finding repeats the matched text."""
    pats = public_patterns(repo_root) if patterns is None else patterns
    findings = []
    for n, rel in enumerate(publish_list(repo_root), 1):
        path = Path(repo_root) / rel
        name_hits = scan_text(rel, pats)
        label = f"entry {n}" if name_hits else rel
        findings += [f"{label}:name {name}" for name, _ in name_hits]
        try:
            if path.is_symlink():
                target = os.readlink(path)
                hits = scan_text(target, pats) + ([("absolute-symlink", 1)] if os.path.isabs(target) else [])
                findings += [f"{label}:link-target {name}" for name, _ in hits]
                continue
            data = path.read_bytes()
        except OSError:
            findings.append(f"{label}:0 unreadable")
            continue
        findings += [f"{label}:{line} {name}" for name, line in scan_bytes(data, pats)]
    return findings


def _ocr(clip, t, tmp):
    png = os.path.join(tmp, f"f{t:09.3f}.png")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", str(clip), "-frames:v", "1", png],
                   check=True)
    out = subprocess.run(["tesseract", png, "-", "--psm", "11"], capture_output=True, text=True).stdout
    os.unlink(png)
    return t, out


def scan_video(video, step, patterns, which=shutil.which, log=None):
    """OCR one frame every `step` seconds. (ok, lines): HIT lines then one PASS/FAIL line, or one SKIP line."""
    if not which("tesseract"):
        return True, ["SKIP privacy OCR: tesseract not found; install it to scan rendered frames"]
    from .common import probe_duration
    dur = probe_duration(video)
    times = [i * step for i in range(max(1, int(dur / step)))]
    hits = []
    with tempfile.TemporaryDirectory() as tmp, ThreadPoolExecutor(4) as ex:
        for t, text in ex.map(lambda t: _ocr(video, t, tmp), times):
            for line in text.splitlines():
                names = [n for n, p in patterns if p.search(line)]
                if names:
                    hits.append((t, ",".join(names)))
    lines = [f"HIT {t:8.3f}s  pattern {names}" for t, names in hits]
    lines.append(f"{'FAIL' if hits else 'PASS'} privacy OCR: {len(times)} frames every {step:g} s, "
                 f"{len(hits)} matching lines")
    return not hits, lines
