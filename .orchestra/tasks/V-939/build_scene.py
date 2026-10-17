"""V-939: ролик «когда серверу не хватает памяти» (V-921, V-924) в стиле «бумага».

Открытие — сцена cafe (инцидент случился утром, 09:20–09:46 CEST), концовка — board.
Числа: дампы ядра V-921/logs/kernel-oom-*.txt (RAM 6291320 страниц = 24 ГиБ, своп 16 ГиБ,
ffmpeg oom_score_adj 0, Orchestra 800, первый дамп: ffmpeg 7.47/3.91/3.86/2.03 ГиБ RSS,
крупнейший 7.47 + 2.16 своп = 9.6), cgroup agents 14 ГиБ / своп 1 ГиБ из 16 ГиБ сервиса,
V-924 (1000 для агентов, ssh без choom блокируется), живая проверка 17.10.
Очки ядра: badness = память + oom_score_adj/1000 · (RAM + своп); шкала 13 px на ГиБ.
Запуск: python3 build_scene.py <путь к animation.md> > scene.html
"""
import re
import sys
from pathlib import Path

md = Path(sys.argv[1]).read_text()
tpl = re.search(r"```html motion-template\n(.*?)```", md, re.S).group(1)

PX = 980 / 24  # ширина полосы ОЗУ: 980 единиц = 24 ГиБ
SEGS = "".join(
    f'<rect id="ff{k}" x="{150 + sum(v * PX for v in (7.47, 3.91, 3.86, 2.03)[:k]):.1f}" y="100" width="0" '
    f'height="100" fill="#fde4d0" stroke="#c9551b" stroke-width="2"/>'
    for k in range(4))
SWAP_W = round(16 * PX)
S = 13  # очки: единиц на ГиБ
ROWS = [("R", 210, "рендер · 9,6 ГБ", 9.6), ("O", 300, "Orchestra · 0,5 ГБ", 0.53), ("A", 390, "агент · 0,3 ГБ", 0.33)]
SCORE_ROWS = "".join(
    f'<g id="row{k}" opacity="{0 if k == "A" else 1}">'
    f'<text x="110" y="{y + 38}" font-size="28">{label}</text>'
    f'<rect x="400" y="{y}" width="{max(3, round(m * S))}" height="56" rx="4" fill="#9aa1ad"/>'
    f'<rect id="adj{k}" x="{400 + max(3, round(m * S))}" y="{y}" width="{416 if k == "A" else 0}" height="56" rx="4" '
    f'fill="#fde4d0" stroke="#c9551b" stroke-width="2"/>'
    f'<text id="adjT{k}" x="{400 + max(3, round(m * S)) + 14}" y="{y + 39}" font-size="28" class="mono" fill="#c9551b" opacity="0">'
    f'{"800" if k != "R" else "0"}</text></g>'
    for k, y, label, m in ROWS)

SVG = f"""<svg id="stage" viewBox="0 0 1280 590" role="img" aria-labelledby="st"><title id="st">Нехватка памяти: кого убивает ядро</title>
<g id="room"></g>
<g id="roomEnd" opacity="0"></g>
<g id="memLayer" opacity="0">
 <g id="mem">
  <rect x="120" y="20" width="1040" height="460" rx="16" fill="#fff" stroke="#d9dce3" stroke-width="2"/>
  <text x="150" y="80" font-size="30" fill="#6b7280">память сервера · 24 ГБ</text>
  <rect x="150" y="100" width="980" height="100" rx="6" fill="#eef0f3"/>
  {SEGS}
  <text id="ffT" x="150" y="262" font-size="30" fill="#c9551b" opacity="0">4 видеорендера ffmpeg:</text>
  <text id="ffN" x="525" y="264" font-size="40" class="mono" fill="#c9551b"></text>
  <text x="150" y="350" font-size="30" fill="#6b7280">своп на диске · 16 ГБ</text>
  <rect x="150" y="370" width="{SWAP_W}" height="70" rx="6" fill="#eef0f3"/>
  <rect id="swapF" x="150" y="370" width="0" height="70" rx="6" fill="#fde4d0" stroke="#c9551b" stroke-width="2"/>
  <text id="swapT" x="{150 + SWAP_W + 30}" y="420" font-size="34" class="mono" fill="#c9551b" opacity="0">✗ свободно 0</text>
 </g>
</g>
<g id="scoreLayer" opacity="0">
 <g id="score">
  <text x="640" y="80" text-anchor="middle" font-size="42" font-weight="600">очки = память + надбавка</text>
  <text id="note" x="640" y="140" text-anchor="middle" font-size="30" fill="#c9551b" opacity="0">надбавка 800 = будто съел 80 % всей памяти</text>
  {SCORE_ROWS}
  <text id="vO" x="1060" y="339" font-size="28" fill="#c9551b" opacity="0">✗ убита 3 из 3</text>
  <text id="vA" x="1060" y="429" font-size="28" fill="#c9551b" opacity="0">✗ ещё 4 убиты</text>
  <text id="vR" x="1060" y="249" font-size="28" fill="#0e5e9c" opacity="0">✓ первый</text>
 </g>
</g>
<g id="cmdLayer" opacity="0">
 <rect x="110" y="40" width="1060" height="440" rx="16" fill="#fff" stroke="#d9dce3" stroke-width="2"/>
 <text x="150" y="105" font-size="30" fill="#6b7280">запуск в обход — вход на тот же сервер</text>
 <text id="cmd1" x="150" y="195" font-size="32" class="mono"></text>
 <text id="no1" x="150" y="255" font-size="30" fill="#c9551b" opacity="0">✗ отклонено: нет пометки «убивать первым»</text>
 <text id="cmd2" x="150" y="360" font-size="32" class="mono" fill="#0e5e9c"></text>
 <text id="ok2" x="150" y="420" font-size="30" fill="#0e5e9c" opacity="0">✓ пропущено: надбавка 1000</text>
</g>
<g id="groupLayer" opacity="0">
 <rect x="110" y="30" width="1060" height="450" rx="16" fill="#fff" stroke="#d9dce3" stroke-width="2"/>
 <text x="150" y="88" font-size="30" fill="#6b7280">Orchestra на сервере · потолок 16 ГБ</text>
 <rect id="agBox" x="150" y="120" width="660" height="320" rx="14" fill="#d6e8f4" stroke="#0e5e9c" stroke-width="2" opacity="0"/>
 <g id="agTxt" opacity="0">
  <text x="190" y="185" font-size="36" font-weight="600" fill="#0e5e9c">агенты</text>
  <text x="190" y="265" font-size="36" class="mono">память ≤ 14 ГБ</text>
  <text x="190" y="335" font-size="36" class="mono">своп   ≤ 1 ГБ</text>
  <text x="190" y="405" font-size="30" fill="#6b7280">надбавка 1000</text>
 </g>
 <rect x="840" y="120" width="290" height="320" rx="14" fill="#eef0f3"/>
 <text x="985" y="185" text-anchor="middle" font-size="32" font-weight="600">платформа</text>
 <text x="985" y="275" text-anchor="middle" font-size="30" fill="#6b7280">надбавка</text>
 <text x="985" y="330" text-anchor="middle" font-size="40" class="mono">800</text>
</g>
<g id="liveLayer" opacity="0">
 <rect x="190" y="50" width="900" height="400" rx="16" fill="#fff" stroke="#d9dce3" stroke-width="2"/>
 <text x="240" y="115" font-size="30" fill="#6b7280">живая проверка 17.10 · новый процесс агента</text>
 <text id="lv1" x="240" y="215" font-size="36" class="mono"></text>
 <text id="lv2" x="240" y="295" font-size="36" class="mono"></text>
 <text id="lv3" x="240" y="390" font-size="30" class="mono" fill="#6b7280"></text>
</g>
<g id="minusLayer" opacity="0">
 <text x="130" y="110" font-size="34" font-weight="600">честный минус</text>
 <text id="m1" x="130" y="200" font-size="32" fill="#c9551b" opacity="0">✗ под нож идёт работа агента:</text>
 <text id="m1b" x="172" y="250" font-size="32" fill="#c9551b" opacity="0">рендер придётся запускать заново</text>
 <text id="m2" x="130" y="350" font-size="32" fill="#c9551b" opacity="0">✗ запуск в обход помечен, но не ограничен:</text>
 <text id="m2b" x="172" y="400" font-size="32" fill="#c9551b" opacity="0">память всё ещё может кончиться</text>
</g>
</svg>"""

JS = r"""
Paper.install();
const BOX = {x: 96, y: 18, w: 1088, h: 556};
const PIC = Paper.picture('room', BOX, {scene: 'cafe'});
const VIEW = Paper.view('cafe', {to: [640, 250], width: 1100});
const MINI = Paper.mini(PIC, 'mem', VIEW);
MINI.setAttribute('opacity', 0);
const END = Paper.picture('roomEnd', BOX, {scene: 'board'});
Paper.mini(END, 'score', Paper.view('board', {to: [640, 250], width: 1100}));
const FF = [7.47, 3.91, 3.86, 2.03], PX = 980 / 24;
const STEPS = [
 {t: 'Утро 17 октября', say: 'Семнадцатое октября, утро. За двадцать шесть минут сервер трижды остался без памяти.',
  sub: '17 октября, утро. За 26 минут сервер трижды остался без памяти.'},
 {t: 'Рендеры', say: 'Её съели видеорендеры агентов: четыре процесса, семнадцать гигабайт из двадцати четырёх.',
  sub: 'Её съели видеорендеры агентов: четыре процесса ffmpeg, 17,3 ГБ из 24.',
  set: Object.fromEntries(FF.map((v, k) => ['ff' + k, {width: +(v * PX).toFixed(1)}]).concat([['ffT', {opacity: 1}]])),
  w: {ff0: [.2, .4], ff1: [.35, .5], ff2: [.45, .6], ff3: [.55, .7], ffT: [.2, .3]}},
 {t: 'Своп', say: 'Своп на диске, шестнадцать гигабайт, тоже кончился.', sub: 'Своп на диске, 16 ГБ, тоже кончился.',
  set: {swapF: {width: %SWAP_W%}, swapT: {opacity: 1}}, w: {swapF: [.1, .7], swapT: [.7, .85]}},
 {t: 'Очки', say: 'Тогда ядро убивает процесс с наибольшими очками: это его память плюс надбавка.',
  set: {scoreLayer: {opacity: 1}}, w: {scoreLayer: [.08, .2]}},
 {t: 'Надбавка', say: 'Надбавка восемьсот, это как будто процесс съел восемьдесят процентов всей памяти.',
  sub: 'Надбавка 800 — как будто процесс съел 80 % всей памяти.',
  set: {note: {opacity: 1}, adjO: {width: 416}}, w: {note: [.05, .2], adjO: [.4, .8]}},
 {t: 'Кто первый', say: 'У рендеров надбавка ноль, а у Оркестры восемьсот. И три раза из трёх первой погибала платформа.',
  sub: 'У рендеров надбавка 0, а у Orchestra — 800. И три раза из трёх первой погибала платформа.',
  set: {adjTR: {opacity: 1}, adjTO: {opacity: 1}, vO: {opacity: 1}}, w: {adjTR: [.1, .2], adjTO: [.3, .4], vO: [.65, .8]}},
 {t: 'Агенты', say: 'Во второй раз ядро убило и четыре процесса агентов, а рендеры жили дальше.',
  sub: 'Во второй раз ядро убило и 4 процесса агентов, а рендеры жили дальше.',
  set: {rowA: {opacity: 1}, adjTA: {opacity: 1}, vA: {opacity: 1}}, w: {rowA: [.1, .25], adjTA: [.1, .25], vA: [.3, .5]}},
 {t: 'Теперь', say: 'Теперь каждый процесс агента до запуска получает надбавку тысяча, максимум.',
  sub: 'Теперь каждый процесс агента до запуска получает надбавку 1000 — максимум.',
  set: {note: {opacity: 0}, vO: {opacity: 0}, vA: {opacity: 0}, adjA: {width: 520}, adjTA: {text: '1000'}},
  w: {note: [0, .1], vO: [0, .1], vA: [0, .1], adjA: [.4, .75], adjTA: [.6, .7]}},
 {t: 'В обход', say: 'Рендеры шли в обход, через вход на тот же сервер. Без пометки «убивать первым» платформа такую команду отклоняет.',
  sub: 'Рендеры шли в обход, через ssh на тот же сервер. Без пометки «убивать первым» платформа такую команду отклоняет.',
  set: {scoreLayer: {opacity: 0}, cmdLayer: {opacity: 1}, no1: {opacity: 1}, ok2: {opacity: 1}},
  w: {scoreLayer: [0, .06], cmdLayer: [.04, .12], no1: [.62, .7], ok2: [.92, .98]}},
 {t: 'Рендер первым', say: 'Так у рендера тоже тысяча плюс память, и первым под нож идёт он.',
  sub: 'Так у рендера тоже 1000 плюс память, и первым под нож идёт он.',
  set: {cmdLayer: {opacity: 0}, scoreLayer: {opacity: 1}, adjR: {width: 520}, adjTR: {text: '1000'}, vR: {opacity: 1}},
  w: {cmdLayer: [0, .08], scoreLayer: [.06, .14], adjR: [.15, .5], adjTR: [.35, .45], vR: [.7, .85]}},
 {t: 'Своя группа', say: 'А агенты сидят в своей группе: четырнадцать гигабайт памяти и один гигабайт свопа.',
  sub: 'А агенты сидят в своей группе: 14 ГБ памяти и 1 ГБ свопа.',
  set: {scoreLayer: {opacity: 0}, groupLayer: {opacity: 1}, agBox: {opacity: 1}, agTxt: {opacity: 1}},
  w: {scoreLayer: [0, .08], groupLayer: [.06, .14], agBox: [.25, .4], agTxt: [.35, .5]}},
 {t: 'Проверка', say: 'Живая проверка: у нового процесса агента надбавка тысяча, и сидит он в группе агентов.',
  sub: 'Живая проверка 17.10: у нового процесса агента надбавка 1000, и сидит он в группе agents/workers.',
  set: {groupLayer: {opacity: 0}, liveLayer: {opacity: 1}}, w: {groupLayer: [0, .08], liveLayer: [.06, .14]}},
 {t: 'Минус', say: 'Честный минус: под нож теперь идёт работа агента, и рендер придётся запускать заново.',
  set: {liveLayer: {opacity: 0}, minusLayer: {opacity: 1}, m1: {opacity: 1}, m1b: {opacity: 1}},
  w: {liveLayer: [0, .08], minusLayer: [.06, .14], m1: [.2, .3], m1b: [.55, .65]}},
 {t: 'Не предел', say: 'А запуск в обход только помечен, но не ограничен: память всё ещё может кончиться.',
  set: {m2: {opacity: 1}, m2b: {opacity: 1}}, w: {m2: [.05, .15], m2b: [.55, .65]}},
 {t: 'Итог', say: 'Зато первым теперь падает рендер, а не сама Оркестра.', sub: 'Зато первым теперь падает рендер, а не сама Orchestra.',
  hold: 1.4, set: {minusLayer: {opacity: 0}}, w: {minusLayer: [0, .15]}},
];
STEPS.forEach(s => s.x ??= s.sub ?? s.say); window.voice?.(STEPS);
STEPS.forEach(s => s.d ??= Math.max(3, s.say.length / 14));  // браузерный просмотр без озвучки
function draw(i, p, t) {
  const st = []; let at = 0; for (const s of STEPS) { st.push(at); at += s.d; }
  const last = st.length - 1, d0 = STEPS[0].d;
  Paper.brush(PIC, t, 0, 1.2); Paper.live(PIC, t);
  Paper.camera(PIC, t, {...VIEW, t0: .4 * d0, t1: st[1] - .15});
  MINI.setAttribute('opacity', Paper.fade(t, .25 * d0, .4).toFixed(3));
  $('room').setAttribute('opacity', (1 - Paper.fade(t, st[1] - .1)).toFixed(3));
  $('memLayer').setAttribute('opacity', (Paper.fade(t, st[1] - .15) - Paper.fade(t, st[3], .3)).toFixed(3));
  $('roomEnd').setAttribute('opacity', t >= st[last] ? 1 : 0);
  Paper.brush(END, t, st[last], 1.4); Paper.live(END, t);
  // счётчик идёт по реальным размерам четырёх процессов
  const s1 = st[1], d1 = STEPS[1].d, q = Math.min(1, Math.max(0, (t - s1 - .2 * d1) / (.5 * d1)));
  $('ffN').textContent = t < s1 + .2 * d1 ? '' : (FF.reduce((a, b) => a + b) * q).toFixed(1).replace('.', ',') + ' ГБ';
  const s8 = st[8], d8 = STEPS[8].d;
  Paper.type($('cmd1'), "ssh kesha@localhost 'ffmpeg …'", t, s8 + .14 * d8, s8 + .4 * d8, {cursor: false});
  Paper.type($('cmd2'), "ssh kesha@localhost 'choom -n 1000 -- ffmpeg …'", t, s8 + .7 * d8, s8 + .92 * d8, {cursor: t < st[9]});
  const s11 = st[11], d11 = STEPS[11].d;
  Paper.type($('lv1'), 'oom_score_adj   1000  ✓', t, s11 + .15 * d11, s11 + .45 * d11, {cursor: false});
  Paper.type($('lv2'), 'группа   agents/workers  ✓', t, s11 + .55 * d11, s11 + .85 * d11, {cursor: false});
  Paper.type($('lv3'), 'платформа         800', t, s11 + .86 * d11, s11 + .98 * d11, {cursor: t < st[12]});
}
""".replace("%SWAP_W%", str(SWAP_W))

html = re.sub(r'<div class="stg"><svg id="stage".*?</svg></div>', lambda _: f'<div class="stg">{SVG}</div>', tpl, count=1, flags=re.S)
html = re.sub(r"const STEPS = \[.*?\];\n", lambda _: JS.lstrip("\n"), html, count=1, flags=re.S)
html = html.replace("<title>Title</title>", "<title>Нехватка памяти — V-939</title>", 1)
sys.stdout.write(html)
