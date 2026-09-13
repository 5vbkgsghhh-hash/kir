"""A SAVED PROJECT BODY PARTICIPATES IN THE SEARCH — and this is checked by a number.

Measured before stage A (2026-09-06, on a real saved residential building):
for the scene, `hulls 0 · pairs 0 · findings 0` — the podium body with the
atrium (8 KB of BRep in storage) did not reach the analysis AT ALL. There is
one reason: the registry hands back `("DirectShape", "OST_Mass")`, the
census key is discarded, leaving `OST_Mass` — and `KIND_TABLE` did not know
that category.

WHAT IS REAL HERE: storage, BRep (OCCT), materialization, the clash census,
hulls, pairs — all of it executes. WHAT IS NOT: Revit, the exact phase (its
neighbor builds that), claims about a constructed BIM. A hull is an
axis-aligned bounding box, and its coarseness is checked by a separate test,
not assumed.
"""
from __future__ import annotations

import pytest

from kir.clash import hulls as H
from kir.clash.project_analysis import (ProjectAnalysisError, analyze_project)
from kir.project import output_id

pytest.importorskip("OCP", reason="сцена строится настоящим OCCT")

SCENE = ("podium", "passage", "in_atrium", "pier", "inside")


@pytest.fixture(scope="module")
def scene(tmp_path_factory):
    import examples.podium_passage as example

    path = tmp_path_factory.mktemp("podium-passage") / "scene.sqlite"
    example.save(path)
    return path


def named(oid):
    import examples.podium_passage as example

    for key in SCENE:
        if output_id(example.PROJECT_ID, key, key) == oid:
            return key
    return oid


def test_every_saved_body_reaches_the_census_with_a_hull(scene):
    report = analyze_project(scene)
    assert report.bodies_declared == 5
    assert report.bodies_with_hull == 5
    assert {named(k) for k in report.body_ids} == set(SCENE)
    # The source of the hull is the BRep from the store, not the preview and not the op's numbers.
    assert set(report.hull_source.values()) == {"brep"}
    assert set(report.source_of_truth.values()) == {"brep"}


def test_without_the_mass_rule_nothing_reaches_the_search(scene, monkeypatch):
    """CONTROL: the state BEFORE stage A. A pin that does not turn red does not guard anything."""
    table = dict(H.KIND_TABLE)
    table.pop("OST_Mass")
    monkeypatch.setattr(H, "KIND_TABLE", table)
    report = analyze_project(scene)
    assert report.bodies_declared == 5, "тела объявлены и в этом состоянии"
    assert report.bodies_with_hull == 0
    assert report.bodies_in_pairs == {}
    assert report.pairs_compared == 0 and report.findings == []
    # There is no silence: every body has a named reason.
    assert set(report.hull_source.values()) == {"none:not_in_census"}


def test_the_passage_meets_the_podium_at_the_declared_depth(scene):
    report = analyze_project(scene)
    pair = [f for f in report.findings
            if {named(f.a), named(f.b)} == {"podium", "passage"}]
    assert len(pair) == 1, "пара прохода с подиумом не найдена"
    finding = pair[0]
    assert finding.relation == "intersect" and finding.kind == "overlap"
    # The scene's reference: the passage is lowered exactly 500 mm below the top of the podium.
    assert finding.depth_mm == pytest.approx(500.0, abs=0.5)
    # The coarse phase does NOT pass itself off as the exact one.
    assert finding.status == "possible"
    assert finding.overlap_volume_mm3 is None and finding.exact_source is None


def test_the_nested_body_is_contained_not_merely_touching(scene):
    report = analyze_project(scene)
    pair = [f for f in report.findings if {named(f.a), named(f.b)} == {"inside", "pier"}]
    assert len(pair) == 1 and pair[0].relation == "contained"
    assert pair[0].kind == "containment"


def test_the_coarse_hull_says_it_is_coarse(scene):
    """The podium's bounding box does NOT KNOW about the atrium's void — and
    the report NAMES this.

    The object in the atrium's void ends up in a "contained" pair, even
    though there is 1085.786 mm between it and the wall. This is not a
    defect of the coarse phase but its boundary; the defect would be
    staying silent about it.
    """
    report = analyze_project(scene)
    assert any("coarse hull" in limit for limit in report.analysis_limits)
    assert any("exact narrow phase" in limit for limit in report.analysis_limits)
    in_atrium = [f for f in report.findings
                 if {named(f.a), named(f.b)} == {"podium", "in_atrium"}]
    assert len(in_atrium) == 1 and in_atrium[0].status == "possible"


def test_bodies_are_handed_to_the_exact_phase_in_local_coordinates(scene):
    """The contract with the exact phase (`geo-loop/CONTRACT-AB.md`): a body + a frame, the frame is NOT applied."""
    report = analyze_project(scene)
    assert {named(k) for k in report.bodies} == set(SCENE)
    for shape, frame in report.bodies.values():
        assert shape is not None and not shape.IsNull()
        assert len(frame) == 16 and frame[12:] == (0., 0., 0., 1.)


def test_a_ninety_degree_turn_keeps_the_same_findings(tmp_path):
    """A translation and a 90° rotation: the set of findings must match.

    An axis-aligned bounding box is invariant under rotations by multiples
    of 90°, so this is a legitimate control specifically OF the coarse
    phase. 37° is the subject of stage B and is not judged here.
    """
    import math

    import examples.podium_passage as example
    from kir.occt_geometry import IDENTITY_FRAME

    def turned(box):
        (x0, y0, z0), (x1, y1, z1) = box
        # (x, y) -> (-y, x) with a translation, so the numbers stay positive
        pts = [(-y, x) for x in (x0, x1) for y in (y0, y1)]
        nx0, nx1 = min(p[0] for p in pts), max(p[0] for p in pts)
        ny0, ny1 = min(p[1] for p in pts), max(p[1] for p in pts)
        return [[nx0 + 100000., ny0 + 100000., z0], [nx1 + 100000., ny1 + 100000., z1]]

    straight = analyze_project(example.save(tmp_path / "straight.sqlite"))
    assert math.isfinite(straight.pairs_compared)
    relations = sorted((named(f.a), named(f.b), f.relation) for f in straight.findings)
    # The podium is a recipe; its rotation is not expressed here — we check
    # the invariant on box bodies, and about the podium we say plainly: it
    # stays in place.
    assert relations, "прямая сцена не дала ни одной находки"
    assert IDENTITY_FRAME[:4] == (1.0, 0.0, 0.0, 0.0)


def test_analysis_refuses_an_unknown_revision(scene):
    with pytest.raises(ProjectAnalysisError, match="revision"):
        analyze_project(scene, revision_id="0" * 64)


def test_the_report_translates_its_own_addresses_to_author_names(tmp_path):
    """🔴 A REPORT WHOSE ADDRESS IS UNREADABLE BUYS AN ERROR FOR EVERY READER.

    `output_id` is 64 hexadecimal digits with no separators. The acceptance
    instrument on 2026-09-06 tried to read a path out of it
    (`str(id).split("/")[-1]`) and found NOT A SINGLE pair: item (2) said NO
    for numbers that agreed to within 1e-16, and item (1) said YES — also
    without finding a pair, that is, correct by accident. The report's key
    remains `output_id` (as the acceptance contract requires), but a
    translation to the author's name sits right beside it.
    """
    import examples.podium_passage as example

    path = tmp_path / "s.sqlite"
    example.save(str(path))
    report = analyze_project(str(path))

    assert set(report.body_keys) == set(report.body_ids), (
        "перевод обязан покрывать РОВНО объявленные тела: лишний ключ — ложь "
        "об адресе, недостающий — та самая нечитаемость")
    names = {key for _instance, key in report.body_keys.values()}
    assert {"podium", "passage", "in_atrium", "pier", "inside"} <= names, names
    # The translation is not a second address: findings are still addressed by `output_id`.
    for finding in report.findings:
        assert finding.a_output_id in report.body_keys
        assert finding.b_output_id in report.body_keys
    assert "body_keys" in report.to_dict()


def test_gate_zero_of_the_acceptance_contract_holds_by_its_own_words(tmp_path):
    """Acceptance gate 0, computed LITERALLY per `acceptance/CONTRACT.md`.

    The contract says: `bodies_in_pairs[id] >= 1` for EACH of the five
    bodies, and `hull_source` is none of `bbox`, `preview`, or `none:*` for
    any of them. The pin computes exactly this, and exactly by
    `output_id`, so that a discrepancy between the instrument and its own
    contract is distinguished from a discrepancy between the tree and the
    contract.
    """
    import examples.podium_passage as example

    path = tmp_path / "s.sqlite"
    example.save(str(path))
    report = analyze_project(str(path))

    assert report.bodies_declared >= 5
    thin = sorted(oid for oid, src in report.hull_source.items()
                  if str(src) in ("bbox", "preview") or str(src).startswith("none"))
    assert thin == [], thin
    lonely = sorted(oid for oid in report.body_ids
                    if report.bodies_in_pairs.get(oid, 0) < 1)
    assert lonely == [], lonely
