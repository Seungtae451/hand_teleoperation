#!/usr/bin/env python3
"""Count geometry-usable public Quest frames; never equate this with tracking GT."""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

REVISION = "b5c916d89c771f4a09d5f6d6c59e1dc4f912bb61"
ROOT = Path(__file__).resolve().parents[1]
# Native OpenXR order: palm, wrist, thumb 4, then 4 fingers of 5 joints each.
COMMON_INDICES = [1, 2, 3, 4, 5, 7, 8, 9, 10, 12, 13, 14, 15, 17, 18, 19, 20, 22, 23, 24, 25]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def shaped(values, width):
    result = np.full((len(values), width), np.nan)
    matches = np.array([value is not None and len(value) == width for value in values])
    for index in np.flatnonzero(matches):
        result[index] = values[index]
    return result, matches


def audit(source, output):
    paths = sorted((source / "data").glob("chunk_*.parquet"))
    if len(paths) != 2:
        raise ValueError("Expected both files from the pinned release")
    table = pq.read_table(paths)
    metadata = json.loads((source / "meta/info.json").read_text())
    index = pq.read_table(source / "meta/episode_index.parquet").to_pylist()
    episodes = np.array(table["episode_index"].to_pylist())
    frames = np.array(table["frame_index"].to_pylist())
    raw, right_shape = shaped(table["observation.right_joint_poses"].to_pylist(), 78)
    right = raw.reshape(-1, 26, 3)[:, COMMON_INDICES]
    left_raw, left_shape = shaped(table["observation.left_joint_poses"].to_pylist(), 78)
    left = left_raw.reshape(-1, 26, 3)[:, COMMON_INDICES]
    wrist, wrist_shape = shaped(table["observation.right_state"].to_pylist(), 7)
    finite = np.isfinite(right).all(axis=(1, 2))
    bone_lengths = np.stack(
        [
            np.linalg.norm(np.diff(right[:, base : base + 4], axis=1), axis=2)
            for base in (1, 5, 9, 13, 17)
        ],
        axis=1,
    )
    bones_valid = (bone_lengths > 1e-6).all(axis=(1, 2))
    z = right[:, 9] - right[:, 0]
    y_aux = right[:, 5] - right[:, 13]
    palm_lengths = np.linalg.norm(z, axis=1)
    meter_plausible = (palm_lengths > 0.02) & (palm_lengths < 0.25)
    axes_valid = np.linalg.norm(np.cross(y_aux, z), axis=1) > 1e-8
    valid = right_shape & finite & bones_valid & meter_plausible & axes_valid
    wrist_residual = np.linalg.norm(wrist[:, :3] - right[:, 0], axis=1)
    quaternion_norms = np.linalg.norm(wrist[:, 3:], axis=1)
    ep_counts, sequence_problems = [], []
    for row in index:
        episode = row["episode_index"]
        selected = episodes == episode
        count = int(selected.sum())
        expected = row["end_frame_index"] - row["start_frame_index"] + 1
        if count != expected or not np.array_equal(frames[selected], np.arange(count)):
            sequence_problems.append(episode)
        ep_counts.append(
            {
                "episode": episode,
                "task": row["task"],
                "rows": count,
                "geometry_valid_right_frames": int(valid[selected].sum()),
            }
        )
    # Exact duplicate world-space skeletons; these counts are NOT motion diversity estimates.
    pose_hashes = [hashlib.sha256(pose.tobytes()).hexdigest() for pose in right[valid]]
    unique = len(set(pose_hashes))
    finite_bones = bone_lengths[np.isfinite(bone_lengths)]
    report = {
        "dataset": "OOJU/wild-mani-kitchen",
        "revision": REVISION,
        "source_url": "https://huggingface.co/datasets/OOJU/wild-mani-kitchen",
        "license_as_declared": "Apache-2.0",
        "input_kind_as_declared": "Quest 3 hand tracking",
        "official_meta_dataset": False,
        "native_joint_order_source": "pinned README.md",
        "native_to_common21_indices": COMMON_INDICES,
        "total_rows": table.num_rows,
        "declared_rows": metadata["total_frames"],
        "episodes": len(set(episodes.tolist())),
        "declared_episodes": metadata["total_episodes"],
        "fps_declared": metadata["fps"],
        "coordinate_frame_declared": metadata["coordinate_frame"],
        "timestamp_column_present": any("time" in name for name in table.column_names),
        "participant_id_column_present": any(
            "participant" in name or "subject" in name for name in table.column_names
        ),
        "tracking_validity_or_confidence_columns": [
            name
            for name in table.column_names
            if "confidence" in name or "tracking" in name or "valid" in name
        ],
        "right_native_78_value_rows": int(right_shape.sum()),
        "left_native_78_value_rows": int(left_shape.sum()),
        "right_finite_rows": int(finite.sum()),
        "left_finite_rows": int((left_shape & np.isfinite(left).all(axis=(1, 2))).sum()),
        "right_geometry_usable_rows": int(valid.sum()),
        "right_rejection_counts_nonexclusive": {
            "wrong_shape": int((~right_shape).sum()),
            "nonfinite": int((~finite).sum()),
            "degenerate_phalanges": int((~bones_valid).sum()),
            "implausible_meter_palm_length": int((~meter_plausible).sum()),
            "degenerate_palm_axes": int((~axes_valid).sum()),
        },
        "exact_unique_right_world_skeletons": unique,
        "exact_duplicate_right_world_skeleton_rows": int(valid.sum()) - unique,
        "right_wrist_state_7_value_rows": int(wrist_shape.sum()),
        "max_right_wrist_position_residual_m": float(np.nanmax(wrist_residual)),
        "right_unit_wrist_quaternion_rows_atol_1e_4": int(
            np.isclose(quaternion_norms, 1, atol=1e-4).sum()
        ),
        "wrist_middle_mcp_length_m": {
            "minimum": float(np.nanmin(palm_lengths)),
            "median": float(np.nanmedian(palm_lengths)),
            "maximum": float(np.nanmax(palm_lengths)),
        },
        "phalanx_length_m": {
            "minimum": float(finite_bones.min()),
            "maximum": float(finite_bones.max()),
        },
        "sequence_index_problems": sequence_problems,
        "task_episode_counts": dict(Counter(row["task"] for row in ep_counts)),
        "episodes_detail": ep_counts,
        "files_sha256": {
            str(path.relative_to(source)): digest(path)
            for path in sorted(source.rglob("*"))
            if path.is_file()
        },
        "validation_scope": "Array shape, finite values, nonzero bones, nondegenerate palm axes, "
        "plausible meter scale, native joint mapping, episode indices and source hashes. "
        "Does not certify tracking accuracy, handedness ground truth or pose diversity. "
        "No training/test split assigned and no training run.",
    }
    if table.num_rows != metadata["total_frames"] or len(ep_counts) != metadata["total_episodes"]:
        raise ValueError("Published count mismatch")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(
        json.dumps(
            {
                key: value
                for key, value in report.items()
                if key not in ("episodes_detail", "files_sha256")
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", type=Path, default=ROOT / "data/public/wild_mani_kitchen" / REVISION
    )
    parser.add_argument("--output", type=Path, default=ROOT / "results/public_quest_audit.json")
    args = parser.parse_args()
    audit(args.input, args.output)
