"""Verify source fidelity, independent FK/gradients and public-data contracts."""

import json
from dataclasses import replace

import numpy as np
import pytest

from benchmark.datasets.public import (
    audit_samples,
    audit_split_overlap,
    catalog,
    load_public,
    validate_points,
    verify_file,
    write_frames,
)
from benchmark.experiments.manus_fixtures import pose_frame
from benchmark.experiments.offline_benchmark import OfflineController, main
from benchmark.retargeting.anydex import AnyDexRetargeter, model_config, upstream
from benchmark.tracking.recorder import frame_to_dict, replay_frames


@pytest.mark.parametrize("name,count", [("geort_alex", 3498), ("anydex_avp1", 2751)])
def test_public_adapter_preserves_all_points_units_and_provenance(name, count):
    frames = list(load_public(name))
    assert len(frames) == count
    assert all(
        frame.handedness == "right" and frame.joint_positions.shape == (21, 3) for frame in frames
    )
    item = catalog()[name]
    if name == "geort_alex":
        from benchmark.paths import ROOT

        original = np.load(ROOT / item["local_path"], allow_pickle=False)
        np.testing.assert_array_equal(frames[123].joint_positions, original[123])
    metadata = frames[0].metadata
    assert metadata["is_quest_sdk_output"] is False
    assert metadata["participant_id"] is None
    assert metadata["split"] == "development"
    assert metadata["wrist_pose_measured"] is False
    assert metadata["license"] and metadata["tracking_evidence"]
    assert metadata["scale_applied"] == 1
    assert frames[3].timestamp == pytest.approx(0.1)
    assert frames[0].joint_rotations is None
    assert frames[0].timestamp_domain == "dataset_assumed_replay"
    audit = audit_samples(frames)
    assert audit["frames"] == count
    assert "candidates only" in audit["gesture_policy"]


def test_no_missing_points_padding_or_silent_unit_rescale():
    points = pose_frame("open").joint_positions
    for invalid in (points[:20], np.zeros((21, 3)), points * 1000, np.full((21, 3), np.nan)):
        with pytest.raises(ValueError):
            validate_points(invalid)


def test_dataset_hash_checked_before_unpickling(tmp_path):
    path = tmp_path / "bad.pkl"
    path.write_bytes(b"invalid pickle")
    with pytest.raises(ValueError, match="hash mismatch"):
        verify_file(path, catalog()["anydex_avp1"])


def test_public_frames_round_trip_with_assumed_clock_and_metadata(tmp_path):
    frames = list(load_public("geort_alex"))[:5]
    path = tmp_path / "common.jsonl"
    write_frames(path, frames)
    replayed = list(replay_frames(path))
    assert [frame_to_dict(f) for f in replayed] == [frame_to_dict(f) for f in frames]
    with pytest.raises(FileExistsError):
        write_frames(path, frames)


@pytest.mark.parametrize("key", ["sha256", "sequence_id", "participant_id"])
def test_split_audit_rejects_source_sequence_and_subject_leakage(key):
    a = {"sha256": "a", "sequence_id": "a", "participant_id": "a"}
    b = {"sha256": "b", "sequence_id": "b", "participant_id": "b", key: a[key]}
    with pytest.raises(ValueError, match="leakage"):
        audit_split_overlap({"train": [a], "eval": [b]})
    result = audit_split_overlap({"development": list(catalog().values())})
    assert result["subject_disjoint_verified"] is False


def test_anydex_wrapper_exactly_matches_direct_upstream_calls(robot):
    adapter = AnyDexRetargeter(robot)
    original = upstream().from_config(model_config(robot), hand_side="right")
    for i, kind in enumerate(("open", "closed", "pinch", "open")):
        frame = pose_frame(kind, i * 0.02, i)
        reference, info = original.retarget_verbose(frame.joint_positions)
        result = adapter.retarget(frame)
        ordered = reference[adapter.indices].astype(float)
        np.testing.assert_array_equal(result.metadata["q_vendor_raw"], ordered)
        np.testing.assert_array_equal(
            result.metadata["optimizer_q_unfiltered"], info["qpos_unfiltered"][adapter.indices]
        )
        np.testing.assert_array_equal(result.q_target, robot.validate_target(ordered, clip=True))
    adapter.reset()
    original.reset()
    frame = pose_frame("open")
    np.testing.assert_array_equal(
        adapter.retarget(frame).metadata["q_vendor_raw"],
        original.retarget(frame.joint_positions)[adapter.indices],
    )


def test_pinocchio_fk_jacobian_and_order_agree_with_mujoco(robot):
    adapter = AnyDexRetargeter(robot)
    vendor = adapter.vendor.optimizer.robot
    rng = np.random.default_rng(5)
    q = robot.limits[:, 0] + (robot.limits[:, 1] - robot.limits[:, 0]) * rng.uniform(0.2, 0.8, 20)
    # Pinocchio order may differ from canonical order; map by names in both directions.
    pin_q = q[[robot.joint_names.index(name) for name in adapter.names]]
    ids = [vendor.get_link_index(name) for name in robot.config["tip_links"]]
    positions = vendor.compute_points_batch(pin_q, ids)
    np.testing.assert_allclose(positions, robot.forward_kinematics(q), atol=1e-10)
    jac = vendor.compute_all_jacobians_batch(pin_q, ids)[:, :, adapter.indices]
    np.testing.assert_allclose(jac, robot.fingertip_jacobians(q), atol=1e-10)
    # Independent central difference, not only comparison between two libraries.
    h = 1e-6
    for joint in (0, 5, 10, 19):
        dq = np.zeros(20)
        dq[joint] = h
        fd = (robot.forward_kinematics(q + dq) - robot.forward_kinematics(q - dq)) / (2 * h)
        np.testing.assert_allclose(jac[:, :, joint], fd, atol=1e-8)


def test_invalid_side_degenerate_input_and_time_regression_rejected(robot):
    adapter = AnyDexRetargeter(robot)
    frame = pose_frame("closed", 2)
    adapter.retarget(frame)
    for bad in (
        replace(frame, handedness="left"),
        replace(frame, tracking_valid=False),
        replace(frame, timestamp=1),
        replace(frame, joint_positions=np.zeros((21, 3))),
    ):
        with pytest.raises(ValueError):
            adapter.retarget(bad)


def test_anydex_uses_same_controller_speed_and_tracking_loss_hold(robot):
    a, b = OfflineController(robot, "anydex"), OfflineController(robot, "manus")
    assert a.max_speed == b.max_speed == np.pi
    assert a.timeout == b.timeout
    a.tick(pose_frame("closed", 1), 1)
    assert np.max(np.abs(a.command)) <= np.pi * 0.02 + 1e-12
    held = a.command.copy()
    a.tick(pose_frame("closed", 1), 1.3)
    np.testing.assert_array_equal(a.command, held)
    assert a.status == "HOLD_TRACKING_LOST"


def test_two_method_benchmark_same_inputs_and_repeatable_anydex_state(tmp_path):
    summaries = []
    for name in ("first", "second"):
        folder = tmp_path / name
        main(["--dataset", "anydex_avp1", "--frames", "8", "--output", str(folder)])
        report = json.loads((folder / "comparison.json").read_text())
        assert len({s["common_input_stream_sha256"] for s in report["methods"]}) == 1
        assert all(s["unique_input_frames_evaluated"] == 8 for s in report["methods"])
        rows = [json.loads(line) for line in (folder / "anydex.jsonl").read_text().splitlines()][1:]
        summaries.append(rows)
    assert len(summaries[0]) == len(summaries[1])
    for a, b in zip(*summaries):
        assert a["retarget_q_target"] == b["retarget_q_target"]
        assert a["simulation"] == b["simulation"]


def test_unimplemented_methods_never_replaced_by_fake_baseline(robot):
    with pytest.raises(NotImplementedError):
        OfflineController(robot, "wuji")
    with pytest.raises(NotImplementedError):
        OfflineController(robot, "geort")
