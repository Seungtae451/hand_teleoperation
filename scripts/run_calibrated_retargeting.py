#!/usr/bin/env python3
"""Live entry point selecting the frozen DG-5F calibration profile explicitly."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if __name__ == "__main__":
    from benchmark.experiments.live_retargeting import main

    arguments = sys.argv[1:]
    if not any(arg == "--robot-profile" or arg.startswith("--robot-profile=") for arg in arguments):
        arguments = [
            "--robot-profile",
            str(ROOT / "configs/tesollo_calibrated/profile.json"),
            *arguments,
        ]
    main(arguments)
