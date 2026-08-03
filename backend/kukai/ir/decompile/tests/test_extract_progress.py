"""Самая длинная стадия прогона обязана быть ВИДНОЙ.

Замер 30.07 на живой башне: извлечение шло 41 минуту, за это время L0 вырос до
88 МБ и закрылся футером, а ``status.json`` за все 41 минуту не обновился ни
разу и продолжал утверждать ``stage=open_model_profile, done 0/0``. Спрашивающий
«как там прогон» получал ответ, по которому невозможно отличить «идёт нормально»
от «повисло на первой же странице».

Это не косметика. Единственный способ узнать, жив ли прогон, был у того, кто
догадается посмотреть на размер файла, — то есть у одного человека, а не у
инструмента. Тесты ниже требуют, чтобы стадия называла СЕБЯ и чтобы прогресс
был монотонным.
"""
from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from kukai.ir.decompile.extract import EXTRACT_CATEGORIES, extract_document
from kukai.ir.decompile.tests.fixtures_decompile import FakeExtractBridge


class ExtractProgressTests(unittest.TestCase):

    def test_on_progress_is_called_for_every_category(self) -> None:
        seen: list = []
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "L0.jsonl"
            asyncio.run(extract_document(
                FakeExtractBridge(), change_stamp="synthetic-v1",
                output_path=output, on_progress=seen.append))

        self.assertEqual(len(seen), len(EXTRACT_CATEGORIES))
        # Каждая запись называет СВОЮ категорию, в порядке таблицы.
        self.assertEqual(tuple(p.category for p in seen), EXTRACT_CATEGORIES)
        # Счётчик пройденного растёт на единицу и доходит до конца таблицы.
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
        # Последний доклад обязан совпасть с итогом прогона: доклад, который
        # расходится с результатом, хуже отсутствия доклада.
        self.assertEqual(counts[-1], result.element_count)

    def test_a_broken_sink_never_aborts_the_run(self) -> None:
        """Сток прогресса — наблюдатель, а не участник."""
        def explode(_progress) -> None:
            raise RuntimeError("сток прогресса сломан")

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "L0.jsonl"
            result = asyncio.run(extract_document(
                FakeExtractBridge(), change_stamp="synthetic-v1",
                output_path=output, on_progress=explode))

        self.assertEqual(result.completed_categories, EXTRACT_CATEGORIES)

    def test_progress_carries_the_category_verdict(self) -> None:
        """Не только «сколько», но и «чем кончилось» — PARTIAL обязан быть видно."""
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
