// Run the actual inline state machine without WebGL; UI is verified separately in a browser.
const {readFileSync}=require('node:fs');
const {join}=require('node:path');
const vm=require('node:vm');
const assert=require('node:assert/strict');
const {test}=require('node:test');
const page=readFileSync(join(__dirname,'../tool/calibration.html'),'utf8');
const inline=[...page.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)].at(-1)[1];
const source=inline.slice(0,inline.lastIndexOf('\nrender();\nrequestAnimationFrame(frame);'));
function setup(){
  const elements=new Map();
  const el=id=>{if(!elements.has(id))elements.set(id,{checked:false,textContent:'',className:'',style:{},replaceChildren(){},close(){},showModal(){},querySelector(){return null}});return elements.get(id)};
  const context=vm.createContext({console,DOMParser:class{parseFromString(){return{body:{childNodes:[]}}}},Math:Object.assign(Object.create(Math),{random:()=>.5}),performance:{now:()=>10000},setTimeout:()=>0,clearTimeout(){},setInterval:()=>0,clearInterval(){},matchMedia:()=>({matches:true}),document:{getElementById:el,addEventListener(){},querySelectorAll:()=>[]},window:{addEventListener(){}},requestAnimationFrame(){}});
  vm.runInContext(source,context);
  const run=code=>vm.runInContext(code,context);
  run(`render=()=>{};toast=()=>{};beep=()=>{};S.conn.up=true;S.ok={check:true,imu:true,try:true,pad:true};S.pad.sub='card';S.step='stand';S.standSub='confirm';S.locked={left:true,right:true,head:true};J.forEach(j=>{S.zero[j.key]=sim.zero[j.key];bus[j.key].u=bus[j.key].last=sim.zero[j.key]});`);
  return run;
}
test('camera and ToF share one optional step; mixed pass/skip continues without claiming both passed',()=>{
 const r=setup();r(`S.step='sensors';S.sens.camOk=true;act.skipDevice({dataset:{k:'tof'}})`);
 assert.equal(r(`STEP_KEYS.filter(k=>k==='sensors').length`),1);
 assert.equal(r(`isResolved('sensors')`),true);assert.equal(r(`isDone('sensors')`),false);
 r('act.sensorNext()');assert.equal(r('S.step'),'done');
 r(`act.reviewSensor();S.sens.tofOk=true;S.sens.skipped.tof=false;act.sensorNext()`);
 assert.equal(r(`isDone('sensors')`),true);assert.equal(r(`isSkipped('sensors')`),false);
});
test('skip all marks both skipped, keeps checks false and still requires standing confirmation',()=>{
 const r=setup();r(`S.ok.try=false;S.ok.pad=false;goStep('sensors');act.sensorSkip()`);
 assert.equal(r(`S.step`),'stand');assert.equal(r(`S.standSub`),'ready');
 assert.equal(r(`S.sens.skipped.camera&&S.sens.skipped.tof`),true);assert.equal(r(`isDone('sensors')`),false);
});
test('device retry preserves the other device result; skipping never satisfies motion prerequisites',()=>{
 const r=setup();r(`S.step='sensors';S.sens.camOk=true;S.sens.tofOk=true;act.sensRetry({dataset:{k:'tof'}})`);
 assert.equal(r(`S.sens.camOk`),true);assert.equal(r(`S.sens.tofOk`),false);
 r(`S.ok.imu=false;S.sens.skipped={camera:true,tof:true}`);
 assert.equal(r(`missing('try').includes('imu')`),true);
});
test('draft does not change calibration or simulated hardware; untested draft cannot save',()=>{
 const r=setup();r(`openTune('left_hip_yaw');globalThis.before=sim.q.left_hip_yaw;nudgeTrim(.5);saveTrim()`);
 assert.equal(r(`S.trim.left_hip_yaw||0`),0);assert.equal(r(`sim.q.left_hip_yaw===before`),true);
 assert.equal(r(`S.tune.draft`),.5);assert.equal(r(`S.ok.try`),true);
});
test('trial requires support; saving tested draft preserves all other joints and invalidates motion verification',()=>{
 const r=setup();r(`S.sens.skipped={camera:true,tof:true};openTune('right_hip_yaw');nudgeTrim(.5);trialTrim()`);
 assert.equal(r(`S.tune.moving`),false);
 r(`S.tune.supported=true;trialTrim()`);assert.equal(r(`S.tune.moving`),true);
 r(`S.tune.moving=false;S.tune.tested=true;S.tune.applied=.5;saveTrim()`);
 assert.equal(r(`S.trim.right_hip_yaw`),.5);assert.equal(r(`S.zero.right_hip_yaw`),2048);
 assert.equal(r(`effectiveZero('right_hip_yaw')`),2042);
 assert.equal(r(`effectiveZero('left_hip_yaw')`),2048);
 assert.equal(r(`S.ok.try||S.ok.pad`),false);assert.equal(r(`S.standSub`),'ready');
 assert.match(r(`allToml()`),/name = "right_hip_yaw"\nid = 10\nzero_raw = 2042/);
 assert.equal(r(`S.history.length`),1);
 r(`bus.right_hip_yaw.u=effectiveZero('right_hip_yaw')`);assert.equal(r(`Math.abs(calibratedAngle('right_hip_yaw'))`),0);
});
test('draft bounds and firmware limits prevent trial and save',()=>{
 const r=setup();r(`openTune('left_hip_yaw');for(let i=0;i<9;i++)nudgeTrim(.5)`);
 assert.equal(r(`S.tune.draft`),3);
 r(`S.zero.left_hip_yaw=10;S.tune.supported=true;trialTrim()`);
 assert.equal(r(`typeof trimProblem()`),'string');assert.equal(r(`S.tune.moving`),false);
});
test('discard restores the last saved configuration; re-editing after a trial requires another trial',()=>{
 const r=setup();r(`openTune('left_hip_yaw');nudgeTrim(.5);S.tune.tested=true;S.tune.applied=.5;nudgeTrim(.1);saveTrim()`);
 assert.equal(r(`S.trim.left_hip_yaw||0`),0);assert.equal(r(`S.tune.tested`),false);
 r(`discardTune()`);assert.equal(r(`S.tune`),null);assert.equal(r(`S.zero.left_hip_yaw`),2048);
});
test('single-joint recalibration does not erase 14 other calibrations or sensor results',()=>{
 const r=setup();r(`S.sens.camOk=true;S.trim.right_knee=.5;beginRecal('left_knee');S.recal.supported=true;bus.left_knee.u=bus.left_knee.last=2055;saveRecal()`);
 assert.equal(r(`S.zero.left_knee`),2055);assert.equal(r(`S.zero.right_knee`),2048);
 assert.equal(r(`S.trim.right_knee`),.5);assert.equal(r(`S.sens.camOk`),true);
 assert.equal(r(`S.ok.try`),false);assert.equal(r(`S.standSub`),'ready');assert.equal(r(`S.history.length`),1);
});
test('invalid recalibration can be cancelled without modifying the prior calibration',()=>{
 const r=setup();r(`beginRecal('head_yaw');S.recal.supported=true;bus.head_yaw.u=bus.head_yaw.last=20;saveRecal()`);
 assert.equal(r(`S.zero.head_yaw`),2048);assert.equal(r(`typeof S.recal.error`),'string');
 r(`act.recalCancel()`);assert.equal(r(`S.recal`),null);assert.equal(r(`S.standSub`),'pick');
});
test('restart clears optional skips and correction drafts',()=>{
 const r=setup();r(`S.trim.left_knee=.5;S.history=['old'];S.sens.skipped={camera:true,tof:true};openTune('left_knee');act.restart()`);
 assert.equal(r(`Object.keys(S.trim).length`),0);assert.equal(r(`S.history.length`),0);assert.equal(r(`S.tune`),null);
 assert.equal(r(`S.sens.skipped.camera||S.sens.skipped.tof`),false);
});

test('leaving an unsaved draft waits for a discard decision; busy trial prevents navigation',()=>{
 const r=setup();r(`openTune('left_hip_yaw');nudgeTrim(.5);goStep('sensors')`);
 assert.equal(r(`S.standSub`),'tune');assert.equal(r(`S.tune.draft`),.5);
 r(`$('discardDlg').onclick()`);assert.equal(r(`S.tune`),null);assert.equal(r(`S.step`),'sensors');
 r(`openTune('left_hip_yaw');S.tune.supported=true;trialTrim();goStep('sensors')`);
 assert.equal(r(`S.step`),'stand');assert.equal(r(`S.tune.moving`),true);
});
test('mixed device result is labelled partial skip; a later passing check clears it',()=>{
 const r=setup();r(`S.sens.camOk=true;S.sens.skipped.tof=true`);
 assert.equal(r(`skipLabel('sensors')`),'部分跳过');
 r(`S.step='sensors';S.sens.tofOk=true;S.sens.skipped.tof=false`);
 assert.equal(r(`isDone('sensors')`),true);assert.equal(r(`isSkipped('sensors')`),false);
});
