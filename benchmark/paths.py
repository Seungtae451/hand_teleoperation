"""Paths for a source checkout (editable installation is the supported workflow)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "configs/tesollo_right.json"
DEFAULT_MODEL = ROOT / "assets/tesollo/generated/dg5f_right.xml"


def writable_output(path: Path) -> Path:
    """Keep upstream sources and the user's original model directory read-only."""
    path = path.resolve()
    for protected in (
        ROOT / "external",
        ROOT / "tesollo_model-main",
        ROOT / ".git",
        ROOT / "PROJECT_SPEC.md",
    ):
        if path == protected or protected in path.parents:
            raise ValueError(f"Output must not be inside upstream source: {protected}")
    return path
