"""Whether the contents of `members` reach emission — element-by-element or as a summary.

WHY. The director's decision: the unfolding of intent targets L1. Then
everything `fold.iter_l1_leaves` yields out of `members` must reach the
ops — otherwise a cluster that is one node to the reader loses content on
the way to the building. The BUILDING zone named the cost: 23 855 records
out of 55 293 on the tower, 43% of the content.

THE ANSWER: **`members` is NOT a summary.** It is `list[L1Node]`, the same
type as `payload`, full records with their own `_id`/`source_element_id`;
the summary sits ALONGSIDE, in `macro`. `iter_l1_leaves` yields a member at
the same rank as `payload`, and `fold.assert_preservation` — a law that
stands over EVERY `fold_document` — requires an exact match of the leaf
multiset AND byte-for-byte equality of the payload. A member cannot be
lost quietly, or at all.

**BUT 43% IS NOT THE NUMBER THAT DECIDES HERE, AND A BREAKDOWN BY KIND
CHANGES IT.** Measurement of 12.08.2026 on THREE tower runs. A
provenance-tracking traversal, its total checked against the authority on
each one (55 293 = 55 293, 115 880 = 115 880, 115 880 = 115 880), otherwise
the breakdown is invalid:

    run           leaves    members            ATOMS    OPS   ops       payload
                                               in members       reached   control
    v6 RECALLED    55 293   23 855 (43.14%)   23 582    273   273/273   29 575/29 575
    v7            115 880   80 547 (69.51%)   80 268    279   279/279   29 650/29 650
    v8            115 880   77 262 (66.67%)   76 983    279   279/279   32 555/33 198

Member decomposition is stable: `atom_cluster→atom` holds 96–99% of
members, `row→op` gives 265/271/271, `grid_array→op` gives 8 on all three.

An atom is typed inexpressibility with a reason code, not an op: the
unfolding does not produce it and is not obligated to. **Member ops must
reach, and on all three runs ALL of them reach — 0 missed.** Materialize's
misses are exactly atoms (`atom:*`), plus on `v8` another 643
`host_unmaterialized` — and this MATTERS: on `v8` the control stopped
being 100% (payload 32 555 out of 33 198 = 98.06%), meaning the matcher IS
ABLE to show a loss. Member ops, meanwhile, do better than payload: 100%
against 98.06%.

**A RETRACTION, AND IT IS MY OWN.** The headline number "honest authorship
denominator = 53.98%" was taken from `v6` and IS INVALID: the BUILDING
zone found 2 846 group-index failures out of 2 941 in that run (96.77% of
groups lost), and on top of that `v6` was a partial read (20 categories
out of the table came back empty). The legitimate band from the two clean
runs:

    v7   29 929 leaf-ops out of 115 880 = 25.83%
    v8   33 477 leaf-ops out of 115 880 = 28.89%

**Why this matters more than the correction itself.** Ops barely grew
between `v6` and `v7` (29 848 → 29 929, +0.27%), while atoms tripled
(25 445 → 85 951). So the 53.98% was not measuring the COMPILER — it was
measuring HOW MUCH OF THE BUILDING THAT RUN HAD READ. Exactly the same
defect that made the facade give 63.80 and 91.23 without a single line
changed. The authorship denominator must be published together with its
reading conditions, otherwise it is uninterpretable. The `v7`→`v8`
difference (25.83 → 28.89 with the same read of 115 880) is genuine
already: that is the lifter, not the reading.

THE CONTROL CAUGHT ITSELF, and this is worth recording: the first run
matched the emission address against the bare `source_element_id` and gave
**0 out of 273** — which would read as "members are being lost." What
saved it was that the control's own denominator was printed alongside:
payload gave **0 out of 29 575**, meaning it was the MATCHER that was
blind. The emission address is `_op_id` = ``"e" + source_element_id``;
asked of `materialize._op_id`, not guessed.

THE KIND OF THIS TEST. The numbers above are a DATED MEASUREMENT on a
machine-local corpus (`backend/backend/data/decompile/`, outside any
checkout; `k2_ar_rd_v15` gives no numbers at all — it has no `tree.json`,
and that is the instrument's silence, not a zero). The test does NOT run
them: a guard without its own instrument must refuse in a category that
cannot be mistaken for "no findings." What is pinned here is a STRUCTURAL
fact that does not depend on the corpus and is all the unfolding contract
needs: a member travels at the same rank as `payload` and reaches an op.
To repeat the measurement: ``scratchpad/member_ops_reach_programs.py``
(traversal + `leaves_to_program`).
"""
from __future__ import annotations

import unittest

from kir.decompile.fold import iter_l1_leaves
from kir.decompile.l1_schema import stable_l1_id
from kir.decompile.materialize import leaves_to_program

LEVEL_SRC = "SYNTH-LEVEL-1"
PAYLOAD_SRC = "SYNTH-COL-PAYLOAD"
MEMBER_SRC = "SYNTH-COL-MEMBER"
LEVEL_ID = stable_l1_id("op", LEVEL_SRC)


def _op(op_name, source_id, params, level_name=None):
    return {
        "kind": "op",
        "_id": stable_l1_id("op", source_id),
        "source_element_id": source_id,
        "level_name": level_name,
        "anchor_mm": None,
        "type_name": "—",
        "op_name": op_name,
        "params": params,
    }


def _level():
    return _op("create_level", LEVEL_SRC, {"name": "Этаж 1", "elev_mm": 0})


def _wall(source_id, x):
    return _op("create_wall", source_id, {
        "p0_mm": [x, 0], "p1_mm": [x + 4000, 0], "height_mm": 3000,
        "level": {"ref": LEVEL_ID},
        "type": {"by": "name", "value": "Стена 200", "_id": "12345"},
    }, level_name="Этаж 1")


def _node(kind, *, payload=None, members=(), children=()):
    """A node literal in exactly the part `iter_l1_leaves` reads.

    The traversal touches three keys and no others; building a full
    `TreeNode` with `facts`/`node_id` here would mean asserting more than
    what is being checked.
    """
    return {"kind": kind, "payload": payload,
            "members": list(members), "children": list(children)}


def _tree(members):
    """Tree: the level as a leaf, and the wall as a MEMBER of the `row` summary."""
    return _node("floor", children=[
        _node("op", payload=_level()),
        _node("row", members=members),
    ])


class AMemberTravelsAtTheSameRankAsAPayload(unittest.TestCase):

    def test_the_authority_yields_members_beside_payloads(self):
        """`iter_l1_leaves` does not distinguish a member from a payload."""
        seen = [leaf["source_element_id"]
                for leaf in iter_l1_leaves(_tree([_wall(MEMBER_SRC, 8000)]))]
        self.assertEqual(sorted(seen), sorted([LEVEL_SRC, MEMBER_SRC]))

    def test_a_member_op_reaches_the_emitted_program(self):
        """A member reaches an op under the address `_op_id` = "e" + source id."""
        leaves = list(iter_l1_leaves(_tree([_wall(MEMBER_SRC, 8000)])))
        result = leaves_to_program(leaves, include_datums=True)
        emitted = {op["id"] for program in result.programs
                   for op in program["ops"]}
        self.assertIn("e" + MEMBER_SRC, emitted)
        self.assertEqual(
            [record.source_id for record in result.skipped], [],
            "член пропущен materialize — содержимое сводки теряется")

    def test_the_probe_can_say_no(self):
        """FAIL control: without the member, the same address must
        DISAPPEAR.

        Otherwise "reached" is indistinguishable from a matcher that
        answers yes to anything — exactly the mistake the live measurement
        caught in itself: matching by bare `source_element_id` gave 0 out
        of 273 WHILE the control gave 0 out of 29 575.
        """
        leaves = list(iter_l1_leaves(_tree([])))
        result = leaves_to_program(leaves, include_datums=True)
        emitted = {op["id"] for program in result.programs
                   for op in program["ops"]}
        self.assertNotIn("e" + MEMBER_SRC, emitted)

    def test_a_payload_and_a_member_are_indistinguishable_downstream(self):
        """The same op as a payload and as a member gives the same
        emission, except for the address.

        This is precisely "not a summary": the node's rank changes NOTHING
        about what reaches.
        """
        as_member = leaves_to_program(
            list(iter_l1_leaves(_tree([_wall(MEMBER_SRC, 8000)]))),
            include_datums=True)
        as_payload = leaves_to_program(
            list(iter_l1_leaves(_node("floor", children=[
                _node("op", payload=_level()),
                _node("op", payload=_wall(PAYLOAD_SRC, 8000)),
            ]))),
            include_datums=True)

        def shape(result, source_id):
            for program in result.programs:
                for op in program["ops"]:
                    if op["id"] == "e" + source_id:
                        return {key: value for key, value in op.items()
                                if key != "id"}
            return None

        self.assertIsNotNone(shape(as_member, MEMBER_SRC))
        self.assertEqual(shape(as_member, MEMBER_SRC),
                         shape(as_payload, PAYLOAD_SRC))


if __name__ == "__main__":
    unittest.main()
