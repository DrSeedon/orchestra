"""V-917: демо стиля «бумага» штатным инструментом — тема и комплект paper.js из make.py, без своих CSS-перебивок.

Та же сцена, что V-904/demo-v2 (сверка AGENTS.md/CLAUDE.md), но рамка, кисть, камера, печать,
полоса прогресса и размытие субтитра идут из scripts/video_artifact/paper.js и video-paper.css.
Запуск: python3 build_scene.py <путь к animation.md> > scene.html
"""
import re
import sys
from pathlib import Path

md = Path(sys.argv[1]).read_text()
tpl = re.search(r"```html motion-template\n(.*?)```", md, re.S).group(1)

BARS = "".join(f'<rect x="{x0 + 32}" y="{y}" width="{w}" height="12" rx="6"/>'
               for x0 in (240, 660) for y, w in ((118, 250), (150, 300), (182, 210), (214, 270), (246, 160)))

SVG = f"""<svg id="stage" viewBox="0 0 1280 590" role="img" aria-labelledby="st"><title id="st">Сверка AGENTS.md и CLAUDE.md</title>
<defs>
 <linearGradient id="wall" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#232b52"/><stop offset="1" stop-color="#1a2040"/></linearGradient>
 <radialGradient id="glow" cx=".5" cy=".5" r=".5"><stop offset="0" stop-color="#f3d99c" stop-opacity=".55"/><stop offset="1" stop-color="#f3d99c" stop-opacity="0"/></radialGradient>
 <radialGradient id="scr" cx=".45" cy=".4" r=".8"><stop offset="0" stop-color="#fbeec0"/><stop offset="1" stop-color="#e6cf8a"/></radialGradient>
</defs>
<!-- картина: ночная комната; рамку, зерно, виньетку и маску кисти добавляет Paper.picture -->
<g id="room">
 <rect x="60" y="0" width="1160" height="600" fill="url(#wall)"/>
 <rect x="60" y="405" width="1160" height="200" fill="#151a31"/>
 <ellipse cx="640" cy="270" rx="430" ry="250" fill="url(#glow)"/>
 <g><rect x="955" y="68" width="160" height="190" fill="#10152e" stroke="#46507c" stroke-width="7"/><path d="M1035 68V258M955 163H1115" stroke="#46507c" stroke-width="6"/>
  <circle cx="1072" cy="112" r="22" fill="#e7e1c8"/><circle cx="1065" cy="106" r="4" fill="#cfc8ad"/><circle cx="1080" cy="119" r="3" fill="#cfc8ad"/>
  <circle cx="985" cy="98" r="2" fill="#cfd5ea"/><circle cx="1000" cy="215" r="2" fill="#cfd5ea"/><circle cx="1090" cy="200" r="2" fill="#cfd5ea"/></g>
 <g><circle cx="860" cy="100" r="36" fill="#e9e5d8" stroke="#2b2b30" stroke-width="6"/>
  <line id="hh" x1="860" y1="100" x2="860" y2="80" stroke="#222" stroke-width="5" stroke-linecap="round"/>
  <line id="hm" x1="860" y1="100" x2="860" y2="72" stroke="#222" stroke-width="3" stroke-linecap="round"/></g>
 <g><rect x="165" y="70" width="170" height="135" rx="4" fill="#d9d4c6"/><rect x="165" y="70" width="170" height="34" rx="4" fill="#8f3b26"/>
  <text x="250" y="93" text-anchor="middle" font-size="17" font-weight="700" fill="#f5efe4">Октябрь 2026</text>
  <g fill="#7d7a73" id="calDots"></g><circle cx="281" cy="165" r="11" fill="none" stroke="#c9551b" stroke-width="3"/></g>
 <path d="M400 385L440 352H900L940 385Z" fill="#6b3324"/><rect x="400" y="385" width="540" height="16" fill="#4e2419"/>
 <rect x="418" y="401" width="16" height="140" fill="#43201a"/><rect x="906" y="401" width="16" height="140" fill="#43201a"/>
 <rect x="518" y="186" width="244" height="134" rx="14" fill="#d8cfb5" stroke="#9a8f74" stroke-width="2"/>
 <rect x="530" y="198" width="220" height="108" rx="8" fill="url(#scr)"/>
 <rect x="612" y="320" width="56" height="22" fill="#bdb398"/><rect x="588" y="342" width="104" height="10" rx="3" fill="#a99f84"/>
 <circle cx="752" cy="312" r="2.5" fill="#6fbf73"/>
 <g id="mini" opacity="0"><use id="miniUse" href="#cards"/></g>
 <path d="M990 352L1002 300L968 278" fill="none" stroke="#3a2a22" stroke-width="7" stroke-linecap="round"/>
 <path d="M940 290Q955 255 990 262L978 300Z" fill="#c9551b"/><ellipse cx="992" cy="352" rx="26" ry="6" fill="#3a2a22"/>
 <rect x="440" y="290" width="92" height="120" rx="10" fill="#7a2e1f"/><rect x="452" y="410" width="68" height="12" fill="#5d2318"/><rect x="480" y="422" width="10" height="70" fill="#2a2730"/>
 <path d="M440 500H530" stroke="#2a2730" stroke-width="8" stroke-linecap="round"/>
</g>
<g id="dia" opacity="0" class="mono">
 <g id="cards" class="mono">
  <rect id="aCard" x="240" y="20" width="380" height="300" rx="14" fill="#fff" stroke="#d9dce3" stroke-width="2"/>
  <rect id="cCard" x="660" y="20" width="380" height="300" rx="14" fill="#fff" stroke="#d9dce3" stroke-width="2"/>
  <g id="bars" fill="#dfe2e8">{BARS}</g>
  <text id="aName" x="272" y="86" font-size="40" font-weight="500">AGENTS.md</text>
  <text id="cName" x="692" y="86" font-size="40" font-weight="500">CLAUDE.md</text>
 </g>
 <g id="chips" font-family="Manrope,system-ui,sans-serif" font-size="30" text-anchor="middle" fill="#6b7280">
  <text x="430" y="378">Codex</text><text x="850" y="378">Claude</text></g>
 <g id="rowA" opacity="0"></g><g id="rowC" opacity="0"></g>
 <path id="linkArrow" opacity="0" d="M108 292Q62 252 104 212" fill="none" stroke="#0e5e9c" stroke-width="3.5" marker-end="url(#paper-arrow)" stroke-dasharray="140" stroke-dashoffset="140"/>
 <text id="cnt" x="1080" y="440" text-anchor="end" font-size="34" fill="#6b7280" opacity="0">0 из 16 171 байт</text>
 <text id="ok" x="200" y="440" font-size="34" fill="#0e5e9c" opacity="0">✓ симлинк + git commit</text>
 <text id="alarm" x="200" y="440" font-size="34" fill="#c9551b"></text>
</g>
</svg>"""

JS = r"""
// картина и совпадение наезда: копия карточек в мониторе — обратная проекция камеры
Paper.install();
const PIC = Paper.picture('room', {x: 96, y: 18, w: 1088, h: 556});
const VIEW = {from: [640, 252], to: [640, 170], scale: 4.2};
$('miniUse').setAttribute('transform', Paper.miniature(VIEW));
// первые 8 байт AGENTS.md: «# Orches»; размер файла 16 171 байт
const BYTES='23 20 4F 72 63 68 65 73'.split(' '), SIZE=16171, X0=400, STEP=86;
(()=>{const ns='http://www.w3.org/2000/svg',mk=(g,n,a)=>{const e=document.createElementNS(ns,n);for(const k in a)e.setAttribute(k,a[k]);g.append(e);return e};
 [['rowA',172],['rowC',262]].forEach(([id,y],r)=>{const g=$(id);BYTES.forEach((b,k)=>{
  mk(g,'rect',{id:`b${r}_${k}`,x:X0+k*STEP,y,width:76,height:60,rx:8,fill:'#eef0f3'});
  const t=mk(g,'text',{id:`t${r}_${k}`,x:X0+38+k*STEP,y:y+43,'text-anchor':'middle','font-size':36,fill:'#3b3e46'});t.textContent=b})});
 const c=$('calDots');for(let k=0;k<28;k++){const e=document.createElementNS(ns,'rect');Object.entries({x:176+(k%7)*22,y:116+Math.floor(k/7)*22,width:12,height:9,rx:2}).forEach(([a,v])=>e.setAttribute(a,v));c.append(e)}})();
const STEPS = [
 {t:'Два файла', say:'Правила для Кодекса и для Клода лежат в двух файлах.', sub:'Правила для Codex и Claude лежат в двух файлах: AGENTS.md и CLAUDE.md.', set:{mini:{opacity:1}}, w:{mini:[.25,.4]}},
 // карточки сворачиваются в подписи строк байтов: имена файлов переезжают и уменьшаются
 {t:'Сверка', say:'Чтобы копии не разошлись, раз в шесть часов платформа сравнивает их побайтно.',
  set:{aCard:{opacity:0}, cCard:{opacity:0}, bars:{opacity:0}, chips:{opacity:0},
       aName:{x:120, y:214, 'font-size':32}, cName:{x:120, y:304, 'font-size':32}, rowA:{opacity:1}, rowC:{opacity:1}, cnt:{opacity:1}},
  w:{aCard:[.2,.32], cCard:[.2,.32], bars:[.2,.3], chips:[.2,.3], aName:[.22,.42], cName:[.22,.42], rowA:[.38,.48], rowC:[.38,.48], cnt:[.45,.52]}},
 {t:'Совпали', say:'Совпали: второй файл становится симл+инком.', sub:'Совпали — второй файл становится симлинком.',
  set:{rowC:{opacity:0}, cnt:{opacity:0}, cName:{text:'CLAUDE.md → AGENTS.md', fill:'#0e5e9c'}, linkArrow:{'stroke-dashoffset':0, opacity:1}, ok:{opacity:1}},
  w:{rowC:[0,.15], cnt:[0,.15], cName:[.15,.35], linkArrow:[.3,.55], ok:[.5,.7]}},
 {t:'Разошлись', say:'Разошлись: платформа ничего не трогает и зовёт оркестратора.', sub:'Разошлись — платформа ничего не трогает и зовёт оркестратора.', hold:1.0,
  set:{ok:{opacity:0}, linkArrow:{opacity:0}, cName:{text:'CLAUDE.md', fill:'#16171b'}, rowC:{opacity:1}},
  w:{ok:[0,.1], linkArrow:[0,.1], cName:[0,.15], rowC:[.05,.2]},
  events:[{id:'key1', at:.55, sound:'key/fs-194795-vintage-keyboard-1-1', weight:'support', visual:'appear'},
          {id:'key2', at:1.35, sound:'key/fs-194795-vintage-keyboard-1-2', weight:'support', visual:'appear'},
          {id:'key3', at:2.15, sound:'key/fs-194796-vintage-keyboard-2-1', weight:'support', visual:'appear'}]},
];
STEPS.forEach(s => s.x ??= s.sub ?? s.say); window.voice?.(STEPS);
STEPS.forEach(s => s.d ??= Math.max(2.5, s.say.length / 15));  // браузерный просмотр без озвучки
const ALARM='≠ ничего не пишем → оркестратору';
function draw(i, p, t){
 const st=[];let acc=0;for(const s of STEPS){st.push(acc);acc+=s.d}
 const d0=STEPS[0].d;
 Paper.brush(PIC, t, 0, 1.2);
 $('hm').setAttribute('transform',`rotate(${(300+t*9).toFixed(2)} 860 100)`);$('hh').setAttribute('transform',`rotate(${(-40+t*.75).toFixed(2)} 860 100)`);
 // наезд: экран (640,252) → центр карточек (640,170); кончается до смены шага
 Paper.camera(PIC, t, {...VIEW, t0: .45*d0, t1: st[1]-.15});
 $('room').setAttribute('opacity',(1-Paper.fade(t, st[1]-.1)).toFixed(3));
 $('dia').setAttribute('opacity',Paper.fade(t, st[1]-.15).toFixed(3));
 // сверка: курсор по 8 ячейкам, счётчик по всем 16 171 байтам
 const q=i>=1?clamp((t-st[1]-.52*STEPS[1].d)/(STEPS[1].d*.4)):0,n=Math.floor(q*8+1e-9);
 const diverged=i>=3;
 for(let r=0;r<2;r++)for(let k=0;k<8;k++){
  const bad=diverged&&r==1&&k==5;
  $(`b${r}_${k}`).setAttribute('fill',bad?'#fde4d0':k<n||diverged?'#d6e8f4':k==n&&q>0?'#c7ccd6':'#eef0f3');
  $(`t${r}_${k}`).setAttribute('fill',bad?'#c9551b':k<n||diverged?'#0e5e9c':'#3b3e46');
  if(r==1&&k==5)$(`t1_5`).textContent=bad?'6F':'68'}
 $('cnt').textContent=`${Math.round(q*SIZE).toLocaleString('ru-RU')} из ${SIZE.toLocaleString('ru-RU')} байт${q>=1?' ✓':''}`;
 $('cnt').setAttribute('fill',q>=1?'#0e5e9c':'#6b7280');
 Paper.type($('alarm'), ALARM, t, st[3]+.4, st[3]+.4+STEPS[3].d*.45);
}
"""

html = re.sub(r'<div class="stg"><svg id="stage".*?</svg></div>', lambda _: f'<div class="stg">{SVG}</div>', tpl, count=1, flags=re.S)
html = re.sub(r"const STEPS = \[.*?\];\n", lambda _: JS.lstrip("\n"), html, count=1, flags=re.S)
html = html.replace("<title>Title</title>", "<title>V-917 демо: сверка AGENTS.md и CLAUDE.md</title>", 1)
sys.stdout.write(html)
