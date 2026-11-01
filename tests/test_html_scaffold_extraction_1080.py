"""Execute the delivered recipe; a successful awk exit can still leave an empty HTML."""
from html.parser import HTMLParser
from pathlib import Path
import re
import shlex
import subprocess

import pytest


class _ScaffoldParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = set()

    def handle_starttag(self, tag, attrs):
        self.tags.add(tag)


@pytest.mark.parametrize("home", [".claude", ".codex"])
def test_documented_extraction_from_injected_reference(tmp_path, home):
    from app.prompting import inject_skills_to_worktree_report

    # Exercise both native deliveries in a working directory containing spaces.
    repo = tmp_path / "project with spaces"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    inject_skills_to_worktree_report(["html-artifacts"], str(repo), home)
    reference = repo / home / "skills/html-artifacts/references/animation.md"
    text = reference.read_text(encoding="utf-8")

    # Read the executable example and its runtime-specific default from the delivered
    # instructions. Do not hard-code a corrected source that could hide a regression.
    command = re.search(r"`(awk\s.*? > out\.html)`", text, re.DOTALL).group(1)
    command = " ".join(command.splitlines())
    source_placeholder = re.search(r"<[^>]+>", command).group()
    source = re.search(rf"`({re.escape(home)}/[^`]+\.md)`", text).group(1)
    result = subprocess.run(
        command.replace(source_placeholder, shlex.quote(source)),
        shell=True, cwd=repo, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    html_bytes = (repo / "out.html").read_bytes()
    html = html_bytes.decode("utf-8")
    assert html.lower().startswith("<!doctype html>")
    assert html.rstrip().endswith("</html>")

    canonical = (Path(__file__).parents[1] /
                 ".orchestra/pipelines/default/prompts/skills/html-artifacts/references/animation.md")
    scaffold = canonical.read_bytes().split(b"```html motion-template\n", 1)[1].split(b"\n```", 1)[0]
    assert html_bytes == scaffold + b"\n"  # Preserve all player JS and CSS, not just a nonempty fragment.
    parser = _ScaffoldParser()
    parser.feed(html)
    assert {"html", "head", "body", "style", "script", "svg"} <= parser.tags
