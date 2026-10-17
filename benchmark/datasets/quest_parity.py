"""Explicit canonical-only parity adapter for pinned OOJU kitchen exports.

Empirical coordinate correction, NOT a publisher-confirmed world-pose transform.
Apply after original GeoRT canonicalization, never to live WebXR or human_alex.
No quaternion or anatomical handedness labels are changed.
"""

import numpy as np

ADAPTER_ID = "ooju_kitchen_canonical_parity_v1"
REVISION = "b5c916d89c771f4a09d5f6d6c59e1dc4f912bb61"
PROVENANCE = {
    "adapter": ADAPTER_ID,
    "dataset": "OOJU/wild-mani-kitchen",
    "revision": REVISION,
    "matrix_on_row_vectors": [[-1, 0, 0], [0, 1, 0], [0, 0, 1]],
    "space": "original GeoRT wrist-centered canonical points, meters",
    "applies_to": "both anatomical hands; right hand only used for model training",
    "basis": "User observed reversed canonical X flexion in both hands; "
    "public versus live geometric chirality diagnostics agree. "
    "Historical 1923-row export comparison shows axis permutation (z,x,y), determinant +1.",
    "publisher_exporter_verified": False,
    "limitation": "Collection/exporter code unavailable in released dataset. "
    "Exact world transform and source quaternion conversion remain unverified. "
    "This is a declared empirical parity experiment, not a certified SDK conversion.",
    "original_tracking": "Publisher-declared Quest 3 Unity hand tracking; SDK version unknown",
    "license": "Apache-2.0",
    "live_webxr_changed": False,
    "algorithm_changed": False,
    "scale_or_offset_changed": False,
}


def adapt_canonical(points, *, revision=REVISION):
    """Copy finite (...,21,3) wrist-centered points and reflect canonical X."""
    if revision != REVISION:
        raise ValueError("Adapter only verified empirically for the pinned dataset revision")
    result = np.array(points, dtype=np.float64, copy=True)
    if result.ndim < 2 or result.shape[-2:] != (21, 3):
        raise ValueError("Expected (...,21,3) canonical points")
    if not np.isfinite(result).all() or not np.allclose(result[..., 0, :], 0, atol=1e-7):
        raise ValueError("Expected finite wrist-centered canonical points")
    result[..., 0] *= -1
    return result
