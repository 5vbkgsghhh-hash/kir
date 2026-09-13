"""A FAILURE MUST BE ATTRIBUTABLE FROM A SINGLE CORPUS.

WHAT WAS MEASURED (2026-08-09, by enumerating EVERY key of ALL 1306 lines of
`backend/data/telemetry/kir_witness.jsonl`): not one line carries a field
with the failure message — none at all. A consequence measured at the same
time: of 204 red lines, 165 are unattributable BY CONSTRUCTION — 79
`KIR-X999`, 41 `unconfirmed`, 38 `KIR-X003`, 7 assorted ones without
identifiers.

The cost of this was paid the same day: analyzing 12 `create_door` failures
gave a "compiler 5 / Revit 11" split — a split obtained by reading messages
that lived OUTSIDE the corpus. A more precise measurement showed that such a
split should not have been attempted at all: the corpus carried no causes,
so this was not a measurement but hearsay.

Refuting tests stand here for both halves of the fix:

  * THE PRODUCER — `witness_feed` stopped discarding what the diagnostic
    already carried (code, address, field, message, runtime words), and an
    unknown cause is named out loud rather than left as a gap;
  * THE TAXONOMY — `KIR-X003` stopped being two worlds at once; a runtime
    failure got its own `KIR-X009`, and the split did NOT weaken knowledge
    about the rollback;
  * THE LAW "WHAT IS ABSENT STAYS ABSENT" — a successful program must write
    the BYTE-IDENTICAL same line with the same digest as before the fix.

Attribution on the consumer side is checked in
`tests/test_live_op_rates.py` (which also carries a negative control against
backfilling old lines).
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest

from kir import coverage_feed, serving, witness_feed
from kir.diag import Diagnostic

_PROGRAM = {"ir_version": "1.0", "ops": [
    {"op": "create_wall", "id": "W1", "p0_mm": [0, 0], "p1_mm": [4000, 0],
     "height_mm": 3000},
    {"op": "create_door", "id": "D1", "host": {"by": "ref", "value": "W1"},
     "offset_mm": 2000}]}


def _record(**kwargs) -> dict:
    """One record through the PRODUCTION path, read back."""
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "kir_witness.jsonl")
        previous = os.environ.get(witness_feed._ENV)
        os.environ[witness_feed._ENV] = path
        try:
            witness_feed.record_witness(**kwargs)
            with open(path, encoding="utf-8") as handle:
                return json.loads(handle.read().strip())
        finally:
            if previous is None:
                os.environ.pop(witness_feed._ENV, None)
            else:
                os.environ[witness_feed._ENV] = previous


def _runtime_diag(message: str, marker: str = "stale_or_failed") -> dict:
    return serving._translate_runtime(
        {"error": marker,
         "layer": {"error": marker, "op_id": "D1", "message": message}})


class GreenRowStaysByteIdentical(unittest.TestCase):
    """THE LAW: what is absent stays absent.

    A successful program did not fail, so it has neither a failure identity
    nor a named ignorance. Both numbers below were taken by comparing
    against `witness_feed` at `c3e019f6` (the version BEFORE this fix) on
    the very same program: the record's canonical bytes and its checksum
    matched the same prior link. The pin sits here so that the next "while
    I'm at it" field trips the ratchet.

    THE BOUNDARY OF THE LIST BELOW, named 2026-08-13, so it is not read
    wider than it is: the fixture does NOT declare `txn_isolation`, so the
    field is absent from the line (not declared — not written). **A live
    production record carries it**, and the list of ten names here is a
    claim about the LAW "no failure — no failure identity," not a
    description of a live line. The form of a live line is pinned
    separately, in `test_witness_readback_facts.py`; the digests below must
    not be touched — they were taken by comparing against `c3e019f6`, and
    re-pinning them would destroy the measurement itself.
    """

    def setUp(self) -> None:
        self.row = _record(
            program=_PROGRAM, family="write", revit_version="2026", ok=True,
            witness={"geometry_ok": True, "semantic_ok": True,
                     "topology_ok": True},
            duration_ms=250.0,
            outcome={"execution": "committed", "witness": "satisfied",
                     "acceptance": "accepted"},
            result_payload={"W1": {"id": "1001"}, "D1": {"id": "1002"}})
        self.body = {k: v for k, v in self.row.items()
                     if k not in ("ts", "prev_checksum", "checksum")}

    def test_no_refusal_field_appears_on_a_successful_program(self):
        self.assertEqual(
            sorted(self.body),
            ["duration_ms", "family", "ok", "op_outcomes", "ops", "outcome",
             "revit_version", "source", "v", "witness"])

    def test_the_canonical_bytes_are_the_ones_measured_before_the_change(self):
        blob = witness_feed._canonical(self.body)
        self.assertEqual(
            hashlib.sha256(blob).hexdigest(),
            "74d9518637e04a23b7c22d5f9823af71c52897172a7e103ef513b33196eef6d1")

    def test_the_row_digest_is_unmoved(self):
        self.assertEqual(
            witness_feed._row_checksum("0" * 64, self.body),
            "337f019286bfe9e0eea78ba04aa5b88eb72f9f9bbb6e542851fabf19ed0672ba")


class TheRowCarriesTheRefusalsIdentity(unittest.TestCase):
    """What the diagnostic ALREADY carried and what telemetry was discarding."""

    def setUp(self) -> None:
        self.diag = _runtime_diag("NewFamilyInstance (дверь) вернул null")
        self.row = _record(
            program=_PROGRAM, family="write", revit_version="2026", ok=False,
            witness=serving._derive_witness(False, "write", self.diag),
            duration_ms=412.5,
            diag_code=self.diag["code"], diag_op_id=self.diag.get("op_id"),
            diag_field=self.diag.get("field_name"),
            diag_message=self.diag.get("message_ru"),
            diag_detail=self.diag.get("detail"),
            outcome={"execution": "rolled_back", "witness": "incomplete",
                     "acceptance": "not_applicable"})

    def test_the_code_and_the_address_travel_together(self):
        self.assertEqual(self.row["diag_code"], "KIR-X009")
        self.assertEqual(self.row["diag_op_id"], "D1")

    def test_our_own_words_are_persisted(self):
        self.assertIn("отказан в рантайме", self.row["diag_message"])

    def test_the_runtimes_own_words_are_persisted(self):
        """The single distinguishing feature of X999/X003 — and exactly the
        one the corpus did not carry. Without it, the cause of 117 live
        lines is unrecoverable forever."""
        self.assertIn("NewFamilyInstance", self.row["diag_detail"])

    def test_the_cause_says_where_it_lives(self):
        self.assertEqual(self.row["refusal_cause"], "diagnostic")

    def test_free_text_obeys_the_existing_size_discipline(self):
        """The ceiling is not new: the corpus holds exactly this much for
        every violation."""
        row = _record(program=_PROGRAM, family="write", revit_version="2026",
                      ok=False, witness=None, duration_ms=1.0,
                      diag_code="KIR-X999", diag_detail="ы" * 5000,
                      diag_message="я" * 5000)
        self.assertEqual(len(row["diag_detail"]), witness_feed._MAX_TEXT)
        self.assertEqual(len(row["diag_message"]), witness_feed._MAX_TEXT)

    def test_an_empty_message_is_absence_not_an_empty_field(self):
        row = _record(program=_PROGRAM, family="write", revit_version="2026",
                      ok=False, witness=None, duration_ms=1.0,
                      diag_code="KIR-X999", diag_message="   ", diag_field=None)
        self.assertNotIn("diag_message", row)
        self.assertNotIn("diag_field", row)


class AnUnknownCauseIsNamedNotOmitted(unittest.TestCase):
    """"I don't know the cause" and "the cause was not recorded" must look
    different.

    This is the same boundary as "the stage failed" versus "the stage never
    spoke" (§18.2): a missing index and an empty index are different facts.
    """

    def test_a_red_row_without_a_diagnostic_says_so(self):
        row = _record(program=_PROGRAM, family="write", revit_version="2026",
                      ok=False, witness=None, duration_ms=88.0)
        self.assertEqual(row["refusal_cause"], "unknown")

    def test_violations_are_named_as_the_place_of_the_cause(self):
        row = _record(program=_PROGRAM, family="write", revit_version="2026",
                      ok=False, witness=None, duration_ms=88.0,
                      violations=["D1: mirrored state mismatch (semantic)"])
        self.assertEqual(row["refusal_cause"], "violations")

    def test_a_committed_program_refused_by_acceptance_says_acceptance(self):
        row = _record(program=_PROGRAM, family="write", revit_version="2026",
                      ok=False, witness=None, duration_ms=88.0,
                      outcome={"execution": "committed", "witness": "satisfied",
                               "acceptance": "inconclusive"})
        self.assertEqual(row["refusal_cause"], "acceptance")

    def test_a_green_row_has_no_such_field_at_all(self):
        row = _record(program=_PROGRAM, family="query", revit_version="2026",
                      ok=True, witness={"read_only": True}, duration_ms=12.0)
        self.assertNotIn("refusal_cause", row)


class OneCodeIsOneWorld(unittest.TestCase):
    """`KIR-X003` covered TWO worlds, and only the text told them apart.

    `__Refuse` tags every typed emitter failure with a single transport
    marker `stale_or_failed`, so "the element disappeared between grounding
    and execution" and "Revit refused to do it" traveled under one code. A
    reader of the corpus sees the CODE, not the prose — so the text fix
    (07-27) cured the message and did not cure the taxonomy.
    """

    def test_genuine_drift_keeps_its_own_code(self):
        diag = _runtime_diag(
            "base_level: уровень не найден (модель изменилась после grounding)")
        self.assertEqual(diag["code"], "KIR-X003")
        self.assertIn("исчез", diag["message_ru"])

    def test_a_runtime_refusal_is_no_longer_called_drift(self):
        diag = _runtime_diag("NewElbowFitting: failed to insert elbow")
        self.assertEqual(diag["code"], "KIR-X009")
        self.assertNotIn("исчез", diag["message_ru"])

    def test_the_wrong_type_guard_is_not_drift_either(self):
        """The `_level_expr` branch, which ITSELF says it could not
        determine the cause: it has no right to travel under the code "the
        model has drifted."""
        diag = _runtime_diag(
            "id уровня резолвится не в Level, а в Wall — причина (дрейф модели "
            "или неверный id) не определена рантаймом")
        self.assertEqual(diag["code"], "KIR-X009")

    def test_both_worlds_still_carry_the_runtime_text(self):
        for message in ("уровень не найден (модель изменилась после grounding)",
                        "NewFamilyInstance (дверь) вернул null"):
            self.assertIn("detail", _runtime_diag(message))

    def test_splitting_the_code_did_not_weaken_the_rollback_proof(self):
        """A NEGATIVE CONTROL ON THE FIX ITSELF. Both forms come from
        `refuse_stmt`, and it renders RollBack/throw BEFORE the commit —
        meaning they prove the rollback equally. Were X009 to drop out of
        the list, splitting the code would turn a proven rollback into
        `unconfirmed`, i.e. it would WORSEN knowledge of the effect for the
        sake of a tidier taxonomy."""
        self.assertIn("KIR-X003", serving._ROLLBACK_PROVEN_CODES)
        self.assertIn("KIR-X009", serving._ROLLBACK_PROVEN_CODES)
        self.assertIn("KIR-X004", serving._ROLLBACK_PROVEN_CODES)


class PreEffectRefusalKeepsItsAddress(unittest.TestCase):
    """A failure BEFORE execution lives in its own corpus
    (`kir_rejections.jsonl`), and the same hole was already there:
    `op_requested` names the operation's NAME, while the diagnostic carried
    `op_id` and `field_name`, and the feed was discarding them."""

    def _events(self, diag: Diagnostic) -> list:
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "kir_rejections.jsonl")
            previous = os.environ.get(coverage_feed._ENV)
            os.environ[coverage_feed._ENV] = path
            try:
                coverage_feed.record_rejections(
                    [diag], [{"op": "create_door", "id": "D1"}])
                with open(path, encoding="utf-8") as handle:
                    return [json.loads(line) for line in handle if line.strip()]
            finally:
                if previous is None:
                    os.environ.pop(coverage_feed._ENV, None)
                else:
                    os.environ[coverage_feed._ENV] = previous

    def test_the_instance_and_the_field_survive(self):
        event, = self._events(Diagnostic(
            code="KIR-G102", message_ru="тип двери неоднозначен",
            op_index=0, op_id="D1", field_name="symbol"))
        self.assertEqual(event["op_id"], "D1")
        self.assertEqual(event["field_name"], "symbol")
        self.assertEqual(event["diag_code"], "KIR-G102")

    def test_absence_stays_absence(self):
        event, = self._events(Diagnostic(
            code="KIR-P004", message_ru="ir_version не поддержан"))
        self.assertNotIn("op_id", event)
        self.assertNotIn("field_name", event)


if __name__ == "__main__":
    unittest.main()
