"""Shared pre-execution policy for expensive recursive shell commands."""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import sys
from pathlib import Path

MAX_SHORT_SLEEP_SECONDS = 5

_RULES = {
    "long_sleep": (
        "Long shell sleeps are blocked (maximum 5 seconds). Use bg_create(type='run') "
        "for a process, bg_create(type='file') for a file, or "
        "bg_create(type='command') for a condition; the job will wake the session."
    ),
    "recursive_find": (
        "Recursive find searches are blocked. Use `rg --files --hidden --no-ignore` "
        "for paths or `rg` for file contents; keep the search scoped."
    ),
    "recursive_grep": (
        "Recursive grep (-r/-R) is blocked. Use `rg` for file contents or "
        "`rg --files --hidden --no-ignore` for paths."
    ),
    "shell_policy_unavailable": (
        "The shell command could not be checked safely. Submit it again after the "
        "session shell policy is available."
    ),
}

# Keep find operations whose meaning cannot be reproduced by an rg path/content search.
_FIND_SEMANTIC_OPTIONS = {
    "-newer", "-anewer", "-cnewer", "-mtime", "-mmin", "-atime", "-amin",
    "-ctime", "-cmin", "-delete", "-exec", "-execdir", "-ok", "-okdir",
    "-printf", "-fprintf", "-ls", "-prune", "-maxdepth", "-mindepth", "-depth",
    "-follow", "-L", "-H", "-P", "-perm", "-user", "-group", "-uid", "-gid",
    "-size", "-empty", "-links", "-inum", "-fstype", "-samefile", "-mount", "-xdev",
}
_SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
_TRANSPARENT = {"time", "nohup", "exec", "do", "then", "else"}
CODEX_POLICY_WRAPPED_COMMANDS = (
    "sleep", "find", "grep", "egrep", "fgrep", "timeout", "env", "nice",
)


def violation_message(rule: str) -> str:
    return f"POLICY VIOLATION [{rule}]: {_RULES[rule]}"


def _rg_available() -> bool:
    return shutil.which("rg") is not None


def classify_shell_command(command: str) -> str | None:
    """Return the one policy rule violated, or None for permitted commands."""
    if not isinstance(command, str) or not command.strip():
        return None
    command = _without_heredoc_bodies(command)
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()\n")
        lexer.whitespace_split = True
        lexer.commenters = "#"
        tokens = list(lexer)
    except ValueError:
        # A malformed command that visibly contains one of the guarded forms must not
        # bypass the pre-execution check because quoting failed to parse.
        sleep_match = re.search(r"\bsleep\s+([^;&|\n]*)", command)
        if sleep_match:
            try:
                duration_args = shlex.split(sleep_match.group(1))
            except ValueError:
                duration_args = []
            duration = _sleep_duration(duration_args)
            if duration is None or duration > MAX_SHORT_SLEEP_SECONDS:
                return "long_sleep"
        if _rg_available() and re.search(r"\bfind\b[^\n;&|]*", command) and not any(
            option in command for option in _FIND_SEMANTIC_OPTIONS
        ):
            return "recursive_find"
        if _rg_available() and re.search(
            r"\bgrep\b[^\n;&|]*\s-(?:[^\s]*[rR]|[rR])(?:\s|$)", command,
        ):
            return "recursive_grep"
        return None

    segments: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token in {";", "&&", "||", "|", "&", "(", ")", "\n"}:
            if current:
                segments.append(current)
                current = []
        else:
            current.append(token)
    if current:
        segments.append(current)

    for segment in segments:
        rule = _classify_segment(segment, depth=0)
        if rule:
            return rule
    return None


def _without_heredoc_bodies(command: str) -> str:
    pending: list[tuple[str, bool]] = []
    output: list[str] = []
    declaration = re.compile(
        r"(?<!<)<<(-?)\s*(?:'([^']+)'|\"([^\"]+)\"|([A-Za-z_][A-Za-z0-9_]*))"
    )
    for line in command.splitlines(keepends=True):
        if pending:
            delimiter, strip_tabs = pending[0]
            candidate = line.rstrip("\r\n")
            if strip_tabs:
                candidate = candidate.lstrip("\t")
            if candidate == delimiter:
                pending.pop(0)
            output.append("\n" if line.endswith(("\n", "\r")) else "")
            continue
        output.append(line)
        for match in declaration.finditer(line):
            delimiter = match.group(2) or match.group(3) or match.group(4)
            pending.append((delimiter, bool(match.group(1))))
    return "".join(output)


def _classify_segment(tokens: list[str], depth: int) -> str | None:
    if not tokens or depth > 5:
        return None
    command_index = 0
    while command_index < len(tokens):
        token = tokens[command_index]
        if token == "env":
            command_index += 1
            while command_index < len(tokens) and (
                tokens[command_index].startswith("-") or "=" in tokens[command_index]
            ):
                command_index += 1
            continue
        if token == "nice":
            command_index += 1
            if command_index < len(tokens) and tokens[command_index] in {
                "-n", "--adjustment",
            }:
                command_index += 2
            continue
        if token in _TRANSPARENT | {"sudo", "command", "builtin"}:
            command_index += 1
            continue
        break
    if command_index >= len(tokens):
        return None
    name = tokens[command_index].rsplit("/", 1)[-1]
    args = tokens[command_index + 1:]

    if name in _SHELLS:
        for index, token in enumerate(args[:-1]):
            if token == "-c" or (token.startswith("-") and "c" in token[1:] and token != "--"):
                return classify_shell_command(args[index + 1])

    if name == "timeout":
        index = 0
        while index < len(args) and args[index].startswith("-"):
            index += 2 if args[index] in {"-k", "--kill-after", "-s", "--signal"} else 1
        if index + 1 < len(args):
            rule = _classify_segment(args[index + 1:], depth + 1)
            timeout_seconds = _sleep_duration([args[index]])
            if (
                rule == "long_sleep"
                and timeout_seconds is not None
                and timeout_seconds <= MAX_SHORT_SLEEP_SECONDS
            ):
                return None
            return rule

    if name == "sleep":
        duration_args = [arg for arg in args if arg != "--"]
        seconds = _sleep_duration(duration_args)
        if seconds is None or seconds > MAX_SHORT_SLEEP_SECONDS:
            return "long_sleep"

    if name == "find":
        for index, token in enumerate(args):
            if token not in {"-exec", "-execdir", "-ok", "-okdir"}:
                continue
            end = next((
                position for position in range(index + 1, len(args))
                if args[position] in {";", "+"}
            ), len(args))
            executable = [token for token in args[index + 1:end] if token != "{}"]
            rule = _classify_segment(executable, depth + 1)
            if rule:
                return rule

    if name == "find" and _rg_available() and not any(
        token in _FIND_SEMANTIC_OPTIONS
        or any(token.startswith(option + "=") for option in ("-mtime", "-mmin", "-newer"))
        for token in args
    ):
        return "recursive_find"

    if name in {"grep", "egrep", "fgrep"} and _rg_available():
        for token in args:
            if token == "--":
                break
            if (
                token.startswith("-") and not token.startswith("--")
                and any(c in token[1:] for c in "rR")
            ):
                return "recursive_grep"
            if token in {"--recursive", "--dereference-recursive"}:
                return "recursive_grep"
    return None


def _sleep_duration(args: list[str]) -> float | None:
    if not args:
        return None
    total = 0.0
    for arg in args:
        match = re.fullmatch(r"(\d+(?:\.\d*)?|\.\d+)([smhd]?)", arg)
        if not match:
            return None
        amount = float(match.group(1))
        multiplier = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}[match.group(2)]
        total += amount * multiplier
    return total


def _codex_shell_command(argv: list[str]) -> str | None:
    if not argv or Path(argv[0]).name not in _SHELLS:
        return None
    for index, arg in enumerate(argv[:-1]):
        if arg == "--command" or arg == "-c" or (
            arg.startswith("-") and "c" in arg[1:] and arg != "--"
        ):
            return argv[index + 1]
    return None


def _is_codex_app_server(executable: str, argv: list[str]) -> bool:
    return Path(executable).name == "codex" and "app-server" in argv


def codex_wrapper_rule(
    command: str,
    process_chain: list[tuple[str, list[str]]],
) -> str | None:
    """Guard Codex tool commands, while leaving commands from applications alone."""
    for index, (executable, argv) in enumerate(process_chain):
        if _is_codex_app_server(executable, argv):
            if index == 0:
                return classify_shell_command(command)
            shell_command = _codex_shell_command(process_chain[index - 1][1])
            return classify_shell_command(shell_command) if shell_command is not None else None
        if Path(executable).name not in _SHELLS:
            return None
    return None


def _process_info(pid: int) -> tuple[str, list[str], int] | None:
    try:
        argv = Path(f"/proc/{pid}/cmdline").read_bytes().decode().rstrip("\0").split("\0")
        executable = os.readlink(f"/proc/{pid}/exe")
        status = Path(f"/proc/{pid}/status").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    parent_line = next((line for line in status.splitlines() if line.startswith("PPid:")), None)
    if parent_line is None:
        return None
    try:
        parent_pid = int(parent_line.split(":", 1)[1].strip())
    except ValueError:
        return None
    return executable, argv, parent_pid


def _codex_wrapper_rule(command: str) -> str | None:
    info = _process_info(os.getppid())
    if info is None:
        return None
    process_chain = []
    for _ in range(16):
        executable, argv, parent_pid = info
        process_chain.append((executable, argv))
        if _is_codex_app_server(executable, argv):
            break
        if Path(executable).name not in _SHELLS:
            return None
        info = _process_info(parent_pid)
        if info is None:
            return None
    return codex_wrapper_rule(command, process_chain)


def codex_policy_wrapper_main() -> int:
    if len(sys.argv) < 3:
        print("POLICY VIOLATION [shell_policy_unavailable]: missing executable", file=sys.stderr)
        return 126
    executable, *args = sys.argv[2:]
    command = shlex.join([Path(executable).name, *args])
    rule = _codex_wrapper_rule(command)
    if rule:
        print(violation_message(rule), file=sys.stderr)
        return 126
    os.execv(executable, [executable, *args])
    return 126


def install_codex_policy_wrappers(directory: Path) -> None:
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    script = Path(__file__).resolve()
    python = sys.executable
    for name in CODEX_POLICY_WRAPPED_COMMANDS:
        executable = shutil.which(name)
        if not executable:
            continue
        wrapper = directory / name
        wrapper.write_text(
            "#!/bin/sh\n"
            f"exec {shlex.quote(python)} {shlex.quote(str(script))} "
            f"codex-policy-wrapper {shlex.quote(executable)} \"$@\"\n",
            encoding="utf-8",
        )
        wrapper.chmod(0o700)


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "codex-policy-wrapper":
    raise SystemExit(codex_policy_wrapper_main())
