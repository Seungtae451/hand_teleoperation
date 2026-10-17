"""Synthetic human skeletons for integration checks, never measured human ground truth."""

import numpy as np

from benchmark.tracking.hand_frame import HandFrame


def pose_frame(kind="open", timestamp=0.0, sequence=0):
    """Right hand in geometric palm axes. No invented Quest sensor rotations."""
    values = np.zeros(20)
    if kind == "closed":
        values[:4] = [45, 25, 35, 35]
        for base in (4, 8, 12, 16):
            values[base : base + 4] = [0, 65, 80, 50]
    elif kind == "pinch":
        values[:4] = [50, 35, 30, 15]
        values[4:8] = [5, 55, 70, 35]
    elif kind != "open":
        raise ValueError("Unknown synthetic human pose")
    radians = np.deg2rad(values)
    points = np.zeros((21, 3))
    points[1] = [0, 0.028, 0.025]
    opposition, elevation, mcp, ip = radians[:4]
    direction = np.array(
        [
            np.sin(elevation),
            np.cos(elevation) * np.cos(opposition),
            np.cos(elevation) * np.sin(opposition),
        ]
    )
    points[2] = points[1] + 0.035 * direction
    palmar = np.array([1.0, 0, 0])
    axis = np.cross(direction, palmar)
    axis /= np.linalg.norm(axis)
    from benchmark.simulation.urdf import axis_rotation

    direction = axis_rotation(axis, mcp) @ direction
    points[3] = points[2] + 0.028 * direction
    direction = axis_rotation(axis, ip) @ direction
    points[4] = points[3] + 0.022 * direction
    for finger, base in enumerate((5, 9, 13, 17)):
        points[base] = [0, [0.03, 0, -0.025, -0.046][finger], 0.075]
        spread, flex, pip, dip = radians[4 + 4 * finger : 8 + 4 * finger]
        for part, (angle, length) in enumerate(
            zip((flex, flex + pip, flex + pip + dip), (0.042, 0.026, 0.02))
        ):
            direction = [
                np.sin(angle) * np.cos(spread),
                np.sin(spread),
                np.cos(angle) * np.cos(spread),
            ]
            points[base + part + 1] = points[base + part] + length * np.array(direction)
    return HandFrame(
        timestamp,
        "right",
        points,
        np.zeros(3),
        np.array([0.0, 0, 0, 1]),
        True,
        coordinate_frame="world_rh",
        metadata={
            "session_id": "synthetic",
            "sequence": sequence,
            "reference_epoch": 0,
            "source": "synthetic_geometry",
        },
    )
