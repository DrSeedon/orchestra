"""Small counterexamples to over-interpreting the kit's offline summaries."""
import json
from pathlib import Path
import subprocess
import sys

TASK = Path(__file__).resolve().parents[1]
ROOT = TASK.parents[2]
SCRIPTS = TASK / "upstream/kit/skill/scripts"
sys.path.insert(0, str(SCRIPTS))

from chain_coverage import load_tasks
from compare import load as load_comparison, summarise

FIX = TASK / "exemplar/edge-fixtures"
FIX.mkdir(exist_ok=True)


def write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def run(name, script, *args):
    r = subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)],
                       capture_output=True, text=True, timeout=10)
    print(f"CASE {name}; exit={r.returncode}")
    print((r.stdout + r.stderr).replace(str(ROOT), "<WORKSPACE>"))
    return r


# Starts overlap completely; this fixture asserts independence as ground truth.
write(FIX / "parallel.jsonl", [
    {"trace_id": f"fixture-{i}", "agent": agent, "ts": ts, "duration_ms": 1000,
     "fixture_dependency": "none"}
    for i in range(2) for agent, ts in [("reader_a", 0), ("reader_b", 0.1)]])
r = run("parallel starts can look coupled", "coupling_map.py", FIX / "parallel.jsonl", "--json")
assert r.returncode == 0 and json.loads(r.stdout)["candidates"][0]["coupling"] == 1

write(FIX / "serial.jsonl", [
    {"trace_id": f"fixture-{i}", "agent": agent, "ts": ts}
    for i in range(2) for agent, ts in [("a", 0), ("b", 1)]])
write(FIX / "coverage/baseline/results.jsonl", [
    {"prompt_id": "split-repetitions", "rep": rep, "grade": {"task_complete": 1}, "by_agent": {agent: {}}}
    for rep, agent in [(0, "a"), (1, "b")]])
r = run("coverage unions agents across different reps", "chain_coverage.py", FIX / "serial.jsonl",
        FIX / "coverage", "baseline")
coverage_rows = [json.loads(line) for line in (FIX / "coverage/baseline/results.jsonl").read_text().splitlines()]
required_agents = {"a", "b"}
assert len(coverage_rows) == 2
assert all(not required_agents <= set(row["by_agent"]) for row in coverage_rows)
coverage_core = load_tasks(FIX / "coverage", "baseline", set())
task = coverage_core["split-repetitions"]
assert task["agents"] == required_agents and task["passes"] == task["reps"] == 2
assert r.returncode == 0
print(json.dumps({"case": "split-repetition coverage", "exit": r.returncode,
                  "required_agents": sorted(required_agents),
                  "agents_per_rep": [sorted(row["by_agent"]) for row in coverage_rows],
                  "core_agents_union": sorted(task["agents"]),
                  "core_passes": task["passes"], "core_reps": task["reps"]}, sort_keys=True))

for variant, grades in [("baseline", (1, 0)), ("changed", (0, 1))]:
    write(FIX / "equal-mean" / variant / "results.jsonl", [
        {"prompt_id": case, "rep": 0, "grade": {"task_complete": grade}, "model": "synthetic-no-model"}
        for case, grade in zip(["safety_case", "ordinary_case"], grades)])
r = run("aggregate gate is not a no-flips gate", "compare.py", FIX / "equal-mean", "baseline", "changed",
        "--fail-if-worse")
before = load_comparison(FIX / "equal-mean", "baseline", "task_complete")
after = load_comparison(FIX / "equal-mean", "changed", "task_complete")
assert set(before["cases"]) == set(after["cases"]) == {"safety_case", "ordinary_case"}
common = sorted(before["cases"])
before_core = summarise(before, common, None, None)
after_core = summarise(after, common, None, None)
assert before_core["score"] == after_core["score"] == 0.5
assert before_core["per_case"]["safety_case"] == 1 and after_core["per_case"]["safety_case"] == 0
assert before_core["per_case"]["ordinary_case"] == 0 and after_core["per_case"]["ordinary_case"] == 1
assert r.returncode == 0
print(json.dumps({"case": "compensated safety regression", "exit": r.returncode,
                  "aggregate_before": before_core["score"], "aggregate_after": after_core["score"],
                  "per_case_before": before_core["per_case"],
                  "per_case_after": after_core["per_case"]}, sort_keys=True))
print("EDGE CASES CONFIRMED; all data synthetic; no production or model performance claim")
