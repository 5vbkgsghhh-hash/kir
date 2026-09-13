"""ops_surface — a SMOOTH SURFACE as an element (paired file to `surface.py`).

HOW THIS OPERATION DIFFERS FROM THE THREE NEIGHBORING ONES, AND WHY A
FOURTH IS NEEDED. The registry already has three doors to "shape without a
BIM role", and they do not substitute for one another:

    create_directshape       MESH: triangles. Any topology, but FACETED —
                             no amount of them expresses a smooth shell
    create_solid_extrusion   PARAMETRIC: a CONTOUR profile + a height
    create_solid_revolve     PARAMETRIC: a CONTOUR profile + an axis + an
                             angle

None of them expresses a doubly-curved surface given by a grid of control
points — i.e. exactly what a shell or a complex facade is made with in
Rhino and Grasshopper. This operation closes exactly this, and nothing
more.

WHAT THE RESULT LACKS — THE SAME AS THE MESH, AND SAID JUST AS LOUDLY.
`DirectShape` is geometry without BIM meaning: no type, no layer
parameters, it will not enter a schedule as a construction, a human will
not edit it by hand. This is a property of Revit, not our shortcoming, and
so the operation is obligated to say so itself — in the spec, in the
receipt, and as a label in the model itself.

THE CAPABILITY CELL is («create», «geometry»), not («create», «element»).
The temptation here is stronger than for the mesh: a smooth shell LOOKS
like a roof or a facade. It still has neither layers, nor joins, nor a
schedule entry. The categories are the SAME closed table
`DIRECTSHAPE_CATEGORIES` from `ops_shape.py`, by IMPORT, not by copy: two
tables that must match drift apart silently.

THE WITNESS READS THE RESULT, AND IT HAS FOUR LEVELS — see
`surface_emit.py`. The main one is READING BACK the control points from
the built face through
`ExportUtils.GetNurbsSurfaceDataForSurface`, i.e. with the same instrument
the compiler's reverse pass uses to read them. This closes the round trip,
and makes the check capable of failing.
"""
from __future__ import annotations

from kir.registry_base import *  # noqa: F401,F403 (OpSpec/ParamSpec/...)
from kir.ops_shape import DIRECTSHAPE_CATEGORIES

OPS = [
    # ── READING A SURFACE. A paired operation to `create_surface`; all
    # the shape refinement and the three rejected variants are in the
    # `surface_query.py` header.
    OpSpec(
        name="query_surface",
        effect=EffectKind.READ,
        result=RESULT_QUERY,
        family="query",
        params=(
            ParamSpec("target", "target", required=True),
            # A pair, not one number: a 5×0 grid is neither a grid nor a
            # refusal of one. Both are optional — then only the surface's
            # definition is returned, and this is a legitimate, frequent
            # case (edit and build).
            ParamSpec("u_count", "int", min_val=2, max_val=64),
            ParamSpec("v_count", "int", min_val=2, max_val=64),
        ),
        # The same capability cell as `query_inspect`, and deliberately
        # so: both operations LOOK AT THE ELEMENT and change nothing.
        # Introducing the pair («inspect», «geometry») would mean
        # expanding the capability table for the sake of one op, without
        # changing a single access decision.
        capability=(("inspect", "element"),),
        post=("result.faces == number of faces of the target element; "
              "when it is exactly 1: result.surface = the NURBS definition of "
              "that face in the SAME keys create_surface accepts, or null with "
              "surface_absence_ru when the face is not a NURBS surface; "
              "result.domain_uv = the face's own parametric domain; "
              "when u_count/v_count are given, result.samples = u_count*v_count "
              "rows of {uv_norm, uv_face, inside, point_mm, normal} read by "
              "Face.Evaluate/ComputeNormal/IsInside, with point_mm=null and "
              "sample_absence_ru where evaluation threw; "
              "when the element has any other face count: surface and samples "
              "are null and absence_ru names the count"),
    ),
    OpSpec(
        name="create_surface",
        effect=EffectKind.CREATE,
        result=RESULT_ELEMENT,
        family="authoring",
        params=(
            # A surface is ONE value, not seven parallel lists, for the
            # same reason a mesh is one: a degree without knots and knots
            # without points are not verifiable in principle, and separate
            # fields would allow the state "one exists, the other doesn't"
            # — exactly the class where absence turns into zero.
            ParamSpec("surface", "surface", required=True),
            ParamSpec("category", "enum", required=True,
                      choices=tuple(DIRECTSHAPE_CATEGORIES)),
            # The name is MANDATORY — the same argument as for the mesh:
            # for an element without a type, the name is the only thing
            # that distinguishes it from a nameless blob in the project
            # tree a year later.
            ParamSpec("name", "str", required=True, max_val=64),
        ),
        capability=(("create", "geometry"),),
        # What is promised is exactly what is checked, and every promise
        # reads the RESULT, not our call.
        # 🔴 THE PROMISE WAS REWRITTEN ON 20.08.2026 FOLLOWING A LIVE
        # MEASUREMENT — together with the witness, in one commit. The
        # caveat below ("if it reparametrizes the surface, the witness
        # will TURN RED... the first live run must confirm or refute
        # this") did its job: the run REFUTED it. A 4×4 ruled saddle of
        # degree 3×3 read back as 1×1 with four points — an exact folding
        # of the representation, the same geometry. The red here was
        # FALSE, and the promise of representation equality is withdrawn
        # as wrong in kind, not softened.
        post=("surface shell exists and Revit removed no faces "
              "(materialized or typed refusal); "
              "built face count == 1 (geometry); "
              "the built face is readable back as a NURBS surface (geometry); "
              "every sampled point of the authored surface lies on the built "
              "face within the emission coordinate quantum (geometry); "
              "when Revit preserved the representation, read-back control "
              "points == authored control points within the same quantum "
              "(geometry)"),
        writes_model=True,
        # EMPTY, AND THAT IS MEANINGFUL: DirectShape has no type, so there
        # is neither a pool nor grounding — just as with
        # `create_directshape`.
        grounded=(),
        # THERE IS ONE TOLERANCE, AND IT IS DERIVED, NOT ASSIGNED. Control
        # points travel into C# printed with `EMIT_DECIMALS` digits, so
        # our own side of the comparison already differs from the ideal
        # one by no more than the printing quantum. Reading back with a
        # larger tolerance would mean forgiving Revit a discrepancy we
        # have not measured; reading with a smaller one would mean turning
        # red on our own rounding.
        #
        # 🔴 WHAT THIS TOLERANCE DOES NOT KNOW is stated here, not passed
        # over in silence: whether Revit accepts the control points
        # WITHOUT RECOMPUTING them cannot be checked offline at all. If it
        # reparametrizes the surface or inserts knots, the witness will
        # TURN RED — and this is the chosen direction of failure: let
        # unknown behavior show up as noise, not silence. The first live
        # run must confirm or refute this, and then the tolerance will get
        # a measurement instead of a derivation.
        tolerances={"control_point_mm": 0.01},
    ),
]
