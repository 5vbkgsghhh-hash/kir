# -*- coding: utf-8 -*-
"""Задачи #26/#27: извлечение переживает уход окна на минуты.

Сеть оператора рвётся, сокет моста умирает 1006 посреди многостраничного
извлечения, окно возвращается с НОВЫМ ws_id через секунды-минуты (замер
29.07 на 13A-RD-AR-K2, РД, 18 492 элемента: три прогона умерли на плавающей
странице, каждый пришлось начинать заново полностью).

Уже сделано до этой волны: страницы по 400 (KUKAI_IR_EXTRACT_BATCH),
пере-резолв окна на каждый вызов, паузы ретраев (5, 20) — терпит ~25 с.

Здесь два настоящих фикса:

* #26 — при исчерпании ретраев страницы цикл ЖДЁТ возвращения окна и
  повторяет страницу; запас общий на прогон, потолок исчерпан → категория
  partial с причиной;
* #27 — резюм с partial-категориями ДОИЗВЛЕКАЕТ их, а не отдаёт снимок как
  есть (сегодня это блокирует прогон `snapshot_non_authoritative`, и
  оператору остаётся полный прогон под новым штампом).

Все тесты — опровергающие: каждый красен без своей правки.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from kukai.ir.decompile import extract as E
from kukai.ir.decompile.extract import (
    BridgeCallError, L0JSONLReader, extract_document)
from kukai.ir.decompile.schema import EXTRACT_BATCH, CategoryState
from kukai.ir.decompile.tests.fixtures_decompile import (
    FakeExtractBridge, project1_elements)


def _walls(count: int) -> dict[str, list[dict[str, Any]]]:
    """Только стены — одна категория, чтобы обрыв бил в известное место."""
    rows = project1_elements()
    walls = [row for row in rows.get("OST_Walls", [])]
    if not walls:
        raise AssertionError("фикстура без стен")
    out = []
    for index in range(count):
        row = dict(walls[0])
        row["element_id"] = str(1000 + index)
        out.append(row)
    return {"OST_Walls": out}


def _checkpoint(output: Path) -> dict[str, Any]:
    path = output.with_suffix(output.suffix + ".checkpoint.json")
    return json.loads(path.read_text(encoding="utf-8"))


# Паузы в тестах — миллисекунды: проверяется ЛОГИКА ожидания, а не часы.
# Паузы РЕТРАЕВ патчатся вместе с паузами ОЖИДАНИЯ: боевые (5, 20) с дали бы
# 25 секунд на каждый оборот ожидания и превратили бы набор в получасовой.
FAST = mock.patch.multiple(
    E, EXTRACT_WINDOW_WAIT_S=0.30, EXTRACT_WINDOW_POLL_S=0.01,
    EXTRACT_RETRY_BACKOFF_S=(0.001,))
NO_WAIT = mock.patch.multiple(
    E, EXTRACT_WINDOW_WAIT_S=0.0, EXTRACT_WINDOW_POLL_S=0.01,
    EXTRACT_RETRY_BACKOFF_S=(0.001,))


class WaitingForTheWindow(unittest.IsolatedAsyncioTestCase):
    """#26: обрыв на странице N → ожидание → окно вернулось → complete."""

    async def test_a_returning_window_completes_the_category(self) -> None:
        rows = _walls(3)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "outage.jsonl"
            # Окно уходит на первой странице стен и возвращается после
            # нескольких неудачных попыток — ровно поведение живого обрыва.
            bridge = FakeExtractBridge(
                elements=rows, outage_for="OST_Walls",
                outage_after_pages=0, outage_calls=6)
            with FAST:
                result = await extract_document(
                    bridge, change_stamp="outage-heals", output_path=output)

            self.assertGreater(bridge.outage_raised, 0, "обрыва не было")
            self.assertEqual(result.partial_categories, (),
                             "категория обязана закрыться полной")
            self.assertIn("OST_Walls", result.completed_categories)
            self.assertEqual(result.element_count, 3)
            L0JSONLReader(output).validate()

    async def test_pre_state_without_waiting_the_category_is_buried(self) -> None:
        """ПРЕД-СОСТОЯНИЕ #26: без ожидания тот же обрыв хоронит категорию.

        Запас ожидания обнулён — остаётся ровно вчерашнее поведение: бюджет
        ретраев (~25 с) сгорает, и переживший бы обрыв прогон отдаёт partial.
        Тот же самый мост в тесте выше закрывает категорию полной.
        """
        rows = _walls(3)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "no-wait.jsonl"
            bridge = FakeExtractBridge(
                elements=rows, outage_for="OST_Walls",
                outage_after_pages=0, outage_calls=6)
            with NO_WAIT:
                result = await extract_document(
                    bridge, change_stamp="outage-no-wait", output_path=output)

            self.assertIn("OST_Walls", result.partial_categories)
            self.assertEqual(result.element_count, 0)

    async def test_an_outage_longer_than_the_cap_is_a_partial(self) -> None:
        """Потолок исчерпан → partial С ПРИЧИНОЙ, без тихого успеха."""
        rows = _walls(3)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "gone.jsonl"
            bridge = FakeExtractBridge(
                elements=rows, outage_for="OST_Walls",
                outage_after_pages=0, outage_calls=10_000)
            with FAST:
                result = await extract_document(
                    bridge, change_stamp="outage-forever", output_path=output)

            self.assertIn("OST_Walls", result.partial_categories)
            status = _checkpoint(output)["category_states"]["OST_Walls"]
            self.assertEqual(status, CategoryState.PARTIAL.value)
            # Причина обязана НАЗЫВАТЬ ожидание, иначе читатель отчёта
            # решит, что мост отказал мгновенно.
            reason = next(
                row["status"]["error"]
                for row in (json.loads(line)
                            for line in output.read_text().splitlines())
                if row.get("record") == "category_status"
                and row["status"]["category"] == "OST_Walls")
            self.assertIn("окно не вернулось", reason)
            # Поток всё равно закрыт по закону: один футер, последним.
            L0JSONLReader(output).validate()

    async def test_the_budget_is_shared_by_the_whole_run(self) -> None:
        """Запас ОБЩИЙ: мёртвое окно стоит потолок один раз, а не на каждую.

        Попостраничный потолок множился бы на число категорий — закрытое
        навсегда окно стоило бы часы мнимой работы вместо минут.
        """
        budget = E._WindowWaitBudget(total_s=0.05)
        with mock.patch.object(E, "EXTRACT_WINDOW_POLL_S", 0.01):
            spent = 0
            while await budget.pause():
                spent += 1
            self.assertGreater(spent, 0)
            self.assertEqual(budget.remaining, 0.0)
            # Исчерпанный запас не восстанавливается сам собой.
            self.assertFalse(await budget.pause())

    async def test_revision_drift_is_never_waited_out(self) -> None:
        """Смена документа за время обрыва — типизированный отказ ПРОГОНА.

        Ждать её значило бы выбирать другую ревизию и выдавать смешанный
        снимок за успешный.
        """
        from kukai.ir.decompile.pipeline import DocumentRevisionError

        calls = {"n": 0}

        async def drifting(code: str, *, timeout_ms: int) -> Any:
            calls["n"] += 1
            raise DocumentRevisionError("document changed during one bridge read")

        with FAST:
            with self.assertRaises(DocumentRevisionError):
                await E._execute_awaiting_window(
                    drifting, "code", timeout_ms=1000, retries=2,
                    budget=E._WindowWaitBudget(), what="проба")
        self.assertEqual(calls["n"], 1, "ревизию не ретраят и не пережидают")

    async def test_exhausted_wait_still_raises_bridge_call_error(self) -> None:
        """Наружу — по-прежнему BridgeCallError: новых исходов не заведено."""
        async def dead(code: str, *, timeout_ms: int) -> Any:
            raise RuntimeError("bridge window is not connected (matches: 0)")

        with NO_WAIT:
            with self.assertRaises(BridgeCallError) as caught:
                await E._execute_awaiting_window(
                    dead, "code", timeout_ms=1000, retries=0,
                    budget=E._WindowWaitBudget(), what="страница OST_Walls")
        self.assertIn("окно не вернулось", str(caught.exception))


#: Конверт, который сервер РЕАЛЬНО отдаёт, когда наш собственный шаблон не
#: собрался. Форма снята с ``RevitExecutionPipeline.run_declarative`` (ветка
#: ``state = "compile_failed"``) и ``envelope.attach_err``: голый флаг
#: ``error: True``, человеческий текст в ``message``, машинный код в
#: ``err.code``. Ни одного ``ok`` в нём нет — это не ответ моста, до моста
#: дело не дошло.
COMPILE_FAILED_ENVELOPE = {
    "error": True,
    "message": (
        "Внутренняя ошибка: серверный шаблон decompile_read не "
        "скомпилировался — сообщи оператору. CS1503: Argument 1: cannot "
        "convert from 'long' to 'Autodesk.Revit.DB.BuiltInParameter' "
        "(line 103)"
    ),
    "err": {
        "code": "compile.cs_error",
        "retryable": True,
        "transient": False,
        "cs_codes": ["CS1503"],
    },
}


class OurOwnTemplateIsNotTheWindowsSilence(unittest.IsolatedAsyncioTestCase):
    """«Мост молчит» и «мы не смогли собрать то, что собирались послать».

    ЖИВОЙ СЛУЧАЙ 30.07. Разбор 59-этажной башни на R2023 полтора часа печатал
    «окно не отвечает на боковая стадия annotation пачка 1/14 — ждём
    возвращения», пока в журнале службы по кругу шло ``TEMPLATE COMPILE
    FAILED ... CS1503 ... bridge_roundtrips=0``. Окно было живым: не собрался
    НАШ шаблон. Слой ожидания отправлял искать причину в Revit — то есть
    ровно туда, где её не было.

    Отказ компиляции нельзя переждать по построению: тот же текст не станет
    собираться оттого, что мы подождали. Он обязан быть НЕМЕДЛЕННЫМ
    типизированным отказом, как ``DocumentRevisionError``, а не транспортной
    неудачей внутри бюджета ретраев.

    Все тесты опровергающие: каждый красен без своей правки.
    """

    def test_the_detail_survives_instead_of_a_bare_true(self) -> None:
        """Причина обязана нести CS-код и строку, а не строку ``True``.

        Разворачиватель конверта брал ``current["error"]``, а там лежит
        БУЛЕВ ФЛАГ. Наружу уходило ``ExtractionProtocolError: True`` — то
        единственное, что нельзя загуглить, отгрепать и понять.
        """
        with self.assertRaises(E.TemplateCompileError) as caught:
            E._unwrap_bridge_payload(dict(COMPILE_FAILED_ENVELOPE))
        detail = str(caught.exception)
        self.assertNotEqual(detail, "True")
        self.assertIn("CS1503", detail)
        self.assertIn("не скомпилировался", detail)

    async def test_a_template_compile_failure_is_not_a_transport_failure(
        self,
    ) -> None:
        """Ни ретраев, ни ожидания: один вызов и типизированный отказ."""
        calls = {"n": 0}

        async def refuses(code: str, *, timeout_ms: int) -> Any:
            calls["n"] += 1
            return dict(COMPILE_FAILED_ENVELOPE)

        # Запас задан ЯВНО: conftest этого каталога обнуляет боевые 300 с, и
        # бюджет по умолчанию не смог бы доказать, что его не тратили.
        budget = E._WindowWaitBudget(total_s=0.05)
        with FAST:
            with self.assertRaises(E.TemplateCompileError):
                await E._execute_awaiting_window(
                    refuses, "code", timeout_ms=1000, retries=2,
                    budget=budget, what="боковая стадия annotation пачка 1/14")
        self.assertEqual(calls["n"], 1,
                         "нескомпилировавшийся шаблон не ретраят")
        self.assertEqual(budget.waits, 0, "и не пережидают")
        self.assertEqual(budget.remaining, 0.05,
                         "запас ожидания окна на это не тратится")

    async def test_a_silent_window_is_still_waited_out(self) -> None:
        """Разведение — в ОБЕ стороны: настоящее молчание по-прежнему ждут."""
        async def dead(code: str, *, timeout_ms: int) -> Any:
            raise RuntimeError("bridge window is not connected (matches: 0)")

        budget = E._WindowWaitBudget(total_s=0.05)
        with FAST:
            with self.assertRaises(BridgeCallError):
                await E._execute_awaiting_window(
                    dead, "code", timeout_ms=1000, retries=0,
                    budget=budget, what="страница OST_Walls")
        self.assertGreater(budget.waits, 0, "молчание окна обязано ждаться")

    def test_a_runtime_refusal_is_still_a_protocol_error(self) -> None:
        """Отказ РАНТАЙМА Revit — не отказ компиляции; класс не расползается."""
        envelope = {
            "error": True,
            "message": "Revit отказал: InvalidOperationException",
            "err": {"code": "runtime.revit_exception",
                    "retryable": False, "transient": False},
        }
        with self.assertRaises(E.ExtractionProtocolError) as caught:
            E._unwrap_bridge_payload(envelope)
        self.assertNotIsInstance(caught.exception, E.TemplateCompileError)
        self.assertIn("InvalidOperationException", str(caught.exception))

    async def test_the_run_names_it_a_compile_failure_not_an_extract_failure(
        self,
    ) -> None:
        """Прогон обязан назвать дефект своим именем в типизированном отказе."""
        from kukai.ir.decompile import pipeline as P

        async def refuses(code: str, *, timeout_ms: int = 0) -> Any:
            return dict(COMPILE_FAILED_ENVELOPE)

        with tempfile.TemporaryDirectory() as directory:
            with FAST:
                result = await P.run_decompile(
                    refuses, out_dir=directory, change_stamp="compile-fail")
        self.assertFalse(result.ok)
        self.assertEqual((result.error or {}).get("code"),
                         "template_compile_failed")
        self.assertIn("CS1503", json.dumps(result.to_dict(), ensure_ascii=False))


class ResumeFinishesPartials(unittest.IsolatedAsyncioTestCase):
    """#27: резюм доизвлекает partial, а не отдаёт снимок как есть."""

    async def _partial_run(self, directory: str) -> Path:
        output = Path(directory) / "partial.jsonl"
        bridge = FakeExtractBridge(
            elements=_walls(3), outage_for="OST_Walls",
            outage_after_pages=0, outage_calls=10_000)
        with FAST:
            result = await extract_document(
                bridge, change_stamp="resume-partial", output_path=output)
        self.assertIn("OST_Walls", result.partial_categories)
        self.assertTrue(_checkpoint(output)["footer_written"])
        return output

    async def test_resume_re_extracts_and_yields_an_authoritative_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            output = await self._partial_run(directory)
            before = json.loads(
                [line for line in output.read_text().splitlines()
                 if json.loads(line).get("record") == "footer"][0])
            self.assertEqual(before["element_count"], 0)

            # Окно вернулось — резюм обязан ДОИЗВЛЕЧЬ, а не вернуть как есть.
            healthy = FakeExtractBridge(elements=_walls(3))
            with FAST:
                result = await extract_document(
                    healthy, change_stamp="resume-partial",
                    output_path=output)

            self.assertTrue(result.resumed)
            self.assertEqual(result.partial_categories, ())
            self.assertIn("OST_Walls", result.completed_categories)
            self.assertEqual(result.element_count, 3)
            self.assertGreater(healthy.page_attempts["OST_Walls"], 0,
                               "резюм обязан был сходить за страницами")

    async def test_the_stream_keeps_exactly_one_footer_with_the_true_count(self):
        """`stream_complete` остаётся законом: один футер, последним, честный.

        Второй футер «с приоритетом» вылечил бы счётчик и оставил бы дубли
        элементов, а заодно завёл бы второй закон рядом с первым.
        """
        with tempfile.TemporaryDirectory() as directory:
            output = await self._partial_run(directory)
            with FAST:
                await extract_document(
                    FakeExtractBridge(elements=_walls(3)),
                    change_stamp="resume-partial", output_path=output)

            records = [json.loads(line)
                       for line in output.read_text().splitlines()]
            footers = [row for row in records if row.get("record") == "footer"]
            self.assertEqual(len(footers), 1)
            self.assertIs(records[-1], footers[0])
            self.assertTrue(footers[0]["stream_complete"])
            self.assertEqual(footers[0]["element_count"], 3)
            # Ни одного дубля: элементы категории лежат ровно один раз.
            ids = [row["element"]["element_id"] for row in records
                   if row.get("record") == "element"]
            self.assertEqual(len(ids), len(set(ids)))
            L0JSONLReader(output).validate()

    async def test_a_complete_resume_does_no_work(self) -> None:
        """Резюм полного снимка обязан остаться мгновенным."""
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "done.jsonl"
            with FAST:
                await extract_document(
                    FakeExtractBridge(elements=_walls(2)),
                    change_stamp="resume-done", output_path=output)
            idle = FakeExtractBridge(elements=_walls(2))
            with FAST:
                result = await extract_document(
                    idle, change_stamp="resume-done", output_path=output)
            self.assertTrue(result.resumed)
            self.assertEqual(result.partial_categories, ())
            self.assertEqual(idle.page_attempts["OST_Walls"], 0,
                             "полный снимок не смеет извлекаться заново")

    async def test_a_stream_disagreeing_with_the_checkpoint_is_refused(self):
        """Поток и чекпойнт спорят о завершённости — типизированный отказ.

        Обе стороны описывают ОДИН прогон; если они расходятся, неизвестно,
        какая граница настоящая, и «взять более полную» было бы догадкой.
        """
        with tempfile.TemporaryDirectory() as directory:
            output = await self._partial_run(directory)
            path = output.with_suffix(output.suffix + ".checkpoint.json")
            state = json.loads(path.read_text(encoding="utf-8"))
            state["category_states"]["OST_Walls"] = CategoryState.PARTIAL.value
            # Поток говорит partial, чекпойнт — про другую категорию complete
            # там, где поток её вовсе не закрывал.
            other = next(c for c in E.EXTRACT_CATEGORIES if c != "OST_Walls")
            state["category_states"][other] = CategoryState.PARTIAL.value
            path.write_text(json.dumps(state), encoding="utf-8")

            with FAST:
                with self.assertRaises(E.ExtractionProtocolError) as caught:
                    await extract_document(
                        FakeExtractBridge(elements=_walls(3)),
                        change_stamp="resume-partial", output_path=output)
            self.assertIn("stream says", str(caught.exception))


if __name__ == "__main__":
    unittest.main()


class ResumeNeverAppendsAGeneration(unittest.IsolatedAsyncioTestCase):
    """Докат после смерти ПРОЦЕССА не дописывает второе поколение строк.

    Подозрение возникло на К2 (v5): счётчик элементов рос 16 475 → 32 379 →
    52 605 → 55 293, и это выглядело как три поколения, дописанные поверх
    друг друга. Разбор артефакта показал обратное — 55 293 строки, 55 293
    УНИКАЛЬНЫХ id, по одной записи `category_status` на каждую из 54
    категорий, чекпойнт и файл сходятся байт в байт. Числа были снимками
    ОДНОГО идущего извлечения.

    Тест закрепляет это как закон, а не как везение: обрыв процесса
    посреди категории, резюм — и в файле не должно быть ни одного дубля.
    """

    async def _kill_and_resume(self, *, crash_after_pages: int) -> Path:
        from kukai.ir.decompile.tests.fixtures_decompile import (
            SyntheticBridgeCrash)
        rows = _walls(EXTRACT_BATCH * 2 + 5)
        directory = tempfile.mkdtemp()
        output = Path(directory) / "generations.jsonl"
        dying = FakeExtractBridge(
            elements=rows, crash_batch_for="OST_Walls",
            crash_after_pages=crash_after_pages)
        with FAST:
            with self.assertRaises(SyntheticBridgeCrash):
                await extract_document(
                    dying, change_stamp="generations", output_path=output)
        # Файл ДЛИННЕЕ зафиксированной границы — незакоммиченный хвост есть.
        self.assertGreater(
            output.stat().st_size, _checkpoint(output)["committed_offset"])
        with FAST:
            await extract_document(
                FakeExtractBridge(elements=rows),
                change_stamp="generations", output_path=output)
        return output

    async def test_no_duplicate_rows_after_resume(self) -> None:
        output = await self._kill_and_resume(crash_after_pages=1)
        records = [json.loads(line)
                   for line in output.read_text().splitlines()]
        ids = [row["element"]["element_id"] for row in records
               if row.get("record") == "element"]
        statuses = [row["status"]["category"] for row in records
                    if row.get("record") == "category_status"]
        self.assertEqual(len(ids), len(set(ids)), "дубли строк элементов")
        self.assertEqual(len(statuses), len(set(statuses)),
                         "категория закрыта дважды")
        self.assertEqual(
            len([r for r in records if r.get("record") == "header"]), 1)
        self.assertEqual(
            len([r for r in records if r.get("record") == "footer"]), 1)
        L0JSONLReader(output).validate()

    async def test_the_footer_counts_the_rows_that_are_actually_there(self):
        """Закон уровня файла: футер, квитанции и СТРОКИ обязаны сойтись."""
        output = await self._kill_and_resume(crash_after_pages=1)
        records = [json.loads(line)
                   for line in output.read_text().splitlines()]
        actual = sum(1 for r in records if r.get("record") == "element")
        footer = next(r for r in records if r.get("record") == "footer")
        by_status = sum(r["status"]["extracted_count"] for r in records
                        if r.get("record") == "category_status")
        self.assertEqual(footer["element_count"], actual)
        self.assertEqual(by_status, actual)
