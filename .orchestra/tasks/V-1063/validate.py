"""Check only deliverable source/artifacts, never private runtime inventories."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.secret_scan import scan_text

artifacts = Path(__file__).resolve().parent
sources = [ROOT / name for name in (
    "app/hub_workspace.py", "tests/test_publication_gate_v1047.py",
    "tests/test_hub_inputs_v1063.py", "CHANGELOG.md",
)]
notes = [p for p in artifacts.iterdir() if p.is_file()]
findings = []
for path in sources + notes:
    text = path.read_text()
    findings.extend(scan_text(text, str(path.relative_to(ROOT))))
    if path in notes:
        for private in (str(ROOT), str(Path.home()), Path.home().name, ROOT.parent.name, ROOT.name):
            assert private not in text, f"private machine prefix in {path.name}"
assert not findings, "\n".join(findings)
print(f"Canonical secret-shape scan: {len(sources)} source files and {len(notes)} task artifacts clean.")
print("Private workspace/HOME prefixes, hostname, workspace identifier and username: absent from artifacts.")
