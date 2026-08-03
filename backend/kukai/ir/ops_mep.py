"""ops_mep — MEP single-element ops (duct/cable-tray/...); systems live in ops_connect.

Registry module — see REGISTRY_MODULES.md. Add ops HERE, not in spec.py.
"""
from __future__ import annotations

from kukai.ir.registry_base import *  # noqa: F401,F403 (OpSpec/ParamSpec/DEFAULTS/LIST_*/...)

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
            ),
            capability=(("create", "element"),),
            post=("cable tray exists; LocationCurve endpoints == p0/p1 (±5mm, 3D); "
                  "reference level == resolved level (topology)"),
            writes_model=True,
            grounded=(("level", "levels", True),
                      ("tray_type", "cable_tray_types", False)),
            tolerances={"endpoint_mm": 5.0},
        ),
]
