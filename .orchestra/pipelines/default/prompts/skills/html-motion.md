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
  меняет только названное, остальное держит. `[a, b]` — явно «от a к b» (повтор движения).
  `text` меняет текст, `along: 'idПути', at: 0..1` ведёт элемент по SVG-пути (рисуй его
  вокруг 0,0). `w` — доля шага, в которую меняется элемент: `[.75,1]` для итога «когда
  дошло», `[0,.5]` и `[.5,1]` — очерёдность внутри шага.
- **Плавность делает каркас, кривые не пиши.** Движение (числа: координаты, `at`, ширина)
  идёт весь шаг по пружине с критическим затуханием — мягкий старт, долгое торможение, без
  перелёта. Если тот же атрибут меняется в соседних шагах в ту же сторону, объект не
  останавливается на границе: скорость переходит в следующий шаг (монотонный кубический
  сплайн, без перелёта). Состояния — цвет `#rrggbb`, `opacity`, `text` — меняются за 0.5 с
  в начале окна: текст — наплывом старого в новый, появление и исчезновение — с лёгким
  сдвигом и масштабом. Подпись шага тоже меняется наплывом. `e:'lin'|'io'|'out'` нужен
  редко: равномерный ход ленты или часов. Задал `w` — изменение занимает всё окно.
- **Непрерывный путь вместо прыжков.** Не переставляй объект с одного пути на другой в
  видимом месте: сменил `along` — начало нового пути совпадает с концом прежнего. Токен,
  который «входит» в узел и выходит из него, рисуй ДО прямоугольников узлов и веди невидимым
  путём (`fill="none"` без `stroke`) через их центры: внутри узла он скрыт, там же можно
  сменить ему текст или пересадить на другой путь. Углы путей скругляй (`Q`).
- Анимируемое задавай атрибутами SVG, а не классами: CSS-правило перекрывает атрибут, и
  изменение не будет видно. Элементу с анимируемым `text` или `opacity` не давай свой
  `transform` — оберни в `<g>`: каркас двигает его через CSS `transform`. Вычисляемое
  (подпись курсора графика, Canvas) — в необязательной `function draw(i, p, t)`, она
  вызывается после применения состояний и тоже чиста от `t`.
- Шаг 2–4 с, всего до ~30 с. Подпись — 1–2 фразы: что меняется и почему это важно, с числами
  из источника. Порядок внутри шага: движение, затем результат.
- **График во времени:** линия открывается шириной `<clipPath>` (обычное числовое состояние:
  соседние шаги сливаются в одно непрерывное движение), маркеры событий — под тем же clip,
  чтобы появляться ровно при проходе курсора. Точку на курсоре веди по линии интерполяцией
  между соседними точками данных, а не ступенькой; значение у курсора в подписи считай в
  `draw` из данных: факт, ориентир и разница. Пропуск остаётся разрывом. Числа в подписях
  шагов сверяй со значением у курсора в конце шага.
- **Запасной вариант — Canvas:** тот же плеер, шаги без `set`, рисование в `draw` с учётом
  `devicePixelRatio`; подписи остаются в HTML. Бери, только когда объектов столько, что SVG
  не справляется: у Canvas нет DOM для наведения и доступности.
- Не подключай GSAP с CDN: без сети артефакт пустой. Встроенный весит 73 КБ, а пользы по
  сравнению с каркасом не даёт.

Проверка дополняет общую из `html-artifacts`: сними кадры `P.seek(0)`, середины и
`P.seek(P.T)`; поставь на паузу во время пуска и сравни снимок с `P.seek(P.t)`, сделанным
из другого состояния, — пиксели должны совпасть; пройди клавиши (⏮ ⏭ и ←/→ доезжают до
цели за 0.4 с), reduced motion и узкий экран. **Видео пиши покадрово, не экранной записью:**
`record_video_dir` Playwright даёт 25 к/с с повторёнными кадрами — рывки там, где их нет в
браузере. Нужен `page.clock.install()`, `P.play()`, затем в цикле `page.clock.run_for(1000/60)`
и снимок кадра → `ffmpeg -framerate 60 -f image2pipe -i - -c:v libx264 -pix_fmt yuv420p`.
Замер техник и плавности, примеры и скрипты записи лежат в репозитории Orchestra в
`.orchestra/tasks/V-665/` и `.orchestra/tasks/V-668/`.

## Каркас плеера

```html motion-template
<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Название</title>
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Ccircle cx='8' cy='8' r='7' fill='%23007aff'/%3E%3Cpath d='M6 4.5v7l6-3.5z' fill='%23fff'/%3E%3C/svg%3E">
<style>
body{margin:0;background:#f5f5f7;color:#1d1d1f;font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;-webkit-font-smoothing:antialiased}
.mv{max-width:980px;margin:16px auto;background:#fff;border-radius:14px;padding:16px 18px;box-shadow:0 1px 2px #0000000d,0 6px 20px #0000000a}
.mv h1{font-size:21px;margin:0 0 8px;letter-spacing:-.01em}.stg{overflow-x:auto}.stg>svg{width:100%;min-width:680px;height:auto;display:block}
.cap{position:relative;min-height:4.4em;margin:8px 0}.cap b{display:block;font-size:16px}#capB{position:absolute;inset:0 0 auto}
.bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.bar button{display:grid;place-items:center;width:32px;height:32px;padding:0;border:0;border-radius:50%;background:#f5f5f7;color:#1d1d1f;cursor:pointer;transition:transform .25s cubic-bezier(.3,1.5,.5,1),background-color .2s}
.bar button:hover{background:#e8e8ed}.bar button:active{transform:scale(.88)}.bar svg{width:14px;height:14px;fill:currentColor}
#bPlay{width:40px;height:40px;background:#007aff;color:#fff}#bPlay:hover{background:#0071e3}#bPlay svg{width:16px;height:16px}
#bPlay path{transition:opacity .2s,transform .3s cubic-bezier(.3,1.5,.5,1);transform-box:fill-box;transform-origin:center}#bPlay .i2,#bPlay.on .i1{opacity:0;transform:scale(.4)}#bPlay.on .i2{opacity:1;transform:none}
#seek{flex:1;min-width:140px;-webkit-appearance:none;appearance:none;height:4px;margin:0 4px;border-radius:2px;background:linear-gradient(#007aff 0 0) 0/var(--p,0%) 100% no-repeat,#e5e5ea;cursor:pointer}
#seek::-webkit-slider-thumb{-webkit-appearance:none;width:16px;height:16px;border-radius:50%;background:#fff;box-shadow:0 1px 4px #0000004d;transition:transform .2s}
#seek::-moz-range-thumb{width:16px;height:16px;border:0;border-radius:50%;background:#fff;box-shadow:0 1px 4px #0000004d;transition:transform .2s}
#seek:hover::-webkit-slider-thumb{transform:scale(1.2)}#seek:hover::-moz-range-thumb{transform:scale(1.2)}
#clock{font-variant-numeric:tabular-nums;min-width:92px;text-align:right;color:#6e6e73}.bar select{border:0;background:#f5f5f7;border-radius:8px;padding:6px 8px;font:inherit;cursor:pointer}
.ch{display:flex;gap:6px;flex-wrap:wrap;margin:12px 0 0;padding:0;list-style:none}
.ch li{--o:0;padding:3px 10px;border-radius:8px;cursor:pointer;background:color-mix(in srgb,#007aff calc(var(--o)*100%),#f5f5f7);color:color-mix(in srgb,#fff calc(var(--o)*100%),#1d1d1f)}.ch li:hover{filter:brightness(.96)}
@media print{.bar{display:none}}@media (prefers-reduced-motion:reduce){*{transition:none!important}}
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
<div class="cap"><div id="capA" aria-live="polite"><b id="capT"></b><span id="capX"></span></div><div id="capB" aria-hidden="true"><b></b><span></span></div></div>
<div class="bar"><button id="bPrev" aria-label="Предыдущий шаг"><svg viewBox="0 0 16 16"><path d="M3 3h2v10H3zM13 3v10L5.5 8z"/></svg></button><button id="bPlay" aria-label="Пуск или пауза"><svg viewBox="0 0 16 16"><path class="i1" d="M4.5 2.5v11l9-5.5z"/><path class="i2" d="M4 3h3v10H4zM9 3h3v10H9z"/></svg></button><button id="bNext" aria-label="Следующий шаг"><svg viewBox="0 0 16 16"><path d="M11 3h2v10h-2zM3 3v10l7.5-5z"/></svg></button>
 <input id="seek" type="range" min="0" step="0.01" value="0" aria-label="Время"><span id="clock"></span>
 <select id="rate" aria-label="Скорость"><option value="0.5">0.5×</option><option value="1" selected>1×</option><option value="2">2×</option></select></div>
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
const clamp=(v,a=0,b=1)=>Math.min(b,Math.max(a,v)),SK=7;
const EASE={spring:p=>(1-(1+SK*p)*Math.exp(-SK*p))/(1-(1+SK)*Math.exp(-SK)),io:p=>p*p*(3-2*p),out:p=>1-(1-p)**3,lin:p=>p}; // spring: критическое затухание
const hex=/^#[0-9a-f]{6}$/i,mix=(a,b,p)=>typeof a=='number'&&typeof b=='number'?a+(b-a)*p:hex.test(a)&&hex.test(b)?'#'+[1,3,5].map(k=>Math.round(parseInt(a.substr(k,2),16)*(1-p)+parseInt(b.substr(k,2),16)*p).toString(16).padStart(2,'0')).join(''):p>0?b:a;
const P=(()=>{const S=[],TL={},E={},G={},FX={},rm=matchMedia('(prefers-reduced-motion: reduce)').matches,FADE=.5,sp=EASE.spring;let T=0,t=0,on=false,last=0,ci=-1,gl=null;
 const get=(e,a)=>{const v=a=='text'?e.textContent:e.getAttribute(a);return v!==null&&v!==''&&!isNaN(v)?+v:v};
 // у каждого атрибута свой список отрезков {t0,t1,a,b}; между отрезками значение держится
 for(const s of STEPS){for(const[id,o]of Object.entries(s.set||{}))for(const[a,v]of Object.entries(o)){const e=E[id]??=$(id),L=(TL[id]??={})[a]??=Object.assign([],{v0:get(e,a)}),
   to=Array.isArray(v)?v[1]:v,st=a=='text'||/opacity/.test(a)||typeof to=='string',w=s.w?.[id];
   L.push({t0:T+(w?w[0]*s.d:0),t1:T+(w?w[1]*s.d:st?Math.min(s.d,FADE):s.d),a:Array.isArray(v)?v[0]:(L.length?L.at(-1).b:L.v0)??to,b:to,e:s.e,st,m0:0,m1:0})}
  S.push(T);T+=s.d}
 // стык двух движений в одну сторону: общая скорость (монотонный сплайн Фрича–Батленда), объект не встаёт на границе шага
 for(const id in TL)for(const a in TL[id]){const L=TL[id][a];for(let k=1;k<L.length;k++){const x=L[k-1],y=L[k],h0=x.t1-x.t0,h1=y.t1-y.t0,d0=(x.b-x.a)/h0,d1=(y.b-y.a)/h1;
   if(!x.st&&!y.st&&!x.e&&!y.e&&Math.abs(x.t1-y.t0)<1e-9&&x.b===y.a&&d0*d1>0)x.m1=y.m0=3*(h0+h1)/((2*h1+h0)/d0+(h1+2*h0)/d1)}}
 for(const id in TL){const e=E[id],o=TL[id];if(o.along||!(o.text||o.opacity))continue;FX[id]=1;
  if(o.text){const g=G[id]=e.cloneNode(true);g.removeAttribute('id');g.setAttribute('aria-hidden','true');e.after(g)}
  for(const x of[e,G[id]])if(x)Object.assign(x.style,{transformBox:'fill-box',transformOrigin:'center'})}
 const val=(L,t)=>{let g=null;for(const s of L)if(s.t0<t||s.t0<=0&&t<=0)g=s;if(!g)return[L.v0,1,L.v0,L.v0];
  const h=g.t1-g.t0,p=h>0?clamp((t-g.t0)/h):1;if(p>=1)return[g.b,1,g.a,g.b];
  if(g.m0||g.m1){const p2=p*p,p3=p2*p;return[(2*p3-3*p2+1)*g.a+(p3-2*p2+p)*h*g.m0+(3*p2-2*p3)*g.b+(p3-p2)*h*g.m1,p,g.a,g.b]}
  const q=(EASE[g.e]||sp)(p);return[mix(g.a,g.b,q),q,g.a,g.b]};
 const xout=q=>1-EASE.io(clamp(q/.45)),xin=q=>EASE.io(clamp((q-.35)/.65)); // смена текста: старый уходит раньше, чем проявляется новый — буквы не наслаиваются
 const put=(e,a,v)=>{const c=e._c??={};if(c[a]===v)return;c[a]=v;a=='text'?e.textContent=v:a=='css'?e.style.transform=v:a[0]=='-'?e.style.setProperty(a,v):e.setAttribute(a,v)};
 function frame(te){for(const id in TL){const e=E[id],o=TL[id],g=G[id],v={};for(const a in o)v[a]=val(o[a],te);let dy=0,gy=0,k=0;
   for(const a in v)if(a!='text'&&a!='along'&&a!='at'&&v[a][0]!=null)put(e,a,v[a][0]);
   if(v.opacity){const[,q,f,b]=v.opacity;k=f==0&&b!=0?1-q:b==0&&f!=0?q:0}
   if(v.text&&!g)put(e,'text',v.text[0]);
   if(g){const[x,q,f,b]=v.text,x2=f!==b&&q<1;put(e,'text',x2?b:x);put(g,'text',f);put(e,'fill-opacity',x2?xin(q):1);put(g,'fill-opacity',x2?xout(q):0);
    if(x2){dy=(1-q)*6;gy=-q*6}for(const a of['opacity','fill'])if(v[a])put(g,a,e.getAttribute(a))}
   if(FX[id]){const tf=d=>`translateY(${(d+k*6).toFixed(2)}px) scale(${(1-.03*k).toFixed(4)})`;put(e,'css',tf(dy));if(g)put(g,'css',tf(gy))}
   if(v.along){const p=$(v.along[0]),pt=p.getPointAtLength(clamp(v.at?.[0]??0)*p.getTotalLength());put(e,'transform',`translate(${pt.x.toFixed(2)},${pt.y.toFixed(2)})`)}}}
 const at=t=>{let i=S.length-1;while(i>0&&t<=S[i])i--;return i},end=i=>S[i]+STEPS[i].d;
 function seek(v){t=clamp(v,0,T);const i=at(t);frame(rm?end(i):t);if(typeof draw=='function')draw(i,rm?1:clamp((t-S[i])/STEPS[i].d),t);
  if(i!==ci){ci=i;$('capT').textContent=(i+1)+'. '+STEPS[i].t;$('capX').textContent=STEPS[i].x;const B=$('capB').children;B[0].textContent=i?i+'. '+STEPS[i-1].t:'';B[1].textContent=i?STEPS[i-1].x:'';
   [...$('chap').children].forEach((li,k)=>li.classList.toggle('on',k==i))}
  const q=rm||!i?1:sp(clamp((t-S[i])/FADE));[...$('chap').children].forEach((li,k)=>put(li,'--o',k==i?q:k==i-1?1-q:0));$('capA').style.cssText=`opacity:${xin(q)};transform:translateY(${(1-q)*6}px)`;$('capB').style.cssText=`opacity:${xout(q)};transform:translateY(${-q*6}px)`;
  $('seek').value=t;$('seek').style.setProperty('--p',t/T*100+'%');$('clock').textContent=t.toFixed(1)+' / '+T.toFixed(1)+' с'}
 function tick(now){if(!on)return;seek(t+Math.max(0,now-last)/1000*$('rate').value);last=now;t>=T?pause():requestAnimationFrame(tick)}
 function play(){gl=null;if(t>=T)t=0;on=true;last=performance.now();$('bPlay').classList.add('on');requestAnimationFrame(tick)}
 function pause(){on=false;gl=null;$('bPlay').classList.remove('on')}
 function glide(to){pause();if(rm)return seek(to);const a=t,t0=performance.now(),g=gl={to},f=now=>{if(gl!==g)return;const q=clamp((now-t0)/400);seek(q<1?a+(to-a)*EASE.out(q):to);if(q<1)requestAnimationFrame(f);else gl=null};requestAnimationFrame(f)}
 const toggle=()=>on?pause():play(),next=()=>{const c=gl?gl.to:t,i=at(c);glide(c<end(i)-1e-3?end(i):end(Math.min(i+1,S.length-1)))},prev=()=>{const c=gl?gl.to:t,i=at(c);glide(i?end(i-1):0)};
 $('seek').max=T;$('seek').oninput=e=>{pause();seek(+e.target.value)};$('bPlay').onclick=toggle;$('bNext').onclick=next;$('bPrev').onclick=prev;
 STEPS.forEach((s,k)=>{const li=document.createElement('li');li.textContent=(k+1)+'. '+s.t;li.onclick=()=>{seek(S[k]);play()};$('chap').append(li)});
 addEventListener('keydown',e=>{const f={' ':toggle,ArrowRight:next,ArrowLeft:prev,Home:()=>{pause();seek(0)},End:()=>{pause();seek(T)}}[e.key];if(f&&e.target.tagName!='SELECT'){e.preventDefault();f()}});
 seek(+(location.hash.match(/t=([\d.]+)/)||[])[1]||0);return{seek,play,pause,get t(){return t},T,S}})();
</script></body></html>
```
