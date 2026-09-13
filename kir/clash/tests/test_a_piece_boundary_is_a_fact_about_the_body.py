"""A piece's boundary is a fact about the body; the order of pieces is not
(F-087).

WHAT IS PINNED DOWN HERE. For a pair of prism unions, `hulls_coincide` was
sorting pieces, sorting vertices within a piece — and then MERGING
everything into one list. The piece boundary took no part in the
comparison at all, so two DIFFERENT bodies, whose pieces are different
blocks of one and the same sorted vertex sequence, were declared to
coincide. `pair_kind_of` answered such a pair with `coincident_duplicate`,
that is, ADVICE TO DELETE A GENUINE ELEMENT — exactly the outcome the
footprint comparison was written to guard against.

THE FIXTURE IS CERTIFIED BY PROD CODE, NOT BY EYE. Eight vertices in
convex position (on a circle, with uneven angles — no three collinear); a
4+4 split versus 3+5. Convexity and non-zero area of EACH piece are asked
of `decompose.loop_is_convex` / `decompose.polygon_area` — the `PrismSet`
precondition ("every piece must be CONVEX, or everything below lies
silently") is checked here, not merely declared. Otherwise the argument
would be about a shape that prod cannot ship.

THE CARDINALITY WITHOUT WHICH THE CONTROL COULD NOT TURN RED (form 18).
The defect lives in the MERGING of pieces: for a body made of ONE piece,
the merge and the piece-by-piece comparison are identical by
construction, and no edit would tell them apart. That is why both sides
here carry NO FEWER THAN TWO pieces each, while bounding-box coincidence
is checked separately — so that `pair_kind_of` doesn't filter out the
pair with a cheap box comparison BEFORE it asks the footprints.
"""

from __future__ import annotations

import math

import pytest

from kir.clash import decompose as DC
from kir.clash import detect as D
from kir.clash import geom as G
from kir.clash import hulls as H

#: The angles are deliberately uneven: on a regular grid, collinear
#: triples appear, and "convex piece" would become a matter of
#: implementation taste.
_ANGLES_DEG = (7.0, 41.0, 83.0, 122.0, 168.0, 214.0, 266.0, 311.0)
_RADIUS_MM = 1000.0
_Z0, _Z1 = 0.0, 100.0


def _vertices() -> list[tuple[float, float]]:
    points = [(round(_RADIUS_MM * math.cos(math.radians(t)), 6),
               round(_RADIUS_MM * math.sin(math.radians(t)), 6))
              for t in _ANGLES_DEG]
    assert len(set(points)) == len(points)
    return sorted(points)


def _ring(points):
    """Vertices walked in angular order — this is how a piece becomes a
    CONVEX contour."""
    cx = sum(p[0] for p in points) / len(points)
    cy = sum(p[1] for p in points) / len(points)
    ring = tuple(sorted(points, key=lambda p: math.atan2(p[1] - cy, p[0] - cx)))
    assert DC.loop_is_convex(ring), ring
    assert DC.polygon_area(ring) > 0.0, ring
    return ring


def _split(at: int) -> G.PrismSet:
    vertices = _vertices()
    return G.PrismSet((_ring(vertices[:at]), _ring(vertices[at:])), _Z0, _Z1)


def _record(source_id: str, hull: G.Hull) -> H.HullRecord:
    #: The grade and source are the ones prod assigns to a prism union
    #: (`hulls`: a footprint from a contour, split into convex pieces).
    return H.HullRecord(
        source_id=source_id, category="OST_Floors", label="floor",
        mvp_side="struct", hull=hull, grade="conservative",
        hull_source="profile")


def test_two_partitions_of_one_vertex_set_are_not_one_body():
    """Different splits of the same vertex set — different bodies."""
    four_four, three_five = _split(4), _split(3)
    a, b = _record("a", four_four), _record("b", three_five)

    # Both sides — two pieces each: otherwise the defect is
    # INEXPRESSIBLE (see the header).
    assert len(four_four.pieces) == 2 and len(three_five.pieces) == 2
    # The bounding boxes coincide, so `pair_kind_of`'s cheap gate will let
    # the pair through, and the decision will rest exactly on the
    # footprint comparison.
    assert a.bounds() == b.bounds()
    # And the splits are genuinely DIFFERENT, not merely permuted.
    assert sorted(sorted(p) for p in four_four.pieces) != sorted(
        sorted(p) for p in three_five.pieces)

    assert D.hulls_coincide(a, b) is False
    assert D.pair_kind_of(a, b) == "interference"

    finding = D.evaluate(a, b)
    assert finding is not None, "тела пересекаются — пара обязана быть находкой"
    assert finding.as_dict()["pair_kind"] == "interference", (
        "разные тела получили совет «удалить одно из них»")


def test_the_order_of_pieces_is_still_not_a_fact_about_the_body():
    """Strictness must not become "always different": the order of pieces
    is a trace of the sweep, and a permuted union remains THE SAME
    body."""
    vertices = _vertices()
    straight = G.PrismSet(
        (_ring(vertices[:4]), _ring(vertices[4:])), _Z0, _Z1)
    reversed_pieces = G.PrismSet(
        (_ring(vertices[4:]), _ring(vertices[:4])), _Z0, _Z1)
    assert straight.pieces != reversed_pieces.pieces

    a, b = _record("a", straight), _record("b", reversed_pieces)
    assert D.hulls_coincide(a, b) is True
    assert D.pair_kind_of(a, b) == "coincident_duplicate"


def test_a_different_piece_count_stays_separated():
    """The piece count is also a fact about the body, and it is checked
    before the vertices."""
    vertices = _vertices()
    two = G.PrismSet((_ring(vertices[:4]), _ring(vertices[4:])), _Z0, _Z1)
    three = G.PrismSet(
        (_ring(vertices[:3]), _ring(vertices[3:6]), _ring(vertices[5:])),
        _Z0, _Z1)
    assert D.hulls_coincide(_record("a", two), _record("b", three)) is False


def test_canonical_evidence_keeps_the_piece_boundary():
    """A second comparison of the same truth — by sealed evidence."""
    four_four, three_five = _split(4), _split(3)
    evidence_a = D._canonical_exact_hull(four_four)
    evidence_b = D._canonical_exact_hull(three_five)

    # Canonicalization itself was NOT losing pieces — the comparison was.
    # This is a correction to the analysis of the finding, and it is
    # checked, not merely retold.
    assert evidence_a["pieces_mm"] != evidence_b["pieces_mm"]
    assert len(evidence_a["pieces_mm"]) == len(evidence_b["pieces_mm"]) == 2

    assert D._canonical_evidence_coincides(
        evidence_a, evidence_b, eps=D.EXACT_BODY_EQUALITY_EPS_MM) is False

    vertices = _vertices()
    reordered = D._canonical_exact_hull(
        G.PrismSet((_ring(vertices[4:]), _ring(vertices[:4])), _Z0, _Z1))
    assert D._canonical_evidence_coincides(
        evidence_a, reordered, eps=D.EXACT_BODY_EQUALITY_EPS_MM) is True


def test_the_sealed_kernel_cannot_see_a_union_and_says_so():
    """A NAMED LIMIT, not silence: a prism union has no printable evidence.

    The branch above is the only place where merging pieces could
    survive all the way to PRINT: `_canonical_evidence_coincides` is
    called from `exact_body_equality_
    proof` and from the check of sealed proof. Both paths are closed off
    by a neighboring module: the analytic table knows exactly Aabb and
    Prism, that is, exactly ONE piece. So the piece-by-piece comparison
    above is pinned down only by a single-piece control — and this is
    stated here out loud, not inferred by the reader from a green
    result.
    """
    with pytest.raises(ValueError):
        H.analytic_hull_digest(_split(4))

    exact_a = H.HullRecord(
        source_id="a", category="OST_Floors", label="floor", mvp_side="struct",
        hull=_split(4), grade="exact", hull_source="profile")
    exact_b = H.HullRecord(
        source_id="b", category="OST_Floors", label="floor", mvp_side="struct",
        hull=_split(3), grade="exact", hull_source="profile")
    proof = D.exact_body_equality_proof(exact_a, exact_b)
    assert proof["status"] == "not_proven"
    assert proof["outcome"] == "unknown"
    assert proof["reason"] is not None
