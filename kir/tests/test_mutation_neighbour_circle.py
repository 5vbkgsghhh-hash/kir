"""THE CIRCLE OF A MUTATION'S CONSEQUENCES: neighbor guards and clues in
the receipt.

🔴 MEASUREMENT OF 22.08.2026, LIVE PROD PATH `serving._witness_for_success`.
Of the registry's six mutations, `move_elements` was the ONLY ONE whose
`unwitnessed_axes` was empty:

    move_elements      unwitnessed_axes = {}                   ← FULL coverage
    change_type        {'geometry': [...], 'topology': [...]}
    delete             {'geometry': [...], 'topology': [...]}
    set_param          {'geometry', 'semantic', 'topology'}
    join_elements      {'geometry': [...], 'topology': [...]}
    set_curtain_panel  {'geometry': [...]}

An empty dictionary is the ASSERTION that "every op in the program has
declared obligations along all three axes," and it was green BY
CONSTRUCTION: all three of `move_elements`'s obligations spoke about the
TARGET ITSELF (its point, its connectors, its tilt), while the actual
effect of the move lives entirely in the NEIGHBORS — the host's door, the
connection with an adjoining wall, the author's lock, a room's area. The
neighbor's axes are not in the axis list at all, so nothing was even
counted as unchecked.

WHAT THIS FILE HOLDS. Two neighbor guards for the move, and a clue about
incidental deletion. EVERY pin has a CONTROL MUTATION next to it: the
same predicate the pin uses to judge the live emitter is applied to input
WITHOUT the check and must fail. A guard that cannot turn red is
indistinguishable from an absent one.

WHAT THIS FILE DOES NOT HOLD, AND THIS IS NAMED. It judges EMISSION, not
Revit's behavior. That inserts survive the host's move, and that the
author's lock survives it — this was never checked live, not once: the
wave had no live Revit. What is bought is compilability (36 out of 36
checks across six versions and two isolations, with a negative control),
not executability.
"""
from __future__ import annotations

import unittest

from kir.authoring import _emit_delete, _emit_move_elements
from kir.emit_model import WitnessCheck
from kir.serving import _axes_from_violations

MOVE_OP = {
    "op": "move_elements", "id": "ME1",
    "targets": [{"by": "element_id", "value": 9001},
                {"by": "element_id", "value": 9002}],
    "delta_mm": [200.0, 0.0, 0.0],
}
DELETE_OP = {"op": "delete", "id": "D1",
             "target": {"by": "element_id", "value": 9001}}


def _keys(checks) -> set[str]:
    """Obligation keys declared by the check suite."""

    return {c.obligation_key for c in checks}


def _verdict_of(checks, key: str) -> str:
    """The C# of ONE check — exactly what will go into Revit."""

    return next(c.render() for c in checks if c.obligation_key == key)


class ПереносСпрашиваетПроСоседей(unittest.TestCase):
    """Two neighbor obligations and their control mutations."""

    def setUp(self) -> None:
        self.decl, self.create, self.post, self.readback = _emit_move_elements(
            MOVE_OP, "2026", "kir:test")

    # ── guard 1: the host's inserts ────────────────────────────────────────
    def test_вставки_хозяина_объявлены_обязательством(self):
        self.assertIn("hosted_inserts", _keys(self.post))

    def test_вставки_читаются_ДО_и_ПОСЛЕ_хода(self):
        # The "before" snapshot must be taken INSIDE create: after
        # MoveElements, "how it was" can no longer be asked — there is
        # nothing left to compare against.
        self.assertIn("FindInserts(true, true, false, false)", self.create)
        self.assertIn("FindInserts(true, true, false, false)",
                      _verdict_of(self.post, "hosted_inserts"))

    def test_общий_и_врезанный_ВЫКЛЮЧЕНЫ_осознанно(self):
        # A wall inserted into a curtain wall legitimately stops being
        # inserted when it is moved away: the one branch where a red
        # would accuse correct work. That is why the third and fourth
        # arguments are false.
        self.assertNotIn("FindInserts(true, true, true, true)", self.create)

    def test_потеря_вставки_краснит_ТОПОЛОГИЮ(self):
        # The guard's message must land on ITS OWN axis — read by the
        # same reader prod uses to find it (`serving._axes_from_violations`).
        axes = _axes_from_violations(
            ["ME1: targets[0] потерял размещённый в нём элемент 4242 (topology)"])
        self.assertFalse(axes["topology_ok"])
        self.assertTrue(axes["geometry_ok"])
        self.assertTrue(axes["semantic_ok"])

    # ── guard 2: author lock ───────────────────────────────────────────
    def test_замки_размеров_объявлены_обязательством(self):
        self.assertIn("locked_dimensions", _keys(self.post))

    def test_замок_спрашивается_у_САМОЙ_цели_а_не_обходом(self):
        # The guard's cost is one call per target. Walking every dimension in
        # the document (745 in MNVNK, and `OST_Constraints` has 1 256) would
        # be a different order of magnitude.
        self.assertIn("GetDependentElements(new ElementClassFilter"
                      "(typeof(Dimension)))", self.create)
        self.assertNotIn("FilteredElementCollector", self.create)

    def test_многосегментный_размер_НЕ_судится_а_считается(self):
        # Autodesk: for a linear dimension with more than one segment,
        # `IsLocked` IS NOT SET — locks there are per-segment. Judging it by a
        # single boolean would mean signing off on something never read.
        self.assertIn("NumberOfSegments > 1", self.create)
        self.assertIn("__mtDimsMulti_ME1++", self.create)
        self.assertIn("dims_multisegment_unjudged", self.readback)

    def test_потеря_замка_краснит_ТОПОЛОГИЮ(self):
        axes = _axes_from_violations(
            ["ME1: замок размера 4242 не пережил перенос (topology)"])
        self.assertFalse(axes["topology_ok"])
        self.assertTrue(axes["semantic_ok"])

    # ── evidence: joins ────────────────────────────────────────────────
    def test_соединения_ФАКТ_а_не_сторож(self):
        """Moving a partition away from a wall — an ordinary re-plan.

        A guard on lost joins would flag correct work as red, and in strict
        mode it would roll back the whole program. So the count and the names
        travel in the receipt, and they MUST NOT be in the obligations.
        """
        self.assertNotIn("joins_lost", _keys(self.post))
        self.assertIn("joins_lost_count", self.readback)
        self.assertIn("joins_lost", self.readback)

    def test_неудача_чтения_соединений_НАЗЫВАЕТСЯ(self):
        """"Asked and got zero" and "the ask failed" are different facts.

        `GetJoinedElements` carries three documented pitfalls. An empty
        catch would give an empty "before" list, and "nothing was lost" would
        become true by construction — the same green-by-construction that
        this whole wave was opened against.
        """
        self.assertIn("__mtJoinRead_ME1 = false;", self.create)
        self.assertIn('__rb["joins_read"] = __mtJoinRead_ME1;', self.readback)

    # ── scope contract ──────────────────────────────────────────────
    def test_всё_читаемое_после_хода_объявлено_в_decl(self):
        for var in ("__mtInsBefore_ME1", "__mtJoinBefore_ME1",
                    "__mtLockedDims_ME1", "__mtJoinRead_ME1",
                    "__mtDimsSeen_ME1", "__mtDimsMulti_ME1"):
            with self.subTest(var=var):
                self.assertIn(var, self.decl)

    # ── CONTROL MUTATION ──────────────────────────────────────────────
    def test_КОНТРОЛЬ_пин_падает_на_наборе_БЕЗ_сторожа(self):
        """The same predicate, applied to a post without the check, must
        fail.

        Without this test, the pins above are indistinguishable from
        `assertTrue(True)`: they stay green even when there is no guard, if
        the predicate is looking the wrong way.
        """
        for key in ("hosted_inserts", "locked_dimensions"):
            with self.subTest(dropped=key):
                кастрированный = [c for c in self.post
                                  if c.obligation_key != key]
                self.assertNotIn(key, _keys(кастрированный))
                with self.assertRaises(AssertionError):
                    self.assertIn(key, _keys(кастрированный))

    def test_КОНТРОЛЬ_пометка_оси_у_сообщения_умеет_отсутствовать(self):
        """The axis reader must distinguish the flagged from the unflagged.

        If `_axes_from_violations` flagged the topology axis red on anything
        at all, the axis pins above would mean nothing.
        """
        axes = _axes_from_violations(["ME1: замок размера 4242 не пережил перенос"])
        self.assertTrue(axes["topology_ok"], "без пометки топология не краснеет")
        self.assertFalse(axes["semantic_ok"], "непомеченное — семантика")

    def test_КОНТРОЛЬ_проверка_без_вердикта_НЕКОНСТРУИРУЕМА(self):
        """A guard without `__post.Add` does not compile — this is by construction."""
        with self.assertRaises(Exception):
            WitnessCheck(obligation_key="hosted_inserts", reader_cs="",
                         verdict_cs="    // ничего не проверяю\n",
                         message="пусто", style="plain")


class УдалениеНазываетПопутноУдалённое(unittest.TestCase):
    """Revit itself returns the circle of deletion consequences, and it was being discarded."""

    def setUp(self) -> None:
        self.decl, self.create, self.post, self.readback = _emit_delete(
            DELETE_OP, "2026", "kir:test")

    def test_возврат_doc_Delete_ЗАБИРАЕТСЯ(self):
        # Autodesk (remarks, 6/6 версий): "This method will delete the element
        # AND ANY ELEMENTS THAT ARE TOTALLY DEPENDENT UPON THAT ELEMENT."
        self.assertIn("ICollection<ElementId> __delret_D1 = doc.Delete(__delid_D1);",
                      self.create)

    def test_лишних_вызовов_ревита_НОЛЬ(self):
        # The evidence comes from the return value, not a separate query:
        # there is not a single new call to the document in create.
        self.assertEqual(self.create.count("doc.Delete("), 1)
        self.assertNotIn("GetDependentElements", self.create)

    def test_сама_цель_из_числа_ВЫЧТЕНА(self):
        # The question asked is "what ELSE was lost"; a count that includes
        # what was ordered would answer a different question.
        self.assertIn("if (__delx_D1.ToString() != __delid_D1.ToString())",
                      self.create)

    def test_число_полное_имена_режутся(self):
        self.assertIn('__rb["collateral_count"] = __delalso_D1.Count;',
                      self.readback)
        self.assertIn("Math.Min(10, __delalso_D1.Count)", self.readback)
        self.assertIn('__rb["collateral_capped"]', self.readback)

    def test_попутное_удаление_НЕ_обязательство(self):
        """A "zero incidental deletions" guard would flag deleting a wall
        with a door as red.

        That is the most ordinary case, and in strict mode it would roll back
        the whole program. The language carries no boundary for incidental
        deletion at all: the plan knows only `allow_destructive` — a boolean
        gate on the TARGET.
        """
        self.assertEqual(_keys(self.post), {"gone"})

    def test_КОНТРОЛЬ_пин_на_возврат_падает_на_прежней_эмиссии(self):
        """The previous body — `try { doc.Delete(id); }` — must fail the pin."""
        прежнее = "try { doc.Delete(__delid_D1); }"
        self.assertNotIn(
            "ICollection<ElementId> __delret_D1 = doc.Delete(__delid_D1);",
            прежнее)
        with self.assertRaises(AssertionError):
            self.assertIn(
                "ICollection<ElementId> __delret_D1 = doc.Delete(__delid_D1);",
                прежнее)


class ЧтоОстаётсяНЕСПРОШЕННЫМ(unittest.TestCase):
    """The wave's named absences are pins on the BOUNDARY, not on capability."""

    def test_помещения_переносом_НЕ_перечитываются(self):
        """Revit has no query for "which rooms border this wall."

        Cost per the MNVNK census (`L0.jsonl`, `document.census`): OST_Rooms
        1 102 — that is how many elements would have to be walked ON EVERY
        op, whereas everything taken here costs one call per target. The pin
        holds the BOUNDARY: if rooms ever enter the witness, this test must
        fail and force the named absence to be rewritten.
        """
        _d, create, _p, readback = _emit_move_elements(
            MOVE_OP, "2026", "kir:test")
        for marker in ("OST_Rooms", "GetBoundarySegments", "Room "):
            with self.subTest(marker=marker):
                self.assertNotIn(marker, create)
                self.assertNotIn(marker, readback)


if __name__ == "__main__":                                   # pragma: no cover
    unittest.main()
