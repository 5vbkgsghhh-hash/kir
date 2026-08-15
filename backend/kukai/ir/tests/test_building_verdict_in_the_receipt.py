"""В ПРОДЕ ВЕРДИКТ НЕ ВИДЕЛ ЗДАНИЯ — ТОЛЬКО ЗВЕНО.

ЧТО БЫЛО ЗАМЕРЕНО 04.08. Пачка в проде уже собиралась, и собиралась правильно:
`live/journal.py` копит программы сессии, `plan_stream._slice_for` отдаёт их
НЕ СКЛЕЕННЫМИ, `transfer.redeem()` возвращает `list[list[dict]]`, а
`chat_ws._handle_kir_transfer` гоняет её через прод-дверь по одной. Но уезжала
эта пачка ВИТРИНЕ и ИСПОЛНИТЕЛЮ — человеку и Revit'у. К СУДЬЕ она не приходила
никогда: у `design_check.check_bundle` был РОВНО ОДИН прод-вызывающий —
`course.design_check` внутри песочницы, то есть только тогда, когда модель сама
догадалась собрать пачку руками и спросить.

Следствие названо числом в `test_verdict_takes_kir_ops`: тело двухэтажного
здания БЕЗ лестницы обязано блокироваться по HAB010 — а лестницу в него класть
запрещено (KIR-L002). Значит каждое звено по отдельности непригодно ПО
ПОСТРОЕНИЮ, и единственная единица, о которой можно сказать правду, — ПАЧКА.

ВТОРАЯ ЛОВУШКА, РАДИ КОТОРОЙ ПОЛОВИНА ЭТОГО ФАЙЛА. PASS по УДОВЛЕТВОРЕНИЮ и
PASS по СНЯТИЮ читаются одинаково. Замер: одно и то же здание, отличается
ТОЛЬКО имя помещения у лестницы — «Лестничная клетка» даёт PASS, 13 правил из
20, HAB001/HAB010 ОЦЕНЕНЫ; «Кладовая» даёт PASS, 11 из 20, те же два правила
СНЯТЫ профилем и не высказывались вовсе. Обе строки при наивном чтении:
«PASS, блокирующих 0». Квитанция, которая не различает эти два случая, — это
красивое враньё, отправленное туда, где его нечем проверить.

`engine.run_checker` этой разницы не ловит и не обязан: правило, снятое
профилем, уходит `continue` ДО учёта в `mandatory_not_evaluated` (замер:
список ПУСТ в обоих случаях выше). Значит различать обязана квитанция.

Прогон: KUKAI_CHECKER_V2=1 venv/bin/python3.12 -m pytest \
        kukai/ir/tests/test_building_verdict_in_the_receipt.py -q
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("KUKAI_CHECKER_V2", "1")
os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_test_queue.jsonl"))

from kukai.ir import serving  # noqa: E402
from kukai.ir.tests.acceptance_fakes import PassingAcceptanceBridge  # noqa: E402
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT  # noqa: E402
from kukai.live import journal as J  # noqa: E402
from kukai.live import plan_stream as S  # noqa: E402
from kukai.ir.tests.gate_fixture import enter_kir_mode

BACKEND = Path(__file__).resolve().parents[3]


def _run(coro):
    return asyncio.run(coro)


# ═════════════════════════════════════════════════════════════════════════
# Материал: двухэтажное здание ТРЕМЯ программами, каждая в авторском бюджете
#
# Именно так его и обязана строить модель: 20 операций на программу, лестница
# отдельным звеном (KIR-L002), а уровень второй программы адресован ПО ИМЕНИ —
# ссылка через границу программы незаконна (KIR-V002).
# ═════════════════════════════════════════════════════════════════════════

BOX = [((0, 0), (8000, 0)), ((8000, 0), (8000, 5000)),
       ((8000, 5000), (0, 5000)), ((0, 5000), (0, 0)),
       ((4000, 0), (4000, 5000))]


def storey(tag: str, level: dict, core: str, *, first: bool) -> dict:
    ops: list[dict] = []
    if first:
        ops += [{"op": "create_level", "id": "lvl", "elev_mm": 0,
                 "name": "Этаж 1"},
                {"op": "create_level", "id": "lvl2", "elev_mm": 3000,
                 "name": "Этаж 2"}]
    for i, (p0, p1) in enumerate(BOX, start=1):
        ops.append({"op": "create_wall", "id": f"{tag}w{i}", "p0_mm": list(p0),
                    "p1_mm": list(p1), "level": level, "height_mm": 3000})
    ops.append({"op": "create_room", "id": f"{tag}r", "xy": [6000, 2500],
                "level": level, "name": "Жилая комната"})
    ops.append({"op": "create_room", "id": f"{tag}st", "xy": [2000, 2500],
                "level": level, "name": core})
    ops.append({"op": "create_door", "id": f"{tag}d", "offset_mm": 2500,
                "host": {"by": "ref", "value": f"{tag}w5"}})
    ops.append({"op": "create_window", "id": f"{tag}win", "offset_mm": 2500,
                "host": {"by": "ref", "value": f"{tag}w2"}})
    if first:
        ops.append({"op": "create_door", "id": "entrance", "offset_mm": 2000,
                    "host": {"by": "ref", "value": f"{tag}w1"}})
    return {"ir_version": "1.0", "ops": ops}


def stairs() -> dict:
    return {"ir_version": "1.0", "ops": [{
        "op": "create_stairs", "id": "s1", "width_mm": 1200,
        "p0_mm": [2000, 1000], "p1_mm": [2000, 4000],
        "base_level": {"by": "name", "value": "Этаж 1"},
        "top_level": {"by": "name", "value": "Этаж 2"}}]}


def building(core: str = "Лестничная клетка") -> list[dict]:
    return [storey("a", {"by": "ref", "value": "lvl"}, core, first=True),
            storey("b", {"by": "name", "value": "Этаж 2"}, core, first=False),
            stairs()]


class _Door(unittest.TestCase):
    """Прод-дверь целиком: гейт открыт, устройство админское, мост подменён."""

    DEVICE = None

    def setUp(self) -> None:
        self.DEVICE = serving.ADMIN_DEVICE
        self._prev_flag = os.environ.get("KUKAI_KIR_TOOL")
        os.environ["KUKAI_KIR_TOOL"] = "stage2"
        self._device = mock.patch.object(
            serving, "_turn_device_id", return_value=self.DEVICE)
        self._device.start()
        self.llm = mock.Mock()
        self.llm._revit_version = "2026"
        self._acc = tempfile.TemporaryDirectory()
        self._prev_acc = os.environ.get("KIR_ACCEPTANCE_EVIDENCE_DIR")
        os.environ["KIR_ACCEPTANCE_EVIDENCE_DIR"] = self._acc.name
        self._feed = tempfile.TemporaryDirectory()
        self._prev_feed = os.environ.get("KIR_WITNESS_PATH")
        os.environ["KIR_WITNESS_PATH"] = os.path.join(self._feed.name, "w.jsonl")
        J.reset()
        # ТРЕТЬЕ УСЛОВИЕ ГЕЙТА (13.08): режим КИР ставится ЯВНО.
        enter_kir_mode(self)

    def tearDown(self) -> None:
        self._device.stop()
        for name, prev in (("KUKAI_KIR_TOOL", self._prev_flag),
                           ("KIR_ACCEPTANCE_EVIDENCE_DIR", self._prev_acc),
                           ("KIR_WITNESS_PATH", self._prev_feed)):
            if prev is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = prev
        self._acc.cleanup()
        self._feed.cleanup()
        J.reset()

    def send(self, program: dict) -> dict:
        """Один ход через `handle_revit_ir` — тот самый прод-путь."""
        state: dict = {}

        async def fake_exec(_llm, _bridge, code, op, _timeout_ms):
            acceptance = state.get("acceptance")
            if acceptance is None:
                acceptance = state["acceptance"] = PassingAcceptanceBridge(
                    program, bulk=False)

            def execute(_code, stage):
                if stage == "ground_snapshot":
                    return {"result": GROUND_SNAPSHOT}
                payload: dict = {"ok": True}
                for index, row in enumerate(program.get("ops") or []):
                    payload[row["id"]] = {"id": 900_000 + index}
                return {"result": payload}

            return acceptance.dispatch(execute, code, op)

        async def go():
            with mock.patch.object(serving, "_run_declarative",
                                   side_effect=fake_exec):
                return await serving.handle_revit_ir(
                    {"program": program}, self.llm, bridge_callback=None)

        return _run(go())

    def build(self, core: str = "Лестничная клетка") -> dict:
        """Три хода. Возвращает квитанцию ПОСЛЕДНЕГО — там всё здание."""
        last: dict = {}
        for program in building(core):
            last = self.send(program)
        return last


# ═════════════════════════════════════════════════════════════════════════
# 1. ПАЧКА ДОХОДИТ ДО СУДЬИ
# ═════════════════════════════════════════════════════════════════════════

class ThePackReachesTheJudge(_Door):

    def test_the_receipt_carries_a_verdict_about_the_whole_building(self) -> None:
        """ГЛАВНОЕ УТВЕРЖДЕНИЕ. Три программы, три хода — и в квитанции третьего
        стоит вердикт о ЗДАНИИ, а не о звене."""
        receipt = self.build()
        block = receipt.get("building")
        self.assertIsNotNone(block, sorted(receipt))
        self.assertEqual(block["programs"], 3, block)
        self.assertEqual(block["verdict"], "pass", block)
        self.assertEqual(block["blocking"], [], block)

    def test_the_pack_verdict_is_not_the_verdict_of_its_last_link(self) -> None:
        """ЧИСЛОМ: то же здание, судимое ЗВЕНОМ, непригодно.

        Лестничная программа сама по себе — один оп без единого помещения:
        HAB000. Тело без лестницы — HAB010. Пригодным здание становится РОВНО
        как пачка, и это единственная причина, ради которой пачка едет судье.
        """
        from kukai.ir import design_check as dc

        alone = dc.check_ops(stairs(), building_id="звено")
        self.assertIn("HAB000", [v.rule_id for v in alone.report.blocking])
        body = dc.check_bundle(building()[:2], building_id="тело")
        self.assertIn("HAB010", [v.rule_id for v in body.report.blocking])
        # А пачка целиком — пригодна.
        self.assertEqual(self.build()["building"]["verdict"], "pass")

    def test_the_block_names_the_pack_it_judged(self) -> None:
        """Вердикт без знаменателя — утверждение ни о чём: сколько программ и
        операций съедено, и сколько журнал ВЫТЕСНИЛ, обязано ехать рядом."""
        block = self.build()["building"]
        self.assertEqual(block["ops"],
                         sum(len(p["ops"]) for p in building()), block)
        self.assertEqual(block["programs_evicted"], 0, block)
        self.assertIn("3 программ", block["message_ru"])

    def test_a_read_only_turn_does_not_grow_the_building(self) -> None:
        """Запрос зданию не принадлежит (замер 29.07: 176 чтений на 5 записей).
        Ход, ничего не добавивший в журнал, не имеет права печатать вердикт —
        иначе один и тот же вердикт повторялся бы, пока идёт чтение."""
        self.build()
        receipt = self.send({"ir_version": "1.0", "ops": [
            {"op": "query_count", "id": "q", "kind": "wall"}]})
        self.assertIsNone(receipt.get("building"), receipt.get("building"))

    def test_only_the_chat_door_stamps_the_verdict(self) -> None:
        """АДМИНСКАЯ ДВЕРЬ МОЛЧИТ, И ЭТО РЕШЕНИЕ, А НЕ ЗАБЫВЧИВОСТЬ.

        `handle_revit_ir_bulk` — путь пересборки разбора: замер 30.07 по
        Snowdon Towers — 6 335 опов, 26 программ чанками по 250. Автор там
        материализатор, а не модель, читателя у квитанции нет вовсе, и вердикт
        о всё растущей пачке стоил бы времени на каждом чанке. Структурно, а не
        на глаз: отметка снимается ровно в одной функции.
        """
        import ast
        import inspect

        source = inspect.getsource(serving)
        tree = ast.parse(source)
        stampers = {node.name for node in ast.walk(tree)
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    for inner in ast.walk(node)
                    if isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Name)
                    and inner.func.id == "_stamp_building_verdict"}
        self.assertEqual(stampers, {"handle_revit_ir"}, stampers)

    def test_the_judge_has_a_live_caller_outside_the_sandbox(self) -> None:
        """ДОСТИЖИМОСТЬ МЕРЯЕТСЯ ПРИБОРОМ, А НЕ GREP'ОМ. До 04.08 у
        `check_bundle` был ровно один прод-вызывающий — `kukai.ir.course`,
        то есть песочница: пачка доходила до судьи только тогда, когда модель
        собрала её руками и спросила сама."""
        sys.path.insert(0, str(BACKEND / "tests"))
        try:
            import capability_graph  # noqa: WPS433
            graph = capability_graph.Graph(BACKEND)
        finally:
            if sys.path and sys.path[0] == str(BACKEND / "tests"):
                sys.path.pop(0)
        live = graph.live()
        callers = {name for name
                   in graph.callers_of("check_bundle", "kukai.ir.design_check")
                   if not name.startswith("kukai.ir.tests")}
        self.assertIn("kukai.ir.course", callers, callers)
        outside = callers - {"kukai.ir.course"}
        self.assertTrue(outside, "у судьи по-прежнему только дверь песочницы")
        self.assertTrue([c for c in outside if c in live],
                        f"вызывающий есть, но он не достижим из прода: {outside}")


# ═════════════════════════════════════════════════════════════════════════
# 2. PASS ПО УДОВЛЕТВОРЕНИЮ ≠ PASS ПО СНЯТИЮ
# ═════════════════════════════════════════════════════════════════════════

class TwoKindsOfPass(_Door):

    def test_the_two_passes_differ_by_a_number_the_model_can_read(self) -> None:
        """Одно здание, разница ТОЛЬКО в имени помещения у лестницы.

        Замер: «Лестничная клетка» -> 13 правил из 20; «Кладовая» -> 11 из 20,
        и разница ровно HAB001 (второй выход) + HAB010 (связь этажей). Обе —
        PASS с нулём блокирующих.
        """
        named = self.build("Лестничная клетка")["building"]
        J.reset()
        waived = self.build("Кладовая")["building"]

        self.assertEqual((named["verdict"], waived["verdict"]), ("pass", "pass"))
        self.assertEqual((named["blocking"], waived["blocking"]), ([], []))
        # …и всё же это РАЗНЫЕ утверждения, названные числом:
        self.assertEqual(named["rules_evaluated"], 13, named)
        self.assertEqual(waived["rules_evaluated"], 11, waived)
        self.assertEqual(named["rules_total"], waived["rules_total"], 20)
        gap = set(waived["rules_suspended"]) - set(named["rules_suspended"])
        self.assertEqual(gap, {"HAB001", "HAB010"}, gap)

    def test_the_waived_pass_says_suspended_and_gives_the_reason(self) -> None:
        """Число мало: модель читает текст. Снятое правило обязано быть названо
        СНЯТЫМ (не «пройденным») и обязано принести ПРИЧИНУ снятия — ту самую,
        которую полный вердикт печатает, а краткий отсылает «см. полный»."""
        waived = self.build("Кладовая")["building"]
        text = waived["message_ru"]
        self.assertIn("СНЯТО", text, text)
        self.assertIn("ЭТИМ ЗДАНИЕМ HAB001/HAB010", text, text)
        # Причина, а не отсылка к причине: она и есть починка следующего хода.
        self.assertIn("ЛЕСТНИЦА", text.upper(), text)

    def test_the_always_on_waivers_do_not_cost_the_channel_every_turn(self) -> None:
        """Снятия САМОЙ СТАДИИ стоят при любом здании и не меняются никогда.
        Их причины — ~1100 символов, и печатать их каждый пишущий ход значит
        платить контекстом за новость, которой нет. Названы поимённо, но без
        своих причин; развод СТРУКТУРНЫЙ — вычитанием `DESIGN_STAGE.suspended`,
        а не угадыванием по тексту."""
        from kukai.ir.design_check import DESIGN_STAGE

        text = self.build("Кладовая")["building"]["message_ru"]
        self.assertIn("СТАДИЕЙ (стоят при любом замысле", text)
        for rule_id in sorted(DESIGN_STAGE.suspended):
            self.assertIn(rule_id, text)
        # Длинная причина оракула квартиры в канал НЕ едет.
        self.assertNotIn("precision mop/core", text, text)
        self.assertLess(len(text), 2_000, len(text))

    def test_the_satisfied_pass_does_not_carry_the_waiver(self) -> None:
        """Обратная сторона: предупреждение, которое стоит ВСЕГДА, — это шум,
        и модель перестанет его читать через два хода."""
        named = self.build("Лестничная клетка")["building"]
        text = named["message_ru"]
        self.assertNotIn("HAB010", text, text)
        self.assertNotIn("HAB001", text, text)

    def test_the_headline_never_reads_stronger_than_the_coverage(self) -> None:
        """ЗАКОН ЗАГОЛОВКА (`verdict_headline_text`) обязан действовать и здесь:
        PASS при неполном покрытии не имеет права печататься словом ПРИГОДЕН и
        точкой. Заголовок — единственная строка, которую читают всегда."""
        for core, evaluated in (("Лестничная клетка", 13), ("Кладовая", 11)):
            J.reset()
            text = self.build(core)["building"]["message_ru"]
            head = text.splitlines()[0] + " " + text.splitlines()[1]
            self.assertIn(f"{evaluated} ПРАВИЛАМ ИЗ 20", text, head)


# ═════════════════════════════════════════════════════════════════════════
# 3. МОДЕЛЬ ЗНАЕТ, ЧТО СТРОИТ ЗДАНИЕ ПО ЧАСТЯМ
# ═════════════════════════════════════════════════════════════════════════

class TheModelIsTold(unittest.TestCase):

    def test_the_tool_description_says_the_programs_accumulate(self) -> None:
        """Вторая половина той же дыры: канал построен, а модели о нём не
        сказано. В замере 03-04.08 модель освоила пачку РОВНО потому, что стенд
        ей о ней сказал; в проде такой строки не было.

        ПРОВЕРЯЕТСЯ ОДНА ЛОВУШКА ЦЕЛИКОМ, А НЕ СЛОВА ПО ВСЕМУ ТЕКСТУ. Первая
        редакция этого теста искала «накапливаются» и «квитанции» в описании
        ЦЕЛИКОМ — и осталась зелёной под мутацией, снявшей половину фразы:
        слово «квитанции» стоит в описании `program_py` и без неё. Утверждение
        здесь СОСТАВНОЕ («копятся» И «вердикт о пачке приезжает сам» И «вот имя
        блока»), значит и мерить его надо в одном абзаце.
        """
        from kukai.ir.tool_doc import NOTES, build_tool_description

        notes = [n for n in NOTES if "НАКАПЛИВАЮТСЯ" in n]
        self.assertEqual(len(notes), 1, "факт накопления назван 0 или 2 раза")
        note = notes[0]
        for needle in ("КВИТАНЦИИ", "ПАЧКЕ", "`building`", "design_check(["):
            self.assertIn(needle, note, note)
        self.assertIn(note, build_tool_description())

    def test_the_pointer_and_the_receipt_speak_of_the_same_unit(self) -> None:
        """Указатель обещает `design_check([...])` для пачки — и квитанция
        обязана судить ТУ ЖЕ единицу, иначе модель учится на двух разных
        зданиях сразу."""
        from kukai.ir.tool_doc import build_tool_description

        text = build_tool_description()
        self.assertIn("design_check([", text)
        self.assertIn("ПАЧКА", text.upper())
