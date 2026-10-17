#!/usr/bin/env python3
"""Export real public training windows for visual inspection; no pose synthesis."""

import json
import sys
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from benchmark.geort_support.source import canonical_function

    study = ROOT / "results/geort_data_size_20261018"
    document = json.loads((study / "study.json").read_text())
    source = ROOT / "data/public/wild_mani_kitchen" / document["quest_source"]["revision"]
    p = np.load(study / "datasets/quest_10000/human.npy", allow_pickle=False)
    ids = np.load(study / "datasets/quest_10000/row_ids.npz", allow_pickle=False)
    bends = []
    for base in (5, 9, 13, 17):
        u, v = p[:, base + 1] - p[:, base], p[:, base + 2] - p[:, base + 1]
        cosine = (u * v).sum(1) / (np.linalg.norm(u, axis=1) * np.linalg.norm(v, axis=1))
        bends.append(np.degrees(np.arccos(np.clip(cosine, -1, 1))))
    bends = np.mean(bends, axis=0)
    selections = [
        ("open_candidate", "펼친 손 후보", int(np.argmin(bends))),
        ("flexed_candidate", "최대 굴곡 후보", int(np.argmax(bends))),
    ]
    for finger, tip in zip(("index", "middle", "ring", "pinky"), (8, 12, 16, 20)):
        selections.append(
            (
                f"pinch_{finger}",
                f"엄지–{finger} 최단 거리 후보",
                int(np.argmin(np.linalg.norm(p[:, 4] - p[:, tip], axis=1))),
            )
        )
    table = pq.read_table(
        sorted((source / "data").glob("chunk_*.parquet")),
        columns=[
            "episode_index",
            "frame_index",
            "observation.right_joint_poses",
            "observation.left_joint_poses",
            "observation.action_label",
        ],
    )
    episodes = np.array(table["episode_index"].to_pylist())
    frame_ids = np.array(table["frame_index"].to_pylist())
    native = {
        side: np.array(table[f"observation.{side}_joint_poses"].to_pylist()).reshape(-1, 26, 3)
        for side in ("right", "left")
    }
    labels = table["observation.action_label"].to_pylist()
    common = document["quest_source"]["native_to_common21"]
    canonical = canonical_function()
    clips, max_error = [], 0.0
    for key, label, index in selections:
        row = int(ids["global_row"][index])
        assert int(episodes[row]) in document["split_episode_ids"]["train"]
        max_error = max(
            max_error, float(np.max(np.abs(canonical(native["right"][row, common]) - p[index])))
        )
        rows = np.flatnonzero(
            (episodes == episodes[row]) & (np.abs(frame_ids - frame_ids[row]) <= 30)
        )
        clip = {
            "id": key,
            "label": label,
            "episode": int(episodes[row]),
            "center_frame": int(frame_ids[row]),
            "center_index": int(np.flatnonzero(rows == row)[0]),
            "frames": [],
        }
        for current in rows:
            clip["frames"].append(
                {
                    "frame_index": int(frame_ids[current]),
                    "action_label": labels[current],
                    "global_row": int(current),
                    **{side: canonical(native[side][current, common]).tolist() for side in native},
                }
            )
        clips.append(clip)
    assert max_error < 1e-7
    result = {
        "schema": "hand_validation_public_v1",
        "source": document["quest_source"],
        "role": "train_only_visual_diagnosis",
        "fps": 30,
        "canonical_training_export_max_difference_m": max_error,
        "left_note": "Left is displayed using the same geometric axis construction "
        "for comparison; never retargeted as right",
        "labels_note": "Automatically selected geometric candidates, not verified gesture labels",
        "clips": clips,
    }
    target = ROOT / "results/hand_validation_public_20261018.json"
    with target.open("x") as stream:
        json.dump(result, stream, allow_nan=False)
    print(
        json.dumps(
            {"output": str(target), "clips": len(clips), "training_export_difference_m": max_error},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
