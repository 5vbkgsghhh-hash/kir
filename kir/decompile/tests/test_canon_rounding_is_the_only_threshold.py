"""The threshold for an optional `_mm` field is ONE, and it has a name:
the law.

🔴 WHAT THIS FILE IS BOUGHT BY, A MEASUREMENT FROM 25.08.2026.
`_survives_canon_rounding` (lift.py:867) declares itself verbatim: "the
ONLY law for whether an optional _mm param is worth carrying at all — not
an independent threshold." The law was applied at four lifters (floors
and ceilings) and NOT applied at six live ones:

    create_wall.base_offset_mm · create_wall.top_offset_mm
    create_column.base_offset_mm · create_column.top_offset_mm
    create_door.sill_mm · place_family.top_offset_mm

There, an independent literal `abs(...) >= 1.0` stood instead — exactly
what the law's docstring forbids in its very first sentence.

RUN OF 25.08, the wall lifter, WALL_BASE_OFFSET across a grid:

    offset     law      gate >=1.0   in params
       0.5     drop      drop       absent          <- agree
       0.6     KEEP      drop       ABSENT          <- 🔴
       0.9     KEEP      drop       ABSENT          <- 🔴
       1.0     keep      keep       1.0             <- agree

The band of disagreement is 0.6…0.99 mm. A wall offset by 0.6 mm lost it
silently, and the rebuilt wall stood 0.6 mm higher. The witness COULD NOT
turn red by construction: both sides of the comparison — lifting the
source model and re-lifting the rebuilt one — go through the SAME gate
and drop the field the same way. The same 0.6, on the same grid, gave two
different answers depending on whose lifter it was: for a floor it was
carried, for a wall it vanished.

WHY THE THRESHOLD EXISTS AT ALL. Comments at the six gates referred to the
byte-level stability of canonical hashes: a wall at the level (offset
exactly 0) must not sprout the field. The law preserves this —
`round(0/1) == 0`, the field is not carried. ONLY the 0.6…0.99 band
changes, and there the old answer was wrong.

THE BOUNDARY. What is checked is that the threshold is ONE, and that it
is honored on the live paths. The correctness of the law itself (that
1 mm is the right canonical grid) is not judged here: it was bought by
the v13 measurement and is recorded in that measurement's docstring.
"""

from __future__ import annotations

import ast
import copy
import unittest
from pathlib import Path

from kir.decompile.lift import (
    _survives_canon_rounding,
    lift_document_detailed,
)
from kir.decompile.schema import L0Document
from kir.decompile.tests.fixtures_decompile import (
    make_element,
    project1_metadata,
)

_LIFT = Path(__file__).resolve().parents[1] / "lift.py"

#: THE GUARD'S DENOMINATOR FOR THE SEVENTH GATE. How many places, where a
#: lifter puts a `*_mm` into params at all, it is OBLIGED to see in
#: `lift.py`.
#:
#: 🔴 WHY, IF A FAIL CONTROL ALREADY EXISTS BELOW (measured 02.09.2026).
#: The control below feeds the guard a SYNTHETIC sample and proves it can
#: say "no." It does NOT prove that the guard is looking at the live file,
#: one that actually has something to look at: `lift.py`, whose bodies
#: moved out into satellite files, will parse silently and hand back an
#: empty list — "there are no independent thresholds" indistinguishable
#: from "no `_mm` fields are put here anymore." This exact difference is
#: what kept the emitter guard green on 02.09, having seen only 35 names
#: out of 72.
#:
#: Measurement 02.09.2026: **10** `params["*_mm"]` assignments in
#: `lift.py`, and exactly as many calls to the law itself,
#: `_survives_canon_rounding`.
_MM_ПОЛЕЙ_В_ЛИФТЕРЕ_НЕ_МЕНЬШЕ = 8


def _документ(rows):
    row = copy.deepcopy(project1_metadata())
    row["change_stamp"] = "canon-threshold-probe"
    row["elements"] = copy.deepcopy(rows)
    row["category_status"] = []
    return L0Document.from_dict(row)


def _стена(*, base_offset, top_offset=None, eid=9310):
    row = make_element("OST_Walls", eid, ordinal=0)   # level "Floor 1" @ 0
    row["params"] = {
        "WALL_USER_HEIGHT_PARAM": 3615.0,
        "WALL_BASE_OFFSET": base_offset,
        "WALL_HEIGHT_TYPE": "100",
        "WALL_TOP_OFFSET": top_offset,
    }
    return row


class ЗаконОдинИСоблюдён(unittest.TestCase):

    def test_смещение_переживающее_округление_доезжает_до_params(self):
        """0.6 mm rounds to 1.0 — a quantity DISTINGUISHABLE on the
        canonical grid, and it must not be lost."""
        узел = lift_document_detailed(
            _документ([_стена(base_offset=0.6)])).nodes[0]
        self.assertEqual(узел["op_name"], "create_wall")
        self.assertIn("base_offset_mm", узел["params"],
                      "0.6 мм переживает канонское округление и обязано "
                      "доехать: закон объявлен в _survives_canon_rounding")

    def test_КОНТРОЛЬ_смещение_ноль_поля_не_заводит(self):
        """PASS control. If the fix carried the field ALWAYS, it would
        break the byte-level stability of a typical wall at the level —
        the very thing the threshold was set up for."""
        узел = lift_document_detailed(
            _документ([_стена(base_offset=0.0)])).nodes[0]
        self.assertNotIn("base_offset_mm", узел["params"])

    def test_КОНТРОЛЬ_ниже_сетки_роняется_законом_а_не_литералом(self):
        """0.4 is dropped by BOTH rules, and this must stay so: the
        control catches a fix that would simply remove the threshold."""
        self.assertFalse(_survives_canon_rounding(0.4))
        узел = lift_document_detailed(
            _документ([_стена(base_offset=0.4)])).nodes[0]
        self.assertNotIn("base_offset_mm", узел["params"])

    def test_верхнее_смещение_стены_подчиняется_тому_же_закону(self):
        """A second bearer of the same gate in the same lifter."""
        узел = lift_document_detailed(
            _документ([_стена(base_offset=0.0, top_offset=0.6)])).nodes[0]
        self.assertIn("top_offset_mm", узел["params"],
                      "верх стены роняет 0.6 мм, пока низ его несёт — "
                      "два порога в одной операции")

    def test_отрицательное_смещение_не_теряется_знаком(self):
        """`abs()` in the previous gate hid the question: the law must
        answer -0.6 and 0.6 identically."""
        self.assertTrue(_survives_canon_rounding(-0.6))
        узел = lift_document_detailed(
            _документ([_стена(base_offset=-0.6)])).nodes[0]
        self.assertIn("base_offset_mm", узел["params"])


class НезависимогоПорогаБольшеНет(unittest.TestCase):
    """A guard for a SEVENTH gate. Five years from now someone will write
    `>= 1.0` again, and there will be nothing to catch it — as there was
    nothing until 25.08.

    What is read is the SUBJECT, not the appearance: not "is there a 1.0
    in the file" but "does a comparison against a threshold literal sit
    IN A CONDITION whose body puts `*_mm` into params." A naive grep for
    `>= 1.0` would turn red on arithmetic that has nothing to do with
    thresholds."""

    @staticmethod
    def _mm_полей_всего() -> int:
        """The denominator: how many places put `params["*_mm"]` AT ALL.

        `_литеральные_пороги` counts the SICK places. This is the
        population they are drawn from. Zero sick out of zero population
        is a statement about the walker, not about the lifter.
        """
        найдено = 0
        for узел in ast.walk(ast.parse(_LIFT.read_text(encoding="utf-8"))):
            if isinstance(узел, ast.Assign):
                цели = узел.targets
            elif isinstance(узел, ast.AugAssign):
                цели = [узел.target]
            else:
                continue
            for цель in цели:
                if (isinstance(цель, ast.Subscript)
                        and isinstance(цель.slice, ast.Constant)
                        and isinstance(цель.slice.value, str)
                        and цель.slice.value.endswith("_mm")):
                    найдено += 1
        return найдено

    @staticmethod
    def _литеральные_пороги() -> list[tuple[int, str]]:
        дерево = ast.parse(_LIFT.read_text(encoding="utf-8"))
        найдено: list[tuple[int, str]] = []
        for узел in ast.walk(дерево):
            if not isinstance(узел, ast.If):
                continue
            сравнения = [
                c for c in ast.walk(узел.test) if isinstance(c, ast.Compare)
            ]
            порог = any(
                isinstance(op, (ast.GtE, ast.Gt))
                and isinstance(cmp, ast.Constant)
                and isinstance(cmp.value, (int, float))
                and float(cmp.value) == 1.0
                for c in сравнения
                for op, cmp in zip(c.ops, c.comparators)
            )
            if not порог:
                continue
            for ветвь in узел.body:
                for под in ast.walk(ветвь):
                    ключ = None
                    if isinstance(под, ast.Assign):
                        цели = под.targets
                    elif isinstance(под, ast.AugAssign):
                        цели = [под.target]
                    else:
                        continue
                    for цель in цели:
                        if (isinstance(цель, ast.Subscript)
                                and isinstance(цель.slice, ast.Constant)
                                and isinstance(цель.slice.value, str)
                                and цель.slice.value.endswith("_mm")):
                            ключ = цель.slice.value
                    if ключ:
                        найдено.append((узел.lineno, ключ))
        return найдено

    def test_ни_один_mm_параметр_не_стоит_за_литеральным_порогом(self):
        # THE DENOMINATOR FIRST: a lifter without `_mm` fields gives an
        # empty list of violators and reads as "there is no seventh
        # gate."
        население = self._mm_полей_всего()
        self.assertGreaterEqual(
            население, _MM_ПОЛЕЙ_В_ЛИФТЕРЕ_НЕ_МЕНЬШЕ,
            f"сторож видит {население} мест, кладущих `params['*_mm']`, при "
            f"поле {_MM_ПОЛЕЙ_В_ЛИФТЕРЕ_НЕ_МЕНЬШЕ} (замер 02.09.2026 — 10). "
            f"Это заявление о ХОДОКЕ: `lift.py` читается, а класть `_mm` в "
            f"нём больше некому — значит лифтеры уехали, и пустой список "
            f"нарушителей ниже НИЧЕГО не означает")
        нарушители = self._литеральные_пороги()
        self.assertEqual(
            нарушители, [],
            f"{len(нарушители)} `_mm` полей стоят за независимым порогом "
            f"вместо _survives_canon_rounding: {нарушители}. Докстрока закона "
            f"запрещает это первым предложением.")

    def test_КОНТРОЛЬ_сторож_умеет_покраснеть(self):
        """An instrument that has not proven it can say "no" is not an
        instrument. We feed it exactly the shape that lived in the tree
        before 25.08."""
        образец = ast.parse(
            "def f(element, params):\n"
            "    v = element.get('X')\n"
            "    if v is not None and abs(v) >= 1.0:\n"
            "        params['base_offset_mm'] = v\n"
        )
        сохранённый = _LIFT.read_text
        try:
            найдено = []
            дерево = образец
            for узел in ast.walk(дерево):
                if isinstance(узел, ast.If):
                    найдено.append(узел.lineno)
            self.assertTrue(найдено, "стенд негоден: условие не разобралось")
        finally:
            del сохранённый
        # The same parse as in the live test, but over a sample.
        import types
        временный = types.SimpleNamespace(
            read_text=lambda encoding=None: (
                "def f(element, params):\n"
                "    v = element.get('X')\n"
                "    if v is not None and abs(v) >= 1.0:\n"
                "        params['base_offset_mm'] = v\n"))
        глобальный = globals()
        было = глобальный["_LIFT"]
        глобальный["_LIFT"] = временный
        try:
            self.assertEqual(
                [k for _, k in self._литеральные_пороги()],
                ["base_offset_mm"],
                "сторож НЕ УВИДЕЛ форму, ради которой написан")
        finally:
            глобальный["_LIFT"] = было


if __name__ == "__main__":
    unittest.main()
