#!/usr/bin/env python3
"""Integration check: replay native recorded packets through TLS, test all workers and loss."""

import argparse
import asyncio
import json
import signal
import ssl
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def validate(args):
    from websockets.asyncio.client import connect

    folder = Path(tempfile.mkdtemp(prefix="live-validation-", dir=ROOT / "results"))
    session = folder / "session"
    context = ssl._create_unverified_context()  # Local self-signed development certificate.
    base_url = f"https://127.0.0.1:{args.port}"

    def status():
        with urllib.request.urlopen(base_url + "/status", context=context, timeout=2) as response:
            return json.load(response)

    packets = []
    with args.input.open() as source:
        for line in source:
            event = json.loads(line)
            if event.get("event") == "native_packet":
                packet = event["packet"]
                if packet["type"] == "frame" and packet["hands"]["right"]["valid"]:
                    packets.append(packet)
                    if len(packets) >= 150:
                        break
    if len(packets) < 100:
        raise ValueError("Need at least 100 real native packets for this integration check")
    with (folder / "server_console.txt").open("x") as console:
        command = [
            str(ROOT / ".venv/bin/python"),
            str(ROOT / "scripts/run_live_retargeting.py"),
            "--port",
            str(args.port),
            "--output",
            str(session),
        ]
        if not args.viewer:
            command.append("--headless")
        if args.robot_profile:
            command.extend(["--robot-profile", str(args.robot_profile.resolve())])
        if args.geort_study:
            command.extend(["--geort-study", str(args.geort_study.resolve())])
        process = await asyncio.create_subprocess_exec(
            *command, stdout=console, stderr=asyncio.subprocess.STDOUT, cwd=ROOT
        )
        try:
            deadline = time.monotonic() + 60
            while True:
                if process.returncode is not None:
                    raise RuntimeError(f"Server exited; see {folder}/server_console.txt")
                try:
                    state = await asyncio.to_thread(status)
                    if all(v["status"] != "STARTING" for v in state["retargeting"].values()):
                        break
                except (OSError, ValueError):
                    pass
                if time.monotonic() > deadline:
                    raise TimeoutError("Workers did not initialize within 60 seconds")
                await asyncio.sleep(0.2)
            async with connect(
                base_url.replace("https:", "wss:") + "/ws?role=source", ssl=context, max_size=65536
            ) as socket:
                await socket.recv()
                for packet in packets:
                    await socket.send(json.dumps(packet))
                    await asyncio.sleep(0.025)
                tracking = await asyncio.to_thread(status)
                assert all(v["status"] == "TRACKING" for v in tracking["retargeting"].values()), (
                    tracking
                )
                # Keep the source connected while intentionally stopping pose transmission.
                await asyncio.sleep(0.7)
                held = await asyncio.to_thread(status)
                assert all(
                    v["status"] == "HOLD_TRACKING_LOST" for v in held["retargeting"].values()
                ), held
        finally:
            if process.returncode is None:
                process.send_signal(signal.SIGTERM)
            try:
                await asyncio.wait_for(process.wait(), 20)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        methods = {}
        for method in tracking["retargeting"]:
            entries = [
                json.loads(line) for line in (session / f"{method}.jsonl").read_text().splitlines()
            ]
            tracked = [entry for entry in entries if entry.get("control_status") == "TRACKING"]
            assert tracked and all(len(e["retarget_q_target"]) == 20 for e in tracked)
            sequences = {e["input_sequence"] for e in tracked}
            assert len(sequences) > 10
            methods[method] = {"tracking_ticks": len(tracked), "unique_sequences": len(sequences)}
        result = {
            "passed": True,
            "packet_source": str(args.input),
            "packets_replayed": len(packets),
            "real_live_quest_test": False,
            "viewer_enabled": args.viewer,
            "geort_study": str(args.geort_study) if args.geort_study else None,
            "methods": methods,
            "tracking_loss_hold_verified": True,
            "output": str(folder),
        }
        (folder / "validation.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", type=Path, default=ROOT / "recordings/geort_train_session_001.jsonl"
    )
    parser.add_argument("--port", type=int, default=8027)
    parser.add_argument("--viewer", action="store_true")
    parser.add_argument("--robot-profile", type=Path)
    parser.add_argument("--geort-study", type=Path)
    asyncio.run(validate(parser.parse_args()))
