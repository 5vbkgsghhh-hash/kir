"""Working documentation: what became expressible, and what honestly
refused (29.07).

REASON. The reading table grew 54 → 73 categories (ee32fb82), and it
took in the content of the measured tower's RD: 13 905 dimensions,
11 585 room tags, 2 697 notes, 3 046 node elements, 4 479 phone
devices, and more — 60 587 elements. That wave was about READING and
honestly said it would not move coverage: there are no lifters,
everything becomes atoms. This wave examined what of it could be
lifted, and the answer turned out to be NOT what was expected.

THE MAIN FORK DECIDED HERE. A dimension, a tag, and a note reference
OTHER elements and live on a SPECIFIC VIEW. Operations for them have
been in the registry since 28.07 (ops_annotation.py), but their
required inputs — `in_view`, `refs`, `target`, `at`/`line_at`,
`content` — are absent AS FIELDS from the frozen L0 1.0 row. So the
lifter here is not "unwritten," it CANNOT be written from this
reading: any such lifter would have had to INVENT a source — attach the
dimension to some element and drop the tag roughly there. That would
pass the L1 schema and look like coverage. Law §18.1 forbids exactly
this, and the price of the substitution is not a percentage but trust
in the number.

Hence this wave's work is not a lifter but the CORRECT NAME FOR THE
REFUSAL. Before it, all these elements received `no_lifter` ("category
is outside the exact Part 5 lifter table"), which in the reasons
ranking reads as "there is no operation, write one" — and the next
person would go write create_dimension, which is already written. The
new code `source_contract_gap` points to READING and names by name
what to start capturing. This is exactly the same distinction already
drawn on 29.07 for the placement stage ("a stage's silence is not a
fact about the element").

WHAT ACTUALLY GETS LIFTED. Phone devices are model families, and once
the lead added them to the side placement index's whitelist (same
commit), they get lifted by `place_family` WITHOUT A SINGLE LIFTER
CHANGE. The test below locks this in: the path exists and must not
break silently.

WHAT REFUSED, AND WHY THE DIAGNOSIS HAD TO BE FIXED. Node elements were
refusing with the text «place_family ставит только точечные
размещения, а у этого экземпляра 'ViewBased'». That is a wrong
diagnosis: ViewBased IS A POINT, and Autodesk writes verbatim, "The
family is view-specific (e.g. a detail annotation)." The node element
does have a point, and it sits in the side index; what is missing is
the VIEW, which place_family does not have among its parameters at
all. The old text sent people to look for different geometry — that
is, in a direction where there is nothing.
"""
import unittest
from dataclasses import fields

from kir import spec
from kir.decompile.family_placement_extract import (
    FAMILY_PLACEMENT_INDEX_SCHEMA_VERSION,
)
from kir.decompile.l1_schema import AtomReason, FidelityReason
from kir.decompile.lift import (
    _L0_ALREADY_CARRIES,
    _L0_HAS_NO_SOURCE_FOR,
    _OPS_WHOSE_REFUSAL_IS_BUILT,
    _OPS_WITHOUT_L0_INPUTS,
    LIFTER_TABLE,
    lift_document,
)
from kir.decompile.schema import (
    GeometryKind,
    L0Document,
    L0Element,
    LevelInfo,
    ProjectInfo,
)


def _annotation(eid, category, type_name="Тип аннотации"):
    """An annotation row exactly as emission returns it.

    Without a level (an annotation has none), without a host (it is not
    a FamilyInstance), with a bounding box instead of a point, and with
    EMPTY params: `__PutParams` is a closed whitelist of geometric
    BuiltInParameter, and it contains no text, no view, and no
    references.
    """

    return L0Element(
        element_id=eid, category=category, category_ru="",
        type_id="9001", type_name=type_name,
        level_id=None, level_name=None,
        geom_kind=GeometryKind.BBOX_ONLY,
        p0_mm=None, p1_mm=None, rotation_deg=None,
        bbox_min_mm=(0.0, 0.0, 0.0), bbox_max_mm=(100.0, 100.0, 0.0),
        host_id=None, params={})


def _instance(eid, category, level=True):
    return L0Element(
        element_id=eid, category=category, category_ru="",
        type_id="9002", type_name="Тип экземпляра",
        level_id="10" if level else None,
        level_name="L1" if level else None,
        geom_kind=GeometryKind.POINT,
        p0_mm=(1500.0, 2500.0, 3000.0), p1_mm=None, rotation_deg=0.0,
        bbox_min_mm=None, bbox_max_mm=None, host_id=None, params={})


def _row(placement_type, **over):
    row = {
        "placement_type": placement_type,
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
    row.update(over)
    return row


def _doc(*elements):
    return L0Document(
        doc_name="rd", revit_version="2023", units="mm", change_stamp="t",
        levels=(LevelInfo("10", "L1", 0.0),), grids=(), rooms=(),
        project_info=ProjectInfo(), elements=elements)


def _nodes(document, index=None):
    envelope = None
    if index is not None:
        envelope = {
            "schema_version": FAMILY_PLACEMENT_INDEX_SCHEMA_VERSION,
            "family_placement_index": index,
            "failures": [],
        }
    return {node["source_element_id"]: node
            for node in lift_document(document, None, envelope)}


class TheRefusalsPremiseIsChecked(unittest.TestCase):
    """The refusal asserts two things. Both must be checked, not merely
    claimed."""

    def test_every_named_op_really_is_in_the_registry(self):
        """The first half: "the op EXISTS." If it does not, the text
        lies."""

        for category, op_name in sorted(_OPS_WITHOUT_L0_INPUTS.items()):
            with self.subTest(category=category):
                self.assertIn(
                    op_name, spec.OPS,
                    f"{category} обещает оп {op_name!r}, которого нет в "
                    "реестре: отказ рассказывал бы про входы несуществующей "
                    "операции")

    def test_l0_really_carries_no_field_for_those_inputs(self):
        """The second half: "the inputs ARE NOT IN THE READING."

        This is checked STRUCTURALLY, from the fields of the frozen row,
        not from a list of strings: if the next wave starts capturing
        the owning view and adds the field, the test will fail, and the
        refusal will have to be revisited rather than left lying out of
        inertia.
        """

        field_names = {field.name for field in fields(L0Element)}
        forbidden = ("view", "text", "content", "reference", "refs")
        for token in forbidden:
            with self.subTest(token=token):
                carriers = sorted(
                    name for name in field_names if token in name.lower())
                self.assertEqual(
                    carriers, [],
                    f"в L0Element появилось поле про {token!r}: {carriers}. "
                    "Если вход опа теперь читается, отказ "
                    "source_contract_gap про него больше не верен")

    def test_every_required_input_is_named_in_the_gap_map(self):
        """The map of "what to capture" must cover the registry in
        full.

        An op may acquire a new required input. Without this check, the
        refusal would silently print "source not named" and stop being
        a specification for the next wave.

        NOT only the categories from ``_OPS_WITHOUT_L0_INPUTS`` are
        checked: the tag and the note moved out of it into the lifters
        table (they gained reading stages), but the SAME refusal text
        is assembled for them when the index is absent — so the map
        must hold their inputs too.

        ON 09.08 THE TABLE BECAME TWO TABLES, and the requirement did
        not weaken because of that, it became more precise: an input
        must stand in EXACTLY ONE of them. The flexible run is the
        first partial capture gap (`level` is present in the L0 row,
        `path` is not), and without a positive declaration "we already
        carry this input," the refusal text could silently lose a newly
        missing input: it names only what is missing.
        """

        # 04.09.2026: the traversal was switched from
        # `_OPS_WITHOUT_L0_INPUTS` to an explicit list. That table went
        # EMPTY (flexible runs and openings moved to candidates), and
        # traversing its values would have gone empty too — i.e. green,
        # without checking A SINGLE op, even though the
        # `_unsourceable_inputs_detail` instrument still assembles a
        # refusal for six operations.
        collected = set(_OPS_WHOSE_REFUSAL_IS_BUILT)
        for op_name in sorted(collected):
            for param in spec.OPS[op_name].params:
                if not param.required:
                    continue
                with self.subTest(op=op_name, param=param.name):
                    # 04.09.2026: the key became a PAIR (op, input) with
                    # a wildcard op "*". We ask exactly the way the
                    # instrument itself asks, otherwise the test would
                    # be checking a different table than the one that
                    # assembles the text.
                    missing = ((op_name, param.name) in _L0_HAS_NO_SOURCE_FOR
                               or ("*", param.name) in _L0_HAS_NO_SOURCE_FOR)
                    carried = param.name in _L0_ALREADY_CARRIES
                    self.assertTrue(
                        missing or carried,
                        f"{op_name}.{param.name} обязателен, но ни одна из "
                        "таблиц не говорит, читаем мы его или какой член API "
                        "пришлось бы начать снимать")
                    self.assertFalse(
                        missing and carried,
                        f"{op_name}.{param.name} объявлен и читаемым, и "
                        "нечитаемым сразу — отказ про него не может быть "
                        "верным ни в одну из сторон")


class OneNameTwoSourcesIsToldApart(unittest.TestCase):
    """A refuting test for the key pair (04.09.2026).

    The pair itself is GREEN TODAY WITHOUT ANY ACT OF DISTINCTION: there
    is not a single name collision in the table, and there is nothing to
    point to and say "it works." The probe DELIBERATELY sets up a
    collision and requires that each op get ITS OWN source. Without this
    probe the fix would be a promise, not a mechanism.
    """

    def test_the_exact_pair_wins_over_the_wildcard(self):
        from unittest import mock

        from kir.decompile import lift

        подмена = {
            ("*", "variety"): "ОБЩИЙ источник",
            ("create_topography", "variety"): "СВОЙ источник топографии",
        }
        with mock.patch.object(lift, "_L0_HAS_NO_SOURCE_FOR", подмена):
            self.assertEqual(
                lift._source_gap_note("create_topography", "variety"),
                "СВОЙ источник топографии",
                "точная пара обязана побеждать подстановочную, иначе отказ "
                "одного опа сослался бы на член API другого")
            self.assertEqual(
                lift._source_gap_note("create_opening", "variety"),
                "ОБЩИЙ источник",
                "оп без своей пары обязан получить подстановочную")
            self.assertEqual(
                lift._source_gap_note("create_opening", "неведомый_вход"),
                "источник не назван",
                "вход, не объявленный нигде, обязан называться прямо, а не "
                "получать чужую строку")


class AnnotationsRefuseByTheirOwnName(unittest.TestCase):
    """`no_lifter` used to point to the operations registry. The truth
    lies in reading."""

    def test_each_documentation_category_names_its_own_op(self):
        elements = tuple(
            _annotation(str(1000 + i), category)
            for i, category in enumerate(sorted(_OPS_WITHOUT_L0_INPUTS)))
        nodes = _nodes(_doc(*elements))
        for element in elements:
            op_name = _OPS_WITHOUT_L0_INPUTS[element.category]
            with self.subTest(category=element.category):
                node = nodes[element.element_id]
                self.assertEqual(node["kind"], "atom")
                self.assertEqual(
                    node["reason"]["code"], AtomReason.SOURCE_CONTRACT_GAP.value)
                self.assertIn(op_name, node["reason"]["detail"])

    def test_the_detail_names_every_missing_input(self):
        """A refusal must be a specification, not a complaint."""

        node = _nodes(_doc(_annotation("1", "OST_Dimensions")))["1"]
        detail = node["reason"]["detail"]
        for param in spec.OPS["create_dimension"].params:
            if param.required:
                with self.subTest(param=param.name):
                    self.assertIn(param.name, detail)
        self.assertIn("Dimension.References", detail)
        self.assertIn("Element.OwnerViewId", detail)

    def test_text_notes_name_the_missing_content(self):
        """A note is missing not only the view but also THE TEXT
        ITSELF.

        `type_name` carries the note's TYPE name, not its content, and
        mistaking one for the other would mean writing the style's name
        into the model instead of the label.
        """

        detail = _nodes(_doc(_annotation("1", "OST_TextNotes")))["1"]["reason"]["detail"]
        self.assertIn("TextElement.Text", detail)
        self.assertIn("content", detail)

    def test_all_ten_tag_kinds_collapse_to_one_ranking_row(self):
        """Ten kinds of tags — one op, hence one line in the reasons
        ranking.

        Otherwise the document's largest gap would look like ten small
        ones and would lose out in the ranking to something cheaper to
        fix.

        On 30.07 tags moved out of ``_OPS_WITHOUT_L0_INPUTS`` into the
        lifters table (they gained a ``tag`` reading stage), and the
        list is now taken FROM THERE. The requirement itself has not
        changed by a single letter: WITHOUT THE INDEX all ten kinds must
        refuse with one and the same text and the same code as before
        the wave — otherwise snapshots taken earlier would read under a
        different taxonomy than today's.
        """

        tags = sorted(c for c, (_kind, op) in LIFTER_TABLE.items()
                      if op == "create_tag")
        self.assertGreater(len(tags), 1)
        elements = tuple(
            _annotation(str(2000 + i), category)
            for i, category in enumerate(tags))
        nodes = _nodes(_doc(*elements))
        codes = {nodes[e.element_id]["reason"]["code"] for e in elements}
        self.assertEqual(codes, {AtomReason.SOURCE_CONTRACT_GAP.value})
        details = {nodes[e.element_id]["reason"]["detail"] for e in elements}
        self.assertEqual(
            len(details), 1,
            "марки разных родов обязаны отказывать ОДНИМ текстом")
        self.assertIn("create_tag", details.pop())

    def test_categories_that_genuinely_have_no_op_keep_no_lifter(self):
        """The table must not be allowed to grow: where there is NO op,
        `no_lifter` is the truth.

        Lines, elevation marks, slopes, and typical annotations went into
        the reading deliberately and without an op (recorded as such in
        ee32fb82). Relabeling them with the new code would mean chasing a
        prettier reason instead of the correct one.

        ON 03.08 THE LIST GOT SHORTER BY ONE LINE, and this is NOT a
        weakening of the test but its meaning in action.
        ``OST_RoomSeparationLines`` left here because the category
        ACQUIRED an op (``create_room_separator``, wave/room), and keeping
        it here would mean demanding a knowingly FALSE reason: "there is
        no op" would send the next person to write an operation that is
        already written. Exactly the same move that tags and text notes
        made on 30.07, and for exactly the same reason. Its own
        boundaries are now checked directly — ``test_lift_room_separator.py``.
        """

        opless = (
            "OST_Lines", "OST_SpotElevations", "OST_SpotSlopes",
            "OST_GenericAnnotation",
        )
        elements = tuple(
            _annotation(str(3000 + i), category)
            for i, category in enumerate(opless))
        nodes = _nodes(_doc(*elements))
        for element in elements:
            with self.subTest(category=element.category):
                self.assertEqual(
                    nodes[element.element_id]["reason"]["code"],
                    AtomReason.NO_LIFTER.value)


class TelephoneDevicesActuallyLift(unittest.TestCase):
    """The one genuine gain of the reading wave — and it already works.

    The lift was not touched: devices land in the generic placement path
    because the lead added the category to the side index's whitelist.
    The test locks in the whole path — if the list drifts from the
    reading table again, this will fail here, rather than through a
    96-minute snapshot.
    """

    def test_unhosted_device_becomes_place_family(self):
        node = _nodes(
            _doc(_instance("500", "OST_TelephoneDevices")),
            {"500": _row("OneLevelBased")})["500"]
        self.assertEqual(node["kind"], "op", node.get("reason"))
        self.assertEqual(node["op_name"], "place_family")

    def test_wall_hosted_device_keeps_its_host(self):
        wall = L0Element(
            element_id="900", category="OST_Walls", category_ru="",
            type_id="20", type_name="Стена 200",
            level_id="10", level_name="L1",
            geom_kind=GeometryKind.CURVE,
            p0_mm=(0.0, 0.0, 0.0), p1_mm=(6000.0, 0.0, 0.0),
            rotation_deg=None, bbox_min_mm=None, bbox_max_mm=None,
            host_id=None, params={})
        nodes = _nodes(
            _doc(wall, _instance("500", "OST_TelephoneDevices")),
            {"500": _row("OneLevelBasedHosted", host_id="900",
                         host_class="Wall")})
        self.assertEqual(nodes["500"]["op_name"], "place_family")
        self.assertEqual(
            nodes["500"]["params"]["host"], {"ref": nodes["900"]["_id"]})


class DetailComponentsRefuseForTheRightReason(unittest.TestCase):
    """The refusal was correct by code and FALSE by diagnosis."""

    def _detail(self, placement_type):
        node = _nodes(
            _doc(_instance("600", "OST_DetailComponents", level=False)),
            {"600": _row(placement_type)})["600"]
        self.assertEqual(node["kind"], "atom")
        self.assertEqual(
            node["reason"]["code"], AtomReason.UNSUPPORTED_SIGNATURE.value)
        return node["reason"]["detail"]

    def test_view_specific_placement_blames_the_missing_view(self):
        for placement_type in ("ViewBased", "CurveBasedDetail"):
            with self.subTest(placement_type=placement_type):
                detail = self._detail(placement_type)
                self.assertIn("вида", detail)

    def test_view_specific_placement_no_longer_claims_it_is_not_a_point(self):
        """Autodesk: ViewBased = "The family is view-specific".

        The node element DOES have a point. The old text claimed the
        opposite and sent the next person looking for a curve or adaptive
        points — into a direction where there is nothing.
        """

        detail = self._detail("ViewBased")
        self.assertNotIn("только точечные размещения", detail)

    def test_placements_that_really_are_not_points_keep_the_old_reason(self):
        """The gate narrowed, it was not swapped out: a curve is still
        not a point."""

        detail = self._detail("CurveDrivenStructural")
        self.assertIn("только точечные размещения", detail)


class TheHonestyContractStaysLossless(unittest.TestCase):
    """A safeguard that did not exist: the new code must make it all the
    way to the manifest.

    `FidelityReason` documents that EVERY `AtomReason` has a like-named
    value — otherwise a typed refusal gets lost on the way into VERIFY.
    Before 29.07 this rested on attentiveness alone: not a single
    correspondence test existed, and adding a code to one enum while
    forgetting the other would have broken nothing on the spot.
    """

    def test_every_atom_reason_has_an_identical_fidelity_reason(self):
        fidelity_values = {reason.value for reason in FidelityReason}
        for reason in AtomReason:
            with self.subTest(reason=reason.name):
                self.assertIn(
                    reason.value, fidelity_values,
                    f"AtomReason.{reason.name} не доедет до паспорта: в "
                    "FidelityReason нет одноимённого значения")


if __name__ == "__main__":
    unittest.main()
