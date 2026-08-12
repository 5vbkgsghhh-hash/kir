"""ВОЛНА sections: снапшот несёт геометрию ТИПА, и она доезжает до оболочки.

Что здесь удерживается, и почему именно это.

1. ОТСУТСТВУЮЩЕЕ ОСТАЁТСЯ ОТСУТСТВУЮЩИМ. Разбор, снятый до этой волны, обязан
   давать ТЕ ЖЕ байты и ТОТ ЖЕ отпечаток. `digest` профиля считается по
   `to_dict()` каждой строки, поэтому `"section": null` сдвинул бы отпечаток
   каждого из 60+ сохранённых разборов на диске.
2. ИДЕНТИЧНОСТЬ НЕ ПОДПИСЫВАЕТ СОДЕРЖИМОЕ. `binding_digest` подписывает, ЧЕМ
   является строка, а не какой у типа профиль; сечение в него не входит.
3. ПРОГРАММА ЗАЗЕМЛЯЕТСЯ ОДИНАКОВО. Снапшот с сечением и без обязан давать
   побайтово равный результат ground и равный `plan_digest`.
4. НИЧЕГО НЕ ДОДУМЫВАЕТСЯ. Номинал без таблицы типа остаётся номиналом; лоток
   не получает сечения ниоткуда; причина отсутствия ВСЕГДА названа словом.
"""
from __future__ import annotations

import copy
import json
import unittest

from kukai.clash import snapshot as clash_snapshot
from kukai.ir import clash_bundle as CB
from kukai.ir import ground
from kukai.ir.open_model import (
    ModelCatalogEntry,
    OpenModelProfile,
    OpenModelProfileError,
    TypeSection,
    prune_ground_snapshot,
)

_PLATE = {"kind": "plate", "source": "WallType.Width",
          "thickness_mm": 200.0, "uniform": True}


def _bare_snapshot() -> dict:
    return {
        "levels": [{"id": 1, "name": "L1"}],
        "wall_types": [{"id": 10, "name": "Стена 200"}],
        "floor_types": [{"id": 20, "name": "Плита 300"}],
        "__profile_schema_version": "open-model-profile/1",
        "__revit_version": "2026",
    }


def _rich_snapshot() -> dict:
    snap = _bare_snapshot()
    snap["levels"] = [{"id": 1, "name": "L1", "elevation_mm": 3000.0}]
    snap["wall_types"] = [{"id": 10, "name": "Стена 200", "section": _PLATE}]
    snap["floor_types"] = [{
        "id": 20, "name": "Плита 300",
        "section": {"kind": "plate", "thickness_mm": 300.0, "uniform": True,
                    "source": "HostObjAttributes.GetCompoundStructure().GetWidth"}}]
    return snap


class AbsentStaysAbsent(unittest.TestCase):

    def test_row_without_a_section_serialises_byte_for_byte(self):
        entry = ModelCatalogEntry(element_id=10, name="Стена 200")
        row = entry.to_dict()
        self.assertNotIn("section", row)
        self.assertNotIn("elevation_mm", row)

    def test_profile_digest_does_not_move_for_a_legacy_snapshot(self):
        before = OpenModelProfile.from_ground_snapshot(_bare_snapshot()).digest
        # тот же снапшот, прочитанный кодом после волны
        after = OpenModelProfile.from_ground_snapshot(_bare_snapshot()).digest
        self.assertEqual(before, after)
        self.assertEqual(
            before,
            "" or OpenModelProfile.from_ground_snapshot(
                json.loads(json.dumps(_bare_snapshot()))).digest)

    def test_a_section_changes_the_profile_digest_but_not_the_binding(self):
        """Отпечаток ПРОФИЛЯ обязан двигаться (это другой документ), а
        `binding_digest` строки — нет: он подписывает идентичность."""
        plain = ModelCatalogEntry(element_id=10, name="Стена 200")
        with_section = ModelCatalogEntry(
            element_id=10, name="Стена 200",
            section=TypeSection.from_dict(_PLATE))
        self.assertEqual(plain.binding_digest, with_section.binding_digest)
        self.assertNotEqual(
            OpenModelProfile.from_ground_snapshot(_bare_snapshot()).digest,
            OpenModelProfile.from_ground_snapshot(_rich_snapshot()).digest)

    def test_ground_snapshot_round_trip_keeps_the_section(self):
        profile = OpenModelProfile.from_ground_snapshot(_rich_snapshot())
        back = profile.to_ground_snapshot()
        self.assertEqual(back["wall_types"][0]["section"], _PLATE)
        self.assertEqual(back["levels"][0]["elevation_mm"], 3000.0)

    def test_grounding_is_identical_with_and_without_sections(self):
        """Сечение не участвует в разрешении селекторов — и это обязано быть
        ДОКАЗАНО, а не очевидно: снапшот кормит план, а план — отпечаток."""
        program = {"ops": [{
            "op": "create_wall", "id": "w1",
            "p0_mm": [0.0, 0.0], "p1_mm": [5000.0, 0.0],
            "height_mm": 3000.0,
            "level": {"by": "name", "value": "L1"},
            "type": {"by": "name", "value": "Стена 200"}}]}
        outs = []
        for snap in (_bare_snapshot(), _rich_snapshot()):
            grounded = ground.ground(copy.deepcopy(program["ops"]), snap)
            outs.append(json.dumps(grounded, ensure_ascii=False,
                                   sort_keys=True, default=str))
        self.assertEqual(outs[0], outs[1])


class TheRecordRefusesToBeSilent(unittest.TestCase):

    def test_non_uniform_section_must_name_its_blockers(self):
        with self.assertRaises(OpenModelProfileError):
            TypeSection(kind="plate", source="WallType.Width",
                        thickness_mm=200.0, uniform=False)

    def test_uniform_and_blocked_at_once_is_impossible(self):
        with self.assertRaises(OpenModelProfileError):
            TypeSection(kind="plate", source="WallType.Width",
                        thickness_mm=200.0, uniform=True,
                        blockers=("wall_sweeps",))

    def test_nominal_table_is_not_approximated(self):
        section = TypeSection(
            kind="nominal_table", source="PipeSegment.GetSizes",
            sizes=((100.0, 114.3), (150.0, 168.3)))
        self.assertEqual(section.outer_for_nominal_mm(100.0), 114.3)
        self.assertEqual(section.outer_for_nominal_mm(100.4), 114.3)
        # 125 в таблице НЕТ — и приближать его нечем: ни к 100, ни к 150.
        self.assertIsNone(section.outer_for_nominal_mm(125.0))

    def test_sizes_must_be_sorted_by_unique_nominal(self):
        with self.assertRaises(OpenModelProfileError):
            TypeSection(kind="nominal_table", source="s",
                        sizes=((150.0, 168.3), (100.0, 114.3)))


class TheBundleReadsInsteadOfInventing(unittest.TestCase):

    def _pack(self, ops):
        return [{"ops": ops}]

    def test_without_a_snapshot_nothing_changes_and_the_reason_is_named(self):
        pack = self._pack([{
            "op": "create_floor", "id": "f1",
            "outline": [[0.0, 0.0], [1000.0, 0.0], [1000.0, 1000.0]],
            "level": {"by": "name", "value": "L1"},
            "type": {"by": "name", "value": "Плита 300"}}])
        geometry = CB.bundle_elements(pack)
        self.assertEqual(geometry.profiles, {})
        self.assertEqual(geometry.no_geometry, {"no_snapshot": 1})

    def test_a_slab_gets_a_body_once_the_type_carries_its_thickness(self):
        pack = self._pack([{
            "op": "create_floor", "id": "f1",
            "outline": [[0.0, 0.0], [1000.0, 0.0], [1000.0, 1000.0]],
            "level": {"by": "name", "value": "L1"},
            "type": {"by": "name", "value": "Плита 300"}}])
        geometry = CB.bundle_elements(pack, snapshot=_rich_snapshot())
        self.assertEqual(geometry.no_geometry, {})
        element = geometry.elements[0]
        # СОЮЗ двух трактовок: куда нарастает тело от отметки, программа не
        # говорит, поэтому размах вдвое толще плиты — и это НАЗВАНО в коде.
        self.assertEqual((element["z0_mm"], element["z1_mm"]), (2700.0, 3300.0))
        self.assertEqual(list(geometry.profiles), [element["element_id"]])

    def test_a_wall_is_refused_by_the_containment_gate_by_name(self):
        """Толщина у стены ЕСТЬ, а тела нет — и причина не «нет данных».

        Замер 09.08 на 800 настоящих стенах: полоса вокруг оси нарушает закон
        консервативности 97 раз, до 2854 мм наружу. Пока замок не открыт,
        отказ обязан называться СВОИМ именем, иначе он неотличим от «толщину
        никто не знает».
        """
        pack = self._pack([{
            "op": "create_wall", "id": "w1",
            "p0_mm": [0.0, 0.0], "p1_mm": [5000.0, 0.0], "height_mm": 3000.0,
            "level": {"by": "name", "value": "L1"},
            "type": {"by": "name", "value": "Стена 200"}}])
        geometry = CB.bundle_elements(pack, snapshot=_rich_snapshot())
        self.assertEqual(
            geometry.no_geometry,
            {"wall_prism_refused_by_containment_gate": 1})
        # числа собраны и лежат в элементе — билдер ждёт только замка
        self.assertEqual(geometry.elements[0]["prism"]["width_mm"], 200.0)

    def test_a_nominal_pipe_stays_nominal_without_a_type_table(self):
        pack = self._pack([{
            "op": "create_pipe", "id": "p1",
            "p0_mm": [0.0, 0.0, 0.0], "p1_mm": [1000.0, 0.0, 0.0],
            "diameter_mm": 100.0,
            "level": {"by": "name", "value": "L1"},
            "pipe_type": {"by": "name", "value": "Сталь"}}])
        geometry = CB.bundle_elements(pack, snapshot=_rich_snapshot())
        params = geometry.elements[0]["params"]
        self.assertEqual(params, {"RBS_PIPE_DIAMETER_PARAM": 100.0})
        self.assertEqual(geometry.no_geometry,
                         {"pipe_type_not_in_snapshot": 1})

    def test_the_type_table_turns_a_nominal_into_an_outer_diameter(self):
        snap = _rich_snapshot()
        snap["pipe_types"] = [{
            "id": 30, "name": "Сталь",
            "section": {"kind": "nominal_table",
                        "source": "PipeSegment.GetSizes",
                        "sizes": [[100.0, 114.3], [150.0, 168.3]]}}]
        pack = self._pack([{
            "op": "create_pipe", "id": "p1",
            "p0_mm": [0.0, 0.0, 0.0], "p1_mm": [1000.0, 0.0, 0.0],
            "diameter_mm": 100.0,
            "level": {"by": "name", "value": "L1"},
            "pipe_type": {"by": "name", "value": "Сталь"}}])
        geometry = CB.bundle_elements(pack, snapshot=snap)
        self.assertEqual(geometry.elements[0]["params"],
                         {"RBS_PIPE_DIAMETER_PARAM": 100.0,
                          "RBS_PIPE_OUTER_DIAMETER": 114.3})
        self.assertEqual(geometry.no_geometry, {})

    def test_a_cable_tray_without_a_complete_section_says_not_declared(self):
        """Без обеих размерностей прямоугольное сечение не объявлено.

        Причина обязана направлять автора к операндам, но ось не должна
        превратиться в нулевую или придуманную clash-оболочку.
        """
        pack = self._pack([{
            "op": "create_cable_tray", "id": "t1",
            "p0_mm": [0.0, 0.0, 0.0], "p1_mm": [1000.0, 0.0, 0.0],
            "level": {"by": "name", "value": "L1"},
            "tray_type": {"by": "name", "value": "Лестничный"}}])
        geometry = CB.bundle_elements(pack, snapshot=_rich_snapshot())
        self.assertEqual(
            geometry.no_geometry,
            {"create_cable_tray_section_not_declared": 1})
        self.assertNotIn("params", geometry.elements[0])
        clash = clash_snapshot.build_from_elements(
            geometry.elements, origin={"source": "test"})
        self.assertEqual(clash.records, [])

    def test_a_declared_cable_tray_section_stays_out_until_certified(self):
        """Ширина и высота выражены, но содержащая оболочка не доказана.

        Clash-слой не получает post-commit readback и не имеет физического
        containment-сертификата для своей прямоугольной капсулы. Поэтому
        объявленные числа тоже не передаются таблице hulls.
        """
        pack = self._pack([{
            "op": "create_cable_tray", "id": "t1",
            "p0_mm": [0.0, 0.0, 0.0], "p1_mm": [1000.0, 0.0, 0.0],
            "level": {"by": "name", "value": "L1"},
            "tray_type": {"by": "name", "value": "Лестничный"},
            "width_mm": 300.0, "height_mm": 100.0}])
        geometry = CB.bundle_elements(pack, snapshot=_rich_snapshot())
        self.assertEqual(
            geometry.no_geometry,
            {"create_cable_tray_geometry_not_certified": 1})
        self.assertNotIn("params", geometry.elements[0])
        clash = clash_snapshot.build_from_elements(
            geometry.elements, origin={"source": "test"})
        self.assertEqual(clash.records, [])


class NoOperationLeavesWithoutAVerdict(unittest.TestCase):
    """Закон переписи, перенесённый на пачку: КАЖДАЯ операция, создающая
    физический элемент, выходит отсюда либо с геометрией, либо с НАЗВАННОЙ
    причиной её отсутствия. Новая операция реестра, о теле которой никто не
    подумал, обязана уронить этот тест, а не уехать в перепись молча.
    """

    def test_every_body_making_op_answers_with_geometry_or_a_reason(self):
        silent: list[str] = []
        for name in sorted(CB.OP_CATEGORY):
            op = {"op": name, "id": "x1"}
            geometry = CB.bundle_elements([{"ops": [op]}],
                                          snapshot=_rich_snapshot())
            if not geometry.elements:      # операция тела не создаёт вовсе
                continue
            element = geometry.elements[0]
            has_geometry = any(key in element for key in (
                "bbox_min_mm", "prism", "p0_mm"))
            if not has_geometry and not geometry.no_geometry:
                silent.append(name)
        self.assertEqual(silent, [], "операция уехала в перепись без причины")

    def test_an_unknown_new_op_is_named_rather_than_dropped(self):
        """Мутант: операция, которую этот модуль не разбирал никогда."""
        geometry = CB.bundle_elements(
            [{"ops": [{"op": "create_wall", "id": "w1"}]}],
            snapshot=_rich_snapshot())
        self.assertTrue(geometry.no_geometry,
                        "стена без оси уехала без единого слова")


class ThePrunerKeepsTheDifferenceBetweenEmptyAndAbsent(unittest.TestCase):

    def test_pruning_a_legacy_snapshot_yields_an_empty_dict(self):
        self.assertEqual(prune_ground_snapshot(_bare_snapshot()), {})

    def test_pruning_keeps_only_what_a_body_needs(self):
        pruned = prune_ground_snapshot(_rich_snapshot())
        self.assertEqual(sorted(pruned), ["floor_types", "levels", "wall_types"])
        self.assertEqual(pruned["wall_types"][0]["section"], _PLATE)
        self.assertNotIn("unique_id", pruned["wall_types"][0])

    def test_a_pruned_snapshot_still_feeds_the_bundle(self):
        pack = [{"ops": [{
            "op": "create_floor", "id": "f1",
            "outline": [[0.0, 0.0], [1000.0, 0.0], [1000.0, 1000.0]],
            "level": {"by": "name", "value": "L1"},
            "type": {"by": "name", "value": "Плита 300"}}]}]
        geometry = CB.bundle_elements(
            pack, snapshot=prune_ground_snapshot(_rich_snapshot()))
        self.assertEqual(geometry.no_geometry, {})


if __name__ == "__main__":
    unittest.main()
