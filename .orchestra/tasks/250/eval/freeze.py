#!/usr/bin/env python3
"""Write a stable manifest for all preregistered inputs, excluding later raw results."""

from __future__ import annotations

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "freeze-manifest.sha256"
INCLUDED = [
    ROOT / "baseline-prompt.md",
    ROOT / "candidate-prompt.md",
    ROOT / "corpus.md",
    ROOT / "prereg.md",
    ROOT / "expected-outcomes.json",
    *sorted((ROOT / "eval" / "fixtures").rglob("*")),
    *sorted((ROOT / "eval" / "tasks").glob("*.md")),
    *sorted((ROOT / "eval" / "controls").rglob("*.py")),
    ROOT / "eval" / "run_eval.py",
    ROOT / "eval" / "grader.py",
    ROOT / "eval" / "freeze.py",
]


def main() -> None:
    rows = []
    for path in INCLUDED:
        if not path.is_file() or path == OUTPUT:
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        rows.append(f"{digest}  {path.relative_to(ROOT)}")
    OUTPUT.write_text("\n".join(rows) + "\n")


if __name__ == "__main__":
    main()
