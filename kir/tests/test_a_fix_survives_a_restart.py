"""STAGE C: finding -> editing an AUTHORED parameter -> revision -> RESTART.

Reconnaissance on 06.09.2026 showed by measurement that this half of the
cycle is already built (`project_merge` + `ProjectStore`), so
`kir/project_fix.py` stores nothing of its own: it translates the finding
into the existing `ChangeProposal` and hands it to the existing
`accept_proposal`. Here this is verified end to end, including a restart
by A DIFFERENT PROCESS — otherwise "survives a restart" would remain just
words.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

#: The tree root — from ITS OWN file, not a machine literal (guard: test_a_test_may_not_reach_outside_the_tree).
_TREE = Path(__file__).resolve().parents[2]

pytest.importorskip("OCP", reason="сцена строится настоящим OCCT")

from kir.clash.project_analysis import analyze_project          # noqa: E402
from kir.project import output_id                               # noqa: E402
from kir.project_fix import FixError, apply_fix, propose_fix    # noqa: E402


@pytest.fixture
def scene(tmp_path):
    import examples.podium_passage as example

    path = tmp_path / "scene.sqlite"
    example.save(path)
    return path


def _passage(example):
    return output_id(example.PROJECT_ID, "passage", "passage")


def _rebuild(example):
    return lambda key, box, params: example.rebuild_body(key, box, params, instance_key=key)


def _hit(report, example):
    podium, passage = output_id(example.PROJECT_ID, "podium", "podium"), _passage(example)
    for finding in report.findings:
        if {finding.a, finding.b} == {podium, passage}:
            return finding
    raise AssertionError("пара подиума с проходом не найдена")


def test_the_whole_loop_closes_and_another_process_sees_it(scene):
    import examples.podium_passage as example

    before = analyze_project(scene)
    finding = _hit(before, example)
    assert finding.depth_mm == pytest.approx(500.0, abs=0.5)

    proposal, bundle = propose_fix(scene, before, finding.finding_id,
                                   move=_passage(example), rebuild=_rebuild(example))
    # The fix edits the BODY, not the display: otherwise "fixed" would be just a label.
    assert proposal.touches_display_only is False
    assert proposal.changed_outputs == frozenset({_passage(example)})
    assert "550.000" in proposal.describe(), proposal.describe()

    head = apply_fix(scene, proposal, assets=[bundle])
    assert head != before.revision

    # A DIFFERENT PROCESS: it has neither our memory nor our objects.
    out = subprocess.run(
        [sys.executable, "-c",
         f"import sys; sys.path.insert(0, {str(_TREE)!r});"
         "from kir.clash.project_analysis import analyze_project; import json;"
         f"r = analyze_project({str(scene)!r});"
         "print(json.dumps({'rev': r.revision, 'n': len(r.findings),"
         " 'digest': r.program_digest}))"],
        capture_output=True, text=True, timeout=300)
    assert out.returncode == 0, out.stderr[-2000:]
    fresh = json.loads(out.stdout.strip().splitlines()[-1])
    assert fresh["rev"] == head
    assert fresh["digest"] != before.program_digest, "программа не изменилась — правка не доехала"

    after = analyze_project(scene)
    assert len(after.findings) == len(before.findings) - 1
    with pytest.raises(AssertionError):
        _hit(after, example)


def test_a_report_of_another_revision_is_refused(scene):
    import examples.podium_passage as example

    before = analyze_project(scene)
    finding = _hit(before, example)
    proposal, bundle = propose_fix(scene, before, finding.finding_id,
                                   move=_passage(example), rebuild=_rebuild(example))
    apply_fix(scene, proposal, assets=[bundle])
    # The report went stale along with the head — it must not be used to propose from.
    with pytest.raises(FixError, match="another revision"):
        propose_fix(scene, before, finding.finding_id,
                    move=_passage(example), rebuild=_rebuild(example))


def test_a_clear_pair_is_not_something_to_fix(scene):
    import examples.podium_passage as example
    from kir.clash.project_analysis import Finding

    report = analyze_project(scene)
    clear = Finding("f" * 16, _passage(example), _passage(example), "possible",
                    "clear", "clearance", "test", depth_mm=None, gap_mm=10.0)
    patched = type(report)(**{**report.__dict__, "findings": [clear]})
    with pytest.raises(FixError, match="clear"):
        propose_fix(scene, patched, clear.finding_id, rebuild=_rebuild(example))


def test_the_strategy_refuses_a_shape_it_cannot_raise(scene):
    """The podium is defined by a recipe, not a box: raising it FAILS by name."""
    import examples.podium_passage as example

    report = analyze_project(scene)
    finding = _hit(report, example)
    with pytest.raises(FixError, match="parameterised otherwise"):
        propose_fix(scene, report, finding.finding_id,
                    move=output_id(example.PROJECT_ID, "podium", "podium"),
                    rebuild=_rebuild(example))


def test_an_unknown_strategy_is_named(scene):
    import examples.podium_passage as example

    report = analyze_project(scene)
    with pytest.raises(FixError, match="unknown strategy"):
        propose_fix(scene, report, _hit(report, example).finding_id, strategy="teleport")


def test_the_lift_is_the_z_overlap_not_whatever_depth_the_exact_phase_reports(scene):
    """🔴 MY OWN DEFECT, CAUGHT BY EXECUTION ON 06.09.2026.

    `raise_clear` moves along ONE axis, yet it took `depth_mm` — a field
    that two phases compute by different laws. Measured on the acceptance
    scene: the rough finding gave 500.0 (matched z by coincidence — that is
    the SHORT axis), the exact one gave 3000.01, and with `exact=True` the
    pass raised things by 3050.010 mm instead of 550.000. Not a single red
    light came on: the collision genuinely disappeared, it is just that the
    project itself moved three meters along with it. A silent falsehood.

    The pin checks the NUMBER, not the fact of cleanliness, and checks it
    in BOTH phases: if raising starts depending again on whether the exact
    phase was called, the test will go red.

    🔴 THE COUNTERPIN WENT RED FROM A NEIGHBOR'S SUCCESS, AND WAS FIXED BY
    REMOVING THE PREMISE, NOT BY ADJUSTING IT (07.09.2026). The last line
    required the exact depth to DIFFER from 500 — that is, for the
    `exact.py` defect to keep existing. It was fixed by commit `81bc166`
    (`_solid_spans` switched to `TopAbs_SOLID` + `AddOptimal_s`), and
    `verify_pair` now honestly returns 500.0 in both argument orders.
    Measured on a CLEAN `git archive HEAD` (e5fa16f): the same line, the
    same failure — the pin was red BEFORE the fixes of the 07.09 wave. The
    counterexample was restored on a MADE-UP finding: the law "raising
    takes the dimensions, not `depth_mm`" is checked by a number that the
    scene is no longer obligated to belong to.
    """
    import examples.podium_passage as example

    coarse = analyze_project(scene)
    exact = analyze_project(scene, exact=True)
    lifts = []
    for report in (coarse, exact):
        finding = _hit(report, example)
        proposal, _ = propose_fix(scene, report, finding.finding_id,
                                  rebuild=_rebuild(example))
        lifts.append(proposal.describe())

    for text in lifts:
        assert "поднять на 550.000 мм" in text, text
        assert "перекрытие по z у габаритов оболочек 500.000" in text, text
    hit = _hit(exact, example)
    assert hit.exact_source, "точная фаза не участвовала: пин ничего не сторожит"
    # The counterexample IS CONSTRUCTED: the finding is assigned a
    # deliberately foreign depth. If the strategy ever starts reading it
    # again, the raise will become 3050.010, and the pin will go red — and
    # there is no need to keep the scene around for this.
    import dataclasses

    lying = dataclasses.replace(hit, depth_mm=3000.01)
    patched = type(exact)(**{**exact.__dict__,
                             "findings": [lying if f is hit else f for f in exact.findings]})
    proposal, _ = propose_fix(scene, patched, lying.finding_id, rebuild=_rebuild(example))
    assert "поднять на 550.000 мм" in proposal.describe(), proposal.describe()


def test_moving_a_body_outside_the_pair_is_refused_by_name(scene):
    """Name a third body — and the "fix" would report on a pair it never touched."""
    import examples.podium_passage as example

    report = analyze_project(scene)
    finding = _hit(report, example)
    outsider = next(oid for oid in sorted(report.body_ids)
                    if oid not in (finding.a_output_id, finding.b_output_id))
    with pytest.raises(FixError, match="не входит в пару"):
        propose_fix(scene, report, finding.finding_id, move=outsider,
                    rebuild=_rebuild(example))
