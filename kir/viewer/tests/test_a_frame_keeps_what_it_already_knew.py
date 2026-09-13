"""A FRAME MUST NOT LOSE KNOWLEDGE IT ALREADY HAD, AND STAY SILENT ABOUT THE
LOSS.

Audit findings `F-310` and `F-171` (P1), taken by MY OWN coverage number
(turn 1). One class: a live frame holds a fact, hands it out empty, and does
not say the fact existed.

`F-310` — `kir/viewer/live_scene.py`. `bundle_elements` builds
`BundleGeometry.hosted`, and `facts_for_programs` EXPLICITLY accepts this
index — its docstring calls it "READY-MADE, computed before this." The only
production call passed only `op_by_id`.

    COVERAGE MEASUREMENT: a frame over the raised program of EACH of the
    corpus's 65 decompiles
    BEFORE: edges_unmeasured=true — 65 of 65
    AFTER:  edges_unmeasured=true —  0 of 65

Every live frame published empty links and NOT A SINGLE unresolved host —
even when that same frame had resolved or refused them.

`F-171` — `kir/assembly_view.py` + `kir/live/verdict.py`. For a verdict with
no walls, `enclosure_none` was built with an EMPTY address, and
`Observation.__post_init__` forbids an empty address ("the reader has
nothing to fix"). The exception flew out of the observation itself, and the
live wrapper swallowed it TOGETHER WITH THE WHOLE SUMMARY.

    COVERAGE MEASUREMENT across 65 corpus batches:
    BEFORE: 57 get the summary, 8 LOSE IT, and for ALL EIGHT no reason is
            named
    AFTER:  65 of 65 get it

🔴 TWO OF MY OWN MEASUREMENT INSTRUMENTS WERE WRONG, AND BOTH WERE RETRACTED
BEFORE HANDOFF. The first read the `assembly` key in the FRAME's metadata
and gave "65 of 65 without a summary"; the summary is stamped not by the
frame but by the VERDICT BLOCK, and it is not in the frame's metadata and
should not be. The correct surface gave 8 of 65. The same tell that already
cost the shift two cases: an instrument answering SUSPICIOUSLY THE SAME on
everything means either I am feeding it the wrong thing or looking in the
wrong place.

WHY `no_walls`, AND NOT NEW CODE. A wall-less branch already exists in this
same module and has already chosen an address form
(`address=("(программа)",)`). A second way of saying the same thing would
split the vocabulary into two.

WHY THE WRAPPER STILL DOES NOT DROP THE VERDICT. The argument "the summary
is younger than the verdict" is correct and left as it was. What was wrong
was something else — that the loss went NOWHERE: the channel exists (the
same block), there was simply nothing to put into it.
"""
from __future__ import annotations

import unittest

from kir import assembly_view as AV
from kir.live import verdict as V
from kir.viewer import live_scene as L

_LEVEL = {"op": "create_level", "id": "lv", "name": "L1", "elev_mm": 0.0}
_WALL = {"op": "create_wall", "id": "w0", "p0_mm": [0, 0], "p1_mm": [5000, 0],
         "height_mm": 3000, "level": {"by": "name", "value": "L1"}}


class _Report:
    building_id = "HAB000"
    witness = None


class КадрНесётТоЧтоУжеПосчитал(unittest.TestCase):
    """F-310."""

    def test_the_hosted_index_reaches_the_graph(self) -> None:
        """🔴 THE SUBJECT. The host index was already built earlier from the
        same frame."""
        door = {"op": "create_door", "id": "d0", "host": "w0",
                "offset_mm": 1000.0, "symbol": {"by": "name", "value": "Д"}}
        _blob, meta = L.scene_from_programs([{"ops": [_LEVEL, _WALL, door]}],
                                            doc_key="проба")
        graph = meta.get("graph") or {}
        self.assertFalse(graph.get("edges_unmeasured"),
                         "кадр объявил связи неизмеренными, имея индекс хозяев")

    def test_the_sole_production_call_passes_two_arguments(self) -> None:
        """STRUCTURALLY, NOT BY NUMBERS: a check on the outcome would not
        distinguish "the index was passed in" from "the graph happened to
        find the edges on its own"."""
        seen = []
        real = L._graph.facts_for_programs

        def spy(ops_by_id, hosted=None):
            seen.append(hosted is not None)
            return real(ops_by_id, hosted)

        L._graph.facts_for_programs = spy
        try:
            L.scene_from_programs([{"ops": [_LEVEL, _WALL]}], doc_key="проба")
        finally:
            L._graph.facts_for_programs = real
        self.assertTrue(seen and all(seen),
                        "индекс хозяев в граф не передан")


class СводкаЛибоЕстьЛибоНазываетПочемуЕёНет(unittest.TestCase):
    """F-171."""

    def test_a_wall_less_verdict_does_not_throw_inside_its_own_observation(self) -> None:
        """🔴 THE SUBJECT: an observation with an empty address is forbidden
        by `Observation` itself, and it was being built exactly on a
        wall-less input."""
        view = AV.observe_verdict(_Report(), [], programs=[{"ops": [_LEVEL]}])
        self.assertIn("no_walls", [o.code for o in view.observations])

    def test_a_wall_less_pack_still_gets_its_assembly(self) -> None:
        """MEASURED: before the fix such batches lost the summary entirely
        — 8 of 65 across the corpus."""
        block = V._with_assembly({}, _Report(), [{"ops": [_LEVEL]}])
        self.assertIn("assembly", block)
        self.assertIn("assembly_note", block)

    def test_a_walled_pack_is_unchanged(self) -> None:
        """🔴 THE GREEN OUTCOME. 57 of 65 batches got the summary even
        before the fix; it must not touch them."""
        block = V._with_assembly({}, _Report(), [{"ops": [_LEVEL, _WALL]}])
        self.assertIn("assembly", block)
        codes = [o["code"] for o in block["assembly"].get("observations", ())]
        self.assertNotIn("no_walls", codes)

    def test_a_failure_of_the_summary_is_named_not_swallowed(self) -> None:
        """🔴 THE SECOND HALF: a failed summary still does NOT drop the
        verdict, but no longer disappears without a trace."""
        real = AV.observe_verdict

        def boom(*_a, **_kw):
            raise RuntimeError("свидетель отвалился")

        AV.observe_verdict = boom
        try:
            block = V._with_assembly({"message_ru": "цел"}, _Report(),
                                     [{"ops": [_LEVEL, _WALL]}])
        finally:
            AV.observe_verdict = real
        self.assertEqual(block["message_ru"], "цел", "вердикт пострадал")
        self.assertNotIn("assembly", block)
        self.assertIn("НЕ СОБРАЛАСЬ", block.get("assembly_note", ""))
        self.assertIn("RuntimeError", block["assembly_note"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
