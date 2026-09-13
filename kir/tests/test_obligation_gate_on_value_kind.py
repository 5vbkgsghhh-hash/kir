"""A GATE ON THE OBLIGATION BY THE VALUE'S KIND, NOT BY THE PARAMETER'S
PRESENCE.

WHY A THIRD GATE. The certificate had two of them, and both ask "is the
field present": `conditional`/`param` (a witness is needed when the field
IS present) and `unless_param` (needed when the field is NOT present). There
is an obligation whose provability is decided by the field's CONTENTS.

A case bought live on 20.08.2026. A contour's bounding box is provable as
long as the loop consists of lines and arcs, and BECOMES UNPROVABLE the
moment a spline appears in it: Revit chooses the shape between the declared
points (`HermiteSpline`, tangents undocumented), and our compile-time
estimate undershoots it by construction — Revit gave 9705.3 mm along Y where
the estimate expected 9426.0, a 279 mm gap against a tolerance of 50.

WHAT HAPPENED WITHOUT THE GATE. The emitter (correctly) does not set a
bounding-box witness for a splined loop, while the obligation stayed
declared — and the certificate printed `proven=False`, reason "no witness
check with key 'bbox'". The verdict is formally correct, yet reads as
"COULD NOT prove" instead of "deliberately NOT CLAIMING." The difference is
exactly the one named absences were built for: an inability and a
withdrawal of claim turn red the same way, and mean different things.

🔴 AND WHY THE REASON'S TEXT IS CHECKED RIGHT HERE TOO. The gate's first
version gave a correct verdict with a false explanation: "absent param
'contour'" — while `contour` was live and present. A correct verdict with a
false explanation is more dangerous than an error: the reader will check the
verdict, but will remember the explanation.
"""
from __future__ import annotations

import unittest

from kir import translation_cert as TC
from kir.compiler import compile_program

_SNAP = {"levels": [{"id": 355, "name": "Уровень 1", "elevation_mm": 0.0}]}
_RING = [[0, 0], [12000, 0], [12000, 8000], [0, 8000]]
_VIA = [[9600, 9400], [6600, 6600]]


def _cert(contour: dict):
    out = compile_program({"ir_version": "1.0", "ops": [{
        "op": "create_floor_by_contour", "id": "F1", "contour": contour,
        "level": {"by": "element_id", "value": 355}}]},
        revit_version="2026", snapshot=_SNAP)
    assert out.ok, [str(d.message_ru)[:200] for d in out.diagnostics]
    return TC.certify_program(list(out.grounded_ops or []), "2026")


def _bbox_clause(cert):
    return next(c for c in cert.ops[0].clauses if "bbox" in (c.clause or ""))


_PLAIN = {"outer": {"shape": "poly", "points_mm": _RING}}
_SPLINE = {"outer": {"shape": "poly", "points_mm": _RING,
                     "splines": [{"edge": 2, "via_mm": _VIA}]}}


class TheGateReadsTheValue(unittest.TestCase):

    def test_a_plain_ring_still_OWES_its_bbox(self) -> None:
        """NARROWNESS CONTROL FIRST: the gate must not dare free everyone.

        An obligation lifted from everyone at once passes any check below.
        """
        clause = _bbox_clause(_cert(_PLAIN))
        self.assertTrue(clause.required, "габарит перестал требоваться у прямого контура")
        self.assertTrue(clause.discharged)
        self.assertTrue(_cert(_PLAIN).proven)

    def test_a_spline_ring_is_PROVEN_without_claiming_the_bbox(self) -> None:
        cert = _cert(_SPLINE)
        clause = _bbox_clause(cert)
        self.assertFalse(clause.required)
        self.assertTrue(clause.discharged)
        self.assertTrue(cert.proven,
                        "сплайновая плита не доказана — затвор не сработал")

    def test_the_reason_names_the_KIND_not_a_missing_param(self) -> None:
        """A correct verdict with a false explanation is more dangerous than an error."""
        reason = _bbox_clause(_cert(_SPLINE)).reason or ""
        self.assertIn("spline", reason)
        self.assertIn("contour", reason)
        self.assertNotIn("absent param", reason)

    def test_a_spline_in_a_HOLE_gates_the_bbox_too(self) -> None:
        """A hole is the same kind of loop. A gate that looks only at the
        outer boundary would leave a false red exactly where it is hardest
        to find."""
        holed = {"outer": {"shape": "poly", "points_mm":
                           [[0, 0], [20000, 0], [20000, 16000], [0, 16000]]},
                 "holes": [{"shape": "poly",
                            "points_mm": [[5000, 5000], [12000, 5000],
                                          [12000, 11000], [5000, 11000]],
                            "splines": [{"edge": 0,
                                         "via_mm": [[7000, 6200], [10000, 3800]]}]}]}
        cert = _cert(holed)
        self.assertFalse(_bbox_clause(cert).required)
        self.assertTrue(cert.proven)

    def test_an_unknown_kind_is_REFUSED_not_ignored(self) -> None:
        """A gate that silently lets an unfamiliar kind through frees the
        obligation by a typo. Here it must scream."""
        with self.assertRaises(TC.CertificateSchemaError):
            TC._value_carries_kind({"__region__": {"outer": []}}, "contour", "выдумка")


if __name__ == "__main__":
    unittest.main()
