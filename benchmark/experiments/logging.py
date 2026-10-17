"""JSONL command replay and CSV export with target/actual separation."""

import csv
import json
from pathlib import Path

from benchmark.paths import writable_output
from benchmark.simulation.mujoco_runner import SimulationSample
from benchmark.simulation.robot_model import RobotModel


class SimulationLogger:
    def __init__(self, output: Path, robot: RobotModel, control_steps: int, seed: int = 0):
        output = writable_output(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        self.stream = output.open("w")
        self.csv_stream = output.with_suffix(".csv").open("w", newline="")
        self.writer = csv.writer(self.csv_stream)
        names = robot.joint_names
        fields = ["time"]
        for quantity in ("q_target", "q_command", "q_actual", "q_velocity", "clipped"):
            fields.extend(f"{quantity}/{name}" for name in names)
        for quantity in ("tips_command_world", "tips_actual_world"):
            fields.extend(
                f"{quantity}/{finger}/{axis}" for finger in robot.fingers for axis in "xyz"
            )
        self.writer.writerow([*fields, "contact_count"])
        self.metadata = {
            "schema": "tesollo_simulation_v1",
            "joint_names": names,
            "finger_names": robot.fingers,
            "position_unit": "m",
            "joint_unit": "rad",
            "time_unit": "s",
            "tip_frame": "world",
            "seed": seed,
            "control_steps": control_steps,
            "timestep": float(robot.model.opt.timestep),
            "provenance": robot.provenance,
        }
        self.stream.write(json.dumps({"metadata": self.metadata}) + "\n")

    def write(self, sample: SimulationSample) -> None:
        self.stream.write(json.dumps(sample.to_dict(), allow_nan=False) + "\n")
        row = [sample.time]
        for value in (
            sample.q_target,
            sample.q_command,
            sample.q_actual,
            sample.q_velocity,
            sample.clipped,
            sample.tips_command_world,
            sample.tips_actual_world,
        ):
            row.extend(value.ravel().tolist())
        self.writer.writerow([*row, sample.contact_count])

    def close(self) -> None:
        self.stream.close()
        self.csv_stream.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def read_log(path: Path) -> tuple[dict, list[dict]]:
    with Path(path).open() as stream:
        metadata = json.loads(next(stream))["metadata"]
        if metadata["schema"] != "tesollo_simulation_v1":
            raise ValueError("Unsupported simulation log schema")
        return metadata, [json.loads(line) for line in stream if line.strip()]
