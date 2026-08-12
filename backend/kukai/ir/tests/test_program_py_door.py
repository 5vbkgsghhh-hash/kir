"""ДВЕРЬ ИСХОДНОГО ЯЗЫКА — `program_py` рядом с `ops`.

ЗАЧЕМ ФАЙЛ. Слой исходного языка (`kukai/ir/dsl.py` + `kukai/ir/sandbox.py`)
был построен и проверен 328 + N тестами, и модель им воспользоваться не могла:
двери не было. Здесь проверяется ровно дверь — и главное её свойство:

    НИЖЕ ШЛЮЗА НЕТ НИ ОДНОЙ ВЕТКИ «А ЕСЛИ ЭТО БЫЛ СКРИПТ».

Скрипт превращается в операции РОВНО в одном месте (`serving._authored_input`),
и дальше программа идёт тем же путём, что JSON: `plan_program` → заземление →
эмиссия → свидетель → приёмка → журнал. Тест `test_the_same_program_written_
two_ways_is_byte_identical_below_the_gate` меряет это утверждение, а не
пересказывает: две формы входа обязаны дать ОДИН `plan_digest`.

ЧТО ЕЩЁ ЗДЕСЬ ПРИБИТО:
  * взаимоисключение форм и отказ на «оба»/«ни одного»/«не текст»;
  * `author_digest` доезжает до КВИТАНЦИИ и до ЖУРНАЛА рядом с `plan_digest`;
  * отказ песочницы выходит наружу типизированным, с номером строки МОДЕЛИ,
    и попадает в таксономию `ErrCode` осмысленно (см. «RETRYABLE» ниже);
  * ШОВ БЮДЖЕТОВ: перечисление по-прежнему меряется авторскими 20, а выход
    скрипта — внутренним бюджетом. Это не послабление, а следствие того, ЧТО
    здесь авторская единица; отдельный тест держит обе стороны шва.

RETRYABLE — почему отказ песочницы retryable, а B012 нет. Ответ в двух фактах,
каждый со своим тестом ниже: (1) до моста дело не дошло, эффекта не было,
значит повтор не может задвоить постройку — а `retryable=false` в этой системе
означает ровно «эффект мог случиться»; (2) отказ детерминирован (на этом стоит
`author_digest`), поэтому `transient=false`: ждать бессмысленно, чинят
ИСХОДНИК. B012 переворачивает первое: это НАШ дефект, модели чинить нечего.
"""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_test_queue.jsonl"))

from kukai.ir import compiler, serving  # noqa: E402
from kukai.ir.tests.acceptance_fakes import PassingAcceptanceBridge  # noqa: E402
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


#: Настоящий скрипт: считает эллипс, строит по нему ломаную стену и ПЕЧАТАЕТ
#: расхождение приближения числом. 25 операций из 21 строки — то есть больше
#: авторского бюджета и заведомо меньше внутреннего.
ELLIPSE_SCRIPT = '''
import math
envelope(intent="кольцевая стена по эллипсу")
lvl = create_level(elev_mm=0, name="Отм. 0.000")
N = 24
A, B = 18000.0, 11000.0
def pt(i):
    a = 2 * math.pi * i / N
    return [round(A * math.cos(a)), round(B * math.sin(a))]
per = 0.0
for i in range(N):
    p0, p1 = pt(i), pt(i + 1)
    per += math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    create_wall(p0_mm=p0, p1_mm=p1, height_mm=3300, level=lvl,
                type={"by": "element_id", "value": 100})
ideal = 2 * math.pi * math.sqrt((A * A + B * B) / 2)
print("расхождение ломаной с эллипсом: %.2f%%" % (100 * abs(per - ideal) / ideal))
'''


class _DoorHarness(unittest.TestCase):
    """Гейт открыт, устройство админское, мост подменён — прод-путь целиком."""

    def setUp(self) -> None:
        self._prev_flag = os.environ.get("KUKAI_KIR_TOOL")
        os.environ["KUKAI_KIR_TOOL"] = "stage2"
        self._device = mock.patch.object(
            serving, "_turn_device_id", return_value=serving.ADMIN_DEVICE)
        self._device.start()
        self.llm = mock.Mock()
        self.llm._revit_version = "2026"
        self._acceptance_dir = tempfile.TemporaryDirectory()
        self._prev_acceptance = os.environ.get("KIR_ACCEPTANCE_EVIDENCE_DIR")
        os.environ["KIR_ACCEPTANCE_EVIDENCE_DIR"] = self._acceptance_dir.name
        self._feed_dir = tempfile.TemporaryDirectory()
        self._prev_feed = os.environ.get("KIR_WITNESS_PATH")
        self.feed_path = os.path.join(self._feed_dir.name, "witness.jsonl")
        os.environ["KIR_WITNESS_PATH"] = self.feed_path

    def tearDown(self) -> None:
        self._device.stop()
        for name, prev in (("KUKAI_KIR_TOOL", self._prev_flag),
                           ("KIR_ACCEPTANCE_EVIDENCE_DIR", self._prev_acceptance),
                           ("KIR_WITNESS_PATH", self._prev_feed)):
            if prev is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = prev
        self._acceptance_dir.cleanup()
        self._feed_dir.cleanup()

    # -- вызовы ------------------------------------------------------------
    def _no_bridge(self):
        async def boom(*_a, **_kw):
            raise AssertionError("мост не должен быть тронут")
        return mock.patch.object(serving, "_run_declarative", side_effect=boom)

    def _call_refusing(self, args: dict) -> dict:
        """Вызов, который ОБЯЗАН отказать до моста."""
        with self._no_bridge():
            return _run(serving.handle_revit_ir(args, self.llm,
                                                bridge_callback=None))

    def _call_executing(self, args: dict, *, bulk_plan: bool = True) -> dict:
        """Вызов до конца пути: снапшот, запись, свидетель, приёмка, журнал."""
        state: dict = {}

        async def fake_exec(_llm, _bridge, code, op, _timeout_ms):
            program = state.get("program") or {"ops": []}
            acceptance = state.get("acceptance")
            if acceptance is None:
                acceptance = state["acceptance"] = PassingAcceptanceBridge(
                    program, bulk=bulk_plan)

            def execute(_code, stage):
                if stage == "ground_snapshot":
                    return {"result": GROUND_SNAPSHOT}
                payload: dict = {"ok": True}
                for index, row in enumerate(program.get("ops") or []):
                    payload[row["id"]] = {"id": 900_000 + index}
                return {"result": payload}

            return acceptance.dispatch(execute, code, op)

        async def go():
            # Мосту нужна та же программа, что уйдёт в тело: получаем её ТЕМ
            # ЖЕ шлюзом, а не вторым разбором скрипта.
            authored = await serving._authored_input(dict(args))
            if authored.refusal is None:
                state["program"] = authored.args["program"]
            with mock.patch.object(serving, "_run_declarative",
                                   side_effect=fake_exec):
                return await serving.handle_revit_ir(args, self.llm,
                                                     bridge_callback=None)
        return _run(go())

    def _journal_rows(self) -> list[dict]:
        if not os.path.exists(self.feed_path):
            return []
        with open(self.feed_path, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]


# ═════════════════════════════════════════════════════════════════════════════
# ДВЕРЬ РАБОТАЕТ
# ═════════════════════════════════════════════════════════════════════════════

class TheDoorOpens(_DoorHarness):

    def test_a_script_becomes_a_program_and_goes_the_whole_way(self) -> None:
        result = self._call_executing({"program_py": ELLIPSE_SCRIPT})
        self.assertTrue(result["ok"], result)
        # весь путь, а не только шлюз: свидетель и НЕЗАВИСИМАЯ приёмка
        # Тройка — поимённо: см. ту же правку в `test_v11_regressions`.
        for axis in ("geometry_ok", "semantic_ok", "topology_ok"):
            self.assertIs(result["witness"][axis], True, axis)
        self.assertIn("unwitnessed_axes", result["witness"])
        self.assertEqual(result["outcome"]["execution"], "committed")
        self.assertEqual(result["outcome"]["acceptance"], "accepted")

    def test_the_receipt_carries_the_signature_of_the_source(self) -> None:
        """`author_digest` рядом с `plan_digest` — новая доказуемость.

        Квитанция обязана читаться как «эта программа порождена вот этим
        скриптом»: подпись плана даёт приёмка, подпись исходника — этот блок.
        """
        result = self._call_executing({"program_py": ELLIPSE_SCRIPT})
        source = result["program_source"]
        self.assertEqual(source["language"], "python")
        self.assertEqual(len(source["author_digest"]), 64)
        self.assertEqual(len(source["program_digest"]), 64)
        self.assertEqual(source["op_count"], 25)
        # …и обе подписи лежат в ОДНОЙ квитанции, иначе связать их нечем
        self.assertEqual(len(result["acceptance"]["plan_digest"]), 64)

    def test_the_print_of_the_script_comes_back_to_the_model(self) -> None:
        """Образцы формы печатают ЧИСЛОМ расхождение приближения. Отрезать
        этот канал значит вернуть «сказал синус, построил ломаную, промолчал».
        """
        result = self._call_executing({"program_py": ELLIPSE_SCRIPT})
        self.assertIn("расхождение ломаной с эллипсом",
                      result["program_source"]["stdout"])

    def test_the_signature_is_of_the_bytes_and_moves_with_them(self) -> None:
        """Подпись — исходника, а не замысла: пробел меняет её."""
        first = self._call_executing({"program_py": ELLIPSE_SCRIPT})
        second = self._call_executing({"program_py": ELLIPSE_SCRIPT + "\n"})
        self.assertNotEqual(first["program_source"]["author_digest"],
                            second["program_source"]["author_digest"])
        # …а программа при этом ТА ЖЕ: подписи двух разных вещей независимы
        self.assertEqual(first["program_source"]["program_digest"],
                         second["program_source"]["program_digest"])

    def test_the_journal_gets_the_author_digest_beside_the_plan_digest(self) -> None:
        """Журнал — то же правило, что у квитанции. `plan_digest` отвечает
        «что скомпилировано», `author_digest` — «чем это написано»."""
        result = self._call_executing({"program_py": ELLIPSE_SCRIPT})
        rows = self._journal_rows()
        self.assertEqual(len(rows), 1, rows)
        row = rows[0]
        self.assertEqual(row["author_digest"],
                         result["program_source"]["author_digest"])
        self.assertEqual(row["authored_in"], "python")
        self.assertEqual(len(row["plan_digest"]), 64)

    def test_a_json_program_carries_no_authorship_at_all(self) -> None:
        """Пустая строка в корпусе читалась бы как «скрипт был и не
        подписался». Поля нет вовсе."""
        program = {"ir_version": "1.0", "ops": [
            {"op": "query_count", "id": "q", "kind": "wall"}]}
        result = self._call_executing({"program": program}, bulk_plan=False)
        self.assertTrue(result["ok"], result)
        self.assertNotIn("program_source", result)
        row = self._journal_rows()[0]
        self.assertNotIn("author_digest", row)
        self.assertNotIn("authored_in", row)

    def test_the_envelope_the_script_set_survives_the_gate(self) -> None:
        """`intent`/`defaults` — то, что автор НАЗВАЛ явно. Пересобирать
        конверт на глазок значит потерять названное."""
        script = (
            'envelope(intent="этаж", defaults={"symbol": {"by": "element_id", '
            '"value": 1101}})\n'
            'lvl = create_level(elev_mm=0, name="L")\n'
            'create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], height_mm=3000, '
            'level=lvl)\n')
        authored = _run(serving._authored_input({"program_py": script}))
        self.assertIsNone(authored.refusal)
        self.assertEqual(authored.args["program"]["intent"], "этаж")
        self.assertEqual(authored.args["program"]["defaults"],
                         {"symbol": {"by": "element_id", "value": 1101}})

    def test_defaults_cannot_fill_a_required_selector_and_the_doc_says_so(self):
        """ЗАМЕР 03.08, ИЗ-ЗА КОТОРОГО В ОПИСАНИИ СТОИТ ОГОВОРКА.

        Конверт `defaults` заполняет ТОЛЬКО ОПУЩЕННОЕ поле (замерено ниже:
        опущенный `level` получает значение конверта, а явный `{"by":
        "default"}` — нет). В языке же `level` — ОБЯЗАТЕЛЬНЫЙ аргумент, и
        опустить его питон не даст. Значит совет «селектор один на программу
        — его место в `defaults`», верный для поля `program`, в скрипте стоил
        бы раунда — с 04.08 это KIR-P005 (до того был голый питоновский
        `TypeError: missing a required argument`, назвавший один слот из
        десяти; см. `dsl._bind_refusal`).

        Тест держит обе половины: замер поведения и то, что описание
        инструмента о нём ПРЕДУПРЕЖДАЕТ.
        """
        base = {"op": "create_wall", "id": "w1", "p0_mm": [0, 0],
                "p1_mm": [6000, 0], "height_mm": 3000}
        envelope = {"level": {"by": "name", "value": "Этаж 1"}}
        omitted = compiler.plan_program(
            {"ir_version": "1.0", "defaults": envelope, "ops": [dict(base)]})
        self.assertEqual(omitted.to_ops()[0]["level"], envelope["level"])
        explicit = compiler.plan_program({
            "ir_version": "1.0", "defaults": envelope,
            "ops": [{**base, "level": {"by": "default"}}]})
        self.assertEqual(explicit.to_ops()[0]["level"], {"by": "default"})

        # …а в скрипте обязательный аргумент не опускается вовсе
        refused = _run(serving._authored_input({"program_py": (
            'envelope(defaults={"level": {"by": "name", "value": "Этаж 1"}})\n'
            'create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], height_mm=3000)\n')}))
        self.assertIsNotNone(refused.refusal)
        message = refused.refusal["message_ru"]
        self.assertIn("KIR-P005", message)
        self.assertIn("level", message)
        # Отказ обязан довести до следующего хода, а не только назвать слот.
        self.assertIn("СЛЕДУЮЩИЙ ХОД", message)

        from kukai.ir.tool_doc import build_tool_description
        self.assertIn("заполняет только ОПУЩЕННОЕ поле",
                      build_tool_description())


# ═════════════════════════════════════════════════════════════════════════════
# ОДИН ПУТЬ НИЖЕ ШЛЮЗА — главное утверждение архитектуры, замеренное
# ═════════════════════════════════════════════════════════════════════════════

class OnePathBelowTheGate(_DoorHarness):

    #: Одна и та же программа, написанная двумя способами.
    OPS = [
        {"op": "create_level", "id": "level1", "elev_mm": 0, "name": "L"},
        {"op": "create_wall", "id": "wall1", "p0_mm": [0, 0],
         "p1_mm": [6000, 0], "height_mm": 3000,
         "level": {"by": "ref", "value": "level1"}},
    ]
    SCRIPT = ('lvl = create_level(elev_mm=0, name="L")\n'
              'create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], height_mm=3000, '
              'level=lvl)\n')

    def test_the_same_program_written_two_ways_is_identical_below_the_gate(self):
        """ДВЕ ФОРМЫ ВХОДА — ОДНО ДОКАЗАТЕЛЬСТВО.

        `plan_digest` покрывает не только payload, но и типизированные
        контракты реестра. Совпадение дайджестов означает, что ниже шлюза
        компилятор получил ТУ ЖЕ вещь — то есть ветки «а если это был скрипт»
        там действительно нет.
        """
        from_json = compiler.plan_program(
            {"ir_version": "1.0", "ops": self.OPS}, bulk=True)
        authored = _run(serving._authored_input({"program_py": self.SCRIPT}))
        self.assertIsNone(authored.refusal,
                          authored.refusal and authored.refusal["message_ru"])
        from_script = compiler.plan_program(authored.args["program"], bulk=True)
        self.assertEqual(from_script.plan_digest, from_json.plan_digest)

    def test_the_gate_is_the_only_place_that_knows_about_python(self) -> None:
        """СТРУКТУРНО, А НЕ ПО ДОГОВОРУ: тело инструмента не вправе спрашивать
        про скрипт. Единственное, что оно знает, — какой БЮДЖЕТ мерить
        (`authored_in_python`) и чем подписан журнал (`author_digest`); ни
        одной развилки исполнения по языку происхождения быть не может.
        """
        import inspect
        body = inspect.getsource(serving._handle_revit_ir_inner)
        self.assertNotIn("program_py", body)
        self.assertNotIn("sandbox", body)
        self.assertNotIn("execute_author_script", body)
        # …а имена, которые тело всё-таки знает, встречаются наперечёт
        self.assertEqual(body.count("authored_in_python"), 2)


# ═════════════════════════════════════════════════════════════════════════════
# ФОРМЫ ВХОДА ВЗАИМОИСКЛЮЧАЮЩИ
# ═════════════════════════════════════════════════════════════════════════════

class ExactlyOneForm(_DoorHarness):

    def _form_refusal(self, args: dict) -> dict:
        result = self._call_refusing(args)
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["error"], "program_form", result)
        self.assertEqual(result["err"]["code"], "tool.invalid_args")
        # чинится правкой ВЫЗОВА, и повтор безопасен по построению
        self.assertTrue(result["err"]["retryable"])
        self.assertIsNone(result["handoff"])
        return result

    def test_both_forms_at_once_is_a_typed_refusal(self) -> None:
        result = self._form_refusal({
            "program": {"ir_version": "1.0", "ops": [
                {"op": "query_count", "id": "q", "kind": "wall"}]},
            "program_py": 'create_level(elev_mm=0, name="L")'})
        self.assertIn("СРАЗУ", result["message_ru"])

    def test_neither_form_is_a_typed_refusal(self) -> None:
        """Раньше такой вызов доезжал до компилятора и получал «программа
        отклонена компилятором» — неправду: программы не присылали."""
        result = self._form_refusal({})
        self.assertIn("program_py", result["message_ru"])

    def test_a_script_that_is_not_text_is_named_by_its_type(self) -> None:
        result = self._form_refusal({"program_py": ["create_level()"]})
        self.assertIn("list", result["message_ru"])

    def test_the_schema_offers_both_and_says_the_rule(self) -> None:
        tools: list = []
        serving.inject_revit_ir_schema(tools)
        params = tools[0]["function"]["parameters"]
        self.assertEqual(sorted(params["properties"]), ["program", "program_py"])
        self.assertEqual(params["properties"]["program_py"]["type"], "string")
        # «ровно одно из двух» названо словами, потому что `required` этого
        # не выражает, а `oneOf` в корне никто из инструментов ещё не возил
        self.assertIn("РОВНО ОДНИМ", params["description"])
        self.assertNotIn("required", params)


# ═════════════════════════════════════════════════════════════════════════════
# ОТКАЗ ПЕСОЧНИЦЫ ВЫХОДИТ НАРУЖУ НЕИСКАЖЁННЫМ
# ═════════════════════════════════════════════════════════════════════════════

class SandboxRefusalsReachTheModel(_DoorHarness):

    def _refuse(self, script: str) -> dict:
        result = self._call_refusing({"program_py": script})
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["stage"], "author_script")
        return result

    def test_a_syntax_error_names_the_line_of_the_model(self) -> None:
        result = self._refuse("create_wall(p0_mm=[0,0], p1_mm=[6000,0]\n")
        diagnostic = result["diagnostics"][0]
        self.assertEqual(diagnostic["code"], "KIR-B001")
        self.assertEqual(diagnostic["script_line"], 1)
        self.assertIn("create_wall", diagnostic["script_line_text"])
        # строка видна и в тексте, который читает модель, и в err.fix
        self.assertIn("строка 1", result["message_ru"])
        self.assertIn("строка 1", result["err"]["fix"])

    def test_a_runtime_error_names_the_line_inside_the_loop(self) -> None:
        result = self._refuse(
            'lvl = create_level(elev_mm=0, name="L")\n'
            'for i in range(3):\n'
            '    create_wall(p0_mm=[0,0], p1_mm=[6000/i, 0], height_mm=3000, '
            'level=lvl)\n')
        diagnostic = result["diagnostics"][0]
        self.assertEqual(diagnostic["code"], "KIR-B006")
        self.assertEqual(diagnostic["kind"], "ZeroDivisionError")
        self.assertEqual(diagnostic["script_line"], 3)

    def test_a_foreign_import_teaches_instead_of_forbidding(self) -> None:
        """Отказ обязан УЧИТЬ: «не разрешён» модель прочитает как каприз и
        попробует соседний модуль."""
        result = self._refuse("import numpy as np\n")
        diagnostic = result["diagnostics"][0]
        self.assertEqual(diagnostic["code"], "KIR-B004")
        self.assertIn("math, itertools, functools", result["message_ru"])

    def test_no_frame_of_ours_leaks_into_the_refusal(self) -> None:
        """Модели чинить надо СВОЙ код: наши кадры в отказе — это ремонт не
        по адресу."""
        result = self._refuse("create_wall(p0_mm=[0,0])\n")
        text = json.dumps(result, ensure_ascii=False)
        for ours in ("kukai/ir", "site-packages", "Traceback (most recent",
                     "sandbox.py", "dsl.py"):
            self.assertNotIn(ours, text)

    def test_the_bridge_is_never_touched_by_a_refused_script(self) -> None:
        """Само по себе: `_no_bridge` роняет вызов, поэтому зелёный тест ЕСТЬ
        доказательство, что до моста дело не дошло. На этом стоит ответ про
        retryable."""
        self._refuse("while True:\n    pass\n")

    # -- таксономия --------------------------------------------------------

    def test_every_sandbox_code_has_a_deliberate_taxonomy_row(self) -> None:
        """Ни одного кода «по умолчанию»: каждый разобран поимённо."""
        from kukai.ir import diag
        declared = {value for name, value in vars(diag).items()
                    if name.startswith("SANDBOX_") and isinstance(value, str)}
        self.assertEqual(declared - set(serving._KIR_B_TO_ERRCODE), set())
        self.assertEqual(set(serving._KIR_B_TO_ERRCODE) - declared, set())

    def test_an_author_refusal_is_retryable_and_not_transient(self) -> None:
        """ОТВЕТ ПРО RETRYABLE, ПРИБИТЫЙ ЧИСЛОМ.

        retryable=True — потому что эффекта НЕ БЫЛО (тест выше это и меряет:
        мост роняет вызов). Запрет на повтор в этой системе защищает от
        задвоения постройки, а задваивать нечего.
        transient=False — потому что тот же исходник даст ту же ошибку; на
        этом же стоит `author_digest`. Ждать бессмысленно, чинят исходник.
        """
        result = self._refuse("import numpy\n")
        self.assertEqual(result["err"]["code"], "kir.program_refused")
        self.assertTrue(result["err"]["retryable"])
        self.assertFalse(result["err"]["transient"])
        self.assertTrue(result["err"]["kir"])
        self.assertEqual(result["err"]["kir_code"], "KIR-B004")

    def test_our_own_defect_is_not_retryable_and_says_what_to_do(self) -> None:
        """B012 — единственный, у кого `blame="sandbox"`. Модели чинить
        нечего, и «retryable» отправило бы её переписывать исправный скрипт."""
        from kukai.ir.sandbox import SandboxRefusal, SandboxResult

        broken = SandboxResult(
            ok=False, author_digest="a" * 64,
            refusal=SandboxRefusal(
                code="KIR-B012", kind="NamespaceUnavailable", blame="sandbox",
                message_ru="сетевое пространство имён не создано"))
        with mock.patch("kukai.ir.sandbox.execute_author_script",
                        return_value=broken):
            result = self._call_refusing({"program_py": "create_level()"})
        self.assertEqual(result["diagnostics"][0]["blame"], "sandbox")
        self.assertEqual(result["err"]["code"], "internal.unhandled")
        self.assertFalse(result["err"]["retryable"])
        self.assertFalse(result["err"]["transient"])
        # …и НАЗЫВАЕТ вторую форму входа: песочница этой фразы произнести не
        # может, она не знает про поле `program`
        self.assertIn("`program`", result["message_ru"])

    def test_a_refused_script_still_signs_its_source(self) -> None:
        """Подпись исходника, который НЕ собрался, — такое же свидетельство."""
        result = self._refuse("import numpy\n")
        self.assertEqual(len(result["program_source"]["author_digest"]), 64)
        self.assertEqual(result["program_source"]["op_count"], 0)
        self.assertNotIn("program_digest", result["program_source"])

    def test_the_receipt_reports_measured_isolation_not_intent(self) -> None:
        result = self._refuse("import numpy\n")
        isolation = result["program_source"]["isolation"]
        self.assertIn("namespaces", isolation)
        self.assertIn("filesystem", isolation)
        self.assertIn("network_probe", isolation)

    def test_determinism_is_measured_on_the_production_path(self) -> None:
        """`replay_check` включён в проде: подпись, которую никто не
        проверял, — обещание, а не доказательство."""
        self.assertTrue(serving._sandbox_policy().replay_check)
        result = self._call_executing({"program_py": ELLIPSE_SCRIPT})
        self.assertTrue(result["program_source"]["replay_checked"])


# ═════════════════════════════════════════════════════════════════════════════
# ШОВ БЮДЖЕТОВ — обе стороны, поимённо
# ═════════════════════════════════════════════════════════════════════════════

class TheBudgetSeamAfterTheSourceLayer(_DoorHarness):
    """ЕДИНИЦА АВТОРСТВА РЕШАЕТ, КАКОЙ БЮДЖЕТ ЕЁ МЕРЯЕТ.

    Авторский бюджет (20) меряет ПЕРЕЧИСЛЕНИЕ, написанное моделью. Когда
    прислали СКРИПТ, авторская вещь — его строки, а операции написал фронт-энд,
    и мерить их авторским бюджетом — тот же стык, что стоил 318 раундов вместо
    26 на пересборке Snowdon (30.07). Поэтому выход скрипта меряется внутренним
    бюджетом — и ТОЛЬКО он: политика компиляции не меняется ничем.
    """

    def _script_of(self, count: int) -> str:
        return (f"for i in range({count}):\n"
                f"    query_count(kind='wall')\n")

    def test_enumeration_still_hits_the_authored_budget(self) -> None:
        """Сторона, которую нельзя ослаблять: поле `program` как было."""
        ops = [{"op": "query_count", "id": f"q{i}", "kind": "wall"}
               for i in range(compiler.MAX_OPS_PER_PROGRAM + 1)]
        result = self._call_refusing({"program": {"ir_version": "1.0",
                                                  "ops": ops}})
        self.assertFalse(result["ok"])
        diagnostic = result["diagnostics"][0]
        self.assertEqual(diagnostic["code"], "KIR-L001")
        self.assertEqual(diagnostic["expected"],
                         f"<={compiler.MAX_OPS_PER_PROGRAM}")

    def test_a_script_may_exceed_the_authored_budget(self) -> None:
        """Иначе дверь бесполезна: скрипт, который умеет ровно двадцать
        операций, строго хуже двадцати написанных руками."""
        count = compiler.MAX_OPS_PER_PROGRAM + 5
        authored = _run(serving._authored_input(
            {"program_py": self._script_of(count)}))
        self.assertIsNone(authored.refusal)
        result = self._call_executing({"program_py": self._script_of(count)})
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["program_source"]["op_count"], count)

    def test_a_script_stops_at_the_internal_budget_and_names_it(self) -> None:
        """Потолок стоит и в языке (`dsl._append`), и он НАЗЫВАЕТ, что делать
        дальше: чанкование прямого хода."""
        result = self._call_refusing(
            {"program_py": self._script_of(compiler.MAX_BULK_OPS + 1)})
        self.assertFalse(result["ok"])
        diagnostic = result["diagnostics"][0]
        self.assertEqual(diagnostic["code"], "KIR-B006")
        self.assertIn(str(compiler.MAX_BULK_OPS), result["message_ru"])
        self.assertIn("чанкование", result["message_ru"])

    def test_the_post_expansion_ceiling_is_untouched(self) -> None:
        """`MAX_VALIDATED_OPS` — предел эмиттера, а не политика: его не
        поднимает ни одна дверь и ни одна форма входа."""
        self.assertEqual(compiler.MAX_VALIDATED_OPS, 320)
        result = self._call_refusing(
            {"program_py": self._script_of(compiler.MAX_VALIDATED_OPS + 1)})
        self.assertFalse(result["ok"])

    def test_a_script_does_not_buy_per_op_isolation(self) -> None:
        """ПОДНЯТ РОВНО БЮДЖЕТ. Скрипт компилируется `compile_program`
        (одна транзакция, строгие постусловия, откат целиком), а НЕ
        `compile_rebuild_chunk` с per-op изоляцией и режимом report: частично
        закоммиченная программа правом скрипта не становится.
        """
        seen: list = []
        real = compiler.compile_rebuild_chunk

        def spy(*args, **kwargs):
            seen.append(kwargs)
            return real(*args, **kwargs)

        with mock.patch.object(compiler, "compile_rebuild_chunk", spy):
            result = self._call_executing({"program_py": ELLIPSE_SCRIPT})
        self.assertTrue(result["ok"], result)
        self.assertEqual(seen, [], "скрипт пошёл политикой ПЕРЕСБОРКИ чанка")

    def test_the_chat_signature_still_cannot_express_bulk(self) -> None:
        """Закон `test_op_budget_seam` остаётся дословно верен: бюджет
        перечисления не поднимает ни одно поле и ни один параметр."""
        import inspect
        forbidden = ("bulk", "internal", "channel", "budget", "cap", "chunk")
        for name in inspect.signature(serving.handle_revit_ir).parameters:
            self.assertFalse(any(tok in name.lower() for tok in forbidden), name)


if __name__ == "__main__":
    unittest.main()
