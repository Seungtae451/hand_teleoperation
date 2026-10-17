#!/usr/bin/env python3
"""Compare the two locally preserved, small historical public pose shards."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "results/quest_coordinate_provenance_20261018"
OLD = "f96317e96bbc0359f8759efde9ff109cb6ca183f"
NEW = "6c562cea69817ab54e4b80fd2353459d343eba87"
CURRENT = "b5c916d89c771f4a09d5f6d6c59e1dc4f912bb61"


def main():
    paths = [FOLDER / rev / "data/chunk_0001.parquet" for rev in (OLD, NEW)]
    tables = [pq.read_table(path) for path in paths]
    current = pq.read_table(
        ROOT / "data/public/wild_mani_kitchen" / CURRENT / "data/chunk_0001.parquet"
    )
    for key in ("episode_index", "frame_index"):
        assert tables[0][key].to_pylist() == tables[1][key].to_pylist() == current[key].to_pylist()
    report = {
        "source": "https://huggingface.co/datasets/OOJU/wild-mani-kitchen",
        "export_commit": f"https://huggingface.co/datasets/OOJU/wild-mani-kitchen/commit/{NEW}",
        "rows_compared": len(tables[0]),
        "files_sha256": {
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths
        },
        "hands": {},
        "publisher_collection_code_verified": False,
        "conclusion": "Measured export permutation has determinant +1 and preserves chirality. "
        "This alone does not establish old coordinates or prove a publisher bug. "
        "Canonical parity correction is an explicit empirical experiment supported by "
        "user-observed flexion direction and independent geometric diagnostics.",
    }
    for hand in ("right", "left"):
        key = f"observation.{hand}_joint_poses"
        old, new = [np.array(t[key].to_pylist()).reshape(-1, 26, 3) for t in tables]
        np.testing.assert_array_equal(new, np.array(current[key].to_pylist()).reshape(-1, 26, 3))
        np.testing.assert_array_equal(old[..., [2, 0, 1]], new)
        fit = np.linalg.lstsq(
            np.c_[old.reshape(-1, 3), np.ones(old.shape[0] * 26)], new.reshape(-1, 3), rcond=None
        )[0]
        report["hands"][hand] = {
            "old_to_new_row_vector_affine": fit.tolist(),
            "determinant": float(np.linalg.det(fit[:3])),
            "exact_permutation": "new = old[..., [2,0,1]]",
            "current_native_points_unchanged_since_export": True,
        }
    (FOLDER / "history_comparison.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
