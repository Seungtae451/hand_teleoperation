"""GeoRT preparation commands. Training plans never execute without --execute."""

import argparse
import json
import tempfile
from functools import partial
from pathlib import Path

from benchmark.geort_support.assets import prepare, validate_config
from benchmark.geort_support.runtime import check_runtime
from benchmark.geort_support.training import execute_training, export_recording, training_plan
from benchmark.paths import ROOT, writable_output


def infer(args):
    if not args.checkpoint.is_file():
        raise FileNotFoundError(
            "Provide a trained DG-5F checkpoint; inference cannot use random weights"
        )
    validate_config(json.loads(args.config.read_text()))
    from benchmark.experiments.offline_benchmark import run_method
    from benchmark.retargeting import registry
    from benchmark.retargeting.geort import GeoRTRetargeter
    from benchmark.tracking.recorder import replay_frames

    frames = list(replay_frames(args.input, handedness="right"))[: args.frames]
    if len(frames) < 2 or args.frames < 2:
        raise ValueError("Inference needs at least two input frames")
    if "geort" in registry._FACTORIES:
        raise ValueError("GeoRT is already registered; use an explicit fresh process")
    (ROOT / "results").mkdir(exist_ok=True)
    if args.output:
        output = writable_output(args.output)
        output.mkdir(parents=True, exist_ok=False)
    else:
        output = Path(tempfile.mkdtemp(prefix="geort-inference-", dir=ROOT / "results"))
    registry.register(
        "geort", partial(GeoRTRetargeter, checkpoint=args.checkpoint, config_path=args.config)
    )
    try:
        return run_method(frames, "geort", output, viewer=args.viewer, video=args.video)
    finally:
        registry._FACTORIES.pop("geort", None)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser(
        "prepare", help="write derived URDF/config; no data collection or learning"
    )
    build.add_argument("--workspace", required=True, type=Path)
    check = sub.add_parser(
        "check", help="check original SAPIEN FK/architecture, without neural inference"
    )
    check.add_argument("--workspace", required=True, type=Path)
    check.add_argument("--output", type=Path)
    train = sub.add_parser(
        "train", help="plan only by default; future execution requires --execute"
    )
    train.add_argument("--workspace", required=True, type=Path)
    train.add_argument("--human-data", type=Path)
    train.add_argument("--manifest", type=Path)
    train.add_argument("--execute", action="store_true")
    train.add_argument("--seed", type=int, default=20261018)
    export = sub.add_parser("export-input", help="future user recording to original canonical NPY")
    export.add_argument("--input", required=True, type=Path)
    export.add_argument("--output", required=True, type=Path)
    export.add_argument("--split", choices=("train", "eval", "development"), default="development")
    export.add_argument("--drop-invalid", action="store_true")
    inference = sub.add_parser(
        "infer", help="requires an actual trained checkpoint and export config"
    )
    inference.add_argument("--input", type=Path, required=True)
    inference.add_argument("--checkpoint", type=Path, required=True)
    inference.add_argument("--config", type=Path, required=True)
    inference.add_argument("--frames", type=int, default=150)
    inference.add_argument("--output", type=Path)
    inference.add_argument("--viewer", action="store_true")
    inference.add_argument("--video", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "prepare":
        _, result = prepare(args.workspace)
    elif args.command == "check":
        result = check_runtime(args.workspace)
        if args.output:
            path = writable_output(args.output)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("x") as stream:
                stream.write(json.dumps(result, indent=2) + "\n")
    elif args.command == "train":
        if args.execute:
            if args.human_data is None or args.manifest is None:
                parser.error("--execute requires --human-data and --manifest")
            result = {
                "run": execute_training(
                    args.workspace, args.human_data, args.manifest, seed=args.seed
                )
            }
        else:
            result = training_plan(args.workspace, args.human_data)
    elif args.command == "export-input":
        result = export_recording(
            args.input, args.output, split=args.split, drop_invalid=args.drop_invalid
        )
        # Full per-frame provenance is saved in manifest.json; avoid dumping it to the terminal.
        result = {k: v for k, v in result.items() if k != "retained_frame_provenance"}
    else:
        result = infer(args)
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    main()
