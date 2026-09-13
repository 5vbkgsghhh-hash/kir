"""§18.1-consequence — L0 must distinguish the curve's kind; a chord is
forbidden.

Finding M2 of the 2026-07-28 audit: ``geometry_store`` wrote
``geom_kind="curve"`` for ANY ``LocationCurve``. Arc, spline, and straight
line are indistinguishable in L0; the arc side-index was collected for
walls and framing, but was CONSUMED only by walls. A beam, pipe, duct, or
cable tray with an arc was lifted as a CHORD — no atom, no reason, no
trace; ``verify`` compares only the endpoints and stamps ``exact``. A
building round in plan gave "coverage 95%" against a straight model.

At the time of writing these were failing (measured):

  * ``lift_document_detailed`` on an arced beam/pipe/duct/cable-tray gave
    ``create_beam``/``create_pipe``/``create_duct``/``create_cable_tray`` —
    four silent chords;
  * ``_lift_beam`` accepted ``_context`` and DID NOT READ it, even though
    the row with the exact arc already sat in ``curve.index.json`` (the
    ``curve`` stage requests OST_StructuralFraming on a par with walls);
  * ``L0Element``/``ExtractedGeometry`` carried no curve kind at all, and
    the emitted C# did not measure it.

Discipline §18.7: a refuting test BEFORE the fix.
"""
from __future__ import annotations

import math
import unittest

from kir.decompile.geometry_store import (
    GEOMETRY_HELPER_CS,
    parse_geometry,
)
from kir.decompile.l1_schema import AtomReason, FidelityReason
from kir.decompile.lift import lift_document_detailed
from kir.decompile.schema import (
    GeometryKind,
    L0Document,
    L0Element,
    L0SchemaError,
    LevelInfo,
    LocationCurveKind,
    ProjectInfo,
)


_RADIUS = 8_000.0
# The endpoints of a quarter-circle of radius 8 m are the same as those
# of the chord between them.
_P0 = (_RADIUS, 0.0, 0.0)
_P1 = (0.0, _RADIUS, 0.0)


def _element(
    category: str,
    element_id: str,
    *,
    curve_kind: LocationCurveKind | None,
    params: dict | None = None,
) -> L0Element:
    return L0Element(
        element_id=element_id,
        category=category,
        category_ru="—",
        type_id="7",
        type_name="T1",
        level_id="10",
        level_name="L1",
        geom_kind=GeometryKind.CURVE,
        p0_mm=_P0,
        p1_mm=_P1,
        rotation_deg=None,
        bbox_min_mm=(0.0, 0.0, 0.0),
        bbox_max_mm=(_RADIUS, _RADIUS, 3_000.0),
        host_id=None,
        params=params or {},
        curve_kind=curve_kind,
    )


def _document(*elements: L0Element) -> L0Document:
    return L0Document(
        doc_name="curve-kind", revit_version="2024", units="mm",
        change_stamp="t", levels=(LevelInfo("10", "L1", 0.0),),
        grids=(), rooms=(), project_info=ProjectInfo(), elements=elements)


def _arc_index(element_id: str) -> dict:
    """A side-index row with the EXACT arc (endpoints match L0)."""
    return {
        element_id: {
            "curve_kind": "arc",
            "arc": {
                "center_mm": [0.0, 0.0, 0.0],
                "radius_mm": _RADIUS,
                "x_axis": [1.0, 0.0, 0.0],
                "y_axis": [0.0, 1.0, 0.0],
                "start_angle_rad": 0.0,
                "end_angle_rad": math.pi / 2.0,
            },
        }
    }


def _nodes(result) -> dict:
    return {node["source_element_id"]: node for node in result.nodes}


_CURVE_ELEMENTS = (
    ("OST_StructuralFraming", "100", "create_beam", {}),
    ("OST_PipeCurves", "101", "create_pipe",
     {"RBS_PIPE_DIAMETER_PARAM": 100.0}),
    ("OST_DuctCurves", "102", "create_duct",
     {"RBS_CURVE_DIAMETER_PARAM": 200.0}),
    ("OST_CableTray", "103", "create_cable_tray", {}),
)


class L0CapturesTheCurveKind(unittest.TestCase):
    """2a — the curve's kind must be measured in the capture itself."""

    def test_emitted_csharp_classifies_line_arc_other(self) -> None:
        for token in ('__row["curve_kind"]', "as Line", "as Arc",
                      '"line"', '"arc"', '"other"'):
            self.assertIn(token, GEOMETRY_HELPER_CS, token)
        # §18.5/version drift: the same prohibition as throughout emission.
        self.assertNotIn("IntegerValue", GEOMETRY_HELPER_CS)

    def test_bridge_row_curve_kind_survives_parsing(self) -> None:
        row = {
            "geom_kind": "curve", "curve_kind": "arc",
            "p0_mm": list(_P0), "p1_mm": list(_P1),
            "rotation_deg": None,
            "bbox_min_mm": [0.0, 0.0, 0.0],
            "bbox_max_mm": [_RADIUS, _RADIUS, 10.0],
        }
        fields = parse_geometry(row).to_element_fields()
        self.assertEqual(fields["curve_kind"], "arc")

    def test_old_l0_without_the_field_stays_valid(self) -> None:
        """Absence of the field in a frozen L0 = "not measured", not "straight"."""
        row = {
            "geom_kind": "curve",
            "p0_mm": list(_P0), "p1_mm": list(_P1),
            "rotation_deg": None,
            "bbox_min_mm": None, "bbox_max_mm": None,
        }
        self.assertIsNone(parse_geometry(row).curve_kind)
        element = _element("OST_PipeCurves", "1", curve_kind=None)
        self.assertIsNone(element.curve_kind)
        self.assertIsNone(element.to_dict()["curve_kind"])

    def test_curve_kind_round_trips_through_the_element_dict(self) -> None:
        element = _element(
            "OST_PipeCurves", "1", curve_kind=LocationCurveKind.ARC)
        restored = L0Element.from_dict(element.to_dict())
        self.assertEqual(restored.curve_kind, LocationCurveKind.ARC)
        self.assertEqual(restored, element)

    def test_a_point_element_cannot_carry_a_curve_kind(self) -> None:
        with self.assertRaises(L0SchemaError):
            L0Element(
                element_id="1", category="OST_Doors", category_ru="—",
                type_id="7", type_name="T", level_id=None, level_name=None,
                geom_kind=GeometryKind.POINT,
                p0_mm=(0.0, 0.0, 0.0), p1_mm=None, rotation_deg=0.0,
                bbox_min_mm=None, bbox_max_mm=None, host_id=None,
                curve_kind=LocationCurveKind.LINE)


class ArcsMustNeverBecomeChords(unittest.TestCase):
    """2b — a non-Line without an expressible arc = an honest atom, NEVER a chord."""

    def test_arc_curve_elements_refuse_instead_of_chording(self) -> None:
        for category, element_id, op_name, params in _CURVE_ELEMENTS:
            with self.subTest(category=category):
                result = lift_document_detailed(
                    _document(_element(
                        category, element_id,
                        curve_kind=LocationCurveKind.ARC, params=params)),
                    None, None)
                node = _nodes(result)[element_id]
                self.assertNotEqual(
                    node.get("op_name"), op_name,
                    f"{category}: дуга поднялась ХОРДОЙ в {op_name} — "
                    "молчаливо-неверный результат")
                self.assertEqual(node["kind"], "atom")
                self.assertEqual(
                    node["reason"]["code"],
                    AtomReason.CURVE_KIND_UNSUPPORTED.value)

    def test_other_curve_kinds_refuse_too(self) -> None:
        for category, element_id, op_name, params in _CURVE_ELEMENTS:
            with self.subTest(category=category):
                result = lift_document_detailed(
                    _document(_element(
                        category, element_id,
                        curve_kind=LocationCurveKind.OTHER, params=params)),
                    None, None)
                node = _nodes(result)[element_id]
                self.assertEqual(node["kind"], "atom", op_name)
                self.assertEqual(
                    node["reason"]["code"],
                    AtomReason.CURVE_KIND_UNSUPPORTED.value)

    def test_straight_and_unmeasured_curves_are_untouched(self) -> None:
        for kind in (LocationCurveKind.LINE, None):
            for category, element_id, op_name, params in _CURVE_ELEMENTS:
                with self.subTest(category=category, curve_kind=kind):
                    result = lift_document_detailed(
                        _document(_element(
                            category, element_id,
                            curve_kind=kind, params=params)),
                        None, None)
                    node = _nodes(result)[element_id]
                    self.assertEqual(node["kind"], "op")
                    self.assertEqual(node["op_name"], op_name)

    def test_beam_consumes_the_curve_index_it_was_already_paid_for(self) -> None:
        """A beam with an arc IN THE INDEX is an atom, even if L0 does
        not know the curve's kind.

        The row already sits in ``curve.index.json`` (the ``curve`` stage
        requests OST_StructuralFraming), and ``_lift_beam`` accepted the
        context and did not read it. ``create_beam`` does not express an
        arc (in the registry it has no ``arc`` parameter, unlike
        ``create_wall``), so the honest outcome is an atom, not an arced
        op and certainly not a chord.
        """
        beam = _element("OST_StructuralFraming", "100", curve_kind=None)
        result = lift_document_detailed(
            _document(beam), None, None,
            wall_curve_index=_arc_index("100"))
        node = _nodes(result)["100"]
        self.assertEqual(node["kind"], "atom")
        self.assertEqual(
            node["reason"]["code"], AtomReason.CURVE_KIND_UNSUPPORTED.value)
        self.assertIn("create_beam", node["reason"]["detail"])

    def test_beam_with_a_straight_index_row_still_lifts(self) -> None:
        beam = _element(
            "OST_StructuralFraming", "100", curve_kind=LocationCurveKind.LINE)
        result = lift_document_detailed(
            _document(beam), None, None,
            wall_curve_index={"100": {"curve_kind": "line"}})
        self.assertEqual(_nodes(result)["100"]["op_name"], "create_beam")

    def test_curve_kind_refusal_is_not_a_shape_refusal(self) -> None:
        """A refusal by curve kind is TERMINAL: place_family would return a point.

        ``_SHAPE_REFUSALS`` lets an element through to the generic
        ``place_family``. An arced beam must not end up there: a point
        placement would throw away the curve entirely — exactly the
        "allowed it through by discarding the facts" outcome that this
        seam was introduced to forbid.
        """
        from kir.decompile.lift import _SHAPE_REFUSALS

        self.assertNotIn(AtomReason.CURVE_KIND_UNSUPPORTED, _SHAPE_REFUSALS)

    def test_walls_keep_their_working_arc_path(self) -> None:
        """Walls are left untouched: ``create_wall`` can express an arc and it is pinned down."""
        wall = L0Element(
            element_id="200", category="OST_Walls", category_ru="Стены",
            type_id="7", type_name="W200", level_id="10", level_name="L1",
            geom_kind=GeometryKind.CURVE, p0_mm=_P0, p1_mm=_P1,
            rotation_deg=None, bbox_min_mm=(0.0, -100.0, 0.0),
            bbox_max_mm=(_RADIUS, _RADIUS, 3_000.0), host_id=None,
            params={"WALL_USER_HEIGHT_PARAM": 3_000.0},
            curve_kind=LocationCurveKind.ARC)
        result = lift_document_detailed(
            _document(wall), None, None, wall_curve_index=_arc_index("200"))
        node = _nodes(result)["200"]
        self.assertEqual(node["op_name"], "create_wall")
        self.assertIn("arc", node["params"])

    def test_a_wall_whose_arc_is_missing_no_longer_flattens(self) -> None:
        """An arced wall WITHOUT an index row is an atom, not a silent straight line."""
        wall = L0Element(
            element_id="200", category="OST_Walls", category_ru="Стены",
            type_id="7", type_name="W200", level_id="10", level_name="L1",
            geom_kind=GeometryKind.CURVE, p0_mm=_P0, p1_mm=_P1,
            rotation_deg=None, bbox_min_mm=(0.0, -100.0, 0.0),
            bbox_max_mm=(_RADIUS, _RADIUS, 3_000.0), host_id=None,
            params={"WALL_USER_HEIGHT_PARAM": 3_000.0},
            curve_kind=LocationCurveKind.ARC)
        result = lift_document_detailed(_document(wall), None, None)
        node = _nodes(result)["200"]
        self.assertEqual(node["kind"], "atom")
        self.assertEqual(
            node["reason"]["code"], AtomReason.CURVE_KIND_UNSUPPORTED.value)


class TheReasonTravelsToFidelity(unittest.TestCase):
    """The reason must make it to verify/passport without loss."""

    def test_atom_reason_has_a_fidelity_twin(self) -> None:
        self.assertIn(
            AtomReason.CURVE_KIND_UNSUPPORTED.value,
            {reason.value for reason in FidelityReason})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
