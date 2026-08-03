"""Model vitals — ONE live read-only query for the passport "health header".

The study's worst failures were fabrications about model STATE the passport never
carried: s30 invented "560 warnings" + GOST clauses (0 tool calls); s19 invented
"котлы 40" + OST_Boilers; s28 missed 18 CAD imports. The fix is to put the cheap,
high-signal model-health scalars *in the pocket* so the model has a real anchor
(and, crucially, sees a real ZERO instead of guessing something exists).

This module only ACQUIRES the data: it builds one version-safe C# body (run once
per document via the bridge, cached, like A2's type_meta) and normalizes the raw
result. Presentation lives in ``model_passport._v2_health`` (acquisition vs render
stay separated). Version-safety mirrors query_builder: NEVER .Value/.IntegerValue;
ids via Id.ToString(); every block in its own try/catch so one failure on an
exotic model can't blank the whole header.
"""
from __future__ import annotations

from typing import Any

# Consolidated read-only vitals query. Body for Execute(Document doc, UIDocument uidoc).
VITALS_CS = """
var res = new Dictionary<string,object>();
// --- warnings (the anti-fabrication anchor: s30) ---
try {
  var __warns = doc.GetWarnings();
  res["warnings_count"] = (__warns != null) ? __warns.Count : 0;
  var __wd = new Dictionary<string,int>();
  if (__warns != null) foreach (var __w in __warns) {
    string __t = ""; try { __t = __w.GetDescriptionText(); } catch {}
    if (string.IsNullOrEmpty(__t)) continue;
    if (!__wd.ContainsKey(__t)) __wd[__t] = 0;
    __wd[__t] = __wd[__t] + 1;
  }
  var __keys = new List<string>(__wd.Keys);
  __keys.Sort((__a,__b) => __wd[__b].CompareTo(__wd[__a]));
  var __top = new List<string>();
  foreach (var __k in __keys) { if (__top.Count >= 5) break; __top.Add(__k + " (" + __wd[__k] + ")"); }
  res["warnings_top"] = __top;
} catch { res["warnings_count"] = 0; }
// --- CAD imports (s28: the missed 18) ---
try { res["cad_imports"] = new FilteredElementCollector(doc).OfClass(typeof(ImportInstance)).WhereElementIsNotElementType().GetElementCount(); } catch { res["cad_imports"] = 0; }
// --- grids / levels pinned ratio ---
try {
  int __gt=0,__gp=0;
  foreach (var __g in new FilteredElementCollector(doc).OfClass(typeof(Grid)).WhereElementIsNotElementType()) { __gt++; if (__g.Pinned) __gp++; }
  res["grids_total"]=__gt; res["grids_pinned"]=__gp;
} catch { res["grids_total"]=0; res["grids_pinned"]=0; }
try {
  int __lt=0,__lp=0;
  foreach (var __l in new FilteredElementCollector(doc).OfClass(typeof(Level)).WhereElementIsNotElementType()) { __lt++; if (__l.Pinned) __lp++; }
  res["levels_total"]=__lt; res["levels_pinned"]=__lp;
} catch { res["levels_total"]=0; res["levels_pinned"]=0; }
// --- rooms: placed / unnamed / unplaced ---
try {
  int __rt=0,__rp=0,__run=0;
  foreach (var __e in new FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Rooms).WhereElementIsNotElementType()) {
    __rt++;
    var __ap = __e.get_Parameter(BuiltInParameter.ROOM_AREA);
    bool __placed = (__ap != null && __ap.HasValue && __ap.AsDouble() > 0.0);
    if (!__placed) continue;
    __rp++;
    var __np = __e.get_Parameter(BuiltInParameter.ROOM_NAME);
    var __nu = __e.get_Parameter(BuiltInParameter.ROOM_NUMBER);
    string __nm = (__np!=null)?__np.AsString():null;
    string __numv = (__nu!=null)?__nu.AsString():null;
    if (string.IsNullOrWhiteSpace(__nm) || string.IsNullOrWhiteSpace(__numv)) __run++;
  }
  res["rooms_total"]=__rt; res["rooms_placed"]=__rp; res["rooms_unnamed"]=__run; res["rooms_unplaced"]=__rt-__rp;
} catch { res["rooms_total"]=0; }
// --- design options / worksharing ---
try { res["design_options"] = new FilteredElementCollector(doc).OfClass(typeof(DesignOption)).GetElementCount(); } catch { res["design_options"] = 0; }
try { res["workshared"] = doc.IsWorkshared; } catch { res["workshared"] = false; }
// --- MEP presence (s18/s19: seeing 0 = honest "no MEP" instead of hallucination) ---
try { res["mep_ducts"] = new FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_DuctCurves).WhereElementIsNotElementType().GetElementCount(); } catch { res["mep_ducts"]=0; }
try { res["mep_pipes"] = new FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_PipeCurves).WhereElementIsNotElementType().GetElementCount(); } catch { res["mep_pipes"]=0; }
try { res["mep_mech_equipment"] = new FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_MechanicalEquipment).WhereElementIsNotElementType().GetElementCount(); } catch { res["mep_mech_equipment"]=0; }
try { res["mep_plumbing"] = new FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_PlumbingFixtures).WhereElementIsNotElementType().GetElementCount(); } catch { res["mep_plumbing"]=0; }
// --- mandatory-param coverage (cheap, category-bounded; the s27 anchor) ---
try {
  int __wt2=0,__wmok=0;
  foreach (var __w in new FilteredElementCollector(doc).OfClass(typeof(Wall)).WhereElementIsNotElementType().Cast<Wall>()) {
    __wt2++;
    bool __has=false;
    try { var __wtp = doc.GetElement(__w.GetTypeId()) as HostObjAttributes;
      if (__wtp!=null) { var __cs=__wtp.GetCompoundStructure();
        if (__cs!=null) foreach (var __ly in __cs.GetLayers()) { if (__ly.MaterialId != ElementId.InvalidElementId) { __has=true; break; } } } } catch {}
    if (__has) __wmok++;
  }
  res["walls_total"]=__wt2; res["walls_with_material"]=__wmok;
} catch { res["walls_total"]=0; res["walls_with_material"]=0; }
try {
  int __ct=0,__cmk=0;
  foreach (var __c in new FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_StructuralColumns).WhereElementIsNotElementType()) {
    __ct++; var __mp=__c.get_Parameter(BuiltInParameter.ALL_MODEL_MARK);
    if (__mp!=null && __mp.HasValue && !string.IsNullOrWhiteSpace(__mp.AsString())) __cmk++;
  }
  res["columns_total"]=__ct; res["columns_marked"]=__cmk;
} catch { res["columns_total"]=0; res["columns_marked"]=0; }
try {
  int __dt=0,__dmk=0;
  foreach (var __d in new FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Doors).WhereElementIsNotElementType()) {
    __dt++; var __mp=__d.get_Parameter(BuiltInParameter.ALL_MODEL_MARK);
    if (__mp!=null && __mp.HasValue && !string.IsNullOrWhiteSpace(__mp.AsString())) __dmk++;
  }
  res["doors_total"]=__dt; res["doors_marked"]=__dmk;
} catch { res["doors_total"]=0; res["doors_marked"]=0; }
return res;
"""


def _i(v: Any) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def summarize_vitals(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize the raw C# vitals into the structured dict the passport renders.

    Mandatory entries are emitted only when that category has elements (an empty
    category is not a completeness problem and would just add noise)."""
    if not isinstance(raw, dict):
        return {}
    top = raw.get("warnings_top")
    mep = {
        "ducts": _i(raw.get("mep_ducts")),
        "pipes": _i(raw.get("mep_pipes")),
        "mech_equipment": _i(raw.get("mep_mech_equipment")),
        "plumbing": _i(raw.get("mep_plumbing")),
    }
    mep["present"] = any(mep[k] for k in ("ducts", "pipes", "mech_equipment", "plumbing"))

    mandatory: list[dict[str, Any]] = []

    def _add(label: str, total_key: str, filled_key: str) -> None:
        total = _i(raw.get(total_key))
        if total > 0:
            mandatory.append({"label": label, "filled": _i(raw.get(filled_key)), "total": total})

    _add("Стены / материал", "walls_total", "walls_with_material")
    _add("Колонны / Марка", "columns_total", "columns_marked")
    _add("Двери / Марка", "doors_total", "doors_marked")

    return {
        "warnings": {
            "count": _i(raw.get("warnings_count")),
            "top": [str(x) for x in top] if isinstance(top, list) else [],
        },
        "imports": _i(raw.get("cad_imports")),
        "grids": {"total": _i(raw.get("grids_total")), "pinned": _i(raw.get("grids_pinned"))},
        "levels": {"total": _i(raw.get("levels_total")), "pinned": _i(raw.get("levels_pinned"))},
        "rooms": {
            "total": _i(raw.get("rooms_total")),
            "placed": _i(raw.get("rooms_placed")),
            "unnamed": _i(raw.get("rooms_unnamed")),
            "unplaced": _i(raw.get("rooms_unplaced")),
        },
        "design_options": _i(raw.get("design_options")),
        "workshared": bool(raw.get("workshared")),
        "mep": mep,
        "mandatory": mandatory,
    }
