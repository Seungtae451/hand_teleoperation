"""Method A: explicit Quest geometry adapter followed by exact official MANUS mapping."""

import json
from pathlib import Path
from time import perf_counter

import numpy as np

from benchmark.paths import ROOT
from benchmark.retargeting.base import BaseRetargeter, RetargetingResult
from benchmark.retargeting.manus_vendor import OfficialManusMapping
from benchmark.retargeting.quest_ergonomics import FEATURE_NAMES, geometric_features

DEFAULT_MANUS_CONFIG = ROOT / "configs/manus_quest.json"


class ManusRetargeter(BaseRetargeter):
    def __init__(self, robot, config=DEFAULT_MANUS_CONFIG):
        self.robot = robot
        self.config = (
            json.loads(Path(config).read_text())
            if not isinstance(config, dict)
            else json.loads(json.dumps(config))
        )
        forbidden = {"feature_reference_deg", "feature_gain", "ergonomics_bias_deg"}
        if forbidden.intersection(self.config):
            raise ValueError("Project calibration/gain corrections are forbidden in this baseline")
        if self.config["handedness"] != robot.config["handedness"]:
            raise ValueError("MANUS adapter hand side must match the simulated robot")
        if robot.config["handedness"] != "right":
            raise NotImplementedError("Only the validated right DG-5F model is supported")
        self.vendor = OfficialManusMapping()
        self.reset()

    def reset(self):
        self.last_timestamp = None
        self.last_session = None

    def retarget(self, hand_frame):
        start = perf_counter()
        if hand_frame.handedness != self.config["handedness"]:
            raise ValueError("Input hand does not match the MANUS adapter")
        session = hand_frame.metadata.get("session_id")
        if (
            session == self.last_session
            and self.last_timestamp is not None
            and hand_frame.timestamp < self.last_timestamp
        ):
            raise ValueError("Retargeting timestamps regressed; reset before replay")
        features = geometric_features(hand_frame)
        ergonomics = features.copy()
        preprocess_s = perf_counter() - start
        mapping_start = perf_counter()
        raw = np.array(self.vendor(ergonomics, hand_frame.handedness))
        target = self.robot.validate_target(raw, clip=True)
        self.last_timestamp, self.last_session = hand_frame.timestamp, session
        return RetargetingResult(
            target,
            {
                "method": "manus_style_quest_geometry",
                "solver_status": "mapped",
                "feature_names": FEATURE_NAMES,
                "features_deg": features.tolist(),
                "ergonomics_proxy_deg": ergonomics.tolist(),
                "q_vendor_raw": raw.tolist(),
                "joint_limit_clipped": (raw != target).tolist(),
                "preprocess_s": preprocess_s,
                "mapping_s": perf_counter() - mapping_start,
                "total_s": perf_counter() - start,
                "source_tracking_valid": True,
            },
        )


def register_manus():
    """Explicit installation avoids importing optional adapters as global side effects."""
    from benchmark.retargeting.registry import register

    register("manus", ManusRetargeter)
