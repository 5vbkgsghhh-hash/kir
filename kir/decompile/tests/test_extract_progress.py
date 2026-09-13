"""The longest stage of a run must be VISIBLE.

Measured 07-30 on a live tower: extraction ran for 41 minutes, during
which L0 grew to 88 MB and closed with a footer, while ``status.json``
was not updated even once across all 41 minutes and kept claiming
``stage=open_model_profile, done 0/0``. Someone asking "how is the run
doing" got an answer from which it is impossible to tell "running
normally" apart from "hung on the very first page."

This is not cosmetic. The only way to learn whether the run was alive
belonged to whoever thought to look at the file size — that is, to one
person, not to an instrument. The tests below require the stage to name
ITSELF and progress to be monotonic.
"""
from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from kir.decompile.extract import EXTRACT_CATEGORIES, extract_document
from kir.decompile.tests.fixtures_decompile import FakeExtractBridge


class ExtractProgressTests(unittest.TestCase):

    def test_on_progress_is_called_for_every_category(self) -> None:
        seen: list = []
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "L0.jsonl"
            asyncio.run(extract_document(
                FakeExtractBridge(), change_stamp="synthetic-v1",
                output_path=output, on_progress=seen.append))

        self.assertEqual(len(seen), len(EXTRACT_CATEGORIES))
        # Each entry names ITS OWN category, in the table's order.
        self.assertEqual(tuple(p.category for p in seen), EXTRACT_CATEGORIES)
        # The counter of progress grows by one and reaches the end of the table.
        self.assertEqual([p.categories_done for p in seen],
                         list(range(1, len(EXTRACT_CATEGORIES) + 1)))
        self.assertTrue(all(p.categories_total == len(EXTRACT_CATEGORIES)
                            for p in seen))

    def test_element_count_never_goes_backwards(self) -> None:
        seen: list = []
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "L0.jsonl"
            result = asyncio.run(extract_document(
                FakeExtractBridge(), change_stamp="synthetic-v1",
                output_path=output, on_progress=seen.append))

        counts = [p.elements for p in seen]
        self.assertEqual(counts, sorted(counts))
        # The last report must match the outcome of the run: a report
        # that diverges from the result is worse than no report at all.
        self.assertEqual(counts[-1], result.element_count)

    def test_a_broken_sink_never_aborts_the_run(self) -> None:
        """The progress sink is an observer, not a participant."""
        def explode(_progress) -> None:
            raise RuntimeError("сток прогресса сломан")

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "L0.jsonl"
            result = asyncio.run(extract_document(
                FakeExtractBridge(), change_stamp="synthetic-v1",
                output_path=output, on_progress=explode))

        self.assertEqual(result.completed_categories, EXTRACT_CATEGORIES)

    def test_progress_carries_the_category_verdict(self) -> None:
        """Not only "how much," but also "how it ended" — PARTIAL must be visible."""
        seen: list = []
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "L0.jsonl"
            asyncio.run(extract_document(
                FakeExtractBridge(timeout_probe_for="OST_Roofs"),
                change_stamp="synthetic-v1", output_path=output,
                on_progress=seen.append))

        by_category = {p.category: p for p in seen}
        self.assertEqual(by_category["OST_Roofs"].category_state, "partial")
        self.assertEqual(by_category["OST_Walls"].category_state, "complete")


if __name__ == "__main__":
    unittest.main()
