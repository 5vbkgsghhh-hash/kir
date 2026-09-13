"""Wave D2-A: cross-sections from L0's `params` -> a hull more precise
than a bounding box.

The same discipline as in hardening: every fix is first reproduced by a
test that is RED against the old code, and only then repaired. Here
that is the `axis_section` branch: it had existed since D1, but was
waiting on a `section_radius_mm` field that no element in the decompile
artifacts has — the numbers live in the `params` of an L0 record under
BuiltInParameter names (commit d154196e).

The file's second subject is the CONSERVATISM LAW on cross-sections. It
is not declared, it is measured: the element's body is sampled densely,
and EVERY point of it must lie inside the hull. For a rectangular
cross-section, the sampling runs over ALL roll angles, because the
rotation of the cross-section around the axis is not captured in L0 —
which is exactly why the half-diagonal is taken as the radius, not the
half-width.

FIX 29.07 (red team's R3). The first edition of this file was building
capsules from `RBS_PIPE_DIAMETER_PARAM` / `RBS_CONDUIT_DIAMETER_PARAM`.
Both are NOMINAL values («Diameter», «Diameter(Trade Size)» per
RevitAPI.xml), and a capsule built from a nominal value does not
contain the body: for DN100 that's radius 50.0 against an outer
diameter of 57.15. The tests have been switched to the outer
parameters, and the law "a nominal value doesn't build a hull" lives on
as counterexamples in `test_clash_redteam.py`.

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

#: A live decompile from the prod box. Tests that need it are marked
#: skipif — the rest must be green on a clean checkout (hardening law
#: #18).
LIVE_V13 = (pathlib.Path(__file__).resolve().parents[3]
            / "backend" / "data" / "decompile" / "sob62_fas_r23_v13")


def _frame(d: G.Pt3, roll: float) -> tuple[G.Pt3, G.Pt3]:
    """A pair of unit normals to direction `d`, rotated by `roll`."""
    u0 = G._any_perpendicular(d)
    L = G._len(d)
    w = tuple(c / L for c in d)
    v0 = (w[1] * u0[2] - w[2] * u0[1],
          w[2] * u0[0] - w[0] * u0[2],
          w[0] * u0[1] - w[1] * u0[0])
    ca, sa = math.cos(roll), math.sin(roll)
    u = tuple(u0[i] * ca + v0[i] * sa for i in range(3))
    v = tuple(-u0[i] * sa + v0[i] * ca for i in range(3))
    return u, v


# ── A1: the axis_section branch is dead while the cross-section sits in params ─

def test_sections_pipe_reads_its_diameter_from_l0_params():
    """The wave's refuting test: an element in exactly the shape the
    decompile writes it — the cross-section number in `params`, not in
    a `section_radius_mm` field.

    On D1's code, the `axis_section` branch looked ONLY at
    `el["section_radius_mm"]`, which no element in L0 has, so a pipe
    with a known diameter was getting a bounding box: grade coarse, a
    25mm ranking tolerance, a verdict no higher than `possible`, and
    the separating translation not published at all.
    """
    el = {"element_id": "p1", "category": "OST_PipeCurves",
          "p0_mm": [0, 0, 0], "p1_mm": [4000, 0, 0],
          "params": {"RBS_PIPE_OUTER_DIAMETER": 100.0},
          "bbox_min_mm": [-50, -50, -50], "bbox_max_mm": [4050, 50, 50],
          "type_name": "Сталь 100"}
    rec, ref = H.build_hull(el)
    assert rec is not None, ref
    assert rec.hull_source == "axis_section", "диаметр из params не прочитан"
    assert isinstance(rec.hull, G.Capsule)
    assert rec.hull.radius == pytest.approx(50.0)
    assert rec.section_round is True
    assert rec.section_radius_mm == pytest.approx(50.0)


@pytest.mark.parametrize("category,params,expected_r,is_round", [
    ("OST_PipeCurves", {"RBS_PIPE_OUTER_DIAMETER": 219.0}, 109.5, True),
    ("OST_DuctCurves", {"RBS_CURVE_DIAMETER_PARAM": 400.0}, 200.0, True),
    ("OST_DuctCurves", {"RBS_CURVE_WIDTH_PARAM": 600.0,
                        "RBS_CURVE_HEIGHT_PARAM": 300.0},
     math.hypot(600.0, 300.0) / 2, False),
    ("OST_CableTray", {"RBS_CABLETRAY_WIDTH_PARAM": 200.0,
                       "RBS_CABLETRAY_HEIGHT_PARAM": 100.0},
     math.hypot(200.0, 100.0) / 2, False),
    ("OST_Conduit", {"RBS_CONDUIT_OUTER_DIAM_PARAM": 50.0}, 25.0, True),
])
def test_sections_every_mep_class_reads_its_own_parameter(
        category, params, expected_r, is_round):
    """The rule is a property of the CATEGORY, just like `sources`
    (review #12): a pipe reads a pipe's diameter, a tray reads a
    tray's bounding box. "Any number that looks like a cross-section"
    is exactly the self-consistent, empty list of sources."""
    el = {"element_id": "e", "category": category,
          "p0_mm": [0, 0, 0], "p1_mm": [3000, 0, 0], "params": params,
          "bbox_min_mm": [-500, -500, -500], "bbox_max_mm": [3500, 500, 500]}
    rec, _ = H.build_hull(el)
    assert rec.hull_source == "axis_section", category
    assert rec.hull.radius == pytest.approx(expected_r)
    assert rec.section_round is is_round


def test_sections_oval_duct_takes_the_larger_radius():
    """For an oval duct, BOTH cross-sections are read. The smaller
    radius might not contain the body, so the larger one is taken —
    coarsening only upward."""
    el = {"element_id": "d", "category": "OST_DuctCurves",
          "p0_mm": [0, 0, 0], "p1_mm": [3000, 0, 0],
          "params": {"RBS_CURVE_DIAMETER_PARAM": 100.0,
                     "RBS_CURVE_WIDTH_PARAM": 600.0,
                     "RBS_CURVE_HEIGHT_PARAM": 300.0},
          "bbox_min_mm": [-500, -500, -500], "bbox_max_mm": [3500, 500, 500]}
    rec, _ = H.build_hull(el)
    assert rec.hull.radius == pytest.approx(math.hypot(600.0, 300.0) / 2)


def test_sections_a_non_positive_number_is_a_named_refusal_not_a_hull():
    """A zero or negative diameter would build a capsule of zero
    radius — that is, a segment instead of a pipe. That is a shrinking
    of the hull, and it is forbidden."""
    for bad in (0.0, -100.0, float("nan")):
        el = {"element_id": "p", "category": "OST_PipeCurves",
              "p0_mm": [0, 0, 0], "p1_mm": [1000, 0, 0],
              "params": {"RBS_PIPE_OUTER_DIAMETER": bad},
              "bbox_min_mm": [-50, -50, -50], "bbox_max_mm": [1050, 50, 50]}
        rec, _ = H.build_hull(el)
        assert rec.hull_source == "bbox", bad
        assert "section_absent" in (rec.extra.get("downgraded_from") or []), bad


# ── A2: the conservatism law on cross-sections, by measurement, not by declaration ─

def test_sections_round_capsule_contains_the_whole_cylinder():
    """The body of a round pipe is a cylinder with FLAT caps around the
    axis. Every point of it must lie inside a capsule of radius d/2."""
    rnd = random.Random(20260729)
    for _ in range(40):
        p0 = tuple(rnd.uniform(-5000, 5000) for _ in range(3))
        d = tuple(rnd.uniform(-1, 1) for _ in range(3))
        if G._len(d) < 1e-3:
            continue
        L = rnd.uniform(100, 8000)
        w = tuple(c / G._len(d) * L for c in d)
        p1 = tuple(p0[i] + w[i] for i in range(3))
        diameter = rnd.uniform(15, 800)
        el = {"element_id": "p", "category": "OST_PipeCurves",
              "p0_mm": list(p0), "p1_mm": list(p1),
              "params": {"RBS_PIPE_OUTER_DIAMETER": diameter},
              "bbox_min_mm": [-1e6, -1e6, -1e6], "bbox_max_mm": [1e6, 1e6, 1e6]}
        rec, _ = H.build_hull(el)
        assert rec.hull_source == "axis_section"
        u, v = _frame(w, 0.0)
        r = diameter / 2
        for t in (0.0, 0.25, 0.5, 0.75, 1.0):
            for k in range(12):
                ang = 2 * math.pi * k / 12
                for rad in (r, r * 0.5, 0.0):
                    pt = tuple(p0[i] + w[i] * t
                               + u[i] * rad * math.cos(ang)
                               + v[i] * rad * math.sin(ang) for i in range(3))
                    assert G.contains_point(rec.hull, pt), (
                        "точка тела трубы вне оболочки")


def test_sections_rectangular_capsule_contains_the_box_at_any_roll():
    """The rotation of a rectangular cross-section around its axis is
    NOT captured in L0. So the hull must contain the box at ANY roll
    angle — and that is exactly a cylinder of radius hypot(w,h)/2.
    Checked by dense sampling of the body, including the corners, where
    the bound is tight: a half-width would no longer hold it."""
    rnd = random.Random(31415926)
    for _ in range(40):
        p0 = tuple(rnd.uniform(-5000, 5000) for _ in range(3))
        d = tuple(rnd.uniform(-1, 1) for _ in range(3))
        if G._len(d) < 1e-3:
            continue
        L = rnd.uniform(100, 8000)
        w = tuple(c / G._len(d) * L for c in d)
        p1 = tuple(p0[i] + w[i] for i in range(3))
        bw, bh = rnd.uniform(50, 1200), rnd.uniform(50, 1200)
        el = {"element_id": "t", "category": "OST_CableTray",
              "p0_mm": list(p0), "p1_mm": list(p1),
              "params": {"RBS_CABLETRAY_WIDTH_PARAM": bw,
                         "RBS_CABLETRAY_HEIGHT_PARAM": bh},
              "bbox_min_mm": [-1e6, -1e6, -1e6], "bbox_max_mm": [1e6, 1e6, 1e6]}
        rec, _ = H.build_hull(el)
        assert rec.hull_source == "axis_section"
        for roll_i in range(8):
            u, v = _frame(w, 2 * math.pi * roll_i / 8)
            for t in (0.0, 0.5, 1.0):
                for a in (-bw / 2, 0.0, bw / 2):
                    for b in (-bh / 2, 0.0, bh / 2):
                        pt = tuple(p0[i] + w[i] * t + u[i] * a + v[i] * b
                                   for i in range(3))
                        assert G.contains_point(rec.hull, pt), (
                            f"угол коробки вне оболочки при крене {roll_i}")


def test_sections_capsule_is_not_exact_the_spherical_cap_proves_it():
    """The codex review's #11, verbatim: a point PAST the pipe's flat
    end, but inside the capsule's hemisphere, lies inside the hull and
    outside the body. So the hull contains the body STRICTLY, so the
    grade is `conservative`, not `exact`.

    This is not nitpicking: an inflated grade would substitute the
    meaning of an OUTER hull, and could be mistakenly taken by a future
    consumer as proof of the body.
    """
    el = {"element_id": "p", "category": "OST_PipeCurves",
          "p0_mm": [0, 0, 0], "p1_mm": [1000, 0, 0],
          "params": {"RBS_PIPE_OUTER_DIAMETER": 200.0},
          "bbox_min_mm": [-100, -100, -100], "bbox_max_mm": [1100, 100, 100]}
    rec, _ = H.build_hull(el)
    assert rec.grade == "conservative"
    beyond_the_flat_end = (1050.0, 0.0, 0.0)     # past the end cap, inside the hemisphere
    assert G.contains_point(rec.hull, beyond_the_flat_end)
    assert D.pair_grade(rec, rec) != "exact"


# ── A3: a wall isn't lifted — a ban, not "there's no data" ─────────────────

def test_sections_wall_with_width_param_still_gets_a_bounding_box():
    """On v13, thickness exists for 992 of 1,189 walls — meaning
    "there's no data" no longer offers protection. What protects is the
    ban: `OST_Walls` has no `axis_section` source, and a number showing
    up changes nothing (review #2)."""
    el = {"element_id": "w", "category": "OST_Walls",
          "p0_mm": [0, 0, 0], "p1_mm": [5000, 0, 0],
          "params": {"WALL_ATTR_WIDTH_PARAM": 200.0},
          "bbox_min_mm": [-100, -100, 0], "bbox_max_mm": [5100, 100, 3000]}
    rec, _ = H.build_hull(el)
    assert rec.hull_source == "bbox" and rec.grade == "coarse"
    assert rec.section_radius_mm is None, "стене сечение не переносится"
    assert G.contains_point(rec.hull, (2500.0, 0.0, 2900.0))


def test_sections_wall_prism_builder_contains_the_wall_body():
    """The wall builder IS WRITTEN (review #10 requires it for future
    capture) and is checked separately from the table: a strip around
    the axis must contain the wall's body in full, including the top —
    which a capsule around the lower axis does not give."""
    pr = H.hull_from_wall_axis((0, 0, 0), (5000, 0, 0), width_mm=200.0,
                               z0=0.0, z1=3000.0)
    assert pr is not None
    for x in (0.0, 2500.0, 5000.0):
        for y in (-100.0, 0.0, 100.0):
            for z in (0.0, 1500.0, 3000.0):
                assert G.contains_point(pr, (x, y, z)), (x, y, z)


def test_sections_wall_prism_builder_honours_the_location_line_offset():
    """A wall does NOT sit on its axis when the location line is a
    face: the body is offset by half the thickness. The builder must
    accept the offset as an explicit number, not guess it from
    `WALL_KEY_REF_PARAM` (the sign depends on an orientation that L0
    doesn't have).
    """
    pr = H.hull_from_wall_axis((0, 0, 0), (5000, 0, 0), width_mm=200.0,
                               z0=0.0, z1=3000.0, offset_mm=100.0)
    assert G.contains_point(pr, (2500.0, 200.0, 1500.0))
    assert not G.contains_point(pr, (2500.0, -100.0, 1500.0))


def test_sections_wall_prism_blockers_name_what_is_missing():
    """Three classes of walls for which a single thickness is
    non-conservative (review #10): slanted/tapered (WALL_CROSS_SECTION),
    stacked/vertically compound (composition by height), sweeps. L0
    captures none of them — and the builder SAYS SO."""
    el = {"element_id": "w", "category": "OST_Walls",
          "params": {"WALL_ATTR_WIDTH_PARAM": 200.0, "WALL_KEY_REF_PARAM": 0}}
    blockers = H.wall_prism_blockers(el)
    assert set(blockers) == set(H.WALL_PRISM_EVIDENCE)


@pytest.mark.xfail(strict=True,
                   reason="blocked-on-ground-sections: WALL_CROSS_SECTION, состав "
                          "CompoundStructure по высоте и список sweeps L0 не "
                          "снимает, поэтому призма по одной толщине не доказана "
                          "консервативной (ревью кодекса №10). Тест обязан "
                          "покраснеть в день захвата — и тогда снимается xfail "
                          "вместе с SOURCES_BBOX у OST_Walls.")
def test_sections_wall_prism_is_blocked_on_cross_section():
    el = {"element_id": "w", "category": "OST_Walls",
          "params": {"WALL_ATTR_WIDTH_PARAM": 200.0}}
    assert H.wall_prism_blockers(el) == ()


# ── C: the cross-section census in the snapshot ─────────────────────────────

def _mep_scene() -> list[dict]:
    return [
        {"element_id": "1", "category": "OST_PipeCurves",
         "p0_mm": [0, 0, 0], "p1_mm": [1000, 0, 0],
         "params": {"RBS_PIPE_OUTER_DIAMETER": 100.0},
         "bbox_min_mm": [-50, -50, -50], "bbox_max_mm": [1050, 50, 50],
         "type_name": "Сталь 100"},
        {"element_id": "2", "category": "OST_PipeCurves",
         "p0_mm": [0, 500, 0], "p1_mm": [1000, 500, 0], "params": {},
         "bbox_min_mm": [-50, 450, -50], "bbox_max_mm": [1050, 550, 50],
         "type_name": "Без сечения"},
        {"element_id": "3", "category": "OST_Walls",
         "params": {"WALL_ATTR_WIDTH_PARAM": 200.0},
         "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [5000, 200, 3000],
         "type_name": "Кирпич 200"},
    ]


def test_census_counts_sections_present_absent_and_hulled():
    """"No cross-sections" must be indistinguishable from "wasn't
    asked" ONLY in one case — when we have proven it with a number. The
    census publishes three counters."""
    snap = S.build_from_elements(_mep_scene(), origin={"run_dir": "t"})
    sec = snap.census.as_dict()["sections"]
    assert sec["totals"] == {"present": 1, "absent": 1, "hulled": 1}
    assert sec["by_category"]["OST_PipeCurves"] == {
        "present": 1, "absent": 1, "hulled": 1, "eligible": 2}
    assert "OST_Walls" not in sec["by_category"], (
        "стене сечение не разрешено — её нет и в знаменателе сечений")


def test_census_lists_the_types_that_have_no_section():
    """The "types without a cross-section" counter (directive C):
    without it, a missing cross-section for a whole type looks the
    same as for one broken element."""
    snap = S.build_from_elements(_mep_scene(), origin={"run_dir": "t"})
    sec = snap.census.as_dict()["sections"]
    assert sec["types_without_section_count"] == 1
    assert sec["types_without_section"] == {"OST_PipeCurves": ["Без сечения"]}


def test_census_section_balance_is_a_gate_not_a_warning():
    """The same law as for the hull census: a discrepancy is an
    exception."""
    snap = S.build_from_elements(_mep_scene(), origin={"run_dir": "t"})
    snap.validate()
    snap.census.section_absent["OST_PipeCurves"] += 5
    with pytest.raises(S.SnapshotIntegrityError):
        snap.validate()


def test_census_names_every_section_bearing_category_even_when_absent():
    """The SOB6.2 facade contains NOT A SINGLE MEP element. An empty
    cross-section block in such a report reads as "wasn't asked" — and
    that is exactly what the census law protects against. So the
    denominator is always printed, zeros included: "0 of 0" and
    "didn't search" must look different."""
    snap = S.build_from_elements(
        [{"element_id": "w", "category": "OST_Walls",
          "params": {"WALL_ATTR_WIDTH_PARAM": 200.0},
          "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [1, 1, 1]}],
        origin={"run_dir": "t"})
    sec = snap.census.as_dict()["sections"]
    assert set(sec["by_category"]) == set(H.SECTION_RULES), (
        "категории, которым сечение разрешено, обязаны стоять в знаменателе "
        "даже с нулём элементов")
    assert sec["by_category"]["OST_PipeCurves"]["eligible"] == 0


def test_census_counts_the_numbers_that_the_table_refuses_to_use():
    """The wave's main number on the facade: the cross-section EXISTS
    (992 of 1,189 walls), and there is NO lift — because of the ban,
    not because there's no data. Without this counter,
    "coarse=everything" is indistinguishable from broken parameter
    reading."""
    snap = S.build_from_elements(
        [{"element_id": "w", "category": "OST_Walls",
          "params": {"WALL_ATTR_WIDTH_PARAM": 200.0},
          "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [1, 1, 1]},
         {"element_id": "w2", "category": "OST_Walls", "params": {},
          "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [1, 1, 1]}],
        origin={"run_dir": "t"})
    sec = snap.census.as_dict()["sections"]
    assert sec["blocked_by_table"] == {"OST_Walls": 1}
    assert sec["blocked_total"] == 1


def test_every_clash_section_parameter_is_emitted():
    """Every clash-relevant reading must have a probe in L0.

    The converse is deliberately false: the shared L0 also captures
    levels, offsets, and stairs for reverse/graph. Equality of the two
    lists was a false guard, and it turned red on a lawful extension of
    the emitter, not on lost clash data.
    """
    from kir.decompile.extract import SECTION_PARAM_NAMES
    needed = set(H.ALL_SECTION_PARAM_NAMES + H.SECTION_ENUM_PARAM_NAMES)
    emitted = set(SECTION_PARAM_NAMES)
    assert needed <= emitted, (
        "clash читает параметры, которых L0 не снимает: "
        f"{sorted(needed - emitted)}")
    assert not (set(H.ALL_SECTION_PARAM_NAMES) & set(H.SECTION_ENUM_PARAM_NAMES))


def test_markdown_says_out_loud_that_no_section_was_lifted():
    """The report must SAY "no cross-sections were lifted, and here's
    why," not show it as a zero in the grade table."""
    snap = S.build_from_elements(
        [{"element_id": "w", "category": "OST_Walls",
          "params": {"WALL_ATTR_WIDTH_PARAM": 200.0},
          "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [1, 1, 1]}],
        origin={"run_dir": "t"})
    md = D.to_markdown(D.detect(snap, pair_filter=D.any_physical_pair_filter))
    assert "## Сечения" in md
    assert "запрещён таблицей" in md


def test_a_finding_names_the_parameter_its_hull_stands_on():
    """`hull_source: axis_section` says "hull from an axis and a
    cross-section," but not WHERE the number was taken from. This
    matters for a finding: a pipe's diameter and a tray's half-diagonal
    are different justifications for the same capsule."""
    els = [
        {"element_id": "1", "category": "OST_PipeCurves",
         "p0_mm": [0, 0, 0], "p1_mm": [1000, 0, 0],
         "params": {"RBS_PIPE_OUTER_DIAMETER": 200.0},
         "bbox_min_mm": [-100, -100, -100], "bbox_max_mm": [1100, 100, 100]},
        {"element_id": "2", "category": "OST_Walls",
         "bbox_min_mm": [400, -200, -200], "bbox_max_mm": [600, 200, 200]},
    ]
    rep = D.detect(S.build_from_elements(els, origin={"run_dir": "t"}))
    assert rep["findings"], "труба сквозь стену не найдена"
    sides = [rep["findings"][0]["a"], rep["findings"][0]["b"]]
    pipe = [s for s in sides if s["label"] == "pipe"][0]
    assert pipe["section_source"] == "RBS_PIPE_OUTER_DIAMETER"
    assert pipe["section_radius_mm"] == 100.0
    wall = [s for s in sides if s["label"] == "wall"][0]
    assert wall["section_source"] is None


def test_detect_publishes_the_section_census():
    """The report must NAME the absence of cross-sections, not show it
    as a zero in `by_grade`: "coarse=everything" without a reason is
    indistinguishable from broken reading."""
    snap = S.build_from_elements(_mep_scene(), origin={"run_dir": "t"})
    rep = D.detect(snap, pair_filter=D.any_physical_pair_filter)
    assert rep["census"]["sections"]["totals"]["absent"] == 1


# ── E: the live v13 (an artifact from the prod box) ─────────────────────────

@pytest.mark.skipif(not LIVE_V13.exists(),
                    reason="живой декомпайл только на прод-боксе")
def test_live_v13_walls_carry_width_and_still_stay_coarse():
    """By the numbers: on v13, thickness was captured for 992 of 1,189
    walls — and NOT A SINGLE hull was lifted by it, because the source
    is banned for a wall. This is exactly an honest zero lifts: the
    data EXISTS, there is NO lift, and the reason is named."""
    with_width = total = 0
    for line in (LIVE_V13 / "L0.jsonl").open(encoding="utf-8"):
        line = line.strip()
        if not line or '"OST_Walls"' not in line:
            continue
        row = json.loads(line)
        if row.get("record") != "element":
            continue
        el = row["element"]
        if el.get("category") != "OST_Walls":
            continue
        total += 1
        if "WALL_ATTR_WIDTH_PARAM" in (el.get("params") or {}):
            with_width += 1
        rec, _ = H.build_hull(el)
        assert rec is None or rec.hull_source == "bbox"
    assert (total, with_width) == (1189, 992)
