"""Command-line entry points for the Phase 2 simulator."""

import argparse
import json
import time
from contextlib import ExitStack, nullcontext
from pathlib import Path

import mujoco
import numpy as np

from benchmark.experiments.logging import SimulationLogger, read_log
from benchmark.experiments.trajectory import demo_target
from benchmark.paths import DEFAULT_CONFIG, DEFAULT_MODEL, ROOT, writable_output
from benchmark.simulation.build_model import build_model
from benchmark.simulation.mujoco_runner import MujocoRunner
from benchmark.simulation.robot_model import RobotModel
from benchmark.simulation.visualization import OffscreenRenderer, passive_viewer


def _outputs(stack, args, runner):
    viewer = None
    if args.viewer:
        viewer = stack.enter_context(passive_viewer(runner.model, runner.data))
    renderer = None
    video = None
    if args.video or args.image:
        renderer = stack.enter_context(OffscreenRenderer(runner.model))
    if args.video:
        import imageio.v2 as imageio

        path = writable_output(args.video)
        path.parent.mkdir(parents=True, exist_ok=True)
        video = stack.enter_context(
            imageio.get_writer(str(path), fps=args.fps, codec="libx264", quality=8)
        )
    return viewer, renderer, video


def _display(args, runner, viewer, renderer, video, deadline):
    if renderer:
        image = renderer.render(runner.data)
        if video:
            video.append_data(image)
        if args.image:
            from PIL import Image

            path = writable_output(args.image)
            path.parent.mkdir(parents=True, exist_ok=True)
            Image.fromarray(image).save(path)
    if viewer:
        viewer.sync()
        if not viewer.is_running():
            return False
        time.sleep(max(0, deadline - time.monotonic()))
    return True


def _summary(runner, sample, frames):
    return {
        "frames": frames,
        "simulation_time_s": sample.time,
        "nq": runner.model.nq,
        "nu": runner.model.nu,
        "final_tracking_error_max_rad": float(np.max(np.abs(sample.q_actual - sample.q_command))),
        "fingertips_actual_world_m": dict(
            zip(runner.robot.fingers, sample.tips_actual_world.tolist())
        ),
        "contacts_enabled": not bool(
            runner.model.opt.disableflags & mujoco.mjtDisableBit.mjDSBL_CONTACT
        ),
    }


def run_demo(args):
    if not np.isfinite(args.duration) or args.duration <= 0 or args.fps <= 0:
        raise ValueError("duration and fps must be positive")
    runner = MujocoRunner(RobotModel(args.model))
    steps = 1 / (args.fps * runner.model.opt.timestep)
    if not np.isclose(steps, round(steps)) or steps < 1:
        raise ValueError("fps must divide the physics frequency (default: 500 Hz)")
    steps = int(round(steps))
    frame_count = round(args.duration * args.fps)
    if frame_count < 1 or not np.isclose(frame_count, args.duration * args.fps):
        raise ValueError("duration must be a positive whole number of control frames")
    fixed_target = None
    if args.joint:
        fixed_target = np.zeros(20)
        for item in args.joint:
            name, value = item.split("=", 1)
            fixed_target[runner.robot.joint_names.index(name)] = float(value)
        runner.robot.validate_target(fixed_target)
    with ExitStack() as stack:
        logger = stack.enter_context(SimulationLogger(args.log, runner.robot, steps))
        viewer, renderer, video = _outputs(stack, args, runner)
        start = time.monotonic()
        for index in range(frame_count):
            target = (
                demo_target((index + 1) / args.fps, args.duration)
                if fixed_target is None
                else fixed_target
            )
            with viewer.lock() if viewer else nullcontext():
                runner.set_target(target)
                sample = runner.step(steps)
            logger.write(sample)
            if not _display(args, runner, viewer, renderer, video, start + (index + 1) / args.fps):
                break
    summary = _summary(runner, sample, index + 1)
    summary["input"] = "synthetic joint commands (not a retargeting algorithm)"
    summary["log"] = str(args.log)
    print(json.dumps(summary, indent=2))


def run_replay(args):
    metadata, rows = read_log(args.input)
    runner = MujocoRunner(RobotModel(args.model))
    if not rows:
        raise ValueError("Cannot replay an empty log")
    if (
        tuple(metadata["joint_names"]) != runner.robot.joint_names
        or metadata["provenance"] != runner.robot.provenance
        or metadata["timestep"] != runner.model.opt.timestep
    ):
        raise ValueError(
            "Replay requires the same joint order, model, controller, and MuJoCo version"
        )
    steps = metadata["control_steps"]
    args.fps = 1 / (steps * runner.model.opt.timestep)
    if args.log.resolve() == args.input.resolve():
        raise ValueError("Replay output must differ from the input log")
    max_error = 0.0
    with ExitStack() as stack:
        logger = stack.enter_context(SimulationLogger(args.log, runner.robot, steps))
        viewer, renderer, video = _outputs(stack, args, runner)
        start = time.monotonic()
        for index, row in enumerate(rows):
            with viewer.lock() if viewer else nullcontext():
                runner.set_target(row["q_target"], clip=True)
                sample = runner.step(steps)
            logger.write(sample)
            max_error = max(
                max_error, float(np.max(np.abs(sample.q_actual - np.array(row["q_actual"]))))
            )
            if not _display(args, runner, viewer, renderer, video, start + (index + 1) / args.fps):
                break
    summary = _summary(runner, sample, index + 1)
    summary["replay_max_q_difference_rad"] = max_error
    print(json.dumps(summary, indent=2))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="Build a derived MJCF without editing upstream files")
    build.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    build.add_argument("--output", type=Path, default=DEFAULT_MODEL)
    inspect = sub.add_parser("inspect", help="Print actual joint order, limits, and zero-pose FK")
    inspect.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    demo = sub.add_parser("demo", help="Run synthetic joint commands using position actuators")
    demo.add_argument("--duration", type=float, default=4.0)
    demo.add_argument("--fps", type=int, default=50)
    demo.add_argument("--joint", action="append", help="Hold a joint at NAME=RADIANS (repeatable)")
    replay = sub.add_parser("replay", help="Replay recorded joint commands from a reset state")
    replay.add_argument("input", type=Path)
    for command, default_log in ((demo, "demo.jsonl"), (replay, "replay.jsonl")):
        command.add_argument("--model", type=Path, default=DEFAULT_MODEL)
        command.add_argument("--log", type=Path, default=ROOT / "results" / default_log)
        command.add_argument("--viewer", action="store_true")
        command.add_argument("--video", type=Path)
        command.add_argument("--image", type=Path, help="Write the latest rendered frame as PNG")
    args = parser.parse_args(argv)
    if args.command == "build":
        print(build_model(args.config, args.output))
    elif args.command == "inspect":
        robot = RobotModel(args.model)
        print(
            json.dumps(
                {
                    "joint_names": robot.joint_names,
                    "limits_rad": robot.limits.tolist(),
                    "fingers": robot.fingers,
                    "zero_tips_world_m": robot.forward_kinematics(np.zeros(20)).tolist(),
                    "source_commit": robot.provenance["source_commit"],
                },
                indent=2,
            )
        )
    elif args.command == "demo":
        run_demo(args)
    elif args.command == "replay":
        run_replay(args)


if __name__ == "__main__":
    main()
