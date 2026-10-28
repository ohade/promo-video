"""Invariant 1: no file git would publish holds a key, token, private key, e-mail, personal or machine string.

Patterns are computed at runtime from this machine (home path, user name, installed skill names) plus the untracked
.public-denylist.local. Nothing secret or personal is written in this file; every positive probe is assembled at
runtime, so the file passes its own scan.
"""
import getpass
import gzip
import io
import os
import struct
import subprocess
import zipfile
import zlib

import pytest

from promovideo import privacy

SLASH = "/"
TRK = "tr" + "ack"      # a common word that may also be an installed skill name here


def _names(hits):
    return {h[0] for h in hits}


def _hits(text, pats):
    return _names(privacy.scan_text(text, pats))


def _git_repo(root):
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    return root


def _findings_for(findings, rel):
    return [f for f in findings if f.startswith(rel + ":")]


def _kinds_for(findings, rel):
    return {f.rsplit(" ", 1)[1] for f in _findings_for(findings, rel)}


def _home_probe():
    return f"see {os.path.expanduser('~')}/notes\n"


def _pdf(stream, filters="/FlateDecode"):
    """A minimal one-object PDF whose stream bytes are `stream`, declared with the given /Filter."""
    head = b"%%PDF-1.4\n1 0 obj\n<< /Length %d /Filter %s >>\nstream\n" % (len(stream), filters.encode())
    return head + stream + b"\nendstream\nendobj\ntrailer\n<< /Root 1 0 R >>\n%EOF\n"


def test_public_patterns_include_this_machine(repo_root):
    pats = privacy.public_patterns(repo_root)
    names = {n for n, _ in pats}
    assert {"home-path", "user-name", "google-key", "private-key", "email"} <= names
    home = os.path.expanduser("~")
    user = getpass.getuser()
    assert _hits(f"see {home}/x", pats) >= {"home-path"}
    assert "user-name" in _hits(f"by {user} today", pats)


def test_public_detector_catches_secret_shapes(repo_root):
    pats = privacy.public_patterns(repo_root)
    key = "AIza" + "Ab1_-" * 7
    pem = "-----BEGIN " + "RSA PRIVATE" + " KEY-----"
    mail = "someone" + "@" + "mailhost.io"
    assert "google-key" in _hits(f'k = "{key}"', pats)
    assert "private-key" in _hits(pem, pats)
    assert "email" in _hits(f"write to {mail}", pats)


def test_public_detector_allows_placeholders(repo_root):
    pats = privacy.public_patterns(repo_root)
    ok = ("contact" + "@" + "example.com", "AIza...your-key...", "@dataclass", "~/.config/promo-video/config.toml")
    for text in ok:
        assert privacy.scan_text(text, pats) == [], text


def test_public_email_placeholder_domain_is_anchored(repo_root):
    pats = privacy.public_patterns(repo_root)
    assert "email" in _hits("mail j.doe" + "@" + "example.com" + ".evil.io", pats)
    assert "email" in _hits("mail j.doe" + "@" + "example.org" + "-mail.net", pats)
    assert "email" not in _hits("write to contact" + "@" + "example.com" + ". Thanks", pats)
    assert "email" not in _hits("write to contact" + "@" + "mail.example.net" + ")", pats)


def test_public_scan_reads_every_line(repo_root):
    pats = privacy.public_patterns(repo_root)
    text = "clean line\n" * 60 + "see " + os.path.expanduser("~") + "/notes\n"
    assert ("home-path", 61) in privacy.scan_text(text, pats)


@pytest.mark.parametrize("name, positive, negatives", [
    ("user-home-path", [SLASH + "Users" + SLASH + "someone/x", "cd " + SLASH + "home" + SLASH + "someone",
                        "file://" + SLASH + "Users" + SLASH + "a.b/c"],
     ["the Users page", "https://example.com" + SLASH + "home" + SLASH + "page", "no " + SLASH + "Users" + SLASH]),
    ("mac-private-path", [SLASH + "var" + SLASH + "folders" + SLASH + "ab/T/x", SLASH + "private" + SLASH + "var/db",
                          SLASH + "private" + SLASH + "tmp/x", SLASH + "Volumes" + SLASH + "Disk/x"],
     ["the var folders", "lib" + SLASH + "var" + SLASH + "folders" + SLASH + "x", "a private var"]),
    ("home-tilde-path", ["~" + SLASH + "git/x", "~" + SLASH + ".claude/skills/other", "~" + SLASH + ".config/other",
                         "~" + SLASH + ".claude/skills/promo-video-old"],
     ["~" + SLASH + ".claude/skills/promo-video", "~" + SLASH + ".claude/skills/promo-video/SKILL.md",
      "~" + SLASH + ".config/promo-video/config.toml", "approx ~5 s"]),
    ("github-token", ["t = gh" + "p_" + "A1b2C3d4" * 5, "gh" + "s_" + "Z9" * 18, "github" + "_pat_" + "11AB_" * 8],
     ["prefix gh" + "p_ only", "gh" + "p_" + "short1"]),
    ("slack-token", ["xo" + "xb-" + "1234567890-abcdefABCDEF", "xo" + "xp-" + "12345-67890-abc"],
     ["xo" + "xb-", "xo" + "xz-" + "1234567890-abcdef"]),
    ("openai-key", ["sk" + "-" + "proj-" + "A1b2C3d4" * 4, "OPENAI=sk" + "-" + "Z9y8X7w6" * 4],
     ["task" + "-" + "runner-" + "A1b2C3d4" * 4, "sk" + "-learn", "desk" + "-" + "A1b2C3d4" * 4]),
    ("anthropic-key", ["sk" + "-ant-" + "api03-" + "A1b2C3d4" * 4],
     ["sk" + "-ant-" + "x"]),
    ("aws-key", ["AK" + "IA" + "ABCDEFGH" + "23456789", "id=AS" + "IA" + "QWERTYUI" + "OP123456"],
     ["AK" + "IA" + "short", "XAK" + "IA" + "ABCDEFGH" + "23456789" + "Z"]),
    ("secret-assignment", ['api' + '_key = "' + "Zq8wVt3p" * 2 + '"', "GITHUB" + "_TOKEN=" + "a1B2c3D4e5" * 3,
                           'client' + '_secret: "' + "s3cr3tV4lu3" + '"', '"auth' + 'Token": "' + "abc123def456" + '"'],
     ['gemini' + '_api_key = "YOUR-GOOGLE-AI-STUDIO-KEY"', 'gemini' + '_api_key = "from-file"',
      'api' + '_key = "<your-key-1234>"', 'api' + '_key = "${GEMINI' + '_KEY1}"', "key = cfg.api_key()",
      'FILE' + '_KEY = "gemini_api_key"', 'api' + '_key = "xxxxxxxx1"', 'token = "..."']),
])
def test_public_new_pattern_positive_and_negative(repo_root, name, positive, negatives):
    pats = privacy.public_patterns(repo_root)
    for text in positive:
        assert name in _hits(text, pats), (name, "positive", positive.index(text))
    for text in negatives:
        assert name not in _hits(text, pats), (name, "negative", negatives.index(text))


def test_public_denylist_lines_are_patterns(tmp_path):
    (tmp_path / ".public-denylist.local").write_text("# comment\nzebracorp\n\n")
    pats = privacy.public_patterns(tmp_path)
    assert "denylist" in _names(privacy.scan_text("Made at ZebraCorp HQ", pats))
    assert privacy.scan_text("# comment", [p for p in pats if p[0] == "denylist"]) == []


def test_public_denylist_regex_lines(tmp_path):
    (tmp_path / ".public-denylist.local").write_text("re:(?i)\\bqu[- ]?77\\b\nre:\\bZorb\\b\nplainword\n")
    pats = [p for p in privacy.public_patterns(tmp_path) if p[0] == "denylist"]
    assert len(pats) == 3
    for text in ("the QU-77 line", "qu 77", "qu77 api", "Zorb here", "PLAINWORD"):
        assert privacy.scan_text(text, pats) != [], text
    for text in ("qu-777", "zorb here", "Zorbs", "re:", "a quiet line"):
        assert privacy.scan_text(text, pats) == [], text


def test_public_skill_names_from_installed_skills(tmp_path, repo_root):
    home = tmp_path / "home"
    for d in (".claude/skills/zorbleflux", ".claude/skills/promo-video", ".claude/skills/metal",
              ".claude/skills/" + TRK, ".claude/skills/voice", ".codex/skills/quixo-tool", ".codex/skills/.system"):
        (home / d).mkdir(parents=True)
    (home / ".claude/skills/notes.txt").write_text("not a skill")
    pats = [p for p in privacy.public_patterns(repo_root, home=str(home)) if p[0] == "skill-name"]
    assert len(pats) == 1
    for text in ("run zorbleflux now", "use the Quixo-Tool skill", "metal."):
        assert privacy.scan_text(text, pats) != [], text
    for text in ("promo-video", "zorblefluxes", "prezorbleflux", "quixo-tools", "metallic", "tracked", "untracked",
                 "voice", "(" + TRK + ")", "notes.txt", ".system"):
        assert privacy.scan_text(text, pats) == [], text


def test_public_skill_names_absent_without_skill_dirs(tmp_path, repo_root):
    pats = privacy.public_patterns(repo_root, home=str(tmp_path))
    assert "skill-name" not in {n for n, _ in pats}


def test_public_publish_list_listing(repo_root):
    rel = set(privacy.publish_list(repo_root))
    assert "README.md" in rel and "tests/test_public.py" in rel and "skills/promo-video/SKILL.md" in rel
    assert "config.local.toml" not in rel and ".public-denylist.local" not in rel
    assert not any(r.startswith(".venv/") or "__pycache__" in r for r in rel)


def test_public_scans_files_that_are_not_utf8(tmp_path):
    from PIL import Image, PngImagePlugin
    root = _git_repo(tmp_path / "r")
    home = os.path.expanduser("~")
    probe = f"see {home}/notes\n"
    (root / "latin1.txt").write_bytes(b"caf\xe9\n" + probe.encode())
    (root / "utf16.txt").write_bytes(probe.encode("utf-16"))
    (root / "utf16be.txt").write_bytes(probe.encode("utf-16-be"))
    info = PngImagePlugin.PngInfo()
    info.add_text("Comment", home + "/Desktop/shot.png")
    Image.new("RGB", (4, 4)).save(root / "text.png", pnginfo=info)
    info = PngImagePlugin.PngInfo()
    info.add_text("Comment", "key=" + "AIza" + "Q" * 35 + " ", zip=True)
    Image.new("RGB", (4, 4)).save(root / "ztext.png", pnginfo=info)
    (root / "notes.gz").write_bytes(gzip.compress(probe.encode()))
    (root / "clean.bin").write_bytes(bytes(range(256)) * 4)
    findings = privacy.scan_repo(root)
    for rel in ("latin1.txt", "utf16.txt", "utf16be.txt", "text.png", "ztext.png", "notes.gz"):
        assert _findings_for(findings, rel), rel
    assert _findings_for(findings, "clean.bin") == []
    assert all(home not in f for f in findings)


def test_public_scans_paths_and_symlinks(tmp_path):
    root = _git_repo(tmp_path / "r")
    home = os.path.expanduser("~")
    user = getpass.getuser()
    (root / "README.md").write_text("clean\n")
    (root / "docs").mkdir()
    (root / "docs" / f"{user}-notes.txt").write_text("clean\n")
    os.symlink(home + "/git/x/README.md", root / "file-link")
    os.symlink(home + "/git", root / "dir-link")
    os.symlink(SLASH + "opt" + SLASH + "elsewhere", root / "abs-link")
    os.symlink("README.md", root / "rel-link")
    findings = privacy.scan_repo(root)
    text = "\n".join(findings)
    assert home not in text and user not in text
    assert _findings_for(findings, "file-link") and _findings_for(findings, "dir-link")
    assert any("absolute-symlink" in f for f in _findings_for(findings, "abs-link"))
    assert _findings_for(findings, "rel-link") == [] and _findings_for(findings, "README.md") == []
    assert sum(1 for f in findings if "user-name" in f and ":name " in f) == 1


def test_public_generated_outputs_are_gitignored(repo_root):
    for rel in ("examples/hello/out/promo.srt", "examples/hello/out/promo.sheet.png", "examples/hello/out/x.png",
                "examples/hello/audio/vo.json", "examples/hello/audio/music.json",
                "examples/hello/audio/music/drive.ogg", "examples/hello/audio/vo/l01.wav.try",
                "examples/hello/material/shot.png", "examples/hello/footage/demo.mp4", "other/proj/out/a.png",
                "x/y.srt", "x/y.sheet.png", "x/y.ogg", "x/y.wav.try"):
        r = subprocess.run(["git", "-C", str(repo_root), "check-ignore", "-q", "--no-index", rel])
        assert r.returncode == 0, rel


def test_public_every_tracked_file_is_clean(repo_root):
    assert privacy.scan_repo(repo_root) == []


def test_public_truncated_stream_is_undecodable(tmp_path):
    root = _git_repo(tmp_path / "r")
    blob = gzip.compress((_home_probe() * 200).encode())
    (root / "trunc.gz").write_bytes(blob[:len(blob) // 2])
    findings = privacy.scan_repo(root)
    assert "trunc.gz:0 undecodable" in findings
    assert all(os.path.expanduser("~") not in f for f in findings)


def test_public_unreadable_entry_is_a_finding(tmp_path):
    root = _git_repo(tmp_path / "r")
    (root / "gone.txt").write_text("clean\n")
    subprocess.run(["git", "-C", str(root), "add", "gone.txt"], check=True)
    (root / "gone.txt").unlink()
    assert privacy.scan_repo(root) == ["gone.txt:0 unreadable"]


def test_public_invalid_denylist_regex_fails_without_echoing_it(tmp_path):
    word = "zorb" + "quux"
    (tmp_path / ".public-denylist.local").write_text(f"plainword\nre:({word}\n")
    with pytest.raises(ValueError) as err:
        privacy.public_patterns(tmp_path)
    assert "entry 2" in str(err.value)
    assert word not in str(err.value) and "re:(" not in str(err.value)


def test_public_relative_symlink_target_text_is_scanned(tmp_path):
    root = _git_repo(tmp_path / "r")
    word = "zebra" + "corp"
    (root / ".gitignore").write_text(".public-denylist.local\n")
    (root / ".public-denylist.local").write_text(word + "\n")
    os.symlink(f"docs/{word}-notes.md", root / "rel-link")
    findings = privacy.scan_repo(root)
    assert findings == ["rel-link:link-target denylist"]


def test_public_compressed_itxt_is_inflated(tmp_path):
    from PIL import Image, PngImagePlugin
    root = _git_repo(tmp_path / "r")
    info = PngImagePlugin.PngInfo()
    info.add_itxt("Comment", os.path.expanduser("~") + "/Desktop/shot.png", zip=True)
    Image.new("RGB", (4, 4)).save(root / "itxt.png", pnginfo=info)
    assert os.path.expanduser("~").encode() not in (root / "itxt.png").read_bytes()
    assert "home-path" in _kinds_for(privacy.scan_repo(root), "itxt.png")


def test_public_footage_folder_is_gitignored(repo_root):
    for rel in ("examples/hello/footage/take1.braw", "other/footage/cue-notes.txt"):
        r = subprocess.run(["git", "-C", str(repo_root), "check-ignore", "-q", "--no-index", rel])
        assert r.returncode == 0, rel


def test_public_zip_members_and_pdf_flate_streams_are_scanned(tmp_path):
    root = _git_repo(tmp_path / "r")
    probe = _home_probe().encode()
    for name, text in (("z1.zip", probe * 3), ("clean.zip", b"hello\n")):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("notes.txt", text)
        (root / name).write_bytes(buf.getvalue())
    (root / "z2.pdf").write_bytes(_pdf(zlib.compress(b"BT (" + probe + b") Tj ET")))
    (root / "clean.pdf").write_bytes(_pdf(zlib.compress(b"BT (hello) Tj ET")))
    (root / "photo.pdf").write_bytes(_pdf(bytes(range(256)) * 4, "/DCTDecode"))
    findings = privacy.scan_repo(root)
    assert "home-path" in _kinds_for(findings, "z1.zip")
    assert "home-path" in _kinds_for(findings, "z2.pdf")
    for rel in ("clean.zip", "clean.pdf", "photo.pdf"):
        assert _findings_for(findings, rel) == [], rel
    assert all(os.path.expanduser("~") not in f for f in findings)


def test_public_damaged_zip_or_pdf_stream_is_undecodable(tmp_path):
    root = _git_repo(tmp_path / "r")
    (root / "broken.zip").write_bytes(b"PK\x03\x04" + bytes(range(256)))
    deflated = zlib.compress(_home_probe().encode() * 50)
    (root / "cut.pdf").write_bytes(_pdf(deflated[:len(deflated) // 2]))
    (root / "nostream.pdf").write_bytes(b"%PDF-1.4\n<< /Filter /FlateDecode >>\n%EOF\n")
    whole = _pdf(deflated)
    (root / "eof.pdf").write_bytes(whole[:whole.index(b"stream\n") + len(b"stream\n") + len(deflated) // 2])
    findings = privacy.scan_repo(root)
    for rel in ("broken.zip", "cut.pdf", "nostream.pdf", "eof.pdf"):
        assert "undecodable" in _kinds_for(findings, rel), rel


def test_public_secret_assignment_covers_passwords(repo_root):
    pats = privacy.public_patterns(repo_root)
    for text in ("pass" + 'word = "' + "Hunter2Secret9Zq" + '"', "DB_PASS" + "WD=" + "Zq8wVt3pLm2RkT4wPz8N1",
                 "pw" + 'd: "' + "s3cr3tV4lu3x" + '"'):
        assert "secret-assignment" in _hits(text, pats), text
    for text in ("pass" + 'word = "<your-password-1>"', "pass" + 'word = "changeme123"',
                 "PASS" + "WD=${DB_PASS" + "WD1}", "dir = pwd()", "pass" + "words = load(1)"):
        assert "secret-assignment" not in _hits(text, pats), text


def test_public_home_variable_paths_are_treated_like_tilde(repo_root):
    pats = privacy.public_patterns(repo_root)
    for var in ("$" + "HOME", "${" + "HOME}"):
        for rest in ("/git/projects/demo", "/.claude/skills/other", "/.config/other", "/.config/promo-video-old"):
            assert "home-tilde-path" in _hits(f"cp x {var}{rest}", pats), (var, rest)
        for rest in ("/.claude/skills/promo-video", "/.config/promo-video/config.toml"):
            assert "home-tilde-path" not in _hits(f'X="{var}{rest}"', pats), (var, rest)
    assert "home-tilde-path" not in _hits("$" + "HOMEBREW_PREFIX/bin", pats)


def test_public_common_words_that_are_skill_names_pass(tmp_path, repo_root):
    home = tmp_path / "home"
    for name in (TRK, "review", "verify", "sync", "zorbleflux"):
        (home / ".claude/skills" / name).mkdir(parents=True)
    pats = [p for p in privacy.public_patterns(repo_root, home=str(home)) if p[0] == "skill-name"]
    assert len(pats) == 1 and privacy.scan_text("run zorbleflux", pats) != []
    for text in ("the audio " + TRK + " fades", "review the cut", "verify the render", "sync the audio"):
        assert privacy.scan_text(text, pats) == [], text


def _scan(root):
    """scan_repo's findings; a crash becomes one marker finding, so it fails the test's assertion instead of erroring."""
    try:
        return privacy.scan_repo(root)
    except Exception as e:  # noqa: BLE001
        return [f"scan_repo crashed with {type(e).__name__}"]


def _zip(members, method=zipfile.ZIP_DEFLATED):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", method) as z:
        for name, data in members:
            z.writestr(name, data)
    return buf.getvalue()


def _pdf_streams(streams):
    """A PDF with one object per (filter, stream bytes) pair, in order."""
    out = b"%PDF-1.4\n"
    for n, (filters, stream) in enumerate(streams, 1):
        out += b"%d 0 obj\n<< /Length %d /Filter %s >>\nstream\n" % (n, len(stream), filters.encode())
        out += stream + b"\nendstream\nendobj\n"
    return out + b"trailer\n<< /Root 1 0 R >>\n%EOF\n"


def _zipcrypto(name, data, password):
    """A one-member stored zip encrypted with traditional PKWARE ZipCrypto, written byte by byte."""
    mask = 0xFFFFFFFF
    keys = [0x12345678, 0x23456789, 0x34567890]

    def crc_byte(value, byte):
        return zlib.crc32(bytes([byte]), value ^ mask) ^ mask

    def update(byte):
        keys[0] = crc_byte(keys[0], byte)
        keys[1] = ((keys[1] + (keys[0] & 0xFF)) * 134775813 + 1) & mask
        keys[2] = crc_byte(keys[2], keys[1] >> 24)

    def encrypt(plain):
        out = bytearray()
        for byte in plain:
            t = (keys[2] | 2) & 0xFFFF
            out.append(byte ^ (((t * (t ^ 1)) >> 8) & 0xFF))
            update(byte)
        return bytes(out)

    for byte in password:
        update(byte)
    crc = zlib.crc32(data)
    body = encrypt(bytes(range(11)) + bytes([crc >> 24]) + data)
    fname = name.encode()
    sizes = (crc, len(body), len(data), len(fname))
    local = struct.pack("<I5H3I2H", 0x04034B50, 20, 1, 0, 0, 0x21, *sizes, 0) + fname + body
    central = struct.pack("<I6H3I5H2I", 0x02014B50, 20, 20, 1, 0, 0, 0x21, *sizes, 0, 0, 0, 0, 0, 0) + fname
    end = struct.pack("<I4H2IH", 0x06054B50, 0, 0, 1, 1, len(central), len(local), 0)
    return local + central + end


def _with_method(zip_bytes, method):
    """The same stored zip with its member's compression method field set to `method` in both headers."""
    out = bytearray(zip_bytes)
    struct.pack_into("<H", out, 8, method)
    struct.pack_into("<H", out, out.index(b"PK\x01\x02") + 10, method)
    return bytes(out)


@pytest.mark.parametrize("method", [zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA])
def test_public_corrupt_bzip2_or_lzma_member_is_undecodable_and_the_scan_goes_on(tmp_path, method):
    root = _git_repo(tmp_path / "r")
    good = _zip([("notes.txt", _home_probe().encode() * 40)], method)
    start = good.index(b"notes.txt") + len(b"notes.txt") + 20       # inside the member data, past the local header
    (root / "a-corrupt.zip").write_bytes(good[:start] + bytes(b ^ 0x5A for b in good[start:start + 24])
                                         + good[start + 24:])
    (root / "b-notes.txt").write_text(_home_probe())
    findings = _scan(root)
    assert "a-corrupt.zip:0 undecodable" in findings, findings
    assert "home-path" in _kinds_for(findings, "b-notes.txt"), findings
    assert all(os.path.expanduser("~") not in f for f in findings)


def test_public_zip_nested_past_the_depth_cap_is_a_finding(tmp_path):
    root = _git_repo(tmp_path / "r")

    def nested(levels):
        data = _home_probe().encode()
        for n in range(levels):
            data = _zip([(f"level{n}.zip" if n else "notes.txt", data)])
        return data

    (root / "three.zip").write_bytes(nested(3))
    (root / "four.zip").write_bytes(nested(4))
    findings = _scan(root)
    assert "home-path" in _kinds_for(findings, "three.zip"), findings
    assert "undecodable" in _kinds_for(findings, "four.zip"), findings


def test_public_every_zip_member_and_pdf_stream_is_scanned(tmp_path):
    root = _git_repo(tmp_path / "r")
    probe = _home_probe().encode()
    (root / "two.zip").write_bytes(_zip([("a.txt", b"hello\n"), ("b.txt", probe)]))
    (root / "two.pdf").write_bytes(_pdf_streams([("/FlateDecode", zlib.compress(b"BT (hello) Tj ET")),
                                                 ("/FlateDecode", zlib.compress(b"BT (" + probe + b") Tj ET"))]))
    (root / "mixed.pdf").write_bytes(_pdf_streams([("/FlateDecode", zlib.compress(b"BT (hello) Tj ET")),
                                                   ("/DCTDecode", bytes(range(256)) * 4)]))
    findings = _scan(root)
    assert "home-path" in _kinds_for(findings, "two.zip"), findings
    assert "home-path" in _kinds_for(findings, "two.pdf"), findings
    assert _findings_for(findings, "mixed.pdf") == [], findings


def test_public_encrypted_or_unsupported_zip_member_is_undecodable(tmp_path):
    root = _git_repo(tmp_path / "r")
    probe = _home_probe().encode()
    password = b"pw" + b"42x"
    locked = _zipcrypto("notes.txt", probe, password)
    with zipfile.ZipFile(io.BytesIO(locked)) as archive:
        assert archive.read("notes.txt", pwd=password) == probe        # a real ZipCrypto archive
    (root / "locked.zip").write_bytes(locked)
    (root / "imploded.zip").write_bytes(_with_method(_zip([("notes.txt", probe)], zipfile.ZIP_STORED), 6))
    findings = _scan(root)
    assert "locked.zip:0 undecodable" in findings, findings
    assert "imploded.zip:0 undecodable" in findings, findings


def test_public_zip_member_over_the_size_cap_is_undecodable(tmp_path, monkeypatch):
    root = _git_repo(tmp_path / "r")
    monkeypatch.setattr(privacy, "INFLATE_LIMIT", 1024)
    (root / "big.zip").write_bytes(_zip([("notes.txt", b"hello\n" * 400)], zipfile.ZIP_STORED))
    (root / "small.zip").write_bytes(_zip([("notes.txt", b"hello\n" * 100)], zipfile.ZIP_STORED))
    findings = _scan(root)
    assert findings == ["big.zip:0 undecodable"], findings
