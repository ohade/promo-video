# promo-video

Turn a project folder (script lines, an edit list, footage) into a finished trailer-style promotional video:
generated narration (Gemini TTS) and music (Lyria), procedural sound effects, ducking and loudness mastering, kinetic
graphics, contact sheets, an edit-list checker and a privacy scan. A Claude Code skill (`skills/promo-video/`) drives
the whole flow: `/promo-video "<topic>" [bay|nolan]`.

## Install

One script takes a fresh macOS or Debian/Ubuntu computer to a working setup:

```bash
git clone <this repo> promo-video && cd promo-video
scripts/install.sh --dry-run     # print the plan and every action, change nothing
scripts/install.sh               # do it (asks once before installing system packages; --yes skips the question)
```

It installs only what is missing, so it is safe to run again: a second run installs nothing. Requirements and where
each one comes from:

| Requirement | Minimum version | How `scripts/install.sh` gets it |
|---|---|---|
| Python | 3.11 (`requires-python` in `pyproject.toml`, the one place it is set; the script reads it) | the first of `python3.13`, `python3.12`, `python3.11`, `python3` on PATH that is new enough, never the macOS system Python 3.9; else `brew install python@3.12` on macOS, or `apt-get install python3 python3-venv` when the distribution's `python3` is new enough (otherwise it stops and names the version it needs) |
| numpy | 1.24 | `pip install -e .` into `<repo>/.venv` |
| Pillow | 10.1 | `pip install -e .` into `<repo>/.venv` |
| filelock | 4.2.4 | `pip install -e .` into `<repo>/.venv` |
| setuptools (build only) | 68 | fetched by pip while installing |
| ffmpeg and ffprobe | none pinned (developed with ffmpeg 9.0) | `brew install ffmpeg` / `apt-get install ffmpeg` |
| tesseract (optional) | none pinned (developed with 5.5) | only with `--with-ocr`: `brew install tesseract` / `apt-get install tesseract-ocr`; without it the OCR privacy scan prints a SKIP line |
| Homebrew (macOS only) | a current release | when it is needed and missing, the script prints the official install command and exits 2; `--install-homebrew` runs that installer |
| bash | 3.2 (the macOS `/bin/bash`) | already there |
| Whisper server (optional) | none | not installed; see Config |

Then it creates `<repo>/.venv` and installs the package there, links the skill for Claude Code
(`~/.claude/skills/promo-video` -> `<repo>/skills/promo-video`), copies `config.example.toml` to
`~/.config/promo-video/config.toml` (or `$PROMO_VIDEO_CONFIG`) with mode 600 when no config exists yet, and ends with
a summary, `bin/promo-video config check` (a missing key is reported, not fatal) and `bin/promo-video check --self-test`.
It never writes, reads back or prints a key, and never changes an existing config.

| Flag | Effect |
|---|---|
| `--dry-run` | print every action, change nothing |
| `--yes` | no questions |
| `--with-ocr` | also install tesseract |
| `--install-homebrew` | on macOS, run the official Homebrew installer when brew is missing |
| `--force-link` | replace a `~/.claude/skills/promo-video` link that points elsewhere (a link only, never a real folder) |
| `--no-skill` | do not link the skill |
| `--help` | usage |

Exit codes: 0 done, 1 error or stopped, 2 a package manager step comes first (Homebrew missing on macOS, or apt
offering no `python3` package, which usually means empty package lists: the script prints `sudo apt-get update` to run
before trying again), 3 the skill path is already taken by a different link or a real folder (left unchanged). On
Debian/Ubuntu `apt-get` runs through `sudo` when you are not root, and the script says so before it does.

By hand, on any other system: install Python 3.11+, ffmpeg and ffprobe, then

```bash
python3 -m venv .venv && .venv/bin/pip install -e .
ln -s "$PWD/skills/promo-video" ~/.claude/skills/promo-video
```

To run the tests, add the test extra: `.venv/bin/pip install -e '.[test]'`.

`bin/promo-video` finds its repo from its own real path and picks a Python with numpy, Pillow and filelock:
`$PROMO_VIDEO_PYTHON`, then `.venv/bin/python`, then `python3`, then `uv run --with numpy --with pillow --with 'filelock>=4.2.4'`. The skill
resolves its symlink the same way to find this repo.

## Config

Narration and music need a Google AI Studio API key. It is read only from:

1. the environment variable `GEMINI_API_KEY` (always wins), else
2. `gemini_api_key` in the config files, in this order: `$PROMO_VIDEO_CONFIG` (when set, the only file read),
   `~/.config/promo-video/config.toml`, `<repo>/config.local.toml`.

The first source with a real value wins: an empty value and the placeholder `YOUR-GOOGLE-AI-STUDIO-KEY` from
`config.example.toml` count as no key, so a key in `config.local.toml` is still found after the installer copies the
example to `~/.config/promo-video/config.toml`. The other settings come from the first config file that exists.
Copy `config.example.toml` to one of those places and `chmod 600` it. `config.local.toml` is gitignored. The key is
never printed, logged, written to an output file or put in an error message. Check your setup with:

```bash
bin/promo-video config check
```

`whisper_url` (optional) points to an OpenAI-compatible transcription endpoint. When set, every narration line is
transcribed and regenerated (up to 3 tries) until it matches the script (word ratio >= 0.90), and `check` matches the
final mix (>= 0.85). Without it, those checks print one SKIP line each and do not fail.

Matching normalizes spoken numbers up to 999 and spelled letter runs before comparison. A comma can join
one-letter list items such as `S, M, L`, but cannot join the end of one acronym to the start of another.
Punctuation keeps number boundaries, except supported word-internal number hyphens and marked acronym spellings.
Changed numbers, letters and omitted words still reduce the score. Ambiguous leading/trailing `A` or `I` in an
unmarked letter run stays an ordinary word: forms such as `I B M` versus `IBM` can still fail to match.

An export measures every limiter retry before publishing its result. Simultaneous exports to the same destination
are rejected before changing that output. Each attempt owns a fresh temporary media file; the native inter-process
lock uses an opaque filename under the shared Mac/Linux `/tmp`, independent of `TMPDIR` and outside the output folder.
Names that differ only by case or
Unicode composition share a reservation, including on case-sensitive filesystems.

## Usage

```bash
bin/promo-video new "Fast search" --style bay            # ./promo-video-out/fast-search (or $PROMO_VIDEO_OUT/...)
bin/promo-video plan <project>                            # number of paid requests voice + music would make
bin/promo-video render <project> --placeholder-audio      # draft: silent narration timed from the script, no API
bin/promo-video voice <project>                           # paid: Gemini TTS, one request per script line
bin/promo-video music <project>                           # paid: Lyria, one request per preset cue
bin/promo-video render <project> --out <project>/out/promo.mp4
bin/promo-video check <project>/out/promo.mp4             # edit-list rules; exit 1 on any FAIL
bin/promo-video check --self-test                         # proves each rule catches a broken edit list
bin/promo-video privacy <project>/out/promo.mp4 --step 2  # OCR frames for personal text
bin/promo-video sheet <project>/out/promo.mp4 --step 2    # contact sheet PNG
bin/promo-video record <project>/footage/take1.mp4 --seconds 60   # screen capture (UI topics only)
```

Try it without any key: `bin/promo-video render examples/hello --placeholder-audio --out /tmp/hello.mp4`.

## Presets

| preset | feel | voice | music cues | longest shot |
|---|---|---|---|---|
| `bay` | fast, loud blockbuster: hard cuts, whip pans, slam text, impacts, teal-orange graphics | Gemini TTS `Fenrir`, energetic and brisk | `open`, `drive`, `tension`, `outro` | 4 s |
| `nolan` | slow, cerebral, building: letterbox, slow push-ins, intertitles, rising ticking pulse | Gemini TTS `Algenib`, low, calm, deliberate | `pulse`, `rise`, `organ` | 10 s |

Both use TTS model `gemini-3.8-flash-tts` and music model `lyria-3.5`; every music prompt ends with
"Instrumental only, no vocals, no spoken words." Presets are TOML files in `promovideo/presets/`.

## Costs

Only `voice` and `music` make paid requests; nothing else calls an API. `plan` prints the count first:
voice = one request per script line (up to 3 per line with a Whisper URL set), music = one request per cue
(4 for bay, 3 for nolan). Re-running single items: `voice <project> --only l03`, `music <project> --cue drive`.

## Project folder

```
<project>/
  project.toml      title, preset
  script.txt        one narration line per row: <id> "<text>"
  edl.json          the edit list (below)
  footage/          screen recordings and clips used by capture segments
  material/         facts with sources, screenshots
  audio/vo/*.wav    generated narration (+ audio/vo.json)
  audio/music/*     generated cues (+ audio/music.json)
```

## Edit list

`edl.json` holds `segments` (played in order) and `audio`. Times are seconds.

- `kind: "graphic"` with `scene`: `title` (`text`, `sub`), `card` (`lines`, `beat`), `meter` (`label`, `from`, `to`),
  `intertitle` (`text`, `sub`, `fade`), `image` (`file`, `push`), `tilt` (`file`, `yaw_from`, `yaw_to`, `pitch`,
  `height`: a still as a 3D-tilted card), via `params`.
- `kind: "black"`.
- `kind: "capture"`: `source` (under the project), `raw_in`, `mode` (`HUMAN` speed <= 1, `WAIT` 8-60, `HOLD`, `CUT`,
  `RESET`), `speed`, optional `ramp_from`/`ramp_in`, `ramp_to`/`ramp_out`, `crop` `[x, y, w, h]` (16:9) or `crop_keys`
  `[[t, [x, y, w, h]], ...]` for eased moves, `blur` regions blurred before the crop, `clock: true` for the analog
  elapsed-time clock (with `clock_zero`), `label`, `arrows`.
- Every segment: `id`, `block`, `dur`, optional `overlays`: `label`, `slam`, `arrow`, `flare` (events), and `whip_in`,
  `whip_out`, `shake`, `glitch`, `flash` (post effects).
- `audio.vo`: `[{"id", "start"}]` for every script line in order; `audio.music`: `[{"cue", "start", "dur", "src_in",
  "fade_in", "fade_out", "gain_db"}]`; `audio.sfx`: `[{"name", "start", "gain_db", "params"}]` with names `sub_hit`,
  `impact`, `whoosh`, `riser`, `braam`, `glitch`, `pop`, `tick`, `flash_hit`, `low_note`; optional `silence`
  `[[from, to]]`. Music and SFX duck 12 dB and 10 dB under the voice.
- Optional `forbidden`: `[[source, from, to]]` windows of footage that must never appear.

Rendering writes `<out>.edl.json`, `<out>.frames.tsv` (per-frame log the checker reads) and `<out>.srt` next to the
video. Master: H.264 1920x1080 30 fps, AAC 48 kHz stereo, -16 LUFS integrated, true peak no higher than -1.3 dBTP.

## Public-safety check

This repo is meant to be public. Before every push:

```bash
bash scripts/check-public.sh
```

It runs `tests/test_public.py` over every entry git would publish (`git ls-files --cached --others
--exclude-standard`) and then `gitleaks` over the same regular files. For each entry it scans the path itself, a
symlink's own target text (never followed; an absolute target is a finding too) and the file's bytes: UTF-8 text, or
latin-1 when the bytes are not UTF-8, plus a UTF-16 pass, and the inflated contents of four compressed kinds: gzip
data, compressed PNG text chunks (zTXt and iTXt), the members of a zip file (one that starts with `PK`, so also
`.docx` and similar) and the `/FlateDecode` streams of a PDF, opened up to three containers deep. A file it cannot
read, or one of those streams it cannot fully inflate (truncated, damaged, encrypted, an unsupported zip method, over
64 MiB inflated, or still compressed at the three-level depth cap), is a finding, not a skip. Any other encoding or
compression (xz, bzip2, 7z, other PDF filters, images and media) is scanned only as its raw bytes. The patterns:

- this machine's home path and user name, computed when the test runs;
- the names of the skills installed for Claude Code and Codex in your home folder (except `promo-video`), as whole
  words; a few common words (`COMMON_WORDS` in `promovideo/privacy.py`) are exempt;
- each line of the untracked `.public-denylist.local`: a case-insensitive literal, or a regular expression after a
  `re:` prefix, used as written (add `(?i)` for case-insensitive);
- absolute user-home paths on macOS and Linux, macOS private, temporary and volume paths, and home-relative paths
  (starting with a tilde, `$HOME` or `${HOME}`) other than this skill's install folder and its config folder;
- Google, GitHub, Slack, OpenAI, Anthropic and AWS key shapes, private-key headers, and `*_key`, `*token`, `*secret`,
  `*password`, `*passwd` or `*pwd` assignments whose value looks real (a placeholder such as `YOUR-KEY`, `<...>` or
  `${...}` passes);
- e-mail addresses outside the `example.com`, `example.org` and `example.net` placeholder domains.

A finding prints the entry, the line and the pattern name, never the matched text; an entry whose path itself
matches is shown by its position in the `git ls-files` list. Put your own names, employer, hosts and product words
in `.public-denylist.local` (gitignored), one per line. Tests build every positive probe at runtime, so the test files
pass their own scan.

Generated project outputs (`out/`, `audio/`, `material/`, `footage/`, subtitles, contact sheets, media) are
gitignored wherever a project folder sits, including `examples/`.

## Tests

```bash
.venv/bin/python -m pytest -q tests
```

No test calls an API: every HTTP request goes through one injectable transport and the tests use a fake.
