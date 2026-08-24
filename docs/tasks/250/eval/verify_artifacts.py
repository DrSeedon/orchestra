#!/usr/bin/env python3
"""Mechanical completeness and secret-form checks for #250 research artifacts."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_COLUMNS = [
    "case/source",
    "user-visible or API contract",
    "brittle test pattern",
    "valid future change that should remain green",
    "target regression/mutant that must turn red",
    "whether existing test distinguishes both",
    "strongest minimal replacement",
    "proof command/output",
]
EXPECTED_RAW_FILES = {
    "prompt.txt", "events.jsonl", "stderr.txt", "last-message.txt",
    "diff.patch", "test_target.py", "metadata.json",
}
SECRET_FORMS = re.compile(
    r"y0_|sk-or-v1-|ya29\.|gh[pousr]_|AIza|Bearer\s+[A-Za-z0-9._-]{25,}"
)


def main() -> None:
    checks = []

    corpus_lines = (ROOT / "corpus.md").read_text().splitlines()
    header = next(line for line in corpus_lines if line.startswith("| case/source |"))
    columns = [cell.strip() for cell in header.strip("|").split("|")]
    rows = [
        line for line in corpus_lines
        if line.startswith("|") and not line.startswith("|---") and line != header
    ]
    checks.append(("corpus exact columns", columns == EXPECTED_COLUMNS, columns))
    checks.append(("corpus real-case rows", len(rows) == 13, len(rows)))

    raw_dirs = sorted(path for path in (ROOT / "raw").iterdir() if path.is_dir())
    checks.append(("raw run directories", len(raw_dirs) == 12, len(raw_dirs)))
    for path in raw_dirs:
        names = {item.name for item in path.iterdir() if item.is_file()}
        checks.append((f"{path.name} raw file set", names == EXPECTED_RAW_FILES, sorted(names)))

    summary = json.loads((ROOT / "analysis-summary.json").read_text())
    checks.append(("candidate six answers before edit", summary["candidate_adherence_count"] == "6/6", summary["candidate_adherence_count"]))
    checks.append(("paired model cells", len(summary["paired_task_scores"]) == 6, len(summary["paired_task_scores"])))
    checks.append(("behavioral score measured", summary["arms"]["baseline"]["score"] == 28 and summary["arms"]["candidate"]["score"] == 28, [summary["arms"]["baseline"]["score"], summary["arms"]["candidate"]["score"]]))

    manifest_ok = True
    manifest_rows = 0
    for line in (ROOT / "freeze-manifest.sha256").read_text().splitlines():
        digest, relative = line.split("  ", 1)
        manifest_rows += 1
        manifest_ok &= hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == digest
    checks.append(("frozen input hashes", manifest_ok and manifest_rows == 38, manifest_rows))

    secret_hits = []
    for path in (ROOT / "raw").rglob("*"):
        if not path.is_file():
            continue
        for number, line in enumerate(path.read_text(errors="replace").splitlines(), start=1):
            if SECRET_FORMS.search(line):
                secret_hits.append(f"{path.relative_to(ROOT)}:{number}")
    checks.append(("raw secret-form scan", not secret_hits, secret_hits))

    failed = False
    for name, ok, detail in checks:
        failed |= not ok
        print(f"{'PASS' if ok else 'FAIL'} {name}: {detail}")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()

