#!/usr/bin/env python3
"""Reproducible public-data subsets and four independent, original GeoRT trainings."""

import argparse
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SEED = 20261018
REVISION = "b5c916d89c771f4a09d5f6d6c59e1dc4f912bb61"
NATIVE_INDICES = [1, 2, 3, 4, 5, 7, 8, 9, 10, 12, 13, 14, 15, 17, 18, 19, 20, 22, 23, 24, 25]
CONDITIONS = ("official_3498", "quest_1000", "quest_3498", "quest_10000")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def prepare(output):
    import pyarrow.parquet as pq

    from benchmark.geort_support.input import INPUT_CONTRACT, canonical_points
    from benchmark.paths import writable_output
    from benchmark.tracking.hand_frame import HandFrame

    output = writable_output(output)
    output.mkdir(parents=True, exist_ok=False)
    workspace = ROOT / "results/geort_dg5f_workspace"
    source = ROOT / "data/public/wild_mani_kitchen" / REVISION
    audit = json.loads((ROOT / "results/public_quest_audit.json").read_text())
    for relative, expected in audit["files_sha256"].items():
        if sha(source / relative) != expected:
            raise ValueError(f"Pinned public source changed: {relative}")
    table = pq.read_table(sorted((source / "data").glob("chunk_*.parquet")))
    index = pq.read_table(source / "meta/episode_index.parquet").to_pylist()
    native = np.asarray(table["observation.right_joint_poses"].to_pylist()).reshape(-1, 26, 3)
    wrists = np.asarray(table["observation.right_state"].to_pylist())
    episodes = np.asarray(table["episode_index"].to_pylist())
    frame_ids = np.asarray(table["frame_index"].to_pylist())
    rng = np.random.default_rng(SEED)
    split_episodes = {"train": [], "validation": [], "test": []}
    for task in sorted({row["task"] for row in index}):
        ids = np.array(sorted(row["episode_index"] for row in index if row["task"] == task))
        rng.shuffle(ids)
        n_train, n_val = round(len(ids) * 0.70), round(len(ids) * 0.15)
        for split, values in zip(
            split_episodes, (ids[:n_train], ids[n_train : n_train + n_val], ids[n_train + n_val :])
        ):
            split_episodes[split].extend(int(i) for i in values)
    # Deduplicate exact world skeletons globally before assigning row pools.
    _, first_indices = np.unique(
        native[:, NATIVE_INDICES].reshape(len(native), -1), axis=0, return_index=True
    )
    eligible = np.zeros(len(native), dtype=bool)
    eligible[first_indices] = True
    pools = {
        split: np.flatnonzero(eligible & np.isin(episodes, ids))
        for split, ids in split_episodes.items()
    }
    all_rows = np.concatenate(list(pools.values()))
    assert len(np.unique(all_rows)) == len(all_rows) == len(first_indices)
    # Randomized round-robin across episodes keeps every task/episode represented at every N.
    queues = []
    order = rng.permutation(split_episodes["train"])
    for episode in order:
        rows = pools["train"][episodes[pools["train"]] == episode].copy()
        rng.shuffle(rows)
        queues.append(rows.tolist())
    sampling_order = []
    for position in range(max(map(len, queues))):
        sampling_order.extend(queue[position] for queue in queues if position < len(queue))
    if len(sampling_order) < 10000:
        raise ValueError("Insufficient independent training rows")
    canonical = np.empty((len(native), 21, 3), dtype=np.float64)
    for row in range(len(native)):
        frame = HandFrame(
            timestamp=float(frame_ids[row]) / 30,
            handedness="right",
            joint_positions=native[row, NATIVE_INDICES],
            wrist_position=wrists[row, :3],
            wrist_rotation=wrists[row, 3:],
            tracking_valid=True,
            coordinate_frame="world_rh",
            timestamp_domain="assumed_frame_index_30hz",
            metadata={
                "source": "OOJU/wild-mani-kitchen",
                "revision": REVISION,
                "episode_index": int(episodes[row]),
                "frame_index": int(frame_ids[row]),
                "units": "m",
                "native_frame": "FLU right-handed",
                "tracking_validity_policy": "geometry only; SDK confidence unavailable",
            },
        )
        canonical[row] = canonical_points(frame)
    all_manifest = {
        "schema": "geort_data_size_study_v1",
        "seed": SEED,
        "quest_source": {
            "dataset": "OOJU/wild-mani-kitchen",
            "revision": REVISION,
            "files_sha256": audit["files_sha256"],
            "license": "Apache-2.0",
            "tracking": "Quest 3 hand tracking as declared by publisher; no SDK version given",
            "coordinate_frame": "FLU, right-handed; units validated by geometry as meters",
            "native_to_common21": NATIVE_INDICES,
            "invalid_geometry_frames": 0,
            "raw_rows": len(native),
            "exact_world_duplicates_removed": len(native) - len(first_indices),
        },
        "split_episode_ids": {k: sorted(v) for k, v in split_episodes.items()},
        "split_rows": {k: len(v) for k, v in pools.items()},
        "participant_disjoint_verified": False,
        "split_policy": "task-stratified 70/15/15 by episode, rounded within each task; "
        "same episode never crosses splits; participant identity unavailable",
        "subset_policy": "seeded per-episode shuffle, round-robin across training episodes; "
        "nested 1000 subset 3498 subset 10000; no hand-size scaling or augmentation",
        "own_quest_recordings_used": False,
        "robot_workspace": str(workspace),
        "robot_config_sha256": sha(workspace / "config.json"),
        "conditions": {},
    }
    for split in ("validation", "test"):
        folder = output / "datasets" / split
        folder.mkdir(parents=True)
        rows = pools[split]
        np.save(folder / "human.npy", canonical[rows])
        np.savez(
            folder / "row_ids.npz", global_row=rows, episode=episodes[rows], frame=frame_ids[rows]
        )
    official = ROOT / "data/public/geort/human_alex.npy"
    expected = json.loads((ROOT / "configs/public_datasets.json").read_text())["geort_alex"]
    assert sha(official) == expected["sha256"]
    for condition in CONDITIONS:
        folder = output / "datasets" / condition
        folder.mkdir(parents=True)
        if condition.startswith("official"):
            shutil.copyfile(official, folder / "human.npy")
            size = 3498
            origin = {
                "dataset": "facebookresearch/GeoRT",
                "source_sha256": sha(official),
                "license": expected["license"],
                "tracking": expected["tracking_method"],
            }
        else:
            size = int(condition.split("_")[1])
            rows = np.array(sampling_order[:size])
            np.save(folder / "human.npy", canonical[rows])
            np.savez(
                folder / "row_ids.npz",
                global_row=rows,
                episode=episodes[rows],
                frame=frame_ids[rows],
            )
            assert not np.intersect1d(
                rows, np.concatenate([pools["validation"], pools["test"]])
            ).size
            origin = all_manifest["quest_source"]
        manifest = {
            "schema": "geort_human_input_v1",
            "split": "train",
            "input_contract": INPUT_CONTRACT,
            "frames": size,
            "npy_sha256": sha(folder / "human.npy"),
            "source": origin,
            "condition": condition,
            "own_quest_recordings_used": False,
        }
        write_json(folder / "manifest.json", manifest)
        all_manifest["conditions"][condition] = {
            "frames": size,
            "dataset": str(folder),
            "npy_sha256": manifest["npy_sha256"],
        }
    # Cache is robot-only: prior FK optimization never used a human dataset.
    old = workspace / "training-2glhel2r"
    fk = old / "checkpoint/fk_model_dg5f_right_geort.pth"
    robot_data = old / "data/dg5f_right_geort.npz"
    shared = output / "shared"
    shared.mkdir()
    shutil.copyfile(fk, shared / fk.name)
    shutil.copyfile(robot_data, shared / robot_data.name)
    all_manifest["shared_robot_cache"] = {
        "fk_sha256": sha(fk),
        "robot_data_sha256": sha(robot_data),
        "provenance": "robot-only 100000 URDF kinematic samples and "
        "original 200-epoch FK training; "
        "reused identically for all four conditions; no human poses used for FK training",
    }
    write_json(output / "study.json", all_manifest)
    print(
        json.dumps(
            {
                "study": str(output),
                "split_rows": all_manifest["split_rows"],
                "split_episode_counts": {k: len(v) for k, v in split_episodes.items()},
                "conditions": all_manifest["conditions"],
            },
            indent=2,
        ),
        flush=True,
    )


def train_worker(study, condition):
    from benchmark.geort_support.runtime import load_workspace
    from benchmark.geort_support.source import enable_upstream

    document = json.loads((study / "study.json").read_text())
    _, config = load_workspace(document["robot_workspace"])
    if sha(Path(document["robot_workspace"]) / "config.json") != document["robot_config_sha256"]:
        raise ValueError("Robot config changed")
    dataset = Path(document["conditions"][condition]["dataset"]) / "human.npy"
    if sha(dataset) != document["conditions"][condition]["npy_sha256"]:
        raise ValueError("Input hash changed")
    points = np.load(dataset, allow_pickle=False)
    assert points.shape == (document["conditions"][condition]["frames"], 21, 3)
    assert np.isfinite(points).all() and np.allclose(points[:, 0], 0, atol=1e-7)
    provenance = enable_upstream()
    import torch
    from geort.trainer import GeoRTTrainer

    if not torch.cuda.is_available():
        raise RuntimeError("Original trainer requires CUDA")
    run = study / "models" / condition
    run.mkdir(parents=True, exist_ok=False)
    for relative in ("checkpoint/fk_model_dg5f_right_geort.pth", "data/dg5f_right_geort.npz"):
        destination = run / relative
        destination.parent.mkdir(exist_ok=True)
        shutil.copyfile(study / "shared" / destination.name, destination)
    random.seed(SEED)
    np.random.seed(SEED)
    torch.manual_seed(SEED)
    torch.cuda.manual_seed_all(SEED)
    manifest = {
        "condition": condition,
        "status": "training",
        "seed": SEED,
        "input_sha256": sha(dataset),
        "input_frames": len(points),
        "ik_epochs": 200,
        "shared_robot_cache": document["shared_robot_cache"],
        "upstream": provenance,
        "gpu": torch.cuda.get_device_name(0),
        "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
        "own_quest_recordings_used": False,
    }
    write_json(run / "run_manifest.json", manifest)
    started = time.monotonic()
    os.chdir(run)
    try:
        GeoRTTrainer(config).train(dataset)  # Original defaults, new IK weights, no fine-tuning.
        checkpoint_dirs = [
            p for p in (run / "checkpoint").iterdir() if p.is_dir() and not p.name.endswith("_last")
        ]
        assert len(checkpoint_dirs) == 1
        checkpoint = checkpoint_dirs[0]
        assert (checkpoint / "epoch_199.pth").is_file()
        assert len(list(checkpoint.glob("epoch_*.pth"))) == 200
        assert (
            sha(run / "checkpoint/fk_model_dg5f_right_geort.pth")
            == document["shared_robot_cache"]["fk_sha256"]
        )
        # Verify actual CUDA inference, finite 20-joint output and official bounds.
        from benchmark.retargeting.geort import GeoRTRetargeter
        from benchmark.simulation.robot_model import RobotModel
        from benchmark.tracking.hand_frame import HandFrame

        robot = RobotModel()
        adapter = GeoRTRetargeter(
            robot, checkpoint=checkpoint / "last.pth", config_path=checkpoint / "config.json"
        )
        outputs = []
        for i in np.linspace(0, len(points) - 1, 8, dtype=int):
            frame = HandFrame(
                float(len(outputs)),
                "right",
                points[i],
                np.zeros(3),
                np.array([0, 0, 0, 1]),
                True,
                coordinate_frame="wrist_rh",
            )
            outputs.append(adapter.retarget(frame).q_target)
        np.save(run / "inference_smoke_q.npy", outputs)
        shutil.copyfile(checkpoint / "last.pth", run / "model.pth")
        shutil.copyfile(checkpoint / "config.json", run / "config.json")
        manifest.update(
            status="completed",
            elapsed_s=time.monotonic() - started,
            checkpoint=str(run / "model.pth"),
            config=str(run / "config.json"),
            checkpoint_sha256=sha(checkpoint / "last.pth"),
            inference_smoke_finite_8x20=True,
        )
    except BaseException as error:
        manifest.update(status="failed", error=repr(error), elapsed_s=time.monotonic() - started)
        raise
    finally:
        write_json(run / "run_manifest.json", manifest)
    print(json.dumps(manifest), flush=True)


def launch(study):
    # Two independent workers, one per GPU; each trains two conditions in sequence.
    jobs = [("official_3498", 0), ("quest_1000", 1), ("quest_3498", 0), ("quest_10000", 1)]
    active, completed = {}, []
    while jobs or active:
        for gpu in (0, 1):
            if gpu in active:
                continue
            candidate = next(((name, device) for name, device in jobs if device == gpu), None)
            if candidate:
                name, _ = candidate
                jobs.remove(candidate)
                stream = (study / f"{name}_console.txt").open("x")
                env = {**os.environ, "CUDA_VISIBLE_DEVICES": str(gpu), "PYTHONUNBUFFERED": "1"}
                process = subprocess.Popen(
                    [
                        str(ROOT / ".venv-geort/bin/python"),
                        __file__,
                        "worker",
                        "--study",
                        str(study),
                        "--condition",
                        name,
                    ],
                    env=env,
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                    cwd=ROOT,
                )
                active[gpu] = name, process, stream
                print(f"START {name} on GPU {gpu}, pid={process.pid}", flush=True)
        for gpu, (name, process, stream) in list(active.items()):
            if process.poll() is not None:
                stream.close()
                if process.returncode:
                    for _, other, _ in active.values():
                        if other.poll() is None:
                            other.terminate()
                    raise RuntimeError(
                        f"Training failed: {name}; inspect {study}/{name}_console.txt"
                    )
                completed.append(name)
                del active[gpu]
                print(f"COMPLETE {name}", flush=True)
        time.sleep(1)
    models = {
        name: json.loads((study / "models" / name / "run_manifest.json").read_text())
        for name in CONDITIONS
    }
    assert all(model["status"] == "completed" for model in models.values())
    write_json(study / "models.json", models)
    print(f"All four models completed: {study}/models.json", flush=True)


def verify(study):
    document = json.loads((study / "study.json").read_text())
    episode_sets = {name: set(ids) for name, ids in document["split_episode_ids"].items()}
    for a, b in (("train", "validation"), ("train", "test"), ("validation", "test")):
        assert not episode_sets[a] & episode_sets[b]
    arrays = {}
    for name, info in document["conditions"].items():
        folder = Path(info["dataset"])
        assert sha(folder / "human.npy") == info["npy_sha256"]
        points = np.load(folder / "human.npy", allow_pickle=False)
        assert points.shape == (info["frames"], 21, 3) and np.isfinite(points).all()
        assert np.max(np.abs(points[:, 0])) < 1e-7
        if name.startswith("quest"):
            arrays[name] = points
            ids = np.load(folder / "row_ids.npz", allow_pickle=False)
            assert set(ids["episode"].tolist()) == episode_sets["train"]
    np.testing.assert_array_equal(arrays["quest_1000"], arrays["quest_3498"][:1000])
    np.testing.assert_array_equal(arrays["quest_3498"], arrays["quest_10000"][:3498])
    for split in ("validation", "test"):
        ids = np.load(study / "datasets" / split / "row_ids.npz", allow_pickle=False)
        assert set(ids["episode"].tolist()) == episode_sets[split]
    models, checks = {}, {}
    for condition in CONDITIONS:
        run = study / "models" / condition
        manifest = json.loads((run / "run_manifest.json").read_text())
        if manifest["status"] != "completed":
            raise ValueError(f"Training incomplete: {condition}")
        log = (study / f"{condition}_console.txt").read_text()
        epochs = [int(v) for v in re.findall(r"^Epoch (\d+) \|", log, flags=re.MULTILINE)]
        assert epochs == list(range(200))
        source_checkpoint = Path(manifest["checkpoint"])
        source_config = Path(manifest["config"])
        stable_checkpoint, stable_config = run / "model.pth", run / "config.json"
        if source_checkpoint != stable_checkpoint:
            shutil.copyfile(source_checkpoint, stable_checkpoint)
        if source_config != stable_config:
            shutil.copyfile(source_config, stable_config)
        assert sha(stable_checkpoint) == manifest["checkpoint_sha256"]
        assert (
            sha(run / "checkpoint/fk_model_dg5f_right_geort.pth")
            == document["shared_robot_cache"]["fk_sha256"]
        )
        assert (
            sha(run / "data/dg5f_right_geort.npz")
            == document["shared_robot_cache"]["robot_data_sha256"]
        )
        q = np.load(run / "inference_smoke_q.npy", allow_pickle=False)
        assert q.shape == (8, 20) and np.isfinite(q).all()
        manifest.update(checkpoint=str(stable_checkpoint), config=str(stable_config))
        write_json(run / "run_manifest.json", manifest)
        models[condition] = manifest
        checks[condition] = {
            "logged_epochs": len(epochs),
            "final_epoch": epochs[-1],
            "checkpoint_sha256": sha(stable_checkpoint),
            "shared_fk_unchanged": True,
            "shared_robot_data_unchanged": True,
            "inference_smoke_shape": list(q.shape),
        }
    assert len({v["checkpoint_sha256"] for v in models.values()}) == 4
    write_json(study / "models.json", models)
    write_json(study / "model_verification.json", checks)
    print(json.dumps(checks, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "train", "worker", "verify"))
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--condition", choices=CONDITIONS)
    args = parser.parse_args()
    study = args.study.resolve()
    if args.command == "prepare":
        prepare(study)
    elif args.command == "train":
        launch(study)
    elif args.command == "verify":
        verify(study)
    else:
        train_worker(study, args.condition)
