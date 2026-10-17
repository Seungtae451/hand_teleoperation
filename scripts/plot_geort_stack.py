#!/usr/bin/env python3
"""Plot existing diagnostic examples; no pose synthesis or model changes."""

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main(audit):
    from benchmark.simulation.robot_model import RobotModel

    robot = RobotModel()
    names = ["official_3498", "quest_1000", "quest_3498", "quest_10000"]
    colors = ["#dd7042", "#3274a1", "#3c9253", "#ae8a21", "#8755aa"]
    fig, axes = plt.subplots(4, 2, figsize=(11, 15), sharex=True, sharey=True)
    for i, name in enumerate(names):
        data = np.load(audit / f"{name}_targets.npz")
        for col, group in enumerate(("open_candidate_indices", "flex_candidate_indices")):
            index = data[group][len(data[group]) // 2]
            human = data["human"][index]
            robot.forward_kinematics(data["q"][index], frame="palm")
            origin = robot.fk_data.xpos[robot.palm_id]
            rotation = robot.fk_data.xmat[robot.palm_id].reshape(3, 3)
            ax = axes[i, col]
            for f in range(5):
                hp = human[[0, *range(1 + 4 * f, 5 + 4 * f)]] * 1000
                names_chain = [f"rl_dg_{f + 1}_{j}" for j in range(1, 5)] + [f"rl_dg_{f + 1}_tip"]
                rp = (
                    np.array(
                        [
                            np.zeros(3),
                            *[
                                (robot.fk_data.xpos[robot.model.body(n).id] - origin) @ rotation
                                for n in names_chain
                            ],
                        ]
                    )
                    * 1000
                )
                ax.plot(hp[:, 0], hp[:, 2], "--", color="#777777", alpha=0.7)
                ax.plot(rp[:, 0], rp[:, 2], "o-", color=colors[f], markersize=3)
            ax.set_title(f"{name}: {'open' if col == 0 else 'flex'} candidate")
            ax.set_xlim(-95, 150)
            ax.set_ylim(-60, 240)
            ax.set_aspect("equal")
            ax.grid(alpha=0.2)
            ax.set_xlabel("X (mm)")
            ax.set_ylabel("Z (mm)")
    fig.suptitle(
        "Same recorded human input vs model target BEFORE controller\n"
        "Dashed gray: human wrist frame; color: robot palm frame\n"
        "Raw origins differ; this is a posture illustration, not ground-truth error",
        fontsize=12,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(audit / "posture_examples.png", dpi=140)
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path, required=True)
    main(parser.parse_args().audit)
