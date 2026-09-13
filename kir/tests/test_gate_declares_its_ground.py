"""The gate must NAME what it is grounded against, right next to its
number.

WHY. The SUITE zone measured this on 12.08: `gate_runner` takes its
grounding snapshot from `kir.tests.fixtures.GROUND_SNAPSHOT` — a synthetic
FIXTURE. So the completeness of its pools is a property of THE GATE, not
just of the suite, and every "OK" for a program that needs a snapshot is a
claim ABOUT THE FIXTURE.

The price has already been paid once: the fixture was missing the
`roof_types` pool, and `create_roof`/`create_extrusion_roof` had no default
grounding anywhere. It got away with only ONE red, purely because the pool
was declared OPTIONAL — ``("type", "roof_types", False)``. A required pool
in the same spot would have brought down the gate ENTIRELY, and it would
have looked like "the op is broken". The mechanism behind the shortfall is
worth remembering separately: the producer has 35 pools, the fixture has
35, and 34 names match — **the COUNT lined up, the NAMES diverged** — and
any check of "how many pools" would have confirmed completeness. The SET
comparison for `spec.OPS` lives in the SUITE zone; it is not duplicated
here.

WHAT THIS FILE PINS AND WHY EXACTLY THIS. The canon says it plainly: prose
has no detector, no run will ever go red because a comment is lying. That
is why what's pinned here is not a promise in a docstring, but the PRINTED
LINE and the address it was assembled from — something a mutation can turn
red. Remove the declaration from the final block, and this file goes red.

WHAT THIS FILE DOES NOT CLAIM: it does not run the gate (that needs a live
kukai-compile.service on :52412) and says nothing about the completeness of
the fixture itself. It claims exactly one thing — that the subject of the
number is NAMED in the same place as the number.
"""
from __future__ import annotations

import importlib
import inspect
import unittest

from kir import gate_runner


class TheGateNamesWhatItGroundsAgainst(unittest.TestCase):

    def test_the_origin_constant_points_at_the_fixture(self):
        """The grounding address is declared as a constant, not scattered
        across lines."""
        self.assertEqual(
            gate_runner.GROUND_SNAPSHOT_ORIGIN,
            "kir.tests.fixtures.GROUND_SNAPSHOT")

    def test_the_named_module_actually_holds_that_snapshot(self):
        """FAIL control for the address: the name must resolve to a live
        object.

        Otherwise the declaration is a string that has outlived the
        fixture's move, and it would be pointing at nothing with complete
        confidence.
        """
        module_path, _, attribute = (
            gate_runner.GROUND_SNAPSHOT_ORIGIN.rpartition("."))
        module = importlib.import_module(module_path)
        self.assertTrue(
            hasattr(module, attribute),
            f"адрес {gate_runner.GROUND_SNAPSHOT_ORIGIN} не разрешается — "
            f"объявление пережило переезд фикстуры")
        self.assertIsInstance(getattr(module, attribute), dict)

    def test_the_summary_prints_the_ground_beside_the_count(self):
        """The declaration stands in the FINAL block, not only in the
        docstring.

        A reader takes the run's last lines, not the module's docstring.
        So the subject of the number must be printed in the same place as
        the number.
        """
        source = inspect.getsource(gate_runner.main)
        self.assertIn("GROUND_SNAPSHOT_ORIGIN", source,
                      "итоговый блок не называет заземление — число осталось "
                      "без предмета")
        self.assertIn("фикстур", source.lower(),
                      "заземление названо адресом, но не названо СИНТЕТИЧЕСКИМ")

    def test_the_verdict_stays_last(self):
        """The declaration is printed BEFORE the verdict — otherwise
        `tail -1` would return the wrong thing.

        The same law by which this file already carries the assembly
        manifest and the accounting line: the cheapest possible read must
        stay truthful.
        """
        source = inspect.getsource(gate_runner.main)
        ground = source.index("GROUND_SNAPSHOT_ORIGIN} — не против")
        verdict = source.index("'PASS' if failures == 0 else 'FAIL'")
        self.assertLess(
            ground, verdict,
            "объявление заземления печатается ПОСЛЕ вердикта — вердикт "
            "перестал быть последней строкой")


if __name__ == "__main__":
    unittest.main()
