"""Подрезка участка под врезку отвода — законная, а не нарушение.

ЖИВОЙ ЗАМЕР 30.07 на образце Snowdon Towers Sample Plumbing. Системные опы
обещали «each LocationCurve == its node pair ±5mm (geometry)» и на связной
системе НИКОГДА не могли это выполнить: Revit ставит в узле отвод и подрезает
соседние участки под его грань. Различающий опыт снял вопрос:

    1 участок  (стыку взяться неоткуда) -> ok, one_system=true
    2 участка  -> нарушены ОБА конца стыка
    3 участка  -> нарушены все три

Топология (BFS по графу коннекторов) проходила ВО ВСЕХ случаях — система
собиралась связной, ломалась только геометрическая сверка. То есть постусловие
было неверно по построению, и это ровно та причина, по которой три сетевых
операции за всю историю не построили НИЧЕГО.

Новый инвариант различает два рода концов:

* СВОБОДНЫЙ конец (узел степени 1) — совпадает с узлом ±5 мм, как раньше;
* СТЫКОВАННЫЙ конец — вправе отступить ВНУТРЬ участка, но обязан остаться на
  той же прямой и не уйти дальше середины. Подрезка разрешена; уход с оси,
  перелёт наружу и «съело больше половины» — нет.

Здесь проверяется ТА ЧАСТЬ, что живёт в питоне (границы допуска), и то, что
эмиссия их различает. Сама арифметика проекции живёт в C# в единственном
экземпляре и покрыта голденами — второй копии предиката заводить нельзя,
иначе разойдутся, как уже расходились перепись и её копия в инструменте.
"""
from __future__ import annotations

import unittest

from kukai.ir.authoring import _segment_trim_bounds_mm
from kukai.ir import spec

# Допуск конца живёт В РЕЕСТРЕ (03.08): пол подрезки — то же самое число,
# и тест берёт его оттуда же, а не набирает вторым экземпляром.
TOL_MM = spec.OPS["create_pipe_system"].tolerances["endpoint_mm"]


class TrimBoundsTests(unittest.TestCase):

    def test_a_free_end_keeps_the_exact_tolerance(self) -> None:
        """Конец, который ни с чем не стыкуется, подрезать нечему."""
        trim_a, trim_b = _segment_trim_bounds_mm(
            (0.0, 0.0, 0.0), (6000.0, 0.0, 0.0), degree_a=1, degree_b=1, tol_mm=TOL_MM)
        self.assertEqual((trim_a, trim_b), (5.0, 5.0))

    def test_a_junction_end_may_be_trimmed_up_to_half(self) -> None:
        """Отвод съедает начало участка — но не больше половины."""
        trim_a, trim_b = _segment_trim_bounds_mm(
            (0.0, 0.0, 0.0), (6000.0, 0.0, 0.0), degree_a=2, degree_b=1, tol_mm=TOL_MM)
        self.assertEqual(trim_a, 3000.0)
        self.assertEqual(trim_b, 5.0)

    def test_both_ends_may_be_junctions(self) -> None:
        """Средний участок ветки подрезается с обеих сторон."""
        trim_a, trim_b = _segment_trim_bounds_mm(
            (0.0, 0.0, 0.0), (0.0, 4000.0, 0.0), degree_a=3, degree_b=2, tol_mm=TOL_MM)
        self.assertEqual((trim_a, trim_b), (2000.0, 2000.0))

    def test_a_short_segment_never_gets_a_looser_bound_than_the_tolerance(self) -> None:
        """На коротком участке половина меньше допуска — берётся БОЛЬШЕЕ.

        Иначе стыкованный конец получил бы допуск строже свободного, и связная
        система из коротких участков стала бы непроходимой по другой причине.
        """
        trim_a, _ = _segment_trim_bounds_mm(
            (0.0, 0.0, 0.0), (6.0, 0.0, 0.0), degree_a=2, degree_b=1, tol_mm=TOL_MM)
        self.assertEqual(trim_a, 5.0)

    def test_a_degenerate_segment_is_refused_not_tolerated(self) -> None:
        """Нулевая длина — не «всё сошлось», а отсутствие участка."""
        with self.assertRaises(ValueError):
            _segment_trim_bounds_mm(
                (10.0, 10.0, 10.0), (10.0, 10.0, 10.0), degree_a=1, degree_b=1, tol_mm=TOL_MM)


class EmissionDistinguishesEndsTests(unittest.TestCase):
    """Эмиссия обязана РАЗЛИЧАТЬ роды концов, а не смягчать всё подряд."""

    def _emit(self, program: dict) -> str:
        from kukai.ir.compiler import compile_program
        from kukai.ir.tests.fixtures import GROUND_SNAPSHOT
        out = compile_program(program, snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, getattr(out, "diagnostics", None))
        return out.csharp

    def _program(self, nodes: list[dict], segments: list[dict]) -> dict:
        return {"ir_version": "1.0", "ops": [{
            "op": "create_pipe_system", "id": "S1",
            "nodes": nodes, "segments": segments,
            "level": {"by": "element_id", "value": 42}}]}

    def test_a_single_segment_stays_strict_on_both_ends(self) -> None:
        code = self._emit(self._program(
            [{"id": "a", "xyz_mm": [0, 0, 3000]},
             {"id": "b", "xyz_mm": [6000, 0, 3000]}],
            [{"from": "a", "to": "b"}]))
        # Оба конца свободны -> в сравнении стоят только допуски 5.
        self.assertIn("segment 0 endpoints (geometry)", code)
        block = code.split("segment 0 endpoints")[0][-700:]
        self.assertIn("__t0 > (5.0)", block)
        self.assertIn("__t1 > (5.0)", block)

    def test_a_junction_relaxes_only_the_shared_end(self) -> None:
        code = self._emit(self._program(
            [{"id": "a", "xyz_mm": [0, 0, 3000]},
             {"id": "b", "xyz_mm": [6000, 0, 3000]},
             {"id": "c", "xyz_mm": [6000, 6000, 3000]}],
            [{"from": "a", "to": "b"}, {"from": "b", "to": "c"}]))
        # Узел b общий для двух участков: у участка 0 послаблён КОНЕЦ (t1),
        # у участка 1 — НАЧАЛО (t0), а свободные концы остались строгими.
        first = code.split("segment 0 endpoints")[0][-700:]
        second = code.split("segment 1 endpoints")[0][-700:]
        self.assertIn("__t0 > (5.0)", first)
        self.assertIn("__t1 > (3000.0)", first)
        self.assertIn("__t0 > (3000.0)", second)
        self.assertIn("__t1 > (5.0)", second)


if __name__ == "__main__":
    unittest.main()
