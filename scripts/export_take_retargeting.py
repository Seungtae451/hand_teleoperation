#!/usr/bin/env python3
"""Render identical recorded inputs through existing controllers, one method per process."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from benchmark.artifacts import save, sha  # noqa: E402

PERSONAL = (
    ROOT
    / "results/geort_dg5f_workspace/training-f9nel4wo/checkpoint"
    / "dg5f_right_geort_2026-10-18_03-29-30"
)
METHODS = ["manus", "anydex", "wuji", "geort"]
LABELS = {
    "manus": "MANUS-style / thumb axes v2",
    "anydex": "AnyDex / robot profile",
    "wuji": "Wuji / robot profile",
    "geort": "GeoRT / personal 002, full range",
}


def worker(args):
    import imageio.v2 as imageio
    from PIL import Image, ImageDraw, ImageFont

    from benchmark.experiments.live_retargeting import controller_for
    from benchmark.experiments.offline_benchmark import pose_metrics
    from benchmark.simulation.visualization import OffscreenRenderer
    from benchmark.tracking.recorder import frame_to_dict, replay_frames

    method = args.worker
    controller = controller_for(method, args.checkpoint, args.config, args.robot_profile)
    robot = controller.runner.robot
    frames = list(replay_frames(args.take / "quest_input.jsonl", handedness="right"))
    markers = [json.loads(line) for line in (args.take / "markers.jsonl").read_text().splitlines()]
    origin = next(m["receive_time_s"] for m in markers if m["browser"].get("stage") == "sync_start")
    cursor = 0
    digest = hashlib.sha256()
    retargeter = controller.retargeter
    provenance = getattr(retargeter, "provenance", None) or retargeter.vendor.provenance
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 21)
    small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
    columns = {
        k: []
        for k in [
            "time_s",
            "input_index",
            "valid",
            "status",
            "raw",
            "target",
            "command",
            "actual",
            "tips",
            "target_tips",
            "human",
            "shape_error",
            "inference_ms",
            "clip",
            "new_inference",
        ]
    }
    last_key = None
    with (
        (args.output / f"{method}.jsonl").open("x") as log,
        OffscreenRenderer(robot.model) as renderer,
        imageio.get_writer(
            str(args.output / f"{method}.mp4"),
            fps=25,
            codec="libx264",
            quality=8,
            macro_block_size=16,
        ) as video,
    ):
        log.write(
            json.dumps(
                {
                    "event": "header",
                    "method": method,
                    "provenance": provenance,
                    "config": retargeter.config,
                    "robot_profile": str(args.robot_profile),
                    "model": robot.provenance,
                    "control_hz": 50,
                    "video_fps": 25,
                    "render_state": "actual_simulation_qpos",
                    "contact_enabled": False,
                    "input": "same receiver-time resampling for all methods",
                }
            )
            + "\n"
        )
        for tick in range(round(args.seconds * 50)):
            clock = origin + tick / 50
            while cursor + 1 < len(frames) and frames[cursor + 1].timestamp <= clock + 1e-10:
                cursor += 1
            frame = frames[cursor] if frames[cursor].timestamp <= clock else None
            digest.update(
                json.dumps(frame_to_dict(frame) if frame else None, sort_keys=True).encode()
            )
            entry = controller.tick(frame, clock)
            entry.update(
                time_s=tick / 50,
                input_index=cursor,
                input_sequence=frame.metadata.get("sequence") if frame else None,
            )
            log.write(json.dumps(entry, allow_nan=False) + "\n")
            valid = entry["control_status"] == "TRACKING"
            metadata = entry["retarget_metadata"] or {}
            key = (frame.timestamp, frame.metadata.get("sequence")) if frame else None
            new = valid and key != last_key
            if new:
                last_key = key
            target = np.array(entry["retarget_q_target"])
            actual = np.array(entry["simulation"]["q_actual"])
            metric = pose_metrics(robot, target, frame) if valid else None
            columns["time_s"].append(tick / 50)
            columns["input_index"].append(cursor)
            columns["valid"].append(valid)
            columns["status"].append(entry["control_status"])
            columns["new_inference"].append(new)
            columns["inference_ms"].append(metadata.get("total_s", np.nan) * 1000)
            columns["clip"].append(metadata.get("joint_limit_clipped", [False] * 20))
            columns["raw"].append(metadata.get("q_vendor_raw", [np.nan] * 20))
            columns["target"].append(target)
            columns["command"].append(entry["simulation"]["q_command"])
            columns["actual"].append(actual)
            columns["tips"].append(
                robot.forward_kinematics(actual, frame="palm", enforce_limits=False)
            )
            columns["target_tips"].append(robot.forward_kinematics(target, frame="palm"))
            columns["human"].append(frame.joint_positions if valid else np.full((21, 3), np.nan))
            columns["shape_error"].append(
                metric["normalized_tip_position_error"] if metric else np.nan
            )
            if tick % 2 == 0:
                image = Image.fromarray(renderer.render(controller.runner.data))
                draw = ImageDraw.Draw(image)
                draw.rectangle((0, 0, 640, 68), fill="#101827")
                draw.text((12, 7), LABELS[method], font=font, fill="white")
                draw.text(
                    (12, 37),
                    f"t={tick / 50:06.2f}s  {entry['control_status']}  | actual state",
                    font=small,
                    fill="#9fe5c0" if valid else "#ffd080",
                )
                video.append_data(np.asarray(image))
    arrays = {k: np.array(v) for k, v in columns.items()}
    np.savez_compressed(args.output / f"{method}_states.npz", **arrays)
    valid = arrays["valid"]
    new = arrays["new_inference"]
    summary = {
        "method": method,
        "label": LABELS[method],
        "ticks": len(valid),
        "tracking_ticks": int(valid.sum()),
        "input_stream_sha256": digest.hexdigest(),
        "video_seconds": args.seconds,
        "video_frames": len(valid[::2]),
        "shape_error_mean": float(np.nanmean(arrays["shape_error"])),
        "inference_median_ms": float(np.median(arrays["inference_ms"][new])),
        "inference_p95_ms": float(np.percentile(arrays["inference_ms"][new], 95)),
        "clip_fraction": arrays["clip"][new].mean(axis=0).tolist(),
        "command_actual_rmse_rad": float(
            np.sqrt(np.mean((arrays["command"] - arrays["actual"]) ** 2))
        ),
        "target_command_rmse_rad": float(
            np.sqrt(np.mean((arrays["target"] - arrays["command"]) ** 2))
        ),
        "checkpoint_sha256": sha(args.checkpoint) if method == "geort" else None,
        "profile_sha256": sha(args.robot_profile),
        "timing_note": "Concurrent replay workers: diagnostic timing, not isolated speed ranking",
        "metric_note": "Normalized geometric target discrepancy, not independent pose ground truth",
        "contact_enabled": False,
        "input_adapter": provenance,
    }
    save(args.output / f"{method}_summary.json", summary)
    print(f"DONE {method}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--take", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=float, default=108)
    parser.add_argument("--checkpoint", type=Path, default=PERSONAL / "last.pth")
    parser.add_argument("--config", type=Path, default=PERSONAL / "config.json")
    parser.add_argument(
        "--robot-profile", type=Path, default=ROOT / "configs/tesollo_calibrated/profile.json"
    )
    parser.add_argument("--worker", choices=METHODS)
    args = parser.parse_args()
    args.take, args.output = args.take.resolve(), args.output.resolve()
    if args.worker:
        worker(args)
        return
    from scripts.inspect_comparison_take import audit

    report = audit(args.take)
    if report["multi_session_warning"] or not report["hands"].get("right", {}).get("valid"):
        raise ValueError("Require one source session and valid right-hand frames")
    if not np.isfinite(args.seconds) or not 0 < args.seconds <= 108:
        raise ValueError("--seconds must be >0 and <=108")
    args.output.mkdir(parents=True, exist_ok=False)
    save(args.output / "input_audit.json", report)
    save(
        args.output / "run.json",
        {
            "take": str(args.take),
            "seconds": args.seconds,
            "methods": METHODS,
            "profile": str(args.robot_profile),
            "profile_sha256": sha(args.robot_profile),
            "checkpoint": str(args.checkpoint),
            "checkpoint_sha256": sha(args.checkpoint),
            "config": str(args.config),
            "state": "running",
            "video_fps": 25,
            "control_hz": 50,
        },
    )
    processes = []
    try:
        for method in METHODS:
            python = ROOT / (".venv-geort/bin/python" if method == "geort" else ".venv/bin/python")
            log = (args.output / f"{method}_console.txt").open("x")
            command = [
                str(python),
                __file__,
                "--worker",
                method,
                "--take",
                str(args.take),
                "--output",
                str(args.output),
                "--seconds",
                str(args.seconds),
                "--checkpoint",
                str(args.checkpoint),
                "--config",
                str(args.config),
                "--robot-profile",
                str(args.robot_profile),
            ]
            process = subprocess.Popen(
                command,
                cwd=ROOT,
                stdout=log,
                stderr=subprocess.STDOUT,
                env={**os.environ, "MUJOCO_GL": "egl", "PYTHONUNBUFFERED": "1"},
            )
            processes.append((method, process, log))
            print(f"START {method} PID {process.pid}", flush=True)
        for method, process, _ in processes:
            if process.wait():
                raise RuntimeError(f"{method} failed; inspect console")
        summaries = {
            m: json.loads((args.output / f"{m}_summary.json").read_text()) for m in METHODS
        }
        assert len({s["input_stream_sha256"] for s in summaries.values()}) == 1
        save(args.output / "summaries.json", summaries)
        run = json.loads((args.output / "run.json").read_text())
        save(
            args.output / "run.json",
            {**run, "state": "completed", "same_input_digest_verified": True},
        )
        print("All methods complete; identical input streams verified", flush=True)
    finally:
        for _, process, log in processes:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=15)
            log.close()


if __name__ == "__main__":
    main()
