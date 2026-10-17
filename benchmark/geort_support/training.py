"""Future data handoff and training launcher. Planning never calls the trainer."""

import hashlib
import json
import os
import random
import tempfile
from pathlib import Path

import numpy as np

from benchmark.geort_support.input import INPUT_CONTRACT, canonical_points
from benchmark.geort_support.runtime import load_workspace
from benchmark.geort_support.source import enable_upstream
from benchmark.paths import writable_output
from benchmark.tracking.recorder import replay_frames


def export_recording(recording, output, *, split="development", drop_invalid=False):
    if split not in ("train", "eval", "development"):
        raise ValueError("Explicit dataset split must be train/eval/development")
    output = writable_output(Path(output))
    if output.exists():
        raise FileExistsError("Use a new data export directory")
    poses, retained, skipped, participants, sequences = [], [], 0, set(), set()
    for frame in replay_frames(recording, handedness="right"):
        if not frame.tracking_valid and drop_invalid:
            skipped += 1
            continue
        poses.append(canonical_points(frame))
        retained.append(
            {
                "timestamp": frame.timestamp,
                "timestamp_domain": frame.timestamp_domain,
                "metadata": frame.metadata,
            }
        )
        if frame.metadata.get("participant_id"):
            participants.add(frame.metadata["participant_id"])
        if frame.metadata.get("sequence_id") or frame.metadata.get("session_id"):
            sequences.add(frame.metadata.get("sequence_id") or frame.metadata["session_id"])
    if not poses:
        raise ValueError("No valid complete right-hand frames for GeoRT")
    output.mkdir(parents=True)
    target = output / "human.npy"
    np.save(target, np.asarray(poses))
    manifest = {
        "schema": "geort_human_input_v1",
        "split": split,
        "input_contract": INPUT_CONTRACT,
        "source_recording_sha256": hashlib.sha256(Path(recording).read_bytes()).hexdigest(),
        "npy_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "frames": len(poses),
        "invalid_right_frames_skipped": skipped,
        "drop_invalid_requested": drop_invalid,
        "participant_ids": sorted(participants),
        "sequence_ids": sorted(sequences),
        "participant_disjoint_verified": False,
        "retained_frame_provenance": retained,
        "training_executed": False,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def training_plan(workspace, human_data=None):
    folder, config = load_workspace(workspace)
    return {
        "mode": "plan_only",
        "workspace": str(folder),
        "robot": config["name"],
        "human_data": None if human_data is None else str(Path(human_data).resolve()),
        "input_contract": INPUT_CONTRACT,
        "data_ready": human_data is not None and Path(human_data).is_file(),
        "will_train_neural_fk_if_missing": True,
        "upstream_defaults": {
            "neural_fk_epochs": 200,
            "ik_epochs": 200,
            "w_chamfer": 80.0,
            "w_curvature": 0.1,
            "w_collision": 0.0,
            "w_pinch": 1.0,
        },
        "collision_note": "upstream collision loss is an inactive placeholder; no classifier added",
        "training_executed": False,
        "performance_evaluation_executed": False,
        "next_requirement": "user canonical input, train-role manifest, and explicit execute",
    }


def execute_training(workspace, human_data, manifest_path, *, seed=20261018):
    """Only called by a future explicit --execute request; never by preparation/checks."""
    folder, config = load_workspace(workspace)
    manifest = json.loads(Path(manifest_path).read_text())
    path = Path(human_data).resolve()
    if manifest.get("schema") != "geort_human_input_v1" or manifest.get("split") != "train":
        raise ValueError("Training needs an explicitly assigned train-role input manifest")
    if manifest.get("input_contract") != INPUT_CONTRACT:
        raise ValueError("Training/inference input convention mismatch")
    if hashlib.sha256(path.read_bytes()).hexdigest() != manifest["npy_sha256"]:
        raise ValueError("Training data hash mismatch")
    points = np.load(path, allow_pickle=False)
    if (
        points.ndim != 3
        or points.shape[1:] != (21, 3)
        or len(points) < 2
        or not np.isfinite(points).all()
    ):
        raise ValueError("Training input must be finite N x 21 x 3")
    if not np.allclose(points[:, 0], 0, atol=1e-7):
        raise ValueError("Training data is not wrist-centered")
    palm_lengths = np.linalg.norm(points[:, 9], axis=1)
    if np.any((palm_lengths <= 0.02) | (palm_lengths >= 0.25)):
        raise ValueError("Training input must use meter-scale human palms")
    if manifest.get("frames") != len(points):
        raise ValueError("Training manifest frame count mismatch")
    enable_upstream()
    import torch
    from geort.trainer import GeoRTTrainer

    if not torch.cuda.is_available():
        raise RuntimeError("Original training requires CUDA")
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    run = Path(tempfile.mkdtemp(prefix="training-", dir=folder))
    provenance = {
        "seed": seed,
        "input_manifest": manifest,
        "plan": training_plan(workspace, human_data),
        "status": "started",
    }
    (run / "run_manifest.json").write_text(json.dumps(provenance, indent=2) + "\n")
    previous = Path.cwd()
    try:
        os.chdir(run)  # All upstream relative data/checkpoint output stays project-owned.
        trainer = GeoRTTrainer(config)
        trainer.train(path)  # Preserve original defaults, losses, optimizers and epochs.
    finally:
        os.chdir(previous)
    provenance["status"] = "completed"
    (run / "run_manifest.json").write_text(json.dumps(provenance, indent=2) + "\n")
    return str(run)
