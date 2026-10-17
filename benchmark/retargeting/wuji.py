"""DG-5F bindings to the unmodified, pinned Wuji adaptive optimizer."""

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

REPOSITORY = ROOT / "external/wuji-retargeting"
COMMIT = "531f6ed4250b475d2e9231f54e988fc9b1c5b4ea"


def upstream():
    revision = subprocess.check_output(
        ["git", "-C", str(REPOSITORY), "rev-parse", "HEAD"], text=True
    ).strip()
    status = subprocess.check_output(
        ["git", "-C", str(REPOSITORY), "status", "--porcelain", "--untracked-files=no"],
        text=True,
    ).strip()
    if revision != COMMIT or status:
        raise ValueError("Wuji source/commit changed; review before running")
    if str(REPOSITORY) not in sys.path:
        sys.path.insert(0, str(REPOSITORY))
    from wuji_retargeting import Retargeter

    if not Path(sys.modules[Retargeter.__module__].__file__).resolve().is_relative_to(REPOSITORY):
        raise ValueError("A different Wuji installation is already imported")
    return Retargeter


def model_config(robot):
    """Configure robot naming/path only; leave all algorithm defaults unchanged."""
    return {
        "optimizer": {
            "type": "AdaptiveOptimizerAnalytical",
            "hand_side": "right",
            "urdf_path": str(ROOT / robot.config["urdf"]),
            "link_naming": {
                "prefix": "",
                "palm": robot.config["palm_link"],
                "fingers": [f"rl_dg_{i}" for i in range(1, 6)],
                "tip": "{finger}_tip",
                "pip": "{finger}_3",
                "dip": "{finger}_4",
                # Wuji link1 is for optional finger-plane projection, not root anchoring.
                "link1": "{finger}_1",
            },
        },
        "retarget": {},
    }


def resolved_parameters(vendor):
    optimizer = vendor.optimizer
    names = (
        "huber_delta",
        "huber_delta_dir",
        "norm_delta",
        "w_pos",
        "w_dir",
        "w_full_hand",
        "scaling",
        "project_tip_dir",
        "thumb_skip_pip",
        "w_hyper",
        "soft_min",
        "w_couple",
        "couple_ratio",
    )
    result = {name: getattr(optimizer, name) for name in names}
    result.update(
        segment_scaling=optimizer.segment_scaling.tolist(),
        pinch_d1_cm=optimizer.d1.tolist(),
        pinch_d2_cm=optimizer.d2.tolist(),
        pinch_alpha_max=0.7,
        lp_alpha=vendor.lp_filter.alpha,
        nlopt_maxeval=optimizer.opt.get_maxeval(),
        ftol_abs=optimizer.opt.get_ftol_abs(),
        wrist_offset_m=vendor.wrist_offset_m.tolist(),
        thumb_offset_m=vendor.thumb_offset_m.tolist(),
    )
    return result


class WujiRetargeter(BaseRetargeter):
    def __init__(self, robot):
        if robot.config["handedness"] != "right":
            raise NotImplementedError("Only the verified right DG-5F is supported")
        self.robot = robot
        self.config = model_config(robot)
        self.vendor = upstream().from_config(json.loads(json.dumps(self.config)), hand_side="right")
        self.names = tuple(self.vendor.optimizer.robot.dof_joint_names)
        if len(self.names) != 20 or set(self.names) != set(robot.joint_names):
            raise ValueError("Wuji joint names do not match the common 20-DoF contract")
        self.indices = [self.names.index(name) for name in robot.joint_names]
        opt = self.vendor.optimizer
        self.constraint_binding = {
            "pip_joint_names": [self.names[int(i)] for i in opt._pip_idx],
            "dip_joint_names": [self.names[int(i)] for i in opt._dip_idx],
            "hyperextension_active": opt.w_hyper != 0,
            "coupling_active": opt.w_couple != 0,
            "policy": "upstream defaults preserved; no DG-5F coupling ratio fitted or enabled",
        }
        self.provenance = {
            "repository": "https://github.com/wuji-technology/wuji-retargeting",
            "commit": COMMIT,
            "algorithm": "AdaptiveOptimizerAnalytical",
            "parameters": "unchanged upstream code defaults; robot naming/path only",
            "output_filter": "upstream default LPFilter(alpha=0.2) enabled",
            "resolved_parameters": resolved_parameters(self.vendor),
            "constraint_binding": self.constraint_binding,
            "source_sha256": {
                str(p.relative_to(REPOSITORY)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in (REPOSITORY / "wuji_retargeting").rglob("*.py")
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
            raise ValueError("Wuji requires valid right-hand input")
        session = hand_frame.metadata.get("session_id")
        if (
            session == self.last_session
            and self.last_timestamp is not None
            and hand_frame.timestamp < self.last_timestamp
        ):
            raise ValueError("Retargeting timestamps regressed; reset before replay")
        geometric_features(hand_frame)  # Reject degenerate geometry; do not transform gains.
        points = world_points(hand_frame)
        preprocess_s = perf_counter() - start
        mapping_start = perf_counter()
        q, info = self.vendor.retarget_verbose(points)
        mapping_s = perf_counter() - mapping_start
        raw = np.asarray(q, dtype=float)[self.indices]
        unfiltered = np.asarray(info["qpos_unfiltered"], dtype=float)[self.indices]
        target = self.robot.validate_target(raw, clip=True)
        self.last_timestamp, self.last_session = hand_frame.timestamp, session
        code = int(self.vendor.optimizer.opt.last_optimize_result())
        return RetargetingResult(
            target,
            {
                "method": "wuji_adaptive_defaults",
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
                "mapping_s": mapping_s,
                "total_s": perf_counter() - start,
            },
        )


def register_wuji():
    """Explicit opt-in keeps previous Phase 5 entry point and tests unchanged."""
    from benchmark.retargeting.registry import register

    register("wuji", WujiRetargeter)
