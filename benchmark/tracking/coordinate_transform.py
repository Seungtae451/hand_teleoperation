"""Explicit right-handed frame transforms; no Unity reflection for WebXR input."""

import numpy as np

from benchmark.tracking.hand_frame import HandFrame


def quaternion_matrix(quaternion):
    q = np.asarray(quaternion, dtype=float)
    if (
        q.shape != (4,)
        or not np.isfinite(q).all()
        or not np.isclose(np.linalg.norm(q), 1, atol=1e-5)
    ):
        raise ValueError("Expected a finite unit xyzw quaternion")
    x, y, z, w = q / np.linalg.norm(q)
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


def matrix_quaternion(rotation):
    r = np.asarray(rotation, dtype=float)
    if (
        r.shape != (3, 3)
        or not np.isfinite(r).all()
        or not np.allclose(r.T @ r, np.eye(3), atol=1e-6)
        or not np.isclose(np.linalg.det(r), 1, atol=1e-6)
    ):
        raise ValueError("Expected a proper 3D rotation")
    # Symmetric eigenproblem remains stable at rotations near pi.
    k = (
        np.array(
            [
                [
                    r[0, 0] - r[1, 1] - r[2, 2],
                    r[0, 1] + r[1, 0],
                    r[0, 2] + r[2, 0],
                    r[2, 1] - r[1, 2],
                ],
                [
                    r[0, 1] + r[1, 0],
                    r[1, 1] - r[0, 0] - r[2, 2],
                    r[1, 2] + r[2, 1],
                    r[0, 2] - r[2, 0],
                ],
                [
                    r[0, 2] + r[2, 0],
                    r[1, 2] + r[2, 1],
                    r[2, 2] - r[0, 0] - r[1, 1],
                    r[1, 0] - r[0, 1],
                ],
                [r[2, 1] - r[1, 2], r[0, 2] - r[2, 0], r[1, 0] - r[0, 1], np.trace(r)],
            ]
        )
        / 3
    )
    _, vectors = np.linalg.eigh(k)
    q = vectors[:, -1]
    return q if q[3] >= 0 else -q


def world_points(frame: HandFrame):
    if frame.coordinate_frame == "world_rh":
        return frame.joint_positions.copy()
    if frame.coordinate_frame == "wrist_rh":
        rotation = quaternion_matrix(frame.wrist_rotation)
    elif frame.coordinate_frame == "palm_rh":
        rotation = quaternion_matrix(frame.metadata["palm_to_world_xyzw"])
    else:
        raise ValueError("Unity LH input needs a separate explicit basis conversion")
    return frame.joint_positions @ rotation.T + frame.wrist_position


def transform_world_frame(frame: HandFrame, target: str = "wrist_rh") -> HandFrame:
    """Express WebXR world RH points and joint orientations in wrist or geometric palm.

    Palm origin=wrist; +Z=wrist->middle MCP; +Y=pinky MCP->index MCP,
    orthogonalized against Z; +X=Y cross Z. This isn't a calibrated robot palm.
    Wrist pose fields always retain their original source-world meaning.
    """
    if frame.coordinate_frame != "world_rh":
        raise ValueError("Expected a source world_rh HandFrame")
    metadata = dict(frame.metadata)
    if target == "world_rh":
        rotation = np.eye(3)
        origin = np.zeros(3)
    elif target == "wrist_rh":
        rotation = quaternion_matrix(frame.wrist_rotation)
        origin = frame.wrist_position
    elif target == "palm_rh":
        points = frame.joint_positions
        z = points[9] - points[0]
        if np.linalg.norm(z) < 1e-5:
            raise ValueError("Degenerate wrist-to-middle palm axis")
        z /= np.linalg.norm(z)
        y = points[5] - points[17]
        y -= np.dot(y, z) * z
        if np.linalg.norm(y) < 1e-5:
            raise ValueError("Degenerate index-to-pinky palm axis")
        y /= np.linalg.norm(y)
        rotation = np.column_stack((np.cross(y, z), y, z))
        origin = frame.wrist_position
        metadata.update(
            palm_to_world_xyzw=matrix_quaternion(rotation).tolist(),
            palm_origin="wrist",
            palm_definition="z:middle_mcp,y:pinky_to_index,x:y_cross_z",
        )
    else:
        raise ValueError("Target must be wrist_rh, palm_rh, or world_rh")
    rotations = None
    if frame.joint_rotations is not None:
        rotations = np.array(
            [matrix_quaternion(rotation.T @ quaternion_matrix(q)) for q in frame.joint_rotations]
        )
    return HandFrame(
        frame.timestamp,
        frame.handedness,
        (frame.joint_positions - origin) @ rotation,
        frame.wrist_position,
        frame.wrist_rotation,
        frame.tracking_valid,
        coordinate_frame=target,
        timestamp_domain=frame.timestamp_domain,
        joint_rotations=rotations,
        metadata=metadata,
    )
