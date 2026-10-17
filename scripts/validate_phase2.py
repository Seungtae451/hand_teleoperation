#!/usr/bin/env python3
"""Produce measured Phase 2 acceptance results, a PNG, and a 4-second MP4."""

import json
import os
import subprocess
import sys

# Set the backend before importing MuJoCo. Override with MUJOCO_GL=glfw if needed.
os.environ.setdefault("MUJOCO_GL", "egl")

import mujoco
import numpy as np
from PIL import Image

from benchmark.cli import main as cli
from benchmark.paths import ROOT
from benchmark.simulation.build_model import build_model
from benchmark.simulation.mujoco_runner import MujocoRunner
from benchmark.simulation.robot_model import RobotModel
from benchmark.simulation.urdf import UrdfModel
from benchmark.simulation.visualization import OffscreenRenderer


def main():
    build_model()
    robot = RobotModel()
    source = UrdfModel(ROOT / robot.config["urdf"])
    rng = np.random.default_rng(20261017)
    fk_error = 0.0
    for q in rng.uniform(robot.limits[:, 0], robot.limits[:, 1], (100, 20)):
        transforms = source.forward(q, robot.joint_names)
        expected = np.array([transforms[n][:3, 3] for n in robot.config["tip_links"]])
        fk_error = max(fk_error, float(np.max(np.abs(robot.forward_kinematics(q) - expected))))
    tracking = {}
    runner = MujocoRunner(robot)
    for i, name in enumerate(robot.joint_names):
        runner.reset()
        q = np.zeros(20)
        q[i] = -0.15 if robot.limits[i, 1] <= 0 else min(0.15, robot.limits[i, 1] / 2)
        runner.set_target(q)
        sample = runner.step(1000)
        tracking[name] = float(np.max(np.abs(sample.q_actual - q)))
    assert fk_error < 1e-12, fk_error
    assert max(tracking.values()) < 3e-5, tracking
    results = ROOT / "results"
    results.mkdir(exist_ok=True)
    runner.reset()
    with OffscreenRenderer(runner.model) as renderer:
        Image.fromarray(renderer.render(runner.data)).save(results / "phase2_open.png")
        from benchmark.experiments.trajectory import demo_target

        runner.set_target(demo_target(2, 4))
        runner.step(1000)
        Image.fromarray(renderer.render(runner.data)).save(results / "phase2_flexed.png")
    cli(
        [
            "demo",
            "--duration",
            "4",
            "--video",
            str(results / "phase2_demo.mp4"),
            "--log",
            str(results / "phase2_demo.jsonl"),
        ]
    )
    cli(
        [
            "replay",
            str(results / "phase2_demo.jsonl"),
            "--log",
            str(results / "phase2_replay.jsonl"),
        ]
    )
    from benchmark.experiments.logging import read_log

    _, original = read_log(results / "phase2_demo.jsonl")
    _, replayed = read_log(results / "phase2_replay.jsonl")
    assert original == replayed, "Joint replay did not reproduce the recorded dynamic state"
    report = {
        "mujoco_version": mujoco.__version__,
        "numpy_version": np.__version__,
        "python": sys.version,
        "source_commit": robot.provenance["source_commit"],
        "nq": robot.model.nq,
        "nv": robot.model.nv,
        "nu": robot.model.nu,
        "random_seed": 20261017,
        "urdf_fk_random_pose_count": 100,
        "urdf_fk_max_component_error_m": fk_error,
        "individual_joint_settling_time_s": 2.0,
        "individual_joint_tracking_max_error_rad": tracking,
        "replay_identical": True,
        "demo_frames": len(original),
        "contacts_enabled": False,
        "gravity_compensation": True,
        "render_backend": os.environ["MUJOCO_GL"],
        "zero_pose_tips_world_m": robot.forward_kinematics(np.zeros(20)).tolist(),
        "source_verification": json.loads(
            subprocess.check_output(
                [sys.executable, str(ROOT / "scripts/verify_sources.py"), "--original"], text=True
            )
        ),
    }
    assert not report["source_verification"]["problems"]
    output = results / "phase2_validation.json"
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Acceptance report: {output}")
    print(f"URDF FK maximum error: {fk_error:.3g} m")
    print(f"20-joint maximum settled error: {max(tracking.values()):.3g} rad")


if __name__ == "__main__":
    main()
