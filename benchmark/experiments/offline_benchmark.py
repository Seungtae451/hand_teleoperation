"""Common-input offline runs: preserve upstream outputs separately from common control."""

import argparse
import hashlib
import json
import tempfile
import time
from contextlib import ExitStack
from pathlib import Path

import numpy as np

from benchmark.datasets.public import (
    audit_samples,
    audit_split_overlap,
    catalog,
    fetch_samples,
    load_public,
    write_frames,
)
from benchmark.experiments.manus_control import ManusController
from benchmark.paths import ROOT
from benchmark.retargeting.manus import DEFAULT_MANUS_CONFIG
from benchmark.simulation.robot_model import RobotModel
from benchmark.simulation.visualization import OffscreenRenderer, passive_viewer
from benchmark.tracking.coordinate_transform import world_points
from benchmark.tracking.recorder import frame_to_dict, replay_frames


class OfflineController(ManusController):
    """Reuse identical Phase 4 control/timeout policy with an explicitly selected method."""

    def __init__(self, robot, method):
        super().__init__(robot, DEFAULT_MANUS_CONFIG)
        if method == "anydex":
            from benchmark.retargeting.anydex import AnyDexRetargeter

            self.retargeter = AnyDexRetargeter(robot)
        elif method != "manus":
            # Never substitute another algorithm for methods that aren't implemented yet.
            from benchmark.retargeting.registry import create

            self.retargeter = create(method, robot=robot)


def pose_metrics(robot, q, frame):
    """Dimensionless common alignment. Human wrist / robot palm are explicit origins."""
    points = world_points(frame)
    z = points[9] - points[0]
    human_scale = np.linalg.norm(z)
    z /= human_scale
    y = points[5] - points[17]
    y -= y @ z * z
    y /= np.linalg.norm(y)
    basis = np.column_stack((np.cross(y, z), y, z))
    human = ((points[[4, 8, 12, 16, 20]] - points[0]) @ basis) / human_scale
    robot.forward_kinematics(np.zeros(20))
    mcp = robot.model.body("rl_dg_3_2").id
    robot_scale = np.linalg.norm(robot.fk_data.xpos[mcp] - robot.fk_data.xpos[robot.palm_id])
    tips = robot.forward_kinematics(q, frame="palm") / robot_scale
    return {
        "normalized_tip_position_error": float(np.mean(np.linalg.norm(tips - human, axis=1))),
        "normalized_thumb_distance_abs_error": np.abs(
            np.linalg.norm(tips[1:] - tips[0], axis=1)
            - np.linalg.norm(human[1:] - human[0], axis=1)
        ).tolist(),
        "human_reference_length_m": float(human_scale),
        "robot_reference_length_m": float(robot_scale),
        "tips_target_palm_m": robot.forward_kinematics(q, frame="palm").tolist(),
    }


def stats(values):
    return {
        "mean": float(np.mean(values)),
        "median": float(np.median(values)),
        "p95": float(np.percentile(values, 95)),
        "maximum": float(np.max(values)),
    }


def run_method(frames, method, folder, *, viewer=False, video=False):
    robot = RobotModel()
    controller = OfflineController(robot, method)
    retargeter = controller.retargeter
    provenance = (
        retargeter.provenance if hasattr(retargeter, "provenance") else retargeter.vendor.provenance
    )
    target_history, timings, tip_errors, dist_errors, errors = [], [], [], [], []
    solver_counts, clipped, statuses = {}, np.zeros(20), {}
    input_digest = hashlib.sha256()
    with ExitStack() as stack:
        log = stack.enter_context((folder / f"{method}.jsonl").open("x"))
        log.write(
            json.dumps(
                {
                    "event": "header",
                    "method": method,
                    "upstream": provenance,
                    "method_config": retargeter.config,
                    "model": robot.provenance,
                    "control": {
                        "fps": 50,
                        "timestep_s": 0.002,
                        "max_speed_rad_s": controller.max_speed,
                        "tracking_timeout_s": controller.timeout,
                    },
                    "metric_policy": "human wrist vs robot palm; distal/radial axes; "
                    "normalize each by neutral wrist/palm-to-middle-MCP length",
                    "source_metadata": frames[0].metadata,
                },
                allow_nan=False,
            )
            + "\n"
        )
        gui = (
            stack.enter_context(passive_viewer(robot.model, controller.runner.data))
            if viewer
            else None
        )
        renderer = stack.enter_context(OffscreenRenderer(robot.model)) if video else None
        writer = None
        if video:
            import imageio.v2 as imageio

            writer = stack.enter_context(
                imageio.get_writer(
                    str(folder / f"{method}.mp4"), fps=50, codec="libx264", quality=8
                )
            )
        start_wall = time.monotonic()
        origin = frames[0].timestamp
        cursor = 0
        count = int(np.ceil((frames[-1].timestamp - origin) * 50 - 1e-8)) + 1
        last_metrics_key = None
        for index in range(count):
            clock = origin + index / 50
            while cursor + 1 < len(frames) and frames[cursor + 1].timestamp <= clock + 1e-10:
                cursor += 1
            frame = frames[cursor]
            # Same resampled HandFrame stream for every method; no mutation of the source.
            input_digest.update(json.dumps(frame_to_dict(frame), sort_keys=True).encode())
            if gui:
                with gui.lock():
                    entry = controller.tick(frame, clock)
            else:
                entry = controller.tick(frame, clock)
            entry.update(
                input_index=cursor,
                original_frame_index=frame.metadata.get(
                    "original_frame_index", frame.metadata.get("sequence")
                ),
                input_time_s=clock,
            )
            metadata = entry["retarget_metadata"]
            key = (frame.timestamp, frame.metadata.get("sequence"))
            if metadata is not None and key != last_metrics_key:
                metrics = pose_metrics(robot, controller.target, frame)
                entry["kinematic_metrics"] = metrics
                tip_errors.append(metrics["normalized_tip_position_error"])
                dist_errors.append(metrics["normalized_thumb_distance_abs_error"])
                timings.append(metadata["total_s"] * 1000)
                target_history.append(controller.target.copy())
                clipped += metadata["joint_limit_clipped"]
                status = metadata["solver_status"]
                solver_counts[status] = solver_counts.get(status, 0) + 1
                last_metrics_key = key
            errors.append(
                float(
                    np.max(np.abs(controller.command - np.array(entry["simulation"]["q_actual"])))
                )
            )
            statuses[controller.status] = statuses.get(controller.status, 0) + 1
            log.write(json.dumps(entry, allow_nan=False) + "\n")
            if renderer:
                writer.append_data(renderer.render(controller.runner.data))
            if gui:
                gui.sync()
                if not gui.is_running():
                    break
                time.sleep(max(0, start_wall + (index + 1) / 50 - time.monotonic()))
    if not timings:
        raise ValueError("No valid retargeting output in selected input")
    summary = {
        "method": method,
        "control_frames": index + 1,
        "unique_input_frames_evaluated": len(timings),
        "common_input_stream_sha256": input_digest.hexdigest(),
        "retarget_total_ms": stats(timings),
        "normalized_tip_position_error": stats(tip_errors),
        "normalized_thumb_distance_abs_error_mean": np.mean(dist_errors, axis=0).tolist(),
        "clipping_fraction_by_joint": (clipped / len(timings)).tolist(),
        "joint_excursion_rad": np.ptp(target_history, axis=0).tolist(),
        "dynamic_command_error_rad": stats(errors),
        "solver_status_counts": solver_counts,
        "control_status_counts": statuses,
        "contact_enabled": False,
        "pinch_contact_success": "not evaluated",
        "timing_note": "local wall time, includes adapter/vendor preprocessing, solve, "
        "vendor filter and verbose diagnostics; excludes simulation/render/logging",
        "accuracy_note": "geometric pose correspondence, not independent human ground truth; "
        "no gesture success labels; source and reference-length assumptions apply",
    }
    (folder / f"{method}_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=tuple(catalog()), default="geort_alex")
    parser.add_argument(
        "--input", type=Path, help="existing common HandFrame JSONL instead of dataset"
    )
    parser.add_argument(
        "--methods",
        nargs="+",
        choices=("manus", "anydex", "wuji", "geort"),
        default=["manus", "anydex"],
    )
    parser.add_argument("--start-frame", type=int, default=0)
    parser.add_argument("--frames", type=int, default=150)
    parser.add_argument("--assumed-fps", type=float, default=30)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--viewer", action="store_true")
    parser.add_argument("--video", action="store_true")
    parser.add_argument("--fetch-only", action="store_true")
    args = parser.parse_args(argv)
    if args.frames <= 0 or args.start_frame < 0:
        parser.error("frames must be positive and start-frame nonnegative")
    if len(set(args.methods)) != len(args.methods):
        parser.error("duplicate methods are not allowed")
    fetch_samples() if args.input is None else None
    if args.fetch_only:
        print("Pinned public samples available; verified SHA256 and size")
        return
    frames = (
        list(replay_frames(args.input, handedness="right"))
        if args.input
        else list(load_public(args.dataset, fps=args.assumed_fps))
    )
    audit = None if args.input else audit_samples(frames)
    frames = frames[args.start_frame : args.start_frame + args.frames]
    if len(frames) < 2:
        raise ValueError("Select at least two input frames")
    (ROOT / "results").mkdir(exist_ok=True)
    if args.output:
        from benchmark.paths import writable_output

        folder = writable_output(args.output)
        folder.mkdir(parents=True, exist_ok=False)
    else:
        folder = Path(tempfile.mkdtemp(prefix="phase5-", dir=ROOT / "results"))
    write_frames(folder / "input.jsonl", frames)
    summaries = []
    for method in args.methods:
        print(f"Running {method}: {len(frames)} source frames", flush=True)
        summaries.append(run_method(frames, method, folder, viewer=args.viewer, video=args.video))
    if len({s["common_input_stream_sha256"] for s in summaries}) != 1:
        raise ValueError("Methods did not consume the same input stream (viewer closed early?)")
    manifest = catalog()
    report = {
        "dataset": args.dataset if not args.input else str(args.input),
        "input_frames": len(frames),
        "source_audit": audit,
        "split_audit": audit_split_overlap({"development": list(manifest.values())}),
        "methods": summaries,
        "output": str(folder),
        "scope": "Phase 5: MANUS and AnyDex. Wuji/GeoRT algorithms pending Phase 6/7.",
    }
    (folder / "comparison.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
