from __future__ import annotations

import math
import os
import subprocess
import sys
import unittest

from kukai.ir.decompile.curve_extract import (
    CURVE_EXTRACT_SCHEMA_VERSION,
    CURVE_INDEX_SCHEMA_VERSION,
    CurveExtraction,
    CurveFailureReason,
    CurveKind,
    CurvePayloadError,
    CurveRecord,
    build_curve_extract_cs,
    extract_curves,
)
from kukai.ir.decompile.recompile import ArcCurve
from kukai.llm.revit_execution_pipeline import wrap_user_code
from kukai.security.validation import validate_code_safety


# ── Synthetic fixtures modelled on the real LOT31 rounded-facade shape ───────
# The operator caught the flat-world bug on LOT31's curtained tower and rounded
# facade: an arc storefront/wall collapsed to the chord between its endpoints.
# The arc fixture below is a *geometrically correct* quarter of a circle in the
# plan (Z-up) plane — center at the origin, radius 8000 mm, sweeping the first
# quadrant — so its endpoints, axes, angles, and normal are mutually consistent
# rather than invented numbers.  The contract stays universal; the shape only
# motivates it.

_FACADE_RADIUS_MM = 8000.0
# Endpoints implied by (center, radius, x/y axes, [0, pi/2]): the arc starts at
# center + r*x_axis and ends at center + r*y_axis.
_FACADE_P0 = [_FACADE_RADIUS_MM, 0.0, 0.0]
_FACADE_P1 = [0.0, _FACADE_RADIUS_MM, 0.0]


def _arc_wire() -> dict:
    return {
        "center_mm": [0.0, 0.0, 0.0],
        "radius_mm": _FACADE_RADIUS_MM,
        "x_axis": [1.0, 0.0, 0.0],
        "y_axis": [0.0, 1.0, 0.0],
        "start_angle_rad": 0.0,
        "end_angle_rad": math.pi / 2.0,
    }


def _element_wire(
    element_id: str,
    *,
    status: str = "ok",
    reason: str | None = None,
    typed_reason: str | None = None,
    elapsed_ms: int | None = None,
    category: str | None = None,
    curve_kind: str | None = None,
    p0_mm: list | None = None,
    p1_mm: list | None = None,
    arc: dict | None = None,
    normal: list | None = None,
) -> dict:
    return {
        "element_id": element_id,
        "status": status,
        "reason": reason,
        "typed_reason": typed_reason,
        "elapsed_ms": elapsed_ms,
        "category": category,
        "curve_kind": curve_kind,
        "p0_mm": p0_mm,
        "p1_mm": p1_mm,
        "arc": arc,
        "normal": normal,
    }


def _line_element(element_id: str = "19227219") -> dict:
    return _element_wire(
        element_id,
        category="OST_Walls",
        curve_kind="line",
        p0_mm=[0.0, 0.0, 0.0],
        p1_mm=[5000.0, 0.0, 0.0],
    )


def _arc_element(element_id: str = "19227220") -> dict:
    """A curved facade wall: the real arc, not the flattened chord."""

    return _element_wire(
        element_id,
        category="OST_Walls",
        curve_kind="arc",
        p0_mm=list(_FACADE_P0),
        p1_mm=list(_FACADE_P1),
        arc=_arc_wire(),
        normal=[0.0, 0.0, 1.0],
    )


def _spline_element(element_id: str = "19227221") -> dict:
    return _element_wire(
        element_id,
        category="OST_StructuralFraming",
        curve_kind="spline_unsupported",
        p0_mm=[0.0, 0.0, 0.0],
        p1_mm=[3000.0, 1000.0, 500.0],
    )


def _no_location_element(element_id: str = "19227222") -> dict:
    return _element_wire(
        element_id,
        category="OST_Furniture",
        curve_kind="no_location_curve",
    )


def _payload(elements: list[dict]) -> dict:
    return {
        "schema_version": CURVE_EXTRACT_SCHEMA_VERSION,
        "elements": elements,
    }


# ── Parser: the happy path on line / arc / spline / no-location shapes ────────


class CurveParserTests(unittest.TestCase):
    def test_straight_line_records_world_mm_endpoints(self) -> None:
        record = extract_curves(_payload([_line_element()])).entry_for(
            "19227219")

        self.assertIs(record.curve_kind, CurveKind.LINE)
        self.assertEqual(record.category, "OST_Walls")
        self.assertEqual(record.p0_mm, (0.0, 0.0, 0.0))
        self.assertEqual(record.p1_mm, (5000.0, 0.0, 0.0))
        self.assertIsNone(record.arc)
        self.assertIsNone(record.normal)

    def test_curved_wall_records_the_real_arc_not_the_chord(self) -> None:
        record = extract_curves(_payload([_arc_element()])).entry_for(
            "19227220")

        self.assertIs(record.curve_kind, CurveKind.ARC)
        # The endpoints are the true arc endpoints, and the arc is the exact
        # centreline — the chord between p0 and p1 is NOT what is stored.
        self.assertEqual(record.p0_mm, tuple(_FACADE_P0))
        self.assertEqual(record.p1_mm, tuple(_FACADE_P1))
        self.assertIsInstance(record.arc, ArcCurve)
        self.assertEqual(record.arc.center_mm, (0.0, 0.0, 0.0))
        self.assertEqual(record.arc.radius_mm, _FACADE_RADIUS_MM)
        self.assertEqual(record.arc.x_axis, (1.0, 0.0, 0.0))
        self.assertEqual(record.arc.y_axis, (0.0, 1.0, 0.0))
        self.assertEqual(record.arc.start_angle_rad, 0.0)
        self.assertAlmostEqual(record.arc.end_angle_rad, math.pi / 2.0)
        self.assertEqual(record.normal, (0.0, 0.0, 1.0))
        # The stored radius (8 m) is far from the chord half-length, proving the
        # arc is genuinely curved and not a degenerate near-straight segment.
        chord = math.dist(_FACADE_P0, _FACADE_P1)
        self.assertGreater(record.arc.radius_mm, chord / 2.0)

    def test_spline_is_honest_refusal_with_endpoints_not_tessellation(
            self) -> None:
        record = extract_curves(_payload([_spline_element()])).entry_for(
            "19227221")

        self.assertIs(record.curve_kind, CurveKind.SPLINE_UNSUPPORTED)
        # The endpoints are still captured (fail-closed), but no interior curve
        # is fabricated: the spline is neither tessellated nor chorded to a line.
        self.assertEqual(record.p0_mm, (0.0, 0.0, 0.0))
        self.assertEqual(record.p1_mm, (3000.0, 1000.0, 500.0))
        self.assertIsNone(record.arc)
        self.assertIsNone(record.normal)

    def test_no_location_curve_element_carries_no_geometry(self) -> None:
        record = extract_curves(
            _payload([_no_location_element()])).entry_for("19227222")

        self.assertIs(record.curve_kind, CurveKind.NO_LOCATION_CURVE)
        self.assertEqual(record.category, "OST_Furniture")
        self.assertIsNone(record.p0_mm)
        self.assertIsNone(record.p1_mm)
        self.assertIsNone(record.arc)

    def test_mixed_batch_of_all_kinds_parses_and_is_fully_accounted(
            self) -> None:
        result = extract_curves(_payload([
            _line_element("1"),
            _arc_element("2"),
            _spline_element("3"),
            _no_location_element("4"),
        ]))

        kinds = {rec.element_id: rec.curve_kind for rec in result}
        self.assertEqual(kinds, {
            "1": CurveKind.LINE,
            "2": CurveKind.ARC,
            "3": CurveKind.SPLINE_UNSUPPORTED,
            "4": CurveKind.NO_LOCATION_CURVE,
        })
        self.assertEqual(result.failures, ())
        self.assertEqual(set(result.curve_index), {"1", "2", "3", "4"})

    def test_missing_category_is_permitted(self) -> None:
        wire = _line_element("5")
        wire["category"] = None
        record = extract_curves(_payload([wire])).entry_for("5")
        self.assertIsNone(record.category)


# ── Parser: honest failure handling (resolve/read errors, budgets) ───────────


class CurveFailureTests(unittest.TestCase):
    def test_read_failure_is_kept_out_of_the_index(self) -> None:
        result = extract_curves(_payload([
            _element_wire(
                "401", status="failed",
                reason="location read failed: InvalidOperationException"),
        ]))

        with self.assertRaisesRegex(CurvePayloadError, "absent"):
            result.entry_for("401")
        self.assertEqual(len(result.failures), 1)
        self.assertEqual(result.curve_index, {})

    def test_time_and_call_budget_failures_are_typed(self) -> None:
        elements = [
            _element_wire(
                "500", status="failed", reason="time_budget_exceeded",
                typed_reason="time_budget_exceeded", elapsed_ms=2100),
            _element_wire(
                "501", status="failed", reason="call_budget_exhausted",
                typed_reason="call_budget_exhausted", elapsed_ms=20050),
        ]
        result = extract_curves(_payload(elements))

        by_id = {failure.element_id: failure for failure in result.failures}
        self.assertIs(
            by_id["500"].typed_reason,
            CurveFailureReason.TIME_BUDGET_EXCEEDED)
        self.assertEqual(by_id["500"].elapsed_ms, 2100)
        self.assertIs(
            by_id["501"].typed_reason,
            CurveFailureReason.CALL_BUDGET_EXHAUSTED)
        self.assertEqual(by_id["501"].elapsed_ms, 20050)

    def test_every_element_id_is_accounted_for_under_partial_budget(
            self) -> None:
        elements = [
            _arc_element("600"),
            _element_wire(
                "601", status="failed", reason="time_budget_exceeded",
                typed_reason="time_budget_exceeded", elapsed_ms=2001),
            _element_wire(
                "602", status="failed", reason="call_budget_exhausted",
                typed_reason="call_budget_exhausted", elapsed_ms=20000),
        ]
        result = extract_curves(_payload(elements))

        accounted = (
            set(result.curve_index)
            | {failure.element_id for failure in result.failures})
        self.assertEqual(accounted, {"600", "601", "602"})

    def test_budget_failure_requires_matching_elapsed_and_reason(self) -> None:
        base = _element_wire(
            "700", status="failed", reason="time_budget_exceeded")
        cases = (
            ({**base, "typed_reason": "time_budget_exceeded"},
             "elapsed_ms requires a typed_reason|elapsed_ms"),
            ({**base, "typed_reason": "not_a_reason", "elapsed_ms": 5},
             "typed_reason is unsupported"),
            ({**base, "typed_reason": "call_budget_exhausted",
              "elapsed_ms": 5},
             "typed reason must match the failed reason"),
            ({**base, "elapsed_ms": 5},
             "elapsed_ms requires a typed_reason"),
        )
        for wire, pattern in cases:
            with self.subTest(wire=wire):
                with self.assertRaisesRegex(CurvePayloadError, pattern):
                    extract_curves(_payload([wire]))

    def test_failed_element_cannot_carry_geometry(self) -> None:
        wire = _element_wire(
            "1", status="failed", reason="location read failed")
        wire["curve_kind"] = "line"
        wire["p0_mm"] = [0.0, 0.0, 0.0]
        wire["p1_mm"] = [1.0, 0.0, 0.0]
        with self.assertRaisesRegex(
                CurvePayloadError, "failed element cannot carry"):
            extract_curves(_payload([wire]))

    def test_bridge_envelope_error_is_a_typed_refusal(self) -> None:
        envelope = {"ok": False, "error": "curve sweep refused"}
        with self.assertRaisesRegex(CurvePayloadError, "curve sweep"):
            extract_curves(envelope)

    def test_bridge_envelope_unwraps_a_successful_result(self) -> None:
        envelope = {"ok": True, "result": _payload([_arc_element("800")])}
        result = extract_curves(envelope)
        self.assertIs(result.entry_for("800").curve_kind, CurveKind.ARC)


# ── Parser: malformed payloads fail closed ───────────────────────────────────


class CurveMalformedPayloadTests(unittest.TestCase):
    def test_schema_version_mismatch_is_refused(self) -> None:
        payload = _payload([_line_element()])
        payload["schema_version"] = "kir-decompile-curve-extract/9"
        with self.assertRaisesRegex(CurvePayloadError, "schema_version"):
            extract_curves(payload)

    def test_non_object_payload_is_refused(self) -> None:
        for value in (None, [], "curve", 3):
            with self.subTest(value=value):
                with self.assertRaises(CurvePayloadError):
                    extract_curves(value)

    def test_unexpected_top_level_field_is_refused(self) -> None:
        payload = _payload([_line_element()])
        payload["extra"] = True
        with self.assertRaisesRegex(CurvePayloadError, "unexpected extra"):
            extract_curves(payload)

    def test_unexpected_element_field_is_refused(self) -> None:
        wire = _line_element("1")
        wire["surprise"] = 1
        with self.assertRaisesRegex(CurvePayloadError, "unexpected surprise"):
            extract_curves(_payload([wire]))

    def test_unknown_status_is_refused(self) -> None:
        with self.assertRaisesRegex(
                CurvePayloadError, "status is unsupported"):
            extract_curves(_payload([_element_wire("1", status="maybe")]))

    def test_ok_status_cannot_carry_a_reason(self) -> None:
        wire = _line_element("1")
        wire["reason"] = "should not be here"
        with self.assertRaisesRegex(
                CurvePayloadError, "cannot carry a reason"):
            extract_curves(_payload([wire]))

    def test_ok_status_requires_a_curve_kind(self) -> None:
        wire = _element_wire("1", status="ok")
        with self.assertRaisesRegex(CurvePayloadError, "requires a curve_kind"):
            extract_curves(_payload([wire]))

    def test_unknown_curve_kind_is_refused(self) -> None:
        wire = _element_wire(
            "1", status="ok", curve_kind="helix",
            p0_mm=[0.0, 0.0, 0.0], p1_mm=[1.0, 0.0, 0.0])
        with self.assertRaisesRegex(
                CurvePayloadError, "curve_kind is unsupported"):
            extract_curves(_payload([wire]))

    def test_line_requires_both_endpoints(self) -> None:
        wire = _line_element("1")
        wire["p1_mm"] = None
        with self.assertRaisesRegex(
                CurvePayloadError, "line requires p0_mm and p1_mm"):
            extract_curves(_payload([wire]))

    def test_line_cannot_carry_arc_geometry(self) -> None:
        wire = _line_element("1")
        wire["arc"] = _arc_wire()
        with self.assertRaisesRegex(
                CurvePayloadError, "line cannot carry arc"):
            extract_curves(_payload([wire]))

    def test_arc_requires_arc_and_normal(self) -> None:
        wire = _arc_element("1")
        wire["normal"] = None
        with self.assertRaisesRegex(
                CurvePayloadError, "arc requires arc and normal"):
            extract_curves(_payload([wire]))

    def test_no_location_curve_cannot_carry_endpoints(self) -> None:
        wire = _no_location_element("1")
        wire["p0_mm"] = [0.0, 0.0, 0.0]
        with self.assertRaisesRegex(
                CurvePayloadError, "no_location_curve cannot carry"):
            extract_curves(_payload([wire]))

    def test_arc_with_non_unit_axis_is_refused_by_shared_arccurve(
            self) -> None:
        # Axis validation is delegated to ArcCurve; a non-unit x_axis is caught.
        wire = _arc_element("1")
        wire["arc"] = {**_arc_wire(), "x_axis": [2.0, 0.0, 0.0]}
        with self.assertRaisesRegex(CurvePayloadError, "arc is invalid"):
            extract_curves(_payload([wire]))

    def test_arc_with_non_orthogonal_axes_is_refused(self) -> None:
        wire = _arc_element("1")
        wire["arc"] = {**_arc_wire(), "y_axis": [1.0, 0.0, 0.0]}
        with self.assertRaisesRegex(CurvePayloadError, "arc is invalid"):
            extract_curves(_payload([wire]))

    def test_arc_with_zero_span_is_refused(self) -> None:
        wire = _arc_element("1")
        wire["arc"] = {**_arc_wire(), "end_angle_rad": 0.0}
        with self.assertRaisesRegex(CurvePayloadError, "arc is invalid"):
            extract_curves(_payload([wire]))

    def test_arc_normal_must_match_axis_cross_product(self) -> None:
        wire = _arc_element("1")
        wire["normal"] = [0.0, 0.0, -1.0]
        with self.assertRaisesRegex(
                CurvePayloadError, "normal must equal x_axis cross y_axis"):
            extract_curves(_payload([wire]))

    def test_arc_normal_must_be_unit_length(self) -> None:
        wire = _arc_element("1")
        wire["normal"] = [0.0, 0.0, 2.0]
        with self.assertRaisesRegex(
                CurvePayloadError, "normal must be unit length"):
            extract_curves(_payload([wire]))

    def test_non_finite_endpoint_is_refused(self) -> None:
        wire = _line_element("1")
        wire["p0_mm"] = [float("nan"), 0.0, 0.0]
        with self.assertRaisesRegex(CurvePayloadError, "finite number"):
            extract_curves(_payload([wire]))

    def test_duplicate_element_id_is_refused(self) -> None:
        with self.assertRaisesRegex(
                CurvePayloadError, "duplicate curve element_id"):
            extract_curves(_payload([_line_element("1"), _arc_element("1")]))


# ── Serialization round-trip and determinism ─────────────────────────────────


class CurveSerializationTests(unittest.TestCase):
    def _rich_result(self) -> CurveExtraction:
        elements = [
            _arc_element("19227219"),
            _line_element("19239100"),
            _spline_element("19239147"),
            _no_location_element("19239170"),
            _element_wire(
                "19239192", status="failed",
                reason="time_budget_exceeded",
                typed_reason="time_budget_exceeded", elapsed_ms=2100),
            _element_wire(
                "19239199", status="failed",
                reason="location read failed: NullReferenceException"),
        ]
        return extract_curves(_payload(elements))

    def test_round_trip_through_json_is_stable(self) -> None:
        first = self._rich_result()
        text = first.to_json()
        second = CurveExtraction.from_json(text)
        self.assertEqual(second.to_json(), text)

    def test_to_dict_carries_schema_version(self) -> None:
        result = self._rich_result()
        self.assertEqual(
            result.to_dict()["schema_version"], CURVE_INDEX_SCHEMA_VERSION)

    def test_index_and_failures_are_element_id_ordered(self) -> None:
        # Numeric ids sort numerically, not lexically.
        elements = [
            _line_element("100"),
            _line_element("2"),
            _line_element("30"),
        ]
        result = extract_curves(_payload(elements))
        self.assertEqual(list(result.curve_index), ["2", "30", "100"])

    def test_result_is_independent_of_input_element_order(self) -> None:
        elements = [
            _arc_element("19227219"),
            _line_element("19239100"),
            _spline_element("19239147"),
        ]
        forward = extract_curves(_payload(elements)).to_json()
        reversed_json = extract_curves(
            _payload(list(reversed(elements)))).to_json()
        self.assertEqual(forward, reversed_json)

    def test_result_json_is_identical_under_two_hash_seeds(self) -> None:
        script = (
            "import hashlib, math, json;"
            "from kukai.ir.decompile.curve_extract import "
            "extract_curves, CURVE_EXTRACT_SCHEMA_VERSION;"
            "el={'element_id':'1','status':'ok','reason':None,"
            "'typed_reason':None,'elapsed_ms':None,'category':'OST_Walls',"
            "'curve_kind':'arc','p0_mm':[8000.0,0.0,0.0],"
            "'p1_mm':[0.0,8000.0,0.0],'arc':{'center_mm':[0.0,0.0,0.0],"
            "'radius_mm':8000.0,'x_axis':[1.0,0.0,0.0],'y_axis':[0.0,1.0,0.0],"
            "'start_angle_rad':0.0,'end_angle_rad':math.pi/2.0},"
            "'normal':[0.0,0.0,1.0]};"
            "payload={'schema_version':CURVE_EXTRACT_SCHEMA_VERSION,"
            "'elements':[el]};"
            "print(hashlib.sha256("
            "extract_curves(payload).to_json().encode()).hexdigest())"
        )
        hashes = []
        for seed in ("1", "8675309"):
            environment = dict(os.environ)
            environment["PYTHONHASHSEED"] = seed
            hashes.append(subprocess.check_output(
                [sys.executable, "-c", script],
                env=environment,
                text=True,
            ).strip())
        self.assertEqual(len(set(hashes)), 1)


# ── Record-level construction invariants ─────────────────────────────────────


class CurveRecordInvariantTests(unittest.TestCase):
    def test_no_location_record_rejects_geometry(self) -> None:
        with self.assertRaisesRegex(
                CurvePayloadError, "no_location_curve record cannot carry"):
            CurveRecord(
                "1", CurveKind.NO_LOCATION_CURVE,
                p0_mm=(0.0, 0.0, 0.0), p1_mm=(1.0, 0.0, 0.0))

    def test_line_record_requires_endpoints(self) -> None:
        with self.assertRaisesRegex(
                CurvePayloadError, "line record requires"):
            CurveRecord("1", CurveKind.LINE)

    def test_arc_record_requires_arc_and_normal(self) -> None:
        with self.assertRaisesRegex(
                CurvePayloadError, "arc record requires"):
            CurveRecord(
                "1", CurveKind.ARC,
                p0_mm=(8000.0, 0.0, 0.0), p1_mm=(0.0, 8000.0, 0.0))

    def test_spline_record_cannot_carry_arc(self) -> None:
        arc = ArcCurve(
            center_mm=(0.0, 0.0, 0.0), radius_mm=8000.0,
            x_axis=(1.0, 0.0, 0.0), y_axis=(0.0, 1.0, 0.0),
            start_angle_rad=0.0, end_angle_rad=math.pi / 2.0)
        with self.assertRaisesRegex(
                CurvePayloadError, "spline_unsupported record cannot carry"):
            CurveRecord(
                "1", CurveKind.SPLINE_UNSUPPORTED,
                p0_mm=(0.0, 0.0, 0.0), p1_mm=(1.0, 0.0, 0.0),
                arc=arc, normal=(0.0, 0.0, 1.0))

    def test_curve_extraction_rejects_duplicate_records(self) -> None:
        record = CurveRecord("1", CurveKind.NO_LOCATION_CURVE)
        with self.assertRaisesRegex(
                CurvePayloadError, "duplicate element_id"):
            CurveExtraction(records=(record, record))


# ── C# emitter: read-only contract, budgets, determinism ─────────────────────


class CurveCSharpEmitterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.body = build_curve_extract_cs(["19227219", 456])

    def test_read_only_location_curve_contract_is_emitted(self) -> None:
        for token in (
            "as LocationCurve",
            "__locationCurve.Curve",
            "as Line",
            "as Arc",
            ".GetEndPoint(0)",
            ".GetEndParameter(0)",
            ".GetEndParameter(1)",
            "__arc.Center",
            "__arc.Radius",
            "__arc.XDirection",
            "__arc.YDirection",
            "__arc.Normal",
            "UnitUtils.ConvertFromInternalUnits",
        ):
            self.assertIn(token, self.body)

    def test_no_write_or_geometry_side_effects_are_emitted(self) -> None:
        for forbidden in (
            "new Transaction",
            "get_Geometry",
            "Tessellate",
            "304.8",
            ".Delete(",
        ):
            self.assertNotIn(forbidden, self.body)

    def test_line_arc_and_spline_kinds_are_all_emitted(self) -> None:
        self.assertIn('__row["curve_kind"] = "line"', self.body)
        self.assertIn('__row["curve_kind"] = "arc"', self.body)
        self.assertIn('__row["curve_kind"] = "spline_unsupported"', self.body)
        self.assertIn('__row["curve_kind"] = "no_location_curve"', self.body)

    def test_spline_is_never_tessellated_or_chorded_to_a_line(self) -> None:
        # The comment and code path make the fail-closed contract explicit: a
        # spline keeps its endpoints and is marked unsupported, never widened
        # into a straight Line and never tessellated.
        self.assertIn(
            "HermiteSpline / NurbSpline / any other curve", self.body)
        self.assertNotIn(".Tessellate", self.body)

    def test_arc_span_is_validated_before_promotion(self) -> None:
        # An arc is only promoted to the "arc" kind when its span is in the
        # (0, 2*pi] contract the shared ArcCurve enforces; otherwise it is the
        # honest spline_unsupported marker (never chorded).
        self.assertIn("__span > 0.0", self.body)
        self.assertIn("2.0 * Math.PI + 1.0e-8", self.body)

    def test_cooperative_element_and_call_budget_harness_is_emitted(
            self) -> None:
        for token in (
            "System.Diagnostics.Stopwatch.StartNew()",
            "long __cvElementBudgetMs = 2000L;",
            "long __cvCallBudgetMs = 20000L;",
            "__cvElementWatch.ElapsedMilliseconds",
            "__cvCallWatch.ElapsedMilliseconds",
            '"time_budget_exceeded"',
            '"call_budget_exhausted"',
            '__row["elapsed_ms"] = __cvBudgetElapsed',
        ):
            self.assertIn(token, self.body)
        self.assertIn(
            "foreach (string __requestedId in __cvRequestedIds)", self.body)
        self.assertIn(
            "if (__cvFound.Count == __cvRequestedSet.Count) break;", self.body)

    def test_version_safe_id_resolution_is_used(self) -> None:
        # ElementId.ToString() is the version-safe key; no int/long ElementId
        # constructor fork is emitted.
        self.assertIn("__element.Id.ToString()", self.body)
        self.assertNotIn("new ElementId(", self.body)

    def test_emitter_returns_exact_protocol_shell(self) -> None:
        for token in (
            '"schema_version", "kir-decompile-curve-extract/1"',
            '"elements", __cvElementRows',
            '__row["element_id"]',
            '__row["status"]',
        ):
            self.assertIn(token, self.body)

    def test_budgets_are_configurable(self) -> None:
        custom = build_curve_extract_cs(
            ["123"], element_budget_ms=1_234, call_budget_ms=5_678)
        self.assertIn("long __cvElementBudgetMs = 1234L;", custom)
        self.assertIn("long __cvCallBudgetMs = 5678L;", custom)
        self.assertEqual(
            build_curve_extract_cs(["123"]),
            build_curve_extract_cs(
                ["123"], element_budget_ms=2_000, call_budget_ms=20_000),
        )

    def test_budget_arguments_are_strict(self) -> None:
        for value in (0, -1, True, 1.5, 2**63):
            with self.subTest(element_budget_ms=value):
                with self.assertRaisesRegex(ValueError, "element_budget_ms"):
                    build_curve_extract_cs(
                        ["123"], element_budget_ms=value)  # type: ignore[arg-type]
            with self.subTest(call_budget_ms=value):
                with self.assertRaisesRegex(ValueError, "call_budget_ms"):
                    build_curve_extract_cs(
                        ["123"], call_budget_ms=value)  # type: ignore[arg-type]

    def test_element_id_validation_is_bounded_and_deterministic(self) -> None:
        with self.assertRaisesRegex(ValueError, "sequence"):
            build_curve_extract_cs("123")  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, "numeric Revit id"):
            build_curve_extract_cs(["123); return null;"])
        with self.assertRaisesRegex(ValueError, "unique"):
            build_curve_extract_cs([1, "1"])
        with self.assertRaisesRegex(ValueError, "at least one"):
            build_curve_extract_cs([])

    def test_no_placeholder_survives_emission(self) -> None:
        self.assertNotIn("__CV_", self.body)

    def test_standard_wrapper_and_static_safety_accept_emitter(self) -> None:
        self.assertIsNone(validate_code_safety(self.body))
        wrapped = wrap_user_code(self.body)
        self.assertIn(
            "public static object Execute(Document doc, UIDocument uidoc)",
            wrapped,
        )

    def test_emitted_body_is_identical_under_two_hash_seeds(self) -> None:
        script = (
            "import hashlib; "
            "from kukai.ir.decompile.curve_extract "
            "import build_curve_extract_cs; "
            "b=build_curve_extract_cs(['19227219','456']); "
            "print(hashlib.sha256(b.encode()).hexdigest())"
        )
        hashes = []
        for seed in ("1", "8675309"):
            environment = dict(os.environ)
            environment["PYTHONHASHSEED"] = seed
            hashes.append(subprocess.check_output(
                [sys.executable, "-c", script],
                env=environment,
                text=True,
            ).strip())
        self.assertEqual(len(set(hashes)), 1)


if __name__ == "__main__":
    unittest.main()
