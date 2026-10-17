"""Synthetic joint commands for simulator verification, not human retargeting."""

import numpy as np


def demo_target(time: float, duration: float) -> np.ndarray:
    # Smooth, conservative free-motion pose; all 20 joints have nonzero excursion.
    amplitude = np.array(
        [
            0.25,
            -0.55,
            0.4,
            0.45,
            -0.12,
            0.5,
            0.4,
            0.45,
            0.12,
            0.5,
            0.4,
            0.45,
            0.15,
            0.5,
            0.4,
            0.45,
            0.2,
            0.2,
            0.4,
            0.45,
        ]
    )
    return amplitude * (0.5 - 0.5 * np.cos(2 * np.pi * time / duration))
