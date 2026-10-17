"""Test the measured angle definitions without generating a human dataset."""

import numpy as np
import pytest

from scripts.measure_quest_joint_ranges import bend, projected_mcp


def test_metacarpal_relative_flexion_and_rigid_rotation_invariance():
    meta = np.array([0.0, 0.0, 1.0])
    palm_normal = np.array([1.0, 0.0, 0.0])
    rotation = np.array([[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])
    for degrees in [-20, 0, 45, 100]:
        radians = np.deg2rad(degrees)
        proximal = np.array([np.sin(radians), 0, np.cos(radians)])
        assert projected_mcp(meta, proximal, palm_normal) == pytest.approx(degrees)
        assert projected_mcp(
            rotation @ meta, rotation @ proximal, rotation @ palm_normal
        ) == pytest.approx(degrees)


def test_unsigned_bend_does_not_claim_extension_sign():
    first = np.array([0.0, 0.0, 1.0])
    for degrees in [-30, 30, 90]:
        radians = np.deg2rad(degrees)
        last = np.array([np.sin(radians), 0, np.cos(radians)])
        assert bend(first, last) == pytest.approx(abs(degrees))
    with pytest.raises(ValueError):
        bend(np.zeros(3), first)
    with pytest.raises(ValueError):
        projected_mcp(first, first, first)
