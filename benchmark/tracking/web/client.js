"use strict";
// WebXR source and PC monitor share this page; opening a monitor never takes source ownership.
const byId = id => document.getElementById(id);
const startButton = byId("start"), stopButton = byId("stop");
let viewerSocket, sourceSocket, xrSession, xrReference, protocol;
let sequence = 0, referenceEpoch = 0, referenceName = "local", lastSent = -Infinity;
let lastStatusReceived = 0;
const diagnostics = message => { byId("diagnostics").textContent = message; };
const showError = error => { byId("error").textContent = String(error.message || error); };
const dot = (a, b) => a.reduce((sum, x, i) => sum + x * b[i], 0);
const subtract = (a, b) => a.map((x, i) => x - b[i]);
function normalize(a) { const length = Math.hypot(...a); return length > 1e-6 ? a.map(x => x / length) : null; }

function drawHand(side, hand) {
  const canvas = byId(side), ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  byId(side + "-status").textContent = hand.valid ? "추적 중" : (hand.reason || "대기");
  if (!hand.frame) return;
  const points = hand.frame.joint_positions;
  const z = normalize(subtract(points[9], points[0]));
  if (!z) return;
  let y = subtract(points[5], points[17]);
  y = normalize(y.map((x, i) => x - dot(y, z) * z[i]));
  if (!y) return;
  const projected = points.map(p => { const v = subtract(p, points[0]); return [dot(v, y), dot(v, z)]; });
  const extent = Math.max(.10, ...projected.flat().map(Math.abs)), scale = 255 / extent;
  const pixels = projected.map(([x, y]) => [260 - x * scale, 325 - y * scale]);
  const colors = ["#fcad87", "#81c9ef", "#9cdbab", "#e6cf83", "#c6a1e6"];
  ctx.globalAlpha = hand.valid ? 1 : .22;
  for (let finger = 0; finger < 5; finger++) {
    const chain = [0, ...Array.from({length: 4}, (_, j) => 1 + finger * 4 + j)];
    ctx.strokeStyle = colors[finger]; ctx.lineWidth = 4; ctx.beginPath();
    chain.forEach((index, i) => { const p = pixels[index]; i ? ctx.lineTo(...p) : ctx.moveTo(...p); });
    ctx.stroke();
    for (const index of chain.slice(1)) { ctx.beginPath(); ctx.arc(...pixels[index], 5, 0, 2 * Math.PI); ctx.fillStyle = colors[finger]; ctx.fill(); }
  }
  ctx.globalAlpha = 1;
}

function connectMonitor() {
  viewerSocket = new WebSocket(`wss://${location.host}/ws?role=viewer`);
  viewerSocket.onmessage = event => {
    const message = JSON.parse(event.data);
    if (message.type === "session") {
      protocol = message.protocol;
      startButton.disabled = !window.isSecureContext || !navigator.xr;
      startButton.textContent = navigator.xr ? "Quest 손 추적 시작" : "PC 수신 모니터";
      diagnostics(`보안 연결: ${window.isSecureContext}\nWebXR: ${!!navigator.xr}\n손 관절: ${protocol.joint_names.length}`);
    }
    if (message.type !== "status") return;
    lastStatusReceived = performance.now();
    byId("connection").textContent = message.source_connected ? "Quest 연결됨" : "Quest 연결 대기 · PC 모니터 연결됨";
    byId("counts").textContent = `수신 ${message.accepted_packets} 프레임 · 유효한 손 데이터 ${message.accepted_hand_frames}개 · 거부 ${message.rejected_packets}개`;
    byId("recording").textContent = message.recording ? `기록 중: ${message.recording}` : "기록 파일 미지정";
    drawHand("left", message.hands.left); drawHand("right", message.hands.right);
  };
  viewerSocket.onclose = () => { byId("connection").textContent = "서버 연결 끊김 · 재연결 중"; startButton.disabled = true; setTimeout(connectMonitor, 1000); };
  viewerSocket.onerror = () => { byId("connection").textContent = "HTTPS 인증서와 서버 주소를 확인하세요."; };
}

function connectSource() {
  return new Promise((resolve, reject) => {
    const socket = new WebSocket(`wss://${location.host}/ws?role=source`);
    sourceSocket = socket;
    socket.onmessage = event => {
      const message = JSON.parse(event.data);
      if (message.type === "session") resolve();
      if (message.type === "error") { showError(message.message); reject(new Error(message.message)); }
    };
    socket.onerror = () => reject(new Error("손 추적 전송 연결 실패"));
    socket.onclose = () => {
      reject(new Error("손 추적 전송 연결이 종료되었습니다."));
      if (sourceSocket === socket && xrSession) { showError("전송 연결이 끊겨 손 추적을 종료합니다."); xrSession.end(); }
    };
  });
}

function controlPacket(type) {
  if (sourceSocket?.readyState === WebSocket.OPEN) sourceSocket.send(JSON.stringify({
    version: 1, type, sequence: sequence++, source_time_ms: performance.now(),
    reference_space: referenceName, reference_epoch: referenceEpoch
  }));
}

function sampleHand(source, frame) {
  if (!source?.hand) return {valid: false, reason: "hand_not_available"};
  const positions = [], rotations = [];
  for (const name of protocol.joint_names) {
    const space = source.hand.get(name);
    const pose = space ? frame.getJointPose(space, xrReference) : null;
    if (!pose || pose.emulatedPosition) return {valid: false, reason: "joint_pose_unavailable"};
    const p = pose.transform.position, q = pose.transform.orientation;
    positions.push([p.x, p.y, p.z]); rotations.push([q.x, q.y, q.z, q.w]);
  }
  return {valid: true, emulated: false, positions, rotations};
}

function onXRFrame(timestamp, frame) {
  const session = frame.session;
  session.requestAnimationFrame(onXRFrame);
  const gl = byId("xr-canvas").getContext("webgl");
  gl.bindFramebuffer(gl.FRAMEBUFFER, session.renderState.baseLayer.framebuffer);
  gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
  const now = performance.now();
  if (!sourceSocket || sourceSocket.readyState !== WebSocket.OPEN || now - lastSent < 1000 / 60) return;
  if (sourceSocket.bufferedAmount > 65536) return; // Don't accumulate old frames.
  const hands = {};
  for (const side of ["left", "right"]) {
    const source = Array.from(session.inputSources).find(s => s.handedness === side && s.hand);
    hands[side] = session.visibilityState === "visible" ? sampleHand(source, frame) : {valid: false, reason: "session_not_visible"};
  }
  sourceSocket.send(JSON.stringify({version: 1, type: "frame", sequence: sequence++,
    source_time_ms: performance.now(), xr_frame_time_ms: timestamp,
    reference_space: referenceName, reference_epoch: referenceEpoch,
    joint_names: protocol.joint_names, hands}));
  lastSent = now;
}

startButton.onclick = async () => {
  if (xrSession) return;
  startButton.disabled = true; showError("");
  try {
    // Request immediately within the click, before network awaits consume activation.
    xrSession = await navigator.xr.requestSession("immersive-ar", {
      requiredFeatures: ["hand-tracking"], optionalFeatures: ["local-floor"]
    });
    xrSession.addEventListener("end", () => {
      controlPacket("tracking_stopped"); xrSession = null;
      sourceSocket?.close(); sourceSocket = null;
      stopButton.disabled = true; startButton.disabled = false;
    });
    referenceName = "local-floor";
    try { xrReference = await xrSession.requestReferenceSpace(referenceName); }
    catch { referenceName = "local"; xrReference = await xrSession.requestReferenceSpace(referenceName); }
    sequence = 0; referenceEpoch = 0; lastSent = -Infinity;
    xrReference.addEventListener("reset", () => { referenceEpoch++; controlPacket("reference_reset"); });
    const gl = byId("xr-canvas").getContext("webgl", {xrCompatible: true, alpha: true});
    if (!gl) throw new Error("WebGL을 사용할 수 없습니다.");
    if (gl.makeXRCompatible) await gl.makeXRCompatible();
    xrSession.updateRenderState({baseLayer: new XRWebGLLayer(xrSession, gl, {alpha: true})});
    await connectSource();
    stopButton.disabled = false;
    xrSession.requestAnimationFrame(onXRFrame);
  } catch (error) {
    showError(error);
    if (xrSession) await xrSession.end();
    sourceSocket?.close(); sourceSocket = null;
    startButton.disabled = !navigator.xr;
  }
};
stopButton.onclick = () => xrSession?.end();
window.addEventListener("pagehide", () => { controlPacket("tracking_stopped"); sourceSocket?.close(); });
window.addEventListener("error", event => showError(event.message));
setInterval(() => {
  if (lastStatusReceived && performance.now() - lastStatusReceived > 1000) {
    byId("connection").textContent = "상태 수신 중단 · 표시값을 현재 추적으로 사용하지 마세요.";
    for (const side of ["left", "right"]) byId(side + "-status").textContent = "연결 끊김";
  }
}, 250);
connectMonitor();
