"""Original Wuji fidelity, shared loss structure, constraint semantics and integration."""

import json
from copy import deepcopy
from dataclasses import replace

import numpy as np
import pytest

from benchmark.datasets.public import catalog
from benchmark.experiments.manus_fixtures import pose_frame
from benchmark.experiments.offline_benchmark import OfflineController
from benchmark.experiments.phase6_cli import main, wuji_registration
from benchmark.paths import ROOT
from benchmark.retargeting.anydex import AnyDexRetargeter
from benchmark.retargeting.wuji import WujiRetargeter, model_config, upstream
from benchmark.tracking.coordinate_transform import quaternion_matrix


def targets(optimizer, points):
    return (
        optimizer._compute_tip_vectors(points, optimizer.scaling),
        optimizer._compute_tip_dirs(points),
        optimizer._compute_full_hand_vectors(points, optimizer.segment_scaling),
    )


def test_wuji_adapter_matches_original_calls_and_reset_exactly(robot):
    adapter = WujiRetargeter(robot)
    original = upstream().from_config(deepcopy(model_config(robot)), hand_side="right")
    for i, kind in enumerate(("open", "closed", "pinch", "open")):
        frame = pose_frame(kind, i * 0.02, i)
        expected, info = original.retarget_verbose(frame.joint_positions)
        result = adapter.retarget(frame)
        np.testing.assert_array_equal(result.metadata["q_vendor_raw"], expected[adapter.indices])
        np.testing.assert_array_equal(
            result.metadata["optimizer_q_unfiltered"], info["qpos_unfiltered"][adapter.indices]
        )
        np.testing.assert_array_equal(
            result.q_target, robot.validate_target(expected[adapter.indices], clip=True)
        )
    adapter.reset()
    original.reset()
    frame = pose_frame("closed")
    np.testing.assert_array_equal(
        adapter.retarget(frame).metadata["q_vendor_raw"],
        original.retarget(frame.joint_positions)[adapter.indices],
    )


def test_wuji_fk_and_jacobian_match_common_mujoco(robot):
    adapter = WujiRetargeter(robot)
    vendor = adapter.vendor.optimizer.robot
    q = robot.limits.mean(axis=1) * 0.7
    pin_q = q[[robot.joint_names.index(n) for n in adapter.names]]
    ids = [vendor.get_link_index(n) for n in robot.config["tip_links"]]
    points = vendor.compute_fk_batch(pin_q, ids).reshape(5, 3)
    np.testing.assert_allclose(points, robot.forward_kinematics(q), atol=1e-10)
    jac = vendor.compute_all_jacobians_batch(pin_q, ids)[:, :, adapter.indices]
    np.testing.assert_allclose(jac, robot.fingertip_jacobians(q), atol=1e-10)


def test_flex_indices_follow_real_urdf_and_optional_constraints_stay_default_off(robot):
    adapter = WujiRetargeter(robot)
    opt = adapter.vendor.optimizer
    assert adapter.constraint_binding["pip_joint_names"] == [f"rj_dg_{i}_3" for i in range(1, 6)]
    assert adapter.constraint_binding["dip_joint_names"] == [f"rj_dg_{i}_4" for i in range(1, 6)]
    assert opt.w_hyper == opt.w_couple == 0
    assert not opt.thumb_skip_pip
    assert opt.couple_ratio == 0.7
    assert adapter.vendor.lp_filter.alpha == 0.2
    assert np.all(opt.robot.joint_limits[opt._flex_idx, 0] < 0)


@pytest.mark.parametrize("kind", ["open", "closed", "pinch"])
def test_original_default_objectives_share_base_loss_without_invented_algorithm_difference(
    robot, kind
):
    a = AnyDexRetargeter(robot).vendor.optimizer
    w = WujiRetargeter(robot).vendor.optimizer
    from wuji_retargeting.mediapipe import apply_mediapipe_transformations

    p = apply_mediapipe_transformations(pose_frame(kind).joint_positions)
    alpha = w._compute_pinch_alpha(p)
    at = a._compute_adaptive_targets(p, alpha)
    wt = targets(w, p)
    for x, y in zip(at, wt):
        np.testing.assert_allclose(x, y, atol=1e-12)
    q = w.robot.joint_limits.mean(axis=1)
    last = q * 0.8
    av, ag = a._loss_and_grad_analytical(q, *at, alpha, last)
    wv, wg = w._loss_and_grad_analytical(q, *wt, alpha, last)
    assert av == pytest.approx(wv, abs=1e-10)
    np.testing.assert_allclose(ag, wg, atol=1e-10)


def test_original_optional_penalties_have_expected_cost_and_gradient_on_mapped_joints(robot):
    # Diagnostic of the original optional branch, not the evaluation configuration.
    base = WujiRetargeter(robot).vendor.optimizer
    config = deepcopy(model_config(robot))
    config["retarget"] = {"w_hyper": 1.0, "w_couple": 0.1}
    extra = upstream().from_config(config).optimizer
    from wuji_retargeting.mediapipe import apply_mediapipe_transformations

    p = apply_mediapipe_transformations(pose_frame("closed").joint_positions)
    t = targets(base, p)
    alpha = base._compute_pinch_alpha(p)
    q = base.robot.joint_limits.mean(axis=1)
    q[base._pip_idx] = [-0.2, 0.3, -0.4, 0.5, -0.6]
    q[base._dip_idx] = [0.1, -0.2, 0.3, -0.4, 0.5]
    bcost, bgrad = base._loss_and_grad_analytical(q, *t, alpha, None)
    ecost, egrad = extra._loss_and_grad_analytical(q, *t, alpha, None)
    penalty = np.maximum(-q[base._flex_idx], 0)
    diff = q[base._dip_idx] - 0.7 * q[base._pip_idx]
    assert ecost - bcost == pytest.approx(np.sum(penalty**2) + 0.1 * np.sum(diff**2))
    expected = np.zeros(20)
    expected[base._flex_idx] -= 2 * penalty
    expected[base._dip_idx] += 0.2 * diff
    expected[base._pip_idx] -= 0.14 * diff
    np.testing.assert_allclose(egrad - bgrad, expected, atol=1e-11)
    # An independent derivative check exercises the complete upstream objective.
    h = 1e-6
    for i in range(20):
        dq = np.zeros(20)
        dq[i] = h
        plus, _ = extra._loss_and_grad_analytical(q + dq, *t, alpha, None)
        minus, _ = extra._loss_and_grad_analytical(q - dq, *t, alpha, None)
        assert egrad[i] == pytest.approx((plus - minus) / (2 * h), abs=2e-5)


def test_invalid_hand_tracking_time_and_geometry_rejected(robot):
    adapter = WujiRetargeter(robot)
    frame = pose_frame("open", 2)
    adapter.retarget(frame)
    for bad in (
        replace(frame, timestamp=1),
        replace(frame, handedness="left"),
        replace(frame, tracking_valid=False),
        replace(frame, joint_positions=np.zeros((21, 3))),
    ):
        with pytest.raises(ValueError):
            adapter.retarget(bad)


def test_local_wrist_coordinates_reconstruct_same_original_input(robot):
    frame = pose_frame("closed")
    q = np.array([0.1, 0.2, 0.3, 0.9])
    q /= np.linalg.norm(q)
    rot = quaternion_matrix(q)
    moved = replace(frame, joint_positions=frame.joint_positions @ rot.T + [1, 2, 3])
    a, b = WujiRetargeter(robot), WujiRetargeter(robot)
    ma = a.retarget(frame).metadata["optimizer_input_m"]
    mb = b.retarget(moved).metadata["optimizer_input_m"]
    np.testing.assert_allclose(ma, mb, atol=1e-12)


def test_shared_controller_loss_hold_and_registry_restoration(robot):
    from benchmark.retargeting import registry

    before = registry._FACTORIES.copy()
    with wuji_registration():
        with wuji_registration():
            controller = OfflineController(robot, "wuji")
            controller.tick(pose_frame("closed", 1), 1)
            assert np.max(abs(controller.command)) <= np.pi * 0.02 + 1e-12
            held = controller.command.copy()
            controller.tick(pose_frame("closed", 1), 1.3)
            assert controller.status == "HOLD_TRACKING_LOST"
            np.testing.assert_array_equal(controller.command, held)
    assert registry._FACTORIES == before


def test_three_method_replay_is_identical_input_and_wuji_deterministic(tmp_path):
    runs = []
    for name in ("a", "b"):
        folder = tmp_path / name
        report = main(["--dataset", "anydex_avp1", "--frames", "8", "--output", str(folder)])
        assert len(report["methods"]) == 3
        assert len({s["common_input_stream_sha256"] for s in report["methods"]}) == 1
        assert all(s["unique_input_frames_evaluated"] == 8 for s in report["methods"])
        rows = [json.loads(line) for line in (folder / "wuji.jsonl").read_text().splitlines()][1:]
        runs.append(rows)
    for a, b in zip(*runs):
        assert a["retarget_q_target"] == b["retarget_q_target"]
        assert a["simulation"] == b["simulation"]


def test_official_wuji_lfs_example_aliases_existing_anydex_blob():
    pointer = (ROOT / "external/wuji-retargeting/example/data/avp1.pkl").read_text()
    assert pointer.startswith("version https://git-lfs.github.com/spec/v1")
    assert f"oid sha256:{catalog()['anydex_avp1']['sha256']}" in pointer
    assert f"size {catalog()['anydex_avp1']['bytes']}" in pointer
