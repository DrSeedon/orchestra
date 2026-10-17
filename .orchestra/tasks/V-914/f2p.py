#!/usr/bin/env python3
"""V-914 step 1: fail-to-pass index over main commits that touch app/*.py and tests/test_*.py.

usage: f2p.py <list.txt> <out.jsonl> [jobs=4]
Resumable: commits already in out.jsonl are skipped. Run outside the platform cgroup (ssh kesha@localhost).
"""
import json, os, re, shutil, subprocess, sys, time, tempfile
from concurrent.futures import ThreadPoolExecutor

REPO = "/home/kesha/orchestra/.git"
VENV_PY = "/tmp/v914/venv/bin/python"
BASE = "/tmp/v914/wt"
TIMEOUT = int(os.environ.get("F2P_TIMEOUT", "300"))
GIT_INIT = os.environ.get("F2P_GIT") == "1"  # rerun mode: tests that call git need a repository
MIN_AVAIL_KB = 3_500_000  # keep >3.5 GB free for Kesha's bot and the platform


def sh(cmd, **kw):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, **kw)


def wait_mem():
    while True:
        for l in open("/proc/meminfo"):
            if l.startswith("MemAvailable"):
                if int(l.split()[1]) > MIN_AVAIL_KB:
                    return
        time.sleep(10)


def extract(h, dest, paths=None):
    p = " ".join(paths) if paths else "-- . ':!.orchestra/tasks' ':!artifacts'"
    r = sh(f"git --git-dir={REPO} archive {h} {p} | tar -x -C {dest}")
    return r.returncode == 0


def run_tests(d, tests):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    cmd = f"nice -n 15 timeout {TIMEOUT} {VENV_PY} -m pytest {' '.join(tests)} -q -x -p no:cacheprovider --no-header --tb=line -p no:randomly"
    t = time.time()
    r = sh(cmd, cwd=d, env=env)
    out = (r.stdout or "") + (r.stderr or "")
    return r.returncode, out, time.time() - t


def red_reason(rc, out):
    if rc == 124:
        return "timeout"
    lines = [l for l in out.splitlines() if l.strip()]
    for l in lines:
        if re.search(r"(Error|Exception|assert|Failed|FAILED)", l) and not l.startswith("="):
            return l.strip()[:200]
    return (lines[-1] if lines else "")[:200]


def added_stats(h, tests):
    d = sh(f"git --git-dir={REPO} show {h} --format= -U0 -- {' '.join(tests)}").stdout
    added = "\n".join(l[1:] for l in d.splitlines() if l.startswith("+") and not l.startswith("+++"))
    priv = {m for m in re.findall(r"(?<![\w.])_[A-Za-z]\w*", added)} | {m for m in re.findall(r"\._[A-Za-z]\w*", added)}
    priv = {p.lstrip(".") for p in priv}
    mocks = len(re.findall(r"monkeypatch|\bpatch\(|\bMock\(|MagicMock|AsyncMock", added))
    return sorted(priv), mocks


def one(line):
    h, _, subj = line.strip().partition(" ")
    m = re.match(r"(#?V?-?\d+)", subj)
    task = m.group(1) if m else ""
    rec = {"commit": h[:8], "parent": "", "task": task, "subject": subj[:120], "test_files": [], "f2p": False,
           "red_reason": "", "priv_names": 0, "mock_count": 0, "seconds": 0, "new_rc": None, "old_rc": None}
    t0 = time.time()
    wait_mem()
    d = tempfile.mkdtemp(prefix=h[:8] + "_", dir=BASE)
    try:
        rec["parent"] = sh(f"git --git-dir={REPO} rev-parse {h}~1").stdout.strip()[:8]
        files = sh(f"git --git-dir={REPO} show --name-only --format= {h}").stdout.split()
        tests = [f for f in files if re.match(r"tests/test_.*\.py$", f)]
        rec["test_files"] = tests
        priv, mocks = added_stats(h, tests)
        rec["priv_names"], rec["mock_count"] = len(priv), mocks
        if not extract(h, d):
            rec["red_reason"] = "extract_fail"; return rec
        if GIT_INIT:
            sh("git init -q && git add -A && git -c user.name=x -c user.email=x@x commit -qm x && git branch -M main", cwd=d)
        existing = [t for t in tests if os.path.exists(os.path.join(d, t))]
        if not existing:
            rec["red_reason"] = "tests_deleted"; return rec
        rc, out, s1 = run_tests(d, existing)
        rec["new_rc"] = rc
        if rc != 0:
            rec["red_reason"] = "new_" + ("timeout" if rc == 124 else "red:" + red_reason(rc, out))
            return rec
        # parent state of app/scripts/pyproject; tests stay at commit state
        for sub in ("app", "scripts"):
            shutil.rmtree(os.path.join(d, sub), ignore_errors=True)
        os.remove(os.path.join(d, "pyproject.toml")) if os.path.exists(os.path.join(d, "pyproject.toml")) else None
        extract(h + "~1", d, ["app", "scripts", "pyproject.toml"])
        rc2, out2, s2 = run_tests(d, existing)
        rec["old_rc"] = rc2
        if rc2 == 0:
            rec["red_reason"] = "green_on_parent"
        elif rc2 == 124:
            rec["red_reason"] = "old_timeout"
        else:
            rec["f2p"] = True
            rec["red_reason"] = red_reason(rc2, out2)
        return rec
    except Exception as e:
        rec["red_reason"] = "driver_error:" + repr(e)[:150]
        return rec
    finally:
        rec["seconds"] = round(time.time() - t0, 1)
        shutil.rmtree(d, ignore_errors=True)  # own temp dir under /tmp/v914/wt


def main():
    lst, out = sys.argv[1], sys.argv[2]
    jobs = int(sys.argv[3]) if len(sys.argv) > 3 else 4
    os.makedirs(BASE, exist_ok=True)
    done = set()
    if os.path.exists(out):
        done = {json.loads(l)["commit"] for l in open(out) if l.strip()}
    todo = [l for l in open(lst) if l.strip() and l[:8] not in done]
    print(f"todo {len(todo)} done {len(done)}", flush=True)
    with ThreadPoolExecutor(jobs) as ex, open(out, "a") as f:
        for rec in ex.map(one, todo):
            f.write(json.dumps(rec, ensure_ascii=False) + "\n"); f.flush()


if __name__ == "__main__":
    main()
