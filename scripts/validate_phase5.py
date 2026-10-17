#!/usr/bin/env python3
"""Reproduce Phase 5 on both full public samples and render short previews."""

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

os.environ.setdefault("MUJOCO_GL", "egl")

import numpy as np

from benchmark.datasets.public import audit_samples, catalog, fetch_samples, load_public
from benchmark.experiments.offline_benchmark import main as benchmark
from benchmark.paths import ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--summarize-existing",
        type=Path,
        help="Finalize completed runs without repeating benchmark/rendering",
    )
    args = parser.parse_args()
    folder = (
        args.summarize_existing.resolve()
        if args.summarize_existing
        else Path(tempfile.mkdtemp(prefix="phase5-validation-", dir=ROOT / "results"))
    )
    if args.summarize_existing and not folder.is_dir():
        raise ValueError("Completed results directory does not exist")
    fetch_samples()
    reports, audits, pose_hashes = {}, {}, {}
    for name in catalog():
        frames = list(load_public(name))
        audits[name] = audit_samples(frames)
        pose_hashes[name] = {
            hashlib.sha256(f.joint_positions.tobytes()).hexdigest() for f in frames
        }
        if not args.summarize_existing:
            benchmark(
                ["--dataset", name, "--frames", str(len(frames)), "--output", str(folder / name)]
            )
            benchmark(
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
        reports[name] = json.loads((folder / name / "comparison.json").read_text())
        if reports[name]["input_frames"] != len(frames):
            raise ValueError("Completed run did not select the full dataset")
        if len({m["common_input_stream_sha256"] for m in reports[name]["methods"]}) != 1:
            raise ValueError("Completed methods did not use identical inputs")
        for method in ("manus", "anydex"):
            if not (folder / f"{name}_preview" / f"{method}.mp4").is_file():
                raise ValueError("Rendered preview missing")
    geort = np.array([f.joint_positions for f in load_public("geort_alex")])
    # Compare all frames to the physical lengths listed in the upstream MANUS FK source.
    expected = [
        [0.039, 0.033, 0.021],
        [0.026, 0.022, 0.020],
        [0.026, 0.026, 0.022],
        [0.021, 0.021, 0.020],
        [0.021, 0.021, 0.020],
    ]
    length_error = []
    for i, base in enumerate((1, 5, 9, 13, 17)):
        lengths = np.linalg.norm(np.diff(geort[:, base : base + 4], axis=1), axis=2)
        length_error.append(float(np.max(np.abs(lengths - expected[i]))))
    baseline = Path("/tmp/phase5_existing_sha256.json")
    integrity = None
    if baseline.exists():
        hashes = json.loads(baseline.read_text())
        changed = [
            p
            for p, digest in hashes.items()
            if hashlib.sha256(Path(p).read_bytes()).hexdigest() != digest
        ]
        integrity = {"checked": len(hashes), "changed": changed}
        assert not changed, changed
    source_check = subprocess.run(
        [str(ROOT / ".venv/bin/python"), "scripts/verify_phase5_sources.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    (folder / "upstream_integrity.json").write_text(source_check.stdout)
    a, b = pose_hashes.values()
    report = {
        "phase": 5,
        "output": str(folder),
        "datasets": reports,
        "dataset_audits": audits,
        "exact_cross_dataset_pose_overlap": len(a & b),
        "cross_dataset_subject_overlap": "unknown; participant IDs absent",
        "geort_max_segment_length_error_vs_manus_source_m": max(length_error),
        "existing_file_integrity": integrity,
        "scope": "development-only MANUS and AnyDex; no held-out score or four-method completion",
        "show3d": "official API identified; scene download/adapter is a subsequent dataset task",
    }
    (folder / "validation.json").write_text(json.dumps(report, indent=2) + "\n")
    (ROOT / "results/phase5_validation_latest.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"output": str(folder), "existing_file_integrity": integrity}, indent=2))


if __name__ == "__main__":
    main()
