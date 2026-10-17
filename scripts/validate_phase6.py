#!/usr/bin/env python3
"""Execute full public sequences through three unchanged methods and render previews."""

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

os.environ.setdefault("MUJOCO_GL", "egl")

import numpy as np

from benchmark.datasets.public import catalog, fetch_samples, load_public
from benchmark.experiments.manus_fixtures import pose_frame
from benchmark.experiments.phase6_cli import main as run
from benchmark.paths import ROOT
from benchmark.retargeting.anydex import AnyDexRetargeter
from benchmark.retargeting.wuji import WujiRetargeter
from benchmark.simulation.robot_model import RobotModel


def constraint_audit(robot, adapter):
    import xml.etree.ElementTree as ET

    root = ET.parse(ROOT / robot.config["urdf"]).getroot()
    byname = {j.get("name"): j for j in root.findall("joint")}
    names = (
        adapter.constraint_binding["pip_joint_names"]
        + adapter.constraint_binding["dip_joint_names"]
    )
    joints = []
    for name in names:
        node = byname[name]
        limit = node.find("limit")
        joints.append(
            {
                "name": name,
                "axis_local": node.find("axis").get("xyz"),
                "limits_rad": [float(limit.get("lower")), float(limit.get("upper"))],
                "mimic": node.find("mimic") is not None,
            }
        )
    return {
        "binding": adapter.constraint_binding,
        "joints": joints,
        "robot_has_mimic": any(j.find("mimic") is not None for j in root.findall("joint")),
        "interpretation": "negative PIP/DIP allowed by URDF; same local PIP/DIP axis in each "
        "finger, but positive-only soft_min and 0.7 coupling are not "
        "DG-5F hardware constraints; baseline leaves both weights zero",
    }


def shared_loss_audit(robot):
    a = AnyDexRetargeter(robot).vendor.optimizer
    w = WujiRetargeter(robot).vendor.optimizer
    from wuji_retargeting.mediapipe import apply_mediapipe_transformations

    errors = []
    rng = np.random.default_rng(20261018)
    for kind in ("open", "closed", "pinch"):
        points = apply_mediapipe_transformations(pose_frame(kind).joint_positions)
        alphas = w._compute_pinch_alpha(points)
        at = a._compute_adaptive_targets(points, alphas)
        wt = (
            w._compute_tip_vectors(points, w.scaling),
            w._compute_tip_dirs(points),
            w._compute_full_hand_vectors(points, w.segment_scaling),
        )
        for _ in range(10):
            limits = w.robot.joint_limits
            q = limits[:, 0] + rng.uniform(0.1, 0.9, 20) * np.ptp(limits, axis=1)
            av, ag = a._loss_and_grad_analytical(q, *at, alphas, q * 0.9)
            wv, wg = w._loss_and_grad_analytical(q, *wt, alphas, q * 0.9)
            errors.append((abs(av - wv), float(np.max(abs(ag - wg)))))
    return {
        "comparisons": len(errors),
        "max_loss_difference": max(e[0] for e in errors),
        "max_gradient_difference": max(e[1] for e in errors),
        "interpretation": "shared base objective at all-one scales and default inactive extras; "
        "do not treat these as wholly independent algorithms",
    }


def pair_differences(folder):
    errors = []
    with (folder / "anydex.jsonl").open() as af, (folder / "wuji.jsonl").open() as wf:
        next(af)
        next(wf)
        for a, w in zip(af, wf):
            a, w = json.loads(a), json.loads(w)
            assert a["input_index"] == w["input_index"]
            errors.append(np.abs(np.array(a["retarget_q_target"]) - w["retarget_q_target"]))
    errors = np.array(errors)
    return {
        "control_frames": len(errors),
        "mean_abs_joint_difference_rad": float(errors.mean()),
        "max_abs_joint_difference_rad": float(errors.max()),
        "note": "different numerical paths/warm-start precision can change sequential solutions "
        "even when the default objective agrees",
    }


def main():
    (ROOT / "results").mkdir(exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix="phase6-validation-", dir=ROOT / "results"))
    fetch_samples()
    reports, differences = {}, {}
    for name in catalog():
        frames = list(load_public(name))
        reports[name] = run(
            ["--dataset", name, "--frames", str(len(frames)), "--output", str(folder / name)]
        )
        assert all(
            m["unique_input_frames_evaluated"] == len(frames) for m in reports[name]["methods"]
        )
        differences[name] = pair_differences(folder / name)
        run(
            [
                "--dataset",
                name,
                "--frames",
                "90",
                "--video",
                "--output",
                str(folder / f"{name}_preview"),
            ]
        )
    robot = RobotModel()
    adapter = WujiRetargeter(robot)
    baseline = json.loads((ROOT / "docs/phase6_existing_files.sha256.json").read_text())
    changed = [
        p for p, d in baseline.items() if hashlib.sha256((ROOT / p).read_bytes()).hexdigest() != d
    ]
    assert not changed, changed
    checked = subprocess.run(
        [str(ROOT / ".venv/bin/python"), "scripts/verify_phase5_sources.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    upstream_check = json.loads(checked.stdout)
    (folder / "upstream_integrity.json").write_text(checked.stdout)
    pointer = (ROOT / "external/wuji-retargeting/example/data/avp1.pkl").read_text()
    oid = next(line.split("sha256:")[1] for line in pointer.splitlines() if line.startswith("oid "))
    report = {
        "phase": 6,
        "output": str(folder),
        "datasets": reports,
        "wuji_provenance": adapter.provenance,
        "constraints": constraint_audit(robot, adapter),
        "shared_loss_audit": shared_loss_audit(robot),
        "anydex_wuji_trajectory_differences": differences,
        "wuji_official_example": {
            "storage": "Git LFS pointer",
            "blob_sha256": oid,
            "same_as_anydex_sample": oid == catalog()["anydex_avp1"]["sha256"],
            "independent_evaluation_sequence": False,
        },
        "source_integrity": upstream_check,
        "pre_phase6_integrity": {"checked": len(baseline), "changed": changed},
        "scope": "development-only three-method comparison; no independent GT, "
        "pinch/contact success, held-out evaluation, or GeoRT model yet",
    }
    (folder / "validation.json").write_text(json.dumps(report, indent=2) + "\n")
    (ROOT / "results/phase6_validation_latest.json").write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {"output": str(folder), "pre_phase6_integrity": report["pre_phase6_integrity"]},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
