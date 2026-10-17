"""Range-only changes and physical-radian normalization invariants."""

import numpy as np

from benchmark.geort_support.range_experiment import (
    RESTRICTED_INDICES,
    normalization_affine,
    restricted_bounds,
)
from benchmark.simulation.robot_model import RobotModel


def test_exactly_eight_lower_bounds_change_and_source_is_preserved():
    full = RobotModel().limits
    original = full.copy()
    bounds = restricted_bounds(full)
    np.testing.assert_array_equal(full, original)
    np.testing.assert_array_equal(bounds[:, 1], full[:, 1])
    assert np.flatnonzero(bounds[:, 0] != full[:, 0]).tolist() == list(RESTRICTED_INDICES)
    np.testing.assert_array_equal(bounds[list(RESTRICTED_INDICES), 0], 0)
    np.testing.assert_allclose(bounds[list(RESTRICTED_INDICES), 1], np.pi / 2)


def test_same_radians_under_two_normalizers():
    full = RobotModel().limits
    limited = restricted_bounds(full)
    q = np.random.default_rng(4).uniform(limited[:, 0], limited[:, 1], size=(128, 20))
    norm_limited = 2 * (q - limited[:, 0]) / (limited[:, 1] - limited[:, 0]) - 1
    norm_full = 2 * (q - full[:, 0]) / (full[:, 1] - full[:, 0]) - 1
    scale, bias = normalization_affine(limited, full)
    np.testing.assert_allclose(norm_limited * scale + bias, norm_full, atol=1e-14)
    s, b = normalization_affine(full, full)
    np.testing.assert_array_equal(s, np.ones(20))
    np.testing.assert_array_equal(b, np.zeros(20))
