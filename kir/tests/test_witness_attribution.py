"""A measurer must be able to name the OPERATION that failed.

07.31: parsing the witness corpus ran into the instrument's own limits. The
corpus records three things separately — the list of ops (`ops`),
per-operation outcomes (`op_outcomes`), and postcondition violations
(`violations`) — but `ops` holds only the operation's NAME, while outcomes
and violations are addressed by its IDENTIFIER. There is nothing to link
one to the other.

The consequence was measured, not assumed: for a program of `create_wall` +
`create_door` where the door failed, the only available way to count a rate
is to attribute the failure to BOTH operations. And that is how it was
counted: `create_wall` came out at 64.2%, even though the wall was being
built successfully in those runs. A number obtained by such a measurer can
be neither published nor used as a target.

This is not about tidiness of the record. It is about the fact that four of
the five live failures of basic ops are X004 with a named list of
violations, and that whole piece of evidence sits in the file UNLINKED.

Second: truncation. `_MAX_VIOLATIONS` silently cuts the list — a
twenty-beam program with twenty violations will leave ten in the corpus and
no trace that there were more. Silent truncation reads as "that's all there
was" — exactly the kind of silence the whole system is built against.
"""
import json
import os
import tempfile
import unittest
from unittest import mock

from kir import witness_feed


def _read(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


class ViolationIsAttributableToAnOp(unittest.TestCase):
    """A live sample from 07.21: the wall built, the door refused."""

    PROGRAM = {"ops": [
        {"op": "create_wall", "id": "W1", "p0_mm": [0, 0], "p1_mm": [6000, 0],
         "height_mm": 3000},
        {"op": "create_door", "id": "PD", "host": {"by": "ref", "value": "W1"},
         "offset_mm": 3000},
    ]}
    VIOLATIONS = ["PD: mirrored state mismatch (semantic)",
                  "PD: facing flip state mismatch (semantic)"]

    def _record(self, path, **over):
        kw = dict(program=self.PROGRAM, family="write", revit_version="2026",
                  ok=False, witness={"geometry_ok": True, "semantic_ok": False,
                                     "topology_ok": True, "committed": False},
                  duration_ms=812.0, diag_code="KIR-X004",
                  violations=list(self.VIOLATIONS))
        kw.update(over)
        with mock.patch.dict(os.environ, {"KIR_WITNESS_PATH": path}):
            witness_feed.record_witness(**kw)

    def test_ops_carry_the_id_the_violation_names(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "w.jsonl")
            self._record(path)
            row = _read(path)[0]
            by_id = {o.get("id"): o.get("op") for o in row["ops"]}
            self.assertEqual(by_id.get("W1"), "create_wall")
            self.assertEqual(by_id.get("PD"), "create_door")

    def test_failing_op_is_nameable_from_the_row_alone(self):
        """This is all done for exactly this: to say, from one line of the
        corpus, that it was PRECISELY the door that refused, and not the
        wall."""
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "w.jsonl")
            self._record(path)
            row = _read(path)[0]
            by_id = {o.get("id"): o.get("op") for o in row["ops"]}
            blamed = {by_id[v.split(":", 1)[0].strip()]
                      for v in row["violations"]
                      if v.split(":", 1)[0].strip() in by_id}
            self.assertEqual(blamed, {"create_door"})
            self.assertNotIn("create_wall", blamed)

    def test_id_does_not_change_the_skeleton_hash(self):
        """The skeleton stays stable under renaming — the id lives NEXT TO
        it, not inside it."""
        a = dict(self.PROGRAM["ops"][0])
        b = dict(a, id="совсем-другое-имя")
        self.assertEqual(witness_feed.op_skeleton_hash(a),
                         witness_feed.op_skeleton_hash(b))
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "w.jsonl")
            self._record(path)
            row = _read(path)[0]
            self.assertNotIn("6000", json.dumps(row["ops"], ensure_ascii=False))

    def test_missing_id_is_recorded_as_absent_not_invented(self):
        prog = {"ops": [{"op": "create_wall", "p0_mm": [0, 0]}]}
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "w.jsonl")
            self._record(path, program=prog, violations=None)
            row = _read(path)[0]
            self.assertEqual(row["ops"][0]["op"], "create_wall")
            self.assertIsNone(row["ops"][0].get("id"))


class TruncationIsNamed(unittest.TestCase):
    """A twenty-beam program from 07.27: twenty violations, ten in the file."""

    def test_violation_overflow_is_counted(self):
        n = witness_feed._MAX_VIOLATIONS + 7
        prog = {"ops": [{"op": "create_beam", "id": f"b{i}"} for i in range(n)]}
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "w.jsonl")
            with mock.patch.dict(os.environ, {"KIR_WITNESS_PATH": path}):
                witness_feed.record_witness(
                    program=prog, family="write", revit_version="2023",
                    ok=False, witness=None, duration_ms=5.0,
                    diag_code="KIR-X004",
                    violations=[f"b{i}: level binding mismatch (topology)"
                                for i in range(n)])
            row = _read(path)[0]
            self.assertEqual(len(row["violations"]),
                             witness_feed._MAX_VIOLATIONS)
            self.assertEqual(row.get("violations_truncated"), 7)

    def test_no_overflow_no_counter(self):
        prog = {"ops": [{"op": "create_beam", "id": "b0"}]}
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "w.jsonl")
            with mock.patch.dict(os.environ, {"KIR_WITNESS_PATH": path}):
                witness_feed.record_witness(
                    program=prog, family="write", revit_version="2023",
                    ok=False, witness=None, duration_ms=5.0,
                    diag_code="KIR-X004",
                    violations=["b0: level binding mismatch (topology)"])
            row = _read(path)[0]
            self.assertNotIn("violations_truncated", row)

    def test_a_whole_materialiser_chunk_fits_in_one_record(self):
        """The record's ceiling must cover the LARGEST program the system is
        able to execute — otherwise the corpus measures a third of the work.

        Measured on 07.31 by a live loop on the Snowdon sample: 26 chunks,
        6344 operation executions, 833 made it into the journal. The
        remaining 5511 are honestly marked as truncated — and this is
        precisely why `create_duct` fell short on evidence (34 recorded
        versus 181 executed) and did not clear 95%, even though it did not
        refuse ONCE. The compiler performed flawlessly; the measurer fell
        short.

        The bar was not set by eye: `MAX_VALIDATED_OPS` is the ceiling of a
        program after macro expansion, that is, by construction nothing
        executable is ever larger. The cost is measured: a line for 250
        operations weighs ~25 KB, the whole loop ~640 KB against a corpus of
        a megabyte."""
        from kir.compiler import MAX_VALIDATED_OPS
        self.assertGreaterEqual(witness_feed._MAX_OPS_PER_RECORD,
                                MAX_VALIDATED_OPS)
        n = 250          # the materializer's chunk_target
        prog = {"ops": [{"op": "create_pipe", "id": f"p{i}"} for i in range(n)]}
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "w.jsonl")
            with mock.patch.dict(os.environ, {"KIR_WITNESS_PATH": path}):
                witness_feed.record_witness(
                    program=prog, family="write", revit_version="2026",
                    ok=True, witness={"geometry_ok": True}, duration_ms=14200.0,
                    result_payload={f"p{i}": {"id": str(i)} for i in range(n)})
            row = _read(path)[0]
            self.assertEqual(len(row["ops"]), n)
            self.assertNotIn("ops_truncated", row)
            self.assertEqual(len(row["op_outcomes"]), n)
            self.assertNotIn("op_outcomes_truncated", row)

    def test_outcome_overflow_is_counted(self):
        n = witness_feed._MAX_OPS_PER_RECORD + 3
        prog = {"ops": [{"op": "create_pipe", "id": f"p{i}"} for i in range(n)]}
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "w.jsonl")
            with mock.patch.dict(os.environ, {"KIR_WITNESS_PATH": path}):
                witness_feed.record_witness(
                    program=prog, family="write", revit_version="2026",
                    ok=True, witness={"geometry_ok": True}, duration_ms=5.0,
                    result_payload={f"p{i}": {"id": str(i)} for i in range(n)})
            row = _read(path)[0]
            self.assertEqual(len(row["op_outcomes"]),
                             witness_feed._MAX_OPS_PER_RECORD)
            self.assertEqual(row.get("op_outcomes_truncated"), 3)


if __name__ == "__main__":
    unittest.main()
