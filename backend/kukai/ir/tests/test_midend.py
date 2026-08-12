"""Contracts for the immutable parse/typecheck/plan boundary."""
from __future__ import annotations

import dataclasses
import unittest
from unittest import mock

from kukai.ir.acceptance import derive_expectation
from kukai.ir.compiler import compile_program, plan_program
from kukai.ir.diag import KirRefusal
from kukai.ir.midend import FieldOrigin, ProgramFamily


class TestTypedPlan(unittest.TestCase):
    def test_required_catalog_selector_is_a_plan_invariant(self) -> None:
        with self.assertRaises(KirRefusal) as caught:
            plan_program({
                "ir_version": "1.0",
                "ops": [{
                    "op": "create_wall", "id": "w",
                    "p0_mm": [0, 0], "p1_mm": [5000, 0],
                }],
            })

        diagnostics = caught.exception.diagnostics
        self.assertTrue(any(
            diag.code == "KIR-P005" and diag.field_name == "level"
            for diag in diagnostics
        ), [diag.as_dict() for diag in diagnostics])

    def test_envelope_default_satisfies_required_selector_before_plan(self) -> None:
        selector = {"by": "name", "value": "L1"}
        plan = plan_program({
            "ir_version": "1.0",
            "defaults": {"level": selector},
            "ops": [{
                "op": "create_wall", "id": "w",
                "p0_mm": [0, 0], "p1_mm": [5000, 0],
            }],
        })

        self.assertEqual(plan.to_ops()[0]["level"], selector)
        self.assertEqual(
            plan.ops[0].provenance.origin_for("level"),
            FieldOrigin.ENVELOPE_DEFAULT,
        )

    def test_query_defaults_have_explicit_provenance(self) -> None:
        plan = plan_program({
            "ir_version": "1.0",
            "ops": [{"op": "query_list", "kind": "wall"}],
        })

        self.assertEqual(plan.family, ProgramFamily.QUERY)
        self.assertEqual(plan.source_op_count, 1)
        op = plan.ops[0]
        self.assertEqual(op.op_id, "q0")
        self.assertEqual(op.provenance.origin_for("op"), FieldOrigin.EXPLICIT)
        self.assertEqual(op.provenance.origin_for("kind"), FieldOrigin.EXPLICIT)
        self.assertEqual(op.provenance.origin_for("id"),
                         FieldOrigin.COMPILER_DERIVED)
        self.assertEqual(op.provenance.origin_for("where"),
                         FieldOrigin.COMPILER_DERIVED)
        self.assertEqual(op.provenance.origin_for("fields"),
                         FieldOrigin.REGISTRY_DEFAULT)
        self.assertEqual(op.provenance.origin_for("limit"),
                         FieldOrigin.REGISTRY_DEFAULT)

    def test_macro_and_envelope_defaults_keep_distinct_origins(self) -> None:
        plan = plan_program({
            "ir_version": "1.0",
            "defaults": {"type": {"by": "name", "value": "Generic"}},
            "ops": [{
                "op": "stack", "id": "s", "levels": 1,
                "floor": [{"op": "create_wall", "id": "w",
                           "p0_mm": [0, 0], "p1_mm": [5000, 0]}],
            }],
        })

        wall = next(op for op in plan.ops if op.op_name == "create_wall")
        self.assertEqual(wall.provenance.source_index, 0)
        self.assertEqual(wall.provenance.source_id, "s")
        self.assertEqual(wall.provenance.macro_name, "stack")
        self.assertEqual(wall.provenance.origin_for("p0_mm"),
                         FieldOrigin.MACRO_DERIVED)
        self.assertEqual(wall.provenance.origin_for("level"),
                         FieldOrigin.MACRO_DERIVED)
        self.assertEqual(wall.provenance.origin_for("type"),
                         FieldOrigin.ENVELOPE_DEFAULT)
        self.assertEqual(wall.provenance.origin_for("height_mm"),
                         FieldOrigin.REGISTRY_DEFAULT)

    def test_detached_dicts_cannot_mutate_the_hashed_plan(self) -> None:
        plan = plan_program({
            "ir_version": "1.0",
            "ops": [{"op": "query_count", "kind": "wall"}],
        })
        digest = plan.plan_digest
        detached = plan.to_ops()
        detached[0]["kind"] = "door"
        detached.append({"op": "query_count", "id": "forged"})

        self.assertEqual(plan.plan_digest, digest)
        self.assertEqual(plan.to_ops()[0]["kind"], "wall")
        self.assertEqual(len(plan.ops), 1)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            plan.intent = "mutated"  # type: ignore[misc]

    def test_compile_output_exposes_the_exact_plan_digest(self) -> None:
        program = {
            "ir_version": "1.0",
            "ops": [{"op": "query_count", "id": "q", "kind": "wall"}],
        }
        out = compile_program(program)
        self.assertTrue(out.ok, [diag.as_dict() for diag in out.diagnostics])
        self.assertIsNotNone(out.planned)
        self.assertEqual(out.as_dict()["plan_digest"], out.planned.plan_digest)
        self.assertEqual(out.planned.plan_digest,
                         plan_program(program).plan_digest)

    def test_compiler_lowers_an_existing_plan_without_replanning(self) -> None:
        plan = plan_program({
            "ir_version": "1.0",
            "ops": [{"op": "query_count", "id": "q", "kind": "wall"}],
        })
        with mock.patch("kukai.ir.compiler._parse_and_check_internal",
                        side_effect=AssertionError("must not parse twice")):
            out = compile_program(plan)
        self.assertTrue(out.ok, [diag.as_dict() for diag in out.diagnostics])
        self.assertIs(out.planned, plan)

    def test_acceptance_consumes_existing_plan_without_replanning(self) -> None:
        plan = plan_program({
            "ir_version": "1.0",
            "ops": [{
                "op": "create_wall", "id": "w",
                "p0_mm": [0, 0], "p1_mm": [5000, 0],
                "level": {"by": "name", "value": "L1"},
            }],
        })
        with mock.patch("kukai.ir.compiler.plan_program",
                        side_effect=AssertionError("must not re-plan")):
            expectation = derive_expectation(plan)
        self.assertTrue(expectation.checkable)
        self.assertEqual(expectation.op_count, 1)


if __name__ == "__main__":
    unittest.main()
