"""ops_mep — MEP single-element ops (duct/cable-tray/conduit/flex/placeholder);
systems live in ops_connect.

Registry module — see REGISTRY_MODULES.md. Add ops HERE, not in spec.py.

────────────────────────────────────────────────────────────────────────────
THE ELECTRICAL/FLEX/PLACEHOLDER WAVE (2026-08-09) — WHAT WAS MEASURED, AND WHAT WAS REJECTED
────────────────────────────────────────────────────────────────────────────

Before this wave, everything electrical below the cable tray and all
"flexible" engineering were BLIND: no op, no refusal, not even a mention.
`registry_base.KINDS` already knew the categories `OST_Conduit`,
`OST_FlexDuctCurves`, `OST_FlexPipeCurves` — that is, you could ask "how
many are there" but could not build even one. Five new operations close
exactly this gap.

All five descend from `MEPCurve : HostObject`, so their witness is the
same as the already-shipped `create_pipe`'s: an INDEPENDENT RE-READ of the
result (geometry + level binding + type), not a confirmation that the call
was made.

API SIGNATURES WERE TAKEN FROM THE REFERENCE ASSEMBLIES, NOT FROM MEMORY.
Every call shape was compiled by live Roslyn against the real
`RevitAPI.dll` 2021-2026 BEFORE the emitter was written
(`data/revit_api_db.json` has been proven incomplete and was not consulted
here):

  Electrical.Conduit.Create(Document, ElementId conduitType, XYZ start,
                            XYZ end, ElementId levelId)          6/6
  Plumbing.Pipe.CreatePlaceholder(Document, ElementId systemTypeId,
                            ElementId pipeTypeId, ElementId levelId,
                            XYZ start, XYZ end)                  6/6
  Mechanical.Duct.CreatePlaceholder(… the same …)                6/6
  Mechanical.FlexDuct.Create(Document, ElementId systemTypeId,
                            ElementId ductTypeId, ElementId levelId,
                            IList<XYZ> points)                   6/6
  Plumbing.FlexPipe.Create(… the same …)                         6/6
  Pipe.IsPlaceholder / Duct.IsPlaceholder (bool)                 6/6
  FlexDuct.Points / FlexPipe.Points (IList<XYZ>)                 6/6
  Electrical.ConduitType / Mechanical.FlexDuctType /
  Plumbing.FlexPipeType (classes for the pools)                  6/6

THE ARGUMENT ORDER FOR CONDUIT IS DIFFERENT, and this is not a trifle: in
`Conduit.Create` the level comes LAST (as in `CableTray.Create`), while for
`Pipe`/`Duct`/`FlexDuct`/`FlexPipe` it comes THIRD/FOURTH, before the
points. Mixing them up is `CS1503` at the gate, not a silent error, but
pinning down the order here is cheaper than relearning it.

────────────────────────────────────────────────────────────────────────────
REJECTED: `create_wire` (Electrical.Wire.Create) — DELIBERATELY, NOT FORGOTTEN
────────────────────────────────────────────────────────────────────────────

The signature exists across all six versions and COMPILES with both
`null` connectors (checked with the same instrument):

  Wire.Create(Document, ElementId wireTypeId, ElementId viewId,
              WiringType, IList<XYZ> vertexPoints,
              Connector startConnectorTo, Connector endConnectorTo)

That is, a wire CAN be built WITHOUT connections, and its vertices can
even be read back (`NumberOfVertices` + `GetVertex(i)`, 6/6). There is
still no operation, and there are three reasons — each one checkable:

1. A CONNECTOR IS NOT ADDRESSABLE IN THIS LANGUAGE.
   `Autodesk.Revit.DB.Connector` is not an `Element`: it has no
   `ElementId`, it lives only inside its owner's `ConnectorManager`, and it
   does not survive a transaction. KIR's frozen reference dialect —
   `{"by": "name"|"element_id"|"ref", "value": …}` — can name ELEMENTS.
   There is NO WAY AT ALL to name "the third electrical connector of that
   panel over there" — not merely "inconvenient for now."

2. A WIRE WITH NO CIRCUIT IS EXACTLY THE SILENTLY-WRONG OUTCOME THIS
   COMPILER EXISTS TO PREVENT. With both `null`s, the element builds, the
   vertex witness is green, the routing is visible on the plan — while
   `Wire.GetMEPSystems()` is empty, and not a meter of cable will appear in
   the schedule. From the outside this is indistinguishable from a
   completed electrical section. A witness that signs off on geometry where
   the ENTIRE professional substance of the operation is missing is a
   showroom, not proof.

3. THE VERTICES HAVE NO THIRD COORDINATE. Autodesk states outright:
   "Vertices are projected to the view plane for comparison," and
   `AreVertexPointsValid` compares only X and Y. So a three-dimensional
   wire path is inexpressible by construction, and `viewId` (a plan or a
   ceiling plan only) is not decoration but part of the meaning.

What it would take to lift the refusal: an addressable connector (a
CONNECT extension — "connector k of the element created by op X," plus the
same language for existing equipment) and a live measurement of what reads
back for a CONNECTED wire. The decision is pinned by a test
(`tests/test_mep_electrical.py::WireIsDeliberatelyAbsent`), so the next
session does not silently ship a vacuous version.

────────────────────────────────────────────────────────────────────────────
WHAT DID NOT MAKE IT INTO `create_conduit`: `diameter_mm`
────────────────────────────────────────────────────────────────────────────

`RBS_CONDUIT_DIAMETER_PARAM` exists on all six versions, and writing
`Set(U(x))` plus a witness would be mechanically the same as
`create_duct`'s. This was NOT DONE, DELIBERATELY: a conduit's nominal
diameter is a TRADE SIZE (`RBS_CONDUIT_TRADESIZE`), an enumeration from a
type table, not a length drawn from a continuum. Revit snaps a value
outside the table to the nearest one in it, and the witness would honestly
fail on a CORRECTLY built conduit — the same price `create_duct` already
paid on a rectangular cross-section (measured 07-30), except here it would
be the norm, not the exception. There is no size table in the snapshot, so
there is nothing to refuse ON at compile time either. The law of
tolerances says: if it is not derivable, do not check it, and say so. Said.
"""
# 🔴 PROVENANCE WAS MOVED OUT OF THE DOCSTRING ON 2026-09-01 — THE DOOR
# VERSUS THE JOURNAL. A module docstring is a PUBLIC DOOR: `help()` prints
# it to the reader of a published package, and our machine's address tells
# them nothing. The knowledge is not erased — it lives here, in the
# journal, where it belongs:
#     the live Roslyn against which the signatures were checked — localhost:52412
from __future__ import annotations

from kir.registry_base import *  # noqa: F401,F403 (OpSpec/ParamSpec/DEFAULTS/LIST_*/...)

#: The endpoint tolerance for EVERY linear MEP op is 5 mm. The number is NOT
#: NEW: it is exactly the registered `create_pipe.endpoint_mm` ==
#: `create_duct` == `create_cable_tray`, and the match here is substantive,
#: not cosmetic. All of them read the SAME THING — `MEPCurve.Location as
#: LocationCurve`, i.e. the axis Revit returns itself — and none of them has
#: its own reason to diverge. Introducing a sixth number would mean
#: asserting that a conduit's axis is read differently from a pipe's; no
#: such measurement exists.
_MEP_ENDPOINT_MM = 5.0

OPS = [
    OpSpec(
            name="create_duct",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                ParamSpec("p0_mm", "pt_xyz", required=True),
                ParamSpec("p1_mm", "pt_xyz", required=True),
                ParamSpec("level", "sel", required=True,
                          ref_kinds=(ReferenceKind.LEVEL,)),
                ParamSpec("system_type", "sel"),   # omitted -> sole snapshot entry, else AMBIGUOUS
                ParamSpec("duct_type", "sel"),     # same rule
                ParamSpec("diameter_mm", "mm", min_val=50, max_val=3_000),
            ),
            capability=(("create", "mep_system"), ("create", "element")),
            post=("duct exists; LocationCurve endpoints == p0/p1 (±5mm, 3D); "
                  "reference level == resolved level (topology); "
                  "diameter param == diameter_mm (±0.5mm) when given"),
            writes_model=True,
            grounded=(("level", "levels", True),
                      ("system_type", "duct_system_types", False),
                      ("duct_type", "duct_types", False)),
            tolerances={"endpoint_mm": 5.0, "diameter_mm": 0.5},
        ),
    OpSpec(
            name="create_cable_tray",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                ParamSpec("p0_mm", "pt_xyz", required=True),
                ParamSpec("p1_mm", "pt_xyz", required=True),
                ParamSpec("level", "sel", required=True,
                          ref_kinds=(ReferenceKind.LEVEL,)),
                ParamSpec("tray_type", "sel"),     # omitted -> sole snapshot entry, else AMBIGUOUS
                # CableTrayType has no width/height API and CableTray.Create
                # has no sized overload (verified for Revit 2021-2026).  The
                # dimensions therefore belong to the instance operation.
                ParamSpec("width_mm", "mm", min_val=1),
                ParamSpec("height_mm", "mm", min_val=1),
            ),
            capability=(("create", "element"),),
            post=("cable tray exists; LocationCurve endpoints == p0/p1 (±5mm, 3D); "
                  "reference level == resolved level (topology); "
                  "width param == width_mm (±0.5mm) when given; "
                  "height param == height_mm (±0.5mm) when given"),
            writes_model=True,
            grounded=(("level", "levels", True),
                      ("tray_type", "cable_tray_types", False)),
            tolerances={"endpoint_mm": 5.0, "section_mm": 0.5},
        ),
    # ── ELECTRICAL: CONDUIT ─────────────────────────────────────────────────
    # The closest relative of cable tray: the same argument order (points,
    # then level) and the same witness. There is exactly one difference,
    # and it favors strictness — for conduit the TYPE is also checked:
    # `Conduit.Create` accepts `InvalidElementId` and in that case silently
    # falls back to the document's default type (documented by Autodesk
    # verbatim). ground.py never hands out such an id, but showing the
    # type read back is cheaper than trusting that it won't.
    OpSpec(
            name="create_conduit",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                ParamSpec("p0_mm", "pt_xyz", required=True),
                ParamSpec("p1_mm", "pt_xyz", required=True),
                ParamSpec("level", "sel", required=True,
                          ref_kinds=(ReferenceKind.LEVEL,)),
                ParamSpec("conduit_type", "sel"),  # omitted -> sole entry, else AMBIGUOUS
            ),
            capability=(("create", "element"),),
            post=("conduit exists; LocationCurve endpoints == p0/p1 (±5mm, 3D); "
                  "reference level == resolved level (topology); "
                  "conduit_type of the built element == resolved conduit_type "
                  "(semantic)"),
            writes_model=True,
            grounded=(("level", "levels", True),
                      ("conduit_type", "conduit_types", False)),
            tolerances={"endpoint_mm": _MEP_ENDPOINT_MM},
        ),
    # ── Placeholders ──────────────────────────────────────────────────────
    # An early stage: the route and system are named, there are no fittings
    # or cross-section yet. A cheap and useful operation, but its own
    # substance is exactly one bit, `IsPlaceholder`, and without it this
    # would be an ordinary pipe under another name. That is why the bit IS
    # READ BACK and signed off `(semantic)`.
    OpSpec(
            name="create_pipe_placeholder",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                ParamSpec("p0_mm", "pt_xyz", required=True),
                ParamSpec("p1_mm", "pt_xyz", required=True),
                ParamSpec("level", "sel", required=True,
                          ref_kinds=(ReferenceKind.LEVEL,)),
                ParamSpec("system_type", "sel"),
                ParamSpec("pipe_type", "sel"),
            ),
            capability=(("create", "mep_system"), ("create", "element")),
            post=("placeholder pipe exists; LocationCurve endpoints == p0/p1 "
                  "(±5mm, 3D); reference level == resolved level (topology); "
                  "IsPlaceholder of the built element (semantic); "
                  "pipe_type of the built element == resolved pipe_type "
                  "(semantic)"),
            writes_model=True,
            grounded=(("level", "levels", True),
                      ("system_type", "piping_system_types", False),
                      ("pipe_type", "pipe_types", False)),
            tolerances={"endpoint_mm": _MEP_ENDPOINT_MM},
        ),
    OpSpec(
            name="create_duct_placeholder",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                ParamSpec("p0_mm", "pt_xyz", required=True),
                ParamSpec("p1_mm", "pt_xyz", required=True),
                ParamSpec("level", "sel", required=True,
                          ref_kinds=(ReferenceKind.LEVEL,)),
                ParamSpec("system_type", "sel"),
                ParamSpec("duct_type", "sel"),
            ),
            capability=(("create", "mep_system"), ("create", "element")),
            post=("placeholder duct exists; LocationCurve endpoints == p0/p1 "
                  "(±5mm, 3D); reference level == resolved level (topology); "
                  "IsPlaceholder of the built element (semantic); "
                  "duct_type of the built element == resolved duct_type "
                  "(semantic)"),
            writes_model=True,
            grounded=(("level", "levels", True),
                      ("system_type", "duct_system_types", False),
                      ("duct_type", "duct_types", False)),
            tolerances={"endpoint_mm": _MEP_ENDPOINT_MM},
        ),
    # ── Flexible runs ────────────────────────────────────────────────────
    # A flexible duct/pipe has NO pair of ends: it has a PATH. Hence its own
    # `path3` parameter kind — an open THREE-DIMENSIONAL polyline of 2..64
    # points. The flat `path` (used by enclosures) could not be reused: it
    # is two-dimensional, while a flexible run almost always goes from the
    # floor to a suspended ceiling, i.e. its whole point is the Z axis.
    # Silently padding in a zero height would mean building the WRONG
    # route; this is exactly the class of problem that made create_beam
    # require `pt_xyz`.
    #
    # THE WITNESS HERE IS STRONGER THAN FOR RIGID OPS, and this is not
    # decoration: Revit hands back the whole path
    # (`FlexDuct.Points`/`FlexPipe.Points` — "points of the flex duct,
    # including the end points"), so ALL the points and their COUNT are
    # checked, not just the ends. Checking only the ends would miss a
    # dropped middle, i.e. a different route under a green verdict.
    # `Location as LocationCurve` is deliberately NOT read for a flexible
    # element: there it is a Hermite spline, and its ends are a derived
    # quantity, while `Points` is the primary one.
    OpSpec(
            name="create_flex_duct",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                ParamSpec("path", "path3", required=True),
                ParamSpec("level", "sel", required=True,
                          ref_kinds=(ReferenceKind.LEVEL,)),
                ParamSpec("system_type", "sel"),
                ParamSpec("flex_duct_type", "sel"),
            ),
            capability=(("create", "mep_system"), ("create", "element")),
            post=("flex duct exists; Points read back == path, same count and "
                  "same order (±5mm, 3D, geometry); reference level == "
                  "resolved level (topology); flex_duct_type of the built "
                  "element == resolved flex_duct_type (semantic)"),
            writes_model=True,
            grounded=(("level", "levels", True),
                      ("system_type", "duct_system_types", False),
                      ("flex_duct_type", "flex_duct_types", False)),
            tolerances={"point_mm": _MEP_ENDPOINT_MM},
        ),
    OpSpec(
            name="create_flex_pipe",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                ParamSpec("path", "path3", required=True),
                ParamSpec("level", "sel", required=True,
                          ref_kinds=(ReferenceKind.LEVEL,)),
                ParamSpec("system_type", "sel"),
                ParamSpec("flex_pipe_type", "sel"),
            ),
            capability=(("create", "mep_system"), ("create", "element")),
            post=("flex pipe exists; Points read back == path, same count and "
                  "same order (±5mm, 3D, geometry); reference level == "
                  "resolved level (topology); flex_pipe_type of the built "
                  "element == resolved flex_pipe_type (semantic)"),
            writes_model=True,
            grounded=(("level", "levels", True),
                      ("system_type", "piping_system_types", False),
                      ("flex_pipe_type", "flex_pipe_types", False)),
            tolerances={"point_mm": _MEP_ENDPOINT_MM},
        ),
]
