#!/usr/bin/env python3
"""Verify pinned upstream sources and the persistent pre-Phase6 project snapshot."""

import hashlib
import json

from verify_phase5_sources import ROOT, phase5_integrity


def main():
    report = phase5_integrity()
    baseline = json.loads((ROOT / "docs/phase6_existing_files.sha256.json").read_text())
    changed = [
        p
        for p, digest in baseline.items()
        if not (ROOT / p).is_file() or hashlib.sha256((ROOT / p).read_bytes()).hexdigest() != digest
    ]
    report["pre_phase6_files"] = {"checked": len(baseline), "changed": changed}
    report["problems"].extend(f"Changed pre-Phase6 file: {p}" for p in changed)
    print(json.dumps(report, indent=2))
    raise SystemExit(bool(report["problems"]))


if __name__ == "__main__":
    main()
