"""A FIELD THAT DID NOT REACH L1 MUST BE NAMED WITH AN ADDRESS AND A REASON.

🔴 WHY THIS WAS OPENED (07.09.2026).

A recon measurement across all 1455 elements of `sob62_r23_v3`: non-empty
L0 fields **20 482**, did not reach L1 **11 625 (56.8%)**, with OPS losing
more than atoms (60.3% versus 46.3%). This refutes the convenient framing
"losses are a property of the fallback atom": enriching the atom would
cure 46%, not 57%.

🔴 AND THE MAIN POINT — WHAT THIS FILE GUARDS. "lift → fold → expand gave
an equal L1" IS NOT proof of preservation. Measured on `bench_A`, door
286533: of its 17 non-empty fields, **five** (`host_source`, `level_id`,
`phase_created`, `rotation_deg`, `unique_id`) can be stripped from L0 such
that L1 remains BYTE FOR BYTE the same — including `unique_id`, that is,
the very address by which the acceptance itself names this door. The
ledger changes as a result: 17 → 16 non-empty, 11 → 10 lost, the overall
count 28 279 → 28 278.

🔴 THE PROPOSED CONTROL BENCHMARK DID NOT REPRODUCE, AND THIS IS A
MEASUREMENT, NOT NITPICKING. The control was proposed as "strip `workset`
from door 286533". For this door in `bench_A`, `workset` is **EMPTY**:
there is nothing to strip, and a control built on it would be green by
construction. The field was chosen BY EXECUTION — by enumerating every
non-empty field.
"""
from __future__ import annotations

import dataclasses
import json
import os
import pathlib
import unittest

from kir.decompile.field_ledger import (FIELD_LEDGER_SCHEMA, RECOVERABLE_FROM, WHY,
                                        ElementFields, FieldLedger, FieldLedgerError,
                                        LostField, field_ledger)


class _Element:
    """The minimal L0 element: the ledger reads fields via `dataclasses.fields`."""


@dataclasses.dataclass(frozen=True)
class FakeElement:
    element_id: str
    category: str
    category_ru: str
    type_id: str
    type_name: str
    level_id: str | None
    level_name: str | None
    workset: str | None = None
    host_id: str | None = None
    unique_id: str | None = None


@dataclasses.dataclass(frozen=True)
class FakeDocument:
    elements: tuple


def op_node(element, **over):
    node = {"kind": "op", "op_name": "create_wall", "_id": "n-" + element.element_id,
            "source_element_id": element.element_id, "type_name": element.type_name,
            "level_name": element.level_name}
    node.update(over)
    return node


def atom_node(element, **over):
    node = {"kind": "atom", "_id": "a-" + element.element_id,
            "source_element_id": element.element_id, "category": element.category,
            "category_ru": element.category_ru, "type_name": element.type_name,
            "level_name": element.level_name,
            "reason": {"code": "no_lifter", "detail": ""}}
    node.update(over)
    return node


WALL = FakeElement(element_id="1", category="OST_Walls", category_ru="Стены",
                   type_id="t1", type_name="Базовая стена", level_id="L1",
                   level_name="Этаж 1", workset="Раб.набор 1", host_id=None,
                   unique_id="u-1")
FLOOR = FakeElement(element_id="2", category="OST_Floors", category_ru="Перекрытия",
                    type_id="t2", type_name="Плита", level_id="L1",
                    level_name="Этаж 1", workset="Раб.набор 1", unique_id="u-2")


class TheLedgerNamesEveryLossWithAnAddress(unittest.TestCase):

    def setUp(self) -> None:
        self.document = FakeDocument(elements=(WALL, FLOOR))
        self.ledger = field_ledger(self.document, [op_node(WALL), atom_node(FLOOR)])

    def test_every_row_carries_a_non_empty_address(self) -> None:
        """A line with no address is useless: there is nothing in the model to match it against."""
        self.assertEqual(len(self.ledger.rows), 2)
        for row in self.ledger.rows:
            with self.subTest(row=row.element_id):
                self.assertTrue(row.address["element_id"])
                self.assertTrue(row.address["unique_id"])

    def test_the_reasons_sum_to_the_losses_and_nothing_is_unclassified(self) -> None:
        """🔴 THE SUM OF THE KINDS = THE LOSS COUNT, and `unclassified` is
        always printed.

        A classifier that drops what fits no branch reports by kind and
        lies more plausibly than silence would.
        """
        totals = self.ledger.totals
        self.assertEqual(sum(totals["by_why"].values()), totals["lost"])
        self.assertEqual(totals["unclassified"], 0)
        self.assertEqual(sorted(totals["by_why"]), sorted(WHY))

    def test_an_empty_field_is_neither_kept_nor_lost(self) -> None:
        """"Was never there" and "was lost" are different facts."""
        row = next(r for r in self.ledger.rows if r.element_id == "1")
        self.assertNotIn("host_id", row.kept)
        self.assertNotIn("host_id", [item.field for item in row.lost])

    def test_an_atom_loses_by_the_reason_atom(self) -> None:
        row = next(r for r in self.ledger.rows if r.element_id == "2")
        self.assertEqual(row.node_kind, "atom")
        self.assertIn("atom", {item.why for item in row.lost})

    def test_an_op_loses_by_the_reason_of_the_language(self) -> None:
        row = next(r for r in self.ledger.rows if r.element_id == "1")
        self.assertEqual(row.node_kind, "op")
        self.assertIn("op_language", {item.why for item in row.lost})

    def test_the_derived_reason_requires_its_partner_to_have_arrived(self) -> None:
        """"A name instead of an id" saves the fact ONLY when a name actually exists."""
        row = next(r for r in self.ledger.rows if r.element_id == "1")
        level = next(item for item in row.lost if item.field == "level_id")
        self.assertEqual(level.why, "derived")
        self.assertEqual(level.recovered_from, "level_name")
        # The same element with no level name in the node: there is nothing to save it with, and the reason is different.
        blind = field_ledger(FakeDocument(elements=(WALL,)),
                             [op_node(WALL, level_name=None, type_name="иное")])
        item = next(x for x in blind.rows[0].lost if x.field == "level_id")
        self.assertNotEqual(item.why, "derived")
        self.assertIsNone(item.recovered_from)

    def test_the_op_contract_is_measured_not_guessed(self) -> None:
        """Telling "the language has no way to say it" apart from "it can, but it did not arrive" — by a number."""
        row = next(r for r in self.ledger.rows if r.element_id == "1")
        values = {item.in_op_contract for item in row.lost}
        self.assertTrue(values <= {True, False, None})
        self.assertIn("lost_though_the_op_contract_has_the_word", self.ledger.totals)

    def test_an_element_without_a_node_is_counted_not_dropped(self) -> None:
        """A gap in the DENOMINATOR makes the loss share smaller — and does it silently."""
        ledger = field_ledger(self.document, [op_node(WALL)])
        self.assertEqual(ledger.totals["elements"], 2)
        self.assertEqual(ledger.totals["elements_with_node"], 1)
        self.assertEqual(ledger.totals["elements_without_node"], 1)

    def test_an_empty_l0_is_refused_not_reported_as_no_losses(self) -> None:
        """An empty ledger is green BY CONSTRUCTION — meaning it is not a ledger."""
        with self.assertRaises(FieldLedgerError):
            field_ledger(FakeDocument(elements=()), [])

    def test_a_ledger_whose_kinds_do_not_sum_is_refused(self) -> None:
        totals = dict(self.ledger.totals)
        totals["lost"] = totals["lost"] + 1
        with self.assertRaises(FieldLedgerError):
            FieldLedger(rows=self.ledger.rows, totals=totals)
        totals = dict(self.ledger.totals)
        totals["unclassified"] = 1
        totals["lost"] = totals["lost"] + 1
        with self.assertRaises(FieldLedgerError):
            FieldLedger(rows=self.ledger.rows, totals=totals)

    def test_a_reason_outside_the_closed_list_is_refused(self) -> None:
        with self.assertRaises(FieldLedgerError):
            LostField(field="x", why="whatever")
        with self.assertRaises(FieldLedgerError):
            LostField(field="x", why="derived")          # the partner is not named
        with self.assertRaises(FieldLedgerError):
            LostField(field="x", why="atom", recovered_from="y")

    def test_the_report_is_json_ready_and_schema_stamped(self) -> None:
        data = self.ledger.to_dict()
        self.assertEqual(data["schema"], FIELD_LEDGER_SCHEMA)
        json.dumps(data, ensure_ascii=False)


class TheSkipCarriesItsAddressAsAField(unittest.TestCase):
    """The address of a materialization gap is a field, not a piece of a string."""

    def test_the_address_is_parsed_and_the_reason_bytes_are_untouched(self) -> None:
        from kir.decompile.materialize import SkipRecord

        record = SkipRecord(source_id="13590394", category="create_door",
                            reason="host_unmaterialized:32ab509a2a0f")
        self.assertEqual(record.reason_code, "host_unmaterialized")
        self.assertEqual(record.unresolved_id, "32ab509a2a0f")
        self.assertEqual(record.as_dict()["reason"], record.reason,
                         "формат причины обязан остаться байт в байт")

    def test_a_reason_without_an_address_says_none_not_empty(self) -> None:
        """Empty would read as "the address existed and got lost"."""
        from kir.decompile.materialize import SkipRecord

        for reason in ("atom", "atom_escrow:mesh_refused", "datum_pinned_existing"):
            with self.subTest(reason=reason):
                record = SkipRecord(source_id="1", category="c", reason=reason)
                self.assertIsNone(record.unresolved_id)

    def test_there_is_no_second_carrier_of_the_address(self) -> None:
        """The field is COMPUTED from the reason: it cannot drift apart from it."""
        from kir.decompile.materialize import SkipRecord

        self.assertNotIn("unresolved_id", {f.name for f in dataclasses.fields(SkipRecord)})


class TheUnresolvedDependencyNamesItsKind(unittest.TestCase):

    def test_a_typed_kind_travels_into_the_report(self) -> None:
        from kir.decompile.dependencies import DependencyKind, UnresolvedDependency
        from kir.decompile.l1_schema import FidelityReason

        row = UnresolvedDependency(key="k", reason=FidelityReason.DEPENDENCY_UNRESOLVED,
                                   detail="d", affected_source_ids=(),
                                   kind=DependencyKind.ELEMENT_TYPE)
        self.assertEqual(row.to_dict()["kind"], "element_type")

    def test_none_is_a_named_state_not_a_hole(self) -> None:
        """A document-environment line describes no definition — it has no kind."""
        from kir.decompile.dependencies import UnresolvedDependency
        from kir.decompile.l1_schema import FidelityReason

        row = UnresolvedDependency(key="source_environment:l0_1_0",
                                   reason=FidelityReason.DEPENDENCY_UNRESOLVED,
                                   detail="d", affected_source_ids=())
        self.assertIsNone(row.kind)
        self.assertIn("kind", row.to_dict())

    def test_an_untyped_kind_is_refused(self) -> None:
        from kir.decompile.dependencies import DependencyManifestError, UnresolvedDependency
        from kir.decompile.l1_schema import FidelityReason

        with self.assertRaises(DependencyManifestError):
            UnresolvedDependency(key="k", reason=FidelityReason.DEPENDENCY_UNRESOLVED,
                                 detail="d", affected_source_ids=(), kind="element_type")


CORPUS = pathlib.Path(os.environ.get(
    "KIR_DECOMPILE_CORPUS",
    "/opt/kukai-rebuild1/backend/backend/data/decompile"))


def _read(run: str):
    from kir.decompile.extract import L0JSONLReader

    return L0JSONLReader(CORPUS / run / "L0.jsonl").materialize()


def _lift(run: str, document):
    """🔴 SIDE INDEXES ARE MANDATORY, AND THIS WAS BOUGHT WITH A RED.

    The first edition called `lift_document_detailed(document)` with no
    indexes, and the numbers diverged from the recon measurement: 11 643
    versus 11 625, and for operations, 14 719 non-empty versus 15 304.
    Without the indexes, part of the elements never become operations at
    all — meaning a DIFFERENT subject was measured while looking green.
    """
    import gzip

    from kir.decompile.lift import lift_document_detailed

    def index(name):
        # 🔴 AN UNCOMPRESSED INDEX IS STILL AN INDEX, AND THIS WAS BOUGHT
        # WITH A RED (07.09.2026). Only `*.index.json.gz` was asked for;
        # `bench_A`'s side indexes sit UNCOMPRESSED, and the lift ran
        # without them — meaning a DIFFERENT subject was measured while
        # looking green. The same defect was already caught in reviewer
        # B4's probe (`MISSION_4_RU.md`); here it lived in the suite
        # itself.
        packed = CORPUS / run / f"{name}.index.json.gz"
        if packed.is_file():
            with gzip.open(packed, "rt", encoding="utf-8") as handle:
                return json.load(handle)
        flat = CORPUS / run / f"{name}.index.json"
        if flat.is_file():
            return json.loads(flat.read_text(encoding="utf-8"))
        return None

    return lift_document_detailed(document,
                                  family_placement_index=index("family_placement"),
                                  wall_curve_index=index("curve"),
                                  curtain_index=index("curtain"))


def _corpus(run: str):
    """A snapshot's existence is asked FROM THE HELPER, not from the
    filesystem.

    🔴 THIS IS A RED THAT I MYSELF BROUGHT, AND IT WAS CAUGHT BY SOMEONE
    ELSE'S GUARD. The first edition called `path.is_file()` on the RAW
    name `L0.jsonl` — the very thing `test_snapshot_existence_is_asked` has
    forbidden since 20.08.2026: on a COMPRESSED decompile (`L0.jsonl.gz`)
    the bare verb answers "no", and skipping would look like "there is no
    corpus" rather than "we do not know how to see it". Silence here is
    worse than a refusal: the suite would have gone green without taking
    the measurement.
    """
    from kir.model.snapshot_io import snapshot_file_exists

    path = CORPUS / run / "L0.jsonl"
    return path if snapshot_file_exists(path) else None


#: The profile reading mode THE CORPUS'S PINS STAND ON. This is not an
#: instrument setting, it is a declaration of the subject: the ledger's
#: numbers CHANGE with the mode, and a pin taken in one and checked in
#: another lies more plausibly than silence would.
PINNED_PROFILES = "editable"


def _public_capture(run: str):
    """A capture opened through the SAME door and with the SAME default
    that people use.

    🔴 ADDED AFTER THE 07.09.2026 FINDING, AND THIS WAS A PIN ON SOMEONE
    ELSE'S SUBJECT. Before, the numbers were taken from
    `lift_document_detailed` DIRECTLY, with all the side indexes and no
    profile filter, that is, in `none` mode. Through the public door
    (`open_capture`, default `editable`), the same building gives DIFFERENT
    numbers, and the pin stood on a mode the public does not read with:

        bench_A represented:  none 26 330 · editable 26 282 · all 26 272

    `profiles` is deliberately NOT passed here: the door's default is
    taken, and the guard below checks it against `PINNED_PROFILES`. Had we
    passed the mode explicitly, the default could have drifted away while
    the pin stayed green on the old number.
    """
    from kir.decompile.capture_edit import open_capture

    return open_capture(CORPUS / run)


@unittest.skipUnless(_corpus("bench_A"), "корпуса нет — замер не состоялся")
class ThePinAndThePublicDoorReadTheSameBuilding(unittest.TestCase):
    """🔴 THE DESYNC GUARD: a pin and the public door must read THE SAME
    THING.

    The corpus numbers below are a property of the READING MODE, not just
    of the building. As long as the door's default and the pin's mode
    match, the pin speaks about what the user sees. Let them drift apart
    silently, and the whole file becomes a green report about a different
    subject; that is why equality is checked BY A NUMBER, not by memory.
    """

    def test_the_default_of_the_public_door_is_the_pinned_mode(self) -> None:
        from kir.decompile.capture_edit import open_capture

        self.assertEqual((open_capture.__kwdefaults__ or {}).get("profiles"),
                         PINNED_PROFILES,
                         "умолчание open_capture уехало от режима, на котором "
                         "стоят пины корпуса: перемерь и перепини")
        self.assertEqual(_public_capture("bench_A").profiles, PINNED_PROFILES)

    def test_the_three_modes_really_differ(self) -> None:
        """Control: if the modes never diverged, the guard would be guarding an emptiness."""
        from kir.decompile.capture_edit import open_capture

        seen = {}
        for mode in ("none", "editable", "all"):
            capture = open_capture(CORPUS / "bench_A", profiles=mode)
            seen[mode] = field_ledger(
                capture.document, capture.nodes).totals["by_state"]["represented"]
        self.assertEqual(seen, {"none": 26_330, "editable": 26_282, "all": 26_272})
        self.assertEqual(seen[PINNED_PROFILES], 26_282)


@unittest.skipUnless(_corpus("sob62_r23_v3"), "корпуса нет — замер не состоялся")
class TheLedgerReproducesTheMeasuredCorpusNumbers(unittest.TestCase):
    """The corpus is ONLY READ. The numbers are taken from recon and must add up."""

    @classmethod
    def setUpClass(cls) -> None:
        capture = _public_capture("sob62_r23_v3")
        cls.ledger = field_ledger(capture.document, capture.nodes)

    def test_the_totals_match_the_reconnaissance(self) -> None:
        """🔴 THE LOSS COUNT WAS RE-MEASURED 07.09.2026, AND THIS IS NOT
        FITTING TO GREEN.

        The former **11 625** was measured by the law "a name exists OR
        the value occurs in the node's text". That law counted as arrived:
        `params` (a key of that name exists on ANY operation-node, the
        content differs), any field whose `0` was found in someone else's
        coordinate, and a number in a DIFFERENT unit. With proof by value,
        units, and reference, losses became **12 865** (+1 240): part of
        the former "arrived" was a substring coincidence, part of the
        former "lost" was `host_id`, translated into A REFERENCE TO A NODE
        (0 → 182 represented). The denominator **20 482** did not move: the
        law "an empty field does not count" was not changed.

        🔴 THE NUMBERS WERE RE-MEASURED 07.09.2026 A SECOND TIME, AND THIS
        IS A REMOVED LOSS, NOT A WEAKENED INSTRUMENT: **12 865 -> 12 387**
        (−478), represented **7 617 -> 8 095**. One thing moved — the
        placement point was found where it actually sits: the node slot
        `anchor_mm` carries `p0_mm` for 151 doors, 31 windows, and 275
        other families. The comparison law was not touched, the comparison
        stayed BY VALUE: for 683 walls, `anchor_mm` is the segment's
        midpoint, and not one of them got `p0_mm` counted as arrived.
        """
        totals = self.ledger.totals
        self.assertEqual(totals["nonempty"], 20_482)
        self.assertEqual(totals["lost"], 12_417)
        self.assertAlmostEqual(totals["lost_share"], 0.606, places=3)
        self.assertEqual(totals["unclassified"], 0)
        self.assertEqual(totals["elements_without_node"], 0)
        self.assertEqual(totals["by_state"],
                         {"represented": 8_065, "approximate": 2_273,
                          "source_data": 1_247, "unknown": 8_897})
        self.assertEqual(sum(totals["by_state"].values()), totals["nonempty"])
        # 🔴 A RATCHET TOWARD THE WORK. The exact number is a snapshot; the
        # inequality is the obligation: there must not be MORE losses than
        # the previous measurement, and this instrument must turn red from
        # a REGRESSION, not from success.
        self.assertLessEqual(totals["lost"], 12_865)

    def test_the_ops_lose_more_than_the_atoms(self) -> None:
        """The refutation of "losses are a property of the atom" holds up
        BY THE NUMBER.

        The numbers were re-measured together with the counting law (it
        was 9 226 / 2 399), then again after removing the `anchor_mm` loss
        (it was 10 176 / 2 689): the conclusion did not budge once — ops
        lose more, even under strict proof.

        A third re-measurement — switching to the PUBLIC reading mode
        (`editable` instead of `none`; it was 15 304/9 955 and 5 178/2 432):
        the sketch profile lifts part of the atoms into ops, so the ops
        denominator grows while the atoms' shrinks. The conclusion did not
        budge the third time either.
        """
        kinds = self.ledger.totals["by_kind"]
        self.assertEqual(kinds["op"], {"nonempty": 15_499, "lost": 10_075})
        self.assertEqual(kinds["atom"], {"nonempty": 4_983, "lost": 2_342})
        self.assertGreater(kinds["op"]["lost"] / kinds["op"]["nonempty"],
                           kinds["atom"]["lost"] / kinds["atom"]["nonempty"])

    def test_exactly_three_fields_are_never_lost(self) -> None:
        self.assertEqual(self.ledger.totals["never_lost"],
                         ["element_id", "level_name", "type_name"])


@unittest.skipUnless(_corpus("bench_A"), "корпуса нет — замер не состоялся")
class TheBenchmarkRunIsFullyAddressed(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        capture = _public_capture("bench_A")
        cls.document = capture.document
        cls.ledger = field_ledger(cls.document, capture.nodes)

    def test_the_four_states_are_measured_on_the_real_capture(self) -> None:
        """🔴 A MEASUREMENT, NOT A GREEN LIGHT. A state counter on the real
        `bench_A`.

        `source_data` is exactly `params`, Revit's raw parameter dict for
        2 940 elements out of 4 223: it stays in L0 on disk and is
        addressed by `element_id`, but not one KIR operation reconstructs
        it. The former law counted it as ARRIVED for 2 737 elements only
        because the key `params` exists on any operation-node.

        🔴 RE-MEASURED 07.09.2026: represented **24 447 -> 26 330**
        (+1 883), unknown **29 369 -> 27 486**. Exactly two removed losses
        moved this, both by comparison BY VALUE, not by weakening the law:

        * `p0_mm` for 756 columns and 126 doors sat in the node slot
          `anchor_mm` (for 476 walls it is the segment's MIDPOINT — and not
          one was counted);
        * `host_id` for 777 beams is addressed by the reference
          `params.level._id`: a beam's host IS its level, and the node
          names that very entity.

        🔴 THE NUMBER DEPENDS ON THE READING MODE, AND THE PIN STOOD ON THE
        WRONG ONE (finding of 07.09.2026). One building, three
        `open_capture` modes:

            profiles   represented  approximate  unknown   lost
            none            26 330        1 695   27 486  32 121
            editable        26 282        1 647   27 582  32 169   <- PUBLIC
            all             26 272        1 638   27 601  32 179

        The pin stood at 26 330 — on `none`, a mode the public door does
        NOT read with: its default is `editable`. The numbers are now
        taken by that very door.

        THE REASON IN ONE SENTENCE: an atom carries Revit's fields
        VERBATIM, while an operation speaks the language of operations —
        so the sketch profile, lifting 24 elements (19 ceilings, 5 slabs)
        out of atoms into `create_ceiling`/`create_floor`, trades 96
        verbatim proofs (`category`, `category_ru`, `bbox_min_mm`,
        `bbox_max_mm` × 24 — `represented -> unknown`) for 48 referential
        ones (`type_id`, `level_id` × 24 — `approximate -> represented`,
        because an op addresses a type and a level by a registry reference
        with `_id`, while an atom only had a name).

        The sum adds up exactly: represented −48, approximate −48, unknown
        +96. And this is NOT a regression of the lift: 24 elements became
        reassemblable, and what dropped was a per-file match — different
        questions, and the ledger measures the second one.
        """
        totals = self.ledger.totals
        self.assertEqual(totals["nonempty"], 58_451)
        self.assertEqual(totals["by_state"],
                         {"represented": 26_282, "approximate": 1_647,
                          "source_data": 2_940, "unknown": 27_582})
        self.assertEqual(totals["lost"], 32_169)
        # 🔴 A RATCHET: represented must be NO LESS than the previous
        # measurement (24 447). The instrument turns red from a
        # regression, not from a removed loss.
        self.assertGreaterEqual(totals["by_state"]["represented"], 24_447)
        self.assertEqual(sum(totals["by_state"].values()), totals["nonempty"])
        self.assertEqual(totals["by_state"]["represented"],
                         totals["nonempty"] - totals["lost"])
        source_data = {item.field for row in self.ledger.rows for item in row.lost
                       if item.state == "source_data"}
        self.assertEqual(source_data, {"params"})

    def test_there_are_far_more_rows_than_the_measured_floor(self) -> None:
        """The acceptance's lower bound — 1109 lines with an address."""
        rows = self.ledger.lost_rows()
        self.assertGreaterEqual(len(rows), 1109)
        self.assertEqual(self.ledger.addressed, len(self.ledger.rows))
        self.assertTrue(all(row.element_id and row.unique_id for row in rows))

    def test_l1_equality_is_not_proof_that_nothing_was_lost(self) -> None:
        """🔴 CONTROL (d), AND IT MUST TURN RED FOR ANYONE WHO COUNTS L1
        EQUALITY AS SUCCESS.

        Five fields of door 286533 are stripped from L0 such that L1 stays
        BYTE FOR BYTE the same. The ledger must see every one of them.
        """
        import hashlib

        def digest(nodes):
            return hashlib.sha256(json.dumps(nodes, ensure_ascii=False, sort_keys=True,
                                             default=str).encode()).hexdigest()

        base = _lift("bench_A", self.document)
        before = field_ledger(self.document, base)
        door = next(e for e in self.document.elements if str(e.element_id) == "286533")
        self.assertIsNone(getattr(door, "workset", None),
                          "у этой двери `workset` ПУСТ — контроль на нём был бы "
                          "зелен по построению")
        invisible = ("host_source", "level_id", "phase_created", "rotation_deg", "unique_id")
        for name in invisible:
            with self.subTest(field=name):
                self.assertIsNotNone(getattr(door, name),
                                     "снимать надо НЕПУСТОЕ поле, иначе замера нет")
                elements = tuple(
                    dataclasses.replace(item, **{name: None})
                    if str(item.element_id) == "286533" else item
                    for item in self.document.elements)
                edited = dataclasses.replace(self.document, elements=elements)
                after = _lift("bench_A", edited)
                self.assertEqual(digest(after.nodes), digest(base.nodes),
                                 f"{name}: L1 обязан остаться равным — в этом контроль")
                ledger = field_ledger(edited, after)
                self.assertEqual(ledger.totals["lost"], before.totals["lost"] - 1,
                                 f"{name}: ведомость обязана увидеть то, чего L1 не видит")


if __name__ == "__main__":                                     # pragma: no cover
    unittest.main()


class TheSeamShapeGroupsByReasonNotByElement(unittest.TestCase):
    """`capture_edit.losses` calls this shape; it must not lie about the reason."""

    def setUp(self) -> None:
        from kir.decompile.field_ledger import as_losses

        self.ledger = field_ledger(FakeDocument(elements=(WALL, FLOOR)),
                                   [op_node(WALL), atom_node(FLOOR)])
        self.rows = as_losses(self.ledger)

    def test_every_row_has_an_address_and_a_single_reason(self) -> None:
        self.assertTrue(self.rows)
        for row in self.rows:
            with self.subTest(row=row):
                self.assertTrue(row["element_id"])
                self.assertIn(row["why"], WHY)
                self.assertTrue(row["fields"])
                self.assertEqual(row["fields"], sorted(row["fields"]))

    def test_one_element_with_two_reasons_gives_two_rows(self) -> None:
        """One line per element would name a single reason for all its fields."""
        wall_rows = [row for row in self.rows if row["element_id"] == "1"]
        self.assertGreater(len(wall_rows), 1)
        self.assertEqual(len({row["why"] for row in wall_rows}), len(wall_rows))

    def test_the_fields_of_all_rows_sum_to_the_ledger_total(self) -> None:
        """Not one lost field disappears when repacking into lines."""
        self.assertEqual(sum(len(row["fields"]) for row in self.rows),
                         self.ledger.totals["lost"])
