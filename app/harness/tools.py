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
import logging
import os
import re
import signal
import stat
import tempfile
import time
from pathlib import Path

BASH_DEFAULT_TIMEOUT = 120
BASH_MAX_TIMEOUT = 600
OUTPUT_CAP = 30_000
READ_MAX_BYTES = 256 * 1024

logger = logging.getLogger(__name__)


def _umask_from_status(status_text: str) -> int | None:
    """Parse the Umask line of a /proc/<pid>/status dump → int, else None.
    The kernel prints it as %04o — OCTAL (measured: `sh -c 'umask 077'` shows Umask: 0077;
    parsing it as hex silently yields 34 and corrupts the mode — caught by test #367)."""
    for line in status_text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] == "Umask:":
            try:
                return int(parts[1], 8)
            except ValueError:
                return None
    return None


def _read_umask_nondestructive() -> int:
    """Read the process umask WITHOUT changing it: os.umask(x) is destructive, so prefer
    /proc/self/status; fall back to os.umask with immediate restore (#367 D8)."""
    try:
        u = _umask_from_status(open("/proc/self/status").read())
        if u is not None:
            return u
    except OSError:
        pass
    old = os.umask(0o022)
    os.umask(old)
    return old


# Computed ONCE at import — the machine's umask decides what mode agent-written NEW files get.
_CURRENT_UMASK = _read_umask_nondestructive()
NEW_FILE_MODE = 0o666 & ~_CURRENT_UMASK
logger.info("harness tools: umask %04o → new-file mode %04o", _CURRENT_UMASK, NEW_FILE_MODE)


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
    """Read a REGULAR file with 1-based line numbers. Binary files report a marker.
    offset is a DISPLAY line number (1-based; 0 = start); limit caps the line count.
    Reads at most READ_MAX_BYTES+1 bytes (never loads huge files whole); an oversize
    text file is returned truncated WITH an explicit marker stating the full size."""
    try:
        p = _resolve_in_workspace(path, cwd)
    except PathPolicyError as e:
        return f"[read error] {e}"
    try:
        st = p.stat()
    except OSError as e:
        return f"[read error] {e}"
    if not stat.S_ISREG(st.st_mode):
        return f"[read error] not a regular file: {path}"
    try:
        with open(p, "rb") as f:
            raw = f.read(READ_MAX_BYTES + 1)
    except OSError as e:
        return f"[read error] {e}"
    if b"\0" in raw[:8192]:
        return f"[binary file, {st.st_size} bytes — not shown]"
    truncated = len(raw) > READ_MAX_BYTES
    raw = raw[:READ_MAX_BYTES]
    # Byte cap may split a multibyte char — replace instead of falsely declaring binary (#367 D4).
    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    total_lines = len(lines)
    shown_note = ""
    if truncated:
        shown_note = (f"\n(truncated at {READ_MAX_BYTES} bytes of {st.st_size}; "
                      f"{total_lines} lines in shown portion)")
    start = max(0, int(offset or 0))
    idx_start = start - 1 if start > 0 else 0          # offset is a display line number
    if idx_start >= total_lines:
        if truncated:
            return (f"[read error] offset {offset} beyond shown portion "
                    f"(truncated at {READ_MAX_BYTES} bytes of {st.st_size}; "
                    f"{total_lines} lines in shown portion)")
        return f"[read error] offset {offset} past EOF (file has {total_lines} lines)"
    end = idx_start + int(limit) if limit else total_lines
    numbered = [f"{i + 1}\t{ln}" for i, ln in enumerate(lines) if idx_start <= i < end]
    out = _cap("\n".join(numbered)) if numbered else "(empty)"
    if shown_note:
        out += shown_note          # AFTER _cap: the marker must survive output capping
    return out


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
            # Preserve the existing file's access mode across the atomic replace (#367 D8):
            # mkstemp creates 0600 and os.replace would silently make that final. Only
            # permission bits move — an edit must never mint a setuid/setgid file.
            mode = (stat.S_IMODE(p.stat().st_mode) if p.exists() else NEW_FILE_MODE)
            os.chmod(tmp, mode)
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
    result = write(path, updated, cwd)
    if not result.startswith("wrote"):
        return result                      # write blocked (e.g. syntax guard) — surface as-is
    # Own success feedback stating HOW MANY occurrences moved (#367 C3) — "wrote N chars" hides it.
    n = count if replace_all else 1
    suffix = " (replace_all)" if replace_all and count > 1 else ""
    return f"replaced {n}× in {path}{suffix}"


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


GREP_EXCLUDE_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", "dist",
                     "build", ".mypy_cache", ".ruff_cache", ".pytest_cache", ".tox",
                     "target", "vendor"}
GREP_MAX_FILE_BYTES = 1_000_000
GREP_TIME_BUDGET = 25.0


def grep(pattern: str, cwd: str, glob_filter: str = "", limit: int = 200,
         context: int = 0) -> str:
    """Search file contents. Single deterministic Python engine (no external rg/grep —
    the silent engine switch was the root cause of #367's false "(no matches)").

    `pattern` is Python `re` syntax (alternation is a plain `|`; BRE habits like `a\\|b`
    now mean the literal string "a|b"). `glob_filter` matches path segments anchored at
    cwd (Path.match): "app/*.py" does NOT descend into app/sub/. Hidden files are searched;
    VCS/cache dirs in GREP_EXCLUDE_DIRS, binary files (NUL in first 8 KiB) and files over
    1 MiB are skipped — each skip class is COUNTED and reported in the tail. The walk is
    bounded by GREP_TIME_BUDGET seconds; exhaustion returns partial results with an
    explicit note."""
    try:
        rx = re.compile(pattern)
    except re.error as e:
        return f"[grep error] invalid pattern {pattern!r}: {e}"
    base = Path(cwd).resolve()
    flt = glob_filter or None
    limit = max(1, int(limit or 200))
    context = max(0, min(int(context or 0), 5))
    out_lines: list[str] = []
    skipped_binary = skipped_large = 0
    budget_exhausted = False
    deadline = time.monotonic() + GREP_TIME_BUDGET
    try:
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in GREP_EXCLUDE_DIRS]
            if time.monotonic() > deadline:
                budget_exhausted = True
                break
            if len(out_lines) >= limit * 4:
                break
            for name in files:
                fp = Path(root) / name
                rel = fp.relative_to(base)
                if flt is not None and not rel.match(flt):
                    continue
                try:
                    if fp.stat().st_size > GREP_MAX_FILE_BYTES:
                        skipped_large += 1
                        continue
                    raw = fp.read_bytes()
                except OSError:
                    continue
                if b"\0" in raw[:8192]:
                    skipped_binary += 1
                    continue
                # Non-UTF-8 text decodes with replacement chars — the MATCH IS SHOWN,
                # never silently dropped into discarded stderr (#367 D3).
                text = raw.decode("utf-8", errors="replace")
                file_lines = text.splitlines()
                for i, line in enumerate(file_lines):
                    if rx.search(line):
                        s = max(0, i - context)
                        for j in range(s, min(len(file_lines), i + context + 1)):
                            out_lines.append(f"{rel}:{j + 1}:{file_lines[j]}")
                if len(out_lines) >= limit * 4:
                    break
    except OSError as e:
        return f"[grep error] {e}"
    if not out_lines:
        notes = []
        if skipped_binary or skipped_large or budget_exhausted:
            notes.append(f"skipped {skipped_binary} binary / {skipped_large} oversize files"
                         + ("; search budget exhausted" if budget_exhausted else ""))
        return "(no matches)" + (f" ({'; '.join(notes)})" if notes else "")
    shown = out_lines[:limit * 4]
    tail_parts = []
    if len(out_lines) > len(shown):
        tail_parts.append("more matches truncated")
    if skipped_binary or skipped_large:
        tail_parts.append(f"skipped {skipped_binary} binary / {skipped_large} oversize files")
    if budget_exhausted:
        tail_parts.append("search budget exhausted — results PARTIAL")
    tail = f"\n... ({'; '.join(tail_parts)})" if tail_parts else ""
    return _cap("\n".join(shown) + tail)


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
        fn("glob", "Find files by glob pattern (newest first). Patterns are NOT recursive "
                    "by default — use '**' for recursion, e.g. '**/*.py' finds nested files; "
                    "'*.py' matches only the workspace top level.",
           {"pattern": s, "limit": i}, ["pattern"]),
        fn("grep", "Search file contents. Pattern is Python re syntax (alternation '|', "
                   "\\d, \\b...); BRE habits like 'a\\|b' mean the LITERAL string 'a|b'. "
                   "Hidden files searched; VCS/cache dirs skipped.",
           {"pattern": s, "glob_filter": s, "limit": i,
            "context": {"type": "integer",
                        "description": "Lines of context around each match (0-5)."}}, ["pattern"]),
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


_MUTATION_LOCK = asyncio.Lock()   # serializes write/edit across concurrent sessions (#367 B2):
                                  # inline-on-the-loop execution used to give them that for free


async def dispatch(name: str, args: dict, cwd: str) -> tuple[str, bool]:
    """Execute a built-in tool. Returns (result_text, is_file_change).
    Never raises — tool errors come back as strings.
    Sync tools run in a worker thread: inline execution blocked the SERVER event loop for
    the whole subprocess/file duration (measured: 10ms sleep took 2008ms under grep, #367 D6)."""
    try:
        if name == "bash":
            return await bash(args.get("command", ""), cwd, args.get("timeout", BASH_DEFAULT_TIMEOUT)), False
        if name == "read":
            return await asyncio.to_thread(read, args.get("path", ""), cwd,
                                           args.get("offset", 0), args.get("limit", 0)), False
        if name == "write":
            async with _MUTATION_LOCK:
                return await asyncio.to_thread(write, args.get("path", ""), args.get("content", ""), cwd), True
        if name == "edit":
            async with _MUTATION_LOCK:
                return await asyncio.to_thread(edit, args.get("path", ""), args.get("old", ""),
                                               args.get("new", ""), cwd, args.get("replace_all", False)), True
        if name == "glob":
            return await asyncio.to_thread(glob, args.get("pattern", ""), cwd, args.get("limit", 200)), False
        if name == "grep":
            return await asyncio.to_thread(grep, args.get("pattern", ""), cwd, args.get("glob_filter", ""),
                                           args.get("limit", 200), args.get("context", 0)), False
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
