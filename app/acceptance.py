"""Platform-run ticket acceptance. The worker does not execute this."""

from __future__ import annotations

import hashlib
import json
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
_PYTEST_CONFIG_NAMES = {
    "pytest.toml", ".pytest.toml", "pytest.ini", ".pytest.ini",
    "pyproject.toml", "tox.ini", "setup.cfg",
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


def _git(worktree: str, *args: str, timeout: float = 30.0) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=worktree, capture_output=True, text=True,
        timeout=timeout, check=False,
    )
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or f"exit {proc.returncode}"
        raise ValueError(f"git {' '.join(args)} failed: {detail}")
    return proc.stdout


def _tree_entries(worktree: str, ref: str, path: str, *, recursive: bool) -> list[dict]:
    args = ["ls-tree"]
    if recursive:
        args.append("-r")
    args.extend(("-z", ref, "--", path))
    output = _git(worktree, *args)
    entries = []
    for raw in output.split("\0"):
        if not raw:
            continue
        metadata, relative = raw.split("\t", 1)
        mode, kind, blob = metadata.split(" ", 2)
        if kind == "blob":
            entries.append({"path": relative, "mode": mode, "blob": blob})
    return entries


def pin_task_oracle(
    *,
    task_id: str,
    revision: int,
    command: str,
    manifest_paths: list[str],
    updated_by: dict,
    target_ref: str,
    target_sha: str,
    worktree_path: str,
) -> dict:
    from app import tm

    parse_acceptance_command(command)
    manifest_roots = tm._normalize_acceptance_manifest(manifest_paths)
    if "tests" not in manifest_roots:
        raise ValueError("acceptance manifest must include tests")
    if not any(path in _PYTEST_CONFIG_NAMES for path in manifest_roots):
        raise ValueError("acceptance manifest must include pytest config")
    resolved = _git(worktree_path, "rev-parse", "--verify", f"{target_sha}^{{commit}}")
    resolved_sha = resolved.strip()
    if resolved_sha != target_sha:
        raise ValueError("target SHA did not resolve exactly")

    expanded: dict[str, dict] = {}
    for path in manifest_roots:
        entries = _tree_entries(
            worktree_path, target_sha, path, recursive=path == "tests",
        )
        if not entries:
            raise ValueError(f"acceptance manifest path missing from target: {path}")
        for entry in entries:
            expanded[entry["path"]] = entry
    manifest = [expanded[path] for path in sorted(expanded)]
    contract = {
        "source": "task",
        "task_id": str(task_id),
        "revision": int(revision),
        "ref": target_sha,
        "target_ref": target_ref,
        "command": command.strip(),
        "manifest": manifest,
    }
    digest = hashlib.sha256(
        json.dumps(contract, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {**contract, "hash": digest, "updated_by": dict(updated_by)}


def _candidate_changed_paths(worktree: str, target_sha: str) -> set[str]:
    changed: set[str] = set()
    for args in (
        ("diff", "--name-only", f"{target_sha}...HEAD"),
        ("diff", "--name-only", "HEAD"),
        ("diff", "--cached", "--name-only"),
        ("ls-files", "--others", "--exclude-standard"),
    ):
        changed.update(
            line.strip().replace("\\", "/")
            for line in _git(worktree, *args).splitlines()
            if line.strip()
        )
    return changed


def _verify_pinned_inputs(oracle: dict, worktree: str) -> list[str]:
    expected = {
        entry["path"]: entry for entry in oracle.get("manifest", [])
        if isinstance(entry, dict) and entry.get("path")
    }
    mutated: set[str] = set()
    for path, entry in expected.items():
        head_entries = _tree_entries(worktree, "HEAD", path, recursive=False)
        if len(head_entries) != 1 or any(
            head_entries[0].get(key) != entry.get(key) for key in ("mode", "blob")
        ):
            mutated.add(path)
            continue
        local = Path(worktree) / path
        if not local.exists() or not local.is_file():
            mutated.add(path)
            continue
        local_blob = _git(
            worktree, "hash-object", "--no-filters", "--", path,
        ).strip()
        local_mode = "100755" if local.stat().st_mode & 0o111 else "100644"
        if local_blob != entry["blob"] or local_mode != entry["mode"]:
            mutated.add(path)

    expected_tests = {path for path in expected if path == "tests" or path.startswith("tests/")}
    candidate_tests = {
        entry["path"] for entry in _tree_entries(worktree, "HEAD", "tests", recursive=True)
    }
    candidate_tests.update(
        line.strip().replace("\\", "/")
        for line in _git(
            worktree, "ls-files", "--others", "--exclude-standard", "--", "tests",
        ).splitlines()
        if line.strip()
    )
    mutated.update(expected_tests ^ candidate_tests)

    for path in _candidate_changed_paths(worktree, str(oracle.get("ref") or "")):
        name = Path(path).name
        if (name == "conftest.py" or name in _PYTEST_CONFIG_NAMES) and path not in expected:
            mutated.add(path)
    return sorted(mutated)


def evaluate_pinned_oracle(
    oracle: dict,
    worktree_path: str,
    *,
    timeout: float | None = None,
) -> dict:
    if not isinstance(oracle, dict) or not oracle.get("command"):
        return {
            "status": FAILED, "reason": "oracle_missing", "exit_code": None,
            "output": "", "command": "",
        }
    try:
        mutated = _verify_pinned_inputs(oracle, worktree_path)
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return {
            "status": INCONCLUSIVE, "reason": "oracle_verification_failed",
            "exit_code": None, "output": str(exc),
            "command": str(oracle.get("command") or ""),
        }
    if mutated:
        return {
            "status": FAILED, "reason": "oracle_input_mutated", "exit_code": None,
            "output": ", ".join(mutated), "mutated_inputs": mutated,
            "command": str(oracle["command"]),
        }
    result = run_command(str(oracle["command"]), worktree_path, timeout=timeout)
    if result["status"] == SKIPPED:
        result = {**result, "status": FAILED, "reason": "oracle_skipped"}
    result["command"] = str(oracle["command"])
    return result


def command_for_session(session_id: str) -> str:
    task = task_oracle_for_session(session_id)
    return str(task.get("command") or "")


def task_oracle_for_session(session_id: str) -> dict:
    from app import tm

    row = get_session(session_id)
    if not row:
        return {}
    ref = str(row.get("task_id") or "").strip()
    scope = (row.get("scope") or "").rstrip("/")
    if not ref or not scope:
        return {}
    try:
        identity = tm.resolve_scoped_task_identity(scope, ref)
    except ValueError:
        return {}
    with tm._conn() as conn:
        task = tm.get_task_by_id(conn, identity["id"])
    if not task:
        return {}
    oracle = tm.parse_acceptance_oracle(task.get("acceptance_oracle_json"))
    return {
        "task_id": ref,
        "command": str(task.get("acceptance_command") or "").strip(),
        "required": bool(oracle.get("required")),
        "revision": int(oracle.get("revision") or 0),
        "manifest_paths": list(oracle.get("manifest_paths") or []),
        "updated_by": dict(oracle.get("updated_by") or {}),
    }


def evaluate_for_merge(*, session_id: str, worktree_path: str) -> dict:
    command = command_for_session(session_id)
    result = run_command(command, worktree_path)
    result["command"] = command
    return result
