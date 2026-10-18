"""Check direction in exact FK and preserve upstream mapping/other fingers."""

import numpy as np
import pytest

from benchmark.retargeting.manus import ManusRetargeter
from benchmark.retargeting.quest_ergonomics import geometric_features, manus_ergonomics_proxy
from scripts.inspect_manus_thumb import controlled_frame, robot_direction


def test_axis_convention_is_a_coordinate_change_not_vendor_parameter_fit():
    f = np.arange(20, dtype=float)
    f[:2] = [40, 20]
    new = manus_ergonomics_proxy(f)
    np.testing.assert_allclose(new[:2], [20, 50])
    np.testing.assert_array_equal(new[2:], f[2:])
    np.testing.assert_array_equal(manus_ergonomics_proxy(f, "legacy_v1"), f)
    np.testing.assert_array_equal(f[:2], [40, 20])
    with pytest.raises(ValueError):
        manus_ergonomics_proxy(f, "unknown")


def test_vendor_offsets_gains_and_non_thumb_outputs_remain_original(robot):
    adapter = ManusRetargeter(robot)
    frame = controlled_frame(40, 20)
    f = geometric_features(frame)
    output = adapter.retarget(frame)
    raw = np.array(output.metadata["q_vendor_raw"])
    expected_input = manus_ergonomics_proxy(f)
    np.testing.assert_allclose(raw, adapter.vendor(expected_input, "right"))
    np.testing.assert_allclose(np.degrees(raw[:2]), [8.5, -64])
    legacy = np.array(adapter.vendor(f, "right"))
    np.testing.assert_array_equal(raw[2:], legacy[2:])


def test_unsaturated_base_directions_follow_each_input_axis_in_fk(robot):
    adapter = ManusRetargeter(robot)
    outputs = []
    for a, e in [(40, 20), (50, 20), (40, 30)]:
        adapter.reset()
        result = adapter.retarget(controlled_frame(a, e))
        v, angles = robot_direction(robot, result.q_target)
        outputs.append((v, angles))
    v0, angles0 = outputs[0]
    va, angles_a = outputs[1]
    ve, angles_e = outputs[2]
    assert va[2] > v0[2]  # +distal movement rather than the legacy negative response
    assert ve[0] > v0[0]  # +palmar movement
    np.testing.assert_allclose(angles_a - angles0, [10, 0], atol=1e-10)
    np.testing.assert_allclose(angles_e - angles0, [0, 16], atol=1e-10)


def test_legacy_mode_reproduces_old_result(robot):
    old = ManusRetargeter(robot, {"handedness": "right", "thumb_input_convention": "legacy_v1"})
    frame = controlled_frame(40, 20)
    result = old.retarget(frame)
    np.testing.assert_array_equal(
        result.metadata["ergonomics_proxy_deg"], geometric_features(frame)
    )
    np.testing.assert_allclose(np.degrees(result.metadata["q_vendor_raw"][:2]), [38.5, -96])
