"""Small shared helpers for the retained recording and publication pipeline."""

import hashlib
import json
from pathlib import Path

import numpy as np


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def geometry(p):
    """Unchanged PIP/MCP geometry previously embedded in the Allegro audit script."""
    pip, mcp = [], []
    for b in [5, 9, 13]:
        u, v = p[:, b + 1] - p[:, b], p[:, b + 2] - p[:, b + 1]
        pip.append(
            np.degrees(
                np.arccos(
                    np.clip(
                        np.sum(u * v, axis=1)
                        / (np.linalg.norm(u, axis=1) * np.linalg.norm(v, axis=1)),
                        -1,
                        1,
                    )
                )
            )
        )
        mcp.append(np.degrees(np.arctan2(u[:, 0], u[:, 2])))
    return np.array(pip).T, np.array(mcp).T
