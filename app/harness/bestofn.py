"""Best-of-N (pass@k) — run up to N solution attempts, verify each by running the project's
tests, keep the first that passes. Gated + off by default (#124).

Why this shape: a "solve attempt" here is a whole turn's worth of edits, verified by the REAL
project test suite (exit code, NEVER string-matching 'PASS' — Terminal-Bench-2 gaming). Attempts
are SEQUENTIAL (parallel writers = coordination chaos) in the worker's own single-writer worktree,
with a DEFENSIVE git rollback between them: reset only when the dirt is attempt-generated, else
abort without a destructive reset (no data loss). Early-exit on the first pass.

This module is pure/subprocess only — no LLM, no backend state — so it unit-tests in isolation.
The backend (backend_harness.py) drives the attempt loop and owns history/cost.
"""

import asyncio
import contextlib
import json
import os
import signal
import subprocess
from pathlib import Path

VERIFIER_TIMEOUT = 300          # seconds per test run
VERIFIER_OUTPUT_CAP = 4000      # chars of tail kept for the agent
N_DEFAULT = 3
N_MIN = 2
N_MAX = 5

# npm's default `test` script when none is set — treat as "no real tests".
_NPM_STUB = 'echo "Error: no test specified" && exit 1'


def clamp_n(raw: "str | int | None", default: int = N_DEFAULT) -> int:
    """Clamp the configured N into [N_MIN, N_MAX]. Junk/empty → default."""
    try:
        n = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return max(N_MIN, min(n, N_MAX))


def is_git_repo(cwd: str) -> bool:
    """True if cwd is inside a git worktree (a real toplevel, not a submodule/nested edge)."""
    r = _git(["rev-parse", "--show-toplevel"], cwd)
    return r.returncode == 0 and bool(r.stdout.strip())


def clean_tree(cwd: str) -> bool:
    """True if the worktree has NO uncommitted changes (clean-entry gate). A dirty tree means we
    must NOT run Best-of-N — we'd risk the user's uncommitted work with a rollback."""
    r = _git(["status", "--porcelain"], cwd)
    return r.returncode == 0 and r.stdout.strip() == ""


def base_sha(cwd: str) -> "str | None":
    """The commit the attempts branch from. None if it can't be resolved (→ disable Best-of-N)."""
    r = _git(["rev-parse", "--verify", "HEAD"], cwd)
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None


def resolve_test_cmd(cwd: str) -> "str | None":
    """The verifier command. HARNESS_TEST_CMD wins (verbatim). Else auto-detect a default ONLY for a
    recognized ecosystem WITH detectable tests. Else None → Best-of-N does not activate (fail-safe)."""
    explicit = os.environ.get("HARNESS_TEST_CMD", "").strip()
    if explicit:
        return explicit
    base = Path(cwd)
    if _pyproject_has_pytest(base / "pyproject.toml") or (base / "tests").is_dir() or _find_python_tests(base):
        return "uv run python -m pytest -q"
    if _package_json_has_test(base / "package.json"):
        return "npm test"
    return None


async def run_verifier(cwd: str, test_cmd: str,
                       timeout: int = VERIFIER_TIMEOUT) -> "tuple[str, str]":
    """ASYNC. Run test_cmd in cwd; return (verdict, tail).
      verdict = "pass" (exit 0) | "fail" (other exit OR timeout) | "no_verifier" (126/127/exec-fail).
    A test HANG (timeout) is a FAIL (the attempt's code may loop) — not a broken runner. Only a
    missing/non-executable command (126/127/OSError) is "no_verifier". Judged by EXIT CODE only,
    NEVER by matching 'PASS' in output (verifier-gaming guard)."""
    env = {**os.environ, "CI": "1"}     # non-interactive
    try:
        proc = await asyncio.create_subprocess_shell(
            test_cmd, cwd=cwd, env=env,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,     # own process group → killpg on timeout
        )
    except OSError as e:
        return "no_verifier", f"[verifier could not start] {e}"
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        with contextlib.suppress(Exception):
            await proc.wait()
        return "fail", f"[verifier timed out after {timeout}s — treated as fail]"
    rc = proc.returncode
    tail = (out.decode(errors="replace") if out else "")[-VERIFIER_OUTPUT_CAP:]
    if rc == 0:
        return "pass", tail
    if rc in (126, 127):                # not executable / not found → broken runner
        return "no_verifier", tail
    return "fail", tail


def dirt_is_attempt_only(cwd: str, base: str, touched: "set[str]") -> bool:
    """Defensive-rollback guard (Option 1). True iff it is SAFE to reset — i.e. HEAD still points at
    `base` (no external commit landed) AND every currently-dirty path is one the attempt itself
    wrote. Any unexpected state → False → the backend ABORTS the reset (no data loss).
    `touched` = repo-relative paths the attempt's file tools wrote."""
    head = _git(["rev-parse", "--verify", "HEAD"], cwd)
    if head.returncode != 0 or head.stdout.strip() != base:
        return False                    # HEAD moved (external commit) → a reset would drop it
    r = _git(["status", "--porcelain"], cwd)
    if r.returncode != 0:
        return False                    # can't tell → be safe, don't reset
    for line in r.stdout.splitlines():
        path = line[3:].strip().strip('"')
        if " -> " in path:              # rename "old -> new"
            path = path.split(" -> ", 1)[1]
        if path and path not in touched:
            return False
    return True


def rollback_to_base(cwd: str, base: str) -> bool:
    """Discard the current attempt's edits: reset tracked files to `base` + remove untracked.
    Returns True only if the worktree is verifiably clean-at-base afterwards (both git commands
    succeeded AND HEAD==base AND no dirt) — the caller must NOT proceed on False."""
    r1 = _git(["reset", "--hard", base], cwd)
    r2 = _git(["clean", "-fd"], cwd)
    if r1.returncode != 0 or r2.returncode != 0:
        return False
    head = _git(["rev-parse", "--verify", "HEAD"], cwd)
    return head.returncode == 0 and head.stdout.strip() == base and clean_tree(cwd)


# ── helpers ──

def _git(args: list, cwd: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                              text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        return subprocess.CompletedProcess(args, returncode=1, stdout="", stderr=str(e))


def _find_python_tests(base: Path) -> bool:
    skip = {".venv", "node_modules", ".git", "__pycache__", ".tox"}
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in skip]
        for f in files:
            if (f.startswith("test_") or f.endswith("_test.py")) and f.endswith(".py"):
                return True
    return False


def _pyproject_has_pytest(pyproject: Path) -> bool:
    if not pyproject.is_file():
        return False
    with contextlib.suppress(OSError):
        return "[tool.pytest" in pyproject.read_text(encoding="utf-8", errors="replace")
    return False


def _package_json_has_test(pkg: Path) -> bool:
    if not pkg.is_file():
        return False
    with contextlib.suppress(OSError, ValueError):
        data = json.loads(pkg.read_text(encoding="utf-8", errors="replace"))
        test = (data.get("scripts") or {}).get("test", "")
        return bool(test) and test.strip() != _NPM_STUB
    return False
