"""Боковой индекс ОФОРМЛЕНИЯ: то, чего замороженная строка L0 не несёт.

ЗАЧЕМ ЭТА СТАДИЯ ВООБЩЕ ПОЯВИЛАСЬ. Замер 30.07 на РД-башне: 53 796 элементов
оформления ЧИТАЮТСЯ и ни один не поднимается. Причина названа самим разбором,
37 050 атомов несут её дословно — «оп есть в реестре, но L0 1.0 не несёт НИ
ОДНОГО из его обязательных входов». Операции ``create_text`` / ``create_tag`` /
``create_dimension`` написаны с 28.07 и лежат мёртвыми не потому, что кто-то
поленился написать лифтер, а потому что лифтеру НЕЧЕГО читать: в строке L0 нет
ни вида-владельца, ни ссылок, ни текста, ни координаты в плоскости вида.

ПОЧЕМУ КООРДИНАТА СЧИТАЕТСЯ НА МОСТУ, А НЕ ОФЛАЙН. Прямой ход материализует
точку вида в мир по базису САМОГО вида
(``docspace.emit_view2d_to_xyz_cs``: ``Origin + u*RightDirection +
v*UpDirection``), и базис известен только в момент исполнения. Обратное
преобразование обязано быть ТОЧНОЙ инверсией той же формулы, иначе круг не
замкнётся:

    rel = P - view.Origin
    u   = rel · view.RightDirection
    v   = rel · view.UpDirection

Эти три строки уже живут в свидетеле марки (``authoring.py``, проверено живым
замером E5 28.07) — здесь они переиспользуются ДОСЛОВНО, а не переписываются
заново. Хранить базис и проецировать офлайн было бы вторым местом, где живёт
формула, и первым местом, где она разойдётся.

ЧТО ПЕРЕСЕКАЕТ ПРОВОД. Сырые внутренние футы, как у групп: пересчёт в
миллиметры принадлежит офлайн-разборщику, и он один. Идентификаторы — строками
(32-битного числового доступа к ElementId нет с 2026).

ЧЕГО ЗДЕСЬ НЕТ И ПОЧЕМУ. ``TextNote.Width`` не документирован ни в одной из
шести версий (проверено индексом ловушек, а не памятью), поэтому ширина НЕ
снимается: параметр опа необязательный, и отсутствие остаётся отсутствием, а не
подставленным числом. Марки и размеры этой волной не снимаются — у марки шов
версий на 2022 (``TaggedLocalElementId`` до 2022 / ``GetTaggedLocalElementIds``
с 2022), и он заслуживает своей волны, а не строчки в конце этой.
"""
from __future__ import annotations

import json
from kukai.ir.emit_utils import cs_string_literal
from dataclasses import dataclass
from typing import Any, Iterator, Mapping

from kukai.ir.decompile.side_contract import (
    ELEMENT_ID_HELPER_CS,
    ELEMENT_ID_OUT_OF_RANGE_REASON,
    source_binding_cs,
)

#: Версия ПЕРСИСТЕНТНОГО индекса (то, что ложится на диск и переиспользуется
#: возобновлением). Меняется, когда меняется форма записи.
ANNOTATION_INDEX_SCHEMA_VERSION = "kir-decompile-annotation-index/1"
#: Версия ПРОВОДНОГО ответа моста. Литерал вшит в C# и сверяется при разборе:
#: чужой или устаревший ответ обязан отказать громко, а не разобраться наполовину.
ANNOTATION_EXTRACT_SCHEMA_VERSION = "kir-decompile-annotation-extract/1"

_FT_TO_MM = 304.8

#: Категории L0, которые кормит эта стадия. Одна строка — одна категория, и она
#: обязана двигаться ВМЕСТЕ со строкой в ``pipeline._STAGE_CATEGORIES``:
#: категория здесь без строки там — id никогда не запросят; строка там без
#: категории здесь — каждый id уйдёт квитанцией «не наш род».
ANNOTATION_CATEGORIES = frozenset({"OST_TextNotes"})


class AnnotationPayloadError(ValueError):
    """Проводной ответ не той формы — типизированный отказ, а не догадка."""


def _mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise AnnotationPayloadError(f"{field_name} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise AnnotationPayloadError(f"{field_name} keys must be strings")
    return dict(value)


def _array(value: Any, field_name: str) -> list[Any]:
    if not isinstance(value, list):
        raise AnnotationPayloadError(f"{field_name} must be an array")
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
        raise AnnotationPayloadError(
            f"{field_name} is missing {sorted(missing)}")
    extra = set(root) - allowed
    if extra:
        raise AnnotationPayloadError(
            f"{field_name} has unexpected {sorted(extra)}")
    return root


def _string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise AnnotationPayloadError(f"{field_name} must be a non-empty string")
    return value


def _number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AnnotationPayloadError(f"{field_name} must be a number")
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        raise AnnotationPayloadError(f"{field_name} must be finite")
    return number


def _element_id_key(value: str) -> tuple[int, int | str, str]:
    """Порядок по ЧИСЛОВОМУ id, нечисловые — в конец, но всегда детерминированно."""
    try:
        return (0, int(value), value)
    except (TypeError, ValueError):
        return (1, value, value)


@dataclass(frozen=True, slots=True)
class TextNoteRecord:
    """Одно текстовое примечание в координатах СВОЕГО вида."""

    element_id: str
    owner_view_id: str
    #: Имя вида. Не украшение: замороженный диалект ссылок L1 знает РОВНО
    #: одну именованную форму — {"by": "name", "value": <имя>, "_id": <id>}.
    #: Ссылка «по element_id» в L1 не существует, поэтому без имени вида
    #: примечание нельзя выразить вовсе (поймано тестом, а не живым прогоном).
    owner_view_name: str
    #: [u, v] мм в плоскости вида — уже спроецировано базисом вида на мосту.
    at_view_mm: tuple[float, float]
    content: str
    type_id: str | None = None
    type_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "element_id": self.element_id,
            "owner_view_id": self.owner_view_id,
            "owner_view_name": self.owner_view_name,
            "at_view_mm": [self.at_view_mm[0], self.at_view_mm[1]],
            "content": self.content,
            "type_id": self.type_id,
            "type_name": self.type_name,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "TextNoteRecord":
        root = _exact_fields(
            value,
            {"element_id", "owner_view_id", "owner_view_name", "at_view_mm",
             "content", "type_id", "type_name"},
            "text note record", optional={"type_id", "type_name"})
        at = _array(root["at_view_mm"], "text note record.at_view_mm")
        if len(at) != 2:
            raise AnnotationPayloadError(
                "text note record.at_view_mm must be [u, v] — точка вида "
                "ДВУМЕРНА, третья координата означала бы модельную точку в "
                "поле вида")
        type_id = root.get("type_id")
        if type_id is not None and not isinstance(type_id, str):
            raise AnnotationPayloadError("text note record.type_id must be a string")
        type_name = root.get("type_name")
        if type_name is not None and not isinstance(type_name, str):
            raise AnnotationPayloadError("text note record.type_name must be a string")
        content = root["content"]
        if not isinstance(content, str):
            raise AnnotationPayloadError("text note record.content must be a string")
        return cls(
            element_id=_string(root["element_id"], "text note record.element_id"),
            owner_view_id=_string(
                root["owner_view_id"], "text note record.owner_view_id"),
            owner_view_name=_string(
                root["owner_view_name"], "text note record.owner_view_name"),
            at_view_mm=(_number(at[0], "at_view_mm[0]"),
                        _number(at[1], "at_view_mm[1]")),
            content=content,
            type_id=type_id or None,
            type_name=type_name or None,
        )


@dataclass(frozen=True, slots=True)
class AnnotationFailure:
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
    def from_dict(cls, value: Any) -> "AnnotationFailure":
        root = _exact_fields(
            value, {"element_id", "reason", "typed_reason"},
            "annotation failure")
        return cls(
            element_id=_string(root["element_id"], "annotation failure.element_id"),
            reason=_string(root["reason"], "annotation failure.reason"),
            typed_reason=_string(
                root["typed_reason"], "annotation failure.typed_reason"),
        )


@dataclass(frozen=True, slots=True)
class AnnotationExtraction:
    """Проверенный боковой индекс оформления, независимый от замороженной L0."""

    text_notes: tuple[TextNoteRecord, ...] = ()
    failures: tuple[AnnotationFailure, ...] = ()

    def __post_init__(self) -> None:
        ids = [record.element_id for record in self.text_notes]
        if len(ids) != len(set(ids)):
            raise AnnotationPayloadError(
                "annotation index contains duplicate element_id")

    def __iter__(self) -> Iterator[TextNoteRecord]:
        return iter(self.text_notes)

    def __len__(self) -> int:
        return len(self.text_notes)

    @property
    def records(self) -> tuple[TextNoteRecord, ...]:
        """НЕЯВНЫЙ КОНТРАКТ БОКОВОЙ СТАДИИ, о который эта волна и споткнулась.

        Сверщик §18.2 (``pipeline._accounted_ids``) спрашивает у результата
        пачки ``records`` и ``failures``, чтобы назвать поимённо id, о
        которых стадия не сказала НИЧЕГО. Первая редакция называла своё поле
        только ``text_notes``, сверщик увидел ноль отчётов на 26 запрошенных
        примечаний и честно уронил живой прогон Snowdon с
        ``side_stage_count_mismatch``. C# при этом работал идеально — дефект
        был ровно в имени поля.

        Поэтому ``text_notes`` остаётся читаемым именем для людей, а
        ``records`` — именем контракта. Полнота контракта у ВСЕХ стадий
        проверяется тестом, чтобы следующая новая стадия падала на тестах, а
        не через сорок минут живого чтения.
        """
        return self.text_notes

    @property
    def text_note_index(self) -> dict[str, dict[str, Any]]:
        return {
            record.element_id: record.to_dict()
            for record in sorted(
                self.text_notes,
                key=lambda record: _element_id_key(record.element_id))
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": ANNOTATION_INDEX_SCHEMA_VERSION,
            "text_note_index": self.text_note_index,
            "failures": [
                failure.to_dict()
                for failure in sorted(
                    self.failures,
                    key=lambda item: (_element_id_key(item.element_id),
                                      item.reason))
            ],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, allow_nan=False,
                          separators=(",", ":"), sort_keys=True)

    @classmethod
    def from_dict(cls, value: Any) -> "AnnotationExtraction":
        root = _exact_fields(
            value, {"schema_version", "text_note_index", "failures"},
            "annotation index", optional={"failures"})
        if root["schema_version"] != ANNOTATION_INDEX_SCHEMA_VERSION:
            raise AnnotationPayloadError("annotation index schema_version mismatch")
        index = _mapping(root["text_note_index"], "annotation index.text_note_index")
        records = []
        for key, row in index.items():
            record = TextNoteRecord.from_dict(row)
            if record.element_id != key:
                raise AnnotationPayloadError(
                    "annotation index key does not match record.element_id")
            records.append(record)
        failures = tuple(
            AnnotationFailure.from_dict(row)
            for row in _array(root.get("failures") or [],
                              "annotation index.failures"))
        return cls(text_notes=tuple(records), failures=failures)

    @classmethod
    def from_json(cls, text: str) -> "AnnotationExtraction":
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise AnnotationPayloadError(
                f"annotation index is not valid JSON: {exc}") from exc
        return cls.from_dict(value)


def _unwrap_bridge_payload(payload: Any) -> Any:
    """Мост заворачивает ответ в ``{"payload": ...}`` — разворачиваем ОДИН раз."""
    if isinstance(payload, Mapping) and "payload" in payload \
            and "schema_version" not in payload:
        return payload["payload"]
    return payload


def extract_annotations(payload: Any) -> AnnotationExtraction:
    """Проверить один ответ моста и собрать индекс.

    Порча формы провода — типизированное исключение. Честный отказ по КОНКРЕТНОМУ
    элементу — строка квитанции, а не исключение: стадия обязана дочитать
    остальное и назвать пропущенное.
    """
    root = _exact_fields(
        _unwrap_bridge_payload(payload),
        {"schema_version", "elements", "failures"},
        "Annotation extraction", optional={"failures"})
    if root["schema_version"] != ANNOTATION_EXTRACT_SCHEMA_VERSION:
        raise AnnotationPayloadError("Annotation extraction schema_version mismatch")

    records: list[TextNoteRecord] = []
    for index, row in enumerate(_array(root["elements"],
                                       "Annotation extraction.elements")):
        item = _exact_fields(
            row,
            {"element_id", "owner_view_id", "owner_view_name", "at_view_ft",
             "content", "type_id", "type_name"},
            f"Annotation extraction.elements[{index}]",
            optional={"type_id", "type_name"})
        at = _array(item["at_view_ft"], f"elements[{index}].at_view_ft")
        if len(at) != 2:
            raise AnnotationPayloadError(
                f"elements[{index}].at_view_ft must be [u, v]")
        content = item["content"]
        if not isinstance(content, str):
            raise AnnotationPayloadError(f"elements[{index}].content must be a string")
        type_id = item.get("type_id")
        if type_id is not None and not isinstance(type_id, str):
            raise AnnotationPayloadError(f"elements[{index}].type_id must be a string")
        type_name = item.get("type_name")
        if type_name is not None and not isinstance(type_name, str):
            raise AnnotationPayloadError(f"elements[{index}].type_name must be a string")
        records.append(TextNoteRecord(
            element_id=_string(item["element_id"], f"elements[{index}].element_id"),
            owner_view_id=_string(
                item["owner_view_id"], f"elements[{index}].owner_view_id"),
            owner_view_name=_string(
                item["owner_view_name"], f"elements[{index}].owner_view_name"),
            # ПЕРЕСЧЁТ ЖИВЁТ ЗДЕСЬ И ТОЛЬКО ЗДЕСЬ: провод несёт сырые футы.
            at_view_mm=(
                _number(at[0], f"elements[{index}].at_view_ft[0]") * _FT_TO_MM,
                _number(at[1], f"elements[{index}].at_view_ft[1]") * _FT_TO_MM),
            content=content,
            type_id=type_id or None,
            type_name=type_name or None,
        ))

    failures = tuple(
        AnnotationFailure.from_dict(row)
        for row in _array(root.get("failures") or [],
                          "Annotation extraction.failures"))
    return AnnotationExtraction(text_notes=tuple(records), failures=failures)


def merge_annotations(parts: list[AnnotationExtraction]) -> AnnotationExtraction:
    """Склеить страницы одной стадии, не потеряв ни записи, ни квитанции."""
    records: list[TextNoteRecord] = []
    failures: list[AnnotationFailure] = []
    seen: set[str] = set()
    for part in parts:
        for record in part.text_notes:
            # Страницы не обязаны быть непересекающимися по построению — но
            # если пересеклись, побеждает ПЕРВАЯ прочитанная, а не последняя:
            # «последняя выигрывает» делает результат зависимым от порядка
            # страниц, то есть от сети.
            if record.element_id in seen:
                continue
            seen.add(record.element_id)
            records.append(record)
        failures.extend(part.failures)
    return AnnotationExtraction(text_notes=tuple(records),
                                failures=tuple(failures))


def _csharp_string(value: str) -> str:
    return cs_string_literal(value)


ANNOTATION_EXTRACT_HELPER_CS = r"""
// KIR DECOMPILE — read-only annotation helpers. Никаких транзакций.
// Точка вида считается ТОЙ ЖЕ формулой, что и свидетель марки:
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
Func<object, string> __anClassName = (__ancnObj) =>
{
    if (__ancnObj == null) return "";
    string __ancn = __ancnObj.ToString();
    if (__ancn == null) return "";
    int __ancnCut = __ancn.IndexOf((char)10);
    if (__ancnCut >= 0) __ancn = __ancn.Substring(0, __ancnCut);
    __ancnCut = __ancn.IndexOf(':');
    if (__ancnCut >= 0) __ancn = __ancn.Substring(0, __ancnCut);
    __ancn = __ancn.Trim();
    __ancnCut = __ancn.LastIndexOf('.');
    return __ancnCut >= 0 && __ancnCut + 1 < __ancn.Length
        ? __ancn.Substring(__ancnCut + 1) : __ancn;
};
Func<ElementId, string> __anValidIdString = (__id) =>
    (__id == null || __id == ElementId.InvalidElementId)
        ? null : __id.ToString();
Func<double, bool> __anFinite = (__value) =>
    !Double.IsNaN(__value) && !Double.IsInfinity(__value);
""" + ELEMENT_ID_HELPER_CS + "\n"


_ANNOTATION_EXTRACT_BODY_CS = r"""
long __anCallBudgetMs = __AN_CALL_BUDGET_MS__L;
long __anCallWatchT0 = DateTime.UtcNow.Ticks;

var __anFailures = new List<object>();
Action<string, string, string> __anFail =
    (__failedId, __reason, __typed) =>
{
    var __failure = new Dictionary<string, object>();
    __failure["element_id"] = __failedId;
    __failure["reason"] = __reason;
    __failure["typed_reason"] = __typed;
    __anFailures.Add(__failure);
};

var __anIds = new List<string> { __ANNOTATION_IDS__ };
var __anRows = new List<object>();
bool __anBudgetOut = false;
foreach (string __anRaw in __anIds)
{
    if (__anBudgetOut
        || ((DateTime.UtcNow.Ticks - __anCallWatchT0) / TimeSpan.TicksPerMillisecond) >= __anCallBudgetMs)
    {
        __anBudgetOut = true;
        __anFail(__anRaw, "call_budget_exhausted", "call_budget_exhausted");
        continue;
    }
    // ИМЯ ШАГА, КОТОРЫЙ СЕЙЧАС ИДЁТ. Урок 2846 групп: тип исключения без
    // имени вызова — одно ведро на всё, и по нему нельзя сказать ни ЧТО
    // читали, ни ЧТО ответил Revit.
    string __anStep = "ElementId.Parse";
    try
    {
        long __anNum = 0L;
        if (!Int64.TryParse(__anRaw, out __anNum))
        {
            __anFail(__anRaw, "element id is not numeric", "element_unresolved");
            continue;
        }
        __anStep = "Document.GetElement";
        ElementId __anId = __sideElementId(__anNum);
        if (__anId == null)
        {
            __anFail(__anRaw, "__ELEMENT_ID_OUT_OF_RANGE__", "element_unresolved");
            continue;
        }
        Element __anEl = __src.GetElement(__anId);
        if (__anEl == null)
        {
            __anFail(__anRaw, "element not found in document", "element_unresolved");
            continue;
        }
        __anStep = "cast to TextElement";
        Autodesk.Revit.DB.TextElement __anText =
            __anEl as Autodesk.Revit.DB.TextElement;
        if (__anText == null)
        {
            __anFail(__anRaw,
                     "not a TextElement: " + __anClassName(__anEl),
                     "element_kind_mismatch");
            continue;
        }
        __anStep = "Element.OwnerViewId";
        ElementId __anViewId = __anEl.OwnerViewId;
        string __anViewIdStr = __anValidIdString(__anViewId);
        if (__anViewIdStr == null)
        {
            // Аннотация без вида-владельца невыразима принципиально: точка
            // вида существует ТОЛЬКО в плоскости конкретного вида.
            __anFail(__anRaw, "annotation has no owner view", "aspect_not_present");
            continue;
        }
        __anStep = "GetElement(OwnerViewId) as View";
        Autodesk.Revit.DB.View __anView =
            __src.GetElement(__anViewId) as Autodesk.Revit.DB.View;
        if (__anView == null)
        {
            __anFail(__anRaw, "owner view is not a View element", "element_unresolved");
            continue;
        }
        __anStep = "View basis (Origin/RightDirection/UpDirection)";
        XYZ __anOrigin = __anView.Origin;
        XYZ __anRight = __anView.RightDirection;
        XYZ __anUp = __anView.UpDirection;
        if (__anOrigin == null || __anRight == null || __anUp == null)
        {
            __anFail(__anRaw, "view basis is unavailable", "aspect_not_present");
            continue;
        }
        __anStep = "TextElement.Coord";
        XYZ __anCoord = __anText.Coord;
        if (__anCoord == null)
        {
            __anFail(__anRaw, "text note has no Coord", "aspect_not_present");
            continue;
        }
        __anStep = "project onto view basis";
        XYZ __anRel = __anCoord - __anOrigin;
        double __anU = __anRel.DotProduct(__anRight);
        double __anV = __anRel.DotProduct(__anUp);
        if (!__anFinite(__anU) || !__anFinite(__anV))
        {
            __anFail(__anRaw, "projected view point is not finite", "aspect_not_present");
            continue;
        }
        __anStep = "TextElement.Text";
        string __anContent = __anText.Text;
        if (__anContent == null)
        {
            __anFail(__anRaw, "text note has no Text", "aspect_not_present");
            continue;
        }
        __anStep = "View.Name";
        string __anViewName = __anView.Name;
        if (String.IsNullOrEmpty(__anViewName))
        {
            // Диалект ссылок L1 именованный: вид без имени невыразим.
            __anFail(__anRaw, "owner view has no name", "aspect_not_present");
            continue;
        }
        __anStep = "Element.GetTypeId";
        string __anTypeId = __anValidIdString(__anEl.GetTypeId());
        string __anTypeName = null;
        if (__anTypeId != null)
        {
            __anStep = "type element Name";
            Element __anTypeEl = __src.GetElement(__anEl.GetTypeId());
            if (__anTypeEl != null) __anTypeName = __anTypeEl.Name;
        }

        var __anRow = new Dictionary<string, object>();
        __anRow["element_id"] = __anRaw;
        __anRow["owner_view_id"] = __anViewIdStr;
    __anRow["owner_view_name"] = __anViewName;
        __anRow["at_view_ft"] = (object)new double[] { __anU, __anV };
        __anRow["content"] = __anContent;
        __anRow["type_id"] = __anTypeId;
    __anRow["type_name"] = __anTypeName;
        __anRows.Add(__anRow);
    }
    catch (Exception __anEx)
    {
        __anFail(__anRaw,
                 "annotation read failed at " + __anStep + ": "
                     + __anClassName(__anEx),
                 "read_failed");
    }
}

var __anPayload = new Dictionary<string, object>();
__anPayload["schema_version"] = __AN_SCHEMA__;
__anPayload["elements"] = __anRows;
__anPayload["failures"] = __anFailures;
return __anPayload;
"""


def build_annotation_extract_cs(element_ids: list[str], *,
                                call_budget_ms: int = 20_000,
                                link_title: str | None = None) -> str:
    """C# одной страницы стадии оформления.

    Пустой список id — это НЕ повод собрать тело, которое пройдёт по всему
    документу: стадия страничная, и «нет id» означает «нечего читать».

    ``link_title`` — читать не ХОЗЯИНА, а его связь с таким ``Document.Title``.
    Замер 30.07 на связанной электрике: 89 квитанций стадии, из них 87
    ``element_unresolved`` — id связи искались в документе хозяина. Вид-хозяин
    примечания и тип примечания читаются ТЕМ ЖЕ ``__src``: вид из другого
    документа сделал бы точку примечания бессмысленной, не назвав причины.
    """
    quoted = ", ".join(_csharp_string(str(item)) for item in element_ids)
    body = _ANNOTATION_EXTRACT_BODY_CS
    body = body.replace("__AN_CALL_BUDGET_MS__", str(int(call_budget_ms)))
    body = body.replace("__ANNOTATION_IDS__", quoted)
    body = body.replace(
        "__ELEMENT_ID_OUT_OF_RANGE__", ELEMENT_ID_OUT_OF_RANGE_REASON)
    body = body.replace(
        "__AN_SCHEMA__", _csharp_string(ANNOTATION_EXTRACT_SCHEMA_VERSION))
    return (source_binding_cs(link_title) + "\n"
            + ANNOTATION_EXTRACT_HELPER_CS + body)
