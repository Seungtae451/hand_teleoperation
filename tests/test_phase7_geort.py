"""GeoRT preparation only: no collection, training, learned inference or scoring."""

import json
import os
import xml.etree.ElementTree as ET
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from benchmark.datasets.public import write_frames
from benchmark.experiments.manus_fixtures import pose_frame
from benchmark.geort_support.assets import TEMPLATE, prepare, validate_config
from benchmark.geort_support.cli import main
from benchmark.geort_support.input import INPUT_CONTRACT, canonical_points
from benchmark.geort_support.training import execute_training, export_recording, training_plan
from benchmark.paths import ROOT
from benchmark.retargeting.geort import GeoRTRetargeter
from benchmark.tracking.coordinate_transform import quaternion_matrix


def test_official_config_has_exact_twenty_dof_five_chains():
    config = json.loads(TEMPLATE.read_text())
    _, _, limits = validate_config(config)
    assert limits.shape == (20, 2)
    assert [tip["human_hand_id"] for tip in config["fingertip_link"]] == [4, 8, 12, 16, 20]
    assert [j for tip in config["fingertip_link"] for j in tip["joint"]] == config["joint_order"]
    assert config["base_link"] == "rl_dg_palm"


def test_derived_urdf_changes_only_mesh_filename_resolution(tmp_path):
    config, manifest = prepare(tmp_path / "workspace")
    original = ET.parse(ROOT / manifest["urdf_source"])
    derived = ET.parse(config["urdf_path"])
    before = list(original.getroot().iter("mesh"))
    after = list(derived.getroot().iter("mesh"))
    assert len(before) == len(after) == 56
    for a, b in zip(before, after):
        assert Path(b.get("filename")).is_absolute()
        assert Path(b.get("filename")).is_file()
        b.set("filename", a.get("filename"))
    assert ET.tostring(original.getroot()) == ET.tostring(derived.getroot())
    assert manifest["training_executed"] is False
    assert manifest["inference_executed"] is False
    assert not list((tmp_path / "workspace").rglob("*.pth"))
    with pytest.raises(FileExistsError):
        prepare(tmp_path / "workspace")


@pytest.mark.parametrize("field", ["joint_order", "fingertip_link", "base_link"])
def test_incompatible_robot_configs_are_rejected(field):
    config = json.loads(TEMPLATE.read_text())
    config[field] = [] if field != "base_link" else "invented_link"
    with pytest.raises(ValueError):
        validate_config(config)


def test_canonical_points_preserve_geometry_and_ignore_global_wrist_motion():
    frame = pose_frame("closed")
    expected = canonical_points(frame)
    q = np.array([0.1, 0.2, 0.3, 0.9])
    q /= np.linalg.norm(q)
    rotation = quaternion_matrix(q)
    world = replace(frame, joint_positions=frame.joint_positions @ rotation.T + [1, 2, 3])
    np.testing.assert_allclose(canonical_points(world), expected, atol=1e-12)
    local = replace(
        frame, coordinate_frame="wrist_rh", wrist_position=np.array([1, 2, 3]), wrist_rotation=q
    )
    np.testing.assert_allclose(canonical_points(local), expected, atol=1e-12)
    np.testing.assert_allclose(expected[0], 0, atol=1e-12)
    for base in (1, 5, 9, 13, 17):
        np.testing.assert_allclose(
            np.linalg.norm(np.diff(expected[base : base + 4], axis=0), axis=1),
            np.linalg.norm(np.diff(frame.joint_positions[base : base + 4], axis=0), axis=1),
        )


def test_invalid_side_tracking_scale_and_degenerate_bones_are_never_repaired():
    frame = pose_frame("open")
    missing = frame.joint_positions.copy()
    missing[4] = missing[3]
    for invalid in (
        replace(frame, handedness="left"),
        replace(frame, tracking_valid=False),
        replace(frame, joint_positions=missing),
        replace(frame, joint_positions=frame.joint_positions * 1000),
        replace(frame, joint_positions=np.zeros((21, 3))),
    ):
        with pytest.raises(ValueError):
            canonical_points(invalid)


def test_export_uses_original_canonical_convention_and_explicit_drop_policy(tmp_path):
    frames = [
        pose_frame("open", 0),
        replace(pose_frame("closed", 1), tracking_valid=False),
        pose_frame("pinch", 2),
    ]
    recording = tmp_path / "fixture.jsonl"
    write_frames(recording, frames)
    with pytest.raises(ValueError):
        export_recording(recording, tmp_path / "reject")
    report = export_recording(
        recording, tmp_path / "export", split="development", drop_invalid=True
    )
    points = np.load(tmp_path / "export/human.npy", allow_pickle=False)
    assert points.shape == (2, 21, 3)
    np.testing.assert_array_equal(points[0], canonical_points(frames[0]))
    assert report["invalid_right_frames_skipped"] == 1
    assert report["retained_frame_provenance"][1]["timestamp"] == 2
    assert report["input_contract"] == INPUT_CONTRACT
    assert report["training_executed"] is False


def test_train_command_without_execute_never_invokes_training(tmp_path, monkeypatch):
    prepare(tmp_path / "workspace")

    def forbidden(*args, **kwargs):
        raise AssertionError("Training must not be invoked")

    monkeypatch.setattr("benchmark.geort_support.cli.execute_training", forbidden)
    report = main(["train", "--workspace", str(tmp_path / "workspace")])
    assert report["mode"] == "plan_only" and not report["training_executed"]
    assert not report["data_ready"]
    assert not list(tmp_path.rglob("*.pth"))
    with pytest.raises(SystemExit):
        main(["train", "--workspace", str(tmp_path / "workspace"), "--execute"])


def test_training_preflight_rejects_eval_role_before_importing_trainer(tmp_path):
    prepare(tmp_path / "workspace")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"schema": "geort_human_input_v1", "split": "eval"}))
    with pytest.raises(ValueError, match="train-role"):
        execute_training(tmp_path / "workspace", tmp_path / "missing.npy", manifest)
    assert not list(tmp_path.rglob("training-*"))


def test_workspace_modification_is_detected_before_training(tmp_path):
    _, _ = prepare(tmp_path / "workspace")
    p = tmp_path / "workspace/dg5f_right_resolved.urdf"
    p.write_bytes(p.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="URDF changed"):
        training_plan(tmp_path / "workspace")


def test_checkpoint_absence_and_wrong_robot_config_fail_without_neural_output(robot, tmp_path):
    with pytest.raises(FileNotFoundError, match="trained DG-5F"):
        GeoRTRetargeter(robot, checkpoint=tmp_path / "missing.pth", config_path=TEMPLATE)
    config = json.loads(TEMPLATE.read_text())
    config["joint_order"] = config["joint_order"][:16]
    path = tmp_path / "wrong.json"
    path.write_text(json.dumps(config))
    sentinel = tmp_path / "never-loaded.pth"
    sentinel.write_bytes(b"not a model")
    with pytest.raises(ValueError, match="mismatch"):
        GeoRTRetargeter(robot, checkpoint=sentinel, config_path=path)


def test_original_runtime_fk_and_architecture_without_neural_forward(tmp_path):
    if os.environ.get("GEORT_RUNTIME_TEST") != "1":
        pytest.skip("Use isolated GeoRT environment with GEORT_RUNTIME_TEST=1")
    from benchmark.geort_support.runtime import check_runtime
    from benchmark.geort_support.source import enable_upstream

    prepare(tmp_path / "workspace")
    enable_upstream()
    from geort.trainer import GeoRTTrainer

    assert callable(GeoRTTrainer.train)  # Import compatibility only; never call it.
    report = check_runtime(tmp_path / "workspace")
    assert report["joint_count"] == 20 and report["fingertip_count"] == 5
    assert report["max_sapien_mujoco_fk_difference_m"] < 2e-6
    assert report["network_architecture"]["forward_executed"] is False
    assert not report["training_executed"]


@pytest.mark.parametrize("kind", ["empty", "millimeter", "count"])
def test_invalid_training_data_stops_during_preflight_without_loading_trainer(tmp_path, kind):
    import hashlib

    prepare(tmp_path / "workspace")
    points = np.array(
        [canonical_points(pose_frame("open")), canonical_points(pose_frame("closed"))]
    )
    count = 2
    if kind == "empty":
        points = np.empty((0, 21, 3))
        count = 0
    elif kind == "millimeter":
        points *= 1000
    else:
        count = 3
    path = tmp_path / "synthetic-invalid.npy"
    np.save(path, points)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "geort_human_input_v1",
                "split": "train",
                "input_contract": INPUT_CONTRACT,
                "frames": count,
                "npy_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    )
    with pytest.raises(ValueError):
        execute_training(tmp_path / "workspace", path, manifest)
    assert not list(tmp_path.rglob("training-*"))
