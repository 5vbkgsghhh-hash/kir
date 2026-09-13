"""Refuting tests for immutable, parent-bound grounding evidence."""
from __future__ import annotations

import copy
import dataclasses
import json
import unittest
from unittest import mock

from kir.compiler import compile_program, plan_program
from kir.ground import ground, ground_program
from kir.midend import (
    GroundedOp,
    _authored_selectors_left,
    GroundedProgram,
    GroundingContext,
    PlanEncodingError,
)
from kir.tests.fixtures import GROUND_SNAPSHOT


WALL_PROGRAM = {
    "ir_version": "1.0",
    "intent": "стена на первом этаже",
    "ops": [{
        "op": "create_wall",
        "id": "W1",
        "p0_mm": [0, 0],
        "p1_mm": [5000, 0],
        "level": {"by": "name", "value": "Этаж 1"},
    }],
}

STAIRS_PROGRAM = {
    "ir_version": "1.0",
    "intent": "размножить лестницу на два уровня",
    "ops": [{
        "op": "create_multistory_stairs",
        "id": "MS1",
        "stairs": {"by": "element_id", "value": 8145901},
        "levels": [
            {"by": "name", "value": "Этаж 1"},
            {"by": "element_id", "value": 43},
        ],
    }],
}


def _wire_bytes(payload: dict) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _marker_paths(value, path: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        if "__grounded__" in value:
            found.append(path or "<root>")
        for key in sorted(value):
            child_path = f"{path}.{key}" if path else key
            found.extend(_marker_paths(value[key], child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_marker_paths(child, f"{path}[{index}]"))
    return found


class GroundedProgramContractTests(unittest.TestCase):
    def test_write_compile_exposes_immutable_parent_bound_digest(self) -> None:
        out = compile_program(copy.deepcopy(WALL_PROGRAM),
                              snapshot=GROUND_SNAPSHOT)

        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        self.assertIsNotNone(out.grounded)
        assert out.grounded is not None
        self.assertIs(out.grounded.planned, out.planned)
        self.assertRegex(out.grounded.ground_digest, r"^[0-9a-f]{64}$")
        self.assertEqual(out.grounded.to_evidence_dict()["schema"],
                         "kir-grounded-program/4")
        self.assertEqual(out.as_dict()["ground_digest"],
                         out.grounded.ground_digest)

        digest = out.grounded.ground_digest
        detached = out.grounded.to_ops()
        detached[0]["level"]["__grounded__"]["id"] = 999999
        out.grounded_ops[0]["level"]["__grounded__"]["id"] = 888888
        detached_report = out.grounded.resolution_report()
        detached_report[0]["detail"]["id"] = 777777

        self.assertEqual(out.grounded.ground_digest, digest)
        self.assertEqual(
            out.grounded.to_ops()[0]["level"]["__grounded__"]["id"],
            42,
        )
        self.assertEqual(
            out.grounded.resolution_report()[0]["detail"]["id"],
            42,
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            out.grounded.ground_digest = "0" * 64  # type: ignore[misc]

    def test_every_nested_stairs_resolution_is_accounted_exactly(self) -> None:
        out = compile_program(copy.deepcopy(STAIRS_PROGRAM),
                              snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        assert out.grounded is not None

        marker_paths = [
            path
            for op in out.grounded.to_ops()
            for path in _marker_paths(op)
        ]
        report_paths = [
            row["field_name"] for row in out.grounded.resolution_report()
        ]
        self.assertEqual(marker_paths, ["levels[0]", "levels[1]"])
        self.assertEqual(report_paths, marker_paths)

        with self.assertRaisesRegex(ValueError, "cover every"):
            GroundedProgram(
                planned=out.grounded.planned,
                ops=out.grounded.ops,
                resolutions=out.grounded.resolutions[:-1],
            )
        with self.assertRaisesRegex(ValueError, "cover every"):
            GroundedProgram(
                planned=out.grounded.planned,
                ops=out.grounded.ops,
                resolutions=out.grounded.resolutions
                + (out.grounded.resolutions[0],),
            )
        with self.assertRaisesRegex(ValueError, "cover every"):
            GroundedProgram(
                planned=out.grounded.planned,
                ops=out.grounded.ops,
                resolutions=tuple(reversed(out.grounded.resolutions)),
            )

    def test_resolution_identity_changes_digest_but_rule_cannot_be_rewritten(self) -> None:
        out = compile_program(copy.deepcopy(WALL_PROGRAM),
                              snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        assert out.grounded is not None and out.planned is not None
        changed = out.grounded.to_ops()
        changed[0]["level"]["__grounded__"]["id"] = 424242
        rebuilt = GroundedProgram.from_ops(out.planned, changed)
        self.assertNotEqual(rebuilt.ground_digest, out.grounded.ground_digest)

        for field_name, replacement in (
            ("name", "Другой уровень"),
            ("via", "element_id"),
        ):
            with self.subTest(field_name=field_name):
                changed = out.grounded.to_ops()
                changed[0]["level"]["__grounded__"][field_name] = replacement
                with self.assertRaisesRegex(
                        ValueError, "declared selector did not lower"):
                    GroundedProgram.from_ops(out.planned, changed)

    def test_non_resolution_output_drift_cannot_keep_the_same_digest(self) -> None:
        """Ordinary authored values are outside the lowering surface."""
        out = compile_program(copy.deepcopy(WALL_PROGRAM),
                              snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        assert out.grounded is not None and out.planned is not None

        changed = out.grounded.to_ops()
        changed[0]["p1_mm"] = [6000, 0]
        with self.assertRaisesRegex(ValueError, "ordinary planned value changed"):
            GroundedProgram.from_ops(out.planned, changed)

    def test_ground_digest_binds_exact_snapshot_and_document_identity(self) -> None:
        planned = plan_program(copy.deepcopy(WALL_PROGRAM))
        first_snapshot = copy.deepcopy(GROUND_SNAPSHOT)
        second_snapshot = copy.deepcopy(GROUND_SNAPSHOT)
        second_snapshot["__document_fingerprint"] = {
            "title": "Other Model",
            "path_name": r"C:\models\other.rvt",
            "project_uid": "other-project-uid",
        }

        first = ground_program(planned, first_snapshot)
        second = ground_program(planned, second_snapshot)

        # Resolved ids/names are identical, but the model read is not.
        self.assertNotEqual(first.ground_digest, second.ground_digest)
        self.assertNotEqual(first.context.context_digest,
                            second.context.context_digest)
        self.assertNotEqual(first.context.document_digest,
                            second.context.document_digest)
        evidence = first.to_evidence_dict()
        self.assertEqual(
            evidence["context"]["snapshot_digest"],
            first.context.snapshot_digest,
        )
        self.assertTrue(evidence["context"]["identity_bound"])
        self.assertFalse(evidence["context"]["execution_bound"])
        self.assertFalse(evidence["context"]["authoritative"])

    def test_trusted_context_cannot_be_reused_for_another_snapshot(self) -> None:
        planned = plan_program(copy.deepcopy(WALL_PROGRAM))
        context = GroundingContext.from_snapshot(
            GROUND_SNAPSHOT,
            source="trusted_bridge",
            trusted_source=True,
        )
        grounded = ground_program(
            planned, GROUND_SNAPSHOT, context=context)
        self.assertTrue(grounded.context.execution_bound)
        # No revision/profile proof was supplied: identity binding must not be
        # promoted to full snapshot authority.
        self.assertFalse(grounded.context.authoritative)

        other = copy.deepcopy(GROUND_SNAPSHOT)
        other["levels"][0]["name"] = "Подменённый уровень"
        with self.assertRaisesRegex(ValueError, "another snapshot payload"):
            ground_program(planned, other, context=context)

    def test_removed_reordered_and_extra_ops_cannot_rebind_parent(self) -> None:
        program = copy.deepcopy(WALL_PROGRAM)
        program["ops"].append({
            "op": "create_wall",
            "id": "W2",
            "p0_mm": [0, 1000],
            "p1_mm": [5000, 1000],
            "level": {"by": "name", "value": "Этаж 1"},
        })
        planned = plan_program(program)
        grounded = ground_program(planned, GROUND_SNAPSHOT)
        ops = grounded.to_ops()

        variants = {
            "removed": ops[:-1],
            "reordered": list(reversed(ops)),
            "extra": ops + [{**copy.deepcopy(ops[-1]), "id": "EXTRA"}],
        }
        for name, candidate in variants.items():
            with self.subTest(name=name), self.assertRaisesRegex(
                    ValueError, "preserve parent order and identity"):
                GroundedProgram.from_ops(planned, candidate)

    def test_typed_adapter_preserves_legacy_ground_bytes(self) -> None:
        planned = plan_program(copy.deepcopy(STAIRS_PROGRAM))
        legacy_input = planned.to_ops()
        original_input = copy.deepcopy(legacy_input)

        legacy = ground(legacy_input, GROUND_SNAPSHOT)
        typed = ground_program(planned, GROUND_SNAPSHOT)

        self.assertIsInstance(legacy, list)
        self.assertEqual(legacy_input, original_input)
        self.assertEqual(_wire_bytes(legacy), _wire_bytes(typed.to_ops()))

    def test_query_and_refusal_wire_dicts_do_not_gain_ground_fields(self) -> None:
        query = compile_program({
            "ir_version": "1.0",
            "ops": [{"op": "query_count", "id": "Q1", "kind": "wall"}],
        })
        self.assertTrue(query.ok, [d.as_dict() for d in query.diagnostics])
        assert query.planned is not None
        expected_query = {
            "ok": True,
            "csharp": query.csharp,
            "diagnostics": [],
            "plan_digest": query.planned.plan_digest,
        }
        self.assertEqual(_wire_bytes(query.as_dict()),
                         _wire_bytes(expected_query))

        refusal = compile_program({"ir_version": "1.0", "ops": []})
        # THE TEXT HERE IS INCIDENTAL, THE SHAPE IS THE SUBJECT. The
        # test asserts that the wire's dict does NOT GROW grounding
        # fields; a byte-for-byte comparison is the strongest form of
        # this assertion, and the price for it is the message literal.
        # It grew on 17.08.2026 when the envelope ritual was removed
        # (`dc84b87e`): the refusal started naming a new capability. It
        # is updated along with that, not "fixed" — the message is not
        # this test's subject.
        expected_refusal = {
            "ok": False,
            "csharp": None,
            "diagnostics": [{
                "code": "KIR-P001",
                "message_ru": ("ops — непустой список операций (одна операция "
                               "может быть написана и без списка)"),
                "field_name": "ops",
            }],
        }
        self.assertEqual(_wire_bytes(refusal.as_dict()),
                         _wire_bytes(expected_refusal))
        self.assertNotIn("ground_digest", query.as_dict())
        self.assertNotIn("ground_digest", refusal.as_dict())

    def test_canonical_grounding_rejects_nan_and_lone_surrogates(self) -> None:
        for label, value in (
            ("nan", float("nan")),
            ("lone_surrogate", "\ud800"),
        ):
            with self.subTest(label=label), self.assertRaises(PlanEncodingError):
                GroundedOp.from_dict({
                    "op": "create_wall",
                    "id": "W1",
                    "probe": value,
                })

        planned = plan_program(copy.deepcopy(WALL_PROGRAM))
        invalid_ground = planned.to_ops()
        invalid_ground[0]["__test_non_finite__"] = float("nan")
        with mock.patch("kir.ground.ground",
                        return_value=invalid_ground):
            out = compile_program(planned, snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertEqual([d.code for d in out.diagnostics], ["KIR-P000"])

    def test_marker_without_named_resolution_rule_is_rejected(self) -> None:
        planned = plan_program(copy.deepcopy(WALL_PROGRAM))
        grounded = ground(planned.to_ops(), GROUND_SNAPSHOT)
        del grounded[0]["level"]["__grounded__"]["via"]
        with self.assertRaisesRegex(ValueError, "named rule"):
            GroundedProgram.from_ops(planned, grounded)


class ПланВРолиЗаземлённогоНеПроходит(unittest.TestCase):
    """🔴 ZERO WORK IS NOT ZERO DISCREPANCIES (F-103, 30.08.2026).

    `_assert_payload_refinement` skips EVERY unchanged value before
    checking whether the selector fields were omitted. If NOTHING had
    changed, there turned out to be nothing to check — and
    `GroundedProgram.from_ops(plan, plan.to_ops())`, that is, "here is
    the plan, and here it is again playing the role of the grounded
    one", PASSED. The selector stayed authored, no resolution had
    taken place, and `derived_artifacts_verified` and
    `selector_resolution_replayed` reported true and rode into the
    receipt (`serving.py`, the `ground_context` block) as proof that
    the compiler had queried the document.
    """

    ПРОГРАММА = {
        "ir_version": "1.0", "intent": "t",
        "ops": [{"op": "create_wall", "id": "W1",
                 "p0_mm": [0, 0], "p1_mm": [6000, 0], "height_mm": 3000,
                 "level": {"by": "name", "value": "Этаж 1"}}],
    }
    СНИМОК = {"levels": [{"id": 501, "name": "Этаж 1", "elevation_mm": 0}],
              "types": {"wall": [{"id": 900, "name": "Типовой - 200мм"}]}}

    def test_a_plan_handed_to_itself_is_refused_by_name(self):
        plan = plan_program(self.ПРОГРАММА)
        with self.assertRaises(ValueError) as поймано:
            GroundedProgram.from_ops(plan, plan.to_ops())
        текст = str(поймано.exception)
        self.assertIn("заземление не состоялось", текст)
        self.assertIn("W1.level", текст,
                      "отказ не назвал ПОЛЕ, из-за которого он случился")

    def test_a_really_grounded_program_still_passes(self):
        """A NARROWNESS CONTROL, and it matters more than the first
        one: a refusal that fires on a legitimate input is worse than a
        missing one."""
        out = compile_program(self.ПРОГРАММА, revit_version="2026",
                              snapshot=self.СНИМОК)
        self.assertTrue(out.ok, out.diagnostics)
        self.assertIsNotNone(out.grounded)
        self.assertTrue(out.grounded.derived_artifacts_verified)
        # And not a single authored selector was left — the very thing
        # the refusal above rests its right to exist on.
        for op in out.grounded.to_ops():
            for поле in ("level", "type"):
                значение = op.get(поле)
                if isinstance(значение, dict):
                    with self.subTest(op=op["id"], поле=поле):
                        self.assertNotIn("by", значение)

    def test_an_op_without_selectors_is_not_accused(self):
        """There being nothing to ground does not mean "grounding did
        not happen". An op with no selector fields passes, and that is
        the SECOND side of narrowness."""
        plan = plan_program({"ir_version": "1.0", "intent": "t", "ops": [
            {"op": "create_level", "id": "L1", "elev_mm": 0,
             "name": "Этаж 1"}]})
        g = GroundedProgram.from_ops(plan, plan.to_ops())
        self.assertTrue(g.derived_artifacts_verified)

    def test_a_selector_the_grounder_cannot_lower_is_not_accused(self):
        """🔴 A CONTROL I DID NOT HAVE, AND IT WAS BOUGHT BY A RED.

        The first edition of the check only asked `kind == "sel"` and
        was failing the course recipes «витраж» and «витраж-джуниор» on
        ALL six versions: `set_curtain_panel.panel_type` is declared a
        selector, but its `ref_kinds` is EMPTY — there is nothing to
        ground it with, and real grounding legitimately leaves it
        authored.

        It splits on the same trait the grounder itself uses: a
        non-empty `ref_kinds`. That is what gets pinned here — against
        THE REGISTRY, not against the op's name, so the test does not
        rot along with the recipe.
        """
        from kir import spec

        # A field declared a selector and yet UNgroundable must exist —
        # otherwise the test's subject has vanished and the test must
        # be rewritten, not left as is.
        незаземляемые = [
            (имя, p.name) for имя, op in spec.OPS.items() for p in op.params
            if p.kind == "sel" and not p.ref_kinds
        ]
        self.assertTrue(
            незаземляемые,
            "в реестре не осталось незаземляемых селекторов — предмет теста "
            "исчез")
        for имя_опа, поле in незаземляемые:
            with self.subTest(оп=имя_опа, поле=поле):
                self.assertEqual(
                    _authored_selectors_left(
                        имя_опа, {поле: {"by": "name", "value": "Х"}}),
                    [],
                    "обвинён селектор, который заземлять НЕЧЕМ")

    def test_a_groundable_selector_left_authored_IS_accused(self):
        """The other side of the same thing: a field with a non-empty
        `ref_kinds` that stayed authored must be found. Without this,
        the test above would settle for a check that NEVER accuses
        anything."""
        from kir import spec

        заземляемые = [
            (имя, p.name) for имя, op in spec.OPS.items() for p in op.params
            if p.kind == "sel" and p.ref_kinds
        ]
        self.assertTrue(заземляемые)
        имя_опа, поле = заземляемые[0]
        self.assertEqual(
            _authored_selectors_left(
                имя_опа, {поле: {"by": "name", "value": "Х"}}),
            [поле])

    def test_the_ledger_of_ungrounded_places_holds_no_ghosts(self):
        """🔴 THE LEDGER TRAVELS IN ONE DIRECTION. A resolution whose
        spot has been fixed makes the check less truthful with every
        passing day — the same ratchet as `MUTE_SOURCES` and
        `BARE_ACCESS_OPEN`, and the same price: THE SAME commit that
        fixes the spot removes the line.

        Here this is checked by BEHAVIOR, not by a list: if the
        grounder has learned to omit the field, the entry must go.
        """
        from kir.compiler import plan_program
        from kir.ground import ground
        from kir.midend import UNGROUNDED_PLACES

        призраки = []
        for (имя_опа, поле), _ in UNGROUNDED_PLACES.items():
            программа = self.ПРОГРАММЫ_ВЕДОМОСТИ.get((имя_опа, поле))
            if программа is None:
                continue
            ops = ground(plan_program(программа).to_ops(), GROUND_SNAPSHOT)
            raw = ops.to_ops() if hasattr(ops, "to_ops") else ops
            for op in raw:
                if op.get("op") != имя_опа:
                    continue
                значение = op.get(поле)
                if isinstance(значение, dict) and "__grounded__" in значение:
                    призраки.append(f"{имя_опа}.{поле}")
        self.assertEqual(
            призраки, [],
            "заземлитель научился опускать эти поля — сними их из "
            "UNGROUNDED_PLACES тем же коммитом, что починил место")

    #: A witness program for every ledger entry. Without it, the check
    #: above is green by construction: nothing to run — nothing to
    #: disprove.
    ПРОГРАММЫ_ВЕДОМОСТИ = {
        ("create_site_subregion", "host"): {
            "ir_version": "1.0", "intent": "подобласть площадки",
            "ops": [{"op": "create_site_subregion", "id": "R1",
                     "contour": {"outer": {
                         "shape": "poly",
                         "points_mm": [[1000, 1000], [9000, 1000],
                                       [9000, 7000], [1000, 7000]]}},
                     "host": {"by": "element_id", "value": 7777}}],
        },
    }

    def test_every_ledger_entry_has_a_witness_program(self):
        """An entry with no witness is unverifiable, and the ledger
        would turn into a place where the inconvenient gets dumped."""
        from kir.midend import UNGROUNDED_PLACES
        self.assertEqual(
            sorted(UNGROUNDED_PLACES), sorted(self.ПРОГРАММЫ_ВЕДОМОСТИ),
            "у записи ведомости нет программы-свидетеля")

    def test_the_ledger_is_small_and_named(self):
        """A FLOOR against the dump: the list must stay SMALL, and
        every entry must carry a reason."""
        from kir.midend import UNGROUNDED_PLACES
        self.assertLessEqual(len(UNGROUNDED_PLACES), 3)
        for ключ, довод in UNGROUNDED_PLACES.items():
            with self.subTest(место=ключ):
                self.assertGreaterEqual(len(довод), 40)

    def test_the_resolution_count_stands_beside_the_flag(self):
        """🔴 ONE FIELD CANNOT CARRY TWO FACTS.

        `selector_resolution_replayed` is true EXACTLY WHEN there are NO
        resolutions — a deliberate caution, explained in its own place:
        without actually replaying the snapshot resolver, asserting
        "replayed" would mean claiming more than the digest proves. But
        the name reads the opposite way, so a NUMBER must stand next to
        it: "there was nothing to replay" and "there was something, and
        we did not do it" stop looking the same.

        The flag's polarity is deliberately NOT touched — that would
        tell an untruth in the other direction.
        """
        out = compile_program(self.ПРОГРАММА, revit_version="2026",
                              snapshot=self.СНИМОК)
        self.assertGreater(out.grounded.selector_resolutions, 0)
        self.assertFalse(out.grounded.selector_resolution_replayed)

        plan = plan_program({"ir_version": "1.0", "intent": "t", "ops": [
            {"op": "create_level", "id": "L1", "elev_mm": 0,
             "name": "Этаж 1"}]})
        пусто = GroundedProgram.from_ops(plan, plan.to_ops())
        self.assertEqual(пусто.selector_resolutions, 0)
        self.assertTrue(пусто.selector_resolution_replayed)

    def test_the_resolution_count_does_not_move_the_ground_digest(self):
        """The number is COMPUTED and does not go into the evidence:
        the list of resolutions is already there, and an extra field
        would shift `ground_digest` for every golden for the sake of
        something that is already derivable."""
        out = compile_program(self.ПРОГРАММА, revit_version="2026",
                              snapshot=self.СНИМОК)
        evidence = out.grounded._unsigned_evidence()
        self.assertNotIn("selector_resolutions",
                         json.dumps(evidence, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
