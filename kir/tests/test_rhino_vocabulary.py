"""A FREE-FORM DICTIONARY: what it promises and where it NAMES its
boundary.

🔴 WHY THIS FILE (01.09.2026). `course/rhino.py` was set up so the author
could build the way one builds in Rhino, with BIM arriving after the
form. That means what must be checked is not "does the function work" but
TWO things the whole branch stands on:

  1. THE NUMBERS `faces()` RETURNS ARE CORRECT. The advance of form into
     BIM will stand on them (strip -> wall, region -> floor slab), and a
     thickness taken wrong will ride silently into the wall;
  2. WHERE COUNTING IS IMPOSSIBLE, A NAMED REFUSAL ARRIVES, NOT A NUMBER.
     Form 44 of this tree: a plausible number is more dangerous than a
     zero, because no one argues with it.

🔴 AND SEPARATELY — WHY THERE IS A "PRISM VS. NON-PRISM" PAIR HERE. A test
on a single prism would be green BY CONSTRUCTION: it always has opposing
faces, and the check would not distinguish a working thickness search
from a function that simply always returns the distance between the
first two planes. The pair tells them apart: on a prism the thickness is
named by a number, on a beveled body — by a refusal with words.
"""
from __future__ import annotations

import unittest

from kir import contour, dsl
from kir.course import rhino as R
from kir.diag import KirRefusal


def _band(width_mm: float = 300.0, length_mm: float = 6000.0) -> dict:
    """A strip in plan — what will in the future become a WALL."""
    return contour.region([[0, 0], [length_mm, 0],
                           [length_mm, width_mm], [0, width_mm]])


def _prism(height_mm: float = 3000.0, **kw) -> dict:
    dsl.reset(intent="проба")
    r = _band(**kw)
    return R.loft([(r, 0), (r, height_mm)], name="полоса")


class ЛофтСобираетТелоИНазываетСвоюГраницу(unittest.TestCase):

    def test_two_sections_make_one_blend(self):
        body = _prism()
        self.assertEqual(len(body["ops"]), 1)
        self.assertEqual(body["sections"], 2)

    def test_three_sections_make_two_blends_bottom_up(self):
        dsl.reset(intent="проба")
        r = _band()
        body = R.loft([(r, 0), (r, 3000), (r, 6000)], name="стопка")
        self.assertEqual(len(body["ops"]), 2)
        ops = dsl.current().ops
        self.assertEqual([o["base_z_mm"] for o in ops], [0.0, 3000.0])
        self.assertEqual([o["height_mm"] for o in ops], [3000.0, 3000.0])

    def test_the_note_says_the_loft_is_piecewise(self):
        """The boundary reaches the author IN THE OUTPUT, not in a
        docstring he doesn't read."""
        self.assertIn("ПРЯМАЯ", _prism()["note"])

    def test_sections_must_ascend(self):
        dsl.reset(intent="проба")
        r = _band()
        with self.assertRaises(KirRefusal) as e:
            R.loft([(r, 3000), (r, 0)], name="вниз")
        self.assertIn("расти", e.exception.diagnostics[0].message_ru)

    def test_one_section_is_not_a_loft(self):
        dsl.reset(intent="проба")
        with self.assertRaises(KirRefusal):
            R.loft([(_band(), 0)], name="одно")

    def test_unequal_point_counts_lose_the_mesh_and_say_why(self):
        """🔴 THE REFERENCE CASE: the operations are built, but there IS
        NO mesh, and this is NAMED.

        The correspondence between vertices on different rings is
        Revit's choice. Any triangulation of ours would describe a body
        we did not build — hence `None` with a reason here, not a
        plausible mesh.
        """
        dsl.reset(intent="проба")
        квадрат = _band()
        треугольник = contour.region([[0, 0], [6000, 0], [3000, 4000]])
        body = R.loft([(квадрат, 0), (треугольник, 3000)], name="разные")
        self.assertEqual(len(body["ops"]), 1, "операции обязаны строиться")
        self.assertIsNone(body["mesh"])
        self.assertIn("разное число точек", body["mesh_absent_reason"])
        with self.assertRaises(KirRefusal) as e:
            R.faces(body)
        self.assertIn("причина названа", e.exception.diagnostics[0].message_ru)


class ГраниОтдаютЧисла(unittest.TestCase):

    def test_a_box_has_six_faces_and_every_field(self):
        fs = R.faces(_prism())
        self.assertEqual(len(fs), 6)
        for f in fs:
            for key in ("normal", "centroid_mm", "area_mm2", "ring_mm",
                        "plane", "facing", "thickness_mm"):
                self.assertIn(key, f)
            self.assertAlmostEqual(
                sum(c * c for c in f["normal"]), 1.0, places=9,
                msg="нормаль обязана быть единичной")

    def test_the_plane_of_a_face_is_the_language_kind(self):
        """A face gives back `plane` as a NATIVE TYPE OF THE LANGUAGE —
        the operation takes it as is."""
        f = R.faces(_prism(), facing="up")[0]
        self.assertEqual(sorted(f["plane"]), ["normal", "origin_mm", "x_dir"])
        self.assertAlmostEqual(
            sum(a * b for a, b in zip(f["plane"]["normal"], f["plane"]["x_dir"])),
            0.0, places=9, msg="x_dir обязан лежать В плоскости")

    def test_thickness_of_a_band_is_its_width(self):
        """🔴 THE CONTRACT THE ADVANCE INTO A WALL WILL STAND ON."""
        fs = R.faces(_prism(width_mm=380.0, length_mm=6000.0,
                            height_mm=3000.0))
        толщины = {f["facing"]: f["thickness_mm"] for f in fs}
        self.assertEqual(толщины["south"], 380.0)
        self.assertEqual(толщины["north"], 380.0)
        self.assertEqual(толщины["up"], 3000.0)
        self.assertEqual(толщины["west"], 6000.0)

    def test_a_tapered_body_has_no_thickness_and_says_why(self):
        """PAIRED WITH THE PREVIOUS ONE: without it, the test would be
        green by construction."""
        dsl.reset(intent="проба")
        низ = _band(width_mm=380.0)
        верх = contour.region([[1000, 100], [5000, 100],
                              [5000, 280], [1000, 280]])
        fs = R.faces(R.loft([(низ, 0), (верх, 3000)], name="скос"))
        self.assertEqual([f for f in fs if f["thickness_mm"] is not None], [])
        for f in fs:
            self.assertTrue(f["thickness_reason"],
                            "нет толщины — обязана быть причина словом")

    def test_facing_filters_and_refuses_an_unknown_side(self):
        body = _prism()
        self.assertEqual(len(R.faces(body, facing="up")), 1)
        self.assertEqual(len(R.faces(body, facing="side")), 4)
        with self.assertRaises(KirRefusal) as e:
            R.faces(body, facing="вверх")
        self.assertIn("сторон", e.exception.diagnostics[0].message_ru)

    def test_horizontal_faces_carry_a_plan_ring(self):
        """For a horizontal face, the ring lies flat in the plane
        without projection."""
        верх = R.faces(_prism(), facing="up")[0]
        self.assertEqual(верх["poly"]["shape"], "poly")
        self.assertEqual(len(верх["poly"]["points_mm"]), 4)
        self.assertNotIn("poly", R.faces(_prism(), facing="south")[0])


class СечениеРежетИНеВыдумывает(unittest.TestCase):

    def test_the_middle_of_a_taper_is_interpolated(self):
        dsl.reset(intent="проба")
        низ = contour.region([[0, 0], [12000, 0], [12000, 8000], [0, 8000]])
        верх = contour.region([[2000, 2000], [10000, 2000],
                              [10000, 6000], [2000, 6000]])
        s = R.section(R.loft([(низ, 0), (верх, 30000)], name="конус"), 15000)
        xs = sorted({p[0] for p in s["outer"]["points_mm"]})
        ys = sorted({p[1] for p in s["outer"]["points_mm"]})
        self.assertEqual((xs[0], xs[-1]), (1000.0, 11000.0))
        self.assertEqual((ys[0], ys[-1]), (1000.0, 7000.0))

    def test_the_ring_carries_no_collinear_leftovers(self):
        """The triangulation trace is removed: a rectangular
        cross-section has EXACTLY 4 points."""
        s = R.section(_prism(), 1500)
        self.assertEqual(len(s["outer"]["points_mm"]), 4)

    def test_a_miss_is_a_named_refusal_not_an_empty_region(self):
        with self.assertRaises(KirRefusal) as e:
            R.section(_prism(height_mm=3000.0), 9000)
        self.assertIn("не пересекло", e.exception.diagnostics[0].message_ru)

    def test_two_disjoint_pieces_refuse_by_name(self):
        """🔴 A LIMIT OF THE LANGUAGE, NAMED OUT LOUD, NOT WORKED AROUND.

        The `region` kind has exactly ONE outer ring. A body whose
        cross-section has split into two pieces refuses here, by name —
        instead of merging the pieces into one shape and lying about the
        form. This is lifted by separate work on the limit (multiple
        outer rings), not by a prop here.
        """
        m1 = R._loft_mesh([(None, 0.0, [(0, 0), (1000, 0), (1000, 1000),
                                        (0, 1000)]),
                           (None, 3000.0, [(0, 0), (1000, 0), (1000, 1000),
                                           (0, 1000)])])[0]
        m2 = R._loft_mesh([(None, 0.0, [(5000, 0), (6000, 0), (6000, 1000),
                                        (5000, 1000)]),
                           (None, 3000.0, [(5000, 0), (6000, 0), (6000, 1000),
                                           (5000, 1000)])])[0]
        off = len(m1["vertices_mm"])
        both = {"vertices_mm": m1["vertices_mm"] + m2["vertices_mm"],
                "triangles": m1["triangles"] + [[i + off for i in t]
                                                for t in m2["triangles"]]}
        with self.assertRaises(KirRefusal) as e:
            R.section(both, 1500)
        self.assertIn("НЕСВЯЗНЫХ", e.exception.diagnostics[0].message_ru)


class ПреобразованияСохраняютРодЗначения(unittest.TestCase):

    def test_move_keeps_the_kind(self):
        poly = {"shape": "poly", "points_mm": [[0, 0], [100, 0], [100, 100]]}
        self.assertEqual(R.move(poly, 10, 20)["shape"], "poly")
        self.assertIn("outer", R.move(_band(), 10, 20))
        self.assertIn("vertices_mm", R.move(_prism()["mesh"], 0, 0, 500))

    def test_move_is_exact(self):
        got = R.move({"shape": "poly", "points_mm": [[0, 0], [100, 0]]}, 5, -5)
        self.assertEqual(got["points_mm"], [[5.0, -5.0], [105.0, -5.0]])

    def test_rotate_ninety_degrees(self):
        got = R.rotate({"shape": "poly", "points_mm": [[1000, 0]]}, 90)
        x, y = got["points_mm"][0]
        self.assertAlmostEqual(x, 0.0, places=6)
        self.assertAlmostEqual(y, 1000.0, places=6)

    def test_mirror_and_scale(self):
        p = {"shape": "poly", "points_mm": [[100, 200]]}
        self.assertEqual(R.mirror(p, "x")["points_mm"], [[-100.0, 200.0]])
        self.assertEqual(R.scale(p, 2)["points_mm"], [[200.0, 400.0]])

    def test_scale_refuses_a_non_positive_factor(self):
        with self.assertRaises(KirRefusal):
            R.scale({"shape": "poly", "points_mm": [[1, 1]]}, 0)

    def test_array_linear_and_polar(self):
        p = {"shape": "poly", "points_mm": [[0, 0], [100, 0]]}
        ряд = R.array(p, 3, step_mm=(1000, 0))
        self.assertEqual(len(ряд), 3)
        self.assertEqual(ряд[2]["points_mm"][0], [2000.0, 0.0])
        круг = R.array(p, 4, angle_deg=90)
        self.assertEqual(len(круг), 4)

    def test_array_refuses_both_or_neither(self):
        p = {"shape": "poly", "points_mm": [[0, 0], [100, 0]]}
        for kw in ({}, {"step_mm": (1, 0), "angle_deg": 90}):
            with self.assertRaises(KirRefusal):
                R.array(p, 2, **kw)


class ЧастиБулевойИАдресацияСвойством(unittest.TestCase):

    def test_parts_have_the_shapes_the_registry_knows(self):
        from kir.ops_boolean import PART_SHAPES, PART_FIELDS
        части = [R.box((0, 0, 0), (100, 100, 100)),
                 R.sphere((0, 0, 0), 50),
                 R.cylinder((0, 0, 0), 50, 200),
                 R.prism(_band(), 500)]
        for ч in части:
            self.assertIn(ч["shape"], PART_SHAPES)
            for поле in PART_FIELDS[ч["shape"]]:
                self.assertIn(поле, ч, f"{ч['shape']}: реестр требует {поле}")

    def test_by_property_is_sugar_over_the_registry(self):
        self.assertEqual(R.by_property("Width", 380),
                         {"disambiguate_by": dsl.disambiguate("Width", 380)})

    def test_tolerance_refuses_because_grounding_narrows_exactly(self):
        """🔴 REFUSAL INSTEAD OF ROUNDING: grounding narrows the pool by
        EXACT equality."""
        with self.assertRaises(KirRefusal) as e:
            R.by_property("Width", 380, tol_mm=5)
        self.assertIn("ТОЧНЫМ", e.exception.diagnostics[0].message_ru)


class СловарьНеЗатеняетУжеВведённыхИмён(unittest.TestCase):

    def test_every_public_name_is_in_the_seam(self):
        """A name that sits in the module and is not named at the seam is dark BY CONSTRUCTION."""
        публичные = {n for n in dir(R)
                     if not n.startswith("_") and callable(getattr(R, n))
                     and getattr(getattr(R, n), "__module__", "") == R.__name__}
        self.assertEqual(публичные, set(R.RHINO_NAMES),
                         "поверхность модуля разошлась с объявленным швом")

    def test_no_name_shadows_a_different_object(self):
        """Wiring has no right to silently replace `region` or `extrude`.

        The test will outlive the wiring: it asks not "was it introduced"
        but "if it was introduced, is it THE SAME THING". A name collision
        is the only way this wave could break the existing dictionary.
        """
        from kir import course
        for имя, что in R.RHINO_NAMES.items():
            если_есть = course.SANDBOX_NAMES.get(имя)
            if если_есть is not None:
                self.assertIs(если_есть, что,
                              f"{имя}: в шве лежит ДРУГОЙ объект")


if __name__ == "__main__":
    unittest.main()
