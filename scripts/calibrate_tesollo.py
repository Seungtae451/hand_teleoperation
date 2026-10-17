#!/usr/bin/env python3
"""Generate a separate frozen robot profile from a recorded open-hand candidate."""

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmark.retargeting.tesollo_calibration import build_profile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument(
        "--output", type=Path, required=True, help="new directory, never overwrites"
    )
    parser.add_argument("--seconds", type=float, default=5.0)
    args = parser.parse_args()
    if not math.isfinite(args.seconds) or args.seconds < 1:
        parser.error("seconds must be finite and >=1")
    path, profile = build_profile(args.input, args.output, args.seconds)
    print(
        json.dumps(
            {
                "profile": str(path),
                "calibration": {
                    key: value
                    for key, value in profile["calibration"].items()
                    if key != "selected_right_frame_indices"
                },
                "anydex": profile["methods"]["anydex"]["config"]["retarget"],
                "wuji": profile["methods"]["wuji"]["config"]["retarget"],
                "fk_audit": profile["fk_audit"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
