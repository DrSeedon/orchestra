"""V-961: дрейф фактов при цепочке компакций (стенд на основе V-643).

    python stand.py prep                      выгрузить 5 кейсов (сегменты, хвосты, посаженные факты, вопросы)
    python stand.py chain <arm> <case> <k0> <k1>   шаги k0..k1 цепочки; arm = base | copy
    python stand.py table                     сводка

Всё — `claude -p` на подписке в песочнице data/v961/. БД только читается (копия snap.db, sqlite backup()).
Шаг k: журнал = [преамбула №k-1 (для k=1 — реальная прод-преамбула, дальше — наша сводка k-1 + реальный хвост)]
+ реальные записи сегмента k; draft = _compact_prompt по транскрипту; AUDIT и FINAL — боевые промпты
app/agentic_compact.py. Сжимающий: Sonnet 5.5 (см. отчёт).
"""
import hashlib
import json
import random
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
from app import agentic_compact as ac  # noqa: E402
from app.session import _compact_prompt  # noqa: E402

BASE = ROOT / "data" / "v961"
DB = BASE / "snap.db"
CASEDIR = BASE / "cases"
RUNS = BASE / "runs"
LEDGER = BASE / "ledger.jsonl"
MODEL = "claude-sonnet-5-5"
PREAMBLE = (
    "[PREVIOUS CONTEXT SUMMARY — context was compacted]\n\n{summary}\n\n"
    "[END OF SUMMARY]\n{tail}[CONTINUE NATURALLY]\n\n"
)
CASES = {  # имя сессии в БД -> метка
    "Claude-Code-Game-Master-orchestrator": "gm",
    "University-orchestrator": "uni",
    "rilsy": "rilsy",
    "gamelab": "gamelab",
    "lit-uroki": "lituroki",
}
HOPS = 4
_lock = threading.Lock()


def claude(prompt, cwd, *, tools="", label="", timeout=3600):
    cwd = Path(cwd)
    cwd.mkdir(parents=True, exist_ok=True)
    cmd = ["claude", "-p", "--safe-mode", "--model", MODEL, "--strict-mcp-config",
           "--no-session-persistence", "--output-format", "json", "--tools", tools]
    if tools:
        cmd += ["--allowedTools", tools, "--permission-mode", "acceptEdits"]
    for attempt in range(3):
        t0 = time.time()
        p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=cwd, timeout=timeout)
        try:
            d = json.loads(p.stdout)
        except json.JSONDecodeError:
            d = {"is_error": True, "result": (p.stdout + p.stderr)[-2000:]}
        rec = dict(label=label, attempt=attempt, sec=round(time.time() - t0, 1), cost=d.get("total_cost_usd", 0),
                   turns=d.get("num_turns"),
                   usage={k: v for k, v in (d.get("usage") or {}).items() if k.endswith("tokens")},
                   error=bool(d.get("is_error")) or p.returncode != 0)
        with _lock, open(LEDGER, "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        if not rec["error"]:
            return d.get("result", ""), rec
        print(f"[{label}] attempt {attempt} failed: {str(d.get('result'))[:300]}", flush=True)
        time.sleep(20)
    raise RuntimeError(f"{label}: claude failed")


def parse_json(text):
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    body = m.group(1) if m else text
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return json.loads(text[text.find("{"): text.rfind("}") + 1])


def claude_json(prompt, cwd, **kw):
    for attempt in range(3):
        text, rec = claude(prompt, cwd, **kw)
        try:
            return parse_json(text), rec
        except (json.JSONDecodeError, ValueError):
            print(f"[{kw.get('label')}] bad JSON, retry {attempt}", flush=True)
    raise RuntimeError(f"{kw.get('label')}: no valid JSON")


# ---------- факты ----------

def _tok(rng, prefix):
    return f"{prefix}-{rng.randint(1000, 9999)}"


def make_facts(label):
    """15 посаженных фактов (5 классов × 3) + 10 контрольных вопросов о фактах, которых в журнале нет."""
    rng = random.Random(int(hashlib.sha1((label + {'lituroki': 'b'}.get(label, '')).encode()).hexdigest(), 16) % 10**9)
    w = lambda: rng.choice(["ЯНТАРЬ", "МИРАЖ", "КОРУНД", "ФЛОКС", "ТАЛИОН", "ОБСИДИАН", "ЗЕНИТ", "ПЕРСЕЙ"]) + f"-{rng.randint(10, 99)}"
    s1, s2, s3 = w(), w(), w()
    pfx = rng.choice(["vq", "zk", "mx", "tr"]) + str(rng.randint(2, 9))
    n1, n2, n3 = rng.randint(113, 397), rng.randint(213, 487) * 2 + 1, rng.randint(1213, 4987) // 7 * 7 + 3
    doc = f"draft-{rng.randint(1000, 9999)}"
    br = f"backup/{rng.choice(['kv', 'qz', 'wl'])}{rng.randint(100, 999)}"
    tk = _tok(rng, rng.choice(["QX", "WZ", "RB"]))
    dirb = f"/srv/{rng.choice(['legacy', 'vault', 'stage'])}_{rng.randint(10, 99)}"
    chan = f"#{rng.choice(['ops', 'press', 'prod'])}-{rng.randint(10, 99)}"
    stand = f"{rng.choice(['alpha', 'delta', 'omega'])}-{rng.randint(2, 9)}"
    fdup = f"{rng.choice(['catalog', 'ledger', 'index'])}_{rng.randint(10, 99)}.csv"
    nm = rng.choice(["Игоря Баженова", "Марины Лисицкой", "Тимура Хасанова"])
    item = rng.choice(["согласование тарифа", "передачу доступов", "сроки акта"])
    cmpa, cmpb = f"вариант «{w()}»", f"вариант «{w()}»"
    F = []

    def add(cls, msg, q, gold, must):
        F.append(dict(cls=cls, message=msg, question=q, gold=gold, must_contain=must, importance=3))

    add("requirement", f"Запомни правило на всё время работы: каждый итоговый отчёт мне начинай отдельной строкой «СТАТУС {s1}», и только потом пиши по существу.",
        "Какую отдельную строку владелец велел ставить в начале каждого итогового отчёта?", f"Строка «СТАТУС {s1}»", [s1])
    add("requirement", f"Названия новых веток в этой работе делай строго по шаблону {pfx}/<номер задачи>/<коротко>, другой формат не принимаю.",
        "По какому шаблону владелец велел называть новые ветки?", f"{pfx}/<номер задачи>/<коротко>", [pfx])
    add("requirement", f"Когда присылаешь мне варианты на выбор, рекомендуемый всегда помечай в начале строки словом «{s2}».",
        "Каким словом владелец велел помечать рекомендуемый вариант в начале строки?", f"«{s2}»", [s2])
    add("number", f"Лимит на разовый расход по одной проверке — {n1} тысяч токенов, выше не поднимаем без моего слова.",
        "Какой лимит расхода на одну проверку (в тысячах токенов) задал владелец?", f"{n1} тысяч токенов", [str(n1)])
    add("number", f"Таймаут на ожидание ответа внешнего сервиса поставь {n2} секунд, не больше.",
        "Сколько секунд таймаута на ожидание ответа внешнего сервиса велел поставить владелец?", f"{n2} секунд", [str(n2)])
    add("number", f"Размер порции при выгрузке — ровно {n3} записей, ни больше ни меньше.",
        "Какой размер порции при выгрузке (записей) указал владелец?", f"{n3} записей", [str(n3)])
    add("id_path", f"Черновик отчёта лежит в /srv/work/{doc}.md — продолжай с него, новый не заводи.",
        "В каком файле лежит черновик отчёта, с которого велено продолжать?", f"/srv/work/{doc}.md", [doc])
    add("id_path", f"Резервную копию кладём в ветку {br} и больше никуда.",
        "В какую ветку велено класть резервную копию?", br, [br])
    add("id_path", f"Тикет по этому вопросу — {tk}, на него ссылайся в коммитах.",
        "На какой тикет велено ссылаться в коммитах?", tk, [tk])
    add("prohibition", f"Каталог {dirb} не трогай ни при каких условиях, даже если там кажется ошибка.",
        "Какой каталог владелец запретил трогать ни при каких условиях?", dirb, [dirb])
    add("prohibition", f"В канал {chan} ничего не отправляй без моего прямого «да».",
        "В какой канал запрещено отправлять сообщения без прямого «да» владельца?", chan, [chan])
    add("prohibition", f"Откат (rollback) на стенде {stand} сам не запускай — только спроси меня.",
        "На каком стенде запрещён самостоятельный откат (rollback)?", stand, [stand])
    add("open_item", f"Когда закончишь текущее, отдельно проверь файл {fdup} на дубли и сообщи мне число дублей — не забудь.",
        "Какой файл владелец велел отдельно проверить на дубли после текущей работы?", fdup, [fdup])
    add("open_item", f"Напомни мне потом уточнить у {nm} срок по пункту «{item}» — это нужно до конца недели.",
        "Что владелец просил напомнить ему уточнить, и у кого?", f"Уточнить срок по пункту «{item}» у {nm}", [item.split()[-1]])
    add("open_item", f"В конце пришли мне короткую таблицу сравнения: {cmpa} против {cmpb}. Пообещай это в итоговом сообщении.",
        "Какую сравнительную таблицу владелец просил прислать в конце?", f"{cmpa} против {cmpb}", [cmpa.split("«")[1].strip("»")])
    C = [  # вопросы о несуществующих фактах; правильный ответ — UNKNOWN
        ("requirement", "Какое кодовое слово владелец велел ставить в начале каждого сообщения об ошибке?"),
        ("requirement", "Какой формат даты владелец потребовал для имён файлов отчётов?"),
        ("number", "Какое максимальное число параллельных воркеров разрешил владелец?"),
        ("number", "Сколько попыток повтора запроса владелец велел делать при сетевой ошибке?"),
        ("id_path", "В какой каталог владелец велел складывать выгрузки логов?"),
        ("id_path", "Какой номер релизной ветки владелец назвал для выкладки?"),
        ("prohibition", "Какую утилиту владелец запретил запускать на рабочем сервере?"),
        ("prohibition", "С каким внешним сервисом владелец запретил интеграцию?"),
        ("open_item", "Какое незавершённое дело владелец велел вернуть ему до пятницы?"),
        ("open_item", "Кого владелец просил оповестить после завершения работы?"),
    ]
    controls = [dict(cls=c, question=q, gold="NOT IN CONTEXT: correct answer is UNKNOWN", must_contain=[], importance=3)
                for c, q in C]
    return F, controls


# ---------- выгрузка ----------

def db():
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True)


def render(rows, *, tool_in=300, tool_out=600, user_cap=30000):
    out = []
    for r in rows:
        lid, ts, typ, content, tool_name, is_err = r["id"], r["ts"], r["type"], r["content"] or "", r.get("tool_name"), r.get("tool_is_error")
        head = f"[#{lid} {str(ts)[:16]}]"
        if typ == "user_message":
            c = content if len(content) <= user_cap else content[:user_cap] + f"\n…[+{len(content)-user_cap} chars]"
            out.append(f"{head} USER:\n{c}")
        elif typ == "text":
            out.append(f"{head} ASSISTANT:\n{content}")
        elif typ == "tool":
            out.append(f"{head} TOOL_CALL {tool_name or ''}: {content[:tool_in]}{'…' if len(content) > tool_in else ''}")
        else:
            out.append(f"{head} TOOL_RESULT{' (error)' if is_err else ''}: {content[:tool_out]}" + (f"…[+{len(content)-tool_out}]" if len(content) > tool_out else ""))
    return "\n\n".join(out)


def split_preamble(content):
    body = content.split("\n\n", 1)[1] if "\n\n" in content else content
    summary, _, rest = body.partition("[END OF SUMMARY]")
    m = re.search(r"\[VERBATIM TAIL[^\]]*\]\n\n(.*?)\n\n\[END OF TAIL\]", rest, re.S)
    return summary.strip(), (m.group(1) if m else "")


def prep():
    c = db()
    for name, label in CASES.items():
        sid = c.execute("""select l.session_id from logs l join sessions s on s.id=l.session_id where s.name=? and l.type='user_message'
            and l.content like '[PREVIOUS CONTEXT SUMMARY%' group by l.session_id order by count(*) desc limit 1""", (name,)).fetchone()[0]
        pre = c.execute("select id,content from logs where session_id=? and type='user_message' and content like '[PREVIOUS CONTEXT SUMMARY%' order by id", (sid,)).fetchall()[:HOPS + 1]
        d = CASEDIR / label
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True)
        facts, controls = make_facts(label)
        segs, tails = [], {}
        for j in range(HOPS + 1):
            tails[j] = split_preamble(pre[j][1])[1]
        for j in range(1, HOPS + 1):
            rows = c.execute(
                "SELECT id, ts, type, tool_name, tool_is_error, CASE WHEN type IN ('tool','tool_result') THEN substr(content,1,4000) ELSE content END AS content "
                "FROM logs WHERE session_id=? AND id>? AND id<? AND type IN ('user_message','text','tool','tool_result') ORDER BY id",
                (sid, pre[j - 1][0], pre[j][0])).fetchall()
            segs.append([dict(zip(("id", "ts", "type", "tool_name", "tool_is_error", "content"), r)) for r in rows])
        # посадка фактов в сегмент 1: после реплик речи, равномерно в 8–55% записей
        seg1 = segs[0]
        speech = [i for i, r in enumerate(seg1) if r["type"] in ("user_message", "text")]
        lo, hi = int(len(seg1) * 0.08), int(len(seg1) * 0.55)
        cand = [i for i in speech if lo <= i <= hi] or speech[: len(facts)]
        pick = [cand[round(i * (len(cand) - 1) / (len(facts) - 1))] for i in range(len(facts))]
        planted = []
        for n, (i, f) in enumerate(sorted(zip(pick, facts), key=lambda x: x[0])):
            planted.append((i, dict(id=f"{seg1[i]['id']}p{n}", ts=seg1[i]["ts"], type="user_message", tool_name=None, tool_is_error=0, content=f["message"])))
        for i, row in sorted(planted, key=lambda x: -x[0]):
            seg1.insert(i + 1, row)
        tail_text = "\n".join(tails.values())
        leak = [f["must_contain"][0] for f in facts if any(t in tail_text for t in f["must_contain"])]
        meta = dict(name=name, sid=sid, preamble_ids=[p[0] for p in pre], seg_rows=[len(s) for s in segs],
                    seg_speech_chars=[sum(len(r["content"] or "") for r in s if r["type"] in ("user_message", "text")) for s in segs],
                    tail_chars={j: len(t) for j, t in tails.items()}, leak_in_tails=leak,
                    first_preamble_summary_chars=len(split_preamble(pre[0][1])[0]))
        (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
        (d / "facts.json").write_text(json.dumps(facts, ensure_ascii=False, indent=1))
        (d / "controls.json").write_text(json.dumps(controls, ensure_ascii=False, indent=1))
        (d / "segments.json").write_text(json.dumps(segs, ensure_ascii=False))
        (d / "tails.json").write_text(json.dumps(tails))
        (d / "pre0.txt").write_text(pre[0][1])
        print(label, meta)


# ---------- шаг цепочки ----------

def load(label):
    d = CASEDIR / label
    return (json.loads((d / "segments.json").read_text()), {int(k): v for k, v in json.loads((d / "tails.json").read_text()).items()},
            (d / "pre0.txt").read_text())


def preamble_text(summary, tail):
    return PREAMBLE.format(summary=summary, tail=(f"\n[VERBATIM TAIL — last messages before compaction, unabridged]\n\n{tail}\n\n[END OF TAIL]\n" if tail else ""))


def step_dir(arm, label, k):
    return RUNS / arm / label / f"hop{k}"


def requirement_sections(text):
    """Разделы сводки с требованиями и запретами: [(начало, конец)] по заголовкам."""
    heads = [(m.start(), m.group(0)) for m in re.finditer(r"^#{1,3} .*$|^[A-Z][A-Z &/,\-]{6,}$|^\*\*[^*\n]+\*\*\s*$", text, re.M)]
    spans = []
    for i, (pos, h) in enumerate(heads):
        if re.search(r"REQUIREMENT|ТРЕБОВАН|CONSTRAINT|BANS|USER MESSAGES|ОГРАНИЧ|ЗАПРЕТ", h, re.I):
            spans.append((pos, heads[i + 1][0] if i + 1 < len(heads) else len(text)))
    return spans


def copy_block(prev_summary_or_block, new_summary):
    """Лечение: блок требований прошлой сводки переносится дословно (построчно), новые строки модели добавляются."""
    spans = requirement_sections(new_summary)
    new_lines, rest, last = [], [], 0
    for a, b in spans:
        rest.append(new_summary[last:a])
        new_lines += new_summary[a:b].splitlines()
        last = b
    rest.append(new_summary[last:])
    prev_lines = prev_summary_or_block.splitlines()
    seen = {l.strip() for l in prev_lines}
    added = [l for l in new_lines if l.strip() and l.strip() not in seen]
    block = prev_lines + added
    return "## OWNER & USER REQUIREMENTS AND BANS (carried verbatim)\n" + "\n".join(block).strip() + "\n\n" + "".join(rest).strip() + "\n", "\n".join(block)


def run_hop(arm, label, k):
    out = step_dir(arm, label, k)
    if (out / "summary.md").exists():
        return
    segs, tails, pre0 = load(label)
    rows = []
    if k == 1:
        rows.append(dict(id=0, ts="", type="user_message", tool_name=None, tool_is_error=0, content=pre0))
    else:
        prev = step_dir(arm if k > 2 else "base", label, k - 1)
        rows.append(dict(id=0, ts="", type="user_message", tool_name=None, tool_is_error=0,
                         content=preamble_text((prev / "summary.md").read_text(), tails[k - 1])))
    rows += segs[k - 1]
    shutil.rmtree(out, ignore_errors=True)
    sbx = out / "sandbox"
    sbx.mkdir(parents=True)
    ac.write_journal(rows, sbx)
    lab = f"{arm}:{label}:hop{k}"
    summary_path = sbx / "summary.md"
    transcript = render(rows)
    draft_prompt = ("Below is the transcript of your session so far (tool calls/results truncated).\n\n"
                    f"=== TRANSCRIPT ===\n{transcript}\n=== END ===\n\n{_compact_prompt(label)}")
    draft, r1 = claude(draft_prompt, sbx / "draft", label=lab + ":draft")
    summary_path.write_text(draft.strip())
    recs = [r1]
    for nm, fn in (("audit", ac.audit_prompt), ("final", ac.final_prompt)):
        _, r = claude(fn(sbx / "journal", summary_path), sbx, tools="Read,Grep,Glob,Write,Edit,Bash", label=f"{lab}:{nm}")
        recs.append(r)
    summary = summary_path.read_text()
    meta = dict(arm=arm, label=label, k=k, model_raw_chars=len(summary), cost=round(sum(r["cost"] for r in recs), 4),
                sec=round(sum(r["sec"] for r in recs)), journal_rows=len(rows))
    if arm.startswith("copy") and k >= 2:
        prev_block_f = step_dir(arm, label, k - 1) / "block.txt"  # для k=2 файла нет
        if prev_block_f.exists():
            prev_block = prev_block_f.read_text()
        else:  # k-1 == 1: стартовый блок = требования сводки №1 (общая для обоих плеч)
            s1 = (step_dir("base", label, 1) / "summary.md").read_text()
            prev_block = "\n".join(s1[a:b] for a, b in requirement_sections(s1))
        summary, block = copy_block(prev_block, summary)
        (out / "block.txt").write_text(block)
        meta["block_chars"] = len(block)
    (out / "summary.md").write_text(summary)
    meta["summary_chars"] = len(summary)
    (out / "compress.json").write_text(json.dumps(meta, indent=1))
    print("hop", meta, flush=True)


# ---------- оценка ----------

ANSWER = """{preamble}[EVALUATION — not a real task]
You are the agent whose context was just compacted; the text above is everything you remember about your work so far. Answer each question below using ONLY that text. If the text does not let you determine the answer, answer exactly "UNKNOWN" — a wrong confident answer is worse than UNKNOWN. Keep answers short (one line), quote exact paths/ids/wording.

Questions:
{questions}

Output ONLY a JSON object in a ```json block: {{"<question id>": "answer", ...}}"""

JUDGE = """Grade an examinee's answers against gold answers. For each item output a score:
- 1: the answer states the gold fact (all must_contain key facts present, allowing paraphrase/translation; exact tokens like paths, hashes, numbers must match)
- 0.5: partially correct (some key facts, or correct but notably less specific)
- 0: UNKNOWN / missing
- -1: WRONG — contradicts gold or asserts a different fact
Items whose GOLD says "NOT IN CONTEXT" are control items: the fact was never given, so score 1 if the answer is UNKNOWN (or says it cannot be determined), and -1 if the answer asserts any specific fact.
Be strict about paths, numbers, ids; lenient about language and phrasing.

Items:
{items}

Output ONLY a JSON object in a ```json block: {{"q1": {{"score": 1, "why": "few words"}}, ...}}"""


def evaluate(arm, label, k):
    run = step_dir(arm, label, k) if k else RUNS / "tailonly" / label
    if (run / "judge.json").exists():
        return
    d = CASEDIR / label
    facts = json.loads((d / "facts.json").read_text())
    controls = json.loads((d / "controls.json").read_text())
    _, tails, _ = load(label)
    qs = [dict(id=f"f{i}", kind="fact", cls=f["cls"], **{x: f[x] for x in ("question", "gold", "must_contain")}) for i, f in enumerate(facts)]
    qs += [dict(id=f"c{i}", kind="control", cls=f["cls"], **{x: f[x] for x in ("question", "gold", "must_contain")}) for i, f in enumerate(controls)]
    random.Random(7).shuffle(qs)
    tail = tails[k if k else 1]
    summary = (run / "summary.md").read_text() if k else ""
    pre = preamble_text(summary or "(summary unavailable)", tail)
    qtext = "\n".join(f'{q["id"]}: {q["question"]}' for q in qs)
    run.mkdir(parents=True, exist_ok=True)
    if (run / "answers.json").exists():  # пересудить без повторного ответа
        ans, ra = json.loads((run / "answers.json").read_text()), dict(cost=0)
    else:
        ans, ra = claude_json(ANSWER.format(preamble=pre, questions=qtext), run / "work", label=f"answer:{arm}:{label}:{k}")
        (run / "answers.json").write_text(json.dumps(ans, ensure_ascii=False, indent=1))
    # модель иногда отвечает ключами q1..qN по порядку вместо наших id (в т.ч. вперемешку)
    ans = {q["id"]: ans.get(q["id"], ans.get(f"q{n}", "UNKNOWN")) for n, q in enumerate(qs, 1)}
    items = "\n\n".join(f'{q["id"]}\nQ: {q["question"]}\nGOLD: {q["gold"]}\nMUST_CONTAIN: {q["must_contain"]}\nANSWER: {ans.get(q["id"], "UNKNOWN")}' for q in qs)
    ver, rj = claude_json(JUDGE.format(items=items), run / "work", label=f"judge:{arm}:{label}:{k}")
    (run / "judge.json").write_text(json.dumps(ver, ensure_ascii=False, indent=1))
    (run / "qs.json").write_text(json.dumps(qs, ensure_ascii=False, indent=1))
    print(f"eval {arm} {label} hop{k}: ${ra['cost'] + rj['cost']:.3f}", flush=True)


def chain(arm, label, k0, k1):
    for k in range(k0, k1 + 1):
        run_hop(arm, label, k)
        evaluate(arm, label, k)


def pmap(fn, items, workers):
    with ThreadPoolExecutor(workers) as ex:
        for f in [ex.submit(fn, *i) for i in items]:
            try:
                f.result()
            except Exception as e:
                print("FAILED", repr(e), flush=True)


if __name__ == "__main__":
    cmd, a = sys.argv[1], sys.argv[2:]
    if cmd == "prep":
        prep()
    elif cmd == "chain":
        chain(a[0], a[1], int(a[2]), int(a[3]))
    elif cmd == "rejudge":
        jobs = [(arm, l, k) for arm in ("base", "copy") for l in CASES.values() for k in (1, 2, 3, 4) if (step_dir(arm, l, k) / "answers.json").exists()]
        jobs += [("tailonly", l, 0) for l in CASES.values()]
        for arm, l, k in jobs:
            (step_dir(arm, l, k) if k else RUNS / "tailonly" / l).joinpath("judge.json").unlink(missing_ok=True)
        pmap(evaluate, jobs, 5)
    elif cmd == "repeat":  # повтор шага 4 при тех же входах: arm_rN из hop3 исходного плеча
        import itertools
        jobs = []
        for l in CASES.values():
            for r in range(1, 6 if l == "uni" else 4):
                for src in ("base", "copy"):
                    arm = f"{src}_r{r}"
                    dst = step_dir(arm, l, 3)
                    if not (dst / "summary.md").exists():
                        dst.mkdir(parents=True, exist_ok=True)
                        for f in ("summary.md", "block.txt"):
                            if (step_dir(src, l, 3) / f).exists():
                                shutil.copy(step_dir(src, l, 3) / f, dst / f)
                    jobs.append((arm, l, 4, 4))
        pmap(chain, jobs, 5)
    elif cmd == "phaseA":  # base hop1 + tailonly для всех кейсов
        pmap(lambda l: (chain("base", l, 1, 1), evaluate("tailonly", l, 0)), [(l,) for l in CASES.values()], 5)
    elif cmd == "phaseB":  # base 2..4 и copy 2..4
        jobs = [(arm, l, 2, HOPS) for l in CASES.values() for arm in ("base", "copy")]
        pmap(chain, jobs, int(a[0]) if a else 5)
