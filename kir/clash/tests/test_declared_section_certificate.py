"""WHY CLASH CANNOT SAY "FIX": TWO WALLS, NOT ONE.

Measurement 11.08.2026. In prod the top rung is unreachable: `_rung` gives `fix`
only when `proven is True`, `_physical_overlap_proof` requires
`verdict == "confirmed"` plus a certified INNER overlap, and two
pipes crossing in the air come out as `look`. This file keeps
BOTH reasons in view — the second was found while trying to remove the first, and
without it the plan "register a publisher from the declaration" looks feasible,
but it is not feasible.

WALL ONE — THERE IS NO PRODUCTION PUBLISHER. The trust registry holds exactly
one name, and it names itself: `certify_analytic_inner_for_test`, publisher
`kir.clash.analytic-test-body/v1`, provenance `explicit-analytic-body/v1`.
The publisher requires a TRUE BODY as input, and its docstring names the condition
for lifting the ban: «until a Revit body extractor can provide equivalent source
evidence». `record.inner` is filled in NOWHERE in prod.

    This wall is NOT general. For `bbox` the ban is correct (a bounding box is not
    a body) and for `profile` it is correct (the contour coarsens outward). But for
    a ROUND declared cross-section the capsule does not approximate the body, it IS
    the body: the program said 400 mm, the emitter sets exactly 400 mm, and a Revit
    extractor is not needed to know what we ourselves are about to build.

WALL TWO, DEEPER THAN THE FIRST — THE PROOF CORE ACCEPTS ONLY
POLYHEDRA. `_analytic_vertices` canonicalizes `Aabb` and `Prism` and rejects
`Capsule` and `PrismSet`. This is not a gap but a core decision, recorded in the
core itself: «No Capsule is silently promoted to an inner hull merely because its
outer approximation has a radius». EVERY MEP run is a capsule. So even with a
live publisher from the declaration, the certificate for the very class all this
was started for is not issued: this core has nothing to express the body of a
round pipe with.

WHY THIS IS RECORDED AS A TEST, NOT A COMMENT. Both walls are claims about
TODAY's code, and both are required to turn red when they are removed: the
first — when a second publisher appears, the second — when the core learns the
body of revolution. Red here means "the wall is removed, reread the plan," not
breakage. A comment cannot do this: this very file already carries a history of a
record outliving its own truth.

WHAT THIS FILE DOES NOT COVER: it does not claim that a certificate from the
declaration is the correct next turn. It claims only WHAT exactly is blocking, and
that two different things are blocking, not one.
"""
from __future__ import annotations

from kir.clash import detect as D
from kir.clash import geom as G
from kir.clash import hulls as H


def _duct(source_id: str, *, y_mm: float = 0.0, across: bool = False,
          params: dict | None = None, category: str = "OST_DuctCurves"):
    el = {"element_id": source_id, "category": category,
          "params": params or {"RBS_CURVE_DIAMETER_PARAM": 400.0}}
    if across:
        el |= {"p0_mm": [2500.0, -2000.0, 2700.0],
               "p1_mm": [2500.0, 2000.0, 2700.0]}
    else:
        el |= {"p0_mm": [0.0, y_mm, 2700.0], "p1_mm": [5000.0, y_mm, 2700.0]}
    rec, refusal = H.build_hull(el)
    assert rec is not None, refusal
    return rec


# ── WALL ONE ──────────────────────────────────────────────────────────────

def test_the_trust_registry_has_exactly_one_issuer_and_it_is_a_fixture():
    """The only registered publisher calls itself a test — both by
    name and by provenance. Red here = a second publisher has appeared."""
    assert set(H.INNER_CERTIFICATE_ISSUER_REGISTRY) == {
        H.ANALYTIC_TEST_INNER_ISSUER}
    assert "test" in H.ANALYTIC_TEST_INNER_ISSUER
    assert H.INNER_CERTIFICATE_PROVENANCE == frozenset(
        {H.ANALYTIC_BODY_PROVENANCE})
    assert hasattr(H, "certify_analytic_inner_for_test")


def test_no_production_hull_carries_inner_evidence():
    """`record.inner` is not filled in for any shell source."""
    for rec in (_duct("d1"),
                _duct("d2", params={"RBS_CURVE_WIDTH_PARAM": 400.0,
                                    "RBS_CURVE_HEIGHT_PARAM": 200.0})):
        assert rec.inner is None, rec.hull_source
    wall, _ = H.build_hull({"element_id": "w", "category": "OST_Walls",
                            "bbox_min_mm": [0, 0, 0],
                            "bbox_max_mm": [1000, 200, 3000]})
    assert wall.inner is None and wall.hull_source == "bbox"


def test_two_crossing_declared_ducts_stay_possible_for_a_NAMED_reason():
    """Two runs crossing in the air are a collision under any reading, and
    the verdict is «possible» with a reason named explicitly."""
    finding, why = D.evaluate_with_reason(_duct("d1"), _duct("d2", across=True))
    assert finding is not None, why
    proof = finding.as_dict()["physical_overlap_proof"]
    assert proof["status"] == "not_proven"
    assert proof["reason"] == "a:inner_evidence_absent;b:inner_evidence_absent"


def test_the_declared_capsule_IS_the_body_for_a_round_section():
    """WHY THE FIRST WALL IS NOT GENERAL: for a round cross-section the capsule
    radius EQUALS half of the declared diameter — not a hair more. There is no
    coarsening, and there is nothing to prove here beyond what the program has
    already said."""
    rec = _duct("d1")
    assert rec.hull_source == "axis_section"
    assert isinstance(rec.hull, G.Capsule)
    assert rec.hull.radius == 200.0            # exactly 400/2, not circumscribed
    rect = _duct("d2", params={"RBS_CURVE_WIDTH_PARAM": 400.0,
                               "RBS_CURVE_HEIGHT_PARAM": 200.0})
    # Whereas for a rectangular one — the CIRCUMSCRIBED circle, i.e. outward
    # coarsening, and for it the ban remains correct.
    assert rect.hull.radius > 200.0


# ── WALL TWO ──────────────────────────────────────────────────────────────

def test_the_proof_kernel_accepts_only_polytopes():
    """The core canonicalizes `Aabb` and `Prism` and rejects `Capsule`/`PrismSet`.

    Red here = the core has learned the body of revolution, and the plan to
    remove the first wall is feasible again.
    """
    box = G.Aabb((0, 0, 0), (100, 200, 300))
    prism = G.Prism(((0, 0), (100, 0), (100, 100), (0, 100)), 0.0, 100.0)
    capsule = G.Capsule(((0, 0, 0), (1000, 0, 0)), 200.0)
    prism_set = G.PrismSet(((((0, 0), (100, 0), (100, 100), (0, 100))),),
                           0.0, 100.0)
    assert H._analytic_vertices(box) is not None
    assert H._analytic_vertices(prism) is not None
    assert H._analytic_vertices(capsule) is None, (
        "ядро приняло капсулу — вторая стена снята, перечитайте план")
    assert H._analytic_vertices(prism_set) is None


def test_every_mep_run_is_a_capsule_so_the_second_wall_binds_exactly_here():
    """The joint of the two walls: the class for whose sake it was worth removing
    the first consists entirely of bodies that the second rejects."""
    for params in ({"RBS_CURVE_DIAMETER_PARAM": 400.0},
                   {"RBS_CURVE_WIDTH_PARAM": 400.0,
                    "RBS_CURVE_HEIGHT_PARAM": 200.0}):
        rec = _duct("d", params=params)
        assert isinstance(rec.hull, G.Capsule)
        assert H._analytic_vertices(rec.hull) is None
