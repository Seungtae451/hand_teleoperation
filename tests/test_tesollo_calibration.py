"""Check native config semantics and preserve original solver behavior."""

import json

import numpy as np
import pytest

from benchmark.paths import ROOT
from benchmark.retargeting.anydex import AnyDexRetargeter
from benchmark.retargeting.tesollo_calibration import (
    CalibratedAnyDex,
    CalibratedWuji,
    load_profile,
    select_open_frames,
    verify_fk,
)
from benchmark.retargeting.wuji import WujiRetargeter
from benchmark.simulation.robot_model import RobotModel
from benchmark.tracking.coordinate_transform import world_points
from benchmark.tracking.recorder import replay_frames

PROFILE = ROOT / "configs/tesollo_calibrated/profile.json"


@pytest.fixture(scope="module")
def robot():
    return RobotModel()


@pytest.fixture(scope="module")
def frame():
    return next(
        replay_frames(
            ROOT / "recordings/geort_train_session_001.jsonl",
            handedness="right",
            include_invalid=False,
        )
    )


@pytest.mark.parametrize(
    "factory,base,method",
    [
        (CalibratedAnyDex, AnyDexRetargeter, "anydex"),
        (CalibratedWuji, WujiRetargeter, "wuji"),
    ],
)
def test_configured_adapter_matches_direct_original_api(robot, frame, factory, base, method):
    configured = factory(robot, profile=PROFILE)
    baseline = base(robot)
    reference = type(configured.vendor).from_config(
        json.loads(json.dumps(configured.config)), hand_side="right"
    )
    original, info = reference.retarget_verbose(world_points(frame))
    result = configured.retarget(frame)
    expected_raw = np.asarray(original)[configured.indices]
    np.testing.assert_allclose(result.metadata["q_vendor_raw"], expected_raw, atol=1e-7)
    np.testing.assert_allclose(result.q_target, robot.validate_target(expected_raw, clip=True))
    np.testing.assert_allclose(result.metadata["optimizer_input_m"], info["mediapipe_kp"])
    for name in ("huber_delta", "huber_delta_dir", "norm_delta", "w_pos", "w_dir", "w_full_hand"):
        assert getattr(configured.vendor.optimizer, name) == getattr(
            baseline.vendor.optimizer, name
        )
    assert configured.vendor.lp_filter.alpha == baseline.vendor.lp_filter.alpha
    assert (
        configured.vendor.optimizer.opt.get_maxeval() == baseline.vendor.optimizer.opt.get_maxeval()
    )
    assert configured.config["retarget"] != baseline.config["retarget"]
    assert verify_fk(robot, configured, count=2)["max_coordinate_error_m"] < 2e-6


def test_distinct_native_scaling_definitions(robot):
    anydex = CalibratedAnyDex(robot, profile=PROFILE)
    wuji = CalibratedWuji(robot, profile=PROFILE)
    document = load_profile(PROFILE, robot)
    np.testing.assert_allclose(
        anydex.vendor.optimizer.segment_scaling_full,
        [
            document["methods"]["anydex"]["config"]["retarget"]["segment_scaling"][f]
            for f in robot.fingers
        ],
    )
    np.testing.assert_allclose(
        wuji.vendor.optimizer.segment_scaling,
        [
            document["methods"]["wuji"]["config"]["retarget"]["segment_scaling"][f]
            for f in robot.fingers
        ],
    )
    assert not wuji.vendor.optimizer.w_hyper and not wuji.vendor.optimizer.w_couple


@pytest.mark.parametrize("mutation", ["units", "joint_order", "loss_weight", "negative", "nan"])
def test_reject_invalid_or_algorithm_tuning_profiles(robot, tmp_path, mutation):
    document = json.loads(PROFILE.read_text())
    if mutation == "units":
        document["units"] = "cm"
    elif mutation == "joint_order":
        document["joint_names"].reverse()
    elif mutation == "loss_weight":
        document["methods"]["anydex"]["config"]["retarget"]["w_pos"] = 99
    elif mutation == "negative":
        document["methods"]["wuji"]["config"]["retarget"]["segment_scaling"]["thumb"][0] = -1
    else:
        document["methods"]["anydex"]["config"]["retarget"]["pinch_scaling"] = float("nan")
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError):
        load_profile(path, robot)


def test_short_capture_never_produces_fabricated_calibration(frame):
    with pytest.raises(ValueError):
        select_open_frames([frame])
