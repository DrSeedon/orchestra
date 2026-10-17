"""Собирает demo/scene.html: стандартный каркас плеера из html-artifacts + сцена V-904.

Каркас берётся из скилла без правок; меняются только CSS-дополнение, SVG и STEPS/draw.
Запуск: python3 build_scene.py <путь к animation.md> > scene.html
"""
import re
import sys
from pathlib import Path

md = Path(sys.argv[1]).read_text()
tpl = re.search(r"```html motion-template\n(.*?)```", md, re.S).group(1)

# Палитра снята пипеткой с кадров ролика NIST (report.md, «Палитра»).
CSS = """
/* V-904: светлая «бумажная» тема поверх video.css (тот грузится позже, поэтому !important) */
html,body{background:#f6f7f9!important;color:#16171b!important}
:root{color-scheme:light!important}
.mv{background:#f6f7f9!important;padding:18px 0 0!important}
.mv h1{display:none!important}
#stage{fill:#16171b!important}
.cap{margin:0 56px!important;min-height:0!important;height:92px;border-top:1px solid #e3e5e9;
 display:flex;align-items:center;justify-content:center;text-align:center;
 font-size:23px!important;line-height:1.3!important;color:#1d1e20!important;font-weight:500}
.cap b{display:none!important}#capA,#capB{width:100%}#capB{top:22px!important}
#prog{position:fixed;left:0;bottom:0;height:3px;background:#cdd0d9;width:0}
.mono{font-family:'JetBrains Mono',ui-monospace,monospace}
"""

SVG = r"""<svg id="stage" viewBox="0 0 1280 590" role="img" aria-labelledby="st"><title id="st">Сверка AGENTS.md и CLAUDE.md</title>
<defs>
 <filter id="torn" x="-5%" y="-5%" width="110%" height="110%"><feTurbulence type="fractalNoise" baseFrequency="0.035" numOctaves="3" seed="7"/><feDisplacementMap in="SourceGraphic" scale="22"/></filter>
 <filter id="bristle" x="-10%" y="-30%" width="120%" height="160%"><feTurbulence type="fractalNoise" baseFrequency="0.02 0.25" numOctaves="2" seed="3"/><feDisplacementMap in="SourceGraphic" scale="70"/></filter>
 <filter id="wobble"><feTurbulence type="fractalNoise" baseFrequency="0.018" numOctaves="2" seed="11"/><feDisplacementMap in="SourceGraphic" scale="5"/></filter>
 <filter id="grain"><feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves="2" seed="5"/><feColorMatrix type="saturate" values="0"/><feComponentTransfer><feFuncA type="table" tableValues="0 .55"/></feComponentTransfer></filter>
 <mask id="mTorn"><rect x="96" y="18" width="1088" height="556" fill="#fff" filter="url(#torn)"/></mask>
 <mask id="mBrush"><g filter="url(#bristle)"><path id="brush" d="M40 70H1240M1240 70L40 190H1240L40 310H1240L40 430H1240L40 560H1240" fill="none" stroke="#fff" stroke-width="170" stroke-linejoin="round"/></g></mask>
 <linearGradient id="wall" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#232b52"/><stop offset="1" stop-color="#1a2040"/></linearGradient>
 <radialGradient id="glow" cx=".5" cy=".5" r=".5"><stop offset="0" stop-color="#f3d99c" stop-opacity=".55"/><stop offset="1" stop-color="#f3d99c" stop-opacity="0"/></radialGradient>
 <radialGradient id="vig" cx=".5" cy=".45" r=".75"><stop offset=".55" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".55"/></radialGradient>
 <radialGradient id="scr" cx=".45" cy=".4" r=".8"><stop offset="0" stop-color="#fbeec0"/><stop offset="1" stop-color="#e6cf8a"/></radialGradient>
 <marker id="ar" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L10 5L0 10z" fill="#0e5e9c"/></marker>
</defs>

<!-- ИЛЛЮСТРАЦИЯ: ночная комната, рваный край, проявление мазками кисти, наезд камеры в монитор -->
<g id="room" mask="url(#mBrush)"><g mask="url(#mTorn)"><g id="cam" filter="url(#wobble)">
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
 <g id="mini" opacity="0"><use href="#cards" transform="translate(640 252) scale(0.238095) translate(-640 -170)"/></g>
 <path d="M990 352L1002 300L968 278" fill="none" stroke="#3a2a22" stroke-width="7" stroke-linecap="round"/>
 <path d="M940 290Q955 255 990 262L978 300Z" fill="#c9551b"/><ellipse cx="992" cy="352" rx="26" ry="6" fill="#3a2a22"/>
 <rect x="440" y="290" width="92" height="120" rx="10" fill="#7a2e1f"/><rect x="452" y="410" width="68" height="12" fill="#5d2318"/><rect x="480" y="422" width="10" height="70" fill="#2a2730"/>
 <path d="M440 500H530" stroke="#2a2730" stroke-width="8" stroke-linecap="round"/>
 <rect x="60" y="0" width="1160" height="600" filter="url(#grain)" style="mix-blend-mode:multiply" opacity=".55"/>
 <rect x="60" y="0" width="1160" height="600" fill="url(#vig)"/>
</g></g></g>

<!-- ПЛОСКАЯ СХЕМА: те же две карточки, что в мониторе после наезда (мини-копия — <use> этой группы) -->
<g id="dia" opacity="0" class="mono">
 <g id="cards" class="mono">
 <rect id="aCard" x="240" y="20" width="380" height="300" rx="12" fill="#fff" stroke="#d9dce3" stroke-width="1.5"/>
 <text x="264" y="58" font-size="22" font-weight="500">AGENTS.md</text>
 <g font-size="16" fill="#3b3e46">
  <text x="264" y="102"># Orchestra — правила</text><text x="264" y="132">## Границы полномочий</text>
  <text x="264" y="166">- Рестарт инициирует</text><text x="264" y="192">  только владелец.</text>
  <text x="264" y="226">- Не выкатывай код</text><text x="264" y="252">  самостоятельно.</text></g>
 <rect id="cCard" x="660" y="20" width="380" height="300" rx="12" fill="#fff" stroke="#d9dce3" stroke-width="1.5"/>
 <text id="cName" x="684" y="58" font-size="22" font-weight="500">CLAUDE.md</text>
 <g id="cBody" font-size="16" fill="#3b3e46">
  <rect id="diffBg" x="672" y="206" width="356" height="56" rx="5" fill="#fde4d0" opacity="0"/>
  <text x="684" y="102"># Orchestra — правила</text><text x="684" y="132">## Границы полномочий</text>
  <text x="684" y="166">- Рестарт инициирует</text><text x="684" y="192">  только владелец.</text>
  <text id="cL5" x="684" y="226">- Не выкатывай код</text><text id="cL6" x="684" y="252">  самостоятельно.</text></g>
 </g>
 <text id="link" x="850" y="178" text-anchor="middle" font-size="20" fill="#0e5e9c" opacity="0">CLAUDE.md → AGENTS.md</text>
 <path id="linkArrow" opacity="0" d="M700 150Q665 110 628 128" fill="none" stroke="#0e5e9c" stroke-width="2.5" marker-end="url(#ar)" stroke-dasharray="120" stroke-dashoffset="120"/>
 <g font-family="Manrope,system-ui,sans-serif" font-size="18">
  <rect id="chipA" x="375" y="336" width="110" height="36" rx="18" fill="#eef0f3"/><text x="430" y="360" text-anchor="middle" fill="#3b3e46">Codex</text>
  <rect id="chipC" x="785" y="336" width="130" height="36" rx="18" fill="#eef0f3"/><text id="chipCT" x="850" y="360" text-anchor="middle" fill="#3b3e46">Claude</text>
 </g>
 <g id="bytes" opacity="0"></g>
 <text id="cnt" x="1137" y="508" text-anchor="end" font-size="16" fill="#6b7280" opacity="0">совпало 0 из 16 171 байт</text>
 <g id="out1" opacity="0" font-size="19"><text x="90" y="546" font-family="Manrope,system-ui,sans-serif" fill="#6b7280">совпали</text>
  <text x="230" y="546" fill="#0e5e9c">CLAUDE.md → AGENTS.md  ✓  git commit (локально)</text></g>
 <g id="out2" opacity="0" font-size="19"><text x="90" y="582" font-family="Manrope,system-ui,sans-serif" fill="#6b7280">разошлись</text>
  <text id="out2t" x="230" y="582" fill="#c9551b"></text></g>
</g>
</svg>"""

JS = r"""
// реальные первые 16 байт AGENTS.md («# Orchestra — »), размер файла 16 171 байт (V-904)
const BYTES='23 20 4F 72 63 68 65 73 74 72 61 20 E2 80 94 20'.split(' '), SIZE=16171;
(()=>{const g=$('bytes'),ns='http://www.w3.org/2000/svg',mk=(n,a)=>{const e=document.createElementNS(ns,n);for(const k in a)e.setAttribute(k,a[k]);g.append(e);return e};
 [['AGENTS.md',398],['CLAUDE.md',442]].forEach(([nm,y],r)=>{mk('text',{x:90,y:y+24,'font-size':16,fill:'#6b7280'}).textContent=nm;
  BYTES.forEach((b,k)=>{mk('rect',{id:`b${r}_${k}`,x:230+k*57,y,width:52,height:36,rx:5,fill:'#eef0f3'});
   mk('text',{x:256+k*57,y:y+24,'text-anchor':'middle','font-size':17,fill:'#3b3e46'}).textContent=b})});
 const c=$('calDots');for(let k=0;k<28;k++){const e=document.createElementNS(ns,'rect');Object.entries({x:176+(k%7)*22,y:116+Math.floor(k/7)*22,width:12,height:9,rx:2}).forEach(([a,v])=>e.setAttribute(a,v));c.append(e)}})();
const STEPS = [
 {t:'Два файла', say:'Правила для Кодекса и для Клода лежат в двух файлах.', sub:'Правила для Codex и Claude лежат в двух файлах: AGENTS.md и CLAUDE.md.', set:{mini:{opacity:1}}, w:{mini:[.3,.45]}},
 {t:'Сверка', say:'Чтобы копии не разошлись, раз в шесть часов платформа сравнивает их побайтно.',
  set:{bytes:{opacity:1}, cnt:{opacity:1}},
  w:{bytes:[0,.2], cnt:[0,.2]}},
 {t:'Совпали', say:'Совпали: второй файл становится симл+инком.', sub:'Совпали — второй файл становится симлинком.',
  set:{cBody:{opacity:0}, cCard:{height:56, y:142, stroke:'#9cc3e0'}, cName:{y:180, opacity:0}, link:{opacity:1}, linkArrow:{"stroke-dashoffset":0, opacity:1}, out1:{opacity:1}},
  w:{cBody:[0,.2], cCard:[.1,.45], cName:[.1,.3], link:[.3,.5], linkArrow:[.35,.6], out1:[.55,.75]}},
 {t:'Разошлись', say:'Разошлись: платформа ничего не трогает и зовёт оркестратора.', sub:'Разошлись — платформа ничего не трогает и зовёт оркестратора.', hold:1.0, set:{out2:{opacity:1}}, w:{out2:[0,.1]}},
];
STEPS.forEach(s => s.x ??= s.sub ?? s.say); window.voice?.(STEPS);
STEPS.forEach(s => s.d ??= Math.max(2.5, s.say.length / 14));  // браузерный просмотр без озвучки
const OUT2='ничего не пишем   ✗   тревога оркестратору проекта';
function draw(i, p, t){
 const st=[];let acc=0;for(const s of STEPS){st.push(acc);acc+=s.d}
 const io=EASE.io, d0=STEPS[0].d;
 $('prog').style.width=(t/acc*100).toFixed(3)+'%';
 document.querySelector('.cap').style.filter=`blur(${((1-clamp((t-st[i])/.45))*4).toFixed(2)}px)`;
 // мазки кисти проявляют иллюстрацию за 1,2 с
 const br=$('brush'),L=br.getTotalLength();br.style.strokeDasharray=L;br.style.strokeDashoffset=(L*(1-io(clamp(t/1.2)))).toFixed(1);
 // стрелки часов идут медленно — «живая» иллюстрация
 $('hm').setAttribute('transform',`rotate(${(300+t*9).toFixed(2)} 860 100)`);$('hh').setAttribute('transform',`rotate(${(-40+t*.75).toFixed(2)} 860 100)`);
 // наезд камеры в экран: экран (640,250) → центр карточек (640,190), масштаб 3.6
 const z=io(clamp((t-.5*d0)/(.5*d0-.15))),s=1+3.2*z;  // наезд заканчивается до смены шага, иначе карточки двоятся
 $('cam').setAttribute('transform',`translate(640 ${(252-82*z).toFixed(2)}) scale(${s.toFixed(4)}) translate(-640 -252)`);
 $('room').setAttribute('opacity',(1-io(clamp((t-st[1]+.1)/.45))).toFixed(3));
 $('dia').setAttribute('opacity',io(clamp((t-st[1]+.15)/.45)).toFixed(3));
 // побайтная сверка: курсор идёт по 16 ячейкам, счётчик — по всем 16 171 байтам
 const q=i>=1?clamp((t-st[1]-.35)/(STEPS[1].d*.7)):0,n=Math.floor(q*16+1e-9);
 for(let r=0;r<2;r++)for(let k=0;k<16;k++)$(`b${r}_${k}`).setAttribute('fill',k<n?'#d6e8f4':k==n&&q>0&&q<1?'#c7ccd6':'#eef0f3');
 $('cnt').textContent=`совпало ${Math.round(q*SIZE).toLocaleString('ru-RU')} из ${SIZE.toLocaleString('ru-RU')} байт${q>=1?'  ✓':''}`;
 $('cnt').setAttribute('fill',q>=1?'#0e5e9c':'#6b7280');
 // печать с блочным курсором
 const ty=i>=3?clamp((t-st[3]-.15)/(STEPS[3].d*.55)):0,m=Math.round(ty*OUT2.length),blink=Math.floor(t*2.2)%2==0;
 $('out2t').textContent=OUT2.slice(0,m)+(i>=3&&(ty<1||blink)?'▌':'');
}
"""

html = tpl.replace("</style>", CSS + "</style>", 1)
html = re.sub(r'<div class="stg"><svg id="stage".*?</svg></div>', lambda _: f'<div class="stg">{SVG}</div>', html, count=1, flags=re.S)
html = re.sub(r"const STEPS = \[.*?\];\n", lambda _: JS.lstrip("\n"), html, count=1, flags=re.S)
html = html.replace('<ol class="ch" id="chap"></ol>', '<ol class="ch" id="chap"></ol><div id="prog"></div>', 1)
html = html.replace("<title>Title</title>", "<title>V-904 демо: сверка AGENTS.md и CLAUDE.md</title>", 1)
assert JS.strip()[:20] in html and "id=\"room\"" in html
sys.stdout.write(html)
