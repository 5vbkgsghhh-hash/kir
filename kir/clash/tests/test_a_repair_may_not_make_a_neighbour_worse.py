# -*- coding: utf-8 -*-
"""KIR-F001: "the pair did not appear" is not yet "the neighbour did not get worse".

🔴 A FACT FROM THE EXTERNAL AUDIT, RE-MEASURED HERE ON 2026-09-07.
`apply_fix(verify=True)` checked exactly one thing: whether NEW conflicting
pairs appeared. `new_conflicts` compares SETS of pair keys (`_pair_key`), so
a pair that existed and remained drops out of the comparison entirely —
along with its numbers.

THE AUDIT SCENE, THREE 100×100 BOXES IN XY, BY Z:

    A = [0, 100]      the lift target
    B = [−90, 10]     overlap with A along z: 10 mm — this is the pair being fixed
    C = [90, 200]     overlap with A along z: 10 mm — and this one gets worse

Lifting A by 20 mm separates A/B and DRIVES A DEEPER into C: 10 → 30 mm.

MEASURED ON THIS TREE (`exact=False`, HEAD 1224c89), which also explains why
the probe rests on `depth_mm` and not on volume: under the coarse phase
there is NO volume at all.

    BEFORE  C/A  possible/intersect  depth_mm=10.000000199999988  volume=None
    AFTER   C/A  possible/intersect  depth_mm=30.000000199999988  volume=None
    new_conflicts = []  ->  the proposal WAS ACCEPTED, the head moved forward

The volume 100 000 → 300 000 mm³ from the audit report is a value of the
EXACT phase; under `exact=False` its place is taken by the depth, and the
guard must rest on the number that IS in the report, not on the one that
was expected there.
"""
from __future__ import annotations

import hashlib
import json
import platform

import pytest

# 🔴 THE KERNEL IS TAKEN THROUGH ONE SINGLE DOOR, NOT A DIRECT `import OCP`.
# A direct import here would be a SECOND boundary crossing from the tree
# into a foreign package, and the closed list
# (`kir/tests/test_kir_boundary_to_the_product_is_a_closed_list.py`) named it
# by a number: 52 hard exits against a bar of 51. The ratchet only goes
# down, which means it is the exit that gets fixed, not the bar.
# `kir.occt_geometry._kernel()` is the same door as `kir/clash/exact.py`
# uses, and it is the one that checks the version pin exactly once.
from kir.occt_geometry import GeometryRefusal, _kernel                # noqa: E402

try:
    _kernel()
except GeometryRefusal as _refusal:                                   # pragma: no cover
    pytest.skip(f"ядро недоступно ({_refusal.code}): сцена строится настоящим OCCT",
                allow_module_level=True)

from kir.clash.project_analysis import analyze_project                # noqa: E402
from kir.project import output_id                                     # noqa: E402
from kir.project_fix import FixError, apply_fix, propose_fix          # noqa: E402

PROJECT_ID = "f001-worsen"
MODULE = "f001-scene-v1"

#: The audit's boxes. XY is the same for all of them, the only difference is
#: along Z — so "depth along z" and "overlap along the short axis" are one
#: and the same number, and there is nothing to argue about.
A = ((0., 0., 0.), (100., 100., 100.))
B = ((0., 0., -90.), (100., 100., 10.))
C = ((0., 0., 90.), (100., 100., 200.))


def _pin():
    from kir.occt_geometry import OCP_VERSION
    from kir.project import RecipePin

    env = {"python": platform.python_version(), "ocp_package": OCP_VERSION,
           "dependencies": {}}
    digest = hashlib.sha256(json.dumps(env, sort_keys=True).encode()).hexdigest()
    return RecipePin("f001 scene", digest, entrypoint="build", dependencies={})


def _shape(bounds):
    k = _kernel()
    (x0, y0, z0), (x1, y1, z1) = bounds
    return k.BRepPrimAPI.BRepPrimAPI_MakeBox(
        k.gp.gp_Pnt(x0, y0, z0), k.gp.gp_Pnt(x1, y1, z1)).Shape()


def _rebuild(output_key, box, parameters, frame=None):
    from kir.occt_geometry import IDENTITY_FRAME, capture_body

    return capture_body(_shape(box), project_id=PROJECT_ID, instance_key=output_key,
                        output_key=output_key, recipe=_pin(), parameters=parameters,
                        frame=tuple(frame) if frame else IDENTITY_FRAME,
                        linear_deflection_mm=5.)


def _save(path, boxes):
    from kir.occt_geometry import IDENTITY_FRAME, capture_body
    from kir.project import (BodyRepresentation, ModuleDefinition, ModuleInstance,
                             NamedOutput, PROJECT_SCHEMA_V2, ProjectRevision)
    from kir.project_store import ProjectStore

    pin = _pin()
    instances, bundles = [], {}
    for key, bounds in boxes.items():
        own = {key: [list(bounds[0]), list(bounds[1])]}
        bundle = capture_body(_shape(bounds), project_id=PROJECT_ID, instance_key=key,
                              output_key=key, recipe=pin, parameters=own,
                              frame=IDENTITY_FRAME, linear_deflection_mm=5.)
        bundles[key] = bundle
        instances.append(ModuleInstance(
            key, MODULE,
            [NamedOutput(key, {"op": "create_directshape", "category": "mass",
                               "name": "f001 " + key},
                         BodyRepresentation(bundle.digest, bundle.body_digest))], own))
    seed = NamedOutput("origin", {"op": "create_level", "elev_mm": 0, "name": "L0"})
    root = ProjectRevision(PROJECT_ID, [ModuleDefinition(MODULE)],
                           [ModuleInstance("origin", MODULE, [seed])])
    upgraded = root.upgrade_schema(PROJECT_SCHEMA_V2, expected_revision=root.revision_id)
    revision = upgraded.revise(
        expected_revision=upgraded.revision_id,
        modules=[ModuleDefinition(MODULE, "sealed_evaluation", pin)],
        instances=instances)
    store = ProjectStore.create(path, root)
    store.upgrade_schema("kir-project-store/2", expected_revision=root.revision_id)
    store.commit(upgraded, expected_revision=root.revision_id)
    store.commit(revision, expected_revision=upgraded.revision_id,
                 assets=list(bundles.values()))
    return store


def _ids(*keys):
    return tuple(output_id(PROJECT_ID, k, k) for k in keys)


def _finding(report, x, y):
    for item in report.findings:
        if {item.a_output_id, item.b_output_id} == {x, y}:
            return item
    return None


def _scene(tmp_path, name, boxes):
    path = tmp_path / name
    _save(path, boxes)
    return path


def test_a_lift_that_drives_the_target_deeper_into_a_third_body_is_refused(tmp_path):
    """🔴 THE AUDIT'S RED: A/B is separated, A/C became two-to-three times deeper."""
    scene = _scene(tmp_path, "worsen.sqlite", {"A": A, "B": B, "C": C})
    a, b, c = _ids("A", "B", "C")
    before = analyze_project(scene)
    ab, ac = _finding(before, a, b), _finding(before, a, c)
    assert ab is not None and ac is not None, "сцена не та: нужны обе пары"
    assert ac.depth_mm == pytest.approx(10.0, abs=1e-3), ac.depth_mm

    proposal, bundle = propose_fix(scene, before, ab.finding_id, move=a,
                                   lift_mm=20.0, rebuild=_rebuild)
    assert proposal.world_lift_mm == pytest.approx(20.0)

    with pytest.raises(FixError, match="fix_worsens_existing_conflict") as raised:
        apply_fix(scene, proposal, assets=[bundle])
    text = str(raised.value)
    # The refusal must name the PAIR and BOTH numbers, otherwise it is about a different subject.
    assert c[:12] in text and a[:12] in text, text
    assert "10.000" in text and "30.000" in text, text

    # THE MAIN POINT: nothing was recorded into history.
    again = analyze_project(scene)
    assert again.revision == before.revision
    assert _finding(again, a, b) is not None, "голова сдвинулась вопреки отказу"


def test_the_same_lift_without_the_third_body_is_accepted(tmp_path):
    """CONTROL 1: a clean move is accepted. Without it, the guard could be silencing everything."""
    scene = _scene(tmp_path, "clean.sqlite", {"A": A, "B": B})
    a, b = _ids("A", "B")
    before = analyze_project(scene)
    ab = _finding(before, a, b)
    proposal, bundle = propose_fix(scene, before, ab.finding_id, move=a,
                                   lift_mm=20.0, rebuild=_rebuild)
    head = apply_fix(scene, proposal, assets=[bundle])
    after = analyze_project(scene)
    assert after.revision == head != before.revision
    assert _finding(after, a, b) is None, "пара осталась — сцена не та"


def test_the_refusal_comes_from_the_worsening_check_and_from_nothing_else(
        tmp_path, monkeypatch):
    """FAIL CONTROL BY MUTATION: disarm the assessment — and the same proposal goes through."""
    scene = _scene(tmp_path, "control.sqlite", {"A": A, "B": B, "C": C})
    a, b, _c = _ids("A", "B", "C")
    before = analyze_project(scene)
    ab = _finding(before, a, b)
    proposal, bundle = propose_fix(scene, before, ab.finding_id, move=a,
                                   lift_mm=20.0, rebuild=_rebuild)
    monkeypatch.setattr("kir.project_fix.worsened_conflicts",
                        lambda before, after, *, ignore=(): ([], []))
    head = apply_fix(scene, proposal, assets=[bundle])
    assert head != before.revision, "с обезвреженной оценкой запись не состоялась"


def test_the_body_strategy_goes_through_the_same_assessment(tmp_path):
    """`raise_clear_body` — a second strategy for the same lift, ONE guard."""
    scene = _scene(tmp_path, "body.sqlite", {"A": A, "B": B, "C": C})
    a, b, _c = _ids("A", "B", "C")
    before = analyze_project(scene)
    ab = _finding(before, a, b)
    proposal, bundle = propose_fix(scene, before, ab.finding_id, move=a,
                                   lift_mm=20.0, strategy="raise_clear_body")
    with pytest.raises(FixError, match="fix_worsens_existing_conflict"):
        apply_fix(scene, proposal, assets=[bundle])


# ------------------------------------------------- kinds 2 and 3, directly on the assessment

from dataclasses import dataclass                                     # noqa: E402
from kir.project_fix import worsened_conflicts                        # noqa: E402


@dataclass
class _F:
    """A finding with exactly the fields the assessment reads."""
    a_output_id: str = "aaaa"
    b_output_id: str = "bbbb"
    status: str = "possible"
    depth_mm: float | None = 10.0
    overlap_volume_mm3: float | None = None
    surface_intersections: int | None = None
    deficit_mm: float | None = None
    exact_source: str | None = None


@dataclass
class _R:
    findings: list


def test_a_changed_measurer_is_unverifiable_not_unchanged():
    """(3) The exact phase BEFORE, the coarse one AFTER: there is nothing to
    compare — and this is NOT "not worse".

    The case is not invented: the exact phase is limited by a budget
    (`exact_pair_budget`, refusal `exact_budget_exhausted`), and the same
    pair can legitimately be judged exactly before and coarsely after,
    under the SAME run options.
    """
    before = _R([_F(exact_source="occt", depth_mm=3000.01)])
    after = _R([_F(exact_source=None, depth_mm=500.0)])
    worse, incomparable = worsened_conflicts(before, after)
    # The number DROPPED, and a naive check would say "it got better".
    assert worse == [], worse
    assert len(incomparable) == 1 and "exact_source" in incomparable[0][1]


def test_losing_the_measurement_counts_as_worse_not_as_silence():
    """(2) The pair was measured, became `clearance_unverified` — "not checked" ≠ "not worse"."""
    before = _R([_F(status="clearance_violated", depth_mm=None, deficit_mm=12.0)])
    after = _R([_F(status="clearance_unverified", depth_mm=None, deficit_mm=None)])
    worse, incomparable = worsened_conflicts(before, after)
    assert incomparable == []
    assert len(worse) == 1 and worse[0][1] == "измеримость", worse


def test_an_unchanged_pair_is_not_called_worse():
    """CONTROL: the same numbers with recomputation noise are NOT counted as a worsening."""
    before = _R([_F(depth_mm=10.000000199999988)])
    after = _R([_F(depth_mm=10.000000199999999)])
    assert worsened_conflicts(before, after) == ([], [])


def test_an_improved_pair_is_not_called_worse():
    """CONTROL: the measure DROPPED under the same instrument — silence."""
    assert worsened_conflicts(_R([_F(depth_mm=30.0)]), _R([_F(depth_mm=10.0)])) == ([], [])


def test_the_repaired_pair_itself_is_not_judged_by_this_check():
    """CONTROL: the pair being fixed is handled by `fix_did_not_separate`, not by this assessment."""
    before, after = _R([_F(depth_mm=10.0)]), _R([_F(depth_mm=30.0)])
    assert worsened_conflicts(before, after, ignore=(("aaaa", "bbbb"),)) == ([], [])
    # without `ignore` the same pair IS counted as a worsening — a control on discriminating power
    worse, _inc = worsened_conflicts(before, after)
    assert len(worse) == 1 and worse[0][1] == "глубина проникания, мм", worse
