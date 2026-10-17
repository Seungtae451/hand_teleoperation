"""Validation of original SAPIEN kinematics and architecture; never starts training."""

import importlib.metadata
import json
from pathlib import Path

import numpy as np

from benchmark.geort_support.assets import validate_config
from benchmark.geort_support.source import enable_upstream
from benchmark.simulation.robot_model import RobotModel


def load_workspace(path):
    folder = Path(path).resolve()
    config = json.loads((folder / "config.json").read_text())
    validate_config(config)
    import hashlib

    manifest = json.loads((folder / "preparation.json").read_text())
    if (
        hashlib.sha256((folder / "config.json").read_bytes()).hexdigest()
        != manifest["config_sha256"]
    ):
        raise ValueError("Prepared config changed; prepare a new workspace")
    if (
        hashlib.sha256(Path(config["urdf_path"]).read_bytes()).hexdigest()
        != manifest["derived_urdf_sha256"]
    ):
        raise ValueError("Prepared URDF changed; prepare a new workspace")
    for mesh in manifest["mesh_resolution"]:
        if hashlib.sha256(Path(mesh["resolved"]).read_bytes()).hexdigest() != mesh["sha256"]:
            raise ValueError("Prepared mesh changed; prepare a new workspace")
    return folder, config


def check_runtime(workspace):
    _, config = load_workspace(workspace)
    provenance = enable_upstream()
    import torch
    from geort.env.hand import HandKinematicModel
    from geort.model import FKModel, IKModel
    from geort.utils.config_utils import parse_config_keypoint_info

    info = parse_config_keypoint_info(config)
    hand = HandKinematicModel.build_from_config(config, render=False)
    hand.initialize_keypoint(info["link"], info["offset"])
    robot = RobotModel()
    lower, upper = hand.get_joint_limit()
    np.testing.assert_allclose(lower, robot.limits[:, 0], atol=1e-7)
    np.testing.assert_allclose(upper, robot.limits[:, 1], atol=1e-7)
    # Small deterministic geometry checks; no sampled training dataset or benchmark.
    errors = []
    for q in (
        np.zeros(20),
        robot.limits.mean(axis=1),
        robot.limits[:, 0] * 0.2 + robot.limits[:, 1] * 0.8,
    ):
        points = hand.keypoint_from_qpos(q, ret_vec=True)
        expected = robot.forward_kinematics(q, frame="palm")
        errors.append(float(np.max(np.abs(points - expected))))
        np.testing.assert_allclose(points, expected, atol=2e-6)
    # Inspect architecture only. No neural forward pass with untrained weights.
    with torch.random.fork_rng(devices=[]):
        fk = FKModel(info["joint"])
        ik = IKModel(info["joint"])
    assert fk.n_total_joint == ik.n_total_joint == 20
    assert len(fk.nets) == len(ik.nets) == 5
    gpu_probe = None
    if torch.cuda.is_available():
        gpu_probe = float(torch.ones(1, device="cuda").sum().item())
    report = {
        "source": provenance,
        "geometry_cases": len(errors),
        "max_sapien_mujoco_fk_difference_m": max(errors),
        "joint_count": 20,
        "fingertip_count": 5,
        "network_architecture": {
            "fk_parameter_count": sum(p.numel() for p in fk.parameters()),
            "ik_parameter_count": sum(p.numel() for p in ik.parameters()),
            "forward_executed": False,
        },
        "environment": {
            name: importlib.metadata.version(name)
            for name in ("torch", "sapien", "numpy", "open3d", "mujoco")
        },
        "cuda_available": torch.cuda.is_available(),
        "cuda_runtime": torch.version.cuda,
        "gpu_names": [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())],
        "gpu_scalar_probe": gpu_probe,
        "training_executed": False,
        "performance_evaluation_executed": False,
        "trained_inference": "pending a real DG-5F checkpoint",
    }
    return report
