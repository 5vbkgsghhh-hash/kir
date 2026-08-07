"""Contract tests for the process-wide KIR registry snapshot."""
from __future__ import annotations

import unittest

from kukai.ir import spec
from kukai.ir.ops_arch import RAILING_PLACEMENT_MEMBERS
from kukai.ir.ops_authoring import WALL_LOCATION_LINE_ORDINALS
from kukai.ir.ops_opening import CUT_PERPENDICULAR_FACE
from kukai.ir.ops_shape import DIRECTSHAPE_CATEGORIES
from kukai.ir.registry_base import (
    EffectKind,
    OpSpec,
    ParamSpec,
    RESULT_ELEMENT,
    freeze_registry_mapping,
)


class RegistryImmutabilityTests(unittest.TestCase):
    def test_public_registry_and_nested_tolerances_refuse_mutation(self) -> None:
        with self.assertRaises(TypeError):
            spec.OPS["invented"] = spec.OPS["create_wall"]  # type: ignore[index]
        with self.assertRaises(TypeError):
            spec.OPS["create_opening"].tolerances["bbox_mm"] = 0.0  # type: ignore[index]

    def test_list_default_is_frozen_without_changing_wire_shape(self) -> None:
        fields = next(
            param.default
            for param in spec.OPS["query_list"].params
            if param.name == "fields"
        )
        self.assertEqual(fields, spec.LIST_FIELDS)
        self.assertIsInstance(fields, tuple)
        with self.assertRaises(AttributeError):
            fields.append("invented")  # type: ignore[attr-defined]

    def test_shared_registry_tables_are_deeply_immutable(self) -> None:
        protected = (
            spec.ROUTE_ONLY_ACTIONS,
            spec.DEFAULTS,
            spec.KINDS,
            spec.FILTERS,
            WALL_LOCATION_LINE_ORDINALS,
            RAILING_PLACEMENT_MEMBERS,
            CUT_PERPENDICULAR_FACE,
            DIRECTSHAPE_CATEGORIES,
        )
        for mapping in protected:
            with self.subTest(mapping=next(iter(mapping), "empty")):
                with self.assertRaises(TypeError):
                    mapping["invented"] = "unsafe"  # type: ignore[index]
        with self.assertRaises(TypeError):
            spec.DEFAULTS["wall"]["height_mm"] = 1.0  # type: ignore[index]
        with self.assertRaises(TypeError):
            spec.FILTERS["structural"]["type"] = str  # type: ignore[index]

    def test_registry_mapping_freeze_is_recursive_and_defensive(self) -> None:
        source = {"outer": {"items": [1, 2]}}
        frozen = freeze_registry_mapping(source)
        source["outer"]["items"].append(3)
        self.assertEqual(frozen["outer"]["items"], (1, 2))
        with self.assertRaises(TypeError):
            frozen["outer"]["new"] = True  # type: ignore[index]

    def test_constructors_make_defensive_copies(self) -> None:
        default_source = ["id", ["name"]]
        choices_source = ["a", "b"]
        param = ParamSpec(
            "fields",
            "fields",
            default=default_source,
            choices=choices_source,
        )
        default_source.append("category")
        choices_source.append("c")
        self.assertEqual(param.default, ("id", ("name",)))
        self.assertEqual(param.choices, ("a", "b"))

        params = [param]
        capability = [["create", "element"]]
        grounded = [["level", "levels", True]]
        tolerances = {"bbox_mm": 1.0}
        op = OpSpec(
            name="immutable_probe",
            family="authoring",
            params=params,  # type: ignore[arg-type]
            capability=capability,  # type: ignore[arg-type]
            post="probe",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            writes_model=True,
            grounded=grounded,  # type: ignore[arg-type]
            tolerances=tolerances,
        )
        params.append(ParamSpec("extra", "str"))
        capability[0][0] = "mutate"
        grounded[0][0] = "type"
        tolerances["bbox_mm"] = 999.0

        self.assertEqual(op.params, (param,))
        self.assertEqual(op.capability, (("create", "element"),))
        self.assertEqual(op.grounded, (("level", "levels", True),))
        self.assertEqual(op.tolerances["bbox_mm"], 1.0)

    def test_mapping_default_requires_an_explicit_immutable_model(self) -> None:
        with self.assertRaises(TypeError):
            ParamSpec("unsafe", "value", default={"nested": []})


if __name__ == "__main__":
    unittest.main()
