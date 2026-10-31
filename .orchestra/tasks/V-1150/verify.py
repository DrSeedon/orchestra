"""Final copy identity; raw paths remain in the ignored private evidence folder."""
import ast
import argparse
import hashlib
from pathlib import Path

import app
from app.publication_secrets import HUB_SECRET_SHAPES

parser = argparse.ArgumentParser()
parser.add_argument("--record-current", action="store_true")
record_current = parser.parse_args().record_current
root = Path(__file__).resolve().parents[3]
notes = root / ".orchestra/tasks/V-1150"
private = notes / "private"
private.mkdir(exist_ok=True)
imported = Path(app.__file__).resolve()
assert imported == root / "app/__init__.py", imported
(private / "import-path.txt").write_text(str(imported) + "\n")
paths = [
    "app/backend_codex.py", "app/session.py", "app/mcp_stdio.py",
    "app/static/js/app.js", "CHANGELOG.md",
    "tests/test_codex_compact_delivery_1150.py",
    "tests/test_codex_compact_ui_1150.py", "tests/test_codex_compact_ui_1150.cjs",
    "tests/test_codex_compact_immediate_1150.py",
    ".orchestra/tasks/V-1148/report.md", ".orchestra/tasks/V-1148/parent-acceptance.md",
    ".orchestra/tasks/V-1150/report.md", ".orchestra/tasks/V-1150/commands.md",
    ".orchestra/tasks/V-1150/verify.py", ".orchestra/tasks/V-1150/mutation_probe.py",
    ".orchestra/tasks/V-1150/.gitignore",
    ".orchestra/tasks/V-1150/mutation-results.txt",
    ".orchestra/tasks/V-1150/review-mutation-results.txt",
]
records = []
identity_file = notes / "source-sha256.txt"
previous = dict(line.split("  ", 1)[::-1] for line in identity_file.read_text().splitlines()) if identity_file.exists() else {}
for relative in paths:
    path = root / relative
    content = path.read_text()
    if path.suffix == ".py":
        ast.parse(content, filename=relative)
    for name, shape in HUB_SECRET_SHAPES:
        assert not shape.search(content), f"secret-shaped literal ({name}): {relative}"
    assert Path.home().name not in content, f"runtime user literal: {relative}"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if not record_current and relative in paths[:9] and relative in previous:
        assert digest == previous[relative], f"tested production/test bytes changed: {relative}"
    records.append(f"{digest}  {relative}")
identity_file.write_text("\n".join(records) + "\n")
print("APP_IMPORT=app/__init__.py (absolute path preserved privately)")
print(f"PASS: {len(paths)} file identities, Python syntax, secret forms and runtime-user literals")
print("PASS: current revision identity recorded" if record_current else
      "PASS: tested production/test bytes unchanged after mutation restoration")
