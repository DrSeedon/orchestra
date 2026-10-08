#!/usr/bin/env python3
"""V-758 small-task oracle. Usage: oracle.py <S1..S5> <workdir> <result.json> <pristine_commit>"""
import ast, csv, json, re, subprocess, sys
from pathlib import Path

PY = "/opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python"
REPO = "/home/kesha/orchestra"
task, wd, resf, commit = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4]
checks = {}


def show(path):
    return subprocess.run(["git", "-C", REPO, "show", f"{commit}:{path}"], capture_output=True, text=True).stdout


def answer_text():
    try:
        return json.loads(resf.read_text()).get("result", "") or ""
    except Exception:
        return ""


def tracked_diff():
    return subprocess.run(["git", "-C", str(wd), "status", "--porcelain"], capture_output=True, text=True).stdout.splitlines()


def pytest_counts(files, cwd):
    r = subprocess.run([PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", *files], cwd=cwd, capture_output=True, text=True)
    out = r.stdout + r.stderr
    p = sum(int(m) for m in re.findall(r"(\d+) passed", out))
    f = sum(int(m) for m in re.findall(r"(\d+) failed", out)) + sum(int(m) for m in re.findall(r"(\d+) error", out))
    return p, f, out


if task == "S1":
    txt = answer_text()
    m = re.findall(r"\{.*\}", txt, re.S)
    ans = {}
    for cand in reversed(m):
        try:
            ans = json.loads(cand); break
        except Exception:
            continue
    models = show("app/models.py")
    node = ast.parse(models)
    routes = None
    for n in ast.walk(node):
        if isinstance(n, ast.AnnAssign) and getattr(n.target, "id", "") == "PAID_HARNESS_ROUTES":
            routes = len(n.value.args[0].elts)
    sm = show("app/secret_mask.py")
    line = next(i for i, l in enumerate(sm.splitlines(), 1) if l.startswith("_MIN_LEN ="))
    words = None
    for n in ast.walk(ast.parse(sm)):
        if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "_SECRET_WORDS":
            words = len(n.value.elts)
    checks["paid_routes"] = ans.get("paid_routes") == routes
    checks["admission_fn"] = ans.get("admission_fn") == "harness_route_allowed"
    checks["min_len_line"] = ans.get("min_len_line") == line
    checks["min_len_value"] = ans.get("min_len_value") == 12
    checks["secret_words"] = ans.get("secret_words") == words
    checks["no_file_changes"] = not tracked_diff()
elif task == "S2":
    out = subprocess.run(["git", "-C", REPO, "ls-tree", "--name-only", commit, "tests/"], capture_output=True, text=True).stdout.split()
    truth = {}
    for f in sorted(out):
        if re.fullmatch(r"tests/test_.*_5\d\d\.py", f):
            body = show(f)
            truth[f] = (body.count("\n"), len(re.findall(r"^\s*(?:async\s+)?def test_", body, re.M)))
    p = wd / "inventory.csv"
    rows = []
    try:
        rows = list(csv.reader(p.read_text().splitlines()))
    except Exception:
        pass
    checks["header"] = bool(rows) and rows[0] == ["file", "lines", "tests"]
    got = {}
    for r in rows[1:]:
        if len(r) == 3:
            got[r[0]] = r[1:]
    checks["file_set"] = set(got) == set(truth)
    checks["lines"] = bool(truth) and all(got.get(f, [None])[0] == str(v[0]) for f, v in truth.items())
    checks["tests"] = bool(truth) and all(got.get(f, [None, None])[1] == str(v[1]) for f, v in truth.items())
    checks["sorted"] = [r[0] for r in rows[1:]] == sorted(r[0] for r in rows[1:]) and len(rows) > 1
    other = [l for l in tracked_diff() if not l.endswith("inventory.csv")]
    checks["no_other_changes"] = not other
elif task in ("S3", "S4"):
    name = "secret_mask_report" if task == "S3" else "kb_index_deprecated"
    ot = Path(__file__).parent / f"oracle_{task}_test.py"
    dst = wd / "tests" / f"_oracle_{task}_hidden.py"
    dst.write_text(ot.read_text())
    p, f, o = pytest_counts([str(dst.relative_to(wd))], wd)
    total = p + f
    expect = 7 if task == "S3" else 6
    checks["oracle_all_pass"] = (p == expect and f == 0)
    reg = ["tests/test_secret_mask.py", "tests/test_secret_mask_tg_proxy.py"] if task == "S3" else ["tests/test_kb_index_injection_522.py"]
    rp, rf, ro = pytest_counts(reg, wd)
    checks["regression_green"] = rp > 0 and rf == 0
    own = wd / "tests" / f"test_{name}.py"
    ok = False
    if own.exists():
        op, of, oo = pytest_counts([str(own.relative_to(wd))], wd)
        ok = op >= 3 and of == 0
    checks["own_tests_green"] = ok
    dst.unlink()
    result_extra = {"oracle_passed": p, "oracle_failed": f}
elif task == "S5":
    src = Path(__file__).parent / "inputs_master"
    truth = {}
    skipped = []
    for d in sorted(src.iterdir()):
        try:
            j = json.loads((d / "result.json").read_text())
            rt = (d / "run.txt").read_text()
            m = re.search(r"rc=(\d+) seconds=(\d+)", rt)
            mu = j["modelUsage"]
            truth[d.name] = {"output_tokens": sum(v["outputTokens"] for v in mu.values()), "turns": j["num_turns"],
                             "cost_usd": sum(v["costUSD"] for v in mu.values()), "seconds": int(m.group(2)), "rc": int(m.group(1))}
        except Exception:
            skipped.append(d.name)
    try:
        s = json.loads((wd / "summary.json").read_text())
    except Exception:
        s = {}
    def close(a, b):
        return isinstance(a, (int, float)) and abs(a - b) < 1e-6 * max(1, abs(b))
    ok_runs = 0
    for k, v in truth.items():
        g = s.get(k, {})
        if all(close(g.get(f), v[f]) for f in v):
            ok_runs += 1
    checks["per_run_values"] = ok_runs == len(truth) and len(truth) > 0
    tot = {"output_tokens": sum(v["output_tokens"] for v in truth.values()), "turns": sum(v["turns"] for v in truth.values()),
           "cost_usd": sum(v["cost_usd"] for v in truth.values()), "seconds": sum(v["seconds"] for v in truth.values())}
    g = s.get("_total", {})
    checks["total"] = all(close(g.get(f), tot[f]) for f in tot)
    checks["n"] = s.get("n") == len(truth)
    checks["skipped"] = sorted(s.get("_skipped", [])) == sorted(skipped)
    checks["no_extra_run_keys"] = set(k for k in s if not k.startswith("_") and k != "n") == set(truth)
    subprocess_diff = subprocess.run(["diff", "-r", str(wd / "inputs"), str(src)], capture_output=True, text=True)
    checks["inputs_untouched"] = subprocess_diff.returncode == 0
res = {"task": task, "checks": checks, "passed": sum(checks.values()), "total": len(checks), "full": all(checks.values())}
try:
    res.update(result_extra)
except NameError:
    pass
print(json.dumps(res))
