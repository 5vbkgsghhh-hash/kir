"""Open-model profile: compatibility, identity and pre-transaction refusal."""
from __future__ import annotations

import copy
import json
import unittest

from kukai.ir.contracts import RevisionProof
from kukai.ir.open_model import (
    GROUND_SNAPSHOT_CS,
    OpenModelProfile,
    OpenModelProfileError,
    PreflightIssueCode,
    preflight_programs,
    required_grounding_pools,
)
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT


def _live_snapshot() -> dict:
    snapshot = copy.deepcopy(GROUND_SNAPSHOT)
    for pool_name in required_grounding_pools():
        rows = snapshot.setdefault(pool_name, [])
        for row in rows:
            element_id = int(row["id"])
            row["unique_id"] = f"{pool_name}:uid:{element_id}"
            row["version_guid"] = f"{element_id:032x}"
            row["class_name"] = "Autodesk.Revit.DB.ElementType"
        snapshot[pool_name + "__total"] = len(rows)
    snapshot.update({
        "__profile_schema_version": "open-model-profile/1",
        "__profile_required_pools": list(required_grounding_pools()),
        "__document_fingerprint": {
            "title": "Tower — COPY",
            "path_name": r"C:\models\tower-copy.rvt",
            "project_uid": "tower-project-uid",
        },
        "__revit_version": "2026",
        "__revit_build": "26.0.4.0",
    })
    return snapshot


def _profile(snapshot: dict | None = None) -> OpenModelProfile:
    return OpenModelProfile.from_ground_snapshot(
        _live_snapshot() if snapshot is None else snapshot,
        revision_proof=RevisionProof(
            "tower-revision",
            "1200:0123456789abcdef:fedcba9876543210"),
    )


def _wall_program(*, level_id: int = 42, type_id: int = 100) -> dict:
    return {
        "ir_version": "1.0",
        "ops": [{
            "op": "create_wall",
            "id": "W1",
            "p0_mm": [0, 0],
            "p1_mm": [6000, 0],
            "height_mm": 3000,
            "level": {"by": "element_id", "value": level_id},
            "type": {"by": "element_id", "value": type_id},
        }],
    }


class OpenModelProfileContractTests(unittest.TestCase):
    def test_registry_is_the_pool_source_of_truth_and_probe_proves_counts(
            self) -> None:
        pools = required_grounding_pools()

        # 17 -> 19: wave/arch добавила ceiling_types и railing_types
        # (create_ceiling / create_railing). Число держится руками намеренно —
        # новый пул тянет за собой сборщик в GROUND_SNAPSHOT_CS, и молча
        # выросшая цифра означала бы пул, который никто не собирает.
        self.assertEqual(len(pools), 19)
        for pool in pools:
            if pool == "grids":
                self.assertIn('__snap["grids__total"]', GROUND_SNAPSHOT_CS)
            else:
                self.assertIn(f'__AddPool("{pool}"', GROUND_SNAPSHOT_CS)
        self.assertIn('__r["unique_id"]', GROUND_SNAPSHOT_CS)
        self.assertIn('__r["version_guid"]', GROUND_SNAPSHOT_CS)
        self.assertIn('__snap["__document_fingerprint"]', GROUND_SNAPSHOT_CS)
        self.assertIn(
            '__snap[__pool + "__total"] = __total', GROUND_SNAPSHOT_CS)
        self.assertNotIn("IntegerValue", GROUND_SNAPSHOT_CS)

    def test_live_profile_is_revision_bound_authoritative_and_round_trips(
            self) -> None:
        profile = _profile()
        encoded = profile.to_dict()

        self.assertTrue(profile.identity_bound)
        self.assertTrue(profile.grounding_complete)
        self.assertTrue(profile.identity_complete)
        self.assertTrue(profile.authoritative)
        self.assertEqual(len(profile.digest), 64)
        self.assertEqual(
            OpenModelProfile.from_dict(
                json.loads(json.dumps(encoded, ensure_ascii=False))),
            profile,
        )

    def test_order_is_canonical_and_digest_is_deterministic(self) -> None:
        forward = _live_snapshot()
        reverse = copy.deepcopy(forward)
        for pool in required_grounding_pools():
            reverse[pool] = list(reversed(reverse[pool]))

        a = _profile(forward)
        b = _profile(reverse)

        self.assertEqual(a, b)
        self.assertEqual(a.digest, b.digest)
        self.assertEqual(a.to_dict(), b.to_dict())

    def test_legacy_snapshot_remains_groundable_but_not_authoritative(
            self) -> None:
        legacy = copy.deepcopy(GROUND_SNAPSHOT)
        before = copy.deepcopy(legacy)
        profile = OpenModelProfile.from_ground_snapshot(legacy)
        report = preflight_programs(_wall_program(), profile)

        self.assertFalse(profile.authoritative)
        self.assertFalse(profile.grounding_complete)
        self.assertFalse(profile.identity_complete)
        self.assertTrue(report.ready)
        self.assertEqual(len(report.bindings), 2)
        self.assertEqual(legacy, before)

    def test_unknown_explicit_version_is_refused(self) -> None:
        snapshot = _live_snapshot()
        snapshot["__profile_schema_version"] = "open-model-profile/99"
        with self.assertRaisesRegex(
                OpenModelProfileError, "unsupported"):
            OpenModelProfile.from_ground_snapshot(snapshot)

        row = _profile().to_dict()
        row["schema_version"] = "open-model-profile/99"
        with self.assertRaisesRegex(
                OpenModelProfileError, "unsupported"):
            OpenModelProfile.from_dict(row)

    def test_truncation_and_missing_total_never_become_authoritative(
            self) -> None:
        truncated = _live_snapshot()
        truncated["levels"] = truncated["levels"][:1]
        truncated["levels__truncated"] = True
        # The observed total remains two.
        profile = _profile(truncated)
        self.assertFalse(profile.grounding_complete)
        self.assertFalse(profile.authoritative)

        unproven = _live_snapshot()
        unproven.pop("levels__total")
        profile = _profile(unproven)
        self.assertFalse(profile.grounding_complete)
        self.assertFalse(profile.authoritative)

    def test_derived_flags_and_digest_cannot_lie(self) -> None:
        row = _profile().to_dict()
        row["authoritative"] = False
        with self.assertRaisesRegex(OpenModelProfileError, "mismatch"):
            OpenModelProfile.from_dict(row)

        row = _profile().to_dict()
        row["digest"] = "0" * 64
        with self.assertRaisesRegex(OpenModelProfileError, "digest mismatch"):
            OpenModelProfile.from_dict(row)

    def test_duplicate_ids_and_contradictory_counts_are_refused(self) -> None:
        duplicate = _live_snapshot()
        duplicate["levels"].append(copy.deepcopy(duplicate["levels"][0]))
        duplicate["levels__total"] += 1
        with self.assertRaisesRegex(OpenModelProfileError, "unique ElementId"):
            _profile(duplicate)

        contradictory = _live_snapshot()
        contradictory["levels__total"] = 1
        with self.assertRaisesRegex(OpenModelProfileError, "below captured"):
            _profile(contradictory)


class OpenModelPreflightTests(unittest.TestCase):
    def test_pinned_level_and_type_are_bound_before_transaction(self) -> None:
        report = preflight_programs(
            _wall_program(), _profile(), require_exact_identity=True)

        self.assertTrue(report.ready)
        self.assertEqual(
            [(item.pool, item.element_id) for item in report.bindings],
            [("levels", 42), ("wall_types", 100)],
        )
        self.assertEqual(
            [proof.element_id for proof in report.exact_identity_proofs()],
            [42, 100],
        )
        self.assertEqual(report.to_dict()["binding_count"], 2)

    def test_missing_pinned_element_refuses(self) -> None:
        report = preflight_programs(
            _wall_program(level_id=999_999), _profile(),
            require_exact_identity=True,
        )

        self.assertFalse(report.ready)
        self.assertEqual(
            report.issues[0].code,
            PreflightIssueCode.PINNED_ELEMENT_MISSING,
        )
        self.assertEqual(report.issues[0].pool, "levels")

    def test_incomplete_pool_refuses_exact_same_document_preflight(self) -> None:
        legacy = OpenModelProfile.from_ground_snapshot(
            copy.deepcopy(GROUND_SNAPSHOT))
        report = preflight_programs(
            _wall_program(), legacy, require_exact_identity=True)

        self.assertFalse(report.ready)
        self.assertEqual(
            {item.code for item in report.issues},
            {PreflightIssueCode.PROFILE_POOL_INCOMPLETE},
        )
        with self.assertRaisesRegex(
                OpenModelProfileError, "refused preflight"):
            report.exact_identity_proofs()

    def test_malformed_version_guid_is_not_exact_evidence(self) -> None:
        snapshot = _live_snapshot()
        snapshot["levels"][0]["version_guid"] = "not-a-revit-guid"
        report = preflight_programs(
            _wall_program(), _profile(snapshot), require_exact_identity=True)

        self.assertFalse(report.ready)
        self.assertEqual(
            report.issues[0].code,
            PreflightIssueCode.PINNED_IDENTITY_UNPROVEN,
        )

    def test_element_id_reuse_or_type_edit_is_detected(self) -> None:
        source = _profile()
        changed_snapshot = _live_snapshot()
        changed = next(
            row for row in changed_snapshot["wall_types"]
            if row["id"] == 100)
        changed["version_guid"] = "f" * 32
        target = _profile(changed_snapshot)

        report = preflight_programs(
            _wall_program(),
            target,
            expected_profile=source,
            require_exact_identity=True,
        )

        self.assertFalse(report.ready)
        self.assertEqual(
            [item.code for item in report.issues],
            [PreflightIssueCode.PINNED_IDENTITY_CHANGED],
        )

    def test_wrong_open_document_is_detected_even_when_ids_match(self) -> None:
        source = _profile()
        other_snapshot = _live_snapshot()
        other_snapshot["__document_fingerprint"]["project_uid"] = "other"
        target = _profile(other_snapshot)

        report = preflight_programs(
            _wall_program(),
            target,
            expected_profile=source,
            require_exact_identity=True,
        )

        self.assertFalse(report.ready)
        self.assertEqual(
            report.issues[0].code,
            PreflightIssueCode.DOCUMENT_IDENTITY_CHANGED,
        )

    def test_name_selectors_remain_owned_by_ground_stage(self) -> None:
        program = _wall_program()
        program["ops"][0]["level"] = {"by": "name", "value": "Этаж 1"}
        program["ops"][0]["type"] = {"by": "default"}

        report = preflight_programs(
            program, _profile(), require_exact_identity=True)

        self.assertTrue(report.ready)
        self.assertFalse(report.bindings)


if __name__ == "__main__":
    unittest.main()
