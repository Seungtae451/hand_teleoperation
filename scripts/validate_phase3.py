#!/usr/bin/env python3
"""Validate Phase 3 without a headset, using actual verified TLS WebSocket transport."""

import asyncio
import hashlib
import json
import ssl
import subprocess
import sys
import tempfile
from pathlib import Path

from websockets.asyncio.client import connect

from benchmark.paths import ROOT
from benchmark.tracking.quest_receiver import QuestReceiver, tls_context
from benchmark.tracking.receiver_state import ReceiverState
from benchmark.tracking.recorder import HandRecorder, frame_to_dict, read_events, replay_frames
from benchmark.tracking.synthetic import synthetic_packet


async def run_network(output):
    with tempfile.TemporaryDirectory(prefix="quest-phase3-") as tmp:
        cert, key = Path(tmp) / "cert.pem", Path(tmp) / "key.pem"
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-keyout",
                str(key),
                "-out",
                str(cert),
                "-days",
                "1",
                "-subj",
                "/CN=localhost",
                "-addext",
                "subjectAltName=DNS:localhost,IP:127.0.0.1",
            ],
            capture_output=True,
            check=True,
        )
        tls = ssl.create_default_context(cafile=str(cert))
        with HandRecorder(output, source_kind="synthetic_webxr_over_verified_wss") as recorder:
            state = ReceiverState(timeout=0.1, recorder=recorder)
            receiver = QuestReceiver(state)
            port = await receiver.start(context=tls_context(cert, key))
            try:
                async with connect(
                    f"wss://127.0.0.1:{port}/ws?role=source", ssl=tls, proxy=None
                ) as ws:
                    while json.loads(await ws.recv())["type"] != "session":
                        pass
                    for i in range(120):
                        packet = synthetic_packet(i, i / 60, lost=40 <= i < 50)
                        await ws.send(json.dumps(packet))
                        await asyncio.sleep(0.002)
                    # This is accelerated synthetic input, not a capture-rate measurement.
                    for _ in range(100):
                        if state.accepted_packets == 120:
                            break
                        await asyncio.sleep(0.01)
                    assert state.accepted_packets == 120
                    await asyncio.sleep(0.2)
                    assert not state.status(asyncio.get_running_loop().time())["hands"]["right"][
                        "valid"
                    ]
                    await ws.send(json.dumps(synthetic_packet(120, 2)))
                    await asyncio.sleep(0.02)
                    assert state.latest["right"].tracking_valid
            finally:
                await receiver.close()
            counters = {
                "accepted_packets": state.accepted_packets,
                "accepted_hand_frames": state.accepted_frames,
                "rejected_packets": state.rejected_packets,
            }
    events = list(read_events(output))
    expected = [e["frame"] for e in events if e["event"] == "hand_frame"]
    replayed = [frame_to_dict(f) for f in replay_frames(output)]
    assert expected == replayed
    return {
        **counters,
        "replayed_frames": len(replayed),
        "invalid_replayed_frames": sum(not f["tracking_valid"] for f in replayed),
        "replay_exact": True,
        "tls_certificate_verification": True,
        "recording": str(output),
        "loss_reasons": sorted({e["reason"] for e in events if e["event"] == "tracking_lost"}),
    }


def main():
    folder = ROOT / "results"
    folder.mkdir(exist_ok=True)
    # Use a fresh directory each run; input recordings are never silently overwritten.
    output_dir = Path(tempfile.mkdtemp(prefix="phase3-", dir=folder))
    network = asyncio.run(run_network(output_dir / "synthetic_wss.jsonl"))
    baseline_path = Path("/tmp/phase3_existing_files_sha256.json")
    integrity = None
    if baseline_path.is_file():
        baseline = json.loads(baseline_path.read_text())
        changed = [
            p
            for p, digest in baseline.items()
            if not Path(p).is_file() or hashlib.sha256(Path(p).read_bytes()).hexdigest() != digest
        ]
        integrity = {"checked_existing_files": len(baseline), "changed_files": changed}
        assert not changed
    report = {
        "hardware_quest_test": "PENDING: no real Quest input was used in this validation",
        "source": "explicit synthetic WebXR packets",
        "network": network,
        "existing_file_integrity": integrity,
        "python": sys.version,
        "next_step": "Open the HTTPS page in Quest Browser and verify live joint updates",
    }
    path = folder / "phase3_validation.json"
    path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    print(f"Report: {path}")


if __name__ == "__main__":
    main()
