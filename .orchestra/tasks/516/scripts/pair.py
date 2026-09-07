"""Строит пары tool -> tool_result из logs и кладёт их в .orchestra/tasks/516/raw/pairs.sqlite.

Правила отнесения (дословно, чтобы можно было перепроверить):
  1. Читаем только type in ('tool','tool_result') из READ-ONLY копии боевой БД.
  2. Имя инструмента:
     - tool_name из колонки, если она непустая;
     - иначе префикс content до первого ': ' (легаси-строки формата "Bash: {json}");
     - строка вида "file: add|update|delete <path>" -> имя FileChange;
     - иначе '<unparsed>'.
  3. Спаривание — два независимых правила, оба считаются и сравниваются:
     - RULE-TUID: точный join по tool_use_id (только там, где он непустой у обеих строк
                  и встречается ровно один раз с каждой стороны).
     - RULE-TS:   FIFO внутри session_id по возрастанию (ts, id): очередь незакрытых
                  tool-строк, каждый tool_result закрывает САМУЮ РАННЮЮ незакрытую.
  4. Длительность = ts(tool_result) - ts(tool) в секундах. Отрицательные сохраняем
     (отсечка делается на анализе, а не здесь), отсечка выброса >600 c — тоже на анализе.
"""
import os
import sqlite3
from datetime import datetime

DB = "file:/home/kesha/orchestra/data/orchestra.db?mode=ro"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "raw", "pairs.sqlite")


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


def main():
    src = sqlite3.connect(DB, uri=True)
    rows = list(
        src.execute(
            "select id, session_id, ts, type, coalesce(tool_use_id,''), "
            "coalesce(tool_name,''), content "
            "from logs where type in ('tool','tool_result') order by session_id, ts, id"
        )
    )
    print(f"rows loaded: {len(rows)}")

    if os.path.exists(OUT):
        os.remove(OUT)
    dst = sqlite3.connect(OUT)
    dst.execute(
        "create table pairs (rule text, session_id text, tool_id int, res_id int,"
        " ts text, tool_name text, dur real, cmd text)"
    )

    # ---- RULE-TUID ----
    tool_by, res_by = {}, {}
    for rid, sid, ts, typ, tuid, tname, content in rows:
        if not tuid:
            continue
        (tool_by if typ == "tool" else res_by).setdefault(tuid, []).append(
            (rid, sid, ts, tname, content)
        )
    tuid_pairs = []
    ambiguous = 0
    for tuid, tl in tool_by.items():
        rl = res_by.get(tuid)
        if not rl:
            continue
        if len(tl) != 1 or len(rl) != 1:
            ambiguous += 1
            continue
        rid, sid, ts, tname, content = tl[0]
        rrid, _, rts, _, _ = rl[0]
        dur = (parse(rts) - parse(ts)).total_seconds()
        tuid_pairs.append(
            ("tuid", sid, rid, rrid, ts, tool_name_of(tname, content), dur, content)
        )

    # ---- RULE-TS ----
    ts_pairs = []
    cur_sid, queue = None, []
    for rid, sid, ts, typ, tuid, tname, content in rows:
        if sid != cur_sid:
            cur_sid, queue = sid, []
        if typ == "tool":
            queue.append((rid, ts, tname, content))
        elif queue:
            trid, tts, tname_t, content_t = queue.pop(0)
            ts_pairs.append(
                (
                    "ts",
                    sid,
                    trid,
                    rid,
                    tts,
                    tool_name_of(tname_t, content_t),
                    (parse(ts) - parse(tts)).total_seconds(),
                    content_t,
                )
            )

    dst.executemany("insert into pairs values (?,?,?,?,?,?,?,?)", tuid_pairs)
    dst.executemany("insert into pairs values (?,?,?,?,?,?,?,?)", ts_pairs)
    dst.execute("create index i1 on pairs(rule, tool_name)")
    dst.execute("create index i2 on pairs(rule, dur)")
    dst.commit()
    print(f"tuid pairs: {len(tuid_pairs)} (ambiguous tuid groups skipped: {ambiguous})")
    print(f"ts   pairs: {len(ts_pairs)}")


if __name__ == "__main__":
    main()
