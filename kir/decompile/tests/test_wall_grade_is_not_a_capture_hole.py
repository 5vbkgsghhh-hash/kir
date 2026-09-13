"""THE WALL GRADE IS NOT HELD BY CAPTURE, AND THIS IS PINNED STRUCTURALLY.

WHY THIS FILE EXISTS. On 19.08.2026 a record was laid down in `hulls.py`,
on the strength of which the next wave would have gone on to build
wall-width capture. A re-measurement on 20.08 overturned three of its
numbers: the `wall_types` pool is non-empty in 77 profiles out of 77 (6880
lines), the type width sits on 1023 lines, and the wall itself carries
`WALL_ATTR_WIDTH_PARAM` in L0 on 220 326 of 286 430. The full set for a
prism exists on 203 661 walls (71.1 %).

🔴 BUT THESE NUMBERS WERE TAKEN FROM THE CORPUS, WHICH DOES NOT EXIST ON
SOMEONE ELSE'S MACHINE. The corpus is machine-local
(`backend/data/decompile`, 4.8 GB, outside any checkout), and a guard
standing on it would silently turn green for a neighbor. So what is
pinned here is not a NUMBER but a CAUSE — a property of selection that
does not depend on the corpus at all:

    `pipeline._geometry_atom_ids` requests Tier-G ONLY for L1-ATOMS.
    A wall is raised in `create_wall` SUCCESSFULLY, does not become an
    atom — and never falls into the triangle request, on any corpus
    whatsoever.

From this, `bundles_containing_a_wall: 0` stops being an observation
about three bundles and becomes a consequence of the code. The
difference decides whose work it is: an observation is fixed by a fresh
reading, a consequence — only by a DECISION to widen the Tier-G scope,
which has a cost.
"""
from __future__ import annotations

import unittest


class ОбластьTierGНеВключаетСтенуПоПостроению(unittest.TestCase):
    """The input is built by PROD CODE of L1 shape, not by a hand-written dictionary at random.

    Form 27 in its refined edition: a hand-written input is dangerous not
    through inaccuracy but through answering NO, with the negative answer
    looking like a result. Here the nodes are assembled in exactly the
    shape the lifter emits, and both sides of the experiment are present
    — otherwise it could not have ended any other way.
    """

    def _ids(self, nodes):
        from kir.decompile.pipeline import _geometry_atom_ids
        return _geometry_atom_ids(nodes)

    def test_a_successfully_lifted_wall_is_never_requested(self):
        """A wall raised into an operation is not an atom, and it is absent from the request."""
        nodes = [
            {"kind": "op", "op": "create_wall", "source_element_id": "301922"},
            {"kind": "op", "op": "create_wall", "source_element_id": "301923"},
        ]
        self.assertEqual(self._ids(nodes), [])

    def test_the_probe_can_say_yes_or_the_test_above_proves_nothing(self):
        """CONTROL: the same instrument on an atom MUST return its id.

        Without this half the previous test would turn green even for an
        instrument that returns NOTHING, EVER — that is, it would not
        distinguish "the wall is not taken" from "no one is taken."
        """
        nodes = [
            {"kind": "op", "op": "create_wall", "source_element_id": "301922"},
            {"kind": "atom", "reason": {"code": "missing_geometry"},
             "source_element_id": "409001"},
        ]
        self.assertEqual(self._ids(nodes), ["409001"])

    def test_a_generator_child_atom_is_excluded_with_its_own_reason(self):
        """The second scope exclusion is named separately — it is about the duplicate, not the wall."""
        nodes = [
            {"kind": "atom", "reason": {"code": "generator_child"},
             "source_element_id": "409002"},
            {"kind": "atom", "reason": {"code": "missing_reference"},
             "source_element_id": "409003"},
        ]
        self.assertEqual(self._ids(nodes), ["409003"])


class ШестьПараметровДоезжаютДоЭмИссии(unittest.TestCase):
    """Added on 20.08 for NAMED consumers: HAB050, HAB011, HAB022.

    There are FIVE of them. A sixth was withdrawn by a live run — see
    `ASKED` below.

    We ask the BUILDER, not the file: `build_category_batch_cs` — the
    very function whose text travels into the bridge. A grep over
    `extract.py` would answer "is the line present," while the question
    is "does it land in the body that Revit will execute": a name in a
    commented-out line or in a docstring does not make it into the
    output.

    WHAT THIS TEST DOES NOT SAY, and this is a boundary, not a caveat:
    that the parameters WILL ARRIVE. It shows that we ASK for them.
    Whether they arrive is known only to live Revit, and until the first
    live read this is an intent, not a capture.
    """

    #: FIVE, NOT SIX. `STAIRS_ATTR_TREAD_WIDTH` was added on 20.08 and
    #: withdrawn on the same day by a live run: 24 stairs, `есть 0 / пусто
    #: 24`. `Stairs` has no width property at all — it lives on
    #: `StairsRun.ActualRunWidth`.
    #:
    #: 🔴 "AND THE RUN IS NOT EXTRACTED" STOOD HERE AND WAS WIDER THAN THE
    #: TRUTH (withdrawn by the 22.08 measurement on MNVNK). The run is
    #: read by a SIDE STAGE: `sketch.index.json` holds
    #: `stairs_run_path_index` — 24 stairs, 48 out of 48 runs per the
    #: `OST_StairsRuns` census. The narrow half is true: the run has no
    #: row in the category table, and no one collects its WIDTH — the
    #: index carries only the path. The difference is fixed by different
    #: means: "there is no stage" would have sent someone to write the
    #: extraction again on top of something that already works. The cause
    #: sits right at the line in `extract.py`.
    ASKED = (
        "WALL_STRUCTURAL_SIGNIFICANT",
        "STAIRS_ACTUAL_NUM_RISERS",
        "STAIRS_ACTUAL_TREAD_DEPTH",
        "STAIRS_ACTUAL_RISER_HEIGHT",
        "ROOM_UPPER_OFFSET",
    )

    def _body(self) -> str:
        from kir.decompile.extract import build_category_batch_cs
        return build_category_batch_cs("OST_Walls")

    def test_each_of_the_six_is_asked_for_in_the_emitted_body(self):
        body = self._body()
        for name in self.ASKED:
            with self.subTest(параметр=name):
                self.assertIn("BuiltInParameter." + name, body)

    def test_the_probe_reads_the_body_and_not_the_universe(self):
        """CONTROL: a name we do not ask for must not be present in the body.

        Otherwise `assertIn` would pass on any sufficiently long text,
        and the previous test would be measuring length, not content.
        """
        body = self._body()
        self.assertNotIn("BuiltInParameter.__KIR_NO_SUCH_PARAMETER__", body)
        self.assertNotIn("BuiltInParameter.STAIRS_ATTR_RISER_HEIGHT", body)
        # AND THIS ONE SPECIFICALLY IS NOT ASKED FOR, BECAUSE IT CANNOT
        # ARRIVE. The claim is not empty: the line was here and was
        # withdrawn by a live measurement, so its return must turn red,
        # not slip through silently.
        self.assertNotIn("BuiltInParameter.STAIRS_ATTR_TREAD_WIDTH", body)


class КаждыйЗондОСТАВЛЯЕТ_КВИТАНЦИЮ(unittest.TestCase):
    """SCHEMA AUTHORITY TRAVELS IN EVERY EXTRACTION, NOT IN A SPECIAL PROBE.

    WHY, BY THE 20.08.2026 MEASUREMENT. A live A/B showed that probing
    costs 50-66 % of the extraction body (`OST_Dimensions`: 1.2-1.5 s out
    of 2.0 for ZERO values), that is, routing by category pays for
    itself. But the safe routing key is not "did the parameter land" (a
    fact about the project's DATA) but "does it exist on the element" — a
    fact about the SCHEMA.

    This fact was already being collected — for 16 of the 43 probes, by
    the helpers that keep a receipt (`not_applicable` = present neither
    on the instance nor on the type). The remaining 27
    (`__PutLengthParam`/`__PutIntParam`/`__PutIdParam`) wrote the value
    and stayed silent about the reason for the omission.

    The fix: all 43 were switched to the counting helpers
    (`__PutSectionIdParam` was added for ElementId), three orphaned ones
    were removed. The value is written by the same expression —
    `__PutSectionParam` and `__PutLengthParam` were byte-for-byte
    identical in the write line — only the receipt changed.

    The census's own law checks this itself: the sum of the six outcomes
    MUST equal `extracted_count` (`schema.CategoryStatus`), so a probe
    that forgets to report will bring the decompile down LOUDLY, not
    quietly.
    """

    @staticmethod
    def _lines(text):
        return text.splitlines()

    def _block(self) -> str:
        from kir.decompile.extract import build_category_batch_cs
        body = build_category_batch_cs("OST_Walls")
        start = body.index("Action<Element, Dictionary<string, object>> __PutParams")
        return body[start:body.index('__row["params"] = __params;', start)]

    def test_no_probe_is_left_without_a_receipt(self):
        import re
        block = self._block()
        counted = re.findall(
            r"__Put(SectionParam|SectionIntParam|SectionIdParam)"
            r"\(__e, __typeEl, BuiltInParameter\.", block)
        silent = re.findall(
            r"__Put(LengthParam|IntParam|IdParam)"
            r"\(__e, (?:__typeEl, )?BuiltInParameter\.", block)
        self.assertEqual(silent, [], "зонд без квитанции: причина пропуска снова "
                                     "неотличима от «параметра здесь не бывает»")
        self.assertEqual(len(counted), 43, "число зондов сдвинулось — проверь, "
                                           "что новый тоже отчитывается")
    def test_the_type_is_fetched_once_per_element_not_once_per_probe(self):
        """Before 20.08 each of the 43 probes asked
        `doc.GetElement(GetTypeId())` itself, and 82.1 % miss on the
        instance (corpus receipts, 3 661 545 probes) — that is, ~35
        document calls per element where one would suffice.

        🔴 THE WINDOW HERE IS THE WHOLE BODY, NOT THE `__PutParams`
        BLOCK, AND THIS WAS BOUGHT BY A CONTROL. The first edition
        counted lookups inside the block; the helpers are declared ABOVE
        it, so the mutation "move the lookup back inside the helper"
        left the guard GREEN. Form 28: the window is narrower than the
        subject.
        """
        from kir.decompile.extract import build_category_batch_cs
        body = build_category_batch_cs("OST_Walls")
        real = [line for line in self._lines(body)
                # The document prefix changed on 25.08 (`doc` -> `__src`):
                # the extraction body reads the SOURCE. This guard's law
                # is "one type lookup per element," and it has nothing to
                # do with the document, so we look for the call without
                # the prefix.
                if ".GetElement(__e.GetTypeId())" in line
                and not line.strip().startswith("//")]
        self.assertEqual(len(real), 1,
                         "выборка типа снова размножилась: %d мест — при 43 "
                         "зондах это ~35 лишних поисков в документе на КАЖДЫЙ "
                         "элемент" % len(real))

    def test_the_silent_helpers_are_gone_entirely(self):
        """An orphaned helper is an invitation to write another silent probe.

        🔴 THE FIRST EDITION OF THIS TEST TURNED RED ON A COMMENT. It
        searched for the bare NAME in the body, while the name sat in
        prose next to the code — form 31 in its own guard: a grep
        answers "is the line present," while the question asked was "is
        the helper defined." We search for the DEFINITION.
        """
        from kir.decompile.extract import build_category_batch_cs
        body = build_category_batch_cs("OST_Walls")
        for name in ("__PutLengthParam", "__PutIntParam", "__PutIdParam"):
            with self.subTest(помощник=name):
                self.assertNotIn("%s = (__e, __bip, __name, __params)" % name, body)


if __name__ == "__main__":
    unittest.main()
