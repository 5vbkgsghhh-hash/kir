"""АЛИАС ФОРМЫ ПО ТИПУ — законы, которые нельзя нарушить.

Каждый тест держит одно решение из шапки `geom_alias`, и у каждого закона есть
КОНТРОЛЬ-FAIL: если бы правило исчезло, тест обязан покраснеть. Проверка,
которая зелена при снятом правиле, измеряет собственную доброжелательность.
"""
from __future__ import annotations

import unittest

from kukai.ir.decompile import geom_alias as GA


def _el(eid, tid, dims=(1000.0, 2000.0, 3000.0), origin=(0.0, 0.0, 0.0)):
    if dims is None:
        return {"element_id": eid, "type_id": tid}
    return {
        "element_id": eid,
        "type_id": tid,
        "bbox_min_mm": list(origin),
        "bbox_max_mm": [origin[i] + dims[i] for i in range(3)],
    }


class TheAliasSavesCallsOnlyWhenTheShapeAgrees(unittest.TestCase):

    def test_identical_instances_of_one_type_ask_once(self):
        plan = GA.plan_geometry_asks([_el("1", "T"), _el("2", "T"),
                                      _el("3", "T")])
        self.assertEqual(plan.ask, ("1",))
        self.assertEqual(plan.alias, {"2": "1", "3": "1"})
        self.assertEqual(plan.saved_calls(), 2)
        self.assertEqual(plan.reason["1"], "representative")

    def test_a_divergent_instance_is_asked_and_NAMED(self):
        """КОНТРОЛЬ-FAIL к предыдущему. Мимбель того же типа, но длиннее:
        форму гнёт экземпляр, и алиас был бы тихой ложью."""
        plan = GA.plan_geometry_asks([
            _el("1", "T", dims=(100.0, 100.0, 3000.0)),
            _el("2", "T", dims=(100.0, 100.0, 3000.0)),
            _el("3", "T", dims=(100.0, 100.0, 4500.0)),   # кроен по месту
        ])
        self.assertEqual(sorted(plan.ask), ["1", "3"])
        self.assertEqual(plan.alias, {"2": "1"})
        self.assertEqual(plan.reason["3"], "instance_driven")
        self.assertEqual(plan.stats["instance_driven"], 1)

    def test_the_tolerance_is_the_one_declared_and_it_decides(self):
        near = [_el("1", "T", dims=(1000.0, 2000.0, 3000.0)),
                _el("2", "T", dims=(1000.0, 2000.0, 3001.5))]
        self.assertEqual(GA.plan_geometry_asks(near).alias, {"2": "1"})
        # тот же вход при вдвое меньшем допуске обязан развалить алиас
        strict = GA.plan_geometry_asks(near, tolerance_mm=1.0)
        self.assertEqual(strict.alias, {})
        self.assertEqual(strict.reason["2"], "instance_driven")


class NothingIsAliasedOnFaith(unittest.TestCase):

    def test_a_type_with_one_instance_is_asked_not_aliased(self):
        """ВЫРОЖДЕННЫЙ СЛУЧАЙ НАЗВАН. Тип в одном экземпляре согласован по
        построению — сравнивать не с чем, и записывать это в экономию значило
        бы мерить отсутствие конкуренции."""
        plan = GA.plan_geometry_asks([_el("1", "T"), _el("2", "U")])
        self.assertEqual(sorted(plan.ask), ["1", "2"])
        self.assertEqual(plan.alias, {})
        self.assertEqual(plan.reason["1"], "singleton")

    def test_no_type_means_ask(self):
        plan = GA.plan_geometry_asks([{"element_id": "1"},
                                      {"element_id": "2"}])
        self.assertEqual(sorted(plan.ask), ["1", "2"])
        self.assertEqual(plan.reason["1"], "type_unknown")

    def test_no_bbox_means_ask_even_within_a_known_type(self):
        plan = GA.plan_geometry_asks([_el("1", "T"), _el("2", "T", dims=None)])
        self.assertEqual(sorted(plan.ask), ["1", "2"])
        self.assertEqual(plan.reason["2"], "bbox_unknown")

    def test_a_representative_without_a_bbox_aliases_nobody(self):
        """Образец, который нечем сверить, не делает своё тело общим."""
        plan = GA.plan_geometry_asks([_el("1", "T", dims=None),
                                      _el("2", "T"), _el("3", "T")])
        self.assertEqual(sorted(plan.ask), ["1", "2", "3"])
        self.assertEqual(plan.alias, {})


class EveryElementIsAccountedFor(unittest.TestCase):

    def test_ask_and_alias_partition_the_input(self):
        els = ([_el(str(i), "A") for i in range(1, 6)]
               + [_el(str(i), "B", dims=(9.0, 9.0, float(i))) for i in range(6, 11)]
               + [{"element_id": "11"}])
        plan = GA.plan_geometry_asks(els)
        self.assertEqual(len(plan.ask) + len(plan.alias), len(els))
        self.assertEqual(set(plan.reason), set(plan.ask))
        for why in plan.reason.values():
            self.assertIn(why, GA.ASK_REASONS)

    def test_the_share_is_named_a_lower_bound_in_the_field_itself(self):
        """Имя поля несёт границу. Число «28 %», названное просто долей, было
        бы прочитано как оценка, а габарит объявляет разными одинаковые формы,
        повёрнутые на непрямой угол."""
        plan = GA.plan_geometry_asks([_el("1", "T"), _el("2", "T")])
        self.assertIn("alias_share_lower_bound", plan.stats)
        self.assertEqual(plan.stats["alias_share_lower_bound"], 50.0)


class TheRepresentativeIsDeterministic(unittest.TestCase):

    def test_input_order_does_not_move_the_representative(self):
        """Недетерминированный выбор дал бы одному зданию разные `geo_hash` от
        прогона к прогону, и разность двух разборов показала бы правки там,
        где ничего не менялось."""
        a = GA.plan_geometry_asks([_el("7", "T"), _el("3", "T"), _el("11", "T")])
        b = GA.plan_geometry_asks([_el("11", "T"), _el("7", "T"), _el("3", "T")])
        self.assertEqual(a.ask, b.ask)
        self.assertEqual(a.alias, b.alias)
        self.assertEqual(a.ask, ("3",))

    def test_numeric_ids_sort_by_number_not_by_string(self):
        """Строковая сортировка дала бы «10» < «9» и сделала бы образец
        зависимым от разрядности id."""
        plan = GA.plan_geometry_asks([_el("10", "T"), _el("9", "T")])
        self.assertEqual(plan.ask, ("9",))


class ThePositionIsNEVERInherited(unittest.TestCase):
    """Главный замок модуля. Форма общая, положение — нет."""

    def _plan(self):
        return GA.plan_geometry_asks([_el("1", "T"), _el("2", "T")])

    def test_the_alias_row_carries_the_hash_and_drops_the_transform(self):
        """Строки съёма несут `element_id` — имя спрошено у живого прогона.

        Первая редакция читала `source_element_id` (так зовётся поле в индексе
        КОНВЕЙЕРА) и на живой модели дала НОЛЬ форм при НУЛЕ отказов.
        """
        rows = [{"element_id": "1", "geo_hash": "a" * 64,
                 "transform": (1.0, 0.0, 0.0, 0.0)}]
        out = GA.attach_aliased_geometry(rows, self._plan())
        self.assertEqual(len(out), 2)
        alias_row = [r for r in out if r["element_id"] == "2"][0]
        self.assertEqual(alias_row["geo_hash"], "a" * 64)
        self.assertIsNone(alias_row["transform"])
        self.assertEqual(alias_row["alias_of"], "1")

    def test_the_pipeline_field_name_is_accepted_too(self):
        """КОНТРОЛЬ ВТОРОЙ СТОРОНЫ. Индекс конвейера действительно зовёт поле
        `source_element_id`; молча не найти его строку — тот же дефект,
        повёрнутый обратной стороной."""
        rows = [{"source_element_id": "1", "geo_hash": "b" * 64,
                 "transform": None}]
        out = GA.attach_aliased_geometry(rows, self._plan())
        self.assertEqual(len(out), 2)
        self.assertEqual([r for r in out if r.get("source_element_id") == "2"][0]
                         ["alias_of"], "1")

    def test_an_unextracted_representative_gives_nobody_a_shape(self):
        """Съём мог отказать по своим причинам. Тогда алиас НЕ выдаётся: строка
        без источника — это молчаливая выдача чужой формы."""
        out = GA.attach_aliased_geometry([], self._plan())
        self.assertEqual(out, [])


if __name__ == "__main__":
    unittest.main()


class TheTypeLibraryCountsMeshApartFromBox(unittest.TestCase):
    """`Gb` — тот же габаритный ящик, добытый дороже. Сложить его с мешем в
    одну графу «формы» значило бы объявить победой ровно то, на что жаловался
    владелец. Живой прогон 15.08 дал `Gm 16 / Gb 14 / A 1`, и разница между
    «30 типов с формой» и «16 типов с мешем» — это весь смысл канала."""

    def _els(self):
        return [_el("1", "T"), _el("2", "T"), _el("3", "U"), _el("4", "U")]

    def test_a_box_tier_is_a_shape_but_NOT_a_mesh(self):
        plan = GA.plan_geometry_asks(self._els())
        rows = [{"element_id": "1", "geo_hash": "a" * 64, "tier": "Gm"},
                {"element_id": "3", "geo_hash": "b" * 64, "tier": "Gb"}]
        lib = GA.build_type_shape_library(self._els(), rows, plan)
        self.assertEqual(lib["types_with_shape"], 2)
        self.assertEqual(lib["types_with_mesh"], 1)
        self.assertEqual(lib["instances_covered"], 4)
        self.assertEqual(lib["instances_covered_by_mesh"], 2)
        self.assertEqual(lib["tiers"], {"Gm": 1, "Gb": 1})

    def test_only_representatives_enter_the_library(self):
        """КОНТРОЛЬ. Строка съёма НЕ представителя не имеет права стать формой
        типа: это форма одного экземпляра, выданная за форму всех."""
        plan = GA.plan_geometry_asks(self._els())
        rows = [{"element_id": "2", "geo_hash": "c" * 64, "tier": "Gm"}]
        lib = GA.build_type_shape_library(self._els(), rows, plan)
        self.assertEqual(lib["types_with_shape"], 0)
        self.assertEqual(lib["instances_covered"], 0)

    def test_the_gate_is_off_by_default(self):
        self.assertFalse(GA.type_shapes_enabled())
