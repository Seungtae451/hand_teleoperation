import csv
import json

import numpy as np
import pytest

from benchmark.cli import main
from benchmark.experiments.logging import read_log
from benchmark.retargeting.registry import PHASES, create
from benchmark.tracking.hand_frame import (
    HTS_OPENXR_INDICES,
    HandFrame,
    select_hts_joints,
)


def test_common_frame_preserves_unavailable_rotation_and_explicit_source_frame():
    frame = HandFrame(1.0, "right", np.zeros((21, 3)), np.zeros(3), np.array([0, 0, 0, 1]), True)
    assert frame.joint_rotations is None
    assert frame.coordinate_frame == "unity_wrist_lh"
    source = np.arange(26 * 3).reshape(26, 3)
    np.testing.assert_array_equal(select_hts_joints(source), source[list(HTS_OPENXR_INDICES)])
    assert select_hts_joints(source).shape == (21, 3)
    with pytest.raises(ValueError):
        select_hts_joints(np.zeros((21, 3)))
    with pytest.raises(ValueError):
        HandFrame(0, "right", np.zeros((26, 3)), np.zeros(3), np.array([0, 0, 0, 1]), True)


@pytest.mark.parametrize("method", PHASES)
def test_unimplemented_adapters_fail_explicitly(method):
    with pytest.raises(NotImplementedError, match="not implemented"):
        create(method)


def test_cli_log_and_replay_reproduce_actuator_states_and_separate_fk(model_path, tmp_path):
    original = tmp_path / "original.jsonl"
    replay = tmp_path / "replay.jsonl"
    main(["demo", "--model", str(model_path), "--duration", "0.4", "--log", str(original)])
    main(["replay", str(original), "--model", str(model_path), "--log", str(replay)])
    meta1, rows1 = read_log(original)
    meta2, rows2 = read_log(replay)
    assert meta1 == meta2
    assert len(rows1) == len(rows2) == 20
    assert rows1 == rows2
    assert rows1[2]["q_command"] != rows1[2]["q_actual"]
    assert rows1[2]["tips_command_world"] != rows1[2]["tips_actual_world"]
    with original.with_suffix(".csv").open() as stream:
        csv_rows = list(csv.reader(stream))
    assert len(csv_rows) == 21
    assert len(csv_rows[0]) == len(csv_rows[1]) == 132
    assert "q_actual/rj_dg_1_1" in csv_rows[0]
    with pytest.raises(ValueError, match="differ"):
        main(["replay", str(original), "--model", str(model_path), "--log", str(original)])


def test_replay_rejects_different_simulation_parameters(model_path, tmp_path):
    original = tmp_path / "original.jsonl"
    main(["demo", "--model", str(model_path), "--duration", "0.1", "--log", str(original)])
    lines = original.read_text().splitlines()
    header = json.loads(lines[0])
    header["metadata"]["provenance"]["config"]["simulation"]["kp"] = 999
    lines[0] = json.dumps(header)
    original.write_text("\n".join(lines) + "\n")
    with pytest.raises(ValueError, match="Replay requires"):
        main(
            [
                "replay",
                str(original),
                "--model",
                str(model_path),
                "--log",
                str(tmp_path / "different.jsonl"),
            ]
        )
