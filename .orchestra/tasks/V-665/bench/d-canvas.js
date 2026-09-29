// ── СЦЕНА ──
const STEPS=[{d:2,t:'Владелец ставит задачу',x:'Задача появляется у владельца.'},{d:2,t:'Задача уходит оркестратору',x:'Оркестратор получает постановку.'},
 {d:2,t:'Оркестратор назначает воркера',x:'Воркер берёт задачу в работу.'},{d:2,t:'Воркер сделал',x:'Результат готов к мержу.'}];
const $=id=>document.getElementById(id),cv=$('cv'),W=900,H=220,dpr=devicePixelRatio||1,c=cv.getContext('2d');
cv.width=W*dpr;cv.height=H*dpr;c.scale(dpr,dpr);
const clamp=(v,a=0,b=1)=>Math.min(b,Math.max(a,v)),io=p=>p<.5?2*p*p:1-(1-p)*(1-p)*2,lerp=(a,b,p)=>a+(b-a)*p,
 mixc=(a,b,p)=>'#'+[1,3,5].map(k=>Math.round(lerp(parseInt(a.substr(k,2),16),parseInt(b.substr(k,2),16),p)).toString(16).padStart(2,'0')).join('');
function box(x,w,fill,stroke,label){c.beginPath();c.roundRect(x,75,w,70,12);c.fillStyle=fill;c.fill();c.lineWidth=2;c.strokeStyle=stroke;c.stroke();
 c.fillStyle='#1d1d1f';c.font='14px -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif';c.textAlign='center';c.fillText(label,x+w/2,115)}
function arrow(x1,x2){c.strokeStyle='#86868b';c.lineWidth=2;c.beginPath();c.moveTo(x1,110);c.lineTo(x2-2,110);c.stroke();
 c.fillStyle='#86868b';c.beginPath();c.moveTo(x2,110);c.lineTo(x2-9,105);c.lineTo(x2-9,115);c.fill()}
function draw(t){const p=i=>io(clamp((t-2*i)/2));c.clearRect(0,0,W,H);arrow(190,350);arrow(550,710);
 box(40,150,'#ffffff','#007aff','Владелец');box(350,200,'#ffffff',mixc('#d2d2d7','#007aff',p(1)),'Оркестратор');
 box(710,150,mixc('#ffffff','#e8f7ec',p(3)),p(3)>0?mixc('#007aff','#34c759',p(3)):mixc('#d2d2d7','#007aff',p(2)),'Воркер');
 c.fillStyle=t>6?'#248a3d':'#6e6e73';c.fillText(t>6?'готово':'ожидает',785,170);
 const x=t<4?lerp(190,350,p(1)):lerp(550,710,p(2));c.globalAlpha=p(0)*(1-p(3));c.fillStyle='#007aff';c.beginPath();c.arc(x,110,9,0,7);c.fill();c.globalAlpha=1}
// ── ПЛЕЕР ──
const P=(()=>{const S=[],rm=matchMedia('(prefers-reduced-motion: reduce)').matches;let T=0,t=0,on=false,last=0,ci=-1;for(const s of STEPS){S.push(T);T+=s.d}
 const at=t=>{let i=S.length-1;while(i>0&&t<=S[i])i--;return i},end=i=>S[i]+STEPS[i].d;
 function seek(v){t=clamp(v,0,T);const i=at(t);draw(rm?end(i):t);$('seek').value=t;$('clock').textContent=t.toFixed(1)+' / '+T.toFixed(1)+' с';
  if(i!==ci){ci=i;$('capT').textContent=(i+1)+'. '+STEPS[i].t;$('capX').textContent=STEPS[i].x;[...$('chap').children].forEach((li,k)=>li.classList.toggle('on',k==i))}}
 function tick(now){if(!on)return;seek(t+(now-last)/1000*$('rate').value);last=now;t>=T?pause():requestAnimationFrame(tick)}
 function play(){if(t>=T)t=0;on=true;last=performance.now();$('bPlay').textContent='⏸';requestAnimationFrame(tick)}
 function pause(){on=false;$('bPlay').textContent='▶'}
 const toggle=()=>on?pause():play(),next=()=>{pause();const i=at(t);seek(t<end(i)-1e-3?end(i):end(Math.min(i+1,S.length-1)))},prev=()=>{pause();const i=at(t);seek(i?end(i-1):0)};
 $('seek').max=T;$('seek').oninput=e=>{pause();seek(+e.target.value)};$('bPlay').onclick=toggle;$('bNext').onclick=next;$('bPrev').onclick=prev;
 STEPS.forEach((s,k)=>{const li=document.createElement('li');li.textContent=(k+1)+'. '+s.t;li.onclick=()=>{seek(S[k]);play()};$('chap').append(li)});
 addEventListener('keydown',e=>{const f={' ':toggle,ArrowRight:next,ArrowLeft:prev,Home:()=>{pause();seek(0)},End:()=>{pause();seek(T)}}[e.key];if(f&&e.target.tagName!='SELECT'){e.preventDefault();f()}});
 seek(+(location.hash.match(/t=([\d.]+)/)||[])[1]||0);return{seek,play,pause,get t(){return t},T,S}})();
