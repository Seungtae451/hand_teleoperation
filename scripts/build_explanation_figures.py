#!/usr/bin/env python3
"""Build explanatory schematics; synthetic illustrations are explicitly labelled."""

import argparse
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyBboxPatch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "docs/figures")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.size": 11, "axes.spines.top": False, "axes.spines.right": False})

    def finish(fig, name):
        fig.tight_layout()
        fig.savefig(args.output / name, dpi=170, bbox_inches="tight")
        plt.close(fig)

    fig, ax = plt.subplots(figsize=(14, 5))
    ax.set(xlim=(0, 14), ylim=(-0.5, 4))
    ax.axis("off")
    rows = [
        (
            "MANUS-style",
            ["21 keypoints", "20 geometric angles", "Vendor mapping", "20 robot angles"],
        ),
        (
            "AnyDex",
            ["21 keypoints", "Vectors + pinch weight", "Constrained optimizer", "20 robot angles"],
        ),
        (
            "Wuji",
            ["21 keypoints", "Vectors + pinch weight", "Related optimizer", "20 robot angles"],
        ),
        (
            "GeoRT",
            [
                "5 fingertip positions",
                "5 trained finger nets",
                "Range unnormalization",
                "20 robot angles",
            ],
        ),
    ]
    for row, (method, boxes) in enumerate(rows):
        y = 3 - row
        ax.text(0, y + 0.27, method, weight="bold", va="center")
        for i, label in enumerate(boxes):
            x = 1.7 + i * 3.05
            ax.add_patch(
                FancyBboxPatch(
                    (x, y),
                    2.65,
                    0.56,
                    boxstyle="round,pad=.06",
                    facecolor=["#e9e4ff", "#d8f0ee", "#fff0d5", "#fce1e7"][row],
                    edgecolor="#555",
                )
            )
            ax.text(x + 1.325, y + 0.28, label, ha="center", va="center", fontsize=10)
            if i < 3:
                ax.annotate(
                    "", (x + 2.98, y + 0.28), (x + 2.68, y + 0.28), arrowprops={"arrowstyle": "->"}
                )
    ax.set_title("What is matched? Angles / geometry / a learned fingertip map", pad=20)
    finish(fig, "method_overview.png")

    fig, axes = plt.subplots(1, 3, figsize=(14, 4))
    theta = np.linspace(0, 110, 300)
    axes[0].plot(theta, np.maximum(0, 1.3 * (theta - 40)), lw=2, label="Index PIP")
    axes[0].plot(theta, np.maximum(0, 1.3 * (theta - 30)), lw=2, label="Middle PIP")
    axes[0].set(
        xlabel="Input ergonomics proxy (deg)",
        ylabel="Vendor output (deg)",
        title="MANUS right-hand mapping\nBefore common clipping",
    )
    axes[0].legend()
    distance = np.linspace(0, 6, 300)
    alpha = np.clip((4 - distance) / 2, 0, 0.7)
    axes[1].plot(distance, alpha, lw=2, label="Tip position + direction weight")
    axes[1].plot(distance, 1 - alpha, lw=2, label="Full-hand weight")
    axes[1].set(
        xlabel="Thumb-finger distance (cm)",
        ylabel="Blend weight",
        title="Adaptive pinch weighting\nDefault d1=2, d2=4, alpha max=0.7",
    )
    axes[1].legend(fontsize=8)
    x = np.linspace(-6, 6, 300)
    delta = 2
    axes[2].plot(
        x,
        np.where(abs(x) <= delta, 0.5 * x * x, delta * (abs(x) - 0.5 * delta)),
        lw=2,
        label="Huber, delta=2",
    )
    axes[2].plot(x, 0.5 * x * x, "--", color="gray", label="Squared error")
    axes[2].set(
        xlabel="Residual (illustrative cm)",
        ylabel="Penalty",
        title="Robust geometry error\nSmall error: quadratic; large: linear",
    )
    axes[2].legend()
    fig.suptitle("Formula illustrations / not measured algorithm performance")
    finish(fig, "mapping_and_optimizer.png")

    fig, axes = plt.subplots(1, 4, figsize=(15, 3.8))
    axes[0].quiver([0, 0], [0, 0.5], [1, 0.8], [0.25, 0.2], angles="xy", scale_units="xy", scale=1)
    axes[0].text(0.05, -0.1, "input perturbation")
    axes[0].text(0.05, 0.8, "mapped perturbation")
    axes[0].set(xlim=(-0.1, 1.2), ylim=(-0.3, 1.1), title="Direction\nMatch local motion direction")
    a = np.array([[0, 0], [0.5, 0.8], [1.1, 0.2]])
    b = a + np.array([0.12, -0.15])
    axes[1].scatter(*a.T, label="mapped human cloud")
    axes[1].scatter(*b.T, marker="x", label="robot workspace")
    for u, v in zip(a, b):
        axes[1].plot([u[0], v[0]], [u[1], v[1]], ":", color="gray")
    axes[1].set_title("Chamfer\nMatch fingertip distributions")
    axes[1].legend(fontsize=7)
    x = np.linspace(-1, 1, 100)
    axes[2].plot(x, x, label="locally straight")
    axes[2].plot(x, x + 0.5 * x * x, label="curved response")
    axes[2].set_title("Curvature\nPenalize local second difference")
    axes[2].legend(fontsize=8)
    axes[3].scatter([0, 0.15], [0, 0], s=80, label="nearby input pair")
    axes[3].scatter([0, 0.7], [0.6, 0.6], s=80, marker="x", label="separated mapped pair")
    axes[3].annotate("", (0.7, 0.6), (0, 0.6), arrowprops={"arrowstyle": "<->"})
    axes[3].set(xlim=(-0.2, 1), ylim=(-0.3, 1), title="Pinch\nPenalize mapped separation")
    axes[3].legend(fontsize=7)
    for ax in axes:
        ax.set_xticks([])
        ax.set_yticks([])
    fig.suptitle("GeoRT training objectives / conceptual examples, not collected data")
    finish(fig, "geort_losses.png")

    from benchmark.simulation.robot_model import RobotModel

    robot = RobotModel()
    record = json.loads((ROOT / "docs/media/video_benchmark_002/ik_ambiguity.json").read_text())
    fig, ax = plt.subplots(figsize=(6, 5))
    for key, label in [
        ("positive_middle_flexion_deg", "Positive-flexion solution"),
        ("alternative_middle_flexion_deg", "Alternative solution"),
    ]:
        q = np.zeros(20)
        q[9:12] = np.radians(record[key])
        tips = robot.forward_kinematics(q, frame="palm")
        d = robot.fk_data
        R = d.xmat[robot.palm_id].reshape(3, 3)
        o = d.xpos[robot.palm_id]
        chain = np.array(
            [(d.xpos[robot.model.body(f"rl_dg_3_{j}").id] - o) @ R for j in [2, 3, 4]] + [tips[2]]
        )
        ax.plot(chain[:, 0] * 1000, chain[:, 2] * 1000, "o-", label=label, lw=2)
    ax.set(
        aspect="equal",
        xlabel="Palm X (mm)",
        ylabel="Palm Z (mm)",
        title="Actual DG-5F FK: same tip, different posture",
    )
    ax.legend(fontsize=9)
    finish(fig, "ik_ambiguity.png")

    from benchmark.tracking.recorder import read_events

    take = ROOT / "recordings/video_benchmark_002"
    markers = [json.loads(s) for s in (take / "markers.jsonl").read_text().splitlines()]
    stages = [m for m in markers if m["browser"]["event"] == "stage"]
    origin = stages[0]["receive_time_s"]
    times = []
    valid = []
    for e in read_events(take / "quest_input.jsonl"):
        if e.get("event") == "hand_frame" and e["frame"]["handedness"] == "right":
            times.append(e["frame"]["timestamp"] - origin)
            valid.append(e["frame"]["tracking_valid"])
    times = np.array(times)
    valid = np.array(valid)
    fig, axes = plt.subplots(2, 1, figsize=(14, 5), gridspec_kw={"height_ratios": [1, 2]})
    for i, m in enumerate(stages):
        start = m["receive_time_s"] - origin
        axes[0].broken_barh([(start, 6)], (0, 1), facecolors=plt.cm.tab20(i % 20))
        axes[0].text(
            start + 3,
            0.5,
            m["browser"]["stage"].replace("_", "\n"),
            ha="center",
            va="center",
            fontsize=7,
        )
    axes[0].set(
        xlim=(0, 114),
        ylim=(0, 1),
        yticks=[],
        title="Actual recording: prompted actions (not ground-truth success)",
    )
    axes[1].plot(times[1:], np.diff(times) * 1000, lw=0.8)
    for x in times[~valid]:
        axes[1].axvline(x, color="red", label="Invalid frame (end of capture)")
    axes[1].set(
        xlabel="Receiver time from routine start (s)",
        ylabel="Frame interval (ms)",
        title="Raw right-hand frame timing / no interpolated tracking data",
    )
    axes[1].legend(fontsize=9)
    finish(fig, "collection_timeline.png")


if __name__ == "__main__":
    main()
