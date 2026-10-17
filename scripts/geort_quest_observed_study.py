#!/usr/bin/env python3
"""Train-only observed distal upper bounds, explicit experimental zero lower bounds."""

import argparse
import json
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.geort_range_study import SEED, save, sha, train  # noqa: E402


def prepare(folder):
    from benchmark.geort_support.source import enable_upstream
    from benchmark.simulation.robot_model import RobotModel

    source = ROOT / "results/geort_range_study_20261018"
    observed = ROOT / "results/quest_observed_ranges_session002_verified/observed_ranges.json"
    stats = json.loads(observed.read_text())
    old = json.loads((source / "study.json").read_text())
    human = Path(old["human_data"])
    manifest = json.loads((human.parent / "manifest.json").read_text())
    assert manifest["split"] == "train" and sha(human) == old["human_sha256"]
    assert manifest["source_recording_sha256"] == stats["source_sha256"]
    assert sha(stats["source_recording"]) == stats["source_sha256"]
    robot = RobotModel()
    full, bounds = robot.limits.copy(), robot.limits.copy()
    mappings = []
    for f, finger in [(2, "index"), (3, "middle"), (4, "ring")]:
        for j, human_joint in [(3, "pip"), (4, "dip")]:
            name = f"rj_dg_{f}_{j}"
            i = robot.joint_names.index(name)
            measure = f"{finger}_{human_joint}_unsigned_bend"
            maximum = stats["native_joint_angles"][measure]["maximum_deg"]
            bounds[i] = [0, min(full[i, 1], np.radians(maximum))]
            mappings.append(
                {
                    "joint": name,
                    "measure": measure,
                    "observed_max_deg": maximum,
                    "applied_bounds_deg": np.degrees(bounds[i]).tolist(),
                }
            )
    changed = np.flatnonzero(np.any(bounds != full, axis=1))
    assert len(changed) == 6
    folder.mkdir(parents=True, exist_ok=False)
    profile = {
        "profile_id": "quest_observed_distal_six_v1",
        "observed_statistics": str(observed),
        "observed_statistics_sha256": sha(observed),
        "recording_sha256": stats["source_sha256"],
        "training_frames": stats["valid_native_frames"],
        "bounds_rad": bounds.tolist(),
        "official_bounds_rad": full.tolist(),
        "mappings": mappings,
        "lower_policy": (
            "Zero is an explicit experimental flexion-only constraint, NOT measured ROM"
        ),
        "upper_policy": "Raw observed training maximum intersected with official limit",
        "unmapped_policy": "MCP, spread, thumb and pinky retain official limits",
        "experimental_not_official_calibration": True,
    }
    save(folder / "profile.json", profile)
    enable_upstream()
    from geort.env.hand import HandKinematicModel

    config = json.loads((source / "full/config.json").read_text())
    hand = HandKinematicModel.build_from_config(config, render=False)
    tips = config["fingertip_link"]
    links = [t["link"] for t in tips]
    hand.initialize_keypoint(links, [t["center_offset"] for t in tips])
    u = np.random.RandomState(SEED).uniform(0, 1, (100000, 20))
    for name, limits in [("full", full), ("restricted", bounds)]:
        run = folder / name
        (run / "data").mkdir(parents=True)
        (run / "checkpoint").mkdir()
        derived = json.loads(json.dumps(config))
        if name == "restricted":
            tree = ET.parse(config["urdf_path"])
            nodes = {j.get("name"): j for j in tree.getroot().findall("joint")}
            for i in changed:
                limit = nodes[robot.joint_names[i]].find("limit")
                limit.set("lower", str(limits[i, 0]))
                limit.set("upper", str(limits[i, 1]))
            path = run / "training_bounds.urdf"
            tree.write(path, encoding="utf-8", xml_declaration=True)
            derived["urdf_path"] = str(path)
        derived["joint"] = {"lower": limits[:, 0].tolist(), "upper": limits[:, 1].tolist()}
        save(run / "config.json", derived)
        shutil.copyfile(
            old["shared_full_range_fk"], run / "checkpoint/fk_model_dg5f_right_geort.pth"
        )
        q = u * (limits[:, 1] - limits[:, 0]) + limits[:, 0]
        if name == "full":
            prior = np.load(source / "full/data/dg5f_right_geort.npz", allow_pickle=True)
            np.testing.assert_array_equal(q, prior["qpos"])
            shutil.copyfile(
                source / "full/data/dg5f_right_geort.npz", run / "data/dg5f_right_geort.npz"
            )
        else:
            p = np.array([hand.keypoint_from_qpos(row, ret_vec=True) for row in q])
            np.savez(
                run / "data/dg5f_right_geort.npz",
                qpos=q,
                keypoint={link: p[:, i] for i, link in enumerate(links)},
            )
    save(
        folder / "study.json",
        {
            **old,
            "full_bounds": full.tolist(),
            "restricted_bounds": bounds.tolist(),
            "restricted_joint_indices": changed.tolist(),
            "restricted_joint_names": [robot.joint_names[i] for i in changed],
            "profile_id": profile["profile_id"],
            "profile_sha256": sha(folder / "profile.json"),
            "change": (
                "Six verified PIP/DIP axes only: explicit zero lower, "
                "observed maximum upper; no MCP calibration"
            ),
        },
    )
    print(f"Prepared {folder}", flush=True)


def verified_train(folder):
    from benchmark.geort_support.source import enable_upstream
    from benchmark.simulation.robot_model import RobotModel

    enable_upstream()
    from geort.env.hand import HandKinematicModel

    doc = json.loads((folder / "study.json").read_text())
    assert sha(folder / "profile.json") == doc["profile_sha256"]
    cfg = json.loads((folder / "restricted/config.json").read_text())
    original_cfg = json.loads((folder / "full/config.json").read_text())
    a, b = ET.parse(original_cfg["urdf_path"]), ET.parse(cfg["urdf_path"])
    original_nodes = {j.get("name"): j for j in a.getroot().findall("joint")}
    for j in b.getroot().findall("joint"):
        if j.get("name") in doc["restricted_joint_names"]:
            for attr in ["lower", "upper"]:
                j.find("limit").set(attr, original_nodes[j.get("name")].find("limit").get(attr))
    assert ET.tostring(a.getroot()) == ET.tostring(b.getroot())
    hand = HandKinematicModel.build_from_config(cfg, render=False)
    tips = cfg["fingertip_link"]
    hand.initialize_keypoint([t["link"] for t in tips], [t["center_offset"] for t in tips])
    bounds = np.array(doc["restricted_bounds"])
    np.testing.assert_allclose(hand.get_joint_limit(), bounds.T, atol=1e-7)
    robot = RobotModel()
    errors = []
    for q in np.random.default_rng(SEED).uniform(*bounds.T, (100, 20)):
        expected = robot.forward_kinematics(q, frame="palm")
        actual = hand.keypoint_from_qpos(q, ret_vec=True)
        np.testing.assert_allclose(actual, expected, atol=2e-6)
        errors.append(float(np.linalg.norm(actual - expected, axis=1).max() * 1000))
    for name in ["full", "restricted"]:
        assert sha(folder / name / "checkpoint/fk_model_dg5f_right_geort.pth") == doc["fk_sha256"]
    save(
        folder / "preparation_verification.json",
        {
            "derived_urdf_only_declared_ranges_changed": True,
            "shared_fk_identical": True,
            "fk_cases": 100,
            "fk_max_mm": max(errors),
        },
    )
    train(folder)


def check(folder):
    import torch
    from scipy.stats import spearmanr

    from benchmark.geort_support.source import enable_upstream
    from benchmark.simulation.robot_model import RobotModel
    from scripts.compare_allegro_control import geometry

    enable_upstream()
    from geort.export import GeoRTRetargetingModel

    doc = json.loads((folder / "study.json").read_text())
    assert sha(folder / "profile.json") == doc["profile_sha256"]
    robot = RobotModel()
    points = np.load(ROOT / "data/geort/quest_eval_session_001/human.npy")
    pip, mcp = geometry(points)
    masks = {
        "open": (pip < 25).all(axis=1) & (np.abs(mcp) < 25).all(axis=1),
        "fist": (pip > 60).all(axis=1) & (np.abs(mcp) > 45).all(axis=1),
    }
    report = {
        "scope": "Already inspected evaluation recording; diagnostic, not blind test",
        "conditions": {},
    }
    arrays = {"human": points, **{f"{k}_mask": v for k, v in masks.items()}}
    for name in ["full", "restricted"]:
        meta = json.loads((folder / name / "manifest.json").read_text())
        assert (
            meta["status"] == "completed" and sha(meta["checkpoint"]) == meta["checkpoint_sha256"]
        )
        model = GeoRTRetargetingModel(meta["checkpoint"], meta["config"])
        with torch.inference_mode():
            n = model.model(
                torch.tensor(points[:, model.human_ids], device="cuda", dtype=torch.float32)
            )
        q = model.qpos_normalizer.unnormalize(n.cpu().numpy())
        bounds = np.array(doc["full_bounds"] if name == "full" else doc["restricted_bounds"])
        assert np.isfinite(q).all() and (q >= bounds[:, 0] - 1e-6).all()
        assert (q <= bounds[:, 1] + 1e-6).all()
        tips = np.array([robot.forward_kinematics(row, frame="palm") for row in q])
        flex = q[:, 4:16].reshape(-1, 3, 4)[:, :, 1:].sum(axis=2)
        report["conditions"][name] = {
            "frames": len(q),
            "checkpoint_sha256": meta["checkpoint_sha256"],
            "bounds_pass": True,
            "pip_vs_total_flexion_spearman": [
                float(spearmanr(pip[:, i], flex[:, i]).statistic) for i in range(3)
            ],
            "gestures": {
                k: {
                    "frames": int(mask.sum()),
                    "joint_mean_deg": np.degrees(q[mask].mean(axis=0)).reshape(5, 4).tolist(),
                }
                for k, mask in masks.items()
            },
        }
        arrays.update({f"{name}_q": q, f"{name}_tips": tips})
    save(folder / "comparison.json", report)
    np.savez_compressed(folder / "eval_outputs.npz", **arrays)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "train", "check"])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    {"prepare": prepare, "train": verified_train, "check": check}[args.command](
        args.output.resolve()
    )
