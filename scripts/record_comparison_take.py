#!/usr/bin/env python3
"""Record a Quest comparison take; see README_VIDEO_CAPTURE.md."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmark.tracking.video_capture import main  # noqa: E402

if __name__ == "__main__":
    main()
