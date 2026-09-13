"""SHAPE ALIASING BY TYPE — laws that must not be broken.

Each test pins down one decision from `geom_alias`'s header, and every
law has a FAIL CONTROL: if the rule disappeared, the test must turn
red. A check that stays green with the rule removed measures nothing
but its own goodwill.
"""
from __future__ import annotations

import unittest

from kir.decompile import geom_alias as GA


def _el(eid, tid, dims=(1000.0, 2000.0, 3000.0), origin=(0.0, 0.0, 0.0)):
    if dims is None:
        return {"element_id": eid, "type_id": tid}
    return {
        "element_id": eid,
        "type_id": tid,
        "bbox_min_mm": list(origin),
        "bbox_max_mm": [origin[i] + dims[i] for i in range(3)],
    }


class TheAliasSavesCallsOnlyWhenTheShapeAgrees(unittest.TestCase):

    def test_identical_instances_of_one_type_ask_once(self):
        plan = GA.plan_geometry_asks([_el("1", "T"), _el("2", "T"),
                                      _el("3", "T")])
        self.assertEqual(plan.ask, ("1",))
        self.assertEqual(plan.alias, {"2": "1", "3": "1"})
        self.assertEqual(plan.saved_calls(), 2)
        self.assertEqual(plan.reason["1"], "representative")

    def test_a_divergent_instance_is_asked_and_NAMED(self):
        """FAIL CONTROL for the previous test. Furniture of the same
        type but longer: the instance bends the shape, and aliasing
        would be a silent lie."""
        plan = GA.plan_geometry_asks([
            _el("1", "T", dims=(100.0, 100.0, 3000.0)),
            _el("2", "T", dims=(100.0, 100.0, 3000.0)),
            _el("3", "T", dims=(100.0, 100.0, 4500.0)),   # tailored on-site
        ])
        self.assertEqual(sorted(plan.ask), ["1", "3"])
        self.assertEqual(plan.alias, {"2": "1"})
        self.assertEqual(plan.reason["3"], "instance_driven")
        self.assertEqual(plan.stats["instance_driven"], 1)

    def test_the_tolerance_is_the_one_declared_and_it_decides(self):
        near = [_el("1", "T", dims=(1000.0, 2000.0, 3000.0)),
                _el("2", "T", dims=(1000.0, 2000.0, 3001.5))]
        self.assertEqual(GA.plan_geometry_asks(near).alias, {"2": "1"})
        # the same input at half the tolerance must break the alias
        strict = GA.plan_geometry_asks(near, tolerance_mm=1.0)
        self.assertEqual(strict.alias, {})
        self.assertEqual(strict.reason["2"], "instance_driven")


class NothingIsAliasedOnFaith(unittest.TestCase):

    def test_a_type_with_one_instance_is_asked_not_aliased(self):
        """THE DEGENERATE CASE IS NAMED. A type with a single instance
        is consistent by construction — there is nothing to compare
        against, and counting it toward the savings would mean
        measuring the absence of competition."""
        plan = GA.plan_geometry_asks([_el("1", "T"), _el("2", "U")])
        self.assertEqual(sorted(plan.ask), ["1", "2"])
        self.assertEqual(plan.alias, {})
        self.assertEqual(plan.reason["1"], "singleton")

    def test_no_type_means_ask(self):
        plan = GA.plan_geometry_asks([{"element_id": "1"},
                                      {"element_id": "2"}])
        self.assertEqual(sorted(plan.ask), ["1", "2"])
        self.assertEqual(plan.reason["1"], "type_unknown")

    def test_no_bbox_means_ask_even_within_a_known_type(self):
        plan = GA.plan_geometry_asks([_el("1", "T"), _el("2", "T", dims=None)])
        self.assertEqual(sorted(plan.ask), ["1", "2"])
        self.assertEqual(plan.reason["2"], "bbox_unknown")

    def test_a_representative_without_a_bbox_aliases_nobody(self):
        """A sample with nothing to check it against does not make its body shared."""
        plan = GA.plan_geometry_asks([_el("1", "T", dims=None),
                                      _el("2", "T"), _el("3", "T")])
        self.assertEqual(sorted(plan.ask), ["1", "2", "3"])
        self.assertEqual(plan.alias, {})


class EveryElementIsAccountedFor(unittest.TestCase):

    def test_ask_and_alias_partition_the_input(self):
        els = ([_el(str(i), "A") for i in range(1, 6)]
               + [_el(str(i), "B", dims=(9.0, 9.0, float(i))) for i in range(6, 11)]
               + [{"element_id": "11"}])
        plan = GA.plan_geometry_asks(els)
        self.assertEqual(len(plan.ask) + len(plan.alias), len(els))
        self.assertEqual(set(plan.reason), set(plan.ask))
        for why in plan.reason.values():
            self.assertIn(why, GA.ASK_REASONS)

    def test_the_share_is_named_a_lower_bound_in_the_field_itself(self):
        """The field's name carries the boundary. The number "28%," if
        named merely a share, would be read as an estimate, while the
        bounding box declares identical shapes rotated by a non-right
        angle to be different."""
        plan = GA.plan_geometry_asks([_el("1", "T"), _el("2", "T")])
        self.assertIn("alias_share_lower_bound", plan.stats)
        self.assertEqual(plan.stats["alias_share_lower_bound"], 50.0)


class TheRepresentativeIsDeterministic(unittest.TestCase):

    def test_input_order_does_not_move_the_representative(self):
        """A non-deterministic choice would give one building different
        `geo_hash` values from run to run, and a diff of two decompiles
        would show edits where nothing had changed."""
        a = GA.plan_geometry_asks([_el("7", "T"), _el("3", "T"), _el("11", "T")])
        b = GA.plan_geometry_asks([_el("11", "T"), _el("7", "T"), _el("3", "T")])
        self.assertEqual(a.ask, b.ask)
        self.assertEqual(a.alias, b.alias)
        self.assertEqual(a.ask, ("3",))

    def test_numeric_ids_sort_by_number_not_by_string(self):
        """A string sort would give "10" < "9" and would make the
        sample depend on the number of digits in the id."""
        plan = GA.plan_geometry_asks([_el("10", "T"), _el("9", "T")])
        self.assertEqual(plan.ask, ("9",))


class ThePositionIsNEVERInherited(unittest.TestCase):
    """The module's main lock. The shape is shared, the position is not."""

    def _plan(self):
        return GA.plan_geometry_asks([_el("1", "T"), _el("2", "T")])

    def test_the_alias_row_carries_the_hash_and_drops_the_transform(self):
        """Capture rows carry `element_id` — the name was asked of a live run.

        The first edition read `source_element_id` (that's what the
        field is called in the PIPELINE's index) and on a live model
        gave ZERO shapes with ZERO failures.
        """
        rows = [{"element_id": "1", "geo_hash": "a" * 64,
                 "transform": (1.0, 0.0, 0.0, 0.0)}]
        out = GA.attach_aliased_geometry(rows, self._plan())
        self.assertEqual(len(out), 2)
        alias_row = [r for r in out if r["element_id"] == "2"][0]
        self.assertEqual(alias_row["geo_hash"], "a" * 64)
        self.assertIsNone(alias_row["transform"])
        self.assertEqual(alias_row["alias_of"], "1")

    def test_the_pipeline_field_name_is_accepted_too(self):
        """THE OTHER-SIDE CONTROL. The pipeline's index really does
        call the field `source_element_id`; silently failing to find
        its row is the same defect turned inside out."""
        rows = [{"source_element_id": "1", "geo_hash": "b" * 64,
                 "transform": None}]
        out = GA.attach_aliased_geometry(rows, self._plan())
        self.assertEqual(len(out), 2)
        self.assertEqual([r for r in out if r.get("source_element_id") == "2"][0]
                         ["alias_of"], "1")

    def test_an_unextracted_representative_gives_nobody_a_shape(self):
        """Capture could fail for its own reasons. In that case the
        alias is NOT issued: a row without a source would silently
        hand out a foreign shape."""
        out = GA.attach_aliased_geometry([], self._plan())
        self.assertEqual(out, [])


if __name__ == "__main__":
    unittest.main()


class TheTypeLibraryCountsMeshApartFromBox(unittest.TestCase):
    """`Gb` is the same bounding box, obtained at a higher cost. Lumping
    it together with a mesh under one "shapes" column would mean
    declaring a win out of exactly what the owner complained about.
    Live run 08-15 gave `Gm 16 / Gb 14 / A 1`, and the difference
    between "30 types with a shape" and "16 types with a mesh" is the
    whole point of this channel."""

    def _els(self):
        return [_el("1", "T"), _el("2", "T"), _el("3", "U"), _el("4", "U")]

    def test_a_box_tier_is_a_shape_but_NOT_a_mesh(self):
        plan = GA.plan_geometry_asks(self._els())
        rows = [{"element_id": "1", "geo_hash": "a" * 64, "tier": "Gm"},
                {"element_id": "3", "geo_hash": "b" * 64, "tier": "Gb"}]
        lib = GA.build_type_shape_library(self._els(), rows, plan)
        self.assertEqual(lib["types_with_shape"], 2)
        self.assertEqual(lib["types_with_mesh"], 1)
        self.assertEqual(lib["instances_covered"], 4)
        self.assertEqual(lib["instances_covered_by_mesh"], 2)
        self.assertEqual(lib["tiers"], {"Gm": 1, "Gb": 1})

    def test_only_representatives_enter_the_library(self):
        """A CONTROL. A capture row that is NOT the representative has
        no right to become the type's shape: it is the shape of one
        instance, passed off as the shape of all."""
        plan = GA.plan_geometry_asks(self._els())
        rows = [{"element_id": "2", "geo_hash": "c" * 64, "tier": "Gm"}]
        lib = GA.build_type_shape_library(self._els(), rows, plan)
        self.assertEqual(lib["types_with_shape"], 0)
        self.assertEqual(lib["instances_covered"], 0)

    def test_the_gate_is_off_by_default(self):
        self.assertFalse(GA.type_shapes_enabled())
