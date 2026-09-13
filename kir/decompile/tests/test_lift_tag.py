"""Lifting a TAG — and five refusals it has no right to dodge.

A tag is the first KIR operation whose required input is a REFERENCE TO
ANOTHER ELEMENT. A note has none (the text is self-sufficient), a door
has one but it resolves from the L0 row itself (``host_id``). Here the
reference comes from the SIDE INDEX and may fail to resolve, and every
way it can fail must be NAMED, not sidestepped:

1. the index is absent entirely (every snapshot before this wave) — the
   old ``source_contract_gap`` VERBATIM, otherwise the coverage history
   stops being a history;
2. the tagged element is not among those read — ``missing_reference``.
   Attaching the tag to a similar element would be the worst possible
   choice: it would pass the L1 schema and look like coverage;
3. a room/area tag is a ``SpatialElementTag``, and the forward path only
   knows ``IndependentTag.Create``. Reassembly would build THE WRONG
   THING, hence ``unsupported_forward_signature``;
4. the tag has a LEADER, in which case the seventh argument of
   ``Create`` means not the head but the leader's endpoint (Autodesk's
   verbatim wording, the same in 2021 and in 2026) — while the stage
   reads ``TagHeadPosition``;
5. the tag is rotated, but the emitter hardcodes
   ``TagOrientation.Horizontal`` unconditionally — a silent straightening
   invisible to a head-position comparison, hence also a named refusal.

The fourth and fifth refusals cost more than the others: they CUT
coverage that would otherwise have been counted. That is exactly why
they are here and not on the "finish later" list: imperfect is allowed,
lying is not.
"""
from __future__ import annotations

import copy
import unittest

from kir.decompile.l1_schema import AtomReason
from kir.decompile.lift import lift_document_detailed
from kir.decompile.lift_cache import lift_cache_key
from kir.decompile.schema import L0Document
from kir.decompile.tag_extract import TagExtraction, TagRecord
from kir.decompile.tests.fixtures_decompile import (
    make_element,
    project1_metadata,
)


TAG_ID = "4300"
WALL_ID = "512"
VIEW_ID = "900"
VIEW_NAME = "1 этаж"


def _document(tag_category: str = "OST_WallTags") -> L0Document:
    row = copy.deepcopy(project1_metadata())
    row["change_stamp"] = "tag-wave"
    wall = make_element("OST_Walls", int(WALL_ID))
    tag = make_element(tag_category, int(TAG_ID))
    row["elements"] = [tag, wall]
    row["category_status"] = []
    return L0Document.from_dict(row)


def _lonely_document() -> L0Document:
    """The tag exists, the tagged element is NOT among those read."""
    row = copy.deepcopy(project1_metadata())
    row["change_stamp"] = "tag-wave"
    row["elements"] = [make_element("OST_WallTags", int(TAG_ID))]
    row["category_status"] = []
    return L0Document.from_dict(row)


def _index(**overrides) -> TagExtraction:
    record = TagRecord(
        element_id=overrides.get("element_id", TAG_ID),
        owner_view_id=overrides.get("owner_view_id", VIEW_ID),
        owner_view_name=overrides.get("owner_view_name", VIEW_NAME),
        at_view_mm=overrides.get("at_view_mm", (3048.0, -762.0)),
        tagged_element_id=overrides.get("tagged_element_id", WALL_ID),
        tag_family=overrides.get("tag_family", "independent"),
        leader=overrides.get("leader", False),
        orientation=overrides.get("orientation", "Horizontal"),
        type_id=overrides.get("type_id", "77"),
        type_name=overrides.get("type_name", "Марка стены"),
    )
    return TagExtraction(tags=(record,))


def _node(result, element_id: str):
    for node in result.nodes:
        if node is not None and node.get("source_element_id") == element_id:
            return node
    raise AssertionError(f"нет узла для {element_id}")


class LiftWithIndexTests(unittest.TestCase):

    def test_a_tag_becomes_create_tag(self) -> None:
        result = lift_document_detailed(_document(), tag_index=_index())
        node = _node(result, TAG_ID)
        self.assertEqual(node["kind"], "op", node.get("reason"))
        self.assertEqual(node["op_name"], "create_tag")

    def test_the_view_travels_in_the_only_named_dialect_l1_has(self) -> None:
        node = _node(lift_document_detailed(_document(), tag_index=_index()),
                     TAG_ID)
        self.assertEqual(node["params"]["in_view"],
                         {"by": "name", "value": VIEW_NAME, "_id": VIEW_ID})

    def test_the_target_points_at_the_lifted_element_not_at_a_raw_id(self) -> None:
        """The reference is intra-program: reassembly must connect two
        NODES."""
        result = lift_document_detailed(_document(), tag_index=_index())
        wall = _node(result, WALL_ID)
        tag = _node(result, TAG_ID)
        self.assertEqual(tag["params"]["target"], {"ref": wall["_id"]})

    def test_the_point_stays_two_dimensional(self) -> None:
        node = _node(lift_document_detailed(_document(), tag_index=_index()),
                     TAG_ID)
        self.assertEqual(node["params"]["at"], [3048.0, -762.0])

    def test_a_leaderless_tag_carries_no_leader_key_at_all(self) -> None:
        """The absence of a leader is the ABSENCE of the key: that is how
        the emitter reads it.

        The ``leader`` key never appears in the lifted params at all: a
        tag with a leader never reaches this point (see
        ``test_a_leadered_tag_refuses_because_at_stops_meaning_the_head``),
        and for a tag without a leader ``leader`` being absent is exactly
        what it means.
        """
        node = _node(lift_document_detailed(_document(), tag_index=_index()),
                     TAG_ID)
        self.assertNotIn("leader", node["params"])

    def test_tag_type_is_carried_when_named_and_omitted_when_not(self) -> None:
        node = _node(lift_document_detailed(_document(), tag_index=_index()),
                     TAG_ID)
        self.assertEqual(node["params"]["tag_type"],
                         {"by": "name", "value": "Марка стены", "_id": "77"})
        bare = _node(
            lift_document_detailed(_document(), tag_index=_index(type_id=None)),
            TAG_ID)
        self.assertNotIn("tag_type", bare["params"])

    def test_a_persisted_envelope_works_as_well_as_the_object(self) -> None:
        from_disk = lift_document_detailed(
            _document(), tag_index=_index().to_dict())
        in_memory = lift_document_detailed(_document(), tag_index=_index())
        self.assertEqual(_node(from_disk, TAG_ID), _node(in_memory, TAG_ID))

    def test_a_tag_on_a_door_still_resolves_though_doors_lift_in_pass_two(self) -> None:
        """Pass order: the door lifts SECOND, the tag must lift AFTER
        it.

        Without this, a tag on a door would give ``missing_reference``
        not because the door does not exist but because the lift had not
        reached it yet — a refusal that depends on the lift's internal
        order, not on the model.
        """
        row = copy.deepcopy(project1_metadata())
        row["change_stamp"] = "tag-wave"
        wall = make_element("OST_Walls", 512)
        door = make_element("OST_Doors", 600)
        door["host_id"] = "512"
        tag = make_element("OST_DoorTags", int(TAG_ID))
        # The tag stands FIRST in the document — the most inconvenient
        # order.
        row["elements"] = [tag, door, wall]
        row["category_status"] = []
        document = L0Document.from_dict(row)
        result = lift_document_detailed(
            document, tag_index=_index(tagged_element_id="600"))
        door_node = _node(result, "600")
        self.assertEqual(_node(result, TAG_ID)["params"]["target"],
                         {"ref": door_node["_id"]})


class RefusalsAreNamedNotAvoided(unittest.TestCase):

    def _atom(self, document=None, **kwargs) -> tuple[str, str]:
        result = lift_document_detailed(document or _document(), **kwargs)
        node = _node(result, TAG_ID)
        self.assertEqual(node["kind"], "op" if False else "atom",
                         node.get("op_name"))
        detail = next(
            item.detail for item in result.diagnostics
            if item.source_element_id == TAG_ID)
        reason = node["reason"]
        code = reason["code"] if isinstance(reason, dict) else reason
        return code, detail

    def test_without_the_index_the_old_refusal_is_reproduced_verbatim(self) -> None:
        code, detail = self._atom()
        self.assertEqual(code, AtomReason.SOURCE_CONTRACT_GAP.value)
        self.assertIn("create_tag", detail)
        self.assertIn("in_view", detail)
        self.assertIn("target", detail)
        self.assertIn("at", detail)

    def test_an_index_without_this_element_refuses_the_same_way(self) -> None:
        code, detail = self._atom(tag_index=_index(element_id="999"))
        self.assertEqual(code, AtomReason.SOURCE_CONTRACT_GAP.value)
        self.assertIn("create_tag", detail)

    def test_an_unreadable_target_is_a_named_refusal_not_a_guessed_binding(self) -> None:
        """The MAIN refusal of the wave: a similar element is not the
        same element."""
        code, detail = self._atom(
            document=_lonely_document(), tag_index=_index())
        self.assertEqual(code, AtomReason.MISSING_REFERENCE.value)
        self.assertIn(WALL_ID, detail)

    def test_an_unknown_tag_family_is_refused_rather_than_assumed(self) -> None:
        """A kind outside the closed vocabulary is a refusal, not
        "probably independent."

        BEFORE, a refusal for the `spatial` KIND used to stand here ("the
        forward path builds a tag only one way"). It was removed on
        13.08.2026, because the forward path learned:
        `authoring._emit_tag` tells the target apart in C# and builds
        `NewRoomTag`/`NewSpaceTag`/`NewAreaTag`. The refusal was honest
        and named the route — it was waited out, not made obsolete.

        The check was NOT DELETED, it was moved onto the boundary that
        remained: the vocabulary of kinds is CLOSED, and an unfamiliar
        value must scream. Deleting it would mean giving away for free
        what the test was guarding — a silent turning of the unknown
        into the known.
        """
        code, detail = self._atom(
            document=_document("OST_RoomTags"),
            tag_index=_index(tag_family="совершенно новый род"))
        self.assertEqual(code, AtomReason.UNSUPPORTED_SIGNATURE.value)
        self.assertIn("род марки", detail)

    def test_a_room_tag_now_lifts_to_an_op(self) -> None:
        """7 067 elements of `len_ar_me_r24_v1` — the price of the
        removed refusal.

        Measurement of 13.08.2026 on a second residential building, read
        in full: tags of the `spatial` kind were the largest reason for
        `unsupported_forward_signature`. It is pinned down here that they
        get lifted rather than remaining an atom.
        """
        result = lift_document_detailed(
            _document("OST_RoomTags"), tag_index=_index(tag_family="spatial"))
        node = _node(result, TAG_ID)
        self.assertEqual(node["kind"], "op")
        self.assertEqual(node["op_name"], "create_tag")

    def test_a_spatial_tag_with_a_leader_is_still_refused(self) -> None:
        """Removing one refusal does not remove its neighbor.

        The point of a tag WITH A LEADER means the leader's endpoint, and
        what is read is the head. That holds for BOTH kinds, and the
        forward emitter refuses a leader on a spatial tag too — both
        ends must break in the same place.
        """
        code, detail = self._atom(
            document=_document("OST_RoomTags"),
            tag_index=_index(tag_family="spatial", leader=True))
        self.assertEqual(code, AtomReason.UNSUPPORTED_SIGNATURE.value)
        self.assertIn("выноск", detail)

    def test_a_leadered_tag_refuses_because_at_stops_meaning_the_head(self) -> None:
        """Autodesk's verbatim wording about Create's seventh argument.

        "For tags with leaders, this point is the end point of the leader,
        and a leader of default length will be created from this point to
        the tag head" — identical in 2021 and in 2026, in both overloads.
        The stage reads the HEAD, meaning that for a tag with a leader the
        loop does not close, and the shift would be invisible to a
        head-position comparison.
        """
        code, detail = self._atom(tag_index=_index(leader=True))
        self.assertEqual(code, AtomReason.UNSUPPORTED_SIGNATURE.value)
        self.assertIn("выноск", detail)
        self.assertIn("TagHeadPosition", detail)

    def test_a_rotated_tag_refuses_instead_of_being_straightened_silently(self) -> None:
        code, detail = self._atom(tag_index=_index(orientation="Vertical"))
        self.assertEqual(code, AtomReason.UNSUPPORTED_SIGNATURE.value)
        self.assertIn("Vertical", detail)

    def test_a_corrupt_index_degrades_to_the_refusal_not_to_half_a_lift(self) -> None:
        code, _ = self._atom(
            tag_index={"schema_version": "чужая/1", "tag_index": {}})
        self.assertEqual(code, AtomReason.SOURCE_CONTRACT_GAP.value)

    def test_a_row_without_a_view_name_refuses(self) -> None:
        """The L1 reference dialect is named: a view without a name is
        inexpressible."""
        broken = _index().to_dict()
        broken["tag_index"][TAG_ID]["owner_view_name"] = ""
        code, _ = self._atom(tag_index=broken)
        self.assertEqual(code, AtomReason.SOURCE_CONTRACT_GAP.value)


class TheRefusalIsNotQuietlySubstituted(unittest.TestCase):
    """A tag's shape refusal has no right to become ``place_family``.

    ``unsupported_forward_signature`` is part of ``_SHAPE_REFUSALS``,
    meaning by default it says "let it try a family placement." For a
    tag that would be a fabricated source: neither IndependentTag nor
    SpatialElementTag is a FamilyInstance. The test slips a row keyed ON
    THE TAG'S ID into the side placement index — a state unreachable
    today — and requires that the refusal stay the same.
    """

    def _placement_index(self) -> dict:
        return {
            TAG_ID: {
                "placement_type": "OneLevelBased",
                "placement_available": True,
                "point_mm": [1500.0, 2500.0, 3000.0],
                "family_name": "Семейство",
                "host_id": None,
                "host_class": None,
                "group_id": None,
                "in_place": False,
                "mirrored": False,
                "hand_flipped": False,
                "facing_flipped": False,
                "hand_orientation": [0.0, 1.0, 0.0],
                "facing_orientation": [-1.0, 0.0, 0.0],
                "rotation_deg": 0.0,
                "super_component_id": None,
                "symbol_id": "9002",
                "type_name": "Тип экземпляра",
            }
        }

    def test_a_spatial_tag_stays_an_atom_even_with_a_placement_row(self) -> None:
        result = lift_document_detailed(
            _document("OST_RoomTags"),
            family_placement_index=self._placement_index(),
            # THE GROUND FOR THE REFUSAL CHANGED ON 13.08: the `spatial`
            # kind stopped being a refusal (the forward path learned it),
            # while the test's purpose — "a tag's refusal has no right
            # to become place_family" — stayed. We take the refusal that
            # is still alive: the leader.
            tag_index=_index(leader=True))
        node = _node(result, TAG_ID)
        self.assertEqual(node["kind"], "atom", node.get("op_name"))
        self.assertEqual(node["reason"]["code"],
                         AtomReason.UNSUPPORTED_SIGNATURE.value)

    def test_a_rotated_tag_stays_an_atom_even_with_a_placement_row(self) -> None:
        result = lift_document_detailed(
            _document(),
            family_placement_index=self._placement_index(),
            tag_index=_index(orientation="Vertical"))
        node = _node(result, TAG_ID)
        self.assertEqual(node["kind"], "atom", node.get("op_name"))
        self.assertEqual(node["reason"]["code"],
                         AtomReason.UNSUPPORTED_SIGNATURE.value)


class CacheKeyTests(unittest.TestCase):
    """A key without an input means the cache is lying: the same class
    of defect has already cost three waves."""

    def test_the_tag_index_changes_the_cache_key(self) -> None:
        document = _document()
        without = lift_cache_key(document)
        with_index = lift_cache_key(document, tag_index=_index())
        other = lift_cache_key(document, tag_index=_index(leader=True))
        self.assertNotEqual(without, with_index)
        self.assertNotEqual(with_index, other)

    def test_the_same_index_gives_the_same_key(self) -> None:
        document = _document()
        self.assertEqual(lift_cache_key(document, tag_index=_index()),
                         lift_cache_key(document, tag_index=_index()))


if __name__ == "__main__":
    unittest.main()
