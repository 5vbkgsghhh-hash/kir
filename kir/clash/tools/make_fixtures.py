"""The CLASH golden-fixture generator — SEPARATE from the tests (review #17).

A test that writes its own golden when one is missing and then passes can
never fail: it blesses any behaviour, including a broken one. So writing
goldens lives here, and the test knows exactly one thing — compare and
fail.

    PYTHONPATH=. venv/bin/python -m kir.clash.tools.make_fixtures

Regeneration is a deliberate move by hand, and its result must be read by
eye in the diff: a shifted golden means the formula shifted.
"""
from __future__ import annotations

import json
import pathlib

from kir.clash import detect as D
from kir.clash import hulls as H
from kir.clash import snapshot as S

#: 🔴 ANCHORED TO THE PACKAGE'S LOCATION, NOT TO THIS FILE'S DEPTH. Fixtures
#: belong to the `kir/clash` subpackage, and are addressed from it:
#: `parents[1]` was correct only for as long as the instrument sat in
#: `kir/clash/tools/`. The same shape brought down the sandbox (`f518b05`)
#: and `install_paths`.
import kir as _kir_pkg  # noqa: E402  — package anchor

FIXTURES = (pathlib.Path(_kir_pkg.__file__).resolve().parent
            / "clash" / "tests" / "fixtures")


def golden_scene() -> S.ClashGeometrySnapshot:
    """The golden scene covers ALL kinds of pairs and relations (review #17).

    The previous golden carried a single coarse AABB pair: most of
    `geom.py` could break without shifting a single byte. Here there is
    overlap, contact, a gap, a capsule against a prism, a capsule against a
    capsule, a geometry refusal, and an unsupported category.
    """
    els = [
        # the receiving wall (bbox/coarse — an axis is forbidden for a wall, review #2)
        {"element_id": "100", "category": "OST_Walls",
         "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [6000, 200, 3000],
         "level_id": "L1", "type_name": "Кирпич 250"},
        # a pipe running THROUGH the wall — overlap, a capsule against a box
        {"element_id": "200", "category": "OST_PipeCurves",
         "p0_mm": [3000, -500, 1500], "p1_mm": [3000, 700, 1500],
         "section_radius_mm": 50.0, "section_round": True,
         "bbox_min_mm": [2950, -550, 1450], "bbox_max_mm": [3050, 750, 1550],
         "level_id": "L1", "type_name": "Сталь 100"},
        # a duct TOUCHING the wall's face at exactly 0 — contact
        {"element_id": "300", "category": "OST_DuctCurves",
         "p0_mm": [1000, 400, 2000], "p1_mm": [2000, 400, 2000],
         "section_radius_mm": 200.0,
         "bbox_min_mm": [800, 200, 1800], "bbox_max_mm": [2200, 600, 2200],
         "level_id": "L1", "type_name": "Круглый 400"},
        # a cable tray far away — not a finding, but present in the census and in the area's pairs
        {"element_id": "400", "category": "OST_CableTray",
         "p0_mm": [0, 20000, 0], "p1_mm": [1000, 20000, 0],
         "section_radius_mm": 100.0,
         "bbox_min_mm": [-100, 19900, -100], "bbox_max_mm": [1100, 20100, 100],
         "level_id": "L1", "type_name": "Лоток 200"},
        # a floor with an ARC in its contour -> falls back to bbox (review #1)
        {"element_id": "500", "category": "OST_Floors",
         "bbox_min_mm": [0, 0, 2950], "bbox_max_mm": [6000, 4000, 3150],
         "level_id": "L1", "type_name": "Монолит 200"},
        # a floor with a CLEAN contour -> prism/conservative; pipe 200
        # pierces it, giving a conservative×conservative pair (otherwise the
        # golden would only know coarse pairs — exactly the reproach of
        # review #17)
        {"element_id": "900", "category": "OST_Floors",
         "bbox_min_mm": [2000, -1000, 1400], "bbox_max_mm": [4000, 1000, 1600],
         "level_id": "L1", "type_name": "Монолит 200 чистый"},
        # an element with no geometry at all -> missing_geometry
        {"element_id": "600", "category": "OST_PipeCurves",
         "level_id": "L1", "type_name": "битый"},
        # a category outside the table -> unsupported/kind_outside_table
        {"element_id": "700", "category": "OST_Parking", "level_id": "L1"},
        # a datum -> not_eligible
        {"element_id": "800", "category": "OST_Grids"},
    ]
    profiles = {
        "500": {"profile_available": True,
                "exterior_loop": [[0, 0], [6000, 0], [6000, 4000], [0, 4000]],
                "curve_kinds": [["line", "line", "arc", "line"]],
                "arc_midpoints": [[None, None, [3000, 4300], None]],
                "holes": []},
        "900": {"profile_available": True,
                "exterior_loop": [[2000, -1000], [4000, -1000], [4000, 1000],
                                  [2000, 1000]],
                "curve_kinds": [["line", "line", "line", "line"]],
                "arc_midpoints": [[None, None, None, None]],
                "holes": []},
    }
    return S.build_from_elements(
        els, origin={"run_dir": "golden", "l0_sha": "0"}, profiles=profiles)


def category_manifest() -> dict:
    """SEEDING the manifest — only when the file is absent. After that it
    lives by hand.

    🔴 THIS FUNCTION PROMISED AN INDEPENDENCE IT DOES NOT HAVE, AND PROMISED
    IT IN ITS OWN DOCSTRING. The previous text read: "the manifest is the
    independent side of the equality, and it changes only by hand" — while
    the function reads `H.coverage_matrix()`, that is, the SAME
    `KIND_TABLE` that `test_12_category_manifest_is_frozen_and_counted`
    compares it against, and `main()` overwrote the file with it on every
    run of the generator.

    That is, the freeze held only up until the first run of
    `make_fixtures` — after that, both sides of the equality read one
    source, and the test is green BY CONSTRUCTION for any mistaken edit to
    the table. This is exactly the defect the test was written for,
    sitting inside the test itself.

    Found on 2026-08-14 while admitting the strip for a wall: the
    generator silently overwrote a manual edit to the manifest, and "my
    deliberate one-line edit" became indistinguishable from an accidental
    one.

    So: seeding — yes (otherwise the first run on a fresh tree runs into a
    missing file), overwriting — no. The line changes by hand, and then it
    is visible in the diff.
    """
    rows = {}
    for row in H.coverage_matrix():
        rows[row["category"]] = {
            "eligible": row["eligible"],
            "mvp_side": row["mvp_side"],
            "label": row["label"],
            "hull_sources": row["hull_sources"],
            "refusal": row["refusal"],
        }
    return {"row_count": len(H.KIND_TABLE),
            "note": ("Заморожено руками. Новая категория обязана уронить тест. "
                     "Генератор этот файл НЕ перезаписывает — только засевает, "
                     "если его нет (см. category_manifest())."),
            "rows": rows}


def _write(name: str, payload) -> None:
    p = FIXTURES / name
    p.parent.mkdir(parents=True, exist_ok=True)
    text = payload if isinstance(payload, str) else json.dumps(
        payload, ensure_ascii=False, sort_keys=True, indent=1)
    p.write_text(text + "\n", encoding="utf-8")
    # Printed relative to the PACKAGE: a short path for the reader, and it
    # does not depend on how deep the fixtures sit inside the subpackage.
    print(f"написан {p.relative_to(pathlib.Path(_kir_pkg.__file__).parent)}")


def main() -> int:
    snap = golden_scene()
    rep = D.detect(snap, clearance_mm=0.0)
    _write("golden_report_v2.json", D.dumps(rep))
    if (FIXTURES / "category_manifest.json").exists():
        print("манифест НЕ тронут: он живёт руками (см. category_manifest())")
    else:
        _write("category_manifest.json", category_manifest())
    print("грейды:", snap.by_grade())
    print("находок:", len(rep["findings"]),
          "отношения:", rep["relation_counts"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
