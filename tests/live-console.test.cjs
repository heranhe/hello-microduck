const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../backend/static/live.js'), 'utf8');
function fixture({calibrationResponse, statusResponse, sessionResponse} = {}) {
  const requests = [];
  let connected = false;
  let saved = [];
  let now = 1000;
  let tick, interval;
  const joint = {id: 20, key: 'left_hip_yaw'};
  const report = () => connected ? {
    connected, target: 'radxa@fixture.local',
    bus: {mode:'commissioning', torque_state:'off', updated_at_us:1000,
      last_sample:{at_us:950, servos:[{id:20, joint:joint.key, position_raw:2050}]}},
  } : {connected};
  const context = vm.createContext({
    K: Math.PI * 2 / 4096, J: [joint], reduced:false, render(){}, $(){return null}, AbortSignal,
    performance:{now:() => now}, setInterval(callback, ms){tick = callback; interval = ms},
    isBusy(){return false}, tuneDirty(){return false}, S:{pad:{sub:'ready'}},
    fetch: async (route, options) => {
      const body = options.body && JSON.parse(options.body);
      requests.push({route, body, token:options.headers?.['X-Session-Token']});
      if (route === '/api/command') {
        assert.equal(body.action, 'capture');
        saved = [{id:20, calibrated:true, zero_raw:2050, direction:1}];
        return {ok:true, json:async () => ({result:{saved:true}})};
      }
      if (route === '/api/connect') connected = true;
      if (route === '/api/calibration') {
        if (calibrationResponse) await calibrationResponse;
        return {ok:true, json:async () => ({result:{calibration:{joints:saved}}})};
      }
      if (route === '/api/session') return sessionResponse?.() || {ok:true, json:async () => ({mode:'real', token:'test-session-ticket'})};
      if (route === '/api/status') {
        const response = statusResponse?.();
        if (response) return response;
      }
      return {ok:true, json:async () => ({result:report()})};
    },
    FormData: class {get(key) {return ({target:'radxa@fixture.local',port:'22',socket:'/run/robotd.sock',password:'local-fixture-example'})[key]}},
  });
  vm.runInContext(source, context);
  const run = input => vm.runInContext(input, context);
  run('globalThis.updatePanel = liveUpdate');
  run('liveUpdate = () => { live.feedbackVisible = liveFresh(); }');
  return {run, requests, advance(ms){now += ms}, tick(){tick()}, interval:() => interval};
}

test('connection status and the header action follow login, feedback loss and confirmed disconnect', async () => {
  let response;
  const {run, requests, advance, tick} = fixture({statusResponse: () => response});
  run(`
    globalThis.nodes = Object.fromEntries(['live-message', 'link', 'link-state', 'link-detail', 'live-relax', 'mode-toggle',
      'live-connection-action', 'live-password'].map(id => [id, {classList:{toggle(){}}}]));
    nodes['live-target'] = {value:live.target};
    nodes['live-password'].focus = () => { nodes['live-password'].focused = true; };
    $ = id => nodes[id];
    globalThis.document = {querySelectorAll: () => []};
    globalThis.R = null;
    globalThis.aboutNote = '';
    globalThis.html = String.raw;
    liveUpdate = updatePanel;
    render = () => { globalThis.panelMarkup = liveConnectionPanel(); liveUpdate(); };
    render();
  `);
  assert.equal(run(`nodes['live-connection-action'].textContent`), '登录');
  await run('liveStart()');
  await run('liveConnect({elements:{password:{value:"local-fixture-example"}}})');
  await run('Promise.all([live.pendingRead, live.pendingCalibration])');
  run(`nodes['live-count'] = {}; liveUpdate()`);
  assert.match(run(`nodes['live-count'].textContent`), /1 \/ 1 颗有实时反馈/);
  advance(501);
  run('liveUpdate()');
  assert.match(run(`nodes['live-count'].textContent`), /实时读数暂不可用/);
  run(`liveStep('connect')`);
  assert.match(run('panelMarkup'), /已连接机器人/);
  assert.equal(run(`nodes['live-connection-action'].textContent`), '断开');

  response = {ok:false, json:async () => ({error:'反馈通道暂不可用'})};
  await run('liveRefresh()');
  assert.doesNotMatch(run('panelMarkup'), /已连接机器人/);
  assert.equal(run(`nodes['link-state'].textContent`), '等待机器人响应');

  response = {ok:true, json:async () => ({result:{connected:false, reason:'SSH 已断开。'}})};
  advance(1000);
  tick();
  await run('live.pendingRead');
  assert.equal(run('liveConnected()'), false);
  assert.match(run('panelMarkup'), /连接 MicroDuck/);
  assert.equal(run(`nodes['link-state'].textContent`), 'SSH 已断开');
  assert.equal(run(`nodes['live-connection-action'].textContent`), '重连');
  assert.equal(run(`nodes['live-relax'].disabled`), true);
  run(`liveHandleClick({dataset:{a:'liveConnectionAction'}})`);
  assert.equal(run(`nodes['live-password'].focused`), true);
  assert.equal(requests.filter(request => request.route === '/api/connect').length, 1);
});

test('starting the local session can be retried after a network failure', async () => {
  let attempts = 0;
  const {run, interval, requests} = fixture({sessionResponse: () => {
    if (++attempts === 1) throw new TypeError('Failed to fetch');
  }});
  await run('liveStart()');
  assert.equal(run('live.sessionFailed'), true);
  assert.equal(run('live.token'), '');
  await run('Promise.all([liveStart(), liveStart()])');
  assert.equal(run('live.sessionFailed'), false);
  assert.ok(run('live.token'));
  assert.equal(interval(), 100);
  assert.deepEqual(requests.map(request => request.route), ['/api/session', '/api/session', '/api/status']);
});

test('default mode submits SSH credentials only to the local connect API and reads real joint feedback', async () => {
  const {run, requests} = fixture();
  assert.equal(run('live.mode'), true);
  await run('liveStart()');
  await run('liveConnect({elements:{password:{value:"local-fixture-example"}}})');
  await run('live.pendingRead');
  assert.equal(run('live.step'), 'check');
  assert.equal(run('liveServo(J[0]).position_raw'), 2050);
  assert.deepEqual(requests.find(request => request.route === '/api/connect'), {
    route:'/api/connect', token:'test-session-ticket', body:{target:'radxa@fixture.local', port:22, socket:'/run/robotd.sock', password:'local-fixture-example'},
  });
  assert.equal(run('Object.hasOwn(live, "password")'), false);
});

test('real capture is blocked on stale feedback and reads back the saved joint after an accepted write', async () => {
  const {run, requests} = fixture();
  await run('liveStart()');
  await run('liveConnect({elements:{password:{value:"local-fixture-example"}}})');
  await run('Promise.all([live.pendingRead, live.pendingCalibration])');
  const payload = `{action:'capture', id:20, supported:true, angle_deg:0, direction:1, min_deg:-17, max_deg:17}`;
  await run(`live.receivedAt=0; liveOperate(${payload}, '已保存')`);
  assert.equal(requests.filter(request => request.route === '/api/command').length, 0);
  await run(`liveRefresh();`);
  await run(`liveOperate(${payload}, '已保存')`);
  assert.deepEqual(requests.slice(-3).map(request => request.route), ['/api/command', '/api/status', '/api/calibration']);
  assert.equal(run('liveSaved(J[0]).zero_raw'), 2050);
});

test('100 ms feedback polling continues while calibration is pending', async () => {
  let finishCalibration;
  const calibrationResponse = new Promise(resolve => {finishCalibration = resolve;});
  const {run, requests, tick, advance, interval} = fixture({calibrationResponse});
  await run('liveStart()');
  await run('liveConnect({elements:{password:{value:"local-fixture-example"}}})');
  await run('live.pendingRead');
  assert.equal(interval(), 100);
  for (let i = 0; i < 10; i++) {
    advance(100);
    tick();
    tick();
    await run('live.pendingRead');
  }
  assert.equal(requests.filter(request => request.route === '/api/status').length, 12);
  assert.equal(requests.filter(request => request.route === '/api/calibration').length, 1);
  assert.equal(run('liveServo(J[0]).position_raw'), 2050);
  finishCalibration();
  await run('live.pendingCalibration');
});

test('the model settles within 65 ms and holds the last pose when feedback expires', () => {
  const {run, advance} = fixture();
  run(`globalThis.motion = position => ({connected:true, bus:{mode:'motion', phase:'control', native:{
    sample_age_ms:20, joints:[{id:20, name:J[0].key, position_raw:2013, position_rad:position}]
  }}});
  liveModelPose(performance.now())`);
  run('liveAccept(motion(1))');
  assert.equal(run('liveModelPose(performance.now())[J[0].key]'), 0);
  advance(32.5);
  assert.equal(run('liveModelPose(performance.now())[J[0].key]'), 0.5);
  advance(32.5);
  assert.equal(run('liveModelPose(performance.now())[J[0].key]'), 1);
  advance(416);
  assert.equal(run('liveFresh()'), false);
  assert.equal(run('liveModelPose(performance.now())[J[0].key]'), 1);
  run('liveAccept(motion(2), performance.now() - 600)');
  assert.equal(run('liveModelPose(performance.now())[J[0].key]'), 1);
  run('liveAccept({connected:false})');
  assert.equal(run('liveModelPose(performance.now())[J[0].key]'), 0);
});

test('demo switch stays in the same UI, clears the unsubmitted password and performs no SSH calls', () => {
  const {run, requests} = fixture();
  run(`globalThis.input = {value:'unsubmitted-test-value'}; $ = id => id === 'live-password' ? input : null; liveToggle()`);
  assert.equal(run('live.mode'), false);
  assert.equal(run('input.value'), '');
  run('liveToggle()');
  assert.equal(run('live.mode'), true);
  assert.deepEqual(requests, []);
});

test('motion mode reads native joint positions without a commissioning last_sample', () => {
  const {run} = fixture();
  run(`liveAccept({connected:true, bus:{mode:'motion', phase:'control', fresh_sample:true, native:{
    sample_age_ms:20, torque_state_confirmed:true, joints:[
      {id:20, name:J[0].key, position_raw:2013, position_rad:0.125, volts:7.3, temperature_c:29, feedback_fresh:true, sample_age_ms:20}
    ]
  }}})`);
  assert.equal(run('liveServo(J[0]).position_raw'), 2013);
  assert.equal(run('liveServo(J[0]).volts'), 7.3);
  assert.equal(run('livePose()[J[0].key]'), 0.125);
  assert.equal(run('liveTorqueLabel()'), '已上力');
  assert.equal(run('liveMotorReady()'), false);

  run('live.report.bus.native.joints[0].feedback_fresh = false');
  assert.equal(run('liveServo(J[0])'), null);
  run('live.report.bus.native.joints[0].feedback_fresh = true; live.report.bus.native.joints[0].sample_age_ms = 501');
  assert.equal(run('liveServo(J[0])'), null);
  run('live.report.bus.native.joints[0].sample_age_ms = 20; live.report.bus.fresh_sample = false');
  assert.equal(run('liveServo(J[0])'), null);
  run('live.report.bus.fresh_sample = true; live.report.bus.native.sample_age_ms = null');
  assert.equal(run('liveServo(J[0])'), null);
});
