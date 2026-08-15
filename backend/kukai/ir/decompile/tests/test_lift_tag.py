"""Подъём МАРКИ — и пять отказов, которых он не имеет права избежать.

Марка — первая операция KIR, чей обязательный вход есть ССЫЛКА НА ДРУГОЙ
ЭЛЕМЕНТ. У примечания её нет (текст самодостаточен), у двери есть, но
разрешается из самой строки L0 (``host_id``). Здесь ссылка приезжает из
БОКОВОГО ИНДЕКСА и может не разрешиться, и каждый способ обязан быть НАЗВАН,
а не обойдён:

1. индекса нет вовсе (все слепки до этой волны) — прежний
   ``source_contract_gap`` ДОСЛОВНО, иначе история покрытия перестанет быть
   историей;
2. помеченного элемента нет среди прочитанных — ``missing_reference``.
   Привязать марку к похожему элементу было бы худшим из возможных: это
   прошло бы схему L1 и выглядело бы покрытием;
3. марка помещения/площади — ``SpatialElementTag``, а прямой ход умеет ровно
   ``IndependentTag.Create``. Пересборка построила бы НЕ ТО, поэтому
   ``unsupported_forward_signature``;
4. у марки есть ВЫНОСКА, и тогда седьмой аргумент ``Create`` означает не
   голову, а конец выноски (дословная строка Autodesk, одна и та же в 2021 и
   2026) — а стадия читает ``TagHeadPosition``;
5. марка повёрнута, а эмиттер вшивает ``TagOrientation.Horizontal``
   безусловно — молчаливое выпрямление не видно сравнению по положению
   головы, поэтому тоже названный отказ.

Четвёртый и пятый отказы стоят дороже прочих: они РЕЖУТ покрытие, которое
иначе засчиталось бы. Именно поэтому они здесь, а не в списке «доделать
потом»: несовершенное можно, врущее нельзя.
"""
from __future__ import annotations

import copy
import unittest

from kukai.ir.decompile.l1_schema import AtomReason
from kukai.ir.decompile.lift import lift_document_detailed
from kukai.ir.decompile.lift_cache import lift_cache_key
from kukai.ir.decompile.schema import L0Document
from kukai.ir.decompile.tag_extract import TagExtraction, TagRecord
from kukai.ir.decompile.tests.fixtures_decompile import (
    make_element,
    project1_metadata,
)


TAG_ID = "4300"
WALL_ID = "512"
VIEW_ID = "900"
VIEW_NAME = "1 этаж"


def _document(tag_category: str = "OST_WallTags") -> L0Document:
    row = copy.deepcopy(project1_metadata())
    row["change_stamp"] = "tag-wave"
    wall = make_element("OST_Walls", int(WALL_ID))
    tag = make_element(tag_category, int(TAG_ID))
    row["elements"] = [tag, wall]
    row["category_status"] = []
    return L0Document.from_dict(row)


def _lonely_document() -> L0Document:
    """Марка есть, помеченного элемента среди прочитанных НЕТ."""
    row = copy.deepcopy(project1_metadata())
    row["change_stamp"] = "tag-wave"
    row["elements"] = [make_element("OST_WallTags", int(TAG_ID))]
    row["category_status"] = []
    return L0Document.from_dict(row)


def _index(**overrides) -> TagExtraction:
    record = TagRecord(
        element_id=overrides.get("element_id", TAG_ID),
        owner_view_id=overrides.get("owner_view_id", VIEW_ID),
        owner_view_name=overrides.get("owner_view_name", VIEW_NAME),
        at_view_mm=overrides.get("at_view_mm", (3048.0, -762.0)),
        tagged_element_id=overrides.get("tagged_element_id", WALL_ID),
        tag_family=overrides.get("tag_family", "independent"),
        leader=overrides.get("leader", False),
        orientation=overrides.get("orientation", "Horizontal"),
        type_id=overrides.get("type_id", "77"),
        type_name=overrides.get("type_name", "Марка стены"),
    )
    return TagExtraction(tags=(record,))


def _node(result, element_id: str):
    for node in result.nodes:
        if node is not None and node.get("source_element_id") == element_id:
            return node
    raise AssertionError(f"нет узла для {element_id}")


class LiftWithIndexTests(unittest.TestCase):

    def test_a_tag_becomes_create_tag(self) -> None:
        result = lift_document_detailed(_document(), tag_index=_index())
        node = _node(result, TAG_ID)
        self.assertEqual(node["kind"], "op", node.get("reason"))
        self.assertEqual(node["op_name"], "create_tag")

    def test_the_view_travels_in_the_only_named_dialect_l1_has(self) -> None:
        node = _node(lift_document_detailed(_document(), tag_index=_index()),
                     TAG_ID)
        self.assertEqual(node["params"]["in_view"],
                         {"by": "name", "value": VIEW_NAME, "_id": VIEW_ID})

    def test_the_target_points_at_the_lifted_element_not_at_a_raw_id(self) -> None:
        """Ссылка внутрипрограммная: пересборка обязана связать два УЗЛА."""
        result = lift_document_detailed(_document(), tag_index=_index())
        wall = _node(result, WALL_ID)
        tag = _node(result, TAG_ID)
        self.assertEqual(tag["params"]["target"], {"ref": wall["_id"]})

    def test_the_point_stays_two_dimensional(self) -> None:
        node = _node(lift_document_detailed(_document(), tag_index=_index()),
                     TAG_ID)
        self.assertEqual(node["params"]["at"], [3048.0, -762.0])

    def test_a_leaderless_tag_carries_no_leader_key_at_all(self) -> None:
        """Отсутствие выноски — ОТСУТСТВИЕ ключа: эмиттер читает его так.

        Ключа ``leader`` в поднятых параметрах не бывает вовсе: марка с
        выноской до этой точки не доходит (см.
        ``test_a_leadered_tag_refuses_because_at_stops_meaning_the_head``), а
        у марки без выноски ``leader`` и означает пропуск.
        """
        node = _node(lift_document_detailed(_document(), tag_index=_index()),
                     TAG_ID)
        self.assertNotIn("leader", node["params"])

    def test_tag_type_is_carried_when_named_and_omitted_when_not(self) -> None:
        node = _node(lift_document_detailed(_document(), tag_index=_index()),
                     TAG_ID)
        self.assertEqual(node["params"]["tag_type"],
                         {"by": "name", "value": "Марка стены", "_id": "77"})
        bare = _node(
            lift_document_detailed(_document(), tag_index=_index(type_id=None)),
            TAG_ID)
        self.assertNotIn("tag_type", bare["params"])

    def test_a_persisted_envelope_works_as_well_as_the_object(self) -> None:
        from_disk = lift_document_detailed(
            _document(), tag_index=_index().to_dict())
        in_memory = lift_document_detailed(_document(), tag_index=_index())
        self.assertEqual(_node(from_disk, TAG_ID), _node(in_memory, TAG_ID))

    def test_a_tag_on_a_door_still_resolves_though_doors_lift_in_pass_two(self) -> None:
        """Порядок проходов: дверь поднимается ВТОРЫМ, марка обязана — ПОСЛЕ.

        Без этого марка на двери давала бы ``missing_reference`` не потому,
        что двери нет, а потому, что до неё ещё не дошли, — отказ, который
        зависит от внутреннего порядка лифта, а не от модели.
        """
        row = copy.deepcopy(project1_metadata())
        row["change_stamp"] = "tag-wave"
        wall = make_element("OST_Walls", 512)
        door = make_element("OST_Doors", 600)
        door["host_id"] = "512"
        tag = make_element("OST_DoorTags", int(TAG_ID))
        # Марка стоит ПЕРВОЙ в документе — самый неудобный порядок.
        row["elements"] = [tag, door, wall]
        row["category_status"] = []
        document = L0Document.from_dict(row)
        result = lift_document_detailed(
            document, tag_index=_index(tagged_element_id="600"))
        door_node = _node(result, "600")
        self.assertEqual(_node(result, TAG_ID)["params"]["target"],
                         {"ref": door_node["_id"]})


class RefusalsAreNamedNotAvoided(unittest.TestCase):

    def _atom(self, document=None, **kwargs) -> tuple[str, str]:
        result = lift_document_detailed(document or _document(), **kwargs)
        node = _node(result, TAG_ID)
        self.assertEqual(node["kind"], "op" if False else "atom",
                         node.get("op_name"))
        detail = next(
            item.detail for item in result.diagnostics
            if item.source_element_id == TAG_ID)
        reason = node["reason"]
        code = reason["code"] if isinstance(reason, dict) else reason
        return code, detail

    def test_without_the_index_the_old_refusal_is_reproduced_verbatim(self) -> None:
        code, detail = self._atom()
        self.assertEqual(code, AtomReason.SOURCE_CONTRACT_GAP.value)
        self.assertIn("create_tag", detail)
        self.assertIn("in_view", detail)
        self.assertIn("target", detail)
        self.assertIn("at", detail)

    def test_an_index_without_this_element_refuses_the_same_way(self) -> None:
        code, detail = self._atom(tag_index=_index(element_id="999"))
        self.assertEqual(code, AtomReason.SOURCE_CONTRACT_GAP.value)
        self.assertIn("create_tag", detail)

    def test_an_unreadable_target_is_a_named_refusal_not_a_guessed_binding(self) -> None:
        """ГЛАВНЫЙ отказ волны: похожий элемент — не тот элемент."""
        code, detail = self._atom(
            document=_lonely_document(), tag_index=_index())
        self.assertEqual(code, AtomReason.MISSING_REFERENCE.value)
        self.assertIn(WALL_ID, detail)

    def test_an_unknown_tag_family_is_refused_rather_than_assumed(self) -> None:
        """Род вне закрытого словаря — отказ, а не «наверное, независимая».

        ПРЕЖДЕ здесь стоял отказ РОДУ `spatial` («прямой ход строит марку
        единственным способом»). Он снят 13.08.2026, потому что прямой ход
        научился: `authoring._emit_tag` различает цель в C# и строит
        `NewRoomTag`/`NewSpaceTag`/`NewAreaTag`. Отказ был честным и назвал
        маршрут — он дождался, а не устарел.

        Проверка НЕ УДАЛЕНА, а переставлена на границу, которая осталась:
        словарь родов ЗАКРЫТ, и незнакомое значение обязано кричать. Удалить
        её значило бы отдать даром то, что тест охранял, — молчаливое
        превращение неизвестного в известное.
        """
        code, detail = self._atom(
            document=_document("OST_RoomTags"),
            tag_index=_index(tag_family="совершенно новый род"))
        self.assertEqual(code, AtomReason.UNSUPPORTED_SIGNATURE.value)
        self.assertIn("род марки", detail)

    def test_a_room_tag_now_lifts_to_an_op(self) -> None:
        """7 067 элементов `len_ar_me_r24_v1` — цена снятого отказа.

        Замер 13.08.2026 на втором жилом здании, прочитанном полностью:
        марки рода `spatial` были крупнейшей причиной
        `unsupported_forward_signature`. Здесь закреплено, что они
        поднимаются, а не остаются атомом.
        """
        result = lift_document_detailed(
            _document("OST_RoomTags"), tag_index=_index(tag_family="spatial"))
        node = _node(result, TAG_ID)
        self.assertEqual(node["kind"], "op")
        self.assertEqual(node["op_name"], "create_tag")

    def test_a_spatial_tag_with_a_leader_is_still_refused(self) -> None:
        """Снятие одного отказа не снимает соседний.

        Точка марки С ВЫНОСКОЙ означает конец выноски, а прочитана голова.
        Это верно для ОБОИХ родов, и прямой эмиттер отказывает выноске у
        пространственной марки тоже — оба конца должны рвать в одном месте.
        """
        code, detail = self._atom(
            document=_document("OST_RoomTags"),
            tag_index=_index(tag_family="spatial", leader=True))
        self.assertEqual(code, AtomReason.UNSUPPORTED_SIGNATURE.value)
        self.assertIn("выноск", detail)

    def test_a_leadered_tag_refuses_because_at_stops_meaning_the_head(self) -> None:
        """Дословная строка Autodesk про седьмой аргумент Create.

        «For tags with leaders, this point is the end point of the leader,
        and a leader of default length will be created from this point to
        the tag head» — одинаково в 2021 и в 2026, в обеих перегрузках.
        Стадия читает ГОЛОВУ, значит для марки с выноской круг не
        замыкается, и сдвиг был бы невидим сравнению по голове.
        """
        code, detail = self._atom(tag_index=_index(leader=True))
        self.assertEqual(code, AtomReason.UNSUPPORTED_SIGNATURE.value)
        self.assertIn("выноск", detail)
        self.assertIn("TagHeadPosition", detail)

    def test_a_rotated_tag_refuses_instead_of_being_straightened_silently(self) -> None:
        code, detail = self._atom(tag_index=_index(orientation="Vertical"))
        self.assertEqual(code, AtomReason.UNSUPPORTED_SIGNATURE.value)
        self.assertIn("Vertical", detail)

    def test_a_corrupt_index_degrades_to_the_refusal_not_to_half_a_lift(self) -> None:
        code, _ = self._atom(
            tag_index={"schema_version": "чужая/1", "tag_index": {}})
        self.assertEqual(code, AtomReason.SOURCE_CONTRACT_GAP.value)

    def test_a_row_without_a_view_name_refuses(self) -> None:
        """Диалект ссылок L1 именованный: вид без имени невыразим."""
        broken = _index().to_dict()
        broken["tag_index"][TAG_ID]["owner_view_name"] = ""
        code, _ = self._atom(tag_index=broken)
        self.assertEqual(code, AtomReason.SOURCE_CONTRACT_GAP.value)


class TheRefusalIsNotQuietlySubstituted(unittest.TestCase):
    """Форменный отказ марки не имеет права стать ``place_family``.

    ``unsupported_forward_signature`` входит в ``_SHAPE_REFUSALS``, то есть по
    умолчанию означает «пусть попробует размещение семейства». Для марки это
    было бы выдуманным источником: ни IndependentTag, ни SpatialElementTag не
    FamilyInstance. Тест подсовывает боковому индексу размещений строку НА
    ID МАРКИ — состояние, недостижимое сегодня, — и требует, чтобы отказ
    остался тем же.
    """

    def _placement_index(self) -> dict:
        return {
            TAG_ID: {
                "placement_type": "OneLevelBased",
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
        }

    def test_a_spatial_tag_stays_an_atom_even_with_a_placement_row(self) -> None:
        result = lift_document_detailed(
            _document("OST_RoomTags"),
            family_placement_index=self._placement_index(),
            # ПОВОД ОТКАЗА СМЕНЁН 13.08: род `spatial` перестал быть
            # отказом (прямой ход научился), а цель теста — «отказ марки не
            # имеет права стать place_family» — осталась. Берём отказ,
            # который жив: выноска.
            tag_index=_index(leader=True))
        node = _node(result, TAG_ID)
        self.assertEqual(node["kind"], "atom", node.get("op_name"))
        self.assertEqual(node["reason"]["code"],
                         AtomReason.UNSUPPORTED_SIGNATURE.value)

    def test_a_rotated_tag_stays_an_atom_even_with_a_placement_row(self) -> None:
        result = lift_document_detailed(
            _document(),
            family_placement_index=self._placement_index(),
            tag_index=_index(orientation="Vertical"))
        node = _node(result, TAG_ID)
        self.assertEqual(node["kind"], "atom", node.get("op_name"))
        self.assertEqual(node["reason"]["code"],
                         AtomReason.UNSUPPORTED_SIGNATURE.value)


class CacheKeyTests(unittest.TestCase):
    """Ключ без входа = кэш врёт: тот же класс дефекта уже стоил трёх волн."""

    def test_the_tag_index_changes_the_cache_key(self) -> None:
        document = _document()
        without = lift_cache_key(document)
        with_index = lift_cache_key(document, tag_index=_index())
        other = lift_cache_key(document, tag_index=_index(leader=True))
        self.assertNotEqual(without, with_index)
        self.assertNotEqual(with_index, other)

    def test_the_same_index_gives_the_same_key(self) -> None:
        document = _document()
        self.assertEqual(lift_cache_key(document, tag_index=_index()),
                         lift_cache_key(document, tag_index=_index()))


if __name__ == "__main__":
    unittest.main()
