"""REUSING THE GROUNDING SNAPSHOT — guards on the premise, not on the
implementation.

Measured 23.08.2026 (migration of building K3, 55 programs): the
snapshot is taken again for every program, time grows 3 s -> 16 s -> 126
s -> 250 s, and the run stalls. The cause is not size but
UNCACHEABILITY: the snapshot text is byte-for-byte the same across all
55 programs, but the obfuscator is non-deterministic, so a different
source arrives in Revit each time and gets compiled again.

Three guards stand here, and the first of them is the main one: it
guards the PREMISE that makes reuse legitimate at all.
"""
import unittest

from kir import serving, spec
from kir.open_model import required_grounding_pools


class ПосылкаПереиспользования(unittest.TestCase):
    """A snapshot can be reused ONLY because it is entirely catalog
    data."""

    def test_ни_один_пул_заземления_не_держит_экземпляры(self):
        """🔴 THE MAIN GUARD OF THIS WAVE.

        Reuse is legitimate precisely because all 36 pools are catalog
        data (types, type-marks, levels, grids, materials, sets,
        stages). A program placing walls cannot change them, by
        construction.

        Should INSTANCES ever appear among the pools, the premise would
        collapse, while the code would keep running and grounding
        against a stale snapshot. So it must be the TEST that fails,
        not prod.
        """
        pools = required_grounding_pools()
        self.assertTrue(pools, "пулы заземления не прочитаны")
        # `_types`/`_symbols` are searched for INSIDE the name, not at
        # the end: the `column_symbols_architectural` pool is catalog
        # data too, and the first edition of this guard declared it an
        # instance pool. The guard was right to go red; what was wrong
        # was the allow-list.
        allowed_exact = {"levels", "grids", "load_cases"}
        for pool in pools:
            with self.subTest(pool=pool):
                self.assertTrue(
                    "_types" in pool or "_symbols" in pool
                    or pool in allowed_exact,
                    f"пул {pool!r} не выглядит каталожным — посылка "
                    "переиспользования требует пересмотра")


class РазличительКаталога(unittest.TestCase):
    """A pair (verb, object), not just an object: both halves were
    bought by a mistake."""

    def _prog(self, op_name: str) -> dict:
        return {"ops": [{"op": op_name, "id": "A"}]}

    def test_создающие_каталог_узнаются(self):
        for name in ("create_level", "create_grid", "create_wall_type",
                     "create_type", "load_family", "transfer_family"):
            with self.subTest(op=name):
                self.assertTrue(
                    serving._program_writes_catalog(self._prog(name)))

    def test_ставящие_экземпляр_не_узнаются(self):
        """🔴 THE CONTROL THAT CAUGHT THE FIRST EDITION.

        `create_wall` carries `('create', 'category')` — it creates an
        element OF a category, not the category itself. `place_family`
        carries `('place', 'family')` — a different verb. Comparing by
        object alone would declare both catalog ops, and reuse would
        NEVER kick in: the fix would look done and would not work.
        """
        for name in ("create_wall", "place_family", "create_door",
                     "create_room_separator"):
            with self.subTest(op=name):
                self.assertFalse(
                    serving._program_writes_catalog(self._prog(name)))

    def test_delete_считается_каталожным_намеренно(self):
        """A type can be deleted too; there is nothing to tell the two
        apart BEFORE execution."""
        self.assertTrue(serving._program_writes_catalog(self._prog("delete")))

    def test_непонятное_считается_каталожным(self):
        """An unfamiliar op and a malformed program — toward the safe
        side."""
        self.assertTrue(serving._program_writes_catalog({"ops": [{"op": "ззз"}]}))
        self.assertTrue(serving._program_writes_catalog({"нет_опов": 1}))
        self.assertTrue(serving._program_writes_catalog(None))

    def test_каждая_пара_названа_живым_опом(self):
        """A pair that no op declares is decoration, not a rule."""
        declared = {tuple(pair)
                    for op in spec.OPS.values()
                    for pair in (op.capability or ())}
        for pair in serving._CATALOG_CAPABILITIES:
            with self.subTest(pair=pair):
                self.assertIn(pair, declared)


class ГейтИКэш(unittest.TestCase):
    def setUp(self) -> None:
        serving._ground_cache_drop()

    def test_гейт_по_умолчанию_выключен(self):
        """A switched-off gate must be byte-for-byte the old
        behavior."""
        self.assertFalse(serving._ground_reuse_enabled())

    def test_сброс_чистит_целиком(self):
        serving._GROUND_SNAPSHOT_CACHE["x"] = {"levels": []}
        serving._ground_cache_drop()
        self.assertEqual(serving._GROUND_SNAPSHOT_CACHE, {})

    def test_зонд_личности_много_меньше_снимка(self):
        """The point of this wave is the size: 638 against 34 430
        characters."""
        self.assertLess(
            len(serving._GROUND_IDENTITY_CS),
            len(serving._SNAPSHOT_CS) // 10,
            "зонд личности перестал быть дешевле снимка на порядок")

    def test_зонд_отдаёт_то_же_поле_личности(self):
        """The probe and the full snapshot must speak about the same
        field."""
        self.assertIn("__document_fingerprint", serving._GROUND_IDENTITY_CS)
        self.assertIn("document-fingerprint/1", serving._GROUND_IDENTITY_CS)


if __name__ == "__main__":
    unittest.main()
