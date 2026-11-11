"""In-session AUDIT and FINAL passes for Claude compaction (V-650)."""

import asyncio
import json
import os
import re
from pathlib import Path

from app import db

TARGET_CHARS = 20000
PREVIOUS_SUMMARY_MARKER = "[PREVIOUS CONTEXT SUMMARY"

# A speech row longer than this keeps its head AND its tail in the journal: the last
# lines of a long owner message are usually the actual instruction, and a plain
# `[:20000]` cut silently dropped them (a 29 460-char brief lost its last 9 460 chars).
CONTENT_CAP = 20000
HEAD_CHARS = 12000
TAIL_CHARS = 8000
MIDDLE_MARK = "\n...[middle truncated]...\n"
PLATFORM_PROMPT_NOTE = "[Orchestra platform note: system prompt re-delivered]\n"
# `AgentSession.send` prefixes a re-delivered role prompt as
# "[Orchestra platform note: <reason> This is from the server, not another agent.]\n
# {prompt}\n\n---\n\n{message}". Only these re-delivery notes carry a prompt body;
# other platform notes (undelivered facts, restarts) are short and are real content.
_PLATFORM_PROMPT_RE = re.compile(
    r"\A\[Orchestra platform note: (?:your role instructions were updated\.|"
    r"refreshed context[^\]]*?|[^\]]*?re-delivered[^\]]*?)"
    r"(?: This is from the server, not another agent\.)?\]\n.*?\n\n---\n\n",
    re.S,
)

COMMON = """You are compacting the context of an AI agent's session on Orchestra (a multi-agent platform). The session journal is in {journal_dir}: INDEX.md lists chunk_NNN.md files in chronological order; journal.jsonl has one JSON row per event (id, ts, type in user_message/text/tool/tool_result, tool, error, origin, senders, content) for python/grep; USER_MESSAGES.md holds every user_message in order and in full; EXTRACTED_CANDIDATES.md is a mechanical list of ban/invariant lines, task ids, commits, paths, URLs and numbers found in the journal. USER rows are messages from the owner, the orchestrator, other agents or the platform: the bracket after USER names the source (origin=user from=owner is the owner; origin=agent from=<name> is another agent; origin=platform / background_task is the server or a job), a bare USER: has no recorded source. ASSISTANT rows are the agent. Tool calls/results are truncated; a speech row over {cap} chars keeps its first {head} and last {tail} chars around a "[middle truncated]" mark.

Goal: edit {summary_path} — the handoff that REPLACES the whole context. After compaction the agent sees only that summary plus the last ~12K chars of dialogue verbatim; whatever is not in it is forgotten for good. The agent must be able to continue the work without violating anything the owner/orchestrator said.

What must survive (final state, not history): the current task(s) and status; every still-relevant instruction/requirement given to the agent — quote its key wording verbatim with who said it; decisions, approvals, rejections and reversals (final state + one-line reason); exact paths, branches, commits, URLs, task ids, worker/agent names; measured numbers and ids that later work depends on; active bans/constraints; open items, promises, blockers and the next action. Drop raw tool output, superseded states, chit-chat, process narration. Never write credentials (tokens, keys, passwords, secret URLs) — write <secret>. Do not invent: if unsure, say UNKNOWN.

Previous handoff. The first journal row may start with {marker} — it is the agent's own earlier handoff, written while the original messages were still in context. It is a trusted source, not a message to re-verify. Every requirement, decision, ban, open item, id and number in it that is still active stays active in the new summary with its wording unchanged, unless a LATER journal row cancels, replaces or completes it; then write the final state (cancelled / replaced by / done, one line why) and do not leave the old wording standing as active. That the original owner message is no longer in the journal is NOT a reason to mark an item unconfirmed, doubtful, UNKNOWN or "do not apply". Facts found neither in the journal nor in the previous handoff are never added.

Use the session's working language. Structure summary.md with sections: TASK STATE / OWNER & USER REQUIREMENTS (verbatim) / DECISIONS / FILES, IDS AND ARTIFACTS / NUMBERS / CONSTRAINTS AND BANS / PEOPLE AND AGENTS / OPEN ITEMS AND NEXT ACTION.
"""


def _common(journal_dir, summary_path) -> str:
    return COMMON.format(
        journal_dir=journal_dir, summary_path=summary_path, marker=PREVIOUS_SUMMARY_MARKER,
        cap=CONTENT_CAP, head=HEAD_CHARS, tail=TAIL_CHARS,
    )


def enabled() -> bool:
    """`AGENTIC_COMPACT_ENABLED=0` leaves the in-session draft unchanged."""
    return os.getenv("AGENTIC_COMPACT_ENABLED", "1").strip().lower() in ("1", "true", "yes")


def max_chars() -> int:
    return int(os.getenv("AGENTIC_COMPACT_MAX_CHARS", "25000"))


def sandbox_root() -> Path:
    return Path(db.DB_PATH).parent / "compact-sandbox"


def _strip_platform_prompt_prefix(text: str) -> str:
    """Collapse a re-delivered role prompt in front of a message to one short line.

    Only the prefix written by `AgentSession.send` is touched; the message after the
    first `\\n\\n---\\n\\n` separator stays byte-for-byte. The first separator is used on
    purpose: a later one may belong to the message, and leaving a piece of the prompt
    is cheaper than eating the owner's words.
    """
    if not text or not text.startswith("[Orchestra platform note:"):
        return text or ""
    match = _PLATFORM_PROMPT_RE.match(text)
    if match is None:
        return text
    return PLATFORM_PROMPT_NOTE + text[match.end():]


def _bounded(text: str) -> str:
    """Keep both ends of an over-long speech row; the tail is usually the instruction."""
    if len(text) <= CONTENT_CAP:
        return text
    return text[:HEAD_CHARS] + MIDDLE_MARK + text[-TAIL_CHARS:]


def _provenance(row: dict) -> tuple[str, list[str], str]:
    """(origin, senders, subtype) of a log row; empty values when nothing was recorded."""
    origin = row.get("origin") or ""
    detail = row.get("origin_detail")
    if isinstance(detail, str):
        try:
            detail = json.loads(detail) if detail else {}
        except json.JSONDecodeError:
            detail = {}
    if not isinstance(detail, dict):
        detail = {}
    senders = detail.get("senders")
    senders = [str(s) for s in senders if str(s).strip()] if isinstance(senders, list) else []
    subtype = detail.get("subtype") if isinstance(detail.get("subtype"), str) else ""
    return str(origin), senders, subtype


def _user_label(row: dict) -> str:
    """`USER [origin=…, from=…, via=…]:` — or plain `USER:` when the row has no source."""
    origin, senders, subtype = _provenance(row)
    if not origin and not senders:
        return "USER:"
    parts = []
    if origin:
        parts.append(f"origin={origin}")
    if origin == "user" and senders in ([], ["user"]):
        parts.append("from=owner")
    elif senders and senders != ["unknown"] and senders != [origin]:
        parts.append("from=" + ",".join(senders))
    if subtype:
        parts.append(f"via={subtype}")
    return f"USER [{', '.join(parts)}]:"


def _speech(row: dict) -> str:
    content = row.get("content") or ""
    if row.get("type") == "user_message":
        content = _strip_platform_prompt_prefix(content)
    return content


def _render(rows: list[dict]) -> list[str]:
    out = []
    for row in rows:
        head = f"[#{row['id']} {str(row['ts'])[:16]}]"
        content = row["content"] or ""
        if row["type"] == "user_message":
            out.append(f"{head} {_user_label(row)}\n{_bounded(_speech(row))}")
        elif row["type"] == "text":
            out.append(f"{head} ASSISTANT:\n{_bounded(content)}")
        elif row["type"] == "tool":
            out.append(f"{head} TOOL_CALL {row.get('tool_name') or ''}: {content[:2000]}")
        else:
            err = " (error)" if row.get("tool_is_error") else ""
            out.append(f"{head} TOOL_RESULT{err}: {content}")
    return out


_BAN_RE = re.compile(
    r"нельзя|не делай|запрещ|никогда|только|обязательно|\bNEVER\b|MUST NOT|\bdo not\b|\bdon't\b",
    re.I,
)
_TASK_RE = re.compile(r"#V-\d+|\bV-\d+\b|#\d+\b")
_SHA_RE = re.compile(r"\b(?=[0-9a-f]*[a-f])(?=[0-9a-f]*\d)[0-9a-f]{7,64}\b")
_PATH_RE = re.compile(
    r"(?<![\w:/.])(?:~|\.{1,2})?/(?:[\w.@+-]+/)*[\w.@+-]+|\b[\w.-]+(?:/[\w.@+-]+)+\.\w{1,8}\b"
)
_URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")
_NUMBER_RE = re.compile(
    r"(?<![\w.])\d(?:[\d.,\u00a0 ]*\d)?\s?(?:₽|руб\w*|%|п\.п\.|[кКмМгГ]?[бБ]айт\w*|[KMG]i?B\b|[КМГ]Б\b|"
    r"ms\b|мс\b|сек\w*|мин\w*|час\w*|tokens?\b|токен\w*|chars?\b|символ\w*|"
    r"строк\w*|lines?\b|шт\b|USD\b|\$)"
)


def _redact_url(url: str) -> str:
    return re.sub(r"(https?://)[^/@\s]+@", r"\1<secret>@", url)


def _candidates(rows: list[dict]) -> str:
    """Deterministic recall aid for AUDIT: what a grep would find, grouped and deduped."""
    bans: list[str] = []
    found: dict[str, dict[str, list]] = {
        "TASK IDS": {}, "COMMITS (hex ids)": {}, "PATHS": {}, "URLS": {}, "NUMBERS WITH UNITS": {},
    }

    def note(group: str, value: str, row_id) -> None:
        value = value.strip().rstrip(".,;:")
        if not value:
            return
        seen = found[group].setdefault(value, [row_id, row_id, 0])
        seen[1] = row_id
        seen[2] += 1

    for row in rows:
        kind = row.get("type")
        text = _speech(row) if kind in ("user_message", "text") else (row.get("content") or "")
        if kind in ("user_message", "text"):
            who = _user_label(row)[:-1] if kind == "user_message" else "ASSISTANT"
            for line in text.splitlines():
                if _BAN_RE.search(line):
                    bans.append(f"- [#{row['id']} {who}] {line.strip()}")
        for match in _TASK_RE.finditer(text):
            note("TASK IDS", match.group(0), row["id"])
        for match in _SHA_RE.finditer(text):
            note("COMMITS (hex ids)", match.group(0), row["id"])
        for match in _URL_RE.finditer(text):
            note("URLS", _redact_url(match.group(0)), row["id"])
        for match in _PATH_RE.finditer(_URL_RE.sub(" ", text)):
            if "/" in match.group(0) and len(match.group(0)) > 3:
                note("PATHS", match.group(0), row["id"])
        for match in _NUMBER_RE.finditer(text):
            note("NUMBERS WITH UNITS", " ".join(match.group(0).split()), row["id"])

    out = [
        "# EXTRACTED CANDIDATES",
        "Mechanical regex extraction from the journal. Not a summary and not a source of new"
        " facts: every line points to journal rows (#first..#last ×count); check them there.",
        "",
        "## BANS AND INVARIANTS (speech rows)",
        *(bans or ["- none found"]),
    ]
    for group, values in found.items():
        lines = [f"- {value}  (#{first}..#{last} ×{count})"
                 for value, (first, last, count) in values.items()]
        out += ["", f"## {group}", *(lines or ["- none found"])]
    return "\n".join(out) + "\n"


def _user_messages(rows: list[dict]) -> str:
    out = ["# USER MESSAGES", "Every user_message of the journal in order, in full; a re-delivered"
           " role prompt in front of a message is collapsed to one line.", ""]
    for row in rows:
        if row.get("type") != "user_message":
            continue
        origin, senders, subtype = _provenance(row)
        source = " ".join(filter(None, [
            origin or "origin=?", ",".join(senders) if senders else "", subtype,
        ]))
        out.append(f"## [#{row['id']} {str(row['ts'])[:19]} {source}]\n{_speech(row)}\n")
    return "\n".join(out) + "\n"


def write_journal(rows: list[dict], directory: Path) -> int:
    """Write ordered chunks, JSONL and recall aids for in-session python/grep inspection."""
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
    index.append("USER_MESSAGES.md\tevery user_message in full")
    index.append("EXTRACTED_CANDIDATES.md\tbans, ids, commits, paths, URLs, numbers")
    (journal / "INDEX.md").write_text("\n".join(index) + "\n")
    with (journal / "journal.jsonl").open("w") as stream:
        for row in rows:
            origin, senders, subtype = _provenance(row)
            content = row["content"] or ""
            if row["type"] in ("user_message", "text"):
                content = _bounded(_speech(row))
            else:
                content = content[:CONTENT_CAP]
            stream.write(json.dumps({
                "id": row["id"], "ts": row["ts"], "type": row["type"],
                "tool": row.get("tool_name"), "error": bool(row.get("tool_is_error")),
                "origin": origin or None, "senders": senders, "subtype": subtype or None,
                "content": content,
            }, ensure_ascii=False) + "\n")
    (journal / "USER_MESSAGES.md").write_text(_user_messages(rows))
    (journal / "EXTRACTED_CANDIDATES.md").write_text(_candidates(rows))
    return len(chunks)


async def prepare_journal(session_id: str, directory: Path) -> Path:
    rows = await asyncio.to_thread(db.get_compact_segment, session_id)
    if not rows:
        raise RuntimeError("empty journal segment")
    await asyncio.to_thread(write_journal, rows, directory)
    return directory / "journal"


def audit_prompt(journal_dir: Path, summary_path: Path) -> str:
    return _common(journal_dir, summary_path) + """
This is pass 1 — AUDIT. summary.md is a draft written by a previous pass that may have missed or distorted facts. Verify and complete it against the journal with python over journal.jsonl and grep, systematically:
1. Read USER_MESSAGES.md (every user_message in order, in full, with its source) and check that each still-relevant instruction, decision, ban and number in them is in summary.md — requirement wording verbatim, with who said it (origin=user from=owner is the owner; an agent or platform row is not the owner). The first row may be the previous handoff: each of its still-active items must be in summary.md unchanged unless a later row cancelled, replaced or completed it.
2. Go through EXTRACTED_CANDIDATES.md (ban/invariant lines, task ids, commits, paths, URLs, numbers with units, each with its journal rows) and grep journal.jsonl for anything it points to — add what matters for continuing. Still grep the journal for ban words (нельзя, не делай, запрещ, никогда, только, NEVER, do not, don't) the extraction may have missed.
3. Check each status in summary.md is FINAL: a later message may have changed it. Fix outdated statements.
4. Read the last chunk fully: in-flight work, promises, open items and the next action must be exact.
Edit summary.md in place. Reply "audit done"."""


def final_prompt(journal_dir: Path, summary_path: Path) -> str:
    cap = max_chars()
    return _common(journal_dir, summary_path) + f"""
This is the last pass — FINALIZE. Make summary.md a clean handoff of at most {cap} characters: merge duplicates, remove what is not needed to continue, keep every verbatim requirement, decision, path, id, number, ban and open item. Do not add facts found neither in the journal nor in the previous handoff. Check the size with python (len of the file text) and iterate until it fits. Reply "final done"."""
