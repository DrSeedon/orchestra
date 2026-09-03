"""#189 — сколько сообщений и знаков реально уходит в Telegram.

Читает СНИМОК живой БД (Connection.backup), не саму БД.
Моделирует stream_logs() из app/tg_bridge.py: одна строка logs → N сообщений в TG.
"""
import sqlite3
import sys
from collections import defaultdict

DB = sys.argv[1] if len(sys.argv) > 1 else "/tmp/snap189.db"
DAY = sys.argv[2] if len(sys.argv) > 2 else "2026-08-10"

# Кто реально стримится в TG — ключи data/tg_bridge.json["topics"]
TOPICS = [
    "orchestrator", "Orchestra-orchestrator", "seedon-orchestrator",
    "kesha-tg-bot-orchestrator", "Claude-Code-Game-Master-orchestrator",
    "dev-lead", "University-orchestrator", "feat-groom-demo",
    "perf-codex-runtime", "fix-groom-proxy", "fix-groom-live",
    "fix-groom-models", "fix-groom-conversation", "fix-groom-render",
    "fix-groom-operator",
]

TG_MSG_LIMIT = 4096
IMG_TOOLS = ("Read", "Grep", "Bash", "Glob")   # _send_result_image
DIFF_TOOLS = ("Edit", "Write")                  # _send_diff_image

conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
q = ",".join("?" * len(TOPICS))
rows = conn.execute(
    f"""SELECT s.name AS agent, l.ts, l.type, l.content
        FROM logs l JOIN sessions s ON s.id = l.session_id
        WHERE s.name IN ({q}) AND l.ts >= ? AND l.ts < ?
        ORDER BY s.name, l.id""",
    (*TOPICS, DAY, DAY[:8] + f"{int(DAY[8:]) + 1:02d}"),
).fetchall()


class Acc:
    def __init__(self):
        self.msgs = defaultdict(int)     # класс сообщения -> штук
        self.chars = defaultdict(int)    # класс -> знаков в TG
        self.images = defaultdict(int)   # какой тул породил картинку


per_agent = defaultdict(Acc)
last_tool = defaultdict(str)     # agent -> имя последнего тула
tool_msg_open = defaultdict(bool)  # agent -> есть незакрытое expandable


def add(a, kind, n_msgs, n_chars):
    per_agent[a].msgs[kind] += n_msgs
    per_agent[a].chars[kind] += n_chars


for r in rows:
    a, t, c = r["agent"], r["type"], r["content"]
    if t == "user_message":
        add(a, "user_message", 1, len(c))
    elif t == "text":
        chunks = max(1, -(-len(c) // TG_MSG_LIMIT))
        add(a, "text", chunks, len(c))
    elif t == "tool":
        name = c.split(":")[0].strip() if ":" in c else "tool"
        body = c[len(name) + 1:].strip()[:1200] if ":" in c else c[:1200]
        add(a, "tool_call", 1, len(body) + len(name) + 4)
        last_tool[a] = name
        tool_msg_open[a] = True
        if name in DIFF_TOOLS:
            add(a, "image", 1, 0)
            per_agent[a].images[name] += 1
    elif t == "tool_result":
        name = last_tool.get(a, "")
        if name in IMG_TOOLS:
            add(a, "image", 1, 0)
            per_agent[a].images[name] += 1
            tool_msg_open[a] = False   # результат ушёл картинкой, текст не дописан
        elif tool_msg_open[a]:
            add(a, "tool_result_edit", 0, min(len(c), 800))  # правка на месте
            tool_msg_open[a] = False
        else:
            add(a, "tool_result_new", 1, min(len(c), 800))
        last_tool[a] = ""
    elif t == "status":
        add(a, "status", 1, len(c) + 2)
    elif t == "error":
        add(a, "error", 1, len(c) + 2)
    elif t == "subagent_end":
        add(a, "subagent_end", 1, 80)

print(f"=== {DAY}, топиков с активностью: {len(per_agent)} ===\n")
tot = Acc()
for a, acc in sorted(per_agent.items(), key=lambda kv: -sum(kv[1].msgs.values())):
    m = sum(acc.msgs.values())
    ch = sum(acc.chars.values())
    print(f"{a:32} {m:5} сообщ  {ch:8} знаков")
    for k in sorted(acc.msgs, key=lambda k: -acc.msgs[k]):
        print(f"    {k:18} {acc.msgs[k]:5}  {acc.chars[k]:8}")
        tot.msgs[k] += acc.msgs[k]
        tot.chars[k] += acc.chars[k]
    if acc.images:
        print(f"    картинки по тулам: {dict(acc.images)}")
    for k, v in acc.images.items():
        tot.images[k] += v
    print()

M, C = sum(tot.msgs.values()), sum(tot.chars.values())
print(f"=== ВСЕГО {M} сообщений, {C} знаков ===")
for k in sorted(tot.msgs, key=lambda k: -tot.msgs[k]):
    print(f"  {k:18} {tot.msgs[k]:5} ({tot.msgs[k]*100//M:2}%)  {tot.chars[k]:8} ({tot.chars[k]*100//C:2}%)")
print(f"  картинки по тулам: {dict(tot.images)}")
