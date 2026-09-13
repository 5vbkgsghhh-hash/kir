"""A CACHE RECORD IS CHECKED, NOT MEASURED: LENGTH IS NOT INTEGRITY.

Audit finding `F-268` (P0), `kir/viewer/cache.py`.

The comment in `load` declared an INTEGRITY CHECK of the record; only
LENGTH was checked. Swapping the blob for a different one of the SAME
length was returned as a hit and shown to the human AS THE BUILDING.
Measured before the fix:

    honest read:    b'good'
    AFTER THE SWAP: b'evil'   hit=True
    counters: {'hit': 2, 'miss': 0, 'stored': 1, 'evicted': 0, 'errors': 0}

🔴 NOTICE `errors: 0`. The instrument did not merely make a mistake — it
BELIEVED there were no errors. A silent VALUE, not a silent output: a human
looking at the counters saw a healthy cache.

🔴 COVERAGE MEASUREMENT 30.08.2026 (mine, turn 1): on this machine there IS
a real cache record — `/tmp/kir-scene-cache/6a6e1983….bin`, 498 901 bytes,
`inputs` names `run=sob62_fas_r23_v19`, that is, A CORPUS BUILDING.
Enumerating its manifest's keys: `version`, `bytes`, `built_at`, `build_ms`,
`inputs` — there is NOT A SINGLE field with digest/sha/hash. Coverage: 1 of
1 records was checked by length alone. The corruption itself was not
observed here — the measurement says there is NO GUARD, not that the data
is corrupted.

THE MODULE'S HEADER HONESTLY NAMES A NEIGHBORING HOLE ("swapping a file for
one with the same size and the same mtime goes unnoticed by the cache") —
but that one is about INPUTS (`key_inputs`, `F-269`). Here the hole is in
THE RECORD ITSELF, and it was named nowhere.

WHY THE OLD RECORD IS A MISS, NOT "NOTHING TO CHECK WITH". Silent
acquiescence to an unverifiable record is exactly the defect being fixed
here. `CACHE_VERSION` was not bumped: a version would devalue the WHOLE
cache at once, a miss devalues it gradually, and the safety is the same.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest

from kir.viewer import cache as K


class ЗаписьКэшаСверяетсяДайджестом(unittest.TestCase):

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self._saved = os.environ.get("KIR_SCENE_CACHE_DIR")
        os.environ["KIR_SCENE_CACHE_DIR"] = self._dir.name
        self.addCleanup(self._restore)
        self._counters = dict(K._COUNTERS)
        self.addCleanup(K._COUNTERS.update, self._counters)
        for k in K._COUNTERS:
            K._COUNTERS[k] = 0

    def _restore(self) -> None:
        if self._saved is None:
            os.environ.pop("KIR_SCENE_CACHE_DIR", None)
        else:
            os.environ["KIR_SCENE_CACHE_DIR"] = self._saved

    def test_an_honest_entry_is_still_a_hit(self) -> None:
        """🔴 THE GREEN OUTCOME FIRST. A cache that always misses is not a
        cache; a fix that "checking is impossible, always miss" would pass
        everything else and strip the module of its entire point."""
        self.assertTrue(K.store("k", b"good", build_ms=1.0, inputs=["x"]))
        got = K.load("k")
        self.assertIsNotNone(got)
        self.assertEqual(got[0], b"good")
        self.assertTrue(got[1]["hit"])
        self.assertEqual(K._COUNTERS["errors"], 0)

    def test_a_same_length_substitution_is_a_miss(self) -> None:
        """🔴 THE SUBJECT OF THE FINDING: the length matches, the content is
        someone else's."""
        K.store("k", b"good", build_ms=1.0, inputs=["x"])
        (K.cache_dir() / "k.bin").write_bytes(b"evil")
        self.assertEqual(len(b"evil"), len(b"good"))   # the length is THE SAME
        self.assertIsNone(K.load("k"), "подменённый блоб отдан как здание")

    def test_the_error_is_counted_not_swallowed(self) -> None:
        """🔴 THE SECOND HALF: `errors` stayed at ZERO. The instrument
        believed there were no errors — a silent value, not a silent
        output."""
        K.store("k", b"good", build_ms=1.0, inputs=["x"])
        (K.cache_dir() / "k.bin").write_bytes(b"evil")
        K.load("k")
        self.assertEqual(K._COUNTERS["errors"], 1)
        self.assertEqual(K._COUNTERS["hit"], 0)

    def test_an_entry_without_a_digest_is_a_miss(self) -> None:
        """A record from the previous revision carries no digest. This is a
        MISS, not "nothing to check with": acquiescing to an unverifiable
        record is itself the defect."""
        K.store("k", b"good", build_ms=1.0, inputs=["x"])
        meta_path = K.cache_dir() / "k.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        self.assertIn("sha256", meta)
        meta.pop("sha256")
        meta_path.write_text(json.dumps(meta, ensure_ascii=False),
                             encoding="utf-8")
        self.assertIsNone(K.load("k"))

    def test_a_truncated_entry_is_still_a_miss(self) -> None:
        """A truncated file must remain a miss.

        🔴 SAYING PLAINLY WHAT THIS CHECK DOES NOT GUARD. The FAIL control
        showed: removing the LENGTH check leaves the whole file GREEN. This
        is not the instrument's blindness but a fact about the code —
        truncation changes both the length and the digest, so the length
        check is now SUBSUMED by the digest check and survives only as a
        cheap early exit. The check below guards a PROPERTY ("truncated is
        a miss"), not a line of code, and that is correct; but let the next
        person not read it as a ratchet on length.
        """
        K.store("k", b"good", build_ms=1.0, inputs=["x"])
        (K.cache_dir() / "k.bin").write_bytes(b"go")
        self.assertIsNone(K.load("k"))

    def test_the_digest_written_is_the_digest_of_the_blob(self) -> None:
        """The digest is of the SCENE, not of the inputs and not of the key
        name."""
        blob = b"\x00\x01scene-bytes\xff"
        K.store("k", blob, build_ms=1.0, inputs=["x"])
        meta = json.loads((K.cache_dir() / "k.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["sha256"], hashlib.sha256(blob).hexdigest())
        self.assertEqual(meta["bytes"], len(blob))

    def test_the_neighbouring_hole_is_not_claimed_fixed(self) -> None:
        """🔴 WHAT THIS DOES NOT FIX. Swapping an INPUT of the same length
        and the same mtime (`key_inputs`, F-269) remains unnoticed; the
        module header names it separately. This check exists so the fix is
        not mistaken for the neighboring one."""
        import inspect
        src = inspect.getsource(K.key_inputs)
        self.assertNotIn("sha256", src,
                         "входы начали хешироваться — это другая находка, и "
                         "её цена (L0 до 88 МБ) здесь не мерена")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
