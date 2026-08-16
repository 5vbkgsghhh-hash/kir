"""МОСТ `op_id → element_id`: карта, отказ вместо тишины, и перевод.

Что здесь сторожится, по важности:

1. **Пустое пересечение — НАЗВАННАЯ находка, а не пустой список.** До 15.08
   `compare_geometry` на авторской программе возвращал `[]`, потому что каждая
   его ветка стоит под `if common:`. Пустой список расхождений читается как
   «всё совпало» — ноль величины, которую никто не считал.
2. **Ключи созданного ВЫВОДЯТСЯ из реестра.** Рукописный кортёж терял четыре
   созидающих опа (`segment_ids`) и нёс два имени, которых нет ни у одного опа.
3. **Пара «созидающие/никогда-не-созидающие» есть РАЗБИЕНИЕ** полей реестра:
   без остатка и без пересечения. Условие «без пересечения» поймало ошибку
   автора: `change_type` — `MUTATE` и несёт тот же `id`, что и 59 созидающих.
"""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("KUKAI_CHECKER_V2", "1")

from kukai.ir import created_ledger, design_check, spec           # noqa: E402
from kukai.ir.address import (                                    # noqa: E402
    Address, AddressSpace, AddressSpaceError, IdentityMissingError,
    assert_one_space, created_identity_fields, element_addresses,
    identity_field_reasons, receipt_map)


def _walls(prefix: str) -> list[dict]:
    """Замкнутая коробка 5×4 м на своём уровне, id по образцу `prefix`.

    Уровень создаётся ТУТ ЖЕ и адресуется `by=ref`: без него сборщик стену не
    берёт вовсе — проверено, и именно на этом сработала строка «контроль
    вырожден». Уровень несёт тот же префикс, потому что перевод обязан накрыть
    и его: адрес — свойство ВСЕХ узлов программы, а не только интересных.
    """

    box = [((0, 0), (5000, 0)), ((5000, 0), (5000, 4000)),
           ((5000, 4000), (0, 4000)), ((0, 4000), (0, 0))]
    level_id = f"{prefix}0"
    ops: list[dict] = [{"op": "create_level", "id": level_id,
                        "elev_mm": 0.0, "name": "L1"}]
    ops += [{"op": "create_wall", "id": f"{prefix}{i}",
             "p0_mm": list(p0), "p1_mm": list(p1),
             "level": {"by": "ref", "value": level_id}, "height_mm": 3000.0}
            for i, (p0, p1) in enumerate(box, start=1)]
    return ops


def _model(ops: list[dict]):
    nodes = design_check._ops_to_nodes(ops)
    model, _witness = design_check.spatial_model_from_program(
        nodes, building_id="контроль")
    return model


class TheMapIsDerivedFromTheRegistry(unittest.TestCase):

    def test_all_four_identity_forms_reach_the_map(self) -> None:
        """Карта обязана накрыть ВСЕ формы, а не только `id` у 59 опов."""

        ops = [{"op": "create_wall", "id": "w1"},
               {"op": "move_elements", "id": "m1"},
               {"op": "delete", "id": "d1"},
               {"op": "route_pipe_system", "id": "r1"},
               {"op": "query_count", "id": "q1"}]
        payload = {"w1": {"id": 9001}, "m1": {"moved_ids": [11, 12]},
                   "d1": {"deleted_id": 77}, "r1": {"segment_ids": [21, 22]},
                   "q1": {"n": 5}}
        got = element_addresses(ops, payload)
        self.assertEqual(sorted(got), ["d1", "m1", "r1", "w1"])
        self.assertNotIn("q1", got, "у запроса идентичности нет по контракту")
        self.assertEqual([a.value for a in got["r1"]], ["21", "22"])
        self.assertTrue(all(a.space is AddressSpace.ELEMENT_ID
                            for addrs in got.values() for a in addrs))

    def test_a_writing_op_without_identity_refuses(self) -> None:
        """КОНТРОЛЬ-FAIL: тихий пропуск дал бы неполную карту, похожую на полную."""

        ops = [{"op": "create_wall", "id": "w1"},
               {"op": "create_wall", "id": "w2"}]
        payload = {"w1": {"id": 9001}}                 # w2 без идентичности
        with self.assertRaises(IdentityMissingError) as caught:
            element_addresses(ops, payload)
        self.assertIn("w2", str(caught.exception))
        # и мягкий режим обязан существовать, но не быть умолчанием
        self.assertEqual(sorted(element_addresses(ops, payload, strict=False)),
                         ["w1"])

    def test_the_map_is_a_list_on_every_arity(self) -> None:
        """ОДНА ФОРМА НА ВСЕ АРНОСТИ — список даже когда элемент один.

        🔴 ЭТОТ ТЕСТ ЗАМЕНИЛ СОБОЙ `test_the_flat_translation_drops_plural_
        ops_on_purpose`, И ЗАМЕНИЛ ВМЕСТЕ С ЕГО УТВЕРЖДЕНИЕМ. Тот пришпиливал
        как ЗАДУМАННОЕ поведение то, что плоская карта роняет операции
        множественной арности: `op_to_element_ids(...) == {"w1": "9001"}` —
        и `r1` с двумя сегментами просто исчезал. Замерено 15.08 на реестре:
        так терялись ПЯТЬ пишущих опов из 66. Функция удалена, и утверждение
        о её «намеренности» удалено вместе с ней, а не закомментировано:
        закомментированное утверждение через месяц читается как временно
        снятое, а это было решение.
        """

        ops = [{"op": "create_wall", "id": "w1"},
               {"op": "route_pipe_system", "id": "r1"}]
        payload = {"w1": {"id": 9001}, "r1": {"segment_ids": [21, 22]}}
        got = receipt_map(ops, payload)
        self.assertEqual(got, {"w1": ["9001"], "r1": ["21", "22"]},
                         "множественная арность обязана ДОЕХАТЬ, а не выпасть")

    def test_a_flat_translation_now_refuses_instead_of_dropping(self) -> None:
        """КОНТРОЛЬ-FAIL СВЕДЕНИЯ: подмена формы меняет ответ ровно там, где
        должна.

        Плоская карта на границе по-прежнему нужна — `design_check.
        compare_geometry` берёт `translate: Mapping[str, str]`, потому что
        сравнивает стены, проёмы и помещения, все арности ОДИН. Разница с
        удалённой функцией в ИСХОДЕ: явная распаковка `(only,)` ОТКАЗЫВАЕТ на
        множественной арности там, где та молча теряла.
        """

        ops = [{"op": "create_wall", "id": "w1"},
               {"op": "route_pipe_system", "id": "r1"}]
        payload = {"w1": {"id": 9001}, "r1": {"segment_ids": [21, 22]}}

        # ЧЕСТНЫЙ ПУТЬ: там, где арность одна, распаковка проходит.
        only_walls = {"w1": payload["w1"]}
        flat = {oid: only for oid, (only,) in
                receipt_map(ops[:1], only_walls).items()}
        self.assertEqual(flat, {"w1": "9001"})

        # А на множественной — ОТКАЗ, а не тихая потеря.
        with self.assertRaises(ValueError):
            {oid: only for oid, (only,) in receipt_map(ops, payload).items()}

    def test_there_is_exactly_one_producer_of_the_map(self) -> None:
        """ПОКА ОТВЕТОВ ДВА, ЧИСЛО РАСХОЖДЕНИЙ МЕЖДУ НИМИ НИКТО НЕ ЗНАЕТ.

        Две функции одной работы разъезжаются молча — так у этого дерева уже
        расходились `KIND_TABLE` с `REGISTRY_GAPS` (трижды) и
        `acceptance._OP_CATEGORIES` с `clash_bundle.OP_CATEGORY` (три
        расхождения вместо одного предполагаемого). Здесь это пришпилено
        структурно: `receipt_map` обязан строиться НА `element_addresses`, а не
        читать реестр вторым проходом."""

        import inspect

        from kukai.ir import address as _mod

        source = inspect.getsource(_mod.receipt_map)
        self.assertIn("element_addresses(", source,
                      "второй проход по реестру = второй производитель карты")
        self.assertFalse(hasattr(_mod, "op_to_element_ids"),
                         "плоская форма вернулась — их снова две")
        self.assertNotIn("op_to_element_ids", _mod.__all__)


class TheCreatedKeysAreTheRegistrys(unittest.TestCase):

    def test_the_four_network_ops_are_no_longer_lost(self) -> None:
        """Замер 15.08: `segment_ids` несут ЧЕТЫРЕ созидающих опа."""

        keys = created_identity_fields()
        self.assertIn("segment_ids", keys)
        network = [n for n, o in spec.OPS.items()
                   if o.result.identity_field == "segment_ids"]
        self.assertEqual(len(network), 4, sorted(network))
        got = created_ledger.extract_created({"r1": {"segment_ids": [21, 22]}})
        self.assertEqual(got, {"r1": ["21", "22"]})

    def test_the_hand_written_names_are_gone(self) -> None:
        """`ids` и `created_ids` не объявлены НИ ОДНИМ опом — угаданные имена."""

        self.assertNotIn("ids", created_identity_fields())
        self.assertNotIn("created_ids", created_identity_fields())

    def test_created_and_never_created_partition_the_registry(self) -> None:
        """РАЗБИЕНИЕ: без остатка И без пересечения. Второе поймало ошибку автора."""

        created = set(created_identity_fields())
        never = set(identity_field_reasons())
        every = {o.result.identity_field for o in spec.OPS.values()
                 if o.result.identity_field}
        self.assertEqual(created | never, every, "остаток есть — реестр не покрыт")
        self.assertFalse(created & never, "пересечение есть — это не разбиение")
        for field, reason in identity_field_reasons().items():
            self.assertTrue(reason.strip(), f"{field} исключён без причины")

    def test_the_ratchet_can_actually_fail(self) -> None:
        """Сверка, которая не умеет покраснеть, сторожит ноль.

        Прежний тест этого файла-предшественника проверял `"id" in ("id",…)` —
        константу. Здесь ломается сам предмет: поле, выброшенное из реестра,
        обязано исчезнуть и из ключей.
        """

        keys_before = created_identity_fields()
        self.assertIn("segment_ids", keys_before)
        victim = next(o for o in spec.OPS.values()
                      if o.result.identity_field == "segment_ids")
        import dataclasses
        from kukai.ir.registry_base import IdentityCardinality, ResultSpec
        patched = dict(spec.OPS)
        for name, op in list(patched.items()):
            if op.result.identity_field == "segment_ids":
                patched[name] = dataclasses.replace(
                    op, result=ResultSpec(IdentityCardinality.ONE, "id"))
        original = spec.OPS
        try:
            spec.OPS = patched                       # type: ignore[misc]
            created_identity_fields.cache_clear()
            self.assertNotIn("segment_ids", created_identity_fields(),
                             "ключи не следуют за реестром — вывод фиктивен")
        finally:
            spec.OPS = original                      # type: ignore[misc]
            created_identity_fields.cache_clear()
        self.assertIn("segment_ids", created_identity_fields())
        self.assertIsNotNone(victim)


class TheAddressRefusesToCrossSpaces(unittest.TestCase):

    def test_comparing_two_spaces_refuses_instead_of_returning_false(self) -> None:
        op = Address(AddressSpace.OP_ID, "w1")
        el = Address(AddressSpace.ELEMENT_ID, "9001")
        with self.assertRaises(AddressSpaceError):
            op.same_as(el)
        self.assertTrue(op.same_as(Address(AddressSpace.OP_ID, "w1")))
        self.assertFalse(op.same_as(Address(AddressSpace.OP_ID, "w2")))

    def test_containers_still_work(self) -> None:
        """`__eq__` намеренно структурное: иначе `set`/`dict` падали бы на коллизии."""

        pool = {Address(AddressSpace.OP_ID, "w1"),
                Address(AddressSpace.ELEMENT_ID, "w1")}
        self.assertEqual(len(pool), 2)

    def test_an_empty_set_has_no_space(self) -> None:
        with self.assertRaises(AddressSpaceError):
            assert_one_space([])
        with self.assertRaises(AddressSpaceError):
            assert_one_space([Address(AddressSpace.OP_ID, "w1"),
                              Address(AddressSpace.ELEMENT_ID, "9001")])
        self.assertIs(assert_one_space([Address(AddressSpace.OP_ID, "w1")]),
                      AddressSpace.OP_ID)


class TheComparatorSpeaksInsteadOfBeingSilent(unittest.TestCase):

    def test_without_a_translation_the_empty_intersection_is_NAMED(self) -> None:
        """Главная находка волны: раньше здесь был пустой список."""

        program = _model(_walls("w"))
        parse = _model(_walls("900"))
        self.assertTrue(program.walls and parse.walls, "контроль вырожден")
        out = design_check.compare_geometry(parse, program)
        self.assertEqual(len(out), 1, [d.subject for d in out])
        self.assertEqual(out[0].kind, "адрес")
        self.assertIn("ПУСТО", out[0].cause)

    def test_with_the_translation_the_comparison_actually_happens(self) -> None:
        program = _model(_walls("w"))
        parse = _model(_walls("900"))
        translate = {f"w{i}": f"900{i}" for i in range(0, 5)}
        out = design_check.compare_geometry(parse, program, translate=translate)
        self.assertFalse([d for d in out if d.kind == "адрес"],
                         "перевод дан, а пространства всё ещё не сведены")
        self.assertTrue(any(d.subject == "ось стены" for d in out) or not out,
                        "сравнение не дошло до осей стен")

    def test_moving_one_wall_changes_the_answer(self) -> None:
        """КОНТРОЛЬ-FAIL компаратора: зелёный без акта различения не считается.

        Совпадающая геометрия обязана НЕ давать расхождения по осям; сдвинутая
        на 250 мм — обязана давать. Если оба прогона отвечают одинаково,
        компаратор зелен по построению и ничего не меряет.
        """

        translate = {f"w{i}": f"900{i}" for i in range(0, 5)}
        parse = _model(_walls("900"))

        same = design_check.compare_geometry(
            parse, _model(_walls("w")), translate=translate)
        axis_same = [d for d in same if d.subject == "ось стены"]

        moved_ops = _walls("w")
        moved_ops[1]["p1_mm"] = [5250, 0]          # одна стена длиннее на 250 мм
        moved = design_check.compare_geometry(
            parse, _model(moved_ops), translate=translate)
        axis_moved = [d for d in moved if d.subject == "ось стены"]

        self.assertFalse(axis_same, "совпадающая геометрия дала расхождение")
        self.assertTrue(axis_moved, "сдвиг на 250 мм НЕ изменил ответ — "
                                    "компаратор не меряет геометрию")
        self.assertIn("250", axis_moved[0].program)


if __name__ == "__main__":
    unittest.main()
