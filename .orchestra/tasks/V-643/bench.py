"""V-643: стенд сравнения одноходового компакта и агентного сжатия.

    python bench.py qgen <case>..                 вопросы+эталон из журнала (сжимающий их не видит)
    python bench.py compress <method> <case>..    построить сводку методом
    python bench.py eval <method> <case>..        свежая модель отвечает по сводке+хвосту, судья оценивает
    python bench.py table [case..]                сводная таблица

Все вызовы — `claude -p` на подписке, в песочнице data/v643/runs/…, без MCP и без
пользовательских настроек (--safe-mode). Стоимость — total_cost_usd из ответа CLI
(API-эквивалент), пишется в ledger.jsonl.
"""
import json
import re
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import methods  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / "data" / "v643"
CASES = BASE / "cases"
EVAL = BASE / "eval"
RUNS = BASE / "runs"
LEDGER = BASE / "ledger.jsonl"
PREAMBLE = (
    "[PREVIOUS CONTEXT SUMMARY — context was compacted]\n\n{summary}\n\n"
    "[END OF SUMMARY]\n{tail}[CONTINUE NATURALLY]\n\n"
)
_lock = threading.Lock()


def claude(prompt, cwd, *, model="sonnet", tools="", label="", timeout=3600):
    cwd = Path(cwd)
    cwd.mkdir(parents=True, exist_ok=True)
    cmd = ["claude", "-p", "--safe-mode", "--model", model, "--strict-mcp-config",
           "--no-session-persistence", "--output-format", "json", "--tools", tools]
    if tools:
        cmd += ["--allowedTools", tools, "--permission-mode", "acceptEdits"]
    for attempt in range(3):
        t0 = time.time()
        p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=cwd, timeout=timeout)
        dt = time.time() - t0
        try:
            d = json.loads(p.stdout)
        except json.JSONDecodeError:
            d = {"is_error": True, "result": (p.stdout + p.stderr)[-2000:]}
        rec = dict(label=label, model=model, attempt=attempt, sec=round(dt, 1),
                   cost=d.get("total_cost_usd", 0), turns=d.get("num_turns"),
                   usage={k: v for k, v in (d.get("usage") or {}).items() if k.endswith("tokens")},
                   error=bool(d.get("is_error")) or p.returncode != 0)
        with _lock, open(LEDGER, "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        if not rec["error"]:
            return d.get("result", ""), rec
        print(f"[{label}] attempt {attempt} failed: {str(d.get('result'))[:300]}", flush=True)
        time.sleep(20)
    raise RuntimeError(f"{label}: claude failed")


def claude_json(prompt, cwd, **kw):
    """Модель иногда ломает JSON (неэкранированные кавычки) — повторяем вызов."""
    for attempt in range(3):
        text, rec = claude(prompt, cwd, **kw)
        try:
            return parse_json(text), rec
        except (json.JSONDecodeError, ValueError):
            print(f"[{kw.get('label')}] bad JSON, retry {attempt}", flush=True)
    raise RuntimeError(f"{kw.get('label')}: no valid JSON")


def parse_json(text):
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    body = m.group(1) if m else text[text.find("[") if text.find("[") >= 0 else 0:]
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return json.loads(text[text.find("{"): text.rfind("}") + 1])


# ---------- вопросы ----------

QGEN = """You are building an exam that measures whether an AI agent can continue its work after its context was compacted.

Below is the COMPACTED PART of the agent's session journal (Orchestra multi-agent platform; USER = the owner, the orchestrator or other agents/platform messages; ASSISTANT = the agent; tool calls and results are truncated). After compaction the agent will see only a summary plus the VERBATIM TAIL shown at the end. The summary is written by someone else; you do not see it.

Write exactly {n} questions whose answers the agent NEEDS to continue working correctly, drawn from the compacted part. Categories (spread roughly evenly):
- owner_decision: a decision/choice/approval/rejection made by the owner or the orchestrator, including reversals (ask about the FINAL state)
- user_verbatim: the exact wording of an instruction/requirement given to the agent (gold = the key phrase, quoted)
- path: exact file path, branch, commit hash, URL, task id or artifact name
- open_item: work not finished / promised / blocked / next step as of the END of the part
- number: a measured value, count, price, limit, percentage, id
- prohibition: an active ban, constraint or "do not" rule

Rules:
- Each question must be answerable from the compacted part with a short, checkable gold answer (one line; list the key tokens that must appear).
- NOT answerable from the VERBATIM TAIL alone — the examinee sees the tail. Skip facts restated in the tail.
- The fact must still matter at the end of the part (no superseded states unless asking what replaced them). No trivia (timestamps, wording of chit-chat, tool mechanics).
- Questions must be self-contained and unambiguous for someone who has only a summary of this session; do not say "in log #123".
- importance: 3 = acting without it causes a wrong action or violates the owner's will; 2 = useful; 1 = nice to know.

Output ONLY a JSON array in a ```json block: [{{"id": "q1", "category": "...", "question": "...", "gold": "...", "must_contain": ["..."], "importance": 3, "evidence_log_ids": [123]}}]

=== COMPACTED PART ===
{transcript}
=== END OF COMPACTED PART ===

=== VERBATIM TAIL (visible to the examinee) ===
{tail}
=== END OF TAIL ===
"""


def qgen(case, n=20):
    d = CASES / case
    out = EVAL / case / "questions.json"
    if out.exists():
        return
    prompt = QGEN.format(n=n, transcript=(d / "transcript.md").read_text(), tail=(d / "tail.md").read_text())
    qs, rec = claude_json(prompt, EVAL / case / "work", label=f"qgen:{case}")
    out.write_text(json.dumps(qs, ensure_ascii=False, indent=1))
    print(f"qgen {case}: {len(qs)} q, ${rec['cost']:.3f}", flush=True)


# ---------- сжатие ----------

def compress(method, case):
    run = RUNS / method / case
    if (run / "summary.md").exists():
        return
    d = CASES / case
    if run.exists():
        shutil.rmtree(run)
    run.mkdir(parents=True)
    t0 = time.time()
    cost = 0.0
    calls = []
    if method == "real":
        (run / "summary.md").write_text((d / "real_summary.md").read_text())
    elif method == "tailonly":
        (run / "summary.md").write_text("")
    else:
        spec = methods.METHODS[method]
        sbx = run / "sandbox"
        shutil.copytree(d / "journal", sbx / "journal")
        summary, calls = spec(ctx=dict(case_dir=d, sandbox=sbx, claude=claude, label=f"{method}:{case}"))
        (run / "summary.md").write_text(summary)
        cost = sum(c["cost"] for c in calls)
    meta = dict(method=method, case=case, sec=round(time.time() - t0, 1), cost=round(cost, 4),
                calls=len(calls), summary_chars=len((run / "summary.md").read_text()))
    (run / "compress.json").write_text(json.dumps(meta, indent=1))
    print(f"compress {method} {case}: {meta}", flush=True)


# ---------- оценка ----------

ANSWER = """{preamble}[EVALUATION — not a real task]
You are the agent whose context was just compacted; the text above is everything you remember about your work so far. Answer each question below using ONLY that text. If the text does not let you determine the answer, answer exactly "UNKNOWN" — a wrong confident answer is worse than UNKNOWN. Keep answers short (one line), quote exact paths/ids/wording.

Questions:
{questions}

Output ONLY a JSON object in a ```json block: {{"q1": "answer", ...}}"""

JUDGE = """Grade an examinee's answers against gold answers. For each item output a score:
- 1: the answer states the gold fact (all must_contain key facts present, allowing paraphrase/translation; exact tokens like paths, hashes, numbers must match)
- 0.5: partially correct (some key facts, or correct but notably less specific)
- 0: UNKNOWN / missing
- -1: WRONG — contradicts gold or asserts a different fact
Be strict about paths, numbers, ids; lenient about language and phrasing.

Items:
{items}

Output ONLY a JSON object in a ```json block: {{"q1": {{"score": 1, "why": "few words"}}, ...}}"""


def evaluate(method, case):
    run = RUNS / method / case
    if (run / "judge.json").exists():
        return
    qs = json.loads((EVAL / case / "questions.json").read_text())
    tail = (CASES / case / "tail.md").read_text()
    summary = (run / "summary.md").read_text()
    preamble = PREAMBLE.format(
        summary=summary or "(summary unavailable)",
        tail=(f"\n[VERBATIM TAIL — last messages before compaction, unabridged]\n\n{tail}\n\n[END OF TAIL]\n" if tail else ""),
    )
    qtext = "\n".join(f'{q["id"]}: {q["question"]}' for q in qs)
    answers, rec_a = claude_json(ANSWER.format(preamble=preamble, questions=qtext), run / "work",
                                 label=f"answer:{method}:{case}")
    (run / "answers.json").write_text(json.dumps(answers, ensure_ascii=False, indent=1))
    items = "\n\n".join(
        f'{q["id"]}\nQ: {q["question"]}\nGOLD: {q["gold"]}\nMUST_CONTAIN: {q.get("must_contain")}\nANSWER: {answers.get(q["id"], "UNKNOWN")}'
        for q in qs)
    verdict, rec_j = claude_json(JUDGE.format(items=items), run / "work", label=f"judge:{method}:{case}")
    (run / "judge.json").write_text(json.dumps(verdict, ensure_ascii=False, indent=1))
    print(f"eval {method} {case}: ${rec_a['cost'] + rec_j['cost']:.3f}", flush=True)


def score(method, case, drop=frozenset()):
    run = RUNS / method / case
    qs = json.loads((EVAL / case / "questions.json").read_text())
    j = json.loads((run / "judge.json").read_text())
    s = w = wrong = 0
    for q in qs:
        if q["id"] in drop:
            continue
        v = j.get(q["id"], {}).get("score", 0)
        imp = q.get("importance", 2)
        s += max(v, 0) * imp
        w += imp
        wrong += v < 0
    return s / w if w else 0, wrong


def easy_ids(case):
    """Вопросы, на которые отвечает один хвост без сводки — шум, из метрики выкидываем."""
    j = json.loads((RUNS / "tailonly" / case / "judge.json").read_text())
    return frozenset(k for k, v in j.items() if v.get("score", 0) >= 0.5)


def table(cases):
    ms = sorted(p.name for p in RUNS.iterdir() if p.is_dir())
    print("method\t" + "\t".join(c[:18] for c in cases) + "\tmean\twrong\tchars\t$compress\tsec")
    for m in ms:
        row, wr, ch, co, se = [], 0, [], [], []
        for c in cases:
            r = RUNS / m / c
            if not (r / "judge.json").exists():
                row.append(None); continue
            acc, wrong = score(m, c, easy_ids(c))
            row.append(acc); wr += wrong
            meta = json.loads((r / "compress.json").read_text())
            ch.append(meta["summary_chars"]); co.append(meta["cost"]); se.append(meta["sec"])
        got = [x for x in row if x is not None]
        if not got:
            continue
        mean = sum(got) / len(got)
        print(f"{m}\t" + "\t".join("-" if x is None else f"{x:.2f}" for x in row)
              + f"\t{mean:.3f}\t{wr}\t{sum(ch)//len(ch)}\t{sum(co)/len(co):.2f}\t{sum(se)/len(se):.0f}")


def pmap(fn, items, workers=4):
    with ThreadPoolExecutor(workers) as ex:
        for f in [ex.submit(fn, *i) for i in items]:
            try:
                f.result()
            except Exception as e:  # один кейс не валит остальные
                print("FAILED", e, flush=True)


if __name__ == "__main__":
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == "qgen":
        pmap(qgen, [(c,) for c in args])
    elif cmd == "compress":
        pmap(compress, [(args[0], c) for c in args[1:]])
    elif cmd == "eval":
        pmap(evaluate, [(args[0], c) for c in args[1:]])
    elif cmd == "run":  # compress + eval
        pmap(lambda m, c: (compress(m, c), evaluate(m, c)), [(args[0], c) for c in args[1:]])
    elif cmd == "table":
        table(args or sorted(p.name for p in EVAL.iterdir()))
