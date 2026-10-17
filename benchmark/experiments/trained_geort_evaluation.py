"""Evaluate a completed original GeoRT run without retraining or tuning it."""

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from functools import partial
from pathlib import Path

import numpy as np

from benchmark.experiments.offline_benchmark import pose_metrics, run_method, stats
from benchmark.geort_support.input import canonical_points
from benchmark.geort_support.source import enable_upstream
from benchmark.paths import ROOT, writable_output
from benchmark.retargeting.geort import GeoRTRetargeter
from benchmark.simulation.mujoco_runner import MujocoRunner
from benchmark.simulation.robot_model import RobotModel
from benchmark.simulation.visualization import OffscreenRenderer
from benchmark.tracking.recorder import replay_frames


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def training_log(path):
    text = Path(path).read_text()
    fk = [
        (int(e), float(v))
        for e, v in re.findall(
            r"Neural FK Training Epoch:\s*(\d+); Training Loss:\s*([\deE.+-]+)", text
        )
    ]
    ik = [
        (int(row[0]), *map(float, row[1:]))
        for row in re.findall(
            r"Epoch (\d+) \| Losses - Direction: ([\deE.+-]+) - Chamfer: ([\deE.+-]+) "
            r"- Curvature: ([\deE.+-]+) - Collision: ([\deE.+-]+) - Pinch: ([\deE.+-]+)",
            text,
        )
    ]
    if len(fk) != 200 or len(ik) != 200:
        raise ValueError("Expected the completed 200-epoch logs; inspect log before evaluating")
    return {
        "log_sha256": sha(path),
        "fk_epochs": len(fk),
        "ik_epochs": len(ik),
        "fk_first_epoch_loss": fk[0][1],
        "fk_last_epoch_loss": fk[-1][1],
        "ik_first_logged_batch": dict(
            zip(("epoch", "direction", "chamfer", "curvature", "collision", "pinch"), ik[0])
        ),
        "ik_last_logged_batch": dict(
            zip(("epoch", "direction", "chamfer", "curvature", "collision", "pinch"), ik[-1])
        ),
        "fk_curve": fk,
        "ik_curve": ik,
        "note": "FK logs are epoch means; IK logs are batch 0 per epoch, not validation losses",
    }


def neural_fk_check(run, config, robot, folder):
    import torch
    from geort.formatter import HandFormatter
    from geort.model import FKModel
    from geort.utils.config_utils import parse_config_keypoint_info

    info = parse_config_keypoint_info(config)
    checkpoint = run / "checkpoint/fk_model_dg5f_right_geort.pth"
    model = FKModel(info["joint"]).cuda()
    model.load_state_dict(torch.load(checkpoint))
    model.eval()
    q = np.random.default_rng(2026101807).uniform(
        robot.limits[:, 0], robot.limits[:, 1], (1024, 20)
    )
    # Verify that the probe vectors aren't exact members of the FK training set.
    archive = np.load(run / "data/dg5f_right_geort.npz", allow_pickle=False)
    train_q = archive["qpos"]
    seen = {hashlib.sha256(np.asarray(row, dtype=np.float64).tobytes()).digest() for row in train_q}
    overlap = sum(hashlib.sha256(row.tobytes()).digest() in seen for row in q)
    if overlap:
        raise ValueError("Random FK probe vectors overlap training vectors")
    normalizer = HandFormatter(config["joint"]["lower"], config["joint"]["upper"])
    with torch.inference_mode():
        pred = model(torch.from_numpy(normalizer.normalize(q)).float().cuda()).cpu().numpy()
    true = np.array([robot.forward_kinematics(row, frame="palm") for row in q])
    distances = np.linalg.norm(pred - true, axis=2) * 1000
    np.savez_compressed(folder / "neural_fk_probe.npz", q=q, predicted_m=pred, true_m=true)
    return {
        "checkpoint_sha256": sha(checkpoint),
        "probe_vectors": len(q),
        "fk_training_vectors": len(train_q),
        "exact_q_overlap": int(overlap),
        "fingertip_distance_error_mm": stats(distances),
        "per_finger_mean_mm": distances.mean(axis=0).tolist(),
        "coordinate_rmse_mm": float(np.sqrt(np.mean((pred - true) ** 2)) * 1000),
        "note": "fresh uniform joint samples, same robot domain; not human retargeting accuracy",
    }


def direct_pose_check(path, label, adapter, robot, folder):
    all_frames = list(replay_frames(path, handedness="right"))
    frames = [frame for frame in all_frames if frame.tracking_valid]
    if not frames:
        raise ValueError("Recording has no valid right-hand data")
    adapter.reset()
    for _ in range(20):
        adapter.retarget(frames[0])
    adapter.reset()
    qs, raws, human, robot_points, times, normalized, clipped = [], [], [], [], [], [], []
    for frame in frames:
        result = adapter.retarget(frame)
        hp = canonical_points(frame)[[4, 8, 12, 16, 20]]
        rp = robot.forward_kinematics(result.q_target, frame="palm")
        metric = pose_metrics(robot, result.q_target, frame)
        qs.append(result.q_target)
        raws.append(result.metadata["q_vendor_raw"])
        human.append(hp)
        robot_points.append(rp)
        times.append(result.metadata["total_s"] * 1000)
        normalized.append(metric["normalized_tip_position_error"])
        clipped.append(result.metadata["joint_limit_clipped"])
    qs, raws, human, robot_points = map(np.asarray, (qs, raws, human, robot_points))
    hd = np.linalg.norm(human[:, 0] - human[:, 1], axis=1)
    rd = np.linalg.norm(robot_points[:, 0] - robot_points[:, 1], axis=1)
    candidates = (
        hd < 0.015
    )  # Original GeoRT training pinch-mask distance, not gesture ground truth.
    tip_errors = np.linalg.norm(human - robot_points, axis=2) * 1000
    excess = np.maximum(robot.limits[:, 0] - raws, 0) + np.maximum(raws - robot.limits[:, 1], 0)
    np.savez_compressed(
        folder / f"{label}_direct.npz",
        q_target=qs,
        q_vendor_raw=raws,
        human_tips_m=human,
        robot_tips_m=robot_points,
        timestamps=[f.timestamp for f in frames],
        retarget_ms=times,
        normalized_tip_error=normalized,
    )
    examples = {
        "largest_tip_spread": int(np.argmax(hd)),
        "closest_human_thumb_index": int(np.argmin(hd)),
        "largest_correspondence_error": int(np.argmax(tip_errors.mean(axis=1))),
    }
    from PIL import Image

    runner = MujocoRunner(robot)
    with OffscreenRenderer(robot.model) as renderer:
        for name, index in examples.items():
            runner.reset(qs[index])
            Image.fromarray(renderer.render(runner.data)).save(folder / f"{label}_{name}.png")
    return {
        "input": str(path),
        "input_sha256": sha(path),
        "role": label,
        "valid_right_frames": len(frames),
        "invalid_right_frames": len(all_frames) - len(frames),
        "distinct_sessions": sorted({f.metadata.get("session_id", "") for f in frames}),
        "normalized_tip_correspondence_error": stats(normalized),
        "raw_canonical_tip_correspondence_mm": stats(tip_errors),
        "per_finger_raw_correspondence_mean_mm": tip_errors.mean(axis=0).tolist(),
        "retarget_total_ms": stats(times),
        "warmup_calls_excluded": 20,
        "joint_limit_clipped_fraction": np.mean(clipped, axis=0).tolist(),
        "raw_joint_limit_excess_max_rad": float(excess.max()),
        "joint_excursion_rad": np.ptp(qs, axis=0).tolist(),
        "human_thumb_index_under_15mm_candidates": int(candidates.sum()),
        "robot_thumb_index_distance_on_candidates_mm": stats(rd[candidates] * 1000)
        if candidates.any()
        else None,
        "example_frame_indices": examples,
        "note": "all valid source frames, direct target FK; no physical contact or independent GT",
    }, all_frames


def geort_dynamic(frames, checkpoint, config, folder, video=False):
    from benchmark.retargeting import registry

    registry.register("geort", partial(GeoRTRetargeter, checkpoint=checkpoint, config_path=config))
    try:
        return run_method(frames, "geort", folder, video=video)
    finally:
        registry._FACTORIES.pop("geort", None)


def plot_results(log, direct, comparison, folder):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fk = np.array(log["fk_curve"])
    ik = np.array(log["ik_curve"])
    fig, axes = plt.subplots(2, 2, figsize=(10, 6), layout="constrained")
    axes[0, 0].semilogy(fk[:, 0], fk[:, 1])
    axes[0, 0].set_title("Neural FK: epoch mean MSE")
    for ax, column, title in [
        (axes[0, 1], 1, "IK direction (logged batch 0)"),
        (axes[1, 0], 2, "IK Chamfer (logged batch 0)"),
        (axes[1, 1], 5, "IK pinch (logged batch 0)"),
    ]:
        ax.plot(ik[:, 0], ik[:, column])
        ax.set_title(title)
    for ax in axes.flat:
        ax.set_xlabel("Epoch")
        ax.grid(alpha=0.2)
    fig.savefig(folder / "training_curves.png", dpi=160)
    plt.close(fig)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4), layout="constrained")
    for label in direct:
        x = np.load(folder / f"{label}_direct.npz")
        axes[0].hist(x["normalized_tip_error"], bins=50, density=True, alpha=0.5, label=label)
    axes[0].set_xlabel("Normalized tip correspondence error")
    axes[0].legend()
    if comparison:
        axes[1].bar(
            [m["method"] for m in comparison],
            [m["normalized_tip_position_error"]["mean"] for m in comparison],
        )
        axes[1].set_title("Same prior session, common 50 Hz runner")
        axes[1].set_ylabel("Mean normalized correspondence error")
    axes[0].set_title("Training session vs prior session (not subject-held-out)")
    fig.savefig(folder / "correspondence.png", dpi=160)
    plt.close(fig)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--train-recording", type=Path, required=True)
    parser.add_argument("--cross-recording", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--compare-baselines", action="store_true")
    args = parser.parse_args(argv)
    run = args.run.resolve()
    manifest = json.loads((run / "run_manifest.json").read_text())
    if manifest["status"] != "completed":
        raise ValueError("Training run is not completed")
    checkpoint_dir = next(
        p
        for p in sorted((run / "checkpoint").iterdir())
        if p.is_dir() and not p.name.endswith("_last")
    )
    checkpoint = checkpoint_dir / "last.pth"
    config = checkpoint_dir / "config.json"
    if sha(args.train_recording) != manifest["input_manifest"]["source_recording_sha256"]:
        raise ValueError("Training recording provenance mismatch")
    if sha(args.cross_recording) == sha(args.train_recording):
        raise ValueError("Cross-session input is the training recording")
    folder = (
        writable_output(args.output)
        if args.output
        else Path(tempfile.mkdtemp(prefix="geort-evaluation-", dir=ROOT / "results"))
    )
    if args.output:
        folder.mkdir(parents=True, exist_ok=False)
    input_hashes = {
        str(p): sha(p) for p in (checkpoint, config, args.train_recording, args.cross_recording)
    }
    log = training_log(args.log)
    enable_upstream()
    robot = RobotModel()
    adapter = GeoRTRetargeter(robot, checkpoint=checkpoint, config_path=config)
    neural = neural_fk_check(run, adapter.config, robot, folder)
    direct = {}
    sources = {}
    for label, path in (
        ("training_session", args.train_recording),
        ("prior_session", args.cross_recording),
    ):
        print(f"Direct checkpoint inference: {label}", flush=True)
        direct[label], sources[label] = direct_pose_check(path, label, adapter, robot, folder)
    dynamic_folder = folder / "prior_session_dynamic"
    dynamic_folder.mkdir()
    dynamic = geort_dynamic(sources["prior_session"], checkpoint, config, dynamic_folder)
    video_folder = folder / "training_preview"
    video_folder.mkdir()
    geort_dynamic(sources["training_session"][:300], checkpoint, config, video_folder, video=True)
    comparison = []
    if args.compare_baselines:
        with (folder / "baselines_console.txt").open("x") as stream:
            subprocess.run(
                [
                    str(ROOT / ".venv/bin/python"),
                    str(ROOT / "scripts/run_phase6.py"),
                    "--input",
                    str(args.cross_recording.resolve()),
                    "--frames",
                    "100000",
                    "--output",
                    str(folder / "prior_session_baselines"),
                ],
                cwd=ROOT,
                stdout=stream,
                stderr=subprocess.STDOUT,
                check=True,
            )
        baseline = json.loads((folder / "prior_session_baselines/comparison.json").read_text())
        comparison = baseline["methods"] + [dynamic]
        if len({m["common_input_stream_sha256"] for m in comparison}) != 1:
            raise ValueError("Four methods consumed different input streams")
    plot_results(log, direct, comparison, folder)
    for p, digest in input_hashes.items():
        if sha(p) != digest:
            raise ValueError("Input or checkpoint changed during evaluation")
    report = {
        "output": str(folder),
        "checkpoint": str(checkpoint),
        "checkpoint_sha256": sha(checkpoint),
        "run_status": manifest["status"],
        "training_log": log,
        "neural_fk": neural,
        "direct_pose_checks": direct,
        "common_runner_comparison": comparison,
        "generalization_status": "prior session is not in recorded training file; participant "
        "identity/independence unknown, not a formal held-out evaluation",
        "metric_policy": "geometric correspondence to estimated human pose, no robot joint GT; "
        "raw meter discrepancy affected by hand size and wrist/palm origins",
        "contact_enabled": False,
        "pinch_contact_success": "not tested",
        "retraining_executed": False,
        "inputs_and_checkpoints_unchanged": True,
    }
    (folder / "evaluation.json").write_text(json.dumps(report, indent=2) + "\n")
    (ROOT / "results/geort_evaluation_latest.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"output": str(folder), "neural_fk": neural, "direct": direct}, indent=2))


if __name__ == "__main__":
    main()
