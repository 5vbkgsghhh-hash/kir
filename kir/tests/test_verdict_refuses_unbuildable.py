"""A verdict must not dare judge the fitness of what the compiler will not take.

THE DEFECT FOR WHICH THIS FILE EXISTS (measured 2026-08-04, live A/B).
`check_ops` judged the fitness of a program where `create_stairs` stood
next to neighbors, and printed a verdict — whereas `plan_program` rejected
the very same program with `KIR-L002`. The model got TWO green lights and
a wall: `preview()` drew it, `design_check()` handed down a verdict, and
the compiler refused. This is exactly the "two signatures for one
building" against which the whole compiler is typed, and our own verdict
was one of those signatures.

WHY THIS IS NOT A FINDING BUT A DOOR'S REFUSAL. A verdict's finding says
"the building is bad" — it is fixed by changing the building. Here the
building can be flawless: it is the PROGRAM that is unbuildable as a
unit, and this is fixed by splitting it into a batch. Conflating the two
would send the author looking for a nonexistent flaw in the design.

THIS FILE'S BOUNDARY. It checks precisely the law of form (`spec.SOLO_OPS`),
not whether the verdict door has become the compiler's frontend:
`plan_program` also refuses for reasons that have nothing to do with
fitness (an unknown field, budget), and dragging those into the verdict
would substitute the question "is this a house" with the question "does
this compile."
"""
from __future__ import annotations

import os

# Set BEFORE importing the verdict: the flag is read at build time, and a
# module-level `skipif` here has already stepped on this rake before — in
# the shared run the tests were silently skipped.
os.environ.setdefault("KUKAI_CHECKER_V2", "1")

import pytest  # noqa: E402

from kir import compiler, spec  # noqa: E402
from kir.design_check import (
    PROGRAM_NOT_BUILDABLE,
    ProgramNotBuildableError,
    VerdictInputError,
    check_bundle,
    check_ops,
)




_LEVELS = [
    {"op": "create_level", "id": "L1", "name": "Этаж 1", "elev_mm": 0},
    {"op": "create_level", "id": "L2", "name": "Этаж 2", "elev_mm": 4200},
]
_WALL = {"op": "create_wall", "id": "W1", "p0_mm": [0, 0], "p1_mm": [8000, 0],
         "height_mm": 4200, "level": {"by": "ref", "value": "L1"}}
_STAIRS = {"op": "create_stairs", "id": "S1",
           "p0_mm": [1000, 1000], "p1_mm": [1000, 7000],
           "base_level": {"by": "name", "value": "Этаж 1"},
           "top_level": {"by": "name", "value": "Этаж 2"},
           "width_mm": 1200}


def _illegal() -> dict:
    return {"ir_version": "1.0", "ops": [*_LEVELS, _WALL, _STAIRS]}


def test_the_compiler_really_refuses_this_program():
    """The test's foundation. If the compiler ever stops refusing, the
    verdict has no reason to refuse either — and this file must fail first,
    not silently guard a retired rule."""
    with pytest.raises(Exception) as excinfo:
        compiler.plan_program(_illegal(), bulk=True)
    assert "KIR-L002" in str(excinfo.value)


def test_verdict_refuses_what_the_compiler_will_not_take():
    with pytest.raises(ProgramNotBuildableError) as excinfo:
        check_ops(_illegal(), building_id="непостроимая")
    assert ProgramNotBuildableError.code == PROGRAM_NOT_BUILDABLE


def test_the_refusal_names_the_next_move_not_only_the_diagnosis():
    """The genre's bar — `KIR-L001`: the law is named, the culprit is named,
    the move is named.

    A refusal that names only the diagnosis leaves the model in the same
    place: it already knows something is wrong — it needs to know what to
    do next.
    """
    with pytest.raises(ProgramNotBuildableError) as excinfo:
        check_ops(_illegal(), building_id="непостроимая")
    text = str(excinfo.value)
    assert "KIR-L002" in text                 # the law is named
    assert "create_stairs" in text            # the culprit is named
    assert "ПАЧКУ" in text
    # THE MOVE IS NAMED BY A NAME THE MODEL HAS. The first edition sent it
    # to `check_bundle` — a door's name from OUTSIDE; from inside the
    # sandbox it does not exist at all (`NameError`). A refusal that names a
    # nonexistent move spends the model's move checking our own typo.
    assert "design_check([" in text
    assert "check_bundle" not in text


def test_the_named_next_move_exists_in_the_model_language():
    """A guard against repeating the same typo: the name from the refusal
    must be in the sandbox's own namespace, not only in our module."""
    from kir.course import SANDBOX_NAMES

    with pytest.raises(ProgramNotBuildableError) as excinfo:
        check_ops(_illegal(), building_id="непостроимая")
    named = [n for n in SANDBOX_NAMES if f"{n}(" in str(excinfo.value)]
    assert named, ("отказ не назвал НИ ОДНОГО имени, доступного модели: "
                   f"{sorted(SANDBOX_NAMES)}")


def test_one_catch_point_for_the_whole_door():
    """The generic catch must also catch this refusal — otherwise a new
    kind silently flies past the old `except`, and a traceback escapes
    outward instead of the reason."""
    with pytest.raises(VerdictInputError):
        check_ops(_illegal(), building_id="непостроимая")


def test_the_same_ops_are_legal_as_a_bundle():
    """The batch's meaning: the same set, broken up into links, IS legitimate.

    Without this assertion, the gate would not be a law but a ban on
    staircases.
    """
    verdict = check_bundle(
        [{"ir_version": "1.0", "ops": [*_LEVELS, _WALL]},
         {"ir_version": "1.0", "ops": [_STAIRS]}],
        building_id="пачка")
    assert verdict is not None


def test_a_lone_solo_op_is_not_refused():
    """A single `create_stairs` is a legitimate program, and the door must
    accept it.

    The threshold is precisely "has neighbors," not "has a solo op": to
    confuse the two would mean banning the only form in which a staircase
    can be expressed at all.
    """
    assert check_ops({"ir_version": "1.0", "ops": [_STAIRS]},
                     building_id="одна лестница") is not None


def test_the_gate_reads_the_registry_not_its_own_list(monkeypatch):
    """There is one judge. This test having its own list of solo ops would
    make it a FOURTH one (after the plan, the emitter, and the registry),
    and it would diverge from the rest at the very next new op.

    THE FIRST EDITION OF THIS TEST WAS VACUOUS AND WAS CAUGHT BY REVIEW: it
    asserted `"create_stairs" in spec.SOLO_OPS` — a fact ABOUT THE REGISTRY,
    unrelated to the gate. The mutation "the gate keeps its own list" left
    all seven tests green. What must be checked is not what lies in the
    registry, but whether the gate READS IT: we add to the registry an op
    that cannot be in any hardcoded list, and require the gate to see it.
    """
    monkeypatch.setattr(
        spec, "SOLO_OPS", frozenset({*spec.SOLO_OPS, "create_wall"}))
    with pytest.raises(ProgramNotBuildableError) as excinfo:
        check_ops({"ir_version": "1.0", "ops": [*_LEVELS, _WALL]},
                  building_id="реестр расширен")
    assert "create_wall" in str(excinfo.value)


def test_a_bundle_whose_own_link_is_unbuildable_is_refused(monkeypatch):
    """The law is checked LINK BY LINK — and this assertion had not been
    protected by anything until now.

    Review showed: strip the link check out of
    `spatial_model_from_bundle` entirely — and all seven tests stay green,
    because none of them feeds in a batch of which ONE LINK ITSELF is
    unbuildable. That edit's longest comment explained precisely this
    check, and only honest word held it in place.
    """
    seen: list[str] = []
    monkeypatch.setattr(spec, "SOLO_OPS",
                        frozenset({*spec.SOLO_OPS, "create_wall"}))
    bundle = [
        {"ir_version": "1.0", "ops": [*_LEVELS, _WALL]},   # the link is ILLEGITIMATE
        {"ir_version": "1.0", "ops": [_STAIRS]},
    ]
    with pytest.raises(ProgramNotBuildableError) as excinfo:
        check_bundle(bundle, building_id="пачка с больным звеном")
    text = str(excinfo.value)
    seen.append(text)
    # It names PRECISELY THE LINK, not "the batch is bad": the author is
    # fixing one program, and without the number would have had to find it
    # by trial.
    assert "звено пачки p1" in text, text


def test_a_healthy_bundle_survives_the_per_link_check():
    """The flip side: the link-by-link check must not forbid the batch itself.

    Without this assertion, the previous test could be "fixed" by refusing
    any batch with a solo op — that is, by banning the one form for which
    the batch was introduced at all.
    """
    verdict = check_bundle(
        [{"ir_version": "1.0", "ops": [*_LEVELS, _WALL]},
         {"ir_version": "1.0", "ops": [_STAIRS]}],
        building_id="здоровая пачка")
    assert verdict is not None
