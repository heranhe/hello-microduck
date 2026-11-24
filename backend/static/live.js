'use strict';

// This adapter is loaded by the local service only. The demo keeps its own state.
const live = {
  mode: true, step: 'connect', selected: null, target: 'radxa@192.168.31.37',
  port: 22, socket: '/run/robotd.sock', token: '', report: null, receivedAt: -Infinity,
  busy: false, relaxing: false, pendingRead: null, pendingKey: null,
  calibration: null, pendingCalibration: null, calibrationDue: 0,
  readDue: 0, panelDue: 0, feedbackVisible: false, feedbackError: '',
  error: '', notice: '', visited: new Set(),
};

async function liveApi(path, body) {
  const options = body === undefined ? {} : {
    method: 'POST', headers: {'Content-Type': 'application/json', 'X-Session-Token': live.token},
    body: JSON.stringify(body),
  };
  const response = await fetch(`/api/${path}`, options);
  const data = await response.json();
  if (!response.ok) {
    const error = new Error(data.error || '本机服务请求失败');
    error.fingerprint = data.fingerprint;
    throw error;
  }
  return body === undefined ? data : data.result;
}

const liveConnected = () => live.report?.connected === true;
const liveSample = () => live.report?.bus?.last_sample;
const liveCalibration = () => live.calibration?.calibration;
const liveSaved = joint => liveCalibration()?.joints?.find(row => row.id === joint.id && row.calibrated);
const liveNative = () => live.report?.bus?.native || live.report?.bus;
const feedbackMaxAgeMs = 500;

function liveAge(now) {
  const bus = live.report?.bus;
  const elapsed = now - live.receivedAt;
  if (!liveConnected() || !bus || !Number.isFinite(elapsed) || elapsed < 0) return Infinity;
  if (bus.mode === 'motion') {
    const age = liveNative()?.sample_age_ms;
    return bus.phase === 'control' && bus.fresh_sample !== false && Number.isFinite(age) && age >= 0
      ? age + elapsed : Infinity;
  }
  const age = (bus.updated_at_us - liveSample()?.at_us) / 1000;
  return Number.isFinite(age) && age >= 0 ? age + elapsed : Infinity;
}

const liveFresh = (now = performance.now()) => liveAge(now) <= feedbackMaxAgeMs;

function liveServo(joint, now = performance.now()) {
  if (!liveFresh(now)) return null;
  const motionMode = live.report.bus.mode === 'motion';
  const rows = motionMode ? liveNative()?.joints : liveSample()?.servos;
  if (!Array.isArray(rows)) return null;
  const row = rows.find(item => item?.id === joint.id && (item.joint || item.name) === joint.key);
  if (!Number.isInteger(row?.position_raw)) return null;
  if (motionMode && (row.feedback_fresh === false
      || row.sample_age_ms + now - live.receivedAt > feedbackMaxAgeMs)) return null;
  return row;
}

function liveTorqueLabel() {
  const bus = live.report?.bus;
  if (bus?.mode !== 'motion') return bus?.torque_state || '未知';
  const confirmed = liveNative()?.torque_state_confirmed;
  return confirmed === true ? '已上力' : confirmed === false ? '已卸力' : '未确认';
}

function liveMotorReady() {
  const bus = live.report?.bus;
  return liveConnected() && liveFresh() && bus.mode === 'commissioning' && bus.torque_state === 'off'
    && !bus.torque_off_pending && !bus.motion;
}
function livePose(now = performance.now()) {
  return Object.fromEntries(J.map(joint => {
    const row = liveServo(joint, now);
    if (Number.isFinite(row?.position_rad)) return [joint.key, row.position_rad];
    const saved = liveSaved(joint);
    const angle = saved && row ? saved.direction * (row.position_raw - saved.zero_raw) * K : 0;
    return [joint.key, Number.isFinite(angle) ? angle : 0];
  }));
}

const liveModel = {report: null, calibration: null, from: null, target: null, pose: null, startedAt: 0};
function liveModelPose(now) {
  const connected = liveConnected();
  if (!connected || liveFresh(now)) {
    if (!liveModel.target || liveModel.report !== live.report || liveModel.calibration !== live.calibration) {
      const target = livePose(now);
      liveModel.report = live.report;
      liveModel.calibration = live.calibration;
      if (!connected || !liveModel.pose || reduced) {
        liveModel.from = liveModel.target = liveModel.pose = target;
      } else if (J.some(joint => target[joint.key] !== liveModel.target[joint.key])) {
        liveModel.from = liveModel.pose;
        liveModel.target = target;
        liveModel.startedAt = now;
      }
    }
  }
  if (!liveModel.pose) return liveModel.pose = liveModel.target = livePose(now);
  if (liveModel.pose === liveModel.target) return liveModel.pose;
  const progress = Math.min(1, (now - liveModel.startedAt) / 65);
  if (progress === 1) return liveModel.pose = liveModel.target;
  if (progress === 0) return liveModel.pose;
  liveModel.pose = Object.fromEntries(J.map(({key}) => [
    key, liveModel.from[key] + (liveModel.target[key] - liveModel.from[key]) * progress,
  ]));
  return liveModel.pose;
}

function liveAccept(report, requestedAt = performance.now()) {
  if (report?.connected !== true) {
    live.report = null;
    live.calibration = null;
    live.feedbackError = '';
    live.step = 'connect';
    live.selected = null;
    live.visited.clear();
    return;
  }
  live.report = report;
  live.target = report.target || live.target;
  // Conservatively include the request's transit time in the sample age.
  live.receivedAt = requestedAt;
}

function liveRefresh() {
  if (live.pendingRead) return live.pendingRead;
  const wasConnected = liveConnected();
  const requestedAt = performance.now();
  live.pendingRead = (async () => {
    try {
      liveAccept(await liveApi('status', {}), requestedAt);
      live.feedbackError = '';
      live.readDue = 0;
      if (wasConnected !== liveConnected() && live.mode) render();
    } catch (error) {
      live.receivedAt = -Infinity;
      live.feedbackError = error.message;
      live.readDue = performance.now() + 1000;
    }
  })().finally(() => {
    live.pendingRead = null;
    const now = performance.now();
    if (live.mode && (now >= live.panelDue || liveFresh(now) !== live.feedbackVisible)) liveUpdate();
  });
  return live.pendingRead;
}

function liveRefreshCalibration() {
  if (live.pendingCalibration) return live.pendingCalibration;
  live.pendingCalibration = liveApi('calibration', {})
    .then(value => { if (liveConnected()) live.calibration = value; })
    .catch(() => { live.calibration = null; })
    .finally(() => {
      live.pendingCalibration = null;
      live.calibrationDue = performance.now() + 5000;
      if (live.mode) liveUpdate();
    });
  return live.pendingCalibration;
}

async function liveStart() {
  try {
    const session = await liveApi('session');
    if (session.mode !== 'real' || !session.token) throw new Error('未能建立实机会话');
    live.token = session.token;
    await liveRefresh();
    setInterval(() => {
      if (!live.mode || !liveConnected()) return;
      const now = performance.now();
      if (liveFresh(now) !== live.feedbackVisible) liveUpdate();
      if (live.busy || live.relaxing) return;
      if (now >= live.readDue) liveRefresh();
      if (now >= live.calibrationDue) liveRefreshCalibration();
    }, 100);
  } catch (error) {
    live.error = error.message;
  }
  if (live.mode) liveUpdate();
}

async function liveConnect(form, fingerprint) {
  if (!live.token || live.busy) return;
  const values = new FormData(form);
  const request = {
    target: String(values.get('target')).trim(), port: Number(values.get('port')),
    password: values.get('password'), socket: String(values.get('socket')).trim(), fingerprint,
  };
  Object.assign(live, {target: request.target, port: request.port, socket: request.socket, busy: true, error: '', notice: '正在连接 SSH 并读取 robotd…'});
  liveUpdate();
  try {
    await live.pendingRead;
    liveAccept(await liveApi('connect', request), -Infinity);
    live.calibration = null;
    live.feedbackError = '';
    live.readDue = 0;
    live.pendingKey = null;
    live.visited.clear();
    live.step = 'check';
    live.notice = '';
    form.elements.password.value = '';
    render();
    liveRefresh();
    liveRefreshCalibration();
  } catch (error) {
    live.pendingKey = error.fingerprint ? {fingerprint: error.fingerprint, target: request.target, port: request.port} : null;
    if (!live.pendingKey) form.elements.password.value = '';
    live.error = error.message;
    live.notice = '';
  } finally {
    live.busy = false;
    liveUpdate();
  }
}

async function liveOperate(payload, success) {
  const relax = payload.action === 'relax';
  if (!liveConnected() || (relax ? live.relaxing : live.busy || live.relaxing || !liveMotorReady())) return;
  const flag = relax ? 'relaxing' : 'busy';
  live[flag] = true;
  live.error = '';
  live.notice = '等待 robotd 回执…';
  liveUpdate();
  try {
    const result = await liveApi('command', payload);
    if (payload.action === 'capture' && result?.saved !== true) throw new Error('robotd 未确认写入标定');
    if (relax && result?.torque !== 'off') throw new Error('robotd 未确认已卸力');
    live.notice = success;
  } catch (error) {
    live.error = `${error.message}。请核对实机状态后再操作。`;
    live.notice = '';
  } finally {
    // Always read back after the command, including when its reply was lost.
    const readBack = async () => {
      await live.pendingRead;
      await liveRefresh();
    };
    const readCalibration = async () => {
      await live.pendingCalibration;
      await liveRefreshCalibration();
    };
    await Promise.all([
      readBack(),
      ...(['capture', 'verify-imu'].includes(payload.action) ? [readCalibration()] : []),
    ]);
    live[flag] = false;
    liveUpdate();
  }
}

function liveStep(next) {
  if (live.busy || live.relaxing) return;
  if (next !== 'connect' && !liveConnected()) {
    live.error = '请先连接机器人。';
    liveUpdate();
    return;
  }
  live.step = next;
  live.error = '';
  live.notice = '';
  render();
}

function liveSelect(key) {
  if (!BY[key] || live.selected === key || live.busy || live.relaxing) return;
  live.selected = key;
  render();
}

function liveConnectionPanel() {
  if (liveConnected()) return html`<h1>已连接机器人</h1><p class="say">${live.target}</p><div class="spring"></div><button class="btn main" data-a="liveStep" data-k="check">检查舵机</button><button class="link" data-a="liveDisconnect" data-idle>断开 SSH</button>`;
  return html`<h1>连接 MicroDuck</h1><p class="say">确认机器人主板已通电并完成启动，电脑和机器人在同一局域网，再填写机器人 SSH 账户。</p>
    <form id="live-connection" class="stack">
      <div class="field"><label for="live-target">SSH 地址</label><input name="target" id="live-target" value="${live.target}" autocomplete="username" autocapitalize="off" spellcheck="false" required></div>
      <div class="field"><label for="live-password">SSH 密码</label><input name="password" id="live-password" type="password" autocomplete="current-password" placeholder="已配置密钥时可留空"></div>
      <details><summary>SSH 端口和 robotd socket</summary><div class="stack live-options">
        <div class="field"><label for="live-port">SSH 端口</label><input name="port" id="live-port" type="number" min="1" max="65535" value="${live.port}" required></div>
        <div class="field"><label for="live-socket">robotd socket</label><input name="socket" id="live-socket" value="${live.socket}" required spellcheck="false"></div>
      </div></details>
      <div class="note warn" id="live-host-key" hidden><strong>核对 SSH 主机指纹</strong><code id="live-fingerprint"></code><p>与机器人的主机公钥指纹一致后再确认。</p><button class="btn" type="button" data-a="liveTrust" data-idle>指纹一致，继续连接</button></div>
      <button class="btn main" type="submit" data-live-connect disabled>连接并读取状态</button>
    </form>${aboutNote}`;
}

function liveJointList() {
  return html`<div class="bodymap">${ZONES.map(zone => html`<section class="z-${zone.k}"><h2>${zone.label}</h2>${inZone(zone.k).map(joint => html`<button class="sv ${live.selected === joint.key ? 'hot' : ''}" data-j="${joint.key}" aria-label="${joint.label} ${joint.id}"><b>${joint.id}</b><span>${SHORT[joint.key]}</span><em data-live-position="${joint.key}">—</em></button>`)}</section>`)}</div>`;
}

function liveCheckPanel() {
  const joint = BY[live.selected];
  return html`<h1>检查舵机</h1><p class="say" id="live-count">等候总线反馈</p>${liveJointList()}
    ${joint ? html`<div class="scard"><h2>${joint.label} · ${joint.id} 号</h2><p class="hint" id="live-detail"></p><button class="mini" data-a="liveStep" data-k="pose">查看这颗关节的标定</button></div>` : html`<p class="hint">点模型或列表中的关节，查看电压、温度和零位。</p>`}
    <div class="spring"></div><button class="btn main" data-a="liveStep" data-k="pose">继续摆零位</button>
    ${foot(html`<button class="link" data-a="liveRefresh" data-idle>刷新读数</button>`)}`;
}

function liveCapturePanel() {
  const joint = BY[live.selected];
  const saved = joint && liveSaved(joint);
  return html`<h1>摆零位</h1><p class="say">选择一颗关节，托稳并卸力，手动摆至已知角度后记录。其他关节的标定会保留。</p>${liveJointList()}
    ${joint ? html`<div class="scard"><h2>${joint.label} · ${joint.id} 号</h2><p class="hint" id="live-detail"></p>
      <form id="live-capture" class="stack">
        <div class="field"><label for="live-angle">当前已知角度 °（零位填 0）</label><input id="live-angle" name="angle" type="number" step="any" required></div>
        <div class="field"><label for="live-direction">转动方向</label><select id="live-direction" name="direction" required><option value="">按装配实测选择</option><option value="-1" ${saved?.direction === -1 ? 'selected' : ''}>−1</option><option value="1" ${saved?.direction === 1 ? 'selected' : ''}>+1</option></select></div>
        <div class="row"><div class="field"><label for="live-min">最小角 °</label><input id="live-min" name="min" type="number" step="any" value="${Number.isFinite(saved?.min_rad) ? saved.min_rad*R2D : ''}" required></div><div class="field"><label for="live-max">最大角 °</label><input id="live-max" name="max" type="number" step="any" value="${Number.isFinite(saved?.max_rad) ? saved.max_rad*R2D : ''}" required></div></div>
        <label class="support-check"><input name="supported" type="checkbox" required>已可靠支撑机身，舵机已卸力</label>
        <button class="btn main" type="submit" data-live-write>写入 ${joint.id} 号关节标定</button>
        <details><summary>舵机还没装上骨架</summary><label class="support-check"><input name="unassembled" type="checkbox">此舵机已脱离骨架并拆下舵盘</label><button type="button" class="btn" data-a="liveCenter" data-live-write>将此舵机转到 2048</button></details>
      </form></div>` : html`<p class="hint">从上方或 3D 模型点选一颗关节。</p>`}
    <p class="hint" id="live-ready"></p><div class="spring"></div><button class="btn" data-a="liveStep" data-k="imu">下一步 · 姿态传感器</button>`;
}

function liveUnavailable(title, details, next) {
  return html`<h1>${title}</h1>${details}<div class="spring"></div><button class="btn main" data-a="liveSkip" data-k="${next}">跳过，继续</button>`;
}

function livePanel() {
  let body;
  switch (live.step) {
    case 'connect': body = liveConnectionPanel(); break;
    case 'check': body = liveCheckPanel(); break;
    case 'pose': body = liveCapturePanel(); break;
    case 'imu': body = html`<h1>检查姿态传感器</h1><p class="say">将机身扶正，向前、向左轻倾，核对固件报告的重力方向。</p><pre class="live-data" id="live-imu">等候 IMU 反馈</pre>
      <form id="live-imu-form" class="stack"><label class="support-check"><input type="checkbox" name="confirmed" required>已撑稳机身、卸力，并按固件说明核对当前 IMU 安装方向</label><button class="btn main" type="submit" data-live-write>保存安装确认</button></form><p class="hint" id="live-ready"></p><div class="spring"></div><button class="btn" data-a="liveStep" data-k="sensors">下一步 · 摄像头与 ToF</button>`; break;
    case 'sensors': body = liveUnavailable('摄像头与 ToF', html`<section class="scard"><h2>摄像头</h2><p class="hint">本机后台尚未接入实机视频。</p></section><section class="scard"><h2>ToF 距离传感器</h2><p class="hint">本机后台尚未接入实机距离数据。</p></section>`, 'try'); break;
    case 'try': body = liveUnavailable('试站与局部修正', html`<p class="say">请使用固件自己的试站入口。在本机向导中，可以检查读数并重标有偏差的关节。</p><button class="btn" data-a="liveStep" data-k="pose">返回选择关节并重标</button><p class="hint">自动试站和角度微调试用尚未接入实机。</p>`, 'pad'); break;
    case 'pad': body = liveUnavailable('手柄', html`<p class="say">手柄配对由机器人固件处理。本机向导尚未接入配对和按键反馈。</p>`, 'done'); break;
    default: body = html`<h1>实机检查结果</h1><p class="say" id="live-results"></p><p class="hint">标定结果以机器人的回读为准。跳过的项目未进行实机验证。</p><button class="btn" data-a="liveStep" data-k="check">查看舵机反馈</button><button class="btn" data-a="liveStep" data-k="pose">复查关节标定</button>`;
  }
  return html`<p id="live-message" class="note" role="status" hidden></p>${body}`;
}

function liveRenderRail() {
  mount($('rail'), html`${STEP_KEYS.map((key, i) => {
    const current = live.step === key;
    const skipped = live.visited.has(key);
    const done = key === 'connect' ? liveConnected() : key === 'check' ? J.every(liveServo) : key === 'pose' ? J.every(liveSaved) : key === 'imu' && liveCalibration()?.imu_mount_verified === true;
    return html`<li class="${current ? 'now' : done ? 'done' : skipped ? 'skipped' : ''}"><button class="rb" data-a="liveStep" data-k="${key}" ${current ? new Safe('aria-current="step"') : ''} aria-label="${STEPS[i]}${skipped ? '，已跳过' : ''}"><i>${done && !current ? '✓' : skipped && !current ? '−' : i+1}</i><span>${STEPS[i]}${OPTIONAL.has(key) ? html`<small>可选</small>` : ''}</span></button></li>`;
  })}`);
}

function liveUpdateStage(fresh = liveFresh()) {
  if (!R) return;
  const stageTag = $('stageTag');
  const label = fresh ? '3D 实时关节反馈' : liveConnected() ? '3D 等待新鲜反馈' : '3D 关节参考';
  if (stageTag.textContent !== label) stageTag.textContent = label;
}

function liveUpdate() {
  if (!live.mode) return;
  const messageEl = $('live-message'), bus = live.report?.bus;
  if (!messageEl) return;
  const now = performance.now();
  live.panelDue = now + 250;
  const fresh = live.feedbackVisible = liveFresh(now);
  const error = live.error || live.feedbackError;
  messageEl.hidden = !(error || live.notice);
  messageEl.className = `note ${error ? 'bad' : ''}`;
  if (messageEl.textContent !== (error || live.notice)) messageEl.textContent = error || live.notice;
  liveUpdateStage(fresh);
  $('link').textContent = liveConnected() ? `${live.target} · ${bus.mode || '模式未知'}` : '';
  $('live-relax').disabled = !liveConnected() || live.relaxing;
  $('mode-toggle').disabled = live.busy || live.relaxing;
  const form = $('live-connection');
  if (form) {
    const key = live.pendingKey;
    $('live-host-key').hidden = !key;
    $('live-fingerprint').textContent = key?.fingerprint || '';
    form.querySelector('[data-live-connect]').disabled = !live.token || live.busy;
  }
  for (const button of document.querySelectorAll('[data-idle]')) button.disabled = live.busy || live.relaxing;
  for (const button of document.querySelectorAll('[data-live-write]')) button.disabled = live.busy || live.relaxing || !liveMotorReady();
  for (const element of document.querySelectorAll('[data-live-position]')) {
    const row = liveServo(BY[element.dataset.livePosition]);
    element.textContent = row ? row.position_raw : '—';
    element.closest('button').classList.toggle('ok', Boolean(row));
  }
  const count = $('live-count');
  if (count) {
    const online = J.filter(liveServo).length;
    count.textContent = online ? `${online} / ${J.length} 颗有实时反馈 · 扭矩 ${liveTorqueLabel()}`
      : '主板已连接，暂无有效舵机反馈。请检查舵机供电、总线接线和固件运行状态。';
  }
  const detail = $('live-detail');
  if (detail && live.selected) {
    const joint = BY[live.selected], saved = liveSaved(joint), row = liveServo(joint);
    detail.textContent = `${row ? `位置 ${row.position_raw} · ${row.voltage_v ?? row.volts ?? '—'} V · ${row.temperature_c ?? '—'} °C` : '等候有效位置反馈'} · ${saved ? `已保存零位 ${saved.zero_raw} / 方向 ${saved.direction}` : '尚未回读到标定'}`;
  }
  const imu = $('live-imu');
  if (imu) {
    const data = fresh && liveSample()?.imu;
    imu.textContent = data ? `IMU ${data.valid && data.ready ? '就绪' : '未就绪'} · 安装 ${data.mount_verified ? '已确认' : '待确认'}\n重力 XYZ：${data.gravity?.map(value => value.toFixed(3)).join(' / ') || '—'}` : bus?.mode === 'motion'
      ? '当前处于运动模式。核对 IMU 的重力方向及写入安装确认，请按固件说明进入 commissioning 标定模式。' : '等候有效 IMU 反馈';
  }
  if ($('live-ready')) $('live-ready').textContent = liveMotorReady() ? '标定模式 · 已确认卸力' : bus?.mode === 'motion'
    ? '运动模式可查看实时舵机反馈。写入前请按固件说明进入 commissioning 标定模式并确认卸力。'
    : '写入需要新鲜反馈、commissioning 标定模式及已确认卸力。';
  if ($('live-results')) $('live-results').textContent = `${J.filter(liveSaved).length} / ${J.length} 颗关节已保存标定。IMU 安装${liveCalibration()?.imu_mount_verified ? '已确认' : '待确认'}。`;
}

function liveRender() {
  liveRenderRail();
  $('dock').hidden = true;
  mount($('panel'), livePanel());
  liveUpdate();
  updateScene();
}

async function liveDisconnect() {
  if (live.busy || live.relaxing) return;
  live.busy = true;
  liveUpdate();
  try {
    await Promise.all([live.pendingRead, live.pendingCalibration]);
    liveAccept(await liveApi('disconnect', {}));
    live.notice = 'SSH 已断开。';
    live.error = '';
  } catch (error) {
    live.error = error.message;
  } finally {
    live.busy = false;
    if (live.mode) render();
  }
}

function liveAdvanced() {
  dlg.className = '';
  mount(dlg, html`<h2>实机诊断</h2><p>${live.report?.calibration_error || '最近一次 robotd 回读'}</p><pre class="live-data">${JSON.stringify(live.report || {}, null, 2)}</pre><div class="dlgbtns"><span></span><button class="btn main" id="closeDlg">关闭</button></div>`);
  dlg.showModal();
  $('closeDlg').onclick = () => dlg.close();
}

function liveConfirm(title, details, label, onConfirm) {
  dlg.className = 'small';
  mount(dlg, html`<h2>${title}</h2><p>${details}</p><div class="dlgbtns"><button class="btn" id="closeDlg">取消</button><button class="btn main" id="confirmLive">${label}</button></div>`);
  dlg.showModal();
  $('closeDlg').onclick = () => dlg.close();
  $('confirmLive').onclick = () => { dlg.close(); onConfirm(); };
}

function liveHandleClick(button) {
  switch (button?.dataset.a) {
    case 'liveStep': liveStep(button.dataset.k); break;
    case 'liveSkip': live.visited.add(live.step); liveStep(button.dataset.k); break;
    case 'liveRelax':
      liveConfirm('停止并卸力', '先托住机身，卸力后机身可能倒下。', '确认卸力',
        () => liveOperate({action: 'relax'}, 'robotd 已确认卸力。'));
      break;
    case 'liveDisconnect': liveDisconnect(); break;
    case 'liveRefresh': liveRefresh(); break;
    case 'liveTrust': {
      const form = $('live-connection'), key = live.pendingKey;
      if (!key || !form.reportValidity()) break;
      const matches = form.elements.target.value.trim() === key.target && Number(form.elements.port.value) === key.port;
      liveConnect(form, matches ? key.fingerprint : undefined);
      break;
    }
    case 'liveCenter': {
      const form = $('live-capture'), joint = BY[live.selected];
      if (!form.elements.supported.checked || !form.elements.unassembled.checked) {
        live.error = '请确认可靠支撑，并确认舵机已拆离骨架且取下舵盘。';
        liveUpdate();
        break;
      }
      liveConfirm(`回中 ${joint.id} 号舵机`, '此操作会让选中的舵机转到 2048。', '确认回中',
        () => liveOperate({action:'center-one', id:joint.id, supported:true, unassembled:true}, 'robotd 已完成回中。'));
      break;
    }
    case 'adv': liveAdvanced(); break;
    case 'about': openAbout(); break;
  }
}

function liveHandleSubmit(event) {
  if (!live.mode) return;
  event.preventDefault();
  const form = event.target;
  if (form.id === 'live-connection') {
    liveConnect(form);
  } else if (form.id === 'live-capture' && liveMotorReady()) {
    const values = new FormData(form), joint = BY[live.selected];
    const payload = {action:'capture', id:joint.id, supported:values.has('supported'),
      angle_deg:Number(values.get('angle')), direction:Number(values.get('direction')),
      min_deg:Number(values.get('min')), max_deg:Number(values.get('max'))};
    liveConfirm(`写入 ${joint.id} 号关节标定`, `请确认已将关节摆到 ${payload.angle_deg}°，方向和限位已经核对。`, '确认写入',
      () => liveOperate(payload, '标定已保存，已请求回读。'));
  } else if (form.id === 'live-imu-form' && liveMotorReady()) {
    liveOperate({action:'verify-imu', supported:true, confirmed:form.elements.confirmed.checked}, 'IMU 安装确认已保存。');
  }
}

function liveToggle() {
  if (live.busy || live.relaxing) return;
  if (!live.mode && isBusy()) return;
  if (!live.mode && tuneDirty()) {
    confirmLeave(() => { discardTune(); liveToggle(); });
    return;
  }
  live.mode = !live.mode;
  if (live.mode && S.pad.sub === 'search') {
    clearTimeout(padTimer);
    S.pad.sub = 'ready';
  }
  const password = $('live-password');
  if (password) password.value = '';
  live.pendingKey = null;
  render();
  if (live.mode && liveConnected()) {
    liveRefresh();
    liveRefreshCalibration();
  }
}
