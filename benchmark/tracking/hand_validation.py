"""Human skeleton inspection endpoint, separate from all training and controllers."""

import argparse
import asyncio
import json
import signal
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

import numpy as np

from benchmark.geort_support.input import canonical_points
from benchmark.geort_support.source import canonical_function
from benchmark.paths import ROOT
from benchmark.tracking.coordinate_transform import world_points
from benchmark.tracking.quest_cli import certificate_paths, host_ip
from benchmark.tracking.quest_receiver import QuestReceiver, tls_context
from benchmark.tracking.receiver_state import ReceiverState
from benchmark.tracking.recorder import HandRecorder


class InspectionServer(QuestReceiver):
    def __init__(self, state, samples):
        super().__init__(state)
        self.samples = samples.read_bytes()
        self.canonical = canonical_function()

    def geometry(self):
        self.state.expire(time.monotonic())
        result = {}
        for side in ("right", "left"):
            frame = self.state.latest.get(side)
            if frame is None:
                result[side] = {"valid": False, "points": None, "reason": "waiting"}
                continue
            try:
                points = self.canonical(world_points(frame))
                if not np.isfinite(points).all():
                    raise ValueError("Degenerate hand geometry")
                parity_error = (
                    float(np.max(np.abs(points - canonical_points(frame))))
                    if side == "right" and frame.tracking_valid
                    else None
                )
                result[side] = {
                    "valid": bool(frame.tracking_valid),
                    "points": points.tolist(),
                    "reason": self.state.reasons[side],
                    "canonical_adapter_difference_m": parity_error,
                    "sequence": frame.metadata.get("sequence"),
                    "tip_x_mm": (points[[4, 8, 12, 16, 20], 0] * 1000).tolist(),
                }
            except ValueError as error:
                result[side] = {"valid": False, "points": None, "reason": str(error)}
        return {
            "hands": result,
            "source_connected": self.state.session_id is not None,
            "source": "Quest WebXR",
            "reflection_applied": False,
        }

    def http_request(self, connection, request):
        path = urlsplit(request.path).path
        content_type = "application/json; charset=utf-8"
        if path in ("/", "/inspect"):
            body = Path(__file__).with_name("hand_validation.html").read_bytes()
            content_type = "text/html; charset=utf-8"
        elif path == "/validation.js":
            body = Path(__file__).with_name("hand_validation.js").read_bytes()
            content_type = "text/javascript; charset=utf-8"
        elif path == "/samples.json":
            body = self.samples
        elif path == "/validation.json":
            body = json.dumps(self.geometry(), allow_nan=False).encode()
        else:
            return super().http_request(connection, request)
        response = connection.respond(200, body.decode())
        del response.headers["Content-Type"]
        response.headers["Content-Type"] = content_type
        response.headers["Cache-Control"] = "no-store"
        return response


async def run(args):
    folder = Path(tempfile.mkdtemp(prefix="hand-validation-", dir=ROOT / "results"))
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, stop.set)
    with HandRecorder(folder / "diagnostic_quest_input.jsonl") as recorder:
        state = ReceiverState(recorder=recorder)
        server = InspectionServer(state, args.samples)
        monitor = InspectionServer(state, args.samples)
        cert, key = certificate_paths()
        try:
            await server.start("0.0.0.0", args.port, tls_context(cert, key))
            # Loopback-only PC view; hand capture must use the secure Quest URL.
            await monitor.start("127.0.0.1", args.monitor_port)
            manifest = {
                "quest_url": f"https://{host_ip()}:{args.port}/",
                "pc_url": f"http://127.0.0.1:{args.monitor_port}/inspect",
                "output": str(folder),
                "pid": __import__("os").getpid(),
                "source_samples": str(args.samples),
                "training_executed": False,
                "reflection_applied_to_source": False,
            }
            (folder / "session.json").write_text(json.dumps(manifest, indent=2) + "\n")
            print(json.dumps(manifest, indent=2), flush=True)
            await stop.wait()
        finally:
            await server.close()
            await monitor.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8028)
    parser.add_argument("--monitor-port", type=int, default=8029)
    parser.add_argument(
        "--samples", type=Path, default=ROOT / "results/hand_validation_public_20261018.json"
    )
    asyncio.run(run(parser.parse_args()))
