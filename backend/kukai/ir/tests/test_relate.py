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

from kukai.ir import contour, relate                       # noqa: E402
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


if __name__ == "__main__":
    unittest.main()
