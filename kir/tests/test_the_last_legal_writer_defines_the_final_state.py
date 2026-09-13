"""THE LAST LEGAL WRITER DEFINES THE FINAL STATE, NOT THE FIRST.

WHAT WAS FOUND (07.09.2026, mandate F1/C01 "last successful writer").
The writer witness is emitted at the FINAL STAGE, i.e. it runs AFTER the
whole program. As long as a property has a single writer in the program,
this makes no difference. As soon as there are TWO legal writers of one
address×property, the FIRST writer's witness pins an ALREADY OVERWRITTEN
value and fails a correct program:

    set_param(101,"Comments","first"); set_param(101,"Comments","last")
    → the final block `// post S1` asks `!= "first"`, while the model
      holds "last" → `__post.Add` → RollBack. The building was built
      correctly, the answer is a refusal.

    move_elements([102], +10/+20/+30); move_elements([102], -5/0/+5)
    → the final block `// post M1` checks "current point == snapshot
      BEFORE M1 + delta_M1", but the element has also moved by delta_M2
      (5 mm > tolerance 1.0) → the same false refusal.

This is NOT the same thing as a missing check: the check exists, but it
is about the STAGE OF THE OPERATION ("at the end of my op the value was
mine"), while it is declared to be about the END OF THE PROGRAM. This
exact difference was already named and closed by
`docs/OPERATION_WITNESS_STAGE_RU.md` for `change_type` (`stage="operation"`,
key `type_assignment`); `set_param.value_held` and `move_elements.location`
were left on final.

WHAT IS MEASURED: an INDEPENDENT calculator of the final state
(`_last_writers` below) works out, from the program, who is the last
legal writer of each address×property, and checks it against WHOSE
witness stands in the final emission block. A pinned, overwritten writer
= red. The calculator does NOT call the plan and does NOT read
`acceptance_mutation`: this is a second count, not a retelling.

FAIL CONTROL: revert `stage="final"` on `set_param.value_held` or
`move_elements.location` in `kir/authoring.py` — tests 1 and 4 and the
combined calculator (test 7) go red. PASS CONTROL: two DIFFERENT
parameters of one target (test 3) and a single writer (test 2) do not
lose their witnesses.

Run:
    venv/bin/python -m pytest \
        kir/tests/test_the_last_legal_writer_defines_the_final_state.py -q
"""
from __future__ import annotations

import re
import unittest

from kir import spec
from kir.acceptance_mutation import (MUTATION_ACCEPTANCE_OPS, MutationKind,
                                     derive_mutation_expectation)
from kir.compiler import compile_program, plan_program
from kir.registry_base import EffectKind, IdentityCardinality
from kir.tests.fixtures import GROUND_SNAPSHOT

LVL = {"by": "element_id", "value": 42}


def _eid(value: int) -> dict:
    return {"by": "element_id", "value": value}


def _compile(ops, intent="последний писатель"):
    return compile_program(
        {"ir_version": "1.0", "intent": intent, "ops": ops},
        "2026", snapshot=GROUND_SNAPSHOT)


_HEADER = re.compile(r"^\s*//\s+(\S+)\s+(\S+)\s*$")
_SENTINEL = "if (__post.Count > 0)"


def _stage_blocks(cs: str) -> dict[str, dict[str, str]]:
    """Break the emission down into STAGES by its own headers.

    `emit_model._render_stage` prints `// post <oid>` for final and
    `// operation <oid>` for operation — this is a machine marker of the
    stage right in the emission itself, not a guess from content.
    """

    out: dict[str, dict[str, str]] = {"post": {}, "operation": {}}
    stage = oid = None
    body: list[str] = []

    def flush() -> None:
        if stage is not None:
            out[stage][oid] = "\n".join(body)

    for line in cs.splitlines():
        header = _HEADER.match(line)
        if header is not None:
            flush()
            kind, name = header.group(1), header.group(2)
            if kind in ("post", "operation"):
                stage, oid, body = kind, name, []
            else:
                stage = oid = None
                body = []
            continue
        if _SENTINEL in line:
            flush()
            stage = oid = None
            body = []
            continue
        if stage is not None:
            body.append(line)
    flush()
    return out


#: Property ← substring of the witness's OWN message. The key here is not
#: made up: it is exactly the text the emitter prints in `__post.Add`,
#: i.e. the binding "pinned" is tied to "pinned to exactly what".
_PROPERTY_MARKERS = (
    ("param", "параметр не удержал значение"),
    ("location", "не сдвинулась на delta_mm"),
    ("location", "концы не сдвинулись на delta_mm"),
    ("type", "type assignment mismatch"),
)


def _pins(cs: str, stage: str) -> set[tuple[str, str]]:
    """Pairs "op × property" that the `stage` STAGE is able to reject."""

    found: set[tuple[str, str]] = set()
    for oid, body in _stage_blocks(cs)[stage].items():
        for prop, marker in _PROPERTY_MARKERS:
            if marker in body:
                found.add((oid, prop))
    return found


# --------------------------------------------------------------------------
# INDEPENDENT CALCULATOR OF THE FINAL STATE
# --------------------------------------------------------------------------

def _last_writers(ops: list[dict]) -> dict[tuple, str]:
    """The last legal writer of each address×property.

    Computed FROM THE PROGRAM and only from it: no plan, no acceptance,
    no emission here — otherwise this would be a retelling of what is
    under test, not a second count.
    """

    last: dict[tuple, str] = {}
    for op in ops:
        name, oid = op["op"], op["id"]
        if name == "set_param":
            target = op["target"]
            if target.get("by") == "element_id":
                last[(target["value"], "param", op["param"])] = oid
        elif name == "change_type":
            target = op["target"]
            if target.get("by") == "element_id":
                last[(target["value"], "type")] = oid
        elif name == "move_elements":
            for selector in op["targets"]:
                if selector.get("by") == "element_id":
                    last[(selector["value"], "location")] = oid
    return last


_PROPERTY_OF = {"set_param": "param", "change_type": "type",
                "move_elements": "location"}


def _superseded(ops: list[dict]) -> set[tuple[str, str]]:
    """Pairs "op × property" whose word was overridden by a later writer."""

    last = _last_writers(ops)
    winners = {(oid, key[1]) for key, oid in last.items()}
    wrote: set[tuple[str, str]] = set()
    for op in ops:
        name, oid = op["op"], op["id"]
        prop = _PROPERTY_OF.get(name)
        if prop is None:
            continue
        selectors = (op["targets"] if name == "move_elements"
                     else [op["target"]])
        if any(sel.get("by") == "element_id" for sel in selectors):
            wrote.add((oid, prop))
    return wrote - winners


# --------------------------------------------------------------------------
# 1-3. TWO `set_param` CALLS ON ONE PARAMETER
# --------------------------------------------------------------------------

_TWO_PARAMS = [
    {"op": "set_param", "id": "S1", "target": _eid(101),
     "param": "Comments", "value": "first"},
    {"op": "set_param", "id": "S2", "target": _eid(101),
     "param": "Comments", "value": "last"},
]


class TwoWritersOfOneParameter(unittest.TestCase):

    def test_a_superseded_set_param_does_not_veto_the_final_state(self):
        out = _compile(_TWO_PARAMS)
        self.assertTrue(out.ok, [d.code for d in out.diagnostics])
        self.assertNotIn(
            ("S1", "param"), _pins(out.csharp, "post"),
            'финальный блок S1 пришпиливает отменённое "first": законная '
            'программа получила бы postconditions_violated и RollBack')

    def test_the_last_writer_value_is_the_one_that_is_checked(self):
        """PASS CONTROL: the check does not disappear — it moves to the stage."""

        out = _compile(_TWO_PARAMS)
        blocks = _stage_blocks(out.csharp)
        pinned = "".join(blocks["post"].values()) + \
            "".join(blocks["operation"].values())
        self.assertIn('"last"', pinned, "последнее значение не сверяется вовсе")
        self.assertIn(
            "S1", set(blocks["post"]) | set(blocks["operation"]),
            "первый писатель остался БЕЗ свидетеля — это не починка, "
            "а снятие проверки")

    def test_two_different_parameters_of_one_target_keep_both_witnesses(self):
        """PASS CONTROL: different properties do not override each other."""

        out = _compile([
            {"op": "set_param", "id": "A", "target": _eid(101),
             "param": "Comments", "value": "one"},
            {"op": "set_param", "id": "B", "target": _eid(101),
             "param": "Mark", "value": "two"},
        ])
        self.assertTrue(out.ok, [d.code for d in out.diagnostics])
        self.assertEqual(_superseded(
            [{"op": "set_param", "id": "A", "target": _eid(101),
              "param": "Comments", "value": "one"},
             {"op": "set_param", "id": "B", "target": _eid(101),
              "param": "Mark", "value": "two"}]), set(),
            "разные параметры одной цели друг друга не отменяют")
        self.assertEqual({("A", "param"), ("B", "param")},
                         _pins(out.csharp, "post") | _pins(out.csharp, "operation"),
                         "оба свидетеля обязаны остаться на своих местах")


# --------------------------------------------------------------------------
# 4. TWO `move_elements` CALLS ON ONE TARGET
# --------------------------------------------------------------------------

_TWO_MOVES = [
    {"op": "move_elements", "id": "M1", "targets": [_eid(102)],
     "delta_mm": [10, 20, 30]},
    {"op": "move_elements", "id": "M2", "targets": [_eid(102)],
     "delta_mm": [-5, 0, 5]},
]


class TwoMovesOfOneTarget(unittest.TestCase):

    def test_a_superseded_move_does_not_veto_the_final_state(self):
        out = _compile(_TWO_MOVES)
        self.assertTrue(out.ok, [d.code for d in out.diagnostics])
        body = _stage_blocks(out.csharp)["post"].get("M1", "")
        self.assertNotIn(
            "точка не сдвинулась на delta_mm", body,
            "финальный блок M1 сверяет «снимок ДО M1 + delta_M1» с точкой, "
            "уехавшей ещё на delta_M2 = (-5,0,5) при допуске 1.0 мм — "
            "гарантированный ложный отказ на законной программе")
        self.assertNotIn("концы не сдвинулись на delta_mm", body)

    def test_the_move_delta_is_still_checked_somewhere(self):
        """PASS CONTROL: the move does not end up without a witness at all."""

        blocks = _stage_blocks(_compile(_TWO_MOVES).csharp)
        everything = "".join(blocks["post"].values()) + \
            "".join(blocks["operation"].values())
        self.assertEqual(2, everything.count("точка не сдвинулась на delta_mm"),
                         "оба переноса обязаны иметь свидетеля перемещения")


# --------------------------------------------------------------------------
# 5-6. `change_type` — ALREADY HOLDS, THIS IS THE SAMPLE FORM
# --------------------------------------------------------------------------

class TwoTypeChangesOfOneTarget(unittest.TestCase):

    _OPS = [
        {"op": "change_type", "id": "C1", "target": _eid(101),
         "type": _eid(5001)},
        {"op": "change_type", "id": "C2", "target": _eid(101),
         "type": _eid(5002)},
    ]

    def test_the_first_type_change_does_not_veto_the_second(self):
        out = _compile(self._OPS)
        self.assertTrue(out.ok, [d.code for d in out.diagnostics])
        self.assertEqual(set(), _pins(out.csharp, "post"))
        self.assertEqual({"C1", "C2"}, set(_stage_blocks(out.csharp)["operation"]))

    def test_a_created_wall_does_not_pin_its_creation_type(self):
        out = _compile([
            {"op": "create_wall", "id": "W", "p0_mm": [0, 0],
             "p1_mm": [6000, 0], "level": LVL},
            {"op": "change_type", "id": "C", "target": {"by": "ref", "value": "W"},
             "type": _eid(5001)},
        ])
        self.assertTrue(out.ok, [d.code for d in out.diagnostics])
        self.assertNotIn("GetTypeId", _stage_blocks(out.csharp)["post"].get("W", ""),
                         "финальный свидетель create_wall не вправе требовать "
                         "тип создания после законного change_type")

    def test_the_final_state_claim_takes_the_second_type(self):
        plan = plan_program({"ir_version": "1.0", "ops": self._OPS})
        expectation = derive_mutation_expectation(plan)
        claims = [c for c in expectation.claims
                  if c.kind is MutationKind.CHANGE_TYPE]
        self.assertEqual(1, len(claims))
        self.assertEqual(5002, claims[0].type_id)
        self.assertEqual(("C1", "C2"), claims[0].op_ids)


# --------------------------------------------------------------------------
# 7. THE COMBINED CALCULATOR AGAINST FINAL WITNESSES
# --------------------------------------------------------------------------

class TheIndependentFinalStateAgreesWithTheWitnesses(unittest.TestCase):

    MIXED = _TWO_PARAMS + _TWO_MOVES + [
        {"op": "change_type", "id": "C1", "target": _eid(103),
         "type": _eid(5001)},
        {"op": "change_type", "id": "C2", "target": _eid(103),
         "type": _eid(5002)},
        {"op": "set_param", "id": "S3", "target": _eid(104),
         "param": "Mark", "value": "solo"},
    ]

    def test_no_superseded_writer_stands_in_the_final_block(self):
        out = _compile(self.MIXED, intent="смешанная цепочка")
        self.assertTrue(out.ok, [d.code for d in out.diagnostics])
        superseded = _superseded(self.MIXED)
        self.assertEqual({("S1", "param"), ("M1", "location"), ("C1", "type")},
                         superseded,
                         "независимый вычислитель назвал не тех отменённых")
        self.assertEqual(
            set(), superseded & _pins(out.csharp, "post"),
            "финальный блок вправе судить только последнего законного "
            "писателя адреса×свойства")

    def test_every_last_writer_keeps_a_witness(self):
        """PASS CONTROL: winners are not lost along with the overridden ones."""

        blocks = _stage_blocks(_compile(self.MIXED).csharp)
        witnessed = set(blocks["post"]) | set(blocks["operation"])
        for oid in _last_writers(self.MIXED).values():
            self.assertIn(oid, witnessed,
                          f"последний писатель {oid} остался без свидетеля")


# --------------------------------------------------------------------------
# 8. A WRITER WITH AN UNKNOWN EFFECT DOES NOT GET SUCCESS
# --------------------------------------------------------------------------

class AWriterWithAnUndeclaredEffect(unittest.TestCase):

    def test_no_registry_op_reads_in_a_writing_place(self):
        for name, entry in sorted(spec.OPS.items()):
            if getattr(entry, "effect", None) is EffectKind.READ:
                with self.subTest(op=name):
                    self.assertFalse(
                        getattr(entry, "writes_model", False),
                        "оп объявлен READ, но пишет модель: его эффект "
                        "неизвестен приёмке и success выдавать нечем")

    def test_no_write_carries_an_identity_free_result(self):
        for name, entry in sorted(spec.OPS.items()):
            effect = getattr(entry, "effect", None)
            if effect not in (EffectKind.MUTATE, EffectKind.DELETE,
                              EffectKind.CREATE):
                continue
            result = getattr(entry, "result", None)
            if result is None:
                continue
            with self.subTest(op=name):
                if result.identity_cardinality is IdentityCardinality.NONE:
                    self.assertIn(
                        name, MUTATION_ACCEPTANCE_OPS,
                        "писатель без объявленной идентичности результата не "
                        "имеет независимого локатора и обязан быть назван "
                        "слепым, а не молча пройти")

    def test_the_mutation_derivation_classifies_every_op_it_owns(self):
        """UNPARSED: 0 — a classifier must have no silent bottom."""

        payloads = {
            "set_param": {"op": "set_param", "id": "X", "target": _eid(101),
                          "param": "Comments", "value": "v"},
            "move_elements": {"op": "move_elements", "id": "X",
                              "targets": [_eid(101)], "delta_mm": [1, 2, 3]},
            "change_type": {"op": "change_type", "id": "X", "target": _eid(101),
                            "type": _eid(5001)},
            "delete": {"op": "delete", "id": "X", "target": _eid(101)},
        }
        for name in sorted(MUTATION_ACCEPTANCE_OPS):
            payload = payloads.get(name)
            if payload is None:
                continue
            with self.subTest(op=name):
                plan = plan_program({"ir_version": "1.0", "ops": [payload],
                                     "allow_destructive": True})
                got = derive_mutation_expectation(plan)
                self.assertEqual(
                    1, len(got.claims) + len(got.blind_ops),
                    f"{name} не получил ни заявки, ни объявленной слепоты")


if __name__ == "__main__":
    unittest.main()
