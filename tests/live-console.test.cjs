const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../backend/static/live.js'), 'utf8');
function fixture() {
  const requests = [];
  let connected = false;
  let saved = [];
  const joint = {id: 20, key: 'left_hip_yaw'};
  const report = () => connected ? {
    connected, target: 'radxa@fixture.local',
    bus: {mode:'commissioning', torque_state:'off', updated_at_us:1000,
      last_sample:{at_us:950, servos:[{id:20, joint:joint.key, position_raw:2050}]}},
    calibration: {calibration:{joints:saved}},
  } : {connected};
  const context = vm.createContext({
    K: Math.PI * 2 / 4096, J: [joint], render(){}, $(){return null}, setInterval(){},
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
      if (route === '/api/session') return {ok:true, json:async () => ({mode:'real', token:'test-session-ticket'})};
      return {ok:true, json:async () => ({result:report()})};
    },
    FormData: class {get(key) {return ({target:'radxa@fixture.local',port:'22',socket:'/run/robotd.sock',password:'local-fixture-example'})[key]}},
  });
  vm.runInContext(source, context);
  const run = input => vm.runInContext(input, context);
  run('liveUpdate = () => {}');
  return {run, requests};
}

test('default mode submits SSH credentials only to the local connect API and reads real joint feedback', async () => {
  const {run, requests} = fixture();
  assert.equal(run('live.mode'), true);
  await run('liveStart()');
  await run('liveConnect({elements:{password:{value:"local-fixture-example"}}})');
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
  const payload = `{action:'capture', id:20, supported:true, angle_deg:0, direction:1, min_deg:-17, max_deg:17}`;
  await run(`live.receivedAt=0; liveOperate(${payload}, '已保存')`);
  assert.equal(requests.filter(request => request.route === '/api/command').length, 0);
  await run(`liveRefresh();`);
  await run(`liveOperate(${payload}, '已保存')`);
  assert.deepEqual(requests.slice(-2).map(request => request.route), ['/api/command', '/api/status']);
  assert.equal(run('liveSaved(J[0]).zero_raw'), 2050);
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
