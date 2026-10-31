"""Read-only final checks on this task's artifacts and source snapshot."""
import ast
import hashlib
import re
from pathlib import Path

root = Path(__file__).resolve().parents[3]
notes = root / ".orchestra/tasks/V-1148"
count = 0
for line in (notes / "source-identity.txt").read_text().splitlines():
    if line.startswith("SHA256 "):
        path, digest = line.removeprefix("SHA256 ").split("=", 1)
        assert hashlib.sha256((root / path).read_bytes()).hexdigest() == digest, path
        count += 1
print(f"SOURCE_HASHES_UNCHANGED={count}")
for path in notes.glob("*.py"):
    ast.parse(path.read_text(), filename=path.name)
print("TASK_PYTHON_PARSE=PASS")
report = (notes / "report.md").read_text()
expected = ["path/trigger", "awaited contract", "timeout/cancellation behavior",
            "late terminal behavior", "context update source", "queue release",
            "frontend-visible status", "evidence symbol+test"]
table = report.split("| path/trigger", 1)[1].split("\n\n", 1)[0].splitlines()
table[0] = "| path/trigger" + table[0]
assert [part.strip() for part in table[0].split("|")[1:-1]] == expected
assert len(table[2:]) == 7
assert all(len(line.split("|")) == 10 for line in table[2:])
print("REQUIRED_EVIDENCE_TABLE=PASS")
# Shape scan is bounded to newly written research artifacts, not local logs.
patterns = [r"sk-" + r"[A-Za-z0-9_-]{20,}", r"gh[pousr]_" + r"[A-Za-z0-9]{20,}",
            r"-----BEGIN " + r"(?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
            r"eyJ[A-Za-z0-9_-]{10,}" + r"\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"]
for path in notes.iterdir():
    if path.is_file():
        content = path.read_text()
        assert not any(re.search(pattern, content) for pattern in patterns), path.name
print("COMMON_SECRET_SHAPES_IN_TASK_ARTIFACTS=NONE")
print("HEAD=UNAVAILABLE_NO_DOT_GIT")
