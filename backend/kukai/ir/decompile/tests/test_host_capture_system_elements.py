"""ЗАХВАТ ХОЗЯИНА У СИСТЕМНОГО ЭЛЕМЕНТА — и обещание про ленточный фундамент.

`extract.build_category_batch_cs` заполнял `host_id` ЕДИНСТВЕННЫМ способом —
`__element as FamilyInstance`. Системный элемент (`WallFoundation`, `Railing`,
`Opening`, изоляция трубы/воздуховода) под это приведение не подходит, поэтому
у него `host_id` оставался пустым ВСЕГДА, и L0 не нёс о нём ни одного факта,
по которому его можно отличить от экземпляра семейства ТОЙ ЖЕ категории:
`category` у ленточного фундамента и у столбчатого башмака одна
(`OST_StructuralFoundation`), а различать по `type_name` — сопоставление по
голому имени, которое канон запрещает.

ЧТО ЛОМАЛОСЬ (замерено чтением кода 09.08, ветка feat/kir-day-integration).
`reverse_contract` про `create_wall_foundation` обещает: такой элемент —
«типизованный атом, НИКОГДА не переизлучаемый молча как столбчатый башмак».
`lift._lift_foundation` при `geom_kind is POINT` выдаёт
`create_foundation(variety="isolated")` без единой проверки на то, ЧЕМ элемент
является. Обещание держалось ровно потому, что у `WallFoundation` нет
`LocationPoint` — то есть ПО ПОВЕДЕНИЮ REVIT, а не по нашему инварианту. Это
тот же класс, что тест, проходящий по совпадению фикстуры.

ЧЕМ ПОЧИНЕНО: захват получил ОДНУ таблицу читателей хозяина
(`extract._HOST_READERS`) и один генератор к ней; вместе с `host_id` в строку
пишется `host_source` — КЛАСС отношения, а не догадка по имени. Лифтер
отказывает по КЛАССУ (`HostSource.WALL_FOUNDATION`), а не по факту «хозяин
вообще есть»: в замороженном L0 непустой `host_id` ДОКАЗЫВАЕТ, что элемент был
`FamilyInstance` (другая ветка его не заполняла), то есть как раз честный
башмак. Отказ по одному лишь `host_id` отверг бы исправную работу.

Дисциплина §18.7: опровергающий тест ДО починки.
"""
from __future__ import annotations

import unittest

from kukai.ir.decompile.extract import build_category_batch_cs
from kukai.ir.decompile.l1_schema import AtomReason
from kukai.ir.decompile.lift import _SHAPE_REFUSALS, lift_document_detailed
from kukai.ir.decompile.schema import (
    GeometryKind,
    L0Document,
    L0Element,
    LevelInfo,
    ProjectInfo,
)


def _row(
    category: str,
    element_id: str,
    *,
    geom_kind: str,
    host_id: str | None = None,
    host_source: str | None = None,
) -> dict:
    """Строка L0 в том виде, в каком её отдаёт мост.

    Элемент строится ЧЕРЕЗ ``from_dict``, а не через конструктор, намеренно:
    так один и тот же текст теста исполним и ДО починки (лишний ключ просто
    игнорируется разбором), и после — то есть «покраснел до, позеленел после»
    проверяется дословно одним файлом, а не двумя его редакциями.
    """
    row: dict = {
        "element_id": element_id,
        "category": category,
        "category_ru": "—",
        "type_id": "7",
        "type_name": "ФМ1",
        "level_id": "10",
        "level_name": "L1",
        "geom_kind": geom_kind,
        "p0_mm": (
            [1000.0, 2000.0, 0.0] if geom_kind in ("point", "curve") else None),
        "p1_mm": [4000.0, 2000.0, 0.0] if geom_kind == "curve" else None,
        "rotation_deg": 0.0 if geom_kind == "point" else None,
        "bbox_min_mm": [0.0, 0.0, 0.0],
        "bbox_max_mm": [2000.0, 3000.0, 600.0],
        "host_id": host_id,
        "params": {},
    }
    if host_source is not None:
        row["host_source"] = host_source
    return row


def _document(*rows: dict) -> L0Document:
    return L0Document(
        doc_name="host-capture", revit_version="2024", units="mm",
        change_stamp="t", levels=(LevelInfo("10", "L1", 0.0),),
        grids=(), rooms=(), project_info=ProjectInfo(),
        elements=tuple(L0Element.from_dict(row) for row in rows))


def _nodes(result) -> dict:
    return {node["source_element_id"]: node for node in result.nodes}


class CaptureReadsTheHostOfASystemElement(unittest.TestCase):
    """1 — дыра шире одного фундамента: мерим ЗАХВАТ, а не лифтер."""

    def test_family_instance_branch_alone_leaves_system_elements_blind(
        self,
    ) -> None:
        """Один механизм, а не список частных случаев.

        Читатели держатся ОДНОЙ таблицей и рендерятся ОДНИМ генератором;
        `FamilyInstance` входит в неё на общих правах и перестал быть
        особым случаем. Тест требует именно этого: чтобы источник каждой
        ветки был назван в строке, а не подразумевался её порядком.
        """
        cs = build_category_batch_cs("OST_StructuralFoundation")
        # Имена ПОЛНЫЕ: тело извлечения оборачивают разные обёртки, и
        # зависеть от объявленного в них `using` значит зависеть от файла,
        # которого генератор не видит.
        for token in (
            "as Autodesk.Revit.DB.FamilyInstance", '"family_instance"',
            "as Autodesk.Revit.DB.WallFoundation", '"wall_foundation"',
            "as Autodesk.Revit.DB.Architecture.Railing", '"railing"',
            "as Autodesk.Revit.DB.Opening", '"opening"',
            "as Autodesk.Revit.DB.InsulationLiningBase", '"insulation_lining"',
            '__row["host_source"]',
        ):
            self.assertIn(token, cs, token)

    def test_reader_block_is_identical_across_categories(self) -> None:
        """Читатели не зависят от категории — как и блок параметров.

        Ворота компилируют извлечение на ТРЁХ категориях именно на этом
        основании (`gate_runner`: «блок параметров общий для всех категорий,
        различается только коллектор»). Если бы читатели ставились по
        категориям, три категории перестали бы покрывать остальные 74.
        """
        bodies = [build_category_batch_cs(name) for name in
                  ("OST_Walls", "OST_StructuralFoundation",
                   "OST_StairsRailing", "OST_PipeInsulations")]
        blocks = [body.split('__row["host_id"] = null;')[1].split(
            "__PutParams")[0] for body in bodies]
        self.assertEqual(len(set(blocks)), 1, "блок читателей разъехался")

    def test_no_host_is_null_and_never_the_string_of_invalid_id(self) -> None:
        """`ElementId.InvalidElementId` — это «хозяина нет», а не хозяин «-1».

        Ветки, читающие `ElementId` напрямую (`WallFoundation.WallId`,
        `Railing.HostId`, `InsulationLiningBase.HostElementId`), обязаны
        отсеивать невалидный id: без этого свободно стоящее ограждение
        получило бы `host_id = "-1"` — непустую строку, то есть ЛОЖНОГО
        хозяина, что хуже пустого поля.
        """
        cs = build_category_batch_cs("OST_StairsRailing")
        self.assertIn("ElementId.InvalidElementId", cs)
        # Идиома на все шесть версий: только ToString(); ни .Value, ни
        # .IntegerValue (у ElementId нет общего члена на 2021-2026).
        block = cs.split('__row["host_id"] = null;')[1].split("__PutParams")[0]
        self.assertNotIn("IntegerValue", block)
        self.assertNotIn(".Value", block)


class AWallFoundationIsNeverAnIsolatedFooting(unittest.TestCase):
    """2 — обещание reverse_contract, обеспеченное КОДОМ, а не поведением."""

    def test_point_placed_wall_foundation_becomes_a_typed_atom(self) -> None:
        """ОПРОВЕРГАЮЩИЙ ТЕСТ. До починки здесь `create_foundation`.

        Именно та ветка, ради которой работа: `geom_kind is POINT` уходила в
        `variety="isolated"` без единой проверки на класс элемента.
        """
        result = lift_document_detailed(_document(_row(
            "OST_StructuralFoundation", "500", geom_kind="point",
            host_id="900", host_source="wall_foundation")))
        node = _nodes(result)["500"]
        self.assertEqual(
            node["kind"], "atom",
            f"ленточный фундамент переизлучён как {node.get('op_name')!r}: "
            f"{node.get('params')!r}")

    def test_the_refusal_survives_every_geometry_kind(self) -> None:
        """Отказ по КЛАССУ, а не по геометрии.

        До починки обещание держалось тем, что у `WallFoundation` нет
        `LocationPoint`. Инвариант обязан не зависеть от того, что именно
        Revit положил в геометрию.
        """
        for geom_kind in ("point", "bbox_only", "curve"):
            with self.subTest(geom_kind=geom_kind):
                result = lift_document_detailed(_document(_row(
                    "OST_StructuralFoundation", "501", geom_kind=geom_kind,
                    host_id="900", host_source="wall_foundation")))
                node = _nodes(result)["501"]
                self.assertEqual(node["kind"], "atom", geom_kind)

    def test_the_reason_never_falls_through_to_place_family(self) -> None:
        """Не ФОРМЕННЫЙ отказ: иначе лента станет обычным семейством.

        `MISSING_GEOMETRY` (сегодняшний ответ на bbox-фундамент) входит в
        `_SHAPE_REFUSALS`, то есть отдаёт элемент `place_family`. Для
        ленточного фундамента это не «частичный успех», а потеря объекта.
        """
        result = lift_document_detailed(_document(_row(
            "OST_StructuralFoundation", "502", geom_kind="bbox_only",
            host_id="900", host_source="wall_foundation")))
        node = _nodes(result)["502"]
        self.assertEqual(node["kind"], "atom")
        reason = node["reason"]
        self.assertNotIn(
            AtomReason(reason["code"]), _SHAPE_REFUSALS, reason["code"])
        self.assertIn("wall_foundation", reason["detail"])


class TheRefusalMustNotCostWorkingCoverage(unittest.TestCase):
    """3 — честность, купленная отказом исправной работе, — не честность."""

    def test_a_hosted_family_instance_footing_still_lifts(self) -> None:
        """Башмак на грани/рабочей плоскости — по-прежнему `isolated`.

        Отказ по одному лишь непустому `host_id` отверг бы этот элемент, а он
        РОВНО тот, ради которого ветка `isolated` написана.
        """
        result = lift_document_detailed(_document(_row(
            "OST_StructuralFoundation", "503", geom_kind="point",
            host_id="900", host_source="family_instance")))
        node = _nodes(result)["503"]
        self.assertEqual(node["kind"], "op")
        self.assertEqual(node["op_name"], "create_foundation")
        self.assertEqual(node["params"]["variety"], "isolated")

    def test_frozen_l0_without_the_field_answers_exactly_as_before(
        self,
    ) -> None:
        """Отсутствие `host_source` = «не мерили», а не «системный элемент».

        Все 67 сохранённых разборов сняты до этой волны. Непустой `host_id` в
        них ДОКАЗЫВАЕТ `FamilyInstance` — другая ветка его не заполняла, —
        поэтому старый слепок обязан дать прежний ответ дословно.
        """
        for host_id in (None, "900"):
            with self.subTest(host_id=host_id):
                result = lift_document_detailed(_document(_row(
                    "OST_StructuralFoundation", "504", geom_kind="point",
                    host_id=host_id)))
                node = _nodes(result)["504"]
                self.assertEqual(node["kind"], "op")
                self.assertEqual(node["params"]["variety"], "isolated")


class TheClassFactRoundTripsThroughL0(unittest.TestCase):
    """4 — поле дописано В ХВОСТ по закону дописи (как `curve_kind`)."""

    def test_host_source_round_trips(self) -> None:
        element = L0Element.from_dict(_row(
            "OST_StairsRailing", "600", geom_kind="bbox_only",
            host_id="900", host_source="railing"))
        restored = L0Element.from_dict(element.to_dict())
        self.assertEqual(restored, element)
        self.assertEqual(restored.host_source.value, "railing")

    def test_old_row_without_the_field_stays_valid(self) -> None:
        element = L0Element.from_dict(_row(
            "OST_Doors", "601", geom_kind="point", host_id="900"))
        self.assertIsNone(element.host_source)
        self.assertIsNone(element.to_dict()["host_source"])

    def test_a_source_without_an_id_is_refused(self) -> None:
        """Источник без id — противоречие, а не бедная строка."""
        from kukai.ir.decompile.schema import L0SchemaError
        with self.assertRaises(L0SchemaError):
            L0Element.from_dict(_row(
                "OST_StructuralFoundation", "602", geom_kind="point",
                host_id=None, host_source="wall_foundation"))


if __name__ == "__main__":
    unittest.main()
