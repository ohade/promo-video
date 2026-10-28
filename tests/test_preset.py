"""Invariant 4: the presets reproduce the v2 voice and music settings exactly."""
from promovideo.presets import PRESETS, load_preset

NO = " Instrumental only, no vocals, no spoken words."

BAY_CUES = {
    "open": "Dark cinematic tension opener: a slow sub-bass heartbeat, glitchy pulsing synth stabs and a rising metallic riser "
            "for twelve seconds, then one enormous brass-and-drum impact, then a short heroic hybrid orchestral statement with "
            "pounding drums." + NO,
    "drive": "High-energy hybrid orchestral action groove at 125 BPM: taiko and big drum kit, driving staccato strings, chugging "
             "distorted guitars and brass stabs on the downbeats, constant forward momentum, bright and exciting, no breakdown." + NO,
    "tension": "Suspense build for a countdown: pulsing low strings and an accelerating drum pattern with rising risers, getting "
               "tighter and louder, a sudden cut to silence, then a massive low brass blast and a triumphant full orchestra "
               "with drums." + NO,
    "outro": "Triumphant heroic finale: full brass fanfare over pounding drums and choir-like synth pads, building to a last huge "
             "hit with a long low tail." + NO,
}
NOLAN_CUES = {
    "pulse": "Minimalist cinematic underscore at 60 BPM: a dry mechanical pocket-watch tick on every beat, a low sustained string "
             "drone, sparse soft piano notes, cold and patient, slowly growing in weight." + NO,
    "rise": "Relentless tension build: layered strings and synths that seem to rise in pitch forever, an accelerating ticking "
            "pulse, deep low brass swells, intensity growing continuously for the whole cue without resolving." + NO,
    "organ": "Solemn awe-inspiring resolution: a slow pipe-organ swell over low strings, wide and spacious, then gradually "
             "settling to a quiet sustained chord." + NO,
}


def test_preset_names():
    assert tuple(PRESETS) == ("bay", "nolan")


def test_preset_bay_voice_exact():
    p = load_preset("bay")
    assert p.tts_model == "gemini-3.8-flash-tts"
    assert p.voice == "Fenrir"
    assert p.profile == "Narrator for a high-energy blockbuster-style trailer for a developer tool."
    assert p.notes == ("Style: energetic, grinning, punchy but natural and conversational, a person, not an announcer.\n"
                       "Pace: brisk.")


def test_preset_nolan_voice_exact():
    p = load_preset("nolan")
    assert p.tts_model == "gemini-3.8-flash-tts"
    assert p.voice == "Algenib"
    assert p.profile == "Narrator for a cerebral, slow-burn film trailer about memory and time."
    assert p.notes == ("Style: low, calm, measured, quietly intense; intimate, close to the microphone.\n"
                       "Pace: slow, with deliberate pauses.")


def test_preset_music_cues_exact():
    bay, nolan = load_preset("bay"), load_preset("nolan")
    assert bay.music_model == "lyria-3.5" and nolan.music_model == "lyria-3.5"
    assert list(bay.cues) == ["open", "drive", "tension", "outro"]
    assert list(nolan.cues) == ["pulse", "rise", "organ"]
    for cue, prompt in BAY_CUES.items():
        assert bay.music_prompt(cue) == prompt, cue
    for cue, prompt in NOLAN_CUES.items():
        assert nolan.music_prompt(cue) == prompt, cue


def test_preset_whisper_threshold_and_tries():
    for name in PRESETS:
        p = load_preset(name)
        assert p.whisper_min_match == 0.90
        assert p.whisper_tries == 3


def test_preset_tts_prompt_format():
    p = load_preset("bay")
    assert p.tts_prompt("Hello there.") == (
        "# AUDIO PROFILE: Narrator for a high-energy blockbuster-style trailer for a developer tool.\n"
        "### DIRECTOR'S NOTES\nStyle: energetic, grinning, punchy but natural and conversational, a person, not an "
        "announcer.\nPace: brisk.\n### TRANSCRIPT\nHello there.")


def test_preset_pacing():
    assert load_preset("bay").max_shot_s == 4.0
    assert load_preset("nolan").max_shot_s == 10.0


def test_preset_unknown_name_rejected(raises):
    err = raises(ValueError, lambda: load_preset("western"))
    assert err is not None and "bay" in str(err) and "nolan" in str(err)
