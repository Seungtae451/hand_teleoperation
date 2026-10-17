import json
import shutil
from pathlib import Path

import mujoco
import numpy as np
import pytest

from benchmark.paths import ROOT
from benchmark.simulation.robot_model import RobotModel
from benchmark.simulation.urdf import UrdfModel


def test_model_has_exact_official_joint_limits_axes_and_frames(robot):
    source = UrdfModel(ROOT / robot.config["urdf"])
    assert (robot.model.nq, robot.model.nv, robot.model.nu) == (20, 20, 20)
    assert len(source.links) == 28
    assert len(source.joints) == 27
    assert len(set(robot.qpos_indices)) == 20
    assert len(set(robot.dof_indices)) == 20
    np.testing.assert_array_equal(robot.limits, source.validate_order(robot.joint_names))
    for name in robot.joint_names:
        joint = source.by_name[name]
        np.testing.assert_allclose(robot.model.joint(name).axis, joint.axis, atol=1e-15)
        actuator = robot.model.actuator(f"position_{name}")
        assert actuator.trnid[0] == robot.model.joint(name).id
        np.testing.assert_array_equal(actuator.forcerange, [-joint.effort, joint.effort])
    for link in (source.base_link, robot.config["palm_link"], *robot.config["tip_links"]):
        assert robot.model.body(link).id > 0


def test_fk_matches_independent_urdf_chain_for_zero_limits_and_random_poses(robot):
    source = UrdfModel(ROOT / robot.config["urdf"])
    rng = np.random.default_rng(20261017)
    poses = [np.zeros(20), robot.limits[:, 0], robot.limits[:, 1]]
    poses.extend(rng.uniform(robot.limits[:, 0], robot.limits[:, 1], (40, 20)))
    for q in poses:
        transforms = source.forward(q, robot.joint_names)
        expected = np.array([transforms[link][:3, 3] for link in robot.config["tip_links"]])
        np.testing.assert_allclose(robot.forward_kinematics(q), expected, atol=1e-12, rtol=0)
        for link, expected_pose in transforms.items():
            body_id = robot.model.body(link).id
            np.testing.assert_allclose(
                robot.fk_data.xpos[body_id], expected_pose[:3, 3], atol=1e-12, rtol=0
            )
            np.testing.assert_allclose(
                robot.fk_data.xmat[body_id].reshape(3, 3), expected_pose[:3, :3], atol=1e-12, rtol=0
            )
        palm = transforms[robot.config["palm_link"]]
        np.testing.assert_allclose(
            robot.forward_kinematics(q, frame="palm"),
            (expected - palm[:3, 3]) @ palm[:3, :3],
            atol=1e-12,
        )


@pytest.mark.parametrize("index", range(20))
def test_every_joint_has_correct_fingertip_jacobian(robot, index):
    q = np.mean(robot.limits, axis=1)
    analytic = robot.fingertip_jacobians(q)
    dq = np.eye(20)[index] * 1e-6
    finite_difference = (robot.forward_kinematics(q + dq) - robot.forward_kinematics(q - dq)) / 2e-6
    np.testing.assert_allclose(analytic[:, :, index], finite_difference, atol=1e-9, rtol=1e-7)
    # A finger joint must affect exactly its own fingertip.
    assert np.linalg.norm(analytic[index // 4, :, index]) > 1e-4
    others = [i for i in range(5) if i != index // 4]
    np.testing.assert_allclose(analytic[others, :, index], 0, atol=1e-15)


def test_generated_bundle_is_relocatable(model_path, tmp_path):
    destination = tmp_path / "relocated"
    shutil.copytree(model_path.parent, destination)
    model = mujoco.MjModel.from_xml_path(str(destination / model_path.name))
    assert (model.nq, model.nu, model.ngeom) == (20, 20, 28)
    imported = mujoco.MjModel.from_xml_path(str(destination / "dg5f_right.normalized.urdf"))
    assert imported.nq == 20
    metadata = json.loads((destination / "dg5f_right.provenance.json").read_text())
    assert len(metadata["source_hashes"]) == 29
    assert (destination / "TESOLLO_LICENSE").is_file()


def test_canonical_reordering_does_not_assume_library_indices(robot):
    q = np.mean(robot.limits, axis=1)
    perm = np.random.default_rng(17).permutation(20)
    names = tuple(robot.joint_names[i] for i in perm)
    np.testing.assert_array_equal(robot.reorder(q[perm], names), q)
    with pytest.raises(ValueError):
        robot.reorder(q, (robot.joint_names[0],) * 20)


def test_generated_model_tampering_is_detected(model_path, tmp_path):
    destination = tmp_path / "modified"
    shutil.copytree(model_path.parent, destination)
    copied = destination / model_path.name
    copied.write_text(copied.read_text().replace('kp="12.0"', 'kp="13.0"'))
    with pytest.raises(ValueError, match="artifact was changed"):
        RobotModel(copied)


def test_missing_model_does_not_implicitly_write_to_custom_location(tmp_path):
    with pytest.raises(FileNotFoundError):
        RobotModel(Path(tmp_path) / "missing.xml")
