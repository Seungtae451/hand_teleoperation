"""Transport-independent latest hand state with ordering, timeout, and session resets."""

import math
from dataclasses import replace

from benchmark.tracking.recorder import frame_to_dict
from benchmark.tracking.webxr_protocol import hand_frame_from_packet, validate_envelope


class ReceiverState:
    def __init__(self, *, timeout=0.25, target_frame="wrist_rh", recorder=None):
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Tracking timeout must be positive and finite")
        if target_frame not in ("wrist_rh", "palm_rh", "world_rh"):
            raise ValueError("Unsupported target coordinate frame")
        self.timeout, self.target_frame, self.recorder = timeout, target_frame, recorder
        self.session_id = None
        self.sequence = -1
        self.source_time_ms = -1
        self.reference_epoch = None
        self.latest = {}
        self.valid_received = {}
        self.reasons = {side: "waiting" for side in ("left", "right")}
        self.accepted_packets = self.rejected_packets = self.accepted_frames = 0

    def emit(self, event):
        if self.recorder:
            self.recorder.write(event)

    def connect(self, session_id, now):
        if self.session_id is not None:
            raise ValueError("An input source already owns the receiver")
        self.session_id = session_id
        self.sequence, self.source_time_ms, self.reference_epoch = -1, -1, None
        self.latest.clear()
        self.valid_received.clear()
        self.reasons = {side: "waiting" for side in ("left", "right")}
        self.emit({"event": "session_start", "session_id": session_id, "receive_time_s": now})

    def invalidate(self, side, reason, now):
        previous = self.latest.get(side)
        if self.reasons[side] == reason and (previous is None or not previous.tracking_valid):
            return
        self.reasons[side] = reason
        self.emit(
            {
                "event": "tracking_lost",
                "handedness": side,
                "reason": reason,
                "receive_time_s": now,
                "session_id": self.session_id,
            }
        )
        if previous is not None and previous.tracking_valid:
            invalid = replace(
                previous,
                timestamp=now,
                tracking_valid=False,
                metadata={
                    **previous.metadata,
                    "held_pose": True,
                    "invalid_reason": reason,
                    "last_valid_receive_time_s": self.valid_received[side],
                },
            )
            self.latest[side] = invalid
            self.emit({"event": "hand_frame", "frame": frame_to_dict(invalid)})

    def disconnect(self, now):
        for side in ("left", "right"):
            self.invalidate(side, "source_disconnected", now)
        self.emit({"event": "session_end", "session_id": self.session_id, "receive_time_s": now})
        self.session_id = None

    def accept(self, packet, session_id, now):
        try:
            if session_id != self.session_id or self.session_id is None:
                raise ValueError("Packet does not belong to the active source")
            validate_envelope(packet)
            if (
                packet["sequence"] <= self.sequence
                or packet["source_time_ms"] < self.source_time_ms
            ):
                raise ValueError("Out-of-order sequence or browser timestamp")
            epoch = packet["reference_epoch"]
            if self.reference_epoch is not None and epoch < self.reference_epoch:
                raise ValueError("Reference epoch regressed")
            # Validate both hands before committing either one.
            frames = {}
            if packet["type"] == "frame":
                frames = {
                    side: hand_frame_from_packet(packet, side, now, session_id, self.target_frame)
                    for side in ("left", "right")
                }
            if self.reference_epoch is not None and epoch != self.reference_epoch:
                for side in ("left", "right"):
                    self.invalidate(side, "reference_reset", now)
            self.sequence, self.source_time_ms, self.reference_epoch = (
                packet["sequence"],
                packet["source_time_ms"],
                epoch,
            )
            self.accepted_packets += 1
            self.emit(
                {
                    "event": "native_packet",
                    "receive_time_s": now,
                    "session_id": session_id,
                    "packet": packet,
                }
            )
            if packet["type"] != "frame":
                for side in ("left", "right"):
                    self.invalidate(side, packet["type"], now)
                return []
            for side, frame in frames.items():
                if frame is None:
                    reason = str(packet["hands"][side].get("reason", "tracking_invalid"))[:160]
                    self.invalidate(side, reason, now)
                else:
                    self.latest[side], self.valid_received[side], self.reasons[side] = (
                        frame,
                        now,
                        "valid",
                    )
                    self.accepted_frames += 1
                    self.emit({"event": "hand_frame", "frame": frame_to_dict(frame)})
            return [f for f in frames.values() if f is not None]
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            self.rejected_packets += 1
            self.emit({"event": "rejected_packet", "reason": str(exc), "receive_time_s": now})
            raise ValueError(str(exc)) from exc

    def expire(self, now):
        for side, frame in list(self.latest.items()):
            if frame.tracking_valid and now - self.valid_received[side] >= self.timeout:
                self.invalidate(side, "receive_timeout", now)

    def status(self, now):
        self.expire(now)
        return {
            "type": "status",
            "source_connected": self.session_id is not None,
            "session_id": self.session_id,
            "accepted_packets": self.accepted_packets,
            "rejected_packets": self.rejected_packets,
            "accepted_hand_frames": self.accepted_frames,
            "timeout_s": self.timeout,
            "target_frame": self.target_frame,
            "recording": str(self.recorder.path) if self.recorder else None,
            "hands": {
                side: {
                    "valid": bool(self.latest.get(side) and self.latest[side].tracking_valid),
                    "reason": self.reasons[side],
                    "last_valid_age_s": (
                        now - self.valid_received[side] if side in self.valid_received else None
                    ),
                    "frame": (frame_to_dict(self.latest[side]) if side in self.latest else None),
                }
                for side in ("left", "right")
            },
        }
