"""Documented geometric Quest-to-MANUS-like features, not actual MANUS sensor values."""

import numpy as np

from benchmark.tracking.coordinate_transform import world_points

FEATURE_NAMES = (
    "thumb_opposition",
    "thumb_palmar_elevation",
    "thumb_mcp_bend",
    "thumb_ip_bend",
    *(
        f"{finger}_{angle}"
        for finger in ("index", "middle", "ring", "pinky")
        for angle in ("spread", "mcp_flex", "pip_flex", "dip_flex")
    ),
)


def unit(vector):
    norm = np.linalg.norm(vector)
    if not np.isfinite(norm) or norm < 1e-6:
        raise ValueError("Degenerate human hand bone or palm axis")
    return vector / norm


def bend(before, after):
    return np.arccos(np.clip(unit(before) @ unit(after), -1, 1))


def geometric_features(frame):
    """20 degree features. Palm Z=distal, Y=radial, X=Y cross Z.

    Right hand palmar flexion is +X; left hand uses -X. PIP/DIP use
    unsigned inter-bone bend (hyperextension is not distinguished here).
    Thumb roles are a project convention, not a certified MANUS calibration.
    """
    if not frame.tracking_valid:
        raise ValueError("Tracking-invalid frames must not enter retargeting")
    points = world_points(frame)
    z = unit(points[9] - points[0])
    y = points[5] - points[17]
    y = unit(y - (y @ z) * z)
    x = np.cross(y, z) * (1 if frame.handedness == "right" else -1)
    thumb = unit(points[2] - points[1])
    features = [
        np.arctan2(thumb @ z, thumb @ y),
        np.arctan2(thumb @ x, np.hypot(thumb @ y, thumb @ z)),
        bend(points[2] - points[1], points[3] - points[2]),
        bend(points[3] - points[2], points[4] - points[3]),
    ]
    for base in (5, 9, 13, 17):
        proximal = points[base + 1] - points[base]
        middle = points[base + 2] - points[base + 1]
        distal = points[base + 3] - points[base + 2]
        direction = unit(proximal)
        features.extend(
            [
                np.arctan2(direction @ y, np.hypot(direction @ x, direction @ z)),
                np.arctan2(direction @ x, direction @ z),
                bend(proximal, middle),
                bend(middle, distal),
            ]
        )
    result = np.rad2deg(features)
    if not np.isfinite(result).all():
        raise ValueError("Nonfinite Quest geometric features")
    return result


def manus_ergonomics_proxy(features, convention="thumb_axes_v2"):
    """Convert geometric angles to MANUS input slots, without fitting vendor parameters.

    v2: spread is out-of-palm elevation E; stretch is the YZ angle from +Z
    toward +Y (atan2(uY, uZ)), rather than opposition A measured from +Y.
    The quarter-turn is a geometric basis change, not vendor offset cancellation.
    This remains a Quest proxy, not calibrated MANUS sensor output.
    """
    result = np.asarray(features, dtype=float).copy()
    if result.shape != (20,) or not np.isfinite(result).all():
        raise ValueError("Expected twenty finite geometric degree features")
    if convention == "legacy_v1":
        return result
    if convention != "thumb_axes_v2":
        raise ValueError(f"Unknown Quest-to-MANUS input convention: {convention}")
    opposition, elevation = result[:2]
    angle = np.radians(opposition)
    result[0] = elevation
    result[1] = np.degrees(np.arctan2(np.cos(angle), np.sin(angle)))
    return result
