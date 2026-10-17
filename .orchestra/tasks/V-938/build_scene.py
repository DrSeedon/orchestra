"""V-938: ролик «частичные копии репозитория» в стиле «бумага».

Сцена = каркас плеера из html-artifacts без правок + SVG и STEPS этого ролика.
Открытие — night-desk (проблема: диск заполнен), концовка — cafe («теперь стало так»).
Факты: .orchestra/tasks/V-821/report.md (размеры и время копии, доля доработок),
постановка задачи V-938 (диск 96% → 84%, −48 ГБ — итог всей чистки 17.10, включая убитых
лишних воркеров).
Запуск: python3 build_scene.py <путь к animation.md> > scene.html
"""
import re
import sys
from pathlib import Path

md = Path(sys.argv[1]).read_text()
tpl = re.search(r"```html motion-template\n(.*?)```", md, re.S).group(1)

CARDS = "".join(
    f'<path d="M640 120L{x + 150} 190" stroke="#c9ced8" stroke-width="3" fill="none"/>'
    f'<rect id="card{k}" x="{x}" y="190" width="300" height="330" rx="14" fill="#fff" stroke="#d9dce3" stroke-width="2"/>'
    f'<text x="{x + 150}" y="232" text-anchor="middle" font-size="32" font-weight="600">агент {k + 1}</text>'
    f'<rect x="{x + 20}" y="250" width="260" height="56" rx="8" fill="#d6e8f4"/>'
    f'<text x="{x + 150}" y="288" text-anchor="middle" font-size="28" fill="#0e5e9c">исходники</text>'
    f'<rect id="own{k}" x="{x + 20}" y="316" width="260" height="50" rx="8" fill="#eef0f3"/>'
    f'<text id="ownT{k}" x="{x + 150}" y="350" text-anchor="middle" font-size="26" fill="#3b3e46">своя задача</text>'
    f'<g id="arch{k}"><rect x="{x + 20}" y="376" width="260" height="128" rx="8" fill="#fde4d0" stroke="#c9551b" stroke-width="2"/>'
    f'<text x="{x + 150}" y="432" text-anchor="middle" font-size="28" fill="#c9551b">чужие архивы</text>'
    f'<text x="{x + 150}" y="470" text-anchor="middle" font-size="24" fill="#c9551b">и результаты</text></g>'
    for k, x in enumerate((90, 490, 890)))

# 4246 МБ и 40 МБ, 48,0 с и 1,39 с — полоса в масштабе: 980 единиц = большее значение
W = 980
RES = f"""
 <text x="150" y="80" font-size="30" fill="#6b7280">размер одной копии</text>
 <rect x="150" y="100" width="{W}" height="56" rx="8" fill="#eef0f3"/>
 <rect id="szBar" x="150" y="100" width="{W}" height="56" rx="8" fill="#fde4d0" stroke="#c9551b" stroke-width="2"/>
 <text id="szT" x="150" y="210" font-size="38" class="mono" fill="#c9551b">4 246 МБ</text>
 <text id="szN" x="420" y="210" font-size="38" class="mono" fill="#0e5e9c" opacity="0">→ 40 МБ  ✓</text>
 <text x="150" y="300" font-size="30" fill="#6b7280">создание копии</text>
 <rect x="150" y="320" width="{W}" height="56" rx="8" fill="#eef0f3"/>
 <rect id="tmBar" x="150" y="320" width="{W}" height="56" rx="8" fill="#fde4d0" stroke="#c9551b" stroke-width="2"/>
 <text id="tmT" x="150" y="430" font-size="38" class="mono" fill="#c9551b">48,0 с</text>
 <text id="tmN" x="350" y="430" font-size="38" class="mono" fill="#0e5e9c" opacity="0">→ 1,39 с  ✓</text>"""

MINUS = "".join(
    f'<text x="150" y="{y + 40}" font-size="30">{label}</text>'
    f'<rect x="420" y="{y}" width="{W - 270}" height="54" rx="8" fill="#eef0f3"/>'
    f'<rect id="mb{k}" x="420" y="{y}" width="0" height="54" rx="8" fill="#fde4d0" stroke="#c9551b" stroke-width="2"/>'
    f'<text id="mt{k}" x="{420 + (W - 270) * pct / 100 + 16}" y="{y + 40}" font-size="34" class="mono" fill="#c9551b" opacity="0">{pct}%</text>'
    for k, (label, pct, y) in enumerate((("проект 1", 29, 200), ("проект 2", 24, 280), ("Orchestra", 6, 360))))

SVG = f"""<svg id="stage" viewBox="0 0 1280 590" role="img" aria-labelledby="st"><title id="st">Частичные копии репозитория у агентов Orchestra</title>
<g id="room"></g>
<g id="roomEnd" opacity="0"></g>
<g id="copiesLayer" opacity="0">
 <g id="copies">
  <rect id="mainBox" x="420" y="30" width="440" height="90" rx="14" fill="#fff" stroke="#d9dce3" stroke-width="2"/>
  <text x="640" y="88" text-anchor="middle" font-size="34" font-weight="600">основная копия проекта</text>
  {CARDS}
 </g>
 <g id="readLayer" opacity="0">
  <path d="M760 120C880 130 1000 150 1060 186" stroke="#0e5e9c" stroke-width="4" stroke-dasharray="12 9" fill="none" marker-end="url(#paper-arrow)"/>
  <rect x="890" y="52" width="250" height="46" rx="10" fill="#d6e8f4"/>
  <text x="1015" y="84" text-anchor="middle" font-size="26" fill="#0e5e9c">читает отсюда</text>
 </g>
 <g id="addLayer" opacity="0">
  <rect x="510" y="376" width="260" height="56" rx="8" fill="#fde4d0" stroke="#c9551b" stroke-width="2" stroke-dasharray="8 6"/>
  <text x="640" y="413" text-anchor="middle" font-size="26" fill="#c9551b">+ одна папка</text>
 </g>
</g>
<g id="sizeLayer" opacity="0">
 <text x="640" y="110" text-anchor="middle" font-size="32" fill="#6b7280">одна полная копия, проект 1</text>
 <text x="640" y="230" text-anchor="middle" font-size="96" class="mono" fill="#c9551b">4 246 МБ</text>
 <text id="times" x="640" y="350" text-anchor="middle" font-size="44" class="mono" opacity="0">× ~14 копий воркеров</text>
</g>
<g id="diskLayer" opacity="0">
 <text id="diskL" x="150" y="110" font-size="32" fill="#6b7280">диск сервера, 17.10</text>
 <rect x="150" y="150" width="{W}" height="90" rx="12" fill="#eef0f3"/>
 <rect id="diskBar" x="150" y="150" width="0" height="90" rx="12" fill="#fde4d0" stroke="#c9551b" stroke-width="2"/>
 <text id="diskPct" x="150" y="350" font-size="88" class="mono" fill="#c9551b">0%</text>
 <text id="freed" x="560" y="345" font-size="44" class="mono" fill="#0e5e9c" opacity="0">освободилось 48 ГБ ✓</text>
 <g id="partsLayer" opacity="0">
  <rect x="150" y="410" width="440" height="60" rx="10" fill="#d6e8f4"/>
  <text x="370" y="450" text-anchor="middle" font-size="28" fill="#0e5e9c">частичные копии</text>
  <text x="640" y="452" text-anchor="middle" font-size="40" fill="#6b7280">+</text>
  <rect x="690" y="410" width="440" height="60" rx="10" fill="#d6e8f4"/>
  <text x="910" y="450" text-anchor="middle" font-size="28" fill="#0e5e9c">убитые лишние воркеры</text>
 </g>
</g>
<g id="resLayer" opacity="0">{RES}</g>
<g id="minusLayer" opacity="0">
 <text x="150" y="80" font-size="36" fill="#c9551b">✗ доработка: прошлого результата в копии нет</text>
 <text x="150" y="140" font-size="28" fill="#6b7280">доля таких задач среди прошлых</text>
 {MINUS}
 <text id="minusFix" x="150" y="490" font-size="30" fill="#0e5e9c" opacity="0">читается из основной копии или догружается</text>
</g>
</svg>"""

JS = r"""
Paper.install();
const BOX = {x: 96, y: 18, w: 1088, h: 556};
const PIC = Paper.picture('room', BOX, {scene: 'night-desk'});
const VIEW = Paper.view('night-desk', {to: [640, 275], width: 1100});
const MINI = Paper.mini(PIC, 'copies', VIEW);
MINI.setAttribute('opacity', 0);
const END = Paper.picture('roomEnd', BOX, {scene: 'cafe'});
Paper.mini(END, 'copies', Paper.view('cafe', {to: [640, 275], width: 1100}));
const ARCH = {}, SHRINK = {};
for (const k of [0, 1, 2]) { ARCH[`arch${k}`] = {opacity: 0}; SHRINK[`card${k}`] = {height: 196}; }
const STEPS = [
 {t: 'Копии', say: 'В Оркестре над проектом работают несколько агентов сразу, и у каждого своя копия проекта.',
  sub: 'В Orchestra над проектом работают несколько агентов сразу, и у каждого своя копия проекта.'},
 {t: 'Полная копия', say: 'Раньше копия была полной: исходники, своя задача и заодно вс+е чужие архивы и результаты.'},
 {t: 'Пример', say: 'В одном проекте такая копия весила больше четырёх гигабайт. А воркеров там было около четырнадцати.',
  sub: 'В одном проекте такая копия весила больше 4 ГБ (4 246 МБ). А воркеров там было около четырнадцати.',
  set: {sizeLayer: {opacity: 1}, times: {opacity: 1}}, w: {sizeLayer: [.05, .18], times: [.65, .78]}},
 {t: 'Диск', say: 'Семнадцатого октября диск сервера был заполнен на девяносто шесть процентов.',
  sub: '17 октября диск сервера был заполнен на 96%.',
  set: {sizeLayer: {opacity: 0}, diskLayer: {opacity: 1}, diskBar: {width: 940.8}}, w: {sizeLayer: [0, .1], diskLayer: [.08, .2], diskBar: [.3, .85]}},
 {t: 'Частичная копия', say: 'Теперь копия частичная: исходники и папка своей задачи. Чужих архивов в ней нет.',
  set: {diskLayer: {opacity: 0}, ...ARCH, ...SHRINK, own0: {fill: '#d6e8f4'}, own1: {fill: '#d6e8f4'}, own2: {fill: '#d6e8f4'},
        ownT0: {fill: '#0e5e9c'}, ownT1: {fill: '#0e5e9c'}, ownT2: {fill: '#0e5e9c'}},
  w: {diskLayer: [0, .1], own0: [.35, .5], own1: [.35, .5], own2: [.35, .5], ownT0: [.35, .5], ownT1: [.35, .5], ownT2: [.35, .5],
      arch0: [.6, .8], arch1: [.6, .8], arch2: [.6, .8], card0: [.65, .95], card1: [.65, .95], card2: [.65, .95]}},
 {t: 'Чтение', say: 'Нужен чужой результат? Агент читает его прямо из основной копии и ничего не тянет к себе.',
  set: {readLayer: {opacity: 1}}, w: {readLayer: [.25, .45]}},
 {t: 'Догрузка', say: 'А если надо изменить файл за пределами копии, агент догружает только эту папку.',
  set: {readLayer: {opacity: 0}, addLayer: {opacity: 1}, card1: {height: 256}}, w: {readLayer: [0, .15], card1: [.5, .7], addLayer: [.55, .7]}},
 {t: 'Размер и скорость', say: 'Та же копия весит теперь сорок мегабайт и создаётся не за сорок восемь секунд, а меньше ч+ем за полторы.',
  sub: 'Та же копия весит теперь 40 МБ и создаётся не за 48 секунд, а меньше чем за полторы.',
  set: {resLayer: {opacity: 1}, szBar: {width: 9.2, fill: '#d6e8f4', stroke: '#0e5e9c'}, szN: {opacity: 1},
        tmBar: {width: 28.4, fill: '#d6e8f4', stroke: '#0e5e9c'}, tmN: {opacity: 1}},
  w: {resLayer: [.04, .14], szBar: [.15, .4], szN: [.3, .42], tmBar: [.5, .85], tmN: [.75, .88]}},
 {t: 'Чистка', say: 'Старые копии перевели на новый лад, и после чистки диск заполнен на восемьдесят четыре процента. Освободилось сорок восемь гигабайт.',
  sub: 'Старые копии перевели на новый лад, и после чистки диск заполнен на 84%. Освободилось 48 ГБ.',
  set: {resLayer: {opacity: 0}, diskLayer: {opacity: 1}, diskL: {text: 'диск сервера после чистки'}, diskBar: {width: 823.2, fill: '#d6e8f4', stroke: '#0e5e9c'},
        diskPct: {fill: '#0e5e9c'}, freed: {opacity: 1}},
  w: {resLayer: [0, .08], diskLayer: [.06, .14], diskL: [.06, .14], diskBar: [.25, .6], diskPct: [.25, .6], freed: [.72, .84]}},
 {t: 'Честно', say: 'Честно: эти сорок восемь гигабайт дала вся чистка целиком. Туда вошли и убитые лишние воркеры, а не только частичные копии.',
  sub: 'Честно: эти 48 ГБ дала вся чистка целиком. Туда вошли и убитые лишние воркеры, а не только частичные копии.',
  set: {partsLayer: {opacity: 1}}, w: {partsLayer: [.45, .6]}},
 {t: 'Минус', say: 'Минус: если задача дорабатывает прошлую, её результата в копии нет. В одном проекте так почти каждая третья задача, в самой Оркестре шесть процентов.',
  sub: 'Минус: если задача дорабатывает прошлую, её результата в копии нет. В одном проекте так почти каждая третья задача, в самой Orchestra — 6%.',
  set: {diskLayer: {opacity: 0}, minusLayer: {opacity: 1}, mb0: {width: 206.1}, mt0: {opacity: 1}, mb1: {width: 170.6}, mt1: {opacity: 1},
        mb2: {width: 42.6}, mt2: {opacity: 1}},
  w: {diskLayer: [0, .08], minusLayer: [.06, .16], mb0: [.45, .6], mt0: [.5, .62], mb1: [.55, .68], mt1: [.6, .7], mb2: [.78, .9], mt2: [.82, .92]}},
 {t: 'Цена', say: 'Тогда агент читает его из основной копии или догружает. Это лишний шаг, но не потеря.',
  set: {minusFix: {opacity: 1}}, w: {minusFix: [.05, .2]}},
 {t: 'Итог', say: 'Теперь у каждого агента только то, что нужно для его задачи.', hold: 1.4,
  set: {minusLayer: {opacity: 0}}, w: {minusLayer: [0, .15]}},
];
STEPS.forEach(s => s.x ??= s.sub ?? s.say); window.voice?.(STEPS);
STEPS.forEach(s => s.d ??= Math.max(3, s.say.length / 14));  // браузерный просмотр без озвучки
function draw(i, p, t) {
  const st = []; let at = 0; for (const s of STEPS) { st.push(at); at += s.d; }
  const last = st.length - 1, d0 = STEPS[0].d;
  Paper.brush(PIC, t, 0, 1.2);
  Paper.camera(PIC, t, {...VIEW, t0: .4 * d0, t1: st[1] - .15});
  MINI.setAttribute('opacity', Paper.fade(t, .25 * d0, .4).toFixed(3));
  $('room').setAttribute('opacity', (1 - Paper.fade(t, st[1] - .1)).toFixed(3));
  Paper.live(PIC, t);
  $('roomEnd').setAttribute('opacity', t >= st[last] ? 1 : 0);
  Paper.brush(END, t, st[last], 1.4); Paper.live(END, t);
  // схема копий: шаг 1 (полные копии) и шаги 4–6 (частичные)
  const cp = Paper.fade(t, st[1] - .15) - Paper.fade(t, st[2], .3) + Paper.fade(t, st[4] + STEPS[4].d * .08, .35) - Paper.fade(t, st[7], .3);
  $('copiesLayer').setAttribute('opacity', Math.max(0, cp).toFixed(3));
  // счётчик процента идёт за полосой: 0 → 96 на шаге 3, 96 → 84 на шаге 8
  const bar = +$('diskBar').getAttribute('width');
  $('diskPct').textContent = Math.round(bar / 9.8) + '%';
}
"""

html = re.sub(r'<div class="stg"><svg id="stage".*?</svg></div>', lambda _: f'<div class="stg">{SVG}</div>', tpl, count=1, flags=re.S)
html = re.sub(r"const STEPS = \[.*?\];\n", lambda _: JS.lstrip("\n"), html, count=1, flags=re.S)
html = html.replace("<title>Title</title>", "<title>Частичные копии — V-938</title>", 1)
sys.stdout.write(html)
