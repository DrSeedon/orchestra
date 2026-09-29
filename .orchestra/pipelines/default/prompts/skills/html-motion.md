---
name: html-motion
description: "Анимированное объяснение по шагам в HTML: готовый каркас плеера (пуск/пауза, шаги, перемотка, скорость, клавиши), пояснение к каждому шагу, анимация графика во времени, проверка кадров и запись MP4."
---

# HTML Motion

Дополнение к `html-artifacts`: его внешний вид, честность данных, самостоятельный файл,
SVG-иконка и проверка действуют и здесь. Этот скилл добавляет только движение и плеер.

Анимация нужна, когда смысл в порядке или в изменении во времени: путь задачи, передача
данных, рост показателя к событию. Она поясняет, а не украшает. Ответ виден сразу: подпись
текущего шага и список всех шагов на экране, любой кадр доступен без просмотра до конца.

- **Время — единственная правда.** Кадр — чистая функция от `t`: `render` каждый раз
  выставляет все анимируемые атрибуты, не накапливая изменений. Тогда пауза, перемотка назад
  и шаг по стрелке дают тот же кадр, что и проигрывание. Цепочки `setTimeout` и CSS
  `@keyframes` к произвольному `t` не перематываются; у Web Animations API `pause()`
  срабатывает на кадр позже, а `play()` завершённой анимации перематывает её в 0.
- **Каркас ниже вставляй целиком, не переписывай.** Сцену заполняй в двух местах: SVG с `id`
  и массив `STEPS`. Плеер уже умеет пуск/паузу, шаги ⏮ ⏭, ползунок, скорость 0.5/1/2,
  клавиши (пробел, ←/→ — конец шага, Home/End), главы кликом, `prefers-reduced-motion`
  (шаг сразу в итоговом состоянии), печать, ссылку на кадр `#t=12.5` и `window.P`
  (`seek/play/pause/t/T/S`) для проверки. Если есть shell, копируй каркас из файла скилла
  командой, а не перепечатывай: `awk '/^```html motion-template/{f=1;next} f&&/^```/{exit} f'
  <путь к этому SKILL.md> > out.html` (обычно `.claude/skills/html-motion/SKILL.md` или
  `.codex/skills/html-motion/SKILL.md` в рабочей папке).
- **Шаг:** `{d: секунды, t: 'что происходит', x: 'почему и что это значит, с числами',
  set: {id: {атрибут: значение}}, w: {id: [от, до]}, e: 'lin'}`. `set` накапливается: шаг
  меняет только названное, остальное держит. Числа и цвета `#rrggbb` плавно переходят от
  прежнего значения, строки переключаются в начале окна, `[a, b]` — явно «от a к b» (повтор
  движения). `text` меняет текст, `along: 'idПути', at: 0..1` ведёт элемент по SVG-пути
  (рисуй его вокруг 0,0). `w` — доля шага, в которую меняется элемент: `[.75,1]` для
  итога «когда дошло», `[0,.5]` и `[.5,1]` — очерёдность внутри шага.
- Анимируемое задавай атрибутами SVG, а не классами: CSS-правило перекрывает атрибут, и
  изменение не будет видно. Вычисляемое (подпись курсора графика, Canvas) — в необязательной
  `function draw(i, p, t)`, она вызывается после применения состояний и тоже чиста от `t`.
- Шаг 2–4 с, всего до ~30 с. Подпись — 1–2 фразы: что меняется и почему это важно, с числами
  из источника. Порядок внутри шага: движение, затем результат.
- **График во времени:** линия открывается шириной `<clipPath>` (обычное числовое состояние),
  маркеры событий — под тем же clip, чтобы появляться ровно при проходе курсора. Значение
  у курсора считай в `draw` из данных: факт, ориентир и разница. Пропуск остаётся разрывом.
  Числа в подписях шагов сверяй со значением у курсора в конце шага.
- **Запасной вариант — Canvas:** тот же плеер, шаги без `set`, рисование в `draw` с учётом
  `devicePixelRatio`; подписи остаются в HTML. Бери, только когда объектов столько, что SVG
  не справляется: у Canvas нет DOM для наведения и доступности.
- Не подключай GSAP с CDN: без сети артефакт пустой. Встроенный весит 73 КБ, а пользы по
  сравнению с каркасом не даёт.

Проверка дополняет общую из `html-artifacts`: сними кадры `P.seek(0)`, середины и
`P.seek(P.T)`; поставь на паузу во время пуска и сравни снимок с `P.seek(P.t)`, сделанным
из другого состояния, — пиксели должны совпасть; пройди клавиши, reduced motion и узкий экран. Видео при необходимости:
Playwright `record_video_dir` → `P.play()` на `P.T` секунд → `ffmpeg -c:v libx264 -pix_fmt
yuv420p` в MP4. Замер техник, примеры и скрипты проверки лежат в репозитории Orchestra
в `.orchestra/tasks/V-665/`.

## Каркас плеера

```html motion-template
<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Название</title>
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Ccircle cx='8' cy='8' r='7' fill='%23007aff'/%3E%3Cpath d='M6 4.5v7l6-3.5z' fill='%23fff'/%3E%3C/svg%3E">
<style>
body{margin:0;background:#f5f5f7;color:#1d1d1f;font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif}
.mv{max-width:980px;margin:16px auto;background:#fff;border-radius:12px;padding:14px 16px}
.mv h1{font-size:21px;margin:0 0 8px}.stg{overflow-x:auto}.stg>svg{width:100%;min-width:680px;height:auto;display:block}
.cap{min-height:4.4em;margin:8px 0}.cap b{display:block;font-size:16px}
.bar{display:flex;flex-wrap:wrap;gap:6px;align-items:center}.bar input{flex:1;min-width:140px}
.bar button,.bar select{border:1px solid #d2d2d7;background:#fff;border-radius:8px;padding:4px 10px;font:inherit;cursor:pointer}
#clock{font-variant-numeric:tabular-nums;min-width:92px;text-align:right;color:#6e6e73}
.ch{display:flex;gap:6px;flex-wrap:wrap;margin:10px 0 0;padding:0;list-style:none}
.ch li{padding:3px 9px;border-radius:8px;background:#f5f5f7;cursor:pointer}.ch li.on{background:#007aff;color:#fff}
@media print{.bar{display:none}}
</style>
</head><body>
<div class="mv">
<h1>Заголовок: что объясняем</h1>
<div class="stg"><svg id="stage" viewBox="0 0 900 200" role="img" aria-labelledby="st"><title id="st">О чём схема</title>
 <defs><marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L10 5L0 10z" fill="#86868b"/></marker></defs>
 <path id="e1" d="M260 100H640" stroke="#86868b" stroke-width="2" fill="none" marker-end="url(#ar)"/>
 <rect id="a" x="60" y="68" width="200" height="64" rx="12" fill="#ffffff" stroke="#d2d2d7" stroke-width="2"/><text x="160" y="105" text-anchor="middle">Источник</text>
 <rect id="b" x="640" y="68" width="200" height="64" rx="12" fill="#ffffff" stroke="#d2d2d7" stroke-width="2"/><text id="bT" x="740" y="105" text-anchor="middle">Приёмник</text>
 <circle id="dot" r="9" fill="#007aff" opacity="0"/>
</svg></div>
<div class="cap" aria-live="polite"><b id="capT"></b><span id="capX"></span></div>
<div class="bar"><button id="bPrev" aria-label="Предыдущий шаг">⏮</button><button id="bPlay" aria-label="Пуск или пауза">▶</button><button id="bNext" aria-label="Следующий шаг">⏭</button>
 <input id="seek" type="range" min="0" step="0.01" value="0" aria-label="Время"><span id="clock"></span>
 <select id="rate" aria-label="Скорость"><option>0.5</option><option selected>1</option><option>2</option></select></div>
<ol class="ch" id="chap"></ol>
</div>
<script>
// ── СЦЕНА ──
const STEPS = [
 {d:2, t:'Источник готов', x:'Что происходит и почему — одна-две фразы с числами.', set:{a:{stroke:'#007aff'}, dot:{opacity:[0,1], along:'e1', at:0}}},
 {d:3, t:'Передача', x:'Итог шага появляется, когда точка дошла.', set:{dot:{at:[0,1]}, b:{stroke:'#34c759', fill:'#e8f7ec'}, bT:{text:'Получено'}}, w:{b:[.75,1], bT:[.75,1]}},
];
// ── ПЛЕЕР ──
function $(id){return document.getElementById(id)} // function: всплывает, сцена может звать $ раньше плеера
const clamp=(v,a=0,b=1)=>Math.min(b,Math.max(a,v)),EASE={io:p=>p<.5?2*p*p:1-(1-p)*(1-p)*2,lin:p=>p};
const hex=/^#[0-9a-f]{6}$/i,mix=(a,b,p)=>typeof a=='number'&&typeof b=='number'?a+(b-a)*p:hex.test(a)&&hex.test(b)?'#'+[1,3,5].map(k=>Math.round(parseInt(a.substr(k,2),16)*(1-p)+parseInt(b.substr(k,2),16)*p).toString(16).padStart(2,'0')).join(''):p>0?b:a;
const P=(()=>{const S=[],K=[],cur={},rm=matchMedia('(prefers-reduced-motion: reduce)').matches;let T=0,t=0,on=false,last=0,ci=-1;
 const get=(e,a)=>{const v=a=='text'?e.textContent:e.getAttribute(a);return v!==null&&v!==''&&!isNaN(v)?+v:v};
 for(const s of STEPS)for(const[id,o]of Object.entries(s.set||{}))for(const a in o)(cur[id]??={})[a]=get($(id),a);
 for(const s of STEPS){S.push(T);T+=s.d;const from=structuredClone(cur);
  for(const[id,o]of Object.entries(s.set||{}))for(const[a,v]of Object.entries(o)){if(Array.isArray(v))from[id][a]=v[0];cur[id][a]=Array.isArray(v)?v[1]:v}
  K.push([from,structuredClone(cur)])}
 const at=t=>{let i=S.length-1;while(i>0&&t<=S[i])i--;return i},end=i=>S[i]+STEPS[i].d;
 function render(i,p){const[f,to]=K[i],s=STEPS[i],E=EASE[s.e]||EASE.io;
  for(const id in to){const w=s.w?.[id]||[0,1],q=E(clamp((p-w[0])/(w[1]-w[0]))),e=$(id),v={};for(const a in to[id]){v[a]=mix(f[id][a],to[id][a],q);
    if(a=='text')e.textContent=v[a];else if(a!='along'&&a!='at'&&v[a]!=null)e.setAttribute(a,v[a])}
   if(v.along){const g=$(v.along),pt=g.getPointAtLength((v.at??0)*g.getTotalLength());e.setAttribute('transform',`translate(${pt.x},${pt.y})`)}}
  if(typeof draw=='function')draw(i,p,t)}
 function seek(v){t=clamp(v,0,T);const i=at(t);render(i,rm?1:clamp((t-S[i])/STEPS[i].d));
  $('seek').value=t;$('clock').textContent=t.toFixed(1)+' / '+T.toFixed(1)+' с';
  if(i!==ci){ci=i;$('capT').textContent=(i+1)+'. '+STEPS[i].t;$('capX').textContent=STEPS[i].x;[...$('chap').children].forEach((li,k)=>li.classList.toggle('on',k==i))}}
 function tick(now){if(!on)return;seek(t+(now-last)/1000*$('rate').value);last=now;t>=T?pause():requestAnimationFrame(tick)}
 function play(){if(t>=T)t=0;on=true;last=performance.now();$('bPlay').textContent='⏸';requestAnimationFrame(tick)}
 function pause(){on=false;$('bPlay').textContent='▶'}
 const toggle=()=>on?pause():play(),next=()=>{pause();const i=at(t);seek(t<end(i)-1e-3?end(i):end(Math.min(i+1,S.length-1)))},prev=()=>{pause();const i=at(t);seek(i?end(i-1):0)};
 $('seek').max=T;$('seek').oninput=e=>{pause();seek(+e.target.value)};$('bPlay').onclick=toggle;$('bNext').onclick=next;$('bPrev').onclick=prev;
 STEPS.forEach((s,k)=>{const li=document.createElement('li');li.textContent=(k+1)+'. '+s.t;li.onclick=()=>{seek(S[k]);play()};$('chap').append(li)});
 addEventListener('keydown',e=>{const f={' ':toggle,ArrowRight:next,ArrowLeft:prev,Home:()=>{pause();seek(0)},End:()=>{pause();seek(T)}}[e.key];if(f&&e.target.tagName!='SELECT'){e.preventDefault();f()}});
 seek(+(location.hash.match(/t=([\d.]+)/)||[])[1]||0);return{seek,play,pause,get t(){return t},T,S}})();
</script></body></html>
```
