"""A thin CLI on top of `kir.instruments.revit_refs`.

The logic LIVES IN `kir/`, not here, and the reason is named in
`kir/instruments/__init__.py`: instruments moved out of the product's
`tools/` into the package by the owner's decision on 27.08. An import
`kir` -> `tools` is core leaking outward, and it is caught by the gate
`kir/tests/test_kir_boundary_to_the_product_is_a_closed_list.py`. The first
edition on 07.09 put the instrument here and IMMEDIATELY got the line
`tests/test_connector_compiler_conformance.py -> tools (мягкий)` from the
gate.

    python tools/revit_refs.py            # 2021…2026
    python tools/revit_refs.py 2023 2026
"""
import sys

from kir.instruments.revit_refs import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
