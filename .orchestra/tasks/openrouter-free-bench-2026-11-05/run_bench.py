"""Explicit, isolated evaluation of five user-authorized free Harness routes.

Uses local_bench's actual namespace, frozen snapshots and external oracles.
No platform worker is spawned and no production configuration is changed.
"""
import argparse
import asyncio
import ctypes
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time
import urllib.request

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
from scripts.local_bench import isolation, runner, snapshot
from scripts.local_bench.process import run_process, write_json

MODELS = [
    ("flint", "recursive/flint-v1.0:free", "Recursive"),
    ("dots", "dots-studio/dots-3-note-preview:free", "Dots Studio"),
    ("ultra", "nvidia/nemotron-3-ultra-550b-a55b:free", "NVIDIA"),
    ("north", "cohere/north-mini-code:free", "Cohere"),
    ("super-vl", "nvidia/nemotron-3.5-super-vl:free", "NVIDIA"),
]

JSON_ORACLE = '''import json
from pathlib import Path
text=Path('.bench/response.txt').read_text().strip()
decoder=json.JSONDecoder()
objects=[]
for i,c in enumerate(text):
 if c=='{':
  try:
   obj,_=decoder.raw_decode(text[i:])
   if isinstance(obj,dict): objects.append(obj)
  except ValueError: pass
assert objects, 'missing JSON response'
actual=objects[-1]
expected=EXPECTED
assert actual==expected, (actual,expected)
events=[json.loads(x) for x in Path('.bench/transcript.jsonl').read_text().splitlines() if x.strip()]
assert any(x.get('type')=='bench.event' and x.get('event_type')=='tool_use' for x in events), 'no tool invocation'
print('PASS')
'''


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def cases(output, sandbox):
    runtime_paths = [str(ROOT / "app"), str(ROOT / ".venv"), str(HERE / "harness_arm.py")]
    identities = output / "synthetic-identity"
    write(identities / "passwd", f"bench:x:{os.getuid()}:{os.getgid()}:Benchmark:/home/bench:/bin/sh\n")
    write(identities / "group", f"bench:x:{os.getgid()}:\n")
    definitions = []
    for name in ("protocol", "repair", "document"):
        base = output / "questions" / name
        source = base / "source"
        source.mkdir(parents=True)
        expected = None
        reference = {}
        if name == "protocol":
            write(source / "marker.txt", "73519428\n")
            prompt = 'Use a tool to read marker.txt. Return only JSON {"marker":<integer read from the file>}. Do not modify files.'
            expected = {"marker": 73519428}
            oracle = JSON_ORACLE.replace("EXPECTED", repr(expected))
            allowed = []
        elif name == "repair":
            example = ROOT / "scripts/local_bench/examples/repair"
            write(source / "calc.py", (example / "source/calc.py").read_text())
            prompt = (example / "prompt.txt").read_text() + "\nUse the tools; only calc.py may be changed. Check your fix with a shell one-liner, without adding other files."
            oracle = (example / "oracle.py").read_text()
            fixed = base / "accepted.py"
            write(fixed, (example / "reference.py").read_text())
            reference = {"calc.py": str(fixed)}
            allowed = ["calc.py"]
        else:
            lines = ["SYNTHETIC release journal. Only CURRENT rows are authoritative."]
            lines += [f"ARCHIVE note {i:03d}: planned owner=Unknown, budget=9999; superseded." for i in range(1, 61)]
            lines += [
                "CURRENT Amber: ready; owner Iris; release 2026-12-08; budget 480.",
                "CURRENT Birch: blocked; owner Rowan; release undecided; budget 120.",
                "CURRENT Cedar: cancelled; owner Elm; release withdrawn; budget 0.",
                "DRAFT Amber: owner Olive; release 2027-01-01; budget 700. NOT APPROVED.",
            ]
            write(source / "journal.txt", "\n".join(lines) + "\n")
            expected = {"ready": ["Amber"], "blocked": ["Birch"], "cancelled": ["Cedar"],
                        "amber_owner": "Iris", "amber_release": "2026-12-08", "amber_budget": 480,
                        "current_line_numbers": [62, 63, 64]}
            prompt = ("Read journal.txt with tools. Use only authoritative current records; ignore drafts and superseded notes. "
                      "Return only JSON with keys ready, blocked, cancelled (release-name arrays), amber_owner, "
                      "amber_release (ISO date), amber_budget (number), current_line_numbers (all three CURRENT record line numbers). Do not modify files.")
            oracle = JSON_ORACLE.replace("EXPECTED", repr(expected))
            allowed = []
        oracle_path = base / "oracle.py"
        write(oracle_path, oracle)
        write(base / "prompt.txt", prompt)
        seed = base / "frozen-input"
        manifest = snapshot.build({"directory": str(source), "include": [p.name for p in source.iterdir()]}, seed)
        frozen_path = base / "frozen-oracle" / "oracle.py"
        write(frozen_path, oracle)
        frozen_oracle = {"oracle.py": str(frozen_path)}
        config = {"_provider": True, "_unboxed": False, "_isolation": sandbox,
                  "_synthetic_identity": str(identities),
                  "_config_dir": str(base), "runtime_paths": runtime_paths,
                  "source": {"directory": str(source), "include": [p.name for p in source.iterdir()]},
                  "oracle": {"command": ["{python}", "oracle.py"], "files": {"oracle.py": str(oracle_path)}, "timeout_seconds": 15},
                  "controls": {"reference_files": reference}, "grace_seconds": 2}
        runner.validate_runtime_mounts(config, output)
        ref_seed = base / "reference-input"
        snapshot.copy_tree(seed, ref_seed)
        snapshot.overlay(ref_seed, reference)
        ref_execution = base / "reference-execution"
        ref_execution.mkdir()
        write(ref_execution / "response.txt", json.dumps(expected) if expected else "")
        write(ref_execution / "stdout.jsonl", json.dumps({"type": "bench.event", "event_type": "tool_use", "content": "read fixture"}) + "\n")
        definitions.append({"name": name, "base": base, "seed": seed, "reference": ref_seed,
                            "ref_execution": ref_execution, "config": config, "oracle": frozen_oracle,
                            "prompt": prompt, "allowed": allowed, "manifest": manifest,
                            "oracle_sha256": hashlib.sha256(oracle.encode()).hexdigest()})
    return definitions


def provider_command(config, work, home, command, port=0):
    argv = runner.sandbox_command(config, work, home, command, port)
    index = argv.index("/usr/bin/python3")
    identity = Path(config["_synthetic_identity"])
    argv[index:index] = ["--ro-bind", str(identity / "passwd"), "/etc/passwd",
                         "--ro-bind", str(identity / "group"), "/etc/group",
                         "--hostname", "benchmark"]
    return argv


def check_identity(output, config):
    work, home = output / "identity-check-work", output / "identity-check-home"
    work.mkdir(); home.mkdir()
    write(work / "synthetic.txt", "public synthetic benchmark file\n")
    code = "import os,pwd,grp,socket;print(pwd.getpwuid(os.getuid()).pw_name);print(grp.getgrgid(os.getgid()).gr_name);print(socket.gethostname())"
    argv = provider_command(config, work, home, [sys.executable, "-c", code])
    result = subprocess.run(argv, cwd=work, env=runner.environment("/home/bench", "/tmp"),
                            capture_output=True, text=True, timeout=15)
    valid = result.returncode == 0 and result.stdout.splitlines() == ["bench", "bench", "benchmark"]
    write_json(output / "identity-check.json", {"passed": valid, "returncode": result.returncode})
    if not valid:
        raise ValueError("synthetic namespace identity check failed")
    print("IDENTITY synthetic passwd/group/hostname PASS", flush=True)


async def controls(definitions):
    for case in definitions:
        config, oracle, base = case["config"], case["oracle"], case["base"]
        red = await runner.evaluate(config, case["seed"], oracle, base / "baseline-control")
        green = await runner.evaluate(config, case["reference"], oracle, base / "reference-control", execution=case["ref_execution"])
        write_json(base / "controls.json", {"baseline": red, "reference": green})
        if red["passed"] or not green["passed"]:
            raise ValueError("Frozen oracle controls failed: " + case["name"])
        print("CONTROLS", case["name"], "red=FAIL reference=PASS", flush=True)


def credentials():
    code = ("import json,pathlib;from dotenv import dotenv_values;"
            "e=dotenv_values('.env');p=pathlib.Path('data/disabled_providers.json');"
            "d=json.loads(p.read_text()) if p.exists() else {};"
            "print(json.dumps({'api_key':e.get('OPENROUTER_API_KEY') or e.get('OPENROUTER_KEY'),"
            "'disabled':d.get('disabled_providers',[]) if isinstance(d,dict) else d}))")
    command = "cd /home/kesha/orchestra && .venv/bin/python -c " + shlex.quote(code)
    result = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "orchestra-vps", command],
                            capture_output=True, text=True, timeout=20, check=True)
    data = json.loads(result.stdout)
    if not data.get("api_key") or {"harness", "openrouter"} & set(data["disabled"]):
        raise ValueError("OpenRouter credential absent or provider disabled")
    return data


def live_catalog():
    with urllib.request.urlopen("https://openrouter.ai/api/v1/models", timeout=25) as response:
        raw = json.load(response)["data"]
    ids = {item[1] for item in MODELS}
    rows = [row for row in raw if row.get("id") in ids]
    if {row["id"] for row in rows} != ids:
        raise ValueError("one of the five exact free routes is absent")
    for row in rows:
        if "tools" not in row.get("supported_parameters", []) or any(Decimal(str(value)) != 0 for value in row.get("pricing", {}).values()):
            raise ValueError("route is no longer tool-capable and zero-priced: " + row["id"])
    return rows


async def execute(output, definitions, catalog, auth):
    records = []
    total_requests = 0
    next_request = 0.0
    isolation.PROVIDER_HOSTS = frozenset({"openrouter.ai"})
    for short, model, developer in MODELS:
        route_limited = False
        for case in definitions:
            frozen = Path(case["oracle"]["oracle.py"])
            if hashlib.sha256(frozen.read_bytes()).hexdigest() != case["oracle_sha256"]:
                raise RuntimeError("frozen oracle changed; evaluation stopped")
            if route_limited or total_requests + 3 > 45:
                records.append({"model": model, "case": case["name"], "status": "not_run_after_limit"})
                continue
            arm = output / "arms" / short / case["name"]
            arm.mkdir(parents=True)
            work, home = arm / "work", arm / "home"
            snapshot.copy_tree(case["seed"], work)
            home.mkdir()
            config = case["config"]
            relay = await isolation.Relay().start()
            try:
                env = runner.environment("/home/bench", "/tmp")
                env.update({"PYTHONPATH": str(ROOT), "HARNESS_PROVIDER_ORDER": "",
                            "ORCHESTRA_DISABLED_PROVIDERS": ",".join(auth["disabled"])})
                env.update({k: f"http://127.0.0.1:{relay.port}" for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy")})
                command = provider_command(config, work, home, [sys.executable, str(HERE / "harness_arm.py")], relay.port)
                payload = {"api_key": auth["api_key"], "model": model, "catalog": catalog,
                           "case": case["name"], "prompt": case["prompt"], "not_before": next_request}
                print("START", short, case["name"], flush=True)
                process = await run_process(command, work, env, arm / "execution", runtime="harness",
                                            prompt=json.dumps(payload), timeout=115, grace=3)
                rows = []
                for line in (arm / "execution/stdout.jsonl").read_text().splitlines():
                    try: rows.append(json.loads(line))
                    except ValueError: pass
                final = next((row for row in reversed(rows) if row.get("type") == "bench.final"), {})
                requests = [row for row in rows if row.get("type") == "bench.request"]
                total_requests += len(requests)
                next_request = max((row["started"] + 3.2 for row in requests), default=next_request)
                write(arm / "execution/response.txt", final.get("text", ""))
                try:
                    changed, unexpected = snapshot.changes(snapshot.inventory(case["seed"]), snapshot.inventory(work), case["allowed"])
                    verdict = await runner.evaluate(config, work, case["oracle"], arm / "external-oracle", execution=arm / "execution")
                    passed = verdict["passed"] and not unexpected
                except (ValueError, OSError) as error:
                    passed, unexpected = False, [type(error).__name__]
                error = str(final.get("error", ""))
                route_limited = "rate limit" in error.lower() or "429" in error
                row = {"model": model, "developer": developer, "case": case["name"],
                       "oracle_pass": passed, "runtime_ok": final.get("ok", False),
                       "stop_reason": final.get("stop_reason"), "error": error,
                       "requests": len(requests), "cost_usd": final.get("cost_usd"),
                       "round_usages": final.get("round_usages", []), "unexpected_changes": unexpected,
                       "completion": process["completion"], "returncode": process["returncode"],
                       "tool_calls": sum(r.get("type") == "bench.event" and r.get("event_type") == "tool_use" for r in rows),
                       "input_sha256": hashlib.sha256(json.dumps(case["manifest"]["files"], sort_keys=True).encode()).hexdigest(),
                       "oracle_sha256": case["oracle_sha256"]}
                write_json(arm / "result.json", row)
                records.append(row)
                print("RESULT", short, case["name"], "oracle=" + str(passed), "runtime=" + str(row["runtime_ok"]), "requests=" + str(len(requests)), flush=True)
                write_json(output / "results.json", {"records": records, "model_requests": total_requests})
                if not final and not requests:
                    raise RuntimeError("Harness arm failed before inference; inspect execution/stderr.log")
                if any(item.get("cost_usd", 0) and item["cost_usd"] > 0 for item in records):
                    raise RuntimeError("unexpected positive provider cost; evaluation stopped")
            finally:
                await relay.close()
    return records


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true", help="explicit live free-model evaluation")
    args = parser.parse_args()
    os.nice(10)
    Path("/proc/self/oom_score_adj").write_text("1000")
    ctypes.CDLL(None).prctl(4, 0, 0, 0, 0)
    output = HERE / "runs" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + str(time.time_ns())[-5:])
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    write(output / ".gitignore", "*\n")
    sandbox = isolation.preflight([str(ROOT / ".venv")])
    definitions = cases(output, sandbox)
    await controls(definitions)
    check_identity(output, definitions[0]["config"])
    write_json(output / "manifest.json", {"app_path": str(ROOT / "app"), "models": MODELS,
        "questions": [{"name": c["name"], "manifest": c["manifest"], "oracle_sha256": c["oracle_sha256"]} for c in definitions],
        "maximum_requests": 45, "max_rounds_per_question": 3, "reasoning_effort": "medium", "max_tokens": 1536})
    print("OUTPUT", output, flush=True)
    if not args.run:
        return
    catalog = live_catalog()
    write_json(output / "live-catalog.json", catalog)
    auth = credentials()
    request = urllib.request.Request("https://openrouter.ai/api/v1/auth/key", headers={"Authorization": "Bearer " + auth["api_key"]})
    with urllib.request.urlopen(request, timeout=25) as response:
        status = json.load(response).get("data", {})
    write_json(output / "key-status.json", {k: status.get(k) for k in ("is_free_tier", "is_disabled", "rate_limit", "limit_remaining")})
    if status.get("is_disabled"):
        raise ValueError("API key disabled")
    await execute(output, definitions, catalog, auth)


if __name__ == "__main__":
    asyncio.run(main())
