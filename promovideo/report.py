"""Text outputs for a resolved edit list: subtitles (.srt) of the narration lines with their times."""


def _ts(t):
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def write_srt(edl, path):
    out = []
    for i, v in enumerate(edl.get("audio", {}).get("vo", []), 1):
        out += [str(i), f"{_ts(v['start'])} --> {_ts(v['start'] + v['dur'])}", edl["script"][v["id"]], ""]
    with open(path, "w") as f:
        f.write("\n".join(out))
