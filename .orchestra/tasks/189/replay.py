"""#189 — базовая линия: сколько сообщений РЕАЛЬНО доезжает до телефона.

Прогоняет настоящий `app.tg_bridge.stream_logs` и настоящую очередь доставки над журналом
за прошедшие сутки, подменяя ТОЛЬКО объект `bot`. Живой Telegram не трогается, живая БД
только читается (снимок через `Connection.backup` делается отдельно, см. README ниже).

## Как повторить (одна команда)

    /home/kesha/orchestra/.venv/bin/python docs/tasks/189/replay.py \
        --snapshot /tmp/snap189.db --day 2026-08-10 --out /tmp/replay189

Снимок готовится так (НЕ `cp` — при WAL копия файла отдаёт устаревший срез):

    .venv/bin/python -c "import sqlite3;\
      s=sqlite3.connect('file:data/orchestra.db?mode=ro',uri=True);\
      d=sqlite3.connect('/tmp/snap189.db');s.backup(d)"

## Почему прогон идёт пачками, а не сутками подряд

Косметика живёт 15 с (`_TG_TELEMETRY_MAX_AGE`), надёжная очередь сливается со скоростью
одно сообщение в 1.05 с (`_TG_GROUP_INTERVAL`). Значит тишина длиннее 180 с гарантированно
опустошает все очереди, и участки журнала, разделённые такой тишиной, НЕЗАВИСИМЫ. Поэтому
сутки режутся на пачки по тишине, каждая проигрывается в реальном времени (масштабировать
время нельзя: TTL сравнивается с часами, а не со сном), а пачки считаются параллельно.
Независимость не постулируется, а ПРОВЕРЯЕТСЯ: в конце каждой пачки все очереди обязаны
быть пусты, иначе прогон падает.

Единица измерения — вызов Bot API, порождающий НОВОЕ сообщение в ленте:
`send_message`. Правки (`edit_message_text`, `edit_message_media`) считаются отдельно:
они меняют уже стоящее сообщение и не удлиняют ленту.
"""
import argparse
import asyncio
import json
import os
import sqlite3
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

# Корень берётся ОТ САМОГО ФАЙЛА, а не из константы: стенд обязан мерить то дерево,
# в котором лежит, иначе замерит чужой код. Наступал на это дважды за одну задачу.
REPO = Path(__file__).resolve().parents[3]      # переопределяется флагом --repo

# Живая карта топиков из data/tg_bridge.json — стримятся ТОЛЬКО эти агенты
TOPICS = {
    "orchestrator": 81207, "Orchestra-orchestrator": 82134,
    "seedon-orchestrator": 118607, "kesha-tg-bot-orchestrator": 118623,
    "Claude-Code-Game-Master-orchestrator": 119152, "dev-lead": 119703,
    "University-orchestrator": 128502, "feat-groom-demo": 131770,
    "perf-codex-runtime": 133139, "fix-groom-proxy": 133810,
    "fix-groom-live": 134017, "fix-groom-models": 134373,
    "fix-groom-conversation": 134649, "fix-groom-render": 135376,
    "fix-groom-operator": 135530,
}
GROUP_ID = -1003760207564
GAP_SECONDS = 180.0
DRAIN_TIMEOUT = 300.0

# Классы — по ведущему значку, как их видит глазами читатель ленты.
# Значки тулов взяты из _TG_TOOL_ICONS / _TG_MCP_ICONS (tg_bridge.py:2061-2069).
_TOOL_ICONS = "🔧🔌🖥📖✏️🔎🌐🤖🔍❓🎼🦜📋🧠📧📝🚀"
CLASSES = {
    **{i: "тул" for i in ("🔧", "🔌", "🖥", "📖", "✏️", "🔎", "🌐", "🤖",
                          "🔍", "❓", "🎼", "🦜", "📋", "🧠", "📧", "📝", "🚀")},
    "💬": "текст оркестратора", "👤": "юзер", "📨": "отчёт воркера",
    "✉️": "задание воркеру", "📎": "результат тулом", "⚡": "статус",
    "❌": "ошибка", "🖼": "картинка", "📷": "картинка", "✅": "sub-agent",
    "⚙️": "⚙️ свёртка хода", "━": "━ якорь конца хода",
}


def classify(text: str) -> str:
    head = text.lstrip()[:2]
    for prefix, name in CLASSES.items():
        if head.startswith(prefix):
            return name
    return "прочее"


def load_rows(snapshot: str, day: str, ids: str = ""):
    conn = sqlite3.connect(f"file:{snapshot}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    q = ",".join("?" * len(TOPICS))
    nxt = f"{day[:8]}{int(day[8:]) + 1:02d}"
    if ids:
        lo, _, hi = ids.partition("-")
        rows = conn.execute(
            f"""SELECT l.id, l.ts, l.type, l.content, l.event_id, l.session_id, s.name agent
                FROM logs l JOIN sessions s ON s.id = l.session_id
                WHERE s.name IN ({q}) AND l.id BETWEEN ? AND ? ORDER BY l.id""",
            (*TOPICS, int(lo), int(hi or lo)),
        ).fetchall()
    else:
        rows = conn.execute(
            f"""SELECT l.id, l.ts, l.type, l.content, l.event_id, l.session_id, s.name agent
                FROM logs l JOIN sessions s ON s.id = l.session_id
                WHERE s.name IN ({q}) AND l.ts >= ? AND l.ts < ?
                ORDER BY l.id""",
            (*TOPICS, day, nxt),
        ).fetchall()
    sessions = conn.execute(
        f"SELECT * FROM sessions WHERE name IN ({q})", tuple(TOPICS)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows], [dict(s) for s in sessions]


def split_bursts(rows):
    bursts, cur = [], [rows[0]]
    for r in rows[1:]:
        gap = (datetime.fromisoformat(r["ts"]).timestamp()
               - datetime.fromisoformat(cur[-1]["ts"]).timestamp())
        if gap > GAP_SECONDS:
            bursts.append(cur)
            cur = []
        cur.append(r)
    bursts.append(cur)
    return bursts


def build_replay_db(path: Path, sessions):
    global REPO
    if path.exists():
        path.unlink()
    for suffix in ("-wal", "-shm"):
        p = Path(str(path) + suffix)
        if p.exists():
            p.unlink()
    os.environ["ORCHESTRA_DB_PATH"] = str(path)
    sys.path.insert(0, str(REPO))
    print(f"дерево под замером: {REPO}", flush=True)
    from app import db

    assert db.DB_PATH == path, f"БД не подменилась: {db.DB_PATH}"
    db.init_db()
    with db._conn() as c:
        cols = [r[1] for r in c.execute("PRAGMA table_info(sessions)")]
        for s in sessions:
            # В проигрываемые сутки агент был жив; сегодня он может быть архивирован, а
            # `get_all_sessions()` архивных НЕ отдаёт — `stream_logs` тогда выходит сразу,
            # и все строки такого агента молча не доезжают. На 10.08 это три воркера и
            # 767 строк из 3339 (23%). Воспроизводим день, а не сегодняшний реестр.
            s = {**s, "status": "idle"}
            vals = [s.get(col) for col in cols]
            c.execute(
                f"INSERT OR REPLACE INTO sessions ({','.join(cols)}) "
                f"VALUES ({','.join('?' * len(cols))})", vals)
        c.execute("DELETE FROM logs")
        c.commit()
    return db


async def run_burst(db, tg, rows, stats):
    """Скармливает пачку в реальном темпе и ждёт, пока поток ДОЧИТАЕТ журнал.

    Ждать одного лишь опустошения очереди недостаточно: `stream_logs` опрашивает журнал
    раз в 2-5 с, и в момент проверки хвост пачки может быть ещё не прочитан — очередь
    пуста просто потому, что работа не началась. Так первый суточный прогон недосчитал
    58 из 254 надёжных сообщений (23%), по хвосту на каждую из 24 пачек. Поэтому сначала
    ждём, что курсор каждого потока прошёл последнюю поданную ему строку, и только потом
    проверяем очередь.
    """
    t0 = datetime.fromisoformat(rows[0]["ts"]).timestamp()
    started = time.monotonic()

    cursors: dict[str, int] = {}
    original_get_logs = db.get_logs

    def watched_get_logs(session_id, after_id=0, limit=5000, conn=None):
        cursors[session_id] = max(cursors.get(session_id, 0), after_id)
        return original_get_logs(session_id, after_id, limit, conn)

    db.get_logs = watched_get_logs
    streams = [
        asyncio.create_task(tg.stream_logs(name, thread))
        for name, thread in TOPICS.items()
    ]
    await asyncio.sleep(0.3)   # дать потокам взять стартовый курсор на пустом журнале

    conn = db._conn()
    for r in rows:
        due = datetime.fromisoformat(r["ts"]).timestamp() - t0
        lag = due - (time.monotonic() - started - 0.3)
        if lag > 0:
            await asyncio.sleep(lag)
        conn.execute(
            "INSERT INTO logs (id, session_id, ts, type, content, event_id) "
            "VALUES (?,?,?,?,?,?)",
            (r["id"], r["session_id"], r["ts"], r["type"], r["content"],
             r["event_id"]),
        )
        conn.commit()
    stats["fed"] += len(rows)

    # 1) поток обязан ДОЧИТАТЬ журнал: курсор прошёл последнюю поданную строку
    last_by_session: dict[str, int] = {}
    for r in rows:
        last_by_session[r["session_id"]] = max(
            last_by_session.get(r["session_id"], 0), r["id"])
    deadline = time.monotonic() + DRAIN_TIMEOUT
    while time.monotonic() < deadline:
        behind = {sid: last for sid, last in last_by_session.items()
                  if cursors.get(sid, 0) < last}
        if not behind:
            break
        await asyncio.sleep(1)
    else:
        raise RuntimeError(f"поток не дочитал журнал за {DRAIN_TIMEOUT} с: {behind}")

    # 2) и только теперь ждём, пока очередь доставит прочитанное
    deadline = time.monotonic() + DRAIN_TIMEOUT
    while time.monotonic() < deadline:
        await asyncio.sleep(3)
        snap = tg._tg_delivery_snapshot(GROUP_ID)
        busy = (snap["reliable_queued"] or snap["telemetry_pending"]
                or snap["optional_queued"] or snap["image_queued"]
                or snap["image_in_flight"] or snap["image_reserved"])
        if os.getenv("REPLAY_DEBUG"):
            print("  drain:", {k: v for k, v in snap.items() if v}, flush=True)
        if not busy:
            break
    else:
        raise RuntimeError(f"очередь не опустела за {DRAIN_TIMEOUT} с: {snap}")

    # Тела, оставшиеся в batch_bucket, — НЕ доставлены: они уедут только со следующим
    # тулом того же агента, возможно в следующем ходу. Это измеряемый дефект (раздел 4
    # research.md), поэтому bucket между пачками НЕ чистится — в проде он тоже не чистится.
    stats["stuck_in_bucket"] = sum(len(b) for b in tg._tg_tool_batches.values())

    db.get_logs = original_get_logs
    for t in streams:
        t.cancel()
    await asyncio.gather(*streams, return_exceptions=True)
    conn.close()
    snap = tg._tg_delivery_snapshot(GROUP_ID)
    for key in ("telemetry_dropped", "telemetry_coalesced", "optional_dropped",
                "image_dropped", "reliable_lost", "telemetry_lost", "image_lost"):
        stats["queue"][key] += snap[key]
    await tg._reset_tg_delivery_state()


def make_bot(stats, latency: float):
    from unittest.mock import AsyncMock
    from types import SimpleNamespace

    counter = {"mid": 0}

    async def send_message(chat_id, text, **kw):
        await asyncio.sleep(latency)
        counter["mid"] += 1
        if os.getenv("REPLAY_DUMP"):
            print(f"\n┌─ СООБЩЕНИЕ #{counter['mid']} ({len(text)} зн)\n"
                  + "\n".join("│ " + ln for ln in text.splitlines()), flush=True)
        cls = classify(text)
        stats["delivered"][cls] += 1
        stats["chars"][cls] += len(text)
        stats["glued"][cls] += sum(text.count("\n\n" + i) for i in _TOOL_ICONS)
        if cls == "прочее":
            stats["unknown_heads"][text.lstrip()[:6]] += 1
        if kw.get("entities"):
            stats["with_entities"] += 1
        else:
            stats["without_entities"] += 1
        return SimpleNamespace(message_id=counter["mid"])

    async def edit_message_text(*a, **kw):
        await asyncio.sleep(latency)
        stats["edits"]["text"] += 1
        if os.getenv("REPLAY_DUMP"):
            body = a[0] if a else kw.get("text", "")
            print(f"\n┌─ ПРАВКА msg#{kw.get('message_id')} ({len(body)} зн)\n"
                  + "\n".join("│ " + ln for ln in str(body).splitlines()), flush=True)
        return SimpleNamespace(message_id=0)

    async def edit_message_media(*a, **kw):
        await asyncio.sleep(latency)
        stats["edits"]["media"] += 1
        return SimpleNamespace(message_id=0)

    async def edit_forum_topic(*a, **kw):
        stats["edits"]["topic"] += 1
        return True

    bot = AsyncMock()
    bot.send_message.side_effect = send_message
    bot.edit_message_text.side_effect = edit_message_text
    bot.edit_message_media.side_effect = edit_message_media
    bot.edit_forum_topic.side_effect = edit_forum_topic
    return bot


async def main_async(args):
    rows, sessions = load_rows(args.snapshot, args.day, args.ids)
    if not rows:
        raise SystemExit("нет строк за этот день")
    bursts = split_bursts(rows)
    idx = ([int(x) for x in args.bursts.split(",") if x.strip() != ""]
           if args.bursts else list(range(len(bursts))))
    picked = [bursts[i] for i in idx]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    tag = "-".join(str(i) for i in idx[:1]) or "all"
    db = build_replay_db(out / f"replay-{tag}.db", sessions)
    import app.tg_bridge as tg

    tg.config = {"group_id": GROUP_ID, "topics": dict(TOPICS),
                 "topic_names": {k: k for k in TOPICS}, "mirrors": {}}
    tg.TG_USER_MENTION = ""          # как в проде: переменной нет в окружении сервиса
    tg._pil_available = None
    os.environ.setdefault("TG_DIFF_IMAGES", "true")
    os.environ.setdefault("TG_RESULT_IMAGES", "true")

    stats = {
        "day": args.day, "bursts": len(picked), "fed": 0,
        "delivered": Counter(), "chars": Counter(), "glued": Counter(),
        "edits": Counter(), "queue": Counter(),
        "with_entities": 0, "without_entities": 0, "latency": args.latency,
        "stuck_in_bucket": 0, "unknown_heads": Counter(),
    }
    tg.bot = make_bot(stats, args.latency)

    for i, burst in enumerate(picked):
        span = (datetime.fromisoformat(burst[-1]["ts"]).timestamp()
                - datetime.fromisoformat(burst[0]["ts"]).timestamp())
        print(f"[{i+1}/{len(picked)}] пачка {burst[0]['ts'][11:19]}, "
              f"{len(burst)} строк, {span/60:.1f} мин", flush=True)
        with db._conn() as c:
            c.execute("DELETE FROM logs")
            c.commit()
        await run_burst(db, tg, burst, stats)

    stats["delivered"] = dict(stats["delivered"])
    stats["chars"] = dict(stats["chars"])
    stats["glued"] = dict(stats["glued"])
    stats["edits"] = dict(stats["edits"])
    stats["queue"] = dict(stats["queue"])
    stats["unknown_heads"] = dict(stats["unknown_heads"])
    stats["burst_ids"] = idx
    (out / f"part-{tag}.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2))
    print(json.dumps(stats, ensure_ascii=False, indent=2))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--snapshot", default="/tmp/snap189.db")
    p.add_argument("--day", default="2026-08-10")
    p.add_argument("--out", default="/tmp/replay189")
    p.add_argument("--bursts", default="",
                   help="номера пачек через запятую; пусто — все подряд")
    p.add_argument("--latency", type=float, default=0.13,
                   help="задержка Bot API, с (живой замер: reliable_last_latency 0.13)")
    p.add_argument("--repo", default="", help="какое дерево мерить (для замера «до»)")
    p.add_argument("--ids", default="", help="диапазон log.id вместо суток, напр. 54907-54956")
    p.add_argument("--list", action="store_true", help="только показать пачки")
    args = p.parse_args()
    if args.list:
        rows, _ = load_rows(args.snapshot, args.day)
        for i, b in enumerate(split_bursts(rows)):
            span = (datetime.fromisoformat(b[-1]["ts"]).timestamp()
                    - datetime.fromisoformat(b[0]["ts"]).timestamp())
            print(f"{i:3} {b[0]['ts'][11:19]} {len(b):5} строк {span/60:6.1f} мин")
        return
    if args.repo:
        globals()["REPO"] = Path(args.repo).resolve()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
