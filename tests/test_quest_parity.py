"""Coordinate-boundary invariants for the explicit OOJU parity experiment."""

import numpy as np
import pytest

from benchmark.datasets.quest_parity import adapt_canonical
from benchmark.geort_support.source import canonical_function


def test_reflection_equivalent_to_improper_world_basis_and_preserves_geometry():
    canonicalize = canonical_function()
    rng = np.random.default_rng(42)
    for _ in range(10):
        points = rng.normal(size=(21, 3)) * 0.04
        original = points.copy()
        q, _ = np.linalg.qr(rng.normal(size=(3, 3)))
        if np.linalg.det(q) > 0:
            q[:, 0] *= -1
        source = canonicalize(points)
        expected = canonicalize(points @ q + rng.normal(size=3))
        corrected = adapt_canonical(source)
        np.testing.assert_allclose(corrected, expected, atol=1e-14)
        np.testing.assert_allclose(
            np.linalg.norm(source[:, None] - source[None, :], axis=-1),
            np.linalg.norm(corrected[:, None] - corrected[None, :], axis=-1),
        )
        np.testing.assert_array_equal(adapt_canonical(corrected), source)
        np.testing.assert_array_equal(points, original)
        np.testing.assert_array_equal(corrected[:, 1:], source[:, 1:])


def test_reject_wrong_revision_shape_nonfinite_and_noncanonical():
    points = np.zeros((21, 3))
    with pytest.raises(ValueError):
        adapt_canonical(points, revision="other")
    for invalid in (np.zeros((26, 3)), np.full((21, 3), np.nan), np.ones((21, 3))):
        with pytest.raises(ValueError):
            adapt_canonical(invalid)
