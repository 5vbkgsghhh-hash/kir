from __future__ import annotations

import asyncio
import json
import copy
import tempfile
import unittest
from pathlib import Path

from kukai.ir.decompile.extract import (
    EXTRACT_CATEGORIES,
    L0JSONLReader,
    ExtractionProtocolError,
    build_category_batch_cs,
    build_category_probe_cs,
    build_metadata_cs,
    extract_document,
)
from kukai.ir.decompile.geometry_store import parse_geometry
from kukai.ir.decompile.schema import (
    EXTRACT_BATCH,
    EXTRACT_RETRIES,
    EXTRACT_TIMEOUT_MS,
    CategoryState,
    L0Element,
    L0SchemaError,
)
from kukai.ir.decompile.tests.fixtures_decompile import (
    FakeExtractBridge,
    SyntheticBridgeCrash,
    make_element,
    project1_elements,
    project1_metadata,
)
from kukai.security.validation import validate_code_safety


EXPECTED_CATEGORIES = (
    "OST_Walls",
    "OST_Floors",
    "OST_Roofs",
    "OST_Columns",
    "OST_StructuralColumns",
    "OST_StructuralFraming",
    "OST_StructuralFoundation",
    "OST_Doors",
    "OST_Windows",
    "OST_Stairs",
    "OST_StairsRailing",
    "OST_Rooms",
    "OST_Grids",
    "OST_Levels",
    "OST_PipeCurves",
    "OST_DuctCurves",
    "OST_CableTray",
    "OST_Furniture",
    "OST_GenericModel",
    "DirectShape",
    "ImportInstance",
    "OST_RasterImages",
)


def _only_walls(count: int, *, same_level: bool = False) \
        -> dict[str, list[dict]]:
    rows = {category: [] for category in EXTRACT_CATEGORIES}
    for ordinal in range(count):
        row = make_element("OST_Walls", 100_000 + ordinal, ordinal=ordinal)
        if same_level:
            row["level_id"] = "100"
            row["level_name"] = "Этаж 1"
            row["p0_mm"][2] = 0.0
            row["p1_mm"][2] = 0.0
            row["bbox_min_mm"][2] = 0.0
            row["bbox_max_mm"][2] = 2_800.0
        rows["OST_Walls"].append(row)
    return rows


class FrozenSchemaTests(unittest.TestCase):
    def test_fixed_category_order_and_limits(self) -> None:
        """Порядок категорий заморожен НА ПРЕФИКСЕ, а не целиком.

        Индекс категории в этом кортеже — часть формата возобновления: уже
        начатое извлечение хранит, докуда дошло, номером. Поэтому
        переставлять и вставлять в середину нельзя — это перепутало бы
        возобновляемые прогоны. А ДОПИСЫВАТЬ В КОНЕЦ можно и нужно: таблица
        обязана расти по мере того, как компилятор перестаёт быть
        архитектурным.

        Пока тест сравнивал кортеж целиком, он запрещал ровно то, что
        безопасно, и это его единственное следствие: 27.07 при добавлении
        разделов ЭОМ/ОВ/ВК/КР (20 -> 45 категорий) он упал, хотя ни один
        существующий индекс не сдвинулся. Теперь он проверяет то, что
        действительно нельзя нарушать.
        """
        prefix = EXTRACT_CATEGORIES[:len(EXPECTED_CATEGORIES)]
        self.assertEqual(prefix, EXPECTED_CATEGORIES,
                         "порядок ранее существовавших категорий сдвинулся — "
                         "это ломает возобновление начатых извлечений")
        self.assertGreaterEqual(len(EXTRACT_CATEGORIES),
                                len(EXPECTED_CATEGORIES))
        self.assertEqual(len(set(EXTRACT_CATEGORIES)),
                         len(EXTRACT_CATEGORIES), "категория продублирована")
        # 29.07: EXTRACT_BATCH стал переопределяемым ТОЛЬКО окружением
        # (KUKAI_IR_EXTRACT_BATCH) — страница на UI-потоке Revit обязана
        # укладываться в EXTRACT_TIMEOUT_MS с запасом, иначе сокет моста
        # умирает голоданием пинга (13A-RD-AR-K2, 15 341 стена, смерть 1006
        # на плавающей странице). Закон здесь — про ДЕФОЛТ и нижнюю границу.
        from kukai.ir.decompile.schema import _EXTRACT_BATCH_DEFAULT
        self.assertEqual(_EXTRACT_BATCH_DEFAULT, 2_000)
        self.assertGreaterEqual(EXTRACT_BATCH, 50)
        self.assertEqual(EXTRACT_TIMEOUT_MS, 30_000)
        self.assertEqual(EXTRACT_RETRIES, 2)

    def test_curtain_categories_are_appended_after_the_frozen_prefix(
            self) -> None:
        """Витражные дописки живут В ХВОСТЕ, за замороженным префиксом.

        OST_CurtaSystem — хвост волны aaa44b45 (28.07): витражная система,
        третий род носителя сетки наравне со стеной и кровлей; без строки в
        таблице её панели не получали носителя при чтении.

        Линии разрезки — волна 29.07: без них раскладка сетки не читается
        вовсе, и обратный ход не может поставить линию операцией, не
        ИЗОБРЕТЯ источник. Живой прогон v14 остановился ровно на этом:
        ``FoldError('L0/L1 source mismatch: missing=0, invented=122')``.
        Имя категории взято из ПЕРЕПИСИ той же живой модели —
        OST_CurtainGridsWall, 122 элемента, ровно столько же, сколько линий
        в curtain-индексе; существование всех трёх имён проверено
        компиляцией на 2021-2026.

        Проверяется то, что действительно нельзя нарушать: строки есть и
        стоят ЗА префиксом (дописаны в конец, а не вставлены в середину —
        индекс категории есть часть формата возобновления). Требовать
        «последняя» от конкретного имени нельзя: следующая же дописка
        сделала бы такой тест ложно-красным, ничего не сломав.
        """
        tail = EXTRACT_CATEGORIES[len(EXPECTED_CATEGORIES):]
        for name in ("OST_CurtaSystem", "OST_CurtainGridsWall",
                     "OST_CurtainGridsRoof", "OST_CurtainGridsCurtaSystem"):
            with self.subTest(category=name):
                self.assertIn(name, EXTRACT_CATEGORIES)
                self.assertIn(name, tail)

    def test_every_fixed_category_has_valid_fixture_records(self) -> None:
        fixtures = project1_elements()
        self.assertEqual(set(fixtures), set(EXTRACT_CATEGORIES))
        for category in EXTRACT_CATEGORIES:
            self.assertTrue(fixtures[category], category)
            for row in fixtures[category]:
                geometry = parse_geometry(row)
                normalized = dict(row)
                normalized.update(geometry.to_element_fields())
                element = L0Element.from_dict(normalized)
                self.assertEqual(element.category, category)

    def test_schema_does_not_normalize_bad_link_loaded_flag(self) -> None:
        from kukai.ir.decompile.schema import LinkSummary

        with self.assertRaisesRegex(L0SchemaError, "loaded"):
            LinkSummary.from_dict({
                "element_id": "1",
                "name": "bad",
                "loaded": "false",
                "element_count": None,
                "bbox_min_mm": None,
                "bbox_max_mm": None,
                "discipline": "unknown",
            })


class GeneratedCSharpTests(unittest.TestCase):
    def test_all_bodies_are_read_only_and_pass_static_safety(self) -> None:
        bodies = [build_metadata_cs()]
        for category in EXTRACT_CATEGORIES:
            probe = build_category_probe_cs(category)
            batch = build_category_batch_cs(category)
            self.assertIn("WhereElementIsNotElementType()", probe)
            self.assertIn("WhereElementIsNotElementType()", batch)
            self.assertIn("UnitUtils.ConvertFromInternalUnits", batch)
            self.assertIn(".Id.ToString()", batch)
            self.assertIn(f".Take({EXTRACT_BATCH + 1})", batch)
            bodies.extend((probe, batch))
        for body in bodies:
            self.assertIsNone(validate_code_safety(body))
            self.assertNotIn("304.8", body)
            self.assertNotIn("IntegerValue", body)
            self.assertNotIn("Transaction", body)

    def test_metadata_captures_required_document_facts_and_links(self) -> None:
        body = build_metadata_cs()
        for token in (
            "Level", "Grid", "GetBoundarySegments", "ProjectInformation",
            "RevitLinkInstance", "GetLinkDocument", "get_BoundingBox(null)",
            "UnitTypeId.SquareMeters",
            # ПОЛНОЕ ИМЯ, а не голое `Regex.Split` — замерено 04.08 на живом
            # устройстве оператора: `CS0103: The name 'Regex' does not exist`.
            # `System.Text.RegularExpressions` НЕ входит в список usings
            # клиента намеренно: его `Group` конфликтует с
            # `Autodesk.Revit.DB.Group` (см. NOTES_A1B). Серверная обёртка его
            # включает — поэтому расхождение и не всплывало до живого прогона.
            # Так же квалифицируют `Regex` правила аудита.
            "Char.IsLetterOrDigit",
        ):
            self.assertIn(token, body)
        self.assertIn(f".Take({EXTRACT_BATCH + 1})", body)
        self.assertNotIn("__PutGeometry", body)
        self.assertNotIn("get_Geometry", body)

    def test_element_body_captures_grouping_state(self) -> None:
        body = build_category_batch_cs("OST_Walls")
        for token in (
            "DesignOption", "CreatedPhaseId", "WorksetId",
            "phase_created", "design_option", "workset",
        ):
            self.assertIn(token, body)


class ExtractionIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_project1_stream_round_trip_all_categories_and_link(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "project1.jsonl"
            bridge = FakeExtractBridge()
            result = await extract_document(
                bridge, change_stamp="synthetic-v1", output_path=output)

            self.assertEqual(result.element_count, 350)
            self.assertEqual(result.completed_categories, EXTRACT_CATEGORIES)
            self.assertEqual(result.partial_categories, ())
            self.assertFalse(result.resumed)
            self.assertFalse(bridge.link_recursion_attempted)
            self.assertLessEqual(bridge.max_page_size, EXTRACT_BATCH)

            reader = L0JSONLReader(output)
            reader.validate()
            metadata = reader.metadata()
            self.assertEqual(metadata.doc_name, "Проект1_synthetic")
            self.assertEqual(len(metadata.levels), 13)
            self.assertEqual(len(tuple(reader.iter_elements())), 350)
            links = tuple(reader.iter_links())
            self.assertEqual(len(links), 1)
            self.assertEqual(links[0].discipline, "structural")

            document = reader.materialize()
            self.assertEqual(len(document.elements), 350)
            self.assertEqual(
                {element.category for element in document.elements},
                set(EXTRACT_CATEGORIES))
            self.assertTrue(all(
                status.state is CategoryState.COMPLETE
                for status in document.category_status))

    async def test_timed_out_category_is_partial_and_later_categories_continue(
            self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "partial.jsonl"
            bridge = FakeExtractBridge(timeout_probe_for="OST_Roofs")
            result = await extract_document(
                bridge, change_stamp="synthetic-v1", output_path=output)

            self.assertEqual(result.partial_categories, ("OST_Roofs",))
            self.assertEqual(
                bridge.probe_attempts["OST_Roofs"], EXTRACT_RETRIES + 1)
            statuses = {
                status.category: status
                for status in L0JSONLReader(output).iter_category_status()
            }
            roof = statuses["OST_Roofs"]
            self.assertIs(roof.state, CategoryState.PARTIAL)
            self.assertEqual(roof.extracted_count, 0)
            self.assertIsNone(roof.expected_count)
            self.assertIn("failed after 3 attempts", roof.error or "")
            self.assertIs(
                statuses["OST_RasterImages"].state, CategoryState.COMPLETE)

    async def test_category_over_batch_is_split_by_level(self) -> None:
        rows = _only_walls(EXTRACT_BATCH + 1)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "large.jsonl"
            bridge = FakeExtractBridge(elements=rows)
            result = await extract_document(
                bridge, change_stamp="synthetic-large", output_path=output)

            self.assertEqual(result.element_count, EXTRACT_BATCH + 1)
            # The fixture spans 13 levels, so no single response approaches
            # the whole 2001-element population.
            self.assertLess(bridge.max_page_size, EXTRACT_BATCH)
            self.assertEqual(
                len(tuple(L0JSONLReader(output).iter_elements())),
                EXTRACT_BATCH + 1)

    async def test_room_metadata_is_paged_at_same_hard_limit(self) -> None:
        metadata = project1_metadata()
        room_template = metadata["rooms"][0]
        metadata["rooms"] = []
        for ordinal in range(EXTRACT_BATCH + 1):
            room = copy.deepcopy(room_template)
            room["id"] = str(300_000 + ordinal)
            room["name"] = f"Комната {ordinal + 1}"
            metadata["rooms"].append(room)
        empty = {category: [] for category in EXTRACT_CATEGORIES}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "room-pages.jsonl"
            bridge = FakeExtractBridge(metadata=metadata, elements=empty)
            await extract_document(
                bridge, change_stamp="synthetic-rooms", output_path=output)

            self.assertEqual(bridge.max_room_page_size, EXTRACT_BATCH)
            self.assertEqual(
                len(L0JSONLReader(output).metadata().rooms),
                EXTRACT_BATCH + 1)

    async def test_resume_truncates_uncommitted_category_tail(self) -> None:
        rows = _only_walls(EXTRACT_BATCH + 1, same_level=True)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "resume.jsonl"
            bridge = FakeExtractBridge(
                elements=rows, crash_batch_for="OST_Walls",
                crash_after_pages=1)
            with self.assertRaises(SyntheticBridgeCrash):
                await extract_document(
                    bridge, change_stamp="synthetic-resume",
                    output_path=output)

            checkpoint_path = output.with_suffix(
                output.suffix + ".checkpoint.json")
            checkpoint = json.loads(
                checkpoint_path.read_text(encoding="utf-8"))
            self.assertEqual(checkpoint["processed_categories"], [])
            self.assertGreater(
                output.stat().st_size, checkpoint["committed_offset"])

            resumed_bridge = FakeExtractBridge(elements=rows)
            result = await extract_document(
                resumed_bridge, change_stamp="synthetic-resume",
                output_path=output)
            self.assertTrue(result.resumed)
            self.assertEqual(result.element_count, EXTRACT_BATCH + 1)
            ids = [
                element.element_id
                for element in L0JSONLReader(output).iter_elements()]
            self.assertEqual(len(ids), len(set(ids)))
            self.assertEqual(len(ids), EXTRACT_BATCH + 1)

    async def test_resume_refuses_different_change_stamp(self) -> None:
        rows = _only_walls(EXTRACT_BATCH + 1, same_level=True)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "stale.jsonl"
            bridge = FakeExtractBridge(
                elements=rows, crash_batch_for="OST_Walls")
            with self.assertRaises(SyntheticBridgeCrash):
                await extract_document(
                    bridge, change_stamp="stamp-a", output_path=output)
            fresh_bridge = FakeExtractBridge(elements=rows)
            with self.assertRaisesRegex(
                    ExtractionProtocolError, "change_stamp differs"):
                await extract_document(
                    fresh_bridge, change_stamp="stamp-b",
                    output_path=output)
            self.assertEqual(fresh_bridge.calls, [])

    async def test_stream_parser_rejects_missing_footer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "truncated.jsonl"
            await extract_document(
                FakeExtractBridge(), change_stamp="synthetic-v1",
                output_path=output)
            lines = output.read_bytes().splitlines(keepends=True)
            output.write_bytes(b"".join(lines[:-1]))
            with self.assertRaisesRegex(
                    ExtractionProtocolError, "no committed footer"):
                L0JSONLReader(output).validate()


if __name__ == "__main__":
    unittest.main()


class RetryBackoffWaitsForTheBridgeToComeBack(unittest.TestCase):
    """Обрыв сети рвёт сокет моста (1006), окно возвращается с новым ws_id
    через секунды. Мгновенный ретрай (sleep(0)) расходовал весь бюджет за
    миллисекунды по ещё мёртвому сокету — замер 29.07 (К2 РД, три прогона
    умерли на плавающей странице). Ретрай обязан ЖДАТЬ между попытками."""

    def test_backoff_sleeps_between_attempts_and_then_succeeds(self) -> None:
        from kukai.ir.decompile import extract as E

        delays: list[float] = []
        calls = {"n": 0}

        async def flaky_executor(code, *, timeout_ms):
            calls["n"] += 1
            if calls["n"] <= 2:
                raise RuntimeError("Unexpected ASGI message 'websocket.send'")
            return {"ok": True, "result": {"count": 1}}

        async def fake_sleep(seconds):
            delays.append(seconds)

        async def scenario():
            real_sleep = E.asyncio.sleep
            E.asyncio.sleep = fake_sleep
            try:
                return await E._execute_with_retries(
                    flaky_executor, "return 1;", timeout_ms=1000, retries=2)
            finally:
                E.asyncio.sleep = real_sleep

        result = asyncio.run(scenario())
        self.assertEqual(result, {"count": 1})
        self.assertEqual(calls["n"], 3)
        self.assertEqual(delays, list(E.EXTRACT_RETRY_BACKOFF_S[:2]),
                         "между попытками обязана быть пауза на реконнект")

    def test_exhausted_budget_does_not_sleep_after_the_last_attempt(self) -> None:
        from kukai.ir.decompile import extract as E

        delays: list[float] = []

        async def dead_executor(code, *, timeout_ms):
            raise RuntimeError("socket is dead")

        async def fake_sleep(seconds):
            delays.append(seconds)

        async def scenario():
            real_sleep = E.asyncio.sleep
            E.asyncio.sleep = fake_sleep
            try:
                with self.assertRaises(E.BridgeCallError):
                    await E._execute_with_retries(
                        dead_executor, "return 1;", timeout_ms=1000, retries=2)
            finally:
                E.asyncio.sleep = real_sleep

        asyncio.run(scenario())
        self.assertEqual(len(delays), 2,
                         "после ПОСЛЕДНЕЙ попытки спать незачем")
