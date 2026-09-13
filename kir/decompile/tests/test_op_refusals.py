# -*- coding: utf-8 -*-
"""Task #25: a per-operation refusal inside a COMMITTED chunk.

The reason — reassembly #11 (v18): 122 curtain wall grid lines were
expected, ZERO were created, and 113 of them sat in chunks with
``Committed`` status. The run reported success, the lines went to
missing, and the reason was preserved nowhere: the receipt carried only
``element_ids``.

Yet the reason had been surfacing from the very start. In
``isolation="per_op"``, emission puts it in the same ``result`` the ids
are taken from::

    __rf["refused"] = <text>;  __rf["refused_op_id"] = <op_id>;
    __results[oid] = __rf;

So what is checked here is not "can Revit say it" — what is checked is
that we stopped throwing away what was said, and that the census law
catches an op with no outcome.

VERBATIM: chunk 6's payload below is the real shape of the output (198
walls created, 37 lines refused, 15 cells changed type in place), 250
ops.
"""
from __future__ import annotations

import unittest

from kir.contracts import CommitReceipt, ContractSchemaError, RunId
from kir.serving import collect_op_refusals, count_ops_without_element

RUN_ID = RunId("d51b64480a14a8b4")
PROGRAM_ID = "01745acbe44a476787c20eed37266dc55772085fa1c0b080d7ae1b4f5ecf4d5c"
# The verbatim refusal text emission builds for a grid line when the
# strict run-stamp block (path A5 only) throws on the missing Comments
# parameter.
LINE_REFUSAL = (
    "линия разрезки не принимает штамп прогона (A5 stamp write failed: "
    "A5 stamp parameter missing) — созданный, но непомеченный элемент "
    "сломал бы сверку пересборки")


def chunk6_payload(walls=198, lines=37, panels=15):
    """The output shape of chunk 6 of run #11: walls + refused lines +
    cells."""
    result = {}
    for index in range(walls):
        result[f"w{index}"] = {"id": str(11472000 + index), "created": True}
    for index in range(lines):
        result[f"g{index}"] = {"refused": LINE_REFUSAL,
                               "refused_op_id": f"g{index}"}
    for index in range(panels):
        result[f"p{index}"] = {"id": str(9000000 + index), "created": False}
    return {"ok": True, "result": result}


def chunk6_program(walls=198, lines=37, panels=15):
    ops = [{"op": "create_wall", "id": f"w{i}"} for i in range(walls)]
    ops += [{"op": "create_curtain_grid_line", "id": f"g{i}",
             "host": {"by": "ref", "value": f"w{i}"}} for i in range(lines)]
    ops += [{"op": "set_curtain_panel", "id": f"p{i}",
             "host": {"by": "ref", "value": f"w{i}"}} for i in range(panels)]
    return {"ir_version": "1.0", "ops": ops}


def receipt(**over):
    base = dict(
        run_id=RUN_ID, operation="rebuild", element_ids=(),
        bridge_error=False, commit_confirmed=True, commit_status="Committed",
        program_id=PROGRAM_ID, document_revision="1:a:b")
    base.update(over)
    return CommitReceipt(**base)


class HarvestingRefusals(unittest.TestCase):

    def test_01_refusals_are_read_from_the_same_result_map(self):
        """Refusals are lifted from the same place ids are — on the
        live shape of chunk 6."""
        rows = collect_op_refusals(chunk6_payload(), chunk6_program())
        self.assertEqual(len(rows), 37)
        first = rows[0]
        self.assertEqual(first["op_name"], "create_curtain_grid_line")
        self.assertEqual(first["intent"], {"by": "ref", "value": "w0"})
        # The reason VERBATIM: this exact text named the culprit in
        # chunk 9's analysis.
        self.assertEqual(first["reason"], LINE_REFUSAL)
        self.assertIn("штамп прогона", first["reason"])
        # The order is deterministic — the receipt goes to the journal.
        self.assertEqual([r["op_id"] for r in rows],
                         sorted(r["op_id"] for r in rows))

    def test_02_no_element_counts_only_explicit_created_false(self):
        """`created:false` is a semantic value; a row without an id and
        without a refusal is NOT that."""
        self.assertEqual(count_ops_without_element(chunk6_payload()), 15)
        silent = {"ok": True, "result": {"x": {"op": "create_wall"}}}
        self.assertEqual(count_ops_without_element(silent), 0)

    def test_03_the_chunk_balances_end_to_end(self):
        """198 created + 37 refused + 15 without an element == 250
        ops."""
        payload, program = chunk6_payload(), chunk6_program()
        rows = collect_op_refusals(payload, program)
        created = [v["id"] for v in payload["result"].values()
                   if v.get("id") and v.get("created") is True]
        built = receipt(element_ids=tuple(created), op_refusals=rows,
                        ops_total=len(program["ops"]),
                        ops_no_element=count_ops_without_element(payload))
        self.assertEqual(len(built.element_ids), 198)
        self.assertEqual(len(built.op_refusals), 37)
        self.assertEqual(built.ops_no_element, 15)
        self.assertEqual(built.ops_total, 250)
        out = built.to_dict()
        self.assertEqual(out["schema_version"], "a5-commit-receipt/3")
        self.assertEqual(out["ops_refused"], 37)
        self.assertEqual(
            CommitReceipt.from_dict(out).op_refusals, built.op_refusals)


class CensusLaw(unittest.TestCase):

    def test_04_an_op_without_an_outcome_is_refused(self):
        """REFUTING: a receipt with a mismatch must FAIL to build.

        This is exactly the "silently not created" class: 250 ops in
        the plan, 249 outcomes.
        """
        with self.assertRaises(ContractSchemaError) as caught:
            receipt(element_ids=("1", "2"), ops_total=250, ops_no_element=0)
        self.assertIn("не сходятся", str(caught.exception))

    def test_05_legacy_receipts_stay_readable(self):
        """ops_total=0 turns the law off: journals #9-#11 must still
        replay."""
        legacy = receipt(element_ids=("1", "2")).to_dict()
        self.assertNotIn("ops_total", legacy)
        self.assertEqual(len(CommitReceipt.from_dict(legacy).element_ids), 2)
        old = dict(legacy, schema_version="a5-commit-receipt/2")
        self.assertEqual(len(CommitReceipt.from_dict(old).element_ids), 2)

    def test_06_law_assumes_one_element_per_op(self):
        """AN ASSUMPTION RECORDED DELIBERATELY: one op — no more than
        one id.

        The law equates the NUMBER OF CREATED IDS with the number of
        successful ops. Today, in reassembly, this holds (the v18
        retro-balance matched on every committed chunk), but this is a
        property of the current set of ops, not a law of nature: a
        multi-element op (move_elements, with a set of targets already
        nearby) will produce MORE ids than ops, and the receipt will
        stop building.

        This test exists so that day is a DELIBERATE RED with an
        understandable name, not a mystery in a live run. To the author
        of the multi-element op: count the law BY OPS (carry
        ops_created in the receipt), and do NOT weaken the comparison —
        otherwise the assumption's removal would take with it the whole
        "silently not created" class the law was set up for.
        """
        # One op, two created elements — today this no longer balances.
        with self.assertRaises(ContractSchemaError):
            receipt(element_ids=("1", "2"), ops_total=1, ops_no_element=0)
        # And an honest single-op case will fail to balance in exactly
        # the same way.
        ok = receipt(element_ids=("1",), ops_total=1, ops_no_element=0)
        self.assertEqual(ok.ops_total, 1)


if __name__ == "__main__":
    unittest.main()
