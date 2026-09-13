"""THE FRESHNESS FLAG MUST NOT COMPARE A VALUE AGAINST ITSELF.

Audit findings `F-198` and `F-199` (class P5-G, continuation),
`kir/live/transfer.py`.

`F-198`. When a selection produces a NEW signature, the batch is placed
into the showroom (`_showroom.show`) BEFORE `latest` is read. So `latest`
was returning the value JUST PLACED, and `stale` was always computed as
false. A stale source frame was being declared fresh — meaning the
staleness flag was dead exactly where it is needed: when selecting FROM AN
OLD frame.

Measurement before the fix (frame 1 shown, frame 2 shown on top, selection
from frame 1):

    stale = False               <- false, the frame is stale
    current_digest = e3f17594…  equal to ITS OWN transfer_digest: True

After: `stale = True`, `current_digest = e01fba92…` — the signature of the
LATEST frame.

`F-199`. Rendering and rereading a frame include `shown.context` — the held
datums (`create_level`, `create_grid`). The package that is signed and
submitted for execution carries ONLY `programs_json`. A person was seeing a
reread in which the datums were counted, while the batch that got executed
had none: the floor was leaving unnamed. The same seam as `F-284`, but on a
DIFFERENT quantity — there PROGRAMS diverge, here it is the CONTEXT.

🔴 THE PROMISE WAS REMOVED, NOT THE RECONCILIATION. Striking the context
out of the reread would mean taking away the one place that shows WHICH
FLOOR is being built on; carrying it into the package is a decision about
what travels to Revit, and it requires knowing "does the datum already
exist in the model", which KIR does not have: Revit has it. So the reread
has stayed complete and NAMES its unexecuted share as a number
(`census_not_executed`). The fork has been handed to the lead.

🔴 AN UNFIT CONTROL FOR `F-198`: "`stale` can be true". It is green on the
path WITHOUT a selection — there `transfer_digest == digest`, `show` is
never called, and `latest` is read unspoiled. The defect lives EXACTLY
where the signature is derived, and the case must be precisely that one.
"""
from __future__ import annotations

import unittest

from kir.live import showroom as SH
from kir.live import transfer as T

_LEVEL = {"op": "create_level", "id": "lv", "name": "L1", "elev_mm": 0.0}


def _wall(oid: str, y: float) -> dict:
    return {"op": "create_wall", "id": oid, "p0_mm": [0, y],
            "p1_mm": [5000, y], "height_mm": 3000,
            "level": {"by": "name", "value": "L1"}}


class СвежестьЧитаетсяДоСвоейЗаписи(unittest.TestCase):

    KEY = ("устр-свежесть", "док-свежесть")

    def setUp(self) -> None:
        SH.forget(self.KEY)
        self.addCleanup(SH.forget, self.KEY)
        self.first = SH.show(
            self.KEY, level="L1", programs=[[_wall("w0", 0)],
                                            [_wall("w1", 3000)]],
            context=[_LEVEL], census={}, seq=1, ts=1.0)

    def test_a_selection_from_a_stale_frame_says_it_is_stale(self) -> None:
        """🔴 THE SUBJECT OF F-198. A selection produces a derived
        signature — exactly the path on which the flag was dead."""
        SH.show(self.KEY, level="L1",
                programs=[[_wall("w0", 0)], [_wall("w1", 3000)],
                          [_wall("w2", 6000)]],
                context=[_LEVEL], census={}, seq=2, ts=2.0)
        d = T.authorize(self.KEY, digest=self.first.digest, selection=["w0"])
        self.assertEqual(d.status, T.Status.READY)
        self.assertTrue(d.stale, "устаревший кадр объявлен свежим")
        self.assertNotEqual(
            d.current_digest, d.transfer_digest,
            "current_digest равен собственной подписи решения — значит "
            "свежесть снова сравнивается сама с собой")

    def test_a_selection_from_the_newest_frame_is_not_stale(self) -> None:
        """🔴 THE GREEN OUTCOME. Without it, a "stale always True" edit
        would pass, and a person would stop trusting the flag
        altogether."""
        d = T.authorize(self.KEY, digest=self.first.digest, selection=["w0"])
        self.assertEqual(d.status, T.Status.READY)
        self.assertFalse(d.stale)

    def test_the_whole_frame_path_is_untouched(self) -> None:
        """A SCOPE CONTROL: without a selection the signature is not
        derived, `show` is never called, and the fix must not be allowed
        to touch this path."""
        d = T.authorize(self.KEY, digest=self.first.digest, selection=None)
        self.assertEqual(d.status, T.Status.READY)
        self.assertEqual(d.transfer_digest, self.first.digest)
        self.assertFalse(d.stale)


class ПереписьНазываетСвоюНеисполняемуюДолю(unittest.TestCase):

    KEY = ("устр-контекст", "док-контекст")

    def setUp(self) -> None:
        SH.forget(self.KEY)
        self.addCleanup(SH.forget, self.KEY)

    def _shown(self, context):
        return SH.show(self.KEY, level="L1",
                       programs=[[_wall("w0", 0)], [_wall("w1", 3000)]],
                       context=context, census={}, seq=1, ts=1.0)

    def test_the_counted_but_unexecuted_context_is_named_by_number(self) -> None:
        """🔴 THE SUBJECT OF F-199: the reread was counting datums, the
        package carried none of them."""
        shown = self._shown([_LEVEL])
        d = T.authorize(self.KEY, digest=shown.digest, selection=["w0"])
        self.assertEqual(d.census_not_executed, 1)
        self.assertIn("census_not_executed", d.to_dict())

    def test_without_context_the_census_and_the_pack_agree(self) -> None:
        """🔴 THE GREEN OUTCOME. Zero means "the reread and the package
        are about the same thing", and without this case the number would
        be "always something", i.e. noise."""
        shown = self._shown([])
        d = T.authorize(self.KEY, digest=shown.digest, selection=["w0"])
        self.assertEqual(d.census_not_executed, 0)

    def test_the_census_itself_is_not_amputated(self) -> None:
        """What was removed is the PROMISE, not the reconciliation: the
        reread must stay complete, otherwise the one place that shows
        which floor is being built on disappears."""
        shown = self._shown([_LEVEL])
        d = T.authorize(self.KEY, digest=shown.digest, selection=["w0"])
        self.assertTrue(d.census)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
