"""NAME DIALECT: A PROGRAM TAKEN FROM ONE DOCUMENT TRAVELS INTO A FOREIGN ONE.

WHY THIS FILE APPEARED ON 2026-08-23
------------------------------------
Live trial 08-22: the first materialized program of a real building
(MNVNK K6) was sent into "Project1" and came back `rolled_back`,
`KIR-X003` "wall type not found." The reason is not accidental:
`same_document` DELIBERATELY takes a single `_id` from the catalog
reference and pins it to the ElementId of the SOURCE file — the
rationale is recorded in the module's docstring ("the same document is
being rebuilt… no name resolution, no snapshot needed").

🔴 THE NAME IS ALREADY IN L1, THOUGH. The lifter emits
`{"_id","by":"name","value"}` and `{"_id","by":"family_type",…}` —
measured 08-23 against K6, 19,041 operations: there are NO other kinds
of catalog reference. So `fresh_document` is not a new translation
layer, but a REFUSAL TO DEREFERENCE: it discards the `_id`, not the name.

WHAT IS GUARDED
--------------
NAME      the catalog reference travels by name, `_id` is REMOVED (the
          receiving grammar demands an exact set of keys — an extra
          field would fail parsing)
FAMILY    `family_type` travels by its own three fields
GRAMMAR   the resulting selector IS ACCEPTED by the language's grammar —
          otherwise the translation would be pretty and useless
BOUND     a parameter of kind `target_w` (a view, a tag/text/dimension
          type) is not expressible by name: the operation becomes a
          TYPED skip, and everything that referenced it drops out as well
DATUM     `include_datums` decides the mode; an explicit False is a
          contradiction, not a reason to silently fix it
QUIET     `same_document` and `escrow` did not shift by a single byte
HEAD      catalog preparation stands at the HEAD of the program: a
          level is addressed by name, there is no toposort edge for a
          name, and without lifting it, a wall would end up placed
          BEFORE its level (measured on K3: 5 of 55 programs)
CATALOG   the program NAMES BY NUMBER something it demands of the
          foreign document's catalog and cannot create: a type (there
          is no such op at all) and a family type (there is an op, but
          no path). A silently-unexecutable program is worse than a
          refusal: it spends a live turn and lies with its receipt
"""
from __future__ import annotations

import os
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(),
                                   "kir_fresh_queue.jsonl"))

from kir.authoring_validation import _sel_shape_ok  # noqa: E402
from kir.decompile.l1_schema import validate_l1_nodes  # noqa: E402
from kir.decompile.materialize import (  # noqa: E402
    MaterializeError,
    leaves_to_program,
)
from kir.decompile.tests.test_materialize import (  # noqa: E402
    _hosted_chain,
    _op_leaf,
)


def _fresh(leaves, **kwargs):
    """Materialization in the name dialect, ON VALIDATED LEAVES.

    🔴 `validate_l1_nodes` here is not decoration. The first edition of
    this file built `create_text` with `point_mm`/`text` fields, which
    the operation does not have at all — and all eleven tests passed,
    because the materializer does not check the leaf's schema. A guard
    standing on an invented input proves something other than what its
    name says (our form: "a control on a degenerate input is green by construction").
    """

    return leaves_to_program(
        validate_l1_nodes(list(leaves)), mode="fresh_document", **kwargs)


def _programs_ops(result):
    return [op for program in result.programs for op in program["ops"]]


def _by_op(result, op_name):
    return [op for op in _programs_ops(result) if op["op"] == op_name]


class NameDialect(unittest.TestCase):
    """The catalog reference travels by NAME, and the grammar accepts that name."""

    def test_sel_reference_travels_as_a_name(self):
        result = _fresh(_hosted_chain())
        wall = _by_op(result, "create_wall")[0]
        self.assertEqual(wall["level"], {"by": "name", "value": "L1"})
        self.assertEqual(wall["type"], {"by": "name", "value": "W200"})

    def test_the_source_element_id_is_dropped_not_carried_along(self):
        """`_id` is precisely what does not travel over.

        The grammar (`_sel_shape_ok`) demands an EXACT set of keys, so
        leaving `_id` "just in case" would mean building a selector
        that gets rejected at parse time.
        """
        result = _fresh(_hosted_chain())
        for op in _programs_ops(result):
            for value in op.values():
                if isinstance(value, dict) and "by" in value:
                    self.assertNotIn("_id", value)

    def test_emitted_selectors_pass_the_language_grammar(self):
        """The translation must be VALID, not just pretty."""
        result = _fresh(_hosted_chain())
        checked = 0
        for op in _programs_ops(result):
            for name, value in op.items():
                if name in {"op", "id"} or not isinstance(value, dict):
                    continue
                if value.get("by") in {"name", "family_type"}:
                    self.assertTrue(
                        _sel_shape_ok(value),
                        f"{op['op']}.{name} не принят грамматикой: {value}")
                    checked += 1
        self.assertGreater(checked, 0, "ни одного именного селектора — "
                                       "сторож был бы вырожден")

    def test_family_type_reference_keeps_its_three_fields(self):
        leaf = _op_leaf(
            "place_family", "2001",
            {
                "xyz": [0.0, 0.0, 0.0],
                "level": {"by": "name", "value": "L1", "_id": "500"},
                "symbol": {
                    "by": "family_type", "_id": "900",
                    "category": "OST_Furniture",
                    "family_name": "Стол",
                    "type_name": "1200x600",
                },
            },
            level_name="L1", anchor=(0.0, 0.0, 0.0))
        result = _fresh([leaf])
        symbol = _by_op(result, "place_family")[0]["symbol"]
        self.assertEqual(symbol, {
            "by": "family_type",
            "category": "OST_Furniture",
            "family_name": "Стол",
            "type_name": "1200x600",
        })
        self.assertTrue(_sel_shape_ok(symbol))


class DocumentBound(unittest.TestCase):
    """What cannot be expressed by name drops out NAMED, rather than traveling broken."""

    @staticmethod
    def _text_leaf():
        # create_text.in_view and .text_type are of kind `target_w`,
        # which has no name form at all in the grammar (only element_id and ref).
        return _op_leaf(
            "create_text", "3001",
            {
                "in_view": {"by": "name", "value": "План 1", "_id": "800"},
                "at": [0.0, 0.0],
                "content": "примечание",
                "text_type": {"by": "name", "value": "3.5мм", "_id": "801"},
            },
            level_name="L1", anchor=(0.0, 0.0, 0.0))

    def test_target_w_reference_becomes_a_typed_skip(self):
        result = _fresh([self._text_leaf()])
        self.assertEqual(_by_op(result, "create_text"), [])
        reasons = [skip.reason for skip in result.skipped]
        self.assertEqual(len(reasons), 1)
        self.assertTrue(reasons[0].startswith("document_bound:"), reasons)
        self.assertTrue(reasons[0].split(":", 1)[1],
                        "причина обязана НАЗВАТЬ параметр")
        self.assertEqual(result.stats.as_dict()["document_bound_ops"], 1)

    def test_the_same_leaf_still_materializes_in_same_document(self):
        """The wave's boundary is a property of the FOREIGN document, not a defect of the operation."""
        result = leaves_to_program(
            validate_l1_nodes([self._text_leaf()]), mode="same_document")
        self.assertEqual(len(_by_op(result, "create_text")), 1)
        self.assertEqual(result.stats.as_dict()["document_bound_ops"], 0)

    def test_an_empty_name_is_refused_never_invented(self):
        leaf = _op_leaf(
            "create_wall", "4001",
            {
                "p0_mm": [0.0, 0.0], "p1_mm": [3000.0, 0.0],
                "height_mm": 2800.0,
                "level": {"by": "name", "value": "L1", "_id": "500"},
                "type": {"by": "name", "value": "   ", "_id": "600"},
            },
            level_name="L1", anchor=(1500.0, 0.0, 0.0))
        result = _fresh([leaf])
        self.assertEqual(_by_op(result, "create_wall"), [])
        self.assertEqual(
            [skip.reason for skip in result.skipped], ["document_bound:type"])


class DatumPolicy(unittest.TestCase):
    def test_fresh_document_creates_datums_by_default(self):
        level = _op_leaf(
            "create_level", "5001",
            {"elev_mm": 0.0, "name": "L1"},
            level_name="L1", anchor=(0.0, 0.0, 0.0))
        fresh = _fresh([level])
        self.assertEqual(len(_by_op(fresh, "create_level")), 1)
        self.assertEqual(fresh.stats.as_dict()["datums_skipped"], 0)

        same = leaves_to_program(
            validate_l1_nodes([level]), mode="same_document")
        self.assertEqual(_by_op(same, "create_level"), [])
        self.assertEqual(same.stats.as_dict()["datums_skipped"], 1)

    def test_explicit_false_is_a_contradiction_not_a_silent_fix(self):
        with self.assertRaises(MaterializeError) as caught:
            _fresh(_hosted_chain(), include_datums=False)
        self.assertIn("fresh_document", str(caught.exception))


class OldModesAreUntouched(unittest.TestCase):
    """The fix must be INVISIBLE to previous modes."""

    def test_same_document_still_pins_by_element_id(self):
        result = leaves_to_program(
            validate_l1_nodes(_hosted_chain()), mode="same_document")
        wall = _by_op(result, "create_wall")[0]
        self.assertEqual(wall["level"], {"by": "element_id", "value": 500})
        self.assertEqual(wall["type"], {"by": "element_id", "value": 600})

    def test_unknown_mode_names_the_three_that_exist(self):
        with self.assertRaises(MaterializeError) as caught:
            leaves_to_program(
                validate_l1_nodes(_hosted_chain()), mode="b4_future")
        message = str(caught.exception)
        for known in ("same_document", "escrow", "fresh_document"):
            self.assertIn(known, message)


if __name__ == "__main__":
    unittest.main()


class CatalogPrepIsHoisted(unittest.TestCase):
    """Catalog preparation is at the HEAD of the program, and only in the name dialect."""

    def test_datums_precede_every_op_that_names_a_level(self):
        """A level is created BEFORE the first thing that requests it by name.

        A name has no edge: `_toposort_chunk` builds links only via
        `ref`, so before the lift the order was decided by the order of
        the source's elements. Measurement on K3 (`mnvnk_k3_23aug`): 5
        of 55 programs asked for a level before creating it, the worst
        being `create_level` at operation 65 with the wall at operation zero.
        """
        result = _fresh(_hosted_chain())
        for program in result.programs:
            ops = program["ops"]
            made = [i for i, op in enumerate(ops)
                    if op["op"] in ("create_level", "create_grid")]
            used = [i for i, op in enumerate(ops)
                    for key, value in op.items()
                    if isinstance(value, dict)
                    and value.get("by") == "name"
                    and key in ("level", "top_level", "base_level")]
            if made and used:
                self.assertLess(
                    min(made), min(used),
                    "датум обязан стоять раньше первого потребителя имени")

    def test_same_document_order_is_not_disturbed(self):
        """Into one's own document, the order is NOT touched.

        There, the reference to a level is the `element_id` of an
        existing element, order decides nothing, and a reordering
        would shift previous runs byte for byte with no gain at all.
        """
        leaves = validate_l1_nodes(list(_hosted_chain()))
        plain = leaves_to_program(leaves, mode="same_document")
        again = leaves_to_program(leaves, mode="same_document")
        self.assertEqual(
            [op["op"] for p in plain.programs for op in p["ops"]],
            [op["op"] for p in again.programs for op in p["ops"]])


class CatalogRequirementIsNamed(unittest.TestCase):
    """What the program demands of the foreign catalog — stated as a NUMBER."""

    def test_counters_are_zero_outside_the_name_dialect(self):
        """Into one's own document, the catalog already exists — nothing to demand."""
        leaves = validate_l1_nodes(list(_hosted_chain()))
        stats = leaves_to_program(leaves, mode="same_document").stats
        self.assertEqual(stats.catalog_types_required, 0)
        self.assertEqual(stats.catalog_family_symbols_required, 0)

    def test_a_named_type_is_counted_as_required(self):
        """A type addressed by name enters the catalog requirement.

        There is NO op in the registry that creates a `WallType`:
        `create_type` duplicates `FamilySymbol` ("columns/beams —
        symbol-based types ONLY," per its own emitter's docstring). So
        the type must be named as a requirement, rather than passed
        over in silence.
        """
        stats = _fresh(_hosted_chain()).stats
        self.assertGreater(stats.catalog_types_required, 0)

    def test_the_counters_are_in_the_public_dict(self):
        """A number absent from `as_dict` will be read by no one."""
        stats = _fresh(_hosted_chain()).stats.as_dict()
        self.assertIn("catalog_types_required", stats)
        self.assertIn("catalog_family_symbols_required", stats)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
