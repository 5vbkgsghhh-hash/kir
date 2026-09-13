"""SCHEMA DEDUPLICATION — the savings must be PROVEN, not promised.

The KIR schema is 70.7% of everything sent to the model on the first
turn (measurement 03.08: 22,631 tokens out of 44,615). Two thirds of it
is a verbatim repeat of selectors. Hoisting the repeats into `$defs`
gives a threefold reduction WITHOUT removing a single operation from
context — and this is what fundamentally distinguishes it from tiered
delivery, which pays with visibility (from the refusal journal: 4.8%
of compilations were ops the model never saw and so INVENTED).

What is checked here is exactly what this distinction rests on: the
transformation is REVERSIBLE. As long as `expand(hoist(s))` equals `s`
byte-for-byte, "we lost nothing" is a fact checked by the machine. The
moment it stops holding, the test goes red, and no savings outweighs
that.
"""
from __future__ import annotations

import json

import pytest

from kir import spec
from kir.schema_dedup import expand, hoist, measure
from kir.schema_gen import program_schema


def _canon(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


@pytest.fixture(scope="module")
def flat() -> dict:
    return program_schema()


@pytest.fixture(scope="module")
def packed(flat: dict) -> dict:
    return hoist(flat)


def test_the_transform_is_exactly_reversible(flat: dict, packed: dict) -> None:
    """THE FILE'S MAIN TEST: the schema expanded back is IDENTICAL to
    the original."""
    assert _canon(expand(packed)) == _canon(flat), (
        "дедупликация изменила смысл схемы — экономия не имеет значения, "
        "если язык стал другим")


def test_no_operation_disappears(flat: dict, packed: dict) -> None:
    """Not a single op disappears — that is exactly the difference
    from tiering.

    Tiered delivery removes ops from view and pays for it with
    invented calls. Deduplication removes nothing, and this is checked
    here by name, not by trusting the previous test.
    """
    text = _canon(packed)
    missing = sorted(name for name in spec.OPS if f'"{name}"' not in text)
    assert not missing, f"опы пропали из схемы после выноса: {missing}"


def test_every_reference_resolves(packed: dict) -> None:
    """A dangling reference is a schema that cannot be read. We catch
    it before it reaches the model."""
    defs = set(packed.get("$defs", {}))
    dangling: list[str] = []

    def walk(node) -> None:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str):
                name = ref.rsplit("/", 1)[-1]
                if name not in defs:
                    dangling.append(ref)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(packed)
    assert not dangling, f"висячие ссылки: {sorted(set(dangling))}"


def test_the_saving_is_real_and_large(flat: dict) -> None:
    """The savings must be LARGE, otherwise they aren't worth the new
    entity.

    The 2.5x threshold is set BELOW the measured value (3.04x on
    03.08; 3.871x on 41 ops on 09.08) — the test guards against
    regression, it does not pin today's number. If hoisting ever stops
    paying off, it is more honest to throw it out entirely than to
    keep carrying `$defs` for appearance's sake.

    The sharp ratchet lives in `test_schema_transport.py` (a 3.5x
    threshold, set against the weakest LIVE measurement, plus a
    byte-per-op ceiling). What remains here is a rough lower bound on
    the transformation itself, independent of where it is wired in.
    """
    stats = measure(flat)
    assert stats["ratio"] >= 2.5, (
        f"вынос перестал окупаться: {stats}")
    assert stats["packed_bytes"] < stats["flat_bytes"]


def test_the_result_is_deterministic(flat: dict) -> None:
    """Twice the same schema — twice the same bytes.

    Without this, any hash over the schema (and one will eventually be
    needed: that's how all pre-registration in this package works)
    would become a random number.
    """
    assert _canon(hoist(flat)) == _canon(hoist(program_schema()))


def test_names_explain_themselves_where_they_can(packed: dict) -> None:
    """The name in `$defs` is read by the MODEL, not just the
    compiler.

    `#/$defs/sel_by_name` explains the form; `#/$defs/shape_7` does
    not. We do not demand meaningfulness from every name (inventing
    meaning where none was recognized is worse than an honest sequence
    number), but selectors are 90% of what's hoisted, and they must be
    readable.
    """
    names = set(packed.get("$defs", {}))
    assert names, "вынос ничего не дал"
    # An unnamed form is one that got a sequence number because it
    # went UNRECOGNIZED. All other names are derived structurally:
    # `pt_xy`, `element_id`, `kind_enum`, `region_rect`,
    # `number_5_2000`.
    anonymous = {name for name in names if name.startswith("shape_")}
    speaking = names - anonymous
    assert len(speaking) * 3 >= len(names) * 2, (
        f"узнано только {len(speaking)} форм из {len(names)}; "
        f"безымянные: {sorted(anonymous)}")


def test_both_forms_are_legal_json_schema(flat: dict, packed: dict) -> None:
    """THE COLLAPSED FORM MUST BE VALID ON ITS OWN — identity is not
    enough.

    The first edition of hoisting was reversible and yet INVALID:
    `$ref` was substituted inside the `properties` map, where it reads
    as a property NAMED "$ref" rather than as a reference. The
    identity test let this through, because expansion mechanically
    brought everything back. The model, meanwhile, would have received
    a schema describing an object with a `$ref` property instead of
    describing an operation.

    Here judgment comes from an OUTSIDE validator against the
    meta-schema, not from our own reasoning about where a reference
    belongs.
    """
    jsonschema = pytest.importorskip("jsonschema")
    validator = jsonschema.Draft202012Validator
    validator.check_schema(flat)
    validator.check_schema(packed)


def test_both_forms_accept_the_same_program(flat: dict, packed: dict) -> None:
    """The final word belongs to behavior: both forms accept the same
    program.

    Validity against the meta-schema says "this is a legal schema,"
    but not "this is the SAME schema." A real program, run through
    both, answers the second question.
    """
    jsonschema = pytest.importorskip("jsonschema")
    program = {
        "ir_version": spec.IR_VERSION,
        "intent": "проверка тождества форм схемы",
        "ops": [
            {"op": "create_wall", "id": "w1",
             "p0_mm": [0, 0], "p1_mm": [5000, 0],
             "level": {"by": "name", "value": "Этаж 1"},
             "height_mm": 3000},
            {"op": "create_door", "id": "d1",
             "host": {"by": "ref", "value": "w1"}, "offset_mm": 2500},
        ],
    }
    flat_errors = [e.message for e
                   in jsonschema.Draft202012Validator(flat).iter_errors(program)]
    packed_errors = [e.message for e
                     in jsonschema.Draft202012Validator(packed).iter_errors(program)]
    assert not flat_errors, f"плоская схема отвергла верную программу: {flat_errors}"
    assert not packed_errors, (
        f"свёрнутая схема отвергла программу, которую приняла плоская: "
        f"{packed_errors}")


def test_hoisting_twice_is_refused(packed: dict) -> None:
    """A repeated hoist is a sign of a tangled pipeline, not
    harmlessness."""
    with pytest.raises(ValueError):
        hoist(packed)


def test_flat_schema_is_untouched_by_this_module(flat: dict) -> None:
    """THE GENERATOR STAYS FLAT — and this is no longer a
    postponement, it's a separation of roles.

    Since 09.08.2026 hoisting is WIRED IN, but not here: it is done by
    `schema_transport.program_schema_for_tool()` at the tool boundary
    (`serving.inject_revit_ir_schema`), under a MEASURED transport
    condition. The generator, meanwhile, must remain the single source
    of truth about the LANGUAGE, and `schema_dedup` a clean post-pass
    over its result: the moment `program_schema()` itself starts
    handing out `$defs`, a repeat hoist becomes impossible ("repeated
    hoist is forbidden"), and the language's form stops being
    described in one place.

    What the model sees is checked where that is decided:
    `test_schema_transport.py::test_the_live_tool_actually_ships_the_deduped_schema`.
    """
    assert "$defs" not in flat, (
        "program_schema() начал отдавать схему со ссылками — тогда хойст на "
        "границе инструмента откажет, и единственный работающий механизм "
        "дедупликации сломается о рукописный `$defs`")
