'use strict';
const $ = id => document.getElementById(id);
const joints = [[20,'左髋转向'],[21,'左髋侧摆'],[22,'左髋前后'],[23,'左膝'],[24,'左踝'],[10,'右髋转向'],[11,'右髋侧摆'],[12,'右髋前后'],[13,'右膝'],[14,'右踝'],[30,'脖子前后'],[31,'头部点头'],[32,'头部转向'],[33,'头部侧歪'],[34,'嘴']];
for (const [id, name] of joints) { const option = document.createElement('option'); option.value = id; option.textContent = `${id} · ${name}`; $('joint').append(option); }
let token = '', connected = false, pending = false, polling = false, commandBusy = false, generation = 0, trustFingerprint = '';
let bus = null;
function message(text, error = false) { $('message').textContent = text; $('message').classList.toggle('error', error); }
function controls() {
  for (const id of ['refresh','disconnect','relax']) $(id).disabled = !connected;
  $('disconnect').disabled = !connected || pending || commandBusy;
  $('connection').querySelector('[type=submit]').disabled = pending || commandBusy;
  const ready = connected && bus?.mode === 'commissioning' && $('supported').checked && !commandBusy;
  $('save').disabled = !ready; $('center').disabled = !ready || !$('unassembled').checked;
  $('imu').disabled = !ready || !$('imu-confirmed').checked;
}
async function api(path, body = {}) {
  const response = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json','X-Session-Token':token}, body:JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) { const error = new Error(data.error || '请求失败'); error.fingerprint = data.fingerprint; throw error; }
  return data.result;
}
const display = value => value == null ? '—' : String(value);
function showStatus(data) {
  connected = data.connected; bus = data.bus || null; controls();
  if (!connected) { $('summary').textContent = '已断开；旧读数不再作为实时反馈。'; $('servos').replaceChildren(); $('raw').textContent = '未连接'; $('calibration-info').textContent = ''; return; }
  const sample = bus.last_sample || {};
  const rows = sample.servos || bus.native?.joints || bus.joints || [];
  const saved = data.calibration?.calibration?.joints || [];
  const age = typeof sample.at_us === 'number' && typeof bus.updated_at_us === 'number' ? (bus.updated_at_us-sample.at_us)/1000 : null;
  const fresh = age != null && age >= 0 && age <= 500 && bus.mode === 'commissioning';
  $('summary').textContent = `${data.target} · ${bus.build || '未知固件'} · ${bus.mode || '未知模式'} / ${bus.phase || '—'} · 反馈间隔 ${age == null ? '未知' : Math.round(age)+' ms'} · 卸力状态 ${bus.torque_state || '未知'}${fresh ? '' : ' · 反馈未确认新鲜，请核对原始数据'}`;
  $('servos').replaceChildren();
  for (const [id, name] of joints) {
    const row = rows.find(x => x.id === id), cal = saved.find(x => x.id === id);
    const tr = document.createElement('tr');
    for (const value of [`${id} · ${name}`, row ? `${display(row.position_raw)}${fresh?'':'（待核对）'}` : '无反馈', row?.voltage_v ?? row?.volts, row?.temperature_c, cal?.calibrated ? `${cal.zero_raw} / ${cal.direction}` : '未标定']) {
      const td = document.createElement('td'); td.textContent = display(value); tr.append(td);
    }
    $('servos').append(tr);
  }
  $('calibration-info').textContent = data.calibration_error || `标定路径：${data.calibration?.calibration_path || '—'}；运动校验：${data.calibration?.motion_validation || '未报告错误（不代表已启用运动）'}`;
  $('raw').textContent = JSON.stringify({bus, calibration:data.calibration}, null, 2);
}
async function refresh() {
  if (!connected || polling) return;
  polling = true; const current = generation;
  try { const data = await api('/api/status'); if (current === generation) showStatus(data); }
  catch (error) { if (current === generation) { bus = null; controls(); $('summary').textContent = '读取失败，下面保留的是旧读数，不能用于标定。卸力仍可尝试，成功与否以回执为准。'; message(error.message, true); } }
  finally { polling = false; }
}
async function connect(fingerprint = '') {
  if (pending) return;
  pending = true; generation++; $('connection').querySelector('[type=submit]').disabled = true;
  const form = new FormData($('connection'));
  const data = {target:form.get('target').trim(),port:Number(form.get('port')),password:form.get('password'),socket:form.get('socket').trim(),fingerprint};
  try {
    message('正在验证 SSH 与 robotd，不发送运动指令…');
    const result = await api('/api/connect', data); $('connection').elements.password.value = ''; $('host-key').hidden = true;
    connected = true; showStatus(result); message('已通过真实 SSH 连接并读到 robotd 状态。'); await refresh();
  } catch (error) {
    if (error.fingerprint) { trustFingerprint = error.fingerprint; $('fingerprint').textContent = error.fingerprint; $('host-key').hidden = false; message('需要先核对 SSH 主机指纹。'); }
    else { $('connection').elements.password.value = ''; message(error.message, true); }
  } finally { pending = false; $('connection').querySelector('[type=submit]').disabled = false; controls(); }
}
async function command(data) {
  if (data.action !== 'relax' && commandBusy) return;
  const regular = data.action !== 'relax';
  if (regular) commandBusy = true;
  controls();
  try {
    message('正在等待 robotd 回执；失败或超时不会自动重发。');
    const result = await api('/api/command', {...data,supported:$('supported').checked});
    message('robotd 回执：' + JSON.stringify(result)); await refresh();
  } catch (error) { message(error.message + '；请刷新核对实际状态，指令没有自动重发。', true); }
  finally { if (regular) commandBusy = false; controls(); }
}
$('connection').addEventListener('submit', event => { event.preventDefault(); connect(); });
$('trust').addEventListener('click', () => connect(trustFingerprint));
$('disconnect').addEventListener('click', async () => { try { await api('/api/disconnect'); generation++; showStatus({connected:false}); message('SSH 已断开。断开本身不代表机器人已卸力。'); } catch(error) {message(error.message,true);} });
$('refresh').addEventListener('click', refresh);
$('relax').addEventListener('click', () => command({action:'relax'}));
$('capture').addEventListener('submit', event => {
  event.preventDefault(); const data = Object.fromEntries(new FormData(event.currentTarget));
  for (const key of Object.keys(data)) data[key] = Number(data[key]);
  if (confirm(`将写入 ${data.id} 号关节的真实标定。确认已摆到 ${data.angle_deg}°，方向和限位已核对？`)) command({...data,action:'capture'});
});
$('center').addEventListener('click', () => { if(confirm(`允许 ${$('joint').value} 号舵机真实转动到 2048？请确认已拆下舵盘并脱离骨架。`)) command({action:'center-one',id:Number($('joint').value),unassembled:$('unassembled').checked}); });
$('imu').addEventListener('click', () => { if(confirm('确认当前 IMU 安装方向已按固件要求核验，将保存此确认？')) command({action:'verify-imu',confirmed:$('imu-confirmed').checked}); });
for (const id of ['supported','unassembled','imu-confirmed']) $(id).addEventListener('change',controls);
fetch('/api/session').then(r=>r.json()).then(data=>{token=data.token;setInterval(refresh,2000);}).catch(error=>message('本机服务不可用：'+error.message,true));
