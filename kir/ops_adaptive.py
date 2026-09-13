"""ops_adaptive — ADAPTIVE COMPONENT: a shape by points that does NOT lose meaning.

Registry module — operations are added HERE, not in spec.py. The emitter
lives in `adaptive_emit.py` (a paired file, like `ops_mass.py` + `mass_emit.py`).

═══ WHY THIS OPERATION, AND WHY IT IS ONE OF A KIND ═════════════

The owner: "it matters to us to be able to model complex facades the way you
can in Rhino and Grasshopper." KIR's free-form already knows how to speak two
ways, and BOTH lose BIM meaning, as their authors honestly write in their own headers:

    mesh.py      "a mesh is GEOMETRY WITHOUT BIM MEANING… no type, no
                 layer thickness/material parameters, it will not appear
                 in schedules as a wall or a slab"
    ops_solid.py the same about DirectShape: "an extruded contour LOOKS LIKE
                 a slab… it still has neither layers, nor connections, nor
                 openings, nor a schedule entry"

For a pouf this is not a loss — a pouf is simply a shape. For a FACADE the
loss is fundamental: a panel must be a panel, or it will not appear in any
schedule, and "we made a facade" will turn out to be the same lie this whole
compiler is written against.

The adaptive component is the ONLY mechanism in Revit that gives, at the
same time, arbitrary placement by points AND a genuine typed
`FamilyInstance`: it has a family, a type, parameters, and a row in a schedule.

═══ API MEASUREMENT (RevitAPI.xml for all SIX versions + live Roslyn :52412, 08-20) ═

  AdaptiveComponentInstanceUtils.CreateAdaptiveComponentInstance
      (Document, FamilySymbol)                                       → 6/6
  AdaptiveComponentInstanceUtils.IsAdaptiveFamilySymbol(FamilySymbol) → 6/6
  AdaptiveComponentInstanceUtils.GetInstancePlacementPointElementRefIds
      (FamilyInstance)                                               → 6/6
  AdaptiveComponentInstanceUtils.IsAdaptiveComponentInstance          → 6/6
  AdaptiveComponentFamilyUtils.IsAdaptiveComponentFamily(Family)      → 6/6
  AdaptiveComponentFamilyUtils.GetNumberOfPlacementPoints(Family)     → 6/6
  ReferencePoint.Position — read AND written                          → 6/6
  A probe of the WHOLE chain with a witness (checks → creation → writing
      points → reading back → extent)                                → 6/6
  CONTROL  IsAdaptiveComponentInstanceZZZ   CS0117 ×6                → 0/6
  CONTROL  FamilyInstance.Id = null         CS0200 ×6                → 0/6

Both controls discriminate: the probe could have ended differently.

🔴 THE KIND OF DOCUMENT IS CHECKED SEPARATELY, ACROSS EACH OF THE SIX
RevitAPI.xml FILES, because this is exactly what the entire free-form chapter
stumbles on. `CreateAdaptiveComponentInstance` has NO condition about the
document's kind at all among its declared throws — only "symbol not found"
and "symbol not adaptive." Zero drift across versions. For comparison, in the same measurement:

    FreeFormElement.Create      "document is not a family document"   ALL SIX
    DirectShape.CreateElement   no condition about the document's kind ALL SIX

That is, an adaptive component is placed into a PROJECT document — the very
same one KIR writes into — and this is exactly the inversion the mass wave
already found on 08-10 in `FaceWall.Create`.

═══ WHAT THIS OPERATION DOES NOT HAVE, AND THIS IS A BOUNDARY, NOT AN OMISSION ════════════════

* **THE PANEL'S SHAPE BELONGS TO THE FAMILY, NOT TO US.** The op supplies
  POINTS to which the geometry adapts; exactly what geometry that is is
  decided by the family's author. The freedom here is in the ARRANGEMENT,
  and this is not a workaround — it is exactly how panelization is done in Revit.
* **THE MATERIAL MUST BE IMPORTED.** A live read-only measurement on 08-20 on
  a real project (`MNVNK_ATR_PD_B14_K6_AR_R2022`, Revit 2023, without a
  single transaction): 150 families, 293 types, **0 adaptive ones**, 0
  errors. A typical Russian project has no adaptive families at all — but,
  unlike the curve's kind, this is NOT "nothing to fix": an adaptive family
  does not appear on its own, it is loaded, and `load_family` is already in the registry.
* **WHETHER A READY-MADE `.rfa` EXISTS ON THE MACHINE IS NOT ASKED BY THIS
  INSTRUMENT.** `System.IO` is blocked at compile time in the
  `/admin/remote/exec` channel. This is a named absence, not "didn't check."

═══ THE KIND OF THE POINTS PARAMETER: A READY-MADE ONE IS TAKEN, AND HERE IS
WHY THIS ONE EXACTLY ════════════

The placement points are `path3` (2..64 points `[x,y,z]` mm). Considered and rejected:

* `pts_xyz` (a terrain point cloud) — rejected BY ITS LAWS, not by its shape.
  `geom.validate_points_xyz` holds two rules derived from the terrain's
  2.5-dimensionality: "one XY — one elevation" and "not all points on one
  line." Both are WRONG for a panel: a vertical edge is two points with the
  same plan position and different heights, and a two-point adaptive family
  is linear by construction. Taking it would mean introducing a
  silently-wrong constraint;
* a new kind — rejected because `path3`'s laws match the needed ones DOWN TO
  THE LAST ONE (2..64 points, finite coordinates, refusal on coinciding
  neighbors), and a second set of rules about the exact same thing would drift apart from the first.

⚠️ AND AN HONEST CAVEAT TO THIS CHOICE, because the kind's name lies about
the subject (canon form 25 — "an instrument that names a path measures a
path"): `path3` is called a POLYLINE, and here it is NOT a polyline but A SET
OF PLACEMENT POINTS. The order in the list means the PLACEMENT POINT NUMBER,
not a traversal sequence; there are no segments between neighboring points.
That is why the field is named `points_mm`, not `path`, and this caveat
stands here, not in someone's memory.

═══ THE NUMBER OF POINTS IS DECIDED BY THE FAMILY, NOT BY THE OP ══════════════════════════════════

How many placement points an adaptive family has is its own property
(`GetNumberOfPlacementPoints`). The op has no right to either choose on its
behalf or adjust the list: an extra point will not apply, a missing one will
leave the panel half-assembled, and both outcomes look like success from the
outside. So a mismatch is a REFUSAL, and the refusal names BOTH numbers: how
many the family asks for and how many the author sent.

The check stands BEFORE THE EFFECT: `IsAdaptiveFamilySymbol` and
`IsAdaptiveComponentFamily` are safe (they only throw on null), while
`GetNumberOfPlacementPoints` throws an `ArgumentException` on a non-adaptive
family — so it goes THIRD, after both kind checks. The order carries weight:
reorder it, and a typed refusal turns into a Revit exception with someone
else's text.
"""
from __future__ import annotations

from kir.registry_base import (
    EffectKind,
    OpSpec,
    ParamSpec,
    ReferenceKind,
    RESULT_ELEMENT,
)

#: How many placement points the op is willing to accept. The bounds are NOT
#: its own: they are exactly `geom.MIN_PATH_POINTS`/`MAX_PATH_POINTS` of kind
#: `path3`, and repeating them here as a number would mean introducing a
#: second copy of the bound, obliged to match the first. The real limit
#: belongs not to us but to the family, and it is asked of Revit.

OPS = [
    OpSpec(
        name="create_adaptive_component",
        effect=EffectKind.CREATE,
        result=RESULT_ELEMENT,
        family="authoring",
        params=(
            # THE TYPE — the same pool and the same reference kind as
            # `place_family`. A second pool over the same elements would mean
            # two answers to one question; the fitness of a SPECIFIC symbol
            # is decided not by the pool but by Revit itself —
            # `IsAdaptiveFamilySymbol` in the emission.
            #
            # ⚠️ THE POOL DOES NOT FILTER BY ADAPTIVENESS, and this is named,
            # not silenced: the snapshot is gathered by `open_model.py`,
            # which has no adaptiveness trait. Exactly the same asymmetry is
            # already recorded in the canon about `beam_types` ("the pool
            # does not filter on placement type, so ground happily hands the
            # emitter a symbol it cannot use"). It follows from this that the
            # preflight check must be IN THE EMISSION, before the effect.
            ParamSpec("symbol", "sel", required=True,
                      ref_kinds=(ReferenceKind.FAMILY_SYMBOL,)),
            # PLACEMENT POINTS. Kind `path3`, but this is NOT a polyline — see the module header.
            ParamSpec("points_mm", "path3", required=True),
        ),
        # 🔴 WITHOUT `grounded=`, ANY AUTHORED PROGRAM DIES IN A PANIC:
        # `KeyError: '__grounded__'` during emission, i.e. a COMPILER failure
        # instead of a typed refusal from the op. Found on 08-20 by a
        # neighboring wave, BY RUNNING IT, not by reading: the op compiled
        # 6/6 and crashed on the very first authored call — compilation
        # answered "it exists," while the question was "will it run" (canon
        # form 36, bought the same day).
        grounded=(("symbol", "family_symbols", False),),
        capability=(("create", "element"),),
        # Exactly what is checked is promised, and every promise reads the
        # BUILT element, not its own input.
        post=("adaptive instance exists and Revit confirms it is adaptive "
              "(semantic); placement point count == authored points (topology); "
              "each placement point sits at the authored point within the "
              "derived tolerance (geometry); instance bounding box contains "
              "every authored point (geometry)"),
        writes_model=True,
    ),
]
