"""Explicit experimental input/output bounds; original GeoRT weights/loss unchanged."""

import json
from pathlib import Path
from time import perf_counter

import numpy as np

from benchmark.geort_support.assets import validate_config
from benchmark.geort_support.input import canonical_points
from benchmark.geort_support.source import enable_upstream
from benchmark.retargeting.base import BaseRetargeter, RetargetingResult

RESTRICTED_INDICES = (6, 7, 10, 11, 14, 15, 18, 19)


def restricted_bounds(full):
    bounds = np.array(full, dtype=float, copy=True)
    bounds[list(RESTRICTED_INDICES), 0] = 0
    return bounds


def normalization_affine(source, destination):
    """Map source-normalized [-1,1] to destination normalization for SAME radians."""
    source, destination = np.asarray(source), np.asarray(destination)
    width = destination[:, 1] - destination[:, 0]
    scale = (source[:, 1] - source[:, 0]) / width
    bias = (source.sum(axis=1) - destination.sum(axis=1)) / width
    return scale, bias


def load_range_model(robot, checkpoint, config_path):
    config = json.loads(Path(config_path).read_text())
    full = np.array(robot.limits)
    expected = restricted_bounds(full)
    bounds = np.array([config["joint"]["lower"], config["joint"]["upper"]]).T
    if not np.allclose(bounds, expected, atol=1e-7):
        raise ValueError("Expected explicit 0..90-degree nonthumb distal experiment bounds")
    # Validate remaining robot metadata using an in-memory official-limit copy.
    validation = json.loads(json.dumps(config))
    validation["joint"] = {"lower": full[:, 0].tolist(), "upper": full[:, 1].tolist()}
    validate_config(validation)
    enable_upstream()
    from geort.export import GeoRTRetargetingModel

    return GeoRTRetargetingModel(str(checkpoint), str(config_path)), config


class RangeRetargeter(BaseRetargeter):
    """Explicit experimental retargeter, not substituted into original baseline."""

    def __init__(self, robot, *, checkpoint, config_path):
        self.robot = robot
        self.vendor, self.config = load_range_model(robot, checkpoint, config_path)
        self.reset()

    def reset(self):
        self.last_timestamp = None
        self.last_session = None

    def retarget(self, frame):
        import torch

        start = perf_counter()
        session = frame.metadata.get("session_id")
        if (
            self.last_session == session
            and self.last_timestamp is not None
            and frame.timestamp < self.last_timestamp
        ):
            raise ValueError("Timestamp regression; reset before replay")
        points = canonical_points(frame)
        with torch.inference_mode():
            raw = np.asarray(self.vendor.forward(points), dtype=float)
        limits = restricted_bounds(self.robot.limits)
        if np.any(raw < limits[:, 0] - 1e-6) or np.any(raw > limits[:, 1] + 1e-6):
            raise ValueError("Network output exceeded declared experimental range")
        target = self.robot.validate_target(raw, clip=True)
        self.last_timestamp, self.last_session = frame.timestamp, session
        return RetargetingResult(
            target,
            {
                "method": "geort_range_experiment",
                "q_vendor_raw": raw.tolist(),
                "joint_limit_clipped": (raw != target).tolist(),
                "total_s": perf_counter() - start,
                "solver_status": "checkpoint_inference",
                "experimental_range": (
                    "nonthumb joint 3/4: 0..90 deg; original robot limits unchanged"
                ),
            },
        )
