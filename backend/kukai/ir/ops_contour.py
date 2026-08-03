"""ops_contour — CONTOUR sublanguage (sketch-geometry floors, etc.).

Registry module — see REGISTRY_MODULES.md. Add ops HERE, not in spec.py.
"""
from __future__ import annotations

from kukai.ir.registry_base import *  # noqa: F401,F403 (OpSpec/ParamSpec/DEFAULTS/LIST_*/...)

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
                ParamSpec("type", "sel"),
                # Смещение от уровня — ТА ЖЕ степень свободы, что у
                # create_floor (FLOOR_HEIGHTABOVELEVEL_PARAM), и без неё
                # обратный ход невыразим: замер 28.07 по двум разборам —
                # 108 из 156 контурных полов (демо-v3 и фасад) имеют
                # ненулевое смещение (-700, -600, -300, -150, -100, +450,
                # +1090 мм), то есть лифт обязан был бы отказывать по ним
                # или ронять пол на плоскость уровня. NO default: absent
                # stays absent, вся прежняя эмиссия байт-в-байт.
                ParamSpec("height_offset_mm", "mm", min_val=-15_000,
                          max_val=15_000),
            ),
            capability=(("create", "element"), ("create", "geometry")),
            post=("floor exists; level binding (topology); bbox == lowered-edges "
                  "bbox ±50mm (arc extremes included, computed at compile time); "
                  "height offset param == height_offset_mm when given (±1mm)"),
            writes_model=True,
            grounded=(("level", "levels", True), ("type", "floor_types", False)),
            tolerances={"bbox_mm": 50.0, "height_offset_mm": 1.0},
        ),
]
