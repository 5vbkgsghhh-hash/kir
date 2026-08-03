"""Family-editor tool handlers — V2/V3 architecture.

Each handler:
1. Validates structured args
2. Renders C# from a server-controlled template (verified-API only)
3. Dispatches via bridge_callback("execute", {"code": ..., "timeout_ms": ...})
4. Returns dict with {success, output|error, message}

API references encoded in templates come from
`docs/research/family_labeled_dim_api_2026-05.md` (Sonnet semantic audit V2) and
`docs/research/family_v3_api_spec_2026-05.md` (Sonnet semantic audit V3).

Critical V2 guards baked in:
- `if (!doc.IsFamilyDocument) return ...;` on every template
- `UnitUtils.ConvertToInternalUnits(value, UnitTypeId.Millimeters)` for all dims
- `GroupTypeId.Geometry` for Length params (= "Dimensions" UI group)
- `Dimension.FamilyLabel = familyParam` for labeled dim binding (correct property)
- `ReferencePlane.GetReference()` (METHOD not property)
- `doc.Regenerate()` between create-refs and NewDimension (2023+ regression fix)
- `mgr.CurrentType = target; mgr.RenameCurrentType(name)` (FamilyType.Name is read-only)
- Void extrusion (isSolid=false) auto-cuts in standard family templates
- `FamilyElementVisibility.IsShownInTopBottom` (NOT IsShownInPlan — doesn't exist)
- `doc.CombineElements(CombinableElementArray)` (NOT CombineWith — doesn't exist)

V3 additions:
- Unified profile_spec data structure: {outer_loop: [...], inner_loops: [[...], ...]}
  - segments support Line + Arc primitives (no splines — fall back to execute_revit_code)
  - multi-loop renders into CurveArrArray with outer first + inner loops as holes
  - full-circle arcs auto-split into two 180° arcs (Revit rejects full-circle in profile)
  - closed-loop validation (last endpoint == first startpoint within EPS_MM)
- sketch_plane spec: {origin_mm, normal} — supports inclined planes via Plane.XVec/YVec
- _render_* helpers emit local-2D-to-world XYZ via the plane's UV basis vectors.
"""
from __future__ import annotations

import json
import logging
import math
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger(__name__)

# Type alias — same shape as kukai.llm.client.BridgeCallback
BridgeCallback = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]

# Default execution timeout for family tools (ms). Geometry creation is fast.
_DEFAULT_TIMEOUT_MS = 30000
# Skeleton + composite ops can take a bit longer (regenerate + multiple ops)
_COMPOSITE_TIMEOUT_MS = 60000


# ─── Shared helpers ──────────────────────────────────────────────────────

async def _dispatch_code(
    code: str,
    bridge_callback: Optional[BridgeCallback],
    timeout_ms: int = _DEFAULT_TIMEOUT_MS,
) -> dict[str, Any]:
    """Send a code-block through the standard execute path."""
    if not bridge_callback:
        return {"error": True, "message": "Revit не подключён"}
    try:
        result = await bridge_callback(
            "execute", {"code": code, "timeout_ms": timeout_ms}
        )
        return result
    except Exception as exc:  # noqa: BLE001
        logger.exception("family-tool dispatch failed")
        return {"error": True, "message": f"Bridge error: {exc}"}


def _escape_cs_string(s: str) -> str:
    """Escape a Python string for embedding inside a C# verbatim string literal."""
    if s is None:
        return ""
    return s.replace("\\", "\\\\").replace('"', '\\"')


# ─── Diagnostic wrapper for FamilyCreate.NewExtrusion failures ──────────────
#
# Revit throws `Autodesk.Revit.Exceptions.InvalidOperationException("attempted
# operation is not permitted in this type of family")` when:
#   • the family template doesn't support extrusion creation (Annotation, Profile);
#   • the sketch plane is incompatible with the active view;
#   • the active view type doesn't permit geometry creation (rare);
#   • the family is loaded "in-place" (project context).
#
# Without diagnostic, Gemini just sees "operation not permitted" and falls back to
# DirectShape via execute_revit_code. With diagnostic, we return:
#   family_category (name + id), active_view_type, active_view_name,
#   sketch_plane_normal/origin (internal feet), extrusion_end (internal feet).
# Gemini can then either retry with a different sketch plane or pivot intelligently.
#
# Usage: emit DIAG_TRY_OPEN before NewExtrusion, DIAG_CATCH_CLOSE after the success
# return. The catch rolls back the transaction it's inside (no leaks).


def _diag_catch_block(operation_label: str, fallback_loop_var: str = "loop") -> str:
    """C# catch block: diagnostic + DirectShape rescue for FamilyCreate.NewExtrusion failures.

    Background (verified 2026-05-22 via prod trace):
        FamilyCreate.NewExtrusion throws Autodesk.Revit.Exceptions.InvalidOperationException
        "The attempted operation is not permitted in this type of family" whenever
        `doc.ActiveView.ViewType == ViewType.ThreeD`. Revit requires a 2D view
        (FloorPlan / CeilingPlan / Elevation) for native sketch-based geometry.

        Switching the active view from server-side is intrusive (would yank the user
        out of their working view). Instead we silently fall back to DirectShape via
        GeometryCreationUtilities.CreateExtrusionGeometry — works in any view
        including 3D and Mass, gives identical visual result. Trade-off: DirectShape
        is static (no EXTRUSION_START_PARAM / END_PARAM for parametric flex). The
        return payload sets `mode = "directshape"` so the model knows.

    Self-contained block. Closes preceding `try`, declares `catch`, performs rescue,
    closes catch.

    Variable contract expected in scope:
        • `tx` — the original Transaction (will be rolled back)
        • `planeGeom` — the original Plane (its Normal becomes extrusion direction)
        • `{fallback_loop_var}` — the original CurveArray (curves form the profile)
        • `depth` (advanced) OR computed via plane normal + thick/height — see helper

    NOTE on `.GetType()` — bridge-side `NamespaceValidator.cs:78` blocks ANY
    `GetType(` invocation. We use Revit's first-class `ViewType` enum + the
    fixed catch-type literal.
    """
    return f"""    }}
    catch (Autodesk.Revit.Exceptions.InvalidOperationException _ex_extr)
    {{
        try {{ tx.RollBack(); }} catch {{ }}
        Category _diag_cat = null;
        try {{ _diag_cat = doc.OwnerFamily?.FamilyCategory; }} catch {{ }}
        string _diag_catName = _diag_cat?.Name ?? "(unknown)";
        long _diag_catId = _diag_cat != null ? _diag_cat.Id.Value : -1L;
        string _diag_viewKind = "(none)";
        string _diag_viewName = "(none)";
        try {{
            var _diag_v = doc.ActiveView;
            if (_diag_v != null) {{ _diag_viewKind = _diag_v.ViewType.ToString(); _diag_viewName = _diag_v.Name; }}
        }} catch {{ }}

        // ─── DirectShape rescue ──────────────────────────────────────────
        // Reuse the in-memory CurveArray ({fallback_loop_var}) and Plane (planeGeom);
        // they're plain managed objects — survive the tx rollback. Build a CurveLoop
        // (modern API) and feed GeometryCreationUtilities + DirectShape.
        using (var _txFb = new Transaction(doc, "KUKI: {operation_label} (DirectShape fallback)"))
        {{
            try
            {{
                _txFb.Start();
                var _fbCurves = new System.Collections.Generic.List<Curve>();
                foreach (Curve _c in {fallback_loop_var}) _fbCurves.Add(_c);
                CurveLoop _fbLoop = CurveLoop.Create(_fbCurves);
                var _fbLoops = new System.Collections.Generic.List<CurveLoop> {{ _fbLoop }};

                // Extrusion direction = plane normal (already normalized).
                // Extrusion depth = derived from the original `end` arg of NewExtrusion:
                //   • family_extrude:  zOffset + thick → minus the plane's origin Z gives `thick`
                //   • family_cylinder: zOffset + height → ditto
                //   • family_extrude_advanced: depth directly
                // We use the local variable named `__fallbackDepth` declared inline.
                double __fallbackDepth = __fallback_depth_ft;
                if (__fallbackDepth <= 0) __fallbackDepth = 1.0;  // sanity floor

                Solid _fbSolid = GeometryCreationUtilities.CreateExtrusionGeometry(
                    _fbLoops, planeGeom.Normal, __fallbackDepth);

                // Family doc — use its own category for the DirectShape host.
                ElementId _fbCatId;
                try {{ _fbCatId = doc.OwnerFamily.FamilyCategory.Id; }}
                catch {{ _fbCatId = new ElementId((int)BuiltInCategory.OST_GenericModel); }}

                DirectShape _fbDs = DirectShape.CreateElement(doc, _fbCatId);
                _fbDs.SetShape(new GeometryObject[] {{ _fbSolid }});
                _txFb.Commit();
                return new {{
                    success = true,
                    id = _fbDs.Id.Value,
                    kind = "DirectShape",
                    mode = "directshape_fallback",
                    note = "FamilyCreate.NewExtrusion rejected in this view (likely 3D) — fell back to DirectShape. Geometry is static (no parametric flex).",
                    diagnostic = new {{
                        operation = "{operation_label}",
                        family_category = _diag_catName,
                        family_category_id = _diag_catId,
                        active_view_kind = _diag_viewKind,
                        active_view_name = _diag_viewName,
                        rejected_by = "FamilyCreate.NewExtrusion",
                    }}
                }};
            }}
            catch (Exception _ex_fb)
            {{
                try {{ _txFb.RollBack(); }} catch {{ }}
                return new {{
                    error = true,
                    message = "{operation_label} failed and DirectShape fallback also failed: " + _ex_extr.Message + " | fallback: " + _ex_fb.Message,
                    diagnostic = new {{
                        operation = "{operation_label}",
                        family_category = _diag_catName,
                        family_category_id = _diag_catId,
                        active_view_kind = _diag_viewKind,
                        active_view_name = _diag_viewName,
                        sketch_plane_normal = new double[] {{ planeGeom.Normal.X, planeGeom.Normal.Y, planeGeom.Normal.Z }},
                        sketch_plane_origin = new double[] {{ planeGeom.Origin.X, planeGeom.Origin.Y, planeGeom.Origin.Z }},
                        fallback_error_message = _ex_fb.Message,
                        error_type = "InvalidOperationException",
                    }}
                }};
            }}
        }}
    }}"""


def _serialise_param_values_cs(values: dict[str, Any]) -> str:
    """Render a Python dict of {paramName: mmValue|string} into a C# dictionary literal.

    Length values stay numeric (will be converted via UnitUtils on C# side); other
    primitives are emitted as their CLR-typed literal.
    """
    if not values:
        return "new Dictionary<string, object>()"
    parts = []
    for k, v in values.items():
        key_lit = f'"{_escape_cs_string(str(k))}"'
        if isinstance(v, bool):
            val_lit = "true" if v else "false"
        elif isinstance(v, (int, float)):
            val_lit = repr(float(v))
        else:
            val_lit = f'"{_escape_cs_string(str(v))}"'
        parts.append(f"{{ {key_lit}, {val_lit} }}")
    return "new Dictionary<string, object> { " + ", ".join(parts) + " }"


# ─── Layer 0: Inspection ─────────────────────────────────────────────────

async def inspect_family(
    args: dict[str, Any],
    bridge_callback: Optional[BridgeCallback],
) -> dict[str, Any]:
    """Read-only rich snapshot of the active family doc.

    Uses the dedicated `family_inspect` bridge method (not generic execute),
    which calls C# ContextCollector.CollectFamilyPassportAsJson().
    """
    if not bridge_callback:
        return {"error": True, "message": "Revit не подключён"}
    try:
        result = await bridge_callback("family_inspect", {})
        return {"success": True, "passport": result}
    except Exception as exc:  # noqa: BLE001
        logger.exception("inspect_family failed")
        return {"error": True, "message": f"Bridge error: {exc}"}


# ─── Layer 1: Skeleton tools ─────────────────────────────────────────────

# Standard ForgeTypeId.Group mapping (UI label → C# ForgeTypeId).
# CRITICAL: "Dimensions" in UI = GroupTypeId.Geometry (Sonnet research finding).
_GROUP_MAP = {
    "Dimensions": "GroupTypeId.Geometry",
    "Geometry": "GroupTypeId.Geometry",
    "Constraints": "GroupTypeId.Constraints",
    "Identity": "GroupTypeId.IdentityData",
    "IdentityData": "GroupTypeId.IdentityData",
    "Materials": "GroupTypeId.Materials",
    "Visibility": "GroupTypeId.Visibility",
    "Graphics": "GroupTypeId.Visibility",
    "Structural": "GroupTypeId.StructuralAnalysis",
    "Mechanical": "GroupTypeId.Mechanical",
    "Electrical": "GroupTypeId.Electrical",
}

_SPEC_MAP = {
    "Length": "SpecTypeId.Length",
    "Area": "SpecTypeId.Area",
    "Volume": "SpecTypeId.Volume",
    "Angle": "SpecTypeId.Angle",
    "Number": "SpecTypeId.Number",
    "Integer": "SpecTypeId.Int.Integer",
    "Boolean": "SpecTypeId.Boolean.YesNo",
    "YesNo": "SpecTypeId.Boolean.YesNo",
    "Text": "SpecTypeId.String.Text",
    "String": "SpecTypeId.String.Text",
    "Material": "SpecTypeId.Reference.Material",
}


async def family_add_parameter(
    args: dict[str, Any],
    bridge_callback: Optional[BridgeCallback],
) -> dict[str, Any]:
    """Add a FamilyParameter via FamilyManager.AddParameter (modern ForgeTypeId API).

    Idempotent — skips if parameter with same name already exists.
    """
    name = (args.get("name") or "").strip()
    if not name:
        return {"error": True, "message": "name is required"}
    spec_label = args.get("spec_type") or "Length"
    group_label = args.get("group") or "Dimensions"
    is_instance = bool(args.get("is_instance", False))

    spec_cs = _SPEC_MAP.get(spec_label, "SpecTypeId.Length")
    group_cs = _GROUP_MAP.get(group_label, "GroupTypeId.Geometry")

    code = f"""if (!doc.IsFamilyDocument) return new {{ error = "this code requires family editor" }};

using (var tx = new Transaction(doc, "KUKI: Add Family Parameter"))
{{
    tx.Start();
    FamilyManager mgr = doc.FamilyManager;
    string paramName = "{_escape_cs_string(name)}";

    // Idempotent — skip if exists
    FamilyParameter existing = mgr.get_Parameter(paramName);
    if (existing != null)
    {{
        tx.RollBack();
        return new {{ added = false, alreadyExists = true, name = paramName }};
    }}

    FamilyParameter fp = mgr.AddParameter(
        paramName,
        {group_cs},
        {spec_cs},
        {('true' if is_instance else 'false')});
    tx.Commit();
    return new {{ added = true, name = paramName, isInstance = {('true' if is_instance else 'false')} }};
}}"""
    return await _dispatch_code(code, bridge_callback)


async def family_new_type(
    args: dict[str, Any],
    bridge_callback: Optional[BridgeCallback],
) -> dict[str, Any]:
    """Create new FamilyType and set parameter values.

    `param_values` is a dict {paramName: valueMm|valueString}. Length-typed
    parameters are converted from mm to feet on the C# side.
    """
    name = (args.get("name") or "").strip()
    if not name:
        return {"error": True, "message": "name is required"}
    values = args.get("param_values") or {}
    if not isinstance(values, dict):
        return {"error": True, "message": "param_values must be an object"}

    values_cs = _serialise_param_values_cs(values)

    code = f"""if (!doc.IsFamilyDocument) return new {{ error = "this code requires family editor" }};

string newTypeName = "{_escape_cs_string(name)}";
var values = {values_cs};

using (var tx = new Transaction(doc, "KUKI: NewType + set params"))
{{
    tx.Start();
    FamilyManager mgr = doc.FamilyManager;

    FamilyType existing = null;
    foreach (FamilyType t in mgr.Types)
        if (t.Name == newTypeName) {{ existing = t; break; }}

    FamilyType targetType = existing ?? mgr.NewType(newTypeName);
    mgr.CurrentType = targetType;  // required before mgr.Set

    int set = 0, skipped = 0;
    foreach (var kv in values)
    {{
        FamilyParameter p = mgr.get_Parameter(kv.Key);
        if (p == null) {{ skipped++; continue; }}
        try {{
            object val = kv.Value;
            if (val is double dval)
            {{
                // Heuristic: if param is Length-typed, treat val as mm
                bool isLength = false;
                try {{ isLength = p.Definition.GetDataType().Equals(SpecTypeId.Length); }} catch {{ }}
                double internalVal = isLength
                    ? UnitUtils.ConvertToInternalUnits(dval, UnitTypeId.Millimeters)
                    : dval;
                mgr.Set(p, internalVal);
            }}
            else if (val is int ival) mgr.Set(p, ival);
            else if (val is string sval) mgr.Set(p, sval);
            else continue;
            set++;
        }} catch {{ skipped++; }}
    }}
    tx.Commit();
    return new {{ typeName = targetType.Name, paramsSet = set, paramsSkipped = skipped, alreadyExisted = (existing != null) }};
}}"""
    return await _dispatch_code(code, bridge_callback)


# ─── Layer 2: Geometry tools ─────────────────────────────────────────────


async def family_extrude(
    args: dict[str, Any],
    bridge_callback: Optional[BridgeCallback],
) -> dict[str, Any]:
    """Create a rectangular Extrusion in family editor (free-coordinate, not skeleton-bound).

    Args:
        width_mm, depth_mm: rectangle dimensions in mm (centered on local origin)
        thickness_mm: extrusion depth in mm
        z_offset_mm: bottom face of extrusion at this Z (default 0)
        subcategory: optional subcategory name to assign to the solid
    """
    try:
        width_mm = float(args.get("width_mm", 450))
        depth_mm = float(args.get("depth_mm", 450))
        thickness_mm = float(args.get("thickness_mm", 40))
        z_offset_mm = float(args.get("z_offset_mm", 0))
    except (TypeError, ValueError):
        return {"error": True, "message": "*_mm values must be numbers"}
    subcat = (args.get("subcategory") or "").strip()

    diag_catch = _diag_catch_block("family_extrude", fallback_loop_var="loop")
    code = f"""if (!doc.IsFamilyDocument) return new {{ error = "this code requires family editor" }};

double halfW   = UnitUtils.ConvertToInternalUnits({width_mm} / 2.0, UnitTypeId.Millimeters);
double halfD   = UnitUtils.ConvertToInternalUnits({depth_mm} / 2.0, UnitTypeId.Millimeters);
double thick   = UnitUtils.ConvertToInternalUnits({thickness_mm}, UnitTypeId.Millimeters);
double zOffset = UnitUtils.ConvertToInternalUnits({z_offset_mm}, UnitTypeId.Millimeters);
double __fallback_depth_ft = thick;

Plane planeGeom = Plane.CreateByNormalAndOrigin(XYZ.BasisZ, new XYZ(0, 0, zOffset));

// Hoisted so the catch (rescue path) can reference them after a tx rollback
CurveArray loop = new CurveArray();
loop.Append(Line.CreateBound(new XYZ(-halfW, -halfD, zOffset), new XYZ( halfW, -halfD, zOffset)));
loop.Append(Line.CreateBound(new XYZ( halfW, -halfD, zOffset), new XYZ( halfW,  halfD, zOffset)));
loop.Append(Line.CreateBound(new XYZ( halfW,  halfD, zOffset), new XYZ(-halfW,  halfD, zOffset)));
loop.Append(Line.CreateBound(new XYZ(-halfW,  halfD, zOffset), new XYZ(-halfW, -halfD, zOffset)));

using (var tx = new Transaction(doc, "KUKI: Extrude rectangle"))
{{
    tx.Start();
    try
    {{
        SketchPlane sp = SketchPlane.Create(doc, planeGeom);

        var profile = new CurveArrArray();
        profile.Append(loop);

        Extrusion ext = doc.FamilyCreate.NewExtrusion(true, profile, sp, zOffset + thick);

        string scName = "{_escape_cs_string(subcat)}";
        if (!string.IsNullOrEmpty(scName))
        {{
            try {{
                doc.Regenerate();  // ensure ext.Subcategory is queryable
                Category owner = doc.OwnerFamily?.FamilyCategory;
                if (owner != null)
                {{
                    Category sub = null;
                    foreach (Category c in owner.SubCategories) if (c.Name == scName) {{ sub = c; break; }}
                    if (sub == null) sub = doc.Settings.Categories.NewSubcategory(owner, scName);
                    ext.Subcategory = sub;
                }}
            }} catch {{ }}
        }}
        tx.Commit();
        return new {{ success = true, id = ext.Id.Value, kind = "Extrusion", mode = "extrusion", subcategory = scName }};
{diag_catch}
}}"""
    return await _dispatch_code(code, bridge_callback)


async def family_cylinder(
    args: dict[str, Any],
    bridge_callback: Optional[BridgeCallback],
) -> dict[str, Any]:
    """Cylinder extrusion (chair leg / post / column).

    Args:
        center_x_mm, center_y_mm: cylinder centre in family local coords (mm)
        radius_mm: cylinder radius (mm)
        height_mm: cylinder height (mm)
        z_offset_mm: base Z position (mm, default 0)
        subcategory: optional subcategory name
    """
    try:
        cx = float(args.get("center_x_mm", 0))
        cy = float(args.get("center_y_mm", 0))
        radius_mm = float(args.get("radius_mm", 15))
        height_mm = float(args.get("height_mm", 450))
        z_offset_mm = float(args.get("z_offset_mm", 0))
    except (TypeError, ValueError):
        return {"error": True, "message": "*_mm values must be numbers"}
    subcat = (args.get("subcategory") or "").strip()

    diag_catch = _diag_catch_block("family_cylinder", fallback_loop_var="loop")
    code = f"""if (!doc.IsFamilyDocument) return new {{ error = "this code requires family editor" }};

double cx       = UnitUtils.ConvertToInternalUnits({cx}, UnitTypeId.Millimeters);
double cy       = UnitUtils.ConvertToInternalUnits({cy}, UnitTypeId.Millimeters);
double radius   = UnitUtils.ConvertToInternalUnits({radius_mm}, UnitTypeId.Millimeters);
double height   = UnitUtils.ConvertToInternalUnits({height_mm}, UnitTypeId.Millimeters);
double zOffset  = UnitUtils.ConvertToInternalUnits({z_offset_mm}, UnitTypeId.Millimeters);
double __fallback_depth_ft = height;

Plane planeGeom = Plane.CreateByNormalAndOrigin(XYZ.BasisZ, new XYZ(cx, cy, zOffset));

// Hoisted so the catch (rescue path) can reference after rollback
XYZ centre = new XYZ(cx, cy, zOffset);
CurveArray loop = new CurveArray();
loop.Append(Arc.Create(centre, radius, 0,        Math.PI,     XYZ.BasisX, XYZ.BasisY));
loop.Append(Arc.Create(centre, radius, Math.PI,  2 * Math.PI, XYZ.BasisX, XYZ.BasisY));

using (var tx = new Transaction(doc, "KUKI: Extrude cylinder"))
{{
    tx.Start();
    try
    {{
        SketchPlane sp = SketchPlane.Create(doc, planeGeom);
        var profile = new CurveArrArray();
        profile.Append(loop);

        Extrusion ext = doc.FamilyCreate.NewExtrusion(true, profile, sp, zOffset + height);

        string scName = "{_escape_cs_string(subcat)}";
        if (!string.IsNullOrEmpty(scName))
        {{
            try {{
                doc.Regenerate();
                Category owner = doc.OwnerFamily?.FamilyCategory;
                if (owner != null)
                {{
                    Category sub = null;
                    foreach (Category c in owner.SubCategories) if (c.Name == scName) {{ sub = c; break; }}
                    if (sub == null) sub = doc.Settings.Categories.NewSubcategory(owner, scName);
                    ext.Subcategory = sub;
                }}
            }} catch {{ }}
        }}
        tx.Commit();
        return new {{ success = true, id = ext.Id.Value, kind = "Extrusion", mode = "extrusion", shape = "cylinder", subcategory = scName }};
{diag_catch}
}}"""
    return await _dispatch_code(code, bridge_callback)


async def family_void_cut(
    args: dict[str, Any],
    bridge_callback: Optional[BridgeCallback],
) -> dict[str, Any]:
    """Create a void extrusion that auto-cuts overlapping solids in standard
    family templates (Generic Model / Furniture / Door / Window / Casework).

    In Conceptual Mass families this would need explicit SolidSolidCutUtils,
    which we DO NOT call — V1 audit showed it throws in standard templates.

    Args: shape = "circle" | "rectangle", coords + size in mm.
    """
    shape = (args.get("shape") or "circle").lower()
    try:
        cx = float(args.get("center_x_mm", 0))
        cy = float(args.get("center_y_mm", 0))
        z_offset_mm = float(args.get("z_offset_mm", -50))
        depth_mm = float(args.get("depth_mm", 100))
    except (TypeError, ValueError):
        return {"error": True, "message": "*_mm values must be numbers"}

    if shape == "circle":
        try:
            radius_mm = float(args.get("radius_mm", 15))
        except (TypeError, ValueError):
            return {"error": True, "message": "radius_mm must be a number for circle"}
        profile_block = f"""    XYZ centre = new XYZ(cx, cy, zOffset);
    double radius = UnitUtils.ConvertToInternalUnits({radius_mm}, UnitTypeId.Millimeters);
    var loop = new CurveArray();
    loop.Append(Arc.Create(centre, radius, 0,        Math.PI,     XYZ.BasisX, XYZ.BasisY));
    loop.Append(Arc.Create(centre, radius, Math.PI,  2 * Math.PI, XYZ.BasisX, XYZ.BasisY));"""
    elif shape == "rectangle":
        try:
            width_mm = float(args.get("width_mm", 30))
            d_mm = float(args.get("depth_mm_xy", 30))
        except (TypeError, ValueError):
            return {"error": True, "message": "width_mm/depth_mm_xy must be numbers for rectangle"}
        profile_block = f"""    double halfW = UnitUtils.ConvertToInternalUnits({width_mm} / 2.0, UnitTypeId.Millimeters);
    double halfD = UnitUtils.ConvertToInternalUnits({d_mm} / 2.0, UnitTypeId.Millimeters);
    var loop = new CurveArray();
    loop.Append(Line.CreateBound(new XYZ(cx - halfW, cy - halfD, zOffset), new XYZ(cx + halfW, cy - halfD, zOffset)));
    loop.Append(Line.CreateBound(new XYZ(cx + halfW, cy - halfD, zOffset), new XYZ(cx + halfW, cy + halfD, zOffset)));
    loop.Append(Line.CreateBound(new XYZ(cx + halfW, cy + halfD, zOffset), new XYZ(cx - halfW, cy + halfD, zOffset)));
    loop.Append(Line.CreateBound(new XYZ(cx - halfW, cy + halfD, zOffset), new XYZ(cx - halfW, cy - halfD, zOffset)));"""
    else:
        return {"error": True, "message": "shape must be 'circle' or 'rectangle'"}

    code = f"""if (!doc.IsFamilyDocument) return new {{ error = "this code requires family editor" }};

double cx      = UnitUtils.ConvertToInternalUnits({cx}, UnitTypeId.Millimeters);
double cy      = UnitUtils.ConvertToInternalUnits({cy}, UnitTypeId.Millimeters);
double zOffset = UnitUtils.ConvertToInternalUnits({z_offset_mm}, UnitTypeId.Millimeters);
double depth   = UnitUtils.ConvertToInternalUnits({depth_mm}, UnitTypeId.Millimeters);

using (var tx = new Transaction(doc, "KUKI: Void cut"))
{{
    tx.Start();
    Plane planeGeom = Plane.CreateByNormalAndOrigin(XYZ.BasisZ, new XYZ(cx, cy, zOffset));
    SketchPlane sp = SketchPlane.Create(doc, planeGeom);

{profile_block}
    var profile = new CurveArrArray();
    profile.Append(loop);

    // isSolid=false  →  void extrusion. In standard family templates voids
    // auto-cut overlapping solids on doc.Regenerate(). DO NOT call
    // SolidSolidCutUtils — it only works in Conceptual Mass templates.
    Extrusion voidExt = doc.FamilyCreate.NewExtrusion(false, profile, sp, zOffset + depth);
    tx.Commit();
    doc.Regenerate();  // auto-cut takes effect on next regen
    return new {{ id = voidExt.Id.Value, kind = "VoidExtrusion", autoCut = true }};
}}"""
    return await _dispatch_code(code, bridge_callback)


# ─── Layer 3: Polish tools ───────────────────────────────────────────────


async def family_assign_material(
    args: dict[str, Any],
    bridge_callback: Optional[BridgeCallback],
) -> dict[str, Any]:
    """Assign a Material to family solids by name.

    Args:
        material_name: material to find by name (case-insensitive)
        target: "all" | subcategory name (filter solids by subcat)
    """
    material_name = (args.get("material_name") or "").strip()
    if not material_name:
        return {"error": True, "message": "material_name is required"}
    target = (args.get("target") or "all").strip()

    code = f"""if (!doc.IsFamilyDocument) return new {{ error = "this code requires family editor" }};

string materialName = "{_escape_cs_string(material_name)}";
string target       = "{_escape_cs_string(target)}";

Material mat = new FilteredElementCollector(doc)
    .OfClass(typeof(Material)).Cast<Material>()
    .FirstOrDefault(m => string.Equals(m.Name, materialName, StringComparison.OrdinalIgnoreCase));
if (mat == null) return new {{ error = "material '" + materialName + "' not found in family" }};

var solids = new FilteredElementCollector(doc)
    .OfClass(typeof(GenericForm)).Cast<GenericForm>()
    .Where(g => g.IsSolid)
    .Where(g => target == "all" || string.Equals((g.Subcategory?.Name ?? ""), target, StringComparison.OrdinalIgnoreCase))
    .ToList();

int assigned = 0;
using (var tx = new Transaction(doc, "KUKI: Assign material"))
{{
    tx.Start();
    foreach (var s in solids)
    {{
        Parameter mp = s.get_Parameter(BuiltInParameter.MATERIAL_ID_PARAM);
        if (mp != null && !mp.IsReadOnly)
        {{
            try {{ mp.Set(mat.Id); assigned++; }} catch {{ }}
        }}
    }}
    tx.Commit();
}}
return new {{ material = mat.Name, assigned = assigned, totalSolids = solids.Count }};"""
    return await _dispatch_code(code, bridge_callback)


async def family_create_subcategory(
    args: dict[str, Any],
    bridge_callback: Optional[BridgeCallback],
) -> dict[str, Any]:
    """Create a subcategory under the family's owner category."""
    name = (args.get("name") or "").strip()
    if not name:
        return {"error": True, "message": "name is required"}

    code = f"""if (!doc.IsFamilyDocument) return new {{ error = "this code requires family editor" }};

string scName = "{_escape_cs_string(name)}";
Category owner = doc.OwnerFamily?.FamilyCategory;
if (owner == null) return new {{ error = "no owner family category" }};

using (var tx = new Transaction(doc, "KUKI: NewSubcategory"))
{{
    tx.Start();
    Category sub = null;
    foreach (Category c in owner.SubCategories) if (c.Name == scName) {{ sub = c; break; }}
    if (sub == null) sub = doc.Settings.Categories.NewSubcategory(owner, scName);
    tx.Commit();
    return new {{ id = sub.Id.Value, name = sub.Name }};
}}"""
    return await _dispatch_code(code, bridge_callback)


async def family_set_visibility(
    args: dict[str, Any],
    bridge_callback: Optional[BridgeCallback],
) -> dict[str, Any]:
    """Set FamilyElementVisibility on a solid by element id.

    CRITICAL: uses IsShownInTopBottom (the correct property — IsShownInPlan
    does NOT exist; that was a V1 hallucination).
    """
    try:
        element_id = int(args.get("element_id", 0))
    except (TypeError, ValueError):
        return {"error": True, "message": "element_id must be an integer"}
    if element_id <= 0:
        return {"error": True, "message": "element_id is required"}

    in_plan = bool(args.get("in_plan", True))
    in_front_back = bool(args.get("in_front_back", True))
    in_left_right = bool(args.get("in_left_right", True))
    in_coarse = bool(args.get("in_coarse", True))
    in_medium = bool(args.get("in_medium", True))
    in_fine = bool(args.get("in_fine", True))

    def b(v):  # noqa: E306
        return "true" if v else "false"

    code = f"""if (!doc.IsFamilyDocument) return new {{ error = "this code requires family editor" }};

ElementId eid = new ElementId((long)({element_id}));
Element el = doc.GetElement(eid);
GenericForm target = el as GenericForm;
if (target == null) return new {{ error = "element " + {element_id} + " is not a GenericForm" }};

using (var tx = new Transaction(doc, "KUKI: Set visibility"))
{{
    tx.Start();
    var vis = new FamilyElementVisibility(FamilyElementVisibilityType.Model);
    vis.IsShownInTopBottom = {b(in_plan)};       // controls plan / RCP visibility
    vis.IsShownInFrontBack = {b(in_front_back)};
    vis.IsShownInLeftRight = {b(in_left_right)};
    vis.IsShownInCoarse    = {b(in_coarse)};
    vis.IsShownInMedium    = {b(in_medium)};
    vis.IsShownInFine      = {b(in_fine)};
    vis.IsShownOnlyWhenCut = false;
    target.SetVisibility(vis);
    tx.Commit();
    return new {{ id = {element_id}, visibility = "set" }};
}}"""
    return await _dispatch_code(code, bridge_callback)


# ─── Geometry primitives — arbitrary shapes ──────────────────────────────


def _curve_array_from_points_cs(var_name: str, points_mm: list[list[float]], z_mm: float = 0) -> str:
    """Render a Python list of 2D points into a C# CurveArray of closed-polygon lines.

    Profile is auto-closed (last point linked back to first). LEGACY helper —
    kept for backward compat with V2 handlers (family_extrude_polygon, family_revolve,
    family_blend, family_create_model_lines, family_create_symbolic_lines).
    V3 handlers use the richer `_render_curve_loop_cs` (Line + Arc + closed-validation).
    """
    if not points_mm or len(points_mm) < 3:
        raise ValueError("polygon profile needs >=3 points")
    lines = [f"    var {var_name} = new CurveArray();"]
    for i in range(len(points_mm)):
        p0 = points_mm[i]
        p1 = points_mm[(i + 1) % len(points_mm)]
        lines.append(
            f"    {var_name}.Append(Line.CreateBound("
            f"new XYZ(UnitUtils.ConvertToInternalUnits({p0[0]}, UnitTypeId.Millimeters), "
            f"UnitUtils.ConvertToInternalUnits({p0[1]}, UnitTypeId.Millimeters), "
            f"UnitUtils.ConvertToInternalUnits({z_mm}, UnitTypeId.Millimeters)), "
            f"new XYZ(UnitUtils.ConvertToInternalUnits({p1[0]}, UnitTypeId.Millimeters), "
            f"UnitUtils.ConvertToInternalUnits({p1[1]}, UnitTypeId.Millimeters), "
            f"UnitUtils.ConvertToInternalUnits({z_mm}, UnitTypeId.Millimeters))));"
        )
    return "\n".join(lines)


# ─── V3: Profile spec parser + curve renderer ────────────────────────────
#
# Profile spec shape (Python dict):
#
#     {
#       "outer_loop": [<segment>, <segment>, ...],   # closed CCW outer boundary
#       "inner_loops": [                              # optional list of holes (CW)
#           [<segment>, ...],
#           ...
#       ]
#     }
#
# Segment shapes:
#
#     {"type": "line", "p1": [x_mm, y_mm], "p2": [x_mm, y_mm]}
#     {"type": "arc",  "center": [cx_mm, cy_mm], "radius": r_mm,
#                       "start_deg": <deg>, "end_deg": <deg>}
#     {"type": "arc",  "p1": [x,y], "p2": [x,y], "p3": [x,y]}   # p2 on arc, 3-pt form
#
# All coords are LOCAL 2D in the sketch plane's UV frame, millimetres.
# The C# template converts via the plane's XVec/YVec basis at runtime, so
# inclined planes work transparently.

_EPS_MM = 1e-3  # 1 micrometre — endpoint-match tolerance for closed-loop check


def _arc_endpoints_mm(seg: dict[str, Any]) -> tuple[tuple[float, float], tuple[float, float]]:
    """Return (start_xy_mm, end_xy_mm) of an arc segment, in local 2D coords."""
    if "center" in seg:
        cx, cy = seg["center"]
        r = float(seg["radius"])
        a0 = math.radians(float(seg.get("start_deg", 0.0)))
        a1 = math.radians(float(seg.get("end_deg", 360.0)))
        return (
            (cx + r * math.cos(a0), cy + r * math.sin(a0)),
            (cx + r * math.cos(a1), cy + r * math.sin(a1)),
        )
    # 3-point form
    if "p1" in seg and "p3" in seg:
        return (tuple(seg["p1"]), tuple(seg["p3"]))
    raise ValueError("arc segment needs either {center, radius, start_deg, end_deg} or {p1, p2, p3}")


def _segment_endpoints_mm(seg: dict[str, Any]) -> tuple[tuple[float, float], tuple[float, float]]:
    """Return (start, end) of any segment in local 2D mm coords."""
    t = seg.get("type")
    if t == "line":
        return (tuple(seg["p1"]), tuple(seg["p2"]))
    if t == "arc":
        return _arc_endpoints_mm(seg)
    raise ValueError(f"unsupported segment type: {t!r}")


def _split_full_circles(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """If any arc segment spans ~360°, split it into two 180° halves.

    Revit rejects full-circle arcs inside a CurveLoop / CurveArrArray profile —
    the loop must be open at both ends so the next segment can bind to the start.
    """
    out: list[dict[str, Any]] = []
    for seg in segments:
        if seg.get("type") != "arc" or "center" not in seg:
            out.append(seg)
            continue
        a0 = float(seg.get("start_deg", 0.0))
        a1 = float(seg.get("end_deg", 360.0))
        span = abs(a1 - a0)
        if span >= 359.99:  # full circle within float tolerance
            mid = a0 + (a1 - a0) / 2.0
            half1 = dict(seg, start_deg=a0, end_deg=mid)
            half2 = dict(seg, start_deg=mid, end_deg=a1)
            out.extend([half1, half2])
        else:
            out.append(seg)
    return out


def _sample_points_mm(seg: dict[str, Any], n_samples: int = 5) -> list[tuple[float, float]]:
    """Approximate a segment as a polyline of `n_samples` 2D points (including endpoints).

    Used for shoelace-based signed-area computation of mixed line/arc loops.
    """
    t = seg.get("type")
    if t == "line":
        p1, p2 = seg["p1"], seg["p2"]
        pts = []
        for i in range(n_samples):
            tt = i / (n_samples - 1)
            pts.append((p1[0] + tt * (p2[0] - p1[0]), p1[1] + tt * (p2[1] - p1[1])))
        return pts
    if t == "arc":
        if "center" in seg:
            cx, cy = seg["center"]
            r = float(seg["radius"])
            a0 = math.radians(float(seg.get("start_deg", 0.0)))
            a1 = math.radians(float(seg.get("end_deg", 90.0)))
            pts = []
            for i in range(n_samples):
                tt = i / (n_samples - 1)
                angle = a0 + tt * (a1 - a0)
                pts.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
            return pts
        if "p1" in seg and "p3" in seg:
            # 3-point arc — for area sampling just use endpoints + the on-arc midpoint
            return [tuple(seg["p1"]), tuple(seg.get("p2", seg["p1"])), tuple(seg["p3"])]
    raise ValueError(f"unsupported segment type for sampling: {t!r}")


def _compute_loop_signed_area_mm2(segments: list[dict[str, Any]]) -> float:
    """Compute signed area of a closed 2D loop (mm²) using the shoelace formula.

    Sign convention (standard math, matches Revit's CurveLoop.IsCounterclockwise
    when viewed from the +normal direction in the sketch plane's UV frame):
        positive area  → CCW (counter-clockwise) → outer boundary
        negative area  → CW  (clockwise)         → inner hole

    Arcs are approximated with 5-point polylines, accurate enough to disambiguate
    the sign for any reasonable profile (arc bulge effects don't flip the sign).
    """
    pts: list[tuple[float, float]] = []
    for seg in segments:
        # Drop the duplicated startpoint between adjacent segments
        samp = _sample_points_mm(seg, n_samples=5)
        if pts and len(samp) > 0 and abs(samp[0][0] - pts[-1][0]) < _EPS_MM and abs(samp[0][1] - pts[-1][1]) < _EPS_MM:
            samp = samp[1:]
        pts.extend(samp)
    if len(pts) < 3:
        return 0.0
    # Shoelace
    area2 = 0.0
    for i in range(len(pts)):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % len(pts)]
        area2 += x0 * y1 - x1 * y0
    return 0.5 * area2


def _reverse_segment(seg: dict[str, Any]) -> dict[str, Any]:
    """Return a new segment with reversed direction (start↔end swapped).

    Lines: trivial — swap p1 and p2.
    Arcs by center/angles: convert to 3-point form (Arc.Create(end0, end1, pointOnArc))
        because Revit's Arc.Create(center, radius, startAngle, endAngle, ...) requires
        startAngle < endAngle. The 3-point form has no direction constraint, so we
        compute the midpoint of the original arc and emit (orig_end → orig_start) via
        (mid_point). This preserves geometry and reverses traversal.
    Arcs by 3 points: just swap p1 ↔ p3, p2 stays (it's on the arc, direction-agnostic).
    """
    t = seg.get("type")
    if t == "line":
        return {"type": "line", "p1": list(seg["p2"]), "p2": list(seg["p1"])}
    if t == "arc":
        if "center" in seg:
            cx, cy = seg["center"]
            r = float(seg["radius"])
            a0 = math.radians(float(seg.get("start_deg", 0.0)))
            a1 = math.radians(float(seg.get("end_deg", 360.0)))
            am = (a0 + a1) / 2.0  # midpoint of original arc (on the arc)
            return {
                "type": "arc",
                # 3-point form: reversed = (orig_end_pt, mid_pt, orig_start_pt)
                "p1": [cx + r * math.cos(a1), cy + r * math.sin(a1)],
                "p2": [cx + r * math.cos(am), cy + r * math.sin(am)],
                "p3": [cx + r * math.cos(a0), cy + r * math.sin(a0)],
            }
        if "p1" in seg and "p3" in seg:
            return {
                "type": "arc",
                "p1": list(seg["p3"]),
                "p2": list(seg.get("p2", [])),
                "p3": list(seg["p1"]),
            }
    raise ValueError(f"cannot reverse segment type {t!r}")


def _reverse_loop(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a new loop with all segments reversed in order AND direction.

    Going [A→B, B→C, C→A] (CCW) becomes [A→C, C→B, B→A] (CW after reversal).
    """
    return [_reverse_segment(s) for s in reversed(segments)]


def _ensure_winding(segments: list[dict[str, Any]], want_ccw: bool) -> list[dict[str, Any]]:
    """Auto-correct loop winding by reversing if it doesn't match want_ccw.

    Revit treats outer profile loops as CCW (positive signed area in plane UV
    frame) and inner holes as CW. Silent failure if winding is wrong — Sonnet
    research finding from IFC exporter source. Auto-correction prevents the
    silent-failure mode entirely.
    """
    if not segments:
        return segments
    area = _compute_loop_signed_area_mm2(segments)
    is_ccw = area > 0
    if is_ccw == want_ccw:
        return segments
    return _reverse_loop(segments)


def _validate_loop_closed(segments: list[dict[str, Any]]) -> None:
    """Raise ValueError unless segment chain forms a closed loop within EPS_MM."""
    if len(segments) < 2:
        # Single segment must itself be closed — only a full-circle arc qualifies,
        # but those get split upstream. So any 1-segment loop is invalid.
        raise ValueError("loop must have at least 2 segments after splitting full circles")
    # Each segment's end must match the next segment's start (chain)
    prev_end: Optional[tuple[float, float]] = None
    first_start: Optional[tuple[float, float]] = None
    for i, seg in enumerate(segments):
        s, e = _segment_endpoints_mm(seg)
        if first_start is None:
            first_start = s
        else:
            if math.hypot(s[0] - prev_end[0], s[1] - prev_end[1]) > _EPS_MM:
                raise ValueError(
                    f"segment {i} start {s} does not match previous end {prev_end} (gap > {_EPS_MM} mm)"
                )
        prev_end = e
    # Final segment end must match first segment start
    if math.hypot(prev_end[0] - first_start[0], prev_end[1] - first_start[1]) > _EPS_MM:
        raise ValueError(
            f"loop not closed: last endpoint {prev_end} != first startpoint {first_start} (gap > {_EPS_MM} mm)"
        )


def _f(value: float) -> str:
    """C# numeric literal — keeps full precision."""
    return repr(float(value))


def _render_local_xy_to_world_cs(plane_var: str, origin_var: str) -> str:
    """Render an inline local-helper that converts a local (u_mm, v_mm) into world XYZ.

    The plane's XVec / YVec give the basis vectors of the sketch plane in world coords.
    Local (u, v) mm convert to world: origin + XVec * u_ft + YVec * v_ft.
    """
    return (
        f"System.Func<double, double, XYZ> __toWorld = (uMm, vMm) => "
        f"{origin_var} + {plane_var}.XVec * UnitUtils.ConvertToInternalUnits(uMm, UnitTypeId.Millimeters) "
        f"+ {plane_var}.YVec * UnitUtils.ConvertToInternalUnits(vMm, UnitTypeId.Millimeters);"
    )


def _render_segment_cs(seg: dict[str, Any]) -> str:
    """Emit one C# curve constructor call. Assumes __toWorld lambda is in scope."""
    t = seg.get("type")
    if t == "line":
        p1, p2 = seg["p1"], seg["p2"]
        return (
            f"Line.CreateBound("
            f"__toWorld({_f(p1[0])}, {_f(p1[1])}), "
            f"__toWorld({_f(p2[0])}, {_f(p2[1])}))"
        )
    if t == "arc":
        if "center" in seg:
            cx, cy = seg["center"]
            r = float(seg["radius"])
            a0_rad = math.radians(float(seg.get("start_deg", 0.0)))
            a1_rad = math.radians(float(seg.get("end_deg", 90.0)))
            # Arc.Create(center, radius, startAngle, endAngle, xAxis, yAxis)
            # Pass radius in feet (via UnitUtils on C# side); xAxis=plane.XVec, yAxis=plane.YVec
            # IMPORTANT: when start/end angles are non-axis-aligned this gives an arc in
            # the sketch plane's UV frame, in world coords.
            return (
                f"Arc.Create("
                f"__toWorld({_f(cx)}, {_f(cy)}), "
                f"UnitUtils.ConvertToInternalUnits({_f(r)}, UnitTypeId.Millimeters), "
                f"{_f(a0_rad)}, {_f(a1_rad)}, "
                f"__planeXVec, __planeYVec)"
            )
        if "p1" in seg and "p2" in seg and "p3" in seg:
            p1, p2, p3 = seg["p1"], seg["p2"], seg["p3"]
            # 3-point arc: Arc.Create(end0, end1, pointOnArc) — p2 is the mid/point-on-arc
            return (
                f"Arc.Create("
                f"__toWorld({_f(p1[0])}, {_f(p1[1])}), "
                f"__toWorld({_f(p3[0])}, {_f(p3[1])}), "
                f"__toWorld({_f(p2[0])}, {_f(p2[1])}))"
            )
        raise ValueError("arc segment needs either {center, radius, start_deg, end_deg} or {p1, p2, p3}")
    raise ValueError(f"unsupported segment type: {t!r}")


def _render_curve_loop_cs(
    segments: list[dict[str, Any]],
    var_name: str,
    indent: str = "    ",
) -> str:
    """Render a list of segments as a C# CurveArray.

    Assumes `__toWorld`, `__planeXVec`, `__planeYVec` are in scope.
    Full-circle arcs are auto-split and the loop is closed-validated.
    """
    if not segments:
        raise ValueError("loop is empty")
    segs = _split_full_circles(list(segments))
    _validate_loop_closed(segs)
    out_lines = [f"{indent}var {var_name} = new CurveArray();"]
    for seg in segs:
        out_lines.append(f"{indent}{var_name}.Append({_render_segment_cs(seg)});")
    return "\n".join(out_lines)


def _render_curve_arr_array_cs(
    profile_spec: dict[str, Any],
    profile_var: str = "profile",
    indent: str = "    ",
) -> str:
    """Render a full profile_spec into a C# CurveArrArray.

    Output structure:
        var outerLoop = new CurveArray(); ...
        var innerLoop_0 = new CurveArray(); ...
        var profile = new CurveArrArray();
        profile.Append(outerLoop);
        profile.Append(innerLoop_0);

    First loop is the outer boundary; remaining loops are holes.
    **CRITICAL — winding order (Sonnet V3 research finding):**
    Revit silently fails on incorrect winding. We auto-correct in Python before
    emitting C# so the generated template is always winding-correct:
    - Outer loop: CCW (counter-clockwise viewed from +normal) → positive signed area
    - Inner loops (holes): CW → negative signed area

    Auto-correction reverses the segment order AND each segment's direction.
    """
    if not isinstance(profile_spec, dict):
        raise ValueError("profile_spec must be a dict with outer_loop + optional inner_loops")
    outer = profile_spec.get("outer_loop") or []
    inner_loops = profile_spec.get("inner_loops") or []
    if not outer:
        raise ValueError("profile_spec.outer_loop is required and must be non-empty")
    if not isinstance(inner_loops, list):
        raise ValueError("profile_spec.inner_loops must be a list of loops")

    # Auto-correct winding before rendering. Outer must be CCW (want_ccw=True),
    # each inner hole must be CW (want_ccw=False).
    outer_fixed = _ensure_winding(_split_full_circles(outer), want_ccw=True)
    inner_fixed = [
        _ensure_winding(_split_full_circles(loop), want_ccw=False)
        for loop in inner_loops
    ]

    parts = [_render_curve_loop_cs(outer_fixed, "outerLoop", indent=indent)]
    parts.append(f"{indent}var {profile_var} = new CurveArrArray();")
    parts.append(f"{indent}{profile_var}.Append(outerLoop);")
    for i, loop in enumerate(inner_fixed):
        var = f"innerLoop_{i}"
        parts.append(_render_curve_loop_cs(loop, var, indent=indent))
        parts.append(f"{indent}{profile_var}.Append({var});")
    return "\n".join(parts)


def _render_sketch_plane_cs(
    sketch_plane: Optional[dict[str, Any]],
    plane_var: str = "planeGeom",
    sp_var: str = "sp",
    origin_var: str = "__planeOrigin",
    indent: str = "    ",
) -> str:
    """Render a sketch_plane spec into a C# `Plane` + `SketchPlane` + helper bindings.

    Output declares:
        XYZ __planeOrigin = new XYZ(...);
        XYZ __planeNormal = new XYZ(...);
        Plane planeGeom = Plane.CreateByNormalAndOrigin(__planeNormal, __planeOrigin);
        XYZ __planeXVec = planeGeom.XVec;
        XYZ __planeYVec = planeGeom.YVec;
        System.Func<double,double,XYZ> __toWorld = (u, v) => ...;
        SketchPlane sp = SketchPlane.Create(doc, planeGeom);

    Default sketch_plane = XY at world origin (normal=Z, origin=0,0,0).
    """
    if sketch_plane is None:
        sketch_plane = {}
    origin = sketch_plane.get("origin_mm") or [0.0, 0.0, 0.0]
    normal = sketch_plane.get("normal") or [0.0, 0.0, 1.0]
    if len(origin) != 3:
        raise ValueError("sketch_plane.origin_mm must be [x,y,z] in mm")
    if len(normal) != 3:
        raise ValueError("sketch_plane.normal must be [nx,ny,nz]")
    # Sanity-normalise normal in Python (just to catch zero-vector early)
    nx, ny, nz = (float(v) for v in normal)
    mag = math.sqrt(nx * nx + ny * ny + nz * nz)
    if mag < 1e-9:
        raise ValueError("sketch_plane.normal must be non-zero")

    lines = [
        f"{indent}XYZ {origin_var} = new XYZ("
        f"UnitUtils.ConvertToInternalUnits({_f(origin[0])}, UnitTypeId.Millimeters), "
        f"UnitUtils.ConvertToInternalUnits({_f(origin[1])}, UnitTypeId.Millimeters), "
        f"UnitUtils.ConvertToInternalUnits({_f(origin[2])}, UnitTypeId.Millimeters));",
        f"{indent}XYZ __planeNormal = new XYZ({_f(nx)}, {_f(ny)}, {_f(nz)}).Normalize();",
        f"{indent}Plane {plane_var} = Plane.CreateByNormalAndOrigin(__planeNormal, {origin_var});",
        f"{indent}XYZ __planeXVec = {plane_var}.XVec;",
        f"{indent}XYZ __planeYVec = {plane_var}.YVec;",
        f"{indent}{_render_local_xy_to_world_cs(plane_var, origin_var)}",
        f"{indent}SketchPlane {sp_var} = SketchPlane.Create(doc, {plane_var});",
    ]
    return "\n".join(lines)


def _rectangle_profile_spec(width_mm: float, depth_mm: float) -> dict[str, Any]:
    """Build a profile_spec for a centered rectangle (Width × Depth, centered at 0,0)."""
    hw = width_mm / 2.0
    hd = depth_mm / 2.0
    return {
        "outer_loop": [
            {"type": "line", "p1": [-hw, -hd], "p2": [ hw, -hd]},
            {"type": "line", "p1": [ hw, -hd], "p2": [ hw,  hd]},
            {"type": "line", "p1": [ hw,  hd], "p2": [-hw,  hd]},
            {"type": "line", "p1": [-hw,  hd], "p2": [-hw, -hd]},
        ],
    }


def _circle_profile_spec(center_x_mm: float, center_y_mm: float, radius_mm: float) -> dict[str, Any]:
    """Build a profile_spec for a centered circle (split into two 180° arcs)."""
    return {
        "outer_loop": [
            {"type": "arc", "center": [center_x_mm, center_y_mm], "radius": radius_mm,
             "start_deg":   0.0, "end_deg": 180.0},
            {"type": "arc", "center": [center_x_mm, center_y_mm], "radius": radius_mm,
             "start_deg": 180.0, "end_deg": 360.0},
        ],
    }


def _ring_profile_spec(
    center_x_mm: float, center_y_mm: float, outer_r_mm: float, inner_r_mm: float
) -> dict[str, Any]:
    """Build a profile_spec for an annular ring (outer circle + inner hole)."""
    return {
        "outer_loop": [
            {"type": "arc", "center": [center_x_mm, center_y_mm], "radius": outer_r_mm,
             "start_deg":   0.0, "end_deg": 180.0},
            {"type": "arc", "center": [center_x_mm, center_y_mm], "radius": outer_r_mm,
             "start_deg": 180.0, "end_deg": 360.0},
        ],
        "inner_loops": [[
            {"type": "arc", "center": [center_x_mm, center_y_mm], "radius": inner_r_mm,
             "start_deg":   0.0, "end_deg": 180.0},
            {"type": "arc", "center": [center_x_mm, center_y_mm], "radius": inner_r_mm,
             "start_deg": 180.0, "end_deg": 360.0},
        ]],
    }


async def family_extrude_polygon(
    args: dict[str, Any],
    bridge_callback: Optional[BridgeCallback],
) -> dict[str, Any]:
    """Extrude an ARBITRARY 2D polygon profile (any number of vertices, any shape).

    Args:
        points_mm: list of [x_mm, y_mm] vertices. Min 3 points. Auto-closed.
        depth_mm: extrusion depth (Z)
        z_offset_mm: bottom face Z (default 0)
        is_solid: true=solid, false=void (auto-cuts)
        subcategory: optional subcategory name
    """
    points = args.get("points_mm") or []
    if not isinstance(points, list) or len(points) < 3:
        return {"error": True, "message": "points_mm must be a list of >=3 [x,y] pairs"}
    try:
        depth_mm = float(args.get("depth_mm", 100))
        z_offset_mm = float(args.get("z_offset_mm", 0))
    except (TypeError, ValueError):
        return {"error": True, "message": "depth_mm / z_offset_mm must be numbers"}
    is_solid = bool(args.get("is_solid", True))
    subcat = (args.get("subcategory") or "").strip()
    is_solid_cs = "true" if is_solid else "false"

    try:
        loop_cs = _curve_array_from_points_cs("loop", points, z_offset_mm)
    except ValueError as e:
        return {"error": True, "message": str(e)}

    code = f"""if (!doc.IsFamilyDocument) return new {{ error = "this code requires family editor" }};

double depth   = UnitUtils.ConvertToInternalUnits({depth_mm}, UnitTypeId.Millimeters);
double zOffset = UnitUtils.ConvertToInternalUnits({z_offset_mm}, UnitTypeId.Millimeters);

using (var tx = new Transaction(doc, "KUKI: Extrude polygon"))
{{
    tx.Start();
    Plane planeGeom = Plane.CreateByNormalAndOrigin(XYZ.BasisZ, new XYZ(0, 0, zOffset));
    SketchPlane sp = SketchPlane.Create(doc, planeGeom);

{loop_cs}
    var profile = new CurveArrArray();
    profile.Append(loop);

    Extrusion ext = doc.FamilyCreate.NewExtrusion({is_solid_cs}, profile, sp, zOffset + depth);

    string scName = "{_escape_cs_string(subcat)}";
    if (!string.IsNullOrEmpty(scName) && {is_solid_cs})
    {{
        try {{
            doc.Regenerate();
            Category owner = doc.OwnerFamily?.FamilyCategory;
            if (owner != null)
            {{
                Category sub = null;
                foreach (Category c in owner.SubCategories) if (c.Name == scName) {{ sub = c; break; }}
                if (sub == null) sub = doc.Settings.Categories.NewSubcategory(owner, scName);
                ext.Subcategory = sub;
            }}
        }} catch {{ }}
    }}
    tx.Commit();
    return new {{ id = ext.Id.Value, kind = "Extrusion", isSolid = {is_solid_cs}, pointCount = {len(points)} }};
}}"""
    return await _dispatch_code(code, bridge_callback)


async def family_blend(
    args: dict[str, Any],
    bridge_callback: Optional[BridgeCallback],
) -> dict[str, Any]:
    """Blend solid — different top and bottom polygon profiles at different Z heights.

    For tapered/morphed shapes: lamp shade, conical leg, prism transitions.
    Both profiles are arbitrary polygons.

    Args:
        bottom_points_mm: [[x,y], ...] for bottom profile
        top_points_mm: [[x,y], ...] for top profile (must have same #points as bottom)
        bottom_z_mm: Z of bottom profile (default 0)
        top_z_mm: Z of top profile (default 300)
        is_solid: true=solid, false=void
    """
    bottom = args.get("bottom_points_mm") or []
    top = args.get("top_points_mm") or []
    if len(bottom) < 3 or len(top) < 3:
        return {"error": True, "message": "both profiles need >=3 points"}
    try:
        bottom_z = float(args.get("bottom_z_mm", 0))
        top_z = float(args.get("top_z_mm", 300))
    except (TypeError, ValueError):
        return {"error": True, "message": "bottom_z_mm / top_z_mm must be numbers"}
    is_solid_cs = "true" if bool(args.get("is_solid", True)) else "false"

    bottom_cs = _curve_array_from_points_cs("bottomLoop", bottom, bottom_z)
    top_cs = _curve_array_from_points_cs("topLoop", top, top_z)

    code = f"""if (!doc.IsFamilyDocument) return new {{ error = "this code requires family editor" }};

using (var tx = new Transaction(doc, "KUKI: Blend"))
{{
    tx.Start();
    Plane planeGeom = Plane.CreateByNormalAndOrigin(XYZ.BasisZ, new XYZ(0, 0, 0));
    SketchPlane sp = SketchPlane.Create(doc, planeGeom);

{bottom_cs}

{top_cs}

    Blend blend = doc.FamilyCreate.NewBlend({is_solid_cs}, topLoop, bottomLoop, sp);
    tx.Commit();
    return new {{ id = blend.Id.Value, kind = "Blend" }};
}}"""
    return await _dispatch_code(code, bridge_callback)


async def family_revolve(
    args: dict[str, Any],
    bridge_callback: Optional[BridgeCallback],
) -> dict[str, Any]:
    """Revolution solid — rotate a 2D profile around an axis (vase, bowl, dome, sphere).

    Args:
        profile_points_mm: 2D points in the XZ plane (Y=0). Profile MUST be closed
            and include the axis-edge segment (when axis is Z, an edge along x=0).
        axis_start_mm, axis_end_mm: [x,y,z] endpoints of the rotation axis line
        start_angle_rad: 0 by default (in radians)
        end_angle_rad: 2*PI by default (full revolution)
    """
    profile_pts = args.get("profile_points_mm") or []
    if len(profile_pts) < 3:
        return {"error": True, "message": "profile needs >=3 points (closed loop including axis edge)"}
    axis_start = args.get("axis_start_mm") or [0, 0, 0]
    axis_end = args.get("axis_end_mm") or [0, 0, 500]
    if len(axis_start) != 3 or len(axis_end) != 3:
        return {"error": True, "message": "axis_start_mm / axis_end_mm must be [x,y,z]"}
    try:
        start_angle = float(args.get("start_angle_rad", 0.0))
        end_angle = float(args.get("end_angle_rad", 6.283185307179586))
    except (TypeError, ValueError):
        return {"error": True, "message": "angles must be numbers (radians)"}
    is_solid_cs = "true" if bool(args.get("is_solid", True)) else "false"

    # Profile is in XZ plane; use Y as ignored (always 0).
    profile_lines = ["    var profile = new CurveArray();"]
    for i in range(len(profile_pts)):
        p0 = profile_pts[i]
        p1 = profile_pts[(i + 1) % len(profile_pts)]
        profile_lines.append(
            f"    profile.Append(Line.CreateBound("
            f"new XYZ(UnitUtils.ConvertToInternalUnits({p0[0]}, UnitTypeId.Millimeters), 0, "
            f"UnitUtils.ConvertToInternalUnits({p0[1]}, UnitTypeId.Millimeters)), "
            f"new XYZ(UnitUtils.ConvertToInternalUnits({p1[0]}, UnitTypeId.Millimeters), 0, "
            f"UnitUtils.ConvertToInternalUnits({p1[1]}, UnitTypeId.Millimeters))));"
        )
    profile_cs = "\n".join(profile_lines)

    code = f"""if (!doc.IsFamilyDocument) return new {{ error = "this code requires family editor" }};

using (var tx = new Transaction(doc, "KUKI: Revolve"))
{{
    tx.Start();
    // Sketch plane = XZ plane (normal=BasisY)
    Plane planeGeom = Plane.CreateByNormalAndOrigin(XYZ.BasisY, XYZ.Zero);
    SketchPlane sp = SketchPlane.Create(doc, planeGeom);

{profile_cs}
    var profiles = new CurveArrArray();
    profiles.Append(profile);

    Line axis = Line.CreateBound(
        new XYZ(
            UnitUtils.ConvertToInternalUnits({axis_start[0]}, UnitTypeId.Millimeters),
            UnitUtils.ConvertToInternalUnits({axis_start[1]}, UnitTypeId.Millimeters),
            UnitUtils.ConvertToInternalUnits({axis_start[2]}, UnitTypeId.Millimeters)),
        new XYZ(
            UnitUtils.ConvertToInternalUnits({axis_end[0]}, UnitTypeId.Millimeters),
            UnitUtils.ConvertToInternalUnits({axis_end[1]}, UnitTypeId.Millimeters),
            UnitUtils.ConvertToInternalUnits({axis_end[2]}, UnitTypeId.Millimeters)));

    Revolution rev = doc.FamilyCreate.NewRevolution({is_solid_cs}, profiles, sp, axis, {start_angle}, {end_angle});
    tx.Commit();
    return new {{ id = rev.Id.Value, kind = "Revolution" }};
}}"""
    return await _dispatch_code(code, bridge_callback)


# ─── Geometry modification ───────────────────────────────────────────────


async def family_delete_element(
    args: dict[str, Any],
    bridge_callback: Optional[BridgeCallback],
) -> dict[str, Any]:
    """Delete a family element by ElementId."""
    try:
        eid = int(args.get("element_id", 0))
    except (TypeError, ValueError):
        return {"error": True, "message": "element_id must be integer"}
    if eid <= 0:
        return {"error": True, "message": "element_id required"}

    code = f"""if (!doc.IsFamilyDocument) return new {{ error = "this code requires family editor" }};

ElementId eid = new ElementId((long)({eid}));
Element el = doc.GetElement(eid);
if (el == null) return new {{ error = "element not found: " + {eid} }};

using (var tx = new Transaction(doc, "KUKI: Delete element"))
{{
    tx.Start();
    try {{
        doc.Delete(eid);
        tx.Commit();
        return new {{ deleted = (long){eid} }};
    }} catch (Exception ex) {{
        tx.RollBack();
        return new {{ error = "delete failed: " + ex.Message }};
    }}
}}"""
    return await _dispatch_code(code, bridge_callback)


async def family_move_element(
    args: dict[str, Any],
    bridge_callback: Optional[BridgeCallback],
) -> dict[str, Any]:
    """Translate an element by [dx, dy, dz] in mm."""
    try:
        eid = int(args.get("element_id", 0))
        dx = float(args.get("dx_mm", 0))
        dy = float(args.get("dy_mm", 0))
        dz = float(args.get("dz_mm", 0))
    except (TypeError, ValueError):
        return {"error": True, "message": "element_id required (int); dx/dy/dz must be numbers"}
    if eid <= 0:
        return {"error": True, "message": "element_id required"}

    code = f"""if (!doc.IsFamilyDocument) return new {{ error = "this code requires family editor" }};

ElementId eid = new ElementId((long)({eid}));
Element el = doc.GetElement(eid);
if (el == null) return new {{ error = "element not found: " + {eid} }};

double dxFt = UnitUtils.ConvertToInternalUnits({dx}, UnitTypeId.Millimeters);
double dyFt = UnitUtils.ConvertToInternalUnits({dy}, UnitTypeId.Millimeters);
double dzFt = UnitUtils.ConvertToInternalUnits({dz}, UnitTypeId.Millimeters);
XYZ translation = new XYZ(dxFt, dyFt, dzFt);

using (var tx = new Transaction(doc, "KUKI: Move element"))
{{
    tx.Start();
    try {{
        ElementTransformUtils.MoveElement(doc, eid, translation);
        tx.Commit();
        return new {{ moved = (long){eid}, dx_mm = {dx}, dy_mm = {dy}, dz_mm = {dz} }};
    }} catch (Exception ex) {{
        tx.RollBack();
        return new {{ error = "move failed: " + ex.Message }};
    }}
}}"""
    return await _dispatch_code(code, bridge_callback)


# ─── References & constraints — parametric flex primitives ───────────────


async def family_create_reference_plane(
    args: dict[str, Any],
    bridge_callback: Optional[BridgeCallback],
) -> dict[str, Any]:
    """Create a single named ReferencePlane (the building block for skeleton).

    Args:
        bubble_mm: [x,y,z] for the bubble end
        free_mm: [x,y,z] for the free end
        cut_dir: [x,y,z] cut vector (third basis of plane)
        name: optional name for the ref plane
    """
    bubble = args.get("bubble_mm") or [0, 0, 0]
    free = args.get("free_mm") or [1000, 0, 0]
    cut = args.get("cut_dir") or [0, 0, 1]
    if len(bubble) != 3 or len(free) != 3 or len(cut) != 3:
        return {"error": True, "message": "bubble_mm / free_mm / cut_dir must be [x,y,z]"}
    name = (args.get("name") or "").strip()

    code = f"""if (!doc.IsFamilyDocument) return new {{ error = "this code requires family editor" }};

View activeView = doc.ActiveView;
if (activeView == null) return new {{ error = "no active view" }};

XYZ bubble = new XYZ(
    UnitUtils.ConvertToInternalUnits({bubble[0]}, UnitTypeId.Millimeters),
    UnitUtils.ConvertToInternalUnits({bubble[1]}, UnitTypeId.Millimeters),
    UnitUtils.ConvertToInternalUnits({bubble[2]}, UnitTypeId.Millimeters));
XYZ freeEnd = new XYZ(
    UnitUtils.ConvertToInternalUnits({free[0]}, UnitTypeId.Millimeters),
    UnitUtils.ConvertToInternalUnits({free[1]}, UnitTypeId.Millimeters),
    UnitUtils.ConvertToInternalUnits({free[2]}, UnitTypeId.Millimeters));
XYZ cutDir = new XYZ({cut[0]}, {cut[1]}, {cut[2]});

using (var tx = new Transaction(doc, "KUKI: NewReferencePlane"))
{{
    tx.Start();
    ReferencePlane rp = doc.FamilyCreate.NewReferencePlane(bubble, freeEnd, cutDir, activeView);
    string newName = "{_escape_cs_string(name)}";
    if (!string.IsNullOrEmpty(newName)) {{
        try {{ rp.Name = newName; }} catch {{ }}
    }}
    tx.Commit();
    return new {{ id = rp.Id.Value, name = rp.Name }};
}}"""
    return await _dispatch_code(code, bridge_callback)


async def family_regenerate(
    args: dict[str, Any],
    bridge_callback: Optional[BridgeCallback],
) -> dict[str, Any]:
    """Force doc.Regenerate(). Required between creating ref planes and dimensioning them
    in Revit 2023+ (regression fix). Call this between steps when composing parametric skeletons.
    """
    code = """if (!doc.IsFamilyDocument) return new { error = "this code requires family editor" };
doc.Regenerate();
return new { regenerated = true };"""
    return await _dispatch_code(code, bridge_callback)


async def family_create_dimension(
    args: dict[str, Any],
    bridge_callback: Optional[BridgeCallback],
) -> dict[str, Any]:
    """Create a labeled Dimension between two ReferencePlanes (by id) and bind to a FamilyParameter.

    Args:
        ref_plane_id_a, ref_plane_id_b: ElementId.Value of the two reference planes
        dim_line_p1_mm, dim_line_p2_mm: [x,y,z] dimension line endpoints (must be coplanar with view)
        family_param_name: name of the existing FamilyParameter to bind (must already exist)
    """
    try:
        ref_a = int(args.get("ref_plane_id_a", 0))
        ref_b = int(args.get("ref_plane_id_b", 0))
    except (TypeError, ValueError):
        return {"error": True, "message": "ref_plane_id_a / ref_plane_id_b must be integers"}
    if ref_a <= 0 or ref_b <= 0:
        return {"error": True, "message": "both ref_plane_id_a and ref_plane_id_b required"}
    p1 = args.get("dim_line_p1_mm") or [0, 0, 0]
    p2 = args.get("dim_line_p2_mm") or [1000, 0, 0]
    if len(p1) != 3 or len(p2) != 3:
        return {"error": True, "message": "dim_line points must be [x,y,z]"}
    param = (args.get("family_param_name") or "").strip()

    code = f"""if (!doc.IsFamilyDocument) return new {{ error = "this code requires family editor" }};

View activeView = doc.ActiveView;
if (activeView == null) return new {{ error = "no active view" }};

Element elA = doc.GetElement(new ElementId((long)({ref_a})));
Element elB = doc.GetElement(new ElementId((long)({ref_b})));
ReferencePlane rpA = elA as ReferencePlane;
ReferencePlane rpB = elB as ReferencePlane;
if (rpA == null || rpB == null) return new {{ error = "ref_plane_id_a or _b is not a ReferencePlane" }};

string paramName = "{_escape_cs_string(param)}";
FamilyParameter fp = null;
if (!string.IsNullOrEmpty(paramName))
{{
    fp = doc.FamilyManager.get_Parameter(paramName);
    if (fp == null) return new {{ error = "FamilyParameter '" + paramName + "' not found (create it first via family_add_parameter)" }};
}}

using (var tx = new Transaction(doc, "KUKI: Create labeled dimension"))
{{
    tx.Start();
    ReferenceArray refs = new ReferenceArray();
    refs.Append(rpA.GetReference());
    refs.Append(rpB.GetReference());

    Line dimLine = Line.CreateBound(
        new XYZ(
            UnitUtils.ConvertToInternalUnits({p1[0]}, UnitTypeId.Millimeters),
            UnitUtils.ConvertToInternalUnits({p1[1]}, UnitTypeId.Millimeters),
            UnitUtils.ConvertToInternalUnits({p1[2]}, UnitTypeId.Millimeters)),
        new XYZ(
            UnitUtils.ConvertToInternalUnits({p2[0]}, UnitTypeId.Millimeters),
            UnitUtils.ConvertToInternalUnits({p2[1]}, UnitTypeId.Millimeters),
            UnitUtils.ConvertToInternalUnits({p2[2]}, UnitTypeId.Millimeters)));

    Dimension dim;
    try {{
        dim = doc.FamilyCreate.NewDimension(activeView, dimLine, refs);
    }} catch (Exception ex) {{
        tx.RollBack();
        return new {{ error = "NewDimension failed (try family_regenerate() before this): " + ex.Message }};
    }}
    if (fp != null)
    {{
        try {{ dim.FamilyLabel = fp; }} catch (Exception ex) {{ tx.RollBack(); return new {{ error = "FamilyLabel binding failed: " + ex.Message }}; }}
    }}
    tx.Commit();
    return new {{ id = dim.Id.Value, linkedParam = (fp != null ? fp.Definition.Name : "") }};
}}"""
    return await _dispatch_code(code, bridge_callback)


async def family_set_parameter_value(
    args: dict[str, Any],
    bridge_callback: Optional[BridgeCallback],
) -> dict[str, Any]:
    """Set a single FamilyParameter value on the CURRENT type.

    For length parameters, value is in mm. For other types, pass the raw value.
    """
    name = (args.get("param_name") or "").strip()
    if not name:
        return {"error": True, "message": "param_name required"}
    value = args.get("value")
    if value is None:
        return {"error": True, "message": "value required"}

    if isinstance(value, bool):
        value_cs = "true" if value else "false"
        value_kind = "bool"
    elif isinstance(value, (int, float)):
        value_cs = repr(float(value))
        value_kind = "double"
    else:
        value_cs = f'"{_escape_cs_string(str(value))}"'
        value_kind = "string"

    code = f"""if (!doc.IsFamilyDocument) return new {{ error = "this code requires family editor" }};

string pname = "{_escape_cs_string(name)}";
FamilyManager mgr = doc.FamilyManager;
FamilyParameter p = mgr.get_Parameter(pname);
if (p == null) return new {{ error = "FamilyParameter '" + pname + "' not found" }};

using (var tx = new Transaction(doc, "KUKI: Set parameter value"))
{{
    tx.Start();
    try {{
        switch ("{value_kind}")
        {{
            case "double":
                bool isLength = false;
                try {{ isLength = p.Definition.GetDataType().Equals(SpecTypeId.Length); }} catch {{ }}
                double internalVal = isLength
                    ? UnitUtils.ConvertToInternalUnits((double)({value_cs}), UnitTypeId.Millimeters)
                    : (double)({value_cs});
                mgr.Set(p, internalVal);
                break;
            case "bool":
                mgr.Set(p, ({value_cs}) ? 1 : 0);
                break;
            case "string":
                mgr.Set(p, {value_cs});
                break;
        }}
        tx.Commit();
        return new {{ param = pname, success = true }};
    }} catch (Exception ex) {{
        tx.RollBack();
        return new {{ error = "set failed: " + ex.Message }};
    }}
}}"""
    return await _dispatch_code(code, bridge_callback)


async def family_create_model_lines(
    args: dict[str, Any],
    bridge_callback: Optional[BridgeCallback],
) -> dict[str, Any]:
    """Create 3D model lines (visible in all view types).

    Args:
        lines_mm: list of [[x1,y1,z1], [x2,y2,z2]] segments
        sketch_plane_normal: [nx, ny, nz] (default [0,0,1])
        sketch_plane_origin_mm: [x,y,z] (default [0,0,0])
    """
    lines = args.get("lines_mm") or []
    if not isinstance(lines, list) or not lines:
        return {"error": True, "message": "lines_mm must be non-empty list of segments"}
    for seg in lines:
        if len(seg) != 2 or len(seg[0]) != 3 or len(seg[1]) != 3:
            return {"error": True, "message": "each segment must be [[x1,y1,z1], [x2,y2,z2]]"}
    normal = args.get("sketch_plane_normal") or [0, 0, 1]
    origin = args.get("sketch_plane_origin_mm") or [0, 0, 0]

    line_appends = []
    for seg in lines:
        p1, p2 = seg
        line_appends.append(
            f"    curves.Append(Line.CreateBound("
            f"new XYZ(UnitUtils.ConvertToInternalUnits({p1[0]}, UnitTypeId.Millimeters), "
            f"UnitUtils.ConvertToInternalUnits({p1[1]}, UnitTypeId.Millimeters), "
            f"UnitUtils.ConvertToInternalUnits({p1[2]}, UnitTypeId.Millimeters)), "
            f"new XYZ(UnitUtils.ConvertToInternalUnits({p2[0]}, UnitTypeId.Millimeters), "
            f"UnitUtils.ConvertToInternalUnits({p2[1]}, UnitTypeId.Millimeters), "
            f"UnitUtils.ConvertToInternalUnits({p2[2]}, UnitTypeId.Millimeters))));"
        )
    curves_cs = "\n".join(line_appends)

    code = f"""if (!doc.IsFamilyDocument) return new {{ error = "this code requires family editor" }};

using (var tx = new Transaction(doc, "KUKI: NewModelCurves"))
{{
    tx.Start();
    XYZ origin = new XYZ(
        UnitUtils.ConvertToInternalUnits({origin[0]}, UnitTypeId.Millimeters),
        UnitUtils.ConvertToInternalUnits({origin[1]}, UnitTypeId.Millimeters),
        UnitUtils.ConvertToInternalUnits({origin[2]}, UnitTypeId.Millimeters));
    Plane planeGeom = Plane.CreateByNormalAndOrigin(new XYZ({normal[0]}, {normal[1]}, {normal[2]}), origin);
    SketchPlane sp = SketchPlane.Create(doc, planeGeom);

    var curves = new CurveArray();
{curves_cs}
    ModelCurveArray mcs = doc.FamilyCreate.NewModelCurveArray(curves, sp);
    tx.Commit();
    return new {{ created = mcs.Size }};
}}"""
    return await _dispatch_code(code, bridge_callback)


async def family_create_symbolic_lines(
    args: dict[str, Any],
    bridge_callback: Optional[BridgeCallback],
) -> dict[str, Any]:
    """2D symbolic lines — visible only in plan/elevation (УГО/СПДС symbols)."""
    lines = args.get("lines_mm") or []
    if not isinstance(lines, list) or not lines:
        return {"error": True, "message": "lines_mm must be non-empty list of segments"}
    for seg in lines:
        if len(seg) != 2 or len(seg[0]) != 3 or len(seg[1]) != 3:
            return {"error": True, "message": "each segment must be [[x1,y1,z1], [x2,y2,z2]]"}
    normal = args.get("sketch_plane_normal") or [0, 0, 1]
    origin = args.get("sketch_plane_origin_mm") or [0, 0, 0]

    line_appends = []
    for seg in lines:
        p1, p2 = seg
        line_appends.append(
            f"    curves.Append(Line.CreateBound("
            f"new XYZ(UnitUtils.ConvertToInternalUnits({p1[0]}, UnitTypeId.Millimeters), "
            f"UnitUtils.ConvertToInternalUnits({p1[1]}, UnitTypeId.Millimeters), "
            f"UnitUtils.ConvertToInternalUnits({p1[2]}, UnitTypeId.Millimeters)), "
            f"new XYZ(UnitUtils.ConvertToInternalUnits({p2[0]}, UnitTypeId.Millimeters), "
            f"UnitUtils.ConvertToInternalUnits({p2[1]}, UnitTypeId.Millimeters), "
            f"UnitUtils.ConvertToInternalUnits({p2[2]}, UnitTypeId.Millimeters))));"
        )
    curves_cs = "\n".join(line_appends)

    code = f"""if (!doc.IsFamilyDocument) return new {{ error = "this code requires family editor" }};

using (var tx = new Transaction(doc, "KUKI: NewSymbolicCurves"))
{{
    tx.Start();
    XYZ origin = new XYZ(
        UnitUtils.ConvertToInternalUnits({origin[0]}, UnitTypeId.Millimeters),
        UnitUtils.ConvertToInternalUnits({origin[1]}, UnitTypeId.Millimeters),
        UnitUtils.ConvertToInternalUnits({origin[2]}, UnitTypeId.Millimeters));
    Plane planeGeom = Plane.CreateByNormalAndOrigin(new XYZ({normal[0]}, {normal[1]}, {normal[2]}), origin);
    SketchPlane sp = SketchPlane.Create(doc, planeGeom);

    var curves = new CurveArray();
{curves_cs}
    SymbolicCurveArray scs = doc.FamilyCreate.NewSymbolicCurveArray(curves, sp);
    tx.Commit();
    return new {{ created = scs.Size }};
}}"""
    return await _dispatch_code(code, bridge_callback)


# ─── V3: Sweep / SweptBlend (extrusion along a path) ─────────────────────


def _render_path_curve_array_cs(
    path_segments: list[dict[str, Any]],
    var_name: str = "pathCA",
    z_mm: float = 0.0,
    indent: str = "    ",
) -> str:
    """Render a sequence of segments as a C# CurveArray for a sweep PATH.

    Unlike profile loops, paths use absolute world XYZ (not local-2D). Each
    segment's points are full [x,y,z] triplets. We support Line + Arc only.
    """
    if not path_segments:
        raise ValueError("path must have at least one segment")
    lines = [f"{indent}var {var_name} = new CurveArray();"]
    for i, seg in enumerate(path_segments):
        t = seg.get("type")
        if t == "line":
            p1 = seg.get("p1", [0, 0, z_mm])
            p2 = seg.get("p2", [0, 0, z_mm])
            if len(p1) == 2: p1 = [p1[0], p1[1], z_mm]
            if len(p2) == 2: p2 = [p2[0], p2[1], z_mm]
            lines.append(
                f"{indent}{var_name}.Append(Line.CreateBound("
                f"new XYZ(UnitUtils.ConvertToInternalUnits({_f(p1[0])}, UnitTypeId.Millimeters), "
                f"UnitUtils.ConvertToInternalUnits({_f(p1[1])}, UnitTypeId.Millimeters), "
                f"UnitUtils.ConvertToInternalUnits({_f(p1[2])}, UnitTypeId.Millimeters)), "
                f"new XYZ(UnitUtils.ConvertToInternalUnits({_f(p2[0])}, UnitTypeId.Millimeters), "
                f"UnitUtils.ConvertToInternalUnits({_f(p2[1])}, UnitTypeId.Millimeters), "
                f"UnitUtils.ConvertToInternalUnits({_f(p2[2])}, UnitTypeId.Millimeters))));"
            )
        elif t == "arc":
            if "center" in seg:
                c = seg["center"]
                if len(c) == 2: c = [c[0], c[1], z_mm]
                r = float(seg["radius"])
                a0 = math.radians(float(seg.get("start_deg", 0.0)))
                a1 = math.radians(float(seg.get("end_deg", 360.0)))
                # For path arcs we assume XY-plane orientation (simple case);
                # complex 3D arcs should use 3-point form.
                lines.append(
                    f"{indent}{var_name}.Append(Arc.Create("
                    f"new XYZ(UnitUtils.ConvertToInternalUnits({_f(c[0])}, UnitTypeId.Millimeters), "
                    f"UnitUtils.ConvertToInternalUnits({_f(c[1])}, UnitTypeId.Millimeters), "
                    f"UnitUtils.ConvertToInternalUnits({_f(c[2])}, UnitTypeId.Millimeters)), "
                    f"UnitUtils.ConvertToInternalUnits({_f(r)}, UnitTypeId.Millimeters), "
                    f"{_f(a0)}, {_f(a1)}, XYZ.BasisX, XYZ.BasisY));"
                )
            elif "p1" in seg and "p3" in seg:
                p1 = seg["p1"]; p2 = seg.get("p2", p1); p3 = seg["p3"]
                if len(p1) == 2: p1 = [p1[0], p1[1], z_mm]
                if len(p2) == 2: p2 = [p2[0], p2[1], z_mm]
                if len(p3) == 2: p3 = [p3[0], p3[1], z_mm]
                lines.append(
                    f"{indent}{var_name}.Append(Arc.Create("
                    f"new XYZ(UnitUtils.ConvertToInternalUnits({_f(p1[0])}, UnitTypeId.Millimeters), "
                    f"UnitUtils.ConvertToInternalUnits({_f(p1[1])}, UnitTypeId.Millimeters), "
                    f"UnitUtils.ConvertToInternalUnits({_f(p1[2])}, UnitTypeId.Millimeters)), "
                    f"new XYZ(UnitUtils.ConvertToInternalUnits({_f(p3[0])}, UnitTypeId.Millimeters), "
                    f"UnitUtils.ConvertToInternalUnits({_f(p3[1])}, UnitTypeId.Millimeters), "
                    f"UnitUtils.ConvertToInternalUnits({_f(p3[2])}, UnitTypeId.Millimeters)), "
                    f"new XYZ(UnitUtils.ConvertToInternalUnits({_f(p2[0])}, UnitTypeId.Millimeters), "
                    f"UnitUtils.ConvertToInternalUnits({_f(p2[1])}, UnitTypeId.Millimeters), "
                    f"UnitUtils.ConvertToInternalUnits({_f(p2[2])}, UnitTypeId.Millimeters))));"
                )
            else:
                raise ValueError(f"arc segment {i} needs center+radius+angles or p1/p2/p3")
        else:
            raise ValueError(f"path segment {i}: unsupported type {t!r}")
    return "\n".join(lines)


def _render_xy_profile_loop_cs(
    segments: list[dict[str, Any]],
    var_name: str,
    indent: str = "    ",
) -> str:
    """Render a profile loop in pure XY plane (Z=0) — for NewSweep / NewSweptBlend.

    Difference from _render_curve_loop_cs: uses absolute XYZ coords (not __toWorld
    via a local plane) because the sweep API expects profiles in the XY plane and
    transforms them internally to the sweep path.
    """
    if not segments:
        raise ValueError("profile loop is empty")
    segs = _ensure_winding(_split_full_circles(list(segments)), want_ccw=True)
    _validate_loop_closed(segs)
    lines = [f"{indent}var {var_name} = new CurveArray();"]
    for seg in segs:
        t = seg.get("type")
        if t == "line":
            p1, p2 = seg["p1"], seg["p2"]
            lines.append(
                f"{indent}{var_name}.Append(Line.CreateBound("
                f"new XYZ(UnitUtils.ConvertToInternalUnits({_f(p1[0])}, UnitTypeId.Millimeters), "
                f"UnitUtils.ConvertToInternalUnits({_f(p1[1])}, UnitTypeId.Millimeters), 0), "
                f"new XYZ(UnitUtils.ConvertToInternalUnits({_f(p2[0])}, UnitTypeId.Millimeters), "
                f"UnitUtils.ConvertToInternalUnits({_f(p2[1])}, UnitTypeId.Millimeters), 0)));"
            )
        elif t == "arc":
            if "center" in seg:
                cx, cy = seg["center"]
                r = float(seg["radius"])
                a0 = math.radians(float(seg.get("start_deg", 0.0)))
                a1 = math.radians(float(seg.get("end_deg", 90.0)))
                lines.append(
                    f"{indent}{var_name}.Append(Arc.Create("
                    f"new XYZ(UnitUtils.ConvertToInternalUnits({_f(cx)}, UnitTypeId.Millimeters), "
                    f"UnitUtils.ConvertToInternalUnits({_f(cy)}, UnitTypeId.Millimeters), 0), "
                    f"UnitUtils.ConvertToInternalUnits({_f(r)}, UnitTypeId.Millimeters), "
                    f"{_f(a0)}, {_f(a1)}, XYZ.BasisX, XYZ.BasisY));"
                )
            elif "p1" in seg and "p3" in seg:
                p1 = seg["p1"]; p2 = seg.get("p2", p1); p3 = seg["p3"]
                lines.append(
                    f"{indent}{var_name}.Append(Arc.Create("
                    f"new XYZ(UnitUtils.ConvertToInternalUnits({_f(p1[0])}, UnitTypeId.Millimeters), "
                    f"UnitUtils.ConvertToInternalUnits({_f(p1[1])}, UnitTypeId.Millimeters), 0), "
                    f"new XYZ(UnitUtils.ConvertToInternalUnits({_f(p3[0])}, UnitTypeId.Millimeters), "
                    f"UnitUtils.ConvertToInternalUnits({_f(p3[1])}, UnitTypeId.Millimeters), 0), "
                    f"new XYZ(UnitUtils.ConvertToInternalUnits({_f(p2[0])}, UnitTypeId.Millimeters), "
                    f"UnitUtils.ConvertToInternalUnits({_f(p2[1])}, UnitTypeId.Millimeters), 0)));"
                )
        else:
            raise ValueError(f"unsupported profile segment type: {t!r}")
    return "\n".join(lines)


async def family_sweep(
    args: dict[str, Any],
    bridge_callback: Optional[BridgeCallback],
) -> dict[str, Any]:
    """Solid swept along a 2D path.

    Use for handrails, pipes/conduit, gutters, decorative trim — anything where
    a constant 2D cross-section follows a curve.

    Verified API (Sonnet V3 research item 2):
        Sweep doc.FamilyCreate.NewSweep(
            bool isSolid,
            CurveArray path,                                 // 2D path in any plane
            SketchPlane pathPlane,                           // can be null for inline curves
            SweepProfile profile,                            // from NewCurveLoopsProfile
            int profileLocationCurveIndex,                   // 0-based, profile is at this curve
            ProfilePlaneLocation profilePlaneLocation        // Start or End of the indexed curve
        )

    Args:
        path_curves: list of {type: line|arc, ...} — the path to sweep along.
        profile_loop: list of segments forming the 2D cross-section (all Z=0).
        is_solid: true=solid (default), false=void (auto-cuts).
        subcategory: optional subcategory.
    """
    path = args.get("path_curves") or []
    profile_loop = args.get("profile_loop") or []
    if not isinstance(path, list) or not path:
        return {"error": True, "message": "path_curves required (list of segments)"}
    if not isinstance(profile_loop, list) or not profile_loop:
        return {"error": True, "message": "profile_loop required (list of segments forming a closed loop)"}

    is_solid = bool(args.get("is_solid", True))
    is_solid_cs = "true" if is_solid else "false"
    subcat = (args.get("subcategory") or "").strip()

    try:
        path_cs = _render_path_curve_array_cs(path, "pathCA")
        profile_cs = _render_xy_profile_loop_cs(profile_loop, "profileLoop")
    except ValueError as e:
        return {"error": True, "message": f"sweep input invalid: {e}"}

    code = f"""if (!doc.IsFamilyDocument) return new {{ error = "this code requires family editor" }};

using (var tx = new Transaction(doc, "KUKI: Sweep"))
{{
    tx.Start();
    var creApp = doc.Application.Create;

{path_cs}

{profile_cs}

    // Build the SweepProfile via NewCurveLoopsProfile (the only documented
    // factory for inline-geometry profiles — verified V3 research item 1).
    CurveArrArray profileArr = creApp.NewCurveArrArray();
    profileArr.Append(profileLoop);
    SweepProfile sweepProfile = creApp.NewCurveLoopsProfile(profileArr);

    // NewSweep: overload 1 (CurveArray path). pathPlane=null is documented OK for inline.
    Sweep sw = doc.FamilyCreate.NewSweep(
        {is_solid_cs},
        pathCA,
        null,
        sweepProfile,
        0,
        ProfilePlaneLocation.Start);

    string scName = "{_escape_cs_string(subcat)}";
    if (!string.IsNullOrEmpty(scName) && {is_solid_cs})
    {{
        try {{
            doc.Regenerate();
            Category owner = doc.OwnerFamily?.FamilyCategory;
            if (owner != null)
            {{
                Category sub = null;
                foreach (Category c in owner.SubCategories) if (c.Name == scName) {{ sub = c; break; }}
                if (sub == null) sub = doc.Settings.Categories.NewSubcategory(owner, scName);
                sw.Subcategory = sub;
            }}
        }} catch {{ }}
    }}
    tx.Commit();
    if (!{is_solid_cs}) doc.Regenerate();
    return new {{ id = sw.Id.Value, kind = "Sweep", isSolid = {is_solid_cs} }};
}}"""
    return await _dispatch_code(code, bridge_callback)


async def family_swept_blend(
    args: dict[str, Any],
    bridge_callback: Optional[BridgeCallback],
) -> dict[str, Any]:
    """Solid swept along a SINGLE-curve path, morphing between two end profiles.

    Use for transitions: morphing pipe (round-to-square), HVAC reducers, smooth
    decorative transitions.

    Verified API (Sonnet V3 research item 3):
        SweptBlend doc.FamilyCreate.NewSweptBlend(
            bool isSolid,
            Curve path,                       // ONE curve only — Line or Arc
            SketchPlane pathSketchPlane,      // can be null
            SweepProfile bottomProfile,       // ALL Z=0
            SweepProfile topProfile           // ALL Z=0
        )

    Args:
        path_curve: ONE {type: line|arc, ...} curve (not a list).
        start_profile: list of segments forming the closed start cross-section (Z=0).
        end_profile: same shape — closed end cross-section.
        is_solid: true=solid (default), false=void.
    """
    path_curve = args.get("path_curve")
    if not isinstance(path_curve, dict):
        return {"error": True, "message": "path_curve required (single segment dict, NOT a list)"}
    if path_curve.get("type") not in ("line", "arc"):
        return {"error": True, "message": "path_curve.type must be 'line' or 'arc' (NewSweptBlend path must be one Curve)"}
    start_profile = args.get("start_profile") or []
    end_profile = args.get("end_profile") or []
    if not start_profile or not end_profile:
        return {"error": True, "message": "start_profile and end_profile both required"}

    is_solid_cs = "true" if bool(args.get("is_solid", True)) else "false"

    try:
        # Path is ONE curve, rendered as a single-segment chain
        path_cs = _render_path_curve_array_cs([path_curve], "pathTemp")
        start_cs = _render_xy_profile_loop_cs(start_profile, "startLoop")
        end_cs = _render_xy_profile_loop_cs(end_profile, "endLoop")
    except ValueError as e:
        return {"error": True, "message": f"swept_blend input invalid: {e}"}

    code = f"""if (!doc.IsFamilyDocument) return new {{ error = "this code requires family editor" }};

using (var tx = new Transaction(doc, "KUKI: SweptBlend"))
{{
    tx.Start();
    var creApp = doc.Application.Create;

{path_cs}
    // NewSweptBlend wants a single Curve, not a CurveArray
    Curve pathCurve = pathTemp.get_Item(0);

{start_cs}
    CurveArrArray startArr = creApp.NewCurveArrArray();
    startArr.Append(startLoop);
    SweepProfile startProfile = creApp.NewCurveLoopsProfile(startArr);

{end_cs}
    CurveArrArray endArr = creApp.NewCurveArrArray();
    endArr.Append(endLoop);
    SweepProfile endProfile = creApp.NewCurveLoopsProfile(endArr);

    // NewSweptBlend: bottomProfile, topProfile parameter order per revitapidocs 2015+ verified V3.
    // Both profiles must lie in XY plane (Z=0) — enforced by _render_xy_profile_loop_cs.
    SweptBlend sb = doc.FamilyCreate.NewSweptBlend(
        {is_solid_cs}, pathCurve, null, startProfile, endProfile);

    tx.Commit();
    if (!{is_solid_cs}) doc.Regenerate();
    return new {{ id = sb.Id.Value, kind = "SweptBlend", isSolid = {is_solid_cs} }};
}}"""
    return await _dispatch_code(code, bridge_callback)


# ─── V3: Alignment (parametric face-to-refplane lock) ────────────────────


async def family_create_alignment(
    args: dict[str, Any],
    bridge_callback: Optional[BridgeCallback],
) -> dict[str, Any]:
    """Lock alignment between two references — extrusion face ↔ ref plane, or
    two ref planes. Returns the locked Dimension element.

    Verified API (Sonnet V3 research item 6):
        Dimension doc.FamilyCreate.NewAlignment(View view, Reference ref1, Reference ref2)

    KEY constraints from research:
    - View MUST be a 2D view (Plan / Elevation / Section). 3D views fail.
    - References must ALREADY be geometrically aligned before this call —
      NewAlignment locks an existing alignment, it doesn't create a constraint.
    - face.Reference requires `Options.ComputeReferences = true`.
    - face.Reference is stale after `doc.Regenerate()` — re-query.
    - `ReferencePlane.GetReference()` returns a stable, ready-to-use Reference.

    Args:
        anchor: {"type": "reference_plane", "id": int}
        target: {"type": "reference_plane", "id": int}
                 OR
                {"type": "extrusion_face", "element_id": int, "face_normal": [nx,ny,nz]}

    Returns: {id: <dim_id>, kind: "Alignment"}
    """
    anchor = args.get("anchor") or {}
    target = args.get("target") or {}
    if not isinstance(anchor, dict) or not isinstance(target, dict):
        return {"error": True, "message": "anchor and target must be objects"}

    def _validate_ref(ref: dict[str, Any], name: str) -> Optional[str]:
        t = ref.get("type")
        if t == "reference_plane":
            try:
                rid = int(ref.get("id", 0))
            except (TypeError, ValueError):
                return f"{name}.id must be integer"
            if rid <= 0:
                return f"{name}.id required"
            return None
        if t == "extrusion_face":
            try:
                eid = int(ref.get("element_id", 0))
            except (TypeError, ValueError):
                return f"{name}.element_id must be integer"
            if eid <= 0:
                return f"{name}.element_id required"
            normal = ref.get("face_normal")
            if not normal or len(normal) != 3:
                return f"{name}.face_normal must be [nx,ny,nz]"
            return None
        return f"{name}.type must be 'reference_plane' or 'extrusion_face'"

    for label, r in [("anchor", anchor), ("target", target)]:
        err = _validate_ref(r, label)
        if err:
            return {"error": True, "message": err}

    def _ref_block_cs(ref: dict[str, Any], var: str) -> str:
        t = ref["type"]
        if t == "reference_plane":
            rid = int(ref["id"])
            return f"""    Element {var}El = doc.GetElement(new ElementId((long)({rid})));
    ReferencePlane {var}Rp = {var}El as ReferencePlane;
    if ({var}Rp == null) return new {{ error = "ref_plane {rid} not found or not a ReferencePlane" }};
    Reference {var} = {var}Rp.GetReference();"""
        # extrusion_face: traverse geometry with ComputeReferences=true and pick the face
        # whose normal matches face_normal within a small tolerance.
        eid = int(ref["element_id"])
        nx, ny, nz = ref["face_normal"]
        return f"""    Element {var}El = doc.GetElement(new ElementId((long)({eid})));
    if ({var}El == null) return new {{ error = "extrusion {eid} not found" }};
    XYZ {var}NWanted = new XYZ({_f(nx)}, {_f(ny)}, {_f(nz)}).Normalize();
    Options {var}Opt = new Options {{ ComputeReferences = true }};
    GeometryElement {var}Geo = {var}El.get_Geometry({var}Opt);
    Reference {var} = null;
    foreach (GeometryObject __go in {var}Geo)
    {{
        Solid __sol = __go as Solid;
        if (__sol == null) continue;
        foreach (Face __f in __sol.Faces)
        {{
            // For PlanarFace, FaceNormal is constant
            PlanarFace __pf = __f as PlanarFace;
            if (__pf == null) continue;
            XYZ __n = __pf.FaceNormal.Normalize();
            if (__n.IsAlmostEqualTo({var}NWanted, 0.01) || __n.IsAlmostEqualTo({var}NWanted.Negate(), 0.01))
            {{
                {var} = __pf.Reference;
                if ({var} != null) break;
            }}
        }}
        if ({var} != null) break;
    }}
    if ({var} == null) return new {{ error = "no planar face on element {eid} matched normal ({nx},{ny},{nz}) — verify the element has a face with that normal" }};"""

    anchor_cs = _ref_block_cs(anchor, "anchorRef")
    target_cs = _ref_block_cs(target, "targetRef")

    code = f"""if (!doc.IsFamilyDocument) return new {{ error = "this code requires family editor" }};

// NewAlignment requires a 2D view (Plan/Elevation/Section).
// doc.ActiveView may be the 3D view in family editor — find a 2D view if needed.
View align2dView = doc.ActiveView;
if (align2dView is View3D)
{{
    align2dView = new FilteredElementCollector(doc).OfClass(typeof(View)).Cast<View>()
        .FirstOrDefault(v => !v.IsTemplate && (v.ViewType == ViewType.FloorPlan
            || v.ViewType == ViewType.Elevation
            || v.ViewType == ViewType.Section
            || v.ViewType == ViewType.CeilingPlan));
}}
if (align2dView == null) return new {{ error = "no 2D view available for NewAlignment (need Plan/Elevation/Section)" }};

using (var tx = new Transaction(doc, "KUKI: Alignment"))
{{
    tx.Start();
{anchor_cs}

{target_cs}

    Dimension dim;
    try {{
        dim = doc.FamilyCreate.NewAlignment(align2dView, anchorRef, targetRef);
    }} catch (Exception ex) {{
        tx.RollBack();
        return new {{ error = "NewAlignment failed (geometry must be ALIGNED before this call): " + ex.Message }};
    }}
    tx.Commit();
    return new {{ id = dim.Id.Value, kind = "Alignment" }};
}}"""
    return await _dispatch_code(code, bridge_callback)


# ─── V3: Unified family_extrude_advanced (profile_spec + sketch_plane) ───


async def family_extrude_advanced(
    args: dict[str, Any],
    bridge_callback: Optional[BridgeCallback],
) -> dict[str, Any]:
    """Powerful unified extrude: arbitrary profile (Lines + Arcs, multi-loop = holes),
    arbitrary sketch plane (axis-aligned OR inclined).

    Use this when the rectangle/cylinder shortcuts (`family_extrude`,
    `family_cylinder`) aren't enough — gears with curved teeth, rings with
    inner holes, L/U/hex profiles with rounded corners, sloped/tilted features.

    Args:
        profile (dict): {outer_loop: [<segment>, ...], inner_loops?: [[...], ...]}
            Segment shapes:
              - {"type": "line", "p1": [x,y], "p2": [x,y]}        — straight segment
              - {"type": "arc",  "center": [cx,cy], "radius": r,
                                  "start_deg": a, "end_deg": b}    — arc by angles
              - {"type": "arc",  "p1": [x,y], "p2": [x,y], "p3": [x,y]}
                                                                   — 3-point arc, p2 on arc
            All coords in LOCAL 2D (mm) inside the sketch_plane's UV frame.
            outer_loop must be closed (last segment end == first segment start).
            inner_loops are HOLES — each must be closed; placed INSIDE outer_loop.
        sketch_plane (dict, optional): {"origin_mm": [x,y,z], "normal": [nx,ny,nz]}
            Default = XY plane at world origin.
        depth_mm (float): extrusion length along plane normal in mm.
        is_solid (bool): true=solid, false=void (auto-cuts overlapping solids
            in standard family templates).
        subcategory (str, optional): subcategory name to assign.

    Returns: {id (long), kind: "Extrusion", isSolid (bool)}
    """
    profile = args.get("profile")
    if not isinstance(profile, dict):
        return {"error": True, "message": "profile required (dict with outer_loop + optional inner_loops)"}
    sketch_plane = args.get("sketch_plane")
    try:
        depth_mm = float(args.get("depth_mm", 0))
    except (TypeError, ValueError):
        return {"error": True, "message": "depth_mm must be a number"}
    if depth_mm <= 0:
        return {"error": True, "message": "depth_mm must be > 0"}
    is_solid = bool(args.get("is_solid", True))
    is_solid_cs = "true" if is_solid else "false"
    subcat = (args.get("subcategory") or "").strip()

    # Render once in Python — surface validation errors back to Gemini.
    try:
        sp_cs = _render_sketch_plane_cs(sketch_plane)
        profile_cs = _render_curve_arr_array_cs(profile)
    except ValueError as e:
        return {"error": True, "message": f"profile_spec invalid: {e}"}

    code = f"""if (!doc.IsFamilyDocument) return new {{ error = "this code requires family editor" }};

double depth = UnitUtils.ConvertToInternalUnits({_f(depth_mm)}, UnitTypeId.Millimeters);
Plane __planeGeomForDiag = null;  // captured from sp_cs block — used by diag catch

using (var tx = new Transaction(doc, "KUKI: Extrude (advanced)"))
{{
    tx.Start();
    try
    {{
{sp_cs}
        __planeGeomForDiag = planeGeom;

{profile_cs}

        // NewExtrusion(isSolid, profile, sketchPlane, end) - `end` is along plane normal in feet
        Extrusion ext = doc.FamilyCreate.NewExtrusion({is_solid_cs}, profile, sp, depth);

        string scName = "{_escape_cs_string(subcat)}";
        if (!string.IsNullOrEmpty(scName) && {is_solid_cs})
        {{
            try {{
                doc.Regenerate();
                Category owner = doc.OwnerFamily?.FamilyCategory;
                if (owner != null)
                {{
                    Category sub = null;
                    foreach (Category c in owner.SubCategories) if (c.Name == scName) {{ sub = c; break; }}
                    if (sub == null) sub = doc.Settings.Categories.NewSubcategory(owner, scName);
                    ext.Subcategory = sub;
                }}
            }} catch {{ }}
        }}
        tx.Commit();
        if (!{is_solid_cs}) doc.Regenerate();  // void auto-cut takes effect on regen
        return new {{ id = ext.Id.Value, kind = "Extrusion", isSolid = {is_solid_cs} }};
    }}
    catch (Autodesk.Revit.Exceptions.InvalidOperationException _ex_extr)
    {{
        try {{ tx.RollBack(); }} catch {{ }}
        Category _diag_cat = null;
        try {{ _diag_cat = doc.OwnerFamily?.FamilyCategory; }} catch {{ }}
        string _diag_catName = _diag_cat?.Name ?? "(unknown)";
        long _diag_catId = _diag_cat != null ? _diag_cat.Id.Value : -1L;
        string _diag_viewKind = "(none)";
        string _diag_viewName = "(none)";
        try {{
            var _diag_v = doc.ActiveView;
            if (_diag_v != null) {{ _diag_viewKind = _diag_v.ViewType.ToString(); _diag_viewName = _diag_v.Name; }}
        }} catch {{ }}
        double[] _diag_norm = new double[] {{ 0, 0, 0 }};
        double[] _diag_orig = new double[] {{ 0, 0, 0 }};
        try {{
            if (__planeGeomForDiag != null) {{
                _diag_norm = new double[] {{ __planeGeomForDiag.Normal.X, __planeGeomForDiag.Normal.Y, __planeGeomForDiag.Normal.Z }};
                _diag_orig = new double[] {{ __planeGeomForDiag.Origin.X, __planeGeomForDiag.Origin.Y, __planeGeomForDiag.Origin.Z }};
            }}
        }} catch {{ }}
        return new {{
            error = true,
            message = "family_extrude_advanced failed: " + _ex_extr.Message,
            diagnostic = new {{
                operation = "family_extrude_advanced",
                family_category = _diag_catName,
                family_category_id = _diag_catId,
                active_view_kind = _diag_viewKind,
                active_view_name = _diag_viewName,
                sketch_plane_normal = _diag_norm,
                sketch_plane_origin = _diag_orig,
                error_type = "InvalidOperationException",
            }}
        }};
    }}
}}"""
    return await _dispatch_code(code, bridge_callback)


# ─── V3: Array primitive (radial + linear) ───────────────────────────────


async def family_create_array(
    args: dict[str, Any],
    bridge_callback: Optional[BridgeCallback],
) -> dict[str, Any]:
    """Replicate one or more existing solids N times — radial or linear.

    Implementation: server-side C# loop calling ElementTransformUtils.CopyElement
    + ElementTransformUtils.RotateElement (radial) or just CopyElement with
    cumulative translation (linear). All inside a single transaction.

    We DO NOT use Revit's `ArrayElement` — that's a project-side parametric
    array system; behaviour in family editor is undocumented and parametric
    flex through it is messy. Manual replication is deterministic and atomic.

    Args:
        source_element_ids: list[int] — ElementId.Value of solids to clone
        array_type: "radial" | "linear"
        count: total copies INCLUDING the original (so count=20 → 19 copies + 1 source)
        rotation_center_mm: [x,y,z] in mm — required for radial
        rotation_axis: [nx,ny,nz] — default [0,0,1] (Z axis)
        total_angle_deg: full sweep angle in degrees — default 360 (full ring)
        translation_step_mm: [dx,dy,dz] in mm — required for linear

    Returns:
        {success, new_element_ids: list[int], count}
    """
    source_ids = args.get("source_element_ids") or []
    if not isinstance(source_ids, list) or not source_ids:
        return {"error": True, "message": "source_element_ids required (non-empty list)"}
    try:
        source_ids_int = [int(i) for i in source_ids]
    except (TypeError, ValueError):
        return {"error": True, "message": "source_element_ids must be integers"}
    if any(i <= 0 for i in source_ids_int):
        return {"error": True, "message": "all source_element_ids must be > 0"}

    array_type = (args.get("array_type") or "").lower()
    if array_type not in ("radial", "linear"):
        return {"error": True, "message": "array_type must be 'radial' or 'linear'"}

    try:
        count = int(args.get("count", 0))
    except (TypeError, ValueError):
        return {"error": True, "message": "count must be an integer"}
    if count < 2:
        return {"error": True, "message": "count must be >= 2 (count=1 = original alone)"}
    if count > 200:
        return {"error": True, "message": "count > 200 not allowed (use execute_revit_code for large arrays)"}

    if array_type == "radial":
        center = args.get("rotation_center_mm") or [0.0, 0.0, 0.0]
        axis = args.get("rotation_axis") or [0.0, 0.0, 1.0]
        if len(center) != 3 or len(axis) != 3:
            return {"error": True, "message": "rotation_center_mm / rotation_axis must be [x,y,z]"}
        try:
            total_angle_deg = float(args.get("total_angle_deg", 360.0))
        except (TypeError, ValueError):
            return {"error": True, "message": "total_angle_deg must be a number"}
        # step angle: if 360°, distribute evenly N times (last one wraps to start)
        # else evenly across the open arc (N-1 gaps between N items)
        is_full_circle = abs(abs(total_angle_deg) - 360.0) < 1e-6
        step_deg = total_angle_deg / count if is_full_circle else total_angle_deg / (count - 1)
        step_rad = math.radians(step_deg)

        ids_cs = "new long[] { " + ", ".join(str(i) for i in source_ids_int) + " }"
        code = f"""if (!doc.IsFamilyDocument) return new {{ error = "this code requires family editor" }};

long[] srcIds = {ids_cs};
int copyCount = {count - 1};        // count INCLUDES original; we create N-1 copies
double stepRad = {_f(step_rad)};
XYZ rotCenter = new XYZ(
    UnitUtils.ConvertToInternalUnits({_f(center[0])}, UnitTypeId.Millimeters),
    UnitUtils.ConvertToInternalUnits({_f(center[1])}, UnitTypeId.Millimeters),
    UnitUtils.ConvertToInternalUnits({_f(center[2])}, UnitTypeId.Millimeters));
XYZ rotAxisDir = new XYZ({_f(axis[0])}, {_f(axis[1])}, {_f(axis[2])}).Normalize();
Line rotAxis = Line.CreateUnbound(rotCenter, rotAxisDir);

var srcIdList = new List<ElementId>();
foreach (long id in srcIds) {{
    ElementId eid = new ElementId(id);
    if (doc.GetElement(eid) == null) return new {{ error = "source element " + id + " not found" }};
    srcIdList.Add(eid);
}}

var newIds = new List<long>();
using (var tx = new Transaction(doc, "KUKI: Radial array"))
{{
    tx.Start();
    for (int i = 1; i <= copyCount; i++)
    {{
        double angle = stepRad * i;
        var copies = ElementTransformUtils.CopyElements(doc, srcIdList, XYZ.Zero);
        ElementTransformUtils.RotateElements(doc, copies, rotAxis, angle);
        foreach (var cId in copies) newIds.Add(cId.Value);
    }}
    tx.Commit();
}}
return new {{ success = true, arrayType = "radial", count = {count}, newElementIds = newIds.ToArray() }};"""
        return await _dispatch_code(code, bridge_callback, timeout_ms=_COMPOSITE_TIMEOUT_MS)

    # linear
    step = args.get("translation_step_mm") or []
    if len(step) != 3:
        return {"error": True, "message": "translation_step_mm must be [dx,dy,dz] in mm"}
    ids_cs = "new long[] { " + ", ".join(str(i) for i in source_ids_int) + " }"
    code = f"""if (!doc.IsFamilyDocument) return new {{ error = "this code requires family editor" }};

long[] srcIds = {ids_cs};
int copyCount = {count - 1};
XYZ stepVec = new XYZ(
    UnitUtils.ConvertToInternalUnits({_f(step[0])}, UnitTypeId.Millimeters),
    UnitUtils.ConvertToInternalUnits({_f(step[1])}, UnitTypeId.Millimeters),
    UnitUtils.ConvertToInternalUnits({_f(step[2])}, UnitTypeId.Millimeters));

var srcIdList = new List<ElementId>();
foreach (long id in srcIds) {{
    ElementId eid = new ElementId(id);
    if (doc.GetElement(eid) == null) return new {{ error = "source element " + id + " not found" }};
    srcIdList.Add(eid);
}}

var newIds = new List<long>();
using (var tx = new Transaction(doc, "KUKI: Linear array"))
{{
    tx.Start();
    for (int i = 1; i <= copyCount; i++)
    {{
        XYZ offset = new XYZ(stepVec.X * i, stepVec.Y * i, stepVec.Z * i);
        var copies = ElementTransformUtils.CopyElements(doc, srcIdList, offset);
        foreach (var cId in copies) newIds.Add(cId.Value);
    }}
    tx.Commit();
}}
return new {{ success = true, arrayType = "linear", count = {count}, newElementIds = newIds.ToArray() }};"""
    return await _dispatch_code(code, bridge_callback, timeout_ms=_COMPOSITE_TIMEOUT_MS)


# ─── Dispatch table — public entry-point ─────────────────────────────────

HANDLERS: dict[str, Callable[[dict[str, Any], Optional[BridgeCallback]], Awaitable[dict[str, Any]]]] = {
    # Layer 0 — read state
    "inspect_family": inspect_family,
    # Layer 1 — geometry primitives (compose ANY shape)
    "family_extrude": family_extrude,                    # rectangle shortcut
    "family_cylinder": family_cylinder,                  # circle shortcut
    "family_extrude_polygon": family_extrude_polygon,    # arbitrary polygon
    "family_blend": family_blend,                        # tapered (two profiles)
    "family_revolve": family_revolve,                    # rotation
    "family_void_cut": family_void_cut,                  # void (auto-cuts)
    # Layer 2 — geometry modification
    "family_delete_element": family_delete_element,
    "family_move_element": family_move_element,
    # Layer 3 — references & parametric constraints
    "family_create_reference_plane": family_create_reference_plane,
    "family_regenerate": family_regenerate,              # required between create-refs and dim
    "family_create_dimension": family_create_dimension,  # labeled dim
    # Layer 4 — parameters & types
    "family_add_parameter": family_add_parameter,
    "family_set_parameter_value": family_set_parameter_value,
    "family_new_type": family_new_type,
    # Layer 5 — polish (materials, visibility, annotations)
    "family_assign_material": family_assign_material,
    "family_create_subcategory": family_create_subcategory,
    "family_set_visibility": family_set_visibility,
    "family_create_model_lines": family_create_model_lines,
    "family_create_symbolic_lines": family_create_symbolic_lines,
    # NOTE: family_build_skeleton REMOVED in V3.1 — was a "ready-made rectangular
    # box skeleton" recipe, identical anti-pattern to the killed family_build_chair.
    # Gemini composes any skeleton (rect/triangle/hex/asymmetric) from primitives:
    # family_add_parameter × N + family_create_reference_plane × M + family_regenerate
    # + family_create_dimension × N. Documented in the slim prompt.
    # V3 — array replication (radial/linear)
    "family_create_array": family_create_array,
    # V3 — unified extrude with profile_spec (arcs + multi-loop + inclined plane)
    "family_extrude_advanced": family_extrude_advanced,
    # V3 — swept geometry along a path
    "family_sweep": family_sweep,
    "family_swept_blend": family_swept_blend,
    # V3 — parametric alignment lock
    "family_create_alignment": family_create_alignment,
}


# ─── V4: Code-CAD "any complexity" path ──────────────────────────────────
# Lazy import to avoid pulling cadquery (≈1.1 GB on disk) when the family
# tools module is imported but the codecad tool is never called.
def _lazy_family_generate_complex():
    """Returns the family_generate_complex handler, importing lazily."""
    from kukai.llm.tool_handlers.family_codecad import family_generate_complex
    return family_generate_complex


async def _family_generate_complex_dispatcher(args, bridge_callback):
    """Trampoline so HANDLERS can reference the V4 tool without an eager import.

    Loading kukai.codecad.cadquery_runner forces import of cadquery (~250 MB
    site-packages); we keep family_tools.py cheap by deferring that until
    Gemini actually calls family_generate_complex.
    """
    handler = _lazy_family_generate_complex()
    return await handler(args, bridge_callback)


HANDLERS["family_generate_complex"] = _family_generate_complex_dispatcher


def is_family_tool(name: str) -> bool:
    """Whether a tool name is a family-* tool handled by this module."""
    return name in HANDLERS


async def dispatch(
    tool_name: str,
    args: dict[str, Any],
    bridge_callback: Optional[BridgeCallback],
) -> dict[str, Any]:
    """Dispatch a family-* tool call to the appropriate handler."""
    handler = HANDLERS.get(tool_name)
    if handler is None:
        return {"error": True, "message": f"unknown family tool: {tool_name}"}
    return await handler(args, bridge_callback)
