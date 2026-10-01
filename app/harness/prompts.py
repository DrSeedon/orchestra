"""System prompt + OpenAI tool-schema assembly for the harness.

The model already knows how to use tools from their JSON schemas; the prompt
stays lean. Tool guidelines are short and name each tool explicitly (so the
model never has to guess which "this tool" a bullet refers to).
"""

from pathlib import Path

_TOOL_GUIDELINES = """
You operate in a workspace directory with these tools:
- bash: run shell commands (git, tests, build). Runs in the workspace cwd.
- read: read a file (line-numbered, 1-based offset). Use before editing.
- write: create or overwrite a file.
- edit: replace an exact unique string in a file.
- glob: find files by pattern ('**/*.py' for recursive search).
- grep: search file contents (Python re syntax; '|' alternates).
Independent tool calls (several reads, several greps) go in ONE reply — each reply costs one API request.
Prefer read before write/edit. Keep changes minimal and verify with bash when useful.
""".strip()


# GigaChat returns at most one function_call per reply, and without an explicit rule
# GigaChat-2-Max wrote `ls`/`python` and invented their output as text (V-636).
_SINGLE_CALL_GUIDELINES = """
Call exactly one function per reply; its result arrives in the next message.
Never write a command or its output as text: call bash (or read/glob) and report only what it actually returned.
""".strip()


# Тот же потолок, что у Codex по умолчанию (project_doc_max_bytes = 32 KiB).
PROJECT_DOC_MAX_BYTES = 32 * 1024


def project_instructions(cwd: str) -> str:
    """Project rules the way managed Codex sees them: from the git root down to cwd,
    one file per directory — AGENTS.md, else CLAUDE.md (they are often one file under
    two names). Personal global files are deliberately not read: shared norms reach
    agents through pipeline modules (owner's decision, V-570)."""
    if not cwd:
        return ""
    here = Path(cwd).resolve()
    root = next((p for p in (here, *here.parents) if (p / ".git").exists()), here)
    dirs = [here, *here.parents]
    dirs = list(reversed(dirs[: dirs.index(root) + 1]))
    seen: set[Path] = set()
    parts: list[str] = []
    budget = PROJECT_DOC_MAX_BYTES
    for d in dirs:
        doc = next((d / n for n in ("AGENTS.md", "CLAUDE.md") if (d / n).is_file()), None)
        if doc is None or doc.resolve() in seen:
            continue
        seen.add(doc.resolve())
        raw = doc.read_bytes()
        text = raw[:budget].decode("utf-8", errors="ignore")
        if len(raw) > budget:
            text += f"\n[harness: {doc} truncated at {PROJECT_DOC_MAX_BYTES} bytes]"
        parts.append(f"# Project instructions: {doc}\n\n{text.strip()}")
        budget -= min(len(raw), budget)
        if budget <= 0:
            break
    return "\n\n".join(parts)


def build_system_prompt(base: str, has_own_tools: bool = True, *, cwd: str = "",
                        single_call: bool = False) -> str:
    """base = Orchestra role prompt; then project rules; then concise tool guidelines."""
    parts = [base.strip()] if base and base.strip() else []
    project = project_instructions(cwd)
    if project:
        parts.append(project)
    if has_own_tools:
        guidelines = _TOOL_GUIDELINES
        if single_call:
            guidelines = guidelines.replace(
                "Independent tool calls (several reads, several greps) go in ONE reply — "
                "each reply costs one API request.\n", "")
            guidelines += "\n" + _SINGLE_CALL_GUIDELINES
        if cwd:
            guidelines += f"\nWorkspace directory (cwd of every tool): {cwd}"
        parts.append(guidelines)
    return "\n\n".join(parts)


def merge_tool_schemas(own_tools: list[dict], mcp_tools: list[dict]) -> list[dict]:
    """Combine own + MCP tool schemas (already OpenAI function-format).

    Fail fast on duplicate tool names — collisions across MCP servers or with
    own tools are a hard error (the model cannot disambiguate by name).
    """
    seen: dict[str, str] = {}
    out: list[dict] = []
    for src, schemas in (("own", own_tools), ("mcp", mcp_tools)):
        for s in schemas:
            name = s.get("function", {}).get("name", "")
            if name in seen:
                raise ValueError(
                    f"duplicate tool name '{name}' (from {src}, already from {seen[name]})"
                )
            seen[name] = src
            out.append(s)
    return out
