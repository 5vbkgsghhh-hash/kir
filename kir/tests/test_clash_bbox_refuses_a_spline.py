"""AN UNDERSIZED BOUNDING BOX HIDES A CLASH SILENTLY.

🔴 WHY (2026-08-25, audit finding, confirmed by reading the definition sites).

`contour.region_bbox` says so about itself, in plain text:

> THAT IS WHY A BOUNDING-BOX WITNESS ON A SPLINE IS ILLEGAL… An op whose witness
> relies on the bounding box is obligated to ask `region_has_spline` and refuse.

Both emitters do exactly that, bought by a LIVE measurement: Revit gave 9705.3 mm
along Y, our sample expected 9426.0 — **279 mm against a tolerance of 50**.

`clash_bundle._contour_slab_geometry` took the same `region_bbox` and DID NOT ASK.
And `create_floor_by_contour` IS LISTED in `SPLINE_WITNESSED_OPS` — meaning the
grounding guard SKIPS it for splines, and the undersized box went straight into
the bundle's `bbox_min_mm`/`bbox_max_mm`.

**The consequence is quieter than a refusal, and therefore worse:** a clash beyond
the undersized box's limit simply is not found, and "0 clashes" reads as "clean."

The solid-body neighbor deliberately has no check: a spline never reaches it —
there are no solid ops in `SPLINE_WITNESSED_OPS`. A guard that cannot fire is
worse than no guard at all.
"""
from __future__ import annotations

import unittest

from kir import clash_bundle, contour


class ЗАКОНОБЪЯВЛЕНИСОБЛЮДЁН(unittest.TestCase):

    def test_закон_записан_у_самой_геометрии(self):
        """The basis for the fix is not an opinion but the subject's own docstring.

        The law lives in `edges_bbox` (read by `region_bbox`), and the first
        edition of this test asked the wrong function — the instrument answered
        honestly, but the question was a different one.
        """
        текст = contour.edges_bbox.__doc__ or ""
        self.assertIn("ENVELOPE WITNESS IS ILLEGAL ON A SPLINE", текст)
        self.assertIn("region_has_spline", текст)

    def test_оп_со_сплайном_ПРОПУСКАЕТСЯ_заземлением(self):
        """Without this, the check would be unreachable — i.e. a dummy."""
        self.assertIn("create_floor_by_contour", contour.SPLINE_WITNESSED_OPS)

    def test_у_солида_проверки_НЕТ_и_это_намеренно(self):
        """There are no solid ops in the list — the guard could not fire there."""
        солидные = {n for n in contour.SPLINE_WITNESSED_OPS
                    if n.startswith("create_solid")}
        self.assertEqual(солидные, set())


class ПРИЧИНАНАЗВАНАИКЛАССИФИЦИРОВАНА(unittest.TestCase):

    def test_причина_есть_в_таблице_классов(self):
        """A reason with no class is a line nobody counts."""
        таблица = clash_bundle._WHY_CLASS if hasattr(clash_bundle, "_WHY_CLASS") \
            else None
        if таблица is None:
            import re
            src = open(clash_bundle.__file__, encoding="utf-8").read()
            self.assertIn('"region_has_spline": "op_expresses_no_body"', src)
            return
        self.assertEqual(таблица.get("region_has_spline"),
                         "op_expresses_no_body")

    def test_геометрия_контурной_плиты_СПРАШИВАЕТ(self):
        """WIRING: without it, the reason would exist and never be returned."""
        import ast
        import inspect
        # READ THE CODE, NOT THE TEXT: the first edition compared positions in
        # the SOURCE and failed on its own comment, where `region_bbox`
        # is mentioned before the call. Shape 7 — the matcher reads the label.
        дерево = ast.parse(inspect.getsource(clash_bundle._contour_slab_geometry))
        порядок = [n.func.attr for n in ast.walk(дерево)
                   if isinstance(n, ast.Call)
                   and isinstance(n.func, ast.Attribute)
                   and n.func.attr in ("region_has_spline", "region_bbox")]
        self.assertEqual(порядок[:2], ["region_has_spline", "region_bbox"],
                         f"спрашивать надо ДО габарита, получено: {порядок}")


if __name__ == "__main__":
    unittest.main()
