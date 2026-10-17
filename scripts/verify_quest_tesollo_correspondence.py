#!/usr/bin/env python3
"""Read-only FK and vendor-source audit; does not calibrate Quest to encoders."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from benchmark.retargeting.manus_vendor import OfficialManusMapping  # noqa: E402
from benchmark.simulation.robot_model import RobotModel  # noqa: E402


def signed_bend(a, b, axis):
    a, b = a / np.linalg.norm(a), b / np.linalg.norm(b)
    return float(np.degrees(np.arctan2(axis @ np.cross(a, b), a @ b)))


def audit():
    robot = RobotModel()
    vendor = OfficialManusMapping()
    rng = np.random.default_rng(20261018)
    errors = {n: [] for n in robot.joint_names if n[-1] in "34"}
    mcp_errors = {f"rj_dg_{i}_2": [] for i in (2, 3, 4)}
    unsigned_errors = []
    for case in range(129):
        q = np.zeros(20) if case == 0 else rng.uniform(*robot.limits.T)
        robot.forward_kinematics(q)
        data = robot.fk_data
        for f in range(1, 6):
            points = [data.xpos[robot.model.body(f"rl_dg_{f}_{j}").id] for j in (2, 3, 4)]
            points.append(data.site_xpos[robot.site_ids[f - 1]])
            bones = np.diff(points, axis=0)
            for j in (3, 4):
                name = f"rj_dg_{f}_{j}"
                jid = robot.model.joint(name).id
                measured = signed_bend(bones[j - 3], bones[j - 2], data.xaxis[jid])
                expected = np.degrees(q[robot.joint_names.index(name)])
                errors[name].append(abs(measured - expected))
                unsigned = np.degrees(
                    np.arccos(
                        np.clip(
                            bones[j - 3]
                            @ bones[j - 2]
                            / (np.linalg.norm(bones[j - 3]) * np.linalg.norm(bones[j - 2])),
                            -1,
                            1,
                        )
                    )
                )
                unsigned_errors.append(abs(unsigned - abs(expected)))
            if f in (2, 3, 4):
                name = f"rj_dg_{f}_2"
                parent = robot.model.body(f"rl_dg_{f}_1").id
                zero_direction = data.xmat[parent].reshape(3, 3)[:, 2]
                measured = signed_bend(
                    zero_direction, bones[0], data.xaxis[robot.model.joint(name).id]
                )
                mcp_errors[name].append(
                    abs(measured - np.degrees(q[robot.joint_names.index(name)]))
                )
    max_error = max(max(v) for v in [*errors.values(), *mcp_errors.values()])
    assert max_error < 1e-8, max_error
    assert max(unsigned_errors) < 1e-5

    # Numerical examples run the exact pinned vendor function, not a reimplementation.
    vendor_cases = {}
    for label, changes in {
        "zero_input": {},
        "index_pip_60": {6: 60},
        "middle_pip_60": {10: 60},
        "pinky_mcp_60": {17: 60},
        "pinky_pip_60": {18: 60},
        "pinky_dip_60": {19: 60},
        "thumb_last_feature_60": {3: 60},
    }.items():
        values = np.zeros(20)
        for i, value in changes.items():
            values[i] = value
        vendor_cases[label] = np.degrees(vendor(values)).tolist()
    assert abs(vendor_cases["index_pip_60"][6] - 26) < 1e-10
    assert abs(vendor_cases["middle_pip_60"][10] - 39) < 1e-10
    assert np.isclose(vendor_cases["pinky_mcp_60"][18], 60)
    assert np.isclose(vendor_cases["pinky_pip_60"][19], 60)
    assert vendor_cases["pinky_dip_60"] == vendor_cases["zero_input"]

    positive_tip_dx = {}
    for f in (2, 3, 4):
        zero = robot.forward_kinematics(np.zeros(20), frame="palm")[f - 1].copy()
        q = np.zeros(20)
        q[(f - 1) * 4 + 2] = np.radians(10)
        moved = robot.forward_kinematics(q, frame="palm")[f - 1]
        positive_tip_dx[f"rj_dg_{f}_3"] = float((moved[0] - zero[0]) * 1000)
    assert all(v > 0 for v in positive_tip_dx.values())

    rows = []
    for i, name in enumerate(robot.joint_names):
        f, j = i // 4 + 1, i % 4 + 1
        if f in (2, 3, 4) and j in (3, 4):
            status = (
                "PIP/DIP geometric magnitude and robot sign/zero verified; human sign unavailable"
            )
        elif f in (2, 3, 4) and j == 2:
            status = (
                "MCP flexion role verified; human metacarpal-to-robot "
                "neutral registration unverified"
            )
        elif f == 5:
            status = "vendor: cupping/spread, spread, MCP, PIP; no independent DIP mapping"
        elif f == 1:
            status = "thumb axes differ; vendor offsets/coupling; no calibrated Quest mapping"
        else:
            status = "spread axis; no calibrated Quest mapping"
        rows.append(
            {
                "joint": name,
                "axis_local": robot.model.joint(name).axis.tolist(),
                "official_limits_deg": np.degrees(robot.limits[i]).tolist(),
                "status": status,
            }
        )
    urdf = ROOT / robot.config["urdf"]
    return {
        "schema": "quest_tesollo_correspondence_audit_v1",
        "handedness": "right",
        "urdf": str(urdf.relative_to(ROOT)),
        "urdf_sha256": hashlib.sha256(urdf.read_bytes()).hexdigest(),
        "vendor_source": vendor.provenance,
        "joint_correspondence": rows,
        "fk_cases": 129,
        "signed_bone_angle_max_error_deg": max_error,
        "unsigned_bone_angle_max_error_deg": max(unsigned_errors),
        "positive_pip_10deg_tip_palmar_x_displacement_mm": positive_tip_dx,
        "vendor_examples_output_deg": vendor_cases,
        "scope": "Robot FK and source audit; no paired human/robot ground truth or calibration",
        "candidate_review": {
            "six_PIP_DIP": (
                "geometric magnitude reference only; "
                "unsigned human angles cannot set negative bounds"
            ),
            "three_MCP": "defer numeric upper adoption until neutral-reference calibration",
            "thumb_pinky": "do not assign by joint ordinal",
        },
        "changed_urdf_weights_bounds_or_upstream": False,
        "warning": (
            "MANUS ergonomics and Quest geometric angles are distinct; "
            "vendor gains/offsets are not Quest calibration"
        ),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "fk_cases": report["fk_cases"],
                "max_error_deg": report["signed_bone_angle_max_error_deg"],
            },
            indent=2,
        )
    )
