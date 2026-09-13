"""THE BOUNDARY OF EXTRACTION IS NOT THE AUTHOR'S ERROR (wave of
11.08.2026).

A continuation of `test_clash_wiring.py`. A separate file, because the
subject here is one and narrow: a dangling host edge that has TWO
different meanings depending on WHOSE words these are.

EVERY TEST HERE FAILED BEFORE THE FIX.
"""
from __future__ import annotations

import unittest

from kir.clash import hulls as H
from kir.clash import snapshot as S
from kir import clash_bundle
from kir import clash_judgement as J


def _finding(a_id, b_id, la="door", lb="wall", rel="overlap",
             grade="conservative", depth=120.0, sa="profile", sb="profile"):
    return {
        "finding_id": f"{a_id}~{b_id}",
        "a": {"source_element_id": a_id, "label": la,
              "category": "OST_Doors", "hull_source": sa},
        "b": {"source_element_id": b_id, "label": lb,
              "category": "OST_Walls", "hull_source": sb},
        "hull_relation": rel, "hull_grade": grade,
        "hull_overlap_depth_mm": depth, "ranking_tol_mm": 1.0,
        "pair_kind": "physical",
    }


class TheBoundaryOfExtractionIsNotAnAuthorsError(unittest.TestCase):
    """A DANGLING HOST — TWO DIFFERENT FACTS, AND ONE OF THEM IS NOT
    ABOUT THE AUTHOR.

    A CORPUS-WIDE MEASUREMENT (11.08.2026, `/tmp/wiring/m_dangling.py`:
    67 snapshots, 1 139 477 elements, 213 811 `host_id` edges). Dangling
    references: 1 263 — 0.6% of the whole corpus, but they are
    CONCENTRATED, not spread evenly:

        snowdon_elec_v1        959 of 1 001    (95.8%)
        snowdon_plumb_v1..v4    50..54 of 50..54 (100%)
        snowdon_plumb_v5        86 of 2 860    (3.0%)
        sob62_r23_v2..v6         1 of 187..189 (0.5%)
        the remaining 41 snapshots with edges  (0%)

    WHAT THEY ACTUALLY ARE (`/tmp/wiring/m_elec.py`):

      * 1 010 point into the L0 file's `link` ENTRY — the host lies in a
        LINKED file. For `snowdon_elec_v1` all 959 lead into THREE
        different `RevitLinkInstance` objects (`1362762` x812, `1362428`
        x110, `1484390` x37), and the owners are light fixtures, panels,
        and equipment: OST_ElectricalFixtures 497, OST_LightingDevices
        187, OST_ElectricalEquipment 165;
      * 86 (`snowdon_plumb_v5`) point into a `ReferencePlane` — a datum
        that `hulls.KIND_TABLE` does not count as a body IN PRINCIPLE.
        The host is not "lost": it could NEVER have become a hull.

    Neither of the two is the author's error: both are THE BOUNDARY OF
    OUR OWN EXTRACTION. Folding them into `contradicts` ("the author
    named the wrong one") means accusing the author 959 times in a row of
    something they did not do. This is the same class of defect closed
    yesterday, only with the opposite sign: there the instrument was
    silent in a way that looked clean, here THE INSTRUMENT'S BOUNDARY
    LOOKS LIKE THE AUTHOR'S ERROR.

    WHAT DISTINGUISHES THEM IS THE SOURCE, NOT A GUESS.
    `program_host_ref` is the words of the PROGRAM ITSELF, and there a
    nonexistent reference is INDEED the author's to fix (`KIR-V002`
    forbids a reference across a program boundary). `l0_host_id` is the
    words of the DECOMPILE, and there a host that was not found says only
    that we did not extract it.
    """

    def test_an_L0_host_never_extracted_is_not_blamed_on_the_author(self):
        hosted = {"1516314": {"host_element_id": None,
                              "host_ref": "1362762",
                              "host_class": None,
                              "source": "l0_host_id"}}
        row = J.judge([_finding("1516314", "1516399")], hosted=hosted).judged[0]
        self.assertEqual(row.host_state, "host_out_of_scope")
        self.assertNotEqual(row.host_state, "contradicts")
        self.assertEqual(row.declared_host_id, "1362762")

    def test_a_program_ref_that_does_not_exist_IS_the_authors_fault(self):
        ops = {"p1/d": {"op": "create_door", "id": "d",
                        "host": {"by": "ref", "value": "нет-такой-стены"}}}
        hosted = J.hosted_from_ops(ops)
        self.assertEqual(hosted["p1/d"]["source"], "program_host_ref")
        self.assertEqual(J.host_relation("p1/d", "p1/w", hosted)[0],
                         "contradicts")

    def test_out_of_scope_still_does_NOT_acquit(self):
        """The boundary of extraction is NOT an excuse. Whether the
        element lives inside the second side, we do not know; "we do not
        know" and "it lives there" are different answers, and the tier
        must remain the same as for a pair with no host at all."""
        hosted = {"a": {"host_element_id": None, "host_ref": "1362762",
                        "source": "l0_host_id"}}
        row = J.judge([_finding("a", "b")], hosted=hosted).judged[0]
        self.assertNotEqual(row.rule_id, "host_declared")
        self.assertEqual(
            row.rung, J.judge([_finding("a", "b")], hosted={}).judged[0].rung)

    def test_the_text_names_the_boundary_and_never_the_author(self):
        hosted = {"a": {"host_element_id": None, "host_ref": "1362762",
                        "source": "l0_host_id"}}
        text = J.judge([_finding("a", "b")], hosted=hosted).judged[0].text_ru
        self.assertIn("1362762", text)
        self.assertNotIn("автор назвал хозяином", text)
        self.assertIn("ИЗВЛЕЧ", text.upper())

    def test_a_resolvable_L0_host_elsewhere_is_STILL_contradicts(self):
        """The boundary of extraction is ONLY about a host that was not
        found. When the host is found and it is a different element, the
        fact remains a fact: the 10.08 measurement — 587 of 588 such
        pairs on `sob62_r23_v5` and 8 728 of 8 728 on
        `sob62_fas_r23_v19` have a host WITH A BODY, that is, checkable."""
        hosted = {"10324348": {"host_element_id": "9857641",
                               "host_class": "Wall", "source": "l0_host_id"}}
        row = J.judge([_finding("10324348", "13109052")],
                      hosted=hosted).judged[0]
        self.assertEqual(row.host_state, "contradicts")

    def test_an_unknown_source_is_extraction_not_authorship(self):
        """The author can be blamed ONLY by their own words. A source we
        know nothing about is not their words."""
        hosted = {"a": {"host_element_id": None, "host_ref": "zzz",
                        "source": "какой-то-будущий-индекс"}}
        row = J.judge([_finding("a", "b")], hosted=hosted).judged[0]
        self.assertEqual(row.host_state, "host_out_of_scope")

    def test_the_state_list_stays_closed_and_counted(self):
        self.assertEqual(set(J.HOST_STATES),
                         {"confirms", "contradicts", "host_out_of_scope",
                          "absent", "unknown"})
        hosted = {"a": {"host_element_id": None, "host_ref": "x",
                        "source": "l0_host_id"},
                  "c": {"host_element_id": "zzz", "source": "l0_host_id"}}
        out = J.judge([_finding("a", "b"), _finding("c", "d"),
                       _finding("e", "f")], hosted=hosted)
        self.assertEqual(out.by_host_state,
                         {"absent": 1, "contradicts": 1,
                          "host_out_of_scope": 1})
        self.assertEqual(sum(out.by_host_state.values()), len(out.judged))
        for state in out.by_host_state:
            self.assertIn(state, J.HOST_STATES)


class TheWallCensusAsksTheTableInsteadOfAsserting(unittest.TestCase):
    """`_wall_geometry` DECLARED in a string that a wall has no hull
    (`wall_prism_refused_by_containment_gate`), WITHOUT EVER asking the
    table that decides this.

    MEASUREMENT OF 11.08.2026 (`/tmp/wiring/m_wall.py`): today the
    statement is CORRECT — `hulls.KIND_TABLE["OST_Walls"].sources ==
    ("bbox",)`, and `build_hull` on a FULL prism (`width_mm` 200,
    `uniform` True, no blockers) returns `None` with the reason "neither
    a contour, nor a cross-section, nor a bounding box." The lock is
    closed, and my report yesterday that it had opened was an INFERENCE
    ERROR: `hulls.hull_from_wall_axis` exists in the tree, but
    `KIND_TABLE` does not allow it for walls.

    The defect, therefore, is not in the number but in the METHOD: a
    constant in one module asserts the contents of another module's
    table, without ever reading it. On the day `prism` appears in
    `sources`, a wall will get a body — and the `clash_bundle` census
    will keep counting it as "without geometry," and the receipt will
    say "NOT LOOKED AT" about an element that was looked at. This is
    fixed not by a new number but by a QUESTION to the table that
    decides.
    """

    def _wall_op(self):
        return {"op": "create_wall", "id": "w1",
                "type": {"by": "name", "value": "Стена 200"},
                "level": {"by": "name", "value": "L1"},
                "height_mm": 3000.0,
                "p0_mm": [0.0, 0.0, 0.0], "p1_mm": [4000.0, 0.0, 0.0]}

    def _snapshot(self):
        return {"levels": [{"id": "lv1", "name": "L1", "elevation_mm": 0.0}],
                "wall_types": [{"id": "wt1", "name": "Стена 200",
                                "section": {"kind": "plate",
                                            "thickness_mm": 200.0,
                                            "uniform": True, "blockers": [],
                                            "source": "type"}}]}

    def _geometry(self):
        return clash_bundle.bundle_elements([{"ops": [self._wall_op()]}],
                                            snapshot=self._snapshot())

    def test_the_numbers_are_still_collected(self):
        """The fix must not touch the COLLECTION of numbers: the prism is
        assembled exactly as it was assembled, only what is said about it
        changes."""
        el = self._geometry().elements[0]
        self.assertIn("prism", el)
        self.assertEqual(el["prism"]["width_mm"], 200.0)
        self.assertEqual((el["z0_mm"], el["z1_mm"]), (0.0, 3000.0))

    def test_the_blame_matches_what_the_table_actually_allows(self):
        geo = self._geometry()
        blamed = "wall_prism_refused_by_containment_gate" in geo.no_geometry
        allowed = "prism" in (H.KIND_TABLE["OST_Walls"].sources or ())
        self.assertEqual(blamed, not allowed)

    def test_a_wall_is_never_both_hulled_and_counted_as_bodiless(self):
        """A LOCK AGAINST DIVERGENCE. An element that made it into bodies
        must not simultaneously stand in the "without geometry" census:
        the receipt counts `without_body` from the first, and prints the
        REASON from the second."""
        geo = self._geometry()
        snap = S.build_from_elements(geo.elements, origin={"source": "t"},
                                     profiles=geo.profiles)
        hulled = len(snap.records) > 0
        blamed = sum(geo.no_geometry.values()) > 0
        self.assertNotEqual(
            hulled, blamed, "стена одновременно с телом и без геометрии")

    def test_a_wall_the_snapshot_cannot_type_names_its_own_reason(self):
        """A refusal BEFORE the prism is not substituted: "no type in the
        snapshot" and "the table does not accept the prism" are different
        fixes, and must remain different."""
        geo = clash_bundle.bundle_elements(
            [{"ops": [self._wall_op()]}],
            snapshot={"levels": [{"id": "lv1", "name": "L1",
                                  "elevation_mm": 0.0}], "wall_types": []})
        self.assertIn("wall_type_not_in_snapshot", geo.no_geometry)
        self.assertNotIn("prism", geo.elements[0])


if __name__ == "__main__":
    unittest.main()
