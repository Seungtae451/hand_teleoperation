#!/usr/bin/env python3
"""Observed Quest geometric angle extrema; never anatomical ROM or encoder calibration."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def unit(v):
    length = np.linalg.norm(v)
    if not np.isfinite(length) or length < 1e-6:
        raise ValueError("Degenerate bone/axis")
    return v / length


def bend(a, b):
    return float(np.degrees(np.arccos(np.clip(unit(a) @ unit(b), -1, 1))))


def projected_mcp(meta, proximal, palm_normal):
    """Flexion relative to measured metacarpal, spread projected out; degrees."""
    z = unit(meta)
    axis = unit(np.cross(z, unit(palm_normal)))
    normal = np.cross(axis, z)
    return float(np.degrees(np.arctan2(proximal @ normal, proximal @ z)))


def main(recording, output, manifest_path):
    from benchmark.retargeting.quest_ergonomics import FEATURE_NAMES, geometric_features
    from benchmark.simulation.robot_model import RobotModel
    from benchmark.tracking.recorder import read_events
    from benchmark.tracking.webxr_protocol import (
        WEBXR_JOINT_NAMES,
        hand_frame_from_packet,
        validate_envelope,
    )

    manifest = json.loads(Path(manifest_path).read_text())
    if manifest.get("split") != "train" or hashlib.sha256(
        recording.read_bytes()
    ).hexdigest() != manifest.get("source_recording_sha256"):
        raise ValueError("Use an explicitly assigned training recording and matching manifest")
    output.mkdir(parents=True, exist_ok=False)
    features = []
    angles = []
    provenance = []
    rejected = 0
    names = [
        f"{finger}_{joint}"
        for finger in ["index", "middle", "ring", "pinky"]
        for joint in ["mcp_flex_metacarpal", "pip_unsigned_bend", "dip_unsigned_bend"]
    ] + ["thumb_mcp_unsigned_bend", "thumb_ip_unsigned_bend"]
    for event in read_events(recording):
        if event.get("event") != "native_packet":
            continue
        packet = event["packet"]
        if packet.get("type") != "frame":
            continue
        try:
            validate_envelope(packet)
            frame = hand_frame_from_packet(
                packet,
                "right",
                event["receive_time_s"],
                event["session_id"],
                target_frame="world_rh",
            )
            if frame is None:
                rejected += 1
                continue
            p = np.asarray(packet["hands"]["right"]["positions"], dtype=float)
            by_name = dict(zip(WEBXR_JOINT_NAMES, p))
            z = unit(frame.joint_positions[9] - frame.joint_positions[0])
            radial = frame.joint_positions[5] - frame.joint_positions[13]
            normal = unit(np.cross(radial, z))
            values = []
            for finger in ["index", "middle", "ring", "pinky"]:
                chain = np.array(
                    [
                        by_name[f"{finger}-finger-{part}"]
                        for part in [
                            "metacarpal",
                            "phalanx-proximal",
                            "phalanx-intermediate",
                            "phalanx-distal",
                            "tip",
                        ]
                    ]
                )
                bones = np.diff(chain, axis=0)
                values.extend(
                    [
                        projected_mcp(bones[0], bones[1], normal),
                        bend(bones[1], bones[2]),
                        bend(bones[2], bones[3]),
                    ]
                )
            thumb = np.array(
                [
                    by_name[n]
                    for n in [
                        "thumb-metacarpal",
                        "thumb-phalanx-proximal",
                        "thumb-phalanx-distal",
                        "thumb-tip",
                    ]
                ]
            )
            b = np.diff(thumb, axis=0)
            values.extend([bend(b[0], b[1]), bend(b[1], b[2])])
            feature = geometric_features(frame)
        except ValueError:
            rejected += 1
            continue
        angles.append(values)
        features.append(feature)
        provenance.append(
            {
                "sequence": packet["sequence"],
                "receiver_time_s": frame.timestamp,
                "source_time_ms": packet["source_time_ms"],
                "session_id": event["session_id"],
            }
        )
    a = np.array(angles)
    f = np.array(features)
    if len(a) == 0:
        raise ValueError("No valid right hand geometry")

    def summarize(array, labels):
        result = {}
        for i, name in enumerate(labels):
            v = array[:, i]
            lo, hi = int(v.argmin()), int(v.argmax())
            result[name] = {
                "minimum_deg": float(v[lo]),
                "maximum_deg": float(v[hi]),
                "p0_5_deg": float(np.percentile(v, 0.5)),
                "p99_5_deg": float(np.percentile(v, 99.5)),
                "minimum_frame": provenance[lo],
                "maximum_frame": provenance[hi],
                "frames_within_2deg_of_max": int((v >= v[hi] - 2).sum()),
            }
        return result

    measured = summarize(a, names)
    proxies = summarize(f, list(FEATURE_NAMES))
    robot = RobotModel()
    candidate = robot.limits.copy()
    mapping = []
    # Only +Y serial flexion stages of the three common fingers have a declared mapping.
    for finger_index, finger in [(2, "index"), (3, "middle"), (4, "ring")]:
        for stage, feature in [
            (2, "mcp_flex_metacarpal"),
            (3, "pip_unsigned_bend"),
            (4, "dip_unsigned_bend"),
        ]:
            joint = f"rj_dg_{finger_index}_{stage}"
            i = robot.joint_names.index(joint)
            name = f"{finger}_{feature}"
            maximum = measured[name]["maximum_deg"]
            upper = min(robot.limits[i, 1], np.deg2rad(maximum))
            if upper <= candidate[i, 0]:
                raise ValueError("Observed angle cannot form a meaningful candidate range")
            candidate[i, 1] = upper
            mapping.append(
                {
                    "robot_joint": joint,
                    "human_measure": name,
                    "observed_max_deg": maximum,
                    "candidate_upper_deg": float(np.rad2deg(upper)),
                    "official_upper_deg": float(np.rad2deg(robot.limits[i, 1])),
                    "lower_policy": (
                        "official lower retained; upper-only estimate does NOT prevent "
                        "backward flexion"
                    ),
                    "mapping_status": (
                        "candidate corresponding flexion stage; not validated "
                        "human-to-encoder calibration"
                    ),
                }
            )
    mapped = {m["robot_joint"] for m in mapping}
    report = {
        "schema": "quest_observed_joint_extrema_v1",
        "source_recording": str(recording),
        "source_sha256": hashlib.sha256(recording.read_bytes()).hexdigest(),
        "role": "training recording only; evaluation not used",
        "handedness": "right",
        "tracking": "Quest Browser WebXR estimated joint poses",
        "valid_native_frames": len(a),
        "rejected_or_invalid_native_right_frames": rejected,
        "angle_units": "degrees",
        "clinical_or_hardware_rom_measurement": False,
        "native_bend_definitions": (
            "MCP signed metacarpal/proximal flexion projected around "
            "palm-based side axis. PIP/DIP/thumb unsigned inter-bone bend; "
            "hyperextension sign unavailable."
        ),
        "proxy_definitions": (
            "Existing 20 geometric Quest ergonomics; thumb "
            "opposition/elevation are orientation proxies, not certified CMC "
            "encoder angles. Proxy MCP uses palm direction, distinct from "
            "metacarpal-relative MCP."
        ),
        "raw_extrema_used_without_percentile_substitution": True,
        "native_joint_angles": measured,
        "existing_20_feature_proxies": proxies,
        "candidate_robot_upper_mapping": mapping,
        "unmapped_robot_joints": [n for n in robot.joint_names if n not in mapped],
        "candidate_bounds_rad": candidate.tolist(),
        "profile_status": (
            "upper-only candidate, NOT applied or trained; "
            "geometry/sign/zero calibration remains required; does not block "
            "existing negative lower limits"
        ),
        "training_executed": False,
        "original_models_or_urdf_modified": False,
        "warning": (
            "Observed recording extrema are "
            "task/participant/tracker-dependent, not anatomical maxima. Raw "
            "maximum can be a tracking outlier. No gain, offset or inverse "
            "retargeter used to fabricate robot limits."
        ),
    }
    (output / "observed_ranges.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n"
    )
    np.savez_compressed(
        output / "observed_angles.npz",
        native_angles_deg=a,
        native_angle_names=names,
        feature_proxy_deg=f,
        feature_proxy_names=FEATURE_NAMES,
        sequences=[p["sequence"] for p in provenance],
        receiver_time_s=[p["receiver_time_s"] for p in provenance],
    )
    print(
        json.dumps(
            {"output": str(output), "valid_frames": len(a), "candidate_mapping": mapping}, indent=2
        )
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, default=ROOT / "recordings/quest_train_session_002.jsonl")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument(
        "--manifest", type=Path, default=ROOT / "data/geort/quest_train_session_002/manifest.json"
    )
    args = p.parse_args()
    from benchmark.paths import writable_output

    main(args.input.resolve(), writable_output(args.output), args.manifest)
