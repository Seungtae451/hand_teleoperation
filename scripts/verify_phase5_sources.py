#!/usr/bin/env python3
"""Check upstream/assets, recognizing the user's authorized specification append."""

import hashlib
import json
from pathlib import Path

from verify_sources import ROOT, verify


def phase5_integrity():
    report = verify(include_original=False)
    hashes = json.loads((ROOT / "docs/original_files.sha256.json").read_text())
    report["original_files_checked"] = len(hashes)
    report["authorized_spec_append"] = False
    for relative, digest in hashes.items():
        path = ROOT / relative
        if not path.is_file():
            report["problems"].append(f"Missing original file: {relative}")
            continue
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() == digest:
            continue
        if relative == "PROJECT_SPEC.md":
            marker = content.find(b"## 17. Additional Task")
            if marker > 0:
                # Append follows a Markdown separator. Verify the entire original
                # prefix against its original digest, preserving trailing newlines.
                sep = content.rfind(b"---", 0, marker)
                candidates = range(max(0, sep - 4), sep + 1)
                if any(hashlib.sha256(content[:i]).hexdigest() == digest for i in candidates):
                    report["authorized_spec_append"] = True
                    continue
        report["problems"].append(f"Changed original file: {relative}")
    baseline = Path("/tmp/phase5_existing_sha256.json")
    if baseline.exists():
        existing = json.loads(baseline.read_text())
        changed = [
            p
            for p, d in existing.items()
            if hashlib.sha256((ROOT / p).read_bytes()).hexdigest() != d
        ]
        report["phase5_existing_files"] = {"checked": len(existing), "changed": changed}
        report["problems"].extend(f"Changed pre-Phase5 file: {p}" for p in changed)
    return report


def main():
    report = phase5_integrity()
    print(json.dumps(report, indent=2))
    raise SystemExit(bool(report["problems"]))


if __name__ == "__main__":
    main()
