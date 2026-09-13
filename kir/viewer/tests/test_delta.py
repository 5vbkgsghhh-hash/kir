"""THE DELTA CONTRACT: the live-session transport and the "what changed" response.

THE MEASUREMENT IT WAS WRITTEN FOR (11.08.2026, pipes of 20 ops per program):

| programs | elements | TOTAL           | DELTA (+1 program)    |
|---------:|---------:|----------------:|-----------------------:|
|       10 |      200 |  15 ms /  21 KB |     2.0 ms / 9.9 KB     |
|       50 |    1 000 |  69 ms /  71 KB |     1.8 ms / 9.9 KB     |
|      150 |    3 000 | 247 ms / 197 KB |     1.8 ms / 10.0 KB    |
|      300 |    6 000 | 479 ms / 387 KB |     2.0 ms / 10.0 KB    |

The point of the table is not 479 versus 2.0, but that the delta column DOES
NOT GROW. With polling once every 1.5 s, a full rebuild ate a third of the
session's time and grew linearly; a three-hour session would end right there
because of it.
"""

import json
import struct
import unittest

from kir.live import journal as _journal
from kir.viewer import live_scene as L

SNAPSHOT = {
    "levels": [{"id": 1, "name": "L1", "elevation_mm": 0.0}],
    "pipe_types": [{"id": 30, "name": "Сталь",
                    "section": {"kind": "nominal_table",
                                "source": "PipeSegment.GetSizes",
                                "sizes": [[100.0, 114.3]]}}],
}


def _pipe(oid, y=0.0):
    return {"op": "create_pipe", "id": oid,
            "p0_mm": [0.0, y, 2800.0], "p1_mm": [12000.0, y, 2800.0],
            "diameter_mm": 100.0,
            "pipe_type": {"by": "name", "value": "Сталь"},
            "level": {"by": "name", "value": "L1"}}


def _header(blob):
    head_len = struct.unpack_from("<I", blob, 8)[0]
    return json.loads(blob[12:12 + head_len].decode("utf-8"))


def _ids(blob):
    header = _header(blob)
    base = 12 + struct.unpack_from("<I", blob, 8)[0]
    span = next(b for b in header["buffers"] if b["name"] == "ids")
    raw = blob[base + span["offset"]:
               base + span["offset"] + span["length"]].decode("utf-8")
    return raw.split("\n") if raw else []


class DeltaBase(unittest.TestCase):

    DEVICE = "тест-дельта"
    DOC = "тест-док"

    def setUp(self):
        key = _journal.key_for(self.DEVICE, self.DOC)
        _journal.reset(key)
        _journal.remember_sections(key, SNAPSHOT)
        _journal.append(key, {"ops": [{"op": "create_level", "id": "lv",
                                       "name": "L1", "elev_mm": 0.0}]})
        for i in range(3):
            _journal.append(key, {"ops": [_pipe(f"p{j}", i * 100.0 + j)
                                          for j in range(2)]})
        self.key = key

    def _full(self):
        blob, meta = L.scene_from_session(self.DEVICE, self.DOC, 0)
        return blob, meta, _header(blob)


class AStaleBaseIsRefusedNotGuessed(DeltaBase):
    """Gluing the tail onto someone else's base means showing a building that
    never existed. An empty screen is at least visible."""

    def test_a_delta_without_a_base_is_refused(self):
        """Silent acceptance of an unknown base is the same splice, just with
        laziness instead of a bug."""
        _, _, header = self._full()
        with self.assertRaises(L.StaleBase):
            L.scene_from_session(self.DEVICE, self.DOC,
                                 header["journal"]["next_seq"], "")

    def test_a_delta_with_a_foreign_base_is_refused(self):
        _, _, header = self._full()
        with self.assertRaises(L.StaleBase):
            L.scene_from_session(self.DEVICE, self.DOC,
                                 header["journal"]["next_seq"], "0" * 32)

    def test_the_refusal_names_both_digests(self):
        """A refusal must name its cause: a silent rollback is
        indistinguishable from a breakage."""
        _, _, header = self._full()
        try:
            L.scene_from_session(self.DEVICE, self.DOC,
                                 header["journal"]["next_seq"], "0" * 32)
        except L.StaleBase as exc:
            self.assertIn(header["base_digest"], str(exc))
            self.assertIn("since=0", str(exc))
        else:
            self.fail("протухшая база принята")

    def test_a_matching_base_is_accepted(self):
        _, _, header = self._full()
        _journal.append(self.key, {"ops": [_pipe("new", 999.0)]})
        blob, meta = L.scene_from_session(
            self.DEVICE, self.DOC, header["journal"]["next_seq"],
            header["base_digest"])
        self.assertTrue(_header(blob)["delta"])
        self.assertEqual(meta["honesty"]["total"], 1)


class EverythingThatCanChangeThePastInvalidatesTheBase(DeltaBase):
    """A delta is valid exactly when the past is immutable. There are exactly
    three channels through which a new program changes an OLD element, and
    the base signature must cover all three."""

    def test_a_new_datum_invalidates_it(self):
        """`create_level` sets the elevation that programs which arrived
        EARLIER reference by name."""
        before = self._full()[2]["base_digest"]
        _journal.append(self.key, {"ops": [{"op": "create_level", "id": "lv2",
                                            "name": "L2", "elev_mm": 3300.0}]})
        self.assertNotEqual(self._full()[2]["base_digest"], before)

    def test_a_new_type_snapshot_invalidates_it(self):
        """Wall thickness and pipe outer diameter come from the TYPE:
        changing the snapshot recomputes the bodies of ALL elements."""
        before = self._full()[2]["base_digest"]
        _journal.remember_sections(self.key, {"levels": [
            {"id": 9, "name": "L9", "elevation_mm": 1.0}]})
        self.assertNotEqual(self._full()[2]["base_digest"], before)

    def test_eviction_invalidates_it(self):
        """Eviction removes programs that are already drawn on the client."""
        digest_a = L.base_digest([], None, 0)
        digest_b = L.base_digest([], None, 1)
        self.assertNotEqual(digest_a, digest_b)

    def test_appending_an_ordinary_program_does_not_invalidate_it(self):
        """`ref` references under `KIR-L003` do not leave the bounds of
        their own program, so an ordinary program does not touch the past.
        If it did, a delta would be impossible in principle."""
        before = self._full()[2]["base_digest"]
        _journal.append(self.key, {"ops": [_pipe("ещё", 555.0)]})
        self.assertEqual(self._full()[2]["base_digest"], before)


class AddressesAndOriginSurviveTheSeam(DeltaBase):
    """Two ways to splice a building out of two frames of reference, and both are quiet."""

    def test_delta_addresses_equal_the_ones_the_whole_scene_would_give(self):
        """A delta that restarted numbering from `p1` would hand new
        elements addresses already occupied by old ones on the client, and
        the splice would silently SUBSTITUTE them: a body would be found,
        just the wrong one."""
        _, _, header = self._full()
        cursor, digest = header["journal"]["next_seq"], header["base_digest"]
        _journal.append(self.key, {"ops": [_pipe("p0", 777.0),
                                           _pipe("p1", 778.0)]})
        delta, _ = L.scene_from_session(self.DEVICE, self.DOC, cursor, digest)
        whole, _ = L.scene_from_session(self.DEVICE, self.DOC, 0)
        fresh = set(_ids(delta))
        self.assertTrue(fresh)
        self.assertTrue(fresh <= set(_ids(whole)),
                        f"адреса дельты не встречаются в целом: {fresh}")

    def test_the_origin_is_pinned_and_identical(self):
        """The codec writes coordinates as OFFSETS from an origin. An origin
        computed from the slice's bounding box would shift the delta by an
        amount nobody would notice, and the discrepancy would grow smoothly."""
        _, _, header = self._full()
        _journal.append(self.key, {"ops": [_pipe("далеко", 9_000_000.0)]})
        delta, _ = L.scene_from_session(
            self.DEVICE, self.DOC, header["journal"]["next_seq"],
            header["base_digest"])
        self.assertEqual(_header(delta)["origin_mm"], header["origin_mm"])

    def test_the_origin_depends_only_on_datums(self):
        """The live scene's origin must depend ONLY on what the delta does
        not change. Otherwise it would drift along with the elements."""
        self.assertEqual(L.live_origin([]), (0.0, 0.0, 0.0))
        self.assertEqual(
            L.live_origin([{"op": "create_level", "elev_mm": -8500.0},
                           {"op": "create_level", "elev_mm": 3300.0}]),
            (0.0, 0.0, -8500.0))

    def test_a_building_too_far_from_the_origin_is_named(self):
        """Beyond `FLOAT32_EXACT_MM` the millimeter stops being
        representable, and the splice would drift SUB-MILLIMETER, i.e.
        unnoticeably. The radius is verified, not promised."""
        self.assertEqual(L.FLOAT32_EXACT_MM, 16_777_216.0)
        _journal.append(self.key, {"ops": [
            _pipe("очень_далеко", 40_000_000.0)]})
        _, meta = L.scene_from_session(self.DEVICE, self.DOC, 0)
        self.assertTrue(meta["origin_overflow"])
        self.assertGreater(meta["origin_far_mm"], L.FLOAT32_EXACT_MM)

    def test_datums_ride_as_context_so_new_elements_land_on_their_level(self):
        """Without `create_level` the slice has no floor elevation, and new
        elements would land at zero: the delta would draw only the first
        floor correctly."""
        _, _, header = self._full()
        _journal.append(self.key, {"ops": [_pipe("свежая", 888.0)]})
        _, meta = L.scene_from_session(
            self.DEVICE, self.DOC, header["journal"]["next_seq"],
            header["base_digest"])
        self.assertGreaterEqual(meta["context_ops"], 1)


class PartialStaysUntilTheDeltaIsClosed(DeltaBase):
    """The lead's condition: as long as a tail is possible, it must be
    called a tail. The red banner goes away together with the last
    possibility of getting one, not before — and today a tail is possible,
    because the delta is the tail."""

    def test_a_delta_is_still_marked_partial(self):
        _, _, header = self._full()
        _journal.append(self.key, {"ops": [_pipe("ещё", 111.0)]})
        blob, _ = L.scene_from_session(
            self.DEVICE, self.DOC, header["journal"]["next_seq"],
            header["base_digest"])
        fresh = _header(blob)
        self.assertTrue(fresh["partial"])
        self.assertTrue(fresh["delta"])
        self.assertIn("ХВОСТ", fresh["partial_ru"])

    def test_a_whole_scene_is_neither_partial_nor_a_delta(self):
        header = self._full()[2]
        self.assertFalse(header["partial"])
        self.assertFalse(header["delta"])
        self.assertTrue(header["base_digest"])


class TheClientSideMergeIsCheckedByNode(unittest.TestCase):
    """The splice lives on the client and is not checked by python — but it is checked.

    `verify_merge.mjs` next to this file cross-checks the splice against the
    whole scene ELEMENT BY ELEMENT: geometry through the slot (exactly the
    way the renderer will take it), both honesty axes, the graph axes, and
    the row tables. An error in slot shift drops nothing — it shows an
    element SOMEONE ELSE'S body, and the building stays plausible; only
    equality catches such an error.

    What is held here is exactly what can be held in python: the instrument
    exists and lives in the tree, not in the /tmp of a single run.
    """

    def test_the_checker_ships_with_the_tests(self):
        import pathlib
        tool = pathlib.Path(__file__).with_name("verify_merge.mjs")
        self.assertTrue(tool.exists())
        text = tool.read_text(encoding="utf-8")
        self.assertIn("mergeScenes", text)
        self.assertIn("ВЫДУМАЛА", text)

    def test_the_merge_module_has_no_dom_or_three_dependency(self):
        """`scene-data.js` was factored out of `viewer.js` specifically so
        it could be run under node. Importing three.js would send it right
        back into the unverifiable.

        🔴 THE INSTRUMENT WAS FIXED ON 14.08.2026, TWO DEFECTS AT ONCE — and
        both are our favorites.

        FIRST: `assertNotIn("three", text)` searched for a WORD, not a
        dependency. The module's own header says "no DOM and no three.js" —
        and the test went red on its own comment, reporting nothing about
        actual dependencies. A label instead of a branch: the instrument
        lied both ways, because `// three.js is not needed` colors it the
        same as a real import.

        SECOND: it read PROD (`/opt/kukai-rebuild1/...`), not the tree it
        itself lives in. On someone else's machine it was silently skipped,
        and here it checked a file that might not exist in the branch at
        all — that is, it was reporting on a NEIGHBORING copy. Its own file
        is looked up from `__file__`; prod remains a fallback path and is
        NAMED when used.
        """
        import re
        # 🔴 THE ADDRESS BELONGS TO ONE CARRIER (`_client_asset`), NOT A STEP COUNT.
        # `parents[4]` was computed for the `backend/kukai/ir/viewer/tests`
        # layout, and after the split it flew past the root: `own.exists()`
        # was ALWAYS false, so a fix already made once — "own, otherwise
        # prod" — silently reverted, and the instrument went back to
        # reading PROD while staying green.
        from kir.viewer.tests._client_asset import scene_data_js
        path, откуда = scene_data_js()
        if path is None:
            self.skipTest(откуда)
        text = path.read_text(encoding="utf-8")
        # Comments are stripped: the dependency lives in the CODE, and it
        # must be judged by the code. String literals stay — `import("three")`
        # is also a dependency.
        code = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
        code = re.sub(r"(?m)//.*$", "", code)
        for bad in ("three", "document", "window", "requestAnimationFrame"):
            self.assertNotIn(bad, code,
                             f"{path} тянет {bad!r} — модуль перестал быть "
                             "проверяемым в node")
        # PASS CONTROL: the stripping did not eat the whole file, otherwise
        # the check would be green by construction.
        self.assertIn("mergeScenes", code)


class TheCompletenessFlagSurvivesTheMerge(DeltaBase):
    """🔴 "TAIL" IS A PROPERTY OF THE ACCUMULATED STATE, NOT OF THE LAST RESPONSE.

    FOUND ON 16.08.2026 ON THE OWNER'S LIVE TURN, and the price was the
    whole product. He asked for a 4x4 box, saw it in the KIR window, pressed
    "Send to Revit" and got: "on screen there's a TAIL of the journal, not a
    building: part of the programs did not make it into this scene." His
    verbatim reaction: "as a human I genuinely cannot understand why, or
    what's wrong."

    Both halves were right on their own. The server sets `partial = since >
    0` (`live_scene.py:243`) and tells the truth ABOUT ITS OWN BYTES. The
    button reads `data.header.partial` and asks about the SCENE. Between
    them stood `mergeScenes`, which took the header wholesale from the
    delta — and the truth about the response became a lie about the scene.
    This project's named defect, verbatim: a value is ASSERTED in one
    place, READ in another, and nothing forces them to agree.

    THE PRICE IS BY CONSTRUCTION, NOT BY BAD LUCK. A live session starts
    with the `since=0` frame, then deltas follow; the VERY FIRST delta —
    even an empty one, even "nothing new" — set the flag forever. Transfer
    to Revit was dead for anyone who kept the window open longer than one
    poll.

    WHY IT IS CHECKED IN NODE, NOT IN PYTHON. The splice lives on the
    client, and python does not execute it. The instrument next to it
    (`verify_merge.mjs`) checks the GEOMETRY of the splice and is not
    concerned with this question; here there is exactly one value —
    honesty about completeness. This test lays down the blobs itself: an
    instrument whose inputs nobody prepares never gets run —
    `verify_merge.mjs` lives in exactly that state, its python companion is
    promised by the docstring and is absent from the tree.
    """

    def _blobs(self, into):
        """The base (`since=0`) and the tail (`since>0`) — BY PROD CODE, not by hand.

        Form 27: a test that builds its input by hand is green on a form
        that prod does not produce.
        """
        base, _, header = self._full()
        _journal.append(self.key, {"ops": [_pipe("хвост", 777.0)]})
        delta, _ = L.scene_from_session(
            self.DEVICE, self.DOC, header["journal"]["next_seq"],
            header["base_digest"])
        (into / "d_base.bin").write_bytes(base)
        (into / "d_delta.bin").write_bytes(delta)

    def _run_node(self, module_path):
        import pathlib
        import subprocess
        import tempfile
        tool = pathlib.Path(__file__).with_name("verify_partial.mjs")
        self.assertTrue(tool.exists(), "прибор не приехал вместе с тестом")
        with tempfile.TemporaryDirectory() as tmp:
            into = pathlib.Path(tmp)
            self._blobs(into)
            return subprocess.run(
                ["node", str(tool), str(into), str(module_path)],
                capture_output=True, text=True, timeout=120)

    def _module(self):
        import pathlib
        import shutil
        if shutil.which("node") is None:
            self.skipTest("node не установлен — прибор не запускался")
        # The same single address carrier as its neighbor in the file.
        from kir.viewer.tests._client_asset import scene_data_js
        own, откуда = scene_data_js()
        if own is None:
            self.skipTest(откуда)
        return own

    def test_a_whole_scene_plus_a_tail_is_still_whole(self):
        proc = self._run_node(self._module())
        self.assertEqual(proc.returncode, 0,
                         f"\n{proc.stdout}\n{proc.stderr}")
        self.assertIn("склейка целого с хвостом — не хвост", proc.stdout)

    def test_the_instrument_reddens_on_the_broken_merge(self):
        """A FAIL CONTROL, AND IT IS BEHAVIORAL, NOT "SYMBOL MISSING".

        The REAL module is taken, and exactly the previous behavior is
        restored in it — the header taken wholesale from the delta. A green
        instrument that cannot turn red is not an instrument; six of those
        were found on this tree in one evening.
        """
        import pathlib
        import re
        import tempfile
        module = self._module()
        text = module.read_text(encoding="utf-8")
        broken = re.sub(
            r"\n\s*partial: partial,\n\s*partial_ru: \(partial.*?\),\n",
            "\n", text, flags=re.S)
        self.assertNotEqual(broken, text, "мутация не нашла своё место")
        with tempfile.TemporaryDirectory() as tmp:
            hurt = pathlib.Path(tmp) / "scene-data.js"
            hurt.write_text(broken, encoding="utf-8")
            proc = self._run_node(hurt)
        self.assertEqual(proc.returncode, 1,
                         f"прибор не покраснел на сломанной склейке:"
                         f"\n{proc.stdout}\n{proc.stderr}")
        self.assertIn("Кнопка переноса мертва по построению", proc.stdout)
