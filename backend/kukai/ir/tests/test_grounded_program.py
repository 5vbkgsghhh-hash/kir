"""Refuting tests for immutable, parent-bound grounding evidence."""
from __future__ import annotations

import copy
import dataclasses
import json
import unittest
from unittest import mock

from kukai.ir.compiler import compile_program, plan_program
from kukai.ir.ground import ground, ground_program
from kukai.ir.midend import (
    GroundedOp,
    GroundedProgram,
    PlanEncodingError,
)
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT


WALL_PROGRAM = {
    "ir_version": "1.0",
    "intent": "стена на первом этаже",
    "ops": [{
        "op": "create_wall",
        "id": "W1",
        "p0_mm": [0, 0],
        "p1_mm": [5000, 0],
        "level": {"by": "name", "value": "Этаж 1"},
    }],
}

STAIRS_PROGRAM = {
    "ir_version": "1.0",
    "intent": "размножить лестницу на два уровня",
    "ops": [{
        "op": "create_multistory_stairs",
        "id": "MS1",
        "stairs": {"by": "element_id", "value": 8145901},
        "levels": [
            {"by": "name", "value": "Этаж 1"},
            {"by": "element_id", "value": 43},
        ],
    }],
}


def _wire_bytes(payload: dict) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _marker_paths(value, path: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        if "__grounded__" in value:
            found.append(path or "<root>")
        for key in sorted(value):
            child_path = f"{path}.{key}" if path else key
            found.extend(_marker_paths(value[key], child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_marker_paths(child, f"{path}[{index}]"))
    return found


class GroundedProgramContractTests(unittest.TestCase):
    def test_write_compile_exposes_immutable_parent_bound_digest(self) -> None:
        out = compile_program(copy.deepcopy(WALL_PROGRAM),
                              snapshot=GROUND_SNAPSHOT)

        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        self.assertIsNotNone(out.grounded)
        assert out.grounded is not None
        self.assertIs(out.grounded.planned, out.planned)
        self.assertRegex(out.grounded.ground_digest, r"^[0-9a-f]{64}$")
        self.assertEqual(out.as_dict()["ground_digest"],
                         out.grounded.ground_digest)

        digest = out.grounded.ground_digest
        detached = out.grounded.to_ops()
        detached[0]["level"]["__grounded__"]["id"] = 999999
        out.grounded_ops[0]["level"]["__grounded__"]["id"] = 888888
        detached_report = out.grounded.resolution_report()
        detached_report[0]["detail"]["id"] = 777777

        self.assertEqual(out.grounded.ground_digest, digest)
        self.assertEqual(
            out.grounded.to_ops()[0]["level"]["__grounded__"]["id"],
            42,
        )
        self.assertEqual(
            out.grounded.resolution_report()[0]["detail"]["id"],
            42,
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            out.grounded.ground_digest = "0" * 64  # type: ignore[misc]

    def test_every_nested_stairs_resolution_is_accounted_exactly(self) -> None:
        out = compile_program(copy.deepcopy(STAIRS_PROGRAM),
                              snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        assert out.grounded is not None

        marker_paths = [
            path
            for op in out.grounded.to_ops()
            for path in _marker_paths(op)
        ]
        report_paths = [
            row["field_name"] for row in out.grounded.resolution_report()
        ]
        self.assertEqual(marker_paths, ["levels[0]", "levels[1]"])
        self.assertEqual(report_paths, marker_paths)

        with self.assertRaisesRegex(ValueError, "cover every"):
            GroundedProgram(
                planned=out.grounded.planned,
                ops=out.grounded.ops,
                resolutions=out.grounded.resolutions[:-1],
            )
        with self.assertRaisesRegex(ValueError, "cover every"):
            GroundedProgram(
                planned=out.grounded.planned,
                ops=out.grounded.ops,
                resolutions=out.grounded.resolutions
                + (out.grounded.resolutions[0],),
            )
        with self.assertRaisesRegex(ValueError, "cover every"):
            GroundedProgram(
                planned=out.grounded.planned,
                ops=out.grounded.ops,
                resolutions=tuple(reversed(out.grounded.resolutions)),
            )

    def test_resolved_id_name_and_rule_each_change_ground_digest(self) -> None:
        out = compile_program(copy.deepcopy(WALL_PROGRAM),
                              snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        assert out.grounded is not None and out.planned is not None
        original = out.grounded.ground_digest

        for field_name, replacement in (
            ("id", 424242),
            ("name", "Другой уровень"),
            ("via", "element_id"),
        ):
            with self.subTest(field_name=field_name):
                changed = out.grounded.to_ops()
                changed[0]["level"]["__grounded__"][field_name] = replacement
                rebuilt = GroundedProgram.from_ops(out.planned, changed)
                self.assertNotEqual(rebuilt.ground_digest, original)

    def test_non_resolution_output_drift_cannot_keep_the_same_digest(self) -> None:
        """The type freezes trusted-grounder output; it is not its validator."""
        out = compile_program(copy.deepcopy(WALL_PROGRAM),
                              snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        assert out.grounded is not None and out.planned is not None

        changed = out.grounded.to_ops()
        changed[0]["p1_mm"] = [6000, 0]
        rebound = GroundedProgram.from_ops(out.planned, changed)

        # The constructor deliberately accepts a same-shape output from the
        # trusted grounder, but the output cannot masquerade under the old id.
        self.assertNotEqual(rebound.ground_digest,
                            out.grounded.ground_digest)

    def test_ground_digest_does_not_claim_snapshot_identity_or_revision(self) -> None:
        planned = plan_program(copy.deepcopy(WALL_PROGRAM))
        first_snapshot = copy.deepcopy(GROUND_SNAPSHOT)
        second_snapshot = copy.deepcopy(GROUND_SNAPSHOT)
        second_snapshot["__document_fingerprint"] = {
            "title": "Other Model",
            "path_name": r"C:\models\other.rvt",
            "project_uid": "other-project-uid",
        }

        first = ground_program(planned, first_snapshot)
        second = ground_program(planned, second_snapshot)

        # Resolved output is identical, therefore the digest is identical.
        # This is a named residual boundary, not snapshot attestation.
        self.assertEqual(first.ground_digest, second.ground_digest)
        evidence = first.to_evidence_dict()
        self.assertNotIn("snapshot_digest", evidence)
        self.assertNotIn("document_fingerprint", evidence)

    def test_removed_reordered_and_extra_ops_cannot_rebind_parent(self) -> None:
        program = copy.deepcopy(WALL_PROGRAM)
        program["ops"].append({
            "op": "create_wall",
            "id": "W2",
            "p0_mm": [0, 1000],
            "p1_mm": [5000, 1000],
            "level": {"by": "name", "value": "Этаж 1"},
        })
        planned = plan_program(program)
        grounded = ground_program(planned, GROUND_SNAPSHOT)
        ops = grounded.to_ops()

        variants = {
            "removed": ops[:-1],
            "reordered": list(reversed(ops)),
            "extra": ops + [{**copy.deepcopy(ops[-1]), "id": "EXTRA"}],
        }
        for name, candidate in variants.items():
            with self.subTest(name=name), self.assertRaisesRegex(
                    ValueError, "preserve parent order and identity"):
                GroundedProgram.from_ops(planned, candidate)

    def test_typed_adapter_preserves_legacy_ground_bytes(self) -> None:
        planned = plan_program(copy.deepcopy(STAIRS_PROGRAM))
        legacy_input = planned.to_ops()
        original_input = copy.deepcopy(legacy_input)

        legacy = ground(legacy_input, GROUND_SNAPSHOT)
        typed = ground_program(planned, GROUND_SNAPSHOT)

        self.assertIsInstance(legacy, list)
        self.assertEqual(legacy_input, original_input)
        self.assertEqual(_wire_bytes(legacy), _wire_bytes(typed.to_ops()))

    def test_query_and_refusal_wire_dicts_do_not_gain_ground_fields(self) -> None:
        query = compile_program({
            "ir_version": "1.0",
            "ops": [{"op": "query_count", "id": "Q1", "kind": "wall"}],
        })
        self.assertTrue(query.ok, [d.as_dict() for d in query.diagnostics])
        assert query.planned is not None
        expected_query = {
            "ok": True,
            "csharp": query.csharp,
            "diagnostics": [],
            "plan_digest": query.planned.plan_digest,
        }
        self.assertEqual(_wire_bytes(query.as_dict()),
                         _wire_bytes(expected_query))

        refusal = compile_program({"ir_version": "1.0", "ops": []})
        expected_refusal = {
            "ok": False,
            "csharp": None,
            "diagnostics": [{
                "code": "KIR-P001",
                "message_ru": "ops — непустой список",
                "field_name": "ops",
            }],
        }
        self.assertEqual(_wire_bytes(refusal.as_dict()),
                         _wire_bytes(expected_refusal))
        self.assertNotIn("ground_digest", query.as_dict())
        self.assertNotIn("ground_digest", refusal.as_dict())

    def test_canonical_grounding_rejects_nan_and_lone_surrogates(self) -> None:
        for label, value in (
            ("nan", float("nan")),
            ("lone_surrogate", "\ud800"),
        ):
            with self.subTest(label=label), self.assertRaises(PlanEncodingError):
                GroundedOp.from_dict({
                    "op": "create_wall",
                    "id": "W1",
                    "probe": value,
                })

        planned = plan_program(copy.deepcopy(WALL_PROGRAM))
        invalid_ground = planned.to_ops()
        invalid_ground[0]["__test_non_finite__"] = float("nan")
        with mock.patch("kukai.ir.ground.ground",
                        return_value=invalid_ground):
            out = compile_program(planned, snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertEqual([d.code for d in out.diagnostics], ["KIR-P000"])

    def test_marker_without_named_resolution_rule_is_rejected(self) -> None:
        planned = plan_program(copy.deepcopy(WALL_PROGRAM))
        grounded = ground(planned.to_ops(), GROUND_SNAPSHOT)
        del grounded[0]["level"]["__grounded__"]["via"]
        with self.assertRaisesRegex(ValueError, "named rule"):
            GroundedProgram.from_ops(planned, grounded)


if __name__ == "__main__":
    unittest.main()
