#!/usr/bin/env python3
"""Read-only model evaluation with project-owned reports and videos."""

import sys
from pathlib import Path


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from benchmark.experiments.trained_geort_evaluation import main as run

    run()


if __name__ == "__main__":
    main()
