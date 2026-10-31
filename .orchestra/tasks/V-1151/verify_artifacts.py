"""Scan only this task's deliverables by existing credential shapes; no inventory reads."""

from pathlib import Path
import sys

root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(root))

from app.publication_secrets import HUB_SECRET_SHAPES

task = root / ".orchestra/tasks/V-1151"
paths = [root / "app/manager.py", root / "app/private_folder.py",
         root / "tests/test_source_owned_dirs_v1151.py", root / "CHANGELOG.md"]
paths.extend(path for path in task.iterdir() if path.is_file())
paths.extend(path for path in (task / "round2").iterdir() if path.is_file())
found = []
for path in paths:
    content = path.read_text()
    found.extend(f"{path.relative_to(root)}: {label}" for label, pattern in HUB_SECRET_SHAPES
                 if pattern.search(content))
if found:
    raise SystemExit("\n".join(found))
print(f"Credential-shape scan: {len(paths)} task/source files, no matches.")
print("No credential inventory or files outside this checkout were read.")
