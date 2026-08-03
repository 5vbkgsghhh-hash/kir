from __future__ import annotations

import copy
import json
import math
import unittest

from kukai.ir.decompile.curtain_extract import CurveState
from kukai.ir.decompile.family_placement_extract import (
    FAMILY_PLACEMENT_EXTRACT_SCHEMA_VERSION,
    FAMILY_PLACEMENT_INDEX_SCHEMA_VERSION,
    FamilyPlacementExtraction,
    FamilyPlacementPayloadError,
    FamilyPlacementRecord,
    FamilyPlacementType,
    build_family_placement_extract_cs,
    parse_family_placement_index,
)
from kukai.ir.decompile.family_placement_extract import _FT_TO_MM
from kukai.ir.decompile.group_extract import (
    GROUP_EXTRACT_SCHEMA_VERSION,
    GROUP_INDEX_SCHEMA_VERSION,
    LEGACY_GROUP_INDEX_SCHEMA_VERSION,
    GroupExtraction,
    GroupIndexPayloadError,
    GroupInstanceRecord,
    build_group_extract_cs,
    parse_group_index,
)
from kukai.ir.decompile.group_relations import analyze_group_relations
from kukai.ir.decompile.pipeline import _rows_of
from kukai.llm.revit_execution_pipeline import wrap_user_code
from kukai.security.validation import validate_code_safety


def _family_raw(element_id: str = "10") -> dict:
    return {
        "element_id": element_id,
        "symbol_id": "800",
        "type_name": "Стол 1200",
        "family_name": "Стол офисный",
        "placement_type": "OneLevelBased",
        "in_place": False,
        "mirrored": True,
        "hand_flipped": False,
        "facing_flipped": True,
        "super_component_id": None,
        "group_id": "90",
        "host_id": None,
        "host_class": None,
        "hand_orientation": [1, 0, 0],
        "facing_orientation": [0, 1, 0],
        "point_ft": [1, -2, 3.5],
        "rotation_rad": math.pi / 2,
        "status": "ok",
    }


# MEASURED (2026-07-27, SKLNK_EOM_R26_V2, Revit 2026): element 1268396 in
# ``backend/data/decompile/sklnk_eom_r26_v2/family_placement.index.json`` is
# a live ``CurveBased`` FamilyInstance -- Обобщенные модели /
# «Техстронг_ОЗК : 4 стороны», hosted on cable tray 1221482. Its persisted
# row today reads ``placement_available: false, point_mm: null,
# rotation_deg: null`` (see the frozen fixture below) even though the live
# model exposes ``Location as LocationCurve`` -> a straight Line from
# [155643,-5766,565] to [155643,-5766,4910] mm. This helper reproduces that
# exact element's raw-extract shape (as a fixed extractor would emit it) so
# the falsifying test below is not a synthetic example.
def _curve_based_raw(element_id: str = "1268396") -> dict:
    p0_mm = (155643.0, -5766.0, 565.0)
    p1_mm = (155643.0, -5766.0, 4910.0)
    return {
        "element_id": element_id,
        "symbol_id": "1268385",
        "type_name": "Техстронг_ОЗК : 4 стороны",
        "family_name": "Обобщенные модели",
        "placement_type": "CurveBased",
        "in_place": False,
        "mirrored": False,
        "hand_flipped": False,
        "facing_flipped": False,
        "super_component_id": None,
        "group_id": None,
        "host_id": "1221482",
        "host_class": "CableTray",
        "hand_orientation": [0.0, 0.0, 1.0],
        "facing_orientation": [1.0, 0.0, 0.0],
        "curve_state": "line",
        "curve_p0_ft": [value / _FT_TO_MM for value in p0_mm],
        "curve_p1_ft": [value / _FT_TO_MM for value in p1_mm],
        "status": "ok",
    }


def _group_raw(
    element_id: str,
    members: list[str],
    *,
    type_id: str = "500",
) -> dict:
    return {
        "element_id": element_id,
        "group_type_id": type_id,
        "group_type_name": "Тип группы",
        "member_ids": members,
        "group_id_parent": None,
        "attached_detail_type_count": 0,
        "origin_ft": [1, 2, 3],
        "rotation_rad": math.pi,
        "reference_level_id": "42",
        "origin_level_offset_ft": 0.5,
        "status": "ok",
    }


class FamilyPlacementIndexTests(unittest.TestCase):
    def test_raw_units_and_state_are_normalized_without_l0_mutation(self) -> None:
        record = FamilyPlacementRecord.from_raw(_family_raw())
        self.assertEqual(record.placement_type, FamilyPlacementType.ONE_LEVEL_BASED)
        self.assertEqual(record.point_mm, (304.8, -609.6, 1066.8))
        self.assertAlmostEqual(record.rotation_deg, 90.0)
        self.assertTrue(record.mirrored)
        self.assertTrue(record.facing_flipped)
        self.assertEqual(record.group_id, "90")

    def test_absent_location_pair_is_an_explicit_unavailable_record(self) -> None:
        raw = _family_raw()
        del raw["point_ft"]
        del raw["rotation_rad"]
        record = FamilyPlacementRecord.from_raw(raw)
        self.assertFalse(record.placement_available)
        self.assertIsNone(record.point_mm)
        self.assertIsNone(record.rotation_deg)

    def test_partial_or_invalid_raw_rows_fail_closed(self) -> None:
        partial = _family_raw()
        del partial["rotation_rad"]
        with self.assertRaises(FamilyPlacementPayloadError):
            FamilyPlacementRecord.from_raw(partial)

        non_unit = _family_raw()
        non_unit["hand_orientation"] = [2, 0, 0]
        with self.assertRaises(FamilyPlacementPayloadError):
            FamilyPlacementRecord.from_raw(non_unit)

        extra = _family_raw()
        extra["unknown"] = 1
        with self.assertRaises(FamilyPlacementPayloadError):
            FamilyPlacementRecord.from_raw(extra)

        impossible = _family_raw()
        impossible.update({
            "mirrored": True,
            "hand_flipped": False,
            "facing_flipped": False,
        })
        with self.assertRaisesRegex(
                FamilyPlacementPayloadError, "must equal.*XOR"):
            FamilyPlacementRecord.from_raw(impossible)

    def test_versioned_bundle_roundtrips_canonically_and_rejects_duplicates(
            self) -> None:
        extraction = FamilyPlacementExtraction.from_rows([
            _family_raw("20"), _family_raw("3"),
        ])
        payload = extraction.to_dict()
        self.assertEqual(
            payload["schema_version"], FAMILY_PLACEMENT_INDEX_SCHEMA_VERSION)
        self.assertEqual(list(payload["family_placement_index"]), ["3", "20"])
        self.assertEqual(
            FamilyPlacementExtraction.from_json(extraction.to_json()),
            extraction,
        )
        self.assertEqual(
            parse_family_placement_index(payload),
            extraction.family_placement_index,
        )
        with self.assertRaises(FamilyPlacementPayloadError):
            FamilyPlacementExtraction.from_rows([
                _family_raw("3"), _family_raw("3"),
            ])


class FamilyPlacementCurveBasedTests(unittest.TestCase):
    """CurveBased FamilyInstances carry a LocationCurve, not a LocationPoint.

    MEASURED (2026-07-27, SKLNK_EOM_R26_V2): 1916 elements, 67.7% honest
    lift coverage, and the *entire* remaining gap (79 elements) was every
    single CurveBased row -- all with a real, straight-Line LocationCurve
    the extractor never read. See ``_curve_based_raw`` for the exact live
    element (1268396) this reproduces.
    """

    def test_curve_based_line_raw_row_becomes_available_placement(self) -> None:
        # THE falsifying test: on the unmodified extractor this raises
        # FamilyPlacementPayloadError (curve_state/curve_p0_ft/curve_p1_ft
        # are "unexpected" fields) instead of yielding a usable placement.
        record = FamilyPlacementRecord.from_raw(_curve_based_raw())
        self.assertEqual(record.placement_type, FamilyPlacementType.CURVE_BASED)
        self.assertTrue(record.placement_available)
        self.assertIsNone(record.point_mm)
        self.assertIsNone(record.rotation_deg)
        self.assertIs(record.curve_state, CurveState.LINE)
        self.assertIsNotNone(record.curve_p0_mm)
        self.assertIsNotNone(record.curve_p1_mm)
        for actual, expected in zip(
                record.curve_p0_mm or (), (155643.0, -5766.0, 565.0)):
            self.assertAlmostEqual(actual, expected, places=6)
        for actual, expected in zip(
                record.curve_p1_mm or (), (155643.0, -5766.0, 4910.0)):
            self.assertAlmostEqual(actual, expected, places=6)
        self.assertEqual(record.host_id, "1221482")
        self.assertEqual(record.host_class, "CableTray")

    def test_curved_unsupported_state_alone_stays_unavailable(self) -> None:
        # An honestly-recorded non-straight curve (arc/spline/unbound) does
        # not grant availability: there is no exact geometry to place from.
        raw = _curve_based_raw()
        raw["curve_state"] = "curved_unsupported"
        del raw["curve_p0_ft"]
        del raw["curve_p1_ft"]
        record = FamilyPlacementRecord.from_raw(raw)
        self.assertIs(record.curve_state, CurveState.CURVED_UNSUPPORTED)
        self.assertFalse(record.placement_available)
        self.assertIsNone(record.curve_p0_mm)
        self.assertIsNone(record.curve_p1_mm)

    def test_line_curve_requires_both_endpoints(self) -> None:
        raw = _curve_based_raw()
        del raw["curve_p1_ft"]
        with self.assertRaises(FamilyPlacementPayloadError):
            FamilyPlacementRecord.from_raw(raw)

    def test_curved_unsupported_state_cannot_carry_endpoints(self) -> None:
        raw = _curve_based_raw()
        raw["curve_state"] = "curved_unsupported"
        with self.assertRaises(FamilyPlacementPayloadError):
            FamilyPlacementRecord.from_raw(raw)

    def test_point_and_line_curve_are_mutually_exclusive(self) -> None:
        # Revit's Location is either a LocationPoint or a LocationCurve for
        # one instance, never both (MEASURED: no counterexample across the
        # SKLNK_EOM_R26_V2 census). A row claiming both is malformed.
        raw = _curve_based_raw()
        raw["point_ft"] = [1, -2, 3.5]
        raw["rotation_rad"] = math.pi / 2
        with self.assertRaises(FamilyPlacementPayloadError):
            FamilyPlacementRecord.from_raw(raw)

    def test_persisted_v1_rows_without_curve_fields_stay_legal(self) -> None:
        # Frozen L0 1.0 side-index rows (e.g. the real, currently-persisted
        # sklnk_eom_r26_v2/family_placement.index.json row for 1268396)
        # never carry curve_state/curve_p0_mm/curve_p1_mm. Absence must stay
        # legal, not become a schema error.
        v1_row = {
            "symbol_id": "1268385",
            "type_name": "4 стороны",
            "family_name": "Техстронг_ОЗК",
            "placement_type": "CurveBased",
            "in_place": False,
            "mirrored": False,
            "hand_flipped": False,
            "facing_flipped": False,
            "super_component_id": None,
            "group_id": None,
            "host_id": "1221482",
            "host_class": "CableTray",
            "hand_orientation": [0.0, 1.9475703179545603e-15, 1.0],
            "facing_orientation": [-0.40479010787298697,
                                    -0.9144096284314681,
                                    1.7808770507849856e-15],
            "placement_available": False,
            "point_mm": None,
            "rotation_deg": None,
        }
        record = FamilyPlacementRecord.from_dict("1268396", v1_row)
        self.assertIsNone(record.curve_state)
        self.assertIsNone(record.curve_p0_mm)
        self.assertIsNone(record.curve_p1_mm)
        self.assertFalse(record.placement_available)

        # MEASURED (demo side index: 59927 rows, almost all point-based):
        # to_dict() omits curve_state/curve_p0_mm/curve_p1_mm entirely when
        # there is no curve to report (mirrors curtain_extract.
        # CurtainWallRecord.to_dict()'s "not applicable => key absent"
        # contract), so this row's canonical shape is byte-identical to the
        # legacy V1 shape it came from. Re-parsing it must still round-trip.
        upgraded = record.to_dict()
        self.assertNotIn("curve_state", upgraded)
        self.assertNotIn("curve_p0_mm", upgraded)
        self.assertNotIn("curve_p1_mm", upgraded)
        self.assertEqual(upgraded, v1_row)
        roundtripped = FamilyPlacementRecord.from_dict("1268396", upgraded)
        self.assertEqual(roundtripped, record)

    def test_persisted_v2_rows_with_curve_fields_roundtrip(self) -> None:
        extraction = FamilyPlacementExtraction.from_rows(
            [_curve_based_raw("1268396")])
        record = extraction.entry_for("1268396")
        payload = record.to_dict()
        self.assertEqual(payload["curve_state"], "line")
        self.assertIsNotNone(payload["curve_p0_mm"])
        self.assertIsNotNone(payload["curve_p1_mm"])
        roundtripped = FamilyPlacementRecord.from_dict("1268396", payload)
        self.assertEqual(roundtripped, record)


class GroupIndexTests(unittest.TestCase):
    def test_transform_units_and_partial_observation_are_honest(self) -> None:
        complete = GroupInstanceRecord.from_raw(_group_raw("10", ["1", "2"]))
        self.assertTrue(complete.transform_available)
        for actual, expected in zip(
                complete.origin_mm or (), (304.8, 609.6, 914.4)):
            self.assertAlmostEqual(actual, expected)
        self.assertAlmostEqual(complete.rotation_deg, 180.0)
        self.assertTrue(complete.level_binding_available)
        self.assertEqual(complete.reference_level_id, "42")
        self.assertAlmostEqual(
            complete.origin_level_offset_mm or 0.0, 152.4)

        origin_only = _group_raw("11", ["3"])
        del origin_only["rotation_rad"]
        partial = GroupInstanceRecord.from_raw(origin_only)
        self.assertFalse(partial.transform_available)
        for actual, expected in zip(
                partial.origin_mm or (), (304.8, 609.6, 914.4)):
            self.assertAlmostEqual(actual, expected)
        self.assertIsNone(partial.rotation_deg)

        legacy = _group_raw("12", ["4"])
        del legacy["reference_level_id"]
        del legacy["origin_level_offset_ft"]
        unobserved = GroupInstanceRecord.from_raw(legacy)
        self.assertFalse(unobserved.level_binding_available)
        self.assertIsNone(unobserved.reference_level_id)
        self.assertIsNone(unobserved.origin_level_offset_mm)

        broken = _group_raw("13", ["5"])
        del broken["origin_level_offset_ft"]
        with self.assertRaisesRegex(
                GroupIndexPayloadError, "partial group level binding"):
            GroupInstanceRecord.from_raw(broken)

    def test_definitions_use_a_reference_and_record_but_do_not_repair_drift(
            self) -> None:
        extraction = GroupExtraction.from_rows([
            _group_raw("30", ["300", "301"]),
            _group_raw("10", ["100", "101", "102"]),
            _group_raw("20", ["200", "201", "202"]),
        ])
        definition = extraction.definitions[0]
        self.assertEqual(definition.reference_instance_id, "10")
        self.assertEqual(
            [slot.reference_member_id for slot in definition.slots],
            ["100", "101", "102"],
        )
        self.assertEqual(definition.comparison_basis, "ordered_cardinality_only")
        self.assertEqual(len(extraction.composition_mismatches), 1)
        mismatch = extraction.composition_mismatches[0]
        self.assertEqual(mismatch.instance_id, "30")
        self.assertEqual(mismatch.expected_member_count, 3)
        self.assertEqual(mismatch.actual_member_count, 2)
        # The divergent instance remains untouched in the authoritative rows.
        self.assertEqual(extraction.instances["30"]["member_ids"], ["300", "301"])

    def test_versioned_bundle_roundtrips_and_detects_derived_tampering(self) -> None:
        extraction = GroupExtraction.from_rows([
            _group_raw("2", ["20", "21"]),
            _group_raw("1", ["10", "11"]),
        ])
        payload = extraction.to_dict()
        self.assertEqual(payload["schema_version"], GROUP_INDEX_SCHEMA_VERSION)
        self.assertEqual(GroupExtraction.from_json(extraction.to_json()), extraction)
        self.assertEqual(
            parse_group_index(payload["group_index"]),
            payload,
        )

        legacy = copy.deepcopy(payload)
        legacy["schema_version"] = LEGACY_GROUP_INDEX_SCHEMA_VERSION
        for instance in legacy["group_index"]["instances"].values():
            instance.pop("level_binding_available")
            instance.pop("reference_level_id")
            instance.pop("origin_level_offset_mm")
        upgraded = GroupExtraction.from_dict(legacy)
        self.assertEqual(
            upgraded.to_dict()["schema_version"],
            GROUP_INDEX_SCHEMA_VERSION)
        self.assertTrue(all(
            not row["level_binding_available"]
            for row in upgraded.instances.values()))

        tampered = copy.deepcopy(payload)
        definition = tampered["group_index"]["definitions"]["500"]
        definition["reference_instance_id"] = "2"
        with self.assertRaises(GroupIndexPayloadError):
            GroupExtraction.from_dict(tampered)

        duplicate = _group_raw("3", ["30", "30"])
        with self.assertRaises(GroupIndexPayloadError):
            GroupInstanceRecord.from_raw(duplicate)

    def test_json_is_independent_of_input_order(self) -> None:
        rows = [_group_raw("10", ["1"]), _group_raw("2", ["2"])]
        left = GroupExtraction.from_rows(rows).to_json()
        right = GroupExtraction.from_rows(reversed(rows)).to_json()
        self.assertEqual(json.loads(left), json.loads(right))

    def test_cross_instance_duplicate_claim_is_ambiguous_not_guessed(
            self) -> None:
        extraction = GroupExtraction.from_rows([
            _group_raw("10", ["100", "shared"], type_id="500"),
            _group_raw("20", ["200", "shared"], type_id="600"),
        ])

        analysis = analyze_group_relations(
            extraction, {"100", "200", "shared", "ungrouped"})

        membership = analysis.relations_dict()["group_membership"]
        self.assertEqual(set(membership), {"100", "200"})
        self.assertNotIn("shared", membership)
        unmatched = analysis.relations_dict()[
            "group_membership_unmatched"]
        self.assertEqual(unmatched["ambiguous_group_claim_count"], 1)
        self.assertEqual(unmatched["absent_from_l0_count"], 0)
        self.assertEqual(
            analysis.boundary_by_source["shared"], "ambiguous:shared")


# ── C# emitters: read-only contract, budgets, determinism (Wave A1b) ─────────


class FamilyPlacementCSharpEmitterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.body = build_family_placement_extract_cs(["19227219", 456])

    def test_read_only_placement_contract_is_emitted(self) -> None:
        for token in (
            "as FamilyInstance",
            "__instance.Symbol",
            "__symbol.Family",
            # FamilyPlacementType lives on Family, not FamilySymbol.
            "__family.FamilyPlacementType.ToString()",
            "__family.IsInPlace",
            "__instance.Mirrored",
            "__instance.HandFlipped",
            "__instance.FacingFlipped",
            "__instance.SuperComponent",
            "__instance.GroupId",
            "__instance.Host",
            ".GetType().Name",
            "__instance.HandOrientation",
            "__instance.FacingOrientation",
            # ``Location`` читается ЧЕРЕЗ СВОЙ СТРАЖ (2026-07-29): раньше
            # бросок этого свойства убивал ВСЮ строку через общий catch, а
            # значит и уже прочитанные символ/тип/носитель. Каст остался
            # прежним, изменился только источник.
            "__fpTryLocation(__instance)",
            "__rawLocation as LocationPoint",
            "__location.Point",
            "__location.Rotation",
        ):
            self.assertIn(token, self.body)

    def test_no_write_geometry_or_conversion_side_effects_are_emitted(
            self) -> None:
        # Position stays in RAW feet; the offline parser owns the 304.8 factor.
        for forbidden in (
            "new Transaction",
            "get_Geometry",
            "Tessellate",
            "304.8",
            "UnitUtils.ConvertFromInternalUnits",
            ".Delete(",
            ".IntegerValue",
        ):
            self.assertNotIn(forbidden, self.body)

    def test_invalid_group_id_becomes_null(self) -> None:
        # GroupId is emitted via the ElementId.InvalidElementId guard so a
        # non-grouped instance carries null rather than the invalid id string.
        self.assertIn("ElementId.InvalidElementId", self.body)

    def test_cooperative_element_and_call_budget_harness_is_emitted(
            self) -> None:
        for token in (
            "System.Diagnostics.Stopwatch.StartNew()",
            "long __fpElementBudgetMs = 2000L;",
            "long __fpCallBudgetMs = 20000L;",
            "__fpElementWatch.ElapsedMilliseconds",
            "__fpCallWatch.ElapsedMilliseconds",
        ):
            self.assertIn(token, self.body)
        self.assertIn(
            "foreach (string __requestedId in __fpRequestedIds)", self.body)
        self.assertIn(
            "if (__fpFound.Count == __fpRequestedSet.Count) break;", self.body)

    def test_version_safe_id_resolution_is_used(self) -> None:
        self.assertIn("__element.Id.ToString()", self.body)
        self.assertNotIn("new ElementId(", self.body)

    def test_emitter_returns_exact_protocol_shell(self) -> None:
        for token in (
            '"schema_version", "kir-decompile-family-placement-extract/1"',
            '"placements", __fpPlacements',
            '__row["element_id"]',
            '__row["status"] = "ok"',
        ):
            self.assertIn(token, self.body)

    def test_point_and_rotation_are_emitted_as_an_inseparable_pair(
            self) -> None:
        # Both keys appear only inside the LocationPoint branch, so the parser
        # never sees a lone member.
        self.assertIn('__row["point_ft"] = __fpRawPoint(__point)', self.body)
        self.assertIn('__row["rotation_rad"] = __rotation', self.body)

    def test_curve_based_location_curve_contract_is_emitted(self) -> None:
        # MEASURED (SKLNK_EOM_R26_V2): every CurveBased instance in the
        # census has Location as LocationCurve, never LocationPoint. The
        # emitter must fall back to reading it when LocationPoint is null.
        for token in (
            # Тот же каст, но от прочитанного под стражем ``Location``
            # (2026-07-29) — см. соседний тест про __fpTryLocation.
            "__rawLocation as LocationCurve",
            "__locCurve.Curve",
            "as Line",
            ".IsBound",
            ".GetEndPoint(0)",
            ".GetEndPoint(1)",
            '__row["curve_state"] = "curved_unsupported"',
            '__row["curve_state"] = "line"',
            '__row["curve_p0_ft"]',
            '__row["curve_p1_ft"]',
        ):
            self.assertIn(token, self.body)

    def test_curve_marker_is_pessimistic_before_the_read_is_attempted(
            self) -> None:
        # The curve-state marker starts as the honest "curved_unsupported"
        # default BEFORE the Line cast/GetEndPoint calls are attempted, so a
        # read that throws partway never masquerades as a successfully read
        # line (same discipline as curtain_extract's __cwCurve helper).
        default_index = self.body.index('"curved_unsupported"')
        line_index = self.body.rindex('"line"')
        self.assertLess(default_index, line_index)

    def test_budgets_are_configurable_and_default_stable(self) -> None:
        custom = build_family_placement_extract_cs(
            ["123"], element_budget_ms=1_234, call_budget_ms=5_678)
        self.assertIn("long __fpElementBudgetMs = 1234L;", custom)
        self.assertIn("long __fpCallBudgetMs = 5678L;", custom)
        self.assertEqual(
            build_family_placement_extract_cs(["123"]),
            build_family_placement_extract_cs(
                ["123"], element_budget_ms=2_000, call_budget_ms=20_000),
        )

    def test_budget_arguments_are_strict(self) -> None:
        for value in (0, -1, True, 1.5, 2**63):
            with self.subTest(element_budget_ms=value):
                with self.assertRaisesRegex(ValueError, "element_budget_ms"):
                    build_family_placement_extract_cs(
                        ["123"], element_budget_ms=value)  # type: ignore[arg-type]
            with self.subTest(call_budget_ms=value):
                with self.assertRaisesRegex(ValueError, "call_budget_ms"):
                    build_family_placement_extract_cs(
                        ["123"], call_budget_ms=value)  # type: ignore[arg-type]

    def test_element_id_validation_is_bounded_and_deterministic(self) -> None:
        with self.assertRaisesRegex(ValueError, "sequence"):
            build_family_placement_extract_cs("123")  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, "numeric Revit id"):
            build_family_placement_extract_cs(["123); return null;"])
        with self.assertRaisesRegex(ValueError, "unique"):
            build_family_placement_extract_cs([1, "1"])
        with self.assertRaisesRegex(ValueError, "at least one"):
            build_family_placement_extract_cs([])

    def test_no_placeholder_survives_emission(self) -> None:
        self.assertNotIn("__FP_", self.body)

    def test_standard_wrapper_and_static_safety_accept_emitter(self) -> None:
        self.assertIsNone(validate_code_safety(self.body))
        self.assertIn(
            "public static object Execute(Document doc, UIDocument uidoc)",
            wrap_user_code(self.body),
        )


class GroupCSharpEmitterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.body = build_group_extract_cs()

    def test_read_only_group_contract_is_emitted(self) -> None:
        for token in (
            # Whole-model: the collector picks groups itself, no requested ids.
            # Group is fully qualified — the serving wrapper's usings include
            # System.Text.RegularExpressions whose Group collides (CS0104,
            # caught by the live 6-version gate).
            "OfClass(typeof(Autodesk.Revit.DB.Group))",
            "foreach (Autodesk.Revit.DB.Group __group",
            "__group.GroupType",
            # GroupType.Name getter is non-public; read via public Element.Name.
            "((Element)__groupType).Name",
            "__group.GetMemberIds()",
            "__group.GroupId",
            "GetAvailableAttachedDetailGroupTypeIds()",
            "__group.Location as LocationPoint",
            "__location.Point",
            # "__location.Rotation" is deliberately NOT here: Autodesk
            # documents that property as unsupported for Group, and reading it
            # cost this stage 96.77% of the groups in a real building. See
            # GroupRotationIsUnsupportedByTheApiTests below.
            "__group.LevelId",
            "__referenceLevel.Elevation",
            '__row["reference_level_id"]',
            '__row["origin_level_offset_ft"]',
        ):
            self.assertIn(token, self.body)

    def test_no_write_geometry_or_conversion_side_effects_are_emitted(
            self) -> None:
        for forbidden in (
            "new Transaction",
            "get_Geometry",
            "Tessellate",
            "304.8",
            "UnitUtils.ConvertFromInternalUnits",
            ".Delete(",
            ".IntegerValue",
        ):
            self.assertNotIn(forbidden, self.body)

    def test_deterministic_id_ordering_without_int_accessor(self) -> None:
        # OrderBy on a version-safe numeric key (ToString + Int64.TryParse),
        # never the removed 32-bit IntegerValue accessor.
        self.assertIn("Int64.TryParse", self.body)
        self.assertIn("OrderBy(__item => __grIdOrder(__item.Id))", self.body)

    def test_cooperative_call_budget_harness_is_emitted(self) -> None:
        self.assertIn("System.Diagnostics.Stopwatch.StartNew()", self.body)
        self.assertIn("long __grCallBudgetMs = 20000L;", self.body)
        self.assertIn("__grCallWatch.ElapsedMilliseconds", self.body)

    def test_emitter_returns_exact_protocol_shell(self) -> None:
        for token in (
            f'"schema_version", "{GROUP_EXTRACT_SCHEMA_VERSION}"',
            '"groups", __grGroups',
            '__row["element_id"]',
            '__row["status"] = "ok"',
        ):
            self.assertIn(token, self.body)

    def test_invalid_parent_group_id_becomes_null(self) -> None:
        self.assertIn("ElementId.InvalidElementId", self.body)

    def test_call_budget_argument_is_strict_and_default_stable(self) -> None:
        for value in (0, -1, True, 1.5, 2**63):
            with self.subTest(call_budget_ms=value):
                with self.assertRaisesRegex(ValueError, "call_budget_ms"):
                    build_group_extract_cs(
                        call_budget_ms=value)  # type: ignore[arg-type]
        self.assertEqual(
            build_group_extract_cs(),
            build_group_extract_cs(call_budget_ms=20_000),
        )

    def test_no_placeholder_survives_emission(self) -> None:
        self.assertNotIn("__GR_", self.body)

    def test_standard_wrapper_and_static_safety_accept_emitter(self) -> None:
        self.assertIsNone(validate_code_safety(self.body))
        self.assertIn(
            "public static object Execute(Document doc, UIDocument uidoc)",
            wrap_user_code(self.body),
        )


def _csharp_code_only(body: str) -> str:
    """The emitted C# with ``//`` comments removed.

    A "this call must not appear" assertion has to read CODE, not prose: the
    first version of the rotation test below passed on the broken emitter and
    then FAILED on the fixed one, because the fix's own comment quotes the
    forbidden call while explaining why it is gone.  A comment that can break a
    test can also silence one.
    """
    out: list[str] = []
    for line in body.splitlines():
        in_string = False
        cut = len(line)
        index = 0
        while index < len(line):
            char = line[index]
            if char == '"' and (index == 0 or line[index - 1] != "\\"):
                in_string = not in_string
            elif (not in_string and char == "/"
                    and line[index + 1:index + 2] == "/"):
                cut = index
                break
            index += 1
        out.append(line[:cut])
    return "\n".join(out)


class GroupRotationIsUnsupportedByTheApiTests(unittest.TestCase):
    """``LocationPoint.Rotation`` must never be read off a ``Group``.

    Autodesk's own ``RevitAPI.xml`` says so, and says it identically in every
    one of the six supported versions (2021…2026), at
    ``P:Autodesk.Revit.DB.LocationPoint.Rotation``:

        "This property is not supported for some elements supporting
         LocationPoints, such as AssemblyInstances, **Groups**, ModelText,
         Room, and SpotDimensions."
        <throws cref="Autodesk.Revit.Exceptions.InvalidOperationException">
            The rotation property is not supported for the Element related to
            this LocationPoint.

    So the read throws for EVERY group that has a location, always, in every
    model.  It sat inside the element-wide ``try``, so the throw took the whole
    row down with it — including ``group_type_name`` and ``member_ids``, which
    had already been read successfully one statement earlier.

    ЗАМЕР, ради которого этот класс написан — 13A-RD-AR-K2_v33
    (``backend/data/decompile/k2_ar_rd_v6``, башня 59 этажей):

        групп в переписи (OST_IOSModelGroups + OST_IOSDetailGroups)   2941
        прочитано в индекс                                              95
        квитанций «group read failed: InvalidOperationException»       2846  (96.77%)

    Все 2846 — ОДНА строка на всех: тип исключения без сообщения и без имени
    чтения, которое его бросило.  А все 95 выживших — ровно вложенные группы:
    у каждой ``group_id_parent`` не пуст и ``transform_available`` ложно, то
    есть ``Location`` вернул null и до запретного чтения дело не дошло.
    Совпадение «выжил ⇔ нет локации» и есть доказательство того, что убивала
    именно локация, а не тип, имя или состав.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.body = build_group_extract_cs()
        cls.code = _csharp_code_only(cls.body)

    def test_rotation_is_never_read_off_a_group_location_point(self) -> None:
        self.assertNotIn("Rotation", self.code)
        # …and the explanation IS expected to survive in the prose, so that the
        # next reader does not "restore" the read a third time.
        self.assertIn("LocationPoint.Rotation", self.body)

    def test_origin_survives_the_rotation_the_api_refuses_to_give(
            self) -> None:
        """Origin IS readable; it must not die with the rotation.

        ``LocationPoint.Point`` carries no such restriction for Group — only
        SETTING it is unsupported, and this stage never writes.  Emitting the
        origin alone is exactly the dialect ``GroupInstanceRecord.from_raw``
        was already written for ("the observed bridge dialect omits rotation
        for all rows; retain that as unavailable instead of inventing 0
        degrees from its absence").
        """
        self.assertIn('__row["origin_ft"] = __grRawPoint(__origin)', self.code)
        self.assertNotIn("rotation_rad", self.code)

    def test_every_soft_read_degrades_only_its_own_field(self) -> None:
        """The general rule, not a patch for one property.

        Identity and composition (type, name, members) are what makes a group
        row a group row: if one of those cannot be read the element is honestly
        absent (I2 fail-closed).  Everything else — origin, level binding,
        attached-detail count — is an ADDITION, and an addition that throws is
        allowed to cost its own field and nothing more.  Each such read
        therefore sits in its own named ``catch``.
        """
        # The origin read is the one that was taking whole rows down; when it
        # throws now it costs the origin, keeps the row, and says so by name.
        self.assertIn("catch (Exception __originError)", self.body)
        self.assertIn("row kept", self.body)
        # Level binding and attached-detail count keep their own quiet guards:
        # the row already states `level_binding_available` / the count
        # explicitly, so the row itself is the record and a second voice would
        # only double-count. Two guards, neither of them the element-wide one.
        self.assertGreaterEqual(self.body.count("catch (Exception)"), 2)
        # …and the element-wide catch stays last-resort, for identity reads.
        self.assertIn("catch (Exception __groupError)", self.body)

    def test_receipt_carries_the_message_and_the_read_that_threw(self) -> None:
        """2846 identical lines named neither the message nor the call.

        ``GetType().Name`` alone is what made the whole population look like a
        single unexplained event.  The exception's own ``Message`` is the
        verbatim text from the Revit bridge, and the step label says WHICH read
        produced it — without the label an exception type is still one bucket.
        """
        self.assertIn("__groupError.Message", self.body)
        self.assertIn("__grStep", self.body)


# ── Wire-format round-trip: emitted C# shape ⇄ the REAL strict parsers ────────


def _fp_wire_row(element_id: str = "3001", **overrides: object) -> dict:
    """One placement row in the exact shape ``build_family_placement_extract_cs``
    emits (RAW feet/radians, unit orientations, the ``point_ft``/``rotation_rad``
    pair present)."""
    row = {
        "element_id": element_id,
        "symbol_id": "800",
        "type_name": "Дверь 900",
        "family_name": "Одностворчатая",
        "placement_type": "OneLevelBasedHosted",
        "in_place": False,
        "mirrored": False,
        "hand_flipped": True,
        "facing_flipped": True,
        "super_component_id": None,
        "group_id": None,
        "host_id": "1001",
        "host_class": "Wall",
        "hand_orientation": [0, 1, 0],
        "facing_orientation": [1, 0, 0],
        "point_ft": [1, -2, 3.5],
        "rotation_rad": math.pi / 2,
        "status": "ok",
    }
    row.update(overrides)
    return row


def _gr_wire_row(
    element_id: str,
    members: list[str],
    *,
    type_id: str = "500",
    with_transform: bool = True,
) -> dict:
    row = {
        "element_id": element_id,
        "group_type_id": type_id,
        "group_type_name": "Типовой этаж",
        "member_ids": members,
        "group_id_parent": None,
        "attached_detail_type_count": 2,
        "status": "ok",
    }
    if with_transform:
        row["origin_ft"] = [1, 2, 3]
        row["rotation_rad"] = math.pi
        row["reference_level_id"] = "42"
        row["origin_level_offset_ft"] = 0.5
    else:
        row["reference_level_id"] = None
        row["origin_level_offset_ft"] = None
    return row


class EmittedFamilyWireRoundTripTests(unittest.TestCase):
    def test_emitted_placement_rows_parse_through_the_real_parser(
            self) -> None:
        # A hosted family with no LocationPoint: the emitter omits both the
        # point_ft and rotation_rad keys (the pair is present or absent).
        no_location = _fp_wire_row(
            "4002", placement_type="WorkPlaneBased",
            host_id=None, host_class=None,
            mirrored=False, hand_flipped=False, facing_flipped=False,
            hand_orientation=[1, 0, 0], facing_orientation=[0, 1, 0])
        del no_location["point_ft"]
        del no_location["rotation_rad"]
        payload = {
            "schema_version": FAMILY_PLACEMENT_EXTRACT_SCHEMA_VERSION,
            "placements": [_fp_wire_row("3001"), no_location],
        }

        # Exactly the pipeline's parse+merge path for this stage.
        rows = _rows_of(payload, "placements")
        extraction = FamilyPlacementExtraction.from_rows(rows)

        # Hosted door with the XOR-consistent double-flip state.
        door = extraction.entry_for("3001")
        self.assertEqual(door.host_id, "1001")
        self.assertEqual(door.host_class, "Wall")
        self.assertFalse(door.mirrored)
        self.assertTrue(door.hand_flipped and door.facing_flipped)
        self.assertEqual(
            door.placement_type, FamilyPlacementType.ONE_LEVEL_BASED_HOSTED)
        self.assertTrue(door.placement_available)
        self.assertEqual(door.point_mm, (304.8, -609.6, 1066.8))
        self.assertAlmostEqual(door.rotation_deg, 90.0)

        noloc = extraction.entry_for("4002")
        self.assertFalse(noloc.placement_available)
        self.assertIsNone(noloc.point_mm)
        self.assertIsNone(noloc.rotation_deg)

    def test_emitted_curve_based_placement_rows_parse_through_the_real_parser(
            self) -> None:
        # The exact pipeline parse+merge path for a CurveBased row (element
        # 1268396, MEASURED against SKLNK_EOM_R26_V2 -- see _curve_based_raw).
        payload = {
            "schema_version": FAMILY_PLACEMENT_EXTRACT_SCHEMA_VERSION,
            "placements": [_curve_based_raw("1268396")],
        }
        rows = _rows_of(payload, "placements")
        extraction = FamilyPlacementExtraction.from_rows(rows)

        row = extraction.entry_for("1268396")
        self.assertEqual(row.placement_type, FamilyPlacementType.CURVE_BASED)
        self.assertTrue(row.placement_available)
        self.assertIs(row.curve_state, CurveState.LINE)
        self.assertEqual(row.host_id, "1221482")
        self.assertEqual(row.host_class, "CableTray")
        for actual, expected in zip(
                row.curve_p0_mm or (), (155643.0, -5766.0, 565.0)):
            self.assertAlmostEqual(actual, expected, places=6)
        for actual, expected in zip(
                row.curve_p1_mm or (), (155643.0, -5766.0, 4910.0)):
            self.assertAlmostEqual(actual, expected, places=6)


class EmittedGroupWireRoundTripTests(unittest.TestCase):
    def test_emitted_group_rows_parse_through_the_real_parser(self) -> None:
        payload = {
            "schema_version": GROUP_EXTRACT_SCHEMA_VERSION,
            "groups": [
                _gr_wire_row("10", ["100", "101", "102"]),
                _gr_wire_row("20", ["200", "201", "202"]),
            ],
        }
        rows = _rows_of(payload, "groups")
        extraction = GroupExtraction.from_rows(rows)

        instance = extraction.instances["10"]
        self.assertEqual(instance["member_ids"], ["100", "101", "102"])
        self.assertTrue(instance["transform_available"])
        self.assertAlmostEqual(instance["rotation_deg"], 180.0)
        self.assertEqual(instance["attached_detail_type_count"], 2)
        self.assertTrue(instance["level_binding_available"])
        self.assertEqual(instance["reference_level_id"], "42")
        self.assertAlmostEqual(instance["origin_level_offset_mm"], 152.4)
        for actual, expected in zip(
                instance["origin_mm"], (304.8, 609.6, 914.4)):
            self.assertAlmostEqual(actual, expected)

        # Both instances share the type: a single definition, no drift.
        definitions = extraction.definitions
        self.assertEqual(len(definitions), 1)
        self.assertEqual(definitions[0].group_type_id, "500")
        self.assertEqual(len(extraction.composition_mismatches), 0)

    def test_origin_only_row_keeps_the_origin_and_admits_no_angle(
            self) -> None:
        """The shape a placed group actually has once the emitter is honest.

        Before the fix this row could not exist: the rotation read threw first,
        so 2846 groups on 13A-RD-AR-K2_v33 produced no row at all.  The parser
        was already able to accept it — nothing here is a new tolerance, only a
        contract the emitter finally reaches.
        """
        row = _gr_wire_row("10", ["100", "101"])
        del row["rotation_rad"]
        extraction = GroupExtraction.from_rows(_rows_of(
            {"schema_version": GROUP_EXTRACT_SCHEMA_VERSION, "groups": [row]},
            "groups"))
        instance = extraction.instances["10"]
        # The origin is kept…
        for actual, expected in zip(
                instance["origin_mm"], (304.8, 609.6, 914.4)):
            self.assertAlmostEqual(actual, expected)
        # …and the angle is honestly absent rather than invented as 0°.
        self.assertIsNone(instance["rotation_deg"])
        self.assertFalse(instance["transform_available"])
        self.assertEqual(instance["member_ids"], ["100", "101"])
        # Composition still reaches the relations layer — the whole point of
        # keeping the row.
        analysis = analyze_group_relations(
            extraction, ("100", "101"))
        self.assertEqual(len(analysis.memberships), 2)

    def test_group_without_location_omits_the_transform_pair(self) -> None:
        payload = {
            "schema_version": GROUP_EXTRACT_SCHEMA_VERSION,
            "groups": [_gr_wire_row("10", ["1"], with_transform=False)],
        }
        extraction = GroupExtraction.from_rows(
            _rows_of(payload, "groups"))
        instance = extraction.instances["10"]
        self.assertFalse(instance["transform_available"])
        self.assertIsNone(instance["origin_mm"])
        self.assertIsNone(instance["rotation_deg"])


if __name__ == "__main__":
    unittest.main()
