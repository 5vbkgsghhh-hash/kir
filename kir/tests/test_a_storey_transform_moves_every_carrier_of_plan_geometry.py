"""SHRINKING A FLOOR MUST CARRY OVER ALL OF ITS GEOMETRY, OR NAME WHAT IT
CANNOT.

Audit finding `F-139` (29.08.2026), `kir/macros._apply_transform`.

`stack.transform` was carrying over ONLY four scalar point fields
(`_XY_FIELDS = ("p0_mm", "p1_mm", "xy", "top_xy")`). Flat outlines went right
past it. Taken by execution — a `stack` of two floors with
`scale_xy_top=[0.5, 0.5]`:

    wall  s_L2_w [0, 0] [500, 0]                       <- shrank BY HALF, correct
    floor s_L2_f [[0,0],[1000,0],[1000,1000],[0,1000]] <- DID NOT SHRINK

The top floor ended up with walls along a 500 outline and a slab along a
1000 outline. THERE IS NO REFUSAL: the compiler checks the shape of EACH op
separately, and "the walls agree with the slab" is nowhere a law. A second
carrier of the same miss — outline holes: `outer` was carried over, `holes`
were not mentioned.

🔴 APPENDING `"outline"` TO THE LIST IS THE WRONG FIX, AND THIS IS THE MAIN
POINT. A list of names forever chases the registry; the next carrier of
geometry will be forgotten the same way, and the miss will become invisible
again.

🔴 BUT PULLING EVERYTHING FROM THE REGISTRY IS ALSO WRONG, AND THE PACKAGE
WAS MISTAKEN HERE TOO. Its proposed `_geometry_fields` filtered FOUR kinds
(`pt_xy pt_xyz pts pts_list`), while plan geometry is carried by NINE: on top
of these — `pts_xyz`, `path`, `path3`, `region`, `slopes`. "Does this kind
carry geometry" is a SEMANTIC property, it cannot be derived from the
registry.

SO WHAT STANDS HERE IS NOT A LIST OF NAMES BUT A DECISION PER KIND, and its
completeness is guarded BY A NUMBER: every kind from `spec.PARAM_KINDS` must
have an entry in the table. A new kind in the registry turns this set red and
forces someone to COME AND DECIDE — the same technique that closed the
sandbox's name list (`test_course.NAMES`).

A `REFUSAL` where a kind DOES carry geometry but there is nothing to carry
it with (`mesh`, `surface`, `solid_parts`, `spiral`, `plane`, `placements`,
`slopes`, a graph): inventing a mesh transform or a boolean-primitive
transform WITHOUT A WITNESS would mean silently building the wrong building
— exactly the defect this fix is against. A named refusal is strictly
better.

🔴 CAUGHT BY THE RUN WHILE FIXING: the first draft left the old
`_XY_FIELDS` pass UNCONDITIONAL, and a point got carried TWICE — a wall
shrank fourfold instead of twofold. The safety net for ops outside the
registry now works ONLY when the registry does not know about the op.
"""
from __future__ import annotations

import unittest

from kir import macros, spec
from kir.diag import KirRefusal


def _stack(floor_ops, transform=None, levels=2):
    macro = {"op": "stack", "id": "s", "levels": levels, "h_mm": 3000,
             "floor": floor_ops}
    if transform is not None:
        macro["transform"] = transform
    return macros.expand([macro])


def _top(ops, op_name):
    return [o for o in ops if o["op"] == op_name and o["id"].startswith("s_L2")][0]


class ВсяГеометрияЭтажаПереезжает(unittest.TestCase):

    HALF = {"scale_xy_top": [0.5, 0.5]}

    def test_a_contour_narrows_with_the_walls(self) -> None:
        """🔴 THE SUBJECT OF THE FINDING."""
        ops = _stack([
            {"op": "create_wall", "id": "w", "p0_mm": [0, 0], "p1_mm": [1000, 0]},
            {"op": "create_floor", "id": "f",
             "outline": [[0, 0], [1000, 0], [1000, 1000], [0, 1000]]},
        ], self.HALF)
        self.assertEqual(_top(ops, "create_wall")["p1_mm"], [500.0, 0.0])
        self.assertEqual(_top(ops, "create_floor")["outline"],
                         [[0.0, 0.0], [500.0, 0.0], [500.0, 500.0], [0.0, 500.0]])

    def test_the_holes_move_with_their_outer_ring(self) -> None:
        """A SECOND CARRIER OF THE SAME MISS: shrinking the outer ring while
        the cutout stays put yields a skewed opening."""
        ops = _stack([
            {"op": "create_floor", "id": "f",
             "outline": [[0, 0], [1000, 0], [1000, 1000], [0, 1000]],
             "holes": [[[200, 200], [300, 200], [300, 300], [200, 300]]]},
        ], self.HALF)
        self.assertEqual(_top(ops, "create_floor")["holes"],
                         [[[100.0, 100.0], [150.0, 100.0],
                           [150.0, 150.0], [100.0, 150.0]]])

    def test_a_region_moves_outer_and_every_hole_as_one_value(self) -> None:
        """`region` is a single value: carrying over just the outer silently
        corrupts the data, even when the forgotten hole still legally lies
        inside it."""
        ops = _stack([
            {"op": "create_floor_by_contour", "id": "f",
             "contour": {
                 "outer": {"shape": "poly", "points_mm": [
                     [0, 0], [2000, 0], [2000, 2000], [0, 2000]]},
                 "holes": [{"shape": "poly", "points_mm": [
                     [400, 400], [800, 400], [800, 800], [400, 800]]}]}}
        ], self.HALF)
        contour = _top(ops, "create_floor_by_contour")["contour"]
        self.assertEqual(contour["outer"]["points_mm"],
                         [[0.0, 0.0], [1000.0, 0.0],
                          [1000.0, 1000.0], [0.0, 1000.0]])
        self.assertEqual(contour["holes"][0]["points_mm"],
                         [[200.0, 200.0], [400.0, 200.0],
                          [400.0, 400.0], [200.0, 400.0]])

    def test_a_spline_via_point_moves_with_its_edge_endpoints(self) -> None:
        ops = _stack([
            {"op": "create_floor_by_contour", "id": "f",
             "contour": {
                 "outer": {"shape": "poly", "points_mm": [
                     [0, 0], [2000, 0], [2000, 2000], [0, 2000]],
                     "splines": [{"edge": 0, "via_mm": [[1000, -400]]}]},
                 "holes": []}}
        ], self.HALF)
        outer = _top(ops, "create_floor_by_contour")["contour"]["outer"]
        self.assertEqual(outer["splines"],
                         [{"edge": 0, "via_mm": [[500.0, -200.0]]}])

    def test_arc_metadata_survives_a_similarity_transform_exactly(self) -> None:
        ops = _stack([
            {"op": "create_floor_by_contour", "id": "f",
             "contour": {
                 "outer": {"shape": "poly", "points_mm": [
                     [0, 0], [2000, 0], [2000, 2000], [0, 2000]],
                     "arcs": [{"edge": 0, "radius_mm": 1200, "dir": "ccw"},
                              {"edge": 2, "bulge": -0.25}]},
                 "holes": []}}
        ], self.HALF)
        arcs = _top(ops, "create_floor_by_contour")["contour"]["outer"]["arcs"]
        self.assertEqual(arcs,
                         [{"edge": 0, "radius_mm": 600.0, "dir": "ccw"},
                          {"edge": 2, "bulge": -0.25}])

    def test_anisotropic_scale_of_a_circular_arc_refuses_instead_of_lying(self) -> None:
        with self.assertRaises(KirRefusal) as ctx:
            _stack([
                {"op": "create_floor_by_contour", "id": "f",
                 "contour": {
                     "outer": {"shape": "poly", "points_mm": [
                         [0, 0], [2000, 0], [2000, 2000], [0, 2000]],
                         "arcs": [{"edge": 0, "bulge": 0.25}]},
                     "holes": []}}
            ], {"scale_xy_top": [0.5, 0.75]})
        diag = ctx.exception.diagnostics[0]
        self.assertEqual(diag.field_name, "contour.outer.arcs")
        self.assertIn("эллипс", diag.message_ru)

    def test_a_point_is_moved_exactly_once(self) -> None:
        """🔴 CAUGHT BY THE RUN: a double carry-over produced a fourfold shrink."""
        ops = _stack([
            {"op": "create_column", "id": "c", "xy": [1000, 1000],
             "symbol": {"by": "name", "value": "К"}},
        ], self.HALF)
        self.assertEqual(_top(ops, "create_column")["xy"], [500.0, 500.0])

    def test_a_carrier_we_cannot_move_is_refused_by_name(self) -> None:
        """Silently leaving geometry in place is that very defect. The
        refusal names the FIELD, the KIND, and the next move."""
        with self.assertRaises(KirRefusal) as ctx:
            _stack([{"op": "create_roof", "id": "r",
                     "outline": [[0, 0], [1000, 0], [1000, 1000]],
                     "slopes": [30.0, None, None]}], self.HALF)
        msg = ctx.exception.diagnostics[0].message_ru
        self.assertIn("slopes", msg)
        self.assertIn("Следующий ход", msg)

    def test_without_a_transform_nothing_moves_at_all(self) -> None:
        """🔴 THE GREEN OUTCOME. Without it, a fix that "always carries over"
        would pass everything else, and `stack` without `transform` is the
        macro's main use case."""
        ops = _stack([
            {"op": "create_floor", "id": "f",
             "outline": [[0, 0], [1000, 0], [1000, 1000], [0, 1000]]},
            {"op": "create_roof", "id": "r", "outline": [[0, 0], [1, 0], [1, 1]],
             "slopes": [30.0, None, None]},
        ])
        self.assertEqual(_top(ops, "create_floor")["outline"],
                         [[0, 0], [1000, 0], [1000, 1000], [0, 1000]])
        self.assertEqual(_top(ops, "create_roof")["slopes"], [30.0, None, None])


class РешениеЕстьПоКАЖДОМУРоду(unittest.TestCase):

    def test_the_table_is_complete_over_the_registry(self) -> None:
        """🔴 THE MECHANISM THAT REPLACED THE LIST OF NAMES. A new parameter
        kind in the registry must DEMAND A DECISION, not slip through
        silently — which is exactly how `pts` (`create_floor.outline`) slipped
        through."""
        undecided = sorted(set(spec.PARAM_KINDS) - set(macros._TRANSFORM_BY_KIND))
        self.assertEqual(undecided, [],
                         f"роды без решения о переносе: {undecided}")
        self.assertGreaterEqual(len(spec.PARAM_KINDS), 30)   # denominator

    def test_the_table_invents_no_kind_of_its_own(self) -> None:
        """The other side: the table must not contain a kind that isn't in
        the registry — otherwise it would silently drift from it in the
        OTHER direction."""
        extra = sorted(set(macros._TRANSFORM_BY_KIND) - set(spec.PARAM_KINDS))
        self.assertEqual(extra, [], f"роды, которых нет в реестре: {extra}")

    def test_the_plan_comes_from_the_registry_not_from_a_name_list(self) -> None:
        """`create_floor.outline` is exactly the field missing from the
        hand-written list; now it comes from the registry."""
        plan = dict(macros._geometry_plan("create_floor"))
        self.assertEqual(plan["outline"], macros._KIND_RING)
        self.assertEqual(plan["holes"], macros._KIND_RINGS)
        for name in ("p0_mm", "p1_mm"):
            self.assertEqual(dict(macros._geometry_plan("create_wall"))[name],
                             macros._KIND_POINT)

    def test_an_op_outside_the_registry_still_gets_the_safety_net(self) -> None:
        """The `_XY_FIELDS` safety net remains, and works ONLY where the
        registry does not know about the op."""
        self.assertEqual(macros._geometry_plan("такого-опа-нет"), ())
        self.assertIn("p0_mm", macros._XY_FIELDS)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
