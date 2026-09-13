"""Live stream of intent — journal READERS of the program log, and nothing else.

The package is deliberately empty: `__init__` imports not a single module. This
is not tidiness, it is a load-bearing structure. `kir/__init__.py` imports the
compiler, so any module INSIDE `kir` pulls in the compiler by the mere fact of
its location — and a scan of imports could not tell "the drawer calls the
compiler" apart from "the drawer merely sits next to the compiler".

There is no such ambiguity here, by construction: `kir.live` pulls in nothing,
and the one edge from here into the compiler is the lazy import of
`kir.preview` inside the working body. `preview.py` itself, at module level,
imports NOTHING from `kir` (measured: stdlib only). This is checked
mechanically — `kir/tests/test_live_plan_stream.py::test_no_reverse_edge_into_compiler`.

FIVE MODULES, AND WHY FIVE, NOT TWO (04.08)
--------------------------------------------
`journal` (what was declared) and `plan_stream` (how it looks) are the path
THERE, and it must remain one-way. `showroom`, `transfer` and `verdict` are the
path BACK, and it is cut exactly along this boundary:

  * `showroom` holds what was shown, under a signature of its contents. It is
    a stdlib LEAF, because `plan_stream` populates it: let the showroom gain a
    path into the compiler, and one-way-ness would become false THROUGH IT;
  * `transfer` decides what to carry over, and so knows both the op registry
    and the preview. It is imported by NOT A SINGLE module on the "there"
    path — only by `chat_ws`. Checked mechanically (`test_kir_transfer.py::
    test_transfer_is_not_imported_by_the_drawing_path`);
  * `verdict` (04.08) judges the accumulated batch and hands down a verdict
    about the BUILDING into the MODEL's receipt. Also a path back, and by the
    same rules: it knows the verdict (i.e. the compiler), is imported by no
    module on the "there" path, and its sole importer is `kir/serving.py`.
    Before it, the batch travelled to the HUMAN (`showroom`) and to REVIT
    (`transfer`), and to the judge — never.

In other words: there are three edges back, each named, and none of them
leads back inside the "there" path.
"""
