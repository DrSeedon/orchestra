"""Собрать один HTML-обзор извлечённых фактов базы знаний.

Читает .orchestra/tasks/kb-extract/part-*.json и пишет самодостаточный HTML: без сети,
без внешних шрифтов, весь поиск и фильтры работают офлайн. Нужен, чтобы юзер
глазами увидел, что именно легло в базу знаний, до заливки в canonical.
"""
import html
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / ".orchestra/tasks/kb-extract"
OUT = ROOT / ".orchestra/tasks/kb-extract/report.html"


def load_facts() -> list[dict]:
    facts: list[dict] = []
    for path in sorted(SRC.glob("part-*.json")):
        for item in json.loads(path.read_text(encoding="utf-8")):
            item["_part"] = path.stem
            facts.append(item)
    return facts


def esc(value) -> str:
    return html.escape(str(value)) if value else ""


def card(fact: dict) -> str:
    rejected = fact.get("status") == "rejected"
    kind = fact.get("kind") or ""
    meta = []
    if fact.get("decided_at"):
        meta.append(f'<span class="date">{esc(fact["decided_at"])}</span>')
    if kind:
        meta.append(f'<span class="kind k-{esc(kind)}">{esc(kind)}</span>')
    meta.append(f'<span class="src">{esc(fact.get("source_file"))}:{esc(fact.get("source_lines"))}</span>')
    reason = (
        f'<div class="reason"><b>почему:</b> {esc(fact["reason"])}</div>'
        if fact.get("reason")
        else ""
    )
    return f"""<article class="fact{' rejected' if rejected else ''}"
   data-topic="{esc(fact.get('topic'))}" data-kind="{esc(kind)}"
   data-status="{esc(fact.get('status'))}">
  <div class="statement">{esc(fact.get('statement'))}</div>
  {reason}
  <details><summary>доказательство</summary><q>{esc(fact.get('evidence'))}</q></details>
  <div class="meta">{''.join(meta)}</div>
</article>"""


def build(facts: list[dict]) -> str:
    topics = Counter(f.get("topic") or "—" for f in facts)
    rejected = sum(1 for f in facts if f.get("status") == "rejected")
    with_reason = sum(1 for f in facts if f.get("reason"))
    with_date = sum(1 for f in facts if f.get("decided_at"))
    kinds = Counter(f.get("kind") for f in facts if f.get("kind"))

    kind_tiles = "".join(
        f'<div class="tile"><b>{count}</b><span>{esc(name)}</span></div>'
        for name, count in kinds.most_common()
    )
    topic_buttons = "".join(
        f'<button data-t="{esc(name)}">{esc(name)} <i>{count}</i></button>'
        for name, count in topics.most_common(40)
    )
    cards = "\n".join(card(f) for f in facts)

    return f"""<!doctype html>
<html lang="ru"><meta charset="utf-8">
<title>База знаний — {len(facts)} фактов</title>
<style>
:root {{ color-scheme: dark; --bg:#0f1115; --card:#171a21; --line:#252a34;
        --text:#e6e9ef; --dim:#8b93a3; --acc:#6ea8fe; --bad:#f08a8a; }}
* {{ box-sizing:border-box }}
body {{ margin:0; background:var(--bg); color:var(--text);
       font:15px/1.55 system-ui,-apple-system,Segoe UI,Roboto,sans-serif; }}
header {{ padding:28px 24px 8px; }}
h1 {{ margin:0 0 4px; font-size:24px; }}
.sub {{ color:var(--dim); font-size:14px; }}
.tiles {{ display:flex; gap:12px; flex-wrap:wrap; padding:16px 24px; }}
.tile {{ background:var(--card); border:1px solid var(--line); border-radius:12px;
        padding:12px 18px; min-width:110px; }}
.tile b {{ display:block; font-size:26px; }}
.tile span {{ color:var(--dim); font-size:13px; }}
.controls {{ padding:8px 24px 4px; display:flex; gap:10px; flex-wrap:wrap; align-items:center; }}
input[type=search] {{ flex:1; min-width:260px; background:var(--card); color:var(--text);
   border:1px solid var(--line); border-radius:10px; padding:10px 14px; font-size:15px; }}
.topics {{ padding:10px 24px; display:flex; gap:8px; flex-wrap:wrap; }}
.topics button {{ background:var(--card); color:var(--text); border:1px solid var(--line);
   border-radius:999px; padding:6px 12px; cursor:pointer; font-size:13px; }}
.topics button.on {{ border-color:var(--acc); color:var(--acc); }}
.topics i {{ color:var(--dim); font-style:normal; }}
main {{ padding:12px 24px 60px; display:grid; gap:12px;
        grid-template-columns:repeat(auto-fill,minmax(420px,1fr)); }}
.fact {{ background:var(--card); border:1px solid var(--line); border-left:3px solid var(--acc);
        border-radius:12px; padding:14px 16px; }}
.fact.rejected {{ border-left-color:var(--bad); opacity:.85; }}
.fact.rejected .statement {{ text-decoration:line-through; text-decoration-color:var(--bad); }}
.statement {{ font-weight:600; }}
.reason {{ margin-top:8px; color:var(--dim); font-size:14px; }}
.reason b {{ color:var(--text); font-weight:600; }}
details {{ margin-top:8px; }}
summary {{ cursor:pointer; color:var(--acc); font-size:13px; }}
q {{ display:block; margin-top:6px; color:var(--dim); font-size:13px;
     border-left:2px solid var(--line); padding-left:10px; }}
.meta {{ margin-top:10px; display:flex; gap:8px; flex-wrap:wrap; font-size:12px; color:var(--dim); }}
.kind {{ padding:1px 8px; border-radius:999px; border:1px solid var(--line); }}
.k-rule {{ color:#8fd3a0 }} .k-lesson {{ color:#e8c07d }} .k-state {{ color:#9db4ff }}
.src {{ font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }}
.hidden {{ display:none }}
#empty {{ color:var(--dim); padding:20px 24px; }}
</style>
<header>
  <h1>База знаний — {len(facts)} фактов</h1>
  <div class="sub">Извлечено из 20 тем <code>.orchestra/kb/</code> и <code>CLAUDE.md</code>.
  Каждый факт самодостаточен: читается без исходного файла.</div>
</header>
<div class="tiles">
  <div class="tile"><b>{len(facts)}</b><span>всего фактов</span></div>
  <div class="tile"><b>{rejected}</b><span>отменённых</span></div>
  <div class="tile"><b>{with_reason}</b><span>с причиной</span></div>
  <div class="tile"><b>{with_date}</b><span>с датой</span></div>
  <div class="tile"><b>{len(topics)}</b><span>тем</span></div>
  {kind_tiles}
</div>
<div class="controls">
  <input type="search" id="q" placeholder="Поиск по формулировке, причине, цитате…">
  <label><input type="checkbox" id="onlyRejected"> только отменённые</label>
</div>
<div class="topics" id="topics"><button data-t="" class="on">все <i>{len(facts)}</i></button>{topic_buttons}</div>
<main id="list">{cards}</main>
<div id="empty" class="hidden">Ничего не найдено.</div>
<script>
const list = document.getElementById('list');
const cards = [...list.children];
const q = document.getElementById('q');
const onlyRej = document.getElementById('onlyRejected');
let topic = '';

function apply() {{
  const needle = q.value.trim().toLowerCase();
  let shown = 0;
  for (const el of cards) {{
    const okTopic = !topic || el.dataset.topic === topic;
    const okRej = !onlyRej.checked || el.dataset.status === 'rejected';
    const okText = !needle || el.textContent.toLowerCase().includes(needle);
    const ok = okTopic && okRej && okText;
    el.classList.toggle('hidden', !ok);
    if (ok) shown++;
  }}
  document.getElementById('empty').classList.toggle('hidden', shown > 0);
}}

document.getElementById('topics').addEventListener('click', (e) => {{
  const btn = e.target.closest('button');
  if (!btn) return;
  topic = btn.dataset.t;
  for (const b of e.currentTarget.children) b.classList.toggle('on', b === btn);
  apply();
}});
q.addEventListener('input', apply);
onlyRej.addEventListener('change', apply);
</script>
</html>"""


def main() -> None:
    facts = load_facts()
    OUT.write_text(build(facts), encoding="utf-8")
    print(f"{OUT}: {len(facts)} фактов, {OUT.stat().st_size // 1024} КБ")


if __name__ == "__main__":
    main()
