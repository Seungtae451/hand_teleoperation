#!/usr/bin/env python3
"""Read-only model/data/control diagnosis; no optimization or checkpoint edits."""

import hashlib
import json
import re
import sys
import tempfile
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def summary(values):
    values = np.asarray(values)
    return {
        "mean": float(values.mean()),
        "median": float(np.median(values)),
        "p95": float(np.percentile(values, 95)),
        "maximum": float(values.max()),
    }


def data_stats(points):
    tips = points[:, [4, 8, 12, 16, 20]]
    pinch = np.linalg.norm(tips[:, 1:] - tips[:, :1], axis=2)
    pip, mcp = [], []
    for base in (5, 9, 13, 17):
        proximal = points[:, base + 1] - points[:, base]
        middle = points[:, base + 2] - points[:, base + 1]
        cos = np.sum(proximal * middle, axis=1) / (
            np.linalg.norm(proximal, axis=1) * np.linalg.norm(middle, axis=1)
        )
        pip.append(np.degrees(np.arccos(np.clip(cos, -1, 1))))
        mcp.append(np.degrees(np.arctan2(proximal[:, 0], proximal[:, 2])))
    pip, mcp = np.array(pip).T, np.array(mcp).T
    return {
        "frames": len(points),
        "palm_length_m": summary(np.linalg.norm(points[:, 9], axis=1)),
        "thumb_pair_under_15mm_counts": (pinch < 0.015).sum(axis=0).tolist(),
        "nonthumb_mean_pip_bend_deg": pip.mean(axis=0).tolist(),
        "fist_candidate_count_pip60_mcp45": int(
            ((pip > 60).all(axis=1) & (mcp > 45).all(axis=1)).sum()
        ),
    }


def control_stats(path):
    lag, tracking, jumps, ages = [], [], [], []
    previous = None
    statuses = {}
    for line in path.open():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            break  # A live writer may be appending its final line.
        status = entry.get("control_status")
        statuses[status] = statuses.get(status, 0) + 1
        if status != "TRACKING":
            previous = None
            continue
        target = np.array(entry["retarget_q_target"])
        sim = entry["simulation"]
        lag.append(np.max(np.abs(target - sim["q_command"])))
        tracking.append(np.max(np.abs(np.array(sim["q_actual"]) - sim["q_command"])))
        ages.append(entry["input_age_s"])
        if previous is not None:
            jumps.append(np.max(np.abs(target - previous)))
        previous = target
    return {
        "statuses": statuses,
        "max_joint_target_command_gap_rad": summary(lag),
        "max_joint_command_actual_gap_rad": summary(tracking),
        "max_target_jump_per_control_tick_rad": summary(jumps),
        "fraction_ticks_target_jump_exceeds_pi_per_s_20ms": float(
            (np.array(jumps) > np.pi * 0.02).mean()
        ),
        "input_age_s": summary(ages),
    }


def main():
    from benchmark.geort_support.input import canonical_points
    from benchmark.retargeting.geort import GeoRTRetargeter
    from benchmark.simulation.robot_model import RobotModel
    from benchmark.tracking.recorder import replay_frames

    study = ROOT / "results/geort_data_size_20261018"
    live = ROOT / "results/live-retargeting-x2117cq6"
    output = Path(tempfile.mkdtemp(prefix="geort-diagnosis-", dir=ROOT / "results"))
    raw = (live / "quest_input.jsonl").read_bytes()
    raw = raw[: raw.rfind(b"\n") + 1]
    snapshot = output / "live_input_snapshot.jsonl"
    snapshot.write_bytes(raw)
    frames = list(replay_frames(snapshot, handedness="right", include_invalid=False))
    live_points = np.array([canonical_points(frame) for frame in frames])
    models = json.loads((study / "models.json").read_text())
    robot = RobotModel()
    report = {
        "live_source": str(live),
        "live_snapshot_sha256": hashlib.sha256(raw).hexdigest(),
        "live_valid_frames": len(frames),
        "data": {},
        "models": {},
        "policy": "diagnosis only; validation split and live observation; test split untouched; "
        "raw distances compare human wrist and robot palm, not independent ground-truth error",
    }
    np.save(output / "live_canonical.npy", live_points)
    evaluation = {
        "public_validation": np.load(study / "datasets/validation/human.npy"),
        "live_quest": live_points,
    }
    for key, values in evaluation.items():
        report["data"][key] = data_stats(values)
    for name, metadata in models.items():
        source = np.load(study / "datasets" / name / "human.npy")
        report["data"][name] = data_stats(source)
        adapter = GeoRTRetargeter(
            robot, checkpoint=metadata["checkpoint"], config_path=metadata["config"]
        )
        import torch

        model_report = {
            "input_frames": len(source),
            "sources": {},
            "eval_mode": not adapter.vendor.model.training,
            "control": control_stats(live / f"{name}.jsonl"),
        }
        text = (study / f"{name}_console.txt").read_text()
        rows = re.findall(
            r"^Epoch (\d+) \| Losses - Direction: (\S+) - Chamfer: (\S+) "
            r"- Curvature: (\S+) - Collision: (\S+) - Pinch: (\S+)",
            text,
            re.M,
        )
        model_report["logged_epochs"] = len(rows)
        model_report["first_logged_batch"] = list(map(float, rows[0][1:]))
        model_report["last_logged_batch"] = list(map(float, rows[-1][1:]))
        sources = {"own_training": source, **evaluation}
        trees = [cKDTree(source[:, tip]) for tip in (4, 8, 12, 16, 20)]
        for label, points in sources.items():
            indices = np.linspace(0, len(points) - 1, min(512, len(points)), dtype=int)
            sample = points[indices]
            hp = sample[:, [4, 8, 12, 16, 20]]
            with torch.inference_mode():
                normalized = adapter.vendor.model(torch.from_numpy(hp).float().cuda()).cpu().numpy()
            raw_q = adapter.vendor.qpos_normalizer.unnormalize(normalized)
            np.testing.assert_allclose(raw_q[0], adapter.vendor.forward(sample[0]), atol=1e-5)
            q = np.array([robot.validate_target(row, clip=True) for row in raw_q])
            rp = np.array([robot.forward_kinematics(row, frame="palm") for row in q])
            nearest = np.stack(
                [tree.query(hp[:, finger])[0] for finger, tree in enumerate(trees)], axis=1
            )
            hd = np.linalg.norm(hp[:, 1:] - hp[:, :1], axis=2)
            rd = np.linalg.norm(rp[:, 1:] - rp[:, :1], axis=2)
            masks = hd < 0.015
            error = np.linalg.norm(rp - hp, axis=2) * 1000
            limit_scale = (q - robot.limits[:, 0]) / (robot.limits[:, 1] - robot.limits[:, 0])
            model_report["sources"][label] = {
                "raw_joint_bound_excess_max_rad": float(np.max(np.abs(q - raw_q))),
                "frames_sampled": len(sample),
                "tip_correspondence_mm": summary(error),
                "per_finger_mean_correspondence_mm": error.mean(axis=0).tolist(),
                "nearest_training_tip_mm": summary(nearest * 1000),
                "fraction_finger_inputs_over_5mm_from_training": float((nearest > 0.005).mean()),
                "fraction_joint_outputs_within_5percent_of_limit": float(
                    ((limit_scale < 0.05) | (limit_scale > 0.95)).mean()
                ),
                "human_pinch_pair_candidates": int(masks.sum()),
                "robot_pair_distance_on_candidates_mm": summary(rd[masks] * 1000)
                if masks.any()
                else None,
                "joint_excursion_rad": np.ptp(q, axis=0).tolist(),
            }
            np.savez_compressed(
                output / f"{name}_{label}.npz",
                source_indices=indices,
                q=q,
                human_tips=hp,
                robot_tips=rp,
                nearest_training_m=nearest,
            )
        report["models"][name] = model_report
    (output / "diagnosis.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(str(output), flush=True)
    for name, entry in report["models"].items():
        print(
            name,
            json.dumps(
                {
                    label: {
                        "error_mm": round(v["tip_correspondence_mm"]["mean"], 2),
                        "nn_mm": round(v["nearest_training_tip_mm"]["mean"], 2),
                        "outside_5mm": round(v["fraction_finger_inputs_over_5mm_from_training"], 3),
                    }
                    for label, v in entry["sources"].items()
                }
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
