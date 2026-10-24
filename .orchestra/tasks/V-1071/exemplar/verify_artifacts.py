"""Read-only integrity/publication checks; never loads credentials or live state."""
import ast
import hashlib
import json
from pathlib import Path
import re
import sys

TASK = Path(__file__).resolve().parents[1]
ROOT = TASK.parents[2]
sys.path.insert(0, str(ROOT))

from scripts.secret_scan import scan_text
from app.publication_secrets import HUB_SECRET_SHAPES

kit = json.loads((TASK / "upstream/manifest.json").read_text())
for row in kit["files"]:
    assert hashlib.sha256((TASK / "upstream/kit" / row["path"]).read_bytes()).hexdigest() == row["sha256"]
source = json.loads((TASK / "evidence/orchestra-source-manifest.json").read_text())
for row in source["files"]:
    assert hashlib.sha256((ROOT / row["path"]).read_bytes()).hexdigest() == row["sha256"]
for file in (TASK / "exemplar").rglob("*.py"):
    ast.parse(file.read_text(), filename=str(file.relative_to(TASK)))
for file in TASK.glob("*.md"):
    for target in re.findall(r"\]\(([^)]+)\)", file.read_text()):
        if target.startswith(("https://", "http://", "#")):
            continue
        assert (file.parent / target.split("#")[0]).is_file(), (file.name, target)

findings = []
files = 0
for path in sorted(TASK.rglob("*")):
    if not path.is_file() or path.suffix == ".pyc":
        continue
    try:
        text = path.read_text()
    except UnicodeError:
        continue
    files += 1
    findings += scan_text(text, str(path.relative_to(TASK)))
    for name, pattern in HUB_SECRET_SHAPES:
        for match in pattern.finditer(text):
            findings.append(f"{path.relative_to(TASK)}:{text.count(chr(10), 0, match.start()) + 1}: {name}")
    if str(ROOT) in text:
        findings.append(f"{path.relative_to(TASK)}: local workspace identifier")
assert not findings, findings
print(f"Pinned kit hashes: {len(kit['files'])}/{len(kit['files'])} match")
print(f"Orchestra snapshot hashes: {len(source['files'])}/{len(source['files'])} match")
print("Task-local Python AST and local Markdown links: OK")
print(f"Publication scan: {files} text files; 0 credential-shape or local-workspace findings")
print("Scanner used only content patterns; no credential inventory or environment values were read")
