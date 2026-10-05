from __future__ import annotations

import json
import sys
from pathlib import Path

repo = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(repo))
from app.merge_test_gate import evaluate_mutation_gate

worktree = str(repo)
target = "f122aa50e41cefeb026074fce322deb1b939574f"
cases = {
    "T012": ["app/merge_test_gate.py", "tests/test_merge_gate_mutation_702.py"],
    "T072": ["app/mcp_stdio.py", "tests/test_mcp_stdio.py"],
    "T099": [
        "app/routes/sessions.py", "app/merge_operations.py",
        "tests/test_unbound_merge_recovery_702.py",
        "tests/test_taskless_merge_no_id_702.py",
    ],
    "T159": [
        "app/mcp_stdio.py", "app/merge_operations.py",
        "app/routes/merge_operations.py", "tests/test_taskless_delivery_702.py",
    ],
    "T101": [
        "app/merge_operations.py", "tests/test_diff_budget_recovery_702.py",
    ],
}
if len(sys.argv) > 1:
    cases = {name: paths for name, paths in cases.items() if name in sys.argv[1:]}
results = {}
for name, paths in cases.items():
    result = evaluate_mutation_gate(
        worktree, paths, target_sha=target,
    )
    results[name] = {
        key: result.get(key)
        for key in (
            "status", "reason", "exit_code", "tests", "changed_sources",
            "selected_nodes", "fallback_files", "output",
        )
    }
print(json.dumps(results, ensure_ascii=False, indent=2))
if any(result.get("status") != "PASSED" for result in results.values()):
    raise SystemExit(1)
