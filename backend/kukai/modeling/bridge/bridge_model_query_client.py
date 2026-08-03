"""BridgeModelQueryClient — ModelQueryClient over the EXISTING exec channel.

Instead of a new bridge endpoint (the framework's original Phase-5 deferral in
model_query_client.py:3-6), this runs read-only FilteredElementCollector C# via
an injected ``exec_fn`` and parses the returned native dicts/lists into the
framework's pydantic types.

``exec_fn(code: str, timeout_ms: int) -> Any`` contract:
  * returns the C# ``return``ed value, already UNWRAPPED from the admin-remote
    envelope ``body["result"]`` — a list (families/levels/grids) or a dict
    (properties/geometry);
  * on a bridge/transport error returns ``{"error": True, "message": ...}``.
  The exec_fn owns transport: POST /admin/remote/exec/{device}, the
  ``body["result"]`` unwrap, and 503 round-robin retry across uvicorn workers.

Verified live on the 'Муза' doc:
  * the C# ``return res;`` dict surfaces at ``body.result`` (not the HTTP body);
  * element ids come back as STRINGS via ``Id.ToString()`` — version-safe,
    never ``.IntegerValue``/``.Value`` (which don't exist on Revit 2024+).
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from kukai.modeling.bridge.model_query_client import (
    ElementGeometry,
    GridInfo,
    LevelInfo,
)
from kukai.modeling.schemas.resolver import FamilySymbolCandidate

ExecFn = Callable[[str, int], Awaitable[Any]]


# ── C# query templates (placeholders, not f-strings, to avoid brace escaping) ──

_FAMILIES = """
var res = new List<object>();
try {
  BuiltInCategory bic = (BuiltInCategory)Enum.Parse(typeof(BuiltInCategory), "__CAT__");
  foreach (FamilySymbol fs in new FilteredElementCollector(doc).OfCategory(bic).OfClass(typeof(FamilySymbol)).WhereElementIsElementType()) {
    var d = new Dictionary<string,object>();
    d["family_symbol_id"] = fs.Id.ToString();
    d["name"] = fs.Name;
    try { d["family_name"] = fs.Family != null ? fs.Family.Name : ""; } catch { d["family_name"] = ""; }
    try { d["category"] = fs.Category != null ? fs.Category.Name : ""; } catch { d["category"] = ""; }
    res.Add(d);
  }
} catch {}
return res;
"""

_LEVELS = """
var res = new List<object>();
foreach (Level lv in new FilteredElementCollector(doc).OfClass(typeof(Level)).WhereElementIsNotElementType()) {
  try { var d = new Dictionary<string,object>(); d["level_id"]=lv.Id.ToString(); d["name"]=lv.Name; d["elevation_mm"]=lv.Elevation*304.8; res.Add(d); } catch {}
}
return res;
"""

# Axis convention VERIFIED LIVE on Муза (critic B-2 fix): the resolver reads
# axis=="horizontal" as the X coordinate and "vertical" as Y. A grid line running
# ALONG Y (constant X) supplies X => "horizontal"; along X (constant Y) => "vertical".
_GRIDS = """
var res = new List<object>();
foreach (Grid g in new FilteredElementCollector(doc).OfClass(typeof(Grid)).WhereElementIsNotElementType()) {
  try {
    var d = new Dictionary<string,object>(); d["grid_id"]=g.Id.ToString(); d["name"]=g.Name;
    string axis="unknown"; double pos=0.0;
    var ln = g.Curve as Line;
    if (ln != null) {
      var dir = ln.Direction; var p0 = ln.GetEndPoint(0);
      if (Math.Abs(dir.Y) >= Math.Abs(dir.X)) { axis="horizontal"; pos = p0.X*304.8; }
      else { axis="vertical"; pos = p0.Y*304.8; }
    }
    d["axis"]=axis; d["position_mm"]=pos; res.Add(d);
  } catch {}
}
return res;
"""

_PROPS = """
var res = new Dictionary<string,object>();
try {
  var el = doc.GetElement(new ElementId(__EID__));
  if (el == null) return res;
  res["FamilySymbolId"] = el.GetTypeId().ToString();
  try { var mk = el.get_Parameter(BuiltInParameter.ALL_MODEL_MARK); if (mk!=null && mk.HasValue) res["Mark"] = mk.AsString() ?? ""; } catch {}
  try { var lp = el.get_Parameter(BuiltInParameter.FAMILY_LEVEL_PARAM); if (lp==null) lp = el.get_Parameter(BuiltInParameter.SCHEDULE_LEVEL_PARAM);
        if (lp!=null && lp.HasValue) { var lvl = doc.GetElement(lp.AsElementId()) as Level; if (lvl!=null) res["Level"] = lvl.Name; } } catch {}
  foreach (Parameter p in el.Parameters) {
    try {
      string v = "";
      switch (p.StorageType) {
        case StorageType.String: v = p.AsString() ?? ""; break;
        case StorageType.Integer: v = p.AsInteger().ToString(); break;
        case StorageType.Double: v = p.AsValueString() ?? p.AsDouble().ToString(); break;
        case StorageType.ElementId: v = p.AsElementId().ToString(); break;
      }
      if (p.Definition != null && !res.ContainsKey(p.Definition.Name)) res[p.Definition.Name] = v;
    } catch {}
  }
} catch {}
return res;
"""

_GEOM = """
var res = new Dictionary<string,object>();
try {
  var el = doc.GetElement(new ElementId(__EID__));
  if (el == null) return res;
  var bb = el.get_BoundingBox(null);
  if (bb != null) {
    res["min"] = new List<object>{ bb.Min.X*304.8, bb.Min.Y*304.8, bb.Min.Z*304.8 };
    res["max"] = new List<object>{ bb.Max.X*304.8, bb.Max.Y*304.8, bb.Max.Z*304.8 };
    res["centroid"] = new List<object>{ (bb.Min.X+bb.Max.X)/2.0*304.8, (bb.Min.Y+bb.Max.Y)/2.0*304.8, (bb.Min.Z+bb.Max.Z)/2.0*304.8 };
  }
  var fi = el as FamilyInstance;
  try { if (fi != null && fi.Host != null) res["host_element_id"] = fi.Host.Id.ToString(); } catch {}
  try { if (el.LevelId != null && el.LevelId != ElementId.InvalidElementId) res["level_id"] = el.LevelId.ToString(); } catch {}
} catch {}
return res;
"""


def _ok(res: Any) -> Any:
    if isinstance(res, dict) and res.get("error"):
        raise RuntimeError(f"bridge query failed: {res.get('message', 'unknown')}")
    return res


class BridgeModelQueryClient:
    """Read-only ModelQueryClient over the live exec channel."""

    def __init__(self, exec_fn: ExecFn, *, revit_version: str = "2026", timeout_ms: int = 15000) -> None:
        self._exec = exec_fn
        self._revit_version = revit_version
        self._timeout_ms = timeout_ms

    async def _run(self, code: str) -> Any:
        return _ok(await self._exec(code, self._timeout_ms))

    def _eid(self, element_id: int) -> str:
        # Revit 2024+ uses ElementId(long); pre-2024 uses ElementId(int).
        try:
            year = int(str(self._revit_version)[:4])
        except (ValueError, TypeError):
            year = 2026
        return f"{int(element_id)}L" if year >= 2024 else f"{int(element_id)}"

    async def query_families(self, category: str | None = None) -> list[FamilySymbolCandidate]:
        rows = await self._run(_FAMILIES.replace("__CAT__", category or "OST_GenericModel"))
        out: list[FamilySymbolCandidate] = []
        for r in rows or []:
            try:
                out.append(FamilySymbolCandidate(
                    family_symbol_id=int(r["family_symbol_id"]),
                    name=str(r.get("name", "")),
                    family_name=str(r.get("family_name", "")),
                    category=str(r.get("category", "")),
                ))
            except (KeyError, ValueError, TypeError):
                continue
        return out

    async def query_levels(self) -> list[LevelInfo]:
        rows = await self._run(_LEVELS)
        out: list[LevelInfo] = []
        for r in rows or []:
            try:
                out.append(LevelInfo(level_id=int(r["level_id"]), name=str(r["name"]), elevation_mm=float(r["elevation_mm"])))
            except (KeyError, ValueError, TypeError):
                continue
        return out

    async def query_grids(self) -> list[GridInfo]:
        rows = await self._run(_GRIDS)
        out: list[GridInfo] = []
        for r in rows or []:
            try:
                out.append(GridInfo(grid_id=int(r["grid_id"]), name=str(r["name"]),
                                    axis=str(r.get("axis", "unknown")), position_mm=float(r.get("position_mm", 0.0))))
            except (KeyError, ValueError, TypeError):
                continue
        return out

    async def query_parameter_info(self, family_symbol_id: int) -> dict[str, tuple[str, str]]:
        # Deferred: semantic-name -> actual-name mapping is not derivable from Revit.
        # Empty map is valid (resolver yields an empty parameter_map). Element types
        # that need instance params must supply a map config later.
        return {}

    async def query_element_properties(self, element_id: int) -> dict[str, str]:
        row = await self._run(_PROPS.replace("__EID__", self._eid(element_id)))
        if not isinstance(row, dict):
            return {}
        return {str(k): str(v) for k, v in row.items()}

    async def query_element_geometry(self, element_id: int) -> ElementGeometry:
        row = await self._run(_GEOM.replace("__EID__", self._eid(element_id)))
        row = row if isinstance(row, dict) else {}

        def _t3(key: str) -> tuple[float, float, float]:
            v = row.get(key) or [0.0, 0.0, 0.0]
            return (float(v[0]), float(v[1]), float(v[2]))

        def _oid(key: str) -> int | None:
            v = row.get(key)
            try:
                return int(v) if v is not None else None
            except (ValueError, TypeError):
                return None

        return ElementGeometry(
            element_id=int(element_id),
            bounding_box_min_mm=_t3("min"),
            bounding_box_max_mm=_t3("max"),
            centroid_mm=_t3("centroid"),
            host_element_id=_oid("host_element_id"),
            level_id=_oid("level_id"),
        )
