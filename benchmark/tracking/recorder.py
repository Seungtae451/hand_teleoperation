"""Loss-aware input recordings; native packets and canonical frames remain separate."""

import json
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from benchmark.paths import writable_output
from benchmark.tracking.hand_frame import HandFrame
from benchmark.tracking.webxr_protocol import protocol_description


def frame_to_dict(frame):
    return {
        name: value.tolist() if isinstance(value, np.ndarray) else value
        for name, value in asdict(frame).items()
    }


def frame_from_dict(data):
    if type(data.get("tracking_valid")) is not bool:
        raise ValueError("Recorded tracking validity must be boolean")
    return HandFrame(**data)


class HandRecorder:
    def __init__(
        self, path: Path, *, source_kind="webxr_live", target_frame="wrist_rh", timeout=0.25
    ):
        self.path = writable_output(Path(path))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.path.open("x", buffering=1)
        self.write(
            {
                "event": "header",
                "schema": "quest_hand_recording_v1",
                "created_utc": datetime.now(timezone.utc).isoformat(),
                "source_kind": source_kind,
                "target_frame": target_frame,
                "tracking_timeout_s": timeout,
                "protocol": protocol_description(),
                "clock_note": "Receiver monotonic seconds; browser clocks are not synchronized",
            }
        )

    def write(self, event):
        self.stream.write(json.dumps(event, allow_nan=False, separators=(",", ":")) + "\n")

    def close(self):
        self.stream.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def read_events(path):
    with Path(path).open() as stream:
        header = json.loads(next(stream))
        if header.get("schema") != "quest_hand_recording_v1":
            raise ValueError("Unsupported hand recording schema")
        for line in stream:
            if line.strip():
                yield json.loads(line)


def replay_frames(path, *, realtime=False, speed=1.0, handedness=None, include_invalid=True):
    """Yield the recorded frames verbatim, with optional receive-time pacing.

    Invalid held poses retain tracking_valid=False. Consumers must never silently
    retarget these frames. source/wall/receiver timestamps aren't interchanged.
    """
    if not np.isfinite(speed) or speed <= 0:
        raise ValueError("Replay speed must be finite and positive")
    if handedness not in (None, "left", "right"):
        raise ValueError("Unknown handedness")
    first_stamp = None
    previous_stamp = -np.inf
    start = time.monotonic()
    for event in read_events(path):
        if event.get("event") != "hand_frame":
            continue
        frame = frame_from_dict(event["frame"])
        if frame.timestamp < previous_stamp:
            raise ValueError("Recording receiver timestamps must not regress")
        previous_stamp = frame.timestamp
        if handedness and frame.handedness != handedness:
            continue
        if not include_invalid and not frame.tracking_valid:
            continue
        if first_stamp is None:
            first_stamp = frame.timestamp
        if realtime:
            time.sleep(max(0, (frame.timestamp - first_stamp) / speed - (time.monotonic() - start)))
        yield frame
