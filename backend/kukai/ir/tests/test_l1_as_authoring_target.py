"""Годен ли L1 как ЦЕЛЬ АВТОРСТВА, а не только как слепок существующего.

ЗАЧЕМ. Решение директора 12.08: разворот замысла целится в **L1**, а не в
диалект программы — тогда чанкование, ref-замыкание и топосорт достаются даром
от `materialize` (куплены 76 прогонами по настоящим зданиям; группировка по
`host` оставляла 39 чанков из 133 отказанными на башне `k2_ar_rd_v8`), и второй
обходчик ссылок не заводится вовсе.

Решение стоит на посылке, которую надо было проверить ПЕРВОЙ: **L1 — схема
ОБРАТНОГО хода, её узлы родом из существующего здания.** Если L1 обязателен к
происхождению из документа, целиться в него нельзя. Замер ниже — ответ.

ЗАМЕР 12.08.2026, и он ПОЛОЖИТЕЛЬНЫЙ С ОДНОЙ ИМЕНОВАННОЙ ДЫРОЙ:

* синтетическое происхождение ПРИНИМАЕТСЯ — `source_element_id` проверяется как
  непустая уникальная строка, НЕ как элемент документа; `_id` из него выводится
  детерминированно (`stable_l1_id`);
* ссылка на оп ЭТОЙ ЖЕ программы работает: уровень создаётся здесь же, стена
  ссылается `{"ref": …}`, `leaves_to_program` переводит;
* **единственный разрыв — ТИП/СИМВОЛ.** `{"by": "name"|"family_type", "_id": …}`
  требует, чтобы `_id` разбирался как целый ElementId, то есть тип обязан УЖЕ
  СУЩЕСТВОВАТЬ в документе. Схема это пропускает, рвёт переводчик диалекта:
  ``MaterializeError: L1 reference _id 'NEW' is not an integer ElementId``.

И ОБХОДА У ЭТОЙ ДЫРЫ СЕГОДНЯ НЕТ — обе дороги закрыты, замерено по реестру:

    family_symbol ПРОИЗВОДЯТ 2 опа (create_type, load_family)
    family_symbol ПОТРЕБЛЯЮТ  0
    селекторных параметров 123, из них не принимают ref вообще 69

То есть программа умеет создать/загрузить тип, и ни один оп не может на него
сослаться: у `create_wall.type`, `create_door.symbol`, `create_floor.type`
``ref_kinds`` ПУСТ. Именная дорога закрыта тем же: `ground.py` не упоминает ни
`create_type`, ни `load_family` (23 `def` в файле — греп живой), а заземление
идёт по снимку, снятому ДО исполнения.

СЛЕДСТВИЕ ДЛЯ МИССИИ, названное числом: авторство здания в документе, где его
каталога ещё нет, упирается не в геометрию и не в чанкование, а в ОДНО звено —
некому потребить созданный символ. Это ровно форма «построено и не подключено»,
и она измерима, а не на слух.

РОД СПИСКА: **регистр — ДАТИРОВАННЫЙ ЗАМЕР, а не полнота.** Тест краснеет, когда
дыру закроют, — и это хорошая новость, обязывающая обновить строку О12 в
`KIR_PLAN.md`, а не признак поломки.
"""
from __future__ import annotations

import unittest

from kukai.ir import spec
from kukai.ir.decompile.l1_schema import (
    L1SchemaError, stable_l1_id, validate_l1_nodes)
from kukai.ir.decompile.materialize import MaterializeError, leaves_to_program

LEVEL_SRC = "SYNTH-LEVEL-1"
WALL_SRC = "SYNTH-WALL-1"
LEVEL_ID = stable_l1_id("op", LEVEL_SRC)


def _node(op_name, source_id, params, level_name=None):
    return {
        "kind": "op",
        "_id": stable_l1_id("op", source_id),
        "source_element_id": source_id,
        "level_name": level_name,
        "anchor_mm": None,
        "type_name": "—",
        "op_name": op_name,
        "params": params,
    }


def _level():
    return _node("create_level", LEVEL_SRC, {"name": "Этаж 1", "elev_mm": 0})


def _wall(type_selector):
    return _node("create_wall", WALL_SRC, {
        "p0_mm": [0, 0], "p1_mm": [6000, 0], "height_mm": 3000,
        "level": {"ref": LEVEL_ID},
        "type": type_selector,
    }, level_name="Этаж 1")


class L1AcceptsABuildingThatDoesNotExistYet(unittest.TestCase):

    def test_synthetic_origin_is_accepted(self):
        """`source_element_id` — уникальная строка, а НЕ элемент документа."""
        nodes = validate_l1_nodes(
            [_level(), _wall({"by": "name", "value": "Стена 200",
                              "_id": "12345"})])
        self.assertEqual(len(nodes), 2)

    def test_the_probe_can_say_no(self):
        """Контроль-FAIL: пустое происхождение обязано краснеть.

        Без него «принято» выше не отличить от проверки, которая не может
        отказать никому.
        """
        with self.assertRaises(L1SchemaError):
            validate_l1_nodes(
                [_node("create_level", "", {"name": "x", "elev_mm": 0})])

    def test_a_ref_to_an_op_of_the_same_program_survives_translation(self):
        """Уровень, создаваемый ЭТОЙ ЖЕ программой, адресуем."""
        nodes = validate_l1_nodes(
            [_level(), _wall({"by": "name", "value": "Стена 200",
                              "_id": "12345"})])
        result = leaves_to_program(nodes, include_datums=True)
        self.assertTrue(result.programs)


class TheOneBreakIsTheTypeThatDoesNotExistYet(unittest.TestCase):

    def test_schema_admits_it_but_translation_refuses(self):
        """Граница живёт в переводчике диалекта, а не в схеме — это важно.

        Схема пропускает тип без ElementId; отказ приходит из `materialize`.
        Значит чинить надо диалект ссылки, а не валидатор.
        """
        nodes = validate_l1_nodes(
            [_level(), _wall({"by": "name", "value": "Стена, которой нет",
                              "_id": "NEW"})])
        with self.assertRaises(MaterializeError) as ctx:
            leaves_to_program(nodes, include_datums=True)
        self.assertIn("is not an integer ElementId", str(ctx.exception))

    def test_the_symbol_this_program_creates_is_now_consumable(self):
        """РЕГИСТР СРАБОТАЛ И БЫЛ ИСПОЛНЕН 13.08.2026 — здесь его вторая жизнь.

        До 13.08 этот тест требовал `consumers == []` и нёс приказ: «краснеет,
        когда дыру закроют — это хорошая новость и приказ обновить О12».
        Полный набор на сведённой линии его покрасил, приказ исполнен, и
        утверждение перевёрнуто, а не снято: снять значило бы потерять
        единственное место, где ребро языка проверяется машиной.

            замер 12.08   family_symbol производят 2, потребляют 0
            замер 13.08   производят 2, потребляют 7   (A8)

        Семь потребителей — это `symbol` у `create_beam`, `create_beam_system`,
        `create_column`, `create_door`, `create_foundation`, `create_window`,
        `place_family`; все семь идут через ОДНУ площадку `_symbol_res`.

        ЧТО ЭТОТ ТЕСТ ТЕПЕРЬ ОХРАНЯЕТ, и почему оба конца обязательны:
        производители без потребителей — незамкнутое ребро (то, что было);
        потребители без производителей — зеркальное незамкнутое ребро, и оно
        выглядит БОЛЬШЕЙ завершённостью, потому что строк в реестре больше.
        Типовые параметры (`FloorType`/`RoofType`) сюда намеренно НЕ добавлены:
        их класс не производит ни один оп.
        """
        producers = [
            name for name, op in spec.OPS.items()
            if op.result.reference_kind is not None
            and op.result.reference_kind.value == "family_symbol"]
        consumers = sorted(
            f"{name}.{param.name}"
            for name, op in spec.OPS.items()
            for param in op.params
            if any(kind.value == "family_symbol" for kind in param.ref_kinds))
        self.assertGreaterEqual(
            len(producers), 1,
            "производителей family_symbol не осталось, а потребители есть — "
            "это ЗЕРКАЛЬНОЕ незамкнутое ребро, хуже исходного")
        self.assertTrue(
            consumers,
            "потребителей family_symbol снова ноль — ребро разомкнулось "
            "обратно; см. A8 и `_symbol_res`")
        self.assertEqual(consumers, [
            "create_beam.symbol", "create_beam_system.symbol",
            "create_column.symbol", "create_door.symbol",
            "create_foundation.symbol", "create_window.symbol",
            "place_family.symbol"])


if __name__ == "__main__":
    unittest.main()
