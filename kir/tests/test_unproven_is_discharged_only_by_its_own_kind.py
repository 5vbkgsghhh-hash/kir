"""A JOURNAL ENTRY IS LIFTED ONLY BY WHAT ACTUALLY REFUTES IT.

Bought on 2026-08-17 by reverting the previous day's own edit. The day
before, `tool_doc` rendering had learned to subtract from the journal of
the unproven everything for which the witness corpus found a live trace,
and it was reported that "the journal has rotted by 24 entries." Rereading
THE ENTRIES THEMSELVES gave a different number — ONE.

Two independent mistakes, and both are guarded here:

1. **MEASURE.** What counted as a trace was a row with nonzero
   `duration_ms`, that is, "the program REACHED Revit." Of 65 ops that
   reached it, four never committed even once, and seven more committed
   without a green witness.
2. **KIND.** The journal is not a list of "the op never saw live Revit,"
   but a list of TYPED warnings: about semantics ("Revit builds the
   triangulation"), about the op's BRANCH ("walls live, no family"), about
   repeatability ("one green run is not a bet"). A green build discharges
   exactly the first kind and confirms the second.

Control-FAIL run by hand while writing: removing the condition
`_DISCHARGED_BY_ONE_GREEN_ROW` from `_unproven_minus_live_corpus` turns
`test_a_semantic_warning_survives_a_green_corpus` red; reverting to
`duration_ms` instead of the full chain turns
`test_a_rolled_back_row_is_not_proof` red.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest

from kir import tool_doc, witness_corpus


def _corpus(rows: list) -> str:
    fh = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False,
                                     encoding="utf-8")
    for row in rows:
        fh.write(json.dumps(row) + "\n")
    fh.close()
    return fh.name


class _Corpus(unittest.TestCase):
    """Substitutes the corpus via an environment variable and cleans up after itself."""

    def use(self, rows: list) -> None:
        path = _corpus(rows)
        self.addCleanup(os.unlink, path)
        old = os.environ.get(witness_corpus.ENV_PATH)
        os.environ[witness_corpus.ENV_PATH] = path
        if old is None:
            self.addCleanup(os.environ.pop, witness_corpus.ENV_PATH, None)
        else:
            self.addCleanup(os.environ.__setitem__, witness_corpus.ENV_PATH, old)


class TheMeasureIsTheFullChain(_Corpus):

    def test_a_rolled_back_row_is_not_proof(self):
        """Reached it and rolled back — not proof. This is THAT VERY measure."""
        self.use([{"duration_ms": 812.0, "ok": False,
                   "outcome": {"execution": "rolled_back"},
                   "ops": [{"op": "create_angular_dimension"}]}])
        got = witness_corpus.tiers()
        self.assertIn("create_angular_dimension", got["reached"],
                      "строка доехала — уровень 1 обязан её видеть")
        self.assertNotIn("create_angular_dimension", got["committed"])
        self.assertNotIn("create_angular_dimension", got["full_chain"])
        self.assertIn("create_angular_dimension",
                      tool_doc._unproven_minus_live_corpus(),
                      "откат не снимает запись журнала")

    def test_a_commit_without_a_witness_is_not_proof_either(self):
        """A commit without a green witness is a legitimate state, not evidence.

        This is exactly how `create_multi_segment_grid` lives: the
        transaction went through four times, the witness was never green
        once.
        """
        self.use([{"duration_ms": 900.0, "ok": False,
                   "outcome": {"execution": "committed"},
                   "ops": [{"op": "create_angular_dimension"}]}])
        got = witness_corpus.tiers()
        self.assertIn("create_angular_dimension", got["committed"])
        self.assertNotIn("create_angular_dimension", got["full_chain"])
        self.assertIn("create_angular_dimension",
                      tool_doc._unproven_minus_live_corpus())

    def test_a_full_chain_row_does_discharge_its_own_kind(self):
        """And the positive side: a full chain DOES discharge a kind-1 entry.

        Without this, the check degenerates into "nothing is ever
        discharged" and turns green by construction.
        """
        self.use([{"duration_ms": 700.0, "ok": True,
                   "ops": [{"op": "create_angular_dimension"}]}])
        self.assertNotIn("create_angular_dimension",
                         tool_doc._unproven_minus_live_corpus())


class TheKindDecidesWhatDischargesIt(_Corpus):

    def test_a_semantic_warning_survives_a_green_corpus(self):
        """"Revit builds the triangulation" IS confirmed by a green build.

        These are exactly the twelve entries yesterday's edit would have
        removed from the model.
        """
        self.use([{"duration_ms": 500.0, "ok": True,
                   "ops": [{"op": "create_topography"}]}])
        self.assertIn("create_topography", witness_corpus.proven_ops())
        self.assertIn("create_topography",
                      tool_doc._unproven_minus_live_corpus(),
                      "запись о семантике зелёной строкой не снимается")

    def test_a_branch_scoped_debt_survives_a_green_corpus(self):
        """The debt about the op's BRANCH the corpus does not address in
        principle: it is keyed by NAME.

        `create_dimension`: walls live on 07.28, families and grids not
        checked.
        """
        self.use([{"duration_ms": 500.0, "ok": True,
                   "ops": [{"op": "create_dimension"}]}])
        self.assertIn("create_dimension",
                      tool_doc._unproven_minus_live_corpus())


class TheListCannotRotSilently(unittest.TestCase):

    def test_every_discharged_key_is_a_real_ledger_key(self):
        """A key that has dropped out of the journal must drop out here too —
        otherwise the list guards an entry that no longer exists, and stays
        silent about it."""
        stale = sorted(tool_doc._DISCHARGED_BY_ONE_GREEN_ROW
                       - set(tool_doc.UNPROVEN))
        self.assertEqual(stale, [],
                         "в списке снимаемых есть ключи, которых нет в журнале")

    def test_the_refusal_of_the_corpus_shows_the_whole_ledger(self):
        """No corpus — the WHOLE journal is printed. An instrument's refusal
        is not evidence."""
        old = os.environ.get(witness_corpus.ENV_PATH)
        os.environ[witness_corpus.ENV_PATH] = "/nonexistent/kir_witness.jsonl"
        try:
            self.assertEqual(set(tool_doc._unproven_minus_live_corpus()),
                             set(tool_doc.UNPROVEN))
        finally:
            if old is None:
                os.environ.pop(witness_corpus.ENV_PATH, None)
            else:
                os.environ[witness_corpus.ENV_PATH] = old


if __name__ == "__main__":
    unittest.main()
