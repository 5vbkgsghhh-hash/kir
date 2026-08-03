"""family_generate_complex — the "any complexity" geometry path.

Workflow:
1. Gemini emits CadQuery Python code (lofts, fillets, NURBS, booleans —
   anything Code-CAD can express).
2. We run that code in a sandboxed subprocess (cadquery_runner.run_to_stl).
3. We parse the produced STL into a triangle list.
4. We synthesise C# that builds a Revit TessellatedShape from those triangles
   and places it as a DirectShape inside the active family document.
5. The C# is dispatched through the existing `execute` bridge path — which
   already pre-flight-compiles, encrypts and routes safely.

This complements V3 primitives. Gemini picks the right path:
    - Parametric family (chair, cabinet, door, gear)   → V3 primitives + dims.
    - Organic / freeform / detailed (car, statue, ...) → this tool.

Result: a DirectShape inside the .rfa. The downstream "self-review +
parametrize" step (system_base_family_editor.md Phase 4) wraps it with
Width/Depth/Height labeled dims on the bounding box, so the family still
behaves like a real Revit family for placement.

Known limitations (Phase 1 — Roslyn-embedded mesh):
    - Triangle count cap (~50k) because C# string literal embedding gets
      heavy. Higher density meshes require Phase 2 (bridge-side STL import
      via a dedicated bridge method).
    - DirectShape is static — no labeled-dim flex inside the imported solid.
      External Width/Depth/Height on the bounding box still work.
"""
from __future__ import annotations

import base64
import logging
from typing import Any, Optional

from kukai.codecad.cadquery_runner import (
    CadQueryError,
    CadQueryPart,
    MAX_OUTPUT_TRIANGLES,
    run,
)
from kukai.codecad.stl_parser import Triangle, parse_stl
from kukai.llm.tool_handlers.family_tools import (
    BridgeCallback,
    _COMPOSITE_TIMEOUT_MS,
    _dispatch_code,
    _escape_cs_string,
)

logger = logging.getLogger(__name__)

# Triangle batch size for C# code generation. Roslyn handles ~5000 array
# initialiser entries per single literal smoothly; we split larger meshes
# across multiple AddTriangles calls so the wrapped class stays parseable.
_TRI_BATCH = 4000


def _f(x: float) -> str:
    """C# numeric literal — never scientific notation (Roslyn rejects 1e-5)."""
    if x == 0.0:
        return "0.0"
    return repr(float(x))


def _render_triangle_batches_cs(triangles: list[Triangle]) -> str:
    """Emit `__addBatch(...)` calls; each batch carries up to _TRI_BATCH triangles.

    A batch is a `double[][] {{ ... }}` literal where each row is
    9 doubles (3 vertices × 3 coords) in *millimetres*. The C# side multiplies
    by the mm→ft conversion. Splitting prevents single literals from exceeding
    Roslyn's expression-tree depth on big meshes.
    """
    out: list[str] = []
    for start in range(0, len(triangles), _TRI_BATCH):
        rows = []
        for t in triangles[start:start + _TRI_BATCH]:
            (x1, y1, z1), (x2, y2, z2), (x3, y3, z3) = t.v1, t.v2, t.v3
            rows.append(
                "new double[]{"
                f"{_f(x1)},{_f(y1)},{_f(z1)},"
                f"{_f(x2)},{_f(y2)},{_f(z2)},"
                f"{_f(x3)},{_f(y3)},{_f(z3)}"
                "}"
            )
        batch_lit = "new double[][] {\n        " + ",\n        ".join(rows) + "\n    }"
        out.append(f"    __addBatch({batch_lit});")
    return "\n".join(out)


def _bbox_of_triangles(triangles: list[Triangle]) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float]]:
    """Min/max per axis from a triangle list. Returns ((xmin,xmax),(ymin,ymax),(zmin,zmax))."""
    if not triangles:
        return ((0.0, 0.0), (0.0, 0.0), (0.0, 0.0))
    xs, ys, zs = [], [], []
    for t in triangles:
        for v in (t.v1, t.v2, t.v3):
            xs.append(v[0]); ys.append(v[1]); zs.append(v[2])
    return ((min(xs), max(xs)), (min(ys), max(ys)), (min(zs), max(zs)))


def _render_multi_part_directshape_cs(
    parts: list[tuple[str, list[Triangle], tuple[float, float, float] | None]],
    description: str,
) -> str:
    """Compose C# that creates ONE DirectShape per part, each with its own colour.

    Each tuple: (part_name, triangles, color_rgb_0_to_1).

    The colour is applied via an override-graphics-settings pattern on the
    OwnerFamily's category — for now we just store it as the DirectShape's
    overridden colour in the active view. Material assignment is via
    Material.Create + BuiltInParameter.MATERIAL_ID_PARAM (a follow-up — for
    now, the colour goes through the visible-in-view path).
    """
    desc_lit = _escape_cs_string(description[:120])

    # Per-part rendered batches
    blocks = []
    for idx, (name, tris, color) in enumerate(parts):
        batches_cs = _render_triangle_batches_cs(tris)
        name_lit = _escape_cs_string(name[:80])
        color_block = ""
        if color is not None:
            r = max(0, min(255, int(round(color[0] * 255))))
            g = max(0, min(255, int(round(color[1] * 255))))
            b = max(0, min(255, int(round(color[2] * 255))))
            # Override per-view colour so user actually sees the difference.
            color_block = f"""
        try {{
            var __ogs = new OverrideGraphicSettings();
            var __col = new Color((byte){r}, (byte){g}, (byte){b});
            __ogs.SetSurfaceForegroundPatternColor(__col);
            __ogs.SetProjectionLineColor(__col);
            doc.ActiveView.SetElementOverrides(__ds_{idx}.Id, __ogs);
        }} catch {{ }}"""

        blocks.append(f"""    // Part {idx}: {name_lit}
    var __tris_{idx} = new System.Collections.Generic.List<double[]>();
    System.Action<double[][]> __addBatch_{idx} = (batch) => {{ foreach (var t in batch) __tris_{idx}.Add(t); }};

{batches_cs.replace('__addBatch(', f'__addBatch_{idx}(')}

    var __builder_{idx} = new TessellatedShapeBuilder();
    __builder_{idx}.OpenConnectedFaceSet(false);
    foreach (var t in __tris_{idx})
    {{
        XYZ __v1 = new XYZ(t[0] * __mm2ft, t[1] * __mm2ft, t[2] * __mm2ft);
        XYZ __v2 = new XYZ(t[3] * __mm2ft, t[4] * __mm2ft, t[5] * __mm2ft);
        XYZ __v3 = new XYZ(t[6] * __mm2ft, t[7] * __mm2ft, t[8] * __mm2ft);
        __builder_{idx}.AddFace(new TessellatedFace(
            new System.Collections.Generic.List<XYZ> {{ __v1, __v2, __v3 }},
            ElementId.InvalidElementId));
    }}
    __builder_{idx}.CloseConnectedFaceSet();
    __builder_{idx}.Target = TessellatedShapeBuilderTarget.AnyGeometry;
    __builder_{idx}.Fallback = TessellatedShapeBuilderFallback.Mesh;
    __builder_{idx}.Build();

    DirectShape __ds_{idx} = DirectShape.CreateElement(doc, __catId);
    __ds_{idx}.SetShape(__builder_{idx}.GetBuildResult().GetGeometricalObjects());
    try {{ __ds_{idx}.SetName("{desc_lit}_{name_lit}"); }} catch {{ }}
    __all_ids.Add(__ds_{idx}.Id.Value);
    __all_triangles += __tris_{idx}.Count;{color_block}""")

    parts_cs = "\n\n".join(blocks)

    return f"""if (!doc.IsFamilyDocument) return new {{ error = "this code requires family editor" }};

double __mm2ft = UnitUtils.ConvertToInternalUnits(1.0, UnitTypeId.Millimeters);

ElementId __catId;
try {{ __catId = doc.OwnerFamily.FamilyCategory.Id; }}
catch {{ __catId = new ElementId((int)BuiltInCategory.OST_GenericModel); }}

var __all_ids = new System.Collections.Generic.List<long>();
int __all_triangles = 0;

using (var tx = new Transaction(doc, "KUKI: Import complex geometry ({desc_lit})"))
{{
    tx.Start();
{parts_cs}
    tx.Commit();
}}

return new {{
    success = true,
    kind = "DirectShape",
    mode = "codecad_mesh",
    part_count = __all_ids.Count,
    element_ids = __all_ids,
    triangle_count = __all_triangles,
    description = "{desc_lit}",
}};"""


def _render_directshape_cs(triangles: list[Triangle], description: str) -> str:
    """Compose the full C# script that:
      1. Pre-allocates the mesh from the embedded triangle batches.
      2. Builds a TessellatedShape (Mesh fallback — robust for arbitrary meshes).
      3. Creates a DirectShape inside the family document, sets the shape.
      4. Returns success with element id + bbox.
    """
    batches_cs = _render_triangle_batches_cs(triangles)
    desc_lit = _escape_cs_string(description[:120])
    return f"""if (!doc.IsFamilyDocument) return new {{ error = "this code requires family editor" }};

double __mm2ft = UnitUtils.ConvertToInternalUnits(1.0, UnitTypeId.Millimeters);

var __allTris = new System.Collections.Generic.List<double[]>();
System.Action<double[][]> __addBatch = (batch) =>
{{
    foreach (var t in batch) __allTris.Add(t);
}};

{batches_cs}

using (var tx = new Transaction(doc, "KUKI: Import complex geometry"))
{{
    tx.Start();
    var __builder = new TessellatedShapeBuilder();
    __builder.OpenConnectedFaceSet(false);
    foreach (var t in __allTris)
    {{
        XYZ __v1 = new XYZ(t[0] * __mm2ft, t[1] * __mm2ft, t[2] * __mm2ft);
        XYZ __v2 = new XYZ(t[3] * __mm2ft, t[4] * __mm2ft, t[5] * __mm2ft);
        XYZ __v3 = new XYZ(t[6] * __mm2ft, t[7] * __mm2ft, t[8] * __mm2ft);
        var __face = new TessellatedFace(
            new System.Collections.Generic.List<XYZ> {{ __v1, __v2, __v3 }},
            ElementId.InvalidElementId);
        __builder.AddFace(__face);
    }}
    __builder.CloseConnectedFaceSet();
    __builder.Target = TessellatedShapeBuilderTarget.AnyGeometry;
    __builder.Fallback = TessellatedShapeBuilderFallback.Mesh;
    __builder.Build();
    var __result = __builder.GetBuildResult();
    var __geo = __result.GetGeometricalObjects();

    ElementId __catId;
    try {{ __catId = doc.OwnerFamily.FamilyCategory.Id; }}
    catch {{ __catId = new ElementId((int)BuiltInCategory.OST_GenericModel); }}

    DirectShape __ds = DirectShape.CreateElement(doc, __catId);
    __ds.SetShape(__geo);
    try {{ __ds.SetName("{desc_lit}"); }} catch {{ }}
    tx.Commit();

    return new {{
        success = true,
        id = __ds.Id.Value,
        kind = "DirectShape",
        mode = "codecad_mesh",
        triangle_count = __allTris.Count,
        description = "{desc_lit}",
    }};
}}"""


async def family_generate_complex(
    args: dict[str, Any],
    bridge_callback: Optional[BridgeCallback],
) -> dict[str, Any]:
    """Generate arbitrary-complexity geometry from CadQuery code.

    Args:
        code (str): CadQuery Python source. Final result must be assigned to
            a variable named one of: result, model, final, output, shape.
            Example:
                ```
                result = (cq.Workplane("XY")
                    .box(1600, 800, 350)
                    .edges("|Z").fillet(60))
                ```
        description (str, optional): short label for the resulting DirectShape.
        tolerance (float, optional): STL linear tolerance in mm (default 0.1).
            Higher = fewer triangles, lower fidelity.
        angular_tolerance (float, optional): STL angular tolerance (default 0.1).
        timeout_s (float, optional): subprocess timeout in seconds (default 60).

    Returns dict with:
        success (bool), id (long DirectShape id), triangle_count,
        cadquery_stdout (truncated, surfaced for self-debug),
        runtime_s.
    """
    code = args.get("code")
    if not isinstance(code, str) or not code.strip():
        return {"error": True, "message": "code (CadQuery Python) required"}

    description = str(args.get("description", "complex_geometry"))[:200]
    # Quality preset maps to tolerance + angular_tolerance. Explicit tolerance
    # wins if supplied; otherwise quality preset; otherwise the "balanced" default.
    quality = str(args.get("quality", "balanced")).lower()
    _quality_presets = {
        "draft":    (0.5,  0.5),
        "balanced": (0.1,  0.1),
        "high":     (0.03, 0.05),
    }
    qt_tol, qt_ang = _quality_presets.get(quality, _quality_presets["balanced"])
    tolerance = float(args.get("tolerance", qt_tol))
    angular_tolerance = float(args.get("angular_tolerance", qt_ang))
    timeout_s = float(args.get("timeout_s", 60.0))
    # Output format. "stl" = TessellatedShape via Roslyn C# (default, all Revit versions,
    # faceted). "step" = NURBS curves via bridge import_step (Revit 2024+, smoother).
    output_format = str(args.get("output_format", "stl")).lower()
    if output_format not in ("stl", "step", "auto"):
        return {"error": True, "message": "output_format must be 'stl', 'step', or 'auto'"}
    if not (0.001 <= tolerance <= 10.0):
        return {"error": True, "message": "tolerance must be in [0.001, 10.0] mm"}
    if not (0.001 <= angular_tolerance <= 1.5):
        return {"error": True, "message": "angular_tolerance must be in [0.001, 1.5] radians"}
    if not (5.0 <= timeout_s <= 300.0):
        return {"error": True, "message": "timeout_s must be in [5, 300]"}

    # Step 1 — run CadQuery in subprocess. Returns multi-part result + SVG preview + bbox.
    try:
        cq_result = await run(
            code,
            timeout_s=timeout_s,
            stl_tolerance=tolerance,
            stl_angular_tolerance=angular_tolerance,
        )
    except CadQueryError as cqe:
        return {
            "error": True,
            "message": str(cqe)[:2000],
            "kind": cqe.kind,
            "hint": _hint_for(cqe.kind),
        }
    except Exception as e:  # noqa: BLE001
        logger.exception("CadQuery runner exploded")
        return {"error": True, "message": f"runner failure: {e}", "kind": "runtime"}

    # ─── STEP path (Revit 2024+) ────────────────────────────────────────────
    # When the caller asks for STEP and we actually have STEP bytes per part, try
    # dispatching via the bridge `import_step` method. If it succeeds, return.
    # Falls back to STL silently if bridge doesn't yet support import_step
    # (older bridge DLL) or if some parts have no STEP export.
    if output_format in ("step", "auto"):
        all_have_step = all(p.step_bytes for p in cq_result.parts)
        if all_have_step and bridge_callback is not None:
            step_dispatch = await _try_step_dispatch(cq_result, description, bridge_callback)
            if step_dispatch is not None:
                # Annotate with bbox + svg_preview + cadquery diagnostics, same as STL path.
                _annotate_response(step_dispatch, cq_result, description, mode="step",
                                   per_part_diag=[
                                       {"name": p.name,
                                        "color_rgb": list(p.color_rgb) if p.color_rgb else None,
                                        "step_bytes": len(p.step_bytes)}
                                       for p in cq_result.parts
                                   ])
                return step_dispatch
            if output_format == "step":
                # User explicitly asked for STEP and bridge couldn't handle it.
                # Tell Gemini honestly so she can retry with output_format="stl".
                logger.info("family_generate_complex: STEP dispatch unsupported by bridge; falling back to STL")

    # Step 2 — parse STL for each part. Build (name, triangles, color) tuples.
    parts_for_render: list[tuple[str, list[Triangle], tuple[float, float, float] | None]] = []
    total_triangles = 0
    per_part_diag: list[dict[str, Any]] = []

    for cq_part in cq_result.parts:
        try:
            tris = parse_stl(cq_part.stl_bytes)
        except ValueError as e:
            return {"error": True, "message": f"STL parse failed for part {cq_part.name!r}: {e}", "kind": "runtime"}

        if not tris:
            logger.warning("CadQuery part %r has 0 triangles — skipping", cq_part.name)
            continue
        total_triangles += len(tris)
        if total_triangles > MAX_OUTPUT_TRIANGLES:
            return {
                "error": True,
                "message": (
                    f"Combined mesh has {total_triangles} triangles (cap "
                    f"{MAX_OUTPUT_TRIANGLES}). Increase tolerance "
                    f"(currently {tolerance}mm) or simplify."
                ),
                "kind": "oversize",
            }
        parts_for_render.append((cq_part.name, tris, cq_part.color_rgb))
        per_part_diag.append({
            "name": cq_part.name,
            "triangle_count": len(tris),
            "color_rgb": list(cq_part.color_rgb) if cq_part.color_rgb else None,
        })

    if not parts_for_render:
        return {
            "error": True,
            "message": "CadQuery produced 0 triangles total — your code likely created an empty Compound.",
            "kind": "no_result",
        }

    # Step 3 — synthesise multi-part C# (one DirectShape per part with per-element colour).
    cs_code = _render_multi_part_directshape_cs(parts_for_render, description)
    logger.info(
        "family_generate_complex: cadquery %.2fs → %d parts → %d triangles → %d bytes C#",
        cq_result.duration_s,
        len(parts_for_render),
        total_triangles,
        len(cs_code),
    )

    bridge_result = await _dispatch_code(
        cs_code,
        bridge_callback,
        timeout_ms=_COMPOSITE_TIMEOUT_MS,
    )

    # Annotate bridge response with bbox + SVG preview + cadquery diagnostics.
    if isinstance(bridge_result, dict):
        _annotate_response(bridge_result, cq_result, description, mode="stl",
                           per_part_diag=per_part_diag)
        bridge_result.setdefault("cadquery", {})
        if isinstance(bridge_result["cadquery"], dict):
            bridge_result["cadquery"]["total_triangles"] = total_triangles
    return bridge_result


async def _try_step_dispatch(
    cq_result,                              # CadQueryResult (avoid forward-import noise)
    description: str,
    bridge_callback: BridgeCallback,
) -> Optional[dict[str, Any]]:
    """Attempt STEP-based import via bridge `import_step` method.

    Returns the bridge response dict on success, or None when:
      - The bridge doesn't yet implement `import_step` (older DLL).
      - The bridge returns an error response (active Revit lacks STEP support).

    Callers that get None fall back to STL+TessellatedShape via execute path.
    """
    params = {
        "description": description[:120],
        # Per-part: {name, step_base64, color_rgb_0_1 or None}
        "parts": [
            {
                "name": p.name,
                "step_base64": base64.b64encode(p.step_bytes).decode("ascii"),
                "color_rgb": list(p.color_rgb) if p.color_rgb else None,
                "material_hint": p.material_hint or "",
            }
            for p in cq_result.parts
        ],
    }
    try:
        result = await bridge_callback("import_step", params)
    except Exception as e:  # noqa: BLE001
        logger.info("import_step bridge call failed (likely DLL doesn't support it yet): %s", e)
        return None

    if not isinstance(result, dict):
        return None
    # Bridge convention for unknown methods: error=True with hint like "unknown method".
    if result.get("error") is True:
        msg = str(result.get("message", "")).lower()
        if "unknown" in msg or "not supported" in msg or "not implemented" in msg:
            return None
        # Real error — surface it back so caller can decide.
        return result
    return result


def _annotate_response(
    bridge_result: dict[str, Any],
    cq_result,
    description: str,
    mode: str,                              # "stl" | "step"
    per_part_diag: list[dict[str, Any]],
) -> None:
    """Mutate bridge_result with bbox + SVG preview + cadquery diagnostics.

    Same payload regardless of STL vs STEP path so Phase 4 self-review and
    Gemini's next-round multimodal vision see the same shape.
    """
    bbox = cq_result.bbox_mm
    bridge_result["bbox_mm"] = {
        "x": list(bbox[0]),
        "y": list(bbox[1]),
        "z": list(bbox[2]),
        "size_mm": [bbox[0][1] - bbox[0][0], bbox[1][1] - bbox[1][0], bbox[2][1] - bbox[2][0]],
    }
    bridge_result["parts_summary"] = per_part_diag
    bridge_result["dispatch_mode"] = mode
    if cq_result.svg_preview:
        svg_b = cq_result.svg_preview[:200_000]
        bridge_result["svg_preview_base64"] = base64.b64encode(svg_b).decode("ascii")
        bridge_result["svg_preview_format"] = "image/svg+xml"
    bridge_result.setdefault("cadquery", {})
    if isinstance(bridge_result["cadquery"], dict):
        bridge_result["cadquery"].update({
            "duration_s": round(cq_result.duration_s, 3),
            "part_count": len(cq_result.parts),
            "stdout_tail": cq_result.stdout[-400:],
            "step_available_per_part": [bool(p.step_bytes) for p in cq_result.parts],
        })


def _hint_for(kind: str) -> str:
    """Targeted hints surfaced back to Gemini for self-correction."""
    hints = {
        "syntax":   "Check Python syntax / indentation.",
        "runtime":  "Read the traceback. Common: missing import (only `cq` is imported by default; add `from cadquery import Workplane` etc. if you need other names), wrong shape combination.",
        "timeout":  "Reduce shape complexity or raise timeout_s up to 300.",
        "oversize": "Raise the `tolerance` argument (e.g. 0.5 → coarser mesh) or simplify the model. Cap is 10MB STL / 100K triangles.",
        "no_result": "Assign the final Workplane/Shape to a variable named `result`, e.g. `result = cq.Workplane('XY').box(100,100,100)`.",
    }
    return hints.get(kind, "")
