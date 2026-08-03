"""Две фазы поиска и плоский детерминированный отчёт.

Широкая фаза (ревью №11): оболочка кладётся во ВСЕ ячейки, которые задевает её
AABB, а не в одну по центру. «Соседние ячейки от медианного габарита» корректны
только при доказанной верхней границе размера оболочки — а длинная стена и
короткая труба пересекаются, когда их центры разнесены на десятки ячеек.
Гиганты, задевающие слишком много ячеек, уходят в отдельный список и
сравниваются со всеми — без этого сетка либо врёт, либо взрывается.

Узкая фаза даёт формальный выход (ревью №13): `signed_distance` (отрицательное
= проникание), `physical_penetration_mm`, `clearance_deficit_mm`, MTV как
перенос A при неподвижном B. Вердикт — `confirmed | possible` (ревью №14):
пересечение двух консервативных оболочек означает «возможен клеш», а не клеш,
потому что судятся ОБОЛОЧКИ, а не тела.
"""

from __future__ import annotations

import collections
import json
import math
import pathlib
import statistics
import time
from dataclasses import dataclass, field
from typing import Iterable

from kukai.clash import geom as G
from kukai.clash import hulls as H
from kukai.clash.snapshot import ClashGeometrySnapshot, SnapshotIntegrityError

REPORT_SCHEMA = "clash-report/2"

#: Сколько ячеек одна оболочка вправе занять, прежде чем её признают гигантом.
#: Не вкус: при большем числе стоимость раскладки перевешивает выигрыш сетки.
MAX_CELLS_PER_HULL = 512

#: Ревью №14. ОТНОШЕНИЕ оболочек — отдельная ось от ДОКАЗАТЕЛЬНОСТИ. Прежний
#: `tol_grade` решал обе задачи разом и глушил доказанные касания: при sd=0
#: находки не было даже у точной пары, а грубая пара с sd=-1…-25 мм
#: подавлялась порогом, который никогда не был доказанной погрешностью AABB.
HULL_RELATIONS = ("overlap", "contact", "separated")
VERDICTS = ("confirmed", "possible")

#: Численный шум перевода футы→мм, а НЕ физический допуск. Отметка 1800 мм
#: приезжает как 1799.9999999998602 — вот на это и на ничто другое.
EPS_NUMERIC_MM = 1e-6

#: Что означает опубликованное расстояние (ревью №7). Для пары призм это
#: НИЖНЯЯ ОЦЕНКА по лучшей разделяющей оси, а не евклидово расстояние: она
#: никогда не выше истинного, поэтому даёт лишние находки, но не пропуски.
SEPARATION_SEMANTICS = (
    "signed_distance_mm: <0 — глубина перекрытия ОБОЛОЧЕК; >0 — расстояние. "
    "Для пар призма×призма это lower_bound по лучшей разделяющей оси (SAT), "
    "не евклидово расстояние: оценка снизу завышает клеш, но не прячет его."
)

#: Ревью №13: область поиска обязана называться в каноне. Произвольный
#: callable-фильтр делал её неопределимой — «6/236» невозможно отнести ни к
#: MVP, ни к диагностике.
SCOPES: dict[str, str] = {
    "mvp_v2": "{труба, воздуховод, лоток, кабель-канал} × "
              "{стена, пол, колонна, балка, фундамент, кровля}",
    "all_physical_diagnostic": "ВСЕ физические пары — диагностика, не MVP: "
                               "внутрираздельные примыкания законны сплошь и рядом",
}


@dataclass
class Grid:
    cell: float
    buckets: dict[tuple[int, int, int], list[int]] = field(default_factory=dict)
    oversized: list[int] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    #: На сколько раздувался габарит при раскладке (ревью №9). Кандидаты,
    #: запрошенные с бо́льшим slack, чем построена сетка, — ложный пропуск.
    slack: float = 0.0


def choose_cell_size(records: list[H.HullRecord]) -> float:
    """Ребро ячейки — 2× медианного габарита оболочки, но не ноль."""
    spans = []
    for r in records:
        lo, hi = r.bounds()
        spans.append(max(hi[i] - lo[i] for i in range(3)))
    if not spans:
        return 1000.0
    med = statistics.median(spans)
    return max(2.0 * med, 1.0)


def build_grid(records: list[H.HullRecord], cell: float | None = None, *,
               slack: float = 0.0) -> Grid:
    """Раскладка оболочек по ячейкам.

    Ревью №9: `slack` (положительный зазор) применялся ТОЛЬКО после встречи в
    общей ячейке, а раскладка шла по нераздутому габариту. Контрпример: cell=10,
    боксы x=[8,9] и [10.1,11], clearance=2 — полный перебор даёт пару, сетка
    давала []. Раздуваем габарит КАЖДОЙ оболочки на slack при раскладке: если
    два габарита сходятся в пределах slack, их раздутые версии обязаны
    пересечься, а значит разделить хотя бы одну ячейку.
    """
    cell = cell or choose_cell_size(records)
    g = Grid(cell=cell, slack=slack)
    cells_per = []
    for idx, r in enumerate(records):
        lo, hi = r.bounds()
        lo = tuple(lo[k] - slack for k in range(3))
        hi = tuple(hi[k] + slack for k in range(3))
        i0 = [math.floor(lo[k] / cell) for k in range(3)]
        i1 = [math.floor(hi[k] / cell) for k in range(3)]
        n = 1
        for k in range(3):
            n *= (i1[k] - i0[k] + 1)
        cells_per.append(n)
        if n > MAX_CELLS_PER_HULL:
            g.oversized.append(idx)
            continue
        for x in range(i0[0], i1[0] + 1):
            for y in range(i0[1], i1[1] + 1):
                for z in range(i0[2], i1[2] + 1):
                    g.buckets.setdefault((x, y, z), []).append(idx)
    occ = [len(v) for v in g.buckets.values()]
    g.stats = {
        "cell_mm": round(cell, 3),
        "cells": len(g.buckets),
        "oversized_hulls": len(g.oversized),
        "max_cells_per_hull": max(cells_per) if cells_per else 0,
        "mean_cells_per_hull": round(sum(cells_per) / len(cells_per), 3) if cells_per else 0.0,
        "max_bucket": max(occ) if occ else 0,
        "mean_bucket": round(sum(occ) / len(occ), 3) if occ else 0.0,
    }
    return g


def _boxes_overlap(a: H.HullRecord, b: H.HullRecord, slack: float) -> bool:
    alo, ahi = a.bounds()
    blo, bhi = b.bounds()
    return all(alo[k] - slack <= bhi[k] and blo[k] - slack <= ahi[k]
               for k in range(3))


def candidate_pairs(records: list[H.HullRecord], grid: Grid, *,
                    slack: float = 0.0,
                    pair_filter=None) -> list[tuple[int, int]]:
    """Кандидаты широкой фазы — НАДМНОЖЕСТВО реальных пересечений.

    Дедупликация глобальная: одна пара попадает в результат один раз, сколько
    бы ячеек она ни делила.

    Сетка обязана быть построена с тем же (или бо́льшим) `slack` — иначе
    раскладка не видела зазора и надмножество перестаёт им быть (ревью №9).
    """
    if slack > grid.slack + 1e-12:
        raise ValueError(
            f"сетка построена со slack={grid.slack}, запрошено {slack}: "
            "широкая фаза перестала бы быть надмножеством")
    seen: set[tuple[int, int]] = set()

    def offer(i: int, j: int) -> None:
        if i == j:
            return
        key = (i, j) if i < j else (j, i)
        if key in seen:
            return
        a, b = records[key[0]], records[key[1]]
        if pair_filter is not None and not pair_filter(a, b):
            return
        if _boxes_overlap(a, b, slack):
            seen.add(key)

    for members in grid.buckets.values():
        n = len(members)
        for x in range(n):
            for y in range(x + 1, n):
                offer(members[x], members[y])
    # Гиганты сравниваются со всеми: их AABB может задеть что угодно, и
    # выбросить их из сетки, не сравнив, — это ложный пропуск.
    for idx in grid.oversized:
        for other in range(len(records)):
            offer(idx, other)
    return sorted(seen)


def brute_pairs(records: list[H.HullRecord], *, slack: float = 0.0,
                pair_filter=None) -> list[tuple[int, int]]:
    """Полный перебор — эталон для property-теста широкой фазы."""
    out = []
    for i in range(len(records)):
        for j in range(i + 1, len(records)):
            a, b = records[i], records[j]
            if pair_filter is not None and not pair_filter(a, b):
                continue
            if _boxes_overlap(a, b, slack):
                out.append((i, j))
    return out


def mvp_pair_filter(a: H.HullRecord, b: H.HullRecord) -> bool:
    """Пары MVP: {труба, воздуховод, лоток} × {стена, пол, колонна, ...}."""
    return {a.mvp_side, b.mvp_side} == set(H.MVP_PAIR)


def any_physical_pair_filter(a: H.HullRecord, b: H.HullRecord) -> bool:
    """Все физические пары — НЕ MVP; годится только для диагностики, потому
    что внутрираздельные примыкания законны сплошь и рядом."""
    return True


# ───────────────────────────────────────────────────────────── узкая фаза

@dataclass
class Finding:
    finding_id: str
    a: dict
    b: dict
    pair_class: str
    signed_distance_mm: float
    #: Ревью №6/№14: это глубина перекрытия ОБОЛОЧЕК, а не проникания тел.
    #: Прежнее имя `physical_penetration_mm` обещало факт о постройке.
    hull_overlap_depth_mm: float
    clearance_mm: float
    clearance_deficit_mm: float
    #: Только для ранжирования и UI (ревью №14). НЕ ворота полноты: 25 мм
    #: никогда не были доказанной погрешностью габаритной оболочки.
    ranking_tol_mm: float
    hull_grade: str
    #: РОД пары: обычное пересечение или ДУБЛИКАТ (два элемента на одном
    #: месте). Дубликат — диагностика модели, а не клеш: он чинится удалением,
    #: а не раздвиганием, и заказчику нужен отдельной строкой.
    pair_kind: str
    #: Ось ОТНОШЕНИЯ: overlap | contact | separated.
    hull_relation: str
    #: Ось ДОКАЗАТЕЛЬНОСТИ: confirmed | possible. `touch` сюда не добавляется
    #: намеренно — это смешало бы две оси обратно в одну.
    verdict: str
    #: Ревью №6: сертифицированный разводящий перенос, НЕ минимальный вектор.
    certified_separating_translation_mm: tuple[float, float, float] | None
    separation_is_lower_bound: bool
    ranking_significant: bool
    translation_unavailable_reason: str | None = None

    def as_dict(self) -> dict:
        def r(x):
            return G._norm_zero(round(float(x), 3))
        v = self.certified_separating_translation_mm
        return {
            "finding_id": self.finding_id,
            "a": self.a, "b": self.b,
            "pair_class": self.pair_class,
            "signed_distance_mm": r(self.signed_distance_mm),
            "separation_is_lower_bound": self.separation_is_lower_bound,
            "hull_overlap_depth_mm": r(self.hull_overlap_depth_mm),
            "clearance_mm": r(self.clearance_mm),
            "clearance_deficit_mm": r(self.clearance_deficit_mm),
            "ranking_tol_mm": r(self.ranking_tol_mm),
            "ranking_significant": self.ranking_significant,
            "hull_grade": self.hull_grade,
            "pair_kind": self.pair_kind,
            "hull_relation": self.hull_relation,
            "verdict": self.verdict,
            "certified_separating_translation_mm": (
                None if v is None else [r(c) for c in v]),
            "translation_unavailable_reason": self.translation_unavailable_reason,
        }


def _side(rec: H.HullRecord) -> dict:
    """Обе стороны находки адресуются одинаково (ревью №15): чем именно
    элемент назван, видно без догадок."""
    return {"source_element_id": rec.source_id, "category": rec.category,
            "label": rec.label, "hull_grade": rec.grade,
            "hull_source": rec.hull_source, "level_id": rec.level_id,
            "type_name": rec.type_name,
            # Волна D2-A: `hull_source: axis_section` не говорит, ГДЕ взято
            # число. Диаметр трубы и полудиагональ лотка — разные обоснования
            # одной и той же капсулы, и находка обязана их различать.
            "section_source": rec.section_source,
            "section_radius_mm": (
                None if rec.section_radius_mm is None
                else G._norm_zero(round(float(rec.section_radius_mm), 3)))}


def pair_grade(a: H.HullRecord, b: H.HullRecord) -> str:
    """Грейд пары — по худшей стороне: доказательность не бывает выше самой
    грубой из двух оболочек."""
    order = {g: i for i, g in enumerate(H.GRADES)}
    return H.GRADES[max(order[a.grade], order[b.grade])]


#: Допуск совпадения оболочек: численный шум перевода футов в мм, и ничего
#: больше. Два элемента, чьи габариты совпали в его пределах, стоят на одном
#: месте — признак СТРУКТУРНЫЙ, никаких имён типов.
DUPLICATE_EPS_MM = 1.0

PAIR_KINDS = ("interference", "coincident_duplicate")


def pair_kind_of(a: H.HullRecord, b: H.HullRecord, *,
                 eps: float = DUPLICATE_EPS_MM) -> str:
    """Дубликат или обычное пересечение. Замер v19 нашёл две такие пары —
    одна ось, один габарит, разные id."""
    if a.category != b.category:
        return "interference"
    alo, ahi = a.bounds()
    blo, bhi = b.bounds()
    if all(abs(alo[k] - blo[k]) <= eps and abs(ahi[k] - bhi[k]) <= eps
           for k in range(3)):
        return "coincident_duplicate"
    return "interference"


def relation_of(sd: float, *, eps: float = EPS_NUMERIC_MM) -> str:
    """Отношение оболочек по знаковому расстоянию (ревью №14)."""
    if sd < -eps:
        return "overlap"
    if sd <= eps:
        return "contact"
    return "separated"


def evaluate_with_reason(a: H.HullRecord, b: H.HullRecord, *,
                         clearance_mm: float = 0.0
                         ) -> tuple[Finding | None, str | None]:
    """Одна пара -> (находка либо None, причина отсутствия находки).

    Ревью №11: нечисловая узкая фаза возвращала `None` МОЛЧА, неотличимо от
    «пара чистая». Теперь у каждого None есть имя, и оно попадает в счётчик.

    Ревью №14: порог грейда больше НЕ решает, быть находке или нет. Отношение
    оболочек (overlap/contact/separated) — факт геометрии; `ranking_tol_mm`
    остался только для сортировки и UI.
    """
    sd = G.signed_distance(a.hull, b.hull)
    if not math.isfinite(sd):
        return None, "narrow_unsupported"
    grade = pair_grade(a, b)
    tol = H.TOL_GRADE_MM[grade]
    relation = relation_of(sd)
    deficit = max(0.0, clearance_mm - sd)
    clearance_violation = sd < clearance_mm - EPS_NUMERIC_MM
    if relation == "separated" and not clearance_violation:
        return None, None
    verdict = "confirmed" if grade == "exact" else "possible"
    ends = sorted((a, b), key=lambda r: r.source_id)
    lo, hi = ends[0], ends[1]
    # Перенос не публикуется у грубых пар: направление выхода из габаритного
    # бокса ничего не доказывает про тело.
    vec, why = None, None
    if grade in ("exact", "conservative") and relation == "overlap":
        vec = G.certified_separating_translation(lo.hull, hi.hull)
        if vec is None:
            why = G.mtv_unavailable_reason(lo.hull, hi.hull)
    both_prisms = all(not isinstance(r.hull, G.Capsule) for r in (lo, hi))
    return Finding(
        finding_id=f"{lo.source_id}~{hi.source_id}", a=_side(lo), b=_side(hi),
        # Класс пары — НЕУПОРЯДОЧЕННЫЙ ключ: стороны A/B упорядочены по
        # source_id (это детерминизм адресов), но `wall~mullion` и
        # `mullion~wall` — один класс, и складывать их в две строки отчёта
        # значит делить одно число пополам случайным образом.
        pair_class="~".join(sorted((lo.label, hi.label))),
        signed_distance_mm=sd,
        separation_is_lower_bound=both_prisms,
        hull_overlap_depth_mm=max(0.0, -sd),
        clearance_mm=clearance_mm, clearance_deficit_mm=deficit,
        ranking_tol_mm=tol, ranking_significant=(sd < -tol or deficit > tol),
        hull_grade=grade, pair_kind=pair_kind_of(lo, hi),
        hull_relation=relation, verdict=verdict,
        certified_separating_translation_mm=vec,
        translation_unavailable_reason=why), None


def evaluate(a: H.HullRecord, b: H.HullRecord, *, clearance_mm: float = 0.0
             ) -> Finding | None:
    return evaluate_with_reason(a, b, clearance_mm=clearance_mm)[0]


# ────────────────────────────────────────────────────────────── оркестровка

#: Единственные допустимые фильтры пар и их имена в каноне (ревью №13).
_SCOPE_BY_FILTER = {
    "mvp_pair_filter": "mvp_v2",
    "any_physical_pair_filter": "all_physical_diagnostic",
}


def scope_id_of(pair_filter) -> str:
    name = getattr(pair_filter, "__name__", "")
    scope = _SCOPE_BY_FILTER.get(name)
    if scope is None:
        raise ValueError(
            f"неизвестный фильтр пар {name!r}: область поиска обязана "
            f"называться в каноне (ревью №13). Допустимо: {sorted(_SCOPE_BY_FILTER)}")
    return scope


def completeness_of(snapshot: ClashGeometrySnapshot) -> dict:
    """Полон ли поиск ПО ПОСТРОЕНИЮ (R5 красных).

    Элемент стороны MVP без оболочки — не строка переписи, а дыра в поиске:
    стена, которой нет, гарантированно пропустит всё, что сквозь неё проходит.
    На фасаде v14 таких 783 (15.66 %), и отчёт при этом выглядел исправным.

    Полнота публикуется УТВЕРЖДЕНИЕМ в обе стороны: «полон» — тоже факт,
    который надо сказать, иначе молчание читается как успех.
    """
    c = snapshot.census
    without = sum(c.no_hull_mvp_side.values())
    return {
        "complete": without == 0,
        "without_hull_on_mvp_side": without,
        "by_side": {side: c.no_hull_mvp_side.get(side, 0)
                    for side in ("mep", "struct")},
        "by_category": dict(sorted(c.no_hull_by_category.items())),
        "note": ("элемент стороны MVP без оболочки не участвует в поиске: "
                 "любой клеш через него пропущен ПО ПОСТРОЕНИЮ, а не по "
                 "порогу (R5 красных)."),
    }


def detect(snapshot: ClashGeometrySnapshot, *, clearance_mm: float = 0.0,
           pair_filter=mvp_pair_filter, cell_mm: float | None = None,
           require_complete: bool = False) -> dict:
    """Снапшот -> отчёт. Read-only от начала до конца.

    Ревью №11: снапшот проверяется НА ВХОДЕ. Детектор, продолжающий работу на
    несошедшейся переписи, найдёт ноль клешей и будет выглядеть исправным.

    `require_complete` (R5 красных): вызывающий, которому нужен ПОЛНЫЙ поиск,
    обязан иметь способ этого потребовать. По умолчанию отчёт печатает
    неполноту громко, но работу не останавливает — иначе сегодняшний фасад
    вообще перестал бы считаться, а вместе с ним и диагностика.
    """
    scope = scope_id_of(pair_filter)
    snapshot.validate()
    completeness = completeness_of(snapshot)
    if require_complete and not completeness["complete"]:
        raise SnapshotIntegrityError(
            f"поиск неполон по построению: без оболочки "
            f"{completeness['without_hull_on_mvp_side']} элементов стороны MVP "
            f"({completeness['by_category']})")
    t0 = time.perf_counter()
    records = snapshot.records
    grid = build_grid(records, cell_mm, slack=clearance_mm)
    t_grid = time.perf_counter()
    cands = candidate_pairs(records, grid, slack=clearance_mm,
                            pair_filter=pair_filter)
    t_broad = time.perf_counter()
    findings = []
    narrow_refusals: dict[str, int] = {}
    for i, j in cands:
        f, why = evaluate_with_reason(records[i], records[j],
                                      clearance_mm=clearance_mm)
        if f is not None:
            findings.append(f)
        elif why:
            narrow_refusals[why] = narrow_refusals.get(why, 0) + 1
    t_narrow = time.perf_counter()
    findings.sort(key=lambda f: (f.finding_id, f.pair_class))

    # pairs_in_scope агрегатом по классам, НЕ полным перебором: замер
    # приёмки 28.07 — на демо-башне (90 758 элементов, ~50k оболочек)
    # попарный цикл это ~1.25e9 вызовов фильтра, детектор не дожил до
    # ответа за 570 с. Оба фильтра детерминированы классом записи
    # (label/mvp_side) — контракт закреплён тестом против полного
    # перебора; счётчик тот же самый, число в отчёте не меняется.
    class_counts: dict = {}
    class_rep: dict = {}
    for r in records:
        key = (r.label, r.mvp_side)
        class_counts[key] = class_counts.get(key, 0) + 1
        class_rep.setdefault(key, r)
    class_keys = sorted(class_counts)
    eligible_pairs = 0
    for i, ka in enumerate(class_keys):
        for kb in class_keys[i:]:
            if pair_filter is not None and not pair_filter(
                    class_rep[ka], class_rep[kb]):
                continue
            if ka == kb:
                n = class_counts[ka]
                eligible_pairs += n * (n - 1) // 2
            else:
                eligible_pairs += class_counts[ka] * class_counts[kb]
    return {
        "schema_version": REPORT_SCHEMA,
        "origin": snapshot.origin,
        "census": snapshot.census.as_dict(),
        "by_grade": snapshot.by_grade(),
        "coverage_matrix": H.coverage_matrix(),
        "search": {
            "scope_id": scope,
            "scope_definition": SCOPES[scope],
            "completeness": completeness,
            "clearance_mm": clearance_mm,
            "hulls": len(records),
            "pairs_in_scope": eligible_pairs,
            "candidate_pairs": len(cands),
            "narrow_evaluations": len(cands),
            "narrow_refusals": dict(sorted(narrow_refusals.items())),
            "separation_semantics": SEPARATION_SEMANTICS,
            "grid": grid.stats,
        },
        "join_manifest": snapshot.join_manifest(),
        # Телеметрия прогона, НЕ факт о здании: один вход обязан давать
        # байт-в-байт один канонический отчёт, а стенные часы дают его
        # только случайно (замер приёмки 28.07: голден агента нёс 0.1 мс,
        # прогон лида — 0.0). Подчёркнутый ключ dumps() не сериализует.
        "_timings_ms": {"grid": round((t_grid - t0) * 1000, 1),
                        "broad": round((t_broad - t_grid) * 1000, 1),
                        "narrow": round((t_narrow - t_broad) * 1000, 1)},
        "verdict_counts": dict(collections.Counter(f.verdict for f in findings)),
        "pair_kind_counts": dict(sorted(
            collections.Counter(f.pair_kind for f in findings).items())),
        "relation_counts": dict(sorted(
            collections.Counter(f.hull_relation for f in findings).items())),
        "pair_class_counts": dict(sorted(
            collections.Counter(f.pair_class for f in findings).items())),
        "findings": [f.as_dict() for f in findings],
        "notes": [
            "raw_interference: легальные отверстия, гильзы и соединения НЕ "
            "исключены — legal_relation_index появится в D2 (ревью №20).",
            "verdict=possible означает пересечение ОБОЛОЧЕК, а не тел; "
            "ход ремонта из него строить нельзя (ревью №14).",
            "Это не оракульный замер: recall/precision против "
            "ElementIntersectsElementFilter — волна D2 (§6).",
        ],
    }


def migrate_report(old: dict) -> dict:
    """`clash-report/1` -> `/2`. Ревью №14: канон нельзя сохранить байт-в-байт,
    добавив факт, — его надо версионировать И уметь читать историю. Миграция
    ничего не досочиняет: отношение выводится из уже записанного расстояния,
    старые имена переносятся в новые без изменения ЧИСЕЛ.
    """
    if old.get("schema_version") == REPORT_SCHEMA:
        return old
    if old.get("schema_version") != "clash-report/1":
        raise ValueError(f"неизвестная схема отчёта: {old.get('schema_version')!r}")
    rep = dict(old)
    rep["schema_version"] = REPORT_SCHEMA
    out = []
    for f in old.get("findings") or []:
        g = dict(f)
        sd = float(g.get("signed_distance_mm", 0.0))
        g["hull_overlap_depth_mm"] = g.pop("physical_penetration_mm", max(0.0, -sd))
        g["certified_separating_translation_mm"] = g.pop("mtv_mm", None)
        g["ranking_tol_mm"] = g.pop("tol_grade_mm", 0.0)
        g["hull_relation"] = relation_of(sd)
        g.setdefault("separation_is_lower_bound", False)
        g.setdefault("ranking_significant", True)
        g.setdefault("translation_unavailable_reason", None)
        g.setdefault("pair_kind", "interference")
        out.append(g)
    rep["findings"] = out
    rep["relation_counts"] = dict(sorted(
        collections.Counter(f["hull_relation"] for f in out).items()))
    rep.setdefault("notes", []).append(
        "МИГРАЦИЯ clash-report/1 -> /2: отношение выведено из записанного "
        "signed_distance_mm; поля переименованы, числа не пересчитывались.")
    return rep


def dumps(report: dict) -> str:
    """Каноническая сериализация: один и тот же вход даёт байт-в-байт один
    и тот же файл. Без этого голден бессмыслен, а два прогона неразличимы.

    Ключи, начинающиеся с ``_``, — телеметрия прогона (тайминги и т.п.),
    в канон не входят: канон — функция ВХОДА, часы в него не входят."""
    canon = {k: v for k, v in report.items() if not k.startswith("_")}
    return json.dumps(canon, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def _sections_markdown(sec: dict) -> list[str]:
    """Сечения В ОТЧЁТЕ. Ноль поднятых оболочек обязан быть СКАЗАН вместе с
    причиной: «в модели нет таких категорий» и «читать запрещено таблицей» —
    разные диагнозы, а в таблице грейдов оба выглядят как `exact=0`."""
    if not sec:
        return []
    t = sec.get("totals") or {}
    out = ["## Сечения", ""]
    rows = sec.get("by_category") or {}
    if rows:
        out += ["| категория | элементов | сечение есть | сечения нет | "
                "оболочек по сечению |", "|---|---|---|---|---|"]
        for cat, r in sorted(rows.items()):
            out.append(f"| {cat} | {r['eligible']} | {r['present']} | "
                       f"{r['absent']} | {r['hulled']} |")
        out.append("")
    out.append(
        f"Итого: сечение прочитано у {t.get('present', 0)} элементов, "
        f"оболочек по сечению построено {t.get('hulled', 0)}; "
        f"типов без сечения {sec.get('types_without_section_count', 0)}.")
    blocked = sec.get("blocked_by_table") or {}
    if blocked:
        out += ["", "Сечение снято, но **запрещён таблицей** источник "
                    "`axis_section` (ревью №2, №3, №10) — "
                + ", ".join(f"{c}: {n}" for c, n in sorted(blocked.items()))
                + f" (всего {sec.get('blocked_total', 0)}). Это ЗАПРЕТ, а не "
                  "отсутствие данных: оболочкой у них остаётся габарит."]
    elif not t.get("present"):
        out += ["", "Ни одной оболочки по сечению: в модели нет элементов "
                    "категорий, которым источник `axis_section` разрешён. "
                    "Знаменатель выше публикуется нулями намеренно — «0 из 0» "
                    "и «не спрашивали» обязаны выглядеть по-разному."]
    out.append("")
    return out


def to_markdown(report: dict) -> str:
    s = report["search"]
    c = report["census"]["totals"]
    org = report["origin"]
    out = [
        "# CLASH D1 — плоский отчёт (raw_interference)",
        "",
        "**Не оракульный замер.** Судятся ОБОЛОЧКИ, а не тела; recall и "
        "precision против `ElementIntersectsElementFilter` — волна D2. "
        "Легальные отверстия и гильзы не исключены: `legal_relation_index` "
        "тоже D2.",
        "",
        f"Источник: `{org.get('run_dir', '?')}` · L0 SHA `{org.get('l0_sha', '?')}` "
        f"· ревизия `{(org.get('revision') or {}).get('fingerprint', '?')}`",
        "",
        "## Перепись",
        "",
        f"| eligible | hulled | unsupported | missing_geometry | сходится |",
        "|---|---|---|---|---|",
        f"| {c['eligible']} | {c['hulled']} | {c['unsupported']} | "
        f"{c['missing_geometry']} | {'да' if report['census']['balanced'] else 'НЕТ'} |",
        "",
        "Грейды оболочек: " + ", ".join(
            f"{g}={n}" for g, n in sorted(report["by_grade"].items())),
        "",
    ]
    comp = (report["search"].get("completeness") or {})
    cov = (report["census"].get("mvp_side_coverage") or {})
    if comp and not comp.get("complete", True):
        out += [
            f"> **ПОИСК НЕПОЛОН ПО ПОСТРОЕНИЮ.** Без оболочки остались "
            f"{comp['without_hull_on_mvp_side']} элементов стороны MVP "
            f"({', '.join(f'{k}: {v}' for k, v in comp['by_category'].items())}). "
            f"Любой клеш через них пропущен не по порогу, а потому что их нет "
            f"в поиске. Список находок ниже читать как НИЖНЮЮ оценку.",
            "",
        ]
    if cov:
        out += ["Покрытие сторон MVP: " + ", ".join(
            f"{side}: {v['hulled']}/{v['eligible']}"
            + (f" (без оболочки {v['without_hull']})" if v["without_hull"] else "")
            for side, v in sorted(cov.items())), ""]
    out += _sections_markdown(report["census"].get("sections") or {})
    out += [
        "## Поиск",
        "",
        f"- область: `{s['scope_id']}` — {s['scope_definition']}",
        f"- оболочек: {s['hulls']}, пар в области `{s['scope_id']}`: "
        f"{s['pairs_in_scope']}",
        f"- кандидатов широкой фазы: {s['candidate_pairs']}",
        f"- ячейка {s['grid']['cell_mm']} мм, ячеек {s['grid']['cells']}, "
        f"максимум в ячейке {s['grid']['max_bucket']}, "
        f"гигантов {s['grid']['oversized_hulls']}",
        "",
    ]
    ms = report.get("_timings_ms")
    if ms:  # телеметрия прогона; в каноническом JSON её нет
        out += [f"- время, мс: сетка {ms['grid']}, широкая {ms['broad']}, "
                f"узкая {ms['narrow']}", ""]
    out += [
        "## Находки",
        "",
    ]
    if not report["findings"]:
        out += ["Ни одной. Счётчики выше показывают, что поиск шёл: "
                "детектор, который «нашёл 0», обязан доказать, что искал.", ""]
    else:
        out += ["| # | A | B | класс | перекрытие оболочек, мм | отношение "
                "| грейд | вердикт |",
                "|---|---|---|---|---|---|---|---|"]
        for i, f in enumerate(report["findings"][:200], 1):
            out.append(
                f"| {i} | {f['a']['source_element_id']} ({f['a']['label']}) "
                f"| {f['b']['source_element_id']} ({f['b']['label']}) "
                f"| {f['pair_class']} | {f['hull_overlap_depth_mm']} "
                f"| {f['hull_relation']} | {f['hull_grade']} | {f['verdict']} |")
        if len(report["findings"]) > 200:
            out.append(f"| … | ещё {len(report['findings']) - 200} | | | | | |")
        out.append("")
    out += ["## Оговорки", ""] + [f"- {n}" for n in report["notes"]]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    import argparse

    from kukai.clash.snapshot import build_from_decompile

    ap = argparse.ArgumentParser(description="CLASH D1 — детектор поверх KIR")
    ap.add_argument("run_dir", help="каталог декомпайла (L0.jsonl + индексы)")
    ap.add_argument("--clearance-mm", type=float, default=0.0)
    ap.add_argument("--cell-mm", type=float, default=None)
    ap.add_argument("--all-pairs", action="store_true",
                    help="ДИАГНОСТИКА: все физические пары, не только MVP")
    ap.add_argument("--out", default=None, help="префикс: <out>.json + <out>.md")
    a = ap.parse_args(argv)

    snap = build_from_decompile(a.run_dir)
    rep = detect(snap, clearance_mm=a.clearance_mm, cell_mm=a.cell_mm,
                 pair_filter=any_physical_pair_filter if a.all_pairs
                 else mvp_pair_filter)
    if a.all_pairs:
        rep["notes"].insert(0, "ДИАГНОСТИКА: --all-pairs, пары вне MVP; "
                               "внутрираздельные примыкания законны и здесь НЕ "
                               "отфильтрованы.")
    if a.out:
        p = pathlib.Path(a.out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.with_suffix(".json").write_text(dumps(rep) + "\n", encoding="utf-8")
        p.with_suffix(".md").write_text(to_markdown(rep), encoding="utf-8")
    print(to_markdown(rep))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
