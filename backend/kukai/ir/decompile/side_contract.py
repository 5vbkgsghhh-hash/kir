"""§18.2 — общий контракт боковой стадии («закон квитанции»).

Каждый боковой экстрактор (curve / curtain / sketch / family_placement /
group) отвечает ОДИНАКОВО: ``rows + failures``, оба ключа обязательны. Любой
бюджет, таймаут, непарсируемая строка или неузнанная форма ответа обязаны
оставить запись ``{element_id, typed_reason}``. Одна плохая строка изолируется
в квитанцию с id элемента — прогон живёт.

Почему это отдельный модуль, а не пятая копия одного и того же
--------------------------------------------------------------
``curve_extract`` завёл эту дисциплину первым и держал её ЛОКАЛЬНО
(``CurveFailureReason`` с двумя значениями). ``curtain_extract`` скопировал её
дословно. ``sketch_extract`` взял только форму (``ProfileFailure`` без
типизированной причины), а ``family_placement_extract`` и ``group_extract`` не
взяли ничего: они выбрасывали элемент молча — ``break`` по бюджету,
``continue`` на неподходящем классе, пустой ``catch {}``.

ЗАМЕР 28.07 (SOB6.2_FAS_R23, ``backend/data/decompile/sob62_fas_r23_v2``),
ради которого модуль и написан:

    стадия            запрошено   строк   квитанций   БЕЗ СЛЕДА
    curve                  1178    1178           0           0
    curtain                1178    1178         983           0
    sketch                   55      55           5           0
    family_placement       1799    1557           0         242

Все 242 — ``OST_CurtainWallPanels``; в лифте они стали атомами
``placement_kind_unknown`` с текстом «element is absent from the family
placement side index». Снаружи это неотличимо от «компилятор не умеет
панели», хотя на деле их выбросил экстрактор. Разница между «мы не умеем» и
«мы не посмотрели» и есть предмет этого закона.

Инвариант, который проверяет стадия
-----------------------------------
Проверяется ПОКРЫТИЕ, а не арифметическая сумма: каждый запрошенный id обязан
быть либо в строках, либо в квитанциях. Для curve / family_placement / group
строки и квитанции не пересекаются, и покрытие тождественно равно
``|rows| + |failures| == |запрошено|``. Для sketch и curtain это не так по
построению: элемент получает СТРОКУ (пусть с ``profile_available=False``) и
вдобавок диагностические квитанции — по одной на каждый непрочитанный марш
лестницы. Сумма там больше числа запрошенных, и требовать равенства значило бы
запретить экстрактору говорить о причине больше одного раза. Потерянный id
покрытие ловит одинаково в обоих случаях, а это и есть то, ради чего сверка
существует.
"""
from __future__ import annotations

import json
from kukai.ir.emit_utils import cs_string_literal
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence


class SideStageContractError(ValueError):
    """Боковая стадия нарушила контракт §18.2 (потерян id, битая форма)."""


class SideFailureReason(str, Enum):
    """Закрытый словарь типизированных причин среза.

    Значения ``time_budget_exceeded`` / ``call_budget_exhausted`` совпадают с
    заведёнными ранее ``CurveFailureReason`` / ``CurtainFailureReason``
    ДОСЛОВНО: у одной и той же причины обязано быть одно имя во всех пяти
    индексах, иначе разбивка по причинам в паспорте складывает разные строки
    как разные явления.
    """

    TIME_BUDGET_EXCEEDED = "time_budget_exceeded"
    CALL_BUDGET_EXHAUSTED = "call_budget_exhausted"
    # Запрошенный id не нашёлся В ДОКУМЕНТЕ за один ограниченный проход
    # коллектора (модель могла измениться, id мог прийти из чужого разбора).
    # Замер, ради которого причина сужена до этой строки: у
    # `snowdon_elec_v1` 1 837 таких отказов сопровождались 20 строками из
    # ЧУЖОГО документа (`dependencies.py`) — то есть смысл «пришёл извне»
    # реален и обязан остаться различимым.
    ELEMENT_UNRESOLVED = "element_unresolved"
    # Стадия ЗАПРОСИЛА id, ни один её коллектор его не забрал, и элемент
    # ЛЕЖИТ В L0 этого же прогона. Это граница ОХВАТА стадии, а не отсутствие
    # в документе. Заведено 12.08.2026 после того, как общий улов
    # `sketch_extract` слал `element_unresolved` для 172 `OST_StairsRailing`,
    # найденных в L0 все 172 из 172 (контроль: 8 из 8 настоящих id найдены,
    # 0 из 5 выдуманных). Два читателя вывели по этому коду ПРОТИВОПОЛОЖНОЕ,
    # каждый верно относительно своего источника: контракт объявлял «нет в
    # документе», производитель писал «не читаю». Разошлись АВТОРИТЕТ и
    # ПРОИЗВОДИТЕЛЬ, а не два невнимательных человека.
    # Форма лечения — та же, что у HOST_KIND_UNRESOLVED ниже: причина
    # разделена, старый код ОСТАЁТСЯ объявленным ради артефактов, снятых до
    # разделения, и новые разборы его в этом месте не пишут.
    ELEMENT_NOT_CLAIMED = "element_not_claimed"
    # Элемент нашёлся, но он не того класса, который читает эта стадия
    # (панель-стена в витраже — не FamilyInstance). ЧЕСТНЫЙ факт о модели, а
    # не сбой: именно эти 242 строки и терялись молча.
    ELEMENT_KIND_MISMATCH = "element_kind_mismatch"
    # Чтение элемента бросило исключение внутри моста.
    READ_FAILED = "read_failed"
    # Строка ответа не разобралась строгим парсером — изолирована.
    ROW_UNPARSABLE = "row_unparsable"
    # mirrored == hand XOR facing не выполнился. НЕ смерть прогона: см.
    # family_placement_extract о зеркалировании произвольной плоскостью.
    MIRROR_INVARIANT_VIOLATED = "mirror_invariant_violated"
    # Ответ моста пришёл в форме, которой контракт не знает.
    PAYLOAD_SHAPE_UNRECOGNIZED = "payload_shape_unrecognized"
    # ── Ниже: причины, введённые волной «у отказа обязана быть причина». ──
    #
    # Стадия ПОСМОТРЕЛА элемент, и аспекта, который она индексирует, у него
    # нет вовсе: у стены нет CurtainGrid, у элемента нет профиля. Ни один
    # компилятор здесь ничего не сделает — делать нечего.
    ASPECT_NOT_PRESENT = "aspect_not_present"
    # Носитель не опознан, НО эмиттер слил в одну строку два разных случая
    # («элемент не нашёлся» и «нашёлся, но не того класса»). Причина
    # называет ровно то, что известно: какой именно — неизвестно. Новые
    # разборы её не пишут (эмиттер разделён), она остаётся ради артефактов,
    # снятых до разделения.
    HOST_KIND_UNRESOLVED = "host_kind_unresolved"
    # Аспект есть, но носителей адреса больше одного (две сетки на одном
    # витраже): любой одиночный адрес был бы догадкой. Ограничение НАШЕГО
    # адреса, а не факт о модели.
    ADDRESS_AMBIGUOUS = "address_ambiguous"
    # Контур прочитан, но его топология вне того, что умеет схема стороны
    # (несвязный/вложенный внешний контур).
    PROFILE_TOPOLOGY_UNSUPPORTED = "profile_topology_unsupported"
    # У носителя нет одного надёжного замкнутого контура.
    PROFILE_NOT_SINGLE_CLOSED = "profile_not_single_closed"
    # Зависимых эскизов не один, выбрать единственный нечем.
    DEPENDENT_SKETCH_AMBIGUOUS = "dependent_sketch_ambiguous"
    # ── Волна МАРОК (30.07). ──────────────────────────────────────────────
    #
    # Марка ССЫЛАЕТСЯ на другой элемент, и ссылку не всегда можно
    # восстановить: марка на элементе СВЯЗАННОГО файла даёт пустое
    # ``GetTaggedLocalElementIds()`` (2022+) / ``InvalidElementId`` в
    # ``TaggedLocalElementId`` (2021), осиротевшая марка — то же самое.
    #
    # Отдельная причина нужна потому, что ни одна прежняя не говорит правду:
    # ``ELEMENT_UNRESOLVED`` — про ЗАПРОШЕННЫЙ id (сама марка нашлась
    # прекрасно), ``ASPECT_NOT_PRESENT`` — про отсутствующий аспект (цель у
    # марки ЕСТЬ, она просто не в этом документе). Худшее, что здесь можно
    # сделать, — привязать марку к похожему элементу своего файла: это
    # прошло бы схему L1 и выглядело бы покрытием.
    #
    # Класс CUT, а не DETERMINATION: наш ``target`` адресует элемент ЭТОГО
    # документа, то есть ограничение наше, а не факт о модели. Словарь
    # намеренно самокритичен (см. SideFailureKind), и спорное кладётся в срез.
    TAG_TARGET_NOT_LOCAL = "tag_target_not_local"

    # ── Волна РАЗМЕРОВ. ──────────────────────────────────────────────────
    #
    # ЗАМЕР, ради которого причины заведены (k2_ar_rd_v8, переподъём текущим
    # лифтом): 13 905 размеров = 13 905 атомов source_contract_gap, то есть
    # ВСЕ до единого. Стадии не было вовсе, а операция create_dimension в
    # реестре есть с 28.07.
    #
    # Размер СВЯЗАН со ссылками (``Dimension.References`` ->
    # ``ReferenceArray``, тип замерен компилятором на 2021/2023/2026, лежит в
    # RevitAPI.dll — ловушки ``System.dll``, убившей стадию марок 04.08,
    # здесь нет). Ссылка может указывать на элемент СВЯЗАННОГО файла или на
    # то, чего в этом документе не адресовать: тогда ``refs`` опа собрать
    # нечем. Класс CUT, а не DETERMINATION, по тому же правилу, что и
    # ``TAG_TARGET_NOT_LOCAL``: наш ``refs`` адресует элементы ЭТОГО
    # документа, значит ограничение НАШЕ.
    DIMENSION_REF_NOT_LOCAL = "dimension_ref_not_local"
    # Точку НА ЛИНИИ размера прочитать не удалось: ``Dimension.Origin`` не
    # ответил и ``Dimension.Curve`` не дал начала. Без точки ``line_at`` опа
    # не собрать, а подставить любую — выдумать источник.
    #
    # ОТДЕЛЬНАЯ ПРИЧИНА, А НЕ ``ASPECT_NOT_PRESENT``: у размера линия ЕСТЬ по
    # определению (он ею и нарисован), значит это НАШЕ непрочтение, а не
    # факт о модели. Класс CUT.
    DIMENSION_LINE_UNREADABLE = "dimension_line_unreadable"


class SideFailureKind(str, Enum):
    """Класс квитанции: «не досмотрели» против «посмотрели, аспекта нет».

    Разделение введено потому, что без него ОДНО число называло два разных
    явления, и большее из них было не тем, за что его принимали.

    ЗАМЕР 29.07 (13A-RD-AR-K2_v33, 55 293 элемента,
    ``backend/data/decompile/k2_ar_rd_v6``), ради которого класс и заведён:
    ``side_failures_by_stage.curtain`` показывал 14 343 — крупнейшую массу
    отказов разбора. Из них 14 324 — обычные стены без CurtainGrid, и у
    КАЖДОЙ из них есть, кроме квитанции, ещё и строка индекса
    (``curtain_available: false``). То есть стадия отработала по ним начисто,
    а число читалось как «витражи не осилены на 14 тысячах элементов».

    ``CUT`` — мы не досмотрели: бюджет, исключение, неразобранная строка,
    неопознанная форма ответа, а также СОБСТВЕННЫЕ ограничения адреса и
    схемы. Всё, что относится к нам, лежит здесь; класс намеренно
    самокритичен, и в спорном случае причина кладётся сюда.

    ``DETERMINATION`` — мы посмотрели, и у элемента этого аспекта нет.
    Сюда попадают ровно две причины: аспекта нет вовсе и элемент другого
    класса, чем читает стадия. Обе — факты о модели, а не о компиляторе.
    """

    CUT = "cut"
    DETERMINATION = "determination"


#: Класс каждой причины. Словарь ПОЛНЫЙ по построению: тест
#: ``test_every_reason_is_classified`` падает на любом новом члене
#: ``SideFailureReason``, который сюда не добавили, — иначе первая же
#: неклассифицированная причина молча выпала бы из обеих сумм.
SIDE_FAILURE_KINDS: dict["SideFailureReason", SideFailureKind] = {
    SideFailureReason.TIME_BUDGET_EXCEEDED: SideFailureKind.CUT,
    SideFailureReason.CALL_BUDGET_EXHAUSTED: SideFailureKind.CUT,
    SideFailureReason.ELEMENT_UNRESOLVED: SideFailureKind.CUT,
    SideFailureReason.ELEMENT_NOT_CLAIMED: SideFailureKind.CUT,
    SideFailureReason.READ_FAILED: SideFailureKind.CUT,
    SideFailureReason.ROW_UNPARSABLE: SideFailureKind.CUT,
    SideFailureReason.MIRROR_INVARIANT_VIOLATED: SideFailureKind.CUT,
    SideFailureReason.PAYLOAD_SHAPE_UNRECOGNIZED: SideFailureKind.CUT,
    SideFailureReason.HOST_KIND_UNRESOLVED: SideFailureKind.CUT,
    SideFailureReason.ADDRESS_AMBIGUOUS: SideFailureKind.CUT,
    SideFailureReason.PROFILE_TOPOLOGY_UNSUPPORTED: SideFailureKind.CUT,
    SideFailureReason.PROFILE_NOT_SINGLE_CLOSED: SideFailureKind.CUT,
    SideFailureReason.DEPENDENT_SKETCH_AMBIGUOUS: SideFailureKind.CUT,
    SideFailureReason.TAG_TARGET_NOT_LOCAL: SideFailureKind.CUT,
    SideFailureReason.DIMENSION_REF_NOT_LOCAL: SideFailureKind.CUT,
    SideFailureReason.DIMENSION_LINE_UNREADABLE: SideFailureKind.CUT,
    # Обе причины ниже — факты о модели. ``ELEMENT_KIND_MISMATCH`` переехал
    # сюда из срезов: его собственный докстринг с самого начала называл его
    # «ЧЕСТНЫЙ факт о модели, а не сбой», но считался он вместе со срезами.
    SideFailureReason.ASPECT_NOT_PRESENT: SideFailureKind.DETERMINATION,
    SideFailureReason.ELEMENT_KIND_MISMATCH: SideFailureKind.DETERMINATION,
}


def _string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise SideStageContractError(f"{field_name} must be a non-empty string")
    return value


def _nonnegative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SideStageContractError(
            f"{field_name} must be a non-negative integer")
    return value


def element_id_key(value: str) -> tuple[int, int | str, str]:
    """Числовой id сортируется как число, любой другой — лексикографически."""
    try:
        return 0, int(value), value
    except ValueError:
        return 1, value, value


@dataclass(frozen=True, slots=True)
class SideFailure:
    """Одна квитанция: элемент, о котором стадия не смогла сказать строкой.

    Форма умышленно совпадает с ``CurveFailure``/``CurtainFailure`` —
    ``{element_id, reason}`` плюс необязательная пара
    ``{typed_reason, elapsed_ms}``. ``elapsed_ms`` необязателен и при
    типизированной причине: у среза по классу элемента нет осмысленного
    времени, а требовать его значило бы заставлять эмиттер выдумывать число.
    """

    element_id: str
    reason: str
    typed_reason: SideFailureReason | None = None
    elapsed_ms: int | None = None

    def __post_init__(self) -> None:
        _string(self.element_id, "SideFailure.element_id")
        _string(self.reason, "SideFailure.reason")
        if self.typed_reason is None:
            if self.elapsed_ms is not None:
                raise SideStageContractError(
                    "SideFailure.elapsed_ms requires a typed reason")
        else:
            if not isinstance(self.typed_reason, SideFailureReason):
                raise SideStageContractError(
                    "SideFailure.typed_reason must be a SideFailureReason")
            if self.elapsed_ms is not None:
                _nonnegative_int(self.elapsed_ms, "SideFailure.elapsed_ms")

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "element_id": self.element_id,
            "reason": self.reason,
        }
        if self.typed_reason is not None:
            result["typed_reason"] = self.typed_reason.value
            result["elapsed_ms"] = self.elapsed_ms
        return result

    @classmethod
    def from_dict(cls, value: Any, field_name: str) -> "SideFailure":
        if not isinstance(value, Mapping):
            raise SideStageContractError(f"{field_name} must be an object")
        row = dict(value)
        allowed = {"element_id", "reason", "typed_reason", "elapsed_ms"}
        extra = sorted(set(row) - allowed)
        if extra:
            raise SideStageContractError(
                f"{field_name} unexpected fields: {', '.join(extra)}")
        typed: SideFailureReason | None = None
        raw_typed = row.get("typed_reason")
        if raw_typed is not None:
            try:
                typed = SideFailureReason(raw_typed)
            except (TypeError, ValueError) as exc:
                raise SideStageContractError(
                    f"{field_name}.typed_reason is unsupported") from exc
        elapsed = row.get("elapsed_ms")
        if elapsed is not None:
            _nonnegative_int(elapsed, f"{field_name}.elapsed_ms")
        return cls(
            element_id=_string(
                row.get("element_id"), f"{field_name}.element_id"),
            reason=_string(row.get("reason"), f"{field_name}.reason"),
            typed_reason=typed,
            elapsed_ms=elapsed,
        )


def sorted_failures(
    failures: Iterable[SideFailure],
) -> tuple[SideFailure, ...]:
    """Детерминированный порядок квитанций (I4: артефакт побайтово стабилен)."""
    return tuple(sorted(
        failures,
        key=lambda item: (element_id_key(item.element_id), item.reason)))


def _named_id(item: Any) -> str | None:
    for attribute in ("element_id", "wall_id"):
        value = getattr(item, attribute, None)
        if isinstance(value, str) and value:
            return value
    if isinstance(item, Mapping):
        for key in ("element_id", "wall_id"):
            value = item.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def failure_element_id(failure: Any) -> str | None:
    """id элемента из квитанции ЛЮБОГО из пяти индексов.

    ``CurtainFailure`` называет своё поле ``wall_id`` (индекс витражей знает
    только стены). Переименовывать его значило бы менять форму уже записанных
    артефактов ради единообразия читателя — читатель дешевле.
    """
    return _named_id(failure)


def record_element_id(record: Any) -> str | None:
    """id элемента из СТРОКИ индекса — тот же разнобой имён, что и в квитанциях.

    ``CurtainWallRecord.wall_id`` — не описка и не наследие: индекс витражей
    описывает стены и ничего кроме, и поле названо тем, что в нём лежит.
    Сверка стадии обязана уметь читать оба имени, иначе она объявит потерянным
    каждый успешно прочитанный витраж.
    """
    return _named_id(record)


def failure_typed_reason(failure: Any) -> str | None:
    """Типизированная причина квитанции, если она есть.

    ``.value`` берётся ВСЕГДА, а не только у не-строк: все три Enum-а причин —
    ``str``-энумы, и ``isinstance(value, str)`` для них истинно. Проверка «если
    не строка» пропускала их мимо и печатала в паспорте
    ``SideFailureReason.TIME_BUDGET_EXCEEDED`` вместо ``time_budget_exceeded``.
    """
    value = getattr(failure, "typed_reason", None)
    if value is None and isinstance(failure, Mapping):
        value = failure.get("typed_reason")
    if value is None:
        return None
    resolved = getattr(value, "value", value)
    return resolved if isinstance(resolved, str) else str(resolved)


#: Причины, которые НАШИ ЖЕ эмиттеры писали строкой до того, как у квитанции
#: появился тип. Ключ — начало строки: часть сообщений несёт в хвосте число
#: («dependent Sketch count is 2»), и сверять их целиком значило бы разобрать
#: одно здание и промахнуться на следующем.
#:
#: ЭТО НЕ СПИСОК ЗНАКОМЫХ ИМЁН ИЗ МОДЕЛИ. Здесь только строки нашего
#: собственного протокола — ни имени типа, ни имени семейства, ни id отсюда
#: взяться не может, и на чужом здании таблица работает ровно так же.
#: Нужна она затем, что разборы уже лежат на диске: пере-снять их без Revit
#: нельзя, а читать их новой таксономией надо.
_LEGACY_REASON_PREFIXES: tuple[tuple[str, str, "SideFailureReason"], ...] = (
    ("curtain", "not_curtain", SideFailureReason.ASPECT_NOT_PRESENT),
    ("curtain", "host has no CurtainGrid",
     SideFailureReason.ASPECT_NOT_PRESENT),
    ("curtain", "requested element is not a curtain host",
     SideFailureReason.HOST_KIND_UNRESOLVED),
    ("curtain", "multiple_curtain_grids",
     SideFailureReason.ADDRESS_AMBIGUOUS),
    ("sketch", "exact profile topology unavailable",
     SideFailureReason.PROFILE_TOPOLOGY_UNSUPPORTED),
    ("sketch", "stairs parent has no single reliable closed Sketch profile",
     SideFailureReason.PROFILE_NOT_SINGLE_CLOSED),
    ("sketch", "dependent Sketch count is",
     SideFailureReason.DEPENDENT_SKETCH_AMBIGUOUS),
    # Ограждение — ПУТЕВОЙ элемент: замкнутого контура у него нет не потому,
    # что мы не досмотрели, а потому, что его не бывает. Это дословно тот
    # случай, который ASPECT_NOT_PRESENT описывает своим же примером («у
    # элемента нет профиля»), поэтому DETERMINATION, а не CUT: иначе 203
    # ограждения одной только К2 приехали бы в паспорт как наш недочёт.
    # Таблица адресуется ПРЕФИКСОМ, а не индексом (см. legacy_typed_reason),
    # поэтому строка стоит рядом со своей стадией, а не в хвосте кортежа.
    ("sketch", "railing is a path element",
     SideFailureReason.ASPECT_NOT_PRESENT),
    ("family_placement", "not a FamilyInstance",
     SideFailureReason.ELEMENT_KIND_MISMATCH),
    ("group", "group read failed", SideFailureReason.READ_FAILED),
)


def legacy_typed_reason(stage: str, reason: Any) -> "SideFailureReason | None":
    """Тип для квитанции, записанной ДО того, как тип стал обязательным."""
    if not isinstance(reason, str) or not reason:
        return None
    for known_stage, prefix, typed in _LEGACY_REASON_PREFIXES:
        if known_stage == stage and reason.startswith(prefix):
            return typed
    return None


def resolved_typed_reason(failure: Any, stage: str) -> str | None:
    """Тип квитанции: свой, если он есть, иначе выведенный из старой строки.

    Порядок неслучаен: записанный тип всегда сильнее выведенного, иначе
    сегодняшняя таблица совместимости переписывала бы завтрашние квитанции.
    """
    typed = failure_typed_reason(failure)
    if typed is not None:
        return typed
    reason = getattr(failure, "reason", None)
    if reason is None and isinstance(failure, Mapping):
        reason = failure.get("reason")
    inferred = legacy_typed_reason(stage, reason)
    return inferred.value if inferred is not None else None


def failure_kind(typed_reason: Any) -> SideFailureKind | None:
    """Класс причины (срез / определение) по её значению."""
    if typed_reason is None:
        return None
    try:
        reason = SideFailureReason(getattr(
            typed_reason, "value", typed_reason))
    except (TypeError, ValueError):
        return None
    return SIDE_FAILURE_KINDS.get(reason)


def reconcile_side_stage(
    stage: str,
    *,
    requested: Sequence[str],
    accounted: Iterable[str],
) -> None:
    """Сверить запрошенное с полученным; расхождение — типизированный отказ.

    ``accounted`` — объединение id строк и id квитанций. Проверяется покрытие
    (см. докстринг модуля, почему именно оно, а не сумма длин).
    """
    wanted = set(requested)
    if not wanted:
        return
    seen = set(accounted)
    missing = sorted(wanted - seen, key=element_id_key)
    if missing:
        raise SideStageContractError(
            f"{stage}: запрошено {len(wanted)}, без строки и без квитанции "
            f"{len(missing)} (первые: {', '.join(missing[:8])})")
    unexpected = sorted(seen - wanted, key=element_id_key)
    if unexpected:
        raise SideStageContractError(
            f"{stage}: ответ несёт {len(unexpected)} незапрошенных id "
            f"(первые: {', '.join(unexpected[:8])})")


def summarize_side_failures(
    extractions: Mapping[str, Any],
) -> dict[str, Any]:
    """Агрегат квитанций всех боковых индексов для run.json / статуса / паспорта.

    Квитанции раскладываются на ДВА класса (см. :class:`SideFailureKind`), и
    оба печатаются рядом. ``side_cuts_*`` — только срезы, то есть то, чего мы
    не досмотрели. ``side_determinations_*`` — то, что мы посмотрели и чего у
    элемента нет.

    Раньше здесь стояло «нетипизированные отказы — честные наблюдения, и
    подписывать их типом было бы враньём». Наблюдение верное, вывод — нет:
    из него следовало не отсутствие типа, а отсутствие ВТОРОГО КЛАССА. Пока
    класса не было, ``not_curtain`` оставался без причины, не попадал ни в
    одну разбивку и всплывал единственным числом ``side_failures_by_stage``,
    где читался как масса отказов: 14 343 на 13A-RD-AR-K2_v33 при 19
    настоящих. ``side_failures_untyped`` теперь обязан быть нулём, и это
    проверяется тестом, а не соглашением.
    """
    by_stage: dict[str, int] = {}
    cuts: dict[str, int] = {}
    determinations: dict[str, int] = {}
    unclassified: dict[str, int] = {}
    cuts_by_stage: dict[str, int] = {}
    determinations_by_stage: dict[str, int] = {}
    untyped = 0
    for stage in sorted(extractions):
        extraction = extractions[stage]
        if extraction is None:
            continue
        failures = tuple(getattr(extraction, "failures", ()) or ())
        if not failures:
            continue
        by_stage[stage] = len(failures)
        for failure in failures:
            reason = resolved_typed_reason(failure, stage)
            if reason is None:
                untyped += 1
                continue
            kind = failure_kind(reason)
            bucket = (cuts if kind is SideFailureKind.CUT
                      else determinations if kind is SideFailureKind.DETERMINATION
                      else unclassified)
            bucket[reason] = bucket.get(reason, 0) + 1
            if kind is SideFailureKind.CUT:
                cuts_by_stage[stage] = cuts_by_stage.get(stage, 0) + 1
            elif kind is SideFailureKind.DETERMINATION:
                determinations_by_stage[stage] = (
                    determinations_by_stage.get(stage, 0) + 1)
    summary = {
        "side_failures_total": sum(by_stage.values()),
        "side_failures_by_stage": by_stage,
        "side_failures_untyped": untyped,
        "side_cuts_total": sum(cuts.values()),
        "side_cuts_by_reason": dict(sorted(cuts.items())),
        # Разбивка по стадиям нужна ИМЕННО в этом виде: единственное число
        # ``side_failures_by_stage[curtain]`` = 14 343 и было тем, по чему
        # стадию назначали самой провальной. Рядом с ним обязано стоять, что
        # срезов там 19, а остальное — ответы.
        "side_cuts_by_stage": dict(sorted(cuts_by_stage.items())),
        "side_determinations_total": sum(determinations.values()),
        "side_determinations_by_reason": dict(sorted(determinations.items())),
        "side_determinations_by_stage": dict(sorted(
            determinations_by_stage.items())),
    }
    if unclassified:
        # Причина есть, класса у неё нет: молчать об этом нельзя — это ровно
        # та дыра, ради закрытия которой словарь заводился.
        summary["side_failures_unclassified"] = dict(sorted(
            unclassified.items()))
    return summary


def receipts_summary_ru(summary: Mapping[str, Any]) -> str:
    """Строка паспорта: «квитанции срезов: N (по причинам: …)» либо «срезов нет».

    Печатается ПОСЛЕ переписи и ПЕРЕД процентами по той же причине, по которой
    там же стоит перепись: читатель обязан узнать, чего мы не досмотрели,
    раньше, чем увидит долю поднятого.
    """
    def _detail(reasons: Mapping[str, Any]) -> str:
        return ", ".join(
            f"{reason} {count}"
            for reason, count in sorted(
                reasons.items(), key=lambda item: (-item[1], item[0])))

    total = int(summary.get("side_cuts_total") or 0)
    if total:
        head = f"{total} (по причинам: " \
               f"{_detail(summary.get('side_cuts_by_reason') or {})})"
    else:
        head = "срезов нет"
    # Определения печатаются той же строкой и ОТДЕЛЬНЫМ числом: без них
    # читатель видит «срезов нет» там, где стадия выдала 14 тысяч квитанций,
    # и справедливо перестаёт верить строке.
    determined = int(summary.get("side_determinations_total") or 0)
    if determined:
        head += (f"; определений: {determined} (по причинам: "
                 f"{_detail(summary.get('side_determinations_by_reason') or {})})")
    return head


def parse_wire_failures(
    value: Any,
    field_name: str,
) -> tuple[SideFailure, ...]:
    """Разобрать список квитанций из ответа моста (строгий, fail-closed)."""
    if value is None:
        return ()
    if not isinstance(value, list):
        raise SideStageContractError(f"{field_name} must be an array")
    return sorted_failures(
        SideFailure.from_dict(raw, f"{field_name}[{index}]")
        for index, raw in enumerate(value)
    )


def failures_to_json(failures: Iterable[SideFailure]) -> str:
    return json.dumps(
        [failure.to_dict() for failure in sorted_failures(failures)],
        ensure_ascii=False, allow_nan=False, sort_keys=True,
        separators=(",", ":"))


# ── чей документ читает стадия ───────────────────────────────────────────────
#: Единственное ЗАКОННОЕ обращение эмитированного тела к документу-хозяину:
#: поиск самой связи. Всё остальное в теле обязано идти через ``__src``.
SOURCE_HOST_LOOKUP_CS = (
    "foreach (RevitLinkInstance __srcLi in new FilteredElementCollector(doc)")


def csharp_string(value: str) -> str:
    """C#-литерал строки: имя документа приезжает извне и едет ЛИТЕРАЛОМ."""
    return cs_string_literal(value)


# ── как построить ElementId из числа ─────────────────────────────────────────
#: ЕДИНСТВЕННЫЙ способ собрать ``ElementId`` из числа в эмитированном теле.
#: Один текст на ВСЕ тела ровно по той же причине, что и привязка источника:
#: две копии этого решения означали бы две правды о том, что законно на шести
#: версиях, и разошлись бы молча.
#:
#: ЖИВОЙ ЗАМЕР 30.07, ради которого фрагмент существует. Разбор 59-этажной
#: башни на **Revit 2023** встал намертво и повторял по кругу, каждые 5-20
#: секунд, ``bridge_roundtrips=0``:
#:
#:     CS1503: Argument 1: cannot convert from 'long' to
#:     'Autodesk.Revit.DB.BuiltInParameter'   (line 103)
#:
#: Слова ``BuiltInParameter`` нет НИ В ОДНОМ нашем исходнике — и это не
#: странность сообщения, а его устройство. ``ElementId(Int64)`` появился
#: ТОЛЬКО в 2024 (сверено по RevitAPI.xml всех шести версий); на 2021-2023
#: набор перегрузок — ``{BuiltInCategory, BuiltInParameter, Int32}``, и
#: ``long`` не подходит ни к одной. Имя типа в CS1503 приезжает из
#: ПОСТАВЛЯЕМОЙ СБОРКИ, а не из нашего текста, поэтому искать виновника
#: грепом по сообщению бесполезно: искать надо ``new ElementId(``.
#:
#: ``int`` проходит на всех шести: 2021-2023 берут свой конструктор, 2024+
#: расширяют ``int``→``long`` неявно. Поэтому число едет ``int``-ом, а выход
#: за ``Int32`` НЕ обрезается: обрезанный id адресовал бы ЧУЖОЙ элемент
#: молча — исход хуже любого названного отказа. На 2021-2023 таких id не
#: бывает по построению (там ``ElementId`` 32-битный), на 2024+ это документ
#: с двумя миллиардами элементов.
ELEMENT_ID_HELPER_CS = (
    "Func<long, ElementId> __sideElementId = (__value) =>\n"
    "    (__value < Int32.MinValue || __value > Int32.MaxValue)\n"
    "        ? null : new ElementId((int)__value);"
)

#: Причина квитанции для id, который эмитированное тело адресовать не может.
#: Текст один на все стадии: одно явление — одна строка, иначе разбивка
#: паспорта сложит его как три разных.
ELEMENT_ID_OUT_OF_RANGE_REASON = (
    "element id is outside the 32-bit id space this body can address"
)


def source_binding_cs(
    link_title: str | None,
    link_instance_unique_id: str | None = None,
) -> str:
    """Привязка источника: хозяин или его СВЯЗЬ с таким ``Document.Title``.

    Один текст на ВСЕ тела — и основное извлечение, и каждую боковую стадию.
    Две копии этого C# означали бы две правды о том, какой документ читается,
    а проверяется закон «одно тело — один документ» по ТЕКСТУ эмиссии: копии
    разошлись бы молча и оставили проверку зелёной.

    Тело обязано начинаться с этой привязки. Причина не стилистическая:
    хелперы боковых стадий — лямбды, захватывающие ``__src``, а локальная
    переменная C# не видна выше своего объявления. Привязка после хелперов не
    «прочитала бы не то», а не собралась бы у Roslyn — то есть узналась бы
    только живьём.

    ЗАМЕР 30.07 (``backend/data/decompile/snowdon_elec_v1``), ради которого
    привязка сюда и переехала: связанная электрика, снятая из окна
    сантехники, дала 1837 квитанций одной стадии размещения семейств — её
    коллектор искал id связи в ХОЗЯИНЕ. И 20 раз хозяин ОТВЕТИЛ: у документов
    разные пространства идентификаторов, а числа в них совпадают, и стадия
    записала чужие строки как свои.

    ОГОВОРКА, КОТОРУЮ НЕЛЬЗЯ ПРЯТАТЬ: ревизионный страж отпечатывает документ
    ХОЗЯИНА, поэтому на чтении связи concurrent-правку он не поймает (см.
    ``extract._source_binding_cs``).

    Exact ``RevitLinkInstance.UniqueId`` is the authoritative selector.
    ``Document.Title`` remains only a legacy selector and requires exactly one
    loaded match; two placements with the same title refuse instead of
    choosing an arbitrary occurrence.  Either route retains the exact
    ``RevitLinkInstance`` for identity and transform evidence.
    """
    if link_title is not None and link_instance_unique_id is not None:
        raise ValueError(
            "link_title and link_instance_unique_id are mutually exclusive")
    if link_instance_unique_id is not None and (
            not isinstance(link_instance_unique_id, str)
            or not link_instance_unique_id.strip()):
        raise ValueError("link_instance_unique_id must be a non-blank string")
    if not link_title:
        if link_instance_unique_id is not None:
            uid = csharp_string(link_instance_unique_id)
            return (
                "Document __federationRoot = doc;\n"
                "Document __src = null;\n"
                "RevitLinkInstance __sourceLinkInstance = null;\n"
                "int __sourceLinkMatches = 0;\n"
                + SOURCE_HOST_LOOKUP_CS + "\n"
                "         .OfClass(typeof(RevitLinkInstance)).WhereElementIsNotElementType()\n"
                "         .Cast<RevitLinkInstance>()\n"
                "         .OrderBy(__x => __x.Id.ToString()))\n"
                "{\n"
                "    string __candidateUniqueId = null;\n"
                "    try { __candidateUniqueId = __srcLi.UniqueId; } catch { }\n"
                "    if (__candidateUniqueId == " + uid + ")\n"
                "    {\n"
                "        __sourceLinkMatches++;\n"
                "        Document __srcLd = __srcLi.GetLinkDocument();\n"
                "        if (__srcLd != null)\n"
                "        {\n"
                "            __src = __srcLd;\n"
                "            __sourceLinkInstance = __srcLi;\n"
                "        }\n"
                "    }\n"
                "}\n"
                "if (__sourceLinkMatches > 1) throw new InvalidOperationException(\n"
                "    \"duplicate RevitLinkInstance.UniqueId: \" + " + uid + ");\n"
                "if (__sourceLinkMatches == 0) throw new InvalidOperationException(\n"
                "    \"link instance UniqueId not found: \" + " + uid + ");\n"
                "if (__src == null) throw new InvalidOperationException(\n"
                "    \"link instance is not loaded: \" + " + uid + ");"
            )
        return (
            "Document __federationRoot = doc;\n"
            "Document __src = doc;\n"
            "RevitLinkInstance __sourceLinkInstance = null;")
    return (
        "Document __federationRoot = doc;\n"
        "Document __src = null;\n"
        "RevitLinkInstance __sourceLinkInstance = null;\n"
        "int __sourceLinkMatches = 0;\n"
        + SOURCE_HOST_LOOKUP_CS + "\n"
        "         .OfClass(typeof(RevitLinkInstance)).WhereElementIsNotElementType()\n"
        "         .Cast<RevitLinkInstance>()\n"
        "         .OrderBy(__x => __x.Id.ToString()))\n"
        "{\n"
        "    Document __srcLd = __srcLi.GetLinkDocument();\n"
        "    if (__srcLd != null && __srcLd.Title == " + csharp_string(link_title) + ")\n"
        "    {\n"
        "        __sourceLinkMatches++;\n"
        "        if (__sourceLinkMatches == 1)\n"
        "        {\n"
        "            __src = __srcLd;\n"
        "            __sourceLinkInstance = __srcLi;\n"
        "        }\n"
        "    }\n"
        "}\n"
        "if (__sourceLinkMatches > 1) throw new InvalidOperationException(\n"
        "    \"linked document title is ambiguous; select a link instance: \" + "
        + csharp_string(link_title) + ");\n"
        "if (__src == null) throw new InvalidOperationException(\n"
        "    \"linked document not found or not loaded: \" + "
        + csharp_string(link_title) + ");"
    )


__all__ = [
    "ELEMENT_ID_HELPER_CS",
    "ELEMENT_ID_OUT_OF_RANGE_REASON",
    "SIDE_FAILURE_KINDS",
    "SOURCE_HOST_LOOKUP_CS",
    "SideFailure",
    "SideFailureKind",
    "SideFailureReason",
    "SideStageContractError",
    "csharp_string",
    "element_id_key",
    "failure_element_id",
    "failure_kind",
    "failure_typed_reason",
    "legacy_typed_reason",
    "resolved_typed_reason",
    "record_element_id",
    "failures_to_json",
    "parse_wire_failures",
    "receipts_summary_ru",
    "reconcile_side_stage",
    "sorted_failures",
    "source_binding_cs",
    "summarize_side_failures",
]
