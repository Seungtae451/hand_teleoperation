#!/usr/bin/env python3
"""Fetch pinned, sparse upstream checkouts. Existing checkouts are only verified."""

import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def git(path, *args):
    return subprocess.check_output(["git", "-C", str(path), *args], text=True).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", nargs="+", help="Fetch selected repository names")
    args = parser.parse_args()
    repos = json.loads((ROOT / "external_repositories.lock.json").read_text())["repositories"]
    names = {r["name"] for r in repos}
    if args.only and set(args.only) - names:
        parser.error(f"Unknown repositories: {set(args.only) - names}")
    for repo in repos:
        if args.only and repo["name"] not in args.only:
            continue
        path = ROOT / "external" / repo["name"]
        if path.exists():
            if not (path / ".git").exists():
                raise RuntimeError(f"Refusing to overwrite existing non-Git directory: {path}")
            if git(path, "status", "--porcelain"):
                raise RuntimeError(f"Upstream checkout has local changes; left untouched: {path}")
            if git(path, "rev-parse", "HEAD") != repo["revision"]:
                raise RuntimeError(f"Different revision; existing checkout left untouched: {path}")
            print(f"Verified {repo['name']} @ {repo['revision']}")
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "--filter=blob:none",
                "--no-checkout",
                repo["url"],
                str(path),
            ],
            check=True,
        )
        git(path, "fetch", "--depth", "1", "origin", repo["revision"])
        git(path, "sparse-checkout", "init", "--cone")
        git(path, "sparse-checkout", "set", *repo["sparse_paths"])
        git(path, "checkout", "--detach", repo["revision"])
        print(f"Fetched {repo['name']} @ {repo['revision']}")


if __name__ == "__main__":
    main()
