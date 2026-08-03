from __future__ import annotations

import copy
import json
import os
from dataclasses import fields, replace
from pathlib import Path
import subprocess
import sys
import unittest
from typing import Any

from kukai.ir.decompile.dependencies import (
    FAMILY_IDENTITY_NOTE,
    DependencyKind,
    DependencyResolution,
    TargetContract,
    build_dependency_manifest,
)
from kukai.ir.decompile.fold import fold_document
from kukai.ir.decompile.honesty import (
    BuildStageEvidence,
    BuildStageState,
    BuildStatuses,
    EquivalenceClaim,
    EquivalenceScope,
    EquivalenceState,
    FidelityAssessment,
    HonestyContractError,
    coerce_equivalence_scope,
    require_scope_for_equivalence_text,
)
from kukai.ir.decompile.l1_schema import (
    AtomReason,
    FidelityReason,
    FidelityVerdict,
    validate_l1_node,
)
from kukai.ir.decompile.lift import lift_document
from kukai.ir.decompile.name import name_document
from kukai.ir.decompile.orchestrator import decompile
from kukai.ir.decompile.passport import (
    PassportAssemblyError,
    build_passport,
    passport_inject,
    query_passport,
)
from kukai.ir.decompile.schema import (
    L0_SCHEMA_VERSION,
    L0Document,
    L0Element,
)
from kukai.ir.decompile.tests.fixtures_decompile import (
    make_element,
    project1_metadata,
)
from kukai.ir.decompile.verify import verify_document


REPO_ROOT = next(
    ancestor for ancestor in Path(__file__).resolve().parents
    if (ancestor / "backend").is_dir()
)


def _document(
    elements: list[dict[str, Any]],
    *,
    name: str = "step-zero-honesty",
    links: list[dict[str, Any]] | None = None,
) -> L0Document:
    metadata = copy.deepcopy(project1_metadata())
    metadata.update({
        "doc_name": name,
        "change_stamp": f"{name}-v1",
        "levels": [metadata["levels"][0]],
        "grids": [],
        "rooms": [],
        "elements": copy.deepcopy(elements),
        "category_status": [],
        "links": copy.deepcopy(links or []),
    })
    return L0Document.from_dict(metadata)


def _walk(node: Any) -> list[Any]:
    return [node] + [
        descendant
        for child in node.get("children", [])
        for descendant in _walk(child)
    ]


def _honesty_document() -> L0Document:
    return _document([
        make_element("OST_Walls", 71_001, ordinal=0),
        make_element("OST_StructuralColumns", 71_002, ordinal=0),
        make_element("OST_Floors", 71_003, ordinal=0),
    ], name="honesty-scale")


def seeded_honesty_payload() -> str:
    result = decompile(
        _honesty_document(),
        target_contract=TargetContract.PORTABLE_EMPTY_DOCUMENT,
        equivalence_scope=EquivalenceScope.DOCUMENT,
    )
    return json.dumps(
        result.to_dict(),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


class FidelityContractTests(unittest.TestCase):
    def test_closed_scales_and_typed_lift_reasons_are_additive(self) -> None:
        self.assertEqual(
            {value.value for value in FidelityVerdict},
            {
                "native_exact",
                "form_exact",
                "approximate",
                "opaque",
                "generated_accounted",
            },
        )
        new_reason_values = {
            "placement_kind_unknown",
            "flip_state_unknown",
            "instance_params_incomplete",
            "dependency_unresolved",
            "generator_child",
        }
        self.assertTrue(
            new_reason_values <= {value.value for value in AtomReason})
        self.assertTrue(
            {value.value for value in AtomReason}
            <= {value.value for value in FidelityReason})
        with self.assertRaises(ValueError):
            FidelityVerdict("environment_identical")
        with self.assertRaises(ValueError):
            AtomReason("untyped_free_text")

        document = _document([
            make_element("OST_Furniture", 72_001, ordinal=0),
        ])
        source_atom = copy.deepcopy(lift_document(document)[0])
        self.assertEqual(source_atom["kind"], "atom")
        for reason in (
            AtomReason.PLACEMENT_KIND_UNKNOWN,
            AtomReason.FLIP_STATE_UNKNOWN,
            AtomReason.INSTANCE_PARAMS_INCOMPLETE,
            AtomReason.DEPENDENCY_UNRESOLVED,
            AtomReason.GENERATOR_CHILD,
        ):
            candidate = copy.deepcopy(source_atom)
            candidate["reason"] = {
                "code": reason.value,
                "detail": f"typed test evidence for {reason.value}",
            }
            self.assertEqual(
                validate_l1_node(candidate)["reason"]["code"], reason.value)

    def test_legacy_exact_maps_to_approximate_without_overclaim(self) -> None:
        document = _honesty_document()
        nodes = lift_document(document)
        tree = fold_document(document, nodes)

        verified = verify_document(document, tree, nodes)

        # The existing metrics and verdicts remain exactly as before STEP-0.
        self.assertEqual(verified.summary.exact, 2)
        self.assertEqual(verified.summary.approximate, 1)
        self.assertEqual(verified.summary.failed_count, 0)
        self.assertEqual(verified.summary.point_geometry_passthrough_pct, 100.0)

        strict = verified.fidelity_summary
        self.assertEqual(strict.fidelity_total, 3)
        self.assertEqual(strict.native_exact, 0)
        self.assertEqual(strict.form_exact, 0)
        self.assertEqual(strict.fidelity_approximate, 2)
        self.assertEqual(strict.opaque, 1)
        self.assertEqual(strict.generated_accounted, 0)
        self.assertEqual(strict.dependency_resolved, 0)
        self.assertEqual(strict.dependency_unresolved, 3)
        by_source = {
            value.source_element_id: value
            for value in verified.fidelity_verdicts
        }
        wall = by_source["71001"]
        self.assertEqual(wall.verdict, FidelityVerdict.APPROXIMATE)
        self.assertEqual(wall.legacy_verify_status, "exact")
        self.assertIn(
            FidelityReason.LEGACY_VERIFY_SCOPE_LIMITED, wall.reasons)
        self.assertIn(FidelityReason.DEPENDENCY_UNRESOLVED, wall.reasons)

        column = by_source["71002"]
        self.assertIn(FidelityReason.FLIP_STATE_UNKNOWN, column.reasons)
        self.assertIn(
            FidelityReason.INSTANCE_PARAMS_INCOMPLETE, column.reasons)
        floor = by_source["71003"]
        self.assertEqual(floor.verdict, FidelityVerdict.OPAQUE)
        self.assertEqual(
            floor.source_reason.code, AtomReason.MISSING_GEOMETRY)
        self.assertEqual(
            floor.source_reason.detail,
            next(node for node in nodes if node["source_element_id"] == "71003")
            ["reason"]["detail"],
        )

        manifest = build_dependency_manifest(document)
        grounded = replace(
            manifest,
            definitions=tuple(
                replace(definition, fingerprint=f"test-fp-{index}")
                for index, definition in enumerate(manifest.definitions)
            ),
            unresolved=(),
        )
        grounded_verify = verify_document(
            document,
            tree,
            nodes,
            dependency_manifest=grounded,
        )
        self.assertEqual(
            grounded_verify.fidelity_summary.dependency_resolved, 3)
        self.assertEqual(grounded_verify.fidelity_summary.native_exact, 0)

    def test_exact_verdicts_require_real_evidence(self) -> None:
        common = {
            "node_id": "l1:test",
            "source_element_id": "test",
            "detail": "bounded evidence",
            "legacy_verify_status": "exact",
        }
        with self.assertRaisesRegex(
                HonestyContractError, "resolved dependencies"):
            FidelityAssessment(
                **common,
                verdict=FidelityVerdict.NATIVE_EXACT,
                reasons=(FidelityReason.NATIVE_SEMANTICS_VERIFIED,),
                dependency_resolved=False,
            )
        with self.assertRaisesRegex(
                HonestyContractError, "native semantic evidence"):
            FidelityAssessment(
                **common,
                verdict=FidelityVerdict.NATIVE_EXACT,
                reasons=(FidelityReason.LEGACY_VERIFY_SCOPE_LIMITED,),
                dependency_resolved=True,
            )
        with self.assertRaisesRegex(
                HonestyContractError, "form witness"):
            FidelityAssessment(
                **common,
                verdict=FidelityVerdict.FORM_EXACT,
                reasons=(FidelityReason.GEOMETRY_EVIDENCE_INCOMPLETE,),
                dependency_resolved=False,
            )

    def test_typed_atom_reason_reaches_verify_and_passport_losslessly(self) -> None:
        document = _document([
            make_element("OST_Furniture", 73_001, ordinal=0),
        ], name="typed-reason-transport")
        node = copy.deepcopy(lift_document(document)[0])
        node["reason"] = {
            "code": AtomReason.PLACEMENT_KIND_UNKNOWN.value,
            "detail": "host mode absent from frozen L0 1.0",
        }
        validate_l1_node(node)
        tree = fold_document(document, (node,))
        verified = verify_document(document, tree, (node,))
        passport = build_passport(
            document,
            tree,
            name_document(document, tree),
            verified,
        )
        assessment = verified.fidelity_verdicts[0]
        self.assertEqual(assessment.verdict, FidelityVerdict.OPAQUE)
        self.assertEqual(
            assessment.reasons[0], FidelityReason.PLACEMENT_KIND_UNKNOWN)
        self.assertEqual(assessment.source_reason.to_dict(), node["reason"])

        leaf = next(
            value for value in _walk(passport["tree"])
            if (value.get("payload") or {}).get("_id") == node["_id"]
        )
        queried = query_passport(passport, leaf["node_id"])
        self.assertEqual(
            queried["fidelity"]["source_reason"], node["reason"])
        self.assertEqual(
            queried["fidelity"]["reasons"][0],
            AtomReason.PLACEMENT_KIND_UNKNOWN.value,
        )

        generated = copy.deepcopy(node)
        generated["reason"] = {
            "code": AtomReason.GENERATOR_CHILD.value,
            "detail": "owned by a preserved generator relationship",
        }
        generated_tree = fold_document(document, (generated,))
        generated_verify = verify_document(
            document, generated_tree, (generated,))
        self.assertEqual(
            generated_verify.fidelity_verdicts[0].verdict,
            FidelityVerdict.GENERATED_ACCOUNTED,
        )
        self.assertEqual(
            generated_verify.fidelity_summary.generated_accounted, 1)


class DependencyManifestTests(unittest.TestCase):
    def test_current_l0_manifest_names_dependencies_without_fake_hashes(
            self) -> None:
        column_a = make_element("OST_StructuralColumns", 74_001, ordinal=0)
        column_b = make_element("OST_StructuralColumns", 74_002, ordinal=0)
        wall = make_element("OST_Walls", 74_003, ordinal=0)
        for row in (column_a, column_b, wall):
            row.update({
                "phase_created": {"id": "phase-new", "name": "New"},
                "workset": {"id": "ws-a", "name": "Architecture"},
                "design_option": {"id": "option-1", "name": "Primary"},
            })
        document = _document(
            [column_b, wall, column_a],
            name="manifest-source",
            links=[{
                "element_id": "link-1",
                "name": "Structure.rvt",
                "loaded": True,
                "element_count": 17,
                "bbox_min_mm": [0.0, 0.0, 0.0],
                "bbox_max_mm": [10.0, 20.0, 30.0],
                "discipline": "Structural",
            }],
        )

        manifest = build_dependency_manifest(document)
        payload = manifest.to_dict()

        self.assertEqual(payload["schema_version"], "1.0")
        self.assertEqual(payload["target_contract"], "same_environment")
        self.assertEqual(payload["source_environment"], {
            "doc_name": "manifest-source",
            "revit_version": document.revit_version,
            "units": "mm",
            "revit_build": None,
            "document_kind": None,
            "locale": None,
            "template_fingerprint": None,
        })
        columns = next(
            value for value in manifest.definitions
            if value.identity.category == "OST_StructuralColumns"
        )
        self.assertEqual(columns.kind, DependencyKind.ELEMENT_TYPE)
        self.assertEqual(
            columns.identity.to_dict(),
            {
                "category": "OST_StructuralColumns",
                "type_name": column_a["type_name"],
            },
        )
        self.assertEqual(columns.required_by, ("74001", "74002"))
        self.assertEqual(columns.fingerprint, None)
        self.assertEqual(
            columns.resolution, DependencyResolution.TARGET_MATCH)
        self.assertFalse(columns.resolved)
        self.assertEqual(columns.identity_note, FAMILY_IDENTITY_NOTE)
        self.assertIsNone(columns.artifact_uri)
        self.assertIsNone(columns.artifact_hash)
        self.assertIsNone(columns.embedded_store_ref)
        self.assertEqual(
            payload["document_state"]["phases"],
            [{"source_id": "phase-new", "name": "New"}],
        )
        self.assertEqual(
            payload["document_state"]["worksets"],
            [{"source_id": "ws-a", "name": "Architecture"}],
        )
        self.assertEqual(
            payload["document_state"]["design_options"],
            [{"source_id": "option-1", "name": "Primary"}],
        )
        self.assertIsNone(payload["document_state"]["design_option_sets"])
        self.assertIsNone(payload["document_state"]["coordinates_sites"])
        self.assertIsNone(payload["document_state"]["parameter_bindings"])
        self.assertEqual(
            payload["external_resources"][0]["fingerprint"], None)
        self.assertEqual(
            payload["external_resources"][0]["resolution"], "unsupported")
        self.assertEqual(
            {value["key"] for value in payload["unresolved"]},
            {
                *(value["key"] for value in payload["definitions"]),
                payload["external_resources"][0]["key"],
                "source_environment:l0_1_0",
                "document_state:l0_1_0",
            },
        )
        self.assertTrue(all(
            value["reason"] == "dependency_unresolved"
            for value in payload["unresolved"]
        ))
        self.assertNotIn('"fingerprint":"', json.dumps(
            payload, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"),
        ))
        self.assertFalse(manifest.dependency_resolved_for("74001"))

    def test_portable_target_is_explicit_but_not_magically_resolved(self) -> None:
        document = _document([
            make_element("OST_Walls", 75_001, ordinal=0),
        ])
        manifest = build_dependency_manifest(
            document,
            target_contract=TargetContract.PORTABLE_EMPTY_DOCUMENT,
        )

        self.assertEqual(
            manifest.target_contract, TargetContract.PORTABLE_EMPTY_DOCUMENT)
        self.assertGreater(manifest.unresolved_count, 0)
        self.assertTrue(all(
            value.fingerprint is None for value in manifest.definitions))
        self.assertTrue(all(
            not value.resolved for value in manifest.definitions))

        empty_manifest = build_dependency_manifest(
            _document([], name="empty-manifest"))
        self.assertEqual(
            {value.key for value in empty_manifest.unresolved},
            {
                "source_environment:l0_1_0",
                "document_state:l0_1_0",
            },
        )
        self.assertEqual(
            BuildStatuses.initial(
                unresolved_dependencies=empty_manifest.unresolved_count,
            ).groundable.state,
            BuildStageState.BLOCKED,
        )


class BuildAndEquivalenceContractTests(unittest.TestCase):
    def test_four_build_statuses_default_to_unattempted_or_blocked(self) -> None:
        statuses = BuildStatuses.initial(unresolved_dependencies=4)

        self.assertEqual(
            set(statuses.to_dict()),
            {"compilable", "groundable", "executed", "roundtrip_verified"},
        )
        self.assertEqual(
            statuses.compilable.state, BuildStageState.NOT_ATTEMPTED)
        self.assertEqual(statuses.groundable.state, BuildStageState.BLOCKED)
        self.assertEqual(
            statuses.executed.state, BuildStageState.NOT_ATTEMPTED)
        self.assertEqual(
            statuses.roundtrip_verified.state,
            BuildStageState.NOT_ATTEMPTED,
        )
        no_dependencies = BuildStatuses.initial(unresolved_dependencies=0)
        self.assertEqual(
            no_dependencies.groundable.state, BuildStageState.NOT_ATTEMPTED)
        with self.assertRaises(HonestyContractError):
            BuildStatuses.initial(unresolved_dependencies=-1)
        passed = BuildStageEvidence(
            BuildStageState.PASSED, "synthetic gate evidence")
        not_attempted = BuildStageEvidence(
            BuildStageState.NOT_ATTEMPTED, "not attempted")
        with self.assertRaisesRegex(
                HonestyContractError, "executed=passed"):
            BuildStatuses(
                compilable=not_attempted,
                groundable=not_attempted,
                executed=passed,
                roundtrip_verified=not_attempted,
            )

    def test_equivalence_is_scoped_and_environment_identity_is_forbidden(
            self) -> None:
        self.assertEqual(
            {value.value for value in EquivalenceScope},
            {"native_semantic", "form", "document"},
        )
        with self.assertRaisesRegex(
                HonestyContractError, "outside the reconstructable"):
            coerce_equivalence_scope("environment_identical")
        with self.assertRaisesRegex(
                HonestyContractError, "explicit supported scope"):
            require_scope_for_equivalence_text(
                "This is a 1:1 reconstruction", None)
        require_scope_for_equivalence_text(
            "This is a 1:1 form claim", EquivalenceScope.FORM)
        with self.assertRaisesRegex(
                HonestyContractError, "must never be emitted"):
            require_scope_for_equivalence_text(
                "environment_identical", EquivalenceScope.DOCUMENT)

        result = decompile(
            _honesty_document(),
            equivalence_scope=EquivalenceScope.FORM,
        )
        self.assertEqual(result.passport["equivalence"], {
            "scope": "form",
            "state": "not_verified",
            "detail": "form equivalence has not been live-roundtrip verified",
        })
        injected = json.loads(passport_inject(result.passport))
        self.assertEqual(injected["equivalence"], {
            "scope": "form", "state": "not_verified",
        })
        self.assertEqual(injected["target_contract"], "same_environment")
        self.assertEqual(
            set(injected["build_status"]),
            {"compilable", "groundable", "executed", "roundtrip_verified"},
        )

        passed = BuildStageEvidence(
            BuildStageState.PASSED, "synthetic live gate evidence")
        all_passed = BuildStatuses(
            compilable=passed,
            groundable=passed,
            executed=passed,
            roundtrip_verified=passed,
        )
        verified_form = EquivalenceClaim(
            scope=EquivalenceScope.FORM,
            state=EquivalenceState.VERIFIED,
            detail="form equivalence verified by a synthetic test gate",
        )
        with self.assertRaisesRegex(
                PassportAssemblyError, "roundtrip_verified=passed"):
            build_passport(
                _honesty_document(),
                result.tree,
                result.name_result,
                result.verify_result,
                dependencies=result.dependency_manifest,
                build_status=result.build_status,
                equivalence=verified_form,
            )
        resolved_manifest = replace(
            result.dependency_manifest,
            definitions=tuple(
                replace(definition, fingerprint=f"test-fp-{index}")
                for index, definition in enumerate(
                    result.dependency_manifest.definitions)
            ),
            unresolved=(),
        )
        with self.assertRaisesRegex(
                PassportAssemblyError, "exact native/form evidence"):
            build_passport(
                _honesty_document(),
                result.tree,
                result.name_result,
                result.verify_result,
                dependencies=resolved_manifest,
                build_status=all_passed,
                equivalence=verified_form,
            )

    def test_pre_step_zero_passport_remains_renderable(self) -> None:
        passport = decompile(_honesty_document()).passport.to_dict()
        passport.pop("dependencies")
        passport.pop("build_status")
        passport.pop("equivalence")
        for key in (
            "fidelity_total",
            "native_exact",
            "form_exact",
            "fidelity_approximate",
            "opaque",
            "generated_accounted",
            "native_exact_pct",
            "form_exact_pct",
            "fidelity_approximate_pct",
            "opaque_pct",
            "generated_accounted_pct",
            "dependency_resolved",
            "dependency_unresolved",
            "dependency_resolved_pct",
            "fidelity_assessments_joined",
            "unknown_fidelity_assessments",
        ):
            passport["verify_summary"].pop(key, None)
        for node in _walk(passport["tree"]):
            node.pop("fidelity", None)
            node.pop("member_fidelity", None)

        injected = json.loads(passport_inject(passport))

        self.assertNotIn("equivalence", injected)
        self.assertNotIn("build_status", injected)
        self.assertNotIn(
            "dependency_resolved_pct", injected["verify_quality"])
        leaf = next(
            node for node in _walk(passport["tree"])
            if isinstance(node.get("payload"), dict)
        )
        queried = query_passport(passport, leaf["node_id"])
        self.assertIn(queried["fidelity"]["verdict"], {
            "approximate", "opaque",
        })

    def test_orchestrator_surfaces_manifest_status_and_strict_metrics(self) -> None:
        result = decompile(
            _honesty_document(),
            target_contract=TargetContract.PORTABLE_EMPTY_DOCUMENT,
            equivalence_scope=EquivalenceScope.DOCUMENT,
        )

        self.assertEqual(result.failed_count, 0)
        self.assertEqual(result.metrics["exact"], 2)
        self.assertEqual(result.metrics["native_exact"], 0)
        self.assertEqual(result.metrics["dependency_resolved"], 0)
        self.assertEqual(
            result.passport["dependencies"],
            result.dependency_manifest.to_dict(),
        )
        self.assertEqual(
            result.passport["build_status"], result.build_status.to_dict())
        self.assertEqual(
            result.passport["equivalence"], result.equivalence.to_dict())
        self.assertEqual(
            result.passport["verify_summary"]["fidelity_approximate"], 2)
        self.assertEqual(
            result.to_dict()["dependencies"]["target_contract"],
            "portable_empty_document",
        )

    def test_frozen_l0_1_0_shape_is_unchanged(self) -> None:
        self.assertEqual(L0_SCHEMA_VERSION, "1.0")
        field_names = {value.name for value in fields(L0Element)}
        self.assertFalse({
            "mirrored",
            "hand_flipped",
            "facing_flipped",
            "family_name",
            "is_family_instance",
            "group_id",
        } & field_names)


class HonestyDeterminismTests(unittest.TestCase):
    def test_result_is_identical_under_two_pythonhashseed_values(self) -> None:
        outputs: list[str] = []
        for seed in ("31", "9001"):
            env = os.environ.copy()
            env["PYTHONHASHSEED"] = seed
            env["PYTHONPATH"] = str(REPO_ROOT / "backend")
            completed = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "from kukai.ir.decompile.tests.test_honesty import "
                        "seeded_honesty_payload; "
                        "print(seeded_honesty_payload())"
                    ),
                ],
                cwd=REPO_ROOT,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
            outputs.append(completed.stdout.strip())

        self.assertEqual(outputs[0], outputs[1])
        payload = json.loads(outputs[0])
        self.assertEqual(
            payload["dependencies"]["target_contract"],
            "portable_empty_document",
        )
        self.assertEqual(payload["equivalence"]["scope"], "document")
        self.assertEqual(payload["metrics"]["native_exact"], 0)


if __name__ == "__main__":
    unittest.main()
