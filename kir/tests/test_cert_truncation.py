"""SILENT TRUNCATION IS AN ASSERTION OF "HERE IS EVERYTHING" WHERE NOT EVERYTHING WAS READ.

`_certify_translation` cuts two lists at `_CERT_DIAGNOSTIC_LIMIT = 8`:

    receipt["diagnostics"]     = _certificate_diagnostics(...)[:8]
    receipt["vacuity_partial"] = partial[:8]

and NOT ONE key of the receipt says a cut happened. The reader sees eight
diagnostics and has no reason at all to think there were twenty.

ESPECIALLY BITING FOR `vacuity_partial`, because a comment ONE LINE ABOVE in
`serving.py` ITSELF says: "'Read whole' and 'read in pieces' are different
facts, and the second must not be read as proof of cleanliness." The list
carrying that very fact was cut silently.

THE SHAPE IS THE SAME AS THE WHOLE SERIES: a value is ASSERTED in one place
("here are the diagnostics") and READ elsewhere (there were more), and
nothing forces them to agree. The cure here is of the second kind — not "ask
an authority," but NAME the total right next to the truncated list, exactly
the way the clash check already does ("… the judgment list is truncated,
showing N").

WHAT THIS TEST DOES NOT ASSERT. The size of the damage. I have not
reproduced a program that gives more than eight diagnostics; the existence
of the defect does not depend on that, but its cost does, and that is NOT
measured here.
"""
from __future__ import annotations

import unittest

from kir import serving as S


class _Cert:
    """A minimal certificate double: as many diagnostics as needed."""

    def __init__(self, unproven: int, partial: int):
        self.vacuous = False
        self.proven = False
        self.ops = tuple(
            _OpCert(f"k{i}") for i in range(partial))
        self._unproven = unproven


class _OpCert:
    def __init__(self, key: str):
        self.vacuity_partial = (key,)
        self.op = "create_wall"
        self.clauses = ()


class _Out:
    """A compiled program, exactly in the part the instrument reads."""

    def __init__(self, ops: int):
        self.grounded_ops = tuple({"op": "create_wall"} for _ in range(ops))


class TheTruncationNamesItself(unittest.TestCase):
    """Truncation is obligated to NAME ITSELF with a number, not stay silent."""

    LIMIT = S._CERT_DIAGNOSTIC_LIMIT

    def _receipt(self, diagnostics: int, partial: int) -> dict:
        """The instrument's receipt with a given number of diagnostics and partial reads.

        Exactly two things are mocked: the diagnostics collector and the
        certifier. Everything else is the real `_certify_translation`,
        otherwise the test would be checking its own imagination, not the
        instrument.
        """
        from unittest import mock

        from kir import translation_cert as _cert

        rows = [{"code": "CERT_UNPROVEN", "op_index": i, "op_id": f"o{i}",
                 "message_ru": f"обязательство {i} не разряжено"}
                for i in range(diagnostics)]
        certificate = _Cert(diagnostics, partial)
        with mock.patch.object(S, "_certificate_diagnostics",
                               return_value=rows), \
                mock.patch.object(_cert, "certify_program",
                                  return_value=certificate), \
                mock.patch.object(_cert, "certificate_mode",
                                  return_value="report"):
            return S._certify_translation(_Out(3), "2026")

    def test_a_short_list_is_not_marked_as_cut(self):
        """A marker that is always present is not a marker: the reader stops seeing
        it after two turns."""
        receipt = self._receipt(2, 2)
        self.assertEqual(len(receipt["diagnostics"]), 2)
        self.assertEqual(receipt.get("diagnostics_total"), 2)
        self.assertEqual(receipt.get("vacuity_partial_total"), 2)

    def test_a_cut_list_says_how_many_there_were(self):
        receipt = self._receipt(self.LIMIT + 12, 2)
        self.assertEqual(len(receipt["diagnostics"]), self.LIMIT)
        self.assertEqual(receipt["diagnostics_total"], self.LIMIT + 12,
                         "усечение молчит: «вот всё» там, где не всё")

    def test_the_partial_reads_say_how_many_there_were(self):
        """The very list whose own comment says that "read in pieces" must not be
        read as proof of cleanliness."""
        receipt = self._receipt(1, self.LIMIT + 5)
        self.assertEqual(len(receipt["vacuity_partial"]), self.LIMIT)
        self.assertEqual(receipt["vacuity_partial_total"], self.LIMIT + 5)

    def test_the_total_is_never_smaller_than_what_is_shown(self):
        for diagnostics, partial in ((0, 0), (3, 1), (self.LIMIT, self.LIMIT),
                                     (self.LIMIT + 1, self.LIMIT + 1)):
            receipt = self._receipt(diagnostics, partial)
            shown = len(receipt.get("diagnostics") or ())
            self.assertGreaterEqual(receipt.get("diagnostics_total", 0), shown)
            shown_p = len(receipt.get("vacuity_partial") or ())
            self.assertGreaterEqual(
                receipt.get("vacuity_partial_total", 0), shown_p)

    def test_a_proven_receipt_carries_no_empty_counters(self):
        """An absence stays an absence: a proven program has neither diagnostics
        nor a total for them — a zero here would read as 'we counted'."""
        from unittest import mock

        from kir import translation_cert as _cert

        certificate = _Cert(0, 0)
        certificate.proven = True
        with mock.patch.object(_cert, "certify_program",
                               return_value=certificate), \
                mock.patch.object(_cert, "certificate_mode",
                                  return_value="report"):
            receipt = S._certify_translation(_Out(3), "2026")
        self.assertEqual(receipt["status"], "proven")
        self.assertNotIn("diagnostics", receipt)
        self.assertNotIn("diagnostics_total", receipt)


if __name__ == "__main__":
    unittest.main()
