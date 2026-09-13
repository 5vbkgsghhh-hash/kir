"""ops_contour — CONTOUR sublanguage (sketch-geometry floors, etc.).

Registry module — see REGISTRY_MODULES.md. Add ops HERE, not in spec.py.
"""
from __future__ import annotations

from kir.registry_base import *  # noqa: F401,F403 (OpSpec/ParamSpec/DEFAULTS/LIST_*/...)

OPS = [
    OpSpec(
            name="create_floor_by_contour",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                ParamSpec("contour", "region", required=True),
                ParamSpec("level", "sel", required=True,
                          ref_kinds=(ReferenceKind.LEVEL,)),
                # 🔴 THE REFERENCE KIND WAS NARROWED ON 2026-08-24: the
                # `floor_types` pool is taken from the target document
                # BEFORE the run, and a type created by this same program is
                # not there BY CONSTRUCTION. In a clean "Project1," 0 of 82
                # floors failed to build.
                ParamSpec("type", "sel",
                          ref_kinds=(ReferenceKind.FLOOR_TYPE,)),
                # Offset from the level — the SAME degree of freedom as
                # create_floor's (FLOOR_HEIGHTABOVELEVEL_PARAM), and without
                # it the reverse pass is inexpressible: a census on 07-28
                # across two decompiles — 108 of 156 contour floors (demo-v3
                # and the facade) have a nonzero offset (-700, -600, -300,
                # -150, -100, +450, +1090 mm) — that is, the lift would have
                # to refuse on them or drop the floor onto the level's plane.
                # NO default: absent stays absent, all prior emission
                # byte-for-byte.
                ParamSpec("height_offset_mm", "mm", min_val=-15_000,
                          max_val=15_000),
            ),
            capability=(("create", "element"), ("create", "geometry")),
            post=("floor exists; level binding (topology); "
                  "assigned type == resolved requested type at operation end, before later edits (identity); "
                  "bbox == lowered-edges "
                  "bbox ±50mm (arc extremes included, computed at compile time); "
                  "sketch loop count and per-loop vertex multiset == authored rings "
                  "on the ±1mm canon grid (geometry); "
                  "height offset param == height_offset_mm when given (±1mm); "
                  # THE PROMISE WAS WRITTEN TOGETHER WITH THE WITNESS, NOT
                  # AFTER IT. `translation_cert.audit_registry_coverage`
                  # invariant 3 goes FROM the promise TO the obligation and
                  # does not check the reverse direction — that is, an op
                  # that proves more than it promises is NOT caught by the
                  # audit. Harmless to the outcome and harmful to the
                  # reader: the prose becomes NARROWER than the code, and
                  # this codebase has already paid for prose diverging from
                  # behavior in both directions.
                  "every declared spline via-point lies ON the built sketch "
                  "curve, within Revit's own VertexTolerance plus the emitted "
                  "coordinate quantum (geometry)"),
            writes_model=True,
            grounded=(("level", "levels", True), ("type", "floor_types", False)),
            # `spline_point_mm` is OUR HALF of the tolerance, and only that
            # half can live in the registry. The curve witness's full
            # tolerance is assembled AT EMISSION from two parts of different
            # origin: Revit's own `VertexTolerance` (read at runtime — "two
            # points closer than this are considered coincident") and this
            # number here, the coordinate-printing quantum
            # (`contour.EMIT_COORD_QUANTUM_MM`): our boundary already
            # differs from the ideal one by half of it along each axis.
            # Writing the sum here would be a lie — the second term belongs
            # to Revit and differs across documents.
            tolerances={"bbox_mm": 50.0, "height_offset_mm": 1.0,
                        "sketch_mm": 1.0, "spline_point_mm": 0.01},
        ),
]
