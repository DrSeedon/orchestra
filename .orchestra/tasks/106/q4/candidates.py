import hashlib
import importlib.util
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PARENT = ROOT.parent


def _load_current_prompt() -> str:
    spec = importlib.util.spec_from_file_location(
        "q106_original_prompts", PARENT / "prompts.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load original #106 prompts")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ORCHESTRA_CURRENT


ORCHESTRA_CURRENT = _load_current_prompt()

EXACT3_PROMPT = ORCHESTRA_CURRENT.replace(
    "RECENT: Last 5-10 exchanges in detail — what was asked, what you did, what the result was.",
    "RECENT USER MESSAGES: Copy the last 3 user messages verbatim and in order. "
    "Do not paraphrase, normalize, translate, or omit punctuation. Replace any credential, "
    "token, password, private key, or equivalent secret span with "
    "`[REDACTED SECRET: <type>]` while preserving all surrounding text exactly.",
)

RAW_TAIL_PROMPT = ORCHESTRA_CURRENT.replace(
    "RECENT: Last 5-10 exchanges in detail — what was asked, what you did, what the result was.",
    "RECENT: Do not reproduce recent user messages. The runtime will append a protected, "
    "redacted raw tail after your summary. Preserve only decisions or pending state from "
    "those messages when needed elsewhere.",
)

HOT_LEDGER_PROMPT = """[SYSTEM: Context compaction requested — structured handoff]

Before writing the handoff, promote a durable fact only when the conversation explicitly names an existing canonical Markdown path and the exact fact to store. Update only that path, preserve unrelated content, and make the write idempotent. Otherwise do not write files. Never create CLAUDE.md, TODO.md, BUGS.md, or a new note solely for compaction. Never write credentials.

Write a compact task-state handoff from supported evidence only. The runtime will append a redacted raw user tail and a deterministic tool/file ledger after your text; do not copy or infer those records.

TASK STATE
- Current objective, phase, and evidence-backed status.

DECISIONS
- Only active decisions and reversals needed to continue; retain provisional/final state and rationale.

BLOCKER / NEXT
- Current blocker and owner if known; then the single next executable action. If continuity is uncertain, write `UNKNOWN — source gap` instead of guessing.

CONSTRAINTS
- Still-active user preferences, safety constraints, and unresolved conflicts. Distinguish durable preferences from one-off instructions.

Do not claim a file was read, changed, committed, deployed, or tested unless the conversation or tool evidence says so. Omit redundant tool output and all credentials. Output only these four short sections."""


PRIMARY_VARIANTS = {
    "orchestra_current": ORCHESTRA_CURRENT,
    "exact3_prompt": EXACT3_PROMPT,
    "raw_tail": RAW_TAIL_PROMPT,
    "hot_state_ledger": HOT_LEDGER_PROMPT,
}

CANDIDATE_VARIANTS = tuple(
    name for name in PRIMARY_VARIANTS if name != "orchestra_current"
)

_USER_LINE = re.compile(r"^\[USER\]\s?(.*)$")
_PROTECTED_LINE = re.compile(r"^\[(?:1|2|3)\]\s?(.*)$")
_TOOL_EVENT = re.compile(
    r"^\[(?:TOOL|TOOL_RESULT|ASSISTANT TOOL_USE)(?:\s|\])"
)
_TOOL_ID = re.compile(r"\bid=([A-Za-z0-9_.:-]+)")


def redact(text: str, fixture: dict) -> str:
    for secret, replacement in fixture.get("redactions", {}).items():
        text = text.replace(secret, replacement)
    generic = (
        (re.compile(r"sk-FAKE-[A-Za-z0-9_-]+"), "[REDACTED SECRET: token]"),
        (re.compile(r"AKIA_FAKE_[A-Za-z0-9_-]+"), "[REDACTED SECRET: access key]"),
        (re.compile(r"ghp_FAKE_[A-Za-z0-9_-]+"), "[REDACTED SECRET: token]"),
    )
    for pattern, replacement in generic:
        text = pattern.sub(replacement, text)
    return text


def recent_user_messages(transcript: str, fixture: dict) -> list[str]:
    messages = []
    for line in transcript.splitlines():
        match = _USER_LINE.match(line)
        if match:
            messages.append(match.group(1))
    if not messages and "PROTECTED RECENT USER MESSAGES" in transcript:
        in_block = False
        for line in transcript.splitlines():
            if line == "PROTECTED RECENT USER MESSAGES":
                in_block = True
                continue
            if in_block and line.startswith("DETERMINISTIC EVIDENCE LEDGER"):
                break
            if in_block:
                match = _PROTECTED_LINE.match(line)
                if match:
                    messages.append(match.group(1))
    return [redact(message, fixture) for message in messages[-3:]]


def _event_ledger(transcript: str, fixture: dict) -> list[str]:
    events = [
        redact(line, fixture)
        for line in transcript.splitlines()
        if _TOOL_EVENT.match(line)
    ]
    uses = {}
    results = set()
    for event in events:
        match = _TOOL_ID.search(event)
        if not match:
            continue
        event_id = match.group(1)
        if event.startswith("[ASSISTANT TOOL_USE"):
            uses[event_id] = event
        elif event.startswith("[TOOL_RESULT"):
            results.add(event_id)
    for event_id in sorted(set(uses) - results):
        events.append(f"[GAP unmatched tool event id={event_id}: result absent]")
    return events


def _excerpt(value: str | None, fixture: dict, limit: int = 180) -> str:
    if value is None:
        return "<absent>"
    value = redact(value.replace("\n", "\\n"), fixture)
    if len(value) <= limit:
        return value
    return value[:90] + f"…<{len(value) - 180} chars omitted>…" + value[-90:]


def _file_ledger(
    files_before: dict[str, str], files_after: dict[str, str], fixture: dict
) -> list[str]:
    rows = []
    for path in sorted(set(files_before) | set(files_after)):
        before = files_before.get(path)
        after = files_after.get(path)
        if before == after:
            continue
        if before is None:
            change = "created"
        elif after is None:
            change = "deleted"
        else:
            change = "modified"
        before_hash = hashlib.sha256((before or "").encode()).hexdigest()[:12]
        after_hash = hashlib.sha256((after or "").encode()).hexdigest()[:12]
        rows.append(
            f"{path} | {change} | before_sha256={before_hash} | "
            f"after_sha256={after_hash} | after={_excerpt(after, fixture)}"
        )
    return rows or ["no measured file changes"]


def compose_handoff(
    variant: str,
    model_summary: str,
    transcript: str,
    fixture: dict,
    files_before: dict[str, str],
    files_after: dict[str, str],
) -> str:
    if variant in {"orchestra_current", "exact3_prompt"}:
        return model_summary
    recent = recent_user_messages(transcript, fixture)
    recent_block = "\n".join(
        f"[{index}] {message}" for index, message in enumerate(recent, start=1)
    )
    parts = [
        model_summary.rstrip(),
        "PROTECTED RECENT USER MESSAGES",
        recent_block or "[GAP: no user messages found]",
    ]
    if variant == "hot_state_ledger":
        parts.extend(
            [
                "DETERMINISTIC EVIDENCE LEDGER",
                "TOOL EVENTS",
                "\n".join(_event_ledger(transcript, fixture))
                or "no structured tool events",
                "MEASURED WORKSPACE DIFF",
                "\n".join(_file_ledger(files_before, files_after, fixture)),
            ]
        )
    return "\n\n".join(parts).strip()
