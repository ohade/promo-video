---
name: promo-video
description: Make a persuasive, trailer-style promotional video for a feature or tool, with generated narration, music, sound effects, an edit-list checker and a privacy scan. Use for /promo-video "<topic>" [bay|nolan], "make a promo video", "a trailer for this feature". Not for calm teaching or how-to videos; those belong to a separate explainer skill.
---

# promo-video

Usage: `/promo-video "<topic>" [bay|nolan]`

- **bay**: fast, loud blockbuster. Hard cuts every 1.5-4 s, whip pans, slam text, impacts, risers.
- **nolan**: slow, cerebral, building. Letterbox, slow push-ins, intertitles, a ticking pulse that keeps rising.

## 0. Find the toolkit (never a hard-coded path)

This skill lives in the promo-video repo at `skills/promo-video/` and is usually installed as a symlink. Take the
base directory this skill was loaded from, resolve it with realpath, and go up two levels:

```bash
PV_REPO="$(python3 -c 'import os, sys; print(os.path.realpath(os.path.join(sys.argv[1], "..", "..")))' "<this skill's base directory>")"
PV="$PV_REPO/bin/promo-video"
```

## 1. Style

If the user gave no style, ask with AskUserQuestion (one question, two options):
Bay ("fast, loud blockbuster") or Nolan ("slow, cerebral, building"). Do not guess.

## 2. Settings and project folder

1. Run `"$PV" config check`. If the key line is FAIL, stop and tell the user to set `GEMINI_API_KEY` or copy
   `config.example.toml` to `~/.config/promo-video/config.toml`. Never ask for the key in chat, never print it.
   A SKIP whisper line is fine: transcription checks are then skipped.
2. Create the project: `"$PV" new "<topic>" --style <bay|nolan>`. It prints the folder: `$PROMO_VIDEO_OUT/<slug>`
   when `PROMO_VIDEO_OUT` is set, else `./promo-video-out/<slug>`.

## 3. Material (ONE subagent)

Send ONE subagent to collect material into `<project>/material/` and `<project>/footage/`, and nothing else:
- `material/facts.md`: the claims the video may make, each with its source (file, URL, or command output);
- screenshots as PNG in `material/`;
- a screen recording only when the topic is a UI: `"$PV" record <project>/footage/take1.mp4 --seconds <n>`.
The subagent makes no paid calls and writes nothing outside the project. Facts not in `facts.md` stay out of the video.

## 4. Script and edit list (you, the lead)

Write `<project>/script.txt` (one `<id> "<text>"` per line, conversational, contractions) and `<project>/edl.json`
from the preset's pacing (`"$PV_REPO/promovideo/presets/<style>.toml"`, `look.pacing` and `max_shot_s`). Open on the
problem, name the product, give a three-item agenda, show, close on the name. The edit-list reference is in the
repo README ("Edit list"). Draft first with no paid requests:

```bash
"$PV" render <project> --placeholder-audio --out <project>/out/draft.mp4
"$PV" check <project>/out/draft.mp4
"$PV" sheet <project>/out/draft.mp4 --step 2
```

Look at the contact sheet yourself before going on.

## 5. Voice and music (paid requests)

Run `"$PV" plan <project>` and state the number of paid requests to the user before generating. Then:

```bash
"$PV" voice <project>      # one Gemini TTS request per line (up to 3 per line when a Whisper URL is set)
"$PV" music <project>      # one Lyria request per preset cue
```

Re-time the narration starts in `edl.json` to the real durations in `<project>/audio/vo.json`.

## 6. Render, check, privacy, deliver

```bash
"$PV" render <project> --out <project>/out/promo.mp4
"$PV" check <project>/out/promo.mp4
"$PV" privacy <project>/out/promo.mp4 --step 2
```

Fix every FAIL by changing the edit list or the script, never by weakening a rule. Deliver: the video path, the check
lines (PASS/SKIP), the privacy line, and the number of paid requests made.
