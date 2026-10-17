import json
from copy import deepcopy

import numpy as np
import pytest

from benchmark.tracking.coordinate_transform import (
    matrix_quaternion,
    quaternion_matrix,
    transform_world_frame,
    world_points,
)
from benchmark.tracking.receiver_state import ReceiverState
from benchmark.tracking.recorder import HandRecorder, frame_to_dict, read_events, replay_frames
from benchmark.tracking.synthetic import synthetic_packet
from benchmark.tracking.webxr_protocol import (
    COMMON_INDICES,
    COMMON_JOINT_NAMES,
    WEBXR_JOINT_NAMES,
    hand_frame_from_packet,
    validate_envelope,
)


def test_webxr_named_mapping_selects_21_actual_joints_without_non_thumb_metacarpals():
    assert len(WEBXR_JOINT_NAMES) == 25
    assert len(COMMON_JOINT_NAMES) == 21
    assert COMMON_INDICES == (
        0,
        1,
        2,
        3,
        4,
        6,
        7,
        8,
        9,
        11,
        12,
        13,
        14,
        16,
        17,
        18,
        19,
        21,
        22,
        23,
        24,
    )
    assert [COMMON_JOINT_NAMES[i] for i in (4, 8, 12, 16, 20)] == [
        "thumb-tip",
        "index-finger-tip",
        "middle-finger-tip",
        "ring-finger-tip",
        "pinky-finger-tip",
    ]
    packet = synthetic_packet()
    frame = hand_frame_from_packet(packet, "right", 42, "test")
    native = np.array(packet["hands"]["right"]["positions"])
    np.testing.assert_allclose(frame.joint_positions, native[list(COMMON_INDICES)] - native[0])
    np.testing.assert_array_equal(frame.joint_positions[0], np.zeros(3))
    assert frame.timestamp == 42 and frame.timestamp_domain == "receiver_monotonic"
    assert frame.joint_rotations.shape == (21, 4)
    assert frame.coordinate_frame == "wrist_rh"


def test_quaternion_roundtrip_random_and_pi_rotations():
    rng = np.random.default_rng(17)
    quaternions = [np.array([1, 0, 0, 0]), np.array([0, 1, 0, 0]), np.array([0, 0, 1, 0])]
    for q in rng.normal(size=(50, 4)):
        quaternions.append(q / np.linalg.norm(q))
    for q in quaternions:
        r = quaternion_matrix(q)
        np.testing.assert_allclose(quaternion_matrix(matrix_quaternion(r)), r, atol=2e-15)


@pytest.mark.parametrize("side", ["left", "right"])
@pytest.mark.parametrize("target", ["wrist_rh", "palm_rh"])
def test_rigid_source_transform_preserves_local_geometry_and_orientation(side, target):
    packet = synthetic_packet()
    before = hand_frame_from_packet(packet, side, 1, "s", target)
    q = np.array([0.3, -0.4, 0.2, 0.7])
    q /= np.linalg.norm(q)
    rotation = quaternion_matrix(q)
    offset = np.array([1.5, -0.2, 0.8])
    hand = packet["hands"][side]
    hand["positions"] = (np.array(hand["positions"]) @ rotation.T + offset).tolist()
    hand["rotations"] = [q.tolist() for _ in range(25)]
    after = hand_frame_from_packet(packet, side, 2, "s", target)
    np.testing.assert_allclose(before.joint_positions, after.joint_positions, atol=1e-15)
    for a, b in zip(before.joint_rotations, after.joint_rotations):
        np.testing.assert_allclose(quaternion_matrix(a), quaternion_matrix(b), atol=5e-15)
    expected_world = np.array(hand["positions"])[list(COMMON_INDICES)]
    np.testing.assert_allclose(world_points(after), expected_world, atol=2e-15)
    assert after.handedness == side


def test_palm_axes_are_orthogonal_and_degenerate_pose_is_rejected():
    packet = synthetic_packet()
    world = hand_frame_from_packet(packet, "right", 1, "s", "world_rh")
    palm = transform_world_frame(world, "palm_rh")
    assert palm.joint_positions[9, 2] > 0
    np.testing.assert_allclose(palm.joint_positions[9, :2], 0, atol=1e-15)
    assert palm.joint_positions[5, 1] > palm.joint_positions[17, 1]
    world.joint_positions[9] = world.joint_positions[0]
    with pytest.raises(ValueError, match="Degenerate"):
        transform_world_frame(world, "palm_rh")


@pytest.mark.parametrize(
    "mutation", ["names", "shape", "nan", "rotation", "emulated", "valid_flag"]
)
def test_invalid_native_packets_never_partially_commit_one_hand(mutation):
    packet = synthetic_packet()
    hand = packet["hands"]["right"]
    if mutation == "names":
        packet["joint_names"][0] = "invented"
    elif mutation == "shape":
        hand["positions"] = hand["positions"][:21]
    elif mutation == "nan":
        hand["positions"][4][0] = np.nan
    elif mutation == "rotation":
        hand["rotations"][4] = [0, 0, 0, 0]
    elif mutation == "emulated":
        hand["emulated"] = True
    elif mutation == "valid_flag":
        hand["valid"] = 1
    state = ReceiverState()
    state.connect("s", 0)
    with pytest.raises(ValueError):
        state.accept(packet, "s", 1)
    assert state.latest == {} and state.accepted_packets == 0 and state.rejected_packets == 1


def test_ordering_timeout_disconnect_and_new_session_reset():
    state = ReceiverState(timeout=0.25)
    state.connect("one", 10)
    state.accept(synthetic_packet(10, 10), "one", 10)
    with pytest.raises(ValueError, match="Out-of-order"):
        state.accept(synthetic_packet(10, 10), "one", 10.1)
    with pytest.raises(ValueError, match="Out-of-order"):
        state.accept(synthetic_packet(11, 9), "one", 10.1)
    assert state.status(10.24)["hands"]["right"]["valid"]
    assert not state.status(10.26)["hands"]["right"]["valid"]
    invalid = state.latest["right"]
    assert invalid.metadata["held_pose"] and invalid.metadata["invalid_reason"] == "receive_timeout"
    state.disconnect(10.3)
    state.connect("two", 20)
    assert state.latest == {}
    with pytest.raises(ValueError, match="active source"):
        state.accept(synthetic_packet(), "one", 20.1)
    state.accept(synthetic_packet(), "two", 20.2)
    assert state.latest["right"].tracking_valid


def test_no_fake_hand_pose_before_first_valid_tracking():
    state = ReceiverState()
    state.connect("s", 0)
    state.accept(synthetic_packet(lost=True), "s", 1)
    assert state.latest == {}
    assert state.status(1)["hands"]["right"]["frame"] is None


def test_recording_preserves_native_data_invalid_events_and_exact_canonical_replay(tmp_path):
    path = tmp_path / "hands.jsonl"
    packets = [
        synthetic_packet(0, 0),
        synthetic_packet(1, 0.1, lost=True),
        synthetic_packet(2, 0.2),
    ]
    original = deepcopy(packets)
    with HandRecorder(path, source_kind="synthetic_webxr") as recorder:
        state = ReceiverState(recorder=recorder)
        state.connect("s", 100)
        for i, packet in enumerate(packets):
            state.accept(packet, "s", 100 + i * 0.1)
        state.expire(101)
        state.disconnect(102)
    events = list(read_events(path))
    assert [e["packet"] for e in events if e["event"] == "native_packet"] == original
    recorded = [e["frame"] for e in events if e["event"] == "hand_frame"]
    replayed = [frame_to_dict(frame) for frame in replay_frames(path)]
    assert recorded == replayed and len(replayed) == 8
    assert sum(f["tracking_valid"] for f in replayed) == 4
    assert len(list(replay_frames(path, handedness="right", include_invalid=False))) == 2
    assert packets == original
    with pytest.raises(FileExistsError):
        HandRecorder(path)


def test_reference_reset_is_recorded_and_reference_epoch_cannot_regress(tmp_path):
    path = tmp_path / "reset.jsonl"
    with HandRecorder(path) as recorder:
        state = ReceiverState(recorder=recorder)
        state.connect("s", 0)
        state.accept(synthetic_packet(), "s", 1)
        packet = {
            "version": 1,
            "type": "reference_reset",
            "sequence": 1,
            "source_time_ms": 10,
            "reference_space": "local",
            "reference_epoch": 1,
        }
        state.accept(packet, "s", 2)
        assert not state.latest["left"].tracking_valid
        with pytest.raises(ValueError, match="epoch regressed"):
            state.accept(synthetic_packet(2, 0.02), "s", 3)
    assert any(e.get("reason") == "reference_reset" for e in read_events(path))


def test_replay_rejects_bad_schema_and_time_regression(tmp_path):
    path = tmp_path / "bad.jsonl"
    path.write_text('{"schema":"wrong"}\n')
    with pytest.raises(ValueError, match="schema"):
        list(replay_frames(path))
    frame = hand_frame_from_packet(synthetic_packet(), "right", 2, "s")
    events = [
        {"schema": "quest_hand_recording_v1"},
        {"event": "hand_frame", "frame": frame_to_dict(frame)},
    ]
    frame.timestamp = 1
    events.append({"event": "hand_frame", "frame": frame_to_dict(frame)})
    path.write_text("\n".join(map(json.dumps, events)) + "\n")
    with pytest.raises(ValueError, match="regress"):
        list(replay_frames(path))
    with pytest.raises(ValueError, match="speed"):
        list(replay_frames(path, speed=0))


def test_unknown_reference_space_rejected():
    packet = synthetic_packet()
    packet["reference_space"] = "invented"
    with pytest.raises(ValueError, match="reference space"):
        validate_envelope(packet)
