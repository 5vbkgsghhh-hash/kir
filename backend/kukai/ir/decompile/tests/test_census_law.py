"""§18.1 — закон переписи. Опровергающие тесты (§18.7 п.3).

Находка M3 аудита 2026-07-28: extract читает ЗАКРЫТУЮ таблицу из 47 категорий
(``extract._CATEGORY_SPECS``), и всё, чего в ней нет — топография, площадка,
паркинг, озеленение, массы, арматура, изоляция труб и воздуховодов, — не даёт
НИ ЭЛЕМЕНТА, НИ СТРОКИ СТАТУСА, НИ ОТКАЗА. Знаменатель любого процента
покрытия был выборкой таблицы, а не документом: «покрытие 93%» описывало то,
что посмотрели, и молчало о том, чего не смотрели вовсе.

На момент написания падали (замерено):

  * ``build_metadata_cs()`` полномодельного прохода не эмитировал вообще;
  * ``L0Document`` поля ``census`` не имел — переписи негде было ехать;
  * ``run.json``/``passport.json``/``passport.md`` о непрочитанном молчали;
  * документ с категорией вне таблицы давал тихие 100% (``unscanned == 0``).
"""
from __future__ import annotations

import asyncio
import copy
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from kukai.ir.decompile import extract as ex
from kukai.ir.decompile import pipeline as pipe
from kukai.ir.decompile.census import (
    CensusBalanceError,
    UnscannedReason,
    reconcile_census,
)
from kukai.ir.decompile.schema import (
    CategoryState,
    CategoryStatus,
    CensusEntry,
    GridInfo,
    L0Document,
    L0SchemaError,
    LevelInfo,
    ProjectInfo,
)
from kukai.ir.decompile.tests.fixtures_decompile import make_element
from kukai.ir.decompile.tests.test_pipeline import (
    FakePipelineBridge,
    _mini_elements,
    _mini_metadata,
)
from kukai.security.validation import validate_code_safety


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _document(
    *,
    census: tuple[CensusEntry, ...] = (),
    elements: tuple = (),
    category_status: tuple[CategoryStatus, ...] = (),
) -> L0Document:
    return L0Document(
        doc_name="census-doc",
        revit_version="2026",
        units="mm",
        change_stamp="census-v1",
        levels=(LevelInfo(id="100", name="Этаж 1", elevation_mm=0.0),),
        grids=(GridInfo(id="7001", name="1", p0_mm=[0.0, 0.0, 0.0],
                        p1_mm=[0.0, 9000.0, 0.0]),),
        rooms=(),
        project_info=ProjectInfo(name="П", address="а",
                                 building_type_hint=None),
        elements=elements,
        category_status=category_status,
        census=census,
    )


def _l0_element(category: str, element_id: int, ordinal: int = 0):
    from kukai.ir.decompile.geometry_store import parse_geometry
    from kukai.ir.decompile.schema import L0Element

    row = make_element(category, element_id, ordinal=ordinal)
    row.update(parse_geometry(row).to_element_fields())
    return L0Element.from_dict(row)


class TheCensusIsMeasuredInCSharp(unittest.TestCase):
    """1a — один дешёвый полномодельный проход, без геометрии и параметров."""

    def test_metadata_body_emits_a_whole_document_census(self) -> None:
        body = ex.build_metadata_cs()
        self.assertIn("WhereElementIsNotElementType()", body)
        self.assertIn("census", body)
        self.assertIn("BuiltInCategory", body)
        # §18.5 — ключ переписи — BuiltInCategory/id, локализованное имя лишь
        # справочная колонка.
        self.assertIn("Enum.GetName", body)
        self.assertIn(ex.NO_CATEGORY_KEY, body)
        # Перепись не смеет тащить ни геометрию, ни параметры.
        self.assertNotIn("__PutGeometry", body)
        self.assertNotIn("get_Geometry", body)

    def test_census_body_keeps_the_frozen_emission_invariants(self) -> None:
        body = ex.build_metadata_cs()
        self.assertIsNone(validate_code_safety(body))
        self.assertNotIn("IntegerValue", body)
        self.assertNotIn("Transaction", body)
        self.assertNotIn("304.8", body)

    def test_census_is_computed_once_not_per_room_page(self) -> None:
        """Перепись — на ПЕРВОЙ странице комнат; иначе платим за неё N раз."""
        first = ex.build_metadata_cs()
        later = ex.build_metadata_cs(after_room_id=8001)
        self.assertIn("-9223372036854775808L", first)
        self.assertIn("long __RoomAfter = 8001L;", later)


class TheCensusSurvivesTheHeader(unittest.TestCase):
    """1a — round-trip: metadata_dict + оба конструктора (образец §18.4)."""

    def test_metadata_dict_carries_the_census(self) -> None:
        document = _document(census=(
            CensusEntry("OST_Walls", "Стены", 12),
            CensusEntry("OST_Topography", "Топография", 3),
        ))
        header = document.metadata_dict()
        self.assertEqual(len(header["census"]), 2)
        self.assertEqual(header["census"][0]["key"], "OST_Walls")
        self.assertEqual(header["census"][0]["count"], 12)
        restored = L0Document.from_dict({
            **header, "elements": [], "category_status": [], "links": []})
        self.assertEqual(restored.census, document.census)

    def test_header_write_read_and_materialize_preserve_it(self) -> None:
        document = _document(census=(
            CensusEntry("OST_Walls", "Стены", 2),
            CensusEntry("OST_Topography", "Топография", 40),
        ))
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "L0.jsonl"
            with path.open("wb") as handle:
                ex._write_record(handle, {
                    "record": "header",
                    "schema_version": ex.L0_SCHEMA_VERSION,
                    "document": document.metadata_dict(),
                })
                for category in ex.EXTRACT_CATEGORIES:
                    ex._write_record(handle, {
                        "record": "category_status",
                        "status": {
                            "category": category, "state": "complete",
                            "extracted_count": 0, "expected_count": 0,
                            "error": None,
                        },
                    })
                ex._write_record(handle, {
                    "record": "footer", "stream_complete": True,
                    "element_count": 0, "link_count": 0,
                    "category_count": len(ex.EXTRACT_CATEGORIES),
                })
            self.assertEqual(ex._read_header(path).census, document.census)
            self.assertEqual(
                ex.L0JSONLReader(path).materialize().census, document.census)

    def test_absent_census_is_absence_not_zero(self) -> None:
        self.assertEqual(_document().census, ())
        self.assertFalse(reconcile_census(_document()).present)

    def test_a_duplicated_census_key_is_refused(self) -> None:
        with self.assertRaises(L0SchemaError):
            _document(census=(
                CensusEntry("OST_Walls", "Стены", 1),
                CensusEntry("OST_Walls", "Стены", 2),
            ))

    def test_a_negative_count_is_refused(self) -> None:
        with self.assertRaises(L0SchemaError):
            CensusEntry("OST_Walls", "Стены", -1)


class TheBridgeContractIsChecked(unittest.TestCase):
    """1b — |перепись| == сумме её строк, иначе типизированный отказ."""

    def test_census_total_must_equal_the_row_sum(self) -> None:
        payload = copy.deepcopy(_mini_metadata())
        payload["census"] = [{"key": "OST_Walls", "name": "Стены", "count": 2}]
        payload["census_total"] = 7
        with self.assertRaises(ex.ExtractionProtocolError):
            ex._parse_metadata(payload, "stamp")

    def test_a_census_without_its_total_is_refused(self) -> None:
        payload = copy.deepcopy(_mini_metadata())
        payload["census"] = [{"key": "OST_Walls", "name": "Стены", "count": 2}]
        with self.assertRaises(ex.ExtractionProtocolError):
            ex._parse_metadata(payload, "stamp")

    def test_no_census_at_all_still_parses(self) -> None:
        document = ex._parse_metadata(copy.deepcopy(_mini_metadata()), "stamp")
        self.assertEqual(document.census, ())


class TheIdentityBalances(unittest.TestCase):
    """1b — тождество: перепись = извлечено + не читалось, по причинам."""

    def test_a_category_outside_the_table_is_counted_and_typed(self) -> None:
        elements = (_l0_element("OST_Walls", 1001),)
        balance = reconcile_census(_document(
            elements=elements,
            census=(
                CensusEntry("OST_Walls", "Стены", 1),
                CensusEntry("OST_Topography", "Топография", 40),
                CensusEntry("no_category", "", 5),
            )))
        self.assertTrue(balance.present)
        self.assertEqual(balance.census_total, 46)
        self.assertEqual(balance.extracted, 1)
        self.assertEqual(balance.unscanned, 45)
        self.assertEqual(balance.census_total,
                         balance.extracted + balance.unscanned)
        self.assertTrue(balance.balanced)
        reasons = {row.category: row.reason for row in balance.rows}
        self.assertEqual(reasons["OST_Topography"],
                         UnscannedReason.CATEGORY_OUTSIDE_TABLE)
        self.assertEqual(reasons["no_category"],
                         UnscannedReason.CATEGORY_OUTSIDE_TABLE)
        self.assertEqual(balance.categories_in_model, 3)
        self.assertEqual(balance.categories_scanned, 1)

    def test_a_partial_category_is_page_refused_not_outside_table(self) -> None:
        balance = reconcile_census(_document(
            elements=(),
            census=(CensusEntry("OST_Walls", "Стены", 9),),
            category_status=(CategoryStatus(
                category="OST_Walls", state=CategoryState.PARTIAL,
                extracted_count=0, expected_count=9, error="timeout"),)))
        self.assertEqual(balance.rows[0].reason, UnscannedReason.PAGE_REFUSED)

    def test_a_short_read_of_a_known_category_is_typed_too(self) -> None:
        balance = reconcile_census(_document(
            elements=(_l0_element("OST_Walls", 1001),),
            census=(CensusEntry("OST_Walls", "Стены", 9),),
            category_status=(CategoryStatus(
                category="OST_Walls", state=CategoryState.COMPLETE,
                extracted_count=1, expected_count=1, error=None),)))
        self.assertEqual(balance.unscanned, 8)
        self.assertEqual(
            balance.rows[0].reason, UnscannedReason.CATEGORY_SHORT_READ)

    def test_extracting_more_than_exists_is_a_typed_run_error(self) -> None:
        """ПЕРЕБОР — не «не читалось», а опровергнутое утверждение."""
        balance = reconcile_census(_document(
            elements=(_l0_element("OST_Walls", 1001),
                      _l0_element("OST_Walls", 1002, ordinal=1)),
            census=(CensusEntry("OST_Walls", "Стены", 1),)))
        self.assertFalse(balance.balanced)
        self.assertEqual(
            balance.errors[0]["code"],
            CensusBalanceError.EXTRACTED_EXCEEDS_CENSUS.value)

    def test_a_category_absent_from_the_census_is_a_typed_error(self) -> None:
        balance = reconcile_census(_document(
            elements=(_l0_element("OST_Walls", 1001),),
            census=(CensusEntry("OST_Floors", "Перекрытия", 3),)))
        self.assertFalse(balance.balanced)
        self.assertEqual(
            balance.errors[0]["code"],
            CensusBalanceError.EXTRACTED_EXCEEDS_CENSUS.value)

    def test_both_denominators_are_available(self) -> None:
        balance = reconcile_census(_document(
            elements=(_l0_element("OST_Walls", 1001),),
            census=(CensusEntry("OST_Walls", "Стены", 1),
                    CensusEntry("OST_Topography", "Топография", 3),)))
        self.assertEqual(balance.extracted_pct(1), 100.0)
        self.assertEqual(balance.document_pct(1), 25.0)

    def test_summary_line_says_what_was_not_read(self) -> None:
        balance = reconcile_census(_document(
            elements=(_l0_element("OST_Walls", 1001),),
            census=(CensusEntry("OST_Walls", "Стены", 1),
                    CensusEntry("OST_Topography", "Топография", 40))))
        line = balance.summary_ru()
        self.assertIn("категорий в модели 2", line)
        self.assertIn("читается 1", line)
        self.assertIn("не читалось 40", line)
        self.assertIn("OST_Topography", line)

    def test_missing_census_degrades_honestly_in_the_summary(self) -> None:
        self.assertIn("переписи нет", reconcile_census(_document()).summary_ru())


def _census_payload(extra: dict[str, int] | None = None) -> dict[str, Any]:
    """Перепись, точно совпадающая с мини-моделью, плюс что попросили сверх."""
    counts: dict[str, int] = {
        category: len(rows) for category, rows in _mini_elements().items()}
    counts.update(extra or {})
    return {
        "census": [
            {"key": key, "name": key, "count": count}
            for key, count in sorted(counts.items())
        ],
        "census_total": sum(counts.values()),
    }


def _metadata_with_census(extra: dict[str, int] | None = None) -> dict[str, Any]:
    meta = copy.deepcopy(_mini_metadata())
    meta.update(_census_payload(extra))
    return meta


class ThePipelineReportsTheCensus(unittest.TestCase):
    """1c/1e — CI-фикстура: категория вне таблицы ⇒ unscanned > 0."""

    def test_outside_table_category_reaches_run_json_and_passport(self) -> None:
        with TemporaryDirectory() as tmp:
            bridge = FakePipelineBridge(metadata=_metadata_with_census(
                {"OST_Topography": 40, "no_category": 7}))
            result = _run(pipe.run_decompile(
                bridge, out_dir=tmp, change_stamp="pipeline-mini-v1"))
            self.assertTrue(result.ok, msg=result.to_dict())
            out = Path(tmp)

            run = json.loads((out / "run.json").read_text("utf-8"))
            self.assertTrue(run["census_present"])
            self.assertEqual(run["census_total"], 52)
            self.assertEqual(run["extracted"], 5)
            self.assertEqual(run["unscanned_elements"], 47)
            self.assertEqual(
                run["census_total"],
                run["extracted"] + run["unscanned_elements"])
            self.assertIn("ops_lifted", run)
            self.assertIn("atoms", run)
            top = {row["category"]: row
                   for row in run["unscanned_by_category"]["top"]}
            self.assertEqual(top["OST_Topography"]["unscanned"], 40)
            self.assertEqual(top["OST_Topography"]["reason"],
                             UnscannedReason.CATEGORY_OUTSIDE_TABLE.value)

            passport = json.loads((out / "passport.json").read_text("utf-8"))
            stats = passport["stats"]
            self.assertEqual(stats["census_total"], 52)
            self.assertEqual(stats["unscanned_elements"], 47)
            self.assertIn("unscanned_by_category", stats)

            markdown = (out / "passport.md").read_text("utf-8")
            self.assertIn("категорий в модели", markdown)
            self.assertIn("не читалось 47 элементов", markdown)
            # Строка переписи обязана стоять ПЕРЕД процентами.
            self.assertLess(markdown.index("категорий в модели"),
                            markdown.index("## Stats"))

    def test_status_json_carries_the_census_during_the_run(self) -> None:
        with TemporaryDirectory() as tmp:
            bridge = FakePipelineBridge(
                metadata=_metadata_with_census({"OST_Topography": 40}))
            result = _run(pipe.run_decompile(
                bridge, out_dir=tmp, change_stamp="pipeline-mini-v1"))
            self.assertTrue(result.ok, msg=result.to_dict())
            status = json.loads((Path(tmp) / "status.json").read_text("utf-8"))
            self.assertEqual(status["unscanned_elements"], 40)
            self.assertEqual(status["census_total"], 45)

    def test_a_run_without_a_census_degrades_but_does_not_lie(self) -> None:
        with TemporaryDirectory() as tmp:
            result = _run(pipe.run_decompile(
                FakePipelineBridge(), out_dir=tmp,
                change_stamp="pipeline-mini-v1"))
            self.assertTrue(result.ok, msg=result.to_dict())
            run = json.loads((Path(tmp) / "run.json").read_text("utf-8"))
            self.assertFalse(run["census_present"])
            markdown = (Path(tmp) / "passport.md").read_text("utf-8")
            self.assertIn("переписи нет", markdown)

    def test_a_broken_balance_fails_the_run_typed(self) -> None:
        """§18.1: расхождение тождества — ошибка прогона, не предупреждение."""
        with TemporaryDirectory() as tmp:
            # Перепись знает про одну стену, а извлечение вернёт две.
            meta = copy.deepcopy(_mini_metadata())
            meta["census"] = [
                {"key": "OST_Walls", "name": "Стены", "count": 1}]
            meta["census_total"] = 1
            result = _run(pipe.run_decompile(
                FakePipelineBridge(metadata=meta), out_dir=tmp,
                change_stamp="pipeline-mini-v1"))
            self.assertFalse(result.ok)
            self.assertEqual(
                (result.error or {}).get("code"), "census_balance_mismatch")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
