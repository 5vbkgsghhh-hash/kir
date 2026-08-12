"""Отрицательные контроли L2-приёмки — и доказательство их падучести.

ПОРЯДОК ЭТОГО ФАЙЛА ОБРАТЕН ПРИВЫЧНОМУ И ЭТО ГЛАВНОЕ В НЁМ. Дизайн лида
(docs/2026-07-29-independent-acceptance-design.md, п.3 порядка постройки)
говорит прямо: заведомо неверная постройка обязана валить каждый предикат, и
это ПЕРВОЕ, что надо написать, иначе о слепом чекере мы узнаем тогда же, когда
узнали про «выглядит правильно». Поэтому неверные постройки стоят первыми,
верная — рядом с ними (чекер, который валит всё, так же бесполезен, как
пропускающий всё), а дальше идёт то, чего обычно не пишут вовсе: МУТАЦИИ,
которые доказывают, что каждый контроль падает НЕ САМ ПО СЕБЕ, а от конкретного
правила. Тест, который не может провалиться, — не тест; тест, который не может
ПЕРЕСТАТЬ проваливаться при поломке правила, не доказывает, что правило есть.
"""
from __future__ import annotations

import json
import re
import unittest
from unittest import mock

from kukai.ir import acceptance, spec
from kukai.ir.acceptance import (
    Certainty,
    MismatchCode,
    census_delta,
    check_acceptance,
    derive_expectation,
    expectation_digest,
    scope_census_from_elements,
)

L3 = "Этаж 3"
L4 = "Этаж 4"


def _walls_and_doors_program() -> dict:
    """12 стен на «Этаж 3» и 4 двери в них — образец из дизайна L2."""
    ops = [
        {"op": "create_wall", "id": f"w{i}",
         "p0_mm": [i * 1000.0, 0.0], "p1_mm": [i * 1000.0, 6000.0],
         "level": {"by": "name", "value": L3}, "height_mm": 3000.0}
        for i in range(12)
    ]
    ops += [
        {"op": "create_door", "id": f"d{i}",
         "host": {"by": "ref", "value": f"w{i}"}, "offset_mm": 1000.0}
        for i in range(4)
    ]
    return {"ir_version": "1.0", "ops": ops}


def _census(rows: dict[tuple[str, str], int]) -> dict[tuple[str, str], int]:
    return dict(rows)


BEFORE = _census({("OST_Walls", L3): 100, ("OST_Doors", L3): 5,
                  ("OST_Walls", L4): 40})


class TestProgramIsReal(unittest.TestCase):
    """Якорь: предикат выводится из программы, которую компилятор ПРИНИМАЕТ.

    Без этого теста все контроли ниже проверяли бы приёмку выдуманной формы:
    ожидание, выведенное из того, что компилятор откажется компилировать,
    ничего не значит.
    """

    def test_the_control_program_compiles_and_yields_the_same_scopes(self) -> None:
        from kukai.ir.compiler import compile_program
        from kukai.ir.tests.fixtures import GROUND_SNAPSHOT

        level = GROUND_SNAPSHOT["levels"][0]["name"]
        ops = [
            {"op": "create_wall", "id": f"w{i}",
             "p0_mm": [i * 1000.0, 0.0], "p1_mm": [i * 1000.0, 6000.0],
             "level": {"by": "name", "value": level}, "height_mm": 3000.0}
            for i in range(12)
        ] + [
            {"op": "create_door", "id": f"d{i}",
             "host": {"by": "ref", "value": f"w{i}"}, "offset_mm": 1000.0}
            for i in range(4)
        ]
        program = {"ir_version": "1.0", "ops": ops}
        out = compile_program(program, revit_version="2023",
                              snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])

        expectation = derive_expectation(program)
        rows = {r.categories: r for r in expectation.rows}
        self.assertEqual((rows[("OST_Walls",)].level,
                          rows[("OST_Walls",)].count), (level, 12))
        self.assertEqual((rows[("OST_Doors",)].level,
                          rows[("OST_Doors",)].count), (None, 4))


class TestNegativeControls(unittest.TestCase):
    """Заведомо неверные постройки. Каждая ОБЯЗАНА быть отклонена."""

    def setUp(self) -> None:
        self.expectation = derive_expectation(_walls_and_doors_program())
        # Предикат обязан быть непустым, иначе «отклонено» ничего не значит.
        self.assertTrue(self.expectation.checkable)

    def _verdict(self, after):
        return check_acceptance(self.expectation, BEFORE, after)

    def test_one_element_short_is_refused(self) -> None:
        """Построено на один элемент меньше, чем следует из программы."""
        after = _census({("OST_Walls", L3): 111, ("OST_Doors", L3): 9,
                         ("OST_Walls", L4): 40})
        verdict = self._verdict(after)
        self.assertFalse(verdict.accepted)
        self.assertIn(MismatchCode.CATEGORY_SHORTFALL,
                      {m.code for m in verdict.mismatches})
        wall = next(m for m in verdict.mismatches
                    if m.categories == ("OST_Walls",)
                    and m.code is MismatchCode.CATEGORY_SHORTFALL)
        self.assertEqual((wall.expected, wall.observed), (12, 11))

    def test_one_element_short_in_a_floating_category_is_refused(self) -> None:
        """Недостача там, где уровень НЕ выводится (дверь).

        Шестой контроль сверх пяти обязательных, и он не для полноты: у
        двери разрез по уровням пуст, поэтому недостачу ловит ровно одно
        правило. Контроль, который ловят два правила сразу, не доказывает,
        что работает хоть одно из них.
        """
        after = _census({("OST_Walls", L3): 112, ("OST_Doors", L3): 8,
                         ("OST_Walls", L4): 40})
        verdict = self._verdict(after)
        self.assertFalse(verdict.accepted)
        door = next(m for m in verdict.mismatches
                    if m.categories == ("OST_Doors",))
        self.assertEqual((door.code, door.expected, door.observed),
                         (MismatchCode.CATEGORY_SHORTFALL, 4, 3))

    def test_right_count_wrong_level_is_refused(self) -> None:
        """Суммарно сходится, по охвату — нет: «построил в другом месте».

        Ради этого класса L2 и существует: любой чекер, считающий только
        итог, здесь молча скажет «сошлось».
        """
        after = _census({("OST_Walls", L3): 100, ("OST_Doors", L3): 9,
                         ("OST_Walls", L4): 52})
        verdict = self._verdict(after)
        self.assertFalse(verdict.accepted)
        codes = {m.code for m in verdict.mismatches}
        self.assertIn(MismatchCode.LEVEL_SHORTFALL, codes)
        self.assertNotIn(MismatchCode.CATEGORY_SHORTFALL, codes,
                         "итог по категории сходится — обязан ловить именно "
                         "разрез по уровням")
        short = next(m for m in verdict.mismatches
                     if m.code is MismatchCode.LEVEL_SHORTFALL)
        self.assertEqual(short.level, L3)
        self.assertEqual((short.expected, short.observed), (12, 0))

    def test_built_twice_is_refused(self) -> None:
        """Построено вдвое — дубликаты."""
        after = _census({("OST_Walls", L3): 124, ("OST_Doors", L3): 13,
                         ("OST_Walls", L4): 40})
        verdict = self._verdict(after)
        self.assertFalse(verdict.accepted)
        self.assertIn(MismatchCode.CATEGORY_OVERSHOOT,
                      {m.code for m in verdict.mismatches})

    def test_right_count_wrong_category_is_refused(self) -> None:
        """Ровно столько, сколько надо, но в другой категории."""
        after = _census({("OST_Walls", L3): 100, ("OST_Doors", L3): 5,
                         ("OST_Walls", L4): 40, ("OST_Floors", L3): 12})
        verdict = self._verdict(after)
        self.assertFalse(verdict.accepted)
        self.assertIn(("OST_Walls",),
                      {m.categories for m in verdict.mismatches})
        # Категория-самозванец названа в справке, а не молча проигнорирована.
        self.assertIn(("OST_Floors", 12), verdict.unexpected)

    def test_empty_build_is_refused(self) -> None:
        """Пустая постройка при непустой программе."""
        verdict = self._verdict(BEFORE)
        self.assertFalse(verdict.accepted)
        self.assertEqual(
            {("OST_Walls",), ("OST_Doors",)},
            {m.categories for m in verdict.mismatches
             if m.code is MismatchCode.CATEGORY_SHORTFALL})


class TestPositiveControl(unittest.TestCase):
    """Верная постройка обязана ПРОЙТИ — иначе чекер валит всё подряд."""

    def test_correct_build_is_accepted(self) -> None:
        expectation = derive_expectation(_walls_and_doors_program())
        after = _census({("OST_Walls", L3): 112, ("OST_Doors", L3): 9,
                         ("OST_Walls", L4): 40})
        verdict = check_acceptance(expectation, BEFORE, after)
        self.assertTrue(verdict.accepted, verdict.summary_ru())
        self.assertFalse(verdict.vacuous)
        self.assertGreaterEqual(verdict.checked_groups, 2)
        self.assertTrue(verdict.upper_bounds_checked)

    def test_doors_may_land_on_any_level(self) -> None:
        """Двери «плавают», и честная постройка это переживает.

        ЗАМЕР, на котором стоит правило: уровень двери отличается от уровня
        стены-хозяина в 76 случаях из 15 569 (0.49%) по 31 сохранённому
        разбору — дверь в стене L42 со смещением 400 мм получает уровень
        «L42_+500». Ожидание «дверь на уровне хозяина» завалило бы эти
        постройки, а выдуманная точность хуже отсутствия проверки.
        """
        expectation = derive_expectation(_walls_and_doors_program())
        after = _census({("OST_Walls", L3): 112, ("OST_Doors", L3): 5,
                         ("OST_Doors", L4): 4, ("OST_Walls", L4): 40})
        verdict = check_acceptance(expectation, BEFORE, after)
        self.assertTrue(verdict.accepted, verdict.summary_ru())

    def test_derived_elements_do_not_break_a_correct_build(self) -> None:
        """Revit добавил своё (линии эскиза, панели витража) — это не отказ."""
        expectation = derive_expectation(_walls_and_doors_program())
        after = _census({("OST_Walls", L3): 112, ("OST_Doors", L3): 9,
                         ("OST_Walls", L4): 40,
                         ("OST_CurtainWallPanels", L3): 300,
                         ("OST_SketchLines", ""): 4096})
        verdict = check_acceptance(expectation, BEFORE, after)
        self.assertTrue(verdict.accepted, verdict.summary_ru())
        # Панели объявлены производными у create_wall — в справке их нет.
        self.assertNotIn("OST_CurtainWallPanels",
                         {c for c, _ in verdict.unexpected})
        # Линии эскиза create_wall не порождает — они попадают в справку,
        # но справка не отказ.
        self.assertIn(("OST_SketchLines", 4096), verdict.unexpected)


class TestControlsCanFail(unittest.TestCase):
    """МУТАЦИИ: доказательство, что каждый контроль держится правилом.

    Контроль, который падает по случайной причине, доказывает не больше, чем
    свидетель, подписавший ось, которую не читал. Здесь правило ломается
    адресно, и контроль ОБЯЗАН перестать падать — тогда он про это правило.
    """

    def setUp(self) -> None:
        self.expectation = derive_expectation(_walls_and_doors_program())
        self.builds = {
            "short": _census({("OST_Walls", L3): 111, ("OST_Doors", L3): 9,
                              ("OST_Walls", L4): 40}),
            "wrong_level": _census({("OST_Walls", L3): 100,
                                    ("OST_Doors", L3): 9,
                                    ("OST_Walls", L4): 52}),
            "doubled": _census({("OST_Walls", L3): 124, ("OST_Doors", L3): 13,
                                ("OST_Walls", L4): 40}),
            "wrong_category": _census({("OST_Walls", L3): 100,
                                       ("OST_Doors", L3): 5,
                                       ("OST_Walls", L4): 40,
                                       ("OST_Floors", L3): 12}),
            "empty": dict(BEFORE),
            # Дверь «плавает» (уровень не выводится), поэтому недостачу в
            # ней ловит ТОЛЬКО итоговое правило — разрезу по уровням тут не
            # за что зацепиться.
            "door_short": _census({("OST_Walls", L3): 112,
                                   ("OST_Doors", L3): 8,
                                   ("OST_Walls", L4): 40}),
        }

    def test_every_bad_build_fails_on_the_real_checker(self) -> None:
        for name, after in self.builds.items():
            with self.subTest(build=name):
                self.assertFalse(
                    check_acceptance(self.expectation, BEFORE, after).accepted)

    def test_blinded_checker_accepts_every_bad_build(self) -> None:
        """Ослепить оба правила — и КАЖДАЯ неверная постройка «сдаётся».

        Это и есть тот чекер, которым была вчерашняя самопроверка. Если
        какой-то контроль продолжит падать здесь, значит он падает по
        постороннему поводу и ничего не доказывает.
        """
        import dataclasses
        blinded = dataclasses.replace(self.expectation,
                                      upper_bounds_valid=False)
        with mock.patch.object(acceptance, "_check_total",
                               lambda *a, **k: []), \
                mock.patch.object(acceptance, "_check_levels",
                                  lambda *a, **k: []):
            for name, after in self.builds.items():
                with self.subTest(build=name):
                    self.assertTrue(
                        check_acceptance(blinded, BEFORE, after).accepted)

    def test_doubled_control_is_owned_by_the_upper_bound(self) -> None:
        """Снять верхнюю границу — и только «вдвое» перестаёт падать."""
        import dataclasses
        weakened = dataclasses.replace(self.expectation,
                                       upper_bounds_valid=False)
        self.assertTrue(
            check_acceptance(weakened, BEFORE, self.builds["doubled"]).accepted,
            "контроль «построено вдвое» держится ИМЕННО верхней границей")
        for name in ("short", "wrong_level", "wrong_category", "empty",
                     "door_short"):
            with self.subTest(build=name):
                self.assertFalse(
                    check_acceptance(weakened, BEFORE,
                                     self.builds[name]).accepted,
                    "нижние границы обязаны пережить снятие верхних")

    def test_wrong_level_control_is_owned_by_the_level_rule(self) -> None:
        """Убрать разрез по уровням — и только «не на том уровне» проходит."""
        with mock.patch.object(acceptance, "_check_levels", lambda *a, **k: []):
            self.assertTrue(
                check_acceptance(self.expectation, BEFORE,
                                 self.builds["wrong_level"]).accepted)
            for name in ("short", "doubled", "wrong_category", "empty",
                         "door_short"):
                with self.subTest(build=name):
                    self.assertFalse(
                        check_acceptance(self.expectation, BEFORE,
                                         self.builds[name]).accepted)

    def test_floating_shortfall_is_owned_by_the_total_rule(self) -> None:
        """Недостача в «плавающей» категории держится ИМЕННО итогом.

        У двери уровень не выводится, поэтому разрезу по уровням зацепиться
        не за что: убрать итог — и недостающая дверь проходит. Контроль,
        который ловится ДВУМЯ правилами сразу, не доказывает, что работает
        хоть одно.
        """
        after = self.builds["door_short"]
        with mock.patch.object(acceptance, "_check_levels", lambda *a, **k: []):
            self.assertFalse(
                check_acceptance(self.expectation, BEFORE, after).accepted)
        with mock.patch.object(acceptance, "_check_total", lambda *a, **k: []):
            self.assertTrue(
                check_acceptance(self.expectation, BEFORE, after).accepted)


class TestExpectationDerivation(unittest.TestCase):
    """Ожидание выводится из программы механически — ослабить его нечем."""

    def test_walls_are_scoped_by_level(self) -> None:
        expectation = derive_expectation(_walls_and_doors_program())
        walls = [r for r in expectation.rows if r.categories == ("OST_Walls",)]
        self.assertEqual(len(walls), 1)
        self.assertEqual((walls[0].level, walls[0].count, walls[0].certainty),
                         (L3, 12, Certainty.EXACT))

    def test_doors_are_floating_not_invented(self) -> None:
        expectation = derive_expectation(_walls_and_doors_program())
        doors = [r for r in expectation.rows if r.categories == ("OST_Doors",)]
        self.assertEqual(len(doors), 1)
        self.assertIsNone(doors[0].level,
                          "уровень двери не выводится из хозяина — замерено")
        self.assertEqual(doors[0].count, 4)

    def test_level_by_ref_resolves_to_the_declared_name(self) -> None:
        program = {"ir_version": "1.0", "ops": [
            {"op": "create_level", "id": "lv", "elev_mm": 6000.0,
             "name": "Этаж 3"},
            {"op": "create_wall", "id": "w", "p0_mm": [0.0, 0.0],
             "p1_mm": [5000.0, 0.0], "level": {"by": "ref", "value": "lv"}},
        ]}
        rows = {r.categories: r for r in derive_expectation(program).rows}
        self.assertEqual(rows[("OST_Walls",)].level, "Этаж 3")
        self.assertEqual(rows[("OST_Levels",)].count, 1)

    def test_level_by_element_id_stays_unknown_without_the_lookup(self) -> None:
        """id — не имя; без справочника модели подставить нечего."""
        program = {"ir_version": "1.0", "ops": [
            {"op": "create_wall", "id": "w", "p0_mm": [0.0, 0.0],
             "p1_mm": [5000.0, 0.0],
             "level": {"by": "element_id", "value": 1679}},
        ]}
        row = derive_expectation(program).rows[0]
        self.assertIsNone(row.level)

    def test_level_lookup_locates_a_pinned_level(self) -> None:
        """Справочник уровней возвращает L2 на путь пересборки.

        Материализатор пришпиливает уровень по ElementId, и без справочника
        на настоящем здании (11 программ, 2 720 опов) располагалось НОЛЬ
        строк из 2 450 — приёмка вырождалась в проверку итогов.
        """
        program = {"ir_version": "1.0", "ops": [
            {"op": "create_wall", "id": "w", "p0_mm": [0.0, 0.0],
             "p1_mm": [5000.0, 0.0],
             "level": {"by": "element_id", "value": 1679}},
        ]}
        expectation = derive_expectation(program,
                                         level_names_by_id={1679: L3})
        self.assertEqual(expectation.rows[0].level, L3)
        # И теперь «не на том уровне» ловится на пересборочной программе.
        verdict = check_acceptance(expectation, {}, {("OST_Walls", L4): 1})
        self.assertFalse(verdict.accepted)
        self.assertIn(MismatchCode.LEVEL_SHORTFALL,
                      {m.code for m in verdict.mismatches})

    def test_stack_macro_expands_into_per_storey_scopes(self) -> None:
        """Макрос — это тоже программа, и ожидание считается ПОСЛЕ раскрытия."""
        program = {"ir_version": "1.0", "ops": [{
            "op": "stack", "id": "s", "levels": 3, "h_mm": 3000,
            "name_prefix": "Этаж",
            "floor": [{"op": "create_wall", "id": "w", "p0_mm": [0.0, 0.0],
                       "p1_mm": [6000.0, 0.0], "height_mm": 3000.0}],
        }]}
        expectation = derive_expectation(program)
        walls = {r.level: r.count for r in expectation.rows
                 if r.categories == ("OST_Walls",)}
        self.assertEqual(walls, {"Этаж 1": 1, "Этаж 2": 1, "Этаж 3": 1})
        levels = [r for r in expectation.rows if r.categories == ("OST_Levels",)]
        self.assertEqual(levels[0].count, 3)

    def test_defaults_envelope_fills_the_level(self) -> None:
        program = {"ir_version": "1.0",
                   "defaults": {"level": {"by": "name", "value": L4}},
                   "ops": [{"op": "create_wall", "id": "w",
                            "p0_mm": [0.0, 0.0], "p1_mm": [6000.0, 0.0]}]}
        self.assertEqual(derive_expectation(program).rows[0].level, L4)

    def test_graph_op_counts_segments_and_leaves_fitting_count_unclaimed(self) -> None:
        """Один оп — много труб; ЧИСЛО фитингов не объявляется.

        Имя и докстрока правлены 10.08.2026. Было: «фитинги Revit делает сам»
        со ссылкой на «2 652 фитинга и 152 арматуры при НУЛЕ авторских». И то,
        и другое неверно: фитинги создаёт сам оп (`emit_fittings_cs` ->
        NewElbowFitting/NewTeeFitting/NewTransitionFitting в каждом узле
        степени >= 2), а числа — перепись snowdon_plumb_v3 (PF=2652, DF=152,
        PA=126), где «152» это фитинги воздуховодов, а не арматура, и арматуру
        не создаёт ни один эмиттер пакета.

        Проверяемое утверждение поэтому уже и честнее: оп называет число ТРУБ
        (= len(segments)) и НЕ называет числа фитингов — оно не выведено ни
        одним замером, потому что стык может свестись к Connector.ConnectTo без
        элемента, а семейство выбирают routing preferences. Объявить его числом
        значило бы валить каждую честную разводку.
        """
        program = {"ir_version": "1.0", "ops": [{
            "op": "route_pipe_system", "id": "r",
            "level": {"by": "name", "value": L3},
            "nodes": [{"id": "a", "xyz_mm": [0.0, 0.0, 0.0]},
                      {"id": "b", "xyz_mm": [3000.0, 0.0, 0.0]},
                      {"id": "c", "xyz_mm": [3000.0, 3000.0, 0.0]}],
            "segments": [{"from": "a", "to": "b"}, {"from": "b", "to": "c"}],
        }]}
        expectation = derive_expectation(program)
        pipes = [r for r in expectation.rows
                 if r.categories == ("OST_PipeCurves",)]
        self.assertEqual((pipes[0].count, pipes[0].certainty, pipes[0].level),
                         (2, Certainty.EXACT, L3))
        self.assertIn("OST_PipeFitting", expectation.derived_categories)
        self.assertIn("OST_PipeAccessory", expectation.derived_categories)

    def test_hosted_railing_is_at_least_one(self) -> None:
        """Railing.Create(host) отдаёт КОЛЛЕКЦИЮ — «ровно 1» было бы выдумкой."""
        program = {"ir_version": "1.0", "ops": [{
            "op": "create_railing", "id": "r", "variety": "hosted",
            "host": {"by": "element_id", "value": 4242},
            "position": "treads",
        }]}
        row = derive_expectation(program).rows[0]
        self.assertEqual(row.certainty, Certainty.AT_LEAST)
        self.assertEqual(row.count, 1)
        self.assertEqual(row.categories, ("OST_Railings", "OST_StairsRailing"))

    def test_at_least_row_survives_extra_elements(self) -> None:
        """«Не менее» обязано пропускать больше и отказывать при меньшем."""
        program = {"ir_version": "1.0", "ops": [{
            "op": "create_railing", "id": "r", "variety": "hosted",
            "host": {"by": "element_id", "value": 4242},
            "position": "treads",
        }]}
        expectation = derive_expectation(program)
        before = {("OST_StairsRailing", L3): 10}
        self.assertTrue(check_acceptance(
            expectation, before, {("OST_StairsRailing", L3): 12}).accepted)
        self.assertFalse(check_acceptance(
            expectation, before, {("OST_StairsRailing", L3): 10}).accepted)

    def test_beam_and_stairs_levels_are_not_claimed(self) -> None:
        """Оба «плавают», и оба — по замеру, а не по осторожности.

        Балка: Revit выводит опорный уровень из отметки кривой, а не из
        аргумента (записано в самом post опа, замер 27.07).
        Лестница: 0 строк из 351 в 31 разборе несут level_name.
        """
        program = {"ir_version": "1.0", "ops": [
            {"op": "create_beam", "id": "b", "p0_mm": [0.0, 0.0, 3000.0],
             "p1_mm": [6000.0, 0.0, 3000.0],
             "level": {"by": "name", "value": L3}},
            {"op": "create_stairs", "id": "s", "p0_mm": [0.0, 0.0],
             "p1_mm": [3000.0, 0.0],
             "base_level": {"by": "name", "value": L3},
             "top_level": {"by": "name", "value": L4}},
        ]}
        for row in derive_expectation(program).rows:
            with self.subTest(categories=row.categories):
                self.assertIsNone(row.level)

    def test_group_multiplies_members_by_occurrences(self) -> None:
        """Занятие 0 — сами члены; каждое placement добавляет ещё одно."""
        member = {"op": "create_wall", "id": "m", "p0_mm": [0.0, 0.0],
                  "p1_mm": [6000.0, 0.0],
                  "level": {"by": "name", "value": L3}}
        program = {"ir_version": "1.0", "ops": [{
            "op": "create_group", "id": "g", "members": [member],
            "placements": [[6000.0, 0.0, 0.0], [12000.0, 0.0, 0.0]],
        }]}
        expectation = derive_expectation(program)
        walls = [r for r in expectation.rows if r.categories == ("OST_Walls",)]
        self.assertEqual((walls[0].count, walls[0].level), (3, L3))
        self.assertIn("OST_IOSModelGroups", expectation.derived_categories)

    def test_overlapping_category_groups_lose_their_upper_bound(self) -> None:
        """Перекрытие и фундаментная плита делят OST_Floors — верх снят.

        Иначе честная постройка (3 пола + плита, легшая в OST_Floors) читалась
        бы как «прибавилось 4 вместо 3», то есть проверка врала бы на верном
        результате — самый быстрый способ добиться, чтобы её отключили.
        """
        program = {"ir_version": "1.0", "ops": [
            {"op": "create_floor", "id": f"f{i}",
             "outline": [[0.0, 0.0], [6000.0, 0.0], [6000.0, 6000.0]],
             "level": {"by": "name", "value": L3}} for i in range(3)
        ] + [
            {"op": "create_foundation", "id": "fd", "variety": "slab",
             "outline": [[0.0, 0.0], [3000.0, 0.0], [3000.0, 3000.0]],
             "level": {"by": "name", "value": L3}},
        ]}
        expectation = derive_expectation(program)
        self.assertTrue(expectation.upper_bounds_valid)
        verdict = check_acceptance(expectation, {}, {("OST_Floors", L3): 4})
        self.assertTrue(verdict.accepted, verdict.summary_ru())
        # А недостача по-прежнему ловится.
        self.assertFalse(
            check_acceptance(expectation, {}, {("OST_Floors", L3): 2}).accepted)

    def test_a_derived_category_never_gets_an_upper_bound(self) -> None:
        """Лестница сама делает ограждения — «ровно 1 ограждение» соврало бы.

        Программа СОЛЬНАЯ, и это не косметика. До 04.08 здесь стояли лестница
        И ограждение вместе — программа, которую `emit_program` отказывался
        собирать всегда (KIR-L002: `StairsEditScope` владеет собственными
        транзакциями). План её тогда принимал, поэтому тест проходил, проверяя
        поведение на входе, который до Revit не доехал бы никогда. Правило
        переехало на план, и вход пришлось привести к законному — утверждение
        теста от этого не изменилось: ограждение выводится ИЗ ЛЕСТНИЦЫ, своего
        `create_railing` для этого не нужно.
        """
        program = {"ir_version": "1.0", "ops": [
            {"op": "create_stairs", "id": "s", "p0_mm": [0.0, 0.0],
             "p1_mm": [3000.0, 0.0],
             "base_level": {"by": "name", "value": L3},
             "top_level": {"by": "name", "value": L4}},
        ]}
        expectation = derive_expectation(program)
        self.assertIn("OST_StairsRailing", expectation.derived_categories)
        verdict = check_acceptance(
            expectation, {},
            {("OST_Stairs", ""): 1, ("OST_StairsRailing", L3): 5})
        self.assertTrue(verdict.accepted, verdict.summary_ru())

    def test_a_stairs_program_with_a_neighbour_fails_closed_by_name(self) -> None:
        """И обратная сторона: незаконная программа обязана не «дать пустую
        перепись», а НАЗВАТЬ причину. Приёмка держится fail-closed, и её отказ
        несёт код правила, а не общую фразу."""
        program = {"ir_version": "1.0", "ops": [
            {"op": "create_stairs", "id": "s", "p0_mm": [0.0, 0.0],
             "p1_mm": [3000.0, 0.0],
             "base_level": {"by": "name", "value": L3},
             "top_level": {"by": "name", "value": L4}},
            {"op": "create_railing", "id": "r", "variety": "path",
             "path": [[0.0, 0.0], [3000.0, 0.0]],
             "level": {"by": "name", "value": L3}},
        ]}
        expectation = derive_expectation(program)
        self.assertEqual(expectation.derived_categories, ())
        self.assertTrue(any("KIR-L002" in note for note in expectation.notes),
                        expectation.notes)

    def test_type_ops_add_no_elements(self) -> None:
        """Перепись §18.1 — WhereElementIsNotElementType(); типы в неё не идут."""
        program = {"ir_version": "1.0", "ops": [
            {"op": "load_family", "id": "lf", "path": "C:/f.rfa"},
            {"op": "create_type", "id": "ct",
             "source_type": {"by": "name", "value": "К1"},
             "new_name": "К2", "width_mm": 400.0},
        ]}
        expectation = derive_expectation(program)
        self.assertEqual(expectation.rows, ())
        self.assertEqual(expectation.blind_ops, ())
        self.assertFalse(expectation.checkable)

    def test_unknown_category_op_is_named_and_disables_upper_bounds(self) -> None:
        """Слепота обязана быть НАЗВАНА, а верхняя граница — честно снята."""
        program = {"ir_version": "1.0", "ops": [
            {"op": "create_wall", "id": "w", "p0_mm": [0.0, 0.0],
             "p1_mm": [6000.0, 0.0], "level": {"by": "name", "value": L3}},
            {"op": "place_family", "id": "p", "xyz": [0.0, 0.0, 0.0],
             "level": {"by": "name", "value": L3}},
        ]}
        expectation = derive_expectation(program)
        self.assertFalse(expectation.upper_bounds_valid)
        self.assertEqual([b.op_name for b in expectation.blind_ops],
                         ["place_family"])
        self.assertTrue(expectation.blind_ops[0].reason)
        verdict = check_acceptance(expectation, {}, {("OST_Walls", L3): 5})
        self.assertTrue(verdict.accepted, "верх открыт — 5 стен не отказ")
        self.assertFalse(verdict.upper_bounds_checked)
        self.assertEqual(verdict.blind_ops, expectation.blind_ops)

    def test_subtractive_blind_op_cannot_false_reject_a_mixed_create(self) -> None:
        """Net delta cannot prove creation while an old cell may be removed."""

        program = {"ir_version": "1.0", "allow_destructive": True, "ops": [
            {"op": "create_wall", "id": "w", "p0_mm": [0.0, 0.0],
             "p1_mm": [6000.0, 0.0],
             "level": {"by": "name", "value": L3}},
            {"op": "delete", "id": "d",
             "target": {"by": "element_id", "value": 101}},
        ]}
        expectation = derive_expectation(program)

        self.assertFalse(expectation.lower_bounds_valid)
        self.assertFalse(expectation.checkable)
        # One wall was created and one old wall was deleted: net zero is a
        # correct execution, not a category_shortfall.  L2 must abstain.
        verdict = check_acceptance(
            expectation,
            {("OST_Walls", L3): 10},
            {("OST_Walls", L3): 10},
        )
        self.assertTrue(verdict.vacuous)
        self.assertEqual(verdict.mismatches, ())
        self.assertFalse(verdict.upper_bounds_checked)


FURNITURE = "OST_Furniture"


def _symbol_pool(**overrides):
    """Одна строка пула family_symbols — форма ровно как у open_model."""
    row = {"id": 800, "name": "Стол 1200", "category": FURNITURE,
           "family_name": "Стол офисный", "type_name": "Стол 1200",
           "instances": 4}
    row.update(overrides)
    return [row]


def _place_program(symbol=None, *, count=1):
    ops = []
    for index in range(count):
        op = {"op": "place_family", "id": f"f{index}",
              "xyz": [1000.0 * index, 1000.0, 0.0],
              "level": {"by": "name", "value": L3}}
        if symbol is not None:
            op["symbol"] = symbol
        ops.append(op)
    return {"ir_version": "1.0", "ops": ops}


_BY_TYPE = {"by": "family_type", "category": FURNITURE,
            "family_name": "Стол офисный", "type_name": "Стол 1200"}


class TestPlaceFamilyScope(unittest.TestCase):
    """Самый нагруженный пишущий оп реестра обязан ДОХОДИТЬ до приёмки.

    7 000 построенных экземпляров против 6 обвинённых — и до 09.08 ни один из
    них не мог получить независимого «сошлось»: `place_family` был безусловно
    слепым, а слепой оп в программе делает вердикт INCONCLUSIVE при любой,
    сколь угодно верной постройке. Слепота была НЕ ТАМ, где её записали:
    категория действительно не читается из программы, но она лежит в снимке
    модели — той же строкой BuiltInCategory, которой ключует живая перепись.

    Порядок этого класса тот же, что у файла: сначала отказ от суждения (его
    легко потерять молча), потом ложный отказ верной постройки (он дороже
    всего), и только потом зелёный.
    """

    def test_the_control_program_compiles_against_the_same_snapshot(self) -> None:
        """Якорь: предикат выведен из программы, которую компилятор ПРИНИМАЕТ."""
        from kukai.ir.compiler import compile_program
        from kukai.ir.tests.fixtures import GROUND_SNAPSHOT

        program = _place_program(_BY_TYPE)
        program["ops"][0]["level"] = {
            "by": "name", "value": GROUND_SNAPSHOT["levels"][0]["name"]}
        out = compile_program(program, revit_version="2023",
                              snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])

        expectation = acceptance.derive_expectation(
            out.planned,
            family_symbols=acceptance.symbol_rows_from_snapshot(GROUND_SNAPSHOT))
        self.assertEqual(expectation.blind_ops, ())
        self.assertEqual(len(expectation.rows), 1)
        self.assertEqual(expectation.rows[0].categories, (FURNITURE,))
        self.assertTrue(expectation.checkable)

    # ── отказ от суждения: каждая ветка НАЗВАНА ──────────────────────────

    def _blind_reason(self, expectation) -> str:
        self.assertEqual(expectation.rows, ())
        self.assertEqual([b.op_name for b in expectation.blind_ops],
                         ["place_family"])
        self.assertFalse(expectation.checkable,
                         "неизмеренная ветка обязана остаться ok:false")
        return expectation.blind_ops[0].reason

    def test_without_a_snapshot_pool_it_abstains(self) -> None:
        """Пула нет — категорию брать неоткуда, и это НАЗВАНО."""
        reason = self._blind_reason(
            acceptance.derive_expectation(_place_program(_BY_TYPE)))
        self.assertIn("пул family_symbols", reason)

    def test_a_truncated_pool_abstains(self) -> None:
        """За срезом мог остаться символ другой категории (тот же довод F7)."""
        snapshot = {"family_symbols": _symbol_pool(),
                    "family_symbols__truncated": True}
        self.assertIsNone(acceptance.symbol_rows_from_snapshot(snapshot))
        reason = self._blind_reason(acceptance.derive_expectation(
            _place_program(_BY_TYPE),
            family_symbols=acceptance.symbol_rows_from_snapshot(snapshot)))
        self.assertIn("обрезан", reason)

    def test_candidates_of_different_categories_abstain(self) -> None:
        """Одно имя на два рода вещей — какая клетка вырастет, неизвестно."""
        pool = _symbol_pool() + [{
            "id": 801, "name": "Стол 1200", "category": "OST_Casework",
            "family_name": "Стол лабораторный", "type_name": "Стол 1200"}]
        reason = self._blind_reason(acceptance.derive_expectation(
            _place_program({"by": "name", "value": "Стол 1200"}),
            family_symbols=pool))
        self.assertIn("2 разных категорий", reason)

    def test_a_symbol_made_by_this_same_program_abstains(self) -> None:
        """create_type/load_family — тот самый partial_blind_scope контракта.

        Символа, который создаётся в этой же программе, в снимке ДО записи
        нет по построению, и выдумать его категорию нечем.
        """
        program = {"ir_version": "1.0", "ops": [
            {"op": "create_type", "id": "t",
             "source_type": {"by": "name", "value": "К 300x300"},
             "new_name": "К2", "width_mm": 400.0},
            {"op": "place_family", "id": "f", "xyz": [0.0, 0.0, 0.0],
             "level": {"by": "name", "value": L3},
             "symbol": {"by": "name", "value": "К2"}},
        ]}
        reason = self._blind_reason(acceptance.derive_expectation(
            program, family_symbols=_symbol_pool()))
        self.assertIn("нет в снимке ДО записи", reason)

    def test_a_category_the_census_cannot_isolate_abstains(self) -> None:
        """Числовой ключ снимка живая перепись НЕ ВЫДЕЛИТ — значит отказ.

        Снимок падает на `__categoryId.ToString()`, когда имени в
        BuiltInCategory нет; перепись же ключует ТОЛЬКО именем и такую строку
        отбросит. Утверждать про клетку, которой в переписи не будет, значит
        завернуть верную постройку.
        """
        reason = self._blind_reason(acceptance.derive_expectation(
            _place_program({"by": "element_id", "value": 800}),
            family_symbols=_symbol_pool(category="-2000151")))
        self.assertIn("BuiltInCategory", reason)

    def test_the_census_key_rule_is_what_refuses(self) -> None:
        """МУТАЦИЯ: сломай правило ключа — и отказ ПЕРЕСТАЁТ случаться.

        Иначе тест выше доказывал бы лишь то, что где-то что-то отказало.
        """
        with mock.patch.object(acceptance, "_CENSUS_CATEGORY_RE",
                               re.compile(r".*")):
            expectation = acceptance.derive_expectation(
                _place_program({"by": "element_id", "value": 800}),
                family_symbols=_symbol_pool(category="-2000151"))
        self.assertEqual(expectation.blind_ops, ())

    # ── ложный отказ верной постройки — дороже всего ─────────────────────

    def test_extra_nested_children_are_not_a_rejection(self) -> None:
        """Вложенные общие семейства Revit создаёт САМ (21 555 на башне).

        `EXACT` здесь завернул бы каждую честную постройку такого семейства,
        поэтому число объявлено «не менее».
        """
        expectation = acceptance.derive_expectation(
            _place_program(_BY_TYPE), family_symbols=_symbol_pool())
        self.assertEqual(expectation.rows[0].certainty, Certainty.AT_LEAST)
        verdict = check_acceptance(expectation, {(FURNITURE, ""): 0},
                                   {(FURNITURE, ""): 4})
        self.assertTrue(verdict.accepted, verdict.summary_ru())

    def test_the_level_is_never_asserted(self) -> None:
        """Уровень FamilyInstance не объявляется — замер по двери (76/15 569).

        Экземпляр лёг на СОСЕДНИЙ уровень: L2 обязан промолчать, а не
        завернуть постройку по неизмеренной оси.
        """
        expectation = acceptance.derive_expectation(
            _place_program(_BY_TYPE), family_symbols=_symbol_pool())
        self.assertIsNone(expectation.rows[0].level)
        verdict = check_acceptance(expectation, {}, {(FURNITURE, L4): 1})
        self.assertTrue(verdict.accepted, verdict.summary_ru())

    def test_upper_bounds_stay_off_for_the_whole_program(self) -> None:
        """Вложенный ребёнок вправе лечь в категорию СОСЕДНЕГО опа.

        Поэтому верх снимается целиком — ровно как было при слепоте, потери
        нет. Причина обязана быть видна в самом ожидании.
        """
        program = {"ir_version": "1.0", "ops": [
            {"op": "create_wall", "id": "w", "p0_mm": [0.0, 0.0],
             "p1_mm": [6000.0, 0.0], "level": {"by": "name", "value": L3}},
            {"op": "place_family", "id": "f", "xyz": [0.0, 0.0, 0.0],
             "level": {"by": "name", "value": L3}, "symbol": _BY_TYPE},
        ]}
        expectation = acceptance.derive_expectation(
            program, family_symbols=_symbol_pool())
        self.assertEqual(expectation.blind_ops, ())
        self.assertFalse(expectation.upper_bounds_valid)
        self.assertTrue(any("верхние границы" in note
                            for note in expectation.notes))
        # Одна стена по программе, ЧЕТЫРЕ в модели: перебор не судится.
        verdict = check_acceptance(expectation, {},
                                   {("OST_Walls", L3): 4, (FURNITURE, ""): 1})
        self.assertTrue(verdict.accepted, verdict.summary_ru())
        self.assertFalse(verdict.upper_bounds_checked)

    # ── и только теперь зелёное и красное ────────────────────────────────

    def test_a_placement_that_did_not_happen_is_refused(self) -> None:
        expectation = acceptance.derive_expectation(
            _place_program(_BY_TYPE), family_symbols=_symbol_pool())
        verdict = check_acceptance(expectation, {(FURNITURE, ""): 7},
                                   {(FURNITURE, ""): 7})
        self.assertFalse(verdict.accepted)
        self.assertEqual([m.code for m in verdict.mismatches],
                         [MismatchCode.CATEGORY_SHORTFALL])
        self.assertEqual((verdict.mismatches[0].expected,
                          verdict.mismatches[0].observed), (1, 0))

    def test_two_placements_short_by_one_are_refused(self) -> None:
        expectation = acceptance.derive_expectation(
            _place_program(_BY_TYPE, count=2), family_symbols=_symbol_pool())
        self.assertEqual(expectation.rows[0].count, 2)
        verdict = check_acceptance(expectation, {(FURNITURE, ""): 7},
                                   {(FURNITURE, ""): 8})
        self.assertFalse(verdict.accepted)

    def test_the_category_follows_the_SNAPSHOT_not_the_program(self) -> None:
        """Ключевое отличие от «объявленного ожидания»: это ДАННЫЕ О МОДЕЛИ.

        Тот же селектор по имени против пула с другой категорией даёт другую
        клетку — значит утверждение не переписано из программы, а прочитано
        у Revit.
        """
        selector = {"by": "name", "value": "Стол 1200"}
        first = acceptance.derive_expectation(_place_program(selector),
                                              family_symbols=_symbol_pool())
        second = acceptance.derive_expectation(
            _place_program(selector),
            family_symbols=_symbol_pool(category="OST_Casework"))
        self.assertEqual(first.rows[0].categories, (FURNITURE,))
        self.assertEqual(second.rows[0].categories, ("OST_Casework",))
        self.assertNotEqual(expectation_digest(first), expectation_digest(second))

    def test_group_placements_multiply_the_member(self) -> None:
        """Оп внутри группы считается по числу занятий, как и все остальные."""
        program = {"ir_version": "1.0", "ops": [{
            "op": "create_group", "id": "g",
            "members": [{"op": "place_family", "id": "f",
                         "xyz": [0.0, 0.0, 0.0],
                         "level": {"by": "name", "value": L3},
                         "symbol": _BY_TYPE}],
            "placements": [[5000.0, 0.0], [10000.0, 0.0]],
        }]}
        expectation = acceptance.derive_expectation(
            program, family_symbols=_symbol_pool())
        rows = [r for r in expectation.rows if r.categories == (FURNITURE,)]
        self.assertEqual([r.count for r in rows], [3])


class TestPurityAndStability(unittest.TestCase):
    """Ожидание сериализуемо и одинаково между процессами."""

    def test_expectation_is_json_serialisable_and_stable(self) -> None:
        program = _walls_and_doors_program()
        first = derive_expectation(program)
        # Порядок независимых опов не должен менять ожидание. Зависимости
        # остаются топологичными: дверь не может предшествовать своей стене.
        walls, doors = program["ops"][:12], program["ops"][12:]
        shuffled = {"ir_version": "1.0",
                    "ops": list(reversed(walls)) + list(reversed(doors))}
        second = derive_expectation(shuffled)
        self.assertEqual(expectation_digest(first), expectation_digest(second))
        payload = json.dumps(first.to_dict(), ensure_ascii=False,
                             sort_keys=True)
        self.assertEqual(json.loads(payload), first.to_dict())

    def test_digest_changes_when_the_program_changes(self) -> None:
        """Подпись обязана РАЗЛИЧАТЬ — иначе пред-регистрация ничего не даёт."""
        base = derive_expectation(_walls_and_doors_program())
        program = _walls_and_doors_program()
        program["ops"][0]["level"] = {"by": "name", "value": L4}
        self.assertNotEqual(expectation_digest(base),
                            expectation_digest(derive_expectation(program)))

    def test_derivation_does_not_mutate_the_program(self) -> None:
        program = _walls_and_doors_program()
        snapshot = json.dumps(program, ensure_ascii=False, sort_keys=True)
        derive_expectation(program)
        self.assertEqual(json.dumps(program, ensure_ascii=False,
                                    sort_keys=True), snapshot)

    def test_malformed_program_yields_an_empty_but_honest_expectation(self) -> None:
        """Нераскрывшиеся макросы — записанная причина, а не тихий успех."""
        broken = {"ir_version": "1.0", "ops": [
            {"op": "stack", "id": "s", "levels": 999, "floor": []}]}
        expectation = derive_expectation(broken)
        self.assertEqual(expectation.rows, ())
        self.assertTrue(expectation.notes)
        verdict = check_acceptance(expectation, {}, {})
        self.assertTrue(verdict.vacuous)
        self.assertIn("НИЧЕГО", verdict.summary_ru())


class TestRegistryCoverage(unittest.TestCase):
    """Структурные стражи: новый оп не может провалиться в тишину."""

    def test_every_writing_op_is_classified(self) -> None:
        """Оп реестра, о котором таблицы молчат, обязан ронять сборку.

        Иначе он молча станет «слепым», снимет верхние границы во ВСЕЙ
        программе и приёмка тихо ослабнет — ровно тот класс, которым 30.07
        стадия оформления отвечала полем не того имени.
        """
        from kukai.ir.acceptance import (
            _LEVEL_FROM_PARAM, _OPS_BLIND, _OPS_WITHOUT_ELEMENTS,
            _OP_CATEGORIES,
        )
        # «special» — опы, чья категория выводится ВЕТКОЙ в _category_of_op, а
        # не строкой таблицы (у них категория зависит от собственного поля).
        # create_opening здесь потому же, почему create_foundation: род проёма
        # решает `variety` — wall_rect даёт ровно OST_SWallRectOpening, а
        # host_face зависит от категории НОСИТЕЛЯ, которая из программы не
        # читается, и сверяется суммой по трём родам.
        # create_topography здесь по той же причине, что create_foundation:
        # разновидность рельефа выбирает КАТЕГОРИЮ (OST_Topography против
        # OST_Toposolid), и ветка в _category_of_op называет её точно —
        # сумма по двум ключам скрыла бы ровно ту подмену, которую операция
        # запрещает.
        # wave/solid (09.08): оба тела кладут результат в DirectShape той же
        # категории из той же закрытой таблицы, поэтому едут ТОЙ ЖЕ веткой,
        # что и меш, — не строкой таблицы. Множества СЛОЖЕНЫ, а не выбрано
        # одно: у каждой волны здесь свои опы и ни одна не знала о чужих.
        special = {"create_column", "create_directshape", "create_foundation",
                   "create_group", "create_opening", "create_topography",
                   "create_solid_extrusion", "create_solid_revolve"}
        classified = (set(_OP_CATEGORIES) | set(_OPS_BLIND)
                      | set(_OPS_WITHOUT_ELEMENTS) | special)
        writing = {name for name, op in spec.OPS.items() if op.writes_model}
        self.assertEqual(writing - classified, set(),
                         "оп реестра не разобран в acceptance.py")
        self.assertEqual(classified - writing, set(),
                         "в таблицах acceptance.py есть несуществующий оп")
        self.assertLessEqual(_LEVEL_FROM_PARAM, writing)

    def test_level_from_param_ops_actually_have_a_level_param(self) -> None:
        from kukai.ir.acceptance import _LEVEL_FROM_PARAM
        for name in sorted(_LEVEL_FROM_PARAM):
            with self.subTest(op=name):
                self.assertIn("level",
                              {p.name for p in spec.OPS[name].params})

    def test_every_non_census_write_enters_mutation_acceptance(self) -> None:
        from kukai.ir.acceptance import _OPS_WITHOUT_ELEMENTS
        from kukai.ir.acceptance_mutation import MUTATION_ACCEPTANCE_OPS

        self.assertEqual(
            set(_OPS_WITHOUT_ELEMENTS) | {"delete", "change_type"},
            set(MUTATION_ACCEPTANCE_OPS),
            "write op is invisible to census but missing from exact mutation "
            "acceptance (or vice versa)",
        )

    def test_categories_agree_with_the_lifter_table(self) -> None:
        """Прямой и обратный ход обязаны звать категорию одинаково.

        Таблица здесь ЯВНАЯ, а не выведенная из lift.LIFTER_TABLE (вопросы у
        них разные), но там, где обе говорят об одном опе, расхождение —
        дефект: одна из двух зовёт категорию не своим именем.
        """
        from kukai.ir.decompile.lift import LIFTER_TABLE
        from kukai.ir.acceptance import _OP_CATEGORIES

        by_op: dict[str, set[str]] = {}
        for category, (_kind, op_name) in LIFTER_TABLE.items():
            by_op.setdefault(op_name, set()).add(category)
        for op_name, declared in _OP_CATEGORIES.items():
            if op_name not in by_op:
                continue
            with self.subTest(op=op_name):
                self.assertTrue(
                    set(declared) & by_op[op_name],
                    f"{op_name}: приёмка ждёт {sorted(declared)}, лифтер "
                    f"поднимает из {sorted(by_op[op_name])}")

    def test_derived_categories_are_never_also_expected(self) -> None:
        """Категория не может быть одновременно авторской и производной."""
        from kukai.ir.acceptance import _OP_CATEGORIES, _OP_DERIVED
        for op_name, derived in _OP_DERIVED.items():
            with self.subTest(op=op_name):
                self.assertFalse(
                    set(derived) & set(_OP_CATEGORIES.get(op_name, ())))


class TestScopeCensusHelper(unittest.TestCase):
    """Перепись охвата: (категория, уровень) → сколько."""

    def test_counts_rows_and_keeps_levelless_elements(self) -> None:
        rows = [
            {"category": "OST_Walls", "level_name": " Этаж 3 "},
            {"category": "OST_Walls", "level_name": "Этаж 3"},
            {"category": "OST_Stairs", "level_name": None},
            {"category": "OST_Dimensions"},
        ]
        self.assertEqual(scope_census_from_elements(rows), {
            ("OST_Walls", L3): 2,
            ("OST_Stairs", ""): 1,
            ("OST_Dimensions", ""): 1,
        })

    def test_delta_treats_a_new_category_as_zero_before(self) -> None:
        delta = census_delta({("OST_Walls", L3): 5},
                             {("OST_Walls", L3): 5, ("OST_Doors", L3): 3})
        self.assertEqual(delta[("OST_Doors", L3)], 3)
        self.assertEqual(delta[("OST_Walls", L3)], 0)


if __name__ == "__main__":
    unittest.main()
