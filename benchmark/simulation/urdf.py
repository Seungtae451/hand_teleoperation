"""Read the actual URDF and provide an independent NumPy FK reference."""

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import numpy as np


def vector(text: str) -> np.ndarray:
    return np.array([float(x) for x in text.split()], dtype=np.float64)


def axis_rotation(axis: np.ndarray, angle: float) -> np.ndarray:
    axis = axis / np.linalg.norm(axis)
    x, y, z = axis
    cross = np.array([[0, -z, y], [z, 0, -x], [-y, x, 0]])
    return np.eye(3) + np.sin(angle) * cross + (1 - np.cos(angle)) * (cross @ cross)


@dataclass(frozen=True)
class Joint:
    name: str
    kind: str
    parent: str
    child: str
    xyz: np.ndarray
    rpy: np.ndarray
    axis: np.ndarray
    lower: float | None
    upper: float | None
    effort: float | None
    velocity: float | None


class UrdfModel:
    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        self.root = ET.parse(self.path).getroot()
        self.links = tuple(link.attrib["name"] for link in self.root.findall("link"))
        if self.root.findall(".//mimic"):
            raise ValueError("Mimic joints require an explicit coupling adapter")
        self.joints = []
        for node in self.root.findall("joint"):
            kind = node.attrib["type"]
            if kind not in ("fixed", "revolute"):
                raise ValueError(f"Unsupported joint type: {kind}")
            origin = node.find("origin")
            attrs = {} if origin is None else origin.attrib
            axis = node.find("axis")
            limit = node.find("limit")
            limits = {} if limit is None else limit.attrib
            self.joints.append(
                Joint(
                    node.attrib["name"],
                    kind,
                    node.find("parent").attrib["link"],
                    node.find("child").attrib["link"],
                    vector(attrs.get("xyz", "0 0 0")),
                    vector(attrs.get("rpy", "0 0 0")),
                    vector("1 0 0" if axis is None else axis.attrib["xyz"]),
                    *(
                        float(limits[k]) if k in limits else None
                        for k in ("lower", "upper", "effort", "velocity")
                    ),
                )
            )
        self.by_name = {joint.name: joint for joint in self.joints}
        children = {joint.child for joint in self.joints}
        roots = set(self.links) - children
        if len(roots) != 1:
            raise ValueError(f"Expected one URDF root link, found {roots}")
        self.base_link = roots.pop()

    def validate_order(self, names: tuple[str, ...]) -> np.ndarray:
        actual = {j.name for j in self.joints if j.kind == "revolute"}
        if len(names) != 20 or len(set(names)) != 20 or actual != set(names):
            raise ValueError("Configured 20-joint order does not match URDF revolute joints")
        limits = np.array(
            [[self.by_name[n].lower, self.by_name[n].upper] for n in names], dtype=float
        )
        if not np.isfinite(limits).all() or np.any(limits[:, 0] >= limits[:, 1]):
            raise ValueError("URDF limits must be finite and ordered")
        return limits

    def forward(self, q: np.ndarray, names: tuple[str, ...]) -> dict[str, np.ndarray]:
        """Root-relative link transforms using URDF Rz(yaw) Ry(pitch) Rx(roll)."""
        q = np.asarray(q, dtype=float)
        if q.shape != (len(names),) or not np.isfinite(q).all():
            raise ValueError("Invalid FK joint vector")
        angles = dict(zip(names, q))
        transforms = {self.base_link: np.eye(4)}
        pending = list(self.joints)
        while pending:
            ready = [j for j in pending if j.parent in transforms]
            if not ready:
                raise ValueError("URDF is disconnected or cyclic")
            for joint in ready:
                r, p, y = joint.rpy
                local = np.eye(4)
                local[:3, :3] = (
                    axis_rotation(np.array([0, 0, 1]), y)
                    @ axis_rotation(np.array([0, 1, 0]), p)
                    @ axis_rotation(np.array([1, 0, 0]), r)
                )
                local[:3, 3] = joint.xyz
                motion = np.eye(4)
                if joint.kind == "revolute":
                    motion[:3, :3] = axis_rotation(joint.axis, angles[joint.name])
                transforms[joint.child] = transforms[joint.parent] @ local @ motion
                pending.remove(joint)
        return transforms
