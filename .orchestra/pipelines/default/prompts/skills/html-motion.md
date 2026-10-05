---
name: html-motion
description: "Step-by-step animated HTML explanation: a ready player scaffold (play/pause, steps, seeking, speed, keys), an explanation for each step, chart animation over time, frame checks, and MP4 recording."
---

# HTML Motion

An extension of `html-artifacts`: its appearance, honest data, standalone file, SVG icon, and
checks apply here too. This skill adds only motion and the player.

Animation is useful when meaning lies in order or change over time: a task path, data transfer,
or a metric growing toward an event. It explains rather than decorates. The answer is visible
immediately: the current step label and all steps remain on screen, and any frame is available
without watching to the end.

 - **Time is the only truth.** A frame is a pure function of `t`: `render` sets every animated
   attribute on each call without accumulating changes. Pause, reverse seek, and arrow stepping
   then produce the same frame as playback. `setTimeout` chains and CSS `@keyframes` cannot seek
   to arbitrary `t`; Web Animations API `pause()` fires one frame late, and `play()` on a finished
   animation rewinds it to 0.
 - **Insert the scaffold below whole; do not rewrite it.** Fill the scene in two places: the SVG
   with its `id` and the `STEPS` array. The player already supports play/pause, ⏮ ⏭ steps, slider,
   speed 0.5/1/2, keys (space, ←/→ to step end, Home/End), click chapters,
   `prefers-reduced-motion` (step immediately at final state), print, frame link `#t=12.5`, and
   `window.P` (`seek/play/pause/t/T/S`) for checks. If a shell is available, copy the scaffold
   from this skill instead of retyping it: `awk '/^```html motion-template/{f=1;next} f&&/^```/{exit} f'
   <path-to-this-SKILL.md> > out.html` (usually `.claude/skills/html-motion/SKILL.md` or
   `.codex/skills/html-motion/SKILL.md` in the working folder).
 - **Step:** `{d: seconds, t: 'what happens', x: 'why it matters, with numbers', set: {id: {attribute: value}}, w: {id: [from, to]}, e: 'lin'}`. `set` accumulates: a step changes only named values and holds the rest. `[a, b]` explicitly means “from a to b” (repeat motion). `text` changes text, `along: 'pathId', at: 0..1` moves an element along an SVG path (draw it around 0,0). `w` is the fraction of the step during which an element changes: `[.75,1]` for a result “when it arrives”, `[0,.5]` and `[.5,1]` for ordering within a step.
 - **The scaffold handles smoothness; do not write curves.** Numeric motion (coordinates, `at`,
   width) runs through the whole step with critically damped spring motion: soft start, long
   braking, no overshoot. If the same attribute changes in the same direction in adjacent steps,
   the object does not stop at the boundary: velocity continues into the next step (monotone
   cubic spline without overshoot). States — `#rrggbb`, `opacity`, `text` — change over 0.5 s at
   the window start: text crossfades old to new, appearance/disappearance uses a slight shift and
   scale. The step label also crossfades. Use `e:'lin'|'io'|'out'` rarely, for uniform tape or
   clock motion. If `w` is set, the change fills that entire window.
 - **Use continuous paths instead of jumps.** Do not move an object from one path to another at a
   visible point: when `along` changes, the new path must begin at the old path's end. Draw a
   token that enters and leaves a node BEFORE node rectangles, and route it through their centers
   on an invisible path (`fill="none"` without `stroke`): it is hidden inside the node, where you
   may change its text or move it to another path. Round path corners (`Q`).
 - Set animated values through SVG attributes, not classes: CSS rules override attributes and hide
   the change. Do not give an element with animated `text` or `opacity` its own `transform`; wrap
   it in `<g>`, so the scaffold moves it through CSS `transform`. Computed content (chart cursor
   label, Canvas) belongs in optional `function draw(i, p, t)`, called after states are applied and
   also pure in `t`.
 - Use 2–4 s per step and about 30 s total. The label is 1–2 source-grounded sentences: what
   changes and why it matters, with numbers. Within a step, move first, then show the result.
 - **Chart over time:** reveal the line by `<clipPath>` width (an ordinary numeric state; adjacent
   steps merge into one continuous movement), and put event markers under the same clip so they
   appear exactly as the cursor passes. Move the cursor point by interpolation between adjacent
   data points, not a step; calculate its label value in `draw` from the data: fact, reference,
   and difference. Keep missing data as a gap. Check step-label numbers against the cursor value
   at the end of the step.
 - **Canvas fallback:** use the same player, steps without `set`, and draw with `devicePixelRatio`;
   labels remain HTML. Use it only when there are so many objects that SVG cannot cope: Canvas has
   no DOM for hover or accessibility.
 - Do not load GSAP from a CDN: without a network the artifact is empty. The embedded version is
   73 KB and gives no benefit over the scaffold.

Checks extend those in `html-artifacts`: capture frames at `P.seek(0)`, the middle, and
`P.seek(P.T)`; pause during playback and compare with a capture from `P.seek(P.t)` in another
state — pixels must match. Test keys (⏮ ⏭ and ←/→ reach the target in 0.4 s), reduced motion,
and a narrow screen. **Write video frame by frame, not by screen recording:** Playwright's
`record_video_dir` gives 25 fps with repeated frames and creates stutter absent in the browser.
Use `page.clock.install()`, `P.play()`, then loop over `page.clock.run_for(1000/60)` and capture
frames → `ffmpeg -framerate 60 -f image2pipe -i - -c:v libx264 -pix_fmt yuv420p`.
Technique and smoothness measurements, examples, and recording scripts are in the Orchestra
repository under `.orchestra/tasks/V-665/` and `.orchestra/tasks/V-668/`.

## Player scaffold

```html motion-template
<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Title</title>
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
<h1>Title: what we explain</h1>
<div class="stg"><svg id="stage" viewBox="0 0 900 200" role="img" aria-labelledby="st"><title id="st">What the diagram shows</title>
 <defs><marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L10 5L0 10z" fill="#86868b"/></marker></defs>
 <path id="e1" d="M260 100H640" stroke="#86868b" stroke-width="2" fill="none" marker-end="url(#ar)"/>
 <rect id="a" x="60" y="68" width="200" height="64" rx="12" fill="#ffffff" stroke="#d2d2d7" stroke-width="2"/><text x="160" y="105" text-anchor="middle">Source</text>
 <rect id="b" x="640" y="68" width="200" height="64" rx="12" fill="#ffffff" stroke="#d2d2d7" stroke-width="2"/><text id="bT" x="740" y="105" text-anchor="middle">Receiver</text>
 <circle id="dot" r="9" fill="#007aff" opacity="0"/>
</svg></div>
<div class="cap"><div id="capA" aria-live="polite"><b id="capT"></b><span id="capX"></span></div><div id="capB" aria-hidden="true"><b></b><span></span></div></div>
<div class="bar"><button id="bPrev" aria-label="Previous step"><svg viewBox="0 0 16 16"><path d="M3 3h2v10H3zM13 3v10L5.5 8z"/></svg></button><button id="bPlay" aria-label="Play or pause"><svg viewBox="0 0 16 16"><path class="i1" d="M4.5 2.5v11l9-5.5z"/><path class="i2" d="M4 3h3v10H4zM9 3h3v10H9z"/></svg></button><button id="bNext" aria-label="Next step"><svg viewBox="0 0 16 16"><path d="M11 3h2v10h-2zM3 3v10l7.5-5z"/></svg></button>
 <input id="seek" type="range" min="0" step="0.01" value="0" aria-label="Time"><span id="clock"></span>
 <select id="rate" aria-label="Speed"><option value="0.5">0.5×</option><option value="1" selected>1×</option><option value="2">2×</option></select></div>
<ol class="ch" id="chap"></ol>
</div>
<script>
// ── SCENE ──
const STEPS = [
 {d:2, t:'Source ready', x:'What happens and why — one or two sentences with numbers.', set:{a:{stroke:'#007aff'}, dot:{opacity:[0,1], along:'e1', at:0}}},
 {d:3, t:'Transfer', x:'The step result appears when the dot arrives.', set:{dot:{at:[0,1]}, b:{stroke:'#34c759', fill:'#e8f7ec'}, bT:{text:'Received'}}, w:{b:[.75,1], bT:[.75,1]}},
];
// ── PLAYER ──
function $(id){return document.getElementById(id)} // function declaration is hoisted; scenes may call $ before the player
const clamp=(v,a=0,b=1)=>Math.min(b,Math.max(a,v)),SK=7;
const EASE={spring:p=>(1-(1+SK*p)*Math.exp(-SK*p))/(1-(1+SK)*Math.exp(-SK)),io:p=>p*p*(3-2*p),out:p=>1-(1-p)**3,lin:p=>p}; // critically damped spring
const hex=/^#[0-9a-f]{6}$/i,mix=(a,b,p)=>typeof a=='number'&&typeof b=='number'?a+(b-a)*p:hex.test(a)&&hex.test(b)?'#'+[1,3,5].map(k=>Math.round(parseInt(a.substr(k,2),16)*(1-p)+parseInt(b.substr(k,2),16)*p).toString(16).padStart(2,'0')).join(''):p>0?b:a;
const P=(()=>{const S=[],TL={},E={},G={},FX={},rm=matchMedia('(prefers-reduced-motion: reduce)').matches,FADE=.5,sp=EASE.spring;let T=0,t=0,on=false,last=0,ci=-1,gl=null;
 const get=(e,a)=>{const v=a=='text'?e.textContent:e.getAttribute(a);return v!==null&&v!==''&&!isNaN(v)?+v:v};
 // each attribute has its own segment list {t0,t1,a,b}; value holds between segments
 for(const s of STEPS){for(const[id,o]of Object.entries(s.set||{}))for(const[a,v]of Object.entries(o)){const e=E[id]??=$(id),L=(TL[id]??={})[a]??=Object.assign([],{v0:get(e,a)}),
   to=Array.isArray(v)?v[1]:v,st=a=='text'||/opacity/.test(a)||typeof to=='string',w=s.w?.[id];
   L.push({t0:T+(w?w[0]*s.d:0),t1:T+(w?w[1]*s.d:st?Math.min(s.d,FADE):s.d),a:Array.isArray(v)?v[0]:(L.length?L.at(-1).b:L.v0)??to,b:to,e:s.e,st,m0:0,m1:0})}
  S.push(T);T+=s.d}
 // same-direction motion joins with shared velocity (monotone Fritsch–Butland spline)
 for(const id in TL)for(const a in TL[id]){const L=TL[id][a];for(let k=1;k<L.length;k++){const x=L[k-1],y=L[k],h0=x.t1-x.t0,h1=y.t1-y.t0,d0=(x.b-x.a)/h0,d1=(y.b-y.a)/h1;
   if(!x.st&&!y.st&&!x.e&&!y.e&&Math.abs(x.t1-y.t0)<1e-9&&x.b===y.a&&d0*d1>0)x.m1=y.m0=3*(h0+h1)/((2*h1+h0)/d0+(h1+2*h0)/d1)}}
 for(const id in TL){const e=E[id],o=TL[id];if(o.along||!(o.text||o.opacity))continue;FX[id]=1;
  if(o.text){const g=G[id]=e.cloneNode(true);g.removeAttribute('id');g.setAttribute('aria-hidden','true');e.after(g)}
  for(const x of[e,G[id]])if(x)Object.assign(x.style,{transformBox:'fill-box',transformOrigin:'center'})}
 const val=(L,t)=>{let g=null;for(const s of L)if(s.t0<t||s.t0<=0&&t<=0)g=s;if(!g)return[L.v0,1,L.v0,L.v0];
  const h=g.t1-g.t0,p=h>0?clamp((t-g.t0)/h):1;if(p>=1)return[g.b,1,g.a,g.b];
  if(g.m0||g.m1){const p2=p*p,p3=p2*p;return[(2*p3-3*p2+1)*g.a+(p3-2*p2+p)*h*g.m0+(3*p2-2*p3)*g.b+(p3-p2)*h*g.m1,p,g.a,g.b]}
  const q=(EASE[g.e]||sp)(p);return[mix(g.a,g.b,q),q,g.a,g.b]};
 const xout=q=>1-EASE.io(clamp(q/.45)),xin=q=>EASE.io(clamp((q-.35)/.65)); // text change: old leaves before new appears, so letters do not overlap
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
  $('seek').value=t;$('seek').style.setProperty('--p',t/T*100+'%');$('clock').textContent=t.toFixed(1)+' / '+T.toFixed(1)+' s'}
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
