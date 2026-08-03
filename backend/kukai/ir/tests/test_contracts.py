"""PR1 contract vocabulary: compatibility, invariants, and fail-closed proof."""
from __future__ import annotations

import copy
import json
import unittest
from dataclasses import FrozenInstanceError

from kukai.ir.contracts import (
    CleanupReceipt,
    CommitReceipt,
    ContractSchemaError,
    CoverageProof,
    DocumentFingerprint,
    ElementIdentityProof,
    IdempotenceMetrics,
    RevisionProof,
    RunId,
    SnapshotManifest,
)


RUN_ID = "0123456789abcdef"
STAMP_PREFIX = f"kir:a5:0123456789ab:{RUN_ID}:"


def _fingerprint() -> DocumentFingerprint:
    return DocumentFingerprint(
        title="Tower_A5_COPY",
        path_name=r"C:\models\tower-copy.rvt",
        project_uid="project-uid-1",
    )


def _coverage(*, partial: bool = False) -> CoverageProof:
    return CoverageProof(
        stream_complete=True,
        required_categories=("OST_Walls", "OST_Doors"),
        complete_categories=("OST_Walls",) if partial else (
            "OST_Walls", "OST_Doors"),
        partial_categories=("OST_Doors",) if partial else (),
        element_count=12,
        link_count=1,
    )


def _metrics() -> IdempotenceMetrics:
    return IdempotenceMetrics(
        comparison_performed=True,
        multiset_match=False,
        total_expected=2,
        total_actual=3,
        total_matched=2,
        total_extra=1,
        raw_precision_pct=66.667,
        raw_recall_pct=100.0,
        adjusted_precision_pct=66.667,
        adjusted_recall_pct=100.0,
        atoms_excluded=1,
        non_datum_total=3,
        comparable_coverage_pct=66.667,
        canon_version="fidelity-canon/1",
    )


class DocumentIdentityContracts(unittest.TestCase):
    def test_fingerprint_round_trip_and_compiler_guard_are_stable(self) -> None:
        fingerprint = _fingerprint()
        encoded = fingerprint.to_dict()

        self.assertEqual(
            fingerprint.compiler_guard(),
            {
                "title": "Tower_A5_COPY",
                "path_name": r"C:\models\tower-copy.rvt",
                "project_uid": "project-uid-1",
            },
        )
        self.assertEqual(
            DocumentFingerprint.from_dict(json.loads(json.dumps(encoded))),
            fingerprint,
        )
        self.assertEqual(len(fingerprint.digest), 64)

    def test_fingerprint_reads_unversioned_and_ignores_additive_fields(self) -> None:
        legacy = {**_fingerprint().compiler_guard(), "future_field": {"v": 2}}
        before = copy.deepcopy(legacy)

        self.assertEqual(DocumentFingerprint.from_dict(legacy), _fingerprint())
        self.assertEqual(legacy, before)

    def test_fingerprint_is_frozen(self) -> None:
        with self.assertRaises(FrozenInstanceError):
            _fingerprint().title = "other"  # type: ignore[misc]

    def test_revision_proof_preserves_existing_wire_shape(self) -> None:
        proof = RevisionProof("stamp-1", "12:0123456789abcdef:fedcba9876543210")
        self.assertEqual(
            proof.to_dict(),
            {
                "schema_version": "document-revision/1",
                "change_stamp": "stamp-1",
                "fingerprint": "12:0123456789abcdef:fedcba9876543210",
            },
        )
        legacy = {
            "change_stamp": proof.change_stamp,
            "fingerprint": proof.fingerprint,
            "future": True,
        }
        self.assertEqual(RevisionProof.from_dict(legacy), proof)

    def test_element_identity_is_versioned_exact_and_legacy_readable(self) -> None:
        proof = ElementIdentityProof(
            element_id=5_000_000_000,
            unique_id="level-42",
            version_guid="0123456789abcdef0123456789abcdef",
        )

        self.assertEqual(
            ElementIdentityProof.from_dict(proof.to_dict()),
            proof,
        )
        self.assertEqual(
            ElementIdentityProof.from_dict({
                "element_id": proof.element_id,
                "unique_id": proof.unique_id,
                "version_guid": proof.version_guid,
                "future": True,
            }),
            proof,
        )

    def test_element_identity_refuses_weak_or_unknown_evidence(self) -> None:
        base = {
            "element_id": 42,
            "unique_id": "level-42",
            "version_guid": "0" * 32,
        }
        for patch in (
            {"element_id": 0},
            {"element_id": True},
            {"unique_id": ""},
            {"version_guid": "not-a-guid"},
            {"version_guid": "A" * 32},
            {"schema_version": "revit-element-identity/99"},
        ):
            with self.subTest(patch=patch):
                with self.assertRaises(ContractSchemaError):
                    ElementIdentityProof.from_dict({**base, **patch})

    def test_run_id_round_trip_and_legacy_value_alias(self) -> None:
        run_id = RunId(RUN_ID)
        self.assertEqual(RunId.from_dict(run_id.to_dict()), run_id)
        self.assertEqual(RunId.from_dict({"value": RUN_ID}), run_id)
        self.assertEqual(str(run_id), RUN_ID)

    def test_unknown_explicit_version_and_bad_run_id_are_refused(self) -> None:
        row = _fingerprint().to_dict()
        row["schema_version"] = "document-fingerprint/99"
        with self.assertRaises(ContractSchemaError):
            DocumentFingerprint.from_dict(row)
        row["schema_version"] = None
        with self.assertRaises(ContractSchemaError):
            DocumentFingerprint.from_dict(row)
        with self.assertRaises(ContractSchemaError):
            RunId("ABCDEF0123456789")


class SnapshotContracts(unittest.TestCase):
    def test_complete_named_coverage_is_authoritative(self) -> None:
        proof = _coverage()
        self.assertTrue(proof.authoritative)
        self.assertEqual(CoverageProof.from_dict(proof.to_dict()), proof)

    def test_legacy_category_states_need_the_known_category_universe(self) -> None:
        legacy = {
            "stream_complete": True,
            "element_count": 12,
            "link_count": 1,
            "category_count": 2,
            "category_states": {
                "OST_Walls": "complete",
                "OST_Doors": "complete",
            },
            "future_footer_field": "ignored",
        }
        unbound = CoverageProof.from_dict(legacy)
        bound = CoverageProof.from_dict(
            legacy, required_categories=("OST_Doors", "OST_Walls"))

        self.assertFalse(unbound.authoritative)
        self.assertTrue(bound.authoritative)

    def test_partial_or_incomplete_coverage_never_becomes_authoritative(self) -> None:
        self.assertFalse(_coverage(partial=True).authoritative)
        incomplete = CoverageProof(
            stream_complete=True,
            required_categories=("A", "B"),
            complete_categories=("A",),
            partial_categories=(),
            element_count=1,
        )
        self.assertFalse(incomplete.authoritative)

    def test_coverage_rejects_contradictory_derived_fields(self) -> None:
        row = _coverage().to_dict()
        row["authoritative"] = False
        with self.assertRaises(ContractSchemaError):
            CoverageProof.from_dict(row)
        row = _coverage().to_dict()
        row["category_count"] = 999
        with self.assertRaises(ContractSchemaError):
            CoverageProof.from_dict(row)

    def test_snapshot_round_trip_binds_identity_revision_and_coverage(self) -> None:
        manifest = SnapshotManifest(
            doc_stamp="stamp-1",
            document_fingerprint=_fingerprint(),
            revision_proof=RevisionProof("stamp-1", "revision-1"),
            coverage=_coverage(),
        )
        wire = manifest.to_dict()
        wire["future_manifest_field"] = [1, 2, 3]
        wire["document_fingerprint"]["future_identity_field"] = "ok"

        self.assertTrue(manifest.authoritative)
        self.assertEqual(SnapshotManifest.from_dict(wire), manifest)

    def test_snapshot_refuses_revision_from_another_stamp(self) -> None:
        with self.assertRaises(ContractSchemaError):
            SnapshotManifest(
                doc_stamp="stamp-1",
                document_fingerprint=_fingerprint(),
                revision_proof=RevisionProof("stamp-2", "revision-1"),
                coverage=_coverage(),
            )


class ReceiptContracts(unittest.TestCase):
    def test_confirmed_commit_receipt_round_trip(self) -> None:
        receipt = CommitReceipt(
            run_id=RunId(RUN_ID),
            operation="rebuild",
            element_ids=("101", "102"),
            bridge_error=False,
            commit_confirmed=True,
            commit_status="Committed",
        )

        self.assertTrue(receipt.confirmed)
        self.assertFalse(receipt.resumable_rebuild)
        self.assertEqual(CommitReceipt.from_dict(receipt.to_dict()), receipt)

    def test_rebuild_receipt_proves_exact_resume_boundary(self) -> None:
        """СТРАЖ ВЕРСИИ ПИСАТЕЛЯ.

        /2 -> /3 (29.07, задача №25): квитанция чанка получила
        ``op_refusals``/``ops_total``/``ops_no_element`` и закон переписи
        «создано + отказало + без-элемента == опов». Повод — пересборка №11:
        113 линий разрезки витража отказали ВНУТРИ закоммиченных чанков, и
        причина не сохранялась нигде. Читаемость /1 и /2 проверяется тестами
        ниже; ``ops_total=0`` выключает закон на старых журналах.
        """
        receipt = CommitReceipt(
            run_id=RunId(RUN_ID),
            operation="rebuild",
            element_ids=("101", "102"),
            bridge_error=False,
            commit_confirmed=True,
            commit_status="Committed",
            program_id="a" * 64,
            document_revision="revision-after-chunk-0",
        )

        self.assertTrue(receipt.resumable_rebuild)
        self.assertEqual(
            receipt.to_dict()["schema_version"], "a5-commit-receipt/3")
        self.assertEqual(CommitReceipt.from_dict(receipt.to_dict()), receipt)

    def test_v2_receipt_remains_readable(self) -> None:
        """Журналы прогонов №9-№11 писаны /2 и обязаны реплеиться."""
        receipt = CommitReceipt.from_dict({
            "schema_version": "a5-commit-receipt/2",
            "run_id": RUN_ID,
            "operation": "rebuild",
            "element_ids": ["101", "102"],
            "element_count": 2,
            "bridge_error": False,
            "commit_confirmed": True,
            "commit_status": "Committed",
            "program_id": "a" * 64,
            "document_revision": "revision-after-chunk-0",
        })

        self.assertTrue(receipt.resumable_rebuild)
        self.assertEqual(receipt.op_refusals, ())
        self.assertEqual(receipt.ops_total, 0)

    def test_v1_receipt_remains_readable_but_not_resumable(self) -> None:
        receipt = CommitReceipt.from_dict({
            "schema_version": "a5-commit-receipt/1",
            "run_id": RUN_ID,
            "operation": "rebuild",
            "element_ids": ["101"],
            "element_count": 1,
            "bridge_error": False,
            "commit_confirmed": True,
            "commit_status": "Committed",
        })

        self.assertTrue(receipt.confirmed)
        self.assertFalse(receipt.resumable_rebuild)

    def test_legacy_ledger_commit_is_readable_but_not_upgraded_to_proof(self) -> None:
        legacy = {
            "version": "a5-run-ledger/1",
            "event": "rebuild_commit_receipt",
            "run_id": RUN_ID,
            "time_ns": 123,
            "created_ids": ["101", "102"],
            "created_ids_count": 2,
            "bridge_error": False,
            "future": "ignored",
        }
        receipt = CommitReceipt.from_dict(legacy)

        self.assertEqual(receipt.operation, "rebuild")
        self.assertEqual(receipt.element_ids, ("101", "102"))
        self.assertFalse(receipt.commit_confirmed)
        self.assertFalse(receipt.confirmed)

    def test_commit_receipt_rejects_bad_count_and_string_boolean(self) -> None:
        legacy = {
            "event": "delete_commit_receipt",
            "run_id": RUN_ID,
            "deleted_ids": ["101"],
            "deleted_ids_count": 2,
            "bridge_error": False,
        }
        with self.assertRaises(ContractSchemaError):
            CommitReceipt.from_dict(legacy)
        legacy["deleted_ids_count"] = 1
        legacy["bridge_error"] = "false"
        with self.assertRaises(ContractSchemaError):
            CommitReceipt.from_dict(legacy)

    def test_exact_cleanup_receipt_round_trip(self) -> None:
        receipt = CleanupReceipt(
            run_id=RunId(RUN_ID),
            stamp_prefix=STAMP_PREFIX,
            found_count=2,
            deleted_count=2,
            remaining_count=0,
            found_ids=("101", "102"),
            deleted_ids=("102", "101"),
            remaining_ids=(),
            commit_status="Committed",
            reconciled=True,
            witnesses_complete=True,
        )

        self.assertTrue(receipt.ownership_bound)
        self.assertTrue(receipt.confirmed)
        self.assertEqual(CleanupReceipt.from_dict(receipt.to_dict()), receipt)

    def test_legacy_reconciliation_is_readable_but_not_exact_proof(self) -> None:
        legacy = {
            "version": "a5-run-ledger/1",
            "event": "stamp_reconciliation",
            "run_id": RUN_ID,
            "found": 2,
            "remaining": 0,
            "commit_status": "Committed",
            "reconciled": True,
        }
        receipt = CleanupReceipt.from_dict(legacy)

        self.assertTrue(receipt.reconciled)
        self.assertFalse(receipt.ownership_bound)
        self.assertFalse(receipt.witnesses_complete)
        self.assertFalse(receipt.confirmed)

    def test_cleanup_prefix_is_exactly_bound_to_run_id(self) -> None:
        with self.assertRaises(ContractSchemaError):
            CleanupReceipt(
                run_id=RunId(RUN_ID),
                stamp_prefix="kir:a5:0123456789ab:fedcba9876543210:",
                found_count=0,
                deleted_count=0,
                remaining_count=0,
                found_ids=(),
                deleted_ids=(),
                remaining_ids=(),
                commit_status="NotStarted",
                reconciled=True,
                witnesses_complete=True,
            )


class MetricsContracts(unittest.TestCase):
    def test_current_metrics_round_trip_keeps_legacy_recall_aliases(self) -> None:
        metrics = _metrics()
        wire = metrics.to_dict()

        self.assertEqual(wire["raw_exact_pct"], wire["raw_recall_pct"])
        self.assertEqual(
            wire["adjusted_exact_pct"], wire["adjusted_recall_pct"])
        self.assertEqual(IdempotenceMetrics.from_dict(wire), metrics)
        self.assertTrue(metrics.precision_available)

    def test_legacy_recall_only_metrics_remain_readable_without_fake_precision(
        self,
    ) -> None:
        legacy = {
            "multiset_match": True,
            "total_expected": 2,
            "total_matched": 2,
            "raw_exact_pct": 100.0,
            "adjusted_exact_pct": 100.0,
            "future_metric": 7,
        }
        metrics = IdempotenceMetrics.from_dict(legacy)

        self.assertTrue(metrics.comparison_performed)
        self.assertEqual(metrics.raw_recall_pct, 100.0)
        self.assertIsNone(metrics.total_actual)
        self.assertIsNone(metrics.raw_precision_pct)
        self.assertFalse(metrics.precision_available)

    def test_unperformed_comparison_cannot_claim_percentages(self) -> None:
        dry = {
            "comparison_performed": False,
            "multiset_match": None,
            "total_expected": 2,
            "total_matched": 0,
            "non_datum_total": 2,
        }
        self.assertFalse(IdempotenceMetrics.from_dict(dry).comparison_performed)
        dry["raw_exact_pct"] = 100.0
        with self.assertRaises(ContractSchemaError):
            IdempotenceMetrics.from_dict(dry)

    def test_metrics_reject_false_denominators_and_unknown_version(self) -> None:
        wire = _metrics().to_dict()
        wire["total_extra"] = 0
        with self.assertRaises(ContractSchemaError):
            IdempotenceMetrics.from_dict(wire)
        wire = _metrics().to_dict()
        wire["schema_version"] = "idempotence-metrics/2"
        with self.assertRaises(ContractSchemaError):
            IdempotenceMetrics.from_dict(wire)


if __name__ == "__main__":
    unittest.main()
