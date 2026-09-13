"""THE REVERSE PASS AS ONE CHAIN: L0 -> lift -> fold -> KIR ops -> real C#.

WHY THIS FILE EXISTS, BY MEASUREMENT ON 19.08.2026. The reverse half of KIR IS
the product: "the building has source code." Its links are covered separately (`test_lift`,
`test_fold`, `test_rebuild`, `test_idempotence`), but the CHAIN is not: the nearest test
reaches "dry-run compile summary," that is, a compilation summary, not the
real `compile_program` and not a witness. So the assertion "a building that has been read
can be rebuilt" was not checked end to end by any test.

The chain this file drives is entirely offline and Revit-free:

    L0Document (40 elements)
      -> lift_document      elements -> L1 nodes
      -> fold_document      nodes -> tree
      -> iter_l1_leaves     tree -> leaves
      -> leaves_to_program  leaves -> KIR OPS
      -> compile_program    ops -> C# with a guard and rollback
      -> certify_op         every op has a witness behind it

🔴 THE MAIN ASSERTION IS POPULATION ARITHMETIC, NOT "IT WORKED."
On input, 40 leaves; on output, 16 ops. The twenty-four did not vanish: they sit as
typed residuals with the named reason `atom:no_lifter`, and the accounting closes
exactly:

    input_leaves (40) == emitted_ops (16) + typed_residuals (24)

Without this equality, "the reverse pass read the building" means nothing: what can be
lost is exactly what nobody counts. This is exactly why the test checks not the
chain's success but the CLOSURE OF THE COUNT — a leaf lost with no name fails it.

WHAT IS NOT HERE, AND THIS IS NAMED:

  * real Roslyn is not invoked. `compile_program` is OUR compiler that prints
    C#; whether it builds on six versions is checked by a separate tier
    (compile-service on 52412, the `compile_service` fixture skips itself without
    dotnet). What is checked here is that the C# EXISTS and carries a guard, not that it builds;
  * geometry is not compared against the original. The chain proves that what was read
    becomes a PROGRAM under a witness, not that the building built from it
    will match the original down to the millimeter — that is `built_verdict`/`compare_geometry`,
    a different subject and a different tier;
  * atoms (furniture without a lifter) do not leak out. The twenty-four residuals are
    the legitimate outcome `same_document`, not a loss; in `escrow` mode they would have gone out
    honestly marked `create_directshape`.
"""
from __future__ import annotations

import collections
import os
import tempfile
import unittest

os.environ.setdefault(
    "KIR_REJECTIONS_PATH",
    os.path.join(tempfile.gettempdir(), "kir_reverse_chain_queue.jsonl"))

from kir import translation_cert as tc  # noqa: E402
from kir.compiler import compile_program  # noqa: E402
from kir.decompile.fold import fold_document, iter_l1_leaves  # noqa: E402
from kir.decompile.lift import lift_document  # noqa: E402
from kir.decompile.materialize import leaves_to_program  # noqa: E402
from kir.decompile.tests.test_merkle import _grid_building  # noqa: E402

_VERSIONS = ("2021", "2024", "2026")


def _chain(document):
    """The full chain up to the materialization result, without compilation."""
    tree = fold_document(document, lift_document(document))
    leaves = list(iter_l1_leaves(tree))
    return leaves, leaves_to_program(leaves)


class ReverseChainReachesCSharp(unittest.TestCase):

    def test_a_read_building_becomes_a_program_under_a_witness(self):
        """The whole chain: 40 L0 elements -> 16 ops -> C# -> 16 witnesses."""
        document = _grid_building(floors=2)
        self.assertEqual(len(document.elements), 40)

        leaves, result = _chain(document)
        self.assertEqual(len(leaves), 40)
        kinds = collections.Counter(leaf["kind"] for leaf in leaves)
        self.assertEqual(dict(kinds), {"op": 16, "atom": 24})

        # 🔴 HERE STOOD `len(result.programs) == 1`, AND THIS WAS A COINCIDENCE
        # OF THE FIXTURE, NOT A CONTRACT. Before 23.08 lone groups were packed into one
        # stream; `af748a8b` separated lone items with no shared references BY OP KIND —
        # hostages on building K3 went from 7.0 % to 85.5 %, — and the same chain
        # now gives TWO programs with the same sixteen ops. `_pack_groups`
        # itself says this outright: "the chunk size is the same, the number of
        # programs is almost the same, only WHAT TRAVELS TOGETHER changes."
        # Replacing `1` with `2` would mean introducing the same defect with a different
        # literal. The law of separation by kind is guarded by ITS OWN test —
        # `test_chunk_kind_segregation.py` — and there is nothing to duplicate it with.
        #
        # 🔴 AND WHY NOTHING WAS PUT IN ITS PLACE — that is measured, not laziness.
        # It was tempting to write "no op is lost between accounting and programs"
        # (`sum(len(ops)) == accounting.counts["emitted_ops"]`). A FAIL control
        # on 24.08 showed that such a check CANNOT FAIL: `MaterializeResult.__post_init__`
        # already has THREE guards in a row —
        # `accounting digest disagrees with raw programs`, `accounting emitted
        # count disagrees with wire`, `accounting program count disagrees with
        # wire`. A result with such a discrepancy does not exist, and the check
        # would be green by construction. The population is guarded by
        # `test_the_population_arithmetic_closes` below, and the composition by op —
        # by the next three lines, and they do not depend on packing.
        by_op = collections.Counter(
            op["op"] for program in result.programs for op in program["ops"])
        self.assertEqual(dict(by_op), {"create_wall": 8, "create_column": 8})

        proven = total = 0
        for program in result.programs:
            out = compile_program(program)
            self.assertTrue(out.ok, f"обратный ход не собрался: {out.diagnostics}")
            for marker in ("__post", "RollBack", "Transaction"):
                with self.subTest(marker=marker):
                    self.assertIn(marker, out.csharp,
                                  "C# обратного хода обязан несть сторожа и "
                                  "откат, иначе пересборка пишет без "
                                  "обязательства")
            for op in (out.grounded_ops or []):
                total += 1
                for version in _VERSIONS:
                    with self.subTest(op=op["op"], version=version):
                        cert = tc.certify_op(op, version)
                        self.assertTrue(cert.proven, f"{op['op']} на {version}")
                        self.assertFalse(cert.vacuous)
                proven += 1
        self.assertEqual((proven, total), (16, 16))

    def test_the_population_arithmetic_closes(self):
        """🔴 Not a single leaf disappears without a name.

        `input_leaves == emitted_ops + typed_residuals`. What can be lost is exactly
        what nobody counts, and that is why this assertion outranks any
        "the chain passed."
        """
        _leaves, result = _chain(_grid_building(floors=2))
        counts = result.accounting.counts
        self.assertEqual(counts["input_leaves"], 40)
        self.assertEqual(counts["emitted_ops"], 16)
        self.assertEqual(counts["typed_residuals"], 24)
        self.assertEqual(
            counts["input_leaves"],
            counts["emitted_ops"] + counts["typed_residuals"],
            "счёт не сходится: часть листьев ушла в никуда, и это молчание")

    def test_every_residual_carries_a_typed_reason(self):
        """A residual without a reason is a loss wearing the costume of an outcome."""
        _leaves, result = _chain(_grid_building(floors=2))
        self.assertEqual(len(result.skipped), 24)
        reasons = collections.Counter(
            getattr(record, "reason", "") for record in result.skipped)
        self.assertEqual(dict(reasons), {"atom:no_lifter": 24})
        for record in result.skipped:
            reason = getattr(record, "reason", "")
            self.assertIn(":", reason,
                          f"причина {reason!r} обязана быть типизованной "
                          f"(род:подробность), а не свободной фразой")

    def test_the_chain_is_deterministic(self):
        """A building read twice gives the SAME program digest.

        Without this, an A->B delta is meaningless: the difference between two runs would be
        indistinguishable from the difference between two buildings.
        """
        document = _grid_building(floors=2)
        first = _chain(document)[1].accounting.programs_digest
        second = _chain(document)[1].accounting.programs_digest
        self.assertEqual(first, second)
        self.assertEqual(len(first), 64, "дайджест обязан быть sha256")

    def test_a_bigger_building_scales_the_chain_not_the_losses(self):
        """More floors — more ops, and the share of unnamed losses is still zero.

        The trap this test closes: a chain that loses on scale looks
        intact on a small sample.
        """
        for floors in (2, 3, 4):
            with self.subTest(floors=floors):
                leaves, result = _chain(_grid_building(floors=floors))
                counts = result.accounting.counts
                self.assertEqual(counts["input_leaves"], len(leaves))
                self.assertEqual(
                    counts["input_leaves"],
                    counts["emitted_ops"] + counts["typed_residuals"])
                self.assertEqual(counts["emitted_ops"], 8 * floors)


if __name__ == "__main__":
    unittest.main()
