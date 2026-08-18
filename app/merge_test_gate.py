"""Merge-time test subset. Not the full suite.

Full pytest is ~728s (grok-51, 2026-08-14) and takes the one-per-project
test_lock — four workers would queue. This gate never launches the full suite
and never passes pytest -x (CI with -x hid a red main for a week).

Subset: tests/test_<stem>.py for each changed app/*.py, plus
tests/test_routes_surface.py when app/routes/**, app/main.py or the snapshot
change. Docs-only / no git diff → skipped (fixtures without git stay skipped
so #240 oracles keep working). Unmapped app modules are a hole we accept —
missing tests ≠ landing a red test that already exists.

Tests marked `live_probe` are deselected: they spend a real provider turn, so they go red
on quota and provider outages instead of on the diff. They stay runnable by hand
(`pytest -m live_probe tests/`) and their inventory is pinned by a test.

Mapped files are run in sequential batches of MAX_TEST_FILES. The batches share one
wall-clock budget and never turn into a full-suite invocation.
Timeout → inconclusive. Does not close bash: the worker can rewrite this file.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from app.acceptance import FAILED, INCONCLUSIVE, PASSED, SKIPPED

MAX_TEST_FILES = 12
MAX_BATCH_TESTS = 6
DEFAULT_TIMEOUT_SECONDS = 180.0
_BATCH_DIAGNOSTIC_LIMIT = 4000
ROUTE_TEST = "tests/test_routes_surface.py"
_ROUTE_EXACT = frozenset({
    "app/main.py",
    "tests/route_surface_snapshot.json",
    "tests/test_routes_surface.py",
})


def _normalize_output(output: str | bytes | None) -> str:
    if output is None:
        return ""
    if isinstance(output, bytes):
        return output.decode("utf-8", "replace")
    return output


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


LIVE_PROBE_MARKER = "live_probe"
NO_TESTS_EXIT_CODE = 5  # pytest EXIT_NOTESTSCOLLECTED


def pytest_argv(tests: list[str]) -> list[str]:
    # No -x / --exitfirst / --maxfail=1: one red must not hide the rest.
    # `-m "not live_probe"` снимает с гейта пробы, тратящие настоящий ход провайдера: они
    # краснеют от квоты и недоступности, а не от диффа, и блокируют чужие мержи (18.08:
    # codex-проба стояла красной по rate_limit в самом main). Умолчание безопасное — новая
    # проба БЕЗ маркера гоняется гейтом и падает громко; исчезнуть незаметно она не может.
    return [
        sys.executable, "-m", "pytest", "-q",
        "-m", f"not {LIVE_PROBE_MARKER}",
        *tests,
    ]


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
        out = _normalize_output(exc.stdout) + _normalize_output(exc.stderr)
        return {
            "status": INCONCLUSIVE, "reason": "timeout",
            "exit_code": None, "output": out[-4000:], "tests": tests,
        }
    except OSError as exc:
        return {
            "status": INCONCLUSIVE, "reason": "os_error",
            "exit_code": None, "output": str(exc), "tests": tests,
        }
    output = (_normalize_output(proc.stdout) + _normalize_output(proc.stderr))[-4000:]
    if proc.returncode == 0:
        return {
            "status": PASSED, "reason": "",
            "exit_code": 0, "output": output, "tests": tests,
        }
    if proc.returncode == NO_TESTS_EXIT_CODE:
        # Файл выбран, но после `-m "not live_probe"` в нём не осталось ни одного теста —
        # то есть весь файл состоит из живых проб. Это не провал, но и не «проверено»:
        # FAILED врал бы про красноту, PASSED — про пустой прогон.
        return {
            "status": SKIPPED, "reason": "no_tests_after_deselect",
            "exit_code": proc.returncode, "output": output, "tests": tests,
        }
    return {
        "status": FAILED, "reason": "exit_nonzero",
        "exit_code": proc.returncode, "output": output, "tests": tests,
    }


def _compact_output(text: str, limit: int) -> str:
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    marker = "\n…\n"
    if limit <= len(marker):
        return text[:limit]
    head = (limit - len(marker)) // 2
    tail = limit - len(marker) - head
    return f"{text[:head]}{marker}{text[-tail:]}"


def _ordered_batches(tests: list[str]) -> list[list[str]]:
    if len(tests) <= MAX_TEST_FILES:
        return [tests]
    batch_count = (len(tests) + MAX_BATCH_TESTS - 1) // MAX_BATCH_TESTS
    base_size, remainder = divmod(len(tests), batch_count)
    batches = []
    cursor = 0
    for index in range(batch_count):
        size = base_size + (index < remainder)
        batches.append(tests[cursor:cursor + size])
        cursor += size
    return batches


def _batch_result(worktree: str, batches: list[list[str]]) -> dict:
    """Run every mapped batch under one deadline and combine its evidence."""
    deadline = time.monotonic() + DEFAULT_TIMEOUT_SECONDS
    batches_left = len(batches)
    results: list[dict] = []
    for batch in batches:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            result = {
                "status": INCONCLUSIVE,
                "reason": "timeout",
                "exit_code": None,
                "output": "total timeout budget exhausted before this batch",
                "tests": batch,
            }
        else:
            result = run_pytest(worktree, batch, timeout=remaining / batches_left)
        batches_left -= 1
        results.append(result)

    failed = [result for result in results if result["status"] == FAILED]
    inconclusive = [
        result for result in results if result["status"] == INCONCLUSIVE
    ]
    if failed:
        status = FAILED
        reason = "batch_failed"
        exit_code = failed[0].get("exit_code")
    elif inconclusive:
        status = INCONCLUSIVE
        reason = "batch_inconclusive"
        exit_code = None
    else:
        status = PASSED
        reason = ""
        exit_code = 0

    sections = []
    for index, result in enumerate(results, start=1):
        lines = [
            f"batch {index}/{len(results)} "
            f"status={result['status']} tests={','.join(result['tests'])}"
        ]
        if result.get("reason"):
            lines.append(f"reason={result['reason']}")
        section_limit = max(
            1,
            (_BATCH_DIAGNOSTIC_LIMIT - max(0, len(results) - 1)) // len(results),
        )
        section = "\n".join(lines)
        output = result.get("output") or ""
        budget = section_limit - len(section) - 1
        if output and budget > 0:
            section = f"{section}\n{_compact_output(output, budget)}"
        sections.append(section[:section_limit])
    return {
        "status": status,
        "reason": reason,
        "exit_code": exit_code,
        "output": "\n".join(sections),
        "tests": list(sum(batches, [])),
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
        batches = _ordered_batches(tests)
        return _batch_result(worktree, batches)
    return run_pytest(worktree, tests)
