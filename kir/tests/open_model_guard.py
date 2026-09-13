"""Shared guard for the version-fragility of C# snapshots.

Moved into ONE place, because the rule was held by TWO tests
(`test_open_model`, `test_serving`) as two copies of the same substring —
and two signatures on one fact drift apart, and here that already cost a
false red.
"""
from __future__ import annotations


#: CLOSED LIST OF EXCEPTIONS TO THE RULE "DO NOT MENTION `IntegerValue`".
#:
#: The rule exists because the integer property of `ElementId` disappeared:
#: measured by compilation on 16.08.2026 on live Roslyn, across all six
#: versions — `ElementId.IntegerValue` compiles on 2021-2025 and FAILS on
#: 2026 (CS1061). So the ban is correct and needed.
#:
#: 🔴 BUT IT WAS HELD AS A SUBSTRING, AND A SUBSTRING CATCHES THE LABEL,
#: NOT THE BRANCH. A wave of workset code legitimately wrote
#: `__w.Id.IntegerValue` — this is `WorksetId`, A DIFFERENT type, and the
#: rename did not concern it: by the same 16.08.2026 measurement,
#: `WorksetId.IntegerValue` compiles on ALL SIX. The guard went red on
#: correct code and was read as a compiler defect for two days.
#:
#: The list is CLOSED and every line carries a MEASUREMENT, not an
#: argument. Adding a new exception without a six-version measurement is
#: forbidden: an open rule of the form "well, that's a different type"
#: turns the guard into a muffler on the first real failure.
INTEGER_VALUE_EXCEPTIONS: dict[str, str] = {
    "__wr[\"id\"] = __w.Id.IntegerValue;":
        "WorksetId.IntegerValue — замер 16.08.2026: OK на 2021-2026. "
        "Переименование затронуло ElementId, не WorksetId.",
}


def integer_value_offenders(cs: str) -> list[str]:
    """Lines with `IntegerValue` that are not in the closed exception list."""
    return [ln.strip() for ln in cs.split("\n")
            if "IntegerValue" in ln and ln.strip() not in INTEGER_VALUE_EXCEPTIONS
            and not ln.strip().startswith("//")]
