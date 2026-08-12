"""СЕРТИФИКАТ ПЕРЕВОДА В ЖИВОМ ПУТИ ЗАПИСИ — прибор, который наконец включён.

ЧТО БЫЛО НЕ ТАК ДО 09.08.2026.  ``translation_cert`` умеет доказывать, что у
каждого обещанного постусловия есть свидетель и что этот свидетель СПОСОБЕН
сработать (17 форм вакуума, 940 экземпляров опов, 0 находок, обход 3748 из
3748 вердиктов).  При этом ЖИВОЙ ПУТЬ ЗАПИСИ его не звал ни разу: гейт
``KUKAI_IR_TRANSLATION_CERT`` читался только из тестов, и
``tools/capability_map.py`` честно докладывал «НА СКЛАДЕ».  Детектор вакуума,
который никогда не смотрит на настоящую программу, не защищает ничего — это
подпись вместо проверки.

ЧТО ЗАКРЕПЛЕНО ЗДЕСЬ, по одному классу на секцию:

  * РЕЖИМЫ — один флаг, три состояния, и «включён» не может разъехаться с
    «отказывает»;
  * ОТСУТСТВУЮЩЕЕ ОСТАЁТСЯ ОТСУТСТВУЮЩИМ — при снятом флаге путь записи
    байт-в-байт тот же, и сертификатор не вызывается ВООБЩЕ;
  * НАХОДКА ОТКАЗЫВАЕТ ДО ЭФФЕКТА — всаженный вакуумный свидетель заворачивает
    запись типизированной, привязанной к опу диагностикой, и мост не видит
    ничего, кроме ground-снимка;
  * НАБЛЮДЕНИЕ ПИШЕТ, А НЕ ЗАПРЕЩАЕТ — режим ``record`` пропускает ту же
    программу, но квитанция называет находку;
  * МОЛЧАНИЕ ПРИБОРА — НЕ НАХОДКА — оп без ``OpRefinementSpec`` и упавший
    сертификатор НЕ отказывают даже в режиме ``refuse``.  Это ровно граница,
    на которой приёмка когда-то сломалась на кириллице и месяцами
    заворачивала ВЕРНО построенные помещения.
"""
from __future__ import annotations

import asyncio
import contextlib
import copy
import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault(
    "KIR_REJECTIONS_PATH",
    os.path.join(tempfile.gettempdir(), "kir_cert_wiring_queue.jsonl"),
)

from kukai.ir import authoring                                    # noqa: E402
from kukai.ir import serving                                      # noqa: E402
from kukai.ir import translation_cert as tc                       # noqa: E402
from kukai.ir.emit_model import BarePost, WitnessCheck            # noqa: E402
from kukai.ir.tests.acceptance_fakes import (                     # noqa: E402
    PassingAcceptanceBridge,
)
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT               # noqa: E402

_FLAG = "KUKAI_IR_TRANSLATION_CERT"

WRITE_PROGRAM = {"ir_version": "1.0", "ops": [{
    "op": "create_wall",
    "id": "W1",
    "p0_mm": [0, 0],
    "p1_mm": [6000, 0],
    "level": {"by": "element_id", "value": 42},
}]}

#: Саженец: вердикт, который НЕ МОЖЕТ выполниться ни при каком прогоне.
DEAD_VERDICT = '    if (false) __post.Add("never");\n'

def _paths(left, right, prefix: str = "") -> set[str]:
    """Адреса полей, которыми две квитанции РАЗЛИЧАЮТСЯ.

    Списком «волатильных полей» на глаз этот тест писать нельзя: список
    устарел бы молча и превратил бы доказательство в оформление.  Уровень
    шума ЗАМЕРЯЕТСЯ (два прогона при одинаковых условиях), и только потом с
    ним сравнивается эффект флага.
    """

    if isinstance(left, dict) and isinstance(right, dict):
        out: set[str] = set()
        for key in set(left) | set(right):
            out |= _paths(left.get(key), right.get(key), f"{prefix}.{key}")
        return out
    if (isinstance(left, list) and isinstance(right, list)
            and len(left) == len(right)):
        out = set()
        for index, (one, two) in enumerate(zip(left, right)):
            out |= _paths(one, two, f"{prefix}[{index}]")
        return out
    return set() if left == right else {prefix}


@contextlib.contextmanager
def planted(op_name: str, key: str, verdict_cs: str):
    """Всадить вакуумный вердикт в свидетеля ``key`` живого опа ``op_name``.

    Мутация, а не выдуманный словарь: сертифицируется ровно тот эмиттер,
    который в проде пишет C#.
    """

    original = authoring._EMITTERS[op_name]

    def broken(op, ver, stamp, isolation="atomic", _o=original):
        decl, create, post, readback = _o(op, ver, stamp, isolation)
        bare = isinstance(post, BarePost)
        checks = list(post.checks) if bare else list(post)
        out = []
        for check in checks:
            if check.obligation_key != key:
                out.append(check)
                continue
            out.append(WitnessCheck(
                obligation_key=check.obligation_key,
                reader_cs="",
                verdict_cs=verdict_cs,
                message=check.message,
                tol=None,
                style="plain"))
        return decl, create, (BarePost(tuple(out)) if bare else out), readback

    authoring._EMITTERS[op_name] = broken
    try:
        yield
    finally:
        authoring._EMITTERS[op_name] = original


class Modes(unittest.TestCase):
    """Один флаг, три состояния — и они не могут противоречить друг другу."""

    def setUp(self) -> None:
        self._previous = os.environ.get(_FLAG)

    def tearDown(self) -> None:
        if self._previous is None:
            os.environ.pop(_FLAG, None)
        else:
            os.environ[_FLAG] = self._previous

    def _set(self, value) -> None:
        if value is None:
            os.environ.pop(_FLAG, None)
        else:
            os.environ[_FLAG] = value

    def test_default_is_off(self) -> None:
        self._set(None)
        self.assertEqual(tc.certificate_mode(), tc.CERT_MODE_OFF)
        self.assertFalse(tc.certificate_enabled())

    def test_truthy_values_refuse(self) -> None:
        for value in ("1", "true", "yes", "on", "refuse", "REFUSE", " On "):
            with self.subTest(value=value):
                self._set(value)
                self.assertEqual(tc.certificate_mode(), tc.CERT_MODE_REFUSE)
                self.assertTrue(tc.certificate_enabled())

    def test_record_is_on_but_does_not_refuse(self) -> None:
        for value in ("record", "observe", "RECORD"):
            with self.subTest(value=value):
                self._set(value)
                self.assertEqual(tc.certificate_mode(), tc.CERT_MODE_RECORD)
                self.assertTrue(tc.certificate_enabled())

    def test_enabled_and_mode_can_never_disagree(self) -> None:
        """Обратная сторона: НЕТ значения, где прибор «включён», но режима у
        него нет, и нет значения с режимом при выключенном приборе."""

        for value in (None, "", "0", "off", "no", "false", "1", "on", "yes",
                      "true", "refuse", "record", "observe", "мусор", "2"):
            with self.subTest(value=value):
                self._set(value)
                self.assertEqual(
                    tc.certificate_enabled(),
                    tc.certificate_mode() != tc.CERT_MODE_OFF,
                    f"{value!r}: «включён» и режим разъехались")


class _ServingHarness(unittest.TestCase):
    """Живой путь записи с детерминированным мостом (без Revit)."""

    def setUp(self) -> None:
        os.environ["KUKAI_KIR_TOOL"] = "stage2"
        self._device = mock.patch.object(
            serving, "_turn_device_id", return_value=serving.ADMIN_DEVICE)
        self._device.start()
        self.llm = mock.Mock()
        self.llm._revit_version = "2024"
        self._dir = tempfile.TemporaryDirectory()
        self._prev_dir = os.environ.get("KIR_ACCEPTANCE_EVIDENCE_DIR")
        os.environ["KIR_ACCEPTANCE_EVIDENCE_DIR"] = self._dir.name
        self._prev_flag = os.environ.get(_FLAG)
        os.environ.pop(_FLAG, None)

    def tearDown(self) -> None:
        self._device.stop()
        os.environ.pop("KUKAI_KIR_TOOL", None)
        if self._prev_dir is None:
            os.environ.pop("KIR_ACCEPTANCE_EVIDENCE_DIR", None)
        else:
            os.environ["KIR_ACCEPTANCE_EVIDENCE_DIR"] = self._prev_dir
        if self._prev_flag is None:
            os.environ.pop(_FLAG, None)
        else:
            os.environ[_FLAG] = self._prev_flag
        self._dir.cleanup()

    def _write(self) -> tuple[dict, list[str]]:
        """(результат хода, список стадий, которые ВИДЕЛ мост)."""

        acceptance = PassingAcceptanceBridge(WRITE_PROGRAM)
        seen: list[str] = []

        async def execute(_llm, _bridge, _code, op, _timeout_ms):
            seen.append(op)
            if op == "ground_snapshot":
                result = {"result": GROUND_SNAPSHOT}
            else:
                result = {"result": {"ok": True, "W1": {"id": "9001"}}}
            return acceptance.dispatch(lambda _c, _o: result, _code, op)

        with mock.patch.object(
                serving, "_run_declarative", side_effect=execute):
            result = asyncio.run(serving.handle_revit_ir(
                {"program": copy.deepcopy(WRITE_PROGRAM)}, self.llm, None))
        return result, seen


class AbsentStaysAbsent(_ServingHarness):
    """Снятый флаг обязан не менять НИЧЕГО — ни байта, ни вызова."""

    def test_flag_off_never_calls_the_certifier(self) -> None:
        with mock.patch.object(
                serving, "_certify_translation",
                side_effect=AssertionError(
                    "сертификатор вызван при снятом флаге")) as spy:
            result, _seen = self._write()
        self.assertEqual(spy.call_count, 0)
        self.assertTrue(result["ok"])

    def test_flag_off_leaves_no_trace_in_the_receipt(self) -> None:
        result, seen = self._write()
        self.assertTrue(result["ok"])
        self.assertNotIn("certificate", result)
        self.assertNotIn("ground_snapshot", seen[1:])

    def test_a_proven_program_is_byte_identical_apart_from_the_receipt(self):
        """Включённый прибор на ЗДОРОВОМ эмиттере не меняет исход.

        Это половина закона «отсутствующее остаётся отсутствующим»: вторая
        половина — что включение не меняет РЕЗУЛЬТАТ там, где находки нет.
        Если бы меняло, цена включения была бы неизвестна.
        """

        os.environ.pop(_FLAG, None)
        first, _ = self._write()
        second, _ = self._write()
        # УРОВЕНЬ ШУМА, ЗАМЕРЕННЫЙ, А НЕ ОБЪЯВЛЕННЫЙ: два прогона в одинаковых
        # условиях (идентификатор запуска, контрольная сумма журнала,
        # накопительный счётчик здания).
        noise = _paths(first, second)
        self.assertTrue(
            noise, "шума нет вовсе — замер сломан, сравнивать не с чем")

        os.environ[_FLAG] = "1"
        on, _ = self._write()
        moved = _paths(second, on) - noise
        self.assertEqual(
            moved, {".certificate"},
            f"включение прибора сдвинуло квитанцию сверх квитанции: {moved}")

        certificate = on["certificate"]
        self.assertEqual(certificate["status"], "proven")
        self.assertEqual(certificate["mode"], tc.CERT_MODE_REFUSE)
        self.assertFalse(certificate["refused"])
        self.assertEqual(certificate["ops"], 1)
        self.assertIsInstance(certificate["duration_ms"], float)


class AFindingRefusesBeforeAnyEffect(_ServingHarness):
    """Свидетель, который не может упасть, не даёт записи состояться."""

    def test_planted_vacuity_refuses_with_a_typed_op_bound_diagnostic(self):
        os.environ[_FLAG] = "1"
        with planted("create_wall", "endpoints", DEAD_VERDICT):
            result, seen = self._write()

        self.assertFalse(result["ok"])
        self.assertTrue(result["refused"])
        self.assertEqual(result["stage"], "translation_certificate")
        # Отказ не уводит на свободный C#: там свидетеля не будет вовсе.
        self.assertIsNone(result["handoff"])

        lead = result["diagnostics"][0]
        self.assertEqual(lead["code"], "KIR-R002")
        self.assertEqual(lead["op_id"], "W1")
        self.assertEqual(lead["op_index"], 0)
        self.assertEqual(lead["field_name"], "endpoints")
        self.assertEqual(lead["got"], tc.VACUITY_CONSTANT_FALSE)
        self.assertIn("вакуумный свидетель", lead["message_ru"])

        # ЭФФЕКТА НЕТ ПО ПОСТРОЕНИЮ: мост видел ровно ground-снимок и больше
        # ничего — ни чтения приёмки, ни записи.
        self.assertEqual(seen, ["ground_snapshot"])
        self.assertEqual(result["outcome"]["execution"], "not_started")

    def test_the_refusal_carries_a_machine_readable_err(self) -> None:
        os.environ[_FLAG] = "1"
        with planted("create_wall", "endpoints", DEAD_VERDICT):
            result, _ = self._write()
        self.assertEqual(result["err"]["kir_code"], "KIR-R002")
        self.assertEqual(result["err"]["op_id"], "W1")
        self.assertTrue(result["err"]["kir"])

    def test_a_missing_witness_refuses_under_its_own_code(self) -> None:
        """«Свидетеля нет» и «свидетель есть и мёртв» — разные дефекты и
        обязаны приходить под разными кодами."""

        os.environ[_FLAG] = "1"
        original = authoring._EMITTERS["create_wall"]

        def broken(op, ver, stamp, isolation="atomic"):
            decl, create, post, rb = original(op, ver, stamp, isolation)
            bare = isinstance(post, BarePost)
            checks = [c for c in (post.checks if bare else post)
                      if c.obligation_key != "endpoints"]
            return decl, create, (BarePost(tuple(checks)) if bare
                                  else checks), rb

        authoring._EMITTERS["create_wall"] = broken
        try:
            result, seen = self._write()
        finally:
            authoring._EMITTERS["create_wall"] = original

        self.assertFalse(result["ok"])
        self.assertEqual(result["stage"], "translation_certificate")
        codes = {d["code"] for d in result["diagnostics"]}
        self.assertEqual(codes, {"KIR-R001"})
        self.assertEqual(seen, ["ground_snapshot"])


class ObservationRecordsButDoesNotForbid(_ServingHarness):
    """Другое поведение обязано быть достижимо КОНФИГУРАЦИЕЙ, а не правкой."""

    def test_record_mode_lets_the_same_program_through_and_says_so(self):
        os.environ[_FLAG] = "record"
        with planted("create_wall", "endpoints", DEAD_VERDICT):
            result, seen = self._write()

        self.assertTrue(result["ok"], "режим наблюдения не должен запрещать")
        self.assertIn("ground_snapshot", seen)
        self.assertGreater(len(seen), 1, "запись не дошла до моста")

        certificate = result["certificate"]
        self.assertEqual(certificate["mode"], tc.CERT_MODE_RECORD)
        self.assertEqual(certificate["status"], "vacuous")
        self.assertFalse(certificate["refused"])
        # Находка ЗАПИСАНА, а не потеряна: наблюдение без следа — тишина,
        # а тишина неотличима от чистоты.
        self.assertEqual(certificate["diagnostics"][0]["code"], "KIR-R002")
        self.assertEqual(certificate["diagnostics"][0]["op_id"], "W1")


class SilenceOfTheInstrumentIsNotAFinding(_ServingHarness):
    """Граница, на которой «приёмка сломалась на кириллице».

    Прибор, которому НЕ ХВАТИЛО данных, обязан молчать и быть НАЗВАННЫМ, а не
    заворачивать верно построенную программу по нашей собственной бухгалтерии.
    """

    def test_an_op_without_a_refinement_spec_does_not_refuse(self) -> None:
        os.environ[_FLAG] = "1"
        table = tc._ensure_table()
        previous = tc.REFINEMENT
        tc.REFINEMENT = {k: v for k, v in table.items() if k != "create_wall"}
        try:
            result, seen = self._write()
        finally:
            tc.REFINEMENT = previous

        self.assertTrue(result["ok"], "молчание прибора завернуло запись")
        self.assertGreater(len(seen), 1)
        certificate = result["certificate"]
        self.assertEqual(certificate["status"], "uncertifiable")
        self.assertFalse(certificate["refused"])
        self.assertIn("create_wall", certificate["detail"])

    def test_a_crashing_certifier_does_not_refuse(self) -> None:
        os.environ[_FLAG] = "1"
        with mock.patch.object(
                tc, "certify_program",
                side_effect=RuntimeError("прибор сломался")):
            result, seen = self._write()

        self.assertTrue(result["ok"], "сломанный прибор завернул запись")
        self.assertGreater(len(seen), 1)
        certificate = result["certificate"]
        self.assertEqual(certificate["status"], "instrument_failed")
        self.assertFalse(certificate["refused"])
        self.assertIn("RuntimeError", certificate["detail"])

    def test_a_query_is_never_certified(self) -> None:
        """У запроса нет ни свидетеля, ни обязательств: REFINEMENT про него
        не знает по построению, и попытка сертифицировать была бы отказом
        всему читающему пути."""

        os.environ[_FLAG] = "1"

        async def execute(_llm, _bridge, _code, _op, _timeout_ms):
            return {"result": {"Q1": {"total": 0, "rows": []}}}

        with mock.patch.object(
                serving, "_run_declarative", side_effect=execute):
            result = asyncio.run(serving.handle_revit_ir({"program": {
                "ir_version": "1.0",
                "ops": [{"op": "query_count", "id": "Q1", "kind": "wall"}],
            }}, self.llm, None))

        self.assertNotIn("certificate", result)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
