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
from typing import Any, Iterable

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
    #: Элементы связанных файлов: в потоке есть, оболочек им никто не строил.
    linked_elements_unscored: int = 0
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
                "linked_elements_unscored": self.linked_elements_unscored}

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
            "sections": self.sections_as_dict(),
            "mvp_side_coverage": self.mvp_side_coverage(),
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
        for r in self.records:
            if not r.source_id or r.source_id in ("None", "?"):
                raise SnapshotIntegrityError(f"пустой адрес элемента: {r!r}")
            if r.source_id in seen:
                raise SnapshotIntegrityError(f"дублирующийся source_id: {r.source_id}")
            seen.add(r.source_id)
            lo, hi = r.bounds()
            if not all(isinstance(c, (int, float)) and math.isfinite(c)
                       for c in (*lo, *hi)):
                raise SnapshotIntegrityError(
                    f"неконечная оболочка у {r.source_id}: {lo} {hi}")
        if not self.origin:
            raise SnapshotIntegrityError("снапшот без происхождения")

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
                links += 1
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
    snap.census.linked_elements_unscored = origin.get("links_in_l0", 0)
    snap.validate()
    return snap
