"""Агентный аудит сводки компакта (V-643).

Одноходовая сводка, которую сессия пишет в своём контексте, теряет числа и незавершённые
дела: на 9 реальных компактах доля правильных ответов после сжатия была 0.55. Схема hybrid
(.orchestra/tasks/V-643/report.md) дала 0.85: журнал сессии от последней преамбулы компакта
раскладывается файлами в песочницу, отдельный процесс CLI той же модели (без MCP,
--safe-mode) сначала пишет свежий черновик по тому же промпту компакта, затем проходы AUDIT и
FINAL проверяют и дополняют summary.md. Аудит поверх сводки из контекста давал только 0.74:
он закрепляет пробелы черновика, поэтому черновик пишется заново.

Любой сбой возвращает сводку из контекста: компакт из-за аудита не падает.
"""

import asyncio
import json
import logging
import os
import re
import shutil
import signal
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app import db

logger = logging.getLogger(__name__)

TOOLS = "Read,Grep,Glob,Write,Edit,Bash"
TARGET_CHARS = 20000
CHUNK_CHARS = 60000

COMMON = """You are compacting the context of an AI agent's session on Orchestra (a multi-agent platform). The session journal is in ./journal/: INDEX.md lists chunk_NNN.md files in chronological order; journal.jsonl has one JSON row per event (id, ts, type in user_message/text/tool/tool_result, tool, error, content) for python/grep. USER rows are messages from the owner, the orchestrator, other agents or the platform; ASSISTANT rows are the agent. Tool calls/results are truncated.

Goal: ./summary.md — the handoff that REPLACES the whole context. After compaction the agent sees only summary.md plus the last ~12K chars of dialogue verbatim; whatever is not in summary.md is forgotten for good. The agent must be able to continue the work without violating anything the owner/orchestrator said.

What must survive (final state, not history): the current task(s) and status; every still-relevant instruction/requirement given to the agent — quote its key wording verbatim with who said it; decisions, approvals, rejections and reversals (final state + one-line reason); exact paths, branches, commits, URLs, task ids, worker/agent names; measured numbers and ids that later work depends on; active bans/constraints; open items, promises, blockers and the next action. Drop raw tool output, superseded states, chit-chat, process narration. Never write credentials (tokens, keys, passwords, secret URLs) — write <secret>. Do not invent: if unsure, say UNKNOWN.

Use the session's working language. Structure summary.md with sections: TASK STATE / OWNER & USER REQUIREMENTS (verbatim) / DECISIONS / FILES, IDS AND ARTIFACTS / NUMBERS / CONSTRAINTS AND BANS / PEOPLE AND AGENTS / OPEN ITEMS AND NEXT ACTION.
"""

AUDIT = COMMON + """
This is pass 1 — AUDIT. summary.md is a draft written by a previous pass that may have missed or distorted facts. Verify and complete it against the journal with python over journal/journal.jsonl and grep, systematically:
1. Print every user_message (python; shorten long platform notices) and check that each still-relevant instruction, decision, ban and number in them is in summary.md — requirement wording verbatim.
2. Grep the journal for paths, commit hashes, task ids (e.g. #V-123, V-123, #123), URLs, numbers with units, and ban words (нельзя, не делай, запрещ, никогда, только, NEVER, do not, don't) — add what matters for continuing.
3. Check each status in summary.md is FINAL: a later message may have changed it. Fix outdated statements.
4. Read the last chunk fully: in-flight work, promises, open items and the next action must be exact.
Edit summary.md in place. Reply "audit done"."""

FINAL = COMMON + """
This is the last pass — FINALIZE. Make summary.md a clean handoff of at most {cap} characters: merge duplicates, remove what is not needed to continue, keep every verbatim requirement, decision, path, id, number, ban and open item. Do not add facts you have not verified in the journal. Check the size with python (len of the file text) and iterate until it fits. Reply "final done"."""


def enabled() -> bool:
    """`AGENTIC_COMPACT_ENABLED=0` возвращает одноходовый компакт без аудита."""
    return os.getenv("AGENTIC_COMPACT_ENABLED", "1").strip().lower() in ("1", "true", "yes")


def _timeout() -> float:
    return float(os.getenv("AGENTIC_COMPACT_TIMEOUT", "900"))


def _max_chars() -> int:
    return int(os.getenv("AGENTIC_COMPACT_MAX_CHARS", "25000"))


def sandbox_root() -> Path:
    return Path(db.DB_PATH).parent / "compact-sandbox"


@dataclass
class AuditResult:
    summary: str
    applied: bool
    cost: float
    seconds: float
    reason: str


def _render(rows: list[dict]) -> list[str]:
    out = []
    for r in rows:
        head = f"[#{r['id']} {str(r['ts'])[:16]}]"
        content = r["content"] or ""
        if r["type"] == "user_message":
            out.append(f"{head} USER:\n{content}")
        elif r["type"] == "text":
            out.append(f"{head} ASSISTANT:\n{content}")
        elif r["type"] == "tool":
            out.append(f"{head} TOOL_CALL {r.get('tool_name') or ''}: {content[:2000]}")
        else:
            err = " (error)" if r.get("tool_is_error") else ""
            out.append(f"{head} TOOL_RESULT{err}: {content}")
    return out


def condensed_transcript(rows: list[dict]) -> str:
    """Транскрипт для черновика одним сообщением: речь целиком, инструменты усечены."""
    out = []
    for r in rows:
        head = f"[#{r['id']} {str(r['ts'])[:16]}]"
        content = r["content"] or ""
        if r["type"] == "user_message":
            out.append(f"{head} USER:\n{content[:30000]}")
        elif r["type"] == "text":
            out.append(f"{head} ASSISTANT:\n{content}")
        elif r["type"] == "tool":
            out.append(f"{head} TOOL_CALL {r.get('tool_name') or ''}: {content[:300]}")
        else:
            err = " (error)" if r.get("tool_is_error") else ""
            out.append(f"{head} TOOL_RESULT{err}: {content[:600]}")
    return "\n\n".join(out)


def write_journal(rows: list[dict], directory: Path) -> int:
    """Журнал файлами: чанки для чтения по порядку, jsonl для python/grep. Возвращает число чанков."""
    journal = directory / "journal"
    journal.mkdir(parents=True)
    chunks, current, size = [], [], 0
    for entry in _render(rows):
        current.append(entry)
        size += len(entry)
        if size > CHUNK_CHARS:
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
    with open(journal / "journal.jsonl", "w") as f:
        for r in rows:
            f.write(json.dumps({
                "id": r["id"], "ts": r["ts"], "type": r["type"], "tool": r.get("tool_name"),
                "error": bool(r.get("tool_is_error")), "content": (r["content"] or "")[:20000],
            }, ensure_ascii=False) + "\n")
    return len(chunks)


def _cli_env(config_dir: str) -> dict:
    env = dict(os.environ)
    env["DISABLE_NON_ESSENTIAL_MODEL_CALLS"] = "1"
    env["DISABLE_TELEMETRY"] = "1"
    if config_dir:
        env["CLAUDE_CONFIG_DIR"] = os.path.expanduser(config_dir)
    return env


async def _run_pass(prompt: str, *, cwd: Path, model: str, config_dir: str, deadline: float,
                    should_stop: Callable[[], bool], tools: str = TOOLS) -> tuple[float, str]:
    """Один проход CLI. Возвращает (стоимость, текст ответа); при ошибке, таймауте или стопе — исключение."""
    cli = shutil.which("claude") or os.environ.get("CLAUDE_CLI_PATH", "claude")
    args = ["-p", "--safe-mode", "--model", model, "--strict-mcp-config",
            "--no-session-persistence", "--output-format", "json", "--tools", tools]
    if tools:
        args += ["--allowedTools", tools, "--permission-mode", "acceptEdits"]
    cwd.mkdir(parents=True, exist_ok=True)
    proc = await asyncio.create_subprocess_exec(
        cli, *args,
        cwd=str(cwd), env=_cli_env(config_dir),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, start_new_session=True,
    )
    task = asyncio.ensure_future(proc.communicate(prompt.encode()))
    try:
        while not task.done():
            if should_stop():
                raise RuntimeError("stopped")
            if time.monotonic() > deadline:
                raise TimeoutError("timeout")
            await asyncio.wait({task}, timeout=1)
        stdout, stderr = task.result()
    except BaseException:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        task.cancel()
        await proc.wait()
        raise
    try:
        data = json.loads(stdout.decode() or "{}")
    except json.JSONDecodeError:
        data = {}
    cost = float(data.get("total_cost_usd") or 0)
    if proc.returncode != 0 or data.get("is_error") or not data:
        tail = (stderr.decode(errors="replace") or str(data.get("result", "")))[-300:]
        raise RuntimeError(f"cli exit {proc.returncode}: {tail.strip()}")
    return cost, str(data.get("result") or "")


async def audit_summary(*, session_id: str, model: str, draft: str, draft_prompt: str,
                        config_dir: str = "",
                        should_stop: Callable[[], bool] = lambda: False) -> AuditResult:
    """`draft` — сводка из контекста сессии (фолбэк), `draft_prompt` — промпт компакта для
    свежего черновика по журналу."""
    started = time.monotonic()

    def fallback(reason: str, cost: float = 0.0) -> AuditResult:
        return AuditResult(draft, False, cost, round(time.monotonic() - started, 1), reason)

    if not enabled():
        return fallback("disabled (AGENTIC_COMPACT_ENABLED=0)")
    if os.environ.get("ORCHESTRA_AGENT_UID"):
        # CLI агента запускается под отдельным uid; песочница и процесс аудита этого не
        # воспроизводят, поэтому в такой конфигурации аудит не запускаем.
        return fallback("agent uid isolation is not supported")
    sandbox = sandbox_root() / f"{session_id}-{uuid.uuid4().hex[:8]}"
    cost = 0.0
    try:
        rows = await asyncio.to_thread(db.get_compact_segment, session_id)
        if not rows:
            return fallback("empty journal segment")
        await asyncio.to_thread(write_journal, rows, sandbox)
        deadline = started + _timeout()
        passes = dict(model=model, config_dir=config_dir, deadline=deadline, should_stop=should_stop)
        transcript = condensed_transcript(rows)
        spent, fresh = await _run_pass(
            "Below is the transcript of your session so far (tool calls/results truncated).\n\n"
            f"=== TRANSCRIPT ===\n{transcript}\n=== END ===\n\n{draft_prompt}",
            cwd=sandbox / "draft", tools="", **passes,
        )
        cost += spent
        if not fresh.strip():
            return fallback("fresh draft is empty", cost)
        target = sandbox / "summary.md"
        target.write_text(fresh.strip())
        for prompt in (AUDIT, FINAL.format(cap=TARGET_CHARS)):
            spent, _ = await _run_pass(prompt, cwd=sandbox, **passes)
            cost += spent
        result = target.read_text().strip() if target.exists() else ""
        if not result:
            return fallback("audit produced empty summary", cost)
        if len(result) > _max_chars():
            return fallback(f"audit summary too long ({len(result)} > {_max_chars()} chars)", cost)
        return AuditResult(result, True, cost, round(time.monotonic() - started, 1), "ok")
    except Exception as error:
        return fallback(f"{type(error).__name__}: {error}"[:400], cost)
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)
