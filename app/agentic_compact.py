"""In-session AUDIT and FINAL passes for Claude compaction (V-650)."""

import asyncio
import json
import os
import re
from pathlib import Path

from app import db

TARGET_CHARS = 20000

COMMON = """You are compacting the context of an AI agent's session on Orchestra (a multi-agent platform). The session journal is in {journal_dir}: INDEX.md lists chunk_NNN.md files in chronological order; journal.jsonl has one JSON row per event (id, ts, type in user_message/text/tool/tool_result, tool, error, content) for python/grep. USER rows are messages from the owner, the orchestrator, other agents or the platform; ASSISTANT rows are the agent. Tool calls/results are truncated.

Goal: edit {summary_path} — the handoff that REPLACES the whole context. After compaction the agent sees only that summary plus the last ~12K chars of dialogue verbatim; whatever is not in it is forgotten for good. The agent must be able to continue the work without violating anything the owner/orchestrator said.

What must survive (final state, not history): the current task(s) and status; every still-relevant instruction/requirement given to the agent — quote its key wording verbatim with who said it; decisions, approvals, rejections and reversals (final state + one-line reason); exact paths, branches, commits, URLs, task ids, worker/agent names; measured numbers and ids that later work depends on; active bans/constraints; open items, promises, blockers and the next action. Drop raw tool output, superseded states, chit-chat, process narration. Never write credentials (tokens, keys, passwords, secret URLs) — write <secret>. Do not invent: if unsure, say UNKNOWN.

Use the session's working language. Structure summary.md with sections: TASK STATE / OWNER & USER REQUIREMENTS (verbatim) / DECISIONS / FILES, IDS AND ARTIFACTS / NUMBERS / CONSTRAINTS AND BANS / PEOPLE AND AGENTS / OPEN ITEMS AND NEXT ACTION.
"""


def enabled() -> bool:
    """`AGENTIC_COMPACT_ENABLED=0` leaves the in-session draft unchanged."""
    return os.getenv("AGENTIC_COMPACT_ENABLED", "1").strip().lower() in ("1", "true", "yes")


def max_chars() -> int:
    return int(os.getenv("AGENTIC_COMPACT_MAX_CHARS", "25000"))


def sandbox_root() -> Path:
    return Path(db.DB_PATH).parent / "compact-sandbox"


def _render(rows: list[dict]) -> list[str]:
    out = []
    for row in rows:
        head = f"[#{row['id']} {str(row['ts'])[:16]}]"
        content = row["content"] or ""
        if row["type"] == "user_message":
            out.append(f"{head} USER:\n{content}")
        elif row["type"] == "text":
            out.append(f"{head} ASSISTANT:\n{content}")
        elif row["type"] == "tool":
            out.append(f"{head} TOOL_CALL {row.get('tool_name') or ''}: {content[:2000]}")
        else:
            err = " (error)" if row.get("tool_is_error") else ""
            out.append(f"{head} TOOL_RESULT{err}: {content}")
    return out


def write_journal(rows: list[dict], directory: Path) -> int:
    """Write ordered chunks and JSONL for in-session python/grep inspection."""
    journal = directory / "journal"
    journal.mkdir(parents=True)
    chunks, current, size = [], [], 0
    for entry in _render(rows):
        current.append(entry)
        size += len(entry)
        if size > 60000:
            chunks.append(current)
            current, size = [], 0
    if current:
        chunks.append(current)
    index = []
    for number, chunk in enumerate(chunks, 1):
        text = "\n\n".join(chunk)
        name = f"chunk_{number:03d}.md"
        (journal / name).write_text(text)
        first = re.match(r"\[#(\d+) ([^\]]+)\]", text)
        index.append(f"{name}\t{len(text)} chars\tfrom #{first.group(1)} {first.group(2)}" if first else name)
    (journal / "INDEX.md").write_text("\n".join(index) + "\n")
    with (journal / "journal.jsonl").open("w") as stream:
        for row in rows:
            stream.write(json.dumps({
                "id": row["id"], "ts": row["ts"], "type": row["type"],
                "tool": row.get("tool_name"), "error": bool(row.get("tool_is_error")),
                "content": (row["content"] or "")[:20000],
            }, ensure_ascii=False) + "\n")
    return len(chunks)


async def prepare_journal(session_id: str, directory: Path) -> Path:
    rows = await asyncio.to_thread(db.get_compact_segment, session_id)
    if not rows:
        raise RuntimeError("empty journal segment")
    await asyncio.to_thread(write_journal, rows, directory)
    return directory / "journal"


def audit_prompt(journal_dir: Path, summary_path: Path) -> str:
    return COMMON.format(journal_dir=journal_dir, summary_path=summary_path) + """
This is pass 1 — AUDIT. summary.md is a draft written by a previous pass that may have missed or distorted facts. Verify and complete it against the journal with python over journal.jsonl and grep, systematically:
1. Print every user_message (python; shorten long platform notices) and check that each still-relevant instruction, decision, ban and number in them is in summary.md — requirement wording verbatim.
2. Grep the journal for paths, commit hashes, task ids (e.g. #V-123, V-123, #123), URLs, numbers with units, and ban words (нельзя, не делай, запрещ, никогда, только, NEVER, do not, don't) — add what matters for continuing.
3. Check each status in summary.md is FINAL: a later message may have changed it. Fix outdated statements.
4. Read the last chunk fully: in-flight work, promises, open items and the next action must be exact.
Edit summary.md in place. Reply "audit done"."""


def final_prompt(journal_dir: Path, summary_path: Path) -> str:
    cap = TARGET_CHARS
    return COMMON.format(journal_dir=journal_dir, summary_path=summary_path) + f"""
This is the last pass — FINALIZE. Make summary.md a clean handoff of at most {cap} characters: merge duplicates, remove what is not needed to continue, keep every verbatim requirement, decision, path, id, number, ban and open item. Do not add facts you have not verified in the journal. Check the size with python (len of the file text) and iterate until it fits. Reply "final done"."""
