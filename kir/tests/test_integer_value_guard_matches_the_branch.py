"""THE VERSION-FRAGILITY GUARD MUST CATCH THE BRANCH, NOT THE LABEL.

WHAT PAID FOR THIS FILE (16.08.2026). Two tests — `test_open_model` and
`test_serving` — enforced the rule "`IntegerValue` must not be mentioned"
with TWO copies of a bare substring check. A wave of worksets legitimately
wrote `__wr["id"] = __w.Id.IntegerValue;`, and both turned red. The red sat
there and read as a compiler defect, even though the compiler was sound.

THE MEASUREMENT THAT SETTLED THE DISPUTE (live Roslyn, six versions,
16.08.2026):

    ElementId.IntegerValue   2021 OK · 2022 OK · 2023 OK · 2024 OK · 2025 OK
                             2026 FAIL (CS1061: no such member)
    WorksetId.IntegerValue   2021 OK · 2022 OK · 2023 OK · 2024 OK · 2025 OK
                             2026 OK

So the prohibition is CORRECT and needed — but exactly for `ElementId`. The
substring check does not distinguish the receiver's type and so forbids the
sound use along with the dangerous one.

🔴 WHY THE CHECK WAS NOT SIMPLY REMOVED. Removing it would mean losing the
only guard against a real version-specific failure in 2026. So the exception
list is CLOSED, each entry carries ITS OWN measurement, and this file
enforces both properties at once: the exception works AND the rule still
catches what it was written to catch.
"""
from __future__ import annotations

import unittest

from kir.tests.open_model_guard import (INTEGER_VALUE_EXCEPTIONS,
                                             integer_value_offenders)


class TheGuardMatchesTheBranchNotTheLabel(unittest.TestCase):

    def test_the_measured_safe_use_is_allowed(self):
        """`WorksetId.IntegerValue` — sound on all six, not red."""
        cs = 'var __w = 1;\n__wr["id"] = __w.Id.IntegerValue;\nreturn "{}";'
        self.assertEqual(integer_value_offenders(cs), [])

    def test_the_measured_dangerous_use_still_reddens(self):
        """THE OPPOSITE POLE — without it, the relaxation would become a silencer.

        `ElementId.IntegerValue` fails on 2026 — the guard must catch it,
        otherwise the exception would degenerate into "everything is
        allowed".
        """
        cs = 'foreach (var __e in xs) { __n += __e.Id.IntegerValue; }'
        offenders = integer_value_offenders(cs)
        self.assertEqual(len(offenders), 1, msg=offenders)
        self.assertIn("__e.Id.IntegerValue", offenders[0])

    def test_a_comment_is_not_code(self):
        """A mention in a comment is not a use.

        Otherwise it would become impossible to explain WHY the name is
        forbidden: the rule would be forbidding its own documentation. This
        defect was paid for the same day on a neighboring guard
        (`_MIGRATION_ADMIN_DEVICE`).
        """
        cs = '// старое имя ElementId.IntegerValue исчезло в 2026\nreturn "{}";'
        self.assertEqual(integer_value_offenders(cs), [])

    def test_the_exception_list_is_closed_and_each_entry_carries_a_measurement(self):
        """The closed list declares its own kind, and every row comes with a measurement."""
        self.assertTrue(INTEGER_VALUE_EXCEPTIONS)
        self.assertLess(len(INTEGER_VALUE_EXCEPTIONS), 5,
                        msg="список исключений разрастается — это уже не "
                            "исключения, а отмена правила")
        for fragment, why in INTEGER_VALUE_EXCEPTIONS.items():
            self.assertIn("IntegerValue", fragment)
            self.assertIn("замер", why.lower(),
                          msg=f"исключение «{fragment}» обосновано доводом, "
                              f"а не замером: {why}")


if __name__ == "__main__":
    unittest.main()
