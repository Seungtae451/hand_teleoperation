"""Phase 3 commands, kept separate from the existing Phase 2 CLI."""

import argparse
import asyncio
import json
import os
import signal
import socket
import ssl
from datetime import datetime, timezone
from pathlib import Path

from benchmark.paths import ROOT, writable_output
from benchmark.tracking.quest_receiver import QuestReceiver, tls_context
from benchmark.tracking.receiver_state import ReceiverState
from benchmark.tracking.recorder import HandRecorder, frame_to_dict, replay_frames
from benchmark.tracking.synthetic import synthetic_packet


def certificate_paths(cert=None, key=None):
    """Explicit/env paths, then project TLS, then the reference user config path.

    No import of Isaac/TeleVuer and no modification of existing certificates.
    """
    cert = cert or os.environ.get("XR_TELEOP_CERT")
    key = key or os.environ.get("XR_TELEOP_KEY")
    if bool(cert) != bool(key):
        raise ValueError("Provide both --cert and --key, or both XR_TELEOP_CERT/XR_TELEOP_KEY")
    project_tls = ROOT / "results/phase3_tls"
    base = (
        project_tls
        if all((project_tls / p).is_file() for p in ("cert.pem", "key.pem"))
        else Path.home() / ".config/xr_teleoperate"
    )
    pair = (
        (Path(cert).expanduser(), Path(key).expanduser())
        if cert
        else (base / "cert.pem", base / "key.pem")
    )
    if not all(p.is_file() for p in pair):
        raise FileNotFoundError("TLS certificate/key not found; provide --cert and --key")
    return pair


def host_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 9))
            return probe.getsockname()[0]
    except OSError:
        return "127.0.0.1"


async def serve_command(args):
    if args.cert or args.key:
        if not (args.cert and args.key):
            raise ValueError("--cert and --key must be supplied together")
    cert, key = certificate_paths(args.cert, args.key)
    context = tls_context(cert, key)
    path = args.record or ROOT / "recordings" / (
        "quest-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S-%fZ") + ".jsonl"
    )
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    with HandRecorder(path, target_frame=args.frame, timeout=args.timeout) as recorder:
        state = ReceiverState(timeout=args.timeout, target_frame=args.frame, recorder=recorder)
        receiver = QuestReceiver(state)
        try:
            port = await receiver.start(args.bind, args.port, context)
            advertised = args.host_ip or (host_ip() if args.bind == "0.0.0.0" else args.bind)
            print(f"Quest / PC URL: https://{advertised}:{port}/", flush=True)
            print(f"Recording: {recorder.path}", flush=True)
            print("Phase 3: hand input only; no robot commands are generated.", flush=True)
            if args.duration is not None:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=args.duration)
                except asyncio.TimeoutError:
                    pass
            else:
                await stop.wait()
        finally:
            await receiver.close()


def synthetic_command(args):
    if args.frames < 4 or args.fps <= 0:
        raise ValueError("Use at least four frames and a positive fps")
    with HandRecorder(
        args.output, source_kind="synthetic_webxr", target_frame=args.frame
    ) as recorder:
        state = ReceiverState(target_frame=args.frame, recorder=recorder)
        state.connect("synthetic-session", 1000)
        for i in range(args.frames):
            seconds = i / args.fps
            lost = args.frames // 3 <= i < args.frames // 3 + max(1, args.frames // 12)
            state.accept(
                synthetic_packet(i, seconds, lost=lost), "synthetic-session", 1000 + seconds
            )
        state.expire(1000 + args.frames / args.fps + 1)
        state.disconnect(1000 + args.frames / args.fps + 1.1)
    print(
        json.dumps(
            {
                "recording": str(args.output),
                "source": "synthetic_webxr",
                "valid_hand_frames": state.accepted_frames,
                "includes_tracking_loss": True,
            },
            indent=2,
        )
    )


def replay_command(args):
    output = None
    if args.output:
        if args.output.resolve() == args.input.resolve():
            raise ValueError("Replay output must not overwrite its input")
        path = writable_output(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        output = path.open("x")
    count = valid = 0
    sides = set()
    try:
        for frame in replay_frames(
            args.input, realtime=args.realtime, speed=args.speed, handedness=args.hand
        ):
            count += 1
            valid += frame.tracking_valid
            sides.add(frame.handedness)
            if output:
                output.write(json.dumps(frame_to_dict(frame), allow_nan=False) + "\n")
    finally:
        if output:
            output.close()
    print(
        json.dumps(
            {
                "frames": count,
                "valid": valid,
                "invalid": count - valid,
                "hands": sorted(sides),
                "timestamps": "preserved receiver monotonic seconds",
            },
            indent=2,
        )
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    server = sub.add_parser(
        "serve", help="Serve the Quest WebXR page and receive hands via HTTPS/WSS"
    )
    server.add_argument("--bind", default="0.0.0.0")
    server.add_argument("--host-ip", help="Advertised LAN IP; does not change the bind address")
    server.add_argument(
        "--port", type=int, default=8023, help="Separate from the humanoid server's 8022"
    )
    server.add_argument("--cert", type=Path)
    server.add_argument("--key", type=Path)
    server.add_argument("--timeout", type=float, default=0.25)
    server.add_argument("--record", type=Path)
    server.add_argument("--duration", type=float, help="Stop automatically after this many seconds")
    fixture = sub.add_parser(
        "synthetic", help="Create an explicitly synthetic hand-input recording"
    )
    fixture.add_argument("--output", type=Path, required=True)
    fixture.add_argument("--frames", type=int, default=120)
    fixture.add_argument("--fps", type=int, default=60)
    for command in (server, fixture):
        command.add_argument(
            "--frame", choices=("wrist_rh", "palm_rh", "world_rh"), default="wrist_rh"
        )
    replay = sub.add_parser(
        "replay", help="Replay common HandFrames, preserving invalid/lost events"
    )
    replay.add_argument("input", type=Path)
    replay.add_argument("--output", type=Path, help="Export canonical frames as JSONL")
    replay.add_argument("--hand", choices=("left", "right"))
    replay.add_argument("--realtime", action="store_true")
    replay.add_argument("--speed", type=float, default=1.0)
    doctor = sub.add_parser("doctor", help="Check TLS discovery and available local ports")
    doctor.add_argument("--cert", type=Path)
    doctor.add_argument("--key", type=Path)
    args = parser.parse_args(argv)
    if args.command == "serve":
        if args.duration is not None and (not 0 < args.duration < float("inf")):
            parser.error("--duration must be positive and finite")
        asyncio.run(serve_command(args))
    elif args.command == "synthetic":
        synthetic_command(args)
    elif args.command == "replay":
        replay_command(args)
    elif args.command == "doctor":
        cert, key = certificate_paths(args.cert, args.key)
        tls_context(cert, key)
        print(
            json.dumps(
                {
                    "certificate": str(cert),
                    "tls_chain_loads": True,
                    "host_ip": host_ip(),
                    "recommended_port": 8023,
                    "webxr_device_test": "pending actual Quest connection",
                    "ssl": ssl.OPENSSL_VERSION,
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
