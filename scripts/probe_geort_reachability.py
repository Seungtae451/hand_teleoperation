#!/usr/bin/env python3
"""Existing robot-cloud nearest lookup for diagnosis only; not a retargeting baseline."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main(audit):
    import torch

    from benchmark.retargeting.geort import GeoRTRetargeter
    from benchmark.simulation.robot_model import RobotModel

    study = ROOT / "results/geort_data_size_parity_20261018"
    models = json.loads((study / "models.json").read_text())
    robot = RobotModel()
    cache = study / "shared/dg5f_right_geort.npz"
    study_document = json.loads((study / "study.json").read_text())
    assert (
        hashlib.sha256(cache.read_bytes()).hexdigest()
        == study_document["shared_robot_cache"]["robot_data_sha256"]
    )
    cloud = np.load(cache, allow_pickle=True)
    # Object dict is loaded only from the project-generated robot cache checked by study hash.
    keypoints = cloud["keypoint"].item()
    cloud_q = cloud["qpos"]
    sample = np.load(audit / "quest_10000_targets.npz")["human"]
    report = {
        "policy": "Independent-finger nearest existing robot samples. Diagnostic reachability "
        "probe only, not a new algorithm or replacement model. "
        "No contact/self-collision guarantee. "
        "Human raw positions compare wrist vs palm. "
        "Training data diagnostics are not held-out scores.",
        "models": {},
    }
    targets = np.zeros((len(sample), 20))
    for f in range(5):
        tip = [4, 8, 12, 16, 20][f]
        points = keypoints[f"rl_dg_{f + 1}_tip"]
        _, ids = cKDTree(points).query(sample[:, tip])
        targets[:, f * 4 : (f + 1) * 4] = cloud_q[ids, f * 4 : (f + 1) * 4]
    tips = np.array([robot.forward_kinematics(q, frame="palm") for q in targets])
    distance = np.linalg.norm(tips - sample[:, [4, 8, 12, 16, 20]], axis=2) * 1000
    report["existing_sample_reachability_tip_distance_mm"] = {
        "mean": float(distance.mean()),
        "p95": float(np.percentile(distance, 95)),
        "per_finger_mean": distance.mean(axis=0).tolist(),
    }
    for name, meta in models.items():
        folder = Path(json.loads((study / "study.json").read_text())["conditions"][name]["dataset"])
        points = np.load(folder / "human.npy")
        indices = np.linspace(0, len(points) - 1, min(512, len(points)), dtype=int)
        points = points[indices]
        adapter = GeoRTRetargeter(robot, checkpoint=meta["checkpoint"], config_path=meta["config"])
        with torch.inference_mode():
            norm = (
                adapter.vendor.model(
                    torch.tensor(points[:, [4, 8, 12, 16, 20]], dtype=torch.float32, device="cuda")
                )
                .cpu()
                .numpy()
            )
        q = adapter.vendor.qpos_normalizer.unnormalize(norm)
        rp = np.array([robot.forward_kinematics(row, frame="palm") for row in q])
        error = np.linalg.norm(rp - points[:, [4, 8, 12, 16, 20]], axis=2) * 1000
        report["models"][name] = {
            "training_sample_frames": len(points),
            "human_to_model_tip_mean_mm_on_own_training": float(error.mean()),
            "fraction_negative_nonthumb_distal_joint_values": float(
                (q[:, [6, 7, 10, 11, 14, 15, 18, 19]] < -0.05).mean()
            ),
        }
    (audit / "reachability.json").write_text(json.dumps(report, indent=2) + "\n")
    np.savez_compressed(audit / "reachability_probe_only.npz", human=sample, q=targets, tips=tips)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path, required=True)
    main(parser.parse_args().audit.resolve())
