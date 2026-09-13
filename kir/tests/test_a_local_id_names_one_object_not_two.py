"""ONE NAME WAS SELECTING TWO OBJECTS, AND NOT A SINGLE DIAGNOSTIC (HR-03).

The subject is `kir/live/transfer.py`, selection resolution. The set of
known addresses was collected FLAT across the whole bundle:

    known = {str(op.get("id")) for program in programs for op in program ...}

and this same set was passed into `closure(program, ...)` for EVERY
program. A local `id` is unique only WITHIN a program — the compiler rule
`KIR-L003` ("a ref points to an earlier op of THE SAME program") makes a
name collision between programs LEGITIMATE, not corruption.

MEASURED BEFORE (04.09.2026). Two programs, each with its own legitimate
`W1` (the first at y=0, the second at y=5000), selection `["W1"]`:

    status                     needs_confirm
    refusal                    None
    programs in the bundle issued   2
    WALLS UNDER ONE NAME       2   (y = 0.0 and 5000.0)
    diagnostics                NONE AT ALL

A person selected ONE object, and two resolved for transfer. There was
nothing to name this with, by construction too: the `added` list enumerates
what was PULLED IN by references, and the second `W1` was not pulled in —
it arrived as the selection itself.

MEASURED AFTER: an ambiguous name is a typed refusal `SELECTION_AMBIGUOUS`,
0 walls are issued, the refusal names "`W1` — in programs p1/W1, p2/W1".
A bundle-scale address resolves the same selection unambiguously: `p1/W1`
-> one wall at y=0, `p2/W1` -> one wall at y=5000.

NO SECOND ADDRESS FORMAT WAS INTRODUCED. The bundle scale is already named
in the tree — `clash_bundle.bundle_oid` gives `p1/W1`, and it is exactly
this that `viewer.live_scene._qualify` uses to qualify the scene before
display. The separator is not hardcoded here as a string: it is taken from
`bundle_oid(position, "")`, so no copy of the format appeared.

🔴 THE CONTROL WITHOUT WHICH THIS SET PROVES NOTHING is below
(`test_control_an_unambiguous_local_id_still_selects_one`). A fix that
simply BANNED raw local ids would pass every check about ambiguity and
would break the panel's one and only live path: today it sends exactly a
raw `id` (`kir/tests/test_kir_transfer.py` calls `selection=["D3"]`). An
unambiguous name must keep working exactly as before.
"""
from __future__ import annotations

import os
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_test_queue.jsonl"))

from kir.clash_bundle import bundle_oid          # noqa: E402
from kir.live import showroom as SR              # noqa: E402
from kir.live import transfer as T               # noqa: E402

KEY = ("dev-hr03", "")
LEVEL = {"op": "create_level", "id": "LV", "elev_mm": 0.0, "name": "Этаж 1"}


def стена(oid: str, y: float) -> dict:
    return {"op": "create_wall", "id": oid, "p0_mm": [0.0, y],
            "p1_mm": [6000.0, y], "level": {"by": "ref", "value": "LV"}}


def дверь(oid: str, host: str) -> dict:
    return {"op": "create_door", "id": oid, "offset_mm": 3000.0,
            "host": {"by": "ref", "value": host}}


class _База(unittest.TestCase):

    def setUp(self) -> None:
        SR.reset()

    def tearDown(self) -> None:
        SR.reset()

    def показать(self, programs):
        entry = SR.show(KEY, level="Этаж 1", programs=programs, context=[LEVEL])
        self.assertIsNotNone(entry, "витрина обязана принять кодируемую пачку")
        return entry

    def стены(self, decision) -> list[float]:
        """The ordinates of walls RESOLVED for transfer. Counted from the
        body taken from the showroom, not from the decision's fields: what
        is resolved is exactly what the showroom hands over."""
        if not decision.transfer_digest:
            return []
        pack = T.redeem(KEY, decision.transfer_digest) or []
        return [op["p0_mm"][1] for program in pack for op in program
                if op.get("op") == "create_wall"]


class AnAmbiguousLocalIdIsRefused(_База):

    #: Two programs, EACH with its own legitimate `W1`.
    def пачка(self):
        return [[LEVEL, стена("W1", 0.0)], [LEVEL, стена("W1", 5000.0)]]

    def test_one_name_never_selects_two_objects(self) -> None:
        """The whole defect, in one number: there were 2 walls, now there are 0 and a refusal."""
        entry = self.показать(self.пачка())
        d = T.authorize(KEY, digest=entry.digest, selection=["W1"])
        self.assertIs(d.status, T.Status.REFUSED)
        self.assertIs(d.refusal, T.Refusal.SELECTION_AMBIGUOUS)
        self.assertEqual(self.стены(d), [],
                         "молчаливый выбор двух объектов вернулся")

    def test_the_refusal_names_where_the_name_was_found(self) -> None:
        """The refusal must NAME, not apologize: exactly which programs the
        name occurred in — otherwise a person has nothing to build an exact
        address from."""
        entry = self.показать(self.пачка())
        d = T.authorize(KEY, digest=entry.digest, selection=["W1"])
        назвал = " ".join(d.diverged)
        self.assertIn("W1", назвал)
        self.assertIn(bundle_oid(1, "W1"), назвал)
        self.assertIn(bundle_oid(2, "W1"), назвал)
        self.assertIn("p1/W1", d.refusal_ru + назвал,
                      "человеку не показан формат, которым спор снимается")

    def test_the_bundle_address_resolves_it_to_exactly_one(self) -> None:
        """And the dispute is resolved WITHOUT a second frame: by the very
        address the scene already labels its elements with. `p1` and `p2`
        must give DIFFERENT walls — otherwise the address qualifies the
        wrong thing."""
        entry = self.показать(self.пачка())
        первая = T.authorize(KEY, digest=entry.digest,
                             selection=[bundle_oid(1, "W1")])
        self.assertIsNot(первая.status, T.Status.REFUSED)
        self.assertEqual(self.стены(первая), [0.0])

        entry = self.показать(self.пачка())
        вторая = T.authorize(KEY, digest=entry.digest,
                             selection=[bundle_oid(2, "W1")])
        self.assertIsNot(вторая.status, T.Status.REFUSED)
        self.assertEqual(self.стены(вторая), [5000.0])

    def test_an_address_of_a_program_without_that_id_is_unknown(self) -> None:
        """`p9/W1` is not "ambiguous" but "no such thing exists": two
        different cures, and they must not be confused (the same argument
        by which `NOTHING_SHOWN` is kept separate from `SHOWN_MISMATCH`)."""
        entry = self.показать(self.пачка())
        d = T.authorize(KEY, digest=entry.digest, selection=["p9/W1"])
        self.assertIs(d.status, T.Status.REFUSED)
        self.assertIs(d.refusal, T.Refusal.SELECTION_UNKNOWN)

    def test_an_address_pointing_at_the_wrong_program_is_unknown(self) -> None:
        """The position exists, the name does not exist in THAT program.
        Taking it from a neighboring one would mean bringing back exactly
        HR-03 through a qualified door."""
        entry = self.показать([[LEVEL, стена("W1", 0.0)],
                               [LEVEL, стена("W2", 5000.0)]])
        d = T.authorize(KEY, digest=entry.digest,
                        selection=[bundle_oid(1, "W2")])
        self.assertIs(d.status, T.Status.REFUSED)
        self.assertIs(d.refusal, T.Refusal.SELECTION_UNKNOWN)


class TheOldPathIsNotBroken(_База):
    """🔴 CONTROL. The same input with ONE condition changed — the name is
    unique within the bundle — and everything must work exactly as before
    the fix."""

    def test_control_an_unambiguous_local_id_still_selects_one(self) -> None:
        entry = self.показать([[LEVEL, стена("W1", 0.0)],
                               [LEVEL, стена("W2", 5000.0)]])
        d = T.authorize(KEY, digest=entry.digest, selection=["W2"])
        self.assertIsNot(d.status, T.Status.REFUSED)
        self.assertEqual(self.стены(d), [5000.0])

    def test_control_a_single_program_pack_is_untouched(self) -> None:
        """A bundle of a single program does not even know about a bundle scale."""
        entry = self.показать([[LEVEL, стена("W1", 0.0)]])
        d = T.authorize(KEY, digest=entry.digest, selection=["W1"])
        self.assertIsNot(d.status, T.Status.REFUSED)
        self.assertEqual(self.стены(d), [0.0])

    def test_control_a_truly_unknown_id_is_still_unknown(self) -> None:
        entry = self.показать([[LEVEL, стена("W1", 0.0)]])
        d = T.authorize(KEY, digest=entry.digest, selection=["W9"])
        self.assertIs(d.refusal, T.Refusal.SELECTION_UNKNOWN)

    def test_control_the_closure_still_grows_within_its_program(self) -> None:
        """The closure was not lost by the fix: the door still pulls in its
        own wall — and specifically ITS OWN, from its own program, not the
        same-named neighbor."""
        entry = self.показать([[LEVEL, стена("W1", 0.0)],
                               [LEVEL, стена("W1", 5000.0), дверь("D3", "W1")]])
        d = T.authorize(KEY, digest=entry.digest,
                        selection=[bundle_oid(2, "D3")])
        self.assertIs(d.status, T.Status.NEEDS_CONFIRM)
        # A door pulls in a wall, a wall pulls in its own level: the
        # closure follows the graph, not just one step.
        self.assertEqual(sorted(a.op_id for a in d.added), ["LV", "W1"])
        self.assertEqual(self.стены(d), [5000.0],
                         "замыкание притянуло одноимённую стену чужой программы")


if __name__ == "__main__":
    unittest.main()
