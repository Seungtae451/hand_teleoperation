#!/usr/bin/env python3
"""Live paired range experiment using existing Quest protocol and common controller."""

import argparse
import asyncio
import hashlib
import json
import signal
import sys
import tempfile
import time
from contextlib import ExitStack
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def run(args):
    import mujoco

    from benchmark.experiments.manus_control import ManusController
    from benchmark.geort_support.range_experiment import RangeRetargeter
    from benchmark.retargeting.geort import GeoRTRetargeter
    from benchmark.retargeting.manus import DEFAULT_MANUS_CONFIG
    from benchmark.simulation.robot_model import RobotModel
    from benchmark.simulation.visualization import passive_viewer
    from benchmark.tracking.quest_cli import certificate_paths, host_ip
    from benchmark.tracking.quest_receiver import QuestReceiver, tls_context
    from benchmark.tracking.receiver_state import ReceiverState
    from benchmark.tracking.recorder import HandRecorder

    folder = Path(tempfile.mkdtemp(prefix="live-geort-ranges-", dir=ROOT / "results"))
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, stop.set)
    with ExitStack() as stack:
        recorder = stack.enter_context(HandRecorder(folder / "quest_input.jsonl"))
        state = ReceiverState(recorder=recorder)
        receiver = QuestReceiver(state)
        workers = []
        models = {}
        for name in [args.condition]:
            manifest = json.loads((args.study / name / "manifest.json").read_text())
            assert (
                hashlib.sha256(Path(manifest["checkpoint"]).read_bytes()).hexdigest()
                == manifest["checkpoint_sha256"]
            )
            models[name] = manifest
            c = ManusController(RobotModel(), DEFAULT_MANUS_CONFIG)
            factory = RangeRetargeter if name == "restricted" else GeoRTRetargeter
            c.retargeter = factory(
                c.runner.robot, checkpoint=manifest["checkpoint"], config_path=manifest["config"]
            )
            viewer = (
                None
                if args.headless
                else stack.enter_context(passive_viewer(c.runner.model, c.runner.data))
            )
            stream = stack.enter_context((folder / f"{name}.jsonl").open("x", buffering=1))
            stream.write(
                json.dumps(
                    {
                        "event": "header",
                        "condition": name,
                        "model": manifest,
                        "experimental_range": True,
                        "control_hz": 50,
                        "speed_limit_rad_s": c.max_speed,
                    }
                )
                + "\n"
            )
            workers.append((name, c, viewer, stream))
        cert, key = certificate_paths()
        await receiver.start("0.0.0.0", args.port, tls_context(cert, key))
        session = {
            "pid": __import__("os").getpid(),
            "quest_url": f"https://{host_ip()}:{args.port}/",
            "models": models,
            "output": str(folder),
            "experimental_not_original_baseline": True,
        }
        (folder / "session.json").write_text(json.dumps(session, indent=2) + "\n")
        print(json.dumps(session, indent=2), flush=True)
        started = time.monotonic()
        try:
            while not stop.is_set():
                tick = time.monotonic()
                state.expire(tick)
                frame = state.latest.get("right")
                for name, c, viewer, stream in workers:
                    if viewer:
                        with viewer.lock():
                            entry = c.tick(frame, tick)
                    else:
                        entry = c.tick(frame, tick)
                    entry.update(
                        input_timestamp_s=frame.timestamp if frame else None,
                        input_sequence=frame.metadata.get("sequence") if frame else None,
                        input_time_s=tick,
                    )
                    stream.write(json.dumps(entry, allow_nan=False) + "\n")
                    if viewer:
                        title = (
                            "FULL RANGE CONTROL"
                            if name == "full"
                            else "RESTRICTED: NONTHUMB 3/4 = 0..90 DEG"
                        )
                        viewer.set_texts(
                            (
                                mujoco.mjtFontScale.mjFONTSCALE_150,
                                mujoco.mjtGridPos.mjGRID_TOPLEFT,
                                title,
                                c.status,
                            )
                        )
                        viewer.sync()
                        if not viewer.is_running():
                            stop.set()
                if args.duration is not None and tick - started >= args.duration:
                    stop.set()
                await asyncio.sleep(max(0, 0.02 - (time.monotonic() - tick)))
        finally:
            await receiver.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--study", type=Path, default=ROOT / "results/geort_range_study_20261018")
    p.add_argument("--condition", choices=["full", "restricted"], default="restricted")
    p.add_argument("--port", type=int, default=8034)
    p.add_argument("--headless", action="store_true")
    p.add_argument("--duration", type=float)
    args = p.parse_args()
    args.study = args.study.resolve()
    asyncio.run(run(args))
