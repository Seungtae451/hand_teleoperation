#!/usr/bin/env python3
"""Execute the actual capture/client JS in headless Chrome with mocked WebXR transport."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from benchmark.tracking.video_capture import schedule  # noqa: E402
from benchmark.tracking.webxr_protocol import protocol_description  # noqa: E402


def main():
    config = {"take_id": "SYNTHETIC_BROWSER_TEST", "stages": schedule("preflight", 3)}
    mock = r"""
const sentCapture = [];
window.fetch = async () => ({json: async () => CAPTURE_CONFIG});
window.WebSocket = class {
  static OPEN = 1;
  constructor(url) {this.url=url; this.readyState=1; this.bufferedAmount=0;
    setTimeout(()=>{this.onopen?.(); if (!url.includes('capture-events'))
      this.onmessage?.({data:JSON.stringify({type:'session',protocol:PROTOCOL})});},0);}
  send(text) {if(this.url.includes('capture-events'))sentCapture.push(JSON.parse(text));}
  close() {this.readyState=3;}
};
const fakeSession = {visibilityState:'visible', renderState:{}, inputSources:[],
  requestReferenceSpace:async()=>({addEventListener(){}}),
  addEventListener(){},requestAnimationFrame(){},
  updateRenderState(s){this.renderState=s;},end:async()=>{}};
Object.defineProperty(navigator,'xr',{value:{requestSession:async()=>fakeSession}});
WebGLRenderingContext.prototype.makeXRCompatible=async()=>{};
window.XRWebGLLayer = class {constructor(){this.framebuffer=null;}
  getViewport(){return {x:0,y:0,width:520,height:360};}};
"""
    exercise = r"""
setTimeout(async()=>{
  try {
    await startButton.onclick();
    const frame={session:fakeSession,getViewerPose:()=>({views:[{}]})};
    onXRFrame(0,frame);
    captureStart=performance.now()-9500;
    onXRFrame(9500,frame);
    if (!sentCapture.some(m=>m.event==='stage'&&m.stage==='sync_start'))
      throw Error('No start marker');
    if (!sentCapture.some(m=>m.event==='routine_end')) throw Error('No end marker');
    const message=document.getElementById('error').textContent;
    if (message) throw Error(message);
    const p=document.createElement('pre'); p.id='test-result';
    p.textContent='CAPTURE_BROWSER_PASS '+JSON.stringify(sentCapture); document.body.appendChild(p);
  } catch(e) {document.body.textContent='CAPTURE_BROWSER_FAIL '+e.stack;}
},200);
"""
    html = (ROOT / "benchmark/tracking/video_capture.html").read_text()
    html = html.replace('<script src="/client.js" defer></script>', "")
    html = html.replace('<script src="/capture.js" defer></script>', "")
    js = (
        "const CAPTURE_CONFIG="
        + json.dumps(config)
        + ";const PROTOCOL="
        + json.dumps(protocol_description())
        + ";"
        + mock
        + (ROOT / "benchmark/tracking/web/client.js").read_text()
        + (ROOT / "benchmark/tracking/video_capture.js").read_text()
        + exercise
    )
    with tempfile.TemporaryDirectory(prefix="quest-capture-browser-") as temp:
        path = Path(temp) / "test.html"
        path.write_text(html.replace("</html>", "<script>" + js + "</script></html>"))
        result = subprocess.run(
            [
                "google-chrome",
                "--headless",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--enable-unsafe-swiftshader",
                "--use-gl=angle",
                "--use-angle=swiftshader",
                "--no-first-run",
                "--no-default-browser-check",
                f"--user-data-dir={temp}/profile",
                "--virtual-time-budget=3000",
                "--dump-dom",
                path.as_uri(),
            ],
            capture_output=True,
            text=True,
            timeout=45,
        )
        if 'id="test-result">CAPTURE_BROWSER_PASS' not in result.stdout:
            print(result.stdout[-6000:])
            print(result.stderr[-2000:])
            raise SystemExit("Browser capture test failed")
    print("PASS: real client + capture extension + WebGL overlay; mocked WebXR, not hardware")


if __name__ == "__main__":
    main()
