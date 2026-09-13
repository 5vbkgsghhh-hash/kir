"""The bridge's prose is parsed by TWO functions — and they must answer identically.

🔴 WHY THIS FILE EXISTS, IN ONE LIVE REFUSAL (21.08.2026). Revit stopped taking
jobs, the bridge answered "Execution was cancelled before Revit started it", and
the prod journal wrote `runtime.revit_exception` on the `script_catalogue` and
`ground_snapshot` phases — that is, the model was told "your code
compiled and ran" about a turn that NEVER REACHED Revit.

The code `TRANSPORT_CANCELLED` existed at the time, and right next to it in
`envelope.py` stood a comment directly describing this very error: "7 fresh
cases in 30 days were tagged runtime.revit_exception, whose hint
claims 'the code compiled and ran'".

It was warning — and it did not work, because **half the fix landed in one
function out of two**:

    classify_execution_error   the "cancelled before start" branch WAS there
    classify_bridge_error      the branch was NOT THERE   ← and it is this one that won

It won because the code attaching to the BRIDGE does so earlier;
the reclassification does not touch an `err` that is already built in the pipeline.

This is the project's named defect in its pure form: two carriers of one piece of
knowledge, drifted apart silently. Here stands a guard that holds them together — not
the author's memory, but a test.

WHAT THE GUARD DOES NOT REQUIRE. A complete match on ALL prose: the bridge has
its own cases that the execution path never sees ("not connected",
"ExternalEvent: Pending" — these are transport states, not the result of
executed code). They are listed below by name and with a reason. What is required is a
match on the prose that BOTH see — and every new line falls
either into the shared list, or into the list of differences WITH A REASON, but never into silence.
"""
from __future__ import annotations

import unittest

from kir.envelope import (
    DIVERGENT_BRIDGE_PROSE, ErrCode, SHARED_BRIDGE_PROSE,
    classify_bridge_error, classify_execution_error,
)

# 🔴 THE CORPUS MOVED INTO `envelope.py`, RIGHT NEXT TO THE CLASSIFIERS THEMSELVES (21.08.2026).
# It used to live here and was appropriate for as long as there was one asker. After it came the
# agreement registry, and keeping the corpus in the test would have meant either pulling the test into
# prod, or starting a second corpus — that is, buying exactly the defect
# this file guards against.
SHARED_PROSE = SHARED_BRIDGE_PROSE
DIVERGENT_PROSE = DIVERGENT_BRIDGE_PROSE


class TwoClassifiersAgree(unittest.TestCase):

    def test_shared_prose_gets_the_same_code_from_both(self):
        for message, expected in SHARED_PROSE:
            with self.subTest(message=message[:48]):
                from_bridge = classify_bridge_error(message)
                from_exec = classify_execution_error(
                    {"message": message, "error": True})
                self.assertEqual(
                    from_bridge, expected,
                    f"классификатор МОСТА разошёлся с ожидаемым на "
                    f"{message[:60]!r}")
                self.assertEqual(
                    from_exec, expected,
                    f"классификатор ИСПОЛНЕНИЯ разошёлся с ожидаемым на "
                    f"{message[:60]!r}")
                self.assertEqual(
                    from_bridge, from_exec,
                    "два носителя одного знания разошлись — ровно тот "
                    "дефект, ради которого этот файл существует")

    def test_cancelled_is_never_called_a_runtime_exception(self):
        """The main case — as its own test, so that it turns red BY NAME.

        `runtime.revit_exception` claims "the code compiled and
        ran". About a turn cancelled BEFORE it started, that is a lie, and it costs more than
        the absence of any code: the model goes off to fix a working program, and with
        `retryable=True` it even retries it.
        """
        for message, _ in SHARED_PROSE[:4]:
            with self.subTest(message=message[:48]):
                self.assertNotEqual(
                    classify_bridge_error(message),
                    ErrCode.RUNTIME_REVIT_EXCEPTION)
                self.assertNotEqual(
                    classify_execution_error({"message": message,
                                              "error": True}),
                    ErrCode.RUNTIME_REVIT_EXCEPTION)

    def test_divergences_are_named_and_still_true(self):
        """The discrepancies are pinned down with a reason — not "it just happened to turn out this way"."""
        for message, expected, why in DIVERGENT_PROSE:
            with self.subTest(message=message[:48]):
                self.assertEqual(
                    classify_bridge_error(message), expected,
                    f"мост обязан знать этот случай: {why}")
                self.assertTrue(why, "расхождение без причины — это тишина")


if __name__ == "__main__":
    unittest.main()
