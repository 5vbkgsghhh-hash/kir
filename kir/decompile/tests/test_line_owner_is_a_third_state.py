"""LINE OWNERSHIP: "undetermined" must differ from "never measured".

WHY THIS FILE. ``OST_Lines`` holds model lines (authored geometry) and
detail lines (annotation) in one category. Measured 2026-08-13 on
`k2_ar_rd_v7`: 9 407 elements of this category, ALL with an empty
``type_name``, ALL missing a level, while geometry IS present — 9 256 curves
with endpoints and 151 bounding boxes. What was missing was exactly
OWNERSHIP: a line has a "where", but not a known "whose". `tools/
content_coverage.py` assigns the whole category to annotation and says so in
its own line: "by majority in real construction documentation". That is an
estimate, not a measurement, and the project's headline coverage strip rests
on it.

WHAT IS FIXED HERE is not a fact about buildings, but a field's shape: THREE
states must be distinguishable BY CONSTRUCTION, or an empty field will again
come to mean three different truths. Every check runs as a "control-PASS +
control-FAIL" pair: without the second half a green result says nothing
(canon form 8).

BOUNDARY. This file checks the CONTRACT (the L0 schema and the emitted C#
text). It does not check that Revit answers correctly — that is a question
for a live run, and no offline test answers it. Six versions are closed by
compilation through `gate_runner` (measured 2026-08-13: 6/6 green on the
real thing, 6/6 red on the `SketchPlaneZZZ` control, CS1061 on the same
line).
"""

from __future__ import annotations

import unittest

from kir.decompile.geometry_store import GEOMETRY_HELPER_CS
# The catch-block parser is ONE per tree: two copies of the "silent
# catch" concept would drift apart silently, and that is a named defect
# of this tree.
from kir.decompile.tests.test_a_swallowed_read_failure_has_no_carrier import (
    catch_blocks,
    is_silent,
)
from kir.decompile.schema import L0Element, L0SchemaError, LineOwner


def _row(**overrides: object) -> dict[str, object]:
    """An L0 row of category `OST_Lines`.

    The bounding-box form is used (151 of 9 407) because it is simpler:
    ownership is orthogonal to geometry, and checking it on a curve would
    mean dragging extra mandatory fields into every case. That the field
    also lives on a curve is fixed separately —
    :meth:`ThreeStatesAreDistinguishable.
    test_the_field_is_orthogonal_to_geometry`.
    """

    row: dict[str, object] = {
        "element_id": "1001",
        "category": "OST_Lines",
        "category_ru": "Линии",
        "type_id": "2002",
        "type_name": "",
        "level_id": None,
        "level_name": None,
        "geom_kind": "bbox_only",
        "p0_mm": None,
        "p1_mm": None,
        "rotation_deg": None,
        "bbox_min_mm": [0.0, 0.0, 0.0],
        "bbox_max_mm": [1000.0, 0.0, 0.0],
        "host_id": None,
        "params": {},
    }
    row.update(overrides)
    return row


class ThreeStatesAreDistinguishable(unittest.TestCase):
    """ "Never measured", "undetermined", and a determined owner — three different things."""

    def test_absent_key_reads_as_not_measured(self) -> None:
        element = L0Element.from_dict(_row())
        self.assertIsNone(element.line_owner_kind)
        # And conversely: what was not measured is not written — otherwise a
        # frozen L0 would start looking measured.
        self.assertNotIn("line_owner_kind", element.to_dict())

    def test_undecided_is_a_typed_refusal_not_an_empty_field(self) -> None:
        element = L0Element.from_dict(
            _row(line_owner_kind="none", line_owner_id=None))
        self.assertIs(element.line_owner_kind, LineOwner.NONE)
        # Discrimination control: this state MUST be distinguishable from
        # the previous one in the serialized row, not only in the object.
        self.assertIn("line_owner_kind", element.to_dict())
        self.assertNotEqual(
            L0Element.from_dict(_row()).to_dict().get("line_owner_kind"),
            element.to_dict()["line_owner_kind"])

    def test_both_owners_carry_their_id(self) -> None:
        for value, expected in (
            ("view", LineOwner.VIEW),
            ("sketch_plane", LineOwner.SKETCH_PLANE),
        ):
            with self.subTest(value):
                element = L0Element.from_dict(
                    _row(line_owner_kind=value, line_owner_id="4242"))
                self.assertIs(element.line_owner_kind, expected)
                self.assertEqual(element.line_owner_id, "4242")

    def test_the_field_is_orthogonal_to_geometry(self) -> None:
        # 9 256 of 9 407 lines carry a CURVE, not a bounding box: checking
        # ownership only on the bounding-box row would mean measuring the
        # minority (1.6%) and calling it the category.
        element = L0Element.from_dict(_row(
            geom_kind="curve", p0_mm=[0.0, 0.0, 0.0], p1_mm=[1000.0, 0.0, 0.0],
            bbox_min_mm=None, bbox_max_mm=None,
            line_owner_kind="sketch_plane", line_owner_id="4242"))
        self.assertIs(element.line_owner_kind, LineOwner.SKETCH_PLANE)
        self.assertEqual(element.line_owner_id, "4242")

    def test_read_failure_is_its_own_state(self) -> None:
        element = L0Element.from_dict(_row(line_owner_kind="read_failed"))
        self.assertIs(element.line_owner_kind, LineOwner.READ_FAILED)
        self.assertIsNone(element.line_owner_id)


class TheContractCanActuallyRefuse(unittest.TestCase):
    """Control-FAIL: without it, the green result above says nothing."""

    def test_an_owner_without_its_id_is_refused(self) -> None:
        with self.assertRaises(L0SchemaError):
            L0Element.from_dict(
                _row(line_owner_kind="view", line_owner_id=None))

    def test_an_id_without_its_owner_is_refused(self) -> None:
        # An identifier whose origin is not recorded is not a measurement.
        with self.assertRaises(L0SchemaError):
            L0Element.from_dict(_row(line_owner_id="4242"))

    def test_an_unknown_value_is_refused_not_coerced(self) -> None:
        with self.assertRaises(L0SchemaError):
            L0Element.from_dict(_row(line_owner_kind="model"))

    def test_a_refusal_state_must_not_carry_an_owner_id(self) -> None:
        with self.assertRaises(L0SchemaError):
            L0Element.from_dict(
                _row(line_owner_kind="none", line_owner_id="4242"))


class TheEmittedReaderAsksTheRightMembers(unittest.TestCase):
    """The C# text: the view is asked first, then the sketch plane, and the refusal is typed.

    The check proceeds by DEFINITION (what is written in the emitted body),
    not by a naming convention: canon, form 7.
    """

    def test_the_helper_reads_view_before_sketch_plane(self) -> None:
        body = GEOMETRY_HELPER_CS
        self.assertIn("OwnerViewId", body)
        self.assertIn("SketchPlane", body)
        self.assertLess(
            body.index("OwnerViewId"), body.index("__ce.SketchPlane"),
            "вид спрашивается первым: у линии детализации плоскости может не "
            "быть вовсе, а у модельной линии вида нет по построению")

    def test_every_state_of_the_enum_is_emitted(self) -> None:
        for member in LineOwner:
            with self.subTest(member.value):
                self.assertIn(f'"{member.value}"', GEOMETRY_HELPER_CS)

    def test_the_reader_is_guarded_as_a_curve_element(self) -> None:
        # Without this cast the key would appear on EVERY model element, and
        # "never measured" would stop being distinguishable from "this is
        # not a line".
        self.assertIn("as CurveElement", GEOMETRY_HELPER_CS)

    def test_a_failed_read_is_named_rather_than_swallowed(self) -> None:
        """A read failure IS NAMED — and that is asked for as a PROPERTY.

        🔴 THE EDITION BEFORE 2026-09-02 PINNED THE SHAPE, AND TURNED RED
        FROM A FIX. It looked for a single-line
        ``catch { __row["line_owner_kind"] = "read_failed"; }`` byte for
        byte. A read-receipt wave added a second line to that same catch
        block — and the assertion failed even though the subject got
        BETTER, not worse. This is canon form 52 to the letter: the test was
        pinning a defect (more precisely, the shape of its fix), not a
        property, and turning red from it was news about correctness.

        The property here is twofold, and both halves are needed:

        * NOT ONE of the helper's catch blocks is silent — otherwise the
          next read attempt would swallow the failure, and the shape of the
          first would not show it;
        * there are TWO attempts to read ownership (the inner `SketchPlane`
          one and the outer one), and EACH must name its failure. The inner
          one stayed silent until this wave: its throw used to leave
          ``none`` — "measured and undetermined" — a fact about the LINE
          instead of a fact about our own reading.
        """

        body = GEOMETRY_HELPER_CS
        self.assertEqual(
            body.count('__row["line_owner_kind"] = "read_failed";'), 2,
            "у чтения принадлежности две независимые попытки, и назвать "
            "свой отказ обязана каждая")
        silent = [
            offset for offset, catch_body in catch_blocks(body)
            if is_silent(catch_body)
        ]
        self.assertEqual(
            silent, [],
            "в помощнике геометрии снова есть немой перехват: отказ чтения "
            "уедет неотличимо от настоящего отсутствия (§18.2)")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
