"""Syntax, whitespace and secret-shape checks for the V-1045 result only."""

import re
from pathlib import Path


root = Path(__file__).resolve().parents[3]
paths = [root / "app/message_deliveries.py", root / "tests/test_message_failure_backfill_1045.py"]
paths += [path for path in Path(__file__).parent.iterdir() if path.is_file()]
secret_shapes = (
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    r"\bsk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,}",
    r"\bgh[pousr]_[A-Za-z0-9]{20,}",
    r"\bgithub_pat_[A-Za-z0-9_]{30,}",
    r"\bAKIA[A-Z0-9]{16}\b",
    r"\b\d{8,12}:[A-Za-z0-9_-]{30,}\b",
)
for path in paths:
    source = path.read_text()
    if path.suffix == ".py":
        compile(source, str(path), "exec")
    if path.suffix in {".py", ".md"} and any(line.rstrip() != line for line in source.splitlines()):
        raise AssertionError(f"Trailing whitespace: {path}")
    if any(re.search(pattern, source) for pattern in secret_shapes):
        raise AssertionError(f"Secret-shaped value needs review: {path}")
print(f"PASS: syntax, trailing whitespace and secret-shape checks on {len(paths)} files")
print("Canonical app.secret_mask is absent; scan was limited to explicit shapes and synthetic outputs.")
