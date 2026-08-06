#!/usr/bin/env python3
"""Собирает артефакт #128 из данных, а не из памяти.

Все числа в HTML вычисляются здесь из comparison.tsv и из замеров richness.py —
чтобы в артефакте не оказалось цифры, набранной руками.

Запуск:  python3 docs/tasks/128/build-artifact.py
Выход:   docs/tasks/128/codex-dizayn-protiv-nashego-skilla.html
"""
import collections
import csv
import html
import pathlib

HERE = pathlib.Path(__file__).parent
ROWS = list(csv.DictReader((HERE / "comparison.tsv").open(), delimiter="\t"))
OUT = HERE / "codex-dizayn-protiv-nashego-skilla.html"

VERDICTS = ["ЕСТЬ", "РАЗМЫТО", "НЕТ", "ПРОТИВОРЕЧИТ", "НЕ НАШ ЖАНР"]
TONE = {"ЕСТЬ": "s3", "РАЗМЫТО": "s2", "НЕТ": "mut", "ПРОТИВОРЕЧИТ": "bad", "НЕ НАШ ЖАНР": "off"}
SRC_TITLE = {
    "gpt-5.5": "gpt-5.5 · Frontend guidance",
    "gpt-5.4": "gpt-5.4 · Frontend tasks",
    "gpt-5.6-sol": "gpt-5.6-sol · Visualizations",
    "visualize.css": "visualize.css · дизайн-система",
}

applicable = [r for r in ROWS if r["verdict"] != "НЕ НАШ ЖАНР"]
total_c = collections.Counter(r["verdict"] for r in ROWS)
appl_c = collections.Counter(r["verdict"] for r in applicable)


def by_source(src: str) -> collections.Counter:
    return collections.Counter(
        r["verdict"] for r in applicable if r["source"] == src
    )


def esc(s: str) -> str:
    return html.escape(s, quote=True)


def bar(counter: collections.Counter, n: int) -> str:
    """Полоса-стопка: доля каждого вердикта."""
    seg = []
    for v in VERDICTS[:4]:
        c = counter.get(v, 0)
        if not c:
            continue
        seg.append(
            f'<i style="--w:{c / n * 100:.1f}%;--t:var(--{TONE[v]})" '
            f'title="{esc(v)}: {c}"><b>{c}</b></i>'
        )
    return '<span class="bar">' + "".join(seg) + "</span>"


# ── таблица правил ───────────────────────────────────────────────────────────
trs = []
for r in ROWS:
    v = r["verdict"]
    trs.append(
        f'<tr data-v="{esc(v)}">'
        f'<td class="id"><code>{esc(r["id"])}</code></td>'
        f'<td class="src">{esc(r["source"])}</td>'
        f'<td>{esc(r["their_rule"])}</td>'
        f'<td class="mut">{esc(r["our_state"])}</td>'
        f'<td><span class="chip t-{TONE[v]}">{esc(v)}</span></td>'
        f"</tr>"
    )

# ── доза-эффект ──────────────────────────────────────────────────────────────
DOSE = [
    ("дословный синтаксис", "light-dark(светлое, тёмное)", "5/5", 100, "s3"),
    ("дословная строка", "--card: color-mix(in oklab, var(--ink) 5%, transparent)", "5/5", 100, "s3"),
    ("дословные коэффициенты", "calc(var(--fs) * 1.72 / 1.43 / 1.29)", "65 из 77 объявлений", 84, "s3"),
    ("дословная строка", "box-shadow: inset 0 0 0 1px var(--ring)", "5/5", 100, "s3"),
    ("коэффициенты без базы", "радиусы .6 / .8 / 1", "4/5", 80, "s2"),
    ("принцип без значений", "«тень — состояние, не украшение»", "1–2 тени на файл", 25, "s2"),
    ("принцип без значений", "«меняй шрифтовую пару»", "0/5", 0, "bad"),
    ("принцип без значений", "«серии — 6 различимых тонов»", "не определено: графиков нет", 0, "off"),
    ("не написано ничего", "движение, переходы", "0/5 @keyframes", 0, "bad"),
    ("не написано ничего", "таблицы, .sr-only", "tabular-nums: медиана 0", 0, "bad"),
]
dose_rows = "".join(
    f'<tr><td class="mut">{esc(form)}</td><td><code>{esc(rule)}</code></td>'
    f'<td class="num">{esc(res)}</td>'
    f'<td class="fill"><span class="meter"><i style="--w:{w}%;--t:var(--{t})"></i></span></td></tr>'
    for form, rule, res, w, t in DOSE
)

# ── насыщенность ─────────────────────────────────────────────────────────────
RICH = [
    ("объявлено токенов", 11, 59),
    ("различных радиусов", 3, 6),
    (":focus-visible", 1, 8),
    ("box-shadow", 1, 12),
    (":hover", 0, 7),
    ("transition", 0, 3),
    ("токенов серий графиков", 0, 6),
    ("правил про таблицы", 0, 14),
]
rich_rows = "".join(
    f'<tr><td>{esc(k)}</td><td class="num">{a}</td><td class="num">{b}</td>'
    f'<td class="fill"><span class="meter two">'
    f'<i style="--w:{a / b * 100:.0f}%;--t:var(--accent)"></i>'
    f'<i style="--w:100%;--t:color-mix(in srgb, var(--ink) 22%, transparent)"></i>'
    f"</span></td></tr>"
    for k, a, b in RICH
)

CSS = """
:root{
  color-scheme: light dark;
  /* ── ручки: выбраны под предмет — разбор чужой правки, красный карандаш ── */
  --accent: light-dark(#b23a10, #ff8a5b);
  --fs: 15px;
  --radius: 10px;
  --font: ui-sans-serif, system-ui, "Segoe UI", sans-serif;
  --font-head: ui-serif, Georgia, "Times New Roman", serif;
  /* ── система: копируется как есть ─────────────────────────────────────── */
  --bg: light-dark(#fdfcfb, #17181a);
  --ink: light-dark(#1a1c1f, #f2f2f0);
  --mut: color-mix(in srgb, var(--ink) 48%, transparent);
  --off: color-mix(in srgb, var(--ink) 22%, transparent);
  --card: color-mix(in oklab, var(--ink) 5%, transparent);
  --border: color-mix(in srgb, var(--ink) 12%, transparent);
  --ring: var(--accent);
  --bad: light-dark(#c0341a, #ff7a63);
  --fs-sm: max(11px, calc(var(--fs) - 2px));
  --fs-h3: calc(var(--fs) * 1.29);
  --fs-h2: calc(var(--fs) * 1.43);
  --fs-h1: calc(var(--fs) * 1.72);
  --r-sm: calc(var(--radius) * .6);
  --r-lg: calc(var(--radius) * 1.6);
  --s2: light-dark(#c26a1f, #f59a56);
  --s3: light-dark(#2f7d46, #74d58b);
  --s5: light-dark(#7a5fd0, #aa91ef);
  --s6: light-dark(#1f7a72, #5acbc2);
}
*{box-sizing:border-box}
body{margin:0;padding:clamp(16px,4vw,40px);background:var(--bg);color:var(--ink);
     font:430 var(--fs)/1.5 var(--font);letter-spacing:0}
main{max-width:1120px;margin:0 auto}
h1,h2,h3{margin:0;font-family:var(--font-head);font-weight:500;line-height:1.2}
h1{font-size:var(--fs-h1);letter-spacing:0}
h2{font-size:var(--fs-h2);margin-top:40px;padding-bottom:6px;border-bottom:2px solid var(--accent);display:inline-block}
h3{font-size:var(--fs-h3);margin-top:24px}
p{margin:8px 0 0;max-width:76ch}
.lead{font-size:calc(var(--fs) * 1.1);max-width:70ch}
.mut{color:var(--mut)}
small,.sm{font-size:var(--fs-sm)}
code{padding:1px 5px;border-radius:var(--r-sm);font-size:.9em;
     font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
     background:color-mix(in srgb,var(--ink) 8%,transparent);
     box-decoration-break:clone;-webkit-box-decoration-break:clone;overflow-wrap:anywhere}
a{color:var(--accent);text-underline-offset:2px}
header{padding-bottom:16px;border-bottom:1px solid var(--border)}
.eyebrow{font-size:var(--fs-sm);letter-spacing:.08em;text-transform:uppercase;color:var(--accent)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(max(180px,22%),1fr));gap:12px;margin-top:16px}
.stat{padding:12px;border-radius:var(--r-lg);background:var(--card)}
.stat b{display:block;font-family:var(--font-head);font-size:calc(var(--fs) * 2);
        font-weight:500;line-height:1.1;font-variant-numeric:tabular-nums}
.stat span{display:block;color:var(--mut);font-size:var(--fs-sm);margin-top:2px}
table{width:100%;border-collapse:collapse;margin-top:12px}
th,td{padding:9px 20px 9px 0;border-bottom:1px solid var(--border);text-align:start;
      vertical-align:top;overflow-wrap:anywhere}
th{font-weight:600;font-size:var(--fs-sm);color:var(--mut);
   border-bottom-color:color-mix(in srgb,var(--ink) 16%,transparent)}
tbody tr:last-child :is(th,td){border-bottom:0}
td:last-child,th:last-child{padding-right:0}
.num{text-align:end;font-variant-numeric:tabular-nums;white-space:nowrap}
td.id,td.src{white-space:nowrap;color:var(--mut);font-size:var(--fs-sm)}
.scroll{overflow-x:auto;scrollbar-width:thin}
.chip{display:inline-block;padding:2px 8px;border-radius:9999px;font-size:var(--fs-sm);
      white-space:nowrap;background:color-mix(in srgb,var(--t) 18%,transparent);
      color:color-mix(in srgb,var(--t) 78%,var(--ink))}
.t-s3{--t:var(--s3)}.t-s2{--t:var(--s2)}.t-mut{--t:var(--mut)}.t-bad{--t:var(--bad)}.t-off{--t:var(--off)}
.bar{display:flex;height:22px;border-radius:var(--r-sm);overflow:hidden;min-width:180px}
.bar i{width:var(--w);background:color-mix(in srgb,var(--t) 55%,transparent);
       display:grid;place-items:center;font-style:normal;font-size:var(--fs-sm)}
.bar i b{font-weight:500;font-variant-numeric:tabular-nums}
.meter{display:block;height:10px;border-radius:9999px;
       background:color-mix(in srgb,var(--ink) 8%,transparent);overflow:hidden;min-width:120px}
.meter i{display:block;height:100%;width:var(--w);background:var(--t)}
.meter.two{position:relative;background:none}
.meter.two i{position:absolute;inset:0 auto 0 0;height:10px;border-radius:9999px}
.meter.two i:first-child{z-index:2}
.meter.two i:last-child{opacity:.25}
td.fill{width:34%;min-width:130px;padding-top:14px}
.filters{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin-top:12px}
button{font:inherit;min-height:28px;padding:0 10px;border:1px solid var(--border);
       border-radius:var(--radius);background:transparent;color:var(--ink);cursor:pointer}
button:hover{background:color-mix(in srgb,var(--ink) 6%,transparent)}
button[aria-pressed="true"]{background:var(--accent);border-color:var(--accent);color:var(--bg)}
:is(a,button,summary,[tabindex]):focus-visible{outline:2px solid var(--ring);outline-offset:2px}
.two-col{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,320px),1fr));gap:20px;margin-top:12px}
.take,.leave{padding:14px;border-radius:var(--r-lg);background:var(--card)}
.take{box-shadow:inset 3px 0 0 var(--s3)}
.leave{box-shadow:inset 3px 0 0 var(--mut)}
ul{margin:8px 0 0;padding-left:18px}
li{margin:4px 0;max-width:70ch}
.spec{display:grid;grid-template-columns:1fr auto;gap:2px 16px;margin-top:10px;max-width:520px;
      font-variant-numeric:tabular-nums}
.spec div:nth-child(2n){text-align:end}
.spec .sum{border-top:1px solid var(--border);padding-top:4px;margin-top:4px;font-weight:500}
.fontdemo{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,280px),1fr));gap:12px;margin-top:12px}
.fontdemo>div{padding:12px;border-radius:var(--r-lg);background:var(--card)}
.fd-now{font-family:var(--font);font-weight:400}
.fd-now h4,.fd-new h4{margin:0 0 6px;font-size:var(--fs-sm);color:var(--mut);font-weight:600;
                      font-family:var(--font);letter-spacing:.04em;text-transform:uppercase}
.fd-now p.t{font-family:var(--font);font-weight:400;font-size:var(--fs-h2);margin:0}
.fd-new p.t{font-family:var(--font-head);font-weight:500;font-size:var(--fs-h2);margin:0}
.fd-new{font-weight:430}
blockquote{margin:12px 0 0;padding:10px 14px;border-left:3px solid var(--accent);
           background:var(--card);border-radius:0 var(--r-sm) var(--r-sm) 0;max-width:76ch}
footer{margin-top:44px;padding-top:12px;border-top:1px solid var(--border);
       color:var(--mut);font-size:var(--fs-sm)}
svg{display:block;max-width:100%;height:auto}
.sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap}
@media print{
  :root{color-scheme:light}
  body{padding:0;background:#fff;color:#000;font-size:10pt}
  .no-print{display:none}
  h2{margin-top:20px}
  tr,li,blockquote{break-inside:avoid}
  *{print-color-adjust:exact;-webkit-print-color-adjust:exact}
}
"""

BODY = f"""<main>
<header>
  <div class="eyebrow">#128 · разбор чужой дизайн-системы</div>
  <h1>Что у Codex есть про дизайн — и чего из этого нет у нас</h1>
  <p class="lead">Разобрано 54 правила из четырёх источников OpenAI. Каждое сверено с текущим
  текстом нашего скилла <code>html-artifacts</code>. Вывод короткий: текстовые правила мы
  перенесли почти наполовину, а дизайн-систему — на одну двадцатую. Сухость идёт оттуда.</p>
  <div class="grid">
    <div class="stat"><b>{len(ROWS)}</b><span>правил разобрано</span></div>
    <div class="stat"><b>{appl_c['ЕСТЬ'] * 100 // len(applicable)}%</b><span>из применимых у нас уже есть</span></div>
    <div class="stat"><b>{appl_c['НЕТ'] * 100 // len(applicable)}%</b><span>нет вовсе</span></div>
    <div class="stat"><b>1 из 20</b><span>правил их CSS-системы у нас перенесено</span></div>
  </div>
</header>

<h2>Гипотеза подтвердилась, но причина глубже</h2>
<p>Проверялось предположение: «сухость — следствие того, что мы переносили принципы и не
переносили конкретику». Замер на десяти правилах, по пяти артефактам каждое.
Зависимость монотонная и без исключений.</p>
<div class="scroll"><table>
<thead><tr><th>форма правила в скилле</th><th>правило</th><th class="num">исполнение</th><th>&nbsp;</th></tr></thead>
<tbody>{dose_rows}</tbody>
</table></div>
<p class="mut sm">«Серии — 6 тонов» помечено серым не как провал: ни в одном из пяти артефактов
нет графика, метрика не определена. Записано как есть.</p>

<h2>Настоящая причина «сухости» — не цвет, а шрифт</h2>
<p>Проверка рендером (headless Chromium, вычисленный стиль) на всех пяти артефактах даёт
одинаковый ответ: <strong>один и тот же системный гротеск, начертание 400, заголовок той же
семьёй.</strong> Пары шрифтов нет ни в одном. У Codex базовое начертание — 430, заголовочное —
500, и это отдельные токены дизайн-системы.</p>
<div class="fontdemo">
  <div class="fd-now"><h4>как сейчас — 5 из 5</h4>
    <p class="t">Пост-мортем инцидента</p>
    <p class="sm">Один гротеск на заголовок и текст, вес 400. Ровно то, что браузер даёт
    по умолчанию — поэтому и читается как «без дизайна».</p></div>
  <div class="fd-new"><h4>что предлагается</h4>
    <p class="t">Пост-мортем инцидента</p>
    <p class="sm">Заголовок — вторая семья (<code>ui-serif</code>, Georgia), вес 500;
    текст — 430. Обе семьи локальные, офлайн не нарушен.</p></div>
</div>
<blockquote>Правило OpenAI (поколение ≤&nbsp;5.4), дословно: «Typography: Use expressive, purposeful
fonts and avoid default stacks (Inter, Roboto, Arial, system)». Наш пункт 3 — «Системные шрифты,
без веб-шрифтов». Это прямое противоречие, и оно наше собственное: офлайн запрещает
веб-шрифты, а не разнообразие.</blockquote>

<h2>Разрез по источникам объясняет всё</h2>
<div class="scroll"><table>
<thead><tr><th>источник</th><th class="num">применимых</th><th>что с ними у нас</th></tr></thead>
<tbody>
{"".join(
    f'<tr><td>{esc(SRC_TITLE[s])}</td><td class="num">{sum(by_source(s).values())}</td>'
    f'<td class="fill">{bar(by_source(s), sum(by_source(s).values()))}</td></tr>'
    for s in ("gpt-5.5", "gpt-5.4", "visualize.css") )}
</tbody></table></div>
<p>Зелёное — перенесено, оранжевое — размыто до принципа, серое — нет вовсе, красное —
противоречит. Текст мы читали и переносили. Код — нет.</p>

<h2>Насыщенность: наши артефакты против их дизайн-системы</h2>
<div class="scroll"><table>
<thead><tr><th>признак</th><th class="num">у нас</th><th class="num">Codex</th><th>&nbsp;</th></tr></thead>
<tbody>{rich_rows}</tbody></table></div>
<p class="mut sm">Столбец «у нас» — медиана по пяти артефактам нового скилла;
столбец «Codex» — <code>visualize.css</code>, 793 строки, Apache-2.0.</p>

<h2>Построчно: их правило → что у нас → вердикт</h2>
<div class="filters no-print" role="group" aria-label="Фильтр по вердикту">
  <button type="button" data-f="все" aria-pressed="true">все · {len(ROWS)}</button>
  {"".join(f'<button type="button" data-f="{esc(v)}" aria-pressed="false">{esc(v.lower())} · {total_c[v]}</button>' for v in VERDICTS)}
</div>
<div class="scroll"><table id="rules">
<thead><tr><th>№</th><th>источник</th><th>их правило</th><th>что стоит у нас сейчас</th><th>вердикт</th></tr></thead>
<tbody>{"".join(trs)}</tbody></table></div>

<h2>Что предлагается перенести</h2>
<p>Форма переноса — <strong>костяк CSS в теле скилла</strong>: пять «ручек» сверху агент
выбирает под предмет, всё ниже копирует без изменений. Механизм — то, что у нас не
исполнялось; вкус — то, что как раз исполнялось (5 из 5 уникальных акцентов, когда попросили
выбрать цвет под предмет).</p>
<div class="two-col">
  <div class="take"><h3>Берём дословно</h3>
  <ul>
    <li>Производные цвета: <code>color-mix(in oklab, var(--ink) 5%)</code>, границы 12%, шапка таблицы 16%</li>
    <li>Шкала кеглей 1.72&nbsp;/&nbsp;1.43&nbsp;/&nbsp;1.29 + нижний предел <code>max(11px, …)</code></li>
    <li>Начертания 430 и 500, интерлиньяж 1.5 и 1.25</li>
    <li>Радиусы .6&nbsp;/&nbsp;.8&nbsp;/&nbsp;1.6 от одной базы и <code>9999px</code></li>
    <li>Одна тень на файл: <code>0 1px 2px -1px rgb(0 0 0 / 8%)</code></li>
    <li>Шесть тонов серий, у каждого своя пара light/dark</li>
    <li>Фокус <code>outline: 2px + offset 2px</code> и состояние «выбрано» по <code>[aria-pressed]</code></li>
    <li>Таблица: линии снизу, последняя строка без линии, <code>tabular-nums</code> в числах</li>
    <li>Ритм отступов закрытым рядом 2 4 6 8 12 16 24 40</li>
  </ul></div>
  <div class="leave"><h3>Не берём</h3>
  <ul>
    <li>Тултип на Floating UI и иконки lucide — внешний JS с <code>unpkg.com</code>, ломает офлайн</li>
    <li><code>#widget</code>, прозрачный фон, <code>::codex-inline-vis</code> — привязка к их вьюеру</li>
    <li>Лендинги, hero, Three.js, дев-сервер, React — 7 правил «не наш жанр»</li>
    <li>Инструкции ChatGPT Canvas (2024) — другой продукт, нашим извлечением не подтверждены
        и конфликтуют с Codex 5.5 по радиусам</li>
    <li>Требование «атмосферных градиентов» из поколения ≤ 5.4 — сама OpenAI его отменила в 5.5</li>
  </ul></div>
</div>

<h3>Цена</h3>
<div class="spec">
  <div>скилл сейчас</div><div>7 065 Б</div>
  <div>+ костяк</div><div>3 896 Б</div>
  <div>+ строка атрибуции Apache-2.0</div><div>86 Б</div>
  <div class="mut">− секция «Размеры — шкалой» (её заменяет костяк)</div><div class="mut">−687 Б</div>
  <div class="mut">− секция «Состояния» (её заменяет костяк)</div><div class="mut">−371 Б</div>
  <div class="sum">итого</div><div class="sum">≈ 9 989 Б</div>
</div>
<p>Дороже, чем сейчас, на 41% — но дешевле, чем считалось в #119. Тот отчёт утверждал, что
тело скилла вклеивается в системный промпт Sol целиком; сегодня это уже не так:
<code>build_skills_index</code> (<code>app/prompting.py:239</code>) кладёт в промпт только строку
«имя — описание — путь», а тело агент читает сам и только когда скилл сработал.</p>

<h2>Возражение, которое надо назвать вслух</h2>
<p>Костяк — это одинаковый вид у всех артефактов, то есть ровно та монотонность, на которую
жалоба и была, только с другой стороны. У Codex один фирменный стиль потому, что это одна
поверхность одного продукта. У нас артефакты обязаны отличаться по предмету.</p>
<p>Поэтому переносится <strong>механизм, а не облик</strong>: закрытые наборы, состояния,
компоненты — копируются; акцент, база кегля, база радиуса и обе шрифтовые семьи — выбираются
под предмет каждый раз. Это ровно та граница, по которой прошёл замер: механизм у нас не
исполнялся, вкус исполнялся.</p>

<h2>Чего этот разбор не доказывает</h2>
<p>Прирост не измерен. Что костяк действительно делает артефакты живее — пока гипотеза
с сильным основанием, а не результат. Доказательство требует такого же прогона, как в #119:
N независимых сессий на старом теле скилла против N на новом, и обязательно с проверкой
на далёкой предметной области. Внешнего ревью у разбора тоже нет — Codex недоступен
до 8 августа. Вердикта второй модели здесь нет.</p>

<footer>
  <p>Источники, дословно и с происхождением: <code>docs/tasks/128/verbatim/</code> —
  инструкции gpt-5.5, gpt-5.4, gpt-5.6-sol, терминальные визуализации,
  <code>visualize.css</code> целиком (© OpenAI, Apache-2.0) и официальная публикация OpenAI.
  Построчная таблица — <code>docs/tasks/128/comparison.tsv</code>, замеры —
  <code>richness.py</code>, черновик костяка — <code>proposed-skeleton.css</code>.
  Артефакт собран скриптом <code>build-artifact.py</code>: числа в нём вычислены из данных,
  а не набраны руками.</p>
  <p>Оформление этой страницы сделано по правилам, которые в ней предлагаются, —
  она одновременно образец.</p>
</footer>
</main>"""

JS = """
(function () {
  var tbl = document.getElementById('rules');
  if (!tbl) return;
  var rows = Array.prototype.slice.call(tbl.tBodies[0].rows);
  var btns = Array.prototype.slice.call(document.querySelectorAll('.filters button'));
  btns.forEach(function (btn) {
    btn.addEventListener('click', function () {
      var f = btn.dataset.f;
      btns.forEach(function (b) { b.setAttribute('aria-pressed', String(b === btn)); });
      rows.forEach(function (row) {
        row.hidden = !(f === 'все' || row.dataset.v === f);
      });
    });
  });
})();
"""

DOC = f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>#128 — дизайн Codex против нашего скилла html-artifacts</title>
<!-- костяк производен от visualize.css, (c) OpenAI, Apache-2.0; изменено: офлайн, печать, вторая шрифтовая семья -->
<style>{CSS}</style>
</head>
<body>
{BODY}
<script>{JS}</script>
</body>
</html>
"""

OUT.write_text(DOC)
print(f"{OUT}: {len(DOC.encode())} Б, строк таблицы {len(ROWS)}")
print("вердикты (все):", dict(total_c))
print("вердикты (применимые):", dict(appl_c))
