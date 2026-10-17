"""Generate a separate MuJoCo model; never edit the upstream URDF or XML."""

import hashlib
import json
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import mujoco

from benchmark.paths import DEFAULT_CONFIG, DEFAULT_MODEL, ROOT, writable_output
from benchmark.simulation.urdf import UrdfModel


def build_model(config_path: Path = DEFAULT_CONFIG, output: Path = DEFAULT_MODEL) -> Path:
    output = writable_output(Path(output))
    config = json.loads(Path(config_path).read_text())
    urdf_path = (ROOT / config["urdf"]).resolve()
    source = UrdfModel(urdf_path)
    names = tuple(config["joint_names"])
    limits = source.validate_order(names)
    if source.base_link != config["base_link"]:
        raise ValueError("Configured base does not match URDF root")
    for link in [config["palm_link"], *config["tip_links"]]:
        if link not in source.links:
            raise ValueError(f"Configured link absent from URDF: {link}")
    output.parent.mkdir(parents=True, exist_ok=True)
    meshes = output.parent / "meshes"
    meshes.mkdir(exist_ok=True)

    # MuJoCo cannot read the Collada visual meshes. Keep the official STL collision
    # surfaces for both rendering and collision, with unchanged URDF kinematics/inertia.
    root = ET.parse(urdf_path).getroot()
    for link in root.findall("link"):
        for visual in link.findall("visual"):
            link.remove(visual)
    source_hashes = {
        str(urdf_path.relative_to(ROOT)): hashlib.sha256(urdf_path.read_bytes()).hexdigest()
    }
    for mesh in root.findall(".//mesh"):
        uri = mesh.attrib["filename"]
        path = urdf_path.parent / uri.removeprefix("package://")
        if not path.is_file():
            raise FileNotFoundError(path)
        destination = meshes / path.name
        shutil.copy2(path, destination)
        source_hashes[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
        mesh.set("filename", str(destination))
    extension = ET.SubElement(root, "mujoco")
    ET.SubElement(
        extension, "compiler", fusestatic="false", discardvisual="true", strippath="false"
    )
    normalized = output.with_suffix(".normalized.urdf")
    ET.ElementTree(root).write(normalized, encoding="utf-8", xml_declaration=True)
    imported = mujoco.MjModel.from_xml_path(str(normalized))
    mujoco.mj_saveLastXML(str(output), imported)
    mjcf = ET.parse(output).getroot()
    compiler = mjcf.find("compiler")
    compiler.set("meshdir", "meshes")
    compiler.set("strippath", "false")
    for mesh in mjcf.findall("asset/mesh"):
        mesh.set("file", Path(mesh.attrib["file"]).name)
    settings = config["simulation"]
    option = ET.SubElement(
        mjcf,
        "option",
        timestep=str(settings["timestep"]),
        integrator="implicitfast",
        gravity=" ".join(map(str, settings["gravity"])),
    )
    ET.SubElement(option, "flag", contact="enable" if settings["contacts"] else "disable")
    defaults = ET.SubElement(mjcf, "default")
    ET.SubElement(
        defaults, "joint", armature=str(settings["armature"]), damping=str(settings["damping"])
    )
    ET.SubElement(defaults, "geom", rgba="0.6 0.65 0.72 1", friction="0.7 0.01 0.001")
    bodies = {b.attrib["name"]: b for b in mjcf.findall(".//body")}
    for body in bodies.values():
        body.set("gravcomp", "1" if settings["gravity_compensation"] else "0")
    colors = ("1 .35 .2 1", ".2 .8 1 1", ".3 1 .5 1", "1 .8 .2 1", ".8 .4 1 1")
    for finger, link, color in zip(config["fingers"], config["tip_links"], colors):
        ET.SubElement(
            bodies[link],
            "site",
            name=f"tip_{finger}",
            pos="0 0 0",
            size="0.003",
            rgba=color,
            group="0",
        )
    # mj_saveLastXML serializes some numbers at reduced precision. Restore exact
    # source joint bounds; verify FK independently after the full conversion.
    joints = {j.attrib["name"]: j for j in mjcf.findall(".//body/joint")}
    actuators = ET.SubElement(mjcf, "actuator")
    for name, (lower, upper) in zip(names, limits):
        joint_range = f"{lower:.17g} {upper:.17g}"
        joints[name].set("range", joint_range)
        effort = source.by_name[name].effort
        ET.SubElement(
            actuators,
            "position",
            name=f"position_{name}",
            joint=name,
            kp=str(settings["kp"]),
            kv=str(settings["kv"]),
            ctrllimited="true",
            ctrlrange=joint_range,
            forcelimited="true",
            forcerange=f"{-effort} {effort}",
        )
    world = mjcf.find("worldbody")
    ET.SubElement(world, "light", pos="0.5 0.4 0.7", dir="-0.5 -0.4 -0.5", directional="true")
    ET.SubElement(world, "light", pos="-0.4 -0.3 0.5", dir="0.4 0.3 -0.3", directional="true")
    ET.SubElement(
        world,
        "camera",
        name="overview",
        pos="0.5 0.36 0.36",
        xyaxes="-0.584 0.812 0 -0.284 -0.204 0.936",
    )
    ET.indent(mjcf)
    ET.ElementTree(mjcf).write(output, encoding="utf-8", xml_declaration=True)
    compiled = mujoco.MjModel.from_xml_path(str(output))
    if (compiled.nq, compiled.nv, compiled.nu) != (20, 20, 20):
        raise ValueError("Generated model does not have 20 independent actuated joints")
    # Make the retained import artifact portable too.
    for mesh in root.findall(".//mesh"):
        mesh.set("filename", f"meshes/{Path(mesh.attrib['filename']).name}")
    ET.indent(root)
    ET.ElementTree(root).write(normalized, encoding="utf-8", xml_declaration=True)
    license_path = urdf_path.parents[1] / "LICENSE"
    shutil.copy2(license_path, output.parent / "TESOLLO_LICENSE")
    revision = subprocess.check_output(
        ["git", "-C", str(urdf_path.parents[1]), "rev-parse", "HEAD"], text=True
    ).strip()
    metadata = {
        "source_repository": "https://github.com/tesollodelto/tesollo_model",
        "source_commit": revision,
        "source_hashes": source_hashes,
        "mujoco_version": mujoco.__version__,
        "config": config,
        "tip_definition": "Official URDF fingertip link origins, not pad surface centers",
        "derived_changes": [
            "package URI resolution",
            "DAE visuals omitted; official STL used",
            "fixed link frames retained",
            "20 position actuators",
            "five sites at official tip origins",
            "scene and controller parameters",
        ],
    }
    artifacts = [
        output,
        normalized,
        output.parent / "TESOLLO_LICENSE",
        *(meshes / Path(p).name for p in source_hashes if p.endswith(".STL")),
    ]
    metadata["artifact_hashes"] = {
        str(path.relative_to(output.parent)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in artifacts
    }
    output.with_suffix(".provenance.json").write_text(json.dumps(metadata, indent=2) + "\n")
    return output
