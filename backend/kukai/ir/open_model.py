"""Typed capabilities of the already-open Revit document.

The KIR compiler has always grounded symbolic selectors against one batched
``ground_snapshot`` bridge read.  This module turns that loose dictionary into
a versioned contract without introducing a second catalog:

* the existing snapshot remains the compiler-facing wire shape;
* every catalog row can additionally carry Revit's ``UniqueId`` and
  ``VersionGuid`` so an ``ElementId`` is not mistaken for durable identity;
* every pool carries an observed total, making truncation/completeness a proof
  rather than an assumption;
* the profile is bound to :class:`DocumentFingerprint` and, when persisted by
  a revision-guarded caller, :class:`RevisionProof`;
* same-document preflight checks pinned selectors before the first write.

Compatibility is deliberately fail-closed.  Legacy unversioned snapshots are
still accepted and can ground exactly as before, but missing identity/count
evidence keeps ``authoritative`` false.  An explicit unknown schema version is
refused.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence

from kukai.ir.contracts import (
    ContractSchemaError,
    DocumentFingerprint,
    ElementIdentityProof,
    RevisionProof,
)
from kukai.ir.emit_utils import ELEMENT_ID_MAX


OPEN_MODEL_PROFILE_SCHEMA_VERSION = "open-model-profile/1"
OPEN_MODEL_PREFLIGHT_SCHEMA_VERSION = "open-model-preflight/1"
_VERSION_GUID_RE = re.compile(r"[0-9a-f]{32}\Z")


class OpenModelProfileError(ValueError):
    """A live/serialized model profile is malformed or overclaims evidence."""


def _mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise OpenModelProfileError(f"{field_name} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise OpenModelProfileError(f"{field_name} keys must be strings")
    return dict(value)


def _string(
    value: Any,
    field_name: str,
    *,
    nonempty: bool = False,
) -> str:
    if not isinstance(value, str) or (nonempty and not value):
        suffix = "a non-empty string" if nonempty else "a string"
        raise OpenModelProfileError(f"{field_name} must be {suffix}")
    return value


def _optional_string(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    return _string(value, field_name, nonempty=True)


def _optional_evidence_string(value: Any, field_name: str) -> str | None:
    """Treat a bridge catch-path's empty string as absent evidence."""

    if value in (None, ""):
        return None
    return _string(value, field_name, nonempty=True)


def _strict_bool(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise OpenModelProfileError(f"{field_name} must be a JSON boolean")
    return value


def _element_id(value: Any, field_name: str) -> int:
    if (isinstance(value, bool) or not isinstance(value, int)
            or not 1 <= value <= ELEMENT_ID_MAX):
        raise OpenModelProfileError(
            f"{field_name} must be an ElementId within 1..{ELEMENT_ID_MAX}")
    return value


def _nonnegative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise OpenModelProfileError(
            f"{field_name} must be a non-negative integer")
    return value


def _strings(value: Any, field_name: str) -> tuple[str, ...]:
    if (not isinstance(value, Sequence)
            or isinstance(value, (str, bytes, bytearray))):
        raise OpenModelProfileError(
            f"{field_name} must be a list of strings")
    result = tuple(
        _string(item, f"{field_name}[{index}]", nonempty=True)
        for index, item in enumerate(value)
    )
    if len(result) != len(set(result)):
        raise OpenModelProfileError(f"{field_name} contains duplicates")
    return result


def _optional_vec2(value: Any, field_name: str) -> tuple[float, float] | None:
    if value is None:
        return None
    if (not isinstance(value, Sequence)
            or isinstance(value, (str, bytes, bytearray))
            or len(value) != 2):
        raise OpenModelProfileError(f"{field_name} must contain two numbers")
    result: list[float] = []
    for index, item in enumerate(value):
        if (isinstance(item, bool) or not isinstance(item, (int, float))
                or not math.isfinite(float(item))):
            raise OpenModelProfileError(
                f"{field_name}[{index}] must be a finite number")
        result.append(float(item))
    return result[0], result[1]


def _canonical_object_json(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    row = _mapping(value, field_name)
    try:
        return json.dumps(
            row,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise OpenModelProfileError(
            f"{field_name} must contain only finite JSON values") from exc


#: Виды сечения типа. Список ЗАКРЫТ: строка пула либо выходит отсюда ровно с
#: одним видом, либо не несёт сечения вовсе — «похожего» вида не бывает.
#:
#: `plate`         — тело постоянной толщины вокруг своей опорной поверхности
#:                   (стена вокруг оси, плита вокруг отметки);
#: `round`         — круглое сечение объявленного ДИАМЕТРА;
#: `rect`          — прямоугольное сечение (ширина, высота);
#: `nominal_table` — таблица «номинал -> наружный», прочитанная у типа. Одна
#:                   строка сама по себе тела не задаёт: тело появляется, когда
#:                   программа НАЗОВЁТ номинал, а таблица переведёт его в
#:                   наружный размер.
SECTION_KINDS = ("plate", "round", "rect", "nominal_table")

#: Максимум строк в таблице номиналов ОДНОГО типа. Сегмент трубы несёт весь
#: сортамент; потолок держит вес снапшота, а его достижение НАЗЫВАЕТСЯ
#: (`sizes_truncated`), потому что усечённая таблица и отсутствующая таблица —
#: разные факты: по первой номинал может не найтись, и это не «нет данных».
SECTION_MAX_SIZES = 64


@dataclass(frozen=True, slots=True)
class TypeSection:
    """Геометрия ТИПА: чем именно тело элемента этого типа ограничено.

    ЗАЧЕМ ЭТО ЗДЕСЬ. Замер 09.08 по реестру (`spec.OPS`, 48 операций): ни одна
    операция создания не несёт толщину стены, перекрытия или сечение колонны —
    `create_wall` объявляет ось и высоту, `create_cable_tray` только ось. Все
    эти числа живут в ТИПЕ, а тип разрешается против ЖИВОГО документа ровно на
    стадии ground. Значит, единственное место, где сечение вообще знаемо, —
    здесь, и до этой волны строка пула несла только `{id, name}`.

    ЧЕСТНОСТЬ ПОЛЯ `uniform`. Число само по себе не даёт права строить призму:
    у стены переменного состава по высоте, у наклонной, у стены с выступами
    призма по одной толщине тело НЕ содержит, то есть допускает ПРОПУСК клеша.
    Поэтому запись несёт два поля сразу: число и приговор о том, ограничивает
    ли оно тело. `uniform=False` без `blockers` невозможен — причина обязана
    быть НАЗВАНА, иначе «тела нет» неотличимо от «не смотрели».

    Единицы — миллиметры, как во всём снапшоте.
    """

    kind: str
    source: str
    thickness_mm: float | None = None
    diameter_mm: float | None = None
    width_mm: float | None = None
    height_mm: float | None = None
    #: Собственный габарит типоразмера по Z относительно ТОЧКИ ВСТАВКИ, мм.
    #: Знак значим: у реальной колонны база уходит НИЖЕ своей отметки (замер
    #: 09.08 на Snowdon: 4 колонны из 114 выходили за оболочку ровно на
    #: 254.0 мм вниз — это геометрия семейства, а не ошибка программы).
    local_z_min_mm: float | None = None
    local_z_max_mm: float | None = None
    #: Пары `(номинал_мм, наружный_мм)`, отсортированные по номиналу.
    sizes: tuple[tuple[float, float], ...] = ()
    sizes_truncated: bool = False
    uniform: bool = False
    blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in SECTION_KINDS:
            raise OpenModelProfileError(
                f"type_section.kind must be one of {SECTION_KINDS}")
        _string(self.source, "type_section.source", nonempty=True)
        for field_name, value in (
            ("thickness_mm", self.thickness_mm),
            ("diameter_mm", self.diameter_mm),
            ("width_mm", self.width_mm),
            ("height_mm", self.height_mm),
        ):
            if value is None:
                continue
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(float(value)) or float(value) <= 0.0):
                raise OpenModelProfileError(
                    f"type_section.{field_name} must be a positive number")
        for field_name, value in (("local_z_min_mm", self.local_z_min_mm),
                                  ("local_z_max_mm", self.local_z_max_mm)):
            if value is None:
                continue
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(float(value))):
                raise OpenModelProfileError(
                    f"type_section.{field_name} must be a finite number")
        if ((self.local_z_min_mm is None) != (self.local_z_max_mm is None)):
            raise OpenModelProfileError(
                "type_section local z bounds must both be present or absent")
        if (self.local_z_min_mm is not None
                and float(self.local_z_min_mm) > float(self.local_z_max_mm)):
            raise OpenModelProfileError(
                "type_section.local_z_min_mm must not exceed local_z_max_mm")
        if not isinstance(self.sizes, tuple):
            raise OpenModelProfileError("type_section.sizes must be a tuple")
        previous = None
        for index, pair in enumerate(self.sizes):
            if (not isinstance(pair, tuple) or len(pair) != 2
                    or any(isinstance(item, bool)
                           or not isinstance(item, (int, float))
                           or not math.isfinite(float(item))
                           or float(item) <= 0.0 for item in pair)):
                raise OpenModelProfileError(
                    f"type_section.sizes[{index}] must be two positive numbers")
            if previous is not None and float(pair[0]) <= previous:
                raise OpenModelProfileError(
                    "type_section.sizes must be sorted by unique nominal")
            previous = float(pair[0])
        _strict_bool(self.sizes_truncated, "type_section.sizes_truncated")
        _strict_bool(self.uniform, "type_section.uniform")
        blockers = _strings(self.blockers, "type_section.blockers")
        if blockers != tuple(sorted(blockers)):
            raise OpenModelProfileError(
                "type_section.blockers must be sorted")
        # Закон переписи, перенесённый на одну строку: «не ограничивает» без
        # причины — то же молчание, от которого весь этот модуль защищает.
        if self.uniform and blockers:
            raise OpenModelProfileError(
                "type_section cannot be uniform and blocked at once")
        if not self.uniform and not blockers and self.kind != "nominal_table":
            raise OpenModelProfileError(
                "non-uniform type_section must name its blockers")

    def to_dict(self) -> dict[str, Any]:
        """Каноническая строка. Пустые поля ОПУЩЕНЫ, а не занулены: снапшот
        без сечения обязан остаться байт в байт прежним (см. отпечатки)."""
        row: dict[str, Any] = {"kind": self.kind, "source": self.source}
        for key, value in (
            ("thickness_mm", self.thickness_mm),
            ("diameter_mm", self.diameter_mm),
            ("width_mm", self.width_mm),
            ("height_mm", self.height_mm),
        ):
            if value is not None:
                row[key] = float(value)
        if self.local_z_min_mm is not None:
            row["local_z_min_mm"] = float(self.local_z_min_mm)
            row["local_z_max_mm"] = float(self.local_z_max_mm)
        if self.sizes:
            row["sizes"] = [[float(a), float(b)] for a, b in self.sizes]
        if self.sizes_truncated:
            row["sizes_truncated"] = True
        if self.uniform:
            row["uniform"] = True
        if self.blockers:
            row["blockers"] = list(self.blockers)
        return row

    @classmethod
    def from_dict(cls, value: Any, *,
                  field_name: str = "type_section") -> "TypeSection":
        row = _mapping(value, field_name)
        raw_sizes = row.get("sizes") or ()
        if (not isinstance(raw_sizes, Sequence)
                or isinstance(raw_sizes, (str, bytes, bytearray))):
            raise OpenModelProfileError(f"{field_name}.sizes must be a list")
        sizes: list[tuple[float, float]] = []
        for index, pair in enumerate(raw_sizes):
            if (not isinstance(pair, Sequence)
                    or isinstance(pair, (str, bytes, bytearray))
                    or len(pair) != 2):
                raise OpenModelProfileError(
                    f"{field_name}.sizes[{index}] must be a pair")
            sizes.append((float(pair[0]), float(pair[1])))
        raw_blockers = row.get("blockers") or ()
        return cls(
            kind=_string(row.get("kind"), f"{field_name}.kind", nonempty=True),
            source=_string(
                row.get("source"), f"{field_name}.source", nonempty=True),
            thickness_mm=row.get("thickness_mm"),
            diameter_mm=row.get("diameter_mm"),
            width_mm=row.get("width_mm"),
            height_mm=row.get("height_mm"),
            local_z_min_mm=row.get("local_z_min_mm"),
            local_z_max_mm=row.get("local_z_max_mm"),
            sizes=tuple(sizes),
            sizes_truncated=_strict_bool(
                row.get("sizes_truncated", False),
                f"{field_name}.sizes_truncated"),
            uniform=_strict_bool(
                row.get("uniform", False), f"{field_name}.uniform"),
            blockers=_strings(list(raw_blockers), f"{field_name}.blockers"),
        )

    def outer_for_nominal_mm(self, nominal_mm: float,
                             *, tol_mm: float = 0.5) -> float | None:
        """Номинал -> НАРУЖНЫЙ размер по таблице ТИПА, либо `None`.

        Ни одного коэффициента здесь нет и быть не может: перевод существует
        ровно потому, что его напечатал сам документ (`PipeSegment.GetSizes`).
        Номинала, которого в таблице нет, эта функция НЕ приближает — «почти
        совпал» есть та же выдумка, что и переводной множитель.

        `tol_mm` — допуск на сравнение ДВУХ ЧИСЕЛ В МИЛЛИМЕТРАХ, пришедших
        разными путями (программа пишет 100.0, документ хранит футы и
        переводит обратно). 0.5 мм выбран как половина наименьшего шага
        сортамента, а не как «мало»: соседние номиналы ДУ отстоят минимум на
        4 мм (ДУ6/ДУ8), то есть спутать два номинала этот допуск не может.
        """
        if (isinstance(nominal_mm, bool)
                or not isinstance(nominal_mm, (int, float))
                or not math.isfinite(float(nominal_mm))):
            return None
        target = float(nominal_mm)
        for nominal, outer in self.sizes:
            if abs(nominal - target) <= tol_mm:
                return outer
        return None


def prune_ground_snapshot(snapshot: Any) -> dict[str, Any]:
    """Снапшот -> только то, что нужно для ТЕЛА: отметки и сечения типов.

    Живёт здесь, потому что диалект снапшота принадлежит этому модулю, а
    носить целый снапшот через сессию нельзя: пул `family_symbols` бывает в
    тысячи строк, и 99% его полей (`unique_id`, `version_guid`, счётчики) на
    оболочку не влияют вовсе.

    Пустой словарь и ОТСУТСТВИЕ словаря — разные факты, и здесь они разные
    значения: пустой значит «спросили, сечений нет», отсутствие — «не
    спрашивали». Читатель обязан их различать.
    """
    if not isinstance(snapshot, Mapping):
        return {}
    out: dict[str, Any] = {}
    for pool, rows in snapshot.items():
        if not isinstance(pool, str) or not isinstance(rows, list):
            continue
        keep: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            if pool == "levels":
                if row.get("elevation_mm") is None:
                    continue
                keep.append({"id": row.get("id"), "name": row.get("name"),
                             "elevation_mm": row["elevation_mm"]})
            elif isinstance(row.get("section"), Mapping):
                keep.append({"id": row.get("id"), "name": row.get("name"),
                             "section": dict(row["section"])})
        if keep:
            out[pool] = keep
    return out


def required_grounding_pools() -> tuple[str, ...]:
    """Return the exact pool universe declared by the live OpSpec registry."""

    from kukai.ir import spec

    pools: set[str] = set()
    for op_spec in spec.OPS.values():
        for _param, pool, _required in op_spec.grounded:
            if "{category}" in pool:
                pools.update(pool.format(category=value) for value in (
                    "structural", "architectural"))
            else:
                pools.add(pool)
    # ``at_grid`` is a contour sublanguage selector, not an OpSpec parameter.
    pools.add("grids")
    return tuple(sorted(pools))


@dataclass(frozen=True, slots=True)
class ModelCatalogEntry:
    """One selectable Revit datum/type/symbol with exact live identity."""

    element_id: int
    name: str
    unique_id: str | None = None
    version_guid: str | None = None
    class_name: str | None = None
    category: str | None = None
    family_name: str | None = None
    type_name: str | None = None
    params_json: str | None = None
    p0_mm: tuple[float, float] | None = None
    p1_mm: tuple[float, float] | None = None
    #: Геометрия ТИПА (волна sections). НЕ входит в `binding_digest`: тот
    #: подписывает ИДЕНТИЧНОСТЬ строки, а сечение — её содержимое. Снапшот,
    #: снятый до этой волны, обязан дать тот же отпечаток, что и раньше.
    section: "TypeSection | None" = None
    #: Отметка уровня в мм — только у строк пула `levels`. Без неё программа,
    #: объявившая стену на уровне, не имеет НИ ОДНОЙ отметки Z, и тела у неё
    #: нет по построению, сколько бы толщин ни знал тип.
    elevation_mm: float | None = None

    def __post_init__(self) -> None:
        _element_id(self.element_id, "catalog_entry.element_id")
        _string(self.name, "catalog_entry.name")
        for field_name, value in (
            ("unique_id", self.unique_id),
            ("version_guid", self.version_guid),
            ("class_name", self.class_name),
            ("category", self.category),
            ("family_name", self.family_name),
            ("type_name", self.type_name),
        ):
            _optional_string(value, f"catalog_entry.{field_name}")
        if self.params_json is not None:
            _string(
                self.params_json, "catalog_entry.params_json", nonempty=True)
            try:
                parsed = json.loads(self.params_json)
            except (TypeError, ValueError) as exc:
                raise OpenModelProfileError(
                    "catalog_entry.params_json is invalid JSON") from exc
            canonical = _canonical_object_json(
                parsed, "catalog_entry.params_json")
            if canonical != self.params_json:
                raise OpenModelProfileError(
                    "catalog_entry.params_json must be canonical")
        _optional_vec2(self.p0_mm, "catalog_entry.p0_mm")
        _optional_vec2(self.p1_mm, "catalog_entry.p1_mm")
        if (self.p0_mm is None) != (self.p1_mm is None):
            raise OpenModelProfileError(
                "catalog entry grid endpoints must both be present or absent")
        if self.section is not None and not isinstance(
                self.section, TypeSection):
            raise OpenModelProfileError(
                "catalog_entry.section must be a typed TypeSection")
        if self.elevation_mm is not None and (
                isinstance(self.elevation_mm, bool)
                or not isinstance(self.elevation_mm, (int, float))
                or not math.isfinite(float(self.elevation_mm))):
            raise OpenModelProfileError(
                "catalog_entry.elevation_mm must be a finite number")

    @property
    def identity_exact(self) -> bool:
        return (
            self.unique_id is not None
            and self.version_guid is not None
            and _VERSION_GUID_RE.fullmatch(self.version_guid) is not None
        )

    @property
    def binding_digest(self) -> str:
        payload = {
            "element_id": self.element_id,
            "unique_id": self.unique_id,
            "version_guid": self.version_guid,
            "class_name": self.class_name,
            "category": self.category,
            "family_name": self.family_name,
            "type_name": self.type_name,
            "name": self.name,
        }
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @property
    def params(self) -> dict[str, Any] | None:
        return (
            None if self.params_json is None
            else json.loads(self.params_json)
        )

    def to_ground_row(self) -> dict[str, Any]:
        row: dict[str, Any] = {
            "id": self.element_id,
            "name": self.name,
        }
        for key, value in (
            ("unique_id", self.unique_id),
            ("version_guid", self.version_guid),
            ("class_name", self.class_name),
            ("category", self.category),
            ("family_name", self.family_name),
            ("type_name", self.type_name),
        ):
            if value is not None:
                row[key] = value
        if self.params_json is not None:
            row["params"] = self.params
        if self.p0_mm is not None:
            row["p0_mm"] = list(self.p0_mm)
            row["p1_mm"] = list(self.p1_mm or ())
        if self.section is not None:
            row["section"] = self.section.to_dict()
        if self.elevation_mm is not None:
            row["elevation_mm"] = float(self.elevation_mm)
        return row

    def to_dict(self) -> dict[str, Any]:
        row = {
            "element_id": self.element_id,
            "name": self.name,
            "unique_id": self.unique_id,
            "version_guid": self.version_guid,
            "class_name": self.class_name,
            "category": self.category,
            "family_name": self.family_name,
            "type_name": self.type_name,
            "params": self.params,
            "p0_mm": (
                list(self.p0_mm) if self.p0_mm is not None else None),
            "p1_mm": (
                list(self.p1_mm) if self.p1_mm is not None else None),
            "identity_exact": self.identity_exact,
            "binding_digest": self.binding_digest,
        }
        # ОТСУТСТВУЮЩЕЕ ОСТАЁТСЯ ОТСУТСТВУЮЩИМ. Остальные поля зануляются
        # (так было и так остаётся), а эти два ОПУСКАЮТСЯ: `digest` профиля
        # считается по этому же словарю, и `"section": null` сдвинул бы
        # отпечаток КАЖДОГО разбора, снятого до этой волны.
        if self.section is not None:
            row["section"] = self.section.to_dict()
        if self.elevation_mm is not None:
            row["elevation_mm"] = float(self.elevation_mm)
        return row

    @classmethod
    def from_ground_row(
        cls,
        value: Any,
        *,
        field_name: str = "catalog_entry",
    ) -> "ModelCatalogEntry":
        row = _mapping(value, field_name)
        return cls(
            element_id=_element_id(row.get("id"), f"{field_name}.id"),
            name=_string(row.get("name"), f"{field_name}.name"),
            unique_id=_optional_evidence_string(
                row.get("unique_id"), f"{field_name}.unique_id"),
            version_guid=_optional_evidence_string(
                row.get("version_guid"), f"{field_name}.version_guid"),
            class_name=_optional_evidence_string(
                row.get("class_name"), f"{field_name}.class_name"),
            category=_optional_evidence_string(
                row.get("category"), f"{field_name}.category"),
            family_name=_optional_evidence_string(
                row.get("family_name"), f"{field_name}.family_name"),
            type_name=_optional_evidence_string(
                row.get("type_name"), f"{field_name}.type_name"),
            params_json=_canonical_object_json(
                row.get("params"), f"{field_name}.params"),
            p0_mm=_optional_vec2(row.get("p0_mm"), f"{field_name}.p0_mm"),
            p1_mm=_optional_vec2(row.get("p1_mm"), f"{field_name}.p1_mm"),
            section=(
                None if row.get("section") is None
                else TypeSection.from_dict(
                    row["section"], field_name=f"{field_name}.section")),
            elevation_mm=row.get("elevation_mm"),
        )

    @classmethod
    def from_dict(
        cls,
        value: Any,
        *,
        field_name: str = "catalog_entry",
    ) -> "ModelCatalogEntry":
        row = _mapping(value, field_name)
        entry = cls.from_ground_row(
            {
                **row,
                "id": row.get("element_id", row.get("id")),
            },
            field_name=field_name,
        )
        if ("identity_exact" in row
                and _strict_bool(
                    row["identity_exact"], f"{field_name}.identity_exact")
                != entry.identity_exact):
            raise OpenModelProfileError(
                f"{field_name}.identity_exact mismatch")
        if ("binding_digest" in row
                and _string(
                    row["binding_digest"], f"{field_name}.binding_digest",
                    nonempty=True) != entry.binding_digest):
            raise OpenModelProfileError(
                f"{field_name}.binding_digest mismatch")
        return entry


@dataclass(frozen=True, slots=True)
class ModelCatalogPool:
    """A deterministically ordered catalog plus a completeness witness."""

    name: str
    entries: tuple[ModelCatalogEntry, ...]
    total_count: int | None
    truncated: bool

    def __post_init__(self) -> None:
        _string(self.name, "catalog_pool.name", nonempty=True)
        if (not isinstance(self.entries, tuple)
                or not all(isinstance(item, ModelCatalogEntry)
                           for item in self.entries)):
            raise OpenModelProfileError(
                "catalog_pool.entries must be a typed tuple")
        ids = tuple(item.element_id for item in self.entries)
        if ids != tuple(sorted(set(ids))):
            raise OpenModelProfileError(
                "catalog_pool.entries must be sorted by unique ElementId")
        if self.total_count is not None:
            _nonnegative_int(self.total_count, "catalog_pool.total_count")
            if self.total_count < len(self.entries):
                raise OpenModelProfileError(
                    "catalog_pool.total_count is below captured row count")
        _strict_bool(self.truncated, "catalog_pool.truncated")
        if (self.total_count is not None
                and self.total_count > len(self.entries)
                and not self.truncated):
            raise OpenModelProfileError(
                "incomplete catalog pool must declare truncated=true")
        if (self.total_count is not None
                and self.total_count == len(self.entries)
                and self.truncated):
            raise OpenModelProfileError(
                "complete catalog pool cannot declare truncated=true")

    @property
    def complete(self) -> bool:
        return (
            self.total_count is not None
            and self.total_count == len(self.entries)
            and not self.truncated
        )

    @property
    def identity_complete(self) -> bool:
        return all(item.identity_exact for item in self.entries)

    def entry(self, element_id: int) -> ModelCatalogEntry | None:
        return next(
            (item for item in self.entries if item.element_id == element_id),
            None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "entries": [item.to_dict() for item in self.entries],
            "captured_count": len(self.entries),
            "total_count": self.total_count,
            "truncated": self.truncated,
            "complete": self.complete,
            "identity_complete": self.identity_complete,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "ModelCatalogPool":
        row = _mapping(value, "catalog_pool")
        raw_entries = row.get("entries")
        if not isinstance(raw_entries, list):
            raise OpenModelProfileError(
                "catalog_pool.entries must be an array")
        entries = tuple(sorted(
            (
                ModelCatalogEntry.from_dict(
                    item, field_name=f"catalog_pool.entries[{index}]")
                for index, item in enumerate(raw_entries)
            ),
            key=lambda item: item.element_id,
        ))
        raw_total = row.get("total_count")
        pool = cls(
            name=_string(
                row.get("name"), "catalog_pool.name", nonempty=True),
            entries=entries,
            total_count=(
                None if raw_total is None
                else _nonnegative_int(
                    raw_total, "catalog_pool.total_count")
            ),
            truncated=_strict_bool(
                row.get("truncated", False), "catalog_pool.truncated"),
        )
        for field_name, actual in (
            ("captured_count", len(pool.entries)),
            ("complete", pool.complete),
            ("identity_complete", pool.identity_complete),
        ):
            if field_name not in row:
                continue
            supplied = (
                _nonnegative_int(row[field_name], f"catalog_pool.{field_name}")
                if field_name == "captured_count"
                else _strict_bool(
                    row[field_name], f"catalog_pool.{field_name}")
            )
            if supplied != actual:
                raise OpenModelProfileError(
                    f"catalog_pool.{field_name} mismatch")
        return pool


@dataclass(frozen=True, slots=True)
class OpenModelProfile:
    """Capabilities and exact selectable identities of one open document."""

    schema_version: str
    document_fingerprint: DocumentFingerprint | None
    revit_version: str
    revit_build: str | None
    required_pools: tuple[str, ...]
    pools: tuple[ModelCatalogPool, ...]
    revision_proof: RevisionProof | None = None

    def __post_init__(self) -> None:
        if self.schema_version != OPEN_MODEL_PROFILE_SCHEMA_VERSION:
            raise OpenModelProfileError(
                f"unsupported open model profile schema_version "
                f"{self.schema_version!r}")
        if (self.document_fingerprint is not None
                and not isinstance(
                    self.document_fingerprint, DocumentFingerprint)):
            raise OpenModelProfileError(
                "document_fingerprint must be typed or null")
        _string(self.revit_version, "open_model.revit_version")
        _optional_string(self.revit_build, "open_model.revit_build")
        required = _strings(
            self.required_pools, "open_model.required_pools")
        if required != tuple(sorted(required)):
            raise OpenModelProfileError(
                "open_model.required_pools must be sorted")
        if (not isinstance(self.pools, tuple)
                or not all(isinstance(item, ModelCatalogPool)
                           for item in self.pools)):
            raise OpenModelProfileError(
                "open_model.pools must be a typed tuple")
        names = tuple(item.name for item in self.pools)
        if names != tuple(sorted(set(names))):
            raise OpenModelProfileError(
                "open_model.pools must be sorted with unique names")
        if (self.revision_proof is not None
                and not isinstance(self.revision_proof, RevisionProof)):
            raise OpenModelProfileError(
                "open_model.revision_proof must be typed or null")

    @property
    def identity_bound(self) -> bool:
        fingerprint = self.document_fingerprint
        return bool(
            fingerprint is not None
            and fingerprint.title
            and (fingerprint.path_name or fingerprint.project_uid)
        )

    @property
    def grounding_complete(self) -> bool:
        by_name = {pool.name: pool for pool in self.pools}
        return all(
            name in by_name and by_name[name].complete
            for name in self.required_pools
        )

    @property
    def identity_complete(self) -> bool:
        by_name = {pool.name: pool for pool in self.pools}
        return all(
            name in by_name and by_name[name].identity_complete
            for name in self.required_pools
        )

    @property
    def authoritative(self) -> bool:
        return (
            self.identity_bound
            and self.grounding_complete
            and self.identity_complete
            and self.revision_proof is not None
        )

    def pool(self, name: str) -> ModelCatalogPool | None:
        return next((pool for pool in self.pools if pool.name == name), None)

    def _canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "document_fingerprint": (
                self.document_fingerprint.to_dict()
                if self.document_fingerprint is not None else None
            ),
            "revit_version": self.revit_version,
            "revit_build": self.revit_build,
            "required_pools": list(self.required_pools),
            "pools": [pool.to_dict() for pool in self.pools],
            "revision_proof": (
                self.revision_proof.to_dict()
                if self.revision_proof is not None else None
            ),
        }

    @property
    def digest(self) -> str:
        encoded = json.dumps(
            self._canonical_payload(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            **self._canonical_payload(),
            "identity_bound": self.identity_bound,
            "grounding_complete": self.grounding_complete,
            "identity_complete": self.identity_complete,
            "authoritative": self.authoritative,
            "digest": self.digest,
        }

    def to_ground_snapshot(self) -> dict[str, Any]:
        """Return the existing compiler snapshot dialect, deterministically."""

        result: dict[str, Any] = {}
        for pool in self.pools:
            result[pool.name] = [
                entry.to_ground_row() for entry in pool.entries]
            if pool.total_count is not None:
                result[pool.name + "__total"] = pool.total_count
            if pool.truncated:
                result[pool.name + "__truncated"] = True
        if self.document_fingerprint is not None:
            result["__document_fingerprint"] = (
                self.document_fingerprint.compiler_guard())
        result["__profile_schema_version"] = self.schema_version
        result["__profile_required_pools"] = list(self.required_pools)
        result["__revit_version"] = self.revit_version
        result["__revit_build"] = self.revit_build
        return result

    @classmethod
    def from_ground_snapshot(
        cls,
        value: Any,
        *,
        revision_proof: RevisionProof | None = None,
        required_pools: Sequence[str] | None = None,
    ) -> "OpenModelProfile":
        """Upgrade the current or legacy ground-snapshot wire shape."""

        row = _mapping(value, "ground_snapshot")
        explicit_version = row.get("__profile_schema_version")
        if (explicit_version is not None
                and explicit_version != OPEN_MODEL_PROFILE_SCHEMA_VERSION):
            raise OpenModelProfileError(
                f"unsupported open model profile schema_version "
                f"{explicit_version!r}")
        required = tuple(sorted(_strings(
            (
                required_pools
                if required_pools is not None
                else row.get(
                    "__profile_required_pools",
                    required_grounding_pools())
            ),
            "open_model.required_pools",
        )))
        pools: list[ModelCatalogPool] = []
        for name in required:
            raw_entries = row.get(name)
            if raw_entries is None:
                continue
            if not isinstance(raw_entries, list):
                raise OpenModelProfileError(
                    f"ground_snapshot.{name} must be an array")
            entries = tuple(sorted(
                (
                    ModelCatalogEntry.from_ground_row(
                        item,
                        field_name=(
                            f"ground_snapshot.{name}[{index}]"))
                    for index, item in enumerate(raw_entries)
                ),
                key=lambda item: item.element_id,
            ))
            raw_total = row.get(name + "__total")
            raw_truncated = row.get(name + "__truncated", False)
            pools.append(ModelCatalogPool(
                name=name,
                entries=entries,
                total_count=(
                    None if raw_total is None
                    else _nonnegative_int(
                        raw_total, f"ground_snapshot.{name}__total")
                ),
                truncated=_strict_bool(
                    raw_truncated,
                    f"ground_snapshot.{name}__truncated"),
            ))
        raw_fingerprint = row.get("__document_fingerprint")
        return cls(
            schema_version=OPEN_MODEL_PROFILE_SCHEMA_VERSION,
            document_fingerprint=(
                None if raw_fingerprint is None
                else DocumentFingerprint.from_dict(raw_fingerprint)
            ),
            revit_version=_string(
                row.get("__revit_version", ""),
                "open_model.revit_version"),
            revit_build=_optional_evidence_string(
                row.get("__revit_build"), "open_model.revit_build"),
            required_pools=required,
            pools=tuple(sorted(pools, key=lambda item: item.name)),
            revision_proof=revision_proof,
        )

    @classmethod
    def from_dict(cls, value: Any) -> "OpenModelProfile":
        row = _mapping(value, "open_model")
        version = row.get(
            "schema_version", OPEN_MODEL_PROFILE_SCHEMA_VERSION)
        if version != OPEN_MODEL_PROFILE_SCHEMA_VERSION:
            raise OpenModelProfileError(
                f"unsupported open model profile schema_version {version!r}")
        raw_pools = row.get("pools", [])
        if not isinstance(raw_pools, list):
            raise OpenModelProfileError("open_model.pools must be an array")
        raw_fingerprint = row.get("document_fingerprint")
        raw_revision = row.get("revision_proof")
        profile = cls(
            schema_version=OPEN_MODEL_PROFILE_SCHEMA_VERSION,
            document_fingerprint=(
                None if raw_fingerprint is None
                else DocumentFingerprint.from_dict(raw_fingerprint)
            ),
            revit_version=_string(
                row.get("revit_version", ""), "open_model.revit_version"),
            revit_build=_optional_evidence_string(
                row.get("revit_build"), "open_model.revit_build"),
            required_pools=tuple(sorted(_strings(
                row.get("required_pools", ()),
                "open_model.required_pools",
            ))),
            pools=tuple(sorted(
                (ModelCatalogPool.from_dict(item) for item in raw_pools),
                key=lambda item: item.name,
            )),
            revision_proof=(
                None if raw_revision is None
                else RevisionProof.from_dict(raw_revision)
            ),
        )
        for field_name, actual in (
            ("identity_bound", profile.identity_bound),
            ("grounding_complete", profile.grounding_complete),
            ("identity_complete", profile.identity_complete),
            ("authoritative", profile.authoritative),
        ):
            if (field_name in row
                    and _strict_bool(
                        row[field_name], f"open_model.{field_name}") != actual):
                raise OpenModelProfileError(
                    f"open_model.{field_name} mismatch")
        if ("digest" in row
                and _string(
                    row["digest"], "open_model.digest", nonempty=True)
                != profile.digest):
            raise OpenModelProfileError("open_model.digest mismatch")
        return profile


class PreflightIssueCode(str, Enum):
    PROFILE_POOL_MISSING = "profile_pool_missing"
    PROFILE_POOL_INCOMPLETE = "profile_pool_incomplete"
    PINNED_ELEMENT_MISSING = "pinned_element_missing"
    PINNED_IDENTITY_UNPROVEN = "pinned_identity_unproven"
    PINNED_IDENTITY_CHANGED = "pinned_identity_changed"
    DOCUMENT_IDENTITY_CHANGED = "document_identity_changed"


@dataclass(frozen=True, slots=True)
class ModelBinding:
    op_index: int
    op_id: str
    parameter: str
    pool: str
    element_id: int
    binding_digest: str
    unique_id: str | None
    version_guid: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "op_index": self.op_index,
            "op_id": self.op_id,
            "parameter": self.parameter,
            "pool": self.pool,
            "element_id": self.element_id,
            "binding_digest": self.binding_digest,
        }


@dataclass(frozen=True, slots=True)
class ModelPreflightIssue:
    code: PreflightIssueCode
    detail: str
    op_index: int | None = None
    op_id: str | None = None
    parameter: str | None = None
    pool: str | None = None
    element_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "code": self.code.value,
            "detail": self.detail,
        }
        for name, value in (
            ("op_index", self.op_index),
            ("op_id", self.op_id),
            ("parameter", self.parameter),
            ("pool", self.pool),
            ("element_id", self.element_id),
        ):
            if value is not None:
                result[name] = value
        return result


@dataclass(frozen=True, slots=True)
class OpenModelPreflight:
    profile_digest: str
    bindings: tuple[ModelBinding, ...]
    issues: tuple[ModelPreflightIssue, ...]

    @property
    def ready(self) -> bool:
        return not self.issues

    def exact_identity_proofs(self) -> tuple[ElementIdentityProof, ...]:
        """Return deduplicated transaction guards for a successful preflight."""

        if not self.ready:
            raise OpenModelProfileError(
                "cannot emit identity guards for a refused preflight")
        by_id: dict[int, ElementIdentityProof] = {}
        for binding in self.bindings:
            if binding.unique_id is None or binding.version_guid is None:
                raise OpenModelProfileError(
                    "preflight binding has no exact identity proof")
            try:
                proof = ElementIdentityProof(
                    element_id=binding.element_id,
                    unique_id=binding.unique_id,
                    version_guid=binding.version_guid,
                )
            except ContractSchemaError as exc:
                raise OpenModelProfileError(
                    "preflight binding identity proof is malformed") from exc
            prior = by_id.get(proof.element_id)
            if prior is not None and prior != proof:
                raise OpenModelProfileError(
                    "one ElementId has contradictory identity proofs")
            by_id[proof.element_id] = proof
        return tuple(by_id[element_id] for element_id in sorted(by_id))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": OPEN_MODEL_PREFLIGHT_SCHEMA_VERSION,
            "profile_digest": self.profile_digest,
            "ready": self.ready,
            "binding_count": len(self.bindings),
            "bindings": [item.to_dict() for item in self.bindings],
            "issue_count": len(self.issues),
            "issues": [item.to_dict() for item in self.issues],
        }


def _iter_program_ops(programs: Any) -> Iterable[tuple[int, Mapping[str, Any]]]:
    from kukai.ir import macros
    from kukai.ir.midend import PlannedProgram

    raw_programs = (
        [programs]
        if isinstance(programs, (Mapping, PlannedProgram))
        else programs
    )
    if (not isinstance(raw_programs, Sequence)
            or isinstance(raw_programs, (str, bytes, bytearray))):
        return ()
    flattened: list[tuple[int, Mapping[str, Any]]] = []
    global_index = 0
    for program in raw_programs:
        if isinstance(program, PlannedProgram):
            # The compiler already expanded, defaulted and validated this exact
            # immutable payload. Re-expanding its source would reopen drift.
            expanded = program.to_ops()
        else:
            if not isinstance(program, Mapping):
                continue
            raw_ops = program.get("ops")
            if not isinstance(raw_ops, list):
                continue
            try:
                expanded = macros.expand(raw_ops)
            except Exception:
                # Compiler validation owns malformed macro diagnostics.
                # Preflight must not replace them with a less useful model-
                # profile error.
                expanded = raw_ops
        for op in expanded:
            if isinstance(op, Mapping):
                flattened.append((global_index, op))
            global_index += 1
    return tuple(flattened)


def open_model_preflight_enabled() -> bool:
    """Opt-in gate for the open-model preflight on the LIVE write path; default OFF.

    Этот преflight — единственная fail-closed проверка здесь, которая может
    ОТКАЗАТЬ в записи там, где раньше запись проходила: ``ready`` требует
    пустого списка issues, а issue возникает, когда селектор ``element_id`` не
    находится в каталогах снапшота.  На УСЕЧЁННОМ снапшоте большой модели
    легитимный элемент может оказаться вне каталога — и получить отказ вместо
    записи.  Проверено это было только на синтетических фикстурах и моках моста,
    ни разу на живом Revit.

    Поэтому — как ``KUKAI_IR_NATIVE_GROUP`` и ``KUKAI_BRIDGE_IDENTITY_ACCEPT``:
    выключено по умолчанию, включается осознанно.  При выключенном флаге путь
    деградирует РОВНО в прежнее поведение (сырой снапшот как есть), а не в
    какое-то новое.
    """

    return os.getenv("KUKAI_IR_OPEN_MODEL_PREFLIGHT", "").strip().lower() in {
        "1", "true", "yes", "on",
    }


def preflight_programs(
    programs: Any,
    profile: OpenModelProfile,
    *,
    expected_profile: OpenModelProfile | None = None,
    require_exact_identity: bool = False,
) -> OpenModelPreflight:
    """Check every pinned grounding selector before any Revit transaction.

    Name/default selectors remain owned by ``ground.py``.  This fills its one
    intentional gap: an ``element_id`` selector historically skipped the
    snapshot and was only null-checked inside the transaction.  For
    ``same_document`` rebuilds an optional source ``expected_profile`` also
    proves that the id was not reused or semantically changed.
    """

    if not isinstance(profile, OpenModelProfile):
        raise OpenModelProfileError("profile must be OpenModelProfile")
    if (expected_profile is not None
            and not isinstance(expected_profile, OpenModelProfile)):
        raise OpenModelProfileError(
            "expected_profile must be OpenModelProfile or null")
    issues: list[ModelPreflightIssue] = []
    bindings: list[ModelBinding] = []

    if expected_profile is not None:
        if (profile.document_fingerprint is None
                or expected_profile.document_fingerprint is None
                or profile.document_fingerprint
                != expected_profile.document_fingerprint):
            issues.append(ModelPreflightIssue(
                code=PreflightIssueCode.DOCUMENT_IDENTITY_CHANGED,
                detail="target open document differs from source profile",
            ))

    from kukai.ir import spec

    for op_index, op in _iter_program_ops(programs):
        op_name = op.get("op")
        op_spec = spec.OPS.get(op_name) if isinstance(op_name, str) else None
        if op_spec is None:
            continue
        op_id = str(op.get("id") or f"op{op_index}")
        for parameter, pool_template, _required in op_spec.grounded:
            if (op_spec.name == "create_foundation"
                    and ((parameter == "symbol"
                          and op.get("variety") != "isolated")
                         or (parameter == "type"
                             and op.get("variety") != "slab"))):
                continue
            selector = op.get(parameter)
            if not isinstance(selector, Mapping):
                continue
            grounded = selector.get("__grounded__")
            if isinstance(grounded, Mapping):
                # A post-ground compiler pass covers by=name/family_type too.
                # Intra-program refs and document defaults have no pre-existing
                # ElementId and are guarded by their dedicated emit path.
                if grounded.get("via") == "ref":
                    continue
                raw_id = grounded.get("id")
                if raw_id is None:
                    continue
            elif selector.get("by") == "element_id":
                raw_id = selector.get("value")
            else:
                continue
            try:
                pinned_id = _element_id(
                    raw_id, f"{op_id}.{parameter}.value")
            except OpenModelProfileError:
                # Compiler selector validation owns malformed values.
                continue
            pool_name = (
                pool_template.format(
                    category=op.get("category", "structural"))
                if "{category}" in pool_template else pool_template
            )
            pool = profile.pool(pool_name)
            common = {
                "op_index": op_index,
                "op_id": op_id,
                "parameter": parameter,
                "pool": pool_name,
                "element_id": pinned_id,
            }
            if pool is None:
                issues.append(ModelPreflightIssue(
                    code=PreflightIssueCode.PROFILE_POOL_MISSING,
                    detail=f"open model profile has no {pool_name} pool",
                    **common,
                ))
                continue
            legacy_count_unproven = (
                pool.total_count is None and not pool.truncated)
            if not pool.complete and (
                    require_exact_identity or not legacy_count_unproven):
                issues.append(ModelPreflightIssue(
                    code=PreflightIssueCode.PROFILE_POOL_INCOMPLETE,
                    detail=f"open model profile pool {pool_name} is incomplete",
                    **common,
                ))
                continue
            entry = pool.entry(pinned_id)
            if entry is None:
                issues.append(ModelPreflightIssue(
                    code=PreflightIssueCode.PINNED_ELEMENT_MISSING,
                    detail=(
                        f"ElementId {pinned_id} is absent from {pool_name}"),
                    **common,
                ))
                continue
            if require_exact_identity and not entry.identity_exact:
                issues.append(ModelPreflightIssue(
                    code=PreflightIssueCode.PINNED_IDENTITY_UNPROVEN,
                    detail=(
                        f"ElementId {pinned_id} has no UniqueId/VersionGuid "
                        "identity proof"),
                    **common,
                ))
                continue
            if expected_profile is not None:
                expected_pool = expected_profile.pool(pool_name)
                expected = (
                    expected_pool.entry(pinned_id)
                    if expected_pool is not None else None
                )
                if (expected is None
                        or not expected.identity_exact
                        or expected.binding_digest != entry.binding_digest):
                    issues.append(ModelPreflightIssue(
                        code=PreflightIssueCode.PINNED_IDENTITY_CHANGED,
                        detail=(
                            f"ElementId {pinned_id} identity differs from "
                            "the source profile"),
                        **common,
                    ))
                    continue
            bindings.append(ModelBinding(
                op_index=op_index,
                op_id=op_id,
                parameter=parameter,
                pool=pool_name,
                element_id=pinned_id,
                binding_digest=entry.binding_digest,
                unique_id=entry.unique_id,
                version_guid=entry.version_guid,
            ))

    return OpenModelPreflight(
        profile_digest=profile.digest,
        bindings=tuple(bindings),
        issues=tuple(issues),
    )


async def capture_open_model_profile(
    executor: Any,
    *,
    timeout_ms: int = 30_000,
    revision_proof: RevisionProof | None = None,
) -> OpenModelProfile:
    """Capture one profile through a bridge-shaped async executor.

    A pipeline revision guard may wrap ``executor``; in that case it returns
    the read payload directly.  Plain serving executors commonly return one or
    more ``{"result": ...}`` envelopes, which are unwrapped conservatively.
    """

    if not callable(executor):
        raise OpenModelProfileError("profile executor must be callable")
    if (isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int)
            or timeout_ms <= 0):
        raise OpenModelProfileError(
            "profile timeout_ms must be a positive integer")
    value = await executor(GROUND_SNAPSHOT_CS, timeout_ms=timeout_ms)
    for _ in range(3):
        if not isinstance(value, Mapping):
            break
        if value.get("ok") is False or value.get("error"):
            raise OpenModelProfileError(
                "open model profile bridge read failed")
        nested = value.get("result")
        if not isinstance(nested, Mapping):
            break
        value = nested
    if not isinstance(value, Mapping):
        raise OpenModelProfileError(
            "open model profile bridge payload must be an object")
    return OpenModelProfile.from_ground_snapshot(
        value, revision_proof=revision_proof)


# Read-only ground-snapshot collector (version-safe 2021-2026; C# 7.3).
# The top-level pool dialect is unchanged.  ``__*`` metadata and per-row exact
# identity fields are additive; old compiler/ground consumers ignore them.
GROUND_SNAPSHOT_CS = r"""
Func<Element, long> __Id = (Element __e) => { try { return long.Parse(__e.Id.ToString()); } catch { return -1; } };
Func<double, double> __MM = (double __ft) => UnitUtils.ConvertFromInternalUnits(__ft, UnitTypeId.Millimeters);
// НАЗВАННОЕ УМОЛЧАНИЕ (замер 02.08.2026, Snowdon): сколько экземпляров каждого
// типоразмера УЖЕ РАЗМЕЩЕНО в этом документе. Без этого числа ground не может
// назвать правило «самый употребимый», и единственным исходом на 62 кандидатах
// остаётся отказ — при том, что плечо C# в том же документе взяло 1 тип из 62
// молча. Один проход по экземплярам: типов в каталоге тысячи, но правило
// опирается на ПРАКТИКУ проекта, а её знают только размещённые элементы.
// long.Parse(...ToString()) — тот же версионно-нейтральный приём, что и __Id:
// целочисленное свойство ElementId сменило имя и тип в 2024+, а ToString()
// одинаков на всех шести (страж test_open_model держит это правило подстрокой,
// поэтому старое имя нельзя даже упоминать — и это правильно).
var __instCount = new Dictionary<long, int>();
try
{
    foreach (var __fi in new FilteredElementCollector(doc).OfClass(typeof(FamilyInstance)))
    {
        long __tid;
        try { __tid = long.Parse(__fi.GetTypeId().ToString()); } catch { continue; }
        if (__tid <= 0) continue;
        int __prev;
        __instCount[__tid] = __instCount.TryGetValue(__tid, out __prev) ? __prev + 1 : 1;
    }
}
catch { }
// ─────────────────────────────────────────────────────────────────────────
// СЕЧЕНИЕ ТИПА (волна sections, 09.08.2026). ЗАЧЕМ: замер по реестру
// (`spec.OPS`, 48 операций) — НИ ОДНА операция создания не несёт толщину
// стены, перекрытия или сечение колонны. Они живут в ТИПЕ, а тип разрешается
// против живого документа ровно здесь. До этой волны строка пула несла
// `{id, name}`, и потому `kukai/clash/` не мог построить тело НИ ОДНОМУ
// заявленному элементу: на двух реальных зданиях — ноль оболочек.
//
// ВСЕ ЧЛЕНЫ НИЖЕ СКОМПИЛИРОВАНЫ НА ШЕСТИ ВЕРСИЯХ (:52412, 09.08.2026):
//   Level.Elevation                              2021-2026 6/6
//   WallType.Width, WallType.Kind                2021-2026 6/6
//   HostObjAttributes.GetCompoundStructure       2021-2026 6/6
//   CompoundStructure.GetWidth                   2021-2026 6/6
//   CompoundStructure.IsVerticallyHomogeneous()  2021-2026 6/6
//   CompoundStructure.GetWallSweepsInfo(WallSweepType)  2021-2026 6/6
//   CompoundStructure.VariableLayerIndex         2021-2026 6/6
//   CompoundStructure.HasStructuralDeck          2021-2026 6/6
//   PipeType.RoutingPreferenceManager            2021-2026 6/6
//   RoutingPreferenceManager.GetNumberOfRules/GetRule   2021-2026 6/6
//   PipeSegment.GetSizes / MEPSize.Nominal|OuterDiameter 2021-2026 6/6
//   BuiltInParameter.STRUCTURAL_SECTION_COMMON_*  2021-2026 6/6
// Версионно-условных чтений здесь поэтому НЕТ: тело снапшота одно на все
// шесть, и отсутствующий на 2021 член сломал бы весь снапшот целиком.
//
// ЧЕГО ЗДЕСЬ НЕТ И ПОЧЕМУ. У ЛОТКА сечения на типе не существует ни в одной
// из шести версий: `CableTrayType` несёт только `BendMultiplier`,
// `IsWithFitting`, `ShapeType` (сверено по RevitAPI.xml и компиляцией), а
// `Autodesk.Revit.DB.Electrical.CableTraySizeSettings` не существует вовсе
// (CS0234 на всех шести). Ширина и высота лотка — параметры ЭКЗЕМПЛЯРА, и
// `CableTray.Create(doc, typeId, p0, p1, levelId)` их не принимает. Значит
// молчание тут честное: тела у лотка нет не потому, что снапшот беден, а
// потому, что ни операция, ни тип его не выражают.
Func<Element, BuiltInParameter, double> __ParamMM =
    (Element __pe, BuiltInParameter __bip) =>
{
    try
    {
        var __p = __pe.get_Parameter(__bip);
        if (__p == null || !__p.HasValue
            || __p.StorageType != StorageType.Double) return 0.0;
        return __MM(__p.AsDouble());
    }
    catch { return 0.0; }
};
Func<Element, string, Dictionary<string, object>> __Section =
    (Element __e, string __cat) =>
{
    var __sec = new Dictionary<string, object>();
    var __blk = new List<string>();
    // 1. СТЕНА. Толщина есть, но одного числа МАЛО: у наклонной, ступенчатой
    //    и составной по высоте стены призма по толщине тело НЕ содержит, то
    //    есть допускает пропуск клеша. Поэтому число едет вместе с приговором.
    var __wt = __e as WallType;
    if (__wt != null)
    {
        double __ww = 0.0;
        try { __ww = __MM(__wt.Width); } catch { }
        if (!(__ww > 0.0)) return null;
        __sec["kind"] = "plate";
        __sec["source"] = "WallType.Width";
        __sec["thickness_mm"] = __ww;
        try { if (__wt.Kind != WallKind.Basic)
                  __blk.Add("wall_kind_" + __wt.Kind.ToString()); }
        catch { __blk.Add("wall_kind_unreadable"); }
        try
        {
            var __cs = __wt.GetCompoundStructure();
            if (__cs == null) __blk.Add("compound_structure_absent");
            else
            {
                if (!__cs.IsVerticallyHomogeneous())
                    __blk.Add("vertically_compound");
                if (__cs.GetWallSweepsInfo(WallSweepType.Sweep).Count > 0)
                    __blk.Add("wall_sweeps");
                if (__cs.GetWallSweepsInfo(WallSweepType.Reveal).Count > 0)
                    __blk.Add("wall_reveals");
                if (__cs.VariableLayerIndex >= 0) __blk.Add("variable_layer");
            }
        }
        catch { __blk.Add("compound_structure_unreadable"); }
        if (__blk.Count == 0) __sec["uniform"] = true;
        else { __blk.Sort(); __sec["blockers"] = __blk.ToArray(); }
        return __sec;
    }
    // 2. ПЛИТА (перекрытие / потолок / кровля) — общий предок
    //    `HostObjAttributes`. Стена сюда не доходит: она разобрана выше.
    var __ho = __e as HostObjAttributes;
    if (__ho != null)
    {
        CompoundStructure __cs2 = null;
        try { __cs2 = __ho.GetCompoundStructure(); } catch { }
        if (__cs2 == null) return null;
        double __th = 0.0;
        try { __th = __MM(__cs2.GetWidth()); } catch { }
        if (!(__th > 0.0)) return null;
        __sec["kind"] = "plate";
        __sec["source"] = "HostObjAttributes.GetCompoundStructure().GetWidth";
        __sec["thickness_mm"] = __th;
        try { if (__cs2.VariableLayerIndex >= 0) __blk.Add("variable_layer"); }
        catch { __blk.Add("variable_layer_unreadable"); }
        try { if (__cs2.HasStructuralDeck) __blk.Add("structural_deck"); }
        catch { }
        if (__blk.Count == 0) __sec["uniform"] = true;
        else { __blk.Sort(); __sec["blockers"] = __blk.ToArray(); }
        return __sec;
    }
    // 3. ТРУБА: таблица «номинал -> НАРУЖНЫЙ», напечатанная самим документом.
    //    Ни одного переводного множителя здесь нет и быть не может: у ДУ100
    //    номинал 100, наружный 114.3, и вывести второе из первого нельзя
    //    ничем, кроме сортамента. Когда один номинал приходит от нескольких
    //    сегментов (сталь и медь в одних правилах), берётся БОЛЬШИЙ наружный:
    //    огрубление вверх законно, выбор одного из двух — нет.
    var __pt2 = __e as Autodesk.Revit.DB.Plumbing.PipeType;
    if (__pt2 != null)
    {
        var __nominals = new List<double>();
        var __outers = new Dictionary<double, double>();
        try
        {
            var __rpm = __pt2.RoutingPreferenceManager;
            int __nr = __rpm == null ? 0 : __rpm.GetNumberOfRules(
                RoutingPreferenceRuleGroupType.Segments);
            for (int __i = 0; __i < __nr; __i++)
            {
                var __rule = __rpm.GetRule(
                    RoutingPreferenceRuleGroupType.Segments, __i);
                if (__rule == null) continue;
                var __segEl = doc.GetElement(__rule.MEPPartId)
                    as Autodesk.Revit.DB.Plumbing.PipeSegment;
                if (__segEl == null) continue;
                foreach (MEPSize __z in __segEl.GetSizes())
                {
                    double __nom = __MM(__z.NominalDiameter);
                    double __out = __MM(__z.OuterDiameter);
                    if (!(__nom > 0.0) || !(__out > 0.0)) continue;
                    double __prev;
                    if (!__outers.TryGetValue(__nom, out __prev))
                    { __outers[__nom] = __out; __nominals.Add(__nom); }
                    else if (__prev < __out) __outers[__nom] = __out;
                }
            }
        }
        catch { }
        if (__nominals.Count == 0) return null;
        __nominals.Sort();
        var __pairs = new List<object>();
        bool __trunc = false;
        foreach (double __nom in __nominals)
        {
            if (__pairs.Count >= 64) { __trunc = true; break; }
            __pairs.Add(new double[] { __nom, __outers[__nom] });
        }
        __sec["kind"] = "nominal_table";
        __sec["source"] =
            "PipeType.RoutingPreferenceManager+PipeSegment.GetSizes";
        __sec["sizes"] = __pairs;
        if (__trunc) __sec["sizes_truncated"] = true;
        return __sec;
    }
    // 4. НЕСУЩИЙ ПРОФИЛЬ у типоразмера семейства. Спрашивается ТОЛЬКО у
    //    несущих категорий: пул `family_symbols` собирается без сужения и
    //    насчитывает тысячи строк, а три чтения на каждую окупаются лишь
    //    там, где ответ бывает.
    if (__cat == "OST_StructuralColumns" || __cat == "OST_Columns"
        || __cat == "OST_StructuralFraming"
        || __cat == "OST_StructuralFoundation")
    {
        var __fsy = __e as FamilySymbol;
        if (__fsy != null)
        {
            double __dia = __ParamMM(
                __fsy, BuiltInParameter.STRUCTURAL_SECTION_COMMON_DIAMETER);
            double __sw = __ParamMM(
                __fsy, BuiltInParameter.STRUCTURAL_SECTION_COMMON_WIDTH);
            double __sh = __ParamMM(
                __fsy, BuiltInParameter.STRUCTURAL_SECTION_COMMON_HEIGHT);
            if (__dia > 0.0)
            {
                __sec["kind"] = "round";
                __sec["source"] = "STRUCTURAL_SECTION_COMMON_DIAMETER";
                __sec["diameter_mm"] = __dia;
                __sec["uniform"] = true;
            }
            else if (__sw > 0.0 && __sh > 0.0)
            {
                __sec["kind"] = "rect";
                __sec["source"] =
                    "STRUCTURAL_SECTION_COMMON_WIDTH+HEIGHT";
                __sec["width_mm"] = __sw;
                __sec["height_mm"] = __sh;
                __sec["uniform"] = true;
            }
            else return null;
            // СОБСТВЕННЫЙ ГАБАРИТ ТИПОРАЗМЕРА ПО Z. Замер 09.08 на Snowdon:
            // 4 колонны из 114 выходили за оболочку ровно на 254.0 мм ВНИЗ, и
            // все четыре — одного типоразмера. База семейства уходит ниже
            // своей отметки, и знать об этом может только сам типоразмер.
            try
            {
                var __bb = __fsy.get_BoundingBox(null);
                if (__bb != null)
                {
                    __sec["local_z_min_mm"] = __MM(__bb.Min.Z);
                    __sec["local_z_max_mm"] = __MM(__bb.Max.Z);
                }
            }
            catch { }
            return __sec;
        }
    }
    return null;
};
var __ParamNames = new string[0];
var __snap = new Dictionary<string, object>();
Action<string, System.Collections.Generic.IEnumerable<Element>, int> __AddPool =
    (string __pool, System.Collections.Generic.IEnumerable<Element> __els, int __limit) =>
{
    var __rows = new List<object>();
    int __total = 0;
    foreach (var __e in __els.OrderBy(__x => __Id(__x)))
    {
        // audit F7: count PAST the cap so a truncated pool is marked, never
        // silently passed off as the whole catalog (ground refuses default/
        // sole-entry on a truncated pool and says so on NOT_FOUND).
        __total++;
        if (__rows.Count >= __limit) continue;
        var __r = new Dictionary<string, object>();
        __r["id"] = __Id(__e);
        try { __r["name"] = __e.Name ?? ""; } catch { __r["name"] = ""; }
        try { __r["unique_id"] = __e.UniqueId ?? ""; } catch { __r["unique_id"] = ""; }
        try { __r["version_guid"] = __e.VersionGuid.ToString("N"); } catch { __r["version_guid"] = ""; }
        try { __r["class_name"] = __e.ToString() ?? ""; } catch { __r["class_name"] = ""; }
        string __catName = "";
        try
        {
            var __category = __e.Category;
            if (__category != null)
            {
                int __categoryId;
                if (Int32.TryParse(__category.Id.ToString(), out __categoryId))
                {
                    __catName = Enum.GetName(
                        typeof(BuiltInCategory), __categoryId)
                        ?? __categoryId.ToString();
                    __r["category"] = __catName;
                }
            }
        }
        catch { }
        // Отметка УРОВНЯ. Без неё программа, объявившая стену на уровне, не
        // имеет ни одной отметки Z, и тела у неё нет по построению — сколько
        // бы толщин ни знал тип. Ключ появляется только у строк пула levels.
        var __lvl = __e as Level;
        if (__lvl != null)
        {
            try { __r["elevation_mm"] = __MM(__lvl.Elevation); } catch { }
        }
        try
        {
            var __secRow = __Section(__e, __catName);
            if (__secRow != null) __r["section"] = __secRow;
        }
        catch { }
        var __fs = __e as FamilySymbol;
        if (__fs != null)
        {
            try { __r["family_name"] = __fs.FamilyName ?? ""; } catch { }
            try { __r["type_name"] = __fs.Name ?? ""; } catch { }
            // Ноль — ЗНАЧИМОЕ значение, а не отсутствие: правило требует
            // счётчик на КАЖДОЙ строке пула, иначе максимум по неполным
            // данным — утверждение, которого мы доказать не можем, и
            // ground.py осознанно откажется его делать.
            int __used;
            __r["instances"] = __instCount.TryGetValue(__Id(__e), out __used)
                ? __used : 0;
        }
        if (__ParamNames.Length > 0)
        {
            var __params = new Dictionary<string, object>();
            foreach (var __paramName in __ParamNames)
            {
                System.Collections.Generic.IList<Parameter> __matches = null;
                try { __matches = __e.GetParameters(__paramName); } catch { }
                // Duplicate display names are ambiguous too.  Omitting the
                // value makes ground.py refuse; never pick the first.
                if (__matches == null || __matches.Count != 1) continue;
                var __p = __matches[0];
                if (__p == null || !__p.HasValue) continue;
                var __pv = new Dictionary<string, object>();
                __pv["storage_type"] = __p.StorageType.ToString();
                try
                {
                    var __display = __p.AsValueString();
                    if (__display != null) __pv["display"] = __display;
                }
                catch { }
                try
                {
                    if (__p.StorageType == StorageType.String)
                        __pv["value"] = __p.AsString();
                    else if (__p.StorageType == StorageType.Integer)
                        __pv["value"] = __p.AsInteger();
                    else if (__p.StorageType == StorageType.Double)
                        __pv["raw"] = __p.AsDouble();
                    else if (__p.StorageType == StorageType.ElementId)
                        __pv["value"] = __p.AsElementId().ToString();
                }
                catch { continue; }
                __params[__paramName] = __pv;
            }
            __r["params"] = __params;
        }
        __rows.Add(__r);
    }
    __snap[__pool] = __rows;
    __snap[__pool + "__total"] = __total;
    if (__total > __limit) __snap[__pool + "__truncated"] = true;
};
__AddPool("levels", new FilteredElementCollector(doc).OfClass(typeof(Level)).Cast<Element>(), 1000);
__AddPool("phases", new FilteredElementCollector(doc).OfClass(typeof(Phase)).Cast<Element>(), 1000);
__AddPool("materials", new FilteredElementCollector(doc).OfClass(typeof(Material)).Cast<Element>(), 1000);
__AddPool("wall_types", new FilteredElementCollector(doc).OfClass(typeof(WallType)).Cast<Element>(), 1000);
__AddPool("floor_types", new FilteredElementCollector(doc).OfClass(typeof(FloorType)).Cast<Element>(), 1000);
__AddPool("pipe_types", new FilteredElementCollector(doc).OfClass(typeof(Autodesk.Revit.DB.Plumbing.PipeType)).Cast<Element>(), 1000);
__AddPool("piping_system_types", new FilteredElementCollector(doc).OfClass(typeof(Autodesk.Revit.DB.Plumbing.PipingSystemType)).Cast<Element>(), 1000);
__AddPool("column_symbols_structural", new FilteredElementCollector(doc).OfClass(typeof(FamilySymbol)).OfCategory(BuiltInCategory.OST_StructuralColumns).Cast<Element>(), 1000);
__AddPool("column_symbols_architectural", new FilteredElementCollector(doc).OfClass(typeof(FamilySymbol)).OfCategory(BuiltInCategory.OST_Columns).Cast<Element>(), 1000);
__AddPool("window_symbols", new FilteredElementCollector(doc).OfClass(typeof(FamilySymbol)).OfCategory(BuiltInCategory.OST_Windows).Cast<Element>(), 1000);
__AddPool("door_symbols", new FilteredElementCollector(doc).OfClass(typeof(FamilySymbol)).OfCategory(BuiltInCategory.OST_Doors).Cast<Element>(), 1000);
__AddPool("family_symbols", new FilteredElementCollector(doc).OfClass(typeof(FamilySymbol)).Cast<Element>(), int.MaxValue);
__AddPool("roof_types", new FilteredElementCollector(doc).OfClass(typeof(RoofType)).Cast<Element>(), 1000);
__AddPool("duct_types", new FilteredElementCollector(doc).OfClass(typeof(Autodesk.Revit.DB.Mechanical.DuctType)).Cast<Element>(), 1000);
__AddPool("duct_system_types", new FilteredElementCollector(doc).OfClass(typeof(Autodesk.Revit.DB.Mechanical.MechanicalSystemType)).Cast<Element>(), 1000);
__AddPool("cable_tray_types", new FilteredElementCollector(doc).OfClass(typeof(Autodesk.Revit.DB.Electrical.CableTrayType)).Cast<Element>(), 1000);
// wave/mep-electrical (2026-08-09): пулы короба и двух гибких типов.
// Собираются ПО КЛАССУ, как pipe/duct/cable-tray выше: ConduitType,
// FlexDuctType и FlexPipeType — самостоятельные классы ElementType
// (существование каждого проверено компиляцией на 2021-2026), и фильтр по
// классу возвращает ровно их. Категорийный фильтр здесь был бы хуже:
// OST_Conduit несёт и сами короба, и их типы.
__AddPool("conduit_types", new FilteredElementCollector(doc).OfClass(typeof(Autodesk.Revit.DB.Electrical.ConduitType)).Cast<Element>(), 1000);
__AddPool("flex_duct_types", new FilteredElementCollector(doc).OfClass(typeof(Autodesk.Revit.DB.Mechanical.FlexDuctType)).Cast<Element>(), 1000);
__AddPool("flex_pipe_types", new FilteredElementCollector(doc).OfClass(typeof(Autodesk.Revit.DB.Plumbing.FlexPipeType)).Cast<Element>(), 1000);
// beam_types фильтруется по ТИПУ РАЗМЕЩЕНИЯ, в отличие от остальных пулов
// символов. Замерено 27.07: все 36 семейств каркаса реального здания —
// FamilyPlacementType.OneLevelBased (точечные), а create_beam эмитит
// NewFamilyInstance(Line, …, StructuralType.Beam), который на точечном
// семействе возвращает null. Факт известен здесь, на ground — значит здесь и
// должен приводить к честному KIR-G104 «пусто в модели», а не к рантайм-null
// с сообщением про исчезнувший тип. Для окон/дверей/колонн точечное
// размещение — норма, их пулы не трогаем.
__AddPool("beam_types", new FilteredElementCollector(doc).OfClass(typeof(FamilySymbol)).OfCategory(BuiltInCategory.OST_StructuralFraming).Cast<FamilySymbol>().Where(__bfs => { try { var __pt = __bfs.Family.FamilyPlacementType; return __pt == FamilyPlacementType.CurveDrivenStructural || __pt == FamilyPlacementType.CurveBased; } catch { return false; } }).Cast<Element>(), 1000);
__AddPool("foundation_symbols", new FilteredElementCollector(doc).OfClass(typeof(FamilySymbol)).OfCategory(BuiltInCategory.OST_StructuralFoundation).Cast<Element>(), 1000);
// wave/arch (2026-07-29): пулы типов потолка и ограждения. Оба собираются
// ПО КЛАССУ, а не по категории: CeilingType и RailingType — самостоятельные
// классы ElementType (существование обоих проверено компиляцией на 2021-2026),
// и фильтр по классу возвращает ровно их, без примеси системных типов.
// У ограждения это единственный способ вообще узнать список типов:
// ElementTypeGroup.RailingType не существует ни на одной версии (замерено),
// то есть спросить документ «а какой тип по умолчанию» нельзя в принципе.
// wave/wall-foundation (2026-08-09): типы ленточного фундамента. По КЛАССУ,
// как потолок и ограждение: WallFoundationType — самостоятельный класс
// ElementType (компиляция 2021-2026, 6/6), и WallFoundation.Create не примет
// ничего другого. В отличие от ограждения, документный тип по умолчанию у
// него ЕСТЬ: ElementTypeGroup.WallFoundationType компилируется на всех шести.
__AddPool("wall_foundation_types", new FilteredElementCollector(doc).OfClass(typeof(WallFoundationType)).Cast<Element>(), 1000);
// wave/analysis (2026-08-09): случаи загружения и три типа нагрузок.
// ТИПЫ — ПО КЛАССУ, как труба/воздуховод/лоток выше: PointLoadType,
// LineLoadType и AreaLoadType — самостоятельные классы ElementType
// (существование каждого проверено компиляцией на 2021-2026), и фильтр по
// классу возвращает ровно их. Категорийный фильтр здесь был бы хуже:
// OST_PointLoads несёт и сами нагрузки, и их типы.
//
// load_cases — пул ЭКЗЕМПЛЯРОВ (как levels и grids), а не типов: случай
// загружения это элемент проекта, и заземляться по нему обязаны все три
// нагрузки. Природы (LoadNature) здесь НЕТ: их вход — операция создания
// СЛУЧАЯ, которой в этой волне нет, а пул без селектора нарушил бы правило
// «пул существует ради заземления» (см. ops_analysis.py).
__AddPool("load_cases", new FilteredElementCollector(doc).OfClass(typeof(Autodesk.Revit.DB.Structure.LoadCase)).Cast<Element>(), 1000);
__AddPool("point_load_types", new FilteredElementCollector(doc).OfClass(typeof(Autodesk.Revit.DB.Structure.PointLoadType)).Cast<Element>(), 1000);
__AddPool("line_load_types", new FilteredElementCollector(doc).OfClass(typeof(Autodesk.Revit.DB.Structure.LineLoadType)).Cast<Element>(), 1000);
__AddPool("area_load_types", new FilteredElementCollector(doc).OfClass(typeof(Autodesk.Revit.DB.Structure.AreaLoadType)).Cast<Element>(), 1000);
// wave/framing (2026-08-09): типы ферм. ПО КЛАССУ, как потолок, ограждение и
// ленточный фундамент: TrussType — самостоятельный класс (компиляция 2021-2026,
// 6/6), и Truss.Create принимает ТОЛЬКО его id. Категорийный фильтр был бы
// хуже: OST_Truss держит и сами фермы, и их типы. Отдельного пула балочной
// системе НЕ ЗАВЕДЕНО — её символ балки это обычный beam_types, тот же пул и
// тот же фильтр по типу размещения, что у create_beam.
__AddPool("truss_types", new FilteredElementCollector(doc).OfClass(typeof(FamilySymbol)).OfCategory(BuiltInCategory.OST_Truss).Cast<Element>(), 1000);
// wave/reinforcement (2026-08-10): три пула армирования по области. ВСЕ ТРИ
// ПО КЛАССУ, как ферма и ленточный фундамент: AreaReinforcementType,
// RebarBarType и RebarHookType — самостоятельные классы ElementType
// (компиляция 2021-2026, 6/6), и AreaReinforcement.Create проверяет КАЖДЫЙ
// аргумент на свой класс отдельно. Категорийный фильтр здесь был бы хуже:
// OST_Rebar держит и стержни, и их типы, а OST_AreaRein — и системы, и типы.
__AddPool("area_reinforcement_types", new FilteredElementCollector(doc).OfClass(typeof(Autodesk.Revit.DB.Structure.AreaReinforcementType)).Cast<Element>(), 1000);
__AddPool("rebar_bar_types", new FilteredElementCollector(doc).OfClass(typeof(Autodesk.Revit.DB.Structure.RebarBarType)).Cast<Element>(), 1000);
__AddPool("rebar_hook_types", new FilteredElementCollector(doc).OfClass(typeof(Autodesk.Revit.DB.Structure.RebarHookType)).Cast<Element>(), 1000);
__AddPool("ceiling_types", new FilteredElementCollector(doc).OfClass(typeof(CeilingType)).Cast<Element>(), 1000);
__AddPool("railing_types", new FilteredElementCollector(doc).OfClass(typeof(Autodesk.Revit.DB.Architecture.RailingType)).Cast<Element>(), 1000);
// wave/site (2026-08-09): типы площадки под здание и толщи рельефа.
//
// ПЛОЩАДКА собирается ПО КЛАССУ, как все остальные: BuildingPadType — тип
// ElementType, существующий на всех шести версиях (замерено компиляцией).
//
// ТОЛЩА — единственный пул этого файла, который НЕ МОЖЕТ назвать свой класс.
// `ToposolidType` появился только в 2024 (на 2021/2022 это CS0246, на 2023 —
// CS0122: тип есть, но internal), а это ТЕЛО ОДНО НА ВСЕ ШЕСТЬ ВЕРСИЙ: оно
// не эмитируется под версию, значит любое упоминание имени не собралось бы
// на половине флота и утащило бы за собой ВЕСЬ снапшот, то есть все
// остальные пулы вместе с ним. Поэтому фильтр идёт по ИМЕНИ ТИПА CLR у
// общего предка HostObjAttributes (BuildingPadType/FloorType/RoofType/
// WallType/CeilingType/ToposolidType — все его наследники; проверено
// присваиванием). На 2021-2023 совпадений нет по построению, и пул честно
// пуст — то есть create_topography(variety=toposolid) там получит KIR-G104
// «пусто в модели», ровно на тех версиях, где эта операция и так отказывает
// по оси версий. Категорией это сделать НЕЛЬЗЯ: BuiltInCategory.OST_Toposolid
// появился в 2023, на ГОД раньше самого класса, то есть имя категории версию
// не различает.
__AddPool("building_pad_types", new FilteredElementCollector(doc).OfClass(typeof(BuildingPadType)).Cast<Element>(), 1000);
// wave/sweep (2026-08-09). ДВА ПУЛА, СОБРАННЫЕ ПО-РАЗНОМУ, И РАЗНИЦА — ЗАМЕР.
// `SlabEdgeType` — настоящий класс ElementType (компиляция 6/6), поэтому пул
// краевых профилей идёт ПО КЛАССУ, как wall_foundation_types.
// А вот класса `WallSweepType`-как-ElementType НЕ СУЩЕСТВУЕТ: `WallSweepType`
// это ПЕРЕЧИСЛЕНИЕ {Sweep, Reveal} (замерено), и тип профиля живёт обычным
// ElementType в OST_Cornices (карнизы) либо OST_Reveals (русты). Поэтому
// единственный возможный сбор — по ДВУМ категориям, одним пулом: разделить их
// на два пула нельзя, потому что `grounded` в реестре статичен, а тип у
// операции один параметр.
__AddPool("wall_sweep_types", new FilteredElementCollector(doc).WherePasses(new ElementMulticategoryFilter(new List<BuiltInCategory> { BuiltInCategory.OST_Cornices, BuiltInCategory.OST_Reveals })).WhereElementIsElementType().Cast<Element>(), 1000);
__AddPool("slab_edge_types", new FilteredElementCollector(doc).OfClass(typeof(SlabEdgeType)).Cast<Element>(), 1000);
// СТРОКОЙ, А НЕ typeof — И ЭТО ЗАПИСЬ О ВЕРСИОННОМ ЗАПРЕТЕ. Не пишите здесь
// typeof(ToposolidType): класса НЕТ в эталонных сборках 2021-2023 (проверено
// по поверхности API всех шести), и снапшот перестанет собираться на трёх
// версиях из шести. Сравнение имени — единственная форма, компилирующаяся
// везде.
//
// СЛЕДСТВИЕ, стоившее живого прогона 13.08.2026: на 2021-2023 этот пул пуст
// ВСЕГДА, в любом документе. Отказ «пусто в модели» там был бы ложью и звал
// бы автора заводить тип, которого на его Ревите не бывает, — поэтому версия
// отвечает РАНЬШЕ заземления (`ops_site.toposolid_version_refusal`, зовётся
// из `compiler` до стадии ground). Знание о запрете жило здесь, в
// исполняемом виде, и не переходило одну границу.
__AddPool("toposolid_types", new FilteredElementCollector(doc).OfClass(typeof(HostObjAttributes)).Cast<Element>().Where(__tse => { try { return __tse.GetType().Name == "ToposolidType"; } catch { return false; } }), 1000);
// wave/detail (2026-08-09): типы заливки. ПО КЛАССУ, как все остальные:
// FilledRegionType — самостоятельный тип ElementType, существующий на всех
// шести версиях (замерено компиляцией). Категорией это делать НЕЛЬЗЯ:
// OST_FilledRegion держит и сами заливки (элементы вида), и их типы, то есть
// категорийный фильтр вернул бы пул, половина которого не является типом и
// отвергается самим `FilledRegion.IsValidFilledRegionTypeId`.
__AddPool("filled_region_types", new FilteredElementCollector(doc).OfClass(typeof(FilledRegionType)).Cast<Element>(), 1000);
// РАБОЧИЕ НАБОРЫ. Кладутся ОТДЕЛЬНО, а не через __AddPool, и это не стиль:
// `Workset` НЕ наследует `Element`, поэтому `Cast<Element>()` к нему неприменим,
// а коллектор у него свой. Замерено по индексу ловушек 13.08.2026 на шести
// версиях; `Parameter.Set(WorksetId)` не существует (CS1503 6/6), набор
// адресуется ЦЕЛЫМ `WorksetId.IntegerValue`.
var __worksets = new List<object>();
try
{
    if (doc.IsWorkshared)
    {
        foreach (Workset __w in new FilteredWorksetCollector(doc).ToWorksets().Take(1000))
        {
            var __wr = new Dictionary<string, object>();
            __wr["id"] = __w.Id.IntegerValue;
            try { __wr["name"] = __w.Name ?? ""; } catch { __wr["name"] = ""; }
            try { __wr["kind"] = __w.Kind.ToString(); } catch { __wr["kind"] = ""; }
            __worksets.Add(__wr);
        }
    }
}
catch { }
// НЕ РАЗДЕЛЁННЫЙ ДОКУМЕНТ ДАЁТ ПУСТОЙ ПУЛ, А НЕ ОТСУТСТВУЮЩИЙ КЛЮЧ: пустой
// читается как «наборов нет», отсутствующий — как «мы не спрашивали», и это
// разные утверждения. Различает их `worksets__workshared`.
__snap["worksets"] = __worksets;
__snap["worksets__workshared"] = doc.IsWorkshared;
var __gridQuery = new FilteredElementCollector(doc).OfClass(typeof(Grid))
    .Cast<Grid>().OrderBy(__x => __Id(__x)).ToList();
var __grids = new List<object>();
foreach (Grid __g in __gridQuery.Take(1000))
{
    var __r = new Dictionary<string, object>();
    __r["id"] = __Id(__g);
    try { __r["name"] = __g.Name ?? ""; } catch { __r["name"] = ""; }
    try { __r["unique_id"] = __g.UniqueId ?? ""; } catch { __r["unique_id"] = ""; }
    try { __r["version_guid"] = __g.VersionGuid.ToString("N"); } catch { __r["version_guid"] = ""; }
    try { __r["class_name"] = __g.ToString() ?? ""; } catch { __r["class_name"] = ""; }
    try
    {
        var __line = __g.Curve as Line;
        if (__line != null)
        {
            var __p0 = __line.GetEndPoint(0); var __p1 = __line.GetEndPoint(1);
            __r["p0_mm"] = new double[] { __MM(__p0.X), __MM(__p0.Y) };
            __r["p1_mm"] = new double[] { __MM(__p1.X), __MM(__p1.Y) };
        }
    }
    catch { }
    __grids.Add(__r);
}
__snap["grids"] = __grids;
__snap["grids__total"] = __gridQuery.Count;
if (__gridQuery.Count > 1000) __snap["grids__truncated"] = true;
var __documentFingerprint = new Dictionary<string, object>();
try { __documentFingerprint["title"] = doc.Title ?? ""; } catch { __documentFingerprint["title"] = ""; }
try { __documentFingerprint["path_name"] = doc.PathName ?? ""; } catch { __documentFingerprint["path_name"] = ""; }
try
{
    __documentFingerprint["project_uid"] = doc.ProjectInformation == null
        ? "" : (doc.ProjectInformation.UniqueId ?? "");
}
catch { __documentFingerprint["project_uid"] = ""; }
__snap["__document_fingerprint"] = __documentFingerprint;
__snap["__profile_schema_version"] = "open-model-profile/1";
__snap["__profile_required_pools"] = new string[] {
    "area_reinforcement_types",
    "beam_types", "building_pad_types", "cable_tray_types", "ceiling_types",
    "column_symbols_architectural",
    "rebar_bar_types", "rebar_hook_types",
    "column_symbols_structural", "conduit_types", "door_symbols",
    "duct_system_types",
    "area_load_types",
    "duct_types", "family_symbols", "filled_region_types",
    "flex_duct_types", "flex_pipe_types",
    "floor_types", "foundation_symbols",
    "grids", "levels", "line_load_types", "load_cases", "pipe_types",
    "piping_system_types", "point_load_types", "railing_types",
    "roof_types", "slab_edge_types", "toposolid_types", "truss_types",
    "wall_foundation_types",
    "materials",
    "phases",
    "worksets",
    "wall_sweep_types", "wall_types", "window_symbols"
};
try { __snap["__revit_version"] = doc.Application.VersionNumber ?? ""; }
catch { __snap["__revit_version"] = ""; }
try { __snap["__revit_build"] = doc.Application.VersionBuild ?? ""; }
catch { __snap["__revit_build"] = null; }
return __snap;
""".strip("\n")


__all__ = [
    "GROUND_SNAPSHOT_CS",
    "ModelBinding",
    "ModelCatalogEntry",
    "ModelCatalogPool",
    "ModelPreflightIssue",
    "OPEN_MODEL_PREFLIGHT_SCHEMA_VERSION",
    "OPEN_MODEL_PROFILE_SCHEMA_VERSION",
    "OpenModelPreflight",
    "OpenModelProfile",
    "OpenModelProfileError",
    "PreflightIssueCode",
    "SECTION_KINDS",
    "SECTION_MAX_SIZES",
    "TypeSection",
    "capture_open_model_profile",
    "preflight_programs",
    "prune_ground_snapshot",
    "required_grounding_pools",
]
