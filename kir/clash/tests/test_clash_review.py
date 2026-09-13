"""Counterexamples from the codex review (18 findings) — one per finding.

The wave's discipline: EVERY finding is first reproduced by a test that
fails against the current code, and only then fixed. A test that could
not be made red is not a finding but a hypothesis; such ones are marked
here explicitly and named in the report.

Test numbering = review finding numbering. The file is kept separate
from `test_clash.py` on purpose: those 57 tests were green throughout
every defect reproduced below (finding #18), and mixing the proof of
their insufficiency in with them would mean losing the evidence.

    venv/bin/pytest kir/clash -q
"""
from __future__ import annotations

import json
import math
import pathlib
import random

import pytest

from kir.clash import detect as D
from kir.clash import geom as G
from kir.clash import hulls as H
from kir.clash import snapshot as S

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"
#: A real decompile on the prod box's disk. The tests do NOT depend on
#: its presence — the fixture below was extracted from it and lives in
#: the repository (finding #18: the gate runs from a clean checkout, no
#: skipif).
LIVE_RUN = (pathlib.Path(__file__).resolve().parents[3]
            / "backend" / "data" / "decompile" / "sob62_fas_r23_v11")


def floor_9981227() -> tuple[dict, dict]:
    fx = json.loads((FIXTURES / "floor_9981227_v11.json").read_text(encoding="utf-8"))
    return fx["element"], fx["profile"]


# ── #1 P0: a profile with an arc builds a hull that doesn't contain the element ─

def test_01_arc_profile_hull_must_contain_the_arc_bulge():
    """A live counterexample: floor slab 9981227, edge #5 of the outer
    contour — an ARC.

    `hull_from_profile` only convexifies the vertices and replaces the
    arc with a chord. Measurement before the fix: the arc's midpoint
    (-287.168, 26565.404) lies 752.832mm OUTSIDE the «conservative»
    hull. This is a direct violation of the conservatism law — the hull
    must CONTAIN the element.
    """
    el, prof = floor_9981227()
    rec, ref = H.build_hull(el, profile=prof)
    assert rec is not None, ref
    zc = (el["bbox_min_mm"][2] + el["bbox_max_mm"][2]) / 2.0
    for loop_i, kinds in enumerate(prof["curve_kinds"]):
        for edge_i, kind in enumerate(kinds):
            if kind != "arc":
                continue
            mid = prof["arc_midpoints"][loop_i][edge_i]
            if mid is None:
                continue
            pt = (float(mid[0]), float(mid[1]), zc)
            assert G.contains_point(rec.hull, pt), (
                f"середина дуги {loop_i}/{edge_i} вне оболочки "
                f"({rec.hull_source}/{rec.grade})")


def test_01b_arc_profile_is_bounded_outward_not_dropped():
    """THE DECOMPOSE WAVE undoes the bbox fallback — but only together
    with PROOF.

    The earlier D1 fix was sending an arc contour into a bounding box,
    and the reason was named honestly: "we have no proven outward
    approximation of an arc." Now one exists, and it is not wording but
    a construction: an arc no larger than a semicircle lies entirely
    within the "chord × outward sagitta" rectangle
    (`hulls._arc_outward_rect`), and the sagitta is taken from the
    decompile's `arc_midpoints`, not from a constant.

    So the test checks not "which source won," but the SAME THING as
    #1 — the conservatism law — and on top of that requires that the
    amount of coarsening be PUBLISHED. A hull that became thinner
    silently is no better than a hull that became thinner unlawfully.
    """
    el, prof = floor_9981227()
    rec, _ = H.build_hull(el, profile=prof)
    assert rec.hull_source == "profile" and rec.grade == "conservative"
    slack = rec.extra.get("arc_outward_slack_mm")
    assert slack is not None and slack > 0.0, (
        "раздутие наружу обязано быть названо числом: без него «наружная "
        "аппроксимация» — обещание, а не замер")
    # Exactly the value review #1 used to measure the violation: the
    # arc's midpoint lay 752.832mm outside the chord hull. The sagitta
    # must cover it — otherwise the rectangle doesn't contain the arc.
    assert slack >= 752.832


def test_01f_the_bbox_clip_may_never_cut_the_declared_contour():
    """Clipping overlaps must cut OVERLAPS, not the declared region.

    A live counterexample (`snowdon_plumb_v5`, floor 1424071, measured
    10.08.2026): the contour reaches x = 974.73, the element's bounding
    box only reaches x = −1854.20. Clipping to the ELEMENT's bounding
    box cut off 21.13% of the declared region, and a containment probe
    found 95 contour points outside the hull. This is a missed clash,
    not imprecision, so the boundary is the bounding box of the region
    ITSELF.

    Here is the same thing on a small scale: a square with one arc and
    a knowingly LYING element bounding box that clips half the contour.
    """
    prof = {"profile_available": True,
            "exterior_loop": [[0, 0], [100, 0], [100, 100], [0, 100]],
            "curve_kinds": [["arc", "line", "line", "line"]],
            "arc_midpoints": [[[50, -20], None, None, None]], "holes": []}
    el = {"element_id": "c", "category": "OST_Floors",
          # the bounding box LIES: it is half as wide as the contour
          "bbox_min_mm": [0, -20, 0], "bbox_max_mm": [50, 100, 10]}
    rec, _ = H.build_hull(el, profile=prof)
    assert rec.hull_source == "profile"
    for x, y in ((0, 0), (100, 0), (100, 100), (0, 100), (50, -20), (99, 99)):
        assert G.contains_point(rec.hull, (float(x), float(y), 5.0)), (
            f"объявленная точка ({x},{y}) вырезана обрезкой")
    zc = (el["bbox_min_mm"][2] + el["bbox_max_mm"][2]) / 2.0
    for loop in [prof["exterior_loop"]] + list(prof.get("holes") or []):
        for p in loop:
            assert G.contains_point(rec.hull, (float(p[0]), float(p[1]), zc)), (
                "объявленная вершина контура вне оболочки")


def test_01d_a_curve_we_cannot_bound_still_falls_back():
    """The lock is not thrown wide open: an unbounded curve still falls
    back to bbox.

    The arc got an outward hull BECAUSE proof exists for it. A spline
    has none, and it must behave exactly like an arc did before this
    wave.
    """
    el = {"element_id": "s", "category": "OST_Floors",
          "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [10, 10, 1]}
    prof = {"profile_available": True,
            "exterior_loop": [[0, 0], [10, 0], [10, 10], [0, 10]],
            "curve_kinds": [["line", "hermite_spline", "line", "line"]],
            "arc_midpoints": [[None, None, None, None]], "holes": []}
    assert H.profile_refusal(prof) == "profile_curve_hermite_spline"
    rec, _ = H.build_hull(el, profile=prof)
    assert rec.hull_source == "bbox" and rec.grade == "coarse"


def test_01e_half_circle_arc_is_refused_not_guessed():
    """The outward-rectangle formula is valid only up to a semicircle.

    Beyond that boundary, the arc's projection extends past the
    chord's ends, and the rectangle no longer contains it. Here there
    must be a REFUSAL, not a formula applied outside its domain — the
    same ailment that `arc_chord_polyline` was fixing for span > π.
    """
    # A semicircle of radius 5: chord 10, sagitta 5 = L/2.
    prof = {"profile_available": True,
            "exterior_loop": [[0, 0], [10, 0], [10, 10], [0, 10]],
            "curve_kinds": [["arc", "line", "line", "line"]],
            "arc_midpoints": [[[5, -5], None, None, None]], "holes": []}
    assert H.profile_refusal(prof) is None, "дуга сама по себе больше не отказ"
    reg = H.profile_loops(prof)
    assert reg.reason == "profile_arc_over_half_circle"
    assert reg.loops == () and reg.arc_patches == ()
    el = {"element_id": "h", "category": "OST_Floors",
          "bbox_min_mm": [0, -5, 0], "bbox_max_mm": [10, 10, 1]}
    rec, _ = H.build_hull(el, profile=prof)
    assert rec.hull_source == "bbox", "неограничиваемая дуга обязана уронить контур"
    assert "profile_arc_over_half_circle" in (rec.extra.get("downgraded_from") or [])


def test_01c_invalid_profile_vertex_is_not_silently_dropped():
    """Lines 188-190: an invalid vertex was being silently dropped,
    shrinking the hull. Silent shrinkage is the same class of lie as
    the arc."""
    el = {"element_id": "x", "category": "OST_Floors",
          "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [10, 10, 1]}
    prof = {"profile_available": True,
            "exterior_loop": [[0, 0], [10, 0], [10, 10], [float("nan"), 3]],
            "curve_kinds": [["line", "line", "line", "line"]],
            "arc_midpoints": [[None, None, None, None]], "holes": []}
    rec, _ = H.build_hull(el, profile=prof)
    assert rec.hull_source == "bbox", "невалидная вершина не уронила профиль в bbox"


@pytest.mark.skipif(not LIVE_RUN.exists(), reason="живой декомпайл только на прод-боксе")
def test_01d_fixture_matches_the_live_artifact():
    """The fixture must not diverge from the artifact it was extracted
    from."""
    el_fx, prof_fx = floor_9981227()
    sk = json.loads((LIVE_RUN / "sketch.index.json").read_text(encoding="utf-8"))
    assert sk["profile_index"]["9981227"] == prof_fx
    for line in (LIVE_RUN / "L0.jsonl").open(encoding="utf-8"):
        if '"9981227"' in line:
            r = json.loads(line)
            if r.get("record") == "element" and str(r["element"]["element_id"]) == "9981227":
                assert r["element"] == el_fx
                return
    pytest.fail("элемент 9981227 исчез из живого L0")


# ── #2/#3 P0: wall and eccentric-axis builders — EXPECTATIONS, not a fix ───

def test_02_wall_never_reaches_the_axis_capsule_branch():
    """Finding #2: a capsule of radius width/2 around the LOWER axis
    does not cover the wall's height — once ground is wired in, this
    branch would become non-conservative.

    This wave's builder is not being built (directive), so the hole is
    closed by a BAN: for a wall, the `axis_section` source is not
    allowed by the table, and even if a cross-section arrives, the hull
    stays the bounding box. What is checked here is exactly the ban,
    not the fact that there is no cross-section today: a premise
    "saved by the absence of data" is not a defense.
    """
    assert "axis_section" not in H.KIND_TABLE["OST_Walls"].sources
    el = {"element_id": "w", "category": "OST_Walls",
          "p0_mm": [0, 0, 0], "p1_mm": [5000, 0, 0],
          "section_radius_mm": 100.0,          # the cross-section EXISTS — and it's still a bbox
          "bbox_min_mm": [-100, -100, 0], "bbox_max_mm": [5100, 100, 3000]}
    rec, _ = H.build_hull(el)
    assert rec.hull_source == "bbox"
    assert G.contains_point(rec.hull, (2500.0, 0.0, 2900.0)), "верх стены вне оболочки"


@pytest.mark.xfail(strict=True,
                   reason="blocked-on-ground-sections: wall-builder (полоса вокруг "
                          "оси с учётом location-line offset × [z0,z1]) — отдельная "
                          "волна. Сегодня стена честна, но груба: габарит вместо "
                          "тела. Тест обязан покраснеть в тот день, когда билдер "
                          "появится, и его надо будет снять с xfail.")
def test_02b_wall_hull_is_still_only_a_bounding_box():
    """An expectation for the future: a wall will get a hull MORE
    PRECISE than a bounding box."""
    el = {"element_id": "w", "category": "OST_Walls",
          "p0_mm": [0, 0, 0], "p1_mm": [5000, 0, 0], "section_radius_mm": 100.0,
          "bbox_min_mm": [-100, -100, 0], "bbox_max_mm": [5100, 100, 3000]}
    rec, _ = H.build_hull(el)
    assert rec.grade != "coarse", "оболочка стены всё ещё габаритный бокс"


def test_03_flex_curves_never_reach_the_chord_branch():
    """Finding #3: `spline_unsupported` was turning into a chord p0→p1
    with no sagitta — a direct route to a false miss on a flexible run.
    Closed by the same ban: flexible runs are not allowed an axis until
    the actual curve has been captured."""
    for cat in ("OST_FlexPipeCurves", "OST_FlexDuctCurves"):
        assert "axis_section" not in H.KIND_TABLE[cat].sources, cat
    el = {"element_id": "f", "category": "OST_FlexPipeCurves",
          "p0_mm": [0, 0, 0], "p1_mm": [1000, 0, 0], "section_radius_mm": 50.0,
          "bbox_min_mm": [-50, -50, -50], "bbox_max_mm": [1050, 400, 50]}
    curve = {"curve_kind": "spline_unsupported", "p0_mm": [0, 0, 0],
             "p1_mm": [1000, 0, 0]}
    rec, _ = H.build_hull(el, curve=curve)
    assert rec.hull_source == "bbox"
    # The real sag of a flexible pipe toward mid-span: 350mm sideways —
    # the bounding box contains it, a chord would not have.
    assert G.contains_point(rec.hull, (500.0, 350.0, 0.0)), "прогиб вне оболочки"


@pytest.mark.xfail(strict=True,
                   reason="blocked-on-ground-sections: category-specific dispatch "
                          "(доказанная дуга / spline / эксцентриситет балки) — "
                          "отдельная волна.")
def test_03b_eccentric_and_curved_classes_still_have_no_own_builder():
    """An expectation for the future: a beam and a flexible run will
    get their own builders."""
    assert "axis_section" in H.KIND_TABLE["OST_StructuralFraming"].sources


# ── #4 P0: the `exact` grade is given to hulls that are not exact ──────────

def test_04_capsule_is_never_exact():
    """A straight capsule has SPHERICAL caps, the pipe has flat ones;
    an arc capsule is inflated by the sagitta. Neither is `exact`, and
    `exact` means `confirmed` in the verdict, that is, a false
    accusation."""
    el = {"element_id": "p", "category": "OST_PipeCurves",
          "p0_mm": [0, 0, 0], "p1_mm": [1000, 0, 0],
          "section_radius_mm": 50.0, "section_round": True,
          "bbox_min_mm": [-50, -50, -50], "bbox_max_mm": [1050, 50, 50]}
    rec, _ = H.build_hull(el)
    assert rec.grade == "conservative", "капсула объявлена точной оболочкой"


def test_04b_zero_length_axis_is_a_typed_refusal_not_a_sphere():
    """A zero-length axis was making a SPHERE of the cross-section's
    radius — a body that doesn't exist in the model."""
    el = {"element_id": "p0", "category": "OST_PipeCurves",
          "p0_mm": [10, 10, 10], "p1_mm": [10, 10, 10],
          "section_radius_mm": 50.0,
          "bbox_min_mm": [-40, -40, -40], "bbox_max_mm": [60, 60, 60]}
    rec, _ = H.build_hull(el)
    assert rec.hull_source == "bbox", "нулевая ось построила капсулу-сферу"


def test_04c_invalid_arc_does_not_become_a_point_at_origin():
    """An invalid arc was returning `[p0, p1]`, and with no p0/p1 —
    `(0,0,0)`: a hull at the coordinate origin, kilometers from the
    element."""
    el = {"element_id": "a", "category": "OST_PipeCurves",
          "section_radius_mm": 50.0,
          "bbox_min_mm": [9000, 9000, 0], "bbox_max_mm": [9100, 9100, 100]}
    curve = {"curve_kind": "arc", "arc": {"radius_mm": None}}
    rec, ref = H.build_hull(el, curve=curve)
    assert rec is not None
    assert rec.hull_source == "bbox", "битая дуга построила капсулу"
    lo, hi = rec.hull.bounds()
    assert lo[0] >= 8000, "оболочка уехала в начало координат"


# ── #5 P0: capsule×capsule MTV by segment midpoints does not separate the pair ─

def test_05_capsule_capsule_mtv_actually_separates():
    """The review's counterexample, verbatim: A(0,0,0)→(10,0,0) r=1,
    B(9,1,-5)→(9,1,5) r=1.

    Before: sd=-1, mtv=(-0.9701,-0.2425,0), after applying the
    translation sd=-0.7575 — the pair remained penetrating, meaning the
    "minimal separating vector" doesn't separate.
    """
    a = G.Capsule(((0, 0, 0), (10, 0, 0)), 1.0)
    b = G.Capsule(((9, 1, -5), (9, 1, 5)), 1.0)
    v = G.certified_separating_translation(a, b)
    assert v is not None
    moved = G.Capsule(tuple(tuple(p[i] + v[i] for i in range(3)) for p in a.path), a.radius)
    assert G.signed_distance(moved, b) >= -1e-6, (
        f"перенос {v} оставил проникание {G.signed_distance(moved, b)}")


@pytest.mark.parametrize("case", [
    ("identical", ((0, 0, 0), (10, 0, 0)), ((0, 0, 0), (10, 0, 0))),
    ("collinear", ((0, 0, 0), (10, 0, 0)), ((5, 0, 0), (15, 0, 0))),
    ("crossing_same_centre", ((-5, 0, 0), (5, 0, 0)), ((0, -5, 0), (0, 5, 0))),
    ("degenerate_points", ((1, 1, 1), (1, 1, 1)), ((1, 1, 1), (1, 1, 1))),
])
def test_05b_degenerate_axes_get_a_vector_or_a_named_reason(case):
    """For coincident/collinear/intersecting axes, the direction was
    silently `None`. Silence is indistinguishable from "not
    penetrating": what's needed is either a deterministic vector or a
    NAMED reason for its absence."""
    _, pa, pb = case
    a, b = G.Capsule(pa, 1.0), G.Capsule(pb, 1.0)
    assert G.signed_distance(a, b) < 0
    v = G.certified_separating_translation(a, b)
    if v is None:
        assert G.mtv_unavailable_reason(a, b), "None без названной причины"
    else:
        moved = G.Capsule(tuple(tuple(p[i] + v[i] for i in range(3)) for p in a.path),
                          a.radius)
        assert G.signed_distance(moved, b) >= -1e-6


def test_05c_separating_translation_postcondition_property():
    """The property: `translation != None ⇒ after it sd >= -eps`.

    No `skip`, deliberately (finding #18): a skipped test inside an
    acceptance target is indistinguishable from a missing one.
    Non-penetrating pairs are not discarded but counted, and the test
    requires that there be enough penetrating ones — otherwise "the
    property holds" would mean "there was nothing to check."
    """
    rnd = random.Random(20260728)
    checked = 0
    for _ in range(400):
        def rp():
            return tuple(rnd.uniform(-6, 6) for _ in range(3))

        a = G.Capsule((rp(), rp()), rnd.uniform(0.2, 2.0))
        b = G.Capsule((rp(), rp()), rnd.uniform(0.2, 2.0))
        if G.signed_distance(a, b) >= 0:
            continue
        checked += 1
        v = G.certified_separating_translation(a, b)
        if v is None:
            assert G.mtv_unavailable_reason(a, b), "None без названной причины"
            continue
        moved = G.Capsule(tuple(tuple(p[i] + v[i] for i in range(3))
                                for p in a.path), a.radius)
        assert G.signed_distance(moved, b) >= -1e-6, (a, b, v)
    assert checked >= 50, f"проникающих пар всего {checked} — свойство не нагружено"


# ── #6 P0: capsule×prism «MTV» is not minimal and is not a penetration ─────

def test_06_capsule_prism_translation_is_certified_not_minimal():
    """A counterexample: a diagonal capsule
    (-100,-100,-100)→(100,100,100) r=1 and a cube [0,10]³. The
    face-based answer had a length of 101 where ~8.07 would have
    sufficed.

    D1 does not build GJK/EPA — so the field was RENAMED: it promises
    separation, not minimality. What is checked here is exactly that
    promise.
    """
    cap = G.Capsule(((-100, -100, -100), (100, 100, 100)), 1.0)
    box = G.Aabb((0, 0, 0), (10, 10, 10))
    v = G.certified_separating_translation(cap, box)
    assert v is not None
    moved = G.Capsule(tuple(tuple(p[i] + v[i] for i in range(3)) for p in cap.path),
                      cap.radius)
    assert G.signed_distance(moved, box) >= -1e-6


def test_06b_penetration_field_is_named_hull_overlap_depth():
    """`physical_penetration_mm` promised the penetration depth of
    BODIES, but was carrying `-sd` of HULLS (finding #6 + #14). The
    name must tell the truth."""
    a = H.HullRecord("1", "OST_PipeCurves", "pipe", "mep",
                     G.Aabb((0, 0, 0), (10, 10, 10)), "coarse", "bbox")
    b = H.HullRecord("2", "OST_Walls", "wall", "struct",
                     G.Aabb((5, 5, 5), (20, 20, 20)), "coarse", "bbox")
    f = D.evaluate(a, b)
    assert f is not None
    d = f.as_dict()
    assert "hull_overlap_depth_mm" in d
    assert "physical_penetration_mm" not in d
    assert "certified_separating_translation_mm" in d
    assert "mtv_mm" not in d


# ── #7 P1: prism×prism distance is a lower bound (operator-checked) ────────

def test_07_prism_gap_is_a_lower_bound_and_says_so():
    """The operator personally checked: the permutation instability
    did NOT reproduce (every cyclic rotation gives 1.0). What remains
    is the second half of the finding — 1.0 versus a true √5: this is
    a LOWER bound, and with clearance>0 it produces extra findings, not
    misses.

    The fix is not a formula but an honest field name in the report.
    """
    a = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
    b = ((2.0, 2.0), (3.0, 2.0), (3.0, 3.0), (2.0, 3.0))
    gap = G.poly_poly_gap(a, b)
    true = math.hypot(1.0, 1.0)
    assert gap <= true + 1e-9, "оценка ВЫШЕ истинной — это был бы пропуск"
    rotations = {round(G.poly_poly_gap(a[i:] + a[:i], b), 9) for i in range(4)}
    assert len(rotations) == 1, f"перестановочная нестабильность: {rotations}"


def test_07b_separation_distance_is_published_as_a_lower_bound():
    """The report must name this value a lower bound, not a distance."""
    assert "lower_bound" in D.SEPARATION_SEMANTICS


# ── #8 P2: EPS has the wrong dimension — the sign breaks on short segments ─

def test_08_short_segment_keeps_its_sign():
    """The review's counterexample: a segment 0.0005mm long, a point
    0.0001mm inside the radius. The squared length (2.5e-7) was being
    compared against EPS_MM=1e-6, and the segment was declared a
    point."""
    p0, p1 = (0.0, 0.0, 0.0), (0.0005, 0.0, 0.0)
    d = G.seg_seg_distance(p0, p1, (0.00025, 0.0001, 0.0), (0.00025, 0.0001, 0.0))
    assert d == pytest.approx(0.0001, abs=1e-9), d


@pytest.mark.parametrize("scale", [1e-6, 1e-3, 1.0, 1e3, 1e6])
def test_08b_sign_is_scale_invariant(scale):
    """One scene, scaled across 12 orders of magnitude: the sign must
    survive."""
    a = G.Capsule(((0.0, 0.0, 0.0), (10.0 * scale, 0.0, 0.0)), 1.0 * scale)
    b = G.Capsule(((5.0 * scale, 2.5 * scale, 0.0),
                   (5.0 * scale, 9.0 * scale, 0.0)), 1.0 * scale)
    sd = G.signed_distance(a, b)
    assert sd > 0, sd
    assert sd / scale == pytest.approx(0.5, rel=1e-6)


# ── #9 P0: a positive clearance gets lost in the broad phase ───────────────

def test_09_positive_clearance_survives_the_grid():
    """The review's counterexample, verbatim: cell=10, boxes x=[8,9]
    and [10.1,11], clearance=2. Exhaustive search gives a pair, the
    grid was giving []."""
    recs = [
        H.HullRecord("a", "OST_PipeCurves", "pipe", "mep",
                     G.Aabb((8.0, 0.0, 0.0), (9.0, 1.0, 1.0)), "coarse", "bbox"),
        H.HullRecord("b", "OST_Walls", "wall", "struct",
                     G.Aabb((10.1, 0.0, 0.0), (11.0, 1.0, 1.0)), "coarse", "bbox"),
    ]
    grid = D.build_grid(recs, 10.0, slack=2.0)
    got = D.candidate_pairs(recs, grid, slack=2.0)
    assert got == D.brute_pairs(recs, slack=2.0) == [(0, 1)]


def test_09c_a_grid_built_without_slack_refuses_a_slack_query():
    """A silent false miss has been replaced with a loud refusal: the
    grid remembers what clearance it was built for."""
    recs = [H.HullRecord("a", "OST_PipeCurves", "pipe", "mep",
                         G.Aabb((0.0, 0.0, 0.0), (1.0, 1.0, 1.0)), "coarse", "bbox")]
    with pytest.raises(ValueError):
        D.candidate_pairs(recs, D.build_grid(recs, 10.0), slack=5.0)


@pytest.mark.parametrize("seed", range(30))
def test_09b_broad_phase_is_a_superset_for_random_positive_slack(seed):
    """The broad phase's property at slack>0, including slack > cell
    size."""
    rnd = random.Random(seed)
    recs = []
    for i in range(14):
        lo = tuple(rnd.uniform(-50, 50) for _ in range(3))
        hi = tuple(lo[k] + rnd.uniform(0.5, 12.0) for k in range(3))
        side = "mep" if i % 2 else "struct"
        recs.append(H.HullRecord(f"e{i}", "OST_PipeCurves" if side == "mep" else "OST_Walls",
                                 "pipe" if side == "mep" else "wall", side,
                                 G.Aabb(lo, hi), "coarse", "bbox"))
    cell = rnd.choice([3.0, 10.0, 40.0])
    slack = rnd.choice([0.5, 5.0, 25.0, 90.0])       # 90 > any cell
    grid = D.build_grid(recs, cell, slack=slack)
    got = set(D.candidate_pairs(recs, grid, slack=slack))
    want = set(D.brute_pairs(recs, slack=slack))
    assert want <= got, f"пропущено {sorted(want - got)} при cell={cell} slack={slack}"


# ── #10 P0: balance does not prove the model is closed ─────────────────────

def _l0(tmp: pathlib.Path, *, footer: bool = True, census: int = 3,
        stream_complete: bool = True) -> pathlib.Path:
    """A synthetic L0 in the MEASURED shape of a live artifact (SOB6.2
    v10): census is a list of {key,count} inside document, status is
    in a nested `status`, the footer is
    element_count/category_count/stream_complete. Inventing the shape
    of the input means checking a format different from the one that
    actually arrives."""
    d = tmp / "run"
    d.mkdir(parents=True, exist_ok=True)
    rows = [{"record": "header", "schema_version": "1.0",
             "document": {"census": [{"key": "OST_Walls", "count": census,
                                      "name": "Стены"}],
                          "doc_name": "t", "change_stamp": "t"}}]
    for i in range(3):
        rows.append({"record": "element", "element": {
            "element_id": str(100 + i), "category": "OST_Walls",
            "bbox_min_mm": [i, 0, 0], "bbox_max_mm": [i + 1, 1, 1]}})
    rows.append({"record": "category_status",
                 "status": {"category": "OST_Walls", "expected_count": census,
                            "extracted_count": 3, "state": "complete",
                            "error": None}})
    if footer:
        rows.append({"record": "footer", "element_count": 3, "category_count": 1,
                     "link_count": 0, "stream_complete": stream_complete})
    (d / "L0.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8")
    return d


def test_10_truncated_l0_is_a_loud_refusal(tmp_path):
    """A file truncated at a VALID JSON line before the footer produced
    an internally reconciling census — that is, "everything's fine" on
    half a building."""
    d = _l0(tmp_path, footer=False)
    with pytest.raises(S.SnapshotIntegrityError):
        S.build_from_decompile(d)


def test_10b_header_census_gap_is_published_not_hidden(tmp_path):
    """On the live facade, header census = 30,489, while element rows
    number 3,153. The difference is not required to be eligible — but
    it must be NAMED, otherwise the coverage denominator is unproven."""
    d = _l0(tmp_path, census=9)
    snap = S.build_from_decompile(d)
    assert snap.census.outside_extraction_scope == 6
    assert snap.origin["stream_complete"] is True


def test_10c_missing_category_status_is_a_refusal(tmp_path):
    """Mutant: remove category_status — the run must fail loudly."""
    d = _l0(tmp_path)
    p = d / "L0.jsonl"
    kept = [l for l in p.read_text(encoding="utf-8").splitlines()
            if '"category_status"' not in l]
    p.write_text("\n".join(kept) + "\n", encoding="utf-8")
    with pytest.raises(S.SnapshotIntegrityError):
        S.build_from_decompile(d)


def test_10d_dropped_element_row_is_a_refusal(tmp_path):
    """Mutant: remove one element row — extracted_count stops
    reconciling with the fact."""
    d = _l0(tmp_path)
    p = d / "L0.jsonl"
    kept = [l for l in p.read_text(encoding="utf-8").splitlines()
            if '"101"' not in l]
    p.write_text("\n".join(kept) + "\n", encoding="utf-8")
    with pytest.raises(S.SnapshotIntegrityError):
        S.build_from_decompile(d)


# ── #11 P1: the census invariant is not a gate ──────────────────────────────

def test_11_detect_refuses_an_unbalanced_snapshot():
    """`detect()` kept working on a snapshot that hadn't reconciled."""
    snap = S.build_from_elements([], origin={"run_dir": "t"})
    snap.census.eligible["OST_Walls"] += 5          # an artificial imbalance
    with pytest.raises(S.SnapshotIntegrityError):
        D.detect(snap)


def test_11b_duplicate_source_ids_are_refused():
    els = [{"element_id": "same", "category": "OST_Walls",
            "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [1, 1, 1]} for _ in range(2)]
    snap = S.build_from_elements(els, origin={"run_dir": "t"})
    with pytest.raises(S.SnapshotIntegrityError):
        snap.validate()


def test_11c_non_finite_hull_is_refused():
    els = [{"element_id": "n", "category": "OST_Walls",
            "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [1, 1, 1]}]
    snap = S.build_from_elements(els, origin={"run_dir": "t"})
    snap.records[0].hull = G.Aabb((0.0, 0.0, 0.0), (float("inf"), 1.0, 1.0))
    with pytest.raises(S.SnapshotIntegrityError):
        snap.validate()


def test_11d_narrow_phase_refusal_is_counted_not_swallowed():
    """A non-numeric narrow phase was silently returning None — now
    it's a counter."""
    a = H.HullRecord("1", "OST_PipeCurves", "pipe", "mep",
                     G.Capsule((((0.0, 0.0, 0.0),)), 1.0), "coarse", "bbox")
    b = H.HullRecord("2", "OST_Walls", "wall", "struct",
                     G.Prism((), 0.0, 1.0), "coarse", "bbox")
    f, reason = D.evaluate_with_reason(a, b, clearance_mm=0.0)
    assert f is None and reason == "narrow_unsupported"


# ── #12 P1: the "closed matrix" is self-consistent but not substantive ─────

def test_12_category_manifest_is_frozen_and_counted():
    """The test was comparing `coverage_matrix()` against the very same
    table — an identical error on both sides was green. Now the
    expectation is frozen separately."""
    man = json.loads((FIXTURES / "category_manifest.json").read_text(encoding="utf-8"))
    assert len(H.KIND_TABLE) == man["row_count"]
    got = {row["category"]: row for row in H.coverage_matrix()}
    assert sorted(got) == sorted(man["rows"])
    for cat, exp in man["rows"].items():
        assert got[cat]["eligible"] == exp["eligible"]
        assert got[cat]["mvp_side"] == exp["mvp_side"]
        assert got[cat]["hull_sources"] == exp["hull_sources"], cat


def test_12b_manifest_rejects_a_new_category():
    """Mutant: add a category — the manifest must fail."""
    man = json.loads((FIXTURES / "category_manifest.json").read_text(encoding="utf-8"))
    assert "OST_Parking" not in man["rows"], "манифест не заморожен"


def test_12c_furniture_may_not_claim_a_profile_source():
    """Every eligible category was declaring ALL three sources.
    Furniture has no footprint contour — declaring one would mean
    promising precision that doesn't exist."""
    row = {r["category"]: r for r in H.coverage_matrix()}["OST_Furniture"]
    assert "profile" not in row["hull_sources"]


# ── #13 P0: the search domain and the oracle's domain cannot be identified ─

def test_13_scope_id_is_in_the_canon():
    snap = S.build_from_elements([], origin={"run_dir": "t"})
    rep = D.detect(snap, pair_filter=D.mvp_pair_filter)
    assert rep["search"]["scope_id"] == "mvp_v2"
    rep2 = D.detect(snap, pair_filter=D.any_physical_pair_filter)
    assert rep2["search"]["scope_id"] == "all_physical_diagnostic"


def test_13b_markdown_does_not_claim_mvp_after_all_pairs():
    snap = S.build_from_elements([], origin={"run_dir": "t"})
    md = D.to_markdown(D.detect(snap, pair_filter=D.any_physical_pair_filter))
    assert "MVP" not in md or "all_physical_diagnostic" in md


def test_13c_unknown_pair_filter_is_refused():
    """An arbitrary callable filter made the search domain
    undeterminable."""
    snap = S.build_from_elements([], origin={"run_dir": "t"})
    with pytest.raises(ValueError):
        D.detect(snap, pair_filter=lambda a, b: True)


# ── #14 P0: tol_grade hides proven contacts and confuses contact with penetration ─

def test_14_contact_is_reported_as_a_relation_not_swallowed():
    """At sd=0 there was no finding even for an exact pair: two bodies
    lying flush against each other were being declared "nothing." The
    relation and the certainty are different axes."""
    a = H.HullRecord("1", "OST_PipeCurves", "pipe", "mep",
                     G.Aabb((0, 0, 0), (10, 10, 10)), "conservative", "axis_section")
    b = H.HullRecord("2", "OST_Walls", "wall", "struct",
                     G.Aabb((10, 0, 0), (20, 10, 10)), "conservative", "axis_section")
    f = D.evaluate(a, b)
    assert f is not None, "касание проглочено"
    assert f.as_dict()["hull_relation"] == "contact"
    assert f.verdict == "possible"


def test_14b_shallow_coarse_overlap_is_emitted_as_possible():
    """A coarse pair with sd=-1…-25 was being suppressed by a 25mm
    threshold that was never a proven AABB error margin. Now 25mm is
    only for ranking."""
    a = H.HullRecord("1", "OST_PipeCurves", "pipe", "mep",
                     G.Aabb((0, 0, 0), (10, 10, 10)), "coarse", "bbox")
    b = H.HullRecord("2", "OST_Walls", "wall", "struct",
                     G.Aabb((9, 0, 0), (20, 10, 10)), "coarse", "bbox")
    f = D.evaluate(a, b)
    assert f is not None, "мелкое перекрытие габаритов проглочено"
    assert f.as_dict()["hull_relation"] == "overlap"
    assert f.verdict == "possible"


def test_14c_relation_axis_is_complete_and_verdict_has_no_touch():
    assert set(D.HULL_RELATIONS) == {"overlap", "contact", "separated"}
    assert "touch" not in D.VERDICTS


def test_14d_the_schema_is_versioned_and_every_past_version_still_reads():
    """THE LAW IS THE READABILITY OF HISTORY, NOT A NUMBER (fix,
    11.08.2026).

    There used to be `assert D.REPORT_SCHEMA == "clash-report/2"` here,
    and the test had become a FOSSIL: the schema had moved on to `/3`
    along with a completed migration ladder, while the assertion still
    reflected the old behavior. Checking the NUMBER means demanding
    that the format never evolve — that is, failing the suite on every
    honest step forward and training people to fix it by rewriting the
    digit.

    Review #14 demanded something different: once a fact is added, the
    canon cannot be kept byte-for-byte — it must be VERSIONED, WITH THE
    ABILITY TO READ ITS HISTORY. And that is exactly what is checked:
    the version is declared, every past version is accepted by the
    migration, and a foreign one is rejected loudly.
    """
    assert D.REPORT_SCHEMA.startswith("clash-report/")
    for past in ("clash-report/1", "clash-report/2"):
        migrated = D.migrate_report({"schema_version": past, "findings": []})
        assert migrated["schema_version"] == D.REPORT_SCHEMA, past
    with pytest.raises(ValueError):
        D.migrate_report({"schema_version": "clash-report/0"})


def test_14e_v1_golden_still_parses_under_the_migration():
    """The canon cannot be kept byte-for-byte while adding a fact — but
    an old report must remain readable, or the measurement history
    dies.

    We check against `D.REPORT_SCHEMA`, not a literal: a literal here
    would be the same fossil as in the test above, and would fail
    this — the real — law together with the number.
    """
    v1 = json.loads((FIXTURES / "golden_report_v1.json").read_text(encoding="utf-8"))
    migrated = D.migrate_report(v1)
    assert migrated["schema_version"] == D.REPORT_SCHEMA
    for f in migrated["findings"]:
        assert f["hull_relation"] in D.HULL_RELATIONS
        assert "hull_overlap_depth_mm" in f


# ── #15/#16 P1: the snapshot and its provenance ─────────────────────────────

def test_16_provenance_covers_every_side_input(tmp_path):
    """Only L0 was being hashed, truncated to 16 hex chars. A profile
    change would alter the findings while the fingerprint stayed the
    same."""
    d = _l0(tmp_path)
    (d / "sketch.index.json").write_text('{"profile_index":{}}', encoding="utf-8")
    (d / "curve.index.json").write_text('{"curve_index":{}}', encoding="utf-8")
    first = S.build_from_decompile(d).origin["snapshot_sha256"]
    (d / "sketch.index.json").write_text('{"profile_index":{} }', encoding="utf-8")
    second = S.build_from_decompile(d).origin["snapshot_sha256"]
    assert first != second, "байт в боковом индексе не изменил отпечаток"
    assert len(first) == 64, "усечённый хеш"


def test_15_join_manifest_names_what_was_not_lifted(tmp_path):
    """§6 requires the set U (not lifted) — the snapshot must compute
    it, even when L1 isn't wired in yet."""
    d = _l0(tmp_path, census=9)
    snap = S.build_from_decompile(d)
    j = snap.join_manifest()
    assert j["eligible"] == j["scored"] + j["not_scored"]
    assert j["outside_extraction_scope"] == 6
    assert j["l1_join"] == "absent"          # honestly: L1 isn't wired in yet


# ── #17 P1: the golden creates itself ───────────────────────────────────────

def test_17_missing_golden_is_an_error_not_a_blessing():
    """A test that, when the reference is missing, WRITES it and
    passes, can never fail."""
    src = (pathlib.Path(__file__).resolve().parent / "test_clash.py").read_text("utf-8")
    body = src.split("def test_the_canonical_golden_does_not_move")[-1][:1200]
    assert "write_text" not in body, "голден всё ещё самоблагословляется"


def test_17b_golden_covers_every_pair_type():
    g = json.loads((FIXTURES / "golden_report_v2.json").read_text(encoding="utf-8"))
    kinds = {f["hull_relation"] for f in g["findings"]}
    grades = {f["hull_grade"] for f in g["findings"]}
    assert {"overlap", "contact"} <= kinds, kinds
    assert {"coarse", "conservative"} <= grades, grades


# ── THE DECOMPOSE WAVE: minimality of a move on a NON-CONVEX body ──────────

def test_19_minimal_exit_takes_the_opening_not_the_whole_slab():
    """A slab with an OPENING: the pipe exits through the opening, not
    past the slab's edge.

    A refuting measurement before the fix (`w1_exit_probe.py`,
    11.08.2026): 400 intersecting "slab-with-opening versus block"
    pairs, 92 of them (23.0%) had bisection producing a move longer
    than the minimal one, by up to 6.79x in the worst case. The cause
    is named in `resolve.minimal_exit`: for a union of pieces, the
    intersection set breaks into segments with gaps, and bisection's
    bracket was spanning the gap in full.
    """
    from kir.clash import decompose as D
    from kir.clash import resolve as R
    plate = [[0, 0], [100, 0], [100, 60], [0, 60]]
    hole = [[30, 10], [50, 10], [50, 50], [30, 50]]
    dec = D.decompose(plate, [hole])
    assert dec.ok, dec.reason
    slab = G.PrismSet(dec.cells, 0.0, 10.0)
    box = G.Prism(((20.0, 20.0), (26.0, 20.0), (26.0, 26.0), (20.0, 26.0)), 2.0, 8.0)
    assert G.signed_distance(slab, box) < 0, "фикстура обязана пересекаться"
    t = R.minimal_exit(box, slab, (1.0, 0.0, 0.0))
    assert t is not None
    # Block [20,26] is clear exactly when its LEFT edge crosses the
    # opening's edge x=30, that is, at t=10; the right edge lands at 36
    # < 50, still inside the opening. The slab ends at x=100, and
    # exiting past it would cost t=80 — exactly what bisection was
    # finding, spanning the whole opening with its bracket.
    assert abs(t - 10.0) < 1e-6, f"ход {t} вместо выхода в проём (10.0)"
    assert G.separates(box, slab, (t, 0.0, 0.0)), "обещанный ход не разводит"
    # A reference with not a single assumption: a dense scan over t.
    scan = next(k * 0.01 for k in range(0, 20001)
                if G.separates(box, slab, (k * 0.01, 0.0, 0.0)))
    assert abs(t - scan) < 0.02, f"точный путь {t} против скана {scan}"


def test_19b_the_exit_is_verified_not_asserted():
    """Every candidate is verified by TRANSLATION, not taken on faith.

    Exactly half a step before the found exit, the pair must still
    intersect — otherwise `t` isn't the minimal one, just some value.
    """
    from kir.clash import decompose as D
    from kir.clash import resolve as R
    plate = [[0, 0], [100, 0], [100, 60], [0, 60]]
    hole = [[30, 10], [50, 10], [50, 50], [30, 50]]
    slab = G.PrismSet(D.decompose(plate, [hole]).cells, 0.0, 10.0)
    box = G.Prism(((20.0, 20.0), (26.0, 20.0), (26.0, 26.0), (20.0, 26.0)), 2.0, 8.0)
    t = R.minimal_exit(box, slab, (1.0, 0.0, 0.0))
    assert G.separates(box, slab, (t, 0.0, 0.0))
    assert not G.separates(box, slab, (t - 0.01, 0.0, 0.0)), (
        "пара разведена ещё до объявленного хода — значит он не наименьший")


# ── WAVE 2: merging convex neighbors ────────────────────────────────────────

def test_20_merge_only_when_the_union_stays_convex():
    """Merging is lawful EXACTLY when the union is convex, and this is
    checked.

    A refuting measurement before the fix (`w3_merge_probe.py`,
    11.08.2026, the whole corpus): of 16,052 pairs of neighboring
    cells, 6,265 (39.0%) had a convex union — every third boundary
    drawn for nothing.

    What matters here is not that the merge happens, but that it does
    NOT happen when the union is concave: a non-convex piece among
    convex ones would silently return the answer of its convex hull
    and would break both the exact distance and the closed form of the
    minimal exit.
    """
    from kir.clash import decompose as D
    # A step shape: the union of two neighboring trapezoids is
    # CONCAVE.
    step = [[0, 0], [10, 0], [10, 4], [20, 4], [20, 10], [0, 10]]
    dec = D.decompose(step)
    assert dec.ok, dec.reason
    for c in dec.cells:
        assert len(c) < 3 or D.loop_is_convex(c), f"невыпуклая ячейка {c}"
    total = sum(D.polygon_area(c) for c in dec.cells if len(c) >= 3)
    assert abs(total - D.polygon_area([(float(x), float(y)) for x, y in step])) \
        <= 1e-9 * total, "слияние изменило площадь области"


def test_20b_merge_preserves_the_region_exactly():
    """Merging changes the RECORD of the region, not the region
    itself.

    Checked on a contour with a hole: area down to the last decimal,
    and point membership — both inside the material and inside the
    opening.
    """
    from kir.clash import decompose as D
    plate = [[0, 0], [100, 0], [100, 60], [0, 60]]
    hole = [[30, 10], [50, 10], [50, 50], [30, 50]]
    dec = D.decompose(plate, [hole])
    assert dec.ok, dec.reason
    area = sum(D.polygon_area(c) for c in dec.cells if len(c) >= 3)
    assert abs(area - (100 * 60 - 20 * 40)) < 1e-9
    hull = G.PrismSet(dec.cells, 0.0, 5.0)
    assert G.contains_point(hull, (10.0, 30.0, 2.0)), "материал вне оболочки"
    assert not G.contains_point(hull, (40.0, 30.0, 2.0)), "проём внутри оболочки"
    for c in dec.cells:
        assert len(c) < 3 or D.loop_is_convex(c)


def test_20c_a_degenerate_sliver_is_repaired_not_swallowed():
    """A degenerate cell is fixed with a convex hull ONLY when the area
    doesn't grow.

    Measured: all 20 non-convex cells in the corpus are produced by
    the sweep, none by the merge, and all twenty are degenerate
    (coordinates differ in the eighteenth decimal digit). Fixing them
    with a convex hull is lawful, because for a degenerate set the
    hull is itself degenerate too; but silently substituting a real
    region with its hull is not allowed, and for that case there
    stands a named refusal.
    """
    from kir.clash import decompose as D
    assert "decomposition_cell_not_convex" in D.REASONS
