"""DG-5F model/input adapter around the pinned, unmodified AnyDex optimizer."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from time import perf_counter

import numpy as np

from benchmark.paths import ROOT
from benchmark.retargeting.base import BaseRetargeter, RetargetingResult
from benchmark.retargeting.quest_ergonomics import geometric_features
from benchmark.tracking.coordinate_transform import world_points

REPOSITORY = ROOT / "external/AnyDexRetarget"
COMMIT = "ee68a0234ccdf8a23b98527fd1ee2c6258278cd1"


def upstream():
    """Import directly from the pinned checkout; never monkeypatch vendor internals."""
    if (
        subprocess.check_output(
            ["git", "-C", str(REPOSITORY), "rev-parse", "HEAD"], text=True
        ).strip()
        != COMMIT
    ):
        raise ValueError("AnyDex commit changed; review before running")
    if subprocess.check_output(
        ["git", "-C", str(REPOSITORY), "status", "--porcelain", "--untracked-files=no"],
        text=True,
    ).strip():
        raise ValueError("AnyDex tracked source was modified; review before running")
    if str(REPOSITORY) not in sys.path:
        sys.path.insert(0, str(REPOSITORY))
    from anydexretarget import Retargeter

    if not Path(sys.modules[Retargeter.__module__].__file__).resolve().is_relative_to(REPOSITORY):
        raise ValueError("A different AnyDex installation is already imported")
    return Retargeter


def model_config(robot):
    """Use upstream algorithm defaults; supply only verified robot model bindings."""
    return {
        "optimizer": {"type": "AdaptiveOptimizerAnalytical", "hand_side": "right"},
        "robot": {
            "type": "tesollo_dg5f",
            "urdf_path": str(ROOT / robot.config["urdf"]),
            "origin_link": robot.config["palm_link"],
            "tip_links": list(robot.config["tip_links"]),
            # Thumb CMC and non-thumb MCP flexion-axis origins in the actual URDF.
            "link1_names": ["rl_dg_1_1", *[f"rl_dg_{i}_2" for i in range(2, 6)]],
            "link3_names": [f"rl_dg_{i}_3" for i in range(1, 6)],
            "link4_names": [f"rl_dg_{i}_4" for i in range(1, 6)],
            "tip_offsets": [[0.0, 0, 0]] * 5,
            "link3_offsets": [[0.0, 0, 0]] * 5,
            "link4_offsets": [[0.0, 0, 0]] * 5,
            "num_fingers": 5,
            "neutral_qpos": None,
        },
        "retarget": {},
    }


class AnyDexRetargeter(BaseRetargeter):
    def __init__(self, robot):
        if robot.config["handedness"] != "right":
            raise NotImplementedError("Only the verified right DG-5F is supported")
        self.robot = robot
        self.config = model_config(robot)
        self.vendor = upstream().from_config(json.loads(json.dumps(self.config)), hand_side="right")
        self.names = tuple(self.vendor.optimizer.robot.dof_joint_names)
        if len(self.names) != 20 or set(self.names) != set(robot.joint_names):
            raise ValueError("Pinocchio joint names do not match the common 20-DoF contract")
        self.indices = [self.names.index(name) for name in robot.joint_names]
        self.provenance = {
            "repository": "https://github.com/qqsq12321/AnyDexRetarget",
            "commit": COMMIT,
            "algorithm": "AdaptiveOptimizerAnalytical",
            "parameters": "unchanged upstream code defaults; model bindings only",
            "output_filter": "upstream Retargeter default LPFilter(alpha=0.2) enabled",
            "source_sha256": {
                str(p.relative_to(REPOSITORY)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in (REPOSITORY / "anydexretarget").rglob("*.py")
            },
        }
        self.reset()

    def reset(self):
        self.vendor.reset()
        self.last_timestamp = None
        self.last_session = None

    def retarget(self, hand_frame):
        start = perf_counter()
        if hand_frame.handedness != "right" or not hand_frame.tracking_valid:
            raise ValueError("AnyDex requires valid right-hand input")
        session = hand_frame.metadata.get("session_id")
        if (
            session == self.last_session
            and self.last_timestamp is not None
            and hand_frame.timestamp < self.last_timestamp
        ):
            raise ValueError("Retargeting timestamps regressed; reset before replay")
        # Geometry validation only. No calibration or gain transformation.
        geometric_features(hand_frame)
        points = world_points(hand_frame)
        preprocess_s = perf_counter() - start
        solve_start = perf_counter()
        q, info = self.vendor.retarget_verbose(points)
        solve_s = perf_counter() - solve_start
        raw = np.asarray(q, dtype=float)[self.indices]
        unfiltered = np.asarray(info["qpos_unfiltered"], dtype=float)[self.indices]
        target = self.robot.validate_target(raw, clip=True)
        self.last_timestamp, self.last_session = hand_frame.timestamp, session
        code = int(self.vendor.optimizer.opt.last_optimize_result())
        return RetargetingResult(
            target,
            {
                "method": "anydex_adaptive_defaults",
                "solver_status": (
                    "evaluation_budget_reached"
                    if code == 5
                    else "time_budget_reached"
                    if code == 6
                    else "success"
                    if code > 0
                    else "vendor_fallback_or_failure"
                ),
                "nlopt_result": code,
                "nlopt_evaluations": self.vendor.optimizer.opt.get_numevals(),
                "optimizer_q_unfiltered": unfiltered.tolist(),
                "q_vendor_raw": raw.tolist(),
                "joint_limit_clipped": (raw != target).tolist(),
                "objective_cost": float(info["cost"]),
                "pinch_alphas": np.asarray(info["pinch_alphas"]).tolist(),
                "optimizer_input_m": info["mediapipe_kp"].tolist(),
                "preprocess_s": preprocess_s,
                "mapping_s": solve_s,
                "total_s": perf_counter() - start,
            },
        )


def register_anydex():
    from benchmark.retargeting.registry import register

    register("anydex", AnyDexRetargeter)
