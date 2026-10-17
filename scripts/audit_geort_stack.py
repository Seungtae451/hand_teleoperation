#!/usr/bin/env python3
"""Read-only causal diagnostics: exact FK, neural FK, inferred targets and live control."""

import argparse
import json
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def stats(x):
    x = np.asarray(x)
    return {"mean": float(x.mean()), "p95": float(np.percentile(x, 95)), "max": float(x.max())}


def main(session):
    import torch
    from scipy.spatial import cKDTree

    from benchmark.geort_support.input import canonical_points
    from benchmark.geort_support.runtime import load_workspace
    from benchmark.geort_support.source import enable_upstream
    from benchmark.retargeting.geort import GeoRTRetargeter
    from benchmark.simulation.mujoco_runner import MujocoRunner
    from benchmark.simulation.robot_model import RobotModel
    from benchmark.tracking.recorder import replay_frames

    output = Path(tempfile.mkdtemp(prefix="geort-stack-audit-", dir=ROOT / "results"))
    _, config = load_workspace(ROOT / "results/geort_dg5f_workspace")
    enable_upstream()
    from geort.env.hand import HandKinematicModel
    from geort.formatter import HandFormatter
    from geort.model import FKModel
    from geort.utils.config_utils import parse_config_keypoint_info

    info = parse_config_keypoint_info(config)
    hand = HandKinematicModel.build_from_config(config, render=False)
    hand.initialize_keypoint(info["link"], info["offset"])
    robot = RobotModel()
    assert config["joint_order"] == list(robot.joint_names)
    np.testing.assert_allclose(hand.get_joint_limit(), robot.limits.T, atol=1e-7)
    formatter = HandFormatter(*hand.get_joint_limit())
    study = ROOT / "results/geort_data_size_parity_20261018"
    fk = FKModel(info["joint"]).cuda()
    fk.load_state_dict(
        torch.load(study / "shared/fk_model_dg5f_right_geort.pth", weights_only=True)
    )
    fk.eval()

    def true_fk(q):
        return np.array([robot.forward_kinematics(row, frame="palm") for row in q])

    def neural_fk(q):
        with torch.inference_mode():
            return (
                fk(torch.tensor(formatter.normalize(q), dtype=torch.float32, device="cuda"))
                .cpu()
                .numpy()
            )

    rng = np.random.default_rng(20261018)
    random_q = rng.uniform(robot.limits[:, 0], robot.limits[:, 1], size=(1024, 20))
    isolated = []
    for j in range(20):
        q = np.zeros(20)
        q[j] = 0.25 if robot.limits[j, 1] >= 0.25 else -0.25
        isolated.append(q)
    q = np.concatenate([np.zeros((1, 20)), isolated, random_q])
    exact = true_fk(q)
    sapien = np.array([hand.keypoint_from_qpos(row, ret_vec=True) for row in q])
    differences = np.linalg.norm(exact - sapien, axis=2) * 1000
    np.testing.assert_allclose(exact, sapien, atol=2e-6)
    # Explicitly compare all 20 body origins, in addition to fingertip sites.
    link_errors = []
    for row in q[:21]:
        robot.forward_kinematics(row, frame="palm")
        hand.pmodel.compute_forward_kinematics(hand.convert_user_order_to_sim_order(row))
        base = hand.pmodel.get_link_pose(hand.base_link_idx)
        for i, link in enumerate(hand.hand.get_links()):
            name = link.get_name()
            if not name.startswith("rl_dg_") or name == "rl_dg_palm":
                continue
            try:
                body = robot.model.body(name).id
            except KeyError:
                continue
            mj = (
                robot.fk_data.xpos[body] - robot.fk_data.xpos[robot.palm_id]
            ) @ robot.fk_data.xmat[robot.palm_id].reshape(3, 3)
            sp = (base.inv() * hand.pmodel.get_link_pose(i)).p
            link_errors.append(np.linalg.norm(mj - sp) * 1000)
    report = {
        "session": str(session),
        "output": str(output),
        "policy": "Read-only diagnosis; no training, no test-set scoring, no algorithm edits. "
        "Human/robot raw point distance is not independent ground-truth error.",
        "joint_order_exact_match": True,
        "exact_sapien_vs_mujoco_tip_mm": stats(differences),
        "exact_sapien_vs_mujoco_link_origin_mm": stats(link_errors),
        "exact_fk_cases": len(q),
        "neural_fk_vs_mujoco_random_mm": stats(
            np.linalg.norm(neural_fk(random_q) - exact[-1024:], axis=2) * 1000
        ),
        "models": {},
    }
    frames = list(
        replay_frames(session / "quest_input.jsonl", handedness="right", include_invalid=False)
    )
    canonical = np.array([canonical_points(frame) for frame in frames])
    np.save(output / "session_canonical.npy", canonical)
    selected = np.linspace(0, len(canonical) - 1, min(512, len(canonical)), dtype=int)
    sample = canonical[selected]
    models = json.loads((study / "models.json").read_text())
    session_models = json.loads((session / "session.json").read_text())["models"]
    report["session_frames"] = len(frames)

    # Human geometry: finger bending is invariant to reflection, and tip-only mapping
    # cannot distinguish two postures having identical fingertip positions.
    def bends(p):
        values = []
        for base in (5, 9, 13, 17):
            a, b = p[:, base + 1] - p[:, base], p[:, base + 2] - p[:, base + 1]
            values.append(
                np.degrees(
                    np.arccos(
                        np.clip(
                            np.sum(a * b, axis=-1)
                            / (np.linalg.norm(a, axis=-1) * np.linalg.norm(b, axis=-1)),
                            -1,
                            1,
                        )
                    )
                )
            )
        return np.array(values).T

    bend = bends(sample).mean(axis=1)
    open_ids, flex_ids = np.argsort(bend)[:32], np.argsort(bend)[-32:]
    report["gesture_candidate_mean_pip_deg"] = {
        "open": float(bend[open_ids].mean()),
        "flex": float(bend[flex_ids].mean()),
    }
    tip_ids = [4, 8, 12, 16, 20]
    for name, meta in models.items():
        assert session_models[name]["checkpoint_sha256"] == meta["checkpoint_sha256"]
        adapter = GeoRTRetargeter(robot, checkpoint=meta["checkpoint"], config_path=meta["config"])
        with torch.inference_mode():
            norm = (
                adapter.vendor.model(
                    torch.tensor(sample[:, tip_ids], dtype=torch.float32, device="cuda")
                )
                .cpu()
                .numpy()
            )
        targets = formatter.unnormalize(norm)
        tips = true_fk(targets)
        surrogate = neural_fk(targets)
        own = np.load(
            Path(json.loads((study / "study.json").read_text())["conditions"][name]["dataset"])
            / "human.npy"
        )
        nearest = np.stack([cKDTree(own[:, t]).query(sample[:, t])[0] for t in tip_ids], axis=1)
        out = {
            "checkpoint_matches_user_session": True,
            "neural_fk_vs_exact_on_model_targets_mm": stats(
                np.linalg.norm(tips - surrogate, axis=2) * 1000
            ),
            "human_tip_vs_model_target_mm": stats(
                np.linalg.norm(tips - sample[:, tip_ids], axis=2) * 1000
            ),
            "nearest_training_tip_mm": stats(nearest * 1000),
            "fraction_inputs_farther_than_5mm_from_training": float((nearest > 0.005).mean()),
            "fraction_non_thumb_pip_or_dip_negative": float(
                (targets[:, [6, 7, 10, 11, 14, 15, 18, 19]] < -0.05).mean()
            ),
            "open_candidate_mean_joint_deg": np.degrees(targets[open_ids].mean(axis=0)).tolist(),
            "flex_candidate_mean_joint_deg": np.degrees(targets[flex_ids].mean(axis=0)).tolist(),
        }
        # Compare actual logged control with targets; statuses break target continuity.
        gaps, track, tip_track, tip_lag = [], [], [], []
        statuses = {}
        for line in (session / f"{name}.jsonl").open():
            event = json.loads(line)
            status = event.get("control_status")
            if status is None:
                continue
            statuses[status] = statuses.get(status, 0) + 1
            if status != "TRACKING":
                continue
            s = event["simulation"]
            gaps.append(np.max(np.abs(np.array(event["retarget_q_target"]) - s["q_command"])))
            track.append(np.max(np.abs(np.array(s["q_actual"]) - s["q_command"])))
            tip_track.append(
                np.linalg.norm(np.array(s["tips_command_world"]) - s["tips_actual_world"], axis=1)
                * 1000
            )
            if len(gaps) % 5 == 0:
                tip_lag.append(
                    np.linalg.norm(
                        robot.forward_kinematics(
                            np.array(event["retarget_q_target"]), frame="world"
                        )
                        - s["tips_actual_world"],
                        axis=1,
                    )
                    * 1000
                )
        out["live_control"] = {
            "statuses": statuses,
            "max_joint_target_command_gap_rad": stats(gaps),
            "max_joint_command_actual_gap_rad": stats(track),
            "command_actual_tip_distance_mm": stats(tip_track),
            "target_actual_tip_distance_every_5th_tick_mm": stats(tip_lag),
        }
        # Constant target settling, no input inference, no rate-cap removal.
        settling = []
        for row in targets[np.linspace(0, len(targets) - 1, 8, dtype=int)]:
            runner = MujocoRunner(robot)
            command = np.zeros(20)
            for _ in range(200):
                command += np.clip(row - command, -np.pi * 0.02, np.pi * 0.02)
                runner.set_target(command)
                state = runner.step(10)
            settling.append(float(np.max(np.abs(state.q_actual - row))))
        out["constant_target_4s_settling_max_joint_rad"] = stats(settling)
        report["models"][name] = out
        np.savez_compressed(
            output / f"{name}_targets.npz",
            sample_indices=selected,
            human=sample,
            q=targets,
            tips=tips,
            neural_tips=surrogate,
            open_candidate_indices=open_ids,
            flex_candidate_indices=flex_ids,
        )
    (output / "audit.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", type=Path, default=ROOT / "results/live-retargeting-o6axl2lk")
    main(parser.parse_args().session.resolve())
