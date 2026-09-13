#!/usr/bin/env python3
"""A thin door to `kir.instruments.walk_denominator` — the command has not changed.

The body moved INTO THE PACKAGE on 02.09.2026: `tools/` is not part of the
installable package, and the ratchet that imported the instrument from there
was a HARD BREACH OF THE BOUNDARY — the guard
`test_kir_boundary_to_the_product_is_a_closed_list` counted two hard
breaches instead of one on that same day. The same resolution as with
`canon_state` on 28.08: the breach is not named, it is REMOVED.

    python3.12 tools/walk_denominator_census.py --names
"""
import sys

from kir.instruments.walk_denominator import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
