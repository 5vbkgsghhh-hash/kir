"""ModelGraph v3 — geometry-true spatial perception (flag KUKAI_GRAPH_V3, default OFF).

Why v3 (live evidence, 2026-07-05, five real models):
  * Муза (22-storey structural tower, 81 m): v2 attributed per storey via
    ``Element.LevelId`` → EVERY element collapsed onto "1 этаж"; the agent's
    mental picture was a 1-storey slab.
  * 158-2025-АР (18 storeys): LevelId clean — v2 was right. v3 must match it.
  * ВК_R24 / 57 ОВ1 (MEP), 1009-FIV-K1-FAS (facade): v2 collected only
    walls/floors/columns/framing → ``cat_by_level == {}`` — a full MEP model
    rendered as an EMPTY building.

Architecture — sensing in C#, spatial reasoning in Python:
  * GRAPH_CS_V3 (ONE read-only execute) runs a discipline-complete census of
    physical elements: category-key → quantized ``(z_base_dm, z_top_dm)``
    histogram (``zhist``), plus levels (with ProjectElevation — the same frame
    as geometry), grid lines with axis+position, links, bbox, worksets. It does
    NO storey logic — dumb, version-safe collection only.
  * summarize_graph_v3 (pure Python, fully unit-tested) builds STOREY BANDS
    from level elevations (sorted; duplicate/thin <1.8 m levels merged; a
    below-lowest bucket; a synthetic band for 0-level models) and attributes
    each histogram cell by geometry: base-anchored (bbox z_base + 0.35 m snap)
    for standing categories, top-anchored (z_top) for floors/framing (a slab's
    top IS its level). Multi-band spanners (columns/walls/risers) count once at
    their base band and are reported separately. It then detects the "typical
    floor": consecutive bands with similar profiles collapse into runs.
  * build_gestalt_v3 renders the minimal 3D skeleton: envelope (bbox), plan
    skeleton (grid families + extents + spacing), vertical stack (bands with
    real elevations/heights; typical runs collapsed), massing (per-band
    totals), zones (rooms per band), MEP systems, links. Hard token budget
    with graceful "query for detail" tails.

Flag OFF ⇒ nothing here runs: chat_ws dispatch and the passport pick v1/v2 by
flag/data-presence exactly as before (byte-identical, pinned by the existing
suites). A cached v3 graph carries ``"v3": True`` so downstream render/API
dispatch is by DATA PRESENCE — no flag checks at render time.

KUKAI_GRAPH_V3_CLEAN (default OFF) — honest census (live audit of
"DODELKA_20_04_LOGO_0001", 2026-07-04: curtain grid schemes 226 + sketches 96
+ masses 4 + balusters 3 leaked into «прочее»/физ. элементы; «Системы MEP:
нет» while 12 pipes exist; no building semantics). Because chat_ws imports the
GRAPH_CS_V3 constant, the C# is NOT flag-dispatched — it senses ADDITIVELY:
non-building garbage goes to NEW census keys (cgrids/sketch/mass, plus
balusters/ramps for real sub-elements) without touching ``counted`` or any
existing key. Python then classifies by flag, read ONCE in
``summarize_graph_v3``:
  * OFF — the new keys fold back into "other": the summarized graph is
    dict-identical to the old C#'s output (deploy-window safety, pinned by
    ``test_dodelka_off_identical_to_legacy_merge``);
  * ON  — cgrids/sketch/mass → a ``nonbuilding`` bucket EXCLUDED from the
    physical count and the storey profiles (disclosed as its own gestalt
    line); balusters fold into railings; ramps get a labeled bucket; an
    ``mep_elements`` census-truth dict powers an honest MEP line («трубы 12
    (систем не задано)» instead of «нет»); a deterministic building-shape
    summary (``shape``) is derived from counts/grid only — never invented.
Render remains data-presence-driven: OFF graphs carry none of the new keys,
so the render path is byte-identical without any flag read. NOTE: cached v3
graphs keep their shape until write-invalidation/TTL after a flag flip.
"""
from __future__ import annotations

import math
import os
import re
from bisect import bisect_right
from statistics import median
from typing import Any, Optional

from kukai.query.model_graph import GRAPH_CS, _i, summarize_graph


def graph_v3_enabled() -> bool:
    """KUKAI_GRAPH_V3 — ModelGraph v3 flag, default OFF; read per-call so tests
    and ops can flip without a restart (same pattern as KUKAI_GESTALT_V2)."""
    return os.getenv("KUKAI_GRAPH_V3", "0").strip().lower() in ("1", "true", "yes", "on")


def graph_v3_clean_enabled() -> bool:
    """KUKAI_GRAPH_V3_CLEAN — honest-census kill-switch, default OFF (⇒ the
    summarized graph is byte-identical to pre-clean v3). Read per-call, in
    ``summarize_graph_v3`` ONLY — render stays data-presence-driven."""
    return os.getenv("KUKAI_GRAPH_V3_CLEAN", "0").strip().lower() in ("1", "true", "yes", "on")


# ═══════════════════════════════════════════════════════════════════════════
# GRAPH_CS_V3 — the acquisition query (body for Execute(doc, uidoc))
#
# Version-safe 2021-2026: no .Value/.IntegerValue, no version-gated API
# (ElementId(BuiltInCategory) ctor, Level.ProjectElevation, Grid.Curve,
# CategoryType are all ancient). Every block in its own try/catch. Read-only:
# no Transaction — also keeps the write-marker heuristic from invalidating the
# cache this query itself just filled.
#
# The census is ONE pass over non-type elements: physical = Model category with
# a 3D bbox. Rooms/areas/links/levels/grids/model-lines and the classic
# bbox-poison singletons (base points, scope boxes, point clouds) are excluded.
# Elements without a bbox fall back to LevelId (emitted per level name so
# Python can still band them); groups/imports/link instances are skipped
# (members are iterated anyway / not part of THIS building).
# ═══════════════════════════════════════════════════════════════════════════

_GRAPH_V3_EXTRA_CS = """
// --- levels: display elevation + ProjectElevation (the geometry frame used for
// --- storey banding — Level.Elevation can be survey-based and off-frame) ---
try {
  var lvls = new List<object>();
  foreach (var le in new FilteredElementCollector(doc).OfClass(typeof(Level)).WhereElementIsNotElementType()) {
    var lv = le as Level; if (lv == null) continue;
    var d = new Dictionary<string,object>();
    d["name"] = (lv.Name != null) ? lv.Name : "?";
    double em = 0; try { em = lv.Elevation * 0.3048; } catch {}
    double pm = em; try { pm = lv.ProjectElevation * 0.3048; } catch {}
    d["elev_m"] = System.Math.Round(em, 2);
    d["proj_elev_m"] = System.Math.Round(pm, 2);
    lvls.Add(d);
  }
  res["levels"] = lvls;
} catch {}
// --- grids: name + axis + position (the plan skeleton: extents and spacing) ---
try {
  var gitems = new List<object>(); int gtotal = 0;
  foreach (var ge in new FilteredElementCollector(doc).OfClass(typeof(Grid)).WhereElementIsNotElementType()) {
    gtotal++;
    if (gitems.Count >= 150) continue;
    try {
      var g = ge as Grid; if (g == null) continue;
      var d = new Dictionary<string,object>();
      d["name"] = (g.Name != null) ? g.Name : "?";
      string ax = "o"; double pos = 0; bool haspos = false;
      try {
        var ln = g.Curve as Line;
        if (ln != null) {
          var dir = ln.Direction; var p0 = ln.GetEndPoint(0);
          if (System.Math.Abs(dir.Y) > 0.9) { ax = "x"; pos = p0.X * 0.3048; haspos = true; }
          else if (System.Math.Abs(dir.X) > 0.9) { ax = "y"; pos = p0.Y * 0.3048; haspos = true; }
        } else if (g.Curve != null) { ax = "arc"; }
      } catch {}
      d["ax"] = ax;
      if (haspos) d["pos_m"] = System.Math.Round(pos, 2);
      gitems.Add(d);
    } catch {}
  }
  var gd = new Dictionary<string,object>(); gd["count"] = gtotal; gd["items"] = gitems;
  res["grids_geo"] = gd;
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
// --- physical census: ONE pass, category-key -> quantized (z_base,z_top) histogram.
// --- Storey attribution happens in Python (testable); C# only senses geometry. ---
try {
  var catkey = new Dictionary<ElementId,string>();
  catkey[new ElementId(BuiltInCategory.OST_Walls)] = "walls";
  catkey[new ElementId(BuiltInCategory.OST_Floors)] = "floors";
  catkey[new ElementId(BuiltInCategory.OST_StructuralColumns)] = "columns";
  catkey[new ElementId(BuiltInCategory.OST_Columns)] = "columns";
  catkey[new ElementId(BuiltInCategory.OST_StructuralFraming)] = "framing";
  catkey[new ElementId(BuiltInCategory.OST_StructuralFoundation)] = "foundation";
  catkey[new ElementId(BuiltInCategory.OST_Roofs)] = "roofs";
  catkey[new ElementId(BuiltInCategory.OST_Stairs)] = "stairs";
  catkey[new ElementId(BuiltInCategory.OST_StairsRailing)] = "railings";
  catkey[new ElementId(BuiltInCategory.OST_Ceilings)] = "ceilings";
  catkey[new ElementId(BuiltInCategory.OST_Doors)] = "doors";
  catkey[new ElementId(BuiltInCategory.OST_Windows)] = "windows";
  catkey[new ElementId(BuiltInCategory.OST_CurtainWallPanels)] = "curtain_panels";
  catkey[new ElementId(BuiltInCategory.OST_CurtainWallMullions)] = "mullions";
  catkey[new ElementId(BuiltInCategory.OST_PipeCurves)] = "pipes";
  catkey[new ElementId(BuiltInCategory.OST_FlexPipeCurves)] = "pipes";
  catkey[new ElementId(BuiltInCategory.OST_PipeFitting)] = "pipe_fit";
  catkey[new ElementId(BuiltInCategory.OST_PipeAccessory)] = "pipe_fit";
  catkey[new ElementId(BuiltInCategory.OST_DuctCurves)] = "ducts";
  catkey[new ElementId(BuiltInCategory.OST_FlexDuctCurves)] = "ducts";
  catkey[new ElementId(BuiltInCategory.OST_DuctFitting)] = "duct_fit";
  catkey[new ElementId(BuiltInCategory.OST_DuctAccessory)] = "duct_fit";
  catkey[new ElementId(BuiltInCategory.OST_DuctTerminal)] = "air_terminals";
  catkey[new ElementId(BuiltInCategory.OST_MechanicalEquipment)] = "mech_equip";
  catkey[new ElementId(BuiltInCategory.OST_PlumbingFixtures)] = "plumbing";
  catkey[new ElementId(BuiltInCategory.OST_Sprinklers)] = "plumbing";
  catkey[new ElementId(BuiltInCategory.OST_ElectricalEquipment)] = "electrical";
  catkey[new ElementId(BuiltInCategory.OST_ElectricalFixtures)] = "electrical";
  catkey[new ElementId(BuiltInCategory.OST_LightingFixtures)] = "electrical";
  catkey[new ElementId(BuiltInCategory.OST_LightingDevices)] = "electrical";
  catkey[new ElementId(BuiltInCategory.OST_CableTray)] = "cable_tray";
  catkey[new ElementId(BuiltInCategory.OST_CableTrayFitting)] = "cable_tray";
  catkey[new ElementId(BuiltInCategory.OST_Conduit)] = "cable_tray";
  catkey[new ElementId(BuiltInCategory.OST_ConduitFitting)] = "cable_tray";
  // pipe/duct insulation — own key so it doesn't inflate the raw pipe/duct
  // counts (it wraps them) yet is censused, not lost to "other". Fabrication
  // pipework/ductwork ARE the real conduit in a detailed model → pipes/ducts;
  // hangers are supports → pipe_fit. All present since ≤2018 API (2021-safe).
  catkey[new ElementId(BuiltInCategory.OST_PipeInsulations)] = "insulation";
  catkey[new ElementId(BuiltInCategory.OST_DuctInsulations)] = "insulation";
  catkey[new ElementId(BuiltInCategory.OST_DuctLinings)] = "insulation";
  catkey[new ElementId(BuiltInCategory.OST_FabricationPipework)] = "pipes";
  catkey[new ElementId(BuiltInCategory.OST_FabricationDuctwork)] = "ducts";
  catkey[new ElementId(BuiltInCategory.OST_FabricationHangers)] = "pipe_fit";
  catkey[new ElementId(BuiltInCategory.OST_Furniture)] = "furniture";
  catkey[new ElementId(BuiltInCategory.OST_FurnitureSystems)] = "furniture";
  catkey[new ElementId(BuiltInCategory.OST_Casework)] = "furniture";
  catkey[new ElementId(BuiltInCategory.OST_GenericModel)] = "generic";
  catkey[new ElementId(BuiltInCategory.OST_Site)] = "site";
  catkey[new ElementId(BuiltInCategory.OST_Topography)] = "site";
  // ADDITIVE garbage/sub-element census keys (KUKAI_GRAPH_V3_CLEAN, live audit
  // DODELKA 2026-07-04). Sensing only: `counted` and every existing key stay
  // untouched — Python folds these back into "other" while the clean flag is
  // OFF (deploy-window byte-identical), and classifies them when ON.
  // All three enums are ancient (pre-2013) — safe to compile on 2021-2026:
  //   OST_Mass                 conceptual massing «Формы» — not built fabric
  //   OST_Ramps                real building element, deserves its own bucket
  //   OST_StairsRailingBaluster balusters «Балясины» — railing sub-elements
  // (curtain grid schemes / sketches / sun path are caught by CLASS below —
  //  their category enums are less uniform across versions than the classes).
  catkey[new ElementId(BuiltInCategory.OST_Mass)] = "mass";
  catkey[new ElementId(BuiltInCategory.OST_Ramps)] = "ramps";
  catkey[new ElementId(BuiltInCategory.OST_StairsRailingBaluster)] = "balusters";
  var skipcat = new HashSet<ElementId>();
  skipcat.Add(new ElementId(BuiltInCategory.OST_Rooms));
  skipcat.Add(new ElementId(BuiltInCategory.OST_Areas));
  skipcat.Add(new ElementId(BuiltInCategory.OST_MEPSpaces));
  skipcat.Add(new ElementId(BuiltInCategory.OST_RvtLinks));
  skipcat.Add(new ElementId(BuiltInCategory.OST_Levels));
  skipcat.Add(new ElementId(BuiltInCategory.OST_Grids));
  skipcat.Add(new ElementId(BuiltInCategory.OST_Lines));
  skipcat.Add(new ElementId(BuiltInCategory.OST_Materials));
  skipcat.Add(new ElementId(BuiltInCategory.OST_Cameras));
  skipcat.Add(new ElementId(BuiltInCategory.OST_HVAC_Zones));
  skipcat.Add(new ElementId(BuiltInCategory.OST_VolumeOfInterest));
  skipcat.Add(new ElementId(BuiltInCategory.OST_ProjectBasePoint));
  skipcat.Add(new ElementId(BuiltInCategory.OST_SharedBasePoint));
  skipcat.Add(new ElementId(BuiltInCategory.OST_PointClouds));
  var zhist = new Dictionary<string, Dictionary<string,int>>();
  var over = new Dictionary<string,int>();
  var nobbox = new Dictionary<string, Dictionary<string,int>>();
  int counted = 0; int nobboxN = 0; int budget = 250000; bool truncated = false;
  double minx = double.MaxValue, miny = double.MaxValue, minz = double.MaxValue;
  double maxx = double.MinValue, maxy = double.MinValue, maxz = double.MinValue;
  bool anybb = false;
  // robust-envelope coordinate histograms (meter bins) — a SINGLE stray element
  // (survey/base point, imported artifact at the -1000ft origin) must not define
  // the габарит; Python trims the tails. min-corner and max-corner kept separate
  // so the true footprint edges survive while outliers drop.
  var xlo = new Dictionary<int,int>(); var xhi = new Dictionary<int,int>();
  var ylo = new Dictionary<int,int>(); var yhi = new Dictionary<int,int>();
  foreach (var e in new FilteredElementCollector(doc).WhereElementIsNotElementType()) {
    try {
      if (e.ViewSpecific) continue;
      if (e is Autodesk.Revit.DB.Group || e is ImportInstance || e is RevitLinkInstance) continue;
      var c = e.Category;
      if (c == null || c.CategoryType != CategoryType.Model) continue;
      if (skipcat.Contains(c.Id)) continue;
      // class checks (exist in every Revit API 2011+ — zero enum-existence
      // risk): curtain grid schemes «Схемы разрезки витражей» (the layout
      // lines — panels/mullions are the real fabric and censused separately),
      // sketches «<Эскиз>» (profiles of sketch-based elements) and the sun
      // path «Траектория солнца» are Model-typed yet NOT building elements.
      string key;
      if (e is CurtainGridLine) key = "cgrids";
      else if (e is Sketch || e is SunAndShadowSettings) key = "sketch";
      else if (!catkey.TryGetValue(c.Id, out key)) key = "other";
      counted++;
      BoundingBoxXYZ bb = null;
      if (budget > 0) { try { bb = e.get_BoundingBox(null); } catch {} }
      if (bb == null || bb.Min == null || bb.Max == null) {
        if (budget <= 0) truncated = true;
        nobboxN++;
        string lvl = "(no level)";
        try { var lv = doc.GetElement(e.LevelId) as Level; if (lv != null && lv.Name != null) lvl = lv.Name; } catch {}
        if (!nobbox.ContainsKey(lvl)) nobbox[lvl] = new Dictionary<string,int>();
        var nrec = nobbox[lvl];
        int ncur = 0; nrec.TryGetValue(key, out ncur); nrec[key] = ncur + 1;
        continue;
      }
      budget--;
      anybb = true;
      if (bb.Min.X < minx) minx = bb.Min.X; if (bb.Min.Y < miny) miny = bb.Min.Y; if (bb.Min.Z < minz) minz = bb.Min.Z;
      if (bb.Max.X > maxx) maxx = bb.Max.X; if (bb.Max.Y > maxy) maxy = bb.Max.Y; if (bb.Max.Z > maxz) maxz = bb.Max.Z;
      int mnx = (int)System.Math.Floor(bb.Min.X * 0.3048), mxx = (int)System.Math.Floor(bb.Max.X * 0.3048);
      int mny = (int)System.Math.Floor(bb.Min.Y * 0.3048), mxy = (int)System.Math.Floor(bb.Max.Y * 0.3048);
      int eh;
      if (xlo.Count < 8000 || xlo.ContainsKey(mnx)) { eh = 0; xlo.TryGetValue(mnx, out eh); xlo[mnx] = eh + 1; }
      if (xhi.Count < 8000 || xhi.ContainsKey(mxx)) { eh = 0; xhi.TryGetValue(mxx, out eh); xhi[mxx] = eh + 1; }
      if (ylo.Count < 8000 || ylo.ContainsKey(mny)) { eh = 0; ylo.TryGetValue(mny, out eh); ylo[mny] = eh + 1; }
      if (yhi.Count < 8000 || yhi.ContainsKey(mxy)) { eh = 0; yhi.TryGetValue(mxy, out eh); yhi[mxy] = eh + 1; }
      int zb = (int)System.Math.Round(bb.Min.Z * 3.048);   // feet -> decimeters
      int zt = (int)System.Math.Round(bb.Max.Z * 3.048);
      if (!zhist.ContainsKey(key)) zhist[key] = new Dictionary<string,int>();
      var h = zhist[key];
      string hk = zb.ToString() + "," + zt.ToString();
      int cur = 0;
      if (h.TryGetValue(hk, out cur)) { h[hk] = cur + 1; }
      else if (h.Count < 3000) { h[hk] = 1; }
      else { int oc = 0; over.TryGetValue(key, out oc); over[key] = oc + 1; }
    } catch {}
  }
  res["zhist"] = zhist;
  res["nobbox_by_level"] = nobbox;
  if (over.Count > 0) res["zhist_overflow"] = over;
  res["xlo"] = xlo; res["xhi"] = xhi; res["ylo"] = ylo; res["yhi"] = yhi;
  var tot = new Dictionary<string,object>();
  tot["model_elements"] = counted; tot["nobbox"] = nobboxN;
  if (truncated) tot["truncated"] = true;
  res["totals"] = tot;
  if (anybb) {
    var bbox = new Dictionary<string,object>();
    bbox["dx_m"] = System.Math.Round((maxx - minx) * 0.3048, 1);
    bbox["dy_m"] = System.Math.Round((maxy - miny) * 0.3048, 1);
    bbox["dz_m"] = System.Math.Round((maxz - minz) * 0.3048, 1);
    bbox["z_min_m"] = System.Math.Round(minz * 0.3048, 1);
    bbox["z_max_m"] = System.Math.Round(maxz * 0.3048, 1);
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

assert GRAPH_CS.rstrip().endswith("return res;"), "GRAPH_CS shape changed — fix GRAPH_CS_V3 composition"
GRAPH_CS_V3 = GRAPH_CS.rsplit("return res;", 1)[0] + _GRAPH_V3_EXTRA_CS.lstrip("\n")


# ═══════════════════════════════════════════════════════════════════════════
# Spatial reasoning (pure Python — fully unit-tested)
# ═══════════════════════════════════════════════════════════════════════════

# Attribution constants. _EPS_M snaps small modelling offsets (base offsets,
# slab thickness, beams hung just under their level) onto the intended storey.
# _MIN_STOREY_M merges paired levels ("2 этаж" + "2 этаж чистый пол",
# duplicated АР/КЖ levels at one elevation) into ONE storey band.
_EPS_M = 0.35
_MIN_STOREY_M = 1.8
# A slab's/beam's TOP sits at its level — anchor them by z_top; everything else
# STANDS on its storey — anchor by z_base.
_TOP_ANCHORED = frozenset({"floors", "framing"})
# Horizontal MEP distribution HANGS in a storey's ceiling plenum: its bbox base
# sits just under the NEXT level (a 3.0 m storey, a duct at 2.7–2.95 m). The
# generic +_EPS_M base-snap (meant for standing elements offset a few cm below
# their own level) would push that base past the boundary and mis-file the whole
# разводка one floor UP. Anchor these by raw z_base — the storey they SIT IN.
_HORIZONTAL_MEP = frozenset({"pipes", "ducts", "cable_tray",
                             "pipe_fit", "duct_fit", "air_terminals", "insulation"})
# Vertical categories worth a spanner report (risers, through-columns, cores).
_SPAN_KEYS = frozenset({"walls", "columns", "stairs", "pipes", "ducts", "cable_tray"})
# A spanner must cross at least this many storey bands to count as a real
# vertical run: a short horizontal element straddling ONE boundary (2 bands) is
# not a riser — only ≥3-band runs are (max_storeys still reports the true reach).
_MIN_SPAN_BANDS = 3
# A bbox-less element in the unmapped catch-all "other" carries no 3D geometry —
# it is data/annotation/asset (an FM facilities model is ~all of these), NOT
# building mass. It must not read as a storey element (the live "MS4_FM_R24"
# bug: 315/316 bbox-less "other" → a full model looked empty). Conservative on
# purpose: elements in ANY mapped discipline key (incl. generic models, which
# are usually real geometry) that merely lack a bbox stay spatial — we never
# hide real building mass, only the genuinely category-less remainder.
_NONSPATIAL_WHEN_BBOXLESS = frozenset({"other"})
# ── KUKAI_GRAPH_V3_CLEAN census classification (see module docstring) ────────
# Non-building garbage: has 3D geometry but is NOT built fabric — excluded
# from the physical count / storey profiles when clean, disclosed separately.
#   cgrids  curtain grid schemes (layout lines; panels+mullions ARE censused)
#   sketch  <Эскиз> sketches of sketch-based elements + sun-path artifacts
#   mass    conceptual massing forms («Формы»)
_NONBUILDING_KEYS = frozenset({"cgrids", "sketch", "mass"})
# Real building sub-elements sensed under their own key: when clean, balusters
# fold into the railings they belong to; ramps keep a labeled bucket.
_CLEAN_FOLD = {"balusters": "railings"}
# Flag OFF: every new census key folds back into "other" — the summarized
# graph is byte-identical to what the pre-clean C# produced (deploy safety).
_LEGACY_FOLD_OTHER = frozenset({"cgrids", "sketch", "mass", "balusters", "ramps"})
# MEP element census keys — the honest source for the passport MEP line
# (element PRESENCE, not just named systems; live lie: «Системы MEP: нет»
# while OST_PipeCurves elements exist without any PipingSystem).
_MEP_ELEMENT_KEYS = ("pipes", "pipe_fit", "ducts", "duct_fit", "air_terminals",
                     "mech_equip", "plumbing", "electrical", "cable_tray",
                     "insulation")

CAT_LABELS_V3 = {
    "walls": "стены", "floors": "перекрытия", "columns": "колонны",
    "framing": "балки", "foundation": "фундаменты", "roofs": "кровля",
    "stairs": "лестницы", "railings": "ограждения", "ceilings": "потолки",
    "doors": "двери", "windows": "окна",
    "curtain_panels": "панели витража", "mullions": "импосты",
    "pipes": "трубы", "pipe_fit": "фитинги труб",
    "ducts": "воздуховоды", "duct_fit": "фитинги возд.",
    "air_terminals": "возд. решётки", "mech_equip": "оборудование",
    "plumbing": "сантехприборы", "electrical": "электрика",
    "cable_tray": "лотки/короба", "insulation": "изоляция",
    "furniture": "мебель",
    "generic": "обобщ. модели", "site": "рельеф/участок", "other": "прочее",
    # clean-census keys (only ever rendered when KUKAI_GRAPH_V3_CLEAN was on
    # at summarize time — OFF folds them into "other" before any profile)
    "ramps": "пандусы", "balusters": "балясины",
    "cgrids": "схемы разрезки витражей", "sketch": "эскизы",
    "mass": "формообразующие",
}

# RU stem → census key, for graph_api op=where ("где колонны?").
_WHERE_STEMS = (
    ("колонн", "columns"), ("стен", "walls"), ("перекрыт", "floors"),
    ("плит", "floors"), ("балк", "framing"), ("фундамент", "foundation"),
    ("кровл", "roofs"), ("крыш", "roofs"), ("лестниц", "stairs"),
    ("огражден", "railings"), ("потолк", "ceilings"), ("двер", "doors"),
    ("окн", "windows"), ("окон", "windows"), ("витраж", "curtain_panels"),
    ("панел", "curtain_panels"), ("импост", "mullions"), ("труб", "pipes"),
    ("воздуховод", "ducts"), ("решётк", "air_terminals"),
    ("решетк", "air_terminals"), ("оборудован", "mech_equip"),
    ("сантех", "plumbing"), ("электр", "electrical"), ("свет", "electrical"),
    ("лотк", "cable_tray"), ("изоляц", "insulation"), ("мебел", "furniture"),
)


def _f(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _parse_levels(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """[{name, elev_m (display), band_elev_m (geometry frame)}], unsorted."""
    out: list[dict[str, Any]] = []
    for lv in (raw.get("levels") or []):
        if not isinstance(lv, dict) or not lv.get("name"):
            continue
        elev = _f(lv.get("elev_m"))
        proj = _f(lv.get("proj_elev_m"), elev)
        out.append({"name": str(lv["name"]), "elev_m": elev, "band_elev_m": proj})
    return out


def _storey_bands(levels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Storey bands from level elevations: sorted bottom→top; a level closer
    than _MIN_STOREY_M above the current band base joins that band (duplicate
    АР/КЖ levels, "чистый пол" sub-levels) instead of opening a spurious one."""
    bands: list[dict[str, Any]] = []
    for lv in sorted(levels, key=lambda x: x["band_elev_m"]):
        if bands and lv["band_elev_m"] - bands[-1]["base_m"] < _MIN_STOREY_M:
            if lv["name"] not in bands[-1]["names"]:
                bands[-1]["names"].append(lv["name"])
        else:
            bands.append({"name": lv["name"], "names": [lv["name"]],
                          "elev_m": lv["elev_m"], "base_m": lv["band_elev_m"]})
    return bands


def _band_of(z_m: float, bases: list[float]) -> int:
    """Index of the band whose [base, next_base) contains z; -1 = below lowest."""
    return bisect_right(bases, z_m) - 1


def _parse_zhist(raw_hist: Any) -> list[tuple[str, float, float, int]]:
    """Flatten the raw census into (key, z_base_m, z_top_m, count); drops junk."""
    cells: list[tuple[str, float, float, int]] = []
    if not isinstance(raw_hist, dict):
        return cells
    for key, hist in raw_hist.items():
        if not isinstance(hist, dict):
            continue
        for hk, n in hist.items():
            try:
                zb_s, zt_s = str(hk).split(",", 1)
                cells.append((str(key), int(zb_s) / 10.0, int(zt_s) / 10.0, int(n)))
            except (TypeError, ValueError):
                continue
    return cells


def _census_key(key: str, clean: bool) -> str:
    """Map a raw census key to its reporting bucket. OFF: the new C# keys fold
    back into "other" (byte-identical to the pre-clean census). ON: real
    sub-elements fold into their assembly (balusters → railings); everything
    else keeps its own key. Non-building keys are diverted BEFORE this map."""
    if not clean:
        return "other" if key in _LEGACY_FOLD_OTHER else key
    return _CLEAN_FOLD.get(key, key)


def _census_totals(bands: list[dict[str, Any]],
                   *extras: dict[str, int]) -> dict[str, int]:
    """Whole-model census: per-key totals over every storey profile plus the
    below/unplaced/overflow buckets (spanners are already counted at base)."""
    totals: dict[str, int] = {}
    for prof in [b.get("profile") or {} for b in bands] + list(extras):
        for k, n in prof.items():
            totals[k] = totals.get(k, 0) + n
    return totals


def _building_shape(t: dict[str, int], storeys: int,
                    grid_axes: Optional[dict[str, Any]]) -> str:
    """One deterministic building-shape line derived ONLY from census counts,
    storey count and grid spacing — never invented facts. Empty string when
    nothing is derivable (a 4-wall shed gets no grand label).

    Rules (thresholds are deliberately coarse — this is a gestalt, not a
    structural report):
      * structural system: ≥10 columns carrying at least half the wall count →
        каркасное; ≥10 walls clearly dominating columns → стеновое; both
        present otherwise → каркасно-стеновое.
      * envelope: ≥40 curtain elements (panels+mullions) → витраж; «сплошное»
        when the curtain fabric outnumbers both walls and 3× windows.
      * a curtain-only payload (no walls/columns/floors) is a facade MODEL,
        not a building — say so instead of claiming a building type.
      * MEP-dominant with no architecture (≥50 MEP elements, <20 arch) — an
        engineering model, honestly not a building at all."""
    walls = t.get("walls", 0)
    cols = t.get("columns", 0)
    floors = t.get("floors", 0)
    windows = t.get("windows", 0)
    curtain = t.get("curtain_panels", 0) + t.get("mullions", 0)
    mep = sum(t.get(k, 0) for k in _MEP_ELEMENT_KEYS)
    struct_ = None
    if cols >= 10 and 2 * cols >= walls:
        struct_ = "каркасное"
    elif walls >= 10 and walls > 2 * cols:
        struct_ = "стеновое"
    elif cols >= 10 and walls >= 10:
        struct_ = "каркасно-стеновое"
    env = None
    if curtain >= 40:
        env = ("сплошное витражное остекление фасада"
               if curtain >= walls and curtain >= 3 * max(windows, 1)
               else "витражное остекление (частично)")
    pre = f"{storeys}-эт. " if storeys else ""
    if struct_ and env:
        seg = f"{pre}{struct_} здание · {env}"
    elif struct_:
        seg = f"{pre}{struct_} здание"
    elif env and not (walls or cols or floors):
        seg = f"{pre}модель фасада/оболочки: {env}"
    elif env:
        seg = f"{pre}здание · {env}"
    elif mep >= 50 and (walls + cols + curtain) < 20:
        seg = "инженерная модель (MEP-разводка), не архитектура"
    else:
        return ""
    ga = grid_axes if isinstance(grid_axes, dict) else {}
    gx, gy = ga.get("x"), ga.get("y")
    if gx and gy and gx.get("spacing_m") and gy.get("spacing_m"):
        seg += f" · шаг осей ~{gx['spacing_m']:g}×{gy['spacing_m']:g} м"
    return seg


def _similar(a: dict[str, int], b: dict[str, int]) -> bool:
    """Two storey profiles are 'the same floor plan' when every category count
    matches within max(2, 25%) — tolerant of small per-floor variation."""
    for k in set(a) | set(b):
        x, y = a.get(k, 0), b.get(k, 0)
        if abs(x - y) > max(2.0, 0.25 * max(x, y)):
            return False
    return True


def _median_profile(members: list[dict[str, int]]) -> dict[str, int]:
    keys = {k for m in members for k in m}
    out = {}
    for k in keys:
        v = int(round(median([m.get(k, 0) for m in members])))
        if v > 0:
            out[k] = v
    return out


def _cluster_runs(bands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Greedy bottom→top clustering of consecutive similar storeys. Anchor is
    the run's FIRST profile (no drift); representative is the per-key median."""
    runs: list[dict[str, Any]] = []
    for idx, b in enumerate(bands):
        prof = b.get("profile") or {}
        if runs and _similar(runs[-1]["_anchor"], prof):
            runs[-1]["to"] = idx
            runs[-1]["_members"].append(prof)
        else:
            runs.append({"from": idx, "to": idx, "_anchor": prof, "_members": [prof]})
    out = []
    for r in runs:
        prof = _median_profile(r["_members"])
        out.append({
            "from_i": r["from"] + 1, "to_i": r["to"] + 1,
            "count": r["to"] - r["from"] + 1,
            "profile": prof,
            "total": int(round(median([sum(m.values()) for m in r["_members"]]))),
        })
    return out


_GRID_NUM_RE = re.compile(r"^-?\d+(?:[.,]\d+)?$")
# A letter-axis label is SHORT: 1–2 letters, optional prime, optional 1–2 digit
# suffix (А, Б, А', Ак, A1). "DIM-1", long words, "1A" are NOT axes → residual.
_GRID_LET_RE = re.compile(r"^[A-Za-zА-Яа-яЁё]{1,2}['’ʹ]?\d{0,2}$")


def _classify_grid_name(nm: str) -> tuple[Optional[str], Any, str]:
    """A grid name → ('num'|'let'|None, sort-key, name). Humans read grids as
    'numeric axis × letter axis' by NAME ("1–20 × А–Г"), NOT by geometric
    direction (which the live run proved unreliable — it fabricated "1–69" and
    mixed "31" into the letter axis). A digit run is a numeric grid; a short
    letter token a letter grid; anything else (DIM lines, "1A", blank) is
    residual — never fabricated into a range."""
    s = (nm or "").strip()
    if not s:
        return (None, None, s)
    if _GRID_NUM_RE.match(s):
        try:
            return ("num", float(s.replace(",", ".")), s)
        except ValueError:
            return (None, None, s)
    if _GRID_LET_RE.match(s):
        return ("let", (ord(s[0].upper()), s), s)
    return (None, None, s)


def _axis_summary(members: list[tuple[Any, str, Optional[float]]]) -> Optional[dict[str, Any]]:
    """Range (by natural name order) + count + median spacing (by geometric
    position) for one grid family; None when the family is empty."""
    if not members:
        return None
    ordered = sorted(members, key=lambda m: m[0])
    positions = sorted(p for _, _, p in members if p is not None)
    spacing = None
    if len(positions) >= 2:
        diffs = [positions[i + 1] - positions[i] for i in range(len(positions) - 1)]
        diffs = [d for d in diffs if d > 0.05]
        if diffs:
            spacing = round(median(diffs), 2)
    return {"count": len(members), "from": str(ordered[0][1]),
            "to": str(ordered[-1][1]), "spacing_m": spacing}


def _grid_axes(raw_grids: Any) -> dict[str, Any]:
    """Plan skeleton: classify grids by NAME into the numeric (→'x') and letter
    (→'y') families, each with its real range + count + spacing; unparseable
    names and any beyond the collection cap fall into 'other' (a residual
    count), so the extents are never fabricated."""
    if not isinstance(raw_grids, dict):
        return {"total": 0, "x": None, "y": None, "other": 0, "names": []}
    total = _i(raw_grids.get("count"))
    items = [it for it in (raw_grids.get("items") or []) if isinstance(it, dict)]
    names = [str(it.get("name")) for it in items if it.get("name")][:40]
    num: list[tuple[Any, str, Optional[float]]] = []
    let: list[tuple[Any, str, Optional[float]]] = []
    for it in items:
        kind, key, nm = _classify_grid_name(str(it.get("name") or ""))
        pos = it.get("pos_m")
        try:
            pos = float(pos) if pos is not None else None
        except (TypeError, ValueError):
            pos = None
        if kind == "num":
            num.append((key, nm, pos))
        elif kind == "let":
            let.append((key, nm, pos))
    classified = len(num) + len(let)
    return {"total": total, "x": _axis_summary(num), "y": _axis_summary(let),
            "other": max(0, total - classified), "names": names}


# ── robust envelope: single strays must not define the габарит ───────────────

def _int_hist(raw_h: Any) -> dict[int, int]:
    """Coerce a JSON {bin: count} histogram (string or int keys) to {int: int}."""
    out: dict[int, int] = {}
    if not isinstance(raw_h, dict):
        return out
    for k, v in raw_h.items():
        try:
            out[int(k)] = out.get(int(k), 0) + int(v)
        except (TypeError, ValueError):
            continue
    return out


def _trim_edge(hist: dict[int, int], side: str, trim: int) -> Optional[int]:
    """The lo/hi bin of ``hist`` after dropping ``trim`` mass from that tail —
    the first bin at which the cumulative count exceeds ``trim`` (so a handful
    of outlier elements can't set the extent)."""
    if not hist:
        return None
    items = sorted(hist.items())
    seq = items if side == "lo" else list(reversed(items))
    acc = 0
    for b, c in seq:
        acc += c
        if acc > trim:
            return b
    return seq[-1][0]


def _robust_bbox(raw: dict[str, Any], zbase_hist: dict[int, int],
                 ztop_hist: dict[int, int]) -> Optional[dict[str, float]]:
    """A poison-proof envelope from the per-element coordinate histograms:
    trimmed min-corner → max-corner per axis (X/Y from the C# histograms, Z
    from the storey census). Returns None when the histograms are absent (older
    payload / a test fixture) → caller falls back to the raw bbox min/max."""
    xlo, xhi = _int_hist(raw.get("xlo")), _int_hist(raw.get("xhi"))
    ylo, yhi = _int_hist(raw.get("ylo")), _int_hist(raw.get("yhi"))
    if not (xlo and xhi and ylo and yhi and zbase_hist and ztop_hist):
        return None

    def _rng(loh: dict[int, int], hih: dict[int, int]) -> tuple[Optional[int], Optional[int]]:
        trim = max(1, int(round(sum(loh.values()) * 0.01)))
        return _trim_edge(loh, "lo", trim), _trim_edge(hih, "hi", trim)

    x0, x1 = _rng(xlo, xhi)
    y0, y1 = _rng(ylo, yhi)
    z0, z1 = _rng(zbase_hist, ztop_hist)
    if None in (x0, x1, y0, y1, z0, z1):
        return None
    return {"dx_m": float(max(0, x1 - x0)), "dy_m": float(max(0, y1 - y0)),
            "dz_m": float(max(0, z1 - z0)), "z_min_m": float(z0), "z_max_m": float(z1)}


def summarize_graph_v3(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize + spatially reason over the raw GRAPH_CS_V3 result.

    Carries ``"v3": True`` so render/API dispatch is by data presence. Emits the
    v2-compatible keys (levels / cat_by_level / grids / links / bbox_m /
    worksets) so every existing graph_api op keeps working — now backed by
    GEOMETRY-attributed counts — plus the v3 spine (bands / runs / typical /
    spanners / grid_axes / below / unplaced / totals).
    """
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {"v3": True, **summarize_graph(raw)}

    # ── levels + storey bands ────────────────────────────────────────────────
    levels = _parse_levels(raw)
    bands = _storey_bands(levels)
    out["levels"] = [{"name": lv["name"], "elev_m": lv["elev_m"]}
                     for lv in sorted(levels, key=lambda x: x["band_elev_m"])]
    out["levels_total"] = len(levels)
    out["storeys"] = len(bands)
    synthetic = not bands
    if synthetic:  # 0-level model: one open band so nothing is lost
        bands = [{"name": "вся модель", "names": [], "elev_m": None,
                  "base_m": float("-inf")}]
    bases = [b["base_m"] for b in bands]
    level_band: dict[str, int] = {}
    for i, b in enumerate(bands):
        for nm in b["names"]:
            level_band[nm] = i

    # ── census cells + robust envelope ───────────────────────────────────────
    # Parse once, reuse for both the envelope (Z extent) and attribution.
    # The clean flag is read HERE and nowhere else: OFF folds the new C# census
    # keys into "other" (pre-clean byte-identical), ON diverts non-building
    # garbage into its own bucket BEFORE the envelope/attribution see it (so
    # a stray mass/sketch can no longer poison the Z extent either).
    clean = graph_v3_clean_enabled()
    nonbuilding: dict[str, int] = {}
    cells = []
    for key, zb, zt, n in _parse_zhist(raw.get("zhist")):
        if clean and key in _NONBUILDING_KEYS:
            nonbuilding[key] = nonbuilding.get(key, 0) + n
            continue
        cells.append((_census_key(key, clean), zb, zt, n))
    zbase_hist: dict[int, int] = {}
    ztop_hist: dict[int, int] = {}
    for key, zb, zt, n in cells:
        b0, b1 = int(math.floor(zb)), int(math.floor(zt))
        zbase_hist[b0] = zbase_hist.get(b0, 0) + n
        ztop_hist[b1] = ztop_hist.get(b1, 0) + n
    # bbox: robust (trimmed coordinate histograms — a single stray at the
    # -1000ft origin can't inflate the габарит) when the histograms are present,
    # else the raw C# min/max (older payload / test fixture).
    bbox: dict[str, float] = _robust_bbox(raw, zbase_hist, ztop_hist) or {}
    if not bbox:
        bb = raw.get("bbox_m") if isinstance(raw.get("bbox_m"), dict) else None
        if bb:
            try:
                for k in ("dx_m", "dy_m", "dz_m", "z_min_m", "z_max_m"):
                    if bb.get(k) is not None:
                        bbox[k] = float(bb[k])
            except (TypeError, ValueError):
                bbox = {}
    if bbox:
        out["bbox_m"] = bbox

    # ── geometry attribution ────────────────────────────────────────────────
    # synthetic (0-level) model: EVERY censused element must land in the one
    # open band so an MEP/coordination model with no levels still renders its
    # census (the live "ВК_R24 → пусто" bug), never an empty building.
    profiles: list[dict[str, int]] = [{} for _ in bands]
    below: dict[str, int] = {}
    unplaced: dict[str, int] = {}
    nonspatial: dict[str, int] = {}
    overflow: dict[str, int] = {}
    spanners: dict[str, dict[str, int]] = {}
    for key, zb, zt, n in cells:
        ref = zt if key in _TOP_ANCHORED else zb
        # standing elements snap onto their level; horizontal MEP anchors by its
        # raw base so a ceiling-plenum run stays on the storey it hangs in.
        snap = 0.0 if key in _HORIZONTAL_MEP else _EPS_M
        i = _band_of(ref + snap, bases)
        if i < 0:
            if synthetic:
                profiles[0][key] = profiles[0].get(key, 0) + n
            else:
                below[key] = below.get(key, 0) + n
            continue
        profiles[i][key] = profiles[i].get(key, 0) + n
        if key in _SPAN_KEYS and not synthetic:
            top_i = _band_of(zt - _EPS_M, bases)
            span = top_i - i + 1
            if span >= _MIN_SPAN_BANDS:
                rec = spanners.setdefault(key, {"count": 0, "max_storeys": 0})
                rec["count"] += n
                rec["max_storeys"] = max(rec["max_storeys"], span)
    # LevelId fallback for bbox-less elements; unknown level → the synthetic
    # band when there are no levels, else the honest 'unplaced' bucket.
    nb = raw.get("nobbox_by_level")
    if isinstance(nb, dict):
        for lvl, rec in nb.items():
            if not isinstance(rec, dict):
                continue
            i = level_band.get(str(lvl))     # (b) resolvable LevelId → its band
            for key, n in rec.items():
                key = str(key)
                try:
                    n = int(n)
                except (TypeError, ValueError):
                    continue
                if clean and key in _NONBUILDING_KEYS:  # garbage even if placed
                    nonbuilding[key] = nonbuilding.get(key, 0) + n
                    continue
                key = _census_key(key, clean)
                if i is not None:
                    profiles[i][key] = profiles[i].get(key, 0) + n
                elif key in _NONSPATIAL_WHEN_BBOXLESS:
                    nonspatial[key] = nonspatial.get(key, 0) + n   # (a) data/annotation
                elif synthetic:
                    profiles[0][key] = profiles[0].get(key, 0) + n  # whole-model band
                else:
                    unplaced[key] = unplaced.get(key, 0) + n        # real, no location
    # zhist overflow = real placed elements the C# histogram capped (>3000 cells
    # for one category — a sloped drainage / dense fabrication network). They are
    # located mass, just not resolved to a band: an OWN honest bucket, never the
    # 'unplaced'/«вне уровней» line (that would assert a false geometric fact).
    # For a 0-level model the single band IS the whole model, so it lands there.
    ov = raw.get("zhist_overflow")
    if isinstance(ov, dict):
        target = profiles[0] if synthetic else overflow
        for key, n in ov.items():
            try:
                key, n = str(key), int(n)
            except (TypeError, ValueError):
                continue
            if clean and key in _NONBUILDING_KEYS:      # garbage stays garbage
                nonbuilding[key] = nonbuilding.get(key, 0) + n
                continue
            key = _census_key(key, clean)
            target[key] = target.get(key, 0) + n

    # ── assemble bands (+ rooms per band, + heights) ─────────────────────────
    rooms_by_level = out.get("rooms_by_level") or {}
    out_bands: list[dict[str, Any]] = []
    for i, b in enumerate(bands):
        height: Optional[float] = None
        if not synthetic:
            if i + 1 < len(bands):
                height = round(bands[i + 1]["base_m"] - b["base_m"], 2)
            elif bbox.get("z_max_m") is not None:
                h = round(bbox["z_max_m"] - b["base_m"], 2)
                height = h if h > 0.2 else None
        rooms = None
        agg = {"count": 0, "unnamed": 0, "area_m2": 0.0}
        for nm in b["names"]:
            r = rooms_by_level.get(nm)
            if isinstance(r, dict) and r.get("count"):
                agg["count"] += _i(r.get("count"))
                agg["unnamed"] += _i(r.get("unnamed"))
                agg["area_m2"] += _f(r.get("area_m2"))
        if agg["count"]:
            rooms = {"count": agg["count"], "unnamed": agg["unnamed"],
                     "area_m2": round(agg["area_m2"], 1)}
        out_bands.append({
            "i": i + 1, "name": b["name"], "names": list(b["names"]),
            "elev_m": b["elev_m"], "height_m": height,
            "profile": profiles[i], "total": sum(profiles[i].values()),
            "rooms": rooms,
        })
    out["bands"] = out_bands
    out["below"] = ({"profile": below, "total": sum(below.values())}
                    if below else None)
    out["unplaced"] = ({"profile": unplaced, "total": sum(unplaced.values())}
                       if unplaced else None)
    out["overflow"] = ({"profile": overflow, "total": sum(overflow.values())}
                       if overflow else None)
    out["nonspatial"] = ({"profile": nonspatial, "total": sum(nonspatial.values())}
                         if nonspatial else None)
    out["spanners"] = spanners

    # ── typical-floor compression ────────────────────────────────────────────
    runs = _cluster_runs(out_bands) if not synthetic else []
    out["runs"] = runs
    big = [r for r in runs if r["count"] >= 3]
    out["typical"] = max(big, key=lambda r: r["count"]) if big else None

    # ── plan skeleton + v2-compatible keys ───────────────────────────────────
    ga = _grid_axes(raw.get("grids_geo"))
    out["grid_axes"] = {k: ga[k] for k in ("total", "x", "y", "other")}
    out["grids"] = {"count": ga["total"], "names": ga["names"]}
    out["cat_by_level"] = {nm: dict(profiles[i]) for nm, i in level_band.items()
                           if profiles[i]}
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
    out["worksets"] = _i(raw.get("worksets"))
    # placed = the mass we can actually LOCATE in 3D (band + below + unplaced-
    # spatial + histogram-overflow). The header shows THIS, not raw
    # model_elements, so a data-only FM model (315 non-geometric of 316) never
    # reads as a full building; overflow counts (real capped geometry) stay in.
    placed = (sum(b["total"] for b in out_bands) + sum(below.values())
              + sum(unplaced.values()) + sum(overflow.values()))
    tot = raw.get("totals") if isinstance(raw.get("totals"), dict) else {}
    out["totals"] = {"model_elements": _i(tot.get("model_elements")),
                     "nobbox": _i(tot.get("nobbox")),
                     "physical": placed,
                     "nonspatial": sum(nonspatial.values())}
    if tot.get("truncated"):
        out["totals"]["truncated"] = True

    # ── clean-census keys (KUKAI_GRAPH_V3_CLEAN only — an OFF graph carries
    # NONE of these, so the render path stays byte-identical by data presence)
    if clean:
        out["clean"] = True
        out["nonbuilding"] = ({"profile": nonbuilding,
                               "total": sum(nonbuilding.values())}
                              if nonbuilding else None)
        out["totals"]["nonbuilding"] = sum(nonbuilding.values())
        totals_by_key = _census_totals(out_bands, below, unplaced, overflow)
        mep_elements = {k: totals_by_key[k] for k in _MEP_ELEMENT_KEYS
                        if totals_by_key.get(k, 0) > 0}
        if mep_elements:
            out["mep_elements"] = mep_elements
        shape = _building_shape(totals_by_key, out["storeys"], ga)
        if shape:
            out["shape"] = shape
    return out


# ═══════════════════════════════════════════════════════════════════════════
# LOD-0 gestalt render — the 3D skeleton the agent thinks with
# ═══════════════════════════════════════════════════════════════════════════

_MAX_GESTALT_CHARS = 2600
_MAX_STOREY_ITEMS = 14


def _short(name: Any, cap: int = 20) -> str:
    s = str(name or "?").split(" (")[0].strip() or "?"
    return s if len(s) <= cap else s[: cap - 1] + "…"


def _cats_str(profile: dict[str, int], top: int = 4) -> str:
    items = sorted(profile.items(),
                   key=lambda kv: (-kv[1], CAT_LABELS_V3.get(kv[0], kv[0])))
    shown = ", ".join(f"{CAT_LABELS_V3.get(k, k)} {n}" for k, n in items[:top])
    return shown + (", …" if len(items) > top else "")


def _grid_line(ga: dict[str, Any]) -> str:
    total = _i(ga.get("total"))
    if not total:
        return ""
    fams = []
    for ax in ("x", "y"):
        f = ga.get(ax)
        if not f:
            continue
        seg = f"{f['from']}–{f['to']}"
        if f.get("spacing_m"):
            seg += f" (шаг ~{f['spacing_m']:.1f}м)"
        fams.append(seg)
    if not fams:
        return f"Оси: {total}"
    line = f"Оси ({total}): " + " × ".join(fams)
    other = _i(ga.get("other"))
    if other:
        line += f" (+{other} прочих)"
    return line


def _storey_items(g: dict[str, Any], top_n: int) -> list[str]:
    """One line per distinct storey / collapsed typical run, bottom→top."""
    bands = g.get("bands") or []
    runs = g.get("runs") or []
    heights = [b["height_m"] for b in bands if b.get("height_m")]
    modal_h = median(heights) if heights else None
    items: list[str] = []
    if not runs:  # synthetic 0-level band
        for b in bands:
            items.append(f"  {b['name']} — {b['total']} эл: "
                         f"{_cats_str(b['profile'], top_n)}" if b["total"]
                         else f"  {b['name']} — пусто")
        return items
    for r in runs:
        first, last = bands[r["from_i"] - 1], bands[r["to_i"] - 1]
        if r["count"] >= 3:
            seg = (f"  {_short(first['name'])}–{_short(last['name'])} "
                   f"({r['count']}× "
                   + (f"типовой ~{r['total']} эл: {_cats_str(r['profile'], top_n)})"
                      if r["total"] else "пусто)"))
            rc = [b["rooms"]["count"] for b in bands[r["from_i"] - 1: r["to_i"]]
                  if b.get("rooms")]
            if len(rc) >= r["count"] / 2:
                seg += f" · помещ ~{int(round(median(rc)))}/эт"
            items.append(seg)
            continue
        for b in bands[r["from_i"] - 1: r["to_i"]]:
            seg = f"  {_short(b['name'])}"
            if b.get("elev_m") is not None:
                seg += f" ({b['elev_m']:+.1f}м"
                if (b.get("height_m") and modal_h
                        and abs(b["height_m"] - modal_h) > 0.6):
                    seg += f", h={b['height_m']:.1f}м"
                seg += ")"
            seg += (f" — {b['total']} эл: {_cats_str(b['profile'], top_n)}"
                    if b["total"] else " — пусто")
            if b.get("rooms"):
                r_ = b["rooms"]
                seg += f" · {r_['count']} помещ"
                if r_.get("area_m2"):
                    seg += f", {r_['area_m2']:.0f} м²"
            items.append(seg)
    return items


def _render_v3(g: dict[str, Any], basic_ctx: dict[str, Any],
               top_n: int, max_items: int) -> str:
    name = basic_ctx.get("document_name", "Модель")
    storeys = _i(g.get("storeys"))
    levels_total = _i(g.get("levels_total"))
    totals = g.get("totals") or {}
    model_total = _i(totals.get("model_elements"))
    nonspatial = _i((g.get("nonspatial") or {}).get("total"))
    # header count = PLACED physical mass (locatable in 3D), never raw
    # model_elements — a data/annotation-heavy model must not read as a building.
    n_elems = _i(totals.get("physical"))
    if not n_elems and not nonspatial:
        n_elems = sum(_i(c.get("count")) for c in (basic_ctx.get("categories") or [])
                      if isinstance(c, dict))
    head = f"{name} · "
    head += (f"этажей {storeys} (уровней {levels_total})" if storeys
             else f"уровней {levels_total}")
    head += f" · {n_elems} физ. элементов"
    if nonspatial:
        head += f" · +{nonspatial} негеом."
    bbox = g.get("bbox_m") or {}
    if n_elems and (bbox.get("dx_m") or bbox.get("dy_m") or bbox.get("dz_m")):
        head += (f" · габарит ~{bbox.get('dx_m', 0):.0f}×{bbox.get('dy_m', 0):.0f}"
                 f"×{bbox.get('dz_m', 0):.0f} м")
        if bbox.get("z_min_m") is not None and bbox["z_min_m"] <= -1.5:
            head += f" · низ {bbox['z_min_m']:+.1f}м"
    lines = ["### КАРТА МОДЕЛИ (LOD0 — крупно; уточнение: query_model scope=graph)",
             head]
    # honest note when there is almost no locatable 3D geometry (FM / data model)
    if nonspatial > n_elems and n_elems <= max(3, model_total // 100):
        lines.append(f"ВНИМАНИЕ: модель почти без 3D-геометрии — вероятно данные/"
                     f"оформление/аннотации ({nonspatial} негеом. элементов из "
                     f"{model_total}); НЕ описывай её как построенное здание.")
    # building-shape semantics — present only on clean graphs, derived from
    # census counts/grid alone (see _building_shape); never invented.
    if g.get("shape"):
        lines.append(f"Облик: {g['shape']}")
    gl = _grid_line(g.get("grid_axes") or {})
    if gl:
        lines.append(gl)

    bands = g.get("bands") or []
    if storeys:
        lines.append("Этажи (снизу вверх; привязка по геометрии, не по LevelId):")
    below = g.get("below")
    if below and bands and bands[0].get("elev_m") is not None:
        lines.append(f"  ниже {bands[0]['elev_m']:+.1f}м: "
                     f"{_cats_str(below['profile'], 3)}")
    items = _storey_items(g, top_n)
    if len(items) > max_items:
        keep_head, keep_tail = max_items - 5, 4
        folded = len(items) - keep_head - keep_tail
        items = (items[:keep_head]
                 + [f"  … +{folded} этажей — query_model scope=graph op=storeys"]
                 + items[-keep_tail:])
    lines.extend(items)
    unplaced = g.get("unplaced")
    if unplaced:
        lines.append(f"  вне уровней: {_cats_str(unplaced['profile'], 3)}")
    overflow = g.get("overflow")
    if overflow:
        lines.append(f"  не детализировано по этажам (переполнение гистограммы): "
                     f"{_cats_str(overflow['profile'], 3)}")
    # clean census: excluded non-building garbage, disclosed by name so the
    # count stays auditable (never silently dropped)
    nonbuilding = g.get("nonbuilding")
    if nonbuilding and nonbuilding.get("total"):
        lines.append(f"  служебные, не здание (исключены из счёта): "
                     f"{_cats_str(nonbuilding['profile'], 4)}")
    spanners = g.get("spanners") or {}
    if spanners:
        sp = sorted(spanners.items(), key=lambda kv: -kv[1]["count"])[:4]
        lines.append("Сквозные (≥2 этажей): " + ", ".join(
            f"{CAT_LABELS_V3.get(k, k)} {v['count']} (до {v['max_storeys']} эт)"
            for k, v in sp))

    rooms_by_level = g.get("rooms_by_level") or {}
    if rooms_by_level:
        r_total = sum(_i(r.get("count")) for r in rooms_by_level.values()
                      if isinstance(r, dict))
        r_bands = sum(1 for b in bands if b.get("rooms"))
        r_area = sum(_f(r.get("area_m2")) for r in rooms_by_level.values()
                     if isinstance(r, dict))
        seg = f"Помещения: {r_total} на {r_bands} этажах"
        if r_area:
            seg += f" · {r_area:.0f} м²"
        lines.append(seg)
    else:
        lines.append("Помещений нет — ориентируйся по уровням/осям/категориям; "
                     "НЕ выдумывай зоны.")
    links = g.get("links") or []
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
    systems = g.get("mep_systems") or []
    if systems:
        top = sorted(systems, key=lambda s: -_i(s.get("count")))[:8]
        mep = "Системы MEP: " + ", ".join(
            f"{s['name']} ({s['count']})" for s in top)
        if len(systems) > 8:
            mep += f" (+{len(systems) - 8} ещё — op=systems)"
    elif g.get("mep_elements"):
        # honest MEP line (clean graphs): ELEMENTS exist even though no named
        # system does — «нет» would be a lie (live: 12 pipes, 0 PipingSystems)
        mel = sorted(g["mep_elements"].items(), key=lambda kv: -kv[1])
        mep = ("MEP: " + ", ".join(f"{CAT_LABELS_V3.get(k, k)} {n}"
                                   for k, n in mel[:5])
               + (", …" if len(mel) > 5 else "") + " (систем не задано)")
    else:
        mep = "Системы MEP: нет"
    wk = _i(g.get("worksets"))
    if wk:
        mep += f" · Рабочие наборы: {wk}"
    lines.append(mep)
    return "\n".join(lines)


def build_gestalt_v3(basic_ctx: dict[str, Any], detailed: dict[str, Any],
                     graph: dict[str, Any]) -> str:
    """LOD-0 map v3 — the 3D skeleton: envelope, plan grid, vertical stack with
    geometry-true per-storey content (typical floors collapsed), spanners,
    zones, systems, links. Token-budgeted: retries in compact form, then hard-
    truncates with a query pointer. Returns "" when there is nothing to show."""
    if not isinstance(graph, dict) or not graph:
        return ""
    basic_ctx = basic_ctx if isinstance(basic_ctx, dict) else {}
    if not (graph.get("bands") or graph.get("rooms_by_level")
            or graph.get("mep_systems") or graph.get("links")):
        return ""
    out = _render_v3(graph, basic_ctx, top_n=4, max_items=_MAX_STOREY_ITEMS)
    if len(out) > _MAX_GESTALT_CHARS:
        out = _render_v3(graph, basic_ctx, top_n=2, max_items=8)
    if len(out) > _MAX_GESTALT_CHARS:
        out = (out[: _MAX_GESTALT_CHARS - 60].rsplit("\n", 1)[0]
               + "\n…(усечено — query_model scope=graph op=storeys)")
    return out
