"""Frozen Wave-0 schema for the streamed DECOMPILE L0 representation.

Every coordinate is millimetres and every Revit identifier is serialized as a
string.  The dataclasses are immutable so later stages cannot accidentally
rewrite extraction truth in place.
"""
from __future__ import annotations

import hashlib
import math
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence


# ── CONSTANTS — KIR_DECOMPILE_SPEC Part 11 ──────────────────────────────────

CANON_MM = 1.0
DZ_TOL = 50.0
SIM_THRESHOLD = 0.90
GRID_COVERAGE = 0.8
GRID_REL_TOL = 0.02
MIN_ROW = 3
MIN_ARRAY = 4
COLLINEAR_TOL = 5.0
VERIFY_TOL = 10.0
# Размер страницы извлечения. Страница исполняется ОДНИМ вызовом на UI-потоке
# Revit и обязана укладываться в EXTRACT_TIMEOUT_MS с запасом: отменённый
# сервером вызов Revit всё равно ДОДЕЛЫВАЕТ, ретрай встаёт в занятое окно,
# пинг моста голодает и сокет умирает 1006. Замер 29.07 (13A-RD-AR-K2, РД,
# 15 341 стена): страницы по 2000 убивали мост на 6-й странице стен (v2) и
# на первой странице дверей (v1) — точка смерти плавает, что и выдаёт
# накопительное голодание, а не «ядовитую» страницу. Переопределение —
# ТОЛЬКО через окружение, признак структурный (размер), не модельный.
_EXTRACT_BATCH_DEFAULT = 2_000
EXTRACT_BATCH = max(50, int(
    os.environ.get("KUKAI_IR_EXTRACT_BATCH", _EXTRACT_BATCH_DEFAULT)))
ATOM_CELL_MM = 5_000.0
ATOM_CLUSTER_MIN = 5
ATOM_LEAF_CAP = 20
ZONE_CELL_MM = 8_000.0
PASSPORT_INJECT_TOKENS = 800
USE_LLM_LABELS = False
GEOM_DETAIL = "Fine"
GEOM_CANON_MM = 0.5
GEOM_TOL = 1.0
GEOM_VOLUME_REL_TOL = 0.001

EXTRACT_TIMEOUT_MS = 30_000
EXTRACT_RETRIES = 2
# ОЖИДАНИЕ ВОЗВРАЩЕНИЯ ОКНА (задача #26). Бюджет ретраев страницы
# (EXTRACT_RETRY_BACKOFF_S) терпит ~25 с — этого хватает на дрожание сети, но
# не на реальный обрыв: окно возвращается с новым ws_id через СЕКУНДЫ-МИНУТЫ.
# При исчерпании ретраев цикл извлечения ждёт окно и повторяет страницу.
#
# БЮДЖЕТ ОБЩИЙ НА ПРОГОН, А НЕ НА СТРАНИЦУ — и это главное решение здесь.
# Попостраничный потолок множился бы на число страниц: если окно закрыто
# насовсем (оператор вышел из Revit), 54 категории по 5 минут дали бы
# четыре с половиной часа мнимой работы. Общий бюджет тратится один раз:
# переживаем один длинный обрыв ИЛИ несколько коротких, а мёртвое окно
# стоит пять минут ровно один раз, после чего остаток прогона отказывает
# быстро и честно.
#
# ПОЧЕМУ 300 с. Цена ошибки несимметрична: ждать пять минут дёшево, а не
# дождаться — значит выбросить извлечение целой модели (замер 29.07, К2 РД:
# три прогона умерли на плавающей странице, каждый пришлось начинать заново
# полностью). Переподключение складывается из реконнекта сети, реконнекта
# клиента и UI-потока Revit, который ещё доделывает отменённый вызов, — три
# минуты для такой суммы тесноваты.
EXTRACT_WINDOW_WAIT_S = max(0.0, float(
    os.environ.get("KUKAI_IR_EXTRACT_WINDOW_WAIT_S", 300.0)))
# Пауза между попытками достучаться до вернувшегося окна. Проба — сам вызов
# страницы: успех И ЕСТЬ доказательство, что окно вернулось. Отдельный
# «пинг живости» был бы вторым путём с собственным режимом отказа и мог бы
# соврать «окно есть» там, где страница всё равно не проходит.
EXTRACT_WINDOW_POLL_S = 10.0
L0_SCHEMA_VERSION = "1.0"
L0_UNITS = "mm"


class L0SchemaError(ValueError):
    """A persisted or bridge-supplied L0 record violates the frozen schema."""


# ── ДИАЛЕКТ L0: ПОКОЛЕНИЕ ТАБЛИЦЫ ЧТЕНИЯ ────────────────────────────────────
#
# ЧТО ВХОДИТ В ВЕРСИЮ ДИАЛЕКТА — И ПОЧЕМУ ИМЕННО ЭТО.
#
# Версия диалекта называет РОВНО ОДНО: поколение упорядоченной таблицы
# категорий, которую извлечение обязано обойти (``EXTRACT_CATEGORIES``).
# Больше — ничего. Обоснование не эстетическое, а структурное: это
# единственная часть L0, чей смысл ПОЗИЦИОННЫЙ И ТОТАЛЬНЫЙ. Контейнер
# объявляет «по одному ``category_status`` на каждую строку таблицы, строго в
# её порядке, футер последним и только после ВСЕХ строк». Значит рост таблицы
# меняет само определение полного потока — а полнота и есть то, ради чего
# читателю нужна версия.
#
# ЧТО В ВЕРСИЮ НЕ ВХОДИТ, хотя напрашивалось:
#
# * НАБОР ПОЛЕЙ ЗАПИСИ. У дома уже есть работающее правило: поле дописывается
#   В ХВОСТ со значением по умолчанию, а его отсутствие значит «не мерили», а
#   не «ноль». Так вошли ``curve_kind``, ``section_receipts``, ``census``,
#   ``worksharing``/``worksets`` — и именно поэтому поток от 18.07 сегодня
#   разбирается запись в запись. Правило локально для записи и НЕ трогает
#   полноту потока, поэтому версии не требует. Тот же docstring у
#   :class:`LocationCurveKind` и у ``CategoryStatus.section_receipts``.
# * ИНВАРИАНТЫ ГЕОМЕТРИИ. 29.07 (cb9c3b65) снято требование «точка обязана
#   нести поворот» — это ОСЛАБЛЕНИЕ, а ослабление не может обесценить старые
#   байты: всё, что разбиралось вчера, разбирается и сегодня. Обесценить
#   способно только УЖЕСТОЧЕНИЕ, и оно обязано отказывать поимённо в
#   :class:`L0SchemaError` с именем поля, а не прятаться за номером версии.
#   Версия, которую двигает каждое такое изменение, бесполезна ровно так же,
#   как отсутствующая.
#
# ПРОВЕРКА ЧАСТОТОЙ (замер 29.07, одиннадцать дней истории). По этому правилу
# версия сдвинулась бы ШЕСТЬ раз — ровно на шести ростах таблицы — и НЕ
# сдвинулась бы ни разу на пяти изменениях, которые её не касаются
# (curve_kind, квитанции сечений, перепись §18.1, рабочие наборы §18.4,
# ослабление поворота). Это и есть искомое соотношение.
#
# ПОЧЕМУ ЭТО НЕ ``L0_SCHEMA_VERSION``. Тот называет схему ЗАПИСИ и честно
# стоит на "1.0": ни одна форма записи несовместимо не менялась. Сдвинуть его
# ради роста таблицы значило бы объявить сломанным то, что не ломалось, и
# заодно отказать в чтении всем 55 накопленным слепкам. Это две РАЗНЫЕ оси, и
# у каждой своя версия.
#
# ЗАКОН ДОПИСИ В ХВОСТ. Все шесть поколений — строгие префиксы друг друга;
# сверено по трём независимым источникам (история git по extract.py; байты 55
# слепков в ``backend/data/decompile``; отпечатки sha256 обоих). Пока закон
# держится, поколение однозначно задаётся ОДНИМ числом — длиной таблицы.
# Отпечаток ниже — не украшение, а страж: он взят из ИСТОРИИ, а не посчитан
# от сегодняшней таблицы, поэтому ``verify_dialect_ladder`` закричит, если
# кто-то вставит строку в середину или переименует её. Без отпечатка «длина =
# поколение» стало бы той самой тихой переинтерпретацией: строка N в старом
# потоке означала бы уже другую категорию.


@dataclass(frozen=True, slots=True)
class L0Dialect:
    """Одно поколение таблицы чтения.

    ``category_count`` — длина таблицы в этом поколении; ``fingerprint`` —
    sha256 (16 hex) по её именам через ``\\n``. Имена версий назначены
    РЕТРОСПЕКТИВНО 29.07: ни один снятый до этого дня байт версии диалекта не
    несёт, и читатель выводит поколение из самого потока. Это честно ровно
    потому, что вывод опирается на доказанный закон дописи в хвост, а не на
    догадку.
    """

    version: str
    category_count: int
    fingerprint: str
    note: str = ""

    def __post_init__(self) -> None:
        # Проверки развёрнуты, а не через ``_nonempty_string``: лестница
        # строится на импорте модуля, ВЫШЕ по файлу, чем общие помощники, —
        # версия обязана стоять рядом с ``L0_SCHEMA_VERSION``, а не уезжать
        # вниз ради переиспользования трёх строк.
        for name in ("version", "fingerprint"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise L0SchemaError(f"L0Dialect.{name} must be a non-empty string")
        if (isinstance(self.category_count, bool)
                or not isinstance(self.category_count, int)
                or self.category_count <= 0):
            raise L0SchemaError("L0Dialect.category_count must be positive")


def dialect_fingerprint(categories: Sequence[str]) -> str:
    """Отпечаток упорядоченной таблицы категорий.

    По ИМЕНАМ и ПОРЯДКУ, а не по длине: длина не отличила бы перестановку от
    исходной таблицы, а именно перестановка ломает адресацию возобновления.
    """
    joined = "\n".join(categories)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


#: Лестница поколений, от старого к новому. Отпечатки сняты с ИСТОРИИ
#: (git-ревизии extract.py) и независимо подтверждены байтами корпуса:
#: 22 — 22 слепка, 47 — 9, 48 — 12, 51 — 1, 54 — 10; расхождений ноль.
SUPPORTED_L0_DIALECTS: tuple[L0Dialect, ...] = (
    L0Dialect("kir-decompile-l0-dialect/1", 22, "0d20aa3e8b5ce49b",
              "18.07 (52ccee78) — первая закрытая таблица: АР + каркас."),
    L0Dialect("kir-decompile-l0-dialect/2", 47, "b256896173524f19",
              "27.07 (0a16e8f5) — разделы ЭОМ/ОВ/ВК/КР, +25 строк."),
    L0Dialect("kir-decompile-l0-dialect/3", 48, "292a11cb208e17b5",
              "28.07 (d1e77855) — витражная система, +1."),
    L0Dialect("kir-decompile-l0-dialect/4", 51, "f7b63ba25d895240",
              "29.07 (cfb820d6) — витражные сетки и линии сетки, +3."),
    L0Dialect("kir-decompile-l0-dialect/5", 54, "999cf7b6c990a8fe",
              "29.07 (8de6d1c5) — изоляция/оболочки воздуховодов, +3."),
    L0Dialect("kir-decompile-l0-dialect/6", 73, "40f56665718cc014",
              "29.07 (ee32fb82) — рабочая документация: размеры, марки, "
              "линии, узлы, +19."),
)

#: Версия, которой пишутся НОВЫЕ потоки.
L0_DIALECT_VERSION = SUPPORTED_L0_DIALECTS[-1].version
SUPPORTED_L0_DIALECT_VERSIONS = tuple(
    dialect.version for dialect in SUPPORTED_L0_DIALECTS)
_DIALECT_BY_VERSION = {
    dialect.version: dialect for dialect in SUPPORTED_L0_DIALECTS}
_DIALECT_BY_COUNT = {
    dialect.category_count: dialect for dialect in SUPPORTED_L0_DIALECTS}


def dialect_by_version(version: str) -> L0Dialect:
    """Ступень по имени версии. Чужое имя — отказ, а не ближайшая похожая."""
    dialect = _DIALECT_BY_VERSION.get(version)
    if dialect is None:
        raise L0SchemaError(
            f"неизвестная версия диалекта L0 {version!r}; поддерживаются "
            f"{', '.join(SUPPORTED_L0_DIALECT_VERSIONS)}")
    return dialect


def verify_dialect_ladder(table: Sequence[str]) -> None:
    """Сверить лестницу с живой таблицей. Расхождение — громкий отказ.

    Три утверждения, и каждое охраняет свой способ тихо соврать:

    1. свежая таблица ОБЯЗАНА быть последней ступенью — иначе следующая волна
       вырастит её, забудет ступень, и свежий слепок откажется читаться своим
       же читателем;
    2. отпечаток каждой ступени обязан совпасть с отпечатком префикса
       сегодняшней таблицы — это и есть запрет вставки в середину и
       переименования;
    3. ступени идут строго по возрастанию длины.
    """
    table = tuple(table)
    counts = [dialect.category_count for dialect in SUPPORTED_L0_DIALECTS]
    if counts != sorted(set(counts)):
        raise L0SchemaError(
            "ступени диалекта L0 обязаны идти строго по возрастанию длины")
    newest = SUPPORTED_L0_DIALECTS[-1]
    if len(table) != newest.category_count:
        raise L0SchemaError(
            f"таблица чтения содержит {len(table)} категорий, а последняя "
            f"ступень диалекта {newest.version} объявляет "
            f"{newest.category_count}: диалект изменился — заведите ступень "
            f"(отпечаток текущей таблицы {dialect_fingerprint(table)})")
    for dialect in SUPPORTED_L0_DIALECTS:
        prefix = table[:dialect.category_count]
        actual = dialect_fingerprint(prefix)
        if actual != dialect.fingerprint:
            raise L0SchemaError(
                f"{dialect.version} больше не является префиксом таблицы "
                f"чтения (ожидался отпечаток {dialect.fingerprint}, получен "
                f"{actual}): строку вставили в середину или переименовали, а "
                f"это сдвигает смысл уже снятых потоков и формат "
                f"возобновления")


def resolve_dialect(category_count: int, table: Sequence[str]) -> L0Dialect:
    """Назвать поколение потока по числу его категорий.

    Число, которого не было НИ В ОДНОЙ сборке, — не поколение, и догадка
    «наверное, префикс» здесь запрещена: неизвестно, что та сборка считала
    полнотой, а значит нельзя называть её поток полным.
    """
    verify_dialect_ladder(table)
    dialect = _DIALECT_BY_COUNT.get(category_count)
    if dialect is None:
        known = ", ".join(
            f"{d.category_count}={d.version}" for d in SUPPORTED_L0_DIALECTS)
        raise L0SchemaError(
            f"поток объявляет {category_count} категорий — такого поколения "
            f"диалекта L0 не существовало; известные: {known}")
    return dialect


def categories_outside_dialect(
    dialect: L0Dialect,
    table: Sequence[str],
) -> tuple[str, ...]:
    """Категории, которых в таблице ТОГО поколения ещё не было.

    Именно это отличает названную неполноту от молчаливого нуля: у старого
    слепка по этим категориям не «ноль элементов», а «не спрашивали».
    """
    return tuple(table[dialect.category_count:])


class GeometryKind(str, Enum):
    CURVE = "curve"
    POINT = "point"
    BBOX_ONLY = "bbox_only"


class LocationCurveKind(str, Enum):
    """Вид кривой элемента, снятый В САМОМ ЗАХВАТЕ (§18.1-следствие).

    ``geom_kind == "curve"`` говорит лишь, что у элемента есть
    ``LocationCurve``, — до этой волны дуга, сплайн и прямая в L0 были
    неразличимы, и лифт молча спрямлял дугу хордой (находка M2 аудита
    2026-07-28). Три значения закрывают вопрос ровно настолько, насколько на
    него можно ответить одним словом:

    * ``line`` — ``Autodesk.Revit.DB.Line``;
    * ``arc`` — ``Arc`` (точная геометрия — в боковом ``curve.index.json``);
    * ``other`` — NurbSpline / HermiteSpline / CylindricalHelix / прочее.

    ``None`` (поля нет в строке) — ОТДЕЛЬНОЕ состояние: «не мерили». Так
    выглядит весь замороженный L0, снятый до этой волны, и трактовать его как
    ``line`` было бы той же догадкой, что и хорда.
    """

    LINE = "line"
    ARC = "arc"
    OTHER = "other"


class CategoryState(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"


Vec2 = tuple[float, float]
Vec3 = tuple[float, float, float]


def _finite_number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise L0SchemaError(f"{field_name} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise L0SchemaError(f"{field_name} must be a finite number")
    return number


def _nonempty_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise L0SchemaError(f"{field_name} must be a non-empty string")
    return value


def _string(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise L0SchemaError(f"{field_name} must be a string")
    return value


def _optional_string(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    return _nonempty_string(value, field_name)


def _optional_enum(enum_cls: Any, value: Any, field_name: str) -> Any:
    """Parse an optional closed-vocabulary field without inventing a default.

    A missing key and an unknown value are deliberately different outcomes:
    absence is "never measured" (frozen L0 предшествующих волн), while a value
    outside the vocabulary is a payload defect and must refuse.
    """
    if value is None:
        return None
    try:
        return enum_cls(value)
    except (TypeError, ValueError) as exc:
        raise L0SchemaError(f"{field_name} is invalid: {value!r}") from exc


def _vec(value: Any, size: int, field_name: str) -> tuple[float, ...]:
    if (not isinstance(value, Sequence) or isinstance(value, (str, bytes))
            or len(value) != size):
        raise L0SchemaError(f"{field_name} must contain exactly {size} numbers")
    return tuple(_finite_number(item, f"{field_name}[{index}]")
                 for index, item in enumerate(value))


def _optional_vec(value: Any, size: int, field_name: str) -> tuple[float, ...] | None:
    return None if value is None else _vec(value, size, field_name)


def _mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise L0SchemaError(f"{field_name} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise L0SchemaError(f"{field_name} keys must be strings")
    return dict(value)


def _require_fields(
    row: Mapping[str, Any],
    required: Sequence[str],
    field_name: str,
) -> None:
    missing = [name for name in required if name not in row]
    if missing:
        raise L0SchemaError(
            f"{field_name} is missing required fields: {', '.join(missing)}")


def _bbox_pair(
    bbox_min_mm: Vec3 | None,
    bbox_max_mm: Vec3 | None,
    field_name: str,
) -> None:
    if (bbox_min_mm is None) != (bbox_max_mm is None):
        raise L0SchemaError(
            f"{field_name}: bbox_min_mm and bbox_max_mm must both be present or absent")
    if bbox_min_mm is not None and any(
            low > high for low, high in zip(bbox_min_mm, bbox_max_mm or ())):
        raise L0SchemaError(f"{field_name}: bbox min must not exceed bbox max")


@dataclass(frozen=True, slots=True)
class NamedReference:
    id: str
    name: str

    def __post_init__(self) -> None:
        _nonempty_string(self.id, "NamedReference.id")
        if not isinstance(self.name, str):
            raise L0SchemaError("NamedReference.name must be a string")

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "name": self.name}

    @classmethod
    def from_dict(cls, value: Any, field_name: str = "reference") -> "NamedReference":
        row = _mapping(value, field_name)
        _require_fields(row, ("id", "name"), field_name)
        return cls(
            id=_nonempty_string(row.get("id"), f"{field_name}.id"),
            name=_string(row.get("name"), f"{field_name}.name"),
        )


@dataclass(frozen=True, slots=True)
class LevelInfo:
    id: str
    name: str
    elevation_mm: float

    def __post_init__(self) -> None:
        _nonempty_string(self.id, "LevelInfo.id")
        if not isinstance(self.name, str):
            raise L0SchemaError("LevelInfo.name must be a string")
        _finite_number(self.elevation_mm, "LevelInfo.elevation_mm")

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name,
                "elevation_mm": self.elevation_mm}

    @classmethod
    def from_dict(cls, value: Any) -> "LevelInfo":
        row = _mapping(value, "level")
        _require_fields(row, ("id", "name", "elevation_mm"), "level")
        return cls(
            id=_nonempty_string(row.get("id"), "level.id"),
            name=_string(row.get("name"), "level.name"),
            elevation_mm=_finite_number(row.get("elevation_mm"), "level.elevation_mm"),
        )


@dataclass(frozen=True, slots=True)
class GridInfo:
    id: str
    name: str
    p0_mm: Vec3
    p1_mm: Vec3

    def __post_init__(self) -> None:
        _nonempty_string(self.id, "GridInfo.id")
        if not isinstance(self.name, str):
            raise L0SchemaError("GridInfo.name must be a string")
        _vec(self.p0_mm, 3, "GridInfo.p0_mm")
        _vec(self.p1_mm, 3, "GridInfo.p1_mm")

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name,
                "p0_mm": list(self.p0_mm), "p1_mm": list(self.p1_mm)}

    @classmethod
    def from_dict(cls, value: Any) -> "GridInfo":
        row = _mapping(value, "grid")
        _require_fields(row, ("id", "name", "p0_mm", "p1_mm"), "grid")
        return cls(
            id=_nonempty_string(row.get("id"), "grid.id"),
            name=_string(row.get("name"), "grid.name"),
            p0_mm=_vec(row.get("p0_mm"), 3, "grid.p0_mm"),  # type: ignore[arg-type]
            p1_mm=_vec(row.get("p1_mm"), 3, "grid.p1_mm"),  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True)
class RoomInfo:
    id: str
    name: str
    level_id: str | None
    level_name: str | None
    area_m2: float
    boundary_mm: tuple[Vec2, ...]
    boundary_loops_mm: tuple[tuple[Vec2, ...], ...]
    bounding_element_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _nonempty_string(self.id, "RoomInfo.id")
        if not isinstance(self.name, str):
            raise L0SchemaError("RoomInfo.name must be a string")
        _optional_string(self.level_id, "RoomInfo.level_id")
        _optional_string(self.level_name, "RoomInfo.level_name")
        if _finite_number(self.area_m2, "RoomInfo.area_m2") < 0:
            raise L0SchemaError("RoomInfo.area_m2 must be non-negative")
        for index, point in enumerate(self.boundary_mm):
            _vec(point, 2, f"RoomInfo.boundary_mm[{index}]")
        for loop_index, loop in enumerate(self.boundary_loops_mm):
            for point_index, point in enumerate(loop):
                _vec(point, 2,
                     f"RoomInfo.boundary_loops_mm[{loop_index}][{point_index}]")
        for index, element_id in enumerate(self.bounding_element_ids):
            _nonempty_string(
                element_id, f"RoomInfo.bounding_element_ids[{index}]")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "level_id": self.level_id,
            "level_name": self.level_name,
            "area_m2": self.area_m2,
            "boundary_mm": [list(point) for point in self.boundary_mm],
            "boundary_loops_mm": [
                [list(point) for point in loop] for loop in self.boundary_loops_mm
            ],
            "bounding_element_ids": list(self.bounding_element_ids),
        }

    @classmethod
    def from_dict(cls, value: Any) -> "RoomInfo":
        row = _mapping(value, "room")
        _require_fields(row, (
            "id", "name", "level_id", "level_name", "area_m2",
            "boundary_mm", "bounding_element_ids",
        ), "room")
        boundary = row.get("boundary_mm")
        loops = row.get("boundary_loops_mm")
        if loops is None:
            loops = [boundary] if boundary else []
        if not isinstance(boundary, list) or not isinstance(loops, list):
            raise L0SchemaError("room boundaries must be arrays")
        ids = row.get("bounding_element_ids")
        if not isinstance(ids, list):
            raise L0SchemaError("room.bounding_element_ids must be an array")
        return cls(
            id=_nonempty_string(row.get("id"), "room.id"),
            name=_string(row.get("name"), "room.name"),
            level_id=_optional_string(row.get("level_id"), "room.level_id"),
            level_name=_optional_string(row.get("level_name"), "room.level_name"),
            area_m2=_finite_number(row.get("area_m2"), "room.area_m2"),
            boundary_mm=tuple(
                _vec(point, 2, f"room.boundary_mm[{index}]")  # type: ignore[arg-type]
                for index, point in enumerate(boundary)),
            boundary_loops_mm=tuple(
                tuple(
                    _vec(point, 2,  # type: ignore[arg-type]
                         f"room.boundary_loops_mm[{loop_index}][{point_index}]")
                    for point_index, point in enumerate(loop))
                for loop_index, loop in enumerate(loops)),
            bounding_element_ids=tuple(
                _nonempty_string(element_id,
                                 f"room.bounding_element_ids[{index}]")
                for index, element_id in enumerate(ids)),
        )


@dataclass(frozen=True, slots=True)
class ProjectInfo:
    name: str | None = None
    address: str | None = None
    building_type_hint: str | None = None

    def __post_init__(self) -> None:
        _optional_string(self.name, "ProjectInfo.name")
        _optional_string(self.address, "ProjectInfo.address")
        _optional_string(
            self.building_type_hint, "ProjectInfo.building_type_hint")

    def to_dict(self) -> dict[str, str | None]:
        return {
            "name": self.name,
            "address": self.address,
            "building_type_hint": self.building_type_hint,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "ProjectInfo":
        row = _mapping({} if value is None else value, "project_info")
        return cls(
            name=_optional_string(row.get("name"), "project_info.name"),
            address=_optional_string(row.get("address"), "project_info.address"),
            building_type_hint=_optional_string(
                row.get("building_type_hint"),
                "project_info.building_type_hint"),
        )


@dataclass(frozen=True, slots=True)
class L0Element:
    element_id: str
    category: str
    category_ru: str
    type_id: str
    type_name: str
    level_id: str | None
    level_name: str | None
    geom_kind: GeometryKind
    p0_mm: Vec3 | None
    p1_mm: Vec3 | None
    rotation_deg: float | None
    bbox_min_mm: Vec3 | None
    bbox_max_mm: Vec3 | None
    host_id: str | None
    params: Mapping[str, Any] = field(default_factory=dict)
    design_option: NamedReference | None = None
    phase_created: NamedReference | None = None
    workset: NamedReference | None = None
    # §18.1-следствие: вид кривой. Поле ДОПИСАНО В КОНЕЦ намеренно — порядок
    # полей выше является позиционным контрактом уже написанного кода, а
    # значение по умолчанию делает поле совместимым с замороженным L0 1.0:
    # его строки поля не содержат, и отсутствие означает «не мерили», а не
    # «прямая» (см. :class:`LocationCurveKind`).
    curve_kind: "LocationCurveKind | None" = None

    def __post_init__(self) -> None:
        _nonempty_string(self.element_id, "L0Element.element_id")
        _nonempty_string(self.category, "L0Element.category")
        if not isinstance(self.category_ru, str):
            raise L0SchemaError("L0Element.category_ru must be a string")
        if not isinstance(self.type_id, str) or not isinstance(self.type_name, str):
            raise L0SchemaError("L0Element type id/name must be strings")
        _optional_string(self.level_id, "L0Element.level_id")
        _optional_string(self.level_name, "L0Element.level_name")
        if not isinstance(self.geom_kind, GeometryKind):
            raise L0SchemaError("L0Element.geom_kind must be a GeometryKind")
        _optional_vec(self.p0_mm, 3, "L0Element.p0_mm")
        _optional_vec(self.p1_mm, 3, "L0Element.p1_mm")
        if self.rotation_deg is not None:
            _finite_number(self.rotation_deg, "L0Element.rotation_deg")
        _optional_vec(self.bbox_min_mm, 3, "L0Element.bbox_min_mm")
        _optional_vec(self.bbox_max_mm, 3, "L0Element.bbox_max_mm")
        _bbox_pair(self.bbox_min_mm, self.bbox_max_mm, "L0Element")
        _optional_string(self.host_id, "L0Element.host_id")
        _mapping(self.params, "L0Element.params")
        for field_name, reference in (
            ("design_option", self.design_option),
            ("phase_created", self.phase_created),
            ("workset", self.workset),
        ):
            if reference is not None and not isinstance(reference, NamedReference):
                raise L0SchemaError(
                    f"L0Element.{field_name} must be a NamedReference or null")
        if self.curve_kind is not None:
            if not isinstance(self.curve_kind, LocationCurveKind):
                raise L0SchemaError(
                    "L0Element.curve_kind must be a LocationCurveKind or null")
            if self.geom_kind is not GeometryKind.CURVE:
                raise L0SchemaError(
                    "curve_kind describes a LocationCurve and cannot accompany "
                    f"{self.geom_kind.value} geometry")
        if self.geom_kind is GeometryKind.CURVE:
            if self.p0_mm is None or self.p1_mm is None:
                raise L0SchemaError("curve geometry requires p0_mm and p1_mm")
            if self.rotation_deg is not None:
                raise L0SchemaError("curve geometry must not carry rotation_deg")
        elif self.geom_kind is GeometryKind.POINT:
            if self.p0_mm is None or self.p1_mm is not None:
                raise L0SchemaError("point geometry requires only p0_mm")
            # Поворот у точки НЕОБЯЗАТЕЛЕН — см. тот же инвариант и его цену в
            # geometry_store.py: у помещений, зон, групп и текста модели
            # `LocationPoint.Rotation` не поддерживается по документации
            # Autodesk и бросает, а требование пары заставляло эмиссию терять
            # ещё и точку (12 369 помещений и 566 зон в четырёх зданиях —
            # ни одной точки за всю историю прогонов).
        elif any(value is not None for value in (
                self.p0_mm, self.p1_mm, self.rotation_deg)):
            raise L0SchemaError(
                "bbox_only geometry must not carry point/curve fields")

    def to_dict(self) -> dict[str, Any]:
        return {
            "element_id": self.element_id,
            "category": self.category,
            "category_ru": self.category_ru,
            "type_id": self.type_id,
            "type_name": self.type_name,
            "level_id": self.level_id,
            "level_name": self.level_name,
            "geom_kind": self.geom_kind.value,
            "p0_mm": list(self.p0_mm) if self.p0_mm is not None else None,
            "p1_mm": list(self.p1_mm) if self.p1_mm is not None else None,
            "rotation_deg": self.rotation_deg,
            "bbox_min_mm": (
                list(self.bbox_min_mm) if self.bbox_min_mm is not None else None),
            "bbox_max_mm": (
                list(self.bbox_max_mm) if self.bbox_max_mm is not None else None),
            "host_id": self.host_id,
            "params": dict(self.params),
            "design_option": (
                self.design_option.to_dict() if self.design_option else None),
            "phase_created": (
                self.phase_created.to_dict() if self.phase_created else None),
            "workset": self.workset.to_dict() if self.workset else None,
            "curve_kind": (
                self.curve_kind.value if self.curve_kind is not None else None),
        }

    @classmethod
    def from_dict(cls, value: Any) -> "L0Element":
        row = _mapping(value, "element")
        _require_fields(row, (
            "element_id", "category", "category_ru", "type_id", "type_name",
            "level_id", "level_name", "geom_kind", "p0_mm", "p1_mm",
            "rotation_deg", "bbox_min_mm", "bbox_max_mm", "host_id", "params",
        ), "element")
        try:
            geom_kind = GeometryKind(row.get("geom_kind"))
        except (TypeError, ValueError) as exc:
            raise L0SchemaError(
                f"element.geom_kind is invalid: {row.get('geom_kind')!r}") from exc
        return cls(
            element_id=_nonempty_string(
                row.get("element_id"), "element.element_id"),
            category=_nonempty_string(row.get("category"), "element.category"),
            category_ru=_string(row.get("category_ru"), "element.category_ru"),
            type_id=_string(row.get("type_id"), "element.type_id"),
            type_name=_string(row.get("type_name"), "element.type_name"),
            level_id=_optional_string(row.get("level_id"), "element.level_id"),
            level_name=_optional_string(row.get("level_name"), "element.level_name"),
            geom_kind=geom_kind,
            p0_mm=_optional_vec(
                row.get("p0_mm"), 3, "element.p0_mm"),  # type: ignore[arg-type]
            p1_mm=_optional_vec(
                row.get("p1_mm"), 3, "element.p1_mm"),  # type: ignore[arg-type]
            rotation_deg=(None if row.get("rotation_deg") is None else
                          _finite_number(
                              row.get("rotation_deg"), "element.rotation_deg")),
            bbox_min_mm=_optional_vec(
                row.get("bbox_min_mm"), 3,
                "element.bbox_min_mm"),  # type: ignore[arg-type]
            bbox_max_mm=_optional_vec(
                row.get("bbox_max_mm"), 3,
                "element.bbox_max_mm"),  # type: ignore[arg-type]
            host_id=_optional_string(row.get("host_id"), "element.host_id"),
            params=_mapping(row.get("params"), "element.params"),
            design_option=(
                NamedReference.from_dict(
                    row["design_option"], "element.design_option")
                if row.get("design_option") is not None else None),
            phase_created=(
                NamedReference.from_dict(
                    row["phase_created"], "element.phase_created")
                if row.get("phase_created") is not None else None),
            workset=(
                NamedReference.from_dict(row["workset"], "element.workset")
                if row.get("workset") is not None else None),
            curve_kind=_optional_enum(
                LocationCurveKind, row.get("curve_kind"), "element.curve_kind"),
        )


@dataclass(frozen=True, slots=True)
class LinkSummary:
    element_id: str
    name: str
    loaded: bool
    element_count: int | None
    bbox_min_mm: Vec3 | None
    bbox_max_mm: Vec3 | None
    discipline: str

    def __post_init__(self) -> None:
        _nonempty_string(self.element_id, "LinkSummary.element_id")
        if not isinstance(self.name, str):
            raise L0SchemaError("LinkSummary.name must be a string")
        if not isinstance(self.loaded, bool):
            raise L0SchemaError("LinkSummary.loaded must be boolean")
        if (self.element_count is not None
                and (isinstance(self.element_count, bool)
                     or not isinstance(self.element_count, int)
                     or self.element_count < 0)):
            raise L0SchemaError(
                "LinkSummary.element_count must be non-negative or null")
        _optional_vec(self.bbox_min_mm, 3, "LinkSummary.bbox_min_mm")
        _optional_vec(self.bbox_max_mm, 3, "LinkSummary.bbox_max_mm")
        _bbox_pair(self.bbox_min_mm, self.bbox_max_mm, "LinkSummary")
        _nonempty_string(self.discipline, "LinkSummary.discipline")

    def to_dict(self) -> dict[str, Any]:
        return {
            "element_id": self.element_id,
            "name": self.name,
            "loaded": self.loaded,
            "element_count": self.element_count,
            "bbox_min_mm": (
                list(self.bbox_min_mm) if self.bbox_min_mm is not None else None),
            "bbox_max_mm": (
                list(self.bbox_max_mm) if self.bbox_max_mm is not None else None),
            "discipline": self.discipline,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "LinkSummary":
        row = _mapping(value, "link")
        _require_fields(row, (
            "element_id", "name", "loaded", "element_count",
            "bbox_min_mm", "bbox_max_mm", "discipline",
        ), "link")
        loaded = row.get("loaded")
        if not isinstance(loaded, bool):
            raise L0SchemaError("link.loaded must be boolean")
        count = row.get("element_count")
        if (count is not None
                and (isinstance(count, bool) or not isinstance(count, int))):
            raise L0SchemaError(
                "link.element_count must be an integer or null")
        return cls(
            element_id=_nonempty_string(
                row.get("element_id"), "link.element_id"),
            name=_string(row.get("name"), "link.name"),
            loaded=loaded,
            element_count=count,
            bbox_min_mm=_optional_vec(
                row.get("bbox_min_mm"), 3,
                "link.bbox_min_mm"),  # type: ignore[arg-type]
            bbox_max_mm=_optional_vec(
                row.get("bbox_max_mm"), 3,
                "link.bbox_max_mm"),  # type: ignore[arg-type]
            discipline=_nonempty_string(
                row.get("discipline"), "link.discipline"),
        )


#: Шесть исходов чтения одного параметра сечения (ревью кодекса №12). Порядок
#: значим: он же порядок слотов в генерируемом C#.
SECTION_RECEIPT_OUTCOMES = (
    "instance_hit", "type_hit", "not_applicable", "no_value",
    "wrong_storage", "exception",
)


@dataclass(frozen=True, slots=True)
class SectionReceipt:
    """Квитанция fail-open одного параметра сечения по одной категории.

    До неё `null`, `HasValue=false`, чужой `StorageType` и исключение
    схлопывались в ОДИН отсутствующий ключ: «у этого класса такого параметра
    нет» было неотличимо от «параметр есть, а прочитать не вышло». Замер v13:
    ширина снята у 992 стен из 1189, и все 197 пропусков совпадают с
    витражными носителями — совпадение идеальное, но код не мог этого ДОКАЗАТЬ.

    Счётчики агрегатные (на категорию × параметр), поэтому цена квитанции не
    зависит от размера модели.
    """

    parameter: str
    instance_hit: int = 0
    type_hit: int = 0
    not_applicable: int = 0
    no_value: int = 0
    wrong_storage: int = 0
    exception: int = 0

    def __post_init__(self) -> None:
        _nonempty_string(self.parameter, "section_receipt.parameter")
        for name in SECTION_RECEIPT_OUTCOMES:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise L0SchemaError(
                    f"section_receipt.{name} must be a non-negative integer")

    def total(self) -> int:
        """Сколько элементов опрошено этим параметром. Ровно это число обязано
        совпасть с `extracted_count` категории — иначе перепись не сходится."""
        return sum(getattr(self, name) for name in SECTION_RECEIPT_OUTCOMES)

    def to_dict(self) -> dict[str, Any]:
        row: dict[str, Any] = {"parameter": self.parameter}
        for name in SECTION_RECEIPT_OUTCOMES:
            row[name] = getattr(self, name)
        return row

    @classmethod
    def from_dict(cls, value: Any) -> "SectionReceipt":
        row = _mapping(value, "section_receipt")
        _require_fields(row, ("parameter",) + SECTION_RECEIPT_OUTCOMES,
                        "section_receipt")
        return cls(
            parameter=_nonempty_string(
                row.get("parameter"), "section_receipt.parameter"),
            **{name: row.get(name) for name in SECTION_RECEIPT_OUTCOMES},
        )


@dataclass(frozen=True, slots=True)
class CategoryStatus:
    category: str
    state: CategoryState
    extracted_count: int
    expected_count: int | None = None
    error: str | None = None
    #: Квитанции чтения сечений (ревью кодекса №12). `None` — поток записан ДО
    #: волны квитанций и об исходах чтения НИЧЕГО не утверждает; пустой кортеж
    #: — ни одной страницы не получено. Шесть нулей вместо `None` были бы
    #: утверждением, которого старый поток не делал.
    section_receipts: tuple["SectionReceipt", ...] | None = None

    def __post_init__(self) -> None:
        _nonempty_string(self.category, "CategoryStatus.category")
        if not isinstance(self.state, CategoryState):
            raise L0SchemaError("CategoryStatus.state must be a CategoryState")
        if (isinstance(self.extracted_count, bool)
                or not isinstance(self.extracted_count, int)
                or self.extracted_count < 0):
            raise L0SchemaError(
                "CategoryStatus.extracted_count must be non-negative")
        if (self.expected_count is not None
                and (isinstance(self.expected_count, bool)
                     or not isinstance(self.expected_count, int)
                     or self.expected_count < 0)):
            raise L0SchemaError(
                "CategoryStatus.expected_count must be non-negative or null")
        _optional_string(self.error, "CategoryStatus.error")
        if self.state is CategoryState.COMPLETE:
            if self.expected_count is None:
                raise L0SchemaError(
                    "complete category status requires expected_count")
            if self.extracted_count != self.expected_count:
                raise L0SchemaError(
                    "complete category status count does not match expected")
            if self.error is not None:
                raise L0SchemaError(
                    "complete category status cannot carry an error")
        elif self.error is None:
            raise L0SchemaError(
                "partial category status requires an error")
        if self.section_receipts is not None:
            if not isinstance(self.section_receipts, tuple):
                raise L0SchemaError(
                    "CategoryStatus.section_receipts must be a tuple or null")
            names = [r.parameter for r in self.section_receipts]
            if names != sorted(names) or len(names) != len(set(names)):
                raise L0SchemaError(
                    "section receipts must be unique and sorted by parameter")
            for receipt in self.section_receipts:
                if receipt.total() != self.extracted_count:
                    raise L0SchemaError(
                        f"перепись сечений не сходится: "
                        f"{receipt.parameter} опросил {receipt.total()} "
                        f"элементов, извлечено {self.extracted_count}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "state": self.state.value,
            "extracted_count": self.extracted_count,
            "expected_count": self.expected_count,
            "error": self.error,
            "section_receipts": (
                None if self.section_receipts is None
                else [r.to_dict() for r in self.section_receipts]),
        }

    @classmethod
    def from_dict(cls, value: Any) -> "CategoryStatus":
        row = _mapping(value, "category_status")
        _require_fields(row, (
            "category", "state", "extracted_count", "expected_count", "error",
        ), "category_status")
        try:
            state = CategoryState(row.get("state"))
        except (TypeError, ValueError) as exc:
            raise L0SchemaError(
                f"category_status.state is invalid: {row.get('state')!r}") from exc
        extracted = row.get("extracted_count")
        expected = row.get("expected_count")
        if isinstance(extracted, bool) or not isinstance(extracted, int):
            raise L0SchemaError(
                "category_status.extracted_count must be an integer")
        if (expected is not None
                and (isinstance(expected, bool) or not isinstance(expected, int))):
            raise L0SchemaError(
                "category_status.expected_count must be an integer or null")
        raw_receipts = row.get("section_receipts")
        if raw_receipts is None:
            receipts = None
        else:
            if not isinstance(raw_receipts, list):
                raise L0SchemaError(
                    "category_status.section_receipts must be an array or null")
            receipts = tuple(
                SectionReceipt.from_dict(item) for item in raw_receipts)
        return cls(
            category=_nonempty_string(
                row.get("category"), "category_status.category"),
            state=state,
            extracted_count=extracted,
            expected_count=expected,
            error=_optional_string(row.get("error"), "category_status.error"),
            section_receipts=receipts,
        )


@dataclass(frozen=True, slots=True)
class CensusEntry:
    """Одна строка переписи документа (§18.1): категория → счётчик.

    ``key`` — BuiltInCategory (или ``category_id:<n>`` для категории, которой
    в перечислении нет, либо ``no_category``). Ключом РАБОТАЕТ только он:
    §18.5 запрещает локализованное имя как единственный ключ правила, поэтому
    ``name`` — справочная колонка для человека и ничего не решает.

    ``count`` — сколько таких элементов насчитал один полномодельный проход.
    Ни геометрии, ни параметров: перепись обязана оставаться дешёвой, чтобы
    исполняться ВСЕГДА, а не «на маленьких моделях».
    """

    key: str
    name: str
    count: int

    def __post_init__(self) -> None:
        _nonempty_string(self.key, "census.key")
        if not isinstance(self.name, str):
            raise L0SchemaError("census.name must be a string")
        if isinstance(self.count, bool) or not isinstance(self.count, int) \
                or self.count < 0:
            raise L0SchemaError("census.count must be a non-negative integer")

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "name": self.name, "count": self.count}

    @classmethod
    def from_dict(cls, value: Any) -> "CensusEntry":
        row = _mapping(value, "census")
        _require_fields(row, ("key", "count"), "census")
        return cls(
            key=_nonempty_string(row.get("key"), "census.key"),
            name=_string(row.get("name") or "", "census.name"),
            count=row.get("count"),  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True)
class L0Document:
    doc_name: str
    revit_version: str
    units: str
    change_stamp: str
    levels: tuple[LevelInfo, ...]
    grids: tuple[GridInfo, ...]
    rooms: tuple[RoomInfo, ...]
    project_info: ProjectInfo
    elements: tuple[L0Element, ...] = ()
    category_status: tuple[CategoryStatus, ...] = ()
    links: tuple[LinkSummary, ...] = ()
    # Состояние рабочих наборов. ЗАМЕР 27.07 (тренировочная модель ЭОМ,
    # SKLNK R2026): документ открыли с 17 закрытыми наборами из 18, и
    # коллекторы честно вернули то, что видели, — 11 элементов вместо 2016.
    # Извлечение прошло бы без единого признака неполноты, а покрытие по
    # такому L0 описывало бы диалог открытия файла, а не компилятор.
    #
    # Значения по умолчанию делают поля совместимыми с замороженным L0 1.0:
    # его строки их не содержат, и отсутствие означает «не измерялось», а не
    # «наборов нет».
    worksharing: bool = False
    worksets: tuple[dict, ...] = ()
    worksets_closed: int = 0
    # §18.1: перепись всего документа. Пустой кортеж = переписи НЕ БЫЛО (L0
    # снят до этой волны или мост её не вернул), а не «в документе ноль
    # элементов»: разбор этих двух состояний живёт в decompile.census и
    # обязан оставаться раздельным — иначе отсутствие знаменателя выглядит
    # как полное покрытие.
    census: tuple["CensusEntry", ...] = ()

    @property
    def census_total(self) -> int:
        """Сколько элементов насчитала перепись (0, если её не было)."""
        return sum(entry.count for entry in self.census)

    @property
    def has_census(self) -> bool:
        return bool(self.census)

    @property
    def is_partial_read(self) -> bool:
        """Читался ли документ ЗАВЕДОМО неполным.

        Отдельным именем, а не голым числом: вызывающему нужен ответ на
        вопрос «можно ли верить этому L0», и он не должен каждый раз
        выводить его сам.
        """
        return self.worksharing and self.worksets_closed > 0

    def __post_init__(self) -> None:
        _nonempty_string(self.doc_name, "L0Document.doc_name")
        _nonempty_string(self.revit_version, "L0Document.revit_version")
        if self.units != L0_UNITS:
            raise L0SchemaError(
                f"L0Document.units must be {L0_UNITS!r}, got {self.units!r}")
        _nonempty_string(self.change_stamp, "L0Document.change_stamp")
        for field_name, collection, expected_type in (
            ("levels", self.levels, LevelInfo),
            ("grids", self.grids, GridInfo),
            ("rooms", self.rooms, RoomInfo),
            ("elements", self.elements, L0Element),
            ("category_status", self.category_status, CategoryStatus),
            ("links", self.links, LinkSummary),
            ("census", self.census, CensusEntry),
        ):
            if not isinstance(collection, tuple) or not all(
                    isinstance(item, expected_type) for item in collection):
                raise L0SchemaError(
                    f"L0Document.{field_name} must be a tuple of "
                    f"{expected_type.__name__}")
        if not isinstance(self.project_info, ProjectInfo):
            raise L0SchemaError(
                "L0Document.project_info must be a ProjectInfo")
        if tuple(sorted(self.levels, key=lambda level: level.elevation_mm)) != self.levels:
            raise L0SchemaError("L0Document.levels must be sorted by elevation")
        for field_name, identifiers in (
            ("levels", [level.id for level in self.levels]),
            ("grids", [grid.id for grid in self.grids]),
            ("rooms", [room.id for room in self.rooms]),
            ("elements", [element.element_id for element in self.elements]),
            ("links", [link.element_id for link in self.links]),
        ):
            if len(identifiers) != len(set(identifiers)):
                raise L0SchemaError(
                    f"L0Document.{field_name} contains duplicate ids")
        categories = [status.category for status in self.category_status]
        if len(categories) != len(set(categories)):
            raise L0SchemaError("L0Document.category_status contains duplicates")
        census_keys = [entry.key for entry in self.census]
        if len(census_keys) != len(set(census_keys)):
            # Дублирующийся ключ означал бы, что одну категорию посчитали
            # дважды, и тождество §18.1 сошлось бы на неверном знаменателе.
            raise L0SchemaError("L0Document.census contains duplicate keys")

    def metadata_dict(self) -> dict[str, Any]:
        # §18.4: состояние рабочих наборов — часть ЗАГОЛОВКА, а не только
        # полного документа. Заголовок — единственное, что переживает запись
        # L0.jsonl и что читают все потребители ниже по течению (A5, re-lift,
        # паспорт). Пока эти три поля жили лишь в to_dict(), сигнал «читалась
        # часть модели» терялся между C# и первым же артефактом.
        return {
            "doc_name": self.doc_name,
            "revit_version": self.revit_version,
            "units": self.units,
            "change_stamp": self.change_stamp,
            "levels": [level.to_dict() for level in self.levels],
            "grids": [grid.to_dict() for grid in self.grids],
            "rooms": [room.to_dict() for room in self.rooms],
            "project_info": self.project_info.to_dict(),
            "worksharing": self.worksharing,
            "worksets": list(self.worksets),
            "worksets_closed": self.worksets_closed,
            # §18.1: перепись — часть ЗАГОЛОВКА по той же причине, по которой
            # ею стали рабочие наборы: заголовок — единственное, что переживает
            # запись L0.jsonl и что читают все потребители ниже по течению.
            "census": [entry.to_dict() for entry in self.census],
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.metadata_dict(),
            "elements": [element.to_dict() for element in self.elements],
            "category_status": [
                status.to_dict() for status in self.category_status],
            "links": [link.to_dict() for link in self.links],
        }

    @classmethod
    def from_dict(cls, value: Any) -> "L0Document":
        row = _mapping(value, "document")
        _require_fields(row, (
            "doc_name", "revit_version", "units", "change_stamp",
            "levels", "grids", "rooms", "project_info", "elements",
        ), "document")
        levels = row.get("levels")
        grids = row.get("grids")
        rooms = row.get("rooms")
        elements = row.get("elements")
        statuses = row.get("category_status", [])
        links = row.get("links", [])
        census_rows = row.get("census") or []
        for field_name, collection in (
            ("levels", levels), ("grids", grids), ("rooms", rooms),
            ("elements", elements), ("category_status", statuses),
            ("links", links), ("census", census_rows),
        ):
            if not isinstance(collection, list):
                raise L0SchemaError(f"document.{field_name} must be an array")
        return cls(
            doc_name=_nonempty_string(row.get("doc_name"), "document.doc_name"),
            revit_version=_nonempty_string(
                row.get("revit_version"), "document.revit_version"),
            units=_nonempty_string(row.get("units"), "document.units"),
            change_stamp=_nonempty_string(
                row.get("change_stamp"), "document.change_stamp"),
            levels=tuple(LevelInfo.from_dict(item) for item in levels),
            grids=tuple(GridInfo.from_dict(item) for item in grids),
            rooms=tuple(RoomInfo.from_dict(item) for item in rooms),
            project_info=ProjectInfo.from_dict(row.get("project_info", {})),
            elements=tuple(L0Element.from_dict(item) for item in elements),
            category_status=tuple(
                CategoryStatus.from_dict(item) for item in statuses),
            links=tuple(LinkSummary.from_dict(item) for item in links),
            worksharing=bool(row.get("worksharing", False)),
            worksets=tuple(row.get("worksets") or ()),
            worksets_closed=int(row.get("worksets_closed") or 0),
            census=tuple(
                CensusEntry.from_dict(item) for item in census_rows),
        )
