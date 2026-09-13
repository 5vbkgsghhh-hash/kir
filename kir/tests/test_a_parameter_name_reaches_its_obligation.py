"""A REVIT PARAMETER NAME REACHES ITS OBLIGATION, AND IT HAS ONE TABLE.

WHAT WAS FOUND (07.09.2026, link E-2/E-3 "the last legitimate writer,"
closed 08.09.2026 by link E-4). The program

    create_wall(W, base_offset_mm=100); set_param(W, "Base Offset", 500мм)

builds the building CORRECTLY and was getting `postconditions_violated`
with a RollBack: the final CREATION witness was pinned to the reverted
100 mm. The E-2/E-3 arithmetic does not fit here — the value comes from A
DIFFERENT OP, not from a shift within the program; this is cured by a
STAGE, and the stage was blocked on a missing link.

WHY THE LINK WAS MISSING, BY A RECONNAISSANCE MEASUREMENT ON 08.09
(15 min): `set_param` addresses the parameter by its REVIT NAME
(`GetParameters("Base Offset")`), the creation witness is pinned by the
OBLIGATION KEY (`base_offset`), and the literal `"Base Offset"` occurred
**ZERO** times in the non-test tree. There was nothing to connect one to
the other with — not in the registry, not in the certificate, not in the
emitter — that is, the table did not exist at all, rather than existing
as a second copy.

THIS FILE IS THE TABLE'S INSTRUMENT, AND IT GUARDS THREE DIFFERENT THINGS:

  1. **the line is verifiable by emission**: a key declared by a line must
     read EXACTLY the `BuiltInParameter` that same line names. A line
     pointing to the wrong key goes red — this is the mandate's FAIL
     CONTROL;
  2. **there is one owner**: the Revit parameter's name lives in the tree
     in exactly one non-test file — the registry. A second name<->key
     dictionary goes red;
  3. **the conditional stage works and is not weakened**: turn off the
     program-tail law — both debt scenes go red again; leave it on — the
     witness stands on the operation's stage with THE SAME key, predicate,
     and tolerance.

Run:
    venv/bin/python -m pytest \
        kir/tests/test_a_parameter_name_reaches_its_obligation.py -q
"""
from __future__ import annotations

import ast
import os
import pathlib
import re
import tempfile
import unittest
from dataclasses import replace as dc_replace

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_e4_queue.jsonl"))

from kir import emit_core, ground as ground_mod, spec  # noqa: E402
from kir.authoring import _EMITTERS  # noqa: E402
from kir.compiler import _parse_and_check, compile_program  # noqa: E402
from kir.registry_base import (  # noqa: E402
    REVIT_PARAM_OBLIGATIONS,
    obligation_for_revit_param,
)
from kir.tests.fixtures import GROUND_SNAPSHOT  # noqa: E402
from kir.translation_cert import (  # noqa: E402
    _ensure_table,
    certify_op,
    certify_program,
)

IR_ROOT = pathlib.Path(__file__).resolve().parents[1]
LVL = {"by": "name", "value": "Этаж 1"}
VER = "2026"

#: The program that carries EVERY line of this op's table through to emission.
#:
#: 🔴 THIS IS NOT A SECOND TABLE. There is not a single Revit parameter name
#: here, nor a single obligation key — only IR fields by which the
#: obligation's gate is opened (`Obligation.param` is read from the
#: certificate, see `_gating_param`). Copy a key in here, and the
#: instrument would start confirming itself.
_REACHING_PROGRAMS: dict[str, list[dict]] = {
    "create_wall": [
        {"op": "create_level", "id": "L2", "elev_mm": 6000, "name": "Этаж 2"},
        {"op": "create_wall", "id": "X", "p0_mm": [0, 0], "p1_mm": [6000, 0],
         "level": LVL, "base_offset_mm": 100.0,
         "top_level": {"by": "ref", "value": "L2"}, "top_offset_mm": 50.0},
    ],
    # The wall-height witness lives behind an INVERTED gate (`unless_param=
    # top_level`), so it has its own program — WITHOUT a top level.
    "create_wall/height": [
        {"op": "create_wall", "id": "X", "p0_mm": [0, 0], "p1_mm": [6000, 0],
         "level": LVL, "height_mm": 3200.0},
    ],
    "create_column": [
        {"op": "create_column", "id": "X", "xy": [4000, 3000], "level": LVL,
         "base_offset_mm": 100.0},
    ],
    # A column's top offset requires a top ATTACHMENT — without it the
    # emitter does not place the witness at all (correctly so: there is
    # nothing to write).
    "create_column/top_offset": [
        {"op": "create_level", "id": "L2", "elev_mm": 6000, "name": "Этаж 2"},
        {"op": "create_column", "id": "X", "xy": [4000, 3000], "level": LVL,
         "top_level": {"by": "ref", "value": "L2"}, "top_offset_mm": 150.0},
    ],
    # A room needs a CLOSED contour: without it there is nowhere to place `NewRoom`.
    "create_room": [
        {"op": "create_wall", "id": "WA", "p0_mm": [0, 0], "p1_mm": [6000, 0],
         "level": LVL},
        {"op": "create_wall", "id": "WB", "p0_mm": [6000, 0],
         "p1_mm": [6000, 5000], "level": LVL},
        {"op": "create_wall", "id": "WC", "p0_mm": [6000, 5000],
         "p1_mm": [0, 5000], "level": LVL},
        {"op": "create_wall", "id": "WD", "p0_mm": [0, 5000], "p1_mm": [0, 0],
         "level": LVL},
        {"op": "create_room", "id": "X", "xy": [1000, 1000], "level": LVL,
         "upper_offset_mm": 2700.0},
    ],
    "create_floor": [
        {"op": "create_floor", "id": "X",
         "outline": [[0, 0], [8000, 0], [8000, 6000], [0, 6000]],
         "level": LVL, "height_offset_mm": 100.0},
    ],
    "create_ceiling": [
        {"op": "create_ceiling", "id": "X",
         "contour": {"outer": {"shape": "poly",
                               "points_mm": [[0, 0], [6000, 0],
                                             [6000, 4000], [0, 4000]]}},
         "level": LVL,
         "type": {"by": "name", "value": "Потолок подвесной 600x600"},
         "height_offset_mm": 2700.0},
    ],
}


def _grounded(ops: list[dict], oid: str = "X", destructive: bool = False):
    body = {"ir_version": "1.0", "intent": "прибор таблицы", "ops": ops}
    if destructive:
        body["allow_destructive"] = True
    grounded = ground_mod.ground(_parse_and_check(body), GROUND_SNAPSHOT)
    return [op for op in grounded if op["id"] == oid][0]


def _checks(op: dict):
    _decl, _create, post, _readback = _EMITTERS[op["op"]](op, VER, "kir:e4")
    return list(post.checks if hasattr(post, "checks") else post)


def _reaching_ops():
    """(op, Revit parameter name, key, BuiltInParameter, emission witnesses)."""

    for op_name, row in REVIT_PARAM_OBLIGATIONS.items():
        for param_name, (key, bip) in row.items():
            slot = f"{op_name}/{key}"
            ops = _REACHING_PROGRAMS.get(slot) or _REACHING_PROGRAMS[op_name]
            yield op_name, param_name, key, bip, _checks(_grounded(ops))


def _post_blocks(cs: str) -> dict:
    """Final emission blocks by their own headers (`// post <id>`).

    The same parse as `test_a_created_element_is_judged_by_its_final_place`
    — and deliberately the same: two readings of one emission would drift
    apart silently.
    """

    out: dict = {}
    oid = None
    body: list = []
    for line in cs.splitlines():
        head = re.match(r"^\s*//\s+(\S+)\s+(\S+)\s*$", line)
        if head is not None:
            if oid is not None:
                out[oid] = "\n".join(body)
            oid, body = (head.group(2), []) if head.group(1) == "post" \
                else (None, [])
            continue
        if oid is not None:
            if "if (__post.Count" in line:
                out[oid] = "\n".join(body)
                oid, body = None, []
                continue
            body.append(line)
    if oid is not None:
        out[oid] = "\n".join(body)
    return out


def _row_holds(key: str, bip: str, checks) -> bool:
    """THE SINGLE predicate for a line: there is exactly one key and it
    reads ITS OWN BIP.

    The very same predicate stands in both the check over all lines and in
    the mutation — otherwise the fail control would be checking something
    different from what the pass control confirms.
    """

    found = [c for c in checks if c.obligation_key == key]
    if len(found) != 1:
        return False
    return f"BuiltInParameter.{bip}" in (found[0].reader_cs
                                         + found[0].verdict_cs)


def _obligation(op_name: str, key: str):
    """The certificate's obligation with this key (or a failure with an address)."""

    for obligation in _ensure_table()[op_name].obligations:
        if obligation.key == key:
            return obligation
    raise AssertionError(f"{op_name}: обязательства с ключом {key!r} нет")


def _code_string_literals(path: pathlib.Path) -> set:
    """String literals of the file's CODE — without comments and without docstrings.

    🔴 WHY NOT `grep`. An instrument counting occurrences as text would
    have declared a COMMENT a second dictionary
    (`authoring.py:358` explains that WALL_USER_HEIGHT_PARAM is
    "Unconnected Height"), that is, it would demand the explanation be
    thrown out for the sake of form. A second dictionary is what the code
    ACTUALLY READS, and what it reads is the literal.
    """

    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if body and isinstance(body[0], ast.Expr) \
                    and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                docstrings.add(id(body[0].value))
    return {n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and id(n) not in docstrings}


class TheRowIsVerifiedByEmission(unittest.TestCase):
    """A table row is not a claim but a checkable assertion."""

    def test_every_row_key_reads_the_builtin_parameter_it_declares(self):
        for op_name, param_name, key, bip, checks in _reaching_ops():
            with self.subTest(op=op_name, param=param_name):
                self.assertTrue(
                    _row_holds(key, bip, checks),
                    f"{op_name}/{param_name}: ключ {key!r} либо отсутствует в "
                    f"эмиссии, либо читает НЕ {bip}")

    def test_every_row_names_a_registry_op_and_a_certified_obligation(self):
        for op_name, param_name, key, _bip, _checks_ in _reaching_ops():
            with self.subTest(op=op_name, param=param_name):
                self.assertIn(op_name, spec.OPS,
                              f"{op_name!r} — не оп реестра")
                # An obligation with this key must be in the certificate's
                # table: a line naming a key that nothing proves would be
                # a dead marker.
                self.assertEqual(key, _obligation(op_name, key).key)

    def test_a_row_moved_to_a_foreign_key_is_caught(self):
        """FAIL CONTROL of the mandate: name -> wrong key => THE SAME
        predicate goes red.

        The mutation taken is REAL and harmful: `"Base Offset" ->
        endpoints` would move to the operation's stage a GEOMETRY witness
        that needs a regenerated document (measured 07.09: the operation
        block is printed BEFORE `doc.Regenerate()` — `// operation W` 3798,
        `Regenerate` 4446). The LIVE table is mutated and restored in
        `finally`.
        """
        row = REVIT_PARAM_OBLIGATIONS["create_wall"]
        live = row["Base Offset"]
        row["Base Offset"] = ("endpoints", "WALL_BASE_OFFSET")
        try:
            checks = _checks(_grounded(_REACHING_PROGRAMS["create_wall"]))
            self.assertFalse(
                _row_holds("endpoints", "WALL_BASE_OFFSET", checks),
                "прибор строки НЕ поймал чужой ключ — контроль пуст")
            # And the harm is real: the law really would have moved the geometry to the operation.
            grounded = ground_mod.ground(_parse_and_check(
                {"ir_version": "1.0", "intent": "мутация",
                 "ops": [{"op": "create_wall", "id": "W", "p0_mm": [0, 0],
                          "p1_mm": [6000, 0], "level": LVL,
                          "base_offset_mm": 100.0},
                         {"op": "set_param", "id": "S",
                          "target": {"by": "ref", "value": "W"},
                          "param": "Base Offset",
                          "value": {"value": 500.0, "unit": "mm"}}]}),
                GROUND_SNAPSHOT)
            self.assertEqual(frozenset({"endpoints"}),
                             emit_core.program_tail_writes(grounded, 0)[0])
        finally:
            row["Base Offset"] = live
        self.assertEqual(("base_offset", "WALL_BASE_OFFSET"),
                         REVIT_PARAM_OBLIGATIONS["create_wall"]["Base Offset"],
                         "мутация не откатилась — прибор отравлен")


class TheTableHasOneOwner(unittest.TestCase):

    def test_no_second_dictionary_of_revit_names_hides_in_the_tree(self):
        """A Revit parameter's name lives in ONE non-test file — the registry.

        FAIL CONTROL: write `"Base Offset"` into the emitter or into the
        certificate — there will be two files, and the test will go red
        naming the offender.
        """
        owner = IR_ROOT / "registry_base.py"
        names = {name for row in REVIT_PARAM_OBLIGATIONS.values()
                 for name in row}
        for name in sorted(names):
            with self.subTest(param=name):
                hits = []
                for path in IR_ROOT.rglob("*.py"):
                    if "tests" in path.parts:
                        continue
                    if name in _code_string_literals(path):
                        hits.append(str(path.relative_to(IR_ROOT)))
                self.assertEqual([str(owner.relative_to(IR_ROOT))], hits,
                                 f"{name!r}: владельцев не один")

    def test_the_only_reader_answers_none_for_a_stranger(self):
        self.assertEqual("base_offset",
                         obligation_for_revit_param("create_wall",
                                                    "Base Offset"))
        self.assertIsNone(obligation_for_revit_param("create_wall",
                                                     "Comments"))
        self.assertIsNone(obligation_for_revit_param("create_grid",
                                                     "Base Offset"))


class TheProgramTailIsOneLaw(unittest.TestCase):

    def test_a_later_set_param_moves_exactly_its_own_key(self):
        ops = [{"op": "create_wall", "id": "W", "p0_mm": [0, 0],
                "p1_mm": [6000, 0], "level": LVL, "base_offset_mm": 100.0},
               {"op": "set_param", "id": "S",
                "target": {"by": "ref", "value": "W"},
                "param": "Base Offset",
                "value": {"value": 500.0, "unit": "mm"}}]
        grounded = ground_mod.ground(
            _parse_and_check({"ir_version": "1.0", "intent": "t",
                              "ops": ops}), GROUND_SNAPSHOT)
        rewritten, deleted = emit_core.program_tail_writes(grounded, 0)
        self.assertEqual(frozenset({"base_offset"}), rewritten)
        self.assertIsNone(deleted)
        staged = {c.obligation_key: c.stage for c in emit_core
                  .restage_for_program_tail(_checks(grounded[0]),
                                            rewritten, deleted)}
        self.assertEqual("operation", staged["base_offset"])
        # THE CHECK IS NOT WEAKENED: EXACTLY one key moved, the neighbors stand where they stood.
        self.assertEqual("final", staged["endpoints"])
        self.assertEqual("final", staged["base_constraint"])

    def test_a_set_param_on_an_unrelated_name_moves_nothing(self):
        ops = [{"op": "create_wall", "id": "W", "p0_mm": [0, 0],
                "p1_mm": [6000, 0], "level": LVL, "base_offset_mm": 100.0},
               {"op": "set_param", "id": "S",
                "target": {"by": "ref", "value": "W"},
                "param": "Length",
                "value": {"value": 700.0, "unit": "mm"}}]
        grounded = ground_mod.ground(
            _parse_and_check({"ir_version": "1.0", "intent": "t",
                              "ops": ops}), GROUND_SNAPSHOT)
        rewritten, deleted = emit_core.program_tail_writes(grounded, 0)
        self.assertEqual(frozenset(), rewritten)
        self.assertIsNone(deleted)
        checks = _checks(grounded[0])
        self.assertIs(checks,
                      emit_core.restage_for_program_tail(checks, rewritten,
                                                         deleted),
                      "пустой хвост ПЕРЕСОБРАЛ свидетелей — байты под угрозой")

    def test_a_set_param_on_a_foreign_element_moves_nothing(self):
        """Addressing by `element_id` — a foreign element, not our obligation."""

        ops = [{"op": "create_wall", "id": "W", "p0_mm": [0, 0],
                "p1_mm": [6000, 0], "level": LVL, "base_offset_mm": 100.0},
               {"op": "set_param", "id": "S",
                "target": {"by": "element_id", "value": 777},
                "param": "Base Offset",
                "value": {"value": 500.0, "unit": "mm"}}]
        grounded = ground_mod.ground(
            _parse_and_check({"ir_version": "1.0", "intent": "t",
                              "ops": ops}), GROUND_SNAPSHOT)
        self.assertEqual((frozenset(), None),
                         emit_core.program_tail_writes(grounded, 0))

    def test_a_set_param_standing_ABOVE_the_creation_does_not_count(self):
        """Program order is the order of effects (the same law as for the shift)."""

        ops = [{"op": "set_param", "id": "S",
                "target": {"by": "element_id", "value": 777},
                "param": "Base Offset",
                "value": {"value": 500.0, "unit": "mm"}},
               {"op": "create_wall", "id": "W", "p0_mm": [0, 0],
                "p1_mm": [6000, 0], "level": LVL, "base_offset_mm": 100.0}]
        grounded = ground_mod.ground(
            _parse_and_check({"ir_version": "1.0", "intent": "t",
                              "ops": ops}), GROUND_SNAPSHOT)
        self.assertEqual((frozenset(), None),
                         emit_core.program_tail_writes(grounded, 1))


class TheCertificateReadsTheSameLaw(unittest.TestCase):

    def _program(self, ops, destructive=False):
        body = {"ir_version": "1.0", "intent": "сертификат", "ops": ops}
        if destructive:
            body["allow_destructive"] = True
        return ground_mod.ground(_parse_and_check(body), GROUND_SNAPSHOT)

    def test_a_rewritten_creation_witness_stays_proven(self):
        grounded = self._program([
            {"op": "create_wall", "id": "W", "p0_mm": [0, 0],
             "p1_mm": [6000, 0], "level": LVL, "base_offset_mm": 100.0},
            {"op": "set_param", "id": "S",
             "target": {"by": "ref", "value": "W"}, "param": "Base Offset",
             "value": {"value": 500.0, "unit": "mm"}}])
        cert = certify_program(grounded, VER)
        self.assertTrue(cert.proven, cert.gaps)

    def test_a_witness_at_the_wrong_stage_is_still_refused(self):
        """🔴 THE STAGE CHECK IS STILL STRICT — A MUTATION, NOT AN ASSURANCE.

        The emitter is substituted so that `base_offset` moves to the
        operation's stage ON ITS OWN, with no program tail involved at
        all. The certificate must declare the witness absent: "moved by
        the law" and "moved on its own" are different things, and if the
        new branch confused them, the stage would stop meaning anything at
        all.

        The same text, but WITH THE LAW naming the key, must be proven —
        otherwise the test would be about impossibility, not about
        strictness.
        """
        op = _grounded(_REACHING_PROGRAMS["create_wall"])
        live = _EMITTERS["create_wall"]

        def _moved(o, ver, stamp, isolation="atomic"):
            decl, create, post, readback = live(o, ver, stamp, isolation)
            return decl, create, [
                dc_replace(c, stage="operation")
                if c.obligation_key == "base_offset" else c
                for c in post], readback

        _EMITTERS["create_wall"] = _moved
        try:
            self.assertTrue(certify_op(op, VER, rewritten_by_tail=frozenset(
                {"base_offset"})).proven)
            blind = certify_op(op, VER)          # the tail is EMPTY ⇒ we wait for `final`
            self.assertFalse(blind.proven,
                             "свидетель уехал на операцию без закона, а "
                             "сертификат этого не заметил — сверка стадии "
                             "перестала быть строгой")
            self.assertTrue(any("base_offset" in gap for gap in blind.gaps),
                            blind.gaps)
        finally:
            _EMITTERS["create_wall"] = live
        self.assertIs(live, _EMITTERS["create_wall"], "мутация не откатилась")

    def test_a_deleted_element_is_a_named_absence_not_a_gap(self):
        grounded = self._program([
            {"op": "create_wall", "id": "W", "p0_mm": [0, 0],
             "p1_mm": [6000, 0], "level": LVL},
            {"op": "delete", "id": "D",
             "target": {"by": "ref", "value": "W"}}], destructive=True)
        cert = certify_program(grounded, VER)
        self.assertTrue(cert.proven, cert.gaps)
        wall = cert.ops[0]
        reasons = [c.reason for c in wall.clauses if c.clause.startswith(
            "LocationCurve endpoints")]
        self.assertEqual(1, len(reasons))
        self.assertIn("законно удалён опом 'D'", reasons[0])


class SwitchingOffTheLawReddensTheScenes(unittest.TestCase):
    """FAIL CONTROL of the mandate: turn off the conditional stage -> the scenes go red."""

    def _emit(self, ops, destructive=False):
        body = {"ir_version": "1.0", "intent": "контроль", "ops": ops}
        if destructive:
            body["allow_destructive"] = True
        out = compile_program(body, VER, snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.code for d in out.diagnostics])
        return out.csharp

    _SET_PARAM_SCENE = [
        {"op": "create_wall", "id": "W", "p0_mm": [0, 0], "p1_mm": [6000, 0],
         "level": LVL, "base_offset_mm": 100.0},
        {"op": "set_param", "id": "S", "target": {"by": "ref", "value": "W"},
         "param": "Base Offset", "value": {"value": 500.0, "unit": "mm"}}]
    _DELETE_SCENE = [
        {"op": "create_wall", "id": "W", "p0_mm": [0, 0], "p1_mm": [6000, 0],
         "level": LVL},
        {"op": "delete", "id": "D", "target": {"by": "ref", "value": "W"}}]

    def _post_block(self, cs: str, oid: str) -> str:
        # ONE emission parser per file (see `_post_blocks`): a second
        # reading of the same emission would drift from the first silently.
        return _post_blocks(cs).get(oid, "")

    def test_the_law_off_brings_both_false_refusals_back(self):
        import kir.authoring as authoring
        live = authoring.program_tail_writes
        authoring.program_tail_writes = lambda ops, index: (frozenset(), None)
        try:
            dead_set = self._post_block(self._emit(self._SET_PARAM_SCENE), "W")
            dead_del = self._post_block(
                self._emit(self._DELETE_SCENE, destructive=True), "W")
        finally:
            authoring.program_tail_writes = live
        self.assertIn("base offset mismatch", dead_set,
                      "закон выключен, а ложный отказ не вернулся — "
                      "значит его чинило что-то другое")
        self.assertIn("endpoints mismatch (geometry)", dead_del)
        # And with the law live, neither is present — the pass control is in the same test.
        self.assertNotIn("base offset mismatch",
                         self._post_block(self._emit(self._SET_PARAM_SCENE),
                                          "W"))
        self.assertNotIn(
            "endpoints mismatch (geometry)",
            self._post_block(self._emit(self._DELETE_SCENE,
                                        destructive=True), "W"))


class ADeletedCreationIsWitnessedByItsDeleter(unittest.TestCase):
    """A TABLE, NOT A REPRESENTATIVE: `create -> delete` on EVERY op of the table.

    "Let's check on a wall, the rest are the same" is exactly the shape
    because of which E-2 reported "the shift is threaded through" while
    seven places were not threaded through (see the header of
    `test_a_created_element_is_judged_by_its_final_place.py`). Here every
    op presents ITS OWN emission and ITS OWN certificate.
    """

    def test_no_op_of_the_table_reads_its_deleted_element(self):
        for op_name in sorted(REVIT_PARAM_OBLIGATIONS):
            with self.subTest(op=op_name):
                ops = list(_REACHING_PROGRAMS[op_name]) + [
                    {"op": "delete", "id": "D",
                     "target": {"by": "ref", "value": "X"}}]
                body = {"ir_version": "1.0", "intent": "создал и удалил",
                        "allow_destructive": True, "ops": ops}
                out = compile_program(body, VER, snapshot=GROUND_SNAPSHOT)
                self.assertTrue(out.ok, [d.code for d in out.diagnostics])
                blocks = _post_blocks(out.csharp)
                self.assertEqual("", blocks.get("X", "").strip(),
                                 f"{op_name}: финальный блок созданного "
                                 f"элемента остался ПОСЛЕ doc.Delete")
                self.assertIn("doc.GetElement(__delid_D)", blocks.get("D", ""),
                              f"{op_name}: отсутствие не свидетельствует никто")
                cert = certify_program(
                    ground_mod.ground(_parse_and_check(body), GROUND_SNAPSHOT),
                    VER)
                self.assertTrue(cert.proven, cert.gaps)


class TheWholeFamilyBuildsWithoutAFalseRefusal(unittest.TestCase):
    """"created -> rewritten -> shifted" on EVERY row of the table."""

    def test_create_then_rewrite_then_move_compiles_and_witnesses_hold(self):
        for op_name, param_name, key, _bip, _c in _reaching_ops():
            with self.subTest(op=op_name, param=param_name):
                slot = f"{op_name}/{key}"
                base = list(_REACHING_PROGRAMS.get(slot)
                            or _REACHING_PROGRAMS[op_name])
                ops = base + [
                    {"op": "set_param", "id": "S",
                     "target": {"by": "ref", "value": "X"},
                     "param": param_name,
                     "value": {"value": 700.0, "unit": "mm"}},
                    {"op": "move_elements", "id": "M",
                     "targets": [{"by": "ref", "value": "X"}],
                     "delta_mm": [1000, 0, 0]}]
                out = compile_program(
                    {"ir_version": "1.0", "intent": "цепь правок",
                     "ops": ops}, VER, snapshot=GROUND_SNAPSHOT)
                self.assertTrue(out.ok, [d.code for d in out.diagnostics])
                grounded = ground_mod.ground(
                    _parse_and_check({"ir_version": "1.0",
                                      "intent": "цепь правок", "ops": ops}),
                    GROUND_SNAPSHOT)
                cert = certify_program(grounded, VER)
                self.assertTrue(cert.proven, cert.gaps)


if __name__ == "__main__":
    unittest.main()
