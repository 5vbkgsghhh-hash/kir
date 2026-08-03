"""§18.4 — закон заражения частичного чтения. Опровергающие тесты (§18.7 п.2).

Замер, из которого закон родился: документ ЭОМ открыли с 17 закрытыми
рабочими наборами из 18 — коллекторы честно вернули 11 элементов вместо 2016,
все статусы категорий `complete`, паспорт отрапортовал высокое покрытие. C#
рабочие наборы МЕРЯЕТ (`build_metadata_cs`), `_parse_metadata` их РАЗБИРАЕТ,
`L0Document.is_partial_read` их ЧИТАЕТ — а заголовок L0 их терял:
`metadata_dict()` не писал, `_new_metadata` и `L0JSONLReader.materialize()` не
передавали. Ни один производный артефакт не мог сказать, что читалась часть
модели.

На момент написания падали:
  * round-trip заголовка (write→read) — поля не переживали запись;
  * materialize — терял поля даже при их наличии в заголовке;
  * pipeline — ни run.json, ни status.json, ни паспорт не несли пометку.
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
from kukai.ir.decompile.schema import (
    GridInfo,
    L0Document,
    LevelInfo,
    ProjectInfo,
    RoomInfo,
)
from kukai.ir.decompile.tests.test_pipeline import (
    FakePipelineBridge,
    _mini_metadata,
)


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


_WORKSETS = [
    {"id": 0, "name": "Рабочий набор 1", "open": True},
    {"id": 1, "name": "ЭОМ_силовое", "open": False},
    {"id": 2, "name": "ЭОМ_освещение", "open": False},
]


def _partial_document() -> L0Document:
    return L0Document(
        doc_name="Централка",
        revit_version="2026",
        units="mm",
        change_stamp="partial-v1",
        levels=(LevelInfo(id="100", name="Этаж 1", elevation_mm=0.0),),
        grids=(GridInfo(id="7001", name="1", p0_mm=[0.0, 0.0, 0.0],
                        p1_mm=[0.0, 9000.0, 0.0]),),
        rooms=(),
        project_info=ProjectInfo(
            name="Проект", address="а", building_type_hint=None),
        worksharing=True,
        worksets=tuple(_WORKSETS),
        worksets_closed=2,
    )


class L0HeaderRoundTrip(unittest.TestCase):
    """Заголовок L0 обязан переносить состояние рабочих наборов."""

    def test_metadata_dict_carries_worksharing_state(self) -> None:
        header = _partial_document().metadata_dict()
        self.assertTrue(header["worksharing"])
        self.assertEqual(header["worksets_closed"], 2)
        self.assertEqual(len(header["worksets"]), 3)

    def test_header_write_read_preserves_is_partial_read(self) -> None:
        document = _partial_document()
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
            restored = ex._read_header(path)
            self.assertTrue(restored.worksharing)
            self.assertEqual(restored.worksets_closed, 2)
            self.assertEqual(len(restored.worksets), 3)
            self.assertTrue(restored.is_partial_read)
            materialized = ex.L0JSONLReader(path).materialize()
            self.assertTrue(materialized.worksharing)
            self.assertEqual(materialized.worksets_closed, 2)
            self.assertTrue(materialized.is_partial_read)

    def test_full_read_stays_unmarked(self) -> None:
        from dataclasses import replace
        document = replace(
            _partial_document(), worksets_closed=0,
            worksets=tuple(_WORKSETS[:1]))
        self.assertFalse(document.is_partial_read)
        header = document.metadata_dict()
        self.assertFalse(header["worksharing"] and header["worksets_closed"])


def _partial_metadata_payload() -> dict[str, Any]:
    meta = copy.deepcopy(_mini_metadata())
    meta["worksharing"] = True
    meta["worksets"] = copy.deepcopy(_WORKSETS)
    meta["worksets_closed"] = 2
    return meta


class PipelineRaisesTheSignal(unittest.TestCase):
    """run.json / status.json / паспорт несут пометку частичного чтения."""

    def test_partial_read_reaches_run_json_status_and_passport(self) -> None:
        with TemporaryDirectory() as tmp:
            bridge = FakePipelineBridge(metadata=_partial_metadata_payload())
            result = _run(pipe.run_decompile(
                bridge, out_dir=tmp, change_stamp="pipeline-mini-v1"))
            self.assertTrue(result.ok, msg=result.to_dict())
            self.assertTrue(result.is_partial_read)
            out = Path(tmp)
            run = json.loads((out / "run.json").read_text("utf-8"))
            self.assertTrue(run["is_partial_read"])
            self.assertEqual(run["worksets_closed"], 2)
            status = json.loads((out / "status.json").read_text("utf-8"))
            self.assertTrue(status["is_partial_read"])
            passport = json.loads((out / "passport.json").read_text("utf-8"))
            self.assertTrue(passport["stats"]["is_partial_read"])
            self.assertEqual(passport["stats"]["worksets_closed"], 2)
            # §18.4: процент печатается только вместе с пометкой.
            markdown = (out / "passport.md").read_text("utf-8")
            self.assertIn("рабочих наборов закрыто", markdown)

    def test_complete_read_carries_a_false_flag_not_an_absence(self) -> None:
        with TemporaryDirectory() as tmp:
            result = _run(pipe.run_decompile(
                FakePipelineBridge(), out_dir=tmp,
                change_stamp="pipeline-mini-v1"))
            self.assertTrue(result.ok, msg=result.to_dict())
            self.assertFalse(result.is_partial_read)
            run = json.loads((Path(tmp) / "run.json").read_text("utf-8"))
            self.assertIn("is_partial_read", run)
            self.assertFalse(run["is_partial_read"])
            passport = json.loads(
                (Path(tmp) / "passport.json").read_text("utf-8"))
            self.assertFalse(passport["stats"]["is_partial_read"])
            self.assertNotIn(
                "рабочих наборов закрыто",
                (Path(tmp) / "passport.md").read_text("utf-8"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
