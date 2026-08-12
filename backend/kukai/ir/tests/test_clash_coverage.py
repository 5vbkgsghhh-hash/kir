"""ПОЧЕМУ ЭЛЕМЕНТ ОСТАЛСЯ БЕЗ ТЕЛА — ПЯТЬ РАЗНЫХ ФАКТОВ, А НЕ ОДИН СПИСОК.

ЗАМЕР 11.08.2026, живая пересборка через `materialize.leaves_to_program`
(`/tmp/wiring/m_blind.py`, `/tmp/wiring/m_cover.py`):

    sob62_r23_v5      902 элемента, БЕЗ снимка типов тел 3, СО снимком 18
    snowdon_plumb_v4  16 257 элементов, БЕЗ снимка 905, СО снимком 16 247

То есть покрытие на двери пересборки определяется НЕ проводкой, а тем, дошёл
ли до проверки снимок открытой модели. Он доходит: `remember_sections` стоит в
ОБЩЕМ теле обеих дверей (`serving.py`, под `_program_writes`), и `clash_only`
читает `entry.sections`. Прежний доклад «аудит видит треть процента здания»
был замером МОЕГО СТЕНДА, который сеял журнал руками и без секций.

Остаток слепоты после снимка распадается на пять РАЗНЫХ фактов, и чинятся они
в пяти разных местах. Пока они лежат одним плоским списком причин, читатель не
может отличить «мы не спросили» от «спрашивать не у кого».
"""
from __future__ import annotations

import pathlib
import re
import unittest

from kukai.ir import clash_bundle as CB


class EveryBlindnessReasonIsClassified(unittest.TestCase):
    """ЗАМОК ОТ МОЛЧАНИЯ, тот же приём, что у таблицы категорий: умолчания
    нет. Новая причина, добавленная в модуль и не отнесённая ни к одному
    классу, обязана быть ЗАМЕЧЕНА тестом, а не уехать в отчёт безымянной."""

    SOURCE = pathlib.Path(CB.__file__)

    def _literals(self):
        text = self.SOURCE.read_text(encoding="utf-8")
        found = set()
        for m in re.finditer(r'blame\("([a-z0-9_]+)"\)', text):
            found.add(m.group(1))
        for m in re.finditer(r'return \(?"([a-z0-9_]+)"', text):
            name = m.group(1)
            if name and not name.startswith("kir"):
                found.add(name)
        for m in re.finditer(r'^\s+return \("([a-z0-9_]+)" if', text, re.M):
            found.add(m.group(1))
        return {f for f in found
                if f not in ("none", "ok", "bbox", "read", "absent", "prism")}

    def test_no_reason_is_left_unclassified(self):
        unknown = sorted(r for r in self._literals() if not CB.blind_class(r))
        self.assertEqual(unknown, [], f"причины без класса: {unknown}")

    def test_the_class_list_is_closed(self):
        """Класс, у которого нет человеческого имени, в отчёте выглядит
        техническим мусором и читается как «непонятно» — то есть как
        отсутствие ответа."""
        self.assertEqual(
            set(CB.BLIND_CLASSES.values())
            | {name for _, name in CB._BLIND_SUFFIX}
            | {"never_a_body"},
            set(CB.BLIND_CLASS_RU))

    def test_dynamic_reasons_are_classified_by_suffix(self):
        """`f"{name}_geometry_not_expressed"` собирается из имени операции, и
        перечислить их поимённо нельзя: реестр растёт."""
        self.assertEqual(CB.blind_class("create_door_geometry_not_expressed"),
                         "op_expresses_no_body")
        self.assertEqual(CB.blind_class("create_window_geometry_not_expressed"),
                         "op_expresses_no_body")
        self.assertEqual(
            CB.blind_class("route_duct_system_graph_has_no_readable_segment"),
            "not_declared_by_program")

    def test_an_invented_reason_is_not_silently_accepted(self):
        self.assertEqual(CB.blind_class("совершенно_новая_причина"), "")


class TheFiveFactsAreNotOneFact(unittest.TestCase):
    """Пять причин из РАЗНЫХ мест чинятся по-разному, и отчёт обязан их
    развести. Одна строка «без тела: 899» отвечает на пять вопросов сразу и
    поэтому не отвечает ни на один."""

    def _pack(self):
        return [{"ops": [
            # 1. операция тела не создаёт вовсе
            {"op": "create_room", "id": "r1"},
            # 2. операция тела не выражает (геометрия у семейства)
            {"op": "create_door", "id": "d1"},
            # 3. программа не объявила число
            {"op": "create_cable_tray", "id": "t1",
             "p0_mm": [0.0, 0.0, 0.0], "p1_mm": [1000.0, 0.0, 0.0]},
            # 4. нужен снимок открытой модели
            {"op": "create_wall", "id": "w1",
             "p0_mm": [0.0, 0.0, 0.0], "p1_mm": [4000.0, 0.0, 0.0],
             "height_mm": 3000.0},
        ]}]

    def test_each_fact_lands_in_its_own_class(self):
        geo = CB.bundle_elements(self._pack())
        classes = {CB.blind_class(r) for r in geo.no_geometry}
        self.assertIn("op_expresses_no_body", classes)
        self.assertIn("not_declared_by_program", classes)
        self.assertIn("needs_live_model", classes)
        # операция без элемента вовсе считается ОТДЕЛЬНО, не через no_geometry
        self.assertIn("create_room", geo.no_body)
        self.assertNotIn("create_room", geo.no_geometry)

    def test_the_receipt_names_the_classes_not_only_the_count(self):
        block = CB._report(self._pack())
        self.assertIn("blind_by_class", block)
        self.assertTrue(block["blind_by_class"])
        text = block["message_ru"]
        for name in block["blind_by_class"]:
            self.assertIn(CB.BLIND_CLASS_RU[name].split(":")[0][:18], text)

    def test_a_hull_gate_refusal_is_not_our_gap(self):
        """Отказ ЧУЖОГО замка (`hulls`) и наша недоделка — разные вещи, и
        сваливать их в одну строку значит чинить не там."""
        self.assertEqual(
            CB.blind_class("wall_prism_refused_by_containment_gate"),
            "refused_by_hull_gate")
        self.assertEqual(CB.blind_class("no_snapshot"), "needs_live_model")


class OneTableForOneRelation(unittest.TestCase):
    """`OP_CATEGORY` дублировала `spec.OP_RESULT_CATEGORIES`, и две таблицы
    одного отношения УЖЕ разошлись — замер 11.08.2026
    (`/tmp/wiring/m_tables.py`, 29 строк против 44):

      * `create_railing` — моя строка `OST_StairsRailing`, реестр
        `("OST_Railings", "OST_StairsRailing")`. Ограждение бывает и
        отдельно стоящим; моя таблица называла категорию, которой Revit в
        этом случае не создаёт;
      * `create_face_wall` реестр знает (`OST_Walls`), а я не знала ВОВСЕ —
        стена по грани массы не попадала в поиск ни одним телом;
      * `create_foundation` variety=slab: реестр честно говорит
        `("OST_Floors", "OST_StructuralFoundation")` — тип решает, а
        компилятор типа не видит; моя строка выбирала одну молча.

    ЧТО ЭТО НЕ ОДНО И ТО ЖЕ ОТНОШЕНИЕ — тоже замерено, и поэтому таблица не
    просто заменяется. Реестр отвечает «какие категории оп создаёт В REVIT»
    (для переписи), а этому модулю нужно «какой категорией ключевать правило
    `hulls.KIND_TABLE`». Отсюда `create_room` есть у реестра и не нужен здесь,
    а литерал `"DirectShape"` реестр возвращает ВТОРЫМ ключом переписи, и
    категорией Revit он не является.
    """

    def test_the_local_table_is_gone(self):
        self.assertFalse(hasattr(CB, "OP_CATEGORY"),
                         "вторая таблица того же отношения жива")

    def test_the_registry_is_the_source(self):
        from kukai.ir import spec
        self.assertIs(CB._REGISTRY_CATEGORIES, spec.op_result_categories)

    def test_a_face_wall_now_gets_a_body(self):
        """Приобретение, а не только уборка: реестр знает оп, которого не
        знала я."""
        self.assertEqual(CB.category_of({"op": "create_face_wall"}),
                         "OST_Walls")

    def test_a_column_still_resolves_by_its_own_enum(self):
        self.assertEqual(
            CB.category_of({"op": "create_column", "category": "structural"}),
            "OST_StructuralColumns")
        self.assertEqual(
            CB.category_of({"op": "create_column",
                            "category": "architectural"}),
            "OST_Columns")

    def test_directshape_keeps_its_revit_category_not_the_census_key(self):
        for op in ("create_directshape", "create_solid_extrusion",
                   "create_solid_revolve"):
            self.assertEqual(
                CB.category_of({"op": op, "category": "furniture"}),
                "OST_Furniture", op)

    def test_an_op_the_registry_cannot_decide_is_named_not_guessed(self):
        """`create_foundation` variety=slab: перекрытие это или фундаментная
        плита, решает ТИП, которого компилятор не видит. Молча выбрать одну —
        это догадка; поэтому выбор назван и держится своей таблицей."""
        self.assertIn("create_foundation", CB.REGISTRY_GAPS)
        self.assertEqual(CB.category_of({"op": "create_foundation",
                                         "variety": "slab"}),
                         "OST_StructuralFoundation")

    def test_ops_the_registry_does_not_carry_are_named_as_gaps(self):
        for op in ("create_curtain_grid_line", "create_wall_foundation"):
            self.assertIn(op, CB.REGISTRY_GAPS)
            self.assertIsNotNone(CB.category_of({"op": op}))

    def test_room_and_text_still_produce_no_element(self):
        for op in ("create_room", "create_text", "place_family"):
            self.assertIsNone(CB.category_of({"op": op}), op)


if __name__ == "__main__":
    unittest.main()
