"""Продуктовый слой отчёта: то, что видит ПРОЕКТИРОВЩИК, а не мы.

## Почему это ОТДЕЛЬНАЯ схема, а не `clash-report/3`

`clash-report/2` — артефакт ДОКАЗАТЕЛЬСТВА. На нём стоят три закона:
канонический байт-в-байт JSON (`detect.dumps`), замороженный голден и
оракульная приёмка. Все они держатся на одном свойстве: **отчёт есть чистая
функция входа**.

Статус находки (`open/discussed/dismissed/fixed`, кто и когда) — величина
ИЗМЕНЯЕМАЯ и принадлежащая пользователю. Положить её в `/2` значит сделать
канон зависящим от того, кто и когда его смотрел: один и тот же вход перестал
бы давать один и тот же файл, и голден стал бы бессмысленным. Ровно поэтому
`_timings_ms` уже исключён из канона — часы не входят в функцию входа, и
статус не входит тем более.

Поэтому здесь — **отдельный слой `clash-review/1`**, ВЫВОДИМЫЙ из `/2` чистой
функцией. Доказательство остаётся неизменным и версионируется своей чередой;
представление меняется под продукт и версионируется своей. Ни одного НОВОГО
замера в этом модуле нет: только переупаковка того, что детектор уже отдал.

## Что даёт слой

* сводку по РОДАМ («что с этим делать» вместо «сколько строк»);
* группировку по ЭЛЕМЕНТУ — у проектировщика в работе элемент, а не пара;
* `severity` из УЖЕ ИМЕЮЩИХСЯ осей (род, отношение, глубина, грейд);
* поле `status` — пустое, но зарезервированное, чтобы схема не сломалась,
  когда приедет цикл «обсудили → закрыли».
"""
from __future__ import annotations

import collections
from typing import Any

REVIEW_SCHEMA = "clash-review/1"

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

SEVERITY_RULE = (
    "Дубликат — всегда «критично»: два элемента на одном месте не чинятся "
    "раздвиганием. Дальше — по ГЛУБИНЕ перекрытия, но не выше «средней», "
    "пока хотя бы одна оболочка `coarse`: у грубой пары проникание тел НЕ "
    "доказано, и обещать проектировщику больше, чем доказано, нельзя. "
    "Касание (`contact`) — всегда «низкая»."
)


def _ru(label: str) -> str:
    return LABEL_RU.get(label, label or "элемент")


def severity_of(finding: dict) -> str:
    """Серьёзность ТОЛЬКО из уже посчитанных осей. Новых замеров нет."""
    if finding.get("pair_kind") == "coincident_duplicate":
        return "критично"
    if finding.get("hull_relation") == "contact":
        return "низкая"
    depth = float(finding.get("hull_overlap_depth_mm") or 0.0)
    coarse = finding.get("hull_grade") == "coarse"
    if coarse:
        # Грубая пара не доказывает проникания тел — потолок «средняя».
        return "средняя" if depth >= 100.0 else "низкая"
    if depth >= 100.0:
        return "критично"
    if depth >= 10.0:
        return "высокая"
    return "средняя"


def phrase(finding: dict) -> str:
    """Строка, которую читает прораб. «Лоток 123 стоит внутри лотка 456»
    вместо «pair 123/456 overlap 141mm»."""
    a, b = finding["a"], finding["b"]
    an, bn = _ru(a.get("label")), _ru(b.get("label"))
    ai, bi = a["source_element_id"], b["source_element_id"]
    depth = float(finding.get("hull_overlap_depth_mm") or 0.0)
    if finding.get("pair_kind") == "coincident_duplicate":
        return (f"{an.capitalize()} {ai} и {bn} {bi} стоят НА ОДНОМ МЕСТЕ — "
                f"похоже на дубликат, чинится удалением одного из них")
    if finding.get("hull_relation") == "contact":
        return f"{an.capitalize()} {ai} касается {bn} {bi} вплотную"
    certainty = ("габариты пересекаются" if finding.get("hull_grade") == "coarse"
                 else "пересечение")
    return (f"{an.capitalize()} {ai} входит в {bn} {bi} на {depth:.0f} мм "
            f"({certainty})")


def _status_stub() -> dict:
    """Место под цикл «обсудили → закрыли». Пусто, но ЗАРЕЗЕРВИРОВАНО: схема
    не должна ломаться в день, когда статус приедет (задача памяти #28)."""
    return {"state": "open", "changed_by": None, "changed_at": None,
            "note": None, "discussion_ref": None}


def build_review(report: dict, *, top: int = 50, max_per_element: int = 20,
                 max_elements: int | None = None) -> dict:
    """`clash-report/2` -> `clash-review/1`. Чистая функция, без замеров.

    `max_elements` режет ХВОСТ группировки для выгрузки на диск: на ЭОМ v10
    полный обзор — 17 МБ, и фронту столько сразу не нужно. Срез НАЗЫВАЕТСЯ
    полем `elements_truncated_to`, а не молчит: усечённый список, выглядящий
    полным, — та же ложь, что и молчаливый ноль.
    """
    findings = report.get("findings") or []
    rows = []
    for f in findings:
        sev = severity_of(f)
        rows.append({
            "finding_id": f["finding_id"],
            "severity": sev,
            "pair_kind": f.get("pair_kind", "interference"),
            "text": phrase(f),
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
    rows.sort(key=lambda r: (order.get(r["severity"], 9),
                             -(r["depth_mm"] or 0.0), r["finding_id"]))

    by_el: dict[str, dict] = {}
    for r in rows:
        for me, other, my_lab, other_lab in (
                (r["a_element_id"], r["b_element_id"], r["a_label"], r["b_label"]),
                (r["b_element_id"], r["a_element_id"], r["b_label"], r["a_label"])):
            slot = by_el.setdefault(me, {
                "element_id": me, "label": my_lab, "level_id": r["level_id"],
                "conflicts": [], "worst_severity": r["severity"],
                "counts": collections.Counter()})
            slot["counts"][r["severity"]] += 1
            if order.get(r["severity"], 9) < order.get(slot["worst_severity"], 9):
                slot["worst_severity"] = r["severity"]
            if len(slot["conflicts"]) < max_per_element:
                slot["conflicts"].append(
                    {"with_element_id": other, "with_label": other_lab,
                     "severity": r["severity"], "text": r["text"],
                     "finding_id": r["finding_id"], "status": r["status"]})
    elements = sorted(by_el.values(),
                      key=lambda e: (order.get(e["worst_severity"], 9),
                                     -sum(e["counts"].values()), e["element_id"]))
    for e in elements:
        e["conflict_total"] = sum(e["counts"].values())
        e["counts"] = dict(e["counts"])
    elements_total = len(elements)
    if max_elements is not None and elements_total > max_elements:
        elements = elements[:max_elements]

    kinds = collections.Counter(r["pair_kind"] for r in rows)
    sev = collections.Counter(r["severity"] for r in rows)
    dup = kinds.get("coincident_duplicate", 0)
    overlaps = sum(1 for r in rows
                   if r["pair_kind"] == "interference"
                   and r["hull_relation"] == "overlap")
    touches = sum(1 for r in rows if r["hull_relation"] == "contact")
    org = report.get("origin") or {}
    comp = (report.get("search") or {}).get("completeness") or {}
    return {
        "schema_version": REVIEW_SCHEMA,
        "derived_from": {"schema": report.get("schema_version"),
                         "run_dir": org.get("run_dir"),
                         "l0_sha": org.get("l0_sha"),
                         "revision": (org.get("revision") or {}).get("fingerprint")},
        "summary": {
            "total": len(rows),
            "duplicates": dup,
            "duplicates_hint": "чинится удалением одного из пары",
            "overlaps": overlaps,
            "overlaps_hint": "элементы входят друг в друга — нужна правка",
            "touches": touches,
            "touches_hint": "касание вплотную — часто законно, проверить глазами",
            "by_severity": {s: sev.get(s, 0) for s in SEVERITY_ORDER},
            "elements_involved": elements_total,
            "elements_truncated_to": (
                len(elements) if len(elements) != elements_total else None),
            "search_complete": comp.get("complete", True),
            "search_incomplete_note": (
                None if comp.get("complete", True) else
                f"ВНИМАНИЕ: {comp.get('without_hull_on_mvp_side', 0)} элементов "
                f"не участвовали в проверке — список неполон"),
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
        "",
        "| род | сколько | что с этим делать |",
        "|---|---|---|",
        f"| дубликаты | {s['duplicates']} | {s['duplicates_hint']} |",
        f"| пересечения | {s['overlaps']} | {s['overlaps_hint']} |",
        f"| касания | {s['touches']} | {s['touches_hint']} |",
        "",
        "По серьёзности: " + ", ".join(
            f"{k} — {v}" for k, v in s["by_severity"].items() if v),
        "", f"## Первые {top} по серьёзности", "",
    ]
    for i, r in enumerate(review["top_findings"][:top], 1):
        out.append(f"{i}. **[{r['severity']}]** {r['text']}")
    out += ["", "## Элементы с наибольшим числом замечаний", "",
            "| элемент | класс | замечаний | худшее |", "|---|---|---|---|"]
    for e in review["elements"][:top]:
        out.append(f"| {e['element_id']} | {e['label']} | "
                   f"{e['conflict_total']} | {e['worst_severity']} |")
    out += ["", f"_Правило серьёзности: {review['severity_rule']}_", ""]
    return "\n".join(out)
