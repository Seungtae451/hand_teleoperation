#!/usr/bin/env python3
"""Read-only verification of upstream revisions, clean checkouts, and original files."""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def verify(include_original=False):
    repositories = json.loads((ROOT / "external_repositories.lock.json").read_text())[
        "repositories"
    ]
    report = {"repositories": {}, "original_files_checked": 0, "problems": []}
    for repo in repositories:
        path = ROOT / "external" / repo["name"]
        if not (path / ".git").exists():
            report["problems"].append(f"Missing repository: {repo['name']}")
            continue
        revision = subprocess.check_output(
            ["git", "-C", str(path), "rev-parse", "HEAD"], text=True
        ).strip()
        status = subprocess.check_output(
            ["git", "-C", str(path), "status", "--porcelain"], text=True
        ).strip()
        ok = revision == repo["revision"] and not status
        report["repositories"][repo["name"]] = {"revision": revision, "clean": not bool(status)}
        if not ok:
            report["problems"].append(f"Changed checkout: {repo['name']}")
    if include_original:
        hashes = json.loads((ROOT / "docs/original_files.sha256.json").read_text())
        for relative, expected in hashes.items():
            path = ROOT / relative
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                report["problems"].append(f"Changed original file: {relative}")
            report["original_files_checked"] += 1
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--original",
        action="store_true",
        help="Also check files present in the initial user workspace",
    )
    args = parser.parse_args()
    report = verify(args.original)
    print(json.dumps(report, indent=2))
    raise SystemExit(bool(report["problems"]))


if __name__ == "__main__":
    main()
