"""Pinning snapshots: a reference holds, a quotation does not.

The module under test (`kir/decompile/snapshot_pins.py`) was set up after
a dry run of the janitor on 21.08.2026, which was about to delete 16
snapshots named by sources — including the one the prod viewer visits.
What is guarded here is exactly the distinction it exists for: **a path
assembled by code is a reference; a name named in a measurement docstring
is a quotation.**

The last test is not synthetic: it queries the REAL tree and fails if the
prod viewer's reference to its own snapshot disappears from the
instrument's view. The synthetic tests check the rule, the live
measurement checks that the rule is applied to the actual tree the
janitor will be cleaning.
"""
from __future__ import annotations

import pathlib
import textwrap
import unittest

from kir.decompile import snapshot_pins

# 🔴 ANCHORED AT THE PACKAGE, NOT BY STEPS UPWARD (29.08.2026). This spot
# used to have `parents[4]`, and after the split that gave `/opt` — the
# directory the repository sits in, not the tree's root. Two troubles at
# once, both live:
#   * the walk ran over `/opt/kir`, and the computed `pin.file` came out
#     as `kir/kir/…`, i.e. it DID NOT MATCH `SELF_FILE` — the
#     self-exclusion below excluded nothing, and the live measurement
#     would be checking its own dictionary;
#   * `CORPUS` pointed at `/opt/backend/data/decompile`, which does not
#     exist under any layout, so both live guards were skipped FOREVER.
# The package's own location is known to the package itself; steps
# upward are correct for exactly one layout.
import kir as _kir_pkg  # noqa: E402

BACKEND = pathlib.Path(_kir_pkg.__file__).resolve().parent.parent
CORPUS = BACKEND / "backend" / "data" / "decompile"

#: The SYNTHETIC dictionary deliberately does not overlap the corpus. The
#: first revision used real names — and then this very file itself pinned
#: `pinprobe_cited_v2`, i.e. the fixture became evidence for the
#: instrument it was testing (form 48). That is why the live measurement
#: below also subtracts ITSELF.
NAMES = ("pinprobe_ref_v1", "pinprobe_cited_v2", "pinprobe_both_v3")

#: In the instrument's terms this file is an ordinary source, and its
#: lines pin no worse than any other's. The live measurement needs to ask
#: the tree WITHOUT itself, otherwise it would be checking its own
#: dictionary.
SELF_FILE = "kir/decompile/tests/test_snapshot_pins.py"


def _pins_excluding_self(names):
    """References of the real tree, except those given by this very file."""
    out = {}
    for pin in snapshot_pins.find_pins(names, BACKEND):
        if pin.file == SELF_FILE:
            continue
        out.setdefault(pin.snapshot, pin)
    return out


def _write(root: pathlib.Path, rel: str, body: str) -> pathlib.Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


class PinsDistinguishReferenceFromCitation(unittest.TestCase):

    def setUp(self) -> None:
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _pins(self) -> dict[str, snapshot_pins.Pin]:
        return snapshot_pins.pinned_snapshots(
            NAMES, self.root, source_roots=("kukai",))

    def test_a_path_built_in_code_pins_the_snapshot(self):
        _write(self.root, "kukai/reader.py", '''
            import pathlib
            RUN = pathlib.Path("backend") / "data" / "decompile" / "pinprobe_ref_v1"
        ''')
        pins = self._pins()
        self.assertIn("pinprobe_ref_v1", pins,
                      "путь, собранный кодом, обязан закреплять слепок")
        self.assertEqual(pins["pinprobe_ref_v1"].line, 3)

    def test_a_docstring_measurement_does_not_pin(self):
        _write(self.root, "kukai/cited.py", '''
            """ЦЕНА ЗАМЕРЕНА (башня pinprobe_ref_v1, 59 этажей)."""
            VALUE = 1
        ''')
        self.assertEqual(
            self._pins(), {},
            "докстрока называет, ГДЕ мерили; удаление каталога ничего не "
            "ломает, и удерживать его из-за цитаты значит держать диск зря")

    def test_a_docstring_of_a_function_does_not_pin_either(self):
        _write(self.root, "kukai/cited_fn.py", '''
            def measure():
                """Замер шёл на pinprobe_cited_v2."""
                return 1
        ''')
        self.assertEqual(self._pins(), {})

    def test_a_string_merely_containing_the_name_does_not_pin(self):
        _write(self.root, "kukai/message.py", '''
            MESSAGE = "851 марку `pinprobe_cited_v2` на всех шести версиях"
        ''')
        self.assertEqual(
            self._pins(), {},
            "имя ВНУТРИ текста — не путь; сравнение обязано быть на "
            "равенство, иначе подстрока закрепляет каталог зря")

    def test_the_same_text_pins_when_it_is_code_even_if_a_docstring_repeats_it(self):
        _write(self.root, "kukai/both.py", '''
            """Замер шёл на pinprobe_both_v3."""
            RUN_NAME = "pinprobe_both_v3"
        ''')
        pins = self._pins()
        self.assertIn("pinprobe_both_v3", pins,
                      "докстрока не обязана глушить настоящую ссылку в том "
                      "же файле — пропускаются УЗЛЫ докстрок, не тексты")
        self.assertEqual(pins["pinprobe_both_v3"].line, 3)

    def test_an_fstring_pins_only_when_the_name_is_its_own_chunk(self):
        """The f-string boundary — NAMED, not merely promised.

        Python glues adjacent pieces at parse time: for
        ``f"{root}/pinprobe_both_v3"`` the constant piece equals
        ``"/pinprobe_both_v3"`` together with the separator, and it is NOT
        equal to the name. So a path assembled from pieces is invisible to
        the instrument — exactly as the module's header says. The test
        pins both halves, so the absence does not look like an oversight.
        """
        _write(self.root, "kukai/fstr_glued.py", '''
            def path_for(root):
                return f"{root}/pinprobe_both_v3"
        ''')
        self.assertEqual(
            self._pins(), {},
            "имя, склеенное с разделителем, куском не является")

        _write(self.root, "kukai/fstr_chunk.py", '''
            def path_for(root):
                return f"{root}" f"{''}pinprobe_both_v3"
        ''')
        self.assertIn(
            "pinprobe_both_v3", self._pins(),
            "имя ОТДЕЛЬНЫМ куском f-строки обязано закреплять")

    def test_a_file_that_does_not_parse_yields_no_pins_and_does_not_raise(self):
        _write(self.root, "kukai/broken.py", '''
            def oops(:
        ''')
        _write(self.root, "kukai/fine.py", 'RUN = "pinprobe_both_v3"\n')
        pins = self._pins()
        self.assertIn(
            "pinprobe_both_v3", pins,
            "чужой недописанный файл не должен останавливать уборку целиком")

    def test_only_names_present_on_disk_are_considered(self):
        _write(self.root, "kukai/reader.py", 'RUN = "no_such_snapshot"\n')
        self.assertEqual(
            snapshot_pins.pinned_snapshots(
                NAMES, self.root, source_roots=("kukai",)),
            {},
            "закрепление имеет смысл только против существующих каталогов")


class PinsOnTheRealTree(unittest.TestCase):
    """A live measurement: the rule is applied to the tree the janitor cleans."""

    @unittest.skipUnless(CORPUS.is_dir(), "корпус разборов не смонтирован")
    def test_the_production_viewer_run_is_pinned(self):
        names = sorted(p.name for p in CORPUS.iterdir() if p.is_dir())
        pins = _pins_excluding_self(names)
        self.assertIn(
            "sob62_fas_r23_v19", pins,
            "kukai/api/viewer.py собирает путь к этому слепку; уборщик "
            "21.08 стоял ровно на том, чтобы его удалить")
        self.assertNotIn(
            "/tests/", pins["sob62_fas_r23_v19"].file,
            f"ссылка ожидалась из ПРОДА, получена из "
            f"{pins['sob62_fas_r23_v19'].file}")

    @unittest.skipUnless(CORPUS.is_dir(), "корпус разборов не смонтирован")
    def test_a_snapshot_only_cited_in_docstrings_is_not_pinned(self):
        """`k2_ar_rd`+`_v8` — 20 mentions in the tree, ZERO literals.

        If this test ever turns red, a real reference to the snapshot has
        appeared — and then it is the test that turns red, not the
        directory that gets deleted.
        """
        # 🔴 THE NAME IS ASSEMBLED FROM PIECES DELIBERATELY, AND THIS IS
        # NOT A TRICK.
        #
        # The instrument's rule: a string literal EQUAL to a directory
        # name is a reference. This test does not read the directory — it
        # merely asks about it — but a whole literal would make it a
        # reference, and the janitor would end up holding onto 695 MB
        # because of a file that never touches the data. The test's own
        # check has already subtracted this (`_pins_excluding_self`), but
        # the janitor has not, and in its dry run the pin was printed from
        # THIS very line.
        #
        # In pieces, rather than through a `_pins_excluding_self`-like
        # crutch inside the instrument: the rule "literal = reference"
        # stays simple and general, and the exception lives where it is
        # actually true — in the one file that names snapshots without
        # reading them.
        cited_only = "k2_ar_rd" + "_v8"
        names = sorted(p.name for p in CORPUS.iterdir() if p.is_dir())
        if cited_only not in names:
            self.skipTest("слепок уже убран из корпуса")
        self.assertNotIn(cited_only, _pins_excluding_self(names))


if __name__ == "__main__":
    unittest.main()
