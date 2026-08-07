"""Contracts for the immutable ground -> lower -> authoring boundary."""
from __future__ import annotations

import dataclasses
import unittest
from unittest import mock

from kukai.compiler_contract import load_target_profile_manifest
from kukai.ir import authoring, ground
from kukai.ir.compiler import CompileOutput, compile_program, plan_program
from kukai.ir.contracts import ElementIdentityProof
from kukai.ir.emitted_artifact import EmittedArtifact
from kukai.ir.lowering import (
    AuthoringPolicy,
    AuthoringTemplate,
    IsolationMode,
    LoweredProgram,
    PostconditionMode,
    lower_program,
)
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT


WALL = {
    "op": "create_wall",
    "id": "W1",
    "p0_mm": [0, 0],
    "p1_mm": [6000, 0],
    "level": {"by": "name", "value": "Этаж 1"},
}
STAIRS = {
    "op": "create_stairs",
    "id": "S1",
    "p0_mm": [0, 0],
    "p1_mm": [0, 3000],
    "base_level": {"by": "name", "value": "Этаж 1"},
    "top_level": {"by": "name", "value": "Этаж 2"},
    "width_mm": 1200,
}


def _program(op: dict, *, intent: str = "lowering test") -> dict:
    return {"ir_version": "1.0", "intent": intent, "ops": [op]}


def _grounded(op: dict = WALL):
    return ground.ground_program(
        plan_program(_program(op)),
        GROUND_SNAPSHOT,
    )


class TestLoweringContract(unittest.TestCase):
    def test_lowering_binds_ground_target_policy_template_and_stamp(self):
        grounded = _grounded()
        lowered = lower_program(
            grounded,
            "2026",
            expected_document={
                "title": "Model A",
                "path_name": r"C:\models\a.rvt",
                "project_uid": "project-a",
            },
            open_model_profile_digest="a" * 64,
        )

        self.assertIs(lowered.grounded, grounded)
        self.assertEqual(lowered.target_profile.revit_year, "2026")
        self.assertEqual(
            lowered.template, AuthoringTemplate.SHARED_TRANSACTION)
        self.assertEqual(lowered.policy.isolation, IsolationMode.ATOMIC)
        self.assertEqual(
            lowered.policy.postconditions, PostconditionMode.STRICT)
        self.assertRegex(lowered.program_stamp, r"^kir:[0-9a-f]{8}$")
        self.assertRegex(lowered.lower_digest, r"^[0-9a-f]{64}$")
        evidence = lowered.to_evidence_dict()
        self.assertEqual(evidence["ground_digest"], grounded.ground_digest)
        self.assertEqual(
            evidence["target_profile"]["profile_digest"],
            lowered.target_profile.profile_digest,
        )
        self.assertEqual(
            evidence["policy"]["open_model_profile_digest"], "a" * 64)

    def test_detached_grounding_view_cannot_mutate_lowering_evidence(self):
        lowered = lower_program(_grounded(), "2026")
        digest = lowered.lower_digest
        stamp = lowered.program_stamp

        detached = lowered.grounded.to_ops()
        detached[0]["p1_mm"][0] = 999_999
        detached[0]["level"]["__grounded__"]["id"] = 999_999

        self.assertEqual(lowered.lower_digest, digest)
        self.assertEqual(lowered.program_stamp, stamp)
        self.assertNotEqual(lowered.grounded.to_ops()[0]["p1_mm"][0],
                            999_999)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            lowered.program_stamp = "kir:00000000"  # type: ignore[misc]

    def test_forged_stamp_digest_profile_and_parent_are_rejected(self):
        lowered = lower_program(_grounded(), "2026")
        with self.assertRaisesRegex(ValueError, "program stamp"):
            dataclasses.replace(lowered, program_stamp="kir:00000000")
        with self.assertRaisesRegex(ValueError, "lower_digest"):
            dataclasses.replace(lowered, lower_digest="0" * 64)

        forged_profile = dataclasses.replace(
            lowered.target_profile,
            profile_digest="0" * 64,
        )
        with self.assertRaisesRegex(ValueError, "packaged contract"):
            dataclasses.replace(
                lowered,
                target_profile=forged_profile,
                lower_digest="",
            )

        other_wall = dict(WALL, p1_mm=[7000, 0])
        with self.assertRaisesRegex(ValueError, "program stamp"):
            dataclasses.replace(
                lowered,
                grounded=_grounded(other_wall),
                lower_digest="",
            )

    def test_effective_policy_is_canonical(self):
        grounded = _grounded()
        per_op = lower_program(
            grounded,
            "2026",
            isolation="per_op",
            postconditions="strict",
            disallow_wall_joins=True,
        )
        self.assertEqual(per_op.policy.isolation, IsolationMode.PER_OP)
        self.assertEqual(
            per_op.policy.postconditions, PostconditionMode.REPORT)
        self.assertTrue(per_op.policy.disallow_wall_joins)

        atomic = lower_program(
            grounded,
            "2026",
            isolation="atomic",
            disallow_wall_joins=True,
        )
        self.assertFalse(atomic.policy.disallow_wall_joins)

        stairs = lower_program(
            _grounded(STAIRS),
            "2026",
            isolation="per_op",
            postconditions="report",
            disallow_wall_joins=True,
        )
        self.assertEqual(stairs.template, AuthoringTemplate.STAIRS_EDIT_SCOPE)
        self.assertEqual(stairs.policy.isolation, IsolationMode.ATOMIC)
        self.assertEqual(
            stairs.policy.postconditions, PostconditionMode.STRICT)
        self.assertFalse(stairs.policy.disallow_wall_joins)

        with self.assertRaisesRegex(ValueError, "per-op isolation"):
            AuthoringPolicy(
                isolation=IsolationMode.PER_OP,
                postconditions=PostconditionMode.STRICT,
                disallow_wall_joins=False,
                stamp_scope="",
                expected_document=None,
                expected_identities=(),
            )

    def test_identity_proofs_are_deduplicated_sorted_and_conflicts_fail(self):
        id_42 = ElementIdentityProof(42, "level-42", "0" * 32)
        id_43 = ElementIdentityProof(43, "level-43", "1" * 32)
        lowered = lower_program(
            _grounded(),
            "2026",
            expected_identities=(id_43, id_42, id_42),
        )
        self.assertEqual(
            [proof.element_id for proof in lowered.policy.expected_identities],
            [42, 43],
        )

        conflict = ElementIdentityProof(42, "other-42", "2" * 32)
        with self.assertRaisesRegex(ValueError, "contradictory"):
            lower_program(
                _grounded(),
                "2026",
                expected_identities=(id_42, conflict),
            )

    def test_only_packaged_target_profiles_are_accepted(self):
        profile = load_target_profile_manifest().profile_for_year("2026")
        lowered = lower_program(_grounded(), profile)
        self.assertIs(lowered.target_profile, profile)

        forged = dataclasses.replace(profile, profile_id="private-profile")
        with self.assertRaisesRegex(ValueError, "packaged contract"):
            lower_program(_grounded(), forged)


class TestTypedAuthoringPath(unittest.TestCase):
    def _assert_legacy_parity(self, op: dict, **policy) -> None:
        out = compile_program(
            _program(op),
            revit_version="2026",
            snapshot=GROUND_SNAPSHOT,
            **policy,
        )
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        self.assertIsNotNone(out.lowered)
        self.assertIsInstance(out.emitted, EmittedArtifact)
        self.assertEqual(out.csharp, out.emitted.source)
        legacy = authoring.emit_program(
            out.grounded.to_ops(),
            "2026",
            out.planned.intent,
            isolation=policy.get("isolation", "atomic"),
            disallow_wall_joins=policy.get("disallow_wall_joins", False),
            stamp_scope=policy.get("stamp_scope", ""),
            expected_document=policy.get("expected_document"),
            expected_identities=policy.get("expected_identities"),
        )
        self.assertEqual(out.csharp, legacy)

    def test_typed_and_legacy_emitters_are_byte_equal(self):
        self._assert_legacy_parity(WALL)
        self._assert_legacy_parity(
            WALL,
            isolation="per_op",
            disallow_wall_joins=True,
            stamp_scope="a5:0123456789ab:0123456789abcdef",
        )
        self._assert_legacy_parity(STAIRS, isolation="per_op")

    def test_compiler_bypasses_the_raw_mutable_facade(self):
        with mock.patch.object(
            authoring,
            "emit_program",
            side_effect=AssertionError("raw facade must not be called"),
        ):
            out = compile_program(
                _program(WALL),
                revit_version="2026",
                snapshot=GROUND_SNAPSHOT,
            )
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        self.assertIsInstance(out.lowered, LoweredProgram)

    def test_lower_digest_is_internal_until_wire_contract_is_versioned(self):
        out = compile_program(
            _program(WALL),
            revit_version="2026",
            snapshot=GROUND_SNAPSHOT,
        )
        self.assertTrue(out.ok)
        self.assertIsNotNone(out.lowered)
        self.assertIsNotNone(out.emitted)
        self.assertNotIn("lower_digest", out.as_dict())
        self.assertNotIn("artifact_digest", out.as_dict())

    def test_emitted_artifact_is_content_addressed_and_parent_bound(self):
        out = compile_program(
            _program(WALL),
            revit_version="2026",
            snapshot=GROUND_SNAPSHOT,
        )
        artifact = out.emitted
        self.assertIsInstance(artifact, EmittedArtifact)
        self.assertIs(artifact.lowered, out.lowered)
        self.assertRegex(artifact.source_sha256, r"^[0-9a-f]{64}$")
        self.assertRegex(artifact.artifact_digest, r"^[0-9a-f]{64}$")
        self.assertEqual(
            artifact.source_bytes,
            len(artifact.source.encode("utf-8")),
        )
        evidence = artifact.to_evidence_dict()
        self.assertNotIn("source", evidence)
        self.assertEqual(evidence["lower_digest"], out.lowered.lower_digest)
        self.assertEqual(
            evidence["target_profile_digest"],
            out.lowered.target_profile.profile_digest,
        )

        with self.assertRaisesRegex(ValueError, "source_sha256"):
            dataclasses.replace(artifact, source=artifact.source + "\n// forged")
        with self.assertRaisesRegex(ValueError, "artifact_digest"):
            dataclasses.replace(
                artifact,
                artifact_digest="0" * 64,
            )
        with self.assertRaisesRegex(ValueError, "legacy csharp"):
            CompileOutput(
                ok=True,
                csharp=artifact.source + "\n// substituted",
                planned=out.planned,
                grounded=out.grounded,
                lowered=out.lowered,
                emitted=artifact,
            )


if __name__ == "__main__":
    unittest.main()
