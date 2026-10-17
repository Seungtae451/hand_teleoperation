#!/usr/bin/env python3
"""Build/verify a source-derived Allegro-reference profile; train only on explicit command."""

import argparse
import json
import shutil
import sys
import xml.etree.ElementTree as ET
from functools import partial
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def prepare(folder, profile_path):
    from benchmark.geort_support.reference_ranges import verify_profile
    from benchmark.geort_support.runtime import load_workspace
    from benchmark.geort_support.source import enable_upstream
    from scripts.geort_range_study import SEED, save, sha

    profile = verify_profile(profile_path)
    _, config = load_workspace(ROOT / "results/geort_dg5f_workspace")
    enable_upstream()
    from geort.env.hand import HandKinematicModel

    folder.mkdir(parents=True, exist_ok=False)
    save(folder / "profile.json", profile)
    full = np.array(profile["official_bounds_rad"])
    limited = np.array(profile["bounds_rad"])
    changed = np.flatnonzero(np.any(full != limited, axis=1))
    fk = (
        ROOT
        / "results/geort_dg5f_workspace/training-f9nel4wo/checkpoint/fk_model_dg5f_right_geort.pth"
    )
    human = ROOT / "data/geort/quest_train_session_002/human.npy"
    manifest = json.loads((human.parent / "manifest.json").read_text())
    assert manifest["split"] == "train" and sha(human) == manifest["npy_sha256"]
    hand = HandKinematicModel.build_from_config(config, render=False)
    tips = config["fingertip_link"]
    links = [t["link"] for t in tips]
    hand.initialize_keypoint(links, [t["center_offset"] for t in tips])
    u = np.random.RandomState(SEED).uniform(0, 1, (100000, 20))
    for name, bounds in [("full", full), ("restricted", limited)]:
        run = folder / name
        run.mkdir()
        derived = json.loads(json.dumps(config))
        if name == "restricted":
            tree = ET.parse(config["urdf_path"])
            nodes = {j.get("name"): j for j in tree.getroot().findall("joint")}
            for i in changed:
                limit = nodes[config["joint_order"][i]].find("limit")
                limit.set("lower", str(bounds[i, 0]))
                limit.set("upper", str(bounds[i, 1]))
            path = run / "dg5f_reference_range.urdf"
            tree.write(path, encoding="utf-8", xml_declaration=True)
            derived["urdf_path"] = str(path)
        derived["joint"] = {"lower": bounds[:, 0].tolist(), "upper": bounds[:, 1].tolist()}
        save(run / "config.json", derived)
        (run / "checkpoint").mkdir()
        (run / "data").mkdir()
        shutil.copyfile(fk, run / "checkpoint/fk_model_dg5f_right_geort.pth")
        q = u * (bounds[:, 1] - bounds[:, 0]) + bounds[:, 0]
        p = np.array([hand.keypoint_from_qpos(row, ret_vec=True) for row in q])
        np.savez(
            run / "data/dg5f_right_geort.npz",
            qpos=q,
            keypoint={link: p[:, i] for i, link in enumerate(links)},
        )
    save(
        folder / "study.json",
        {
            "seed": SEED,
            "profile_id": profile["profile_id"],
            "profile_sha256": sha(folder / "profile.json"),
            "full_bounds": full.tolist(),
            "restricted_bounds": limited.tolist(),
            "restricted_joint_indices": changed.tolist(),
            "restricted_joint_names": [config["joint_order"][i] for i in changed],
            "human_data": str(human),
            "human_sha256": sha(human),
            "training_frames": manifest["frames"],
            "shared_full_range_fk": str(fk),
            "fk_sha256": sha(fk),
            "change": (
                "Pinned Allegro flexion range intersection, 9 joints. Same FK "
                "via original controlled range normalization adapter. No loss, "
                "gain, coupling or input change."
            ),
            "experimental_not_official_calibration": True,
            "original_urdf_modified": False,
        },
    )
    print(f"Prepared {folder}; training NOT started")


def check(folder):
    from benchmark.geort_support.reference_ranges import verify_profile
    from benchmark.geort_support.source import enable_upstream
    from benchmark.simulation.robot_model import RobotModel
    from scripts.geort_range_study import save, sha

    profile = verify_profile(folder / "profile.json")
    doc = json.loads((folder / "study.json").read_text())
    assert sha(folder / "profile.json") == doc["profile_sha256"]
    enable_upstream()
    from geort.env.hand import HandKinematicModel

    cfg = json.loads((folder / "restricted/config.json").read_text())
    hand = HandKinematicModel.build_from_config(cfg, render=False)
    tips = cfg["fingertip_link"]
    hand.initialize_keypoint([t["link"] for t in tips], [t["center_offset"] for t in tips])
    bounds = np.array(profile["bounds_rad"])
    np.testing.assert_allclose(hand.get_joint_limit(), bounds.T, atol=1e-7)
    robot = RobotModel()
    errors = []
    for q in np.random.default_rng(20261018).uniform(bounds[:, 0], bounds[:, 1], (100, 20)):
        a = hand.keypoint_from_qpos(q, ret_vec=True)
        b = robot.forward_kinematics(q, frame="palm")
        np.testing.assert_allclose(a, b, atol=2e-6)
        errors.append(float(np.max(np.linalg.norm(a - b, axis=1)) * 1000))
    clouds = [
        np.load(folder / n / "data/dg5f_right_geort.npz", allow_pickle=True)
        for n in ["full", "restricted"]
    ]
    full = robot.limits
    np.testing.assert_allclose(
        (clouds[0]["qpos"] - full[:, 0]) / (full[:, 1] - full[:, 0]),
        (clouds[1]["qpos"] - bounds[:, 0]) / (bounds[:, 1] - bounds[:, 0]),
        atol=1e-14,
    )
    # Derived URDF is identical after restoring exactly the declared changed attributes.
    original = ET.parse(json.loads((folder / "full/config.json").read_text())["urdf_path"])
    derived = ET.parse(cfg["urdf_path"])
    old = {j.get("name"): j for j in original.getroot().findall("joint")}
    for j in derived.getroot().findall("joint"):
        if j.get("name") in doc["restricted_joint_names"]:
            for key in ["lower", "upper"]:
                j.find("limit").set(key, old[j.get("name")].find("limit").get(key))
    assert ET.tostring(original.getroot()) == ET.tostring(derived.getroot())
    for n in ["full", "restricted"]:
        assert sha(folder / n / "checkpoint/fk_model_dg5f_right_geort.pth") == doc["fk_sha256"]
    result = {
        "profile_verified": True,
        "mapped_joints": len(profile["mappings"]),
        "unmapped_joints": len(profile["unmapped"]),
        "derived_urdf_only_declared_ranges_changed": True,
        "paired_uniform_samples_identical": True,
        "shared_fk_identical": True,
        "sapien_official_mujoco_fk_max_mm": max(errors),
        "geometry_cases": 100,
        "training_executed": False,
    }
    save(folder / "preparation_verification.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["profile", "prepare", "check", "train", "infer"])
    parser.add_argument(
        "--profile", type=Path, default=ROOT / "configs/geort/allegro_reference_v1.json"
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--input", type=Path, default=ROOT / "recordings/quest_eval_session_001.jsonl"
    )
    parser.add_argument("--viewer", action="store_true")
    args = parser.parse_args()
    from benchmark.paths import writable_output

    if args.command == "profile":
        from benchmark.geort_support.reference_ranges import build_profile

        p = writable_output(args.profile)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("x") as f:
            json.dump(build_profile(), f, indent=2)
        print(p)
    else:
        if args.output is None:
            parser.error("--output study directory is required")
        folder = writable_output(args.output)
        if args.command == "prepare":
            prepare(folder, args.profile)
        elif args.command == "check":
            check(folder)
        elif args.command == "train":
            from scripts.geort_range_study import train

            check(folder)
            train(folder)
        else:
            import tempfile

            from benchmark.experiments.offline_benchmark import run_method
            from benchmark.geort_support.reference_ranges import ReferenceRangeRetargeter
            from benchmark.retargeting import registry
            from benchmark.tracking.recorder import replay_frames
            from scripts.geort_range_study import sha

            meta = json.loads((folder / "restricted/manifest.json").read_text())
            doc = json.loads((folder / "study.json").read_text())
            assert (
                meta["status"] == "completed"
                and sha(meta["checkpoint"]) == meta["checkpoint_sha256"]
                and meta["input_sha256"] == doc["human_sha256"]
            )
            registry.register(
                "geort",
                partial(
                    ReferenceRangeRetargeter,
                    checkpoint=meta["checkpoint"],
                    config_path=meta["config"],
                    profile=folder / "profile.json",
                ),
            )
            dest = Path(tempfile.mkdtemp(prefix="reference-range-inference-", dir=ROOT / "results"))
            print(
                json.dumps(
                    run_method(
                        list(replay_frames(args.input, handedness="right")),
                        "geort",
                        dest,
                        viewer=args.viewer,
                    ),
                    indent=2,
                )
            )
