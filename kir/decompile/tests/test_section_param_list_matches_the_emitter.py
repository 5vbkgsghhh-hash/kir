"""THE CLOSED LIST OF PARAMETERS LIVES IN TWO PLACES — AND ONE OF THEM HAS ALREADY MOVED AHEAD.

WHAT HAPPENED ON 20.08.2026, MEASURED ON A REAL BUILDING.
Decompiling the house `MNVNK_ATR_PD_B14_K6_AR_R2022` (Revit 2023, 75 936 elements,
94 categories) ended like this:

    77/77 processed · elements_total: 0 · stage: error
    errors: ["snapshot_non_authoritative: L0 extraction contains partial
              categories; lift is blocked"]

Meanwhile 46 categories are honestly empty, and ALL 31 categories with content —
10 646 walls, 2 952 windows, 1 230 doors, 33 944 elements in total — returned
`extracted_count: 0` with one and the same reason:

    section receipts do not cover the closed list of parameters:
    missing [], extra ['CEILING_HEIGHTABOVELEVEL_PARAM',
    'FAMILY_BASE_LEVEL_OFFSET_PARAM', 'FAMILY_BASE_LEVEL_PARAM', ...]

THE CAUSE. Commit `00ee35f5` (11:12 that same day, its title verbatim: "Schema
authority now travels in EVERY extraction: the receipt existed for 16 probes out of 43")
did exactly what it promised: it widened the receipts from 16 probes to 43. The second
carrier of the same knowledge — `SECTION_PARAM_NAMES` in python — stayed at 16.
The `_parse_section_receipts` guard is fail-closed by construction: a name outside the list
is a protocol refusal. The result — decompiling ANY real building returned zero for
the next ten hours, and it returned HONESTLY: `is_partial_read: false`,
`stream_complete: true`, the error named. The instrument was not lying — it was incomplete.

🔴 WHY NO TEST CAUGHT THIS. The decompile fixtures are built from
MATCHED pairs: the stub page sends exactly the names python expects.
Such a pair is green for any value of both lists — it checks
the guard, not the AGREEMENT of the two carriers. Agreement is checked only by comparing against
the emitter, and here it is.

THE GENRE OF THIS FILE IS A RATCHET, not a behavior check. It does not assert that the
list is correct; it asserts that the list EQUALS what the
emitter produces. Exactly the same technique used elsewhere in this tree to hold
`tests/bridge/test_exec_wrapper_sync.py`: two copies that must match
diverge silently, so a test binds them together.
"""
from __future__ import annotations

import pathlib
import re
import unittest

from kir.decompile.extract import SECTION_PARAM_NAMES

#: The helpers of the emitted C#, each of which calls `__BumpSection`, meaning it
#: MUST send a receipt for its own parameter. The list is closed on purpose:
#: introduce a fourth one, and this test will stay silent, and that silence will be a lie. That is why
#: there is a separate check below that no other families exist in the emitter.
RECEIPT_HELPERS = ("__PutSectionParam", "__PutSectionIntParam",
                   "__PutSectionIdParam")

_SOURCE = pathlib.Path(
    __file__).resolve().parents[1].joinpath("extract.py").read_text(
        encoding="utf-8")


def _names_from_emitter() -> set[str]:
    """The names for which the emitted C# WILL send a receipt.

    The name is taken from `nameof(BuiltInParameter.X)` — exactly the form
    introduced by commit `63462108` ("nameof() makes the member/label mismatch
    impossible"). Reading it with a regex is legitimate precisely because it is
    syntactically rigid: the helper's signature requires the name as the fourth
    argument, and `nameof` does not let it diverge from the member itself.
    """
    found: set[str] = set()
    for helper in RECEIPT_HELPERS:
        for match in re.finditer(re.escape(helper) + r"\(", _SOURCE):
            tail = _SOURCE[match.end():match.end() + 400]
            name = re.search(r"nameof\(BuiltInParameter\.([A-Z_0-9]+)\)", tail)
            if name:
                found.add(name.group(1))
    return found


class TheClosedListEqualsTheEmitter(unittest.TestCase):

    def test_every_probe_that_sends_a_receipt_is_in_the_closed_list(self) -> None:
        """THE MAIN RATCHET. This is exactly the one that would have gone red on 20.08 at 11:12."""
        emitted = _names_from_emitter()
        declared = set(SECTION_PARAM_NAMES)
        unknown = sorted(emitted - declared)
        self.assertEqual(
            unknown, [],
            "эмиттер шлёт квитанции по именам, которых нет в "
            "SECTION_PARAM_NAMES — сторож _parse_section_receipts отвергнет "
            "КАЖДУЮ страницу с этими элементами, и разбор вернёт ноль при "
            "честном is_partial_read=false.\nСЛЕДУЮЩИЙ ХОД: добавь строками в "
            f"SECTION_PARAM_NAMES: {unknown}")

    def test_the_closed_list_promises_nothing_the_emitter_never_sends(self) -> None:
        """THE FLIP SIDE, and it is not symmetric with the first.

        A name declared here and NOT sent by the emitter gives "missing
        [...]" on every page whose route did not cut it off — that is, the same
        zero, only from the other end. We hold both sides because the defect
        has already arrived from one of them.
        """
        emitted = _names_from_emitter()
        declared = set(SECTION_PARAM_NAMES)
        orphan = sorted(declared - emitted)
        self.assertEqual(
            orphan, [],
            "SECTION_PARAM_NAMES требует имён, которых эмиттер не шлёт: "
            f"{orphan}. Либо зонд удалён из C# и строка здесь лишняя, либо "
            "зонд обязан вернуться.")

    def test_no_fourth_receipt_helper_slipped_in(self) -> None:
        """A CONTROL FOR THE NARROWNESS OF THE INSTRUMENT ITSELF.

        The instrument reads THREE families of helpers. Introduce a fourth in the emitter —
        and it will stay silent while green: the diverged names simply will not make it
        into the sample. An instrument that does not see part of its input is a shape
        already recorded in this house ("an instrument covering part of the range"), and here it would
        cost exactly the same zero.
        """
        helpers = set(re.findall(r"__PutSection[A-Za-z]*Param", _SOURCE))
        self.assertEqual(
            helpers, set(RECEIPT_HELPERS),
            "в эмиттере появилось семейство помощников, о котором храповик "
            "не знает — допиши его в RECEIPT_HELPERS, иначе сверка станет "
            "неполной МОЛЧА")

    def test_the_list_is_not_trivially_empty(self) -> None:
        """An empty list would make both comparisons above green for free."""
        self.assertGreaterEqual(len(SECTION_PARAM_NAMES), 40)


if __name__ == "__main__":
    unittest.main()
