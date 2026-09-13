"""THE SCENE CACHE: a cold open pays the first one, not every one.

MEASURED 11.08.2026, `демо-v3` with the graph layer, BY STAGE (19.7 s in
that run):

    L0 #1 (read_decompile)            4.45 s   22.6 %
    L1 (tree.json)                    3.60 s   18.3 %
    graph_from_l0                     3.28 s   16.6 %
    L0 #2 (ONLY for the graph)        3.20 s   16.2 %
    hulls (build_from_elements)       2.32 s   11.8 %
    graph_view                        1.86 s    9.4 %
    codec (packing)                   0.99 s    5.0 %

The breakdown CANCELED the hypothesis it was undertaken with: the second
pass over L0 is 16.2 %, not "the cause". An interface to `decompile` would
have removed one-sixth of the trouble.

Through the route, `демо-v3`: cold 18.05 s -> warm 0.011 s, that is, 1640x.
This is legitimate because the scene's BODY is deterministic: two builds in
a row gave byte-for-byte identical 5 154 042 bytes, and exactly five header
fields differed — stopwatch readings that are supposed to differ.
"""

import os
import pathlib
import tempfile
import pathlib
import unittest

from kir.viewer import cache as C


def _run_dir(name="sob62_fas_r23_v19"):
    from kir.viewer.scene import run_root
    return run_root() / name


def _skip_without_corpus(case) -> None:
    """🔴 THE CACHE KEY IS MEASURED ON A REAL DECOMPILE — OR NOT MEASURED AT
    ALL (28.08.2026).

    Every check below builds the key from the decompile's directory.
    Without the corpus, the directory is not addressable at all
    (`install_root()` is empty — see `KIR_PLAN.md`, gate 2), and `key_for`
    honestly returns an empty string. The claims "the format version is
    part of the key" and "reading the decompile does not change the key"
    were thereby turning into `TypeError: NoneType is not iterable` and
    `'' == ''` — a refusal ABOUT US, in the voice of a finding about the
    cache.

    The reason is asked from the same authority that knows it
    (`scene.corpus_unreachable_reason`), not made up here: "I looked and
    found nothing" and "this does not exist" are one phrase and different
    facts.
    """
    from kir.viewer.scene import corpus_unreachable_reason

    reason = corpus_unreachable_reason()
    if reason:
        case.skipTest("корпус разборов недостижим: " + reason)
    if not _run_dir().is_dir():
        case.skipTest(f"разбора «{_run_dir().name}» нет в корпусе — "
                      f"ключ кэша меряется на настоящем разборе")


class TheKeyCoversEverythingThatChangesTheAnswer(unittest.TestCase):
    """A REQUIREMENT FROM SOMEONE ELSE'S BURN. The clash cache's key failed
    three times over to cover what changes the answer: a raised cap
    returned the OLD refusal."""

    def setUp(self) -> None:
        _skip_without_corpus(self)

    def test_the_inputs_are_a_list_not_a_silent_hash(self):
        """A hash looks equally convincing with the full set of inputs and
        with half of them. The hole is visible only in a list."""
        inputs = C.key_inputs("проба", _run_dir())
        self.assertIsInstance(inputs, list)
        self.assertTrue(any(i.startswith("version=") for i in inputs))
        self.assertTrue(any(i.startswith("run=") for i in inputs))
        self.assertTrue(any(i.startswith("graph=") for i in inputs))

    def test_the_graph_flag_is_in_the_key_because_it_changes_content(self):
        """With the graph, elements get `materialized`/`declared`, without
        it — `unknown`. A cache with no flag would hand a gray building to
        someone who turned the graph on."""
        previous = os.environ.get("KUKAI_IR_BUILDING_GRAPH")
        try:
            os.environ.pop("KUKAI_IR_BUILDING_GRAPH", None)
            off = C.key_for("проба", _run_dir())
            os.environ["KUKAI_IR_BUILDING_GRAPH"] = "1"
            self.assertNotEqual(C.key_for("проба", _run_dir()), off)
        finally:
            if previous is None:
                os.environ.pop("KUKAI_IR_BUILDING_GRAPH", None)
            else:
                os.environ["KUKAI_IR_BUILDING_GRAPH"] = previous

    def test_the_format_version_is_in_the_key(self):
        """When the codec changes, every record must go stale, or the
        client will get yesterday's format for today's decompile."""
        self.assertIn(f"version={C.CACHE_VERSION}",
                      C.key_inputs("проба", _run_dir()))

    def test_an_unreadable_directory_gives_no_key_at_all(self):
        """No key — the cache must miss, not hand back a record justified
        by no one knows what."""
        self.assertIsNone(C.key_inputs("нет", pathlib.Path("/нет/такого")))
        self.assertEqual(C.key_for("нет", pathlib.Path("/нет/такого")), "")


class TheKeyCoversNothingThatDoesNot(unittest.TestCase):
    """A TEST THAT REFUTES ITS OWN KEY, AND THE BUG WAS A MIRROR IMAGE.

    The clash cache's key did NOT COVER what changes the answer. Here it
    COVERED what does NOT change the answer: `.last_access` — the access
    timestamp that `snapshot_io.touch_last_access` sets on every read of a
    decompile file.

    Measured: open the "plan versus volume" panel (it calls
    `preview_snapshot`) — and the key changed from
    26243642fc0a722a9229 to ebe15ccec14bdfd05399. The cache stopped hitting
    FOREVER for anyone who used the reconciliation, and it stopped
    SILENTLY: it looked like it was working, it just rebuilt from scratch
    every time.

    A key that covers too much breaks the cache; a key that covers too
    little breaks correctness. Both errors are about the same thing: the
    set of inputs must be EXACTLY the set of what changes the answer.
    """

    def setUp(self) -> None:
        _skip_without_corpus(self)

    def test_the_access_marker_is_not_an_input(self):
        inputs = C.key_inputs("проба", _run_dir())
        self.assertFalse([i for i in inputs if ".last_access" in i])

    def test_reading_the_run_does_not_change_the_key(self):
        from kir import preview as P
        before = C.key_for("проба", _run_dir())
        P.preview_snapshot(_run_dir())
        self.assertEqual(C.key_for("проба", _run_dir()), before)

    def test_the_marker_name_comes_from_its_owner(self):
        """A copy of the name kept separately would drift apart on a rename
        and bring the defect back silently."""
        import inspect
        self.assertIn("LAST_ACCESS_MARKER", inspect.getsource(C._not_inputs))


class AStaleEntryIsRefusedNotServed(unittest.TestCase):
    """A cached scene of a building that has been rebuilt is a building
    that does not exist. A refusal and a rebuild, not a quiet handout of
    the old one."""

    # 🔴 THIS CLASS DOES NOT NEED THE CORPUS — A MEASUREMENT, NOT AN OPINION
    # (29.08.2026). Not a single assertion in the class touches `_run_dir()`:
    # everything lives in a temp directory. The `_skip_without_corpus`
    # binding stood in `setUp` for ALL SIX classes in the file and
    # extinguished eight checks at once — among them the F-268/269/270
    # guards. The classes that ACTUALLY need a decompile
    # (`TheKeyCoversEverythingThatChangesTheAnswer`,
    # `TheKeyCoversNothingThatDoesNot` — they build the key FROM THE
    # DECOMPILE'S DIRECTORY) keep the binding.

    def test_touching_an_input_invalidates_the_key(self):
        """🔴 REWRITTEN 20.08: THIS TEST USED TO EDIT THE LIVE CORPUS.

        It ran `os.utime` on `sob62_fas_r23_v19/tree.json` — a file of a
        REAL decompile — and restored the time in `finally`. Two arguments
        against it, and the second is stronger than the first:

          * the file belongs to a different user, and since 20.08 the test
            failed with `PermissionError`. The refusal WAS PROTECTING the
            corpus, but read as a breakage;
          * had the run broken off between `utime` and `finally`, the
            decompile would have been left with a foreign `mtime`, meaning
            the suite would be writing into the corpus, which must be an
            immutable archive. This is a named defect of this tree, and it
            cannot be kept for the sake of test convenience.

        The claim did not weaken from the move, it got stronger: a sandbox
        of its own allows touching EXACTLY the file that is in the key, and
        checking both sides — that the key moved and that it came back.
        """
        import time

        with tempfile.TemporaryDirectory() as tmp:
            run = pathlib.Path(tmp)
            victim = run / "tree.json"
            victim.write_text("{}", encoding="utf-8")
            (run / "L0.jsonl").write_text("{}\n", encoding="utf-8")

            before = C.key_for("проба", run)
            self.assertTrue(before, "ключа нет — сравнивать нечего")
            # the subject of this check is the cache key, not the cleaner:
            # raw is intentional: the file was just written by THIS test,
            # raw
            #
            # 🔴 THE TIME IS TAKEN AND SET IN NANOSECONDS (30.08.2026,
            # F-269). The key stopped rounding mtime to whole seconds, and
            # `st_mtime` (a double), for a timestamp on the order of 1.8e9
            # s, carries a resolution of ~238 ns — meaning a round trip
            # THROUGH A FLOAT does not restore the timestamp, and the
            # second half of the assertion would fail on an honest fix. The
            # assertion is correct, it was the round-trip INSTRUMENT that
            # was unfit: `os.utime(..., ns=)` returns exactly what was
            # there.
            original_ns = victim.stat().st_mtime_ns
            os.utime(victim, ns=(original_ns + 5_000_000_000,
                                 original_ns + 5_000_000_000))
            self.assertNotEqual(C.key_for("проба", run), before)
            os.utime(victim, ns=(original_ns, original_ns))
            self.assertEqual(C.key_for("проба", run), before)

    def test_a_truncated_entry_is_a_miss_not_garbage(self):
        """A truncated file that hands back an internally consistent
        header is exactly the defect the clash snapshot catches with an
        exception."""
        C.purge()
        C.store("проба-порча", b"x" * 100, build_ms=1.0)
        blob_path, _ = C._paths("проба-порча")
        blob_path.write_bytes(b"short")
        self.assertIsNone(C.load("проба-порча"))
        C.purge()

    def test_a_missing_entry_is_a_miss(self):
        self.assertIsNone(C.load("такого-ключа-нет"))


class ItNamesItselfAndItsAge(unittest.TestCase):
    """The timings in the header belong to the ORIGINAL build. Handing them
    back as its own would mean reporting "built in 20 s" about a read that
    took a millisecond — that is, lying with the instrument."""

    # 🔴 THIS CLASS DOES NOT NEED THE CORPUS — A MEASUREMENT, NOT AN OPINION
    # (29.08.2026). Not a single assertion in the class touches `_run_dir()`:
    # everything lives in a temp directory. The `_skip_without_corpus`
    # binding stood in `setUp` for ALL SIX classes in the file and
    # extinguished eight checks at once — among them the F-268/269/270
    # guards. The classes that ACTUALLY need a decompile
    # (`TheKeyCoversEverythingThatChangesTheAnswer`,
    # `TheKeyCoversNothingThatDoesNot` — they build the key FROM THE
    # DECOMPILE'S DIRECTORY) keep the binding.

    def test_a_hit_carries_age_and_the_warning(self):
        C.purge()
        C.store("проба-возраст", b"blob", build_ms=1234.5,
                inputs=["version=x", "run=y"])
        loaded = C.load("проба-возраст")
        self.assertIsNotNone(loaded)
        _, note = loaded
        self.assertTrue(note["hit"])
        self.assertIn("age_s", note)
        self.assertEqual(note["build_ms"], 1234.5)
        self.assertIn("ИСХОДНОЙ", note["ru"])
        self.assertEqual(note["inputs"], ["version=x", "run=y"])
        C.purge()

    def test_the_switch_off_restores_the_old_behaviour(self):
        """A disabled cache = the behavior before this wave: everyone pays
        for their own cold open."""
        previous = os.environ.get("KUKAI_KIR_SCENE_CACHE")
        os.environ["KUKAI_KIR_SCENE_CACHE"] = "0"
        try:
            self.assertFalse(C.enabled())
            self.assertIsNone(C.load("любой"))
            self.assertFalse(C.store("любой", b"x", build_ms=1.0))
        finally:
            if previous is None:
                os.environ.pop("KUKAI_KIR_SCENE_CACHE", None)
            else:
                os.environ["KUKAI_KIR_SCENE_CACHE"] = previous


class TheSceneBodyIsDeterministic(unittest.TestCase):
    """The cache is legitimate ONLY because the content is stable, and this
    is checked, not assumed: two builds gave a byte-for-byte identical
    BODY, and exactly `timing_ms.*` and `graph.elapsed_ms` differed —
    stopwatch readings."""

    def setUp(self) -> None:
        # 🔴 THIS CLASS DOES NEED THE CORPUS, AND THIS IS A MEASUREMENT, NOT
        # A READING. The tell "the class does not call `_run_dir()`" is a
        # LABEL, not a property: this class fetches a decompile through
        # `scene.scene_from_decompile("sob62_fas_r23_v19")` and fails with
        # `FileNotFoundError` without the corpus. Caught by RUNNING it on
        # 29.08.2026 while removing the binding — grepping for the
        # helper's name did not catch it.
        _skip_without_corpus(self)

    def test_two_builds_agree_on_the_body(self):
        import json
        import struct
        from kir.viewer.scene import scene_from_decompile

        def split(blob):
            head_len = struct.unpack_from("<I", blob, 8)[0]
            return (json.loads(blob[12:12 + head_len].decode("utf-8")),
                    blob[12 + head_len:])

        head_a, body_a = split(scene_from_decompile("sob62_fas_r23_v19")[0])
        head_b, body_b = split(scene_from_decompile("sob62_fas_r23_v19")[0])
        self.assertEqual(body_a, body_b, "тело сцены обязано быть стабильным")
        differing = {k for k in set(head_a) | set(head_b)
                     if head_a.get(k) != head_b.get(k)}
        self.assertTrue(differing <= {"timing_ms", "graph"},
                        f"разошлось не только время: {differing}")


class BoundedByBytesNotByEntries(unittest.TestCase):
    """The facade scene is 0.5 MB, the demo-v3 scene is 5.2 MB. Counting
    them as the same means not counting at all; an unlimited cache is a
    leak with a nice name."""

    # 🔴 THIS CLASS DOES NOT NEED THE CORPUS — A MEASUREMENT, NOT AN OPINION
    # (29.08.2026). Not a single assertion in the class touches `_run_dir()`:
    # everything lives in a temp directory. The `_skip_without_corpus`
    # binding stood in `setUp` for ALL SIX classes in the file and
    # extinguished eight checks at once — among them the F-268/269/270
    # guards. The classes that ACTUALLY need a decompile
    # (`TheKeyCoversEverythingThatChangesTheAnswer`,
    # `TheKeyCoversNothingThatDoesNot` — they build the key FROM THE
    # DECOMPILE'S DIRECTORY) keep the binding.

    def test_the_ceiling_is_in_bytes(self):
        self.assertGreaterEqual(C._max_bytes(), 10_000_000)

    def test_stats_name_every_outcome(self):
        stats = C.stats()
        for key in ("hit", "miss", "stored", "evicted", "errors", "entries",
                    "bytes", "max_bytes", "enabled", "version"):
            self.assertIn(key, stats)


class TheKeyDoesNotRoundAwayPrecisionItHas(unittest.TestCase):
    """🔴 THE KEY WAS ROUNDING mtime TO WHOLE SECONDS WHILE HAVING
    NANOSECONDS (`F-269`).

    `int(st.st_mtime)` was throwing away distinguishability the filesystem
    gives for free. A corpus sweep on 30.08.2026: **93 of 93 directories
    swept, 0 unswept; 1 328 input files, 1 328 (100 %) with a NON-ZERO
    fractional part of mtime.** That is, it was not lost "sometimes" — it
    was lost on every single input.

    A TWO-SIDED, RACE-FREE DISCRIMINATOR: mtime is set by hand, the "before"
    subject is taken from git (`git show HEAD:kir/viewer/cache.py`):

        mtime shift    HEAD (int seconds)   the tree (nanoseconds)
        1 ns           BLIND                sees it
        4 ms           BLIND                sees it
        200 ms         BLIND                sees it
        1 s            sees it              sees it

    🔴 THE REMAINDER IS NAMED BY A NUMBER, NOT BY THE WORD "NANOSECOND". The
    kernel does not hand out a new stamp on every write: 2 753 rewrites gave
    740 DISTINCT `st_mtime_ns` values, with a 4.000 ms step between
    neighboring stamps (median). So the gain is exactly 250-fold (1 000 ms
    -> 4 ms), not a billion-fold, and the residual window is a property of
    the kernel clock, not of the key.

    THE COST OF THE FIX IS NAMED: every existing cache record will miss
    once and rebuild — the same cost already accepted when `kind=` was
    added. `CACHE_VERSION` is NOT touched here: it is the version of the
    scene FORMAT, the codec did not change, and bumping it would mean
    telling the same untruth in a second place.
    """

    def _run(self, tmp):
        run = pathlib.Path(tmp)
        (run / "L0.jsonl").write_bytes(b"A" * 4096)
        return run

    def test_a_rewrite_inside_one_second_moves_the_key(self):
        """THE HEADLINE CASE: the same size, the same second, different
        content."""
        with tempfile.TemporaryDirectory() as tmp:
            run = self._run(tmp)
            victim = run / "L0.jsonl"
            # raw is intentional: the file is written by THIS test RAW,
            # into a temp directory the cleaner never visits — a compressed
            # variant cannot occur here by construction. And the subject of
            # this check is THE KEY'S SENSITIVITY to the real file's size
            # and stamp; asking the helper for them
            # (`snapshot_raw_size` reads ISIZE from the gzip trailer) would
            # mean measuring something other than what the cache puts into
            # the key.
            stamp = victim.stat().st_mtime_ns
            # exactly the same SECOND, a different nanosecond
            base = stamp - stamp % 1_000_000_000
            os.utime(victim, ns=(base + 1, base + 1))
            before = C.key_for("проба", run)
            victim.write_bytes(b"B" * 4096)          # the SAME size
            os.utime(victim, ns=(base + 2, base + 2))
            # raw is intentional: see the argument above — we check what is
            # on disk
            self.assertEqual(4096, victim.stat().st_size,
                             "размер обязан совпасть, иначе меряем размер")
            # raw is intentional: the same argument — the stamp needs to be
            # ITS OWN, because the teardown block is cut short by the code
            # and does not carry over through the neighboring assertion
            self.assertEqual(int(base / 1e9), int(victim.stat().st_mtime),
                             "секунда обязана совпасть, иначе меряем секунды")
            self.assertNotEqual(C.key_for("проба", run), before,
                                "кэш отдаст СТАРУЮ сцену на изменённом входе")

    def test_the_input_line_carries_the_nanoseconds_the_file_has(self):
        """The number is taken FROM THE FILE, not written as a literal: a
        copy of its own would drift apart silently."""
        with tempfile.TemporaryDirectory() as tmp:
            run = self._run(tmp)
            # raw is intentional: the same argument as in the neighboring
            # check — the file is its own, raw, in a temp directory, and
            # the assertion is exactly about the key string carrying ITS
            # size and ITS nanoseconds
            st = (run / "L0.jsonl").stat()
            self.assertIn(f"L0.jsonl:{st.st_size}:{st.st_mtime_ns}",
                          C.key_inputs("проба", run))

    def test_an_untouched_input_keeps_its_key(self):
        """THE SECOND HALF, WITHOUT WHICH THE FIRST MEANS NOTHING: a guard
        that ALWAYS turns red is not a guard. The same file — the same
        key."""
        with tempfile.TemporaryDirectory() as tmp:
            run = self._run(tmp)
            self.assertEqual(C.key_for("проба", run),
                             C.key_for("проба", run))
