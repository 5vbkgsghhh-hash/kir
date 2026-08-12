"""ВОРОТА ВОЗВРАТА — «что видел, то и построится» ЗАМЕРОМ, а не обещанием.

Здесь доказываются два закона и одна честность:

  §1 ЗАКОН ПЕРВЫЙ — исполняется ровно показанное. Главный тест не «совпало»,
     а «ПОДМЕНА ОТВЕРГНУТА»: программа, которой сервер не показывал, не
     переносится, и отказ называет, чего именно не хватило.
  §2 ЗАКОН ВТОРОЙ — выделение замкнуто по графу прямого хода. Дверь без стены
     доращивается, добавленное НАЗЫВАЕТСЯ, и выросшая пачка НЕ исполняется,
     пока не подтверждена её собственная подпись.
  §3 ПЕРЕПИСЬ доезжает до человека рядом с картинкой и считается для того, что
     переносится, а не для листа.
  §4 ДОСТИЖИМОСТЬ нового кода из прод-процесса — прибором (`capability_graph`),
     а не grep'ом по импортам.

§1.1 — не тест, а сохранённый ЗАМЕР. Он объясняет, почему билетом на перенос
взята подпись программы, а не уже существующая подпись листа.
"""
from __future__ import annotations

import ast
import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_test_queue.jsonl"))

from kukai.live import journal as J          # noqa: E402
from kukai.live import plan_stream as S      # noqa: E402
from kukai.live import showroom as SR        # noqa: E402
from kukai.live import transfer as T         # noqa: E402

BACKEND = Path(__file__).resolve().parents[3]

KEY = ("dev", "")

LEVEL = {"op": "create_level", "id": "LV", "elev_mm": 0.0, "name": "Этаж 1"}
WALL = {"op": "create_wall", "id": "W1", "p0_mm": [0.0, 0.0],
        "p1_mm": [6000.0, 0.0], "level": {"by": "ref", "value": "LV"}}
DOOR = {"op": "create_door", "id": "D3", "offset_mm": 3000.0,
        "host": {"by": "ref", "value": "W1"}}


def _pack(*programs):
    return [list(p) for p in programs]


class _Base(unittest.TestCase):

    def setUp(self):
        S.reset()
        SR.reset()

    def tearDown(self):
        S.reset()
        SR.reset()

    def shown(self, programs, context=(LEVEL,), level="Этаж 1"):
        entry = SR.show(KEY, level=level, programs=programs, context=context)
        self.assertIsNotNone(entry, "витрина обязана принять кодируемую пачку")
        return entry


# ─────────────────────────────────────────────────────────────────────────────
# §1. ЗАКОН ПЕРВЫЙ: смотрим и строим ОДНУ программу
# ─────────────────────────────────────────────────────────────────────────────

class OneProgramTests(_Base):

    def test_sheet_digest_does_not_identify_the_program(self):
        """ЗАМЕР, из-за которого билетом взята подпись ПРОГРАММЫ.

        `FloorPlan.content_digest` подписывает картинку — и обязан подписывать
        именно её. Но высота стены и её тип на плане не рисуются, поэтому три
        разные программы дают ОДИН дайджест листа. Возьми мы его билетом,
        кнопка «построй, что вижу» строила бы кирпичную стену 4.2 м под
        подписью обычной — вторая подпись у одного здания.
        """
        from kukai.ir.preview import build_program_preview

        def sheet(extra):
            program = {"ir_version": "1.0", "intent": "t",
                       "ops": [LEVEL, {**WALL, **extra}]}
            return build_program_preview(program).plan("Этаж 1").content_digest

        plain, tall = sheet({}), sheet({"height_mm": 4200.0})
        typed = sheet({"type_name": "Кирпич 380"})
        self.assertEqual(plain, tall, "лист их и не различает — это про лист")
        self.assertEqual(plain, typed)

        def program(extra):
            return SR.program_digest(
                (SR.canonical_program([LEVEL, {**WALL, **extra}]),),
                SR.canonical_program([]), "Этаж 1")

        self.assertNotEqual(program({}), program({"height_mm": 4200.0}))
        self.assertNotEqual(program({}), program({"type_name": "Кирпич 380"}))

    def test_frame_carries_the_program_signature(self):
        """Кадр уходит человеку С ПОДПИСЬЮ, и подпись адресует витрину."""
        sent: list[dict] = []

        async def scenario():
            async def transport(device_id, payload):
                sent.append(payload)
            S.bind_transport(transport)
            S.attach("dev")
            S.publish(device_id="dev", program={
                "ir_version": "1.0", "intent": "стена",
                "ops": [LEVEL, WALL]})
            await S.drain()

        asyncio.run(scenario())
        self.assertTrue(sent, "кадр обязан доехать")
        frame = sent[-1]
        self.assertTrue(frame["transferable"])
        self.assertEqual(len(frame["program_digest"]), 64)
        self.assertEqual(frame["program_count"], 1)
        self.assertEqual(frame["program_ops"], 2)
        # И подпись действительно достаёт ТЕЛО.
        body = T.redeem(KEY, frame["program_digest"])
        self.assertEqual(body, [[LEVEL, WALL]])

    def test_what_was_seen_is_what_is_built(self):
        """Равенство подписей — и есть закон, выраженный значением."""
        entry = self.shown(_pack([LEVEL, WALL, DOOR]))
        decision = T.authorize(KEY, digest=entry.digest)
        self.assertIs(decision.status, T.Status.READY)
        self.assertEqual(decision.transfer_digest, decision.requested_digest)
        self.assertEqual(T.redeem(KEY, decision.transfer_digest),
                         [[LEVEL, WALL, DOOR]])

    def test_substituted_program_is_refused_and_names_the_gap(self):
        """ГЛАВНЫЙ ТЕСТ ВОЛНЫ. Подменённая программа не переносится.

        Подмена здесь не «поймана сравнением» — она НЕПРОИЗНОСИМА: у панели
        нет способа назвать программу, которой сервер не показывал. Подпись
        подделки просто не адресует ничего.
        """
        entry = self.shown(_pack([LEVEL, WALL]))
        tampered = dict(WALL, p1_mm=[60000.0, 0.0])          # 6 м -> 60 м
        forged = SR.program_digest(
            (SR.canonical_program([LEVEL, tampered]),),
            entry.context_json, entry.level)
        self.assertNotEqual(forged, entry.digest)

        decision = T.authorize(KEY, digest=forged)
        self.assertIs(decision.status, T.Status.REFUSED)
        self.assertIs(decision.refusal, T.Refusal.NOT_SHOWN)
        self.assertIn("не показывал", decision.refusal_ru)
        # Отказ НАЗЫВАЕТ, что сервер помнит, — иначе он бесполезен.
        self.assertEqual(decision.diverged,
                         (f"Этаж 1={entry.digest[:16]}",))
        self.assertIsNone(T.redeem(KEY, forged), "тела у подделки нет")

    def test_store_corruption_is_typed_and_names_both_digests(self):
        """Второй рубеж: подпись пересчитывается ИЗ ХРАНИМОГО перед выдачей."""
        entry = self.shown(_pack([LEVEL, WALL]))
        room = SR._ROOMS[KEY]                                # noqa: SLF001
        broken = SR.Shown(
            digest=entry.digest, level=entry.level, seq=entry.seq, ts=entry.ts,
            programs_json=(SR.canonical_program([LEVEL, dict(WALL, id="ПОДМЕНА")]),),
            context_json=entry.context_json, census=entry.census)
        room.frames[entry.digest] = broken

        decision = T.authorize(KEY, digest=entry.digest)
        self.assertIs(decision.refusal, T.Refusal.STORE_CORRUPT)
        self.assertEqual(len(decision.diverged), 2)
        self.assertIn("подписано", decision.diverged[0])
        self.assertIn("хранится", decision.diverged[1])
        self.assertIsNone(T.redeem(KEY, entry.digest),
                          "испорченный кадр не выдаётся исполнителю")

    def test_executor_body_never_arrives_from_the_panel(self):
        """СТРУКТУРНО: тело программы приходит из витрины, не из сообщения.

        Проверяется обходом `ast`, а не глазами: обработчик переноса в
        `chat_ws` не имеет права читать из входящего словаря ничего, кроме
        подписи, выделения и флага подтверждения. Стоит ему прочитать `ops` —
        и закон превращается в договорённость.
        """
        source = (BACKEND / "kukai/api/chat_ws.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        handler = next(
            (node for node in ast.walk(tree)
             if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
             and node.name == "_handle_kir_transfer"), None)
        self.assertIsNotNone(handler, "обработчик переноса не найден")

        read: set[str] = set()
        for node in ast.walk(handler):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "get"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "data"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)):
                read.add(str(node.args[0].value))
            if (isinstance(node, ast.Subscript)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "data"
                    and isinstance(node.slice, ast.Constant)):
                read.add(str(node.slice.value))
        self.assertTrue(read, "обработчик обязан хоть что-то читать из data")
        self.assertEqual(
            read - {"digest", "selection", "confirm", "type"}, set(),
            f"из панели читается лишнее: {sorted(read)} — тело программы "
            f"обязано приходить ТОЛЬКО из витрины по подписи")


# ─────────────────────────────────────────────────────────────────────────────
# §2. ЗАКОН ВТОРОЙ: подмножество замкнуто по зависимостям
# ─────────────────────────────────────────────────────────────────────────────

class ClosureTests(_Base):

    def test_door_alone_is_grown_to_its_host_and_the_growth_is_named(self):
        entry = self.shown(_pack([LEVEL, WALL, DOOR]))
        decision = T.authorize(KEY, digest=entry.digest, selection=["D3"])

        self.assertIs(decision.status, T.Status.NEEDS_CONFIRM)
        self.assertEqual([a.op_id for a in decision.added], ["LV", "W1"])
        by_id = {a.op_id: a for a in decision.added}
        self.assertEqual((by_id["W1"].needed_by, by_id["W1"].via), ("D3", "host"))
        self.assertEqual((by_id["LV"].needed_by, by_id["LV"].via), ("W1", "level"))
        self.assertIn("его требует «D3» (поле host)",
                      by_id["W1"].to_dict()["ru"])
        # Порядок программы сохранён: ref обязан смотреть НАЗАД.
        self.assertEqual([op["id"] for op in
                          T.redeem(KEY, decision.transfer_digest)[0]],
                         ["LV", "W1", "D3"])

    def test_grown_pack_needs_its_own_signature_before_it_can_be_built(self):
        """Доращивание НЕ исполняется молча: у выросшей пачки своя подпись.

        Программа шире выделения намеренно: замыкание даёт СОБСТВЕННОЕ
        подмножество, и его подпись обязана отличаться от подписи листа.
        """
        other = dict(WALL, id="W2", p0_mm=[0.0, 5000.0], p1_mm=[6000.0, 5000.0])
        entry = self.shown(_pack([LEVEL, WALL, DOOR, other]))
        grown = T.authorize(KEY, digest=entry.digest, selection=["D3"])
        self.assertIs(grown.status, T.Status.NEEDS_CONFIRM)
        self.assertNotEqual(grown.transfer_digest, grown.requested_digest)
        self.assertEqual([a.op_id for a in grown.added], ["LV", "W1"])

        # Второй запрос несёт НОВУЮ подпись — и только тогда статус READY.
        confirmed = T.authorize(KEY, digest=grown.transfer_digest)
        self.assertIs(confirmed.status, T.Status.READY)
        self.assertEqual(confirmed.transfer_digest, grown.transfer_digest)
        self.assertEqual(confirmed.added, ())
        self.assertEqual([op["id"] for op in
                          T.redeem(KEY, confirmed.transfer_digest)[0]],
                         ["LV", "W1", "D3"])

    def test_growth_to_the_whole_program_still_asks_for_confirmation(self):
        """Замыкание доросло до ВСЕЙ программы — подпись совпала с листом, но
        добавленное всё равно названо, и статус всё равно `needs_confirm`.

        Иначе «подпись та же» стало бы лазейкой: человек подсветил дверь, а
        построилось три операции, и никто ему этого не сказал."""
        entry = self.shown(_pack([LEVEL, WALL, DOOR]))
        grown = T.authorize(KEY, digest=entry.digest, selection=["D3"])
        self.assertEqual(grown.transfer_digest, grown.requested_digest)
        self.assertIs(grown.status, T.Status.NEEDS_CONFIRM)
        self.assertEqual([a.op_id for a in grown.added], ["LV", "W1"])

    def test_selecting_a_wall_alone_grows_only_its_level(self):
        """Обратного ребра нет: стене её дверь не нужна."""
        entry = self.shown(_pack([LEVEL, WALL, DOOR]))
        decision = T.authorize(KEY, digest=entry.digest, selection=["W1"])
        ids = [op["id"] for op in T.redeem(KEY, decision.transfer_digest)[0]]
        self.assertEqual(ids, ["LV", "W1"])
        self.assertNotIn("D3", ids)

    def test_closure_reads_the_registry_not_a_list_of_field_names(self):
        """ПАРИТЕТ С КОМПИЛЯТОРОМ по ВСЕМУ реестру, а не на паре примеров.

        Для каждой операции реестра строится синтетический оп, где КАЖДЫЙ
        параметр, способный нести ссылку, её несёт. `refs_of` обязан вернуть
        ровно те поля, которые собрал бы `compiler.py:610-619`. Список имён
        полей («host», «level», «wall») разъехался бы с реестром на первой же
        новой операции — и разъехался бы молча.
        """
        from kukai.ir import spec

        checked = 0
        for name, ospec in spec.OPS.items():
            op: dict = {"op": name, "id": "X"}
            expected: list[tuple[str, str]] = []
            for param in ospec.params:
                if not param.ref_kinds:
                    continue
                if param.kind in ("sel", "target_w"):
                    op[param.name] = {"by": "ref", "value": f"R_{param.name}"}
                    expected.append((param.name, f"R_{param.name}"))
                elif param.kind == "refs_w":
                    op[param.name] = [{"by": "ref", "value": f"R_{param.name}"}]
                    expected.append((f"{param.name}[0]", f"R_{param.name}"))
            if not expected:
                continue
            checked += 1
            self.assertEqual(sorted(T.refs_of(op)), sorted(expected),
                             f"{name}: рёбра разошлись с реестром")
        self.assertGreater(checked, 5,
                           "реестр обязан содержать ссылочные операции")

    def test_closure_does_not_cross_program_boundaries(self):
        """Между программами пачки рёбер `ref` нет — их не изобретают.

        ГРАНИЦА НАЗВАНА ЧЕСТНО. Программа, чей `ref` смотрит наружу, невалидна
        и БЕЗ выделения — `compiler` отвергает её кодом KIR-L003. Замыкание
        такую ссылку не тянет и не «чинит»: второй экземпляр правила «куда
        может смотреть ref» разъехался бы с первым. Судит компилятор, а
        предполётная проверка решения (`preflight`) показывает его вердикт
        ОФЛАЙН — до устройства.
        """
        entry = self.shown(_pack([LEVEL, WALL], [dict(LEVEL), DOOR]))
        decision = T.authorize(KEY, digest=entry.digest, selection=["D3"])
        body = T.redeem(KEY, decision.transfer_digest)
        self.assertEqual(len(body), 1, "программа без выделенного не едет")
        # W1 живёт в СОСЕДНЕЙ программе: тянуть его сюда значило бы завести
        # ребро, которого в языке нет (компилятор резолвит ref внутри одной).
        self.assertEqual([op["id"] for op in body[0]], ["D3"])
        self.assertTrue(decision.preflight,
                        "висячий ref обязан быть назван ОФЛАЙН, а не на устройстве")
        self.assertTrue(any("KIR-L003" in line for line in decision.preflight),
                        decision.preflight)

    def test_empty_selection_is_a_named_refusal_not_a_silent_whole(self):
        entry = self.shown(_pack([LEVEL, WALL]))
        decision = T.authorize(KEY, digest=entry.digest, selection=[])
        self.assertIs(decision.refusal, T.Refusal.SELECTION_EMPTY)

    def test_selection_from_another_frame_is_refused_by_name(self):
        entry = self.shown(_pack([LEVEL, WALL]))
        decision = T.authorize(KEY, digest=entry.digest, selection=["D3", "W9"])
        self.assertIs(decision.refusal, T.Refusal.SELECTION_UNKNOWN)
        self.assertEqual(decision.diverged, ("D3", "W9"))

    def test_over_budget_programs_are_named_before_revit_is_touched(self):
        """Длина программы меряется ОФЛАЙН: узнать это на устройстве стоит
        круглого рейса через самый дорогой ресурс."""
        from kukai.ir.compiler import MAX_OPS_PER_PROGRAM
        many = [LEVEL] + [dict(WALL, id=f"W{i}") for i in range(MAX_OPS_PER_PROGRAM)]
        entry = self.shown(_pack(many))
        decision = T.authorize(KEY, digest=entry.digest)
        self.assertTrue(decision.over_budget)
        self.assertIn(str(MAX_OPS_PER_PROGRAM), decision.over_budget[0])


# ─────────────────────────────────────────────────────────────────────────────
# §3. ПЕРЕПИСЬ
# ─────────────────────────────────────────────────────────────────────────────

class CensusTests(_Base):

    def test_frame_carries_the_census_in_full_russian_lines(self):
        sent: list[dict] = []

        async def scenario():
            async def transport(device_id, payload):
                sent.append(payload)
            S.bind_transport(transport)
            S.attach("dev")
            S.publish(device_id="dev", program={
                "ir_version": "1.0", "intent": "перепись",
                # create_room рисуется точкой (приближение), а create_level в
                # плане не виден — обе строки обязаны доехать текстом.
                "ops": [LEVEL, WALL,
                        {"op": "create_room", "id": "R1", "xy_mm": [1000.0, 1000.0],
                         "level": {"by": "ref", "value": "LV"}}]})
            await S.drain()

        asyncio.run(scenario())
        frame = sent[-1]
        lines = frame["census_lines"]
        self.assertTrue(lines, "перепись обязана ехать рядом с картинкой")
        self.assertTrue(all(line["ru"] and line["ru"] != line["reason"]
                            for line in lines),
                        "каждая строка переписи обязана быть по-русски")
        groups = (len(frame["census"]["omitted"]) + len(frame["census"]["approx"])
                  + len(frame["census"]["anomalies"]))
        self.assertEqual(len(lines), groups, "перепись едет ЦЕЛИКОМ, без срезов")

    def test_decision_census_is_about_the_transfer_not_the_sheet(self):
        entry = self.shown(_pack([LEVEL, WALL, DOOR]))
        whole = T.authorize(KEY, digest=entry.digest)
        part = T.authorize(KEY, digest=entry.digest, selection=["W1"])
        self.assertGreater(whole.census["considered"], part.census["considered"],
                           "перепись решения обязана считать переносимое")

    def test_sheet_names_every_truncation_of_the_census(self):
        """ОПРОВЕРГАЮЩИЙ ЗАМЕР (04.08, до правки): подвал печатал 5 из 7 строк
        приближений, 4 из 5 аномалий и 4 из 6 слепых пятен — и молчал об этом.
        Молчание переписи это тот самый класс дефекта, ради запрета которого
        `PreviewCensus` вообще написан."""
        from kukai.ir import preview as P

        census = P.PreviewCensus(
            considered=len(list(P.OmitReason)), drawn=0,
            omitted=tuple(P.OmissionGroup(reason=r, category=f"c{i}", count=1)
                          for i, r in enumerate(P.OmitReason)),
            approx=tuple(P.ApproxGroup(reason=r, count=1)
                         for r in P.ApproxReason),
            anomalies=tuple(P.AnomalyGroup(reason=r, count=1)
                            for r in P.AnomalyReason))
        svg = P.render_svg(P.FloorPlan(
            source=P.PreviewSource.PROGRAM, doc_name="d", level_name="L1",
            level_elevation_mm=0.0, elements=(), census=census))
        for what in ("строк(и) причин", "строк(и) приближений",
                     "строк(и) аномалий", "вид(а) слепоты"):
            self.assertIn(what, svg, f"урезание не названо: {what}")
        # И полный текст доступен получателю без всяких срезов.
        self.assertEqual(len(P.census_lines(census)),
                         len(census.omitted) + len(census.approx)
                         + len(census.anomalies))


# ─────────────────────────────────────────────────────────────────────────────
# §4. ДОСТИЖИМОСТЬ И ГРАНИЦЫ
# ─────────────────────────────────────────────────────────────────────────────

def _graph():
    sys.path.insert(0, str(BACKEND / "tests"))
    try:
        import capability_graph  # noqa: WPS433
        return capability_graph.Graph(BACKEND)
    finally:
        if sys.path and sys.path[0] == str(BACKEND / "tests"):
            sys.path.pop(0)


class ReachabilityTests(unittest.TestCase):

    def test_transfer_is_reachable_from_the_prod_process(self):
        """ФЛАГ ≠ ДОСТИЖИМОСТЬ. Меряем прибором, а не grep'ом по импортам."""
        live = _graph().live()
        for module in ("kukai.live.showroom", "kukai.live.transfer"):
            self.assertIn(module, live,
                          f"{module} не достижим из прод-процесса — код тёмный")

    def test_showroom_keeps_the_stream_one_way(self):
        """Витрину наполняет РИСОВАЛЬЩИК, значит она обязана остаться листом.

        Появись у неё путь в компилятор — и односторонность потока, доказанная
        `test_live_plan_stream.py`, стала бы ложной через `plan_stream` ->
        `showroom` -> …. Возврат живёт в `transfer.py` ИМЕННО ПОЭТОМУ.
        """
        graph = _graph()
        module = graph.modules["kukai.live.showroom"]
        edges = module.imports | module.dynamic_imports
        self.assertEqual([e for e in edges if e.startswith("kukai.")], [],
                         "витрина обязана быть stdlib-листом")

    def test_transfer_is_not_imported_by_the_drawing_path(self):
        graph = _graph()
        for name in ("kukai.live.plan_stream", "kukai.live.journal",
                     "kukai.live.showroom"):
            module = graph.modules[name]
            self.assertNotIn("kukai.live.transfer",
                             module.imports | module.dynamic_imports,
                             f"{name} не имеет права знать о возврате")


class BoundednessTests(_Base):

    def test_showroom_is_bounded_and_counts_what_it_forgot(self):
        os.environ["KUKAI_KIR_SHOWROOM_FRAMES"] = "3"
        try:
            digests = [self.shown(_pack([LEVEL, dict(WALL, id=f"W{i}")])).digest
                       for i in range(6)]
        finally:
            os.environ.pop("KUKAI_KIR_SHOWROOM_FRAMES", None)
        stats = SR.stats()
        self.assertEqual(stats["frames"], 3)
        self.assertEqual(stats["evicted"], 3)
        self.assertIsNone(T.redeem(KEY, digests[0]), "вытесненное не выдаётся")
        self.assertIsNotNone(T.redeem(KEY, digests[-1]))
        # И вытеснение НЕ становится тихой подменой: отказ типизирован.
        self.assertIs(T.authorize(KEY, digest=digests[0]).refusal,
                      T.Refusal.NOT_SHOWN)

    def test_disabled_transfer_refuses_by_name(self):
        entry = self.shown(_pack([LEVEL, WALL]))
        os.environ["KUKAI_KIR_TRANSFER"] = "0"
        try:
            self.assertIs(T.authorize(KEY, digest=entry.digest).refusal,
                          T.Refusal.DISABLED)
        finally:
            os.environ.pop("KUKAI_KIR_TRANSFER", None)

    def test_journal_and_stream_survive_a_broken_showroom(self):
        """Витрина ломается — стройка не замечает, кадр всё равно едет."""
        sent: list[dict] = []
        original = SR.show

        async def scenario():
            async def transport(device_id, payload):
                sent.append(payload)
            S.bind_transport(transport)
            S.attach("dev")
            SR.show = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("витрина"))
            try:
                S.publish(device_id="dev", program={
                    "ir_version": "1.0", "intent": "t", "ops": [LEVEL, WALL]})
                await S.drain()
            finally:
                SR.show = original

        asyncio.run(scenario())
        self.assertTrue(sent, "кадр обязан доехать и без витрины")
        self.assertFalse(sent[-1]["transferable"])
        self.assertIn("перенос недоступен", sent[-1]["transfer_blocked_ru"])
        self.assertEqual(S.stats()["showroom_errors"], 1)
        self.assertEqual(J.get(KEY).stats()["programs"], 1,
                         "журнал программ обязан остаться полным")


# ─────────────────────────────────────────────────────────────────────────────
# §5. КРУГ ЦЕЛИКОМ: кадр -> панель -> дверь
# ─────────────────────────────────────────────────────────────────────────────

class RoundTripTests(_Base):
    """Через НАСТОЯЩУЮ дверь `chat_ws._handle_kir_transfer`, а не мимо неё.

    Дверь `revit_ir` подменена: живого Revit нет, а доказать надо не «Revit
    построил», а «до Revit доехали РОВНО те операции, что видел человек».
    """

    def _drive(self, messages, program):
        """Проиграть кадр, затем скормить двери сообщения панели."""
        from kukai.api import chat_ws
        from kukai.ir import serving

        sent: list[dict] = []
        handed: list[list[dict]] = []

        async def fake_send(ws, payload):
            sent.append(payload)

        async def fake_door(args, llm_client, bridge, query_id="", **_identity):
            handed.append(args["program"]["ops"])
            return {"ok": True, "created": len(args["program"]["ops"])}

        async def scenario():
            async def transport(device_id, payload):
                sent.append(payload)
            S.bind_transport(transport)
            S.attach("dev")
            S.publish(device_id="dev", program=program)
            await S.drain()
            for message in messages(sent):
                await chat_ws._handle_kir_transfer(   # noqa: SLF001
                    message, object(), ws_id="w", device_id="dev")

        old_send, old_door = chat_ws._send_json, serving.handle_revit_ir
        chat_ws._send_json = fake_send
        serving.handle_revit_ir = fake_door
        try:
            asyncio.run(scenario())
        finally:
            chat_ws._send_json = old_send
            serving.handle_revit_ir = old_door
        return sent, handed

    def test_what_the_panel_saw_is_byte_for_byte_what_reaches_the_door(self):
        program = {"ir_version": "1.0", "intent": "круг",
                   "ops": [LEVEL, WALL, DOOR]}
        sent, handed = self._drive(
            lambda s: [{"type": "kir_transfer",
                        "digest": s[-1]["program_digest"], "confirm": True}],
            program)
        frame = sent[0]
        self.assertTrue(frame["transferable"])
        self.assertEqual(handed, [[LEVEL, WALL, DOOR]],
                         "до двери обязаны доехать РОВНО показанные операции")
        result = [m for m in sent if m.get("type") == "kir_transfer_result"]
        self.assertTrue(result and result[-1]["ok"])

    def test_forged_digest_is_refused_and_the_door_is_never_called(self):
        """ОТКАЗ ПРИ ПОДМЕНЕ, замером, на живом пути.

        Панель присылает подпись программы, которой сервер не показывал (стена
        растянута с 6 м до 60 м). Дверь `revit_ir` не вызывается НИ РАЗУ.
        """
        program = {"ir_version": "1.0", "intent": "круг",
                   "ops": [LEVEL, WALL]}

        def messages(sent):
            forged = SR.program_digest(
                (SR.canonical_program([LEVEL, dict(WALL, p1_mm=[60000.0, 0.0])]),),
                SR.canonical_program([LEVEL]), "Этаж 1")
            return [{"type": "kir_transfer", "digest": forged, "confirm": True}]

        sent, handed = self._drive(messages, program)
        self.assertEqual(handed, [], "подделка не имеет права дойти до двери")
        decisions = [m for m in sent if m.get("type") == "kir_transfer_decision"]
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0]["status"], "refused")
        self.assertEqual(decisions[0]["refusal"], "not_shown")
        self.assertFalse(decisions[0]["executed"])
        self.assertFalse([m for m in sent
                          if m.get("type") == "kir_transfer_result"])

    def test_first_request_never_builds_even_with_confirm(self):
        """`confirm=true` на ВЫРОСШЕЙ пачке не строит: сначала называем, что
        добавлено, и только по её собственной подписи строим."""
        other = dict(WALL, id="W2", p0_mm=[0.0, 5000.0], p1_mm=[6000.0, 5000.0])
        program = {"ir_version": "1.0", "intent": "круг",
                   "ops": [LEVEL, WALL, DOOR, other]}
        sent, handed = self._drive(
            lambda s: [{"type": "kir_transfer",
                        "digest": s[-1]["program_digest"],
                        "selection": ["D3"], "confirm": True}],
            program)
        self.assertEqual(handed, [], "доращивание не строится с первого клика")
        decision = [m for m in sent
                    if m.get("type") == "kir_transfer_decision"][-1]
        self.assertEqual(decision["status"], "needs_confirm")
        self.assertEqual([a["id"] for a in decision["added"]], ["LV", "W1"])

    def test_confirming_the_grown_signature_builds_exactly_the_closure(self):
        other = dict(WALL, id="W2", p0_mm=[0.0, 5000.0], p1_mm=[6000.0, 5000.0])
        program = {"ir_version": "1.0", "intent": "круг",
                   "ops": [LEVEL, WALL, DOOR, other]}

        def messages(sent):
            grown = T.authorize(KEY, digest=sent[-1]["program_digest"],
                                selection=["D3"])
            return [{"type": "kir_transfer", "digest": grown.transfer_digest,
                     "confirm": True}]

        sent, handed = self._drive(messages, program)
        self.assertEqual(handed, [[LEVEL, WALL, DOOR]])
        self.assertNotIn("W2", [op["id"] for op in handed[0]])


if __name__ == "__main__":
    unittest.main()
