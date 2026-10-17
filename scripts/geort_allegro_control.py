#!/usr/bin/env python3
"""Pinned original Allegro positive control; never edit upstream checkouts."""

import argparse
import hashlib
import io
import json
import os
import random
import shutil
import subprocess
import sys
import tarfile
import time
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
    from benchmark.geort_support.source import REPOSITORY, enable_upstream, verify_source

    source = verify_source()
    folder.mkdir(parents=True, exist_ok=False)
    # Read pinned Git objects omitted by sparse checkout, without changing that checkout.
    archive = subprocess.check_output(
        [
            "git",
            "-C",
            str(REPOSITORY),
            "archive",
            "HEAD",
            "assets/allegro_right",
            "checkpoint/fk_model_allegro_right.pth",
        ]
    )
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        members = tar.getmembers()
        assert all(
            not m.name.startswith("/")
            and ".." not in Path(m.name).parts
            and not m.issym()
            and not m.islnk()
            for m in members
        )
        tar.extractall(folder)
    config = json.loads((REPOSITORY / "geort/config/allegro_right.json").read_text())
    original_config = json.loads(json.dumps(config))
    config["urdf_path"] = str(folder / "assets/allegro_right/allegro_hand_right.urdf")
    save(folder / "config.json", config)
    source_hashes = {m.name: sha(folder / m.name) for m in members if m.isfile()}
    enable_upstream()
    from geort.trainer import GeoRTTrainer

    random.seed(SEED)
    np.random.seed(SEED)
    previous = Path.cwd()
    try:
        os.chdir(folder)
        trainer = GeoRTTrainer(config)
        trainer.generate_robot_kinematics_dataset(n_total=100000, save=True)
    finally:
        os.chdir(previous)
    save(
        folder / "preparation.json",
        {
            "source": source,
            "original_config": original_config,
            "config_change": (
                "urdf_path only; original assets copied byte-identically from pinned "
                "Git objects; caches only in result copies"
            ),
            "original_files_sha256": source_hashes,
            "official_fk_sha256": sha(folder / "checkpoint/fk_model_allegro_right.pth"),
            "robot_data_sha256": sha(folder / "data/allegro_right.npz"),
            "seed": SEED,
            "conditions": ["official_alex", "personal_quest"],
            "robot_data": (
                "Original uniform official-limit robot-only 100000 poses; shared by both trainings"
            ),
        },
    )
    print(folder, flush=True)


def worker(folder, name):
    from benchmark.geort_support.source import enable_upstream

    enable_upstream()
    import torch
    from geort.trainer import GeoRTTrainer

    config = json.loads((folder / "config.json").read_text())
    config["urdf_path"] = str(Path(config["urdf_path"]).resolve())
    inputs = {
        "official_alex": ROOT / "data/public/geort/human_alex.npy",
        "personal_quest": ROOT / "data/geort/quest_train_session_002/human.npy",
    }
    data = inputs[name]
    run = folder / "models" / name
    run.mkdir(parents=True, exist_ok=False)
    for relative in ["checkpoint/fk_model_allegro_right.pth", "data/allegro_right.npz"]:
        destination = run / relative
        destination.parent.mkdir(exist_ok=True)
        shutil.copyfile(folder / relative, destination)
    random.seed(SEED)
    np.random.seed(SEED)
    torch.manual_seed(SEED)
    torch.cuda.manual_seed_all(SEED)
    started = time.monotonic()
    previous = Path.cwd()
    try:
        os.chdir(run)
        GeoRTTrainer(config).train(data)
    finally:
        os.chdir(previous)
    checkpoints = [
        p for p in (run / "checkpoint").iterdir() if p.is_dir() and not p.name.endswith("_last")
    ]
    assert len(checkpoints) == 1
    ck = checkpoints[0]
    assert {int(p.stem.split("_")[1]) for p in ck.glob("epoch_*.pth")} == set(range(200))
    shutil.copyfile(ck / "last.pth", run / "model.pth")
    shutil.copyfile(ck / "config.json", run / "config.json")
    save(
        run / "manifest.json",
        {
            "status": "completed",
            "condition": name,
            "seed": SEED,
            "ik_epochs": 200,
            "original_fk_provided_by_upstream": True,
            "input": str(data),
            "input_sha256": sha(data),
            "frames": len(np.load(data)),
            "checkpoint": str(run / "model.pth"),
            "config": str(run / "config.json"),
            "checkpoint_sha256": sha(run / "model.pth"),
            "elapsed_s": time.monotonic() - started,
        },
    )
    print(f"COMPLETE {name}", flush=True)


def train(folder):
    jobs = []
    for gpu, name in enumerate(["official_alex", "personal_quest"]):
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
        jobs.append((name, p, stream))
        print(f"START {name} GPU {gpu} PID {p.pid}", flush=True)
    try:
        while jobs:
            for name, p, stream in list(jobs):
                if p.poll() is not None:
                    stream.close()
                    if p.returncode:
                        raise RuntimeError(f"{name} failed; see console log")
                    jobs.remove((name, p, stream))
                    print(f"COMPLETE {name}", flush=True)
            time.sleep(1)
    finally:
        for _, p, stream in jobs:
            if p.poll() is None:
                p.terminate()
            stream.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "train", "worker"])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--condition", choices=["official_alex", "personal_quest"])
    args = parser.parse_args()
    folder = args.output.resolve()
    if args.command == "prepare":
        prepare(folder)
    elif args.command == "train":
        train(folder)
    else:
        worker(folder, args.condition)
