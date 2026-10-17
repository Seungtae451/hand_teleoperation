"""Original GeoRT inference adapter; requires a real compatible checkpoint."""

import hashlib
import json
from pathlib import Path
from time import perf_counter

import numpy as np

from benchmark.geort_support.assets import validate_config
from benchmark.geort_support.input import INPUT_CONTRACT, canonical_points
from benchmark.geort_support.source import enable_upstream
from benchmark.retargeting.base import BaseRetargeter, RetargetingResult


class GeoRTRetargeter(BaseRetargeter):
    def __init__(self, robot, *, checkpoint, config_path):
        checkpoint, config_path = Path(checkpoint), Path(config_path)
        if not checkpoint.is_file():
            raise FileNotFoundError(
                "A trained DG-5F GeoRT checkpoint is required; no fallback model"
            )
        if robot.config["handedness"] != "right":
            raise NotImplementedError("Only right DG-5F is configured")
        self.config = json.loads(config_path.read_text())
        validate_config(self.config)
        if "joint" not in self.config:
            raise ValueError("Expected the original exported checkpoint config with joint limits")
        provenance = enable_upstream()
        import torch
        from geort.export import GeoRTRetargetingModel

        if not torch.cuda.is_available():
            raise RuntimeError("Original GeoRT inference uses CUDA; no CPU substitution is enabled")
        self.robot = robot
        self.vendor = GeoRTRetargetingModel(str(checkpoint), str(config_path))
        self.provenance = {
            **provenance,
            "checkpoint_sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
            "checkpoint_config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
            "input_contract": INPUT_CONTRACT,
            "reuse": "original GeoRTRetargetingModel.forward; no network/loss changes",
        }
        self.reset()

    def reset(self):
        self.last_timestamp = None
        self.last_session = None

    def retarget(self, hand_frame):
        start = perf_counter()
        session = hand_frame.metadata.get("session_id")
        if (
            self.last_session == session
            and self.last_timestamp is not None
            and hand_frame.timestamp < self.last_timestamp
        ):
            raise ValueError("Retargeting timestamps regressed; reset before replay")
        points = canonical_points(hand_frame)
        preprocess_s = perf_counter() - start
        import torch

        mapping_start = perf_counter()
        with torch.inference_mode():
            raw = np.asarray(self.vendor.forward(points), dtype=float)
        target = self.robot.validate_target(raw, clip=True)
        self.last_timestamp, self.last_session = hand_frame.timestamp, session
        return RetargetingResult(
            target,
            {
                "method": "geort_original_checkpoint",
                "solver_status": "checkpoint_inference",
                "q_vendor_raw": raw.tolist(),
                "joint_limit_clipped": (raw != target).tolist(),
                "preprocess_s": preprocess_s,
                "mapping_s": perf_counter() - mapping_start,
                "total_s": perf_counter() - start,
            },
        )
