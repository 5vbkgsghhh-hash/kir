#!/usr/bin/env python3
"""Offline compile matrix for the create_element verified templates.

Renders every create_element C# artifact (5 creation templates × arg variants,
3 grounding collectors, the op_id recovery query), wraps each with the
pipeline's canonical wrapper, and compiles it against every RevitAPI we support
via the local Roslyn compile service (http://localhost:52412) — the
API-correctness gate BEFORE any live run (design 2026-07-04 §4 step 3).

VERSIONS was 2024/2025/2026 until 2026-08-03, and that was the whole reason this
gate did not fire on a real defect. `build_grounding_code(..., static_cat=None)`
emits `__ty.Category.BuiltInCategory` — a property Autodesk added in 2023, so it
is CS1061 on 2021/2022. The artifact WAS rendered here and the line WAS compiled;
the matrix simply never asked the three columns where the answer was "no". A gate
narrower than the product's support range reports green for the half it cannot
see. The set below is now the same six the compile service declares as
`requiredVersions` and the release pipeline builds clients for.

Usage:  venv/bin/python scripts/create_element_compile_matrix.py
Exit 0 = every cell compiled; non-zero = at least one failure (printed).
No Revit, no bridge, no model — pure offline proof.
"""
from __future__ import annotations

import json
import sys
import urllib.request

sys.path.insert(0, ".")

from kukai.llm.revit_execution_pipeline import wrap_user_code  # noqa: E402
from kukai.write.create_element import (  # noqa: E402
    build_grounding_code,
    render_create_code,
)
from kukai.write.operations import generate_create_recovery_code  # noqa: E402

COMPILE_URL = "http://localhost:52412/compile"
VERSIONS = ["2021", "2022", "2023", "2024", "2025", "2026"]

COMMON = {"transaction_name": "KUKI: создание", "op_id": "kukai:matrix:00000001",
          "params_names_cs": "", "params_vals_cs": ""}
PARAMS = {"params_names_cs": '"Марка", "Комментарии"',
          "params_vals_cs": '"К-1", "тест \\"кавычки\\""'}

CASES: list[tuple[str, dict]] = [
    ("level/basic", dict(COMMON, elevation_mm=9900.0, name="")),
    ("level/named+params", dict(COMMON, **PARAMS, elevation_mm=-3300.0, name='Этаж "9"')),
    ("grid/basic", dict(COMMON, start_x_mm=0.0, start_y_mm=0.0,
                        end_x_mm=12000.0, end_y_mm=0.0, name="")),
    ("grid/named", dict(COMMON, start_x_mm=-500.5, start_y_mm=100.0,
                        end_x_mm=-500.5, end_y_mm=9000.0, name="А1")),
    ("wall/basic", dict(COMMON, wall_type_id=445, level_id=311,
                        start_x_mm=0.0, start_y_mm=0.0, end_x_mm=5000.0,
                        end_y_mm=0.0, base_z_mm=0.0, height_mm=3300.0)),
    ("wall/params", dict(COMMON, **PARAMS, wall_type_id=445, level_id=311,
                         start_x_mm=-100.25, start_y_mm=200.75, end_x_mm=4900.0,
                         end_y_mm=200.75, base_z_mm=3300.0, height_mm=2500.0)),
    ("floor/rect", dict(COMMON, floor_type_id=555, level_id=311, base_z_mm=0.0,
                        profile_cs="{0.000, 0.000}, {5000.000, 0.000}, "
                                   "{5000.000, 4000.000}, {0.000, 4000.000}")),
    ("floor/tri+params", dict(COMMON, **PARAMS, floor_type_id=555, level_id=312,
                              base_z_mm=3300.0,
                              profile_cs="{0.000, 0.000}, {6000.000, 0.000}, "
                                         "{3000.000, 4500.000}")),
    ("family_instance/plain", dict(COMMON, symbol_id=771, level_id=311,
                                   x_mm=0.0, y_mm=0.0, z_mm=0.0,
                                   rotation_deg=0.0, structural_type="NonStructural")),
    ("family_instance/rotated-column+params",
     dict(COMMON, **PARAMS, symbol_id=771, level_id=311, x_mm=1200.5, y_mm=-800.0,
          z_mm=3300.0, rotation_deg=90.0, structural_type="Column")),
]


def compile_one(wrapped: str, version: str) -> tuple[bool, str]:
    body = json.dumps({"code": wrapped, "revitVersion": version}).encode("utf-8")
    req = urllib.request.Request(
        COMPILE_URL, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if data.get("success"):
        return True, ""
    errs = data.get("errors") or []
    msg = "; ".join(f"{e.get('code')}: {e.get('message')} (line {e.get('line')})"
                    for e in errs[:3])
    return False, msg


def main() -> int:
    artifacts: list[tuple[str, str]] = []
    for name, args in CASES:
        et = name.split("/", 1)[0]
        artifacts.append((f"template:{name}", render_create_code(et, args)))
    artifacts.append(("grounding:wall",
                      build_grounding_code("wall", {"name_contains": ["монолит"]}, None)))
    artifacts.append(("grounding:floor", build_grounding_code("floor", {}, None)))
    artifacts.append(("grounding:family_instance",
                      build_grounding_code("family_instance",
                                           {"name_contains": ["400"],
                                            "family_contains": ['ЖБ "спец"']},
                                           "OST_StructuralColumns")))
    artifacts.append(("recovery:walls",
                      generate_create_recovery_code("kukai:matrix:00000001", "OST_Walls")))

    failures = 0
    for name, code in artifacts:
        wrapped = wrap_user_code(code)
        row = []
        for v in VERSIONS:
            ok, msg = compile_one(wrapped, v)
            row.append(f"{v}:{'OK' if ok else 'FAIL'}")
            if not ok:
                failures += 1
                print(f"FAIL {name} [{v}] {msg}")
        print(f"{name:45s} {'  '.join(row)}")
    total = len(artifacts) * len(VERSIONS)
    print(f"\nMATRIX: {total - failures}/{total} cells compiled "
          f"({len(artifacts)} artifacts x {len(VERSIONS)} Revit versions)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
