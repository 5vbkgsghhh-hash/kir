"""THE FIXTURE MODEL MUST CARRY EVERY POOL THAT EVEN ONE OP GROUNDS AGAINST.

KIND OF LIST: **COMPLETE BY CONSTRUCTION** — consumers are enumerated from
the authority (`spec.OPS`), not collected by hand.

WHY. `GROUND_SNAPSHOT` is the only model against which almost the whole
suite is measured. A pool missing from it makes UNREACHABLE by default every
op that grounds on that pool: it refuses with `KIR-G104: <pool>: пусто в
модели` (empty in the model), and the refusal looks like a defect of the OP,
when it is a defect of the MODEL it is measured against.

THE COST, PAID ON 12.08.2026. `roof_types` was missing. Because of this,
`create_roof` and `create_extrusion_roof` did not ground by default anywhere,
and the one corpus entry where a roof sits next to other ops
(`group_mixed_members`) was red — and read as a red of the GROUP path, which
had just become load-bearing that very day.

AND, MOST IMPORTANTLY, WHY THIS WENT UNNOTICED. The producer had 35 pools
and the fixture had 35. **The count matched; the NAMES diverged.** Any check
of "how many pools" would have confirmed completeness. That is why SETS are
compared here, and the number is not checked at all — it distinguishes
nothing.
"""
from __future__ import annotations

import unittest

from kir.spec import OPS
from kir.tests.fixtures import GROUND_SNAPSHOT

#: Pools whose name is a TEMPLATE: `{category}` gets substituted at grounding. What must be checked
#: is the expansions, otherwise the template is forever "absent" and the pin becomes noise.
_TEMPLATE_EXPANSIONS = {"structural", "architectural"}


def pools_ops_ground_against() -> dict[str, set[str]]:
    """Pool → the ops that need it. Asked of `spec.OPS`, not of a list."""
    out: dict[str, set[str]] = {}
    for op_name, op_spec in OPS.items():
        for entry in (getattr(op_spec, "grounded", ()) or ()):
            pool = entry[1]
            names = ({pool.format(category=c) for c in _TEMPLATE_EXPANSIONS}
                     if "{category}" in pool else {pool})
            for name in names:
                out.setdefault(name, set()).add(op_name)
    return out


class TheTestModelCarriesEveryPoolItsOpsNeed(unittest.TestCase):

    def test_no_op_grounds_against_a_pool_the_fixture_lacks(self):
        needed = pools_ops_ground_against()
        missing = {p: sorted(ops) for p, ops in needed.items()
                   if p not in GROUND_SNAPSHOT}
        self.assertEqual(
            missing, {},
            "фикстура-модель не несёт пул, к которому заземляется оп: эти опы "
            "недостижимы по умолчанию во всём наборе, а их отказ выглядит "
            "дефектом опа, а не модели")

    def test_the_check_would_notice_a_pool_going_missing(self):
        """FAIL control: without it, the green above cannot be told apart from an empty check."""
        needed = pools_ops_ground_against()
        self.assertIn("roof_types", needed, "кровли перестали заземляться — "
                                            "пин смотрит не туда")
        crippled = {k: v for k, v in GROUND_SNAPSHOT.items() if k != "roof_types"}
        missing = [p for p in needed if p not in crippled]
        self.assertEqual(missing, ["roof_types"])

    def test_the_count_alone_never_would_have_noticed(self):
        """Why sets are compared, not a number.

        Before the fix, the producer had 35 pools and the fixture had 35 —
        the count matched while the names diverged. This test keeps that
        claim alive: it fails if anyone replaces the set comparison with a
        length comparison.
        """
        needed = set(pools_ops_ground_against())
        carried = {k for k in GROUND_SNAPSHOT if not k.startswith("__")}
        self.assertTrue(needed <= carried)
        self.assertNotEqual(len(needed), len(carried),
                            "числа совпали — значит сверка по длине выглядела "
                            "бы достаточной; именно так пропустили roof_types")


if __name__ == "__main__":
    unittest.main()
