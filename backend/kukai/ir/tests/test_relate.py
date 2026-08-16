"""RELATE — адресация от осей: замки на грамматику, три дефекта и разрешение.

Запускать точечно (полный набор — 5 ГБ RSS):

    venv/bin/python3.12 -m pytest kukai/ir/tests/test_relate.py -q

СТРУКТУРА. Первые три класса — ОПРОВЕРГАЮЩИЕ тесты на три латентных дефекта
шиппед-механизма ``contour.resolve_anchor`` (спека §1.3). Они написаны ДО
починки и на непочиненном дереве красные — это их работа. Дальше грамматика,
разрешение и места, где адрес разрешён.

ГРАНИЦА ЭТОГО ПРИБОРА, СЛОВАМИ. Здесь доказывается ВСЁ, что доказуемо чистой
функцией: форма адреса (от текста) и разрешение (от снапшота-фикстуры).
НЕ доказывается ничего о живой модели: что ось не уехала между снапшотом и
записью, что элемент встал в точку — это свидетели, живой Revit и отдельная
волна ``grid_anchor``. Тест, который бы это «проверил» на фикстуре, был бы
самосертификацией.
"""
from __future__ import annotations

import math
import os
import re
import tempfile
import unittest

os.environ.setdefault(
    "KIR_REJECTIONS_PATH",
    os.path.join(tempfile.gettempdir(), "kir_relate_queue.jsonl"))

from kukai.ir import contour, macros, relate               # noqa: E402
from kukai.ir.compiler import compile_program              # noqa: E402
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT        # noqa: E402


# ── фикстуры осей ───────────────────────────────────────────────────────────

#: Повёрнутое здание. Замер 03.08: у `sklnk_eom` ВСЕ 57 осей идут под 156.1° и
#: 66.1° — ни одна не совпадает с мировой осью. Здесь тот же угол.
_ROT_DEG = 66.1
_UX, _UY = math.cos(math.radians(_ROT_DEG)), math.sin(math.radians(_ROT_DEG))
_NX, _NY = -_UY, _UX          # левая нормаль к направлению осей 25/26

_L = 30_000.0


def _rotated_pool() -> list:
    """Три оси повёрнутого здания: «25» и «26» параллельны (3000 мм врозь),
    «А» перпендикулярна обеим и проходит через начало координат."""
    return [
        {"id": 101, "name": "25",
         "p0_mm": [0.0, 0.0], "p1_mm": [_UX * _L, _UY * _L]},
        {"id": 102, "name": "26",
         "p0_mm": [_NX * 3000.0, _NY * 3000.0],
         "p1_mm": [_UX * _L + _NX * 3000.0, _UY * _L + _NY * 3000.0]},
        {"id": 103, "name": "А",
         "p0_mm": [0.0, 0.0], "p1_mm": [_NX * _L, _NY * _L]},
    ]


def _perp_from_grid25(point) -> float:
    """Знаковое расстояние от точки до прямой «25» — считается ЗДЕСЬ, без
    единой функции из `relate`: сверять резолвер его же арифметикой значило бы
    сверять его с самим собой."""
    return -_UY * point[0] + _UX * point[1]


def _orthogonal_pool() -> list:
    """Сетка ШИППЕД-ФИКСТУРЫ, а не своя: «1»/«2» вертикальные (x=0/4000),
    «А»/«Б» горизонтальные (y=0/4500).

    Второй набор осей рядом с `fixtures.GROUND_SNAPSHOT` разошёлся бы с ним
    на первой же правке — ровно то, о чём предупреждает докстринг фикстур.
    """
    return [dict(row) for row in GROUND_SNAPSHOT["grids"]]


def _resolve(address, pool, *, dims=2, field="xy", truncated=False):
    diags: list = []
    receipt: list = []
    point = relate.resolve_address(address, pool, "op1", field, diags,
                                   dims=dims, truncated=truncated,
                                   receipt=receipt)
    return point, diags, receipt


def _codes(diags) -> list:
    return [d.code for d in diags]


# ── Д1: МИРОВАЯ РАМКА ОТСТУПА ───────────────────────────────────────────────

class D1WorldFrameOffset(unittest.TestCase):
    """Спека §1.3, Д1. Шиппед-форма смещает точку в МИРОВЫХ координатах."""

    def test_shipped_world_offset_is_not_perpendicular(self):
        """ЧИСЛО, которым дефект доказан: на повёрнутой сетке `offset_mm:
        [200, 0]` даёт 182.9 мм от оси и НЕ С ТОЙ СТОРОНЫ."""
        diags: list = []
        point = contour.resolve_anchor(
            {"at_grid": ["25", "А"], "offset_mm": [200, 0]},
            _rotated_pool(), "op1", "origin", diags)
        self.assertEqual(diags, [])
        self.assertIsNotNone(point)
        got = _perp_from_grid25(point)
        self.assertAlmostEqual(got, -182.9, places=1)
        # «в сторону 26» — это ПЛЮС по нормали; мировой отступ ушёл в минус.
        self.assertLess(got, 0.0)

    def test_offset_from_a_rotated_grid_is_expressible(self):
        """ПОЧИНКА: отступ называется у ЛИНИИ и мерится по перпендикуляру
        к самой оси, направление читается из модели."""
        point, diags, _r = _resolve(
            {"at_grid": [{"grid": "25", "offset_mm": 200, "toward": "26"},
                         "А"]},
            _rotated_pool())
        self.assertEqual(diags, [])
        self.assertAlmostEqual(_perp_from_grid25(point), 200.0, places=6)

    def test_offset_direction_follows_the_named_neighbour(self):
        """Сторона названа СОСЕДКОЙ, а не знаком: разверни соседку — точка
        уедет на другую сторону, и никакого знакового соглашения для этого
        не понадобится."""
        pool = _rotated_pool()
        # «27» — зеркальная соседка: та же прямая, но с другой стороны.
        pool.append({"id": 104, "name": "27",
                     "p0_mm": [-_NX * 3000.0, -_NY * 3000.0],
                     "p1_mm": [_UX * _L - _NX * 3000.0,
                               _UY * _L - _NY * 3000.0]})
        toward26, d1, _ = _resolve(
            {"at_grid": [{"grid": "25", "offset_mm": 200, "toward": "26"},
                         "А"]}, pool)
        toward27, d2, _ = _resolve(
            {"at_grid": [{"grid": "25", "offset_mm": 200, "toward": "27"},
                         "А"]}, pool)
        self.assertEqual((d1, d2), ([], []))
        self.assertAlmostEqual(_perp_from_grid25(toward26), 200.0, places=6)
        self.assertAlmostEqual(_perp_from_grid25(toward27), -200.0, places=6)

    def test_world_offset_is_closed_in_the_new_slots(self):
        """Д1 не наследуется: в новых слотах мировая пара [dx,dy] ОТКАЗЫВАЕТ,
        и отказ называет замену."""
        point, diags, _r = _resolve(
            {"at_grid": ["А", "1"], "offset_mm": [200, 0]}, _orthogonal_pool())
        self.assertIsNone(point)
        self.assertEqual(_codes(diags), ["KIR-T001"])
        self.assertIn("toward", diags[0].message_ru)

    def test_world_offset_still_works_for_region(self):
        """…и при этом голдены `region` не двигаются: легаси-дверь открыта
        ИМЕНОВАННО и ровно одному потребителю."""
        diags: list = []
        point = contour.resolve_anchor(
            {"at_grid": ["А", "1"], "offset_mm": [200, 300]},
            _orthogonal_pool(), "op1", "origin", diags)
        self.assertEqual(diags, [])
        self.assertEqual(point, [200.0, 300.0])


# ── Д2: ТИХИЙ ВЫБОР ПРИ СОВПАДЕНИИ ИМЁН ─────────────────────────────────────

class D2DuplicateNames(unittest.TestCase):
    """Спека §1.3, Д2. `{name: g for g in pool}` оставляет ПОСЛЕДНЮЮ строку."""

    @staticmethod
    def _pool_with_two_b():
        return [
            {"id": 11, "name": "Б", "p0_mm": [1000, -5000], "p1_mm": [1000, 25000]},
            {"id": 12, "name": "Б", "p0_mm": [5000, -5000], "p1_mm": [5000, 25000]},
            {"id": 13, "name": "1", "p0_mm": [-5000, 0], "p1_mm": [30000, 0]},
        ]

    def test_shipped_code_silently_took_the_last_row(self):
        """Доказательство ДО: два «Б», ноль диагностик, точка от ПОСЛЕДНЕЙ."""
        by_name = {str(g.get("name", "")).strip(): g
                   for g in self._pool_with_two_b()}          # строка 86 as was
        self.assertEqual(by_name["Б"]["id"], 12)

    def test_duplicate_names_now_refuse_with_both_ids(self):
        point, diags, _r = _resolve({"at_grid": ["Б", "1"]},
                                    self._pool_with_two_b())
        self.assertIsNone(point)
        self.assertEqual(_codes(diags), ["KIR-G109"])
        self.assertEqual([c["id"] for c in diags[0].candidates], [11, 12])
        # ремонт назван и он ВНЕ грамматики — element_id язык не принимает
        self.assertIn("литералом", diags[0].message_ru)

    def test_contour_inherits_the_fix(self):
        """Тот же пул через шиппед-вход CONTOUR — тот же отказ, не тихий выбор."""
        diags: list = []
        point = contour.resolve_anchor({"at_grid": ["Б", "1"]},
                                       self._pool_with_two_b(),
                                       "op1", "origin", diags)
        self.assertIsNone(point)
        self.assertEqual(_codes(diags), ["KIR-G109"])


# ── Д3: ОБУСЛОВЛЕННОСТЬ ─────────────────────────────────────────────────────

class D3Conditioning(unittest.TestCase):
    """Спека §1.3, Д3. `|den| < 1e-9` — это угол порядка 1e-15 рад."""

    @staticmethod
    def _near_parallel(angle_deg: float):
        rad = math.radians(angle_deg)
        return [
            {"id": 21, "name": "A", "p0_mm": [0, 0], "p1_mm": [30000, 0]},
            {"id": 22, "name": "B", "p0_mm": [0, 500],
             "p1_mm": [30000 * math.cos(rad), 500 + 30000 * math.sin(rad)]},
        ]

    @staticmethod
    def _shipped_line_intersection(p0, p1, q0, q1):
        """Дословно `contour._line_intersection` каким он был до 04.08 —
        единственный порог `|den| < 1e-9`. Держится ЗДЕСЬ, потому что
        доказательство дефекта обязано переживать его починку."""
        d1 = (p1[0] - p0[0], p1[1] - p0[1])
        d2 = (q1[0] - q0[0], q1[1] - q0[1])
        den = d1[0] * d2[1] - d1[1] * d2[0]
        if abs(den) < 1e-9:
            return None
        t = ((q0[0] - p0[0]) * d2[1] - (q0[1] - p0[1]) * d2[0]) / den
        return (p0[0] + t * d1[0], p0[1] + t * d1[1])

    def test_shipped_line_intersection_accepted_a_tenth_of_a_degree(self):
        """Доказательство ДО: при 0.1° старая функция возвращает точку,
        и точка эта в 286 метрах от начала координат — то есть шум."""
        pt = self._shipped_line_intersection(
            [0, 0], [30000, 0], [0, 500],
            [30000 * math.cos(math.radians(0.1)),
             500 + 30000 * math.sin(math.radians(0.1))])
        self.assertIsNotNone(pt)
        self.assertGreater(abs(pt[0]), 250_000)

    def test_contour_inherits_the_conditioning_fix(self):
        diags: list = []
        point = contour.resolve_anchor({"at_grid": ["A", "B"]},
                                       self._near_parallel(0.1),
                                       "op1", "origin", diags)
        self.assertIsNone(point)
        self.assertEqual(_codes(diags), ["KIR-G110"])

    def test_near_parallel_pair_now_refuses(self):
        point, diags, _r = _resolve({"at_grid": ["A", "B"]},
                                    self._near_parallel(0.1))
        self.assertIsNone(point)
        self.assertEqual(_codes(diags), ["KIR-G110"])
        self.assertIn("0.100", diags[0].message_ru)

    def test_threshold_is_exactly_one_degree(self):
        """Порог ВЫВЕДЕН (§4.4), поэтому проверяется с обеих сторон."""
        below, d_below, _ = _resolve({"at_grid": ["A", "B"]},
                                     self._near_parallel(0.99))
        above, d_above, _ = _resolve({"at_grid": ["A", "B"]},
                                     self._near_parallel(1.01))
        self.assertIsNone(below)
        self.assertEqual(_codes(d_below), ["KIR-G110"])
        self.assertIsNotNone(above)
        self.assertEqual(d_above, [])

    def test_parallel_pair_refuses_with_the_same_code(self):
        point, diags, _r = _resolve({"at_grid": ["A", "B"]},
                                    self._near_parallel(0.0))
        self.assertIsNone(point)
        self.assertEqual(_codes(diags), ["KIR-G110"])


# ── ГРАММАТИКА: закрытая, три узла ──────────────────────────────────────────

class Grammar(unittest.TestCase):

    def test_four_reference_forms_accepted(self):
        pool = _orthogonal_pool()
        for line in ("А", {"grid": "А"},
                     {"grid": "А", "offset_mm": 250, "toward": "Б"},
                     {"grid": " А "}):
            with self.subTest(line=line):
                point, diags, _r = _resolve({"at_grid": [line, "1"]}, pool)
                self.assertEqual(diags, [])
                self.assertIsNotNone(point)

    def test_short_form_is_byte_identical_to_contour(self):
        """Ключ намеренно тот же: одна грамматика на два места."""
        pool = _orthogonal_pool()
        new, diags, _r = _resolve({"at_grid": ["А", "1"]}, pool)
        old_diags: list = []
        old = contour.resolve_anchor({"at_grid": ["А", "1"]}, pool,
                                     "op1", "origin", old_diags)
        self.assertEqual((diags, old_diags), ([], []))
        self.assertEqual(new, old)

    def test_composition_is_unexpressible(self):
        """Ни «середина между», ни «параллельно», ни «плюс» — реестр форм
        ЗАКРЫТ, и отказ печатает сам реестр."""
        pool = _orthogonal_pool()
        for line in ({"between": ["А", "Б"]},
                     {"grid": "А", "plus": "Б"},
                     {"parallel_to": "А", "offset_mm": 100},
                     {"grid": "А", "offset_mm": 100, "toward": "Б", "extra": 1}):
            with self.subTest(line=line):
                point, diags, _r = _resolve({"at_grid": [line, "1"]}, pool)
                self.assertIsNone(point)
                self.assertEqual(_codes(diags), ["KIR-T001"])

    def test_offset_and_toward_are_a_pair(self):
        pool = _orthogonal_pool()
        _p, d1, _ = _resolve({"at_grid": [{"grid": "А", "offset_mm": 100}, "1"]},
                             pool)
        _p, d2, _ = _resolve({"at_grid": [{"grid": "А", "toward": "Б"}, "1"]},
                             pool)
        self.assertEqual(_codes(d1), ["KIR-T001"])
        self.assertIn("toward", d1[0].message_ru)
        self.assertEqual(_codes(d2), ["KIR-T001"])
        self.assertIn("offset_mm", d2[0].message_ru)

    def test_zero_offset_is_refused_as_a_second_spelling(self):
        point, diags, _r = _resolve(
            {"at_grid": [{"grid": "А", "offset_mm": 0, "toward": "Б"}, "1"]},
            _orthogonal_pool())
        self.assertIsNone(point)
        self.assertEqual(_codes(diags), ["KIR-T002"])

    def test_offset_bound_is_the_move_elements_bound(self):
        point, diags, _r = _resolve(
            {"at_grid": [{"grid": "А", "offset_mm": 100_001, "toward": "Б"},
                         "1"]}, _orthogonal_pool())
        self.assertIsNone(point)
        self.assertEqual(_codes(diags), ["KIR-T002"])

    def test_at_grid_needs_exactly_two_lines(self):
        for value in (["А"], ["А", "1", "2"], [], "А"):
            with self.subTest(value=value):
                point, diags, _r = _resolve({"at_grid": value},
                                            _orthogonal_pool())
                self.assertIsNone(point)
                self.assertEqual(_codes(diags), ["KIR-T001"])

    def test_name_bounds(self):
        for name in ("", "   ", "x" * 65, 3, None):
            with self.subTest(name=name):
                point, diags, _r = _resolve({"at_grid": [name, "1"]},
                                            _orthogonal_pool())
                self.assertIsNone(point)
                self.assertEqual(_codes(diags), ["KIR-T001"])

    def test_toward_cannot_be_its_own_grid(self):
        point, diags, _r = _resolve(
            {"at_grid": [{"grid": "А", "offset_mm": 100, "toward": " А "},
                         "1"]}, _orthogonal_pool())
        self.assertIsNone(point)
        self.assertEqual(_codes(diags), ["KIR-T001"])

    def test_z_is_required_in_xyz_and_forbidden_in_xy(self):
        pool = _orthogonal_pool()
        _p, d_missing, _ = _resolve({"at_grid": ["А", "1"]}, pool, dims=3)
        _p, d_extra, _ = _resolve({"at_grid": ["А", "1"], "z_mm": 3000}, pool,
                                  dims=2)
        self.assertEqual(_codes(d_missing), ["KIR-T001"])
        self.assertIn("z_mm", d_missing[0].message_ru)
        self.assertEqual(_codes(d_extra), ["KIR-T001"])
        point, diags, _r = _resolve({"at_grid": ["А", "1"], "z_mm": 3000},
                                    pool, dims=3)
        self.assertEqual(diags, [])
        self.assertEqual(point, [0.0, 0.0, 3000.0])


# ── РАЗРЕШЕНИЕ ОТ СНАПШОТА ──────────────────────────────────────────────────

class Resolution(unittest.TestCase):

    def test_missing_name_names_the_next_move(self):
        point, diags, _r = _resolve({"at_grid": ["В", "1"]}, _orthogonal_pool())
        self.assertIsNone(point)
        self.assertEqual(_codes(diags), ["KIR-G108"])
        self.assertIn("query_list", diags[0].message_ru)
        self.assertTrue(diags[0].candidates)

    def test_truncated_pool_says_so(self):
        _p, diags, _ = _resolve({"at_grid": ["В", "1"]}, _orthogonal_pool(),
                                truncated=True)
        self.assertEqual(_codes(diags), ["KIR-G108"])
        self.assertIn("обрезан", diags[0].message_ru)

    def test_empty_pool_is_a_different_repair(self):
        point, diags, _r = _resolve({"at_grid": ["А", "1"]}, [])
        self.assertIsNone(point)
        self.assertEqual(_codes(diags), ["KIR-G104"])
        self.assertIn("create_grid", diags[0].message_ru)

    def test_grid_without_straight_geometry(self):
        pool = _orthogonal_pool() + [{"id": 9, "name": "R", "is_curved": True}]
        point, diags, _r = _resolve({"at_grid": ["R", "1"]}, pool)
        self.assertIsNone(point)
        self.assertEqual(_codes(diags), ["KIR-G111"])
        self.assertIn("дуговая", diags[0].message_ru)

    def test_toward_must_be_parallel(self):
        point, diags, _r = _resolve(
            {"at_grid": [{"grid": "А", "offset_mm": 200, "toward": "1"}, "1"]},
            _orthogonal_pool())
        self.assertIsNone(point)
        self.assertEqual(_codes(diags), ["KIR-G112"])
        self.assertEqual(diags[0].candidates, ["Б"])

    def test_toward_perpendicular_but_drawn_entirely_on_one_side(self):
        """САМЫЙ ЗЛОЙ случай, и его нашёл возмущающий оракул: пересекающая
        ось, НАРИСОВАННАЯ целиком по одну сторону. Проверка «концы по разные
        стороны» её пропускает, и ловит только порог параллельности — без
        него «в сторону» посчиталось бы от прямой, которая на самом деле
        пересекает свою же ось за краем чертежа."""
        pool = _orthogonal_pool() + [
            {"id": 5, "name": "К", "p0_mm": [1000, 2000], "p1_mm": [1000, 9000]}]
        point, diags, _r = _resolve(
            {"at_grid": [{"grid": "А", "offset_mm": 200, "toward": "К"}, "1"]},
            pool)
        self.assertIsNone(point)
        self.assertEqual(_codes(diags), ["KIR-G112"])
        self.assertIn("не параллельна", diags[0].message_ru)

    def test_toward_with_no_parallel_neighbour_at_all(self):
        pool = [
            {"id": 1, "name": "А", "p0_mm": [0, -5000], "p1_mm": [0, 25000]},
            {"id": 3, "name": "1", "p0_mm": [-5000, 0], "p1_mm": [30000, 0]},
        ]
        point, diags, _r = _resolve(
            {"at_grid": [{"grid": "А", "offset_mm": 200, "toward": "1"}, "1"]},
            pool)
        self.assertIsNone(point)
        self.assertEqual(_codes(diags), ["KIR-G112"])
        self.assertEqual(diags[0].candidates, [])
        self.assertIn("нет ни одной параллельной соседки",
                      diags[0].message_ru)
        self.assertIn("литералом [x, y]", diags[0].message_ru)

    def test_all_refusals_arrive_in_one_round(self):
        """SPEC 12.7: три неверных имени -> три отказа за один ход."""
        program = {
            "ir_version": "1.0", "ops": [
                {"op": "create_column", "id": f"c{i}",
                 "level": {"by": "name", "value": "Этаж 1"},
                 "symbol": {"by": "name", "value": "К 300x300"},
                 "xy": {"at_grid": [name, "1"]}}
                for i, name in enumerate(("Ж", "З", "И"))]}
        out = compile_program(program, "2026", snapshot=_SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertEqual([d.code for d in out.diagnostics],
                         ["KIR-G108"] * 3)

    def test_receipt_names_every_line(self):
        _p, diags, receipt = _resolve(
            {"at_grid": [{"grid": "А", "offset_mm": 250, "toward": "Б"}, "1"]},
            _orthogonal_pool())
        self.assertEqual(diags, [])
        self.assertEqual(len(receipt), 1)
        text = relate.describe_receipt_ru(receipt)[0]
        self.assertIn("«А» (id 902)", text)
        self.assertIn("250 мм в сторону «Б»", text)
        self.assertIn("[0, 250]", text)


# ── ГДЕ АДРЕС РАЗРЕШЁН ──────────────────────────────────────────────────────

_SNAPSHOT = GROUND_SNAPSHOT


class WhereAddressesAreAllowed(unittest.TestCase):

    def _compile(self, ops, snapshot=None):
        return compile_program({"ir_version": "1.0", "ops": ops}, "2026",
                               snapshot=_SNAPSHOT if snapshot is None
                               else snapshot)

    def test_wall_from_grid_to_grid(self):
        """«стена от оси 1 до оси 2 по оси А» — ДВА адреса, новой грамматики
        для этой формы нет (спека §2.4/Р2)."""
        out = self._compile([{
            "op": "create_wall", "id": "w1",
            "level": {"by": "name", "value": "Этаж 1"},
            "type": {"by": "name", "value": "ЖБ 200"},
            "height_mm": 3000,
            "p0_mm": {"at_grid": ["А", "1"]},
            "p1_mm": {"at_grid": ["А", "2"]}}])
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        self.assertIn("P(0, 0, 0)", out.csharp)
        self.assertIn("P(4000, 0, 0)", out.csharp)

    def test_column_on_an_intersection(self):
        out = self._compile([{
            "op": "create_column", "id": "c1",
            "level": {"by": "name", "value": "Этаж 1"},
            "symbol": {"by": "name", "value": "К 300x300"},
            "xy": {"at_grid": ["Б", "2"]}}])
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        self.assertIn("P(4000, 4500, 0)", out.csharp)

    def test_column_with_an_offset_from_a_grid(self):
        """Главная форма (Р3): НА ОСИ с отступом, сторона названа соседкой."""
        out = self._compile([{
            "op": "create_column", "id": "c2",
            "level": {"by": "name", "value": "Этаж 1"},
            "symbol": {"by": "name", "value": "К 300x300"},
            "xy": {"at_grid": [{"grid": "А", "offset_mm": 200,
                                "toward": "Б"}, "1"]}}])
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        self.assertIn("P(0, 200, 0)", out.csharp)

    def test_beam_needs_z_and_gets_it(self):
        out = self._compile([{
            "op": "create_beam", "id": "b1",
            "level": {"by": "name", "value": "Этаж 1"},
            "symbol": {"by": "name", "value": "Балка 200x400"},
            "p0_mm": {"at_grid": ["А", "1"], "z_mm": 3000},
            "p1_mm": {"at_grid": ["А", "2"], "z_mm": 3000}}])
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])

    def test_addressed_and_literal_programs_emit_the_same_csharp(self):
        """В3 спеки: одна и та же программа, записанная адресами и литералами,
        обязана дать ПОБАЙТОВО одинаковую C#."""
        literal = self._compile([{
            "op": "create_wall", "id": "w1",
            "level": {"by": "name", "value": "Этаж 1"},
            "type": {"by": "name", "value": "ЖБ 200"},
            "height_mm": 3000,
            "p0_mm": [0, 0], "p1_mm": [4000, 0]}])
        addressed = self._compile([{
            "op": "create_wall", "id": "w1",
            "level": {"by": "name", "value": "Этаж 1"},
            "type": {"by": "name", "value": "ЖБ 200"},
            "height_mm": 3000,
            "p0_mm": {"at_grid": ["А", "1"]},
            "p1_mm": {"at_grid": ["А", "2"]}}])
        self.assertTrue(literal.ok and addressed.ok,
                        [d.as_dict() for d in
                         (literal.diagnostics + addressed.diagnostics)])
        # РАЗЛИЧИЕ РОВНО ОДНО И ОНО НАЗВАНО: штамп программы — дайджест
        # АВТОРСКОГО текста, а тексты честно разные (в этом и смысл адреса).
        # Всё остальное — create, post, witness — обязано совпасть побайтово.
        stamp = re.compile(r"kir:[0-9a-f]+:")
        self.assertNotEqual(literal.csharp, addressed.csharp)
        self.assertEqual(stamp.sub("kir:<stamp>:", literal.csharp),
                         stamp.sub("kir:<stamp>:", addressed.csharp))

    def test_delta_mm_is_not_addressable(self):
        """Смещение — не положение; адрес там бессмыслен."""
        out = self._compile([{
            "op": "move_elements", "id": "m1",
            "targets": [{"by": "element_id", "value": 777},
                        {"by": "element_id", "value": 778}],
            "delta_mm": {"at_grid": ["А", "1"], "z_mm": 0}}])
        self.assertFalse(out.ok)
        self.assertEqual([d.code for d in out.diagnostics], ["KIR-T001"])

    def test_face_normal_direction_is_not_addressable(self):
        """Пересечение осей — точка, но face_normal задаёт направление."""
        self.assertNotIn(
            "face_normal", relate.addressable_params("create_face_wall"))
        out = self._compile([{
            "op": "create_face_wall", "id": "fw1",
            "host": {"by": "element_id", "value": 900001},
            "type": {"by": "name", "value": "Кирпич 250"},
            "face_normal": {
                "at_grid": ["А", "1"], "z_mm": 3000},
            "location_line": "core_exterior"}])
        self.assertFalse(out.ok)
        self.assertIn("KIR-T001", [d.code for d in out.diagnostics])

    def test_no_snapshot_is_the_ground_code(self):
        out = compile_program({"ir_version": "1.0", "ops": [{
            "op": "create_column", "id": "c1",
            "level": {"by": "element_id", "value": 42},
            "symbol": {"by": "element_id", "value": 500},
            "xy": {"at_grid": ["А", "1"]}}]}, "2026", snapshot=None)
        self.assertFalse(out.ok)
        self.assertEqual([d.code for d in out.diagnostics], ["KIR-G103"])

    def test_registry_is_the_only_judge_of_where(self):
        """Список мест НЕ ведётся руками: он выводится из рода параметра."""
        from kukai.ir import spec
        derived = {(n, p.name) for n, o in spec.OPS.items() for p in o.params
                   if p.kind in ("pt_xy", "pt_xyz")}
        allowed = {(n, p) for n in spec.OPS
                   for p in relate.addressable_params(n)}
        self.assertEqual(derived - allowed, relate.ADDRESS_EXCLUDED)

    def test_arc_and_address_do_not_mix(self):
        out = self._compile([{
            "op": "create_wall", "id": "w1",
            "level": {"by": "name", "value": "Этаж 1"},
            "type": {"by": "name", "value": "ЖБ 200"},
            "height_mm": 3000,
            "p0_mm": {"at_grid": ["А", "1"]},
            "p1_mm": {"at_grid": ["А", "2"]},
            "arc": {"curve_type": "Arc", "center_mm": [3000, 0, 0],
                    "radius_mm": 3000, "x_axis": [1, 0, 0], "y_axis": [0, 1, 0],
                    "start_angle_rad": 0.0, "end_angle_rad": 3.14159}}])
        self.assertFalse(out.ok)
        self.assertIn("KIR-T001", [d.code for d in out.diagnostics])

    def test_zero_length_is_still_caught_after_resolution(self):
        """Закон «длина ~0» переехал за черту снапшота вместе с адресом,
        а не потерялся."""
        out = self._compile([{
            "op": "create_wall", "id": "w1",
            "level": {"by": "name", "value": "Этаж 1"},
            "type": {"by": "name", "value": "ЖБ 200"},
            "height_mm": 3000,
            "p0_mm": {"at_grid": ["А", "1"]},
            "p1_mm": {"at_grid": ["А", "1"]}}])
        self.assertFalse(out.ok)
        self.assertIn("KIR-T002", [d.code for d in out.diagnostics])

    def test_half_resolved_pair_keeps_its_typed_refusal(self):
        """ОПРОВЕРГАЮЩИЙ ТЕСТ дефекта, найденного 09.08.2026 на базе
        `2bfbec0a` и НЕ связанного с адресом от элемента: когда ОДИН конец
        адресован верно, а второй — на несуществующую ось, повторная площадка
        законов получала объект-адрес там, где ждала список, и вся программа
        отвечала «KIR-P000 внутренняя ошибка компилятора: KeyError». Честный
        KIR-G108 «оси нет в модели» к этому моменту УЖЕ лежал в диагностике и
        просто не доезжал до автора — то есть отказ с названным следующим
        ходом подменялся сообщением «чини компилятор»."""
        out = self._compile([{
            "op": "create_wall", "id": "w1",
            "level": {"by": "name", "value": "Этаж 1"},
            "type": {"by": "name", "value": "ЖБ 200"},
            "p0_mm": {"at_grid": ["НЕТ ТАКОЙ", "А"]},
            "p1_mm": {"at_grid": ["2", "А"]}}])
        self.assertFalse(out.ok)
        codes = [d.code for d in out.diagnostics]
        self.assertIn(relate.GRID_NOT_FOUND, codes)
        self.assertNotIn("KIR-P000", codes)

    def test_hosted_offset_law_survives_an_addressed_host(self):
        """Дверь за краем адресованной стены обязана отказывать так же, как
        за краем литеральной — иначе прибор покрывает часть диапазона."""
        ops = [
            {"op": "create_wall", "id": "w1",
             "level": {"by": "name", "value": "Этаж 1"},
             "type": {"by": "name", "value": "ЖБ 200"},
             "height_mm": 3000,
             "p0_mm": {"at_grid": ["А", "1"]},
             "p1_mm": {"at_grid": ["А", "2"]}},
            {"op": "create_door", "id": "d1",
             "host": {"by": "ref", "value": "w1"},
             "symbol": {"by": "name", "value": "Дверь 900x2100"},
             "offset_mm": 9000},
        ]
        out = self._compile(ops)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T002", [d.code for d in out.diagnostics])


# ── МАКРОСЫ: адрес не переносится геометрическим преобразованием ────────────

class MacrosAndAddresses(unittest.TestCase):

    def test_stack_transform_refuses_an_address(self):
        """`stack.transform` крутит и сужает план. Адрес крутить нельзя: ось
        от этого не переезжает. Молча пропустить — значит поставить все этажи
        в одну точку."""
        program = {"ir_version": "1.0", "ops": [{
            "op": "stack", "id": "s", "levels": 3, "h_mm": 3000,
            "transform": {"twist_deg_total": 5.0},
            "floor": [{"op": "create_column", "id": "c",
                       "symbol": {"by": "name", "value": "К 300x300"},
                       "xy": {"at_grid": ["А", "1"]}}]}]}
        out = compile_program(program, "2026", snapshot=_SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("stack.transform", out.diagnostics[0].message_ru)

    def test_stack_without_transform_keeps_the_address(self):
        program = {"ir_version": "1.0", "ops": [{
            "op": "stack", "id": "s", "levels": 2, "h_mm": 3000,
            "floor": [{"op": "create_column", "id": "c",
                       "symbol": {"by": "name", "value": "К 300x300"},
                       "xy": {"at_grid": ["А", "1"]}}]}]}
        out = compile_program(program, "2026", snapshot=_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])


# ── АДРЕС ОТ ЭЛЕМЕНТА ───────────────────────────────────────────────────────
#
# ГРАНИЦА ЭТОГО ПРИБОРА, СЛОВАМИ. Здесь доказывается ровно одно: что число,
# которое компилятор ВЫВЕЛ из адреса, побайтово совпадает с числом, которое
# автор посчитал бы руками, — и что каждый случай, где вывести его честно
# нельзя, кончается ТИПИЗИРОВАННЫМ отказом с названным следующим ходом.
# НЕ доказывается ничего о живой модели: что колонна встала на свою отметку,
# проверяет свидетель опа, а не этот файл.

_L2_ELEV = 3300   # отметка «Этаж 2» в фикстуре


def _columns(top: bool = True) -> list:
    """Две колонны на пересечениях осей, с привязкой верха ко второму этажу."""
    out = []
    for oid, grid in (("C1", "1"), ("C2", "2")):
        op = {"op": "create_column", "id": oid,
              "xy": {"at_grid": [grid, "А"]},
              "level": {"by": "name", "value": "Этаж 1"},
              "symbol": {"by": "name", "value": "К 300x300"}}
        if top:
            op["top_level"] = {"by": "name", "value": "Этаж 2"}
        out.append(op)
    return out


def _beam_on_columns() -> dict:
    return {"op": "create_beam", "id": "B1",
            "p0_mm": {"at_element": {"by": "ref", "value": "C1"},
                      "point": "center", "z": "top"},
            "p1_mm": {"at_element": {"by": "ref", "value": "C2"},
                      "point": "center", "z": "top"},
            "level": {"by": "name", "value": "Этаж 2"},
            "symbol": {"by": "name", "value": "Балка 200x400"}}


class ElementAddressResolves(unittest.TestCase):
    """Что адрес от элемента ДАЁТ — и что это ровно те же числа."""

    def _compile(self, ops, snapshot=None, version="2026"):
        return compile_program({"ir_version": "1.0", "ops": ops}, version,
                               snapshot=_SNAPSHOT if snapshot is None
                               else snapshot)

    def test_beam_on_top_of_columns(self):
        """ГЛАВНЫЙ СЛУЧАЙ: балка по верху двух колонн. Ни одного числа о
        положении балки в программе нет — все три вывел компилятор."""
        out = self._compile(_columns() + [_beam_on_columns()])
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        self.assertIn(
            "Line.CreateBound(P(0, 0, 3300), P(4000, 0, 3300))", out.csharp)

    def test_addressed_and_hand_computed_emit_the_same_csharp(self):
        """В3 спеки для второго семейства: программа, где модель посчитала
        координаты РУКАМИ, и программа, где их вывел компилятор, обязаны дать
        ПОБАЙТОВО одинаковую C# — иначе адрес меняет не происхождение числа,
        а само число."""
        by_hand = dict(_beam_on_columns(),
                       p0_mm=[0, 0, _L2_ELEV], p1_mm=[4000, 0, _L2_ELEV])
        literal = self._compile(_columns() + [by_hand])
        addressed = self._compile(_columns() + [_beam_on_columns()])
        self.assertTrue(literal.ok and addressed.ok,
                        [d.as_dict() for d in
                         (literal.diagnostics + addressed.diagnostics)])
        # Различие ровно одно и оно названо: штамп программы — дайджест
        # АВТОРСКОГО текста, а тексты честно разные (в этом и смысл адреса).
        stamp = re.compile(r"kir:[0-9a-f]+:")
        self.assertNotEqual(literal.csharp, addressed.csharp)
        self.assertEqual(stamp.sub("kir:<stamp>:", literal.csharp),
                         stamp.sub("kir:<stamp>:", addressed.csharp))

    def test_no_trigonometry_reaches_the_emitted_csharp(self):
        """Ни одной тригонометрической функции и ни одного чтения отметки
        уровня ради адреса: всё посчитано на компиляции."""
        out = self._compile(_columns() + [_beam_on_columns()])
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        for token in ("Math.Sin", "Math.Cos", "Math.Atan", "Math.Sqrt"):
            self.assertNotIn(token, out.csharp)

    def test_the_chain_grid_then_element(self):
        """Колонна адресована ОТ ОСЕЙ, балка — ОТ КОЛОННЫ. Цепочка держится
        порядком заземления, а не отдельной проверкой."""
        out = self._compile(_columns() + [_beam_on_columns()])
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        rules = {row["rule"] for row in out.grounding_report}
        self.assertEqual(rules, {"at_grid", "at_element"})

    def test_per_op_address_keeps_the_runtime_dependency_gate(self):
        """GROUND заменяет адрес числом, но зависимость не исчезает: если
        колонна отказана в своём SubTransaction, балка не должна строиться
        отдельно по уже вычисленным координатам несуществующей опоры."""
        out = compile_program(
            {"ir_version": "1.0", "ops": _columns() + [_beam_on_columns()]},
            "2026", snapshot=_SNAPSHOT, isolation="per_op")
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        self.assertIn(
            'if (!__ok_C1) throw __OpRefuse("B1", '
            '"опорный оп «C1» отказан — оп пропущен");', out.csharp)
        self.assertIn(
            'if (!__ok_C2) throw __OpRefuse("B1", '
            '"опорный оп «C2» отказан — оп пропущен");', out.csharp)

    def test_the_receipt_names_the_summands(self):
        """Квитанция обязана показать АРИФМЕТИКУ, которую компилятор взял на
        себя: отметку уровня и отступ по отдельности. Вывод, который некому
        предъявить, неотличим от `.FirstOrDefault()` в костюме."""
        from kukai.ir.ground import describe_choices_ru
        out = self._compile(_columns() + [_beam_on_columns()])
        text = describe_choices_ru(out.grounding_report)
        self.assertIn("«C1» (create_column) → center", text)
        self.assertIn("отметка top = 3300 + 0 мм", text)
        self.assertIn("[0, 0, 3300]", text)

    def test_the_receipt_formats_a_negative_offset_as_subtraction(self):
        from kukai.ir.ground import describe_choices_ru
        ops = _columns()
        for op in ops:
            op["top_offset_mm"] = -400
        out = self._compile(ops + [_beam_on_columns()])
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        text = describe_choices_ru(out.grounding_report)
        self.assertIn("отметка top = 3300 − 400 мм", text)
        self.assertNotIn("+ -400", text)

    def test_top_offset_rides_the_elevation(self):
        ops = _columns()
        for op in ops:
            op["top_offset_mm"] = -200
        out = self._compile(ops + [_beam_on_columns()])
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        self.assertIn("P(0, 0, 3100)", out.csharp)

    def test_base_reads_the_level_and_its_offset(self):
        ops = _columns()
        for op in ops:
            op["base_offset_mm"] = 150
        beam = dict(_beam_on_columns())
        beam["p0_mm"] = {"at_element": {"by": "ref", "value": "C1"},
                         "point": "center", "z": "base"}
        beam["p1_mm"] = {"at_element": {"by": "ref", "value": "C2"},
                         "point": "center", "z": "base"}
        out = self._compile(ops + [beam])
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        self.assertIn("Line.CreateBound(P(0, 0, 150), P(4000, 0, 150))",
                      out.csharp)

    def test_slanted_column_top_uses_top_xy_and_is_byte_equivalent(self):
        """В текущем реестре у колонны есть `top_xy`. Взять нижний `xy` при
        z=top — тихий плановый промах, хотя отметка и свидетель балки верны."""
        column = {
            "op": "create_column", "id": "C1", "xy": [0, 0],
            "top_xy": [1000, 500],
            "level": {"by": "name", "value": "Этаж 1"},
            "top_level": {"by": "name", "value": "Этаж 2"},
            "symbol": {"by": "name", "value": "К 300x300"}}
        beam = {
            "op": "create_beam", "id": "B1",
            "p0_mm": {"at_element": {"by": "ref", "value": "C1"},
                      "point": "center", "z": "top"},
            "p1_mm": [4000, 500, _L2_ELEV],
            "level": {"by": "name", "value": "Этаж 2"},
            "symbol": {"by": "name", "value": "Балка 200x400"}}
        addressed = self._compile([column, beam])
        literal = self._compile([
            column, dict(beam, p0_mm=[1000, 500, _L2_ELEV])])
        self.assertTrue(addressed.ok and literal.ok,
                        [d.as_dict() for d in
                         (addressed.diagnostics + literal.diagnostics)])
        self.assertIn(
            "Line.CreateBound(P(1000, 500, 3300), P(4000, 500, 3300))",
            addressed.csharp)
        stamp = re.compile(r"kir:[0-9a-f]+:")
        self.assertEqual(stamp.sub("kir:<stamp>:", addressed.csharp),
                         stamp.sub("kir:<stamp>:", literal.csharp))

    def test_wall_end_feeds_the_next_wall(self):
        """Плоский параметр: стык стен без переписывания координаты."""
        out = self._compile([
            {"op": "create_wall", "id": "W1",
             "p0_mm": {"at_grid": ["А", "1"]},
             "p1_mm": {"at_grid": ["А", "2"]},
             "level": {"by": "name", "value": "Этаж 1"},
             "type": {"by": "name", "value": "ЖБ 200"}},
            {"op": "create_wall", "id": "W2",
             "p0_mm": {"at_element": {"by": "ref", "value": "W1"},
                       "point": "end"},
             "p1_mm": [4000, 4500],
             "level": {"by": "name", "value": "Этаж 1"},
             "type": {"by": "name", "value": "ЖБ 200"}}])
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        self.assertIn(
            "Line.CreateBound(P(4000, 0, 0), P(4000, 4500, 0))", out.csharp)

    def test_center_of_a_wall(self):
        out = self._compile([
            {"op": "create_wall", "id": "W1",
             "p0_mm": [0, 0], "p1_mm": [4000, 0],
             "level": {"by": "name", "value": "Этаж 1"},
             "type": {"by": "name", "value": "ЖБ 200"}},
            {"op": "create_column", "id": "C9",
             "xy": {"at_element": {"by": "ref", "value": "W1"},
                    "point": "center"},
             "level": {"by": "name", "value": "Этаж 1"},
             "symbol": {"by": "name", "value": "К 300x300"}}])
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        self.assertIn("P(2000, 0, 0)", out.csharp)

    def test_axis_elevation_of_a_beam(self):
        """У объёмной оси отметка станции лежит в самой программе."""
        out = self._compile([
            {"op": "create_beam", "id": "B0",
             "p0_mm": [0, 0, 3000], "p1_mm": [4000, 0, 3500],
             "level": {"by": "name", "value": "Этаж 1"},
             "symbol": {"by": "name", "value": "Балка 200x400"}},
            {"op": "create_beam", "id": "B1",
             "p0_mm": {"at_element": {"by": "ref", "value": "B0"},
                       "point": "end", "z": "axis"},
             "p1_mm": [8000, 0, 3500],
             "level": {"by": "name", "value": "Этаж 1"},
             "symbol": {"by": "name", "value": "Балка 200x400"}}])
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        self.assertIn("P(4000, 0, 3500)", out.csharp)

    def test_z_mm_is_the_third_way_to_name_an_elevation(self):
        beam = dict(_beam_on_columns())
        beam["p0_mm"] = {"at_element": {"by": "ref", "value": "C1"},
                         "point": "center", "z_mm": 5000}
        beam["p1_mm"] = {"at_element": {"by": "ref", "value": "C2"},
                         "point": "center", "z_mm": 5000}
        out = self._compile(_columns() + [beam])
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        self.assertIn("Line.CreateBound(P(0, 0, 5000), P(4000, 0, 5000))",
                      out.csharp)

    def test_level_built_by_this_same_program(self):
        """Отметка уровня, созданного ЭТОЙ ЖЕ программой, берётся из неё же —
        снапшот про такой уровень не знает ничего и знать не может."""
        out = self._compile([
            {"op": "create_level", "id": "L9", "elev_mm": 7200,
             "name": "Этаж 9"},
            {"op": "create_column", "id": "C1", "xy": [0, 0],
             "level": {"by": "name", "value": "Этаж 1"},
             "top_level": {"by": "ref", "value": "L9"},
             "symbol": {"by": "name", "value": "К 300x300"}},
            {"op": "create_beam", "id": "B1",
             "p0_mm": {"at_element": {"by": "ref", "value": "C1"},
                       "point": "center", "z": "top"},
             "p1_mm": [4000, 0, 7200],
             "level": {"by": "name", "value": "Этаж 1"},
             "symbol": {"by": "name", "value": "Балка 200x400"}}])
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        self.assertIn("P(0, 0, 7200)", out.csharp)


class ElementAddressRefusesLoudly(unittest.TestCase):
    """Каждый случай, где число вывести честно нельзя, — ТИПИЗИРОВАННЫЙ отказ
    с НАЗВАННЫМ следующим ходом. Молчаливый ноль здесь был бы дороже отказа:
    свидетель сверяет элемент с тем же нулём и пропустил бы его."""

    def _compile(self, ops, snapshot=None):
        return compile_program({"ir_version": "1.0", "ops": ops}, "2026",
                               snapshot=_SNAPSHOT if snapshot is None
                               else snapshot)

    def _codes(self, out) -> list:
        return [d.code for d in out.diagnostics]

    def test_existing_model_element_is_refused_with_the_measured_reason(self):
        """ЗАМЕР, А НЕ ВКУС: в снапшоте ground нет ни одной строки геометрии
        существующего элемента, поэтому `element_id` отказывает."""
        beam = dict(_beam_on_columns())
        beam["p0_mm"] = {"at_element": {"by": "element_id", "value": 12345},
                         "point": "center", "z": "top"}
        out = self._compile(_columns() + [beam])
        self.assertFalse(out.ok)
        self.assertIn("KIR-T001", self._codes(out))
        message = " ".join(d.message_ru for d in out.diagnostics)
        self.assertIn("levels, load_cases, grids", message)

    def test_forward_reference_refuses_offline(self):
        """Ссылка вперёд — чистая функция от текста, и отказ обязан прийти БЕЗ
        снапшота: это тот самый обход DAG, ради которого ребро вынуто из
        глубины значения."""
        out = compile_program(
            {"ir_version": "1.0", "ops": [_beam_on_columns()] + _columns()},
            "2026", snapshot=None)
        self.assertFalse(out.ok)
        self.assertIn("KIR-L003", self._codes(out))

    def test_a_room_is_refused_by_name_with_its_reason(self):
        """Пустая строка таблицы отправила бы автора гадать — поэтому у
        каждого отвергнутого рода есть ПРИЧИНА, и она в отказе."""
        out = self._compile([
            {"op": "create_room", "id": "R1", "xy": [1000, 1000],
             "level": {"by": "name", "value": "Этаж 1"}},
            {"op": "create_column", "id": "C1",
             "xy": {"at_element": {"by": "ref", "value": "R1"},
                    "point": "center"},
             "level": {"by": "name", "value": "Этаж 1"},
             "symbol": {"by": "name", "value": "К 300x300"}}])
        self.assertFalse(out.ok)
        self.assertIn(relate.ELEMENT_NOT_ADDRESSABLE, self._codes(out))
        self.assertIn("ТОЧКА ПОСЕВА",
                      " ".join(d.message_ru for d in out.diagnostics))

    def test_top_without_top_level_refuses_and_names_the_move(self):
        """Без привязки верха высота приезжает из УМОЛЧАНИЯ, которого автор не
        произносил, — ровно тот дефект, что откатывал верные фасадные стены."""
        out = self._compile(_columns(top=False) + [_beam_on_columns()])
        self.assertFalse(out.ok)
        self.assertIn(relate.ELEMENT_PART_INVALID, self._codes(out))
        self.assertIn("допишите top_level",
                      " ".join(d.message_ru for d in out.diagnostics))

    def test_a_point_element_has_no_start(self):
        beam = dict(_beam_on_columns())
        beam["p0_mm"] = {"at_element": {"by": "ref", "value": "C1"},
                         "point": "start", "z": "top"}
        out = self._compile(_columns() + [beam])
        self.assertFalse(out.ok)
        self.assertIn(relate.ELEMENT_PART_INVALID, self._codes(out))

    def test_slanted_column_refuses_an_ambiguous_plan_station(self):
        """Без z=base|top у наклонной оси две честные плановые точки;
        `center` не даёт права выбрать нижнюю молча."""
        source = {
            "op": "create_column", "id": "C1", "xy": [0, 0],
            "top_xy": [1000, 500],
            "level": {"by": "name", "value": "Этаж 1"},
            "top_level": {"by": "name", "value": "Этаж 2"},
            "symbol": {"by": "name", "value": "К 300x300"}}
        follower = {
            "op": "create_column", "id": "C2",
            "xy": {"at_element": {"by": "ref", "value": "C1"},
                   "point": "center"},
            "level": {"by": "name", "value": "Этаж 1"},
            "symbol": {"by": "name", "value": "К 300x300"}}
        out = self._compile([source, follower])
        self.assertFalse(out.ok)
        self.assertIn(relate.ELEMENT_PART_INVALID, self._codes(out))
        self.assertIn("наклонная (`top_xy` задан)",
                      " ".join(d.message_ru for d in out.diagnostics))

    def test_a_grid_has_no_elevation(self):
        out = self._compile([
            {"op": "create_grid", "id": "G1", "p0_mm": [0, 0],
             "p1_mm": [0, 9000], "name": "Ф"},
            {"op": "create_beam", "id": "B1",
             "p0_mm": {"at_element": {"by": "ref", "value": "G1"},
                       "point": "start", "z": "base"},
             "p1_mm": [4000, 0, 3000],
             "level": {"by": "name", "value": "Этаж 1"},
             "symbol": {"by": "name", "value": "Балка 200x400"}}])
        self.assertFalse(out.ok)
        self.assertIn(relate.ELEMENT_PART_INVALID, self._codes(out))

    def test_a_grid_built_here_can_still_feed_a_plan_point(self):
        """Обратная сторона того же: ось, созданная ЭТОЙ ЖЕ программой,
        `at_grid` адресовать не может (снимок снят раньше) — а `at_element`
        может, потому что читает программу."""
        out = self._compile([
            {"op": "create_grid", "id": "G1", "p0_mm": [0, 0],
             "p1_mm": [0, 9000], "name": "Ф"},
            {"op": "create_column", "id": "C1",
             "xy": {"at_element": {"by": "ref", "value": "G1"},
                    "point": "start"},
             "level": {"by": "name", "value": "Этаж 1"},
             "symbol": {"by": "name", "value": "К 300x300"}}])
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        self.assertIn("P(0, 0, 0)", out.csharp)

    def test_arc_wall_has_no_center(self):
        """Середина ХОРДЫ лежит вне дуговой стены — молча вернуть её значило
        бы промахнуться тем сильнее, чем круче изгиб."""
        arc = {"curve_type": "Arc", "center_mm": [2000, 0, 0],
               "radius_mm": 2000, "x_axis": [1, 0, 0], "y_axis": [0, 1, 0],
               "start_angle_rad": 0.0, "end_angle_rad": 3.14159}
        base = {"op": "create_wall", "id": "W1",
                "p0_mm": [4000, 0], "p1_mm": [0, 0], "arc": arc,
                "level": {"by": "name", "value": "Этаж 1"},
                "type": {"by": "name", "value": "ЖБ 200"}}
        follower = {"op": "create_column", "id": "C1",
                    "level": {"by": "name", "value": "Этаж 1"},
                    "symbol": {"by": "name", "value": "К 300x300"}}
        refused = self._compile([base, dict(
            follower, xy={"at_element": {"by": "ref", "value": "W1"},
                          "point": "center"})])
        self.assertFalse(refused.ok)
        self.assertIn(relate.ELEMENT_PART_INVALID, self._codes(refused))
        # А концы дуговой стены честные: `materialize._reconcile_arc_endpoints`
        # выводит p0/p1 ИЗ САМОЙ дуги.
        allowed = self._compile([base, dict(
            follower, xy={"at_element": {"by": "ref", "value": "W1"},
                          "point": "end"})])
        self.assertTrue(allowed.ok, [d.as_dict() for d in allowed.diagnostics])

    def test_capture_gap_is_named_not_zeroed(self):
        """Строка уровня БЕЗ elevation_mm — пробел ЗАХВАТА, а не ноль.
        Подставленный ноль поставил бы балку на отметку нуля модели и прошёл
        бы свидетеля, который сверяет с тем же нулём."""
        snapshot = dict(_SNAPSHOT)
        snapshot["levels"] = [{"id": row["id"], "name": row["name"]}
                              for row in _SNAPSHOT["levels"]]
        out = self._compile(_columns() + [_beam_on_columns()],
                            snapshot=snapshot)
        self.assertFalse(out.ok)
        self.assertIn(relate.ELEMENT_CAPTURE_GAP, self._codes(out))
        self.assertIn("пробел ЗАХВАТА",
                      " ".join(d.message_ru for d in out.diagnostics))

    def test_zero_length_law_reaches_the_element_address(self):
        """Балка «из C1 в C1» — нулевая длина, и закон обязан доехать за
        черту снапшота вместе с адресом (прибор на часть диапазона опаснее
        отсутствующего)."""
        beam = dict(_beam_on_columns())
        beam["p1_mm"] = {"at_element": {"by": "ref", "value": "C1"},
                         "point": "center", "z": "top"}
        out = self._compile(_columns() + [beam])
        self.assertFalse(out.ok)
        self.assertIn("KIR-T002", self._codes(out))

    def test_z_and_z_mm_together_are_two_answers_to_one_question(self):
        beam = dict(_beam_on_columns())
        beam["p0_mm"] = {"at_element": {"by": "ref", "value": "C1"},
                         "point": "center", "z": "top", "z_mm": 1000}
        out = self._compile(_columns() + [beam])
        self.assertFalse(out.ok)
        self.assertIn("Отметка названа ДВАЖДЫ",
                      " ".join(d.message_ru for d in out.diagnostics))

    def test_a_flat_parameter_refuses_an_elevation(self):
        out = self._compile([
            {"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
             "p1_mm": [4000, 0],
             "level": {"by": "name", "value": "Этаж 1"},
             "type": {"by": "name", "value": "ЖБ 200"}},
            {"op": "create_wall", "id": "W2",
             "p0_mm": {"at_element": {"by": "ref", "value": "W1"},
                       "point": "end", "z": "base"},
             "p1_mm": [4000, 4500],
             "level": {"by": "name", "value": "Этаж 1"},
             "type": {"by": "name", "value": "ЖБ 200"}}])
        self.assertFalse(out.ok)
        self.assertIn("отметка здесь лишняя",
                      " ".join(d.message_ru for d in out.diagnostics))

    def test_a_volumetric_parameter_demands_an_elevation(self):
        beam = dict(_beam_on_columns())
        beam["p0_mm"] = {"at_element": {"by": "ref", "value": "C1"},
                         "point": "center"}
        out = self._compile(_columns() + [beam])
        self.assertFalse(out.ok)
        self.assertIn("допишите z",
                      " ".join(d.message_ru for d in out.diagnostics))

    def test_unknown_key_prints_the_closed_grammar(self):
        beam = dict(_beam_on_columns())
        beam["p0_mm"] = {"at_element": {"by": "ref", "value": "C1"},
                         "part": "center", "z": "top"}
        out = self._compile(_columns() + [beam])
        self.assertFalse(out.ok)
        message = " ".join(d.message_ru for d in out.diagnostics)
        self.assertIn("Грамматика ЗАКРЫТА", message)
        self.assertIn('"point": "start|end|center"', message)

    def test_unknown_point_name_prints_the_closed_vocabulary(self):
        beam = dict(_beam_on_columns())
        beam["p0_mm"] = {"at_element": {"by": "ref", "value": "C1"},
                         "point": "middle", "z": "top"}
        out = self._compile(_columns() + [beam])
        self.assertFalse(out.ok)
        self.assertIn("['start', 'end', 'center']",
                      " ".join(d.message_ru for d in out.diagnostics))

    def test_inside_a_stack_the_reference_resolves_PER_STOREY(self):
        """🔴 ИСКОПАЕМОЕ ПЕРЕПИСАНО 15.08.2026 — СМЕНИЛСЯ ПРЕДМЕТ, НЕ ПОРОГ.

        Тест утверждал: «`stack` переименовывает опы по этажам и НЕ переписывает
        ссылки — проверяется, что это ГРОМКО», и ждал `KIR-L003`. Волна типового
        этажа (`0efcb2b0`) научила экспансию ПЕРЕПИСЫВАТЬ ссылки, и утверждение
        перестало быть правдой о коде: программа ниже теперь законна.

        Форма 9 канона в чистом виде — прозу никто не мутирует, поэтому тест
        пережил смену поведения и покраснел лишь на полном прогоне. Удалять его
        было нельзя: у него есть ВЫЖИВШИЙ предмет, и он проверяется здесь —
        ссылка внутри набора обязана резолвиться ПОЭТАЖНО, а не на первый этаж.

        Проверяется РАЗРЕШЕНИЕ ССЫЛКИ, а не то, что программа собралась: «оно
        скомпилировалось» не отличает верный этаж от первого.
        """
        floor = [
            {"op": "create_column", "id": "c", "xy": [0, 0],
             "symbol": {"by": "name", "value": "К 300x300"}},
            {"op": "create_beam", "id": "b",
             "p0_mm": {"at_element": {"by": "ref", "value": "c"},
                       "point": "center", "z_mm": 3000},
             "p1_mm": [4000, 0, 3000],
             "symbol": {"by": "name", "value": "Балка 200x400"}},
        ]
        ops = macros._expand_stack(
            {"op": "stack", "id": "s", "levels": 2, "h_mm": 3000,
             "floor": floor})

        beams = [o for o in ops if o["op"] == "create_beam"]
        self.assertEqual(len(beams), 2, "экспансия не дала по балке на этаж — "
                                        "контроль вырожден, сравнивать нечего")
        for beam in beams:
            with self.subTest(beam=beam["id"]):
                ref = beam["p0_mm"]["at_element"]["value"]
                storey = beam["id"].rsplit("_", 1)[0]      # 's_L2_b' -> 's_L2'
                self.assertEqual(
                    ref, f"{storey}_c",
                    "балка адресует колонну ЧУЖОГО этажа — ровно тот молчаливо "
                    "неверный исход, ради запрета которого ссылки переписываются")

    def test_a_reference_OUT_of_the_stack_is_still_refused_loudly(self):
        """Вторая половина, без которой первая ничего не стоит.

        Переписать можно только ссылку на ЧЛЕНА набора. Ссылка наружу
        переписываться не может по построению, и она обязана оставаться
        ГРОМКИМ отказом — иначе хостящийся оп на каждом этаже повис бы на одном
        и том же чужом элементе, и это была бы тихая неправда.
        """
        with self.assertRaises(Exception) as caught:
            macros._expand_stack(
                {"op": "stack", "id": "s", "levels": 2, "h_mm": 3000,
                 "floor": [{"op": "create_door", "id": "d",
                            "host": {"by": "ref", "value": "outsider"},
                            "offset_mm": 1000}]})
        text = str(caught.exception)
        self.assertIn("KIR-M001", text)
        self.assertIn("outsider", text,
                      "отказ обязан НАЗВАТЬ хозяина, которого не нашёл")


    def test_a_contour_corner_says_why_the_element_address_is_not_taken(self):
        """Слот, а не синтаксис: форма верная, но контур опускается в рёбра
        ДО заземления программы. Общий «неизвестная форма точки» послал бы
        автора чинить то, что не сломано."""
        out = self._compile([
            {"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
             "p1_mm": [4000, 0],
             "level": {"by": "name", "value": "Этаж 1"},
             "type": {"by": "name", "value": "ЖБ 200"}},
            {"op": "create_floor_by_contour", "id": "F1",
             "level": {"by": "name", "value": "Этаж 1"},
             "contour": {"outer": {
                 "shape": "rect",
                 "origin": {"at_element": {"by": "ref", "value": "W1"},
                            "point": "start"},
                 "size_mm": [4000, 3000]}}}])
        self.assertFalse(out.ok)
        self.assertIn("контур опускается в рёбра",
                      " ".join(d.message_ru for d in out.diagnostics))

    def test_the_grid_resolver_stays_total(self):
        """`resolve_address` принимает адрес от осей; отданный ему адрес от
        элемента обязан быть ТИПИЗИРОВАННЫМ отказом, а не KeyError, — иначе
        отказ снова подменится «внутренней ошибкой компилятора»."""
        diags: list = []
        point = relate.resolve_address(
            {"at_element": {"by": "ref", "value": "C1"}, "point": "center"},
            _orthogonal_pool(), "op1", "xy", diags, dims=2)
        self.assertIsNone(point)
        self.assertEqual([d.code for d in diags], ["KIR-T001"])

    def test_the_element_resolver_stays_total(self):
        """Симметричный шов: грид-адрес, отданный резолверу элемента,
        обязан отказать типизированно, а не упасть на `at_element`."""
        diags: list = []
        point = relate.resolve_element_address(
            {"at_grid": ["А", "1"]}, {}, [], "op1", "xy", diags, dims=2)
        self.assertIsNone(point)
        self.assertEqual([d.code for d in diags], ["KIR-T001"])


class ElementAddressRegistriesAreClosed(unittest.TestCase):
    """Замки на сами реестры. Реестр, который перестал сверяться с кодом,
    превращает закрытую грамматику в список благих намерений."""

    def test_every_rejected_op_carries_a_reason(self):
        for name, why in relate.ELEMENT_REJECTED.items():
            self.assertTrue(isinstance(why, str) and len(why) > 40,
                            f"{name}: причина отказа пуста или формальна")

    def test_allowed_and_rejected_do_not_overlap(self):
        self.assertFalse(
            set(relate.ELEMENT_GEOMETRY) & set(relate.ELEMENT_REJECTED))

    def test_every_addressable_source_is_decided_one_way_or_the_other(self):
        """Оп, у которого есть точечный параметр, ОБЯЗАН быть либо адресуемым,
        либо названным в отвергнутых. Молчаливая третья корзина — это ровно
        та «пустая строка таблицы», из-за которой автор гадает."""
        from kukai.ir import spec
        undecided = sorted(
            name for name in spec.OPS
            if relate.addressable_params(name)
            and name not in relate.ELEMENT_GEOMETRY
            and name not in relate.ELEMENT_REJECTED)
        self.assertEqual(undecided, [])

    def test_non_geometric_point_fields_are_rejected_by_name(self):
        """Три новых точечных рода — trace/axis/direction, не координаты
        тела. Они обязаны оставаться в явной корзине отказа, иначе следующий
        registry wave снова предложит их как адресуемую геометрию."""
        cases = {
            "create_extrusion_roof": "СЛЕД РАБОЧЕЙ ПЛОСКОСТИ",
            "create_solid_revolve": "ОСЬ ВРАЩЕНИЯ",
            "create_face_wall": "НАПРАВЛЕНИЕ",
        }
        for name, evidence in cases.items():
            self.assertIn(name, relate.ELEMENT_REJECTED)
            self.assertIn(evidence, relate.ELEMENT_REJECTED[name])

            diags: list = []
            point = relate.resolve_element_address(
                {"at_element": {"by": "ref", "value": "X"},
                 "point": "center"},
                {"X": {"op": name}}, [], "follow", "xy", diags, dims=2)
            self.assertIsNone(point)
            self.assertEqual([d.code for d in diags],
                             [relate.ELEMENT_NOT_ADDRESSABLE])
            self.assertIn(evidence, diags[0].message_ru)

    def test_the_grammar_has_no_binary_node(self):
        """Композиции нет и здесь: у узла РОВНО ОДИН селектор, поэтому
        «середина между А и Б» невыразима по построению, а не по запрету."""
        for keys in relate.ELEMENT_ADDRESS_FORMS:
            self.assertEqual(
                sum(1 for k in keys if k == "at_element"), 1)
            self.assertFalse({"at_grid", "between", "plus"} & set(keys))


if __name__ == "__main__":
    unittest.main()
