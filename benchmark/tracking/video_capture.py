"""Capture paired Quest tracking and a video-visible source clock without vendor edits."""

import argparse
import asyncio
import hashlib
import json
import math
import signal
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from websockets.datastructures import Headers
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Response

from benchmark.paths import ROOT
from benchmark.tracking.quest_cli import certificate_paths, host_ip
from benchmark.tracking.quest_receiver import QuestReceiver, tls_context
from benchmark.tracking.receiver_state import ReceiverState
from benchmark.tracking.recorder import HandRecorder

STAGES = [
    ("sync_start", "SYNC START - Hold right hand open"),
    ("open", "OPEN - Hold all fingers straight"),
    ("fist_slow", "FIST SLOW - Open, close, open slowly"),
    ("fist_hold", "FIST HOLD - Hold a comfortable fist"),
    ("index", "INDEX - Bend only index, then extend"),
    ("middle", "MIDDLE - Bend only middle, then extend"),
    ("ring", "RING - Bend only ring, then extend"),
    ("pinky", "PINKY - Bend only pinky, then extend"),
    ("thumb", "THUMB - Move thumb across palm, return"),
    ("pinch_index", "PINCH - Thumb to index, release, repeat"),
    ("pinch_middle", "PINCH - Thumb to middle, release, repeat"),
    ("pinch_ring", "PINCH - Thumb to ring, release, repeat"),
    ("pinch_pinky", "PINCH - Thumb to pinky, release, repeat"),
    ("spread", "SPREAD - Spread and gather fingers"),
    ("wrist", "WRIST - Rotate wrist with open fingers"),
    ("occlusion", "OCCLUSION - Hide right hand briefly, return"),
    ("free", "FREE - Mix open, fist and pinch"),
    ("sync_end", "SYNC END - Hold right hand open"),
]


def schedule(routine, seconds):
    rows = STAGES if routine == "benchmark" else [STAGES[0], STAGES[1], STAGES[-1]]
    return [{"id": key, "label": label, "seconds": seconds} for key, label in rows]


class CaptureReceiver(QuestReceiver):
    def __init__(self, state, folder, config):
        super().__init__(state)
        self.folder, self.config = folder, config
        self.marker_count = 0
        self.marker_stream = (folder / "markers.jsonl").open("x", buffering=1)

    def http_request(self, connection, request):
        path = urlsplit(request.path).path
        if path == "/capture-events":
            if request.headers.get("Origin") != f"https://{request.headers.get('Host')}":
                return connection.respond(403, "Use this receiver's capture page\n")
            return None
        resources = {
            "/": (Path(__file__).with_name("video_capture.html"), "text/html; charset=utf-8"),
            "/capture.js": (Path(__file__).with_name("video_capture.js"), "text/javascript"),
        }
        if path == "/capture-config.json":
            body, kind = json.dumps(self.config).encode(), "application/json"
        elif path in resources:
            file, kind = resources[path]
            body = file.read_bytes()
        else:
            return super().http_request(connection, request)
        return Response(
            200, "OK", Headers({"Content-Type": kind, "Cache-Control": "no-store"}), body
        )

    async def handler(self, connection):
        if urlsplit(connection.request.path).path != "/capture-events":
            return await super().handler(connection)
        try:
            async for message in connection:
                try:
                    marker = json.loads(message)
                    if not isinstance(marker, dict):
                        raise ValueError("Capture event must be an object")
                    if marker.get("event") not in ("stage", "clock", "routine_end", "xr_end"):
                        raise ValueError("Unknown capture event")
                    stamp = marker.get("source_time_ms")
                    if (
                        isinstance(stamp, bool)
                        or not isinstance(stamp, (float, int))
                        or not math.isfinite(stamp)
                    ):
                        raise ValueError("Invalid source clock")
                    row = {
                        "browser": marker,
                        "receive_time_s": time.monotonic(),
                        "source_session_id": self.state.session_id,
                    }
                    self.marker_stream.write(json.dumps(row, allow_nan=False) + "\n")
                    self.marker_count += 1
                    await connection.send(json.dumps({"type": "ack", "count": self.marker_count}))
                except (TypeError, ValueError) as exc:
                    await connection.close(code=1008, reason=str(exc)[:100])
                    break
        except ConnectionClosed:
            pass


async def serve_capture(args):
    cert, key = certificate_paths(args.cert, args.key)
    context = tls_context(cert, key)
    folder = args.output.resolve()
    folder.mkdir(parents=True, exist_ok=False)
    config = {
        "take_id": folder.name,
        "routine": args.routine,
        "stages": schedule(args.routine, args.stage_seconds),
        "video_capture": "Start/stop Quest system recording manually; not recorded by this server",
    }
    manifest = {
        **config,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "schema": "quest_paired_video_take_v1",
        "source_kind": "webxr_live",
        "input_policy": "Synchronous WebXR poses, not hand pose reconstructed from video",
        "hand_priority": "right",
        "split": "demonstration_not_training",
        "video_status": "not_attached",
        "hardware_capture_verified": False,
        "status": "recording",
    }
    manifest_path = folder / "take.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, stop.set)
    with HandRecorder(folder / "quest_input.jsonl") as recorder:
        state = ReceiverState(recorder=recorder)
        receiver = CaptureReceiver(state, folder, config)
        try:
            port = await receiver.start(args.bind, args.port, context)
            print(f"Quest / PC: https://{host_ip()}:{port}/", flush=True)
            print(f"Take: {folder}\nStart Quest SYSTEM VIDEO recording before WebXR.", flush=True)
            if args.duration:
                try:
                    await asyncio.wait_for(stop.wait(), args.duration)
                except asyncio.TimeoutError:
                    pass
            else:
                await stop.wait()
        except BaseException:
            manifest["status"] = "failed"
            raise
        finally:
            await receiver.close()
            receiver.marker_stream.close()
            manifest.update(
                status="failed" if manifest["status"] == "failed" else "closed",
                accepted_packets=state.accepted_packets,
                accepted_hand_frames=state.accepted_frames,
                marker_count=receiver.marker_count,
            )
            recorder.close()
            manifest["sha256"] = {
                name: hashlib.sha256((folder / name).read_bytes()).hexdigest()
                for name in ["quest_input.jsonl", "markers.jsonl"]
            }
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Saved: {folder}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT
        / "recordings"
        / ("video-take-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S-%fZ")),
    )
    parser.add_argument("--port", type=int, default=8036)
    parser.add_argument("--bind", default="0.0.0.0")
    parser.add_argument("--cert", type=Path)
    parser.add_argument("--key", type=Path)
    parser.add_argument("--routine", choices=["preflight", "benchmark"], default="benchmark")
    parser.add_argument("--stage-seconds", type=float, default=6)
    parser.add_argument("--duration", type=float)
    args = parser.parse_args()
    if not math.isfinite(args.stage_seconds) or args.stage_seconds < 2:
        parser.error("--stage-seconds must be finite and >=2")
    if args.duration is not None and (not math.isfinite(args.duration) or args.duration <= 0):
        parser.error("--duration must be finite and positive")
    asyncio.run(serve_capture(args))
