"""§18.2 — the law of the receipt. Refuting tests (§18.7 item 4).

The measurement the law was born from (28.07, SOB6.2_FAS_R23, decompile
``backend/data/decompile/sob62_fas_r23_v2``): the ``family_placement`` side stage
was asked for 1799 elements, the index returned 1557 rows, and about
242 it said NOTHING AT ALL — neither a row nor a refusal. All 242 turned out to be
``OST_CurtainWallPanels``, and in the lift they became atoms with the reason "element is
absent from the family placement side index": from outside this looks like a hole in
the compiler's capabilities, though in fact the extractor simply discarded them (not
``FamilyInstance`` / cut by budget). For comparison, ``curve``/``curtain``/
``sketch`` in the same run matched down to the element: 1178/1178, 1178+983/1178,
55/55.

At the time of writing, the following failed:
  * the family_placement/group response did not carry the ``failures`` key at all;
  * the emitter broke on budget (``break``) and silently skipped an element
    (``continue``/``catch {}``) — with no record of it;
  * one unparsed placement row failed the ENTIRE run
    (``from_rows`` — a generator with no isolation);
  * the invariant ``mirrored == hand XOR facing`` killed the run, even though it is wrong
    for mirroring about an arbitrary plane;
  * ``sketch_extract`` ran three whole-model passes with no budget;
  * ``_rows_of`` on an unrecognized response shape returned ``[]`` — an empty index
    got stuck on disk and was reused by the resume logic;
  * nobody read the ``failures`` aggregate: not ``run.json``, not ``status.json``,
    not the passport, not the lift.
"""
from __future__ import annotations

import asyncio
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from kir.decompile import pipeline as pipe
from kir.decompile.family_placement_extract import (
    FamilyPlacementExtraction,
    FamilyPlacementPayloadError,
    build_family_placement_extract_cs,
)
from kir.decompile.group_extract import (
    GroupExtraction,
    build_group_extract_cs,
)
from kir.decompile.sketch_extract import build_sketch_extract_cs
from kir.decompile.side_contract import (
    SideFailureReason,
    SideStageContractError,
)
from kir.decompile.tests.test_pipeline import (
    FakePipelineBridge,
    _family_wire_row,
    _mini_metadata,
)


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _group_wire_row(element_id: str = "9001") -> dict[str, Any]:
    return {
        "element_id": element_id,
        "group_type_id": "7700",
        "group_type_name": "Санузел",
        "member_ids": ["1", "2"],
        "group_id_parent": None,
        "attached_detail_type_count": 0,
        "reference_level_id": None,
        "origin_level_offset_ft": None,
        "status": "ok",
        "origin_ft": [1.0, 2.0, 0.0],
        "rotation_rad": 0.0,
    }


# ── PART 1: the general contract of the side stage ──────────────────────────────────


class SideAnswerCarriesFailures(unittest.TestCase):
    """The side stage's response = rows + failures, BOTH keys are mandatory."""

    def test_family_placement_bundle_carries_a_failures_key(self) -> None:
        extraction = FamilyPlacementExtraction.from_rows([_family_wire_row("3")])
        payload = extraction.to_dict()
        self.assertIn("failures", payload)
        self.assertEqual(payload["failures"], [])
        # The circle is closed: an empty list survives write/read.
        self.assertEqual(
            FamilyPlacementExtraction.from_json(extraction.to_json()),
            extraction)

    def test_group_bundle_carries_a_failures_key(self) -> None:
        extraction = GroupExtraction.from_rows([_group_wire_row()])
        payload = extraction.to_dict()
        self.assertIn("failures", payload)
        self.assertEqual(payload["failures"], [])
        self.assertEqual(
            GroupExtraction.from_json(extraction.to_json()), extraction)

    def test_wire_failures_ride_into_the_bundle(self) -> None:
        extraction = FamilyPlacementExtraction.from_rows(
            [_family_wire_row("3")],
            wire_failures=[{
                "element_id": "4",
                "reason": "call_budget_exhausted",
                "typed_reason": "call_budget_exhausted",
                "elapsed_ms": 20001,
            }],
        )
        self.assertEqual(len(extraction.records), 1)
        self.assertEqual(len(extraction.failures), 1)
        failure = extraction.failures[0]
        self.assertEqual(failure.element_id, "4")
        self.assertEqual(
            failure.typed_reason, SideFailureReason.CALL_BUDGET_EXHAUSTED)

    def test_family_emitter_leaves_a_receipt_for_every_dropped_id(
            self) -> None:
        body = build_family_placement_extract_cs(["11", "22"])
        # The response carries both keys.
        self.assertIn('"failures", __fpFailures', body)
        # Not a single mute exit: a budget cut, an unresolved id, a non-
        # FamilyInstance, and a caught exception — all of them leave a row.
        for token in (
            '"call_budget_exhausted"',
            '"time_budget_exceeded"',
            '"element_unresolved"',
            '"element_kind_mismatch"',
            '"read_failed"',
        ):
            self.assertIn(token, body, token)
        # No empty `continue` without a receipt record is left.
        self.assertNotIn("if (__instance == null) continue;", body)

    def test_group_emitter_leaves_a_receipt_for_every_dropped_group(
            self) -> None:
        body = build_group_extract_cs()
        self.assertIn('"failures", __grFailures', body)
        for token in ('"call_budget_exhausted"', '"read_failed"',
                      '"element_kind_mismatch"'):
            self.assertIn(token, body, token)


class BrokenRowIsIsolated(unittest.TestCase):
    """One broken row = one failure, zero failed runs (M6)."""

    def test_one_unparsable_row_does_not_kill_the_batch(self) -> None:
        broken = _family_wire_row("77")
        del broken["rotation_rad"]  # point_ft without a pair — malformed
        extraction = FamilyPlacementExtraction.from_rows(
            [_family_wire_row("3"), broken, _family_wire_row("9")])
        self.assertEqual(
            [record.element_id for record in extraction.records], ["3", "9"])
        self.assertEqual(len(extraction.failures), 1)
        self.assertEqual(extraction.failures[0].element_id, "77")
        self.assertEqual(
            extraction.failures[0].typed_reason,
            SideFailureReason.ROW_UNPARSABLE)

    def test_row_without_a_readable_id_still_leaves_a_receipt(self) -> None:
        extraction = FamilyPlacementExtraction.from_rows([{"status": "ok"}])
        self.assertEqual(extraction.records, ())
        self.assertEqual(len(extraction.failures), 1)
        self.assertEqual(
            extraction.failures[0].typed_reason,
            SideFailureReason.ROW_UNPARSABLE)

    def test_mirror_invariant_violation_is_a_receipt_not_a_death(self) -> None:
        impossible = _family_wire_row("55")
        impossible.update({
            "mirrored": True, "hand_flipped": False, "facing_flipped": False})
        extraction = FamilyPlacementExtraction.from_rows(
            [impossible, _family_wire_row("3")])
        self.assertEqual(
            [record.element_id for record in extraction.records], ["3"])
        self.assertEqual(len(extraction.failures), 1)
        self.assertEqual(extraction.failures[0].element_id, "55")
        self.assertEqual(
            extraction.failures[0].typed_reason,
            SideFailureReason.MIRROR_INVARIANT_VIOLATED)

    def test_one_broken_group_row_does_not_kill_the_batch(self) -> None:
        broken = _group_wire_row("9002")
        del broken["group_type_name"]
        extraction = GroupExtraction.from_rows(
            [_group_wire_row("9001"), broken])
        self.assertEqual(
            [record.element_id for record in extraction.records], ["9001"])
        self.assertEqual(len(extraction.failures), 1)
        self.assertEqual(extraction.failures[0].element_id, "9002")


class StageReconcilesCounts(unittest.TestCase):
    """The stage checks requested vs. received and refuses in a typed way."""

    def test_missing_receipt_is_a_typed_stage_error(self) -> None:
        with self.assertRaises(SideStageContractError):
            pipe._reconcile_side_stage(
                "family_placement",
                requested=("1", "2", "3"),
                accounted=("1", "2"))

    def test_full_coverage_passes(self) -> None:
        pipe._reconcile_side_stage(
            "family_placement", requested=("1", "2"), accounted=("2", "1"))

    def test_a_curtain_row_is_counted_by_its_wall_id(self) -> None:
        # The curtain-wall index names the key ``wall_id``. A direct read of
        # ``record.element_id`` would declare EVERY successfully
        # read curtain wall lost and would fail the stage on the very first such building.
        from kir.decompile.curtain_extract import (
            CurtainExtraction,
            CurtainWallRecord,
        )
        extraction = CurtainExtraction(
            records=(CurtainWallRecord.not_curtain("8145914"),))
        self.assertEqual(pipe._accounted_ids(extraction), ["8145914"])

    def test_unrecognized_payload_shape_is_a_typed_refusal(self) -> None:
        with self.assertRaises(pipe.PipelineError) as ctx:
            pipe._rows_of(42, "placements")
        self.assertEqual(ctx.exception.code, "side_payload_unrecognized")

    def test_pipeline_refuses_a_stage_that_loses_ids_silently(self) -> None:
        class _LosesIdsBridge(FakePipelineBridge):
            async def _dispatch(self, code: str, *, timeout_ms: int) -> Any:
                from kir.decompile.family_placement_extract import (
                    FAMILY_PLACEMENT_EXTRACT_SCHEMA_VERSION,
                )
                if FAMILY_PLACEMENT_EXTRACT_SCHEMA_VERSION in code:
                    self.side_calls.append("family_placement")
                    # 3001 and 4001 were requested — we return one row and not a
                    # single receipt: exactly what the live emitter did.
                    return {"ok": True, "result": {
                        "schema_version":
                            FAMILY_PLACEMENT_EXTRACT_SCHEMA_VERSION,
                        "placements": [_family_wire_row("3001")],
                        "failures": []}}
                return await super()._dispatch(code, timeout_ms=timeout_ms)

        with TemporaryDirectory() as tmp:
            result = _run(pipe.run_decompile(
                _LosesIdsBridge(), out_dir=tmp,
                change_stamp="pipeline-mini-v1"))
            self.assertFalse(result.ok, msg=result.to_dict())
            self.assertEqual(
                result.error["code"], "side_stage_count_mismatch")


class ReusedArtifactCarriesARowCount(unittest.TestCase):
    """MINOR-10: an empty index must not get stuck on disk silently."""

    def test_reused_artifact_is_checked_against_its_row_count(self) -> None:
        with TemporaryDirectory() as tmp:
            first = _run(pipe.run_decompile(
                FakePipelineBridge(), out_dir=tmp,
                change_stamp="pipeline-mini-v1"))
            self.assertTrue(first.ok, msg=first.to_dict())
            manifest_path = Path(tmp) / pipe._SIDE_MANIFEST_NAME
            self.assertTrue(manifest_path.is_file())
            manifest = json.loads(manifest_path.read_text("utf-8"))
            self.assertIn("family_placement", manifest["stages"])
            self.assertEqual(
                manifest["stages"]["family_placement"]["rows"], 2)

            # We substitute the artifact with an empty index — the reuse logic must
            # notice the mismatch against the counter and recompute the stage.
            (Path(tmp) / "family_placement.index.json").write_text(
                FamilyPlacementExtraction(()).to_json(), encoding="utf-8")
            bridge = FakePipelineBridge()
            second = _run(pipe.run_decompile(
                bridge, out_dir=tmp, change_stamp="pipeline-mini-v1"))
            self.assertTrue(second.ok, msg=second.to_dict())
            self.assertIn("family_placement", bridge.side_calls)
            index = json.loads(
                (Path(tmp) / "family_placement.index.json").read_text("utf-8"))
            self.assertEqual(len(index["family_placement_index"]), 2)


# ── PART 3: receipts are read ─────────────────────────────────────────────


def _cut_metadata() -> dict[str, Any]:
    return _mini_metadata()


class _CutBridge(FakePipelineBridge):
    """A bridge whose family_placement cuts one id by budget."""

    async def _dispatch(self, code: str, *, timeout_ms: int) -> Any:
        from kir.decompile.family_placement_extract import (
            FAMILY_PLACEMENT_EXTRACT_SCHEMA_VERSION,
        )
        if FAMILY_PLACEMENT_EXTRACT_SCHEMA_VERSION in code:
            self.side_calls.append("family_placement")
            rows = [_family_wire_row("3001")] if '"3001"' in code else []
            failures = []
            if '"4001"' in code:
                failures.append({
                    "element_id": "4001",
                    "reason": "time_budget_exceeded",
                    "typed_reason": "time_budget_exceeded",
                    "elapsed_ms": 2001,
                })
            return {"ok": True, "result": {
                "schema_version": FAMILY_PLACEMENT_EXTRACT_SCHEMA_VERSION,
                "placements": rows, "failures": failures}}
        return await super()._dispatch(code, timeout_ms=timeout_ms)


class FailuresAreRead(unittest.TestCase):
    """The failures aggregate makes it into run.json / status.json / the passport (M5)."""

    def test_receipts_reach_run_status_and_passport(self) -> None:
        with TemporaryDirectory() as tmp:
            result = _run(pipe.run_decompile(
                _CutBridge(), out_dir=tmp, change_stamp="pipeline-mini-v1"))
            self.assertTrue(result.ok, msg=result.to_dict())
            out = Path(tmp)
            run = json.loads((out / "run.json").read_text("utf-8"))
            self.assertEqual(run["side_cuts_total"], 1)
            self.assertEqual(
                run["side_cuts_by_reason"]["time_budget_exceeded"], 1)
            self.assertEqual(
                run["side_failures_by_stage"]["family_placement"], 1)
            status = json.loads((out / "status.json").read_text("utf-8"))
            self.assertEqual(status["side_cuts_total"], 1)
            passport = json.loads((out / "passport.json").read_text("utf-8"))
            self.assertEqual(passport["stats"]["side_cuts_total"], 1)
            markdown = (out / "passport.md").read_text("utf-8")
            self.assertIn("квитанции срезов: 1", markdown)
            self.assertIn("time_budget_exceeded", markdown)

    def test_a_run_without_cuts_says_so_out_loud(self) -> None:
        with TemporaryDirectory() as tmp:
            result = _run(pipe.run_decompile(
                FakePipelineBridge(), out_dir=tmp,
                change_stamp="pipeline-mini-v1"))
            self.assertTrue(result.ok, msg=result.to_dict())
            markdown = (Path(tmp) / "passport.md").read_text("utf-8")
            self.assertIn("квитанции срезов: срезов нет", markdown)
            run = json.loads((Path(tmp) / "run.json").read_text("utf-8"))
            self.assertEqual(run["side_cuts_total"], 0)

    def test_lift_names_the_receipt_instead_of_a_faceless_absence(
            self) -> None:
        from kir.decompile import lift as lift_mod
        from kir.decompile.tests.fixtures_decompile import make_element
        from kir.decompile.schema import L0Document, ProjectInfo

        element = lift_mod.L0Element.from_dict(
            make_element("OST_Furniture", 5005, ordinal=0))
        document = L0Document(
            doc_name="d", revit_version="2026", units="mm",
            change_stamp="c", levels=(), grids=(), rooms=(),
            project_info=ProjectInfo(
                name="p", address="a", building_type_hint=None),
            elements=(element,))
        index_payload = {
            "schema_version":
                "kir-decompile-family-placement-index/1",
            "family_placement_index": {},
            "failures": [{
                "element_id": "5005",
                "reason": "time_budget_exceeded",
                "typed_reason": "time_budget_exceeded",
                "elapsed_ms": 2001,
            }],
        }
        result = lift_mod.lift_document_detailed(
            document, None, index_payload, wall_curve_index=None)
        atoms = [node for node in result.nodes if node.get("kind") != "op"]
        self.assertEqual(len(atoms), 1)
        detail = atoms[0]["reason"]["detail"]
        self.assertIn("time_budget_exceeded", detail)
        self.assertNotIn("absent from the family placement side index", detail)


# ── PART 4: the sketch_extract budget ──────────────────────────────────────────


class SketchIsBudgeted(unittest.TestCase):
    def test_sketch_emitter_takes_ids_and_budgets(self) -> None:
        body = build_sketch_extract_cs(
            ["2001", "2002"], element_budget_ms=1234, call_budget_ms=4321)
        self.assertIn("1234L", body)
        self.assertIn("4321L", body)
        self.assertIn('"2001"', body)
        self.assertIn('"failures", __skFailures', body)
        for token in ('"call_budget_exhausted"', '"time_budget_exceeded"'):
            self.assertIn(token, body, token)

    def test_sketch_stage_is_paginated_by_l0_ids(self) -> None:
        from kir.decompile.sketch_extract import (
            SKETCH_EXTRACT_SCHEMA_VERSION,
        )
        from kir.decompile.tests.fixtures_decompile import make_element

        floors = [make_element("OST_Floors", 2000 + i, ordinal=i)
                  for i in range(pipe._SIDE_BATCH + 1)]
        elements = {
            "OST_Walls": [make_element("OST_Walls", 1001, ordinal=0)],
            "OST_Floors": floors,
        }
        with TemporaryDirectory() as tmp:
            bridge = FakePipelineBridge(
                elements=elements, metadata=_mini_metadata())
            result = _run(pipe.run_decompile(
                bridge, out_dir=tmp, change_stamp="sketch-page-v1"))
            self.assertTrue(result.ok, msg=result.to_dict())
            self.assertEqual(bridge.side_calls.count("sketch"), 2)
            index = json.loads(
                (Path(tmp) / "sketch.index.json").read_text("utf-8"))
            self.assertEqual(
                len(index["profile_index"]), pipe._SIDE_BATCH + 1)
            _ = SKETCH_EXTRACT_SCHEMA_VERSION


class TypedReasonLawTests(unittest.TestCase):
    """§18.2 — EVERY receipt must have a reason, and the reason must have a class.

    The measurement this part of the law was born from (29.07, 13A-RD-AR-K2_v33,
    59 floors, decompile ``backend/data/decompile/k2_ar_rd_v6``, 55 293
    elements): ``side_failures_untyped`` = 14 569 out of 18 023 refusals, meaning
    the overwhelming majority of refusals had no reason at all. Of these, 14 343
    fell on the ``curtain`` stage, and this was the LARGEST number in the entire
    breakdown — and by it the stage was labeled "the biggest failure."

    The analysis showed the opposite: 14 324 out of 14 343 are ordinary walls without a
    CurtainGrid, and each of them, besides the receipt, also has a full index
    row. The stage worked through them cleanly. The real curtain-wall failures number
    19 (18 unrecognized hosts and one curtain wall with two grids).

    At the time of writing, both tests below failed.
    """

    def test_every_reason_is_classified(self) -> None:
        # A new reason without a class would drop out of both sums at once — exactly how
        # the 14 569 refusals ended up outside every breakdown.
        from kir.decompile.side_contract import (
            SIDE_FAILURE_KINDS, SideFailureReason,
        )
        missing = sorted(
            reason.value for reason in SideFailureReason
            if reason not in SIDE_FAILURE_KINDS)
        self.assertEqual(missing, [])

    def test_a_determination_is_not_counted_as_a_cut(self) -> None:
        """A wall without a curtain wall is not a cut: the stage DID ANSWER for it."""
        from types import SimpleNamespace

        from kir.decompile.side_contract import summarize_side_failures

        summary = summarize_side_failures({
            "curtain": SimpleNamespace(failures=(
                {"wall_id": "1", "reason": "not_curtain"},
                {"wall_id": "2", "reason": "not_curtain"},
                {"wall_id": "3", "reason": "multiple_curtain_grids"},
            )),
        })
        self.assertEqual(summary["side_failures_untyped"], 0)
        # Three receipts — but exactly one of them is a cut.
        self.assertEqual(summary["side_failures_by_stage"]["curtain"], 3)
        self.assertEqual(summary["side_cuts_total"], 1)
        self.assertEqual(
            summary["side_cuts_by_reason"], {"address_ambiguous": 1})
        self.assertEqual(summary["side_determinations_total"], 2)
        self.assertEqual(
            summary["side_determinations_by_reason"],
            {"aspect_not_present": 2})

    def test_receipts_written_before_typing_still_classify(self) -> None:
        """The decompiles already sit on disk; they cannot be re-captured without Revit."""
        from types import SimpleNamespace

        from kir.decompile.side_contract import summarize_side_failures

        summary = summarize_side_failures({
            "sketch": SimpleNamespace(failures=(
                {"element_id": "7", "reason": "dependent Sketch count is 2"},
                {"element_id": "8", "reason": (
                    "exact profile topology unavailable: profile has a "
                    "disjoint/nested exterior that the side schema cannot "
                    "represent")},
            )),
            "group": SimpleNamespace(failures=(
                {"element_id": "9",
                 "reason": "group read failed: InvalidOperationException"},
            )),
        })
        self.assertEqual(summary["side_failures_untyped"], 0)
        self.assertEqual(summary["side_cuts_by_reason"], {
            "dependent_sketch_ambiguous": 1,
            "profile_topology_unsupported": 1,
            "read_failed": 1,
        })

    def test_a_recorded_type_beats_an_inferred_one(self) -> None:
        from types import SimpleNamespace

        from kir.decompile.side_contract import summarize_side_failures

        summary = summarize_side_failures({
            "curtain": SimpleNamespace(failures=(
                {"wall_id": "1", "reason": "not_curtain",
                 "typed_reason": "read_failed"},
            )),
        })
        self.assertEqual(summary["side_cuts_by_reason"], {"read_failed": 1})


class CurtainIndexSchemaCompatTests(unittest.TestCase):
    """Both versions of the index are readable, and both give ONE AND THE SAME reason class.

    /6 differs from /5 exactly by the receipt's dialect: in /5 "wall is not a curtain wall"
    sat as an unnamed row, in /6 it has ``typed_reason`` and
    ``elapsed_ms: null``. An old build would fail on /6 in ``from_dict`` (there
    stood an unconditional ``_nonnegative_int``), and it would fail SILENTLY
    with respect to the version — the version string would remain unchanged. The dialect
    changed, so the version must name it.

    /5 must nonetheless remain readable: the decompile of 13A-RD-AR-K2_v33 (55 293
    elements) was captured with it, and there is nowhere to re-capture it without a live Revit.
    """

    def _envelope(self, version: str, failures: tuple) -> dict:
        return {
            "schema_version": version,
            "curtain_index": {"1": {"curtain_available": False}},
            "failures": list(failures),
        }

    def test_both_the_current_and_the_untyped_schema_are_read(self) -> None:
        from kir.decompile.curtain_extract import (
            CURTAIN_INDEX_SCHEMA_VERSION,
            CURTAIN_INDEX_SCHEMA_VERSION_UNTYPED_RECEIPTS,
            CurtainExtraction,
        )

        self.assertEqual(
            CURTAIN_INDEX_SCHEMA_VERSION, "kir-decompile-curtain-index/6")
        old = self._envelope(
            CURTAIN_INDEX_SCHEMA_VERSION_UNTYPED_RECEIPTS,
            ({"wall_id": "1", "reason": "not_curtain"},))
        new = self._envelope(
            CURTAIN_INDEX_SCHEMA_VERSION,
            ({"wall_id": "1", "reason": "not_curtain",
              "typed_reason": "aspect_not_present", "elapsed_ms": None},))
        for name, envelope in (("/5", old), ("/6", new)):
            with self.subTest(schema=name):
                extraction = CurtainExtraction.from_dict(envelope)
                self.assertEqual(len(extraction.failures), 1)

    def test_both_schemas_classify_the_same_way(self) -> None:
        """Different dialect — one conclusion. Otherwise the version would change MEANING."""
        from types import SimpleNamespace

        from kir.decompile.side_contract import summarize_side_failures

        untyped = summarize_side_failures({"curtain": SimpleNamespace(
            failures=({"wall_id": "1", "reason": "not_curtain"},))})
        typed = summarize_side_failures({"curtain": SimpleNamespace(
            failures=({"wall_id": "1", "reason": "not_curtain",
                       "typed_reason": "aspect_not_present",
                       "elapsed_ms": None},))})
        for summary in (untyped, typed):
            self.assertEqual(summary["side_failures_untyped"], 0)
            self.assertEqual(summary["side_cuts_total"], 0)
            self.assertEqual(
                summary["side_determinations_by_reason"],
                {"aspect_not_present": 1})

    def test_an_unknown_schema_is_still_refused(self) -> None:
        # Compatibility is a LIST, not "we read whatever."
        from kir.decompile.curtain_extract import (
            CurtainExtraction, CurtainPayloadError,
        )

        with self.assertRaisesRegex(
                CurtainPayloadError, "schema_version mismatch"):
            CurtainExtraction.from_dict(
                self._envelope("kir-decompile-curtain-index/999", ()))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
