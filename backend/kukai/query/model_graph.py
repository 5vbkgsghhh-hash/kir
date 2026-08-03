"""Wave 1 — the model graph (perception spine) + LOD-0 gestalt.

The flat passport tells DeepSeek "what types/counts exist" but nothing about how the
building is ORGANIZED — which zones sit on which level, which systems run through it.
This module adds the semantic spine **Building → Levels → Zones(rooms) → Systems(MEP)**
built from REAL Revit relationships (room→level, MEP-system membership — deterministic,
not name heuristics), and renders a compact always-in-context **LOD-0 gestalt** so the
model "sees the building whole" without dumping every element. Detail is reached lazily
via the verbs (inspect_zone / inspect) — Wave 1c.

Acquisition (one live read-only C# query, cached per content-fingerprint in model_cache)
+ render are kept separate, mirroring model_vitals. Version-safe: no .Value/.IntegerValue;
every block in its own try/catch so an exotic model can't blank the whole graph.
"""
from __future__ import annotations

import os
from typing import Any, Optional


def gestalt_v2_enabled() -> bool:
    """KUKAI_GESTALT_V2 — ModelGraph v2 flag, default OFF; read per-call so tests
    and ops can flip without a restart (same pattern as the change-witness flag).
    OFF ⇒ the v1 GRAPH_CS / summarize_graph / build_gestalt path stays byte-identical."""
    return os.getenv("KUKAI_GESTALT_V2", "0").strip().lower() in ("1", "true", "yes", "on")


# Relationship-extraction query. Body for Execute(Document doc, UIDocument uidoc).
GRAPH_CS = """
var res = new Dictionary<string,object>();
// --- zones: rooms aggregated per level (real room→level relationship) ---
try {
  var byLevel = new Dictionary<string, double[]>();   // level -> [count, unnamed, area_m2]
  foreach (var e in new FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Rooms).WhereElementIsNotElementType()) {
    var ap = e.get_Parameter(BuiltInParameter.ROOM_AREA);
    if (ap == null || !ap.HasValue || ap.AsDouble() <= 0.0) continue;   // placed only
    double area = ap.AsDouble() * 0.09290304;
    string lvl = "(no level)";
    try { var se = e as SpatialElement; if (se != null) { var lv = doc.GetElement(se.LevelId) as Level; if (lv != null && lv.Name != null) lvl = lv.Name; } } catch {}
    var np = e.get_Parameter(BuiltInParameter.ROOM_NAME);
    string nm = (np != null) ? np.AsString() : null;
    if (!byLevel.ContainsKey(lvl)) byLevel[lvl] = new double[]{0,0,0};
    var rec = byLevel[lvl];
    rec[0] = rec[0] + 1;
    if (string.IsNullOrWhiteSpace(nm)) rec[1] = rec[1] + 1;
    rec[2] = rec[2] + area;
  }
  var rooms = new Dictionary<string,object>();
  foreach (var k in byLevel.Keys) {
    var v = byLevel[k];
    var d = new Dictionary<string,object>(); d["count"]=(int)v[0]; d["unnamed"]=(int)v[1]; d["area_m2"]=System.Math.Round(v[2],1);
    rooms[k] = d;
  }
  res["rooms_by_level"] = rooms;
} catch {}
// --- systems: MEP systems with their member counts (real connector relationship) ---
try {
  var sys = new List<object>();
  foreach (var e in new FilteredElementCollector(doc).OfClass(typeof(MEPSystem))) {
    var ms = e as MEPSystem;
    if (ms == null) continue;
    int cnt = 0; try { if (ms.Elements != null) cnt = ms.Elements.Size; } catch {}
    string nm = (ms.Name != null) ? ms.Name : "(system)";
    var d = new Dictionary<string,object>(); d["name"]=nm; d["count"]=cnt;
    sys.Add(d);
  }
  res["mep_systems"] = sys;
} catch {}
return res;
"""


def _i(v: Any) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def summarize_graph(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize the raw C# graph result into the structured dict the gestalt renders."""
    if not isinstance(raw, dict):
        return {}
    rooms_raw = raw.get("rooms_by_level") if isinstance(raw.get("rooms_by_level"), dict) else {}
    rooms: dict[str, dict[str, Any]] = {}
    for lvl, rec in rooms_raw.items():
        if isinstance(rec, dict):
            rooms[str(lvl)] = {
                "count": _i(rec.get("count")),
                "unnamed": _i(rec.get("unnamed")),
                "area_m2": float(rec.get("area_m2") or 0),
            }
    systems: list[dict[str, Any]] = []
    for s in (raw.get("mep_systems") or []):
        if isinstance(s, dict) and _i(s.get("count")) > 0:
            systems.append({"name": str(s.get("name") or "?"), "count": _i(s.get("count"))})
    return {"rooms_by_level": rooms, "mep_systems": systems}


# ── LOD-0 gestalt render ────────────────────────────────────────────────────

def _levels_sorted(basic_ctx: dict[str, Any]) -> list[dict[str, Any]]:
    levels = basic_ctx.get("levels") or []
    return sorted(
        (lv for lv in levels if isinstance(lv, dict)),
        key=lambda lv: lv.get("elevation_m", 0.0),
    )


def _elems_per_level(detailed: dict[str, Any]) -> dict[str, int]:
    """Sum element count per level from the pushed distribution_by_level, if present."""
    dist = detailed.get("distribution_by_level") if isinstance(detailed, dict) else None
    out: dict[str, int] = {}
    if isinstance(dist, dict):
        for lvl, cats in dist.items():
            if isinstance(cats, dict):
                out[str(lvl)] = sum(_i(n) for n in cats.values())
    return out


def build_gestalt(basic_ctx: dict[str, Any], detailed: dict[str, Any], graph: dict[str, Any]) -> str:
    """Compact always-in-context LOD-0 map (Building → Levels → Zones → Systems).
    Returns "" if there is nothing meaningful to show."""
    if not isinstance(graph, dict) or not graph:
        return ""
    levels = _levels_sorted(basic_ctx)
    rooms_by_level = graph.get("rooms_by_level") or {}
    systems = graph.get("mep_systems") or []
    if not levels and not rooms_by_level and not systems:
        return ""

    name = basic_ctx.get("document_name", "Модель")
    cats = basic_ctx.get("categories") or []
    total = sum(_i(c.get("count")) for c in cats if isinstance(c, dict))
    lines = [
        "### КАРТА МОДЕЛИ (LOD0 — крупно, как видит человек; детали — inspect_zone/inspect)",
        f"{name} · {total} элементов · {len(levels)} уровней",
    ]
    per_level = _elems_per_level(detailed)
    if levels:
        # Cap for tall models (a 108-level tower must not dump 108 lines): prefer the
        # levels that carry content (rooms or elements); note the rest.
        _MAX_LEVELS = 28
        shown = levels
        omitted = 0
        if len(levels) > _MAX_LEVELS:
            def _weight(lv):
                ln = lv.get("name", "?")
                rb = rooms_by_level.get(ln) or {}
                return per_level.get(ln, 0) + (rb.get("count", 0) * 1000)
            keep = sorted(levels, key=_weight, reverse=True)[:_MAX_LEVELS]
            keepset = {id(x) for x in keep}
            shown = [lv for lv in levels if id(lv) in keepset]  # back to elevation order
            omitted = len(levels) - len(shown)
        lines.append("Уровни (снизу вверх):")
        for lv in shown:
            ln = lv.get("name", "?")
            elev = lv.get("elevation_m", 0.0)
            seg = f"  {ln} ({elev:+.1f}м)"
            n = per_level.get(ln)
            if n:
                seg += f" — {n} эл"
            rb = rooms_by_level.get(ln)
            if isinstance(rb, dict) and rb.get("count"):
                seg += (f" · {rb['count']} помещ"
                        + (f", {rb['area_m2']:.0f} м²" if rb.get("area_m2") else "")
                        + (f", без имени {rb['unnamed']}" if rb.get("unnamed") else ""))
            lines.append(seg)
        if omitted:
            lines.append(f"  (+{omitted} уровней — get_model_details spatial)")
    # rooms on levels not in the levels list (e.g. "(no level)")
    orphan = [k for k in rooms_by_level if k not in {lv.get("name") for lv in levels}]
    for k in orphan:
        rb = rooms_by_level[k]
        if rb.get("count"):
            lines.append(f"  {k} · {rb['count']} помещ")
    if systems:
        top = ", ".join(f"{s['name']} ({s['count']})" for s in systems[:8])
        lines.append(f"Системы MEP: {top}")
    else:
        lines.append("Системы MEP: нет")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
# ModelGraph v2 (flag KUKAI_GESTALT_V2, default OFF)
#
# The v1 spine is rooms-only: a room-less coordination model (the operator's
# "Коорд файл Муза": 126 walls, 0 rooms) renders an empty gestalt. v2 keeps the
# room/MEP relationships and ADDS the structure that exists in EVERY model:
# levels+elevations (collected in C#, self-contained), per-level counts of the
# major structural categories, grids, linked models, overall bbox, worksets.
# Still ONE read-only execute; every block in its own try/catch; version-safe
# for Revit 2021-2026 (no .Value/.IntegerValue, no version-gated API).
# ═══════════════════════════════════════════════════════════════════════════

# The v1 blocks (rooms_by_level + mep_systems) are REUSED verbatim by slicing
# GRAPH_CS before its `return res;` — one source of truth, v1/v2 can't drift.
_GRAPH_V2_EXTRA_CS = """
// --- levels: name + elevation, collected here so the spine works even when the
// --- pushed context is thin (room-less/coordination models) ---
try {
  var lvls = new List<object>();
  foreach (var le in new FilteredElementCollector(doc).OfClass(typeof(Level)).WhereElementIsNotElementType()) {
    var lv = le as Level; if (lv == null) continue;
    var d = new Dictionary<string,object>();
    d["name"] = (lv.Name != null) ? lv.Name : "?";
    double em = 0; try { em = lv.Elevation * 0.3048; } catch {}
    d["elev_m"] = System.Math.Round(em, 2);
    lvls.Add(d);
  }
  res["levels"] = lvls;
} catch {}
// --- grids: names + count (the coordination-model skeleton) ---
try {
  var gnames = new List<string>(); int gtotal = 0;
  foreach (var ge in new FilteredElementCollector(doc).OfClass(typeof(Grid)).WhereElementIsNotElementType()) {
    gtotal++;
    if (gnames.Count < 40) { try { if (ge.Name != null) gnames.Add(ge.Name); } catch {} }
  }
  var gd = new Dictionary<string,object>(); gd["count"]=gtotal; gd["names"]=gnames;
  res["grids"] = gd;
} catch {}
// --- linked models: name + loaded state + element count when the link doc is open ---
try {
  var links = new List<object>();
  foreach (var e in new FilteredElementCollector(doc).OfClass(typeof(RevitLinkInstance))) {
    if (links.Count >= 20) break;
    var li = e as RevitLinkInstance; if (li == null) continue;
    var d = new Dictionary<string,object>();
    string nm = "(link)"; try { if (li.Name != null) nm = li.Name; } catch {}
    d["name"] = nm;
    bool loaded = false; int lcnt = -1;
    try {
      var ldoc = li.GetLinkDocument();
      if (ldoc != null) {
        loaded = true;
        try { lcnt = new FilteredElementCollector(ldoc).WhereElementIsNotElementType().GetElementCount(); } catch {}
      }
    } catch {}
    d["loaded"] = loaded;
    if (lcnt >= 0) d["elements"] = lcnt;
    links.Add(d);
  }
  res["links"] = links;
} catch {}
// --- per-level counts of major structural categories + overall bbox (one pass) ---
try {
  var catmap = new object[][] {
    new object[]{ "walls", BuiltInCategory.OST_Walls },
    new object[]{ "floors", BuiltInCategory.OST_Floors },
    new object[]{ "columns", BuiltInCategory.OST_StructuralColumns },
    new object[]{ "framing", BuiltInCategory.OST_StructuralFraming },
  };
  var byLvl = new Dictionary<string, Dictionary<string,object>>();
  double minx=double.MaxValue, miny=double.MaxValue, minz=double.MaxValue;
  double maxx=double.MinValue, maxy=double.MinValue, maxz=double.MinValue;
  bool anybb = false;
  foreach (var pair in catmap) {
    string key = (string)pair[0]; var bic = (BuiltInCategory)pair[1];
    foreach (var e in new FilteredElementCollector(doc).OfCategory(bic).WhereElementIsNotElementType()) {
      string lvl = "(no level)";
      try { var lv = doc.GetElement(e.LevelId) as Level; if (lv != null && lv.Name != null) lvl = lv.Name; } catch {}
      if (!byLvl.ContainsKey(lvl)) byLvl[lvl] = new Dictionary<string,object>();
      var rec = byLvl[lvl];
      int cur = 0; if (rec.ContainsKey(key)) cur = (int)rec[key];
      rec[key] = cur + 1;
      try {
        var bb = e.get_BoundingBox(null);
        if (bb != null) {
          anybb = true;
          if (bb.Min.X < minx) minx = bb.Min.X; if (bb.Min.Y < miny) miny = bb.Min.Y; if (bb.Min.Z < minz) minz = bb.Min.Z;
          if (bb.Max.X > maxx) maxx = bb.Max.X; if (bb.Max.Y > maxy) maxy = bb.Max.Y; if (bb.Max.Z > maxz) maxz = bb.Max.Z;
        }
      } catch {}
    }
  }
  res["cat_by_level"] = byLvl;
  if (anybb) {
    var bbox = new Dictionary<string,object>();
    bbox["dx_m"] = System.Math.Round((maxx - minx) * 0.3048, 1);
    bbox["dy_m"] = System.Math.Round((maxy - miny) * 0.3048, 1);
    bbox["dz_m"] = System.Math.Round((maxz - minz) * 0.3048, 1);
    res["bbox_m"] = bbox;
  }
} catch {}
// --- worksets (cheap only when workshared) ---
try {
  int wcount = 0;
  if (doc.IsWorkshared) { wcount = new FilteredWorksetCollector(doc).OfKind(WorksetKind.UserWorkset).ToWorksets().Count; }
  res["worksets"] = wcount;
} catch {}
return res;
"""

assert GRAPH_CS.rstrip().endswith("return res;"), "GRAPH_CS shape changed — fix GRAPH_CS_V2 composition"
GRAPH_CS_V2 = GRAPH_CS.rsplit("return res;", 1)[0] + _GRAPH_V2_EXTRA_CS.lstrip("\n")

# Human labels for the cat_by_level keys, in render order.
_V2_CAT_LABELS = (("walls", "стены"), ("floors", "перекрытия"),
                  ("columns", "колонны"), ("framing", "балки"))


def summarize_graph_v2(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize the raw GRAPH_CS_V2 result. Superset of summarize_graph plus the
    v2 keys; carries a ``"v2": True`` marker so render/dispatch pick the v2 path
    by DATA PRESENCE (a v2 graph can only exist when the flag was on at fetch
    time → flag OFF stays byte-identical without any flag check downstream)."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {"v2": True, **summarize_graph(raw)}
    # grids
    g = raw.get("grids") if isinstance(raw.get("grids"), dict) else {}
    out["grids"] = {
        "count": _i(g.get("count")),
        "names": [str(n) for n in (g.get("names") or []) if n][:40],
    }
    # links
    links: list[dict[str, Any]] = []
    for lk in (raw.get("links") or []):
        if not isinstance(lk, dict):
            continue
        rec: dict[str, Any] = {"name": str(lk.get("name") or "(link)"),
                               "loaded": bool(lk.get("loaded"))}
        if lk.get("elements") is not None:
            rec["elements"] = _i(lk.get("elements"))
        links.append(rec)
    out["links"] = links
    # per-level major-category counts (keep only positive counts of known keys)
    cbl_raw = raw.get("cat_by_level") if isinstance(raw.get("cat_by_level"), dict) else {}
    cbl: dict[str, dict[str, int]] = {}
    for lvl, rec in cbl_raw.items():
        if not isinstance(rec, dict):
            continue
        row = {k: _i(rec.get(k)) for k, _ in _V2_CAT_LABELS if _i(rec.get(k)) > 0}
        if row:
            cbl[str(lvl)] = row
    out["cat_by_level"] = cbl
    # levels (self-collected: the room-less spine's backbone)
    levels: list[dict[str, Any]] = []
    for lv in (raw.get("levels") or []):
        if isinstance(lv, dict) and lv.get("name"):
            try:
                elev = float(lv.get("elev_m") or 0)
            except (TypeError, ValueError):
                elev = 0.0
            levels.append({"name": str(lv["name"]), "elev_m": elev})
    out["levels"] = sorted(levels, key=lambda x: x["elev_m"])
    # bbox
    bb = raw.get("bbox_m") if isinstance(raw.get("bbox_m"), dict) else None
    if bb:
        try:
            out["bbox_m"] = {k: float(bb.get(k) or 0) for k in ("dx_m", "dy_m", "dz_m")}
        except (TypeError, ValueError):
            pass
    out["worksets"] = _i(raw.get("worksets"))
    return out


def _v2_level_stack(basic_ctx: dict[str, Any], graph: dict[str, Any]) -> list[dict[str, Any]]:
    """Level list for the v2 spine: pushed context levels (elevation_m) when
    present, else the graph's self-collected levels (elev_m) — so a thin/first-turn
    context still yields a full stack. Normalized to {name, elevation_m}."""
    ctx_levels = _levels_sorted(basic_ctx)
    if ctx_levels:
        return [{"name": lv.get("name", "?"), "elevation_m": lv.get("elevation_m", 0.0)}
                for lv in ctx_levels]
    return [{"name": lv["name"], "elevation_m": lv["elev_m"]}
            for lv in (graph.get("levels") or []) if isinstance(lv, dict) and "name" in lv]


def build_gestalt_v2(basic_ctx: dict[str, Any], detailed: dict[str, Any], graph: dict[str, Any]) -> str:
    """LOD-0 map v2 — renders a useful spine even with ZERO rooms (coordination /
    structural models): levels stack with elevations + what-is-on-each-level
    (major categories), grids, links, bbox, worksets — plus the v1 zones/systems
    when they exist. Returns "" only when there is truly nothing to show."""
    if not isinstance(graph, dict) or not graph:
        return ""
    basic_ctx = basic_ctx if isinstance(basic_ctx, dict) else {}
    detailed = detailed if isinstance(detailed, dict) else {}
    rooms_by_level = graph.get("rooms_by_level") or {}
    systems = graph.get("mep_systems") or []
    grids = graph.get("grids") or {}
    links = graph.get("links") or []
    cat_by_level = graph.get("cat_by_level") or {}
    levels = _v2_level_stack(basic_ctx, graph)
    if not (levels or rooms_by_level or systems or cat_by_level or links or grids.get("count")):
        return ""

    name = basic_ctx.get("document_name", "Модель")
    cats = basic_ctx.get("categories") or []
    total = sum(_i(c.get("count")) for c in cats if isinstance(c, dict))
    head = f"{name} · {total} элементов · {len(levels)} уровней"
    bbox = graph.get("bbox_m") or {}
    if bbox.get("dx_m") or bbox.get("dy_m") or bbox.get("dz_m"):
        head += (f" · габарит ~{bbox.get('dx_m', 0):.0f}×{bbox.get('dy_m', 0):.0f}"
                 f"×{bbox.get('dz_m', 0):.0f} м")
    lines = [
        "### КАРТА МОДЕЛИ (LOD0 — крупно, как видит человек; детали — inspect_zone/inspect)",
        head,
    ]

    per_level = _elems_per_level(detailed)
    if not per_level and cat_by_level:
        # No pushed distribution (thin/first-turn context) → derive per-level totals
        # from the graph's own structural counts, so the stack is never bare.
        per_level = {lvl: sum(rec.values()) for lvl, rec in cat_by_level.items()}
    if levels:
        _MAX_LEVELS = 28
        shown = levels
        omitted = 0
        if len(levels) > _MAX_LEVELS:
            def _weight(lv):
                ln = lv.get("name", "?")
                rb = rooms_by_level.get(ln) or {}
                return per_level.get(ln, 0) + (rb.get("count", 0) * 1000)
            keep = sorted(levels, key=_weight, reverse=True)[:_MAX_LEVELS]
            keepset = {id(x) for x in keep}
            shown = [lv for lv in levels if id(lv) in keepset]  # back to elevation order
            omitted = len(levels) - len(shown)
        lines.append("Уровни (снизу вверх):")
        for lv in shown:
            ln = lv.get("name", "?")
            elev = lv.get("elevation_m", 0.0)
            seg = f"  {ln} ({elev:+.1f}м)"
            n = per_level.get(ln)
            if n:
                seg += f" — {n} эл"
            rb = rooms_by_level.get(ln)
            if isinstance(rb, dict) and rb.get("count"):
                seg += (f" · {rb['count']} помещ"
                        + (f", {rb['area_m2']:.0f} м²" if rb.get("area_m2") else "")
                        + (f", без имени {rb['unnamed']}" if rb.get("unnamed") else ""))
            cb = cat_by_level.get(ln)
            if isinstance(cb, dict) and cb:
                seg += " · " + ", ".join(
                    f"{label} {cb[key]}" for key, label in _V2_CAT_LABELS if cb.get(key))
            lines.append(seg)
        if omitted:
            lines.append(f"  (+{omitted} уровней — get_model_details spatial)")
    # rooms/structure on level names outside the stack (e.g. "(no level)")
    stack_names = {lv.get("name") for lv in levels}
    for k in [k for k in rooms_by_level if k not in stack_names]:
        rb = rooms_by_level[k]
        if isinstance(rb, dict) and rb.get("count"):
            lines.append(f"  {k} · {rb['count']} помещ")
    for k in [k for k in cat_by_level if k not in stack_names and k not in rooms_by_level]:
        cb = cat_by_level[k]
        if isinstance(cb, dict) and cb:
            lines.append("  " + str(k) + " · " + ", ".join(
                f"{label} {cb[key]}" for key, label in _V2_CAT_LABELS if cb.get(key)))
    if not rooms_by_level:
        lines.append("Помещений нет (координационная/конструктивная модель) — "
                     "ориентируйся по уровням, осям и категориям; НЕ выдумывай зоны.")
    gcount = _i(grids.get("count"))
    if gcount:
        gnames = [str(x) for x in (grids.get("names") or [])][:15]
        gseg = f"Оси: {gcount}"
        if gnames:
            gseg += " (" + ", ".join(gnames) + (", …" if gcount > len(gnames) else "") + ")"
        lines.append(gseg)
    if links:
        lparts = []
        for lk in links[:8]:
            seg = lk.get("name", "(link)")
            seg += " [загружена" if lk.get("loaded") else " [выгружена"
            if lk.get("elements") is not None:
                seg += f", ~{lk['elements']} эл"
            seg += "]"
            lparts.append(seg)
        more = f" (+{len(links) - 8})" if len(links) > 8 else ""
        lines.append(f"Связи ({len(links)}): " + "; ".join(lparts) + more)
    if systems:
        top = ", ".join(f"{s['name']} ({s['count']})" for s in systems[:8])
        lines.append(f"Системы MEP: {top}")
    else:
        lines.append("Системы MEP: нет")
    wk = _i(graph.get("worksets"))
    if wk:
        lines.append(f"Рабочие наборы: {wk}")
    return "\n".join(lines)
