"""query_model — declarative spec -> ONE version-safe read-only C# template.

The LLM passes a JSON spec (category/type/param + return/action); the backend
emits a single battle-tested C# body for `Execute(Document doc, UIDocument uidoc)`.
This removes ad-hoc discovery C# (the #1 compile-error / repair-round source,
audit 2026-06-06) and makes element discovery as reliable as the family tools.

Version-safety: NEVER uses ElementId.Value / .IntegerValue (the cross-version
trap, F2/F5) — ids go out via `Id.ToString()`; areas/volumes via the stable
HOST_AREA_COMPUTED / HOST_VOLUME_COMPUTED params. Returns Dictionary<string,object>
so keys survive obfuscation (F1).

Supported spec keys (v1):
  category        str  — RU/EN alias, resolved to BuiltInCategory (kukai.write.router)
  type_contains   str  — case-insensitive substring on the element's TYPE name
  type_names      [str]— exact type-name allow-list (use with the passport glossary)
  param           {name, op: empty|not_empty|eq|contains|gt|lt, value?}
  selected        bool — operate on the current selection instead of the whole model
  return          count|ids|aggregate|group   (default count)
  aggregate       subset of [count, area_m2, volume_m3]
  group_by        type | level   (material deferred; level folds per-group
                  count + area_m2/volume_m3 when aggregate requests them)
  action          select|isolate|highlight|none   (default none)
  limit           int    — cap for returned ids (default 1000)

Deferred to v2: material_contains, group_by material, structural filter.
"""
from __future__ import annotations

from typing import Any, Optional

_VALID_OPS = {"empty", "not_empty", "eq", "contains", "gt", "lt"}
_DEFAULT_ID_LIMIT = 1000
# M3 semantic predicates — WallFunction enum (verified in api_surface_2023.json).
_WALL_FUNCTIONS = {"exterior": "Exterior", "interior": "Interior", "foundation": "Foundation",
                   "retaining": "Retaining", "coreshaft": "Coreshaft", "soffit": "Soffit"}


def _csstr(s: Any) -> str:
    """Render a Python value as a safe C# double-quoted string literal."""
    t = "" if s is None else str(s)
    t = (t.replace("\\", "\\\\").replace('"', '\\"')
          .replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t"))
    return f'"{t}"'


def _resolve_category(category: str) -> Optional[str]:
    """alias -> 'OST_...' via the shared write router (canonical map + semantic
    fallback), then any REAL BuiltInCategory base-name via api_surface."""
    if not category:
        return None
    try:
        from kukai.write.router import resolve_category
        r = resolve_category(category)
        if r:
            return r
    except Exception:
        pass
    c = category.strip()
    if c.startswith("OST_"):
        return c
    # Data-driven base-name: "DuctCurves"/"duct curves" -> OST_DuctCurves, etc.
    # Resolves every valid BuiltInCategory (s17: query_model hard-failed on the
    # literal EN base-name the model passed) with NO hand-maintained list.
    try:
        from kukai.llm.api_members import builtin_category_names
        cand = "ost_" + c.replace(" ", "").lower()
        for name in builtin_category_names():
            if name.lower() == cand:
                return name
    except Exception:
        pass
    return None


def _category_suggestions(category: str, limit: int = 4) -> list[str]:
    """Closest known category aliases for an unresolved term (typo help)."""
    try:
        import difflib
        from kukai.categories import CATEGORY_MAP
        return difflib.get_close_matches(
            category.lower().strip(), list(CATEGORY_MAP), n=limit, cutoff=0.6
        )
    except Exception:
        return []


# ── GAP-1 field vocabulary ───────────────────────────────────────────────────
# Derived from the 513 pure-read C# scripts in prod (docs/2026-07-28-query-model-
# output-gaps.md), by how often each was actually touched:
#   Name 194 · Category 146 · type 140 · level 99 · volume 51 · mark 33 ·
#   length 27 · area 22 · height 24 · width 22
# Measures are emitted as boxed doubles (never strings) so order_by can compare
# them numerically; an unavailable measure is null, never a fake 0 — the same
# absence-is-not-zero discipline the aggregate path already follows.
_TABLE_FIELDS = frozenset({
    "id", "name", "category", "type", "level", "mark",
    "area_m2", "volume_m3", "length_m", "height_mm", "width_mm",
})
_MAX_TABLE_FIELDS = 12
_DEFAULT_TABLE_LIMIT = 200
_MAX_TABLE_LIMIT = 1000

# Internal (feet-based) → display factors. Revit stores lengths in feet.
_FT_TO_M = 0.3048
_FT_TO_MM = 304.8
_SQFT_TO_M2 = 0.09290304
_CUFT_TO_M3 = 0.028316846592


def _emit_table_field(field: str) -> list[str]:
    """C# lines writing ONE column into `__r` for the current element `__x`.

    Every emitter is wrapped in its own brace block so locals stay scoped and
    two columns can never collide — and, deliberately, so no local here shadows
    one from the enclosing method (that is exactly the CS0136 landmine fixed in
    the unit-conversion path on 2026-07-28)."""
    if field == "id":
        return ['__r["id"] = __x.Id.ToString();']
    if field == "name":
        return ['__r["name"] = (__x.Name != null) ? __x.Name : null;']
    if field == "category":
        return ['__r["category"] = (__x.Category != null && __x.Category.Name != null) '
                '? __x.Category.Name : null;']
    if field == "type":
        # Guarded exactly like the per-element filter above: a category with no
        # type (many system/annotation elements) yields InvalidElementId, and
        # `table` — unlike group_by=type — can be asked for ANY category.
        return ['{ ElementId __tti = __x.GetTypeId();',
                '  Element __tt = (__tti != null && __tti != ElementId.InvalidElementId) '
                '? doc.GetElement(__tti) : null;',
                '  __r["type"] = (__tt != null && __tt.Name != null) ? __tt.Name : null; }']
    if field == "level":
        # SAME resolution chain as the `level` filter and group_by=level, so a
        # row's level can never disagree with the filter that selected it.
        return ['{ string __lvl = null;',
                '  var __lvp = __x.get_Parameter(BuiltInParameter.WALL_BASE_CONSTRAINT);',
                '  if (__lvp == null) __lvp = __x.get_Parameter(BuiltInParameter.LEVEL_PARAM);',
                '  if (__lvp == null) __lvp = __x.get_Parameter(BuiltInParameter.SCHEDULE_LEVEL_PARAM);',
                '  if (__lvp == null) __lvp = __x.get_Parameter(BuiltInParameter.FAMILY_LEVEL_PARAM);',
                '  if (__lvp != null && __lvp.HasValue) { var __lve = doc.GetElement(__lvp.AsElementId()) as Level;',
                '    if (__lve != null && __lve.Name != null) __lvl = __lve.Name; }',
                '  if (__lvl == null) { try { var __lid2 = __x.LevelId;',
                '    if (__lid2 != null && __lid2 != ElementId.InvalidElementId) {',
                '      var __lve2 = doc.GetElement(__lid2) as Level;',
                '      if (__lve2 != null && __lve2.Name != null) __lvl = __lve2.Name; } } catch {} }',
                '  __r["level"] = __lvl; }']
    if field == "mark":
        return ['{ var __mkp = __x.get_Parameter(BuiltInParameter.ALL_MODEL_MARK);',
                '  __r["mark"] = (__mkp != null && __mkp.HasValue) ? __mkp.AsString() : null; }']
    if field == "area_m2":
        return ['{ var __arp = __x.get_Parameter(BuiltInParameter.HOST_AREA_COMPUTED);',
                '  if (__arp == null || !__arp.HasValue) __arp = __x.get_Parameter(BuiltInParameter.ROOM_AREA);',
                '  __r["area_m2"] = (__arp != null && __arp.HasValue) '
                f'? (object)Math.Round(__arp.AsDouble() * {_SQFT_TO_M2}, 2) : null; }}']
    if field == "volume_m3":
        return ['{ var __vop = __x.get_Parameter(BuiltInParameter.HOST_VOLUME_COMPUTED);',
                '  if (__vop == null || !__vop.HasValue) __vop = __x.get_Parameter(BuiltInParameter.ROOM_VOLUME);',
                '  __r["volume_m3"] = (__vop != null && __vop.HasValue) '
                f'? (object)Math.Round(__vop.AsDouble() * {_CUFT_TO_M3}, 3) : null; }}']
    if field == "length_m":
        return ['{ var __lnp = __x.get_Parameter(BuiltInParameter.CURVE_ELEM_LENGTH);',
                '  __r["length_m"] = (__lnp != null && __lnp.HasValue) '
                f'? (object)Math.Round(__lnp.AsDouble() * {_FT_TO_M}, 3) : null; }}']
    if field == "height_mm":
        return ['{ var __htp = __x.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM);',
                '  if (__htp == null || !__htp.HasValue) __htp = __x.get_Parameter(BuiltInParameter.GENERIC_HEIGHT);',
                '  __r["height_mm"] = (__htp != null && __htp.HasValue) '
                f'? (object)Math.Round(__htp.AsDouble() * {_FT_TO_MM}, 1) : null; }}']
    if field == "width_mm":
        # A wall's real thickness lives on its TYPE (WallType.Width) — the same
        # source the width_mm FILTER reads, so filter and column agree. Families
        # (doors/windows/generic) carry it as an instance/type parameter instead.
        return ['{ double? __wd = null;',
                '  ElementId __wti = __x.GetTypeId();',
                '  var __wtt = (__wti != null && __wti != ElementId.InvalidElementId) '
                '? doc.GetElement(__wti) as WallType : null;',
                f'  if (__wtt != null) __wd = __wtt.Width * {_FT_TO_MM};',
                '  if (__wd == null) { var __wdp = __x.get_Parameter(BuiltInParameter.GENERIC_WIDTH);',
                '    if (__wdp == null || !__wdp.HasValue) __wdp = __x.get_Parameter(BuiltInParameter.DOOR_WIDTH);',
                '    if (__wdp == null || !__wdp.HasValue) __wdp = __x.get_Parameter(BuiltInParameter.WINDOW_WIDTH);',
                f'    if (__wdp != null && __wdp.HasValue) __wd = __wdp.AsDouble() * {_FT_TO_MM}; }}',
                '  __r["width_mm"] = __wd.HasValue ? (object)Math.Round(__wd.Value, 1) : null; }']
    if field.startswith("param:"):
        pname = field[6:].strip()
        return ['{ Parameter __ppp = __x.LookupParameter(%s);' % _csstr(pname),
                '  __r[%s] = (__ppp != null && __ppp.HasValue) ? (object)(__ppp.AsValueString() '
                '?? (__ppp.StorageType == StorageType.String ? __ppp.AsString() : null)) : null; }'
                % _csstr(field)]
    raise ValueError(f"unknown table field: {field!r}")


def build_query_code(spec: dict[str, Any]) -> str:
    """Return the C# METHOD BODY (statements + `return __res;`) for the spec.

    Raises ValueError on an invalid spec so the caller can surface a clear error
    instead of generating broken C#.
    """
    if not isinstance(spec, dict):
        raise ValueError("spec must be an object")

    category = (spec.get("category") or "").strip()
    bic = _resolve_category(category) if category else None
    if category and not bic:
        sugg = _category_suggestions(category)
        hint = f" Похожие: {', '.join(sugg)}." if sugg else ""
        raise ValueError(f"unknown category alias: {category!r}.{hint}")

    type_contains = spec.get("type_contains")
    type_names = spec.get("type_names")
    if type_names is not None and not isinstance(type_names, list):
        raise ValueError("type_names must be a list of strings")
    param = spec.get("param")
    use_selection = bool(spec.get("selected"))
    ret = (spec.get("return") or "count").strip().lower()
    if ret not in {"count", "ids", "aggregate", "group", "coverage", "table"}:
        raise ValueError(f"invalid return: {ret!r}")
    if ret == "coverage" and not (isinstance(param, dict) and param.get("name")):
        raise ValueError("return=coverage requires param.name (the parameter to measure)")
    aggregate = spec.get("aggregate") or ["count", "area_m2", "volume_m3"]
    group_by = (spec.get("group_by") or "type").strip().lower()
    # group_by: type (default) or level (2026-07-12). Level grouping reuses the
    # SAME vetted level-name chain as the level filter (WALL_BASE→LEVEL→SCHEDULE
    # →FAMILY→LevelId). This lets "площадь перекрытий ПО УРОВНЯМ" resolve as one
    # structured query_model call instead of raw execute_revit_code (the exec-
    # gravity lever). Material grouping stays deferred — a multi-material element
    # has no single grouping key. group_by=level was previously rejected loudly
    # (better than the old silent type-mislabel); now it is real.
    if group_by not in {"type", "level"}:
        raise ValueError(
            f"invalid group_by: {group_by!r} (supported: 'type', 'level'; "
            "material grouping is not implemented yet)"
        )
    action = (spec.get("action") or "none").strip().lower()
    if action not in {"none", "select", "isolate", "highlight"}:
        raise ValueError(f"invalid action: {action!r}")
    try:
        limit = int(spec.get("limit") or _DEFAULT_ID_LIMIT)
    except (TypeError, ValueError):
        limit = _DEFAULT_ID_LIMIT
    limit = max(1, min(limit, 5000))

    # GAP-1/GAP-3 (spec docs/2026-07-28-query-model-output-gaps.md): projection
    # + ordering. 57% of the raw-C# reads in prod were a .Select of a handful of
    # fields, 25% sorted and 16% took a top-N — none of which any `return` shape
    # could express, so the model had to write C#. `table` is that shape.
    fields: list[str] = []
    order_by = None
    order_desc = False
    if ret == "table":
        raw_fields = spec.get("fields")
        if raw_fields is None:
            raw_fields = ["id", "name", "type"]
        if not isinstance(raw_fields, list) or not raw_fields:
            raise ValueError("fields must be a non-empty list of strings")
        if len(raw_fields) > _MAX_TABLE_FIELDS:
            raise ValueError(f"too many fields (max {_MAX_TABLE_FIELDS})")
        for f in raw_fields:
            f = str(f).strip()
            if not (f in _TABLE_FIELDS or f.startswith("param:")):
                raise ValueError(
                    f"unknown field: {f!r} (known: {sorted(_TABLE_FIELDS)}; "
                    "any other parameter as 'param:<Имя>')")
            if f.startswith("param:") and not f[6:].strip():
                raise ValueError("param: field needs a parameter name")
            if f not in fields:
                fields.append(f)
        order_by = spec.get("order_by")
        if order_by is not None:
            order_by = str(order_by).strip()
            if order_by not in fields:
                raise ValueError(
                    f"order_by={order_by!r} must be one of the requested fields: {fields}")
        _ord = (spec.get("order") or "asc").strip().lower()
        if _ord not in {"asc", "desc"}:
            raise ValueError("order must be 'asc' or 'desc'")
        order_desc = _ord == "desc"
        # Rows are far heavier than ids: cap tighter, and default to a size that
        # informs without flooding the model's context.
        if spec.get("limit") is None:
            limit = _DEFAULT_TABLE_LIMIT
        limit = max(1, min(limit, _MAX_TABLE_LIMIT))

    # --- M3 semantic predicates (read the REAL property live; no plugin needed).
    #     Fixes the study's name-vs-property bug (s2/s6/s12). Each uses an `as`
    #     cast so it fails closed on categories where it doesn't apply.
    function = spec.get("function")
    if function is not None:
        function = str(function).strip().lower()
        if function not in _WALL_FUNCTIONS:
            raise ValueError(f"invalid function: {function!r} (use {sorted(_WALL_FUNCTIONS)})")
    width_mm = spec.get("width_mm")
    if width_mm is not None:
        if not isinstance(width_mm, dict) or (width_mm.get("op") not in {"gt", "lt", "eq", "range"}):
            raise ValueError("width_mm must be {op: gt|lt|eq|range, value, value2?}")
    layer_material_contains = spec.get("layer_material_contains")
    level = spec.get("level")

    L: list[str] = []
    # Static, build-time list of predicates that WERE compiled into the filter,
    # so a zero result is never naked — the model/user can see exactly what ran
    # (D-disclosure). Runtime fail-closed cases are reported via __pskip below.
    applied: list[str] = []
    if use_selection:
        applied.append("selected")
    if bic:
        applied.append(f"category={bic}")
    L.append("var __res = new Dictionary<string,object>();")
    # __pskip collects predicates that could NOT be honored at RUNTIME (e.g. a
    # unit conversion that couldn't resolve, or an aggregate metric the category
    # doesn't support) — populated by the emitters below.
    L.append("var __pskip = new List<string>();")
    # one-shot guard so a per-element unit-resolution failure is reported once.
    L.append("bool __skUnit = false;")
    # --- collector (whole model or current selection) ---
    if use_selection:
        L.append("var __selIds = uidoc != null ? uidoc.Selection.GetElementIds() : new List<ElementId>();")
        L.append("FilteredElementCollector __c = (__selIds != null && __selIds.Count > 0) "
                 "? new FilteredElementCollector(doc, __selIds) : new FilteredElementCollector(doc);")
    else:
        L.append("FilteredElementCollector __c = new FilteredElementCollector(doc);")
    L.append("__c = __c.WhereElementIsNotElementType();")
    if bic:
        L.append(f"__c = __c.OfCategory(BuiltInCategory.{bic});")
    L.append("var __all = __c.ToElements();")
    L.append("var __m = new List<Element>();")

    # --- per-element filters ---
    _pre_loop_idx = len(L)          # anchor for counters that must precede the loop
    L.append("foreach (Element __e in __all) {")
    L.append("  bool __ok = true;")
    L.append("  ElementId __tid = __e.GetTypeId();")
    L.append("  Element __te = (__tid != null && __tid != ElementId.InvalidElementId) ? doc.GetElement(__tid) : null;")
    L.append("  string __tn = (__te != null && __te.Name != null) ? __te.Name : \"\";")
    if type_contains:
        applied.append(f"type_contains={type_contains}")
        L.append(f"  if (__ok) __ok = __tn.ToLower().Contains({_csstr(str(type_contains).lower())});")
    if type_names:
        applied.append("type_names")
        items = ", ".join(_csstr(n) for n in type_names if str(n).strip())
        L.append(f"  if (__ok) {{ var __tns = new HashSet<string>() {{ {items} }}; __ok = __tns.Contains(__tn); }}")
    if isinstance(param, dict) and param.get("name") and ret != "coverage":
        op = (param.get("op") or "not_empty").strip().lower()
        if op not in _VALID_OPS:
            raise ValueError(f"invalid param.op: {op!r}")
        applied.append(f"param.{op}({param.get('name')})")
        pn = _csstr(param.get("name"))
        pv = _csstr(param.get("value"))
        # D-disclosure (2026-07-28, live check on a real ЭОМ model): a parameter
        # name that exists NOWHERE returned a confident 0 with an empty
        # predicates_skipped — indistinguishable from an honest empty result.
        # Observed for real: «Высота» instead of «Неприсоединенная высота» →
        # "0 стен" with no hint that the NAME, not the model, was wrong. The
        # declarative path is about to become the default, so the model WILL
        # guess names; it must be told when a guess matched nothing.
        L.insert(_pre_loop_idx, "int __pFound = 0;")
        L.append(f"  if (__ok) {{ Parameter __p = __e.LookupParameter({pn});")
        L.append("    if (__p != null) __pFound++;")
        if op == "empty":
            L.append("    __ok = (__p == null) || (!__p.HasValue) || string.IsNullOrEmpty(__p.AsValueString());")
        elif op == "not_empty":
            L.append("    __ok = (__p != null) && __p.HasValue && !string.IsNullOrEmpty(__p.AsValueString());")
        elif op == "eq":
            L.append(f"    string __pv = (__p!=null)?(__p.AsValueString() ?? (__p.StorageType==StorageType.String?__p.AsString():null)):null;")
            L.append(f"    __ok = (__pv != null) && (__pv == {pv});")
        elif op == "contains":
            L.append(f"    string __pv = (__p!=null)?(__p.AsValueString() ?? (__p.StorageType==StorageType.String?__p.AsString():null)):null;")
            L.append(f"    __ok = (__pv != null) && __pv.ToLower().Contains((({pv}) ?? \"\").ToLower());")
        elif op in ("gt", "lt"):
            cmp = ">" if op == "gt" else "<"
            # D3 FIX: the user value is in DISPLAY units (mm for lengths — the
            # *_mm convention), but Parameter.AsDouble() returns Revit INTERNAL
            # units (feet for lengths). A bare `AsDouble() > value` compared mm
            # against feet → near-always false → confident wrong zero. We convert
            # the parameter value from internal units to the parameter's own
            # DISPLAY units, then compare against the (display-unit) user value.
            #
            # Version-safety: this ONE emitted body is compiled across Revit
            # 2021-2026. We cannot #if (blocked by the validator) nor name
            # ForgeTypeId/SpecTypeId (CS0246 on 2021) or DisplayUnitType/UnitType
            # (removed in 2024+) directly. So we resolve the unit and call the
            # right UnitUtils.ConvertFromInternalUnits overload via reflection
            # (permitted by the validator; the same cross-version pattern Revit
            # tooling uses). Fails CLOSED to a unit-aware result, never to the
            # raw feet-vs-mm compare.
            L.append(f"    double __cmp; bool __okn = double.TryParse({pv}, out __cmp);")
            L.append("    if (!__okn || __p == null || !__p.HasValue || __p.StorageType != StorageType.Double) { __ok = false; }")
            L.append("    else {")
            L.append("      double __raw = __p.AsDouble();          // INTERNAL units (feet for lengths)")
            L.append("      double __disp = __raw; bool __conv = false;")
            L.append("      try {")
            L.append("        var __uu = typeof(UnitUtils);")
            # 2022+: Parameter.GetUnitTypeId() -> ForgeTypeId (the param's own,
            # doc/locale-aware display unit). Resolved by reflection so the
            # ForgeTypeId type name never appears in source (compiles on 2021).
            L.append("        object __unit = null;")
            L.append("        try { var __gut = __p.GetType().GetMethod(\"GetUnitTypeId\", Type.EmptyTypes);")
            L.append("          if (__gut != null) __unit = __gut.Invoke(__p, null); } catch {}")
            L.append("        if (__unit != null) {")
            # NOTE (2026-07-28): this local MUST NOT be named `__m` — that name is
            # already taken by the matched-element list declared in the ENCLOSING
            # method scope, and C# rejects the shadow with CS0136 (verified against
            # the live Roslyn service: every param.op=gt|lt query failed to compile
            # and never reached Revit). Prod traces show 0 gt/lt calls, so no user
            # ever hit it — a landmine under the declarative path, disarmed here.
            L.append("          var __mi = __uu.GetMethod(\"ConvertFromInternalUnits\", new Type[] { typeof(double), __unit.GetType() });")
            L.append("          if (__mi != null) { __disp = (double)__mi.Invoke(null, new object[] { __raw, __unit }); __conv = true; }")
            L.append("        }")
            # <=2021: Parameter.DisplayUnitType (DisplayUnitType enum) + the
            # (double, DisplayUnitType) overload. DisplayUnitType is gone in
            # 2024+, so it too is reached only via reflection.
            L.append("        if (!__conv) {")
            L.append("          object __dut = null;")
            L.append("          try { var __pdut = __p.GetType().GetProperty(\"DisplayUnitType\");")
            L.append("            if (__pdut != null) __dut = __pdut.GetValue(__p); } catch {}")
            L.append("          if (__dut != null) {")
            L.append("            var __m2 = __uu.GetMethod(\"ConvertFromInternalUnits\", new Type[] { typeof(double), __dut.GetType() });")
            L.append("            if (__m2 != null) { __disp = (double)__m2.Invoke(null, new object[] { __raw, __dut }); __conv = true; } }")
            L.append("        }")
            L.append("      } catch { __conv = false; }")
            # If we could not resolve the unit on this element, disclose it once
            # via predicates_skipped rather than silently comparing internal feet.
            L.append(f"      if (!__conv && !__skUnit) {{ __pskip.Add({_csstr('param.' + op + '(' + str(param.get('name')) + ') unit-unresolved')}); __skUnit = true; }}")
            L.append(f"      __ok = (__disp {cmp} __cmp);")
            L.append("    }")
        L.append("  }")
    # --- M3 semantic predicates (emitted into the per-element filter) ---
    if function:
        applied.append(f"function={function}")
        L.append(f"  if (__ok) {{ var __wtf = __te as WallType; "
                 f"__ok = (__wtf != null) && (__wtf.Function == WallFunction.{_WALL_FUNCTIONS[function]}); }}")
    if width_mm is not None:
        applied.append(f"width_mm.{width_mm.get('op')}")
        _op = width_mm.get("op")
        _v = float(width_mm.get("value") or 0)
        L.append("  if (__ok) { var __wtw = __te as WallType;")
        L.append("    if (__wtw == null) { __ok = false; } else { double __wmm = __wtw.Width * 304.8;")
        if _op == "gt":
            L.append(f"      __ok = (__wmm > {_v}); }} }}")
        elif _op == "lt":
            L.append(f"      __ok = (__wmm < {_v}); }} }}")
        elif _op == "eq":
            L.append(f"      __ok = (Math.Abs(__wmm - {_v}) < 1.0); }} }}")
        else:  # range
            _v2 = float(width_mm.get("value2") if width_mm.get("value2") is not None else _v)
            L.append(f"      __ok = (__wmm >= {_v} && __wmm <= {_v2}); }} }}")
    if layer_material_contains:
        applied.append(f"layer_material_contains={layer_material_contains}")
        _mv = _csstr(str(layer_material_contains).lower())
        L.append("  if (__ok) {")
        L.append("    var __ho = __te as HostObjAttributes; bool __hasMat = false;")
        L.append("    if (__ho != null) { var __cs2 = __ho.GetCompoundStructure();")
        L.append("      if (__cs2 != null) { foreach (var __ly in __cs2.GetLayers()) {")
        L.append("        var __mid = __ly.MaterialId;")
        L.append("        if (__mid != null && __mid != ElementId.InvalidElementId) {")
        L.append("          var __mat = doc.GetElement(__mid) as Material;")
        L.append(f"          if (__mat != null && __mat.Name != null && __mat.Name.ToLower().Contains({_mv})) {{ __hasMat = true; break; }}")
        L.append("        } } } }")
        L.append("    __ok = __hasMat;")
        L.append("  }")
    if level:
        applied.append(f"level={level}")
        _lv = _csstr(str(level).lower())
        L.append("  if (__ok) {")
        L.append("    string __lvlName = \"\";")
        L.append("    var __lp = __e.get_Parameter(BuiltInParameter.WALL_BASE_CONSTRAINT);")
        L.append("    if (__lp == null) __lp = __e.get_Parameter(BuiltInParameter.LEVEL_PARAM);")
        L.append("    if (__lp == null) __lp = __e.get_Parameter(BuiltInParameter.SCHEDULE_LEVEL_PARAM);")
        # F-percep-2 FIX: doors/windows/family instances carry their level on
        # FAMILY_LEVEL_PARAM (the line verbs.py:37 uses for inspect). Without it
        # «двери на этаже 03» resolved no level → confident zero.
        L.append("    if (__lp == null) __lp = __e.get_Parameter(BuiltInParameter.FAMILY_LEVEL_PARAM);")
        L.append("    if (__lp != null && __lp.HasValue) { var __le = doc.GetElement(__lp.AsElementId()) as Level; if (__le != null && __le.Name != null) __lvlName = __le.Name; }")
        # Last-resort fallback: Element.LevelId (set for many hosted elements that
        # expose no level parameter at all).
        L.append("    if (__lvlName == \"\") { try { var __lid = __e.LevelId; if (__lid != null && __lid != ElementId.InvalidElementId) { var __le2 = doc.GetElement(__lid) as Level; if (__le2 != null && __le2.Name != null) __lvlName = __le2.Name; } } catch {} }")
        L.append(f"    __ok = __lvlName.ToLower().Contains({_lv});")
        L.append("  }")
    L.append("  if (__ok) __m.Add(__e);")
    L.append("}")
    if isinstance(param, dict) and param.get("name") and ret != "coverage":
        L.append(f"if (__all.Count > 0 && __pFound == 0) __pskip.Add("
                 f"{_csstr('param.' + str(param.get('name')) + ' — параметр не найден ни у одного элемента (проверь имя)')});")

    # --- return shape ---
    L.append("__res[\"count\"] = __m.Count;")
    if ret == "ids":
        L.append("var __ids = new List<string>();")
        L.append(f"foreach (var __x in __m) {{ if (__ids.Count >= {limit}) break; __ids.Add(__x.Id.ToString()); }}")
        L.append("__res[\"ids\"] = __ids;")
        L.append(f"__res[\"ids_truncated\"] = (__m.Count > {limit});")
    if ret == "aggregate":
        # D4 FIX: HOST_AREA_COMPUTED / HOST_VOLUME_COMPUTED exist only for host
        # objects (walls/floors/roofs). Rooms/areas/spaces, doors, windows and
        # generic models have NO such param, so the old code summed nothing and
        # returned a silent `area_m2: 0.0` — indistinguishable from a real zero.
        # Now: fall back to the right per-category source (rooms/areas/spaces →
        # ROOM_AREA / ROOM_VOLUME), and when NO element in a non-empty set yields
        # the metric, return `null` + mark it `unsupported` instead of a fake 0.
        L.append("var __unsupported = new List<string>();")
        if "area_m2" in aggregate:
            L.append("double __area = 0; int __areaN = 0;")
            L.append("foreach (var __x in __m) {")
            L.append("  var __ap = __x.get_Parameter(BuiltInParameter.HOST_AREA_COMPUTED);")
            L.append("  if (__ap == null || !__ap.HasValue) __ap = __x.get_Parameter(BuiltInParameter.ROOM_AREA);")
            L.append("  if (__ap != null && __ap.HasValue) { __area += __ap.AsDouble() * 0.09290304; __areaN++; }")
            L.append("}")
            L.append("if (__m.Count > 0 && __areaN == 0) { __res[\"area_m2\"] = null; __unsupported.Add(\"area_m2\"); }")
            L.append("else { __res[\"area_m2\"] = Math.Round(__area, 2); }")
        if "volume_m3" in aggregate:
            L.append("double __vol = 0; int __volN = 0;")
            L.append("foreach (var __x in __m) {")
            L.append("  var __vp = __x.get_Parameter(BuiltInParameter.HOST_VOLUME_COMPUTED);")
            L.append("  if (__vp == null || !__vp.HasValue) __vp = __x.get_Parameter(BuiltInParameter.ROOM_VOLUME);")
            L.append("  if (__vp != null && __vp.HasValue) { __vol += __vp.AsDouble() * 0.028316846592; __volN++; }")
            L.append("}")
            L.append("if (__m.Count > 0 && __volN == 0) { __res[\"volume_m3\"] = null; __unsupported.Add(\"volume_m3\"); }")
            L.append("else { __res[\"volume_m3\"] = Math.Round(__vol, 3); }")
        L.append("__res[\"unsupported\"] = __unsupported;")
        L.append("foreach (var __u in __unsupported) __pskip.Add(\"aggregate.\" + __u + \" (category has no source param)\");")
    if ret == "table":
        L.append("var __rows = new List<Dictionary<string,object>>();")
        if order_by:
            L.append("var __sortv = new List<object>();")
        L.append("foreach (var __x in __m) {")
        L.append("  var __r = new Dictionary<string,object>();")
        for f in fields:
            L.extend("  " + ln for ln in _emit_table_field(f))
        L.append("  __rows.Add(__r);")
        if order_by:
            L.append(f"  __sortv.Add(__r.ContainsKey({_csstr(order_by)}) ? __r[{_csstr(order_by)}] : null);")
        else:
            # No ordering asked for ⇒ the first N matches are the answer; stop
            # walking a 200k-element model once we have them.
            L.append(f"  if (__rows.Count >= {limit}) break;")
        L.append("}")
        if order_by:
            # Nulls sort FIRST ascending, hence LAST descending — which is what
            # "top-5 by area" needs (a missing area must never win the podium).
            L.append("var __ord = new List<int>();")
            L.append("for (int __oi = 0; __oi < __rows.Count; __oi++) __ord.Add(__oi);")
            L.append("__ord.Sort((__a, __b) => {")
            L.append("  object __va = __sortv[__a]; object __vb = __sortv[__b];")
            L.append("  if (__va == null && __vb == null) return 0;")
            L.append("  if (__va == null) return -1;")
            L.append("  if (__vb == null) return 1;")
            L.append("  if ((__va is double) && (__vb is double)) return ((double)__va).CompareTo((double)__vb);")
            L.append("  return string.Compare(Convert.ToString(__va), Convert.ToString(__vb), StringComparison.OrdinalIgnoreCase);")
            L.append("});")
            if order_desc:
                L.append("__ord.Reverse();")
            L.append("var __out = new List<Dictionary<string,object>>();")
            L.append(f"foreach (var __oj in __ord) {{ if (__out.Count >= {limit}) break; __out.Add(__rows[__oj]); }}")
            L.append("__res[\"rows\"] = __out;")
            L.append("__res[\"truncated\"] = (__m.Count > __out.Count);")
        else:
            L.append("__res[\"rows\"] = __rows;")
            L.append("__res[\"truncated\"] = (__m.Count > __rows.Count);")
        L.append("__res[\"total\"] = __m.Count;")
        _fields_lit = ", ".join(_csstr(f) for f in fields)
        L.append(f"__res[\"fields\"] = new List<string>() {{ {_fields_lit} }};")

    if ret == "group":
        # group_by: type | level. Per-group aggregate: count ALWAYS; area_m2 /
        # volume_m3 folded PER GROUP only when EXPLICITLY requested (raw
        # spec.aggregate, not the defaulted list) — so the existing type+count
        # path stays byte-identical (flat {name: count}) while "площадь по
        # уровням" (group_by=level, aggregate=[area_m2]) returns nested
        # {name: {count, area_m2}}. Model reads JSON; no deterministic consumer
        # of query_model.groups exists (passport.groups is a different source).
        _raw_agg = spec.get("aggregate")
        _raw_agg = _raw_agg if isinstance(_raw_agg, list) else []
        _g_area = "area_m2" in _raw_agg
        _g_vol = "volume_m3" in _raw_agg
        _g_nested = _g_area or _g_vol
        L.append("var __g = new Dictionary<string,object>();")
        L.append("foreach (var __x in __m) {")
        if group_by == "level":
            # identical level-name resolution to the level filter above
            L.append("  string __k = \"(no level)\";")
            L.append("  { var __glp = __x.get_Parameter(BuiltInParameter.WALL_BASE_CONSTRAINT);")
            L.append("    if (__glp == null) __glp = __x.get_Parameter(BuiltInParameter.LEVEL_PARAM);")
            L.append("    if (__glp == null) __glp = __x.get_Parameter(BuiltInParameter.SCHEDULE_LEVEL_PARAM);")
            L.append("    if (__glp == null) __glp = __x.get_Parameter(BuiltInParameter.FAMILY_LEVEL_PARAM);")
            L.append("    if (__glp != null && __glp.HasValue) { var __gle = doc.GetElement(__glp.AsElementId()) as Level; if (__gle != null && __gle.Name != null) __k = __gle.Name; }")
            L.append("    if (__k == \"(no level)\") { try { var __glid = __x.LevelId; if (__glid != null && __glid != ElementId.InvalidElementId) { var __gle2 = doc.GetElement(__glid) as Level; if (__gle2 != null && __gle2.Name != null) __k = __gle2.Name; } } catch {} } }")
        else:
            L.append("  var __xt = doc.GetElement(__x.GetTypeId());")
            L.append("  string __k = (__xt != null && __xt.Name != null) ? __xt.Name : \"(no type)\";")
        if not _g_nested:
            L.append("  if (!__g.ContainsKey(__k)) __g[__k] = 0;")
            L.append("  __g[__k] = ((int)__g[__k]) + 1;")
        else:
            L.append("  Dictionary<string,object> __gd;")
            L.append("  if (__g.ContainsKey(__k)) __gd = (Dictionary<string,object>)__g[__k];")
            L.append("  else { __gd = new Dictionary<string,object>(); __gd[\"count\"] = 0;")
            if _g_area:
                L.append("         __gd[\"area_m2\"] = 0.0;")
            if _g_vol:
                L.append("         __gd[\"volume_m3\"] = 0.0;")
            L.append("         __g[__k] = __gd; }")
            L.append("  __gd[\"count\"] = ((int)__gd[\"count\"]) + 1;")
            if _g_area:
                L.append("  { var __gap = __x.get_Parameter(BuiltInParameter.HOST_AREA_COMPUTED);")
                L.append("    if (__gap == null || !__gap.HasValue) __gap = __x.get_Parameter(BuiltInParameter.ROOM_AREA);")
                L.append("    if (__gap != null && __gap.HasValue) __gd[\"area_m2\"] = ((double)__gd[\"area_m2\"]) + __gap.AsDouble() * 0.09290304; }")
            if _g_vol:
                L.append("  { var __gvp = __x.get_Parameter(BuiltInParameter.HOST_VOLUME_COMPUTED);")
                L.append("    if (__gvp == null || !__gvp.HasValue) __gvp = __x.get_Parameter(BuiltInParameter.ROOM_VOLUME);")
                L.append("    if (__gvp != null && __gvp.HasValue) __gd[\"volume_m3\"] = ((double)__gd[\"volume_m3\"]) + __gvp.AsDouble() * 0.028316846592; }")
        L.append("}")
        if _g_nested:
            L.append("foreach (var __gk in new List<string>(__g.Keys)) { var __gd = (Dictionary<string,object>)__g[__gk];")
            if _g_area:
                L.append("  __gd[\"area_m2\"] = Math.Round((double)__gd[\"area_m2\"], 2);")
            if _g_vol:
                L.append("  __gd[\"volume_m3\"] = Math.Round((double)__gd[\"volume_m3\"], 3);")
            L.append("}")
        L.append(f"__res[\"group_by\"] = {_csstr(group_by)};")
        L.append("__res[\"groups\"] = __g;")
    if ret == "coverage":
        # Mandatory-param coverage in ONE call (total/filled/empty/empty_ids) —
        # replaces the per-(category×param) call storm (s27). `param.name` is the
        # MEASURED parameter (its op is ignored in this mode).
        cn = _csstr(param.get("name"))
        L.append(f"string __cn = {cn};")
        L.append("int __filled = 0; var __empty = new List<string>();")
        L.append("foreach (var __x in __m) {")
        L.append("  Parameter __cp = __x.LookupParameter(__cn);")
        L.append("  string __cpv = (__cp!=null) ? (__cp.AsValueString() ?? (__cp.StorageType==StorageType.String?__cp.AsString():null)) : null;")
        L.append("  bool __cok = (__cp != null) && __cp.HasValue && !string.IsNullOrEmpty(__cpv);")
        L.append(f"  if (__cok) __filled++; else {{ if (__empty.Count < {limit}) __empty.Add(__x.Id.ToString()); }}")
        L.append("}")
        L.append("__res[\"total\"] = __m.Count;")
        L.append("__res[\"filled\"] = __filled;")
        L.append("__res[\"empty\"] = __m.Count - __filled;")
        L.append("__res[\"empty_ids\"] = __empty;")

    # --- disclosure: which predicates ran, which were skipped at runtime ---
    # Emitted into EVERY result dict so a zero is never naked (D-disclosure).
    # `predicates_applied` is the build-time list of compiled filters;
    # `predicates_skipped` is accumulated at runtime (unit unresolved, aggregate
    # metric unsupported, …).
    _applied_lit = ", ".join(_csstr(a) for a in applied)
    L.append(f"__res[\"predicates_applied\"] = new List<string>() {{ {_applied_lit} }};")
    L.append("__res[\"predicates_skipped\"] = __pskip;")

    # --- action (mutating view/selection only — needs a Transaction for view ops) ---
    if action == "select":
        L.append("if (uidoc != null) { uidoc.Selection.SetElementIds(__m.Select(x => x.Id).ToList()); __res[\"action\"] = \"selected\"; }")
    elif action == "isolate":
        # 2026-07-10 (operator): never isolate an EMPTY match set — Revit would
        # enter temporary isolate with nothing kept and the view "empties"
        # (guard mirrors kukai/llm/tool_handlers/revit_verbs.py hide_or_isolate).
        L.append("if (__m.Count > 0) { "
                 "using (var __t = new Transaction(doc, \"query_model isolate\")) { __t.Start(); "
                 "doc.ActiveView.IsolateElementsTemporary(__m.Select(x => x.Id).ToList()); __t.Commit(); } "
                 "__res[\"action\"] = \"isolated\"; } "
                 "else { __res[\"action\"] = \"isolate_skipped_empty\"; }")
    elif action == "highlight":
        L.append("using (var __t = new Transaction(doc, \"query_model highlight\")) { __t.Start(); "
                 "var __ogs = new OverrideGraphicSettings(); var __red = new Color(255, 0, 0); "
                 "__ogs.SetProjectionLineColor(__red); __ogs.SetSurfaceForegroundPatternColor(__red); "
                 "foreach (var __x in __m) doc.ActiveView.SetElementOverrides(__x.Id, __ogs); __t.Commit(); } "
                 "__res[\"action\"] = \"highlighted\";")

    L.append("return __res;")
    return "\n".join(L)
