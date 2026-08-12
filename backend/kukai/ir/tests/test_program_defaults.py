"""Envelope defaults: say a repeated selector once, not once per op.

Measured, not imagined. On 2026-07-27 the model was given the Eiffel Tower and
the real `revit_ir` schema in an offline dojo (`tools/kir_dojo.py`), and its
second program was 20 beams with `level` and `symbol` simply omitted — it was
hoping for a default. A project with more than one candidate cannot default, so
grounding refused all twenty at once (KIR-G102 ×40) and the round was spent.
Its recovery was to repeat the identical selector in every op: 128 beams, 256
selectors, all the same two values. That is output tokens, latency and drift on
the one thing that never varies across a lattice.

Since the required-selector plan boundary, the same malformed program stops
earlier with KIR-P005 on ``level``.  The historical observation above still
explains why envelope defaults exist; it no longer names the current stage of
the refusal.  Grounding must not run for a program whose required selector is
absent.

The scope is deliberately narrow. Only selectors default (see DEFAULTABLE); a
default that moved geometry would put the shape somewhere other than the op that
draws it, and an op saying what it does is the property KIR is built on.
"""
from __future__ import annotations

import copy

import pytest

from kukai.ir.compiler import DEFAULTABLE, compile_program
from kukai.ir.schema_gen import program_schema
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT

LEVEL = {"by": "name", "value": "Этаж 1"}
BEAM = {"by": "element_id", "value": 1100}


def _beam(i: int, **extra) -> dict:
    return {"op": "create_beam", "id": f"b{i}",
            "p0_mm": [i * 1000, 0, 0], "p1_mm": [i * 1000, 0, 30000], **extra}


def _compile(program, snapshot=GROUND_SNAPSHOT):
    return compile_program(program, revit_version="2026", snapshot=snapshot)


def _codes(out) -> list[str]:
    return [d.code for d in out.diagnostics]


def test_one_envelope_selector_covers_every_op():
    out = _compile({"ir_version": "1.0",
                    "defaults": {"level": LEVEL, "symbol": BEAM},
                    "ops": [_beam(i) for i in range(12)]})
    assert out.ok, [d.as_dict() for d in out.diagnostics]


def test_without_it_the_same_program_is_the_refusal_we_measured():
    """The historical omission now refuses at the plan boundary, not ground."""
    out = _compile({"ir_version": "1.0", "ops": [_beam(i) for i in range(12)]})
    assert not out.ok
    assert set(_codes(out)) == {"KIR-P005"}, _codes(out)
    assert {d.field_name for d in out.diagnostics} == {"level"}


def test_an_op_that_names_its_own_value_keeps_it():
    """Inheritance, not override — the envelope fills gaps and nothing else."""
    own = {"by": "name", "value": "Этаж 2"}
    out = _compile({"ir_version": "1.0",
                    "defaults": {"level": LEVEL, "symbol": BEAM},
                    "ops": [_beam(0), _beam(1, level=own)]})
    assert out.ok, [d.as_dict() for d in out.diagnostics]


def test_a_program_without_defaults_is_untouched():
    """~50 installs author without this key. Their programs must not move."""
    program = {"ir_version": "1.0",
               "ops": [_beam(i, level=LEVEL, symbol=BEAM) for i in range(4)]}
    before = copy.deepcopy(program)
    out = _compile(program)
    assert out.ok, [d.as_dict() for d in out.diagnostics]
    assert program == before, "compile mutated the caller's program"


def test_only_selectors_may_be_defaulted():
    out = _compile({"ir_version": "1.0",
                    "defaults": {"p0_mm": [0, 0, 0]},
                    "ops": [_beam(0, level=LEVEL, symbol=BEAM)]})
    assert not out.ok
    d = out.diagnostics[0]
    assert d.field_name == "defaults"
    assert set(d.candidates) == set(DEFAULTABLE)


def test_a_default_no_op_accepts_is_named_not_ignored():
    """The silent no-op is the failure mode KIR exists to refuse: a typo that
    changes nothing reads exactly like a default that worked."""
    out = _compile({"ir_version": "1.0",
                    "defaults": {"level": LEVEL, "symbol": BEAM,
                                 "top_level": LEVEL},
                    "ops": [_beam(0)]})
    assert not out.ok
    assert any("top_level" in str(d.got) for d in out.diagnostics), _codes(out)


def test_defaults_reach_macro_generated_ops():
    """Expansion runs first, so a stack's per-storey clones inherit too."""
    out = _compile({
        "ir_version": "1.0",
        "defaults": {"type": {"by": "name", "value": "Кирпич 250"}},
        "ops": [{"op": "stack", "id": "s", "levels": 3, "h_mm": 3000,
                 "floor": [{"op": "create_wall", "id": "w",
                            "p0_mm": [0, 0], "p1_mm": [6000, 0],
                            "height_mm": 3000}]}]})
    assert out.ok, [d.as_dict() for d in out.diagnostics]


def test_a_bad_shape_is_a_typed_refusal_not_a_crash():
    out = _compile({"ir_version": "1.0", "defaults": ["level"],
                    "ops": [_beam(0, level=LEVEL, symbol=BEAM)]})
    assert not out.ok
    assert any(d.field_name == "defaults" for d in out.diagnostics)


@pytest.mark.parametrize("name", DEFAULTABLE)
def test_the_schema_offers_exactly_what_the_compiler_accepts(name):
    """A schema wider than the compiler invites programs it then rejects; a
    narrower one hides the feature. They are generated from one list — this
    fails if they ever stop agreeing."""
    props = program_schema()["properties"]["defaults"]["properties"]
    assert name in props
    assert set(props) == set(DEFAULTABLE)
