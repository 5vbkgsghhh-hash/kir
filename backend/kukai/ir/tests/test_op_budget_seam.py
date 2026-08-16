"""ШОВ ДВУХ БЮДЖЕТОВ ОПЕРАЦИЙ — сделан явным и проверяемым.

ЖИВОЙ СЛУЧАЙ 30.07, из-за которого файл существует. Публичный образец
Autodesk (Snowdon Towers Sample Plumbing) разобран и собран заново живьём:
6 343 элемента, 318 программ, 318 успешных. Круг замкнулся — и обошёлся в
318 раундов вместо ожидаемых ~26.

Причина — НЕ скорость и НЕ язык, а стык. У системы ДВА бюджета операций:

* ``MAX_OPS_PER_PROGRAM = 100`` — АВТОРСКИЙ бюджет: столько операций может
  быть в программе, написанной моделью. Он намеренно мал и намеренно невидим
  для LLM (см. ``tool_doc``): модель, которой разрешили писать программы по
  триста операций, — другой продукт с другими рисками.
* ``MAX_BULK_OPS = 300``       — ВНУТРЕННИЙ бюджет: столько операций держит
  чанк материализатора (``decompile/materialize._pack_groups``), который
  никто не писал руками — он собран из разбора живой модели.

Разборщик резал чанки по 250 опов. Единственная живая дверь
(``serving.handle_revit_ir``) звала ``compile_program`` БЕЗ ``bulk`` — то
есть мерила ВСЁ авторским бюджетом 20. Половины системы считали по разным
бюджетам, и драйверу пересборки пришлось резать по 20.

Замер по сохранённому разбору (``snowdon_plumb_v2/tree.json``, 6 544 листа
L1): chunk_target=20 даёт 317 программ, умолчание материализатора — 26; опов
в обоих случаях 6 335.

Тесты ниже:
  ДЕФЕКТ    чанк размера материализатора проходит ВНУТРЕННЕЙ дверью
            (до починки внутренней двери не существовало вовсе), и он же —
            целиком через тело запроса драйвера в /admin/kir/run;
  ЧАТ       чат-дверь по-прежнему упирается в 20 и НИ ОДНО входное поле её
            не поднимает — невозможность по построению (сигнатура), а не по
            договорённости;
  ШОВ       предельный размер чанка материализатора и потолок, который
            принимает живая дверь во внутреннем режиме, — ОДНО число. Оба
            конца замеряются ПОВЕДЕНЧЕСКИ (дверь сама называет свой бюджет в
            типизированном отказе), поэтому тест валит сборку, если бюджеты
            снова разъедутся — даже если оба литерала «совпадают на глаз».
"""
from __future__ import annotations

import ast
import asyncio
import inspect
import os
import pathlib
import re
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_test_queue.jsonl"))

from kukai.ir import compiler, serving  # noqa: E402
from kukai.ir.decompile import materialize  # noqa: E402
from kukai.ir.decompile.l1_schema import stable_l1_id  # noqa: E402
from kukai.ir.decompile.materialize import leaves_to_program  # noqa: E402
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT  # noqa: E402
from kukai.ir.tests.acceptance_fakes import PassingAcceptanceBridge  # noqa: E402
from kukai.ir.tests.gate_fixture import enter_kir_mode

_BACKEND = pathlib.Path(__file__).resolve().parents[3]


def _run(coro):
    return asyncio.run(coro)


def _referenced_names(path: pathlib.Path) -> set[str]:
    """Имена, к которым модуль ОБРАЩАЕТСЯ (а не упоминает в прозе).

    Разбор AST, а не поиск подстроки: комментарий и докстринг, объясняющие
    внутреннюю дверь, — это не вызов. Строковый литерал, РАВНЫЙ имени, ловится
    отдельно: `getattr(serving, "handle_revit_ir_bulk")` — то же обращение."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.alias):
            names.add(node.name.rsplit(".", 1)[-1])
            if node.asname:
                names.add(node.asname)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            names.add(node.value)
    return names


def _query_ops(count: int) -> list[dict]:
    """Читающие опы: у них нет ground-стадии, поэтому проба бюджета не ходит
    на мост за снапшотом. Бюджет считается ДО семейства опа — читающая
    программа меряет ровно тот же потолок, что и пишущая."""
    return [{"op": "query_count", "id": f"q{index}", "kind": "wall"}
            for index in range(count)]


def _wall_ops(count: int) -> list[dict]:
    """Пишущие опы под общий фикстурный снапшот (level 42, wall_type 100)."""
    return [
        {
            "op": "create_wall", "id": f"w{index}",
            "p0_mm": [float(index) * 6000.0, 0.0],
            "p1_mm": [float(index) * 6000.0 + 5000.0, 0.0],
            "level": {"by": "element_id", "value": 42},
            "height_mm": 2800.0,
            "type": {"by": "element_id", "value": 100},
        }
        for index in range(count)
    ]


def _wall_leaves(count: int, base_id: int = 2000) -> list[dict]:
    """L1-листья разбора — вход материализатора (форма из lift.py)."""
    leaves = []
    for index in range(count):
        x = float(index) * 6000.0
        source_id = str(base_id + index)
        leaves.append({
            "kind": "op",
            "op_name": "create_wall",
            "_id": stable_l1_id("op", source_id),
            "type_name": "T",
            "params": {
                "p0_mm": [x, 0.0],
                "p1_mm": [x + 5000.0, 0.0],
                "level": {"by": "name", "value": "L1", "_id": "500"},
                "height_mm": 2800.0,
                "type": {"by": "name", "value": "W200", "_id": "600"},
            },
            "source_element_id": source_id,
            "level_name": "L1",
            "anchor_mm": [x + 2500.0, 0.0, 0.0],
        })
    return leaves


class _DoorHarness(unittest.TestCase):
    """Общий стенд: гейт stage-2 открыт, устройство админское, мост подменён.

    Обе двери зовутся ОДИНАКОВО — разница между ними должна быть в них самих,
    а не в том, как их зовут из теста."""

    def setUp(self) -> None:
        self._prev_flag = os.environ.get("KUKAI_KIR_TOOL")
        os.environ["KUKAI_KIR_TOOL"] = "stage2"
        self._device = mock.patch.object(
            serving, "_turn_device_id", return_value=serving.ADMIN_DEVICE)
        self._device.start()
        self.llm = mock.Mock()
        self.llm._revit_version = "2026"
        self._acceptance_dir = tempfile.TemporaryDirectory()
        self._prev_acceptance_dir = os.environ.get(
            "KIR_ACCEPTANCE_EVIDENCE_DIR")
        os.environ["KIR_ACCEPTANCE_EVIDENCE_DIR"] = self._acceptance_dir.name
        # ТРЕТЬЕ УСЛОВИЕ ГЕЙТА (13.08): режим КИР ставится ЯВНО.
        enter_kir_mode(self)

    def tearDown(self) -> None:
        self._device.stop()
        if self._prev_flag is None:
            os.environ.pop("KUKAI_KIR_TOOL", None)
        else:
            os.environ["KUKAI_KIR_TOOL"] = self._prev_flag
        if self._prev_acceptance_dir is None:
            os.environ.pop("KIR_ACCEPTANCE_EVIDENCE_DIR", None)
        else:
            os.environ["KIR_ACCEPTANCE_EVIDENCE_DIR"] = (
                self._prev_acceptance_dir)
        self._acceptance_dir.cleanup()

    def _call(self, door, program: dict, args: dict | None = None) -> dict:
        acceptance = PassingAcceptanceBridge(
            program, bulk=door is serving.handle_revit_ir_bulk)

        async def fake_exec(_llm, _bridge, _code, op, _timeout_ms):
            def execute(code, stage):
                if stage == "ground_snapshot":
                    return {"result": GROUND_SNAPSHOT}
                payload: dict = {"ok": True}
                for index, row in enumerate(program.get("ops") or []):
                    payload[row["id"]] = {"id": 900_000 + index}
                return {"result": payload}

            return acceptance.dispatch(execute, _code, op)

        with mock.patch.object(serving, "_run_declarative",
                               side_effect=fake_exec):
            return _run(door(args if args is not None else {"program": program},
                             self.llm, bridge_callback=None))

    def _budget_diagnostic(self, result: dict) -> dict:
        self.assertFalse(result["ok"], result)
        diagnostics = result.get("diagnostics") or []
        self.assertTrue(diagnostics, result)
        self.assertEqual(diagnostics[0]["code"], "KIR-L001", diagnostics[0])
        return diagnostics[0]


# ---------------------------------------------------------------------------
# ДЕФЕКТ — тот самый, замеренный живьём
# ---------------------------------------------------------------------------


class TheLiveDefect(_DoorHarness):
    #: Ровно то, чем режет материализатор по умолчанию (``chunk_target``).
    CHUNK = 250

    def test_chat_door_refuses_a_materializer_sized_chunk(self) -> None:
        """Это НЕ дефект, а замысел: чат меряет авторским бюджетом."""
        result = self._call(serving.handle_revit_ir,
                            {"ir_version": "1.0", "ops": _wall_ops(self.CHUNK)})
        diagnostic = self._budget_diagnostic(result)
        self.assertEqual(diagnostic["expected"],
                         f"<={compiler.MAX_OPS_PER_PROGRAM}")

    def test_internal_door_runs_a_materializer_sized_chunk(self) -> None:
        """ДЕФЕКТ 30.07: такой двери не было, и 6 343 элемента стоили 318
        раундов вместо 26."""
        program = {"ir_version": "1.0", "ops": _wall_ops(self.CHUNK)}
        result = self._call(serving.handle_revit_ir_bulk, program)
        self.assertTrue(result["ok"], result)
        self.assertTrue(result.get("kir"))

    def test_internal_door_is_the_single_rebuild_policy_point(self) -> None:
        """Внутренняя дверь обязана компилировать чанк ТЕМ ЖЕ помощником, что
        сухой гейт (``compile_rebuild_chunk``): bulk+per_op+de-join — один
        факт, названный один раз. Отдельные флаги на каждом вызове уже
        расходились трижды (21.07)."""
        seen: list[dict] = []
        real = compiler.compile_rebuild_chunk

        def spy(program, *args, **kwargs):
            seen.append({"args": args, "kwargs": kwargs})
            return real(program, *args, **kwargs)

        program = {"ir_version": "1.0", "ops": _wall_ops(25)}
        with mock.patch.object(compiler, "compile_rebuild_chunk", spy):
            result = self._call(serving.handle_revit_ir_bulk, program)
        self.assertTrue(result["ok"], result)
        self.assertEqual(len(seen), 1, "внутренняя дверь звала не тот вход")

    def test_internal_door_emits_per_op_isolation(self) -> None:
        """Следствие политики: чанк идёт по-оповой изоляцией и БЕЗ авто-стыка
        стен. Проверяется по C#, а не по флагам: флаг можно передать и не
        применить."""
        program = {"ir_version": "1.0", "ops": _wall_ops(3)}
        chat = compiler.compile_program(program, "2026",
                                        snapshot=GROUND_SNAPSHOT)
        internal = compiler.compile_rebuild_chunk(program, "2026",
                                                  snapshot=GROUND_SNAPSHOT)
        self.assertTrue(chat.ok and internal.ok)
        self.assertNotIn("SubTransaction", chat.csharp)
        self.assertIn("SubTransaction", internal.csharp)
        self.assertIn("DisallowWallJoin", internal.csharp)

    def test_partial_chunk_is_refused_not_blessed(self) -> None:
        """ЦЕНА по-оповой изоляции, зафиксированная явно: часть чанка может
        закоммититься, а часть — нет. Дверь обязана сказать ok=false и НАЗВАТЬ
        оп без идентичности, а не выдать молчаливый успех.

        Квитанция при этом теряет уже созданные элементы (payload не доезжает
        до вызывающего) — это записано здесь как ИЗВЕСТНОЕ поведение, а не как
        сюрприз на следующей живой пересборке."""
        program = {"ir_version": "1.0", "ops": _wall_ops(3)}

        acceptance = PassingAcceptanceBridge(program, bulk=True)

        async def fake_exec(_llm, _bridge, code, op, _timeout_ms):
            def execute(_code, stage):
                if stage == "ground_snapshot":
                    return {"result": GROUND_SNAPSHOT}
                return {"result": {"ok": True,
                                   "w0": {"id": 1},
                                   "w1": {"error": "short curve"},   # отказал
                                   "w2": {"id": 3}}}

            return acceptance.dispatch(execute, code, op)

        with mock.patch.object(serving, "_run_declarative",
                               side_effect=fake_exec):
            result = _run(serving.handle_revit_ir_bulk(
                {"program": program}, self.llm, bridge_callback=None))
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["diagnostics"][0]["code"], "KIR-X008")
        self.assertIn("w1", result["diagnostics"][0]["detail"])


# ---------------------------------------------------------------------------
# ЧАТ — потолок 20 не поднимается НИКАКИМ входным полем
# ---------------------------------------------------------------------------


class ChatDoorStaysAtTheAuthoredBudget(_DoorHarness):

    def _over_budget(self) -> list[dict]:
        return _query_ops(compiler.MAX_OPS_PER_PROGRAM + 1)

    def test_no_input_field_can_raise_the_chat_ceiling(self) -> None:
        """Всё, чем модель могла бы попробовать «попросить bulk»."""
        ops = self._over_budget()
        attempts = [
            {"program": {"ir_version": "1.0", "ops": ops}, "bulk": True},
            {"program": {"ir_version": "1.0", "ops": ops}, "internal_bulk": True},
            {"program": {"ir_version": "1.0", "ops": ops}, "channel": "internal"},
            {"program": {"ir_version": "1.0", "ops": ops}, "mode": "rebuild"},
            {"program": {"ir_version": "1.0", "ops": ops, "bulk": True}},
            {"ir_version": "1.0", "ops": ops, "bulk": True},
            {"program": {"ir_version": "1.0", "ops": ops},
             "program_id": "a" * 64},
        ]
        for args in attempts:
            with self.subTest(args=sorted(args)):
                result = self._call(serving.handle_revit_ir, {"ops": ops},
                                    args=args)
                self.assertFalse(result["ok"], result)
                codes = {d.get("code") for d in (result.get("diagnostics") or [])}
                # Либо бюджет (KIR-L001), либо неизвестное поле конверта
                # (KIR-P003) — но НИКОГДА не «ok».
                self.assertTrue(codes & {"KIR-L001", "KIR-P003"}, result)

    def test_chat_door_signature_cannot_express_bulk(self) -> None:
        """Невозможность по ПОСТРОЕНИЮ: у чат-двери нет параметра, которым
        bulk включается. Договорённость «не передавать флаг» забывается,
        отсутствующий параметр — нет."""
        forbidden = ("bulk", "internal", "channel", "budget", "cap", "chunk")
        for name in inspect.signature(serving.handle_revit_ir).parameters:
            self.assertFalse(
                any(token in name.lower() for token in forbidden),
                f"у чат-двери появился параметр {name!r}, которым можно "
                f"попросить внутренний бюджет")

    def test_the_chat_call_site_never_names_the_internal_door(self) -> None:
        """Петля модели (kukai/llm) не должна ОБРАЩАТЬСЯ к внутренней двери."""
        offenders = []
        for path in sorted((_BACKEND / "kukai" / "llm").rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            if "handle_revit_ir_bulk" in _referenced_names(path):
                offenders.append(str(path))
        self.assertEqual(offenders, [], "чат-петля зовёт внутреннюю дверь")

    def test_internal_door_reachable_only_from_the_admin_route(self) -> None:
        """Кто вообще в дереве ОБРАЩАЕТСЯ к этой двери: она сама и админский
        маршрут. Появился кто-то ещё — это новая дверь наружу."""
        allowed = {
            _BACKEND / "kukai" / "ir" / "serving.py",
            _BACKEND / "kukai" / "api" / "admin_kir.py",
        }
        offenders = []
        for path in sorted((_BACKEND / "kukai").rglob("*.py")):
            if "__pycache__" in path.parts or "tests" in path.parts:
                continue
            if path in allowed:
                continue
            if "handle_revit_ir_bulk" in _referenced_names(path):
                offenders.append(str(path))
        self.assertEqual(offenders, [])
        # Положительный контроль: сканер ДЕЙСТВИТЕЛЬНО видит обращение. Без
        # него «никто не зовёт» проходило бы и на сломанном сканере.
        self.assertIn("handle_revit_ir_bulk",
                      _referenced_names(_BACKEND / "kukai" / "api"
                                        / "admin_kir.py"))
        # ...и НЕ считает обращением прозу, объясняющую дверь.
        self.assertNotIn("handle_revit_ir_bulk",
                         _referenced_names(_BACKEND / "kukai" / "ir"
                                           / "compiler.py"))

    def test_internal_door_still_needs_the_admin_device(self) -> None:
        """Второй рубеж: внутренняя дверь на чужом устройстве закрыта — и это
        проверяется НЕЗАВИСИМО от флага KUKAI_KIR_TOOL."""
        program = {"ir_version": "1.0", "ops": _query_ops(1)}
        with mock.patch.object(serving, "_turn_device_id",
                               return_value="deadbeef"):
            result = self._call(serving.handle_revit_ir_bulk, program)
        self.assertFalse(result["ok"], result)
        self.assertEqual(result.get("error"), "gate")

    def test_internal_door_still_obeys_the_stage2_flag(self) -> None:
        """Первый рубеж на месте: внутренняя дверь идёт тем же телом, значит
        тем же гейтом. Отдельная проверка устройства его НЕ заменяет."""
        program = {"ir_version": "1.0", "ops": _query_ops(1)}
        os.environ["KUKAI_KIR_TOOL"] = "off"
        try:
            result = self._call(serving.handle_revit_ir_bulk, program)
        finally:
            os.environ["KUKAI_KIR_TOOL"] = "stage2"
        self.assertFalse(result["ok"], result)
        self.assertEqual(result.get("error"), "gate")


# ---------------------------------------------------------------------------
# ШОВ — главное вложение: два бюджета не могут разъехаться молча
# ---------------------------------------------------------------------------


class BudgetSeamContract(_DoorHarness):

    def _door_ceiling(self, door) -> int:
        """Потолок, который дверь ПРИНИМАЕТ, замеренный поведенчески.

        Дверь называет свой бюджет сама, в типизированном отказе: константу
        здесь не читают — иначе тест сверял бы литерал с литералом."""
        result = self._call(door, {"ir_version": "1.0", "ops": _query_ops(4000)})
        diagnostic = self._budget_diagnostic(result)
        match = re.search(r"<=(\d+)", str(diagnostic.get("expected")))
        self.assertIsNotNone(match, diagnostic)
        return int(match.group(1))

    def _materializer_ceiling(self) -> int:
        """Предельный размер чанка, замеренный поведенчески: просим у
        материализатора заведомо непосильный ``chunk_target`` и смотрим, чем
        он ответил на самом деле."""
        result = leaves_to_program(_wall_leaves(1500), chunk_target=10 ** 9)
        return max(len(program["ops"]) for program in result.programs)

    def test_materializer_chunk_ceiling_equals_internal_door_ceiling(self) -> None:
        """ГЛАВНЫЙ тест шва. Валит сборку, если бюджеты развести."""
        self.assertEqual(
            self._materializer_ceiling(),
            self._door_ceiling(serving.handle_revit_ir_bulk),
            "разборщик режет чанки одного размера, а живая дверь принимает "
            "другой — ровно тот стык, который стоил 318 раундов 30.07")

    def test_both_ends_read_the_same_constant_object(self) -> None:
        """Одно место, а не два совпадающих литерала."""
        self.assertIs(materialize.MAX_BULK_OPS, compiler.MAX_BULK_OPS)

    def test_chat_ceiling_is_the_authored_budget_and_is_the_smaller_one(self) -> None:
        """Литерал здесь СТОИТ НАМЕРЕННО и обязан краснеть при каждом
        движении бюджета: сверка с самой константой прошла бы при любом её
        значении, то есть не сторожила бы ничего.

        ПОДНЯТ 20 -> 100 РЕШЕНИЕМ ВЛАДЕЛЬЦА 15.08.2026. Пин сработал ровно
        так, как задуман: правка одной константы покраснела здесь и потребовала
        назвать решение вслух, а не проехала молча. Довод ПРОТИВ подъёма (210
        из 586 живых отказов 30.07 — этот бюджет, работавший сигналом «выбрана
        не та форма») не отозван и записан в `compiler.py`; владелец принял его
        и решил иначе.

        Что осталось несущим и проверяется ниже: авторский бюджет по-прежнему
        МЕНЬШЕ внутреннего (100 < 300), то есть чат не стал внутренней дверью.
        """
        chat = self._door_ceiling(serving.handle_revit_ir)
        internal = self._door_ceiling(serving.handle_revit_ir_bulk)
        self.assertEqual(chat, compiler.MAX_OPS_PER_PROGRAM)
        self.assertEqual(chat, 100, "авторский бюджет двигать только решением")
        self.assertLess(chat, internal)

    def test_budget_refusal_names_which_budget_ran_out(self) -> None:
        """Отказ остаётся ТИПИЗИРОВАННЫМ (KIR-L001 + expected/got) и НАЗЫВАЕТ
        бюджет — иначе «слишком много опов» одинаково звучит для двух разных
        причин, и ремонт уходит не туда."""
        chat = self._budget_diagnostic(
            self._call(serving.handle_revit_ir,
                       {"ir_version": "1.0", "ops": _query_ops(4000)}))
        internal = self._budget_diagnostic(
            self._call(serving.handle_revit_ir_bulk,
                       {"ir_version": "1.0", "ops": _query_ops(4000)}))
        self.assertIn("АВТОРСКИЙ", chat["message_ru"])
        self.assertIn(compiler.BUDGET_AUTHORED, chat["message_ru"])
        self.assertIn("ВНУТРЕННИЙ", internal["message_ru"])
        self.assertIn(compiler.BUDGET_INTERNAL_BULK, internal["message_ru"])
        # Внутренний отказ объясняет, ПОЧЕМУ бюджета два (его читает оператор
        # или драйвер пересборки, а не модель).
        self.assertIn("Бюджета два", internal["message_ru"])
        self.assertNotEqual(chat["message_ru"], internal["message_ru"])
        # Число внутреннего бюджета в чат-отказ не течёт: сказанное модели
        # «300» уже стоило раунда и переписи программы (замер 27.07).
        self.assertNotIn(str(compiler.MAX_BULK_OPS), chat["message_ru"])
        self.assertIn(str(compiler.MAX_OPS_PER_PROGRAM), chat["message_ru"])
        # Имя и величина бюджета берутся ПАРОЙ из одного места: отказ не может
        # назвать один бюджет, а померить другой.
        self.assertEqual(compiler.pre_macro_budget(bulk=False),
                         (compiler.BUDGET_AUTHORED,
                          compiler.MAX_OPS_PER_PROGRAM))
        self.assertEqual(compiler.pre_macro_budget(bulk=True),
                         (compiler.BUDGET_INTERNAL_BULK,
                          compiler.MAX_BULK_OPS))

    def test_internal_door_does_not_lift_the_post_expansion_ceiling(self) -> None:
        """``MAX_VALIDATED_OPS`` — потолок ПОСЛЕ раскрытия макросов. Внутренний
        вход поднимает только предмакросный бюджет, этот — никогда."""
        self.assertEqual(compiler.MAX_VALIDATED_OPS, 320)
        blowup = {"op": "stack", "id": "sec", "levels": 3, "h_mm": 3000,
                  "name_prefix": "Этаж",
                  "floor": [{"op": "create_wall", "id": "W", "p0_mm": [0, 0],
                             "p1_mm": [6000, 0], "height_mm": 2800}]}
        program = {"ir_version": "1.0",
                   "ops": _query_ops(compiler.MAX_BULK_OPS - 1) + [blowup]}
        result = self._call(serving.handle_revit_ir_bulk, program)
        self.assertFalse(result["ok"], result)

    def test_internal_door_refuses_one_op_over_its_own_budget(self) -> None:
        program = {"ir_version": "1.0",
                   "ops": _query_ops(compiler.MAX_BULK_OPS + 1)}
        self._budget_diagnostic(self._call(serving.handle_revit_ir_bulk,
                                           program))


# ---------------------------------------------------------------------------
# АДМИНСКИЙ МАРШРУТ — единственный, кому внутренняя дверь доступна
# ---------------------------------------------------------------------------


class AdminRouteWiring(unittest.TestCase):

    def setUp(self) -> None:
        from kukai.api import admin_kir

        self.admin_kir = admin_kir
        self._rows = mock.patch.object(
            admin_kir, "_admin_ws_rows",
            return_value=[{"ws": object(), "ws_id": "ws-1",
                           "device_id": "dev", "document_name": "проект1",
                           "document_path": "", "revit_version": "2026",
                           "has_document": True, "warnings_count": 0}])
        self._rows.start()

    def tearDown(self) -> None:
        self._rows.stop()

    def _post(self, payload: dict) -> tuple[str, dict]:
        called: dict = {}

        async def chat_door(*args, **kwargs):
            called["door"] = "chat"
            return {"ok": True, "kir": True}

        async def bulk_door(*args, **kwargs):
            called["door"] = "bulk"
            return {"ok": True, "kir": True}

        with mock.patch.object(serving, "handle_revit_ir", chat_door), \
                mock.patch.object(serving, "handle_revit_ir_bulk", bulk_door):
            result = _run(self.admin_kir.run_program(payload))
        return called.get("door", ""), result

    def test_default_run_uses_the_chat_door(self) -> None:
        door, _ = self._post({"program": {"ir_version": "1.0",
                                          "ops": _query_ops(1)},
                              "doc_contains": "проект1"})
        self.assertEqual(door, "chat")

    def test_bulk_true_uses_the_internal_door(self) -> None:
        door, _ = self._post({"program": {"ir_version": "1.0",
                                          "ops": _query_ops(1)},
                              "doc_contains": "проект1", "bulk": True})
        self.assertEqual(door, "bulk")

    def test_bulk_field_is_typed(self) -> None:
        from fastapi import HTTPException

        with self.assertRaises(HTTPException):
            self._post({"program": {"ir_version": "1.0", "ops": _query_ops(1)},
                        "doc_contains": "проект1", "bulk": "да"})


class TheLiveDefectEndToEnd(unittest.TestCase):
    """ТОТ САМЫЙ ход целиком: тело запроса драйвера пересборки, реальные двери
    serving, подменён только мост. До 30.07 у /admin/kir/run был ровно один
    путь — чат-дверь, — и каждый чанк материализатора отказывал KIR-L001."""

    CHUNK = 250

    def setUp(self) -> None:
        from kukai.api import admin_kir

        self.admin_kir = admin_kir
        self._prev_flag = os.environ.get("KUKAI_KIR_TOOL")
        os.environ["KUKAI_KIR_TOOL"] = "stage2"
        self._rows = mock.patch.object(
            admin_kir, "_admin_ws_rows",
            return_value=[{"ws": object(), "ws_id": "ws-1",
                           "device_id": serving.ADMIN_DEVICE,
                           "document_name": "проект1", "document_path": "",
                           "revit_version": "2026", "has_document": True,
                           "warnings_count": 0}])
        self._rows.start()
        self._bridge = mock.patch(
            "kukai.api.bridge_protocol._bridge_callback",
            new=mock.AsyncMock(return_value={}))
        self._bridge.start()
        self._acceptance_dir = tempfile.TemporaryDirectory()
        self._prev_acceptance_dir = os.environ.get(
            "KIR_ACCEPTANCE_EVIDENCE_DIR")
        os.environ["KIR_ACCEPTANCE_EVIDENCE_DIR"] = self._acceptance_dir.name
        # ТРЕТЬЕ УСЛОВИЕ ГЕЙТА (13.08): режим КИР ставится ЯВНО.
        enter_kir_mode(self)

    def tearDown(self) -> None:
        self._bridge.stop()
        self._rows.stop()
        if self._prev_acceptance_dir is None:
            os.environ.pop("KIR_ACCEPTANCE_EVIDENCE_DIR", None)
        else:
            os.environ["KIR_ACCEPTANCE_EVIDENCE_DIR"] = (
                self._prev_acceptance_dir)
        self._acceptance_dir.cleanup()
        if self._prev_flag is None:
            os.environ.pop("KUKAI_KIR_TOOL", None)
        else:
            os.environ["KUKAI_KIR_TOOL"] = self._prev_flag

    def _run_driver_payload(self, *, bulk: bool) -> dict:
        program = {"ir_version": "1.0", "ops": _wall_ops(self.CHUNK)}
        acceptance = PassingAcceptanceBridge(program, bulk=bulk)

        async def fake_exec(_llm, _bridge, code, op, _timeout_ms):
            def execute(_code, stage):
                if stage == "ground_snapshot":
                    return {"result": GROUND_SNAPSHOT}
                payload: dict = {"ok": True}
                for index, row in enumerate(program["ops"]):
                    payload[row["id"]] = {"id": 900_000 + index}
                return {"result": payload}

            return acceptance.dispatch(execute, code, op)

        body = {"program": program, "doc_contains": "проект1",
                "timeout_ms": 200_000}
        if bulk:
            body["bulk"] = True
        with mock.patch.object(serving, "_run_declarative",
                               side_effect=fake_exec):
            return _run(self.admin_kir.run_program(body))

    def test_the_defect_without_bulk(self) -> None:
        """Симптом 30.07 дословно: чанк 250 опов отказан по бюджету 20."""
        answer = self._run_driver_payload(bulk=False)
        kir = answer["kir"]
        self.assertFalse(kir["ok"], kir)
        self.assertEqual(kir["diagnostics"][0]["code"], "KIR-L001")
        self.assertEqual(kir["diagnostics"][0]["expected"],
                         f"<={compiler.MAX_OPS_PER_PROGRAM}")

    def test_the_same_chunk_runs_with_bulk(self) -> None:
        """И то же тело с ``bulk: true`` проходит — 26 программ вместо 318."""
        answer = self._run_driver_payload(bulk=True)
        self.assertTrue(answer["bulk"])
        self.assertTrue(answer["kir"]["ok"], answer["kir"])


if __name__ == "__main__":
    unittest.main()
