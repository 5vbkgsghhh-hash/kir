"""An arced grid refuses honestly, rather than arriving as a straight line.

🔴 WHAT THIS FILE COST, MEASURED 2026-08-25.

A grid along an arc is an ordinary thing in residential typology. The
decompiler does NOT DISTINGUISH it:

    capture (extract)  takes `__curve.GetEndPoint(0/1)` and asks neither
                       `IsCurved` nor the curve's kind; a grep for
                       `IsCurved` across the whole tree — ZERO matches
    GridInfo (schema)  fields: id, name, p0_mm, p1_mm — no room for a kind
    _lift_grid         the ONLY curve lifter of seven that does not call
                       `_refuse_non_line_curve`; the six neighbors do
                       (beam, pipe, duct, cable_tray, conduit, room_separator)
    create_grid        exactly three parameters: p0_mm, p1_mm, name — the
                       language does not express an arc
    the emitter        hardcoded `Grid.Create(doc, Line.CreateBound(...))`

Result: the grid arrives STRAIGHT, and there is red nowhere. The op's
postcondition — "curve endpoints == p0/p1 (±5 mm)" — matches a CHORD to
the arc EXACTLY, meaning the witness cannot turn red on exactly the
defect it exists for. The witness is green, VERIFY is green, merkle
checks out.

WHAT IS DONE HERE, AND WHAT IS NOT. The arc is still NOT EXPRESSIBLE: the
language has no such op, and introducing one is separate work. What gets
closed is the SILENCE: an unrecognized curve kind becomes an honest atom
with a named reason. The gap in the language remains a gap, but stops
being a silent lie.

THE THIRD STATE IS MANDATORY. Frozen copies taken BEFORE this wave carry
no such field, and `None` there means "not measured," not "straight."
Refusing on it would mean declaring all 45 frozen copies of the corpus
invalid at once.
"""

from __future__ import annotations

import copy
import unittest

from kir.decompile.lift import lift_document_detailed
from kir.decompile.schema import L0Document
from kir.decompile.tests.fixtures_decompile import (
    make_element,
    project1_metadata,
)


def _документ(оси):
    row = copy.deepcopy(project1_metadata())
    row["change_stamp"] = "curved-grid-probe"
    row["grids"] = оси
    row["elements"] = [make_element("OST_Grids", 7001, ordinal=0)]
    row["elements"][0]["element_id"] = str(оси[0]["id"])
    row["category_status"] = []
    return L0Document.from_dict(row)


def _ось(**ещё):
    строка = {"id": "7001", "name": "A", "p0_mm": [0.0, 0.0, 0.0],
              "p1_mm": [12000.0, 0.0, 0.0]}
    строка.update(ещё)
    return строка


class ДугаНеПриезжаетПрямой(unittest.TestCase):

    @staticmethod
    def _узел(ось):
        итог = lift_document_detailed(_документ([ось]))
        return итог.nodes[0] if итог.nodes else None

    def test_род_кривой_есть_в_схеме(self):
        import dataclasses

        from kir.decompile.schema import GridInfo
        поля = {f.name for f in dataclasses.fields(GridInfo)}
        self.assertIn(
            "curve_kind", поля,
            "у оси нет места под род кривой: дуга неотличима от прямой "
            "ещё на схеме, и различить её ниже по течению нечем")

    def test_захват_спрашивает_род_кривой(self):
        from kir.decompile.extract import build_metadata_cs
        cs = build_metadata_cs()
        self.assertIn(
            "curve_kind", cs,
            "C# берёт только два конца и не спрашивает, чем они соединены")

    def test_дуга_становится_честным_атомом(self):
        узел = self._узел(_ось(curve_kind="Arc"))
        self.assertIsNotNone(узел)
        self.assertNotEqual(
            узел.get("op_name"), "create_grid",
            "дуговая ось поднялась как ПРЯМАЯ: язык её не выражает, "
            "а разбор промолчал")

    def test_причина_атома_называет_род(self):
        узел = self._узел(_ось(curve_kind="Arc"))
        весь = str(узел)
        self.assertIn("Arc", весь, f"причина не называет род кривой: {весь[:180]}")

    def test_КОНТРОЛЬ_прямая_поднимается_как_прежде(self):
        узел = self._узел(_ось(curve_kind="line"))
        self.assertEqual(узел.get("op_name"), "create_grid")

    def test_КОНТРОЛЬ_старый_слепок_без_поля_не_отказывается(self):
        """Frozen copies from before this wave carry no such field.
        `None` means "not measured," not "straight"; refusing on it
        would declare all 45 frozen copies of the corpus invalid."""
        узел = self._узел(_ось())
        self.assertEqual(
            узел.get("op_name"), "create_grid",
            "слепок без поля объявлен негодным — это отказ по НЕЗНАНИЮ")


if __name__ == "__main__":
    unittest.main()
