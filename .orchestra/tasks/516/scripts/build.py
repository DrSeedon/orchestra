"""Финальный датасет пар tool->tool_result -> .orchestra/tasks/516/raw/calls.sqlite.

Правило спаривания (дословно):
  - если у tool-строки непустой tool_use_id и он встречается ровно один раз среди tool
    и ровно один раз среди tool_result -> пара берётся по нему (RULE-TUID, точная);
  - все остальные tool-строки спариваются правилом LIFO внутри session_id в порядке
    (ts, id): очередь незакрытых tool-строк, каждый tool_result закрывает САМУЮ ПОЗДНЮЮ
    незакрытую (RULE-LIFO). Точность LIFO измерена на размеченной части: 96.0 %
    верного res_id, ошибка суммы времени -0.3 % (.orchestra/tasks/516/raw/07-calibration.txt).

Имя инструмента: колонка tool_name; если пуста — префикс content до ': ';
"file: ..." -> FileChange; иначе '<unparsed>'. Имена приводятся к нижнему регистру
для склейки рантаймов (Bash/bash, Read/read_file и т.п. остаются РАЗНЫМИ строками —
склейка делается на этапе классификации, а не здесь).

Длительность = ts(tool_result) - ts(tool), секунды.
"""
import json
import os
import sqlite3
from datetime import datetime

DB = "file:/home/kesha/orchestra/data/orchestra.db?mode=ro"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "raw", "calls.sqlite")


def parse(ts):
    return datetime.fromisoformat(ts)


def tool_name_of(col, content):
    if col:
        return col
    head = content[:120]
    if head.startswith("file: "):
        return "FileChange"
    i = head.find(": ")
    if 0 < i < 60 and " " not in head[:i]:
        return head[:i]
    return "<unparsed>"


def command_of(name, content):
    """Достаёт текст команды из аргументов bash-подобных тулов, иначе ''."""
    i = content.find(": ")
    if i < 0:
        return ""
    try:
        args = json.loads(content[i + 2 :])
    except Exception:
        return ""
    if not isinstance(args, dict):
        return ""
    for k in ("command", "cmd", "script", "shell_command"):
        v = args.get(k)
        if isinstance(v, str):
            return v
    return ""


def main():
    src = sqlite3.connect(DB, uri=True)
    rows = list(
        src.execute(
            "select id, session_id, ts, type, coalesce(tool_use_id,''), "
            "coalesce(tool_name,''), content, coalesce(tool_is_error,0) "
            "from logs where type in ('tool','tool_result') order by session_id, ts, id"
        )
    )

    # ---- шаг 1: точные пары по tool_use_id ----
    tool_by, res_by = {}, {}
    for rid, sid, ts, typ, tuid, tname, content, err in rows:
        if not tuid:
            continue
        (tool_by if typ == "tool" else res_by).setdefault(tuid, []).append(rid)
    exact = {}  # tool_id -> res_id
    exact_res = set()
    for tuid, tl in tool_by.items():
        rl = res_by.get(tuid)
        if rl and len(tl) == 1 and len(rl) == 1:
            exact[tl[0]] = rl[0]
            exact_res.add(rl[0])

    meta = {r[0]: r for r in rows}

    # ---- шаг 2: LIFO по остатку ----
    pairs = []  # (tool_id, res_id, rule)
    for tid, rid in exact.items():
        pairs.append((tid, rid, "tuid"))

    cur_sid, stack = None, []
    for rid, sid, ts, typ, tuid, tname, content, err in rows:
        if sid != cur_sid:
            cur_sid, stack = sid, []
        if typ == "tool":
            if rid not in exact:
                stack.append(rid)
        elif rid not in exact_res and stack:
            pairs.append((stack.pop(), rid, "lifo"))

    out_rows = []
    for tid, rid, rule in pairs:
        _, sid, tts, _, _, tname, content, _ = meta[tid]
        _, _, rts, _, _, _, rcontent, rerr = meta[rid]
        name = tool_name_of(tname, content)
        out_rows.append(
            (
                tid,
                rid,
                rule,
                sid,
                tts,
                (parse(rts) - parse(tts)).total_seconds(),
                name,
                command_of(name, content),
                content[:4000],
                rerr,
                len(rcontent),
            )
        )

    if os.path.exists(OUT):
        os.remove(OUT)
    dst = sqlite3.connect(OUT)
    dst.execute(
        "create table calls (tool_id int primary key, res_id int, rule text,"
        " session_id text, ts text, dur real, tool_name text, cmd text,"
        " args text, is_error int, res_len int)"
    )
    dst.executemany("insert into calls values (?,?,?,?,?,?,?,?,?,?,?)", out_rows)
    dst.execute("create index i1 on calls(tool_name)")
    dst.execute("create index i2 on calls(dur)")
    dst.execute("create index i3 on calls(session_id, ts)")
    dst.commit()
    print(f"пар всего: {len(out_rows)}  (tuid {len(exact)}, lifo {len(out_rows)-len(exact)})")
    for r in dst.execute(
        "select count(*), round(sum(dur)/3600,2) from calls where dur>=0 and dur<=600"
    ):
        print(f"с отсечкой 0<=dur<=600: пар {r[0]}, часов {r[1]}")
    for r in dst.execute("select sum(dur<0), sum(dur>600) from calls"):
        print(f"отброшено: отрицательных {r[0]}, >600 c {r[1]}")


if __name__ == "__main__":
    main()
