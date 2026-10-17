#!/usr/bin/env python3
"""Compose measured video synchronization, comparison clips and evidence plots."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.export_take_retargeting import LABELS, METHODS  # noqa: E402
from scripts.geort_range_study import save  # noqa: E402


def clock_mapping(take, alignment):
    from benchmark.tracking.recorder import read_events

    samples = []
    for event in read_events(take / "quest_input.jsonl"):
        if event.get("event") == "native_packet" and event["packet"].get("type") == "frame":
            samples.append([event["receive_time_s"], event["packet"]["source_time_ms"]])
    p = np.array(samples)
    markers = [json.loads(line) for line in (take / "markers.jsonl").read_text().splitlines()]
    origin = next(m["receive_time_s"] for m in markers if m["browser"].get("stage") == "sync_start")
    slope, intercept = np.polyfit(p[:, 0] - origin, p[:, 1], 1)
    fitted = (p[:, 0] - origin) * slope + intercept
    sync = alignment["sync"]
    return {
        "receiver_origin_s": origin,
        "video_start_pts_s": (intercept - sync["offset_ms"]) / sync["scale_ms_per_video_s"],
        "video_rate_per_replay_s": slope / sync["scale_ms_per_video_s"],
        "source_receiver_clock_fit_max_residual_ms": float(np.max(np.abs(fitted - p[:, 1]))),
        "source_receiver_clock_fit_p95_residual_ms": float(
            np.percentile(np.abs(fitted - p[:, 1]), 95)
        ),
        "video_source_anchor_max_residual_ms": sync["fit_max_residual_ms"],
        "accuracy_note": (
            "Visual source-clock alignment, not a sub-frame synchronization or latency claim"
        ),
    }


def ffmpeg(command, log):
    import imageio_ffmpeg

    with log.open("x") as stream:
        result = subprocess.run(
            [
                imageio_ffmpeg.get_ffmpeg_exe(),
                "-hide_banner",
                "-nostdin",
                "-n",
                "-filter_complex_threads",
                "2",
                *command,
            ],
            stdout=stream,
            stderr=subprocess.STDOUT,
        )
    if result.returncode:
        raise RuntimeError(f"FFmpeg failed: {log}")


def compose(args):
    from PIL import Image, ImageDraw, ImageFont

    alignment = json.loads(args.alignment.read_text())
    run = json.loads((args.replay / "run.json").read_text())
    assert run["state"] == "completed" and run["same_input_digest_verified"]
    seconds = run["seconds"]
    mapping = clock_mapping(args.take, alignment)
    save(args.output / "synchronization.json", mapping)
    bg = Image.new("RGB", (960, 1080), "#101827")
    draw = ImageDraw.Draw(bg)
    title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 40)
    normal = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
    draw.text((42, 86), "REAL HAND / Quest 3 passthrough", fill="white", font=title)
    draw.text(
        (42, 150), "Same capture, synchronized WebXR joint input", fill="#9fe5c0", font=normal
    )
    for y, line in enumerate(
        [
            "Right-hand WebXR poses; video pixels are not the model input.",
            "Robot panels show actual simulated state after common control.",
            "50 Hz control | 25 fps export | pi rad/s command speed limit",
            "Contact disabled. Prompted gestures are not success labels.",
            "GeoRT: personal session 002, full official joint ranges.",
            "Visual clock alignment; video capture interval is about 33 ms.",
        ]
    ):
        draw.text((42, 820 + y * 36), line, fill="#c5cddd", font=normal)
    bg.save(args.output / "human_panel.png")
    source = alignment["video"]["path"]
    start, rate = mapping["video_start_pts_s"], mapping["video_rate_per_replay_s"]
    hand_filter = (
        f"[0:v]trim=start={start:.9f}:duration={seconds * rate:.9f},"
        f"setpts=(PTS-STARTPTS)/{rate:.12f},fps=25,scale=960:540[hs];"
        "[5:v][hs]overlay=0:240:shortest=1[hand];"
    )
    inputs = ["-i", source]
    for method in METHODS:
        inputs += ["-i", str(args.replay / f"{method}.mp4")]
    inputs += ["-loop", "1", "-framerate", "25", "-i", str(args.output / "human_panel.png")]
    robot_filter = "".join(
        f"[{i + 1}:v]scale=480:360,pad=480:540:0:90:color=0x101827[r{i}];" for i in range(4)
    )
    grid = "[r0][r1][r2][r3]xstack=inputs=4:layout=0_0|480_0|0_540|480_540[robots];"
    codec = [
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-threads",
        "4",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-t",
        str(seconds),
    ]
    ffmpeg(
        [
            *inputs,
            "-filter_complex",
            hand_filter + robot_filter + grid + "[hand][robots]hstack=inputs=2[out]",
            "-map",
            "[out]",
            *codec,
            str(args.output / "comparison_all.mp4"),
        ],
        args.output / "compose_all.log",
    )
    for i, method in enumerate(METHODS):
        filt = hand_filter + f"[{i + 1}:v]scale=960:720,pad=960:1080:0:180:color=0x101827[robot];"
        filt += "[hand][robot]hstack=inputs=2[out]"
        ffmpeg(
            [
                *inputs,
                "-filter_complex",
                filt,
                "-map",
                "[out]",
                *codec,
                str(args.output / f"comparison_{method}.mp4"),
            ],
            args.output / f"compose_{method}.log",
        )
    for label, begin, duration in [
        ("open_fist", 6, 18),
        ("individual_fingers", 24, 24),
        ("pinches", 54, 24),
        ("wrist_occlusion", 84, 12),
    ]:
        ffmpeg(
            [
                "-ss",
                str(begin),
                "-i",
                str(args.output / "comparison_all.mp4"),
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "23",
                "-threads",
                "4",
                "-movflags",
                "+faststart",
                "-t",
                str(duration),
                str(args.output / f"clip_{label}.mp4"),
            ],
            args.output / f"clip_{label}.log",
        )
    ffmpeg(
        [
            "-ss",
            "8",
            "-t",
            "8",
            "-i",
            str(args.output / "comparison_all.mp4"),
            "-filter_complex",
            "fps=8,scale=768:-1:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse",
            "-loop",
            "0",
            str(args.output / "preview.gif"),
        ],
        args.output / "preview.log",
    )
    ffmpeg(
        [
            "-ss",
            "12",
            "-i",
            str(args.output / "comparison_all.mp4"),
            "-frames:v",
            "1",
            str(args.output / "comparison_preview.png"),
        ],
        args.output / "preview_image.log",
    )
    # Separate every prompted action; SYNC slates remain in the full video only.
    gestures = args.output / "gestures"
    gestures.mkdir(exist_ok=False)
    take = json.loads((args.take / "take.json").read_text())
    begin = 0.0
    clips = []
    for stage in take["stages"]:
        duration = stage["seconds"]
        if not stage["id"].startswith("sync") and begin + duration <= seconds + 1e-6:
            name = stage["id"]
            ffmpeg(
                [
                    "-ss",
                    str(begin),
                    "-i",
                    str(args.output / "comparison_all.mp4"),
                    "-an",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "23",
                    "-threads",
                    "4",
                    "-pix_fmt",
                    "yuv420p",
                    "-movflags",
                    "+faststart",
                    "-t",
                    str(duration),
                    str(gestures / f"{name}.mp4"),
                ],
                gestures / f"{name}.log",
            )
            ffmpeg(
                [
                    "-i",
                    str(gestures / f"{name}.mp4"),
                    "-filter_complex",
                    "fps=8,scale=640:-1:flags=lanczos,split[a][b];"
                    "[a]palettegen[p];[b][p]paletteuse",
                    "-loop",
                    "0",
                    str(gestures / f"{name}.gif"),
                ],
                gestures / f"{name}_gif.log",
            )
            clips.append(
                {
                    "id": name,
                    "label": stage["label"],
                    "start_s": begin,
                    "duration_s": duration,
                    "video": f"gestures/{name}.mp4",
                    "preview": f"gestures/{name}.gif",
                }
            )
        begin += duration
    save(
        gestures / "clips.json",
        {"selection": "prompt schedule, not verified gesture labels", "clips": clips},
    )


def plots(args):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.size": 11, "axes.spines.top": False, "axes.spines.right": False})
    data = {m: np.load(args.replay / f"{m}_states.npz") for m in METHODS}
    summary = json.loads((args.replay / "summaries.json").read_text())
    time = data["geort"]["time_s"]
    colors = dict(zip(METHODS, ["#7c5cff", "#008d8b", "#e79a24", "#dc4b69"]))

    def finish(fig, name):
        fig.tight_layout()
        fig.savefig(args.output / name, dpi=160, bbox_inches="tight")
        plt.close(fig)

    fig, axes = plt.subplots(2, 1, figsize=(14, 7), sharex=True)
    for m, d in data.items():
        axes[0].plot(time, d["shape_error"], label=LABELS[m], color=colors[m], lw=1)
        gap = np.degrees(np.sqrt(np.mean((d["target"] - d["command"]) ** 2, axis=1)))
        axes[1].plot(time, gap, color=colors[m], lw=1)
    axes[0].set(
        ylabel="Normalized target discrepancy",
        title="Same recorded input / geometric diagnostic, not pose ground truth",
    )
    axes[0].legend(ncol=2, fontsize=9)
    axes[1].set(
        xlabel="Replay time (s)",
        ylabel="Target-command RMS (deg)",
        title="Command lag includes the common speed limiter",
    )
    finish(fig, "timeline.png")

    fig, axes = plt.subplots(1, 3, figsize=(15, 4))
    x = np.arange(4)
    axes[0].bar(x, [summary[m]["shape_error_mean"] for m in METHODS], color=list(colors.values()))
    axes[0].set(title="Mean target discrepancy", ylabel="Normalized geometric distance")
    axes[1].bar(
        x,
        [np.degrees(summary[m]["command_actual_rmse_rad"]) for m in METHODS],
        color=list(colors.values()),
    )
    axes[1].set(title="Command-actual tracking", ylabel="Joint RMSE (deg)")
    axes[2].bar(
        x, [summary[m]["inference_median_ms"] for m in METHODS], color=list(colors.values())
    )
    axes[2].set(title="Diagnostic adapter time", ylabel="Median ms (concurrent workers)")
    for ax in axes:
        ax.set_xticks(x, [m.upper() for m in METHODS], rotation=15)
    fig.suptitle("One 108 s demonstration; no isolated speed ranking or contact-success claim")
    finish(fig, "summary.png")

    fig, axes = plt.subplots(3, 1, figsize=(14, 9), sharex=True)
    from benchmark.geort_support.input import canonical_points
    from benchmark.tracking.recorder import replay_frames
    from scripts.compare_allegro_control import geometry

    frames = list(replay_frames(args.take / "quest_input.jsonl", handedness="right"))
    good = [f for f in frames if f.tracking_valid]
    points = np.array([canonical_points(f) for f in good])
    human_pip, _ = geometry(points)
    origin = clock_mapping(args.take, json.loads(args.alignment.read_text()))["receiver_origin_s"]
    human_t = np.array([f.timestamp - origin for f in good])
    for finger, ax in enumerate(axes):
        ax.plot(human_t, human_pip[:, finger], color="black", lw=1.2, label="Human geometric PIP")
        for m, d in data.items():
            ax.plot(
                time,
                np.degrees(d["target"][:, 6 + 4 * finger]),
                color=colors[m],
                lw=0.9,
                label=m.upper(),
            )
        ax.axhline(0, color="#777", lw=0.5)
        ax.set(ylabel=f"{['Index', 'Middle', 'Ring'][finger]} PIP (deg)", ylim=(-100, 130))
    axes[0].set_title(
        "Human estimated PIP vs robot target PIP / corresponding geometry, not fitted calibration"
    )
    axes[0].legend(ncol=5, fontsize=9)
    axes[-1].set(xlabel="Replay time (s)", xlim=(0, len(time) / 50))
    finish(fig, "pip_response.png")

    fig, axes = plt.subplots(2, 2, figsize=(14, 8), sharex=True)
    for i, ax in enumerate(axes.flat):
        hp = points[:, [4, 8, 12, 16, 20]]
        scale = np.linalg.norm(points[:, 9] - points[:, 0], axis=1)
        hd = np.linalg.norm(hp[:, i + 1] - hp[:, 0], axis=1) / scale
        ax.plot(human_t, hd, color="black", label="Human", lw=1)
        for m, d in data.items():
            robot = __import__(
                "benchmark.simulation.robot_model", fromlist=["RobotModel"]
            ).RobotModel()
            robot.forward_kinematics(np.zeros(20))
            middle_mcp = robot.model.body("rl_dg_3_2").id
            rs = np.linalg.norm(robot.fk_data.xpos[middle_mcp] - robot.fk_data.xpos[robot.palm_id])
            dist = np.linalg.norm(d["tips"][:, i + 1] - d["tips"][:, 0], axis=1) / rs
            ax.plot(time, dist, color=colors[m], label=m.upper(), lw=0.8)
        ax.set(
            title=f"Thumb - {['index', 'middle', 'ring', 'pinky'][i]}",
            ylabel="Pair distance / reference reach",
            xlim=(0, len(time) / 50),
        )
    axes[0, 0].legend(ncol=3, fontsize=9)
    for ax in axes[1]:
        ax.set_xlabel("Replay time (s)")
    fig.suptitle(
        "Actual-state fingertip distance / no collisions or pad contact; "
        "distance is not grasp success"
    )
    finish(fig, "pinch_distances.png")

    fig, ax = plt.subplots(figsize=(13, 4))
    matrix = np.array([summary[m]["clip_fraction"] for m in METHODS])
    im = ax.imshow(matrix, aspect="auto", vmin=0, vmax=max(0.01, matrix.max()), cmap="magma")
    ax.set_yticks(range(4), [m.upper() for m in METHODS])
    ax.set_xticks(
        range(20), [f"{f}{j}" for f in ["T", "I", "M", "R", "P"] for j in range(1, 5)], rotation=45
    )
    ax.set_title(
        "Common official-limit clipping frequency / upstream internal constraints may already apply"
    )
    fig.colorbar(im, ax=ax, label="Fraction of unique valid inferences")
    finish(fig, "clipping.png")

    history_path = ROOT / "docs/media/video_benchmark_002/geort_range_history_data.json"
    if history_path.exists():
        histories = json.loads(history_path.read_text())["histories"]
    else:
        histories = []
        for path, label in [
            ("geort_range_study_20261018", "Eight distal: 0..90"),
            ("geort_quest_observed_six_20261018", "Six: observed upper"),
        ]:
            doc = json.loads((ROOT / "results" / path / "comparison.json").read_text())
            row = doc["conditions"]["restricted"]["gestures"]
            histories.append(
                (
                    label,
                    [[row[g]["joint_mean_deg"][f][2] for f in (1, 2, 3)] for g in ["open", "fist"]],
                )
            )
    fig, axes = plt.subplots(1, 2, figsize=(12, 4), sharey=True)
    for ax, (label, values) in zip(axes, histories):
        ax.bar(np.arange(3) - 0.18, values[0], 0.36, label="Open candidate input", color="#dc4b69")
        ax.bar(np.arange(3) + 0.18, values[1], 0.36, label="Fist candidate input", color="#008d8b")
        ax.set_xticks(range(3), ["Index", "Middle", "Ring"])
        ax.set(title=label, ylabel="Robot target PIP mean (deg)", ylim=(0, 100))
    axes[0].legend(fontsize=9)
    fig.suptitle("Prior range experiments / same inspected evaluation take, not the new video take")
    finish(fig, "geort_range_history.png")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--take", type=Path, required=True)
    parser.add_argument("--replay", type=Path, required=True)
    parser.add_argument("--alignment", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--plots-only", action="store_true")
    parser.add_argument("--skip-plots", action="store_true", help="Keep existing numerical figures")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if not args.plots_only:
        compose(args)
    if not args.skip_plots:
        plots(args)


if __name__ == "__main__":
    main()
