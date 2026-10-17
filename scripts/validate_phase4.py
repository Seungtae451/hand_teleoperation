#!/usr/bin/env python3
"""Measure Phase 4 behavior using explicit synthetic poses and an optional real recording."""

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path

os.environ.setdefault("MUJOCO_GL", "egl")

import numpy as np
from PIL import Image

from benchmark.experiments.manus_cli import main as manus_cli
from benchmark.experiments.manus_fixtures import pose_frame
from benchmark.paths import ROOT
from benchmark.retargeting.manus import ManusRetargeter
from benchmark.simulation.mujoco_runner import MujocoRunner
from benchmark.simulation.robot_model import RobotModel
from benchmark.simulation.visualization import OffscreenRenderer
from benchmark.tracking.recorder import replay_frames


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recording", type=Path)
    args = parser.parse_args()
    folder = Path(tempfile.mkdtemp(prefix="phase4-validation-", dir=ROOT / "results"))
    robot = RobotModel()
    retargeter = ManusRetargeter(robot)
    runner = MujocoRunner(robot)
    poses = {}
    with OffscreenRenderer(robot.model) as renderer:
        for name in ("open", "closed", "pinch"):
            frame = pose_frame(name)
            result = retargeter.retarget(frame)
            runner.reset()
            runner.set_target(result.q_target)
            sample = runner.step(1000)
            Image.fromarray(renderer.render(runner.data)).save(folder / f"{name}.png")
            poses[name] = {
                "human_fixture_thumb_index_distance_m": float(
                    np.linalg.norm(frame.joint_positions[4] - frame.joint_positions[8])
                ),
                "robot_thumb_index_frame_distance_m": float(
                    np.linalg.norm(sample.tips_actual_world[0] - sample.tips_actual_world[1])
                ),
                "limit_clipped_joints": int(sum(result.metadata["joint_limit_clipped"])),
                "settled_max_error_rad": float(np.max(np.abs(sample.q_actual - result.q_target))),
            }
    manus_cli(["demo", "--duration", "5", "--video", "--output", str(folder / "synthetic")])
    recording_result = None
    if args.recording:
        count = 0
        clipped = np.zeros(20)
        targets = []
        timing = []
        retargeter.reset()
        for frame in replay_frames(args.recording, handedness="right"):
            if not frame.tracking_valid:
                continue
            result = retargeter.retarget(frame)
            targets.append(result.q_target)
            timing.append(result.metadata["total_s"] * 1000)
            clipped += result.metadata["joint_limit_clipped"]
            count += 1
        if not count:
            raise ValueError("No valid right-hand frames in the real recording")
        recording_result = {
            "input": str(args.recording),
            "input_sha256": hashlib.sha256(args.recording.read_bytes()).hexdigest(),
            "valid_right_frames": count,
            "joint_excursion_rad": np.ptp(targets, axis=0).tolist(),
            "joint_clipping_fraction": (clipped / count).tolist(),
            "retarget_mean_ms": float(np.mean(timing)),
            "retarget_p95_ms": float(np.percentile(timing, 95)),
            "input_adapter": "raw geometric degree proxy; no project gain/offset calibration",
            "gesture_labels": "not provided; no real pinch success or pose accuracy inferred",
        }
        manus_cli(
            [
                "replay",
                str(args.recording),
                "--duration",
                "5",
                "--video",
                "--output",
                str(folder / "recorded"),
            ]
        )
    integrity = None
    baseline_path = Path("/tmp/phase4_existing_code_sha256.json")
    if baseline_path.is_file():
        baseline = json.loads(baseline_path.read_text())
        changed = [
            p for p, d in baseline.items() if hashlib.sha256(Path(p).read_bytes()).hexdigest() != d
        ]
        integrity = {"checked": len(baseline), "changed": changed}
        assert not changed
    report = {
        "method": "MANUS-style Quest geometric adapter + unmodified official mapping",
        "vendor": retargeter.vendor.provenance,
        "synthetic_pose_results": poses,
        "real_recording": recording_result,
        "existing_file_integrity": integrity,
        "contact_enabled": False,
        "live_hardware_end_to_end": "pending user Quest-to-MuJoCo test",
        "pinch_contact_success": "not demonstrated; frame distance is not surface contact",
        "output": str(folder),
    }
    (folder / "validation.json").write_text(json.dumps(report, indent=2) + "\n")
    (ROOT / "results/phase4_validation_latest.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
