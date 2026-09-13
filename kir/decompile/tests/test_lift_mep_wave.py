# -*- coding: utf-8 -*-
"""The reverse path for the MEP/flex-runs/placeholders wave
(09.08.2026).

In one morning five MEP operations arrived in the registry:
`create_conduit`, `create_pipe_placeholder`, `create_duct_placeholder`,
`create_flex_duct`, `create_flex_pipe`. The forward direction grew, the
reverse did not, and that is FINE for exactly as long as the gap is
NAMED. Here it is named and pinned down, because each of the three
situations lies in its own way if left unguarded.

1. THE DUCT LIFTS. The L0 row of a duct is indistinguishable by shape
   from a cable tray, and the lifter was written in the same wave — and
   until today its only test lived in the manifest
   (`test_reverse_contract`), i.e. it checked the PROMISE, not the lift.

2. THE FLEX RUN REFUSES UNDER THE CORRECT NAME. Before this wave both
   categories received `no_lifter` — "there is no operation for this" —
   and that was true right up until the morning of 09.08. Now the truth
   sits one step earlier: the op exists, but its shape is absent from
   capture. The difference is not cosmetic: `no_lifter` sends the next
   person to the operations registry, `source_contract_gap` sends them to
   READING.

3. THE PLACEHOLDER. 🔴 REWRITTEN 04.09.2026 — THE GAP WAS CLOSED FOUR
   DAYS BEFORE ITS OWN DEADLINE (decided 09.08, due 08.09). The opposite
   claim used to stand here: "there is nothing to tell them apart WITH BY
   CONSTRUCTION," and the tests held the declaration and the behavior
   locked together IN A DEFECT. The `IsPlaceholder` bit is now captured
   (`extract._placeholder_reader_cs`), travels as the
   `L0Element.is_placeholder` field, and splits the lifter into two ops.

   WHAT IS PINNED DOWN IS THREE-VALUEDNESS, NOT TWO OUTCOMES. `True` is a
   placeholder, `False` is a real run, ABSENCE OF THE KEY is "not
   measured," and the last one behaves as before: a snapshot taken before
   04.09 does not carry the bit, and refusing based on it would mean
   tearing down every run of every old decompile. That is exactly why
   the guarantee is `BOUNDED`, not `FORM_EXACT`, and the boundary is
   named in the manifest.
"""
from __future__ import annotations

import unittest
from dataclasses import fields

from kir.decompile.l1_schema import AtomReason
from kir.decompile.lift import (
    _CANDIDATES,
    _OPS_WITHOUT_L0_INPUTS,
    lift_document_detailed,
)
from kir.decompile.schema import (
    GeometryKind,
    L0Document,
    L0Element,
    LevelInfo,
    LocationCurveKind,
    ProjectInfo,
)
from kir.reverse_contract import (
    REVERSE_CONTRACTS,
    ReverseGuarantee,
    ReverseMode,
)


def _run(eid, category, *, curve_kind=None, params=None, is_placeholder=None,
         flex_path_mm=None):
    """An MEP linear run exactly in the shape emission returns it."""

    return L0Element(
        element_id=eid, category=category, category_ru="",
        type_id="7001", type_name="Тип 100",
        level_id="10", level_name="Этаж 1",
        geom_kind=GeometryKind.CURVE,
        p0_mm=(0.0, 0.0, 3000.0), p1_mm=(6000.0, 0.0, 3000.0),
        rotation_deg=None, bbox_min_mm=None, bbox_max_mm=None,
        host_id=None, params=params or {}, curve_kind=curve_kind,
        is_placeholder=is_placeholder, flex_path_mm=flex_path_mm)


def _doc(*elements):
    return L0Document(
        doc_name="mep", revit_version="2023", units="mm", change_stamp="t",
        levels=(LevelInfo("10", "Этаж 1", 0.0),), grids=(), rooms=(),
        project_info=ProjectInfo(), elements=elements)


def _lift(*elements):
    result = lift_document_detailed(_doc(*elements))
    return ({node["source_element_id"]: node for node in result.nodes},
            {item.source_element_id: item for item in result.diagnostics})


class ConduitActuallyLifts(unittest.TestCase):
    """The manifest's promise, checked by the lift, not by reading the
    manifest."""

    def test_a_straight_conduit_becomes_create_conduit(self):
        nodes, diagnostics = _lift(_run("101", "OST_Conduit"))
        self.assertEqual(diagnostics, {})
        node = nodes["101"]
        self.assertEqual(node["kind"], "op", node.get("reason"))
        self.assertEqual(node["op_name"], "create_conduit")
        self.assertEqual(node["params"]["p0_mm"], [0.0, 0.0, 3000.0])
        self.assertEqual(node["params"]["p1_mm"], [6000.0, 0.0, 3000.0])
        self.assertEqual(
            node["params"]["level"],
            {"by": "name", "value": "Этаж 1", "_id": "10"})
        self.assertEqual(node["params"]["conduit_type"]["by"], "name")

    def test_the_diameter_is_deliberately_absent(self):
        """The duct's nominal size is the type's trade size, and the
        forward op does not take it.

        Lifting a number that cannot be built back would mean passing an
        unbuildable program off as a closed loop.
        """

        nodes, _ = _lift(_run("101", "OST_Conduit",
                              params={"RBS_CONDUIT_DIAMETER_PARAM": 50.0}))
        self.assertNotIn("diameter_mm", nodes["101"]["params"])

    def test_a_non_line_conduit_stays_an_honest_atom(self):
        """REFUTING: a chord in place of an arc would pass verify as
        exact."""

        nodes, diagnostics = _lift(
            _run("102", "OST_Conduit", curve_kind=LocationCurveKind.ARC))
        self.assertEqual(nodes["102"]["kind"], "atom")
        self.assertIs(
            diagnostics["102"].reason, AtomReason.CURVE_KIND_UNSUPPORTED)


class FlexRunsAreNowLiftedFromTheirOwnPoints(unittest.TestCase):
    """The gap was closed on 04.09.2026; both the LIFT and BOTH of its
    boundaries are pinned down.

    The class was called `FlexRunsRefuseByTheirOwnName` and held the
    REFUSAL — the correct shape for exactly as long as the point array
    was absent from capture. Now it holds the lift, and the refusal has
    not gone anywhere: it moved down from the table row to the SNAPSHOT
    row, and an old snapshot must receive it VERBATIM.
    """

    CATEGORIES = {
        "OST_FlexDuctCurves": ("create_flex_duct", "flex_duct_type"),
        "OST_FlexPipeCurves": ("create_flex_pipe", "flex_pipe_type"),
    }
    PATH = ((0.0, 0.0, 3000.0), (2000.0, 0.0, 3300.0), (4000.0, 0.0, 3000.0))

    def test_a_captured_path_lifts_into_the_op_point_for_point(self):
        """ALL the points and their COUNT, not just the ends: that is
        what the forward op requires."""

        for category, (op_name, type_param) in sorted(self.CATEGORIES.items()):
            with self.subTest(category=category):
                nodes, diagnostics = _lift(
                    _run("400", category, flex_path_mm=self.PATH))
                self.assertEqual(diagnostics, {})
                node = nodes["400"]
                self.assertEqual(node["op_name"], op_name)
                self.assertEqual(
                    node["params"]["path"],
                    [list(point) for point in self.PATH],
                    "трасса обязана доехать точка в точку: проверка концов "
                    "пропустила бы выброшенную середину")
                self.assertIn(type_param, node["params"])

    def test_an_old_snapshot_still_refuses_with_the_very_same_words(self):
        """THE FIRST BOUNDARY. A snapshot without the key gets the same
        atom, the same reason.

        The text is assembled by the same instrument from the registry
        that assembled it yesterday, so "1 of 2" and the name of the
        missing input stay exactly where they were.
        """

        for category, (op_name, _type_param) in sorted(self.CATEGORIES.items()):
            with self.subTest(category=category):
                nodes, diagnostics = _lift(_run("401", category))
                node = nodes["401"]
                self.assertEqual(node["kind"], "atom")
                self.assertIs(
                    diagnostics["401"].reason, AtomReason.SOURCE_CONTRACT_GAP,
                    "no_lifter послал бы писать операцию, которая написана")
                detail = node["reason"]["detail"]
                self.assertIn(op_name, detail)
                self.assertIn("path", detail)
                # A partial gap must not be called a complete one.
                self.assertNotIn("НИ ОДНОГО", detail)
                self.assertIn("1 из 2", detail)
                self.assertIn("level", detail)

    def test_a_run_longer_than_the_language_refuses_by_name(self):
        """THE SECOND BOUNDARY. 65 points is a refusal, NOT a truncated
        route.

        Truncation would pass a different route off as this one under a
        green verdict, and that is the same substitution the
        chord-instead-of-arc rule was set up to forbid.
        """

        long_path = tuple((float(i) * 100, 0.0, 3000.0) for i in range(70))
        for category, (op_name, _type_param) in sorted(self.CATEGORIES.items()):
            with self.subTest(category=category):
                nodes, diagnostics = _lift(
                    _run("402", category, flex_path_mm=long_path))
                node = nodes["402"]
                self.assertEqual(node["kind"], "atom")
                self.assertIs(
                    diagnostics["402"].reason,
                    AtomReason.UNSUPPORTED_SIGNATURE,
                    "причина адресует РЕЕСТР (оп не выражает), а не чтение: "
                    "прочитано было всё")
                detail = node["reason"]["detail"]
                self.assertIn(op_name, detail)
                self.assertIn("70", detail)

    def test_the_capture_reads_points_and_not_the_location_curve(self):
        from kir.decompile.extract import build_category_batch_cs

        cs = build_category_batch_cs("OST_FlexDuctCurves")
        self.assertIn("FlexDuct.Points", cs.replace("__fxDuct.Points",
                                                    "FlexDuct.Points"))
        self.assertIn("flex_path_read_failed", cs)

    def test_the_declaration_moved_together_with_the_behaviour(self):
        for _category, (op_name, _type_param) in sorted(self.CATEGORIES.items()):
            contract = REVERSE_CONTRACTS[op_name]
            with self.subTest(op=op_name):
                self.assertIs(contract.mode, ReverseMode.DIRECT)
                self.assertIs(contract.guarantee, ReverseGuarantee.BOUNDED)
                # Both boundaries must be NAMED in the manifest, not live
                # only in the code: the manifest is read instead of the
                # code.
                self.assertIn("flex_path_mm", contract.limitation)
                self.assertIn("64", contract.limitation)
                self.assertFalse(contract.due)


class APlaceholderIsNowToldApartFromARealRun(unittest.TestCase):
    """The gap is closed; what is pinned down is THREE-VALUEDNESS, not
    two outcomes.

    The class was rewritten on 04.09.2026. Before that day it was called
    `APlaceholderRebuildsAsARealRun` and held the declaration and the
    DEFECT locked together — that was the correct shape for exactly as
    long as the bit did not exist. Now it holds the declaration and the
    FIX locked together, including its boundary: an old snapshot does not
    carry the bit and must behave exactly as before.
    """

    PAIRS = (
        ("OST_PipeCurves", "create_pipe", "create_pipe_placeholder",
         "RBS_PIPE_DIAMETER_PARAM"),
        ("OST_DuctCurves", "create_duct", "create_duct_placeholder",
         "RBS_CURVE_DIAMETER_PARAM"),
    )

    def test_l0_carries_the_bit_and_it_is_three_valued(self):
        """Checked STRUCTURALLY, from the row's fields, not from a list
        of strings."""

        by_name = {field.name: field for field in fields(L0Element)}
        self.assertIn(
            "is_placeholder", by_name,
            "поле про род участка исчезло из L0Element: закрытый пробел "
            "create_pipe_placeholder держится именно им")
        self.assertIsNone(
            by_name["is_placeholder"].default,
            "умолчание обязано быть None — «не мерили». False объявил бы "
            "каждый старый слепок состоящим из настоящих участков")

    def test_a_measured_placeholder_lifts_as_the_placeholder_op(self):
        for category, _real_op, placeholder_op, diameter in self.PAIRS:
            with self.subTest(category=category):
                nodes, diagnostics = _lift(_run(
                    "300", category, params={diameter: 100.0},
                    is_placeholder=True))
                self.assertEqual(diagnostics, {})
                node = nodes["300"]
                self.assertEqual(node["op_name"], placeholder_op)
                # A placeholder has no diameter IN THE REGISTRY, and the
                # compiler would reject an extra parameter — the run
                # would become an atom.
                self.assertNotIn("diameter_mm", node["params"])

    def test_a_measured_real_run_lifts_as_the_real_op(self):
        for category, real_op, _placeholder_op, diameter in self.PAIRS:
            with self.subTest(category=category):
                nodes, diagnostics = _lift(_run(
                    "300", category, params={diameter: 100.0},
                    is_placeholder=False))
                self.assertEqual(diagnostics, {})
                node = nodes["300"]
                self.assertEqual(node["op_name"], real_op)
                self.assertIn("diameter_mm", node["params"])

    def test_an_unmeasured_row_behaves_exactly_as_it_did_before(self):
        """THE FIX'S BOUNDARY, pinned down explicitly.

        An old snapshot does not carry the key. It must produce THE SAME
        node it produced before the wave — otherwise the coverage history
        stops being a history.
        """

        for category, real_op, _placeholder_op, diameter in self.PAIRS:
            with self.subTest(category=category):
                nodes, diagnostics = _lift(_run(
                    "300", category, params={diameter: 100.0}))
                self.assertEqual(diagnostics, {})
                node = nodes["300"]
                self.assertEqual(node["op_name"], real_op)
                self.assertIn("diameter_mm", node["params"])

    def test_a_string_instead_of_a_bool_is_refused_at_the_schema(self):
        """`bool("false")` is truthy — the trap is named and closed off
        by a refusal."""

        from kir.decompile.schema import L0SchemaError

        row = _run("300", "OST_PipeCurves").to_dict()
        row["is_placeholder"] = "false"
        with self.assertRaises(L0SchemaError):
            L0Element.from_dict(row)

    def test_the_declaration_moved_together_with_the_behaviour(self):
        for _category, real_op, placeholder_op, _diameter in self.PAIRS:
            contract = REVERSE_CONTRACTS[placeholder_op]
            with self.subTest(op=placeholder_op):
                self.assertIs(contract.mode, ReverseMode.DIRECT)
                # BOUNDED, not FORM_EXACT: the fix has a boundary, and it
                # must be NAMED, not implied.
                self.assertIs(contract.guarantee, ReverseGuarantee.BOUNDED)
                self.assertIn("is_placeholder", contract.limitation)
                self.assertIn(real_op, contract.limitation)
                # The deadline is lifted together with the gap: a dated
                # decision lives exactly as long as the gap it names
                # lives. EMPTINESS is checked, not `None`: for a
                # non-placeholder the field holds an empty string, and
                # `assertIsNone` here would turn red on a correct fix.
                self.assertFalse(contract.due)
                self.assertFalse(contract.decided_on)

    def test_the_capture_writes_the_key_only_when_it_read_it(self):
        """A reading refusal must arrive as an ABSENCE, not as `false`."""

        from kir.decompile.extract import build_category_batch_cs

        cs = build_category_batch_cs("OST_PipeCurves")
        self.assertIn("IsPlaceholder", cs)
        self.assertIn("is_placeholder_read_failed", cs)
        # Not a single `false` record by default: the third state is
        # expressed by the key being absent entirely.
        self.assertNotIn('__row["is_placeholder"] = false', cs)


if __name__ == "__main__":
    unittest.main()
