"""Отсутствие параметра и расхождение значения — РАЗНЫЕ отказы.

ЖИВОЙ ЗАМЕР 30.07 на образце Snowdon Towers Sample Plumbing. ``create_duct`` с
``diameter_mm`` на типе «Mitered Elbows / Tees» строил воздуховод, свидетель
говорил «D1: diameter mismatch», транзакция откатывалась. Откат был ЧЕСТНЫЙ, а
диагноз — нет: у прямоугольного воздуховода параметра диаметра не существует
вовсе. Модель, прочитав «mismatch», пошла бы подбирать число, тогда как чинить
надо замысел: у прямоугольного сечения ширина и высота, а не диаметр.

Подтверждено опровержением: тот же оп БЕЗ ``diameter_mm`` строит (id 1738961).

Формы сечения нет в пуле заземления, поэтому отказать на компиляции нечем —
единственное место, где она известна, это исполнение. Поэтому тест стережёт не
«оп отказывает», а то, что отказ РАЗЛИЧАЕТ два случая: параметра нет и
параметр есть, но значение другое.
"""
from __future__ import annotations

import unittest

from kukai.ir.compiler import compile_program
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT


def _duct(**extra) -> dict:
    op = {"op": "create_duct", "id": "D1",
          "p0_mm": [0, 0, 3000], "p1_mm": [8000, 0, 3000],
          "level": {"by": "element_id", "value": 42}}
    op.update(extra)
    return {"ir_version": "1.0", "ops": [op]}


def _route_duct(**extra) -> dict:
    op = {
        "op": "route_duct_system",
        "id": "RD",
        "nodes": [
            {"id": "a", "xyz_mm": [0, 0, 3000]},
            {"id": "b", "xyz_mm": [8000, 0, 3000]},
        ],
        "segments": [{"from": "a", "to": "b"}],
        "level": {"by": "element_id", "value": 42},
    }
    op.update(extra)
    return {"ir_version": "1.0", "ops": [op]}


class DiameterRefusalTests(unittest.TestCase):

    def _emit(self, program: dict) -> str:
        out = compile_program(program, snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, getattr(out, "diagnostics", None))
        return out.csharp

    def test_absent_parameter_names_the_cross_section(self) -> None:
        """Пустой параметр обязан сказать, ПОЧЕМУ он пуст."""
        code = self._emit(_duct(diameter_mm=200))
        self.assertIn("__dp == null", code)
        self.assertIn("сечение не круглое", code)
        self.assertIn("нет параметра диаметра", code)

    def test_a_wrong_value_stays_a_plain_mismatch(self) -> None:
        """Расхождение значения — прежний отказ, без рассказа про сечение."""
        code = self._emit(_duct(diameter_mm=200))
        tail = code.split("сечение не круглое")[1]
        self.assertIn("else if (Math.Abs(", tail)
        self.assertIn("diameter mismatch", tail)

    def test_the_two_cases_are_separate_branches(self) -> None:
        """Один `if` на оба случая — это и есть потерянный диагноз."""
        code = self._emit(_duct(diameter_mm=200))
        self.assertNotIn("__dp == null || Math.Abs(", code)

    def test_without_a_diameter_no_check_is_emitted_at_all(self) -> None:
        """Не спросили диаметр — нечего и сверять: отсутствие остаётся отсутствием."""
        code = self._emit(_duct())
        self.assertNotIn("RBS_CURVE_DIAMETER_PARAM", code)


class RouteDiameterRefusalTests(DiameterRefusalTests):
    """The graph-shaped duct path must preserve the same diagnosis."""

    def test_absent_parameter_names_the_cross_section(self) -> None:
        code = self._emit(_route_duct(diameter_mm=200))
        self.assertIn("__dp == null", code)
        self.assertIn("сечение не круглое", code)
        self.assertIn("нет параметра диаметра", code)

    def test_a_wrong_value_stays_a_plain_mismatch(self) -> None:
        code = self._emit(_route_duct(diameter_mm=200))
        tail = code.split("сечение не круглое")[1]
        self.assertIn("else if (Math.Abs(", tail)
        self.assertIn("segment 0 diameter (semantic)", tail)

    def test_the_two_cases_are_separate_branches(self) -> None:
        code = self._emit(_route_duct(diameter_mm=200))
        self.assertNotIn("__dp == null || Math.Abs(", code)

    def test_without_a_diameter_no_check_is_emitted_at_all(self) -> None:
        code = self._emit(_route_duct())
        self.assertNotIn("RBS_CURVE_DIAMETER_PARAM", code)


if __name__ == "__main__":
    unittest.main()
