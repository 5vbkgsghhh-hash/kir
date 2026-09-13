"""The honesty layer. The main test here is a REGRESSION ON AN INSTRUMENT DEFECT.

The first measurement of shell-to-L1-node connectivity (10.08.2026) gave
32.7-37.9% "shells without a node" and looked like a fact about buildings.
It was a TRAVERSAL defect: `atom_cluster` / `row` / `grid_array` hold
collapsed atoms in `members`, not in `children`, and the cluster's own
`payload` is empty. After fixing the traversal — 0 out of 120 242 on three
buildings.

An instrument that covers only part of its range is worse than a missing
one; that is exactly why this class of error has a refuting test that
fails on the old code.
"""

import unittest

from kir.viewer import honesty as H


class ClusterMembersAreVisible(unittest.TestCase):

    def test_atoms_inside_a_cluster_are_not_lost(self):
        """The test refuting the 10.08 defect: traversing `children` alone
        would return ONE node instead of three and would declare two
        elements "without an L1 node"."""
        tree = {
            "kind": "building",
            "children": [
                {"kind": "op", "payload": {"kind": "op", "op_name": "create_wall",
                                           "source_element_id": "1"}},
                {"kind": "atom_cluster", "payload": {}, "members": [
                    {"kind": "atom", "source_element_id": "2",
                     "reason": {"code": "generator_child"}},
                    {"kind": "atom", "source_element_id": "3",
                     "reason": {"code": "missing_geometry"}},
                ]},
            ],
        }
        found = {p["source_element_id"] for p in H.iter_l1_nodes(tree)}
        self.assertEqual(found, {"1", "2", "3"})

    def test_members_and_children_are_both_walked_at_any_depth(self):
        tree = {"kind": "building", "children": [
            {"kind": "floor", "children": [
                {"kind": "row", "payload": {}, "members": [
                    {"kind": "atom", "source_element_id": "deep",
                     "reason": {"code": "no_lifter"}}]}]}]}
        self.assertEqual([p["source_element_id"] for p in H.iter_l1_nodes(tree)],
                         ["deep"])

    def test_nodes_without_an_element_address_are_skipped_silently_but_totally(self):
        """A node without an address has nothing to connect to — but it
        must not be given a made-up address either. It simply does not
        participate, and the census will see this as a difference between
        the number of nodes and the number of shells."""
        tree = {"kind": "building", "payload": {"kind": "op"}, "children": []}
        self.assertEqual(list(H.iter_l1_nodes(tree)), [])


class FidelityIsChosenByEvidence(unittest.TestCase):

    def test_degeneracy_outranks_grade(self):
        """A zero-volume bounding box stays `coarse` per the grade table,
        but is not a body at all. Drawing it as a box would mean
        inventing a thickness for it — and there are 38.2% of those on
        demo-v3."""
        self.assertIs(H.fidelity_of("coarse", "bbox", "aabb_plane"),
                      H.Fidelity.DEGENERATE)
        self.assertIs(H.fidelity_of("conservative", "profile", "aabb_point"),
                      H.Fidelity.DEGENERATE)

    def test_bbox_is_box_only_and_never_shaped(self):
        """99.89% of demo-v3 are bounding boxes. Showing them as a shape
        would mean lying about exactly what we don't know."""
        self.assertIs(H.fidelity_of("coarse", "bbox", "ok"),
                      H.Fidelity.BOX_ONLY)

    def test_every_conservative_source_is_shaped(self):
        for source in ("profile", "prism", "axis_section"):
            self.assertIs(H.fidelity_of("conservative", source, "ok"),
                          H.Fidelity.SHAPED, source)


class CensusMustBalance(unittest.TestCase):

    def test_totals_agree_across_both_axes(self):
        """A census that does not converge on one of the axes makes any
        percentage on screen unproven."""
        census = H.HonestyCensus()
        for i in range(5):
            census.add(H.ElementHonesty(str(i), H.Trust.ATOM,
                                        H.Fidelity.BOX_ONLY, "generator_child"))
        census.add(H.ElementHonesty("x", H.Trust.OP_PROVEN,
                                    H.Fidelity.SHAPED, "create_wall"))
        self.assertTrue(census.balanced())
        self.assertEqual(census.total, 6)
        self.assertEqual(census.by_atom_reason["generator_child"], 5)

    def test_unproven_ops_are_counted_apart_from_atoms(self):
        census = H.HonestyCensus()
        census.add(H.ElementHonesty("a", H.Trust.OP_UNPROVEN,
                                    H.Fidelity.SHAPED, "create_dimension"))
        self.assertEqual(census.by_unproven_op, {"create_dimension": 1})
        self.assertEqual(census.by_atom_reason, {})


class MissingEvidenceIsNeverGreen(unittest.TestCase):

    def test_absent_tree_reports_unavailable_rather_than_empty(self):
        """A missing tree and a tree without atoms are different facts.
        Silence about the second would read as "everything was loaded"."""
        mapping, note = H.read_l1_honesty("/nonexistent/run")
        self.assertEqual(mapping, {})
        self.assertFalse(note["available"])
        self.assertTrue(note["reason"])

    def test_refutation_is_not_a_trust_state(self):
        """REVERSAL OF MY OWN STATE. `Trust.CLASH_REFUTED` was an axis
        substitution: `Trust` judges the ELEMENT, while refutation
        belongs to the RELATION (`GraphEdge.refuted_by` is mandatory
        exactly when `Modality.REFUTED`). A door whose edge to a room was
        removed by the rule is read perfectly fine, and it must not be
        colored as refuted."""
        self.assertNotIn("clash_refuted", {t.value for t in H.Trust})
        from kir.viewer import graph as G
        self.assertTrue(G.FLAG_REFUTED)


class AxesKeepThreeStates(unittest.TestCase):
    """The tri-state of `serving._unwitnessed_axes`, packed into a byte.

    `{}` = all three axes are declared; a dict = there are no
    obligations on these axes; `None` = there is nothing to judge by.
    **`None` is NOT "everything is fine"**, and a binary light would
    merge the third state with the first, i.e. show green where nobody
    looked. This is exactly the defect the field was introduced to
    prevent.
    """

    def test_declared_everywhere_is_zero(self):
        self.assertEqual(H.axes_byte({}), 0)

    def test_unjudgeable_is_not_zero(self):
        self.assertEqual(H.axes_byte(None), H.AXES_UNJUDGEABLE)
        self.assertNotEqual(H.AXES_UNJUDGEABLE, 0)

    def test_each_axis_owns_its_bit_in_the_published_order(self):
        for index, axis in enumerate(H.AXES_ORDER):
            self.assertEqual(H.axes_byte({axis: ["какой-то_оп"]}), 1 << index)

    def test_all_three_missing_sets_all_three_bits(self):
        self.assertEqual(
            H.axes_byte({axis: ["оп"] for axis in H.AXES_ORDER}), 7)

    def test_an_unknown_axis_reads_as_unjudgeable_not_as_clean(self):
        """The owner of the obligations table is entitled to introduce a
        fourth axis. A response with an axis we don't know about must
        become "nothing to judge by": returning zero would mean saying
        "everything was declared" about something we did not
        understand."""
        self.assertEqual(H.axes_byte({"новая_ось": ["оп"]}),
                         H.AXES_UNJUDGEABLE)

    def test_no_ops_is_unjudgeable_rather_than_clean(self):
        """An element without an op has nothing to ask. `{}` here would
        mean "all obligations are declared", i.e. praise for silence."""
        self.assertIsNone(H.axes_for_ops([]))

    def test_the_rule_itself_is_not_copied_here(self):
        """The rule lives in `serving._unwitnessed_axes` and IS CALLED.
        Two copies drift apart silently and don't fail separately — the
        same reason `serving._axes_from_violations` has exactly one
        copy."""
        import inspect
        source = inspect.getsource(H.axes_for_ops)
        self.assertIn("_unwitnessed_axes", source)

    def test_a_wall_declares_all_three_and_a_level_does_not(self):
        """Live measurement of the table on 11.08: `create_wall`
        declares all three axes, `create_level` does not declare
        semantics or topology. If this test fails, the obligations table
        has changed, not the viewer."""
        self.assertEqual(H.axes_for_ops(["create_wall"]), {})
        missing = H.axes_for_ops(["create_level"])
        self.assertIsNotNone(missing)
        self.assertIn("semantic", missing)


class NoBodyIsItsOwnState(unittest.TestCase):

    def test_it_is_not_the_same_as_a_flat_hull(self):
        """`DEGENERATE` — a body exists and it is flat; `NO_BODY` —
        there is no body at all. Merging them would mean saying "built
        flat" about something that was not built."""
        self.assertIn(H.Fidelity.NO_BODY, set(H.Fidelity))
        self.assertNotEqual(H.Fidelity.NO_BODY, H.Fidelity.DEGENERATE)

    def test_fidelity_of_never_invents_it(self):
        """`fidelity_of` judges a BUILT shell and therefore has no right
        to return `NO_BODY`: the absence of a body is a fact belonging
        to a different module."""
        for grade in ("coarse", "conservative", "exact"):
            for source in ("bbox", "profile", "prism", "axis_section"):
                for degen in ("ok", "aabb_plane", "aabb_line", "aabb_point"):
                    self.assertIsNot(H.fidelity_of(grade, source, degen),
                                     H.Fidelity.NO_BODY)
