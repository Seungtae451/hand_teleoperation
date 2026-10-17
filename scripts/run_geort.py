#!/usr/bin/env python3
"""Use the project source from either the base environment or isolated GeoRT environment."""

import sys
from pathlib import Path


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from benchmark.geort_support.cli import main as run

    run()


if __name__ == "__main__":
    main()
