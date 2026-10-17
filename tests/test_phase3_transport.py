import asyncio
import hashlib
import json
import ssl
import subprocess
import sys
import urllib.request

import pytest
from websockets.asyncio.client import connect

from benchmark.paths import ROOT
from benchmark.tracking.quest_receiver import QuestReceiver, tls_context
from benchmark.tracking.receiver_state import ReceiverState
from benchmark.tracking.recorder import HandRecorder, read_events
from benchmark.tracking.synthetic import synthetic_packet


@pytest.fixture(scope="module")
def tls_pair(tmp_path_factory):
    folder = tmp_path_factory.mktemp("phase3-tls") / "bundle"
    cert, key = folder / "cert.pem", folder / "key.pem"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/setup_quest_tls.py"),
            "--host-ip",
            "127.0.0.1",
            "--output",
            str(folder),
        ],
        check=True,
        capture_output=True,
    )
    assert key.stat().st_mode & 0o777 == 0o600
    assert folder.stat().st_mode & 0o777 == 0o700
    return cert, key


def test_tls_generation_refuses_to_replace_existing_files(tls_pair):
    cert, key = tls_pair
    before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in (cert, key)]
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/setup_quest_tls.py"),
            "--host-ip",
            "127.0.0.1",
            "--output",
            str(cert.parent),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0 and "existing TLS files are preserved" in result.stderr
    assert before == [hashlib.sha256(p.read_bytes()).hexdigest() for p in (cert, key)]


async def receive_type(websocket, kind):
    async def match():
        while True:
            message = json.loads(await websocket.recv())
            if message["type"] == kind:
                return message

    return await asyncio.wait_for(match(), 3)


def test_real_https_wss_receive_timeout_recording_and_second_viewer_do_not_evict_source(
    tls_pair, tmp_path
):
    async def scenario():
        cert, key = tls_pair
        client_tls = ssl.create_default_context(cafile=str(cert))
        path = tmp_path / "network.jsonl"
        with HandRecorder(path, source_kind="synthetic_webxr_wss_test") as recorder:
            state = ReceiverState(recorder=recorder, timeout=0.1)
            server = QuestReceiver(state)
            port = await server.start(context=tls_context(cert, key))
            try:
                base = f"https://127.0.0.1:{port}"

                def get(path):
                    with urllib.request.urlopen(
                        base + path, context=client_tls, timeout=3
                    ) as response:
                        return response.status, response.read()

                status, html = await asyncio.to_thread(get, "/")
                assert status == 200 and "Quest 손 추적".encode() in html
                _, protocol = await asyncio.to_thread(get, "/protocol.json")
                assert len(json.loads(protocol)["joint_names"]) == 25
                async with connect(
                    f"wss://127.0.0.1:{port}/ws?role=source", ssl=client_tls, proxy=None
                ) as source:
                    session = await receive_type(source, "session")
                    await source.send(json.dumps(synthetic_packet()))
                    async with connect(
                        f"wss://127.0.0.1:{port}/ws?role=viewer", ssl=client_tls, proxy=None
                    ) as viewer:
                        await receive_type(viewer, "session")
                        _, body = await asyncio.to_thread(get, "/status")
                        current = json.loads(body)
                        assert current["source_connected"] and current["accepted_packets"] == 1
                        assert state.session_id == session["session_id"]
                        assert state.latest["right"].joint_positions.shape == (21, 3)
                        await asyncio.sleep(0.15)
                        _, body = await asyncio.to_thread(get, "/status")
                        assert json.loads(body)["hands"]["right"]["reason"] == "receive_timeout"
                        await source.send(json.dumps(synthetic_packet(1, 0.2)))
                        await asyncio.sleep(0.01)
                        assert state.latest["right"].tracking_valid
                    assert state.session_id == session["session_id"]
                    async with connect(
                        f"wss://127.0.0.1:{port}/ws?role=source", ssl=client_tls, proxy=None
                    ) as other:
                        error = await receive_type(other, "error")
                        assert "Another Quest" in error["message"]
                        assert state.session_id == session["session_id"]
                await asyncio.sleep(0.01)
                assert state.session_id is None
            finally:
                await server.close()
        events = list(read_events(path))
        assert len([e for e in events if e["event"] == "native_packet"]) == 2
        assert any(e.get("reason") == "receive_timeout" for e in events)
        assert any(e.get("reason") == "source_disconnected" for e in events)

    asyncio.run(scenario())


def test_malformed_json_is_counted_and_receiver_accepts_next_valid_frame(tls_pair):
    async def scenario():
        cert, key = tls_pair
        client_tls = ssl.create_default_context(cafile=str(cert))
        server = QuestReceiver()
        port = await server.start(context=tls_context(cert, key))
        try:
            async with connect(
                f"wss://127.0.0.1:{port}/ws?role=source", ssl=client_tls, proxy=None
            ) as source:
                await receive_type(source, "session")
                for raw in ("not json", '{"version": NaN}', b"binary"):
                    await source.send(raw)
                    assert (await receive_type(source, "error"))["message"]
                assert server.state.rejected_packets == 3
                await source.send(json.dumps(synthetic_packet()))
                await asyncio.sleep(0.02)
                assert server.state.accepted_packets == 1
        finally:
            await server.close()

    asyncio.run(scenario())
