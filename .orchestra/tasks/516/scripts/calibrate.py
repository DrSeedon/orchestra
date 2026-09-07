"""Калибровка эвристик спаривания против ground truth (tool_use_id).

Ground truth: пары, где tool_use_id непуст и встречается ровно один раз с каждой стороны.
Проверяем эвристики ТОЛЬКО на тех строках, у которых ground truth известен, и считаем
две метрики: доля верно угаданного res_id и ошибка суммарного времени в часах.

Эвристики:
  H1  FIFO по всей сессии (очередь незакрытых tool, результат закрывает самый ранний).
  H2  FIFO, но перед закрытием выкидываем из очереди всё старше W секунд.
  H3  LIFO: результат закрывает САМЫЙ ПОЗДНИЙ незакрытый tool.
  H4  FIFO с сбросом очереди на границе хода: любая строка logs, которая не tool
      и не tool_result (text/thinking/status/user_message/...), обнуляет очередь.
"""
import sqlite3
from datetime import datetime

DB = "file:/home/kesha/orchestra/data/orchestra.db?mode=ro"


def parse(ts):
    return datetime.fromisoformat(ts)


def load():
    c = sqlite3.connect(DB, uri=True)
    return list(
        c.execute(
            "select id, session_id, ts, type, coalesce(tool_use_id,'') "
            "from logs order by session_id, ts, id"
        )
    )


def ground_truth(rows):
    tool_by, res_by = {}, {}
    for rid, sid, ts, typ, tuid in rows:
        if not tuid or typ not in ("tool", "tool_result"):
            continue
        (tool_by if typ == "tool" else res_by).setdefault(tuid, []).append((rid, ts))
    gt = {}
    for tuid, tl in tool_by.items():
        rl = res_by.get(tuid)
        if rl and len(tl) == 1 and len(rl) == 1:
            gt[tl[0][0]] = (rl[0][0], (parse(rl[0][1]) - parse(tl[0][1])).total_seconds())
    return gt


def run(rows, mode, window=60.0):
    """Возвращает {tool_id: (res_id, dur)} по эвристике."""
    out, cur_sid, queue = {}, None, []
    for rid, sid, ts, typ, _ in rows:
        if sid != cur_sid:
            cur_sid, queue = sid, []
        if typ == "tool":
            queue.append((rid, ts))
        elif typ == "tool_result":
            if mode == "H2":
                t = parse(ts)
                queue = [q for q in queue if (t - parse(q[1])).total_seconds() <= window]
            if not queue:
                continue
            trid, tts = queue.pop(-1 if mode == "H3" else 0)
            out[trid] = (rid, (parse(ts) - parse(tts)).total_seconds())
        elif mode == "H4":
            queue = []
    return out


def report(name, got, gt):
    common = set(got) & set(gt)
    if not common:
        print(f"{name:8} нет пересечения")
        return
    ok = sum(1 for k in common if got[k][0] == gt[k][0])
    gh = sum(gt[k][1] for k in common) / 3600
    hh = sum(got[k][1] for k in common) / 3600
    # с отсечкой выброса >600 c, как договорено
    ghc = sum(gt[k][1] for k in common if 0 <= gt[k][1] <= 600) / 3600
    hhc = sum(got[k][1] for k in common if 0 <= got[k][1] <= 600) / 3600
    print(
        f"{name:8} совпало res_id {ok}/{len(common)} = {ok/len(common)*100:5.1f}%  "
        f"| часы: истина {gh:8.2f} эвристика {hh:12.2f}  "
        f"| с отсечкой 600c: истина {ghc:7.2f} эвристика {hhc:7.2f}"
    )


if __name__ == "__main__":
    rows = load()
    gt = ground_truth(rows)
    print(f"ground truth пар: {len(gt)}")
    report("H1 FIFO", run(rows, "H1"), gt)
    for w in (10, 60, 600):
        report(f"H2 w={w}", run(rows, "H2", w), gt)
    report("H3 LIFO", run(rows, "H3"), gt)
    report("H4 turn", run(rows, "H4"), gt)
