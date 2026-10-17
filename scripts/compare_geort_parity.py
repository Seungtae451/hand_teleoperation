#!/usr/bin/env python3
"""Fixed validation/live diagnostic for preserved and parity-adapted checkpoints.

No optimization, no test split, no extra human recordings in model training.
Distances compare human wrist to robot palm, and are not ground-truth pose error.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main(study):
    import torch
    from scipy.spatial import cKDTree

    from benchmark.retargeting.geort import GeoRTRetargeter
    from benchmark.simulation.robot_model import RobotModel

    document = json.loads((study / "study.json").read_text())
    parent = Path(document["parent_study"])
    catalogs = {
        "preserved": json.loads((parent / "models.json").read_text()),
        "parity_adapted": json.loads((study / "models.json").read_text()),
    }
    live = ROOT / "results/geort-diagnosis-nsinlfay/live_canonical.npy"
    paths = {
        "public_validation_parity_adapted": study / "datasets/validation/human.npy",
        "live_webxr_unchanged": live,
    }
    report = {
        "policy": "Same 512 evenly spaced indices per source for all models. "
        "Public validation has fixed parity conversion for both model groups; live is unchanged. "
        "Test split not scored. Diagnostic snapshot not used in training. "
        "No controller in this diagnostic. Human-wrist versus robot-palm distances are not "
        "ground-truth error or a formal algorithm ranking.",
        "input_adapter": document["coordinate_adapter"],
        "inputs": {},
        "models": {},
    }
    samples = {}
    for name, path in paths.items():
        points = np.load(path)
        ids = np.linspace(0, len(points) - 1, min(512, len(points)), dtype=int)
        samples[name] = points[ids]
        report["inputs"][name] = {
            "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "indices": ids.tolist(),
        }
    robot = RobotModel()
    for version, catalog in catalogs.items():
        report["models"][version] = {}
        for name, metadata in catalog.items():
            adapter = GeoRTRetargeter(
                robot, checkpoint=metadata["checkpoint"], config_path=metadata["config"]
            )
            source = np.load(
                (parent if version == "preserved" else study) / "datasets" / name / "human.npy"
            )
            trees = [cKDTree(source[:, tip]) for tip in (4, 8, 12, 16, 20)]
            result = {}
            for label, sample in samples.items():
                hp = sample[:, [4, 8, 12, 16, 20]]
                with torch.inference_mode():
                    normalized = (
                        adapter.vendor.model(torch.from_numpy(hp).float().cuda()).cpu().numpy()
                    )
                raw = adapter.vendor.qpos_normalizer.unnormalize(normalized)
                np.testing.assert_allclose(raw[0], adapter.vendor.forward(sample[0]), atol=1e-5)
                assert raw.shape == (len(sample), 20) and np.isfinite(raw).all()
                q = np.array([robot.validate_target(row, clip=True) for row in raw])
                rp = np.array([robot.forward_kinematics(row, frame="palm") for row in q])
                nearest = np.stack(
                    [tree.query(hp[:, finger])[0] for finger, tree in enumerate(trees)], axis=1
                )
                error = np.linalg.norm(rp - hp, axis=2) * 1000
                pinch = np.linalg.norm(hp[:, 1:] - hp[:, :1], axis=2) < 0.015
                robot_pinch = np.linalg.norm(rp[:, 1:] - rp[:, :1], axis=2) * 1000
                result[label] = {
                    "frames": len(sample),
                    "tip_correspondence_mean_mm": float(error.mean()),
                    "tip_correspondence_p95_mm": float(np.percentile(error, 95)),
                    "per_finger_mean_mm": error.mean(axis=0).tolist(),
                    "nearest_training_tip_mean_mm": float(nearest.mean() * 1000),
                    "max_joint_clipping_rad": float(np.max(np.abs(q - raw))),
                    "human_pinch_candidates": int(pinch.sum()),
                    "robot_pinch_distance_mean_mm": float(robot_pinch[pinch].mean())
                    if pinch.any()
                    else None,
                }
                np.savez_compressed(
                    study / f"diagnostic_{version}_{name}_{label}.npz",
                    q_raw=raw,
                    q_target=q,
                    human_tips=hp,
                    robot_tips=rp,
                )
            report["models"][version][name] = result
    (study / "parity_comparison.json").write_text(json.dumps(report, indent=2) + "\n")
    for version, values in report["models"].items():
        for name, entry in values.items():
            print(
                version,
                name,
                {k: round(v["tip_correspondence_mean_mm"], 2) for k, v in entry.items()},
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, required=True)
    main(parser.parse_args().study.resolve())
