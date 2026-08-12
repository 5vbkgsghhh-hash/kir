"""wave/solid — параметрическое тело: замкнутые формы, эмиссия, вакуумность.

ЧТО ЭТОТ НАБОР ДОКАЗЫВАЕТ, А ЧТО НЕТ.

Доказывает офлайн:
  * замкнутые формы мер контура СХОДЯТСЯ С НЕЗАВИСИМЫМ ПРИБОРОМ (плотная
    полигональная выборка) — то есть эталон, с которым сверяется свидетель,
    посчитан верно;
  * свидетель ЧИТАЕТ ГЕОМЕТРИЮ, а не константу: тронь профиль или высоту —
    эталон в эмитируемой C# обязан поехать;
  * свидетель МОЖЕТ ПРОВАЛИТЬСЯ: подмена, которая нас волнует (исчез проём,
    не та высота, оборот не замкнулся), по величине заведомо больше допуска —
    и это ДОКАЗАНО, а не промоделировано, потому что рантайм-запрет
    вакуумности гарантирует `допуск < самая мелкая объявленная часть`;
  * запреты: контур за осью, категория-самозванец, отсутствие отсутствует.

НЕ доказывает и доказать офлайн не может: что Revit построит именно это тело
и что `Solid.Volume` совпадёт с эталоном с точностью до выведенного допуска.
Это первый живой прогон; квитанция везёт сырую пару ожидание/замер именно
затем, чтобы он ИЗМЕРИЛ остаток, а не оценил.
"""
from __future__ import annotations

import math
import os
import re
import tempfile
import unittest

os.environ.setdefault(
    "KIR_REJECTIONS_PATH",
    os.path.join(tempfile.gettempdir(), "kir_solid_queue.jsonl"))

from kukai.ir import contour as C                                  # noqa: E402
from kukai.ir import spec                                          # noqa: E402
from kukai.ir.authoring import _EMITTERS                           # noqa: E402
from kukai.ir.compiler import compile_program                      # noqa: E402
from kukai.ir.emit_model import post_to_string                     # noqa: E402
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT                # noqa: E402

VERSIONS = ("2021", "2022", "2023", "2024", "2025", "2026")


def _prog(*ops, intent="тело"):
    return {"ir_version": "1.0", "intent": intent, "ops": list(ops)}


def _extrusion(**over):
    op = {"op": "create_solid_extrusion", "id": "SX",
          "profile": {"outer": {"shape": "rect", "origin": [0, 0],
                                "size_mm": [4000, 3000]}},
          "height_mm": 2500, "category": "generic_model", "name": "призма"}
    op.update(over)
    return op


def _revolve(**over):
    op = {"op": "create_solid_revolve", "id": "SR",
          "profile": {"outer": {"shape": "rect", "origin": [1000, 0],
                                "size_mm": [800, 2400]}},
          "axis_xy_mm": [0, 0], "sweep_deg": 360,
          "category": "generic_model", "name": "кольцо"}
    op.update(over)
    return op


def _emit(op, ver="2023"):
    """(decl, create, post-как-C#, readback) одного опа после грунтовки."""
    grounded = _ground(op)
    decl, create, checks, readback = _EMITTERS[op["op"]](
        grounded, ver, "kir:test")
    return decl, create, post_to_string(op["id"], checks), readback


def _ground(op):
    from kukai.ir import ground as ground_mod
    from kukai.ir.compiler import _parse_and_check
    return ground_mod.ground(_parse_and_check(_prog(op)), GROUND_SNAPSHOT)[0]


def _num_after(text: str, pattern: str) -> float:
    m = re.search(pattern, text)
    assert m is not None, f"в эмиссии нет {pattern!r}:\n{text}"
    return float(m.group(1))


# ── 1. ЗАМКНУТЫЕ ФОРМЫ ПРОТИВ НЕЗАВИСИМОГО ПРИБОРА ──────────────────────────

class ClosedFormsAgreeWithSampling(unittest.TestCase):
    """Эталон свидетеля считается интегралом по границе. Проверяется он ДРУГИМ
    прибором — плотной полигональной выборкой, — потому что сверять формулу с
    самой собой значит проверять переменную на себя.

    Порог 1e-6 выбран НЕ на глаз: собственная ошибка выборки в N хорд есть
    O(1/N²), при N=4000 это 6e-8, и наблюдаемое расхождение обязано быть ЕЁ
    порядка. Порог на порядок с лишним выше наблюдаемого и на порядки ниже
    любой содержательной ошибки формулы.
    """

    SHAPES = {
        "rect": {"shape": "rect", "origin": [1000, 2000],
                 "size_mm": [3000, 4000]},
        "rect_rotated": {"shape": "rect", "origin": [1000, 2000],
                         "size_mm": [3000, 4000], "rotation_deg": 37},
        "l_shape": {"shape": "l", "origin": [500, 500], "size_mm": [4000, 5000],
                    "cut_mm": [1500, 2000], "corner": "ne"},
        "triangle": {"shape": "poly",
                     "points_mm": [[1000, 0], [5000, 0], [3000, 4000]]},
        "arc_out": {"shape": "poly",
                    "points_mm": [[1000, 0], [5000, 0], [5000, 3000],
                                  [1000, 3000]],
                    "arcs": [{"edge": 2, "bulge": 0.6}]},
        "arc_in": {"shape": "poly",
                   "points_mm": [[1000, 0], [5000, 0], [5000, 3000],
                                 [1000, 3000]],
                   "arcs": [{"edge": 2, "bulge": -0.6}]},
        "two_arcs": {"shape": "poly",
                     "points_mm": [[1200, 100], [6000, 0], [6000, 3000],
                                   [1000, 3400]],
                     "arcs": [{"edge": 0, "bulge": -0.35},
                              {"edge": 2, "bulge": 0.9}]},
        # Обход ПО ЧАСОВОЙ: CONTOUR принимает обе ориентации, и меры обязаны
        # нормализоваться по знаку собственной площади, а не по вере в порядок.
        "clockwise": {"shape": "poly",
                      "points_mm": [[1000, 0], [3000, 4000], [5000, 0]]},
    }
    N_CHORDS = 4000

    def _dense(self, edges):
        poly = []
        for p0, p1, bulge in edges:
            if abs(bulge) < 1e-9:
                poly.append(list(p0))
                continue
            (cx, cy), r, a0, sweep = C._arc_geometry(p0, p1, bulge)
            for k in range(self.N_CHORDS):
                a = a0 + sweep * k / self.N_CHORDS
                poly.append([cx + r * math.cos(a), cy + r * math.sin(a)])
        area = moment = length = x_ds = 0.0
        n = len(poly)
        for k in range(n):
            ax, ay = poly[k]
            bx, by = poly[(k + 1) % n]
            area += 0.5 * (ax * by - ay * bx)
            moment += (by - ay) * (ax * ax + ax * bx + bx * bx) / 6.0
            d = math.hypot(bx - ax, by - ay)
            length += d
            x_ds += d * (ax + bx) / 2.0
        return area, moment, length, x_ds

    def test_area_moment_length_and_pappus_integral_match_dense_sampling(self):
        worst = 0.0
        for name, shape in sorted(self.SHAPES.items()):
            diags = []
            edges = C._validate_shape(shape, [], "T", "profile", diags)
            self.assertIsNotNone(edges, f"{name}: {diags}")
            closed = C.loop_measures(edges)
            sampled = self._dense(edges)
            for label, a, b in zip(("area", "moment", "length", "x_ds"),
                                   closed, sampled):
                with self.subTest(shape=name, measure=label):
                    rel = abs(a - b) / max(1e-9, abs(b))
                    worst = max(worst, rel)
                    self.assertLess(rel, 1e-6)
        # Число ЗАПИСАНО, а не только проверено: следующая волна должна видеть,
        # каким прибором и с каким согласием эталон получен.
        self.assertLess(worst, 1e-6, f"худшее относительное расхождение {worst:.2e}")

    def test_analytic_values_are_exact_on_shapes_with_known_answers(self):
        """Там, где ответ известен школьной формулой, он совпадает точно."""
        rect = C._validate_shape(self.SHAPES["rect"], [], "T", "p", [])
        area, moment, length, _ = C.loop_measures(rect)
        self.assertAlmostEqual(area, 3000.0 * 4000.0, places=6)
        self.assertAlmostEqual(length, 2 * (3000.0 + 4000.0), places=6)
        # Центроид прямоугольника 1000..4000 по x — ровно 2500.
        self.assertAlmostEqual(moment / area, 2500.0, places=6)

    def test_holes_are_subtracted_exactly(self):
        region = C.validate_region(
            {"outer": {"shape": "rect", "origin": [0, 0],
                       "size_mm": [4000, 3000]},
             "holes": [{"shape": "rect", "origin": [1000, 1000],
                        "size_mm": [1000, 1000]}]},
            [], "T", "profile", [])
        m = C.region_measures(region)
        self.assertAlmostEqual(m["area_mm2"], 4000 * 3000 - 1000 * 1000,
                               places=6)
        # Периметр — ПОЛНАЯ длина границы: проём тоже даёт боковую поверхность.
        self.assertAlmostEqual(m["perimeter_mm"], 14000.0 + 4000.0, places=6)
        self.assertAlmostEqual(m["min_area_mm2"], 1000.0 * 1000.0, places=6)


# ── 2. СВИДЕТЕЛЬ ЧИТАЕТ ГЕОМЕТРИЮ, А НЕ КОНСТАНТУ ───────────────────────────

_EXPECTED_VOLUME = r"__vmm_\w+ - ([\d.e+-]+)\)"
_EXPECTED_CAP = r"__rcap_\w+ - ([\d.e+-]+)\)"
_VOL_TOL_FACTOR = r"__tvol_\w+ = ([\d.e+-]+) \* __dt_"
_CAP_TOL_FACTOR = r"__tcap_\w+ = ([\d.e+-]+) \* __dt_"
_VOL_VACUITY = r"if \(__tvol_\w+ >= ([\d.e+-]+)\)"
_CAP_VACUITY = r"if \(__tcap_\w+ >= ([\d.e+-]+)\)"


class TheWitnessReadsTheGeometry(unittest.TestCase):
    """Возмущающий оракул: тронь вход — эталон в C# ОБЯЗАН поехать.

    Это тот же приём, которым `test_tolerance_provenance` ловит декоративный
    `tol_key`. Свидетель, сравнивающий с числом, не зависящим от геометрии,
    прошёл бы любой обычный тест и не доказывал бы ничего.
    """

    def test_extrusion_volume_is_area_times_height(self):
        _d, _c, post, _r = _emit(_extrusion())
        self.assertAlmostEqual(_num_after(post, _EXPECTED_VOLUME),
                               4000.0 * 3000.0 * 2500.0, places=3)

    def test_changing_the_height_moves_the_expected_volume(self):
        _d, _c, a, _r = _emit(_extrusion())
        _d, _c, b, _r = _emit(_extrusion(height_mm=2501))
        self.assertNotEqual(_num_after(a, _EXPECTED_VOLUME),
                            _num_after(b, _EXPECTED_VOLUME))

    def test_adding_a_hole_moves_both_expected_volume_and_cap_area(self):
        holed = _extrusion(profile={
            "outer": {"shape": "rect", "origin": [0, 0], "size_mm": [4000, 3000]},
            "holes": [{"shape": "rect", "origin": [1000, 1000],
                       "size_mm": [1000, 1000]}]})
        _d, _c, plain, _r = _emit(_extrusion())
        _d, _c, with_hole, _r = _emit(holed)
        self.assertAlmostEqual(
            _num_after(with_hole, _EXPECTED_VOLUME),
            (4000.0 * 3000.0 - 1000.0 * 1000.0) * 2500.0, places=3)
        self.assertLess(_num_after(with_hole, _EXPECTED_VOLUME),
                        _num_after(plain, _EXPECTED_VOLUME))
        self.assertLess(_num_after(with_hole, _EXPECTED_CAP),
                        _num_after(plain, _EXPECTED_CAP))

    def test_an_arc_moves_the_expected_volume_off_the_polygon_answer(self):
        """Дуга обязана считаться дугой, а не хордой: иначе замкнутая форма
        была бы декоративной, а свидетель сверял бы многоугольник."""
        straight = _extrusion(profile={"outer": {
            "shape": "poly",
            "points_mm": [[0, 0], [4000, 0], [4000, 3000], [0, 3000]]}})
        curved = _extrusion(profile={"outer": {
            "shape": "poly",
            "points_mm": [[0, 0], [4000, 0], [4000, 3000], [0, 3000]],
            "arcs": [{"edge": 1, "bulge": 0.5}]}})
        _d, _c, sp, _r = _emit(straight)
        _d, _c, cp, _r = _emit(curved)
        self.assertGreater(_num_after(cp, _EXPECTED_VOLUME),
                           _num_after(sp, _EXPECTED_VOLUME) * 1.05)

    def test_revolve_volume_is_sweep_times_first_moment(self):
        """Кольцо радиусов 1000..1800 высотой 2400, полный оборот.

        Независимая проверка школьной формулой: V = π(R²−r²)h.
        """
        _d, _c, post, _r = _emit(_revolve())
        got = _num_after(post, _EXPECTED_VOLUME)
        want = math.pi * (1800.0 ** 2 - 1000.0 ** 2) * 2400.0
        self.assertAlmostEqual(got / want, 1.0, places=9)

    def test_half_turn_is_half_the_volume(self):
        _d, _c, full, _r = _emit(_revolve())
        _d, _c, half, _r = _emit(_revolve(sweep_deg=180))
        self.assertAlmostEqual(_num_after(half, _EXPECTED_VOLUME) * 2.0,
                               _num_after(full, _EXPECTED_VOLUME), places=3)

    def test_moving_the_axis_further_out_grows_the_volume(self):
        """Тот же профиль дальше от оси заметает больший объём — свидетель
        обязан это видеть, иначе он сверял бы площадь, а не тело."""
        near = _emit(_revolve())[2]
        far = _emit(_revolve(profile={
            "outer": {"shape": "rect", "origin": [5000, 0],
                      "size_mm": [800, 2400]}}))[2]
        self.assertGreater(_num_after(far, _EXPECTED_VOLUME),
                           _num_after(near, _EXPECTED_VOLUME) * 3.0)

    def test_full_turn_expects_no_caps_and_a_sector_expects_two(self):
        full = _emit(_revolve())[2]
        sector = _emit(_revolve(sweep_deg=90))[2]
        self.assertEqual(_num_after(full, _EXPECTED_CAP), 0.0)
        self.assertAlmostEqual(_num_after(sector, _EXPECTED_CAP),
                               2.0 * 800.0 * 2400.0, places=3)


# ── 3. МУТАЦИОННОЕ ДОКАЗАТЕЛЬСТВО: СВИДЕТЕЛЬ МОЖЕТ ПРОВАЛИТЬСЯ ──────────────

class TheWitnessCanFail(unittest.TestCase):
    """Проверка, которая не может провалиться, хуже отсутствующей.

    ДОКАЗАТЕЛЬСТВО, А НЕ СИМУЛЯЦИЯ. Допуск считается в рантайме из
    `VertexTolerance`, которого офлайн нет, поэтому подставлять сюда
    правдоподобное δ значило бы придумать число. Вместо этого используется
    то, что эмиссия ГАРАНТИРУЕТ сама: рядом со свидетелем стоит рантайм-отказ
    `if (допуск >= самая мелкая объявленная часть)`. Значит на всяком прогоне,
    доживающем до свидетеля, допуск СТРОГО МЕНЬШЕ этой величины — и любая
    подмена размером с неё гарантированно ловится, каким бы ни было δ.
    """

    def _numbers(self, op):
        _d, create, post, _r = _emit(op)
        return {
            "expected_volume": _num_after(post, _EXPECTED_VOLUME),
            "expected_cap": _num_after(post, _EXPECTED_CAP),
            "vol_tol_factor": _num_after(create, _VOL_TOL_FACTOR),
            "cap_tol_factor": _num_after(create, _CAP_TOL_FACTOR),
            "vol_vacuity": _num_after(create, _VOL_VACUITY),
            "cap_vacuity": _num_after(create, _CAP_VACUITY),
        }

    def test_the_vacuity_refusal_is_emitted_for_both_witnesses(self):
        for op in (_extrusion(), _revolve()):
            with self.subTest(op=op["op"]):
                _d, create, _p, _r = _emit(op)
                self.assertIn("__tvol_", create)
                self.assertRegex(create, _VOL_VACUITY)
                self.assertRegex(create, _CAP_VACUITY)
                self.assertIn("проверка не смогла бы провалиться", create)

    def test_an_ignored_hole_exceeds_every_admissible_tolerance(self):
        """Самая тихая из вероятных поломок: Revit проигнорировал внутреннее
        кольцо и залил проём. Объём тогда больше на объём проёма, и этот
        объём — ровно порог вакуумности, ниже которого допуск не бывает."""
        op = _extrusion(profile={
            "outer": {"shape": "rect", "origin": [0, 0], "size_mm": [4000, 3000]},
            "holes": [{"shape": "rect", "origin": [1000, 1000],
                       "size_mm": [1000, 1000]}]})
        n = self._numbers(op)
        hole_volume = 1000.0 * 1000.0 * 2500.0
        # Порог вакуумности — объём самой мелкой объявленной части, и он равен
        # объёму проёма (проём мельче остатка профиля).
        self.assertAlmostEqual(n["vol_vacuity"], hole_volume, places=3)
        # На всяком прогоне, доживающем до свидетеля, допуск < этого порога,
        # значит расхождение размером с проём СТРОГО больше допуска.
        self.assertGreaterEqual(hole_volume, n["vol_vacuity"])
        # И то же самое для торцов: залитый проём добавляет 2·площадь проёма.
        self.assertAlmostEqual(n["cap_vacuity"], 2.0 * 1000.0 * 1000.0,
                               places=3)

    def test_a_one_percent_error_is_caught_for_every_admissible_delta(self):
        """Высота промахнулась на один процент — ловится ли это ВСЕГДА?

        Профиль без проёмов запретом вакуумности защищён слабо (самая мелкая
        объявленная часть там — само тело), поэтому здесь работает ВТОРАЯ,
        независимая граница, и она тоже выведена, а не назначена.

        Свидетель срабатывает при |Δ| > surface·δ, значит ошибка Δ ловится
        при δ < Δ/surface. С другой стороны δ ограничен СВЕРХУ нашими же
        законами: `contour._EDGE_TOL` = 1 мм — минимальная длина ребра,
        которую CONTOUR вообще выпускает наружу, а `VertexTolerance` по
        определению есть расстояние, на котором две точки СОВПАДАЮТ. Будь он
        не меньше миллиметра, законное ребро CONTOUR было бы для Revit
        вырожденным, и профиль не построился бы вовсе. Значит на всяком
        документе, где наши профили СТРОЯТСЯ, δ < 1 мм + квант эмиссии.

        Тест сравнивает две величины: порог по δ, при котором однопроцентная
        ошибка ещё ловится, обязан быть ЗАМЕТНО выше этой границы.
        """
        max_delta = C._EDGE_TOL + C.EMIT_COORD_QUANTUM_MM
        for op in (_extrusion(), _revolve()):
            with self.subTest(op=op["op"]):
                n = self._numbers(op)
                caught_while_delta_below = (
                    0.01 * n["expected_volume"] / n["vol_tol_factor"])
                self.assertGreater(
                    caught_while_delta_below, max_delta,
                    f"допуск съедает процент объёма уже при δ="
                    f"{caught_while_delta_below:.3f} мм, а δ может доходить "
                    f"до {max_delta} мм — свидетель слеп к процентной ошибке")

    def test_a_sector_built_instead_of_a_full_turn_is_caught_by_the_caps(self):
        """Самая вероятная поломка полного оборота: Revit собрал клин.
        Ожидаемая площадь торцов тогда 0, а измеренная — 2·A."""
        n = self._numbers(_revolve())
        self.assertEqual(n["expected_cap"], 0.0)
        wedge_caps = 2.0 * 800.0 * 2400.0
        self.assertAlmostEqual(n["cap_vacuity"], wedge_caps, places=3)
        self.assertGreaterEqual(wedge_caps, n["cap_vacuity"])

    def test_deleting_a_witness_makes_the_certificate_refuse(self):
        """Прямая мутация эмиссии: вырежи вердикт — сертификат обязан упасть.

        Это сильная форма (та же, что закон L6 в test_tolerance_provenance):
        аудит по словам такую правку не заметил бы.
        """
        from kukai.ir import translation_cert as cert
        from kukai.ir.emit_model import WitnessCheck

        for raw in (_extrusion(), _revolve()):
            grounded = _ground(raw)
            name = raw["op"]
            real = _EMITTERS[name]
            for ver in ("2021", "2026"):
                self.assertTrue(cert.certify_op(grounded, ver).proven,
                                f"{name}/{ver} не заверяется даже целым")
                _d, _c, checks, _r = real(grounded, ver, "kir:test")
                for victim in checks:
                    key = victim.obligation_key

                    def excised(o, v, stamp, isolation="atomic",
                                _r=real, _k=key):
                        d, c, post, rb = _r(o, v, stamp, isolation)
                        kept = [x for x in post if x.obligation_key != _k]
                        if not kept:
                            kept = [WitnessCheck(
                                obligation_key="__excised__", reader_cs="",
                                verdict_cs='    if (false) __post.Add("");\n',
                                message="excised", style="guard")]
                        return d, c, kept, rb

                    with self.subTest(op=name, ver=ver, witness=key):
                        _EMITTERS[name] = excised
                        try:
                            still = cert.certify_op(grounded, ver).proven
                        finally:
                            _EMITTERS[name] = real
                        self.assertFalse(
                            still,
                            f"вырезан свидетель {key}, а сертификат всё ещё "
                            f"proven — обязательство декоративно")


# ── 4. ЗАПРЕТЫ, ОТКАЗЫ И ОТСУТСТВИЕ ─────────────────────────────────────────

class RefusalsAndAbsence(unittest.TestCase):

    def test_a_profile_crossing_the_axis_is_refused_by_name(self):
        out = compile_program(
            _prog(_revolve(profile={
                "outer": {"shape": "rect", "origin": [-500, 0],
                          "size_mm": [800, 2400]}})),
            revit_version="2023", snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertTrue(any("за ось" in (d.message_ru or "")
                            for d in out.diagnostics), out.diagnostics)

    def test_impersonation_categories_name_the_honest_op(self):
        from kukai.ir.ops_shape import IMPERSONATION_ROUTES

        for barred, honest in sorted(IMPERSONATION_ROUTES.items()):
            for op in (_extrusion(category=barred), _revolve(category=barred)):
                with self.subTest(category=barred, op=op["op"]):
                    out = compile_program(_prog(op), revit_version="2023",
                                          snapshot=GROUND_SNAPSHOT)
                    self.assertFalse(out.ok)
                    self.assertTrue(
                        any(honest in (d.message_ru or "")
                            for d in out.diagnostics),
                        f"отказ не назвал {honest}: "
                        f"{[d.message_ru for d in out.diagnostics]}")

    def test_the_registry_bars_the_same_categories_as_the_mesh(self):
        """ОДНА таблица, а не копия: снять запрет в одном файле и не заметить
        во втором — ровно тот класс, ради которого таблица импортируется."""
        from kukai.ir.ops_shape import DIRECTSHAPE_CATEGORIES

        for name in ("create_solid_extrusion", "create_solid_revolve"):
            with self.subTest(op=name):
                choices = {p.name: p.choices
                           for p in spec.OPS[name].params}["category"]
                self.assertEqual(set(choices), set(DIRECTSHAPE_CATEGORIES))

    def test_absent_base_z_emits_no_transform_at_all(self):
        """Отсутствие остаётся отсутствием: без `base_z_mm` в эмиссии нет ни
        одного преобразования контура, а не преобразование на ноль."""
        _d, without, _p, _r = _emit(_extrusion())
        _d, with_z, _p, _r = _emit(_extrusion(base_z_mm=3300))
        self.assertNotIn("CreateViaTransform", without)
        self.assertIn("CreateViaTransform", with_z)
        self.assertIn("U(3300.0)", with_z)

    def test_base_z_moves_the_expected_bbox_in_z_only(self):
        _d, _c, flat, _r = _emit(_extrusion())
        _d, _c, lifted, _r = _emit(_extrusion(base_z_mm=3300))
        self.assertIn("Min.Z) - 0.0", flat)
        self.assertIn("Max.Z) - 2500.0", flat)
        self.assertIn("Min.Z) - 3300.0", lifted)
        self.assertIn("Max.Z) - 5800.0", lifted)

    def test_a_grid_anchored_profile_resolves_and_demands_a_snapshot(self):
        """ПОЧИНКА ОСТАТКА, НАЙДЕННАЯ ЭТОЙ ВОЛНОЙ. `ground._needs_pool` держал
        зашитое ИМЯ параметра (`contour`) там, где соседняя строка уже
        переехала на РОД. Профиль тела зовётся `profile`, и до починки адрес
        от осей внутри него не требовал снапшота: пул `grids` приходил пустым,
        а отказ называл «оси не найдены» вместо «снапшота нет» — ремонт не
        туда. Оба конца проверяются здесь: с осями строится, без снапшота —
        отказ ПРО СНАПШОТ."""
        op = _extrusion(profile={"outer": {
            "shape": "poly",
            "points_mm": [{"at_grid": ["1", "А"]}, {"at_grid": ["2", "А"]},
                          {"at_grid": ["2", "Б"]}, {"at_grid": ["1", "Б"]}]}})
        out = compile_program(_prog(op), revit_version="2023",
                              snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, out.diagnostics)
        # Оси 1/2 (x=0/4000) и А/Б (y=0/4500) дают прямоугольник 4000×4500,
        # то есть площадь 18 000 000 мм² и объём 45 000 000 000 мм³ — числа,
        # которые могли появиться ТОЛЬКО если пул осей действительно прочитан.
        self.assertIn("__rb[\"profile_area_mm2\"] = 18000000.0;", out.csharp)
        self.assertIn("__vmm_SX - 45000000000.0", out.csharp)

        blind = compile_program(_prog(op), revit_version="2023")
        self.assertFalse(blind.ok)
        self.assertTrue(any("снапшот" in (d.message_ru or "")
                            for d in blind.diagnostics), blind.diagnostics)

    def test_neither_op_grounds_anything_and_neither_carries_a_registry_tolerance(self):
        """Оба факта содержательны, а не пусты: у DirectShape нет типа (нечего
        грунтовать), а допуск здесь — функция геометрии опа и собственного
        числа Revit, а не константа реестра."""
        for name in ("create_solid_extrusion", "create_solid_revolve"):
            with self.subTest(op=name):
                self.assertEqual(spec.OPS[name].grounded, ())
                self.assertEqual(spec.OPS[name].tolerances, {})
                self.assertEqual(spec.OPS[name].capability,
                                 (("create", "geometry"),))

    def test_the_receipt_carries_the_raw_pair_the_live_run_must_measure(self):
        for op in (_extrusion(), _revolve()):
            with self.subTest(op=op["op"]):
                _d, _c, _p, readback = _emit(op)
                for field in ("volume_mm3_expected", "volume_mm3_measured",
                              "volume_tolerance_mm3", "cap_area_mm2_expected",
                              "cap_area_mm2_measured", "vertex_tolerance_mm",
                              "bim_semantics", "has_type",
                              "schedulable_as_building_element"):
                    self.assertIn(field, readback)

    def test_the_sector_bbox_is_the_swept_annulus_not_the_profile(self):
        """Габарит кольца — квадрат 2R, а не полоса профиля: тело заметает
        плоскость целиком. Свидетель, взявший габарит профиля, подписал бы
        геометрию, которой нет."""
        _d, _c, post, _r = _emit(_revolve())
        self.assertIn("Min.X) - -1800.0", post)
        self.assertIn("Max.X) - 1800.0", post)
        self.assertIn("Min.Y) - -1800.0", post)
        self.assertIn("Max.Y) - 1800.0", post)

    def test_a_quarter_turn_bbox_keeps_the_inner_radius(self):
        """Четверть оборота: по x от внутреннего радиуса до внешнего, по y —
        так же. Кардинальные направления внутрь сектора не попадают."""
        _d, _c, post, _r = _emit(_revolve(sweep_deg=90))
        self.assertIn("Min.X) - 0.0", post)
        self.assertIn("Max.X) - 1800.0", post)
        self.assertIn("Min.Y) - 0.0", post)
        self.assertIn("Max.Y) - 1800.0", post)


# ── 5. ШЕСТЬ ВЕРСИЙ ─────────────────────────────────────────────────────────

class SixVersionsEmitTheSameSurface(unittest.TestCase):
    """Оси версий у этих опов НЕТ — вся GeometryCreationUtilities побайтово
    одинакова на 2021-2026 (замер компиляцией, таблица в шапке ops_solid.py).
    Здесь это ЗАКРЕПЛЯЕТСЯ: расхождение эмиссии между версиями означало бы,
    что кто-то завёл ветку и не сказал."""

    def test_emission_is_identical_across_all_six(self):
        for op in (_extrusion(), _revolve(), _extrusion(base_z_mm=1000)):
            emissions = {ver: _emit(op, ver) for ver in VERSIONS}
            first = emissions["2021"]
            for ver in VERSIONS[1:]:
                with self.subTest(op=op["op"], ver=ver):
                    self.assertEqual(emissions[ver], first)

    def test_the_program_compiles_on_every_version(self):
        """Тут проверяется только то, что КОМПИЛЯТОР не отказывает; что C#
        собирается Roslyn'ом на шести версиях — ворота, а не этот набор."""
        for op in (_extrusion(), _revolve()):
            for ver in VERSIONS:
                with self.subTest(op=op["op"], ver=ver):
                    out = compile_program(_prog(op), revit_version=ver,
                                          snapshot=GROUND_SNAPSHOT)
                    self.assertTrue(out.ok, out.diagnostics)


if __name__ == "__main__":
    unittest.main()
