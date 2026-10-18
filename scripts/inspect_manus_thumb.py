#!/usr/bin/env python3
"""Read-only thumb proxy/vendor/FK audit; never changes retargeting or model assets."""

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from benchmark.artifacts import save, sha  # noqa: E402
from benchmark.experiments.manus_fixtures import pose_frame  # noqa: E402
from benchmark.retargeting.manus import ManusRetargeter  # noqa: E402
from benchmark.retargeting.quest_ergonomics import geometric_features  # noqa: E402
from benchmark.simulation.robot_model import RobotModel  # noqa: E402


def controlled_frame(opposition, elevation):
    """Synthetic straight thumb, only for checking coordinate response, never real data."""
    frame = pose_frame()
    points = frame.joint_positions.copy()
    a, e = np.radians([opposition, elevation])
    direction = np.array([np.sin(e), np.cos(e) * np.cos(a), np.cos(e) * np.sin(a)])
    for i, length in enumerate([0.035, 0.028, 0.022], 2):
        points[i] = points[i - 1] + length * direction
    return replace(frame, joint_positions=points)


def robot_direction(robot, q):
    robot.forward_kinematics(q, frame="palm")
    data = robot.fk_data
    rotation = data.xmat[robot.palm_id].reshape(3, 3)
    v = (
        data.xpos[robot.model.body("rl_dg_1_3").id] - data.xpos[robot.model.body("rl_dg_1_2").id]
    ) @ rotation
    v /= np.linalg.norm(v)
    return v, np.degrees([np.arctan2(v[2], v[1]), np.arctan2(v[0], np.hypot(v[1], v[2]))])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--log",
        type=Path,
        default=ROOT / "results/video_benchmark_002/manus_thumb_v2/replay/manus.jsonl",
    )
    parser.add_argument(
        "--convention", choices=["legacy_v1", "thumb_axes_v2"], default="thumb_axes_v2"
    )
    args = parser.parse_args()
    args.log = args.log.resolve()
    if args.output.exists():
        raise FileExistsError("Use a new report path")
    robot = RobotModel()
    adapter = ManusRetargeter(
        robot, {"handedness": "right", "thumb_input_convention": args.convention}
    )
    cases = []
    for a, e in [(10, 20), (20, 20), (10, 30), (40, 20), (50, 20), (40, 30)]:
        frame = controlled_frame(a, e)
        adapter.reset()
        result = adapter.retarget(frame)
        features = geometric_features(frame)
        v, angles = robot_direction(robot, result.q_target)
        np.testing.assert_allclose(features[:2], [a, e], atol=1e-10)
        cases.append(
            {
                "synthetic_input_A_E_deg": [a, e],
                "computed_proxy_deg": features[:4].tolist(),
                "vendor_input_deg": result.metadata["ergonomics_proxy_deg"][:4],
                "raw_thumb_q_deg": np.degrees(result.metadata["q_vendor_raw"][:4]).tolist(),
                "clipped_thumb_q_deg": np.degrees(result.q_target[:4]).tolist(),
                "human_thumb_metacarpal_direction_palm": (
                    (frame.joint_positions[2] - frame.joint_positions[1]) / 0.035
                ).tolist(),
                "robot_link2_to_link3_direction_palm": v.tolist(),
                "robot_direction_A_E_deg": angles.tolist(),
            }
        )
    # Check distal curl sign independently of the two base features.
    q = np.zeros(20)
    q[:2] = np.radians([30, -50])
    distal = []
    for mcp, ip in [(0, 0), (20, 0), (0, 20)]:
        value = q.copy()
        value[2:4] = np.radians([mcp, ip])
        robot.forward_kinematics(value)
        d = robot.fk_data
        p = [d.xpos[robot.model.body(f"rl_dg_1_{j}").id].copy() for j in [2, 3, 4]]
        p.append(d.xpos[robot.model.body("rl_dg_1_tip").id].copy())
        bones = np.diff(p, axis=0)
        angles = [
            np.degrees(np.arccos(np.clip(u @ v / np.linalg.norm(u) / np.linalg.norm(v), -1, 1)))
            for u, v in zip(bones[:-1], bones[1:])
        ]
        distal.append({"robot_q3_q4_deg": [mcp, ip], "unsigned_interbone_bends_deg": angles})
        np.testing.assert_allclose(angles, [mcp, ip], atol=1e-5)
    recorded = None
    if args.log.exists():
        features, raw, clipped = [], [], []
        last = None
        for line in args.log.open():
            row = json.loads(line)
            if row.get("control_status") != "TRACKING":
                continue
            key = row["input_index"]
            if key == last:
                continue
            last = key
            m = row["retarget_metadata"]
            f = np.array(m["features_deg"])
            r = np.array(m["q_vendor_raw"])
            vendor_input = np.array(m["ergonomics_proxy_deg"])
            np.testing.assert_allclose(adapter.vendor(vendor_input, "right"), r, atol=1e-12)
            features.append(f[:4])
            raw.append(r[:4])
            clipped.append(row["retarget_q_target"][:4])
        features, raw, clipped = np.array(features), np.array(raw), np.array(clipped)
        recorded = {
            "log": str(args.log.relative_to(ROOT)),
            "sha256": sha(args.log),
            "unique_tracking_inputs": len(features),
            "vendor_recomputed_all_equal": True,
            "proxy_median_deg": np.median(features, axis=0).tolist(),
            "proxy_min_deg": features.min(axis=0).tolist(),
            "proxy_max_deg": features.max(axis=0).tolist(),
            "raw_thumb_median_deg": np.degrees(np.median(raw, axis=0)).tolist(),
            "raw_q2_below_minus_90_count": int(np.sum(raw[:, 1] < -np.pi / 2)),
            "q2_common_limit_clip_count": int(np.sum(np.abs(raw[:, 1] - clipped[:, 1]) > 1e-12)),
        }
    report = {
        "purpose": "check current Quest geometry proxy, pinned vendor mapping and exact DG-5F FK",
        "vendor": adapter.provenance,
        "synthetic_input_convention": args.convention,
        "thumb_limits_deg": np.degrees(robot.limits[:4]).tolist(),
        "synthetic_cases": cases,
        "distal_fk_checks": distal,
        "recorded": recorded,
        "source_files_sha256": {
            str(p.relative_to(ROOT)): sha(p)
            for p in [
                ROOT / "benchmark/retargeting/quest_ergonomics.py",
                ROOT / "benchmark/retargeting/manus.py",
                ROOT / "external/tesollo_model/dg5f/dg5f_right.urdf",
            ]
        },
        "limitations": [
            "Synthetic straight-thumb cases are coordinate probes, not recorded human data.",
            (
                "Robot link2->link3 is a kinematic direction probe, "
                "not certified anatomical correspondence."
            ),
            "MANUS ergonomics sign/zero cannot be validated from Quest keypoints alone.",
            "Audit itself does not modify upstream, adapters, joint ranges or existing results.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    save(args.output, report)
    print(json.dumps({"cases": cases, "recorded": recorded}, indent=2))


if __name__ == "__main__":
    main()
