"""Built-in tools: bash, read, write, edit, glob, grep.

Path policy (security): read/write/edit/glob/grep resolve their path argument with
Path.resolve() and REJECT anything outside the workspace cwd (canonical resolve also
blocks symlink escape).

Bash sandbox: when ORCHESTRA_AGENT_UID is set, bash subprocess switches to that
unprivileged user via preexec_fn (setgid + setuid). The agent user cannot read
Orchestra source code (/opt/orchestra or equivalent) if directory permissions are
set correctly (750 owner-only). File tools run in the uvicorn process (different
user) and are path-restricted to workspace only.

Each tool returns a plain string (tool result). Errors are returned as strings
(never raised) so the agent loop turns them into tool_result, not a crash.
"""

import ast
import asyncio
import contextlib
import os
import shutil
import signal
import subprocess
import tempfile
from pathlib import Path

BASH_DEFAULT_TIMEOUT = 120
BASH_MAX_TIMEOUT = 600
OUTPUT_CAP = 30_000
READ_MAX_BYTES = 256 * 1024


# ── ACI syntax guard (#122) ──
# A write/edit that would leave a source file syntactically broken is REJECTED with an
# actionable message instead of silently corrupting it — the SWE-agent ACI result
# (linter-on-edit, +10.7pp). Python-only for now via ast.parse (zero deps); unknown
# extensions are not guarded. Add entries to SYNTAX_CHECKERS to cover more languages.

def _py_syntax_error(content: str) -> str | None:
    """Actionable message if `content` is not valid Python for the harness interpreter,
    else None. IndentationError/TabError are SyntaxError subclasses. ast.parse can also
    raise ValueError/TypeError on some inputs — never let the guard itself crash write()."""
    try:
        ast.parse(content)
    except SyntaxError as e:
        loc = f"line {e.lineno}" + (f", col {e.offset}" if e.offset else "")
        return f"{type(e).__name__} at {loc}: {e.msg}"
    except (ValueError, TypeError) as e:
        return f"{type(e).__name__}: {e}"
    return None


SYNTAX_CHECKERS = {".py": _py_syntax_error, ".pyi": _py_syntax_error}


def _syntax_error(path: Path, content: str) -> str | None:
    """Run the checker for this file's extension (case-insensitive), if any."""
    checker = SYNTAX_CHECKERS.get(path.suffix.lower())
    return checker(content) if checker is not None else None

def _resolve_agent_uid() -> int | None:
    """Resolve ORCHESTRA_AGENT_UID to numeric uid. None if not set."""
    raw = os.environ.get("ORCHESTRA_AGENT_UID", "")
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        import pwd
        try:
            return pwd.getpwnam(raw).pw_uid
        except KeyError:
            return None


class PathPolicyError(Exception):
    pass


def _resolve_in_workspace(path: str, cwd: str) -> Path:
    """Resolve `path` (relative to cwd) to a canonical absolute path and ensure it
    stays inside the workspace. Canonical resolve() also collapses symlinks, so a
    symlink pointing outside the workspace is rejected."""
    base = Path(cwd).resolve()
    p = (base / path).resolve() if not os.path.isabs(path) else Path(path).resolve()
    if p != base and base not in p.parents:
        raise PathPolicyError(f"path '{path}' is outside the workspace")
    return p


def _cap(text: str) -> str:
    if len(text) > OUTPUT_CAP:
        return text[:OUTPUT_CAP] + f"\n... (truncated, {len(text) - OUTPUT_CAP} more chars)"
    return text


async def bash(command: str, cwd: str, timeout: int = BASH_DEFAULT_TIMEOUT) -> str:
    """Run a shell command in cwd. When ORCHESTRA_AGENT_UID is set, wraps command
    in `su -s /bin/sh <user> -c` so bash runs as unprivileged user who cannot read
    Orchestra source code. Own process group (setsid) for killpg on timeout."""
    timeout = max(1, min(int(timeout or BASH_DEFAULT_TIMEOUT), BASH_MAX_TIMEOUT))
    agent_user = os.environ.get("ORCHESTRA_AGENT_UID", "")
    if agent_user:
        escaped = command.replace("'", "'\\''")
        command = f"su -s /bin/sh {agent_user} -c '{escaped}'"
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=cwd,
            start_new_session=True,
        )
    except OSError as e:
        return f"[bash error] failed to start: {e}"
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        rc = proc.returncode
        body = out.decode(errors="replace") if out else ""
        return _cap(f"exit_code={rc}\n{body}".rstrip())
    except asyncio.TimeoutError:
        # kill the whole process group, not just the shell
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        with contextlib.suppress(Exception):
            await proc.wait()
        return f"[bash error] command timed out after {timeout}s (killed)"


def read(path: str, cwd: str, offset: int = 0, limit: int = 0) -> str:
    """Read a file with 1-based line numbers. Binary files report a marker.
    offset/limit (lines) for ranges; large files truncated by byte cap."""
    try:
        p = _resolve_in_workspace(path, cwd)
    except PathPolicyError as e:
        return f"[read error] {e}"
    if not p.exists():
        return f"[read error] file not found: {path}"
    if p.is_dir():
        return f"[read error] is a directory: {path}"
    try:
        raw = p.read_bytes()[:READ_MAX_BYTES]
    except OSError as e:
        return f"[read error] {e}"
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return f"[binary file, {p.stat().st_size} bytes — not shown]"
    lines = text.splitlines()
    start = max(0, int(offset or 0))
    end = start + int(limit) if limit else len(lines)
    numbered = [f"{i + 1}\t{ln}" for i, ln in enumerate(lines) if start <= i < end]
    return _cap("\n".join(numbered)) if numbered else "(empty)"


def write(path: str, content: str, cwd: str) -> str:
    """Create/overwrite a file atomically (temp in same dir → rename). Source files
    (.py) are syntax-checked first; broken syntax is rejected and the file is NOT
    changed (ACI guard, #122)."""
    try:
        p = _resolve_in_workspace(path, cwd)
    except PathPolicyError as e:
        return f"[write error] {e}"
    # Syntax guard BEFORE creating the temp file — so a blocked write leaks neither a
    # file descriptor nor a temp file, and the original stays untouched (never renamed).
    err = _syntax_error(p, content)
    if err is not None:
        return (f"[write blocked] {path}: {err}. "
                f"The file was NOT changed — fix the syntax and retry.")
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".harness-tmp-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(tmp, p)  # atomic on same filesystem
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
    except OSError as e:
        return f"[write error] {e}"
    return f"wrote {path} ({len(content)} chars)"


def edit(path: str, old: str, new: str, cwd: str, replace_all: bool = False) -> str:
    """Replace `old` with `new`. Without replace_all, `old` must occur exactly once
    (else error) so the edit is unambiguous."""
    try:
        p = _resolve_in_workspace(path, cwd)
    except PathPolicyError as e:
        return f"[edit error] {e}"
    if not p.exists():
        return f"[edit error] file not found: {path}"
    try:
        content = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return f"[edit error] {e}"
    count = content.count(old)
    if count == 0:
        return f"[edit error] old string not found in {path}"
    if count > 1 and not replace_all:
        return f"[edit error] old string occurs {count}× in {path} — not unique (use replace_all or add context)"
    updated = content.replace(old, new) if replace_all else content.replace(old, new, 1)
    return write(path, updated, cwd)


def glob(pattern: str, cwd: str, limit: int = 200) -> str:
    """Find files matching a glob pattern, newest first. Rejects patterns that escape
    the workspace (absolute, or starting with ../) — parity with the file-tool path
    policy. Matches are additionally filtered to those resolving inside the workspace,
    so a symlink under cwd cannot leak files from outside."""
    base = Path(cwd).resolve()
    if os.path.isabs(pattern) or pattern.startswith(".." + os.sep) or pattern == ".." or pattern.startswith("../"):
        return "[glob error] pattern is outside the workspace"
    try:
        matches = []
        for m in base.glob(pattern):
            if not m.is_file():
                continue
            rp = m.resolve()
            if rp != base and base not in rp.parents:
                continue  # symlink/.. resolving outside cwd — skip
            matches.append(m)
    except (ValueError, OSError) as e:
        return f"[glob error] {e}"
    matches.sort(key=lambda m: m.stat().st_mtime if m.exists() else 0, reverse=True)
    rel = [str(m.relative_to(base)) for m in matches[:limit]]
    if not rel:
        return "(no matches)"
    tail = f"\n... ({len(matches) - limit} more)" if len(matches) > limit else ""
    return "\n".join(rel) + tail


def grep(pattern: str, cwd: str, glob_filter: str = "", limit: int = 200) -> str:
    """Search file contents. Uses ripgrep if available, else falls back to grep -r."""
    rg = shutil.which("rg")
    if rg:
        cmd = [rg, "--line-number", "--no-heading", "--color=never", pattern]
        if glob_filter:
            cmd += ["--glob", glob_filter]
        cmd.append(".")
    else:
        cmd = ["grep", "-rn", pattern, "."]
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"[grep error] {e}"
    out = r.stdout.strip()
    if not out:
        return "(no matches)"
    lines = out.splitlines()[:limit]
    tail = f"\n... (more matches truncated)" if len(out.splitlines()) > limit else ""
    return _cap("\n".join(lines) + tail)


# ── OpenAI tool schemas ──

def tool_schemas() -> list[dict]:
    """OpenAI function-format schemas for the built-in tools."""
    def fn(name, desc, props, required):
        return {"type": "function", "function": {
            "name": name, "description": desc,
            "parameters": {"type": "object", "properties": props, "required": required},
        }}
    s = {"type": "string"}
    i = {"type": "integer"}
    b = {"type": "boolean"}
    return [
        fn("bash", "Run a shell command in the workspace directory.",
           {"command": s, "timeout": i}, ["command"]),
        fn("read", "Read a file with line numbers.",
           {"path": s, "offset": i, "limit": i}, ["path"]),
        fn("write", "Create or overwrite a file. Python files are syntax-checked (must parse "
                    "under the harness Python); a broken write is rejected with the error.",
           {"path": s, "content": s}, ["path", "content"]),
        fn("edit", "Replace an exact (unique) string in a file. Python files are syntax-checked; "
                   "an edit that breaks the syntax is rejected and the file is left unchanged.",
           {"path": s, "old": s, "new": s, "replace_all": b}, ["path", "old", "new"]),
        fn("glob", "Find files by glob pattern (newest first).",
           {"pattern": s}, ["pattern"]),
        fn("grep", "Search file contents (ripgrep).",
           {"pattern": s, "glob_filter": s}, ["pattern"]),
    ]


# ── read-only reviewer subset (#126) ──
# A review sub-agent gets ONLY these — it physically cannot write/edit/run shell (Determinism:
# read-only is structural, not a prompt promise).
READONLY_NAMES = {"read", "glob", "grep"}


def readonly_tool_schemas() -> list[dict]:
    """The read-only subset (read/glob/grep) for the reviewer sub-loop."""
    return [s for s in tool_schemas() if s["function"]["name"] in READONLY_NAMES]


REVIEW_TOOL_NAME = "review"


def review_schema() -> dict:
    """Schema for the `review` tool — spawns a read-only reviewer sub-agent (offered on parent turns)."""
    return {"type": "function", "function": {
        "name": REVIEW_TOOL_NAME,
        "description": ("Spawn a READ-ONLY reviewer sub-agent with a clean context to investigate the "
                        "given focus and report findings. It can read/search files but CANNOT modify "
                        "them. Use for a second opinion or self-review before finishing a task."),
        "parameters": {"type": "object", "properties": {
            "focus": {"type": "string", "description": "What the reviewer should investigate/critique."},
        }, "required": ["focus"]},
    }}


REVIEWER_PROMPT = (
    "You are a READ-ONLY code reviewer sub-agent. You investigate the requested focus using read, "
    "glob and grep, then report concrete findings. You CANNOT modify files, run shell commands, or "
    "spawn other agents — you only read and analyze. Be specific: cite file:line, name the issue, and "
    "suggest a fix. When done, give a short verdict. Keep it focused and finish promptly."
)


async def dispatch(name: str, args: dict, cwd: str) -> tuple[str, bool]:
    """Execute a built-in tool. Returns (result_text, is_file_change).
    Never raises — tool errors come back as strings."""
    try:
        if name == "bash":
            return await bash(args.get("command", ""), cwd, args.get("timeout", BASH_DEFAULT_TIMEOUT)), False
        if name == "read":
            return read(args.get("path", ""), cwd, args.get("offset", 0), args.get("limit", 0)), False
        if name == "write":
            return write(args.get("path", ""), args.get("content", ""), cwd), True
        if name == "edit":
            return edit(args.get("path", ""), args.get("old", ""), args.get("new", ""), cwd, args.get("replace_all", False)), True
        if name == "glob":
            return glob(args.get("pattern", ""), cwd), False
        if name == "grep":
            return grep(args.get("pattern", ""), cwd, args.get("glob_filter", "")), False
    except Exception as e:  # defensive — a tool bug must not crash the loop
        return f"[{name} error] {e}", False
    return f"[error] unknown built-in tool: {name}", False


BUILTIN_NAMES = {"bash", "read", "write", "edit", "glob", "grep"}


# ── gated planning: todo_write (#125) ──
# A lightweight planning aid, offered ONLY on complex turns (the backend hard-gates its schema on
# classify_effort=="high"). Whole-list replace, like Claude Code's TodoWrite, minus the UI-only
# activeForm. State lives in a per-session TodoStore on the backend (not the stateless dispatch).

TODO_TOOL_NAME = "todo_write"
TODO_STATUSES = ("pending", "in_progress", "completed")
_TODO_MARK = {"pending": "[ ]", "in_progress": "[~]", "completed": "[x]"}


def todo_write_schema() -> dict:
    """OpenAI function schema for todo_write (offered only on complex turns)."""
    return {"type": "function", "function": {
        "name": TODO_TOOL_NAME,
        "description": ("Record/update a short task plan for a MULTI-STEP task (≥3 steps or many "
                        "files). Replaces the whole list each call. Mark one item in_progress at a "
                        "time; set completed when done. Skip this for simple one-step tasks."),
        "parameters": {"type": "object", "properties": {"todos": {
            "type": "array",
            "description": "The full updated todo list.",
            "items": {"type": "object", "properties": {
                "content": {"type": "string", "description": "What to do (imperative)."},
                "status": {"type": "string", "enum": list(TODO_STATUSES)},
            }, "required": ["content", "status"]},
        }}, "required": ["todos"]},
    }}


def render_todos(todos: list) -> str:
    """Pure render of a validated todo list to a compact checklist. Returns '[todo error] ...' on an
    invalid item (bad status / empty content / wrong shape) — never raises."""
    if not isinstance(todos, list):
        return "[todo error] todos must be a list"
    if not todos:
        return "(todo list cleared)"
    lines = []
    for idx, item in enumerate(todos):
        if not isinstance(item, dict):
            return f"[todo error] item {idx} is not an object"
        content = item.get("content", "")
        status = item.get("status", "")
        if not isinstance(content, str) or not content.strip():
            return f"[todo error] item {idx} has empty content"
        if status not in TODO_STATUSES:
            return f"[todo error] item {idx} has invalid status '{status}' (use {', '.join(TODO_STATUSES)})"
        lines.append(f"{_TODO_MARK[status]} {content.strip()}")
    return "\n".join(lines)


class TodoStore:
    """Per-session in-memory todo list. Whole-list replace with validation."""

    def __init__(self) -> None:
        self.todos: list[dict] = []

    def write(self, todos) -> str:
        """Validate + replace the whole list; return the rendered checklist. On any invalid input the
        stored list is left UNCHANGED and an actionable error is returned. `todos` missing/not-a-list
        is an error (distinct from an explicit empty list, which is a valid 'clear')."""
        if not isinstance(todos, list):
            return "[todo error] missing or invalid 'todos' (must be a list of {content, status})"
        rendered = render_todos(todos)
        if rendered.startswith("[todo error]"):
            return rendered                      # invalid → do NOT mutate the stored list
        self.todos = [{"content": t["content"].strip(), "status": t["status"]} for t in todos]
        return rendered
