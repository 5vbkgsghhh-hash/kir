"""A detector that "found 0 clashes" is indistinguishable from a
detector that never searched.

This is the same Goodhart that buried evaluator-judge, and the defense
against it here is not one check but the whole set: the census must
reconcile, the broad phase must be a SUPERSET of exhaustive search, the
hull must contain the element, and the report must be reproducible
byte-for-byte. Every item of the D1 completion criterion (canon §8.1)
has its own test here.

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

BACKEND = pathlib.Path(__file__).resolve().parents[3]
FACADE = BACKEND / "backend" / "data" / "decompile" / "sob62_fas_r23_v10"


# ── (в) geometry: what the review declared incorrect ───────────────────────

def test_a_slanted_segment_is_not_clashed_by_independent_xy_and_z():
    """Review #12's counterexample, verbatim.

    Segment (-2,0,-2)→(2,0,2) has an XY intersection with a narrow
    prism near x=0, while the relevant slice z=[0.9,1.1] passes through
    x≈1: independent minima along XY and along Z are both zero, even
    though there is no common point. Clamp-by-z would have declared a
    clash.
    """
    prism = G.Prism(((-0.1, -1.0), (0.1, -1.0), (0.1, 1.0), (-0.1, 1.0)), 0.9, 1.1)
    sd = G.seg_prism_signed_distance((-2, 0, -2), (2, 0, 2), prism)
    assert sd > 0, "наклонная труба объявлена пересекающей то, чего не касается"


def test_a_slanted_segment_through_a_prism_is_found():
    """The flip side: the same segment and a prism ON its path — a
    clash must be present, otherwise the first test would be satisfied
    by a detector that always stays silent."""
    prism = G.Prism(((0.9, -1.0), (1.1, -1.0), (1.1, 1.0), (0.9, 1.0)), 0.9, 1.1)
    sd = G.seg_prism_signed_distance((-2, 0, -2), (2, 0, 2), prism)
    assert sd < 0


@pytest.mark.parametrize("seed", range(12))
def test_segment_prism_sign_agrees_with_dense_sampling(seed):
    """The sign — checked against dense sampling of points along the
    segment. A numeric reference that knows nothing of our formula."""
    rnd = random.Random(seed)
    prism = G.Prism(((0.0, 0.0), (3.0, 0.0), (3.0, 2.0), (0.0, 2.0)),
                    0.0, 2.0)
    s0 = tuple(rnd.uniform(-4, 6) for _ in range(3))
    s1 = tuple(rnd.uniform(-4, 6) for _ in range(3))
    sd = G.seg_prism_signed_distance(s0, s1, prism)
    inside = any(G._point_in_prism(
        tuple(s0[k] + (s1[k] - s0[k]) * (i / 4000) for k in range(3)), prism)
        for i in range(4001))
    assert (sd < 0) == inside, (sd, inside, s0, s1)


def test_prism_distance_is_the_product_metric():
    """A prism is the Cartesian product of a footprint and an interval,
    so the distance decomposes: hypot(gap along XY, gap along Z), not
    the minimum of the two."""
    a = G.Prism(((0, 0), (1, 0), (1, 1), (0, 1)), 0, 1)
    b = G.Prism(((4, 0), (5, 0), (5, 1), (4, 1)), 4, 5)
    assert G.signed_distance(a, b) == pytest.approx(math.hypot(3, 3))


def test_zero_length_and_degenerate_segments_do_not_lie():
    """A zero-length pipe is a point, not a division error."""
    p = G.Capsule(((0, 0, 0), (0, 0, 0)), 50.0)
    q = G.Capsule(((0, 0, 80), (0, 0, 80)), 20.0)
    assert G.signed_distance(p, q) == pytest.approx(10.0)
    near = G.Capsule(((0, 0, 60), (0, 0, 60)), 20.0)
    assert G.signed_distance(p, near) < 0


def test_separating_translation_moves_a_and_leaves_b_alone():
    """A translation always means A moving while B stays fixed (review
    #13) — otherwise the vector's sign cannot be read. The name «MTV»
    was removed by review #6: the vector is certified as separating,
    not as minimal."""
    a = G.Prism(((0, 0), (2, 0), (2, 2), (0, 2)), 0, 2)
    b = G.Prism(((1, 0), (3, 0), (3, 2), (1, 2)), 0, 2)
    v = G.certified_separating_translation(a, b)
    assert v is not None
    moved = G.Prism(tuple((x + v[0], y + v[1]) for x, y in a.footprint),
                    a.z0 + v[2], a.z1 + v[2])
    assert G.signed_distance(moved, b) >= -1e-6, "перенос не вывел A из проникания"


def test_no_negative_zero_survives_serialization():
    assert G._norm_zero(-0.0) == 0.0
    assert math.copysign(1.0, G._norm_zero(-0.0)) > 0


# ── (г) adversarial corpus: the hull must CONTAIN the element ──────────────

def _sample_arc(arc: dict, n: int = 400) -> list[G.Pt3]:
    c = arc["center_mm"]
    r = arc["radius_mm"]
    a0, a1 = arc["start_angle_rad"], arc["end_angle_rad"]
    xa, ya = arc["x_axis"], arc["y_axis"]
    out = []
    for i in range(n + 1):
        t = a0 + (a1 - a0) * (i / n)
        out.append(tuple(c[k] + r * (math.cos(t) * xa[k] + math.sin(t) * ya[k])
                         for k in range(3)))
    return out


@pytest.mark.parametrize("span_deg", [30, 179, 181, 270, 359])
def test_an_arc_hull_contains_the_arc_including_spans_over_pi(span_deg):
    """Arcs greater than π are a separate item of the completion
    criterion. The polyline is built from the sagitta, and the hull
    must cover the original arc in full."""
    arc = {"center_mm": [0.0, 0.0, 0.0], "radius_mm": 3000.0,
           "start_angle_rad": 0.0,
           "end_angle_rad": math.radians(span_deg),
           "x_axis": [1.0, 0.0, 0.0], "y_axis": [0.0, 1.0, 0.0]}
    pts, sag = H.arc_chord_polyline(arc, (3000.0, 0.0, 0.0), (0.0, 0.0, 0.0))
    hull = G.Capsule(tuple(pts), 100.0 + sag)
    for p in _sample_arc(arc):
        assert G.contains_point(hull, p), (span_deg, p, sag)


def test_a_concave_floor_contour_is_widened_not_dropped():
    """A concave contour must become CONVEX: SAT does not apply to a
    concave shape, and expanding outward is lawful under the law of
    conservatism — and must cover the original vertices."""
    concave = [[0, 0], [10000, 0], [10000, 10000], [5000, 4000], [0, 10000]]
    pr = H.hull_from_profile(concave, 0.0, 200.0)
    assert pr is not None
    for x, y in concave:
        assert G.contains_point(pr, (float(x), float(y), 100.0))


def test_a_hull_from_bbox_contains_the_whole_bbox():
    el = {"element_id": "1", "category": "OST_Walls",
          "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [1000, 200, 3000]}
    rec, ref = H.build_hull(el)
    assert ref is None and rec.grade == "coarse"
    for corner in ((0, 0, 0), (1000, 200, 3000), (500, 100, 1500)):
        assert G.contains_point(rec.hull, corner)


def test_a_giant_hull_is_compared_against_everything():
    """A giant that touches more cells than are worth expanding goes
    into a separate list — but does NOT drop out of the comparison
    (otherwise a false miss)."""
    giant = _rec("giant", G.Aabb((-1e6, -1e6, -1e6), (1e6, 1e6, 1e6)), side="struct")
    small = _rec("small", G.Aabb((0, 0, 0), (10, 10, 10)), side="mep")
    recs = [giant, small]
    grid = D.build_grid(recs, cell=1.0)
    assert grid.stats["oversized_hulls"] >= 1
    assert (0, 1) in D.candidate_pairs(recs, grid, pair_filter=D.mvp_pair_filter)


def _rec(sid: str, hull: G.Hull, *, side: str | None = "struct",
         grade: str = "coarse", label: str = "x") -> H.HullRecord:
    return H.HullRecord(source_id=sid, category="OST_Walls", label=label,
                        mvp_side=side, hull=hull, grade=grade,
                        hull_source="bbox")


# ── (в) property of the broad phase: candidates ⊇ exhaustive search ────────

def _random_scene(rnd: random.Random, n: int) -> list[H.HullRecord]:
    recs = []
    for i in range(n):
        kind = rnd.choice(("box", "prism", "capsule"))
        x, y, z = (rnd.uniform(-5000, 5000) for _ in range(3))
        if kind == "box":
            d = [rnd.uniform(10, 4000) for _ in range(3)]
            hull = G.Aabb((x, y, z), (x + d[0], y + d[1], z + d[2]))
        elif kind == "prism":
            k = rnd.randint(3, 6)
            pts = [(x + rnd.uniform(-2000, 2000), y + rnd.uniform(-2000, 2000))
                   for _ in range(k)]
            fp = G.convex_footprint(pts)
            if len(fp) < 3:
                continue
            hull = G.Prism(fp, z, z + rnd.uniform(10, 3000))
        else:
            hull = G.Capsule(((x, y, z),
                              (x + rnd.uniform(-4000, 4000),
                               y + rnd.uniform(-4000, 4000),
                               z + rnd.uniform(-4000, 4000))),
                             rnd.uniform(10, 400))
        recs.append(_rec(f"e{i:04d}", hull,
                         side="mep" if i % 2 else "struct"))
    return recs


@pytest.mark.parametrize("seed", range(8))
def test_broad_phase_is_a_superset_of_brute_force(seed):
    """The key property test of §8.1(в). The grid is allowed to give
    extra candidates (the narrow phase will filter them out), but is
    NOT allowed to lose pairs."""
    rnd = random.Random(seed)
    recs = _random_scene(rnd, 90)
    grid = D.build_grid(recs)
    cand = set(D.candidate_pairs(recs, grid, pair_filter=D.mvp_pair_filter))
    brute = set(D.brute_pairs(recs, pair_filter=D.mvp_pair_filter))
    assert brute <= cand, sorted(brute - cand)[:5]


@pytest.mark.parametrize("cell", [1.0, 37.0, 1000.0, 1e6])
def test_broad_phase_holds_for_any_cell_size(cell):
    """Cell size is a performance parameter, not a correctness one."""
    rnd = random.Random(99)
    recs = _random_scene(rnd, 60)
    grid = D.build_grid(recs, cell=cell)
    cand = set(D.candidate_pairs(recs, grid, pair_filter=D.mvp_pair_filter))
    assert set(D.brute_pairs(recs, pair_filter=D.mvp_pair_filter)) <= cand


def test_broad_phase_survives_an_adversarial_scene():
    """Tilted ones, giants, zero lengths, and eccentric profiles — all
    in one scene, because one at a time they already used to pass."""
    recs = [
        _rec("slant", G.Capsule(((-9000, 0, -9000), (9000, 0, 9000)), 60.0), side="mep"),
        _rec("zero", G.Capsule(((0, 0, 0), (0, 0, 0)), 25.0), side="mep"),
        _rec("giant", G.Aabb((-1e5, -1e5, -1e5), (1e5, 1e5, 1e5))),
        _rec("thin", G.Prism(((0, 0), (12000, 0), (12000, 1), (0, 1)), 0, 3000)),
        _rec("ecc", G.Prism(((5000, 5000), (5040, 5000), (5040, 9000),
                             (5000, 9000)), -2000, 12000)),
        _rec("far", G.Aabb((1e4, 1e4, 1e4), (1e4 + 5, 1e4 + 5, 1e4 + 5)), side="mep"),
    ]
    grid = D.build_grid(recs)
    cand = set(D.candidate_pairs(recs, grid, pair_filter=D.mvp_pair_filter))
    assert set(D.brute_pairs(recs, pair_filter=D.mvp_pair_filter)) <= cand


# ── (б) census: not a single class drops out silently ──────────────────────

def test_the_census_balances_by_construction():
    els = [
        {"element_id": "1", "category": "OST_Walls",
         "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [1, 1, 1]},
        {"element_id": "2", "category": "OST_Grids"},                 # datum
        {"element_id": "3", "category": "OST_Nonsense",
         "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [1, 1, 1]},         # outside the table
        {"element_id": "4", "category": "OST_Walls"},                 # without geometry
    ]
    snap = S.build_from_elements(els, origin={})
    t = snap.census.totals()
    assert snap.census.balanced()
    assert t == {"eligible": 3, "hulled": 1, "unsupported": 1,
                 "missing_geometry": 1, "not_eligible": 1,
                 # Review #10: what never reached the stream at all is
                 # also a number.
                 "outside_extraction_scope": 0, "linked_elements_unscored": 0,
                 # 11.08.2026: links for which the element count COULD
                 # NOT BE READ are a separate number, not a zero in the
                 # sum above. This dictionary is closed on purpose, and
                 # it caught the addition exactly as it should: a new
                 # census field must be a decision.
                 "links_without_element_count": 0}


def test_an_unknown_category_is_named_not_dropped():
    """A class silently dropping out is forbidden by census law §18."""
    snap = S.build_from_elements(
        [{"element_id": "9", "category": "OST_BrandNewThing",
          "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [1, 1, 1]}], origin={})
    assert snap.census.unsupported["OST_BrandNewThing"] == 1
    assert snap.refusals[0].reason == "kind_outside_table"


def test_datums_are_not_eligible_and_do_not_pollute_the_denominator():
    """An axis and a level have no body: counting them as "uncovered"
    would mean keeping the census forever unreconciled, and training
    oneself not to read it."""
    snap = S.build_from_elements(
        [{"element_id": "g", "category": "OST_Grids"},
         {"element_id": "l", "category": "OST_Levels"}], origin={})
    assert snap.census.totals()["eligible"] == 0
    assert snap.census.totals()["not_eligible"] == 2


# ── (а) closed matrix ───────────────────────────────────────────────────────

def test_the_coverage_matrix_is_closed_and_complete():
    rows = H.coverage_matrix()
    assert len(rows) == len(H.KIND_TABLE)
    for row in rows:
        assert row["category"] in H.KIND_TABLE
        if row["eligible"]:
            assert row["hull_sources"], row
        else:
            assert row["refusal"], row


def test_every_mvp_side_is_one_of_the_two_named_sides():
    for cat, rule in H.KIND_TABLE.items():
        assert rule.mvp_side in (None, *H.MVP_PAIR), cat
        if rule.mvp_side is not None:
            assert rule.eligible, f"{cat}: сторона MVP без права на оболочку"


# ── verdicts and grades ─────────────────────────────────────────────────────

def test_a_coarse_pair_is_never_confirmed_and_never_publishes_a_translation():
    """Review #14: intersection of bounding boxes proves neither a clash
    nor the direction of a repair."""
    a = _rec("a", G.Aabb((0, 0, 0), (100, 100, 100)), side="mep")
    b = _rec("b", G.Aabb((50, 50, 50), (150, 150, 150)), side="struct")
    f = D.evaluate(a, b)
    assert f is not None and f.hull_grade == "coarse"
    assert f.verdict == "possible"
    assert f.certified_separating_translation_mm is None


def test_an_exact_outer_word_alone_is_not_a_confirmation():
    """Even an ``exact`` outer grade is not the positive proof channel.

    Confirmation is carried by two independently certified inner subsets;
    changing an outer label by hand must not mint that certificate.
    """
    a = _rec("a", G.Capsule(((0, 0, 0), (1000, 0, 0)), 50.0),
             side="mep", grade="exact", label="pipe")
    b = _rec("b", G.Prism(((400, -500), (600, -500), (600, 500), (400, 500)),
                          -500, 500), side="struct", grade="exact", label="wall")
    f = D.evaluate(a, b)
    assert f is not None and f.verdict == "possible"
    assert f.physical_overlap_proof.status == "not_proven"
    assert f.hull_overlap_depth_mm > 0
    assert f.certified_separating_translation_mm is not None


def test_touching_within_the_grade_tolerance_is_reported_but_not_ranked():
    """REWRITTEN per review #14. The earlier behavior — "a shallow overlap
    within the grade's tolerance is not a finding" — was muting proven
    intersections: three FNs on the live facade came from exactly this,
    and 25mm was never a proven AABB error margin.

    Now the hull relation is always published, and the tolerance lives on
    a separate RANKING axis (`ranking_significant`), which hides nothing.
    """
    a = _rec("a", G.Aabb((0, 0, 0), (100, 100, 100)), side="mep")
    b = _rec("b", G.Aabb((100 - H.TOL_GRADE_MM["coarse"] / 2, 0, 0),
                         (200, 100, 100)), side="struct")
    f = D.evaluate(a, b)
    assert f is not None, "мелкое перекрытие проглочено — это и был ложный пропуск"
    assert f.hull_relation == "overlap"
    assert f.ranking_significant is False


def test_clearance_is_not_applied_twice():
    """Review #13: the total dilation must equal exactly `clearance`."""
    a = _rec("a", G.Aabb((0, 0, 0), (100, 100, 100)), side="mep", grade="exact")
    b = _rec("b", G.Aabb((160, 0, 0), (260, 100, 100)), side="struct", grade="exact")
    assert D.evaluate(a, b, clearance_mm=50.0) is None
    f = D.evaluate(a, b, clearance_mm=80.0)
    assert f is not None and f.clearance_deficit_mm == pytest.approx(20.0)
    assert f.hull_overlap_depth_mm == 0.0
    assert f.hull_relation == "separated"       # clearance violated, but the bodies are apart


def test_the_pair_class_is_an_unordered_key():
    """`wall~mullion` and `mullion~wall` are one class; otherwise one
    report number gets split in half by an arbitrary criterion (whichever
    id comes first)."""
    a = _rec("2", G.Aabb((0, 0, 0), (100, 100, 100)), side="mep",
             label="pipe", grade="exact")
    b = _rec("1", G.Aabb((50, 50, 50), (150, 150, 150)), side="struct",
             label="wall", grade="exact")
    f1 = D.evaluate(a, b)
    f2 = D.evaluate(b, a)
    assert f1.pair_class == f2.pair_class == "pipe~wall"
    assert f1.finding_id == f2.finding_id, "id находки зависит от порядка аргументов"


# ── (д) the canonical golden and determinism ────────────────────────────────

def _tiny_snapshot() -> S.ClashGeometrySnapshot:
    els = [
        {"element_id": "100", "category": "OST_Walls",
         "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [6000, 200, 3000],
         "level_id": "L1", "type_name": "Кирпич 250"},
        {"element_id": "200", "category": "OST_PipeCurves",
         "bbox_min_mm": [2900, -500, 1400], "bbox_max_mm": [3100, 700, 1600],
         "level_id": "L1", "type_name": "Сталь 100"},
        {"element_id": "300", "category": "OST_Grids"},
    ]
    return S.build_from_elements(els, origin={"run_dir": "golden", "l0_sha": "0"})


#: The historical clash-report/1 reference. It lives as the INPUT of a
#: migration test (review #14): the schema cannot be kept byte-for-byte
#: while adding a fact, but we are obliged to be able to read our own
#: measurement history. The current reference is v2 in fixtures/, and
#: only the `kir.clash.tools.make_fixtures` generator writes it
#: (review #17).
# 27.08.2026: the path to the reference went through `kukai/clash` — the
# address of the PREVIOUS layout. After the split it pointed at a place
# that no longer existed, and the test reported «эталон отсутствует,
# перегенерируйте руками» — that is, it blamed the data instead of the
# address.
GOLDEN_V1 = pathlib.Path(__file__).resolve().parent / "golden_report.json"


def test_the_report_is_byte_identical_across_runs():
    a = D.dumps(D.detect(_tiny_snapshot()))
    b = D.dumps(D.detect(_tiny_snapshot()))
    assert a == b


def test_pairs_in_scope_aggregate_equals_brute_force():
    """The aggregate's contract: pair_filter is determined by the
    record's class.

    Acceptance measurement, 28.07: a pairwise counter on the demo tower
    (~50k hulls) = ~1.25e9 filter calls, the detector never lived to see
    an answer. The class-based aggregate must give the SAME number as
    exhaustive search."""
    import random
    rng = random.Random(287)
    cats = ["OST_PipeCurves", "OST_Walls", "OST_Floors", "OST_DuctCurves",
            "OST_CableTray", "OST_StructuralColumns", "OST_Doors"]
    els = []
    for i in range(120):
        c = rng.choice(cats)
        x, y, z = (rng.uniform(0, 30000) for _ in range(3))
        els.append({"element_id": str(1000 + i), "category": c,
                    "bbox_min_mm": [x, y, z],
                    "bbox_max_mm": [x + 400, y + 400, z + 400],
                    "level_id": "L1", "type_name": "t"})
    snap = S.build_from_elements(els, origin={"run_dir": "agg", "l0_sha": "0"})
    recs = snap.records
    for pf in (D.mvp_pair_filter, D.any_physical_pair_filter):
        brute = sum(1 for i in range(len(recs))
                    for j in range(i + 1, len(recs)) if pf(recs[i], recs[j]))
        got = D.detect(snap, pair_filter=pf)["search"]["pairs_in_scope"]
        assert got == brute, (pf.__name__, got, brute)


def test_pairs_in_scope_refuses_a_filter_the_aggregate_cannot_count():
    """A filter that is NOT class-based → `pairs_in_scope` must be None
    with a reason.

    Found by a live measurement on 14.08.2026 on a federated model: the
    `/api/viewer/federation/clash` route returned `pairs_in_scope: 0`
    alongside 58,280 findings and 59,937 pairs considered. The aggregate
    asks the filter about a class REPRESENTATIVE `(label, mvp_side)`, and
    `cross_model_pair_filter` decides based on the model name in
    `source_id` — both representatives come from the same decompile, and
    "different models?" answers "no" for every class at once.

    A zero born from a violated precondition is indistinguishable from an
    honest zero. Fail control for this test: bring back the old branch
    without the `_CLASS_DETERMINED_FILTERS` check — then `got` becomes 0
    again and the test turns red.
    """
    els = []
    for i in range(6):
        els.append({"element_id": str(2000 + i), "category": "OST_Walls",
                    "bbox_min_mm": [i * 100.0, 0.0, 0.0],
                    "bbox_max_mm": [i * 100.0 + 400, 400.0, 400.0],
                    "level_id": "L1", "type_name": "t"})
    snap = S.build_from_elements(els, origin={"run_dir": "cross", "l0_sha": "0"})
    # Model names — as the federation assigns them: `<decompile>::<element
    # number>`.
    import dataclasses
    recs = [dataclasses.replace(r, source_id=f"m{i % 2}::{r.source_id}")
            for i, r in enumerate(snap.records)]
    snap = S.ClashGeometrySnapshot(records=recs, census=snap.census,
                                   origin=snap.origin, refusals=snap.refusals)

    rep = D.detect(snap, pair_filter=D.cross_model_pair_filter)
    got = rep["search"]["pairs_in_scope"]
    assert got is None, (
        "агрегат посчитал число для фильтра, чьё предусловие он нарушает: "
        f"{got!r}")
    reason = [n for n in rep["notes"] if "cross_model_pair_filter" in n]
    assert reason, "число не посчитано, а причина не названа — это молчание"

    # AND YET THE SEARCH RUNS: the refusal concerns ONLY the coverage
    # counter. Otherwise an "honest None" would turn into a disabled
    # detector.
    assert rep["search"]["candidate_pairs"] > 0
    assert all(f["a"]["source_element_id"].split("::")[0]
               != f["b"]["source_element_id"].split("::")[0]
               for f in rep["findings"])


def test_pairs_in_scope_still_counts_for_the_canonical_filters():
    """PASS control for the test above: class-based filters are counted
    the way they used to be counted."""
    els = [{"element_id": str(3000 + i), "category": "OST_Walls",
            "bbox_min_mm": [i * 100.0, 0.0, 0.0],
            "bbox_max_mm": [i * 100.0 + 400, 400.0, 400.0],
            "level_id": "L1", "type_name": "t"} for i in range(5)]
    snap = S.build_from_elements(els, origin={"run_dir": "ok", "l0_sha": "0"})
    rep = D.detect(snap, pair_filter=D.any_physical_pair_filter)
    assert rep["search"]["pairs_in_scope"] == 5 * 4 // 2
    assert not [n for n in rep["notes"] if "агрегат по классам неприменим" in n]


def test_the_canon_contains_no_wall_clock():
    """The canon is a function of the input. Acceptance, 28.07: the
    agent's golden carried timings (0.1ms), the lead's run gave 0.0 —
    byte-for-byte broke by construction itself. Telemetry lives in
    underscore-prefixed keys and is not serialized into the canon."""
    rep = D.detect(_tiny_snapshot())
    assert "_timings_ms" in rep            # telemetry is not lost
    canon = json.loads(D.dumps(rep))
    assert not any(k.startswith("_") for k in canon)
    assert "ms" not in canon["search"]


def test_the_canonical_golden_does_not_move():
    """The golden is not decoration: without it, any change to the
    formula goes through silently.

    Review #17: a missing reference is an ERROR, not a reason to write
    it. A test that creates the very thing it checks against is green no
    matter what breaks. Recording lives in a separate generator,
    `kir.clash.tools.make_fixtures`, and the scene covers every kind of
    pair and relation, not just one crude AABB.
    """
    from kir.clash.tools.make_fixtures import golden_scene

    golden = (pathlib.Path(__file__).resolve().parent / "fixtures"
              / "golden_report_v2.json")
    assert golden.exists(), (
        "эталон отсутствует — перегенерировать руками: "
        "PYTHONPATH=. venv/bin/python -m kir.clash.tools.make_fixtures")
    got = D.dumps(D.detect(golden_scene()))
    assert got == golden.read_text(encoding="utf-8").strip()


def test_the_serialization_refuses_nan_and_normalizes_zero():
    rep = D.detect(_tiny_snapshot())
    text = D.dumps(rep)
    assert "NaN" not in text and "-0.0" not in text
    assert json.loads(text)["schema_version"] == D.REPORT_SCHEMA


# ── (ж) binding to provenance ───────────────────────────────────────────────

def test_the_report_carries_the_fingerprint_of_what_it_judged():
    """A report without the source's SHA can be neither reproduced nor
    refuted."""
    snap = _tiny_snapshot()
    snap.origin["revision"] = {"fingerprint": "31587:dd:96"}
    rep = D.detect(snap)
    assert rep["origin"]["l0_sha"] == "0"
    assert rep["origin"]["revision"]["fingerprint"] == "31587:dd:96"
    assert rep["census"]["balanced"] is True


# ── (е) grid bench and a real facade ────────────────────────────────────────

@pytest.mark.skipif(not FACADE.exists(), reason="нет артефактов декомпайла")
def test_the_real_facade_balances_and_the_grid_pays_for_itself():
    snap = S.build_from_decompile(FACADE)
    assert snap.census.balanced()
    assert snap.census.totals()["hulled"] > 2000
    rep = D.detect(snap, pair_filter=D.any_physical_pair_filter)
    s = rep["search"]
    assert s["candidate_pairs"] < s["pairs_in_scope"] / 50, s
    assert s["grid"]["max_bucket"] < 500
    # The detector must PROVE that it searched: on the real facade it
    # found something.
    assert rep["findings"], "ноль находок на 2754 оболочках — поиск не шёл"


@pytest.mark.skipif(not FACADE.exists(), reason="нет артефактов декомпайла")
def test_the_facade_has_no_mvp_pairs_and_says_so_instead_of_pretending():
    """The facade model contains not a single MEP category — meaning MVP
    pairs in it number zero. This is a fact about the data, and the
    report must show it with counters, not with an empty list of findings
    and no explanation."""
    snap = S.build_from_decompile(FACADE)
    assert not [r for r in snap.records if r.mvp_side == "mep"]
    rep = D.detect(snap)
    assert rep["search"]["pairs_in_scope"] == 0
    assert rep["search"]["scope_id"] == "mvp_v2"
    assert rep["findings"] == []
    assert rep["census"]["totals"]["hulled"] > 2000


@pytest.mark.skipif(not FACADE.exists(), reason="нет артефактов декомпайла")
def test_the_facade_publishes_the_gap_between_the_model_and_the_stream():
    """Review #10, a live measurement: header census = 30,489 elements,
    while element rows in the stream number 3,153. The difference of
    27,336 is NOT required to be searchable — but it must be printed as a
    number, otherwise the denominator of any coverage percentage is
    unproven. The shape of the census (a list of {key,count} inside
    document) is measured off this very artifact, not assumed."""
    snap = S.build_from_decompile(FACADE)
    assert snap.origin["header_census_total"] == 30489
    assert snap.origin["elements_in_l0"] == 3153
    assert snap.census.outside_extraction_scope == 27336
    # THE NUMBER OF LINKS AND THE NUMBER OF THEIR ELEMENTS ARE DIFFERENT
    # QUANTITIES, AND ON THIS BUILDING THEY DIVERGE BY A FACTOR OF 65,000
    # (measured 11.08.2026 on this very artifact). There used to be
    # `linked_elements_unscored == 8` here, and the equality held not
    # because that's how it came out on the facade, but because a field
    # named ELEMENTS was receiving the number of LINK RECORDS. One link
    # of the facade (`SOB6.2_STR_ALL_DOO_KR_R23.rvt`) carries 466,184
    # elements.
    assert snap.origin["links_in_l0"] == 8
    assert snap.origin["linked_elements_in_l0"] == 524_865
    assert snap.census.linked_elements_unscored == 524_865
    # AND 524,865 IS A LOWER BOUND, not a total: six links out of eight
    # are unloaded, `GetLinkDocument()` is empty for them, they have NO
    # element count. Without a separate counter, those six would have
    # silently entered the sum as zeros, and the lower bound would have
    # read as an exact number — the same substitution, only quieter.
    # Across the corpus this is not a rarity but the rule: 316 links out
    # of 386.
    assert snap.census.links_without_element_count == 6
    assert (snap.census.links_without_element_count
            == snap.origin["links_without_element_count"])
    assert snap.census.links_without_element_count <= snap.origin["links_in_l0"]
    j = snap.join_manifest()
    assert j["eligible"] == j["scored"] + j["not_scored"]
    assert j["l1_join"] == "absent"
