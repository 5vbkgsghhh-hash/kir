"""A CREATED ELEMENT IS JUDGED BY THE PLACE IT ENDS UP, NOT WHERE IT STARTED.

WHAT WAS FOUND (2026-09-07, mandate F1/C01, link E-2 — the second half of
«the last legal writer»). E-1 closed a compositional defect for TWO writers
(`set_param.value_held`, `move_elements.location`) and NAMED as debt a
third case — the CREATION side:

    create_wall(W, (0,0)-(6000,0)); move_elements([W], +1000/0/0)

The final block `// post W` checked the wall's endpoints against the
AUTHORED p0/p1 AFTER the whole program, while by then the wall had legally
moved by +1000 mm, against a `create_wall.endpoint_mm` tolerance of 5.0 mm.
The building was built CORRECTLY, the answer is `postconditions_violated`
and a RollBack.

WHAT CURES THIS AND WHY NOT A STAGE. For E-1 the cure was a STAGE: the
witness moved inside its own operation. Here a stage does not fit, by two
measurements:

  * the operation block is printed BEFORE `doc.Regenerate()` (measured
    2026-09-07: `// operation W` at 3798, `doc.Regenerate()` at 4446,
    `// post W` at 4473) — witnesses that need a regenerated document
    cannot move there at all;
  * the cost: `endpoints` at the operation stage would shift 646 of the
    corpus's 2340 emissions (27.6%) and 25 of 75 goldens.

So ARITHMETIC was chosen instead: the final witness checks against the
OUTCOME of the last legal writer — the authored endpoints plus the summed
shift of every `move_elements` of the same program standing BELOW it
(`geom.program_shift_after`). With an empty shift the field is not attached
at all and the emission stays byte-identical.

FAIL CONTROL: put `shift=(0,0,0)` back into `_emit_wall` (or zero out
`geom.program_shift_after`) — tests 1 and 2 go red.
PASS CONTROL: a lone creation (test 3) moves no bytes, and the witness does
not go anywhere (test 4).

🔴 E-3 (2026-09-07): THE EIGHT REMAINING SPOTS ARE CLOSED, AND THE LIST IS
NOW CLOSED. E-2 carried the outcome to ONE emitter and named the other seven
`endpoint_witness` spots as its own limit. A probe of "created -> moved by
ref" over NINE creating ops gave **8 of 8** live false refusals: pipe, duct,
cable tray, conduit, both placeholders, beam and truss all expected authored
endpoints after a legal `move_elements`. All nine are checked by the class
`EveryCreateOpWithEndsIsJudgedByItsFinalPlace` — BY EMISSION, not by
retelling, and the parity corpus covers only two of them
(`create_wall`, `create_pipe`).

THE REMAINING DEBT IS NAMED AS A NUMBER, NOT SILENCE — tests 5 and 6 below.

Run:
    venv/bin/python -m pytest \
        kir/tests/test_a_created_element_is_judged_by_its_final_place.py -q
"""
from __future__ import annotations

import hashlib
import re
import unittest

from kir import geom, spec
from kir.compiler import compile_program
from kir.tests.fixtures import GROUND_SNAPSHOT

LVL = {"by": "element_id", "value": 42}
TOL = 5.0                      # create_wall.endpoint_mm, minted by the registry


def _eid(value: int) -> dict:
    return {"by": "element_id", "value": value}


def _ref(value: str) -> dict:
    return {"by": "ref", "value": value}


def _compile(ops, intent="итог последнего писателя"):
    return compile_program(
        {"ir_version": "1.0", "intent": intent, "ops": ops},
        "2026", snapshot=GROUND_SNAPSHOT)


_HEADER = re.compile(r"^\s*//\s+(\S+)\s+(\S+)\s*$")
_SENTINEL = "if (__post.Count > 0)"


def _stage_blocks(cs: str) -> dict[str, dict[str, str]]:
    """Break the emission into STAGES by its own headers.

    The same parser as `test_the_last_legal_writer_defines_the_final_state`
    — and deliberately the same one: two different readings of one emission
    would silently diverge.
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


#: Numbers the endpoint witness checks: `MM(__e0.X) - <NUMBER>`.
_EXPECTED = re.compile(r"MM\(__e(\d)\.([XYZ])\)\s*-\s*(-?\d+(?:\.\d+)?)")


def _endpoint_expectations(body: str) -> dict[str, float]:
    """Exactly what the endpoint witness expects, FROM THE EMISSION ITSELF.

    A NUMBER is read from the C#, not a retelling from Python: otherwise
    the instrument would be checking its own arithmetic, not what will
    travel to Revit.
    """
    return {f"e{i}.{axis}": float(value)
            for i, axis, value in _EXPECTED.findall(body)}


# --------------------------------------------------------------------------
# 1-2. CREATED AND MOVED
# --------------------------------------------------------------------------

_WALL_THEN_MOVE = [
    {"op": "create_wall", "id": "W", "p0_mm": [0, 0], "p1_mm": [6000, 0],
     "level": LVL},
    {"op": "move_elements", "id": "M", "targets": [_ref("W")],
     "delta_mm": [1000, 0, 0]},
]


class ACreatedWallThatTheSameProgramMoves(unittest.TestCase):

    def test_the_final_witness_expects_the_place_the_wall_ends_up(self):
        out = _compile(_WALL_THEN_MOVE)
        self.assertTrue(out.ok, [d.code for d in out.diagnostics])
        body = _stage_blocks(out.csharp)["post"].get("W", "")
        self.assertIn("endpoints mismatch (geometry)", body,
                      "свидетель концов пропал вовсе — это не починка, "
                      "а снятие проверки")
        got = _endpoint_expectations(body)
        self.assertEqual(1000.0, got["e0.X"],
                         "финальный свидетель ждёт АВТОРСКОЕ начало 0 у стены, "
                         "которую та же программа законно увезла на +1000 мм "
                         f"при допуске {TOL} мм — гарантированный "
                         "postconditions_violated и RollBack на верной программе")
        self.assertEqual(7000.0, got["e1.X"])
        self.assertEqual(0.0, got["e0.Y"])
        self.assertEqual(0.0, got["e1.Y"])

    def test_the_shift_is_bigger_than_the_tolerance_it_would_break(self):
        """A control of MEANING: the shift must be OBSERVABLE by the tolerance.

        A probe on a shift smaller than the tolerance would be green both
        before and after the fix — meaning it would not tell the fix apart
        from its absence.
        """
        shift = geom.program_shift_after(_WALL_THEN_MOVE, 0, "W")
        self.assertEqual((1000.0, 0.0, 0.0), shift)
        self.assertGreater(abs(shift[0]), TOL,
                           "сдвиг меньше допуска: зонд не различает починку")

    def test_two_moves_of_one_created_wall_compose(self):
        """Two legal moves compose, they do not contend."""
        out = _compile([
            {"op": "create_wall", "id": "W", "p0_mm": [0, 0],
             "p1_mm": [6000, 0], "level": LVL},
            {"op": "move_elements", "id": "M1", "targets": [_ref("W")],
             "delta_mm": [1000, 0, 0]},
            {"op": "move_elements", "id": "M2", "targets": [_ref("W")],
             "delta_mm": [0, 500, 0]},
        ])
        self.assertTrue(out.ok, [d.code for d in out.diagnostics])
        got = _endpoint_expectations(_stage_blocks(out.csharp)["post"]["W"])
        self.assertEqual({"e0.X": 1000.0, "e0.Y": 500.0,
                          "e1.X": 7000.0, "e1.Y": 500.0}, got)


# --------------------------------------------------------------------------
# 3-4. PASS CONTROL: NOTHING MOVES IF NOBODY MOVED IT
# --------------------------------------------------------------------------

_LONE_WALL = [{"op": "create_wall", "id": "W", "p0_mm": [0, 0],
               "p1_mm": [6000, 0], "level": LVL}]


class AWallNobodyMoves(unittest.TestCase):

    def test_the_emission_is_byte_identical_to_the_authored_intent(self):
        """An empty shift must not move a SINGLE BYTE.

        🔴 THIS IS A PIN ON COST, NOT ON BEAUTY. `6000 + 0.0` is `6000.0`, a
        different literal; an innocent "add zero" would have rewritten 646
        of the corpus's 2340 emissions without fixing a single one. The
        measurement is held HERE, not only in the parity freeze, because
        the freeze answers for the whole corpus at once, while this pin is
        about the cause.
        """
        got = _endpoint_expectations(
            _stage_blocks(_compile(_LONE_WALL).csharp)["post"]["W"])
        self.assertEqual({"e0.X": 0.0, "e0.Y": 0.0,
                          "e1.X": 6000.0, "e1.Y": 0.0}, got)
        # and the LITERALS are the same, not just the numbers
        body = _stage_blocks(_compile(_LONE_WALL).csharp)["post"]["W"]
        self.assertIn("MM(__e1.X) - 6000)", body,
                      "целое 6000 стало дробным литералом — байты корпуса "
                      "поехали от сложения с нулём")

    def test_the_synthetic_field_is_absent_when_nothing_moves(self):
        """The field is not attached at all: there is nothing to strip and nothing to get wrong."""
        self.assertEqual((0.0, 0.0, 0.0),
                         geom.program_shift_after(_LONE_WALL, 0, "W"))

    def test_a_move_standing_ABOVE_the_creation_does_not_count(self):
        """The order of the program is the order of the effects.

        A `move_elements` standing BEFORE the creation cannot refer to a
        `ref` that does not exist yet, and crediting it to the outcome
        would conjure a shift out of nowhere.
        """
        ops = [{"op": "move_elements", "id": "M", "targets": [_ref("W")],
                "delta_mm": [1000, 0, 0]},
               {"op": "create_wall", "id": "W", "p0_mm": [0, 0],
                "p1_mm": [6000, 0], "level": LVL}]
        self.assertEqual((0.0, 0.0, 0.0), geom.program_shift_after(ops, 1, "W"))


# --------------------------------------------------------------------------
# 4b. A CLOSED LIST: ALL NINE CREATING OPS WITH ENDPOINTS (E-3, 2026-09-07)
#
# 🔴 A TABLE, NOT NINE COPIES OF ONE TEST, AND NOT ONE TEST FOR A
# REPRESENTATIVE. A representative ("let's check on the pipe, the rest are
# the same") is exactly the shape that made E-2 report "the shift was
# carried through" while seven spots were left uncarried. Here every op
# presents ITS OWN numbers from ITS OWN emission.
# --------------------------------------------------------------------------

_SHIFT = [1000.0, 0.0, 500.0]

#: op -> (creating dict, endpoint expectation AFTER the shift)
_CREATE_OPS_WITH_ENDS = {
    "create_wall": (
        {"op": "create_wall", "id": "X", "p0_mm": [0, 0], "p1_mm": [6000, 0],
         "level": LVL},
        {"e0.X": 1000.0, "e0.Y": 0.0, "e1.X": 7000.0, "e1.Y": 0.0}),
    "create_pipe": (
        {"op": "create_pipe", "id": "X", "p0_mm": [0, 0, 2700],
         "p1_mm": [3000, 0, 2900], "level": LVL, "diameter_mm": 50},
        {"e0.X": 1000.0, "e0.Y": 0.0, "e0.Z": 3200.0,
         "e1.X": 4000.0, "e1.Y": 0.0, "e1.Z": 3400.0}),
    "create_duct": (
        {"op": "create_duct", "id": "X", "p0_mm": [0, 0, 2700],
         "p1_mm": [3000, 0, 2900], "level": LVL, "diameter_mm": 200},
        {"e0.X": 1000.0, "e0.Y": 0.0, "e0.Z": 3200.0,
         "e1.X": 4000.0, "e1.Y": 0.0, "e1.Z": 3400.0}),
    "create_cable_tray": (
        {"op": "create_cable_tray", "id": "X", "p0_mm": [0, 0, 3000],
         "p1_mm": [6000, 0, 3000], "level": LVL},
        {"e0.X": 1000.0, "e0.Y": 0.0, "e0.Z": 3500.0,
         "e1.X": 7000.0, "e1.Y": 0.0, "e1.Z": 3500.0}),
    "create_conduit": (
        {"op": "create_conduit", "id": "X", "p0_mm": [0, 0, 3000],
         "p1_mm": [6000, 0, 3000], "level": LVL},
        {"e0.X": 1000.0, "e0.Y": 0.0, "e0.Z": 3500.0,
         "e1.X": 7000.0, "e1.Y": 0.0, "e1.Z": 3500.0}),
    "create_pipe_placeholder": (
        {"op": "create_pipe_placeholder", "id": "X", "p0_mm": [0, 1000, 2800],
         "p1_mm": [6000, 1000, 2800], "level": LVL},
        {"e0.X": 1000.0, "e0.Y": 1000.0, "e0.Z": 3300.0,
         "e1.X": 7000.0, "e1.Y": 1000.0, "e1.Z": 3300.0}),
    "create_duct_placeholder": (
        {"op": "create_duct_placeholder", "id": "X", "p0_mm": [0, 2000, 3200],
         "p1_mm": [6000, 2000, 3200], "level": LVL},
        {"e0.X": 1000.0, "e0.Y": 2000.0, "e0.Z": 3700.0,
         "e1.X": 7000.0, "e1.Y": 2000.0, "e1.Z": 3700.0}),
    "create_beam": (
        {"op": "create_beam", "id": "X", "p0_mm": [0, 0, 3000],
         "p1_mm": [6000, 0, 3000], "level": LVL,
         "symbol": {"by": "name", "value": "Балка 200x400"}},
        {"e0.X": 1000.0, "e0.Y": 0.0, "e0.Z": 3500.0,
         "e1.X": 7000.0, "e1.Y": 0.0, "e1.Z": 3500.0}),
    # THE TRUSS IS FLAT BY CONSTRUCTION, AND THIS IS NOT A GAP IN THE TABLE.
    # Its endpoint witness compares only X and Y: the base elevation is
    # known only in the model (the `base_elevation` obligation computes it
    # at runtime from the level's plane). A vertical move of a truss was not
    # checked by this witness before E-3 or after — the limit is named, not
    # worked around.
    "create_truss": (
        {"op": "create_truss", "id": "X", "p0_mm": [0, 0], "p1_mm": [12000, 0],
         "level": LVL, "type": {"by": "name", "value": "Ферма стропильная 12м"}},
        {"e0.X": 1000.0, "e0.Y": 0.0, "e1.X": 13000.0, "e1.Y": 0.0}),
}


class EveryCreateOpWithEndsIsJudgedByItsFinalPlace(unittest.TestCase):
    """A closed list: EVERY creating op with endpoints has its own numbers."""

    def test_the_list_covers_every_endpoint_witness_owner(self):
        """The list of ops comes FROM THE REGISTRY, not rewritten alongside it.

        The owners of the synthetic field are declared in
        `spec.SYNTHETIC_FIELDS`; if someone adds a ninth reader and does
        not add it a row in the table, the test goes red here, not silent.
        """
        self.assertEqual(set(spec.SYNTHETIC_FIELDS[spec.SYNTHETIC_FINAL_SHIFT]),
                         set(_CREATE_OPS_WITH_ENDS) | {"create_window", "create_door"})

    def test_each_op_expects_the_place_its_element_ends_up(self):
        for name, (create, expected) in sorted(_CREATE_OPS_WITH_ENDS.items()):
            with self.subTest(op=name):
                out = _compile([dict(create),
                                {"op": "move_elements", "id": "M",
                                 "targets": [_ref("X")], "delta_mm": _SHIFT}])
                self.assertTrue(out.ok, [d.code for d in out.diagnostics])
                body = _stage_blocks(out.csharp)["post"].get("X", "")
                self.assertIn("endpoints mismatch (geometry)", body,
                              "свидетель концов пропал вовсе — это не починка, "
                              "а снятие проверки")
                self.assertEqual(expected, _endpoint_expectations(body))

    def test_without_a_move_every_op_keeps_its_authored_literals(self):
        """PASS CONTROL on all nine: with no transfer, bytes do not move.

        The same pin on COST as for the lone wall, but over the whole list:
        if a zero shift reaches an addition anywhere, the integer `6000`
        becomes `6000.0` — a different literal, and the corpus moves for
        zero fixes.
        """
        for name, (create, _) in sorted(_CREATE_OPS_WITH_ENDS.items()):
            with self.subTest(op=name):
                out = _compile([dict(create)])
                self.assertTrue(out.ok, [d.code for d in out.diagnostics])
                body = _stage_blocks(out.csharp)["post"].get("X", "")
                got = _endpoint_expectations(body)
                p0, p1 = create["p0_mm"], create["p1_mm"]
                axes = "XYZ"
                want = {f"e0.{axes[i]}": float(v) for i, v in enumerate(p0)}
                want.update({f"e1.{axes[i]}": float(v) for i, v in enumerate(p1)})
                # for a truss the witness is flat: Z is not compared in the emission
                want = {k: v for k, v in want.items() if k in got}
                self.assertEqual(want, got)
                for value in (p0 + p1):
                    if float(value) == int(value):
                        self.assertNotIn(f"- {float(value)})", body,
                                         "целое стало дробным литералом — "
                                         "байты поехали от сложения с нулём")


# --------------------------------------------------------------------------
# 5-6. DEBT NAMED AS A NUMBER ON 2026-09-07, CLOSED ON 2026-09-08 (E-4).
#
# 🔴 THE PINS ARE LIFTED, NOT DISABLED. Both scenarios stood under
# `xfail(strict=True)` and WENT RED without it (measured 09-08,
# `pytest --runxfail`: 2 failed) — that was itself the setup control. Now
# both are green on an ordinary run, and the class changed its name: "debt
# the wave does not close" became "debt the wave closed".
#
# WHAT CLOSED IT, ONE PHRASE EACH:
#
#   * `create -> set_param(same parameter)` — the table "Revit parameter
#     name <-> obligation key" is set up IN THE REGISTRY as a single
#     carrier (`registry_base.REVIT_PARAM_OBLIGATIONS`), the law of the
#     program's tail as a single body (`emit_core.program_tail_writes`),
#     and the creation witness, whose parameter is rewritten below, runs at
#     the stage of ITS OWN operation. Neither the predicate, nor the
#     tolerance, nor the key was touched.
#   * `create -> delete` — final witnesses of a created element are not
#     emitted if the same program legally deleted it. No witness of absence
#     is set up: it already exists and belongs to the deleting op
#     (`// post D`).
#
# FAIL CONTROL for both — `test_a_parameter_name_reaches_its_obligation.py`:
# break the table's row (name -> the wrong key) or disable the conditional
# stage, and the scenes go red again.
# --------------------------------------------------------------------------

class TheDebtThisWaveClosed(unittest.TestCase):

    def test_a_later_set_param_does_not_veto_the_creation_witness(self):
        out = _compile([
            {"op": "create_wall", "id": "W", "p0_mm": [0, 0], "p1_mm": [6000, 0],
             "level": LVL, "base_offset_mm": 100.0},
            {"op": "set_param", "id": "S", "target": _ref("W"),
             "param": "Base Offset", "value": {"value": 500.0, "unit": "mm"}},
        ])
        self.assertTrue(out.ok, [d.code for d in out.diagnostics])
        self.assertNotIn("base offset mismatch",
                         _stage_blocks(out.csharp)["post"].get("W", ""),
                         "финальный свидетель W пришпиливает отменённые 100 мм")

    def test_a_deleted_element_carries_no_final_geometry_witness(self):
        out = compile_program(
            {"ir_version": "1.0", "intent": "создал и удалил",
             "allow_destructive": True,
             "ops": [
                 {"op": "create_wall", "id": "W", "p0_mm": [0, 0],
                  "p1_mm": [6000, 0], "level": LVL},
                 {"op": "delete", "id": "D", "target": _ref("W")}]},
            "2026", snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.code for d in out.diagnostics])
        self.assertNotIn("endpoints mismatch (geometry)",
                         _stage_blocks(out.csharp)["post"].get("W", ""),
                         "финальный свидетель читает ЗАКОННО УДАЛЁННЫЙ элемент")
        # 🔴 THE GUARANTEE IS HANDED OVER, NOT LIFTED. Removing the final
        # block without saying WHO now bears witness would trade a false
        # refusal for a silently unchecked element — the exact swap
        # `emit_model`'s fail-closed on an empty post exists to forbid. The
        # witness is here, and it belongs to the DELETING op.
        self.assertIn("doc.GetElement(__delid_D)",
                      _stage_blocks(out.csharp)["post"].get("D", ""),
                      "отсутствие элемента не свидетельствует никто")


class TheSyntheticFieldHasOneAuthority(unittest.TestCase):

    def test_the_name_is_declared_once_and_owned_by_a_real_op(self):
        self.assertEqual("__final_shift__", spec.SYNTHETIC_FINAL_SHIFT)
        owners = spec.SYNTHETIC_FIELDS[spec.SYNTHETIC_FINAL_SHIFT]
        self.assertTrue(owners, "владельцев ноль — запись мёртвая")
        for op in owners:
            self.assertIn(op, spec.OPS, f"владелец {op!r} не оп реестра")


if __name__ == "__main__":
    unittest.main()
