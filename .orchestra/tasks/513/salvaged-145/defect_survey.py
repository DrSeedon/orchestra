"""#145 — характеристика дефектов ДО замера (не зависит от него).

Три отдельных дефекта, найденных при разборе `_chunk_markdown`. Считаем масштаб каждого,
чтобы решение по фазе 2 опиралось на цифры, а не на «код есть — значит должен работать».
"""
import os, re, sqlite3, statistics as st, sys

ROOT = "/mnt/data/Projects/Python/orchestra"
sys.path.insert(0, ROOT)
src = open(os.path.join(ROOT, "app/rag.py")).read()
ns = {}
exec(compile(src[:src.index("def _classify_log")].replace("import sqlite_vec", ""), "h", "exec"), ns)
HR, MD_MAX, MD_MIN = ns["_HEADING_RE"], ns["MD_MAX_CHUNK"], ns["MD_MIN_MERGE"]
_sp, _ch, _cm = ns["_split_paragraphs"], ns["_chunk"], ns["_chunk_markdown"]
FENCE = re.compile(r"^\s*(```|~~~)")
HEAD = re.compile(r"^\s*#{1,6}\s+")


def sections(content, fence_aware):
    lines, out, stack, buf, crumb, inf = content.split("\n"), [], [], [], "", False
    def flush():
        t = "\n".join(buf).strip()
        if t: out.append((crumb, t))
    for line in lines:
        if fence_aware and FENCE.match(line):
            inf = not inf; buf.append(line); continue
        m = HR.match(line)
        if m and not (fence_aware and inf):
            flush(); buf.clear()
            lv = len(m.group(1)); ti = m.group(2).strip()
            while stack and stack[-1][0] >= lv: stack.pop()
            stack.append((lv, ti)); crumb = " > ".join(t for _, t in stack)
        buf.append(line)
    flush()
    return out


def chunk(content, crumb_on, fence_aware):
    secs = sections(content, fence_aware)
    if not secs:
        return [(c, "") for c in (_sp(content, MD_MAX) or _ch(content))]
    res, pending, pcr = [], "", ""
    for cr, text in secs:
        if len(text) > MD_MAX:
            if pending: res.append((pending.strip(), pcr)); pending = ""
            for p in _sp(text, MD_MAX): res.append((p, cr))
            continue
        if pending and len(pending) + len(text) + 2 > MD_MAX:
            res.append((pending.strip(), pcr)); pending, pcr = text, cr
        else:
            if not pending: pcr = cr
            pending = (pending + "\n\n" + text) if pending else text
        if len(pending) >= MD_MIN: res.append((pending.strip(), pcr)); pending = ""
    if pending.strip(): res.append((pending.strip(), pcr))
    return res


conn = sqlite3.connect(f"file:{ROOT}/data/bench134/vec134.db?mode=ro", uri=True)
paths = [r[0] for r in conn.execute(
    "SELECT DISTINCT f.path FROM files f JOIN file_chunks fc ON fc.file_id=f.file_id WHERE f.project=?",
    (ROOT,))]

tot = orph = deco = 0
fake_head = real_head = 0
files_fake = set()
crumb_changes = 0          # D2: does fence-awareness change the crumb text?
sect_changes = 0           # D3: does fence-awareness change SECTION BOUNDARIES (prod today)?
crumb_lens = []
for p in paths:
    if not p.endswith(".md"): continue
    fp = os.path.join(ROOT, p)
    if not os.path.exists(fp): continue
    c = open(fp, encoding="utf-8", errors="replace").read()
    if not c.strip(): continue
    inf = False
    for l in c.split("\n"):
        if FENCE.match(l): inf = not inf; continue
        if HR.match(l):
            if inf: fake_head += 1; files_fake.add(p)
            else: real_head += 1
    A = chunk(c, False, False)          # production today
    Bc = chunk(c, True, False)          # crumb revived, as the dead code intended
    Bf = chunk(c, False, True)          # fence-aware sectioning only
    tot += len(A)
    orph += sum(1 for t, _ in A if not HEAD.match(t))
    deco += sum(1 for (t, cr) in Bc if cr and not t.lstrip().startswith("#"))
    for (t, cr) in Bc:
        if cr: crumb_lens.append(len(cr))
    if len(A) != len(Bf): sect_changes += 1
    ca = [cr for _, cr in chunk(c, True, False)]
    cb = [cr for _, cr in chunk(c, True, True)]
    if ca != cb: crumb_changes += 1

print("=== D1: мёртвая крошка (заявленный дефект) ===")
print(f"md-чанков всего: {tot}")
print(f"  без заголовка в начале (сироты): {orph} = {100*orph/tot:.1f}%")
print(f"  крошка РЕАЛЬНО декорировала бы: {deco} = {100*deco/tot:.1f}%")
print(f"  длина крошки: медиана {st.median(crumb_lens):.0f} симв, p90 {sorted(crumb_lens)[int(.9*len(crumb_lens))]}")

print("\n=== D2: _HEADING_RE не знает про код-фенсы (НОВЫЙ дефект) ===")
print(f"строк, распознанных как заголовок: {real_head+fake_head}")
print(f"  из них ВНУТРИ ``` фенсов (ложные): {fake_head} = {100*fake_head/(real_head+fake_head):.1f}%")
print(f"  затронуто файлов: {len(files_fake)}")
print(f"  файлов, где fence-awareness меняет ГРАНИЦЫ секций (дефект уже в проде): {sect_changes}")
print(f"  файлов, где меняется ТЕКСТ крошки: {crumb_changes}")
