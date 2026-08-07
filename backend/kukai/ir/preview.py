"""ГЛАЗА КОМПИЛЯТОРА: план этажа из ПРОГРАММЫ и из РАЗБОРА, одним рисовальщиком.

Зачем это существует
--------------------
Диагноз стоит дословно в шапке :mod:`kukai.ir.acceptance`: проверяет тот же,
кто строил.  Свидетель подтверждает, что стена создана и её концы там, где
просили, — и молчит о том, что здание получилось мусором.  29.07 две модели
сдали башни, оба свидетеля написали «форма и пропорции соответствуют задаче»,
вердикт оператора про обе — «мусорная геометрия».  Единственный способ
посмотреть был живой Revit: медленный, рвущийся и сегодня недоступный.

Этот модуль даёт ГЛАЗА без Revit.  Он не судит.  Он рисует то, что есть, и
предъявляет перепись того, чего на картинке НЕТ.

Шесть законов, по которым он написан
------------------------------------
1. **ДВА ИСТОЧНИКА, ОДИН РИСОВАЛЬЩИК.**  ``build_program_preview`` (что я
   СОБИРАЮСЬ построить, до всякой транзакции) и ``build_model_preview`` (что в
   модели ЕСТЬ) сводятся к одному промежуточному языку форм
   (:class:`Poly`/:class:`Path`/:class:`Dot`/:class:`TextMark`), и рисует их
   ровно одна функция — :func:`render_svg`.  Геометрия одна, значит и код
   один.
2. **SVG, а не растр.**  Детерминированный текст: диффится, кладётся в
   квитанцию, частично читается моделью без зрения (перепись лежит машинным
   JSON в ``<metadata>``, у каждой фигуры есть ``data-el``/``data-cat``).
3. **ПЛАН ЭТАЖА ПЕРВЫМ.**  По уровням.  Разрезов и трёхмерки в этой волне нет.
4. **ПРЕВЬЮ НЕ ИМЕЕТ ПРАВА МОЛЧА ТЕРЯТЬ.**  Это не пожелание, а инвариант
   класса: :class:`PreviewCensus` НЕВОЗМОЖНО построить, если
   ``considered != drawn + сумма причин``.  Тот же приём, которым
   :class:`~kukai.ir.emit_model.WitnessCheck` убил по построению класс
   дефектов «маркер читателя остался, вердикт удалён».  Превью, тихо
   опускающее 30% здания, хуже отсутствия превью: оно врёт увереннее.
   Мало того: НАРИСОВАНО ≠ НАРИСОВАНО ТОЧНО, поэтому у переписи есть третья
   колонка — :class:`ApproxGroup` (габарит вместо профиля, ось вместо тела,
   дуга выборкой), и четвёртая — :class:`AnomalyGroup` (нарисовано, и
   геометрия подозрительная).
5. **ДЕТЕРМИНИЗМ.**  Тот же вход — тот же байт.  Ни времени, ни случайных id,
   ни обхода неупорядоченных множеств без сортировки; все числа печатаются
   одним ``_fmt``.
6. **ЧЕСТНОСТЬ ПРО СИЛУ УТВЕРЖДЕНИЯ.**  Превью из программы — самопроверка:
   рисуется то, что автор ЗАЯВИЛ.  Превью из разбора — независимое чтение.
   Разница обязана быть ВИДНА В САМОМ АРТЕФАКТЕ, а не подразумеваться:
   у ``PROGRAM`` другой цвет шапки, штриховая рамка листа, диагональный
   водяной знак «ЗАЯВЛЕНО» и явная строка «модель не читалась».  Не давать им
   выглядеть одинаково — отдельное требование, а не украшение.

Чего этот экран НЕ покажет — написано в :data:`BLIND_SPOTS` и печатается на
самом листе.  Список слепоты важнее списка возможностей: план в мм по XY не
знает ни высот, ни вертикальных привязок, ни материалов, ни того, замкнулась
ли оболочка.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from enum import Enum
from pathlib import Path as _FsPath
from typing import Any, Iterable, Mapping, Sequence

__all__ = (
    "PREVIEW_SCHEMA",
    "PreviewError",
    "PreviewCensusError",
    "PreviewSource",
    "Assertion",
    "OmitReason",
    "ApproxReason",
    "AnomalyReason",
    "Layer",
    "Poly",
    "Path",
    "Dot",
    "TextMark",
    "DrawnElement",
    "OmissionGroup",
    "ApproxGroup",
    "AnomalyGroup",
    "PreviewCensus",
    "FloorPlan",
    "BuildingPreview",
    "build_program_preview",
    "build_model_preview",
    "census_lines",
    "preview_snapshot",
    "render_svg",
    "BLIND_SPOTS",
)

PREVIEW_SCHEMA = "kir-preview/1"

#: Сколько идентификаторов-примеров хранит одна строка переписи.  Перепись
#: обязана НАЗВАТЬ причину и предъявить, на ком её проверить, но не обязана
#: держать в памяти сто тысяч id — на 88-мегабайтном L0 это разница между
#: инструментом и OOM.
MAX_EXAMPLES = 5


class PreviewError(ValueError):
    """Превью не может быть построено или отрисовано."""


class PreviewCensusError(PreviewError):
    """Нарушен ЗАКОН №4: элемент исчез, не будучи посчитанным и названным."""


# ---------------------------------------------------------------------------
# 1. Словарь честности
# ---------------------------------------------------------------------------

class Assertion(str, Enum):
    """Сила утверждения артефакта.  Разная — и обязана выглядеть по-разному."""

    #: Рисуется то, что автор ЗАЯВИЛ в программе.  Модель не читалась.
    SELF_REPORTED = "self_reported"
    #: Рисуется то, что независимо прочитано из документа.
    INDEPENDENT = "independent"


class PreviewSource(str, Enum):
    """Момент жизни, из которого снят план."""

    PROGRAM = "program"
    MODEL = "model"

    @property
    def assertion(self) -> Assertion:
        return (Assertion.SELF_REPORTED if self is PreviewSource.PROGRAM
                else Assertion.INDEPENDENT)


class OmitReason(str, Enum):
    """ЗАКРЫТЫЕ причины, по которым элемент не нарисован.

    Причины адресные, а не косметические, ровно по той же логике, по которой
    :class:`~kukai.ir.decompile.l1_schema.AtomReason` развёл ``no_lifter`` и
    ``source_contract_gap``: одна причина посылает чинить рисовальщик, другая —
    чтение, третья не является дефектом вовсе.
    """

    #: Геометрии нет ни в каком виде: ни кривой, ни точки, ни габарита.
    NO_GEOMETRY = "no_geometry"
    #: Есть только AABB, а нужен контур.  Габарит — НЕ контур: нарисовать
    #: прямоугольник вместо профиля перекрытия значит соврать увереннее, чем
    #: не нарисовать ничего.
    ONLY_BBOX = "only_bbox"
    #: Вырожденная геометрия: нулевая длина, нулевая площадь, схлопнутый габарит.
    DEGENERATE = "degenerate"
    #: NaN/inf в координатах.
    NON_FINITE = "non_finite"
    #: Кривая не прямая и не дуга (сплайн, спираль) — спрямлять хордой нельзя.
    UNSUPPORTED_CURVE = "unsupported_curve"
    #: Категория есть в чтении, правила рисования под неё нет.
    CATEGORY_NOT_DRAWN = "category_not_drawn"
    #: Двумерная аннотация вида, а не тело здания.  Отдельно от предыдущей
    #: намеренно: «я не умею рисовать трубу» и «марка двери принадлежит виду,
    #: а не модели» — разные факты, и лечатся они в разных местах.
    ANNOTATION_NOT_MODEL = "annotation_not_model"
    #: Элемент в плане не виден по построению (уровень — датум разреза).
    NOT_VISIBLE_IN_PLAN = "not_visible_in_plan"
    #: Производная геометрия: схема разрезки витража порождается витражом.
    DERIVED_GEOMETRY = "derived_geometry"
    #: Элемент не удалось отнести ни к одному этажу.
    LEVEL_UNKNOWN = "level_unknown"
    #: Элемент отнесён к этажу, который в этом прогоне не рисовали.  НЕ дефект,
    #: но и НЕ молчание: без этой строки знаменатель у прогона по трём этажам
    #: 59-этажной башни выглядел бы как полное покрытие.
    LEVEL_NOT_IN_RUN = "level_not_in_run"
    #: Проём: хост не назван.
    HOST_UNKNOWN = "host_unknown"
    #: Проём: хост назван, но его геометрии нет — на стене рисовать нечего.
    HOST_NOT_DRAWABLE = "host_not_drawable"
    #: Программа: у операции нет правила рисования.
    OP_NOT_DRAWN = "op_not_drawn"
    #: Программа: селектор уровня не сводится к плану (by=default и т.п.).
    SELECTOR_UNRESOLVED = "selector_unresolved"
    #: Программа: это вообще НЕ операция KIR — ключа `op` у элемента нет.
    #:
    #: Отдельно от `SELECTOR_UNRESOLVED` намеренно, и это не педантизм. До
    #: 04.08 конверт программы (`{"ops": […]}` — элемент ПАЧКИ) и узел L1
    #: декомпилятора попадали сюда же, и план говорил «селектор уровня не
    #: сведён к плану»: утверждение о поле, которого у пришедшего нет ВООБЩЕ.
    #: Модель, прочитавшая его, идёт чинить уровни — то есть ровно та ложь о
    #: входе, ради запрета которой у вердикта заведён `KIR-V001`.
    NOT_AN_OP = "not_an_op"


class ApproxReason(str, Enum):
    """Элемент НАРИСОВАН, но не точно.  Третья колонка переписи."""

    #: Контур взят из AABB — это габарит, а не профиль.
    FOOTPRINT_FROM_BBOX = "footprint_from_bbox"
    #: Толщина неизвестна — нарисована ось.
    THICKNESS_UNKNOWN = "thickness_unknown"
    #: Ширина проёма неизвестна — поставлена засечка.
    OPENING_WIDTH_UNKNOWN = "opening_width_unknown"
    #: Сторона открывания двери из источника не читается (в L0 её нет как
    #: поля, в программе она за флагами створки) — показана условно.
    DOOR_SWING_UNKNOWN = "door_swing_unknown"
    #: Дуга представлена выборкой точек.
    ARC_SAMPLED = "arc_sampled"
    #: Помещение в программе — точка: границу считает Revit, не автор.
    ROOM_BOUNDARY_NOT_COMPUTED = "room_boundary_not_computed"
    #: Уровень взят не из level_id, а из параметра (лестницы держат
    #: STAIRS_BASE_LEVEL_PARAM, экстрактор читает Element.Level и возвращает
    #: None — известная дыра, см. карту компилятора §8.1).
    LEVEL_VIA_PARAMETER = "level_via_parameter"


class AnomalyReason(str, Enum):
    """Нарисовано, и геометрия подозрительная.  Ровно то, ради чего экран.

    Это НЕ приёмка и НЕ вердикт: список заведомо неполон, а аномалия не
    означает дефекта.  Она означает «посмотри сюда».
    """

    #: Проём целиком за пределами своей стены.
    OPENING_OUTSIDE_HOST = "opening_outside_host"
    #: Проём шире стены, в которой стоит.
    OPENING_WIDER_THAN_HOST = "opening_wider_than_host"
    #: Две стены с совпадающими концами (дубль).
    COINCIDENT_WALLS = "coincident_walls"
    #: Помещение с нулевой площадью (не замкнулось).
    ROOM_NOT_ENCLOSED = "room_not_enclosed"
    #: Элемент лежит далеко за облаком остальных — «улетевшая» геометрия.
    FAR_OUTLIER = "far_outlier"


#: Чего этот экран НЕ показывает.  Печатается на самом листе: список слепоты
#: полезнее списка возможностей, потому что молчание превью читается как «всё
#: в порядке».
BLIND_SPOTS: tuple[str, ...] = (
    "высоты, отметки, вертикальные привязки — план это срез XY",
    "замкнутость оболочки и стыковку стен (стены рисуются осями и телами, "
    "а не булевым объединением)",
    "типы, материалы, слои конструкции",
    "что элемент попал не на тот уровень, если уровень назван верно",
    "перекрытия и кровли без бокового эскиза (габарит намеренно не рисуется)",
    "пересечения и коллизии в трёх измерениях",
)


class Layer(str, Enum):
    """Порядок отрисовки снизу вверх.  Значение = ключ стиля."""

    ROOM = "room"
    SLAB = "slab"
    FIXTURE = "fixture"
    MEP = "mep"
    LINE = "line"
    SEPARATION = "separation"
    GRID = "grid"
    STAIR = "stair"
    WALL = "wall"
    OPENING = "opening"
    COLUMN = "column"
    LABEL = "label"


_LAYER_ORDER: tuple[Layer, ...] = (
    Layer.ROOM, Layer.SLAB, Layer.FIXTURE, Layer.MEP, Layer.LINE,
    Layer.SEPARATION, Layer.GRID, Layer.STAIR, Layer.WALL, Layer.OPENING,
    Layer.COLUMN, Layer.LABEL,
)
_LAYER_INDEX = {layer: index for index, layer in enumerate(_LAYER_ORDER)}


# ---------------------------------------------------------------------------
# 2. Промежуточный язык форм — то единственное, что видит рисовальщик
# ---------------------------------------------------------------------------

Pt = tuple[float, float]


def _pt(value: Sequence[float]) -> Pt:
    x, y = float(value[0]), float(value[1])
    if not (math.isfinite(x) and math.isfinite(y)):
        raise PreviewError("координата не конечна")
    return (x, y)


@dataclass(frozen=True, slots=True)
class Poly:
    """Замкнутый контур с дырами.  ``loops[0]`` — внешний."""

    loops: tuple[tuple[Pt, ...], ...]
    role: str = "solid"          # solid | outline | void

    def points(self) -> Iterable[Pt]:
        for loop in self.loops:
            yield from loop


@dataclass(frozen=True, slots=True)
class Path:
    """Незамкнутая ломаная."""

    pts: tuple[Pt, ...]
    role: str = "line"           # line | thin | dashed | axis | tick

    def points(self) -> Iterable[Pt]:
        return self.pts


@dataclass(frozen=True, slots=True)
class Dot:
    xy: Pt
    r_mm: float = 60.0
    role: str = "dot"

    def points(self) -> Iterable[Pt]:
        return (self.xy,)


@dataclass(frozen=True, slots=True)
class TextMark:
    xy: Pt
    text: str
    role: str = "label"          # label | tiny | bubble
    min_area_mm2: float = 0.0    # подпись печатается, если места хватает

    def points(self) -> Iterable[Pt]:
        return ()                # подпись не расширяет габарит


Shape = Poly | Path | Dot | TextMark


@dataclass(frozen=True, slots=True)
class DrawnElement:
    """Один нарисованный элемент и вся правда о качестве его отрисовки."""

    element_id: str
    category: str
    layer: Layer
    shapes: tuple[Shape, ...]
    approx: tuple[ApproxReason, ...] = ()
    anomalies: tuple[AnomalyReason, ...] = ()
    label: str = ""

    def __post_init__(self) -> None:
        if not self.element_id:
            raise PreviewError("у нарисованного элемента должен быть id")
        if not self.shapes:
            raise PreviewError(
                f"{self.element_id}: «нарисован» без единой фигуры — это "
                "потеря, а не отрисовка; такой элемент обязан уйти в перепись")

    def extent(self) -> tuple[float, float, float, float] | None:
        xs: list[float] = []
        ys: list[float] = []
        for shape in self.shapes:
            for x, y in shape.points():
                xs.append(x)
                ys.append(y)
        if not xs:
            return None
        return (min(xs), min(ys), max(xs), max(ys))


# ---------------------------------------------------------------------------
# 3. Перепись — ЗАКОН №4, выраженный структурно
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class OmissionGroup:
    reason: OmitReason
    category: str
    count: int
    examples: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"reason": self.reason.value, "category": self.category,
                "count": self.count, "examples": list(self.examples)}


@dataclass(frozen=True, slots=True)
class ApproxGroup:
    reason: ApproxReason
    count: int
    examples: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"reason": self.reason.value, "count": self.count,
                "examples": list(self.examples)}


@dataclass(frozen=True, slots=True)
class AnomalyGroup:
    reason: AnomalyReason
    count: int
    examples: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"reason": self.reason.value, "count": self.count,
                "examples": list(self.examples)}


@dataclass(frozen=True, slots=True)
class PreviewCensus:
    """«Нарисовано 412 из 480; не нарисовано 68: …» — и это ПРОВЕРЯЕТСЯ.

    Тождество ``considered == drawn + Σ count`` стоит в ``__post_init__``, а не
    в тесте, потому что тест можно забыть написать для нового пути, а
    конструктор обойти нельзя.
    """

    considered: int
    drawn: int
    omitted: tuple[OmissionGroup, ...] = ()
    approx: tuple[ApproxGroup, ...] = ()
    anomalies: tuple[AnomalyGroup, ...] = ()

    def __post_init__(self) -> None:
        for name in ("considered", "drawn"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise PreviewCensusError(f"{name} — неотрицательное целое")
        missing = sum(group.count for group in self.omitted)
        if self.considered != self.drawn + missing:
            raise PreviewCensusError(
                f"ЗАКОН №4 нарушен: рассмотрено {self.considered}, "
                f"нарисовано {self.drawn}, названо причин на {missing}; "
                f"молча потеряно {self.considered - self.drawn - missing}")

    @property
    def omitted_total(self) -> int:
        return sum(group.count for group in self.omitted)

    @property
    def approx_total(self) -> int:
        return sum(group.count for group in self.approx)

    @property
    def anomaly_total(self) -> int:
        return sum(group.count for group in self.anomalies)

    @property
    def coverage_pct(self) -> float:
        if self.considered == 0:
            return 0.0
        return 100.0 * self.drawn / self.considered

    @property
    def vacuous(self) -> bool:
        """Ничего не рассматривали.  Отдельное поле, а не 100% покрытия —
        тот же приём, что у ``Verdict.vacuous`` в приёмке."""
        return self.considered == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "considered": self.considered,
            "drawn": self.drawn,
            "omitted_total": self.omitted_total,
            "coverage_pct": round(self.coverage_pct, 2),
            "vacuous": self.vacuous,
            "omitted": [group.to_dict() for group in self.omitted],
            "approx": [group.to_dict() for group in self.approx],
            "anomalies": [group.to_dict() for group in self.anomalies],
        }


class _CensusBuilder:
    """Накопитель переписи.  Детерминированный порядок обеспечивает сортировка
    в :meth:`build`, а не порядок вставки."""

    __slots__ = ("_omitted", "_approx", "_anomalies", "considered", "drawn")

    def __init__(self) -> None:
        self._omitted: dict[tuple[str, str], list[Any]] = {}
        self._approx: dict[str, list[Any]] = {}
        self._anomalies: dict[str, list[Any]] = {}
        self.considered = 0
        self.drawn = 0

    def offer(self, count: int = 1) -> None:
        self.considered += count

    def omit(self, element_id: str, category: str, reason: OmitReason,
             count: int = 1) -> None:
        key = (reason.value, category)
        slot = self._omitted.setdefault(key, [0, []])
        slot[0] += count
        if len(slot[1]) < MAX_EXAMPLES and element_id:
            slot[1].append(element_id)

    def draw(self, element: DrawnElement) -> None:
        self.drawn += 1
        for reason in element.approx:
            slot = self._approx.setdefault(reason.value, [0, []])
            slot[0] += 1
            if len(slot[1]) < MAX_EXAMPLES:
                slot[1].append(element.element_id)
        for reason in element.anomalies:
            slot = self._anomalies.setdefault(reason.value, [0, []])
            slot[0] += 1
            if len(slot[1]) < MAX_EXAMPLES:
                slot[1].append(element.element_id)

    def absorb(self, census: PreviewCensus) -> None:
        self.considered += census.considered
        self.drawn += census.drawn
        for group in census.omitted:
            slot = self._omitted.setdefault(
                (group.reason.value, group.category), [0, []])
            slot[0] += group.count
            for example in group.examples:
                if len(slot[1]) < MAX_EXAMPLES:
                    slot[1].append(example)
        for group in census.approx:
            slot = self._approx.setdefault(group.reason.value, [0, []])
            slot[0] += group.count
            for example in group.examples:
                if len(slot[1]) < MAX_EXAMPLES:
                    slot[1].append(example)
        for group in census.anomalies:
            slot = self._anomalies.setdefault(group.reason.value, [0, []])
            slot[0] += group.count
            for example in group.examples:
                if len(slot[1]) < MAX_EXAMPLES:
                    slot[1].append(example)

    def build(self) -> PreviewCensus:
        omitted = tuple(
            OmissionGroup(OmitReason(reason), category, slot[0],
                          tuple(slot[1]))
            for (reason, category), slot in sorted(
                self._omitted.items(), key=lambda kv: (-kv[1][0], kv[0]))
        )
        approx = tuple(
            ApproxGroup(ApproxReason(reason), slot[0], tuple(slot[1]))
            for reason, slot in sorted(
                self._approx.items(), key=lambda kv: (-kv[1][0], kv[0]))
        )
        anomalies = tuple(
            AnomalyGroup(AnomalyReason(reason), slot[0], tuple(slot[1]))
            for reason, slot in sorted(
                self._anomalies.items(), key=lambda kv: (-kv[1][0], kv[0]))
        )
        return PreviewCensus(self.considered, self.drawn, omitted, approx,
                             anomalies)


# ---------------------------------------------------------------------------
# 4. План и здание
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class FloorPlan:
    source: PreviewSource
    doc_name: str
    level_name: str
    level_elevation_mm: float | None
    elements: tuple[DrawnElement, ...]
    census: PreviewCensus
    datums: tuple[DrawnElement, ...] = ()
    notes: tuple[str, ...] = ()
    #: Кадр по ЯДРУ облака: улетевшая геометрия не имеет права утащить масштаб
    #: и спрятать здание.  Она всё равно рисуется (и обрезается полем), и
    #: всё равно названа в переписи как :attr:`AnomalyReason.FAR_OUTLIER`.
    frame_mm: tuple[float, float, float, float] | None = None
    outliers: int = 0

    @property
    def assertion(self) -> Assertion:
        return self.source.assertion

    def extents_mm(self) -> tuple[float, float, float, float] | None:
        if self.frame_mm is not None:
            return self.frame_mm
        boxes = [element.extent() for element in self.elements]
        boxes = [box for box in boxes if box is not None]
        if not boxes:
            boxes = [box for box in (d.extent() for d in self.datums)
                     if box is not None]
        if not boxes:
            return None
        return (min(b[0] for b in boxes), min(b[1] for b in boxes),
                max(b[2] for b in boxes), max(b[3] for b in boxes))

    def to_dict(self) -> dict[str, Any]:
        extents = self.extents_mm()
        return {
            "schema": PREVIEW_SCHEMA,
            "source": self.source.value,
            "assertion": self.assertion.value,
            "doc_name": self.doc_name,
            "level_name": self.level_name,
            "level_elevation_mm": self.level_elevation_mm,
            "extents_mm": list(extents) if extents else None,
            "census": self.census.to_dict(),
            "datums_drawn": len(self.datums),
            "outliers_outside_frame": self.outliers,
            "notes": list(self.notes),
        }

    @property
    def content_digest(self) -> str:
        """Подпись содержимого плана — без неё лист нельзя ни сравнить, ни
        положить в квитанцию как доказательство."""
        payload = {
            "meta": self.to_dict(),
            "elements": [
                {"id": e.element_id, "cat": e.category, "layer": e.layer.value,
                 "shapes": _shapes_digest_payload(e.shapes),
                 "approx": [r.value for r in e.approx],
                 "anomalies": [r.value for r in e.anomalies]}
                for e in self.elements
            ],
        }
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False,
                          separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class BuildingPreview:
    source: PreviewSource
    doc_name: str
    revit_version: str
    change_stamp: str
    plans: tuple[FloorPlan, ...]
    census: PreviewCensus
    levels_total: int = 0

    @property
    def assertion(self) -> Assertion:
        return self.source.assertion

    def plan(self, level_name: str) -> FloorPlan:
        for item in self.plans:
            if item.level_name == level_name:
                return item
        raise KeyError(level_name)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": PREVIEW_SCHEMA,
            "source": self.source.value,
            "assertion": self.assertion.value,
            "doc_name": self.doc_name,
            "revit_version": self.revit_version,
            "change_stamp": self.change_stamp,
            "levels_total": self.levels_total,
            "levels_rendered": len(self.plans),
            "census": self.census.to_dict(),
            "plans": [p.to_dict() for p in self.plans],
        }


def _shapes_digest_payload(shapes: Sequence[Shape]) -> list[Any]:
    out: list[Any] = []
    for shape in shapes:
        if isinstance(shape, Poly):
            out.append(["poly", shape.role,
                        [[[_round(x), _round(y)] for x, y in loop]
                         for loop in shape.loops]])
        elif isinstance(shape, Path):
            out.append(["path", shape.role,
                        [[_round(x), _round(y)] for x, y in shape.pts]])
        elif isinstance(shape, Dot):
            out.append(["dot", shape.role,
                        [_round(shape.xy[0]), _round(shape.xy[1])],
                        _round(shape.r_mm)])
        else:
            out.append(["text", shape.role,
                        [_round(shape.xy[0]), _round(shape.xy[1])], shape.text])
    return out


def _round(value: float) -> float:
    return round(float(value), 3) + 0.0


# ---------------------------------------------------------------------------
# 5. Геометрические примитивы
# ---------------------------------------------------------------------------

#: Короче этого стена/линия считается вырожденной (мм).  То же число, что у
#: ``geom._EDGE_TOL``: ниже него Revit сам отказывается строить кривую.
MIN_EDGE_MM = 1.0
#: Допуск, в пределах которого проём считается лежащим на стене (мм).
OPENING_ON_HOST_TOL_MM = 25.0
#: Шаг выборки дуги (рад).  Фиксирован — иначе теряется детерминизм байтов.
ARC_STEP_RAD = math.pi / 32.0
ARC_MAX_SAMPLES = 128


def _unit(dx: float, dy: float) -> tuple[float, float] | None:
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return None
    return (dx / length, dy / length)


def _band(a: Pt, b: Pt, thickness_mm: float) -> tuple[Pt, ...]:
    """Тело стены: прямоугольник ширины ``thickness_mm`` вокруг оси a→b."""
    direction = _unit(b[0] - a[0], b[1] - a[1])
    if direction is None:
        raise PreviewError("нулевая ось — тело не построить")
    nx, ny = -direction[1] * thickness_mm / 2.0, direction[0] * thickness_mm / 2.0
    return ((a[0] + nx, a[1] + ny), (b[0] + nx, b[1] + ny),
            (b[0] - nx, b[1] - ny), (a[0] - nx, a[1] - ny))


def _sample_arc(center: Sequence[float], radius: float,
                x_axis: Sequence[float], y_axis: Sequence[float],
                a0: float, a1: float) -> tuple[Pt, ...]:
    span = a1 - a0
    steps = int(math.ceil(abs(span) / ARC_STEP_RAD))
    steps = max(4, min(ARC_MAX_SAMPLES, steps))
    pts: list[Pt] = []
    for i in range(steps + 1):
        ang = a0 + span * i / steps
        ca, sa = math.cos(ang), math.sin(ang)
        pts.append((center[0] + radius * (ca * x_axis[0] + sa * y_axis[0]),
                    center[1] + radius * (ca * x_axis[1] + sa * y_axis[1])))
    return tuple(pts)


def _arc_through(a: Pt, mid: Pt, b: Pt) -> tuple[Pt, ...]:
    """Выборка дуги по трём точкам.  Вырожденный случай — отрезок a→b."""
    ax, ay = a
    bx, by = mid
    cx, cy = b
    d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-9:
        return (a, mid, b)
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay)
          + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx)
          + (cx * cx + cy * cy) * (bx - ax)) / d
    radius = math.hypot(ax - ux, ay - uy)
    if not math.isfinite(radius) or radius < 1e-6 or radius > 1e9:
        return (a, mid, b)
    t0 = math.atan2(ay - uy, ax - ux)
    tm = math.atan2(by - uy, bx - ux)
    t1 = math.atan2(cy - uy, cx - ux)
    # Развернуть так, чтобы середина лежала между концами.
    two_pi = 2.0 * math.pi
    forward = (t1 - t0) % two_pi
    mid_forward = (tm - t0) % two_pi
    span = forward if mid_forward <= forward else forward - two_pi
    return _sample_arc((ux, uy), radius, (1.0, 0.0), (0.0, 1.0), t0, t0 + span)


def _ring_area(loop: Sequence[Pt]) -> float:
    total = 0.0
    n = len(loop)
    for i in range(n):
        x0, y0 = loop[i]
        x1, y1 = loop[(i + 1) % n]
        total += x0 * y1 - x1 * y0
    return abs(total) / 2.0


def _bbox_rect(bbox_min: Sequence[float], bbox_max: Sequence[float]
               ) -> tuple[Pt, ...]:
    x0, y0 = float(bbox_min[0]), float(bbox_min[1])
    x1, y1 = float(bbox_max[0]), float(bbox_max[1])
    return ((x0, y0), (x1, y0), (x1, y1), (x0, y1))


# ---------------------------------------------------------------------------
# 6. Таблица правил: категория -> как рисовать
# ---------------------------------------------------------------------------

class _Rule(str, Enum):
    WALL = "wall"
    SLAB = "slab"                 # контур только из бокового эскиза
    OPENING = "opening"
    ROOM = "room"
    GRID = "grid"
    COLUMN = "column"
    STAIR = "stair"
    CURVE_MEMBER = "curve_member"
    MEP_LINE = "mep_line"
    THIN_LINE = "thin_line"
    FIXTURE = "fixture"           # габаритный след, честно назван приближением
    ANNOTATION = "annotation"
    NOT_IN_PLAN = "not_in_plan"
    DERIVED = "derived"


_CATEGORY_RULES: dict[str, _Rule] = {
    "OST_Walls": _Rule.WALL,
    "OST_Floors": _Rule.SLAB,
    "OST_Roofs": _Rule.SLAB,
    "OST_Ceilings": _Rule.SLAB,
    "OST_Columns": _Rule.COLUMN,
    "OST_StructuralColumns": _Rule.COLUMN,
    "OST_StructuralFoundation": _Rule.FIXTURE,
    "OST_StructuralFraming": _Rule.CURVE_MEMBER,
    "OST_StructuralTruss": _Rule.CURVE_MEMBER,
    "OST_Doors": _Rule.OPENING,
    "OST_Windows": _Rule.OPENING,
    "OST_Stairs": _Rule.STAIR,
    "OST_StairsRailing": _Rule.THIN_LINE,
    "OST_Ramps": _Rule.FIXTURE,
    "OST_Rooms": _Rule.ROOM,
    "OST_MEPSpaces": _Rule.FIXTURE,
    "OST_Areas": _Rule.FIXTURE,
    "OST_Grids": _Rule.GRID,
    "OST_Levels": _Rule.NOT_IN_PLAN,
    "OST_RoomSeparationLines": _Rule.THIN_LINE,
    "OST_Lines": _Rule.THIN_LINE,
    "OST_PipeCurves": _Rule.MEP_LINE,
    "OST_DuctCurves": _Rule.MEP_LINE,
    "OST_FlexPipeCurves": _Rule.MEP_LINE,
    "OST_FlexDuctCurves": _Rule.MEP_LINE,
    "OST_CableTray": _Rule.MEP_LINE,
    "OST_Conduit": _Rule.MEP_LINE,
    "OST_PipeInsulations": _Rule.MEP_LINE,
    "OST_DuctInsulations": _Rule.MEP_LINE,
    "OST_DuctLinings": _Rule.MEP_LINE,
    "OST_CurtainWallPanels": _Rule.CURVE_MEMBER,
    "OST_CurtainWallMullions": _Rule.FIXTURE,
    "OST_CurtaSystem": _Rule.FIXTURE,
    "OST_CurtainGridsWall": _Rule.DERIVED,
    "OST_CurtainGridsRoof": _Rule.DERIVED,
    "OST_CurtainGridsCurtaSystem": _Rule.DERIVED,
    "OST_Furniture": _Rule.FIXTURE,
    "OST_Casework": _Rule.FIXTURE,
    "OST_PlumbingFixtures": _Rule.FIXTURE,
    "OST_SpecialityEquipment": _Rule.FIXTURE,
    "OST_MechanicalEquipment": _Rule.FIXTURE,
    "OST_ElectricalEquipment": _Rule.FIXTURE,
    "OST_ElectricalFixtures": _Rule.FIXTURE,
    "OST_LightingFixtures": _Rule.FIXTURE,
    "OST_LightingDevices": _Rule.FIXTURE,
    "OST_TelephoneDevices": _Rule.FIXTURE,
    "OST_Sprinklers": _Rule.FIXTURE,
    "OST_DuctTerminal": _Rule.FIXTURE,
    "OST_DuctFitting": _Rule.FIXTURE,
    "OST_PipeFitting": _Rule.FIXTURE,
    "OST_PipeAccessory": _Rule.FIXTURE,
    "OST_CableTrayFitting": _Rule.FIXTURE,
    "OST_ConduitFitting": _Rule.FIXTURE,
    "OST_GenericModel": _Rule.FIXTURE,
    "DirectShape": _Rule.FIXTURE,
    "ImportInstance": _Rule.FIXTURE,
    "OST_RasterImages": _Rule.ANNOTATION,
    "OST_Dimensions": _Rule.ANNOTATION,
    "OST_TextNotes": _Rule.ANNOTATION,
    "OST_SpotElevations": _Rule.ANNOTATION,
    "OST_SpotSlopes": _Rule.ANNOTATION,
    "OST_GenericAnnotation": _Rule.ANNOTATION,
    "OST_DetailComponents": _Rule.ANNOTATION,
    "OST_RoomTags": _Rule.ANNOTATION,
    "OST_DoorTags": _Rule.ANNOTATION,
    "OST_WallTags": _Rule.ANNOTATION,
    "OST_FloorTags": _Rule.ANNOTATION,
    "OST_AreaTags": _Rule.ANNOTATION,
    "OST_StairsRailingTags": _Rule.ANNOTATION,
    "OST_StructuralFramingTags": _Rule.ANNOTATION,
    "OST_MechanicalEquipmentTags": _Rule.ANNOTATION,
    "OST_MaterialTags": _Rule.ANNOTATION,
    "OST_MultiCategoryTags": _Rule.ANNOTATION,
}

_RULE_LAYER: dict[_Rule, Layer] = {
    _Rule.WALL: Layer.WALL,
    _Rule.SLAB: Layer.SLAB,
    _Rule.OPENING: Layer.OPENING,
    _Rule.ROOM: Layer.ROOM,
    _Rule.GRID: Layer.GRID,
    _Rule.COLUMN: Layer.COLUMN,
    _Rule.STAIR: Layer.STAIR,
    _Rule.CURVE_MEMBER: Layer.LINE,
    _Rule.MEP_LINE: Layer.MEP,
    _Rule.THIN_LINE: Layer.SEPARATION,
    _Rule.FIXTURE: Layer.FIXTURE,
}

#: Категории-датумы: они не принадлежат этажу и рисуются на каждом плане.
_DATUM_CATEGORIES = frozenset({"OST_Grids"})

#: Параметры, по которым уровень восстанавливается, когда ``level_id`` пуст.
#: Порядок значим и зафиксирован: первый совпавший выигрывает.
_LEVEL_PARAM_FALLBACKS: tuple[str, ...] = (
    "STAIRS_BASE_LEVEL_PARAM",
    "FAMILY_BASE_LEVEL_PARAM",
    "WALL_BASE_CONSTRAINT",
    "ROOF_BASE_LEVEL_PARAM",
    "SCHEDULE_LEVEL_PARAM",
)


# ---------------------------------------------------------------------------
# 7. ФРОНТ-ЭНД A: превью из ПРОГРАММЫ («что я СОБИРАЮСЬ построить»)
# ---------------------------------------------------------------------------

_PROGRAM_LEVEL_FIELDS = ("level", "base_level", "host_level")


def _selector_key(sel: Any) -> str | None:
    """Ключ уровня из селектора.  ``None`` — селектор не сводится к плану."""
    if not isinstance(sel, Mapping):
        return None
    by = sel.get("by")
    value = sel.get("value")
    if by == "name" and isinstance(value, str) and value.strip():
        return value.strip()
    if by == "ref" and isinstance(value, str) and value.strip():
        return "$" + value.strip()
    if by == "element_id" and isinstance(value, int) and not isinstance(value, bool):
        return "#" + str(value)
    return None


def _program_ops(program: Any) -> list[dict[str, Any]]:
    if hasattr(program, "to_ops"):
        return list(program.to_ops())
    if isinstance(program, Mapping) and "ops" in program:
        return [dict(op) for op in program["ops"]]
    if isinstance(program, Sequence) and not isinstance(program, (str, bytes)):
        return [dict(op) for op in program]
    raise PreviewError("программа — PlannedProgram, {ops: [...]} или список опов")


def build_program_preview(
    program: Any,
    *,
    doc_name: str = "(программа KIR)",
    levels: Sequence[str] | None = None,
) -> BuildingPreview:
    """План(ы) из ПРОГРАММЫ — до всякой транзакции.

    Сила утверждения — САМОПРОВЕРКА (:attr:`Assertion.SELF_REPORTED`):
    рисуется то, что автор ЗАЯВИЛ.  Ни один селектор здесь не разрешён по
    настоящему документу, поэтому толщины стен, ширины проёмов и границы
    помещений НЕИЗВЕСТНЫ — и каждое такое незнание попадает в третью колонку
    переписи, а не заменяется правдоподобным числом.
    """
    ops = _program_ops(program)
    intent = getattr(program, "intent", None)
    if intent is None and isinstance(program, Mapping):
        intent = program.get("intent")

    # Имена уровней, объявленных самой программой (create_level).
    level_names: dict[str, str] = {}
    for op in ops:
        if op.get("op") == "create_level":
            oid = str(op.get("id", ""))
            name = op.get("name")
            level_names["$" + oid] = (
                str(name) if isinstance(name, str) and name.strip()
                else f"уровень {oid}")

    # ОДИН ЭТАЖ — ОДИН ЛИСТ, чем бы его ни адресовали.
    #
    # `create_wall(level={"by":"ref"})` даёт ключ `$L1`, а `create_stairs(
    # base_level={"by":"name"})` — «Этаж 1»: ссылку `base_level` не принимает
    # ВООБЩЕ, поэтому в пачке обе формы стоят рядом ВСЕГДА, а не изредка. Без
    # сведения ключей один этаж выходил ДВУМЯ листами с одинаковым названием —
    # тот же раскол, о котором предупреждает шапка `live/journal.py`. Сводится
    # только ОДНОЗНАЧНОЕ имя: два `create_level` с одним именем — это не повод
    # выбрать любой из них.
    _by_label: dict[str, list[str]] = {}
    for key, label in level_names.items():
        _by_label.setdefault(label, []).append(key)
    alias = {label: keys[0] for label, keys in _by_label.items()
             if len(keys) == 1}

    def level_key_of(op: Mapping[str, Any]) -> str | None:
        key = _op_level_key(op)
        return alias.get(key, key) if key is not None else None

    # Стены программы — хосты для проёмов.
    walls: dict[str, dict[str, Any]] = {}
    for op in ops:
        if op.get("op") == "create_wall":
            oid = str(op.get("id", ""))
            try:
                p0 = _pt(op["p0_mm"])
                p1 = _pt(op["p1_mm"])
            except (KeyError, TypeError, IndexError, PreviewError):
                continue
            walls[oid] = {"p0": p0, "p1": p1, "arc": op.get("arc"),
                          "level": level_key_of(op)}

    buckets: dict[str, list[DrawnElement]] = {}
    datums: list[DrawnElement] = []
    building = _CensusBuilder()
    per_level: dict[str, _CensusBuilder] = {}

    def bucket_for(key: str) -> _CensusBuilder:
        return per_level.setdefault(key, _CensusBuilder())

    # Каждая операция предъявляется РОВНО ОДНОМУ счётчику: либо зданию
    # (датумы и неразрешённые селекторы), либо своему этажу — иначе тождество
    # закона №4 сходилось бы на удвоенном знаменателе и покрытие врало бы вниз.
    for op in ops:
        name = str(op.get("op", ""))
        oid = str(op.get("id", "")) or name
        if not name:
            # НЕ ОПЕРАЦИЯ ВОВСЕ. Ключ `op` — единственный, который есть у каждой
            # операции KIR и ни у одного узла L1 (`_shape_of` в вердикте стоит
            # на том же признаке). Раньше такой элемент падал ниже и получал
            # диагноз «селектор уровня не сведён к плану» — утверждение о поле,
            # которого у него нет вовсе.
            building.offer()
            building.omit(oid, "", OmitReason.NOT_AN_OP)
            continue
        if name in ("create_grid", "create_level"):
            # Датум: живёт вне этажа.  create_grid рисуется на каждом плане,
            # create_level — вообще не план-объект.
            building.offer()
            if name == "create_grid":
                drawn = _program_grid(op, oid)
                if drawn is not None:
                    datums.append(drawn)
                    building.draw(drawn)
                    continue
                building.omit(oid, name, OmitReason.DEGENERATE)
            else:
                building.omit(oid, name, OmitReason.NOT_VISIBLE_IN_PLAN)
            continue

        level_key = level_key_of(op)
        if level_key is None and name in ("create_door", "create_window"):
            host = op.get("host")
            host_ref = (host.get("value")
                        if isinstance(host, Mapping) and host.get("by") == "ref"
                        else None)
            if isinstance(host_ref, str) and host_ref in walls:
                level_key = walls[host_ref]["level"]
        if level_key is None:
            building.offer()
            building.omit(oid, name, OmitReason.SELECTOR_UNRESOLVED)
            continue

        bucket = bucket_for(level_key)
        bucket.offer()
        drawn, reason = _program_shape(op, oid, walls)
        if drawn is None:
            bucket.omit(oid, name, reason or OmitReason.OP_NOT_DRAWN)
            continue
        buckets.setdefault(level_key, []).append(drawn)

    wanted = set(levels) if levels is not None else None
    plans: list[FloorPlan] = []
    for level_key in sorted(per_level):
        label = level_names.get(level_key, level_key.lstrip("$"))
        raw = buckets.get(level_key, [])
        flagged, frame, outliers = _flag_far_outliers(raw)
        bucket = per_level[level_key]
        for element in flagged:
            bucket.draw(element)
        census = bucket.build()
        if wanted is not None and label not in wanted and level_key not in wanted:
            building.offer(census.considered)
            building.omit("", f"(этаж {label})", OmitReason.LEVEL_NOT_IN_RUN,
                          count=census.considered)
            continue
        building.absorb(census)
        plans.append(FloorPlan(
            source=PreviewSource.PROGRAM,
            doc_name=doc_name,
            level_name=label,
            level_elevation_mm=_program_level_elevation(ops, level_key),
            elements=tuple(sorted(flagged, key=_sort_key)),
            census=census,
            datums=tuple(sorted(datums, key=_sort_key)),
            frame_mm=frame,
            outliers=outliers,
            notes=_notes_for(census, PreviewSource.PROGRAM,
                             str(intent or "")),
        ))

    return BuildingPreview(
        source=PreviewSource.PROGRAM,
        doc_name=doc_name,
        revit_version="(не применимо: документ не открывался)",
        change_stamp=getattr(program, "plan_digest", "") or "(нет плана)",
        plans=tuple(plans),
        census=building.build(),
        levels_total=len(per_level),
    )


def _program_level_elevation(ops: Sequence[Mapping[str, Any]],
                             level_key: str) -> float | None:
    """Отметка уровня, объявленная САМОЙ программой. `None` — не выводится.

    АДРЕСАЦИЯ ПО ИМЕНИ РАВНОПРАВНА СО ССЫЛКОЙ, и до 04.08 её здесь не было
    вовсе: резолвился только `$id`, а по имени печаталось «отм. None мм». Это
    слепота ровно на той форме, которую предписывает закон пачки —
    `create_stairs.base_level` ссылку не принимает (`ref_kinds` пуст), и
    уровень соседней программы виден только по ИМЕНИ. Глаза модели гасли на
    единственной форме, которой она обязана пользоваться.

    НЕОДНОЗНАЧНОСТЬ ОСТАЁТСЯ НЕИЗВЕСТНОСТЬЮ. Два `create_level` с одним именем
    и разными отметками — это не повод «взять первый»: правдоподобное число
    здесь дороже честного пробела, потому что отличить его от верного нечем.
    Совпадающие отметки неоднозначности не создают.
    """
    if level_key.startswith("$"):
        target, field = level_key[1:], "id"
    else:
        target, field = level_key, "name"
    found: set[float] = set()
    for op in ops:
        if op.get("op") != "create_level":
            continue
        if str(op.get(field, "")).strip() != target:
            continue
        value = op.get("elev_mm")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            found.add(float(value))
    return found.pop() if len(found) == 1 else None


def _op_level_key(op: Mapping[str, Any]) -> str | None:
    for field_name in _PROGRAM_LEVEL_FIELDS:
        if field_name in op:
            key = _selector_key(op[field_name])
            if key is not None:
                return key
    return None


def _program_grid(op: Mapping[str, Any], oid: str) -> DrawnElement | None:
    try:
        p0 = _pt(op["p0_mm"])
        p1 = _pt(op["p1_mm"])
    except (KeyError, TypeError, IndexError, PreviewError):
        return None
    if math.dist(p0, p1) < MIN_EDGE_MM:
        return None
    name = op.get("name")
    label = str(name) if isinstance(name, str) and name.strip() else oid
    return DrawnElement(oid, "create_grid", Layer.GRID,
                        (Path((p0, p1), role="axis"),
                         TextMark(p0, label, role="bubble"),
                         TextMark(p1, label, role="bubble")),
                        label=label)


def _program_shape(
    op: Mapping[str, Any], oid: str, walls: Mapping[str, dict[str, Any]],
) -> tuple[DrawnElement | None, OmitReason | None]:
    name = str(op.get("op", ""))
    try:
        if name == "create_wall":
            p0 = _pt(op["p0_mm"])
            p1 = _pt(op["p1_mm"])
            if math.dist(p0, p1) < MIN_EDGE_MM:
                return None, OmitReason.DEGENERATE
            approx = [ApproxReason.THICKNESS_UNKNOWN]
            arc = op.get("arc")
            if isinstance(arc, Mapping) and arc.get("curve_type") == "Arc":
                pts = _sample_arc(arc["center_mm"], float(arc["radius_mm"]),
                                  arc["x_axis"], arc["y_axis"],
                                  float(arc["start_angle_rad"]),
                                  float(arc["end_angle_rad"]))
                approx.append(ApproxReason.ARC_SAMPLED)
                shapes: tuple[Shape, ...] = (Path(pts, role="spine"),)
            else:
                shapes = (Path((p0, p1), role="spine"),)
            return DrawnElement(oid, name, Layer.WALL, shapes,
                                approx=tuple(approx)), None

        if name in ("create_door", "create_window"):
            host = op.get("host")
            if not (isinstance(host, Mapping) and host.get("by") == "ref"):
                return None, OmitReason.HOST_UNKNOWN
            host_id = str(host.get("value", ""))
            wall = walls.get(host_id)
            if wall is None:
                return None, OmitReason.HOST_NOT_DRAWABLE
            offset = op.get("offset_mm")
            if not isinstance(offset, (int, float)) or isinstance(offset, bool):
                return None, OmitReason.NO_GEOMETRY
            p0, p1 = wall["p0"], wall["p1"]
            direction = _unit(p1[0] - p0[0], p1[1] - p0[1])
            if direction is None:
                return None, OmitReason.HOST_NOT_DRAWABLE
            length = math.dist(p0, p1)
            at = (p0[0] + direction[0] * float(offset),
                  p0[1] + direction[1] * float(offset))
            normal = (-direction[1], direction[0])
            tick = 400.0
            shapes = (
                Path(((at[0] - normal[0] * tick, at[1] - normal[1] * tick),
                      (at[0] + normal[0] * tick, at[1] + normal[1] * tick)),
                     role="tick"),
                Dot(at, r_mm=90.0),
            )
            anomalies: list[AnomalyReason] = []
            if float(offset) < -OPENING_ON_HOST_TOL_MM or \
                    float(offset) > length + OPENING_ON_HOST_TOL_MM:
                anomalies.append(AnomalyReason.OPENING_OUTSIDE_HOST)
            approx = (ApproxReason.OPENING_WIDTH_UNKNOWN,)
            if name == "create_door":
                approx = approx + (ApproxReason.DOOR_SWING_UNKNOWN,)
            return DrawnElement(oid, name, Layer.OPENING, shapes,
                                approx=approx,
                                anomalies=tuple(anomalies)), None

        if name in ("create_floor", "create_roof", "create_ceiling"):
            outline = op.get("outline")
            if not isinstance(outline, Sequence) or len(outline) < 3:
                return None, OmitReason.NO_GEOMETRY
            loop = tuple(_pt(point) for point in outline)
            if _ring_area(loop) < 1.0:
                return None, OmitReason.DEGENERATE
            loops = [loop]
            holes = op.get("holes")
            if isinstance(holes, Sequence):
                for hole in holes:
                    if isinstance(hole, Sequence) and len(hole) >= 3:
                        loops.append(tuple(_pt(point) for point in hole))
            return DrawnElement(oid, name, Layer.SLAB,
                                (Poly(tuple(loops), role="outline"),)), None

        if name == "create_room":
            xy = _pt(op["xy"])
            label = op.get("name")
            shapes = (Dot(xy, r_mm=140.0),)
            if isinstance(label, str) and label.strip():
                shapes = shapes + (TextMark(xy, label.strip(), role="label"),)
            return DrawnElement(
                oid, name, Layer.ROOM, shapes,
                approx=(ApproxReason.ROOM_BOUNDARY_NOT_COMPUTED,),
                label=str(label or "")), None

        if name == "create_column":
            xy = _pt(op["xy"])
            half = 200.0
            rect = ((xy[0] - half, xy[1] - half), (xy[0] + half, xy[1] - half),
                    (xy[0] + half, xy[1] + half), (xy[0] - half, xy[1] + half))
            return DrawnElement(oid, name, Layer.COLUMN,
                                (Poly((rect,), role="solid"),),
                                approx=(ApproxReason.FOOTPRINT_FROM_BBOX,)), None

        if name in ("create_beam", "create_pipe", "create_duct",
                    "create_cable_tray", "create_conduit"):
            p0 = _pt(op["p0_mm"])
            p1 = _pt(op["p1_mm"])
            if math.dist(p0, p1) < MIN_EDGE_MM:
                return None, OmitReason.DEGENERATE
            layer = Layer.MEP if name != "create_beam" else Layer.LINE
            return DrawnElement(oid, name, layer,
                                (Path((p0, p1), role="thin"),)), None

        if name == "place_family":
            if "xyz" in op and op["xyz"] is not None:
                xy = _pt(op["xyz"])
                return DrawnElement(oid, name, Layer.FIXTURE,
                                    (Dot(xy, r_mm=120.0),)), None
            if op.get("p0_mm") is not None and op.get("p1_mm") is not None:
                p0 = _pt(op["p0_mm"])
                p1 = _pt(op["p1_mm"])
                if math.dist(p0, p1) < MIN_EDGE_MM:
                    return None, OmitReason.DEGENERATE
                return DrawnElement(oid, name, Layer.FIXTURE,
                                    (Path((p0, p1), role="thin"),)), None
            return None, OmitReason.NO_GEOMETRY

        if name == "create_stairs":
            p0 = _pt(op["p0_mm"])
            p1 = _pt(op["p1_mm"])
            if math.dist(p0, p1) < MIN_EDGE_MM:
                return None, OmitReason.DEGENERATE
            return DrawnElement(oid, name, Layer.STAIR,
                                (Path((p0, p1), role="line"),)), None
    except (KeyError, TypeError, IndexError, ValueError):
        return None, OmitReason.NO_GEOMETRY

    return None, OmitReason.OP_NOT_DRAWN


def _sort_key(element: DrawnElement) -> tuple[int, str, int, str]:
    """Порядок отрисовки: слой, категория, id.  Числовые id сортируются
    численно, иначе «10» встало бы раньше «9» и порядок зависел бы от
    ширины идентификатора."""
    ident = element.element_id
    numeric = int(ident) if ident.isdigit() else -1
    return (_LAYER_INDEX[element.layer], element.category, numeric, ident)


# ---------------------------------------------------------------------------
# 8. ФРОНТ-ЭНД B: превью из РАЗБОРА («что в модели ЕСТЬ»)
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class _WallGeom:
    p0: Pt
    p1: Pt
    thickness_mm: float | None
    arc: dict[str, Any] | None


def build_model_preview(
    document: Any,
    elements: Iterable[Any],
    *,
    levels: Sequence[str] | None = None,
    curve_index: Mapping[str, Any] | None = None,
    sketch_index: Mapping[str, Any] | None = None,
) -> BuildingPreview:
    """План(ы) из РАЗБОРА: ``L0Document`` (заголовок) + поток ``L0Element``.

    Сила утверждения — НЕЗАВИСИМОЕ ЧТЕНИЕ (:attr:`Assertion.INDEPENDENT`):
    это то, что в документе ЕСТЬ, а не то, что кто-то собирался построить.

    Функция чистая по отношению к вводу-выводу: поток элементов приходит
    итератором, чтобы 88-мегабайтный ``L0.jsonl`` читался ровно один раз и не
    материализовался целиком (см. :func:`preview_snapshot`).
    """
    level_by_id = {level.id: level for level in document.levels}
    rooms_by_id = {room.id: room for room in document.rooms}
    wanted_names: set[str] | None = set(levels) if levels is not None else None

    keep: dict[str, list[Any]] = {}
    walls: dict[str, _WallGeom] = {}
    building = _CensusBuilder()
    deferred: dict[str, int] = {}
    datum_rows: list[Any] = []
    routed_via_param: set[str] = set()

    # Каждая строка потока предъявляется РОВНО ОДНОМУ счётчику: зданию
    # (датум / этаж не определён / этаж не рисовали) либо своему плану ниже.
    # Иначе тождество закона №4 сошлось бы на удвоенном знаменателе.
    for element in elements:
        category = element.category
        if category in _DATUM_CATEGORIES:
            building.offer()
            datum_rows.append(element)
            continue
        if category == "OST_Walls":
            geom = _wall_geom(element, curve_index)
            if geom is not None:
                walls[element.element_id] = geom
        level_id, via = _route_level(element, level_by_id)
        if level_id is None:
            building.offer()
            building.omit(element.element_id, category, OmitReason.LEVEL_UNKNOWN)
            continue
        if via != "level_id":
            routed_via_param.add(element.element_id)
        level_name = level_by_id[level_id].name
        if wanted_names is not None and level_name not in wanted_names:
            building.offer()
            deferred[level_name] = deferred.get(level_name, 0) + 1
            continue
        keep.setdefault(level_id, []).append(element)

    for level_name in sorted(deferred):
        building.omit("", f"(этаж {level_name})", OmitReason.LEVEL_NOT_IN_RUN,
                      count=deferred[level_name])

    # Датумы (оси) — один раз на здание, рисуются на каждом плане.
    datums: list[DrawnElement] = []
    for grid in document.grids:
        p0 = (float(grid.p0_mm[0]), float(grid.p0_mm[1]))
        p1 = (float(grid.p1_mm[0]), float(grid.p1_mm[1]))
        if math.dist(p0, p1) < MIN_EDGE_MM:
            continue
        datums.append(DrawnElement(
            grid.id, "OST_Grids", Layer.GRID,
            (Path((p0, p1), role="axis"),
             TextMark(p0, grid.name, role="bubble"),
             TextMark(p1, grid.name, role="bubble")),
            label=grid.name))
    drawn_grid_ids = {d.element_id for d in datums}
    for element in datum_rows:
        if element.element_id in drawn_grid_ids:
            building.drawn += 1
        else:
            building.omit(element.element_id, element.category,
                          OmitReason.DEGENERATE)

    plans: list[FloorPlan] = []
    ordered_levels = [level for level in document.levels
                      if wanted_names is None or level.name in wanted_names]
    for level in ordered_levels:
        rows = keep.get(level.id, [])
        census_builder = _CensusBuilder()
        drawn_elements: list[DrawnElement] = []
        wall_key_seen: dict[tuple[int, int, int, int], list[str]] = {}

        for element in sorted(rows, key=_l0_sort_key):
            census_builder.offer()
            drawn, reason = _model_shape(
                element, walls=walls, rooms_by_id=rooms_by_id,
                curve_index=curve_index, sketch_index=sketch_index,
                via_param=element.element_id in routed_via_param)
            if drawn is None:
                census_builder.omit(element.element_id, element.category,
                                    reason or OmitReason.CATEGORY_NOT_DRAWN)
                continue
            if element.category == "OST_Walls":
                geom = walls.get(element.element_id)
                if geom is not None:
                    key = _wall_identity(geom)
                    wall_key_seen.setdefault(key, []).append(element.element_id)
            drawn_elements.append(drawn)

        duplicates = {ident for ids in wall_key_seen.values() if len(ids) > 1
                      for ident in ids}
        if duplicates:
            drawn_elements = [
                (element if element.element_id not in duplicates else
                 DrawnElement(element.element_id, element.category,
                              element.layer, element.shapes, element.approx,
                              tuple(sorted(set(element.anomalies) |
                                           {AnomalyReason.COINCIDENT_WALLS},
                                           key=lambda r: r.value)),
                              element.label))
                for element in drawn_elements
            ]
        drawn_elements, frame, outliers = _flag_far_outliers(drawn_elements)
        for element in drawn_elements:
            census_builder.draw(element)

        census = census_builder.build()
        building.absorb(census)
        plans.append(FloorPlan(
            source=PreviewSource.MODEL,
            doc_name=document.doc_name,
            level_name=level.name,
            level_elevation_mm=level.elevation_mm,
            elements=tuple(sorted(drawn_elements, key=_sort_key)),
            census=census,
            datums=tuple(sorted(datums, key=_sort_key)),
            frame_mm=frame,
            outliers=outliers,
            notes=_notes_for(census, PreviewSource.MODEL,
                             document.project_info.name or ""),
        ))

    return BuildingPreview(
        source=PreviewSource.MODEL,
        doc_name=document.doc_name,
        revit_version=document.revit_version,
        change_stamp=document.change_stamp,
        plans=tuple(plans),
        census=building.build(),
        levels_total=len(document.levels),
    )


def _l0_sort_key(element: Any) -> tuple[str, int, str]:
    ident = element.element_id
    return (element.category, int(ident) if ident.isdigit() else -1, ident)


def _wall_identity(geom: _WallGeom) -> tuple[int, ...]:
    """Личность стены для поиска дублей: концы (без порядка) И дуга.

    Одних концов НЕДОСТАТОЧНО: две разные дуги с общей хордой — это две
    разные стены, и без центра с радиусом «дубль» был бы ложным.
    """
    a = (int(round(geom.p0[0])), int(round(geom.p0[1])))
    b = (int(round(geom.p1[0])), int(round(geom.p1[1])))
    ends = (*a, *b) if a <= b else (*b, *a)
    if geom.arc is None:
        return ends + (0, 0, 0)
    try:
        centre = geom.arc["center_mm"]
        return ends + (int(round(float(centre[0]))),
                       int(round(float(centre[1]))),
                       int(round(float(geom.arc["radius_mm"]))))
    except (KeyError, TypeError, ValueError, IndexError):
        return ends + (0, 0, 0)


#: Ниже этого числа нарисованных элементов «облако» не определено, и разговор
#: об улетевшей геометрии беспредметен.
OUTLIER_MIN_POPULATION = 12
#: Во сколько медианных радиусов нужно отойти от медианного центра, чтобы
#: элемент считался улетевшим.  Мера МЕДИАННАЯ, а не перцентильная: первая
#: редакция брала 2-й и 98-й перцентиль и на k2/L16 промахнулась — 44 улетевших
#: из 1654 это 2.66%, то есть сам 98-й перцентиль уже стоял внутри мусора.
#: Медиана держит до 50% загрязнения, перцентиль — ровно столько, сколько
#: угадал автор.
OUTLIER_RADIUS_FACTOR = 8.0
#: Нижний предел допуска (мм) — чтобы у крошечной модели поле не схлопнулось.
OUTLIER_MIN_PAD_MM = 5_000.0
#: Если «улетевшими» оказалась больше четверти популяции — это не выбросы, а
#: два облака, и правило про них молчит.  Лучше не сказать ничего, чем назвать
#: половину здания мусором.
OUTLIER_MAX_SHARE = 0.25


def _median(values: Sequence[float]) -> float:
    """Медиана по СОРТИРОВАННОЙ копии, без интерполяции на чётной длине:
    берётся верхний из двух средних.  Правило зафиксировано, чтобы байты
    артефакта не зависели от версии statistics."""
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


def _flag_far_outliers(
    elements: Sequence[DrawnElement],
) -> tuple[list[DrawnElement], tuple[float, float, float, float] | None, int]:
    """Отметить «улетевшую» геометрию и вернуть кадр по ЯДРУ облака.

    Замер 03.08 на k2/L16: 44 ``OST_TelephoneDevices`` стоят в 200 м к востоку
    от 26-метровой башни.  Без этого правила масштаб падал с 32 до 146 мм/px и
    здание занимало 12% листа — 1 610 правильных элементов пропадали из виду
    из-за 44 неправильных.  Это НЕ косметика: молчаливая потеря читаемости —
    ровно тот отказ показать, против которого написан закон №4.  Улетевшие
    элементы по-прежнему РИСУЮТСЯ (полем, а не выбрасыванием) и НАЗЫВАЮТСЯ.
    """
    boxes = [(element, element.extent()) for element in elements]
    boxes = [(element, box) for element, box in boxes if box is not None]
    if len(boxes) < OUTLIER_MIN_POPULATION:
        if not boxes:
            return list(elements), None, 0
        return (list(elements),
                (min(b[1][0] for b in boxes), min(b[1][1] for b in boxes),
                 max(b[1][2] for b in boxes), max(b[1][3] for b in boxes)), 0)

    centres = [((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)
               for _, box in boxes]
    mx = _median([centre[0] for centre in centres])
    my = _median([centre[1] for centre in centres])
    radii = [max(abs(cx - mx), abs(cy - my)) for cx, cy in centres]
    threshold = max(_median(radii) * OUTLIER_RADIUS_FACTOR, OUTLIER_MIN_PAD_MM)
    suspects = sum(1 for radius in radii if radius > threshold)
    if suspects > len(boxes) * OUTLIER_MAX_SHARE:
        return (list(elements),
                (min(b[1][0] for b in boxes), min(b[1][1] for b in boxes),
                 max(b[1][2] for b in boxes), max(b[1][3] for b in boxes)), 0)

    kept: list[tuple[float, float, float, float]] = []
    out: list[DrawnElement] = []
    outliers = 0
    for (element, box), radius in zip(boxes, radii):
        if radius <= threshold:
            kept.append(box)
            out.append(element)
        else:
            outliers += 1
            out.append(DrawnElement(
                element.element_id, element.category, element.layer,
                element.shapes, element.approx,
                tuple(sorted(set(element.anomalies) |
                             {AnomalyReason.FAR_OUTLIER},
                             key=lambda reason: reason.value)),
                element.label))
    known = {id(element) for element, _ in boxes}
    out.extend(element for element in elements if id(element) not in known)
    if not kept:
        kept = [box for _, box in boxes]
    frame = (min(b[0] for b in kept), min(b[1] for b in kept),
             max(b[2] for b in kept), max(b[3] for b in kept))
    return out, frame, outliers


def _route_level(element: Any, level_by_id: Mapping[str, Any]
                 ) -> tuple[str | None, str]:
    """Уровень элемента и то, ОТКУДА он взят.

    ``level_id`` пуст у лестниц по известной причине (экстрактор читает
    ``Element.Level``, а лестница держит ``STAIRS_BASE_LEVEL_PARAM``), поэтому
    падение на параметр — не догадка, а второе объявленное чтение.  Оно
    ОТМЕЧАЕТСЯ как приближение, а не выдаётся за прямое знание.
    """
    if element.level_id and element.level_id in level_by_id:
        return element.level_id, "level_id"
    params = element.params or {}
    for key in _LEVEL_PARAM_FALLBACKS:
        value = params.get(key)
        if isinstance(value, str) and value in level_by_id:
            return value, key
    return None, ""


def _wall_geom(element: Any, curve_index: Mapping[str, Any] | None
               ) -> _WallGeom | None:
    thickness = element.params.get("WALL_ATTR_WIDTH_PARAM") if element.params else None
    if isinstance(thickness, bool) or not isinstance(thickness, (int, float)):
        thickness = None
    elif thickness <= 0:
        thickness = None
    arc = None
    if curve_index:
        row = curve_index.get(element.element_id)
        if isinstance(row, Mapping) and row.get("curve_kind") == "arc":
            candidate = row.get("arc")
            if isinstance(candidate, Mapping):
                arc = dict(candidate)
    if element.geom_kind.value != "curve" or element.p0_mm is None or element.p1_mm is None:
        return None
    return _WallGeom(
        p0=(float(element.p0_mm[0]), float(element.p0_mm[1])),
        p1=(float(element.p1_mm[0]), float(element.p1_mm[1])),
        thickness_mm=float(thickness) if thickness is not None else None,
        arc=arc)


def _wall_centerline(geom: _WallGeom) -> tuple[tuple[Pt, ...], bool]:
    if geom.arc is not None:
        try:
            pts = _sample_arc(geom.arc["center_mm"], float(geom.arc["radius_mm"]),
                              geom.arc["x_axis"], geom.arc["y_axis"],
                              float(geom.arc["start_angle_rad"]),
                              float(geom.arc["end_angle_rad"]))
            return pts, True
        except (KeyError, TypeError, ValueError):
            pass
    return (geom.p0, geom.p1), False


def _offset_polyline(pts: Sequence[Pt], half: float) -> tuple[Pt, ...]:
    out: list[Pt] = []
    for index, point in enumerate(pts):
        if index == 0:
            other = pts[1]
            direction = _unit(other[0] - point[0], other[1] - point[1])
        elif index == len(pts) - 1:
            other = pts[index - 1]
            direction = _unit(point[0] - other[0], point[1] - other[1])
        else:
            before, after = pts[index - 1], pts[index + 1]
            direction = _unit(after[0] - before[0], after[1] - before[1])
        if direction is None:
            direction = (1.0, 0.0)
        out.append((point[0] - direction[1] * half, point[1] + direction[0] * half))
    return tuple(out)


def _model_shape(
    element: Any, *, walls: Mapping[str, _WallGeom],
    rooms_by_id: Mapping[str, Any],
    curve_index: Mapping[str, Any] | None,
    sketch_index: Mapping[str, Any] | None,
    via_param: bool,
) -> tuple[DrawnElement | None, OmitReason | None]:
    category = element.category
    rule = _CATEGORY_RULES.get(category)
    base_approx: tuple[ApproxReason, ...] = (
        (ApproxReason.LEVEL_VIA_PARAMETER,) if via_param else ())

    if rule is None:
        return None, OmitReason.CATEGORY_NOT_DRAWN
    if rule is _Rule.ANNOTATION:
        return None, OmitReason.ANNOTATION_NOT_MODEL
    if rule is _Rule.NOT_IN_PLAN:
        return None, OmitReason.NOT_VISIBLE_IN_PLAN
    if rule is _Rule.DERIVED:
        return None, OmitReason.DERIVED_GEOMETRY

    ident = element.element_id

    if rule is _Rule.WALL:
        # Сплайн-стену НЕЛЬЗЯ спрямить хордой: ровно эта молчаливая замена
        # проходила VERIFY как exact (находка M2 аудита 28.07), потому что
        # сравниваются только концы.  Отказ, а не приближение.
        if element.curve_kind is not None and element.curve_kind.value == "other":
            return None, OmitReason.UNSUPPORTED_CURVE
        geom = walls.get(ident)
        if geom is None:
            if element.geom_kind.value == "curve":
                return None, OmitReason.UNSUPPORTED_CURVE
            return None, OmitReason.NO_GEOMETRY
        if math.dist(geom.p0, geom.p1) < MIN_EDGE_MM and geom.arc is None:
            return None, OmitReason.DEGENERATE
        centerline, sampled = _wall_centerline(geom)
        approx = list(base_approx)
        if sampled:
            approx.append(ApproxReason.ARC_SAMPLED)
        if geom.thickness_mm is None:
            approx.append(ApproxReason.THICKNESS_UNKNOWN)
            shapes: tuple[Shape, ...] = (Path(centerline, role="spine"),)
        else:
            half = geom.thickness_mm / 2.0
            left = _offset_polyline(centerline, half)
            right = _offset_polyline(centerline, -half)
            shapes = (Poly((left + tuple(reversed(right)),), role="solid"),)
        return DrawnElement(ident, category, Layer.WALL, shapes,
                            approx=tuple(approx)), None

    if rule is _Rule.OPENING:
        host_id = element.host_id
        if not host_id:
            return None, OmitReason.HOST_UNKNOWN
        geom = walls.get(host_id)
        if geom is None:
            return None, OmitReason.HOST_NOT_DRAWABLE
        if element.p0_mm is None:
            return None, OmitReason.NO_GEOMETRY
        at = (float(element.p0_mm[0]), float(element.p0_mm[1]))
        direction = _unit(geom.p1[0] - geom.p0[0], geom.p1[1] - geom.p0[1])
        if direction is None:
            return None, OmitReason.HOST_NOT_DRAWABLE
        length = math.dist(geom.p0, geom.p1)
        t = ((at[0] - geom.p0[0]) * direction[0]
             + (at[1] - geom.p0[1]) * direction[1])
        width = element.params.get("FAMILY_WIDTH_PARAM") if element.params else None
        approx = list(base_approx)
        if (isinstance(width, bool) or not isinstance(width, (int, float))
                or width < MIN_EDGE_MM):
            width = 900.0
            approx.append(ApproxReason.OPENING_WIDTH_UNKNOWN)
        width = float(width)
        thickness = geom.thickness_mm if geom.thickness_mm else 200.0
        if geom.thickness_mm is None:
            approx.append(ApproxReason.THICKNESS_UNKNOWN)
        anomalies: list[AnomalyReason] = []
        if t + width / 2.0 < -OPENING_ON_HOST_TOL_MM or \
                t - width / 2.0 > length + OPENING_ON_HOST_TOL_MM:
            anomalies.append(AnomalyReason.OPENING_OUTSIDE_HOST)
        if width > length + OPENING_ON_HOST_TOL_MM:
            anomalies.append(AnomalyReason.OPENING_WIDER_THAN_HOST)

        normal = (-direction[1], direction[0])
        half_w, half_t = width / 2.0, thickness / 2.0

        def at_offset(along: float, across: float) -> Pt:
            return (geom.p0[0] + direction[0] * along + normal[0] * across,
                    geom.p0[1] + direction[1] * along + normal[1] * across)

        a0, a1 = t - half_w, t + half_w
        void = (at_offset(a0, -half_t), at_offset(a1, -half_t),
                at_offset(a1, half_t), at_offset(a0, half_t))
        shapes = [Poly((void,), role="void")]
        shapes.append(Path((at_offset(a0, -half_t), at_offset(a0, half_t)),
                           role="tick"))
        shapes.append(Path((at_offset(a1, -half_t), at_offset(a1, half_t)),
                           role="tick"))
        if category == "OST_Doors":
            approx.append(ApproxReason.DOOR_SWING_UNKNOWN)
            shapes.append(Path((at_offset(a0, 0.0), at_offset(a0, width)),
                               role="thin"))
            shapes.append(Path(_arc_through(at_offset(a0, width),
                                            at_offset(t - half_w * 0.293,
                                                      width * 0.707),
                                            at_offset(a1, 0.0)), role="thin"))
        else:
            shapes.append(Path((at_offset(a0, -half_t * 0.35),
                                at_offset(a1, -half_t * 0.35)), role="thin"))
            shapes.append(Path((at_offset(a0, half_t * 0.35),
                                at_offset(a1, half_t * 0.35)), role="thin"))
        return DrawnElement(ident, category, Layer.OPENING, tuple(shapes),
                            approx=tuple(approx),
                            anomalies=tuple(anomalies)), None

    if rule is _Rule.ROOM:
        room = rooms_by_id.get(ident)
        if room is None:
            return None, OmitReason.NO_GEOMETRY
        loops = [tuple(_pt(point) for point in loop)
                 for loop in room.boundary_loops_mm if len(loop) >= 3]
        if not loops:
            return None, OmitReason.DEGENERATE
        anomalies = ([AnomalyReason.ROOM_NOT_ENCLOSED]
                     if room.area_m2 <= 0.0 else [])
        label = room.name or ""
        area_text = f"{room.area_m2:.1f} м²"
        cx = sum(x for x, _ in loops[0]) / len(loops[0])
        cy = sum(y for _, y in loops[0]) / len(loops[0])
        min_area = _ring_area(loops[0])
        shapes = [Poly(tuple(loops), role="solid")]
        if label:
            shapes.append(TextMark((cx, cy), label, role="label",
                                   min_area_mm2=min_area))
        shapes.append(TextMark((cx, cy), area_text, role="tiny",
                               min_area_mm2=min_area))
        return DrawnElement(ident, category, Layer.ROOM, tuple(shapes),
                            approx=base_approx,
                            anomalies=tuple(anomalies), label=label), None

    if rule is _Rule.SLAB:
        profile = None
        if sketch_index:
            profile = sketch_index.get(ident)
        if not isinstance(profile, Mapping) or not profile.get("profile_available"):
            if element.bbox_min_mm is None:
                return None, OmitReason.NO_GEOMETRY
            return None, OmitReason.ONLY_BBOX
        loops = _sketch_loops(profile)
        if not loops:
            return None, OmitReason.DEGENERATE
        approx = list(base_approx)
        if any(kind == "arc" for kinds in profile.get("curve_kinds") or ()
               for kind in (kinds if isinstance(kinds, list) else [kinds])):
            approx.append(ApproxReason.ARC_SAMPLED)
        return DrawnElement(ident, category, Layer.SLAB,
                            (Poly(tuple(loops), role="outline"),),
                            approx=tuple(approx)), None

    if rule is _Rule.COLUMN:
        if element.bbox_min_mm is None or element.bbox_max_mm is None:
            if element.p0_mm is None:
                return None, OmitReason.NO_GEOMETRY
            xy = (float(element.p0_mm[0]), float(element.p0_mm[1]))
            return DrawnElement(ident, category, Layer.COLUMN,
                                (Dot(xy, r_mm=120.0),),
                                approx=base_approx), None
        rect = _bbox_rect(element.bbox_min_mm, element.bbox_max_mm)
        if _ring_area(rect) < 1.0:
            return None, OmitReason.DEGENERATE
        return DrawnElement(ident, category, Layer.COLUMN,
                            (Poly((rect,), role="solid"),),
                            approx=base_approx + (
                                ApproxReason.FOOTPRINT_FROM_BBOX,)), None

    if rule is _Rule.STAIR:
        runs = None
        if sketch_index is not None:
            runs = (sketch_index.get("__runs__") or {}).get(ident)
        shapes = []
        if isinstance(runs, Mapping):
            for run_id in sorted(runs):
                run = runs[run_id]
                pts = run.get("points_mm") if isinstance(run, Mapping) else None
                if isinstance(pts, list) and len(pts) >= 2:
                    shapes.append(Path(tuple(_pt(p) for p in pts), role="line"))
        if shapes:
            return DrawnElement(ident, category, Layer.STAIR, tuple(shapes),
                                approx=base_approx), None
        if element.bbox_min_mm is None or element.bbox_max_mm is None:
            return None, OmitReason.NO_GEOMETRY
        rect = _bbox_rect(element.bbox_min_mm, element.bbox_max_mm)
        if _ring_area(rect) < 1.0:
            return None, OmitReason.DEGENERATE
        return DrawnElement(ident, category, Layer.STAIR,
                            (Poly((rect,), role="outline"),),
                            approx=base_approx + (
                                ApproxReason.FOOTPRINT_FROM_BBOX,)), None

    if rule in (_Rule.CURVE_MEMBER, _Rule.MEP_LINE, _Rule.THIN_LINE):
        if element.curve_kind is not None and element.curve_kind.value == "other":
            return None, OmitReason.UNSUPPORTED_CURVE
        if element.geom_kind.value == "curve" and element.p0_mm and element.p1_mm:
            p0 = (float(element.p0_mm[0]), float(element.p0_mm[1]))
            p1 = (float(element.p1_mm[0]), float(element.p1_mm[1]))
            if math.dist(p0, p1) < MIN_EDGE_MM:
                return None, OmitReason.DEGENERATE
            approx = list(base_approx)
            pts: tuple[Pt, ...] = (p0, p1)
            if curve_index:
                row = curve_index.get(ident)
                if isinstance(row, Mapping) and row.get("curve_kind") == "arc" \
                        and isinstance(row.get("arc"), Mapping):
                    arc = row["arc"]
                    try:
                        pts = _sample_arc(arc["center_mm"],
                                          float(arc["radius_mm"]),
                                          arc["x_axis"], arc["y_axis"],
                                          float(arc["start_angle_rad"]),
                                          float(arc["end_angle_rad"]))
                        approx.append(ApproxReason.ARC_SAMPLED)
                    except (KeyError, TypeError, ValueError):
                        pts = (p0, p1)
                elif isinstance(row, Mapping) and row.get("curve_kind") == "other":
                    return None, OmitReason.UNSUPPORTED_CURVE
            role = "thin" if rule is not _Rule.THIN_LINE else "dashed"
            return DrawnElement(ident, category, _RULE_LAYER[rule],
                                (Path(pts, role=role),),
                                approx=tuple(approx)), None
        if element.bbox_min_mm is not None and element.bbox_max_mm is not None:
            rect = _bbox_rect(element.bbox_min_mm, element.bbox_max_mm)
            if _ring_area(rect) < 1.0:
                return None, OmitReason.DEGENERATE
            return DrawnElement(ident, category, _RULE_LAYER[rule],
                                (Poly((rect,), role="outline"),),
                                approx=base_approx + (
                                    ApproxReason.FOOTPRINT_FROM_BBOX,)), None
        return None, OmitReason.NO_GEOMETRY

    if rule is _Rule.FIXTURE:
        if element.bbox_min_mm is not None and element.bbox_max_mm is not None:
            rect = _bbox_rect(element.bbox_min_mm, element.bbox_max_mm)
            if _ring_area(rect) < 1.0:
                if element.p0_mm is None:
                    return None, OmitReason.DEGENERATE
                xy = (float(element.p0_mm[0]), float(element.p0_mm[1]))
                return DrawnElement(ident, category, Layer.FIXTURE,
                                    (Dot(xy, r_mm=80.0),),
                                    approx=base_approx), None
            return DrawnElement(ident, category, Layer.FIXTURE,
                                (Poly((rect,), role="outline"),),
                                approx=base_approx + (
                                    ApproxReason.FOOTPRINT_FROM_BBOX,)), None
        if element.p0_mm is not None:
            xy = (float(element.p0_mm[0]), float(element.p0_mm[1]))
            return DrawnElement(ident, category, Layer.FIXTURE,
                                (Dot(xy, r_mm=80.0),),
                                approx=base_approx), None
        return None, OmitReason.NO_GEOMETRY

    return None, OmitReason.CATEGORY_NOT_DRAWN


def _sketch_loops(profile: Mapping[str, Any]) -> list[tuple[Pt, ...]]:
    loops: list[tuple[Pt, ...]] = []
    exterior = profile.get("exterior_loop")
    kinds = profile.get("curve_kinds") or []
    mids = profile.get("arc_midpoints") or []
    if isinstance(exterior, list) and len(exterior) >= 3:
        loops.append(_loop_with_arcs(
            exterior,
            kinds[0] if kinds and isinstance(kinds[0], list) else None,
            mids[0] if mids and isinstance(mids[0], list) else None))
    holes = profile.get("holes")
    if isinstance(holes, list):
        for index, hole in enumerate(holes):
            if isinstance(hole, list) and len(hole) >= 3:
                kind = kinds[index + 1] if len(kinds) > index + 1 else None
                mid = mids[index + 1] if len(mids) > index + 1 else None
                loops.append(_loop_with_arcs(
                    hole, kind if isinstance(kind, list) else None,
                    mid if isinstance(mid, list) else None))
    return [loop for loop in loops if len(loop) >= 3]


def _loop_with_arcs(points: Sequence[Any], kinds: Sequence[Any] | None,
                    mids: Sequence[Any] | None) -> tuple[Pt, ...]:
    verts = [_pt(point) for point in points]
    if not kinds or not mids or len(kinds) != len(verts):
        return tuple(verts)
    out: list[Pt] = []
    count = len(verts)
    for index in range(count):
        start = verts[index]
        end = verts[(index + 1) % count]
        out.append(start)
        if kinds[index] == "arc" and index < len(mids) and mids[index]:
            try:
                mid = _pt(mids[index])
            except (PreviewError, TypeError, IndexError):
                continue
            arc = _arc_through(start, mid, end)
            out.extend(arc[1:-1])
    return tuple(out)


# ---------------------------------------------------------------------------
# 9. Удобная обёртка над слепком на диске
# ---------------------------------------------------------------------------

def preview_snapshot(snapshot_dir: str | _FsPath, *,
                     levels: Sequence[str] | None = None) -> BuildingPreview:
    """Прочитать слепок ``backend/data/decompile/<stamp>/`` и построить превью.

    Поток ``L0.jsonl`` читается РОВНО ОДИН РАЗ: файлы этого корпуса доходят до
    88 МБ, и материализация документа целиком стоила бы гигабайтов.
    """
    from kukai.ir.decompile.extract import L0JSONLReader
    from kukai.ir.decompile.snapshot_io import (read_snapshot_text,
                                                snapshot_file_exists)

    directory = _FsPath(snapshot_dir)
    reader = L0JSONLReader(directory / "L0.jsonl")
    document = reader.metadata()

    curve_index: dict[str, Any] = {}
    if snapshot_file_exists(directory / "curve.index.json"):
        raw = json.loads(read_snapshot_text(directory / "curve.index.json"))
        curve_index = raw.get("curve_index") or {}

    sketch_index: dict[str, Any] = {}
    if snapshot_file_exists(directory / "sketch.index.json"):
        raw = json.loads(read_snapshot_text(directory / "sketch.index.json"))
        sketch_index = dict(raw.get("profile_index") or {})
        sketch_index["__runs__"] = raw.get("stairs_run_path_index") or {}

    return build_model_preview(document, reader.iter_elements(), levels=levels,
                               curve_index=curve_index,
                               sketch_index=sketch_index)


# ---------------------------------------------------------------------------
# 10. РИСОВАЛЬЩИК — единственный на оба источника
# ---------------------------------------------------------------------------

SHEET_W = 1680
SHEET_H = 1400
HEADER_H = 104
DRAW_X = 40
DRAW_Y = HEADER_H + 24
DRAW_W = SHEET_W - 2 * DRAW_X
DRAW_H = 960
FOOTER_Y = DRAW_Y + DRAW_H + 24


_STYLE: dict[Layer, dict[str, Any]] = {
    Layer.ROOM: {"fill": "#e8eef5", "stroke": "#b6c4d4", "width": 0.8},
    Layer.SLAB: {"fill": "none", "stroke": "#9aa7b4", "width": 1.0,
                 "dash": "8 5"},
    Layer.FIXTURE: {"fill": "none", "stroke": "#b9c2cc", "width": 0.7},
    Layer.MEP: {"fill": "none", "stroke": "#7fa8c9", "width": 1.0},
    Layer.LINE: {"fill": "none", "stroke": "#8f9aa6", "width": 1.0},
    Layer.SEPARATION: {"fill": "none", "stroke": "#a8b4c0", "width": 0.9,
                       "dash": "5 4"},
    Layer.GRID: {"fill": "none", "stroke": "#c2a15a", "width": 0.9,
                 "dash": "18 5 3 5"},
    Layer.STAIR: {"fill": "none", "stroke": "#6d7c8b", "width": 1.4},
    Layer.WALL: {"fill": "#2b3440", "stroke": "#2b3440", "width": 0.6},
    Layer.OPENING: {"fill": "#ffffff", "stroke": "#2b3440", "width": 1.0},
    Layer.COLUMN: {"fill": "#4a5563", "stroke": "#2b3440", "width": 0.6},
    Layer.LABEL: {"fill": "none", "stroke": "#2b3440", "width": 0.8},
}

_SOURCE_STYLE: dict[PreviewSource, dict[str, str]] = {
    PreviewSource.PROGRAM: {
        "accent": "#b26a00",
        "band": "#fff3e0",
        "border_dash": "12 6",
        "title": "ПРЕВЬЮ ПРОГРАММЫ · САМОПРОВЕРКА",
        "claim": "рисуется ЗАЯВЛЕННОЕ автором. Модель НЕ читалась, "
                 "ни один селектор не разрешён.",
        "watermark": "ЗАЯВЛЕНО",
    },
    PreviewSource.MODEL: {
        "accent": "#1d5b8f",
        "band": "#e7f0f8",
        "border_dash": "",
        "title": "ПРЕВЬЮ РАЗБОРА · НЕЗАВИСИМОЕ ЧТЕНИЕ",
        "claim": "рисуется то, что ЕСТЬ в документе (L0), а не то, "
                 "что кто-то собирался построить.",
        "watermark": "",
    },
}

_APPROX_TEXT: dict[ApproxReason, str] = {
    ApproxReason.FOOTPRINT_FROM_BBOX:
        "след взят из ГАБАРИТА (AABB), а не из профиля",
    ApproxReason.THICKNESS_UNKNOWN:
        "толщина неизвестна — нарисована ОСЬ, не тело",
    ApproxReason.OPENING_WIDTH_UNKNOWN:
        "ширина проёма неизвестна — засечка/условные 900 мм",
    ApproxReason.DOOR_SWING_UNKNOWN:
        "сторона открывания двери в источнике отсутствует — показана условно",
    ApproxReason.ARC_SAMPLED: "дуга представлена выборкой точек",
    ApproxReason.ROOM_BOUNDARY_NOT_COMPUTED:
        "границу помещения считает Revit — в программе это точка",
    ApproxReason.LEVEL_VIA_PARAMETER:
        "этаж восстановлен по параметру (level_id пуст)",
}

_OMIT_TEXT: dict[OmitReason, str] = {
    OmitReason.NO_GEOMETRY: "геометрии нет",
    OmitReason.ONLY_BBOX: "есть только габарит, а нужен контур",
    OmitReason.DEGENERATE: "вырожденная геометрия",
    OmitReason.NON_FINITE: "неконечные координаты",
    OmitReason.UNSUPPORTED_CURVE: "кривая не прямая и не дуга",
    OmitReason.CATEGORY_NOT_DRAWN: "категория не поддержана",
    OmitReason.ANNOTATION_NOT_MODEL: "аннотация вида, не тело здания",
    OmitReason.NOT_VISIBLE_IN_PLAN: "в плане не виден по построению",
    OmitReason.DERIVED_GEOMETRY: "производная геометрия",
    OmitReason.LEVEL_UNKNOWN: "этаж не определён",
    OmitReason.LEVEL_NOT_IN_RUN: "этаж не рисовали в этом прогоне",
    OmitReason.HOST_UNKNOWN: "хост не назван",
    OmitReason.HOST_NOT_DRAWABLE: "геометрии хоста нет",
    OmitReason.OP_NOT_DRAWN: "у операции нет правила рисования",
    OmitReason.SELECTOR_UNRESOLVED: "селектор уровня не сведён к плану",
    OmitReason.NOT_AN_OP: "не операция KIR: ключа `op` у элемента нет",
}

_ANOMALY_TEXT: dict[AnomalyReason, str] = {
    AnomalyReason.OPENING_OUTSIDE_HOST: "проём за пределами своей стены",
    AnomalyReason.OPENING_WIDER_THAN_HOST: "проём шире стены",
    AnomalyReason.COINCIDENT_WALLS: "стены-дубли (совпадают концы)",
    AnomalyReason.ROOM_NOT_ENCLOSED: "помещение не замкнулось (площадь 0)",
    AnomalyReason.FAR_OUTLIER: "элемент далеко за облаком остальных",
}


#: Сколько строк переписи ВЛЕЗАЕТ в подвал листа. Числа геометрические: подвал
#: высотой (SHEET_H - FOOTER_Y) и строкой в 17 px держит ровно столько. Раньше
#: они стояли безымянными срезами `[:5]`/`[:4]` прямо в разметке, и урезание
#: НЕ НАЗЫВАЛОСЬ — то есть модуль, существующий ради запрета молчания, молчал
#: сам. Теперь остаток печатается строкой «… ещё N», как у пропусков.
_FOOTER_OMIT_ROWS = 7
_FOOTER_APPROX_ROWS = 5
_FOOTER_ANOMALY_ROWS = 4
_FOOTER_BLIND_ROWS = 4


def census_lines(census: PreviewCensus) -> tuple[dict[str, Any], ...]:
    """ПЕРЕПИСЬ ЧЕЛОВЕЧЕСКИМИ СТРОКАМИ — целиком, без срезов.

    Лист печатает столько строк, сколько влезает в подвал, и честно называет
    остаток. Но получателю переписи (панель, решение о переносе, квитанция)
    урезание не нужно вовсе: там нет ни подвала, ни его высоты. Русский текст
    причин живёт ровно в одном месте — в `_OMIT_TEXT`/`_APPROX_TEXT`/
    `_ANOMALY_TEXT`, и второго экземпляра этих формулировок не заводится: они
    разъехались бы с кодами причин на первой же новой причине.
    """
    out: list[dict[str, Any]] = []
    for group in census.omitted:
        out.append({
            "kind": "omitted", "reason": group.reason.value,
            "category": group.category, "count": group.count,
            "examples": list(group.examples),
            "ru": _OMIT_TEXT.get(group.reason, group.reason.value),
        })
    for group in census.approx:
        out.append({
            "kind": "approx", "reason": group.reason.value,
            "category": "", "count": group.count,
            "examples": list(group.examples),
            "ru": _APPROX_TEXT.get(group.reason, group.reason.value),
        })
    for group in census.anomalies:
        out.append({
            "kind": "anomaly", "reason": group.reason.value,
            "category": "", "count": group.count,
            "examples": list(group.examples),
            "ru": _ANOMALY_TEXT.get(group.reason, group.reason.value),
        })
    return tuple(out)


def _fmt(value: float) -> str:
    if not math.isfinite(value):
        raise PreviewError("нельзя напечатать неконечное число")
    text = f"{value:.2f}"
    if text.endswith(".00"):
        text = text[:-3]
    elif text.endswith("0"):
        text = text[:-1]
    return "0" if text in ("-0", "-0.0") else text


def _esc(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _nice_length(max_mm: float) -> float:
    if max_mm <= 0:
        return 1000.0
    exponent = math.floor(math.log10(max_mm))
    for factor in (5.0, 2.0, 1.0):
        candidate = factor * (10.0 ** exponent)
        if candidate <= max_mm:
            return candidate
    return 10.0 ** exponent


def render_svg(plan: FloorPlan) -> str:
    """ОДИН рисовальщик на оба источника.  Тот же вход — тот же байт."""
    style = _SOURCE_STYLE[plan.source]
    extents = plan.extents_mm()
    parts: list[str] = []
    out = parts.append

    out(f'<svg xmlns="http://www.w3.org/2000/svg" width="{SHEET_W}" '
        f'height="{SHEET_H}" viewBox="0 0 {SHEET_W} {SHEET_H}" '
        f'font-family="DejaVu Sans, Helvetica, Arial, sans-serif">')
    out(f'<title>{_esc(plan.doc_name)} — {_esc(plan.level_name)} — '
        f'{_esc(style["title"])}</title>')
    out('<metadata id="kir-preview">'
        + _esc(json.dumps({**plan.to_dict(),
                           "content_digest": plan.content_digest},
                          sort_keys=True, ensure_ascii=False,
                          separators=(",", ":")))
        + '</metadata>')
    out(f'<rect width="{SHEET_W}" height="{SHEET_H}" fill="#ffffff"/>')

    # --- рамка листа: у самопроверки она ШТРИХОВАЯ (закон №6)
    dash = f' stroke-dasharray="{style["border_dash"]}"' if style["border_dash"] else ""
    out(f'<rect x="8" y="8" width="{SHEET_W - 16}" height="{SHEET_H - 16}" '
        f'fill="none" stroke="{style["accent"]}" stroke-width="3"{dash}/>')

    # --- шапка
    out(f'<rect x="8" y="8" width="{SHEET_W - 16}" height="{HEADER_H}" '
        f'fill="{style["band"]}"/>')
    out(f'<text x="28" y="46" font-size="24" font-weight="bold" '
        f'fill="{style["accent"]}">{_esc(style["title"])}</text>')
    out(f'<text x="28" y="72" font-size="15" fill="#2b3440">'
        f'{_esc(plan.doc_name)} · этаж <tspan font-weight="bold">'
        f'{_esc(plan.level_name)}</tspan>'
        + (f' · отм. {_fmt(plan.level_elevation_mm)} мм'
           if plan.level_elevation_mm is not None else '')
        + '</text>')
    out(f'<text x="28" y="94" font-size="12.5" fill="{style["accent"]}">'
        f'{_esc(style["claim"])}</text>')

    census = plan.census
    summary = (f'нарисовано {census.drawn} из {census.considered}'
               if not census.vacuous else 'НЕЧЕГО РИСОВАТЬ (0 элементов)')
    out(f'<text x="{SHEET_W - 28}" y="46" font-size="20" text-anchor="end" '
        f'font-weight="bold" fill="#2b3440">{_esc(summary)}</text>')
    out(f'<text x="{SHEET_W - 28}" y="70" font-size="13" text-anchor="end" '
        f'fill="#5a6673">покрытие {census.coverage_pct:.1f}% · '
        f'приближений {census.approx_total} · '
        f'аномалий {census.anomaly_total}</text>')
    out(f'<text x="{SHEET_W - 28}" y="92" font-size="11" text-anchor="end" '
        f'fill="#8a95a1">digest {plan.content_digest[:16]}</text>')

    # --- поле чертежа
    out(f'<rect x="{DRAW_X}" y="{DRAW_Y}" width="{DRAW_W}" height="{DRAW_H}" '
        f'fill="#fcfcfd" stroke="#dfe4ea" stroke-width="1"/>')

    # Водяной знак идёт ПОД геометрию: он обязан быть виден с первого взгляда
    # и не имеет права загораживать то, ради чего лист открыли.
    if style["watermark"]:
        out(f'<text x="{SHEET_W / 2}" y="{DRAW_Y + DRAW_H / 2}" '
            f'font-size="150" text-anchor="middle" fill="{style["accent"]}" '
            f'opacity="0.09" font-weight="bold" '
            f'transform="rotate(-24 {SHEET_W / 2} {DRAW_Y + DRAW_H / 2})">'
            f'{_esc(style["watermark"])}</text>')

    if extents is None:
        out(f'<text x="{DRAW_X + DRAW_W / 2}" y="{DRAW_Y + DRAW_H / 2}" '
            f'font-size="22" text-anchor="middle" fill="#b0392e">'
            f'ПУСТО: ни одна фигура не построена</text>')
        scale = 0.0
    else:
        min_x, min_y, max_x, max_y = extents
        span_x = max(max_x - min_x, 1.0)
        span_y = max(max_y - min_y, 1.0)
        pad = 26.0
        scale = min((DRAW_W - 2 * pad) / span_x, (DRAW_H - 2 * pad) / span_y)
        off_x = DRAW_X + pad + ((DRAW_W - 2 * pad) - span_x * scale) / 2.0
        off_y = DRAW_Y + pad + ((DRAW_H - 2 * pad) - span_y * scale) / 2.0

        def to_px(point: Pt) -> tuple[float, float]:
            return (off_x + (point[0] - min_x) * scale,
                    off_y + (max_y - point[1]) * scale)

        out(f'<clipPath id="fld"><rect x="{DRAW_X}" y="{DRAW_Y}" '
            f'width="{DRAW_W}" height="{DRAW_H}"/></clipPath>')
        out('<g clip-path="url(#fld)">')

        ordered = sorted(tuple(plan.datums) + tuple(plan.elements),
                         key=_sort_key)
        for element in ordered:
            out(_render_element(element, to_px, scale))
        out('</g>')

        if plan.outliers:
            out(f'<text x="{DRAW_X + DRAW_W - 18}" y="{DRAW_Y + DRAW_H - 16}" '
                f'font-size="12.5" text-anchor="end" fill="#c0392b" '
                f'font-weight="bold">КАДР ПО ЯДРУ: {plan.outliers} '
                f'элемент(ов) улетели за облако и обрезаны полем '
                f'(см. аномалии)</text>')

        out(_scale_bar(scale))

    out(_north_marker())
    out(_footer(plan, style))
    out('</svg>')
    return "\n".join(parts) + "\n"


def _render_element(element: DrawnElement, to_px, scale: float) -> str:
    style = dict(_STYLE[element.layer])
    flagged = bool(element.anomalies)
    if flagged:
        style = {**style, "stroke": "#c0392b", "width": max(
            float(style["width"]), 1.6)}
    chunks: list[str] = []
    attrs = (f' data-el="{_esc(element.element_id)}" '
             f'data-cat="{_esc(element.category)}"')
    if flagged:
        attrs += (' data-anomaly="'
                  + _esc(",".join(r.value for r in element.anomalies)) + '"')
    chunks.append(f'<g{attrs}>')
    for shape in element.shapes:
        if isinstance(shape, Poly):
            path = " ".join(
                "M " + " L ".join(
                    f"{_fmt(px)} {_fmt(py)}"
                    for px, py in (to_px(point) for point in loop)) + " Z"
                for loop in shape.loops if loop)
            if not path:
                continue
            if shape.role == "void":
                fill, stroke = "#fcfcfd", "none"
            elif shape.role == "outline":
                fill, stroke = "none", style["stroke"]
            else:
                fill, stroke = style["fill"], style["stroke"]
            dash = (f' stroke-dasharray="{style["dash"]}"'
                    if style.get("dash") and shape.role != "solid" else "")
            chunks.append(
                f'<path d="{path}" fill="{fill}" fill-rule="evenodd" '
                f'stroke="{stroke}" stroke-width="{style["width"]}"{dash}/>')
        elif isinstance(shape, Path):
            pts = [to_px(point) for point in shape.pts]
            if len(pts) < 2:
                continue
            path = ("M " + " L ".join(f"{_fmt(px)} {_fmt(py)}"
                                      for px, py in pts))
            width = float(style["width"])
            dash = ""
            if shape.role == "thin":
                width = max(0.6, width * 0.7)
            elif shape.role == "spine":
                # Ось вместо тела: линия обязана быть ЗАМЕТНО другой, чтобы
                # «толщина неизвестна» читалась с листа, а не только из
                # переписи.
                width = 2.4
            elif shape.role == "tick":
                width = max(1.2, width)
            elif shape.role == "dashed":
                dash = f' stroke-dasharray="{style.get("dash", "5 4")}"'
            elif shape.role == "axis":
                dash = f' stroke-dasharray="{style.get("dash", "18 5 3 5")}"'
            chunks.append(
                f'<path d="{path}" fill="none" stroke="{style["stroke"]}" '
                f'stroke-width="{_fmt(width)}"{dash}/>')
        elif isinstance(shape, Dot):
            px, py = to_px(shape.xy)
            radius = max(1.6, shape.r_mm * scale)
            chunks.append(
                f'<circle cx="{_fmt(px)}" cy="{_fmt(py)}" r="{_fmt(radius)}" '
                f'fill="{style["stroke"]}" opacity="0.85"/>')
        else:  # TextMark
            px, py = to_px(shape.xy)
            if shape.role == "bubble":
                chunks.append(
                    f'<circle cx="{_fmt(px)}" cy="{_fmt(py)}" r="11" '
                    f'fill="#ffffff" stroke="{style["stroke"]}" '
                    f'stroke-width="1"/>')
                chunks.append(
                    f'<text x="{_fmt(px)}" y="{_fmt(py + 3.6)}" font-size="9.5" '
                    f'text-anchor="middle" fill="#6b5424">'
                    f'{_esc(shape.text[:5])}</text>')
                continue
            # Подпись печатается, только если на листе для неё есть место.
            # Порог детерминированный: площадь контура в пикселях.  Нулевой
            # ``min_area_mm2`` = «места хватает по построению» (точечная
            # подпись программы), а не «места нет».
            if 0.0 < shape.min_area_mm2 * scale * scale < 2600.0:
                continue
            size = 11.0 if shape.role == "label" else 9.0
            dy = -3.0 if shape.role == "label" else 10.0
            colour = "#3c4855" if shape.role == "label" else "#78838f"
            text = shape.text if len(shape.text) <= 22 else shape.text[:21] + "…"
            chunks.append(
                f'<text x="{_fmt(px)}" y="{_fmt(py + dy)}" font-size="{size}" '
                f'text-anchor="middle" fill="{colour}">{_esc(text)}</text>')
    chunks.append('</g>')
    return "".join(chunks)


def _scale_bar(scale: float) -> str:
    if scale <= 0:
        return ""
    bar_mm = _nice_length((DRAW_W * 0.22) / scale)
    bar_px = bar_mm * scale
    x0 = DRAW_X + 18
    y0 = DRAW_Y + DRAW_H - 26
    label = (f"{_fmt(bar_mm / 1000.0)} м" if bar_mm >= 1000
             else f"{_fmt(bar_mm)} мм")
    return (
        f'<g><rect x="{_fmt(x0)}" y="{_fmt(y0)}" width="{_fmt(bar_px / 2)}" '
        f'height="7" fill="#2b3440"/>'
        f'<rect x="{_fmt(x0 + bar_px / 2)}" y="{_fmt(y0)}" '
        f'width="{_fmt(bar_px / 2)}" height="7" fill="#ffffff" '
        f'stroke="#2b3440" stroke-width="1"/>'
        f'<text x="{_fmt(x0)}" y="{_fmt(y0 - 6)}" font-size="11" '
        f'fill="#2b3440">0</text>'
        f'<text x="{_fmt(x0 + bar_px)}" y="{_fmt(y0 - 6)}" font-size="11" '
        f'text-anchor="end" fill="#2b3440">{_esc(label)}</text>'
        f'<text x="{_fmt(x0)}" y="{_fmt(y0 + 20)}" font-size="10.5" '
        f'fill="#78838f">1 px = {_fmt(1.0 / scale)} мм</text></g>')


def _north_marker() -> str:
    """Стрелка ПРОЕКТНОГО севера.

    Истинного севера в L0 нет как поля (проверено по
    ``decompile/schema.py``/``extract.py``: ни ``ProjectPosition``, ни угла),
    поэтому стрелка подписана честно.  Молча нарисовать «N» значило бы выдать
    ориентацию за прочитанную.
    """
    cx = SHEET_W - 96
    cy = DRAW_Y + 74
    return (
        f'<g><circle cx="{cx}" cy="{cy}" r="30" fill="#ffffff" '
        f'stroke="#c9d0d8" stroke-width="1"/>'
        f'<path d="M {cx} {cy - 22} L {cx + 9} {cy + 14} L {cx} {cy + 6} '
        f'L {cx - 9} {cy + 14} Z" fill="#2b3440"/>'
        f'<text x="{cx}" y="{cy + 44}" font-size="11" text-anchor="middle" '
        f'font-weight="bold" fill="#2b3440">ПН (+Y)</text>'
        f'<text x="{cx}" y="{cy + 58}" font-size="9" text-anchor="middle" '
        f'fill="#b0392e">истинный север не задан</text></g>')


def _rest_line(groups: Sequence[Any], shown: int,
               what: str) -> list[tuple[str, str]]:
    """«… ещё N» ОДНИМ правилом на все три колонки переписи.

    Раньше остаток называла только колонка пропусков; приближения, аномалии и
    слепые пятна урезались молча (замер 04.08: 7 групп приближений → 5 строк и
    ни слова, 5 аномалий → 4 строки и ни слова, 6 слепых пятен → 4 и ни слова).
    Одно правило вместо трёх мест — потому что четвёртую колонку кто-нибудь
    добавит, а обойти общий помощник труднее, чем забыть скопировать срез.
    """
    if len(groups) <= shown:
        return []
    rest = sum(g.count for g in groups[shown:])
    return [("", f"{rest:>7}  … ещё {len(groups) - shown} {what}")]


def _footer(plan: FloorPlan, style: Mapping[str, str]) -> str:
    census = plan.census
    lines_left: list[tuple[str, str]] = []
    lines_left.append(("ПЕРЕПИСЬ",
                       f"рассмотрено {census.considered} · "
                       f"нарисовано {census.drawn} · "
                       f"не нарисовано {census.omitted_total}"))
    for group in census.omitted[:_FOOTER_OMIT_ROWS]:
        text = _OMIT_TEXT.get(group.reason, group.reason.value)
        lines_left.append(("", f"{group.count:>7}  {group.category} — {text}"))
    lines_left.extend(_rest_line(census.omitted, _FOOTER_OMIT_ROWS,
                                 "строк(и) причин"))

    lines_right: list[tuple[str, str]] = []
    if census.approx:
        lines_right.append(("НАРИСОВАНО, НО НЕ ТОЧНО", ""))
        for group in census.approx[:_FOOTER_APPROX_ROWS]:
            lines_right.append(
                ("", f"{group.count:>7}  "
                     f"{_APPROX_TEXT.get(group.reason, group.reason.value)}"))
        lines_right.extend(_rest_line(census.approx, _FOOTER_APPROX_ROWS,
                                      "строк(и) приближений"))
    if census.anomalies:
        lines_right.append(("АНОМАЛИИ (нарисованы красным)", ""))
        for group in census.anomalies[:_FOOTER_ANOMALY_ROWS]:
            lines_right.append(
                ("", f"{group.count:>7}  "
                     f"{_ANOMALY_TEXT.get(group.reason, group.reason.value)} "
                     f"[{', '.join(group.examples[:3])}]"))
        lines_right.extend(_rest_line(census.anomalies, _FOOTER_ANOMALY_ROWS,
                                      "строк(и) аномалий"))
    if not lines_right:
        lines_right.append(("НАРИСОВАНО, НО НЕ ТОЧНО", ""))
        lines_right.append(("", "      —  приближений и аномалий не отмечено"))
    lines_right.append(("ЭТОТ ЭКРАН НЕ ПОКАЖЕТ", ""))
    for spot in BLIND_SPOTS[:_FOOTER_BLIND_ROWS]:
        lines_right.append(("", f"      ·  {spot}"))
    if len(BLIND_SPOTS) > _FOOTER_BLIND_ROWS:
        # Список слепоты, урезанный молча, читается как «слепота вот такая» —
        # то есть врёт ровно в ту сторону, в которую этому листу врать нельзя.
        lines_right.append(
            ("", f"      ·  … и ещё {len(BLIND_SPOTS) - _FOOTER_BLIND_ROWS} "
                 f"вид(а) слепоты — см. preview.BLIND_SPOTS"))

    chunks = [f'<rect x="{DRAW_X}" y="{FOOTER_Y}" width="{DRAW_W}" '
              f'height="{SHEET_H - FOOTER_Y - 24}" fill="#f7f8fa" '
              f'stroke="#dfe4ea" stroke-width="1"/>']
    chunks.append(f'<line x1="{SHEET_W / 2}" y1="{FOOTER_Y}" '
                  f'x2="{SHEET_W / 2}" y2="{SHEET_H - 24}" '
                  f'stroke="#dfe4ea" stroke-width="1"/>')

    def column(lines: Sequence[tuple[str, str]], x: float) -> None:
        y = FOOTER_Y + 24
        for head, body in lines:
            if head:
                chunks.append(
                    f'<text x="{_fmt(x)}" y="{_fmt(y)}" font-size="12" '
                    f'font-weight="bold" fill="{style["accent"]}">'
                    f'{_esc(head)}</text>')
                y += 18
            if body:
                chunks.append(
                    f'<text x="{_fmt(x)}" y="{_fmt(y)}" font-size="11.5" '
                    f'fill="#3c4855" xml:space="preserve" '
                    f'font-family="DejaVu Sans Mono, monospace">'
                    f'{_esc(body)}</text>')
                y += 17

    column(lines_left, DRAW_X + 18)
    column(lines_right, SHEET_W / 2 + 18)

    for index, note in enumerate(plan.notes[:2]):
        chunks.append(
            f'<text x="{DRAW_X + 18}" y="{SHEET_H - 34 + index * 14}" '
            f'font-size="10.5" fill="#8a95a1">{_esc(note)}</text>')
    return "".join(chunks)


def _notes_for(census: PreviewCensus, source: PreviewSource,
               subtitle: str) -> tuple[str, ...]:
    notes: list[str] = []
    if subtitle:
        notes.append(subtitle[:120])
    if source is PreviewSource.PROGRAM:
        notes.append("самопроверка: несовпадение с моделью этим листом "
                     "не обнаруживается")
    else:
        notes.append(f"источник: L0 (независимое чтение), "
                     f"приближений {census.approx_total}")
    return tuple(notes)
