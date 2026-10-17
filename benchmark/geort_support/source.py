"""Pinned upstream imports and provenance; no edits, stubs or monkeypatches."""

import ast
import hashlib
import subprocess
import sys
from pathlib import Path

import numpy as np

from benchmark.paths import ROOT

REPOSITORY = ROOT / "external/GeoRT"
COMMIT = "fb2075e2a3272be372016580c0b6ebd6120228f0"


def verify_source():
    revision = subprocess.check_output(
        ["git", "-C", str(REPOSITORY), "rev-parse", "HEAD"], text=True
    ).strip()
    status = subprocess.check_output(
        ["git", "-C", str(REPOSITORY), "status", "--porcelain"], text=True
    ).strip()
    if revision != COMMIT or status:
        raise ValueError("GeoRT source changed; review before running")
    return {
        "repository": "https://github.com/facebookresearch/GeoRT",
        "commit": COMMIT,
        "license": "CC-BY-NC-4.0",
        "source_sha256": {
            str(p.relative_to(REPOSITORY)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (REPOSITORY / "geort").rglob("*.py")
        },
    }


def enable_upstream():
    provenance = verify_source()
    if str(REPOSITORY) not in sys.path:
        sys.path.insert(0, str(REPOSITORY))
    import geort

    if not Path(geort.__file__).resolve().is_relative_to(REPOSITORY):
        raise ValueError("A different GeoRT installation is imported")
    return provenance


def canonical_function():
    """Read the original standalone helper without importing its ROS/MANUS node."""
    verify_source()
    path = REPOSITORY / "geort/mocap/manus_mocap_core.py"
    tree = ast.parse(path.read_bytes(), filename=str(path))
    function = next(
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "hand_to_canonical"
    )
    namespace = {"np": np}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), "exec"), namespace)
    return namespace["hand_to_canonical"]
