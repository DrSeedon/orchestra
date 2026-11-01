"""Capture public figures and line-numbered local policy evidence, without running author code."""
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
from urllib.request import urlopen
import xml.etree.ElementTree as ET

TASK = Path(__file__).resolve().parent
REPO = TASK.parents[2]
EVIDENCE = TASK / "evidence"


class Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.ignore = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.ignore += 1
        if tag in {"p", "h1", "h2", "h3", "h5", "h6", "li", "pre", "section"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.ignore -= 1
        if tag in {"p", "li", "pre", "h3", "h5", "h6"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.ignore:
            self.parts.append(data)


parser = Text()
parser.feed((EVIDENCE / "paper.html").read_text())
(EVIDENCE / "paper-text.txt").write_text("".join(parser.parts))
figure_text = []
for name in ("Main", "StaleCases", "Channels", "Kinds", "Results", "Runs", "RewriteExample", "Actions"):
    url = f"https://arxiv.org/html/2610.30571v1/fig-{name}.svg"
    with urlopen(url, timeout=30) as response:
        body = response.read()
        print(response.status, url, len(body), hashlib.sha256(body).hexdigest())
    (EVIDENCE / f"fig-{name}.svg").write_bytes(body)
    tree = ET.fromstring(body)
    figure_text += [f"FIGURE {name}\n" + "\n".join("".join(t.itertext()) for t in tree.iter()
                                                 if t.tag == "{http://www.w3.org/2000/svg}text")]
(EVIDENCE / "figures-text.txt").write_text("\n\n".join(figure_text))
sources = [REPO / "AGENTS.md", REPO / "scripts/check_instruction_contract.py"]
sources += sorted((REPO / ".orchestra/pipelines/default/prompts").rglob("*.md"))
inventory = {str(p.relative_to(REPO)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
(EVIDENCE / "orchestra-source-sha256.json").write_text(json.dumps(inventory, indent=2) + "\n")
with (EVIDENCE / "orchestra-rules-numbered.txt").open("w") as output:
    for source in sources:
        output.write(f"\nFILE {source.relative_to(REPO)}\n")
        for n, line in enumerate(source.read_text().splitlines(), 1):
            output.write(f"{n:4d}: {line}\n")
print("local source files captured", len(sources))
print("local .git exists", (REPO / ".git").exists())
print("CLAUDE.md symlink", (REPO / "CLAUDE.md").is_symlink())
print("app directory exists", (REPO / "app").exists())
print("KB directory exists", (REPO / ".orchestra/kb").exists())
