"""#189 — сколько шума между двумя содержательными сообщениями в одном топике.

«Где я остановился» = сколько сообщений надо пролистать от одного 💬 до следующего.
Считает по тем же правилам маппинга, что и measure.py.
"""
import sqlite3
import sys
from collections import defaultdict
from statistics import median

DB = sys.argv[1] if len(sys.argv) > 1 else "/tmp/snap189.db"
SINCE = sys.argv[2] if len(sys.argv) > 2 else "2026-08-10"
UNTIL = sys.argv[3] if len(sys.argv) > 3 else "2026-08-12"

TOPICS = [
    "orchestrator", "Orchestra-orchestrator", "seedon-orchestrator",
    "kesha-tg-bot-orchestrator", "Claude-Code-Game-Master-orchestrator",
    "dev-lead", "University-orchestrator", "feat-groom-demo",
    "perf-codex-runtime", "fix-groom-proxy", "fix-groom-live",
    "fix-groom-models", "fix-groom-conversation", "fix-groom-render",
    "fix-groom-operator",
]
IMG_TOOLS = ("Read", "Grep", "Bash", "Glob")

conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
q = ",".join("?" * len(TOPICS))
rows = conn.execute(
    f"""SELECT s.name AS agent, l.ts, l.type, l.content
        FROM logs l JOIN sessions s ON s.id=l.session_id
        WHERE s.name IN ({q}) AND l.ts>=? AND l.ts<? ORDER BY s.name, l.id""",
    (*TOPICS, SINCE, UNTIL),
).fetchall()

gaps = defaultdict(list)   # agent -> [шумных сообщений между 💬]
chars_gap = defaultdict(list)
noise, noise_ch = defaultdict(int), defaultdict(int)
last_tool = defaultdict(str)

for r in rows:
    a, t, c = r["agent"], r["type"], r["content"]
    if t == "text":
        gaps[a].append(noise[a])
        chars_gap[a].append(noise_ch[a])
        noise[a] = noise_ch[a] = 0
        continue
    n, ch = 0, 0
    if t == "tool":
        name = c.split(":")[0].strip() if ":" in c else "tool"
        last_tool[a] = name
        n, ch = 1, min(len(c), 1250)
    elif t == "tool_result":
        if last_tool.get(a) in IMG_TOOLS:
            n, ch = 1, 0            # картинка
        last_tool[a] = ""
    elif t in ("status", "error"):
        n, ch = 1, len(c)
    elif t == "user_message":
        n, ch = 1, len(c)
    noise[a] += n
    noise_ch[a] += ch

print(f"Шум между двумя 💬 (сообщений / знаков), {SINCE}..{UNTIL}\n")
allg = []
for a in sorted(gaps, key=lambda a: -len(gaps[a])):
    g = gaps[a][1:]         # первый интервал — с начала суток, не показателен
    if not g:
        continue
    cg = chars_gap[a][1:]
    allg += g
    print(f"{a:30} 💬×{len(g):3}  медиана {median(g):5.0f} сообщ / "
          f"{median(cg):6.0f} зн   макс {max(g):4} / {max(cg):7}")
print(f"\nПо всем топикам: медиана {median(allg):.0f}, "
      f"90-й перцентиль {sorted(allg)[int(len(allg)*0.9)]}, макс {max(allg)}")
