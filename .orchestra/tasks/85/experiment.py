#!/usr/bin/env python3
"""Experiment #85 — can Haiku extract actionable rules from user corrections?

Read-only over Orchestra's logs DB. Calls claude-haiku-4-5 via claude-agent-sdk
through HTTPS_PROXY=http://127.0.0.1:12340.

Run:
    HTTPS_PROXY=http://127.0.0.1:12340 uv run python docs/tasks/85/experiment.py

Outputs JSON to docs/experiments/85/results.json (consumed by the report).
"""
import asyncio
import json
import os
import re
import sqlite3
import time
from pathlib import Path

DB = "/mnt/data/Projects/Python/orchestra/data/orchestra.db"
OUT = Path("/mnt/data/Projects/Python/orchestra/docs/experiments/85/results.json")

# --- regex gate -------------------------------------------------------------
# Coarse "this is a correction" detector. Intentionally simple — that's the point.
CORRECTION_PATTERNS = [
    r"\bхуйн\w*", r"\bхуит\w*", r"\bхуёв\w*", r"\bхуев\w*",
    r"не так\b", r"\bпеределай", r"\bпереписать\b", r"\bперепиши\b",
    r"неправильн\w*", r"\bеблан\w*", r"\bдебил\w*", r"\bдура\b", r"\bтупо?й?\b",
    r"делегир\w*", r"сам не делай", r"не сам", r"не\s+ты\s+делай",
    r"\bне надо\b", r"\bзачем ты\b", r"нахуя ты", r"кто тебя просил",
    r"я (?:же |ведь )?(?:сказал|просил|говорил)", r"\bне то\b",
    r"\bошиб\w*", r"\bфигн\w*", r"\bхрень\b", r"\bбред\b",
    r"^нет[ ,.!]", r"\bнет,? ", r"\bне нужно\b", r"\bне нужн\w*",
]
GATE_RE = re.compile("|".join(CORRECTION_PATTERNS), re.IGNORECASE | re.MULTILINE)

# Profanity alone is NOT correction (e.g. "блять круто получилось"). Require a
# negative/imperative cue. We keep the gate deliberately loose then measure FP.


def strip_prefix(s: str) -> str:
    # logs store "[HH:MM] ..." or "[from ...] ..." prefixes
    return re.sub(r"^\[[^\]]*\]\s*", "", s).strip()


def is_correction(text: str) -> bool:
    t = strip_prefix(text)
    if len(t) < 4:
        return False
    return bool(GATE_RE.search(t))


# --- dataset build ----------------------------------------------------------
def build_pairs():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT id, session_id, ts, content FROM logs WHERE type='user_message' ORDER BY id"
    ).fetchall()

    gate_pos = []
    for r in rows:
        if is_correction(r["content"]):
            gate_pos.append(r)

    pairs = []
    for r in gate_pos:
        prev = con.execute(
            "SELECT content FROM logs WHERE session_id=? AND type='text' AND id<? "
            "ORDER BY id DESC LIMIT 1",
            (r["session_id"], r["id"]),
        ).fetchone()
        if not prev:
            continue
        agent_out = strip_prefix(prev["content"]).strip()
        corr = strip_prefix(r["content"]).strip()
        if len(agent_out) < 20 or len(corr) < 6:
            continue
        pairs.append({
            "log_id": r["id"],
            "session_id": r["session_id"],
            "source": "real",
            "agent_output": agent_out[:1800],
            "correction": corr[:1200],
        })
    con.close()
    return rows, gate_pos, pairs


# --- synthetic top-up (labelled) --------------------------------------------
SYNTHETIC = [
    {
        "source": "synthetic", "log_id": None, "session_id": None,
        "agent_output": "Я сам напишу парсер для всех 200 страниц и прогоню локально, "
                        "потом покажу результат.",
        "correction": "нет, ты сам не делай парсинг — заспавни воркера и делегируй ему, "
                      "твоя задача координировать а не кодить",
    },
    {
        "source": "synthetic", "log_id": None, "session_id": None,
        "agent_output": "Готово, добавил кнопку «Удалить» которая сразу стирает запись "
                        "без подтверждения.",
        "correction": "переделай, удаление должно спрашивать подтверждение, "
                      "а то снесут случайно всё",
    },
    {
        "source": "synthetic", "log_id": None, "session_id": None,
        "agent_output": "ВерсПрог=\"Claude AI 1.0\" — выставил версию ПО в XML отчёте.",
        "correction": "ты еблан, нахуя ты это писал, в ВерсПрог должно быть название "
                      "реальной бухгалтерской программы, а не Claude AI",
    },
    {
        "source": "synthetic", "log_id": None, "session_id": None,
        "agent_output": "Заодно отрефакторил соседний модуль auth.py и переименовал "
                        "пару функций, раз уж был там.",
        "correction": "кто тебя просил трогать auth.py? делай только то что я сказал, "
                      "не лезь в чужой код",
    },
    {
        "source": "synthetic", "log_id": None, "session_id": None,
        "agent_output": "Сумму взносов на травматизм взял 0.2% — это стандартная ставка.",
        "correction": "не угадывай ставку, погугли реальный тариф по нашему ОКВЭД, "
                      "я не буду платить в воздух",
    },
]


# --- Haiku extraction -------------------------------------------------------
EXTRACT_PROMPT = """Ты анализируешь пару: что сделал AI-агент и как его поправил пользователь.
Извлеки ОДНО конкретное правило на будущее.

AGENT_OUTPUT:
{agent}

USER_CORRECTION:
{corr}

Верни СТРОГО JSON (без markdown, без ```):
{{"trigger": "когда это применимо (конкретно)",
  "action": "что делать",
  "avoid": "чего НЕ делать",
  "category": "delegation|revision|style|factual|scope|process",
  "confidence": 0.0-1.0}}

Если коррекция — разовая мелочь без обобщаемого правила, верни ровно: null
Отвечай ТОЛЬКО JSON или null."""


def parse_json(text: str):
    t = text.strip()
    if t.lower() == "null" or t == "":
        return None, "null"
    t = re.sub(r"^```(?:json)?|```$", "", t.strip(), flags=re.MULTILINE).strip()
    m = re.search(r"\{.*\}", t, re.DOTALL)
    if not m:
        if "null" in t.lower():
            return None, "null"
        return None, "parse_error:" + t[:120]
    try:
        return json.loads(m.group(0)), "ok"
    except Exception as e:
        return None, f"parse_error:{e}:{m.group(0)[:120]}"


async def call_haiku(client_cls, options, agent, corr):
    import claude_agent_sdk as s
    out = ""
    async with client_cls(options=options) as c:
        await c.query(EXTRACT_PROMPT.format(agent=agent[:1800], corr=corr[:1200]))
        async for m in c.receive_response():
            if isinstance(m, s.AssistantMessage):
                for b in m.content:
                    if hasattr(b, "text"):
                        out += b.text
    return out.strip()


CKPT = Path("/mnt/data/Projects/Python/orchestra/docs/experiments/85/results.jsonl")


def pair_key(p):
    import hashlib
    # md5 not hash(): hash() is salted per-process (PYTHONHASHSEED) → no resume across restarts
    h = hashlib.md5(p["correction"].encode()).hexdigest()[:8]
    return f"{p['source']}:{p['log_id']}:{h}"


def load_done():
    done = {}
    if CKPT.exists():
        for line in CKPT.read_text().splitlines():
            if line.strip():
                e = json.loads(line)
                done[e["_key"]] = e
    return done


async def run_extraction(pairs, runs=2):
    import claude_agent_sdk as s
    options = s.ClaudeAgentOptions(model="claude-haiku-4-5", max_turns=1, allowed_tools=[])
    done = load_done()
    results = []
    for i, p in enumerate(pairs):
        key = pair_key(p)
        if key in done:  # resume: skip already-computed pairs across restarts
            results.append(done[key])
            print(f"[{i+1}/{len(pairs)}] {p['source']} log_id={p['log_id']} CACHED", flush=True)
            continue
        entry = {**p, "_key": key, "runs": []}
        for run in range(runs):
            t0 = time.time()
            try:
                raw = await call_haiku(s.ClaudeSDKClient, options, p["agent_output"], p["correction"])
                obj, status = parse_json(raw)
            except Exception as e:
                raw, obj, status = f"ERROR:{e}", None, f"call_error:{e}"
            entry["runs"].append({
                "run": run, "raw": raw[:600], "parsed": obj,
                "status": status, "latency_s": round(time.time() - t0, 1),
            })
        results.append(entry)
        with CKPT.open("a") as f:  # append-as-you-go: restart-safe
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        print(f"[{i+1}/{len(pairs)}] {p['source']} log_id={p['log_id']} "
              f"r0={entry['runs'][0]['status']}", flush=True)
    return results


# --- gate audit (precision/recall) ------------------------------------------
def gate_audit(rows, gate_pos, sample_neg=60, seed=42):
    """Build a labelling sample. Manual labels are filled in the report; here we
    emit the sample so the gate metrics are reproducible."""
    import random
    rnd = random.Random(seed)
    pos_ids = {r["id"] for r in gate_pos}
    negs = [r for r in rows if r["id"] not in pos_ids]
    neg_sample = rnd.sample(negs, min(sample_neg, len(negs)))
    audit = []
    for r in gate_pos:
        audit.append({"id": r["id"], "gate": 1, "text": strip_prefix(r["content"])[:200]})
    for r in neg_sample:
        audit.append({"id": r["id"], "gate": 0, "text": strip_prefix(r["content"])[:200]})
    return audit


SAMPLE_N = int(os.environ.get("EXP85_SAMPLE", "30"))


def sample_pairs(pairs, n, seed=42):
    """Deterministic, session-spread sample so we don't burn 220*2 calls."""
    import random
    if len(pairs) <= n:
        return pairs
    rnd = random.Random(seed)
    # bucket by session, round-robin to spread across sessions, then trim
    by_sess = {}
    for p in pairs:
        by_sess.setdefault(p["session_id"], []).append(p)
    for v in by_sess.values():
        rnd.shuffle(v)
    out, sessions = [], list(by_sess.values())
    rnd.shuffle(sessions)
    i = 0
    while len(out) < n:
        bucket = sessions[i % len(sessions)]
        if bucket:
            out.append(bucket.pop())
        i += 1
        if all(not b for b in sessions):
            break
    return out[:n]


async def main():
    rows, gate_pos, pairs = build_pairs()
    print(f"user_messages={len(rows)} gate_positive={len(gate_pos)} usable_pairs={len(pairs)}")

    real_sample = sample_pairs(pairs, SAMPLE_N)
    print(f"sampled {len(real_sample)} real pairs (cap={SAMPLE_N}) + {len(SYNTHETIC)} synthetic")
    # synthetic included to exercise null/category variety; scored separately in report
    all_pairs = real_sample + SYNTHETIC

    results = await run_extraction(all_pairs, runs=2)
    audit = gate_audit(rows, gate_pos)

    OUT.write_text(json.dumps({
        "summary": {
            "user_messages": len(rows),
            "gate_positive": len(gate_pos),
            "usable_real_pairs": len(pairs),
            "sampled_real_pairs": len(real_sample),
            "synthetic_pairs": len(SYNTHETIC),
        },
        "audit_sample": audit,
        "results": results,
    }, ensure_ascii=False, indent=2))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
