#!/usr/bin/env python3
"""Paired DG-5F range ablation with common FK, seed, IK init and human data."""

import argparse
import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SEED = 20261018


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def prepare(folder):
    from benchmark.geort_support.range_experiment import RESTRICTED_INDICES, restricted_bounds
    from benchmark.geort_support.runtime import load_workspace
    from benchmark.geort_support.source import enable_upstream
    from benchmark.simulation.robot_model import RobotModel

    _, config = load_workspace(ROOT / "results/geort_dg5f_workspace")
    enable_upstream()
    from geort.env.hand import HandKinematicModel

    robot = RobotModel()
    full = robot.limits
    restricted = restricted_bounds(full)
    folder.mkdir(parents=True, exist_ok=False)
    # Paired samples use exactly the same latent uniforms, mapped to each range.
    uniforms = np.random.RandomState(SEED).uniform(0, 1, (100000, 20))
    hand = HandKinematicModel.build_from_config(config, render=False)
    links = [tip["link"] for tip in config["fingertip_link"]]
    hand.initialize_keypoint(links, [tip["center_offset"] for tip in config["fingertip_link"]])
    source_fk = (
        ROOT
        / "results/geort_dg5f_workspace/training-f9nel4wo/checkpoint/fk_model_dg5f_right_geort.pth"
    )
    source_input = ROOT / "data/geort/quest_train_session_002/human.npy"
    manifest = json.loads((source_input.parent / "manifest.json").read_text())
    assert manifest["split"] == "train" and sha(source_input) == manifest["npy_sha256"]
    for name, bounds in [("full", full), ("restricted", restricted)]:
        run = folder / name
        run.mkdir()
        derived = json.loads(json.dumps(config))
        if name == "restricted":
            tree = ET.parse(config["urdf_path"])
            nodes = {j.get("name"): j for j in tree.getroot().findall("joint")}
            for i in RESTRICTED_INDICES:
                nodes[config["joint_order"][i]].find("limit").set("lower", "0")
            urdf = run / "dg5f_training_range.urdf"
            tree.write(urdf, encoding="utf-8", xml_declaration=True)
            derived["urdf_path"] = str(urdf)
        derived["joint"] = {"lower": bounds[:, 0].tolist(), "upper": bounds[:, 1].tolist()}
        save(run / "config.json", derived)
        (run / "checkpoint").mkdir()
        (run / "data").mkdir()
        shutil.copyfile(source_fk, run / "checkpoint/fk_model_dg5f_right_geort.pth")
        q = uniforms * (bounds[:, 1] - bounds[:, 0]) + bounds[:, 0]
        points = np.array([hand.keypoint_from_qpos(row, ret_vec=True) for row in q])
        np.savez(
            run / "data/dg5f_right_geort.npz",
            qpos=q,
            keypoint={link: points[:, i] for i, link in enumerate(links)},
        )
    save(
        folder / "study.json",
        {
            "seed": SEED,
            "full_bounds": full.tolist(),
            "restricted_bounds": restricted.tolist(),
            "restricted_joint_indices": list(RESTRICTED_INDICES),
            "restricted_joint_names": [config["joint_order"][i] for i in RESTRICTED_INDICES],
            "human_data": str(source_input),
            "human_sha256": sha(source_input),
            "training_frames": manifest["frames"],
            "shared_full_range_fk": str(source_fk),
            "fk_sha256": sha(source_fk),
            "change": (
                "Only eight nonthumb distal lower bounds set to zero; paired robot "
                "cloud and normalization follow range. Same FK function via "
                "deterministic affine normalization adapter. Original loss/trainer "
                "unchanged."
            ),
            "experimental_not_official_calibration": True,
            "original_urdf_modified": False,
        },
    )
    print(folder, flush=True)


def worker(folder, name):
    import torch

    from benchmark.geort_support.range_experiment import normalization_affine
    from benchmark.geort_support.source import enable_upstream

    enable_upstream()
    from geort.model import IKModel
    from geort.trainer import GeoRTTrainer

    doc = json.loads((folder / "study.json").read_text())
    run = folder / name
    config = json.loads((run / "config.json").read_text())
    bounds = np.array(doc["full_bounds"] if name == "full" else doc["restricted_bounds"])
    scale, bias = normalization_affine(bounds, np.array(doc["full_bounds"]))
    assert sha(run / "checkpoint/fk_model_dg5f_right_geort.pth") == doc["fk_sha256"]
    assert sha(doc["human_data"]) == doc["human_sha256"]

    class AffineFK(torch.nn.Module):
        def __init__(self, original):
            super().__init__()
            self.original = original
            self.register_buffer("scale", torch.tensor(scale, dtype=torch.float32, device="cuda"))
            self.register_buffer("bias", torch.tensor(bias, dtype=torch.float32, device="cuda"))

        def forward(self, normalized):
            return self.original(normalized * self.scale + self.bias)

    class RangeTrainer(GeoRTTrainer):
        def get_robot_neural_fk_model(self, force_train=False):
            if force_train:
                raise ValueError("This controlled experiment must reuse the same FK")
            original = super().get_robot_neural_fk_model(force_train=False)
            # Fork RNG to record exactly the IK initialization that original train creates next.
            with torch.random.fork_rng(devices=[0]):
                initial = IKModel(self.get_keypoint_info()["joint"])
                torch.save(initial.state_dict(), run / "initial_ik.pth")
            wrapped = AffineFK(original).eval()
            # Check SAME physical radians yield the SAME FK and correct derivative scaling.
            n = torch.linspace(-1, 1, 20, device="cuda")[None]
            with torch.no_grad():
                torch.testing.assert_close(
                    wrapped(n), original(n * wrapped.scale + wrapped.bias), rtol=0, atol=0
                )
            return wrapped

    random.seed(SEED)
    np.random.seed(SEED)
    torch.manual_seed(SEED)
    torch.cuda.manual_seed_all(SEED)
    previous = Path.cwd()
    start = time.monotonic()
    try:
        os.chdir(run)
        RangeTrainer(config).train(Path(doc["human_data"]))
    finally:
        os.chdir(previous)
    folders = [
        p for p in (run / "checkpoint").iterdir() if p.is_dir() and not p.name.endswith("_last")
    ]
    assert len(folders) == 1
    ck = folders[0]
    assert {int(p.stem.split("_")[1]) for p in ck.glob("epoch_*.pth")} == set(range(200))
    shutil.copyfile(ck / "last.pth", run / "model.pth")
    shutil.copyfile(ck / "config.json", run / "export_config.json")
    assert sha(run / "checkpoint/fk_model_dg5f_right_geort.pth") == doc["fk_sha256"]
    save(
        run / "manifest.json",
        {
            "status": "completed",
            "condition": name,
            "seed": SEED,
            "ik_epochs": 200,
            "input_sha256": doc["human_sha256"],
            "frames": doc["training_frames"],
            "fk_sha256": doc["fk_sha256"],
            "checkpoint": str(run / "model.pth"),
            "checkpoint_sha256": sha(run / "model.pth"),
            "config": str(run / "export_config.json"),
            "elapsed_s": time.monotonic() - start,
            "experimental_not_official_baseline": True,
        },
    )
    print(f"COMPLETE {name}", flush=True)


def train(folder):
    active = []
    for gpu, name in enumerate(["full", "restricted"]):
        stream = (folder / f"{name}_console.txt").open("x")
        p = subprocess.Popen(
            [
                str(ROOT / ".venv-geort/bin/python"),
                __file__,
                "worker",
                "--output",
                str(folder),
                "--condition",
                name,
            ],
            cwd=ROOT,
            env={**os.environ, "CUDA_VISIBLE_DEVICES": str(gpu), "PYTHONUNBUFFERED": "1"},
            stdout=stream,
            stderr=subprocess.STDOUT,
        )
        active.append((name, p, stream))
        print(f"START {name} GPU {gpu} PID {p.pid}", flush=True)
    try:
        while active:
            for name, p, stream in list(active):
                if p.poll() is not None:
                    stream.close()
                    if p.returncode:
                        raise RuntimeError(f"{name} failed; inspect console log")
                    active.remove((name, p, stream))
                    print(f"COMPLETE {name}", flush=True)
            time.sleep(1)
    finally:
        for _, p, stream in active:
            if p.poll() is None:
                p.terminate()
            stream.close()
    import torch

    a = torch.load(folder / "full/initial_ik.pth", weights_only=True, map_location="cpu")
    b = torch.load(folder / "restricted/initial_ik.pth", weights_only=True, map_location="cpu")
    assert a.keys() == b.keys() and all(torch.equal(a[k], b[k]) for k in a)
    save(
        folder / "initialization_verification.json",
        {"all_initial_ik_tensors_identical": True, "same_full_range_fk_hash": True},
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=["prepare", "train", "worker"])
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--condition", choices=["full", "restricted"])
    a = p.parse_args()
    folder = a.output.resolve()
    if a.command == "prepare":
        prepare(folder)
    elif a.command == "train":
        train(folder)
    else:
        worker(folder, a.condition)
