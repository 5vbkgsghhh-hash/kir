"""Контракт «разворот → L1»: что материализатор чинит САМ, а что обязан разворот.

ЗАЧЕМ. Решение директора 12.08: разворот замысла целится в L1, и тогда
чанкование, ref-замыкание и топосорт «достаются даром» от `materialize`. Даром —
это ГИПОТЕЗА, пока не назван список законов и по каждому не показано, чинится он
или пропускается. Ниже замер, а не прочтение докстрингов: строится L1,
НАРУШАЮЩИЙ закон, и смотрится исход.

    закон Д5 / обязанность          кто держит         как проверено
    ------------------------------  -----------------  --------------------------
    (d) порядок, топосорт Кана      ДАРОМ              уровень подан ПОСЛЕДНИМ —
                                                       эмитирован ПЕРВЫМ
    (a) ref-атомарность             ДАРОМ              хозяин и зависимый всегда
                                                       в одной программе
    (c) размер чанка                ДАРОМ, НО СМ.      1000 стен на СУЩЕСТВУЮЩЕМ
                                    ПОТОЛОК НИЖЕ       уровне → 4 программы×250
    висячая ссылка                  СХЕМА, ГРОМКО      `dangling L1 node
                                                       reference` ДО materialize
    двойной адрес                   СХЕМА, ГРОМКО      `duplicate source ids`
    происхождение `_id`             СХЕМА, ГРОМКО      `op _id is not
                                                       deterministic for its source`
    тип/символ без ElementId        РАЗВОРОТ           единственная дыра, О12

**ГЛАВНАЯ НАХОДКА, И ОНА ПРОТИВ ПОСЫЛКИ «ЧАНКОВАНИЕ ДАРОМ»: ДАТУМ, СОЗДАННЫЙ
ЭТОЙ ЖЕ ПРОГРАММОЙ, СКЛЕИВАЕТ ВСЁ ЗДАНИЕ В ОДНУ НЕДЕЛИМУЮ ЕДИНИЦУ.** Замер
12.08.2026, ровная граница:

    уровень СОЗДАЁТСЯ здесь же:   300 опов → 1 программа [300]
                                  301 оп  → ОТКАЗ MaterializeError
        «host-atomic group exceeds compiler bulk limit: 301 > 300
         (host source S-LEVEL)»

    уровень УЖЕ ЕСТЬ в документе: 1000 стен → 4 программы [250,250,250,250]

    два созданных уровня × 200 стен (402 опа) → 2 программы [201, 201]

Причина — сам закон Д5a, и он работает правильно: неделимая единица есть СВЯЗНАЯ
КОМПОНЕНТА всего графа ссылок. Каждая стена ссылается на уровень ⇒ здание есть
ОДНА компонента ⇒ она обязана уместиться в `MAX_BULK_OPS = 300`. Обратный ход
этого никогда не видел, потому что там датумы ВНЕШНИЕ: `_translate_reference`
переводит существующий уровень в `by=element_id`, а тот, как сказано в
докстринге `_build_host_groups`, РЕБРА НЕ СОЗДАЁТ. Мелкие компоненты обратного
хода — свойство того, что здание уже построено, а не свойство чанкования.

**СЛЕДСТВИЕ ЧИСЛОМ, И ОНО ПРО МИССИЮ.** Здание, авторимое с нуля, вмещает не
более **300 опов на каждый созданный датум** (299 + сам датум). Башня в ~30 000
опов, авторимая с нуля, требует ≥100 созданных уровней — либо датумы обязаны уже
существовать в документе. Разбиение по датумам работает (два уровня дали две
программы), так что потолок не абсолютный, а «на компоненту».

**ЭТО НЕ ДЫРА В КОРРЕКТНОСТИ, А ПОТОЛОК СПОСОБНОСТИ, И РАЗНИЦА ВАЖНА.** Отказ
ГРОМКИЙ, типизированный и называет виновный датум по имени. Тихо неверного здесь
нет; есть именованная граница, которую надо знать ДО того, как кто-то начнёт
строить по решению «разворот целится в L1».

**И ЛЕКАРСТВО УЖЕ СТОИТ — ЭТО ВАЖНЕЕ САМОЙ БОЛЕЗНИ.** Тот же вход, тот же
уровень, те же ссылки, разница в одном флаге:

    include_datums=True   (уровень СОЗДАЁТСЯ)  → ОТКАЗ 401 > 300
    include_datums=False  (уровень ПИНИТСЯ)    → 2 программы [250, 150]
                                                 level: {"by": "element_id",
                                                         "value": 778899}

Ссылка по `element_id` ребра НЕ создаёт, компонента распадается, закон Д5a не
тронут ни строкой. Механизм работает на каждом обратном прогоне. **Дыра ровно
одна и она узкая: сегодня «внешний» и «созданный нами» ВЗАИМОИСКЛЮЧАЮЩИ** —
датум становится внешним тем, что его НЕ СОЗДАЮТ. Чтобы потолок исчез, нужен
датум, который создан И чей ElementId известен к заземлению следующего чанка,
то есть АДРЕС, ПЕРЕЖИВАЮЩИЙ ПРОГРАММУ.

И режим для этого уже назван: **`mode="fresh_document"` — крючок B4, назван в
трёх местах кода, отказывает, и на отказ есть ровно один тест.** Это ИМЕНОВАННАЯ
дыра, а не неизвестность; проектировать «здание вместе с документом» заново не
надо.

РОД ЭТОГО СПИСКА: **ЗАКРЫТЫЙ, НО НЕ ПОЛНЫЙ.** Проверены законы, названные в
докстринге `materialize` (Д5 a/c/d) плюс три обязанности схемы. Законы «комнаты
в хвост» и «лестница соло» здесь НЕ проверены — им нужен L1 с комнатами и
лестницами, и их отсутствие в таблице означает «не знаем», а не «даром».
"""
from __future__ import annotations

import unittest

from kukai.ir.decompile.l1_schema import (
    L1SchemaError, stable_l1_id, validate_l1_nodes)
from kukai.ir.decompile.materialize import (
    MAX_BULK_OPS, MaterializeError, leaves_to_program)

LEVEL_SRC = "S-LEVEL"
LEVEL_ID = stable_l1_id("op", LEVEL_SRC)
#: Уровень, уже стоящий в документе: селектор с целым ElementId. Такая ссылка
#: переводится в `by=element_id` и ребра в графе НЕ создаёт.
EXISTING_LEVEL = {"by": "name", "value": "Этаж 1", "_id": "987654"}


def _node(op_name, source_id, params, level_name=None):
    return {
        "kind": "op", "_id": stable_l1_id("op", source_id),
        "source_element_id": source_id, "level_name": level_name,
        "anchor_mm": None, "type_name": "—",
        "op_name": op_name, "params": params,
    }


def _level(source_id=LEVEL_SRC, name="Этаж 1", elev_mm=0):
    return _node("create_level", source_id, {"name": name, "elev_mm": elev_mm})


def _wall(index, level_selector):
    return _node("create_wall", f"S-WALL-{index}", {
        "p0_mm": [index * 5000, 0], "p1_mm": [index * 5000 + 4000, 0],
        "height_mm": 3000, "level": level_selector,
        "type": {"by": "name", "value": "Стена 200", "_id": "12345"},
    }, level_name="Этаж 1")


def _door(index, host_src):
    return _node("create_door", f"S-DOOR-{index}", {
        "host": {"ref": stable_l1_id("op", host_src)},
        "offset_mm": 2000,
        "symbol": {"by": "name", "value": "Дверь 900", "_id": "22222"},
    }, level_name="Этаж 1")


def _materialize(leaves):
    return leaves_to_program(validate_l1_nodes(leaves), include_datums=True)


def _sizes(result):
    return [len(program["ops"]) for program in result.programs]


def _placement(result):
    return {op["id"]: index
            for index, program in enumerate(result.programs)
            for op in program["ops"]}


class TheseLawsComeFree(unittest.TestCase):
    """Разворот может подавать L1 в любом порядке и не думать о них."""

    def test_order_is_repaired_by_the_toposort(self):
        """Закон (d): уровень подан последним — эмитирован первым."""
        result = _materialize([_wall(1, {"ref": LEVEL_ID}),
                               _wall(2, {"ref": LEVEL_ID}),
                               _level()])
        order = [op["id"] for program in result.programs
                 for op in program["ops"]]
        self.assertEqual(order[0], "e" + LEVEL_SRC,
                         "порядок сохранён как подан — топосорт не сработал")

    def test_a_host_and_its_dependent_never_split(self):
        """Закон (a): дверь и её стена в одной программе даже на границе пачки."""
        leaves = ([_wall(i, EXISTING_LEVEL) for i in range(400)]
                  + [_door(0, "S-WALL-399")])
        where = _placement(_materialize(leaves))
        self.assertIn("eS-DOOR-0", where, "дверь не эмитирована вовсе")
        self.assertEqual(
            where["eS-DOOR-0"], where["eS-WALL-399"],
            "хозяин и зависимый разъехались по программам — KIR-L003")

    def test_chunking_is_free_when_the_datum_is_external(self):
        """Закон (c): 1000 стен на СУЩЕСТВУЮЩЕМ уровне делятся сами."""
        result = _materialize([_wall(i, EXISTING_LEVEL) for i in range(1000)])
        sizes = _sizes(result)
        self.assertGreater(len(sizes), 1, "не разделилось вовсе")
        self.assertLessEqual(max(sizes), MAX_BULK_OPS)


class TheSchemaOwnsTheseLoudly(unittest.TestCase):
    """Разворот обязан, но ошибиться тихо не может: отказ приходит до эмиссии."""

    def test_a_dangling_ref_is_refused_before_materialize(self):
        with self.assertRaises(L1SchemaError) as ctx:
            _materialize([_level(), _wall(1, {"ref": LEVEL_ID}),
                          _door(0, "S-WALL-КОТОРОЙ-НЕТ")])
        self.assertIn("dangling", str(ctx.exception))

    def test_a_duplicate_address_is_refused(self):
        with self.assertRaises(L1SchemaError):
            _materialize([_level(), _wall(1, {"ref": LEVEL_ID}),
                          _wall(1, {"ref": LEVEL_ID})])

    def test_an_id_not_derived_from_its_source_is_refused(self):
        forged = _wall(2, EXISTING_LEVEL)
        forged["_id"] = "не-тот-хеш"
        with self.assertRaises(L1SchemaError):
            _materialize([forged])


class ADatumCreatedInProgramIsACutVertex(unittest.TestCase):
    """Потолок авторства: чанкование даром ТОЛЬКО при внешних датумах.

    Здесь и живёт цена решения «разворот целится в L1». Отказ громкий и
    называет датум — тихо неверного нет, есть именованная граница.
    """

    def test_the_ceiling_is_exactly_the_compiler_bulk_limit(self):
        """300 опов на созданный уровень проходят, 301 — отказ."""
        at_limit = [_level()] + [
            _wall(i, {"ref": LEVEL_ID}) for i in range(MAX_BULK_OPS - 1)]
        self.assertEqual(_sizes(_materialize(at_limit)), [MAX_BULK_OPS])

        over = at_limit + [_wall(MAX_BULK_OPS - 1, {"ref": LEVEL_ID})]
        with self.assertRaises(MaterializeError) as ctx:
            _materialize(over)
        message = str(ctx.exception)
        self.assertIn("exceeds compiler bulk limit", message)
        self.assertIn(LEVEL_SRC, message,
                      "отказ не называет виновный датум — граница безымянна")

    def test_the_same_ops_pass_when_the_datum_is_external(self):
        """Контроль: те же опы и то же число — но датум из документа.

        Без этой пары «301 отказ» неотличим от «301 оп вообще нельзя», и
        потолок читался бы как свойство размера, а не связности.
        """
        external = [_wall(i, EXISTING_LEVEL) for i in range(MAX_BULK_OPS)]
        sizes = _sizes(_materialize(external))
        self.assertEqual(sum(sizes), MAX_BULK_OPS)
        self.assertGreater(len(sizes), 1)

    def test_the_cure_already_exists_and_is_one_flag_away(self):
        """ТОТ ЖЕ вход распадается, если датум пинится по ElementId.

        Самое ценное в этом файле, потому что называет ЛЕКАРСТВО, а не только
        болезнь. 401 лист, тот же уровень, те же ссылки:

            include_datums=True   (уровень СОЗДАЁТСЯ)  -> ОТКАЗ 401 > 300
            include_datums=False  (уровень ПИНИТСЯ)    -> 2 программы [250, 150]

        Во втором случае ссылка переведена в ``{"by": "element_id", "value":
        778899}`` — а такая ссылка ребра в графе НЕ создаёт, компонента
        распадается, и закон Д5a не тронут ни строкой.

        Значит механизм, растворяющий компоненту, УЖЕ СТОИТ и работает на
        каждом обратном прогоне. Дыра ровно одна и она узкая: сегодня
        «внешний» и «созданный нами» ВЗАИМОИСКЛЮЧАЮЩИ — датум становится
        внешним тем, что его НЕ СОЗДАЮТ. Чтобы потолок исчез, нужен датум,
        который создан И чей ElementId известен к заземлению следующего чанка.
        """
        numeric_src = "778899"          # источник как у настоящего элемента
        numeric_id = stable_l1_id("op", numeric_src)
        leaves = [_level(numeric_src)] + [
            _wall(i, {"ref": numeric_id}) for i in range(MAX_BULK_OPS + 100)]

        with self.assertRaises(MaterializeError):
            leaves_to_program(validate_l1_nodes(leaves), include_datums=True)

        pinned = leaves_to_program(
            validate_l1_nodes(leaves), include_datums=False)
        self.assertGreater(len(pinned.programs), 1)
        self.assertEqual(
            pinned.programs[0]["ops"][0]["level"],
            {"by": "element_id", "value": int(numeric_src)},
            "ссылка не переведена в by=element_id — лекарство не то")

    def test_the_mode_the_mission_needs_is_named_and_refused(self):
        """`fresh_document` — ИМЕНОВАННАЯ дыра, а не неизвестность.

        Режим назван в трёх местах кода и отказывает. Записано здесь, чтобы
        «здание вместе с документом» не проектировали заново: у него уже есть
        имя, крючок B4 и ровно один тест, утверждающий отказ.
        """
        with self.assertRaises(MaterializeError) as ctx:
            leaves_to_program([], mode="fresh_document")
        self.assertIn("fresh_document", str(ctx.exception))

    def test_two_created_datums_split_the_building(self):
        """Потолок «на компоненту», а не абсолютный: 402 опа → две программы."""
        half = 200
        second = "S-LEVEL-2"
        leaves = [_level(), _level(second, "Этаж 2", 3000)]
        leaves += [_wall(i, {"ref": LEVEL_ID}) for i in range(half)]
        leaves += [_wall(1000 + i, {"ref": stable_l1_id("op", second)})
                   for i in range(half)]
        sizes = _sizes(_materialize(leaves))
        self.assertEqual(len(sizes), 2)
        self.assertLessEqual(max(sizes), MAX_BULK_OPS)


if __name__ == "__main__":
    unittest.main()
