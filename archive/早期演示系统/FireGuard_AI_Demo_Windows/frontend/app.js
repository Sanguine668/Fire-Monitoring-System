const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const api = async (url, options={}) => {
  const res = await fetch(url, {headers:{'Content-Type':'application/json'}, ...options});
  if(!res.ok) throw new Error(await res.text());
  return res.json();
};

const titles = {
  dashboard:['监控总览','园区重点区域安全态势实时监测'],
  monitor:['实时监控','AI 视频分析与火灾烟雾识别'],
  alarms:['告警中心','统一处置烟雾、明火及高风险事件'],
  cameras:['视频源管理','RTSP / 视频流设备统一管理'],
  settings:['系统设置','检测阈值、告警策略与模型参数配置']
};

function goPage(name){
  $$('.page').forEach(x=>x.classList.toggle('active',x.id===name));
  $$('.nav-item').forEach(x=>x.classList.toggle('active',x.dataset.page===name));
  $('#pageTitle').textContent=titles[name][0]; $('#pageSub').textContent=titles[name][1];
  if(name==='alarms') loadAlarms(); if(name==='cameras') loadCameras(); if(name==='settings') loadSettings();
}
window.goPage=goPage;
$$('.nav-item').forEach(b=>b.onclick=()=>goPage(b.dataset.page));

function updateClock(){ $('#clock').textContent=new Date().toLocaleString('zh-CN',{hour12:false}); }
setInterval(updateClock,1000); updateClock();

function renderBars(){
  const vals=[2,4,1,5,3,6,2]; const labels=['周一','周二','周三','周四','周五','周六','今天'];
  $('#barChart').innerHTML=vals.map((v,i)=>`<div class="bar-item"><div class="bar" style="height:${25+v*16}px"><em>${v}</em></div><span>${labels[i]}</span></div>`).join('');
}
renderBars();

async function loadDashboard(){
  const d=await api('/api/dashboard');
  $('#metricCameras').textContent=d.camera_count; $('#metricOnline').textContent=`${d.online_count} 个在线`;
  $('#metricAlarms').textContent=d.today_alarms; $('#metricCritical').textContent=d.critical_alarms; $('#alarmBadge').textContent=d.unhandled;
  renderRecent(d.recent);
}
function renderRecent(items){
  $('#recentAlarms').innerHTML = items.length ? items.map(a=>`<div class="recent-item"><div class="recent-icon ${a.alarm_type}">${a.alarm_type==='fire'?'🔥':'☁'}</div><div><b>${a.alarm_type==='fire'?'检测到明火':'检测到烟雾'} · ${a.camera_name}</b><small>${a.level==='critical'?'严重告警':'预警'} · 置信度 ${(a.confidence*100).toFixed(0)}%</small></div><time>${a.created_at.slice(11)}</time></div>`).join('') : '<div class="empty">暂无告警记录</div>';
}

function applyDetection(d){
  const fire=d.objects.find(x=>x.type==='fire'), smoke=d.objects.find(x=>x.type==='smoke');
  ['#dashStage','#mainStage'].forEach(sel=>{
    const stage=$(sel); stage.querySelector('.fire-box').classList.toggle('hidden',!fire); stage.querySelector('.smoke-box').classList.toggle('hidden',!smoke);
    stage.querySelector('.fire-effect').classList.toggle('hidden',!fire); stage.querySelector('.smoke-effect').classList.toggle('hidden',!smoke);
    if(fire) stage.querySelector('.fire-box b').textContent=fire.confidence.toFixed(2);
    if(smoke) stage.querySelector('.smoke-box b').textContent=smoke.confidence.toFixed(2);
  });
  $('#dashFps').textContent=d.fps; $('#dashLatency').textContent=d.latency_ms+' ms'; $('#dashRisk').textContent=String(d.risk_score).padStart(2,'0');
  $('#fps').textContent=d.fps+' FPS'; $('#latency').textContent=d.latency_ms+' ms'; $('#objectCount').textContent=d.objects.length;
  setRisk(d.risk_score,d.status);
}
function setRisk(score,status){
  $('#riskScore').textContent=String(score).padStart(2,'0'); $('#currentRisk').textContent=status==='critical'?'危险':status==='warning'?'预警':'正常';
  const circle=$('#riskCircle'); circle.style.strokeDashoffset=314-(314*score/100); circle.style.stroke=status==='critical'?'#ff525d':status==='warning'?'#f2b84b':'#23d18b';
  const label=$('#riskLabel'); label.className='risk-label '+(status==='critical'?'critical':status==='warning'?'warning':'safe'); label.textContent=status==='critical'?'高风险 · 火灾':status==='warning'?'疑似烟雾预警':'当前安全';
  $('#riskText').textContent=status==='critical'?'检测到明火及伴生烟雾，请立即核查':status==='warning'?'连续检测到疑似烟雾目标':'未检测到烟雾或明火目标';
}

async function triggerDemo(kind){
  await api('/api/demo/trigger/'+kind,{method:'POST'}); toast(kind==='fire'?'已启动明火检测演示':kind==='smoke'?'已启动烟雾检测演示':'已恢复正常场景',kind==='fire'?'danger':'info');
}
window.triggerDemo=triggerDemo;

function toast(msg,type='danger'){
  const t=$('#toast'); t.innerHTML=`<b>${type==='danger'?'火灾预警系统':'系统提示'}</b>${msg}`; t.classList.add('show'); setTimeout(()=>t.classList.remove('show'),3500);
}

async function loadAlarms(){
  const rows=await api('/api/alarms'); $('#alarmBadge').textContent=rows.filter(x=>x.status==='unhandled').length;
  $('#alarmTable').innerHTML=rows.length?rows.map(a=>`<tr><td>${a.created_at}</td><td>${a.camera_name}</td><td><span class="tag ${a.alarm_type}">${a.alarm_type==='fire'?'🔥 明火':'☁ 烟雾'}</span></td><td><span class="tag ${a.level}">${a.level==='critical'?'严重':'预警'}</span></td><td>${(a.confidence*100).toFixed(1)}%</td><td><span class="tag ${a.status}">${a.status==='handled'?'已处理':'待处理'}</span></td><td>${a.status==='unhandled'?`<button onclick="ackAlarm(${a.id})">确认处理</button>`:'—'}</td></tr>`).join(''):'<tr><td colspan="7" class="empty">暂无告警记录，进入实时监控点击测试按钮即可生成演示告警。</td></tr>';
}
async function ackAlarm(id){await api('/api/alarms/'+id+'/ack',{method:'POST'}); await loadAlarms(); await loadDashboard(); toast('告警已确认处理','info')}
window.ackAlarm=ackAlarm; window.loadAlarms=loadAlarms;

async function loadCameras(){
  const rows=await api('/api/cameras'); $('#cameraCards').innerHTML=rows.map(c=>`<div class="camera-card"><div class="cam-icon">▣</div><div><h3>${c.name}</h3><p>${c.location}</p><small>${c.source}</small></div><button class="switch" onclick="toggleCamera(${c.id})">${c.enabled?'● 已启用':'○ 已停用'}</button></div>`).join('');
}
async function toggleCamera(id){await api('/api/cameras/'+id+'/toggle',{method:'POST'}); loadCameras()}
window.toggleCamera=toggleCamera;

async function loadSettings(){const s=await api('/api/settings'); $('#fireThreshold').value=s.fire_threshold;$('#smokeThreshold').value=s.smoke_threshold;$('#continuousFrames').value=s.continuous_frames;$('#alarmCooldown').value=s.alarm_cooldown}
$('#settingsForm').onsubmit=async e=>{e.preventDefault(); const body={fire_threshold:+$('#fireThreshold').value,smoke_threshold:+$('#smokeThreshold').value,continuous_frames:+$('#continuousFrames').value,alarm_cooldown:+$('#alarmCooldown').value}; await api('/api/settings',{method:'PUT',body:JSON.stringify(body)}); toast('参数保存成功','info')};

function connectWs(){
  const protocol=location.protocol==='https:'?'wss':'ws'; const ws=new WebSocket(`${protocol}://${location.host}/ws/events`);
  ws.onopen=()=>ws.send('hello');
  ws.onmessage=e=>{const data=JSON.parse(e.data); if(data.event==='detection') applyDetection(data); if(data.event==='alarm'){const a=data.alarm; toast(`${a.camera_name}：${a.alarm_type==='fire'?'检测到明火':'检测到烟雾'}，置信度 ${(a.confidence*100).toFixed(0)}%`); loadDashboard(); if($('#alarms').classList.contains('active')) loadAlarms();}};
  ws.onclose=()=>setTimeout(connectWs,1500); setInterval(()=>{if(ws.readyState===1)ws.send('ping')},10000);
}
connectWs(); loadDashboard();
