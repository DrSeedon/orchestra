"""V-929: ролик «временные правила» (V-927) в стиле «бумага».

Сцена = каркас плеера из html-artifacts без правок + SVG и STEPS этого ролика.
Картина комнаты — room.svg (та же, что в демо V-917). Факты сверены с app/temp_rules.py
и .orchestra/tasks/V-927/report.md.
Запуск: python3 build_scene.py <путь к animation.md> > scene.html
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
md = Path(sys.argv[1]).read_text()
tpl = re.search(r"```html motion-template\n(.*?)```", md, re.S).group(1)
room = (HERE / "room.svg").read_text().replace('<use id="miniUse" href="#cards"/>', '<use id="miniUse" href="#agents"/>')

WORKERS = "".join(
    f'<rect x="{x}" y="330" width="300" height="100" rx="14" fill="#fff" stroke="#d9dce3" stroke-width="2"/>'
    f'<text x="{x + 150}" y="393" text-anchor="middle" font-size="36">воркер</text>'
    f'<path d="M640 140L{x + 150} 330" stroke="#c9ced8" stroke-width="3" fill="none"/>'
    for x in (90, 490, 890))
TAGS = "".join(
    f'<g id="tag{k}" opacity="0"><rect x="{x + 75}" y="444" width="150" height="40" rx="8" fill="#eef0f3"/>'
    f'<text x="{x + 150}" y="472" text-anchor="middle" font-size="22" fill="#6b7280">правила</text></g>'
    for k, x in enumerate((90, 490, 890)))
CHIPS = "".join(
    f'<g id="chip{k}"><rect id="chipR{k}" x="{x}" y="252" width="{w}" height="50" rx="25" fill="#eef0f3"/>'
    f'<text id="chipT{k}" x="{x + w / 2}" y="285" text-anchor="middle" font-size="24" fill="#3b3e46">{label}</text></g>'
    for k, (x, w, label) in enumerate(((330, 210, "всем в проекте"), (555, 210, "оркестраторам"),
                                        (780, 150, "воркерам"), (945, 190, "одному агенту"))))
STICKY = [(400, 120, -4), (610, 90, 5), (470, 230, 3), (700, 250, -6), (560, 170, -2)]
STICKIES = "".join(
    f'<g id="st{k}" opacity="0" transform="rotate({r} {x + 110} {y + 50})"><rect x="{x}" y="{y}" width="220" height="100" rx="4" '
    f'fill="#f6e3a1" stroke="#e2c86f"/><text x="{x + 110}" y="{y + 60}" text-anchor="middle" font-size="24" fill="#5b4a12">'
    f'{"пока делай так" if k == 0 else ["временно!", "до релиза", "не трогать X", "срочно так"][k - 1]}</text></g>'
    for k, (x, y, r) in enumerate(STICKY))
PROS = "".join(
    f'<text id="pro{k}" x="170" y="{90 + k * 92}" font-size="34" fill="#0e5e9c" opacity="0">✓  {s}</text>'
    for k, s in enumerate(("не забывается и не копится", "у правила виден хозяин",
                           "права разделены: на все проекты — только главный оркестратор",
                           "без интерфейса: только инструменты агентов")))
SEGS = "".join(
    f'<rect x="{x}" y="200" width="{w - 10}" height="80" rx="10" fill="{fill}" stroke="{stroke}" stroke-width="2"/>'
    f'<text x="{x + (w - 10) / 2}" y="250" text-anchor="middle" font-size="26" fill="{ink}">{label}</text>'
    for x, w, label, fill, stroke, ink in (
        (150, 260, "роль", "#eef0f3", "#eef0f3", "#3b3e46"),
        (410, 320, "правила проекта", "#eef0f3", "#eef0f3", "#3b3e46"),
        (730, 210, "память", "#eef0f3", "#eef0f3", "#3b3e46"),
        (940, 200, "временные", "#fde4d0", "#c9551b", "#c9551b")))

SVG = f"""<svg id="stage" viewBox="0 0 1280 590" role="img" aria-labelledby="st"><title id="st">Временные правила для агентов Orchestra</title>
{room}
<g id="agentsLayer" opacity="0">
 <g id="agents">
  {WORKERS}
  <rect x="470" y="40" width="340" height="100" rx="14" fill="#fff" stroke="#d9dce3" stroke-width="2"/>
  <text x="640" y="104" text-anchor="middle" font-size="38" font-weight="600">оркестратор</text>
 </g>
 <g id="tagO" opacity="0"><rect x="290" y="70" width="150" height="40" rx="8" fill="#eef0f3"/>
  <text x="365" y="98" text-anchor="middle" font-size="22" fill="#6b7280">правила</text></g>
 {TAGS}
 <g id="ruleTab" opacity="0"><rect id="ruleTabR" x="840" y="66" width="300" height="48" rx="10" fill="#d6e8f4" stroke="#0e5e9c" stroke-width="2"/>
  <text id="ruleTabT" x="990" y="98" text-anchor="middle" font-size="24" fill="#0e5e9c">временное правило ✓</text></g>
</g>
<g id="sheetLayer" opacity="0">
 <rect x="330" y="40" width="520" height="430" rx="10" fill="#fff" stroke="#d9dce3" stroke-width="2"/>
 <text x="370" y="95" font-size="30" font-weight="600">правила агента</text>
 <g fill="#dfe2e8"><rect x="370" y="125" width="420" height="14" rx="7"/><rect x="370" y="160" width="360" height="14" rx="7"/>
  <rect x="370" y="195" width="400" height="14" rx="7"/><rect x="370" y="230" width="300" height="14" rx="7"/></g>
 {STICKIES}
 <g id="harm" opacity="0" font-size="30" fill="#c9551b">
  <text x="900" y="160">✗ забыли снять</text><text x="900" y="230">✗ мешает</text><text x="900" y="300">✗ токены</text>
  <text x="935" y="340" font-size="24">на каждом шаге</text></g>
</g>
<g id="flagLayer" opacity="0">
 <rect x="340" y="70" width="600" height="320" rx="16" fill="#fff" stroke="#d9dce3" stroke-width="2"/>
 <text x="390" y="140" font-size="34" font-weight="600">⚑ временный флаг</text>
 <text id="flagOwner" x="390" y="230" font-size="32" fill="#0e5e9c" opacity="0">хозяин: тот, кто завёл</text>
 <text id="flagTtl" x="390" y="310" font-size="32" fill="#0e5e9c" opacity="0">срок годности: дата</text>
</g>
<g id="cardLayer" opacity="0">
 <rect id="card" x="190" y="30" width="900" height="420" rx="16" fill="#fff" stroke="#d9dce3" stroke-width="2"/>
 <text x="230" y="80" font-size="26" fill="#6b7280">временное правило</text>
 <text id="rule1" x="230" y="145" font-size="32"></text>
 <text id="rule2" x="230" y="195" font-size="32"></text>
 <text x="230" y="285" font-size="26" fill="#6b7280">кому</text>
 {CHIPS}
 <text x="230" y="380" font-size="26" fill="#6b7280">срок</text>
 <text id="due" x="330" y="381" font-size="30" class="mono" opacity="0">вт 20.10, 07:00 UTC</text>
</g>
<g id="timeLayer" opacity="0">
 <path d="M150 120H1130" stroke="#c9ced8" stroke-width="4"/>
 <path d="M900 85V155" stroke="#c9551b" stroke-width="4"/><text x="900" y="72" text-anchor="middle" font-size="26" fill="#c9551b">срок</text>
 <circle id="now" cx="200" cy="120" r="14" fill="#0e5e9c"/>
 <g id="mode1" opacity="0"><rect x="150" y="220" width="460" height="200" rx="16" fill="#fff" stroke="#d9dce3" stroke-width="2"/>
  <text x="180" y="275" font-size="28" fill="#6b7280">режим 1</text>
  <text x="180" y="335" font-size="34" font-weight="600">снимается само</text>
  <text id="mode1v" x="180" y="390" font-size="28" fill="#0e5e9c" opacity="0">✓ из промпта ушло</text></g>
 <g id="mode2" opacity="0"><rect x="670" y="220" width="460" height="200" rx="16" fill="#fff" stroke="#d9dce3" stroke-width="2"/>
  <text x="700" y="275" font-size="28" fill="#6b7280">режим 2: автору, один раз</text>
  <text id="ask1" x="700" y="335" font-size="30" font-weight="600"></text>
  <text id="ask2" x="700" y="390" font-size="28" fill="#0e5e9c"></text></g>
</g>
<g id="prosLayer" opacity="0">{PROS}</g>
<g id="consLayer" opacity="0">
 <text x="150" y="110" font-size="26" fill="#6b7280">промпт агента</text>
 <rect id="cache" x="150" y="140" width="980" height="30" rx="8" fill="#d6e8f4"/>
 <text id="cacheT" x="160" y="163" font-size="20" fill="#0e5e9c">кеш</text>
 {SEGS}
 <text id="cons1" x="150" y="370" font-size="32" fill="#c9551b" opacity="0">✗ смена правила один раз сбрасывает кеш</text>
 <text id="cons2" x="150" y="430" font-size="30" fill="#0e5e9c" opacity="0">поэтому блок — в самом конце, а правила — редкие</text>
</g>
<g id="textLayer" opacity="0">
 <text x="640" y="200" text-anchor="middle" font-size="44" font-weight="600">правило = текст для модели</text>
 <text id="noLock" x="640" y="300" text-anchor="middle" font-size="34" fill="#c9551b" opacity="0">✗ модель может нарушить: замка нет</text>
</g>
</svg>"""

JS = r"""
Paper.install();
const PIC = Paper.picture('room', {x: 96, y: 18, w: 1088, h: 556});
const VIEW = {from: [640, 252], to: [640, 235], scale: 5};
$('miniUse').setAttribute('transform', Paper.miniature(VIEW));
(() => { const c = $('calDots'); for (let k = 0; k < 28; k++) { const e = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
  Object.entries({x: 176 + (k % 7) * 22, y: 116 + Math.floor(k / 7) * 22, width: 12, height: 9, rx: 2}).forEach(([a, v]) => e.setAttribute(a, v)); c.append(e); } })();
const STEPS = [
 {t: 'Команда агентов', say: 'Оркестра это команда ИИ-агентов: оркестратор раздаёт задачи, а воркеры их выполняют.',
  sub: 'Orchestra — команда ИИ-агентов: оркестратор раздаёт задачи, воркеры их выполняют.', set: {mini: {opacity: 1}}, w: {mini: [.2, .35]}},
 {t: 'Правила', say: 'Каждый агент работает по правилам: это текст, который модель перечитывает на каждом шаге.',
  set: {tagO: {opacity: 1}, tag0: {opacity: 1}, tag1: {opacity: 1}, tag2: {opacity: 1}},
  w: {tagO: [.35, .5], tag0: [.45, .6], tag1: [.5, .65], tag2: [.55, .7]}},
 {t: 'Заплатка', say: 'Иногда нужна срочная заплатка: «пока делай так». Её дописывают в правила.',
  set: {sheetLayer: {opacity: 1}, st0: {opacity: 1}}, w: {sheetLayer: [.1, .25], st0: [.55, .7]}},
 {t: 'Навсегда', say: 'А дальше она живёт вечно: про неё забывают, она мешает, и каждый шаг тратит на неё токены.',
  set: {st1: {opacity: 1}, st2: {opacity: 1}, st3: {opacity: 1}, st4: {opacity: 1}, harm: {opacity: 1}},
  w: {st1: [.05, .15], st2: [.12, .22], st3: [.19, .29], st4: [.26, .36], harm: [.4, .55]}},
 {t: 'Флаги', say: 'В разработке это знакомая история временных флагов: у каждого есть хозяин и срок годности.',
  set: {sheetLayer: {opacity: 0}, flagLayer: {opacity: 1}, flagOwner: {opacity: 1}, flagTtl: {opacity: 1}},
  w: {sheetLayer: [0, .1], flagLayer: [.08, .2], flagOwner: [.6, .7], flagTtl: [.75, .85]}},
 {t: 'Временные правила', say: 'Теперь в Оркестре есть временные правила. Оркестратор пишет правило, выбирает, кому оно, и ставит срок.',
  sub: 'Теперь в Orchestra есть временные правила. Оркестратор пишет правило, выбирает, кому оно, и ставит срок.',
  set: {flagLayer: {opacity: 0}, cardLayer: {opacity: 1}, due: {opacity: 1}}, w: {flagLayer: [0, .1], cardLayer: [.08, .2], due: [.8, .9]}},
 {t: 'Пример', say: 'Пример: до вторника Соннет берёт простое, Опус сложное, а Луна даёт только второе мнение. Так мы выжигаем недельный лимит Клода.',
  sub: 'Пример: до вторника Sonnet — простое, Opus — сложное, Luna — только второе мнение. Так выжигаем недельный лимит Claude.',
  set: {chipR1: {fill: '#d6e8f4', stroke: '#0e5e9c'}, chipT1: {fill: '#0e5e9c'}}, w: {chipR1: [.55, .65], chipT1: [.55, .65]}},
 {t: 'Со следующего хода', say: 'Правило появляется у нужных агентов со следующего хода, без перезапуска.',
  set: {cardLayer: {opacity: 0}, ruleTab: {opacity: 1}}, w: {cardLayer: [0, .12], ruleTab: [.4, .55]}},
 {t: 'Режим 1', say: 'Когда срок выходит, есть два режима. Либо правило снимается само.',
  set: {timeLayer: {opacity: 1}, now: {cx: 900}, mode1: {opacity: 1}, mode1v: {opacity: 1}},
  w: {timeLayer: [.1, .22], now: [.2, .6], mode1: [.55, .7], mode1v: [.8, .92]}},
 {t: 'Режим 2', say: 'Либо автору один раз приходит вопрос: продлить, оставить или снять.', set: {mode2: {opacity: 1}}, w: {mode2: [0, .12]}},
 {t: 'Плюсы', say: 'Что хорошо: правило не забудется и не накопится, хозяин виден, права разделены, и никакого интерфейса.',
  set: {timeLayer: {opacity: 0}, prosLayer: {opacity: 1}, pro0: {opacity: 1}, pro1: {opacity: 1}, pro2: {opacity: 1}, pro3: {opacity: 1}},
  w: {timeLayer: [0, .08], prosLayer: [.06, .12], pro0: [.1, .2], pro1: [.32, .42], pro2: [.48, .58], pro3: [.68, .78]}},
 {t: 'Минус: кеш', say: 'Что плохо. Каждое появление или снятие правила один раз сбрасывает кеш промпта у этих агентов, а пересоздание кеша на подписке стоит денег.',
  set: {prosLayer: {opacity: 0}, consLayer: {opacity: 1}, cache: {fill: '#fde4d0'}, cons1: {opacity: 1}},
  w: {prosLayer: [0, .08], consLayer: [.06, .14], cache: [.45, .55], cons1: [.5, .62]}},
 {t: 'Поэтому', say: 'Поэтому блок стоит в самом конце промпта, а правила должны быть редкими.', set: {cons2: {opacity: 1}}, w: {cons2: [.05, .2]}},
 {t: 'Не замок', say: 'И правило это просто текст для модели: она может его нарушить, механического замка нет.', sub: 'И правило — это просто текст для модели: она может его нарушить, механического замка нет.',
  set: {consLayer: {opacity: 0}, textLayer: {opacity: 1}, noLock: {opacity: 1}}, w: {consLayer: [0, .1], textLayer: [.08, .2], noLock: [.55, .7]}},
 {t: 'Итог', say: 'Срочное правило теперь живёт со сроком годности.', hold: 1.4,
  set: {textLayer: {opacity: 0}}, w: {textLayer: [0, .15]}},
];
STEPS.forEach(s => s.x ??= s.sub ?? s.say); window.voice?.(STEPS);
STEPS.forEach(s => s.d ??= Math.max(3, s.say.length / 14));  // браузерный просмотр без озвучки
function draw(i, p, t) {
  const st = []; let at = 0; for (const s of STEPS) { st.push(at); at += s.d; }
  const last = st.length - 1, d0 = STEPS[0].d;
  Paper.brush(PIC, t, 0, 1.2);
  // наезд в монитор в начале; в конце тот же путь назад (время отражено)
  const tc = t < st[last] ? t : st[1] - (t - st[last]) * (st[1] - .4 * d0) / (STEPS[last].d * .6);
  Paper.camera(PIC, Math.max(tc, 0), {...VIEW, t0: .4 * d0, t1: st[1] - .15});
  $('room').setAttribute('opacity', (1 - Paper.fade(t, st[1] - .1) + Paper.fade(t, st[last] - .05)).toFixed(3));
  // схема агентов: шаги 1–2 и 8 (там правило доходит до оркестратора)
  const ag = Paper.fade(t, st[1] - .15) - Paper.fade(t, st[2], .3) + Paper.fade(t, st[7] + STEPS[7].d * .1, .35) - Paper.fade(t, st[8], .3);
  $('agentsLayer').setAttribute('opacity', Math.max(0, ag).toFixed(3));
  $('hm').setAttribute('transform', `rotate(${(300 + t * 9).toFixed(2)} 860 100)`);
  $('hh').setAttribute('transform', `rotate(${(-40 + t * .75).toFixed(2)} 860 100)`);
  const s6 = st[6], d6 = STEPS[6].d;
  Paper.type($('rule1'), 'До вторника: Sonnet — простое, Opus — сложное,', t, s6 + .1, s6 + .1 + d6 * .3, {cursor: false});
  Paper.type($('rule2'), 'Luna — только второе мнение.', t, s6 + .1 + d6 * .3, s6 + .1 + d6 * .45, {cursor: t < st[7]});
  const s9 = st[9], d9 = STEPS[9].d;
  Paper.type($('ask1'), 'срок вышел — реши:', t, s9 + .2, s9 + .2 + d9 * .3, {cursor: false});
  Paper.type($('ask2'), 'продлить · оставить · снять', t, s9 + .2 + d9 * .3, s9 + .2 + d9 * .7, {cursor: t < st[10]});
}
"""

html = re.sub(r'<div class="stg"><svg id="stage".*?</svg></div>', lambda _: f'<div class="stg">{SVG}</div>', tpl, count=1, flags=re.S)
html = re.sub(r"const STEPS = \[.*?\];\n", lambda _: JS.lstrip("\n"), html, count=1, flags=re.S)
html = html.replace("<title>Title</title>", "<title>Временные правила — V-929</title>", 1)
sys.stdout.write(html)
