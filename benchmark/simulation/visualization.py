"""Viewer and offscreen rendering; import viewer only when explicitly requested."""

import threading
from contextlib import contextmanager

import mujoco
import numpy as np


def configure_camera(camera: mujoco.MjvCamera) -> None:
    camera.lookat[:] = [0.025, 0, 0.145]
    camera.distance = 0.48
    camera.azimuth = 35
    camera.elevation = -20


@contextmanager
def passive_viewer(model, data):
    """Wait for MuJoCo's GUI threads before interpreter/GLFW shutdown on Linux.

    Upstream Handle.close() only requests exit; launch_passive() starts a daemon
    render thread and does not expose a join method. The CLI owns this launch,
    so capture its newly started threads and join them without patching MuJoCo.
    """
    import mujoco.viewer

    previous_threads = set(threading.enumerate())
    handle = mujoco.viewer.launch_passive(model, data)
    owned_threads = set(threading.enumerate()) - previous_threads
    try:
        with handle.lock():
            configure_camera(handle.cam)
        yield handle
    finally:
        handle.close()
        for thread in owned_threads:
            thread.join(timeout=5)
            if thread.is_alive():
                raise RuntimeError("MuJoCo viewer did not finish shutting down within 5 seconds")


class OffscreenRenderer:
    def __init__(self, model: mujoco.MjModel, width: int = 640, height: int = 480):
        self.renderer = mujoco.Renderer(model, height=height, width=width)
        self.camera = mujoco.MjvCamera()
        configure_camera(self.camera)

    def render(self, data: mujoco.MjData) -> np.ndarray:
        self.renderer.update_scene(data, camera=self.camera)
        return self.renderer.render().copy()

    def close(self) -> None:
        self.renderer.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
