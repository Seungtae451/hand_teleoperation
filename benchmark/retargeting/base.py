"""Shared interface for all four future adapters."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import numpy as np

from benchmark.tracking.hand_frame import HandFrame


@dataclass
class RetargetingResult:
    q_target: np.ndarray
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        self.q_target = np.asarray(self.q_target, dtype=float).copy()
        if self.q_target.shape != (20,) or not np.isfinite(self.q_target).all():
            raise ValueError("Retargeter must return 20 finite joint targets in radians")


class BaseRetargeter(ABC):
    @abstractmethod
    def reset(self) -> None:
        """Reset optimizer warm start, filtering, and timing state."""

    @abstractmethod
    def retarget(self, hand_frame: HandFrame) -> RetargetingResult:
        """Return canonical joint order, solver status, and timing metadata."""
