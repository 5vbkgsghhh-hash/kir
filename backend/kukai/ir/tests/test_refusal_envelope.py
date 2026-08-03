"""ОТКАЗ ДОЛЖЕН НЕСТИ ПРИЧИНУ — измерение конверта отказа KIR.

Живой замер 29.07 (башня, два плеча — KIR и сырой C#) показал на KIR-плече
``err_code: null``, ``cs_codes: []``, ``repairs: []``, и отсюда родился вывод
«KIR отказывает ХУЖЕ, чем C#: модель получает "не вышло" без диагноза».

Этот файл разделяет замер на два РАЗНЫХ вопроса, потому что смешивать их —
и есть источник неверной трактовки:

  A. Что видит МОДЕЛЬ.   Ровно тот dict, который ``handle_revit_ir`` вернул:
     он целиком уходит в ``json.dumps`` (kukai/llm/client.py:1533) и дальше в
     ``_smart_truncate`` с потолком 50 000 символов (kukai/llm/loop_policy.py:183),
     то есть диагностика размером в сотни байт не режется НИКОГДА.

  B. Что видит СИСТЕМА.  Машиночитаемый блок ``err`` — единственный контракт
     «что случилось» (kukai/llm/envelope.py). Его читают оценщик
     (kukai/will/evaluator.py:144 — ровно ``result["err"]["code"]``), квитанция
     (kukai/api/bridge_protocol.py:1138) и детектор ошибки хода
     (kukai/llm/client.py:1569, kukai/api/chat_ws.py:2007).

Тесты класса A должны проходить и ДО правки: причина у модели была.
Тесты класса B до правки ПАДАЮТ — это и есть опровергающий замер.
"""
import asyncio
import json
import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_test_queue.jsonl"))

from kukai.ir import serving  # noqa: E402
from kukai.ir.tests.acceptance_fakes import PassingAcceptanceBridge  # noqa: E402
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT  # noqa: E402
from kukai.llm.envelope import result_is_error  # noqa: E402
from kukai.will.evaluator import _err_code  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


# Программа-башня в миниатюре: одна стена, запись, привязка к уровню по id.
# Любая запись тянет ground_snapshot, поэтому мост отвечает дважды.
_WRITE_PROGRAM = {"ir_version": "1.0", "ops": [
    {"op": "create_wall", "id": "W1", "p0_mm": [0, 0], "p1_mm": [6000, 0],
     "level": {"by": "element_id", "value": 42}}]}


def _harness_is_error(tool_result: dict) -> bool:
    """Детектор ошибки хода — ровно тот, что стоит в проде.

    Раньше здесь была бы копия инлайн-выражения; теперь оба прод-места
    (kukai/llm/client.py:1569, kukai/api/chat_ws.py:2007) зовут ОДИН
    предикат, поэтому тест меряет прод, а не свою реплику его."""
    result_str = json.dumps(tool_result, ensure_ascii=False, default=str)
    return bool(
        result_is_error(tool_result)
        or '"error": true' in result_str
        or '"error":true' in result_str
    )


class _KirRefusalBase(unittest.TestCase):
    """Общий стенд: KIR-плечо, запись, мост отвечает отказом."""

    def setUp(self):
        os.environ["KUKAI_KIR_TOOL"] = "stage2"
        self._dev = mock.patch.object(serving, "_turn_device_id",
                                      return_value=serving.ADMIN_DEVICE)
        self._dev.start()
        self.llm = mock.Mock()
        self.llm._revit_version = "2024"
        self._acceptance_dir = tempfile.TemporaryDirectory()
        self._prev_acceptance_dir = os.environ.get(
            "KIR_ACCEPTANCE_EVIDENCE_DIR")
        os.environ["KIR_ACCEPTANCE_EVIDENCE_DIR"] = self._acceptance_dir.name

    def tearDown(self):
        self._dev.stop()
        os.environ.pop("KUKAI_KIR_TOOL", None)
        if self._prev_acceptance_dir is None:
            os.environ.pop("KIR_ACCEPTANCE_EVIDENCE_DIR", None)
        else:
            os.environ["KIR_ACCEPTANCE_EVIDENCE_DIR"] = (
                self._prev_acceptance_dir)
        self._acceptance_dir.cleanup()

    def _handle(self, program, execute):
        acceptance = PassingAcceptanceBridge(program)

        async def fake_exec(llm, bridge, code, op, timeout_ms):
            return acceptance.dispatch(execute, code, op)
        with mock.patch.object(serving, "_run_declarative", side_effect=fake_exec):
            return _run(serving.handle_revit_ir(
                {"program": program}, self.llm, bridge_callback=None))

    def _write_refused_at_runtime(self):
        """Отказ рантайма Revit на записи — постусловия нарушены, откат."""
        def execute(_code, op):
            if op == "ground_snapshot":
                return {"result": GROUND_SNAPSHOT}
            return {"result": {"error": "postconditions_violated",
                               "violations": ["W1: endpoints (geometry)"]}}
        return self._handle(_WRITE_PROGRAM, execute)

    def _write_refused_by_compiler(self):
        """Отказ компилятора: kind вне покрытия KIR — до моста дело не дошло."""
        def execute(_code, op):
            raise AssertionError("компилятор обязан отказать ДО исполнения")
        return self._handle({"ir_version": "1.0", "ops": [
            {"op": "query_count", "id": "q", "kind": "OST_ImportInstances"}]},
            execute)


class A_ModelSeesTheReason(_KirRefusalBase):
    """A. Причина У МОДЕЛИ ЕСТЬ — и была до всякой правки.

    Если эти тесты проходят на исходном дереве, то тезис «модель получает
    "не вышло" без диагноза» опровергнут: диагноз в конверте, дословно."""

    def test_runtime_refusal_carries_code_and_human_text(self):
        res = self._write_refused_at_runtime()
        self.assertFalse(res["ok"])
        self.assertEqual(res["diagnostics"][0]["code"], "KIR-X004")
        self.assertIn("постусловия нарушены", res["message_ru"])
        # …и адрес правки: какой оп нарушил и чем именно.
        self.assertEqual(res["diagnostics"][0]["violations"],
                         ["W1: endpoints (geometry)"])

    def test_compiler_refusal_carries_code_and_human_text(self):
        res = self._write_refused_by_compiler()
        self.assertFalse(res["ok"])
        self.assertTrue(res["diagnostics"])
        self.assertTrue(res["diagnostics"][0]["code"].startswith("KIR-"))
        self.assertTrue(res["message_ru"])

    def test_reason_survives_the_trip_to_the_model(self):
        """Сериализация + усечение — ровно то, что делает цикл раундов."""
        from kukai.llm.loop_policy import _smart_truncate
        res = self._write_refused_at_runtime()
        wire = _smart_truncate(json.dumps(res, ensure_ascii=False, default=str))
        self.assertIn("KIR-X004", wire)
        self.assertIn("постусловия нарушены", wire)


class B_SystemSeesNothing(_KirRefusalBase):
    """B. А вот СИСТЕМА слепа: конверт без ``err`` — и все читатели пусты.

    До правки каждый тест здесь падает. Это и есть тот самый ``err_code: null``
    из живого замера."""

    def test_refusal_carries_machine_readable_err_block(self):
        res = self._write_refused_at_runtime()
        self.assertIn("err", res,
                      "отказ записи ушёл без блока err — оценщик, квитанция и "
                      "детектор ошибки хода не увидят НИЧЕГО")
        self.assertTrue(res["err"]["code"])

    def test_evaluator_can_name_the_failure(self):
        """kukai/will/evaluator.py:144 — источник ``err_code`` в квитанции."""
        res = self._write_refused_at_runtime()
        self.assertIsNotNone(
            _err_code(res),
            "оценщик не может назвать отказ => err_code: null в замере")

    def test_harness_counts_the_refusal_as_an_error(self):
        """kukai/llm/client.py:1569. Пока False — отказ записи проходит по
        ходу как УСПЕХ: не пишется в errored_sigs, не считается в подряд
        идущих ошибках, в аудит уходит ok:true."""
        res = self._write_refused_at_runtime()
        self.assertTrue(_harness_is_error(res),
                        "провалившаяся запись классифицирована как успех")

    def test_compiler_refusal_also_carries_err(self):
        res = self._write_refused_by_compiler()
        self.assertIn("err", res)
        self.assertIsNotNone(_err_code(res))

    def test_flat_string_error_refusals_are_seen_too(self):
        """Плоская форма ``{"ok": false, "error": "<строка>"}`` — так отказывают
        ``_typed_error`` (serving.py:443) и rebuild_runner (serving.py:2902).
        ``.get("error") is True`` на строке ложен, подстрока ``"error": true``
        не совпадает => отказ невидим."""
        res = serving._typed_error("ground", "мост не ответил")
        self.assertFalse(res["ok"])
        self.assertIn("err", res)
        self.assertIsNotNone(_err_code(res))
        self.assertTrue(_harness_is_error(res))


class DetectorIsShared(unittest.TestCase):
    """Страж: оба прод-места обязаны звать ОДИН предикат. Если кто-то снова
    напишет собственное `error is True`, слепота вернётся молча — этот тест
    не даст."""

    def test_both_production_sites_call_the_shared_predicate(self):
        import inspect
        from kukai.llm import client
        from kukai.api import chat_ws
        self.assertIn("result_is_error(tool_result)", inspect.getsource(client))
        self.assertIn("_result_is_error(parsed_result)", inspect.getsource(chat_ws))


class PredicateDoesNotInventFailures(unittest.TestCase):
    """Расширение предиката обязано быть КОНСЕРВАТИВНЫМ: превратить успех в
    отказ так же плохо, как отказ в успех."""

    def test_success_stays_success(self):
        self.assertFalse(result_is_error({"ok": True, "result": {"count": 2}}))
        self.assertFalse(result_is_error({"result": {"walls": []}}))
        self.assertFalse(result_is_error({"error": False}))
        self.assertFalse(result_is_error({"error": ""}))
        self.assertFalse(result_is_error(None))
        self.assertFalse(result_is_error("plain string"))

    def test_tool_budget_timeout_stays_non_blocking(self):
        """kukai/llm/client.py:1506 держит `error: False` НАМЕРЕННО: C# может
        всё ещё выполняться, и повторять запись нельзя. Предикат обязан этот
        выбор сохранить."""
        self.assertFalse(result_is_error({
            "error": False, "tool_timeout": True,
            "state": "running_unconfirmed",
            "err": {"code": "transport.tool_budget_exceeded"}}))

    def test_real_failures_are_seen(self):
        self.assertTrue(result_is_error({"error": True, "message": "boom"}))
        self.assertTrue(result_is_error({"ok": False, "error": "ops_unaccounted"}))
        self.assertTrue(result_is_error({"ok": False, "diagnostics": []}))
        self.assertTrue(result_is_error({"refused": True}))


class RefusalTellsWhatToChange(_KirRefusalBase):
    """Перевес структурного отказа над текстом исключения C#: причина не
    только НАЗВАНА, но и адресована — какой оп и что в нём поменять."""

    def test_postcondition_refusal_names_the_op_and_the_fix(self):
        res = self._write_refused_at_runtime()
        err = res["err"]
        self.assertEqual(err["code"], "kir.postcondition_violated")
        self.assertEqual(err["kir_code"], "KIR-X004")
        self.assertEqual(err["violations"], ["W1: endpoints (geometry)"])
        self.assertIn("W1: endpoints (geometry)", err["fix"])
        # …и то, что отличает структурный отказ от флаки-инфраструктуры:
        self.assertFalse(err["transient"])
        self.assertTrue(err["retryable"])

    def test_unconfirmed_write_is_not_retryable(self):
        """KIR-X007: запись могла закоммититься. Повтор вслепую = дубль."""
        def execute(_code, op):
            if op == "ground_snapshot":
                return {"result": GROUND_SNAPSHOT}
            return {"state": "timeout_unconfirmed"}
        res = self._handle(_WRITE_PROGRAM, execute)
        self.assertEqual(res["err"]["code"], "kir.unconfirmed")
        self.assertFalse(res["err"]["retryable"])

    def test_compiler_refusal_is_marked_as_program_fault(self):
        res = self._write_refused_by_compiler()
        self.assertEqual(res["err"]["code"], "kir.program_refused")
        self.assertTrue(res["err"]["retryable"])


class ReceiptNamesTheRefusal(unittest.TestCase):
    """Тот самый замеренный `err_code: null`. Квитанция TurnRecord —
    kukai/llm/revit_execution_pipeline.py:548 — на KIR-плече не называла
    отказ, хотя C#-плечо называло (`runtime.revit_exception`)."""

    def _record(self, bridge_result):
        """Тот же стенд, что у штатных тестов конвейера: фальшивый транспорт
        и пройденный compile-gate — меряем ИМЕННО отказ рантайма, а не
        несобравшийся шаблон."""
        from tests.test_revit_execution_pipeline import FakeTransport, make_deps
        from kukai.llm.revit_execution_pipeline import RevitExecutionPipeline
        deps, _transport, _cc = make_deps(
            transport=FakeTransport(results=[bridge_result]))
        pipe = RevitExecutionPipeline(deps)
        return _run(pipe.run_declarative(
            "var x = 1;\nreturn __res;", tool="revit_ir", op="write",
            args={}, timeout_ms=60_000))

    def test_postcondition_refusal_is_named_in_the_receipt(self):
        rec = self._record({"error": "postconditions_violated",
                            "violations": ["W1: endpoints (geometry)"]})
        self.assertFalse(rec.ok)
        self.assertEqual(rec.err_code, "kir.postcondition_violated")
        # …и по-прежнему БЕЗ ремонта: шаблон верифицирован, чинить нечего.
        self.assertEqual(rec.repairs, [])
        self.assertEqual(rec.attempts, 1)

    def test_revit_runtime_refusal_is_named_in_the_receipt(self):
        rec = self._record({"error": "stale_or_failed",
                            "message": "NewFamilyInstance returned null"})
        self.assertFalse(rec.ok)
        self.assertEqual(rec.err_code, "kir.runtime_refused")

    def test_success_receipt_is_untouched(self):
        rec = self._record({"ok": True, "W1": {"id": "9001"}})
        self.assertTrue(rec.ok)
        self.assertIsNone(rec.err_code)


if __name__ == "__main__":
    unittest.main()
