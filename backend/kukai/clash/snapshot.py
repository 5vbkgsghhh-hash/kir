"""ClashGeometrySnapshot — вход детектора, а не «программа плюс ground».

Ревью P0 №1: пока входом называется «KIR + существующий ground», непонятно,
что именно судится и что осталось за кадром. Снапшот отвечает на это явно —
он несёт (а) оболочки, (б) счётчики непокрытого, (в) отпечаток происхождения,
и его перепись обязана сходиться:

    eligible = hulled + unsupported + missing_geometry

Расхождение — не предупреждение, а ошибка: детектор, у которого половина
здания молча выпала, найдёт ноль клешей и будет выглядеть исправным.
"""

from __future__ import annotations

import collections
import hashlib
import json
import math
import pathlib
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from kukai.clash import geom as G
from kukai.clash import hulls as H

SCHEMA_VERSION = "clash-geometry-snapshot/2"


class SnapshotIntegrityError(RuntimeError):
    """Вход недоказуем: перепись не сходится, поток обрезан, id дублируются.

    Ревью №10/№11: и то и другое раньше было тихим. Файл, обрезанный на
    КОРРЕКТНОЙ json-строке, давал внутренне сходящуюся перепись — «всё в
    порядке» на половине здания. Детектор, у которого половина модели молча
    выпала, найдёт ноль клешей и будет выглядеть исправным, поэтому это
    исключение, а не предупреждение.
    """


FEDERATION_COVERAGE_SCHEMA = "clash-federation-coverage/1"


def _sha256_json(value: Mapping[str, Any]) -> str:
    try:
        payload = json.dumps(
            value, ensure_ascii=False, allow_nan=False, sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise SnapshotIntegrityError(
            "federation coverage is not canonical JSON") from exc
    return hashlib.sha256(payload).hexdigest()


def _typed_string_list(value: Any, name: str) -> list[str]:
    if (not isinstance(value, list)
            or any(not isinstance(item, str) or not item for item in value)
            or value != sorted(value)
            or len(value) != len(set(value))):
        raise SnapshotIntegrityError(
            f"federation coverage {name} must be sorted unique strings")
    return value


def _federation_coverage_axis(
    coverage: Any,
    *,
    records: Iterable[H.HullRecord],
    refusals: Iterable[H.Refusal],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate the sealed graph/hull accounting before exposing green axes."""

    if not isinstance(coverage, Mapping):
        raise SnapshotIntegrityError(
            "origin.federation_coverage must be an object")
    wire = dict(coverage)
    digest = wire.pop("content_digest", None)
    if (not isinstance(digest, str) or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
            or _sha256_json(wire) != digest):
        raise SnapshotIntegrityError(
            "federation coverage content digest mismatch")
    required = {
        "schema_version", "federation_root", "graph_content_digest",
        "hull_set_content_digest", "scope_id", "scope_occurrences",
        "hulled_occurrences", "geometry_refusal_occurrences",
        "scope_census", "graph_complete", "complete", "graph_gaps",
        "node_refusals", "graph_refusals", "source_row_refusals",
        "incomplete_link_resolutions", "geometry_transform_gaps",
    }
    if set(wire) != required:
        raise SnapshotIntegrityError(
            "federation coverage has an unsupported field set")
    if wire["schema_version"] != FEDERATION_COVERAGE_SCHEMA:
        raise SnapshotIntegrityError(
            "unsupported federation coverage schema")
    for name in ("federation_root", "scope_id"):
        if not isinstance(wire[name], str) or not wire[name]:
            raise SnapshotIntegrityError(
                f"federation coverage {name} must be non-empty")
    for name in ("graph_content_digest", "hull_set_content_digest"):
        value = wire[name]
        if (not isinstance(value, str) or len(value) != 64
                or any(char not in "0123456789abcdef" for char in value)):
            raise SnapshotIntegrityError(
                f"federation coverage {name} must be sha256")
    scope = _typed_string_list(
        wire["scope_occurrences"], "scope_occurrences")
    hulled = _typed_string_list(
        wire["hulled_occurrences"], "hulled_occurrences")
    refused_occurrences = _typed_string_list(
        wire["geometry_refusal_occurrences"],
        "geometry_refusal_occurrences")
    if set(hulled).intersection(refused_occurrences) \
            or set(scope) != set(hulled).union(refused_occurrences):
        raise SnapshotIntegrityError(
            "federation scope is not exactly hull-or-refusal accounted")
    census = wire["scope_census"]
    if not isinstance(census, Mapping) or set(census) != {
            "occurrences", "hulled", "refused"}:
        raise SnapshotIntegrityError(
            "federation coverage scope_census is malformed")
    for name, expected in (
        ("occurrences", len(scope)),
        ("hulled", len(hulled)),
        ("refused", len(refused_occurrences)),
    ):
        value = census[name]
        if (isinstance(value, bool) or not isinstance(value, int)
                or value < 0 or value != expected):
            raise SnapshotIntegrityError(
                "federation coverage scope census does not balance")

    list_fields = (
        "graph_gaps", "node_refusals", "graph_refusals",
        "source_row_refusals", "incomplete_link_resolutions",
        "geometry_transform_gaps",
    )
    for name in list_fields:
        if not isinstance(wire[name], list):
            raise SnapshotIntegrityError(
                f"federation coverage {name} must be an array")
    graph_complete = not any(wire[name] for name in list_fields[:-1])
    if (not isinstance(wire["graph_complete"], bool)
            or wire["graph_complete"] != graph_complete):
        raise SnapshotIntegrityError(
            "federation graph completeness contradicts named gaps")
    complete = graph_complete and not wire["geometry_transform_gaps"]
    if not isinstance(wire["complete"], bool) or wire["complete"] != complete:
        raise SnapshotIntegrityError(
            "federation completeness contradicts named gaps")

    actual_records = sorted(record.source_id for record in records)
    if actual_records != hulled:
        raise SnapshotIntegrityError(
            "federation coverage hulled occurrences differ from snapshot")
    expected_refusals: dict[str, tuple[str, str]] = {}
    keyed_gap_occurrences: list[str] = []
    for index, row in enumerate(wire["geometry_transform_gaps"]):
        if not isinstance(row, Mapping) or set(row) != {
                "snapshot_refusal_id", "gap"}:
            raise SnapshotIntegrityError(
                "federation geometry gap row is malformed")
        refusal_id = row["snapshot_refusal_id"]
        gap = row["gap"]
        if (not isinstance(refusal_id, str) or not refusal_id
                or refusal_id in expected_refusals
                or not isinstance(gap, Mapping)):
            raise SnapshotIntegrityError(
                "federation geometry gap refusal identity is invalid")
        category = gap.get("category")
        reason = gap.get("reason")
        occurrence = gap.get("occurrence_key")
        if (not isinstance(category, str) or not category
                or not isinstance(reason, str) or not reason):
            raise SnapshotIntegrityError(
                "federation geometry gap lost category or reason")
        if occurrence is not None:
            if not isinstance(occurrence, str) or not occurrence:
                raise SnapshotIntegrityError(
                    "federation geometry gap occurrence key is invalid")
            keyed_gap_occurrences.append(occurrence)
        expected_refusals[refusal_id] = (
            category, f"federation:{reason}")
    if sorted(keyed_gap_occurrences) != refused_occurrences:
        raise SnapshotIntegrityError(
            "federation coverage keyed geometry refusals disagree")
    actual_refusals: dict[str, tuple[str, str]] = {}
    for refusal in refusals:
        if refusal.source_id in actual_refusals:
            raise SnapshotIntegrityError(
                "federation snapshot has duplicate refusal identities")
        if refusal.bucket != "missing_geometry":
            raise SnapshotIntegrityError(
                "federation geometry gaps must stay missing_geometry refusals")
        actual_refusals[refusal.source_id] = (
            refusal.category, refusal.reason)
    if actual_refusals != expected_refusals:
        raise SnapshotIntegrityError(
            "federation geometry gaps differ from snapshot refusals")

    extraction_complete = not any(wire[name] for name in (
        "node_refusals", "graph_refusals", "source_row_refusals"))
    extraction_axis = {
        "complete": extraction_complete,
        "graph_refusals": wire["graph_refusals"],
        "node_refusals": wire["node_refusals"],
        "source_row_refusals": wire["source_row_refusals"],
        "note": (
            "complete only when every source graph and node entering the "
            "federation has an authoritative occurrence address"),
    }
    federation_axis = {
        **wire,
        "content_digest": digest,
        "note": (
            "complete only when graph assembly, expected links, occurrence "
            "scope accounting, and source-to-root geometry transforms have "
            "no named gaps"),
    }
    return extraction_axis, federation_axis


@dataclass
class Census:
    """Счётчики по классам. Все четыре публикуются всегда, включая нули."""
    eligible: collections.Counter = field(default_factory=collections.Counter)
    hulled: collections.Counter = field(default_factory=collections.Counter)
    unsupported: collections.Counter = field(default_factory=collections.Counter)
    missing_geometry: collections.Counter = field(default_factory=collections.Counter)
    not_eligible: collections.Counter = field(default_factory=collections.Counter)
    reasons: collections.Counter = field(default_factory=collections.Counter)
    #: Ревью №10. Живой замер фасада: header census = 30 489 элементов, а
    #: element-строк в L0 — 3 153. Разница НЕ обязана быть пригодной к поиску,
    #: но обязана быть НАЗВАНА: иначе знаменатель любого процента не доказан.
    outside_extraction_scope: int = 0
    #: ЭЛЕМЕНТЫ связанных файлов, оболочек не получившие. Сумма `element_count`
    #: по строкам `link`, а НЕ число самих строк.
    #:
    #: ДО 11.08.2026 ЗДЕСЬ ЛЕЖАЛО ЧИСЛО СВЯЗЕЙ. Имя говорило «элементы», код
    #: присваивал `origin["links_in_l0"]`, и модель с тремя связями по сорок
    #: тысяч элементов отчитывалась тройкой — величина объявлена в одном месте,
    #: прочитана в другом, совпасть их ничто не заставляло. Настоящее число при
    #: этом было ЗАМЕРЕНО и выброшено строкой рядом: экстрактор кладёт в строку
    #: связи `element_count` с `GetLinkDocument()`, а читатель строку не
    #: открывал вовсе.
    linked_elements_unscored: int = 0
    #: Связи, у которых числа элементов ПРОЧИТАТЬ НЕ УДАЛОСЬ (файл не
    #: загружен — `GetLinkDocument()` пуст, `element_count` остаётся `null`).
    #:
    #: ОТДЕЛЬНОЕ ЧИСЛО, А НЕ НОЛЬ В СУММЕ. «В связи ноль элементов» и «число
    #: элементов связи не прочитано» — разные утверждения; сложить их значит
    #: заменить одну ложь другой, ровно тем же приёмом, каким счётчик выше
    #: врал до сегодняшнего дня.
    links_without_element_count: int = 0
    #: ── сечения (волна D2-A). Знаменатель — `eligible` тех категорий, которым
    #: источник `axis_section` РАЗРЕШЁН. Стены сюда не входят: у них число
    #: есть, а разрешения нет, и складывать одно с другим значит спрятать
    #: запрет за отсутствием данных.
    section_present: collections.Counter = field(default_factory=collections.Counter)
    section_absent: collections.Counter = field(default_factory=collections.Counter)
    #: Сколько оболочек РЕАЛЬНО построено сечением. Всегда `<= present`:
    #: разница — элементы с числом, но с непригодной осью (нулевая длина,
    #: битая дуга), и она уже названа в `reasons`/`downgraded_from`.
    section_hulled: collections.Counter = field(default_factory=collections.Counter)
    #: Элементы, у которых число сечения В L0 ЕСТЬ, а таблица пользоваться им
    #: запрещает (стена, балка, колонна, гибкая трасса — ревью №2/№3/№10).
    #: На фасаде SOB6.2 это главное число волны: сечение снято, подъёма нет, и
    #: причина — ЗАПРЕТ, а не отсутствие данных.
    section_blocked: collections.Counter = field(default_factory=collections.Counter)
    #: R3 красных: у элемента прочитан только НОМИНАЛЬНЫЙ диаметр. Капсула по
    #: нему тела не содержит (ДУ100: 50.0 против наружного 57.15), поэтому
    #: оболочкой становится габарит. Число обязано быть НАЗВАНО: без него
    #: «капсул мало» неотличимо от «труб мало».
    section_nominal_only: collections.Counter = field(
        default_factory=collections.Counter)
    #: R5 красных: элементы стороны MVP, оставшиеся БЕЗ оболочки. Стена,
    #: которой нет в поиске, — гарантированный пропуск всего, что сквозь неё
    #: проходит; отчёт с 783 невидимыми элементами выглядел исправным.
    no_hull_mvp_side: collections.Counter = field(
        default_factory=collections.Counter)
    #: Покрытие по стороне MVP: сколько пригодно и сколько реально захолмлено.
    mvp_eligible: collections.Counter = field(default_factory=collections.Counter)
    mvp_hulled: collections.Counter = field(default_factory=collections.Counter)
    #: Те же элементы без оболочки, но по КАТЕГОРИЯМ — чтобы «поиск неполон»
    #: называл виновника, а не только число.
    no_hull_by_category: collections.Counter = field(
        default_factory=collections.Counter)
    #: ВЫРОЖДЕННЫЕ оболочки: тело нулевого объёма (`hulls.hull_degeneracy`).
    #: Оболочка нулевого объёма не может доказать клеш — её пары ничего не
    #: значат, — но и нарушением закона содержания она не является, пока в
    #: данных нет независимого свидетеля протяжённости. Поэтому счётчик, а не
    #: отказ: 9.7 % склада (замер 10.08.2026) обязаны быть ВИДНЫ.
    degenerate_hulls: collections.Counter = field(
        default_factory=collections.Counter)
    degenerate_by_category: dict = field(
        default_factory=lambda: collections.defaultdict(collections.Counter))
    #: Типы, у которых сечения не оказалось: `category -> {type_name}`.
    #: Один битый элемент и целый тип без параметра — разные диагнозы, и
    #: счётчик элементов их не различает.
    types_without_section: dict = field(
        default_factory=lambda: collections.defaultdict(set))

    def totals(self) -> dict[str, int]:
        return {"eligible": sum(self.eligible.values()),
                "hulled": sum(self.hulled.values()),
                "unsupported": sum(self.unsupported.values()),
                "missing_geometry": sum(self.missing_geometry.values()),
                "not_eligible": sum(self.not_eligible.values()),
                "outside_extraction_scope": self.outside_extraction_scope,
                "linked_elements_unscored": self.linked_elements_unscored,
                "links_without_element_count": self.links_without_element_count}

    def balanced(self) -> bool:
        t = self.totals()
        return t["eligible"] == t["hulled"] + t["unsupported"] + t["missing_geometry"]

    def unbalanced_categories(self) -> dict[str, dict]:
        """Ревью №11: глобальный баланс позволял дефициту одной категории
        компенсироваться избытком другой. Сходиться обязана КАЖДАЯ строка."""
        bad = {}
        for cat in (set(self.eligible) | set(self.hulled) | set(self.unsupported)
                    | set(self.missing_geometry)):
            e = self.eligible.get(cat, 0)
            got = (self.hulled.get(cat, 0) + self.unsupported.get(cat, 0)
                   + self.missing_geometry.get(cat, 0))
            if e != got:
                bad[cat] = {"eligible": e, "accounted": got}
        return bad

    def section_categories(self) -> list[str]:
        """Категории, у которых сечение вообще имеет смысл спрашивать.

        Список ЗАКРЫТ таблицей, а не наблюдением: модель без единой трубы
        обязана показать «0 из 0», а не пустой блок, который читается как
        «не спрашивали».
        """
        return sorted(set(H.SECTION_RULES) | set(self.section_present)
                      | set(self.section_absent))

    def unbalanced_section_categories(self) -> dict[str, dict]:
        """Тот же закон переписи, что у оболочек: `present + absent` обязано
        равняться `eligible` КАЖДОЙ категории, где сечение разрешено. Иначе
        «сечений нет» неотличимо от «не спрашивали»."""
        bad = {}
        for cat in self.section_categories():
            e = self.eligible.get(cat, 0)
            got = self.section_present.get(cat, 0) + self.section_absent.get(cat, 0)
            if e != got:
                bad[cat] = {"eligible": e, "asked": got}
        return bad

    def sections_as_dict(self) -> dict:
        cats = self.section_categories()
        return {
            "totals": {"present": sum(self.section_present.values()),
                       "absent": sum(self.section_absent.values()),
                       "hulled": sum(self.section_hulled.values())},
            "balanced": not self.unbalanced_section_categories(),
            "unbalanced_categories": self.unbalanced_section_categories(),
            "by_category": {
                cat: {"present": self.section_present.get(cat, 0),
                      "absent": self.section_absent.get(cat, 0),
                      "hulled": self.section_hulled.get(cat, 0),
                      "eligible": self.eligible.get(cat, 0)}
                for cat in cats},
            "nominal_only_total": sum(self.section_nominal_only.values()),
            "nominal_only_by_category": dict(
                sorted(self.section_nominal_only.items())),
            "nominal_only_note": (
                "прочитан только НОМИНАЛЬНЫЙ диаметр (R3 красных): капсула по "
                "нему тела не содержит, поэтому оболочкой стал габарит. "
                "Наружный — RBS_PIPE_OUTER_DIAMETER / "
                "RBS_CONDUIT_OUTER_DIAM_PARAM."),
            "blocked_by_table": dict(sorted(self.section_blocked.items())),
            "blocked_total": sum(self.section_blocked.values()),
            "blocked_note": (
                "число сечения в L0 ЕСТЬ, но таблица запрещает категории им "
                "обосновывать оболочку (стена/балка/колонна/гибкая трасса — "
                "ревью №2, №3, №10). Ноль подъёмов здесь означает ЗАПРЕТ, "
                "а не отсутствие данных."),
            "types_without_section_count": sum(
                len(v) for v in self.types_without_section.values()),
            "types_without_section": {
                cat: sorted(names)
                for cat, names in sorted(self.types_without_section.items())
                if names},
        }

    def as_dict(self) -> dict:
        return {
            "totals": self.totals(),
            "balanced": self.balanced(),
            "unbalanced_categories": self.unbalanced_categories(),
            "by_category": {
                cat: {"eligible": self.eligible.get(cat, 0),
                      "hulled": self.hulled.get(cat, 0),
                      "unsupported": self.unsupported.get(cat, 0),
                      "missing_geometry": self.missing_geometry.get(cat, 0),
                      "not_eligible": self.not_eligible.get(cat, 0)}
                for cat in sorted(set(self.eligible) | set(self.not_eligible)
                                  | set(self.unsupported) | set(self.missing_geometry))
            },
            "reasons": dict(sorted(self.reasons.items())),
            "degenerate_hulls": self.degeneracy_as_dict(),
            "sections": self.sections_as_dict(),
            "mvp_side_coverage": self.mvp_side_coverage(),
        }

    def degeneracy_as_dict(self) -> dict:
        """Оболочки нулевого объёма. Публикуется ВСЕГДА, включая ноль:
        «вырожденных нет» и «не считали» обязаны выглядеть по-разному."""
        total = sum(v for k, v in self.degenerate_hulls.items() if k != "ok")
        hulled = sum(self.hulled.values())
        return {
            "total": total,
            "hulled": hulled,
            "share": round(total / hulled, 6) if hulled else 0.0,
            "by_kind": {k: self.degenerate_hulls.get(k, 0)
                        for k in H.DEGENERACIES if k != "ok"},
            "by_category": {cat: dict(sorted(v.items()))
                            for cat, v in sorted(self.degenerate_by_category.items())
                            if v},
            "note": ("оболочка нулевого объёма НЕ МОЖЕТ доказать клеш. "
                     "Нарушением закона содержания она при этом не является: "
                     "независимого свидетеля протяжённости у этих элементов в "
                     "данных нет (замер 10.08.2026: 67 108 из 67 108 без "
                     "свидетеля), поэтому здесь счётчик, а не отказ."),
        }

    def mvp_side_coverage(self) -> dict:
        """Покрытие оболочками ПО СТОРОНЕ MVP (R5 красных).

        Отдельно от общей переписи намеренно: «доля трассы без оболочки» —
        то число, которое из отчёта нельзя было получить вовсе, а именно оно
        решает, имеет ли смысл читать список находок.
        """
        return {
            side: {"eligible": self.mvp_eligible.get(side, 0),
                   "hulled": self.mvp_hulled.get(side, 0),
                   "without_hull": self.no_hull_mvp_side.get(side, 0)}
            for side in ("mep", "struct")
        }


@dataclass
class ClashGeometrySnapshot:
    records: list[H.HullRecord]
    census: Census
    origin: dict
    refusals: list[H.Refusal] = field(default_factory=list)

    def by_grade(self) -> dict[str, int]:
        c = collections.Counter(r.grade for r in self.records)
        return {g: c.get(g, 0) for g in H.GRADES}

    def mvp_records(self) -> list[H.HullRecord]:
        return [r for r in self.records if r.mvp_side in H.MVP_PAIR]

    def coverage_axes(self, *, geometry_scope: str) -> dict[str, dict]:
        """Independent input-coverage facts for a clash query.

        A balanced hull census proves only that every *extracted* eligible
        row was accounted for.  It does not prove that the extractor saw the
        whole host document, that linked-model geometry was federated, or
        that every element relevant to the requested query received a usable
        hull.  Keep those claims separate so that one green counter cannot
        mask a red one.

        ``geometry_scope`` is deliberately small and typed.  ``mvp`` means
        the two sides of the production MEP-vs-structure query;
        ``all_eligible`` means every physical row admitted by the category
        table (the diagnostic all-pairs query).
        """
        if geometry_scope == "mvp":
            eligible = sum(self.census.mvp_eligible.values())
            hulled = sum(self.census.mvp_hulled.values())
            without_hull = sum(self.census.no_hull_mvp_side.values())
            by_side = {
                side: {
                    "eligible": self.census.mvp_eligible.get(side, 0),
                    "hulled": self.census.mvp_hulled.get(side, 0),
                    "without_hull": self.census.no_hull_mvp_side.get(side, 0),
                }
                for side in ("mep", "struct")
            }
            by_category_without_hull = dict(
                sorted(self.census.no_hull_by_category.items()))
            degenerate = sum(
                count
                for category, by_kind in self.census.degenerate_by_category.items()
                if ((H.KIND_TABLE.get(category) is not None)
                    and H.KIND_TABLE[category].mvp_side in H.MVP_PAIR)
                for count in by_kind.values())
        elif geometry_scope == "all_eligible":
            totals = self.census.totals()
            eligible = totals["eligible"]
            hulled = totals["hulled"]
            without_hull = totals["unsupported"] + totals["missing_geometry"]
            by_side = {}
            by_category_without_hull = {
                category: (self.census.unsupported.get(category, 0)
                           + self.census.missing_geometry.get(category, 0))
                for category in sorted(
                    set(self.census.unsupported)
                    | set(self.census.missing_geometry))
                if (self.census.unsupported.get(category, 0)
                    + self.census.missing_geometry.get(category, 0))
            }
            degenerate = sum(
                value for kind, value in self.census.degenerate_hulls.items()
                if kind != "ok")
        else:
            raise ValueError(
                f"unknown clash geometry scope {geometry_scope!r}; "
                "expected 'mvp' or 'all_eligible'")

        outside = self.census.outside_extraction_scope
        linked = self.census.linked_elements_unscored
        extraction_axis = {
                "complete": outside == 0,
                "outside_extraction_scope": outside,
                "elements_in_l0": self.origin.get("elements_in_l0"),
                "header_census_total": self.origin.get("header_census_total"),
                "note": (
                    "complete only when the document census has no rows "
                    "outside the extracted L0 stream"),
            }
        # ПОЛНОТУ РЕШАЮТ СВЯЗИ, А НЕ СУММА ИХ ЭЛЕМЕНТОВ. Условие слияния волны
        # федерации с исправленным счётчиком (11.08.2026), и без него слияние
        # выпускало бы новый молчаливо-неверный исход.
        #
        # Ось написана, когда `linked_elements_unscored` держал ЧИСЛО СВЯЗЕЙ, и
        # тогда `linked == 0` значило «связей нет» — случайно верно. Счётчик
        # исправлен и держит теперь ЭЛЕМЕНТЫ, и то же выражение стало ложью
        # ровно на худших моделях: у здания, все связи которого ВЫГРУЖЕНЫ,
        # `element_count` не прочитан ни у одной, сумма равна нулю, и поиск
        # объявил бы себя ПОЛНЫМ там, где не видел вообще ничего. По корпусу
        # это не край: 316 связей из 386 (82 %) числа не имеют.
        #
        # Тот же класс, что и сам исправленный счётчик: величина объявлена в
        # одном месте (полнота федерации), прочитана в другом (сумма элементов),
        # и совпасть их ничто не заставляло.
        links_in_l0 = self.origin.get("links_in_l0") or 0
        federation_axis = {
                "complete": links_in_l0 == 0,
                "linked_elements_unscored": linked,
                "links_without_element_count":
                    self.census.links_without_element_count,
                "links_in_l0": links_in_l0,
                "note": (
                    "complete only when the document declares no links at all; "
                    "linked_elements_unscored is a LOWER BOUND — "
                    "links_without_element_count links carry no readable count"),
            }
        coverage = self.origin.get("federation_coverage")
        if coverage is not None:
            extraction_axis, federation_axis = _federation_coverage_axis(
                coverage, records=self.records, refusals=self.refusals)
        return {
            "extraction": extraction_axis,
            "federation": federation_axis,
            "geometry": {
                "complete": without_hull == 0 and degenerate == 0,
                "scope": geometry_scope,
                "eligible": eligible,
                "hulled": hulled,
                "without_hull": without_hull,
                "degenerate_hulls": degenerate,
                "by_side": by_side,
                "by_category_without_hull": by_category_without_hull,
                "note": (
                    "complete only when every element relevant to the query "
                    "has a non-degenerate conservative hull"),
            },
        }

    def as_dict(self) -> dict:
        return {"schema_version": SCHEMA_VERSION, "origin": self.origin,
                "census": self.census.as_dict(), "by_grade": self.by_grade(),
                "records": len(self.records)}

    def validate(self) -> None:
        """Ворота входа детектора (ревью №11). Каждое нарушение — исключение.

        Проверяется то, отсутствие чего делает «ноль клешей» неотличимым от
        «не искали»: баланс КАЖДОЙ категории, уникальность и непустота адресов,
        конечность оболочек, наличие происхождения.
        """
        counter_fields = (
            "eligible", "hulled", "unsupported", "missing_geometry",
            "not_eligible", "reasons", "section_present", "section_absent",
            "section_hulled", "section_blocked", "section_nominal_only",
            "no_hull_mvp_side", "mvp_eligible", "mvp_hulled",
            "no_hull_by_category", "degenerate_hulls",
        )
        for field_name in counter_fields:
            counter = getattr(self.census, field_name)
            if not isinstance(counter, collections.Counter):
                raise SnapshotIntegrityError(
                    f"census.{field_name} не является Counter")
            invalid = {
                key: value for key, value in counter.items()
                if (not isinstance(key, str) or not key
                    or isinstance(value, bool) or not isinstance(value, int)
                    or value < 0)
            }
            if invalid:
                raise SnapshotIntegrityError(
                    f"census.{field_name} содержит неверные счётчики: "
                    f"{invalid}")
        for field_name in ("outside_extraction_scope",
                           "linked_elements_unscored"):
            value = getattr(self.census, field_name)
            if (isinstance(value, bool) or not isinstance(value, int)
                    or value < 0):
                raise SnapshotIntegrityError(
                    f"census.{field_name} должен быть неотрицательным int")
        if not isinstance(self.census.degenerate_by_category, dict):
            raise SnapshotIntegrityError(
                "census.degenerate_by_category должен быть mapping")
        for category, counts in self.census.degenerate_by_category.items():
            if (not isinstance(category, str) or not category
                    or not isinstance(counts, collections.Counter)
                    or any(not isinstance(kind, str) or not kind
                           or isinstance(value, bool)
                           or not isinstance(value, int) or value < 0
                           for kind, value in counts.items())):
                raise SnapshotIntegrityError(
                    "census.degenerate_by_category содержит неверные данные")

        bad = self.census.unbalanced_categories()
        if bad:
            raise SnapshotIntegrityError(
                f"перепись не сходится по категориям: {sorted(bad)} ({bad})")
        if not self.census.balanced():
            raise SnapshotIntegrityError(
                f"перепись не сходится: {self.census.totals()}")
        bad_sec = self.census.unbalanced_section_categories()
        if bad_sec:
            raise SnapshotIntegrityError(
                f"перепись сечений не сходится: {sorted(bad_sec)} ({bad_sec})")
        seen: set[str] = set()
        actual_hulled: collections.Counter = collections.Counter()
        actual_mvp_hulled: collections.Counter = collections.Counter()
        actual_degeneracy: collections.Counter = collections.Counter()
        actual_degeneracy_by_category: dict[str, collections.Counter] = (
            collections.defaultdict(collections.Counter))
        for r in self.records:
            if not r.source_id or r.source_id in ("None", "?"):
                raise SnapshotIntegrityError(f"пустой адрес элемента: {r!r}")
            if r.source_id in seen:
                raise SnapshotIntegrityError(f"дублирующийся source_id: {r.source_id}")
            seen.add(r.source_id)
            actual_hulled[r.category] += 1
            if r.mvp_side in H.MVP_PAIR:
                actual_mvp_hulled[r.mvp_side] += 1
            degeneracy = H.hull_degeneracy(r.hull)
            actual_degeneracy[degeneracy] += 1
            if degeneracy != "ok":
                actual_degeneracy_by_category[r.category][degeneracy] += 1
            lo, hi = r.bounds()
            if not all(isinstance(c, (int, float)) and math.isfinite(c)
                       for c in (*lo, *hi)):
                raise SnapshotIntegrityError(
                    f"неконечная оболочка у {r.source_id}: {lo} {hi}")
        normalized = lambda counter: collections.Counter({
            key: value for key, value in counter.items() if value})
        if normalized(actual_hulled) != normalized(self.census.hulled):
            raise SnapshotIntegrityError(
                "перепись hulled не совпадает с записями: "
                f"records={dict(actual_hulled)} "
                f"census={dict(self.census.hulled)}")
        if normalized(actual_mvp_hulled) != normalized(self.census.mvp_hulled):
            raise SnapshotIntegrityError(
                "перепись mvp_hulled не совпадает с записями")
        if normalized(actual_degeneracy) != normalized(
                self.census.degenerate_hulls):
            raise SnapshotIntegrityError(
                "перепись вырожденности не совпадает с записями")
        declared_degeneracy_by_category = {
            category: normalized(counts)
            for category, counts in self.census.degenerate_by_category.items()
            if normalized(counts)
        }
        if ({category: normalized(counts)
             for category, counts in actual_degeneracy_by_category.items()
             if normalized(counts)} != declared_degeneracy_by_category):
            raise SnapshotIntegrityError(
                "перепись вырожденности по категориям не совпадает")

        refusal_by_bucket: dict[str, collections.Counter] = {
            "unsupported": collections.Counter(),
            "missing_geometry": collections.Counter(),
            "not_eligible": collections.Counter(),
        }
        refusal_reasons: collections.Counter = collections.Counter()
        actual_no_hull_mvp_side: collections.Counter = collections.Counter()
        actual_no_hull_by_category: collections.Counter = collections.Counter()
        for refusal in self.refusals:
            if (not isinstance(refusal, H.Refusal)
                    or not isinstance(refusal.source_id, str)
                    or not refusal.source_id
                    or refusal.source_id in seen
                    or refusal.bucket not in refusal_by_bucket
                    or not isinstance(refusal.category, str)
                    or not refusal.category
                    or not isinstance(refusal.reason, str)
                    or not refusal.reason):
                raise SnapshotIntegrityError(
                    f"неверная или дублирующаяся строка refusal: {refusal!r}")
            seen.add(refusal.source_id)
            refusal_by_bucket[refusal.bucket][refusal.category] += 1
            refusal_reasons[refusal.reason] += 1
            rule = H.KIND_TABLE.get(refusal.category)
            if (refusal.bucket != "not_eligible" and rule is not None
                    and rule.mvp_side in H.MVP_PAIR):
                actual_no_hull_mvp_side[rule.mvp_side] += 1
                actual_no_hull_by_category[refusal.category] += 1
        for bucket, actual in refusal_by_bucket.items():
            declared = getattr(self.census, bucket)
            if normalized(actual) != normalized(declared):
                raise SnapshotIntegrityError(
                    f"перепись {bucket} не совпадает с refusals")
        if normalized(refusal_reasons) != normalized(self.census.reasons):
            raise SnapshotIntegrityError(
                "перепись причин отказа не совпадает с refusals")
        if normalized(actual_no_hull_mvp_side) != normalized(
                self.census.no_hull_mvp_side):
            raise SnapshotIntegrityError(
                "перепись no_hull_mvp_side не совпадает с refusals")
        if normalized(actual_no_hull_by_category) != normalized(
                self.census.no_hull_by_category):
            raise SnapshotIntegrityError(
                "перепись no_hull_by_category не совпадает с refusals")
        expected_mvp_eligible = actual_mvp_hulled + actual_no_hull_mvp_side
        if normalized(expected_mvp_eligible) != normalized(
                self.census.mvp_eligible):
            raise SnapshotIntegrityError(
                "перепись mvp_eligible не совпадает с records + refusals")

        elements_in_l0 = self.origin.get("elements_in_l0")
        if (elements_in_l0 is not None
                and (isinstance(elements_in_l0, bool)
                     or not isinstance(elements_in_l0, int)
                     or elements_in_l0 < 0
                     or elements_in_l0 != len(self.records) + len(self.refusals))):
            raise SnapshotIntegrityError(
                "origin.elements_in_l0 не совпадает с records + refusals")
        if not self.origin:
            raise SnapshotIntegrityError("снапшот без происхождения")
        coverage = self.origin.get("federation_coverage")
        if coverage is not None:
            _federation_coverage_axis(
                coverage, records=self.records, refusals=self.refusals)

    def join_manifest(self) -> dict:
        """Ревью №15: что из модели вообще НЕ дошло до поиска.

        Полный join L0↔L1↔ground (op_id, lift_status) в D1 не построен — и это
        сказано полем `l1_join`, а не умолчанием. Равенство ниже проверяемо
        уже сегодня и держит знаменатель честным.
        """
        t = self.census.totals()
        scored = t["hulled"]
        not_scored = t["unsupported"] + t["missing_geometry"]
        return {
            "eligible": t["eligible"],
            "scored": scored,
            "not_scored": not_scored,
            "not_eligible": t["not_eligible"],
            "outside_extraction_scope": t["outside_extraction_scope"],
            "linked_elements_unscored": t["linked_elements_unscored"],
            "links_without_element_count": t["links_without_element_count"],
            "l1_join": "absent",
            "l1_join_note": ("op_id/lift_status/ground-размеры в D1 не "
                             "присоединены: матрица op×category из §6 этим "
                             "модулем НЕ воспроизводится (ревью №15)."),
        }


def _sha(data: bytes) -> str:
    """ПОЛНЫЙ sha256 (ревью №16): усечённые 16 hex экономили строку отчёта
    ценой доказуемости, а sha боковых индексов не считался вовсе — правка
    профиля меняла находки при неизменном отпечатке."""
    return hashlib.sha256(data).hexdigest()


def build_from_elements(elements: Iterable[dict], *, origin: dict,
                        profiles: dict | None = None,
                        curves: dict | None = None) -> ClashGeometrySnapshot:
    """Элементы (форма записи L0) -> снапшот. Единственный путь построения:
    и реальный декомпайл, и синтетические сцены тестов идут здесь."""
    profiles = profiles or {}
    curves = curves or {}
    census = Census()
    records: list[H.HullRecord] = []
    refusals: list[H.Refusal] = []
    for el in elements:
        cat = el.get("category") or "?"
        sid = str(el.get("element_id"))
        rec, ref = H.build_hull(el, profile=profiles.get(sid),
                                curve=curves.get(sid))
        # Сечение считается ДО и НЕЗАВИСИМО от исхода оболочки: элемент, у
        # которого сечение есть, а ось битая, обязан остаться в знаменателе,
        # иначе процент «сечений нет» посчитан по выборке.
        if H.category_allows_sections(cat):
            sec, why, nominal = H.section_from_params(cat, el.get("params"))
            explicit = el.get("section_radius_mm")
            if sec is not None or (G._finite(explicit) and explicit > 0):
                census.section_present[cat] += 1
            else:
                census.section_absent[cat] += 1
                census.types_without_section[cat].add(
                    el.get("type_name") or "__без_имени_типа__")
            if why == "section_nominal_only" or (
                    sec is None and nominal is not None):
                census.section_nominal_only[cat] += 1
            if rec is not None and rec.hull_source == "axis_section":
                census.section_hulled[cat] += 1
        elif H.carries_section_number(el.get("params")):
            rule = H.KIND_TABLE.get(cat)
            if rule is not None and rule.eligible:
                census.section_blocked[cat] += 1
        rule = H.KIND_TABLE.get(cat)
        if rule is not None and rule.eligible and rule.mvp_side:
            census.mvp_eligible[rule.mvp_side] += 1
            if rec is not None:
                census.mvp_hulled[rule.mvp_side] += 1
            else:
                census.no_hull_mvp_side[rule.mvp_side] += 1
                census.no_hull_by_category[cat] += 1
        if rec is not None:
            census.eligible[cat] += 1
            census.hulled[cat] += 1
            degen = H.hull_degeneracy(rec.hull)
            census.degenerate_hulls[degen] += 1
            if degen != "ok":
                census.degenerate_by_category[cat][degen] += 1
            records.append(rec)
            continue
        assert ref is not None
        refusals.append(ref)
        census.reasons[ref.reason] += 1
        if ref.bucket == "not_eligible":
            census.not_eligible[cat] += 1
        else:
            census.eligible[cat] += 1
            getattr(census, ref.bucket)[cat] += 1
    records.sort(key=lambda r: r.source_id)
    refusals.sort(key=lambda r: r.source_id)
    return ClashGeometrySnapshot(records, census, origin, refusals)


# ─────────────────────────────────────────────── реальный декомпайл на диске

def read_decompile(run_dir: str | pathlib.Path) -> tuple[list[dict], dict, dict, dict]:
    """L0 + боковые индексы -> (элементы, профили, кривые, отпечаток).

    Ревью №10: читатель игнорировал header census, `category_status`, footer и
    записи связей — поэтому файл, обрезанный на корректной json-строке, выглядел
    целым. Теперь поток обязан доказать свою полноту, а всё, что в него не
    вошло, обязано быть НАЗВАНО числом.
    """
    d = pathlib.Path(run_dir)
    elements: list[dict] = []
    origin: dict[str, Any] = {"run_dir": d.name}
    header: dict = {}
    footer: dict = {}
    statuses: list[dict] = []
    links = 0
    linked_elements = 0
    links_unread = 0
    seen_categories: collections.Counter = collections.Counter()
    l0 = d / "L0.jsonl"
    with l0.open(encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SnapshotIntegrityError(
                    f"L0 строка {lineno} нечитаема: {exc}") from exc
            kind = r.get("record")
            if kind == "element":
                elements.append(r["element"])
                seen_categories[r["element"].get("category") or "?"] += 1
            elif kind == "header":
                header = r
            elif kind == "footer":
                footer = r
            elif kind == "category_status":
                # Форма замерена на живом L0 (SOB6.2 фасад v10), не придумана:
                # {"record":"category_status","status":{...}}.
                statuses.append(r.get("status") or {})
            elif kind == "link":
                # СТРОКА СВЯЗИ ОТКРЫВАЕТСЯ, А НЕ ТОЛЬКО СЧИТАЕТСЯ (11.08.2026).
                # Здесь стояло одно `links += 1`, а `census.linked_elements_
                # unscored` — поле, чьё ИМЯ обещает элементы — получало именно
                # это число. Настоящее лежало в самой строке: экстрактор кладёт
                # `element_count` с `GetLinkDocument()` (`extract.py`, цикл по
                # `RevitLinkInstance`) и оставляет `null`, когда документ не
                # загружен. Оба случая теперь РАЗЛИЧНЫ и оба названы.
                links += 1
                count = (r.get("link") or {}).get("element_count")
                if isinstance(count, int) and not isinstance(count, bool) \
                        and count >= 0:
                    linked_elements += count
                else:
                    links_unread += 1
    if not footer:
        raise SnapshotIntegrityError(
            "L0 без footer: поток обрезан, а перепись на обрезанном потоке "
            "сходится сама с собой (ревью №10)")
    if footer.get("stream_complete") is False:
        raise SnapshotIntegrityError("L0 объявил stream_complete=false")
    declared = footer.get("element_count")
    if isinstance(declared, int) and declared != len(elements):
        raise SnapshotIntegrityError(
            f"footer обещал {declared} элементов, в потоке {len(elements)}")
    declared_cats = footer.get("category_count")
    if isinstance(declared_cats, int) and declared_cats != len(statuses):
        raise SnapshotIntegrityError(
            f"footer обещал {declared_cats} строк category_status, "
            f"в потоке {len(statuses)}")
    # ТРЕТЬЕ ЧИСЛО ТОГО ЖЕ ФУТЕРА, И ЕГО НЕ ЧИТАЛ НИКТО. `element_count` и
    # `category_count` сверяются с потоком и роняют прогон; `link_count`
    # объявлялся рядом и игнорировался, поэтому связь, потерянная при записи,
    # оставляла перепись сходящейся САМА С СОБОЙ — ровно та дыра, ради которой
    # сверка футера и заведена (ревью №10). Это не новая строгость, а
    # доведение уже принятого закона до третьего его слагаемого.
    declared_links = footer.get("link_count")
    if isinstance(declared_links, int) and declared_links != links:
        raise SnapshotIntegrityError(
            f"footer обещал {declared_links} строк link, в потоке {links}")
    # header.document.census — СПИСОК {key, count, name}; замерено, а не
    # предположено: на фасаде это 30 489 элементов против 3 153 в потоке.
    census_rows = ((header.get("document") or {}).get("census") or []) if header else []
    if census_rows and not statuses:
        raise SnapshotIntegrityError(
            "header census есть, а ни одной строки category_status нет: "
            "закрытость модели не доказана (ревью №10)")
    for st in statuses:
        cat = st.get("category")
        exp, got = st.get("expected_count"), st.get("extracted_count")
        if isinstance(got, int) and got != seen_categories.get(cat, 0):
            raise SnapshotIntegrityError(
                f"category_status[{cat}]: обещано извлечь {got}, в потоке "
                f"{seen_categories.get(cat, 0)}")
        if isinstance(exp, int) and isinstance(got, int) and got > exp:
            raise SnapshotIntegrityError(
                f"category_status[{cat}]: извлечено {got} > заявленных {exp}")
    origin["stream_complete"] = True
    origin["header_census_total"] = sum(
        row.get("count", 0) for row in census_rows
        if isinstance(row.get("count"), int))
    origin["category_status_rows"] = len(statuses)
    origin["links_in_l0"] = links
    #: Три числа, а не одно, и порознь они не заменяют друг друга: связей
    #: столько-то, элементов в них столько-то, а у стольких-то связей число
    #: элементов ПРОЧИТАТЬ НЕ УДАЛОСЬ. Сумма 0 при `links_in_l0 > 0` значит
    #: «все связи выгружены», а не «связей нет».
    origin["linked_elements_in_l0"] = linked_elements
    origin["links_without_element_count"] = links_unread
    origin["elements_in_l0"] = len(elements)

    inputs: dict[str, str] = {"L0.jsonl": _sha(l0.read_bytes())}
    proof = d / "revision.proof.json"
    if proof.exists():
        origin["revision"] = json.loads(proof.read_text(encoding="utf-8"))
        inputs["revision.proof.json"] = _sha(proof.read_bytes())
    profiles: dict[str, dict] = {}
    sk = d / "sketch.index.json"
    if sk.exists():
        raw = json.loads(sk.read_text(encoding="utf-8"))
        profiles = raw.get("profile_index") or {}
        origin["sketch_failures"] = len(raw.get("failures") or [])
        inputs["sketch.index.json"] = _sha(sk.read_bytes())
    curves: dict[str, dict] = {}
    cv = d / "curve.index.json"
    if cv.exists():
        raw = json.loads(cv.read_text(encoding="utf-8"))
        curves = raw.get("curve_index") or {}
        inputs["curve.index.json"] = _sha(cv.read_bytes())
    # Отпечаток входа: содержимое, а не имя каталога. Отчёт, не привязанный к
    # SHA источника, невозможно ни воспроизвести, ни опровергнуть.
    origin["inputs_sha256"] = dict(sorted(inputs.items()))
    origin["l0_sha"] = inputs["L0.jsonl"]
    origin["schema_versions"] = {"snapshot": SCHEMA_VERSION}
    origin["snapshot_sha256"] = _sha(json.dumps(
        {"inputs": origin["inputs_sha256"],
         "schema_versions": origin["schema_versions"]},
        sort_keys=True, ensure_ascii=False).encode("utf-8"))
    return elements, profiles, curves, origin


def build_from_decompile(run_dir: str | pathlib.Path) -> ClashGeometrySnapshot:
    elements, profiles, curves, origin = read_decompile(run_dir)
    snap = build_from_elements(elements, origin=origin, profiles=profiles,
                               curves=curves)
    header_total = origin.get("header_census_total") or 0
    if header_total:
        snap.census.outside_extraction_scope = max(
            0, header_total - origin["elements_in_l0"])
    # СПРОШЕН АВТОРИТЕТ, А НЕ ОБЪЯВЛЕНА ВЕЛИЧИНА. Здесь стояло
    # `= origin.get("links_in_l0", 0)`: поле, названное ЭЛЕМЕНТАМИ, получало
    # число СТРОК-СВЯЗЕЙ, и три связи по сорок тысяч отчитывались тройкой.
    snap.census.linked_elements_unscored = origin.get(
        "linked_elements_in_l0", 0)
    snap.census.links_without_element_count = origin.get(
        "links_without_element_count", 0)
    snap.validate()
    return snap
