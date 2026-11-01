"""Normalize this task's publication artifacts; never read live secret stores."""
from pathlib import Path
import re

from app.publication_secrets import HUB_SECRET_SHAPES
from app.secret_mask import mask_secrets
from scripts.secret_scan import scan_text

root = Path.cwd().resolve()
notes = root / ".orchestra/tasks/V-1064"
slug_prefix = re.sub(r"[^a-zA-Z0-9]+", "-", str(root)).strip("-").lower()[:80]
for path in notes.glob("*.log"):
    text = path.read_text(errors="replace").replace(str(root), "/remote/workspace")
    text = text.replace(str(Path.home()), "/remote/workspace")
    text = text.replace(slug_prefix, "remote-workspace")
    text = mask_secrets(text)
    for name, shape in HUB_SECRET_SHAPES:
        text = shape.sub(f"[REDACTED {name}]", text)
    path.write_text(text)

paths = [root / rel for rel in (
    "app/hub_workspace.py", "app/backend_hub.py", "tests/test_hub_download_v1064.py", "CHANGELOG.md")]
paths.extend(path for path in notes.iterdir()
             if path.is_file() and path.suffix in {".md", ".log", ".json", ".py", ".txt"})
findings = []
for path in paths:
    text = path.read_text(errors="replace")
    findings.extend(scan_text(text, str(path.relative_to(root))))
    if path.parent == notes and str(root) in text:
        findings.append(f"{path.name}: unnormalized workspace prefix")
    if path.parent == notes and str(Path.home()) in text:
        findings.append(f"{path.name}: unnormalized account prefix")
    if path.parent == notes and slug_prefix in text:
        findings.append(f"{path.name}: unnormalized workspace slug")
print("\n".join(findings) if findings else f"PASS: shape scan and prefix checks, {len(paths)} files")
raise SystemExit(bool(findings))
