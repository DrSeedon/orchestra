"""V-912: демо v2 — та же тема и озвучка, что в demo/, но в кадре 2–3 объекта и крупный шрифт.

Иллюстрация комнаты и SVG-фильтры берутся из ../demo/build_scene.py без изменений.
Запуск: python3 build_scene_v2.py <путь к animation.md> > scene.html
"""
import re
import sys
from pathlib import Path

md = Path(sys.argv[1]).read_text()
tpl = re.search(r"```html motion-template\n(.*?)```", md, re.S).group(1)
v1 = (Path(__file__).resolve().parent.parent / "demo" / "build_scene.py").read_text()
defs = re.search(r"(<defs>.*?</defs>)", v1, re.S).group(1)
room = re.search(r"(<!-- ИЛЛЮСТРАЦИЯ.*?</g></g></g>)", v1, re.S).group(1)

# Ориентир из ролика NIST: hex-слово ≈60 px на 1080 → 40 единиц сцены (кадр 1920 = 1280 единиц).
CSS = """
html,body{background:#f6f7f9!important;color:#16171b!important}
:root{color-scheme:light!important}
.mv{background:#f6f7f9!important;padding:18px 0 0!important}
.mv h1{display:none!important}
#stage{fill:#16171b!important}
.cap{margin:0 56px!important;min-height:0!important;height:96px;border-top:1px solid #e3e5e9;
 display:flex;align-items:center;justify-content:center;text-align:center;
 font-size:27px!important;line-height:1.25!important;color:#1d1e20!important;font-weight:500}
.cap b{display:none!important}#capA,#capB{width:100%}#capB{top:24px!important}
#prog{position:fixed;left:0;bottom:0;height:3px;background:#cdd0d9;width:0}
.mono{font-family:'JetBrains Mono',ui-monospace,monospace}
"""

# Карточки шага 1: только имя файла и «строки-бруски», как бруски кода в их терминале.
# Их мини-копия в мониторе — <use> этой группы с обратной проекцией камеры (масштаб 4.2).
BARS = "".join(f'<rect x="{x0 + 32}" y="{y}" width="{w}" height="12" rx="6"/>'
               for x0 in (240, 660) for y, w in ((118, 250), (150, 300), (182, 210), (214, 270), (246, 160)))
DIA = f"""
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
 <path id="linkArrow" opacity="0" d="M108 292Q62 252 104 212" fill="none" stroke="#0e5e9c" stroke-width="3.5" marker-end="url(#ar)" stroke-dasharray="140" stroke-dashoffset="140"/>
 <text id="cnt" x="1080" y="440" text-anchor="end" font-size="34" fill="#6b7280" opacity="0">0 из 16 171 байт</text>
 <text id="ok" x="200" y="440" font-size="34" fill="#0e5e9c" opacity="0">✓ симлинк + git commit</text>
 <text id="alarm" x="200" y="440" font-size="34" fill="#c9551b"></text>
</g>"""

SVG = f"""<svg id="stage" viewBox="0 0 1280 590" role="img" aria-labelledby="st"><title id="st">Сверка AGENTS.md и CLAUDE.md</title>
{defs}
{room}
{DIA}
</svg>"""

JS = r"""
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
 const io=EASE.io, d0=STEPS[0].d;
 $('prog').style.width=(t/acc*100).toFixed(3)+'%';
 document.querySelector('.cap').style.filter=`blur(${((1-clamp((t-st[i])/.45))*4).toFixed(2)}px)`;
 const br=$('brush'),L=br.getTotalLength();br.style.strokeDasharray=L;br.style.strokeDashoffset=(L*(1-io(clamp(t/1.2)))).toFixed(1);
 $('hm').setAttribute('transform',`rotate(${(300+t*9).toFixed(2)} 860 100)`);$('hh').setAttribute('transform',`rotate(${(-40+t*.75).toFixed(2)} 860 100)`);
 // наезд: экран (640,252) → центр карточек (640,170), масштаб 4.2; кончается до смены шага
 const z=io(clamp((t-.45*d0)/(.55*d0-.15))),s=1+3.2*z;
 $('cam').setAttribute('transform',`translate(640 ${(252-82*z).toFixed(2)}) scale(${s.toFixed(4)}) translate(-640 -252)`);
 $('room').setAttribute('opacity',(1-io(clamp((t-st[1]+.1)/.45))).toFixed(3));
 $('dia').setAttribute('opacity',io(clamp((t-st[1]+.15)/.45)).toFixed(3));
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
 const ty=diverged?clamp((t-st[3]-.4)/(STEPS[3].d*.45)):0,m=Math.round(ty*ALARM.length),blink=Math.floor(t*2.2)%2==0;
 $('alarm').textContent=ALARM.slice(0,m)+(diverged&&(ty<1||blink)?'▌':'');
}
"""

html = tpl.replace("</style>", CSS + "</style>", 1)
html = re.sub(r'<div class="stg"><svg id="stage".*?</svg></div>', lambda _: f'<div class="stg">{SVG}</div>', html, count=1, flags=re.S)
html = re.sub(r"const STEPS = \[.*?\];\n", lambda _: JS.lstrip("\n"), html, count=1, flags=re.S)
html = html.replace('<ol class="ch" id="chap"></ol>', '<ol class="ch" id="chap"></ol><div id="prog"></div>', 1)
html = html.replace("<title>Title</title>", "<title>V-912 демо v2: сверка AGENTS.md и CLAUDE.md</title>", 1)
assert 'id="room"' in html and "const ALARM" in html
sys.stdout.write(html)
