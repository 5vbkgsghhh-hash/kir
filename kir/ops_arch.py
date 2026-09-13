"""ops_arch — AR content the compiler did not have: ceilings and
railings.

Registry module — see REGISTRY_MODULES.md. Operations are added HERE, not in
spec.py. Emitters live in arch_emit.py (a paired file, exactly like
ops_struct.py + struct_emit.py for the framing wave); authoring.py gets only
an import and two lines in _EMITTERS.

WHY THIS WAVE. The full snapshot of 13A-RD-AR-K2_v33 (a 59-story tower,
55,293 elements) showed: part of the model is not expressible not because of
a flawed lifter, but because THE OPERATION DOES NOT EXIST AT ALL. The lift
failure-cause map (commit 9c63cc4e) named six categories that are "not a
FamilyInstance and have no op," and two of them — Ceilings 81 and
StairsRailing 203 — occur in EVERY architectural project. Before this wave
the registry had 32 writers and not a single ceiling.

TWO MEASUREMENTS THAT SHAPE THESE OPS (compiled against :52412, 2021-2026,
29.07 — API names here are verified by compilation, not from memory, see
extract.py on _CATEGORY_SPECS):

  Ceiling.Create(doc, IList<CurveLoop>, typeId, levelId)  → 2022-2026, 5/6
      2021: CS0117 'Ceiling' does not contain a definition for 'Create'
  doc.Create.NewCeiling(...)                              → 0/6, NOT A SINGLE ONE
      CS1061 'Document' does not contain a definition for 'NewCeiling'

The second measurement matters more than the first: on Revit 2021 the
ceiling has not "a different overload" but NO creation path at all. So the
version axis here is not an emission fork (as with create_floor, where 2021
falls back to legacy NewFloor) but a typed refusal, KIR-E003. Building a
floor instead of a ceiling "so the gate is green" is exactly the Goodhart
that cost this house 96% of the groups: "did something else" reads from the
outside as success.

  Railing.Create(doc, CurveLoop, typeId, levelId)               → 6/6
  Railing.Create(doc, hostId, typeId, RailingPlacementPosition) → 6/6
  RailingPlacementPosition.Treads / .Stringer                   → 6/6
  RailingPlacementPosition.Left/.Right/.Landing/.Run/.None      → 0/6
  ElementTypeGroup.RailingType                                  → 0/6

The railing has no version axis at all. But there are two MEASURED
consequences:

1. There are TWO placement kinds, because the API has two overloads: a free
   railing along its own path, and a railing that BELONGS TO a stair/ramp.
   On K2 the second kind is the entire population (OST_StairsRailing 203).
   Collapsing them into one would mean inventing a path where the source
   gives an owner. The split is made with the `variety` field — the same
   device and the same name as in create_foundation (the registry reserves
   the word "kind" for the dictionary of Revit object varieties, see the
   NAMING NOTE in ops_struct.py).

2. The railing has NO default type in the document: ElementTypeGroup.
   RailingType does not compile on any version, whereas
   ElementTypeGroup.CeilingType compiles on all six. So create_ceiling COULD
   have a doc_default branch (like create_floor), while create_railing
   cannot, no matter what. Both are deliberately left out of the doc_default
   list in ground.py: an omitted `type` follows the general rule, "sole
   entry in the pool, otherwise a typed question." For the ceiling this is a
   deliberate refusal of an available convenience — a "default type" on
   someone else's building is almost never the type that was in the source,
   and a silent type substitution is indistinguishable from success.

WHAT IS NOT HERE, AND WHY (§18.1, "silent loss is forbidden"):

* CEILING SLOPE. The Ceiling.Create overload with (Line slopeArrow, double
  slope) compiles (5/6, the same axis), but the SEMANTICS of the second
  argument cannot be verified offline: rise-over-run ratio or radians — the
  compiler is equally silent about it either way. Setting a parameter whose
  unit of measure is guessed would introduce exactly the error that already
  cost 96% of the groups ("0 degrees instead of no angle"). So there is NO
  slope in the op, and the lifter must REFUSE on a sloped ceiling rather
  than emit it flat. A flat ceiling instead of a sloped one is not an
  approximation, it is a falsehood.
* RAILING OFFSET FROM THE LEVEL. None of the five plausible names
  (STAIRS_RAILING_HEIGHT_OFFSET_PARAM, STAIRS_RAILING_BASE_OFFSET_PARAM,
  RAILING_HEIGHT_OFFSET, RAILING_SYSTEM_*_OFFSET_PARAM, ...) exists on any
  version — measured. A parameter that is not in the API is also not in the
  op; the lifter must refuse on a railing with an offset rather than zero it
  out. The ceiling's offset, by contrast, DOES EXIST:
  CEILING_HEIGHTABOVELEVEL_PARAM, 6/6.

CONTOUR ON THE CEILING (09.08.2026). create_ceiling gained a SECOND shape
input — an optional `contour` of kind `region`, i.e. the whole sketch
language from contour.py (rect/l/poly with small arcs, up to 8 holes,
grid-intersection points). Three things matter here, each verified, not
assumed:

1. `outline`/`holes` REMAIN and have not changed by a byte. The reverse path
   (decompile/lift.py::_lift_ceiling -> materialize) emits exactly these;
   replacing them would break the loop on every ceiling of every
   decompiled building. Mutual exclusion is a typed KIR-P007 in the
   compiler, exactly as with place_family; an "either/or" schema is not
   expressible.
2. AN ARC IS NOT DECORATION. The polyline `outline` cannot express a rounded
   edge: it gives a DIFFERENT shape, not an approximation. This is the same
   class as "a flat ceiling instead of a sloped one" in the paragraph above.
3. THE CONTOUR BRANCH HAS THE SAME VERSION AXIS AS THE STRAIGHT ONE, AND
   THIS WAS RE-VERIFIED on 09.08 against the reference assemblies, not from
   memory: in
   revit_all_main_versions_api_x64/2021.0.0/.../RevitAPI.xml the type
   `T:Autodesk.Revit.DB.Ceiling` EXISTS, while the number of `M:...Ceiling.*`
   members is ZERO (in 2022 and 2026 both `Ceiling.Create` overloads are
   there); the string `NewCeiling` appears in none of the XML files and in
   none of the RevitAPI.dll files for 2021/2022/2026. So on 2021 the
   ceiling has neither an `IList<CurveLoop>` path nor a legacy `CurveArray`
   path — UNLIKE create_floor_by_contour, which on 2021 falls back to
   doc.Create.NewFloor(CurveArray, ...). So the ceiling's contour branch
   does NOT get `emit_curvearray_cs`: on 2021 the whole operation refuses
   (KIR-E003), before any shape parsing.
"""
from __future__ import annotations

from kir.registry_base import *  # noqa: F401,F403 (OpSpec/ParamSpec/...)

#: `create_railing.position` in words <-> RailingPlacementPosition members.
#: ONE table for the emitter and the lift, so the two directions do not
#: drift apart — the same device as WALL_LOCATION_LINE_ORDINALS in
#: create_wall. Exactly two members, because measurement gives exactly two:
#: .Left/.Right/.Landing/.Run/.None/.Center do not compile on any of the six
#: versions, even though "left/right" is the first thing that comes to mind
#: and what a person would write from memory.
RAILING_PLACEMENT_MEMBERS = {
    "treads": "Treads",
    "stringer": "Stringer",
}

OPS = [
    OpSpec(
            name="create_ceiling",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                # EXACTLY ONE OF TWO: `outline` (a straight polyline) OR
                # `contour` (a typed CONTOUR sketch). That is why `outline`
                # stopped being required AT THE SCHEMA LEVEL: the
                # requirement became MUTUAL, and a schema cannot express a
                # mutual one — it lives in the compiler as a typed KIR-P007,
                # the same device and for the same reason as in place_family
                # (xyz versus p0_mm/p1_mm). Both fields at once are
                # ambiguous ("which of the two shape descriptions is true?"),
                # and neither field is an operation with no shape; guessing
                # on the author's behalf means silently building the wrong
                # ceiling.
                #
                # NO REPLACEMENT TOOK PLACE, AND THIS IS A DECISION, NOT
                # CAUTION: the reverse path (decompile/materialize.py) emits
                # `outline`/`holes`, and if the straight points had
                # disappeared, the loop would break on every ceiling of
                # every decompiled building.
                ParamSpec("outline", "pts"),   # >=3 [x,y] mm
                ParamSpec("holes", "pts_list"),
                # CONTOUR (v2.0, 17.07): rect/l/poly with small arcs, up to
                # 8 holes, points as literals or grid intersections. An arc
                # in a ceiling plan is ENTIRELY inexpressible with straight
                # points: `outline` is a polyline, and a rounded edge of a
                # suspended ceiling under it becomes a polygon, i.e. a
                # DIFFERENT shape, not an approximation. The region has its
                # own holes, so `holes` together with `contour` is also
                # KIR-P007: two opening descriptions would mean one of them
                # gets silently discarded.
                ParamSpec("contour", "region"),
                ParamSpec("level", "sel", required=True,
                          ref_kinds=(ReferenceKind.LEVEL,)),
                # 🔴 REFERENCE KIND NARROWED 24.08.2026: the `ceiling_types`
                # pool is captured from the target document BEFORE the run,
                # and a type created by this same program is not there BY
                # CONSTRUCTION. In a clean "Проект1" 0 of 18 ceilings were
                # built.
                ParamSpec("type", "sel",
                          ref_kinds=(ReferenceKind.CEILING_TYPE,)),
                # The ceiling's offset from the level is the ONLY vertical
                # degree of freedom that has a measured BuiltInParameter
                # (CEILING_HEIGHTABOVELEVEL_PARAM, 6/6). Without a default:
                # no parameter — no line of C#, absence stays absence, not
                # zero.
                ParamSpec("height_offset_mm", "mm", min_val=-15_000,
                          max_val=15_000),
            ),
            capability=(("create", "element"),),
            # A semicolon SEPARATES obligations (translation_cert.py splits
            # post exactly on it and requires a witness for every piece), so
            # there must not be one inside parentheses — otherwise the note
            # about 2021 turns into a separate "promise without a witness".
            post=("ceiling exists on Revit 2022+ (на 2021 операция невозможна "
                  "по построению — типизированный отказ KIR-E003, пути "
                  "создания потолка в API нет ни на одной версии) (materialize); "
                  "level binding == resolved level (topology); "
                  "bbox XY extents == outline or contour extents (±50mm, arc "
                  "extremes included, computed at compile time) (geometry); "
                  "sketch loop count and per-loop vertex multiset == authored rings "
                  "on the ±1mm canon grid (geometry); "
                  "height offset param == height_offset_mm when given (±1mm) (geometry); "
                  # THE PROMISE WAS ADDED TOGETHER WITH THE WITNESS, NOT
                  # AFTER IT — the same argument as with the contour slab:
                  # the audit runs FROM the promise TO the obligation, and it
                  # does not catch an op that proves more than it promises.
                  # Prose narrower than the code harms the reader.
                  "every declared spline via-point lies ON the built sketch "
                  "curve, within Revit's own VertexTolerance plus the emitted "
                  "coordinate quantum (geometry)"),
            writes_model=True,
            grounded=(("level", "levels", True),
                      ("type", "ceiling_types", False)),
            # `spline_point_mm` is OUR HALF of the tolerance, and the
            # number was taken not by reasoning but by the SAME key as the
            # contour slab: the witness there and here is one and the same
            # (`spline_points_witness` over `Sketch.Profile`), and the
            # second addend — Revit's own `VertexTolerance` — is read at
            # runtime and does not belong to the registry. Introducing a
            # DIFFERENT number here would mean declaring that the ceiling is
            # emitted with a different coordinate quantum, which is not the
            # case.
            tolerances={"bbox_mm": 50.0, "height_offset_mm": 1.0,
                        "sketch_mm": 1.0, "spline_point_mm": 0.01},
        ),
    OpSpec(
            name="create_railing",
            effect=EffectKind.CREATE,
            # 🔴 THE RESULT IS PLURAL, AND THIS IS A MEASUREMENT, NOT
            # CAUTION (04.09.2026). This used to have `RESULT_ELEMENT`
            # (`IdentityCardinality.ONE`, field `id`, referenceable), even
            # though `Railing.Create(doc, hostId, typeId, position)` returns
            # `ICollection<ElementId>` — measured by assignment to the
            # declared type on all six versions — while the emitter iterates
            # over ALL created elements and stamps each one. Only the FIRST
            # one went into the receipt.
            #
            # THE COST, MEASURED BY THE READERS, NOT ASSUMED: the identity
            # field is queried by `address.element_addresses` (the "op ->
            # elements" map, on which the A5 ownership check rests) and by
            # `created_ledger.created_keys()` (the ledger of what was
            # created, DERIVED from `ResultSpec.identity_field` of all
            # CREATE ops). Both took `id`, i.e. EXACTLY ONE flight railing;
            # the second one — and on K2 the entire population is
            # `OST_StairsRailing`, 203 of them — existed in the model and
            # existed in no check at all. In their own words, what this
            # means: "created but not shown is indistinguishable from
            # garbage in the model".
            #
            # WHY NOT "THE EXTRAS HONESTLY REFUSE," EVEN THOUGH THAT IS THE
            # SECOND LEGITIMATE WAY OUT. Because the tree ALREADY HAS an
            # answer about the count created, and it is not "one":
            # `acceptance._expected_count` on this same op returns `(1,
            # Certainty.AT_LEAST, "Railing.Create(host)
            # возвращает КОЛЛЕКЦИЮ: у марша ограждение встаёт с двух сторон
            # сразу")`. Refusing on the second railing would refuse the
            # ENTIRE population of the hosted branch and would make that
            # acceptance branch dead — i.e. the choice would be made by
            # taste against measurement.
            #
            # WHAT IS LOST BY THIS, NAMED: referenceability. `reference_kind`
            # on a plural result is forbidden by `ResultSpec` itself ("only a
            # single-identity result can be referenced"), and the
            # `create_railing` handle now REFUSES on `by=ref` with a named
            # reason (`dsl._unreferenceable_reason`) instead of silently
            # linking the first of the two. Cost measurement: references to
            # a railing in the tree are ZERO — no parameter of any op accepts
            # a railing, and no test/corpus addresses it by `by=ref`.
            #
            # THE FIELD NAME IS `railing_ids`, not `created_ids`:
            # `created_ids` is exactly the GUESSED name that the registry
            # never declared and that `test_address_bridge` caught; the name
            # kind is taken from the already-existing plural results
            # (`segment_ids`, `moved_ids`, `joined_ids`).
            result=ResultSpec(IdentityCardinality.MANY, "railing_ids"),
            family="authoring",
            params=(
                # The placement kind is a closed set from the TWO
                # Railing.Create overloads, not from taste. See the module
                # header.
                ParamSpec("variety", "enum", required=True,
                          choices=("path", "hosted")),
                # variety="path": an open polyline of 2..64 points. Its own
                # parameter kind, NOT "pts": the `pts` contour requires >=3
                # points and non-zero area, i.e. it is closed by
                # construction, while a straight railing is two points and
                # zero area.
                ParamSpec("path", "path"),
                ParamSpec("level", "sel",
                          ref_kinds=(ReferenceKind.LEVEL,)),
                # variety="hosted": a stair/ramp owner. target_w is the
                # same reference kind that create_window uses to address its
                # wall, so a reference to a create_stairs op in the same
                # program works without a new mechanism.
                ParamSpec("host", "target_w"),
                ParamSpec("position", "enum",
                          choices=tuple(RAILING_PLACEMENT_MEMBERS)),
                ParamSpec("type", "sel"),
            ),
            capability=(("create", "element"),),
            # EXACTLY WHAT IS CHECKED IS WHAT IS PROMISED. The previous
            # edit also promised "type == resolved railing type," even
            # though the emitter does not place a witness on the type (same
            # as create_floor) — the certificate audit caught this, and the
            # right answer here is to drop the promise, not to find it a
            # wording that passes the check.
            # 🔴 THE BOUNDING-BOX OBLIGATION WAS DROPPED 25.08.2026 BY A LIVE
            # MEASUREMENT, AND IT WAS DROPPED, NOT STRETCHED BY A TOLERANCE.
            #
            # Live, in Проект1 (Revit 2026): 3 built, 20 ACCUSED, and 140
            # accompanying operations died from the program's rollback.
            # Neighboring ops from the same run gave 100% — so it is not the
            # test rig.
            #
            # What was checked was the BODY'S BOUNDING BOX (get_BoundingBox
            # of the built Railing — posts, handrail, end caps) against the
            # PATH LINE (min/max of the author's `path` coordinates, zero
            # thickness). Oranges against apples by construction: the body
            # has a physical overhang, the line does not. Measurement: y
            # from 920975 to 921050 against the author's 921000..921000,
            # i.e. −25 and +50 with a tolerance of 50.0 — one side lands
            # EXACTLY on it.
            #
            # Hence "it doesn't always fail": 50 mm in internal feet is not
            # a terminating binary fraction, and the accumulated residual
            # wanders to both sides of 50.0 across instances with the SAME
            # nominal geometry. The witness was NON-DETERMINISTIC, and
            # "passed" for three out of twenty proved nothing.
            #
            # Nothing is lost: the little that the bounding box could
            # honestly prove — the path's ends — is proven MORE PRECISELY by
            # the neighboring `path_points` obligation (a re-read GetPath()
            # against path by the multiset of endpoints, ±1 mm versus ±50).
            # It stood right next to it the whole time and was SHADOWED by
            # the bounding box's false red.
            post=("railing exists (materialize); "
                  "variety=path: базовый уровень == resolved level (topology); "
                  # 🔴 04.09.2026: it used to be "by the multiset of edge
                  # ENDPOINTS," and that promise held exactly what turned
                  # out to be the defect — a shared bag of endpoints is
                  # blind to a PERMUTATION of interior vertices (A-B-C-D and
                  # A-C-B-D gave the same signature). What is compared is
                  # the multiset of the EDGES THEMSELVES: each edge is its
                  # own pair of endpoints, and the path is thereby fixed
                  # uniquely, up to reversal.
                  "путь, перечитанный GetPath(), совпадает с path по "
                  "мультимножеству РЁБЕР (у каждого ребра своя пара концов) "
                  "на решётке ±1мм "
                  "(geometry) — ОТКРЫТАЯ ломаная, замыкающего сегмента не "
                  "добавляется; "
                  "variety=hosted: КАЖДОЕ созданное ограждение принадлежит "
                  "запрошенному хосту (topology) (HasHost/HostId)"),
            writes_model=True,
            grounded=(("level", "levels", False),
                      ("type", "railing_types", False)),
            # `bbox_mm` was removed together with the obligation: a
            # tolerance that nobody reads is a dead number in the registry,
            # and the tolerance-provenance guard rightly flags it red.
            tolerances={"path_mm": 1.0},
        ),
]
