#!/usr/bin/env python3
"""Audit paired video takes and save explicit, manually measured video/source anchors."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from benchmark.tracking.recorder import read_events  # noqa: E402


def fit_anchors(anchors):
    points = np.asarray(anchors, dtype=float)
    if points.ndim != 2 or points.shape[1] != 2 or len(points) < 2:
        raise ValueError("At least two VIDEO_SECONDS:SOURCE_MS anchors are required")
    if not np.isfinite(points).all() or (points[:, 0] < 0).any():
        raise ValueError("Anchors must be finite and video seconds nonnegative")
    if np.ptp(points[:, 0]) < 1 or np.ptp(points[:, 1]) < 1000:
        raise ValueError("Separate anchors by at least one second")
    if (np.diff(points[:, 0]) <= 0).any() or (np.diff(points[:, 1]) <= 0).any():
        raise ValueError("Anchors must increase in both clocks")
    design = np.column_stack([points[:, 0], np.ones(len(points))])
    scale, offset = np.linalg.lstsq(design, points[:, 1], rcond=None)[0]
    if not 900 < scale < 1100:
        raise ValueError("Implausible clock scale; verify units and video speed")
    return {
        "equation": "source_ms = scale_ms_per_video_s * video_pts_s + offset_ms",
        "scale_ms_per_video_s": float(scale),
        "offset_ms": float(offset),
        "anchors_video_s_source_ms": points.tolist(),
        "fit_max_residual_ms": float(np.abs(design @ [scale, offset] - points[:, 1]).max()),
        "uncertainty": "Manual visual anchors; fit residual is NOT synchronization accuracy",
        "hardware_capture_or_passthrough_verified": False,
    }


def audit(folder):
    take = json.loads((folder / "take.json").read_text())
    if take["status"] != "closed":
        raise ValueError("Stop the capture server with Ctrl+C first")
    for name, digest in take["sha256"].items():
        if hashlib.sha256((folder / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f"Capture file hash mismatch: {name}")
    sessions, sides, clocks = set(), {}, {}
    for e in read_events(folder / "quest_input.jsonl"):
        if e.get("event") == "hand_frame":
            f = e["frame"]
            side = sides.setdefault(f["handedness"], {"valid": 0, "invalid": 0})
            side["valid" if f["tracking_valid"] else "invalid"] += 1
        if e.get("event") == "native_packet" and e["packet"].get("type") == "frame":
            sid = e["session_id"]
            sessions.add(sid)
            clocks.setdefault(sid, []).append([e["packet"]["source_time_ms"], e["receive_time_s"]])
    markers = [json.loads(line) for line in (folder / "markers.jsonl").read_text().splitlines()]
    report = {
        "take_id": take["take_id"],
        "hashes_pass": True,
        "hands": sides,
        "source_sessions": sorted(sessions),
        "markers": len(markers),
        "browser_ids": sorted({m["browser"]["browser_id"] for m in markers}),
        "stages_observed": [
            m["browser"].get("stage") for m in markers if m["browser"]["event"] == "stage"
        ],
        "routine_end_observed": any(m["browser"]["event"] == "routine_end" for m in markers),
        "clock_ranges": {
            sid: {
                "source_min_ms": p[0][0],
                "source_max_ms": p[-1][0],
                "receive_span_s": p[-1][1] - p[0][1],
            }
            for sid, p in clocks.items()
        },
        "multi_session_warning": len(sessions) != 1,
        "stage_labels": "Prompted actions, not manually verified gesture ground truth",
        "video_status": "No video checked by this audit",
    }
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("take", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--video", type=Path)
    parser.add_argument("--anchor", action="append", default=[], help="VIDEO_SECONDS:SOURCE_MS")
    args = parser.parse_args()
    result = audit(args.take)
    if args.video:
        if len(result["source_sessions"]) != 1 or len(result["browser_ids"]) != 1:
            parser.error("Use a take containing exactly one XR session and one capture browser")
        anchors = [tuple(map(float, a.split(":"))) for a in args.anchor]
        sync = fit_anchors(anchors)
        clock = result["clock_ranges"][result["source_sessions"][0]]
        for _, source in anchors:
            if not clock["source_min_ms"] - 1000 <= source <= clock["source_max_ms"] + 1000:
                parser.error("Anchor source clock is outside this take")
        import imageio_ffmpeg

        reader = imageio_ffmpeg.read_frames(str(args.video.resolve()))
        try:
            info = next(reader)
        finally:
            reader.close()
        if info.get("duration", 0) <= 0 or any(a[0] > info["duration"] for a in anchors):
            parser.error("Anchor is outside video duration")
        result.update(
            video={
                "path": str(args.video.resolve()),
                "sha256": hashlib.sha256(args.video.read_bytes()).hexdigest(),
                "metadata": info,
            },
            sync=sync,
        )
        result["video_status"] = (
            "Decodable file with manually supplied anchors; inspect actual hand visibility"
        )
    elif args.anchor:
        parser.error("--anchor requires --video")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
