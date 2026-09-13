"""NOBODY HAD CHECKED THREE REFUSALS OF THE AUTHOR'S DSL (a coverage
instrument for mesh/geom/plane).

The technique was bought in `clash/**` (E-54, E-55): break a summand one at
a time and ask whether the CORPUS notices and whether the SUITES notice.
Here the same technique is in a form suited to CHECKING code: the unit is
not a function but a REFUSAL BRANCH, and the one question for it is
whether it fires even once.

MEASUREMENT of 30.08.2026 (a custom tracer over three files; `coverage` is
not in the suite's venv). 15 suites where these modules are reachable at
all were run — 650 passed, 426 subtests:

    file        refusal branches   never fired
    mesh.py          38                 3
    geom.py          12                 0
    plane.py          6                 0

🔴 THE FIRST MEASUREMENT I WOULD HAVE DECLARED THREE TIMES WORSE. On a
narrow set of nine files the result was "geom.py: 8 cold out of 12",
including all five laws of `validate_points_xyz`. They were cold not by a
property of the code but because `kir/tests/test_site.py` — their only
witness — did not make it into the sample. A sample that does not cover
the subject answers about a different subject; this is the same correction
that already cost me an error on shell kinds (2,988 `Aabb` out of 3,000).

WHAT REMAINED AFTER FIXING THE DENOMINATOR is exactly three branches, and
all three are in the author's DSL (`mesh.extrude` / `mesh.sweep`). It is
never called from the tree: the only door is injecting names into the
author's sandbox (`course/__init__.py`), and decompilation does not produce
these operations. So the corpus cannot be a witness BY CONSTRUCTION, and
the witness must be the suite — as was already proven by a number for
`seg_prism_signed_distance` (83 pairs across five decompiles).

All three branches are REACHABLE — checked by execution, none is dead.
"""

from __future__ import annotations

import unittest

from kir import mesh as M
from kir.diag import KirRefusal

try:
    from shapely.geometry import MultiPolygon, Polygon
    HAVE_SHAPELY = True
except ImportError:                                   # pragma: no cover
    HAVE_SHAPELY = False

SQUARE = [[0., 0.], [1000., 0.], [1000., 1000.], [0., 1000.]]
PATH = [[0., 0., 0.], [0., 0., 1000.]]


class ОтказыВыдавливанияИЗаметанияНазываютПричину(unittest.TestCase):

    def _refusal(self, call) -> "object":
        with self.assertRaises(KirRefusal) as caught:
            call()
        self.assertEqual(len(caught.exception.diagnostics), 1)
        return caught.exception.diagnostics[0]

    @unittest.skipUnless(HAVE_SHAPELY, "shapely не установлена: ветвь про "
                                       "MultiPolygon без неё недостижима")
    def test_a_contour_split_by_a_boolean_is_named_not_swallowed(self):
        """A shapely boolean difference returns a MultiPolygon. One
        DirectShape is built from ONE connected set of faces, and the
        refusal must say so by the number of pieces, not silently take the
        first one."""
        split = MultiPolygon([Polygon([(0, 0), (10, 0), (10, 10), (0, 10)]),
                              Polygon([(50, 0), (60, 0), (60, 10), (50, 10)])])
        diagnostic = self._refusal(lambda: M.extrude(split, 100.0))
        self.assertEqual(diagnostic.code, M.MESH_DISCONNECTED)
        self.assertEqual(diagnostic.got, 2, "число кусков обязано быть НАЗВАНО")
        self.assertIn("несвязных куска", diagnostic.message_ru)

    @unittest.skipUnless(HAVE_SHAPELY, "shapely не установлена")
    def test_a_line_has_no_area_and_says_what_came(self):
        """A neighboring branch of the same condition; checked separately
        because it does not follow from the first."""
        ring = Polygon([(0, 0), (10, 0), (10, 10)]).exterior
        diagnostic = self._refusal(lambda: M.extrude(ring, 100.0))
        self.assertEqual(diagnostic.got, "LinearRing",
                         "род пришедшего обязан быть назван")

    def test_an_unknown_key_in_the_contour_dict_is_refused_by_name(self):
        """The contour dict knows exactly `outer` and `holes`. An extra key
        is not "almost right", it is a typo, and it must be NAMED: a key
        silently swallowed would travel into the model as a missing hole."""
        diagnostic = self._refusal(
            lambda: M.extrude({"outer": SQUARE, "holes": [], "hole": []},
                              100.0))
        self.assertEqual(diagnostic.got, ["hole"],
                         "лишний ключ обязан быть назван поимённо")

    def test_a_malformed_up_axis_is_refused(self):
        """The "up" axis sets where the profile's top is. A string instead
        of a vector is already an invalid input, and a refusal on it cannot
        fire on a legitimate one."""
        diagnostic = self._refusal(
            lambda: M.sweep(SQUARE, PATH, up="вверх"))
        self.assertIn("ось «вверх»", diagnostic.message_ru)
        self.assertEqual(diagnostic.got, "вверх")

    def test_legal_input_still_builds(self):
        """🔴 THE SECOND OUTCOME, MANDATORY. Without it, a change that
        "always refuses" would pass every check above."""
        solid = M.extrude({"outer": SQUARE, "holes": []}, 100.0)
        self.assertGreater(len(solid["vertices_mm"]), 0)
        self.assertGreater(len(solid["triangles"]), 0)
        swept = M.sweep(SQUARE, PATH)
        self.assertGreater(len(swept["vertices_mm"]), 0)
        self.assertGreater(len(swept["triangles"]), 0)

    def test_an_explicit_up_axis_is_still_accepted(self):
        """🔴 THE SECOND OUTCOME for the `up` branch: a legitimate axis must
        pass, otherwise a change that "rejects every up" would pass the
        check above."""
        swept = M.sweep(SQUARE, [[0., 0., 0.], [1000., 0., 0.]],
                        up=[0., 0., 1.])
        self.assertGreater(len(swept["triangles"]), 0)


if __name__ == "__main__":
    unittest.main()
