"""Create a relocatable derived URDF/config without changing upstream assets."""

import hashlib
import json
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

from benchmark.geort_support.input import INPUT_CONTRACT
from benchmark.geort_support.source import verify_source
from benchmark.paths import ROOT, writable_output

TEMPLATE = ROOT / "configs/geort_dg5f_right.json"


def validate_config(config):
    expected = json.loads(TEMPLATE.read_text())
    for name in ("name", "base_link", "joint_order", "fingertip_link"):
        if config[name] != expected[name]:
            raise ValueError(f"GeoRT DG-5F configuration mismatch: {name}")
    source = ROOT / expected["urdf_path"]
    tree = ET.parse(source)
    joints = {j.get("name"): j for j in tree.getroot().findall("joint")}
    movable = {name for name, j in joints.items() if j.get("type") != "fixed"}
    if movable != set(config["joint_order"]) or len(movable) != 20:
        raise ValueError("Expected the 20 official independent joints")
    by_child = {j.find("child").get("link"): j for j in joints.values()}
    for tip in config["fingertip_link"]:
        cursor, chain = tip["link"], []
        while cursor in by_child:
            node = by_child[cursor]
            if node.get("type") != "fixed":
                chain.append(node.get("name"))
            cursor = node.find("parent").get("link")
        if chain[::-1] != tip["joint"]:
            raise ValueError("Fingertip driving chain does not match official URDF")
    bounds = np.array(
        [
            [float(joints[n].find("limit").get(k)) for k in ("lower", "upper")]
            for n in config["joint_order"]
        ]
    )
    if "joint" in config:
        actual = np.array([config["joint"]["lower"], config["joint"]["upper"]]).T
        if actual.shape != (20, 2) or not np.allclose(actual, bounds, atol=1e-7):
            raise ValueError("Exported joint limits do not match official DG-5F")
    return source, tree, bounds


def prepare(folder):
    folder = writable_output(Path(folder))
    if folder.exists():
        raise FileExistsError("Use a new GeoRT workspace; never overwrite checkpoints or inputs")
    config = json.loads(TEMPLATE.read_text())
    source, tree, bounds = validate_config(config)
    provenance = verify_source()
    # SAPIEN cannot resolve this source's package:// paths without ROS/package roots.
    # Only filename resolution changes in this derived asset. Kinematics stay identical.
    replacements = []
    mesh_copies = {}
    for mesh in tree.getroot().iter("mesh"):
        original = mesh.get("filename")
        relative = original.removeprefix("package://")
        resolved = (source.parent / relative).resolve()
        if not resolved.is_file():
            raise FileNotFoundError(f"Official mesh not found: {resolved}")
        local = folder / "meshes" / resolved.name
        mesh_copies[local] = resolved
        replacements.append(
            {
                "original": original,
                "source": str(resolved),
                "resolved": str(local),
                "sha256": hashlib.sha256(resolved.read_bytes()).hexdigest(),
            }
        )
        mesh.set("filename", str(local))
    folder.mkdir(parents=True)
    (folder / "meshes").mkdir()
    for local, source_mesh in mesh_copies.items():
        shutil.copyfile(source_mesh, local)
    urdf = folder / "dg5f_right_resolved.urdf"
    tree.write(urdf, encoding="utf-8", xml_declaration=True)
    config["urdf_path"] = str(urdf)
    config["joint"] = {"lower": bounds[:, 0].tolist(), "upper": bounds[:, 1].tolist()}
    path = folder / "config.json"
    path.write_text(json.dumps(config, indent=2) + "\n")
    manifest = {
        "purpose": "GeoRT integration preparation; no collection, training or benchmark",
        "source": provenance,
        "urdf_source": str(source.relative_to(ROOT)),
        "urdf_source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "derived_urdf_sha256": hashlib.sha256(urdf.read_bytes()).hexdigest(),
        "config_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "derived_asset_change": "mesh byte copies/URIs only; model fields unchanged",
        "mesh_resolution": replacements,
        "input_contract": INPUT_CONTRACT,
        "training_executed": False,
        "inference_executed": False,
        "performance_evaluation_executed": False,
    }
    (folder / "preparation.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return config, manifest
