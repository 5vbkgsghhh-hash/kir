"""Боковой индекс МАРОК: ссылка, вид и точка головы, которых L0 не несёт.

ЗАЧЕМ. Волна оформления 30.07 подняла текстовые примечания и честно назвала,
чего не сделала: «Марки и размеры этой волной не снимаются — у марки шов
версий на 2022 (``TaggedLocalElementId`` до 2022 / ``GetTaggedLocalElementIds``
с 2022), и он заслуживает своей волны, а не строчки в конце этой»
(``annotation_extract`` docstring). Это она.

Марок в замеренном документе 20 448 — крупнейший род оформления после
размеров. Операция ``create_tag`` лежит в реестре с 28.07 и мертва не по
лени: её обязательные входы (``in_view``, ``target``, ``at``) в замороженной
строке L0 1.0 отсутствуют КАК ПОЛЯ, и лифтер отказывал ``source_contract_gap``.
Порядок жёсткий и его нельзя обойти: сперва ЗАХВАТ, потом лифтер.

ШОВ ВЕРСИЙ НА 2022 — ГЛАВНОЕ, ЧТО ЗДЕСЬ ЕСТЬ. Проверено индексом ловушек
(``tools/api_trap_index.py``), а не памятью:

    P:IndependentTag.TaggedLocalElementId       2021-2022, УДАЛЁН после 2022
    M:IndependentTag.GetTaggedLocalElements     2022-2026, НЕТ в 2021
    (M:IndependentTag.GetTaggedLocalElementIds  2022-2026, но ЗАПРЕЩЁН нам:
     возвращает ``ISet<>`` из ``System.dll``, которой нет у развёрнутого
     плагина — CS0012 живьём 04.08; см. _TAG_TARGET_2022_CS)

То есть 2022 — единственный год, где есть ОБА, и ни одного члена, живущего во
всех шести версиях, у цели марки нет. Один текст C#, проверенный против шести
целей, не собрался бы либо на 2021, либо на 2023+, поэтому ветвление живёт В
PYTHON: на каждую версию эмитируется РОВНО ОДИН вызов, никогда не два в одном
теле под try/catch. Это тот же закон, по которому ветвится прямой эмиттер
(``authoring._emit_tag``), и он записан здесь второй раз намеренно: обе
стороны круга обязаны рвать поверхность в одном и том же месте.

ДВА РОДА МАРОК, А НЕ ОДИН. ``OST_RoomTags`` (11 585 элементов, больше половины
всех марок) — это НЕ ``IndependentTag``: марка помещения, площади и
пространства суть ``SpatialElementTag``, у которого своя поверхность
(``TagHeadPosition`` / ``HasLeader``, обе 6/6). Стадия читает оба рода и
помечает строку полем ``tag_family``; решение, что с этим делать, принимает
ЛИФТ, а не чтение (см. ``lift._lift_tag``: прямой ход умеет только
``IndependentTag.Create``, и марка помещения получает названный отказ, а не
выдуманную пересборку).

ЦЕЛЬ ПРОСТРАНСТВЕННОЙ МАРКИ БЕРЁТСЯ У ПОДКЛАССА, А НЕ У БАЗЫ, и это исправление
дефекта, а не стиль. Здесь стояло «``SpatialElementTag.SpatialElement`` — все
6/6, сверено по индексу ловушек». Свойство описано в ``RevitAPI.xml`` всех
шести версий и ОТСУТСТВУЕТ в поставляемой ``RevitAPI.dll`` всех шести: тело
стадии не компилировалось НИ НА ОДНОЙ версии (``CS1061``), то есть марки не
читались никогда и нигде. Индекс ловушек строится по XML, поэтому «сверено по
индексу» подтверждало документацию Autodesk, а не сборку. Член считается
существующим тогда, когда его принял Roslyn (см. ``gate_runner``), а не тогда,
когда о нём написано.

ЧТО ИМЕННО ЧИТАЕТСЯ И ЧЕМ (все члены сверены по индексу ловушек):

    поле опа        член API                                    версии
    ─────────────────────────────────────────────────────────────────────
    in_view         Element.OwnerViewId + View.Name             все 6
    at              IndependentTag.TagHeadPosition              все 6
                    SpatialElementTag.TagHeadPosition           все 6
                    (спроецирована базисом вида НА МОСТУ)
    target          IndependentTag.TaggedLocalElementId         2021-2022
                    IndependentTag.GetTaggedLocalElements()     2022-2026
                    RoomTag.Room / AreaTag.Area / SpaceTag.Space  все 6
                    (НЕ SpatialElementTag.SpatialElement: см. ниже)
    leader          IndependentTag.HasLeader                    все 6
                    SpatialElementTag.HasLeader                 все 6
    tag_type        Element.GetTypeId + Element.Name            все 6

ПОЧЕМУ КООРДИНАТА СЧИТАЕТСЯ НА МОСТУ. Ровно по той же причине, что у
примечаний: прямой ход материализует точку вида в мир базисом САМОГО вида
(``docspace.emit_view2d_to_xyz_cs``: ``Origin + u*Right + v*Up``), и обратное
преобразование обязано быть его ТОЧНОЙ инверсией, а не похожей формулой в
другом месте:

    rel = P - view.Origin;  u = rel · view.RightDirection;  v = rel · view.UpDirection

ЧЕГО ЗДЕСЬ НЕТ И ПОЧЕМУ.

* ``TagOrientation`` (все 6 версий) СНИМАЕТСЯ, хотя параметра под неё у опа
  нет. Это не «впрок»: прямой эмиттер вшивает ``TagOrientation.Horizontal``
  безусловно, и без этого поля вертикальная марка пересобралась бы
  горизонтальной МОЛЧА — сравнение по положению головы такую подмену не
  видит. Поле существует ради НАЗВАННОГО отказа в лифте, а не ради параметра.
* Выноска снимается флагом ``HasLeader`` и только им — но флаг этот несёт
  БОЛЬШЕ, чем кажется, и это главная находка волны. Дословная строка Autodesk
  про седьмой аргумент ``IndependentTag.Create`` (RevitAPI.xml, ``param
  pnt``; одинакова в 2021 и в 2026, в обеих перегрузках):

      "For tags without leaders, this point is the position of the tag head.
       For tags with leaders, this point is the end point of the leader, and a
       leader of default length will be created from this point to the tag
       head."

  То есть ``at`` опа — это голова ТОЛЬКО у марки без выноски. Стадия читает
  ``TagHeadPosition``, поэтому марку С выноской ЛИФТ ОТКАЗЫВАЕТ по имени
  (``lift._lift_tag``): пересборка поставила бы конец выноски туда, где была
  голова, и сдвиг остался бы невидимым — сравнение по положению головы его
  не ловит. Снять конец выноски нечем без новой волны: ``GetLeaderEnd`` НЕТ
  в 2021 (``NEW IN 2022`` по индексу ловушек) и с 2023 документированно
  бросает, когда выноска не свободного конца или не видна.
* Марка на элементе СВЯЗАННОГО файла невыразима: ``target`` опа адресует
  элемент ЭТОГО документа. Такая марка получает квитанцию
  ``tag_target_not_local`` — названный отказ, а не привязка к похожему
  элементу этого файла.
* Марка на НЕСКОЛЬКИХ элементах (2022+ умеет) тоже невыразима: у опа ровно
  один ``target``. Квитанция ``address_ambiguous``, потому что любой
  одиночный адрес здесь был бы догадкой.
"""
from __future__ import annotations

import json
from kukai.ir.emit_utils import cs_string_literal
from kukai.ir import spec as _spec
from dataclasses import dataclass
from typing import Any, Iterator, Mapping

from kukai.ir.decompile.side_contract import (
    ELEMENT_ID_HELPER_CS,
    ELEMENT_ID_OUT_OF_RANGE_REASON,
    source_binding_cs,
)

#: Версия ПЕРСИСТЕНТНОГО индекса (то, что ложится на диск и переиспользуется
#: возобновлением). Меняется, когда меняется форма записи.
TAG_INDEX_SCHEMA_VERSION = "kir-decompile-tag-index/1"
#: Версия ПРОВОДНОГО ответа моста. Литерал вшит в C# и сверяется при разборе:
#: чужой или устаревший ответ обязан отказать громко, а не разобраться наполовину.
TAG_EXTRACT_SCHEMA_VERSION = "kir-decompile-tag-extract/1"

_FT_TO_MM = 304.8

#: Род марки: чем именно она является в API, а не как называется её категория.
#: ``independent`` — ``IndependentTag`` (дверь, стена, перекрытие, балка…);
#: ``spatial`` — ``SpatialElementTag`` (помещение, площадь, пространство).
#: Различие несёт СТРОКА, а не догадка лифта по категории: категорий десять,
#: родов два, и связь между ними — факт API, который обязан ехать из чтения.
TAG_FAMILY_INDEPENDENT = "independent"
TAG_FAMILY_SPATIAL = "spatial"
TAG_FAMILIES = frozenset({TAG_FAMILY_INDEPENDENT, TAG_FAMILY_SPATIAL})

#: Ориентация, которую прямой эмиттер умеет ставить. Всё остальное — честный
#: отказ лифта, а не молча выпрямленная марка.
TAG_ORIENTATION_HORIZONTAL = "Horizontal"

#: Категории L0, которые кормит эта стадия — РОВНО те десять, что читает
#: экстрактор (``extract._CATEGORIES``, блок «МАРКИ»). Строка здесь обязана
#: двигаться ВМЕСТЕ со строкой в ``pipeline._STAGE_CATEGORIES``: категория
#: здесь без строки там — id никогда не запросят; строка там без категории
#: здесь — каждый id уйдёт квитанцией «не наш род».
TAG_CATEGORIES = frozenset({
    "OST_RoomTags",
    "OST_DoorTags",
    "OST_WallTags",
    "OST_FloorTags",
    "OST_AreaTags",
    "OST_StairsRailingTags",
    "OST_StructuralFramingTags",
    "OST_MechanicalEquipmentTags",
    "OST_MaterialTags",
    "OST_MultiCategoryTags",
})

#: Версии, на которые компилируется прямой ход. Шов проходит ровно посередине.
#:
#: СПРАШИВАЕТСЯ У РЕЕСТРА, А НЕ ВЫПИСЫВАЕТСЯ. До 13.08.2026 здесь стояли те же
#: шесть лет литералами — вторая копия авторитета, которая молча осталась бы
#: шестёркой в день, когда `spec.REVIT_VERSIONS` вырастет, и тесты марок
#: продолжили бы «проверять все версии», проверяя старые.
TAG_SUPPORTED_VERSIONS = tuple(_spec.REVIT_VERSIONS)
#: Первая версия, где марка умеет держать НЕСКОЛЬКО целей (и где появился
#: множественный член чтения вместо свойства ``TaggedLocalElementId``).
TAG_MULTI_REFERENCE_SINCE = 2022


class TagPayloadError(ValueError):
    """Проводной ответ не той формы — типизированный отказ, а не догадка."""


def _mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TagPayloadError(f"{field_name} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise TagPayloadError(f"{field_name} keys must be strings")
    return dict(value)


def _array(value: Any, field_name: str) -> list[Any]:
    if not isinstance(value, list):
        raise TagPayloadError(f"{field_name} must be an array")
    return value


def _exact_fields(value: Any, allowed: set[str], field_name: str, *,
                  optional: set[str] | None = None) -> dict[str, Any]:
    """Ни одного лишнего ключа и ни одного пропущенного обязательного.

    Молча проигнорированный лишний ключ — это способ, которым расходятся две
    стороны провода: одна уже пишет новое поле, другая его не видит, и обе
    считают, что договорились.
    """
    root = _mapping(value, field_name)
    optional = optional or set()
    missing = allowed - optional - set(root)
    if missing:
        raise TagPayloadError(f"{field_name} is missing {sorted(missing)}")
    extra = set(root) - allowed
    if extra:
        raise TagPayloadError(f"{field_name} has unexpected {sorted(extra)}")
    return root


def _string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise TagPayloadError(f"{field_name} must be a non-empty string")
    return value


def _number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TagPayloadError(f"{field_name} must be a number")
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        raise TagPayloadError(f"{field_name} must be finite")
    return number


def _boolean(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise TagPayloadError(f"{field_name} must be a boolean")
    return value


def _family(value: Any, field_name: str) -> str:
    family = _string(value, field_name)
    if family not in TAG_FAMILIES:
        raise TagPayloadError(
            f"{field_name} must be one of {sorted(TAG_FAMILIES)}")
    return family


def _element_id_key(value: str) -> tuple[int, int | str, str]:
    """Порядок по ЧИСЛОВОМУ id, нечисловые — в конец, но всегда детерминированно."""
    try:
        return (0, int(value), value)
    except (TypeError, ValueError):
        return (1, value, value)


@dataclass(frozen=True, slots=True)
class TagRecord:
    """Одна марка: на что смотрит, в каком виде живёт и где её голова."""

    element_id: str
    owner_view_id: str
    #: Имя вида. Не украшение: замороженный диалект ссылок L1 знает РОВНО
    #: одну именованную форму — {"by": "name", "value": <имя>, "_id": <id>}.
    #: Ссылка «по element_id» в L1 не существует, поэтому без имени вида
    #: марку нельзя выразить вовсе.
    owner_view_name: str
    #: [u, v] мм в плоскости вида — голова марки, уже спроецированная базисом
    #: вида на мосту той же формулой, которой прямой ход ставит её обратно.
    at_view_mm: tuple[float, float]
    #: ПОМЕЧЕННЫЙ элемент — ровно один и ровно этого документа. Марка на
    #: связи и марка на нескольких элементах сюда не доезжают: они остаются
    #: квитанцией, потому что у опа один ``target`` и он адресует свой файл.
    tagged_element_id: str
    #: Род марки в терминах API (см. TAG_FAMILY_*).
    tag_family: str
    leader: bool
    #: ``TagOrientation``/``SpatialElementTagOrientation`` строкой. Параметра
    #: под неё у опа нет — поле существует, чтобы лифт мог ОТКАЗАТЬ по имени,
    #: а не выпрямить марку молча.
    orientation: str
    type_id: str | None = None
    type_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "element_id": self.element_id,
            "owner_view_id": self.owner_view_id,
            "owner_view_name": self.owner_view_name,
            "at_view_mm": [self.at_view_mm[0], self.at_view_mm[1]],
            "tagged_element_id": self.tagged_element_id,
            "tag_family": self.tag_family,
            "leader": self.leader,
            "orientation": self.orientation,
            "type_id": self.type_id,
            "type_name": self.type_name,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "TagRecord":
        root = _exact_fields(
            value,
            {"element_id", "owner_view_id", "owner_view_name", "at_view_mm",
             "tagged_element_id", "tag_family", "leader", "orientation",
             "type_id", "type_name"},
            "tag record", optional={"type_id", "type_name"})
        at = _array(root["at_view_mm"], "tag record.at_view_mm")
        if len(at) != 2:
            raise TagPayloadError(
                "tag record.at_view_mm must be [u, v] — точка вида ДВУМЕРНА, "
                "третья координата означала бы модельную точку в поле вида")
        type_id = root.get("type_id")
        if type_id is not None and not isinstance(type_id, str):
            raise TagPayloadError("tag record.type_id must be a string")
        type_name = root.get("type_name")
        if type_name is not None and not isinstance(type_name, str):
            raise TagPayloadError("tag record.type_name must be a string")
        return cls(
            element_id=_string(root["element_id"], "tag record.element_id"),
            owner_view_id=_string(
                root["owner_view_id"], "tag record.owner_view_id"),
            owner_view_name=_string(
                root["owner_view_name"], "tag record.owner_view_name"),
            at_view_mm=(_number(at[0], "at_view_mm[0]"),
                        _number(at[1], "at_view_mm[1]")),
            tagged_element_id=_string(
                root["tagged_element_id"], "tag record.tagged_element_id"),
            tag_family=_family(root["tag_family"], "tag record.tag_family"),
            leader=_boolean(root["leader"], "tag record.leader"),
            orientation=_string(root["orientation"], "tag record.orientation"),
            type_id=type_id or None,
            type_name=type_name or None,
        )


@dataclass(frozen=True, slots=True)
class TagFailure:
    """Квитанция §18.2: элемент, который стадия запросила и не прочитала."""

    element_id: str
    reason: str
    typed_reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "element_id": self.element_id,
            "reason": self.reason,
            "typed_reason": self.typed_reason,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "TagFailure":
        root = _exact_fields(
            value, {"element_id", "reason", "typed_reason"}, "tag failure")
        return cls(
            element_id=_string(root["element_id"], "tag failure.element_id"),
            reason=_string(root["reason"], "tag failure.reason"),
            typed_reason=_string(
                root["typed_reason"], "tag failure.typed_reason"),
        )


@dataclass(frozen=True, slots=True)
class TagExtraction:
    """Проверенный боковой индекс марок, независимый от замороженной L0."""

    tags: tuple[TagRecord, ...] = ()
    failures: tuple[TagFailure, ...] = ()

    def __post_init__(self) -> None:
        ids = [record.element_id for record in self.tags]
        if len(ids) != len(set(ids)):
            raise TagPayloadError("tag index contains duplicate element_id")

    def __iter__(self) -> Iterator[TagRecord]:
        return iter(self.tags)

    def __len__(self) -> int:
        return len(self.tags)

    @property
    def records(self) -> tuple[TagRecord, ...]:
        """Имя КОНТРАКТА, которым спрашивает сверщик §18.2.

        Волна оформления споткнулась ровно здесь: поле называлось по смыслу
        (``text_notes``), сверщик спрашивал по контракту (``records``), и
        живой прогон Snowdon умер на 26 элементах при БЕЗУПРЕЧНОМ C# —
        ``side_stage_count_mismatch``. Свойство ставится СРАЗУ, и его наличие
        у каждой зарегистрированной стадии держит тест
        ``test_side_stage_contract``.
        """
        return self.tags

    @property
    def tag_index(self) -> dict[str, dict[str, Any]]:
        return {
            record.element_id: record.to_dict()
            for record in sorted(
                self.tags, key=lambda r: _element_id_key(r.element_id))
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": TAG_INDEX_SCHEMA_VERSION,
            "tag_index": self.tag_index,
            "failures": [
                failure.to_dict()
                for failure in sorted(
                    self.failures,
                    key=lambda f: (_element_id_key(f.element_id), f.reason))
            ],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, allow_nan=False,
                          separators=(",", ":"), sort_keys=True)

    @classmethod
    def from_dict(cls, value: Any) -> "TagExtraction":
        root = _exact_fields(
            value, {"schema_version", "tag_index", "failures"},
            "tag index", optional={"failures"})
        if root["schema_version"] != TAG_INDEX_SCHEMA_VERSION:
            raise TagPayloadError("tag index schema_version mismatch")
        index = _mapping(root["tag_index"], "tag index.tag_index")
        records = []
        for key, row in index.items():
            record = TagRecord.from_dict(row)
            if record.element_id != key:
                raise TagPayloadError(
                    "tag index key does not match record.element_id")
            records.append(record)
        failures = tuple(
            TagFailure.from_dict(row)
            for row in _array(root.get("failures") or [], "tag index.failures"))
        return cls(tags=tuple(records), failures=failures)

    @classmethod
    def from_json(cls, text: str) -> "TagExtraction":
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise TagPayloadError(
                f"tag index is not valid JSON: {exc}") from exc
        return cls.from_dict(value)


def _unwrap_bridge_payload(payload: Any) -> Any:
    """Мост заворачивает ответ в ``{"payload": ...}`` — разворачиваем ОДИН раз."""
    if isinstance(payload, Mapping) and "payload" in payload \
            and "schema_version" not in payload:
        return payload["payload"]
    return payload


def extract_tags(payload: Any) -> TagExtraction:
    """Проверить один ответ моста и собрать индекс.

    Порча формы провода — типизированное исключение. Честный отказ по
    КОНКРЕТНОМУ элементу — строка квитанции, а не исключение: стадия обязана
    дочитать остальное и назвать пропущенное.
    """
    root = _exact_fields(
        _unwrap_bridge_payload(payload),
        {"schema_version", "elements", "failures"},
        "Tag extraction", optional={"failures"})
    if root["schema_version"] != TAG_EXTRACT_SCHEMA_VERSION:
        raise TagPayloadError("Tag extraction schema_version mismatch")

    records: list[TagRecord] = []
    for index, row in enumerate(_array(root["elements"],
                                       "Tag extraction.elements")):
        item = _exact_fields(
            row,
            {"element_id", "owner_view_id", "owner_view_name", "at_view_ft",
             "tagged_element_id", "tag_family", "leader", "orientation",
             "type_id", "type_name"},
            f"Tag extraction.elements[{index}]",
            optional={"type_id", "type_name"})
        at = _array(item["at_view_ft"], f"elements[{index}].at_view_ft")
        if len(at) != 2:
            raise TagPayloadError(
                f"elements[{index}].at_view_ft must be [u, v]")
        type_id = item.get("type_id")
        if type_id is not None and not isinstance(type_id, str):
            raise TagPayloadError(f"elements[{index}].type_id must be a string")
        type_name = item.get("type_name")
        if type_name is not None and not isinstance(type_name, str):
            raise TagPayloadError(
                f"elements[{index}].type_name must be a string")
        records.append(TagRecord(
            element_id=_string(item["element_id"],
                               f"elements[{index}].element_id"),
            owner_view_id=_string(item["owner_view_id"],
                                  f"elements[{index}].owner_view_id"),
            owner_view_name=_string(item["owner_view_name"],
                                    f"elements[{index}].owner_view_name"),
            # ПЕРЕСЧЁТ ЖИВЁТ ЗДЕСЬ И ТОЛЬКО ЗДЕСЬ: провод несёт сырые футы.
            at_view_mm=(
                _number(at[0], f"elements[{index}].at_view_ft[0]") * _FT_TO_MM,
                _number(at[1], f"elements[{index}].at_view_ft[1]") * _FT_TO_MM),
            tagged_element_id=_string(
                item["tagged_element_id"],
                f"elements[{index}].tagged_element_id"),
            tag_family=_family(item["tag_family"],
                               f"elements[{index}].tag_family"),
            leader=_boolean(item["leader"], f"elements[{index}].leader"),
            orientation=_string(item["orientation"],
                                f"elements[{index}].orientation"),
            type_id=type_id or None,
            type_name=type_name or None,
        ))

    failures = tuple(
        TagFailure.from_dict(row)
        for row in _array(root.get("failures") or [],
                          "Tag extraction.failures"))
    return TagExtraction(tags=tuple(records), failures=failures)


def merge_tags(parts: list[TagExtraction]) -> TagExtraction:
    """Склеить страницы одной стадии, не потеряв ни записи, ни квитанции."""
    records: list[TagRecord] = []
    failures: list[TagFailure] = []
    seen: set[str] = set()
    for part in parts:
        for record in part.tags:
            # Побеждает ПЕРВАЯ прочитанная, а не последняя: «последняя
            # выигрывает» сделало бы результат зависимым от порядка страниц,
            # то есть от сети.
            if record.element_id in seen:
                continue
            seen.add(record.element_id)
            records.append(record)
        failures.extend(part.failures)
    return TagExtraction(tags=tuple(records), failures=tuple(failures))


def _csharp_string(value: str) -> str:
    return cs_string_literal(value)


TAG_EXTRACT_HELPER_CS = r"""
// KIR DECOMPILE — read-only tag helpers. Никаких транзакций.
// Точка головы считается ТОЙ ЖЕ формулой, что и прямой эмиттер:
//   rel = P - view.Origin;  u = rel·view.RightDirection;  v = rel·view.UpDirection
// Провод несёт СЫРЫЕ футы; пересчёт в мм принадлежит офлайн-разборщику.
// Имя класса БЕЗ обращения к среде выполнения за типом: та форма записи
// целиком отвергается валидатором безопасности моста версий до 06.07.2026,
// который всё ещё стоит на части флота, — тело браковалось бы на машине
// пользователя ДО компиляции, и сервер об этом не узнавал бы.
// Object.ToString() у Element/Curve/Surface и у исключений — это полное имя
// типа CLR: из Autodesk.Revit.DB его перекрывают только ElementId, UV, XYZ,
// WorksetId, ScheduleFieldId и PolymeshFacet (замер по индексу ловушек), и
// ни один из них сюда не передаётся. Исключение дописывает ": сообщение" и
// стек, поэтому срез идёт по первому переводу строки и первому двоеточию.
// Результат побайтно равен прежнему .Name.
Func<object, string> __tgClassName = (__tgcnObj) =>
{
    if (__tgcnObj == null) return "";
    string __tgcn = __tgcnObj.ToString();
    if (__tgcn == null) return "";
    int __tgcnCut = __tgcn.IndexOf((char)10);
    if (__tgcnCut >= 0) __tgcn = __tgcn.Substring(0, __tgcnCut);
    __tgcnCut = __tgcn.IndexOf(':');
    if (__tgcnCut >= 0) __tgcn = __tgcn.Substring(0, __tgcnCut);
    __tgcn = __tgcn.Trim();
    __tgcnCut = __tgcn.LastIndexOf('.');
    return __tgcnCut >= 0 && __tgcnCut + 1 < __tgcn.Length
        ? __tgcn.Substring(__tgcnCut + 1) : __tgcn;
};
Func<ElementId, string> __tgValidIdString = (__id) =>
    (__id == null || __id == ElementId.InvalidElementId)
        ? null : __id.ToString();
Func<double, bool> __tgFinite = (__value) =>
    !Double.IsNaN(__value) && !Double.IsInfinity(__value);
""" + ELEMENT_ID_HELPER_CS + "\n"


#: Цель ПРОСТРАНСТВЕННОЙ марки. Один текст на ОБЕ версионные ветки: он от
#: версии не зависит, а две его копии (по одной в каждой ветке) разошлись бы
#: молча — и разошлись бы ровно так, как разошёлся первый вариант этого блока.
#:
#: ЗАМЕР 30.07: первый вариант читал ``SpatialElementTag.SpatialElement``, и
#: это НЕ КОМПИЛИРОВАЛОСЬ НИ НА ОДНОЙ из шести версий:
#:
#:     CS1061: 'SpatialElementTag' does not contain a definition for
#:     'SpatialElement'
#:
#: Свойство описано в ``RevitAPI.xml`` всех шести версий — и отсутствует в
#: поставляемой ``RevitAPI.dll`` всех шести. Докстринг стадии утверждал
#: «``SpatialElementTag.SpatialElement`` — все 6/6, сверено по индексу
#: ловушек»; индекс строится ПО XML, то есть сверка подтверждала документацию
#: Autodesk, а не сборку, против которой мы компилируем. Отсюда правило: член
#: считается существующим тогда, когда его принял Roslyn, а не тогда, когда о
#: нём написано.
#:
#: Цель берётся у КОНКРЕТНОГО подкласса — их ровно три на всю иерархию
#: (``RoomTag`` / ``AreaTag`` / ``SpaceTag``), и все три члена живут во всех
#: шести версиях. Четвёртый подкласс, если Autodesk его заведёт, получит
#: НАЗВАННЫЙ отказ ``element_kind_mismatch``, а не тихий
#: ``tag_target_not_local``: «мы не умеем этот род марки» и «у марки нет
#: локальной цели» — разные факты, и путать их значит прятать первый за
#: вторым.
_TAG_TARGET_SPATIAL_CS = r"""
            __tgStep = "RoomTag.Room / AreaTag.Area / SpaceTag.Space";
            Element __tgSpatial = null;
            bool __tgSpatialKnown = false;
            Autodesk.Revit.DB.Architecture.RoomTag __tgRoomTag =
                __tgSpa as Autodesk.Revit.DB.Architecture.RoomTag;
            Autodesk.Revit.DB.AreaTag __tgAreaTag =
                __tgSpa as Autodesk.Revit.DB.AreaTag;
            Autodesk.Revit.DB.Mechanical.SpaceTag __tgSpaceTag =
                __tgSpa as Autodesk.Revit.DB.Mechanical.SpaceTag;
            if (__tgRoomTag != null)
            {
                __tgSpatialKnown = true;
                __tgSpatial = __tgRoomTag.Room;
            }
            else if (__tgAreaTag != null)
            {
                __tgSpatialKnown = true;
                __tgSpatial = __tgAreaTag.Area;
            }
            else if (__tgSpaceTag != null)
            {
                __tgSpatialKnown = true;
                __tgSpatial = __tgSpaceTag.Space;
            }
            if (!__tgSpatialKnown)
            {
                __tgFail(__tgRaw,
                         "unknown SpatialElementTag subclass: "
                             + __tgClassName(__tgSpa),
                         "element_kind_mismatch");
                continue;
            }
            if (__tgSpatial == null)
            {
                __tgFail(__tgRaw,
                         "spatial tag marks no spatial element of this document",
                         "tag_target_not_local");
                continue;
            }
            __tgTargetId = __tgSpatial.Id;
"""


#: Цель марки на 2021: ``TaggedLocalElementId`` — СВОЙСТВО, и множественных
#: ссылок там не бывает по построению API. ``GetTaggedLocalElementIds`` в 2021
#: не существует (индекс ловушек: NEW IN 2022), поэтому этот текст на 2021
#: единственно возможный, а на 2023+ он бы не собрался.
_TAG_TARGET_2021_CS = r"""
        if (__tgInd != null)
        {
            __tgStep = "IndependentTag.TaggedLocalElementId (<=2021)";
            __tgTargetId = __tgInd.TaggedLocalElementId;
            if (__tgTargetId == null
                || __tgTargetId == ElementId.InvalidElementId)
            {
                __tgFail(__tgRaw,
                         "tag marks no element of this document (linked host or orphaned tag)",
                         "tag_target_not_local");
                continue;
            }
        }
        else
        {
__TAG_TARGET_SPATIAL__
        }
"""


#: Цель марки на 2022+: множество, а не один элемент. Одна марка с 2022 умеет
#: помечать несколько элементов, и это не редкость, а задокументированная
#: возможность API. У опа ``target`` ровно один, поэтому множественная марка —
#: квитанция ``address_ambiguous``, а не «возьмём первый»: первый из множества
#: зависел бы от порядка перечисления Revit.
#:
#: СПРАШИВАЕМ ЭЛЕМЕНТЫ, А НЕ ИХ ID, И ЭТО НЕ СТИЛЬ. ``GetTaggedLocalElementIds``
#: возвращает ``ISet<ElementId>``, а ``ISet<>`` на net48 объявлен в
#: ``System.dll``, которой НЕТ в замыкании ссылок развёрнутого плагина: живое
#: извлечение 13A-RD-AR-K2_v33 (Revit 2023) умерло 04.08 в 17:22:39 на ПЕРВОЙ
#: же пачке стадии марок — ``CS0012: The type 'ISet<>' is defined in an assembly
#: that is not referenced``, отпечаток текста ``5f48cd823928``.
#:
#: ОБОЙТИ КАСТОМ НЕЛЬЗЯ: любое использование выражения требует, чтобы компилятор
#: загрузил его тип, — ни ``object``, ни негенерик ``IEnumerable`` этого не
#: снимают (тот же разбор в ``group_extract.py`` о
#: ``GetAvailableAttachedDetailGroupTypeIds``). Но здесь, в отличие от групп,
#: поле обязательное: без цели марка не операция. Поэтому взят СОСЕДНИЙ член
#: того же класса, живущий в те же 2022-2026 и возвращающий тип из ``mscorlib``:
#:
#:     M:IndependentTag.GetTaggedLocalElementIds  -> ISet<ElementId>          ❌
#:     M:IndependentTag.GetTaggedLocalElements    -> ICollection<Element>     ✅
#:
#: Возвраты замерены оракулом Roslyn (``tests/emitted_csharp_signature_closure``
#: — намеренная ошибка CS0029 заставляет компилятор НАЗВАТЬ тип), а не взяты из
#: документации. Множество то же самое — те же помеченные элементы этого
#: документа, — меняется только форма ответа: ``Element.Id`` вместо ``ElementId``
#: напрямую.
_TAG_TARGET_2022_CS = r"""
        if (__tgInd != null)
        {
            __tgStep = "IndependentTag.GetTaggedLocalElements (>=2022)";
            var __tgTargets = __tgInd.GetTaggedLocalElements();
            int __tgTargetCount = (__tgTargets == null) ? 0 : __tgTargets.Count;
            if (__tgTargetCount == 0)
            {
                __tgFail(__tgRaw,
                         "tag marks no element of this document (linked host or orphaned tag)",
                         "tag_target_not_local");
                continue;
            }
            if (__tgTargetCount > 1)
            {
                __tgFail(__tgRaw,
                         "tag marks " + __tgTargetCount.ToString()
                             + " elements; create_tag holds exactly one target",
                         "address_ambiguous");
                continue;
            }
            foreach (Element __tgOne in __tgTargets)
            {
                if (__tgOne == null) continue;
                __tgTargetId = __tgOne.Id;
                break;
            }
        }
        else
        {
__TAG_TARGET_SPATIAL__
        }
"""


_TAG_EXTRACT_BODY_CS = r"""
long __tgCallBudgetMs = __TG_CALL_BUDGET_MS__L;
long __tgCallWatchT0 = DateTime.UtcNow.Ticks;

var __tgFailures = new List<object>();
Action<string, string, string> __tgFail =
    (__failedId, __reason, __typed) =>
{
    var __failure = new Dictionary<string, object>();
    __failure["element_id"] = __failedId;
    __failure["reason"] = __reason;
    __failure["typed_reason"] = __typed;
    __tgFailures.Add(__failure);
};

var __tgIds = new List<string> { __TAG_IDS__ };
var __tgRows = new List<object>();
bool __tgBudgetOut = false;
foreach (string __tgRaw in __tgIds)
{
    if (__tgBudgetOut
        || ((DateTime.UtcNow.Ticks - __tgCallWatchT0) / TimeSpan.TicksPerMillisecond) >= __tgCallBudgetMs)
    {
        __tgBudgetOut = true;
        __tgFail(__tgRaw, "call_budget_exhausted", "call_budget_exhausted");
        continue;
    }
    // ИМЯ ШАГА, КОТОРЫЙ СЕЙЧАС ИДЁТ. Урок 2846 групп: тип исключения без
    // имени вызова — одно ведро на всё, и по нему нельзя сказать ни ЧТО
    // читали, ни ЧТО ответил Revit.
    string __tgStep = "ElementId.Parse";
    try
    {
        long __tgNum = 0L;
        if (!Int64.TryParse(__tgRaw, out __tgNum))
        {
            __tgFail(__tgRaw, "element id is not numeric", "element_unresolved");
            continue;
        }
        __tgStep = "Document.GetElement";
        ElementId __tgId = __sideElementId(__tgNum);
        if (__tgId == null)
        {
            __tgFail(__tgRaw, "__ELEMENT_ID_OUT_OF_RANGE__", "element_unresolved");
            continue;
        }
        Element __tgEl = __src.GetElement(__tgId);
        if (__tgEl == null)
        {
            __tgFail(__tgRaw, "element not found in document", "element_unresolved");
            continue;
        }
        // ДВА РОДА МАРОК. Марка помещения/площади/пространства — НЕ
        // IndependentTag: у неё своя иерархия (SpatialElementTag), и попытка
        // читать её как IndependentTag дала бы null на 11 585 элементах
        // замеренного документа.
        __tgStep = "cast to IndependentTag / SpatialElementTag";
        Autodesk.Revit.DB.IndependentTag __tgInd =
            __tgEl as Autodesk.Revit.DB.IndependentTag;
        Autodesk.Revit.DB.SpatialElementTag __tgSpa =
            __tgEl as Autodesk.Revit.DB.SpatialElementTag;
        if (__tgInd == null && __tgSpa == null)
        {
            __tgFail(__tgRaw,
                     "not a tag element: " + __tgClassName(__tgEl),
                     "element_kind_mismatch");
            continue;
        }
        string __tgFamily = (__tgInd != null) ? "independent" : "spatial";

        __tgStep = "Element.OwnerViewId";
        ElementId __tgViewId = __tgEl.OwnerViewId;
        string __tgViewIdStr = __tgValidIdString(__tgViewId);
        if (__tgViewIdStr == null)
        {
            // ЗАКОН ПРИВЯЗКИ К ВИДУ: аннотация живёт в конкретном виде, и
            // точка вида существует ТОЛЬКО в его плоскости.
            __tgFail(__tgRaw, "tag has no owner view", "aspect_not_present");
            continue;
        }
        __tgStep = "GetElement(OwnerViewId) as View";
        Autodesk.Revit.DB.View __tgView =
            __src.GetElement(__tgViewId) as Autodesk.Revit.DB.View;
        if (__tgView == null)
        {
            __tgFail(__tgRaw, "owner view is not a View element", "element_unresolved");
            continue;
        }
        __tgStep = "View basis (Origin/RightDirection/UpDirection)";
        XYZ __tgOrigin = __tgView.Origin;
        XYZ __tgRight = __tgView.RightDirection;
        XYZ __tgUp = __tgView.UpDirection;
        if (__tgOrigin == null || __tgRight == null || __tgUp == null)
        {
            __tgFail(__tgRaw, "view basis is unavailable", "aspect_not_present");
            continue;
        }
        __tgStep = "View.Name";
        string __tgViewName = __tgView.Name;
        if (String.IsNullOrEmpty(__tgViewName))
        {
            // Диалект ссылок L1 именованный: вид без имени невыразим.
            __tgFail(__tgRaw, "owner view has no name", "aspect_not_present");
            continue;
        }

        __tgStep = "TagHeadPosition";
        XYZ __tgHead = (__tgInd != null)
            ? __tgInd.TagHeadPosition : __tgSpa.TagHeadPosition;
        if (__tgHead == null)
        {
            __tgFail(__tgRaw, "tag has no head position", "aspect_not_present");
            continue;
        }
        __tgStep = "project onto view basis";
        XYZ __tgRel = __tgHead - __tgOrigin;
        double __tgU = __tgRel.DotProduct(__tgRight);
        double __tgV = __tgRel.DotProduct(__tgUp);
        if (!__tgFinite(__tgU) || !__tgFinite(__tgV))
        {
            __tgFail(__tgRaw, "projected view point is not finite", "aspect_not_present");
            continue;
        }

        // ЦЕЛЬ МАРКИ — ЕДИНСТВЕННОЕ МЕСТО, ГДЕ ПОВЕРХНОСТЬ РВЁТСЯ ПО ВЕРСИИ.
        // Ветвление сделано В PYTHON: ниже стоит РОВНО ОДИН вызов, тот, что
        // существует на целевой версии.
        ElementId __tgTargetId = null;
__TAG_TARGET_BLOCK__
        string __tgTargetIdStr = __tgValidIdString(__tgTargetId);
        if (__tgTargetIdStr == null)
        {
            __tgFail(__tgRaw,
                     "tagged element id is invalid",
                     "tag_target_not_local");
            continue;
        }

        __tgStep = "HasLeader";
        bool __tgLeader = (__tgInd != null)
            ? __tgInd.HasLeader : __tgSpa.HasLeader;

        __tgStep = "TagOrientation";
        string __tgOrient = (__tgInd != null)
            ? __tgInd.TagOrientation.ToString()
            : __tgSpa.TagOrientation.ToString();

        __tgStep = "Element.GetTypeId";
        string __tgTypeId = __tgValidIdString(__tgEl.GetTypeId());
        string __tgTypeName = null;
        if (__tgTypeId != null)
        {
            __tgStep = "type element Name";
            Element __tgTypeEl = __src.GetElement(__tgEl.GetTypeId());
            if (__tgTypeEl != null) __tgTypeName = __tgTypeEl.Name;
        }

        var __tgRow = new Dictionary<string, object>();
        __tgRow["element_id"] = __tgRaw;
        __tgRow["owner_view_id"] = __tgViewIdStr;
        __tgRow["owner_view_name"] = __tgViewName;
        __tgRow["at_view_ft"] = (object)new double[] { __tgU, __tgV };
        __tgRow["tagged_element_id"] = __tgTargetIdStr;
        __tgRow["tag_family"] = __tgFamily;
        __tgRow["leader"] = __tgLeader;
        __tgRow["orientation"] = __tgOrient;
        __tgRow["type_id"] = __tgTypeId;
        __tgRow["type_name"] = __tgTypeName;
        __tgRows.Add(__tgRow);
    }
    catch (Exception __tgEx)
    {
        __tgFail(__tgRaw,
                 "tag read failed at " + __tgStep + ": "
                     + __tgClassName(__tgEx),
                 "read_failed");
    }
}

var __tgPayload = new Dictionary<string, object>();
__tgPayload["schema_version"] = __TG_SCHEMA__;
__tgPayload["elements"] = __tgRows;
__tgPayload["failures"] = __tgFailures;
return __tgPayload;
"""


def tag_target_block_cs(revit_version: Any) -> str:
    """Тот единственный кусок C#, который РАЗНЫЙ на разных версиях.

    Выделен в отдельную функцию не для красоты, а чтобы шов было видно и
    можно было проверить тестом отдельно от всего остального тела: шесть
    целей — шесть проверок одного места, а не шесть проверок одного текста.

    Версия неизвестна/непарсируема ⇒ берётся ветка 2022+: это НЕ угадывание
    «поновее», а закрытый отказ в пользу того члена, который существует в
    ПЯТИ версиях из шести. Прямой эмиттер разводит тот же шов той же
    границей (``authoring._emit_tag``: ``if ver >= "2022"``).
    """
    try:
        year = int(str(revit_version))
    except (TypeError, ValueError):
        year = TAG_MULTI_REFERENCE_SINCE
    block = (_TAG_TARGET_2021_CS if year < TAG_MULTI_REFERENCE_SINCE
             else _TAG_TARGET_2022_CS)
    # Пространственная ветка ОДНА на обе версионные: подставляется здесь, а не
    # копируется в каждый текст (см. _TAG_TARGET_SPATIAL_CS о том, чем стоила
    # первая копия).
    return block.replace("__TAG_TARGET_SPATIAL__", _TAG_TARGET_SPATIAL_CS)


def build_tag_extract_cs(element_ids: list[str], *,
                         revit_version: Any = None,
                         call_budget_ms: int = 20_000,
                         link_title: str | None = None) -> str:
    """C# одной страницы стадии марок для КОНКРЕТНОЙ версии Revit.

    ``revit_version`` — не украшение и не необязательная подсказка: у цели
    марки нет ни одного члена, живущего во всех шести версиях, и тело,
    собранное без версии, обязано быть тем, которое соберётся на большинстве
    (см. :func:`tag_target_block_cs`).

    Пустой список id — это НЕ повод собрать тело, которое пройдёт по всему
    документу: стадия страничная, и «нет id» означает «нечего читать».

    ``link_title`` — читать не ХОЗЯИНА, а его связь с таким ``Document.Title``.
    Версия Revit и источник — РАЗНЫЕ вопросы: версия выбирает, каким членом
    API спросить цель марки, источник — у какого документа спрашивать. Оба
    приезжают снаружи, и ни один не угадывается.
    """
    quoted = ", ".join(_csharp_string(str(item)) for item in element_ids)
    body = _TAG_EXTRACT_BODY_CS
    body = body.replace("__TG_CALL_BUDGET_MS__", str(int(call_budget_ms)))
    body = body.replace("__TAG_IDS__", quoted)
    body = body.replace("__TAG_TARGET_BLOCK__",
                        tag_target_block_cs(revit_version))
    body = body.replace(
        "__ELEMENT_ID_OUT_OF_RANGE__", ELEMENT_ID_OUT_OF_RANGE_REASON)
    body = body.replace(
        "__TG_SCHEMA__", _csharp_string(TAG_EXTRACT_SCHEMA_VERSION))
    return (source_binding_cs(link_title) + "\n"
            + TAG_EXTRACT_HELPER_CS + body)


__all__ = [
    "TAG_CATEGORIES",
    "TAG_EXTRACT_SCHEMA_VERSION",
    "TAG_FAMILIES",
    "TAG_FAMILY_INDEPENDENT",
    "TAG_FAMILY_SPATIAL",
    "TAG_INDEX_SCHEMA_VERSION",
    "TAG_MULTI_REFERENCE_SINCE",
    "TAG_ORIENTATION_HORIZONTAL",
    "TAG_SUPPORTED_VERSIONS",
    "TagExtraction",
    "TagFailure",
    "TagPayloadError",
    "TagRecord",
    "build_tag_extract_cs",
    "extract_tags",
    "merge_tags",
    "tag_target_block_cs",
]
