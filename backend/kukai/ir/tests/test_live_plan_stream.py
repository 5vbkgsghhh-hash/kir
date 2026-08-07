"""ВОРОТА ЖИВОГО ПЛАНА — РАЗРУШИТЕЛЬНЫЕ, а не подтверждающие.

Главное доказательство этой волны не «кадр нарисовался», а «рисовальщик сломан
посреди прогона, и стройка этого НЕ ЗАМЕТИЛА». Поэтому здесь почти нет тестов,
которые что-то включают: почти каждый что-то ЛОМАЕТ и предъявляет числом, что
журнал программ остался полным, а вызывающий не задержан и не получил
исключения.

Разделы:
  §1 односторонность — обходом импортов (`ast`), а не чтением глазами;
  §2 единственность крана — обходом вызовов по всему дереву;
  §3 разрушительные сценарии (пять штук);
  §4 ограниченность и длинный прогон;
  §5 честность источника.
"""
from __future__ import annotations

import ast
import asyncio
import gc
import os
import sys
import tempfile
import time
import tracemalloc
import unittest
from pathlib import Path

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_test_queue.jsonl"))

from kukai.live import journal as J          # noqa: E402
from kukai.live import plan_stream as S      # noqa: E402

BACKEND = Path(__file__).resolve().parents[3]

#: Модули, принимающие решения о компиляции и записи. Ребра ОТСЮДА в них быть
#: не должно ни одного — ни прямого, ни через цепочку.
COMPILER_DECIDERS = frozenset({
    "kukai.ir.compiler", "kukai.ir.ground", "kukai.ir.authoring",
    "kukai.ir.midend", "kukai.ir.emit_model", "kukai.ir.serving",
    "kukai.ir.sandbox", "kukai.ir.dsl", "kukai.ir.macros",
    "kukai.ir.authoring_validation", "kukai.ir.schema_gen",
    "kukai.ir.acceptance", "kukai.ir.acceptance_journal",
    "kukai.ir.gate_runner", "kukai.ir.witness_feed",
})

STREAM_MODULES = ("kukai.live", "kukai.live.journal", "kukai.live.plan_stream")


def _graph():
    sys.path.insert(0, str(BACKEND / "tests"))
    try:
        import capability_graph  # noqa: WPS433
        return capability_graph.Graph(BACKEND)
    finally:
        if sys.path and sys.path[0] == str(BACKEND / "tests"):
            sys.path.pop(0)


def _reach(graph, seeds, *, through_packages: bool) -> set[str]:
    """Обход импортов. `through_packages=False` выбрасывает рёбра в `__init__`
    пакетов — то есть отделяет «рисовальщик ЗОВЁТ компилятор» от «рисовальщик
    ЛЕЖИТ в пакете, чей `__init__` зовёт компилятор»."""
    seen: set[str] = set()
    stack = [s for s in seeds if s in graph.modules]
    while stack:
        name = stack.pop()
        if name in seen:
            continue
        seen.add(name)
        mod = graph.modules.get(name)
        if mod is None:
            continue
        for edge in (mod.imports | mod.dynamic_imports):
            target = graph.modules.get(edge)
            if target is None:
                continue
            if not through_packages and target.path.name == "__init__.py":
                continue
            if edge not in seen:
                stack.append(edge)
    return seen


def _program(*ops, level_id="LV", level_name="Этаж 1", elev=0.0):
    return {"ir_version": "1.0", "intent": "поток",
            "ops": [{"op": "create_level", "id": level_id, "elev_mm": elev,
                     "name": level_name}, *ops]}


def _walls(n, *, level_id="LV", y=0.0, x0=0.0, tag=""):
    return [{"op": "create_wall", "id": f"W{tag}{i}",
             "p0_mm": [x0 + i * 4000.0, y], "p1_mm": [x0 + i * 4000.0, y + 6000.0],
             "level": {"by": "ref", "value": level_id}} for i in range(n)]


class _Loop(unittest.TestCase):
    """База: свой цикл событий, чистый поток, подключённая панель."""

    def setUp(self):
        S.reset()
        self.sent: list[dict] = []
        self.send_failures = 0

        async def transport(device_id, payload):
            self.sent.append(payload)

        self.transport = transport

    def tearDown(self):
        S.reset()

    def run_async(self, coro):
        return asyncio.run(coro)

    async def _wired(self, device="dev"):
        S.bind_transport(self.transport)
        S.attach(device)


# ─────────────────────────────────────────────────────────────────────────────
# §1. ОДНОСТОРОННОСТЬ
# ─────────────────────────────────────────────────────────────────────────────

class OneWayTests(unittest.TestCase):

    def test_no_reverse_edge_into_compiler(self):
        """Из рисовальщика в компилятор пути НЕТ — доказано обходом `ast`.

        Обход идёт по тем же рёбрам, что `capability_graph`: `import`,
        `from … import`, относительные, ЛЕНИВЫЕ внутри функций, динамические.
        Пакетные `__init__` выброшены осознанно и это НАЗВАНО: `preview.py`
        лежит внутри `kukai/ir/`, поэтому его импорт исполняет
        `kukai/ir/__init__.py`, а тот импортирует компилятор. Это факт
        РАСПОЛОЖЕНИЯ preview.py, а не ребро, объявленное рисовальщиком —
        см. `test_the_only_package_edge_is_named` ниже, где этот остаток
        предъявлен, а не спрятан.
        """
        graph = _graph()
        reachable = _reach(graph, STREAM_MODULES, through_packages=False)
        leaked = sorted(reachable & COMPILER_DECIDERS)
        self.assertEqual(leaked, [], f"обратное ребро в компилятор: {leaked}")

    def test_the_only_package_edge_is_named(self):
        """Остаток предъявлен: единственный путь — исполнение `kukai/ir/__init__`.

        Тест держит его РОВНО ОДНИМ. Появится второй способ дотянуться до
        компилятора — тест покраснеет, и это ровно то, ради чего он написан.
        """
        graph = _graph()
        stream = set(STREAM_MODULES)
        into_ir = set()
        for name in stream:
            mod = graph.modules[name]
            into_ir |= {e for e in mod.imports if e.startswith("kukai.ir")}
        # Живые рёбра отсюда в компиляторный пакет: сам пакет (он же и есть
        # остаток) и ровно один модуль — рисовальщик.
        self.assertEqual(into_ir, {"kukai.ir", "kukai.ir.preview"}, into_ir)

    def test_preview_declares_no_edge_into_the_compiler(self):
        """`preview.py` — лист: на уровне модуля из `kukai.ir` не тянет ничего."""
        graph = _graph()
        mod = graph.modules["kukai.ir.preview"]
        self.assertEqual(mod.imports & COMPILER_DECIDERS, set())

    def test_journal_is_pure(self):
        """Журнал не знает ни компилятора, ни веба, ни рисовальщика."""
        graph = _graph()
        mod = graph.modules["kukai.live.journal"]
        foreign = {e for e in mod.imports
                   if e.startswith(("kukai.ir", "kukai.api", "kukai.llm"))}
        self.assertEqual(foreign, set(), foreign)

    def test_stream_never_imports_the_web_layer(self):
        """Канал ВНОСЯТ (`bind_transport`), а не импортируют: иначе `kukai.live`
        потащил бы FastAPI в каждый офлайн-прогон."""
        graph = _graph()
        mod = graph.modules["kukai.live.plan_stream"]
        self.assertEqual({e for e in mod.imports if e.startswith("kukai.api")},
                         set())


# ─────────────────────────────────────────────────────────────────────────────
# §2. ЕДИНСТВЕННОСТЬ КРАНА
# ─────────────────────────────────────────────────────────────────────────────

class SingleCraneTests(unittest.TestCase):

    def _publish_sites(self):
        sites = []
        for path in (BACKEND / "kukai").rglob("*.py"):
            if "tests" in path.parts or path.name.startswith("test_"):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            except (SyntaxError, ValueError):
                continue
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "publish"
                        and isinstance(node.func.value, ast.Name)
                        and "plan_stream" in node.func.value.id):
                    sites.append((str(path.relative_to(BACKEND)), node.lineno))
        return sites

    def test_single_publish_call_site(self):
        """Один кран, и это МАШИННОЕ утверждение.

        Точек входа в авторскую программу четыре — чат `handle_revit_ir`,
        админская `handle_revit_ir_bulk`, скриптовая `program_py` и пересборка.
        Четыре крана разъехались бы за месяц: политику пересборки три
        вызывающих независимо забыли 21.07, и ровно поэтому она стала одной
        функцией. Здесь то же правило, проверяемое обходом, а не памятью.
        """
        sites = self._publish_sites()
        self.assertEqual(len(sites), 1, f"кранов больше одного: {sites}")
        self.assertEqual(sites[0][0], "kukai/ir/serving.py", sites)

    def test_all_doors_funnel_through_the_injection_point(self):
        """Обе живые двери сходятся в тело, где стоит врезка."""
        source = (BACKEND / "kukai/ir/serving.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        callers = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for inner in ast.walk(node):
                    if (isinstance(inner, ast.Call)
                            and isinstance(inner.func, ast.Name)
                            and inner.func.id == "_handle_revit_ir_inner"):
                        callers.add(node.name)
        self.assertEqual(callers, {"handle_revit_ir", "handle_revit_ir_bulk"})

    def test_injection_is_write_only(self):
        """Врезка спрашивает семью программы у мидэнда, а не у себя.

        Журнал — исходный код ЗДАНИЯ. Ход 29.07 сделал 176 чтений на 5
        записей; попади запросы в журнал, история здания стала бы шумом.
        Классификатор при этом ОДИН — `_program_writes`, тот же, которым
        пользуется остальной путь.
        """
        source = (BACKEND / "kukai/ir/serving.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        guarded = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            calls = {inner.func.attr for inner in ast.walk(node)
                     if isinstance(inner, ast.Call)
                     and isinstance(inner.func, ast.Attribute)}
            names = {inner.func.id for inner in ast.walk(node.test)
                     if isinstance(inner, ast.Call)
                     and isinstance(inner.func, ast.Name)}
            if "publish" in calls and "_program_writes" in names:
                guarded = True
        self.assertTrue(guarded, "врезка не отфильтрована по семье программы")

    def test_injection_is_wrapped(self):
        """Врезка стоит ВНУТРИ `try/except Exception`. Структурно, а не на глаз:
        забыть применить правило нельзя, забыть строчку — можно."""
        source = (BACKEND / "kukai/ir/serving.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        wrapped = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            has_call = any(
                isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Attribute)
                and inner.func.attr == "publish"
                for inner in ast.walk(node)
            )
            if not has_call:
                continue
            for handler in node.handlers:
                if (handler.type is None
                        or (isinstance(handler.type, ast.Name)
                            and handler.type.id == "Exception")):
                    wrapped = True
        self.assertTrue(wrapped, "врезка не обёрнута в except Exception")

    def test_publish_has_no_await(self):
        """КРАН БЕЗ ОЖИДАНИЯ — по построению, а не по намерению.

        В теле `publish` нет ни одной точки ожидания, поэтому вызывающий не
        может быть задержан рисованием даже теоретически. Это утверждение о
        ФОРМЕ функции, и оно проверяется формой.
        """
        source = (BACKEND / "kukai/live/plan_stream.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        found = [n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name == "publish"]
        self.assertEqual(len(found), 1)
        self.assertFalse(
            any(isinstance(inner, (ast.Await, ast.AsyncFor, ast.AsyncWith))
                for inner in ast.walk(found[0])))


# ─────────────────────────────────────────────────────────────────────────────
# §3. РАЗРУШИТЕЛЬНЫЕ СЦЕНАРИИ
# ─────────────────────────────────────────────────────────────────────────────

class DestructiveTests(_Loop):
    """«Что сломал → что случилось со стройкой». В каждом случае — ЧИСЛОМ."""

    PROGRAMS = 40

    async def _build_run(self, *, device="dev", bridge_s=0.001):
        """Прогон, изображающий стройку: публикация + ожидание «моста».

        Возвращает (сколько программ отправлено, сколько секунд занял прогон).
        """
        started = time.perf_counter()
        for i in range(self.PROGRAMS):
            S.publish(device_id=device, doc_key="doc",
                      program=_program(*_walls(3, tag=f"{i}_", y=i * 500.0)),
                      source="chat")
            await asyncio.sleep(bridge_s)   # «мост исполняет программу»
        return self.PROGRAMS, time.perf_counter() - started

    def _journal_is_intact(self, expected):
        entry = J.get(("dev", "doc"))
        self.assertIsNotNone(entry, "журнал пуст — программы потеряны")
        self.assertEqual(len(entry.records) + entry.programs_evicted, expected)
        return entry

    # -- 1. исключение внутри рисовальщика --------------------------------
    def test_exploding_drawer_does_not_reach_the_build(self):
        async def scenario():
            await self._wired()
            S._render_frame = _boom          # рисовальщик сломан НАСМЕРТЬ
            sent, elapsed = await self._build_run()
            await S.drain(5.0)
            return sent, elapsed

        original = S._render_frame
        try:
            sent, elapsed = self.run_async(scenario())
        finally:
            S._render_frame = original
        entry = self._journal_is_intact(sent)
        st = S.stats()
        self.assertEqual(st["journaled"], sent, "программа потеряна")
        self.assertGreater(st["render_errors"], 0, "поломка не предъявлена числом")
        self.assertEqual(st["frames_sent"], 0)
        self.assertEqual(self.sent, [])
        # Стройка не заметила: журнал полон, ни одного исключения наружу.
        self.assertEqual(entry.ops_held, sum(r.op_count for r in entry.records))

    # -- 2. медленный рисовальщик (кадры отстают) --------------------------
    def test_slow_drawer_does_not_delay_the_build(self):
        slow = 0.05   # 50 мс на кадр против ~1 мс шага стройки

        def crawl(ops, label):
            time.sleep(slow)
            return {"level": label, "assertion": "self_reported", "svg": "",
                    "census": {}, "meta": {}, "source": "program",
                    "assertion_ru": "ЗАЯВЛЕНО", "content_digest": ""}

        async def scenario():
            await self._wired()
            S._render_frame = crawl
            return await self._build_run()

        original = S._render_frame
        try:
            sent, elapsed = self.run_async(scenario())
        finally:
            S._render_frame = original
        self._journal_is_intact(sent)
        # Стройка сделала 40 шагов по 1 мс. Даже если бы рисовальщик успел
        # нарисовать всё, это 40 × 50 мс = 2 с; прогон обязан уложиться сильно
        # раньше, потому что кадры схлопываются, а не ждут очереди.
        self.assertLess(elapsed, 1.0, f"стройку задержали: {elapsed:.3f} с")
        self.assertEqual(S.stats()["journaled"], sent)

    # -- 3. переполнение очереди -------------------------------------------
    def test_queue_overflow_drops_frames_never_programs(self):
        def crawl(ops, label):
            time.sleep(0.02)
            return {"level": label, "assertion": "self_reported", "svg": "",
                    "census": {}, "meta": {}, "source": "program",
                    "assertion_ru": "ЗАЯВЛЕНО", "content_digest": ""}

        async def scenario():
            await self._wired()
            S._render_frame = crawl
            # Публикуем ЗАЛПОМ, без единой уступки циклу: работник не успеет
            # разгрести, очередь обязана упереться в потолок.
            for i in range(400):
                S.publish(device_id="dev", doc_key="doc",
                          program=_program(*_walls(2, tag=f"{i}_")),
                          source="chat")
            await S.drain(10.0)
            return 400

        original = S._render_frame
        os.environ["KUKAI_KIR_LIVE_PLAN_QUEUE"] = "4"
        try:
            sent = self.run_async(scenario())
        finally:
            S._render_frame = original
            os.environ.pop("KUKAI_KIR_LIVE_PLAN_QUEUE", None)
        st = S.stats()
        self.assertGreater(st["dropped_frames"], 0, "потолок очереди не сработал")
        self.assertLessEqual(st["queue_depth"], 4)
        self.assertEqual(st["journaled"], sent, "выброшен кадр — потеряна программа")
        entry = self._journal_is_intact(sent)
        # И главное: выброшенный будильник не оставил журнал непрочитанным.
        self.assertEqual(entry.indexed_upto, entry.next_seq,
                         "работник не догнал журнал по курсору")

    # -- 4. отвалившийся сокет панели ---------------------------------------
    def test_dead_socket_does_not_stop_the_build(self):
        async def dead(device_id, payload):
            raise ConnectionResetError("панель отвалилась")

        async def scenario():
            S.bind_transport(dead)
            S.attach("dev")
            sent, _ = await self._build_run()
            await S.drain(5.0)
            return sent

        sent = self.run_async(scenario())
        self._journal_is_intact(sent)
        st = S.stats()
        self.assertGreater(st["send_errors"], 0)
        self.assertEqual(st["frames_sent"], 0)
        self.assertEqual(st["journaled"], sent)
        # Работник жив: он рисовал, несмотря на мёртвый сокет.
        self.assertGreater(st["renders"], 0)

    def test_hanging_socket_does_not_stop_the_build(self):
        """Сокет не отвалился, а ЗАВИС — худший случай, чем разрыв."""
        async def hang(device_id, payload):
            await asyncio.sleep(30)

        async def scenario():
            S.bind_transport(hang)
            S.attach("dev")
            sent, elapsed = await self._build_run()
            return sent, elapsed

        os.environ["KUKAI_KIR_LIVE_PLAN_SEND_MS"] = "100"
        try:
            sent, elapsed = self.run_async(scenario())
        finally:
            os.environ.pop("KUKAI_KIR_LIVE_PLAN_SEND_MS", None)
        self._journal_is_intact(sent)
        self.assertLess(elapsed, 1.0, f"зависший сокет задержал стройку: {elapsed:.3f}")

    # -- 5. панели нет вовсе -------------------------------------------------
    def test_no_panel_means_no_drawing_at_all(self):
        async def scenario():
            S.bind_transport(self.transport)     # канал есть, панели нет
            sent, _ = await self._build_run()
            await S.drain(2.0)
            return sent

        sent = self.run_async(scenario())
        self._journal_is_intact(sent)
        st = S.stats()
        self.assertEqual(st["renders"], 0, "рисовали без панели")
        self.assertEqual(st["queued"], 0, "будили работника без панели")
        self.assertEqual(st["skipped_no_panel"], sent)
        self.assertEqual(st["journaled"], sent, "журнал обязан жить без панели")

    def test_transport_never_bound(self):
        """Веб-слой не позвал `bind_transport` — поток молчит, стройка идёт."""
        async def scenario():
            S.attach("dev")          # панель «есть», канала нет
            sent, _ = await self._build_run()
            await S.drain(5.0)
            return sent

        sent = self.run_async(scenario())
        self._journal_is_intact(sent)
        self.assertEqual(S.stats()["frames_sent"], 0)

    # -- 6. кран не бросает НИКОГДА -----------------------------------------
    def test_publish_never_raises(self):
        """Даже когда сломан сам журнал — то есть та часть, которая первична."""
        original = J.append

        def poisoned(*a, **k):
            raise MemoryError("журнал отравлен")

        J.append = poisoned
        try:
            S.publish(device_id="dev", doc_key="doc", program=_program(*_walls(2)))
        finally:
            J.append = original
        # Никакого исключения. Это и есть весь тест.

    def test_publish_outside_an_event_loop(self):
        """Скриптовый прогон без цикла: журнал пишется, работник не поднимается."""
        S.bind_transport(self.transport)
        S.attach("dev")
        S.publish(device_id="dev", doc_key="doc", program=_program(*_walls(2)))
        self.assertEqual(S.stats()["journaled"], 1)
        self.assertEqual(S.stats()["queue_depth"], 0)

    def test_disabled_flag_costs_nothing(self):
        os.environ["KUKAI_KIR_LIVE_PLAN"] = "0"
        try:
            S.publish(device_id="dev", doc_key="doc", program=_program(*_walls(2)))
        finally:
            os.environ.pop("KUKAI_KIR_LIVE_PLAN", None)
        self.assertEqual(S.stats()["journaled"], 0)
        self.assertEqual(J.stats()["programs"], 0)


def _boom(ops, label):
    raise RuntimeError("рисовальщик сломан")


# ─────────────────────────────────────────────────────────────────────────────
# §4. ОГРАНИЧЕННОСТЬ И ДЛИННЫЙ ПРОГОН
# ─────────────────────────────────────────────────────────────────────────────

class BoundednessTests(_Loop):

    def test_journal_is_capped_and_names_what_it_dropped(self):
        os.environ["KUKAI_KIR_JOURNAL_PROGRAMS"] = "16"
        try:
            for i in range(60):
                S.publish(device_id="dev", doc_key="doc",
                          program=_program(*_walls(2, tag=f"{i}_")))
            entry = J.get(("dev", "doc"))
            self.assertLessEqual(len(entry.records), 16)
            self.assertEqual(entry.programs_evicted, 60 - len(entry.records))
            # Вытесненное НАЗВАНО и едет на лист, а не забыто молча.
            self.assertGreater(entry.summary()["programs_evicted"], 0)
        finally:
            os.environ.pop("KUKAI_KIR_JOURNAL_PROGRAMS", None)

    def test_sessions_are_capped(self):
        os.environ["KUKAI_KIR_JOURNAL_SESSIONS"] = "3"
        try:
            for i in range(12):
                S.publish(device_id=f"dev{i}", doc_key="doc",
                          program=_program(*_walls(2)))
            self.assertLessEqual(J.stats()["sessions"], 3)
        finally:
            os.environ.pop("KUKAI_KIR_JOURNAL_SESSIONS", None)

    def test_only_the_changed_level_is_redrawn(self):
        """Рисуется уровень, КОТОРЫЙ ИЗМЕНИЛСЯ, а не всё здание.

        Иначе союз всех программ сессии даёт квадратичную работу (замер K2:
        9.3 с на три этажа).
        """
        drawn: list[str] = []
        original = S._render_frame

        def spy(ops, label):
            drawn.append(label)
            return original(ops, label)

        async def scenario():
            await self._wired()
            S._render_frame = spy
            for level in ("A", "B", "C"):
                S.publish(device_id="dev", doc_key="doc",
                          program=_program(*_walls(3, level_id=level),
                                           level_id=level, level_name=f"Этаж {level}"))
                await S.drain(5.0)
            # Ещё одна программа ТОЛЬКО по этажу B.
            drawn.clear()
            S.publish(device_id="dev", doc_key="doc",
                      program=_program(*_walls(2, level_id="B", tag="x", y=9000.0),
                                       level_id="B", level_name="Этаж B"))
            await S.drain(5.0)

        try:
            self.run_async(scenario())
        finally:
            S._render_frame = original
        self.assertEqual(set(drawn), {"Этаж B"},
                         f"перерисовали лишние этажи: {drawn}")

    def test_levels_per_frame_is_capped(self):
        os.environ["KUKAI_KIR_LIVE_PLAN_LEVELS"] = "2"
        drawn: list[str] = []
        original = S._render_frame

        def spy(ops, label):
            drawn.append(label)
            return {"level": label, "assertion": "self_reported", "svg": "",
                    "census": {}, "meta": {}, "source": "program",
                    "assertion_ru": "ЗАЯВЛЕНО", "content_digest": ""}

        async def scenario():
            await self._wired()
            S._render_frame = spy
            ops = []
            for level in ("A", "B", "C", "D", "E"):
                ops.append({"op": "create_level", "id": level, "elev_mm": 0,
                            "name": f"Этаж {level}"})
                ops.extend(_walls(2, level_id=level, tag=level))
            S.publish(device_id="dev", doc_key="doc", program={"ops": ops})
            await S.drain(5.0)

        try:
            self.run_async(scenario())
        finally:
            S._render_frame = original
            os.environ.pop("KUKAI_KIR_LIVE_PLAN_LEVELS", None)
        self.assertLessEqual(len(drawn), 2, drawn)
        self.assertTrue(self.sent)
        self.assertGreater(self.sent[-1]["levels_not_drawn"], 0,
                           "необрисованные этажи не названы")

    def test_long_run_memory_and_time(self):
        """ДЛИННЫЙ ПРОГОН: сотни программ, память и время — числом.

        Печатает замер, чтобы он попал в отчёт волны, а не в утверждение.
        """
        programs = 400
        walls_each = 6

        async def scenario():
            await self._wired()
            t0 = time.perf_counter()
            for i in range(programs):
                S.publish(
                    device_id="dev", doc_key="doc",
                    program=_program(*_walls(walls_each, tag=f"{i}_",
                                             y=(i % 20) * 800.0)),
                    source="chat")
                if i % 25 == 0:
                    await asyncio.sleep(0)
            publish_s = time.perf_counter() - t0
            await S.drain(120.0)
            return publish_s, time.perf_counter() - t0

        gc.collect()
        tracemalloc.start()
        base = tracemalloc.get_traced_memory()[0]
        publish_s, total_s = self.run_async(scenario())
        peak_kb = (tracemalloc.get_traced_memory()[1] - base) / 1024.0
        tracemalloc.stop()

        entry = J.get(("dev", "doc"))
        st = S.stats()
        # Отдельно — ЧИСТАЯ стоимость кадра, без гонки за GIL со стройкой.
        # Разница между ней и средним временем кадра и есть цена соседства.
        slice_ops, _dropped, _pack = S._slice_for(entry, "Этаж 1")
        t0 = time.perf_counter()
        S._render_frame(slice_ops, "Этаж 1")
        solo_ms = (time.perf_counter() - t0) * 1000.0
        print(f"\n[длинный прогон] программ={programs} "
              f"операций={entry.ops_held + entry.ops_evicted} "
              f"кран={publish_s * 1000:.1f} мс всего "
              f"({publish_s / programs * 1000:.3f} мс/программу) "
              f"прогон={total_s:.2f} с "
              f"кадров={st['frames_sent']} выброшено={st['dropped_frames']} "
              f"отрисовок={st['renders']} "
              f"среднее_время_кадра={st['render_ms_total'] / max(1, st['renders']):.1f} мс "
              f"кадр_без_гонки={solo_ms:.1f} мс (срез {len(slice_ops)} опов) "
              f"пик_памяти={peak_kb:.0f} КБ "
              f"вытеснено_программ={entry.programs_evicted}")

        # Кран обязан быть дешёвым: это то, что стоит СТРОЙКЕ.
        self.assertLess(publish_s / programs, 0.002,
                        f"кран дорог: {publish_s / programs * 1000:.3f} мс/программу")
        # Память ограничена потолком журнала, а не числом программ.
        self.assertLess(peak_kb, 60_000, f"память выросла на {peak_kb:.0f} КБ")
        self.assertEqual(st["journaled"], programs)
        self.assertEqual(entry.indexed_upto, entry.next_seq)

    def test_second_long_run_does_not_grow_the_first(self):
        """Утечка ловится не размером, а ПРИРОСТОМ между двумя прогонами."""
        def one_round():
            for i in range(200):
                S.publish(device_id="dev", doc_key="doc",
                          program=_program(*_walls(4, tag=f"{i}_")))
            return J.get(("dev", "doc")).ops_held

        os.environ["KUKAI_KIR_JOURNAL_PROGRAMS"] = "64"
        try:
            first = one_round()
            second = one_round()
            self.assertEqual(first, second,
                             "журнал растёт от прогона к прогону")
        finally:
            os.environ.pop("KUKAI_KIR_JOURNAL_PROGRAMS", None)


# ─────────────────────────────────────────────────────────────────────────────
# §5. ЧЕСТНОСТЬ ИСТОЧНИКА
# ─────────────────────────────────────────────────────────────────────────────

class HonestyTests(_Loop):

    def _one_frame(self):
        async def scenario():
            await self._wired()
            S.publish(device_id="dev", doc_key="doc",
                      program=_program(*_walls(4)), source="chat")
            await S.drain(10.0)

        self.run_async(scenario())
        self.assertTrue(self.sent, "кадр не доехал")
        return self.sent[-1]

    def test_frame_names_its_source_as_declared(self):
        """Метка `preview` доезжает до панели ЦЕЛОЙ.

        Без неё через месяц кто-нибудь скажет «я же видел, всё было
        нормально» — и мы получим приёмку через глаз.
        """
        frame = self._one_frame()
        self.assertEqual(frame["assertion"], "self_reported")
        self.assertEqual(frame["source"], "program")
        self.assertIn("ЗАЯВЛЕНО", frame["assertion_ru"])
        self.assertEqual(frame["stage"], "planned")

    def test_frame_carries_the_census(self):
        """Перепись честности едет с кадром: «нарисовано N из M, не нарисовано
        столько-то по названным причинам»."""
        frame = self._one_frame()
        census = frame["census"]
        self.assertIn("considered", census)
        self.assertIn("drawn", census)
        self.assertIn("omitted", census)
        self.assertEqual(census["considered"],
                         census["drawn"] + census["omitted_total"])
        self.assertIn("<svg", frame["svg"])

    def test_summary_never_says_built(self):
        """Сводка говорит «ЗАЯВЛЕНО», и слова «построено» в ней нет.

        Журнал наполняется ДО записи, поэтому часть программ Revit ещё
        отвергнет. Назвать это «построено» значило бы соврать ровно в том
        месте, ради которого весь экран.
        """
        frame = self._one_frame()
        summary = frame["summary"]
        self.assertEqual(summary["stage"], "planned")
        self.assertEqual(summary["assertion"], "self_reported")
        self.assertTrue(summary["title_ru"].startswith("ЗАЯВЛЕНО"),
                        summary["title_ru"])
        # «построено» в заголовке допустимо ровно в одной форме — отрицании.
        self.assertIn("не «построено»", summary["title_ru"])
        self.assertGreater(summary["total"], 0)

    def test_summary_counts_levels_and_ops(self):
        frame = self._one_frame()
        summary = frame["summary"]
        self.assertEqual([row["level"] for row in summary["levels"]], ["Этаж 1"])
        self.assertEqual(summary["by_op"]["create_wall"], 4)
        self.assertEqual(summary["by_op"]["create_level"], 1)


class EndToEndTests(_Loop):
    """Кадр из НАСТОЯЩЕГО плана компилятора, а не из рукописного словаря.

    Без этого все ворота выше меряли бы поток на своей же выдумке: рисовать
    надо ровно то, что мидэнд пропустил вниз — с раскрытыми макросами и
    проставленными умолчаниями.
    """

    def test_frame_from_a_real_planned_program(self):
        from kukai.ir.compiler import plan_program
        planned = plan_program(_program(*_walls(5)))

        async def scenario():
            await self._wired()
            S.publish(device_id="dev", doc_key="doc", program=planned,
                      source="chat")
            await S.drain(10.0)

        self.run_async(scenario())
        self.assertTrue(self.sent, "кадр из настоящего плана не доехал")
        frame = self.sent[-1]
        self.assertEqual(frame["assertion"], "self_reported")
        self.assertIn("<svg", frame["svg"])
        # Журнал держит РАСКРЫТЫЙ план, а не текст автора: подпись плана
        # приезжает от компилятора и совпадает с записанной.
        record = J.get(("dev", "doc")).records[-1]
        self.assertEqual(record.plan_digest, planned.plan_digest)
        self.assertEqual(record.op_count, len(planned.to_ops()))
        self.assertEqual(frame["census"]["drawn"], 5)

    def test_macro_expanded_program_is_drawn_as_lowered(self):
        """`stack` раскрывается ДО журнала — на листе этажи, а не макрос."""
        from kukai.ir.compiler import plan_program
        floor = [{"op": "create_wall", "id": f"W{i}",
                  "p0_mm": [i * 4000.0, 0.0],
                  "p1_mm": [i * 4000.0, 6000.0]} for i in range(4)]
        program = {
            "ir_version": "1.0", "intent": "башня",
            "ops": [{"op": "stack", "id": "ST", "levels": 3, "h_mm": 3000,
                     "floor": floor}],
        }
        planned = plan_program(program)
        S.publish(device_id="dev", doc_key="doc", program=planned)
        record = J.get(("dev", "doc")).records[-1]
        # 3 этажа × (create_level + 4 стены) = 15 операций.
        self.assertEqual(record.op_count, 15,
                         "в журнал лёг макрос, а не раскрытые операции")
        self.assertNotIn("stack", {op.get("op") for op in record.ops})

        async def scenario():
            await self._wired()
            S.publish(device_id="dev", doc_key="doc2", program=planned)
            await S.drain(10.0)

        self.run_async(scenario())
        # Три этажа — и каждый назван своим листом, а не «башней» одним куском.
        levels = {row["level"] for row in self.sent[-1]["summary"]["levels"]}
        self.assertEqual(len(levels), 3, levels)


if __name__ == "__main__":
    unittest.main()
