/* Browser API mocks test transport and capture logic, not real headset tracking.
 * Optional standalone run: node scripts/test_webxr_client.cjs
 */
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const assert = require('node:assert/strict');

async function run() {
  const names = ['wrist', 'thumb-metacarpal', 'thumb-phalanx-proximal',
    'thumb-phalanx-distal', 'thumb-tip'];
  for (const finger of ['index', 'middle', 'ring', 'pinky']) {
    for (const part of ['metacarpal', 'phalanx-proximal', 'phalanx-intermediate', 'phalanx-distal', 'tip']) {
      names.push(`${finger}-finger-${part}`);
    }
  }
  const protocol = {joint_names: names};
  let now = 100;
  const sockets = [], elements = new Map(), requests = [], referenceListeners = new Map();
  const context2d = new Proxy({}, {get: (obj, name) => obj[name] || (() => {}), set: (obj, name, value) => {obj[name] = value; return true;}});
  const gl = {FRAMEBUFFER: 1, COLOR_BUFFER_BIT: 2, DEPTH_BUFFER_BIT: 4,
    bindFramebuffer() {}, clearColor() {}, clear() {}, async makeXRCompatible() {}};
  function element(id) {
    if (!elements.has(id)) elements.set(id, {disabled: true, textContent: '', width: 520, height: 360,
      getContext: type => type === '2d' ? context2d : gl});
    return elements.get(id);
  }
  class Socket {
    static OPEN = 1;
    constructor(url) {this.url = url; this.readyState = 1; this.bufferedAmount = 0; this.sent = []; sockets.push(this);}
    send(text) {this.sent.push(JSON.parse(text));}
    close() {this.readyState = 3;}
  }
  const session = {
    listeners: new Map(), visibilityState: 'visible', renderState: {}, inputSources: [],
    addEventListener(type, callback) {this.listeners.set(type, callback);},
    async requestReferenceSpace(name) {
      if (name === 'local-floor') throw new Error('Exercise local reference fallback');
      return {addEventListener: (type, callback) => referenceListeners.set(type, callback)};
    },
    updateRenderState(state) {Object.assign(this.renderState, state);},
    requestAnimationFrame(callback) {this.callback = callback;},
    async end() {this.listeners.get('end')?.();},
  };
  const ctx = vm.createContext({
    document: {getElementById: element}, window: {isSecureContext: true, addEventListener() {}},
    navigator: {xr: {async requestSession(mode, options) {requests.push({mode, options}); return session;}}},
    location: {host: 'quest.test:8023'}, WebSocket: Socket,
    performance: {now: () => now}, setInterval() {}, setTimeout() {},
    XRWebGLLayer: class {constructor() {this.framebuffer = {};}}
  });
  const filename = path.join(__dirname, '../benchmark/tracking/web/client.js');
  new vm.Script(fs.readFileSync(filename, 'utf8'), {filename}).runInContext(ctx);
  assert.equal(sockets.length, 1);
  assert.ok(sockets[0].url.endsWith('role=viewer'));
  sockets[0].onmessage({data: JSON.stringify({type: 'session', protocol})});
  assert.equal(element('start').disabled, false);
  const starting = element('start').onclick();
  for (let i = 0; i < 20 && sockets.length < 2; i++) await Promise.resolve();
  assert.equal(sockets.length, 2);
  const source = sockets[1];
  assert.ok(source.url.endsWith('role=source'));
  source.onmessage({data: JSON.stringify({type: 'session'})});
  await starting;
  assert.equal(requests[0].mode, 'immersive-ar');
  assert.ok(requests[0].options.requiredFeatures.includes('hand-tracking'));
  assert.equal(element('stop').disabled, false);
  for (const side of ['left', 'right']) session.inputSources.push({handedness: side,
    hand: new Map(names.map((name, index) => [name, {index}]))});
  let missing = false;
  const frame = {session, getJointPose(space) {
    if (missing && space.index === 8) return null;
    return {emulatedPosition: false, transform: {position: {x: space.index * .001, y: 1, z: -.5},
      orientation: {x: 0, y: 0, z: 0, w: 1}}};
  }};
  session.callback(101, frame);
  const first = source.sent.at(-1);
  assert.equal(first.type, 'frame');
  assert.equal(first.reference_space, 'local');
  assert.equal(first.hands.right.positions.length, 25);
  assert.equal(first.hands.left.rotations.length, 25);
  assert.deepEqual(first.joint_names, names);
  source.bufferedAmount = 100000; now += 20;
  const count = source.sent.length;
  session.callback(121, frame);
  assert.equal(source.sent.length, count);
  source.bufferedAmount = 0; now += 20; missing = true;
  session.callback(141, frame);
  assert.equal(source.sent.at(-1).hands.right.valid, false);
  referenceListeners.get('reset')();
  assert.equal(source.sent.at(-1).type, 'reference_reset');
  assert.equal(source.sent.at(-1).reference_epoch, 1);
  await session.end();
  assert.equal(source.sent.at(-1).type, 'tracking_stopped');
  assert.equal(source.readyState, 3);
  return {passed: true, kind: 'mock_browser_apis', checks: [
    'PC monitor does not acquire source', 'required hand-tracking feature',
    'local-floor fallback to local', '25 named joint positions and rotations',
    'backpressure drops queued input', 'missing joint invalidates hand',
    'reference reset event', 'tracking stop and WebSocket close']};
}

module.exports = run;
if (require.main === module) run().then(result => console.log(JSON.stringify(result, null, 2)))
  .catch(error => {console.error(error); process.exitCode = 1;});
