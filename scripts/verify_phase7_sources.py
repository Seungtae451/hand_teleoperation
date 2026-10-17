#!/usr/bin/env python3
"""Check upstream revisions and every existing project file from before Phase 7."""

import hashlib
import json

from verify_phase5_sources import ROOT, phase5_integrity


def main():
    report = phase5_integrity()
    hashes = json.loads((ROOT / "docs/phase7_existing_files.sha256.json").read_text())
    changed = [
        p
        for p, d in hashes.items()
        if not (ROOT / p).is_file() or hashlib.sha256((ROOT / p).read_bytes()).hexdigest() != d
    ]
    report["pre_phase7_files"] = {"checked": len(hashes), "changed": changed}
    report["problems"].extend(f"Changed pre-Phase7 file: {p}" for p in changed)
    print(json.dumps(report, indent=2))
    raise SystemExit(bool(report["problems"]))


if __name__ == "__main__":
    main()
