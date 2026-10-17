"""Phase 4 logs retain vendor raw target, clipped retarget target, command, and actual."""

import csv
import json
from pathlib import Path

from benchmark.paths import writable_output


class ManusLog:
    def __init__(self, path, controller, source, *, input_sha256=None):
        self.path = writable_output(Path(path))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.path.open("x", buffering=1)
        self.csv_stream = self.path.with_suffix(".csv").open("x", newline="")
        self.csv = csv.writer(self.csv_stream)
        names = controller.runner.robot.joint_names
        self.csv.writerow(
            [
                "time",
                "control_status",
                *(
                    f"{kind}/{name}"
                    for kind in ("retarget_target", "command", "actual")
                    for name in names
                ),
            ]
        )
        self.write(
            {
                "event": "header",
                "schema": "manus_quest_simulation_v1",
                "source": str(source),
                "input_sha256": input_sha256,
                "model": controller.runner.robot.provenance,
                "vendor": controller.retargeter.vendor.provenance,
                "config": controller.retargeter.config,
                "timeout_s": controller.timeout,
                "limitation": "Geometry-derived MANUS proxy; no real glove or hardware validation",
            }
        )

    def write(self, entry):
        self.stream.write(json.dumps(entry, allow_nan=False) + "\n")
        if "simulation" in entry:
            sample = entry["simulation"]
            self.csv.writerow(
                [
                    sample["time"],
                    entry["control_status"],
                    *entry["retarget_q_target"],
                    *sample["q_command"],
                    *sample["q_actual"],
                ]
            )

    def close(self):
        self.stream.close()
        self.csv_stream.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
