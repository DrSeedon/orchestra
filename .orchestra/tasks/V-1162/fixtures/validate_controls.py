#!/usr/bin/env python3
"""Run local fixture controls only; this script never starts a model/provider."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[4]
FIXTURES = Path(__file__).resolve().parent
VALIDATION = FIXTURES / "validation"
PRIVATE_OUTPUT = ROOT / ".orchestra" / "private" / "V-1162-fixture-validation"
CASES = (
    "simple-199-t3",
    "simple-201-accounting",
    "complex-v620-binding",
    "complex-v543-pidfd",
)


def main() -> None:
    VALIDATION.mkdir(exist_ok=True)
    PRIVATE_OUTPUT.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    rows = []
    for fixture in CASES:
        directory = FIXTURES / fixture
        validator = directory / "oracle" / "validate.py"
        for label, candidate, expected in (
            ("base-red", directory / "seed", "RED"),
            ("reference-green", directory / "reference", "GREEN"),
        ):
            started = time.monotonic()
            result = subprocess.run(
                [sys.executable, str(validator), "--candidate", str(candidate)],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            duration = time.monotonic() - started
            prefix = PRIVATE_OUTPUT / f"{fixture}.{label}"
            stdout_path = Path(f"{prefix}.stdout.txt")
            stderr_path = Path(f"{prefix}.stderr.txt")
            stdout_path.write_text(result.stdout)
            stderr_path.write_text(result.stderr)
            outcome = (
                expected == "RED" and result.returncode != 0
            ) or (
                expected == "GREEN" and result.returncode == 0
            )
            rows.append({
                "fixture": fixture,
                "control": label,
                "expected": expected,
                "actual": "RED" if result.returncode else "GREEN",
                "returncode": result.returncode,
                "duration_seconds": round(duration, 3),
                "stdout_path": str(stdout_path.relative_to(ROOT)),
                "stderr_path": str(stderr_path.relative_to(ROOT)),
                "outcome": "PASS" if outcome else "FAIL",
            })
    result_path = VALIDATION / "controls.json"
    result_path.write_text(json.dumps({"controls": rows}, indent=2) + "\n")
    for row in rows:
        print(f"{row['fixture']} {row['control']}: {row['actual']} rc={row['returncode']} {row['outcome']}")
    print(f"receipt: {result_path.relative_to(ROOT)}")
    if any(row["outcome"] != "PASS" for row in rows):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
