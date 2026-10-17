#!/usr/bin/env python3
"""Read-only BN, local motion, Jacobian and sampling investigation of real checkpoints."""

import copy
import hashlib
import json
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    import torch
    from scipy.stats import spearmanr

    from benchmark.geort_support.range_experiment import normalization_affine
    from benchmark.geort_support.source import enable_upstream
    from benchmark.simulation.robot_model import RobotModel
    from scripts.compare_allegro_control import geometry

    enable_upstream()
    from geort.dataset import MultiPointDataset
    from geort.export import GeoRTRetargetingModel
    from geort.model import FKModel
    from geort.utils.config_utils import parse_config_keypoint_info

    output = Path(tempfile.mkdtemp(prefix="geort-mapping-investigation-", dir=ROOT / "results"))
    study = ROOT / "results/geort_range_study_20261018"
    doc = json.loads((study / "study.json").read_text())
    train = np.load(doc["human_data"])
    evaluation = np.load(ROOT / "data/geort/quest_eval_session_001/human.npy")
    # Recreate original sampler without changing source files or recording arrays.
    np.random.seed(20261018)
    resampled = MultiPointDataset.from_points(
        train[:, [4, 8, 12, 16, 20]].transpose(1, 0, 2), n=20000
    ).points.transpose(1, 0, 2)
    rng = np.random.default_rng(20261018)
    robot = RobotModel()
    full = robot.limits
    pip, mcp = geometry(evaluation)
    open_mask = (pip < 25).all(axis=1) & (np.abs(mcp) < 25).all(axis=1)
    fist_mask = (pip > 60).all(axis=1) & (np.abs(mcp) > 45).all(axis=1)

    def counts(tips):
        distances = np.linalg.norm(tips[:, 1:] - tips[:, :1], axis=2)
        return (distances < 0.015).sum(axis=0).tolist()

    report = {
        "policy": (
            "Read-only copied models, no optimizer or checkpoint changes. "
            "BatchNorm train-mode is diagnostic on clones only, not an inference fix. "
            "Local motion uses deterministic probes, not invented dataset keypoints."
        ),
        "output": str(output),
        "sampling": {
            "source_frames": len(train),
            "original_resample_output_frames": len(resampled),
            "source_thumb_pinch_counts": counts(train[:, [4, 8, 12, 16, 20]]),
            "resampled_thumb_pinch_counts": counts(resampled),
            "same_frame_finger_correspondence_preserved": False,
        },
        "models": {},
    }
    metas = {
        "personal_original": json.loads(
            (ROOT / "results/geort_personal_session002_eval/model_verification.json").read_text()
        )
    }
    metas.update(
        {
            name: json.loads((study / name / "manifest.json").read_text())
            for name in ["full", "restricted"]
        }
    )
    for name, meta in metas.items():
        before = hashlib.sha256(Path(meta["checkpoint"]).read_bytes()).hexdigest()
        adapter = GeoRTRetargetingModel(meta["checkpoint"], meta["config"])
        net = adapter.model
        config = json.loads(Path(meta["config"]).read_text())
        bounds = np.array([config["joint"]["lower"], config["joint"]["upper"]]).T
        fk = FKModel(parse_config_keypoint_info(config)["joint"]).cuda()
        fk.load_state_dict(torch.load(doc["shared_full_range_fk"], weights_only=True))
        fk.eval()
        scale, bias = normalization_affine(bounds, full)
        scale = torch.tensor(scale, dtype=torch.float32, device="cuda")
        bias = torch.tensor(bias, dtype=torch.float32, device="cuda")

        def neural(norm):
            return fk(norm * scale + bias)

        def physical(norm):
            return adapter.qpos_normalizer.unnormalize(norm.detach().cpu().numpy())

        def true_fk(norm):
            return np.array(
                [
                    robot.forward_kinematics(robot.validate_target(q, clip=True), frame="palm")
                    for q in physical(norm)
                ]
            )

        batch = torch.tensor(
            resampled[rng.choice(len(resampled), 2048, replace=False)],
            dtype=torch.float32,
            device="cuda",
        )
        # Real training-shaped batch; mode comparison uses an independent cloned network.
        clone = copy.deepcopy(net)
        clone.train()
        with torch.inference_mode():
            ev = net(batch)
            tr = clone(batch)
        diff = np.linalg.norm(true_fk(ev) - true_fk(tr), axis=2) * 1000
        joint_mode_diff = np.max(np.abs(physical(ev) - physical(tr)), axis=1) * 180 / np.pi
        open_ids = np.flatnonzero(open_mask)[np.linspace(0, open_mask.sum() - 1, 64, dtype=int)]
        fist_ids = np.flatnonzero(fist_mask)[np.linspace(0, fist_mask.sum() - 1, 64, dtype=int)]
        context = np.concatenate(
            [
                evaluation[open_ids][:, [4, 8, 12, 16, 20]],
                evaluation[fist_ids][:, [4, 8, 12, 16, 20]],
                resampled[:1920],
            ]
        )
        context = torch.tensor(context, dtype=torch.float32, device="cuda")
        context_clone = copy.deepcopy(net).train()
        with torch.inference_mode():
            context_eval = physical(net(context))
            context_train = physical(context_clone(context))
        result = {
            "eval_vs_training_mode_same_sampler_batch_tip_shift_mm": {
                "mean": float(diff.mean()),
                "p95": float(np.percentile(diff, 95)),
            },
            "bn_max_joint_shift_deg": {
                "mean": float(joint_mode_diff.mean()),
                "p95": float(np.percentile(joint_mode_diff, 95)),
            },
            "middle_pip_mode_context_deg": {
                "eval_open": float(np.degrees(context_eval[:64, 10]).mean()),
                "train_open": float(np.degrees(context_train[:64, 10]).mean()),
                "eval_fist": float(np.degrees(context_eval[64:128, 10]).mean()),
                "train_fist": float(np.degrees(context_train[64:128, 10]).mean()),
            },
            "local_direction": {},
            "checkpoint_trajectory": {},
        }
        ids = np.linspace(0, len(evaluation) - 1, 256, dtype=int)
        sample = torch.tensor(
            evaluation[ids][:, [4, 8, 12, 16, 20]], dtype=torch.float32, device="cuda"
        )
        # Hold probes identical across model conditions.
        torch.manual_seed(602)
        torch.cuda.manual_seed_all(602)
        direction = torch.nn.functional.normalize(torch.randn_like(sample), dim=-1)
        delta = direction * (0.001 + torch.rand(len(sample), 1, 1, device="cuda") * 0.01)
        for mode in ["eval", "training_clone"]:
            chosen = net if mode == "eval" else copy.deepcopy(net).train()
            with torch.inference_mode():
                n1 = chosen(sample)
                n2 = chosen(sample + delta)
                f1 = neural(n1)
                f2 = neural(n2)
            exact1 = true_fk(n1)
            exact2 = true_fk(n2)
            d = delta.cpu().numpy()
            de = (f2 - f1).cpu().numpy()
            dt = exact2 - exact1

            def cosine(v):
                return np.sum(d * v, axis=2) / (
                    np.linalg.norm(d, axis=2) * np.maximum(np.linalg.norm(v, axis=2), 1e-8)
                )

            cn, ct = cosine(de), cosine(dt)
            result["local_direction"][mode] = {
                "neural_fk_cos_mean": float(cn.mean()),
                "true_fk_cos_mean": float(ct.mean()),
                "true_fk_negative_cos_fraction": float((ct < 0).mean()),
                "neural_true_direction_disagreement_fraction": float(((cn > 0) & (ct < 0)).mean()),
            }
        # Physical FK Jacobian check on deployment outputs, including abduction/flexion.
        with torch.inference_mode():
            norm = net(sample[:64])
        q = torch.tensor(physical(norm), dtype=torch.float32, device="cuda", requires_grad=True)
        ffull = fk(
            2
            * (q - torch.tensor(full[:, 0], dtype=torch.float32, device="cuda"))
            / torch.tensor(full[:, 1] - full[:, 0], dtype=torch.float32, device="cuda")
            - 1
        )
        jac = []
        for finger in range(5):
            axes = []
            for axis in range(3):
                axes.append(
                    torch.autograd.grad(ffull[:, finger, axis].sum(), q, retain_graph=True)[0]
                    .detach()
                    .cpu()
                    .numpy()
                )
            jac.append(np.stack(axes, axis=1))
        jn = np.stack(jac, axis=1)
        jt = []
        for row in q.detach().cpu().numpy():
            row = robot.validate_target(row, clip=True)
            jw = robot.fingertip_jacobians(row)
            rotation = robot.fk_data.xmat[robot.palm_id].reshape(3, 3)
            jt.append(np.einsum("ab,fbc->fac", rotation.T, jw))
        jt = np.array(jt)
        # Only own-finger nonzero columns, exclude zero/weak derivatives.
        cvals = []
        relative = []
        for finger in range(5):
            for joint in range(finger * 4, finger * 4 + 4):
                a, b = jn[:, finger, :, joint], jt[:, finger, :, joint]
                length = np.linalg.norm(b, axis=1)
                valid = length > 1e-4
                cvals.extend(
                    (
                        np.sum(a[valid] * b[valid], axis=1)
                        / (np.linalg.norm(a[valid], axis=1) * length[valid])
                    ).tolist()
                )
                relative.extend(
                    (np.linalg.norm(a[valid] - b[valid], axis=1) / length[valid]).tolist()
                )
        result["fk_jacobian"] = {
            "mean_direction_cosine": float(np.mean(cvals)),
            "negative_cos_fraction": float((np.array(cvals) < 0).mean()),
            "median_relative_vector_error": float(np.median(relative)),
        }
        # Track original saved epochs without choosing/replacing a checkpoint.
        parent = Path(meta["checkpoint"]).parent
        candidates = [
            p
            for p in (parent / "checkpoint").glob("*")
            if p.is_dir() and not p.name.endswith("_last")
        ]
        if name == "personal_original":
            candidates = [parent]
        if candidates:
            path = candidates[0]
            subset = np.linspace(0, len(evaluation) - 1, 256, dtype=int)
            tensor = torch.tensor(
                evaluation[subset][:, [4, 8, 12, 16, 20]], dtype=torch.float32, device="cuda"
            )
            for epoch in [0, 1, 5, 10, 20, 50, 100, 150, 199]:
                state_path = path / f"epoch_{epoch}.pth"
                if not state_path.exists():
                    continue
                cloned = copy.deepcopy(net)
                cloned.load_state_dict(torch.load(state_path, weights_only=True))
                cloned.eval()
                with torch.inference_mode():
                    qs = physical(cloned(tensor))
                summed = qs[:, 4:16].reshape(-1, 3, 4)[:, :, 1:].sum(axis=2)
                result["checkpoint_trajectory"][str(epoch)] = {
                    "human_pip_vs_sum_flexion_spearman": [
                        float(spearmanr(pip[subset, i], summed[:, i]).statistic) for i in range(3)
                    ],
                    "open_middle_pip_target_deg": float(
                        np.degrees(qs[open_mask[subset], 10]).mean()
                    ),
                    "fist_middle_pip_target_deg": float(
                        np.degrees(qs[fist_mask[subset], 10]).mean()
                    ),
                }
        assert hashlib.sha256(Path(meta["checkpoint"]).read_bytes()).hexdigest() == before
        result["checkpoint_unchanged"] = True
        report["models"][name] = result
    (output / "investigation.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
