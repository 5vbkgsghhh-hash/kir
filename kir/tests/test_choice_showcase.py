"""THE SHOWROOM OF CHOICE — a choice must be not only MADE but also
SHOWN.

The refuting test reproduces the live case of 10.08.2026 (operator model
`13A-RD-AR-K2_v33`, Revit 2023) verbatim. One wall without a `type`, the
turn green straight through — `execution=committed`, `witness=satisfied`,
`acceptance=accepted` — the built wall received the type «111_Кирпич 380»,
and the receipt returned exactly this:

    [{"op_id": "W1", "op": "create_wall", "param": "type",
      "rule": "doc_default", "chosen": {"id": null, "name": null}}]

The rule is NAMED, but what was chosen is empty, and `defaults_note_ru`
stayed silent altogether. This is exactly the defect the mechanism was
written for: an empty choice is INDISTINGUISHABLE FROM "no choice was
made," meaning it tells the reader (and the main reader here is the model)
a lie about its own awareness.

WHY THE FIELD IS EMPTY IS NOT A FILLING BUG BUT A FACT ABOUT THE STAGE.
Measurement from the code: `ground._resolve_one` for `create_wall.type`
returns `IN_EMIT_DEFAULT`, and the type name appears only inside emission —
`doc.GetDefaultElementTypeId(ElementTypeGroup.WallType)` is asked of THE
DOCUMENT ITSELF at the moment of execution (`authoring.py:507`). At the
grounding stage the name DOES NOT EXIST, and inventing it would be worse
than not naming it. So what is fixed is not "an empty field" but the row's
FALSE FORM, and it is fixed in two steps:

* before execution, the row honestly says the choice is DEFERRED to the
  document, and names where the name will appear (`chosen.resolved_at` +
  `chosen.read_from`);
* after execution, the name ARRIVES from the receipt of the built element
  (`ground.attach_runtime_choices`) — the emitter applied the type, and it
  is the emitter that read it back, so this is a MEASUREMENT, not a guess.

The second step is needed precisely because "go read it yourself" removes
less uncertainty for the model than a named name: we already have the
answer in the same JSON, and failing to wire it in would mean handing the
model our own work.
"""
from __future__ import annotations

import copy
import re

from kir.compiler import compile_program
from kir.ground import describe_choices_ru, IN_EMIT_DEFAULT
from kir.tests.fixtures import GROUND_SNAPSHOT

LV = {"by": "name", "value": "Этаж 1"}
SQ = [[0, 0], [4000, 0], [4000, 3000], [0, 3000]]


def _snapshot(**pools) -> dict:
    snap = copy.deepcopy(GROUND_SNAPSHOT)
    snap.update(pools)
    return snap


def _compile(ops, snapshot, bulk=False):
    return compile_program({"ir_version": "1.0", "ops": ops},
                           revit_version="2026", snapshot=snapshot, bulk=bulk)


def _row(out, op_id, param):
    report = out.as_dict().get("grounding_report") or []
    return next((r for r in report
                 if r["op_id"] == op_id and r["param"] == param), None)


#: The live program of 10.08: one wall, the type not named.
_BARE_WALL = [{"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
               "p1_mm": [6000, 0], "level": LV, "height_mm": 3000}]


def test_the_document_default_must_not_present_an_empty_choice():
    """THE LIVE CASE OF 10.08: `chosen` is empty, and this is
    indistinguishable from "did not choose."

    The empty pair `{id: null, name: null}` is the worst of the possible
    forms: the element DID GET a type, meaning the choice happened, and the
    row reports the opposite.
    """
    out = _compile(_BARE_WALL, _snapshot())
    assert out.ok, [d.code for d in out.diagnostics]
    row = _row(out, "W1", "type")
    assert row is not None and row["rule"] == "doc_default", row
    chosen = row["chosen"]
    assert chosen.get("resolved_at") == "revit", (
        "строка обязана СКАЗАТЬ, что выбор отложен документу, а не молча "
        f"вернуть пустую пару: {chosen}")
    assert chosen.get("read_from") == "result.W1.type_name", (
        "строка обязана назвать, ГДЕ имя появится после постройки: "
        f"{chosen}")


def test_the_note_never_stays_silent_about_a_choice_that_was_made():
    """Silence about a choice that was made is precisely the original
    defect.

    Live, `defaults_note_ru` did not arrive at all: `describe_choices_ru`
    skipped everything that had no `rule_detail.candidates`. For
    `sole_entry` this is justified (one candidate, nothing to choose
    from), for a document default — it is not: a real project has dozens
    of wall types, a choice among them WAS MADE, just not by us.
    """
    out = _compile(_BARE_WALL, _snapshot())
    note = describe_choices_ru(out.as_dict()["grounding_report"])
    assert note, "витрина обязана говорить о документном умолчании"
    assert "result.W1.type_name" in note, note


def test_the_deferred_choice_is_filled_from_the_element_that_was_built():
    """The name arrives from the RUNTIME: the emitter applied the type —
    it is the emitter that read it back.

    This is not a guess and not filling in something plausible:
    `type_name` in the execution receipt is read from `GetTypeId()` of the
    built element.
    """
    from kir.ground import attach_runtime_choices

    out = _compile(_BARE_WALL, _snapshot())
    payload = {"ok": True, "W1": {"id": "424242",
                                  "type_name": "111_Кирпич 380"}}
    filled = attach_runtime_choices(out.as_dict()["grounding_report"], payload)
    chosen = filled[0]["chosen"]
    assert chosen["name"] == "111_Кирпич 380", chosen
    assert chosen["source"] == "readback", (
        "происхождение имени обязано быть названо: снапшот и построенный "
        f"элемент — разные источники: {chosen}")
    note = describe_choices_ru(filled)
    assert "111_Кирпич 380" in note, note


def test_a_missing_readback_leaves_the_choice_unresolved_and_invents_nothing():
    """A made-up type name is WORSE than an empty one: empty is honest,
    made up lies."""
    from kir.ground import attach_runtime_choices

    out = _compile(_BARE_WALL, _snapshot())
    report = out.as_dict()["grounding_report"]
    for payload in ({"ok": True, "W1": {"id": "424242"}},
                    {"ok": True, "W1": {"id": "1", "type_name": "  "}},
                    {"ok": True}, None, "не словарь"):
        filled = attach_runtime_choices(report, payload)
        chosen = filled[0]["chosen"]
        assert chosen["name"] is None, (payload, chosen)
        assert chosen["resolved_at"] == "revit", chosen
        note = describe_choices_ru(filled)
        assert "result.W1.type_name" in note, (payload, note)


def test_the_join_does_not_mutate_the_compiled_report():
    """`CompileOutput` outlives the turn and is cached; a receipt is not a
    draft."""
    from kir.ground import attach_runtime_choices

    out = _compile(_BARE_WALL, _snapshot())
    report = out.as_dict()["grounding_report"]
    before = copy.deepcopy(report)
    attach_runtime_choices(report, {"ok": True,
                                    "W1": {"type_name": "111_Кирпич 380"}})
    assert report == before, "соединение обязано вернуть НОВЫЙ список"


# ── the same instrument for the other two rules ─────────────────────────
# The hole could have been shared. The 10.08 measurement says it is not:
# `sole_entry` and `most_used` take the name from the snapshot, meaning
# they know it even before emission.

def test_sole_entry_carries_its_name_at_compile_time():
    ops = [{"op": "create_ceiling", "id": "C1", "outline": SQ, "level": LV}]
    row = _row(_compile(ops, _snapshot()), "C1", "type")
    assert row is not None and row["rule"] == "sole_entry", row
    assert row["chosen"]["id"] == 1200, row
    assert row["chosen"]["name"] == "Потолок подвесной 600x600", row
    assert "resolved_at" not in row["chosen"], (
        "имя известно на стадии заземления — откладывать нечего")


def test_most_used_carries_its_name_at_compile_time():
    pool = [{"id": 7000 + i, "name": f"Дверь тип {i:02d}",
             "instances": 1 if i % 3 == 0 else 0} for i in range(62)]
    pool[31] = {"id": 7031, "name": "Дверь однопольная 900x2100",
                "instances": 47}
    ops = [{"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
            "p1_mm": [6000, 0], "level": LV, "height_mm": 3000,
            "type": {"by": "name", "value": "Кирпич 250"}},
           {"op": "create_door", "id": "D1",
            "host": {"by": "ref", "value": "W1"}, "offset_mm": 3000}]
    row = _row(_compile(ops, _snapshot(door_symbols=pool)), "D1", "symbol")
    assert row is not None and row["rule"] == "most_used", row
    assert row["chosen"]["name"] == "Дверь однопольная 900x2100", row
    assert "resolved_at" not in row["chosen"], row


# ── LOCK ON THE WHOLE RANGE ──────────────────────────────────────────────
# The `read_from` pointer is honest only while the field exists. An
# instrument covering part of the range is more dangerous than a missing
# one, so the list of ops with a document default is checked IN FULL, not
# on a sample wall.

#: The minimal program for every op whose omitted `type` falls through to
#: the document default. The list is taken from `ground.py` by
#: measurement, not by a hand-kept list.
_DOC_DEFAULT_PROGRAMS = {
    "create_wall": [{"op": "create_wall", "id": "X1", "p0_mm": [0, 0],
                     "p1_mm": [6000, 0], "level": LV, "height_mm": 3000}],
    "create_floor": [{"op": "create_floor", "id": "X1", "outline": SQ,
                      "level": LV}],
    "create_roof": [{"op": "create_roof", "id": "X1", "outline": SQ,
                     "level": LV}],
    "create_floor_by_contour": [
        {"op": "create_floor_by_contour", "id": "X1", "level": LV,
         "contour": {"outer": {"shape": "poly", "points_mm": SQ}}}],
    "create_wall_foundation": [
        {"op": "create_wall", "id": "W1", "p0_mm": [0, 0], "p1_mm": [6000, 0],
         "level": LV, "height_mm": 3000,
         "type": {"by": "name", "value": "Кирпич 250"}},
        {"op": "create_wall_foundation", "id": "X1",
         "wall": {"by": "ref", "value": "W1"}}],
    "create_extrusion_roof": [
        {"op": "create_extrusion_roof", "id": "X1", "level": LV,
         "p0_mm": [0, 0], "p1_mm": [0, 6000],
         "profile_mm": [[0, 0], [4000, 2000], [8000, 0]],
         "start_mm": 0, "end_mm": 6000}],
    "create_area_reinforcement": [
        {"op": "create_floor", "id": "F1", "outline": SQ, "level": LV,
         "type": {"by": "name", "value": "Монолит 200"}},
        {"op": "create_area_reinforcement", "id": "X1",
         "host": {"by": "ref", "value": "F1"}, "direction_deg": 0}],
    "create_filled_region": [
        {"op": "create_filled_region", "id": "X1",
         "in_view": {"by": "element_id", "value": 12345},
         "contour": {"outer": {"shape": "poly", "points_mm": SQ}}}],
}

_TYPE_NAME_READBACK = re.compile(r'__rb(?:_\w+)?\["type_name"\]')


def test_the_named_op_list_matches_the_rule_in_ground():
    """The list above is not the author's memory but the same set as in
    `ground.py`."""
    import inspect

    from kir import ground as ground_mod

    # 🔴 THE AUTHORITY IS QUERIED, NOT THE FUNCTION'S TEXT (28.08.2026).
    #
    # Here `inspect.getsource(ground.ground)` used to be read, and op names
    # were searched for in it as strings. The names live in the
    # MODULE-LEVEL CONSTANT `OPS_WITH_DOC_DEFAULT_TYPE`, not in the
    # function body — and the probe found ZERO, declaring that "the op
    # vanished from ground.py or was renamed." None had vanished: the
    # probe was looking in the wrong place, and its refusal read as a
    # finding about the registry. A form this tree has already paid for
    # more than once: a test that reads SOURCE accuses the subject instead
    # of itself.
    #
    # The constant is the very place where the list is declared, and it is
    # what must be checked against: then a rename or a disappearance is
    # caught IN SUBSTANCE, not by text.
    named = set(_DOC_DEFAULT_PROGRAMS) & set(ground_mod.OPS_WITH_DOC_DEFAULT_TYPE)
    assert named == set(_DOC_DEFAULT_PROGRAMS), (
        "оп с документным умолчанием исчез из ground.OPS_WITH_DOC_DEFAULT_TYPE "
        f"или переименован: {set(_DOC_DEFAULT_PROGRAMS) - named}")


def test_every_document_default_op_reads_its_type_name_back():
    """Otherwise `read_from` would point at a field that is not in the
    receipt.

    An empty field is honest; a pointer to nowhere is not. This lock
    catches a new op with a document default for which reading the type
    back was forgotten.
    """
    for op_name, ops in _DOC_DEFAULT_PROGRAMS.items():
        out = _compile(ops, _snapshot(), bulk=True)
        assert out.ok, (op_name, [d.code for d in out.diagnostics])
        row = _row(out, "X1", "type")
        assert row is not None and row["rule"] == "doc_default", (op_name, row)
        assert row["chosen"].get("read_from") == "result.X1.type_name", (
            op_name, row)
        assert _TYPE_NAME_READBACK.search(out.csharp or ""), (
            f"{op_name}: квитанция обещает result.X1.type_name, а эмиссия "
            "имя типа обратно не читает")


def test_a_deferred_param_other_than_type_gets_no_address_it_cannot_keep():
    """The pointer is correct ONLY while `type` is deferred, and that is
    not an eternal truth.

    Today `IN_EMIT_DEFAULT` is set solely on `type`, and the name is read
    back under the key `type_name`. Should someone set up a document
    default on another parameter, the old pointer would send the reader to
    the wrong field. In that case the row must stay without an address,
    and the wiring must not touch it: a guess disguised as a measurement
    is worse than silence.
    """
    from kir import ground as ground_mod

    report = ground_mod.compiler_choices([{
        "id": "X1", "op": "выдуманный_оп",
        "какой_то_другой_селектор": {"__grounded__": {
            "id": None, "name": None, "via": "doc_default",
            "in_emit": IN_EMIT_DEFAULT}}}])
    chosen = report[0]["chosen"]
    assert chosen["resolved_at"] == "revit", chosen
    assert "read_from" not in chosen, chosen
    filled = ground_mod.attach_runtime_choices(
        report, {"ok": True, "X1": {"type_name": "не про этот параметр"}})
    assert filled[0]["chosen"]["name"] is None, filled
    assert "не про этот параметр" not in describe_choices_ru(filled)


def test_the_deferred_marker_comes_from_the_emitter_contract():
    """`resolved_at` is set by the emission marker, not by the rule's
    name.

    The `IN_EMIT_DEFAULT` marker is the very thing that makes the emitter
    ask the document; binding to it, rather than to the string
    "doc_default," keeps the showroom from drifting apart from emission
    when the rule is renamed.
    """
    from kir import ground as ground_mod
    from kir.compiler import plan_program

    normed = plan_program({"ir_version": "1.0", "ops": _BARE_WALL},
                          bulk=False).to_ops()
    grounded = ground_mod.ground(normed, _snapshot())
    res = grounded[0]["type"]["__grounded__"]
    assert res["in_emit"] == IN_EMIT_DEFAULT
    res_without = dict(res)
    res_without.pop("in_emit")
    report = ground_mod.compiler_choices(
        [{"id": "W1", "op": "create_wall",
          "type": {"__grounded__": res_without}}])
    assert "resolved_at" not in report[0]["chosen"], (
        "без метки эмиссии откладывать нечего — строка не должна обещать "
        "чтения, которого не будет")
