"""`kukai/clash/` БЫЛ ТЁМЕН — И ТЕПЕРЬ У НЕГО ЕСТЬ ПРОД-ВХОД.

ЧТО ЗАМЕРЕНО ПЕРЕД ПРАВКОЙ (09.08, `tests/capability_graph.py`). Пакет
`kukai/clash/` — SAT/MTV, выпуклая оболочка, широкая фаза, закрытая таблица
категорий, канонический байт-в-байт отчёт, шесть наборов тестов — не имел НИ
ОДНОГО достижимого из прода импортёра: `graph.live()` не содержал ни одного
модуля `kukai.clash.*`. Единственный вход — ручной CLI. Опровергающий замер
записан здесь честно, а тест ниже проверяет ПОСЛЕ.

ШОВ — ПАЧКА, а не программа: ссылка через границу программы незаконна
(`KIR-V002`), поэтому две дисциплины (АР / КР / ОВ) никогда не окажутся в одной
программе, и пачка сессии есть единственное место, где компилятор держит звенья
разных авторов одновременно. Проверка в `check_ops` была бы вакуумна ПО
ПОСТРОЕНИЮ для того самого случая, ради которого её строят.

НАХОДКА — СВИДЕТЕЛЬСТВО, А НЕ ВЕРДИКТ. Половина этого файла именно об этом:
клеш не имеет права ни изменить `verdict`, ни попасть в `blocking`, ни стоить
хода. Ложный отказ верной постройке — класс `acceptance-broke-on-Cyrillic`, и
он дороже пропущенной находки.

Прогон:
    KUKAI_CHECKER_V2=1 venv/bin/python3.12 -m pytest \
        kukai/ir/tests/test_clash_in_the_receipt.py -q
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("KUKAI_CHECKER_V2", "1")
os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_test_queue.jsonl"))

from kukai.clash import hulls as H  # noqa: E402
from kukai.ir import clash_bundle as CB  # noqa: E402
from kukai.ir import design_check as DC  # noqa: E402
from kukai.ir import serving, spec  # noqa: E402
from kukai.ir.tests.acceptance_fakes import PassingAcceptanceBridge  # noqa: E402
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT  # noqa: E402
from kukai.live import journal as J  # noqa: E402
from kukai.live import verdict as V  # noqa: E402
from kukai.ir.tests.gate_fixture import enter_kir_mode

BACKEND = Path(__file__).resolve().parents[3]


def _run(coro):
    return asyncio.run(coro)


# ═════════════════════════════════════════════════════════════════════════
# Материал: здание ТРЕМЯ звеньями, как его и обязана строить многоагентная
# раскладка — АР пишет коробку, ОВ ведёт воздуховоды, ВК ведёт трубу.
# ═════════════════════════════════════════════════════════════════════════

BOX = [((0, 0), (8000, 0)), ((8000, 0), (8000, 5000)),
       ((8000, 5000), (0, 5000)), ((0, 5000), (0, 0)),
       ((4000, 0), (4000, 5000))]

_L1 = {"by": "ref", "value": "lvl"}
_L1_BY_NAME = {"by": "name", "value": "Этаж 1"}


def ar_program() -> dict:
    ops: list[dict] = [
        {"op": "create_level", "id": "lvl", "elev_mm": 0, "name": "Этаж 1"},
    ]
    for i, (p0, p1) in enumerate(BOX, start=1):
        ops.append({"op": "create_wall", "id": f"w{i}", "p0_mm": list(p0),
                    "p1_mm": list(p1), "level": _L1, "height_mm": 3000})
    ops.append({"op": "create_room", "id": "r1", "xy": [6000, 2500],
                "level": _L1, "name": "Жилая комната"})
    ops.append({"op": "create_room", "id": "r2", "xy": [2000, 2500],
                "level": _L1, "name": "Лестничная клетка"})
    ops.append({"op": "create_door", "id": "d1", "offset_mm": 2500,
                "host": {"by": "ref", "value": "w5"}})
    ops.append({"op": "create_door", "id": "entrance", "offset_mm": 2000,
                "host": {"by": "ref", "value": "w1"}})
    ops.append({"op": "create_window", "id": "win", "offset_mm": 2500,
                "host": {"by": "ref", "value": "w2"}})
    return {"ir_version": "1.0", "ops": ops}


def ov_program(duct_id: str = "duct1") -> dict:
    """ОВ: магистраль вдоль здания и отвод поперёк — они ПЕРЕСЕКАЮТСЯ."""
    return {"ir_version": "1.0", "ops": [
        {"op": "create_duct", "id": duct_id,
         "p0_mm": [200, 1000, 2700], "p1_mm": [7800, 1000, 2700],
         "level": _L1_BY_NAME, "diameter_mm": 400},
        {"op": "create_duct", "id": "duct2",
         "p0_mm": [4000, 200, 2700], "p1_mm": [4000, 4800, 2700],
         "level": _L1_BY_NAME, "diameter_mm": 300},
    ]}


def touching_ducts_program() -> dict:
    """Два воздуховода, стоящих ВПЛОТНУЮ: оси на 350 мм, радиусы 200 и 150.
    Касание трасс — тот самый случай, для которого правило ОТКАЗАНО: зазор
    между сетями нормируется, а его величину программа не выражает."""
    return {"ir_version": "1.0", "ops": [
        {"op": "create_duct", "id": "near1",
         "p0_mm": [5000, 1000, 2700], "p1_mm": [7800, 1000, 2700],
         "level": _L1_BY_NAME, "diameter_mm": 400},
        {"op": "create_duct", "id": "near2",
         "p0_mm": [5000, 1350, 2700], "p1_mm": [7800, 1350, 2700],
         "level": _L1_BY_NAME, "diameter_mm": 300},
    ]}


def grid_programs(programs: int = 3, per: int = 8,
                  span: float = 60_000.0) -> list[dict]:
    """Решётка воздуховодов НЕСКОЛЬКИМИ ЗАКОННЫМИ программами: бюджет автора —
    20 операций на программу (`MAX_OPS_PER_PROGRAM`), и обходить его в тесте
    значило бы проверять дверь, которой нет."""
    out: list[dict] = []
    total = programs * per
    for index in range(programs):
        ops = []
        for j in range(per):
            k = index * per + j + 1
            t = k * span / (total + 1)
            if k % 2:
                p0, p1 = [0.0, t, 2700.0], [span, t, 2700.0]
            else:
                p0, p1 = [t, 0.0, 2700.0], [t, span, 2700.0]
            ops.append({"op": "create_duct", "id": f"d{k}", "p0_mm": p0,
                        "p1_mm": p1, "level": _L1_BY_NAME,
                        "diameter_mm": 400})
        out.append({"ir_version": "1.0", "ops": ops})
    return out


def vk_program() -> dict:
    """ВК: труба с объявленным диаметром — и он НОМИНАЛЬНЫЙ."""
    return {"ir_version": "1.0", "ops": [
        {"op": "create_pipe", "id": "pipe1",
         "p0_mm": [200, 3000, 2500], "p1_mm": [7800, 3000, 2500],
         "level": _L1_BY_NAME, "diameter_mm": 100},
    ]}


class _Door(unittest.TestCase):
    """Прод-дверь целиком: гейт открыт, устройство админское, мост подменён."""

    def setUp(self) -> None:
        self.DEVICE = serving.ADMIN_DEVICE
        self._env: dict[str, str | None] = {}
        self._set("KUKAI_KIR_TOOL", "stage2")
        self._device = mock.patch.object(
            serving, "_turn_device_id", return_value=self.DEVICE)
        self._device.start()
        self.llm = mock.Mock()
        self.llm._revit_version = "2026"
        self._acc = tempfile.TemporaryDirectory()
        self._set("KIR_ACCEPTANCE_EVIDENCE_DIR", self._acc.name)
        self._feed = tempfile.TemporaryDirectory()
        self._set("KIR_WITNESS_PATH", os.path.join(self._feed.name, "w.jsonl"))
        CB._CACHE.clear()
        J.reset()
        # ТРЕТЬЕ УСЛОВИЕ ГЕЙТА (13.08): режим КИР ставится ЯВНО.
        enter_kir_mode(self)

    def _set(self, name: str, value: str | None) -> None:
        self._env.setdefault(name, os.environ.get(name))
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value

    def tearDown(self) -> None:
        self._device.stop()
        for name, prev in self._env.items():
            if prev is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = prev
        self._acc.cleanup()
        self._feed.cleanup()
        CB._CACHE.clear()
        J.reset()

    def send(self, program: dict) -> dict:
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

    def build(self, programs) -> dict:
        last: dict = {}
        for program in programs:
            last = self.send(program)
        return last


# ═════════════════════════════════════════════════════════════════════════
# 1. ЗАКРЫТАЯ ТАБЛИЦА: НИ ОДНА ОПЕРАЦИЯ НЕ ВЫПАДАЕТ МОЛЧА
# ═════════════════════════════════════════════════════════════════════════

class TheTableIsClosed(unittest.TestCase):

    def test_every_registered_op_leaves_the_table_with_one_outcome(self) -> None:
        """Тот же закон, что у `hulls.KIND_TABLE`. Новая операция, добавляющая
        зданию тела, обязана либо получить категорию, либо назвать причину, по
        которой тела у неё нет, — иначе поиск молча теряет элементы, а отчёт
        остаётся «исправным»."""
        # ДВА ИСХОДА, И ОНИ СПРАШИВАЮТСЯ, А НЕ ОБЪЯВЛЯЮТСЯ (11.08.2026).
        # Здесь стояло `set(CB.OP_CATEGORY) | set(CB.OP_NO_BODY)` — теневая
        # таблица против реестра. Её сняли, тест упал на `AttributeError` и
        # ЗАКОН ПЕРЕСТАЛ ИСПОЛНЯТЬСЯ: ровно тогда две операции и выпали из
        # таблицы молча (`create_space`, `create_curtain_grid_line` — обе
        # названы в `OP_NO_BODY` при воскрешении этого сторожа).
        answered = {name for name in CB.body_making_ops()
                    if CB.op_categories(name)}
        covered = answered | set(CB.OP_NO_BODY)
        self.assertEqual(covered, set(spec.OPS),
                         f"вне таблицы: {sorted(set(spec.OPS) - covered)}; "
                         f"лишние: {sorted(covered - set(spec.OPS))}")

    def test_having_a_category_and_having_a_body_are_independent(self) -> None:
        """ПРОВЕРКА, КОТОРАЯ НЕ МОГЛА УПАСТЬ, ЗАМЕНЕНА НА ТУ, ЧТО МОЖЕТ
        (11.08.2026, и находка чужая — её принёс лид красным тестом).

        Здесь стояло `assertEqual(answered & set(CB.OP_NO_BODY), set())`, где
        `answered` бралось из `body_making_ops()`, а `body_making_ops()` ЕСТЬ
        `OPS − OP_NO_BODY`. Пересечение пусто ПО ПОСТРОЕНИЮ: утверждение не
        могло упасть ни при каком состоянии кода. Я заменил мёртвую проверку
        на непадающую в том же коммите, чьё сообщение — про сторожей, которые
        не могли исполниться. Проверка, которая не может упасть, ХУЖЕ
        отсутствующей: она числится в наборе.

        НЕПУСТОЙ ОТВЕТ, снятый по ВСЕМУ реестру, а не по заранее отфильтрованному
        множеству: `create_face_wall`. Стена по грани массы ЕСТЬ стена
        (`OST_Walls` — категория известна точно), и оболочки не имеет:
        `FaceWall` не `Wall` (CS0029 на всех шести) и `LocationCurve` не имеет
        вовсе. Две величины, и они независимы:

            `category_of`  -> куда результат попадёт в Revit
            `OP_NO_BODY`   -> можем ли мы построить оболочку

        Один из 69 — и потому единственный, на котором подмена одной величины
        другой становится видна. Его зеркало — `create_curtain_grid_line`:
        там категория ОБЪЯВЛЯЛАСЬ строкой `REGISTRY_GAPS` там, где таблица тел
        её отвергала. Одна и та же независимость с двух сторон.

        Список закрыт: новый оп, у которого нет тела и есть категория, обязан
        быть вписан сюда РЕШЕНИЕМ, а не приехать молча.
        """
        both = {name for name in spec.OPS
                if name in CB.OP_NO_BODY and CB.op_categories(name)}
        self.assertEqual(
            both, {"create_face_wall"},
            "изменился состав опов, у которых категория известна, а тела нет. "
            "Это не ошибка сама по себе — но это РЕШЕНИЕ: припишите причину в "
            "`OP_NO_BODY` и назовите оп здесь")
        self.assertEqual(CB.op_categories("create_face_wall"), ("OST_Walls",))
        self.assertIn("LocationCurve", CB.OP_NO_BODY["create_face_wall"])

    def test_every_category_named_here_exists_in_the_closed_hull_table(self) -> None:
        """Категория, которой нет в таблице пакета, ушла бы в
        `kind_outside_table` — то есть в тихий пропуск с красивым именем."""
        # ТРИ МЁРТВЫЕ ССЫЛКИ, А НЕ ОДНА (замер 11.08.2026). Кроме снятой
        # `OP_CATEGORY` этот тест читал `_column_category` и
        # `_directshape_category` — местные разрешатели, снятые ВМЕСТЕ с
        # таблицей: перечисление опа теперь разбирает сам реестр
        # (`spec.op_result_categories`), и `op_categories` перебирает его
        # целиком. Поэтому обе строки не заменены, а СНЯТЫ: их ответ входит
        # в первую строку по построению, и повторять его значило бы завести
        # третью копию того же отношения.
        named = {c for name in CB.body_making_ops()
                 for c in CB.op_categories(name)}
        self.assertLessEqual(
            {"OST_StructuralColumns", "OST_Columns", "OST_Furniture",
             "OST_GenericModel", "OST_SpecialityEquipment"}, named,
            "перечисление опа перестало разбираться — ответ реестра сузился")
        missing = sorted(c for c in named if c not in H.KIND_TABLE)
        self.assertEqual(missing, [], missing)

    def test_the_section_parameters_are_the_ones_the_emitter_writes(self) -> None:
        """Число кладётся под ИМЕНЕМ ПАРАМЕТРА, и о пригодности чтения судит
        закрытая таблица пакета, а не этот модуль. Значит имя обязано быть тем
        же, что пишет эмиттер, и обязано быть известно таблице."""
        for op_name, param in CB.SECTION_PARAM_BY_OP.items():
            self.assertIn(param, H.ALL_SECTION_PARAM_NAMES, op_name)
            categories = CB.op_categories(op_name)
            self.assertTrue(categories, op_name)
            for category in categories:
                self.assertIn(param, H.SECTION_RULES[category]["round"],
                              op_name)

    def test_the_bundle_address_is_the_same_one_the_verdict_uses(self) -> None:
        """Находка о коллизии и находка вердикта обязаны вести в ОДНУ строку
        скрипта: два разных адреса одной операции — это два раунда починки."""
        for position, oid in ((1, "wall3"), (7, "duct1")):
            self.assertEqual(CB.bundle_oid(position, oid),
                             DC._bundle_oid(position, oid))


# ═════════════════════════════════════════════════════════════════════════
# 2. ОТСУТСТВУЮЩЕЕ ОСТАЁТСЯ ОТСУТСТВУЮЩИМ
# ═════════════════════════════════════════════════════════════════════════

class AbsentStaysAbsent(_Door):

    def test_the_flag_is_off_by_default(self) -> None:
        self._set("KUKAI_IR_CLASH", None)
        self.assertFalse(CB.clash_enabled())
        self.assertIsNone(CB.bundle_clash_report([{"ops": []}]))

    def test_with_the_flag_off_the_receipt_is_the_one_from_before(self) -> None:
        """ДОКАЗАТЕЛЬСТВО НЕИЗМЕННОСТИ. Одно и то же здание, два прогона.
        Выключенный флаг не даёт ни одного нового ключа; включённый ДОПИСЫВАЕТ
        текст в хвост и не трогает ни байта перед ним."""
        self._set("KUKAI_IR_CLASH", None)
        off = self.build([ar_program(), ov_program(), vk_program()])["building"]
        self.assertNotIn("clash", off, sorted(off))

        J.reset()
        CB._CACHE.clear()
        self._set("KUKAI_IR_CLASH", "1")
        on = self.build([ar_program(), ov_program(), vk_program()])["building"]

        self.assertEqual(set(on) - set(off), {"clash"}, sorted(on))
        for field in sorted(off):
            # `receipt_chars` исключается ПО ТОЙ ЖЕ ПРИЧИНЕ, что и
            # `message_ru`: это его длина, функция от исключённого поля.
            # Сверять производную, исключив оригинал, — проверять то же
            # самое под другим именем. Поле едет при обоих положениях
            # флага с 13.08: прибор, отвечающий лишь в одной из двух
            # конфигураций, покрывает часть диапазона.
            if field in ("message_ru", "receipt_chars"):
                continue
            self.assertEqual(on[field], off[field], field)
        self.assertIn("receipt_chars", off,
                      "размер поля обязан называться и без клеша")
        self.assertEqual(off["receipt_chars"], len(off["message_ru"]))
        self.assertEqual(on["receipt_chars"], len(on["message_ru"]))
        self.assertGreater(on["receipt_chars"], off["receipt_chars"],
                           "находки дописаны, а число о размере не выросло")
        self.assertTrue(on["message_ru"].startswith(off["message_ru"]),
                        "текст вердикта сдвинулся, а не дописался")

    def test_a_broken_check_never_costs_the_turn(self) -> None:
        """Проверка, упавшая внутри, обязана СКАЗАТЬ об этом и не тронуть
        вердикт. Молчание читалось бы как «коллизий нет»."""
        self._set("KUKAI_IR_CLASH", "1")
        with mock.patch.object(CB, "_report", side_effect=RuntimeError("бум")):
            block = self.build([ar_program(), ov_program()])["building"]
        self.assertEqual(block["clash"]["status"], "unavailable")
        self.assertIn("не смотрели", block["clash"]["message_ru"])
        self.assertEqual(block["verdict"], "pass", block)


# ═════════════════════════════════════════════════════════════════════════
# 3. НАХОДКА ЕСТЬ, И ОНА — СВИДЕТЕЛЬСТВО
# ═════════════════════════════════════════════════════════════════════════

class TheFindingIsEvidence(_Door):

    def setUp(self) -> None:
        super().setUp()
        self._set("KUKAI_IR_CLASH", "1")

    def test_two_authors_crossing_in_one_building_are_found_by_name(self) -> None:
        """ГЛАВНОЕ УТВЕРЖДЕНИЕ. Пара элементов и ИЗМЕРЕННОЕ проникание — из
        разных программ, то есть из разных исполнителей."""
        block = self.build([ar_program(), ov_program()])["building"]
        clash = block["clash"]
        self.assertEqual(clash["status"], "ok", clash)
        pairs = {(row["a_element_id"], row["b_element_id"])
                 for row in clash["findings"]}
        self.assertIn(("p2/duct1", "p2/duct2"), pairs, clash["findings"])
        row = next(r for r in clash["findings"]
                   if (r["a_element_id"], r["b_element_id"])
                   == ("p2/duct1", "p2/duct2"))
        self.assertEqual(row["relation"], "overlap", row)
        self.assertAlmostEqual(row["penetration_mm"], 350.0, places=3)

    def test_the_same_element_declared_twice_reads_as_a_duplicate(self) -> None:
        """Многоагентный случай в чистом виде: второй исполнитель объявил тот
        же воздуховод. Пакет называет это отдельным РОДОМ — он чинится
        удалением, а не раздвиганием."""
        block = self.build([ar_program(), ov_program(), ov_program()])["building"]
        clash = block["clash"]
        self.assertGreaterEqual(clash["duplicates"], 1, clash)
        dup = next(r for r in clash["findings"]
                   if r["pair_kind"] == "coincident_duplicate")
        self.assertEqual({dup["a_element_id"], dup["b_element_id"]},
                         {"p2/duct1", "p3/duct1"}, dup)
        # ТЕКСТ ОБЯЗАН СОГЛАСОВАТЬСЯ СО СТУПЕНЬЮ, А НЕ ПОВТОРЯТЬ ПРЕЖНЮЮ
        # ФОРМУЛИРОВКУ (11.08.2026). Здесь стоял литерал «НА ОДНОМ МЕСТЕ» —
        # утверждение ФАКТА. Волна заменила его на «ВОЗМОЖНЫЙ ДУБЛИКАТ … НЕ
        # доказано: вердикт геометрии possible», и это верное предложение ДЛЯ
        # ВЕРДИКТА `possible`. Утверждается поэтому связка, а не строка.
        self.assertEqual(dup["rung"], "look", dup)
        self.assertIn("НЕ доказано", dup["text"])
        self.assertIn("ВОЗМОЖНЫЙ ДУБЛИКАТ", dup["text"])

    def test_a_clash_never_moves_the_verdict(self) -> None:
        """ЗАКОН. Здание с коллизией и здание без неё обязаны получить ОДИН И
        ТОТ ЖЕ вердикт: находка едет свидетельством, а не отказом. Ложный отказ
        верной постройке — класс `acceptance-broke-on-Cyrillic`."""
        dirty = self.build([ar_program(), ov_program()])["building"]
        J.reset()
        CB._CACHE.clear()
        clean = self.build([ar_program()])["building"]
        self.assertGreater(dirty["clash"]["total_findings"], 0)
        self.assertEqual(dirty["clash"]["status"], "ok")
        self.assertEqual((dirty["verdict"], dirty["blocking"]),
                         (clean["verdict"], clean["blocking"]))
        self.assertNotIn("clash", dirty["blocking"])

    def test_the_receipt_says_what_stayed_out_of_the_search(self) -> None:
        """НИЧЕГО МОЛЧА. Стены в поиске не участвуют — программа не выражает их
        толщину; это обязано быть НАЗВАНО числом и категорией, иначе «находок
        нет» читается как «коллизий нет»."""
        clash = self.build([ar_program(), ov_program()])["building"]["clash"]
        self.assertFalse(clash["search_complete"], clash)
        self.assertEqual(clash["without_body_by_category"].get("OST_Walls"), 5,
                         clash["without_body_by_category"])
        text = clash["message_ru"]
        self.assertIn("БЕЗ ТЕЛА", text)
        self.assertIn("ПО ПОСТРОЕНИЮ", text)

    def test_a_nominal_diameter_does_not_become_a_body(self) -> None:
        """R3 красных, привезённое в компилятор. `create_pipe.diameter_mm`
        эмитируется в `RBS_PIPE_DIAMETER_PARAM` — это НОМИНАЛ, и капсула по
        нему тела не содержит (ДУ100: 50.0 против наружного 57.15). Труба
        поэтому остаётся без оболочки, и это сказано словами.

        Тест держит границу в обе стороны: он упадёт и если номинал начнут
        молча использовать, и если о нём перестанут говорить.

        ПИНИТСЯ УТВЕРЖДЕНИЕ, А НЕ ФОРМУЛИРОВКА (исправлено 13.08.2026).
        Стояло `assertIn("НОМИНАЛЬНЫЙ ДИАМЕТР", ...)`, и текст, сказавший
        ТО ЖЕ САМОЕ другими словами («ТОЛЬКО НОМИНАЛ: 1 — капсула по
        номиналу тела не содержит»), красил тест. Факт не двигался: и
        прежняя пара чисел (50.0 против 57.15), и нынешняя (100 против
        114.3) — про одну трубу, первая радиусы, вторая диаметры; в
        `extract.py` они стоят рядом и согласованы. Расходилось СЛОВО.

        РАЗДЕЛЕНО НА ДВЕ ПОЛОВИНЫ, И ОНИ РАЗНОЙ ПРОЧНОСТИ — сказано прямо,
        потому что одинаково выглядящие `assert` внушают одинаковое доверие.

        «Номинал начали молча использовать» пинится СТРУКТУРНО и надёжно:
        начни капсула считаться телом — труба перестала бы числиться среди
        `without_body_by_category`, и счётчик упал бы в ноль.

        «О нём перестали говорить» пинится ПО ТЕКСТУ, и лучшего здесь нет:
        числа `nominal_only_total`, которое эта строка печатает, В КВИТАНЦИИ
        НЕТ — `census` в блок не попадает вовсе, `type_sections` несёт лишь
        `"read"`. То есть величина существует прозой и только прозой, и
        спросить, кроме прозы, нечего. Пин поэтому взят по КОРНЮ «НОМИНАЛ»
        плюс требование, чтобы в той же строке стояло положительное число:
        это ловит исчезновение утверждения и переживает редактуру слов, но
        остаётся пином по виду, и называть его структурным нельзя.

        ЧТО ОТСЮДА СЛЕДУЕТ ДЛЯ ВЛАДЕЛЬЦА `clash_bundle`: число, живущее
        только в предложении, не читается ничем, кроме глаза. Вывести
        `nominal_only_total` в блок — и второй половине этого теста станет
        что спросить."""
        clash = self.build([ar_program(), vk_program()])["building"]["clash"]
        self.assertEqual(clash["without_body_by_category"].get("OST_PipeCurves"),
                         1, clash["without_body_by_category"])
        self.assertRegex(
            clash["message_ru"], r"НОМИНАЛ\w*[^\n]*?[1-9]\d*",
            "об оболочке по номиналу перестали говорить числом")

    def test_a_building_without_a_single_body_says_so(self) -> None:
        """ВАКУУМ ОБЯЗАН БЫТЬ НАЗВАН. Здание из одних стен не даёт ни одной
        оболочки — и «находок 0» здесь значит «не искали»."""
        clash = self.build([ar_program()])["building"]["clash"]
        self.assertEqual(clash["bodies"], 0, clash)
        self.assertEqual(clash["total_findings"], 0)
        self.assertIn("НИ ОДНОГО ТЕЛА", clash["message_ru"])


# ═════════════════════════════════════════════════════════════════════════
# 3b. НАХОДКА СТАЛА СУЖДЕНИЕМ — ЦЕЛИКОМ ЧЕРЕЗ ПРОД-ДВЕРЬ
#
# Замер, породивший этот раздел (09.08, `snowdon_plumb_v5`): 99 пар, 66 из них
# на верхней ступени, и все 66 — плиты одного этажа, спорящие ТОЛЬКО в нашем
# собственном огрублении. Пары как результат проверки читатель выбрасывает.
# ═════════════════════════════════════════════════════════════════════════

class ThePairBecameAJudgement(_Door):

    def setUp(self) -> None:
        super().setUp()
        self._set("KUKAI_IR_CLASH", "1")

    def test_two_crossing_ducts_are_a_collision_with_a_move_to_make(self) -> None:
        """ЧТО с ЧЕМ, НА СКОЛЬКО, НАСКОЛЬКО УВЕРЕНЫ и ЧТО ДЕЛАТЬ — в одной
        строке, и ход выведен из ПРОГРАММЫ, а не придуман."""
        clash = self.build([ar_program(), ov_program()])["building"]["clash"]
        row = next(r for r in clash["findings"]
                   if (r["a_element_id"], r["b_element_id"])
                   == ("p2/duct1", "p2/duct2"))
        self.assertEqual(row["kind"], "collision")
        self.assertEqual(row["rule_id"], "run_meets_run")
        # СТУПЕНЬ СЛЕДУЕТ ЗА ВЕРДИКТОМ, И ПРОВЕРЯЕТСЯ ИМЕННО ЭТО (11.08.2026).
        # Здесь стояли литералы `rung == "fix"` и `proven is True`. Волна
        # 11.08 привязала ступень к вердикту, литералы стали красными, и
        # соблазн был вернуть строку. Замер говорит обратное: вердикт этой
        # пары — `possible`, значит `fix` был ступенью, НЕ СЛЕДОВАВШЕЙ за
        # вердиктом, и красным стало утверждение, а не поведение.
        self._assert_rung_follows_verdict(row)
        self._assert_next_move_follows_rung(row)
        self.assertTrue(row["why"], row)
        self.assertIn("СТОЛКНОВЕНИЕ", row["text"])

    #: Единственное отображение, которое здесь утверждается. Строки ступеней и
    #: тексты находок могут меняться; расхождение ступени с доказательностью —
    #: нет. Занижать поддержанное утверждение — такой же дефект, как завышать:
    #: прибор, кричащий на всё, учит себя игнорировать.
    _RUNG_FOR_PROVEN = {True: ("fix", "agree"), False: ("look",),
                        None: ("look", "nothing", "note")}

    def _assert_next_move_follows_rung(self, row: dict) -> None:
        """ХОД ТОЖЕ СЛЕДУЕТ ЗА СТУПЕНЬЮ, и это не послабление.

        Здесь стояло `assertIn("create_duct p2/duct1", next_move)` — то есть
        требование НАЗВАТЬ ОПЕРАЦИЮ К СДВИГУ. На ступени `look` такой ход
        запрещён самим определением ступени («разрушающее указание по такой
        находке ЗАПРЕЩЕНО»), и выдавать его значило бы советовать правку по
        находке, которую наше же огрубление могло создать.

        Исходный замысел теста — «ход ВЫВЕДЕН из программы, а не придуман» —
        сохраняется целиком: на `look` выведенный ход это «добыть недостающее
        свидетельство», и он обязан назвать, ЧЕГО не хватает.
        """
        move = row["next_move"]
        self.assertTrue(move, row)
        if row["rung"] == "fix":
            self.assertIn(row["a_element_id"], move, row)
        else:
            self.assertIn("inner-evidence", move, row)
            self.assertIn("нельзя", move, row)

    def _assert_rung_follows_verdict(self, row: dict) -> None:
        allowed = self._RUNG_FOR_PROVEN[row["proven"]]
        self.assertIn(
            row["rung"], allowed,
            f"ступень {row['rung']!r} не следует за доказательностью "
            f"{row['proven']!r}: {row.get('text')}")

    def test_the_top_rung_is_unreachable_in_production_and_says_so(self) -> None:
        """ПОЧЕМУ КАЖДАЯ НАХОДКА — «СМОТРЕТЬ», И ЭТО НЕ НАСТРОЙКА
        ОСТОРОЖНОСТИ (замер 11.08.2026).

        `_rung` отдаёт `fix` только при `proven is True`, а
        `_physical_overlap_proof` возвращает `True` только при связке
        `verdict == "confirmed"` + сертифицированное внутреннее перекрытие.
        `detect.VERDICT_REQUIREMENTS` говорит про это своими словами:
        «production builders do not mint inner certificates yet». То есть на
        ЛЮБОМ производственном снимке верхняя ступень недостижима ПО
        ПОСТРОЕНИЮ, и две пересекающиеся трубы — коллизия по любому прочтению
        — выходят как `look`.

        ЭТО ДЕФЕКТ ВЫШЕ ПО ТЕЧЕНИЮ, А НЕ ФОРМУЛИРОВКА. Детектор НЕДОобъявляет
        там, где мог бы решить точно, потому что ни один производственный
        источник оболочки не несёт внутреннего сертификата. Тест держит факт
        на виду: пока `VERDICT_REQUIREMENTS` называет `confirmed`
        недостижимым, «всё на ступени СМОТРЕТЬ» — следствие этого, а не выбор
        осторожности, и чинить надо сертификаты, а не тексты.

        ЧЕГО ОН НЕ ПОКРЫВАЕТ: он ничего не говорит о том, ПРАВИЛЬНО ли
        отображение `proven -> ступень`. Он утверждает лишь, что верхняя
        ступень сегодня недостижима и что причина названа в коде.
        """
        from kukai.clash import detect as _detect
        self.assertIn("confirmed", _detect.VERDICT_REQUIREMENTS)
        self.assertIn("do not mint inner certificates",
                      _detect.VERDICT_REQUIREMENTS["confirmed"])

    def test_the_receipt_counts_disputes_filtered_and_unseen_apart(self) -> None:
        """ТРИ РАЗНЫХ ФАКТА И ТРИ РАЗНЫХ ЧИСЛА. Пара, снятая правилом, пара,
        которую не видели вовсе, и спор — сложить их в одно «находок N» значит
        соврать дважды."""
        clash = self.build([ar_program(), ov_program()])["building"]["clash"]
        for key in ("disputes", "filtered", "unjudged", "without_body"):
            self.assertIn(key, clash, sorted(clash))
        self.assertEqual(
            clash["disputes"] + clash["filtered"] + clash["unjudged"],
            clash["total_findings"], clash)
        self.assertGreater(clash["without_body"], 0, clash)
        text = clash["message_ru"]
        self.assertIn("СПОРОВ", text)
        self.assertIn("НЕ ВИДЕЛИ", text)

    def test_a_refused_rule_names_itself_and_its_reason_in_the_receipt(self) -> None:
        """НИЧЕГО МОЛЧА, И ОСОБЕННО ПРО ОТКАЗ. Два воздуховода вплотную — пара,
        которую этот слой судить ОТКАЗЫВАЕТСЯ: нормируемый зазор между сетями
        программой не выражен. Отказ обязан назваться числом и обоснованием."""
        clash = self.build([ar_program(),
                            touching_ducts_program()])["building"]["clash"]
        self.assertEqual(clash["refused_by_rule"],
                         {"run_meets_run_clearance": 1}, clash)
        self.assertIn("run_meets_run_clearance", clash["rules"])
        text = clash["message_ru"]
        self.assertIn("ПРАВИЛО ОТКАЗАНО", text)
        self.assertIn("зазор", text)

    def test_a_hundred_disputes_still_fit_and_each_names_its_move(self) -> None:
        """Решётка из 24 воздуховодов: 144 пары, и все они — настоящие споры.
        Слой суждения НЕ обязан ничего снимать, когда снимать нечего."""
        clash = self.build([ar_program()] + grid_programs())["building"]["clash"]
        self.assertEqual(clash["disputes"], clash["total_findings"])
        self.assertEqual(clash["by_kind"], {"collision": 144}, clash["by_kind"])
        # СВОДКА СЛЕДУЕТ ЗА ВЕРДИКТАМИ, а не за ожидаемым числом: на
        # производственном снимке внутренних сертификатов не выдаёт никто,
        # поэтому `proven` не бывает True и верхняя ступень недостижима.
        self.assertEqual(set(clash["by_rung"]), {"look"}, clash["by_rung"])
        self.assertEqual(sum(clash["by_rung"].values()), 144)
        for row in clash["findings"]:
            self._assert_next_move_follows_rung(row)
        self.assertLessEqual(len(clash["message_ru"]), CB._TEXT_CAP)

    def test_the_text_cap_cuts_the_middle_and_never_the_completeness(self) -> None:
        """ПОТОЛОК РЕЖЕТ СЕРЕДИНУ. До этой волны обрезание шло ПО ХВОСТУ, и
        первой под нож уходила перепись «БЕЗ ТЕЛА» — то, чего в квитанции не
        имеет права не быть. Потолок здесь зажат нарочно: сама величина —
        решение о бюджете, а закон обрезания от неё не зависит."""
        with mock.patch.object(CB, "_TEXT_CAP", 900):
            clash = self.build([ar_program()]
                               + grid_programs())["building"]["clash"]
        text = clash["message_ru"]
        self.assertTrue(text.startswith("КОЛЛИЗИИ"), text)
        self.assertIn("БЕЗ ТЕЛА", text)
        self.assertIn("ПО ПОСТРОЕНИЮ", text)
        self.assertIn("область `", text)
        self.assertIn("обрезан", text)
        # Первое суждение вместе со своим ходом проходит ВСЕГДА: «СПОРОВ N» без
        # единой показанной строки — отчёт, который читатель выбросит, а
        # выброшенный отчёт хуже отсутствующего.
        self.assertIn("[СМОТРЕТЬ]", text)
        self.assertIn("ХОД:", text)


# ═════════════════════════════════════════════════════════════════════════
# 4. ПОТОЛКИ НАЗЫВАЮТСЯ ЧИСЛОМ, А НЕ РОНЯЮТ ПРОВЕРКУ МОЛЧА
# ═════════════════════════════════════════════════════════════════════════

def _dense_ducts(count: int, span: float = 60_000.0) -> list[dict]:
    """Решётка: каждый второй воздуховод поперёк — КАЖДАЯ пара пересекается.
    Худший случай узкой фазы, и он обязан упираться в потолок, а не в час."""
    ops = []
    for k in range(1, count + 1):
        t = k * span / count
        if k % 2:
            p0, p1 = [0.0, t, 2700.0], [span, t, 2700.0]
        else:
            p0, p1 = [t, 0.0, 2700.0], [t, span, 2700.0]
        ops.append({"op": "create_duct", "id": f"d{k}", "p0_mm": p0,
                    "p1_mm": p1, "level": _L1_BY_NAME, "diameter_mm": 400})
    return [{"ops": ops}]


class TheCapsAreNamed(unittest.TestCase):

    def setUp(self) -> None:
        self._prev = os.environ.get("KUKAI_IR_CLASH")
        os.environ["KUKAI_IR_CLASH"] = "1"
        CB._CACHE.clear()

    def tearDown(self) -> None:
        if self._prev is None:
            os.environ.pop("KUKAI_IR_CLASH", None)
        else:
            os.environ["KUKAI_IR_CLASH"] = self._prev
        for name in ("KUKAI_IR_CLASH_MAX_PAIRS", "KUKAI_IR_CLASH_MAX_OFFERS",
                     "KUKAI_IR_CLASH_MAX_BODIES"):
            os.environ.pop(name, None)
        CB._CACHE.clear()

    def test_a_dense_building_refuses_by_number_instead_of_running_for_ever(self) -> None:
        """320 воздуховодов, каждый с каждым — 25 918 пар и восемь секунд узкой
        фазы (замер 09.08). Проверка обязана ОТКАЗАТЬ, назвав число, а не
        отдать «находок 0» и не подвесить ход."""
        block = CB.bundle_clash_report(_dense_ducts(320))
        self.assertEqual(block["status"], "over_cap", block)
        self.assertGreater(block["work"], block["cap"])
        self.assertIn("не смотрели", block["message_ru"])
        self.assertNotIn("находок 0", block["message_ru"])

    def test_both_caps_can_fire_and_each_names_its_own_phase(self) -> None:
        """Два потолка меряют две РАЗНЫЕ цены (широкая фаза — мкс на оффер,
        узкая — доли мс на кандидата). Один потолок на оба вопроса выбирал бы
        между ложным отказом и часом работы."""
        os.environ["KUKAI_IR_CLASH_MAX_OFFERS"] = "1000"
        CB._CACHE.clear()
        broad = CB.bundle_clash_report(_dense_ducts(120))
        self.assertEqual((broad["status"], broad["phase"]),
                         ("over_cap", "широкая фаза"), broad)

        os.environ["KUKAI_IR_CLASH_MAX_OFFERS"] = "10000000"
        os.environ["KUKAI_IR_CLASH_MAX_PAIRS"] = "64"
        CB._CACHE.clear()
        narrow = CB.bundle_clash_report(_dense_ducts(120))
        self.assertEqual((narrow["status"], narrow["phase"]),
                         ("over_cap", "узкая фаза"), narrow)

    def test_the_body_cap_is_named_too(self) -> None:
        os.environ["KUKAI_IR_CLASH_MAX_BODIES"] = "16"
        CB._CACHE.clear()
        block = CB.bundle_clash_report(_dense_ducts(64))
        self.assertEqual(block["status"], "over_cap", block)
        self.assertIn("не смотрели", block["message_ru"])

    def test_a_sparse_building_at_the_judges_own_cap_still_runs(self) -> None:
        """Обратная сторона: потолок, отказывающий ИСПРАВНОМУ зданию, — это
        ложный отказ. 1 200 операций (потолок самого судьи), правдоподобная
        раскладка по этажам — обязано считаться."""
        ops = []
        for k in range(1, 1_201):
            floor = k % 8
            row = (k // 8) % 12
            x0 = 1_000.0 + ((k // 96) % 5) * 9_000.0
            y = 1_000.0 + row * 2_500.0
            z = 2_700.0 + floor * 3_200.0
            ops.append({"op": "create_duct", "id": f"d{k}",
                        "p0_mm": [x0, y, z], "p1_mm": [x0 + 8_000.0, y, z],
                        "level": {"by": "name", "value": f"Этаж {floor}"},
                        "diameter_mm": 400})
        pack = [{"ops": ops[i:i + 20]} for i in range(0, len(ops), 20)]
        block = CB.bundle_clash_report(pack)
        self.assertEqual(block["status"], "ok", block)
        self.assertEqual(block["bodies"], 1_200)

    def test_the_same_bundle_twice_is_paid_for_once(self) -> None:
        """Кэш на КАНОНИЧЕСКИХ БАЙТАХ пачки — тот же приём, что у подъёма
        схемы. Замер: 116 мс холодным, 0.3 мс тёплым."""
        pack = _dense_ducts(40)
        CB._CACHE.clear()
        first = time.perf_counter()
        cold = CB.bundle_clash_report(pack)
        first = time.perf_counter() - first
        second = time.perf_counter()
        warm = CB.bundle_clash_report(pack)
        second = time.perf_counter() - second
        self.assertEqual(cold["total_findings"], warm["total_findings"])
        self.assertLess(second, first)


# ═════════════════════════════════════════════════════════════════════════
# 5. ДОСТИЖИМОСТЬ — ПРИБОРОМ, А НЕ GREP'ОМ
# ═════════════════════════════════════════════════════════════════════════

class TheDetectorIsReachable(unittest.TestCase):

    def test_the_clash_package_is_live_from_a_real_entry_point(self) -> None:
        """До этой волны `graph.live()` не содержал НИ ОДНОГО модуля
        `kukai.clash.*`: пакет был достижим только руками, через CLI."""
        sys.path.insert(0, str(BACKEND / "tests"))
        try:
            import capability_graph  # noqa: WPS433

            graph = capability_graph.Graph(BACKEND)
        finally:
            if sys.path and sys.path[0] == str(BACKEND / "tests"):
                sys.path.pop(0)
        live = graph.live()
        for module in ("kukai.clash.detect", "kukai.clash.hulls",
                       "kukai.clash.geom", "kukai.clash.snapshot",
                       "kukai.clash.review"):
            self.assertIn(module, live, sorted(
                m for m in live if m.startswith("kukai.clash")))

    def test_the_gate_is_wired_and_not_on_the_shelf(self) -> None:
        """Флаг, который прибор докладывает «на складе», тёмен ПО ПОСТРОЕНИЮ:
        включать его бессмысленно. Проверяется ТОТ ЖЕ прибор, которым это
        меряет оператор, а не собственный обход."""
        sys.path.insert(0, str(BACKEND / "tools"))
        try:
            import capability_map  # noqa: WPS433

            gates = {row["flag"]: row for row in capability_map._gates()}
        finally:
            if sys.path and sys.path[0] == str(BACKEND / "tools"):
                sys.path.pop(0)
        row = gates.get("KUKAI_IR_CLASH")
        self.assertIsNotNone(row, sorted(gates))
        self.assertEqual(row["gate_fn"], ["clash_enabled"], row)
        self.assertTrue(row["wired_into"], "флаг на складе: никто не вызывает")
        self.assertTrue(any("[маршрут]" in chain for chain in row["wired_into"]),
                        row["wired_into"])


if __name__ == "__main__":
    unittest.main()
