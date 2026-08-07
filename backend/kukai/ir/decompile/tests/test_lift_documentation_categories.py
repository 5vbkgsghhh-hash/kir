"""Рабочая документация: что стало выразимо, а что честно отказалось (29.07).

ПОВОД. Таблица чтения выросла 54 → 73 категории (ee32fb82), и в неё вошло
содержание РД замеренной башни: 13 905 размеров, 11 585 марок помещений,
2 697 примечаний, 3 046 элементов узлов, 4 479 телефонных устройств и прочее —
60 587 элементов. Волна была про ЧТЕНИЕ и честно сказала, что покрытие не
сдвинет: лифтов нет, всё станет атомами. Эта волна разбирала, что из этого
можно поднять, и ответ оказался НЕ тем, которого ждали.

ГЛАВНАЯ РАЗВИЛКА, РЕШЁННАЯ ЗДЕСЬ. Размер, марка и примечание ссылаются на
ДРУГИЕ элементы и живут в КОНКРЕТНОМ ВИДЕ. Операции под них есть в реестре с
28.07 (ops_annotation.py), но их обязательные входы — `in_view`, `refs`,
`target`, `at`/`line_at`, `content` — в замороженной строке L0 1.0
отсутствуют КАК ПОЛЯ. Поэтому лифтер здесь не «не написан», а не может быть
написан из этого чтения: любой такой лифтер обязан был бы ВЫДУМАТЬ источник —
привязать размер к какому-нибудь элементу и поставить марку примерно туда.
Это прошло бы схему L1 и показалось бы покрытием. Закон §18.1 запрещает
ровно это, и цена подстановки не процент, а доверие к числу.

Отсюда работа волны — не лифтер, а ВЕРНОЕ ИМЯ ОТКАЗА. До неё все эти элементы
получали `no_lifter` («category is outside the exact Part 5 lifter table»),
что в ранжире причин читается «операции нет, напиши её», — и следующий пошёл
бы писать create_dimension, который уже написан. Новый код
`source_contract_gap` посылает в ЧТЕНИЕ и называет поимённо, что начать
снимать. Ровно то же различие 29.07 уже разводили для стадии размещений
(«молчание стадии не есть факт об элементе»).

ЧТО ДЕЙСТВИТЕЛЬНО ПОДНИМАЕТСЯ. Телефонные устройства — модельные семейства, и
после того как лид дописал их в белый список бокового индекса размещений (тот
же коммит), они поднимаются `place_family` БЕЗ ЕДИНОЙ ПРАВКИ ЛИФТА. Тест
ниже это закрепляет: путь существует и не должен сломаться молча.

ЧТО ОТКАЗАЛОСЬ И ПОЧЕМУ ДИАГНОЗ ПРИШЛОСЬ ЧИНИТЬ. Элементы узлов отказывали
текстом «place_family ставит только точечные размещения, а у этого экземпляра
'ViewBased'». Это неверный диагноз: ViewBased — ЭТО ТОЧКА, и Autodesk пишет
дословно "The family is view-specific (e.g. a detail annotation)". Точка у
элемента узла есть и лежит в боковом индексе; недостаёт ВИДА, которого у
place_family нет в параметрах вовсе. Старый текст посылал искать другую
геометрию — то есть в сторону, где ничего нет.
"""
import unittest
from dataclasses import fields

from kukai.ir import spec
from kukai.ir.decompile.family_placement_extract import (
    FAMILY_PLACEMENT_INDEX_SCHEMA_VERSION,
)
from kukai.ir.decompile.l1_schema import AtomReason, FidelityReason
from kukai.ir.decompile.lift import (
    _L0_HAS_NO_SOURCE_FOR,
    _OPS_WITHOUT_L0_INPUTS,
    LIFTER_TABLE,
    lift_document,
)
from kukai.ir.decompile.schema import (
    GeometryKind,
    L0Document,
    L0Element,
    LevelInfo,
    ProjectInfo,
)


def _annotation(eid, category, type_name="Тип аннотации"):
    """Строка аннотации ровно такая, какой её отдаёт эмиссия.

    Без уровня (у аннотации его нет), без хоста (она не FamilyInstance), с
    габаритом вместо точки и с ПУСТЫМИ params: `__PutParams` — закрытый белый
    список геометрических BuiltInParameter, и ни текста, ни вида, ни ссылок в
    нём нет.
    """

    return L0Element(
        element_id=eid, category=category, category_ru="",
        type_id="9001", type_name=type_name,
        level_id=None, level_name=None,
        geom_kind=GeometryKind.BBOX_ONLY,
        p0_mm=None, p1_mm=None, rotation_deg=None,
        bbox_min_mm=(0.0, 0.0, 0.0), bbox_max_mm=(100.0, 100.0, 0.0),
        host_id=None, params={})


def _instance(eid, category, level=True):
    return L0Element(
        element_id=eid, category=category, category_ru="",
        type_id="9002", type_name="Тип экземпляра",
        level_id="10" if level else None,
        level_name="L1" if level else None,
        geom_kind=GeometryKind.POINT,
        p0_mm=(1500.0, 2500.0, 3000.0), p1_mm=None, rotation_deg=0.0,
        bbox_min_mm=None, bbox_max_mm=None, host_id=None, params={})


def _row(placement_type, **over):
    row = {
        "placement_type": placement_type,
        "placement_available": True,
        "point_mm": [1500.0, 2500.0, 3000.0],
        "family_name": "Семейство",
        "host_id": None,
        "host_class": None,
        "group_id": None,
        "in_place": False,
        "mirrored": False,
        "hand_flipped": False,
        "facing_flipped": False,
        "hand_orientation": [0.0, 1.0, 0.0],
        "facing_orientation": [-1.0, 0.0, 0.0],
        "rotation_deg": 0.0,
        "super_component_id": None,
        "symbol_id": "9002",
        "type_name": "Тип экземпляра",
    }
    row.update(over)
    return row


def _doc(*elements):
    return L0Document(
        doc_name="rd", revit_version="2023", units="mm", change_stamp="t",
        levels=(LevelInfo("10", "L1", 0.0),), grids=(), rooms=(),
        project_info=ProjectInfo(), elements=elements)


def _nodes(document, index=None):
    envelope = None
    if index is not None:
        envelope = {
            "schema_version": FAMILY_PLACEMENT_INDEX_SCHEMA_VERSION,
            "family_placement_index": index,
            "failures": [],
        }
    return {node["source_element_id"]: node
            for node in lift_document(document, None, envelope)}


class TheRefusalsPremiseIsChecked(unittest.TestCase):
    """Отказ утверждает две вещи. Обе обязаны проверяться, а не заявляться."""

    def test_every_named_op_really_is_in_the_registry(self):
        """Первая половина: «оп ЕСТЬ». Если его нет — текст лжёт."""

        for category, op_name in sorted(_OPS_WITHOUT_L0_INPUTS.items()):
            with self.subTest(category=category):
                self.assertIn(
                    op_name, spec.OPS,
                    f"{category} обещает оп {op_name!r}, которого нет в "
                    "реестре: отказ рассказывал бы про входы несуществующей "
                    "операции")

    def test_l0_really_carries_no_field_for_those_inputs(self):
        """Вторая половина: «входов НЕТ В ЧТЕНИИ».

        Проверяется СТРУКТУРНО, по полям замороженной строки, а не списком
        строк: если следующая волна начнёт снимать вид-владельца и добавит
        поле, тест упадёт, и отказ придётся пересмотреть, а не оставить
        врать по инерции.
        """

        field_names = {field.name for field in fields(L0Element)}
        forbidden = ("view", "text", "content", "reference", "refs")
        for token in forbidden:
            with self.subTest(token=token):
                carriers = sorted(
                    name for name in field_names if token in name.lower())
                self.assertEqual(
                    carriers, [],
                    f"в L0Element появилось поле про {token!r}: {carriers}. "
                    "Если вход опа теперь читается, отказ "
                    "source_contract_gap про него больше не верен")

    def test_every_required_input_is_named_in_the_gap_map(self):
        """Карта «чего снимать» обязана покрывать реестр целиком.

        Оп может обзавестись новым обязательным входом. Без этой проверки
        отказ молча напечатал бы «источник не назван» и перестал быть
        спецификацией следующей волны.

        Проверяются НЕ только категории из ``_OPS_WITHOUT_L0_INPUTS``: марка
        и примечание уехали оттуда в таблицу лифтеров (у них появились
        стадии чтения), но ТОТ ЖЕ текст отказа собирается для них, когда
        индекса нет, — значит карта обязана держать и их входы.
        """

        collected = set(_OPS_WITHOUT_L0_INPUTS.values())
        collected |= {"create_tag", "create_text"}
        for op_name in sorted(collected):
            for param in spec.OPS[op_name].params:
                if not param.required:
                    continue
                with self.subTest(op=op_name, param=param.name):
                    self.assertIn(
                        param.name, _L0_HAS_NO_SOURCE_FOR,
                        f"{op_name}.{param.name} обязателен, но карта не "
                        "говорит, какой член API пришлось бы снимать")


class AnnotationsRefuseByTheirOwnName(unittest.TestCase):
    """`no_lifter` посылал в реестр операций. Правда лежит в чтении."""

    def test_each_documentation_category_names_its_own_op(self):
        elements = tuple(
            _annotation(str(1000 + i), category)
            for i, category in enumerate(sorted(_OPS_WITHOUT_L0_INPUTS)))
        nodes = _nodes(_doc(*elements))
        for element in elements:
            op_name = _OPS_WITHOUT_L0_INPUTS[element.category]
            with self.subTest(category=element.category):
                node = nodes[element.element_id]
                self.assertEqual(node["kind"], "atom")
                self.assertEqual(
                    node["reason"]["code"], AtomReason.SOURCE_CONTRACT_GAP.value)
                self.assertIn(op_name, node["reason"]["detail"])

    def test_the_detail_names_every_missing_input(self):
        """Отказ обязан быть спецификацией, а не жалобой."""

        node = _nodes(_doc(_annotation("1", "OST_Dimensions")))["1"]
        detail = node["reason"]["detail"]
        for param in spec.OPS["create_dimension"].params:
            if param.required:
                with self.subTest(param=param.name):
                    self.assertIn(param.name, detail)
        self.assertIn("Dimension.References", detail)
        self.assertIn("Element.OwnerViewId", detail)

    def test_text_notes_name_the_missing_content(self):
        """У примечания недостаёт не только вида, но и САМОГО ТЕКСТА.

        `type_name` несёт имя ТИПА примечания, а не его содержание, и принять
        одно за другое значило бы записать в модель имя стиля вместо надписи.
        """

        detail = _nodes(_doc(_annotation("1", "OST_TextNotes")))["1"]["reason"]["detail"]
        self.assertIn("TextElement.Text", detail)
        self.assertIn("content", detail)

    def test_all_ten_tag_kinds_collapse_to_one_ranking_row(self):
        """Десять родов марок — один оп, значит одна строка ранжира причин.

        Иначе самая крупная дыра документа выглядела бы десятью мелкими и
        проиграла бы в ранжире тому, что дешевле починить.

        30.07 марки переехали из ``_OPS_WITHOUT_L0_INPUTS`` в таблицу
        лифтеров (у них появилась стадия чтения ``tag``), и список берётся
        теперь ОТТУДА. Само требование не изменилось ни на букву: БЕЗ
        ИНДЕКСА все десять родов обязаны отказывать одним текстом с тем же
        кодом, что и до волны, — иначе слепки, снятые раньше, читаются
        другой таксономией, чем сегодняшние.
        """

        tags = sorted(c for c, (_kind, op) in LIFTER_TABLE.items()
                      if op == "create_tag")
        self.assertGreater(len(tags), 1)
        elements = tuple(
            _annotation(str(2000 + i), category)
            for i, category in enumerate(tags))
        nodes = _nodes(_doc(*elements))
        codes = {nodes[e.element_id]["reason"]["code"] for e in elements}
        self.assertEqual(codes, {AtomReason.SOURCE_CONTRACT_GAP.value})
        details = {nodes[e.element_id]["reason"]["detail"] for e in elements}
        self.assertEqual(
            len(details), 1,
            "марки разных родов обязаны отказывать ОДНИМ текстом")
        self.assertIn("create_tag", details.pop())

    def test_categories_that_genuinely_have_no_op_keep_no_lifter(self):
        """Таблица не смеет разрастаться: где опа НЕТ, `no_lifter` — правда.

        Линии, высотные отметки, уклоны и типовые аннотации вошли в чтение
        сознательно и без опа (так и записано в ee32fb82). Переклеить на них
        новый код значило бы гнаться за красивой причиной вместо верной.

        03.08 СПИСОК СТАЛ КОРОЧЕ НА ОДНУ СТРОКУ, и это НЕ ослабление теста, а
        его смысл в действии. ``OST_RoomSeparationLines`` ушёл отсюда потому,
        что у категории ПОЯВИЛСЯ оп (``create_room_separator``, wave/room), и
        держать её здесь значило бы требовать заведомо ЛОЖНОЙ причины: «опа
        нет» посылало бы следующего писать операцию, которая написана. Ровно
        тот же переезд, что 30.07 проделали марки и текстовое примечание, и
        ровно по той же причине. Её собственные границы теперь проверяются
        адресно — ``test_lift_room_separator.py``.
        """

        opless = (
            "OST_Lines", "OST_SpotElevations", "OST_SpotSlopes",
            "OST_GenericAnnotation",
        )
        elements = tuple(
            _annotation(str(3000 + i), category)
            for i, category in enumerate(opless))
        nodes = _nodes(_doc(*elements))
        for element in elements:
            with self.subTest(category=element.category):
                self.assertEqual(
                    nodes[element.element_id]["reason"]["code"],
                    AtomReason.NO_LIFTER.value)


class TelephoneDevicesActuallyLift(unittest.TestCase):
    """Единственное настоящее приобретение волны чтения — и оно уже работает.

    Лифт не правился: устройства попадают в общий путь размещения потому, что
    лид дописал категорию в белый список бокового индекса. Тест закрепляет
    путь целиком — если список снова разойдётся с таблицей чтения, это
    упадёт здесь, а не через слепок на 96 минут.
    """

    def test_unhosted_device_becomes_place_family(self):
        node = _nodes(
            _doc(_instance("500", "OST_TelephoneDevices")),
            {"500": _row("OneLevelBased")})["500"]
        self.assertEqual(node["kind"], "op", node.get("reason"))
        self.assertEqual(node["op_name"], "place_family")

    def test_wall_hosted_device_keeps_its_host(self):
        wall = L0Element(
            element_id="900", category="OST_Walls", category_ru="",
            type_id="20", type_name="Стена 200",
            level_id="10", level_name="L1",
            geom_kind=GeometryKind.CURVE,
            p0_mm=(0.0, 0.0, 0.0), p1_mm=(6000.0, 0.0, 0.0),
            rotation_deg=None, bbox_min_mm=None, bbox_max_mm=None,
            host_id=None, params={})
        nodes = _nodes(
            _doc(wall, _instance("500", "OST_TelephoneDevices")),
            {"500": _row("OneLevelBasedHosted", host_id="900",
                         host_class="Wall")})
        self.assertEqual(nodes["500"]["op_name"], "place_family")
        self.assertEqual(
            nodes["500"]["params"]["host"], {"ref": nodes["900"]["_id"]})


class DetailComponentsRefuseForTheRightReason(unittest.TestCase):
    """Отказ был верным по коду и ЛОЖНЫМ по диагнозу."""

    def _detail(self, placement_type):
        node = _nodes(
            _doc(_instance("600", "OST_DetailComponents", level=False)),
            {"600": _row(placement_type)})["600"]
        self.assertEqual(node["kind"], "atom")
        self.assertEqual(
            node["reason"]["code"], AtomReason.UNSUPPORTED_SIGNATURE.value)
        return node["reason"]["detail"]

    def test_view_specific_placement_blames_the_missing_view(self):
        for placement_type in ("ViewBased", "CurveBasedDetail"):
            with self.subTest(placement_type=placement_type):
                detail = self._detail(placement_type)
                self.assertIn("вида", detail)

    def test_view_specific_placement_no_longer_claims_it_is_not_a_point(self):
        """Autodesk: ViewBased = "The family is view-specific".

        Точка у элемента узла ЕСТЬ. Старый текст утверждал обратное и посылал
        следующего искать кривую или адаптивные точки — туда, где ничего нет.
        """

        detail = self._detail("ViewBased")
        self.assertNotIn("только точечные размещения", detail)

    def test_placements_that_really_are_not_points_keep_the_old_reason(self):
        """Ворота сузились, а не подменились: кривая — по-прежнему не точка."""

        detail = self._detail("CurveDrivenStructural")
        self.assertIn("только точечные размещения", detail)


class TheHonestyContractStaysLossless(unittest.TestCase):
    """Страховка, которой не было: новый код обязан доехать до паспорта.

    `FidelityReason` документирует, что у КАЖДОГО `AtomReason` есть
    одноимённое значение — иначе типизированный отказ теряется по дороге в
    VERIFY. До 29.07 это держалось только на внимательности: ни одного теста
    на соответствие не существовало, и добавить код в одно перечисление,
    забыв про второе, ничего бы не сломало на месте.
    """

    def test_every_atom_reason_has_an_identical_fidelity_reason(self):
        fidelity_values = {reason.value for reason in FidelityReason}
        for reason in AtomReason:
            with self.subTest(reason=reason.name):
                self.assertIn(
                    reason.value, fidelity_values,
                    f"AtomReason.{reason.name} не доедет до паспорта: в "
                    "FidelityReason нет одноимённого значения")


if __name__ == "__main__":
    unittest.main()
