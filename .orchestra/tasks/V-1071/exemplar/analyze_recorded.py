"""Recompute sample sizes and variation from the upstream public records."""
import json
import statistics
from pathlib import Path

TASK = Path(__file__).resolve().parents[1]
RUNS = TASK / "upstream/kit/examples/support-desk/example-run"
report = {}
for name, folder, variants in [
    ("fold-2026-10-08", RUNS / "results", ["baseline", "v1"]),
    ("as-tool-2026-10-09", RUNS / "as-tool/results", ["baseline", "v1"]),
    ("as-tool-rerun", RUNS / "as-tool/results", ["baseline-t01-t10", "v1-t01-t10"]),
]:
    result = {}
    for variant in variants:
        rows = [json.loads(line) for line in (folder / variant / "results.jsonl").read_text().splitlines()]
        tasks = sorted({r["prompt_id"] for r in rows})
        result[variant] = {
            "tasks": len(tasks), "conversations": len(rows), "models": sorted({r["model"] for r in rows}),
            "passing_conversations": sum(r["grade"]["task_complete"] for r in rows),
            "latency_s": {"mean": statistics.fmean(r["latency_s"] for r in rows),
                          "median": statistics.median(r["latency_s"] for r in rows),
                          "min": min(r["latency_s"] for r in rows), "max": max(r["latency_s"] for r in rows)},
            "model_calls_total": sum(r["model_calls"] for r in rows),
            "input_total": sum(r["in_tokens"] for r in rows), "output_total": sum(r["out_tokens"] for r in rows),
            "passes_by_task": {t: [r["grade"]["task_complete"] for r in rows if r["prompt_id"] == t] for t in tasks},
        }
    result["ratio_of_mean_latencies_before_over_after"] = (
        result[variants[0]]["latency_s"]["mean"] / result[variants[1]]["latency_s"]["mean"])
    report[name] = result
print(json.dumps(report, indent=2))
