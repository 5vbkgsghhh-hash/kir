from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import unittest

from kukai.ir.decompile.geom_extract import (
    GEOMETRY_ARTIFACT_PROOF_VERSION,
    GEOMETRY_EXTRACT_SCHEMA_VERSION,
    ExtractedGeometryTier,
    GeometryDetailLevel,
    GeometryArtifactProof,
    GeometryFailureReason,
    GeometryExtraction,
    GeometryPayloadError,
    GeometryStore,
    build_geometry_extract_cs,
    extract_geometry,
    geometry_hash,
    geometry_atom_contract_digest,
    merge_geometry_extractions,
)
from kukai.ir.decompile.recompile import (
    GbSolid,
    GeometryNode,
    GeometryTier,
    GmMesh,
    IDENTITY_TRANSFORM,
    recompile,
)
from kukai.ir.decompile.tests.test_recompile import (
    _box_solid,
    _translated,
)
from kukai.ir.decompile.schema import GEOM_CANON_MM
from kukai.llm.revit_execution_pipeline import wrap_user_code
from kukai.security.validation import validate_code_safety


def _triangle_mesh(offset: float = 0.0) -> GmMesh:
    return GmMesh(
        (
            (offset, 0.0, 0.0),
            (1000.0 + offset, 0.0, 0.0),
            (offset, 1000.0, 0.0),
        ),
        ((0, 1, 2),),
    )


def _part(geometry, transform=IDENTITY_TRANSFORM) -> dict:
    return {
        "geometry": geometry.to_dict(),
        "transform": list(transform),
        "gb_error": None,
    }


def _element(
    element_id: str,
    category: str,
    parts: list[dict],
    *,
    status: str = "ok",
    errors: list[str] | None = None,
) -> dict:
    return {
        "element_id": element_id,
        "category": category,
        "status": status,
        "parts": parts,
        "errors": [] if errors is None else errors,
    }


def _payload(elements: list[dict]) -> dict:
    return {
        "schema_version": GEOMETRY_EXTRACT_SCHEMA_VERSION,
        "elements": elements,
    }


def _dedup_payload() -> dict:
    mesh = _triangle_mesh()
    return _payload([
        _element("101", "OST_StructuralColumns", [_part(mesh)]),
        _element(
            "102", "OST_StructuralColumns",
            [_part(mesh, _translated(5000.0, 0.0, 0.0))]),
        _element(
            "103", "OST_StructuralColumns",
            [_part(mesh, _translated(10000.0, 0.0, 0.0))]),
    ])


class GeometryStoreTests(unittest.TestCase):
    def test_hash_quantizes_only_geometry_at_geom_canon_mm(self) -> None:
        self.assertEqual(GEOM_CANON_MM, 0.5)
        mesh_a = _triangle_mesh(0.10)
        mesh_b = _triangle_mesh(0.20)

        self.assertNotEqual(mesh_a, mesh_b)
        self.assertEqual(geometry_hash(mesh_a), geometry_hash(mesh_b))

    def test_store_deduplicates_canonical_geometry(self) -> None:
        store = GeometryStore()
        first = store.add(_triangle_mesh(0.10))
        second = store.add(_triangle_mesh(0.20).to_dict())

        self.assertEqual(first, second)
        self.assertEqual(len(store), 1)
        self.assertIsInstance(store.get(first), GmMesh)
        self.assertEqual(list(store.to_dict()), [first])

    def test_geometry_hash_excludes_placement_and_category_by_construction(self) -> None:
        result = extract_geometry(_dedup_payload())

        self.assertEqual(len(result.store), 1)
        self.assertEqual(
            {entry.geo_hash for entry in result.index},
            {next(iter(result.store)).geo_hash},
        )
        self.assertEqual(len({entry.transform for entry in result.index}), 3)


class GeometryIngestionTests(unittest.TestCase):
    def test_n_identical_columns_become_one_definition_n_transforms(self) -> None:
        result = extract_geometry(_dedup_payload())

        self.assertEqual(len(result.store), 1)
        self.assertEqual(len(result.index), 3)
        self.assertEqual(len(result.nodes), 1)
        self.assertEqual(len(result.nodes[0].transforms), 3)
        self.assertEqual(result.nodes[0].geometry.tier, GeometryTier.GM)
        self.assertEqual(recompile(result).direct_shape_count, 3)

    def test_planar_real_spike_shape_fact_lands_on_frozen_gb(self) -> None:
        # The persisted real spike observed Plane as 97% of sampled faces.
        # Wave G's accepted planar box supplies the exact frozen topology shape.
        solid = _box_solid()
        result = extract_geometry(_payload([
            _element("201", "OST_Walls", [_part(solid)]),
        ]))

        self.assertEqual(result.index[0].tier, ExtractedGeometryTier.GB)
        self.assertIsInstance(result.nodes[0].geometry, GbSolid)
        self.assertEqual(
            GeometryNode.from_dict(result.nodes[0].to_dict()),
            result.nodes[0],
        )
        emitted = recompile(result)
        self.assertEqual(emitted.chosen_tier, GeometryTier.GB)
        self.assertIn("new BRepBuilder(BRepType.Solid)", emitted.csharp)

    def test_dirty_gb_candidate_falls_to_its_validated_gm_floor(self) -> None:
        dirty = _box_solid().to_dict()
        dirty["faces"][0]["loops"][0]["coedges"][0]["edge_id"] = "missing"
        payload = _payload([
            _element("301", "OST_Floors", [{
                "geometry": dirty,
                "transform": list(IDENTITY_TRANSFORM),
                "gb_error": None,
            }]),
        ])

        result = extract_geometry(payload)

        self.assertEqual(result.index[0].tier, ExtractedGeometryTier.GM)
        self.assertIsInstance(result.nodes[0].geometry, GmMesh)
        self.assertEqual(len(result.degradations), 1)
        self.assertIn("frozen Gb validation refused", result.degradations[0].reason)
        self.assertEqual(recompile(result).chosen_tier, GeometryTier.GM)

    def test_emitter_reported_gb_failure_is_retained_on_gm(self) -> None:
        mesh_part = _part(_triangle_mesh())
        mesh_part["gb_error"] = "InvalidOperationException: periodic surface"

        result = extract_geometry(_payload([
            _element("302", "OST_Floors", [mesh_part]),
        ]))

        self.assertEqual(result.index[0].tier, ExtractedGeometryTier.GM)
        self.assertEqual(len(result.degradations), 1)
        self.assertIn("periodic surface", result.degradations[0].reason)

    def test_mesh_only_lands_on_frozen_gm(self) -> None:
        result = extract_geometry(_payload([
            _element("401", "OST_GenericModel", [_part(_triangle_mesh())]),
        ]))

        self.assertEqual(result.index[0].tier, ExtractedGeometryTier.GM)
        self.assertEqual(result.nodes[0].geometry.tier, GeometryTier.GM)

    def test_genuinely_empty_geometry_is_tier_a_without_definition(self) -> None:
        result = extract_geometry(_payload([_element(
            "501", "OST_Views", [], status="empty")]))

        self.assertEqual(result.geometry_index, {
            "501": {"tier": "A", "geo_hash": None, "transform": None},
        })
        self.assertEqual(len(result.store), 0)
        self.assertEqual(result.nodes, ())
        self.assertEqual(result.failures, ())

    def test_failed_dirty_geometry_is_not_misreported_as_tier_a(self) -> None:
        result = extract_geometry(_payload([_element(
            "601", "OST_GenericModel", [], status="failed",
            errors=["solid tessellation failed"])]))

        self.assertEqual(result.index, ())
        self.assertEqual(len(result.failures), 1)
        self.assertNotIn("601", result.geometry_index)

    def test_partial_budget_result_accounts_for_every_input_id(self) -> None:
        success = _element(
            "610", "OST_GenericModel", [_part(_triangle_mesh())])
        timed_out = _element(
            "611", "OST_CurtainWallPanels", [], status="failed",
            errors=["time_budget_exceeded"])
        timed_out.update({
            "reason": "time_budget_exceeded",
            "elapsed_ms": 2_417,
            "detail_level": "medium",
        })
        call_exhausted = _element(
            "612", "", [], status="failed",
            errors=["call_budget_exhausted"])
        call_exhausted.update({
            "reason": "call_budget_exhausted",
            "elapsed_ms": 20_031,
            "detail_level": "medium",
        })
        success["detail_level"] = "medium"

        result = extract_geometry(_payload([
            success, timed_out, call_exhausted,
        ]))

        self.assertEqual(
            {record.element_id for record in result.index}, {"610"})
        self.assertEqual(
            result.index[0].detail_level, GeometryDetailLevel.MEDIUM)
        self.assertEqual(
            {failure.element_id for failure in result.failures},
            {"611", "612"},
        )
        accounted = (
            {record.element_id for record in result.index}
            | {failure.element_id for failure in result.failures}
        )
        self.assertEqual(accounted, {"610", "611", "612"})
        failures = {
            failure.element_id: failure for failure in result.failures
        }
        self.assertEqual(
            failures["611"].reason,
            GeometryFailureReason.TIME_BUDGET_EXCEEDED,
        )
        self.assertEqual(failures["611"].elapsed_ms, 2_417)
        self.assertEqual(
            failures["612"].reason,
            GeometryFailureReason.CALL_BUDGET_EXHAUSTED,
        )
        self.assertEqual(failures["612"].elapsed_ms, 20_031)
        self.assertEqual(
            [
                (record.element_id, record.detail_level)
                for record in result.detail_levels
            ],
            [
                (element_id, GeometryDetailLevel.MEDIUM)
                for element_id in ("610", "611", "612")
            ],
        )
        persisted = result.to_dict()
        self.assertEqual(
            persisted["failures"][0]["reason"],
            "time_budget_exceeded",
        )
        self.assertEqual(
            persisted["detail_levels"],
            [
                {"element_id": element_id, "detail_level": "medium"}
                for element_id in ("610", "611", "612")
            ],
        )

    def test_budget_failure_additions_are_strict_and_fail_closed(self) -> None:
        base = _element(
            "620", "OST_GenericModel", [], status="failed",
            errors=["time_budget_exceeded"])
        malformed_rows = (
            ({**base, "reason": "time_budget_exceeded"}, "requires elapsed_ms"),
            ({
                **base,
                "reason": "not_a_budget_reason",
                "elapsed_ms": 2_001,
            }, "reason is unsupported"),
            ({
                **base,
                "reason": "time_budget_exceeded",
                "elapsed_ms": True,
            }, "non-negative integer"),
            ({
                **base,
                "reason": "call_budget_exhausted",
                "elapsed_ms": 20_001,
            }, "matching failed error"),
            ({**base, "detail_level": "ultra"}, "detail_level is unsupported"),
        )
        for row, message in malformed_rows:
            with self.subTest(message=message):
                with self.assertRaisesRegex(GeometryPayloadError, message):
                    extract_geometry(_payload([row]))

    def test_legacy_fine_result_serialization_is_byte_compatible(self) -> None:
        result = extract_geometry(_payload([
            _element("630", "OST_Views", [], status="empty"),
        ]))
        expected = {
            "geometry_store": {},
            "geometry_index": {
                "630": {"tier": "A", "geo_hash": None, "transform": None},
            },
            "nodes": [],
            "degradations": [],
            "failures": [],
        }

        self.assertEqual(
            json.dumps(result.to_dict(), separators=(",", ":")),
            json.dumps(expected, separators=(",", ":")),
        )
        self.assertEqual(result.detail_levels, ())
        self.assertNotIn("detail_levels", result.to_dict())

    def test_multiple_solids_use_one_exact_gm_side_row(self) -> None:
        first = _box_solid()
        second_transform = _translated(3000.0, 0.0, 0.0)
        result = extract_geometry(_payload([
            _element("701", "OST_GenericModel", [
                _part(first),
                _part(first, second_transform),
            ]),
        ]))

        self.assertEqual(len(result.index), 1)
        self.assertEqual(result.index[0].tier, ExtractedGeometryTier.GM)
        self.assertEqual(result.index[0].transform, IDENTITY_TRANSFORM)
        self.assertEqual(len(result.nodes[0].geometry.triangles), 24)
        self.assertTrue(any(
            degradation.part_index is None
            for degradation in result.degradations))
        self.assertEqual(recompile(result).direct_shape_count, 1)

    def test_bridge_envelope_unwraps_without_weakening_geometry_schema(self) -> None:
        wrapped = {"ok": True, "result": _dedup_payload()}

        result = extract_geometry(wrapped)

        self.assertEqual(len(result.index), 3)

    def test_malformed_payload_is_a_typed_refusal(self) -> None:
        malformed = _dedup_payload()
        malformed["elements"][0]["surprise"] = True

        with self.assertRaisesRegex(GeometryPayloadError, "unexpected surprise"):
            extract_geometry(malformed)

    def test_result_bytes_are_identical_under_two_hash_seeds(self) -> None:
        script = (
            "import hashlib,json; "
            "from kukai.ir.decompile.geom_extract import extract_geometry; "
            "from kukai.ir.decompile.tests.test_geom_extract "
            "import _dedup_payload; "
            "r=extract_geometry(_dedup_payload()); "
            "b=json.dumps(r.to_dict(),sort_keys=True,separators=(',',':')); "
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

        self.assertEqual(hashes[0], hashes[1])

    def test_geo_hash_is_full_sha256(self) -> None:
        result = extract_geometry(_dedup_payload())
        encoded = json.dumps(
            result.store.to_dict(), sort_keys=True, separators=(",", ":"))

        self.assertEqual(len(result.index[0].geo_hash or ""), 64)
        self.assertEqual(len(hashlib.sha256(encoded.encode()).hexdigest()), 64)


class GeometryBundleLifecycleTests(unittest.TestCase):
    @staticmethod
    def _atom(source_id: str = "801") -> dict:
        return {
            "kind": "atom",
            "source_element_id": source_id,
            "category": "OST_GenericModel",
            "_id": f"atom-{source_id}",
            "reason": {"code": "unsupported_signature", "detail": "x"},
        }

    def test_artifact_proof_binds_bundle_revision_and_exact_atom_leaf(self):
        bundle = json.dumps(
            extract_geometry(_payload([
                _element("801", "OST_GenericModel", [_part(_triangle_mesh())]),
            ])).to_dict(),
            sort_keys=True, separators=(",", ":"),
        ).encode()
        leaves = [self._atom()]

        proof = GeometryArtifactProof.bind(
            change_stamp="doc-a",
            revision_fingerprint="rev-a",
            geometry_bundle=bundle,
            leaves=leaves,
        )
        restored = GeometryArtifactProof.from_dict(proof.to_dict())
        restored.verify(
            change_stamp="doc-a",
            revision_fingerprint="rev-a",
            geometry_bundle=bundle,
            leaves=leaves,
        )

        self.assertEqual(
            proof.to_dict()["schema_version"],
            GEOMETRY_ARTIFACT_PROOF_VERSION)
        self.assertEqual(proof.atom_count, 1)
        with self.assertRaisesRegex(GeometryPayloadError, "does not match"):
            restored.verify(
                change_stamp="doc-a",
                revision_fingerprint="rev-b",
                geometry_bundle=bundle,
                leaves=leaves,
            )
        changed = copy.deepcopy(leaves)
        changed[0]["reason"]["detail"] = "different lift evidence"
        with self.assertRaisesRegex(GeometryPayloadError, "does not match"):
            restored.verify(
                change_stamp="doc-a",
                revision_fingerprint="rev-a",
                geometry_bundle=bundle,
                leaves=changed,
            )

    def test_generator_children_are_outside_geometry_atom_contract(self):
        generated = self._atom("802")
        generated["reason"] = {
            "code": "generator_child", "detail": "parent recreates child"}

        digest, count = geometry_atom_contract_digest([
            generated, self._atom("801")])

        self.assertEqual(len(digest), 64)
        self.assertEqual(count, 1)

    def test_persisted_bundle_round_trips_without_changing_frozen_shape(
            self) -> None:
        original = extract_geometry(_dedup_payload())

        restored = GeometryExtraction.from_json(json.dumps(
            original.to_dict(), sort_keys=True, separators=(",", ":")),
            categories_by_id={
                record.element_id: record.category
                for record in original.index
            },
        )

        self.assertEqual(restored.to_dict(), original.to_dict())
        self.assertEqual(restored.index, original.index)
        self.assertEqual(restored.records, restored.index)

    def test_class_only_directshape_category_resolves_from_unique_node(
            self) -> None:
        original = extract_geometry(_payload([
            _element("801", "OST_GenericModel", [_part(_triangle_mesh())]),
        ]))

        restored = GeometryExtraction.from_dict(
            original.to_dict(), categories_by_id={"801": "DirectShape"})

        self.assertEqual(restored.index[0].category, "OST_GenericModel")

    def test_non_pseudo_l0_category_mismatch_is_refused(self) -> None:
        original = extract_geometry(_payload([
            _element("802", "OST_GenericModel", [_part(_triangle_mesh())]),
        ]))

        with self.assertRaisesRegex(
                GeometryPayloadError, "disagrees with L0"):
            GeometryExtraction.from_dict(
                original.to_dict(), categories_by_id={"802": "OST_Walls"})

    def test_category_recovery_never_guesses_an_ambiguous_occurrence(
            self) -> None:
        original = extract_geometry(_payload([
            _element("803", "OST_GenericModel", [_part(_triangle_mesh())]),
        ]))
        bundle = original.to_dict()
        second_node = copy.deepcopy(bundle["nodes"][0])
        second_node["node_id"] = "ambiguous-second-node"
        second_node["category"] = "OST_Furniture"
        bundle["nodes"].append(second_node)

        with self.assertRaisesRegex(GeometryPayloadError, "ambiguous"):
            GeometryExtraction.from_dict(bundle)

    def test_paginated_merge_deduplicates_store_and_regroups_nodes(self) -> None:
        mesh = _triangle_mesh()
        first = extract_geometry(_payload([
            _element("901", "OST_GenericModel", [_part(mesh)]),
        ]))
        second = extract_geometry(_payload([
            _element("902", "OST_GenericModel", [
                _part(mesh, _translated(5000.0, 0.0, 0.0))]),
        ]))

        merged = merge_geometry_extractions([first, second])

        self.assertEqual(len(merged.store), 1)
        self.assertEqual(len(merged.index), 2)
        self.assertEqual(len(merged.nodes), 1)
        self.assertEqual(len(merged.nodes[0].transforms), 2)

    def test_paginated_merge_refuses_duplicate_element_identity(self) -> None:
        part = extract_geometry(_payload([
            _element("903", "OST_GenericModel", [_part(_triangle_mesh())]),
        ]))

        with self.assertRaisesRegex(GeometryPayloadError, "repeats element_id"):
            merge_geometry_extractions([part, part])

    def test_world_fallback_mesh_applies_instance_transform(self) -> None:
        translated = _translated(2500.0, -400.0, 75.0)
        result = extract_geometry(_payload([
            _element("904", "OST_GenericModel", [
                _part(_triangle_mesh(), translated)]),
        ]))

        mesh = result.world_fallback_mesh("904")

        self.assertEqual(mesh.vertices_mm[0], (2500.0, -400.0, 75.0))
        self.assertEqual(mesh.vertices_mm[1], (3500.0, -400.0, 75.0))

    def test_world_fallback_mesh_refuses_tier_a(self) -> None:
        result = extract_geometry(_payload([
            _element("905", "OST_Views", [], status="empty"),
        ]))

        with self.assertRaisesRegex(GeometryPayloadError, "no Tier-G"):
            result.world_fallback_mesh("905")


class GeometryCSharpEmitterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.body = build_geometry_extract_cs(["123", 456])

    def test_exact_fine_read_only_get_geometry_contract_is_emitted(self) -> None:
        for token in (
            "ComputeReferences = false",
            "DetailLevel = ViewDetailLevel.Fine",
            "IncludeNonVisibleObjects = false",
            ".get_Geometry(__options)",
            "UnitUtils.ConvertFromInternalUnits",
        ):
            self.assertIn(token, self.body)
        self.assertNotIn("new Transaction", self.body)
        self.assertNotIn("304.8", self.body)

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
            "long __gxElementBudgetMs = 2000L;",
            "long __gxCallBudgetMs = 20000L;",
            "__gxElementWatchT0",
            "__gxCallWatchT0",
            '"time_budget_exceeded"',
            '"call_budget_exhausted"',
            '__row["elapsed_ms"] = __gxBudgetElapsed',
            "__parts.Clear();",
            "__errors.Clear();",
            "Func<bool> __gxBudgetExceeded",
        ):
            self.assertIn(token, self.body)
        # Before/after checkpoints surround get_Geometry and recursive
        # traversal; Revit calls themselves remain deliberately cooperative.
        self.assertGreaterEqual(
            self.body.count("if (!__gxBudgetExceeded())"), 2)
        self.assertIn("Triangulate itself cannot be preempted", self.body)
        self.assertIn(
            "foreach (string __requestedId in __gxRequestedIds)", self.body)
        self.assertIn(
            "if (__gxFound.Count == __gxRequestedSet.Count) break;",
            self.body,
        )

    def test_budgets_and_detail_level_are_configurable(self) -> None:
        medium = build_geometry_extract_cs(
            ["123"],
            element_budget_ms=1_234,
            call_budget_ms=5_678,
            detail="medium",
        )
        coarse = build_geometry_extract_cs(["123"], detail="coarse")

        self.assertIn("long __gxElementBudgetMs = 1234L;", medium)
        self.assertIn("long __gxCallBudgetMs = 5678L;", medium)
        self.assertIn("DetailLevel = ViewDetailLevel.Medium", medium)
        self.assertIn('__row["detail_level"] = "medium"', medium)
        self.assertIn("DetailLevel = ViewDetailLevel.Coarse", coarse)
        self.assertIn('__row["detail_level"] = "coarse"', coarse)
        self.assertEqual(
            build_geometry_extract_cs(["123"]),
            build_geometry_extract_cs(
                ["123"],
                element_budget_ms=2_000,
                call_budget_ms=20_000,
                detail="fine",
            ),
        )

    def test_budget_and_detail_arguments_are_strict(self) -> None:
        invalid_budgets = (0, -1, True, 1.5, 2**63)
        for value in invalid_budgets:
            with self.subTest(element_budget_ms=value):
                with self.assertRaisesRegex(ValueError, "element_budget_ms"):
                    build_geometry_extract_cs(
                        ["123"], element_budget_ms=value)  # type: ignore[arg-type]
            with self.subTest(call_budget_ms=value):
                with self.assertRaisesRegex(ValueError, "call_budget_ms"):
                    build_geometry_extract_cs(
                        ["123"], call_budget_ms=value)  # type: ignore[arg-type]
        for value in ("Fine", "ultra", "", None):
            with self.subTest(detail=value):
                with self.assertRaisesRegex(ValueError, "detail must"):
                    build_geometry_extract_cs(
                        ["123"], detail=value)  # type: ignore[arg-type]

    def test_symbol_geometry_path_structurally_guards_double_transform(self) -> None:
        self.assertIn("GetSymbolGeometry()", self.body)
        self.assertIn("__placement.Multiply(__instance.Transform)", self.body)
        self.assertNotIn("GetInstanceGeometry", self.body)
        self.assertNotIn("OfPoint", self.body)

    def test_all_frozen_surface_curve_and_mesh_branches_are_emitted(self) -> None:
        for token in (
            '"surface_type", "Planar"',
            '"surface_type", "Cylindrical"',
            '"surface_type", "Conical"',
            '"surface_type", "Revolved"',
            '"surface_type", "Ruled"',
            '"surface_type", "NURBS"',
            '"curve_type", "Line"',
            '"curve_type", "Arc"',
            '"curve_type", "Ellipse"',
            '"curve_type", "NURBS"',
            "ExportUtils.GetNurbsSurfaceDataForSurface",
            "Face __face in __solid.Faces",
            "EdgeArray __loop in __face.EdgeLoops",
            "IsFlippedOnFace",
            "get_Triangle",
            "get_Index",
        ):
            self.assertIn(token, self.body)

    def test_emitter_returns_exact_protocol_shell_and_gb_mesh_floor(self) -> None:
        for token in (
            '"schema_version", "kir-decompile-geometry/1"',
            '"fallback_mesh", __fallback',
            '"brep_candidate_valid", true',
            '"geometry", __definition',
            '"transform", __gxTransform(__placement)',
            '"gb_error", __gbError',
        ):
            self.assertIn(token, self.body)

    def test_standard_wrapper_and_static_safety_accept_emitter(self) -> None:
        self.assertIsNone(validate_code_safety(self.body))
        wrapped = wrap_user_code(self.body)
        self.assertIn(
            "public static object Execute(Document doc, UIDocument uidoc)",
            wrapped,
        )

    def test_element_id_validation_is_bounded_and_deterministic(self) -> None:
        with self.assertRaisesRegex(ValueError, "sequence"):
            build_geometry_extract_cs("123")  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, "numeric Revit id"):
            build_geometry_extract_cs(["123); return null;"])
        with self.assertRaisesRegex(ValueError, "unique"):
            build_geometry_extract_cs([1, "1"])
        with self.assertRaisesRegex(ValueError, "at least one"):
            build_geometry_extract_cs([])

    def test_emitted_body_is_identical_under_two_hash_seeds(self) -> None:
        script = (
            "import hashlib; "
            "from kukai.ir.decompile.geom_extract "
            "import build_geometry_extract_cs; "
            "b=build_geometry_extract_cs(['123','456']); "
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

        self.assertEqual(hashes[0], hashes[1])


if __name__ == "__main__":
    unittest.main()
