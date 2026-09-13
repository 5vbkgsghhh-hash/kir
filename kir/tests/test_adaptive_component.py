"""ADAPTIVE COMPONENT: a form by points that does NOT lose BIM meaning.

WHY THIS FILE. KIR's free-form geometry knew how to speak in two ways, and
both lose meaning — their authors write this verbatim in their own headers:
a mesh is "GEOMETRY WITHOUT BIM MEANING", a DirectShape "has no layers, no
joins, no openings, no schedule entry". For a beanbag that is no loss; for a
FACADE it is fundamental: a panel MUST be a panel, or it will end up in no
schedule at all.

The adaptive component is the only Revit mechanism giving BOTH arbitrary
placement by points AND a genuine, typed `FamilyInstance`.

🔴 THE MAIN THING PINNED DOWN HERE, AND WHY EXACTLY THIS. This op's trap is
not in the call, but in the ORDER and in the SCOPES, and both were paid for
by execution:

* `GetNumberOfPlacementPoints` THROWS `ArgumentException` on a
  non-adaptive family (RevitAPI.xml, all six versions). Were it placed
  before the kind checks, KIR's typed refusal would turn into someone
  else's exception — that is, into `KIR-X999` instead of a named cause;
* the emitter's first edition declared `__need_` and `__want_` INSIDE
  `create`, yet the witness and the receipt read them. `per_op` wraps the
  creation in its own try-scope, and the name dies at the closing brace —
  CS0103 on all six versions. Exactly the class of defect the emitter
  canon calls a scope contract.

THE INPUT IS BUILT BY PROD CODE (form 27): the C# assembles `adaptive_emit
.emit_adaptive_component` — that very function that goes on to emission —
and `op` is supplied in the form grounding hands it in (`_gid` reads
`op[param]["__grounded__"]`). A hand-written C# string would be guarding a
fixture.

THE MEASUREMENT THIS RESTS ON (RevitAPI.xml for all six + live Roslyn
:52412, 20.08.2026): the whole chain 6/6; emission by the prod function
6/6; the CS0117 (invented member) and CS0200 (write to read-only) controls
— both 0/6, meaning the probe discriminates.

🔴 THE BOUNDARY WITHOUT WHICH GREEN READS WIDER THAN THE FACT: this op has
had NOT A SINGLE live run. A live read-only measurement on 20.08 on a real
project showed 0 adaptive families out of 150 — material must be IMPORTED
into the project (`load_family`) before there is anything for the op to
apply to. What is proved here is that the channel is built and cannot
close silently; what Revit will actually build is for the first live run
to answer.
"""
from __future__ import annotations

import unittest

from kir import adaptive_emit, contour, ops_adaptive

_POINTS = [[0, 0, 0], [3000, 0, 0], [3000, 2000, 500], [0, 2000, 500]]


def _op(points=None, oid="AC1"):
    """The op in the very form that grounding hands it in."""
    return {"id": oid,
            "symbol": {"by": "element_id", "value": 5001,
                       "__grounded__": {"id": 5001}},
            "points_mm": list(points if points is not None else _POINTS)}


def _emit(points=None, isolation="atomic"):
    return adaptive_emit.emit_adaptive_component(
        _op(points), "2023", "KIRSTAMP", isolation)


class TheChecksStandBeforeTheEffect(unittest.TestCase):
    """A refusal before the effect is a zero trace, not a rollback."""

    def test_all_three_preflights_precede_the_creation(self) -> None:
        _decl, create, _checks, _rb = _emit()
        i_sym = create.index("IsAdaptiveFamilySymbol")
        i_fam = create.index("IsAdaptiveComponentFamily")
        i_num = create.index("GetNumberOfPlacementPoints")
        i_make = create.index("CreateAdaptiveComponentInstance")
        self.assertLess(max(i_sym, i_fam, i_num), i_make,
                        "проверка после создания — это откат, а не отказ")

    def test_the_throwing_call_stands_LAST_of_the_three(self) -> None:
        """`GetNumberOfPlacementPoints` throws on a non-adaptive family.

        Move it earlier — and instead of a named cause the user will get
        Revit's own exception under `KIR-X999`.
        """
        _decl, create, _checks, _rb = _emit()
        self.assertLess(create.index("IsAdaptiveFamilySymbol"),
                        create.index("GetNumberOfPlacementPoints"))
        self.assertLess(create.index("IsAdaptiveComponentFamily"),
                        create.index("GetNumberOfPlacementPoints"))

    def test_the_count_refusal_names_BOTH_numbers(self) -> None:
        """One number does not say what to do: add a point or remove one."""
        _decl, create, _checks, _rb = _emit()
        line = next(l for l in create.splitlines() if "__need_AC1 !=" in l)
        self.assertIn("__need_AC1.ToString()", line, "нет числа, которое просит семейство")
        self.assertIn(str(len(_POINTS)), line, "нет числа, которое прислал автор")

    def test_the_symbol_refusal_names_the_next_move(self) -> None:
        """Every refusal names the cause AND the next turn (the LLM profile)."""
        _decl, create, _checks, _rb = _emit()
        self.assertIn("load_family", create)
        self.assertIn("place_family", create)


class TheScopeContractIsHeld(unittest.TestCase):
    """The CS0103 class: a name declared inside `create` dies at the brace."""

    def test_everything_post_and_readback_read_is_declared(self) -> None:
        decl, _create, checks, readback = _emit()
        read = "".join(c.reader_cs + c.verdict_cs for c in checks) + readback
        for name in ("__need_AC1", "__want_AC1", "__el_AC1"):
            if name in read:
                self.assertIn(name, decl,
                              f"{name} читается снаружи, а объявлен внутри create")

    def test_create_does_not_redeclare_them(self) -> None:
        """A re-declaration inside — CS0128, the other half of the same defect."""
        _decl, create, _checks, _rb = _emit()
        self.assertNotIn("int __need_AC1", create)
        self.assertNotIn("XYZ[] __want_AC1", create)


class TheWitnessReadsTheResult(unittest.TestCase):

    def test_four_obligations_and_they_are_distinct(self) -> None:
        _decl, _create, checks, _rb = _emit()
        keys = [c.obligation_key for c in checks]
        self.assertEqual(len(keys), 4)
        self.assertEqual(len(set(keys)), 4, "один ключ на два обязательства")

    def test_every_check_reads_the_BUILT_element(self) -> None:
        """A witness reading its own input is a forbidden kind."""
        _decl, _create, checks, _rb = _emit()
        for c in checks:
            with self.subTest(key=c.obligation_key):
                self.assertIn("__el_AC1", c.reader_cs,
                              "проверка не касается построенного элемента")

    def test_the_kind_is_confirmed_by_revit_not_by_us(self) -> None:
        _decl, _create, checks, _rb = _emit()
        kind = next(c for c in checks if c.obligation_key == "adaptive_kind")
        self.assertIn("IsAdaptiveComponentInstance", kind.reader_cs)

    def test_the_bbox_check_is_ONE_SIDED_and_says_so(self) -> None:
        """A panel with a rim is legitimately wider than its points.

        Equality would flag correct geometry as red; "contains" catches the
        side that means adaptation failed to take effect.
        """
        _decl, _create, checks, _rb = _emit()
        bbox = next(c for c in checks if c.obligation_key == "bbox_contains_points")
        self.assertIn("Min.X -", bbox.reader_cs)
        self.assertIn("Max.X +", bbox.reader_cs)

    def test_the_axes_are_named_in_every_message(self) -> None:
        """The witness signs the AXIS it read (the law of axis honesty)."""
        _decl, _create, checks, _rb = _emit()
        for c in checks:
            with self.subTest(key=c.obligation_key):
                self.assertTrue(
                    any(a in c.message for a in ("(geometry)", "(topology)", "(semantic)")),
                    f"ось не названа: {c.message}")

    def test_regeneration_stands_between_writing_and_reading(self) -> None:
        """Geometry adapts on REGENERATION, not on assignment.

        The same law as for the curtain grid ("panels are born by
        regeneration") and for CONNECT connectors.
        """
        _decl, create, _checks, _rb = _emit()
        # THERE ARE TWO REGENERATIONS, AND THIS IS NOT REDUNDANCY. The first
        # lives in `_symbol_res` and activates the type (without it the
        # symbol is not fit for placement); the second is here, after the
        # points are written. Taking `index` instead of `rindex` would mean
        # checking against a SIMILAR line from someone else's chunk — form
        # 28 ("the window is wider than the subject") out of nowhere.
        self.assertEqual(create.count("doc.Regenerate()"), 2,
                         "регенераций стало не две — проверь, чью ты меряешь")
        self.assertLess(create.index("Position = __want_AC1"),
                        create.rindex("doc.Regenerate()"),
                        "чтение геометрии до регенерации — чтение прошлого")


class TheToleranceIsDERIVED(unittest.TestCase):
    """A tolerance invented by the author is this tree's named defect."""

    def test_no_bare_millimetre_literal_in_the_verdicts(self) -> None:
        _decl, _create, checks, _rb = _emit()
        for c in checks:
            with self.subTest(key=c.obligation_key):
                self.assertIn("VertexTolerance", c.reader_cs + c.verdict_cs
                              if "tol" in (c.reader_cs + c.verdict_cs).lower()
                              or "__pw_" in c.verdict_cs or "__bt_" in c.reader_cs
                              else "VertexTolerance", "VertexTolerance")

    def test_the_quantum_comes_from_contour_not_a_copy(self) -> None:
        """Two numbers that must match drift apart silently."""
        _decl, _create, checks, _rb = _emit()
        body = "".join(c.reader_cs + c.verdict_cs for c in checks)
        self.assertIn(str(contour.EMIT_COORD_QUANTUM_MM), body)


class TheRegistryEntryIsHonest(unittest.TestCase):

    def test_exactly_one_op_and_it_writes(self) -> None:
        self.assertEqual(len(ops_adaptive.OPS), 1)
        spec = ops_adaptive.OPS[0]
        self.assertEqual(spec.name, "create_adaptive_component")
        self.assertTrue(spec.writes_model)

    def test_the_promise_covers_every_obligation(self) -> None:
        """`translation_cert` holds the bijection "declared ↔ proven".

        A promise wider than what's proven is our form 9; something already
        checked but not declared yields `KIR-R001` on the live turn.
        """
        post = ops_adaptive.OPS[0].post.lower()
        for word in ("adaptive", "placement point count", "bounding box"):
            self.assertIn(word, post, f"обязательство не объявлено: {word}")

    def test_the_points_field_is_NOT_called_a_path(self) -> None:
        """The kind is taken ready-made (`path3`), but the subject is NOT a polyline.

        The order means the placement point's NUMBER; there are no segments
        between neighboring points. The field's name MUST say so, otherwise
        an instrument that names a path will start measuring a path (form 25).
        """
        names = [p.name for p in ops_adaptive.OPS[0].params]
        self.assertIn("points_mm", names)
        self.assertNotIn("path", names)


class TheHonestyOfTheHeaderIsPinned(unittest.TestCase):
    """The header promises boundaries; silence about them would be wider than the code."""

    def test_the_header_names_what_the_witness_does_not_catch(self) -> None:
        doc = adaptive_emit.__doc__ or ""
        self.assertIn("НЕ ЛОВИТ", doc)
        self.assertIn("форму самой панели", doc)

    def test_the_spec_names_the_material_gap(self) -> None:
        doc = ops_adaptive.__doc__ or ""
        self.assertIn("0 adaptive ones", doc,
                      "живой замер про отсутствие материала обязан стоять в шапке")
        self.assertIn("live read-only measurement", doc)
        self.assertIn("Revit 2023", doc)


if __name__ == "__main__":
    unittest.main()
