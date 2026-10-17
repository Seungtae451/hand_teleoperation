#!/usr/bin/env python3
"""Static actual-recording pose illustrations, no dynamics or algorithm changes."""

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

    data = np.load(folder / "comparison_personal_quest_quest_eval.npz")
    allegro = mujoco.MjModel.from_xml_path(str(folder / "allegro_mujoco.xml"))
    allegro.vis.headlight.ambient[:] = [0.65, 0.65, 0.65]
    allegro.vis.headlight.diffuse[:] = [0.8, 0.8, 0.8]
    dg = RobotModel()
    cfg = json.loads((folder / "config.json").read_text())
    figure, axes = plt.subplots(2, 2, figsize=(10, 10))
    metadata = {}
    for row, gesture in enumerate(["open", "fist"]):
        count = len(data[f"{gesture}_human"])
        index = count // 2
        metadata[gesture] = {
            "source_eval_valid_frame_index": int(data[f"{gesture}_source_indices"][index]),
            "candidate_subset_index": index,
        }
        for col, (name, model, joints) in enumerate(
            [("allegro", allegro, cfg["joint_order"]), ("dg5f", dg.model, dg.joint_names)]
        ):
            state = mujoco.MjData(model)
            adr = [model.jnt_qposadr[model.joint(n).id] for n in joints]
            state.qpos[adr] = data[f"{gesture}_{name}_q"][index]
            mujoco.mj_forward(model, state)
            camera = mujoco.MjvCamera()
            camera.azimuth = 35
            camera.elevation = -20
            camera.distance = 0.46
            camera.lookat[:] = [0.02, 0, 0.025] if name == "allegro" else [0.025, 0, 0.12]
            with mujoco.Renderer(model, height=480, width=480) as renderer:
                renderer.update_scene(state, camera=camera)
                pixels = renderer.render().copy()
            axes[row, col].imshow(pixels)
            axes[row, col].axis("off")
            axes[row, col].set_title(f"{name.upper()} / {gesture} input")
    figure.suptitle(
        "Same Quest evaluation frame, original GeoRT model target\n"
        "Static kinematics only; different robot origins and shapes",
        fontsize=13,
    )
    figure.tight_layout(rect=(0, 0, 1, 0.94))
    figure.savefig(folder / "pose_comparison.png", dpi=140)
    plt.close(figure)
    (folder / "pose_comparison_frames.json").write_text(json.dumps(metadata, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    main(parser.parse_args().output.resolve())
