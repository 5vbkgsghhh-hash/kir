"""WHAT THE MODEL STUMBLES ON WHEN IT WRITES PYTHON — A QUESTION WITH NO
SOURCE BEFORE 20.08.

WHY THIS FILE EXISTS, BY MEASUREMENT. The refusal corpus
`data/telemetry/kir_rejections.jsonl` — 2395 lines, window 16.07 → 19.08
— carries **0 lines from the sandbox**: the words `KIR-B004`, `sandbox`,
and the Russian root «песочниц» appear in it zero times. The
author-refusal path (`serving._script_refusal_result`) returned a typed
receipt and NEVER CALLED THE RECORDER, NOT ONCE.

The cost of this silence was named the very same day: the composition of
the import whitelist had to be declared as a DECISION rather than a
measurement — there was no one to ask. A zero in the corpus meant "there
is no one to ask," not "the model never stumbled," and telling one from
the other was possible only by reading the code (form 4).

🔴 THE SINK IS SEPARATE, AND THIS IS NOT A CONVENIENCE. The contract
feed's `reject_code` is a CLOSED enum, by which the consumer ranks
COVERAGE GAPS. `KIR-B004` would have landed there as `VALIDATION_FAILED`,
meaning the author stumbling over our own whitelist would masquerade as
an uncovered Revit operation — one word for two different troubles.

THE INPUT IS BUILT BY PROD'S OWN CODE (form 27): the refusals are
obtained from the REAL sandbox via `sandbox.execute_author_script` with
the prod policy, rather than hand-assembled. A hand-written fixture is
dangerous not through inaccuracy — it answers NO, and a negative answer
looks like a result and closes the question.
"""
from __future__ import annotations

import json
import os
import pathlib
import tempfile
import unittest


def _real_refusal(source: str):
    """A real refusal from a real sandbox, under the PROD policy."""
    from kir import sandbox, serving
    result = sandbox.execute_author_script(source, policy=serving._sandbox_policy())
    assert not result.ok, "ожидался отказ на %r" % source
    return result.refusal


class _Sink(unittest.TestCase):
    """Every test writes to ITS OWN file: a shared sink would make the
    order significant."""

    def setUp(self) -> None:
        from kir import coverage_feed
        self._dir = tempfile.TemporaryDirectory()
        self._path = os.path.join(self._dir.name, "author.jsonl")
        self._saved = os.environ.get(coverage_feed._AUTHOR_ENV)
        os.environ[coverage_feed._AUTHOR_ENV] = self._path
        self._counts = dict(coverage_feed.AUTHOR_FEED_COUNTS)

    def tearDown(self) -> None:
        from kir import coverage_feed
        if self._saved is None:
            os.environ.pop(coverage_feed._AUTHOR_ENV, None)
        else:
            os.environ[coverage_feed._AUTHOR_ENV] = self._saved
        coverage_feed.AUTHOR_FEED_COUNTS.clear()
        coverage_feed.AUTHOR_FEED_COUNTS.update(self._counts)
        self._dir.cleanup()

    def rows(self) -> list:
        p = pathlib.Path(self._path)
        if not p.is_file():
            return []
        return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines()
                if line.strip()]


class ОтказАвтораДоезжаетДоКорпуса(_Sink):

    def test_the_forbidden_module_is_named_and_that_is_the_whole_point(self):
        """«Import forbidden» with no module NAME answers no question
        at all."""
        from kir import serving
        serving._script_refusal_result(_real_refusal("import os\n"),
                                       {"author_digest": "deadbeef"})
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["code"], "KIR-B004")
        self.assertEqual(rows[0]["module"], "os")

    def test_a_forbidden_builtin_names_itself_too(self):
        from kir import serving
        serving._script_refusal_result(_real_refusal("open('x')\n"),
                                       {"author_digest": "deadbeef"})
        rows = self.rows()
        self.assertEqual(rows[0]["code"], "KIR-B005")
        self.assertEqual(rows[0]["name"], "open")
        self.assertIsNone(rows[0]["module"])

    def test_the_row_carries_the_whitelist_of_that_run(self):
        """Without the whitelist of THAT SPECIFIC run, `KIR-B004` cannot
        be interpreted.

        The list is alive: the operator's flag adds geometry libraries
        to it, and the line «import of numpy is forbidden» means the
        opposite depending on whether the flag is on or off. A quantity
        read without its condition is our own named defect.
        """
        from kir import sandbox, serving
        serving._script_refusal_result(_real_refusal("import random\n"),
                                       {"author_digest": "deadbeef"})
        row = self.rows()[0]
        self.assertEqual(list(row["allowed_imports"]),
                         list(sandbox.allowed_imports_for_env()))

    def test_the_authored_source_is_never_written(self):
        """The program's text belongs to the author; the sink holds
        only a signature.

        A second copy of the source would be a surface with no
        consumer, and the receipt already carries `author_digest`.
        """
        from kir import serving
        secret = "import os  # ОСОБАЯ_СТРОКА_АВТОРА\n"
        serving._script_refusal_result(_real_refusal(secret),
                                       {"author_digest": "deadbeef"})
        blob = pathlib.Path(self._path).read_text(encoding="utf-8")
        self.assertNotIn("ОСОБАЯ_СТРОКА_АВТОРА", blob)
        self.assertIn("deadbeef", blob)


class ПроисхождениеРазличимо(_Sink):
    """🔴 A TEST-STAND RUN MUST NOT BE INDISTINGUISHABLE FROM A LIVE TURN.

    Found on 20.08.2026 IMMEDIATELY after the sink was set up: the test
    stand calls the same prod function `_script_refusal_result` as the
    live door, so its refusals landed in the same append-only journal
    with not a single distinguishing field. The future tally of "what
    the model stumbles on when it writes Python" would lie more, the
    harder the stand is run — and it would lie SILENTLY.

    The default is made HONEST rather than convenient: empty means
    UNKNOWN. Only whoever knows the provenance can mark it, and this is
    not the place to record it — both doors enter through one function.
    """

    def test_an_unmarked_refusal_says_UNKNOWN_not_live(self):
        from kir import serving
        serving._script_refusal_result(_real_refusal("import os\n"), {})
        self.assertIsNone(self.rows()[0]["origin"])

    def test_a_marked_run_is_distinguishable(self):
        from kir import coverage_feed, serving
        with coverage_feed.author_origin("bench"):
            serving._script_refusal_result(_real_refusal("import os\n"), {})
        self.assertEqual(self.rows()[0]["origin"], "bench")

    def test_the_mark_does_not_leak_past_its_block(self):
        """Control in the other direction: without it the tag would
        stick for the whole process.

        Then the very first test-stand run would mark all subsequent
        live turns as "the stand" — the indistinguishability would come
        back, just pointed the other way.
        """
        from kir import coverage_feed, serving
        with coverage_feed.author_origin("bench"):
            pass
        serving._script_refusal_result(_real_refusal("import os\n"), {})
        self.assertIsNone(self.rows()[0]["origin"])


class СтокУЧИТЫВАЕТСвоиНеудачи(_Sink):
    """🔴 FAIL-OPEN WITHOUT ACCOUNTING MAKES «DID NOT STUMBLE»
    INDISTINGUISHABLE FROM «DID NOT RECORD».

    Form 34, paid for on 18.08 on the journal bench: an instrument
    denied the chance to perform the measured action printed the cost of
    the action THAT NEVER HAPPENED and looked healthy — it undercounted
    by a FACTOR OF THREE and never once complained. So the sink has
    three outcomes, not two, and all three are observable.
    """

    def test_a_write_that_cannot_happen_is_counted_not_swallowed(self):
        from kir import coverage_feed, serving
        # A path you CANNOT write to: a directory instead of a file.
        os.environ[coverage_feed._AUTHOR_ENV] = self._dir.name
        before = coverage_feed.AUTHOR_FEED_COUNTS["dropped"]
        # The refusal must come out intact — telemetry must not alter it.
        out = serving._script_refusal_result(_real_refusal("import os\n"), {})
        self.assertTrue(out["refused"])
        self.assertEqual(coverage_feed.AUTHOR_FEED_COUNTS["dropped"], before + 1)

    def test_a_disabled_sink_is_a_THIRD_outcome(self):
        """«Zero refusals» and «sink disabled» are different facts, and
        must not be confused."""
        from kir import coverage_feed
        os.environ[coverage_feed._AUTHOR_ENV] = ""
        saved = coverage_feed.install_data_path
        coverage_feed.install_data_path = lambda *a, **k: None
        try:
            before = coverage_feed.AUTHOR_FEED_COUNTS["disabled"]
            coverage_feed.record_author_refusal(_real_refusal("import os\n"))
            self.assertEqual(coverage_feed.AUTHOR_FEED_COUNTS["disabled"], before + 1)
        finally:
            coverage_feed.install_data_path = saved


class ЗаписьДействительноЗОВЁТСЯ(unittest.TestCase):
    """A CHECK ON THE LAST LINK — without it the file guards a fixture.

    The tests above call `_script_refusal_result`, and if the recording
    call is removed from IT, they turn red. But the function itself
    could also be removed from the live path; what is pinned here is
    exactly that the recorder is COMPILED INTO the refusal path.

    🔴 AND WHAT IS CHECKED IS THE CALL, NOT THE NAME — BECAUSE THE NAME
    LANDS THERE FROM THE IMPORT. The first draft checked `co_names`, and
    the control did not turn it red: replacing the call body with `pass`
    leaves the line `from … import record_author_refusal` above intact,
    and the imported name still lands in `co_names`. Five tests out of
    seven turned red, but the last-link guard did not — meaning it could
    not tell the PRESENCE of a call at all. A neighboring wave paid for
    exactly this pattern on its own guard the same day; here it was
    caught by a control, not by reading.

    It distinguishes by NAMED ARGUMENTS: they land in `co_consts` only
    when a call with them is actually compiled. Neither an import, nor a
    comment, nor a docstring puts them there.

    ⚠️ AND TUPLES ARE UNPACKED, OR THE GUARD IS RED FOREVER. Python 3.12
    stores the names of a call's keyword arguments as ONE TUPLE
    (`KW_NAMES`), not as separate strings. The first draft compared
    against strings and turned red on correct code — meaning it would
    have been dismissed as a false alarm, taking the whole check down
    with it. Caught by a control: the mutation turned it red, but so did
    the rollback, and a guard that is red in both states distinguishes
    NOTHING.
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
                ЗаписьДействительноЗОВЁТСЯ._walk(const, field, seen)
        return seen

    def test_the_recorder_is_CALLED_not_merely_imported(self):
        from kir import serving
        code = serving._script_refusal_result.__code__
        names = self._walk(code, "co_names")
        consts = self._walk(code, "co_consts")

        self.assertIn("record_author_refusal", names,
                      "имени записывателя нет вовсе — отказ автора снова "
                      "никуда не пишется")
        for kwarg in ("source_digest", "allowed_imports"):
            with self.subTest(аргумент=kwarg):
                self.assertIn(
                    kwarg, consts,
                    "вызов записи не скомпилирован: имя есть от импорта, а "
                    "именованного аргумента %r нет, значит звать перестали, "
                    "и вопрос «на чём модель спотыкается» снова без "
                    "источника" % kwarg)


if __name__ == "__main__":
    unittest.main()
