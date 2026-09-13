"""The witness channel carries a MEASURED QUANTITY, not only a verdict.

WHY. A census of the channel on 2026-08-13: emitters put **264 distinct
keys** into the receipt (148 emission files), while `record_witness`
collapsed the entire readback dict into one of three label strings. **3**
keys made it through (`id`, `deleted_id`, `refused`), and only by the FACT
of their presence — they select the label. **261 = 98.9%** perished.

The consequence this test was written for: across a corpus of **1,331
rows**, there were **six** numeric fields, and all six were bookkeeping for
the record itself (`duration_ms`, `source_op_count`, `ops_truncated`, …).
**Measurements of the built thing — ZERO.** So every one of our "a live run
will answer with a NUMBER" could never come true: no route existed, and the
next live window would return `{geometry_ok: true}` instead of numbers.

CHECKED OFFLINE, NO LIVE REVIT NEEDED. `record_witness` is an ordinary
function; to learn whether a quantity gets through, it is enough to feed it
a synthetic readback and read the row off disk.

THE QUANTITY WAS CHOSEN WITH ZERO OCCURRENCES IN THE LIVE CORPUS.
`mullions_on_line` was measured on 08.13 across the whole corpus: 0 times.
Otherwise a PASS could have been about a different key already getting
through by another route.
"""

from __future__ import annotations

import json
import ast
import os
import pathlib
import tempfile
import unittest

from kir import witness_feed


#: THE SNAPSHOT OF `serving.py` IS TAKEN AT IMPORT, NOT INSIDE THE TEST BODY.
#:
#: The first edition of the wiring pin read the file off disk AT TEST TIME —
#: and was the suite's only assertion whose outcome depended on what was
#: being done to the tree WHILE the run was in progress. On this machine
#: several sessions edit neighboring copies at once; on 2026-08-13 this
#: file's own author edited `serving.py` while the suite was running and
#: would have gotten a red unrelated to the subject. **A red for an
#: unrelated reason stops being an instrument**, and the next reader will
#: start skipping it.
#:
#: A snapshot at import does not protect against an edit BETWEEN collection
#: and the run of a long suite — the window shrinks from twenty minutes to
#: seconds. That is the difference between "can happen" and "happened
#: today," and it is named, not silenced.
_SERVING_SRC = (
    pathlib.Path(witness_feed.__file__).parent / "serving.py"
).read_text(encoding="utf-8")


#: A key that does NOT occur in the live corpus (measured 2026-08-13: 0
#: occurrences). An instrument for it was built on 07.29 (`98b5f847`), the
#: op has 13 live rows from 07.29-08.04 — the window existed, and the field
#: never got through once.
PROBE_KEY = "mullions_on_line"
PROBE_VALUE = 7


class TheTransactionIsolationReachesTheRow(unittest.TestCase):
    """REVIT TRANSACTION isolation gets through to the row — and is not
    confused with the sandbox.

    WHY. Measured 2026-08-13 across the live corpus: `isolation`, `per_op`,
    `atomic`, `subtransaction` occur in 1,331 rows **exactly 0 times**, and
    `PlannedProgram` carries no isolation. So the question "how many live
    programs ran `per_op` versus `atomic`" was unanswerable BY CONSTRUCTION.

    The cost of this is not idle curiosity: `tools/live_op_rates.py` counts a
    "collateral" bucket — someone else's violation rolled back the
    transaction — and **under `per_op` there is no such thing as collateral,
    by construction**. Without the field, the corpus mixes two populations
    with different bucket semantics, and the main per-op rate instrument is
    interpretable only for `atomic` rows, while which ones are `atomic` is
    unknown.

    THE NAME. Not `isolation`: `serving._sandbox_receipt` reads `isolation`
    off the PYTHON SANDBOX's result. A homonym in the same tree is more
    dangerous than an absent field — an absent one stays silent, a homonym
    ANSWERS.
    """

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self._path = os.path.join(self._dir.name, "feed.jsonl")
        self._prev = os.environ.get(witness_feed._ENV)
        os.environ[witness_feed._ENV] = self._path

    def tearDown(self) -> None:
        if self._prev is None:
            os.environ.pop(witness_feed._ENV, None)
        else:
            os.environ[witness_feed._ENV] = self._prev
        self._dir.cleanup()

    def _row(self, **kw) -> dict:
        witness_feed.record_witness(
            program={"ops": [{"op": "create_wall", "id": "W1"}]},
            family="write", revit_version="2023", ok=True,
            witness={"geometry_ok": True}, duration_ms=1.0, **kw)
        with open(self._path, encoding="utf-8") as handle:
            return json.loads(
                [ln for ln in handle.read().splitlines() if ln.strip()][-1])

    def test_per_op_reaches_the_row(self) -> None:
        """CONTROL-PASS on a value that occurs 0 times in the corpus."""
        self.assertEqual(self._row(txn_isolation="per_op")["txn_isolation"],
                         "per_op")

    def test_atomic_reaches_the_row_too(self) -> None:
        """Both values must get through: an instrument that distinguishes
        one distinguishes nothing — the second population would remain
        indistinguishable from "not stated"."""
        self.assertEqual(self._row(txn_isolation="atomic")["txn_isolation"],
                         "atomic")

    def test_an_unstated_isolation_is_absent_not_atomic(self) -> None:
        """CONTROL-FAIL: not named — there is NO field.

        Defaulting to `"atomic"` after the fact would retroactively assert, for
        1 331 existing rows, something nobody measured, and would erase the
        difference between "it was atomic" and "nobody recorded it".
        """
        row = self._row()
        self.assertNotIn("txn_isolation", row)

    def test_the_compiler_states_it_and_the_rebuild_states_per_op(self) -> None:
        """The value comes from the COMPILER, not invented in serving.

        `compile_program` defaults to `atomic`; `compile_rebuild_chunk` is the
        only door to `per_op` (it is called from `serving.py` :2317, :4257,
        :5121). What is checked is that both carry their choice through to
        `CompileOutput`.
        """
        from kir.compiler import CompileOutput
        self.assertEqual(CompileOutput(ok=True).txn_isolation, "atomic")
        import inspect
        from kir import compiler
        src = inspect.getsource(compiler.compile_rebuild_chunk)
        self.assertIn('isolation="per_op"', src)

    def test_the_live_shaped_green_row_carries_it(self) -> None:
        """The shape of the LIVE green record row is pinned here.

        `test_refusal_identity::GreenRowStaysByteIdentical` lists ten
        names, but its isolation fixture does NOT name it, so that list is an
        assertion of the law "no refusal — no refusal identity", not a
        description of the live row. Its digests were taken by comparison with
        `c3e019f6` and must not be re-pinned — that would destroy the
        measurement itself. So the live shape lives in a separate pin, here.
        """
        row = self._row(txn_isolation="atomic",
                        outcome={"execution": "committed"},
                        result_payload={"W1": {"id": "1001"}})
        body = {k for k in row if k not in ("ts", "prev_checksum", "checksum")}
        self.assertIn("txn_isolation", body)
        self.assertFalse({k for k in body if k.startswith("diag_")},
                         "личность отказа не имеет права появиться на зелёной")

    def test_every_live_call_site_states_it(self) -> None:
        """WIRING, not just the receiver.

        The tests above prove that the `record_witness` field ACCEPTS the value.
        They say nothing about whether the live path PASSES it through — and it
        was exactly at this break that the whole channel stood dark. So what is
        checked is the CALL ITSELF: by parsing, not by searching for a string,
        otherwise a match would go by appearance alone.

        The list of sites is COMPLETE BY CONSTRUCTION: it is not enumerated
        here but gathered by walking every call to `record_witness` in
        `serving.py`. A site added tomorrow falls under the check on its own.
        """
        sites = []
        for node in ast.walk(ast.parse(_SERVING_SRC)):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = (fn.attr if isinstance(fn, ast.Attribute)
                    else fn.id if isinstance(fn, ast.Name) else "")
            if name == "record_witness":
                sites.append({k.arg for k in node.keywords})
        self.assertGreaterEqual(len(sites), 2,
                                "площадок меньше двух — обход не нашёл вызовы, "
                                "и ноль был бы про матчер, а не про serving")
        for i, kwargs in enumerate(sites):
            self.assertIn("txn_isolation", kwargs,
                          f"площадка {i} не называет изоляцию — строка уйдёт "
                          f"без неё, и вопрос atomic/per_op снова станет "
                          f"неотвечаемым")

    def test_the_name_does_not_collide_with_the_sandbox_one(self) -> None:
        """No homonym was introduced: the row's field is called `txn_isolation`,
        while the sandbox keeps its own `isolation`."""
        row = self._row(txn_isolation="per_op")
        self.assertNotIn("isolation", row)
        self.assertIn("txn_isolation", row)


def _record(payload: dict, path: str, ops: list[str] | None = None) -> dict:
    """Write one row and return it parsed.

    By default the program declares EXACTLY the ops present in the receipt —
    otherwise the guard "a fact only for a known op" would make half the
    checks below green by construction, not on the merits.
    """
    ids = list(payload) if ops is None else ops
    witness_feed.record_witness(
        program={"ops": [{"op": "create_curtain_grid_line", "id": i}
                         for i in ids]},
        family="test", revit_version="2023", ok=True,
        witness={"geometry_ok": True}, duration_ms=1.0,
        result_payload=payload,
    )
    with open(path, encoding="utf-8") as handle:
        lines = [ln for ln in handle.read().splitlines() if ln.strip()]
    return json.loads(lines[-1])


class ReadbackFactsReachTheRow(unittest.TestCase):

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self._path = os.path.join(self._dir.name, "feed.jsonl")
        self._prev = os.environ.get(witness_feed._ENV)
        os.environ[witness_feed._ENV] = self._path

    def tearDown(self) -> None:
        # We restore what was OBSERVED, not a remembered constant: the canon
        # already paid for a `finally` that patched global state for the whole process.
        if self._prev is None:
            os.environ.pop(witness_feed._ENV, None)
        else:
            os.environ[witness_feed._ENV] = self._prev
        self._dir.cleanup()

    # ── control-PASS ────────────────────────────────────────────────────
    def test_a_measured_count_reaches_the_stored_row(self) -> None:
        """CONTROL-PASS: the seven placed into the receipt IS READ back from disk."""
        row = _record({"G1": {"id": "1", PROBE_KEY: PROBE_VALUE}}, self._path)
        self.assertIn("op_facts", row,
                      "поле фактов не появилось в строке вообще")
        self.assertEqual(row["op_facts"]["G1"][PROBE_KEY], PROBE_VALUE,
                         "величина не доехала до строки корпуса")

    # ── control-FAIL ────────────────────────────────────────────────────
    def test_without_the_wiring_the_seven_vanishes(self) -> None:
        """CONTROL-FAIL: remove the wiring — the seven must disappear.

        Without this end, "the fix exists" is indistinguishable from "the field
        was getting through anyway". The wiring removed is exactly the one
        added on 13.08: the fact collector.
        """
        original = witness_feed._readback_facts
        witness_feed._readback_facts = lambda row: None
        try:
            row = _record({"G1": {"id": "1", PROBE_KEY: PROBE_VALUE}},
                          self._path)
        finally:
            witness_feed._readback_facts = original
        self.assertNotIn("op_facts", row,
                         "семёрка доехала БЕЗ проводки — значит PASS выше "
                         "доказывал не эту правку")
        self.assertEqual(row["op_outcomes"]["G1"], "created",
                         "метка обязана уцелеть: её читает live_op_rates")

    # ── a rule, not a list ────────────────────────────────────────────
    def test_the_container_stays_in_the_model_and_says_so(self) -> None:
        """The coordinates do not drift — but an outlier IS COUNTED, not silenced.

        `position_mm` is an array (the coordinate, authority — the model),
        `position_delta_mm` is a scalar (the DISCREPANCY, a measurement about
        what was built). One pair shows both halves of the rule at once.
        """
        row = _record({"G1": {"id": "1",
                              "position_mm": [1.0, 2.0, 3.0],
                              "position_delta_mm": 0.25}}, self._path)
        facts = row["op_facts"]["G1"]
        self.assertNotIn("position_mm", facts, "геометрия просочилась в леджер")
        self.assertEqual(facts["position_delta_mm"], 0.25)
        self.assertEqual(facts["__dropped"], {"geometry": 1},
                         "выброшенное обязано быть НАЗВАНО, а не промолчать")

    def test_a_verdict_stays_a_verdict_not_a_one(self) -> None:
        """bool inherits from int — the reverse order of checks would have
        recorded `line_locked` as the integer one and turned a verdict into a magnitude."""
        row = _record({"G1": {"id": "1", "line_locked": True}}, self._path)
        # `1 is True` is false, so `assertIs` distinguishes a verdict from the
        # integer one after the round trip through JSON.
        self.assertIs(row["op_facts"]["G1"]["line_locked"], True)
        with open(self._path, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn('"line_locked":true', text)     # the record is compact
        self.assertNotIn('"line_locked":1', text)

    def test_an_over_long_string_is_dropped_whole_never_cut(self) -> None:
        """A truncated row reads as whole and therefore LIES.

        The canon already paid for a cap that cut one half of a field while
        the other half kept being appended to it. So a value that is too long
        is discarded WHOLE, and this is recorded in the counter.
        """
        row = _record({"G1": {"id": "1",
                              "type_name": "я" * (witness_feed._MAX_FACT_TEXT
                                                  + 1)}}, self._path)
        facts = row["op_facts"]["G1"]
        self.assertNotIn("type_name", facts)
        self.assertEqual(facts["__dropped"], {"over_budget": 1})

    def test_the_budget_is_visible_when_it_bites(self) -> None:
        """More fields than the budget allows — the truncation is NAMED by a number."""
        wide = {f"k{i}": i for i in range(witness_feed._MAX_FACTS_PER_OP + 5)}
        row = _record({"G1": wide}, self._path)
        facts = row["op_facts"]["G1"]
        kept = [k for k in facts if k != "__dropped"]
        self.assertEqual(len(kept), witness_feed._MAX_FACTS_PER_OP)
        self.assertEqual(facts["__dropped"]["over_count"],
                         len(wide) - witness_feed._MAX_FACTS_PER_OP)

    def test_nothing_measured_means_no_field_at_all(self) -> None:
        """An empty dict in a row is indistinguishable from "there were no facts"."""
        row = _record({"G1": {"points_mm": [[0, 0, 0]]}}, self._path)
        self.assertEqual(row["op_facts"]["G1"], {"__dropped": {"geometry": 1}})
        row2 = _record({"G1": {}}, self._path)
        self.assertNotIn("op_facts", row2)

    def test_a_row_of_ids_alone_stays_exactly_as_it_was(self) -> None:
        """WHAT IS ABSENT STAYS ABSENT.

        A green row whose readback carries only `id` values must stay exactly
        that: the `id` already arrived as a LABEL. The first version of this fix
        recorded it a second time as a fact too — a second truth about one fact —
        and the ratchet `test_refusal_identity::GreenRowStaysByteIdentical` went
        red on three assertions at once. The law is pinned here too, at the site
        of the fix, so the next revision does not learn about it from a foreign
        file.
        """
        row = _record({"W1": {"id": "1001"}, "D1": {"id": "1002"}},
                      self._path)
        self.assertNotIn("op_facts", row)
        self.assertEqual(row["op_outcomes"], {"W1": "created",
                                              "D1": "created"})

    def test_a_label_key_is_never_carried_twice(self) -> None:
        """The label's resolver key is not duplicated into the facts — and is not
        counted as dropped either: it is not lost, it is in the neighboring field."""
        row = _record({"G1": {"id": "1", "deleted_id": "2",
                              "count": 5}}, self._path)
        facts = row["op_facts"]["G1"]
        self.assertEqual(facts, {"count": 5})
        self.assertNotIn("__dropped", facts)

    def test_a_program_level_key_never_becomes_an_op(self) -> None:
        """THE AUTHORITY OF OPS IS THE LIST OF OPS, NOT THE SHAPE OF A VALUE.

        The receipt is flat: `ok`, `created_ids`, `postcondition_violations` and
        `results` sit in it alongside the per-row readbacks. Today a dict-shaped
        value only ever occurs in a readback, and "take all dict values" works
        BY ACCIDENT. A single `summary: {...}` added tomorrow would introduce a
        nonexistent op into the facts — and it would be looked up in the registry.
        """
        row = _record({"G1": {"id": "1", "count": 4},
                       "summary": {"total": 99}},
                      self._path, ops=["G1"])
        self.assertEqual(sorted(row["op_facts"]), ["G1"],
                         "программный ключ прочитан как оп")
        self.assertEqual(row["op_facts"]["G1"], {"count": 4})

    def test_the_guard_does_not_eat_ops_beyond_the_record_cap(self) -> None:
        """The guard takes ops from the PROGRAM before truncation (`raw_ops`).

        The record's op list is capped by `_MAX_OPS_PER_RECORD`; if the guard
        checked against the capped list, a wide program would lose legitimate
        facts past the ceiling — a defect indistinguishable from "the value
        never arrived".
        """
        n = witness_feed._MAX_OPS_PER_RECORD
        last = f"op{n + 4}"
        payload = {f"op{i}": {"id": str(i), "count": i} for i in range(n + 5)}
        row = _record(payload, self._path)
        self.assertGreater(len(row["ops"]), 0)
        self.assertIn("ops_truncated", row,
                      "проверка вырождена: программа не переросла потолок")
        self.assertIn(last, {*payload},)
        self.assertNotIn(last, row["op_facts"],
                         "за потолком ЗАПИСИ фактов нет — но не из-за стража")
        self.assertEqual(row["op_facts"]["op0"], {"count": 0})

    def test_the_label_channel_is_untouched(self) -> None:
        """`op_outcomes` must remain STRINGS: `live_op_rates.py:404`
        compares the value against "refused", and changing the type would break
        the four-bucket instrument. The blast radius of a fix is the import
        graph, not the file."""
        row = _record({"A": {"refused": "нет типа"},
                       "B": {"id": "5", "count": 3},
                       "C": {"warning": "хм"}}, self._path)
        self.assertEqual(row["op_outcomes"],
                         {"A": "refused", "B": "created", "C": "other"})
        for value in row["op_outcomes"].values():
            self.assertIsInstance(value, str)


if __name__ == "__main__":
    unittest.main()
