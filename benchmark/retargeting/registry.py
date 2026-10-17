"""Factory registry without loading heavy upstream dependencies in Phase 2."""

from collections.abc import Callable

from benchmark.retargeting.base import BaseRetargeter

PHASES = {"manus": 4, "anydex": 5, "wuji": 6, "geort": 7}
_FACTORIES: dict[str, Callable[..., BaseRetargeter]] = {}


def register(name: str, factory: Callable[..., BaseRetargeter]) -> None:
    if name not in PHASES:
        raise ValueError(f"Unknown benchmark method: {name}")
    if name in _FACTORIES:
        raise ValueError(f"Adapter already registered: {name}")
    _FACTORIES[name] = factory


def create(name: str, **kwargs) -> BaseRetargeter:
    if name not in PHASES:
        raise ValueError(f"Unknown benchmark method: {name}")
    if name not in _FACTORIES:
        raise NotImplementedError(f"{name} adapter is not implemented (Phase {PHASES[name]})")
    return _FACTORIES[name](**kwargs)
