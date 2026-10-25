"""Check artifact integrity, links, source metadata and publication shapes without HOME lookup."""
import ast
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import unquote

from app.publication_secrets import HUB_SECRET_SHAPES
from app.prompting import parse_role_frontmatter

TASK = Path(__file__).resolve().parents[1]
ROOT = TASK.parents[2]
errors = []
inventory = json.loads((TASK / "inventory.json").read_text())
format_results = []
allowed = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
for entry in inventory["skills"]:
    path = ROOT / entry["path"]
    metadata, _ = parse_role_frontmatter(path.read_text())
    name, description = metadata["name"], metadata["description"]
    essentials = (isinstance(name, str) and 1 <= len(name) <= 64 and name == name.lower()
                  and all(char.isalnum() or char == "-" for char in name)
                  and not name.startswith("-") and not name.endswith("-") and "--" not in name
                  and name == path.stem and isinstance(description, str) and 1 <= len(description) <= 1024)
    extra = sorted(set(metadata) - allowed)
    if not essentials:
        errors.append(f"essential format invalid: {entry['path']}")
    if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
        errors.append(f"source changed since inventory: {entry['path']}")
    format_results.append({"name": name, "required_fields_and_lengths": essentials,
                           "extra_top_level_fields": extra, "strict_allowed_fields": not extra})

link_count = 0
report = TASK / "report.md"
for target in re.findall(r"\]\(([^)]+)\)", report.read_text()):
    if target.startswith(("https://", "http://", "#")):
        continue
    filename, _, anchor = target.partition("#")
    path = (TASK / unquote(filename)).resolve()
    link_count += 1
    if not path.is_file():
        errors.append(f"broken report link: {target}")
    elif anchor.startswith("L") and anchor[1:].isdigit():
        if not 1 <= int(anchor[1:]) <= len(path.read_text().splitlines()):
            errors.append(f"invalid line anchor: {target}")

shape_findings = []
fingerprints = {}
for path in sorted(TASK.rglob("*")):
    if not path.is_file() or any(part in {"tmp", "isolated-home", "__pycache__"} for part in path.relative_to(TASK).parts):
        continue
    if path.name in {"final-audit.stdout", "final-audit.stderr", "final-audit.json", "artifact-sha256.json"}:
        continue
    raw = path.read_bytes()
    relative = path.relative_to(TASK).as_posix()
    fingerprints[relative] = hashlib.sha256(raw).hexdigest()
    content = raw.decode("utf-8", errors="replace")
    for kind, pattern in HUB_SECRET_SHAPES:
        match = pattern.search(content)
        if match:
            shape_findings.append({"file": relative, "kind": kind,
                                   "line": content[:match.start()].count("\n") + 1})
    if path.suffix == ".py":
        ast.parse(content, filename=str(path))

(TASK / "artifact-sha256.json").write_text(json.dumps(fingerprints, indent=2) + "\n")
print(json.dumps({"format": format_results, "local_line_links_checked": link_count,
                  "source_fingerprints_unchanged": not errors,
                  "publication_shape_findings": shape_findings, "errors": errors,
                  "artifact_count": len(fingerprints)}, indent=2))
raise SystemExit(bool(errors or shape_findings))
