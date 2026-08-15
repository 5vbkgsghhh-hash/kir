"""Продуктовый слой отчёта: то, что видит ПРОЕКТИРОВЩИК, а не мы.

## Почему это ОТДЕЛЬНАЯ схема, а не `clash-report/3`

`clash-report/3` — артефакт ДОКАЗАТЕЛЬСТВА. На нём стоят три закона:
канонический байт-в-байт JSON (`detect.dumps`), замороженный голден и
оракульная приёмка. Все они держатся на одном свойстве: **отчёт есть чистая
функция входа**.

Статус находки (`open/discussed/dismissed/fixed`, кто и когда) — величина
ИЗМЕНЯЕМАЯ и принадлежащая пользователю. Положить её в `/3` значит сделать
канон зависящим от того, кто и когда его смотрел: один и тот же вход перестал
бы давать один и тот же файл, и голден стал бы бессмысленным. Ровно поэтому
`_timings_ms` уже исключён из канона — часы не входят в функцию входа, и
статус не входит тем более.

Поэтому здесь — **отдельный слой `clash-review/2`**, ВЫВОДИМЫЙ из `/3` чистой
функцией. Доказательство остаётся неизменным и версионируется своей чередой;
представление меняется под продукт и версионируется своей. Ни одного НОВОГО
замера в этом модуле нет: только переупаковка того, что детектор уже отдал.

## Что даёт слой

* сводку по РОДАМ («что с этим делать» вместо «сколько строк»);
* группировку по ЭЛЕМЕНТУ — у проектировщика в работе элемент, а не пара;
* ортогональные `evidence_state`, `impact_severity` и `actionability`;
* legacy `severity` как консервативный приоритет очереди, не как доказательство;
* поле `status` — пустое, но зарезервированное, чтобы схема не сломалась,
  когда приедет цикл «обсудили → закрыли».
"""
from __future__ import annotations

import collections
from typing import Any, Mapping

from kukai.clash import detect as D

REVIEW_SCHEMA = "clash-review/2"

#: Русское имя КЛАССА элемента (не типа и не семейства!). Ключ — `label` из
#: закрытой таблицы `hulls.KIND_TABLE`, то есть словарь закрыт вместе с ней.
LABEL_RU: dict[str, str] = {
    "wall": "стена", "floor": "перекрытие", "roof": "кровля",
    "column": "колонна", "beam": "балка", "foundation": "фундамент",
    "pipe": "труба", "duct": "воздуховод", "tray": "лоток",
    "conduit": "короб", "pipe_fitting": "фитинг трубы",
    "duct_fitting": "фитинг воздуховода", "tray_fitting": "фитинг лотка",
    "conduit_fitting": "фитинг короба", "pipe_accessory": "арматура трубы",
    "duct_accessory": "арматура воздуховода", "duct_terminal": "диффузор",
    "sprinkler": "спринклер", "pipe_insulation": "изоляция трубы",
    "duct_insulation": "изоляция воздуховода", "duct_lining": "обшивка воздуховода",
    "door": "дверь", "window": "окно", "curtain_panel": "панель витража",
    "mullion": "импост", "curtain_system": "витражная система",
    "generic": "обобщённая модель", "equipment": "оборудование",
    "electrical_equipment": "электрощит", "electrical_fixture": "электроприбор",
    "lighting_device": "устройство освещения", "lighting_fixture": "светильник",
    "railing": "ограждение", "stairs": "лестница", "ramp": "пандус",
    "ceiling": "потолок", "furniture": "мебель", "casework": "мебельный блок",
    "fixture": "сантехприбор", "direct_shape": "импортированное тело",
    "import_instance": "импорт", "truss": "ферма",
}

#: Порядок серьёзности. Публикуется В ОТЧЁТЕ, чтобы правило можно было
#: оспорить, а не угадывать по числам.
SEVERITY_ORDER = ("критично", "высокая", "средняя", "низкая")
EVIDENCE_STATES = ("confirmed", "possible")
IMPACT_SEVERITIES = ("critical", "high", "medium", "low", "unknown")
ACTIONABILITY_STATES = ("delete", "repair", "verify", "none")

SEVERITY_RULE = (
    "Legacy severity — приоритет проверки, а не истинность коллизии. "
    "`possible` ограничен средней/низкой очередью независимо от глубины "
    "внешних оболочек. Критичный геометрический дубликат требует двух "
    "независимых sealed-доказательств: физического пересечения и точного "
    "равенства тел; это всё равно не является правом удаления BIM-элемента."
)


def _ru(label: str) -> str:
    return LABEL_RU.get(label, label or "элемент")


def evidence_state_of(finding: Mapping[str, Any]) -> str:
    """Accept ``confirmed`` only through the detector's sealed proof chain."""

    if finding.get("verdict") != "confirmed":
        return "possible"
    a, b = finding.get("a"), finding.get("b")
    proof = finding.get("physical_overlap_proof")
    if (not isinstance(a, Mapping) or not isinstance(b, Mapping)
            or not isinstance(proof, Mapping)):
        return "possible"
    subject_a, subject_b = a.get("source_element_id"), b.get(
        "source_element_id")
    if not isinstance(subject_a, str) or not isinstance(subject_b, str):
        return "possible"
    return ("confirmed" if D.verify_serialized_physical_overlap_proof(
        proof, subject_a=subject_a, subject_b=subject_b) else "possible")


def impact_severity_of(
        finding: Mapping[str, Any], evidence_state: str | None = None,
        duplicate_equality_proven: bool | None = None) -> str:
    """Potential impact, separate from evidence and available action."""

    evidence = evidence_state or evidence_state_of(finding)
    if evidence != "confirmed":
        return "unknown"
    if finding.get("hull_relation") == "contact":
        return "low"
    duplicate_proven = (D.duplicate_claim_is_proven(dict(finding))
                        if duplicate_equality_proven is None
                        else duplicate_equality_proven)
    if (finding.get("pair_kind") == "coincident_duplicate"
            and duplicate_proven):
        return "critical"
    proof = finding.get("physical_overlap_proof") or {}
    depth = float(proof.get("inner_overlap_depth_mm") or 0.0)
    if depth >= 100.0:
        return "critical"
    if depth >= 10.0:
        return "high"
    return "medium"


def severity_of(finding: dict, *, evidence_state: str | None = None,
                impact_severity: str | None = None) -> str:
    """Legacy conservative work priority; never upgrades possible to fact."""

    evidence = evidence_state or evidence_state_of(finding)
    if evidence != "confirmed":
        return "низкая" if finding.get("hull_relation") == "contact" else "средняя"
    impact = impact_severity or impact_severity_of(finding, evidence)
    return {
        "critical": "критично", "high": "высокая", "medium": "средняя",
        "low": "низкая", "unknown": "средняя",
    }[impact]


def actionability_of(
        finding: dict, evidence_state: str | None = None,
        duplicate_equality_proven: bool | None = None,
        ) -> tuple[str, bool]:
    """Return (actionability, verification_required) without unsafe repair."""

    evidence = evidence_state or evidence_state_of(finding)
    if evidence != "confirmed":
        return "verify", True
    if finding.get("hull_relation") == "contact":
        return "verify", True
    if finding.get("pair_kind") == "coincident_duplicate":
        # Exact body equality is a geometric fact, not a deletion
        # capability.  Two distinct BIM elements can intentionally occupy the
        # same body while differing by phase, design option, system, group,
        # ownership or downstream references.  Until a separate semantic and
        # dependency-equivalence proof exists, deletion always needs review.
        # Keep evaluating the geometry proof above for evidence/ranking, but
        # never promote it into a destructive instruction here.
        _ = (D.duplicate_claim_is_proven(finding)
             if duplicate_equality_proven is None
             else duplicate_equality_proven)
        return "verify", True
    return "repair", False


def phrase(finding: dict, *, evidence_state: str | None = None,
           actionability: str | None = None,
           duplicate_equality_proven: bool | None = None) -> str:
    """Строка, которую читает прораб. «Лоток 123 стоит внутри лотка 456»
    вместо «pair 123/456 overlap 141mm».

    Совет не бывает увереннее улики. Даже доказанное совпадение геометрии не
    доказывает равенство фаз, систем, групп и внешних зависимостей, поэтому
    этот слой никогда не печатает указание удалить. У пары, про которую
    известен один габаритный бокс, тот же бокс дают и две диагонали квадрата;
    строка называет ровно то, что совпало, и посылает смотреть модель.
    """
    a, b = finding["a"], finding["b"]
    an, bn = _ru(a.get("label")), _ru(b.get("label"))
    ai, bi = a["source_element_id"], b["source_element_id"]
    depth = float(finding.get("hull_overlap_depth_mm") or 0.0)
    evidence = evidence_state or evidence_state_of(finding)
    duplicate_proven = (D.duplicate_claim_is_proven(finding)
                        if duplicate_equality_proven is None
                        else duplicate_equality_proven)
    action = actionability or actionability_of(
        finding, evidence, duplicate_proven)[0]
    if evidence != "confirmed":
        if finding.get("pair_kind") == "coincident_duplicate":
            return (f"{an.capitalize()} {ai} и {bn} {bi}: внешние оболочки "
                    "совпали — "
                    "возможный дубликат; равенство точных тел не доказано, "
                    "требуется проверка в модели")
        if finding.get("hull_relation") == "contact":
            return (f"{an.capitalize()} {ai} и {bn} {bi}: внешние оболочки "
                    "касаются — "
                    "контакт тел не подтверждён, требуется проверка")
        return (f"{an.capitalize()} {ai} и {bn} {bi}: внешние оболочки "
                "перекрываются "
                f"на {depth:.0f} мм — возможная коллизия; пересечение тел "
                "не подтверждено, требуется проверка")
    if finding.get("pair_kind") == "coincident_duplicate":
        if duplicate_proven:
            return (f"Точные тела {an} {ai} и {bn} {bi} совпадают, но "
                    "семантическая взаимозаменяемость и отсутствие внешних "
                    "зависимостей не доказаны — проверить; автоматически "
                    "удалять нельзя")
        return (f"Пересечение тел {an} {ai} и {bn} {bi} подтверждено, но "
                "их точное равенство не доказано — сверить перед изменением")
    if finding.get("hull_relation") == "contact":
        return f"Контакт тел {an} {ai} и {bn} {bi} подтверждён; сверить узел"
    proof = finding.get("physical_overlap_proof") or {}
    inner_depth = float(proof.get("inner_overlap_depth_mm") or 0.0)
    return (f"Пересечение тел {an} {ai} и {bn} {bi} подтверждено: "
            f"сертифицированные внутренние области перекрываются на "
            f"{inner_depth:.0f} мм; требуется исправление")


def _status_stub() -> dict:
    """Место под цикл «обсудили → закрыли». Пусто, но ЗАРЕЗЕРВИРОВАНО: схема
    не должна ломаться в день, когда статус приедет (задача памяти #28)."""
    return {"state": "open", "changed_by": None, "changed_at": None,
            "note": None, "discussion_ref": None}


def _search_completeness(report: Mapping[str, Any]) -> tuple[bool, bool, str | None]:
    """Return (complete, contract_valid, user-visible note), fail-closed."""

    search = report.get("search")
    comp = search.get("completeness") if isinstance(search, Mapping) else None
    if not isinstance(comp, Mapping):
        return False, False, (
            "ВНИМАНИЕ: контракт полноты поиска отсутствует — список нельзя "
            "считать полным")
    required_axes = {"extraction", "federation", "geometry", "query_scope"}
    axes = comp.get("axes")
    complete = comp.get("complete")
    if (comp.get("schema_version") != "clash-completeness/1"
            or not isinstance(complete, bool)
            or not isinstance(axes, Mapping)
            or not required_axes.issubset(axes)):
        return False, False, (
            "ВНИМАНИЕ: контракт полноты поиска неполон или неизвестной "
            "версии — список нельзя считать полным")
    axis_states = {
        name: (axis.get("complete") if isinstance(axis, Mapping) else None)
        for name, axis in axes.items()}
    if any(not isinstance(value, bool) for value in axis_states.values()):
        return False, False, (
            "ВНИМАНИЕ: контракт полноты содержит ось без вердикта — список "
            "нельзя считать полным")
    derived = all(axis_states.values())
    if complete != derived:
        return False, False, (
            "ВНИМАНИЕ: общий вердикт полноты противоречит своим осям — "
            "список нельзя считать полным")
    if complete:
        return True, True, None
    missing = ", ".join(sorted(
        name for name, value in axis_states.items() if not value))
    return False, True, (
        f"ВНИМАНИЕ: поиск неполон по осям {missing}; список находок неполон")


def build_review(report: dict, *, top: int = 50, max_per_element: int = 20,
                 max_elements: int | None = None) -> dict:
    """`clash-report/3` -> `clash-review/2`. Чистая функция, без замеров.

    `max_elements` режет ХВОСТ группировки для выгрузки на диск: на ЭОМ v10
    полный обзор — 17 МБ, и фронту столько сразу не нужно. Срез НАЗЫВАЕТСЯ
    полем `elements_truncated_to`, а не молчит: усечённый список, выглядящий
    полным, — та же ложь, что и молчаливый ноль.
    """
    if report.get("schema_version") != D.REPORT_SCHEMA:
        report = D.migrate_report(report)
    findings = report.get("findings") or []
    rows = []
    for f in findings:
        evidence = evidence_state_of(f)
        duplicate_proven = D.duplicate_claim_is_proven(f)
        impact = impact_severity_of(f, evidence, duplicate_proven)
        sev = severity_of(
            f, evidence_state=evidence, impact_severity=impact)
        actionability, verification_required = actionability_of(
            f, evidence, duplicate_proven)
        rows.append({
            "finding_id": f["finding_id"],
            "severity": sev,
            "evidence_state": evidence,
            "impact_severity": impact,
            "actionability": actionability,
            "verification_required": verification_required,
            "pair_kind": f.get("pair_kind", "interference"),
            "duplicate_equality_proven": duplicate_proven,
            # Geometry and BIM semantics are independent proof axes.  This
            # explicit false prevents downstream clients from treating
            # `duplicates_confirmed` as permission to mutate the model.
            "deletion_safe": False,
            "deletion_blockers": (
                (["exact_body_equality_unproven"]
                 if (f.get("pair_kind") == "coincident_duplicate"
                     and not duplicate_proven) else [])
                + (["semantic_equivalence_unproven",
                    "dependency_equivalence_unproven"]
                   if f.get("pair_kind") == "coincident_duplicate" else [])
            ),
            "text": phrase(
                f, evidence_state=evidence, actionability=actionability,
                duplicate_equality_proven=duplicate_proven),
            "a_element_id": f["a"]["source_element_id"],
            "b_element_id": f["b"]["source_element_id"],
            "a_label": _ru(f["a"].get("label")),
            "b_label": _ru(f["b"].get("label")),
            "depth_mm": f.get("hull_overlap_depth_mm"),
            "hull_relation": f.get("hull_relation"),
            "hull_grade": f.get("hull_grade"),
            "level_id": f["a"].get("level_id") or f["b"].get("level_id"),
            "status": _status_stub(),
        })
    order = {s: i for i, s in enumerate(SEVERITY_ORDER)}
    rows.sort(key=lambda r: (0 if r["evidence_state"] == "confirmed" else 1,
                             order.get(r["severity"], 9),
                             -(r["depth_mm"] or 0.0), r["finding_id"]))

    by_el: dict[str, dict] = {}
    for r in rows:
        for me, other, my_lab, other_lab in (
                (r["a_element_id"], r["b_element_id"], r["a_label"], r["b_label"]),
                (r["b_element_id"], r["a_element_id"], r["b_label"], r["a_label"])):
            slot = by_el.setdefault(me, {
                "element_id": me, "label": my_lab, "level_id": r["level_id"],
                "conflicts": [], "worst_severity": r["severity"],
                "counts": collections.Counter(),
                "evidence_counts": collections.Counter(),
                "actionability_counts": collections.Counter()})
            slot["counts"][r["severity"]] += 1
            slot["evidence_counts"][r["evidence_state"]] += 1
            slot["actionability_counts"][r["actionability"]] += 1
            if order.get(r["severity"], 9) < order.get(slot["worst_severity"], 9):
                slot["worst_severity"] = r["severity"]
            if len(slot["conflicts"]) < max_per_element:
                slot["conflicts"].append(
                    {"with_element_id": other, "with_label": other_lab,
                     "severity": r["severity"], "text": r["text"],
                     "evidence_state": r["evidence_state"],
                     "impact_severity": r["impact_severity"],
                     "actionability": r["actionability"],
                     "verification_required": r["verification_required"],
                     "finding_id": r["finding_id"], "status": r["status"]})
    elements = sorted(by_el.values(),
                      key=lambda e: (order.get(e["worst_severity"], 9),
                                     -sum(e["counts"].values()), e["element_id"]))
    for e in elements:
        e["conflict_total"] = sum(e["counts"].values())
        e["counts"] = dict(e["counts"])
        e["evidence_counts"] = dict(e["evidence_counts"])
        e["actionability_counts"] = dict(e["actionability_counts"])
    elements_total = len(elements)
    if max_elements is not None and elements_total > max_elements:
        elements = elements[:max_elements]

    kinds = collections.Counter(r["pair_kind"] for r in rows)
    sev = collections.Counter(r["severity"] for r in rows)
    duplicate_candidates = kinds.get("coincident_duplicate", 0)
    confirmed_duplicates = sum(
        1 for r in rows if r["duplicate_equality_proven"]
        and r["evidence_state"] == "confirmed")
    possible_duplicates = duplicate_candidates - confirmed_duplicates
    overlaps_confirmed = sum(1 for r in rows
                   if r["pair_kind"] == "interference"
                   and r["hull_relation"] == "overlap"
                   and r["evidence_state"] == "confirmed")
    overlaps_possible = sum(1 for r in rows
                   if r["pair_kind"] == "interference"
                   and r["hull_relation"] == "overlap"
                   and r["evidence_state"] == "possible")
    touches_confirmed = sum(1 for r in rows
        if r["hull_relation"] == "contact"
        and r["evidence_state"] == "confirmed")
    touches_possible = sum(1 for r in rows
        if r["hull_relation"] == "contact"
        and r["evidence_state"] == "possible")
    evidence_counts = collections.Counter(r["evidence_state"] for r in rows)
    impact_counts = collections.Counter(r["impact_severity"] for r in rows)
    action_counts = collections.Counter(r["actionability"] for r in rows)
    org = report.get("origin") or {}
    search_complete, search_contract_valid, search_note = _search_completeness(
        report)
    return {
        "schema_version": REVIEW_SCHEMA,
        "derived_from": {"schema": report.get("schema_version"),
                         "run_dir": org.get("run_dir"),
                         "l0_sha": org.get("l0_sha"),
                         "revision": (org.get("revision") or {}).get("fingerprint")},
        "summary": {
            "total": len(rows),
            "confirmed": evidence_counts.get("confirmed", 0),
            "possible": evidence_counts.get("possible", 0),
            "duplicates": duplicate_candidates,
            "duplicates_confirmed": confirmed_duplicates,
            "duplicates_possible": possible_duplicates,
            "duplicates_geometry_confirmed": confirmed_duplicates,
            "duplicates_delete_safe": sum(
                1 for row in rows
                if row["pair_kind"] == "coincident_duplicate"
                and row["deletion_safe"]),
            "duplicates_hint": (
                "sealed exact-body equality подтверждает геометрию, но не "
                "семантическую взаимозаменяемость и не отсутствие зависимостей; "
                "все кандидаты требуют проверки перед удалением"),
            "overlaps": overlaps_confirmed + overlaps_possible,
            "overlaps_confirmed": overlaps_confirmed,
            "overlaps_possible": overlaps_possible,
            "overlaps_hint": (
                "confirmed можно исправлять; possible означает лишь "
                "перекрытие внешних оболочек и требует проверки"),
            "touches": touches_confirmed + touches_possible,
            "touches_confirmed": touches_confirmed,
            "touches_possible": touches_possible,
            "touches_hint": (
                "контакт не является автоматическим дефектом; проверить узел"),
            "by_severity": {s: sev.get(s, 0) for s in SEVERITY_ORDER},
            "by_evidence_state": {
                state: evidence_counts.get(state, 0)
                for state in EVIDENCE_STATES},
            "by_impact_severity": {
                state: impact_counts.get(state, 0)
                for state in IMPACT_SEVERITIES},
            "by_actionability": {
                state: action_counts.get(state, 0)
                for state in ACTIONABILITY_STATES},
            "elements_involved": elements_total,
            "elements_truncated_to": (
                len(elements) if len(elements) != elements_total else None),
            "search_complete": search_complete,
            "search_completeness_contract_valid": search_contract_valid,
            "search_incomplete_note": search_note,
        },
        "severity_rule": SEVERITY_RULE,
        "status_vocabulary": ["open", "discussed", "dismissed", "fixed"],
        "top_findings": rows[:top],
        "elements": elements,
    }


def to_markdown(review: dict, *, top: int = 10) -> str:
    s = review["summary"]
    out = ["# Проверка на коллизии — что нашли", ""]
    if s.get("search_incomplete_note"):
        out += [f"> **{s['search_incomplete_note']}**", ""]
    out += [
        f"Всего замечаний: **{s['total']}** по {s['elements_involved']} элементам.",
        f"Доказано: **{s['confirmed']}**; требует проверки: **{s['possible']}**.",
        "",
        "| род | confirmed | possible | что с этим делать |",
        "|---|---:|---:|---|",
        f"| дубликаты | {s['duplicates_confirmed']} | "
        f"{s['duplicates_possible']} | {s['duplicates_hint']} |",
        f"| пересечения | {s['overlaps_confirmed']} | "
        f"{s['overlaps_possible']} | {s['overlaps_hint']} |",
        f"| касания | {s['touches_confirmed']} | "
        f"{s['touches_possible']} | {s['touches_hint']} |",
        "",
        "По серьёзности: " + ", ".join(
            f"{k} — {v}" for k, v in s["by_severity"].items() if v),
        "", f"## Первые {top} по серьёзности", "",
    ]
    for i, r in enumerate(review["top_findings"][:top], 1):
        out.append(
            f"{i}. **[{r['severity']}; {r['evidence_state']}; "
            f"{r['actionability']}]** {r['text']}")
    out += ["", "## Элементы с наибольшим числом замечаний", "",
            "| элемент | класс | замечаний | худшее |", "|---|---|---|---|"]
    for e in review["elements"][:top]:
        out.append(f"| {e['element_id']} | {e['label']} | "
                   f"{e['conflict_total']} | {e['worst_severity']} |")
    out += ["", f"_Правило серьёзности: {review['severity_rule']}_", ""]
    return "\n".join(out)
