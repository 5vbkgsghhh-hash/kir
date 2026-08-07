"""Typed result/effect registry and forward-reference regressions."""
from __future__ import annotations

import os
import tempfile
import unittest

os.environ.setdefault(
    "KIR_REJECTIONS_PATH",
    os.path.join(tempfile.gettempdir(), "kir_test_queue.jsonl"),
)

from kukai.ir import spec  # noqa: E402
from kukai.ir.compiler import compile_program  # noqa: E402
from kukai.ir.registry_base import (  # noqa: E402
    EffectKind,
    IdentityCardinality,
    ReferenceKind,
    ResultSpec,
)
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT  # noqa: E402


class RegistryResultSemantics(unittest.TestCase):
    def test_every_op_has_a_closed_effect_and_result_contract(self):
        # 39 -> 41: wave/room (create_room_separator) и wave/opening в один
        # вечер 03.08. Число — СТОРОЖ, а не факт: оп, добавленный молча, обязан
        # уронить эту строку и заставить автора пройти весь список контрактов
        # ниже.
        self.assertEqual(len(spec.OPS), 41)
        for name, op in spec.OPS.items():
            with self.subTest(op=name):
                self.assertIsInstance(op.effect, EffectKind)
                self.assertIsInstance(op.result, ResultSpec)
                self.assertEqual(
                    op.writes_model,
                    op.effect is not EffectKind.READ,
                )
                if op.writes_model:
                    self.assertIsNot(
                        op.result.identity_cardinality,
                        IdentityCardinality.NONE,
                    )

    def test_plural_and_special_results_are_not_reference_producers(self):
        for name in (
            "create_pipe_system",
            "route_pipe_system",
            "route_duct_system",
            "create_stairs",
            "create_group",
            "create_curtain_grid_line",
        ):
            with self.subTest(op=name):
                self.assertFalse(spec.OPS[name].result.referenceable)

    def test_reference_result_kinds_are_closed(self):
        for name, op in spec.OPS.items():
            with self.subTest(op=name):
                kind = op.result.reference_kind
                self.assertTrue(kind is None or isinstance(kind, ReferenceKind))

    def test_same_spelling_can_have_different_typed_reference_contracts(self):
        def param(op_name: str, param_name: str):
            return next(
                item for item in spec.OPS[op_name].params
                if item.name == param_name)

        self.assertEqual(
            param("create_door", "host").ref_kinds,
            (ReferenceKind.WALL,),
        )
        self.assertEqual(
            param("place_family", "host").ref_kinds,
            (ReferenceKind.ELEMENT,),
        )
        self.assertEqual(param("create_railing", "host").ref_kinds, ())
        self.assertEqual(param("create_text", "in_view").ref_kinds, ())

    def test_wire_identity_is_validated_by_declared_cardinality(self):
        single = spec.OPS["create_wall"].result
        many = spec.OPS["create_pipe_system"].result
        deleted = spec.OPS["delete"].result

        self.assertTrue(single.identity_present({"id": "42"}))
        self.assertTrue(single.identity_present({"id": 42}))
        self.assertFalse(single.identity_present({"id": ""}))
        self.assertFalse(single.identity_present({"id": True}))
        self.assertTrue(many.identity_present({"segment_ids": ["42", 43]}))
        self.assertFalse(many.identity_present({"segment_ids": []}))
        self.assertTrue(deleted.identity_present({"deleted_id": "42"}))


class TypedForwardReferences(unittest.TestCase):
    def test_place_family_is_a_referenceable_single_element_result(self):
        program = {
            "ir_version": "1.0",
            "ops": [
                {
                    "op": "place_family",
                    "id": "PF",
                    "xyz": [0, 0, 0],
                    "level": {"by": "element_id", "value": 42},
                    "symbol": {"by": "element_id", "value": 800},
                },
                {
                    "op": "set_param",
                    "id": "S",
                    "target": {"by": "ref", "value": "PF"},
                    "param": "Comments",
                    "value": "typed-result",
                },
            ],
        }

        out = compile_program(program, snapshot=GROUND_SNAPSHOT)

        self.assertTrue(out.ok, [item.as_dict() for item in out.diagnostics])
        self.assertIn("__tg_S = (Element)__el_PF", out.csharp)

    def test_load_family_is_referenceable_without_a_create_prefix(self):
        program = {
            "ir_version": "1.0",
            "ops": [
                {
                    "op": "load_family",
                    "id": "LF",
                    "path": r"C:\families\chair.rfa",
                    "type_name": "Chair",
                },
                {
                    "op": "set_param",
                    "id": "S",
                    "target": {"by": "ref", "value": "LF"},
                    "param": "Comments",
                    "value": "loaded-by-kir",
                },
            ],
        }

        out = compile_program(program, snapshot=GROUND_SNAPSHOT)

        self.assertTrue(out.ok, [item.as_dict() for item in out.diagnostics])
        self.assertIn("FamilySymbol __el_LF", out.csharp)
        self.assertIn("__tg_S = (Element)__el_LF", out.csharp)

    def test_plural_network_result_cannot_be_used_as_one_element(self):
        program = {
            "ir_version": "1.0",
            "ops": [
                {
                    "op": "create_pipe_system",
                    "id": "NET",
                    "level": {"by": "element_id", "value": 42},
                    "nodes": [
                        {"id": "a", "xyz_mm": [0, 0, 0]},
                        {"id": "b", "xyz_mm": [3000, 0, 0]},
                    ],
                    "segments": [{"from": "a", "to": "b"}],
                },
                {
                    "op": "set_param",
                    "id": "S",
                    "target": {"by": "ref", "value": "NET"},
                    "param": "Comments",
                    "value": "invalid",
                },
            ],
        }

        out = compile_program(program, snapshot=GROUND_SNAPSHOT)

        self.assertFalse(out.ok)
        diagnostic = next(item for item in out.diagnostics
                          if item.code == "KIR-L003")
        self.assertEqual(diagnostic.op_id, "S")
        self.assertEqual(diagnostic.got, "NET")

    def test_wall_only_host_rejects_a_generic_element_result(self):
        program = {
            "ir_version": "1.0",
            "ops": [
                {
                    "op": "place_family",
                    "id": "PF",
                    "xyz": [0, 0, 0],
                    "level": {"by": "element_id", "value": 42},
                    "symbol": {"by": "element_id", "value": 800},
                },
                {
                    "op": "create_door",
                    "id": "D",
                    "host": {"by": "ref", "value": "PF"},
                    "offset_mm": 1000,
                    "symbol": {"by": "element_id", "value": 700},
                },
            ],
        }

        out = compile_program(program, snapshot=GROUND_SNAPSHOT)

        self.assertFalse(out.ok)
        diagnostic = next(item for item in out.diagnostics
                          if item.code == "KIR-L004")
        self.assertEqual(diagnostic.expected, ["wall"])
        self.assertEqual(diagnostic.got, "element")

    def test_generic_element_consumer_accepts_a_level_subtype(self):
        program = {
            "ir_version": "1.0",
            "ops": [
                {"op": "create_level", "id": "L", "elev_mm": 9000,
                 "name": "KIR typed level"},
                {"op": "set_param", "id": "S",
                 "target": {"by": "ref", "value": "L"},
                 "param": "Comments", "value": "typed-supertype"},
            ],
        }

        out = compile_program(program, snapshot=GROUND_SNAPSHOT)

        self.assertTrue(out.ok, [item.as_dict() for item in out.diagnostics])
        self.assertIn("__tg_S = (Element)__el_L", out.csharp)

    def test_nonreferenceable_view_parameter_rejects_ref_before_emit(self):
        program = {
            "ir_version": "1.0",
            "ops": [
                {"op": "create_wall", "id": "W", "p0_mm": [0, 0],
                 "p1_mm": [6000, 0],
                 "level": {"by": "element_id", "value": 42}},
                {"op": "create_text", "id": "T",
                 "in_view": {"by": "ref", "value": "W"},
                 "at": [10, 20], "content": "must refuse"},
            ],
        }

        out = compile_program(program, snapshot=GROUND_SNAPSHOT)

        self.assertFalse(out.ok)
        diagnostic = next(item for item in out.diagnostics
                          if item.field_name == "in_view")
        self.assertEqual(diagnostic.code, "KIR-T001")


if __name__ == "__main__":
    unittest.main()
