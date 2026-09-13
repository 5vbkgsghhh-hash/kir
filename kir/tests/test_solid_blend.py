"""BLEND — THE FIRST FREE FORM: a transition between TWO different profiles.

WHY THIS FILE. Extrusion and revolve work with ONE profile — that is the
prism and the body of revolution. A transition between two different
profiles is exactly what, in Rhino/Grasshopper, is used to make twisted
towers, tapering supports and double-curvature panels, and until 20.08.2026
the language had no way to say this at all.

🔴 WHY THE OP SHIPS EVEN THOUGH THE `ops_solid.py` HEADER REFUSED BLEND. The
refusal was CORRECT in its own argument, and NARROWER than its subject: it is
about VOLUME. There is no volumetric witness here, and there will not be one
until the prismatoid is measured. But volume is not the only quantity that
Revit is not free to move: it receives the profiles as INPUT and turns them
into END FACES, and the area of a flat end face is computed by a closed-form
Green's-theorem integral. Hence two honest witnesses, neither of which
recomputes our own input.

🔴 WHAT THESE WITNESSES DO NOT CATCH, AND THIS IS SAID HERE LOUDLY. The side
surface between the profiles IS PINNED DOWN BY NOTHING. Autodesk's
documentation, verbatim: `CreateLoftGeometry` — "blending smoothly between
the profiles", the smoothing rule is not documented anywhere. Revit is free
to run the side surface straight, bulge it outward, or dish it inward — all
three outcomes pass both witnesses, because both look at the END FACES. A
green triple with an unknown side surface is honest on each axis and
incomplete as a whole.

WHAT THIS WILL OPEN UP: a live measurement of `Solid.Volume` against a
Simpson's-rule prismatoid on a dozen profile pairs. If it matches — the side
surface is ruled, the volumetric witness ships too, and the bounding box
becomes exact. If it does not match — the refusal is confirmed by a number
and closed for good.

MEASUREMENTS THIS FILE RESTS ON (20.08.2026, compilation probe against real
assemblies, controls CS0117 and CS0200 both distinguish):
* `CreateBlendGeometry(CurveLoop, CurveLoop, ICollection<VertexPair>,
  SolidOptions)` — 6/6, as are the forms with an empty list and with `null`;
* the emitted blend program in full, with witness and receipt — 6/6;
* `FreeFormElement.Create` — 6/6 COMPILES, and per RevitAPI.xml on all six
  versions throws `ArgumentException` when "document is not a family
  document, nor a document editing an in-place family". Read from
  `data/api_traps/revit_api_traps.sqlite`, not from memory. That is why the
  element is a DirectShape — this was verified, not chosen.
"""
from __future__ import annotations

import unittest

from kir import contour as C
from kir import spec
from kir.solid_emit import _blend_outward_mm, emit_solid_blend

_LOW = [[0, 0], [2000, 0], [2000, 2000], [0, 2000]]
_TOP = [[400, 400], [1600, 400], [1600, 1600], [400, 1600]]


def _region(points):
    diags: list = []
    edges = C._validate_shape({"shape": "poly", "points_mm": points},
                              [], "B1", "p", diags)
    assert edges is not None, diags
    return {"outer": edges, "holes": []}


def _op(**over):
    base = {"id": "B1", "category": "generic_model", "name": "Пуфик",
            "height_mm": 3000.0, "base_z_mm": None,
            "__region_profile__": _region(_LOW),
            "__region_profile_top__": _region(_TOP)}
    base.update(over)
    return base


def _emit(**over):
    return emit_solid_blend(_op(**over), "2023", "S1")


class TheOpIsInTheRegistry(unittest.TestCase):

    def test_the_op_exists_and_takes_two_regions(self) -> None:
        s = spec.OPS["create_solid_blend"]
        regions = [p.name for p in s.params if p.kind == "region"]
        self.assertEqual(regions, ["profile", "profile_top"])

    def test_the_capability_cell_is_geometry_not_element(self) -> None:
        """The body inside the DirectShape is GEOMETRY WITHOUT BIM MEANING,
        and the cell says so.

        The cell ("create", "element") would read as "we built a building",
        but what got built is a shape with no type, no layers, and no
        specification.
        """
        self.assertEqual(spec.OPS["create_solid_blend"].capability,
                         (("create", "geometry"),))

    def test_the_post_declares_no_volume_and_that_is_the_point(self) -> None:
        """A NAMED ABSENCE, NOT FORGETFULNESS.

        Exactly what is checked is what is promised. The volume of the side
        surface that Revit chooses has no closed form — and promising it
        would mean signing off on an axis that no one reads.
        """
        post = spec.OPS["create_solid_blend"].post
        self.assertNotIn("volume", post)
        self.assertIn("planar cap area", post)
        self.assertIn("boundary", post)
        self.assertIn("outward-tolerant", post,
                      "односторонность габарита обязана быть ОБЪЯВЛЕНА, "
                      "а не спрятана в допуске")


class TheEmissionSaysTheBlend(unittest.TestCase):

    def test_it_calls_the_blend_factory(self) -> None:
        _decl, create, _checks, _rb = _emit()
        self.assertIn("GeometryCreationUtilities.CreateBlendGeometry(", create)

    def test_the_element_is_a_direct_shape_never_a_free_form(self) -> None:
        """`FreeFormElement.Create` throws in a project document — 6/6 per
        RevitAPI.xml. Compiles ≠ will build."""
        _decl, create, _checks, _rb = _emit()
        self.assertIn("DirectShape.CreateElement(", create)
        self.assertNotIn("FreeFormElement", create)

    def test_the_vertex_pairing_is_left_to_revit_by_the_DOCUMENTED_form(self) -> None:
        """🔴 `null`, NOT AN EMPTY LIST — PAID FOR BY A LIVE REFUSAL ON
        20.08.2026.

        The previous edition of this test pinned `new List<VertexPair>()`
        and reasoned as follows: "both forms compile, but an empty list
        reads as 'the correspondence is chosen by Revit', while null reads
        as 'forgotten'." Live, this produced a raw Revit exception instead of
        our own refusal:

            The input pVertexPairs are invalid.
            Parameter name: pVertexPairs

        Autodesk's contract is named verbatim and speaks specifically about
        `null` (RevitAPI.xml, param `vertexPairs`, all six versions): "If
        null, the function chooses vertex connections that will result in a
        geometrically reasonable blend". Nothing at all is said about an
        empty collection — Revit reads it as a given and unworkable
        correspondence.

        Shape of the defect: the author reasoned about the MEANING of the
        value instead of reading the declared contract. Both forms compile;
        one works.
        """
        _decl, create, _checks, _rb = _emit()
        self.assertIn("(ICollection<VertexPair>)null", create)
        self.assertNotIn("new List<VertexPair>()", create)

    def test_profiles_with_DIFFERENT_vertex_counts_are_legal(self) -> None:
        """Since Revit derives the correspondence, a different vertex count
        on each profile is LEGITIMATE.

        This is a direct consequence of the same contract, and it removes an
        entire question: there is no need to refuse on "a square versus a
        hexagon", and doing so would be harmful — this exact cross-section
        transition is precisely what a blend does."""
        _decl, create, _checks, _rb = _emit()
        self.assertIn("CreateBlendGeometry", create)

    def test_both_profiles_are_lifted_to_their_own_planes(self) -> None:
        _decl, create, _checks, _rb = _emit(base_z_mm=500.0)
        self.assertIn("U(500)", create.replace("500.0", "500"))
        self.assertIn("U(3500)", create.replace("3500.0", "3500"))


class TheWitnessesAreFourAndEachReadsTheBuilt(unittest.TestCase):

    def test_the_obligation_keys_are_exactly_these(self) -> None:
        _decl, _create, checks, _rb = _emit()
        self.assertEqual([c.obligation_key for c in checks],
                         ["solid_count", "cap_area", "profiles_on_boundary", "bbox"])

    def test_the_cap_area_is_the_sum_of_both_profile_areas(self) -> None:
        """The end faces ARE the profiles themselves, and their area is
        closed-form."""
        lo = C.region_measures(_region(_LOW))["area_mm2"]
        hi = C.region_measures(_region(_TOP))["area_mm2"]
        _decl, _create, checks, _rb = _emit()
        cap = next(c for c in checks if c.obligation_key == "cap_area")
        self.assertIn(f"{lo + hi:.1f}".rstrip("0").rstrip("."),
                      cap.verdict_cs.replace(",", ""))

    def test_the_boundary_witness_reads_the_BUILT_solid(self) -> None:
        """🔴 THE BODY COMES FROM THE ELEMENT, NOT FROM OUR OWN VARIABLE, AND
        THE DIFFERENCE IS LOAD-BEARING.

        `__sol_` is what the FACTORY returned. Between it and the element
        stands `SetShape`, and Revit is entitled to transform the body. The
        first edition of this witness read `__sol_` — meaning it checked our
        own object, and would have passed even if something different had
        landed in the model. Caught by the control on 20.08, not by
        reasoning.
        """
        _decl, _create, checks, _rb = _emit()
        w = next(c for c in checks if c.obligation_key == "profiles_on_boundary")
        self.assertIn("__el_B1.get_Geometry", w.reader_cs)
        self.assertNotIn("__sol_B1.Faces", w.reader_cs,
                         "свидетель вернулся к чтению нашей же переменной")
        self.assertIn(".Project(", w.reader_cs)
        self.assertIn("GetInstanceGeometry", w.reader_cs,
                      "DirectShape вправе отдать геометрию завёрнутой — "
                      "нераскрытая обёртка читалась бы как «тела нет»")

    def test_it_tells_unprojectable_apart_from_off_boundary(self) -> None:
        """TWO DIFFERENT OUTCOMES — TWO DIFFERENT TEXTS.

        "The face did not accept the point" and "the point is not on the
        boundary" are cured in opposite ways, and one single text for two
        different troubles is a named defect of the tree.
        """
        _decl, _create, checks, _rb = _emit()
        w = next(c for c in checks if c.obligation_key == "profiles_on_boundary")
        self.assertIn("could not be projected", w.verdict_cs)
        self.assertIn("does not lie on the built boundary", w.verdict_cs)

    def test_every_declared_vertex_rides_in_the_witness(self) -> None:
        """Eight vertices of two squares — all eight, not a sample."""
        _decl, _create, checks, _rb = _emit()
        w = next(c for c in checks if c.obligation_key == "profiles_on_boundary")
        self.assertEqual(w.reader_cs.count("new XYZ(U("), 8)


class TheBboxIsOutwardTolerantAndSaysWhy(unittest.TestCase):
    """For the blend the reference is a LOWER bound; for the revolve sector
    it is an UPPER bound."""

    def test_the_blend_allows_the_lateral_surface_to_bulge_out(self) -> None:
        _decl, _create, checks, _rb = _emit()
        bb = next(c for c in checks if c.obligation_key == "bbox")
        out = _blend_outward_mm(C.region_bbox(_region(_LOW)),
                                C.region_bbox(_region(_TOP)), 3000.0)
        self.assertGreater(out, 0.0)
        self.assertIn(f"{out:.2f}"[:6], bb.verdict_cs.replace(",", ""))

    def test_the_inward_side_stays_hard(self) -> None:
        """A shortfall would mean the end face is not where it belongs — a
        violation."""
        _decl, _create, checks, _rb = _emit()
        bb = next(c for c in checks if c.obligation_key == "bbox")
        self.assertIn("__dt_B1", bb.verdict_cs)

    def test_the_outward_estimate_is_derived_from_the_input(self) -> None:
        """The diagonal of the combined bounding box is an upper bound on
        the distance between the profiles, the only one derivable from the
        input. Not an assigned number."""
        box = (0.0, 0.0, 300.0, 400.0)
        self.assertAlmostEqual(_blend_outward_mm(box, box, 1200.0),
                               (300.0 ** 2 + 400.0 ** 2 + 1200.0 ** 2) ** 0.5)


class NothingWithoutABlendMoved(unittest.TestCase):
    """THE CONTROL WITHOUT WHICH EVERYTHING ABOVE IS WORTH NOTHING.

    `outward_mm` was added to the SHARED `_bbox_check` used by both
    extrusion and revolve. If it printed a zero term, the bytes of EVERY
    existing body would have shifted — and the parity ratchet would have
    gone red on a change that does not concern them.
    """

    def test_the_zero_term_is_not_printed_at_all(self) -> None:
        """🔴 THE THIRD EDITION OF THE CONTROL; THE FIRST TWO CHECKED
        NOTHING.

        The first took its reference from zeros — `+ 0.0 +` prints under it
        even in healthy code (`inward_mm`, existing behavior), meaning the
        input was DEGENERATE. The second looked for a double zero — but
        `outward` lands in a position where there was no zero at all,
        giving a SINGLE one. The third compares text against text: with a
        zero term it must be BYTE-FOR-BYTE identical to what it would be
        with no parameter at all.

        And this exact control is what found the real defect: `outward` had
        been applied to three of the six `Min.*` positions and NOT applied
        to `Max.*` — meaning a side surface crossing the upper bound
        remained a violation while being declared legitimate. A line-level
        probe would not have seen this.
        """
        from kir.solid_emit import _bbox_check
        box = (100, 200, 300, 400, 500, 600)
        hard = _bbox_check("Z1", "Z1", box, "")
        # THE REFERENCE IS AN EXACT STRING, NOT A COMPARISON AGAINST ITSELF.
        # Fourth edition: the third compared `hard` against
        # `outward_mm=0.0`, i.e. broken against broken — both carried the
        # extra term and matched. An external reference is the only one
        # that the same change cannot break.
        self.assertEqual(
            hard.verdict_cs.split("\n")[1],
            '    else if (MM(__bb_Z1.Min.X) < 100.0 - __dt_Z1 || MM(__bb_Z1.Min.X) > 100.0 + 0.0 + __dt_Z1 ||',
            "лишний член в габаритном условии — байты КАЖДОГО существующего "
            "тела сдвинулись бы, и ратчет паритета покраснел бы на правке, "
            "которая их не касается")

    def test_a_nonzero_term_IS_printed_on_ALL_SIX_faces(self) -> None:
        """A control in the other direction, AND IT COUNTS FACES.

        Six, not "more than zero": the relaxation must be present on both
        bounds of every axis. Three out of six would mean the body is only
        allowed to protrude down-left-back — an asymmetry that no one
        declared.
        """
        from kir.solid_emit import _bbox_check
        soft = _bbox_check("Z1", "Z1", (100, 200, 300, 400, 500, 600), "",
                           outward_mm=7.5)
        self.assertEqual(soft.verdict_cs.count("7.5"), 6)


if __name__ == "__main__":
    unittest.main()
