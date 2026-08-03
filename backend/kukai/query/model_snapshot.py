"""Model Snapshot — Stage 1: the INVENTORY census (2026-07-12, review-hardened).

ONE read-only pass over the whole model → per-category quantities the agent
actually needs (count / area / volume, broken down by level and top-N types),
each measure carrying PROVENANCE (source) + COVERAGE (n of the category's
elements that yielded a value). Fills the 0%-quantitative gap in the current
graph (see /root/kukai-model-snapshot-plan.md).

Discipline — NEVER FABRICATE, NEVER WRONG: a measure is the real sum over
elements that HAD a source (value > 0), or ``null`` with coverage disclosed —
never a fake 0, never a wrong total. Worst case on an untested model class = a
MISSING datum, never a WRONG one. Applied at EVERY level (category, by_level,
per-type — each nulls independently).

Hardened per adversarial review (2026-07-12):
  * per-element try/catch — one bad element can't blank the whole census (errN);
  * DesignOption primary-only + demolished-phase skip — no double-count/ghost
    totals on option-set / renovation projects (the common wrong-number trap);
  * BuiltInCategory identity emitted (`bic`, e.g. OST_Walls) so the physical-vs-
    annotation classifier is LOCALE-INDEPENDENT (RU/EN Revit alike);
  * value > 0 gate everywhere — unplaced rooms (ROOM_AREA=0) and self-
    intersecting negative areas are treated as no-source uniformly;
  * links present disclosed (host-only census; links not traversed).

Version-safe C# (no .IntegerValue / ElementId.Value; ids via Id.ToString()) —
passes kukai.security.validation.validate_code_safety. Generated Python-side +
sent via the bridge like GRAPH_CS_V3 (no DLL change).
"""
from __future__ import annotations

INVENTORY_CS = r"""
var __res = new Dictionary<string, object>();
var __cats = new Dictionary<string, Dictionary<string, object>>();
var __mats = new Dictionary<string, Dictionary<string, object>>();
var __famPlaced = new Dictionary<string, int>();
int __total = 0; int __errN = 0; int __doSkip = 0; int __demoSkip = 0; bool __hasDO = false;

Dictionary<string,object> __mkCat() {
    return new Dictionary<string,object>{
        {"count",0},{"bic","unknown"},{"cat_type","Model"},
        {"area_sum",0.0},{"area_n",0},{"vol_sum",0.0},{"vol_n",0},{"vol_tk_n",0},
        {"by_level", new Dictionary<string,object>()},
        {"types", new Dictionary<string,object>()}};
}

foreach (Element __e in new FilteredElementCollector(doc).WhereElementIsNotElementType()) {
    try {
        if (__e.Category == null || __e.Category.Name == null) continue;
        // Design options: PRIMARY only — else an option set double-counts every
        // alternate scheme into one confidently-wrong total.
        var __do = __e.DesignOption;
        if (__do != null) { __hasDO = true; if (!__do.IsPrimary) { __doSkip++; continue; } }
        // Demolished elements are in the file but not physically there.
        var __dp = __e.get_Parameter(BuiltInParameter.PHASE_DEMOLISHED);
        if (__dp != null && __dp.HasValue && __dp.AsElementId() != ElementId.InvalidElementId) { __demoSkip++; continue; }

        string __cn = __e.Category.Name;
        __total++;
        if (!__cats.ContainsKey(__cn)) {
            __cats[__cn] = __mkCat();
            try { __cats[__cn]["cat_type"] = __e.Category.CategoryType.ToString(); } catch {}
            // bic WITHOUT Category.BuiltInCategory (2023+ only — CS1061 on 2021/22,
            // caught by the :52412 compile gate) and WITHOUT the version-drifting
            // ElementId int getters: built-in category ids are NEGATIVE ints →
            // Enum.GetName gives the stable OST_* name on every Revit version.
            try {
                long __cid = long.Parse(__e.Category.Id.ToString());
                if (__cid < 0) {
                    string __bn = Enum.GetName(typeof(BuiltInCategory), (int)__cid);
                    if (__bn != null) __cats[__cn]["bic"] = __bn;
                }
            } catch {}
        }
        var __c = __cats[__cn];
        __c["count"] = (int)__c["count"] + 1;

        // area: HOST_AREA_COMPUTED → ROOM_AREA. Count ONLY when > 0 (unplaced
        // rooms report 0; self-intersecting loops report negative → no-source).
        double __a = -1;
        var __ap = __e.get_Parameter(BuiltInParameter.HOST_AREA_COMPUTED);
        if (__ap == null || !__ap.HasValue) __ap = __e.get_Parameter(BuiltInParameter.ROOM_AREA);
        if (__ap != null && __ap.HasValue) {
            double __ar = __ap.AsDouble() * 0.09290304;
            if (__ar > 0) { __a = __ar; __c["area_sum"] = (double)__c["area_sum"] + __a; __c["area_n"] = (int)__c["area_n"] + 1; }
        }
        // volume: HOST_VOLUME_COMPUTED → ROOM_VOLUME.
        double __v = -1;
        var __vp = __e.get_Parameter(BuiltInParameter.HOST_VOLUME_COMPUTED);
        if (__vp == null || !__vp.HasValue) __vp = __e.get_Parameter(BuiltInParameter.ROOM_VOLUME);
        if (__vp != null && __vp.HasValue) {
            double __vr = __vp.AsDouble() * 0.028316846592;
            if (__vr > 0) { __v = __vr; __c["vol_sum"] = (double)__c["vol_sum"] + __v; __c["vol_n"] = (int)__c["vol_n"] + 1; }
        }
        // Stage 2 MATERIAL TAKEOFF (ladder rung 2): the stair cluster carries no
        // HOST_VOLUME_COMPUTED anywhere. Where the direct param gave nothing, sum
        // GetMaterialVolume over GetMaterialIds — the exact number Revit's own
        // takeoff schedule shows. CONTAINERS ONLY (OST_Stairs/Railing/Ramps):
        // the container's takeoff already INCLUDES its run/landing/stringer
        // children — live-corroborated on КР 2026-07-12 (container 5.22 м³ ==
        // runs+landings+stringers 5.22 == independent geometry 5.22) — so adding
        // takeoff on the sub-categories would DOUBLE-COUNT the cluster. Subs stay
        // count-only; provenance in vol_tk_n so the render discloses the source.
        if (__v < 0) {
            string __bicS2 = __c["bic"] as string;
            if (__bicS2 == "OST_Stairs" || __bicS2 == "OST_StairsRailing" || __bicS2 == "OST_Ramps") {
                try {
                    double __tv = 0;
                    foreach (ElementId __mid in __e.GetMaterialIds(false)) {
                        try { double __mv = __e.GetMaterialVolume(__mid); if (__mv > 0) __tv += __mv; } catch {}
                    }
                    if (__tv > 0) {
                        __v = __tv * 0.028316846592;
                        __c["vol_sum"] = (double)__c["vol_sum"] + __v;
                        __c["vol_n"] = (int)__c["vol_n"] + 1;
                        __c["vol_tk_n"] = (int)__c["vol_tk_n"] + 1;
                    }
                } catch {}
            }
        }

        // level (vetted chain, same as the query/level filter)
        string __lv = "(no level)";
        var __lp = __e.get_Parameter(BuiltInParameter.WALL_BASE_CONSTRAINT);
        if (__lp == null) __lp = __e.get_Parameter(BuiltInParameter.LEVEL_PARAM);
        if (__lp == null) __lp = __e.get_Parameter(BuiltInParameter.SCHEDULE_LEVEL_PARAM);
        if (__lp == null) __lp = __e.get_Parameter(BuiltInParameter.FAMILY_LEVEL_PARAM);
        if (__lp != null && __lp.HasValue) {
            var __le = doc.GetElement(__lp.AsElementId()) as Level;
            if (__le != null && __le.Name != null) __lv = __le.Name;
        }
        if (__lv == "(no level)") {
            try { var __lid = __e.LevelId;
                if (__lid != null && __lid != ElementId.InvalidElementId) {
                    var __le2 = doc.GetElement(__lid) as Level;
                    if (__le2 != null && __le2.Name != null) __lv = __le2.Name;
                }
            } catch {}
        }
        var __bl = (Dictionary<string,object>)__c["by_level"];
        if (!__bl.ContainsKey(__lv)) __bl[__lv] = new Dictionary<string,object>{{"count",0},{"area_sum",0.0},{"area_n",0}};
        var __bld = (Dictionary<string,object>)__bl[__lv];
        __bld["count"] = (int)__bld["count"] + 1;
        if (__a > 0) { __bld["area_sum"] = (double)__bld["area_sum"] + __a; __bld["area_n"] = (int)__bld["area_n"] + 1; }

        // type (own null discipline — a type with no source stays null, not 0)
        string __tn = "(no type)";
        var __te = doc.GetElement(__e.GetTypeId());
        if (__te != null && __te.Name != null) __tn = __te.Name;
        // Stage 1e MATERIALS-IN-USE (operator ask: «какие материалы именно
        // используются», not the loaded library): usage census per material —
        // element count + takeoff volume. Model-typed categories only.
        if ((__c["cat_type"] as string) == "Model") {
            try {
                foreach (ElementId __mid in __e.GetMaterialIds(false)) {
                    try {
                        var __mm = doc.GetElement(__mid) as Material;
                        if (__mm == null || __mm.Name == null) continue;
                        if (!__mats.ContainsKey(__mm.Name)) __mats[__mm.Name] = new Dictionary<string,object>{{"n",0},{"vol",0.0},{"vn",0}};
                        var __mdd = __mats[__mm.Name];
                        __mdd["n"] = (int)__mdd["n"] + 1;
                        try { double __mv2 = __e.GetMaterialVolume(__mid); if (__mv2 > 0) { __mdd["vol"] = (double)__mdd["vol"] + __mv2 * 0.028316846592; __mdd["vn"] = (int)__mdd["vn"] + 1; } } catch {}
                    } catch {}
                }
            } catch {}
        }
        // Stage 1e FAMILIES: placed-instances счёт по семействам (символ уже в руках)
        try {
            var __fsym = __te as FamilySymbol;
            if (__fsym != null && __fsym.Family != null && __fsym.Family.Name != null) {
                string __fpn = __fsym.Family.Name;
                __famPlaced[__fpn] = (__famPlaced.ContainsKey(__fpn) ? __famPlaced[__fpn] : 0) + 1;
            }
        } catch {}

        var __ty = (Dictionary<string,object>)__c["types"];
        if (!__ty.ContainsKey(__tn)) {
            __ty[__tn] = new Dictionary<string,object>{{"count",0},{"area_sum",0.0},{"area_n",0},{"vol_sum",0.0},{"vol_n",0}};
            // Stage 1c VOCABULARY: host-type material glossary, once per NEW type —
            // replaces the separate _TYPE_META_CS exec. Compound-structure material
            // names (deduped) + wall Function/Width. Fail-open per type.
            try {
                string __bicS = __c["bic"] as string;
                if (__te != null && (__bicS == "OST_Walls" || __bicS == "OST_Floors" || __bicS == "OST_Ceilings" || __bicS == "OST_Roofs")) {
                    var __ha = __te as HostObjAttributes;
                    if (__ha != null) {
                        var __tmd = (Dictionary<string,object>)__ty[__tn];
                        string __mat = "";
                        try { var __cs2 = __ha.GetCompoundStructure(); if (__cs2 != null) { foreach (var __ly in __cs2.GetLayers()) { var __m = doc.GetElement(__ly.MaterialId) as Material; if (__m != null && __m.Name != null && !__mat.Contains(__m.Name)) __mat += (__mat.Length > 0 ? ";" : "") + __m.Name; } } } catch {}
                        if (__mat.Length > 0) __tmd["material"] = __mat;
                        var __wt2 = __te as WallType;
                        if (__wt2 != null) {
                            try { __tmd["width_mm"] = Math.Round(__wt2.Width * 304.8, 0); } catch {}
                            try { __tmd["function"] = __wt2.Function.ToString(); } catch {}
                        }
                    }
                }
            } catch {}
        }
        var __tyd = (Dictionary<string,object>)__ty[__tn];
        __tyd["count"] = (int)__tyd["count"] + 1;
        if (__a > 0) { __tyd["area_sum"] = (double)__tyd["area_sum"] + __a; __tyd["area_n"] = (int)__tyd["area_n"] + 1; }
        if (__v > 0) { __tyd["vol_sum"] = (double)__tyd["vol_sum"] + __v; __tyd["vol_n"] = (int)__tyd["vol_n"] + 1; }
    } catch { __errN++; }
}

// --- post-process → provenance + coverage + top-N types (null discipline everywhere) ---
var __outCats = new Dictionary<string, object>();
foreach (var __kv in __cats) {
    var __c = __kv.Value;
    int __cnt = (int)__c["count"];
    var __o = new Dictionary<string, object>();
    __o["count"] = __cnt;
    __o["bic"] = __c["bic"];
    __o["cat_type"] = __c["cat_type"];
    int __an = (int)__c["area_n"];
    __o["area_m2"] = __an > 0 ? (object)Math.Round((double)__c["area_sum"], 1) : (object)null;
    __o["area_coverage"] = __an + "/" + __cnt;
    int __vn = (int)__c["vol_n"];
    __o["volume_m3"] = __vn > 0 ? (object)Math.Round((double)__c["vol_sum"], 2) : (object)null;
    __o["volume_coverage"] = __vn + "/" + __cnt;
    __o["volume_takeoff_n"] = (int)__c["vol_tk_n"];

    var __bl = (Dictionary<string,object>)__c["by_level"];
    var __blOut = new Dictionary<string,object>();
    foreach (var __lk in __bl.Keys) {
        var __d = (Dictionary<string,object>)__bl[__lk];
        int __ln = (int)__d["area_n"];
        __blOut[__lk] = new Dictionary<string,object>{
            {"count", (int)__d["count"]},
            {"area_m2", __ln > 0 ? (object)Math.Round((double)__d["area_sum"], 1) : (object)null}};
    }
    __o["by_level"] = __blOut;

    var __ty = (Dictionary<string,object>)__c["types"];
    var __top = __ty
        .OrderByDescending(__x => (int)((Dictionary<string,object>)__x.Value)["count"])
        .Take(8)
        .Select(__x => {
            var __d = (Dictionary<string,object>)__x.Value;
            int __tan = (int)__d["area_n"]; int __tvn = (int)__d["vol_n"];
            var __dd = new Dictionary<string,object>{
                {"type", __x.Key},
                {"count", (int)__d["count"]},
                {"area_m2", __tan > 0 ? (object)Math.Round((double)__d["area_sum"], 1) : (object)null},
                {"volume_m3", __tvn > 0 ? (object)Math.Round((double)__d["vol_sum"], 2) : (object)null}};
            if (__d.ContainsKey("material")) __dd["material"] = __d["material"];
            if (__d.ContainsKey("width_mm")) __dd["width_mm"] = __d["width_mm"];
            if (__d.ContainsKey("function")) __dd["function"] = __d["function"];
            return (object)__dd;
        }).ToList();
    __o["types_top"] = __top;
    __o["types_total"] = __ty.Count;
    __outCats[__kv.Key] = __o;
}

__res["categories"] = __outCats;
__res["category_count"] = __outCats.Count;
__res["element_total"] = __total;
__res["errors"] = __errN;
__res["design_options_present"] = __hasDO;
__res["design_option_skipped"] = __doSkip;
__res["demolished_skipped"] = __demoSkip;
int __phaseCount = 0; try { __phaseCount = doc.Phases.Size; } catch {}
__res["phase_count"] = __phaseCount;
int __links = 0; try { __links = new FilteredElementCollector(doc).OfClass(typeof(RevitLinkInstance)).GetElementCount(); } catch {}
__res["linked_models"] = __links;

// ── Stage 1c ORIENT: levels (name+elevation) + grid names — grounding data ──
var __lvls = new List<object>();
try {
    foreach (Level __l in new FilteredElementCollector(doc).OfClass(typeof(Level))) {
        try { if (__l.Name != null) __lvls.Add(new Dictionary<string,object>{{"name", __l.Name},{"elev_m", Math.Round(__l.Elevation * 0.3048, 3)}}); } catch {}
    }
} catch {}
__res["levels"] = __lvls;
var __grids = new List<object>();
try {
    foreach (Autodesk.Revit.DB.Grid __g in new FilteredElementCollector(doc).OfClass(typeof(Autodesk.Revit.DB.Grid))) {
        try { if (__g.Name != null) __grids.Add(__g.Name); } catch {}
    }
} catch {}
__res["grids"] = __grids;

// ── Stage 1c HEALTH: warnings count. null = COULD NOT read (never a fake 0). ──
int __warn = -1; try { __warn = doc.GetWarnings().Count; } catch {}
__res["warnings"] = __warn >= 0 ? (object)__warn : (object)null;

// ── Stage 1e MATERIALS-IN-USE: post-process → sorted-ready raw dict ──────────
var __matsOut = new Dictionary<string, object>();
foreach (var __mkv in __mats) {
    var __md2 = __mkv.Value;
    int __mvn = (int)__md2["vn"];
    __matsOut[__mkv.Key] = new Dictionary<string,object>{
        {"n", (int)__md2["n"]},
        {"volume_m3", __mvn > 0 ? (object)Math.Round((double)__md2["vol"], 2) : (object)null}};
}
__res["materials"] = __matsOut;

// ── Stage 1e FAMILIES: loaded families (symbols) + placed counts join ────────
// «агент знает, какие семейства уже в проекте» — placed_n==0 = загружено, но
// не размещено (можно ставить БЕЗ подгрузки).
var __fams = new Dictionary<string, object>();
try {
    foreach (FamilySymbol __fs3 in new FilteredElementCollector(doc).OfClass(typeof(FamilySymbol)).Cast<FamilySymbol>()) {
        try {
            var __fam = __fs3.Family;
            if (__fam == null || __fam.Name == null) continue;
            string __fn3 = __fam.Name;
            if (!__fams.ContainsKey(__fn3)) {
                string __fc = ""; try { if (__fs3.Category != null && __fs3.Category.Name != null) __fc = __fs3.Category.Name; } catch {}
                __fams[__fn3] = new Dictionary<string,object>{
                    {"category", __fc},{"types_n",0},
                    {"placed_n", __famPlaced.ContainsKey(__fn3) ? __famPlaced[__fn3] : 0}};
            }
            var __fd3 = (Dictionary<string,object>)__fams[__fn3];
            __fd3["types_n"] = (int)__fd3["types_n"] + 1;
        } catch {}
    }
} catch {}
__res["families"] = __fams;

// ── Stage 1e DOCUMENTATION: views/sheets/schedules (operator ask) ────────────
// Summary counts injected; full lists (≤500) live in the cache for Tier-1.
var __views = new Dictionary<string,int>();
var __viewList = new List<object>();
var __vTemplates = new List<object>();
try {
    foreach (Autodesk.Revit.DB.View __v in new FilteredElementCollector(doc).OfClass(typeof(Autodesk.Revit.DB.View))) {
        try {
            if (__v.IsTemplate) { try { if (__v.Name != null) __vTemplates.Add(__v.Name); } catch {} continue; }
            string __vt = __v.ViewType.ToString();
            __views[__vt] = (__views.ContainsKey(__vt) ? __views[__vt] : 0) + 1;
            if (__viewList.Count < 500) __viewList.Add(new Dictionary<string,object>{{"name", __v.Name},{"type", __vt}});
        } catch {}
    }
} catch {}
__res["views_by_type"] = __views;
__res["views"] = __viewList;
__res["view_templates"] = __vTemplates;
// видимость: фильтры проекта (ParameterFilter + SelectionFilter через базовый
// FilterElement) — «мне не видно X» диагностируется из контекста, не экспедицией
var __vFilters = new List<object>();
try {
    foreach (Element __pf in new FilteredElementCollector(doc).OfClass(typeof(FilterElement))) {
        try { if (__pf.Name != null) __vFilters.Add(__pf.Name); } catch {}
    }
} catch {}
__res["view_filters"] = __vFilters;
var __sheets = new List<object>();
try {
    foreach (ViewSheet __sh in new FilteredElementCollector(doc).OfClass(typeof(ViewSheet))) {
        try { __sheets.Add(new Dictionary<string,object>{{"number", __sh.SheetNumber},{"name", __sh.Name}}); } catch {}
    }
} catch {}
__res["sheets"] = __sheets;
var __scheds = new List<object>();
try {
    foreach (ViewSchedule __sc in new FilteredElementCollector(doc).OfClass(typeof(ViewSchedule))) {
        try { if (!__sc.IsTemplate && __sc.Name != null && !__sc.Name.StartsWith("<")) __scheds.Add(__sc.Name); } catch {}
    }
} catch {}
__res["schedules"] = __scheds;
// Links: the census is host-only, so WHICH links are LOADED decides whether a
// question is answerable at all. A loaded link is queryable
// (RevitLinkInstance.GetLinkDocument()); an unloaded one is a name and nothing
// more. Prod 2026-07-27: the same "что на кровле" answered "только линии" on one
// turn and "297 элементов каркаса в связи KR" on another, because one query
// walked the links and the other did not.
var __linkNames = new List<object>();
var __linkLoaded = new List<object>();
int __linkOk = 0, __linkOff = 0;
try {
    foreach (Element __li in new FilteredElementCollector(doc).OfClass(typeof(RevitLinkInstance))) {
        try { if (__li.Name != null) __linkNames.Add(__li.Name); } catch {}
        try {
            var __ld = (__li as RevitLinkInstance).GetLinkDocument();
            if (__ld != null) { __linkOk++; try { __linkLoaded.Add(__ld.Title); } catch {} }
            else __linkOff++;
        } catch { __linkOff++; }
    }
} catch {}
__res["link_names"] = __linkNames;
__res["links_loaded"] = __linkOk;
__res["links_unloaded"] = __linkOff;
__res["link_loaded_names"] = __linkLoaded;
var __phNames = new List<object>();
try { foreach (Phase __ph in doc.Phases) { try { if (__ph.Name != null) __phNames.Add(__ph.Name); } catch {} } } catch {}
__res["phase_names"] = __phNames;

// ── Stage 1f PROJECT/SHARED PARAMETER BINDINGS (anti-hallucination for the
// «заполни/проверь параметр X» class + codegen grounding). Name + binding kind
// + bound categories; the datatype API is version-incompatible (ParameterType
// removed 2023+, GetDataType absent 2021) — deliberately omitted.
var __pbind = new List<object>();
try {
    var __it2 = doc.ParameterBindings.ForwardIterator();
    while (__it2.MoveNext()) {
        try {
            var __def = __it2.Key as Definition;
            if (__def == null || __def.Name == null) continue;
            var __bind = __it2.Current;
            string __bkind = __bind is InstanceBinding ? "instance" : (__bind is TypeBinding ? "type" : "?");
            var __bcats = new List<object>();
            try {
                var __eb = __bind as ElementBinding;
                if (__eb != null && __eb.Categories != null) {
                    foreach (Category __bc in __eb.Categories) {
                        try { if (__bc.Name != null && __bcats.Count < 12) __bcats.Add(__bc.Name); } catch {}
                    }
                }
            } catch {}
            __pbind.Add(new Dictionary<string,object>{{"name", __def.Name},{"kind", __bkind},{"cats", __bcats}});
        } catch {}
    }
} catch {}
__res["param_bindings"] = __pbind;

// ── Stage 1f UNITS (agent writes values in the project's units) ───────────────
try {
    var __u = doc.GetUnits();
    try { __res["unit_length"] = __u.GetFormatOptions(SpecTypeId.Length).GetUnitTypeId().TypeId; } catch {}
    try { __res["unit_area"] = __u.GetFormatOptions(SpecTypeId.Area).GetUnitTypeId().TypeId; } catch {}
} catch {}

// ── Stage 1f DWG/CAD imports (подложки) + model groups + georef ──────────────
var __dwg = new List<object>();
try {
    foreach (ImportInstance __im in new FilteredElementCollector(doc).OfClass(typeof(ImportInstance))) {
        try {
            string __inm = (__im.Category != null && __im.Category.Name != null) ? __im.Category.Name : "import";
            __dwg.Add(new Dictionary<string,object>{{"name", __inm},{"view_specific", __im.ViewSpecific}});
        } catch {}
    }
} catch {}
__res["cad_imports"] = __dwg;
var __grps = new Dictionary<string,int>();
try {
    foreach (Element __g2 in new FilteredElementCollector(doc).OfClass(typeof(Autodesk.Revit.DB.Group)).WhereElementIsNotElementType()) {
        try { if (__g2.Name != null) __grps[__g2.Name] = (__grps.ContainsKey(__g2.Name) ? __grps[__g2.Name] : 0) + 1; } catch {}
    }
} catch {}
__res["groups"] = __grps;
try {
    var __pl = doc.ActiveProjectLocation;
    var __pp = __pl.GetProjectPosition(XYZ.Zero);
    if (__pp != null) {
        __res["true_north_deg"] = Math.Round(__pp.Angle * 180.0 / Math.PI, 2);
        __res["project_elevation_m"] = Math.Round(__pp.Elevation * 0.3048, 3);
    }
} catch {}

// ── Stage 1e WORKSHARING + project identity ──────────────────────────────────
bool __wsh = false; try { __wsh = doc.IsWorkshared; } catch {}
__res["workshared"] = __wsh;
var __wsets = new List<object>();
if (__wsh) {
    try {
        foreach (Workset __w in new FilteredWorksetCollector(doc).OfKind(WorksetKind.UserWorkset)) {
            try { if (__w.Name != null) __wsets.Add(__w.Name); } catch {}
        }
    } catch {}
}
__res["worksets"] = __wsets;
try {
    var __pi = doc.ProjectInformation;
    if (__pi != null) {
        try { if (__pi.Name != null && __pi.Name.Length > 0) __res["project_name"] = __pi.Name; } catch {}
        try { if (__pi.Number != null && __pi.Number.Length > 0) __res["project_number"] = __pi.Number; } catch {}
    }
} catch {}

// ── Stage 1d MEP: named systems via CONCRETE classes (MechanicalSystem/
// PipingSystem/ElectricalSystem — abstract MEPSystem in OfClass is a version
// gamble, concrete classes compile 2021-2026). n = -1 when Elements failed
// (render omits the count — never a fabricated 0; a real empty system is 0).
var __mep = new List<object>();
try {
    var __mtypes = new List<System.Type>{
        typeof(Autodesk.Revit.DB.Mechanical.MechanicalSystem),
        typeof(Autodesk.Revit.DB.Plumbing.PipingSystem),
        typeof(Autodesk.Revit.DB.Electrical.ElectricalSystem) };
    foreach (var __mt in __mtypes) {
        try {
            foreach (Element __se in new FilteredElementCollector(doc).OfClass(__mt)) {
                try {
                    var __ms = __se as MEPSystem;
                    if (__ms == null || __ms.Name == null) continue;
                    int __sn = -1; try { __sn = __ms.Elements.Size; } catch {}
                    __mep.Add(new Dictionary<string,object>{
                        {"name", __ms.Name},{"kind", __mt.Name},{"n", __sn}});
                } catch {}
            }
        } catch {}
    }
} catch {}
__res["mep_systems"] = __mep;
return __res;
"""


RELATIONS_CS = r"""
var __res = new Dictionary<string, object>();

// ── Stage 3 RELATIONS (lazy, cached Tier-1 — NOT injected): hosting edges ────
// doors/windows → host wall (id + type name) + level. Per-element try/catch.
var __hosted = new List<object>();
foreach (var __bic in new[]{ BuiltInCategory.OST_Doors, BuiltInCategory.OST_Windows }) {
    try {
        foreach (Element __e in new FilteredElementCollector(doc).OfCategory(__bic).WhereElementIsNotElementType()) {
            try {
                var __fi = __e as FamilyInstance;
                if (__fi == null) continue;
                var __d = new Dictionary<string,object>();
                __d["id"] = __e.Id.ToString();
                __d["cat"] = __bic == BuiltInCategory.OST_Doors ? "door" : "window";
                try { var __te = doc.GetElement(__e.GetTypeId()); if (__te != null && __te.Name != null) __d["type"] = __te.Name; } catch {}
                var __h = __fi.Host;
                if (__h != null) {
                    __d["host_id"] = __h.Id.ToString();
                    try { var __hte = doc.GetElement(__h.GetTypeId()); if (__hte != null && __hte.Name != null) __d["host_type"] = __hte.Name; } catch {}
                }
                try {
                    var __lp = __e.get_Parameter(BuiltInParameter.FAMILY_LEVEL_PARAM);
                    if (__lp == null) __lp = __e.get_Parameter(BuiltInParameter.SCHEDULE_LEVEL_PARAM);
                    if (__lp != null && __lp.HasValue) {
                        var __le = doc.GetElement(__lp.AsElementId()) as Level;
                        if (__le != null && __le.Name != null) __d["level"] = __le.Name;
                    }
                } catch {}
                __hosted.Add(__d);
            } catch {}
        }
    } catch {}
}
__res["hosted"] = __hosted;

// rooms: identity + level + DEDUPED boundary element ids (walls/separators) —
// the edge set for "комнаты без окон"/"что ограничивает помещение X".
var __rooms = new List<object>();
try {
    var __opt = new SpatialElementBoundaryOptions();
    foreach (Element __re in new FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Rooms).WhereElementIsNotElementType()) {
        try {
            var __rm = __re as Autodesk.Revit.DB.Architecture.Room;
            if (__rm == null) continue;
            var __rd = new Dictionary<string,object>();
            __rd["id"] = __re.Id.ToString();
            try { if (__rm.Name != null) __rd["name"] = __rm.Name; } catch {}
            try { var __lv = __rm.Level; if (__lv != null && __lv.Name != null) __rd["level"] = __lv.Name; } catch {}
            var __bw = new List<object>();
            try {
                var __loops = __rm.GetBoundarySegments(__opt);
                if (__loops != null) {
                    var __seen2 = new HashSet<string>();
                    foreach (var __loop in __loops) {
                        foreach (var __seg in __loop) {
                            try {
                                var __bid = __seg.ElementId;
                                if (__bid != null && __bid != ElementId.InvalidElementId) {
                                    var __sid = __bid.ToString();
                                    if (__seen2.Add(__sid)) __bw.Add(__sid);
                                }
                            } catch {}
                        }
                    }
                }
            } catch {}
            __rd["boundary_ids"] = __bw;
            __rooms.Add(__rd);
        } catch {}
    }
} catch {}
__res["rooms"] = __rooms;
__res["hosted_n"] = __hosted.Count;
__res["rooms_n"] = __rooms.Count;
return __res;
"""


def build_relations_cs() -> str:
    """Stage 3: the RELATIONS extraction (hosting edges + room boundaries) —
    LAZY companion to the census: cached under model_cache kind "relations"
    (same fp family world_version(basic_ctx, {}), so write-invalidation drops
    it with the census slot). Raw edges live in the cache for Tier-1 queries;
    NOTHING of this is injected into the prompt (token discipline)."""
    return RELATIONS_CS


def build_inventory_cs() -> str:
    """The inventory census C# (body of Execute(doc, uidoc)). Constant for now;
    a function so Stage 2 can compose the material-takeoff source in."""
    return INVENTORY_CS


def build_census_cs() -> str:
    """Stage 1c: the UNIFIED census — INVENTORY + ORIENT (levels/grids) +
    HEALTH (warnings) + host-type VOCABULARY (material/function/width) in ONE
    read-only pass. This is the single extraction that replaces the fragmented
    GRAPH_CS/_TYPE_META_CS/VITALS_CS trio on the snapshot-passport path."""
    return INVENTORY_CS


# ── physical-vs-annotation classification — by STABLE category identity ───────
# Locale-independent (BuiltInCategory `bic` = OST_… is the same on RU/EN Revit,
# unlike display names). Primary signal = Revit's CategoryType; a small bic
# denylist catches Model-typed-but-non-physical categories (model lines, detail
# items, material defs…). A category that carries a REAL quantity is ALWAYS kept
# (a measured area/volume outweighs any name/type heuristic). Refined against
# live bic data — grow the denylist, don't invent name substrings.
_NON_PHYSICAL_BIC = frozenset({
    # "INVALID" = a category with no BuiltInCategory — imported CAD (*.dwg),
    # sheet-name-derived import schemas, custom non-standard categories.
    "INVALID",
    "OST_Lines", "OST_SketchLines", "OST_CLines", "OST_ModelText",
    "OST_InsulationLines", "OST_DetailComponents", "OST_Materials",
    "OST_MaterialAssetProperties", "OST_PropertySet",
    "OST_RvtLinks", "OST_RevitLinks", "OST_ProjectBasePoint",
    "OST_SharedBasePoint", "OST_SiteProperty", "OST_CoordinateSystem",
    "OST_VolumeOfInterest", "OST_Constraints", "OST_CenterLines",
    "OST_ReferencePlanes", "OST_ReferenceLines", "OST_Grids", "OST_Levels",
    "OST_ProjectInformation", "OST_SunPath", "OST_SunStudy",
    "OST_LegendComponents", "OST_PreviewLegendComponents", "OST_Cameras",
    "OST_TopographyContours", "OST_RoomSeparationLines",
    "OST_MEPSpaceSeparationLines", "OST_AreaSchemeLines", "OST_Views",
    "OST_Sheets", "OST_Viewports", "OST_RasterImages", "OST_ImportObjectStyles",
})


def _is_physical(name: str, c: dict) -> bool:
    """Keep a category if it's a real physical model quantity. Classify by STABLE
    identity (bic + CategoryType), NEVER localized display names, so it holds on
    any language / model class. A category carrying a real area/volume is always
    kept; otherwise: Annotation/Internal categories and the bic denylist are out."""
    has_qty = c.get("area_m2") is not None or c.get("volume_m3") is not None
    if has_qty:
        # even a quantity-bearing category is dropped if it's a known 2D/drafting
        # one (detail items carry a 2D 'area' that is NOT a physical quantity).
        if c.get("bic") in _NON_PHYSICAL_BIC:
            return False
        return True
    if c.get("cat_type") in ("Annotation", "Internal"):
        return False
    if c.get("bic") in _NON_PHYSICAL_BIC:
        return False
    # unknown bic (older Revit lacking Category.BuiltInCategory) + Model type →
    # keep (fail toward showing; the agent can ignore, worse to hide real data).
    return c.get("cat_type") == "Model"


def _fmt_measure(value, coverage: str, unit: str) -> str:
    """One measure, honestly: value+unit, with a coverage note ONLY when the
    source was partial (never a bare number hiding missing elements). Null → ''
    (the category simply has no such measure — not a fake 0). Fixed-precision
    (no %g — it drops decimals and scientific-notates campus-scale sums)."""
    if value is None:
        return ""
    try:
        n, tot = (int(x) for x in str(coverage).split("/"))
    except (ValueError, TypeError):
        n = tot = 0
    note = "" if (tot and n == tot) else f" (по {coverage})"
    num = f"{value:,.1f}".rstrip("0").rstrip(".").replace(",", " ")
    return f"{num} {unit}{note}"


def render_inventory(census: dict, *, max_categories: int = 40,
                     top_types: int = 3, min_count: int = 1) -> str:
    """Dense, agent-readable passport text from the inventory census.

    ЯВНО И УДОБНО: physical model categories only (annotation/2D dropped by
    stable identity), sorted by element count; per category — count + area/volume
    (with coverage when partial) + top-N types; never-fabricate stays visible
    ('' / no measure, never a fake 0). The full detail (all types, by_level, all
    categories) lives in the cache for Tier-1 queries; this is the injected
    summary. A header caveat is emitted when the census is host-only / phased /
    had element errors (so a partial snapshot is never silently trusted)."""
    if not isinstance(census, dict):
        return ""
    cats = census.get("categories") or {}
    model = {
        name: c for name, c in cats.items()
        if isinstance(c, dict) and c.get("count", 0) >= min_count
        and _is_physical(name, c)
    }
    # DETERMINISM: ties broken by name — the census dict's arrival order must
    # never leak into the rendered text (it feeds the prompt-cache stable layer).
    ordered = sorted(model.items(), key=lambda kv: (-kv[1].get("count", 0), kv[0]))
    phys_total = sum(c.get("count", 0) for c in model.values())

    lines: list[str] = []
    lines.append(f"## Инвентарь модели ({len(model)} физ-категорий, "
                 f"{phys_total} физ-элементов)")
    lines.append("Количества посчитаны сервером при загрузке (провенанс+покрытие; "
                 "«н/д» = нет источника, НЕ ноль). Для точечных фильтров — query_model.")
    # honesty caveats — a partial/qualified snapshot must announce itself
    caveats = []
    if census.get("linked_models"):
        # Say what is REACHABLE, not just what is missing: a loaded link can be
        # read, an unloaded one cannot, and the difference decides whether an
        # answer is "нет таких элементов" or "они в связи, я туда не смотрел".
        _ld = census.get("links_loaded")
        _un = census.get("links_unloaded")
        if isinstance(_ld, int) and isinstance(_un, int) and (_ld or _un):
            _names = census.get("link_loaded_names") or []
            _shown = ", ".join(str(n) for n in _names[:3])
            _tail = "…" if len(_names) > 3 else ""
            caveats.append(
                f"{census['linked_models']} связей: загружено {_ld}"
                + (f" ({_shown}{_tail})" if _shown else "")
                + f", не загружено {_un}. Их элементы НЕ вошли в подсчёт — "
                "FilteredElementCollector(doc) связи не видит. Нужны они — "
                "пройди RevitLinkInstance.GetLinkDocument() и скажи в ответе, "
                "про хост ты говоришь или про связь"
            )
        else:
            caveats.append(f"{census['linked_models']} связ. моделей НЕ учтены (только хост)")
    if census.get("phase_count", 1) and census.get("phase_count", 1) > 1:
        caveats.append(f"{census['phase_count']} фаз (снесённые исключены)")
    if census.get("design_options_present"):
        caveats.append("есть опции дизайна (учтён только основной вариант)")
    if census.get("errors"):
        caveats.append(f"{census['errors']} элементов не прочитаны")
    if caveats:
        lines.append("⚠ " + " · ".join(caveats))

    for name, c in ordered[:max_categories]:
        parts = [f"{c['count']} шт"]
        a = _fmt_measure(c.get("area_m2"), c.get("area_coverage", ""), "м²")
        if a:
            parts.append("площадь " + a)
        v = _fmt_measure(c.get("volume_m3"), c.get("volume_coverage", ""), "м³")
        if v:
            # Stage 2: disclose the takeoff provenance — a material-takeoff sum is
            # Revit's own schedule number, but the agent must know the source.
            if c.get("volume_takeoff_n"):
                v += " (по материалам)"
            parts.append("объём " + v)
        nt = c.get("types_total")
        if nt and nt > 1:
            parts.append(f"{nt} типов")
        lines.append(f"- **{name}** — " + " · ".join(parts))
        tops = c.get("types_top") or []
        if nt and nt > 1 and tops:
            # DETERMINISM: re-sort (C# OrderByDescending leaves tie order unstable).
            tops = sorted(tops, key=lambda t: (-(t.get("count") or 0), str(t.get("type"))))
            frag = []
            for t in tops[:top_types]:
                seg = f"{t.get('type')} {t.get('count')}шт"
                if t.get("area_m2"):
                    seg += f"/{_fmt_measure(t['area_m2'], '1/1', 'м²')}"
                elif t.get("volume_m3"):
                    seg += f"/{_fmt_measure(t['volume_m3'], '1/1', 'м³')}"
                mat = t.get("material")
                if mat:
                    # first material name only — glossary signal, not a takeoff
                    seg += f" [{str(mat).split(';')[0][:28]}]"
                w = t.get("width_mm")
                if w:
                    seg += f" {int(w)}мм"
                frag.append(seg)
            lines.append("    топ-типы: " + ", ".join(frag))
    if len(ordered) > max_categories:
        lines.append(f"…ещё {len(ordered) - max_categories} категорий "
                     "(меньше по количеству) — спроси query_model при нужде.")
    return "\n".join(lines)


def _fmt_elev(v) -> str:
    """Level elevation, compact: +12.4 / −4.2 / 0. Deterministic, fixed rules."""
    try:
        n = float(v)
    except (TypeError, ValueError):
        return "?"
    s = f"{n:+.3f}".rstrip("0").rstrip(".")
    return "0" if s in ("+0", "-0", "+", "-") else s.replace("-", "−")


def _unit_ru(type_id) -> str:
    """ForgeTypeId tail → human RU unit; unknown tails pass through honestly."""
    tail = str(type_id or "").split(":")[-1].split("-")[0]
    return {"millimeters": "мм", "centimeters": "см", "meters": "м",
            "feet": "фут", "squareMeters": "м²", "squareMillimeters": "мм²",
            "squareCentimeters": "см²", "squareFeet": "фут²"}.get(tail, tail)


def render_passport(census: dict, basic_ctx: dict | None = None) -> str:
    """The UNIFIED model passport from the one census (Stage 1c).

    Одно хорошее описание модели вместо 4 перекрывающихся экстракций:
    identity (из контекста плагина) + ORIENT (уровни/оси) + INVENTORY
    (количества, провенанс+покрытие) + HEALTH (warnings, помещения без
    площади). СТРОГО ДЕТЕРМИНИРОВАН (всё сортируется, никаких времён/
    счётчиков) — текст идёт в СТАБИЛЬНЫЙ слой промпта и не должен дрожать
    между ходами (prompt-cache). Never-fabricate: отсутствующий датум
    опускается, не рисуется нулём."""
    if not isinstance(census, dict):
        return ""
    ctx = basic_ctx or {}
    lines: list[str] = []

    # identity — from the plugin context (no C# needed); omit what we don't know
    doc_name = (ctx.get("document_name")
                or (ctx.get("document") or {}).get("name") or "")
    rv = (ctx.get("revit_version")
          or (ctx.get("document") or {}).get("revit_version") or "")
    head = "# Паспорт модели"
    if doc_name:
        head += f": {doc_name}"
    if rv:
        head += f" · Revit {rv}"
    # Revit's UNFILLED ProjectInformation ships localized placeholder strings —
    # showing them as identity would be fabrication-by-default.
    _PI_PLACEHOLDERS = {"наименование проекта", "project name",
                        "номер проекта", "project number", ""}
    pn = str(census.get("project_name") or "")
    if pn and pn != doc_name and pn.strip().lower() not in _PI_PLACEHOLDERS:
        head += f" · проект: {pn}"
    pnum = str(census.get("project_number") or "")
    if pnum and pnum.strip().lower() not in _PI_PLACEHOLDERS:
        head += f" (№ {pnum})"
    lines.append(head)

    # ORIENT — levels sorted by elevation, grids sorted by name
    lvls = [l for l in (census.get("levels") or [])
            if isinstance(l, dict) and l.get("name")]
    if lvls:
        lvls = sorted(lvls, key=lambda l: (float(l.get("elev_m") or 0), str(l["name"])))
        if len(lvls) <= 14:
            body = " · ".join(f"{l['name']} ({_fmt_elev(l.get('elev_m'))})" for l in lvls)
        else:
            body = (f"{_fmt_elev(lvls[0].get('elev_m'))} … "
                    f"{_fmt_elev(lvls[-1].get('elev_m'))} м; "
                    + ", ".join(str(l["name"]) for l in lvls[:14]) + ", …")
        lines.append(f"**Уровни ({len(lvls)}):** {body}")
    grids = sorted(str(g) for g in (census.get("grids") or []) if g)
    if grids:
        shown = ", ".join(grids[:30]) + (", …" if len(grids) > 30 else "")
        lines.append(f"**Оси ({len(grids)}):** {shown}")

    # Units + georeferencing (Stage 1f) — the agent writes values in THESE units
    ul, ua = census.get("unit_length"), census.get("unit_area")
    if ul or ua:
        seg = []
        if ul:
            seg.append(f"длина {_unit_ru(ul)}")
        if ua:
            seg.append(f"площадь {_unit_ru(ua)}")
        lines.append("**Единицы:** " + ", ".join(seg))
    tn, pe = census.get("true_north_deg"), census.get("project_elevation_m")
    geo = []
    if isinstance(tn, (int, float)) and abs(tn) > 0.01:
        geo.append(f"истинный север {tn}°")
    if isinstance(pe, (int, float)) and abs(pe) > 0.001:
        num = f"{pe:+.3f}".rstrip("0").rstrip(".").replace("-", "−")
        geo.append(f"отметка проекта {num} м")
    if geo:
        lines.append("**Геопривязка:** " + "; ".join(geo))

    # MEP systems (Stage 1d) — sorted by size then name (deterministic);
    # n < 0 = element count unreadable → name only, never a fabricated number.
    mep = [m for m in (census.get("mep_systems") or [])
           if isinstance(m, dict) and m.get("name")]
    if mep:
        mep = sorted(mep, key=lambda m: (-(m.get("n") if isinstance(m.get("n"), int) and m["n"] >= 0 else -1),
                                         str(m["name"])))
        frag = []
        for m in mep[:12]:
            n = m.get("n")
            frag.append(f"{m['name']} ({n} эл.)" if isinstance(n, int) and n >= 0 else str(m["name"]))
        more = f", … ещё {len(mep) - 12}" if len(mep) > 12 else ""
        lines.append(f"**Системы MEP ({len(mep)}):** " + ", ".join(frag) + more)

    # Worksharing (Stage 1e): the agent must know it's a central model + worksets
    if census.get("workshared"):
        ws = sorted(str(w) for w in (census.get("worksets") or []) if w)
        wline = "**Совместная работа:** центральная модель"
        if ws:
            wline += (f"; рабочие наборы ({len(ws)}): " + ", ".join(ws[:12])
                      + (", …" if len(ws) > 12 else ""))
        lines.append(wline)

    # DOCUMENTATION (Stage 1e): views/sheets/schedules summary; full lists in cache
    # internal/system view kinds are browser plumbing, not documentation;
    # DrawingSheet is counted separately as листы
    _NON_DOC_VIEWS = {"ProjectBrowser", "SystemBrowser", "Internal", "Undefined",
                      "DrawingSheet"}
    vbt = {k: v for k, v in (census.get("views_by_type") or {}).items()
           if k not in _NON_DOC_VIEWS}
    sheets = census.get("sheets") or []
    scheds = census.get("schedules") or []
    if vbt or sheets or scheds:
        n_views = sum(v for v in vbt.values() if isinstance(v, int))
        parts = []
        if n_views:
            top_vt = sorted(vbt.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
            parts.append(f"видов {n_views} (" + ", ".join(f"{t}: {n}" for t, n in top_vt) + ")")
        if sheets:
            sample = ", ".join(f"{s.get('number')} «{str(s.get('name'))[:24]}»"
                               for s in sorted(sheets, key=lambda s: str(s.get("number")))[:6]
                               if isinstance(s, dict))
            parts.append(f"листов {len(sheets)}: {sample}" + (", …" if len(sheets) > 6 else ""))
        if scheds:
            parts.append(f"спецификаций {len(scheds)}: "
                         + ", ".join(sorted(str(s) for s in scheds)[:8])
                         + (", …" if len(scheds) > 8 else ""))
        vtpl = sorted(str(t) for t in (census.get("view_templates") or []) if t)
        if vtpl:
            parts.append(f"шаблонов видов {len(vtpl)}: " + ", ".join(vtpl[:6])
                         + (", …" if len(vtpl) > 6 else ""))
        lines.append("**Документация:** " + " · ".join(parts))
    vflt = sorted(str(f) for f in (census.get("view_filters") or []) if f)
    if vflt:
        lines.append(f"**Фильтры видимости ({len(vflt)}):** " + ", ".join(vflt[:8])
                     + (", …" if len(vflt) > 8 else ""))
    links = sorted(str(l) for l in (census.get("link_names") or []) if l)
    if links:
        lines.append(f"**Связи ({len(links)}):** " + ", ".join(l[:40] for l in links[:8])
                     + (", …" if len(links) > 8 else ""))
    phn = [str(p) for p in (census.get("phase_names") or []) if p]
    if len(phn) > 1:
        lines.append(f"**Фазы ({len(phn)}):** " + ", ".join(phn[:8]))

    # INVENTORY — the census core (богатая сводка: все физ-категории, топ-5 типов)
    inv = render_inventory(census, max_categories=200, top_types=5)
    if inv:
        lines.append("")
        lines.append(inv)

    # MATERIALS-IN-USE (Stage 1e) — sorted by takeoff volume, then usage, then name
    mats = census.get("materials") or {}
    if isinstance(mats, dict) and mats:
        rows = [(n, m) for n, m in mats.items() if isinstance(m, dict)]
        rows.sort(key=lambda kv: (-(kv[1].get("volume_m3") or 0),
                                  -(kv[1].get("n") or 0), kv[0]))
        frag = []
        for n, m in rows[:15]:
            v = m.get("volume_m3")
            frag.append(f"{n} — {v} м³ ({m.get('n')} эл.)" if v
                        else f"{n} ({m.get('n')} эл.)")
        lines.append("")
        lines.append(f"**Материалы в модели ({len(rows)}):** " + " · ".join(frag)
                     + (f" · … ещё {len(rows) - 15}" if len(rows) > 15 else ""))

    # FAMILIES (Stage 1e) — loaded vs placed; unplaced disclosed (агент может
    # ставить эти семейства при моделинге БЕЗ подгрузки)
    fams = census.get("families") or {}
    if isinstance(fams, dict) and fams:
        rows = [(n, f) for n, f in fams.items() if isinstance(f, dict)]
        placed = sorted(((n, f) for n, f in rows if (f.get("placed_n") or 0) > 0),
                        key=lambda kv: (-(kv[1].get("placed_n") or 0), kv[0]))
        unplaced_n = len(rows) - len(placed)
        fline = f"**Семейства ({len(rows)} загружено"
        if unplaced_n:
            fline += f", {unplaced_n} не размещено — можно ставить без подгрузки"
        fline += "):** " + ", ".join(
            f"{n} ({f.get('category')}, {f.get('placed_n')} шт)" for n, f in placed[:10])
        if len(placed) > 10:
            fline += f", … ещё {len(placed) - 10} размещённых"
        lines.append("")
        lines.append(fline)

    # PROJECT/SHARED PARAMS (Stage 1f) — the «заполни параметр X» grounding
    pb = [p for p in (census.get("param_bindings") or [])
          if isinstance(p, dict) and p.get("name")]
    if pb:
        pb = sorted(pb, key=lambda p: str(p["name"]))
        frag = []
        for p in pb[:10]:
            cats = p.get("cats") or []
            seg = f"{p['name']} ({'тип' if p.get('kind') == 'type' else 'экз'}"
            if cats:
                seg += f": {cats[0]}" + (f"+{len(cats) - 1}" if len(cats) > 1 else "")
            seg += ")"
            frag.append(seg)
        lines.append("")
        lines.append(f"**Параметры проекта ({len(pb)}):** " + ", ".join(frag)
                     + (f", … ещё {len(pb) - 10}" if len(pb) > 10 else ""))

    # CAD underlays + model groups (Stage 1f)
    dwg = [d for d in (census.get("cad_imports") or []) if isinstance(d, dict)]
    if dwg:
        vs = sum(1 for d in dwg if d.get("view_specific"))
        parts = []
        if len(dwg) - vs:
            parts.append(f"{len(dwg) - vs} модельных")
        if vs:
            parts.append(f"{vs} видовых")
        lines.append(f"**Подложки CAD ({len(dwg)}):** " + ", ".join(parts))
    grps = census.get("groups") or {}
    if isinstance(grps, dict) and grps:
        rows = sorted(grps.items(), key=lambda kv: (-kv[1], kv[0]))
        lines.append(f"**Группы ({sum(grps.values())} разм., {len(grps)} имён):** "
                     + ", ".join(f"{n}×{c}" for n, c in rows[:8])
                     + (", …" if len(rows) > 8 else ""))

    # HEALTH — honest: warnings only when READ (None = could not read, omit);
    # rooms-without-area derived from the Rooms category's own coverage.
    health: list[str] = []
    w = census.get("warnings")
    if isinstance(w, int):
        health.append(f"{w} предупреждений Revit")
    for name, c in (census.get("categories") or {}).items():
        if isinstance(c, dict) and c.get("bic") == "OST_Rooms" and c.get("count"):
            try:
                n, tot = (int(x) for x in str(c.get("area_coverage", "")).split("/"))
                if tot and n < tot:
                    health.append(f"{tot - n} помещений без площади "
                                  "(не размещены/не замкнуты)")
            except (ValueError, TypeError):
                pass
            break
    if health:
        lines.append("")
        lines.append("**Здоровье:** " + " · ".join(sorted(health)))

    lines.append("")
    lines.append("_Полные таблицы типов/параметров/листов — `get_model_details`; "
                 "точечные выборки — `query_model`._")
    return "\n".join(lines)
