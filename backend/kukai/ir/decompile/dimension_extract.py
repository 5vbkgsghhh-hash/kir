"""Боковой индекс РАЗМЕРОВ: единственная настоящая дыра ЧТЕНИЯ из трёх.

ПОВОД — ПЕРЕПОДЪЁМ, А НЕ ПЛАН. Ранжирование, с которым волна начиналась,
называло три дыры чтения: ``create_tag`` (20 459), ``create_dimension``
(13 908) и ``create_text`` (2 786) — все три «операция написана, а L0 не несёт
НИ ОДНОГО её входа». Переподъём ``backend/data/decompile/k2_ar_rd_v8``
текущим лифтом сказал другое, и считано это по строкам ``atom_details``, а не
по памяти::

    13905  create_dimension ... L0 1.0 не несёт НИ ОДНОГО из его входов
      317  create_tag ... L0 1.0 не несёт НИ ОДНОГО из его входов
        0  create_text  (2697 из 2697 подняты в create_text)

Из трёх «дыр чтения» две были закрыты ещё до этой волны: стадия оформления
читает все 2 697 примечаний, стадия марок — 20 131 марку из 20 448.
Оставшиеся 19 280 марок отказывают по причинам ПРЯМОГО хода (11 594
SpatialElementTag, 4 122 выноска, 3 564 ориентация), а не потому, что их
нечем прочесть. Стадии размеров не существовало вовсе — 13 905 из 13 905 —
и это ровно та дыра, за которую волну заводили.

ЧТО ЧИТАЕТСЯ И ЧЕМ ЭТО ДОКАЗАНО. Ни одного имени по памяти: каждый член ниже
назван КОМПИЛЯТОРОМ через намеренную ошибку CS0029 (приём
``tests/emitted_csharp_signature_closure`` — компилятор обязан НАЗВАТЬ тип,
чтобы отказать), проверено на 2021, 2023 и 2026::

    Dimension.References       -> Autodesk.Revit.DB.ReferenceArray
    Dimension.Curve            -> Autodesk.Revit.DB.Curve
    Dimension.Origin           -> Autodesk.Revit.DB.XYZ
    Dimension.NumberOfSegments -> int
    Dimension.DimensionShape   -> Autodesk.Revit.DB.DimensionShape
    Reference.ElementId        -> Autodesk.Revit.DB.ElementId
    Element.OwnerViewId        -> Autodesk.Revit.DB.ElementId

ЛОВУШКИ ``System.dll`` ЗДЕСЬ НЕТ, И ЭТО ПРОВЕРЕНО, А НЕ ПРЕДПОЛОЖЕНО. Стадия
марок умерла живьём 04.08 на ``CS0012: The type ISet<> is defined in an
assembly that is not referenced`` — ``GetTaggedLocalElementIds`` возвращает
``ISet<>`` из ``System.dll``, которой нет в замыкании ссылок РАЗВЁРНУТОГО
плагина. Поэтому ПЕРВОЕ, что здесь спрошено у компилятора, — тип
``Dimension.References``: ``ReferenceArray`` живёт в ``RevitAPI.dll``, и
``foreach (Reference r in d.References)`` собирается на 2021 и 2023.

``ElementId.IntegerValue`` НЕ ИСПОЛЬЗУЕТСЯ: на 2026 это ``CS1061`` (замерено
тем же прогоном). Id едет строкой через ``ElementId.ToString()``, как во всех
соседних стадиях.

ПОЧЕМУ ``line_at`` ЗАМЫКАЕТСЯ ТОЖДЕСТВОМ, А НЕ СОВПАДЕНИЕМ. У прямого хода
``line_at`` — это ОДНА точка-ЯКОРЬ, через которую проходит линия размера;
направление прямой ход берёт из нормали первой ссылки, а не из неё. Его же
докстринг (``authoring._emit_dimension``) ссылается на Revit API Developer
Guide: ``Dimension.Curve`` ВСЕГДА НЕОГРАНИЧЕНА (unbound), и положение
``Origin`` ВДОЛЬ линии — эмерджентное свойство того, куда проецируются
ссылки, а не наш вход. Значит обратному ходу довольно ЛЮБОЙ точки на этой
линии, а ``Dimension.Origin`` («средняя точка линии размера») ею является по
определению. Круг замыкается тем же базисом вида
(``rel = P - view.Origin; u = rel*Right; v = rel*Up``), которым его замыкают
марки и примечания.

ПО ЭТОЙ ЖЕ ПРИЧИНЕ ЗДЕСЬ НЕТ ``GetEndPoint``: у неограниченной кривой он
бросает. Из ``Dimension.Curve`` берётся ``Line.Origin`` и только он, и только
как запасной ход, если ``Origin`` не ответил.

ЧЕГО ЗДЕСЬ НЕТ И ПОЧЕМУ. ``SpotDimension`` (высотная отметка) — ПОДКЛАСС
``Dimension``, но прямой ход строит размер ровно одним способом,
``doc.Create.NewDimension``; отметка — элемент другого класса, и пересборка
дала бы не тот элемент. Отказ типизирован (``element_kind_mismatch``), а не
«почти то же». Категория отметок отдельная (``OST_SpotElevations``, 2 292
элемента в том же документе) и в эту стадию не входит.

ЧЕГО ЭТА СТАДИЯ НЕ РЕШАЕТ (названо, а не спрятано). ``refs`` опа — это
ЭЛЕМЕНТЫ, а ``NewDimension`` требует ГЕОМЕТРИЧЕСКИХ ссылок (грань/ребро);
грань выбирает прямой ход своим обходом. Значит обратный ход записывает,
МЕЖДУ ЧЕМ был размер, но не то, ПО КАКИМ ГРАНЯМ он был проведён. Совпадёт ли
ЧИСЛО после пересборки — вопрос ЖИВОГО сеанса, а не этого файла: здесь
записывается ровно прочитанное, и ни одного поля сверх него.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator, Mapping

from kukai.ir.emit_utils import cs_string_literal
from kukai.ir.decompile.side_contract import (
    ELEMENT_ID_HELPER_CS,
    ELEMENT_ID_OUT_OF_RANGE_REASON,
    source_binding_cs,
)

DIMENSION_INDEX_SCHEMA_VERSION = "kir-decompile-dimension-index/1"
DIMENSION_EXTRACT_SCHEMA_VERSION = "kir-decompile-dimension-extract/1"

#: Категории, которые кормит стадия. Двигается ВМЕСТЕ со строкой в
#: ``pipeline._STAGE_CATEGORIES``: категория здесь без строки там — id никогда
#: не запросят; строка там без категории здесь — каждый id уйдёт квитанцией.
#:
#: РОВНО ОДНА, и это не скупость. ``OST_SpotElevations`` (2 292) и
#: ``OST_WeakDims`` (19 547) стоят в переписи ТОГО ЖЕ документа и
#: компилируются, но первое — другой класс элемента для ПРЯМОГО хода, а
#: второе — автонанесение внутри эскиза, у которого самостоятельной операции
#: нет вовсе. Закрытый список не место для догадок (то же правило, по
#: которому 28.07 в таблицу категорий не пустили ``OST_CurtainGrids``).
DIMENSION_CATEGORIES = frozenset({"OST_Dimensions"})

#: Наименьшее число ссылок, из которого размер вообще состоит. Размер с одной
#: ссылкой нечего измерять, и ``create_dimension`` такой не построит.
DIMENSION_MIN_REFS = 2

#: Единственная форма размера, которую строит ПРЯМОЙ ход: он знает ровно
#: ``doc.Create.NewDimension(view, Line, ReferenceArray)``, а это линейный
#: размер. Имя члена ``Autodesk.Revit.DB.DimensionShape.Linear`` названо
#: компилятором на 2021 и 2026, а не взято из документации.
#:
#: Константа живёт ЗДЕСЬ, а не в лифте, по той же причине, по которой здесь же
#: живут категории: строка, записанная в одном месте и забытая в другом, —
#: это либо немой отказ, либо покрытие, которого нет.
DIMENSION_SHAPE_LINEAR = "Linear"

_FT_TO_MM = 304.8


class DimensionPayloadError(ValueError):
    """Проводной ответ не той формы — типизированный отказ, а не догадка."""


def _mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise DimensionPayloadError(f"{field_name} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise DimensionPayloadError(f"{field_name} keys must be strings")
    return dict(value)


def _array(value: Any, field_name: str) -> list[Any]:
    if not isinstance(value, list):
        raise DimensionPayloadError(f"{field_name} must be an array")
    return value


def _exact_fields(value: Any, allowed: set[str], field_name: str, *,
                  optional: set[str] | None = None) -> dict[str, Any]:
    root = _mapping(value, field_name)
    optional = optional or set()
    missing = allowed - optional - set(root)
    if missing:
        raise DimensionPayloadError(f"{field_name} is missing {sorted(missing)}")
    extra = set(root) - allowed
    if extra:
        raise DimensionPayloadError(
            f"{field_name} has unexpected {sorted(extra)}")
    return root


def _string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise DimensionPayloadError(f"{field_name} must be a non-empty string")
    return value


def _number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DimensionPayloadError(f"{field_name} must be a number")
    return float(value)


def _nonnegative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DimensionPayloadError(
            f"{field_name} must be a non-negative integer")
    return value


def _element_id_key(value: str) -> tuple[int, int | str, str]:
    try:
        return (0, int(value), value)
    except (TypeError, ValueError):
        return (1, value, value)


@dataclass(frozen=True, slots=True)
class DimensionRecord:
    """Один размер: вид, точка на линии, и МЕЖДУ ЧЕМ он проведён."""

    element_id: str
    #: Вид-владелец (``Element.OwnerViewId``). ЗАКОН ПРИВЯЗКИ К ВИДУ: точка
    #: вида существует только в плоскости своего вида.
    owner_view_id: str
    #: Имя вида. Диалект ссылок L1 знает ровно одну именованную форму
    #: ``{"by": "name", "value": <имя>, "_id": <id>}`` — без имени ссылку не
    #: собрать.
    owner_view_name: str
    #: Точка НА ЛИНИИ размера в координатах вида, миллиметры. Якорь, а не
    #: середина отрезка: положение вдоль линии эмерджентно (см. модульный
    #: докстринг).
    line_at_view_mm: tuple[float, float]
    #: Элементы, между которыми проведён размер, в порядке ``References``.
    #: Порядок Revit сохраняется дословно: ``NewDimension`` строит
    #: многосегментный размер именно по порядку ссылок.
    ref_element_ids: tuple[str, ...]
    #: ``Dimension.NumberOfSegments``. Сегментов на единицу меньше, чем
    #: ссылок, у линейного размера; расхождение — улика, которую живой сеанс
    #: обязан объяснить, поэтому число едет, а не выводится.
    segment_count: int
    #: ``Dimension.DimensionShape`` строкой (Linear / Radial / Angular / …).
    #: Прямой ход строит ЛИНЕЙНЫЙ; остальное поднимать нечем, и решает это
    #: лифт, а не съёмщик: съёмщик обязан прочитать и назвать.
    dimension_shape: str
    type_id: str | None = None
    type_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "element_id": self.element_id,
            "owner_view_id": self.owner_view_id,
            "owner_view_name": self.owner_view_name,
            "line_at_view_mm": [
                float(self.line_at_view_mm[0]), float(self.line_at_view_mm[1])],
            "ref_element_ids": list(self.ref_element_ids),
            "segment_count": self.segment_count,
            "dimension_shape": self.dimension_shape,
        }
        if self.type_id is not None:
            payload["type_id"] = self.type_id
        if self.type_name is not None:
            payload["type_name"] = self.type_name
        return payload

    @classmethod
    def from_dict(cls, value: Any) -> "DimensionRecord":
        root = _exact_fields(
            value,
            {"element_id", "owner_view_id", "owner_view_name",
             "line_at_view_mm", "ref_element_ids", "segment_count",
             "dimension_shape", "type_id", "type_name"},
            "dimension record", optional={"type_id", "type_name"})
        at = _array(root["line_at_view_mm"], "dimension record.line_at_view_mm")
        if len(at) != 2:
            raise DimensionPayloadError(
                "dimension record.line_at_view_mm must be [u, v]")
        refs = _array(root["ref_element_ids"],
                      "dimension record.ref_element_ids")
        if len(refs) < DIMENSION_MIN_REFS:
            raise DimensionPayloadError(
                "dimension record.ref_element_ids needs at least "
                f"{DIMENSION_MIN_REFS} entries")
        type_id = root.get("type_id")
        if type_id is not None and not isinstance(type_id, str):
            raise DimensionPayloadError(
                "dimension record.type_id must be a string")
        type_name = root.get("type_name")
        if type_name is not None and not isinstance(type_name, str):
            raise DimensionPayloadError(
                "dimension record.type_name must be a string")
        return cls(
            element_id=_string(root["element_id"],
                               "dimension record.element_id"),
            owner_view_id=_string(root["owner_view_id"],
                                  "dimension record.owner_view_id"),
            owner_view_name=_string(root["owner_view_name"],
                                    "dimension record.owner_view_name"),
            line_at_view_mm=(
                _number(at[0], "dimension record.line_at_view_mm[0]"),
                _number(at[1], "dimension record.line_at_view_mm[1]")),
            ref_element_ids=tuple(
                _string(item, f"dimension record.ref_element_ids[{index}]")
                for index, item in enumerate(refs)),
            segment_count=_nonnegative_int(
                root["segment_count"], "dimension record.segment_count"),
            dimension_shape=_string(root["dimension_shape"],
                                    "dimension record.dimension_shape"),
            type_id=type_id or None,
            type_name=type_name or None,
        )


@dataclass(frozen=True, slots=True)
class DimensionFailure:
    """Квитанция: «не прочитали — и вот почему». Молчание запрещено (§18.2)."""

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
    def from_dict(cls, value: Any) -> "DimensionFailure":
        root = _exact_fields(
            value, {"element_id", "reason", "typed_reason"},
            "dimension failure")
        return cls(
            element_id=_string(root["element_id"],
                               "dimension failure.element_id"),
            reason=_string(root["reason"], "dimension failure.reason"),
            typed_reason=_string(root["typed_reason"],
                                 "dimension failure.typed_reason"),
        )


@dataclass(frozen=True, slots=True)
class DimensionExtraction:
    """Результат стадии.

    ``records`` и ``failures`` — ИМЕНА, КОТОРЫМИ СПРАШИВАЕТ СВЕРЩИК §18.2, и
    они здесь не случайны. Стадия оформления назвала своё поле ``text_notes``,
    её C# отработал на мосту идеально, а полный прогон упал через полторы
    минуты на ``side_stage_count_mismatch: запрошено 26, без строки и без
    квитанции 26``. ``dimensions`` оставлено как ЧИТАЕМОЕ имя, а ``records``
    отвечает сверщику — ровно как ``tags``/``records`` у стадии марок.
    """

    dimensions: tuple[DimensionRecord, ...] = ()
    failures: tuple[DimensionFailure, ...] = ()

    @property
    def records(self) -> tuple[DimensionRecord, ...]:
        return self.dimensions

    @property
    def dimension_index(self) -> dict[str, dict[str, Any]]:
        """id -> строка. Адрес лифта: он спрашивает по element_id.

        **СТРОИТ ВЕСЬ СЛОВАРЬ НА КАЖДОЕ ОБРАЩЕНИЕ — O(n), а не поле.**
        Читать РОВНО ОДИН РАЗ в локальную переменную; обращение изнутри
        включения или цикла делает работу квадратичной. Живьём 2026-08-12:
        `to_dict` читал это свойство на каждый ключ, и на 13 905 размерах
        башни стадия сериализовалась 20+ минут, не дойдя до записи файла
        (`tools`-стек: `to_dict → dimension_index → to_dict → _persist_json`).
        Замер: n=500 0.21 с, 1000 1.06, 2000 4.62, 4000 21.26 — ×4.6 на
        удвоение. Голдены гоняют 2–5 записей, где квадрат неотличим от
        линии, поэтому офлайн его увидеть не мог.
        """
        return {record.element_id: record.to_dict()
                for record in self.dimensions}

    def to_dict(self) -> dict[str, Any]:
        # ОДНО обращение к свойству; см. его докстроку — оно O(n).
        index = self.dimension_index
        return {
            "schema_version": DIMENSION_INDEX_SCHEMA_VERSION,
            "dimension_index": {
                key: index[key]
                for key in sorted(index, key=_element_id_key)},
            "failures": [failure.to_dict()
                         for failure in sorted(
                             self.failures,
                             key=lambda item: _element_id_key(
                                 item.element_id))],
        }

    @classmethod
    def from_dict(cls, value: Any) -> "DimensionExtraction":
        root = _exact_fields(
            value, {"schema_version", "dimension_index", "failures"},
            "dimension extraction", optional={"failures"})
        if root["schema_version"] != DIMENSION_INDEX_SCHEMA_VERSION:
            raise DimensionPayloadError(
                "dimension extraction schema_version mismatch")
        index = _mapping(root["dimension_index"],
                         "dimension extraction.dimension_index")
        records = []
        for key, row in index.items():
            record = DimensionRecord.from_dict(row)
            if record.element_id != key:
                raise DimensionPayloadError(
                    f"dimension_index[{key!r}] holds element_id "
                    f"{record.element_id!r}")
            records.append(record)
        failures = tuple(
            DimensionFailure.from_dict(row)
            for row in _array(root.get("failures") or [],
                              "dimension extraction.failures"))
        return cls(dimensions=tuple(records), failures=failures)


def extract_dimensions(payload: Any) -> DimensionExtraction:
    """Проверить один ответ моста и собрать индекс.

    Порча формы провода — типизированное исключение. Честный отказ по
    КОНКРЕТНОМУ элементу — строка квитанции, а не исключение: стадия обязана
    дочитать остальное и назвать пропущенное.
    """
    root = _exact_fields(
        _unwrap_bridge_payload(payload),
        {"schema_version", "elements", "failures"},
        "Dimension extraction", optional={"failures"})
    if root["schema_version"] != DIMENSION_EXTRACT_SCHEMA_VERSION:
        raise DimensionPayloadError(
            "Dimension extraction schema_version mismatch")

    records: list[DimensionRecord] = []
    for index, row in enumerate(_array(root["elements"],
                                       "Dimension extraction.elements")):
        item = _exact_fields(
            row,
            {"element_id", "owner_view_id", "owner_view_name",
             "line_at_view_ft", "ref_element_ids", "segment_count",
             "dimension_shape", "type_id", "type_name"},
            f"Dimension extraction.elements[{index}]",
            optional={"type_id", "type_name"})
        at = _array(item["line_at_view_ft"],
                    f"elements[{index}].line_at_view_ft")
        if len(at) != 2:
            raise DimensionPayloadError(
                f"elements[{index}].line_at_view_ft must be [u, v]")
        refs = _array(item["ref_element_ids"],
                      f"elements[{index}].ref_element_ids")
        if len(refs) < DIMENSION_MIN_REFS:
            raise DimensionPayloadError(
                f"elements[{index}].ref_element_ids needs at least "
                f"{DIMENSION_MIN_REFS} entries")
        type_id = item.get("type_id")
        if type_id is not None and not isinstance(type_id, str):
            raise DimensionPayloadError(
                f"elements[{index}].type_id must be a string")
        type_name = item.get("type_name")
        if type_name is not None and not isinstance(type_name, str):
            raise DimensionPayloadError(
                f"elements[{index}].type_name must be a string")
        records.append(DimensionRecord(
            element_id=_string(item["element_id"],
                               f"elements[{index}].element_id"),
            owner_view_id=_string(item["owner_view_id"],
                                  f"elements[{index}].owner_view_id"),
            owner_view_name=_string(item["owner_view_name"],
                                    f"elements[{index}].owner_view_name"),
            # ПЕРЕСЧЁТ ЖИВЁТ ЗДЕСЬ И ТОЛЬКО ЗДЕСЬ: провод несёт сырые футы.
            line_at_view_mm=(
                _number(at[0], f"elements[{index}].line_at_view_ft[0]")
                * _FT_TO_MM,
                _number(at[1], f"elements[{index}].line_at_view_ft[1]")
                * _FT_TO_MM),
            ref_element_ids=tuple(
                _string(value, f"elements[{index}].ref_element_ids[{position}]")
                for position, value in enumerate(refs)),
            segment_count=_nonnegative_int(
                item["segment_count"], f"elements[{index}].segment_count"),
            dimension_shape=_string(item["dimension_shape"],
                                    f"elements[{index}].dimension_shape"),
            type_id=type_id or None,
            type_name=type_name or None,
        ))

    failures = tuple(
        DimensionFailure.from_dict(row)
        for row in _array(root.get("failures") or [],
                          "Dimension extraction.failures"))
    return DimensionExtraction(dimensions=tuple(records), failures=failures)


def merge_dimensions(parts: list[DimensionExtraction]) -> DimensionExtraction:
    """Склеить страницы одной стадии, не потеряв ни записи, ни квитанции."""
    records: list[DimensionRecord] = []
    failures: list[DimensionFailure] = []
    seen: set[str] = set()
    for part in parts:
        for record in part.dimensions:
            # Побеждает ПЕРВАЯ прочитанная, а не последняя: «последняя
            # выигрывает» сделало бы результат зависимым от порядка страниц,
            # то есть от сети.
            if record.element_id in seen:
                continue
            seen.add(record.element_id)
            records.append(record)
        failures.extend(part.failures)
    return DimensionExtraction(dimensions=tuple(records),
                               failures=tuple(failures))


def parse_dimension_index(payload: Any) -> DimensionExtraction:
    """Персистентный конверт с диска -> результат стадии."""
    return DimensionExtraction.from_dict(payload)


def _unwrap_bridge_payload(payload: Any) -> Any:
    """Мост оборачивает ответ в конверт; стадия читает и голый словарь."""
    value = payload
    for _ in range(4):
        if not isinstance(value, Mapping):
            break
        if "schema_version" in value:
            return value
        for key in ("result", "value", "payload", "data"):
            if key in value:
                value = value[key]
                break
        else:
            break
    return value


def _csharp_string(value: str) -> str:
    return cs_string_literal(value)


DIMENSION_EXTRACT_HELPER_CS = r"""
// KIR DECOMPILE — read-only dimension helpers. Никаких транзакций.
// Точка на линии считается ТОЙ ЖЕ формулой, что и прямой эмиттер:
//   rel = P - view.Origin;  u = rel·view.RightDirection;  v = rel·view.UpDirection
// Провод несёт СЫРЫЕ футы; пересчёт в мм принадлежит офлайн-разборщику.
//
// Имя класса берётся из Object.ToString() БЕЗ обращения к среде выполнения за
// типом: та форма записи целиком отвергается валидатором безопасности моста
// версий до 06.07.2026, который всё ещё стоит на части флота. Приём и его
// обоснование дословно те же, что в tag_extract.py.
Func<object, string> __dmClassName = (__dmcnObj) =>
{
    if (__dmcnObj == null) return "";
    string __dmcn = __dmcnObj.ToString();
    if (__dmcn == null) return "";
    int __dmcnCut = __dmcn.IndexOf((char)10);
    if (__dmcnCut >= 0) __dmcn = __dmcn.Substring(0, __dmcnCut);
    __dmcnCut = __dmcn.IndexOf(':');
    if (__dmcnCut >= 0) __dmcn = __dmcn.Substring(0, __dmcnCut);
    __dmcn = __dmcn.Trim();
    __dmcnCut = __dmcn.LastIndexOf('.');
    return __dmcnCut >= 0 && __dmcnCut + 1 < __dmcn.Length
        ? __dmcn.Substring(__dmcnCut + 1) : __dmcn;
};
// ElementId.IntegerValue НЕ ИСПОЛЬЗУЕТСЯ: на 2026 это CS1061 (замерено).
Func<ElementId, string> __dmValidIdString = (__id) =>
    (__id == null || __id == ElementId.InvalidElementId)
        ? null : __id.ToString();
Func<double, bool> __dmFinite = (__value) =>
    !Double.IsNaN(__value) && !Double.IsInfinity(__value);
"""


_DIMENSION_EXTRACT_BODY_CS = r"""
long __dmCallBudgetMs = __DM_CALL_BUDGET_MS__L;
long __dmCallWatchT0 = DateTime.UtcNow.Ticks;

var __dmFailures = new List<object>();
Action<string, string, string> __dmFail =
    (__failedId, __reason, __typed) =>
{
    var __failure = new Dictionary<string, object>();
    __failure["element_id"] = __failedId;
    __failure["reason"] = __reason;
    __failure["typed_reason"] = __typed;
    __dmFailures.Add(__failure);
};

var __dmIds = new List<string> { __DIMENSION_IDS__ };
var __dmRows = new List<object>();
bool __dmBudgetOut = false;
foreach (string __dmRaw in __dmIds)
{
    if (__dmBudgetOut
        || ((DateTime.UtcNow.Ticks - __dmCallWatchT0) / TimeSpan.TicksPerMillisecond) >= __dmCallBudgetMs)
    {
        __dmBudgetOut = true;
        __dmFail(__dmRaw, "call_budget_exhausted", "call_budget_exhausted");
        continue;
    }
    // ИМЯ ШАГА, КОТОРЫЙ СЕЙЧАС ИДЁТ. Урок 2846 групп: тип исключения без
    // имени вызова — одно ведро на всё, и по нему нельзя сказать ни ЧТО
    // читали, ни ЧТО ответил Revit.
    string __dmStep = "ElementId.Parse";
    try
    {
        long __dmNum = 0L;
        if (!Int64.TryParse(__dmRaw, out __dmNum))
        {
            __dmFail(__dmRaw, "element id is not numeric", "element_unresolved");
            continue;
        }
        __dmStep = "Document.GetElement";
        ElementId __dmId = __sideElementId(__dmNum);
        if (__dmId == null)
        {
            __dmFail(__dmRaw, "__ELEMENT_ID_OUT_OF_RANGE__", "element_unresolved");
            continue;
        }
        Element __dmEl = __src.GetElement(__dmId);
        if (__dmEl == null)
        {
            __dmFail(__dmRaw, "element not found in document", "element_unresolved");
            continue;
        }
        __dmStep = "cast to Dimension";
        Autodesk.Revit.DB.Dimension __dmDim =
            __dmEl as Autodesk.Revit.DB.Dimension;
        if (__dmDim == null)
        {
            __dmFail(__dmRaw,
                     "not a dimension element: " + __dmClassName(__dmEl),
                     "element_kind_mismatch");
            continue;
        }
        // ВЫСОТНАЯ ОТМЕТКА — ПОДКЛАСС Dimension, но прямой ход строит размер
        // ровно одним способом (doc.Create.NewDimension); пересборка отметки
        // дала бы элемент другого класса, а не эту отметку.
        __dmStep = "cast to SpotDimension";
        Autodesk.Revit.DB.SpotDimension __dmSpot =
            __dmEl as Autodesk.Revit.DB.SpotDimension;
        if (__dmSpot != null)
        {
            __dmFail(__dmRaw,
                     "spot dimension (SpotDimension) is not built by "
                         + "NewDimension; create_dimension would rebuild "
                         + "another element class",
                     "element_kind_mismatch");
            continue;
        }

        __dmStep = "Element.OwnerViewId";
        ElementId __dmViewId = __dmEl.OwnerViewId;
        string __dmViewIdStr = __dmValidIdString(__dmViewId);
        if (__dmViewIdStr == null)
        {
            // ЗАКОН ПРИВЯЗКИ К ВИДУ: аннотация живёт в конкретном виде, и
            // точка вида существует ТОЛЬКО в его плоскости.
            __dmFail(__dmRaw, "dimension has no owner view", "aspect_not_present");
            continue;
        }
        __dmStep = "Document.GetElement(OwnerViewId) as View";
        Autodesk.Revit.DB.View __dmView =
            __src.GetElement(__dmViewId) as Autodesk.Revit.DB.View;
        if (__dmView == null)
        {
            __dmFail(__dmRaw, "owner view is not a View element",
                     "aspect_not_present");
            continue;
        }

        __dmStep = "View basis (Origin/RightDirection/UpDirection)";
        XYZ __dmOrigin = __dmView.Origin;
        XYZ __dmRight = __dmView.RightDirection;
        XYZ __dmUp = __dmView.UpDirection;
        if (__dmOrigin == null || __dmRight == null || __dmUp == null)
        {
            __dmFail(__dmRaw, "owner view has no usable basis",
                     "dimension_line_unreadable");
            continue;
        }

        // ТОЧКА НА ЛИНИИ РАЗМЕРА. Dimension.Origin — «средняя точка линии
        // размера»; для многосегментных её документация объявляет
        // неприменимой и на SpotDimension бросает (те отказаны выше).
        // Запасной ход — Dimension.Curve, у которой берётся ТОЛЬКО Origin:
        // кривая размера документирована ВСЕГДА неограниченной, и
        // GetEndPoint на ней бросает.
        __dmStep = "Dimension.Origin";
        XYZ __dmPoint = null;
        try { __dmPoint = __dmDim.Origin; } catch { __dmPoint = null; }
        if (__dmPoint == null)
        {
            __dmStep = "Dimension.Curve as Line -> Origin";
            try
            {
                Line __dmLine = __dmDim.Curve as Line;
                if (__dmLine != null) __dmPoint = __dmLine.Origin;
            }
            catch { __dmPoint = null; }
        }
        if (__dmPoint == null)
        {
            __dmFail(__dmRaw,
                     "neither Dimension.Origin nor Dimension.Curve gave a "
                         + "point on the dimension line",
                     "dimension_line_unreadable");
            continue;
        }

        __dmStep = "project point into view basis";
        XYZ __dmRel = __dmPoint - __dmOrigin;
        double __dmU = __dmRel.DotProduct(__dmRight);
        double __dmV = __dmRel.DotProduct(__dmUp);
        if (!__dmFinite(__dmU) || !__dmFinite(__dmV))
        {
            __dmFail(__dmRaw, "dimension line point is not finite in view space",
                     "dimension_line_unreadable");
            continue;
        }

        // МЕЖДУ ЧЕМ ПРОВЕДЁН РАЗМЕР. Dimension.References -> ReferenceArray
        // (тип назван компилятором; RevitAPI.dll, не System.dll — ловушки
        // ISet<>, убившей стадию марок, здесь нет).
        __dmStep = "Dimension.References";
        var __dmRefIds = new List<object>();
        bool __dmRefBad = false;
        string __dmRefWhy = "";
        ReferenceArray __dmRefs = __dmDim.References;
        if (__dmRefs == null)
        {
            __dmFail(__dmRaw, "dimension has no references at all",
                     "aspect_not_present");
            continue;
        }
        foreach (Reference __dmRef in __dmRefs)
        {
            if (__dmRef == null)
            {
                __dmRefBad = true;
                __dmRefWhy = "a reference of this dimension is null";
                break;
            }
            string __dmRefId = __dmValidIdString(__dmRef.ElementId);
            if (__dmRefId == null)
            {
                // Ссылка на элемент СВЯЗАННОГО файла или на то, чего в этом
                // документе не адресовать: refs опа собрать нечем. Привязать
                // размер к похожему элементу своего файла — худшее, что здесь
                // можно сделать: это прошло бы схему L1 и выглядело бы
                // покрытием (§18.1).
                __dmRefBad = true;
                __dmRefWhy = "a reference of this dimension names no element "
                    + "of this document (linked host or non-element reference)";
                break;
            }
            __dmRefIds.Add(__dmRefId);
        }
        if (__dmRefBad)
        {
            __dmFail(__dmRaw, __dmRefWhy, "dimension_ref_not_local");
            continue;
        }
        if (__dmRefIds.Count < __DM_MIN_REFS__)
        {
            __dmFail(__dmRaw,
                     "dimension binds " + __dmRefIds.Count.ToString()
                         + " element(s); create_dimension needs at least "
                         + "__DM_MIN_REFS__",
                     "aspect_not_present");
            continue;
        }

        __dmStep = "Dimension.NumberOfSegments";
        int __dmSegments = 0;
        try { __dmSegments = __dmDim.NumberOfSegments; } catch { __dmSegments = 0; }
        if (__dmSegments < 0) __dmSegments = 0;

        __dmStep = "Dimension.DimensionShape";
        string __dmShape = "";
        try { __dmShape = __dmDim.DimensionShape.ToString(); } catch { __dmShape = ""; }
        if (__dmShape == null || __dmShape.Length == 0) __dmShape = "Unknown";

        __dmStep = "Element.GetTypeId";
        string __dmTypeIdStr = null;
        string __dmTypeName = null;
        try
        {
            ElementId __dmTypeId = __dmEl.GetTypeId();
            __dmTypeIdStr = __dmValidIdString(__dmTypeId);
            if (__dmTypeIdStr != null)
            {
                Element __dmType = __src.GetElement(__dmTypeId);
                if (__dmType != null) __dmTypeName = __dmType.Name;
            }
        }
        catch { __dmTypeIdStr = null; __dmTypeName = null; }

        var __dmRow = new Dictionary<string, object>();
        __dmRow["element_id"] = __dmRaw;
        __dmRow["owner_view_id"] = __dmViewIdStr;
        __dmRow["owner_view_name"] = __dmView.Name;
        __dmRow["line_at_view_ft"] = new List<object> { __dmU, __dmV };
        __dmRow["ref_element_ids"] = __dmRefIds;
        __dmRow["segment_count"] = __dmSegments;
        __dmRow["dimension_shape"] = __dmShape;
        if (__dmTypeIdStr != null && __dmTypeName != null)
        {
            __dmRow["type_id"] = __dmTypeIdStr;
            __dmRow["type_name"] = __dmTypeName;
        }
        __dmRows.Add(__dmRow);
    }
    catch (Exception __dmEx)
    {
        __dmFail(__dmRaw, __dmStep + ": " + __dmClassName(__dmEx), "read_failed");
    }
}

var __dmPayload = new Dictionary<string, object>();
__dmPayload["schema_version"] = __DM_SCHEMA__;
__dmPayload["elements"] = __dmRows;
__dmPayload["failures"] = __dmFailures;
return __dmPayload;
"""


def build_dimension_extract_cs(element_ids: list[str], *,
                               call_budget_ms: int = 20_000,
                               link_title: str | None = None) -> str:
    """C# одной страницы стадии размеров.

    ВЕРСИИ ЗДЕСЬ НЕТ, и это ЗАМЕР, а не упущение. У стадии марок версия —
    обязательный вход, потому что у цели марки нет ни одного члена, живущего
    во всех шести версиях. У размера все нужные члены живут во всех шести
    (``References`` / ``Curve`` / ``Origin`` / ``NumberOfSegments`` /
    ``DimensionShape``, проверено индексом ловушек и названо компилятором),
    поэтому шва нет и разводить нечего. Появится член с версионным швом —
    появится и параметр, но не раньше.

    Пустой список id — это НЕ повод собрать тело, которое пройдёт по всему
    документу: стадия страничная, и «нет id» означает «нечего читать».

    ``link_title`` — читать не ХОЗЯИНА, а его связь с таким ``Document.Title``.
    """
    quoted = ", ".join(_csharp_string(str(item)) for item in element_ids)
    body = _DIMENSION_EXTRACT_BODY_CS
    body = body.replace("__DM_CALL_BUDGET_MS__", str(int(call_budget_ms)))
    body = body.replace("__DIMENSION_IDS__", quoted)
    body = body.replace("__DM_MIN_REFS__", str(int(DIMENSION_MIN_REFS)))
    body = body.replace(
        "__ELEMENT_ID_OUT_OF_RANGE__", ELEMENT_ID_OUT_OF_RANGE_REASON)
    body = body.replace(
        "__DM_SCHEMA__", _csharp_string(DIMENSION_EXTRACT_SCHEMA_VERSION))
    return (source_binding_cs(link_title) + "\n"
            + ELEMENT_ID_HELPER_CS + "\n"
            + DIMENSION_EXTRACT_HELPER_CS + body)


__all__ = [
    "DIMENSION_CATEGORIES",
    "DIMENSION_EXTRACT_SCHEMA_VERSION",
    "DIMENSION_INDEX_SCHEMA_VERSION",
    "DIMENSION_MIN_REFS",
    "DIMENSION_SHAPE_LINEAR",
    "DimensionExtraction",
    "DimensionFailure",
    "DimensionPayloadError",
    "DimensionRecord",
    "build_dimension_extract_cs",
    "extract_dimensions",
    "merge_dimensions",
    "parse_dimension_index",
]
