"""Два шва лифта, найденные картой причин 29.07 на четырёх зданиях.

ШОВ 1 — ЗАКРЕПЛЁННОЕ РАЗМЕЩЕНИЕ. ``_lift_family_fallback`` уже умеет ставить
семейство НА ХОСТ: он собирает ``hosted_ref`` и передаёт его в ``place_family``
той же перегрузкой ``NewFamilyInstance(point, symbol, HOST, level, …)``,
которой ставятся двери и окна (замерено живьём 28.07 на ЭОМ). Но двумя
строками выше стоит ворота ``placement_type is not ONE_LEVEL_BASED``, и они
отсекают ровно тот тип размещения, который и ЗНАЧИТ «закреплённое», —
``OneLevelBasedHosted``. Ветка хоста оставалась достижимой только для строки
``OneLevelBased``, у которой хост оказался случайно.

Замер 29.07 по боковым индексам (все строки — НЕ вложенные, то есть не
порождаемые родителем): ``OneLevelBasedHosted`` есть в ЧЕТЫРЁХ документах —
демо 3122, 13A-RD-AR-K2_v33 2053, SOB6.2_AR 184, SOB6.2_FAS 14 — и у ВСЕХ до
одной есть и точка, и поворот, и ``host_id``. Причина структурная: оп научился
хосту, ворота лифта не расширили.

ШОВ 2 — МОЛЧАНИЕ СТАДИИ НЕ ЕСТЬ ФАКТ ОБ ЭЛЕМЕНТЕ. §18.2 уже различает ПУСТОЙ
индекс размещений и ОТСУТСТВУЮЩИЙ: стадию, срезанную бюджетом целиком, нельзя
показывать как «нет лифтера». Но различие сделано ПРО ВЕСЬ ДОКУМЕНТ, а не про
элемент: как только стадия отработала хоть по одной строке, потолок или
лестничное ограждение — то есть элемент, который НИКОГДА не был
FamilyInstance и в индексе размещений оказаться не мог, — получает
«element is absent from the family placement side index». Это читается как
«экстрактор его потерял», тогда как правда — «для его категории у нас нет
операции».

Цена ошибки видна в самой карте причин: одна и та же популяция стоит в ней
дважды под разными именами — 28926 эл. «category is outside the … lifter
table» (слепки, где стадия не запускалась) и 8207 эл. «absent from the family
placement side index» (те же категории там, где стадия запускалась). Ранжир
причин — то, по чему решают, что строить дальше; двоение в нём дороже, чем
любой процент покрытия.

Правило поэтому обобщается с документа на ЭЛЕМЕНТ: если про этот элемент у
стадии нет НИ СТРОКИ, НИ КВИТАНЦИИ, она о нём не высказалась, и её молчание
не может быть уликой против него. Старое условие остаётся частным случаем
нового (пустой индекс без квитанций = молчание про каждый элемент).
"""
import unittest

from kukai.ir.decompile.family_placement_extract import (
    FAMILY_PLACEMENT_INDEX_SCHEMA_VERSION,
)
from kukai.ir.decompile.lift import lift_document
from kukai.ir.decompile.schema import (
    GeometryKind,
    L0Document,
    L0Element,
    LevelInfo,
    ProjectInfo,
)

_HOSTED_ROW = {
    "placement_type": "OneLevelBasedHosted",
    "placement_available": True,
    "point_mm": [1500.0, 2500.0, 3000.0],
    "family_name": "Оборудование_настенное",
    "host_id": "900",
    "host_class": "Wall",
    "group_id": None,
    "in_place": False,
    "mirrored": False,
    "hand_flipped": False,
    "facing_flipped": False,
    "hand_orientation": [0.0, 1.0, 0.0],
    "facing_orientation": [-1.0, 0.0, 0.0],
    "rotation_deg": 0.0,
    "super_component_id": None,
    "symbol_id": "77",
    "type_name": "Тип оборудования",
}


def _wall(eid="900"):
    return L0Element(
        element_id=eid, category="OST_Walls", category_ru="Стены",
        type_id="20", type_name="Стена 200",
        level_id="10", level_name="L1",
        geom_kind=GeometryKind.CURVE,
        p0_mm=(0.0, 0.0, 0.0), p1_mm=(6000.0, 0.0, 0.0),
        rotation_deg=None, bbox_min_mm=None, bbox_max_mm=None,
        host_id=None, params={})


def _equipment(eid="500", category="OST_MechanicalEquipment"):
    """Категория БЕЗ своего лифтера — общий путь размещения."""
    return L0Element(
        element_id=eid, category=category, category_ru="Оборудование",
        type_id="77", type_name="Тип оборудования",
        level_id="10", level_name="L1",
        geom_kind=GeometryKind.POINT,
        p0_mm=(1500.0, 2500.0, 3000.0), p1_mm=None, rotation_deg=0.0,
        bbox_min_mm=None, bbox_max_mm=None, host_id="900", params={})


def _ceiling(eid="700"):
    """Элемент, которого в индексе размещений быть не может, — НЕ
    FamilyInstance и БЕЗ собственного лифтера.

    ЗОНА (wave/arch, 29.07): здесь стояли «Потолки». Пример пришлось
    заменить, потому что у потолка ТЕПЕРЬ ЕСТЬ операция и лифтер
    (create_ceiling), и его атом больше не читается как «лифтера нет» — он
    читается как «нет профиля эскиза», то есть причиной со СВОЕГО пути. Это и
    есть §18.2 в более сильной форме, чем когда тест писался, но проверять на
    таком элементе «молчание стадии = no_lifter» стало нечем.

    Взята «Зона» (OST_Areas) — категория, у которой на 29.07 операции по-
    прежнему нет (на K2 это 213 элементов, самая крупная из оставшихся без
    опа). Смысл теста не изменился ни на букву: молчание стадии размещений об
    элементе — не улика против элемента. Имя функции оставлено прежним, чтобы
    диф читался как замена примера, а не как новая проверка."""
    return L0Element(
        element_id=eid, category="OST_Areas", category_ru="Зоны",
        type_id="30", type_name="Зона 100",
        level_id="10", level_name="L1",
        geom_kind=GeometryKind.BBOX_ONLY,
        p0_mm=None, p1_mm=None, rotation_deg=None,
        bbox_min_mm=(0.0, 0.0, 0.0), bbox_max_mm=(1.0, 1.0, 1.0),
        host_id=None, params={})


def _doc(*elements):
    return L0Document(
        doc_name="hosted", revit_version="2023", units="mm", change_stamp="t",
        levels=(LevelInfo("10", "L1", 1800.0),), grids=(), rooms=(),
        project_info=ProjectInfo(), elements=elements)


def _nodes(doc, index):
    return {n["source_element_id"]: n for n in lift_document(doc, None, index)}


class HostedPlacementTypeIsPlaceable(unittest.TestCase):
    """``OneLevelBasedHosted`` — это хост в опе, а не отказ."""

    def test_hosted_instance_becomes_place_family_on_its_host(self):
        nodes = _nodes(
            _doc(_wall(), _equipment()), {"500": dict(_HOSTED_ROW)})
        node = nodes["500"]
        self.assertEqual(node["kind"], "op", node["reason"]["detail"] if node["kind"] == "atom" else None)
        self.assertEqual(node["op_name"], "place_family")

    def test_hosted_instance_keeps_the_binding_to_its_host(self):
        nodes = _nodes(
            _doc(_wall(), _equipment()), {"500": dict(_HOSTED_ROW)})
        host_node = nodes["900"]
        self.assertEqual(
            nodes["500"]["params"]["host"], {"ref": host_node["_id"]},
            "закреплённое семейство обязано нести ссылку на свой хост")

    def test_hosted_instance_without_a_host_id_stays_an_atom(self):
        """Закреплённое БЕЗ хоста — потеря привязки, а не свободная точка."""
        row = dict(_HOSTED_ROW, host_id=None, host_class=None)
        nodes = _nodes(_doc(_wall(), _equipment()), {"500": row})
        node = nodes["500"]
        self.assertEqual(node["kind"], "atom")
        self.assertEqual(node["reason"]["code"], "missing_reference")

    def test_hosted_instance_whose_host_is_not_lifted_stays_an_atom(self):
        """Ставить на то, чего в программе нет, нельзя (поведение сохраняется)."""
        nodes = _nodes(_doc(_equipment()), {"500": dict(_HOSTED_ROW)})
        node = nodes["500"]
        self.assertEqual(node["kind"], "atom")
        self.assertEqual(node["reason"]["code"], "missing_reference")

    def test_unhosted_one_level_based_is_untouched(self):
        row = dict(_HOSTED_ROW, placement_type="OneLevelBased",
                   host_id=None, host_class=None)
        node = _nodes(_doc(_equipment()), {"500": row})["500"]
        self.assertEqual(node["kind"], "op", node["reason"]["detail"] if node["kind"] == "atom" else None)
        self.assertEqual(node["op_name"], "place_family")

    def test_placement_types_that_are_not_point_placed_still_refuse(self):
        """Ворота сужаются, а не исчезают: CurveDrivenStructural не точка."""
        row = dict(_HOSTED_ROW, placement_type="CurveDrivenStructural")
        node = _nodes(_doc(_wall(), _equipment()), {"500": row})["500"]
        self.assertEqual(node["kind"], "atom")
        self.assertEqual(node["reason"]["code"], "unsupported_forward_signature")


class StageSilenceIsNotEvidenceAboutTheElement(unittest.TestCase):
    """Про потолок стадия размещений не высказывалась — значит, нет лифтера."""

    def _envelope(self, index, failures):
        return {
            "schema_version": FAMILY_PLACEMENT_INDEX_SCHEMA_VERSION,
            "family_placement_index": index,
            "failures": failures,
        }

    def test_element_the_stage_never_mentioned_reads_as_no_lifter(self):
        envelope = self._envelope({"500": dict(_HOSTED_ROW)}, [])
        node = _nodes(
            _doc(_wall(), _equipment(), _ceiling()), envelope)["700"]
        self.assertEqual(node["kind"], "atom")
        self.assertEqual(
            node["reason"]["code"], "no_lifter",
            "молчание стадии об элементе — не улика против элемента")

    def test_element_with_a_receipt_still_reports_the_receipt(self):
        """Квитанция есть — причина обязана прийти ИЗ НЕЁ (§18.2/M5)."""
        envelope = self._envelope(
            {"500": dict(_HOSTED_ROW)},
            [{"element_id": "700", "reason": "not a FamilyInstance: Area",
              "typed_reason": "element_kind_mismatch", "elapsed_ms": None}])
        node = _nodes(
            _doc(_wall(), _equipment(), _ceiling()), envelope)["700"]
        self.assertEqual(node["kind"], "atom")
        self.assertEqual(node["reason"]["code"], "placement_kind_unknown")
        self.assertIn("element_kind_mismatch", node["reason"]["detail"])

    def test_stage_that_never_ran_keeps_its_old_answer(self):
        """Старое условие §18.2 — частный случай нового, не исключение."""
        node = _nodes(_doc(_ceiling()), None)["700"]
        self.assertEqual(node["kind"], "atom")
        self.assertEqual(node["reason"]["code"], "no_lifter")


if __name__ == "__main__":
    unittest.main()
