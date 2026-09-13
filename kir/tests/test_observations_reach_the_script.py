"""THE JUDGE'S OBSERVATIONS TRAVELED TO THE MODEL EMPTY, BECAUSE OF ONE
DEFAULT.

WHY THIS FILE, MEASURED 20.08.2026. `building.observations()` stands in the
model's surface (106 names) and works; `index_from_run` can hand back the
decompile TOGETHER with observations. The gateway called the form WITHOUT
them:

    index_from_run(run)                        observations   0
    index_from_run(run, with_observations=1)   observations  84

That is, the capability was built, wired into the model's surface, and
switched off BY DEFAULT, while **an empty list is indistinguishable from
"the building is clean"**.

🔴 AND THE SECOND HALF, WITHOUT WHICH THE FIRST IS MISLEADING. Measured over
four decompiles under `KUKAI_CHECKER_V2=1` (the condition lives in the
command, not in memory: without the flag the judge stays silent and returns
zero on ANY building):

    decompile            L0 MB   w/o      w/ obs    COST    obs   SILENT
    sob62_r23_v5          1.4   0.44s    1.30s     0.86s     84    144
    sob62_fas_r23_v6      3.0   0.41s    0.65s     0.24s      0    277
    snowdon_plumb_v3      5.2   0.62s    1.26s     0.64s      0    277
    k2_ar_rd_v15         88.4  10.93s   34.76s    23.83s    660    144

For two buildings observations are ZERO with 277 rules silent. There, zero
means "could not judge," not "no violations," and without the second half of
the pair the reader will read the first as the second.

WHY THE DECISION WAS MOVED INTO A PURE FUNCTION (shape 33). Checking a
threshold by calling the guarded action means learning about it AT THE COST
OF THE ACTION ITSELF: on the tower that is 24 seconds and 356 MB per test
run. Here the input is faked, the outcome is read, and the heavy decompile
never happens.
"""
from __future__ import annotations

import unittest

from kir import serving


class ПорогОтвечаетПРИЧИНОЙ(unittest.TestCase):

    def test_a_median_corpus_run_fits_and_says_so_by_None(self):
        """The corpus's median decompile — 3.0 MB, a quarter second. It fits."""
        self.assertIsNone(serving.observations_budget(3_000_000))

    def test_the_tower_does_not_fit_and_the_reason_carries_BOTH_numbers(self):
        """A refusal without figures is a complaint. The reader must see how far off it is."""
        why = serving.observations_budget(88_400_000)
        self.assertIsNotNone(why)
        self.assertIn("88.4", why)
        self.assertIn("16.8", why)

    def test_the_reason_says_it_is_NOT_a_clean_building(self):
        """This line's main job is to separate two outcomes, not to
        apologize.

        "There are no observations" and "observations were not sought" are
        different facts, and the model must read exactly the second one.
        """
        why = serving.observations_budget(88_400_000)
        self.assertIn("НЕ «нарушений нет»", why)
        self.assertIn("normcontrol", why)

    def test_the_edge_is_inclusive_and_one_byte_over_refuses(self):
        """The boundary is named on both sides: exactly at the ceiling it
        fits, +1 byte it does not.

        A boundary coinciding with the content makes a miss invisible — a
        rule bought while cleaning up the live tower, where the strip began
        AT EXACTLY the filter's number.
        """
        cap = serving._OBSERVATIONS_MAX_L0_BYTES
        self.assertIsNone(serving.observations_budget(cap))
        self.assertIsNotNone(serving.observations_budget(cap + 1))


class РешениеДЕЙСТВИТЕЛЬНОЗОВЁТСЯВШлюзе(unittest.TestCase):
    """CHECKING THE LAST LINK: a pure function can be written and never
    called.

    🔴 WE ASK FOR BOTH THE NAME AND THE KEYWORD ARGUMENT. A name lands in
    `co_names` from an import too; Python 3.12 puts keyword-argument names
    as a TUPLE into `co_consts`, and only when a call with them is compiled.
    Both pitfalls were bought on 20.08 — one by a neighboring wave on
    `joins=`, the other by me on this same technique, both on the same day.
    """

    @staticmethod
    def _walk(code, field, seen=None):
        seen = seen if seen is not None else set()
        for item in (getattr(code, field) or ()):
            if isinstance(item, tuple):
                seen.update(x for x in item if isinstance(x, str))
            elif isinstance(item, str):
                seen.add(item)
        for const in code.co_consts:
            if hasattr(const, "co_names"):
                РешениеДЕЙСТВИТЕЛЬНОЗОВЁТСЯВШлюзе._walk(const, field, seen)
        return seen

    def test_the_gate_asks_the_budget_and_asks_for_observations(self):
        code = serving._building_index_for_turn.__code__
        names = self._walk(code, "co_names")
        consts = self._walk(code, "co_consts")
        self.assertIn("observations_budget", names,
                      "порог написан и не спрошен — наблюдения снова поедут "
                      "по умолчанию")
        self.assertIn("with_observations", consts,
                      "шлюз снова зовёт форму БЕЗ наблюдений, и пустой список "
                      "снова неотличим от «здание чистое»")
        self.assertIn("observations_refused", consts,
                      "отказ перестал называться — пустота вернулась молча")


class ОтсутствующийL0НеЧитаетсяКакДешёвыйРазбор(unittest.TestCase):
    """🔴 "THE FILE IS MISSING" PASSED ANY SIZE THRESHOLD.

    `snapshot_raw_size` returns 0 when there is NEITHER a raw NOR a
    compressed file, and its docstring names the rule outright: "this case
    ought to be told apart by `snapshot_file_exists`, not by the size."
    Here, the companion was not asked: the zero went into
    `observations_budget`, which answered "it fits," and a missing decompile
    read as "observations are cheap."

    The cost is not an empty list but a WRONG VERDICT: the turn went ahead
    to judge a building for which there is no source data.
    """

    def test_zero_size_of_a_missing_file_is_not_a_small_file(self) -> None:
        import os, tempfile
        from kir.decompile.snapshot_io import (snapshot_file_exists,
                                               snapshot_raw_size)
        from kir.serving import observations_budget
        with tempfile.TemporaryDirectory() as tmp:
            gone = os.path.join(tmp, "L0.jsonl")
            self.assertFalse(snapshot_file_exists(gone))
            self.assertEqual(snapshot_raw_size(gone), 0,
                             "величина по-прежнему 0 — ответ не тронут")
            self.assertIsNone(
                observations_budget(snapshot_raw_size(gone)),
                "бюджет по-прежнему говорит «влезает» — и именно поэтому "
                "величины НЕДОСТАТОЧНО: спрашивать надо существование")

    def test_the_live_path_asks_existence_before_the_budget(self) -> None:
        """A guard on THE FIX ITSELF: the live path must ask about
        existence.

        The properties of the functions above show that the size is NOT
        ENOUGH. This control demands that it not be enough: between reading
        the size and the budget stands the question of existence, and the
        refusal carries its own cause.
        """
        import ast
        import inspect
        import textwrap
        from kir import serving

        # 🔴 `cleandoc` IS UNFIT HERE, AND THIS WAS BOUGHT RIGHT ON THIS TEST:
        # it aligns by the DOCSTRING and breaks the code's indentation,
        # ast.parse fails with IndentationError — the control stayed red both
        # with and without the fix, meaning it was guarding nothing. `dedent`
        # is needed instead.
        src = textwrap.dedent(
            inspect.getsource(serving._building_index_for_turn))
        tree = ast.parse(src)
        calls = [n.func.id for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
        self.assertIn("snapshot_file_exists", calls,
                      "живой путь спрашивает РАЗМЕР и не спрашивает "
                      "СУЩЕСТВОВАНИЕ — ноль отсутствующего файла пройдёт "
                      "любой порог")
        # The check is BY THE TREE, not by text: the fix quotes the
        # companion's name in its own comment, and a grep on the string
        # would always be green (the same miss recorded in 12cf93e).
        self.assertIn("судить не по чему", src,
                      "отказ обязан назвать причину словами, а не молчать")

    def test_a_real_small_file_still_fits(self) -> None:
        """Positive control: a real small decompile is not rejected."""
        import os, tempfile
        from kir.decompile.snapshot_io import (snapshot_file_exists,
                                               snapshot_raw_size)
        from kir.serving import observations_budget
        with tempfile.TemporaryDirectory() as tmp:
            small = os.path.join(tmp, "L0.jsonl")
            with open(small, "w", encoding="utf-8") as fh:
                fh.write('{"record": "header"}\n')
            self.assertTrue(snapshot_file_exists(small))
            self.assertGreater(snapshot_raw_size(small), 0)
            self.assertIsNone(observations_budget(snapshot_raw_size(small)))


class МетаданныхНетНеЗначитЧтениеПолное(unittest.TestCase):
    """🔴 A GUARD ON A DISTINCTION that is already made and held up by
    NOTHING.

    `_metadata_from_l0_header` returns `None` for a missing L0, and both of
    its consumers do tell this apart — but by DIFFERENT means, and neither
    is pinned by a check:

        re-lift          -> falls back to the passport, and with both
                            `None` — a named refusal `no_metadata`
        read probe       -> `is_partial_read: False, worksets_closed: 0`
                            PLUS `measured: False`

    The second is more dangerous: without `measured` this pair reads as
    "the read is complete, zero worksets closed" — that is, a fact about the
    BUILDING instead of a fact about the MEASUREMENT. Remove the key, and
    not a single test would turn red today.
    """

    def test_the_probe_carries_the_measured_flag(self) -> None:
        import ast
        import inspect
        import textwrap
        from kir import serving

        src = textwrap.dedent(inspect.getsource(serving))
        tree = ast.parse(src)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef)
                  and "partial_read" in ast.get_source_segment(src, n or "")
                  and "_metadata_from_l0_header" in ast.get_source_segment(src, n))
        returns = [n for n in ast.walk(fn) if isinstance(n, ast.Return)
                   and isinstance(n.value, ast.Dict)]
        self.assertTrue(returns, "проба обязана возвращать словарь")
        for node in returns:
            keys = {k.value for k in node.value.keys
                    if isinstance(k, ast.Constant)}
            self.assertIn(
                "measured", keys,
                "ветка возврата без ключа measured: «метаданных нет» станет "
                "неотличимо от «чтение полное, ворксетов ноль» — факт о "
                "ЗАМЕРЕ прочтётся как факт о ЗДАНИИ")

    def test_the_relift_path_refuses_by_name(self) -> None:
        """The first consumer: when both sources are empty — a NAMED
        refusal, not empty metadata."""
        import inspect
        from kir import serving

        src = inspect.getsource(serving)
        self.assertIn("no_metadata", src,
                      "re-lift обязан отказывать ИМЕНЕМ, а не собирать "
                      "программу на пустых метаданных")


if __name__ == "__main__":
    unittest.main()
