"""Platform-run ticket acceptance. The worker does not execute this."""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

from app.db import get_session

PASSED = "passed"
FAILED = "failed"
INCONCLUSIVE = "inconclusive"
SKIPPED = "skipped"

DEFAULT_TIMEOUT_SECONDS = 180.0
_OUTPUT_TAIL = 4000
FIX_ACCEPTANCE_THEN_RETRY = "FIX_ACCEPTANCE_THEN_RETRY"
_SHELL_EXECUTABLES = {
    "bash", "sh", "/bin/bash", "/bin/sh", "/usr/bin/bash", "/usr/bin/sh",
}


class AcceptanceCommandError(ValueError):
    """An acceptance command cannot honor the runner's literal-argv contract."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


def _apparent_shell_syntax(command: str) -> str:
    quote = ""
    index = 0
    while index < len(command):
        char = command[index]

        if quote == "'":
            if char == "'":
                quote = ""
            index += 1
            continue

        if char == "\\":
            index += 2
            continue
        if char in {"'", '"'}:
            if quote == char:
                quote = ""
            elif not quote:
                quote = char
            index += 1
            continue

        if char == "`":
            return "backtick command substitution"
        if char == "$" and index + 1 < len(command):
            following = command[index + 1]
            if following == "(":
                return "command substitution '$('"
            if following == "{":
                return "variable substitution '${...}'"
            if following in {"'", '"'}:
                return "shell-specific dollar quoting"
            if following.isalnum() or following in "_@*#?$!-":
                return "variable substitution"

        if not quote:
            pair = command[index:index + 2]
            if pair in {"&&", "||"}:
                return f"shell operator '{pair}'"
            if char in "|;&":
                return f"shell operator '{char}'"
            if char in "<>":
                return f"shell redirection '{char}'"
            if char in "\r\n":
                return "shell command separator (newline)"

        index += 1
    return ""


def parse_acceptance_command(command: str) -> list[str]:
    """Return the exact argv executed by the shell=False acceptance runner."""
    cmd = (command or "").strip()
    if not cmd:
        return []
    try:
        argv = shlex.split(cmd)
    except ValueError as exc:
        raise AcceptanceCommandError(
            "malformed_quoting",
            "acceptance_command has malformed quoting and cannot be parsed as argv: "
            f"{exc}. Repair the quoting before retrying.",
        ) from exc
    if not argv:
        raise AcceptanceCommandError(
            "empty_argv",
            "acceptance_command produces no executable argv; use an executable command "
            "or clear the acceptance command explicitly.",
        )
    if not argv[0]:
        raise AcceptanceCommandError(
            "empty_executable",
            "acceptance_command produces an empty executable; use an executable command "
            "or clear the acceptance command explicitly.",
        )

    if argv[0] in _SHELL_EXECUTABLES:
        if len(argv) != 3 or argv[1] not in {"-c", "-lc"} or not argv[2].strip():
            raise AcceptanceCommandError(
                "invalid_shell_wrapper",
                "acceptance_command may opt in to shell execution only as exactly "
                "bash/sh -c '<script>' or bash/sh -lc '<script>'.",
            )
        return argv

    shell_syntax = _apparent_shell_syntax(cmd)
    if shell_syntax:
        raise AcceptanceCommandError(
            "shell_syntax_requires_explicit_shell",
            "acceptance_command violates the literal-argv contract: "
            f"{shell_syntax} would be passed literally because the runner uses "
            "shell=False. Rewrite it as one executable argv, or opt in visibly with "
            "bash -lc '<script>'.",
        )
    return argv


def _tail(text: str) -> str:
    if len(text) <= _OUTPUT_TAIL:
        return text
    return text[-_OUTPUT_TAIL:]


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
    try:
        argv = parse_acceptance_command(cmd)
    except AcceptanceCommandError as exc:
        return {
            "status": INCONCLUSIVE,
            "reason": "invalid_acceptance_command",
            "validation_error": exc.reason,
            "guidance": FIX_ACCEPTANCE_THEN_RETRY,
            "exit_code": None,
            "output": str(exc),
        }
    if not cwd or not Path(cwd).is_dir():
        return {
            "status": INCONCLUSIVE, "reason": "cwd_missing",
            "exit_code": None, "output": "",
        }
    try:
        proc = subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=budget,
            check=False,
            shell=False,
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
    from app import tm

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
