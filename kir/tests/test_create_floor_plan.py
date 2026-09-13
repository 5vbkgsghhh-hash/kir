"""`create_floor_plan` — a floor plan for a level.

WHY THE OP EXISTS. `create_level` does not create a plan, and
`NewRoomBoundaryLines` does not work without a view: a live run of the K3
building on 23.08.2026 stalled on 917 room-separation lines, each one
dropping its own 250-operation program.

🔴 THE MAIN GUARD HERE IS NOT "THE OP ASSEMBLES," BUT "THE SEPARATION LINE
WILL FIND THIS VIEW." An op that creates a plan but does not pass the
`room_emit._view_pick_cs` filter would be correct and useless, and no form
test would ever notice.
"""
import unittest

from kir import authoring, ground as ground_mod
from kir.compiler import _parse_and_check
from kir.spec import OPS
from kir.tests.fixtures import GROUND_SNAPSHOT


def _emit(ops, ver="2024"):
    grounded = ground_mod.ground(
        _parse_and_check({"ir_version": "1.0", "ops": ops}), GROUND_SNAPSHOT)
    return authoring.emit_program(grounded, ver)


_LEVEL_AND_PLAN = [
    {"op": "create_level", "id": "LV", "elev_mm": 3300.0, "name": "KIR_L1"},
    {"op": "create_floor_plan", "id": "FP",
     "level": {"by": "ref", "value": "LV"}, "name": "KIR_План"},
]
_WITH_SEPARATOR = _LEVEL_AND_PLAN + [
    {"op": "create_room_separator", "id": "RS",
     "level": {"by": "ref", "value": "LV"},
     "path": [[0.0, 0.0], [3000.0, 0.0]]},
]


class Registry(unittest.TestCase):
    def test_op_is_registered_with_a_level_and_an_optional_name(self):
        op = OPS["create_floor_plan"]
        kinds = {p.name: (p.kind, p.required) for p in op.params}
        self.assertEqual(kinds, {"level": ("sel", True), "name": ("str", False)})

    def test_level_is_grounded_into_the_levels_pool(self):
        """An empty `grounded` would give a KeyError on `__grounded__` in
        the emitter: the parameter is declared, but nobody asked for it to
        be resolved."""
        self.assertIn(("level", "levels", True), OPS["create_floor_plan"].grounded)

    def test_the_result_is_referenceable(self):
        """The view is a legitimate `in_view` target for annotations; being
        unable to reference it would turn the op into a dead end."""
        self.assertTrue(OPS["create_floor_plan"].result.referenceable)

    def test_no_new_param_kind_was_introduced(self):
        """On 23.08 a new kind (`wall_layers`) without a branch in
        `schema_gen` removed the `revit_ir` tool from the toolset for 45
        minutes — silently. This op gets by with existing kinds, and the
        schema must assemble."""
        from kir.schema_transport import program_schema_for_tool
        self.assertGreater(len(str(program_schema_for_tool())), 1000)


class SeparatorWillFindIt(unittest.TestCase):
    """What the op was written for."""

    def test_plan_is_created_and_regenerated_before_the_separator_looks(self):
        cs = _emit(_WITH_SEPARATOR)
        create = cs.find("ViewPlan.Create(")
        regen = cs.find("doc.Regenerate();", create)
        pick = cs.find("foreach (ViewPlan __vp_RS")
        self.assertGreater(create, 0, "плана не создаётся вовсе")
        self.assertLess(create, regen, "нет регенерации после создания")
        self.assertLess(regen, pick,
                        "разделитель ищет вид ДО того, как план материализован")

    def test_the_created_plan_matches_the_pickers_triple(self):
        """The `room_emit` filter: ViewPlan · not a template ·
        ViewType.FloorPlan · GenLevel == the level. The witness must ask the
        SAME triple."""
        cs = _emit(_LEVEL_AND_PLAN)
        for fragment in ("ViewType.FloorPlan", "IsTemplate", "GenLevel",
                         "ElementTypeGroup.ViewTypeFloorPlan"):
            self.assertIn(fragment, cs, fragment)


class Emission(unittest.TestCase):
    def test_existing_plan_is_looked_up_before_creating_a_second(self):
        cs = _emit(_LEVEL_AND_PLAN)
        lookup = cs.find("foreach (ViewPlan __c_FP")
        create = cs.find("ViewPlan.Create(")
        self.assertGreater(lookup, 0)
        self.assertLess(lookup, create, "создаём, не посмотрев, что план уже есть")

    def test_witness_rereads_the_model_not_the_call_echo(self):
        """On 23.08 exactly this caught a `load_family` defect: the witness
        was green when families arrived under someone else's names."""
        cs = _emit(_LEVEL_AND_PLAN)
        self.assertIn("doc.GetElement(__vp_FP.Id) as ViewPlan", cs)

    def test_receipt_separates_found_from_built(self):
        self.assertIn("already_present", _emit(_LEVEL_AND_PLAN))

    def test_default_view_type_comes_from_the_document_not_from_us(self):
        cs = _emit(_LEVEL_AND_PLAN)
        self.assertIn("GetDefaultElementTypeId", cs)
        self.assertIn("ElementTypeGroup.ViewTypeFloorPlan", cs)

    def test_missing_default_view_type_is_a_typed_refusal(self):
        self.assertIn("нет типа вида", _emit(_LEVEL_AND_PLAN))

    def test_element_id_is_compared_as_a_string(self):
        """ElementId has no safe idiom across six versions (measured 03.08)."""
        cs = _emit(_LEVEL_AND_PLAN)
        self.assertIn("ElementId.InvalidElementId.ToString()", cs)


class Contracts(unittest.TestCase):
    def test_contract_kernel_is_clean(self):
        from kir.op_contract import audit_contract_kernel
        self.assertEqual(
            [x for x in audit_contract_kernel() if "create_floor_plan" in x],
            [])

    def test_reverse_contract_names_the_capture_gap(self):
        from kir.reverse_contract import REVERSE_CONTRACTS
        rc = REVERSE_CONTRACTS["create_floor_plan"]
        self.assertEqual(rc.mode.value, "capture_gap")
        self.assertTrue(rc.due, "пробел захвата без срока — это «когда-нибудь»")


if __name__ == "__main__":
    unittest.main()
