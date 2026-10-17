"""Explicit adapters for two small, pinned upstream samples; never pad skeletons."""

import hashlib
import json
import pickle
import subprocess
from pathlib import Path

import numpy as np

from benchmark.paths import ROOT, writable_output
from benchmark.retargeting.quest_ergonomics import geometric_features
from benchmark.tracking.hand_frame import HandFrame
from benchmark.tracking.recorder import frame_to_dict

MANIFEST = ROOT / "configs/public_datasets.json"


def catalog():
    return json.loads(MANIFEST.read_text())


def fetch_samples():
    """Read only the small pinned blobs; preserve external sparse checkouts."""
    for name, item in catalog().items():
        dest = ROOT / item["local_path"]
        if not dest.exists():
            repo = ROOT / "external" / ("GeoRT" if name == "geort_alex" else "AnyDexRetarget")
            content = subprocess.check_output(
                ["git", "-C", str(repo), "show", f"{item['commit']}:{item['repository_path']}"]
            )
            if hashlib.sha256(content).hexdigest() != item["sha256"]:
                raise ValueError("Pinned dataset hash mismatch")
            dest.parent.mkdir(parents=True, exist_ok=True)
            with dest.open("xb") as stream:
                stream.write(content)
        verify_file(dest, item)
        license_copy = dest.parent / "LICENSE"
        if not license_copy.exists():
            with license_copy.open("xb") as stream:
                stream.write((ROOT / item["license_path"]).read_bytes())


def verify_file(path, item):
    if hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
        raise ValueError(f"Dataset hash mismatch: {path}")


def validate_points(points):
    points = np.asarray(points, dtype=float)
    if points.shape != (21, 3) or not np.isfinite(points).all():
        raise ValueError("Need exactly 21 finite keypoints; missing points are never synthesized")
    if not np.allclose(points[0], 0, atol=1e-6):
        raise ValueError("Audited samples must be wrist relative")
    reach = np.linalg.norm(points[9])
    if not 0.02 < reach < 0.25:
        raise ValueError("Implausible meter-scale wrist-to-middle MCP distance")
    for base in (1, 5, 9, 13, 17):
        lengths = np.linalg.norm(np.diff(points[base : base + 4], axis=0), axis=1)
        if np.any((lengths < 0.003) | (lengths > 0.12)):
            raise ValueError("Missing/degenerate bones or unsupported scale")
    return points.copy()


def load_public(name, *, fps=30.0):
    """Yield right HandFrames. Replay FPS is an assumption, not captured timing."""
    if not np.isfinite(fps) or fps <= 0:
        raise ValueError("Assumed replay FPS must be positive and finite")
    item = catalog()[name]
    path = ROOT / item["local_path"]
    verify_file(path, item)
    if name == "geort_alex":
        data = np.load(path, allow_pickle=False)
        if data.ndim != 3 or data.shape[1:] != (21, 3):
            raise ValueError("GeoRT example is not a complete 21-point sequence")
        poses = data
        timestamps = None
    elif name == "anydex_avp1":
        # Never unpickle arbitrary downloads: accept only this hash-verified pinned blob.
        with path.open("rb") as stream:
            data = pickle.load(stream)
        poses = [record["right_fingers"] for record in data]
        timestamps = np.array([record["t"] for record in data])
        if not np.all(timestamps == 0):
            raise ValueError("Official timestamp structure changed; re-audit adapter")
    else:
        raise ValueError("No explicit adapter for this dataset")
    for index, points in enumerate(poses):
        metadata = {
            **item,
            "dataset": name,
            "source_kind": "public_dataset_estimated_pose",
            "is_quest_sdk_output": False,
            "is_webxr_live": False,
            "original_frame_index": index,
            "sequence": index,
            "session_id": f"{name}:{item['sha256']}",
            "reference_epoch": 0,
            "joint_index_mapping": list(range(21)),
            "units": "meters",
            "scale_applied": 1.0,
            "clock_policy": "index / assumed replay fps; original timing unavailable",
            "assumed_replay_fps": fps,
            "original_timestamp": None if timestamps is None else float(timestamps[index]),
            "wrist_pose_measured": False,
            "wrist_pose_policy": "native local coordinates embedded by identity; pose not measured",
            "gesture_label": None,
            "validity_policy": "geometry validated; original tracking confidence unavailable",
        }
        yield HandFrame(
            index / fps,
            "right",
            validate_points(points),
            np.zeros(3),
            np.array([0.0, 0, 0, 1]),
            True,
            coordinate_frame="wrist_rh",
            timestamp_domain="dataset_assumed_replay",
            joint_rotations=None,
            metadata=metadata,
        )


def write_frames(path, frames):
    """Compatible event envelope, with public-data provenance rather than Quest clocks."""
    path = writable_output(Path(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        stream.write(
            json.dumps(
                {
                    "event": "header",
                    "schema": "quest_hand_recording_v1",
                    "source_kind": frames[0].metadata.get("source_kind", "common_handframe_replay"),
                    "target_frame": frames[0].coordinate_frame,
                    "clock_note": "Timing preserved in each frame timestamp_domain and metadata",
                    "protocol": None,
                }
            )
            + "\n"
        )
        for frame in frames:
            stream.write(
                json.dumps({"event": "hand_frame", "frame": frame_to_dict(frame)}, allow_nan=False)
                + "\n"
            )


def audit_samples(frames):
    """Gesture candidates for manual inspection, never ground-truth labels."""
    values = np.array([geometric_features(frame) for frame in frames])
    points = np.array([frame.joint_positions for frame in frames])
    bend = values[:, [6, 7, 10, 11, 14, 15, 18, 19]]
    mcp = values[:, [5, 9, 13, 17]]
    pinch = np.linalg.norm(points[:, 4] - points[:, 8], axis=1)
    palm = np.linalg.norm(points[:, 9] - points[:, 0], axis=1)
    masks = {
        "open": (np.max(bend, axis=1) < 25) & (np.max(np.abs(mcp), axis=1) < 25),
        "fist": (np.min(values[:, [6, 10, 14, 18]], axis=1) > 60) & (np.min(mcp, axis=1) > 45),
        "pinch": pinch / palm < 0.35,
    }
    hashes = [hashlib.sha256(f.joint_positions.tobytes()).hexdigest() for f in frames]
    return {
        "frames": len(frames),
        "unique_pose_hashes": len(set(hashes)),
        "exact_duplicate_pose_count": len(hashes) - len(set(hashes)),
        "gesture_policy": "fixed geometry heuristics; candidates only, not gesture ground truth",
        "gesture_thresholds": {
            "open_max_bend_deg": 25,
            "open_max_abs_mcp_deg": 25,
            "fist_min_pip_deg": 60,
            "fist_min_mcp_deg": 45,
            "pinch_max_distance_over_palm": 0.35,
        },
        "gesture_candidates": {
            key: {"count": int(mask.sum()), "first_indices": np.flatnonzero(mask)[:10].tolist()}
            for key, mask in masks.items()
        },
        "wrist_middle_mcp_median_m": float(np.median(palm)),
        "thumb_index_min_m": float(pinch.min()),
        "participant_id": frames[0].metadata["participant_id"],
        "sequence_id": frames[0].metadata["sequence_id"],
        "split": frames[0].metadata["split"],
    }


def audit_split_overlap(groups):
    """Reject source/sequence/known-subject leakage; disclose missing identity evidence."""
    sets = {
        split: {"sha256": set(), "sequence_id": set(), "participant_id": set()} for split in groups
    }
    unknown = []
    for split, items in groups.items():
        for item in items:
            for key in sets[split]:
                if item.get(key) is not None:
                    sets[split][key].add(item[key])
            if item.get("participant_id") is None:
                unknown.append(item["sequence_id"])
    splits = list(sets)
    for i, a in enumerate(splits):
        for b in splits[i + 1 :]:
            for key in sets[a]:
                if sets[a][key] & sets[b][key]:
                    raise ValueError(f"Split leakage: {key} overlaps between {a} and {b}")
    return {
        "overlap_detected": False,
        "unknown_participant_sequences": sorted(set(unknown)),
        "subject_disjoint_verified": not unknown,
        "policy": "samples remain development-only; no random-frame train/eval split",
    }
