"""HandFrame to the original GeoRT right-hand canonical representation."""

from functools import lru_cache

import numpy as np

from benchmark.geort_support.source import canonical_function
from benchmark.tracking.coordinate_transform import world_points


@lru_cache(maxsize=1)
def _canonical():
    return canonical_function()


def canonical_points(frame):
    if frame.handedness != "right" or not frame.tracking_valid:
        raise ValueError("GeoRT adapter requires valid right-hand input")
    points = world_points(frame)
    z = points[9] - points[0]
    y_aux = points[5] - points[13]
    if not 0.02 < np.linalg.norm(z) < 0.25:
        raise ValueError("Input must use meters; no automatic scale correction")
    if (
        np.linalg.norm(z) < 1e-6
        or np.linalg.norm(y_aux) < 1e-6
        or np.linalg.norm(np.cross(z, y_aux)) < 1e-8
    ):
        raise ValueError("Degenerate GeoRT palm axes")
    for base in (1, 5, 9, 13, 17):
        if np.any(np.linalg.norm(np.diff(points[base : base + 4], axis=0), axis=1) < 1e-6):
            raise ValueError("Missing/degenerate hand bones; never synthesize keypoints")
    local = _canonical()(points.copy())
    if local.shape != (21, 3) or not np.isfinite(local).all():
        raise ValueError("GeoRT canonical conversion produced invalid points")
    return local


INPUT_CONTRACT = {
    "shape": ["N", 21, 3],
    "units": "meters",
    "handedness": "right",
    "origin": "wrist0",
    "z_axis": "wrist0 to middle MCP9",
    "y_aux": "ring MCP13 to index MCP5",
    "x_axis": "normalized y_aux cross z",
    "y_axis": "z cross x",
    "tip_indices": [4, 8, 12, 16, 20],
    "rotations": "not invented or required",
    "scale_applied": 1.0,
    "upstream_helper": "geort/mocap/manus_mocap_core.py:hand_to_canonical",
}
