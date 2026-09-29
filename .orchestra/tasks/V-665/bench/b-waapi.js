// ── СЦЕНА ──
const STEPS=[{d:2,t:'Владелец ставит задачу',x:'Задача появляется у владельца.'},{d:2,t:'Задача уходит оркестратору',x:'Оркестратор получает постановку.'},
 {d:2,t:'Оркестратор назначает воркера',x:'Воркер берёт задачу в работу.'},{d:2,t:'Воркер сделал',x:'Результат готов к мержу.'}];
const $=id=>document.getElementById(id),A=[],an=(id,kf,s,d)=>A.push($(id).animate(kf,{delay:s*1000,duration:d*1000,fill:'forwards',easing:'ease-in-out'}));
$('dot').setAttribute('opacity',1);$('dot').style.opacity=0;$('dot').style.transform='translate(190px,110px)';
an('dot',[{opacity:0},{opacity:1}],0,2);
an('dot',[{transform:'translate(190px,110px)'},{transform:'translate(350px,110px)'}],2,2);
an('n2',[{stroke:'#d2d2d7'},{stroke:'#007aff'}],2,2);
an('dot',[{transform:'translate(550px,110px)'},{transform:'translate(710px,110px)'}],4,2);
an('n3',[{stroke:'#d2d2d7'},{stroke:'#007aff'}],4,2);
an('dot',[{opacity:1},{opacity:0}],6,2);
an('n3',[{fill:'#ffffff',stroke:'#007aff'},{fill:'#e8f7ec',stroke:'#34c759'}],6,2);
const sync=t=>{$('st3').textContent=t>6?'готово':'ожидает';$('st3').setAttribute('fill',t>6?'#248a3d':'#6e6e73')}; // текст WAAPI не анимирует
// ── ПЛЕЕР ──
const P=(()=>{const S=[];let T=0,ci=-1,on=false;for(const s of STEPS){S.push(T);T+=s.d}
 const M=document.body.animate([{},{}],{duration:T*1000,fill:'forwards'}); // главные часы
 const all=()=>[M,...A],now=()=>Math.min(T,M.currentTime/1000);
 const at=t=>{let i=S.length-1;while(i>0&&t<=S[i])i--;return i},end=i=>S[i]+STEPS[i].d;
 function ui(){const t=now(),i=at(t);sync(t);$('seek').value=t;$('clock').textContent=t.toFixed(1)+' / '+T.toFixed(1)+' с';
  if(i!==ci){ci=i;$('capT').textContent=(i+1)+'. '+STEPS[i].t;$('capX').textContent=STEPS[i].x;[...$('chap').children].forEach((li,k)=>li.classList.toggle('on',k==i))}}
 function loop(){ui();if(on){if(now()>=T)pause();else requestAnimationFrame(loop)}}
 function seek(v){all().forEach(a=>{a.pause();a.currentTime=Math.min(T,Math.max(0,v))*1000});on=false;$('bPlay').textContent='▶';ui()}
 function play(){if(now()>=T)seek(0);all().forEach(a=>{a.playbackRate=+$('rate').value;a.play()});on=true;$('bPlay').textContent='⏸';loop()}
 function pause(){all().forEach(a=>a.pause());on=false;$('bPlay').textContent='▶';ui()}
 const toggle=()=>on?pause():play(),next=()=>{const t=now(),i=at(t);seek(t<end(i)-1e-3?end(i):end(Math.min(i+1,S.length-1)))},prev=()=>{const i=at(now());seek(i?end(i-1):0)};
 $('seek').max=T;$('seek').oninput=e=>seek(+e.target.value);$('bPlay').onclick=toggle;$('bNext').onclick=next;$('bPrev').onclick=prev;
 $('rate').onchange=()=>all().forEach(a=>a.updatePlaybackRate(+$('rate').value));
 STEPS.forEach((s,k)=>{const li=document.createElement('li');li.textContent=(k+1)+'. '+s.t;li.onclick=()=>{seek(S[k]);play()};$('chap').append(li)});
 addEventListener('keydown',e=>{const f={' ':toggle,ArrowRight:next,ArrowLeft:prev,Home:()=>seek(0),End:()=>seek(T)}[e.key];if(f&&e.target.tagName!='SELECT'){e.preventDefault();f()}});
 seek(+(location.hash.match(/t=([\d.]+)/)||[])[1]||0);return{seek,play,pause,get t(){return now()},T,S}})();
