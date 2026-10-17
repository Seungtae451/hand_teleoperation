"""Actuator-driven simulation; targets are never written directly to qpos by step()."""

from dataclasses import asdict, dataclass

import mujoco
import numpy as np

from benchmark.simulation.robot_model import RobotModel


@dataclass
class SimulationSample:
    time: float
    q_target: np.ndarray
    q_command: np.ndarray
    q_actual: np.ndarray
    q_velocity: np.ndarray
    tips_command_world: np.ndarray
    tips_actual_world: np.ndarray
    clipped: np.ndarray
    contact_count: int

    def to_dict(self) -> dict:
        return {
            key: value.tolist() if isinstance(value, np.ndarray) else value
            for key, value in asdict(self).items()
        }


class MujocoRunner:
    def __init__(self, robot: RobotModel | None = None):
        self.robot = robot if robot is not None else RobotModel()
        self.model = self.robot.model
        self.data = mujoco.MjData(self.model)
        self.reset()

    def reset(self, q: np.ndarray | None = None) -> None:
        q = np.zeros(20) if q is None else self.robot.validate_target(q)
        mujoco.mj_resetData(self.model, self.data)
        self.data.qpos[self.robot.qpos_indices] = q
        self.q_target = q.copy()
        self.q_command = q.copy()
        self.data.ctrl[self.robot.actuator_ids] = q
        mujoco.mj_forward(self.model, self.data)

    def set_target(self, q: np.ndarray, *, clip: bool = False) -> np.ndarray:
        command = self.robot.validate_target(q, clip=clip)
        self.q_target = np.asarray(q, dtype=float).copy()
        self.q_command = command
        self.data.ctrl[self.robot.actuator_ids] = command
        return command.copy()

    def step(self, n_steps: int = 1) -> SimulationSample:
        if isinstance(n_steps, bool) or not isinstance(n_steps, int) or n_steps < 1:
            raise ValueError("n_steps must be a positive integer")
        mujoco.mj_step(self.model, self.data, nstep=n_steps)
        # mj_step integrates qpos after computing positions. Refresh Cartesian state
        # so recorded fingertip positions and q_actual describe the same instant.
        mujoco.mj_forward(self.model, self.data)
        if not np.isfinite(self.data.qpos).all() or any(w.number for w in self.data.warning):
            raise RuntimeError("MuJoCo reported an unstable simulation or a warning")
        return self.sample()

    def sample(self) -> SimulationSample:
        return SimulationSample(
            float(self.data.time),
            self.q_target.copy(),
            self.q_command.copy(),
            self.data.qpos[self.robot.qpos_indices].copy(),
            self.data.qvel[self.robot.dof_indices].copy(),
            self.robot.forward_kinematics(self.q_command),
            self.robot.positions(self.data),
            self.q_target != self.q_command,
            int(self.data.ncon),
        )
