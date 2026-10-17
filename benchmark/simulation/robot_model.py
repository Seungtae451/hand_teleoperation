"""One common 20-DoF model, with explicit name-to-index mappings."""

import hashlib
import json
from pathlib import Path

import mujoco
import numpy as np

from benchmark.paths import DEFAULT_MODEL
from benchmark.simulation.build_model import build_model


class RobotModel:
    def __init__(self, model_path: str | Path = DEFAULT_MODEL):
        self.path = Path(model_path).resolve()
        if not self.path.exists():
            if self.path != DEFAULT_MODEL.resolve():
                raise FileNotFoundError(self.path)
            build_model()
        self.provenance = json.loads(self.path.with_suffix(".provenance.json").read_text())
        if self.provenance["mujoco_version"] != mujoco.__version__:
            raise ValueError("MuJoCo version differs from generated model; rebuild the model")
        for relative, expected in self.provenance["artifact_hashes"].items():
            artifact = self.path.parent / relative
            if hashlib.sha256(artifact.read_bytes()).hexdigest() != expected:
                raise ValueError(f"Generated model artifact was changed; rebuild: {artifact}")
        self.config = self.provenance["config"]
        self.joint_names = tuple(self.config["joint_names"])
        self.fingers = tuple(self.config["fingers"])
        self.model = mujoco.MjModel.from_xml_path(str(self.path))
        if (self.model.nq, self.model.nv, self.model.nu) != (20, 20, 20):
            raise ValueError("Expected 20 independent, actuated hinge joints")
        self.joint_ids = np.array([self.model.joint(n).id for n in self.joint_names])
        self.qpos_indices = self.model.jnt_qposadr[self.joint_ids].copy()
        self.dof_indices = self.model.jnt_dofadr[self.joint_ids].copy()
        self.actuator_ids = np.array(
            [self.model.actuator(f"position_{n}").id for n in self.joint_names]
        )
        self.site_ids = np.array([self.model.site(f"tip_{f}").id for f in self.fingers])
        self.palm_id = self.model.body(self.config["palm_link"]).id
        self.limits = self.model.jnt_range[self.joint_ids].copy()
        self.fk_data = mujoco.MjData(self.model)

    def validate_target(self, q: np.ndarray, *, clip: bool = False) -> np.ndarray:
        q = np.asarray(q, dtype=np.float64)
        if q.shape != (20,) or not np.isfinite(q).all():
            raise ValueError("Joint target must be a finite vector of shape (20,), in radians")
        if not clip and np.any((q < self.limits[:, 0]) | (q > self.limits[:, 1])):
            raise ValueError("Joint target is outside official URDF limits")
        return np.clip(q, self.limits[:, 0], self.limits[:, 1]) if clip else q.copy()

    def positions(self, data: mujoco.MjData, *, frame: str = "world") -> np.ndarray:
        points = data.site_xpos[self.site_ids].copy()
        if frame == "palm":
            rotation = data.xmat[self.palm_id].reshape(3, 3)
            return (points - data.xpos[self.palm_id]) @ rotation
        if frame != "world":
            raise ValueError("Fingertip frame must be 'world' or 'palm'")
        return points

    def forward_kinematics(
        self, q: np.ndarray, *, frame: str = "world", enforce_limits: bool = True
    ) -> np.ndarray:
        """FK without changing dynamics. Set enforce_limits=False for measured state.

        MuJoCo constraints are soft, so actual qpos can exceed a joint bound,
        even by numerical roundoff. Never clip measured state when evaluating FK.
        """
        if enforce_limits:
            q = self.validate_target(q)
        else:
            q = np.asarray(q, dtype=float)
            if q.shape != (20,) or not np.isfinite(q).all():
                raise ValueError("FK state must be a finite vector of shape (20,)")
        self.fk_data.qpos[self.qpos_indices] = q
        mujoco.mj_forward(self.model, self.fk_data)
        return self.positions(self.fk_data, frame=frame)

    def fingertip_jacobians(self, q: np.ndarray) -> np.ndarray:
        """World-frame translational Jacobians, shape (5, 3, 20), canonical joint order."""
        self.forward_kinematics(q)
        result = np.empty((5, 3, 20))
        for i, site in enumerate(self.site_ids):
            jacobian = np.zeros((3, self.model.nv))
            mujoco.mj_jacSite(self.model, self.fk_data, jacobian, None, int(site))
            result[i] = jacobian[:, self.dof_indices]
        return result

    def reorder(self, q: np.ndarray, source_names: tuple[str, ...]) -> np.ndarray:
        """Adapter boundary for Pinocchio/other-library joint orders."""
        if len(source_names) != 20 or set(source_names) != set(self.joint_names):
            raise ValueError("Source joint names must contain each canonical joint exactly once")
        q = np.asarray(q, dtype=float)
        if q.shape != (20,):
            raise ValueError("Source target must have shape (20,)")
        return self.validate_target(q[[source_names.index(n) for n in self.joint_names]])
