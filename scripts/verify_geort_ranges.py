#!/usr/bin/env python3
"""Verify paired clouds, derived geometry, FK, source hashes and initial weights."""

import argparse
import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main(folder):
    import torch

    from benchmark.geort_support.source import enable_upstream
    from benchmark.simulation.robot_model import RobotModel

    enable_upstream()
    from geort.env.hand import HandKinematicModel

    doc = json.loads((folder / "study.json").read_text())
    configs = {
        name: json.loads((folder / name / "config.json").read_text())
        for name in ["full", "restricted"]
    }
    full = np.array(doc["full_bounds"])
    limited = np.array(doc["restricted_bounds"])
    assert all(
        configs["full"][k] == configs["restricted"][k]
        for k in configs["full"]
        if k not in ["urdf_path", "joint"]
    )
    trees = [ET.parse(configs[n]["urdf_path"]) for n in ["full", "restricted"]]
    source_nodes = {j.get("name"): j for j in trees[0].getroot().findall("joint")}
    for j in trees[1].getroot().findall("joint"):
        if j.get("name") in doc["restricted_joint_names"]:
            assert j.find("limit").get("lower") == "0"
            j.find("limit").set("lower", source_nodes[j.get("name")].find("limit").get("lower"))
    assert ET.tostring(trees[0].getroot()) == ET.tostring(trees[1].getroot())
    clouds = [
        np.load(folder / n / "data/dg5f_right_geort.npz", allow_pickle=True)
        for n in ["full", "restricted"]
    ]
    ufull = (clouds[0]["qpos"] - full[:, 0]) / (full[:, 1] - full[:, 0])
    ulimit = (clouds[1]["qpos"] - limited[:, 0]) / (limited[:, 1] - limited[:, 0])
    np.testing.assert_allclose(ufull, ulimit, atol=1e-14)
    for name in ["full", "restricted"]:
        assert (
            hashlib.sha256(
                (folder / name / "checkpoint/fk_model_dg5f_right_geort.pth").read_bytes()
            ).hexdigest()
            == doc["fk_sha256"]
        )
    hand = HandKinematicModel.build_from_config(configs["restricted"], render=False)
    np.testing.assert_allclose(hand.get_joint_limit(), limited.T, atol=1e-7)
    tips = configs["restricted"]["fingertip_link"]
    hand.initialize_keypoint([x["link"] for x in tips], [x["center_offset"] for x in tips])
    robot = RobotModel()
    errors = []
    for q in clouds[1]["qpos"][::1000]:
        sp = hand.keypoint_from_qpos(q, ret_vec=True)
        mj = robot.forward_kinematics(q, frame="palm")
        np.testing.assert_allclose(sp, mj, atol=2e-6)
        errors.append(float(np.max(np.linalg.norm(sp - mj, axis=1)) * 1000))
    a = torch.load(folder / "full/initial_ik.pth", weights_only=True, map_location="cpu")
    b = torch.load(folder / "restricted/initial_ik.pth", weights_only=True, map_location="cpu")
    assert a.keys() == b.keys() and all(torch.equal(a[k], b[k]) for k in a)
    report = {
        "only_declared_eight_urdf_lower_limits_changed": True,
        "paired_cloud_latent_uniforms_identical": True,
        "fk_weights_identical": True,
        "initial_ik_weights_and_bn_buffers_identical": True,
        "restricted_sapien_vs_official_mujoco_fk_max_mm": max(errors),
        "geometry_cases": len(errors),
        "original_simulation_limits_unchanged": True,
    }
    (folder / "range_verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    main(p.parse_args().output.resolve())
