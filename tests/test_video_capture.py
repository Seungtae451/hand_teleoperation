import asyncio
import json

import numpy as np
import pytest
from websockets.asyncio.client import connect

from benchmark.tracking.receiver_state import ReceiverState
from benchmark.tracking.recorder import HandRecorder, replay_frames
from benchmark.tracking.synthetic import synthetic_packet
from benchmark.tracking.video_capture import CaptureReceiver, schedule
from scripts.inspect_comparison_take import fit_anchors


def test_anchor_mapping_and_validation():
    result = fit_anchors([(2, 1500), (12, 11500), (22, 21500)])
    assert result["scale_ms_per_video_s"] == pytest.approx(1000)
    assert result["offset_ms"] == pytest.approx(-500)
    for anchors in [
        [(1, 2)],
        [(1, 1000), (1, 2000)],
        [(1, 1000), (2, 500)],
        [(1, 1000), (2, np.nan)],
        [(1, 1000), (2, 20000)],
    ]:
        with pytest.raises(ValueError):
            fit_anchors(anchors)


def test_capture_side_channel_preserves_source(tmp_path):
    async def scenario():
        with HandRecorder(tmp_path / "input.jsonl", source_kind="synthetic_webxr") as recorder:
            state = ReceiverState(recorder=recorder)
            receiver = CaptureReceiver(state, tmp_path, {"stages": schedule("preflight", 3)})
            port = await receiver.start()
            try:
                async with connect(f"ws://127.0.0.1:{port}/ws?role=source") as source:
                    session = json.loads(await source.recv())["session_id"]
                    packet = synthetic_packet(0, 0)
                    await source.send(json.dumps(packet))
                    async with connect(
                        f"ws://127.0.0.1:{port}/capture-events", origin=f"https://127.0.0.1:{port}"
                    ) as events:
                        marker = {
                            "event": "stage",
                            "source_time_ms": 0,
                            "browser_id": "test",
                            "stage": "sync_start",
                        }
                        await events.send(json.dumps(marker))
                        assert json.loads(await events.recv())["type"] == "ack"
                        assert receiver.marker_count == 1
                        await events.send(json.dumps({"event": "unknown", "source_time_ms": 0}))
                        await events.wait_closed()
                        assert events.close_code == 1008
                    assert state.session_id == session
            finally:
                await receiver.close()
                receiver.marker_stream.close()
        frames = list(replay_frames(tmp_path / "input.jsonl"))
        assert any(f.tracking_valid and f.handedness == "right" for f in frames)
        assert (
            json.loads((tmp_path / "markers.jsonl").read_text())["browser"]["stage"] == "sync_start"
        )

    asyncio.run(scenario())
