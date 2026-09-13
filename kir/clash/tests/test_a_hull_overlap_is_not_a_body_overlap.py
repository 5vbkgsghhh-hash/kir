"""The exact narrow phase: bodies are judged as bodies, and refutation has
become expressible.

The scene is the acceptance contract (`geo-loop/acceptance/CONTRACT.md`
§2) at `bulge_mm = 0`, where the loft degenerates into an exact prism and
the answers have a closed-form analytic solution. Reference values are
computed WITHOUT OCCT, by two oracles.
"""
import math

import pytest

from kir.clash import detect as D
from kir.clash import exact as E
from kir.clash import geom as G
from kir.clash import hulls as H

OCP = pytest.importorskip("OCP", reason="точная фаза требует профиля OCCT")

from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut                     # noqa: E402
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder  # noqa: E402
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt                       # noqa: E402

PODIUM_VOLUME_MM3 = 3.760095137745e12
PASSAGE_COMMON_MM3 = 3.8e10
PASSAGE_DEPTH_MM = 500.0
IN_ATRIUM_GAP_MM = 1085.786438
INSIDE_COMMON_MM3 = 1.0e9
INSIDE_DEPTH_MM = 1000.0
IDENT = E.IDENTITY_FRAME

BOXES = {
    "passage": ((30000, -6000, -500), (34000, 15000, 2500)),
    "in_atrium": ((18000, 3500, -2500), (20000, 5500, -500)),
    "pier": ((40000, 0, -3000), (46000, 6000, 0)),
    "inside": ((42500, 2500, -2000), (43500, 3500, -1000)),
    "in_atrium_moved": ((19500, 3500, -2500), (21500, 5500, -500)),
    "inside_broken": ((42500, 2500, -3500), (43500, 3500, -1000)),
}


def box(lo, hi):
    return BRepPrimAPI_MakeBox(gp_Pnt(*lo), hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]).Shape()


@pytest.fixture(scope="module")
def scene():
    prism = box((-2000, -5000, -3000), (65000, 14000, 0))
    hole = BRepPrimAPI_MakeCylinder(
        gp_Ax2(gp_Pnt(19000, 4500, -4000), gp_Dir(0, 0, 1)), 2500.0, 5000.0).Shape()
    cut = BRepAlgoAPI_Cut(prism, hole)
    cut.Build()
    assert cut.IsDone()
    return {"podium": cut.Shape(), **{name: box(*c) for name, c in BOXES.items()}}


def frame(dx=0.0, dy=0.0, dz=0.0, degrees=0.0):
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    return (c, -s, 0.0, dx, s, c, 0.0, dy, 0.0, 0.0, 1.0, dz, 0.0, 0.0, 0.0, 1.0)


def record(name, lo, hi, *, source="brep"):
    return H.HullRecord(source_id=name, category="OST_Mass", label="mass",
                        mvp_side=None, hull=G.Aabb(tuple(map(float, lo)), tuple(map(float, hi))),
                        grade="coarse", hull_source=source)


# ─────────────────────────────────────────────────────── owner's controls

def test_an_object_in_the_atrium_void_does_not_touch_the_podium(scene):
    """Item 1: the bounding boxes intersect, the bodies do not, and this is
    PROVEN."""
    verdict = E.verify_pair(scene["podium"], scene["in_atrium"], IDENT, IDENT)
    assert verdict.ok and verdict.relation == "clear"
    assert verdict.overlap_volume_mm3 == 0.0
    assert verdict.gap_mm == pytest.approx(IN_ATRIUM_GAP_MM, abs=0.5)
    # Anti-Goodhart: the shifted twin MUST intersect, otherwise "the phase
    # is silent."
    twin = E.verify_pair(scene["podium"], scene["in_atrium_moved"], IDENT, IDENT)
    assert twin.relation == "intersect" and twin.overlap_volume_mm3 > 0.0
    # The atrium's axis is outside the body; that is what "void" means,
    # not "inside."
    assert E.classify_point(scene["podium"], (19000, 4500, -1500)) == "out"


def test_a_body_fully_inside_another_is_found_and_the_gap_would_have_missed_it(scene):
    """Item 2 + the reason a gap doesn't work for nesting."""
    verdict = E.verify_pair(scene["pier"], scene["inside"], IDENT, IDENT)
    assert verdict.relation == "contained" and verdict.contained_side == "b"
    assert verdict.overlap_volume_mm3 == pytest.approx(INSIDE_COMMON_MM3, rel=1e-3)
    assert verdict.depth_mm == pytest.approx(INSIDE_DEPTH_MM, abs=0.5)
    # A gap for a nested body is NOT computed at all: it would measure the
    # distance to the surface (measured: 3000mm at full nesting) and call
    # it "far away."
    assert verdict.gap_mm is None
    broken = E.verify_pair(scene["pier"], scene["inside_broken"], IDENT, IDENT)
    assert broken.relation == "intersect" and broken.contained_side is None


def test_the_acceptance_volume_and_depth_are_reproduced(scene):
    """Acceptance reference: passage ∩ podium = 38.000 m³ ±0.1%, depth
    500 ±0.5."""
    verdict = E.verify_pair(scene["podium"], scene["passage"], IDENT, IDENT)
    assert verdict.relation == "intersect"
    assert verdict.overlap_volume_mm3 == pytest.approx(PASSAGE_COMMON_MM3, rel=1e-3)
    assert verdict.depth_mm == pytest.approx(PASSAGE_DEPTH_MM, abs=0.5)


@pytest.mark.parametrize("label,f", [
    ("translate_1km", frame(1_000_000, -500_000, 250_000)),
    ("rotate_37", frame(degrees=37.0)),
    ("translate_and_rotate", frame(1_000_000, -500_000, 250_000, 37.0)),
])
def test_moving_the_whole_scene_changes_neither_verdict_nor_volume(scene, label, f):
    """Item 4: translating and rotating the scene moves none of the
    answers."""
    assert E.verify_pair(scene["podium"], scene["passage"], f, f
                         ).overlap_volume_mm3 == pytest.approx(PASSAGE_COMMON_MM3, rel=1e-3)
    void = E.verify_pair(scene["podium"], scene["in_atrium"], f, f)
    assert void.relation == "clear" and void.gap_mm == pytest.approx(IN_ATRIUM_GAP_MM, abs=0.5)
    inside = E.verify_pair(scene["pier"], scene["inside"], f, f)
    assert inside.relation == "contained"
    assert inside.overlap_volume_mm3 == pytest.approx(INSIDE_COMMON_MM3, rel=1e-3)


def test_the_frame_is_applied_here_and_a_mirror_is_a_named_refusal(scene):
    """The frame is THIS module's job: `read_body()` returns local
    coordinates."""
    # The same translation, applied to BOTH bodies, changes nothing;
    # applied to ONE, it pulls them apart. So the frame genuinely works.
    apart = E.verify_pair(scene["podium"], scene["passage"], IDENT, frame(dx=500_000))
    assert apart.relation == "clear"
    mirror = (-1.0, 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1.)
    assert E.verify_pair(scene["podium"], scene["passage"], mirror, IDENT
                         ).refusal == "mirrored_frame"
    assert E.verify_pair(scene["podium"], scene["passage"], (1, 2, 3), IDENT
                         ).refusal == "invalid_frame"


@pytest.mark.parametrize("args,expected", [
    ((None, "passage"), "no_persisted_body"),
    (("null", "passage"), "null_shape"),
])
def test_every_refusal_is_named_and_never_becomes_a_verdict(scene, args, expected):
    from OCP.TopoDS import TopoDS_Shape
    first = None if args[0] is None else (TopoDS_Shape() if args[0] == "null" else scene[args[0]])
    verdict = E.verify_pair(first, scene[args[1]], IDENT, IDENT)
    assert verdict.refusal == expected and verdict.relation is None and not verdict.ok


def test_a_spent_budget_refuses_instead_of_running_over(scene):
    verdict = E.verify_pair(scene["podium"], scene["passage"], IDENT, IDENT, budget_ms=0.0)
    assert verdict.refusal == "exact_budget_exhausted" and verdict.relation is None


def test_the_tolerance_policy_has_one_digest_and_it_moves_with_the_numbers():
    a, b = E.TolerancePolicy(), E.TolerancePolicy()
    assert a.digest == b.digest and len(a.digest) == 64
    assert E.TolerancePolicy(fuzzy_mm=0.02).digest != a.digest
    assert E.TolerancePolicy(contact_gap_mm=1.0).digest != a.digest
    with pytest.raises(ValueError):
        E.TolerancePolicy(fuzzy_mm=-1.0)


def test_fuzzy_value_does_not_buy_contact(scene):
    """Measurement: 0.001…10mm give ONE verdict. Contact is decided by the
    gap, not by fuzz."""
    verdicts = {tol: E.verify_pair(scene["podium"], scene["in_atrium"],
                                   IDENT, IDENT, tolerance_mm=tol)
                for tol in (0.001, 0.01, 0.1, 1.0, 10.0)}
    assert {v.relation for v in verdicts.values()} == {"clear"}
    assert len({round(v.gap_mm, 3) for v in verdicts.values()}) == 1


# ─────────────────────────────────────────────────────────────── the seam in detect

def test_the_third_verdict_exists_and_only_the_exact_phase_can_issue_it():
    assert D.VERDICTS == ("confirmed", "possible", "refuted")
    with pytest.raises(PermissionError):
        D.PhysicalOverlapProof(status="refuted", basis=E.EXACT_BASIS, reason=None,
                               subject_a="a", subject_b="b", a={}, b={})


def test_a_hull_overlap_refuted_by_bodies_becomes_refuted_not_possible(scene):
    """Exactly the phrase the vocabulary was missing: "hulls yes, bodies
    no"."""
    records = [record("podium", (-2000, -5000, -3000), (65000, 14000, 0)),
               record("in_atrium", *BOXES["in_atrium"])]
    finding, reason = D.evaluate_with_reason(records[0], records[1])
    assert finding is not None and finding.verdict == "possible", reason
    bodies = {"podium": (scene["podium"], IDENT), "in_atrium": (scene["in_atrium"], IDENT)}
    updated, limits = D.apply_exact_phase([finding], bodies)
    assert updated[0].verdict == "refuted"
    proof = updated[0].physical_overlap_proof
    assert proof.status == "refuted" and proof.basis == E.EXACT_BASIS
    assert proof.exact_relation == "clear" and proof.exact_overlap_volume_mm3 == 0.0
    assert any("exact_pairs_checked" in item for item in limits)
    # The published proof is checkable and sealed. The sides are taken
    # from the finding itself: their order is canonical (by source_id),
    # and substituting it by hand would mean checking one's own guess, not
    # the carrier.
    assert D.verify_serialized_physical_overlap_proof(
        proof.as_dict(), subject_a=proof.subject_a, subject_b=proof.subject_b)
    assert {proof.subject_a, proof.subject_b} == {"podium", "in_atrium"}


def test_a_real_body_overlap_is_confirmed_with_its_volume(scene):
    records = [record("podium", (-2000, -5000, -3000), (65000, 14000, 0)),
               record("passage", *BOXES["passage"])]
    finding, _ = D.evaluate_with_reason(records[0], records[1])
    bodies = {"podium": (scene["podium"], IDENT), "passage": (scene["passage"], IDENT)}
    updated, _ = D.apply_exact_phase([finding], bodies)
    assert updated[0].verdict == "confirmed"
    proof = updated[0].physical_overlap_proof
    assert proof.basis == E.EXACT_BASIS and proof.exact_relation == "intersect"
    assert proof.exact_overlap_volume_mm3 == pytest.approx(PASSAGE_COMMON_MM3, rel=1e-3)
    assert D.verify_serialized_physical_overlap_proof(
        proof.as_dict(), subject_a=proof.subject_a, subject_b=proof.subject_b)
    assert {proof.subject_a, proof.subject_b} == {"podium", "passage"}


def test_an_edited_exact_proof_fails_closed(scene):
    records = [record("podium", (-2000, -5000, -3000), (65000, 14000, 0)),
               record("passage", *BOXES["passage"])]
    finding, _ = D.evaluate_with_reason(records[0], records[1])
    bodies = {"podium": (scene["podium"], IDENT), "passage": (scene["passage"], IDENT)}
    proof = D.apply_exact_phase([finding], bodies)[0][0].physical_overlap_proof.as_dict()
    for key, value in (("exact_overlap_volume_mm3", 1.0), ("exact_relation", "clear"),
                       ("status", "refuted"), ("tolerance_policy_digest", "0" * 64)):
        edited = {**proof, key: value}
        assert not D.verify_serialized_physical_overlap_proof(
            edited, subject_a=proof["subject_a"], subject_b=proof["subject_b"]), key


def test_a_missing_body_is_a_named_limit_and_never_a_silent_pass(scene):
    records = [record("podium", (-2000, -5000, -3000), (65000, 14000, 0)),
               record("passage", *BOXES["passage"])]
    finding, _ = D.evaluate_with_reason(records[0], records[1])
    updated, limits = D.apply_exact_phase([finding], {})
    assert updated[0].verdict == "possible"          # the finding is untouched
    assert updated[0] is finding
    assert limits == []                               # the pair wasn't even taken
    partial = {"podium": (scene["podium"], IDENT)}
    updated, limits = D.apply_exact_phase([finding], partial)
    assert updated[0].verdict == "possible" and limits == []


def test_only_pairs_with_both_bodies_are_eligible(scene):
    records = [record("a", (0, 0, 0), (1, 1, 1)),
               record("b", (0, 0, 0), (1, 1, 1), source="bbox")]
    bodies = {"a": (scene["passage"], IDENT), "b": (scene["inside"], IDENT)}
    assert D.exact_eligible_pairs(records, bodies, [(0, 1)]) == []
    records[1] = record("b", (0, 0, 0), (1, 1, 1))
    assert D.exact_eligible_pairs(records, bodies, [(0, 1)]) == [(0, 1)]


def test_the_budget_names_what_it_did_not_check(scene):
    records = [record("podium", (-2000, -5000, -3000), (65000, 14000, 0)),
               record("passage", *BOXES["passage"]), record("pier", *BOXES["pier"])]
    findings = [D.evaluate_with_reason(records[0], records[1])[0],
                D.evaluate_with_reason(records[0], records[2])[0]]
    findings = [f for f in findings if f is not None]
    bodies = {name: (scene[name], IDENT) for name in ("podium", "passage", "pier")}
    _, limits = D.apply_exact_phase(findings, bodies, max_pairs=1)
    assert any("exact_pair_limit_reached" in item for item in limits)
    _, limits = D.apply_exact_phase(findings, bodies, budget_ms=1.0)
    assert any("exact_budget_exhausted" in item for item in limits)


# ─────────────────────────────────────────── the depth law (acceptance, entry 7)

def test_depth_is_the_shortest_axis_of_the_intersection_not_of_the_scene(scene):
    """🔴 THE INSTRUMENT WAS RIGHT ABOUT A DIFFERENT SUBJECT (06.09.2026,
    acceptance, entry 7).

    `depth_mm` for `passage × podium` was giving **3000.01mm** at a
    penetration of 500.0 and an EXACT volume of 3.8000e+10. Two causes
    combined into one falsehood: the boolean result is a compound (the
    bounding box of the whole figure equals the podium's bounding box),
    and the "fast" `BRepBndLib.Add_s` builds a bounding box from
    UNTRIMMED face surfaces — and for the single solid of the
    intersection it also returned the podium's bounding box. The law is
    now written down: the minimum AABB extent of the `Common` BODIES
    along the axes, using the optimal bounding box, in world coordinates
    after the frame.
    """
    verdict = E.verify_pair(scene["podium"], scene["passage"], IDENT, IDENT)
    assert verdict.relation == "intersect"
    assert verdict.depth_mm == pytest.approx(PASSAGE_DEPTH_MM, abs=0.5)

    # 🔴 THE DEFECT-RETURN CONTROL USES THE VERY BODY THE DEFECT WAS ON.
    # On a prism made of boxes, the "fast" bounding box coincides with the
    # optimal one — the faces lie on planes, and trimming changes
    # nothing. The defect only shows on the LOFT of the acceptance
    # example, whose faces sit on B-splines: the first edition of this
    # pin would have passed green and guarded nothing.
    from examples.residential_with_podium import build_podium_body
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common

    lofted = build_podium_body({"height_mm": 3000., "bulge_mm": 0., "atrium_radius_mm": 2500.})
    passage = box((30000, -6000, -500), (34000, 15000, 2500))
    assert E.verify_pair(lofted, passage, IDENT, IDENT).depth_mm == pytest.approx(500.0, abs=0.5)
    common = BRepAlgoAPI_Common(lofted, passage)
    common.SetFuzzyValue(0.01)
    common.Build()
    quick = Bnd_Box()
    BRepBndLib.Add_s(common.Shape(), quick, False)
    x0, y0, z0, x1, y1, z1 = quick.Get()
    assert min(x1 - x0, y1 - y0, z1 - z0) > 2000.0, (
        "прежний прибор обязан оставаться неверным — иначе пин ничего не сторожит")


def test_one_depth_law_serves_both_relations(scene):
    """For nesting, `Common` equals the smaller body, so there is one
    law."""
    inside = E.verify_pair(scene["pier"], scene["inside"], IDENT, IDENT)
    assert inside.relation == "contained"
    assert inside.depth_mm == pytest.approx(INSIDE_DEPTH_MM, abs=0.5)
    # A 1000³ cube: the minimum extent equals its edge, not the distance
    # to the enclosing body's face — the numbers coincide, but the law is
    # now ONE, and this is checked on a pair where they would have
    # diverged: a body touching the enclosing body's face.
    flush = E.verify_pair(scene["pier"], box((40000, 0, -3000), (41000, 1000, -2000)),
                          IDENT, IDENT)
    assert flush.relation == "contained" and flush.depth_mm == pytest.approx(1000.0, abs=0.5)


@pytest.mark.parametrize("label,f", [
    ("translate_1km", frame(1_000_000, -500_000, 250_000)),
    ("rotate_37", frame(degrees=37.0)),
])
def test_depth_is_measured_after_the_frame(scene, label, f):
    """The law says "in world coordinates after the frame" — we check the
    translation.

    Rotating the scene CHANGES the axis-aligned extents by construction
    (AABB is not rotation-invariant), and the law acknowledges this: the
    translation is checked exactly, while for rotation only this is
    checked — that the depth stayed finite and did not become the
    scene's bounding box.
    """
    moved = E.verify_pair(scene["podium"], scene["passage"], f, f)
    if label == "translate_1km":
        assert moved.depth_mm == pytest.approx(PASSAGE_DEPTH_MM, abs=0.5)
    else:
        assert moved.depth_mm is not None and moved.depth_mm < 2000.0
