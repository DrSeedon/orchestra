"""V-775 batch experiment: LLM triage of Seedon tender-collector rows that keyword filter left as 'no match, manual review'.
Reads the live collector DB read-only; key from .env, never printed. Usage: batch_tenders.py <model> <n> <submit|collect> [batch_id]"""
import json, os, sqlite3, sys, time, random
from pathlib import Path
import anthropic

model, n, mode = sys.argv[1], int(sys.argv[2]), sys.argv[3]
key = next(l.split("=", 1)[1].strip().strip("\"'") for l in Path("/home/kesha/orchestra/.env").read_text().splitlines()
           if l.startswith("ORCHESTRA_CLAUDE_CREDIT_API_KEY="))
c = anthropic.Anthropic(api_key=key)
OUT = Path("/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-anthropic-api/data/v775")
SYSTEM = """Ты фильтруешь госзакупки для ООО «Сидон» (малая ИТ-студия). Берём: разработку и сопровождение сайтов и веб-порталов, чат-ботов и telegram-ботов, интеграции (1С, API), ИИ/нейросетевые решения и обработку текстов, парсинг, SEO/GEO-продвижение сайтов, автоматизацию процессов, разработку ПО. НЕ берём: поставку товаров и оборудования, лицензии на готовое ПО, строительство, ремонт, монтаж, связь, хостинг, обучение, СМИ и публикации, охрану, транспорт, медицину.
По карточке закупки ответь: fit = "yes" (явно наш профиль), "maybe" (возможно, нужна проверка человеком), "no". reason — не длиннее 12 слов."""
SCHEMA = {"type": "object", "properties": {"fit": {"type": "string", "enum": ["yes", "maybe", "no"]}, "reason": {"type": "string"}},
          "required": ["fit", "reason"], "additionalProperties": False}
if mode == "submit":
    p = os.path.expanduser("~/.local/share/seedon/tender-collector.sqlite3")
    db = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=60)
    rows = db.execute("""select id,title,description,customer,okpd2,price from purchases
        where match_reason like 'Ключевого совпадения нет%' and cast(price as real) between 30000 and 10000000""").fetchall()
    random.seed(775); rows = random.sample(rows, n)
    reqs = []
    for id_, t, d, cu, ok, pr in rows:
        card = f"Название: {t}\nОписание: {(d or '')[:600]}\nЗаказчик: {cu}\nОКПД2: {ok}\nНМЦК: {pr}"
        reqs.append({"custom_id": str(id_), "params": {"model": model, "max_tokens": 200,
            "system": [{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral", "ttl": "1h"}}],
            "output_config": {"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
            "messages": [{"role": "user", "content": card}]}})
    (OUT / f"tenders-{model}-{n}.cards.json").write_text(json.dumps({r["custom_id"]: r["params"]["messages"][0]["content"] for r in reqs}, ensure_ascii=False))
    b = c.messages.batches.create(requests=reqs)
    print("batch", b.id, b.processing_status, "t0", int(time.time()))
else:
    b = c.messages.batches.retrieve(sys.argv[4]); print(b.processing_status, b.request_counts, b.ended_at, b.created_at)
    if b.processing_status == "ended":
        res = []
        for r in c.messages.batches.results(b.id):
            if r.result.type == "succeeded":
                m = r.result.message; u = m.usage
                res.append({"id": r.custom_id, "out": m.content[0].text, "in": u.input_tokens, "cw": u.cache_creation_input_tokens, "cr": u.cache_read_input_tokens, "o": u.output_tokens})
            else: res.append({"id": r.custom_id, "err": str(r.result)[:200]})
        (OUT / f"tenders-{model}-{n}.results.json").write_text(json.dumps(res, ensure_ascii=False))
        print(len(res), "saved")
