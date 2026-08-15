from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import unittest

from kukai.ir.decompile.curtain_extract import (
    CURTAIN_EXTRACT_SCHEMA_VERSION,
    CURTAIN_INDEX_SCHEMA_VERSION,
    CurtainExtraction,
    CurtainFailureReason,
    CurtainPayloadError,
    CurtainWallRecord,
    CurveState,
    GridDirection,
    GridLineRecord,
    MullionRecord,
    PanelRecord,
    build_curtain_extract_cs,
    extract_curtain_topology,
)
from kukai.llm.revit_execution_pipeline import wrap_user_code
from kukai.security.validation import validate_code_safety


# ── Synthetic fixtures modelled on the real LOT31 census_curtain.json ────────
# The census sample is a "Витраж окно(150)" storefront window: a 1×1 curtain
# grid (one U line, one V line), four panels, and twelve mullions.  These
# helpers reproduce that exact shape while keeping the contract universal.


def _line_wire(line_id: str, *, curved: bool = False) -> dict:
    if curved:
        return {
            "line_id": line_id,
            "curve_state": "curved_unsupported",
            "p0_mm": None,
            "p1_mm": None,
            "existing_segment_count": 1,
            "skipped_segment_count": 0,
            "locked": None,
        }
    return {
        "line_id": line_id,
        "curve_state": "line",
        "p0_mm": [0.0, 0.0, 0.0],
        "p1_mm": [1500.0, 0.0, 0.0],
        "existing_segment_count": 1,
        "skipped_segment_count": 0,
        "locked": False,
    }


def _panel_wire(
    panel_id: str,
    *,
    door: bool = False,
    family: bool = False,
    host: str | None = None,
    type_name: str | None = None,
    type_id: str | None = "7001",
    host_type_id: str | None = None,
    host_type_name: str | None = None,
    u_index: int | None = 0,
    v_index: int | None = 0,
    address_state: str = "ok",
) -> dict:
    """Одна ЯЧЕЙКА сетки (схема /2).

    Тип читается через ``GetTypeId`` и потому есть у панели ЛЮБОГО класса —
    схема /1 брала его только у ``FamilyInstance.Symbol`` и оставляла тип
    панели-стены пустым. ``family_name`` по-прежнему факт только про
    ``FamilyInstance``.
    """

    if type_name is None:
        type_name = "D-2100" if family else "Системная панель"
    return {
        "panel_id": panel_id,
        "is_family_instance": family,
        "family_name": "Дверь витражная" if family else None,
        "type_name": type_name,
        "type_id": type_id,
        "host_panel_id": host,
        "host_panel_type_id": host_type_id,
        "host_panel_type_name": host_type_name,
        "u_index": u_index,
        "v_index": v_index,
        "address_state": address_state,
        "is_door": door,
    }


def _mullion_wire(mullion_id: str, *, curved: bool = False) -> dict:
    if curved:
        return {
            "mullion_id": mullion_id,
            "type_name": "Профиль 50x150",
            "curve_state": "curved_unsupported",
            "p0_mm": None,
            "p1_mm": None,
        }
    return {
        "mullion_id": mullion_id,
        "type_name": "Профиль 50x150",
        "curve_state": "line",
        "p0_mm": [0.0, 0.0, 0.0],
        "p1_mm": [0.0, 3000.0, 0.0],
    }


def _wall_wire(
    wall_id: str,
    *,
    status: str = "ok",
    reason: str | None = None,
    typed_reason: str | None = None,
    elapsed_ms: int | None = None,
    u_grid_lines: list | None = None,
    v_grid_lines: list | None = None,
    panels: list | None = None,
    mullions: list | None = None,
    host_kind: str = "wall",
    default_panel_type_id: str | None = "7000",
    default_panel_type_name: str | None = "Системная панель по умолчанию",
    default_panel_state: str = "ok",
    auto_mullion_types: dict | None = None,
    grid_layout: dict | None = None,
) -> dict:
    return {
        "wall_id": wall_id,
        "status": status,
        "reason": reason,
        "typed_reason": typed_reason,
        "elapsed_ms": elapsed_ms,
        "host_kind": host_kind,
        "default_panel_type_id": (
            default_panel_type_id if status == "ok" else None),
        "default_panel_type_name": (
            default_panel_type_name if status == "ok" else None),
        "default_panel_state": (
            default_panel_state if status == "ok" else "not_captured"),
        "default_panel_source": (
            "AUTO_PANEL_WALL" if status == "ok" else None),
        "auto_mullion_types": (
            {"slots": {}, "state": "not_captured"}
            if auto_mullion_types is None else auto_mullion_types),
        "grid_layout": (
            {"slots": {}, "state": "not_captured"}
            if grid_layout is None else grid_layout),
        "u_grid_lines": [] if u_grid_lines is None else u_grid_lines,
        "v_grid_lines": [] if v_grid_lines is None else v_grid_lines,
        "panels": [] if panels is None else panels,
        "mullions": [] if mullions is None else mullions,
    }


def _census_storefront_wire(wall_id: str = "19227219") -> dict:
    """A wall that reproduces the census sample: 1×1 grid, 4 panels, 12 mullions."""

    return _wall_wire(
        wall_id,
        u_grid_lines=[_line_wire("u1")],
        v_grid_lines=[_line_wire("v1")],
        panels=[
            _panel_wire("p0", door=True, family=True),
            _panel_wire("p1"),
            _panel_wire("p2"),
            _panel_wire("p3"),
        ],
        mullions=[_mullion_wire("m%d" % index) for index in range(12)],
    )


def _payload(walls: list[dict]) -> dict:
    return {
        "schema_version": CURTAIN_EXTRACT_SCHEMA_VERSION,
        "walls": walls,
    }


# ── Parser: the happy path on real-census shapes ─────────────────────────────


class CurtainParserTests(unittest.TestCase):
    def test_census_storefront_shape_parses_to_expected_counts(self) -> None:
        result = extract_curtain_topology(
            _payload([_census_storefront_wire()]))

        record = result.entry_for("19227219")
        self.assertTrue(record.curtain_available)
        self.assertEqual(record.u_line_count, 1)
        self.assertEqual(record.v_line_count, 1)
        self.assertEqual(record.panel_count, 4)
        self.assertEqual(record.mullion_count, 12)
        self.assertEqual(record.door_count, 1)
        self.assertEqual(result.failures, ())

    def test_grid_line_and_mullion_world_mm_endpoints_are_exact(self) -> None:
        result = extract_curtain_topology(
            _payload([_census_storefront_wire()]))
        record = result.entry_for("19227219")

        u_line = record.u_grid_lines[0]
        self.assertIs(u_line.direction, GridDirection.U)
        self.assertIs(u_line.curve_state, CurveState.LINE)
        self.assertEqual(u_line.p0_mm, (0.0, 0.0, 0.0))
        self.assertEqual(u_line.p1_mm, (1500.0, 0.0, 0.0))
        self.assertEqual(u_line.existing_segment_count, 1)
        self.assertEqual(u_line.skipped_segment_count, 0)
        self.assertIs(u_line.locked, False)

        mullion = record.mullions[0]
        self.assertIs(mullion.curve_state, CurveState.LINE)
        self.assertEqual(mullion.p1_mm, (0.0, 3000.0, 0.0))
        self.assertEqual(mullion.type_name, "Профиль 50x150")

    def test_curtain_wall_door_panel_is_flagged(self) -> None:
        result = extract_curtain_topology(
            _payload([_census_storefront_wire()]))
        record = result.entry_for("19227219")

        door = record.panels[0]
        self.assertTrue(door.is_door)
        self.assertTrue(door.is_family_instance)
        self.assertEqual(door.family_name, "Дверь витражная")
        glass = record.panels[1]
        self.assertFalse(glass.is_door)
        self.assertFalse(glass.is_family_instance)
        self.assertIsNone(glass.family_name)

    def test_panel_host_reference_is_retained(self) -> None:
        wall = _wall_wire(
            "100",
            panels=[_panel_wire("p0"), _panel_wire("p1", host="p0")],
        )
        result = extract_curtain_topology(_payload([wall]))
        record = result.entry_for("100")

        self.assertIsNone(record.panels[0].host_panel_id)
        self.assertEqual(record.panels[1].host_panel_id, "p0")

    def test_universal_counts_are_not_hardcoded_to_the_census(self) -> None:
        # A 3×2 grid with 10 panels and 40 mullions must parse identically.
        wall = _wall_wire(
            "555",
            u_grid_lines=[_line_wire("u%d" % index) for index in range(3)],
            v_grid_lines=[_line_wire("v%d" % index) for index in range(2)],
            panels=[_panel_wire("p%d" % index) for index in range(10)],
            mullions=[_mullion_wire("m%d" % index) for index in range(40)],
        )
        record = extract_curtain_topology(_payload([wall])).entry_for("555")

        self.assertEqual(record.u_line_count, 3)
        self.assertEqual(record.v_line_count, 2)
        self.assertEqual(record.panel_count, 10)
        self.assertEqual(record.mullion_count, 40)

    def test_curved_grid_line_is_honest_refusal_not_tessellation(self) -> None:
        wall = _wall_wire(
            "200",
            u_grid_lines=[_line_wire("u1", curved=True)],
            mullions=[_mullion_wire("m1", curved=True)],
        )
        record = extract_curtain_topology(_payload([wall])).entry_for("200")

        curved_line = record.u_grid_lines[0]
        self.assertIs(curved_line.curve_state, CurveState.CURVED_UNSUPPORTED)
        self.assertIsNone(curved_line.p0_mm)
        self.assertIsNone(curved_line.p1_mm)
        # Segment accounting survives even when the curve is deferred.
        self.assertEqual(curved_line.existing_segment_count, 1)
        curved_mullion = record.mullions[0]
        self.assertIs(
            curved_mullion.curve_state, CurveState.CURVED_UNSUPPORTED)
        self.assertIsNone(curved_mullion.p0_mm)

    def test_empty_curtain_grid_is_available_with_zero_counts(self) -> None:
        record = extract_curtain_topology(
            _payload([_wall_wire("300")])).entry_for("300")

        self.assertTrue(record.curtain_available)
        self.assertEqual(record.panel_count, 0)
        self.assertEqual(record.mullion_count, 0)


# ── Parser: honest failure handling (not_curtain, budgets, refusals) ─────────


class CurtainFailureTests(unittest.TestCase):
    def test_not_curtain_wall_lands_in_failures_and_index(self) -> None:
        result = extract_curtain_topology(
            _payload([_wall_wire("400", status="not_curtain")]))

        record = result.entry_for("400")
        self.assertFalse(record.curtain_available)
        self.assertEqual(record.to_dict(), {"curtain_available": False})
        reasons = {failure.reason for failure in result.failures}
        self.assertEqual(reasons, {"not_curtain"})
        # Раньше здесь стояло assertIsNone: квитанция «стена не витражная»
        # уходила БЕЗ причины. На 13A-RD-AR-K2_v33 таких было 14 324 из
        # 14 343 отказов стадии, все — с полноценной строкой индекса рядом,
        # и единственное число, куда они попадали, читалось как «витражи не
        # осилены на 14 тысячах элементов». Причина обязательна, и класс у
        # неё — определение (посмотрели, аспекта нет), а не срез.
        self.assertEqual(
            result.failures[0].typed_reason,
            CurtainFailureReason.ASPECT_NOT_PRESENT)
        self.assertIsNone(result.failures[0].elapsed_ms)

    def test_read_failure_is_kept_out_of_the_index(self) -> None:
        result = extract_curtain_topology(
            _payload([
                _wall_wire(
                    "401", status="failed",
                    reason="curtain read failed: InvalidOperationException"),
            ]))

        with self.assertRaisesRegex(CurtainPayloadError, "absent"):
            result.entry_for("401")
        self.assertEqual(len(result.failures), 1)
        self.assertEqual(result.curtain_index, {})

    def test_time_and_call_budget_failures_are_typed(self) -> None:
        walls = [
            _wall_wire(
                "500", status="failed", reason="time_budget_exceeded",
                typed_reason="time_budget_exceeded", elapsed_ms=2100),
            _wall_wire(
                "501", status="failed", reason="call_budget_exhausted",
                typed_reason="call_budget_exhausted", elapsed_ms=20050),
        ]
        result = extract_curtain_topology(_payload(walls))

        by_id = {failure.wall_id: failure for failure in result.failures}
        self.assertIs(
            by_id["500"].typed_reason,
            CurtainFailureReason.TIME_BUDGET_EXCEEDED)
        self.assertEqual(by_id["500"].elapsed_ms, 2100)
        self.assertIs(
            by_id["501"].typed_reason,
            CurtainFailureReason.CALL_BUDGET_EXHAUSTED)
        self.assertEqual(by_id["501"].elapsed_ms, 20050)

    def test_every_wall_id_is_accounted_for_under_partial_budget(self) -> None:
        walls = [
            _census_storefront_wire("600"),
            _wall_wire(
                "601", status="failed", reason="time_budget_exceeded",
                typed_reason="time_budget_exceeded", elapsed_ms=2001),
            _wall_wire(
                "602", status="failed", reason="call_budget_exhausted",
                typed_reason="call_budget_exhausted", elapsed_ms=20000),
        ]
        result = extract_curtain_topology(_payload(walls))

        accounted = (
            set(result.curtain_index)
            | {failure.wall_id for failure in result.failures})
        self.assertEqual(accounted, {"600", "601", "602"})

    def test_budget_failure_requires_matching_elapsed_and_reason(self) -> None:
        base = _wall_wire(
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
        for wall, pattern in cases:
            with self.subTest(wall=wall):
                with self.assertRaisesRegex(CurtainPayloadError, pattern):
                    extract_curtain_topology(_payload([wall]))

    def test_bridge_envelope_error_is_a_typed_refusal(self) -> None:
        envelope = {"ok": False, "error": "curtain sweep refused"}
        with self.assertRaisesRegex(CurtainPayloadError, "curtain sweep"):
            extract_curtain_topology(envelope)

    def test_bridge_envelope_unwraps_a_successful_result(self) -> None:
        envelope = {
            "ok": True,
            "result": _payload([_census_storefront_wire("800")]),
        }
        result = extract_curtain_topology(envelope)
        self.assertEqual(result.entry_for("800").panel_count, 4)


# ── Parser: malformed payloads fail closed ───────────────────────────────────


class CurtainMalformedPayloadTests(unittest.TestCase):
    def test_schema_version_mismatch_is_refused(self) -> None:
        payload = _payload([_census_storefront_wire()])
        payload["schema_version"] = "kir-decompile-curtain-extract/9"
        with self.assertRaisesRegex(CurtainPayloadError, "schema_version"):
            extract_curtain_topology(payload)

    def test_non_object_payload_is_refused(self) -> None:
        for value in (None, [], "curtain", 3):
            with self.subTest(value=value):
                with self.assertRaises(CurtainPayloadError):
                    extract_curtain_topology(value)

    def test_unexpected_top_level_field_is_refused(self) -> None:
        payload = _payload([_census_storefront_wire()])
        payload["extra"] = True
        with self.assertRaisesRegex(CurtainPayloadError, "unexpected extra"):
            extract_curtain_topology(payload)

    def test_unknown_status_is_refused(self) -> None:
        with self.assertRaisesRegex(CurtainPayloadError, "status is unsupported"):
            extract_curtain_topology(
                _payload([_wall_wire("1", status="maybe")]))

    def test_ok_status_cannot_carry_a_reason(self) -> None:
        wall = _census_storefront_wire("1")
        wall["reason"] = "should not be here"
        with self.assertRaisesRegex(CurtainPayloadError, "cannot carry a reason"):
            extract_curtain_topology(_payload([wall]))

    def test_not_curtain_wall_cannot_carry_topology(self) -> None:
        wall = _wall_wire(
            "1", status="not_curtain", panels=[_panel_wire("p0")])
        with self.assertRaisesRegex(CurtainPayloadError, "cannot carry panels"):
            extract_curtain_topology(_payload([wall]))

    def test_line_state_requires_endpoints(self) -> None:
        bad_line = _line_wire("u1")
        bad_line["p1_mm"] = None
        wall = _wall_wire("1", u_grid_lines=[bad_line])
        with self.assertRaisesRegex(
                CurtainPayloadError, "line grid line requires"):
            extract_curtain_topology(_payload([wall]))

    def test_curved_state_cannot_carry_endpoints(self) -> None:
        bad_line = _line_wire("u1", curved=True)
        bad_line["p0_mm"] = [0.0, 0.0, 0.0]
        wall = _wall_wire("1", u_grid_lines=[bad_line])
        with self.assertRaisesRegex(
                CurtainPayloadError, "curved_unsupported grid line"):
            extract_curtain_topology(_payload([wall]))

    def test_non_family_panel_cannot_carry_family_name(self) -> None:
        panel = _panel_wire("p0")
        panel["family_name"] = "Дверь"
        wall = _wall_wire("1", panels=[panel])
        with self.assertRaisesRegex(
                CurtainPayloadError, "non-family panel"):
            extract_curtain_topology(_payload([wall]))

    def test_a_non_family_panel_MAY_carry_its_own_type(self) -> None:
        """Тип есть у панели любого класса — он читается через GetTypeId.

        Схема /1 запрещала тип не-FamilyInstance и тем самым ЗАКРЕПЛЯЛА
        дыру: у каждой панели-стены тип оставался пустым, хотя лежал рядом.
        """

        panel = _panel_wire("p0", family=False, type_name="Стена",
                            type_id="7002")
        wall = _wall_wire("1", panels=[panel])
        record = extract_curtain_topology(_payload([wall])).entry_for("1")
        self.assertEqual(record.panels[0].type_name, "Стена")
        self.assertEqual(record.panels[0].type_id, "7002")
        self.assertIsNone(record.panels[0].family_name)

    def test_half_an_address_is_refused(self) -> None:
        """Адрес либо прочитан, либо его нет: половина — догадка с видом факта."""

        panel = _panel_wire("p0", address_state="not_a_panel")
        wall = _wall_wire("1", panels=[panel])
        with self.assertRaisesRegex(CurtainPayloadError, "address_state"):
            extract_curtain_topology(_payload([wall]))

    def test_effective_type_of_a_wall_filled_cell_is_the_bodys(self) -> None:
        panel = _panel_wire(
            "p0", family=True, type_name="Стена", type_id="7099",
            host="9003", host_type_id="7002",
            host_type_name="НР_ВТ_Сэндвич панель_30мм")
        wall = _wall_wire("1", panels=[panel])
        record = extract_curtain_topology(_payload([wall])).entry_for("1")
        self.assertEqual(record.panels[0].effective_type_id, "7002")
        self.assertEqual(
            record.panels[0].effective_type_name,
            "НР_ВТ_Сэндвич панель_30мм")

    def test_a_legacy_index_reads_as_an_address_that_was_never_captured(
            self) -> None:
        """Разбор схемы /1 читается — и честно говорит, что адреса в нём нет."""

        from kukai.ir.decompile.curtain_extract import (
            CURTAIN_INDEX_SCHEMA_VERSION_LEGACY, CellAddressState)

        legacy = {
            "schema_version": CURTAIN_INDEX_SCHEMA_VERSION_LEGACY,
            "curtain_index": {
                "1": {
                    "curtain_available": True,
                    "u_grid_lines": [],
                    "v_grid_lines": [],
                    "panels": [{
                        "panel_id": "p0",
                        "is_family_instance": True,
                        "family_name": "Системная панель",
                        "type_name": "Стеклопакет",
                        "host_panel_id": None,
                        "is_door": False,
                    }],
                    "mullions": [],
                },
            },
            "failures": [],
        }
        record = CurtainExtraction.from_dict(legacy).entry_for("1")
        panel = record.panels[0]
        self.assertIs(panel.address_state, CellAddressState.NOT_CAPTURED)
        self.assertIsNone(panel.u_index)
        self.assertIsNone(record.default_panel_type_id)

    def test_negative_segment_count_is_refused(self) -> None:
        bad_line = _line_wire("u1")
        bad_line["existing_segment_count"] = -1
        wall = _wall_wire("1", u_grid_lines=[bad_line])
        with self.assertRaisesRegex(
                CurtainPayloadError, "existing_segment_count"):
            extract_curtain_topology(_payload([wall]))

    def test_non_finite_endpoint_is_refused(self) -> None:
        bad_line = _line_wire("u1")
        bad_line["p0_mm"] = [float("nan"), 0.0, 0.0]
        wall = _wall_wire("1", u_grid_lines=[bad_line])
        with self.assertRaisesRegex(CurtainPayloadError, "finite number"):
            extract_curtain_topology(_payload([wall]))

    def test_duplicate_wall_id_is_refused(self) -> None:
        walls = [_census_storefront_wire("1"), _census_storefront_wire("1")]
        with self.assertRaisesRegex(
                CurtainPayloadError, "duplicate curtain wall_id"):
            extract_curtain_topology(_payload(walls))

    def test_duplicate_grid_line_id_within_wall_is_refused(self) -> None:
        wall = _wall_wire(
            "1",
            u_grid_lines=[_line_wire("dup")],
            v_grid_lines=[_line_wire("dup")],
        )
        with self.assertRaisesRegex(
                CurtainPayloadError, "duplicate grid line id"):
            extract_curtain_topology(_payload([wall]))

    def test_duplicate_panel_id_within_wall_is_refused(self) -> None:
        wall = _wall_wire(
            "1", panels=[_panel_wire("dup"), _panel_wire("dup")])
        with self.assertRaisesRegex(
                CurtainPayloadError, "duplicate panel id"):
            extract_curtain_topology(_payload([wall]))


# ── Serialization round-trip and determinism ────────────────────────────────


class CurtainSerializationTests(unittest.TestCase):
    def _rich_result(self) -> CurtainExtraction:
        walls = [
            _census_storefront_wire("19227219"),
            _wall_wire("19239100", status="not_curtain"),
            _wall_wire(
                "19239147", status="failed",
                reason="time_budget_exceeded",
                typed_reason="time_budget_exceeded", elapsed_ms=2100),
            _wall_wire(
                "19239192", status="failed",
                reason="curtain read failed: NullReferenceException"),
        ]
        return extract_curtain_topology(_payload(walls))

    def test_round_trip_through_json_is_stable(self) -> None:
        first = self._rich_result()
        text = first.to_json()
        second = CurtainExtraction.from_json(text)

        self.assertEqual(second.to_json(), text)

    def test_to_dict_carries_schema_version(self) -> None:
        result = self._rich_result()
        self.assertEqual(
            result.to_dict()["schema_version"], CURTAIN_INDEX_SCHEMA_VERSION)

    def test_index_and_failures_are_wall_id_ordered(self) -> None:
        # Numeric wall ids sort numerically, not lexically.
        walls = [
            _census_storefront_wire("100"),
            _census_storefront_wire("2"),
            _census_storefront_wire("30"),
        ]
        result = extract_curtain_topology(_payload(walls))
        self.assertEqual(list(result.curtain_index), ["2", "30", "100"])

    def test_result_is_independent_of_input_wall_order(self) -> None:
        walls = [
            _census_storefront_wire("19227219"),
            _wall_wire("19239100", status="not_curtain"),
            _wall_wire(
                "19239147", status="failed", reason="time_budget_exceeded",
                typed_reason="time_budget_exceeded", elapsed_ms=2100),
        ]
        forward = extract_curtain_topology(_payload(walls)).to_json()
        reversed_json = extract_curtain_topology(
            _payload(list(reversed(walls)))).to_json()
        self.assertEqual(forward, reversed_json)

    def test_result_json_is_identical_under_two_hash_seeds(self) -> None:
        script = (
            "import hashlib, json;"
            "from kukai.ir.decompile.curtain_extract import "
            "extract_curtain_topology, CURTAIN_EXTRACT_SCHEMA_VERSION;"
            "wall={'wall_id':'1','status':'ok','reason':None,"
            "'typed_reason':None,'elapsed_ms':None,'host_kind':'wall',"
            "'default_panel_type_id':'7000',"
            "'default_panel_type_name':'Системная панель',"
            "'default_panel_state':'ok',"
            "'default_panel_source':'AUTO_PANEL_WALL',"
            "'auto_mullion_types':{'slots':{},'state':'not_captured'},"
            "'grid_layout':{'slots':{},'state':'not_captured'},"
            "'u_grid_lines':[{'line_id':'u1','curve_state':'line',"
            "'p0_mm':[0.0,0.0,0.0],'p1_mm':[1.0,0.0,0.0],"
            "'existing_segment_count':1,'skipped_segment_count':0,"
            "'locked':True}],'v_grid_lines':[],"
            "'panels':[{'panel_id':'p0','is_family_instance':False,"
            "'family_name':None,'type_name':'Стеклопакет','type_id':'7001',"
            "'host_panel_id':None,'host_panel_type_id':None,"
            "'host_panel_type_name':None,'u_index':0,'v_index':0,"
            "'address_state':'ok','is_door':False}],'mullions':[]};"
            "payload={'schema_version':CURTAIN_EXTRACT_SCHEMA_VERSION,"
            "'walls':[wall]};"
            "print(hashlib.sha256("
            "extract_curtain_topology(payload).to_json()"
            ".encode()).hexdigest())"
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


class CurtainRecordInvariantTests(unittest.TestCase):
    def test_grid_line_direction_must_match_containing_list(self) -> None:
        # A U-direction line placed in the v_grid_lines list is caught by the
        # v-list validator ("v grid line mislabelled").
        u_line = GridLineRecord.from_wire(
            GridDirection.U, _line_wire("u1"), "line")
        with self.assertRaisesRegex(CurtainPayloadError, "v grid line"):
            CurtainWallRecord("1", True, v_grid_lines=(u_line,))

    def test_not_curtain_record_rejects_topology(self) -> None:
        panel = PanelRecord.from_wire(_panel_wire("p0"), "panel")
        with self.assertRaisesRegex(CurtainPayloadError, "non-curtain wall"):
            CurtainWallRecord("1", False, panels=(panel,))

    def test_curtain_extraction_rejects_duplicate_wall_records(self) -> None:
        record = CurtainWallRecord.not_curtain("1")
        with self.assertRaisesRegex(
                CurtainPayloadError, "duplicate wall_id"):
            CurtainExtraction(records=(record, record))


# ── C# emitter: read-only contract, budgets, determinism ─────────────────────


class CurtainCSharpEmitterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.body = build_curtain_extract_cs(["19227219", 456])

    def test_read_only_curtain_grid_contract_is_emitted(self) -> None:
        for token in (
            ".CurtainGrid",
            ".GetUGridLineIds()",
            ".GetVGridLineIds()",
            ".GetPanelIds()",
            ".GetMullionIds()",
            "as CurtainGridLine",
            ".FullCurve",
            ".ExistingSegmentCurves",
            ".SkippedSegmentCurves",
            "as Mullion",
            ".FindHostPanel()",
            "BuiltInCategory.OST_Doors",
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

    def test_curved_curve_is_the_honest_default_marker(self) -> None:
        # A curve is only promoted to "line" for a bound straight Line; every
        # row is initialized to the honest curved_unsupported marker first.
        self.assertIn('"curve_state"] = "curved_unsupported"', self.body)
        self.assertIn('__row["curve_state"] = "line"', self.body)
        self.assertIn("as Line", self.body)

    def test_cooperative_element_and_call_budget_harness_is_emitted(self) -> None:
        for token in (
            # Budgets are timed with mscorlib only. Stopwatch lives in
            # System.dll, which is absent from the reference closure on part of
            # the fleet — measured live 2026-08-04, CS1069 "forwarded to
            # assembly 'System'". Full qualification does not help: CS1069 is a
            # REFERENCE fault, not a using fault. See
            # tests/bridge_reference_closure.py.
            "DateTime.UtcNow.Ticks",
            "TimeSpan.TicksPerMillisecond",
            "long __cwElementBudgetMs = 2000L;",
            "long __cwCallBudgetMs = 20000L;",
            "__cwElementWatchT0",
            "__cwCallWatchT0",
            '"time_budget_exceeded"',
            '"call_budget_exhausted"',
            '__row["elapsed_ms"] = __cwBudgetElapsed',
            "Func<bool> __cwBudgetExceeded",
        ):
            self.assertIn(token, self.body)
        # Partial topology is discarded on any budget overrun.
        self.assertIn("__uLines.Clear();", self.body)
        self.assertIn("__panels.Clear();", self.body)
        self.assertIn("__mullions.Clear();", self.body)
        # Checkpoints are placed between the grid-line, panel, and mullion
        # stages so an id is never partially emitted after the deadline.
        self.assertGreaterEqual(self.body.count("if (!__cwBudgetExceeded())"), 2)
        self.assertIn(
            "foreach (string __requestedId in __cwRequestedIds)", self.body)
        self.assertIn(
            "if (__cwFound.Count == __cwRequestedSet.Count) break;", self.body)

    def test_every_curtain_host_is_walked_not_only_walls(self) -> None:
        """Сетку несут ТРИ рода носителей, а не один (дизайн 28.07, пункт 4).

        Пока коллектор смотрел только на стены, панели витражных систем и
        витражных кровель не попадали в индекс ВООБЩЕ, и снаружи это было
        неотличимо от «компилятор не умеет панели».
        """

        for category in ("OST_Walls", "OST_CurtaSystem", "OST_Roofs"):
            with self.subTest(category=category):
                self.assertIn(f"BuiltInCategory.{category}", self.body)
        for host_class in ("as Wall", "is Wall", "is CurtainSystem",
                           "is RoofBase"):
            with self.subTest(host_class=host_class):
                self.assertIn(host_class, self.body)
        self.assertIn('"host has no CurtainGrid"', self.body)
        self.assertIn('__row["status"] = "not_curtain"', self.body)

    def test_cell_address_and_both_type_spaces_are_captured(self) -> None:
        """Четыре пункта захвата из дизайна — каждый виден в эмиссии."""

        # 1. адрес ячейки — через опорные линии разрезки, а не порядок выдачи
        self.assertIn("GetRefGridLines", self.body)
        self.assertIn('__panelRow["u_index"]', self.body)
        self.assertIn('__panelRow["v_index"]', self.body)
        self.assertIn('"address_state"] = "ok"', self.body)
        # 2. тип у панели ЛЮБОГО класса, не только FamilyInstance
        self.assertIn("__panelElement.GetTypeId()", self.body)
        # 3. тип панели по умолчанию у носителя — ОБА параметра с меткой
        #    «Curtain Panel» (см. TheCurtainPanelParameterIsTheWallOne)
        self.assertIn("BuiltInParameter.AUTO_PANEL_WALL", self.body)
        self.assertIn("BuiltInParameter.AUTO_PANEL", self.body)
        self.assertIn('__row["default_panel_type_id"]', self.body)
        self.assertIn('__row["default_panel_state"]', self.body)
        # 4. тип ТЕЛА ячейки (стена в ячейке)
        self.assertIn("FindHostPanel", self.body)
        self.assertIn('"host_panel_type_id"', self.body)

    def test_address_definition_is_shared_with_the_forward_emitter(
            self) -> None:
        """ОДНО определение адреса на оба направления.

        Два определения разошлись бы молча: захват писал бы один адрес,
        эмиттер искал бы другую ячейку, и обе стороны по отдельности
        выглядели бы правильными.

        РАЗЛИЧАЕТСЯ РОВНО ОДНО: имя переменной ЧИТАЕМОГО документа. Захват с
        30.07 умеет снимать связь и передаёт ``__src``; прямому компилятору
        читать нечего кроме хозяина. Проверяется поэтому не «тот же текст», а
        «тот же текст с точностью до документа» — иначе достаточно было бы
        переписать формулу адреса вместе с документом, и тест бы это принял.
        """

        from kukai.ir.authoring import curtain_cell_address_cs

        shared = curtain_cell_address_cs("", document="__src")
        self.assertIn(shared.strip(), self.body)
        self.assertEqual(
            curtain_cell_address_cs("").replace(
                "doc.GetElement(", "__src.GetElement("),
            shared)

    def test_a_read_that_failed_carries_no_default_panel_type(self) -> None:
        """Отказ не имеет права нести половину факта о носителе."""

        self.assertIn('if ((string)__row["status"] != "ok")', self.body)

    def test_emitter_returns_exact_protocol_shell(self) -> None:
        for token in (
            '"schema_version", "kir-decompile-curtain-extract/5"',
            '"walls", __cwWallRows',
            '__row["wall_id"]',
            '__row["status"]',
        ):
            self.assertIn(token, self.body)

    def test_budgets_are_configurable(self) -> None:
        custom = build_curtain_extract_cs(
            ["123"], element_budget_ms=1_234, call_budget_ms=5_678)
        self.assertIn("long __cwElementBudgetMs = 1234L;", custom)
        self.assertIn("long __cwCallBudgetMs = 5678L;", custom)
        self.assertEqual(
            build_curtain_extract_cs(["123"]),
            build_curtain_extract_cs(
                ["123"], element_budget_ms=2_000, call_budget_ms=20_000),
        )

    def test_budget_arguments_are_strict(self) -> None:
        for value in (0, -1, True, 1.5, 2**63):
            with self.subTest(element_budget_ms=value):
                with self.assertRaisesRegex(ValueError, "element_budget_ms"):
                    build_curtain_extract_cs(
                        ["123"], element_budget_ms=value)  # type: ignore[arg-type]
            with self.subTest(call_budget_ms=value):
                with self.assertRaisesRegex(ValueError, "call_budget_ms"):
                    build_curtain_extract_cs(
                        ["123"], call_budget_ms=value)  # type: ignore[arg-type]

    def test_wall_id_validation_is_bounded_and_deterministic(self) -> None:
        with self.assertRaisesRegex(ValueError, "sequence"):
            build_curtain_extract_cs("123")  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, "numeric Revit id"):
            build_curtain_extract_cs(["123); return null;"])
        with self.assertRaisesRegex(ValueError, "unique"):
            build_curtain_extract_cs([1, "1"])
        with self.assertRaisesRegex(ValueError, "at least one"):
            build_curtain_extract_cs([])

    def test_no_placeholder_survives_emission(self) -> None:
        self.assertNotIn("__CW_", self.body)

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
            "from kukai.ir.decompile.curtain_extract "
            "import build_curtain_extract_cs; "
            "b=build_curtain_extract_cs(['19227219','456']); "
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


class TheCurtainPanelParameterIsTheWallOne(unittest.TestCase):
    """Почему параметров ДВА и почему читаются оба.

    ЗАМЕР 28.07, живой прогон v4 (фасад SOB6.2, Revit 2023): захват читал
    ``BuiltInParameter.AUTO_PANEL`` и получил null на ВСЕХ 195 витражных
    носителях, из-за чего 311 ячеек с уже прочитанным адресом отказали.

    ДОКАЗАТЕЛЬСТВО (не вики): ``RevitAPI.xml`` из эталонного пакета сборок —
    та самая документация, что едет вместе с ``RevitAPI.dll``. В ней ДВА
    члена перечисления несут одну и ту же метку «Curtain Panel»:

        <member name="F:Autodesk.Revit.DB.BuiltInParameter.AUTO_PANEL_WALL">
          <summary> "Curtain Panel" </summary>
        <member name="F:Autodesk.Revit.DB.BuiltInParameter.AUTO_PANEL">
          <summary> "Curtain Panel" </summary>

    Суффикс ``_WALL`` называет семейство носителя: у типа витражной СТЕНЫ
    параметр этот. Одинаковая ВИДИМАЯ метка — ровно та ловушка, из-за
    которой ошибка не читалась ни в UI, ни в коде.

    Тест смотрит в сами сборки, а не в чью-то запись о них: если Autodesk
    переименует или уберёт член, тест упадёт здесь, а не на живой модели.
    """

    XML_CANDIDATES = (
        os.path.expanduser(
            "~/.nuget/packages/revit_all_main_versions_api_x64/"
            "{version}.0.0/lib/net48/RevitAPI.xml"),
        os.path.expanduser(
            "~/.nuget/packages/revit_all_main_versions_api_x64/"
            "{version}.0.0/lib/net8.0/RevitAPI.xml"),
    )

    def _api_doc(self, version: str) -> str | None:
        import pathlib
        for template in self.XML_CANDIDATES:
            path = pathlib.Path(template.format(version=version))
            if path.is_file():
                return path.read_text(encoding="utf-8", errors="replace")
        return None

    def test_both_parameters_carry_the_same_visible_label(self) -> None:
        import re
        seen_any = False
        for version in ("2021", "2023", "2026"):
            document = self._api_doc(version)
            if document is None:
                continue
            seen_any = True
            for member in ("AUTO_PANEL_WALL", "AUTO_PANEL"):
                with self.subTest(version=version, member=member):
                    match = re.search(
                        r'<member name="F:Autodesk\.Revit\.DB\.'
                        rf'BuiltInParameter\.{member}">\s*<summary>(.*?)'
                        r'</summary>', document, re.S)
                    self.assertIsNotNone(
                        match, f"{member} отсутствует в RevitAPI.xml {version}")
                    self.assertIn("Curtain Panel", match.group(1))
        if not seen_any:
            self.skipTest("эталонные сборки Revit недоступны на этой машине")

    def test_the_wall_parameter_is_asked_first(self) -> None:
        """Порядок значим: у стены отвечает _WALL, и спрашивать его надо
        раньше, иначе провенанс укажет на параметр, который промолчал."""

        body = build_curtain_extract_cs(["123"])
        table = body[body.index("var __cwPanelBips"):]
        table = table[:table.index("};")]
        self.assertLess(
            table.index("AUTO_PANEL_WALL"),
            table.index("BuiltInParameter.AUTO_PANEL\n"),
            "AUTO_PANEL_WALL опрашивается первым")

    def test_the_three_truths_of_a_missing_default_are_distinguished(
            self) -> None:
        """null больше не значит три разные вещи сразу."""

        body = build_curtain_extract_cs(["123"])
        for state in ('"unreadable"', '"none"', '"ok"', '"not_captured"'):
            with self.subTest(state=state):
                self.assertIn(state, body)
        self.assertIn('__row["default_panel_source"]', body)
        self.assertNotIn("""BuiltInParameter.AUTO_PANEL);
                            if (__cwAuto != null)""", body)

    def test_a_state_and_a_value_cannot_disagree(self) -> None:
        from kukai.ir.decompile.curtain_extract import DefaultPanelState

        with self.assertRaisesRegex(CurtainPayloadError, "default_panel_state"):
            CurtainWallRecord(
                "1", True, default_panel_state=DefaultPanelState.OK)
        with self.assertRaisesRegex(CurtainPayloadError, "default_panel_state"):
            CurtainWallRecord(
                "1", True, default_panel_type_id="7000",
                default_panel_state=DefaultPanelState.NONE)

    def test_an_index_of_schema_two_reads_as_not_captured(self) -> None:
        """Живой v4 — схема /2, и её null означает НЕИЗВЕСТНО.

        Прочитать его как «пусто» значило бы задним числом объявить каждую
        ячейку фасада авторской — на основании поля, которого в разборе не
        было.
        """

        from kukai.ir.decompile.curtain_extract import (
            CURTAIN_INDEX_SCHEMA_VERSION_ADDRESSED, DefaultPanelState)

        v2_row = {
            "curtain_available": True,
            "host_kind": "wall",
            "default_panel_type_id": None,
            "default_panel_type_name": None,
            "u_grid_lines": [], "v_grid_lines": [], "mullions": [],
            "panels": [_panel_wire("p0")],
        }
        extraction = CurtainExtraction.from_dict({
            "schema_version": CURTAIN_INDEX_SCHEMA_VERSION_ADDRESSED,
            "curtain_index": {"1": v2_row},
            "failures": [],
        })
        record = extraction.entry_for("1")
        self.assertIs(
            record.default_panel_state, DefaultPanelState.NOT_CAPTURED)
        # адрес из /2 берётся — он там честный
        self.assertEqual(record.panels[0].u_index, 0)
