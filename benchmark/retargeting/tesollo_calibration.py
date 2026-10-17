"""Robot-specific configuration through pinned vendor APIs, without vendor edits."""

import ast
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from scipy.spatial.transform import Rotation

from benchmark.paths import ROOT, writable_output
from benchmark.retargeting.anydex import AnyDexRetargeter
from benchmark.retargeting.quest_ergonomics import geometric_features
from benchmark.retargeting.wuji import WujiRetargeter, resolved_parameters
from benchmark.tracking.coordinate_transform import world_points
from benchmark.tracking.recorder import replay_frames

FINGERS = ("thumb", "index", "middle", "ring", "pinky")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def original_functions(path, names, namespace):
    """Load original AST bodies unchanged; skip device imports and YAML writers."""
    tree = ast.parse(path.read_bytes(), filename=str(path))
    selected = [
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    if {node.name for node in selected} != set(names):
        raise ValueError("Pinned calibration helper API changed")
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


def select_open_frames(frames, seconds=5.0):
    """Select a continuous open-hand candidate; this is an explicit project heuristic."""
    runs, current = [], []
    for index, frame in enumerate(frames):
        if frame.tracking_valid:
            try:
                features = geometric_features(frame).reshape(5, 4)[1:]
                is_open = np.max(np.abs(features[:, 1])) < 25 and np.max(features[:, 2:]) < 25
            except ValueError:
                is_open = False
        else:
            is_open = False
        if is_open and (not current or frame.timestamp - frames[current[-1]].timestamp <= 0.1):
            current.append(index)
        else:
            if current:
                runs.append(current)
            current = [index] if is_open else []
    if current:
        runs.append(current)
    if not runs:
        raise ValueError(
            "No open-hand candidate; supply a dedicated open-hand calibration recording"
        )
    longest = max(runs, key=lambda run: frames[run[-1]].timestamp - frames[run[0]].timestamp)
    selected = [i for i in longest if frames[i].timestamp - frames[longest[0]].timestamp <= seconds]
    if len(selected) < 30 or frames[selected[-1]].timestamp - frames[selected[0]].timestamp < 1:
        raise ValueError("Need >=30 open frames over >=1 second; record a stable open hand")
    return selected


def verify_fk(robot, adapter, count=12):
    """Cross-check vendor Pinocchio vs common MuJoCo at zero, each joint, random poses."""
    rng = np.random.default_rng(20261018)
    probes = [np.zeros(20)]
    for index in range(20):
        q = np.zeros(20)
        q[index] = 0.15 if robot.limits[index, 1] >= 0.15 else -0.15
        probes.append(robot.validate_target(q))
    probes.extend(rng.uniform(robot.limits[:, 0], robot.limits[:, 1], size=(count, 20)))
    maximum = 0.0
    model = adapter.vendor.optimizer.robot
    for q in probes:
        vendor_q = np.array([q[robot.joint_names.index(name)] for name in adapter.names])
        model.compute_forward_kinematics(vendor_q)
        palm = model.get_link_pose(model.get_link_index(robot.config["palm_link"]))
        points = np.array(
            [
                model.get_link_pose(model.get_link_index(name))[:3, 3]
                for name in robot.config["tip_links"]
            ]
        )
        vendor_tips = (points - palm[:3, 3]) @ palm[:3, :3]
        expected = robot.forward_kinematics(q, frame="palm")
        maximum = max(maximum, float(np.max(np.abs(vendor_tips - expected))))
    if maximum > 2e-6:
        raise ValueError(f"Vendor/MuJoCo FK mismatch: {maximum} m")
    return {
        "poses": len(probes),
        "max_coordinate_error_m": maximum,
        "single_joint_axis_and_sign_probes": 20,
    }


def build_profile(recording, output, seconds=5.0):
    from benchmark.retargeting.anydex import REPOSITORY
    from benchmark.retargeting.anydex import model_config as anydex_config
    from benchmark.retargeting.wuji import model_config as wuji_config
    from benchmark.simulation.robot_model import RobotModel

    recording = Path(recording).resolve()
    recording_digest = sha256(recording)
    known_train_hashes = {
        manifest.get("source_recording_sha256")
        for path in (ROOT / "data/geort").glob("*/manifest.json")
        if (manifest := json.loads(path.read_text())).get("split") == "train"
    }
    output = writable_output(Path(output))
    output.mkdir(parents=True, exist_ok=False)
    robot = RobotModel()
    baseline = AnyDexRetargeter(robot)  # Verifies pinned checkout before reading helper AST.
    from anydexretarget.mediapipe import apply_mediapipe_transformations

    frames = list(replay_frames(recording, handedness="right"))
    selected = select_open_frames(frames, seconds)
    points = np.array(
        [apply_mediapipe_transformations(world_points(frames[i]), "right") for i in selected]
    )
    if not np.isfinite(points).all():
        raise ValueError("Nonfinite calibration capture")
    median = np.median(points, axis=0)  # Same robust-center rule as official batch tool.
    palm_lengths = np.linalg.norm(points[:, 9] - points[:, 0], axis=1)
    if not np.all((palm_lengths > 0.02) & (palm_lengths < 0.25)):
        raise ValueError("Calibration capture must be in meters")
    scripts = REPOSITORY / "example/test"
    rotation_helpers = original_functions(
        scripts / "calibrate_rotation.py", ["fit_rotation", "optimal_scale"], {"np": np}
    )
    roots = baseline.vendor.optimizer.finger_root_vectors * 0.01
    human_roots = median[[1, 5, 9, 13, 17]] - median[0]
    rotation, diagnostic_scale = rotation_helpers["fit_rotation"](human_roots, roots)
    xyz = dict(
        zip(("x", "y", "z"), Rotation.from_matrix(rotation).as_euler("xyz", degrees=True).tolist())
    )
    config = anydex_config(robot)
    config["retarget"]["mediapipe_rotation"] = xyz
    binding = output / "calibration_binding/config/adaptive/quest3/quest3_tesollo_dg5f.yaml"
    binding.parent.mkdir(parents=True)
    binding.write_text(json.dumps(config, indent=2) + "\n")  # JSON is valid YAML.
    helpers = original_functions(
        scripts / "calibrate_scaling.py",
        [
            "_resolve_config_paths",
            "_get_link_pos",
            "get_robot_distances",
            "palm_scale_for_finger",
            "segment_scales_for_finger",
            "_phalanx_segments",
            "calibrate_one_robot",
        ],
        {
            "np": np,
            "Retargeter": type(baseline.vendor),
            "CM_TO_M": 0.01,
            "EXAMPLE_ROOT": output / "calibration_binding",
            "config_dir_for": lambda _: "quest3",
            "FINGER_NAMES": list(FINGERS),
            "MP_MCP_INDICES": [1, 5, 9, 13, 17],
            "MP_PIP_INDICES": [2, 6, 10, 14, 18],
            "MP_DIP_INDICES": [3, 7, 11, 15, 19],
            "MP_TIP_INDICES": [4, 8, 12, 16, 20],
            "DEGENERATE_SEGMENT_M": 5e-4,
        },
    )
    segment, cumulative, _, merged = helpers["calibrate_one_robot"](
        SimpleNamespace(input="quest3", hand="right"), "tesollo_dg5f", median
    )
    pinch_helpers = original_functions(
        scripts / "calibrate_pinch_scaling.py", ["_robot_tip_reaches"], {"np": np}
    )
    robot_reach = pinch_helpers["_robot_tip_reaches"](baseline.vendor.optimizer)[1]
    # Official pinch tool uses the median of individual index reach measurements.
    human_reach = float(np.median(np.linalg.norm(points[:, 8] - points[:, 0], axis=1)))
    pinch_scale = round(float(robot_reach / human_reach), 4)
    config["retarget"].update(segment_scaling=segment, pinch_scaling=pinch_scale)
    wuji = wuji_config(robot)
    wuji["retarget"].update(mediapipe_rotation=xyz, segment_scaling=cumulative, scaling=pinch_scale)
    namespace_note = (
        "Project robot-geometry adapter: use wrist-to-PIP/DIP/TIP reach ratios, "
        "not AnyDex per-bone ratios. Wuji provides these config fields but its "
        "bundled glove-only calibrator is not a Quest/DG-5F calibration procedure."
    )
    residual_before = np.linalg.norm(human_roots - roots, axis=1)
    residual_rotated = np.linalg.norm(human_roots @ rotation.T - roots, axis=1)
    profile = {
        "schema": "tesollo_robot_calibration_v1",
        "handedness": "right",
        "units": "m",
        "urdf_sha256": sha256(ROOT / robot.config["urdf"]),
        "joint_names": list(robot.joint_names),
        "calibration": {
            "source": str(recording),
            "source_sha256": recording_digest,
            "role": "calibration_only_not_held_out_evaluation",
            "participant_id": None,
            "source_overlap_with_geort_training": recording_digest in known_train_hashes,
            "selection": "longest contiguous open candidate, then first requested seconds; "
            "non-thumb abs MCP flex<25deg and all PIP/DIP<25deg; gap<=0.1s; not manual labels",
            "selected_right_frame_indices": selected,
            "frames": len(selected),
            "timestamp_start_s": frames[selected[0]].timestamp,
            "timestamp_end_s": frames[selected[-1]].timestamp,
            "open_pose_manually_verified": False,
            "root_residual_before_m": residual_before.tolist(),
            "root_residual_rotation_only_m": residual_rotated.tolist(),
            "rotation_procrustes_scale_diagnostic_only": float(diagnostic_scale),
            "merged_fingers": merged,
            "input_tracking": "Quest WebXR estimated skeleton",
            "upstream_helpers_sha256": {
                p.name: sha256(p)
                for p in (
                    scripts / "calibrate_rotation.py",
                    scripts / "calibrate_scaling.py",
                    scripts / "calibrate_pinch_scaling.py",
                )
            },
        },
        "methods": {
            "anydex": {
                "config": config,
                "procedure": "unchanged official rotation/scaling helpers; "
                "official open-index-reach pinch ratio; project recording input adapter",
            },
            "wuji": {"config": wuji, "procedure": namespace_note},
            "manus": {
                "procedure": "existing official DG-5F MANUS mapping retained; "
                "no official Quest proxy calibration available; no gains/offsets fitted"
            },
            "geort": {
                "procedure": "existing DG-5F URDF/config/trained checkpoint retained; "
                "no post-training scale or input rotation changes"
            },
        },
        "fk_audit": {
            "anydex": verify_fk(robot, baseline),
            "wuji": verify_fk(robot, WujiRetargeter(robot)),
        },
        "evaluation_policy": "freeze profile before evaluation; reject calibration source as test; "
        "preserve baseline; participant-disjointness unverified",
    }
    for method in ("anydex", "wuji"):
        values = np.asarray(
            list(profile["methods"][method]["config"]["retarget"]["segment_scaling"].values())
        )
        if not np.isfinite(values).all() or np.any(values <= 0):
            raise ValueError("Invalid geometry calibration; do not substitute defaults")
    np.savez(
        output / "open_capture.npz",
        transformed_m=points,
        median_transformed_m=median,
        right_frame_indices=np.array(selected),
    )
    path = output / "profile.json"
    path.write_text(json.dumps(profile, indent=2, allow_nan=False) + "\n")
    return path, profile


def load_profile(path, robot):
    path = Path(path).resolve()
    profile = json.loads(path.read_text())
    if (
        profile.get("schema") != "tesollo_robot_calibration_v1"
        or profile.get("handedness") != "right"
        or profile.get("units") != "m"
        or profile.get("joint_names") != list(robot.joint_names)
        or profile.get("urdf_sha256") != sha256(ROOT / robot.config["urdf"])
    ):
        raise ValueError("Calibration profile does not match the official right DG-5F model")
    for method, columns, scalar in (("anydex", 4, "pinch_scaling"), ("wuji", 3, "scaling")):
        settings = profile["methods"][method]["config"]["retarget"]
        if set(settings) != {"mediapipe_rotation", "segment_scaling", scalar}:
            raise ValueError(
                "Only robot geometry calibration settings are permitted in this profile"
            )
        if set(settings["segment_scaling"]) != set(FINGERS):
            raise ValueError("Calibration requires all five fingers")
        scales = np.asarray([settings["segment_scaling"][name] for name in FINGERS])
        if scales.shape != (5, columns) or not np.isfinite(scales).all() or np.any(scales <= 0):
            raise ValueError("Invalid robot segment scaling")
        if not np.isfinite(settings[scalar]) or settings[scalar] <= 0:
            raise ValueError("Invalid robot reach scaling")
        angles = settings["mediapipe_rotation"]
        if set(angles) != {"x", "y", "z"} or not np.isfinite(list(angles.values())).all():
            raise ValueError("Invalid robot orientation calibration")
    return profile


def configure(adapter, method, path):
    profile = load_profile(path, adapter.robot)
    config = json.loads(json.dumps(profile["methods"][method]["config"]))
    # Bindings must still match this checkout; the profile only changes retarget settings.
    for key in ("optimizer", "robot"):
        if config.get(key) != adapter.config.get(key):
            raise ValueError(f"Profile {key} binding changed; recalibrate in this checkout")
    adapter.config = config
    adapter.vendor = type(adapter.vendor).from_config(
        json.loads(json.dumps(config)), hand_side="right"
    )
    if tuple(adapter.vendor.optimizer.robot.dof_joint_names) != adapter.names:
        raise ValueError("Configured vendor joint ordering changed")
    adapter.provenance.update(
        parameters="robot-specific configuration through original vendor APIs",
        robot_profile_sha256=sha256(path),
        robot_profile=str(Path(path).resolve()),
        calibration=profile["calibration"],
        calibration_procedure=profile["methods"][method]["procedure"],
    )
    if method == "wuji":
        adapter.provenance["resolved_parameters"] = resolved_parameters(adapter.vendor)
    adapter.reset()


class CalibratedAnyDex(AnyDexRetargeter):
    def __init__(self, robot, *, profile):
        super().__init__(robot)
        configure(self, "anydex", profile)

    def retarget(self, hand_frame):
        result = super().retarget(hand_frame)
        result.metadata["method"] = "anydex_robot_calibrated"
        result.metadata["robot_profile_sha256"] = self.provenance["robot_profile_sha256"]
        return result


class CalibratedWuji(WujiRetargeter):
    def __init__(self, robot, *, profile):
        super().__init__(robot)
        configure(self, "wuji", profile)

    def retarget(self, hand_frame):
        result = super().retarget(hand_frame)
        result.metadata["method"] = "wuji_robot_geometry_configured"
        result.metadata["robot_profile_sha256"] = self.provenance["robot_profile_sha256"]
        return result
