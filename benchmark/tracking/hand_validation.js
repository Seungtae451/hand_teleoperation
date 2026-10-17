"use strict";
(()=>{
const el=id=>document.getElementById(id);
const names=['wrist','thumb CMC','thumb MCP','thumb IP','thumb tip','index MCP','index PIP','index DIP','index tip','middle MCP','middle PIP','middle DIP','middle tip','ring MCP','ring PIP','ring DIP','ring tip','pinky MCP','pinky PIP','pinky DIP','pinky tip'];
const colors=['#ffa985','#82cfff','#96dfb2','#f4d47d','#c4adfa'];
const axisColors=['#ff8c91','#80d7aa','#8ebeff'];
let samples,clipIndex=0,frameIndex=0,playing=false,live={hands:{}};
el('joint-names').textContent=names.map((name,i)=>`${i}: ${name}`).join(' · ');
function draw(id,points,valid=true){
 const c=el(id),ctx=c.getContext('2d');ctx.clearRect(0,0,c.width,c.height);
 const projections=[[1,2,'Y–Z 정면'],[0,2,'X–Z 측면'],[1,0,'Y–X 위쪽']];
 projections.forEach(([a,b,title],view)=>{
  const left=view*220,ox=left+110,oy=b===2?330:210,scale=1000;
  ctx.save();ctx.beginPath();ctx.rect(left,0,220,410);ctx.clip();
  ctx.fillStyle='#bdcce0';ctx.font='13px system-ui';ctx.fillText(title,left+12,22);
  ctx.strokeStyle='#263a4f';ctx.lineWidth=.5;
  for(let k=-12;k<=22;k++){ctx.beginPath();ctx.moveTo(left,oy-k*10);ctx.lineTo(left+220,oy-k*10);ctx.stroke();}
  for(let k=-11;k<=11;k++){ctx.beginPath();ctx.moveTo(ox+k*10,35);ctx.lineTo(ox+k*10,385);ctx.stroke();}
  for(const [axis,dx,dy] of [[a,45,0],[b,0,-45]]){ctx.strokeStyle=axisColors[axis];ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(ox,oy);ctx.lineTo(ox+dx,oy+dy);ctx.stroke();ctx.fillStyle=axisColors[axis];ctx.fillText('+'+'XYZ'[axis],ox+dx+3,oy+dy-3);}
  if(points){
   const pixels=points.map(p=>[ox+p[a]*scale,oy-p[b]*scale]);ctx.globalAlpha=valid?1:.28;
   for(let f=0;f<5;f++){
    const chain=[0,...Array.from({length:4},(_,j)=>1+f*4+j)];ctx.strokeStyle=colors[f];ctx.fillStyle=colors[f];ctx.lineWidth=2.4;ctx.beginPath();
    chain.forEach((n,j)=>{const [x,y]=pixels[n];j?ctx.lineTo(x,y):ctx.moveTo(x,y)});ctx.stroke();
    chain.slice(1).forEach(n=>{const [x,y]=pixels[n];ctx.beginPath();ctx.arc(x,y,3.2,0,Math.PI*2);ctx.fill();if(el('numbers').checked){ctx.font='10px system-ui';ctx.fillText(String(n),x+4,y-3)}});
   }
   ctx.globalAlpha=1;
  }else{ctx.fillStyle='#879ab2';ctx.fillText('입력 대기',left+70,170)}
  ctx.fillStyle='#879ab2';ctx.font='11px system-ui';ctx.fillText('격자 10 mm · 같은 스케일',left+12,397);ctx.restore();
 });
 c._points=points;
}
document.querySelectorAll('canvas.pose').forEach(c=>{
 c.addEventListener('mousemove',event=>{
  if(!c._points)return;const rect=c.getBoundingClientRect(),x=(event.clientX-rect.left)*c.width/rect.width,y=(event.clientY-rect.top)*c.height/rect.height;
  const view=Math.min(2,Math.floor(x/220)),axes=[[1,2],[0,2],[1,0]][view],ox=view*220+110,oy=axes[1]===2?330:210;
  let best=0,distance=Infinity;c._points.forEach((p,i)=>{const d=Math.hypot(x-ox-p[axes[0]]*1000,y-oy+p[axes[1]]*1000);if(d<distance){distance=d;best=i}});
  c.title=distance<20?`${best}: ${names[best]} · XYZ mm: ${c._points[best].map(v=>(v*1000).toFixed(1)).join(', ')}`:'';
 });
});
function metrics(points){if(!points)return '입력 대기';const d=(a,b)=>Math.hypot(...points[a].map((v,i)=>v-points[b][i]))*1000;return `손끝 X mm [엄지→새끼]: ${[4,8,12,16,20].map(i=>(points[i][0]*1000).toFixed(1)).join(' / ')} · 엄지–검지 ${d(4,8).toFixed(1)} mm`;}
function render(){
 const clip=samples?.clips[clipIndex],frame=clip?.frames[frameIndex];
 if(frame){draw('public-right',frame.right);draw('public-left',frame.left);draw('public-reflected',frame.right.map(p=>[-p[0],p[1],p[2]]));el('public-metrics').textContent=metrics(frame.right);
  el('public-meta').textContent=`공개 학습 구간 · episode ${clip.episode} · 원본 frame ${frame.frame_index} · 제공자 동작 문자열: ${frame.action_label}`;el('position').textContent=`${frameIndex+1}/${clip.frames.length}`;}
 for(const side of ['right','left']){const hand=live.hands?.[side];draw('live-'+side,hand?.points,hand?.valid);el(side+'-status').textContent=hand?.valid?'추적 중':(hand?.reason||'대기');}
 el('live-metrics').textContent=metrics(live.hands?.right?.points);
 el('reflection-card').hidden=!el('reflection').checked;
 const parity=live.hands?.right?.canonical_adapter_difference_m;
 el('parity').textContent=`공개 학습 export와 화면 변환 최대 차이: ${samples?.canonical_training_export_max_difference_m?.toExponential(2)||'대기'} m · 실제 입력의 기존 GeoRT adapter와 차이: ${parity==null?'대기':parity.toExponential(2)+' m'}`;
}
el('clip').onchange=()=>{clipIndex=Number(el('clip').value);frameIndex=samples.clips[clipIndex].center_index;el('frame').max=samples.clips[clipIndex].frames.length-1;el('frame').value=frameIndex;render()};
el('frame').oninput=()=>{frameIndex=Number(el('frame').value);render()};
el('play').onclick=()=>{playing=!playing;el('play').textContent=playing?'일시정지':'구간 재생'};
el('numbers').onchange=render;el('reflection').onchange=render;
setInterval(()=>{if(playing&&samples){frameIndex=(frameIndex+1)%samples.clips[clipIndex].frames.length;el('frame').value=frameIndex;render()}},1000/30);
async function poll(){try{const response=await fetch('/validation.json');if(!response.ok)throw Error('상태 수신 실패');live=await response.json();if(location.protocol!=='https:'){el('connection').textContent=live.source_connected?'Quest 연결됨':'Quest HTTPS 접속 대기';}render();}catch(error){el('error').textContent=String(error)}finally{setTimeout(poll,120)}}
fetch('/samples.json').then(r=>r.json()).then(data=>{samples=data;samples.clips.forEach((clip,i)=>{const option=document.createElement('option');option.value=i;option.textContent=clip.label;el('clip').appendChild(option)});el('clip').onchange();poll()}).catch(error=>{el('error').textContent=String(error)});
})();
