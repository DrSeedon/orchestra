// ── СЦЕНА ──
const STEPS=[{d:2,t:'Владелец ставит задачу',x:'Задача появляется у владельца.'},{d:2,t:'Задача уходит оркестратору',x:'Оркестратор получает постановку.'},
 {d:2,t:'Оркестратор назначает воркера',x:'Воркер берёт задачу в работу.'},{d:2,t:'Воркер сделал',x:'Результат готов к мержу.'}];
const $=id=>document.getElementById(id),tl=gsap.timeline({paused:true,defaults:{ease:'power1.inOut',duration:2}});
gsap.set('#dot',{x:190,y:110});
tl.fromTo('#dot',{attr:{opacity:0}},{attr:{opacity:1}},0)
 .to('#dot',{x:350},2).to('#n2',{attr:{stroke:'#007aff'}},2)
 .set('#dot',{x:550},4).to('#dot',{x:710},4).to('#n3',{attr:{stroke:'#007aff'}},4)
 .to('#dot',{attr:{opacity:0}},6).to('#n3',{attr:{fill:'#e8f7ec',stroke:'#34c759'}},6);
const sync=t=>{$('st3').textContent=t>6?'готово':'ожидает';$('st3').setAttribute('fill',t>6?'#248a3d':'#6e6e73')}; // текст — вручную
// ── ПЛЕЕР ──
const P=(()=>{const S=[];let T=0,ci=-1;for(const s of STEPS){S.push(T);T+=s.d}
 const at=t=>{let i=S.length-1;while(i>0&&t<=S[i])i--;return i},end=i=>S[i]+STEPS[i].d;
 function ui(){const t=tl.time(),i=at(t);sync(t);$('seek').value=t;$('clock').textContent=t.toFixed(1)+' / '+T.toFixed(1)+' с';
  if(i!==ci){ci=i;$('capT').textContent=(i+1)+'. '+STEPS[i].t;$('capX').textContent=STEPS[i].x;[...$('chap').children].forEach((li,k)=>li.classList.toggle('on',k==i))}}
 tl.eventCallback('onUpdate',ui);tl.eventCallback('onComplete',()=>{tl.pause();$('bPlay').textContent='▶'});
 const seek=v=>{tl.pause(Math.min(T,Math.max(0,v)));$('bPlay').textContent='▶';ui()},play=()=>{if(tl.time()>=T)tl.time(0);tl.play();$('bPlay').textContent='⏸'},pause=()=>{tl.pause();$('bPlay').textContent='▶'};
 const toggle=()=>tl.paused()?play():pause(),next=()=>{const t=tl.time(),i=at(t);seek(t<end(i)-1e-3?end(i):end(Math.min(i+1,S.length-1)))},prev=()=>{const i=at(tl.time());seek(i?end(i-1):0)};
 $('seek').max=T;$('seek').oninput=e=>seek(+e.target.value);$('bPlay').onclick=toggle;$('bNext').onclick=next;$('bPrev').onclick=prev;$('rate').onchange=()=>tl.timeScale(+$('rate').value);
 STEPS.forEach((s,k)=>{const li=document.createElement('li');li.textContent=(k+1)+'. '+s.t;li.onclick=()=>{seek(S[k]);play()};$('chap').append(li)});
 addEventListener('keydown',e=>{const f={' ':toggle,ArrowRight:next,ArrowLeft:prev,Home:()=>seek(0),End:()=>seek(T)}[e.key];if(f&&e.target.tagName!='SELECT'){e.preventDefault();f()}});
 seek(+(location.hash.match(/t=([\d.]+)/)||[])[1]||0);return{seek,play,pause,get t(){return tl.time()},T,S}})();
