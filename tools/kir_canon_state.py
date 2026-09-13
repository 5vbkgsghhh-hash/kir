#!/usr/bin/env python3
"""Thin door to `kir.instruments.canon_state` — the command has not changed.

🔴 WHY A WRAPPER, NOT A RENAME OF THE COMMAND (28.08.2026). The instrument's
body moved INTO THE PACKAGE, because `tools/` is NOT part of the installable
package, and the test importing it by its short name was AN ESCAPE BEYOND THE
BOUNDARY — the guard `test_kir_boundary_to_the_product_is_a_closed_list`
counted such escapes by name and found three hard ones instead of one.

Untangling, not a registry entry: the escape wasn't logged, it was REMOVED.
The other nine instruments had already moved into `kir/instruments/` during
the 27.08 split — this one followed after.

The command from the briefing (`KIR_PLAN.md` §9) keeps working letter for
letter:

    PYTHONPATH=/opt/kir python3.12 tools/kir_canon_state.py --write
"""
import sys

from kir.instruments.canon_state import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
