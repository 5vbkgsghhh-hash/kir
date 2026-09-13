"""CAPTURING THE HOST OF A SYSTEM ELEMENT — and the promise about a strip
foundation.

`extract.build_category_batch_cs` was filling `host_id` by a SINGLE method —
`__element as FamilyInstance`. A system element (`WallFoundation`, `Railing`,
`Opening`, pipe/duct insulation) does not fit this cast, so its `host_id`
stayed empty ALWAYS, and L0 carried not a single fact about it by which it
could be told apart from a family instance of the SAME category: the
`category` of a wall foundation and of an isolated footing is one and the same
(`OST_StructuralFoundation`), and distinguishing by `type_name` is matching by
a bare name, which canon forbids.

WHAT WAS BREAKING (measured by reading the code on 09.08, branch
feat/kir-day-integration). The `reverse_contract` for `create_wall_foundation`
promises: such an element is "a typed atom, NEVER silently re-emitted as an
isolated footing." `lift._lift_foundation`, when `geom_kind is POINT`, emits
`create_foundation(variety="isolated")` without a single check on WHAT the
element is. The promise held exactly because `WallFoundation` has no
`LocationPoint` — that is, BY REVIT'S BEHAVIOR, not by our invariant. This is
the same class as a test that passes by a fixture's coincidence.

HOW IT WAS FIXED: the capture got ONE table of host readers
(`extract._HOST_READERS`) and one generator for it; along with `host_id`, the
row now carries `host_source` — the CLASS of the relation, not a guess by
name. The lifter refuses by CLASS (`HostSource.WALL_FOUNDATION`), not by the
mere fact "a host exists": in a frozen L0 a non-empty `host_id` PROVES that
the element was a `FamilyInstance` (no other branch filled it), i.e. an
honest footing after all. Refusing on `host_id` alone would have rejected
correct work.

Discipline §18.7: a refuting test BEFORE the fix.
"""
from __future__ import annotations

import unittest

from kir.decompile.extract import build_category_batch_cs
from kir.decompile.l1_schema import AtomReason
from kir.decompile.lift import _SHAPE_REFUSALS, lift_document_detailed
from kir.decompile.schema import (
    GeometryKind,
    L0Document,
    L0Element,
    LevelInfo,
    ProjectInfo,
)


def _row(
    category: str,
    element_id: str,
    *,
    geom_kind: str,
    host_id: str | None = None,
    host_source: str | None = None,
) -> dict:
    """The L0 row exactly as the bridge hands it over.

    The element is built THROUGH ``from_dict``, not through the constructor,
    deliberately: this way the very same test text is executable both BEFORE
    the fix (an extra key is simply ignored by parsing) and after — that is,
    "was red before, went green after" is checked verbatim by one file, not
    by two of its revisions.
    """
    row: dict = {
        "element_id": element_id,
        "category": category,
        "category_ru": "—",
        "type_id": "7",
        "type_name": "ФМ1",
        "level_id": "10",
        "level_name": "L1",
        "geom_kind": geom_kind,
        "p0_mm": (
            [1000.0, 2000.0, 0.0] if geom_kind in ("point", "curve") else None),
        "p1_mm": [4000.0, 2000.0, 0.0] if geom_kind == "curve" else None,
        "rotation_deg": 0.0 if geom_kind == "point" else None,
        "bbox_min_mm": [0.0, 0.0, 0.0],
        "bbox_max_mm": [2000.0, 3000.0, 600.0],
        "host_id": host_id,
        "params": {},
    }
    if host_source is not None:
        row["host_source"] = host_source
    return row


def _document(*rows: dict) -> L0Document:
    return L0Document(
        doc_name="host-capture", revit_version="2024", units="mm",
        change_stamp="t", levels=(LevelInfo("10", "L1", 0.0),),
        grids=(), rooms=(), project_info=ProjectInfo(),
        elements=tuple(L0Element.from_dict(row) for row in rows))


def _nodes(result) -> dict:
    return {node["source_element_id"]: node for node in result.nodes}


class CaptureReadsTheHostOfASystemElement(unittest.TestCase):
    """1 — the hole is wider than one foundation: we measure the CAPTURE, not
    the lifter."""

    def test_family_instance_branch_alone_leaves_system_elements_blind(
        self,
    ) -> None:
        """One mechanism, not a list of special cases.

        The readers are held by ONE table and rendered by ONE generator;
        `FamilyInstance` is included in it on equal terms and has stopped
        being a special case. The test demands exactly this: that the source
        of every branch be named in the row, not implied by its order.
        """
        cs = build_category_batch_cs("OST_StructuralFoundation")
        # Names are FULL: the extraction body is wrapped by different
        # wrappers, and depending on the `using` declared in them means
        # depending on a file the generator does not see.
        for token in (
            "as Autodesk.Revit.DB.FamilyInstance", '"family_instance"',
            "as Autodesk.Revit.DB.WallFoundation", '"wall_foundation"',
            "as Autodesk.Revit.DB.Architecture.Railing", '"railing"',
            "as Autodesk.Revit.DB.Opening", '"opening"',
            "as Autodesk.Revit.DB.InsulationLiningBase", '"insulation_lining"',
            '__row["host_source"]',
        ):
            self.assertIn(token, cs, token)

    def test_reader_block_is_identical_across_categories(self) -> None:
        """The readers do not depend on the category — just like the
        parameter block.

        The gate compiles the extraction on THREE categories precisely on
        this basis (`gate_runner`: "the parameter block is common to all
        categories, only the collector differs"). If the readers were set per
        category, three categories would stop covering the other 74.
        """
        bodies = [build_category_batch_cs(name) for name in
                  ("OST_Walls", "OST_StructuralFoundation",
                   "OST_StairsRailing", "OST_PipeInsulations")]
        blocks = [body.split('__row["host_id"] = null;')[1].split(
            "__PutParams")[0] for body in bodies]
        self.assertEqual(len(set(blocks)), 1, "блок читателей разъехался")

    def test_no_host_is_null_and_never_the_string_of_invalid_id(self) -> None:
        """`ElementId.InvalidElementId` means "there is no host", not a host
        of "-1".

        Branches that read `ElementId` directly (`WallFoundation.WallId`,
        `Railing.HostId`, `InsulationLiningBase.HostElementId`) must filter
        out an invalid id: without this, a freestanding railing would get
        `host_id = "-1"` — a non-empty string, i.e. a FALSE host, which is
        worse than an empty field.
        """
        cs = build_category_batch_cs("OST_StairsRailing")
        self.assertIn("ElementId.InvalidElementId", cs)
        # The idiom for all six versions: ToString() only; neither .Value nor
        # .IntegerValue (ElementId has no member common across 2021-2026).
        block = cs.split('__row["host_id"] = null;')[1].split("__PutParams")[0]
        self.assertNotIn("IntegerValue", block)
        self.assertNotIn(".Value", block)


class AWallFoundationIsNeverAnIsolatedFooting(unittest.TestCase):
    """2 — the reverse_contract promise, backed by CODE, not by behavior."""

    def test_point_placed_wall_foundation_becomes_a_typed_atom(self) -> None:
        """REFUTING TEST. Before the fix, `create_foundation` stood here.

        Exactly the branch for whose sake this work exists: `geom_kind is
        POINT` was going into `variety="isolated"` without a single check on
        the element's class.
        """
        result = lift_document_detailed(_document(_row(
            "OST_StructuralFoundation", "500", geom_kind="point",
            host_id="900", host_source="wall_foundation")))
        node = _nodes(result)["500"]
        self.assertEqual(
            node["kind"], "atom",
            f"ленточный фундамент переизлучён как {node.get('op_name')!r}: "
            f"{node.get('params')!r}")

    def test_the_refusal_survives_every_geometry_kind(self) -> None:
        """Refusal by CLASS, not by geometry.

        Before the fix, the promise held only because `WallFoundation` has no
        `LocationPoint`. The invariant must not depend on exactly what Revit
        put into the geometry.
        """
        for geom_kind in ("point", "bbox_only", "curve"):
            with self.subTest(geom_kind=geom_kind):
                result = lift_document_detailed(_document(_row(
                    "OST_StructuralFoundation", "501", geom_kind=geom_kind,
                    host_id="900", host_source="wall_foundation")))
                node = _nodes(result)["501"]
                self.assertEqual(node["kind"], "atom", geom_kind)

    def test_the_reason_never_falls_through_to_place_family(self) -> None:
        """Not a SHAPE refusal: otherwise the strip would become an ordinary
        family.

        `MISSING_GEOMETRY` (today's answer for a bbox foundation) is included
        in `_SHAPE_REFUSALS`, i.e. it hands the element off to
        `place_family`. For a wall foundation this is not "a partial
        success" but the loss of the object.
        """
        result = lift_document_detailed(_document(_row(
            "OST_StructuralFoundation", "502", geom_kind="bbox_only",
            host_id="900", host_source="wall_foundation")))
        node = _nodes(result)["502"]
        self.assertEqual(node["kind"], "atom")
        reason = node["reason"]
        self.assertNotIn(
            AtomReason(reason["code"]), _SHAPE_REFUSALS, reason["code"])
        self.assertIn("wall_foundation", reason["detail"])


class TheRefusalMustNotCostWorkingCoverage(unittest.TestCase):
    """3 — honesty bought by refusing correct work is not honesty."""

    def test_a_hosted_family_instance_footing_still_lifts(self) -> None:
        """A footing on a face/work plane is still `isolated`.

        Refusing on a mere non-empty `host_id` would reject this element, and
        it is EXACTLY the one for whose sake the `isolated` branch was
        written.
        """
        result = lift_document_detailed(_document(_row(
            "OST_StructuralFoundation", "503", geom_kind="point",
            host_id="900", host_source="family_instance")))
        node = _nodes(result)["503"]
        self.assertEqual(node["kind"], "op")
        self.assertEqual(node["op_name"], "create_foundation")
        self.assertEqual(node["params"]["variety"], "isolated")

    def test_frozen_l0_without_the_field_answers_exactly_as_before(
        self,
    ) -> None:
        """The absence of `host_source` means "not measured", not "a system
        element".

        All 67 stored decompiles were taken before this wave. A non-empty
        `host_id` in them PROVES `FamilyInstance` — no other branch filled it
        in — so an old snapshot must give the previous answer verbatim.
        """
        for host_id in (None, "900"):
            with self.subTest(host_id=host_id):
                result = lift_document_detailed(_document(_row(
                    "OST_StructuralFoundation", "504", geom_kind="point",
                    host_id=host_id)))
                node = _nodes(result)["504"]
                self.assertEqual(node["kind"], "op")
                self.assertEqual(node["params"]["variety"], "isolated")


class TheClassFactRoundTripsThroughL0(unittest.TestCase):
    """4 — the field was appended AT THE TAIL by the law of appending (like
    `curve_kind`)."""

    def test_host_source_round_trips(self) -> None:
        element = L0Element.from_dict(_row(
            "OST_StairsRailing", "600", geom_kind="bbox_only",
            host_id="900", host_source="railing"))
        restored = L0Element.from_dict(element.to_dict())
        self.assertEqual(restored, element)
        self.assertEqual(restored.host_source.value, "railing")

    def test_old_row_without_the_field_stays_valid(self) -> None:
        element = L0Element.from_dict(_row(
            "OST_Doors", "601", geom_kind="point", host_id="900"))
        self.assertIsNone(element.host_source)
        self.assertIsNone(element.to_dict()["host_source"])

    def test_a_source_without_an_id_is_refused(self) -> None:
        """A source without an id is a contradiction, not a sparse row."""
        from kir.decompile.schema import L0SchemaError
        with self.assertRaises(L0SchemaError):
            L0Element.from_dict(_row(
                "OST_StructuralFoundation", "602", geom_kind="point",
                host_id=None, host_source="wall_foundation"))


if __name__ == "__main__":
    unittest.main()
