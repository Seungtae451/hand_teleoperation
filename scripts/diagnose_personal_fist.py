#!/usr/bin/env python3
"""Diagnose fist target signs without altering model, source recording or controller."""

import json
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def fist_geometry(points):
    pip, mcp = [], []
    for base in (5, 9, 13, 17):
        u, v = points[:, base + 1] - points[:, base], points[:, base + 2] - points[:, base + 1]
        pip.append(
            np.degrees(
                np.arccos(
                    np.clip(
                        np.sum(u * v, axis=1)
                        / (np.linalg.norm(u, axis=1) * np.linalg.norm(v, axis=1)),
                        -1,
                        1,
                    )
                )
            )
        )
        mcp.append(np.degrees(np.arctan2(u[:, 0], u[:, 2])))
    pip, mcp = np.array(pip).T, np.array(mcp).T
    return (pip > 60).all(axis=1) & (np.abs(mcp) > 45).all(axis=1), pip, mcp


def main():
    import torch
    from scipy.spatial import cKDTree

    from benchmark.geort_support.input import canonical_points
    from benchmark.retargeting.geort import GeoRTRetargeter
    from benchmark.simulation.robot_model import RobotModel
    from benchmark.tracking.recorder import replay_frames

    folder = Path(tempfile.mkdtemp(prefix="personal-fist-diagnosis-", dir=ROOT / "results"))
    session = ROOT / "results/live-retargeting-f1zscgh2"
    raw = (session / "quest_input.jsonl").read_bytes()
    raw = raw[: raw.rfind(b"\n") + 1]
    snapshot = folder / "input_snapshot.jsonl"
    snapshot.write_bytes(raw)
    frames = list(replay_frames(snapshot, handedness="right", include_invalid=False))
    live = np.array([canonical_points(f) for f in frames])
    metadata = json.loads(
        (ROOT / "results/geort_personal_session002_eval/model_verification.json").read_text()
    )
    robot = RobotModel()
    adapter = GeoRTRetargeter(
        robot, checkpoint=metadata["checkpoint"], config_path=metadata["config"]
    )
    training = np.load(ROOT / "data/geort/quest_train_session_002/human.npy")
    report = {
        "policy": "Geometric fist candidates, not manually labeled gestures. "
        "Diagnostic only; no training or modifications.",
        "checkpoint_sha256": metadata["checkpoint_sha256"],
        "session": str(session),
        "sources": {},
    }
    for name, points in [("training", training), ("live", live)]:
        mask, pip, mcp = fist_geometry(points)
        indices = np.flatnonzero(mask)
        if len(indices) > 256:
            indices = indices[np.linspace(0, len(indices) - 1, 256, dtype=int)]
        if not len(indices):
            report["sources"][name] = {"frames": len(points), "candidate_count": 0}
            continue
        sample = points[indices]
        with torch.inference_mode():
            norm = (
                adapter.vendor.model(
                    torch.tensor(sample[:, [4, 8, 12, 16, 20]], dtype=torch.float32, device="cuda")
                )
                .cpu()
                .numpy()
            )
        q = adapter.vendor.qpos_normalizer.unnormalize(norm)
        result = {
            "frames": len(points),
            "candidate_count": int(mask.sum()),
            "sampled": len(indices),
            "human_pip_mean_deg": pip[indices].mean(axis=0).tolist(),
            "human_proximal_x_mean_mm": (
                sample[:, [6, 10, 14, 18], 0] - sample[:, [5, 9, 13, 17], 0]
            )
            .mean(axis=0)
            .tolist(),
            "model_joint_mean_deg": np.degrees(q.mean(axis=0)).reshape(5, 4).tolist(),
            "model_negative_distal_fraction_by_finger": (q.reshape(-1, 5, 4)[:, :, 2:] < -0.05)
            .mean(axis=0)
            .tolist(),
        }
        result["human_proximal_x_mean_mm"] = (
            np.array(result["human_proximal_x_mean_mm"]) * 1000
        ).tolist()
        if name == "live":
            nearest = np.stack(
                [cKDTree(training[:, t]).query(sample[:, t])[0] for t in [4, 8, 12, 16, 20]], axis=1
            )
            result["nearest_training_tip_mean_mm"] = float(nearest.mean() * 1000)
            selected_timestamps = {frames[i].timestamp for i in np.flatnonzero(mask)}
            tracked = []
            with (session / "geort.jsonl").open() as stream:
                for line in stream:
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        break
                    if (
                        entry.get("control_status") == "TRACKING"
                        and entry.get("input_timestamp_s") in selected_timestamps
                    ):
                        tracked.append(entry)
            result["matched_control_ticks"] = len(tracked)
            if tracked:
                target = np.array([e["retarget_q_target"] for e in tracked])
                command = np.array([e["simulation"]["q_command"] for e in tracked])
                actual = np.array([e["simulation"]["q_actual"] for e in tracked])
                result["logged_target_mean_deg"] = (
                    np.degrees(target.mean(axis=0)).reshape(5, 4).tolist()
                )
                result["logged_actual_mean_deg"] = (
                    np.degrees(actual.mean(axis=0)).reshape(5, 4).tolist()
                )
                result["mean_max_joint_command_actual_gap_rad"] = float(
                    np.max(np.abs(command - actual), axis=1).mean()
                )
                result["mean_max_joint_target_command_gap_rad"] = float(
                    np.max(np.abs(target - command), axis=1).mean()
                )
                settled = np.max(np.abs(target - command), axis=1) < 0.03
                result["near_target_control_ticks"] = int(settled.sum())
                if settled.any():
                    result["near_target_actual_mean_deg"] = (
                        np.degrees(actual[settled].mean(axis=0)).reshape(5, 4).tolist()
                    )
        np.savez_compressed(folder / f"{name}_fist_targets.npz", human=sample, q=q, indices=indices)
        report["sources"][name] = result
    path = folder / "diagnosis.json"
    path.write_text(json.dumps(report, indent=2) + "\n")
    print(path)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
