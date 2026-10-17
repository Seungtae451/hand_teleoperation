#!/usr/bin/env python3
"""Compare the four data-size GeoRT checkpoints using one Quest connection."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if __name__ == "__main__":
    from benchmark.experiments.live_retargeting import main

    arguments = sys.argv[1:]
    if not any(arg == "--geort-study" or arg.startswith("--geort-study=") for arg in arguments):
        arguments = [
            "--geort-study",
            str(ROOT / "results/geort_data_size_20261018/models.json"),
            *arguments,
        ]
    main(arguments)
