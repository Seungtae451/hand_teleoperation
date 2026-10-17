#!/usr/bin/env python3
"""One Quest source, separate original-method processes and MuJoCo viewers."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmark.experiments.live_retargeting import main

if __name__ == "__main__":
    main()
