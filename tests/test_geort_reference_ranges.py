"""Reference provenance, hardware containment and incompatible checkpoint guards."""

import json

import numpy as np
import pytest

from benchmark.geort_support.reference_ranges import (
    ReferenceRangeRetargeter,
    build_profile,
    verify_profile,
)
from benchmark.paths import ROOT
from benchmark.simulation.robot_model import RobotModel


def test_reference_profile_is_subset_with_declared_unmapped_joints():
    robot = RobotModel()
    profile = build_profile(robot)
    bounds = np.array(profile["bounds_rad"])
    assert len(profile["mappings"]) == 9 and len(profile["unmapped"]) == 11
    assert np.all(bounds[:, 0] >= robot.limits[:, 0]) and np.all(bounds[:, 1] <= robot.limits[:, 1])
    # Source MCP reference caps flexion at 1.61, unlike the previous distal-only experiment.
    np.testing.assert_allclose(bounds[9], [0, 1.61])
    np.testing.assert_allclose(bounds[10], [-0.174, np.pi / 2])
    np.testing.assert_allclose(bounds[11], [-0.227, np.pi / 2])
    for item in profile["unmapped"]:
        i = robot.joint_names.index(item["joint"])
        np.testing.assert_array_equal(bounds[i], robot.limits[i])


def test_profile_tampering_is_rejected(tmp_path):
    profile = build_profile()
    profile["bounds_rad"][10][0] = -1.5
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(profile))
    with pytest.raises(ValueError, match="pinned mapping"):
        verify_profile(path)


def test_old_full_range_weights_cannot_be_reinterpreted_as_reference_model(tmp_path):
    robot = RobotModel()
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps(build_profile(robot)))
    config = json.loads((ROOT / "configs/geort_dg5f_right.json").read_text())
    config["joint"] = {"lower": robot.limits[:, 0].tolist(), "upper": robot.limits[:, 1].tolist()}
    path = tmp_path / "old_config.json"
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="retraining required"):
        ReferenceRangeRetargeter(
            robot, checkpoint=tmp_path / "not_loaded.pth", config_path=path, profile=profile
        )
