import numpy as np
import pytest

from benchmark.simulation.mujoco_runner import MujocoRunner


@pytest.mark.parametrize("index", range(20))
def test_each_joint_is_actuated_and_converges_without_qpos_teleport(robot, index):
    runner = MujocoRunner(robot)
    target = np.zeros(20)
    lower, upper = robot.limits[index]
    target[index] = -0.15 if upper <= 0 else min(0.15, upper * 0.5)
    runner.set_target(target)
    np.testing.assert_array_equal(runner.data.qpos[robot.qpos_indices], np.zeros(20))
    first = runner.step()
    assert first.q_actual[index] != target[index]
    settled = runner.step(999)
    np.testing.assert_allclose(settled.q_actual, target, atol=3e-5, rtol=0)
    assert settled.time == pytest.approx(2.0)
    np.testing.assert_allclose(
        settled.tips_actual_world,
        robot.forward_kinematics(settled.q_actual, enforce_limits=False),
        atol=1e-12,
    )
    assert np.all(np.abs(runner.data.actuator_force) <= 7.5 + 1e-12)


def test_simultaneous_motion_reset_and_fk_isolation(robot):
    runner = MujocoRunner(robot)
    target = 0.2 * np.mean(robot.limits, axis=1)
    runner.set_target(target)
    settled = runner.step(1000)
    np.testing.assert_allclose(settled.q_actual, target, atol=3e-5, rtol=0)
    state = runner.data.qpos.copy()
    robot.forward_kinematics(np.zeros(20))
    np.testing.assert_array_equal(runner.data.qpos, state)
    runner.reset()
    assert runner.data.time == 0
    np.testing.assert_array_equal(runner.data.qpos, np.zeros(20))
    np.testing.assert_array_equal(runner.data.qvel, np.zeros(20))
    runner.set_target(target)
    np.testing.assert_array_equal(runner.step(1000).q_actual, settled.q_actual)


@pytest.mark.parametrize(
    "invalid", [np.zeros(19), np.zeros((20, 1)), [np.nan] * 20, [np.inf] * 20, [-np.inf] * 20]
)
def test_invalid_targets_are_rejected_atomically(robot, invalid):
    runner = MujocoRunner(robot)
    before = runner.data.ctrl.copy()
    with pytest.raises(ValueError):
        runner.set_target(invalid, clip=True)
    np.testing.assert_array_equal(runner.data.ctrl, before)
    np.testing.assert_array_equal(runner.q_target, np.zeros(20))


def test_limits_clipping_retains_raw_command_and_separates_actual_state(robot):
    runner = MujocoRunner(robot)
    raw = robot.limits[:, 1] + 10
    with pytest.raises(ValueError):
        runner.set_target(raw)
    runner.set_target(raw, clip=True)
    sample = runner.sample()
    np.testing.assert_array_equal(sample.q_target, raw)
    np.testing.assert_array_equal(sample.q_command, robot.limits[:, 1])
    np.testing.assert_array_equal(sample.q_actual, np.zeros(20))
    assert sample.clipped.all()
    for target in (robot.limits[:, 0], robot.limits[:, 1]):
        runner.reset(target)
        np.testing.assert_allclose(runner.step(100).q_actual, target, atol=1e-10)


@pytest.mark.parametrize("count", [0, -1, 1.5, True])
def test_invalid_step_counts_rejected(robot, count):
    with pytest.raises(ValueError):
        MujocoRunner(robot).step(count)
