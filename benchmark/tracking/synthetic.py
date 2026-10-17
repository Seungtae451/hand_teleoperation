"""Clearly labeled synthetic WebXR-format packets for offline pipeline verification."""

import numpy as np

from benchmark.tracking.webxr_protocol import WEBXR_JOINT_NAMES


def synthetic_packet(sequence=0, seconds=0.0, *, lost=False):
    packet = {
        "version": 1,
        "type": "frame",
        "sequence": sequence,
        "source_time_ms": seconds * 1000,
        "reference_space": "local-floor",
        "reference_epoch": 0,
        "joint_names": list(WEBXR_JOINT_NAMES),
        "hands": {},
    }
    for side in ("left", "right"):
        if lost:
            packet["hands"][side] = {"valid": False, "reason": "synthetic_tracking_loss"}
            continue
        points = [np.zeros(3)]
        curl = 0.5 + 0.5 * np.sin(2 * np.pi * seconds / 2)
        for finger in range(5):
            count = 4 if finger == 0 else 5
            lateral = [0.055, 0.03, 0.008, -0.015, -0.037][finger]
            for part in range(count):
                distance = 0.03 + part * 0.023
                bend = curl * part * 0.15
                points.append(np.array([np.sin(bend) * distance, lateral, np.cos(bend) * distance]))
        positions = np.array(points)
        if side == "left":
            positions[:, 1] *= -1
        positions += np.array([-0.2 if side == "left" else 0.2, 1.2, -0.5])
        packet["hands"][side] = {
            "valid": True,
            "emulated": False,
            "positions": positions.tolist(),
            "rotations": [[0, 0, 0, 1] for _ in range(25)],
        }
    return packet
