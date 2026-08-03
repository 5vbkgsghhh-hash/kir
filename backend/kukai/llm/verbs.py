"""Wave 1c — perception verbs ("hands").

`query_model` already gives the model select / filter / count / aggregate / group /
coverage / spatial-by-real-property (function/width/material/level) — those are the
"hands" for FINDING and MEASURING. The missing hand is **drilling into ONE element to
see all its properties** — the human "click the element, the palette opens". Today the
model writes ad-hoc `execute_revit_code` for that (a compile-storm source); `inspect`
makes it a clean, version-safe, instant verb.

Returns a structured **perceptual** result (not a raw blob) so the model "sees" the
element: id, category, type, level, and the non-empty parameters.
"""
from __future__ import annotations

from typing import Any

from kukai.query.query_builder import _csstr  # safe C# string-literal helper


def build_inspect_code(element_id: Any) -> str:
    """C# body for Execute(doc, uidoc): dump one element's category/type/level + all
    non-empty parameters. Version-safe (Id.ToString(); no .Value/.IntegerValue)."""
    idlit = _csstr(str(element_id).strip())
    L: list[str] = []
    L.append("var __res = new Dictionary<string,object>();")
    L.append(f"int __id; if (!int.TryParse({idlit}, out __id)) {{ __res[\"error\"] = \"bad_id\"; return __res; }}")
    L.append("Element __e = null; try { __e = doc.GetElement(new ElementId(__id)); } catch {}")
    L.append("if (__e == null) { __res[\"error\"] = \"not_found\"; return __res; }")
    L.append("__res[\"id\"] = __e.Id.ToString();")
    L.append("try { __res[\"category\"] = (__e.Category != null && __e.Category.Name != null) ? __e.Category.Name : \"\"; } catch {}")
    L.append("try { var __t = doc.GetElement(__e.GetTypeId()); __res[\"type\"] = (__t != null && __t.Name != null) ? __t.Name : \"\"; } catch {}")
    # level (best-effort across element kinds)
    L.append("try {")
    L.append("  var __lp = __e.get_Parameter(BuiltInParameter.WALL_BASE_CONSTRAINT);")
    L.append("  if (__lp == null) __lp = __e.get_Parameter(BuiltInParameter.LEVEL_PARAM);")
    L.append("  if (__lp == null) __lp = __e.get_Parameter(BuiltInParameter.SCHEDULE_LEVEL_PARAM);")
    L.append("  if (__lp == null) __lp = __e.get_Parameter(BuiltInParameter.FAMILY_LEVEL_PARAM);")
    L.append("  if (__lp != null && __lp.HasValue) { var __le = doc.GetElement(__lp.AsElementId()) as Level; if (__le != null && __le.Name != null) __res[\"level\"] = __le.Name; }")
    L.append("} catch {}")
    # all non-empty instance parameters
    L.append("var __p = new Dictionary<string,object>();")
    L.append("try { foreach (Parameter __pa in __e.Parameters) {")
    L.append("  if (__pa == null || __pa.Definition == null) continue;")
    L.append("  string __pn = __pa.Definition.Name; if (string.IsNullOrEmpty(__pn) || __p.ContainsKey(__pn)) continue;")
    L.append("  string __pv = null;")
    L.append("  try { __pv = __pa.AsValueString(); if (string.IsNullOrEmpty(__pv) && __pa.StorageType == StorageType.String) __pv = __pa.AsString(); } catch {}")
    L.append("  if (!string.IsNullOrEmpty(__pv)) __p[__pn] = __pv;")
    L.append("} } catch {}")
    L.append("__res[\"parameters\"] = __p;")
    L.append("return __res;")
    return "\n".join(L)


def perceive_inspect(raw: Any) -> dict[str, Any]:
    """Shape the raw bridge result into a compact perceptual dict for the model."""
    if not isinstance(raw, dict):
        return {"error": "no_result"}
    if raw.get("error"):
        return {"error": raw["error"]}
    params = raw.get("parameters") if isinstance(raw.get("parameters"), dict) else {}
    return {
        "id": raw.get("id"),
        "category": raw.get("category") or "",
        "type": raw.get("type") or "",
        "level": raw.get("level") or "",
        "param_count": len(params),
        "parameters": params,
    }
