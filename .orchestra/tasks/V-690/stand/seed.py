"""Фейковое состояние Orchestra для русского README: оркестратор и пять воркеров."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

from app import db
from app.db import _conn
from app.events import MessageProvenance

NOW = datetime.now(timezone.utc)

AGENTS = [
    # name, model, backend, role, status, ctx%, turns, cost, progress, desc
    ("acme-orchestrator", "claude-opus-5-5[1m]", "claude", "orchestrator", "running", 38, 61, 4.12, 0,
     "Оркестратор: планирует работу, запускает воркеров, проверяет изменения и мержит"),
    ("fix-double-charge", "claude-sonnet-5-5[1m]", "claude", "full-cycle", "running", 54, 33, 1.86, 70,
     "lifecycle=one-shot | #2 повторное списание после обновления Stripe SDK"),
    ("payments-ratelimit", "gpt-6-luna", "codex", "worker", "idle", 41, 19, 0.38, 100,
     "lifecycle=one-shot | #3 лимит запросов для /api/payments"),
    ("checkout-ui", "claude-sonnet-5-5[1m]", "claude", "worker", "waiting", 27, 14, 0.91, 45,
     "lifecycle=one-shot | #4 защита кнопки оплаты от повторов"),
    ("e2e-tests", "gpt-6-luna", "codex", "worker", "running", 22, 9, 0.21, 30,
     "lifecycle=one-shot | #5 сквозные тесты Playwright для оплаты"),
    ("docs-writer", "claude-haiku-4-5", "claude", "worker", "idle", 12, 6, 0.09, 100,
     "lifecycle=persistent | синхронизирует CHANGELOG и документацию"),
]
COLORS = ["", "#58c4dd", "#83c167", "#f0ac5f", "#c084fc", "#fc6255"]
TASKS = [
    ("1", "Перенести изображения товаров в CDN", "done", "", 2),
    ("2", "Двойное списание после обновления Stripe SDK", "in_progress", "fix-double-charge", 0),
    ("3", "Ограничить /api/payments: 100 запросов в минуту на IP", "done", "payments-ratelimit", 1),
    ("4", "Блокировать кнопку оплаты, пока создаётся платёж", "in_progress", "checkout-ui", 1),
    ("5", "Сквозные тесты Playwright: оплата и повтор запроса", "in_progress", "e2e-tests", 2),
    ("6", "Вернуть двойные списания за последние семь дней", "new", "", 1),
    ("7", "Обновить CHANGELOG для v0.5.0", "done", "docs-writer", 3),
]


def ts(minutes_ago: float) -> datetime:
    return NOW - timedelta(minutes=minutes_ago)


def iso(minutes_ago: float) -> str:
    return ts(minutes_ago).isoformat()


def tool(sid, at, name, args, result, use_id=None):
    use_id = use_id or "toolu_" + uuid.uuid4().hex[:24]
    db.add_log(sid, ts(at), "tool", f"{name}: {json.dumps(args, indent=2)}", tool_use_id=use_id, tool_name=name)
    db.add_log(sid, ts(at - 0.05), "tool_result", result, tool_use_id=use_id, tool_name=name)


def owner(sid, at, text):
    db.add_log(sid, ts(at), "user_message", text,
               provenance=MessageProvenance(origin="user", senders=("user",), subtype="dashboard"))


def agent_msg(sid, at, sender, text):
    db.add_log(sid, ts(at), "user_message", text, provenance=MessageProvenance(origin="agent", senders=(sender,), subtype="direct_message"))


def run(scope: str) -> None:
    with _conn() as c:
        if c.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]:
            return
    ids = {}
    with _conn() as c:
        for i, (name, model, backend, role, status, ctx, turns, cost, prog, desc) in enumerate(AGENTS):
            sid = str(uuid.uuid4())
            ids[name] = sid
            orch = role == "orchestrator"
            tid = next((r for r, _t, _s, a, _p in TASKS if a == name), "")
            c.execute(
                "INSERT INTO sessions (id,name,scope,cwd,model,status,cost_usd,cost_usd_cached,worktree_path,branch,"
                "base_branch,is_orchestrator,color,created_at,context_pct,context_tokens,progress_pct,progress_status,"
                "backend_type,task_id,description,total_turns,role,parent_name,pipeline,effort,total_tool_calls) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (sid, name, scope, scope if orch else f"{scope}/.worktrees/{name}", model, status, cost, cost,
                 None if orch else f"{scope}/.worktrees/{name}", None if orch else f"task-{tid}/{name}",
                 "main", int(orch), COLORS[i], iso(95 - i * 6), ctx, ctx * 2_000, prog,
                 "" if orch else ["", "пишет регрессионный тест для idempotency key", "готово, ждёт merge",
                                  "ждёт e2e-тесты", "записывает сценарий оплаты", "свободен"][i],
                 backend, tid, desc, turns, role,
                 "" if orch else "acme-orchestrator", "default", "medium", turns * 4))
    _tasks(scope)
    _chat(ids)
    _usage(ids, scope)


def _activity(t: datetime) -> float:
    """Relative agent load per 10 minutes: busy working hours, a thin overnight tail."""
    import math
    t = t + timedelta(hours=7)  # the demo team works UTC+7, so "now" falls in a busy afternoon
    h = t.hour + t.minute / 60
    day = max(0.0, math.sin((h - 5) / 15 * math.pi)) if 5 <= h <= 20 else 0.0
    weekend = 0.45 if t.weekday() >= 5 else 1.0
    return (0.08 + day) * weekend


def _usage(ids: dict, scope: str) -> None:
    """Two weeks of turn costs (📊 analytics) and a week of quota snapshots (usage charts).

    Final points equal stand._fake_quota(), so the live bar and the charts agree.
    """
    import random
    from app.routes.system import _normalize_codex_usage, _provider_usage_snapshot
    rnd = random.Random(686)
    claude = [(n, m) for n, m, b, *_ in AGENTS if b == "claude"]
    codex = [(n, m) for n, m, b, *_ in AGENTS if b == "codex"]
    rows = []
    step = timedelta(minutes=10)
    start = (NOW - timedelta(days=14)).replace(second=0, microsecond=0)
    t = start
    while t < NOW:
        load = _activity(t) * rnd.uniform(0.6, 1.4)
        for runtime, pool, per_turn, busy in (("claude", claude, 0.34, 1.5), ("codex", codex, 0.11, 1.0)):
            lv = min(load * busy, 1.9)
            for _ in range(rnd.choices([0, 1, 2], [max(0.1, 1.2 - lv), lv, lv / 2])[0]):
                name, model = rnd.choice(pool)
                cost = round(per_turn * rnd.uniform(0.3, 2.2) * (1.6 if "opus" in model else 0.5 if "haiku" in model else 1), 4)
                at = t + timedelta(seconds=rnd.uniform(0, 599))
                rows.append((uuid.uuid4().hex, at.isoformat(), ids[name], scope, runtime, model, cost,
                             rnd.randint(2_000, 9_000), rnd.randint(400, 4_000),
                             rnd.randint(20_000, 160_000), rnd.randint(0, 12_000)))
        t += step
    with _conn() as c:
        c.executemany(
            "INSERT INTO turn_usage (event_id,ts,session_id,scope,runtime,model,ok,stop_reason,cost_usd,"
            "input_tokens,output_tokens,cache_read_tokens,cache_create_tokens) "
            "VALUES (?,?,?,?,?,?,1,'end_turn',?,?,?,?,?)", rows)

    # Quota windows: utilisation = scaled load accumulated since the window's last reset.
    def windows(reset_now: datetime, length: timedelta, final: float, peaks: tuple[float, float]):
        """{t: (pct, resets_at)} for 10-minute points over the last 7 days."""
        out, t = {}, (NOW - timedelta(days=7)).replace(second=0, microsecond=0)
        points = []
        while t <= NOW:
            reset = reset_now - ((reset_now - t) // length) * length  # end of the window holding t
            points.append((t, reset))
            t += step
        by_reset: dict[datetime, list] = {}
        for t, reset in points:
            by_reset.setdefault(reset, []).append(t)
        for reset, ts_ in by_reset.items():
            acc, cum = 0.0, []
            for t in ts_:
                acc += _activity(t) * rnd.uniform(0.7, 1.3)
                cum.append(acc)
            top = final if reset == reset_now else rnd.uniform(*peaks)
            # A partial first window (the chart's left edge) keeps its proportion.
            span = (ts_[-1] - (reset - length)) / length if reset != reset_now else 1
            scale = top * min(1.0, span + 0.2) / (cum[-1] or 1)
            for t, v in zip(ts_, cum):
                out[t] = (round(min(99.0, v * scale), 1), reset.isoformat())
        return out

    c5 = windows(NOW + timedelta(hours=2, minutes=41), timedelta(hours=5), 34, (35, 88))
    c7 = windows(NOW + timedelta(days=2, hours=9), timedelta(days=7), 58, (80, 93))
    x5 = windows(NOW + timedelta(hours=3, minutes=15), timedelta(hours=5), 22, (15, 55))
    x7 = windows(NOW + timedelta(days=4), timedelta(days=7), 41, (60, 75))
    snaps = []
    for t in sorted(c5):
        epoch = lambda iso_: int(datetime.fromisoformat(iso_).timestamp())  # noqa: E731
        anth = {"five_hour": {"utilization": c5[t][0], "resets_at": c5[t][1]},
                "seven_day": {"utilization": c7[t][0], "resets_at": c7[t][1]}}
        cdx = _normalize_codex_usage({"rateLimits": {"planType": "pro",
            "primary": {"usedPercent": x5[t][0], "windowDurationMins": 300, "resetsAt": epoch(x5[t][1])},
            "secondary": {"usedPercent": x7[t][0], "windowDurationMins": 10080, "resetsAt": epoch(x7[t][1])}}})
        providers = _provider_usage_snapshot(anth, cdx, None)
        snaps.append((t.isoformat(), c5[t][0], c7[t][0], c5[t][1], c7[t][1],
                      json.dumps(providers, ensure_ascii=False)))
    with _conn() as c:
        c.executemany(
            "INSERT INTO usage_snapshots (ts,five_hour_pct,seven_day_pct,five_hour_resets_at,"
            "seven_day_resets_at,total_cost_usd,active_agents,provider_usage) VALUES (?,?,?,?,?,0,3,?)", snaps)


def _tasks(scope: str) -> None:
    from app import tm
    for ref, title, status, assignee, prio in TASKS:
        tm.api_create_task("", title, scope=scope, assignee=assignee, priority=prio, status="new")
    with _conn() as c:
        rows = c.execute("SELECT id,title FROM tm_tasks ORDER BY id").fetchall()
        by_title = {r["title"]: r["id"] for r in rows}
        for ref, title, status, assignee, _p in TASKS:
            c.execute("UPDATE tm_tasks SET status=? WHERE id=?", (status, by_title[title]))


def _chat(ids: dict) -> None:
    o = ids["acme-orchestrator"]
    owner(o, 52, "После обновления Stripe SDK некоторым клиентам списали деньги дважды. "
                 "Найди причину и исправь. Заодно добавь ограничение запросов к payments API. "
                 "Ничего не выкатывай — сначала я всё проверю.")
    db.add_log(o, ts(51.5), "text",
               "Проверил сценарий оплаты. После обновления SDK `createPaymentIntent` повторяется при сетевом "
               "тайм-ауте **без idempotency key**: медленный ответ Stripe превращается в два списания.\n\n"
               "Разделяю работу на четыре параллельных направления:\n\n"
               "1. **fix-double-charge** — idempotency key для заказа и регрессионный тест\n"
               "2. **payments-ratelimit** — 100 запросов в минуту на IP для `/api/payments`\n"
               "3. **checkout-ui** — блокировать *Pay*, пока платёж обрабатывается\n"
               "4. **e2e-tests** — Playwright: успешная оплата и повтор после тайм-аута")
    for at, (name, model, task) in zip(
        [51, 50.8, 50.6, 50.4],
        [("fix-double-charge", "sonnet", "2"), ("payments-ratelimit", "luna", "3"),
         ("checkout-ui", "sonnet", "4"), ("e2e-tests", "luna", "5")]):
        tool(o, at, "mcp__orchestra__spawn_worker",
             {"name": name, "model": model, "task_id": task, "repo_path": "/srv/demo/acme-shop"},
              f"Запущен воркер '{name}'. Модель: {model}. Задача принята. state=QUEUED.")
    agent_msg(o, 31, "payments-ratelimit",
              "Готово, задача #3: sliding-window limiter для /api/payments, 100 запросов в минуту на IP, 429 с Retry-After.\n\n"
              "Файлы: src/api/rateLimit.ts, src/api/checkout.ts (+48/-3)\nТесты: 14 passed (vitest)")
    tool(o, 30, "Bash", {"command": "git -C .worktrees/payments-ratelimit diff main --stat"},
         " src/api/checkout.ts      |  6 ++-\n src/api/rateLimit.ts     | 31 +++++++++\n"
         " tests/rateLimit.test.ts  | 14 ++++\n 3 files changed, 48 insertions(+), 3 deletions(-)")
    tool(o, 29, "mcp__orchestra__merge_worker",
         {"name": "payments-ratelimit", "task_outcome": "complete",
          "acceptance_note": "diff reviewed, 14 tests green, limiter covers all /api/payments routes"},
         "{'status': 'SUCCEEDED', 'commit': 'a4f2c91', 'task': '#3 → done'}")
    db.add_log(o, ts(28.8), "text", "Смержил **#3** (`a4f2c91`). Ограничение запросов в `main`, ещё не выкачено.")
    agent_msg(o, 9, "fix-double-charge",
              "Нашёл причину: SDK v14 по умолчанию повторяет `paymentIntents.create` при ETIMEDOUT. Вызову не хватает "
              "`idempotencyKey`, поэтому Stripe считает повтор новым списанием. Исправление: ключ `order:{id}:attempt:{n}`. "
              "Пишу регрессионный тест.")
    tool(o, 8.5, "mcp__orchestra__send_message",
         {"to": "fix-double-charge", "message": "Хорошо. Добавь ключ и в возврат платежа — он понадобится для #6."},
         "Сообщение доставлено 'fix-double-charge'; state=QUEUED.")
    db.add_log(o, ts(8.3), "text",
               "Статус работы:\n\n"
               "- ✅ **Ограничение запросов** смерджено (`a4f2c91`), все 14 тестов прошли\n"
               "- 🔧 **Двойное списание** — причина подтверждена (при повторе SDK нет idempotency key), исправление в работе\n"
               "- ⏳ **Интерфейс оплаты** ждёт сквозные тесты\n"
               "- 📋 **#6** (возврат за последние семь дней) ждёт твоего разрешения: задача перемещает деньги")
    db.add_log(o, ts(0.2), "status", "ход завершён (end_turn, 7 запросов, $0,31 за ход, $4,12 за сессию, контекст 38%)")

    w = ids["fix-double-charge"]
    agent_msg(w, 50, "acme-orchestrator", "Задача #2: после обновления Stripe SDK клиентам списали деньги дважды. Найди причину, исправь и добавь регрессионный тест.")
    tool(w, 48, "Grep", {"pattern": "paymentIntents.create", "path": "src"},
         "src/lib/stripe.ts:27:  const intent = await stripe.paymentIntents.create({")
    tool(w, 47, "Read", {"file_path": "src/lib/stripe.ts"}, "  27  const intent = await stripe.paymentIntents.create({\n  28    amount, currency, customer,\n  29  });")
    db.add_log(w, ts(46), "text", "Здесь нет `idempotencyKey`, а SDK v14 по умолчанию включает `maxNetworkRetries: 2`.")
    tool(w, 20, "Edit", {"file_path": "src/lib/stripe.ts",
                         "old_string": "  amount, currency, customer,\n});",
                         "new_string": "  amount, currency, customer,\n}, { idempotencyKey: `order:${order.id}:attempt:${attempt}` });"},
         "Файл src/lib/stripe.ts успешно обновлён.")
    tool(w, 3, "Bash", {"command": "npx vitest run tests/checkout.test.ts"},
         " ✓ tests/checkout.test.ts (6 tests) 412ms\n   ✓ повторы после ETIMEDOUT используют тот же idempotency key\n\n Тестовых файлов: 1 passed (1)\n      Тестов: 6 passed (6)")

    for name in ("payments-ratelimit", "checkout-ui", "e2e-tests", "docs-writer"):
        sid = ids[name]
        agent_msg(sid, 50, "acme-orchestrator", f"Задача для {name}: подробности — в карточке задачи.")
        db.add_log(sid, ts(10), "text", "Работаю над задачей.")


async def live(slow: float = 1.0) -> None:
    """Scripted 'live' turn for the recording: worker reports DONE, orchestrator reviews and merges.

    slow stretches the pauses to match a slow-motion recording (clips.py)."""
    import asyncio

    def pause(seconds):
        return asyncio.sleep(seconds * slow)
    from app.live_broker import broker
    with _conn() as c:
        ids = {r["name"]: r["id"] for r in c.execute("SELECT id,name FROM sessions")}
    o, w = ids["acme-orchestrator"], ids["fix-double-charge"]

    def session(name, **cols):
        with _conn() as c:
            sets = ",".join(f"{k}=?" for k in cols)
            c.execute(f"UPDATE sessions SET {sets} WHERE name=?", (*cols.values(), name))

    owner(o, 0, "Тесты зелёные? Тогда мержи исправление двойного списания. Пока ничего не выкатывай.")
    await pause(1.2)
    session("e2e-tests", progress_pct=60, progress_status="сценарий повтора оплаты проходит")
    agent_msg(o, 0, "fix-double-charge",
              "Готово, задача #2: idempotency key при создании и возврате платежа; регрессионный тест воспроизводит повтор SDK.\n\n"
              "Файлы: src/lib/stripe.ts, src/api/checkout.ts, tests/checkout.test.ts (+61/-4)\nТесты: 21 passed")
    session("fix-double-charge", status="idle", progress_pct=100, progress_status="готово, ждёт merge",
            cost_usd=2.04, cost_usd_cached=2.04, total_turns=38)
    await pause(1.5)
    text = "Проверяю diff: ключ зависит от id заказа и номера попытки. Повтор использует прежний ключ, новая попытка — новый."
    acc = ""
    for word in text.split(" "):
        acc += word + " "
        broker.publish(o, {"type": "stream", "content": word + " "})
        await pause(0.06)
    db.add_log(o, ts(0), "text", text)
    broker.clear_accum(o)  # the runtime does this when the final text lands
    await pause(0.8)
    tool(o, 0, "Bash", {"command": "npx vitest run && git -C .worktrees/fix-double-charge diff main --stat"},
         " Файлов тестов: 9 passed (9)\n      Тестов: 48 passed (48)\n\n"
         " src/api/checkout.ts      |  9 +++--\n src/lib/stripe.ts        | 14 ++++--\n"
         " tests/checkout.test.ts   | 42 +++++++++++++++\n 3 files changed, 61 insertions(+), 4 deletions(-)")
    session("acme-orchestrator", cost_usd=4.27, cost_usd_cached=4.27, context_pct=41, context_tokens=82_000)
    await pause(1.5)
    tool(o, 0, "mcp__orchestra__merge_worker",
         {"name": "fix-double-charge", "task_outcome": "complete",
          "acceptance_note": "48 из 48 тестов прошли; без ключа регрессионный тест падает"},
         "{'status': 'SUCCEEDED', 'commit': 'b81e0d4', 'task': '#2 → done'}")
    with _conn() as c:
        c.execute("UPDATE tm_tasks SET status='done' WHERE title=?",
                   ("Двойное списание после обновления Stripe SDK",))
    await pause(1.2)
    db.add_log(o, ts(0), "text",
               "Смерджил **#2** (`b81e0d4`): с новых заказов больше не спишут деньги дважды. Ничего не выкачено.\n\n"
               "Дальше **#6** — возврат двойных списаний за прошлую неделю. Это движение денег, поэтому жду твоего разрешения.")
    session("acme-orchestrator", cost_usd=4.35, cost_usd_cached=4.35)
