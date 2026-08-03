"""Стадия марок ЧЕРЕЗ ВЕСЬ КОНВЕЙЕР, а не только по частям.

Волна оформления 30.07 прошла все свои тридцать тестов, её C# отработал на
мосту идеально — и полный прогон умер через полторы минуты на стыке
(``side_stage_count_mismatch``). Дефект был не в стадии и не в C#, а в том,
чего ни один из тридцати тестов не касался: в ПРОВОДКЕ.

Здесь проверяется именно она: L0 -> запрос id -> ответ моста ->
``tag.index.json`` -> лифт -> ``create_tag``. И заодно — единственное, что у
этой стадии есть сверх прочих: её C# ЗАВИСИТ ОТ ВЕРСИИ прочитанного
документа, а версия становится известна только после чтения.
"""
from __future__ import annotations

import asyncio
import copy
import json
import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from kukai.ir.decompile import pipeline as pipe
from kukai.ir.decompile.tag_extract import TAG_EXTRACT_SCHEMA_VERSION
from kukai.ir.decompile.tests.fixtures_decompile import (
    make_element,
    project1_metadata,
)
from kukai.ir.decompile.tests.test_pipeline import FakePipelineBridge


#: Стадия марок страничная и перечисляет id как ``new List<string> { ... }``
#: — так же, как оформление и системы, и НЕ так, как ``new string[] { ... }``
#: у первых стадий. Свой съёмщик здесь стоит именно поэтому: чужой вернул бы
#: пустой список, фейковый мост честно ответил бы «ни одной строки», и §18.2
#: уронил бы прогон — то есть тест мерил бы форму литерала, а не проводку.
def _requested_ids(code: str) -> list[str]:
    match = re.search(r"new List<string> \{([^}]*)\}", code)
    if match is None:
        return []
    return re.findall(r'"([^"]+)"', match.group(1))


WALL_ID = "1001"
TAG_ID = "5001"


def _elements() -> dict[str, list[dict[str, Any]]]:
    return {
        "OST_Walls": [
            make_element("OST_Walls", 1001, ordinal=0),
            make_element("OST_Walls", 1002, ordinal=1),
        ],
        "OST_WallTags": [make_element("OST_WallTags", 5001, ordinal=0)],
    }


def _metadata(revit_version: str = "2026") -> dict[str, Any]:
    meta = copy.deepcopy(project1_metadata())
    meta["doc_name"] = "pipeline-tag"
    meta["change_stamp"] = "pipeline-tag-v1"
    meta["revit_version"] = revit_version
    return meta


class TagBridge(FakePipelineBridge):
    """Фейковый мост, умеющий отвечать стадии марок.

    ``readable`` = False моделирует ЧЕСТНУЮ квитанцию: марка на элементе
    связанного файла. Прогон обязан остаться живым, а марка — атомом.
    """

    def __init__(self, *, revit_version: str = "2026",
                 readable: bool = True) -> None:
        super().__init__(elements=_elements(),
                         metadata=_metadata(revit_version))
        self.readable = readable
        self.tag_bodies: list[str] = []

    async def _dispatch(self, code: str, *, timeout_ms: int) -> dict[str, Any]:
        if TAG_EXTRACT_SCHEMA_VERSION in code:
            self.side_calls.append("tag")
            self.tag_bodies.append(code)
            requested = _requested_ids(code)
            if self.readable:
                rows = [{
                    "element_id": element_id,
                    "owner_view_id": "900",
                    "owner_view_name": "Уровень 1",
                    "at_view_ft": [10.0, -2.5],
                    "tagged_element_id": WALL_ID,
                    "tag_family": "independent",
                    # Без выноски: только такая марка сегодня поднимается
                    # (для марки С выноской `at` означает конец выноски, а
                    # стадия читает голову — см. _lift_tag).
                    "leader": False,
                    "orientation": "Horizontal",
                    "type_id": "77",
                    "type_name": "Марка стены",
                } for element_id in requested]
                failures: list[dict[str, Any]] = []
            else:
                rows = []
                failures = [{
                    "element_id": element_id,
                    "reason": "tag marks no element of this document",
                    "typed_reason": "tag_target_not_local",
                } for element_id in requested]
            return {"ok": True, "result": {
                "schema_version": TAG_EXTRACT_SCHEMA_VERSION,
                "elements": rows, "failures": failures}}
        return await super()._dispatch(code, timeout_ms=timeout_ms)


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


class TagStageRunsEndToEnd(unittest.TestCase):

    def test_the_stage_is_asked_persisted_and_lifted(self) -> None:
        with TemporaryDirectory() as tmp:
            bridge = TagBridge()
            result = _run(pipe.run_decompile(
                bridge, out_dir=tmp, change_stamp="pipeline-tag-v1"))
            self.assertTrue(result.ok, msg=result.to_dict())
            self.assertIn("tag", bridge.side_calls,
                          "конвейер не запросил стадию марок ни разу")
            index_path = Path(tmp) / "tag.index.json"
            self.assertTrue(index_path.is_file(), "индекс марок не сохранён")
            index = json.loads(index_path.read_text("utf-8"))
            self.assertIn(TAG_ID, index["tag_index"])
            self.assertEqual(
                index["tag_index"][TAG_ID]["tagged_element_id"], WALL_ID)

    def test_the_tag_becomes_an_op_only_when_the_stage_could_read_it(self) -> None:
        """Разница между «прочитали» и «не смогли» обязана быть ВИДНА в числах.

        Один и тот же документ, один и тот же лифт, отличается только ответ
        моста — и ровно на одну операцию отличается результат. Без этой пары
        нельзя отличить работающую проводку от проводки, которая молча
        отдаёт прежний ответ (та самая ловушка кэша, стоившая трёх волн).
        """
        with TemporaryDirectory() as tmp:
            read = _run(pipe.run_decompile(
                TagBridge(readable=True), out_dir=tmp,
                change_stamp="pipeline-tag-v1"))
        with TemporaryDirectory() as tmp:
            refused = _run(pipe.run_decompile(
                TagBridge(readable=False), out_dir=tmp,
                change_stamp="pipeline-tag-v1"))
        self.assertTrue(read.ok, msg=read.to_dict())
        self.assertTrue(refused.ok, msg=refused.to_dict())
        self.assertEqual(read.ops_lifted, refused.ops_lifted + 1)
        self.assertEqual(read.atoms + 1, refused.atoms)

    def test_a_typed_receipt_keeps_the_run_alive_and_is_counted(self) -> None:
        """Квитанция — отчёт, а не смерть прогона (§18.2)."""
        with TemporaryDirectory() as tmp:
            result = _run(pipe.run_decompile(
                TagBridge(readable=False), out_dir=tmp,
                change_stamp="pipeline-tag-v1"))
            self.assertTrue(result.ok, msg=result.to_dict())
            # Агрегат §18.2 ложится в run.json ПЛОСКО, а не отдельным
            # объектом: ключи разворачиваются в корень (`**side_failures`).
            run = json.loads((Path(tmp) / "run.json").read_text("utf-8"))
            self.assertEqual(run.get("side_failures_by_stage", {}).get("tag"), 1)
            self.assertEqual(
                run.get("side_cuts_by_reason", {}).get("tag_target_not_local"),
                1)
            # Квитанция обязана быть СРЕЗОМ, а не «определением»: наш target
            # адресует свой документ, и это ограничение наше.
            self.assertEqual(run.get("side_cuts_by_stage", {}).get("tag"), 1)
            self.assertEqual(run.get("side_failures_untyped"), 0)


class TheEmittedBodyFollowsTheDocumentsVersion(unittest.TestCase):
    """Шов 2022 обязан ехать из ПРОЧИТАННОГО документа, а не из умолчания."""

    PROPERTY_CALL = "__tgInd.TaggedLocalElementId"
    METHOD_CALL = "__tgInd.GetTaggedLocalElementIds()"

    def _body(self, revit_version: str) -> str:
        with TemporaryDirectory() as tmp:
            bridge = TagBridge(revit_version=revit_version)
            result = _run(pipe.run_decompile(
                bridge, out_dir=tmp, change_stamp="pipeline-tag-v1"))
            self.assertTrue(result.ok, msg=result.to_dict())
        self.assertTrue(bridge.tag_bodies, "стадию марок ни разу не позвали")
        return bridge.tag_bodies[0]

    def test_a_2021_document_gets_the_2021_member(self) -> None:
        body = self._body("2021")
        self.assertIn(self.PROPERTY_CALL, body)
        self.assertNotIn(self.METHOD_CALL, body)

    def test_a_2026_document_gets_the_2022plus_member(self) -> None:
        body = self._body("2026")
        self.assertIn(self.METHOD_CALL, body)
        self.assertNotIn(self.PROPERTY_CALL, body)


if __name__ == "__main__":
    unittest.main()
