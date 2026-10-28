"""The Claude Code skill: name, usage, flow, and no hard-coded location."""
import re


def _skill(repo_root):
    return (repo_root / "skills" / "promo-video" / "SKILL.md").read_text()


def test_skill_frontmatter(repo_root):
    text = _skill(repo_root)
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert m, "frontmatter missing"
    front = m.group(1)
    assert re.search(r"^name: promo-video$", front, re.M)
    desc = re.search(r"^description: (.+)$", front, re.M).group(1).lower()
    assert "promo" in desc and "trailer" in desc and "explainer" in desc


def test_skill_flow(repo_root):
    text = _skill(repo_root)
    for needle in ('/promo-video "<topic>" [bay|nolan]', "AskUserQuestion", "PROMO_VIDEO_OUT", "promo-video-out/",
                   "config check", "paid requests", "check", "privacy", "render", "ONE subagent"):
        assert needle in text, needle


def test_skill_finds_repo_from_its_real_path(repo_root):
    text = _skill(repo_root)
    assert "realpath" in text
    slash = "/"
    for absent in (slash + "Users" + slash, slash + "home" + slash, "~" + slash + "git"):
        assert absent not in text, absent
