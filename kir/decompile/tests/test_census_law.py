"""§18.1 — the census law. Refuting tests (§18.7 clause 3).

Audit finding M3, 2026-07-28: extract reads a CLOSED table of 47
categories (``extract._CATEGORY_SPECS``), and everything absent from it —
topography, site, parking, planting, masses, rebar, pipe and duct
insulation — yields NEITHER AN ELEMENT, NOR A STATUS ROW, NOR A REFUSAL.
The denominator of any coverage percentage was a sample of the table, not
of the document: "93% coverage" described what was looked at, and stayed
silent about what was never looked at at all.

At the time of writing, the following were failing (measured):

  * ``build_metadata_cs()`` did not emit a full-model pass at all;
  * ``L0Document`` had no ``census`` field — there was nowhere for the
    census to go;
  * ``run.json``/``passport.json``/``passport.md`` said nothing about the
    unread;
  * a document with a category outside the table gave a silent 100%
    (``unscanned == 0``).
"""
from __future__ import annotations

import asyncio
import copy
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from kir.decompile import extract as ex
from kir.decompile import pipeline as pipe
from kir.decompile.census import (
    CensusBalanceError,
    UnscannedReason,
    reconcile_census,
)
from kir.decompile.schema import (
    CategoryState,
    CategoryStatus,
    CensusEntry,
    GridInfo,
    L0Document,
    L0SchemaError,
    LevelInfo,
    ProjectInfo,
)
from kir.decompile.tests.fixtures_decompile import make_element
from kir.decompile.tests.test_pipeline import (
    FakePipelineBridge,
    _mini_elements,
    _mini_metadata,
)
from kir.code_safety import validate_code_safety


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
    from kir.decompile.geometry_store import parse_geometry
    from kir.decompile.schema import L0Element

    row = make_element(category, element_id, ordinal=ordinal)
    row.update(parse_geometry(row).to_element_fields())
    return L0Element.from_dict(row)


#: 🔴 THE "OUTSIDE THE TABLE" CATEGORY IS SELECTED, NOT HARDCODED BY NAME.
#:
#: `OST_Topography` used to stand here — a real name, taken as an EXAMPLE
#: of the class "a category outside the extraction table." On 04.09.2026
#: a wave added topography to the table, and three tests in this file
#: turned red WITHOUT FINDING A SINGLE DEFECT: the pin had frozen on one
#: specific instance of the class, while what it was meant to check was
#: the class.
#:
#: Now the name is SELECTED from candidates by the very property it is
#: needed for here, and the premise is checked right there. The next
#: wave, having added one candidate to the table, will simply take the
#: next one; having exhausted them all, it will turn red with
#: instructions on what to do, not with a riddle.
#:
#: The names are checked by an oracle against the metadata of six
#: RevitAPI.dll builds: all four exist, 6/6.
_OUTSIDE_CANDIDATES = ("OST_Planting", "OST_Parking", "OST_Entourage",
                       "OST_Site")
OUTSIDE_TABLE = next(
    (name for name in _OUTSIDE_CANDIDATES if name not in ex.EXTRACT_CATEGORIES),
    "")
OUTSIDE_TABLE_RU = "Вне таблицы"
if not OUTSIDE_TABLE:
    raise RuntimeError(
        "все кандидаты на «категорию вне таблицы» заведены в съём: "
        f"{_OUTSIDE_CANDIDATES}. Добавь в список ещё одно имя, СВЕРИВ его "
        "оракулом /opt/kir-audit/api_name_oracle.py — тест проверяет класс, "
        "а не конкретную категорию")


class TheCensusIsMeasuredInCSharp(unittest.TestCase):
    """1a — one cheap full-model pass, without geometry or parameters."""

    def test_metadata_body_emits_a_whole_document_census(self) -> None:
        body = ex.build_metadata_cs()
        self.assertIn("WhereElementIsNotElementType()", body)
        self.assertIn("census", body)
        self.assertIn("BuiltInCategory", body)
        # §18.5 — the census key is BuiltInCategory/id; the localized name
        # is only a reference column.
        self.assertIn("Enum.GetName", body)
        self.assertIn(ex.NO_CATEGORY_KEY, body)
        # The census must not drag along either geometry or parameters.
        self.assertNotIn("__PutGeometry", body)
        self.assertNotIn("get_Geometry", body)

    def test_census_body_keeps_the_frozen_emission_invariants(self) -> None:
        body = ex.build_metadata_cs()
        self.assertIsNone(validate_code_safety(body))
        self.assertNotIn("IntegerValue", body)
        self.assertNotIn("Transaction", body)
        self.assertNotIn("304.8", body)

    def test_census_is_computed_once_not_per_room_page(self) -> None:
        """The census is on the FIRST page of rooms — otherwise we pay for
        it N times over."""
        first = ex.build_metadata_cs()
        later = ex.build_metadata_cs(after_room_id=8001)
        self.assertIn("-9223372036854775808L", first)
        self.assertIn("long __RoomAfter = 8001L;", later)


class TheCensusSurvivesTheHeader(unittest.TestCase):
    """1a — round-trip: metadata_dict + both constructors (sample §18.4)."""

    def test_metadata_dict_carries_the_census(self) -> None:
        document = _document(census=(
            CensusEntry("OST_Walls", "Стены", 12),
            CensusEntry(OUTSIDE_TABLE, OUTSIDE_TABLE_RU, 3),
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
            CensusEntry(OUTSIDE_TABLE, OUTSIDE_TABLE_RU, 40),
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
    """1b — |census| == the sum of its rows, otherwise a typed refusal."""

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
    """1b — an identity: census = extracted + not-read, broken down by
    reason."""

    def test_a_category_outside_the_table_is_counted_and_typed(self) -> None:
        elements = (_l0_element("OST_Walls", 1001),)
        balance = reconcile_census(_document(
            elements=elements,
            census=(
                CensusEntry("OST_Walls", "Стены", 1),
                CensusEntry(OUTSIDE_TABLE, OUTSIDE_TABLE_RU, 40),
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
        self.assertEqual(reasons[OUTSIDE_TABLE],
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
        """OVERCOUNT is not "not read," it is a refuted assertion."""
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
                    CensusEntry(OUTSIDE_TABLE, OUTSIDE_TABLE_RU, 3),)))
        self.assertEqual(balance.extracted_pct(1), 100.0)
        self.assertEqual(balance.document_pct(1), 25.0)

    def test_summary_line_says_what_was_not_read(self) -> None:
        balance = reconcile_census(_document(
            elements=(_l0_element("OST_Walls", 1001),),
            census=(CensusEntry("OST_Walls", "Стены", 1),
                    CensusEntry(OUTSIDE_TABLE, OUTSIDE_TABLE_RU, 40))))
        line = balance.summary_ru()
        self.assertIn("категорий в модели 2", line)
        self.assertIn("читается 1", line)
        self.assertIn("не читалось 40", line)
        self.assertIn(OUTSIDE_TABLE, line)

    def test_missing_census_degrades_honestly_in_the_summary(self) -> None:
        self.assertIn("переписи нет", reconcile_census(_document()).summary_ru())


def _census_payload(extra: dict[str, int] | None = None) -> dict[str, Any]:
    """A census that matches a mini-model exactly, plus whatever extra was
    requested."""
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
    """1c/1e — CI fixture: a category outside the table ⇒ unscanned > 0."""

    def test_outside_table_category_reaches_run_json_and_passport(self) -> None:
        with TemporaryDirectory() as tmp:
            bridge = FakePipelineBridge(metadata=_metadata_with_census(
                {OUTSIDE_TABLE: 40, "no_category": 7}))
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
            self.assertEqual(top[OUTSIDE_TABLE]["unscanned"], 40)
            self.assertEqual(top[OUTSIDE_TABLE]["reason"],
                             UnscannedReason.CATEGORY_OUTSIDE_TABLE.value)

            passport = json.loads((out / "passport.json").read_text("utf-8"))
            stats = passport["stats"]
            self.assertEqual(stats["census_total"], 52)
            self.assertEqual(stats["unscanned_elements"], 47)
            self.assertIn("unscanned_by_category", stats)

            markdown = (out / "passport.md").read_text("utf-8")
            self.assertIn("категорий в модели", markdown)
            self.assertIn("не читалось 47 элементов", markdown)
            # The census row must come BEFORE the percentages.
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
        """§18.1: a discrepancy in the identity is a run error, not a
        warning."""
        with TemporaryDirectory() as tmp:
            # The census knows of one wall, while the extraction will
            # return two.
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


class ПропущенныйРазборЕдетВОтчёт(unittest.TestCase):
    """🔴 A denominator that silently shrank from a missing source.

    `census()` returns `None` for "no L0.jsonl" — a correct answer; the
    census must not be dropped over one run. But the omission was visible
    ONLY as text and ONLY in stderr: `--json` returned an array of three
    decompiles where ten had been asked for, and "3 censused" became
    indistinguishable from "10 runs, seven with no data." Shares,
    meanwhile, are computed against the SMALLER denominator, meaning they
    ride upward exactly because a source was not found.

    A pair of controls: it can name the omission, and it can NOT name one
    when there isn't any.
    """

    def _run(self, root: Path, names: list[str]) -> dict:
        import io, contextlib
        from kir.decompile import axes_census as A
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            A.main(["--root", str(root), "--json", *names])
        return json.loads(buf.getvalue())

    def test_a_snapshot_without_l0_is_named_not_dropped(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "пусто").mkdir()
            out = self._run(root, ["пусто"])
            self.assertEqual(out["asked"], 1)
            self.assertEqual(out["snapshots"], [],
                             "разбор без L0 в перепись входить не должен")
            self.assertEqual(len(out["skipped"]), 1,
                             "...но обязан быть НАЗВАН, а не исчезнуть")
            self.assertIn("L0.jsonl", out["skipped"][0]["why"])
            self.assertEqual(out["skipped"][0]["snapshot"], "пусто")

    def test_a_snapshot_with_l0_is_not_reported_skipped(self) -> None:
        """A positive control: the list of omissions is not padded for no
        reason.

        Without this half, the assertion degenerates: an instrument that
        always declares an omission would pass the check above and mean
        nothing.
        """
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            good = root / "есть"
            good.mkdir()
            (good / "L0.jsonl").write_text(
                json.dumps({"record": "header",
                            "document": {"doc_name": "проба"}},
                           ensure_ascii=False) + "\n",
                encoding="utf-8")
            out = self._run(root, ["есть"])
            self.assertEqual(out["asked"], 1)
            self.assertEqual(out["skipped"], [],
                             "разбор с L0 пропуском объявлять нельзя")
            self.assertEqual(len(out["snapshots"]), 1)


class ПропавшаяСтрокаОтчётаТожеТишина(unittest.TestCase):
    """🔴 `verify` was vocal about absence; `tree_kinds` stayed silent.

    Both functions return `None` for a missing file, and that is correct:
    the census must still come together even over an incomplete decompile.
    But they printed it differently: `verify.json нет — прогон не дошёл до
    сверки» against a MISSING ROW. The reader saw a decompile with no L3
    node kinds and could not tell "there is no tree" from "there is a
    tree, no kinds were found in it."

    A missing report row is the same silence as a missing number.
    """

    def test_a_missing_artifact_gets_a_note(self) -> None:
        from kir.decompile.axes_census import artifact_absent_note
        with TemporaryDirectory() as tmp:
            d = Path(tmp)
            note = artifact_absent_note(d, "tree.json")
            self.assertIsNotNone(note)
            self.assertIn("tree.json", note, "причина обязана назвать ФАЙЛ")
            self.assertIn("не читали", note,
                          "и сказать, чем пустота НЕ является")

    def test_a_present_artifact_stays_silent(self) -> None:
        """A positive control: an instrument that always complains is not
        guarding anything."""
        from kir.decompile.axes_census import artifact_absent_note
        with TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "tree.json").write_text("{}", encoding="utf-8")
            self.assertIsNone(artifact_absent_note(d, "tree.json"))

    def test_both_artifacts_share_one_answer(self) -> None:
        """One helper for two artifacts — matched by FILE NAME, not by
        input: two similar-looking answers would drift apart, and one of
        them would go silent again."""
        from kir.decompile.axes_census import artifact_absent_note
        with TemporaryDirectory() as tmp:
            d = Path(tmp)
            for name in ("tree.json", "verify.json"):
                note = artifact_absent_note(d, name)
                self.assertIsNotNone(note)
                self.assertIn(name, note)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
