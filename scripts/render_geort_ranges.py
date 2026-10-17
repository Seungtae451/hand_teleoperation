#!/usr/bin/env python3
"""Same-recorded-frame static full/restricted pose comparison."""

import argparse
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mujoco
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main(folder):
    from benchmark.simulation.robot_model import RobotModel
    from benchmark.simulation.visualization import configure_camera

    robot = RobotModel()
    output = np.load(folder / "eval_outputs.npz")
    figure, axes = plt.subplots(2, 2, figsize=(10, 10))
    chosen = {}
    with mujoco.Renderer(robot.model, width=480, height=480) as renderer:
        for row, gesture in enumerate(["open", "fist"]):
            ids = np.flatnonzero(output[f"{gesture}_mask"])
            i = int(ids[len(ids) // 2])
            chosen[gesture] = i
            for col, name in enumerate(["full", "restricted"]):
                state = mujoco.MjData(robot.model)
                state.qpos[robot.qpos_indices] = output[f"{name}_q"][i]
                mujoco.mj_forward(robot.model, state)
                camera = mujoco.MjvCamera()
                configure_camera(camera)
                renderer.update_scene(state, camera=camera)
                axes[row, col].imshow(renderer.render().copy())
                axes[row, col].axis("off")
                axes[row, col].set_title(f"{name.upper()} / {gesture} input")
    figure.suptitle(
        "Paired range experiment: same Quest frame and physical robot\n"
        "Model targets before common controller; no contact-success claim",
        fontsize=12,
    )
    figure.tight_layout(rect=(0, 0, 1, 0.94))
    figure.savefig(folder / "pose_comparison.png", dpi=140)
    plt.close(figure)
    (folder / "pose_comparison_indices.json").write_text(json.dumps(chosen, indent=2) + "\n")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    main(p.parse_args().output.resolve())
