"""The source language must be THE SAME language, not merely resemble it.

The python-front's danger is exactly one thing, and it is not about convenience: it looks like a language
but is not one. The moment it acquires ITS OWN name, ITS OWN default, or ITS OWN
check, the program assembled by python stops being the program that
would have been written by hand. From the outside this is indistinguishable from success: it compiles,
it runs, the witness is green — but the proof is already about something else.

That is why the file begins with REFUTING tests, and the first of them is the
strongest: a program assembled by the DSL is required to match the ALREADY-COMMITTED
golden program byte for byte and match it on `plan_digest`. Not "similar,"
not "compiles to the same C#" — THE SAME ONE.

The measurement this file caught (03.08.2026): a python-front that writes a
registry default into the program changes `plan_digest` (2df7a3bc… versus
eb267955…) and swaps `FieldOrigin.REGISTRY_DEFAULT` for `EXPLICIT`, that is,
it erases the provenance. See `test_an_omitted_registry_default_keeps_its_provenance`.
"""
from __future__ import annotations

import importlib
import inspect
import json
import os
import tempfile

import pytest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_test_queue.jsonl"))

from kir import dsl, sdk, spec  # noqa: E402
from kir.compiler import (  # noqa: E402
    BUDGET_INTERNAL_BULK, MAX_BULK_OPS, MAX_OPS_PER_PROGRAM, plan_program,
)
from kir.diag import KirRefusal  # noqa: E402
from kir.midend import FieldOrigin  # noqa: E402
from kir.tests.test_golden import PROGRAMS as GOLDEN  # noqa: E402
#: Samples by parameter KIND live in `test_sdk` and are guarded there too ("a new
#: parameter kind without a sample" fails the build). A second such table must not be set up —
#: it would drift apart on exactly a new kind. Here there are only ADDITIONS: the shared table
#: deliberately gives degenerate geometry (p0 == p1), while this file needs
#: a program that runs all the way to the end of the plan.
from kir.tests.test_sdk import _SAMPLES, _sample  # noqa: E402

ALL_OPS = sorted(spec.OPS)
REFERENCEABLE = sorted(n for n, o in spec.OPS.items() if o.result.referenceable)
UNREFERENCEABLE = sorted(n for n, o in spec.OPS.items()
                         if not o.result.referenceable)

#: Non-degenerate values where the shared table gives degenerate ones.
_BY_PARAM: dict[str, object] = {
    "p1_mm": None,          # filled in by kind below (2D/3D)
    "delta_mm": [100.0, 0.0, 0.0],
    "outline": [[0.0, 0.0], [6000.0, 0.0], [6000.0, 4000.0], [0.0, 4000.0]],
}

#: Fields beyond the required ones, without which the op makes no sense as a program.
#: Every line is a NAMED reason, not "so the test goes green."
_EXTRA: dict[str, dict] = {
    # place_family: the position is given by EITHER a point OR a curve, and "neither
    # one nor the other" is a typed refusal KIR-P007, not a JSON shape issue.
    "place_family": {"xyz": [0.0, 0.0, 0.0], "level": "Этаж 1"},
    # create_ceiling (09.08): the shape is given by EITHER the straight polyline `outline`
    # OR the sketch `contour`, and "neither one nor the other" is the same typed
    # KIR-P007. The registry cannot express mutual requiredness, so
    # neither of the two fields is marked required, and the corpus needs an explicit
    # choice — exactly like place_family above.
    "create_ceiling": {"outline": [[0.0, 0.0], [6000.0, 0.0],
                                   [6000.0, 4000.0], [0.0, 4000.0]]},
    # create_stairs (09.08): the flight is given by EITHER straight ends OR
    # a `spiral`, and "neither one nor the other" is the same typed
    # KIR-P007. Neither field is marked required precisely because
    # the requiredness is MUTUAL, and the corpus needs an explicit choice.
    "create_stairs": {"p0_mm": [0.0, 0.0], "p1_mm": [5000.0, 0.0]},
    # create_extrusion_roof (09.08): `start_mm` and `end_mm` are not two
    # independent numbers, but the ENDS OF A SEGMENT along the working plane's normal.
    # The shared sample table gives the `num` kind the same value both times, meaning
    # a move of ZERO length, and the compiler legitimately refuses with KIR-T002. The reason
    # is the same one `_BY_PARAM` exists for at all: a degenerate sample
    # tests something other than what was intended.
    "create_extrusion_roof": {"start_mm": 0.0, "end_mm": 12000.0},
    # create_face_wall (10.08): `face_normal` is of kind `pt_xyz`, but is NOT a point:
    # it is a DIRECTION, while the shared sample for the kind gives a zero vector, meaning
    # degeneracy BY DEFINITION, and the compiler legitimately refuses with KIR-T002.
    # The reason is the same as for `create_extrusion_roof` one line above: a sample
    # degenerate for the parameter's MEANING tests something other than what was intended. The tilt
    # is not decoration here — Revit builds a face-hosted wall ONLY on a sloped face
    # (its own rule: the normal is neither vertical nor horizontal).
    "create_face_wall": {"face_normal": [0.6, 0.0, 0.8]},
}


def _args_for(ospec: spec.OpSpec) -> dict:
    args = {}
    for p in ospec.params:
        if not p.required:
            continue
        if p.name == "p1_mm":
            args[p.name] = ([6000.0, 0.0] if p.kind == "pt_xy"
                            else [6000.0, 0.0, 0.0])
        elif p.name in _BY_PARAM and _BY_PARAM[p.name] is not None:
            args[p.name] = _BY_PARAM[p.name]
        else:
            # ONE SOURCE FOR THE SAMPLE (09.08): `_sample` knows about both the enum and the
            # bounds of the parameter ITSELF. A separate enum branch here was a second
            # home for the same table and, more importantly, could not clip a number to its
            # bounds — on `sweep_deg` (1..360) the corpus would get 1000.0 and
            # blame the op for "not building acceptable JSON."
            args[p.name] = _sample(p)
    args.update(_EXTRA.get(ospec.name, {}))
    return args


@pytest.fixture(autouse=True)
def _fresh_program():
    """The accumulation is IMPLICIT, meaning leakage between tests is a real risk, and
    closing it is the suite's own job, not the run order's."""
    dsl.reset()
    yield
    dsl.reset()


# ════════════════════════════════════════════════ REFUTING

def _canon(program: dict) -> str:
    return json.dumps(program, sort_keys=True, ensure_ascii=False)


def test_a_dsl_program_is_the_committed_golden_byte_for_byte():
    """THE STRONGEST TEST IN THE FILE.

    `full_house_v1` is not something this test made up: it is the golden program from
    `test_golden.PROGRAMS`, which has a reviewed C# snapshot. Eight
    ops, three kinds of selector, references to a level and to a wall. The DSL must produce
    THE SAME ONE — the same JSON and the same identity of proof.
    """
    hand = GOLDEN["full_house_v1"]

    p = dsl.program(intent="полный дом v1")
    L1 = dsl.create_level(elev_mm=0, name="КИР-1", id="L1")
    W1 = dsl.create_wall(p0_mm=[0, 0], p1_mm=[8000, 0], level=L1, id="W1")
    dsl.create_window(host=W1, offset_mm=2000, sill_mm=900, id="Win1")
    dsl.create_door(host=W1, offset_mm=5000, id="D1")
    dsl.create_floor(outline=[[0, 0], [8000, 0], [8000, 6000], [0, 6000]],
                     level=L1, id="F1")
    dsl.create_column(xy=[4000, 3000], level=L1, id="C1")
    dsl.create_room(xy=[4000, 3000], level=L1, name="Зал", id="R1")
    dsl.place_family(xyz=[2000, 2000, 0], level=L1, id="T1")
    got = p.build()

    assert _canon(got) == _canon(hand), "DSL собрал НЕ ту программу"
    assert (plan_program(got).plan_digest
            == plan_program(hand).plan_digest), "личность доказательства разная"


def test_a_handle_of_an_unreferenceable_op_cannot_pass_as_a_reference():
    """Every op has a handle, not every op has a REFERENCE.

    `ResultSpec` deliberately separates two facts: a group and a deleted
    element have identity evidence, but no valid forward reference.
    Python must refuse RIGHT AT the call site and name the reason from the registry — otherwise
    the author finds out about it layers below, from KIR-L003, where it is no longer visible which
    script line is at fault.
    """
    wall = dsl.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], level="Этаж 1")
    line = dsl.create_curtain_grid_line(host=wall, direction="u",
                                        position_mm=[3000, 0, 0])
    assert isinstance(line, dsl.Handle)
    assert line.referenceable is False

    with pytest.raises(dsl.DslRefusal) as got:
        dsl.create_window(host=line, offset_mm=1000)
    message = got.value.diagnostics[0].message_ru
    assert "create_curtain_grid_line" in message
    assert "reference_kind" in message


@pytest.mark.parametrize("name", UNREFERENCEABLE)
def test_every_unreferenceable_op_says_so_and_says_why(name):
    """Parameterization by the REGISTRY: a new op without a `reference_kind` brings its own
    test with it, and "forgot about one more" stops being a possible state."""
    handle = dsl.Handle("x1", name, spec.OPS[name])
    assert handle.referenceable is False
    with pytest.raises(dsl.DslRefusal) as got:
        handle.as_selector()
    assert name in got.value.diagnostics[0].message_ru


def test_a_handle_refuses_indexing_and_names_the_two_honest_forms():
    """MEASUREMENT 04.08, the second most frequent class (6 of 27). Both runs of the weak
    model STARTED with `query_types(...)[0]['id']` and lost two turns each.

    There is nothing to index BY CONSTRUCTION: at the moment the program is written, the reading
    op's result does not exist yet — it will appear in Revit. So "make it
    work" would mean returning "whatever comes first," that is, silently choosing
    for the author. What remains is the second path: name the correct form VERBATIM.
    """
    handle = dsl.query_types(pool="wall_types")
    for attempt in (lambda: handle[0], lambda: list(handle), lambda: len(handle)):
        with pytest.raises(dsl.DslRefusal) as got:
            attempt()
        text = got.value.diagnostics[0].message_ru
        assert "query_types" in text
        assert "СЛЕДУЮЩИЙ ХОД" in text
        assert "DEFAULT" in text and "КВИТАНЦИИ" in text, \
            "названа должна быть КАЖДАЯ честная форма, иначе совет — половина"


def test_a_handle_stays_truthy_so_the_fix_does_not_become_a_new_trap():
    """`if wall_types else None` is what the weak model wrote on its FIRST turn (wB t01).

    Truthiness without `__bool__` would be computed via `__len__`, that is, as a refusal:
    fixing one class would introduce a new one. The handle always exists — it is
    an address, not a result.
    """
    assert bool(dsl.query_types(pool="wall_types")) is True
    assert bool(dsl.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0],
                                level="Этаж 1")) is True


def test_a_writing_handle_says_it_is_ONE_handle_not_a_list():
    """A writing op has a different reason, and the refusal must state ITS reason, not
    a generic one: there is one handle, and the author assembles the list in python themselves."""
    wall = dsl.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], level="Этаж 1")
    with pytest.raises(dsl.DslRefusal) as got:
        wall[0]
    text = got.value.diagnostics[0].message_ru
    assert "ОДНУ ручку" in text
    assert "СЛЕДУЮЩИЙ ХОД" in text


def test_a_handle_of_the_WRONG_KIND_is_refused_by_the_compilers_typed_law():
    """🔴 THE LAW IS THE SAME, THE GUARD MOVED AND GOT STRONGER (23.08.2026).

    WHAT STOOD HERE AND WHY IT WAS CORRECT. Measurement of 04.08 (wB t05/t11):
    the `create_type` handle in the `create_wall.type` slot was rejected by an EARLY dsl
    hint, because the slot had an EMPTY `ref_kinds` — meaning the slot accepted
    no in-program references AT ALL, and the hint "match by name" was
    the only way out.

    WHAT CHANGED. On 23.08 the slot gained the `wall_type` kind: `create_wall_type`
    creates a type IN THIS SAME PROGRAM, and referencing it is the only working
    way (grounding resolves catalog names against a snapshot taken BEFORE the
    run, and the created type is not in it by construction).

    So an "empty ref_kinds" is no longer a discriminator, and the early hint is silent.
    But the LAW is intact and became MORE PRECISE: a handle of the WRONG kind
    (`create_type` gives a `FamilySymbol`, while the slot expects `wall_type`) is rejected by the compiler
    with the typed `KIR-L004` — a check of KIND, not an emptiness heuristic.
    A handle of ITS OWN kind it lets through, and that is exactly what the kind exists for.
    """
    from kir.compiler import _parse_and_check
    from kir.diag import KirRefusal

    wrong = {"ir_version": "1.0", "ops": [
        {"op": "create_type", "id": "T1", "category": "architectural",
         "new_name": "Наружная 300", "width_mm": 300,
         "source_type": {"by": "name", "value": "Обобщённая - 200 мм"}},
        {"op": "create_wall", "id": "W1", "p0_mm": [0, 0], "p1_mm": [6000, 0],
         "height_mm": 3000, "level": {"by": "element_id", "value": 42},
         "type": {"by": "ref", "value": "T1"}}]}
    with pytest.raises(KirRefusal) as got:
        _parse_and_check(wrong)
    assert [d.code for d in got.value.diagnostics] == ["KIR-L004"]

    right = {"ir_version": "1.0", "ops": [
        {"op": "create_wall_type", "id": "WT1",
         "source_type": {"by": "name", "value": "Обобщённая - 200 мм"},
         "new_name": "Наружная 300",
         "layers": [{"width_mm": 300.0, "function": "Structure"}]},
        {"op": "create_wall", "id": "W1", "p0_mm": [0, 0], "p1_mm": [6000, 0],
         "height_mm": 3000, "level": {"by": "element_id", "value": 42},
         "type": {"by": "ref", "value": "WT1"}}]}
    _parse_and_check(right)


def test_a_handle_in_a_solo_ops_slot_names_the_BUNDLE_not_just_the_name():
    """For `create_stairs`, the answer "matched by name" is incomplete: the op is SOLO (KIR-L002),
    meaning the level physically cannot lie in this same program. The refusal must
    name the BATCH FORM — otherwise the hint leads into the same pit again, just one turn later."""
    level = dsl.create_level(elev_mm=0, name="Этаж 1")
    with pytest.raises(dsl.DslRefusal) as got:
        dsl.create_stairs(p0_mm=[0, 0], p1_mm=[0, 4000], base_level=level,
                          top_level="Этаж 2")
    text = got.value.diagnostics[0].message_ru
    assert "ПАЧКА" in text
    assert "KIR-L002" in text
    assert "design_check" in text, "вердикт у пачки — часть следующего хода"


def test_the_early_refusal_matches_the_compilers_law_not_our_own():
    """An early refusal must REPEAT the compiler's law, not invent its own:
    the same program, written by hand with a reference to a non-relocatable op,
    must get KIR-L003."""
    by_hand = {
        "ir_version": "1.0",
        "ops": [
            {"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
             "p1_mm": [6000, 0], "level": {"by": "name", "value": "Этаж 1"}},
            {"op": "create_curtain_grid_line", "id": "GL1",
             "host": {"by": "ref", "value": "W1"}, "direction": "u",
             "position_mm": [3000, 0, 0]},
            {"op": "create_window", "id": "Win1",
             "host": {"by": "ref", "value": "GL1"}, "offset_mm": 1000},
        ],
    }
    with pytest.raises(KirRefusal) as got:
        plan_program(by_hand)
    assert any(d.code == "KIR-L003" for d in got.value.diagnostics)


def test_an_unknown_parameter_fails_at_the_call_site_and_names_it():
    """The refusal comes from the SIGNATURE, that is, from the registry, and names the field.

    THE REFUSAL TYPE WAS CHANGED DELIBERATELY (04.08): it used to be a bare python `TypeError`
    from `Signature.bind`, and became a typed `DslRefusal` with code KIR-P003.
    The reason is a measurement: 13 of 27 refusals from the weak model on a live task were
    this very `TypeError`, and it named ONE slot out of six, saying not a
    word about the rest. The model was learning the signature one bit per turn.
    """
    with pytest.raises(dsl.DslRefusal) as got:
        dsl.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], level="Этаж 1",
                        heigth_mm=3000)                    # author's typo
    diagnostic = got.value.diagnostics[0]
    assert diagnostic.code == "KIR-P003"
    assert diagnostic.field_name == "heigth_mm"
    assert "heigth_mm" in str(got.value)
    assert dsl.ops() == [], "отказавший вызов не должен ничего оставить"


def test_a_missing_required_parameter_fails_at_the_call_site():
    with pytest.raises(dsl.DslRefusal) as got:
        dsl.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0])
    diagnostic = got.value.diagnostics[0]
    assert diagnostic.code == "KIR-P005"
    assert diagnostic.field_name == "level"
    assert "level" in str(got.value)


def test_the_arity_refusal_names_the_WHOLE_call_form_not_one_slot():
    """MEASUREMENT 04.08, the most frequent class of surface refusal (13 of 27).

    The weak model wrote `create_stairs(..., width=, tread=, riser=)` and
    got «unexpected keyword argument 'width'» — ONE name per turn. Three
    extra fields would have cost three turns. The refusal must close them all at once, so
    the test requires: ALL extra slots are named, ALL of the op's slots are listed
    (required and not), and the NEXT TURN is named — the reference law KIR-L001.
    """
    with pytest.raises(dsl.DslRefusal) as got:
        dsl.create_stairs(p0_mm=[0, 0], p1_mm=[0, 4000], base_level="Э1",
                          top_level="Э2", width=1200, tread=280, riser=170)
    text = str(got.value)
    for wrong in ("width", "tread", "riser"):
        assert wrong in text, f"{wrong} не назван — модель узнает о нём ходом позже"
    for slot in ("p0_mm", "p1_mm", "base_level", "top_level", "width_mm"):
        assert slot in text, f"{slot} не перечислен — форма вызова неполная"
    assert "СЛЕДУЮЩИЙ ХОД" in text
    assert dsl.ops() == []


@pytest.mark.parametrize("name", sorted(spec.OPS))
def test_every_op_refuses_a_bogus_slot_typed_and_with_a_next_move(name):
    """PARAMETERIZATION BY THE REGISTRY: a new op brings its own test.

    An instrument covering PART of the range is more dangerous than a missing one — this package
    paid for that on 03.08 (the matrix asked about 3 Revit versions out of 6). So the law
    "the refusal is typed and names the next turn" is checked not on the three ops the
    measurement started with, but on ALL of them, and the call form is printed for each:
    `_call_form` failing on a rare op would mean a refusal worse than the original one.
    """
    dsl.reset()
    with pytest.raises(dsl.DslRefusal) as got:
        getattr(dsl, name)(__nonexistent_slot__=1)
    text = str(got.value)
    assert got.value.diagnostics[0].code == "KIR-P003"
    assert name in text, "отказ обязан назвать ОП, иначе ремонт уйдёт не туда"
    assert "СЛЕДУЮЩИЙ ХОД" in text
    assert dsl.ops() == []


def test_the_missing_arity_refusal_shows_enum_choices_it_could_not_guess():
    """`create_railing(path=…, level=…)` -> «missing 'variety'». By itself
    this is a dead end: `variety` is an enum, and there was no way to learn its values from the refusal.
    Now the refusal prints them together with the form."""
    with pytest.raises(dsl.DslRefusal) as got:
        dsl.create_railing(path=[[0, 0, 0], [1000, 0, 0]], level="Э1")
    text = str(got.value)
    assert "variety" in text
    assert "path" in text and "hosted" in text, "значения enum не названы"
    assert "СЛЕДУЮЩИЙ ХОД" in text


def test_the_order_of_ops_is_preserved():
    """Order is part of the program: a reference must point BACKWARD, and the compiler's
    DAG is computed exactly by order."""
    for i in range(6):
        dsl.create_level(elev_mm=i * 3000, name=f"Э{i}")
    assert [o["name"] for o in dsl.ops()] == [f"Э{i}" for i in range(6)]
    assert [o["id"] for o in dsl.ops()] == [f"level{i}" for i in range(1, 7)]


def test_a_fresh_import_carries_no_state_of_the_previous_program():
    """ISOLATION. The accumulation is module-level, so "the previous script appended a
    wall to mine" is not a theory but exactly what makes module-level state dangerous."""
    dsl.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], level="Этаж 1")
    assert len(dsl.ops()) == 1
    reloaded = importlib.reload(dsl)
    try:
        assert reloaded.ops() == []
        assert reloaded.current().intent is None
    finally:
        importlib.reload(dsl)
        _restore_the_reexporters()


def _restore_the_reexporters() -> None:
    """🔴 RELOADING `dsl` POISONS EVERYONE WHO DID `import *` EARLIER.

    MEASUREMENT OF 17.08.2026, AND IT COST 18 RED IN THE WIDE SUITE. Narrow, these files
    pass; wide, they fail with `TypeError: Object of type _RegistryDefault is not
    JSON serializable` — far from the cause, in a circular print run.

    The mechanism. `kir/course/language.py:54` does `from kir.dsl import
    *` and in its own docstring says "THE SAME objects." After
    `importlib.reload(dsl)`, the `dsl` module dict is rewritten IN PLACE:
    a NEW `_RegistryDefault` class appears in it. But the operation functions,
    captured by `language` BEFORE the reload, carry defaults in their signatures —
    instances of the OLD class. The `isinstance(value, _RegistryDefault)` check
    in `dsl.op_fn` (`dsl.py:843`) no longer recognizes them, the registry sentinel rides off
    into the program, and `json.dumps` blows up two layers away.

    Control in both directions, run by hand on 17.08:

        test_course + test_dsl + test_program_source(+corpus)  ->  15 failed
        the same WITHOUT test_dsl                               ->  71 passed

    Order is load-bearing here: `language` is restored AFTER the second
    `reload(dsl)`, otherwise it would capture the intermediate state. And this is the same
    kind of defect the canon already recorded on a different case: a `finally`
    that restored ITS OWN MEMORY instead of the FOUND state — only here
    HALF of the shared state was restored, and the other half stayed broken.

    The list of those who do `import *` from `dsl` is CLOSED BUT NOT COMPLETE: empty
    here means "we don't know," not "there are none." A second one shows up — add it here.
    """

    from kir.course import language

    importlib.reload(language)


def test_the_bulk_budget_refuses_typed_and_names_the_next_work():
    """THE LIMIT is the internal bulk budget. The refusal must name EXACTLY this one
    (otherwise the fix goes to the wrong place — measurement of 30.07) and say WHAT KIND OF
    LIMIT this is.

    🔴 THE ASSERTION CHANGED ON 21.08.2026 ALONG WITH THE WORLD. The test used to guard the words
    "direct-turn chunking is not written yet" and a reference to `materialize` as
    the only place where chunking exists. Both stopped being true:
    direct-turn chunking is now wired to the prod door, and a refusal that kept
    advising "cut the program yourself, in python" would send the model to do by hand
    what the door does for it.

    What is guarded now: the refusal names ITS OWN budget, says that it is a defense
    against a runaway, NOT a transport limit, and does not advise cutting.
    """
    for _ in range(MAX_BULK_OPS):
        dsl.create_level(elev_mm=0)
    assert len(dsl.ops()) == MAX_BULK_OPS

    with pytest.raises(dsl.DslRefusal) as got:
        dsl.create_level(elev_mm=0)
    diag = got.value.diagnostics[0]
    assert diag.code == "KIR-L001"
    assert diag.got == MAX_BULK_OPS + 1
    assert BUDGET_INTERNAL_BULK in diag.message_ru
    assert "чанкование" in diag.message_ru
    assert "РУНАВЭЯ" in diag.message_ru
    assert "резать её в питоне больше НЕ НАДО" in diag.message_ru
    assert len(dsl.ops()) == MAX_BULK_OPS, "отказ не должен ничего дописать"


def test_the_script_door_keeps_headroom_and_the_refusal_names_which_budget():
    """🔴 THE EQUALITY WAS UNDONE ON THE SAME DAY (`e6f47d12`), the assertion is brought
    in line with the decision in force as of 19.08.2026.

    On 18.08 the budgets were equalized at 1000 — and rolled back the same day: "1000
    everywhere" zeroed out the scripted door's HEADROOM, and its whole value lies in that headroom. The
    argument is recorded in the commit: "a script that can do exactly twenty operations is strictly worse
    than twenty written by hand." The position in force:

        authorial (the model writes by hand into JSON)      1000
        internal = builder (rebuild, script)                10000

    What stays load-bearing is the same as before, and it matters more than the number: the refusal must
    NAME which budget is exhausted. Different readers read it — the model and the rebuild
    driver — and their next moves differ."""
    assert MAX_BULK_OPS > MAX_OPS_PER_PROGRAM, (
        "запас скриптовой двери обнулён: у program_py вся ценность в том, что "
        "построитель шире, чем ручное перечисление")
    for _ in range(MAX_OPS_PER_PROGRAM):
        dsl.create_level(elev_mm=0)
    program = dsl.build()
    with pytest.raises(KirRefusal) as authored:
        plan_program({**program, "ops": program["ops"] + program["ops"][:1]},
                     bulk=False)
    assert any(d.code == "KIR-L001" for d in authored.value.diagnostics)


# ════════════════════════════════════════ THE SURFACE IS BORN FROM THE REGISTRY

@pytest.mark.parametrize("name", ALL_OPS)
def test_every_op_of_the_registry_has_a_function(name):
    fn = getattr(dsl, name, None)
    assert callable(fn), f"нет функции для {name}"
    assert fn.op_spec is spec.OPS[name], "функция держит ЧУЖУЮ спецификацию"


def test_there_are_exactly_as_many_functions_as_ops():
    assert set(dsl.OP_FUNCTIONS) == set(spec.OPS)
    assert dsl.op_names(writes=True) == sorted(
        n for n, o in spec.OPS.items() if o.writes_model)


@pytest.mark.parametrize("name", ALL_OPS)
def test_the_signature_never_drifts_from_the_paramspec(name):
    """Names and requiredness come from `ParamSpec`, and only from there. The registry
    interleaves required and optional ones, while python does not allow a parameter
    without a default to stand after a parameter with a default, so the order is compared
    WITHIN each group."""
    ospec = spec.OPS[name]
    sig = inspect.signature(getattr(dsl, name))
    got = [p for p in sig.parameters if p != "id"]
    want = ([p.name for p in ospec.params if p.required]
            + [p.name for p in ospec.params if not p.required])
    assert got == want
    assert "id" in sig.parameters, "у опа обязан быть адрес"


@pytest.mark.parametrize("name", ALL_OPS)
def test_registry_defaults_are_shown_in_the_signature(name):
    """The default is visible in `help`, even though it is not written into the JSON: the author must
    KNOW what they will get without looking into the registry."""
    sig = inspect.signature(getattr(dsl, name))
    for p in spec.OPS[name].params:
        if p.required or p.default is None:
            continue
        assert sig.parameters[p.name].default == p.default, p.name


def test_the_dsl_cannot_name_an_op_the_registry_does_not_have():
    assert not hasattr(dsl, "create_teleporter")


# ═══════════════════════════════════════════════════ INTROSPECTION

def test_the_signature_carries_the_real_bounds_of_the_registry():
    """«How the model learns about what it doesn't see» — the way native to python.
    The bounds are taken from `ParamSpec`, not rewritten into text."""
    text = str(inspect.signature(dsl.create_wall))
    assert "height_mm: mm 1..100000" in text
    assert "p0_mm: pt_xy" in text
    assert "level: sel: name|element_id|default|ref(level)" in text
    assert "enum{wall_centerline|" in text

    p = next(x for x in spec.OPS["create_wall"].params if x.name == "height_mm")
    assert f"{p.min_val:g}..{p.max_val:g}" in text


def test_a_write_target_slot_advertises_that_it_has_no_name_form():
    """`target_w` is a pinned id or a reference. The signature must
    SHOW this, otherwise the author learns the law only from a refusal."""
    text = str(inspect.signature(dsl.create_door))
    assert "host: target_w: element_id|ref(wall)" in text
    assert "name" not in text.split("host: target_w:")[1].split(",")[0]


@pytest.mark.parametrize("name", ALL_OPS)
def test_the_docstring_carries_the_post_of_the_op(name):
    """The postcondition is the op's contract. It must be IN THE DOCSTRING verbatim, not
    paraphrased: a paraphrase survives only until the first registry edit."""
    doc = getattr(dsl, name).__doc__
    assert spec.OPS[name].post in doc


@pytest.mark.parametrize("name", ALL_OPS)
def test_the_return_annotation_states_referenceability_truthfully(name):
    """THE SIGNATURE NAMES EXACTLY WHAT THE OP PRODUCES.

    On 24.08.2026 the law gained a third outcome. For `create_wall_type`, the result
    kind is decided by `host_kind`, and a signature naming ONE kind out of four
    would be a lie ahead of the compiler: python would promise "a wall" where the call
    actually gives a roof type. So for such an op what is checked is NOT one kind, but completeness:
    the deciding parameter and EVERY one of its values are named. Nothing weaker will do —
    a kind added to the table and forgotten in the signature would pass silently.
    """
    ospec = spec.OPS[name]
    ret = str(inspect.signature(getattr(dsl, name)).return_annotation)
    if ospec.result_by_param is not None:
        pname, table = ospec.result_by_param
        assert f"род решает {pname}" in ret
        for value, rspec in table.items():
            assert f"{value}->«{rspec.reference_kind.value}»" in ret
    elif ospec.result.referenceable:
        assert f"ссылка «{ospec.result.reference_kind.value}»" in ret
    else:
        assert "НЕ ссылка" in ret


def test_the_docstring_carries_tolerances_and_grounding_pools():
    doc = dsl.create_wall.__doc__
    assert "endpoint_mm = 5" in doc            # из OpSpec.tolerances
    assert "пулу «levels»" in doc              # из OpSpec.grounded
    assert "wall_types" in doc


# ═══════════════════════════════════════════ HANDLES AND THE DEPENDENCY GRAPH

def test_a_handle_wires_the_dag_by_construction():
    """A reference is built by PASSING a handle, not an id string: the graph is correct by
    construction, because only an already-created op can be passed."""
    wall = dsl.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], level="Этаж 1")
    door = dsl.create_door(host=wall, offset_mm=3000)
    assert dsl.ops()[1]["host"] == {"by": "ref", "value": wall.id}
    assert door.reference_kind is spec.ReferenceKind.ELEMENT
    assert plan_program(dsl.build()) is not None


def test_auto_ids_are_deterministic_and_match_the_sdk_scheme():
    """The two python surfaces must hand out the SAME addresses, otherwise "the same
    program" stops being a checkable comparison."""
    for _ in range(3):
        dsl.create_wall(p0_mm=[0, 0], p1_mm=[1000, 0], level="Этаж 1")
    assert [o["id"] for o in dsl.ops()] == ["wall1", "wall2", "wall3"]

    p = sdk.program()
    for _ in range(3):
        p.add(sdk.create_wall([0, 0], [1000, 0], "Этаж 1"))
    assert [o["id"] for o in p.ops] == [o["id"] for o in dsl.ops()]


def test_an_explicit_id_is_never_overwritten_and_a_duplicate_is_refused():
    dsl.create_level(elev_mm=0, id="мой")
    assert dsl.ops()[0]["id"] == "мой"
    with pytest.raises(dsl.DslRefusal) as got:
        dsl.create_level(elev_mm=3000, id="мой")
    assert got.value.diagnostics[0].code == "KIR-P006"


def test_the_id_is_the_second_key_so_the_program_reads_by_eye():
    dsl.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], level="Этаж 1")
    assert list(dsl.ops()[0])[:2] == ["op", "id"]


def test_the_fields_follow_the_registry_order_not_the_signature_order():
    """The signature must put required parameters first (python), while JSON does not have to.
    The program is read with human eyes, and the order of its fields belongs to the registry."""
    dsl.create_floor(outline=[[0, 0], [6000, 0], [6000, 4000]], level="Этаж 1",
                     holes=[[[1000, 1000], [2000, 1000], [2000, 2000]]],
                     structural=True)
    got = [k for k in dsl.ops()[0] if k not in ("op", "id")]
    want = [p.name for p in spec.OPS["create_floor"].params if p.name in got]
    assert got == want


# ══════════════════════════════════════════ SELECTOR COERCION

def test_the_sugar_is_exactly_the_four_rules_and_nothing_more():
    wall = dsl.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], level="Этаж 1")
    dsl.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], level=42)
    dsl.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], level=dsl.DEFAULT)
    dsl.create_door(host=wall, offset_mm=1000)
    dsl.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0],
                    level={"by": "name", "value": "Этаж 1"})
    got = dsl.ops()
    assert got[0]["level"] == {"by": "name", "value": "Этаж 1"}
    assert got[1]["level"] == {"by": "element_id", "value": 42}
    assert got[2]["level"] == {"by": "default"}
    assert got[3]["host"] == {"by": "ref", "value": wall.id}
    assert got[4]["level"] == {"by": "name", "value": "Этаж 1"}


def test_an_omitted_selector_is_simply_absent():
    """«Omission -> the op's default rule» means the ABSENCE of the key: the resolution
    ladder is driven by `ground.py`, and a written-in `{"by":"default"}` is already a different
    assertion by the author."""
    dsl.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], level="Этаж 1")
    assert "type" not in dsl.ops()[0]


def test_a_string_in_a_write_target_is_refused_and_the_forms_are_named():
    """For `target_w`, the `by=name` form does NOT EXIST (`_target_w_ok`). Sugar
    that cannot be unambiguous is better not made at all — but it must
    refuse RIGHT HERE and name what the slot accepts."""
    with pytest.raises(dsl.DslRefusal) as got:
        dsl.create_door(host="Стена 1", offset_mm=1000)
    diag = got.value.diagnostics[0]
    assert diag.expected == ["element_id", "ref"]
    assert "by=name" in diag.message_ru
    assert any("element_id" in c for c in diag.candidates)


def test_a_bool_is_never_an_address():
    with pytest.raises(dsl.DslRefusal):
        dsl.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], level=True)


def test_a_list_slot_is_coerced_element_by_element():
    wall = dsl.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], level="Этаж 1")
    dsl.move_elements(targets=[42, wall], delta_mm=[100, 0, 0])
    assert dsl.ops()[1]["targets"] == [{"by": "element_id", "value": 42},
                                       {"by": "ref", "value": wall.id}]
    with pytest.raises(dsl.DslRefusal):
        dsl.move_elements(targets=42, delta_mm=[100, 0, 0])


def test_the_explicit_forms_stay_available_and_carry_disambiguate_by():
    """`disambiguate_by` is a narrowing that `ground.py` checks EVEN when there is
    a single candidate. Before this module, it could not be written from python
    any other way than as a hand-written dict."""
    dsl.create_pipe(p0_mm=[0, 0, 0], p1_mm=[3000, 0, 0], level="Этаж 1",
                    pipe_type=dsl.by_name(
                        "Стандарт",
                        disambiguate_by=dsl.disambiguate("Диаметр", 100)))
    assert dsl.ops()[0]["pipe_type"] == {
        "by": "name", "value": "Стандарт",
        "disambiguate_by": {"param": "Диаметр", "value": 100}}
    assert plan_program(dsl.build()) is not None

    assert dsl.by_element_id(7) == {"by": "element_id", "value": 7}
    assert dsl.by_default() == {"by": "default"}
    assert dsl.by_default(disambiguate_by=dsl.disambiguate("Ø", None)) == {
        "by": "default", "disambiguate_by": {"param": "Ø", "value": None}}


def test_family_type_is_available_and_its_legality_belongs_to_the_compiler():
    """The form is always built; WHERE it is legal is known by the compiler, and it alone
    knows it. A DSL that refused here on its own would become a second dialect."""
    catalog = dsl.family_type("OST_Furniture", "Стол офисный", "Стол 1200")
    dsl.place_family(xyz=[0, 0, 0], level="Этаж 1", symbol=catalog)
    assert plan_program(dsl.build()) is not None

    dsl.reset()
    dsl.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], level="Этаж 1",
                    type=catalog)
    with pytest.raises(KirRefusal) as got:
        plan_program(dsl.build())
    assert "family_type" in got.value.diagnostics[0].message_ru


@pytest.mark.parametrize("name", ALL_OPS)
def test_every_selector_slot_of_the_registry_has_named_forms(name):
    """A new kind of selector parameter must be deliberately sorted into forms,
    not slip through silently. The "selector or not" classification is taken from `sdk` —
    it is already guarded there."""
    ospec = spec.OPS[name]
    for p in ospec.params:
        if p.kind not in (sdk.SELECTOR_KINDS | sdk.SELECTOR_LIST_KINDS):
            continue
        forms = dsl.selector_forms(name, p.name)
        assert forms, f"{name}.{p.name}: формы не названы"
        assert ("ref" in forms) == bool(p.ref_kinds)


# ═══════════════════════════════ NO SEMANTICS OF ITS OWN

@pytest.mark.parametrize("name", ALL_OPS)
def test_every_op_builds_json_the_planner_accepts(name):
    """39 ops, 39 programs, not a single exception: everything the DSL produces
    goes through `plan_program` — the ONLY semantic entry point downward."""
    dsl.reset(allow_destructive=True)          # delete requires explicit consent
    getattr(dsl, name)(**_args_for(spec.OPS[name]))
    planned = plan_program(dsl.build(), bulk=True)
    assert planned.ops[0].op_name == name


def test_a_knowingly_bad_program_reaches_the_compiler_untouched():
    """The DSL does not refuse earlier or in its own way: a knowingly invalid value must
    reach the compiler and get ITS diagnostic."""
    dsl.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], level="Этаж 1",
                    height_mm=-5)
    assert dsl.ops()[0]["height_mm"] == -5
    with pytest.raises(KirRefusal) as got:
        plan_program(dsl.build())
    assert got.value.diagnostics[0].code == "KIR-T002"


def test_an_unknown_envelope_default_is_the_compilers_refusal_not_ours():
    dsl.envelope(defaults={"nonsense": "x"})
    dsl.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], level="Этаж 1")
    with pytest.raises(KirRefusal) as got:
        plan_program(dsl.build())
    assert any(d.field_name == "defaults" for d in got.value.diagnostics)


# ═══════════════════════════════════════════════════════ PROVENANCE

def test_an_omitted_registry_default_keeps_its_provenance():
    """MEASUREMENT OF 03.08, because of which a registry default is NOT written into the JSON.

    A written-in default and an omitted one are different programs to the compiler:
    the first has its field marked EXPLICIT, the second REGISTRY_DEFAULT, and their
    `plan_digest` DIFFERS. A python-front that writes in defaults thereby erases
    the provenance mechanism (`midend.FieldOrigin`) and changes the identity
    of the proof without changing anything in the building.
    """
    dsl.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], level="Этаж 1", id="W1")
    assert "height_mm" not in dsl.ops()[0]
    omitted = plan_program(dsl.build())
    assert dict(omitted.ops[0].provenance.field_origins)["height_mm"] \
        is FieldOrigin.REGISTRY_DEFAULT

    dsl.reset()
    dsl.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], level="Этаж 1", id="W1",
                    height_mm=spec.DEFAULTS["wall"]["height_mm"])
    explicit = plan_program(dsl.build())
    assert dict(explicit.ops[0].provenance.field_origins)["height_mm"] \
        is FieldOrigin.EXPLICIT
    assert omitted.plan_digest != explicit.plan_digest


# ══════════════════════════ THE TWO PYTHON SURFACES DO NOT DRIFT APART

def test_the_two_python_surfaces_name_the_same_registry():
    """`sdk.py` and `dsl.py` are both born from `spec.OPS`. As long as both are alive, their
    divergence is a real risk, and it must fail the build, not surface for the
    user."""
    assert set(dsl.OP_FUNCTIONS) == set(sdk.builders())
    for name in ALL_OPS:
        a = [p for p in inspect.signature(getattr(dsl, name)).parameters]
        b = [p for p in inspect.signature(getattr(sdk, name)).parameters]
        assert a == b, f"{name}: питон-поверхности разъехались"


def test_the_shared_facts_are_shared_by_reference_not_by_copy():
    assert dsl.OMIT is sdk.OMIT
    assert dsl.DEFAULT is sdk.DEFAULT
    assert dsl._plain is sdk._plain
    assert dsl._SELECTOR_KINDS == sdk.SELECTOR_KINDS
    assert dsl._SELECTOR_LIST_KINDS == sdk.SELECTOR_LIST_KINDS
    assert sdk.unclassified_kinds() == [], "вид параметра без классификации"


def test_a_ref_made_by_the_sdk_is_understood_here():
    """A script that mixes the two modules must not catch different references."""
    dsl.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], level="Этаж 1", id="W1")
    dsl.create_door(host=sdk.Ref("W1"), offset_mm=3000)
    assert dsl.ops()[1]["host"] == {"by": "ref", "value": "W1"}


# ══════════════════════════════════════════════ ENVELOPE AND PROGRAM

def test_the_envelope_is_the_compilers_envelope_and_nothing_else():
    dsl.envelope(intent="проба", allow_destructive=True,
                 defaults={"level": "Этаж 1", "type": 100})
    dsl.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], level="Этаж 1")
    got = dsl.build()
    assert set(got) <= {"ir_version", "intent", "allow_destructive",
                        "defaults", "ops"}
    assert got["ir_version"] == spec.IR_VERSION
    assert got["defaults"] == {"level": {"by": "name", "value": "Этаж 1"},
                               "type": {"by": "element_id", "value": 100}}
    assert plan_program(got) is not None


def test_the_context_manager_isolates_and_restores():
    """The context manager is available but not mandatory: the script reads as
    a script, and yet a nested program can still be separated explicitly."""
    dsl.create_level(elev_mm=0, name="снаружи")
    outer = dsl.current()
    with dsl.program(intent="внутри") as inner:
        dsl.create_level(elev_mm=3000, name="внутри")
        assert dsl.current() is inner
        assert len(inner.ops) == 1
    assert dsl.current() is outer
    assert len(outer.ops) == 1
    assert inner.build()["intent"] == "внутри"


def test_a_program_without_the_context_manager_is_the_default_path():
    """Five lines of python and nothing more — the form all of this was started for."""
    dsl.envelope(intent="каре 6×4")
    corners = [(0, 0), (6000, 0), (6000, 4000), (0, 4000)]
    walls = [dsl.create_wall(p0_mm=a, p1_mm=b, level="Этаж 1")
             for a, b in zip(corners, corners[1:] + corners[:1])]
    dsl.create_door(host=walls[0], offset_mm=3000, symbol="Дверь 900x2100")
    got = dsl.build()
    assert len(got["ops"]) == 5
    assert got["ops"][4]["host"] == {"by": "ref", "value": "wall1"}
    assert plan_program(got) is not None


def test_the_plan_helper_is_the_single_semantic_door_downwards():
    dsl.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], level="Этаж 1")
    planned = dsl.plan()
    assert planned.plan_digest == plan_program(dsl.build(), bulk=True).plan_digest
    assert planned.bulk is True


# ══════════════════════════════════════════ THE CONTRACT WITH THE SANDBOX

def test_the_drain_hands_the_whole_envelope_and_leaves_nothing_behind():
    """The sandbox polls the language's `take_ops()` FIRST and understands the envelope. Handing back
    a plain list of ops would mean silently losing the `intent` set by
    the script; zeroing out after handing it over isolates the next script."""
    dsl.envelope(intent="каре", allow_destructive=True)
    dsl.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], level="Этаж 1")
    got = dsl.take_ops()
    assert got["intent"] == "каре"
    assert got["allow_destructive"] is True
    assert len(got["ops"]) == 1
    assert dsl.ops() == [], "drain обязан обнулить"


def test_an_empty_drain_is_falsy_so_the_scripts_own_variable_still_wins():
    """The sandbox has TWO collection paths: the language drain and the script's `ops` variable.
    A truthy answer with zero accumulated would hijack the second path for itself."""
    assert dsl.take_ops() is None


def test_the_drain_is_not_injected_into_the_authors_namespace():
    """The sandbox puts the names from `__all__` into the script's namespace. There is no need to
    leak its own program to the author — it takes it back itself."""
    assert "take_ops" not in dsl.__all__
    assert callable(dsl.take_ops)


def test_every_exported_name_is_injectable_into_a_script_namespace():
    """The sandbox NEVER injects modules (otherwise `import os` in the language would become
    a back door). Exporting a module here would mean silently losing a name."""
    import types
    for name in dsl.__all__:
        assert hasattr(dsl, name), f"__all__ обещает несуществующее имя {name}"
        assert not isinstance(getattr(dsl, name), types.ModuleType), name


def test_a_reload_of_dsl_does_not_poison_who_imported_it_with_a_star():
    """🔴 A GUARD FOR THE CLASS, NOT FOR THE CASE (17.08.2026, paid for by 18 reds).

    `kir/course/language.py:54` does `from kir.dsl import *` and in
    its own docstring says "THE SAME objects." That is true, and it is also the vulnerability:
    `importlib.reload(dsl)` rewrites the module dict IN PLACE, introducing
    a NEW `_RegistryDefault` class, while the operation functions captured earlier
    carry defaults of the OLD class in their signatures. The
    `isinstance` check (`dsl.py:843`) no longer recognizes them — and the registry sentinel
    rides off into the program, where `json.dumps` blows up two layers away, far
    from the cause.

    Here this is checked IN SUBSTANCE: after the reload, the course function
    must still OMIT an unfilled field rather than write the sentinel into it.
    The check runs on `json.dumps` — the very place where the defect
    used to surface.

    The test cleans up after itself with the same helper as its neighbor above: otherwise
    the class guard would become the source of the problem.
    """

    import json as _json

    from kir.course import language

    importlib.reload(dsl)
    try:
        language.reset()
        language.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], level="Этаж 1")
        ops = language.ops()
        assert len(ops) == 1
        # Registry defaults are not written in: the program is serializable, and fields
        # that the author did not name are absent from it.
        _json.dumps(ops, ensure_ascii=False)
        assert "structural" not in ops[0], (
            "умолчание реестра вписано в программу — провенанс поля потерян")
    finally:
        importlib.reload(dsl)
        _restore_the_reexporters()
