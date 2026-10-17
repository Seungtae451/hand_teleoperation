"""Common tracking contract verified against the HTS streamed 21-point layout."""

from dataclasses import dataclass, field

import numpy as np

# Source HandLandmarkStreamer.cs _streamedJoints, not the full OpenXR skeleton.
HTS_OPENXR_INDICES = (1, 2, 3, 4, 5, 7, 8, 9, 10, 12, 13, 14, 15, 17, 18, 19, 20, 22, 23, 24, 25)
FINGERTIP_INDICES = (4, 8, 12, 16, 20)


@dataclass
class HandFrame:
    """Meters, seconds, xyzw quaternions. Coordinate conversion must be explicit.

    Positions are in coordinate_frame. wrist_position / wrist_rotation describe
    the wrist in the source world. HTS provides no per-joint rotations or explicit
    invalid packets: leave rotations=None and derive validity from packet age in
    the future receiver. Source clocks must not be treated as synchronized clocks.
    """

    timestamp: float
    handedness: str
    joint_positions: np.ndarray
    wrist_position: np.ndarray
    wrist_rotation: np.ndarray
    tracking_valid: bool
    coordinate_frame: str = "unity_wrist_lh"
    timestamp_domain: str = "receiver_monotonic"
    joint_rotations: np.ndarray | None = None
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.handedness not in ("left", "right") or not np.isfinite(self.timestamp):
            raise ValueError("Invalid handedness or timestamp")
        if self.coordinate_frame not in ("unity_wrist_lh", "wrist_rh", "palm_rh", "world_rh"):
            raise ValueError("Unknown coordinate frame")
        for name, shape in (
            ("joint_positions", (21, 3)),
            ("wrist_position", (3,)),
            ("wrist_rotation", (4,)),
        ):
            value = np.asarray(getattr(self, name), dtype=float).copy()
            if value.shape != shape or not np.isfinite(value).all():
                raise ValueError(f"{name} must be finite with shape {shape}")
            setattr(self, name, value)
        if not np.isclose(np.linalg.norm(self.wrist_rotation), 1.0, atol=1e-5):
            raise ValueError("wrist_rotation must be a unit xyzw quaternion")
        if self.joint_rotations is not None:
            self.joint_rotations = np.asarray(self.joint_rotations, dtype=float).copy()
            if (
                self.joint_rotations.shape != (21, 4)
                or not np.isfinite(self.joint_rotations).all()
                or not np.allclose(np.linalg.norm(self.joint_rotations, axis=1), 1, atol=1e-5)
            ):
                raise ValueError("joint_rotations must be (21, 4) unit xyzw quaternions")


def select_hts_joints(openxr_positions: np.ndarray) -> np.ndarray:
    """Select the actual transmitted 21 points from a full OpenXR-indexed array."""
    points = np.asarray(openxr_positions, dtype=float)
    if points.ndim != 2 or points.shape[1] != 3 or points.shape[0] < 26:
        raise ValueError("Expected at least 26 OpenXR-indexed 3D points")
    if not np.isfinite(points).all():
        raise ValueError("OpenXR positions must be finite")
    return points[list(HTS_OPENXR_INDICES)].copy()
