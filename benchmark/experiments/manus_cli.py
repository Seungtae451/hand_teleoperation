"""Phase 4 replay, synthetic demo, and combined Quest/MuJoCo live server."""

import argparse
import asyncio
import hashlib
import json
import signal
import tempfile
import time
from contextlib import ExitStack, nullcontext
from pathlib import Path

import numpy as np

from benchmark.experiments.manus_control import ManusController
from benchmark.experiments.manus_fixtures import pose_frame
from benchmark.experiments.manus_log import ManusLog
from benchmark.paths import ROOT, writable_output
from benchmark.retargeting.manus import DEFAULT_MANUS_CONFIG
from benchmark.simulation.robot_model import RobotModel
from benchmark.simulation.visualization import OffscreenRenderer, passive_viewer
from benchmark.tracking.quest_cli import certificate_paths, host_ip
from benchmark.tracking.quest_receiver import QuestReceiver, tls_context
from benchmark.tracking.receiver_state import ReceiverState
from benchmark.tracking.recorder import HandRecorder, replay_frames


def output_folder(path=None):
    if path is None:
        (ROOT / "results").mkdir(exist_ok=True)
        return Path(tempfile.mkdtemp(prefix="phase4-", dir=ROOT / "results"))
    path = writable_output(Path(path))
    path.mkdir(parents=True, exist_ok=False)
    return path


def open_visuals(stack, args, runner, folder):
    viewer = stack.enter_context(passive_viewer(runner.model, runner.data)) if args.viewer else None
    renderer = stack.enter_context(OffscreenRenderer(runner.model)) if args.video else None
    writer = None
    if args.video:
        import imageio.v2 as imageio

        writer = stack.enter_context(
            imageio.get_writer(str(folder / "manus.mp4"), fps=50, codec="libx264", quality=8)
        )
    return viewer, renderer, writer


def show(viewer, renderer, writer, runner):
    if renderer:
        writer.append_data(renderer.render(runner.data))
    if viewer:
        viewer.sync()
        return viewer.is_running()
    return True


def offline(args):
    folder = output_folder(args.output)
    robot = RobotModel()
    controller = ManusController(robot, args.config)
    frames = None
    digest = None
    if args.command == "replay":
        digest = hashlib.sha256(args.input.read_bytes()).hexdigest()
        frames = list(replay_frames(args.input, handedness="right"))
        if not frames:
            raise ValueError("Recording contains no right-hand frames")
        origin = frames[0].timestamp
        span = frames[-1].timestamp - origin
        if args.start < 0 or args.start > span:
            raise ValueError("Replay start is outside the recording")
        duration = min(args.duration, span - args.start)
    else:
        origin, duration = 0.0, args.duration
    count = max(1, int(duration * 50))
    cursor, current = 0, None
    errors, statuses, extrema = [], {}, []
    with ExitStack() as stack:
        logger = stack.enter_context(
            ManusLog(
                folder / "simulation.jsonl",
                controller,
                args.input if frames else "synthetic_human_poses",
                input_sha256=digest,
            )
        )
        viewer, renderer, writer = open_visuals(stack, args, controller.runner, folder)
        wall_start = time.monotonic()
        for index in range(count):
            relative = index / 50
            clock = origin + (args.start if frames else 0) + relative
            if frames:
                while cursor < len(frames) and frames[cursor].timestamp <= clock:
                    current = frames[cursor]
                    cursor += 1
            else:
                kind = ("open", "closed", "open", "pinch", "open")[
                    min(4, int(relative / duration * 5))
                ]
                current = pose_frame(kind, clock, index)
            with viewer.lock() if viewer else nullcontext():
                entry = controller.tick(current, clock)
            entry["input_time_s"] = clock
            entry["input_sequence"] = current.metadata.get("sequence") if current else None
            logger.write(entry)
            qactual = np.array(entry["simulation"]["q_actual"])
            errors.append(float(np.max(np.abs(qactual - controller.command))))
            extrema.append(controller.target.copy())
            statuses[controller.status] = statuses.get(controller.status, 0) + 1
            if not show(viewer, renderer, writer, controller.runner):
                break
            if viewer:
                time.sleep(max(0, wall_start + (index + 1) / 50 - time.monotonic()))
    summary = {
        "frames": index + 1,
        "source": str(args.input) if frames else "synthetic_human_poses",
        "control_status_counts": statuses,
        "max_dynamic_command_error_rad": max(errors),
        "retarget_joint_excursion_rad": np.ptp(extrema, axis=0).tolist(),
        "output": str(folder),
        "contact_enabled": False,
        "mapping": controller.retargeter.vendor.provenance,
        "note": "Geometric MANUS proxy baseline; not validated glove/hardware accuracy",
    }
    (folder / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


class LiveState(ReceiverState):
    """Reuse the Phase 3 server without changing its original classes or web source."""

    def __init__(self, controller, **kwargs):
        super().__init__(**kwargs)
        self.controller = controller

    def status(self, now):
        result = super().status(now)
        result["manus_simulation"] = {
            "status": self.controller.status,
            "q_command": self.controller.command.tolist(),
            "q_actual": self.controller.runner.data.qpos[
                self.controller.runner.robot.qpos_indices
            ].tolist(),
        }
        return result


class LiveServer(QuestReceiver):
    def http_request(self, connection, request):
        from urllib.parse import urlsplit

        if urlsplit(request.path).path == "/":
            # Serve a Phase 4-specific page; reuse existing capture JS/CSS unchanged.
            response = connection.respond(
                200, (Path(__file__).with_name("manus_live.html")).read_text()
            )
            del response.headers["Content-Type"]
            response.headers["Content-Type"] = "text/html; charset=utf-8"
            response.headers["Cache-Control"] = "no-store"
            return response
        return super().http_request(connection, request)


async def live(args):
    folder = output_folder(args.output)
    robot = RobotModel()
    controller = ManusController(robot, args.config)
    cert, key = certificate_paths()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    with ExitStack() as stack:
        recorder = stack.enter_context(HandRecorder(folder / "quest_input.jsonl"))
        logger = stack.enter_context(
            ManusLog(folder / "simulation.jsonl", controller, "live_webxr")
        )
        state = LiveState(controller, recorder=recorder)
        server = LiveServer(state)
        viewer, renderer, writer = open_visuals(stack, args, controller.runner, folder)
        try:
            await server.start("0.0.0.0", args.port, tls_context(cert, key))
            print(f"Quest Phase 4 URL: https://{host_ip()}:{args.port}/", flush=True)
            print(f"Output: {folder}", flush=True)
            started = time.monotonic()
            while not stop.is_set():
                now = time.monotonic()
                state.expire(now)
                frame = state.latest.get("right")
                with viewer.lock() if viewer else nullcontext():
                    entry = controller.tick(frame, now)
                entry["input_time_s"] = now
                logger.write(entry)
                if not show(viewer, renderer, writer, controller.runner):
                    break
                if args.duration is not None and now - started >= args.duration:
                    break
                await asyncio.sleep(max(0, 0.02 - (time.monotonic() - now)))
        finally:
            await server.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo")
    replay = sub.add_parser("replay")
    replay.add_argument("input", type=Path)
    replay.add_argument("--start", type=float, default=0)
    server = sub.add_parser("live")
    server.add_argument("--port", type=int, default=8024)
    for command in (demo, replay, server):
        command.add_argument("--duration", type=float, default=None if command is server else 10)
        command.add_argument("--viewer", action="store_true")
        command.add_argument("--video", action="store_true")
        command.add_argument("--output", type=Path)
        command.add_argument("--config", type=Path, default=DEFAULT_MANUS_CONFIG)
    args = parser.parse_args(argv)
    if args.duration is not None and (not np.isfinite(args.duration) or args.duration <= 0):
        parser.error("duration must be finite and positive")
    if args.command == "live":
        asyncio.run(live(args))
    else:
        offline(args)


if __name__ == "__main__":
    main()
