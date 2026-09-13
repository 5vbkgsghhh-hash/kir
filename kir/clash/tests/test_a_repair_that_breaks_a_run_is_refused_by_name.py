# -*- coding: utf-8 -*-
"""B03: MEP REPAIR HAS NO RIGHT TO TEAR APART CONNECTIONS, THE SYSTEM, OR
THE SLOPE.

🔴 WHAT IS RED HERE, MEASURED 07.09.2026. `kir.project_fix.propose_fix`
does not ask the element's TYPE at all: the word `operation` is read
exactly once, and only to copy the old operation into the new output.
The only thing that stops a run from being lifted today is the absence
of a box on it, that is, a refusal ABOUT PARAMETERIZATION where the
question is about TYPE. An element that came from a mass capture with a
box and CARRYING, in its parameters, a connector graph and
`slope_min_pct`, was being lifted silently — and that is a torn system
and a broken KIR-X004 postcondition.

THREE CHECKS:
  (1) RED: a run with connectors/slope -> `repair_profile_unsupported:…`,
      not a silent shift;
  (2) FAIL CONTROL BY MUTATION: with the profile disarmed, the same
      element gets lifted — meaning the red is held EXACTLY by the
      profile, not by something else;
  (3) POSITIVE: a free segment without connectors gets lifted, and the
      AXIS moves by the SAME vector as the body — the slope is
      preserved as a NUMBER.
"""
from __future__ import annotations

import hashlib
import json
import math
import platform

import pytest

pytest.importorskip("OCP", reason="сцена строится настоящим OCCT")

from kir.clash import repair_profile as RP                      # noqa: E402
from kir.clash.project_analysis import analyze_project           # noqa: E402
from kir.project import output_id                                # noqa: E402
from kir.project_fix import FixError, propose_fix                # noqa: E402

PROJECT_ID = "mep-repair-profile"
MODULE = "mep-repair-profile-scene-v1"

#: A slab and a run segment beneath it: a 500mm intersection along z.
SLAB = ((0., 0., 0.), (6000., 4000., 500.))
RUN = ((1000., 1000., 200.), (5000., 1200., 400.))


def _pin():
    from kir.occt_geometry import OCP_VERSION
    from kir.project import RecipePin

    environment = {"python": platform.python_version(), "ocp_package": OCP_VERSION,
                   "dependencies": {}}
    digest = hashlib.sha256(json.dumps(environment, sort_keys=True).encode()).hexdigest()
    return RecipePin("mep repair profile scene", digest, entrypoint="build",
                     dependencies={})


def _box(bounds):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt

    (x0, y0, z0), (x1, y1, z1) = bounds
    return BRepPrimAPI_MakeBox(gp_Pnt(x0, y0, z0), gp_Pnt(x1, y1, z1)).Shape()


def rebuild_body(output_key, box, parameters, *, frame=None):
    from kir.occt_geometry import IDENTITY_FRAME, capture_body

    return capture_body(_box(box), project_id=PROJECT_ID, instance_key=output_key,
                        output_key=output_key, recipe=_pin(), parameters=parameters,
                        frame=tuple(frame) if frame else IDENTITY_FRAME,
                        linear_deflection_mm=40.)


def _rebuild():
    def rebuild(output_key, box, parameters, frame=None):
        return rebuild_body(output_key, box, parameters, frame=frame)
    return rebuild


def _save(path, run_parameters, frame=None):
    """Scene: slab `slab` and run segment `run` with DECLARED
    parameters."""
    from kir.occt_geometry import IDENTITY_FRAME, capture_body
    from kir.project import (BodyRepresentation, ModuleDefinition, ModuleInstance,
                             NamedOutput, PROJECT_SCHEMA_V2, ProjectRevision)
    from kir.project_store import ProjectStore

    placed = tuple(frame) if frame else IDENTITY_FRAME
    pin = _pin()
    scene = {"slab": ({"slab": [list(SLAB[0]), list(SLAB[1])]}, SLAB),
             "run": (dict(run_parameters, run=[list(RUN[0]), list(RUN[1])]), RUN)}
    instances, bundles = [], {}
    for key, (own, bounds) in scene.items():
        bundle = capture_body(_box(bounds), project_id=PROJECT_ID, instance_key=key,
                              output_key=key, recipe=pin, parameters=own,
                              frame=placed, linear_deflection_mm=40.)
        bundles[key] = bundle
        output = NamedOutput(
            key, {"op": "create_directshape", "category": "mass", "name": "mep " + key},
            BodyRepresentation(bundle.digest, bundle.body_digest))
        instances.append(ModuleInstance(key, MODULE, [output], own))
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


#: The run AS THE LANGUAGE DECLARES IT: an axis (`ops_mep.create_duct`),
#: a connector graph, and a slope floor (`ops_connect.route_duct_system`
#: + `route_mep`).
CONNECTED_RUN = {
    "p0_mm": list(RUN[0]), "p1_mm": list(RUN[1]),
    "system_type": "ОВ приточная",
    "nodes": {"n0": list(RUN[0]), "n1": list(RUN[1])},
    "segments": [{"from": "n0", "to": "n1", "diameter_mm": 200.,
                  "slope_min_pct": 2.0}],
}

#: A FREE segment: the same axis, and NOTHING ELSE. No graph, no system,
#: no slope.
FREE_RUN = {"p0_mm": list(RUN[0]), "p1_mm": list(RUN[1]), "diameter_mm": 200.}


def _refusal_code(text: str) -> str:
    """The refusal's CODE — everything up to the first `": "`.

    🔴 WHY SEPARATE, MEASURED 08.09.2026. `propose_fix` glues
    `repair_profile.describe()` onto the refusal, and that lists ALL the
    profile's names at once. So `assert "slope_declared" in str(error)`
    is ALWAYS green — for `system_membership` too, and for
    `mep_category` too. Such a probe guards nothing. Here exactly the
    code is checked, and the discriminating power is verified by a
    control.
    """
    return text.split(": ", 1)[0]


def test_the_refusal_code_is_not_the_whole_text():
    """A control on the helper itself: the full text has ALL the names,
    the code has one."""
    text = "repair_profile_unsupported:mep_category:OST_DuctCurves: почему. " + RP.describe()
    assert _refusal_code(text) == "repair_profile_unsupported:mep_category:OST_DuctCurves"
    for name, _why in RP.UNSUPPORTED:
        assert name in text            # the full text names everything
    assert "slope_declared" not in _refusal_code(text)   # the code — only one


def _finding(report, a, b):
    for item in report.findings:
        if {item.a_output_id, item.b_output_id} == {a, b}:
            return item
    return None


def _ids():
    return (output_id(PROJECT_ID, "slab", "slab"),
            output_id(PROJECT_ID, "run", "run"))


def test_a_connected_run_is_refused_by_name_not_shifted_silently(tmp_path):
    """(1) RED: lifting a run with connectors and a slope — a refusal BY
    NAME."""
    _save(tmp_path / "connected.sqlite", CONNECTED_RUN)
    scene = tmp_path / "connected.sqlite"
    slab, run = _ids()
    report = analyze_project(scene)
    hit = _finding(report, slab, run)
    assert hit is not None, "пара плита×трасса не найдена — сцена не та"

    with pytest.raises(FixError, match="repair_profile_unsupported") as raised:
        propose_fix(scene, report, hit.finding_id, move=run, rebuild=_rebuild())
    # The refusal must name WHAT exactly isn't supported, not just
    # "can't", and it is the CODE that is checked: the full text lists
    # all the profile's names at once.
    code = _refusal_code(str(raised.value))
    assert code == "repair_profile_unsupported:slope_declared:2.0", code


def test_the_refusal_comes_from_the_profile_and_from_nothing_else(tmp_path,
                                                                 monkeypatch):
    """(2) FAIL CONTROL BY MUTATION: disarm the profile — and the lift
    goes through.

    Without this control, the red above could be held up by anything at
    all (no body, no box, no finding), and "the profile works" would be
    a statement about a different subject.
    """
    scene = tmp_path / "control.sqlite"
    _save(scene, CONNECTED_RUN)
    slab, run = _ids()
    report = analyze_project(scene)
    hit = _finding(report, slab, run)

    monkeypatch.setattr("kir.clash.repair_profile.classify",
                        lambda instance, output: None)
    proposal, bundle = propose_fix(scene, report, hit.finding_id, move=run,
                                   rebuild=_rebuild())
    assert proposal.world_lift_mm > 0.0, "с обезвреженным профилем подъём не состоялся"


def test_a_free_segment_is_lifted_with_its_axis_and_keeps_its_slope(tmp_path):
    """(3) POSITIVE: the axis moves with the body, the slope is
    preserved as a NUMBER."""
    scene = tmp_path / "free.sqlite"
    _save(scene, FREE_RUN)
    slab, run = _ids()
    report = analyze_project(scene)
    hit = _finding(report, slab, run)
    assert hit is not None

    before_axis = RP.axis_of(FREE_RUN)
    before_slope = RP.slope_pct(before_axis)
    assert before_slope is not None and before_slope != 0.0, (
        "у эталонного отрезка нет уклона — зонд сторожил бы ноль")

    proposal, bundle = propose_fix(scene, report, hit.finding_id, move=run,
                                   rebuild=_rebuild())
    lift = proposal.world_lift_mm
    changed = proposal.change.candidate
    instance = next(item for item in changed.instances if item.key == "run")
    after_axis = RP.axis_of(instance.parameters)
    assert after_axis is not None, "ось пропала из параметров"
    # THE AXIS MOVES WITH THE BODY. Leaving the axis in place would mean
    # separating the body from its own run: one element, but now with
    # two addresses.
    for k, (was, now) in enumerate(zip(before_axis, after_axis)):
        assert now[0] == pytest.approx(was[0], abs=1e-9)
        assert now[1] == pytest.approx(was[1], abs=1e-9)
        assert now[2] == pytest.approx(was[2] + lift, abs=1e-6), (
            f"конец {k} оси не поднялся вместе с телом")
    # THE SLOPE — AS A NUMBER, not the word "preserved."
    after_slope = RP.slope_pct(after_axis)
    assert after_slope == pytest.approx(before_slope, rel=1e-12), (
        f"уклон изменился: было {before_slope!r}, стало {after_slope!r}")


def test_the_profile_names_an_mep_category_from_the_closed_hull_table():
    """The `mep` side's category — a refusal, and it takes its wording
    from the existing table."""
    class _Output:
        operation = {"op": "create_directshape", "category": "mass", "name": "x"}

    class _Instance:
        parameters = {"box": [[0., 0., 0.], [1., 1., 1.]]}
        metadata = {"source_category": "OST_DuctCurves"}

    verdict = RP.classify(_Instance(), _Output())
    assert verdict is not None, "воздуховод из захвата прошёл как обычная масса"
    assert verdict[0] == "repair_profile_unsupported:mep_category:OST_DuctCurves"
    # A control on the same instrument: a mass is not an `mep` side.
    class _Plain(_Instance):
        metadata = {"source_category": "OST_Mass"}

    assert RP.classify(_Plain(), _Output()) is None


def test_the_declared_profile_is_a_list_not_a_promise():
    """The profile is DECLARED as a list, and both sides are
    non-empty."""
    assert RP.SUPPORTED and RP.UNSUPPORTED
    text = RP.describe()
    for name, _why in (*RP.SUPPORTED, *RP.UNSUPPORTED):
        assert name in text, f"{name} не назван в заявлении профиля"


# --------------------------------------------------- SELF-REVIEW: slope and mix

def _frame(axis: str, degrees: float, translate=(9000., -4000., 2500.)):
    angle = math.radians(degrees)
    c, s = math.cos(angle), math.sin(angle)
    rows = {"x": ((1., 0., 0.), (0., c, -s), (0., s, c)),
            "y": ((c, 0., s), (0., 1., 0.), (-s, 0., c)),
            "z": ((c, -s, 0.), (s, c, 0.), (0., 0., 1.))}[axis]
    return tuple(v for i, row in enumerate(rows) for v in (*row, translate[i])) \
        + (0., 0., 0., 1.)


#: An axis NOT along X and NOT along Y, tilted: three non-zero
#: components.
OBLIQUE = ([1200.0, 2300.0, 310.0], [4700.0, 6500.0, 890.0])


@pytest.mark.parametrize("вектор", [
    (0.0, 0.0, 350.0),            # pure lift
    (0.0, 0.0, -1234.5678),       # descent
    (911.0, -477.0, 350.0),       # a vector with X/Y and Z — a rotated frame
    (-1e6, 2.5e5, 7.5e5),         # a large translation: the numbers don't "line up" by accident
])
def test_a_translation_keeps_an_oblique_slope_bit_for_bit(вектор):
    """The slope is a property of the DIFFERENCE of the endpoints, so a
    translation doesn't touch it. As a number."""
    было = RP.slope_pct(OBLIQUE)
    стало = RP.slope_pct(([OBLIQUE[0][k] + вектор[k] for k in range(3)],
                          [OBLIQUE[1][k] + вектор[k] for k in range(3)]))
    assert было is not None and abs(было) > 1.0, было
    # BIT-FOR-BIT, not "approximately": a translation has no right to
    # round the slope.
    assert стало == было, (было, стало, вектор)


def test_a_vertical_riser_has_no_slope_instead_of_zero():
    """A control on the instrument's discriminating power: a riser has
    NO slope."""
    assert RP.slope_pct(([0., 0., 0.], [0., 0., 3000.])) is None


def test_a_free_oblique_segment_keeps_its_slope_under_a_rotated_frame(tmp_path):
    """End-to-end: the frame is rotated 37° around X, the increment is
    NOT along the z axis."""
    scene = tmp_path / "oblique.sqlite"
    frame = _frame("x", 37.0)
    _save(scene, {"p0_mm": list(OBLIQUE[0]), "p1_mm": list(OBLIQUE[1]),
                  "diameter_mm": 200.}, frame=frame)
    slab, run = _ids()
    report = analyze_project(scene)
    hit = _finding(report, slab, run)
    assert hit is not None, "пара не найдена — сцена не та"

    def rebuild(output_key, box, parameters, frame=frame):
        return rebuild_body(output_key, box, parameters, frame=frame)

    proposal, _bundle = propose_fix(scene, report, hit.finding_id, move=run,
                                    rebuild=rebuild)
    delta = proposal.local_delta_mm
    # The increment MUST NOT be along the z axis, otherwise the probe
    # would be guarding a coincidence.
    assert abs(delta[0]) + abs(delta[1]) > 1e-6, delta
    instance = next(i for i in proposal.change.candidate.instances if i.key == "run")
    было, стало = RP.slope_pct(OBLIQUE), RP.slope_pct(RP.axis_of(instance.parameters))
    assert стало == было, (было, стало, delta)


def test_a_mixed_element_is_judged_by_its_mep_fields_not_by_its_body_category():
    """(3) The body is an ordinary mass, but the MEP fields are present:
    the FIELDS win, not the category."""
    class _Output:
        operation = {"op": "create_directshape", "category": "mass", "name": "x"}

    class _Mixed:
        metadata = {"source_category": "OST_Mass"}   # NOT an mep side
        parameters = {"box": [[0., 0., 0.], [1., 1., 1.]],
                      "p0_mm": [0., 0., 0.], "p1_mm": [1000., 0., 20.],
                      "segments": [{"from": "a", "to": "b", "slope_min_pct": 1.5}]}

    verdict = RP.classify(_Mixed(), _Output())
    assert verdict is not None, "смешанный элемент прошёл как поддержанный"
    assert verdict[0].startswith("repair_profile_unsupported:slope_declared"), verdict[0]

    # Each field on its own — its own named refusal, not a generic
    # "can't."
    class _OnlyGraph(_Mixed):
        parameters = {"box": [[0., 0., 0.], [1., 1., 1.]],
                      "nodes": {"a": [0., 0., 0.], "b": [1000., 0., 20.]}}

    class _OnlySystem(_Mixed):
        parameters = {"box": [[0., 0., 0.], [1., 1., 1.]], "system_type": "ВК"}

    assert RP.classify(_OnlyGraph(), _Output())[0] == \
        "repair_profile_unsupported:connectors_declared"
    assert RP.classify(_OnlySystem(), _Output())[0] == \
        "repair_profile_unsupported:system_membership:ВК"

    # CONTROL: without a single MEP field, the same element is
    # supported.
    class _Plain(_Mixed):
        parameters = {"box": [[0., 0., 0.], [1., 1., 1.]]}

    assert RP.classify(_Plain(), _Output()) is None


# ─────────── WAVE 9 (M1): A BODY FROM AN AUTHORED OP, NOT FROM CAPTURE ──────
#
# 🔴 MEASURED 08.09.2026. Everything above judges an element that came
# FROM CAPTURE: a mass with a box, whose MEP fields live in
# `instance.parameters`. For an AUTHORED program they live somewhere
# else — in the output's OPERATION (`author_project` copies the op's
# payload into `NamedOutput.operation`), and that's why a revision made
# with `create_duct` gave `classify(...) is None`, and `propose_fix`
# refused with SOMEONE ELSE'S words: «raise_clear needs a box parameter
# … this output's shape is parameterised otherwise» — about
# PARAMETERIZATION where the question is about TYPE.

#: An authored duct: the system is declared by a selector, the axis has
#: a slope.
AUTHORED_DUCT = {
    "op": "create_duct", "p0_mm": list(RUN[0]), "p1_mm": list(RUN[1]),
    "level": {"by": "name", "value": "L0"},
    "system_type": {"by": "name", "value": "ОВ приточная"},
    "diameter_mm": 200.,
}


def _save_authored(path, operation):
    """Scene: a slab AS A BODY and a run AS AN AUTHORED OPERATION (no
    body in the revision).

    A body in the project must be `create_directshape`
    (`kir/project.py`), and that's why an authored op has no body at
    all: `clash_bundle` builds its hull from the axis and diameter.
    This is the true shape of an authored run in a revision.
    """
    from kir.occt_geometry import IDENTITY_FRAME, capture_body
    from kir.project import (BodyRepresentation, ModuleDefinition, ModuleInstance,
                             NamedOutput, PROJECT_SCHEMA_V2, ProjectRevision)
    from kir.project_store import ProjectStore

    pin = _pin()
    slab_own = {"slab": [list(SLAB[0]), list(SLAB[1])]}
    bundle = capture_body(_box(SLAB), project_id=PROJECT_ID, instance_key="slab",
                          output_key="slab", recipe=pin, parameters=slab_own,
                          frame=IDENTITY_FRAME, linear_deflection_mm=40.)
    instances = [
        ModuleInstance("slab", MODULE, [NamedOutput(
            "slab", {"op": "create_directshape", "category": "mass", "name": "mep slab"},
            BodyRepresentation(bundle.digest, bundle.body_digest))], slab_own),
        ModuleInstance("run", MODULE, [NamedOutput("run", dict(operation))], {}),
    ]
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
    store.commit(revision, expected_revision=upgraded.revision_id, assets=[bundle])
    return store


def _authored_scene(tmp_path, name, operation=AUTHORED_DUCT):
    scene = tmp_path / name
    _save_authored(scene, operation)
    slab, run = _ids()
    report = analyze_project(scene)
    hit = _finding(report, slab, run)
    assert hit is not None, "пара плита×авторская трасса не найдена — сцена не та"
    return scene, report, hit, run


def test_an_authored_run_is_refused_by_its_type_not_by_its_parameterisation(tmp_path):
    """(M1) An authored run is judged AS A RUN, and the refusal carries
    the slope as a NUMBER."""
    scene, report, hit, run = _authored_scene(tmp_path, "authored.sqlite")
    with pytest.raises(FixError) as raised:
        propose_fix(scene, report, hit.finding_id, move=run, rebuild=_rebuild())
    text = str(raised.value)
    # The slope is computed by its OWN formula, not asked of the module
    # under test.
    (x0, y0, z0), (x1, y1, z1) = RUN
    ожидание = (z1 - z0) / math.hypot(x1 - x0, y1 - y0) * 100.0
    assert _refusal_code(text) == \
        f"repair_profile_unsupported:mep_axis_slope:{ожидание:.6g}", text
    assert "OST_DuctCurves" in text, text
    # The old, WRONG refusal (about parameterization) no longer occurs.
    assert "parameterised otherwise" not in text, text


def test_the_authored_refusal_is_held_by_the_producer_and_by_nothing_else(
        tmp_path, monkeypatch):
    """FAIL CONTROL BY MUTATION: without the producer, the WRONG
    refusal comes back."""
    scene, report, hit, run = _authored_scene(tmp_path, "authored-control.sqlite")
    monkeypatch.setattr("kir.geometry_materialization.mep_fields",
                        lambda operation: {})
    with pytest.raises(FixError) as raised:
        propose_fix(scene, report, hit.finding_id, move=run, rebuild=_rebuild())
    text = str(raised.value)
    assert "parameterised otherwise" in text, text
    assert "repair_profile_unsupported" not in text, text


def test_a_level_authored_run_is_refused_by_category_without_inventing_a_slope(tmp_path):
    """Discriminating power on a live scene: a level run has NO
    number."""
    level = dict(AUTHORED_DUCT, p1_mm=[RUN[1][0], RUN[1][1], RUN[0][2]])
    scene, report, hit, run = _authored_scene(tmp_path, "authored-level.sqlite", level)
    with pytest.raises(FixError) as raised:
        propose_fix(scene, report, hit.finding_id, move=run, rebuild=_rebuild())
    code = _refusal_code(str(raised.value))
    assert code == "repair_profile_unsupported:mep_category:OST_DuctCurves", code
    # There is no number in the CODE: no slope is invented for a level
    # run.
    assert "mep_axis_slope" not in code, code
