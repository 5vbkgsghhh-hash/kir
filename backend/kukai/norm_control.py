"""Нормоконтроль — deterministic norm-compliance checking ("экспертиза до экспертизы").

The killer-app differentiator and a TRUTH LAYER (not model theatre): unlike the LLM
answering "по СП всё хорошо" (fabrication risk), this is deterministic. Each NormRule
carries an author-set quantified threshold, the model value is EXTRACTED (not guessed),
and — the hard part the operator flagged — the norm INJECTION must be PRECISE, not a pile
of СП text dumped into context.

Precise-injection mechanism (no garbage, no fabrication):
  1. Each rule carries a VERIFIED ``citation_anchor`` — a distinctive fragment of the real
     clause that contains the requirement AND the number — plus a ``threshold_token``.
  2. ``ground_citation`` fetches candidate chunks (doc + coarse keyword), normalizes
     whitespace, finds the anchor, and returns a TIGHT WINDOW around it (one requirement
     sentence), NOT the whole chunk and NOT a fuzzy keyword hit.
  3. A build-time test (test_norm_control) asserts EVERY rule's anchor is present in
     norms.db and the cited window contains the threshold token — so a rule can never ship
     with a fabricated number or an unverified citation.

Curating the anchors already caught a real bug: the СП 54 kitchen minimum is 8 м² (the
6 м² figure is the "кухонная зона" case), and the СП 1.13130 door rule could not be
grounded, so it was dropped rather than shipped wrong.
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_NORMS_DB = Path(__file__).resolve().parent.parent / "data" / "norms.db"


@dataclass
class NormRule:
    id: str
    norm_doc: str            # "СП 54.13330.2016" — a document present in norms.db
    name_ru: str
    requirement_ru: str      # human requirement (author-set from the real clause)
    element_kind: str        # what to extract: "room" | "door" | ...
    param: str               # numeric key in each extracted element dict
    predicate: str           # "min" (>= threshold) | "max" (<= threshold)
    threshold: float
    unit: str                # "м²" | "м"
    coarse_kw: str           # keyword to fetch candidate chunks from norms.db
    citation_anchor: str     # distinctive clause fragment (normalized-whitespace form)
    threshold_token: str     # the number as it appears in the clause (e.g. "8 м2")
    applies_when: Optional[str] = None  # label substring filter (e.g. "кухн")
    severity: str = "review"


@dataclass
class Finding:
    rule_id: str
    norm_doc: str
    name_ru: str
    element_id: Any
    element_label: str
    observed: Optional[float]
    threshold: float
    unit: str
    verdict: str              # "violation" | "pass" | "not_evaluated"
    reason: str = ""
    citation: str = ""


# ── pure evaluation (no DB / no LLM) ─────────────────────────────────────────

def _passes(observed: float, predicate: str, threshold: float) -> bool:
    if predicate == "min":
        return observed >= threshold
    if predicate == "max":
        return observed <= threshold
    raise ValueError(f"unknown predicate {predicate!r}")


def evaluate_rule(rule: NormRule, elements: list[dict[str, Any]]) -> list[Finding]:
    """Evaluate one rule against extracted elements (the C# extractor's output — a
    list of dicts with {id, label, <rule.param>}). A missing/None value ⇒
    ``not_evaluated`` (never a silent pass). ``applies_when`` filters by label."""
    findings: list[Finding] = []
    for el in elements:
        label = str(el.get("label", el.get("name", "")))
        if rule.applies_when and rule.applies_when.lower() not in label.lower():
            continue
        raw = el.get(rule.param)
        try:
            observed = float(raw) if raw is not None else None
        except (TypeError, ValueError):
            observed = None
        if observed is None:
            verdict, reason = "not_evaluated", f"нет значения '{rule.param}'"
        elif _passes(observed, rule.predicate, rule.threshold):
            verdict, reason = "pass", ""
        else:
            op = "≥" if rule.predicate == "min" else "≤"
            verdict = "violation"
            reason = f"{observed:g} {rule.unit} — требование {op} {rule.threshold:g} {rule.unit}"
        findings.append(Finding(
            rule_id=rule.id, norm_doc=rule.norm_doc, name_ru=rule.name_ru,
            element_id=el.get("id"), element_label=label, observed=observed,
            threshold=rule.threshold, unit=rule.unit, verdict=verdict, reason=reason,
        ))
    return findings


# ── precise grounding — a TIGHT window around the verified anchor ─────────────

def ground_citation(rule: NormRule, db_path: Path = _NORMS_DB, window: int = 150) -> str:
    """Return the real clause text supporting a rule — a tight window around the
    verified anchor, NOT a whole chunk and NOT a fuzzy keyword hit. "" if the anchor
    isn't found (the report then flags it unverified instead of inventing a citation)."""
    if not db_path.exists():
        return ""
    db = None
    try:
        db = sqlite3.connect(str(db_path))
        db.row_factory = sqlite3.Row
        doc_key = rule.norm_doc.split("(")[0].strip()
        rows = db.execute(
            "SELECT text FROM norm_chunks WHERE document_name LIKE ? AND text LIKE ?",
            (f"%{doc_key}%", f"%{rule.coarse_kw}%"),
        ).fetchall()
        for r in rows:
            nt = " ".join(r["text"].split())          # normalize whitespace
            i = nt.find(rule.citation_anchor)
            if i >= 0:
                start = max(0, i - window // 3)
                end = i + len(rule.citation_anchor) + window
                snippet = nt[start:end].strip()
                return ("…" + snippet) if start > 0 else snippet
        return ""
    except Exception:  # noqa: BLE001 — grounding is best-effort
        logger.debug("norm citation grounding failed", exc_info=True)
        return ""
    finally:
        if db:
            db.close()


# ── curated, corpus-verified rule library (grows by curation, NOT by LLM) ────

RULES: list[NormRule] = [
    NormRule(
        id="residential_ceiling_height",
        norm_doc="СП 54.13330.2016",
        name_ru="Высота жилых помещений",
        requirement_ru="Высота (пол–потолок) жилых комнат и кухни — не менее 2,5 м (в отдельных климатических подрайонах — 2,7 м)",
        element_kind="room", param="height_m", predicate="min", threshold=2.5, unit="м",
        coarse_kw="высот", citation_anchor="не менее 2,5 м", threshold_token="2,5 м",
        applies_when=None, severity="review",
    ),
    NormRule(
        id="residential_kitchen_area",
        norm_doc="СП 54.13330.2016",
        name_ru="Площадь кухни",
        requirement_ru="Площадь кухни — не менее 8 м² (кухонной зоны в кухне-столовой — 6 м²)",
        element_kind="room", param="area_m2", predicate="min", threshold=8.0, unit="м²",
        coarse_kw="кухни", citation_anchor="кухни — 8 м2", threshold_token="8 м2",
        applies_when="кухн", severity="review",
    ),
    NormRule(
        id="residential_living_room_area",
        norm_doc="СП 54.13330.2016",
        name_ru="Площадь общей жилой комнаты",
        requirement_ru="Площадь общей жилой комнаты — не менее 14 м² (в 1-комн. кв.); 16 м² при двух и более комнатах",
        element_kind="room", param="area_m2", predicate="min", threshold=14.0, unit="м²",
        coarse_kw="жилой комнаты", citation_anchor="жилой комнаты в однокомнатной квартире — 14 м2",
        threshold_token="14 м2", applies_when="гостин", severity="review",
    ),
]

RULES_BY_ID: dict[str, NormRule] = {r.id: r for r in RULES}


# ── PER-CATEGORY C# extractors — UNITS ARE THE CONTRACT, ISOLATION IS THE OTHER ─
# Each category is a SEPARATE compilation/execution (run_tree_audit calls one per
# element_kind). A version-absent BuiltInParameter is a COMPILE error that kills its
# whole snippet — isolating per category means one bad category (e.g. stairs on an odd
# Revit build) no longer zeroes out rooms/doors/etc.; the report shows which category
# failed. Every length→m (0.3048) and area ft²→m² (0.09290304) conversion is inline
# (version-safe, no UnitTypeId/DisplayUnitType). Each snippet returns { elements: [...] }.
_FT = 0.3048          # 1 ft → m
_FT2 = 0.09290304     # 1 ft² → m²
_CAP = 3000           # max elements per category

ROOM_CS = (
    "var res = new List<object>();\n"
    "foreach (var e in new FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Rooms).WhereElementIsNotElementType()) {\n"
    "  if (res.Count >= 3000) break;\n"
    "  try { var rm = e as Autodesk.Revit.DB.Architecture.Room; if (rm == null || rm.Area <= 0) continue;\n"
    "    var name = rm.get_Parameter(BuiltInParameter.ROOM_NAME)?.AsString() ?? \"\";\n"
    "    double h = 0; try { h = rm.UnboundedHeight * 0.3048; } catch {}\n"
    "    res.Add(new { id = rm.Id.Value, label = name, area_m2 = Math.Round(rm.Area*0.09290304,2), height_m = Math.Round(h,2) });\n"
    "  } catch {}\n}\n"
    "return new { elements = res };"
)

DOOR_CS = (
    "var res = new List<object>();\n"
    "foreach (var d in new FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Doors).WhereElementIsNotElementType()) {\n"
    "  if (res.Count >= 3000) break;\n"
    "  try { double wf=0, hf=0;\n"
    "    var pw=d.get_Parameter(BuiltInParameter.DOOR_WIDTH); if(pw!=null&&pw.HasValue) wf=pw.AsDouble();\n"
    "    var ph=d.get_Parameter(BuiltInParameter.DOOR_HEIGHT); if(ph!=null&&ph.HasValue) hf=ph.AsDouble();\n"
    "    if(wf<=0){ var te=doc.GetElement(d.GetTypeId()); var tp=te?.get_Parameter(BuiltInParameter.DOOR_WIDTH) ?? te?.get_Parameter(BuiltInParameter.GENERIC_WIDTH); if(tp!=null&&tp.HasValue) wf=tp.AsDouble(); }\n"
    "    var mk=d.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)?.AsString() ?? \"\";\n"
    "    res.Add(new { id=d.Id.Value, label=mk, width_m=Math.Round(wf*0.3048,3), height_m=Math.Round(hf*0.3048,3) });\n"
    "  } catch {}\n}\n"
    "return new { elements = res };"
)

WINDOW_CS = (
    "var res = new List<object>();\n"
    "foreach (var w in new FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Windows).WhereElementIsNotElementType()) {\n"
    "  if (res.Count >= 3000) break;\n"
    "  try { double wf=0, hf=0;\n"
    "    var pw=w.get_Parameter(BuiltInParameter.WINDOW_WIDTH); if(pw!=null&&pw.HasValue) wf=pw.AsDouble();\n"
    "    var ph=w.get_Parameter(BuiltInParameter.WINDOW_HEIGHT); if(ph!=null&&ph.HasValue) hf=ph.AsDouble();\n"
    "    if(wf<=0){ var te=doc.GetElement(w.GetTypeId()); var tp=te?.get_Parameter(BuiltInParameter.WINDOW_WIDTH) ?? te?.get_Parameter(BuiltInParameter.GENERIC_WIDTH); if(tp!=null&&tp.HasValue) wf=tp.AsDouble(); }\n"
    "    var mk=w.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)?.AsString() ?? \"\";\n"
    "    res.Add(new { id=w.Id.Value, label=mk, width_m=Math.Round(wf*0.3048,3), height_m=Math.Round(hf*0.3048,3) });\n"
    "  } catch {}\n}\n"
    "return new { elements = res };"
)

WALL_CS = (
    "var res = new List<object>();\n"
    "foreach (var wl in new FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Walls).WhereElementIsNotElementType()) {\n"
    "  if (res.Count >= 3000) break;\n"
    "  try { double af=0, hf=0;\n"
    "    var pa=wl.get_Parameter(BuiltInParameter.HOST_AREA_COMPUTED); if(pa!=null&&pa.HasValue) af=pa.AsDouble();\n"
    "    var ph=wl.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM); if(ph!=null&&ph.HasValue) hf=ph.AsDouble();\n"
    "    var tn=doc.GetElement(wl.GetTypeId())?.Name ?? \"\";\n"
    "    res.Add(new { id=wl.Id.Value, label=tn, area_m2=Math.Round(af*0.09290304,2), height_m=Math.Round(hf*0.3048,2) });\n"
    "  } catch {}\n}\n"
    "return new { elements = res };"
)

ROOF_CS = (
    "var res = new List<object>();\n"
    "foreach (var rf in new FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Roofs).WhereElementIsNotElementType()) {\n"
    "  if (res.Count >= 3000) break;\n"
    "  try { double af=0, sl=0;\n"
    "    var pa=rf.get_Parameter(BuiltInParameter.HOST_AREA_COMPUTED); if(pa!=null&&pa.HasValue) af=pa.AsDouble();\n"
    "    var ps=rf.get_Parameter(BuiltInParameter.ROOF_SLOPE); if(ps!=null&&ps.HasValue) sl=ps.AsDouble();\n"
    "    var tn=doc.GetElement(rf.GetTypeId())?.Name ?? \"\";\n"
    "    res.Add(new { id=rf.Id.Value, label=tn, area_m2=Math.Round(af*0.09290304,2), slope_ratio=Math.Round(sl,4) });\n"
    "  } catch {}\n}\n"
    "return new { elements = res };"
)

STAIR_CS = (
    "var res = new List<object>();\n"
    "foreach (var s in new FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Stairs).WhereElementIsNotElementType()) {\n"
    "  if (res.Count >= 3000) break;\n"
    "  try { double wf=0, rf=0, tf=0;\n"
    "    var pw=s.LookupParameter(\"Фактическая ширина марша\"); if(pw==null) pw=s.LookupParameter(\"Actual Run Width\"); if(pw==null) pw=s.LookupParameter(\"Ширина\"); if(pw!=null&&pw.HasValue) wf=pw.AsDouble();\n"
    "    var pr=s.LookupParameter(\"Фактическая высота подступенка\"); if(pr==null) pr=s.LookupParameter(\"Actual Riser Height\"); if(pr!=null&&pr.HasValue) rf=pr.AsDouble();\n"
    "    var pt=s.LookupParameter(\"Фактическая глубина проступи\"); if(pt==null) pt=s.LookupParameter(\"Actual Tread Depth\"); if(pt!=null&&pt.HasValue) tf=pt.AsDouble();\n"
    "    res.Add(new { id=s.Id.Value, label=\"Лестница\", width_m=Math.Round(wf*0.3048,3), riser_m=Math.Round(rf*0.3048,3), tread_m=Math.Round(tf*0.3048,3) });\n"
    "  } catch {}\n}\n"
    "return new { elements = res };"
)

_CAT_EXTRACTORS: dict[str, str] = {
    "room": ROOM_CS, "door": DOOR_CS, "window": WINDOW_CS,
    "wall": WALL_CS, "roof": ROOF_CS, "stair": STAIR_CS,
}


def _element_list(result: Any):
    """Parse a single-category bridge result into (elements, ok). ok=False means the
    snippet failed (compile/exec/error) — the category is reported as not-extracted,
    never silently treated as 'no elements'."""
    import json as _json
    r = result
    if isinstance(r, str):
        try:
            r = _json.loads(r)
        except (ValueError, TypeError):
            return [], False
    if not isinstance(r, dict):
        return [], False
    if r.get("error"):
        return [], False
    inner = r.get("elements")
    if inner is None and isinstance(r.get("result"), dict):
        inner = r["result"].get("elements")
    if isinstance(inner, list):
        return inner, True
    return [], False


# ── trigger detection (mirrors qa_checks.detect_qa_trigger) ──────────────


_NC_TRIGGERS = [
    # Strong, unambiguous normcontrol intent only — a loose "по СП" would hijack
    # legitimate questions, so those are deliberately excluded.
    "нормоконтрол", "экспертиз",
    "проверь на соответстви", "проверка на соответстви",
    "проверь по норм", "проверка по норм",
    "соответстви норм", "соответстви сп",
]


def detect_normcontrol_trigger(message: str) -> bool:
    """True if the message asks for a norm-compliance check (vs generic QA)."""
    if not message:
        return False
    return any(t in message.lower() for t in _NC_TRIGGERS)


# ── report — inject ONLY the tight grounded citation per violation ───────────

def format_normcontrol_report(findings: list[Finding]) -> str:
    violations = [f for f in findings if f.verdict == "violation"]
    not_eval = [f for f in findings if f.verdict == "not_evaluated"]
    passed = [f for f in findings if f.verdict == "pass"]

    lines = ["📋 **Нормоконтроль** (экспертиза до экспертизы — кандидаты на проверку)"]
    lines.append(
        f"Проверено: {len(findings)} · ⚠️ вероятных нарушений: {len(violations)} · "
        f"✅ ок: {len(passed)} · ❓ не оценено: {len(not_eval)}"
    )
    if not findings:
        lines.append("\nНечего проверять по текущему набору правил.")
        return "\n".join(lines)

    for f in violations:
        lines.append(f"\n⚠️ **{f.name_ru}** — {f.element_label or f.element_id}")
        lines.append(f"   {f.reason}")
        if f.citation:
            lines.append(f"   Основание — {f.norm_doc}: «{f.citation}»")
        else:
            lines.append(f"   Основание — {f.norm_doc} (сверьтесь с оригиналом: пункт не подтверждён в базе)")
    if not_eval:
        lines.append(f"\n❓ Не оценено ({len(not_eval)}): нет данных модели — "
                     + ", ".join(sorted({f.name_ru for f in not_eval})))
    lines.append("\n_Это предварительная проверка. Окончательное заключение — за экспертом._")
    return "\n".join(lines)
