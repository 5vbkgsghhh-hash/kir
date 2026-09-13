"""shape_emit — emission of create_directshape (a paired file to ops_shape.py,
exactly as arch_emit.py pairs with ops_arch.py and struct_emit.py with
ops_struct.py).

Its own wave zone: this module touches no other ops_*.py and no other
*_emit.py. authoring.py gets an additive import and one line in _EMITTERS —
the same minimal seam through which the framing and AR waves were plugged in.

Reused from authoring.py UNCHANGED (by import, not by copy): _cs, _safe,
_stamp_block, _stamp_readback. All Revit API names were taken from a
measurement on the live compile service (:52412, 2021-2026, 29.07) — the
measurement table is in the header of ops_shape.py.

THE SHAPE OF THE EMISSION AND WHY EXACTLY THIS ONE. The vertex array is
written out ONCE, the triangles as an array of integer indices, the faces are
assembled by a loop:

    XYZ[] __vx_S = new XYZ[] { P(...), ... };      // each vertex once
    int[] __tx_S = new int[] { i, j, k, ... };     // 3 numbers per face
    for (...) __tb_S.AddFace(new TessellatedFace(new List<XYZ>{ ... }, ...));

The straightforward alternative — writing out three points for every face —
triples the source (a vertex of a closed mesh belongs to six faces on
average) and, more importantly, LOSES structure: such C# no longer shows
where the input ends and its unrolling begins. In the current shape, the
emitted C# contains exactly the two arrays that were in the IR, so parsing
the emission back is exact byte for byte, not approximate (see
parse_emitted_mesh below and the round-trip test).

Size measurement (same service, 2021 and 2026) — linear, with no cliff: 1,600
triangles = 49 KB / 26 ms, 12,544 = 412 KB / 187 ms. The registry limit
MAX_TRIANGLES=4096 was taken from this measurement with margin; the number's
derivation is in the header of mesh.py.

TARGET=MESH / FALLBACK=SALVAGE — AND WHY NOT ABORT, EVEN THOUGH ABORT WAS THE
WANTED ONE.

The first draft of this emitter set Target=Mesh and Fallback=Abort by
straightforward reasoning: Salvage ("use all SUITABLE data") is literally a
silent truncation of the input, some faces will silently fail to arrive, the
element will appear, and from outside this looks like success; Abort, on the
other hand, promised a loud refusal. The reasoning was sound, the conclusion
was not.

The Roslyn gate on this pair is GREEN 6/6: the enums exist, the properties
exist, the C# compiles on all six versions. But in RevitAPI.xml of the
reference package, in the remark on TessellatedShapeBuilder.Build, verbatim
(checked in 2021 and in 2026 — the text is identical):

    Currently only "Solid/Abort", "AnyGeometry/Mesh" and "Mesh/Salvage"
    target/fallback combinations are supported.

That is, Mesh/Abort is NOT a supported combination, and we would have found
this out on the first live run, not at compile time. Exactly the class of bug
that names here are checked against by measurement for: it compiled does not
mean it will build.

There are three supported pairs, and choosing among them is, again, a matter
of honesty:

  * Solid/Abort      — requires a closed body; an open shell (and that's half
                       of meaningful meshes) would be rejected;
  * AnyGeometry/Mesh — Revit decides itself whether it's a solid or a mesh,
                       and the difference is invisible from outside, even
                       though the meaning of the result differs;
  * Mesh/Salvage     — always a mesh, but Salvage stays silent about what it
                       dropped.

Mesh/Salvage was chosen, and Salvage's silence is closed not by hope but by a
witness: the face-count check reads Mesh.NumTriangles off the BUILT element
and compares it against the number of submitted triangles. If Salvage dropped
even one face, the postcondition fails, the transaction rolls back, the user
sees a named refusal. Where the API cannot fail loudly, the witness provides
the loudness; that is the division of labor the compiler stands on.

That is why the face-count witness here is LOAD-BEARING, not decoration:
removing it would mean bringing back the silent truncation.

THE SURFACE WITNESS (09.08.2026) — THE SECOND HALF OF THE SAME CLOSURE.

The face count catches a Salvage that DROPPED a face. It is blind to a
Salvage that REASSEMBLED a face: a reassembly that kept the count and moved a
vertex passed both the bounding-box check (±5 mm is held by the extreme
points) and the counter. The gap's size was measured on this same emitter: an
interior vertex of a 2×2 grid mesh can be moved by 400 mm — the bounding box
won't budge, the face count won't change, both previous witnesses stay
SILENT.

An exact predicate has existed since day one of Tier-G and was proven live —
``decompile/geometry_acceptance.py`` (quantization on ``GEOM_CANON_MM``, a
multiset of triangles, independent of vertex numbering, face order, and
winding). The idempotence rig reads the BUILT element with it, in a separate
post-commit read. The authoring branch called it through NOT A SINGLE import.

Now it does — and inside the transaction, because outside it a mismatch can
only be described, while inside it can be rolled back.

WHAT IS COMPARED IS THE PREIMAGE, NOT A HASH, AND THIS IS A MEASUREMENT, NOT
A TASTE. Live compile service (:52412, 09.08.2026, 2021-2026):

    System.Security.Cryptography.SHA256.Create()          4/6
        2025, 2026: CS1069 'SHA256' ... has been forwarded to assembly
                    'System.Security.Cryptography' — the assembly is not in
                    the closure
    System.Security.Cryptography.SHA256Managed            4/6  (same CS1069)
    SHA256.HashData(byte[])                               0/6
    Mesh.NumTriangles / Mesh.get_Triangle(int)            6/6
    MeshTriangle.get_Vertex(int) / Mesh.Vertices          6/6
    List<long[]>.Sort(Comparison<long[]>)                 6/6
    long.ToString(CultureInfo.InvariantCulture)           6/6

A hash in the emitted C# is impossible on two of the six shipped versions
(``tests/bridge_reference_closure.py`` already recorded the same asymmetry
about MD5). So Python pre-registers the PREIMAGE of the digest, and C# builds
the same one from the built element and compares the strings. Preimage
equality is strictly stronger than hash equality, the canonicalizer in the
code stays SINGLE, and there is not one instance here of the degradation
"we'll check more loosely on 2025/2026".

COST, MEASURED (emission of one op, 2026, atomic; n×n grid):

    triangles  C# was    C# now    growth
         8      7,906     11,952   1.51x
       128     10,971     20,273   1.85x
       512     21,547     48,603   2.26x
     2,048     64,508    163,618   2.54x
     4,050    125,720    319,272   2.54x

That is, ~48 bytes per triangle on top plus 2,097 bytes of declarations ONCE
per program. Roslyn did not notice: 4,050 triangles compile in 99-206 ms on
all six versions (was 82-354 ms without the witness — the service's spread is
wider than the effect). The lazy import of ``geometry_acceptance`` costs
0.138 s ONCE per process, and only for programs with a mesh.

The surface witness reads the SAME ``__ge_`` as the face-count witness: two
postconditions on one element must judge one and the same reading of the
geometry.
"""
from __future__ import annotations

from kir.emit_core import (  # noqa: F401
    _cs, _safe, _stamp_block, _stamp_readback, element_identity_readback_cs,
)
from kir.diag import Diagnostic, KirRefusal
from kir.emit_model import WitnessCheck
from kir.emit_utils import cs_line_comment_fragment, refuse_stmt
from kir.mesh import MESH_DEGENERATE, mesh_bbox
from kir.ops_shape import DIRECTSHAPE_CATEGORIES

#: A short label in ALL_MODEL_MARK. Comments is taken by the A5 ownership
#: stamp (_stamp_block), so the human-readable label rides in Mark — and
#: ONLY if the field is empty: overwriting someone else's value for the sake
#: of our own stamp would mean starting with exactly the silent edit all of
#: this was written against.
HONEST_MARK = "KIR DirectShape: геометрия без BIM-смысла (нет типа/параметров)"


#: Decimal places in the vertex literal (see :func:`_xyz_literals`). A
#: LOAD-BEARING NUMBER, not formatting: the surface expectation must be
#: computed from EXACTLY these values, because it is exactly these that go to
#: Revit. Computing it from the raw input would mean planting a 0.005 mm
#: mismatch between the expectation and the mesh actually sent — and on a
#: 0.5 mm grid such a mismatch flips the cell for any coordinate that landed
#: closer than 0.005 mm to its boundary (≈2% of random coordinates), i.e. it
#: would produce FALSE refusals on correctly built meshes.
_EMITTED_DECIMALS = 2


#: Millimeters per foot — EXACTLY, by the definition of the inch. Not an
#: approximation: Revit holds all lengths in internal feet, and
#: `UnitUtils.ConvertToInternalUnits` divides by exactly this number.
_FEET_MM = 304.8


def _as_revit_stores(mm: float) -> float:
    """The value in the form Revit will RETURN it, not the form we sent it in.

    🔴 WHY, MEASURED 20.08.2026, AND THIS IS THE SECOND LAYER OF ONE DEFECT.
    The neighboring `_EMITTED_DECIMALS` already closed the first layer: the
    expectation is computed not from the raw input but from the PRINTED
    value, because it is exactly that which goes to Revit. What went
    unnoticed was that Revit does not store what we printed: it holds mesh
    vertices in SINGLE precision, and on the way back returns a different
    number.

    The model was confirmed LIVE, three values out of three, down to the last
    digit (Revit 2026, "Проект1", reading `Mesh.get_Triangle` via
    `get_Geometry`):

        printed      Revit returned   model float32(mm/foot)*foot
        40345.75     40345.751        40345.751294
        12345.75     12345.750        12345.749918
        40488.97     40488.970        40488.970459

    WHY THIS BROKE THE WITNESS. The canon snaps a coordinate onto a 0.5 mm
    grid by rounding HALF AWAY FROM ZERO. Printing has a quantum of 0.01 mm,
    i.e. a cell boundary (0.25 mm) is exactly reachable by the printed
    number. Python would round such a coordinate UP, while Revit, returning
    it a fraction of a micron lower, would force C# to round it DOWN — and
    the signatures diverged. Measured on the director's "apple" sample (1190
    vertices, 2376 triangles): **27 vertices out of 1190**, i.e. a guaranteed
    rollback of CORRECTLY BUILT geometry.

    ⚠️ WHY NOT "SHIFT THE GRID", even though that's the first thing that
    comes to mind, and it's exactly what was proposed. An odd number of
    quanta per cell makes landing on the boundary impossible, and on the
    apple sample, 37 m from the origin, it gives zero. But the margin there is
    half a quantum, 0.005 mm, and single-precision error GROWS WITH the
    MAGNITUDE of the coordinate, reaching 0.008 mm at 180 m. Re-measured on
    the same run: the odd grid at 180 m gives **12 mismatches out of 1190**,
    i.e. it only cures the case near zero. Plus the grid itself is
    `GEOM_CANON_MM`, the FROZEN grid of Tier-G's content-addressed store;
    changing it would devalue the store. The storage model is exact at any
    distance and touches no shared quantity.

    THE BOUNDARY, NAMED HONESTLY: this is a MODEL of someone else's storage,
    derived from three live values, not a documented Autodesk contract. It is
    pinned by those very three numbers (`test_mesh_witness_storage_model.py`);
    if Revit ever starts storing vertices differently, the test will be the
    first to name it, and the witness will start failing again on correct
    geometry — and that will be a LOUD refusal, not a silent untruth.
    """
    import struct

    feet = float(mm) / _FEET_MM
    stored = struct.unpack("<f", struct.pack("<f", feet))[0]
    return float(stored) * _FEET_MM


def _emitted_vertices(verts: list) -> list:
    """Vertices in the form Revit will RETURN them when reading back the built
    element.

    Two stages, both mandatory: first, printing with `_EMITTED_DECIMALS`
    (exactly this goes into the C#), then single-precision mesh storage
    (:func:`_as_revit_stores`). The witness compares ITS OWN expectation
    against what was read from the model, so the expectation must travel the
    same road in full.
    """

    return [[_as_revit_stores(round(v[0], _EMITTED_DECIMALS)),
             _as_revit_stores(round(v[1], _EMITTED_DECIMALS)),
             _as_revit_stores(round(v[2], _EMITTED_DECIMALS))] for v in verts]


def _xyz_literals(verts: list) -> str:
    return ", ".join(
        f"P({round(v[0], _EMITTED_DECIMALS)}, {round(v[1], _EMITTED_DECIMALS)}, "
        f"{round(v[2], _EMITTED_DECIMALS)})"
        for v in verts)


def _surface_expectation(oid: str, verts: list, tris: list) -> tuple[str, str, str]:
    """(expected preimage, shell head, shell tail) for the witness.

    Computed by the SAME canonicalizer as the live post-commit predicate of
    Tier-G — ``decompile.geometry_acceptance``. The import is lazy: the
    decompile package pulls in ~0.57 s (measured 09.08), and the authoring
    branch is not obligated to pay it for programs without a mesh.

    A REFUSAL, NOT A DEGRADATION. Rounding to hundredths can COLLAPSE a long
    thin triangle that passed mesh.py's laws (min edge 1 mm, min area 1 mm² —
    they let through a needle with a 1 m base and a 2e-6 mm height). Such a
    mesh already ships to Revit today as a degenerate face; leaving it
    silently without a surface witness would mean bringing back exactly the
    silent truncation this emitter is written against, so here there is a
    typed refusal tied to the op.
    """
    from kir.decompile.geometry_acceptance import (   # lazy: see above
        mesh_surface_payload, surface_payload_envelope,
    )
    from kir.decompile.recompile import GmMesh, GeometrySchemaError

    try:
        gm = GmMesh(
            vertices_mm=tuple(tuple(v) for v in verts),
            triangles=tuple(tuple(t) for t in tris),
        )
    except GeometrySchemaError as exc:
        raise KirRefusal([Diagnostic(
            code=MESH_DEGENERATE, op_id=oid, field_name="mesh",
            message_ru=(
                f"меш нельзя подписать свидетелем поверхности: в эмиссии "
                f"координаты округляются до {_EMITTED_DECIMALS} знаков, и "
                f"после округления грань вырождается ({exc}). Такой меш "
                f"уехал бы в Revit вырожденной гранью — раздвинь вершины или "
                f"перестрой этот треугольник"))]) from exc
    head, tail = surface_payload_envelope()
    return mesh_surface_payload(gm), head, tail


def emit_directshape(op: dict, ver: str, stamp: str,
                     isolation: str = "atomic") -> tuple[str, str, list, str]:
    """Mesh -> DirectShape. There is no version axis: everything named here
    was measured 6/6.

    Returns (decl, create, checks, readback) — the package's emitter contract.
    """
    oid = op["id"]
    s = _safe(oid)
    mesh = op["mesh"]
    verts = mesh["vertices_mm"]
    tris = mesh["triangles"]
    member = DIRECTSHAPE_CATEGORIES[op["category"]]
    n_tris = len(tris)

    # DECLARATIONS — IN THE OUTER SCOPE. With isolation="per_op" the creation
    # block and the postcondition/receipt blocks fall into DIFFERENT scopes,
    # and a variable declared inside create is invisible to the witness
    # (CS0103 — the exact seam the first version of the enclosures emitter
    # already failed on).
    decl = (f"DirectShape __el_{s} = null;\n"
            f"bool __lbl_{s} = false;\n"
            f"string __out_{s} = null;")

    idx = ", ".join(str(i) for t in tris for i in t)
    create = (
        f"// create_directshape {cs_line_comment_fragment(oid)} — "
        f"{len(verts)} вершин, {n_tris} треугольников\n"
        f"ElementId __cat_{s} = new ElementId(BuiltInCategory.{member});\n"
        # The category is checked ON THE DOCUMENT, not against our table: the
        # category can be turned off in the project template, and then
        # CreateElement will return null already after we've decided
        # everything is fine.
        f"if (!DirectShape.IsValidCategoryId(__cat_{s}, doc)) {{ "
        f"{refuse_stmt(oid, _cs('категория недопустима для DirectShape в этом документе'), isolation)} }}\n"
        f"XYZ[] __vx_{s} = new XYZ[] {{ {_xyz_literals(verts)} }};\n"
        f"int[] __tx_{s} = new int[] {{ {idx} }};\n"
        f"TessellatedShapeBuilder __tb_{s} = new TessellatedShapeBuilder();\n"
        f"__tb_{s}.OpenConnectedFaceSet(false);\n"
        f"for (int __i_{s} = 0; __i_{s} < __tx_{s}.Length; __i_{s} += 3)\n{{\n"
        f"    __tb_{s}.AddFace(new TessellatedFace(new List<XYZ> {{ "
        f"__vx_{s}[__tx_{s}[__i_{s}]], __vx_{s}[__tx_{s}[__i_{s} + 1]], "
        f"__vx_{s}[__tx_{s}[__i_{s} + 2]] }}, ElementId.InvalidElementId));\n}}\n"
        f"__tb_{s}.CloseConnectedFaceSet();\n"
        # A pair taken exactly from the supported ones (RevitAPI.xml, Build):
        # Mesh/Salvage. Salvage's silence is closed by the face-count witness
        # — see the header.
        f"__tb_{s}.Target = TessellatedShapeBuilderTarget.Mesh;\n"
        f"__tb_{s}.Fallback = TessellatedShapeBuilderFallback.Salvage;\n"
        f"__tb_{s}.Build();\n"
        f"TessellatedShapeBuilderResult __tr_{s} = __tb_{s}.GetBuildResult();\n"
        f"__out_{s} = __tr_{s}.Outcome.ToString();\n"
        f"if (__tr_{s}.Outcome == TessellatedShapeBuilderOutcome.Nothing) {{ "
        f"{refuse_stmt(oid, _cs('Revit не построил тело из этого меша (Outcome=Nothing)'), isolation)} }}\n"
        f"__el_{s} = DirectShape.CreateElement(doc, __cat_{s});\n"
        f"if (__el_{s} == null) {{ "
        f"{refuse_stmt(oid, _cs('создание DirectShape вернуло null'), isolation)} }}\n"
        f"__el_{s}.SetShape(__tr_{s}.GetGeometricalObjects());\n"
        f"__el_{s}.Name = {_cs(op['name'])};\n"
        # A LABEL IN THE MODEL ITSELF. get_Parameter returns null if the
        # element has no such parameter — then there simply will be no label,
        # and the receipt will say so honestly (false), not stay silent about
        # it. A non-empty foreign value is never touched.
        f"Parameter __mk_{s} = __el_{s}.get_Parameter(BuiltInParameter.ALL_MODEL_MARK);\n"
        f"if (__mk_{s} != null && !__mk_{s}.IsReadOnly && "
        f"string.IsNullOrEmpty(__mk_{s}.AsString()))\n"
        f"    __lbl_{s} = __mk_{s}.Set({_cs(HONEST_MARK)});\n"
        + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))

    from kir.emit_model import tolerance
    tol = tolerance("create_directshape", "bbox_mm")
    surf_tol = tolerance("create_directshape", "surface_canon_mm")
    xmin, ymin, zmin, xmax, ymax, zmax = mesh_bbox(verts)
    # THE EXPECTATION IS PRE-REGISTERED BEFORE ANY EFFECT and is computed
    # EXACTLY from the vertices that will go into the C# (see
    # _emitted_vertices). This is exactly what makes the check independent
    # rather than self-confirming: Python builds the "expectation" side,
    # Revit builds the "observation" side, and they can only match if what
    # was built is what was sent.
    surf_expected, surf_head, surf_tail = _surface_expectation(
        oid, _emitted_vertices(verts), tris)

    checks: list[WitnessCheck] = [
        # BOUNDING BOX ON ALL THREE AXES. The shared bbox_extents_witness
        # checks only XY — it was written for floors, where Z sets the
        # level. For a mesh, Z is as full an input coordinate as X and Y, and
        # a witness silent about it would be signing off on geometry it never
        # looked at (§18.3).
        WitnessCheck(
            obligation_key="bbox",
            reader_cs=f"    var __bb_{s} = __el_{s}.get_BoundingBox(null);\n",
            verdict_cs=(
                f"    if (__bb_{s} == null) __post.Add({_cs(oid + ': нет BoundingBox')});\n"
                f"    else if (Math.Abs(MM(__bb_{s}.Min.X) - {round(xmin, 2)}) > {tol} || "
                f"Math.Abs(MM(__bb_{s}.Max.X) - {round(xmax, 2)}) > {tol} ||\n"
                f"             Math.Abs(MM(__bb_{s}.Min.Y) - {round(ymin, 2)}) > {tol} || "
                f"Math.Abs(MM(__bb_{s}.Max.Y) - {round(ymax, 2)}) > {tol} ||\n"
                f"             Math.Abs(MM(__bb_{s}.Min.Z) - {round(zmin, 2)}) > {tol} || "
                f"Math.Abs(MM(__bb_{s}.Max.Z) - {round(zmax, 2)}) > {tol})\n"
                f"        __post.Add({_cs(oid + ': bbox extents mismatch (geometry)')});\n"),
            message="bbox extents mismatch (geometry)",
            tol=tol, style="else_block"),
        # THE FACE COUNT IS READ OFF THE BUILT ELEMENT. This is not a
        # recount of our own input: get_Geometry returns what Revit actually
        # put into the element. If it reassembles the triangulation (merges
        # coplanar faces), the witness will REFUSE — loudly and with numbers,
        # not silently. This has not yet been checked live; the direction of
        # the refusal was chosen so that unknown behavior shows up as noise,
        # not as silence.
        WitnessCheck(
            obligation_key="triangles",
            reader_cs=(f"    int __tc_{s} = 0;\n"
                       f"    var __ge_{s} = __el_{s}.get_Geometry(new Options());\n"),
            verdict_cs=(
                f"    if (__ge_{s} == null) __post.Add({_cs(oid + ': построенная геометрия не читается (geometry)')});\n"
                f"    else\n    {{\n"
                f"        foreach (GeometryObject __go_{s} in __ge_{s})\n        {{\n"
                f"            Mesh __ms_{s} = __go_{s} as Mesh;\n"
                f"            if (__ms_{s} != null) __tc_{s} += __ms_{s}.NumTriangles;\n"
                # THE SAME BLINDNESS AS THE SURFACE WITNESS HAS, AND FIXED
                # TOGETHER WITH IT: a closed shell arrives as `Solid`, and the
                # mesh counter would count ZERO on correct geometry. A flat
                # triangular face gives exactly one triangle, so the count
                # matches the authored one exactly, not approximately.
                f"            Solid __ss_{s} = __go_{s} as Solid;\n"
                f"            if (__ss_{s} != null)\n"
                f"                foreach (Face __sf_{s} in __ss_{s}.Faces)\n"
                f"                {{ try {{ var __sm_{s} = __sf_{s}.Triangulate();\n"
                f"                          if (__sm_{s} != null) __tc_{s} += __sm_{s}.NumTriangles; }} catch {{ }} }}\n"
                f"        }}\n"
                f"        if (__tc_{s} != {n_tris})\n"
                f"            __post.Add({_cs(oid + f': built mesh triangle count != {n_tris} (geometry)')});\n"
                f"    }}\n"),
            message="built mesh triangle count mismatch (geometry)",
            style="guard"),
        # THE WHOLE SURFACE, NOT ITS COUNT. The face-count witness closes
        # Salvage's silence only halfway: a reassembly that kept the COUNT and
        # moved a vertex passes it silently, and from outside this looks like
        # success. An exact predicate already existed and was proven live —
        # the same `mesh_surface_payload` the idempotence rig uses to read the
        # built element with a SEPARATE post-commit read. Before 09.08 it was
        # wired into the authoring branch by not a single import.
        #
        # THE SAME __ge_{s} IS READ as for the face count, and this is a
        # LOAD-BEARING choice, not an economy: two witnesses of one element
        # must judge ONE read of the geometry, otherwise "this many faces" and
        # "this is the surface" could end up referring to different reads.
        # The order of checks in this list is therefore mandatory — held by a
        # test.
        WitnessCheck(
            obligation_key="surface",
            reader_cs=(
                f"    string __csf_{s} = null;\n"
                f"    if (__ge_{s} != null)\n    {{\n"
                f"        var __csr_{s} = new List<long[]>();\n"
                f"        foreach (GeometryObject __csg_{s} in __ge_{s})\n        {{\n"
                # 🔴 A CLOSED SHELL COMES BACK AS A SOLID, NOT A MESH, AND A
                # WITNESS THAT ONLY READ `Mesh` WAS BLIND TO IT.
                #
                # Bought LIVE on 20.08.2026 on two shapes in a row — a torus
                # and an apple, both closed. `TessellatedShapeBuilder` with
                # `Target=Solid` stitches a closed set of faces into an
                # ACTUAL SOLID, and `get_Geometry` returns a `Solid`. Direct
                # probe:
                #
                #     built_kinds              Solid;
                #     read_back_solid_faces    2376   ← exactly our triangles
                #     read_back_mesh_triangles 0      ← but the witness looked
                #                                        HERE
                #
                # The signature came out empty, the surface "didn't match",
                # and the program rolled back. A FALSE FAILURE on correct
                # geometry — by the canon the most expensive outcome, because
                # it does not stay silent, it CONFIDENTLY denies.
                #
                # An open shell (a canopy, a bench) still comes back as a mesh
                # and is read by the old branch; both branches are needed, and
                # neither covers the other. A flat triangular face of a solid
                # gives exactly ONE triangle in `Triangulate()`, so the
                # multiset matches the authored one with no tolerance fudging
                # at all.
                f"            Solid __css_{s} = __csg_{s} as Solid;\n"
                f"            Mesh __csm_{s} = __csg_{s} as Mesh;\n"
                f"            var __csl_{s} = new List<Mesh>();\n"
                f"            if (__csm_{s} != null) __csl_{s}.Add(__csm_{s});\n"
                f"            else if (__css_{s} != null)\n"
                f"                foreach (Face __csfc_{s} in __css_{s}.Faces)\n"
                f"                {{ try {{ var __cstm_{s} = __csfc_{s}.Triangulate();\n"
                f"                          if (__cstm_{s} != null) __csl_{s}.Add(__cstm_{s}); }} catch {{ }} }}\n"
                f"            foreach (Mesh __csmm_{s} in __csl_{s})\n            {{\n"
                f"            for (int __csi_{s} = 0; __csi_{s} < __csmm_{s}.NumTriangles; __csi_{s}++)\n"
                f"            {{\n"
                f"                MeshTriangle __cst_{s} = __csmm_{s}.get_Triangle(__csi_{s});\n"
                f"                var __csp_{s} = new List<long[]>();\n"
                f"                for (int __csv_{s} = 0; __csv_{s} < 3; __csv_{s}++)\n"
                f"                {{\n"
                f"                    XYZ __csx_{s} = __cst_{s}.get_Vertex(__csv_{s});\n"
                f"                    __csp_{s}.Add(new long[] {{ "
                f"__KirCanonUnit(MM(__csx_{s}.X), {surf_tol}), "
                f"__KirCanonUnit(MM(__csx_{s}.Y), {surf_tol}), "
                f"__KirCanonUnit(MM(__csx_{s}.Z), {surf_tol}) }});\n"
                f"                }}\n"
                f"                __csp_{s}.Sort(__KirCanonCmp);\n"
                f"                long[] __csq_{s} = new long[9];\n"
                f"                for (int __csa_{s} = 0; __csa_{s} < 3; __csa_{s}++)\n"
                f"                    for (int __csb_{s} = 0; __csb_{s} < 3; __csb_{s}++)\n"
                f"                        __csq_{s}[__csa_{s} * 3 + __csb_{s}] = __csp_{s}[__csa_{s}][__csb_{s}];\n"
                f"                __csr_{s}.Add(__csq_{s});\n"
                f"            }}\n"
                f"            }}\n"
                f"        }}\n"
                f"        __csf_{s} = __KirCanonPayload(__csr_{s}, {_cs(surf_head)}, {_cs(surf_tail)});\n"
                f"    }}\n"),
            verdict_cs=(
                f"    if (__csf_{s} == null)\n"
                f"        __post.Add({_cs(oid + ': поверхность построенного меша не читается (geometry)')});\n"
                f"    else if (__csf_{s} != {_cs(surf_expected)})\n"
                f"        __post.Add({_cs(oid + ': built mesh surface differs from the authored surface on the canon grid (geometry)')});\n"),
            message="built mesh surface mismatch on the canon grid (geometry)",
            tol=surf_tol, style="guard"),
    ]

    # ITS OWN RECEIPT, NOT _readback_block: the shared block reports
    # LocationCurve and type_name, which a DirectShape does NOT HAVE BY
    # CONSTRUCTION, and it stays silent about the one thing that must be said
    # about it. The fields below are the label that reaches the user: not "we
    # built a building" but "we built a mesh, and here is what it doesn't
    # have".
    readback = (
        f"// witness {cs_line_comment_fragment(oid)}\n{{\n"
        f"    var __rb = new Dictionary<string, object>();\n"
        f"    try {{ __rb[\"id\"] = __el_{s}.Id.ToString(); }} catch {{ __rb[\"id\"] = null; }}\n"
        f"    __rb[\"name\"] = __el_{s}.Name;\n"
        f"    __rb[\"category\"] = {_cs(op['category'])};\n"
        f"    __rb[\"triangles\"] = {n_tris};\n"
        f"    __rb[\"vertices\"] = {len(verts)};\n"
        f"    __rb[\"kind\"] = \"direct_shape_mesh\";\n"
        # What Revit actually assembled (Mesh/Sheet/Solid/Mixed/Nothing).
        # Five members, not three; on the first live run this is the first
        # thing worth reading, and it costs one line.
        f"    __rb[\"build_outcome\"] = __out_{s};\n"
        f"    __rb[\"bim_semantics\"] = \"none\";\n"
        f"    __rb[\"has_type\"] = false;\n"
        f"    __rb[\"schedulable_as_building_element\"] = false;\n"
        f"    __rb[\"human_editable\"] = false;\n"
        f"    __rb[\"honest_label_written\"] = __lbl_{s};\n"
        f"    __rb[\"warning\"] = {_cs('DirectShape — геометрия без BIM-смысла: у элемента нет типа и параметров, в спецификации он не попадёт как строительный элемент, и вручную его не отредактировать. Это не стена/перекрытие/кровля, даже если выглядит похоже.')};\n"
        + _stamp_readback(f"__el_{s}")
        + element_identity_readback_cs(f"__el_{s}", revit_version=ver) +
        f"    __results[{_cs(oid)}] = __rb;\n}}")

    return decl, create, checks, readback


# ── reverse-parsing the EMISSION (offline round-trip) ───────────────────────

def parse_emitted_mesh(csharp: str, oid: str) -> dict:
    """Extracts the mesh back out of the emitted C#.

    Exists because the round-trip must close on the ARTIFACT, not on our
    intent: comparing the input against the same Python structure we emitted
    it from would mean checking a variable against itself. What's read here
    is exactly the text that will go to Revit.

    Returns {"vertices_mm", "triangles"}; raises ValueError if this op's
    arrays are not found in the text.
    """
    import re

    s = _safe(oid)
    vm = re.search(r"XYZ\[\] __vx_" + re.escape(s) + r" = new XYZ\[\] \{(.*?)\};",
                   csharp, re.S)
    tm = re.search(r"int\[\] __tx_" + re.escape(s) + r" = new int\[\] \{(.*?)\};",
                   csharp, re.S)
    if vm is None or tm is None:
        raise ValueError(f"в эмиссии нет массивов меша для опа {oid!r}")
    verts = [[float(c) for c in m]
             for m in re.findall(
                 r"P\(\s*(-?[\d.eE+]+),\s*(-?[\d.eE+]+),\s*(-?[\d.eE+]+)\s*\)",
                 vm.group(1))]
    flat = [int(x) for x in re.findall(r"-?\d+", tm.group(1))]
    tris = [flat[k:k + 3] for k in range(0, len(flat), 3)]
    return {"vertices_mm": verts, "triangles": tris}


#: WHAT THIS SPOKE EMITS — DECLARED HERE, NOT IN THE HUB (02.09.2026).
#: Previously the "op -> body" mapping lived in the hand-written
#: `authoring._EMITTERS`, with the body here, and a thin wrapper in the hub
#: tied them together (41 entries across 19 companions). Two records of one
#: fact in different files is a named defect of this tree; now there is ONE
#: record, and the hub QUERIES it.
EMITTERS = {
    "create_directshape": emit_directshape,
}
