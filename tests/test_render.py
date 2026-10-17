import os
import subprocess
import sys

import numpy as np
import pytest

from benchmark.simulation.mujoco_runner import MujocoRunner
from benchmark.simulation.visualization import OffscreenRenderer


@pytest.mark.render
def test_actual_mujoco_renderer_produces_robot_pixels_and_motion(robot, tmp_path):
    if not os.environ.get("MUJOCO_GL") and not os.environ.get("DISPLAY"):
        pytest.skip("Set MUJOCO_GL=egl or provide an X display")
    runner = MujocoRunner(robot)
    with OffscreenRenderer(runner.model) as renderer:
        before = renderer.render(runner.data)
        q = np.zeros(20)
        q[5:8] = 0.7
        runner.set_target(q)
        runner.step(500)
        after = renderer.render(runner.data)
    assert before.shape == (480, 640, 3)
    assert before.dtype == np.uint8
    assert np.count_nonzero(before.max(axis=2) > 30) > 3000
    assert np.count_nonzero(np.any(before != after, axis=2)) > 500


@pytest.mark.render
def test_gui_viewer_process_exits_cleanly(model_path, tmp_path):
    if not os.environ.get("DISPLAY"):
        pytest.skip("GUI viewer needs an X display; EGL rendering is tested separately")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "benchmark",
            "demo",
            "--model",
            str(model_path),
            "--duration",
            "0.2",
            "--viewer",
            "--log",
            str(tmp_path / "viewer.jsonl"),
        ],
        env={**os.environ, "MUJOCO_GL": "glfw"},
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
