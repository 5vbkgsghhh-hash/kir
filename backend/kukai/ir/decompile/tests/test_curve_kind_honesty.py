"""§18.1-следствие — L0 обязан различать вид кривой; хорда запрещена.

Находка M2 аудита 2026-07-28: ``geometry_store`` писал ``geom_kind="curve"``
для ЛЮБОГО ``LocationCurve``. Дуга, сплайн и прямая в L0 неразличимы, боковой
индекс дуг собирался для стен и каркаса, а ПОТРЕБЛЯЛСЯ только стенами. Балка,
труба, воздуховод и лоток с дугой поднимались ХОРДОЙ — без атома, без причины,
без следа; ``verify`` сравнивает только концы и ставит ``exact``. Круглое в
плане здание давало «покрытие 95%» при прямой модели.

На момент написания падали (замерено):

  * ``lift_document_detailed`` на дуговых балке/трубе/воздуховоде/лотке давал
    ``create_beam``/``create_pipe``/``create_duct``/``create_cable_tray`` —
    четыре молчаливые хорды;
  * ``_lift_beam`` принимал ``_context`` и НЕ ЧИТАЛ его, хотя строка с точной
    дугой уже лежала в ``curve.index.json`` (стадия ``curve`` запрашивает
    OST_StructuralFraming наравне со стенами);
  * ``L0Element``/``ExtractedGeometry`` вида кривой не несли вовсе, а
    эмитируемый C# его не мерил.

Дисциплина §18.7: опровергающий тест ДО починки.
"""
from __future__ import annotations

import math
import unittest

from kukai.ir.decompile.geometry_store import (
    GEOMETRY_HELPER_CS,
    parse_geometry,
)
from kukai.ir.decompile.l1_schema import AtomReason, FidelityReason
from kukai.ir.decompile.lift import lift_document_detailed
from kukai.ir.decompile.schema import (
    GeometryKind,
    L0Document,
    L0Element,
    L0SchemaError,
    LevelInfo,
    LocationCurveKind,
    ProjectInfo,
)


_RADIUS = 8_000.0
# Концы четверти окружности радиуса 8 м — те же, что у хорды между ними.
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
    """Строка бокового индекса с ТОЧНОЙ дугой (концы совпадают с L0)."""
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
    """2a — вид кривой обязан мериться в самом захвате."""

    def test_emitted_csharp_classifies_line_arc_other(self) -> None:
        for token in ('__row["curve_kind"]', "as Line", "as Arc",
                      '"line"', '"arc"', '"other"'):
            self.assertIn(token, GEOMETRY_HELPER_CS, token)
        # §18.5/версионный дрейф: тот же запрет, что и во всей эмиссии.
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
        """Отсутствие поля в замороженном L0 = «не мерили», а не «прямая»."""
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
    """2b — не-Line без выразимой дуги = честный атом, НИКОГДА не хорда."""

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
        """Балка с дугой В ИНДЕКСЕ — атом, даже если L0 вида кривой не знает.

        Строка уже лежит в ``curve.index.json`` (стадия ``curve`` запрашивает
        OST_StructuralFraming), а ``_lift_beam`` принимал контекст и не читал
        его. ``create_beam`` дуги не выражает (в реестре у него нет параметра
        ``arc``, в отличие от ``create_wall``), поэтому честный исход —
        атом, а не арочный оп и тем более не хорда.
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
        """Отказ по виду кривой ТЕРМИНАЛЕН: place_family вернул бы точку.

        ``_SHAPE_REFUSALS`` пропускает элемент в обобщённый ``place_family``.
        Дуговая балка туда попасть не должна: точечное размещение выбросило бы
        кривую целиком — ровно тот «разрешил, отбросив факты» исход, ради
        запрета которого шов и заведён.
        """
        from kukai.ir.decompile.lift import _SHAPE_REFUSALS

        self.assertNotIn(AtomReason.CURVE_KIND_UNSUPPORTED, _SHAPE_REFUSALS)

    def test_walls_keep_their_working_arc_path(self) -> None:
        """Стены не трогаем: у ``create_wall`` дуга выразима и пришпилена."""
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
        """Дуговая стена БЕЗ строки индекса — атом, а не тихая прямая."""
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
    """Причина обязана доезжать до verify/паспорта без потери."""

    def test_atom_reason_has_a_fidelity_twin(self) -> None:
        self.assertIn(
            AtomReason.CURVE_KIND_UNSUPPORTED.value,
            {reason.value for reason in FidelityReason})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
