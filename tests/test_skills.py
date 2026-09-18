"""The shipped skills: `tilewright skills install`, and links that resolve.

The onboarding skill is read on GitHub and by an agent, never built by mkdocs, so nothing
else checks its links. Every relative link in `skills/`, and every GitHub link from
`skills/` or `docs/` into this repository, must name a file that exists and a heading in
it (ADR-0018).
"""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "onboarding"
GH = "https://github.com/slaclab/tilewright/blob/main/"
LINK = re.compile(r"\]\(([^)\s]+)\)")


def _install(home, *flags):
    env = {**os.environ, "HOME": str(home)}
    return subprocess.run([sys.executable, "-m", "tilewright.cli", "skills", "install", *flags],
                          capture_output=True, text=True, env=env)


def test_install_links_the_skill_and_is_idempotent(tmp_path):
    first = _install(tmp_path)
    assert first.returncode == 0, first.stderr
    link = tmp_path / ".claude" / "skills" / "onboarding"
    assert link.is_symlink() and link.resolve() == SKILL.resolve()
    assert (link / "SKILL.md").is_file()
    again = _install(tmp_path)
    assert again.returncode == 0 and "up to date" in again.stdout


def test_install_refuses_a_foreign_symlink_unless_forced(tmp_path):
    link = tmp_path / ".claude" / "skills" / "onboarding"
    link.parent.mkdir(parents=True)
    link.symlink_to(tmp_path)
    refused = _install(tmp_path)
    assert refused.returncode == 1 and "--force" in refused.stderr
    assert link.resolve() == tmp_path.resolve()
    forced = _install(tmp_path, "--force")
    assert forced.returncode == 0 and link.resolve() == SKILL.resolve()


def test_install_never_replaces_a_real_directory(tmp_path):
    mine = tmp_path / ".claude" / "skills" / "onboarding"
    mine.mkdir(parents=True)
    (mine / "SKILL.md").write_text("my own")
    result = _install(tmp_path, "--force")
    assert result.returncode == 1 and "move it away" in result.stderr
    assert (mine / "SKILL.md").read_text() == "my own"


def test_every_reference_page_says_when_to_read_it_and_skill_md_routes_to_it():
    """Pages are read when their decision comes (ADR-0019), so each says when, and the
    routing in SKILL.md names each one; a page it does not name is never read."""
    skill = (SKILL / "SKILL.md").read_text()
    for page in sorted((SKILL / "reference").glob("*.md")):
        text = page.read_text()
        assert "**Read this when**" in text.split("\n## ")[0], f"{page.name} opens without 'Read this when'"
        assert f"reference/{page.name}" in skill, f"SKILL.md never routes to {page.name}"


def _slug(heading):
    """GitHub's anchor for a heading: lowercase, punctuation dropped, spaces to hyphens."""
    text = re.sub(r"[^\w\- ]", "", heading.strip().lower())
    return text.replace(" ", "-")


def _anchors(page):
    return {_slug(m) for m in re.findall(r"^#{1,6} (.+)$", page.read_text(), re.M)}


def _links():
    pages = sorted(SKILL.parent.rglob("*.md")) + sorted((ROOT / "docs").rglob("*.md"))
    for page in pages:
        in_skills = page.is_relative_to(SKILL.parent)
        for target in LINK.findall(page.read_text()):
            if target.startswith(GH):
                yield page, ROOT / target[len(GH):]
            elif in_skills and not re.match(r"[a-z]+:|#", target):
                yield page, page.parent / target


@pytest.mark.parametrize("page,target", list(_links()),
                         ids=lambda v: str(v.relative_to(ROOT)) if isinstance(v, Path) else None)
def test_link_resolves(page, target):
    path, _, anchor = str(target).partition("#")
    path = Path(path)
    assert path.exists(), f"{page.relative_to(ROOT)} links to a missing {path}"
    if anchor and path.suffix == ".md":
        assert anchor in _anchors(path), f"{page.relative_to(ROOT)}: no heading #{anchor} in {path.name}"
