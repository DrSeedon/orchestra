"""V-685: исход компактов по простою у Claude — data/orchestra.db, read-only.

Без компакта возврат после ≥60 мин простоя (от последней активности) перезаписывает весь
контекст pre_tokens; до 60 мин читает горячий кеш (≈0). С компактом: свежая сессия пишет
post_tokens сразу, и ещё раз, если возврат позже 60 мин от самого компакта.
"""
import json, sqlite3, statistics as st, sys
from datetime import datetime as D
c = sqlite3.connect("file:/home/kesha/orchestra/data/orchestra.db?mode=ro", uri=True)
rows = c.execute("select ts,content from logs where type='status' and content like 'precompact timer outcome: %' order by ts").fetchall()
cl = []
for ts, s in rows:
    p = json.loads(s.split(": ", 1)[1])
    r = p.get("compact_result") or {}
    if p.get("backend") == "claude" and r.get("ok") and "pre_tokens" in r and p.get("next_activity"):
        cl.append((ts, p, r))
print("events", len(rows), "claude ok with tokens+next", len(cl), "from", cl[0][0], "to", cl[-1][0])
without = with_ = cross = 0
for ts, p, r in cl:
    sch, fi, n = (D.fromisoformat(p[k]) for k in ("scheduled_at", "fired_at", "next_activity"))
    with_ += r["post_tokens"]
    if (n - sch).total_seconds() >= 3600:
        cross += 1
        without += r["pre_tokens"]
    if (n - fi).total_seconds() >= 3600:
        with_ += r["post_tokens"]
print("returns after cache expiry", cross)
print("W without compaction", without, "pp", round(0.604 * without / 1e6, 2))
print("W with compaction", with_, "pp", round(0.604 * with_ / 1e6, 2))
print("median pre", st.median(r["pre_tokens"] for *_, r in cl), "median post", st.median(r["post_tokens"] for *_, r in cl))
print("median pct", st.median(r["before_pct"] for *_, r in cl), "->", st.median(r["after_pct"] for *_, r in cl))
idle = [(D.fromisoformat(p["next_activity"]) - D.fromisoformat(p["scheduled_at"])).total_seconds() / 60 for _, p, _ in cl]
print("median idle min", round(st.median(idle)))
chars = sum(r.get("summary_chars", 0) for *_, r in cl)
# Пересказ — выход модели (1,81 п.п./М по V-605, коэффициент ненадёжный); токен ≈ 3 знака — грубо.
print("summary chars", chars, "≈ output tokens", chars // 3, "pp", round(1.81 * chars / 3 / 1e6, 2))
