"""HAB002 ВЫШЕЛ ИЗ БЕЗУСЛОВНОГО СНЯТИЯ — и этот файл держит основание.

ЧТО БЫЛО. Четыре правила (HAB002/003/004/042) снимались ВСЕГДА с одной причиной:
оракул квартиры измерен 03.08 и разгромен — «по составу жилища 0%, 415 «квартир» из
469 — одна комната». Правило на оракуле с нулевой точностью обязано молчать.

ЧТО ЗАМЕРЕНО 15.08.2026, и почему это меняет решение. `derive_apartments` НЕ ПРАВЛЕН
ни одной строкой. На эталоне генератора, где истина известна ПО ПОСТРОЕНИЮ
(`generator.building` штампует `apartment_id`), он даёт **20 квартир из 20 с точным
составом — 100%**. Значит «0%» есть свойство ВХОДА, а не алгоритма.

Входов этих два РАЗНЫХ рода, и смешивать их нельзя:

* **нежилое здание.** `sob62_r23_v5` — детский сад: «Групповая ячейка», «Буфетная»,
  «ПУИ», «ВРУ ДОО». Девять «квартир» — это КАБИНЕТЫ: лексикон шлёт «кабинет» в
  ЖИЛАЯ, и врач получает жилище. Верный ответ там не «12 квартир», а «здесь не жильё»;
* **открытая планировка.** `k2_ar_rd_v15` — настоящий жилой дом, но 614 одиночек это
  «Жилая комната N», а 259 — «Кухня-ниша N» ОТДЕЛЬНО: у ниши нет ДВЕРИ в комнату, а
  вывод стоит на дверях.

Отсюда предусловие `apartments_are_dwellings` (`checker/engine.py`): жилище имеет
кухню либо санузел. Это ОПРЕДЕЛЕНИЕ жилища, а не подобранный порог — компонента без
обоих есть артефакт вывода. Замер предиката на трёх входах: эталон 0 не-жилищ из 20
(держит) · детсад 11 из 12 (не держит) · башня 621 из 995 (не держит).

🔴 ПОЧЕМУ ОСТАЛЬНЫЕ ТРИ ОСТАЛИСЬ СНЯТЫМИ. Предусловие делает доверяемой ТОПОЛОГИЮ
компоненты — этого хватает HAB002 («не квартира-в-квартиру, ровно один вход») и НЕ
хватает остальным: HAB003 нужен путь к земле (лестницы + уровень земли), HAB004 —
прихожая внутри квартиры, HAB042 — замкнутость оболочки по стенам и проёмам. Каждое
из этих трёх стоит на СВОЁМ входе, и ни один этим замером не покрыт.

РОД ЭТОГО ФАЙЛА: контроль в ОБЕ стороны. Правило, которое не может сработать, и
правило, которое срабатывает всегда, одинаково бесполезны, и зелёный тест не
различает их без второй половины.
"""
from __future__ import annotations

import copy
import os
import unittest

os.environ.setdefault("KUKAI_CHECKER_V2", "1")

from kukai.ir.design_check import (BuildWitness, ModelSource, check_design,
                                   _APARTMENT_ORACLE_RULES, _DESIGN_PRECONDITIONS)
from kukai.modeling.checker.engine import PRECONDITIONS
from kukai.modeling.checker.graph import build_graph, derive_apartments
from kukai.modeling.checker.spatial_model import RoomFunction, SpatialModel
from kukai.modeling.generator.building import building


def _witness(building_id: str, model: SpatialModel) -> BuildWitness:
    witness = BuildWitness(source=ModelSource.PARSE, building_id=building_id,
                           doc_name=building_id)
    witness.counts.update({"windows": len(model.windows),
                           "stairs": len(model.stairs)})
    return witness


def _outcome(model: SpatialModel, building_id: str, rule_id: str = "HAB002"):
    verdict = check_design(model, _witness(building_id, model))
    for row in verdict.report.coverage.outcomes:
        if row.rule_id == rule_id:
            fired = [v for v in (verdict.report.blocking + verdict.report.warnings)
                     if v.rule_id == rule_id]
            return row, fired
    raise AssertionError(f"{rule_id} отсутствует в покрытии — правило исчезло")


def _reference(n_floors: int = 5, n_apartments: int = 4) -> dict:
    return building(n_floors=n_floors, n_apartments=n_apartments)


class ОракулТоченНаЗдоровомВходе(unittest.TestCase):
    """Замер, на котором стоит всё решение: 0% был про ВХОД, не про алгоритм."""

    def test_состав_квартир_совпадает_точь_в_точь(self):
        model = SpatialModel.model_validate(_reference())
        truth: dict[str, set[str]] = {}
        for room in model.rooms:
            if room.apartment_id:
                truth.setdefault(room.apartment_id, set()).add(room.id)
        self.assertGreaterEqual(len(truth), 2, "контроль вырожден: квартир меньше двух")

        derived = derive_apartments(model, build_graph(model))
        truth_sets = {frozenset(ids) for ids in truth.values()}
        exact = sum(1 for apt in derived if frozenset(apt.room_ids) in truth_sets)
        self.assertEqual(exact, len(truth),
                         "оракул обязан быть точен на входе, где истина известна")


class ПредусловиеРазличаетВход(unittest.TestCase):

    def test_на_эталоне_держит(self):
        model = SpatialModel.model_validate(_reference())
        apartments = derive_apartments(model, build_graph(model))
        ctx = _Ctx(model, apartments)
        self.assertTrue(PRECONDITIONS["apartments_are_dwellings"][0](ctx))

    def test_компонента_без_кухни_и_санузла_не_жилище(self):
        """КОНТРОЛЬ-FAIL предусловия: без него оно зелено по построению."""
        model = SpatialModel.model_validate(_reference())
        apartments = derive_apartments(model, build_graph(model))
        # одну комнату квартиры оставляем жилой, остальные обезличиваем
        victim = apartments[0]
        rooms = []
        for room in model.rooms:
            if room.id in victim.room_ids:
                rooms.append(room.model_copy(update={"function": RoomFunction.ЖИЛАЯ}))
            else:
                rooms.append(room)
        broken = model.model_copy(update={"rooms": rooms})
        ctx = _Ctx(broken, derive_apartments(broken, build_graph(broken)))
        self.assertFalse(PRECONDITIONS["apartments_are_dwellings"][0](ctx),
                         "квартира без кухни и санузла обязана уронить предусловие")

    def test_причина_названа_словами(self):
        reason = PRECONDITIONS["apartments_are_dwellings"][1]
        for token in ("кухни", "санузла", "ДВЕРЯМ"):
            self.assertIn(token, reason,
                          "причина обязана называть механизм, а не только исход")


class ПравилоСудитИОбеСтороныПроверены(unittest.TestCase):
    """Без ОБЕИХ половин это не правило, а шум."""

    def test_на_здоровом_эталоне_правило_РАБОТАЕТ_и_молчит(self):
        model = SpatialModel.model_validate(_reference())
        row, fired = _outcome(model, "gen_healthy")
        self.assertEqual(row.status.name, "EVALUATED",
                         "правило обязано ВЫПОЛНИТЬСЯ, а не быть снятым")
        self.assertEqual(fired, [], "на здоровом здании нарушений быть не должно")

    def test_на_сломанном_эталоне_правило_СРАБАТЫВАЕТ(self):
        raw = copy.deepcopy(_reference())
        halls = [r["id"] for r in raw["rooms"]
                 if r["id"].endswith("_hall") and r["level_id"] == "L1"]
        self.assertGreaterEqual(len(halls), 2, "контроль вырожден: соединять нечего")
        # дверь между прихожими ДВУХ квартир: одна компонента с ДВУМЯ входами
        raw["doors"].append({
            "id": "BREAK", "level_id": "L1", "location": [0.0, 0.0],
            "width_mm": 900.0, "from_room_id": halls[0], "to_room_id": halls[1],
            "is_exterior": False})
        row, fired = _outcome(SpatialModel.model_validate(raw), "gen_broken")
        self.assertEqual(row.status.name, "EVALUATED")
        self.assertEqual(len(fired), 1,
                         "квартира-в-квартиру обязана дать РОВНО одно нарушение")


class ГраницаОсталасьГраницей(unittest.TestCase):

    def test_три_правила_по_прежнему_сняты_безусловно(self):
        self.assertEqual(tuple(_APARTMENT_ORACLE_RULES),
                         ("HAB003", "HAB004", "HAB042"),
                         "снятие остальных трёх этим замером НЕ покрыто")

    def test_hab002_стоит_на_ТРЁХ_предусловиях(self):
        """Третье добавлено ПО КРАСНОМУ: правило о входах молчит без входа."""
        self.assertEqual(_DESIGN_PRECONDITIONS["HAB002"],
                         ["apartments_derived", "apartments_are_dwellings",
                          "building_entrance_known"])


class _Ctx:
    """Минимальный контекст предусловия: ровно то, что читают его лямбды."""

    def __init__(self, model: SpatialModel, apartments) -> None:
        self.model = model
        self.apartments = apartments
        self.drep = None


if __name__ == "__main__":
    unittest.main()
