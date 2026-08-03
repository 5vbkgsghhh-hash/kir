"""The document-revision guard must survive contact with Revit.

Live evidence, 2026-07-26, ``Проект1`` on Revit 2026::

    BRIDGE ERROR: The collector does not have a filter applied.
    Extraction or iteration of elements is not permitted without a filter.

Every decompile read is wrapped in the revision guard, so an unfiltered
``FilteredElementCollector`` inside it is not one broken stage -- it is the
whole live decompile path refusing to start, on every Revit version. The three
``extract_failed`` runs on the R23 model were long attributed to the stale
bridge DLL; this collector throws before any of that is reached.

Revit requires at least one filter before a collector may be iterated. "Every
element, instances and types alike" therefore has to be spelled as a filter
that passes everything, not as the absence of one.
"""

from __future__ import annotations

import re
import unittest

from kukai.ir.decompile import pipeline


# ``new FilteredElementCollector(<anything>)`` followed by whitespace/comments
# and then a call that is NOT a filter. Filters are the only methods allowed to
# stand between construction and iteration.
_FILTER_CALLS = (
    "WherePasses", "WhereElementIsNotElementType", "WhereElementIsElementType",
    "OfClass", "OfCategory", "OfCategoryId", "Excluding", "IntersectWith",
    "UnionWith", "ContainedInDesignOption", "OwnedByView",
)
_COLLECTOR = re.compile(
    r"new\s+FilteredElementCollector\s*\([^)]*\)\s*(?://[^\n]*\n\s*)*\.\s*(\w+)")


def _unfiltered(code: str) -> list[str]:
    return [m.group(1) for m in _COLLECTOR.finditer(code)
            if m.group(1) not in _FILTER_CALLS]


class TheRevisionGuardCollector(unittest.TestCase):
    def test_it_applies_a_filter_before_iterating(self):
        offenders = _unfiltered(pipeline._REVISION_FINGERPRINT_CS)

        self.assertEqual(
            offenders, [],
            "the revision guard iterates a collector whose first call is "
            f"{offenders!r}; Revit refuses that with 'The collector does not "
            "have a filter applied'")

    def test_it_still_covers_type_elements(self):
        # The guard's whole job is add/delete/modify detection, and a type
        # rename is a modification. Filtering down to instances would make the
        # collector legal and the fingerprint blind -- a silent regression that
        # no live run would surface.
        code = pipeline._REVISION_FINGERPRINT_CS

        self.assertIn("ElementIsElementTypeFilter", code)
        self.assertIn("LogicalOrFilter", code)

    def test_the_guard_wraps_reads_with_the_fingerprint(self):
        wrapped = pipeline._revision_guard_cs("var __x = 1;")

        self.assertIn(pipeline._REVISION_GUARD_MARKER, wrapped)
        self.assertIn("__KirDocumentRevision", wrapped)
        self.assertIn("var __x = 1;", wrapped)

    def test_the_detector_itself_recognises_a_bare_collector(self):
        # Guard the guard: if the regex stopped matching, the test above would
        # pass vacuously forever.
        bare = "var __all = new FilteredElementCollector(doc).ToElements();"

        self.assertEqual(_unfiltered(bare), ["ToElements"])

    def test_the_detector_accepts_every_filter_spelling(self):
        for call in _FILTER_CALLS:
            with self.subTest(call=call):
                code = f"new FilteredElementCollector(doc).{call}()"
                self.assertEqual(_unfiltered(code), [])


if __name__ == "__main__":
    unittest.main()
