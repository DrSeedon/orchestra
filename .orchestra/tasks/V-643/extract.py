"""V-643: выгрузка сегментов «до компакта» из КОПИИ боевой БД (data/snap.db, sqlite backup()).

Кейс = один реальный прод-компакт: сегмент журнала от предыдущей преамбулы компакта
(она тоже была в контексте) до преамбулы этого компакта. Из преамбулы берём реальную
прод-сводку и дословный хвост — это и есть базовая линия «как сейчас».

python extract.py list            — кандидаты с размерами сжатого транскрипта
python extract.py dump <log_id>.. — выгрузить кейсы в data/v643/cases/
python extract.py cut <session_name> <n_logs> — синтетический кейс без прод-компакта
"""
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DB = ROOT / "data" / "snap.db"
OUT = ROOT / "data" / "v643" / "cases"
SPEECH = ("user_message", "text", "tool", "tool_result")


def db():
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True)


def render(rows, *, tool_in=300, tool_out=600, user_cap=30000):
    """Сжатый транскрипт: речь целиком, вызовы и результаты инструментов усечены."""
    out = []
    for lid, ts, typ, content, tool_name, is_err in rows:
        head = f"[#{lid} {ts[:16]}]"
        if typ == "user_message":
            c = content if len(content) <= user_cap else content[:user_cap] + f"\n…[+{len(content)-user_cap} chars]"
            out.append(f"{head} USER:\n{c}")
        elif typ == "text":
            out.append(f"{head} ASSISTANT:\n{content}")
        elif typ == "tool":
            c = content[:tool_in] + ("…" if len(content) > tool_in else "")
            out.append(f"{head} TOOL_CALL {tool_name or ''}: {c}")
        elif typ == "tool_result":
            c = content[:tool_out] + (f"…[+{len(content)-tool_out}]" if len(content) > tool_out else "")
            out.append(f"{head} TOOL_RESULT{' (error)' if is_err else ''}: {c}")
    return "\n\n".join(out)


def split_preamble(content):
    body = content.split("\n\n", 1)[1] if "\n\n" in content else content
    summary, _, rest = body.partition("[END OF SUMMARY]")
    tail = ""
    m = re.search(r"\[VERBATIM TAIL[^\]]*\]\n\n(.*?)\n\n\[END OF TAIL\]", rest, re.S)
    if m:
        tail = m.group(1)
    return summary.strip(), tail


def compacts():
    c = db()
    rows = c.execute(
        """select l.id,l.session_id,s.name,s.scope,s.backend_type,s.model,l.ts from logs l
        join sessions s on s.id=l.session_id where l.type='user_message'
        and l.content like '[PREVIOUS CONTEXT SUMMARY%' order by l.session_id,l.id"""
    ).fetchall()
    prev, res = {}, []
    for cid, sid, name, scope, bt, model, ts in rows:
        res.append(dict(cid=cid, start=prev.get(sid, 0), sid=sid, name=name, scope=scope,
                        backend=bt, model=model, ts=ts))
        prev[sid] = cid
    return res


def seg_rows(c, sid, start, end):
    return c.execute(
        f"select id,ts,type,content,tool_name,tool_is_error from logs where session_id=? and id>=? and id<? "
        f"and type in ({','.join('?'*len(SPEECH))}) order by id",
        (sid, start, end, *SPEECH),
    ).fetchall()


def cmd_list():
    c = db()
    for k in compacts():
        if k["ts"] < "2026-09-01":
            continue
        rows = seg_rows(c, k["sid"], k["start"], k["cid"])
        n_user = sum(r[2] == "user_message" for r in rows)
        size = len(render(rows))
        print(f"{k['cid']}\t{k['name']}\t{k['backend']}\t{k['model']}\t{k['ts'][:16]}\tusers={n_user}\tcondensed={size}")


def write_case(case_id, meta, rows, real_summary, tail):
    d = OUT / case_id
    (d / "journal").mkdir(parents=True, exist_ok=True)
    (d / "transcript.md").write_text(render(rows))
    # Полный журнал для агентного метода: результаты инструментов режем по 4000,
    # иначе base64-картинки и дампы по мегабайту раздувают файлы без смысла.
    full = render(rows, tool_in=2000, tool_out=4000, user_cap=10**9)
    chunks, cur, size = [], [], 0
    for part in full.split("\n\n[#"):
        cur.append(part)
        size += len(part)
        if size > 60000:
            chunks.append(cur); cur, size = [], 0
    if cur:
        chunks.append(cur)
    index = []
    for i, ch in enumerate(chunks, 1):
        text = "\n\n[#".join(ch)
        if i > 1:
            text = "[#" + text
        name = f"chunk_{i:03d}.md"
        (d / "journal" / name).write_text(text)
        first = re.search(r"\[#(\d+) ([^\]]+)\]", text)
        index.append(f"{name}\t{len(text)} chars\tfrom {first.group(1) if first else '?'} {first.group(2) if first else ''}")
    (d / "journal" / "INDEX.md").write_text("\n".join(index) + "\n")
    with open(d / "journal" / "journal.jsonl", "w") as f:
        for lid, ts, typ, content, tool_name, is_err in rows:
            f.write(json.dumps(dict(id=lid, ts=ts, type=typ, tool=tool_name, error=bool(is_err),
                                    content=content[:20000]), ensure_ascii=False) + "\n")
    (d / "real_summary.md").write_text(real_summary)
    (d / "tail.md").write_text(tail)
    meta.update(n_rows=len(rows), condensed_chars=len(render(rows)), chunks=len(chunks),
                real_summary_chars=len(real_summary), tail_chars=len(tail))
    (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    print(case_id, meta["condensed_chars"], len(chunks))


def cmd_dump(ids):
    c = db()
    ks = {k["cid"]: k for k in compacts()}
    for cid in map(int, ids):
        k = ks[cid]
        rows = seg_rows(c, k["sid"], k["start"], k["cid"])
        content = c.execute("select content from logs where id=?", (cid,)).fetchone()[0]
        summary, tail = split_preamble(content)
        write_case(f"{k['name']}-{cid}", dict(k), rows, summary, tail)


def cmd_cut(name, n):
    """Сессия без прод-компакта: режем после n-й записи речи, хвост строим как _preserved_tail."""
    c = db()
    sid, scope, bt, model = c.execute("select id,scope,backend_type,model from sessions where name=? order by created_at desc", (name,)).fetchone()
    rows = seg_rows(c, sid, 0, 10**12)[: int(n)]
    parts, total = [], 0
    for lid, ts, typ, content, *_ in reversed(rows):
        if typ not in ("user_message", "text"):
            continue
        label = "USER" if typ == "user_message" else "ASSISTANT"
        entry = f"{label}: {content}"
        if total + len(entry) > 12000:
            break
        parts.append(entry); total += len(entry)
    tail = "\n\n".join(reversed(parts))
    write_case(f"{name}-cut{n}", dict(cid=None, sid=sid, name=name, scope=scope, backend=bt, model=model,
                                      ts=rows[-1][1]), rows, "", tail)


if __name__ == "__main__":
    {"list": lambda: cmd_list(), "dump": lambda: cmd_dump(sys.argv[2:]),
     "cut": lambda: cmd_cut(*sys.argv[2:4])}[sys.argv[1]]()
