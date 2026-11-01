"""Deterministic measurements of copied sources, not a skill-quality score."""
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import subprocess

import app
from app import prompting

TASK = Path(__file__).resolve().parents[1]
ROOT = TASK.parents[2]


class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hidden = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript"}:
            self.hidden += 1
        if tag in {"p", "h1", "h2", "h3", "li", "div", "br", "blockquote", "time"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"}:
            self.hidden -= 1
        if tag in {"p", "h1", "h2", "h3", "li", "div", "blockquote"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)

    def result(self):
        return "\n".join(line.strip() for line in "".join(self.parts).splitlines() if line.strip()) + "\n"


rows = []
for path in sorted(prompting._SKILLS_DIR.glob("*.md")):
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    meta, body = prompting.parse_role_frontmatter(text)
    refs = sorted(set(re.findall(r"references/[\w.-]+", text)))
    rows.append({
        "path": str(path.relative_to(ROOT)), "name": meta["name"],
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw), "characters": len(text),
        "lines_splitlines": len(text.splitlines()), "newline_count": raw.count(b"\n"),
        "body_characters_after_parser_strip": len(body),
        "description": meta["description"], "description_characters": len(meta["description"]),
        "extra_frontmatter": sorted(set(meta) - {"name", "description"}),
        "references_mentioned": refs,
        "references_present": sorted(str(p.relative_to(path.parent / path.stem)) for p in
                                     (path.parent / path.stem / "references").rglob("*") if p.is_file()),
        "canonical_evals_present": (path.parent / path.stem / "evals/evals.json").is_file(),
        "repo_codex_entry_present": (ROOT / ".codex/skills" / path.stem / "SKILL.md").is_file(),
    })

upstreams = []
for prefix in ("agentskills--agentskills", "anthropics--skills"):
    commit = json.loads((TASK / "sources" / f"{prefix}-commit.json").read_text())
    upstreams.append({"repository": prefix.replace("--", "/"), "sha": commit["sha"],
                      "commit_url": commit["html_url"], "author_date": commit["commit"]["author"]["date"],
                      "committer_date": commit["commit"]["committer"]["date"]})
for file in (TASK / "sources").glob("*.html"):
    parser = VisibleText()
    content = file.read_text()
    if file.name == "telegram.html":
        start = content.index('data-post="vibecoding_tg/4167"')
        content = content[start:]
        content = content[content.index('<div class="tgme_widget_message_text'):]
        content = content[:content.index('<div class="tgme_widget_message_footer')]
    parser.feed(content)
    file.with_suffix(".txt").write_text(parser.result())

result = {"measured_utc": datetime.now(timezone.utc).isoformat(), "imported_app": str(Path(app.__file__).resolve()),
          "canonical_skills_root": str(prompting._SKILLS_DIR),
          "copy_has_git": (ROOT / ".git").exists(), "copy_has_codex_dir": (ROOT / ".codex").exists(),
          "copy_has_pipeline_manifest": (ROOT / ".orchestra/pipelines/default/pipeline.yaml").is_file(),
          "copy_has_claude_symlink": (ROOT / "CLAUDE.md").is_symlink(),
          "skills": rows, "upstream_pins": upstreams}
program = '/^```html motion-template/{f=1;next} f&&/^```/{exit} f'
result["scaffold_extraction_bytes"] = {
    "entrypoint_as_documented": len(subprocess.check_output(["awk", program, str(prompting._SKILLS_DIR / "html-artifacts.md")])),
    "actual_reference": len(subprocess.check_output(["awk", program, str(prompting._SKILLS_DIR / "html-artifacts/references/animation.md")])),
}
result["all_seven_index_characters"] = len(prompting.build_skills_index(sorted(prompting._SKILLS_DIR.glob("*.md")), []))
result["reference_metrics"] = [
    {"path": str(path.relative_to(ROOT)), "lines": len(path.read_text().splitlines()),
     "characters": len(path.read_text()), "bytes": path.stat().st_size,
     "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    for path in sorted(prompting._SKILLS_DIR.glob("*/references/*")) if path.is_file()
]
(TASK / "inventory.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
print(json.dumps(result, ensure_ascii=False, indent=2))
