import ast
import asyncio
import json
import math
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest
from websockets.asyncio.client import connect

from benchmark.experiments.manus_cli import live, main
from benchmark.experiments.manus_control import ManusController
from benchmark.experiments.manus_fixtures import pose_frame
from benchmark.paths import ROOT
from benchmark.retargeting.manus import DEFAULT_MANUS_CONFIG, ManusRetargeter, register_manus
from benchmark.retargeting.manus_vendor import SOURCE, OfficialManusMapping
from benchmark.retargeting.quest_ergonomics import geometric_features
from benchmark.tracking.coordinate_transform import quaternion_matrix
from benchmark.tracking.recorder import HandRecorder, frame_to_dict
from benchmark.tracking.synthetic import synthetic_packet
from benchmark.tracking.webxr_protocol import COMMON_INDICES


def test_official_mapping_matches_original_static_method_for_random_and_branch_inputs():
    tree = ast.parse(SOURCE.read_text())
    original_class = next(
        n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ManusBimanualRetarget"
    )
    function = next(
        n
        for n in original_class.body
        if isinstance(n, ast.FunctionDef) and n.name == "_compute_mqd_from_q"
    )
    reference_class = ast.ClassDef(
        name="Reference", bases=[], keywords=[], body=[deepcopy(function)], decorator_list=[]
    )
    namespace = {"math": math}
    exec(
        compile(
            ast.fix_missing_locations(ast.Module(body=[reference_class], type_ignores=[])),
            str(SOURCE),
            "exec",
        ),
        namespace,
    )
    reference = namespace["Reference"]._compute_mqd_from_q
    adapter = OfficialManusMapping()
    rng = np.random.default_rng(20261017)
    for side in ("left", "right"):
        for degrees in rng.uniform(-60, 120, (100, 20)):
            np.testing.assert_array_equal(adapter(degrees, side), reference(degrees.tolist(), side))
    for pip in (24, 25, 26):
        values = np.zeros(20)
        values[16:19] = [-12, 56, pip]
        np.testing.assert_array_equal(adapter(values), reference(values.tolist(), "right"))


def test_changed_vendor_source_requires_review(tmp_path):
    copied = tmp_path / "vendor.py"
    copied.write_bytes(SOURCE.read_bytes() + b"\n# modification\n")
    with pytest.raises(ValueError, match="review"):
        OfficialManusMapping(copied)


def test_adapter_preserves_vendor_offsets_and_uses_only_common_limits(robot):
    retargeter = ManusRetargeter(robot)
    for kind in ("open", "closed", "pinch"):
        frame = pose_frame(kind)
        result = retargeter.retarget(frame)
        features = geometric_features(frame)
        raw = np.array(retargeter.vendor(features))
        np.testing.assert_array_equal(result.metadata["ergonomics_proxy_deg"], features)
        np.testing.assert_array_equal(result.metadata["q_vendor_raw"], raw)
        np.testing.assert_array_equal(result.q_target, robot.validate_target(raw, clip=True))
    opened = retargeter.retarget(pose_frame("open"))
    assert opened.metadata["q_vendor_raw"][0] == pytest.approx(math.radians(58.5))
    assert opened.metadata["q_vendor_raw"][1] == pytest.approx(-math.radians(32))


def test_geometry_features_are_rigid_invariant_and_preserve_left_right_labels():
    frame = pose_frame("closed")
    expected = geometric_features(frame)
    q = np.array([0.1, 0.3, 0.2, 0.8])
    q /= np.linalg.norm(q)
    rotation = quaternion_matrix(q)
    transformed = replace(frame, joint_positions=frame.joint_positions @ rotation.T + [1.0, 2, 3])
    np.testing.assert_allclose(geometric_features(transformed), expected, atol=1e-12)
    left_points = frame.joint_positions.copy()
    left_points[:, 1] *= -1
    np.testing.assert_allclose(
        geometric_features(replace(frame, handedness="left", joint_positions=left_points)),
        expected,
        atol=1e-12,
    )


def test_project_calibration_and_gain_corrections_are_rejected(robot):
    config = json.loads(DEFAULT_MANUS_CONFIG.read_text())
    for key in ("feature_reference_deg", "feature_gain", "ergonomics_bias_deg"):
        with pytest.raises(ValueError, match="forbidden"):
            ManusRetargeter(robot, {**config, key: [0] * 20})


def test_invalid_wrong_hand_and_time_regression_rejected(robot):
    retargeter = ManusRetargeter(robot)
    frame = pose_frame("open", 10)
    retargeter.retarget(frame)
    for invalid in (
        replace(frame, tracking_valid=False),
        replace(frame, handedness="left"),
        replace(frame, timestamp=9),
    ):
        with pytest.raises(ValueError):
            retargeter.retarget(invalid)
    retargeter.reset()
    retargeter.retarget(replace(frame, timestamp=9))


def test_explicit_registry_install_preserves_other_method_slots(robot, monkeypatch):
    import benchmark.retargeting.registry as registry

    monkeypatch.setattr(registry, "_FACTORIES", {})
    register_manus()
    assert isinstance(registry.create("manus", robot=robot), ManusRetargeter)
    with pytest.raises(NotImplementedError):
        registry.create("anydex")


def test_rate_limit_tracking_loss_and_bad_geometry_hold_last_applied_command(robot):
    controller = ManusController(robot, DEFAULT_MANUS_CONFIG)
    entry = controller.tick(pose_frame("closed", 1), 1)
    assert entry["control_status"] == "TRACKING"
    assert np.max(np.abs(controller.command)) <= np.pi * 0.02 + 1e-12
    previous = controller.command.copy()
    entry = controller.tick(pose_frame("closed", 1), 1.3)
    assert entry["control_status"] == "HOLD_TRACKING_LOST"
    np.testing.assert_array_equal(controller.command, previous)
    bad = replace(pose_frame("open", 2), joint_positions=np.zeros((21, 3)))
    entry = controller.tick(bad, 2)
    assert entry["control_status"] == "HOLD_INPUT_REJECTED"
    np.testing.assert_array_equal(controller.command, previous)
    controller.tick(pose_frame("closed", 3), 3)
    assert controller.status == "TRACKING"


def test_offline_retarget_replay_is_deterministic_and_preserves_target_actual_separation(tmp_path):
    recording = tmp_path / "input.jsonl"
    with HandRecorder(
        recording, source_kind="synthetic_geometry", target_frame="world_rh"
    ) as recorder:
        for i in range(100):
            recorder.write(
                {
                    "event": "hand_frame",
                    "frame": frame_to_dict(pose_frame("open" if i < 25 else "closed", i * 0.02, i)),
                }
            )
    runs = []
    for name in ("one", "two"):
        directory = tmp_path / name
        main(["replay", str(recording), "--duration", "1.9", "--output", str(directory)])
        rows = [
            json.loads(line) for line in (directory / "simulation.jsonl").read_text().splitlines()
        ][1:]
        runs.append(rows)
    for a, b in zip(*runs):
        assert a["retarget_q_target"] == b["retarget_q_target"]
        assert a["simulation"] == b["simulation"]
    assert any(row["retarget_q_target"] != row["simulation"]["q_actual"] for row in runs[0])


def test_combined_live_server_maps_without_calibration_and_holds_on_loss(
    tmp_path, monkeypatch
):
    import socket
    import ssl
    import subprocess
    import sys
    import urllib.request

    tls_folder = tmp_path / "tls"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/setup_quest_tls.py"),
            "--host-ip",
            "127.0.0.1",
            "--output",
            str(tls_folder),
        ],
        check=True,
        capture_output=True,
    )
    monkeypatch.setenv("XR_TELEOP_CERT", str(tls_folder / "cert.pem"))
    monkeypatch.setenv("XR_TELEOP_KEY", str(tls_folder / "key.pem"))
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    directory = tmp_path / "live"

    async def scenario():
        args = SimpleNamespace(
            output=directory,
            config=DEFAULT_MANUS_CONFIG,
            port=port,
            viewer=False,
            video=False,
            duration=2,
        )
        task = asyncio.create_task(live(args))
        tls = ssl.create_default_context(cafile=str(tls_folder / "cert.pem"))
        websocket = None
        try:
            for _ in range(100):
                try:
                    websocket = await connect(
                        f"wss://127.0.0.1:{port}/ws?role=source", ssl=tls, proxy=None
                    )
                    break
                except OSError:
                    await asyncio.sleep(0.02)
            assert websocket is not None
            while json.loads(await websocket.recv())["type"] != "session":
                pass

            def get_page():
                with urllib.request.urlopen(f"https://127.0.0.1:{port}/", context=tls) as response:
                    assert response.headers.get_content_type() == "text/html"
                    assert "PHASE 4" in response.read().decode()

            await asyncio.to_thread(get_page)
            for i in range(70):
                packet = synthetic_packet(i, i * 0.02, lost=i >= 60)
                packet["hands"]["left"] = {"valid": False, "reason": "test_right_only"}
                if i < 60:
                    pose = pose_frame("open" if i < 35 else "closed")
                    native = np.zeros((25, 3))
                    native[list(COMMON_INDICES)] = pose.joint_positions
                    packet["hands"]["right"]["positions"] = native.tolist()
                await websocket.send(json.dumps(packet))
                await asyncio.sleep(0.02)
        finally:
            if websocket:
                await websocket.close()
            await asyncio.wait_for(task, 5)

    asyncio.run(scenario())
    rows = [json.loads(line) for line in (directory / "simulation.jsonl").read_text().splitlines()]
    assert not any(row.get("event") == "calibration_complete" for row in rows)
    control = [row for row in rows if "simulation" in row]
    assert {"TRACKING", "HOLD_TRACKING_LOST"} <= {
        row["control_status"] for row in control
    }
    assert max(np.max(np.abs(row["simulation"]["q_actual"])) for row in control) > 0.3
    assert not (directory / "calibration.json").exists()
