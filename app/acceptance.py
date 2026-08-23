"""Platform-run ticket acceptance. The worker does not execute this."""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

from app import tm
from app.db import get_session

PASSED = "passed"
FAILED = "failed"
INCONCLUSIVE = "inconclusive"
SKIPPED = "skipped"

DEFAULT_TIMEOUT_SECONDS = 180.0
_OUTPUT_TAIL = 4000
_SHELL_CONTROL_CHARS = frozenset(";&|<>")
ACCEPTANCE_COMMAND_CONTRACT = (
    "acceptance_command must be one argv command; shell operators are not allowed "
    "unwrapped. Wrap intentional shell semantics explicitly as bash -lc '<chain>'."
)


def _tail(text: str) -> str:
    if len(text) <= _OUTPUT_TAIL:
        return text
    return text[-_OUTPUT_TAIL:]


def _command_tokens(command: str) -> list[str]:
    # Keep quote markers so a literal argument such as ``echo '&&'`` is not
    # mistaken for an unwrapped shell operator. Execution still uses posix
    # splitting below, after this contract check.
    lexer = shlex.shlex(command, posix=False, punctuation_chars=";&|<>")
    lexer.whitespace_split = True
    return list(lexer)


def acceptance_command_error(command: str) -> str | None:
    """Return a contract error for an unsafe unwrapped shell command."""
    try:
        argv = _command_tokens(command)
    except ValueError as exc:
        return f"{ACCEPTANCE_COMMAND_CONTRACT} Invalid quoting: {exc}."
    if len(argv) >= 3 and argv[0] == "bash" and argv[1] == "-lc":
        return None
    for token in argv:
        if token and all(char in _SHELL_CONTROL_CHARS for char in token):
            return ACCEPTANCE_COMMAND_CONTRACT
    return None


def run_command(
    command: str,
    cwd: str,
    *,
    timeout: float | None = None,
) -> dict:
    """Run an operator-registered command. Never reads DONE text.

    passed — process started and exited 0
    failed — process started and exited non-zero
    inconclusive — did not start or did not finish (timeout, missing cwd, bad argv)
    skipped — empty command (caller decides whether to merge)
    """
    budget = DEFAULT_TIMEOUT_SECONDS if timeout is None else timeout
    cmd = (command or "").strip()
    if not cmd:
        return {"status": SKIPPED, "reason": "no_command", "exit_code": None, "output": ""}
    contract_error = acceptance_command_error(cmd)
    if contract_error:
        return {
            "status": INCONCLUSIVE,
            "reason": "invalid_contract",
            "exit_code": None,
            "output": contract_error,
        }
    if not cwd or not Path(cwd).is_dir():
        return {
            "status": INCONCLUSIVE, "reason": "cwd_missing",
            "exit_code": None, "output": "",
        }
    try:
        argv = shlex.split(cmd)
    except ValueError as exc:
        return {
            "status": INCONCLUSIVE, "reason": "bad_command",
            "exit_code": None, "output": str(exc),
        }
    if not argv:
        return {"status": SKIPPED, "reason": "no_command", "exit_code": None, "output": ""}
    try:
        proc = subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            shell=False,
            timeout=budget,
            check=False,
        )
    except FileNotFoundError:
        return {
            "status": INCONCLUSIVE, "reason": "not_found",
            "exit_code": None, "output": argv[0],
        }
    except subprocess.TimeoutExpired as exc:
        out = (exc.stdout or "") + (exc.stderr or "")
        if isinstance(out, bytes):
            out = out.decode("utf-8", "replace")
        return {
            "status": INCONCLUSIVE, "reason": "timeout",
            "exit_code": None, "output": _tail(out),
        }
    except OSError as exc:
        return {
            "status": INCONCLUSIVE, "reason": "os_error",
            "exit_code": None, "output": str(exc),
        }
    output = _tail((proc.stdout or "") + (proc.stderr or ""))
    if proc.returncode == 0:
        return {"status": PASSED, "reason": "", "exit_code": 0, "output": output}
    return {
        "status": FAILED, "reason": "exit_nonzero",
        "exit_code": proc.returncode, "output": output,
    }


def command_for_session(session_id: str) -> str:
    row = get_session(session_id)
    if not row:
        return ""
    ref = str(row.get("task_id") or "").strip()
    scope = (row.get("scope") or "").rstrip("/")
    if not ref or not scope:
        return ""
    try:
        identity = tm.resolve_scoped_task_identity(scope, ref)
    except ValueError:
        return ""
    with tm._conn() as conn:
        task = tm.get_task_by_id(conn, identity["id"])
    if not task:
        return ""
    return str(task.get("acceptance_command") or "").strip()


def evaluate_for_merge(*, session_id: str, worktree_path: str) -> dict:
    command = command_for_session(session_id)
    result = run_command(command, worktree_path)
    result["command"] = command
    return result
