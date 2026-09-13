""""NO RECEIPTS" MUST MEAN EXACTLY THAT, NOT A CORRUPTED FORM (F-164).

THE TRIGGER. All seven side readers were parsing the second half of the
response like this:

    _array(root.get("failures") or [], "…failures")

`or []` substitutes a default value for a CHECK OF THE FORM. A wire that
sent `failures: false`, `0`, `""`, or `{}` was accepted as an HONEST ZERO
RECEIPTS, and a stage reported "checked everything, no slices" on a
response whose form was corrupted. This is exactly the substitution the
whole of §18.2 was written against: the difference between "we cannot" and
"we did not check" — and here it is even worse, between "there are no
slices" and "we did not understand what we were answered".

EXECUTED BEFORE THE FIX (`dimension_extract`, both readers, five values):

    wire failures=False/0/''/{}/[]  ->  ACCEPTED, receipts 0   (all five)
    disk failures=False/0/''/{}/[]  ->  ACCEPTED, receipts 0   (all five)

🔴 WHY THE REFUSAL IS RAISED IMMEDIATELY (separator D2). It can only fire
where the input is ALREADY invalid. Measured on the live corpus 29.08,
read-only: 144 `*.index.json` files, `failures` is a list in 144 of 144,
NOT ONE is invalid. A missing key and `null` still give an empty list:
`failures` is declared optional, and turning "it was not sent" into a
refusal would mean changing the contract instead of fixing the defect.

WHAT IS GUARDED HERE IS A CLASS, NOT ONE READER. Twelve spots across seven
modules carried the same line; the rule is now one
(`side_contract.optional_failures`), and it is checked on EVERY reader, not
just the one that was remembered.

Run it:
    /opt/kir-audit/suite-venv/venv/bin/python -m pytest \
        kir/decompile/tests/test_a_false_zero_of_receipts_is_refused.py -q
"""
from __future__ import annotations

import unittest

from kir.decompile.annotation_extract import (
    ANNOTATION_EXTRACT_SCHEMA_VERSION,
    ANNOTATION_INDEX_SCHEMA_VERSION,
    AnnotationExtraction,
    AnnotationPayloadError,
    extract_annotations,
)
from kir.decompile.dimension_extract import (
    DIMENSION_EXTRACT_SCHEMA_VERSION,
    DIMENSION_INDEX_SCHEMA_VERSION,
    DimensionExtraction,
    DimensionPayloadError,
    extract_dimensions,
)
from kir.decompile.join_extract import (
    JOIN_EXTRACT_SCHEMA_VERSION,
    JOIN_INDEX_SCHEMA_VERSION,
    JoinExtraction,
    JoinPayloadError,
    extract_joins,
)
from kir.decompile.mep_system_extract import (
    MEP_SYSTEM_EXTRACT_SCHEMA_VERSION,
    MEP_SYSTEM_INDEX_SCHEMA_VERSION,
    MepSystemExtraction,
    MepSystemPayloadError,
    extract_mep_systems,
)
from kir.decompile.side_contract import optional_failures
from kir.decompile.sketch_extract import (
    SKETCH_EXTRACT_SCHEMA_VERSION,
    SketchPayloadError,
    extract_sketch_profiles,
)
from kir.decompile.tag_extract import (
    TAG_EXTRACT_SCHEMA_VERSION,
    TAG_INDEX_SCHEMA_VERSION,
    TagExtraction,
    TagPayloadError,
    extract_tags,
)

#: 🔴 THE VALUES ARE CHOSEN BY THE DEFECT'S SUBJECT, NOT BY CONVENIENCE.
#: Each of the four is FALSY in Python and so used to pass `or []`
#: silently; none of them is a list, meaning each must be a refusal under
#: the §18.2 contract. The `"no"` at the end is NOT falsy and not a list:
#: it catches the opposite mistake, a fix shaped like
#: `if not value: return []`.
_IMPOSTORS = (False, 0, 0.0, "", {}, "нет")

#: Readers that used to have `or []`: (name, parser, a valid payload, a
#: refusal). The list is COMPLETE by construction — its completeness is
#: guarded by a separate check below, which counts the spots in the source
#: files.
_READERS = (
    ("annotation index", AnnotationExtraction.from_dict,
     {"schema_version": ANNOTATION_INDEX_SCHEMA_VERSION,
      "text_note_index": {}}, AnnotationPayloadError),
    ("Annotation extraction", extract_annotations,
     {"schema_version": ANNOTATION_EXTRACT_SCHEMA_VERSION,
      "elements": []}, AnnotationPayloadError),
    ("dimension index", DimensionExtraction.from_dict,
     {"schema_version": DIMENSION_INDEX_SCHEMA_VERSION,
      "dimension_index": {}}, DimensionPayloadError),
    ("Dimension extraction", extract_dimensions,
     {"schema_version": DIMENSION_EXTRACT_SCHEMA_VERSION,
      "elements": []}, DimensionPayloadError),
    ("join index", JoinExtraction.from_dict,
     {"schema_version": JOIN_INDEX_SCHEMA_VERSION,
      "join_index": {}}, JoinPayloadError),
    ("join extraction", extract_joins,
     {"schema_version": JOIN_EXTRACT_SCHEMA_VERSION,
      "elements": []}, JoinPayloadError),
    ("mep system index", MepSystemExtraction.from_dict,
     {"schema_version": MEP_SYSTEM_INDEX_SCHEMA_VERSION,
      "system_index": {}}, MepSystemPayloadError),
    ("MEP system extraction", extract_mep_systems,
     {"schema_version": MEP_SYSTEM_EXTRACT_SCHEMA_VERSION,
      "elements": []}, MepSystemPayloadError),
    ("Sketch extraction", extract_sketch_profiles,
     {"schema_version": SKETCH_EXTRACT_SCHEMA_VERSION,
      "elements": []}, SketchPayloadError),
    ("tag index", TagExtraction.from_dict,
     {"schema_version": TAG_INDEX_SCHEMA_VERSION,
      "tag_index": {}}, TagPayloadError),
    ("Tag extraction", extract_tags,
     {"schema_version": TAG_EXTRACT_SCHEMA_VERSION,
      "elements": []}, TagPayloadError),
)


class TheRuleItself(unittest.TestCase):
    """`optional_failures` is proven from BOTH SIDES, separately from the readers."""

    def test_absence_and_null_stay_an_empty_list(self):
        self.assertEqual(optional_failures(None, "x", ValueError), [])

    def test_a_real_list_passes_through_unchanged(self):
        rows = [{"element_id": "1"}]
        self.assertIs(optional_failures(rows, "x", ValueError), rows)

    def test_every_impostor_is_refused_with_the_stages_own_error(self):
        class _Own(ValueError):
            pass

        for value in _IMPOSTORS:
            with self.subTest(value=value):
                with self.assertRaises(_Own):
                    optional_failures(value, "x.failures", _Own)


class EveryReaderRefusesTheFalseZero(unittest.TestCase):
    """The class is guarded on EVERY reader, not on the one that was remembered."""

    def test_an_absent_failures_key_is_still_a_truthful_zero(self):
        for name, parse, payload, _error in _READERS:
            with self.subTest(reader=name):
                result = parse(dict(payload))
                self.assertEqual(
                    len(result.failures), 0,
                    f"{name}: отсутствие `failures` перестало значить «ноль»")

    def test_an_explicit_empty_list_is_still_accepted(self):
        for name, parse, payload, _error in _READERS:
            with self.subTest(reader=name):
                result = parse({**payload, "failures": []})
                self.assertEqual(len(result.failures), 0)

    def test_a_falsey_non_array_is_refused_and_not_read_as_zero(self):
        for name, parse, payload, error in _READERS:
            for value in _IMPOSTORS:
                with self.subTest(reader=name, value=value):
                    with self.assertRaises(error) as caught:
                        parse({**payload, "failures": value})
                    self.assertIn("must be an array", str(caught.exception))


#: Modules of the side READERS — the ones for whom "no receipts" is a
#: CLAIM ABOUT THE BUILDING, and so a corrupted form must be a REFUSAL.
#:
#: 🔴 `axes_census.py` IS NOT ONE OF THESE, AND THIS IS A CLAIM, NOT AN
#: OMISSION. It carries the same line (`len(raw.get("failures") or [])`)
#: and the same false zero, but it is a CENSUS, not a contract reader: a
#: refusal would fail the traversal at the very first damaged artifact,
#: meaning it would trade one blindness for another. Its remedy is a NAMED
#: reason next to the number, and it travels as its own finding (`F-184`,
#: the same file, `_records` swallows every broken row).
_SIDE_READER_MODULES = (
    "annotation_extract.py", "dimension_extract.py", "join_extract.py",
    "mep_system_extract.py", "sketch_extract.py", "tag_extract.py",
)

#: THE DENOMINATOR OF THE SOURCE HALF. How many times the `optional_failures`
#: law must stand in the six readers for "no offenders" to mean anything.
#:
#: 🔴 WHAT IS NOT CAUGHT WITHOUT THIS NUMBER (measured 02.09.2026). A
#: missing FILE is caught by `read_text` — it will raise. But a BODY moving
#: elsewhere catches nothing at all: the file is in place, parsing
#: succeeds, `or []` is not found in it for the simple reason that
#: `failures` is no longer read there at all — and the offenders dict is
#: empty. That is how the emitter guard went blind on 02.09: it read a live
#: file and saw 35 names out of 72, because 32 bodies had moved out to
#: satellites. It stayed GREEN.
#:
#: Measured 02.09.2026: **11** calls across six modules (2 each for five, 1
#: for `sketch_extract`). The floor is set one spot below the measurement —
#: it survives the removal of one reader, but not a kind moving elsewhere.
_ЗАКОН_СТОИТ_НЕ_МЕНЬШЕ_ЧЕМ_В = 10


class TheOldFormIsGoneFromEveryReader(unittest.TestCase):
    """The structural half: `or []` has not returned to a single side
    reader.

    The behavioral check above talks about the READERS the list remembers.
    This one talks about the SOURCE, and so it catches a twelfth spot
    introduced tomorrow.

    🔴 THE MATCHER PARSES THE AST, IT DOES NOT SEARCH FOR A SUBSTRING. The
    first edition searched for a string — and found ITS OWN comment
    explaining what must not be done. An instrument that catches a story
    about a defect instead of the defect lives until the first explanation.
    """

    @staticmethod
    def _законных_мест(source: str) -> int:
        """How many times the LAW ITSELF (`optional_failures`) stands in
        the source.

        The traversal's denominator: `_offenders` counts the DISEASE, and
        this counts the REMEDY. Zero disease with zero remedy means the
        reader is no longer here, not that it is healthy.
        """
        import ast

        return sum(
            1 for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call)
            and (getattr(node.func, "id", None)
                 or getattr(node.func, "attr", None)) == "optional_failures")

    @staticmethod
    def _offenders(source: str) -> int:
        import ast

        found = 0
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.BoolOp):
                continue
            if not isinstance(node.op, ast.Or) or len(node.values) != 2:
                continue
            left, right = node.values
            if not (isinstance(right, ast.List) and not right.elts):
                continue
            if (isinstance(left, ast.Call)
                    and isinstance(left.func, ast.Attribute)
                    and left.func.attr == "get"
                    and left.args
                    and isinstance(left.args[0], ast.Constant)
                    and left.args[0].value == "failures"):
                found += 1
        return found

    def test_the_matcher_sees_the_defect_and_not_its_description(self):
        self.assertEqual(self._offenders('x = root.get("failures") or []'), 1)
        self.assertEqual(
            self._offenders('# root.get("failures") or [] — так было'), 0)
        self.assertEqual(
            self._offenders('x = optional_failures(root.get("failures"))'), 0)
        # …and the second half: the law's counter sees the remedy and does
        # not mistake it for the disease. A denominator whose counter no
        # one has checked is just as plausible-looking a number as prose.
        self.assertEqual(
            self._законных_мест('x = optional_failures(root.get("failures"))'), 1)
        self.assertEqual(
            self._законных_мест('x = root.get("failures") or []'), 0)

    def test_no_side_reader_normalises_failures_with_or(self):
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[1]
        исходники = {
            name: (root / name).read_text(encoding="utf-8")
            for name in _SIDE_READER_MODULES
        }
        # THE DENOMINATOR FIRST: six read files WITH NO BODIES would give
        # an empty offenders dict and would read as "the class is closed".
        закон = sum(self._законных_мест(src) for src in исходники.values())
        self.assertGreaterEqual(
            закон, _ЗАКОН_СТОИТ_НЕ_МЕНЬШЕ_ЧЕМ_В,
            f"`optional_failures` стоит в {закон} местах при поле "
            f"{_ЗАКОН_СТОИТ_НЕ_МЕНЬШЕ_ЧЕМ_В} (замер 02.09.2026 — 11). Это "
            f"заявление о ХОДОКЕ: файлы читаются, а закона в них нет — "
            f"значит читатели уехали, и пустой список нарушителей ниже "
            f"НИЧЕГО не означает")
        offenders = {
            name: count
            for name, src in исходники.items()
            if (count := self._offenders(src))
        }
        self.assertEqual(
            offenders, {},
            "`… .get(\"failures\") or []` вернулся: ложный ноль квитанций "
            f"снова принимается за честный — {offenders}")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
