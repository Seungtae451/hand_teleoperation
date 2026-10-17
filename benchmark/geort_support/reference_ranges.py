"""Pinned Allegro flexion bounds transferred conservatively to a separate DG-5F profile."""

import hashlib
import json
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from time import perf_counter

import numpy as np

from benchmark.geort_support.assets import validate_config
from benchmark.geort_support.input import canonical_points
from benchmark.geort_support.source import COMMIT, REPOSITORY, enable_upstream, verify_source
from benchmark.retargeting.base import BaseRetargeter, RetargetingResult
from benchmark.simulation.robot_model import RobotModel

PROFILE_ID = "geort_allegro_right_flexion_reference_v1"
SOURCE_URDF = "assets/allegro_right/allegro_hand_right.urdf"


def build_profile(robot=None):
    verify_source()
    robot = robot or RobotModel()
    raw = subprocess.check_output(["git", "-C", str(REPOSITORY), "show", f"{COMMIT}:{SOURCE_URDF}"])
    tree = ET.fromstring(raw)
    source = {j.get("name"): j for j in tree.findall("joint")}
    bounds = robot.limits.copy()
    mappings = []
    for finger, source_start in [(2, 0), (3, 4), (4, 8)]:
        for stage in [2, 3, 4]:
            target = f"rj_dg_{finger}_{stage}"
            name = f"joint_{source_start + stage - 1}.0"
            i = robot.joint_names.index(target)
            joint = source[name]
            axis = np.array(list(map(float, joint.find("axis").get("xyz").split())))
            # Only the three serial +Y flexion axes are mapped; roll/spread/thumb are not.
            if not np.array_equal(axis, [0, 1, 0]):
                raise ValueError("Unexpected source flexion axis")
            source_bounds = np.array(
                [float(joint.find("limit").get(k)) for k in ["lower", "upper"]]
            )
            bounds[i] = [max(bounds[i, 0], source_bounds[0]), min(bounds[i, 1], source_bounds[1])]
            if bounds[i, 0] >= bounds[i, 1]:
                raise ValueError("Empty range intersection")
            mappings.append(
                {
                    "source_joint": name,
                    "target_joint": target,
                    "target_index": i,
                    "source_bounds_rad": source_bounds.tolist(),
                    "official_dg_bounds_rad": robot.limits[i].tolist(),
                    "applied_bounds_rad": bounds[i].tolist(),
                    "applied_bounds_deg": np.degrees(bounds[i]).tolist(),
                    "correspondence": (
                        "Serial +Y flexion stage; sign retained, zero offset; range "
                        "intersection only"
                    ),
                }
            )
    mapped = {m["target_joint"] for m in mappings}
    unmapped = []
    for n in robot.joint_names:
        if n in mapped:
            continue
        reason = "First joint rotation axis differs; no direct range transfer"
        if n.startswith("rj_dg_1_"):
            reason = (
                "Thumb axes, zero configuration and joint roles differ; "
                "no verified one-to-one mapping"
            )
        if n.startswith("rj_dg_5_"):
            reason = "Allegro has no pinky; DG-5F pinky has a different axis/chain layout"
        unmapped.append({"joint": n, "policy": "retain official DG-5F range", "reason": reason})
    return {
        "schema": "geort_reference_range_v1",
        "profile_id": PROFILE_ID,
        "source_repository": "https://github.com/facebookresearch/GeoRT",
        "source_commit": COMMIT,
        "source_urdf": SOURCE_URDF,
        "source_urdf_sha256": hashlib.sha256(raw).hexdigest(),
        "source_license": "CC-BY-NC-4.0",
        "target": "DG-5F right",
        "scope": (
            "Experimental Allegro-referenced training bounds; not human "
            "anatomical ROM, not manufacturer calibration, not equivalent "
            "fingertip workspace"
        ),
        "mapping_policy": (
            "Only index/middle/ring serial flexion stages; intersect "
            "reference limits with official robot limits; no fitted "
            "gains/offsets/coupling"
        ),
        "mappings": mappings,
        "unmapped": unmapped,
        "bounds_rad": bounds.tolist(),
        "official_bounds_rad": robot.limits.tolist(),
        "original_files_modified": False,
    }


def verify_profile(path, robot=None):
    expected = build_profile(robot)
    actual = json.loads(Path(path).read_text())
    if actual != expected:
        raise ValueError("Reference profile differs from reproducible pinned mapping")
    return actual


class ReferenceRangeRetargeter(BaseRetargeter):
    def __init__(self, robot, *, checkpoint, config_path, profile):
        self.robot = robot
        self.profile = verify_profile(profile, robot)
        self.bounds = np.array(self.profile["bounds_rad"])
        self.config = json.loads(Path(config_path).read_text())
        actual = np.array([self.config["joint"]["lower"], self.config["joint"]["upper"]]).T
        if not np.allclose(actual, self.bounds, atol=1e-7):
            raise ValueError(
                "Checkpoint range does not match reference profile; retraining required"
            )
        validation = json.loads(json.dumps(self.config))
        validation["joint"] = {
            "lower": robot.limits[:, 0].tolist(),
            "upper": robot.limits[:, 1].tolist(),
        }
        validate_config(validation)
        source = enable_upstream()
        from geort.export import GeoRTRetargetingModel

        self.vendor = GeoRTRetargetingModel(str(checkpoint), str(config_path))
        self.provenance = {
            **source,
            "profile_id": PROFILE_ID,
            "profile_sha256": hashlib.sha256(Path(profile).read_bytes()).hexdigest(),
            "checkpoint_sha256": hashlib.sha256(Path(checkpoint).read_bytes()).hexdigest(),
            "experimental_not_original_baseline": True,
        }
        self.reset()

    def reset(self):
        self.last_timestamp = None
        self.last_session = None

    def retarget(self, frame):
        import torch

        start = perf_counter()
        session = frame.metadata.get("session_id")
        if (
            session == self.last_session
            and self.last_timestamp is not None
            and frame.timestamp < self.last_timestamp
        ):
            raise ValueError("Timestamp regression")
        with torch.inference_mode():
            raw = np.asarray(self.vendor.forward(canonical_points(frame)), dtype=float)
        if np.any(raw < self.bounds[:, 0] - 1e-6) or np.any(raw > self.bounds[:, 1] + 1e-6):
            raise ValueError("Target exceeds declared training range")
        target = self.robot.validate_target(raw, clip=True)
        self.last_timestamp = frame.timestamp
        self.last_session = session
        return RetargetingResult(
            target,
            {
                "method": PROFILE_ID,
                "solver_status": "checkpoint_inference",
                "q_vendor_raw": raw.tolist(),
                "joint_limit_clipped": (raw != target).tolist(),
                "total_s": perf_counter() - start,
            },
        )
