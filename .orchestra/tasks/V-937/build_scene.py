"""V-937: ролик «рестарт Orchestra без потерь» (V-919) в стиле «бумага».

Каркас плеера из html-artifacts без правок + SVG и STEPS этого ролика (как V-935/v929).
Открытие — night-desk (проблема), концовка — cafe («утром всё работает»).
Факты: .orchestra/tasks/V-919/report.md (рестарт 17.10 09:17 UTC: 5 агентов в работе, 2 хода
пропали) и журнал сервиса 17.10 12:18–12:35 CEST: стоп 12:18:26 → готов 12:19:06 (40 с),
«bg_jobs: restored 25 jobs», два run-задания «left running across shutdown» → «adopting run»;
bg-8146688059 доставило «Ran 228 tests … OK» в 12:35, bg-aec620f455 — свой код выхода 1.
Запуск: python3 build_scene.py <путь к animation.md> > scene.html
"""
import re
import sys
from pathlib import Path

md = Path(sys.argv[1]).read_text()
tpl = re.search(r"```html motion-template\n(.*?)```", md, re.S).group(1)

CARD = '<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="#fff" stroke="#d9dce3" stroke-width="2"/>'

WORKERS = "".join(
    CARD.format(x=x, y=330, w=300, h=100)
    + f'<text x="{x + 150}" y="393" text-anchor="middle" font-size="36">агент</text>'
    + f'<path id="wire{k}" d="M640 140L{x + 150} 330" stroke="#c9ced8" stroke-width="3" fill="none"/>'
    for k, x in enumerate((90, 490, 890)))

# пять агентов, которых рестарт 17.10 застал в работе: трое продолжили, у двоих ход пропал
FIVE = "".join(
    f'<g id="a{k}" opacity="0">' + CARD.format(x=70 + k * 232, y=130, w=210, h=150)
    + f'<text x="{175 + k * 232}" y="200" text-anchor="middle" font-size="30">агент {k + 1}</text>'
    + f'<text id="av{k}" x="{175 + k * 232}" y="252" text-anchor="middle" font-size="28" opacity="0" '
    + (f'fill="#0e5e9c">✓ продолжил</text>' if k < 3 else f'fill="#c9551b">✗ ход пропал</text>')
    + '</g>'
    for k in range(5))

NUMS = "".join(
    f'<g id="n{k}" opacity="0">' + CARD.format(x=x, y=60, w=330, h=250)
    + f'<text x="{x + 165}" y="190" text-anchor="middle" font-size="88" font-weight="700" class="mono" fill="#0e5e9c">{v}</text>'
    + f'<text x="{x + 165}" y="260" text-anchor="middle" font-size="30" fill="#6b7280">{label}</text></g>'
    for k, (x, v, label) in enumerate(((115, "40 с", "пауза"), (475, "25", "заданий поднято"),
                                        (835, "2", "бежали в рестарт"))))

SVG = f"""<svg id="stage" viewBox="0 0 1280 590" role="img" aria-labelledby="st"><title id="st">Рестарт Orchestra без потерь</title>
<g id="room"></g>
<g id="roomEnd" opacity="0"></g>
<g id="agentsLayer" opacity="0">
 <g id="agents">
  {WORKERS}
  <rect id="plat" x="440" y="40" width="400" height="100" rx="14" fill="#fff" stroke="#d9dce3" stroke-width="2"/>
  <text id="platT" x="640" y="104" text-anchor="middle" font-size="38" font-weight="600">Orchestra</text>
 </g>
 <text id="rst" x="640" y="215" text-anchor="middle" font-size="36" fill="#c9551b" opacity="0">↻ перезапуск: новый код</text>
</g>
<g id="lossLayer" opacity="0">
 <text x="70" y="90" font-size="30" fill="#6b7280">рестарт 17.10: в работе 5 агентов</text>
 {FIVE}
 <text id="loss" x="640" y="370" text-anchor="middle" font-size="48" font-weight="700" fill="#c9551b" opacity="0">2 из 5 агентов — 40 %</text>
 <text id="manual" x="640" y="450" text-anchor="middle" font-size="32"></text>
</g>
<g id="jobLayer" opacity="0">
 <text x="170" y="110" font-size="30" fill="#6b7280">фоновое задание: длинный прогон тестов</text>
 <rect x="170" y="150" width="940" height="70" rx="12" fill="#eef0f3"/>
 <rect id="jobBar" x="170" y="150" width="0" height="70" rx="12" fill="#d6e8f4"/>
 <path id="jobCut" d="M640 120V250" stroke="#c9551b" stroke-width="5" opacity="0"/>
 <text id="jobCutT" x="655" y="270" font-size="28" fill="#c9551b" opacity="0">рестарт</text>
 <text id="jobMsg" x="170" y="360" font-size="38" class="mono" fill="#c9551b"></text>
 <text id="jobAgain" x="170" y="430" font-size="32" fill="#c9551b" opacity="0">✗ агент запускает всё заново</text>
</g>
<g id="turnLayer" opacity="0">
 <text x="150" y="90" font-size="30" fill="#6b7280">один ход агента</text>
 <path d="M150 200H1130" stroke="#c9ced8" stroke-width="6"/>
 <circle cx="170" cy="200" r="14" fill="#16171b"/><text x="170" y="160" text-anchor="middle" font-size="26">начало</text>
 <circle cx="1110" cy="200" r="14" fill="#16171b"/><text x="1110" y="160" text-anchor="middle" font-size="26">конец</text>
 <g id="oldId" opacity="0"><rect x="890" y="240" width="360" height="64" rx="10" fill="#fde4d0" stroke="#c9551b" stroke-width="2"/>
  <text x="1070" y="283" text-anchor="middle" font-size="30" fill="#c9551b">раньше: номер здесь</text></g>
 <g id="newId" opacity="0"><rect x="50" y="240" width="360" height="64" rx="10" fill="#d6e8f4" stroke="#0e5e9c" stroke-width="2"/>
  <text x="230" y="283" text-anchor="middle" font-size="30" fill="#0e5e9c">теперь: номер здесь ✓</text></g>
 <g id="turnCut" opacity="0"><path d="M640 160V240" stroke="#c9551b" stroke-width="5"/>
  <text x="640" y="140" text-anchor="middle" font-size="26" fill="#c9551b">рестарт</text></g>
 <text id="resume" x="640" y="400" text-anchor="middle" font-size="34" fill="#0e5e9c"></text>
</g>
<g id="fileLayer" opacity="0">
 <g id="oldProc">{CARD.format(x=90, y=60, w=300, h=110)}<text x="240" y="126" text-anchor="middle" font-size="30">старый процесс</text></g>
 <text id="oldX" x="240" y="215" text-anchor="middle" font-size="30" fill="#c9551b" opacity="0">✗ остановлен</text>
 {CARD.format(x=490, y=300, w=300, h=110)}<text x="640" y="366" text-anchor="middle" font-size="30">задание</text>
 <g id="fileBox" opacity="0"><rect x="890" y="300" width="300" height="110" rx="14" fill="#d6e8f4" stroke="#0e5e9c" stroke-width="2"/>
  <text x="1040" y="348" text-anchor="middle" font-size="30" fill="#0e5e9c">файл:</text>
  <text x="1040" y="386" text-anchor="middle" font-size="30" fill="#0e5e9c">вывод + код</text></g>
 <path id="toFile" d="M790 355H880" stroke="#0e5e9c" stroke-width="4" marker-end="url(#paper-arrow)" opacity="0"/>
 <g id="newProc" opacity="0"><rect x="890" y="60" width="300" height="110" rx="14" fill="#fff" stroke="#0e5e9c" stroke-width="3"/>
  <text x="1040" y="126" text-anchor="middle" font-size="30" fill="#0e5e9c">новый процесс</text></g>
 <path id="readFile" d="M1040 290V180" stroke="#0e5e9c" stroke-width="4" marker-end="url(#paper-arrow)" opacity="0"/>
 <text id="fileRes" x="640" y="500" text-anchor="middle" font-size="34" fill="#0e5e9c" opacity="0">ждёт конца → отдаёт результат агенту ✓</text>
</g>
<g id="numLayer" opacity="0">
 <text x="115" y="40" font-size="26" fill="#6b7280">живой рестарт 17.10</text>
 {NUMS}
 <text id="res1" x="115" y="390" font-size="34" class="mono"></text>
 <text id="res2" x="115" y="450" font-size="30" fill="#0e5e9c" opacity="0">второе вернуло свой код ошибки, а не «прервано»</text>
</g>
<g id="consLayer" opacity="0">
 <text id="con1" x="150" y="150" font-size="36" fill="#c9551b" opacity="0">✗ команды внутри хода обрываются</text>
 <text id="con1b" x="190" y="210" font-size="30" fill="#6b7280" opacity="0">агент узнаёт из напоминания и проверяет результат</text>
 <text id="con2" x="150" y="320" font-size="36" fill="#c9551b" opacity="0">✗ на время рестарта всё стоит на паузе</text>
 <text id="con2b" x="190" y="380" font-size="30" fill="#6b7280" opacity="0">в этот раз — 40 секунд</text>
</g>
<g id="endLayer" opacity="0">
 <g id="endCard">
  <rect x="190" y="90" width="900" height="290" rx="16" fill="#fff" stroke="#0e5e9c" stroke-width="3"/>
  <text x="640" y="215" text-anchor="middle" font-size="64" font-weight="700" fill="#0e5e9c">рестарт = пауза</text>
  <text x="640" y="300" text-anchor="middle" font-size="44" fill="#16171b">а не потеря работы ✓</text>
 </g>
</g>
</svg>"""

JS = r"""
Paper.install();
const BOX = {x: 96, y: 18, w: 1088, h: 556};
const PIC = Paper.picture('room', BOX, {scene: 'night-desk'});
const VIEW = Paper.view('night-desk', {to: [640, 235], width: 1100});
const MINI = Paper.mini(PIC, 'agents', VIEW);
MINI.setAttribute('opacity', 0);
const END = Paper.picture('roomEnd', BOX, {scene: 'cafe'});
const VEND = Paper.view('cafe', {to: [640, 235], width: 1100});
Paper.mini(END, 'endCard', VEND);
const STEPS = [
 {t: 'Агенты работают', say: 'Оркестра это команда ИИ-агентов: они часами работают сами и запускают долгие фоновые задания.',
  sub: 'Orchestra — команда ИИ-агентов: они часами работают сами и запускают долгие фоновые задания.'},
 {t: 'Перезапуск', say: 'Но иногда платформу надо перезапустить, чтобы включить новый код.',
  set: {plat: {fill: '#fde4d0', stroke: '#c9551b'}, platT: {fill: '#c9551b'}, rst: {opacity: 1},
        wire0: {stroke: '#fde4d0'}, wire1: {stroke: '#fde4d0'}, wire2: {stroke: '#fde4d0'}},
  w: {plat: [.35, .5], platT: [.35, .5], rst: [.45, .6], wire0: [.5, .65], wire1: [.5, .65], wire2: [.5, .65]}},
 {t: 'Живой пример', say: 'Живой пример. Семнадцатого октября перезапуск застал за работой пятерых агентов.',
  sub: 'Живой пример. 17 октября перезапуск застал за работой пятерых агентов.',
  set: {lossLayer: {opacity: 1}, a0: {opacity: 1}, a1: {opacity: 1}, a2: {opacity: 1}, a3: {opacity: 1}, a4: {opacity: 1}},
  w: {lossLayer: [0, .15], a0: [.3, .4], a1: [.36, .46], a2: [.42, .52], a3: [.48, .58], a4: [.54, .64]}},
 {t: 'Потеря', say: 'Трое продолжили, а у двоих работа молча пропала: это сорок процентов.',
  sub: 'Трое продолжили, а у двоих работа молча пропала: это 40 %.',
  set: {av0: {opacity: 1}, av1: {opacity: 1}, av2: {opacity: 1}, av3: {opacity: 1}, av4: {opacity: 1}, loss: {opacity: 1}},
  w: {av0: [.05, .15], av1: [.08, .18], av2: [.11, .21], av3: [.4, .5], av4: [.43, .53], loss: [.7, .82]}},
 {t: 'Вручную', say: 'Оркестратор пересылал им задания вручную.'},
 {t: 'Фоновые задания', say: 'Фоновые задания, например длинный прогон тестов, обрывались.',
  set: {lossLayer: {opacity: 0}, jobLayer: {opacity: 1}, jobCut: {opacity: 1}, jobCutT: {opacity: 1}},
  w: {lossLayer: [0, .1], jobLayer: [.08, .2], jobCut: [.75, .85], jobCutT: [.75, .85]}},
 {t: 'Заново', say: 'Агенту приходило «прервано», и всё запускали заново.',
  set: {jobAgain: {opacity: 1}}, w: {jobAgain: [.6, .75]}},
 {t: 'Номер разговора', say: 'Теперь номер разговора с агентом запоминается в начале его хода, а не в конце.',
  set: {jobLayer: {opacity: 0}, turnLayer: {opacity: 1}, newId: {opacity: 1}, oldId: {opacity: 1}},
  w: {jobLayer: [0, .08], turnLayer: [.06, .16], newId: [.45, .6], oldId: [.78, .9]}},
 {t: 'Продолжай', say: 'После перезапуска агента поднимают по этому номеру со словами: продолжай с м+еста остановки.',
  set: {oldId: {opacity: 0}, turnCut: {opacity: 1}}, w: {oldId: [0, .1], turnCut: [.05, .18]}},
 {t: 'Вывод в файл', say: 'А фоновое задание пишет вывод и код завершения в файл.',
  set: {turnLayer: {opacity: 0}, fileLayer: {opacity: 1}, fileBox: {opacity: 1}, toFile: {opacity: 1}},
  w: {turnLayer: [0, .08], fileLayer: [.06, .16], fileBox: [.35, .5], toFile: [.4, .55]}},
 {t: 'Подхват', say: 'Перезапуск его не трогает: новый процесс дожидается конца и отдаёт результат агенту.',
  set: {oldProc: {opacity: .35}, oldX: {opacity: 1}, newProc: {opacity: 1}, readFile: {opacity: 1}, fileRes: {opacity: 1}},
  w: {oldProc: [.05, .2], oldX: [.05, .2], newProc: [.35, .5], readFile: [.5, .62], fileRes: [.7, .85]}},
 {t: 'Проверка', say: 'Проверка в тот же день: пауза сорок секунд, поднято двадцать пять фоновых заданий, два бежали прямо во время перезапуска.',
  sub: 'Проверка в тот же день: пауза 40 с, поднято 25 фоновых заданий, 2 бежали прямо во время перезапуска.',
  set: {fileLayer: {opacity: 0}, numLayer: {opacity: 1}, n0: {opacity: 1}, n1: {opacity: 1}, n2: {opacity: 1}},
  w: {fileLayer: [0, .06], numLayer: [.04, .1], n0: [.15, .25], n1: [.38, .48], n2: [.68, .78]}},
 {t: 'Результат', say: 'Одно через шестнадцать минут принесло итог: двести двадцать восемь тестов прошли. Второе честно вернуло свою ошибку.',
  sub: 'Одно через 16 минут принесло итог: 228 тестов прошли. Второе честно вернуло свою ошибку.',
  set: {res2: {opacity: 1}}, w: {res2: [.72, .86]}},
 {t: 'Минус', say: 'Честный минус: команды, которые агент запускает внутри хода, обрываются. Он узнаёт об этом из напоминания.',
  set: {numLayer: {opacity: 0}, consLayer: {opacity: 1}, con1: {opacity: 1}, con1b: {opacity: 1}},
  w: {numLayer: [0, .08], consLayer: [.05, .12], con1: [.1, .22], con1b: [.6, .72]}},
 {t: 'Пауза', say: 'И на время перезапуска агенты ждут.',
  set: {con2: {opacity: 1}, con2b: {opacity: 1}}, w: {con2: [.05, .2], con2b: [.5, .65]}},
 {t: 'Итог', say: 'Перезапуск теперь просто пауза, а не потеря работы.', hold: 1.6,
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
  // схема платформы и агентов: шаги 1–2
  const ag = Paper.fade(t, st[1] - .15) - Paper.fade(t, st[2], .3);
  $('agentsLayer').setAttribute('opacity', Math.max(0, ag).toFixed(3));
  Paper.type($('manual'), 'оркестратор → пересылает задания вручную', t, st[4] + .2, st[4] + STEPS[4].d * .75, {cursor: t < st[5]});
  // полоса прогона растёт до рестарта (середина полосы) и встаёт
  const s5 = st[5], d5 = STEPS[5].d;
  $('jobBar').setAttribute('width', (470 * Math.min(1, Math.max(0, (t - s5 - d5 * .2) / (d5 * .55)))).toFixed(1));
  Paper.type($('jobMsg'), '[Background job INTERRUPTED]', t, st[6] + .1, st[6] + STEPS[6].d * .45, {cursor: t < st[7]});
  Paper.type($('resume'), '«продолжай с места остановки»', t, st[8] + STEPS[8].d * .6, st[8] + STEPS[8].d * .95, {cursor: t < st[9]});
  Paper.type($('res1'), '✓ Ran 228 tests … OK', t, st[12] + STEPS[12].d * .3, st[12] + STEPS[12].d * .55, {cursor: false});
  // концовка: утренняя сцена проявляется кистью, камера отъезжает от ноутбука с итогом
  $('roomEnd').setAttribute('opacity', t >= st[last] ? 1 : 0);
  Paper.brush(END, t, st[last], 1.2); Paper.live(END, t);
  const dl = STEPS[last].d;
  Paper.camera(END, st[last] + dl - (t - st[last]), {...VEND, t0: st[last] + .2 * dl, t1: st[last] + .75 * dl});
}
"""

html = re.sub(r'<div class="stg"><svg id="stage".*?</svg></div>', lambda _: f'<div class="stg">{SVG}</div>', tpl, count=1, flags=re.S)
html = re.sub(r"const STEPS = \[.*?\];\n", lambda _: JS.lstrip("\n"), html, count=1, flags=re.S)
html = html.replace("<title>Title</title>", "<title>Рестарт без потерь — V-937</title>", 1)
sys.stdout.write(html)
