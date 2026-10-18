#!/usr/bin/env python3
"""Re-render saved actual qpos from the opposite camera; never rerun retargeting."""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from benchmark.artifacts import save, sha  # noqa: E402
from scripts.export_take_retargeting import LABELS, METHODS  # noqa: E402

CAMERA = {
    "azimuth": 215,
    "elevation": 20,
    "distance": 0.44,
    "lookat": [0.025, 0, 0.145],
    "view": "palm / opposite original viewing direction",
    "render_size": [960, 624],
    "video_frame_size": [960, 720],
    "caption_policy": "96-pixel header outside the rendered viewport",
}


def render_method(source, output, method):
    import imageio.v2 as imageio
    import mujoco
    from PIL import Image, ImageDraw, ImageFont

    from benchmark.simulation.robot_model import RobotModel
    from benchmark.simulation.visualization import OffscreenRenderer

    robot = RobotModel()
    robot.model.vis.global_.offwidth = 960
    robot.model.vis.global_.offheight = 720
    data = mujoco.MjData(robot.model)
    states = np.load(source / f"{method}_states.npz")
    assert states["actual"].shape[1] == 20 and np.isfinite(states["actual"]).all()
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 32)
    small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
    with (
        OffscreenRenderer(robot.model, width=960, height=624) as renderer,
        imageio.get_writer(
            str(output / f"{method}.mp4"), fps=25, codec="libx264", quality=8
        ) as video,
    ):
        renderer.camera.azimuth = CAMERA["azimuth"]
        renderer.camera.elevation = CAMERA["elevation"]
        renderer.camera.distance = CAMERA["distance"]
        renderer.camera.lookat[:] = CAMERA["lookat"]
        for tick in range(0, len(states["actual"]), 2):
            # No clipping, optimization or physical stepping: replay the recorded measured state.
            data.qpos[robot.qpos_indices] = states["actual"][tick]
            mujoco.mj_forward(robot.model, data)
            image = Image.new("RGB", (960, 720), "#101827")
            image.paste(Image.fromarray(renderer.render(data)), (0, 96))
            draw = ImageDraw.Draw(image)
            draw.rectangle((0, 0, 960, 96), fill="#101827")
            draw.text((18, 10), LABELS[method], font=font, fill="white")
            status = str(states["status"][tick])
            draw.text(
                (18, 56),
                f"t={states['time_s'][tick]:06.2f}s  {status} | PALM",
                font=small,
                fill="#9fe5c0" if status == "TRACKING" else "#ffd080",
            )
            video.append_data(np.asarray(image))
    print(f"DONE {method}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--method", choices=METHODS)
    args = parser.parse_args()
    args.source, args.output = args.source.resolve(), args.output.resolve()
    if args.method:
        render_method(args.source, args.output, args.method)
        return
    run = json.loads((args.source / "run.json").read_text())
    if run["state"] != "completed" or not run["same_input_digest_verified"]:
        raise ValueError("Require a completed common-input replay")
    args.output.mkdir(parents=True, exist_ok=False)
    copies = ["summaries.json"]
    for method in METHODS:
        copies.extend([f"{method}_states.npz", f"{method}_summary.json"])
    for name in copies:
        shutil.copyfile(args.source / name, args.output / name)
    save(
        args.output / "run.json",
        {
            **run,
            "state": "rendering",
            "camera": CAMERA,
            "render_state": "saved_actual_qpos",
            "retargeting_rerun": False,
            "source_replay": str(args.source),
        },
    )
    workers = []
    try:
        for method in METHODS:
            stream = (args.output / f"{method}_render.log").open("x")
            process = subprocess.Popen(
                [
                    sys.executable,
                    __file__,
                    "--source",
                    str(args.source),
                    "--output",
                    str(args.output),
                    "--method",
                    method,
                ],
                env={**os.environ, "MUJOCO_GL": "egl"},
                stdout=stream,
                stderr=subprocess.STDOUT,
            )
            workers.append((method, process, stream))
        for method, process, _ in workers:
            if process.wait():
                raise RuntimeError(f"Camera rendering failed: {method}")
        hashes = {name: sha(args.source / name) for name in copies}
        assert all(sha(args.output / name) == digest for name, digest in hashes.items())
        save(
            args.output / "camera_verification.json",
            {
                "camera": CAMERA,
                "original_camera": {"azimuth": 35, "elevation": -20},
                "actual_states_and_metrics_byte_identical": True,
                "source_hashes": hashes,
                "no_optimization_no_dynamics_no_output_clipping": True,
            },
        )
        rendered = json.loads((args.output / "run.json").read_text())
        save(args.output / "run.json", {**rendered, "state": "completed"})
        print("Palm videos complete; original states and metrics unchanged", flush=True)
    finally:
        for _, process, stream in workers:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=15)
            stream.close()


if __name__ == "__main__":
    main()
