"""V-949: вертикальная (9:16) пересборка ролика V-937 «рестарт без потерь», сокращённая до ~50 с.

Берёт плеер из V-937/scene.html, меняет SVG и сценарий. Сцена живёт в мировых координатах 1280-кадра:
viewBox "280 0 720 720" показывает полосу x 280…1000 вокруг монитора (640), поэтому нарисованные
открытие и концовка и их наезд на экран остаются прежними, а схемы рисуются в колонку 720 × 720
(X(v) = 280 + v). Запуск: python3 build_vertical.py > scene.html
"""
import re
from pathlib import Path

HERE = Path(__file__).parent
src = (HERE.parent / "V-937" / "scene.html").read_text()
X = lambda v: 280 + v
CARD = '<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="16" fill="#fff" stroke="#d9dce3" stroke-width="2"/>'


def card(x, y, w, h):
    return CARD.format(x=X(x), y=y, w=w, h=h)


AGENTS = "".join(card(x, 400, 200, 110)
                 + f'<text x="{X(x + 100)}" y="470" text-anchor="middle" font-size="40">агент</text>'
                 + f'<path id="wire{k}" d="M{X(360)} 240L{X(x + 100)} 400" stroke="#c9ced8" stroke-width="4" fill="none"/>'
                 for k, x in enumerate((20, 260, 500)))

FIVE = "".join(
    f'<g id="a{k}" opacity="0">' + card(40, 110 + k * 100, 640, 84)
    + f'<text x="{X(70)}" y="{110 + k * 100 + 56}" font-size="38">агент {k + 1}</text>'
    + f'<text id="av{k}" x="{X(655)}" y="{110 + k * 100 + 56}" text-anchor="end" font-size="34" opacity="0" '
    + ('fill="#0e5e9c">✓ продолжил</text>' if k < 3 else 'fill="#c9551b">✗ ход пропал</text>') + '</g>'
    for k in range(5))

NUMS = "".join(
    f'<g id="n{k}" opacity="0">' + card(40, 90 + k * 190, 640, 160)
    + f'<text x="{X(70)}" y="{90 + k * 190 + 105}" font-size="92" font-weight="700" class="mono" fill="#0e5e9c">{v}</text>'
    + f'<text x="{X(340)}" y="{90 + k * 190 + 95}" font-size="36" fill="#6b7280">{label}</text></g>'
    for k, (v, label) in enumerate((("40 с", "пауза"), ("25", "заданий поднято"), ("2", "бежали в рестарт"))))

SVG = f"""<svg id="stage" viewBox="280 0 720 720" role="img" aria-labelledby="st"><title id="st">Рестарт Orchestra без потерь</title>
<g id="room"></g>
<g id="roomEnd" opacity="0"></g>
<g id="agentsLayer" opacity="0">
 <g id="agents">
  <rect id="plat" x="{X(160)}" y="130" width="400" height="110" rx="16" fill="#fff" stroke="#d9dce3" stroke-width="2"/>
  <text id="platT" x="{X(360)}" y="202" text-anchor="middle" font-size="48" font-weight="600">Orchestra</text>
  {AGENTS}
 </g>
 <text id="rst" x="{X(360)}" y="330" text-anchor="middle" font-size="40" fill="#c9551b" opacity="0">↻ перезапуск: новый код</text>
</g>
<g id="lossLayer" opacity="0">
 <text x="{X(360)}" y="70" text-anchor="middle" font-size="34" fill="#6b7280">рестарт 17.10: в работе 5 агентов</text>
 {FIVE}
 <text id="loss" x="{X(360)}" y="670" text-anchor="middle" font-size="52" font-weight="700" fill="#c9551b" opacity="0">2 из 5 агентов — 40 %</text>
</g>
<g id="jobLayer" opacity="0">
 <text x="{X(360)}" y="90" text-anchor="middle" font-size="34" fill="#6b7280">фоновое задание: прогон тестов</text>
 <rect x="{X(40)}" y="140" width="640" height="80" rx="14" fill="#eef0f3"/>
 <rect id="jobBar" x="{X(40)}" y="140" width="0" height="80" rx="14" fill="#d6e8f4"/>
 <path id="jobCut" d="M{X(360)} 120V250" stroke="#c9551b" stroke-width="6" opacity="0"/>
 <text id="jobCutT" x="{X(378)}" y="285" font-size="34" fill="#c9551b" opacity="0">рестарт</text>
 <text id="jobMsg" x="{X(40)}" y="400" font-size="34" class="mono" fill="#c9551b"></text>
 <text id="jobAgain" x="{X(40)}" y="500" font-size="40" fill="#c9551b" opacity="0">✗ всё запускают заново</text>
</g>
<g id="turnLayer" opacity="0">
 <text x="{X(360)}" y="80" text-anchor="middle" font-size="34" fill="#6b7280">один ход агента</text>
 <path d="M{X(80)} 220H{X(640)}" stroke="#c9ced8" stroke-width="7"/>
 <circle cx="{X(80)}" cy="220" r="16" fill="#16171b"/><text x="{X(80)}" y="270" text-anchor="middle" font-size="30">начало</text>
 <circle cx="{X(640)}" cy="220" r="16" fill="#16171b"/><text x="{X(640)}" y="270" text-anchor="middle" font-size="30">конец</text>
 <g id="oldId" opacity="0"><rect x="{X(300)}" y="320" width="380" height="76" rx="12" fill="#fde4d0" stroke="#c9551b" stroke-width="2"/>
  <text x="{X(490)}" y="370" text-anchor="middle" font-size="32" fill="#c9551b">раньше: номер здесь</text></g>
 <g id="newId" opacity="0"><rect x="{X(40)}" y="420" width="420" height="76" rx="12" fill="#d6e8f4" stroke="#0e5e9c" stroke-width="2"/>
  <text x="{X(250)}" y="470" text-anchor="middle" font-size="32" fill="#0e5e9c">теперь: номер здесь ✓</text></g>
 <g id="turnCut" opacity="0"><path d="M{X(360)} 150V210" stroke="#c9551b" stroke-width="6"/>
  <text x="{X(360)}" y="135" text-anchor="middle" font-size="30" fill="#c9551b">рестарт</text></g>
 <text id="resume" x="{X(360)}" y="600" text-anchor="middle" font-size="36" fill="#0e5e9c"></text>
</g>
<g id="fileLayer" opacity="0">
 <g id="oldProc">{card(40, 60, 290, 100)}<text x="{X(185)}" y="123" text-anchor="middle" font-size="32">старый процесс</text></g>
 <text id="oldX" x="{X(185)}" y="215" text-anchor="middle" font-size="34" fill="#c9551b" opacity="0">✗ остановлен</text>
 {card(40, 330, 290, 110)}<text x="{X(185)}" y="396" text-anchor="middle" font-size="34">задание</text>
 <g id="fileBox" opacity="0"><rect x="{X(400)}" y="330" width="280" height="110" rx="16" fill="#d6e8f4" stroke="#0e5e9c" stroke-width="2"/>
  <text x="{X(540)}" y="375" text-anchor="middle" font-size="30" fill="#0e5e9c">файл:</text>
  <text x="{X(540)}" y="415" text-anchor="middle" font-size="30" fill="#0e5e9c">вывод + код</text></g>
 <path id="toFile" d="M{X(335)} 385H{X(390)}" stroke="#0e5e9c" stroke-width="5" marker-end="url(#paper-arrow)" opacity="0"/>
 <g id="newProc" opacity="0"><rect x="{X(400)}" y="60" width="280" height="100" rx="16" fill="#fff" stroke="#0e5e9c" stroke-width="3"/>
  <text x="{X(540)}" y="123" text-anchor="middle" font-size="32" fill="#0e5e9c">новый процесс</text></g>
 <path id="readFile" d="M{X(540)} 320V172" stroke="#0e5e9c" stroke-width="5" marker-end="url(#paper-arrow)" opacity="0"/>
 <text id="fileRes" x="{X(360)}" y="560" text-anchor="middle" font-size="36" fill="#0e5e9c" opacity="0">ждёт конца → отдаёт результат ✓</text>
</g>
<g id="numLayer" opacity="0">
 <text x="{X(360)}" y="50" text-anchor="middle" font-size="32" fill="#6b7280">живой рестарт 17.10</text>
 {NUMS}
</g>
<g id="consLayer" opacity="0">
 <text id="con1" x="{X(40)}" y="170" font-size="36" fill="#c9551b" opacity="0">✗ команды внутри хода</text>
 <text id="con1x" x="{X(78)}" y="222" font-size="36" fill="#c9551b" opacity="0">обрываются</text>
 <text id="con1b" x="{X(40)}" y="285" font-size="30" fill="#6b7280" opacity="0">агент узнаёт из напоминания</text>
 <text id="con2" x="{X(40)}" y="430" font-size="36" fill="#c9551b" opacity="0">✗ на время рестарта все ждут</text>
 <text id="con2b" x="{X(40)}" y="490" font-size="30" fill="#6b7280" opacity="0">в этот раз — 40 секунд</text>
</g>
<g id="endLayer" opacity="0">
 <g id="endCard">
  <rect x="{X(40)}" y="150" width="640" height="320" rx="18" fill="#fff" stroke="#0e5e9c" stroke-width="3"/>
  <text x="{X(360)}" y="290" text-anchor="middle" font-size="60" font-weight="700" fill="#0e5e9c">рестарт = пауза</text>
  <text x="{X(360)}" y="380" text-anchor="middle" font-size="40" fill="#16171b">а не потеря работы ✓</text>
 </g>
</g>
</svg>"""

JS = r"""Paper.install();
const BOX = {x: 280, y: 20, w: 720, h: 600};
const PIC = Paper.picture('room', BOX, {scene: 'night-desk'});
const VIEW = Paper.view('night-desk', {to: [640, 320], width: 700});
const MINI = Paper.mini(PIC, 'agents', VIEW);
MINI.setAttribute('opacity', 0);
const END = Paper.picture('roomEnd', BOX, {scene: 'cafe'});
const VEND = Paper.view('cafe', {to: [640, 320], width: 700});
Paper.mini(END, 'endCard', VEND);
const STEPS = [
 {t: 'Агенты работают', say: 'Оркестра это команда ИИ-агентов: они часами работают сами и запускают долгие фоновые задания.',
  sub: 'Orchestra — команда ИИ-агентов: они часами работают сами и запускают долгие фоновые задания.'},
 {t: 'Перезапуск', say: 'Но иногда платформу надо перезапустить, чтобы включить новый код.',
  set: {plat: {fill: '#fde4d0', stroke: '#c9551b'}, platT: {fill: '#c9551b'}, rst: {opacity: 1},
        wire0: {stroke: '#fde4d0'}, wire1: {stroke: '#fde4d0'}, wire2: {stroke: '#fde4d0'}},
  w: {plat: [.35, .5], platT: [.35, .5], rst: [.45, .6], wire0: [.5, .65], wire1: [.5, .65], wire2: [.5, .65]}},
 {t: 'Потеря', say: 'Раньше перезапуск застал за работой пятерых агентов, и у двоих работа молча пропала: это сорок процентов.',
  sub: 'Раньше перезапуск застал за работой 5 агентов, и у 2 работа молча пропала: это 40 %.',
  set: {lossLayer: {opacity: 1}, a0: {opacity: 1}, a1: {opacity: 1}, a2: {opacity: 1}, a3: {opacity: 1}, a4: {opacity: 1},
        av0: {opacity: 1}, av1: {opacity: 1}, av2: {opacity: 1}, av3: {opacity: 1}, av4: {opacity: 1}, loss: {opacity: 1}},
  w: {lossLayer: [0, .1], a0: [.12, .2], a1: [.16, .24], a2: [.2, .28], a3: [.24, .32], a4: [.28, .36],
      av0: [.4, .48], av1: [.43, .51], av2: [.46, .54], av3: [.6, .68], av4: [.63, .71], loss: [.8, .9]}},
 {t: 'Задания обрывались', say: 'Фоновые задания, например длинный прогон тестов, обрывались, и всё запускали заново.',
  set: {lossLayer: {opacity: 0}, jobLayer: {opacity: 1}, jobCut: {opacity: 1}, jobCutT: {opacity: 1}, jobAgain: {opacity: 1}},
  w: {lossLayer: [0, .08], jobLayer: [.06, .16], jobCut: [.45, .52], jobCutT: [.45, .52], jobAgain: [.8, .9]}},
 {t: 'Номер разговора', say: 'Теперь номер разговора запоминается в начале хода, и агента поднимают словами: продолжай с м+еста остановки.',
  sub: 'Номер разговора запоминается в начале хода: «продолжай с места остановки».',
  set: {jobLayer: {opacity: 0}, turnLayer: {opacity: 1}, newId: {opacity: 1}, oldId: {opacity: 1}, turnCut: {opacity: 1}},
  w: {jobLayer: [0, .06], turnLayer: [.04, .12], newId: [.2, .3], oldId: [.35, .45], turnCut: [.55, .65]}},
 {t: 'Вывод в файл', say: 'А фоновое задание пишет вывод и код завершения в файл, и новый процесс отдаёт результат агенту.',
  set: {turnLayer: {opacity: 0}, fileLayer: {opacity: 1}, fileBox: {opacity: 1}, toFile: {opacity: 1},
        oldProc: {opacity: .35}, oldX: {opacity: 1}, newProc: {opacity: 1}, readFile: {opacity: 1}, fileRes: {opacity: 1}},
  w: {turnLayer: [0, .06], fileLayer: [.04, .1], fileBox: [.18, .28], toFile: [.2, .3], oldProc: [.4, .5], oldX: [.4, .5],
      newProc: [.55, .65], readFile: [.65, .75], fileRes: [.82, .92]}},
 {t: 'Проверка', say: 'Проверка в тот же день: пауза сорок секунд, поднято двадцать пять заданий, два бежали прямо во время перезапуска.',
  sub: 'Проверка в тот же день: пауза 40 с, поднято 25 заданий, 2 бежали прямо во время перезапуска.',
  set: {fileLayer: {opacity: 0}, numLayer: {opacity: 1}, n0: {opacity: 1}, n1: {opacity: 1}, n2: {opacity: 1}},
  w: {fileLayer: [0, .05], numLayer: [.03, .08], n0: [.2, .3], n1: [.45, .55], n2: [.72, .82]}},
 {t: 'Минус', say: 'Честный минус: команды внутри хода обрываются, а на время рестарта агенты ждут.',
  set: {numLayer: {opacity: 0}, consLayer: {opacity: 1}, con1: {opacity: 1}, con1x: {opacity: 1}, con1b: {opacity: 1}, con2: {opacity: 1}, con2b: {opacity: 1}},
  w: {numLayer: [0, .06], consLayer: [.04, .1], con1: [.1, .2], con1x: [.1, .2], con1b: [.3, .4], con2: [.6, .7], con2b: [.75, .85]}},
 {t: 'Итог', say: 'Рестарт теперь просто пауза, а не потеря работы.', hold: 1.6,
  set: {consLayer: {opacity: 0}}, w: {consLayer: [0, .15]}},
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
  const ag = Paper.fade(t, st[1] - .15) - Paper.fade(t, st[2], .3);
  $('agentsLayer').setAttribute('opacity', Math.max(0, ag).toFixed(3));
  // полоса прогона растёт до рестарта (середина полосы) и встаёт
  const s3 = st[3], d3 = STEPS[3].d;
  $('jobBar').setAttribute('width', (320 * Math.min(1, Math.max(0, (t - s3 - d3 * .12) / (d3 * .33)))).toFixed(1));
  Paper.type($('jobMsg'), '[Background job INTERRUPTED]', t, s3 + d3 * .55, s3 + d3 * .78, {cursor: t < st[4]});
  Paper.type($('resume'), '«продолжай с места остановки»', t, st[4] + STEPS[4].d * .7, st[4] + STEPS[4].d * .95, {cursor: t < st[5]});
  $('roomEnd').setAttribute('opacity', t >= st[last] ? 1 : 0);
  Paper.brush(END, t, st[last], 1.2); Paper.live(END, t);
  const dl = STEPS[last].d;
  Paper.camera(END, st[last] + dl - (t - st[last]), {...VEND, t0: st[last] + .2 * dl, t1: st[last] + .75 * dl});
}
"""

html = re.sub(r'<div class="stg"><svg id="stage".*?</svg></div>', lambda _: f'<div class="stg">{SVG}</div>', src, count=1, flags=re.S)
html = re.sub(r"Paper\.install\(\);.*?\n\}\n", lambda _: JS, html, count=1, flags=re.S)
html = html.replace("<title>Рестарт без потерь — V-937</title>", "<title>Рестарт без потерь — V-949 (9:16)</title>", 1)
print(html)
