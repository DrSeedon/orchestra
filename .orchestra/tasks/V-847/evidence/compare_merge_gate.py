from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time


root = Path(__file__).resolve().parents[4]
evidence = Path(__file__).resolve().parent
sys.path.insert(0, str(root))
tests = ["tests/test_session_logs_conditional.py", "tests/test_mcp_stdio.py"]
for label, pytests_addopts in (("serial", "-n 0"), ("xdist2", None)):
    if pytests_addopts is None:
        os.environ.pop("PYTEST_ADDOPTS", None)
    else:
        os.environ["PYTEST_ADDOPTS"] = pytests_addopts
    started = time.monotonic()
    from app.merge_test_gate import run_pytest

    result = run_pytest(str(root), tests, timeout=300)
    elapsed = time.monotonic() - started
    (evidence / f"merge_gate_{label}.log").write_text(
        result["output"], encoding="utf-8",
    )
    record = {
        "elapsed_s": round(elapsed, 3),
        "status": result["status"],
        "reason": result["reason"],
        "exit_code": result["exit_code"],
        "passed_count": result.get("passed"),
        "passed_nodes": len(result.get("passed_tests", [])),
        "failed_nodes": result.get("failed_tests", []),
        "xdist_output_present": "[gw0]" in result["output"],
    }
    (evidence / f"merge_gate_{label}.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    if result["status"] != "passed":
        raise SystemExit(f"{label}: {record}")
print("merge gate comparison complete")
