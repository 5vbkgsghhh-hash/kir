"""Канал свидетелей доносит ИЗМЕРЕННУЮ ВЕЛИЧИНУ, а не только вердикт.

ЗАЧЕМ. Перепись канала 13.08.2026: эмиттеры кладут в квитанцию **264
различных ключа** (148 файлов эмиссии), а `record_witness` схлопывал весь
словарь ридбэка в одну из трёх строк-меток. Доезжали **3** ключа (`id`,
`deleted_id`, `refused`), и то лишь ФАКТОМ наличия — они выбирают метку.
Гибло **261 = 98.9%**.

Следствие, ради которого этот тест и написан: в корпусе из **1 331 строки**
числовых полей было **шесть**, и все шесть — бухгалтерия самой записи
(`duration_ms`, `source_op_count`, `ops_truncated`, …). **Измерений о
построенном — НОЛЬ.** Поэтому каждое наше «живой прогон ответит ЧИСЛОМ» не
могло сбыться: маршрута не существовало, и следующее живое окно вернуло бы
`{geometry_ok: true}` вместо чисел.

ПРОВЕРЯЕТСЯ ОФЛАЙН, ЖИВОЙ РЕВИТ НЕ НУЖЕН. `record_witness` — обычная
функция; чтобы узнать, доезжает ли величина, достаточно подать синтетический
ридбэк и прочитать строку с диска.

ВЕЛИЧИНА ВЫБРАНА С НУЛЁМ ВХОЖДЕНИЙ В ЖИВОМ КОРПУСЕ. `mullions_on_line`
замерен 13.08 по всему корпусу: 0 раз. Иначе PASS мог бы оказаться про
чужой ключ, уже проезжавший другим маршрутом.
"""

from __future__ import annotations

import json
import ast
import os
import pathlib
import tempfile
import unittest

from kukai.ir import witness_feed


#: СНИМОК `serving.py` СНИМАЕТСЯ НА ИМПОРТЕ, А НЕ В ТЕЛЕ ТЕСТА.
#:
#: Первая редакция пина проводки читала файл с диска В МОМЕНТ ТЕСТА — и была
#: единственным утверждением набора, чей исход зависел от того, что делают с
#: деревом ВО ВРЕМЯ прогона. На этой машине несколько сессий правят соседние
#: копии одновременно; 13.08.2026 автор этого файла сам изменил `serving.py`
#: под идущим набором и получил бы красный, не имеющий отношения к предмету.
#: **Красный по посторонней причине перестаёт быть прибором**, и следующий
#: читатель начнёт его пропускать.
#:
#: Снимок на импорте не защищает от правки МЕЖДУ сбором и прогоном длинного
#: набора — окно сжимается с двадцати минут до секунд. Это разница между
#: «бывает» и «случилось сегодня», и она названа, а не замолчана.
_SERVING_SRC = (
    pathlib.Path(witness_feed.__file__).parent / "serving.py"
).read_text(encoding="utf-8")


#: Ключ, которого в живом корпусе НЕТ (замер 13.08.2026: 0 вхождений).
#: Прибор для него построен 29.07 (`98b5f847`), у опа 13 живых строк
#: 29.07–04.08 — окно было, а поле не доехало ни разу.
PROBE_KEY = "mullions_on_line"
PROBE_VALUE = 7


class TheTransactionIsolationReachesTheRow(unittest.TestCase):
    """Изоляция ТРАНЗАКЦИИ РЕВИТА доезжает до строки — и не путается с песочницей.

    ЗАЧЕМ. Замер 13.08.2026 по живому корпусу: `isolation`, `per_op`,
    `atomic`, `subtransaction` встречаются в 1 331 строке **ровно 0 раз**, а
    `PlannedProgram` изоляции не несёт. Поэтому вопрос «сколько живых программ
    шло `per_op`, а сколько `atomic`» был неотвечаем ПО ПОСТРОЕНИЮ.

    Цена этого не любопытство: `tools/live_op_rates.py` считает корзину
    «сопутствующий» — чужое нарушение откатило транзакцию, — а **под `per_op`
    сопутствующего не бывает по построению**. Без поля корпус смешивает две
    популяции с разной семантикой корзины, и главный прибор по-оповых ставок
    интерпретируем только для `atomic`-строк, при том что какие из них
    `atomic` — неизвестно.

    ИМЯ. Не `isolation`: `serving._sandbox_receipt` читает `isolation` у
    результата ПЕСОЧНИЦЫ PYTHON. Омоним в одном дереве опаснее отсутствующего
    поля — отсутствующее молчит, омоним ОТВЕЧАЕТ.
    """

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self._path = os.path.join(self._dir.name, "feed.jsonl")
        self._prev = os.environ.get(witness_feed._ENV)
        os.environ[witness_feed._ENV] = self._path

    def tearDown(self) -> None:
        if self._prev is None:
            os.environ.pop(witness_feed._ENV, None)
        else:
            os.environ[witness_feed._ENV] = self._prev
        self._dir.cleanup()

    def _row(self, **kw) -> dict:
        witness_feed.record_witness(
            program={"ops": [{"op": "create_wall", "id": "W1"}]},
            family="write", revit_version="2023", ok=True,
            witness={"geometry_ok": True}, duration_ms=1.0, **kw)
        with open(self._path, encoding="utf-8") as handle:
            return json.loads(
                [ln for ln in handle.read().splitlines() if ln.strip()][-1])

    def test_per_op_reaches_the_row(self) -> None:
        """КОНТРОЛЬ-PASS на значении, которого в корпусе 0 раз."""
        self.assertEqual(self._row(txn_isolation="per_op")["txn_isolation"],
                         "per_op")

    def test_atomic_reaches_the_row_too(self) -> None:
        """Оба значения обязаны доезжать: прибор, различающий одно, не
        различает ничего — вторая популяция осталась бы неотличима от
        «не сказано»."""
        self.assertEqual(self._row(txn_isolation="atomic")["txn_isolation"],
                         "atomic")

    def test_an_unstated_isolation_is_absent_not_atomic(self) -> None:
        """КОНТРОЛЬ-FAIL: не назвали — поля НЕТ.

        Подстановка `"atomic"` по умолчанию задним числом утверждала бы про
        1 331 существующую строку то, чего никто не измерял, и стёрла бы
        разницу между «шло atomic» и «никто не записал».
        """
        row = self._row()
        self.assertNotIn("txn_isolation", row)

    def test_the_compiler_states_it_and_the_rebuild_states_per_op(self) -> None:
        """Значение берётся у КОМПИЛЯТОРА, а не выдумывается в serving.

        `compile_program` по умолчанию `atomic`; `compile_rebuild_chunk` —
        единственная дверь к `per_op` (её зовут `serving.py` :2317, :4257,
        :5121). Проверяется, что оба доносят свой выбор до `CompileOutput`.
        """
        from kukai.ir.compiler import CompileOutput
        self.assertEqual(CompileOutput(ok=True).txn_isolation, "atomic")
        import inspect
        from kukai.ir import compiler
        src = inspect.getsource(compiler.compile_rebuild_chunk)
        self.assertIn('isolation="per_op"', src)

    def test_the_live_shaped_green_row_carries_it(self) -> None:
        """Форма ЖИВОЙ зелёной строки записи — пинится здесь.

        `test_refusal_identity::GreenRowStaysByteIdentical` перечисляет десять
        имён, но его фикстура изоляции НЕ называет, поэтому тот список есть
        утверждение о законе «нет отказа — нет личности отказа», а не описание
        живой строки. Его дайджесты сняты сравнением с `c3e019f6` и
        перепинивать их нельзя — это уничтожило бы сам замер. Поэтому живая
        форма живёт отдельным пином, здесь.
        """
        row = self._row(txn_isolation="atomic",
                        outcome={"execution": "committed"},
                        result_payload={"W1": {"id": "1001"}})
        body = {k for k in row if k not in ("ts", "prev_checksum", "checksum")}
        self.assertIn("txn_isolation", body)
        self.assertFalse({k for k in body if k.startswith("diag_")},
                         "личность отказа не имеет права появиться на зелёной")

    def test_every_live_call_site_states_it(self) -> None:
        """ПРОВОДКА, а не только приёмник.

        Тесты выше доказывают, что `record_witness` поле ПРИНИМАЕТ. Они ничего
        не говорят о том, что живой путь его ПЕРЕДАЁТ, — а именно на этом
        разрыве весь канал и стоял тёмным. Поэтому проверяется САМ ВЫЗОВ:
        разбором, а не поиском строки, иначе совпадение шло бы по виду.

        Список площадок ПОЛОН ПО ПОСТРОЕНИЮ: он не перечислен здесь, а
        собирается обходом всех вызовов `record_witness` в `serving.py`.
        Площадка, добавленная завтра, попадёт под проверку сама.
        """
        sites = []
        for node in ast.walk(ast.parse(_SERVING_SRC)):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = (fn.attr if isinstance(fn, ast.Attribute)
                    else fn.id if isinstance(fn, ast.Name) else "")
            if name == "record_witness":
                sites.append({k.arg for k in node.keywords})
        self.assertGreaterEqual(len(sites), 2,
                                "площадок меньше двух — обход не нашёл вызовы, "
                                "и ноль был бы про матчер, а не про serving")
        for i, kwargs in enumerate(sites):
            self.assertIn("txn_isolation", kwargs,
                          f"площадка {i} не называет изоляцию — строка уйдёт "
                          f"без неё, и вопрос atomic/per_op снова станет "
                          f"неотвечаемым")

    def test_the_name_does_not_collide_with_the_sandbox_one(self) -> None:
        """Омоним не заведён: поле строки называется `txn_isolation`, а
        песочница остаётся при своём `isolation`."""
        row = self._row(txn_isolation="per_op")
        self.assertNotIn("isolation", row)
        self.assertIn("txn_isolation", row)


def _record(payload: dict, path: str, ops: list[str] | None = None) -> dict:
    """Записать одну строку и вернуть её разобранной.

    По умолчанию программа объявляет РОВНО те опы, что есть в квитанции, —
    иначе страж «факт только у известного опа» сделал бы половину проверок
    ниже зелёными по построению, а не по делу.
    """
    ids = list(payload) if ops is None else ops
    witness_feed.record_witness(
        program={"ops": [{"op": "create_curtain_grid_line", "id": i}
                         for i in ids]},
        family="test", revit_version="2023", ok=True,
        witness={"geometry_ok": True}, duration_ms=1.0,
        result_payload=payload,
    )
    with open(path, encoding="utf-8") as handle:
        lines = [ln for ln in handle.read().splitlines() if ln.strip()]
    return json.loads(lines[-1])


class ReadbackFactsReachTheRow(unittest.TestCase):

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self._path = os.path.join(self._dir.name, "feed.jsonl")
        self._prev = os.environ.get(witness_feed._ENV)
        os.environ[witness_feed._ENV] = self._path

    def tearDown(self) -> None:
        # Восстанавливаем НАБЛЮДЁННОЕ, а не запомненную константу: канон уже
        # платил за `finally`, чинивший глобальное состояние за весь процесс.
        if self._prev is None:
            os.environ.pop(witness_feed._ENV, None)
        else:
            os.environ[witness_feed._ENV] = self._prev
        self._dir.cleanup()

    # ── control-PASS ────────────────────────────────────────────────────
    def test_a_measured_count_reaches_the_stored_row(self) -> None:
        """КОНТРОЛЬ-PASS: семёрка, положенная в квитанцию, ЧИТАЕТСЯ с диска."""
        row = _record({"G1": {"id": "1", PROBE_KEY: PROBE_VALUE}}, self._path)
        self.assertIn("op_facts", row,
                      "поле фактов не появилось в строке вообще")
        self.assertEqual(row["op_facts"]["G1"][PROBE_KEY], PROBE_VALUE,
                         "величина не доехала до строки корпуса")

    # ── control-FAIL ────────────────────────────────────────────────────
    def test_without_the_wiring_the_seven_vanishes(self) -> None:
        """КОНТРОЛЬ-FAIL: снять проводку — семёрка обязана исчезнуть.

        Без этого конца «починка есть» неотличима от «поле и так пролезало».
        Проводка снимается ровно та, что добавлена 13.08: сборщик фактов.
        """
        original = witness_feed._readback_facts
        witness_feed._readback_facts = lambda row: None
        try:
            row = _record({"G1": {"id": "1", PROBE_KEY: PROBE_VALUE}},
                          self._path)
        finally:
            witness_feed._readback_facts = original
        self.assertNotIn("op_facts", row,
                         "семёрка доехала БЕЗ проводки — значит PASS выше "
                         "доказывал не эту правку")
        self.assertEqual(row["op_outcomes"]["G1"], "created",
                         "метка обязана уцелеть: её читает live_op_rates")

    # ── правило, а не список ────────────────────────────────────────────
    def test_the_container_stays_in_the_model_and_says_so(self) -> None:
        """Координаты не едут — но выброс СЧИТАЕТСЯ, а не молчит.

        `position_mm` массив (координата, авторитет — модель),
        `position_delta_mm` скаляр (РАСХОЖДЕНИЕ, измерение о построенном).
        Одна пара показывает обе половины правила разом.
        """
        row = _record({"G1": {"id": "1",
                              "position_mm": [1.0, 2.0, 3.0],
                              "position_delta_mm": 0.25}}, self._path)
        facts = row["op_facts"]["G1"]
        self.assertNotIn("position_mm", facts, "геометрия просочилась в леджер")
        self.assertEqual(facts["position_delta_mm"], 0.25)
        self.assertEqual(facts["__dropped"], {"geometry": 1},
                         "выброшенное обязано быть НАЗВАНО, а не промолчать")

    def test_a_verdict_stays_a_verdict_not_a_one(self) -> None:
        """bool наследует int — обратный порядок проверок записал бы
        `line_locked` как единицу и превратил вердикт в величину."""
        row = _record({"G1": {"id": "1", "line_locked": True}}, self._path)
        # `1 is True` ложно, поэтому `assertIs` различает вердикт и единицу
        # после обхода через JSON.
        self.assertIs(row["op_facts"]["G1"]["line_locked"], True)
        with open(self._path, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn('"line_locked":true', text)     # запись компактная
        self.assertNotIn('"line_locked":1', text)

    def test_an_over_long_string_is_dropped_whole_never_cut(self) -> None:
        """Обрезанная строка читается как полная и потому ЛЖЁТ.

        Канон уже платил за потолок, резавший одну половину поля, пока вторая
        дописывалась в него же. Поэтому длинное значение выбрасывается
        целиком и попадает в счётчик.
        """
        row = _record({"G1": {"id": "1",
                              "type_name": "я" * (witness_feed._MAX_FACT_TEXT
                                                  + 1)}}, self._path)
        facts = row["op_facts"]["G1"]
        self.assertNotIn("type_name", facts)
        self.assertEqual(facts["__dropped"], {"over_budget": 1})

    def test_the_budget_is_visible_when_it_bites(self) -> None:
        """Полей больше бюджета — урезание НАЗВАНО числом."""
        wide = {f"k{i}": i for i in range(witness_feed._MAX_FACTS_PER_OP + 5)}
        row = _record({"G1": wide}, self._path)
        facts = row["op_facts"]["G1"]
        kept = [k for k in facts if k != "__dropped"]
        self.assertEqual(len(kept), witness_feed._MAX_FACTS_PER_OP)
        self.assertEqual(facts["__dropped"]["over_count"],
                         len(wide) - witness_feed._MAX_FACTS_PER_OP)

    def test_nothing_measured_means_no_field_at_all(self) -> None:
        """Пустой словарь в строке неотличим от «фактов не было»."""
        row = _record({"G1": {"points_mm": [[0, 0, 0]]}}, self._path)
        self.assertEqual(row["op_facts"]["G1"], {"__dropped": {"geometry": 1}})
        row2 = _record({"G1": {}}, self._path)
        self.assertNotIn("op_facts", row2)

    def test_a_row_of_ids_alone_stays_exactly_as_it_was(self) -> None:
        """ОТСУТСТВУЮЩЕЕ ОСТАЁТСЯ ОТСУТСТВУЮЩИМ.

        Зелёная строка, чей ридбэк несёт одни `id`, обязана остаться той же:
        `id` уже доехал МЕТКОЙ. Первая редакция этой правки записывала его
        ещё и фактом — вторая правда об одном факте, — и ратчет
        `test_refusal_identity::GreenRowStaysByteIdentical` покраснел на трёх
        утверждениях сразу. Закон пинится и здесь, у места правки, чтобы
        следующая редакция не узнавала о нём из чужого файла.
        """
        row = _record({"W1": {"id": "1001"}, "D1": {"id": "1002"}},
                      self._path)
        self.assertNotIn("op_facts", row)
        self.assertEqual(row["op_outcomes"], {"W1": "created",
                                              "D1": "created"})

    def test_a_label_key_is_never_carried_twice(self) -> None:
        """Ключ-решатель метки не дублируется в факты — и не числится
        выброшенным: он не потерян, он в соседнем поле."""
        row = _record({"G1": {"id": "1", "deleted_id": "2",
                              "count": 5}}, self._path)
        facts = row["op_facts"]["G1"]
        self.assertEqual(facts, {"count": 5})
        self.assertNotIn("__dropped", facts)

    def test_a_program_level_key_never_becomes_an_op(self) -> None:
        """АВТОРИТЕТ ОПОВ — СПИСОК ОПОВ, А НЕ ФОРМА ЗНАЧЕНИЯ.

        Квитанция плоская: `ok`, `created_ids`, `postcondition_violations` и
        `results` лежат в ней рядом с построчными ридбэками. Сегодня словарное
        значение бывает только у ридбэка, и «взять все dict-значения» работает
        СЛУЧАЙНО. Один `summary: {...}`, добавленный завтра, завёл бы в фактах
        несуществующий оп — и его искали бы в реестре.
        """
        row = _record({"G1": {"id": "1", "count": 4},
                       "summary": {"total": 99}},
                      self._path, ops=["G1"])
        self.assertEqual(sorted(row["op_facts"]), ["G1"],
                         "программный ключ прочитан как оп")
        self.assertEqual(row["op_facts"]["G1"], {"count": 4})

    def test_the_guard_does_not_eat_ops_beyond_the_record_cap(self) -> None:
        """Страж берёт опы у ПРОГРАММЫ до усечения (`raw_ops`).

        Список записи урезается `_MAX_OPS_PER_RECORD`; если бы страж сверялся
        с урезанным, широкая программа теряла бы законные факты за потолком —
        дефект, неотличимый от «величина не доехала».
        """
        n = witness_feed._MAX_OPS_PER_RECORD
        last = f"op{n + 4}"
        payload = {f"op{i}": {"id": str(i), "count": i} for i in range(n + 5)}
        row = _record(payload, self._path)
        self.assertGreater(len(row["ops"]), 0)
        self.assertIn("ops_truncated", row,
                      "проверка вырождена: программа не переросла потолок")
        self.assertIn(last, {*payload},)
        self.assertNotIn(last, row["op_facts"],
                         "за потолком ЗАПИСИ фактов нет — но не из-за стража")
        self.assertEqual(row["op_facts"]["op0"], {"count": 0})

    def test_the_label_channel_is_untouched(self) -> None:
        """`op_outcomes` обязан остаться СТРОКАМИ: `live_op_rates.py:404`
        сравнивает значение с "refused", и смена типа сломала бы прибор
        четырёх корзин. Радиус правки — граф импорта, а не файл."""
        row = _record({"A": {"refused": "нет типа"},
                       "B": {"id": "5", "count": 3},
                       "C": {"warning": "хм"}}, self._path)
        self.assertEqual(row["op_outcomes"],
                         {"A": "refused", "B": "created", "C": "other"})
        for value in row["op_outcomes"].values():
            self.assertIsInstance(value, str)


if __name__ == "__main__":
    unittest.main()
