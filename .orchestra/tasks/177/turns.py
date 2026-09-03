"""Ходы full-cycle сессий: активное время, tool-вызовы, фаза.

Ход = user_message ... 'turn ended'. Активное время = сумма длительностей ходов
(простой между ходами не считается). Фаза определяется по последовательности гейтов
внутри прогона задачи: до RESEARCH DONE — research, до PLAN READY — plan, дальше — impl.

TSV: session, task, phase, turn_no, minutes, tools, codex_calls, cost, gap_before_min
"""
import re
import sqlite3
from datetime import datetime

DB = "/home/kesha/orchestra/data/snap177.db"
con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
RE_TURN = re.compile(r"turn ended \(([^,]+),")
RE_TASK = re.compile(r"#(\d+)")


def ts(s):
    return datetime.fromisoformat(s.replace(" ", "T"))


rows = con.execute(
    """select s.name, l.ts, l.type, substr(l.content,1,300)
       from logs l join sessions s on s.id=l.session_id
       where s.role='full-cycle' order by s.name, l.id"""
).fetchall()

by_sess = {}
for name, t, typ, content in rows:
    by_sess.setdefault(name, []).append((ts(t), typ, content))

print("session\ttask\tphase\tminutes\ttools\tcodex\tgap_before\tstart\tmarker")
for name, evs in by_sess.items():
    phase = "P1-research"
    task = ""
    cur = None          # текущий ход
    prev_end = None
    for t, typ, content in evs:
        if typ == "user_message":
            if cur is None:
                m = RE_TASK.search(content)
                # новая задача после DONE
                if phase == "done" and m:
                    task, phase = m.group(1), "P1-research"
                elif not task and m:
                    task = m.group(1)
                gap = (t - prev_end).total_seconds() / 60 if prev_end else 0
                cur = {"start": t, "tools": 0, "codex": 0, "gap": gap, "marker": ""}
        elif cur is not None and typ == "tool":
            cur["tools"] += 1
            if "codex_review" in content[:60]:
                cur["codex"] += 1
        elif cur is not None and typ == "text":
            head = content[:300].upper()
            if "RESEARCH DONE" in head:
                cur["marker"] = "RESEARCH-DONE"
            elif "PLAN READY" in head:
                cur["marker"] = "PLAN-READY"
            elif re.search(r"\bDONE #", head):
                cur["marker"] = "DONE"
            if cur["marker"]:
                m = RE_TASK.search(content[:300])
                if m:
                    task = m.group(1)
        elif typ == "status" and RE_TURN.search(content) and cur is not None:
            mins = (t - cur["start"]).total_seconds() / 60
            print(f"{name}\t{task}\t{phase}\t{mins:.0f}\t{cur['tools']}\t{cur['codex']}"
                  f"\t{cur['gap']:.0f}\t{cur['start']:%m-%d %H:%M}\t{cur['marker']}")
            if cur["marker"] == "RESEARCH-DONE":
                phase = "P2-plan"
            elif cur["marker"] == "PLAN-READY":
                phase = "P3-impl"
            elif cur["marker"] == "DONE":
                phase = "done"
            prev_end = t
            cur = None
