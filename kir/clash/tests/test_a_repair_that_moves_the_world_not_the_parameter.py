# -*- coding: utf-8 -*-
"""THE FIX IS COMPUTED IN WORLD COORDINATES AND ANSWERS FOR ITS
NEIGHBORS.

Three owner findings from 07.09.2026, each with its own number:

(2) `hull_bounds` — bounding box IN PROJECT COORDINATES, while the box
    in `instance.parameters` is in the body's LOCAL coordinates. Before
    this wave, the lift was added to the parameter DIRECTLY, and with a
    frame rotated 37° around a horizontal axis, the world-space shift
    came out as `R·(0,0,lift)` — shorter than needed. RED measurement
    (`.work/…/impl3/red-geometry.json`): a lift of 12485.618 was
    accepted, and the podium×passage pair REMAINED with a depth of
    2464.160.
    🔴 A control here is MANDATORY: the same probe, under a rotation
    around Z, does NOT see the defect — the local z axis coincides with
    the world one. That is exactly why the acceptance's "37° control"
    was green: it only spun the scene around z
    (`fixture.frame_translate_rotz`).

(2b) The recompute callback wasn't given the frame and built the body
    with the IDENTITY: the fix silently UNROTATED the rotated body (the
    same pair, after the "repair," remained, but now with a depth of
    760.792 — the body had also drifted by the frame).

(3) "The pair disappeared" ≠ "things got no worse." RED: lifting the
    passage by 550mm moved it out from under the podium and INTO the
    canopy above — the old pair disappeared, a new one appeared,
    `apply_fix` printed success.

(4) Pairs go through the existing broad phase
    (`kir.clash.spatial_index`), and the report prints
    `bodies_with_geometry` — an output without geometry does not count
    as a participant.
"""
from __future__ import annotations

import math

import pytest

pytest.importorskip("OCP", reason="сцена строится настоящим OCCT")

from kir.clash.project_analysis import (analyze_project,          # noqa: E402
                                        reanalyze_after_fix)
from kir.project import output_id                                 # noqa: E402
from kir.project_fix import (FixError, apply_fix,                 # noqa: E402
                             new_conflicts, propose_fix)


def _frame(axis: str, degrees: float, translate=(12345., -6789., 4321.)):
    angle = math.radians(degrees)
    c, s = math.cos(angle), math.sin(angle)
    rows = {"x": ((1., 0., 0.), (0., c, -s), (0., s, c)),
            "y": ((c, 0., s), (0., 1., 0.), (-s, 0., c)),
            "z": ((c, -s, 0.), (s, c, 0.), (0., 0., 1.))}[axis]
    return tuple(value for index, row in enumerate(rows)
                 for value in (*row, translate[index])) + (0., 0., 0., 1.)


def _rebuild_with_frame(example, frame):
    """A callback that PRESERVES the frame: separates finding (2) from
    finding (2b)."""
    def rebuild(output_key, box, parameters, frame=frame):
        return example.rebuild_body(output_key, box, parameters,
                                    instance_key=output_key, frame=frame)
    return rebuild


def _plain_rebuild(example):
    def rebuild(output_key, box, parameters, frame=None):
        return example.rebuild_body(output_key, box, parameters,
                                    instance_key=output_key, frame=frame)
    return rebuild


def _pair(report, a, b):
    for finding in report.findings:
        if {finding.a_output_id, finding.b_output_id} == {a, b}:
            return finding
    return None


def _ids(example):
    return (output_id(example.PROJECT_ID, "podium", "podium"),
            output_id(example.PROJECT_ID, "passage", "passage"))


@pytest.mark.parametrize("axis,defect_visible", [("x", True), ("z", False)])
def test_the_lift_lands_in_world_coordinates_under_a_rotated_frame(
        tmp_path, axis, defect_visible):
    import examples.podium_passage as example

    frame = _frame(axis, 37.0)
    scene = tmp_path / f"rot-{axis}.sqlite"
    example.save(scene, frame=frame)
    podium, passage = _ids(example)
    before = analyze_project(scene)
    hit = _pair(before, podium, passage)
    assert hit is not None, "пара подиум×проход не найдена — сцена не та"

    proposal, bundle = propose_fix(scene, before, hit.finding_id, move=passage,
                                   rebuild=_rebuild_with_frame(example, frame))
    world = proposal.world_lift_mm
    local = proposal.local_delta_mm
    axis_lift = (abs(local[0]) <= 1e-6 and abs(local[1]) <= 1e-6
                 and abs(local[2] - world) <= 1e-6)
    # The control is not "just in case": it PROVES that the probe tells
    # cases apart. Under a rotation around z, the increment must
    # COINCIDE with the world lift.
    assert axis_lift is not defect_visible, (
        f"поворот вокруг {axis}: мировой подъём {world}, локальная прибавка {local}")
    # The translation is rigid: the increment's length equals the lift
    # under any rotation.
    assert math.dist(local, (0., 0., 0.)) == pytest.approx(abs(world), rel=1e-9)

    head = apply_fix(scene, proposal, assets=[bundle])
    after = reanalyze_after_fix(scene, head)
    assert _pair(after, podium, passage) is None, (
        "после исправления пара осталась: подъём ушёл не в ту сторону")
    assert new_conflicts(before, after, ignore=((podium, passage),)) == []


def test_a_rebuild_that_drops_the_frame_is_refused_by_name(tmp_path):
    """A callback without a frame would rearrange the coordinate system,
    not the body."""
    import examples.podium_passage as example

    scene = tmp_path / "rot-drop.sqlite"
    example.save(scene, frame=_frame("x", 37.0))
    podium, passage = _ids(example)
    report = analyze_project(scene)
    hit = _pair(report, podium, passage)

    def rebuild_without_frame(output_key, box, parameters):
        return example.rebuild_body(output_key, box, parameters, instance_key=output_key)

    with pytest.raises(FixError, match="сменил фрейм"):
        propose_fix(scene, report, hit.finding_id, move=passage,
                    rebuild=rebuild_without_frame)


def test_a_fix_that_creates_a_new_conflict_is_refused_before_it_is_written(tmp_path):
    """The canopy above the passage: the lift pulls one pair apart and
    creates another."""
    import examples.podium_passage as example

    (px0, py0, _pz0), (px1, py1, pz1) = example.PASSAGE
    canopy = ((px0 - 500., py0 - 500., pz1 + 200.), (px1 + 500., py1 + 500., pz1 + 900.))
    scene = tmp_path / "canopy.sqlite"
    example.save(scene, extra=(("canopy", canopy),))
    podium, passage = _ids(example)
    canopy_id = output_id(example.PROJECT_ID, "canopy", "canopy")

    before = analyze_project(scene)
    hit = _pair(before, podium, passage)
    assert _pair(before, passage, canopy_id) is None, "навес уже задевает проход"
    proposal, bundle = propose_fix(scene, before, hit.finding_id, move=passage,
                                   rebuild=_plain_rebuild(example))
    with pytest.raises(FixError, match="fix_creates_new_conflict") as raised:
        apply_fix(scene, proposal, assets=[bundle])
    assert canopy_id[:12] in str(raised.value), str(raised.value)
    # THE MAIN POINT: nothing is recorded into history. A refusal after
    # recording would leave a revision that it itself just called
    # invalid, and the "rollback" would have to be staged as yet another
    # commit.
    again = analyze_project(scene)
    assert again.revision == before.revision
    assert _pair(again, podium, passage) is not None


def test_a_fix_that_does_not_separate_the_pair_is_refused_by_name(tmp_path):
    """An explicit `lift_mm` that isn't enough: a refusal, not "the pair
    is still here"."""
    import examples.podium_passage as example

    scene = tmp_path / "short.sqlite"
    example.save(scene)
    podium, passage = _ids(example)
    before = analyze_project(scene)
    hit = _pair(before, podium, passage)
    proposal, bundle = propose_fix(scene, before, hit.finding_id, move=passage,
                                   lift_mm=10.0, rebuild=_plain_rebuild(example))
    with pytest.raises(FixError, match="fix_did_not_separate"):
        apply_fix(scene, proposal, assets=[bundle])
    assert analyze_project(scene).revision == before.revision


def test_the_broad_phase_keeps_every_finding_and_names_what_it_skipped(tmp_path):
    """Pairs go through the index, the findings are the same, and what
    was filtered out is NAMED."""
    import examples.podium_passage as example

    scene = tmp_path / "broad.sqlite"
    example.save(scene)
    report = analyze_project(scene)
    assert report.pairs_compared < report.pairs_possible, (
        "индекс ничего не отсёк — пин сторожил бы совпадение")
    assert report.broad_phase["kind"].endswith("SpatialIndex")
    assert any("широкая фаза" in limit for limit in report.analysis_limits), (
        "отсеянные пары не названы: молчание читается как «сравнили всё»")
    assert report.findings, "находок нет — сцена не та"
    # 🔴 A PARTICIPANT IS NOT AN OUTPUT. This scene has five bodies, and
    # all five have geometry; the participant count is computed from
    # what entered the search, not from the number of outputs.
    assert report.bodies_with_geometry == report.bodies_declared == 5
    assert set(report.bodies_in_pairs) <= set(report.body_ids)


def test_outputs_without_geometry_are_not_counted_as_participants(tmp_path):
    """🔴 OWNER'S FINDING (6): a count of outputs does not prove
    participation.

    The scale fixture was adding 10,000 walls with no data to build
    geometry from, and printing "10,005 outputs." Measurement
    `impl3/probe_scale.py`: such walls have no contour, no
    cross-section, no bounding box, ZERO hulls get built for them, and
    they appear in ZERO pairs. Here is the same fact on a smaller scene.
    """
    import examples.podium_passage as example
    from kir.project import ModuleInstance, NamedOutput
    from kir.project_store import ProjectStore

    scene = tmp_path / "walls.sqlite"
    store = example.save(scene)
    head = store.head()
    walls = [NamedOutput(f"w{i}", {"op": "create_wall",
                                   "p0_mm": [i * 700.0, 0.0],
                                   "p1_mm": [i * 700.0 + 600.0, 0.0],
                                   "height_mm": 3000.0,
                                   "level": {"by": "name", "value": "L0"}})
             for i in range(40)]
    revised = head.revise(
        expected_revision=head.revision_id,
        instances=[*head.instances,
                   ModuleInstance("plain", example.MODULE, walls, {})])
    writable = ProjectStore.open(scene, readonly=False)
    writable.commit(revised, expected_revision=head.revision_id)

    report = analyze_project(scene)
    assert report.bodies_declared == 5, "стена без геометрии сочтена телом"
    assert report.bodies_with_geometry == 5, (
        f"участников {report.bodies_with_geometry}: выход без оболочки "
        f"попал в знаменатель")
    assert all(len(key) == 64 for key in report.bodies_in_pairs)


def test_a_clearance_requirement_survives_the_broad_phase(tmp_path):
    """🔴 SPEEDING UP HAS NO RIGHT TO SWALLOW THE CLEARANCE REQUIREMENT.

    The index selects pairs by bounding-box proximity. Were it to take a
    single `slack_mm`, a pair separated by 10mm against a requirement of
    50 would stop being a candidate — the violation would disappear
    SILENTLY, exactly because things got faster. The broad-phase
    threshold = max(slack, requirement), and here is its number.
    """
    import examples.podium_passage as example

    scene = tmp_path / "clearance.sqlite"
    example.save(scene)
    strict = analyze_project(scene, exact=True,
                             tolerance_policy={"clearance_mm": 2000.0})
    violated = [f for f in strict.findings if f.status == "clearance_violated"]
    assert violated, "при требовании 2000 мм ни одного нарушения — пары съедены индексом"
    for finding in violated:
        assert finding.required_clearance_mm == 2000.0
        assert finding.deficit_mm is not None and finding.deficit_mm > 0.0
    # The broad-phase threshold ROSE together with the requirement,
    # rather than staying at the slack value.
    assert strict.broad_phase["slack_mm"] == 2000.0
    # Without the requirement, the same scene gives no such findings —
    # a control against tautology.
    plain = analyze_project(scene, exact=True)
    assert not [f for f in plain.findings if f.status == "clearance_violated"]


def test_a_declared_clearance_is_judged_on_the_default_path_too(tmp_path):
    """🔴 THE REQUIREMENT IS JUDGED ALWAYS, NOT BY A FLAG (review6, В-1).

    `clearance_violated` was being born in EXACTLY one place —
    `_verify_exact` — which the default path (`exact=False`) never
    enters. An attack measurement on the same scene: a gap of 10mm
    against a requirement of 50 gave `status "possible"` without the
    three fields, and `propose_fix` answered "nothing to fix: the pair
    is clear" — verbatim the owner's finding that had been declared
    closed. Worse: by this module's contract, absent fields read as
    "there was no requirement," while one had in fact been declared.
    The flag decides HOW PRECISELY we answer, and has no right to
    decide whether we ask at all.
    """
    import examples.podium_passage as example

    scene = tmp_path / "default-path.sqlite"
    example.save(scene)
    strict = analyze_project(scene, tolerance_policy={"clearance_mm": 2000.0})
    violated = [f for f in strict.findings if f.status == "clearance_violated"]
    assert violated, "на пути по умолчанию требование не судится"
    for finding in violated:
        assert finding.required_clearance_mm == 2000.0
        assert finding.deficit_mm is not None and finding.deficit_mm > 0.0
        assert finding.clearance_source
        # The exact phase WAS invoked for the candidate, even though
        # `exact` wasn't requested.
        assert finding.exact_source, "требование судится грубой оболочкой"
    assert any("судится и без `exact=True`" in limit
               for limit in strict.analysis_limits), strict.analysis_limits

    # CONTROL: without the requirement, the same scene and the same
    # flag give the old result.
    plain = analyze_project(scene)
    assert not [f for f in plain.findings if f.status.startswith("clearance_")]
    assert all(f.status == "possible" for f in plain.findings), (
        [f.status for f in plain.findings])
    assert not any("судится и без" in limit for limit in plain.analysis_limits)


def test_an_unverified_clearance_is_not_called_clear_by_the_fixer(tmp_path):
    """"Not checked" and "clean" are different answers, and the fixer
    tells them apart."""
    import examples.podium_passage as example
    from kir.clash.project_analysis import Finding

    scene = tmp_path / "unverified.sqlite"
    example.save(scene)
    report = analyze_project(scene)
    unverified = Finding("u" * 16, *_ids(example), "clearance_unverified", "clear",
                         "clearance", "test", depth_mm=None, gap_mm=10.0,
                         required_clearance_mm=50.0, deficit_mm=40.0,
                         clearance_source="analysis_policy.clearance_mm")
    patched = type(report)(**{**report.__dict__, "findings": [unverified]})
    with pytest.raises(FixError, match="clearance_unverified"):
        propose_fix(scene, patched, unverified.finding_id,
                    rebuild=_plain_rebuild(example))


def test_a_proposal_without_a_report_is_refused_instead_of_silently_written(tmp_path):
    """🔴 "CHECKED" AND "THERE WAS NOTHING TO CHECK" MUST BE
    DISTINGUISHED (review6, С-4).

    The earlier edition, when there was no report, returned SILENTLY,
    and the revision was written exactly as after a successful check —
    even though `verify=True` is the default, and the header promised
    to print a refusal.
    """
    import examples.podium_passage as example

    scene = tmp_path / "no-report.sqlite"
    example.save(scene)
    podium, passage = _ids(example)
    before = analyze_project(scene)
    hit = _pair(before, podium, passage)
    proposal, bundle = propose_fix(scene, before, hit.finding_id, move=passage,
                                   rebuild=_plain_rebuild(example))
    naked = proposal.change            # a bare ChangeProposal, carries no report
    with pytest.raises(FixError, match="proposal_unverifiable"):
        apply_fix(scene, naked, assets=[bundle])
    assert analyze_project(scene).revision == before.revision
    # And with an explicit `verify=False`, the same move goes through —
    # the refusal was about the CHECK, not about the move itself.
    head = apply_fix(scene, naked, assets=[bundle], verify=False)
    assert head != before.revision
