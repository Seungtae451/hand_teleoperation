#!/usr/bin/env python3
"""Preserve old data and split IDs; retrain three explicitly parity-adapted inputs."""

import argparse
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from benchmark.datasets.quest_parity import PROVENANCE, adapt_canonical  # noqa: E402
from scripts.geort_data_size_study import sha, write_json  # noqa: E402

CONDITIONS = ("quest_1000", "quest_3498", "quest_10000")


def prepare(source, output):
    source, output = source.resolve(), output.resolve()
    document = copy.deepcopy(json.loads((source / "study.json").read_text()))
    output.mkdir(parents=True, exist_ok=False)
    document.update(parent_study=str(source), coordinate_adapter=PROVENANCE)
    document["quest_source"]["coordinate_frame"] = (
        "publisher-declared FLU; world chirality unverified; canonical parity adapter applied"
    )
    document["quest_source"]["coordinate_adapter"] = PROVENANCE
    for name in (*document["conditions"], "validation", "test"):
        old = source / "datasets" / name
        new = output / "datasets" / name
        new.mkdir(parents=True)
        if name.startswith("official"):
            shutil.copyfile(old / "human.npy", new / "human.npy")
        else:
            np.save(new / "human.npy", adapt_canonical(np.load(old / "human.npy")))
            shutil.copyfile(old / "row_ids.npz", new / "row_ids.npz")
        if (old / "manifest.json").exists():
            manifest = json.loads((old / "manifest.json").read_text())
            if not name.startswith("official"):
                manifest["source"] = document["quest_source"]
                manifest.update(
                    coordinate_adapter=PROVENANCE, parent_input_sha256=sha(old / "human.npy")
                )
            manifest["npy_sha256"] = sha(new / "human.npy")
            write_json(new / "manifest.json", manifest)
        if name in document["conditions"]:
            document["conditions"][name].update(dataset=str(new), npy_sha256=sha(new / "human.npy"))
    shutil.copytree(source / "shared", output / "shared")
    write_json(output / "study.json", document)
    verify_data(output)


def verify_data(study):
    doc = json.loads((study / "study.json").read_text())
    source = Path(doc["parent_study"])
    parent = json.loads((source / "study.json").read_text())
    assert doc["split_episode_ids"] == parent["split_episode_ids"]
    checks = {}
    for name in (*doc["conditions"], "validation", "test"):
        old, new = source / "datasets" / name, study / "datasets" / name
        a, b = np.load(old / "human.npy"), np.load(new / "human.npy")
        if name in parent["conditions"]:
            assert sha(old / "human.npy") == parent["conditions"][name]["npy_sha256"]
        if name.startswith("official"):
            assert sha(old / "human.npy") == sha(new / "human.npy")
        else:
            np.testing.assert_array_equal(b, adapt_canonical(a))
            assert sha(old / "row_ids.npz") == sha(new / "row_ids.npz")
            np.testing.assert_array_equal(b[..., 1:], a[..., 1:])
        checks[name] = {
            "frames": len(b),
            "sha256": sha(new / "human.npy"),
            "row_ids_unchanged": True,
        }
    for small, large, count in [
        ("quest_1000", "quest_3498", 1000),
        ("quest_3498", "quest_10000", 3498),
    ]:
        np.testing.assert_array_equal(
            np.load(study / "datasets" / small / "human.npy"),
            np.load(study / "datasets" / large / "human.npy")[:count],
        )
    for split in ("validation", "test"):
        assert not set(doc["split_episode_ids"]["train"]) & set(doc["split_episode_ids"][split])
    write_json(study / "dataset_verification.json", checks)
    return checks


def train(study):
    verify_data(study)
    jobs, active = list(CONDITIONS), {}
    while jobs or active:
        for gpu in (0, 1):
            if gpu not in active and jobs:
                name = jobs.pop(0)
                stream = (study / f"{name}_console.txt").open("x")
                process = subprocess.Popen(
                    [
                        str(ROOT / ".venv-geort/bin/python"),
                        str(ROOT / "scripts/geort_data_size_study.py"),
                        "worker",
                        "--study",
                        str(study),
                        "--condition",
                        name,
                    ],
                    env={**os.environ, "CUDA_VISIBLE_DEVICES": str(gpu), "PYTHONUNBUFFERED": "1"},
                    cwd=ROOT,
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                )
                active[gpu] = name, process, stream
                print(f"START {name} GPU {gpu} pid {process.pid}", flush=True)
        for gpu, (name, process, stream) in list(active.items()):
            if process.poll() is not None:
                stream.close()
                if process.returncode:
                    for _, other, _ in active.values():
                        if other.poll() is None:
                            other.terminate()
                    raise RuntimeError(f"Failed {name}; inspect console log")
                del active[gpu]
                print(f"COMPLETE {name}", flush=True)
        time.sleep(1)
    verify(study)


def verify(study):
    verify_data(study)
    doc = json.loads((study / "study.json").read_text())
    old = json.loads((Path(doc["parent_study"]) / "models.json").read_text())
    official = copy.deepcopy(old["official_3498"])
    assert sha(official["checkpoint"]) == official["checkpoint_sha256"]
    official["reuse_policy"] = "Original official-data model reused byte-identically; not retrained"
    models = {"official_3498": official}
    for name in CONDITIONS:
        folder = study / "models" / name
        manifest = json.loads((folder / "run_manifest.json").read_text())
        assert manifest["status"] == "completed"
        assert manifest["input_sha256"] == doc["conditions"][name]["npy_sha256"]
        assert sha(manifest["checkpoint"]) == manifest["checkpoint_sha256"]
        epochs = re.findall(r"^Epoch (\d+) \|", (study / f"{name}_console.txt").read_text(), re.M)
        assert list(map(int, epochs)) == list(range(200))
        q = np.load(folder / "inference_smoke_q.npy")
        assert q.shape == (8, 20) and np.isfinite(q).all()
        assert (
            sha(folder / "checkpoint/fk_model_dg5f_right_geort.pth")
            == doc["shared_robot_cache"]["fk_sha256"]
        )
        assert (
            sha(folder / "data/dg5f_right_geort.npz")
            == doc["shared_robot_cache"]["robot_data_sha256"]
        )
        assert manifest["checkpoint_sha256"] != old[name]["checkpoint_sha256"]
        manifest.update(coordinate_adapter=PROVENANCE, logged_epochs=200)
        write_json(folder / "run_manifest.json", manifest)
        models[name] = manifest
    write_json(study / "models.json", models)
    write_json(
        study / "model_verification.json",
        {
            name: {
                k: m.get(k)
                for k in ("status", "checkpoint_sha256", "logged_epochs", "reuse_policy")
            }
            for name, m in models.items()
        },
    )
    print(f"VERIFIED {study / 'models.json'}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "train", "verify"))
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--source", type=Path, default=ROOT / "results/geort_data_size_20261018")
    args = parser.parse_args()
    study = args.study.resolve()
    if args.command == "prepare":
        prepare(args.source, study)
    elif args.command == "train":
        train(study)
    else:
        verify(study)
