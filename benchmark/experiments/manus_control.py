"""Shared Phase 4 controller: retargeting target, rate-limited command, and actual state."""

import numpy as np

from benchmark.retargeting.manus import ManusRetargeter
from benchmark.simulation.mujoco_runner import MujocoRunner


class ManusController:
    def __init__(self, robot, config, *, timeout=0.25):
        self.runner = MujocoRunner(robot)
        self.retargeter = ManusRetargeter(robot, config)
        self.timeout = timeout
        speed = float(self.retargeter.config["maximum_command_speed_rad_s"])
        if not np.isfinite(speed) or speed <= 0 or speed > np.pi:
            raise ValueError("Command speed must be positive and <= URDF pi rad/s")
        self.max_speed = speed
        self.target = np.zeros(20)
        self.command = np.zeros(20)
        self.result = None
        self.status = "WAITING"
        self.input_age = None
        self.last_key = None

    def tick(self, frame, input_time, steps=10, *, enabled=True):
        """input_time is current receiver time (live) or recording time (offline)."""
        self.input_age = None if frame is None else input_time - frame.timestamp
        valid = (
            enabled
            and frame is not None
            and frame.tracking_valid
            and frame.handedness == "right"
            and 0 <= self.input_age < self.timeout
        )
        rejection = None
        if valid:
            key = (
                frame.metadata.get("session_id"),
                frame.metadata.get("reference_epoch"),
                frame.metadata.get("sequence"),
                frame.timestamp,
            )
            if key != self.last_key:
                if self.last_key and key[:2] != self.last_key[:2]:
                    self.retargeter.reset()
                try:
                    self.result = self.retargeter.retarget(frame)
                    self.target = self.result.q_target.copy()
                    self.last_key = key
                except ValueError as exc:
                    valid, rejection = False, str(exc)
        if valid:
            self.status = "TRACKING"
            dt = steps * self.runner.model.opt.timestep
            self.command += np.clip(
                self.target - self.command, -self.max_speed * dt, self.max_speed * dt
            )
        else:
            # Stop progressing toward the old target immediately; hold last applied command.
            self.status = "DISABLED" if not enabled else "HOLD_TRACKING_LOST"
            if rejection:
                self.status = "HOLD_INPUT_REJECTED"
            self.target = self.command.copy()
            self.last_key = None
        self.runner.set_target(self.command)
        sample = self.runner.step(steps)
        return {
            "control_status": self.status,
            "input_age_s": self.input_age,
            "rejection_reason": rejection,
            "retarget_q_target": self.target.tolist(),
            "retarget_metadata": self.result.metadata if valid and self.result else None,
            "simulation": sample.to_dict(),
        }
