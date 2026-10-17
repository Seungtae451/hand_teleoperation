"""Phase 6: three original methods on identical public or recorded HandFrames."""

import argparse
import json
import tempfile
from contextlib import contextmanager
from pathlib import Path

from benchmark.datasets.public import (
    audit_samples,
    audit_split_overlap,
    catalog,
    fetch_samples,
    load_public,
    write_frames,
)
from benchmark.experiments.offline_benchmark import run_method
from benchmark.paths import ROOT, writable_output
from benchmark.retargeting.wuji import WujiRetargeter, register_wuji
from benchmark.tracking.recorder import replay_frames


@contextmanager
def wuji_registration():
    """Use the public registry API; restore previous global state after a run."""
    from benchmark.retargeting import registry

    existing = registry._FACTORIES.get("wuji")
    if existing is not None and existing is not WujiRetargeter:
        raise ValueError("A different Wuji adapter is already registered")
    if existing is None:
        register_wuji()
    try:
        yield
    finally:
        if existing is None:
            registry._FACTORIES.pop("wuji", None)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=tuple(catalog()), default="geort_alex")
    parser.add_argument(
        "--input", type=Path, help="existing common HandFrame JSONL instead of dataset"
    )
    parser.add_argument(
        "--methods",
        nargs="+",
        choices=("manus", "anydex", "wuji"),
        default=["manus", "anydex", "wuji"],
    )
    parser.add_argument("--frames", type=int, default=150)
    parser.add_argument("--start-frame", type=int, default=0)
    parser.add_argument("--assumed-fps", type=float, default=30)
    parser.add_argument("--viewer", action="store_true")
    parser.add_argument("--video", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.frames <= 0 or args.start_frame < 0 or len(set(args.methods)) != len(args.methods):
        parser.error("positive frame count, nonnegative start, and unique methods are required")
    if args.input is None:
        fetch_samples()
    source = (
        list(replay_frames(args.input, handedness="right"))
        if args.input
        else list(load_public(args.dataset, fps=args.assumed_fps))
    )
    audit = None if args.input else audit_samples(source)
    frames = source[args.start_frame : args.start_frame + args.frames]
    if len(frames) < 2:
        raise ValueError("Select at least two input frames")
    (ROOT / "results").mkdir(exist_ok=True)
    if args.output:
        folder = writable_output(args.output)
        folder.mkdir(parents=True, exist_ok=False)
    else:
        folder = Path(tempfile.mkdtemp(prefix="phase6-", dir=ROOT / "results"))
    write_frames(folder / "input.jsonl", frames)
    summaries = []
    with wuji_registration():
        for method in args.methods:
            print(f"Running {method}: {len(frames)} source frames", flush=True)
            summaries.append(
                run_method(frames, method, folder, viewer=args.viewer, video=args.video)
            )
    if len({s["common_input_stream_sha256"] for s in summaries}) != 1:
        raise ValueError(
            "Methods consumed different inputs; complete the same interval in each viewer"
        )
    report = {
        "phase": 6,
        "source": str(args.input) if args.input else args.dataset,
        "input_frames": len(frames),
        "source_audit": audit,
        "split_audit": audit_split_overlap({"development": list(catalog().values())}),
        "methods": summaries,
        "output": str(folder),
        "scope": "MANUS/AnyDex/Wuji; shared adaptive foundations; GeoRT model pending Phase 7",
        "constraint_policy": "Wuji original defaults: hyperextension and coupling weights zero",
    }
    (folder / "comparison.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    main()
