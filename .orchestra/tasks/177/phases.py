"""Разбор ходов full-cycle сессий по фазам.

События: user_message (U) — входящее сообщение; 'turn ended' в status — конец хода
(оттуда же берётся стоимость хода); text с RESEARCH DONE / PLAN READY / DONE — гейт.

Сегмент = отрезок между гейтами. Печатает TSV: сессия, задача, фаза, ходы, минуты,
tool-вызовы, $.
"""
import re
import sqlite3
from datetime import datetime

DB = "/home/kesha/orchestra/data/snap177.db"
con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)

RE_TURN = re.compile(r"turn ended \(([^,]+), (\d+) turns, \$([\d.]+) turn")
RE_TASK = re.compile(r"#(\d+)")


def ts(s):
    return datetime.fromisoformat(s.replace(" ", "T"))


def marker(txt):
    head = txt[:400].upper()
    if "RESEARCH DONE" in head:
        return "R"
    if "PLAN READY" in head:
        return "P"
    if re.search(r"\bDONE\b", head) and "RESEARCH DONE" not in head:
        return "D"
    return None


rows = con.execute(
    """select s.name, l.ts, l.type, substr(l.content,1,400)
       from logs l join sessions s on s.id=l.session_id
       where s.role='full-cycle' order by s.name, l.ts"""
).fetchall()

by_sess = {}
for name, t, typ, content in rows:
    by_sess.setdefault(name, []).append((ts(t), typ, content))

print("session\ttask\tphase\tturns\tminutes\ttools\tcost\tstart\tend")
for name, evs in by_sess.items():
    seg = {"turns": 0, "tools": 0, "cost": 0.0, "start": None, "kind": "P1?"}
    task = ""

    def flush(end_t, kind):
        if seg["start"] is None or seg["turns"] == 0:
            return
        mins = (end_t - seg["start"]).total_seconds() / 60
        print(f"{name}\t{task}\t{kind}\t{seg['turns']}\t{mins:.0f}\t{seg['tools']}"
              f"\t{seg['cost']:.2f}\t{seg['start']:%m-%d %H:%M}\t{end_t:%m-%d %H:%M}")

    for t, typ, content in evs:
        if seg["start"] is None:
            seg["start"] = t
        if typ == "tool":
            seg["tools"] += 1
        elif typ == "user_message":
            if seg["kind"].startswith("GATE"):
                # гейт закрыт ответом оркестратора
                flush(t, seg["kind"])
                nxt = {"GATE-R": "P2-plan", "GATE-P": "P3-impl"}[seg["kind"]]
                seg = {"turns": 0, "tools": 0, "cost": 0.0, "start": t, "kind": nxt}
            elif seg["kind"] == "after-DONE":
                m = RE_TASK.search(content)
                task = m.group(1) if m else ""
                seg = {"turns": 0, "tools": 0, "cost": 0.0, "start": t, "kind": "P1-research"}
            elif seg["kind"] == "P1?":
                m = RE_TASK.search(content)
                if m:
                    task = m.group(1)
                seg["kind"] = "P1-research"
        elif typ == "status":
            m = RE_TURN.search(content)
            if m:
                seg["turns"] += 1
                seg["cost"] += float(m.group(3))
        elif typ == "text":
            mk = marker(content)
            if mk:
                m = RE_TASK.search(content[:400])
                if m:
                    task = m.group(1)
                if mk == "R":
                    flush(t, seg["kind"])
                    seg = {"turns": 0, "tools": 0, "cost": 0.0, "start": t, "kind": "GATE-R"}
                elif mk == "P":
                    flush(t, seg["kind"])
                    seg = {"turns": 0, "tools": 0, "cost": 0.0, "start": t, "kind": "GATE-P"}
                elif mk == "D":
                    flush(t, seg["kind"])
                    seg = {"turns": 0, "tools": 0, "cost": 0.0, "start": t, "kind": "after-DONE"}
    if evs:
        flush(evs[-1][0], seg["kind"])
