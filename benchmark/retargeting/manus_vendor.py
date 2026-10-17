"""Reuse the exact pinned vendor calculation without importing its ROS node."""

import ast
import copy
import hashlib
import math
from pathlib import Path

from benchmark.paths import ROOT

SOURCE = ROOT / "external/dg5f_ros2/dg5f_driver/script/manus_retarget/manus_retarget.py"
EXPECTED_SHA256 = "730f2b4e1c89669f2249c0e8476ded58333c019bbaf501523075abb2a57a3ca4"


class OfficialManusMapping:
    def __init__(self, source: Path = SOURCE):
        content = source.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if digest != EXPECTED_SHA256:
            raise ValueError("Vendor MANUS source changed; review it before using this adapter")
        tree = ast.parse(content, filename=str(source))
        cls = next(
            n
            for n in tree.body
            if isinstance(n, ast.ClassDef) and n.name == "ManusBimanualRetarget"
        )
        function = copy.deepcopy(
            next(
                n
                for n in cls.body
                if isinstance(n, ast.FunctionDef) and n.name == "_compute_mqd_from_q"
            )
        )
        # Only remove the staticmethod binding. The entire calculation AST is unchanged.
        function.decorator_list = []
        module = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
        namespace = {"math": math}
        exec(compile(module, str(source), "exec"), namespace)
        self.function = namespace[function.name]
        self.provenance = {
            "repository": "https://github.com/tesollodelto/dg5f_ros2",
            "commit": "0cb45ae9474caa92410dfa820346da8ffbae8405",
            "file": str(source.relative_to(ROOT)),
            "sha256": digest,
            "function": "ManusBimanualRetarget._compute_mqd_from_q",
            "reuse": "unmodified calculation AST; staticmethod binding removed",
        }

    def __call__(self, degrees, side="right"):
        if side not in ("left", "right"):
            raise ValueError("Unknown hand side")
        return self.function(list(degrees), side)
