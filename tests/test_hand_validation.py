import asyncio
import json
import time
import urllib.request

import numpy as np

from benchmark.geort_support.input import canonical_points
from benchmark.paths import ROOT
from benchmark.tracking.hand_validation import InspectionServer
from benchmark.tracking.receiver_state import ReceiverState
from benchmark.tracking.synthetic import synthetic_packet

SAMPLES = ROOT / "results/hand_validation_public_20261018.json"


def test_public_clips_are_training_only_and_match_training_export():
    samples = json.loads(SAMPLES.read_text())
    study = json.loads((ROOT / "results/geort_data_size_20261018/study.json").read_text())
    assert samples["role"] == "train_only_visual_diagnosis"
    assert samples["canonical_training_export_max_difference_m"] < 1e-7
    for clip in samples["clips"]:
        assert clip["episode"] in study["split_episode_ids"]["train"]
        assert clip["episode"] not in study["split_episode_ids"]["test"]
        for frame in clip["frames"]:
            for side in ("right", "left"):
                points = np.array(frame[side])
                assert points.shape == (21, 3) and np.isfinite(points).all()


def test_live_display_uses_existing_adapter_and_preserves_source():
    state = ReceiverState()
    now = time.monotonic()
    state.connect("diagnostic", now)
    state.accept(synthetic_packet(), "diagnostic", now)
    before = state.latest["right"].joint_positions.copy()
    server = InspectionServer(state, SAMPLES)
    result = server.geometry()
    np.testing.assert_allclose(
        result["hands"]["right"]["points"], canonical_points(state.latest["right"])
    )
    assert result["hands"]["right"]["canonical_adapter_difference_m"] == 0
    assert result["reflection_applied"] is False
    np.testing.assert_array_equal(state.latest["right"].joint_positions, before)
    state.expire(now + 0.3)
    assert not server.geometry()["hands"]["right"]["valid"]


def test_http_monitor_routes_and_source_packet():
    async def check():
        from websockets.asyncio.client import connect

        server = InspectionServer(ReceiverState(), SAMPLES)
        port = await server.start("127.0.0.1", 0)

        def get(path):
            with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=2) as response:
                return response.headers["Content-Type"], response.read()

        try:
            kind, page = await asyncio.to_thread(get, "/inspect")
            assert "text/html" in kind and b"/validation.js" in page
            async with connect(f"ws://127.0.0.1:{port}/ws?role=source") as socket:
                await socket.recv()
                await socket.send(json.dumps(synthetic_packet()))
                await asyncio.sleep(0.03)
                _, body = await asyncio.to_thread(get, "/validation.json")
                status = json.loads(body)
                assert status["hands"]["right"]["valid"]
                assert status["hands"]["right"]["canonical_adapter_difference_m"] == 0
        finally:
            await server.close()

    asyncio.run(check())
