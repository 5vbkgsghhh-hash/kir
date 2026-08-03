"""Real-geometry regression (live smoke 2026-07-10, model LSR_Lot31, 5219 rooms):
a self-intersecting room boundary makes ``Polygon(...).buffer(0)`` return a
**MultiPolygon**, which broke every ``.exterior`` consumer downstream
(``_touches`` derive.py:129, ring build derive.py:313) →
``AttributeError: 'MultiPolygon' object has no attribute 'exterior'``.

Contract fix at the SOURCE: ``_polygon()`` must always return a single
``Polygon`` (the largest-area component — smaller pieces are self-intersection
slivers) or ``None``. Downstream keeps its stated contract untouched.
"""
from __future__ import annotations

from shapely.geometry import Point, Polygon

from kukai.modeling.checker.derive import _polygon, _touches

# A bow-tie (figure-eight) boundary: buffer(0) splits it into TWO triangles →
# MultiPolygon. The left triangle is bigger (height 4 vs 2) so it must win.
_BOWTIE = [(0.0, 0.0), (4.0, 0.0), (0.0, 4.0), (4.0, 2.0), (0.0, 2.0), (0.0, 0.0)]


def test_polygon_normalizes_multipolygon_to_largest_component():
    poly = _polygon(_BOWTIE)
    assert poly is not None
    assert isinstance(poly, Polygon)          # NOT MultiPolygon — the contract
    assert poly.exterior is not None          # the exact attribute that crashed


def test_touches_survives_self_intersecting_boundary():
    poly = _polygon(_BOWTIE)
    # a point on the larger component's boundary — must not raise
    assert _touches(poly, Point(0.0, 1.0), tol=0.1) is True
    # far away — decidable False, still no raise
    assert _touches(poly, Point(100.0, 100.0), tol=0.1) is False


def test_polygon_degenerate_still_none():
    assert _polygon([]) is None
    assert _polygon([(0, 0), (1, 0)]) is None
    # zero-area sliver collapses to empty after buffer(0) → None, not a crash
    assert _polygon([(0, 0), (1, 0), (2, 0), (0, 0)]) is None
