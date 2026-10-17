"""W3C WebXR 25-joint wire contract and explicit common 21-point mapping."""

import numpy as np

from benchmark.tracking.coordinate_transform import transform_world_frame
from benchmark.tracking.hand_frame import HandFrame

WEBXR_JOINT_NAMES = (
    "wrist",
    "thumb-metacarpal",
    "thumb-phalanx-proximal",
    "thumb-phalanx-distal",
    "thumb-tip",
    *(
        f"{finger}-finger-{part}"
        for finger in ("index", "middle", "ring", "pinky")
        for part in (
            "metacarpal",
            "phalanx-proximal",
            "phalanx-intermediate",
            "phalanx-distal",
            "tip",
        )
    ),
)
COMMON_JOINT_NAMES = tuple(
    n for n in WEBXR_JOINT_NAMES if n == "thumb-metacarpal" or not n.endswith("metacarpal")
)
COMMON_INDICES = tuple(WEBXR_JOINT_NAMES.index(n) for n in COMMON_JOINT_NAMES)
PROTOCOL_VERSION = 1


def protocol_description():
    return {
        "version": PROTOCOL_VERSION,
        "source": "webxr",
        "joint_names": WEBXR_JOINT_NAMES,
        "common_joint_names": COMMON_JOINT_NAMES,
        "common_indices": COMMON_INDICES,
        "units": "m",
        "quaternion": "xyzw",
        "coordinate_system": "webxr_reference_rh",
        "maximum_send_hz": 60,
    }


def validate_envelope(packet):
    if (
        not isinstance(packet, dict)
        or type(packet.get("version")) is not int
        or packet.get("version") != PROTOCOL_VERSION
    ):
        raise ValueError("Unsupported WebXR packet version")
    if packet.get("type") not in ("frame", "tracking_stopped", "reference_reset"):
        raise ValueError("Unsupported WebXR packet type")
    sequence = packet.get("sequence")
    if type(sequence) is not int or not 0 <= sequence < 2**53:
        raise ValueError("Sequence must be a nonnegative safe integer")
    stamp = packet.get("source_time_ms")
    if type(stamp) not in (int, float) or not np.isfinite(stamp) or stamp < 0:
        raise ValueError("Invalid source monotonic timestamp")
    if packet.get("reference_space") not in ("local", "local-floor"):
        raise ValueError("Unknown WebXR reference space")
    epoch = packet.get("reference_epoch")
    if type(epoch) is not int or epoch < 0:
        raise ValueError("Invalid reference epoch")
    if packet["type"] == "frame":
        if packet.get("joint_names") != list(WEBXR_JOINT_NAMES):
            raise ValueError("Joint names/order must match the explicit WebXR protocol")
        if not isinstance(packet.get("hands"), dict) or set(packet["hands"]) != {"left", "right"}:
            raise ValueError("Each frame must explicitly describe left and right hand validity")


def hand_frame_from_packet(packet, side, received_at, session_id, target_frame="wrist_rh"):
    """Return None for explicit tracking loss. Reject malformed valid poses."""
    hand = packet["hands"][side]
    if not isinstance(hand, dict) or type(hand.get("valid")) is not bool:
        raise ValueError("Hand payload must have an explicit boolean valid flag")
    if not hand["valid"]:
        return None
    if hand.get("emulated") is not False:
        raise ValueError("Emulated/missing tracking state isn't accepted as a valid hand")
    try:
        positions = np.asarray(hand["positions"], dtype=float)
        rotations = np.asarray(hand["rotations"], dtype=float)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Invalid native hand pose arrays") from exc
    if positions.shape != (25, 3) or not np.isfinite(positions).all():
        raise ValueError("Expected 25 finite native WebXR joint positions")
    if (
        rotations.shape != (25, 4)
        or not np.isfinite(rotations).all()
        or not np.allclose(np.linalg.norm(rotations, axis=1), 1, atol=1e-5)
    ):
        raise ValueError("Expected 25 native unit xyzw joint rotations")
    metadata = {
        "source": "webxr",
        "session_id": session_id,
        "sequence": packet["sequence"],
        "source_time_ms": packet["source_time_ms"],
        "source_clock": "browser_performance_now",
        "source_frame": packet["reference_space"],
        "reference_epoch": packet["reference_epoch"],
        "native_joint_count": 25,
        "joint_layout": "common21",
        "held_pose": False,
    }
    source = HandFrame(
        received_at,
        side,
        positions[list(COMMON_INDICES)],
        positions[0],
        rotations[0],
        True,
        coordinate_frame="world_rh",
        joint_rotations=rotations[list(COMMON_INDICES)],
        metadata=metadata,
    )
    return transform_world_frame(source, target_frame)
