"""Live fan-out without changing vendor algorithms or the common controller."""

import argparse
import asyncio
import hashlib
import json
import math
import os
import signal
import tempfile
import time
from contextlib import ExitStack
from functools import partial
from pathlib import Path
from urllib.parse import urlsplit

from benchmark.paths import ROOT, writable_output
from benchmark.tracking.quest_receiver import QuestReceiver, tls_context
from benchmark.tracking.receiver_state import ReceiverState
from benchmark.tracking.recorder import HandRecorder, frame_from_dict, frame_to_dict

DEFAULT_MODEL = ROOT / (
    "results/geort_dg5f_workspace/training-f9nel4wo/checkpoint/dg5f_right_geort_2026-10-18_03-29-30"
)
METHODS = ("manus", "anydex", "wuji", "geort")
MODEL_CONDITIONS = ("official_3498", "quest_1000", "quest_3498", "quest_10000")


def controller_for(method, checkpoint, config, profile=None):
    if method in MODEL_CONDITIONS:
        method = "geort"
    from benchmark.experiments.offline_benchmark import OfflineController
    from benchmark.retargeting import registry
    from benchmark.simulation.robot_model import RobotModel

    if method == "wuji":
        from benchmark.retargeting.wuji import WujiRetargeter

        registry.register("wuji", WujiRetargeter)
    elif method == "geort":
        from benchmark.retargeting.geort import GeoRTRetargeter

        registry.register(
            "geort", partial(GeoRTRetargeter, checkpoint=checkpoint, config_path=config)
        )
    controller = OfflineController(RobotModel(), method)
    if profile:
        from benchmark.retargeting.tesollo_calibration import (
            CalibratedAnyDex,
            CalibratedWuji,
            load_profile,
            sha256,
        )

        robot = controller.runner.robot
        document = load_profile(profile, robot)
        if method in ("anydex", "wuji"):
            factory = CalibratedAnyDex if method == "anydex" else CalibratedWuji
            controller.retargeter = factory(robot, profile=profile)
        else:
            retargeter = controller.retargeter
            provenance = getattr(retargeter, "provenance", None) or retargeter.vendor.provenance
            retargeter.provenance = {
                **provenance,
                "robot_profile_sha256": sha256(profile),
                "calibration_procedure": document["methods"][method]["procedure"],
            }
    return controller


async def worker(args):
    from websockets.asyncio.client import connect

    from benchmark.simulation.visualization import passive_viewer

    controller = controller_for(args.worker, args.checkpoint, args.config, args.robot_profile)
    folder = args.output
    retargeter = controller.retargeter
    provenance = getattr(retargeter, "provenance", None)
    if provenance is None:
        provenance = retargeter.vendor.provenance
    latest = [None]
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, stop.set)
    with ExitStack() as stack:
        log = stack.enter_context((folder / f"{args.worker}.jsonl").open("x", buffering=1))
        log.write(
            json.dumps(
                {
                    "event": "header",
                    "method": args.worker,
                    "upstream": provenance,
                    "config": retargeter.config,
                    "control_hz": 50,
                    "physics_timestep_s": 0.002,
                    "max_speed_rad_s": controller.max_speed,
                    "timeout_s": controller.timeout,
                    "contact_enabled": False,
                    "note": "Live latest-frame consumption; "
                    "scheduling can differ between processes",
                }
            )
            + "\n"
        )
        viewer = (
            None
            if args.headless
            else stack.enter_context(
                passive_viewer(controller.runner.model, controller.runner.data)
            )
        )
        async with connect(args.feed_url, max_size=65536, compression=None) as socket:
            await socket.send(json.dumps({"method": args.worker, "status": "READY"}))

            async def receive():
                async for message in socket:
                    data = json.loads(message)
                    latest[0] = frame_from_dict(data) if data is not None else None

            reader = asyncio.create_task(receive())
            last_status = 0
            try:
                while not reader.done() and not stop.is_set():
                    started = time.monotonic()
                    frame = latest[0]
                    if viewer:
                        with viewer.lock():
                            entry = controller.tick(frame, started)
                    else:
                        entry = controller.tick(frame, started)
                    entry.update(
                        input_time_s=started,
                        input_sequence=(frame.metadata.get("sequence") if frame else None),
                        input_timestamp_s=frame.timestamp if frame else None,
                    )
                    log.write(json.dumps(entry, allow_nan=False) + "\n")
                    if viewer:
                        import mujoco

                        viewer.set_texts(
                            (
                                mujoco.mjtFontScale.mjFONTSCALE_150,
                                mujoco.mjtGridPos.mjGRID_TOPLEFT,
                                args.worker.upper(),
                                controller.status,
                            )
                        )
                        viewer.sync()
                        if not viewer.is_running():
                            break
                    if started - last_status >= 0.2:
                        await socket.send(
                            json.dumps(
                                {
                                    "method": args.worker,
                                    "status": controller.status,
                                    "input_sequence": entry["input_sequence"],
                                    "input_age_s": controller.input_age,
                                }
                            )
                        )
                        last_status = started
                    await asyncio.sleep(max(0, 0.02 - (time.monotonic() - started)))
                if reader.done():
                    reader.result()
            finally:
                reader.cancel()
                await asyncio.gather(reader, return_exceptions=True)


class LiveState(ReceiverState):
    def __init__(self, methods, **kwargs):
        super().__init__(**kwargs)
        self.workers = {name: {"status": "STARTING"} for name in methods}

    def status(self, now):
        return {**super().status(now), "retargeting": self.workers}


class LiveServer(QuestReceiver):
    def http_request(self, connection, request):
        if urlsplit(request.path).path == "/":
            page = (
                "geort_models_live.html"
                if getattr(self.state, "models", None)
                else "live_retargeting.html"
            )
            response = connection.respond(200, Path(__file__).with_name(page).read_text())
            response.headers["Content-Type"] = "text/html; charset=utf-8"
            response.headers["Cache-Control"] = "no-store"
            return response
        return super().http_request(connection, request)


async def serve(args):
    from websockets.asyncio.server import serve as ws_serve
    from websockets.exceptions import ConnectionClosed

    from benchmark.tracking.quest_cli import certificate_paths, host_ip

    folder = (
        writable_output(args.output)
        if args.output
        else Path(tempfile.mkdtemp(prefix="live-retargeting-", dir=ROOT / "results"))
    )
    if args.output:
        folder.mkdir(parents=True, exist_ok=False)
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, stop.set)
    clients, processes = set(), []
    with ExitStack() as stack:
        recorder = stack.enter_context(HandRecorder(folder / "quest_input.jsonl"))
        state = LiveState(args.methods, recorder=recorder)
        state.models = args.models
        receiver = LiveServer(state)

        async def feed(socket):
            name = None
            try:
                hello = json.loads(await asyncio.wait_for(socket.recv(), 120))
                name = hello["method"]
                if name not in state.workers:
                    raise ValueError("Unexpected worker")
                state.workers[name] = hello
                clients.add(socket)
                frame = state.latest.get("right")
                await socket.send(json.dumps(frame_to_dict(frame) if frame else None))
                print(f"{name.upper()}: READY", flush=True)
                async for message in socket:
                    state.workers[name] = json.loads(message)
            except ConnectionClosed:
                pass
            finally:
                clients.discard(socket)
                if name in state.workers:
                    state.workers[name] = {"status": "CLOSED"}

        async with ws_serve(feed, "127.0.0.1", 0, compression=None) as hub:
            port = hub.sockets[0].getsockname()[1]
            cert, key = certificate_paths()
            await receiver.start("0.0.0.0", args.port, tls_context(cert, key))
            try:
                for method in args.methods:
                    executable = ROOT / (
                        ".venv-geort/bin/python"
                        if method == "geort" or method in MODEL_CONDITIONS
                        else ".venv/bin/python"
                    )
                    selected = args.models.get(method, {})
                    command = [
                        str(executable),
                        str(ROOT / "scripts/run_live_retargeting.py"),
                        "--worker",
                        method,
                        "--feed-url",
                        f"ws://127.0.0.1:{port}",
                        "--output",
                        str(folder),
                        "--checkpoint",
                        str(selected.get("checkpoint", args.checkpoint)),
                        "--config",
                        str(selected.get("config", args.config)),
                    ]
                    if args.headless:
                        command.append("--headless")
                    if args.robot_profile:
                        command.extend(["--robot-profile", str(args.robot_profile.resolve())])
                    console = stack.enter_context((folder / f"{method}_console.txt").open("x"))
                    processes.append(
                        (
                            method,
                            await asyncio.create_subprocess_exec(
                                *command, stdout=console, stderr=asyncio.subprocess.STDOUT, cwd=ROOT
                            ),
                        )
                    )
                manifest = {
                    "methods": args.methods,
                    "output": str(folder),
                    "pid": os.getpid(),
                    "port": args.port,
                    "checkpoint": str(args.checkpoint),
                    "config": str(args.config),
                    "robot_profile": str(args.robot_profile) if args.robot_profile else None,
                    "geort_study": str(args.geort_study) if args.geort_study else None,
                    "models": args.models,
                }
                (folder / "session.json").write_text(json.dumps(manifest, indent=2) + "\n")
                print(f"Quest URL: https://{host_ip()}:{args.port}/\nOutput: {folder}", flush=True)
                started = time.monotonic()
                last_key = object()
                while not stop.is_set():
                    now = time.monotonic()
                    state.expire(now)
                    frame = state.latest.get("right")
                    key = None if frame is None else (frame.timestamp, frame.tracking_valid)
                    if key != last_key or len(clients) < len(args.methods):
                        payload = json.dumps(
                            frame_to_dict(frame) if frame else None, allow_nan=False
                        )
                        for socket in list(clients):
                            try:
                                await asyncio.wait_for(socket.send(payload), 0.1)
                            except (ConnectionClosed, asyncio.TimeoutError):
                                clients.discard(socket)
                        last_key = key
                    for method, process in processes:
                        if process.returncode is not None:
                            print(
                                f"{method} closed (exit {process.returncode}); "
                                f"see {folder}/{method}_console.txt",
                                flush=True,
                            )
                            stop.set()
                    if args.duration and now - started >= args.duration:
                        stop.set()
                    await asyncio.sleep(max(0, 0.02 - (time.monotonic() - now)))
            finally:
                await receiver.close()
                for _, process in processes:
                    if process.returncode is None:
                        process.terminate()
                for _, process in processes:
                    try:
                        await asyncio.wait_for(process.wait(), 10)
                    except asyncio.TimeoutError:
                        process.kill()
                        await process.wait()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--methods", nargs="+", choices=METHODS + MODEL_CONDITIONS)
    parser.add_argument("--geort-study", type=Path, help="four trained GeoRT model catalog JSON")
    parser.add_argument("--port", type=int, default=8026)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_MODEL / "last.pth")
    parser.add_argument("--config", type=Path, default=DEFAULT_MODEL / "config.json")
    parser.add_argument("--robot-profile", type=Path, help="frozen robot calibration profile")
    parser.add_argument("--duration", type=float)
    parser.add_argument("--headless", action="store_true", help="diagnostic: no viewer windows")
    parser.add_argument("--worker", choices=METHODS + MODEL_CONDITIONS, help=argparse.SUPPRESS)
    parser.add_argument("--feed-url", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    args.models = {}
    if args.geort_study:
        if args.robot_profile:
            parser.error("GeoRT model comparison uses the unchanged trained input convention")
        catalog = json.loads(args.geort_study.read_text())
        args.methods = args.methods or list(MODEL_CONDITIONS)
        for name in args.methods:
            if name not in MODEL_CONDITIONS:
                parser.error("--geort-study requires model condition names")
            entry = catalog[name]
            checkpoint, config = Path(entry["checkpoint"]), Path(entry["config"])
            if entry["status"] != "completed" or not checkpoint.is_file() or not config.is_file():
                parser.error(f"Incomplete model: {name}")
            digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
            if digest != entry["checkpoint_sha256"]:
                parser.error(f"Checkpoint hash mismatch: {name}")
            args.models[name] = {
                "checkpoint": str(checkpoint),
                "config": str(config),
                "checkpoint_sha256": digest,
                "frames": entry["input_frames"],
            }
    else:
        args.methods = args.methods or list(METHODS)
        if not args.worker and any(name in MODEL_CONDITIONS for name in args.methods):
            parser.error("Model condition selection requires --geort-study")
    if len(set(args.methods)) != len(args.methods):
        parser.error("duplicate methods")
    if args.duration is not None and (not math.isfinite(args.duration) or args.duration <= 0):
        parser.error("duration must be positive and finite")
    if (
        args.worker in ("geort", *MODEL_CONDITIONS) or (not args.worker and "geort" in args.methods)
    ) and (not args.checkpoint.is_file() or not args.config.is_file()):
        parser.error("trained GeoRT checkpoint and config are required")
    asyncio.run(worker(args) if args.worker else serve(args))
