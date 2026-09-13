"""``sketch_extract``'s catch-all names the BOUNDARY OF COVERAGE, not an absence.

The measurement this test was born from (12.08.2026,
`backend/data/decompile/k2_ar_rd_v7`): the stage's catch-all was sending
`element_unresolved` — a code whose contract declares "the id was not found
IN THE DOCUMENT… it may have come from a foreign decompile." A check against
L0 of the SAME run gave the opposite:

    173 ids with element_unresolved  →  ALL 173 of 173 found in L0
    PASS control  8 real ids from profile_index  →  8 of 8
    FAIL control  5 invented ids                 →  0 of 5

that is, the instrument tells them apart, and the elements exist — the stage
simply does not read them. Of the 173: **172 × OST_StairsRailing** (a
REQUESTED category, of which 31 elements were getting the honest
`profile_not_single_closed` receipt) and 1 × OST_Floors. One category, two
receipts, and the second one told an untruth about the first.

The cost of the ambiguity was measured, not reasoned about: TWO readers drew
OPPOSITE conclusions from this code, each correct relative to their own
source — one read the contract ("not in the document"), the other the
producer ("I don't read it"). It was the AUTHORITY and the PRODUCER that
diverged, not two inattentive people.

Why `PROFILE_INDEX_SCHEMA_VERSION` was NOT bumped: a version mismatch raises
`SketchPayloadError` (`sketch_extract.py:838`), so a bump would have made
every existing index unreadable at once. The shape of the split is taken
from the `HOST_KIND_UNRESOLVED` precedent: the old code REMAINS declared for
the sake of artifacts taken before the split, and new decompiles no longer
write it at this spot. An old passport is distinguishable from a new one by
construction — the new code does not occur in old artifacts at all.
"""

import unittest

from kir.decompile.side_contract import (
    SIDE_FAILURE_KINDS,
    SideFailureKind,
    SideFailureReason,
)
from kir.decompile.sketch_extract import build_sketch_extract_cs


class SketchScopeReceiptTest(unittest.TestCase):

    def _body(self) -> str:
        return build_sketch_extract_cs(["11", "22"])

    def test_catch_all_names_the_scope_boundary(self) -> None:
        """PASS CONTROL: the catch-all writes `element_not_claimed`."""
        self.assertIn('"element_not_claimed"', self._body())

    def test_catch_all_no_longer_claims_absence_from_the_document(self) -> None:
        """FAIL CONTROL: bringing the old code back into the CATCH-ALL fails
        the test.

        The discriminating assertion: `element_unresolved` must not stand
        next to `__skSeen.Contains` — that is exactly the catch-all's
        location. We check not the absence of the row across the whole
        body (the stage is entitled to write it where the id genuinely was
        not found in the document), but its absence SPECIFICALLY in the
        catch-all.
        """
        body = self._body()
        marker = "__skSeen.Contains"
        self.assertIn(marker, body, "площадка общего улова исчезла из эмиссии")
        tail = body[body.index(marker):]
        self.assertNotIn(
            '"element_unresolved"', tail,
            "общий улов снова заявляет отсутствие в документе вместо границы охвата")

    def test_the_new_reason_is_classified(self) -> None:
        """The dictionary of classes is complete by construction — a new reason must be in it."""
        self.assertEqual(
            SIDE_FAILURE_KINDS[SideFailureReason.ELEMENT_NOT_CLAIMED],
            SideFailureKind.CUT)

    def test_the_old_reason_stays_declared_for_pre_split_artefacts(self) -> None:
        """61 saved indexes carry the old code — it must remain readable."""
        self.assertEqual(
            SideFailureReason.ELEMENT_UNRESOLVED.value, "element_unresolved")
        self.assertIn(SideFailureReason.ELEMENT_UNRESOLVED, SIDE_FAILURE_KINDS)


if __name__ == "__main__":
    unittest.main()
