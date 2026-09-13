"""A REFUSAL IS AN INTERFACE, AND THE INSTRUMENT MUST PRESERVE IT.

MEASUREMENT OF 11.08.2026, building `sob62_r23_v6` from the corpus.
`compile_gate_offline` collected ONLY `d.code` from every refusal:

    refused[(version, tuple(sorted({d.code for d in out.diagnostics}))[:2])] += 1

and printed `отказ эмиссии 1 ('2021', ('KIR-G102',))`. Everything else —
`field_name`, `message_ru`, `candidates` — was computed by the compiler
and thrown away.

WHY THIS IS NOT COSMETIC. The canon of this project: a refusal must NAME
THE NEXT MOVE. The compiler fulfills its obligation — the real message
of that finding reads like this:

    field      system_type
    message    «piping_system_types: несколько вариантов — default невозможен,
                уточните через {"by": "element_id", "value": <id из candidates>}»
    candidates [{'id': 246258, 'name': 'Приточная жидкость'}, …]

The instrument was turning this back into an ERROR CODE. Across a corpus
of 55 buildings, the difference between "it refuses somewhere" and "it
refuses HERE, and here is why" is the entire value of the corpus;
without it, every finding has to be dug up again with a separate probe,
which is exactly what was costing two runs a day by the time this was
noticed.

WHAT THIS TEST DOES NOT COVER: it does not check that the message is
USEFUL — only that the instrument does not lose it. The quality of the
wording is the compiler's obligation, and it is covered elsewhere
(`test_diag_*`).
"""
from __future__ import annotations

import unittest

from kir import diag


class _Out:
    """The shape of the compiler's response, exactly the part the
    instrument reads."""

    def __init__(self, diagnostics):
        self.ok = False
        self.csharp = ""
        self.diagnostics = list(diagnostics)


def _ambiguous() -> diag.Diagnostic:
    """A real finding from the corpus, not an invented one:
    `sob62_r23_v6`, op 191."""
    return diag.Diagnostic(
        code="KIR-G102",
        message_ru=("piping_system_types: несколько вариантов — default "
                    'невозможен, уточните через {"by": "element_id", '
                    '"value": <id из candidates>}'),
        op_index=191, op_id="e21201143", field_name="system_type",
        candidates=[{"id": 246258, "name": "Приточная жидкость"},
                    {"id": 246259, "name": "Обратная жидкость"}])


class TheGateKeepsWhatTheCompilerSaid(unittest.TestCase):

    def test_the_refusal_payload_survives_the_instrument(self) -> None:
        from kir.instruments import compile_gate_offline as gate

        rows = gate.refusal_rows([("2021", _ambiguous())])
        self.assertEqual(len(rows), 1, rows)
        row = rows[0]
        self.assertEqual(row["code"], "KIR-G102")
        self.assertEqual(row["field"], "system_type")
        self.assertIn("piping_system_types", row["message"])
        # THE NEXT MOVE is part of the refusal, not a decoration:
        # without it the reader knows there was a refusal and does not
        # know what to do.
        self.assertIn('"by": "element_id"', row["message"])
        self.assertEqual(row["candidates"], 2)
        self.assertEqual(row["versions"], ["2021"])

    def test_one_cause_on_six_versions_is_one_row_not_six(self) -> None:
        """The same refusal on six versions is ONE reason. Six rows
        would read as six findings and would inflate any ranking."""
        from kir.instruments import compile_gate_offline as gate

        rows = gate.refusal_rows(
            [(v, _ambiguous()) for v in
             ("2021", "2022", "2023", "2024", "2025", "2026")])
        self.assertEqual(len(rows), 1, rows)
        self.assertEqual(rows[0]["versions"],
                         ["2021", "2022", "2023", "2024", "2025", "2026"])
        self.assertEqual(rows[0]["count"], 6)

    def test_a_version_specific_refusal_stays_distinguishable(self) -> None:
        """`KIR-E003` on 2021 and on no other version is a fact about
        version COVERAGE, and it must be visible: a building expressible
        on five versions out of six is a property of the product, not
        noise (measurement: `sob62_fas_r23_v10`)."""
        from kir.instruments import compile_gate_offline as gate

        e003 = diag.Diagnostic(code="KIR-E003",
                               message_ru="оп не поддержан на этой версии",
                               field_name=None)
        rows = gate.refusal_rows([("2021", e003), ("2021", e003)])
        self.assertEqual(rows[0]["versions"], ["2021"])
        self.assertEqual(rows[0]["count"], 2)

    def test_a_diagnostic_without_extras_still_produces_a_row(self) -> None:
        """A boundary: a refusal without a field and without candidates
        does not have to invent them, but it must remain a ROW. An empty
        field and a missing row are different facts, and the second one
        is, once again, a loss of the interface."""
        from kir.instruments import compile_gate_offline as gate

        bare = diag.Diagnostic(code="KIR-X999", message_ru="")
        rows = gate.refusal_rows([("2026", bare)])
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["field"])
        self.assertEqual(rows[0]["candidates"], 0)
        self.assertEqual(rows[0]["message"], "")


if __name__ == "__main__":
    unittest.main()
