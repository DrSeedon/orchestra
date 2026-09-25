"""V-643: методы сжатия. Каждый метод: fn(ctx) -> (summary_text, [ledger records]).

Сжимает та же модель, на которой шла сессия (решение владельца): модель берётся из meta.json кейса.
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
TOOLS = "Read,Grep,Glob,Write,Edit,Bash"
COMPACT_PROMPT = (Path(__file__).resolve().parents[3] / "data" / "v643" / "compact_prompt.txt")


def session_model(ctx):
    return json.loads((ctx["case_dir"] / "meta.json").read_text())["model"]


def _oneshot(prompt_text):
    def run(ctx):
        model = session_model(ctx)
        transcript = (ctx["case_dir"] / "transcript.md").read_text()
        prompt = ("Below is the transcript of your session so far (tool calls/results truncated).\n\n"
                  f"=== TRANSCRIPT ===\n{transcript}\n=== END ===\n\n{prompt_text()}")
        text, rec = ctx["claude"](prompt, ctx["sandbox"], model=model, label=ctx["label"])
        return text.strip(), [rec]
    return run


COMMON = """You are compacting the context of an AI agent's session on Orchestra (a multi-agent platform). The session journal is in ./journal/: INDEX.md lists chunk_NNN.md files in chronological order; journal.jsonl has one JSON row per event (id, ts, type in user_message/text/tool/tool_result, tool, error, content) for python/grep. USER rows are messages from the owner, the orchestrator, other agents or the platform; ASSISTANT rows are the agent. Tool calls/results are truncated.

Goal: ./summary.md — the handoff that REPLACES the whole context. After compaction the agent sees only summary.md plus the last ~12K chars of dialogue verbatim; whatever is not in summary.md is forgotten for good. The agent must be able to continue the work without violating anything the owner/orchestrator said.

What must survive (final state, not history): the current task(s) and status; every still-relevant instruction/requirement given to the agent — quote its key wording verbatim with who said it; decisions, approvals, rejections and reversals (final state + one-line reason); exact paths, branches, commits, URLs, task ids, worker/agent names; measured numbers and ids that later work depends on; active bans/constraints; open items, promises, blockers and the next action. Drop raw tool output, superseded states, chit-chat, process narration. Never write credentials (tokens, keys, passwords, secret URLs) — write <secret>. Do not invent: if unsure, say UNKNOWN.

Use the session's working language. Structure summary.md with sections: TASK STATE / OWNER & USER REQUIREMENTS (verbatim) / DECISIONS / FILES, IDS AND ARTIFACTS / NUMBERS / CONSTRAINTS AND BANS / PEOPLE AND AGENTS / OPEN ITEMS AND NEXT ACTION.
"""

SEQ_P1 = COMMON + """
This is pass 1 of 3 — DRAFT. Read every chunk listed in journal/INDEX.md in order, completely. After each chunk (or two), update summary.md with Write/Edit — build the file incrementally, do not hold everything in your head. Later chunks may reverse earlier facts: edit the file, don't append contradictions. When done, reply "draft done"."""

AUDIT = COMMON + """
This is pass {n} — AUDIT. summary.md is a draft written by a previous pass that may have missed or distorted facts. Verify and complete it against the journal with python over journal/journal.jsonl and grep, systematically:
1. Print every user_message (python; shorten long platform notices) and check that each still-relevant instruction, decision, ban and number in them is in summary.md — requirement wording verbatim.
2. Grep the journal for paths, commit hashes, task ids (e.g. #V-123, V-123, #123), URLs, numbers with units, and ban words (нельзя, не делай, запрещ, никогда, только, NEVER, do not, don't) — add what matters for continuing.
3. Check each status in summary.md is FINAL: a later message may have changed it. Fix outdated statements.
4. Read the last chunk fully: in-flight work, promises, open items and the next action must be exact.
Edit summary.md in place. Reply "audit done"."""

FINAL = COMMON + """
This is the last pass — FINALIZE. Make summary.md a clean handoff of at most {cap} characters: merge duplicates, remove what is not needed to continue, keep every verbatim requirement, decision, path, id, number, ban and open item. Do not add facts you have not verified in the journal. Check the size with python (len of the file text) and iterate until it fits. Reply "final done"."""


def _passes(prompts, cap=20000):
    def run(ctx):
        model = session_model(ctx)
        recs = []
        for i, p in enumerate(prompts, 1):
            text, rec = ctx["claude"](p.format(n=i, cap=cap), ctx["sandbox"], model=model,
                                      tools=TOOLS, label=f'{ctx["label"]}:p{i}')
            recs.append(rec)
        f = ctx["sandbox"] / "summary.md"
        return (f.read_text() if f.exists() else ""), recs
    return run


MAP = """You are reading one chunk of an AI agent's session journal (Orchestra multi-agent platform; USER = owner/orchestrator/other agents/platform, ASSISTANT = the agent). Extract NOTES that another pass will merge into a handoff summary replacing the agent's whole memory.

Write notes as terse bullet lines, each tagged: [REQ] instruction/requirement given to the agent (quote key wording verbatim, say who), [DEC] decision/approval/rejection/reversal, [PATH] exact paths/branches/commits/URLs/task ids/agent names with what they are, [NUM] measured values/ids/limits, [BAN] constraints and "do not" rules, [STATE] status of work at the end of this chunk, [OPEN] promises, unfinished work, blockers, next steps. Include the log id (#NNN) at the end of each line. Skip raw tool output, chit-chat and process narration unless it yields one of the above. Never copy credentials — write <secret>.

Output only the notes.

=== CHUNK {i} of {n} ===
{chunk}
=== END ==="""

REDUCE = COMMON + """
This is pass {n} — MERGE. ./notes/ holds per-chunk notes (notes_001.md … in chronological order) extracted from the journal by earlier passes; each line ends with its log id. Write summary.md from them: read all notes files, resolve later-overrides-earlier (final state wins), keep verbatim requirement wording, and check anything ambiguous against journal/journal.jsonl by id (python) or grep. Reply "merge done"."""


def _mapreduce(prompts, cap=20000, workers=4):
    def run(ctx):
        model = map_model = session_model(ctx)
        from concurrent.futures import ThreadPoolExecutor
        sbx = ctx["sandbox"]
        chunks = sorted((sbx / "journal").glob("chunk_*.md"))
        (sbx / "notes").mkdir(exist_ok=True)

        def one(i, path):
            text, rec = ctx["claude"](MAP.format(i=i, n=len(chunks), chunk=path.read_text()), sbx / f"map{i}",
                                      model=map_model, label=f'{ctx["label"]}:map{i}')
            (sbx / "notes" / f"notes_{i:03d}.md").write_text(text)
            return rec

        with ThreadPoolExecutor(workers) as ex:
            recs = list(ex.map(lambda a: one(*a), enumerate(chunks, 1)))
        for i, p in enumerate(prompts, 2):
            text, rec = ctx["claude"](p.format(n=i, cap=cap), sbx, model=model, tools=TOOLS,
                                      label=f'{ctx["label"]}:p{i}')
            recs.append(rec)
        f = sbx / "summary.md"
        return (f.read_text() if f.exists() else ""), recs
    return run


def _hybrid(prompts, base="oneshot", cap=20000):
    """Черновик — готовая одноходовая сводка того же кейса; дальше агентные проходы по журналу.
    Стоимость черновика добавляется из его compress.json, чтобы цена была полной."""
    def run(ctx):
        model = session_model(ctx)
        runs = ctx["sandbox"].parents[2]
        case = ctx["case_dir"].name
        (ctx["sandbox"] / "summary.md").write_text((runs / base / case / "summary.md").read_text())
        draft = json.loads((runs / base / case / "compress.json").read_text())
        recs = [dict(label=f"{base}-draft", cost=draft["cost"], sec=draft["sec"])]
        for i, p in enumerate(prompts, 2):
            text, rec = ctx["claude"](p.format(n=i, cap=cap), ctx["sandbox"], model=model,
                                      tools=TOOLS, label=f'{ctx["label"]}:p{i}')
            recs.append(rec)
        return (ctx["sandbox"] / "summary.md").read_text(), recs
    return run


METHODS = {
    "oneshot": _oneshot(lambda: COMPACT_PROMPT.read_text()),
    "seq3": _passes([SEQ_P1, AUDIT, FINAL]),
    "mapred3": _mapreduce([REDUCE, AUDIT, FINAL]),
    "hybrid": _hybrid([AUDIT, FINAL]),
}
