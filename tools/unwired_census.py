#!/usr/bin/env python3
"""A thin door to `kir.instruments.unwired_census` — the command has not changed.

The reasoning is the same as its neighbor `kir_canon_state.py`: the body is
in the package, the door is here.

    PYTHONPATH=/opt/kir python3.12 tools/unwired_census.py --host <root>
"""
import sys

from kir.instruments.unwired_census import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
