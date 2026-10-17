#!/usr/bin/env python3
"""Same-input original Allegro vs DG-5F diagnostics; no loss/config tuning."""

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def geometry(p):
    pip, mcp = [], []
    for b in [5, 9, 13]:
        u, v = p[:, b + 1] - p[:, b], p[:, b + 2] - p[:, b + 1]
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
    return np.array(pip).T, np.array(mcp).T


def build_mujoco(config, output):
    import mujoco

    tree = ET.parse(config["urdf_path"])
    root = tree.getroot()
    for mesh in root.iter("mesh"):
        mesh.set(
            "filename", str((Path(config["urdf_path"]).parent / mesh.get("filename")).resolve())
        )
    ext = ET.SubElement(root, "mujoco")
    ET.SubElement(ext, "compiler", fusestatic="false", strippath="false", balanceinertia="true")
    urdf = output / "allegro_mujoco_import.urdf"
    tree.write(urdf)
    model = mujoco.MjModel.from_xml_path(str(urdf))
    assert model.nq == 16
    path = output / "allegro_mujoco.xml"
    mujoco.mj_saveLastXML(str(path), model)
    xml = ET.parse(path)
    bodies = {b.get("name"): b for b in xml.getroot().findall(".//body")}
    for i, tip in enumerate(config["fingertip_link"]):
        ET.SubElement(
            bodies[tip["link"]],
            "site",
            name=f"tip_{i}",
            pos=" ".join(map(str, tip["center_offset"])),
            size=".003",
        )
    xml.write(path)
    return mujoco.MjModel.from_xml_path(str(path))


def main(folder):
    import mujoco
    import torch
    from scipy.stats import spearmanr

    from benchmark.geort_support.source import enable_upstream
    from benchmark.simulation.robot_model import RobotModel

    enable_upstream()
    from geort.env.hand import HandKinematicModel
    from geort.export import GeoRTRetargetingModel
    from geort.formatter import HandFormatter
    from geort.model import FKModel
    from geort.utils.config_utils import parse_config_keypoint_info

    cfg = json.loads((folder / "config.json").read_text())
    hand = HandKinematicModel.build_from_config(cfg, render=False)
    hand.initialize_keypoint(
        [k["link"] for k in cfg["fingertip_link"]],
        [k["center_offset"] for k in cfg["fingertip_link"]],
    )
    limits = np.array(hand.get_joint_limit()).T
    robot = RobotModel()
    report = {
        "policy": (
            "Same original loss/default epochs and seed; no tuning. Exact FK "
            "static comparison, not dynamic/contact success. Original Allegro "
            "uses upstream-provided FK; DG uses previously trained FK. Single "
            "seed and distinct robot geometry prevent a causal joint-limit-only "
            "conclusion. All raw tip distances compare different anatomical "
            "origins, not ground-truth error."
        ),
        "source_commit": "fb2075e2a3272be372016580c0b6ebd6120228f0",
        "allegro_mujoco_derivative": (
            "Compiler balanceinertia=true required by original inertial values; "
            "used for static FK/visualization only, not dynamics validation"
        ),
        "allegro_joint_limits_deg": np.degrees(limits).tolist(),
        "dg_joint_limits_deg": np.degrees(robot.limits).tolist(),
        "cases": {},
    }
    mj = build_mujoco(cfg, folder)
    mjdata = mujoco.MjData(mj)
    adr = [mj.jnt_qposadr[mj.joint(n).id] for n in cfg["joint_order"]]
    sites = [mj.site(f"tip_{i}").id for i in range(4)]
    base = mj.body("base_link").id
    rng = np.random.default_rng(20261018)
    qs = rng.uniform(limits[:, 0], limits[:, 1], size=(256, 16))
    exact = np.array([hand.keypoint_from_qpos(q, ret_vec=True) for q in qs])
    mjpoints = []
    for q in qs:
        mjdata.qpos[adr] = q
        mujoco.mj_forward(mj, mjdata)
        mjpoints.append(
            (mjdata.site_xpos[sites] - mjdata.xpos[base]) @ mjdata.xmat[base].reshape(3, 3)
        )
    err = np.linalg.norm(exact - np.array(mjpoints), axis=2) * 1000
    assert err.max() < 0.02
    report["allegro_sapien_mujoco_fk_max_mm"] = float(err.max())
    neural = FKModel(parse_config_keypoint_info(cfg)["joint"]).cuda()
    neural.load_state_dict(
        torch.load(folder / "checkpoint/fk_model_allegro_right.pth", weights_only=True)
    )
    neural.eval()
    with torch.inference_mode():
        nn = (
            neural(
                torch.tensor(
                    HandFormatter(*hand.get_joint_limit()).normalize(qs),
                    dtype=torch.float32,
                    device="cuda",
                )
            )
            .cpu()
            .numpy()
        )
    nnerr = np.linalg.norm(nn - exact, axis=2) * 1000
    report["provided_allegro_fk_error_mm"] = {
        "mean": float(nnerr.mean()),
        "max": float(nnerr.max()),
    }
    report["model_provenance"] = {}
    personal = json.loads(
        (ROOT / "results/geort_personal_session002_eval/model_verification.json").read_text()
    )
    official = json.loads((ROOT / "results/geort_data_size_20261018/models.json").read_text())[
        "official_3498"
    ]
    for cond in ["official_alex", "personal_quest"]:
        manifest = json.loads((folder / "models" / cond / "manifest.json").read_text())
        epochs = re.findall(r"^Epoch (\d+) \|", (folder / f"{cond}_console.txt").read_text(), re.M)
        assert list(map(int, epochs)) == list(range(200))
        report["model_provenance"][cond] = manifest
        amodel = GeoRTRetargetingModel(manifest["checkpoint"], manifest["config"])
        dgmeta = official if cond == "official_alex" else personal
        dmodel = GeoRTRetargetingModel(dgmeta["checkpoint"], dgmeta["config"])
        report["model_provenance"][f"dg_{cond}"] = {
            "checkpoint": dgmeta["checkpoint"],
            "config": dgmeta["config"],
            "checkpoint_sha256": dgmeta["checkpoint_sha256"],
        }
        inputs = {
            "own_training": np.load(manifest["input"]),
            "quest_eval": np.load(ROOT / "data/geort/quest_eval_session_001/human.npy"),
        }
        for source, p in inputs.items():
            pip, mcp = geometry(p)
            masks = {
                "open": (pip < 25).all(axis=1) & (np.abs(mcp) < 25).all(axis=1),
                "fist": (pip > 60).all(axis=1) & (np.abs(mcp) > 45).all(axis=1),
            }
            source_result = {}
            artifacts = {}
            for gesture, mask in masks.items():
                ids = np.flatnonzero(mask)
                if len(ids) > 256:
                    ids = ids[np.linspace(0, len(ids) - 1, 256, dtype=int)]
                if not len(ids):
                    source_result[gesture] = {"candidate_frames": 0}
                    continue
                sample = p[ids]
                outputs = {}
                for robot_name, model, definition in [
                    ("allegro", amodel, cfg),
                    ("dg5f", dmodel, robot.config),
                ]:
                    human_ids = model.human_ids
                    with torch.inference_mode():
                        norm = (
                            model.model(
                                torch.tensor(
                                    sample[:, human_ids], dtype=torch.float32, device="cuda"
                                )
                            )
                            .cpu()
                            .numpy()
                        )
                    q = model.qpos_normalizer.unnormalize(norm)
                    if robot_name == "allegro":
                        rp = np.array([hand.keypoint_from_qpos(row, ret_vec=True) for row in q])
                        nonthumb = q[:, :12].reshape(-1, 3, 4)
                    else:
                        rp = np.array([robot.forward_kinematics(row, frame="palm") for row in q])
                        nonthumb = q[:, 4:16].reshape(-1, 3, 4)
                    shared_ids = [8, 12, 16, 4]
                    shared_order = [list(human_ids).index(i) for i in shared_ids]
                    error = (
                        np.linalg.norm(rp[:, shared_order] - sample[:, shared_ids], axis=2) * 1000
                    )
                    outputs[robot_name] = {
                        "joint_mean_deg": np.degrees(q.mean(axis=0)).reshape(-1, 4).tolist(),
                        "nonthumb_distal_negative_fraction": (nonthumb[:, :, 2:] < -0.05)
                        .mean(axis=0)
                        .tolist(),
                        "nonthumb_flexion_sum_mean_deg": np.degrees(
                            nonthumb[:, :, 1:].sum(axis=2).mean(axis=0)
                        ).tolist(),
                        "raw_shared_4finger_tip_distance_mean_mm": float(error.mean()),
                    }
                    artifacts[f"{gesture}_{robot_name}_q"] = q
                    artifacts[f"{gesture}_{robot_name}_tips"] = rp
                source_result[gesture] = {
                    "candidate_frames": int(mask.sum()),
                    "sampled": len(ids),
                    "human_pip_mean_deg": pip[ids].mean(axis=0).tolist(),
                    "models": outputs,
                }
                artifacts[f"{gesture}_human"] = sample
                artifacts[f"{gesture}_source_indices"] = ids
            # Correlation of human PIP bend and summed robot flexion, shared 3 fingers.
            ids = np.linspace(0, len(p) - 1, min(512, len(p)), dtype=int)
            for label, model in [("allegro", amodel), ("dg5f", dmodel)]:
                with torch.inference_mode():
                    norm = (
                        model.model(
                            torch.tensor(
                                p[ids][:, model.human_ids], dtype=torch.float32, device="cuda"
                            )
                        )
                        .cpu()
                        .numpy()
                    )
                q = model.qpos_normalizer.unnormalize(norm)
                joints = q[:, :12] if label == "allegro" else q[:, 4:16]
                sums = joints.reshape(-1, 3, 4)[:, :, 1:].sum(axis=2)
                source_result[f"{label}_pip_vs_robot_flexion_spearman"] = [
                    float(spearmanr(pip[ids, f], sums[:, f]).statistic) for f in range(3)
                ]
            report["cases"][f"{cond}_{source}"] = source_result
            np.savez_compressed(folder / f"comparison_{cond}_{source}.npz", **artifacts)
    save(folder / "comparison.json", report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    main(parser.parse_args().output.resolve())
