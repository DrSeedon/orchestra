"""Merge-time test subset. Not the full suite.

Full pytest is ~728s (grok-51, 2026-08-14) and takes the one-per-project
test_lock — four workers would queue. This gate never launches the full suite
and never passes pytest -x (CI with -x hid a red main for a week).

Subset: tests/test_<stem>.py for each changed app/*.py, plus
tests/test_routes_surface.py when app/routes/**, app/main.py or the snapshot
change. Docs-only / no git diff → skipped (fixtures without git stay skipped
so #240 oracles keep working). Unmapped app modules are a hole we accept —
missing tests ≠ landing a red test that already exists.

Cap: more than MAX_TEST_FILES mapped → inconclusive, not «run everything».
Timeout → inconclusive. Does not close bash: the worker can rewrite this file.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from app.acceptance import FAILED, INCONCLUSIVE, PASSED, SKIPPED

MAX_TEST_FILES = 12
DEFAULT_TIMEOUT_SECONDS = 180.0
ROUTE_TEST = "tests/test_routes_surface.py"
_ROUTE_EXACT = frozenset({
    "app/main.py",
    "tests/route_surface_snapshot.json",
    "tests/test_routes_surface.py",
})


def _git(cwd: Path, *args: str) -> str | None:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout


def changed_paths(worktree: str) -> list[str] | None:
    wt = Path(worktree)
    if not wt.is_dir():
        return None
    inside = _git(wt, "rev-parse", "--is-inside-work-tree")
    if inside is None or inside.strip() != "true":
        return None
    base = None
    for ref in ("main", "master"):
        if _git(wt, "rev-parse", "--verify", ref) is not None:
            base = ref
            break
    if not base:
        return None
    named = _git(wt, "diff", "--name-only", f"{base}...HEAD")
    if named is None:
        return None
    paths = [line.strip().replace("\\", "/") for line in named.splitlines() if line.strip()]
    extra = _git(wt, "ls-files", "--others", "--exclude-standard")
    if extra:
        paths.extend(
            line.strip().replace("\\", "/")
            for line in extra.splitlines() if line.strip()
        )
    return sorted(set(paths))


def select_tests(changed: list[str], *, worktree: str) -> list[str]:
    wt = Path(worktree)
    selected: set[str] = set()
    for raw in changed:
        path = raw.replace("\\", "/").lstrip("./")
        if path.startswith("app/routes/") or path in _ROUTE_EXACT:
            if (wt / ROUTE_TEST).is_file():
                selected.add(ROUTE_TEST)
        if path.startswith("app/") and path.endswith(".py"):
            cand = f"tests/test_{Path(path).stem}.py"
            if (wt / cand).is_file():
                selected.add(cand)
        if path.startswith("tests/test_") and path.endswith(".py") and (wt / path).is_file():
            selected.add(path)
    return sorted(selected)


def pytest_argv(tests: list[str]) -> list[str]:
    # No -x / --exitfirst / --maxfail=1: one red must not hide the rest.
    return [sys.executable, "-m", "pytest", "-q", *tests]


def run_pytest(worktree: str, tests: list[str], *, timeout: float | None = None) -> dict:
    budget = DEFAULT_TIMEOUT_SECONDS if timeout is None else timeout
    argv = pytest_argv(tests)
    env = os.environ.copy()
    root = str(Path(worktree).resolve())
    prior = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = root if not prior else f"{root}{os.pathsep}{prior}"
    try:
        proc = subprocess.run(
            argv,
            cwd=worktree,
            env=env,
            capture_output=True,
            text=True,
            timeout=budget,
            check=False,
        )
    except FileNotFoundError:
        return {
            "status": INCONCLUSIVE, "reason": "not_found",
            "exit_code": None, "output": argv[0], "tests": tests,
        }
    except subprocess.TimeoutExpired as exc:
        out = (exc.stdout or "") + (exc.stderr or "")
        if isinstance(out, bytes):
            out = out.decode("utf-8", "replace")
        return {
            "status": INCONCLUSIVE, "reason": "timeout",
            "exit_code": None, "output": out[-4000:], "tests": tests,
        }
    except OSError as exc:
        return {
            "status": INCONCLUSIVE, "reason": "os_error",
            "exit_code": None, "output": str(exc), "tests": tests,
        }
    output = ((proc.stdout or "") + (proc.stderr or ""))[-4000:]
    if proc.returncode == 0:
        return {
            "status": PASSED, "reason": "",
            "exit_code": 0, "output": output, "tests": tests,
        }
    return {
        "status": FAILED, "reason": "exit_nonzero",
        "exit_code": proc.returncode, "output": output, "tests": tests,
    }


def evaluate_test_gate(worktree: str) -> dict:
    changed = changed_paths(worktree)
    if changed is None:
        return {
            "status": SKIPPED, "reason": "no_diff",
            "exit_code": None, "output": "", "tests": [],
        }
    tests = select_tests(changed, worktree=worktree)
    if not tests:
        return {
            "status": SKIPPED, "reason": "no_mapped_tests",
            "exit_code": None, "output": "", "tests": [],
        }
    if len(tests) > MAX_TEST_FILES:
        return {
            "status": INCONCLUSIVE, "reason": "subset_too_large",
            "exit_code": None,
            "output": f"{len(tests)} mapped files > {MAX_TEST_FILES}",
            "tests": tests,
        }
    return run_pytest(worktree, tests)
