"""Replay the pinned kit and public recorded results. Invoke with the broker uv."""
import hashlib
import json
import os
import pathlib
import subprocess
import sys

TASK = pathlib.Path(__file__).resolve().parents[1]
ROOT = TASK.parents[2]
KIT = TASK / "upstream/kit"
DEMO = KIT / "examples/support-desk"
EVIDENCE = TASK / "evidence"
TEMP = EVIDENCE / "temporary"
TEMP.mkdir(exist_ok=True)
env = {**os.environ, "KIT_MODEL": "fake", "PYTHONDONTWRITEBYTECODE": "1", "UV_OFFLINE": "1",
       "TMPDIR": str(TEMP), "PYTHONPATH": str(TASK / "exemplar/network_guard"),
       "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
results = []


def run(name, args, cwd=ROOT, expected=0):
    command = [sys.executable, *map(str, args)]
    r = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, timeout=55)
    out = (r.stdout + ("\nSTDERR:\n" + r.stderr if r.stderr else "")).replace(str(ROOT), "<WORKSPACE>")
    (EVIDENCE / f"{name}.stdout").write_text(out)
    results.append({"name": name, "argv": ["python", *[str(a).replace(str(ROOT), "<WORKSPACE>") for a in args]],
                    "cwd": str(cwd.relative_to(ROOT)) or ".", "exit": r.returncode, "expected_exit": expected})
    print(f"{name}: exit={r.returncode}, expected={expected}")
    assert r.returncode == expected, f"Inspect evidence/{name}.stdout"


run("network-guard", ["-c", "import socket; socket.create_connection(('example.com',443))"], expected=1)
run("manual-sample", [TASK / "exemplar/manual_sample.py"])
out = os.path.relpath(EVIDENCE / "smoke-results", DEMO)
run("smoke-original", ["evals/run_eval.py", "--variant", "original", "--out", out, "--fresh"], DEMO)
run("smoke-single", ["evals/run_eval.py", "--variant", "single", "--app", "single_loop", "--out", out, "--fresh"], DEMO)
run("coupling-demo", ["skill/scripts/coupling_map.py", "examples/support-desk/traces/traces.jsonl"], KIT)
run("coverage-recorded-12", ["skill/scripts/chain_coverage.py", "examples/support-desk/traces/traces.jsonl",
                            "examples/support-desk/example-run/results", "baseline"], KIT, expected=1)
run("coverage-smoke-19", ["skill/scripts/chain_coverage.py", "examples/support-desk/traces/traces.jsonl",
                         os.path.relpath(EVIDENCE / "smoke-results", KIT), "original"], KIT)
run("recorded-fold", ["skill/scripts/compare.py", "examples/support-desk/example-run/results", "baseline", "v1"], KIT)
run("recorded-as-tool", ["skill/scripts/compare.py", "examples/support-desk/example-run/as-tool/results", "baseline", "v1"], KIT)
run("recorded-as-tool-rerun", ["skill/scripts/compare.py", "examples/support-desk/example-run/as-tool/results", "baseline-t01-t10", "v1-t01-t10"], KIT)
run("estimate-full", ["skill/scripts/estimate.py", "examples/support-desk/example-run/as-tool/results", "baseline", "--reps", "2", "--actual", "v1"], KIT)
run("estimate-probe", ["skill/scripts/estimate.py", "examples/support-desk/example-run/as-tool/results", "probe", "--tasks", "19", "--reps", "2", "--heavy", "3"], KIT)

manifest = json.loads((TASK / "upstream/manifest.json").read_text())
for row in manifest["files"]:
    assert hashlib.sha256((KIT / row["path"]).read_bytes()).hexdigest() == row["sha256"], row["path"]
(EVIDENCE / "commands.json").write_text(json.dumps(results, indent=2) + "\n")
print(f"PINNED KIT UNCHANGED: {len(manifest['files'])} source/fixture files")
print("OFFLINE REPLAY OK; no real provider CLI, SDK calls or evaluators were run")
