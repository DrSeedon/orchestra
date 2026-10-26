"""Test check of one finished workspace.

A copy of the workspace is made. The original test files and pytest.ini of the task repo are put back,
so the agent's edits to existing tests do not count. The held-out feature test is added as
heldout_tests/test_heldout_<ID>.py. Then one pytest run executes the original test modules and the
held-out module. "all_pass" = pytest exit code 0, at least one test from each group ran, none failed.

Usage: python score.py TASK_ID WORKSPACE
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

from common import TASKS, clean_env, load_task

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import judge  # noqa: E402

IGNORE = shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache")
PYTEST_CONFIGS = ("pytest.ini",)
TIMEOUT_S = 600


def original_test_files(repo):
    out = []
    for dirpath, dirs, names in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".pytest_cache", ".git")]
        for fn in names:
            rel = os.path.relpath(os.path.join(dirpath, fn), repo).replace("\\", "/")
            if judge.is_test_path(rel):
                out.append(rel)
    return sorted(out)


def score(task_id, ws):
    task_dir = os.path.join(TASKS, task_id)
    repo = os.path.join(task_dir, "repo")
    tmp = tempfile.mkdtemp(prefix="score_")
    copy = os.path.join(tmp, "w")
    try:
        shutil.copytree(ws, copy, ignore=IGNORE)
        tests = original_test_files(repo)
        for rel in tests + [c for c in PYTEST_CONFIGS if os.path.exists(os.path.join(repo, c))]:
            dst = os.path.join(copy, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(os.path.join(repo, rel), dst)
        held_name = "test_heldout_%s.py" % task_id
        os.makedirs(os.path.join(copy, "heldout_tests"), exist_ok=True)
        shutil.copyfile(os.path.join(task_dir, "heldout", held_name),
                        os.path.join(copy, "heldout_tests", held_name))
        modules = [t for t in tests if t.rsplit("/", 1)[-1] not in ("conftest.py", "__init__.py")]
        xml = os.path.join(tmp, "junit.xml")
        cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-o", "junit_family=xunit2",
               "--junitxml", xml, *modules, "heldout_tests/" + held_name]
        env = clean_env({"PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"})
        try:
            r = subprocess.run(cmd, cwd=copy, env=env, capture_output=True, encoding="utf-8",
                               errors="replace", timeout=TIMEOUT_S)
            code, out = r.returncode, (r.stdout + r.stderr)
        except subprocess.TimeoutExpired:
            code, out = "timeout", "timeout after %ds" % TIMEOUT_S
        groups = {"existing": [0, 0], "feature": [0, 0]}  # [ran, failed]
        if os.path.exists(xml):
            for tc in ET.parse(xml).getroot().iter("testcase"):
                g = "feature" if tc.get("classname", "").startswith("heldout_tests") else "existing"
                if tc.find("skipped") is not None:
                    continue
                groups[g][0] += 1
                if tc.find("failure") is not None or tc.find("error") is not None:
                    groups[g][1] += 1
        ex_ok = groups["existing"][0] > 0 and groups["existing"][1] == 0
        fe_ok = groups["feature"][0] > 0 and groups["feature"][1] == 0
        return {
            "existing_pass": ex_ok, "feature_pass": fe_ok, "all_pass": code == 0 and ex_ok and fe_ok,
            "pytest_exit": code, "existing_ran": groups["existing"][0], "existing_failed": groups["existing"][1],
            "feature_ran": groups["feature"][0], "feature_failed": groups["feature"][1],
            "pytest_tail": out[-3000:],
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    res = score(sys.argv[1], sys.argv[2])
    tail = res.pop("pytest_tail")
    print(json.dumps(res, indent=1))
    if not res["all_pass"]:
        print(tail)
