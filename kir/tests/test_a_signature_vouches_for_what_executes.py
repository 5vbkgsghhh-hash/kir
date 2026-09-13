"""THE SIGNATURE MUST GUARANTEE WHAT WILL BE EXECUTED, NOT WHAT WAS DRAWN.

Audit findings `F-284` and `F-196` (defect class core П5-Г), `kir/live/showroom.py`,
`kir/viewer/live_scene.py`, `kir/live/transfer.py`.

The "Send to Revit" button was built like this:

    WHAT IS SIGNED                    WHAT WILL EXECUTE
    a signature of WHAT WAS DRAWN     THE ENTIRE SESSION JOURNAL
    (showroom, accumulated records)   (session.records, read AGAIN)
             |                                  |
             +-----------  NOTHING  ------------+
                     connected them

`_authorize_scene` first honestly makes sure the panel saw the same thing the
server showed — and THEN goes to the journal for the package and takes
EVERYTHING lying there RIGHT NOW. Between rendering and clicking, the journal
could have grown. A measurement on live prod code BEFORE the fix:

    SHOWN: programs 2  signature 118e6045589cf07e
    authorize BEFORE the append   : ready  programs 2  ops 2
    a 3rd program appended WITHOUT REDRAWING
    scene signature now : 118e6045589cf07e   THE SAME: True
    authorize AFTER the append: ready  programs 3  ops 3
    what will ship to Revit: ['lv', 'w0', 'NOT-SHOWN']

A wall at address `NOT-SHOWN` was shipping to Revit under a signature issued
BEFORE it appeared, and the status was `ready`, not a refusal. The cost of
the bug here is not "a wrong number in the report" but "showed one thing,
built another."

THE CURE IS ONE RULE: the signature carries the JOURNAL REVISION it was taken
at (`_Scene.upto_seq`), and authorization clips the package to that revision.

🔴 THE SECOND HALF OF `F-284`: record coordinates are RELATIVE to the scene's
origin, and the origin itself was not part of the signature. Shifting the
origin and the content by the same amount gave THE SAME signature under
DIFFERENT executable coordinates. The origin is placed as the frame's service
record — not in an element's record, otherwise the multiset property would
collapse (identical records must add up).

🔴 A REFUSAL, NOT A SILENT TRUNCATION — a fork in the road, named to the
lead. Truncation would build what was shown and stay silent about what was
appended; a refusal forces a redraw and another click. A refusal costs one
extra round-trip and is honest by a whole class: it holds "what I see is what
gets built" in BOTH directions, while silently building LESS than what was
shown is just as much a lie as building more.

🔴 AN UNFIT CONTROL THAT SUGGESTS ITSELF HERE: "the server's and the panel's
signatures are equal." GREEN TODAY — that is exactly the check already
sitting in the code, and it let the defect through. The discriminator holds
the signature UNCHANGED and looks at the PACKAGE'S SIZE.

The guard is END-TO-END (journal -> scene -> showroom -> authorize_scene),
not a unit test on `_Scene`: the defect lives EXACTLY in the seam between the
four modules, and any one of them alone is correct today.
"""
from __future__ import annotations

import json
import struct
import unittest

from kir.live import journal as J
from kir.live import showroom as SH
from kir.live import transfer as T
from kir.viewer import live_scene as L

_LEVEL = {"op": "create_level", "id": "lv", "name": "L1", "elev_mm": 0.0}


def _wall(oid: str, y: float) -> dict:
    return {"op": "create_wall", "id": oid, "p0_mm": [0, y],
            "p1_mm": [5000, y], "height_mm": 3000,
            "level": {"by": "name", "value": "L1"}}


def _shown_digest(blob: bytes) -> str:
    size = struct.unpack_from("<I", blob, 8)[0]
    return json.loads(blob[12:12 + size].decode())["shown_digest"]


class ПодписьРучаетсяЗаПакет(unittest.TestCase):

    DEV, DOC = "устр-сторож", "док-сторож"

    def setUp(self) -> None:
        self.key = J.key_for(self.DEV, self.DOC)
        J.reset(self.key)
        self.addCleanup(J.reset, self.key)
        J.append(self.key, {"ops": [_LEVEL]})
        J.append(self.key, {"ops": [_wall("w0", 0)]})
        blob, _meta = L.scene_from_session(self.DEV, self.DOC, 0)
        self.shown = _shown_digest(blob)

    def _authorize(self):
        return T.authorize_scene(self.key, shown_digest=self.shown,
                                 partial=False)

    def test_what_was_shown_is_still_authorized(self) -> None:
        """🔴 A PASS CONTROL, AND IT COMES FIRST. An instrument that always
        refuses turns green on half the checks below and guards nothing."""
        d = self._authorize()
        self.assertEqual(d.status, T.Status.READY)
        self.assertEqual((d.programs, d.ops), (2, 2))

    def test_a_program_appended_after_the_frame_is_not_authorized(self) -> None:
        """🔴 THE SUBJECT OF THE FINDING. The signature STAYS THE SAME here —
        the check is aimed at the PACKAGE'S SIZE, not at signature
        equality."""
        J.append(self.key, {"ops": [_wall("НЕ-ПОКАЗЫВАЛИ", 9000)]})
        self.assertEqual(SH.scene_digest(self.key), self.shown,
                         "подпись обязана остаться той же — иначе проверка "
                         "ловит не тот предмет")
        d = self._authorize()
        self.assertEqual(d.status, T.Status.REFUSED)
        self.assertEqual(d.refusal, T.Refusal.SHOWN_MISMATCH)
        joined = " ".join(d.diverged)
        self.assertIn("показано программ: 2", joined)
        self.assertIn("в журнале сейчас: 3", joined)
        self.assertIn("дописано после отрисовки: 1", joined)

    def test_redrawing_authorizes_the_new_program(self) -> None:
        """THE GREEN OUTCOME AFTER A REFUSAL: redraw — and you may proceed.
        Without it, the refusal would be a dead end, not just one extra
        round-trip."""
        J.append(self.key, {"ops": [_wall("w1", 9000)]})
        blob, _ = L.scene_from_session(self.DEV, self.DOC, 0)
        again = _shown_digest(blob)
        d = T.authorize_scene(self.key, shown_digest=again, partial=False)
        self.assertEqual(d.status, T.Status.READY)
        self.assertEqual((d.programs, d.ops), (3, 3))

    def test_the_signature_carries_the_revision_it_vouches_for(self) -> None:
        """The revision is not decoration: it is precisely what ties the
        signature to the journal."""
        self.assertEqual(SH.scene_upto_seq(self.key),
                         J.get(self.key).next_seq)
        self.assertGreater(SH.scene_upto_seq(self.key), 0)

    def test_the_revision_only_moves_forward(self) -> None:
        """A tail taken at an older revision must not push the guarantee
        backward."""
        SH.scene_shown(self.key, [b"tail"], elements=1, whole=False,
                       upto_seq=1)
        self.assertEqual(SH.scene_upto_seq(self.key), 2)


class НачалоСценыВходитВПодпись(unittest.TestCase):
    """The second half of F-284."""

    def test_the_same_records_at_a_different_origin_sign_differently(self) -> None:
        """🔴 THE SUBJECT: shifting the origin and the content by the same
        amount gave THE SAME signature under DIFFERENT executable
        coordinates."""
        a = J.key_for("о-1", "д-1")
        b = J.key_for("о-2", "д-2")
        self.addCleanup(SH.scene_reset, a)
        self.addCleanup(SH.scene_reset, b)
        one = SH.scene_shown(a, [b"rec"], elements=1, whole=True,
                             origin_mm=(0.0, 0.0, 0.0))
        two = SH.scene_shown(b, [b"rec"], elements=1, whole=True,
                             origin_mm=(1000.0, 0.0, 0.0))
        self.assertNotEqual(one, two)

    def test_the_same_origin_still_signs_the_same(self) -> None:
        """🔴 THE GREEN OUTCOME. Without it, a fix that "mixes in whatever"
        would pass: the signature must remain A FUNCTION of what was shown,
        not a random value."""
        a = J.key_for("о-3", "д-3")
        b = J.key_for("о-4", "д-4")
        self.addCleanup(SH.scene_reset, a)
        self.addCleanup(SH.scene_reset, b)
        self.assertEqual(
            SH.scene_shown(a, [b"rec"], elements=1, whole=True,
                           origin_mm=(7.0, 8.0, 9.0)),
            SH.scene_shown(b, [b"rec"], elements=1, whole=True,
                           origin_mm=(7.0, 8.0, 9.0)))

    def test_the_origin_is_counted_once_no_matter_how_many_frames(self) -> None:
        """🔴 MY OWN REGRESSION, CAUGHT BY SOMEONE ELSE'S GUARD. The first
        draft added the origin into the sum on EVERY frame: a whole gave one
        addition, while base+tail gave two, and the signature started
        depending on the DELIVERY PATH. Caught by
        `viewer/tests/test_a_tail_is_signed_as_the_glued_scene`. The origin
        is a property of the SCENE, not of the frame, and enters the sum
        exactly once.
        """
        whole = J.key_for("о-7", "д-7")
        split = J.key_for("о-8", "д-8")
        self.addCleanup(SH.scene_reset, whole)
        self.addCleanup(SH.scene_reset, split)
        one = SH.scene_shown(whole, [b"a", b"b"], elements=2, whole=True,
                             origin_mm=(100.0, 200.0, 0.0))
        SH.scene_shown(split, [b"a"], elements=1, whole=True,
                       origin_mm=(100.0, 200.0, 0.0))
        two = SH.scene_shown(split, [b"b"], elements=1, whole=False,
                             origin_mm=(100.0, 200.0, 0.0))
        self.assertEqual(one, two,
                         "подпись поехала за путём доставки: та же геометрия, "
                         "два пути, разные подписи")

    def test_records_still_form_a_multiset(self) -> None:
        """The origin is deliberately placed as a SEPARATE frame record: in
        an element's record it would break the multiset property the whole
        accumulator rests on (identical records must add up, order does not
        matter)."""
        a = J.key_for("о-5", "д-5")
        b = J.key_for("о-6", "д-6")
        self.addCleanup(SH.scene_reset, a)
        self.addCleanup(SH.scene_reset, b)
        self.assertEqual(
            SH.scene_shown(a, [b"x", b"y"], elements=2, whole=True,
                           origin_mm=(0.0, 0.0, 0.0)),
            SH.scene_shown(b, [b"y", b"x"], elements=2, whole=True,
                           origin_mm=(0.0, 0.0, 0.0)))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
