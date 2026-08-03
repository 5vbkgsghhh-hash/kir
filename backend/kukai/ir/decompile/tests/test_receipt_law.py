"""§18.2 — закон квитанции. Опровергающие тесты (§18.7 п.4).

Замер, из которого закон родился (28.07, SOB6.2_FAS_R23, разбор
``backend/data/decompile/sob62_fas_r23_v2``): боковой стадии
``family_placement`` заказали 1799 элементов, индекс вернул 1557 строк, а про
242 не сказал НИЧЕГО — ни строки, ни отказа. Все 242 оказались
``OST_CurtainWallPanels``, и в лифте они стали атомами с причиной «element is
absent from the family placement side index»: снаружи это выглядит дырой в
возможностях компилятора, хотя на деле экстрактор их просто выбросил (не
``FamilyInstance`` / срез по бюджету). Для сравнения, ``curve``/``curtain``/
``sketch`` в том же прогоне сошлись до элемента: 1178/1178, 1178+983/1178,
55/55.

На момент написания падали:
  * ответ family_placement/group не нёс ключа ``failures`` вообще;
  * эмиттер обрывался по бюджету (``break``) и молча пропускал элемент
    (``continue``/``catch {}``) — без записи об этом;
  * одна нераспарсенная строка размещения роняла ВЕСЬ прогон
    (``from_rows`` — генератор без изоляции);
  * инвариант ``mirrored == hand XOR facing`` убивал прогон, хотя он неверен
    для зеркалирования относительно произвольной плоскости;
  * ``sketch_extract`` шёл тремя полномодельными проходами без бюджета;
  * ``_rows_of`` на неузнанной форме ответа возвращал ``[]`` — пустой индекс
    залипал на диске и переиспользовался resume-логикой;
  * агрегат ``failures`` не читал никто: ни ``run.json``, ни ``status.json``,
    ни паспорт, ни лифт.
"""
from __future__ import annotations

import asyncio
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from kukai.ir.decompile import pipeline as pipe
from kukai.ir.decompile.family_placement_extract import (
    FamilyPlacementExtraction,
    FamilyPlacementPayloadError,
    build_family_placement_extract_cs,
)
from kukai.ir.decompile.group_extract import (
    GroupExtraction,
    build_group_extract_cs,
)
from kukai.ir.decompile.sketch_extract import build_sketch_extract_cs
from kukai.ir.decompile.side_contract import (
    SideFailureReason,
    SideStageContractError,
)
from kukai.ir.decompile.tests.test_pipeline import (
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


# ── ЧАСТЬ 1: общий контракт боковой стадии ──────────────────────────────────


class SideAnswerCarriesFailures(unittest.TestCase):
    """Ответ боковой стадии = rows + failures, ОБА ключа обязательны."""

    def test_family_placement_bundle_carries_a_failures_key(self) -> None:
        extraction = FamilyPlacementExtraction.from_rows([_family_wire_row("3")])
        payload = extraction.to_dict()
        self.assertIn("failures", payload)
        self.assertEqual(payload["failures"], [])
        # Круг замкнут: пустой список переживает запись/чтение.
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
        # Ответ несёт оба ключа.
        self.assertIn('"failures", __fpFailures', body)
        # Ни одного немого выхода: срез по бюджету, нерезолвнутый id, не-
        # FamilyInstance и пойманное исключение — все оставляют строку.
        for token in (
            '"call_budget_exhausted"',
            '"time_budget_exceeded"',
            '"element_unresolved"',
            '"element_kind_mismatch"',
            '"read_failed"',
        ):
            self.assertIn(token, body, token)
        # Пустых `continue` без записи в квитанции не осталось.
        self.assertNotIn("if (__instance == null) continue;", body)

    def test_group_emitter_leaves_a_receipt_for_every_dropped_group(
            self) -> None:
        body = build_group_extract_cs()
        self.assertIn('"failures", __grFailures', body)
        for token in ('"call_budget_exhausted"', '"read_failed"',
                      '"element_kind_mismatch"'):
            self.assertIn(token, body, token)


class BrokenRowIsIsolated(unittest.TestCase):
    """Одна битая строка = один failure, ноль упавших прогонов (M6)."""

    def test_one_unparsable_row_does_not_kill_the_batch(self) -> None:
        broken = _family_wire_row("77")
        del broken["rotation_rad"]  # point_ft без пары — малформед
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
    """Стадия сверяет запрошено vs получено и отказывает типизированно."""

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
        # Индекс витражей называет ключ ``wall_id``. Прямое чтение
        # ``record.element_id`` объявило бы потерянным КАЖДЫЙ успешно
        # прочитанный витраж и уронило бы стадию на первом же таком здании.
        from kukai.ir.decompile.curtain_extract import (
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
                from kukai.ir.decompile.family_placement_extract import (
                    FAMILY_PLACEMENT_EXTRACT_SCHEMA_VERSION,
                )
                if FAMILY_PLACEMENT_EXTRACT_SCHEMA_VERSION in code:
                    self.side_calls.append("family_placement")
                    # Заказано 3001 и 4001 — возвращаем одну строку и ни
                    # одной квитанции: ровно то, что делал живой эмиттер.
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
    """MINOR-10: пустой индекс не смеет залипать на диске молча."""

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

            # Подменяем артефакт пустым индексом — переиспользование обязано
            # заметить расхождение со счётчиком и пересчитать стадию.
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


# ── ЧАСТЬ 3: квитанции читаются ─────────────────────────────────────────────


def _cut_metadata() -> dict[str, Any]:
    return _mini_metadata()


class _CutBridge(FakePipelineBridge):
    """Мост, у которого family_placement режет один id по бюджету."""

    async def _dispatch(self, code: str, *, timeout_ms: int) -> Any:
        from kukai.ir.decompile.family_placement_extract import (
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
    """Агрегат failures доезжает до run.json / status.json / паспорта (M5)."""

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
        from kukai.ir.decompile import lift as lift_mod
        from kukai.ir.decompile.tests.fixtures_decompile import make_element
        from kukai.ir.decompile.schema import L0Document, ProjectInfo

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


# ── ЧАСТЬ 4: бюджет sketch_extract ──────────────────────────────────────────


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
        from kukai.ir.decompile.sketch_extract import (
            SKETCH_EXTRACT_SCHEMA_VERSION,
        )
        from kukai.ir.decompile.tests.fixtures_decompile import make_element

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
    """§18.2 — у КАЖДОЙ квитанции обязана быть причина, и у причины — класс.

    Замер, из которого родилась эта часть закона (29.07, 13A-RD-AR-K2_v33,
    59 этажей, разбор ``backend/data/decompile/k2_ar_rd_v6``, 55 293
    элемента): ``side_failures_untyped`` = 14 569 из 18 023 отказов, то есть
    подавляющее большинство отказов не имело причины вовсе. Из них 14 343
    приходилось на стадию ``curtain``, и это было САМОЕ БОЛЬШОЕ число во всей
    разбивке — по нему стадию и назначали «самой провальной».

    Разбор показал обратное: 14 324 из 14 343 — обычные стены без
    CurtainGrid, и у каждой из них, кроме квитанции, есть полноценная строка
    индекса. Стадия отработала по ним начисто. Настоящих отказов витражей —
    19 (18 неопознанных носителей и один витраж с двумя сетками).

    На момент написания падали оба теста ниже.
    """

    def test_every_reason_is_classified(self) -> None:
        # Новая причина без класса выпала бы разом из обеих сумм — ровно так
        # 14 569 отказов и оказались вне всех разбивок.
        from kukai.ir.decompile.side_contract import (
            SIDE_FAILURE_KINDS, SideFailureReason,
        )
        missing = sorted(
            reason.value for reason in SideFailureReason
            if reason not in SIDE_FAILURE_KINDS)
        self.assertEqual(missing, [])

    def test_a_determination_is_not_counted_as_a_cut(self) -> None:
        """Стена без витража — не срез: по ней стадия ОТВЕТИЛА."""
        from types import SimpleNamespace

        from kukai.ir.decompile.side_contract import summarize_side_failures

        summary = summarize_side_failures({
            "curtain": SimpleNamespace(failures=(
                {"wall_id": "1", "reason": "not_curtain"},
                {"wall_id": "2", "reason": "not_curtain"},
                {"wall_id": "3", "reason": "multiple_curtain_grids"},
            )),
        })
        self.assertEqual(summary["side_failures_untyped"], 0)
        # Три квитанции — но срез из них ровно один.
        self.assertEqual(summary["side_failures_by_stage"]["curtain"], 3)
        self.assertEqual(summary["side_cuts_total"], 1)
        self.assertEqual(
            summary["side_cuts_by_reason"], {"address_ambiguous": 1})
        self.assertEqual(summary["side_determinations_total"], 2)
        self.assertEqual(
            summary["side_determinations_by_reason"],
            {"aspect_not_present": 2})

    def test_receipts_written_before_typing_still_classify(self) -> None:
        """Разборы уже лежат на диске; пере-снять их без Revit нельзя."""
        from types import SimpleNamespace

        from kukai.ir.decompile.side_contract import summarize_side_failures

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

        from kukai.ir.decompile.side_contract import summarize_side_failures

        summary = summarize_side_failures({
            "curtain": SimpleNamespace(failures=(
                {"wall_id": "1", "reason": "not_curtain",
                 "typed_reason": "read_failed"},
            )),
        })
        self.assertEqual(summary["side_cuts_by_reason"], {"read_failed": 1})


class CurtainIndexSchemaCompatTests(unittest.TestCase):
    """Обе версии индекса читаются, и обе дают ОДИН И ТОТ ЖЕ класс причины.

    /6 отличается от /5 ровно диалектом квитанции: в /5 «стена не витражная»
    лежала безымянной строкой, в /6 у неё есть ``typed_reason`` и
    ``elapsed_ms: null``. Старый билд на /6 падал бы в ``from_dict`` (там
    стоял безусловный ``_nonnegative_int``), причём падал бы МОЛЧА
    относительно версии — строка версии осталась бы прежней. Диалект
    изменился, значит версия обязана его назвать.

    /5 при этом обязана читаться дальше: разбор 13A-RD-AR-K2_v33 (55 293
    элемента) снят ею, а пере-снять его без живого Revit неоткуда.
    """

    def _envelope(self, version: str, failures: tuple) -> dict:
        return {
            "schema_version": version,
            "curtain_index": {"1": {"curtain_available": False}},
            "failures": list(failures),
        }

    def test_both_the_current_and_the_untyped_schema_are_read(self) -> None:
        from kukai.ir.decompile.curtain_extract import (
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
        """Разный диалект — один вывод. Иначе версия меняла бы СМЫСЛ."""
        from types import SimpleNamespace

        from kukai.ir.decompile.side_contract import summarize_side_failures

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
        # Совместимость — это СПИСОК, а не «читаем что угодно».
        from kukai.ir.decompile.curtain_extract import (
            CurtainExtraction, CurtainPayloadError,
        )

        with self.assertRaisesRegex(
                CurtainPayloadError, "schema_version mismatch"):
            CurtainExtraction.from_dict(
                self._envelope("kir-decompile-curtain-index/999", ()))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
