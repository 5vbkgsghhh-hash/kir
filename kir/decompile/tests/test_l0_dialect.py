"""The L0 dialect must have a name, and old snapshots must remain readable.

WHAT BROKE, AND WHY THIS IS NOT ONE WAVE'S REGRESSION. On 29.07 the read
table grew 54 -> 73 (ee32fb82), and every previous snapshot stopped opening
through ``L0JSONLReader``: "footer precedes one or more fixed categories".
Analysis showed that this wave was not to blame. ``L0_SCHEMA_VERSION`` had
never changed, not once, while the table had grown SIX times
(22 -> 47 -> 48 -> 51 -> 54 -> 73), meaning every past growth was
devaluating the accumulated snapshots just the same — nobody had simply
tried opening an old snapshot with the new code.

THREE INDEPENDENT SOURCES CONVERGED (measurement of 29.07):

* the git history of ``extract.py`` — six distinct tables, each next one
  starting exactly from the previous one;
* the bytes on disk — 55 snapshots in ``backend/data/decompile``: 22 with
  22 categories, 9 with 47, 12 with 48, 1 with 51, 10 with 54, plus one
  interrupted at 7 with no footer; the ``category_status`` sequence of EACH
  of them is an exact prefix of today's 73-row table;
* fingerprints: sha256 over the historical tuples from git matched the
  fingerprints over the bytes on disk for all six generations, zero
  discrepancies.

From this comes the law this file guards: **the table grows ONLY by
appending at the tail**. It had already been written down in words in a
comment in ``extract.py`` ("the order of this tuple is part of the frozen
resume format"), but it was neither checkable nor named as a version. As
long as it holds, a generation is unambiguously given by ONE number — the
table's length; the moment it is violated, ``verify_dialect_ladder`` must
scream, not silently reinterpret the old bytes.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from kir.decompile.extract import (
    EXTRACT_CATEGORIES,
    ExtractionProtocolError,
    L0JSONLReader,
    _load_checkpoint,
)
from kir.decompile.census import (
    UnscannedReason,
    reconcile_census,
)
from kir.decompile.schema import (
    SUPPORTED_L0_DIALECTS,
    SUPPORTED_L0_DIALECT_VERSIONS,
    L0_DIALECT_VERSION,
    L0_SCHEMA_VERSION,
    CensusEntry,
    L0Dialect,
    L0Document,
    L0SchemaError,
    ProjectInfo,
    categories_outside_dialect,
    dialect_by_version,
    dialect_fingerprint,
    resolve_dialect,
    verify_dialect_ladder,
)
from kir.decompile.tests.fixtures_decompile import make_element

# 🔴 A THIRD VERB OF THE SAME CLASS — `stat`. Existence and reading were
# fixed on 20.08, while SIZE by the raw name on a compressed decompile
# raises FileNotFoundError. Exactly the verb the ratchet named as the
# next candidate in its own docstring.
from kir.decompile.snapshot_io import (  # noqa: E402
    open_snapshot, snapshot_raw_size)


def _snapshot_root() -> Path:
    """The directory of real snapshots — the same one serving.py reads."""
    configured = os.environ.get("KUKAI_DECOMPILE_DATA")
    if configured:
        return Path(configured)
    # kir/decompile/tests -> .../backend, затем backend/data/decompile.
    return Path(__file__).resolve().parents[4] / "backend" / "data" / "decompile"


def _write_stream(
    path: Path,
    *,
    categories,
    elements_per_category: int = 0,
    footer_category_count: int | None = None,
    dialect: str | None = None,
) -> None:
    """Write the L0 stream exactly the way extract writes it (compressed
    JSON)."""

    def dump(row) -> bytes:
        return json.dumps(row, ensure_ascii=False, separators=(",", ":"),
                          sort_keys=True).encode("utf-8") + b"\n"

    document = L0Document(
        doc_name="dialect-fixture",
        revit_version="2026",
        units="mm",
        change_stamp=path.parent.name,
        levels=(),
        grids=(),
        rooms=(),
        project_info=ProjectInfo(),
    )
    total = 0
    with path.open("wb") as handle:
        header = {"record": "header", "schema_version": L0_SCHEMA_VERSION,
                  "document": document.metadata_dict()}
        if dialect is not None:
            header["dialect"] = dialect
        handle.write(dump(header))
        for ordinal, category in enumerate(categories):
            for index in range(elements_per_category):
                row = make_element(category, 900_000 + total, ordinal=index)
                handle.write(dump({
                    "record": "element", "collector": category,
                    "element": row}))
                total += 1
            handle.write(dump({"record": "category_status", "status": {
                "category": category, "state": "complete",
                "extracted_count": elements_per_category,
                "expected_count": elements_per_category,
                "error": None, "section_receipts": None}}))
        footer = {"record": "footer", "stream_complete": True,
                  "element_count": total, "link_count": 0,
                  "category_count": (len(list(categories))
                                     if footer_category_count is None
                                     else footer_category_count)}
        handle.write(dump(footer))


class DialectLadderTests(unittest.TestCase):
    """The generation ladder is data, and it must agree with the table."""

    def test_current_table_is_the_newest_generation(self) -> None:
        """The current table must BE the ladder's last step.

        Otherwise the next wave will grow the table, forget the step — and a
        fresh snapshot will refuse to be read by ITS OWN reader. Let it fail
        here.
        """
        newest = SUPPORTED_L0_DIALECTS[-1]
        self.assertEqual(newest.category_count, len(EXTRACT_CATEGORIES),
                         "таблица выросла, а ступень диалекта не заведена")
        self.assertEqual(newest.version, L0_DIALECT_VERSION)
        self.assertEqual(
            newest.fingerprint, dialect_fingerprint(EXTRACT_CATEGORIES))

    def test_every_generation_is_a_prefix_of_todays_table(self) -> None:
        """A step's fingerprint = the fingerprint of today's table's prefix.

        The fingerprints are taken from HISTORY (git + bytes on disk), not
        computed from today's table, so the comparison is not circular: it
        IS the proof that across six growths not a single row was inserted
        in the middle or renamed.
        """
        verify_dialect_ladder(EXTRACT_CATEGORIES)
        for dialect in SUPPORTED_L0_DIALECTS:
            prefix = EXTRACT_CATEGORIES[:dialect.category_count]
            self.assertEqual(len(prefix), dialect.category_count)
            self.assertEqual(dialect_fingerprint(prefix), dialect.fingerprint,
                             f"{dialect.version} больше не префикс таблицы")

    def test_versions_and_counts_are_strictly_increasing(self) -> None:
        counts = [d.category_count for d in SUPPORTED_L0_DIALECTS]
        self.assertEqual(counts, sorted(set(counts)),
                         "ступени обязаны идти строго по возрастанию")
        self.assertEqual(len(set(SUPPORTED_L0_DIALECT_VERSIONS)),
                         len(SUPPORTED_L0_DIALECT_VERSIONS))
        for version in SUPPORTED_L0_DIALECT_VERSIONS:
            self.assertIs(dialect_by_version(version).version.__class__, str)

    def test_mid_table_insertion_is_refused_loudly(self) -> None:
        """REFUTING: an insertion into the middle must scream.

        Exactly this case is the only one in which "generation = length"
        stops working and old bytes could be silently reinterpreted: row N
        in the stream would have meant one category, and in the table —
        another.
        """
        table = list(EXTRACT_CATEGORIES)
        table.insert(10, "OST_Massing")
        with self.assertRaises(L0SchemaError) as caught:
            verify_dialect_ladder(table)
        self.assertIn("kir-decompile-l0-dialect/", str(caught.exception))

    def test_renaming_a_frozen_row_is_refused(self) -> None:
        """REFUTING: renaming a row is the same substitution of meaning."""
        table = list(EXTRACT_CATEGORIES)
        table[0] = "OST_WallsRenamed"
        with self.assertRaises(L0SchemaError):
            verify_dialect_ladder(table)

    def test_truncating_the_table_is_refused(self) -> None:
        """REFUTING: truncating the table is the loss of an already-named
        generation."""
        with self.assertRaises(L0SchemaError):
            verify_dialect_ladder(EXTRACT_CATEGORIES[:-1])

    def test_resolve_names_the_generation_by_count(self) -> None:
        for dialect in SUPPORTED_L0_DIALECTS:
            resolved = resolve_dialect(dialect.category_count,
                                       EXTRACT_CATEGORIES)
            self.assertEqual(resolved.version, dialect.version)

    def test_resolve_refuses_a_count_that_is_no_generation(self) -> None:
        """A category count that occurred in NOT A SINGLE build is not a
        generation.

        The guess "it's probably a prefix" is forbidden here: we do not know
        what such a build considered complete, and so we have no right to
        call its stream complete.
        """
        with self.assertRaises(L0SchemaError) as caught:
            resolve_dialect(30, EXTRACT_CATEGORIES)
        message = str(caught.exception)
        self.assertIn("30", message)
        self.assertIn(SUPPORTED_L0_DIALECTS[-1].version, message)

    def test_absent_categories_are_named_not_zero(self) -> None:
        """Incompleteness must be NAMED, not a silent zero."""
        oldest = SUPPORTED_L0_DIALECTS[0]
        absent = categories_outside_dialect(oldest, EXTRACT_CATEGORIES)
        self.assertEqual(len(absent),
                         len(EXTRACT_CATEGORIES) - oldest.category_count)
        self.assertIn("OST_TelephoneDevices", absent)
        self.assertNotIn("OST_Walls", absent)
        newest = SUPPORTED_L0_DIALECTS[-1]
        self.assertEqual(
            categories_outside_dialect(newest, EXTRACT_CATEGORIES), ())


class ReaderReadsEveryGenerationTests(unittest.TestCase):
    """The reader must open EVERY named generation."""

    def test_every_generation_reads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for dialect in SUPPORTED_L0_DIALECTS:
                with self.subTest(dialect=dialect.version):
                    path = Path(tmp) / f"L0_{dialect.category_count}.jsonl"
                    _write_stream(
                        path,
                        categories=EXTRACT_CATEGORIES[:dialect.category_count],
                        elements_per_category=1)
                    reader = L0JSONLReader(path)
                    elements = list(reader.iter_elements())
                    self.assertEqual(len(elements), dialect.category_count)
                    self.assertEqual(reader.dialect().version, dialect.version)

    def test_unknown_generation_is_refused_and_named(self) -> None:
        """REFUTING: a stream with 30 categories is rejected, and loudly."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "L0.jsonl"
            _write_stream(path, categories=EXTRACT_CATEGORIES[:30])
            with self.assertRaises(ExtractionProtocolError) as caught:
                L0JSONLReader(path).validate()
            self.assertIn("30", str(caught.exception))

    def test_reader_still_refuses_a_reordered_stream(self) -> None:
        """Protection against reordering has NOT weakened: order is still
        law."""
        swapped = list(EXTRACT_CATEGORIES[:22])
        swapped[0], swapped[1] = swapped[1], swapped[0]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "L0.jsonl"
            _write_stream(path, categories=swapped, elements_per_category=1)
            with self.assertRaises(ExtractionProtocolError):
                L0JSONLReader(path).validate()

    def test_reader_still_refuses_a_lying_footer(self) -> None:
        """A footer naming a foreign category count is still rejected."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "L0.jsonl"
            _write_stream(path, categories=EXTRACT_CATEGORIES[:22],
                          footer_category_count=73)
            with self.assertRaises(ExtractionProtocolError) as caught:
                L0JSONLReader(path).validate()
            self.assertIn("footer category count", str(caught.exception))


class RealSnapshotCorpusTests(unittest.TestCase):
    """Proof on REAL bytes, not on a fixture.

    A fixture proves the code agrees with itself. The accumulated corpus (55
    snapshots across six generations, 1.8 GB) proves it agrees with what was
    genuinely captured from live models over eleven days. It was exactly
    this check that confirmed the curtain wall index bump on 29.07, and here
    it must be just as thorough.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.root = _snapshot_root()
        if not cls.root.is_dir():
            raise unittest.SkipTest(f"нет корпуса слепков: {cls.root}")
        cls.by_generation: dict[int, list[Path]] = {}
        for directory in sorted(cls.root.iterdir()):
            stream = directory / "L0.jsonl"
            from kir.decompile.snapshot_io import snapshot_file_exists
            if not snapshot_file_exists(stream):
                continue
            count = 0
            # EXISTENCE AND READING ARE TWO HALVES OF ONE CLASS. Having fixed
            # the first on 20.08, this fixture SAW a compressed decompile and
            # immediately failed on a bare `open`: a silent skip became a
            # loud error. The step is correct, but one half without the
            # other does not work — we read through the helper.
            from kir.decompile.snapshot_io import open_snapshot
            with open_snapshot(stream, "rb", touch=False) as handle:
                for line in handle:
                    if b'"record":"category_status"' in line:
                        count += 1
            cls.by_generation.setdefault(count, []).append(stream)
        if not cls.by_generation:
            raise unittest.SkipTest("корпус пуст")

    def test_corpus_covers_several_generations(self) -> None:
        known = {d.category_count for d in SUPPORTED_L0_DIALECTS}
        covered = sorted(set(self.by_generation) & known)
        self.assertGreaterEqual(
            len(covered), 3,
            f"нужно хотя бы три РАЗНЫХ поколения, есть {covered}")

    def test_one_snapshot_of_every_generation_reads_end_to_end(self) -> None:
        """Every generation from the corpus is read IN FULL, down to the
        footer."""
        known = {d.category_count: d for d in SUPPORTED_L0_DIALECTS}
        checked = 0
        for count, streams in sorted(self.by_generation.items()):
            if count not in known:
                continue
            stream = min(streams, key=lambda path: snapshot_raw_size(path))
            with self.subTest(generation=count, snapshot=stream.parent.name):
                reader = L0JSONLReader(stream)
                elements = sum(1 for _ in reader.iter_elements())
                statuses = list(reader.iter_category_status())
                self.assertEqual(len(statuses), count)
                self.assertEqual(reader.dialect().version,
                                 known[count].version)
                self.assertEqual(
                    [status.category for status in statuses],
                    list(EXTRACT_CATEGORIES[:count]))
                self.assertGreater(elements, 0)
                checked += 1
        self.assertGreaterEqual(checked, 3)

    def test_interrupted_snapshots_still_refuse(self) -> None:
        """An interrupted snapshot (with no footer) must refuse — it genuinely
        is NOT complete.

        Versioning cures "old but whole", not "cut off". Conflating these two
        cases would mean passing off an under-extracted model as a captured
        one.
        """
        refused = 0
        for streams in self.by_generation.values():
            for stream in streams:
                with open_snapshot(stream, "rb", touch=False) as handle:
                    handle.seek(max(0, snapshot_raw_size(stream) - 4096))
                    tail = handle.read()
                if b'"record":"footer"' in tail:
                    continue
                with self.assertRaises(ExtractionProtocolError):
                    L0JSONLReader(stream).validate()
                refused += 1
        if not refused:
            self.skipTest("в корпусе нет оборванных слепков")


class CensusReadsTheSnapshotsOwnTableTests(unittest.TestCase):
    """The census must measure a snapshot by ITS OWN table, not today's."""

    def _document(self, categories, census_counts):
        from kir.decompile.schema import CategoryState, CategoryStatus
        elements = []
        for category in categories:
            count = census_counts.get(category, 0)
            for index in range(count):
                from kir.decompile.schema import L0Element
                row = make_element(category, 700_000 + len(elements),
                                   ordinal=index)
                elements.append(L0Element.from_dict(row))
        return L0Document(
            doc_name="census-fixture", revit_version="2026", units="mm",
            change_stamp="census", levels=(), grids=(), rooms=(),
            project_info=ProjectInfo(),
            elements=tuple(elements),
            category_status=tuple(
                CategoryStatus(category=category,
                               state=CategoryState.COMPLETE,
                               extracted_count=census_counts.get(category, 0),
                               expected_count=census_counts.get(category, 0))
                for category in categories),
            census=tuple(
                CensusEntry(key=key, name=key, count=count)
                for key, count in census_counts.items()),
        )

    def test_category_added_after_the_snapshot_is_outside_its_table(self) -> None:
        """REFUTING: a category that was not in the table AT THAT TIME.

        Before versioning, such a row would get ``category_short_read`` —
        "the extraction read and under-read" — meaning the snapshot was
        blamed for a failure it never committed. There is exactly one
        correct reason: the category was not in that generation's table.
        """
        oldest = SUPPORTED_L0_DIALECTS[0]
        visited = EXTRACT_CATEGORIES[:oldest.category_count]
        newcomer = EXTRACT_CATEGORIES[-1]
        counts = {visited[0]: 3, newcomer: 5}
        document = self._document(visited, counts)
        balance = reconcile_census(document)
        rows = {row.category: row for row in balance.rows}
        self.assertIn(newcomer, rows)
        self.assertEqual(rows[newcomer].reason,
                         UnscannedReason.CATEGORY_OUTSIDE_TABLE)
        self.assertEqual(rows[newcomer].unscanned, 5)
        self.assertFalse(balance.errors)

    def test_explicit_table_still_wins(self) -> None:
        """An explicitly passed table still outranks inference from the
        stream."""
        oldest = SUPPORTED_L0_DIALECTS[0]
        visited = EXTRACT_CATEGORIES[:oldest.category_count]
        newcomer = EXTRACT_CATEGORIES[-1]
        document = self._document(visited, {visited[0]: 1, newcomer: 2})
        balance = reconcile_census(
            document, table=frozenset(EXTRACT_CATEGORIES))
        rows = {row.category: row for row in balance.rows}
        self.assertEqual(rows[newcomer].reason,
                         UnscannedReason.CATEGORY_SHORT_READ)


class ResumeAcrossDialectsTests(unittest.TestCase):
    """What to do about RESUMING a snapshot taken with an old table.

    The decision and its cost are in ``_load_checkpoint``'s docstring. Here
    it is locked down by both outcomes: an interrupted one is resumed, a
    completed one is not.
    """

    def _checkpoint(self, tmp: Path, *, processed, footer_written,
                    dialect=None):
        output = tmp / "L0.jsonl"
        output.write_bytes(b"")
        row = {
            "schema_version": L0_SCHEMA_VERSION,
            "change_stamp": "stamp",
            "output_path": str(output.resolve()),
            "committed_offset": 1,
            "header_written": True,
            "footer_written": footer_written,
            "processed_categories": list(processed),
            "category_states": {c: "complete" for c in processed},
            "element_count": 0,
            "link_count": 0,
        }
        if dialect is not None:
            row["dialect"] = dialect
        path = tmp / "L0.jsonl.checkpoint.json"
        path.write_text(json.dumps(row), encoding="utf-8")
        return path, output

    def test_interrupted_old_generation_resumes(self) -> None:
        """An interrupted run of an old table IS RESUMED.

        Tail-appending is proven: the categories already processed are the
        same rows at the same indices, so extraction can continue without a
        shift.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            path, output = self._checkpoint(
                tmp, processed=EXTRACT_CATEGORIES[:22], footer_written=False,
                dialect=SUPPORTED_L0_DIALECTS[0].version)
            row = _load_checkpoint(path, change_stamp="stamp",
                                   output_path=output)
            self.assertEqual(len(row["processed_categories"]), 22)

    def test_interrupted_checkpoint_without_a_dialect_resumes(self) -> None:
        """A checkpoint from BEFORE versioning also resumes — just
        unnamed.

        There are 55 of 55 such checkpoints on disk: refusing them would mean
        discarding all the accumulated unfinished work for the sake of a
        field that did not exist back then.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            path, output = self._checkpoint(
                tmp, processed=EXTRACT_CATEGORIES[:7], footer_written=False)
            row = _load_checkpoint(path, change_stamp="stamp",
                                   output_path=output)
            self.assertEqual(len(row["processed_categories"]), 7)

    def test_finished_old_generation_refuses_to_be_extended(self) -> None:
        """REFUTING: a completed snapshot is NOT appended to.

        ``stream_complete`` is this container's one and only law. A stream
        that once said "complete" has no right to later say "not complete":
        that is not further extraction, it is a retroactive edit of a
        published fact. Reading such a snapshot is fine (and it is read —
        see the corpus tests), appending to it is not.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            path, output = self._checkpoint(
                tmp, processed=EXTRACT_CATEGORIES[:54], footer_written=True,
                dialect="kir-decompile-l0-dialect/5")
            with self.assertRaises(ExtractionProtocolError) as caught:
                _load_checkpoint(path, change_stamp="stamp",
                                 output_path=output)
            message = str(caught.exception)
            self.assertIn("kir-decompile-l0-dialect/5", message)
            self.assertIn(L0_DIALECT_VERSION, message)

    def test_finished_current_generation_still_loads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            path, output = self._checkpoint(
                tmp, processed=EXTRACT_CATEGORIES, footer_written=True,
                dialect=L0_DIALECT_VERSION)
            row = _load_checkpoint(path, change_stamp="stamp",
                                   output_path=output)
            self.assertTrue(row["footer_written"])

    def test_checkpoint_dialect_must_be_a_known_generation(self) -> None:
        """REFUTING: a foreign dialect version is a refusal, not a guess."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            path, output = self._checkpoint(
                tmp, processed=EXTRACT_CATEGORIES[:22], footer_written=False,
                dialect="kir-decompile-l0-dialect/99")
            with self.assertRaises(ExtractionProtocolError):
                _load_checkpoint(path, change_stamp="stamp",
                                 output_path=output)


if __name__ == "__main__":
    unittest.main()
