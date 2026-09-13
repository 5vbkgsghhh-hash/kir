"""THE HOST BEATS THE LABEL TABLE — AND ONLY WHEN THE DATA OBJECTS.

THE MEASUREMENT THAT BOUGHT THIS FILE (18.08.2026, tree `prod-live`, instrument —
a run of `snapshot.read_decompile` + `detect` + `resolve.propose` live on saved
decompiles; not a single Revit, not a single network):

    sob62_r23_v5        3 759 findings · label removed 497 · became 258
                        returned to findings 239 · confirmed by data 188
                        share of removals NOT by confirmation  62.2 % -> 27.1 %
    sob62_fas_r23_v19  27 041 findings · label removed 8 815 · became 2 604
                        returned to findings 6 211 · confirmed by data 1 473
                        share of removals NOT by confirmation  83.3 % -> 43.4 %

🔴 AND THE MAIN NUMBER OF THIS FILE IS ZERO. New «сдвиньте» instructions after
the fix: **0 on both buildings** (`move` 4->4 and 0->0). Returned pairs become
`review`, not a turn: both sides of the node are immobile, and an overturned
table does not grant the right to build. This is a direct guard against the kind
of defect shipped to prod 17.08 (`9e9a43bf`: a destructive instruction on an
unproven finding, fixed by `95bc2fcd`).

WHAT IS REFUTED HERE IN THE CANON RECORD. The previous wording — "313 out of 497
(63.0 %) were removed AGAINST the data" — added together two different facts:
the data OBJECTS (`contradicts`, 239) and the data IS SILENT (`absent`, 74). The
sum reproduces, but only the first addend has the right to overturn the table.
The discrepancy with the canon on the second building is named, not smoothed
over: it wrote "confirmed 1 453", this run gives **1 473**, a difference of 20
pairs.

WHY SILENCE DOES NOT OVERTURN, even though in `clash_judgement` the same
`absent` "does not justify": there a LADDER OF RUNGS stands behind the unproven,
here there is none — `resolve.to_russian` prints the verb immediately. In this
decompile `host_id` exists for 12.5 % of elements (189 of 1 510), and letting
silence count as a refutation would mean printing «сдвиньте дверь» where the
host simply was not read.

Run:
    venv/bin/python -m pytest kir/clash/tests/test_host_beats_the_label_table.py -q
"""
from __future__ import annotations

import unittest

from kir.clash import geom as G
from kir.clash import hulls as H
from kir.clash import resolve as R
from kir.clash import snapshot as S

#: The door and the wall OVERLAP: `propose` requires an actual overlap,
#: otherwise it returns `not_overlapping` and the recommendation is not checked
#: at all.
_DOOR_BOX = G.Aabb((0.0, 0.0, 0.0), (1000.0, 200.0, 2100.0))
_WALL_BOX = G.Aabb((0.0, 0.0, 0.0), (5000.0, 300.0, 3000.0))


def _rec(sid: str, hull: G.Hull, label: str, category: str) -> H.HullRecord:
    return H.HullRecord(source_id=sid, category=category, label=label,
                        mvp_side=None, hull=hull, grade="coarse",
                        hull_source="bbox")


def _door() -> H.HullRecord:
    return _rec("10324348", _DOOR_BOX, "door", "OST_Doors")


def _wall(sid: str = "13109052") -> H.HullRecord:
    return _rec(sid, _WALL_BOX, "wall", "OST_Walls")


def _edge(target: str | None, source: str) -> dict:
    return {"host_element_id": target, "host_ref": target or "ref",
            "host_class": None, "source": source}


class TheTableDecidesOnlyWhereDataIsSilent(unittest.TestCase):

    def test_without_an_index_the_answer_is_the_old_one_literally(self):
        """The default is PREVIOUS BEHAVIOR. `None` means "was not asked"."""
        p = R.propose(_door(), _wall(), with_alternative=False)
        self.assertEqual(p.recommendation, "assembly_relation")
        self.assertIsNone(p.host_state,
                          "«не спрашивали» обязано быть отличимо от «спросили»")

    def test_an_empty_index_is_asked_and_silent_and_changes_nothing(self):
        """FAIL CONTROL of the wave: an empty index does NOT overturn the table."""
        p = R.propose(_door(), _wall(), hosted={}, with_alternative=False)
        self.assertEqual(p.recommendation, "assembly_relation")
        self.assertEqual(p.host_state, "absent")

    def test_a_declared_host_that_is_the_other_side_confirms_the_node(self):
        hosted = {"10324348": _edge("13109052", S.L0_HOST_SOURCE)}
        p = R.propose(_door(), _wall(), hosted=hosted, with_alternative=False)
        self.assertEqual(p.recommendation, "assembly_relation")
        self.assertEqual(p.host_state, "confirms")

    def test_a_host_elsewhere_overturns_the_table(self):
        """THE CORE CASE: a door overlaps a wall it does NOT live in.

        A sample from the corpus verbatim — door `10324348` declares wall
        `9857641` as its host, but overlaps wall `13109052`.
        """
        hosted = {"10324348": _edge("9857641", S.L0_HOST_SOURCE)}
        p = R.propose(_door(), _wall(), hosted=hosted, with_alternative=False)
        self.assertEqual(p.host_state, "contradicts")
        self.assertNotEqual(p.recommendation, "assembly_relation")

    def test_the_overturned_pair_never_becomes_a_destructive_move(self):
        """🔴 GUARD AGAINST THE `9e9a43bf` KIND OF DEFECT. An overturned table
        does NOT grant the right to build.

        The door and the wall are both immobile per `mobility_of`, so the
        outcome is required to be `review` — «решает человек» — not the verb
        «сдвиньте».
        """
        hosted = {"10324348": _edge("9857641", S.L0_HOST_SOURCE)}
        p = R.propose(_door(), _wall(), hosted=hosted, with_alternative=False)
        self.assertEqual(p.recommendation, "review")
        self.assertNotIn("сдвиньте", R.to_russian(p))

    def test_a_host_outside_the_extraction_does_NOT_overturn(self):
        """A host in a LINKED file is the boundary of our reading, not evidence.

        1 010 of the corpus's 1 263 dangling edges lead exactly there. Blaming
        the author for them is a defect of the same kind as a silent instrument.
        """
        hosted = {"10324348": _edge(None, S.L0_HOST_SOURCE)}
        p = R.propose(_door(), _wall(), hosted=hosted, with_alternative=False)
        self.assertEqual(p.host_state, "host_out_of_scope")
        self.assertEqual(p.recommendation, "assembly_relation")

    def test_the_same_dangling_edge_from_a_program_DOES_overturn(self):
        """The same data, DIFFERENT MOUTH — and a different verdict.

        The program's words: the author referenced an op that is not in his
        program (`KIR-V002`), and he is the one to fix it. The meaning of the
        source is load-bearing, so it is checked, not assumed.
        """
        from kir import clash_judgement as CJ
        hosted = {"10324348": _edge(None, CJ.AUTHORED_SOURCE)}
        p = R.propose(_door(), _wall(), hosted=hosted, with_alternative=False)
        self.assertEqual(p.host_state, "contradicts")
        self.assertNotEqual(p.recommendation, "assembly_relation")

    def test_every_state_is_named_in_the_closed_note_table(self):
        from kir import clash_judgement as CJ
        self.assertEqual(set(R.HOST_STATE_NOTES), set(CJ.HOST_STATES),
                         "словарь перевода разошёлся с алгеброй состояний")


class TheIndexIsBuiltFromWhatTheDecompileAlreadyRead(unittest.TestCase):

    def test_host_id_becomes_an_edge_of_the_shape_the_reader_expects(self):
        idx = S.hosted_from_l0([{"element_id": 10324348, "host_id": 9857641}])
        self.assertEqual(idx, {"10324348": {
            "host_element_id": "9857641", "host_ref": "9857641",
            "host_class": None, "source": "l0_host_id"}})

    def test_an_element_hosting_itself_is_not_an_edge(self):
        """`confirms` on itself would be a false confirmation."""
        self.assertEqual(
            S.hosted_from_l0([{"element_id": 7, "host_id": 7}]), {})

    def test_absence_of_a_host_is_absence_of_an_edge_not_a_null_edge(self):
        for empty in (None, "", 0, "0"):
            with self.subTest(host=empty):
                self.assertEqual(
                    S.hosted_from_l0([{"element_id": 7, "host_id": empty}]), {})

    def test_the_snapshot_carries_the_index_including_unhulled_elements(self):
        """A host also exists for those whose geometry did not come through.

        Measurement: 189 edges against 1 326 hulls on 1 510 elements — an index
        living in `HullRecord` would have SILENTLY lost the refusals.
        """
        elements = [
            {"element_id": 1, "category": "OST_Walls", "host_id": None,
             "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [1000, 300, 3000]},
            # neither bbox nor axes — there will be no hull, but the host is declared
            {"element_id": 2, "category": "OST_Doors", "host_id": 1},
        ]
        snap = S.build_from_elements(elements, origin={})
        self.assertEqual(snap.hosted, {"2": {
            "host_element_id": "1", "host_ref": "1", "host_class": None,
            "source": "l0_host_id"}})
        self.assertNotIn("2", {r.source_id for r in snap.records},
                         "предпосылка теста: у элемента 2 оболочки нет")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
