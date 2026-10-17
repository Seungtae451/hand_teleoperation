#!/usr/bin/env python3
"""Same Quest evaluation inputs and common MuJoCo control for paired range models."""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main(folder):
    import torch
    from scipy.stats import spearmanr

    from benchmark.experiments.manus_control import ManusController
    from benchmark.geort_support.range_experiment import (
        RangeRetargeter,
        normalization_affine,
        restricted_bounds,
    )
    from benchmark.geort_support.source import enable_upstream
    from benchmark.retargeting.geort import GeoRTRetargeter
    from benchmark.retargeting.manus import DEFAULT_MANUS_CONFIG
    from benchmark.simulation.robot_model import RobotModel
    from benchmark.tracking.recorder import replay_frames
    from scripts.compare_allegro_control import geometry

    enable_upstream()
    from geort.export import GeoRTRetargetingModel
    from geort.model import FKModel
    from geort.utils.config_utils import parse_config_keypoint_info

    doc = json.loads((folder / "study.json").read_text())
    robot = RobotModel()
    points = np.load(ROOT / "data/geort/quest_eval_session_001/human.npy")
    pip, mcp = geometry(points)
    groups = {
        "open": (pip < 25).all(axis=1) & (np.abs(mcp) < 25).all(axis=1),
        "fist": (pip > 60).all(axis=1) & (np.abs(mcp) > 45).all(axis=1),
    }
    report = {
        "policy": (
            "Paired experimental ablation; same 12998 training frames, seed, "
            "exact initial IK tensors, full-range FK weights. Only range and "
            "corresponding target workspace/normalization change. Fixed "
            "already-inspected eval recording; diagnostic, not blind test. "
            "Pinch means geometric candidates, not contact success."
        ),
        "study": doc,
        "conditions": {},
    }
    artifacts = {}
    for name in ["full", "restricted"]:
        manifest = json.loads((folder / name / "manifest.json").read_text())
        model = GeoRTRetargetingModel(manifest["checkpoint"], manifest["config"])
        with torch.inference_mode():
            normalized = (
                model.model(
                    torch.tensor(points[:, model.human_ids], dtype=torch.float32, device="cuda")
                )
                .cpu()
                .numpy()
            )
        raw_q = model.qpos_normalizer.unnormalize(normalized)
        q = np.array([robot.validate_target(row, clip=True) for row in raw_q])
        bounds = robot.limits if name == "full" else restricted_bounds(robot.limits)
        assert np.all(q >= bounds[:, 0] - 1e-6) and np.all(q <= bounds[:, 1] + 1e-6)
        rp = np.array([robot.forward_kinematics(row, frame="palm") for row in q])
        config = json.loads(Path(manifest["config"]).read_text())
        fk = FKModel(parse_config_keypoint_info(config)["joint"]).cuda()
        fk.load_state_dict(torch.load(doc["shared_full_range_fk"], weights_only=True))
        fk.eval()
        # Independent physical-radian normalization validates the training adapter.
        nfull = 2 * (q - robot.limits[:, 0]) / (robot.limits[:, 1] - robot.limits[:, 0]) - 1
        scale, bias = normalization_affine(bounds, robot.limits)
        np.testing.assert_allclose(normalized * scale + bias, nfull, atol=2e-7)
        with torch.inference_mode():
            pred = fk(torch.tensor(nfull, dtype=torch.float32, device="cuda")).cpu().numpy()
        result = {
            "checkpoint": manifest["checkpoint"],
            "checkpoint_sha256": manifest["checkpoint_sha256"],
            "common_official_limit_clipping_max_rad": float(np.max(np.abs(q - raw_q))),
            "neural_fk_vs_actual_mean_mm": float(np.linalg.norm(rp - pred, axis=2).mean() * 1000),
            "gestures": {},
        }
        for gesture, mask in groups.items():
            assert mask.any()
            result["gestures"][gesture] = {
                "frames": int(mask.sum()),
                "joint_mean_deg": np.degrees(q[mask].mean(axis=0)).reshape(5, 4).tolist(),
                "negative_nonthumb_distal_fraction": float(
                    (q[mask][:, [6, 7, 10, 11, 14, 15, 18, 19]] < -0.05).mean()
                ),
                "human_robot_raw_tip_mean_mm": float(
                    np.linalg.norm(rp[mask] - points[mask][:, [4, 8, 12, 16, 20]], axis=2).mean()
                    * 1000
                ),
            }
        flex = q[:, 4:16].reshape(-1, 3, 4)[:, :, 1:].sum(axis=2)
        result["pip_vs_flexion_spearman"] = [
            float(spearmanr(pip[:, i], flex[:, i]).statistic) for i in range(3)
        ]
        hp = points[:, [4, 8, 12, 16, 20]]
        hd = np.linalg.norm(hp[:, 1:] - hp[:, :1], axis=2)
        rd = np.linalg.norm(rp[:, 1:] - rp[:, :1], axis=2)
        result["pinch"] = {}
        for i, f in enumerate(["index", "middle", "ring", "pinky"]):
            mask = hd[:, i] < 0.015
            result["pinch"][f] = {
                "candidate_frames": int(mask.sum()),
                "robot_pair_mean_mm": float(rd[mask, i].mean() * 1000) if mask.any() else None,
            }
        # Exact same downstream controller and original full-range simulation.
        controller = ManusController(robot, DEFAULT_MANUS_CONFIG)
        cls = GeoRTRetargeter if name == "full" else RangeRetargeter
        controller.retargeter = cls(
            robot, checkpoint=manifest["checkpoint"], config_path=manifest["config"]
        )
        frames = list(
            replay_frames(ROOT / "recordings/quest_eval_session_001.jsonl", handedness="right")
        )
        origin = frames[0].timestamp
        cursor = 0
        tracked = 0
        command_error = []
        with (folder / f"{name}_eval_control.jsonl").open("x") as stream:
            for tick in range(int(np.ceil((frames[-1].timestamp - origin) * 50)) + 1):
                now = origin + tick / 50
                while cursor + 1 < len(frames) and frames[cursor + 1].timestamp <= now + 1e-10:
                    cursor += 1
                entry = controller.tick(frames[cursor], now)
                stream.write(json.dumps(entry, allow_nan=False) + "\n")
                tracked += int(entry["control_status"] == "TRACKING")
                s = entry["simulation"]
                command_error.append(
                    float(np.max(np.abs(np.array(s["q_actual"]) - s["q_command"])))
                )
            hold = controller.tick(None, frames[-1].timestamp + 1)
            assert hold["control_status"] == "HOLD_TRACKING_LOST"
        result["common_controller"] = {
            "tracking_ticks": tracked,
            "mean_max_joint_command_actual_error_rad": float(np.mean(command_error)),
            "tracking_loss_hold": True,
            "speed_limit_rad_s": controller.max_speed,
            "simulation_official_limits_unchanged": True,
        }
        report["conditions"][name] = result
        artifacts[f"{name}_q"] = q
        artifacts[f"{name}_q_vendor_raw"] = raw_q
        artifacts[f"{name}_tips"] = rp
    artifacts.update(human=points, open_mask=groups["open"], fist_mask=groups["fist"])
    np.savez_compressed(folder / "eval_outputs.npz", **artifacts)
    (folder / "comparison.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    main(p.parse_args().output.resolve())
