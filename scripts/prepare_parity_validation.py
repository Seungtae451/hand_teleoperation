#!/usr/bin/env python3
"""Create a separate, explicitly labeled both-hand parity visualization copy."""

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from benchmark.datasets.quest_parity import PROVENANCE, adapt_canonical

    study = ROOT / "results/geort_data_size_parity_20261018"
    source = ROOT / "results/hand_validation_public_20261018.json"
    output = study / "hand_validation_samples.json"
    document = json.loads(source.read_text())
    document.update(
        coordinate_adapter=PROVENANCE,
        parent_samples=str(source),
        role="train_only_visual_diagnosis_with_explicit_empirical_parity_adapter",
    )
    document["source"]["coordinate_frame"] = "canonical parity adapted; world chirality unverified"
    row_ids = np.load(study / "datasets/quest_10000/row_ids.npz")["global_row"]
    train = np.load(study / "datasets/quest_10000/human.npy")
    by_row = dict(zip(row_ids.tolist(), train))
    differences = []
    for clip in document["clips"]:
        clip["label"] += " [parity adapter]"
        for frame in clip["frames"]:
            for hand in ("right", "left"):
                frame[hand] = adapt_canonical(frame[hand]).tolist()
            if frame["global_row"] in by_row:
                differences.append(
                    float(np.max(np.abs(np.array(frame["right"]) - by_row[frame["global_row"]])))
                )
    assert differences and max(differences) < 1e-14
    document["canonical_training_export_max_difference_m"] = max(differences)
    document["training_export_matched_display_frames"] = len(differences)
    with output.open("x") as stream:
        json.dump(document, stream, allow_nan=False)
    print(output)


if __name__ == "__main__":
    main()
