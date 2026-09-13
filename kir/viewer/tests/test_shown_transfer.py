"""THE "SEND TO REVIT" BUTTON ON A SPLICED SCENE.

The only place where the virtual becomes real, and it signs off on WHAT
THE PERSON SAW. While the scene arrived whole, "shown" and "transferred"
matched by construction. With a splice of a base and tails, these are
two DIFFERENT computations, and any discrepancy between them is a
building the engineer never saw, built with his consent.

MEASURED COST (11.08.2026, 300 programs / 6 000 elements):

  * delta WITHOUT a signature     1.9 ms
  * delta WITH a signature        2.0 ms   (summing 20 records — 0.03 ms)
  * recomputing the signature from scratch  8.5 ms — that is what a
                                             frame would cost if we
                                             computed it not as an
                                             accumulator but over the
                                             whole scene
  * the panel, once per button press: assembling records 50 ms,
    signature 157 ms

That is, the button's transport is not broken: the signature travels as
an accumulator and stays O(new) per frame, while its full cost is paid
once, on the press.
"""

import os
import unittest

from kir.live import journal as _journal
from kir.live import showroom as _showroom
from kir.live import transfer as _transfer
from kir.viewer import live_scene as L


def _wall(oid, y):
    return {"op": "create_wall", "id": oid, "p0_mm": [0.0, y],
            "p1_mm": [9000.0, y], "height_mm": 3200.0,
            "level": {"by": "name", "value": "L1"}}


class ButtonBase(unittest.TestCase):

    DEVICE = "тест-кнопка"
    DOC = "тест-док"

    def setUp(self):
        os.environ.setdefault("KUKAI_KIR_TRANSFER", "1")
        self.key = _journal.key_for(self.DEVICE, self.DOC)
        _journal.reset(self.key)
        _showroom.forget(self.key)
        _journal.append(self.key, {"ops": [{"op": "create_level", "id": "lv",
                                            "name": "L1", "elev_mm": 0.0}]})
        _journal.append(self.key, {"ops": [_wall("w0", 0.0)]})

    def _shown(self):
        import json
        import struct
        blob, _ = L.scene_from_session(self.DEVICE, self.DOC, 0)
        head_len = struct.unpack_from("<I", blob, 8)[0]
        return json.loads(blob[12:12 + head_len].decode("utf-8"))


class TheSignatureIsOfWhatWasShown(ButtonBase):

    def test_a_matching_signature_is_ready_and_equal_to_the_transfer_one(self):
        """The equality of `requested` and `transfer` IS "what was seen
        is what gets built", expressed as an equality, not as a
        promise."""
        header = self._shown()
        decision = _transfer.authorize_scene(
            self.key, shown_digest=header["shown_digest"])
        self.assertIs(decision.status, _transfer.Status.READY)
        self.assertEqual(decision.transfer_digest, decision.requested_digest)
        self.assertEqual(decision.programs, 2)

    def test_the_scene_publishes_the_signature_it_accumulated(self):
        self.assertTrue(self._shown()["shown_digest"])
        self.assertEqual(self._shown()["shown_digest"],
                         _showroom.scene_digest(self.key))


class ADivergenceRefusesBothVersions(ButtonBase):
    """A discrepancy is a refusal, not a choice of a winner: the
    server's version was not on screen, we did not compute the panel's."""

    def test_a_foreign_signature_is_refused(self):
        """SOMEONE ELSE'S SIGNATURE AGAINST WHAT WAS SHOWN — exactly
        `shown_mismatch`.

        14.08.2026: the test was green DUE TO A LEAK. It did not show
        the scene at all, and `_showroom.forget()` cleared only the
        frames (`_ROOMS`) and did not touch the accumulated signature
        (`_SCENES`) — the signature of a NEIGHBORING test arrived here,
        and the "discrepancy" came from someone else's state. Alone, the
        test failed; in a batch, it passed; this is not a test, it is a
        reading of run order. Now the scene is shown explicitly, and
        there is no more leak — `forget` clears both stores.
        """
        self._shown()
        decision = _transfer.authorize_scene(self.key, shown_digest="0" * 64)
        self.assertIs(decision.refusal, _transfer.Refusal.SHOWN_MISMATCH)

    def test_without_anything_shown_a_foreign_signature_is_not_a_mismatch(self):
        """A CONTROL PAIR FOR THE TEST ABOVE, AND ALSO A REFUTATION OF
        THE LEAK.

        The same foreign signature, but nobody showed the scene: there
        is nothing to compare against, and the refusal must be
        DIFFERENT. If `forget` stops clearing `_SCENES` again,
        `shown_mismatch` will appear here — and the test will go red.
        """
        decision = _transfer.authorize_scene(self.key, shown_digest="0" * 64)
        self.assertIs(decision.refusal, _transfer.Refusal.NOTHING_SHOWN)

    def test_the_refusal_names_both_signatures(self):
        """A refusal that does not say what failed to match what is
        indistinguishable from a breakage."""
        header = self._shown()
        decision = _transfer.authorize_scene(self.key, shown_digest="0" * 64)
        joined = " ".join(decision.diverged)
        self.assertIn("0" * 64, joined)
        self.assertIn(header["shown_digest"], joined)
        self.assertEqual(decision.current_digest, header["shown_digest"])

    def test_an_empty_signature_is_a_mismatch_not_a_pass(self):
        """A panel that did not send a signature signed nothing.
        Letting it through would mean agreeing to the unknown."""
        self._shown()
        decision = _transfer.authorize_scene(self.key, shown_digest="")
        self.assertIs(decision.refusal, _transfer.Refusal.SHOWN_MISMATCH)

    def test_nothing_shown_is_its_own_refusal(self):
        """«Did not match» and «was not shown» are fixed by different people."""
        _showroom.forget(self.key)
        decision = _transfer.authorize_scene(self.key, shown_digest="что-то")
        self.assertIs(decision.refusal, _transfer.Refusal.NOTHING_SHOWN)

    def test_no_refusal_silently_picks_a_side(self):
        """No refusal has the right to return `READY` with a foreign signature."""
        for digest in ("", "0" * 64, "короткая"):
            decision = _transfer.authorize_scene(self.key,
                                                 shown_digest=digest)
            self.assertIsNot(decision.status, _transfer.Status.READY)


class ATailCannotBeSentAsABuilding(ButtonBase):

    def test_partial_is_refused_even_with_a_matching_signature(self):
        """A tail's signature will match itself and prove nothing by
        doing so. That is why the tail is checked FIRST."""
        header = self._shown()
        decision = _transfer.authorize_scene(
            self.key, shown_digest=header["shown_digest"], partial=True)
        self.assertIs(decision.refusal, _transfer.Refusal.PARTIAL_SCENE)

    def test_a_delta_scene_is_marked_partial_so_the_button_sees_it(self):
        """`partial` must reach the button, not stay stuck at the picture."""
        header = self._shown()
        _journal.append(self.key, {"ops": [_wall("w1", 3000.0)]})
        import json
        import struct
        blob, _ = L.scene_from_session(
            self.DEVICE, self.DOC, header["journal"]["next_seq"],
            header["base_digest"])
        head_len = struct.unpack_from("<I", blob, 8)[0]
        self.assertTrue(json.loads(blob[12:12 + head_len].decode())["partial"])


class TheSignatureIgnoresOrderButNotContent(ButtonBase):
    """FOUND BY A CHECK BEFORE DELIVERY, not after.

    A whole scene lists elements as "all bodies first, then all
    ghosts", a splice as "the base's bodies and ghosts, then the tail's
    bodies and ghosts". The building is THE SAME ONE, the order in the
    buffer differs. The first edition of the signature was a hash chain
    and declared these two buildings different; `verify_shown.mjs`
    caught this on the third check.

    Order in the buffer is a drawing detail, not a property of the
    building. That is why the signature is composed as a MULTISET (a
    sum of sha256 modulo 2^256), and it must be blind to order while
    catching everything else.
    """

    def test_the_same_elements_in_any_order_sign_the_same(self):
        key_a, key_b = ("сумма", "а"), ("сумма", "б")
        _showroom.forget(key_a)
        _showroom.forget(key_b)
        records = [b"first", b"second", b"third"]
        a = _showroom.scene_shown(key_a, records, elements=3, whole=True)
        b = _showroom.scene_shown(key_b, list(reversed(records)), elements=3,
                                  whole=True)
        self.assertEqual(a, b)

    def test_a_duplicate_element_changes_the_signature(self):
        """A SUM, not XOR: XOR would cancel a pair, and an element
        duplicated by the splice would vanish without a trace — exactly
        the defect the signature must catch."""
        key_a, key_b = ("сумма", "в"), ("сумма", "г")
        _showroom.forget(key_a)
        _showroom.forget(key_b)
        one = _showroom.scene_shown(key_a, [b"x", b"y"], elements=2, whole=True)
        two = _showroom.scene_shown(key_b, [b"x", b"y", b"y"], elements=3,
                                    whole=True)
        self.assertNotEqual(one, two)

    def test_two_identical_records_do_not_cancel(self):
        key = ("сумма", "д")
        _showroom.forget(key)
        empty = _showroom.scene_reset(key)
        pair = _showroom.scene_shown(key, [b"same", b"same"], elements=2,
                                     whole=True)
        self.assertNotEqual(pair, empty)

    def test_a_whole_scene_resets_the_accumulation(self):
        """The base replaces everything the panel held before it; the
        tail is appended. Otherwise reloading the scene would double
        the building in the signature."""
        key = ("сумма", "е")
        _showroom.forget(key)
        first = _showroom.scene_shown(key, [b"a"], elements=1, whole=True)
        _showroom.scene_shown(key, [b"b"], elements=1, whole=False)
        again = _showroom.scene_shown(key, [b"a"], elements=1, whole=True)
        self.assertEqual(first, again)

    def test_an_empty_scene_has_a_signature_of_its_own(self):
        """«Nothing is shown» is a state that has a signature. Telling
        it apart from «there is no session» must be done by a value,
        not by its absence."""
        key = ("сумма", "ж")
        _showroom.forget(key)
        self.assertEqual(_showroom.scene_digest(key), "")
        self.assertTrue(_showroom.scene_reset(key))
        self.assertNotEqual(_showroom.scene_digest(key), "")


class TheCostStaysOffTheFramePath(ButtonBase):
    """The measurement the wave was checked against: 300 programs,
    delta WITHOUT a signature 1.9 ms, WITH a signature 2.0 ms. A full
    signature recompute would cost 8.5 ms per frame — that is, the
    transport would have been fixed only to be broken again by the
    button."""

    def test_the_digest_is_accumulated_not_recomputed(self):
        import inspect
        source = inspect.getsource(_showroom.scene_shown)
        self.assertIn("scene.total", source)
        self.assertNotIn("build_program_preview", source)

    def test_a_frame_only_folds_its_own_elements(self):
        """A frame must sum EXACTLY its own records. If it touched
        someone else's, the frame's cost would again depend on the
        session's age."""
        key = ("цена", "а")
        _showroom.forget(key)
        _showroom.scene_shown(key, [b"x"] * 100, elements=100, whole=True)
        before = _showroom.scene_stats(key)["records_bytes"]
        _showroom.scene_shown(key, [b"y"] * 5, elements=5, whole=False)
        after = _showroom.scene_stats(key)["records_bytes"]
        self.assertEqual(after - before, 5)


class TheClientSideSignatureIsCheckedByNode(unittest.TestCase):
    """The signature of WHAT WAS DRAWN is computed by the panel, and
    python cannot check it.

    `verify_shown.mjs` next to this file computes the signature with
    client code over the spliced scene and cross-checks it against the
    one accumulated by the server. The match is meaningful precisely
    because the two computations are INDEPENDENT: if the panel repeated
    the server's value, the signature would mean politeness, not
    equality.
    """

    def test_the_checker_ships_with_the_tests(self):
        import pathlib
        tool = pathlib.Path(__file__).with_name("verify_shown.mjs")
        self.assertTrue(tool.exists())
        text = tool.read_text(encoding="utf-8")
        self.assertIn("shownDigest", text)
        self.assertIn("склейка == целое-после", text)

    def test_the_client_does_not_echo_the_server_value(self):
        """The panel must COMPUTE the signature, not copy it from the
        header. Otherwise it would be signing the server's intent
        instead of the result on screen."""
        import pathlib
        path = pathlib.Path("/opt/kukai-rebuild1/assets/viewer/viewer.js")
        if not path.exists():
            self.skipTest("клиентские файлы не развёрнуты")
        text = path.read_text(encoding="utf-8")
        self.assertIn("await shownDigest(data)", text)
        self.assertNotIn("shown_digest: data.header.shown_digest", text)

    def test_the_schema_string_matches_on_both_sides(self):
        """The schema string is duplicated by value so the client
        module stays free of dependencies. The duplication is
        legitimate exactly as long as a test holds it in place."""
        import pathlib
        path = pathlib.Path("/opt/kukai-rebuild1/assets/viewer/scene-data.js")
        if not path.exists():
            self.skipTest("клиентские файлы не развёрнуты")
        self.assertIn(_showroom.SCENE_SCHEMA,
                      path.read_text(encoding="utf-8"))
