"use strict";
// Add a visible slate to the original client; no tracking sampling/coordinate changes.
let captureConfig, captureSocket, captureStart = null, captureStage = -1;
let captureLastClock = -Infinity, captureEnded = false, captureGL;
const captureBoot = crypto.randomUUID();
const captureStatus = document.getElementById("capture-status");
function captureEmit(event, stamp, extra = {}) {
  if (captureSocket?.readyState !== WebSocket.OPEN) {
    showError("녹화 표식 연결이 끊겼습니다. 이 take를 중단하고 다시 시작하세요.");
    xrSession?.end(); return;
  }
  captureSocket.send(JSON.stringify({event, source_time_ms: stamp, browser_id: captureBoot,
    last_sent_sequence: sequence - 1, reference_epoch: referenceEpoch, ...extra}));
}
function captureShader(gl, type, source) {
  const shader = gl.createShader(type); gl.shaderSource(shader, source); gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(shader));
  return shader;
}
function captureInitGL(gl) {
  const p = gl.createProgram();
  gl.attachShader(p, captureShader(gl, gl.VERTEX_SHADER,
    "attribute vec2 a; varying vec2 uv; void main(){uv=vec2((a.x+1.)*.5,1.-(a.y+1.)*.5);gl_Position=vec4(a.x*.11,a.y*.075,0.,1.);}"));
  gl.attachShader(p, captureShader(gl, gl.FRAGMENT_SHADER,
    "precision mediump float;varying vec2 uv;uniform sampler2D t;void main(){gl_FragColor=texture2D(t,uv);}"));
  gl.linkProgram(p);
  if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p));
  const buffer = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1,-1,1,-1,-1,1,1,1]), gl.STATIC_DRAW);
  const texture = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, texture);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  const canvas = document.createElement("canvas"); canvas.width = 1024; canvas.height = 640;
  return {p, buffer, texture, canvas, ctx: canvas.getContext("2d"), attribute: gl.getAttribLocation(p,"a")};
}
function captureWrappedText(ctx, text, y) {
  let line = "";
  for (const word of text.split(/\s+/)) {
    const candidate = line ? `${line} ${word}` : word;
    if (line && ctx.measureText(candidate).width > 880) {
      ctx.fillText(line, 512, y); y += 60; line = word;
    } else { line = candidate; }
  }
  if (line) ctx.fillText(line, 512, y);
}
const captureOriginalFrame = onXRFrame;
onXRFrame = function(timestamp, frame) {
  captureOriginalFrame(timestamp, frame);
  const now = performance.now();
  if (captureStart === null) captureStart = now;
  const elapsed = (now - captureStart) / 1000;
  let end = 0, stage = -1;
  for (let i = 0; i < captureConfig.stages.length; i++) {
    end += captureConfig.stages[i].seconds;
    if (elapsed < end) { stage = i; break; }
  }
  if (stage !== captureStage) {
    captureStage = stage;
    if (stage >= 0) captureEmit("stage", now, {stage: captureConfig.stages[stage].id});
  }
  if (stage < 0 && !captureEnded) {
    captureEmit("routine_end", now); captureEnded = true;
  }
  if (now - captureLastClock >= 1000) {
    captureEmit("clock", now, {stage: stage >= 0 ? captureConfig.stages[stage].id : "done"});
    captureLastClock = now;
  }
  try {
    const gl = document.getElementById("xr-canvas").getContext("webgl");
    captureGL ||= captureInitGL(gl);
    const s = captureGL, ctx = s.ctx;
    const flash = stage >= 0 && captureConfig.stages[stage].id.startsWith("sync") && Math.floor(elapsed * 2) % 2 === 0;
    ctx.fillStyle = flash ? "#ffffff" : "#111827"; ctx.fillRect(0, 0, 1024, 640);
    ctx.fillStyle = flash ? "#000000" : "#ffffff";
    ctx.textAlign = "center";
    ctx.font = "bold 64px monospace";
    ctx.fillText(`SRC ${now.toFixed(1)} ms`, 512, 90);
    const label = stage >= 0 ? captureConfig.stages[stage].label : "DONE - Stop tracking and system video";
    const split = label.indexOf(" - ");
    ctx.font = "bold 70px sans-serif";
    ctx.fillText(split >= 0 ? label.slice(0, split) : label, 512, 190);
    ctx.font = "48px sans-serif";
    captureWrappedText(ctx, split >= 0 ? label.slice(split + 3) : "", 280);
    ctx.font = "bold 54px monospace";
    ctx.fillText(`${stage >= 0 ? Math.ceil(end-elapsed) : 0}s left`, 512, 460);
    ctx.font = "34px monospace";
    ctx.fillText(`RIGHT HAND | SEQ ${sequence - 1}`, 512, 525);
    ctx.font = "28px monospace";
    ctx.fillText(captureConfig.take_id.slice(-36), 512, 590);
    gl.bindFramebuffer(gl.FRAMEBUFFER, frame.session.renderState.baseLayer.framebuffer);
    gl.useProgram(s.p); gl.bindBuffer(gl.ARRAY_BUFFER, s.buffer);
    gl.enableVertexAttribArray(s.attribute); gl.vertexAttribPointer(s.attribute, 2, gl.FLOAT, false, 0, 0);
    gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, s.texture);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, s.canvas);
    gl.disable(gl.DEPTH_TEST); gl.disable(gl.CULL_FACE); gl.disable(gl.BLEND);
    const pose = frame.getViewerPose(xrReference);
    for (const view of pose?.views || []) {
      const v = frame.session.renderState.baseLayer.getViewport(view);
      gl.viewport(v.x, v.y, v.width, v.height); gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    }
    captureStatus.textContent = `SRC ${now.toFixed(1)} ms · ${stage >= 0 ? captureConfig.stages[stage].label : "DONE"}`;
  } catch (error) { showError(error); xrSession?.end(); }
};
const captureOriginalStart = startButton.onclick;
startButton.onclick = async () => {
  if (!captureConfig || captureSocket?.readyState !== WebSocket.OPEN) {
    showError("녹화 안내 연결을 기다리거나 페이지를 새로 고침하세요."); return;
  }
  captureStart = null; captureStage = -1; captureEnded = false; captureLastClock = -Infinity;
  await captureOriginalStart();
  xrSession?.addEventListener("end", () => captureEmit("xr_end", performance.now()));
};
fetch("/capture-config.json").then(r => r.json()).then(config => {
  captureConfig = config;
  captureSocket = new WebSocket(`wss://${location.host}/capture-events`);
  captureSocket.onopen = () => { captureStatus.textContent = `${config.take_id} · 시스템 영상 녹화 후 시작하세요`; };
  captureSocket.onclose = () => {
    captureStatus.textContent = "녹화 표식 연결 끊김 · 새 take로 다시 시작하세요";
    if (xrSession) xrSession.end();
  };
}).catch(showError);
