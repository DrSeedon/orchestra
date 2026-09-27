"""V-649: in-session audit on forks of the original precompact Claude CLI sessions."""
from __future__ import annotations

import datetime as dt
import json
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PRIVATE = ROOT / "data" / "v649"
DB = Path("/home/kesha/orchestra/data/orchestra.db")
CASES = {
    "Orchestra-orchestrator-427977": 427977,
    "seo-cro-435842": 435842,
    "oge-russkiy-425581": 425581,
    "University-orchestrator-403387": 403387,
    "katya-work-orchestrator-441732": 441732,
    "cog-second-brain-orchestrator-421326": 421326,
    "designer-447804": 447804,
    "bizdev-390824": 390824,
    "slipways-437565": 437565,
}
KEEP = ("user_message", "text", "tool", "tool_result")
TOOLS = "Read,Grep,Glob,Bash"
ALLOWED = "Read,Grep,Glob,Bash(python *)"
USD_PER_M = {
    # Fitted to isolated Claude CLI calls in V-643/results/ledger.jsonl.
    "claude-opus-5-5[1m]": (8.0, 0.2, 20.0, 4.0),
    "claude-sonnet-5[1m]": (4.0, 0.2, 10.0, 2.0),
}


def token_cost(model, usage):
    rates = USD_PER_M[model]
    keys = ("cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens", "input_tokens")
    return sum(rate * usage.get(key, 0) / 1_000_000 for rate, key in zip(rates, keys))


def render(rows, *, tool_in=2000, tool_out=4000, user_cap=10**9):
    out = []
    for lid, ts, typ, content, tool, is_err in rows:
        head = f"[#{lid} {ts[:16]}]"
        if typ == "user_message":
            c = content if len(content) <= user_cap else content[:user_cap] + "…"
            out.append(f"{head} USER:\n{c}")
        elif typ == "text":
            out.append(f"{head} ASSISTANT:\n{content}")
        elif typ == "tool":
            c = content[:tool_in] + ("…" if len(content) > tool_in else "")
            out.append(f"{head} TOOL_CALL {tool or ''}: {c}")
        elif typ == "tool_result":
            c = content[:tool_out] + (f"…[+{len(content)-tool_out}]" if len(content) > tool_out else "")
            out.append(f"{head} TOOL_RESULT{' (error)' if is_err else ''}: {c}")
    return "\n\n".join(out)


def split_preamble(content):
    body = content.split("\n\n", 1)[1] if "\n\n" in content else content
    summary, _, rest = body.partition("[END OF SUMMARY]")
    m = re.search(r"\[VERBATIM TAIL[^\]]*\]\n\n(.*?)\n\n\[END OF TAIL\]", rest, re.S)
    return summary.strip(), (m.group(1) if m else "")


def db_conn():
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=5)
    c.execute("BEGIN")
    return c


def prepare(case):
    c = db_conn()
    try:
        cid = CASES[case]
        sid, name, scope, model, cwd, history = c.execute(
            """select s.id,s.name,s.scope,s.model,s.cwd,s.session_id_history
               from logs l join sessions s on s.id=l.session_id where l.id=?""", (cid,)
        ).fetchone()
        row = c.execute("select ts,content from logs where id=?", (cid,)).fetchone()
        ts, content = row
        prev = c.execute(
            "select coalesce(max(id),0) from logs where session_id=? and id<? and type='user_message' and content like '[PREVIOUS CONTEXT SUMMARY%'",
            (sid, cid),
        ).fetchone()[0]
        rows = c.execute(
            f"select id,ts,type,content,tool_name,tool_is_error from logs where session_id=? and id>=? and id<? and type in ({','.join('?' * len(KEEP))}) order by id",
            (sid, prev, cid, *KEEP),
        ).fetchall()
        compact_time = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        events = [x for x in json.loads(history or "[]") if x.get("compacted_at")]
        event = min(events, key=lambda x: abs((dt.datetime.fromisoformat(x["compacted_at"]) - compact_time).total_seconds()))
        source_sid = event["session_id"]
    finally:
        c.close()

    history_files = list((Path.home() / ".claude/projects").glob(f"*/{source_sid}.jsonl"))
    if len(history_files) != 1:
        raise RuntimeError(f"{case}: expected one saved source session, got {len(history_files)}")
    if abs((dt.datetime.fromisoformat(event["compacted_at"]) - compact_time).total_seconds()) > 120:
        raise RuntimeError(f"{case}: no matching compaction boundary in session history")
    src = history_files[0]
    if not Path(cwd).is_dir():
        raise RuntimeError(f"{case}: original cwd is missing")

    out = PRIVATE / "cases" / case
    (out / "journal").mkdir(parents=True, exist_ok=True)
    full = render(rows)
    parts, cur, size = [], [], 0
    for part in full.split("\n\n[#"):
        cur.append(part)
        size += len(part)
        if size > 60000:
            parts.append(cur)
            cur, size = [], 0
    if cur:
        parts.append(cur)
    idx = []
    for i, chunk in enumerate(parts, 1):
        text = "\n\n[#".join(chunk)
        if i > 1:
            text = "[#" + text
        p = out / "journal" / f"chunk_{i:03d}.md"
        p.write_text(text)
        first = re.search(r"\[#(\d+) ([^\]]+)\]", text)
        idx.append(f"{p.name}\t{len(text)} chars\tfrom {first.group(1) if first else '?'}")
    (out / "journal" / "INDEX.md").write_text("\n".join(idx) + "\n")
    with (out / "journal" / "journal.jsonl").open("w") as f:
        for lid, row_ts, typ, row_content, tool, is_err in rows:
            f.write(json.dumps(dict(id=lid, ts=row_ts, type=typ, tool=tool,
                                    error=bool(is_err), content=row_content[:20000]), ensure_ascii=False) + "\n")
    real, tail = split_preamble(content)
    (out / "summary.md").write_text(real)
    (out / "tail.md").write_text(tail)
    meta = dict(case=case, compact_log_id=cid, compact_ts=ts, role=name, scope=scope, model=model,
                source_session_id=source_sid, source_session_file=str(src), source_session_bytes=src.stat().st_size,
                original_cwd=cwd, rows=len(rows), transcript_chars=len(render(rows)), chunks=len(parts),
                summary_chars=len(real), tail_chars=len(tail))
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    return meta


def prompt_for(case, stage):
    d = PRIVATE / "cases" / case
    journal = d / "journal"
    summary = d / "summary.md"
    cap = 20000
    if stage == "audit":
        return f"""This is pass 2 — AUDIT. The current production compact summary is the latest assistant message in this conversation. It is a draft and may have missed or distorted facts. Verify and complete it against the session journal at {journal} with python over {journal / 'journal.jsonl'} and grep, systematically:
1. Print every user_message (python; shorten long platform notices) and check that each still-relevant instruction, decision, ban and number in the summary is present — requirement wording verbatim.
2. Grep the journal for paths, commit hashes, task ids (e.g. #V-123, V-123, #123), URLs, numbers with units, and ban words (нельзя, не делай, запрещ, никогда, только, NEVER, do not, don't) — add what matters for continuing.
3. Check each status in the summary is FINAL: a later message may have changed it. Fix outdated statements.
4. Read the last chunk fully: in-flight work, promises, open items and the next action must be exact.
The summary file path is {summary}. You may inspect the journal but must not modify files outside {d}. Return the complete audited summary as plain text; do not include credentials (write <secret>).
"""
    return f"""This is the last pass — FINALIZE. Use the audited summary from your previous response and the journal at {journal}. Make a clean handoff of at most {cap} characters: merge duplicates, remove what is not needed to continue, keep every verbatim requirement, decision, path, id, number, ban and open item. Do not add facts you have not verified in the journal. Check the size with python (len of the file text) and iterate until it fits. Never include credentials; write <secret>. Return the complete final summary as plain text.
"""


def invoke(prompt, cwd, model, *, resume=None, fork=False, add_dir=None, no_persist=False, label=""):
    cmd = ["claude", "-p", "--safe-mode", "--model", model, "--strict-mcp-config",
           "--output-format", "json", "--tools", TOOLS, "--allowedTools", ALLOWED]
    if resume:
        cmd += ["--resume", resume]
    if fork:
        cmd += ["--fork-session"]
    if no_persist:
        cmd += ["--no-session-persistence"]
    if add_dir:
        cmd += ["--add-dir", str(add_dir)]
    t0 = time.monotonic()
    p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=cwd, timeout=3600)
    sec = round(time.monotonic() - t0, 1)
    try:
        d = json.loads(p.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"{label}: invalid CLI JSON (rc={p.returncode}): {(p.stdout+p.stderr)[-1000:]}")
    if p.returncode or d.get("is_error"):
        raise RuntimeError(f"{label}: CLI failed rc={p.returncode}: {str(d.get('result'))[-1000:]}")
    rec = dict(label=label, session_id=d.get("session_id"), model=d.get("model"), sec=sec,
               cost=d.get("total_cost_usd", 0), usage=d.get("usage") or {}, turns=d.get("num_turns"),
               result=d.get("result", ""))
    return rec


def compress(case):
    d = PRIVATE / "cases" / case
    if (d / "compress.json").exists() and (d / "in_session_summary.md").exists():
        print(f"skip existing compression {case}", flush=True)
        return
    meta = json.loads((d / "meta.json").read_text()) if (d / "meta.json").exists() else prepare(case)
    records = []
    # The source UUID ends immediately after the actual production summary. Forking
    # preserves that full history while isolating all new turns from the original.
    first = invoke(prompt_for(case, "audit"), meta["original_cwd"], meta["model"], resume=meta["source_session_id"],
                   fork=True, add_dir=d, label=f"audit:{case}")
    records.append(first)
    fork_id = first["session_id"]
    if not fork_id or fork_id == meta["source_session_id"]:
        raise RuntimeError(f"{case}: CLI did not report fork session id")
    second = invoke(prompt_for(case, "final"), meta["original_cwd"], meta["model"], resume=fork_id,
                    add_dir=d, label=f"final:{case}")
    records.append(second)
    summary = second["result"].strip()
    summary = re.sub(r"^```(?:markdown|md|text)?\s*", "", summary)
    summary = re.sub(r"\s*```\s*$", "", summary)
    (d / "in_session_summary.md").write_text(summary + "\n")
    for record in records:
        record["cumulative_session_cost_usd"] = record.pop("cost")
        record["incremental_cost_usd"] = token_cost(meta["model"], record["usage"])
    out = dict(method="in_session", case=case, model=meta["model"], sec=round(sum(r["sec"] for r in records), 1),
               incremental_cost=round(sum(r["incremental_cost_usd"] for r in records), 6),
               incremental_usage={k: sum(r["usage"].get(k, 0) for r in records)
                                  for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")},
               calls=[{k:v for k,v in r.items() if k != "result"} for r in records],
               summary_chars=len(summary), fork_session_id=fork_id)
    (d / "compress.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))
    with (PRIVATE / "ledger.jsonl").open("a") as f:
        f.write(json.dumps(out, ensure_ascii=False) + "\n")
    print(json.dumps({k:v for k,v in out.items() if k != "calls"}, ensure_ascii=False), flush=True)


def run_eval(case):
    # Reuse V-643's exact question set, answer/judge prompts, and tail-only filter.
    sys.path.insert(0, str(ROOT / ".orchestra/tasks/V-643"))
    import bench  # noqa: E402
    d = PRIVATE / "cases" / case
    if (d / "eval/score.json").exists():
        print(f"skip existing evaluation {case}", flush=True)
        return
    summary = (d / "in_session_summary.md").read_text()
    questions = json.loads((ROOT / ".orchestra/tasks/V-643/results/eval" / case / "questions.json").read_text())
    tail = (d / "tail.md").read_text()
    preamble = bench.PREAMBLE.format(summary=summary,
        tail=(f"\n[VERBATIM TAIL — last messages before compaction, unabridged]\n\n{tail}\n\n[END OF TAIL]\n" if tail else ""))
    qtext = "\n".join(f'{q["id"]}: {q["question"]}' for q in questions)
    model = "claude-sonnet-5[1m]"
    eval_dir = d / "eval"
    eval_dir.mkdir(exist_ok=True)
    answers_prompt = bench.ANSWER.format(preamble=preamble, questions=qtext)
    costs_file = eval_dir / "costs.json"
    answers_file, judge_file = eval_dir / "answers.json", eval_dir / "judge.json"
    costs = json.loads(costs_file.read_text()) if costs_file.exists() else []
    answer = costs[0] if costs else None
    if answers_file.exists():
        answers = json.loads(answers_file.read_text())
    else:
        answer = invoke(answers_prompt, eval_dir, model, no_persist=True, label=f"answer:{case}")
        answers = bench.parse_json(answer["result"])
        answers_file.write_text(json.dumps(answers, ensure_ascii=False, indent=1))
    items = "\n\n".join(
        f'{q["id"]}\nQ: {q["question"]}\nGOLD: {q["gold"]}\nMUST_CONTAIN: {q.get("must_contain")}\nANSWER: {answers.get(q["id"], "UNKNOWN")}'
        for q in questions)
    judge = costs[1] if len(costs) > 1 else None
    if judge_file.exists():
        verdict = json.loads(judge_file.read_text())
    else:
        judge = invoke(bench.JUDGE.format(items=items), eval_dir, model, no_persist=True, label=f"judge:{case}")
        verdict = bench.parse_json(judge["result"])
        judge_file.write_text(json.dumps(verdict, ensure_ascii=False, indent=1))
    if answer and judge and not costs_file.exists():
        costs_file.write_text(json.dumps([answer, judge], ensure_ascii=False, indent=2))
    # Same question exclusions and importance-weighted scoring as bench.score().
    tail_judge = json.loads((ROOT / ".orchestra/tasks/V-643/results/runs/tailonly" / case / "judge.json").read_text())
    easy = {qid for qid, verdict in tail_judge.items() if verdict.get("score", 0) >= 0.5}
    score, wrong = 0, 0
    weight = 0
    for q in questions:
        if q["id"] in easy:
            continue
        v = verdict.get(q["id"], {}).get("score", 0)
        importance = q.get("importance", 2)
        score += max(v, 0) * importance
        weight += importance
        wrong += v < 0
    result = dict(case=case, score=score / weight if weight else 0, wrong=wrong,
                  kept_questions=len(questions)-len(easy), evaluation_cost=answer["cost"]+judge["cost"],
                  evaluation_sec=answer["sec"]+judge["sec"],
                  usage={k: answer["usage"].get(k,0)+judge["usage"].get(k,0)
                         for k in ("input_tokens","cache_creation_input_tokens","cache_read_input_tokens","output_tokens")})
    (eval_dir / "score.json").write_text(json.dumps(result, indent=2))
    with (PRIVATE / "eval_ledger.jsonl").open("a") as f:
        f.write(json.dumps(result) + "\n")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    command, *cases = sys.argv[1:]
    if command == "prepare":
        for case in cases:
            print(json.dumps(prepare(case), ensure_ascii=False), flush=True)
    elif command == "compress":
        for case in cases:
            compress(case)
    elif command == "eval":
        for case in cases:
            run_eval(case)
    elif command == "pilot":
        for case in cases:
            compress(case)
            run_eval(case)
    else:
        raise SystemExit("usage: measure.py prepare|compress|eval <case>...")
