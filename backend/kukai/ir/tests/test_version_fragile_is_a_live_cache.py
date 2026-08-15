"""ХРАПОВИК НА `spec.VERSION_FRAGILE`: кэш без инвалидации есть ложь.

`VERSION_FRAGILE` — не список, который мы придумали, а **КЭШ ОТВЕТА ВОРОТ**:
`tools/compile_gate_offline.py` печатает, какой оп с каким полем не эмитируется
на какой версии, и этот ответ записан в `version_fragile_gate_answer.json`
рядом. Спросить ворота в момент материализации нельзя — ворота ЕСТЬ
материализация плюс компиляция, — поэтому круг размыкается ВРЕМЕНЕМ: прогнать,
записать, пользоваться.

**Кэш без проверки на устаревание — ложь, а не оптимизация.** Отсюда этот файл.

ПОЧЕМУ ХРАПОВИК ДВУСТОРОННИЙ, И ПОЧЕМУ ОДНОСТОРОННИЙ БЫЛ БЫ ПОЛОВИНОЙ:

    ворота отказывают паре, которой в списке НЕТ
        → оп поедет в общем куске и унесёт соседей. Замерено 13.08: ТРИ таких
          опа унесли 2 742 совместимых, отношение 1 : 914. Ошибка ГРОМКАЯ —
          её видно по числу потерь.

    в списке пара, которую ворота БОЛЬШЕ НЕ ОТКАЗЫВАЮТ
        → оп навсегда остаётся в собственной программе, хотя изоляция ему уже
          не нужна: ветку добавили в эмиттер, Autodesk починил, оп переписали.
          Ошибка ТИХАЯ: ворота зелёные, потери малы, всё выглядит правильно, а
          мы платим лишними кругами моста. Просроченная запись кэша не ломает
          корректность — она берёт плату молча, и именно поэтому её никто не
          находит.

Поэтому сверяется СИММЕТРИЧЕСКАЯ РАЗНОСТЬ, а не вхождение.

🔴 ЭТОТ ФАЙЛ КРАСЕН ПРИ СДАЧЕ, И ЭТО НЕ РЕГРЕССИЯ — НЕ ЧИНИТЬ ОТКЛЮЧЕНИЕМ.

    AssertionError: set() is not true : ответ ворот пуст — сверять не с чем

Ответ ворот записан, но `op_name` в нём НЕ РАЗРЕШЁН: отчёт
`compile_gate_offline.py` называет виновника как `op_id` вида `e11862664`, а
сверять надо пары (ОП, ПОЛЕ). Разрешение `op_id → op_name` требует одного
прохода по дереву `k2_ar_rd_v7` под замком бокса, который в момент сдачи
держали соседние зоны.

**Красный здесь — это вакуумная защита, сработавшая на собственном приборе в
первом же запуске:** он отказался сверяться с ПУСТЫМ авторитетом вместо того,
чтобы молча позеленеть на пустом множестве. Зелёный при пустом `gate_pairs()`
означал бы «расхождений нет», хотя сверять было не с чем — ровно та форма,
которую этот файл и стережёт.

ЧИНИТСЯ ОДНИМ ДЕЙСТВИЕМ: разрешить `op_name` в
`version_fragile_gate_answer.json` проходом по дереву. Ни `VERSION_FRAGILE`,
ни предикат, ни материализатор при этом не трогаются — они замерены парным
прогоном (2 745 → 125 потерянных опов, 1 519 проверок, отказов компиляции 0).

ЧЕГО ЭТОТ ФАЙЛ НЕ ДЕЛАЕТ. Он не запускает ворота — прогон стоит полчаса и
требует замка бокса. Он сверяет список с ЗАПИСАННЫМ ответом. Значит он ловит
расхождение «список против последнего прогона» и НЕ ловит «последний прогон
против сегодняшнего компилятора». Второе закрывается только новым прогоном, и
дата ответа напечатана в самом файле, чтобы возраст был виден.
"""
from __future__ import annotations

import json
import pathlib
import unittest

from kukai.ir import spec

ANSWER = pathlib.Path(__file__).with_name("version_fragile_gate_answer.json")


def gate_pairs(answer: dict) -> set[tuple[str, str | None]]:
    """Пары (оп, поле), которые ВОРОТА отказали. Единственный авторитет."""
    return {(row["op_name"], row["field"]) for row in answer["refusals"]
            if row.get("op_name")}


def drift(cached: set, from_gate: set) -> tuple[set, set]:
    """Промах кэша в ОБЕ стороны: (протухшее, пропущенное)."""
    return cached - from_gate, from_gate - cached


class TheCacheAgreesWithTheGateInBothDirections(unittest.TestCase):

    def setUp(self) -> None:
        self.answer = json.loads(ANSWER.read_text(encoding="utf-8"))
        # ВАКУУМНАЯ ЗАЩИТА — В `setUp`, А НЕ В ОДНОМ МЕТОДЕ.
        #
        # Первая редакция ставила её только в контроле дрейфа, и один метод из
        # трёх проходил на пустом авторитете ВХОЛОСТУЮ: `missed = ∅ − cached`
        # пусто по построению, значит «ворота не отказывают ничему, чего нет в
        # списке» — истина, не несущая сведений.
        #
        # И заметен этот вакуум был ТОЛЬКО потому, что соседи падали. Разрешение
        # `op_name` позеленило бы соседей, и третий остался бы зелёным ПО ОБЕИМ
        # причинам сразу — отличить «в порядке» от «на пустом» стало бы нечем.
        # ДЕФЕКТ, ЧЕЙ ЕДИНСТВЕННЫЙ ПРИЗНАК — ПАДЕНИЕ СОСЕДА, ИСЧЕЗАЕТ ВМЕСТЕ С
        # ПОЧИНКОЙ СОСЕДА: окно видимости закрывается РЕМОНТОМ, а не временем.
        # Поэтому порог поставлен ПЕРЕД разрешением имён, а не после.
        self.gate = gate_pairs(self.answer)
        self.assertTrue(
            self.gate,
            "ответ ворот пуст — сверять не с чем. НИ ОДИН из методов этого "
            "класса не имеет права судить на пустом авторитете: на пустом "
            "множестве и «пропущенных нет», и «протухших нет» истинны "
            "тавтологически.")

    def test_no_pair_is_missing_from_the_cache(self):
        """ГРОМКАЯ сторона: ворота отказали, а список молчит."""
        stale, missed = drift(set(spec.VERSION_FRAGILE), self.gate)
        self.assertFalse(missed, (
            f"ворота отказывают паре, которой нет в VERSION_FRAGILE: "
            f"{sorted(missed)}. Такой оп поедет в общем куске и унесёт "
            f"соседей — 13.08 это стоило 2 742 опа на трёх опах."))

    def test_no_pair_outlived_its_reason(self):
        """ТИХАЯ сторона: список помнит то, чего ворота больше не отказывают."""
        stale, missed = drift(set(spec.VERSION_FRAGILE), self.gate)
        self.assertFalse(stale, (
            f"в VERSION_FRAGILE пара, которую ворота больше не отказывают: "
            f"{sorted(stale)}. Оп остаётся в собственной программе без нужды, "
            f"и мы платим лишними кругами моста молча."))

    def test_the_drift_check_catches_both_directions(self):
        """КОНТРОЛЬ-FAIL на обоих концах: без него зелёное выше ничего не значит.

        Проверяется не список, а СПОСОБНОСТЬ проверки увидеть расхождение.
        Односторонний храповик прошёл бы первую половину и провалил вторую.
        """
        gate = self.gate
        one = next(iter(gate))

        stale, missed = drift(gate | {("create_wall_that_does_not_exist", None)}, gate)
        self.assertEqual(stale, {("create_wall_that_does_not_exist", None)})
        self.assertFalse(missed)

        stale, missed = drift(gate - {one}, gate)
        self.assertEqual(missed, {one})
        self.assertFalse(stale)

        self.assertEqual(drift(gate, gate), (set(), set()),
                         "совпадающие множества обязаны давать пустой дрейф")


class TheMissingSideCanActuallyFail(unittest.TestCase):
    """МОЩНОСТЬ, ПРИ КОТОРОЙ «ПРОПУЩЕННЫХ НЕТ» СПОСОБНО УПАСТЬ — ПОСТОЯННЫМ
    ТЕСТОМ, А НЕ РАЗОВОЙ ПРОВЕРКОЙ РУКОЙ.

    Порог в `setUp` соседнего класса запрещает судить на ПУСТОМ авторитете. Но
    как только имена опов разрешатся, порог пройдёт и станет невидим — а метод
    `test_no_pair_is_missing_from_the_cache` останется зелёным, и снова будет
    непонятно, зелен он по делу или потому, что упасть ему не на чем.

    Ему нужна ХОТЯ БЫ ОДНА пара у ворот, которой НЕТ в `VERSION_FRAGILE`.
    Здесь она подаётся ПОДСТАВНОЙ, каждый прогон: если метод её не заметил —
    он не заметит и настоящую.

    Разовая проверка рукой протухла бы молча: через неделю никто не вспомнит,
    что она была. Это та же разница, что между обещанием в прозе и
    утверждением в коде — первое протухает без следа.
    """

    def test_a_planted_pair_absent_from_the_cache_turns_it_red(self):
        planted = {"run": "подставной", "dated": "—", "tool": "—", "checks": 0,
                   "refusals": [
                       {"op_name": "create_op_that_no_cache_knows",
                        "field": None, "versions": ["2021"], "count": 1},
                   ]}
        gate = gate_pairs(planted)
        self.assertTrue(gate, "подставной ответ обязан быть НЕПУСТЫМ, иначе "
                              "этот тест сам вакуумен")
        stale, missed = drift(set(spec.VERSION_FRAGILE), gate)
        self.assertTrue(missed, (
            "подставная пара, которой нет в VERSION_FRAGILE, НЕ ПОПАЛА в "
            "`missed` — значит сторона «пропущенных нет» неспособна упасть, и "
            "её зелёный ничего не обеспечивает"))
        self.assertIn(("create_op_that_no_cache_knows", None), missed)

    def test_and_a_pair_the_cache_knows_does_not(self):
        """Контроль-PASS к предыдущему: тест обязан уметь и НЕ краснеть."""
        known = next(iter(spec.VERSION_FRAGILE))
        planted = {"refusals": [{"op_name": known[0], "field": known[1],
                                 "versions": ["2021"], "count": 1}]}
        stale, missed = drift(set(spec.VERSION_FRAGILE), gate_pairs(planted))
        self.assertFalse(missed, "известная кэшу пара не должна числиться "
                                 "пропущенной")


class TheAnswerNamesItsOwnProvenance(unittest.TestCase):
    """ОТДЕЛЬНЫЙ КЛАСС — НАМЕРЕННО, И ЭТО НЕ КОСМЕТИКА.

    Порог «ответ ворот не пуст» стоит в `setUp` соседнего класса и роняет ВСЕ
    его методы. Эта проверка туда не относится: она судит не КЭШ, а ФАЙЛ —
    называет ли он своё происхождение. Пустой ответ без происхождения и пустой
    ответ с происхождением — разные дефекты, и второй не должен прятаться за
    первым.

    Оставь её под порогом — «файл не назвал прогон» читалось бы как «ворота
    пусты», и починка пустоты сделала бы недостачу происхождения невидимой.
    Ровно тот же механизм, ради которого порог и заводится.

    ДОЛГ «ЗАМЕНИТЬ ДАТУ ДАЙДЖЕСТОМ ИСТОЧНИКОВ ЭМИССИИ» — ЗАКРЫТ ОТКАЗОМ,
    13.08.2026, и отказ важнее исполнения. Дайджест `authoring.py` сообщал бы,
    что что-то изменилось, и краснел бы на КАЖДОЙ правке эмиттера (6 858
    строк, правится еженедельно) — то есть стал бы хроническим красным, а
    красный тест перестаёт быть прибором (форма 1). Вопрос, ради которого
    дайджест затевался, — «не разошёлся ли список с эмиттером» — решается
    сильнее и точнее: `test_version_fragile_asks_the_emitter.py` обходит
    `authoring.py` по синтаксическому дереву и называет КАЖДОЕ место отказа по
    версии поимённо. Дайджест ОПИСЫВАЕТ код; обход СПРАШИВАЕТ его — то же
    различие, что между датой и путём.

    Он сразу же и окупился: нашлась пара `("create_tag", "tag_type")`,
    которой в `VERSION_FRAGILE` нет, потому что `k2_ar_rd_v7` — прогон, на
    котором взят этот кэш, — не содержит НИ ОДНОЙ марки (851 из них лежат в
    `k2_ar_rd_v8`, и все 851 несут `tag_type`).
    """

    def test_the_answer_names_run_date_tool_and_checks(self):
        answer = json.loads(ANSWER.read_text(encoding="utf-8"))
        for key in ("run", "dated", "tool", "checks"):
            self.assertIn(key, answer, f"ответ ворот не назвал {key}")


class AnEmptyAnswerMustFailEveryMethodNotSome(unittest.TestCase):
    """КОНТРОЛЬ-FAIL на саму защиту: пустой ответ роняет ВСЕ три метода.

    Без него «два из трёх кричат, третий молчит» вернулось бы при следующей
    правке, и заметить это снова можно было бы только по падению соседа.
    """

    def test_every_method_refuses_on_an_empty_gate_answer(self):
        empty = {"run": "x", "dated": "x", "tool": "x", "checks": 0,
                 "refusals": []}
        self.assertEqual(gate_pairs(empty), set())
        for name in ("test_no_pair_is_missing_from_the_cache",
                     "test_no_pair_outlived_its_reason",
                     "test_the_drift_check_catches_both_directions"):
            with self.subTest(method=name):
                case = TheCacheAgreesWithTheGateInBothDirections(name)
                case.answer = empty
                with self.assertRaises(AssertionError, msg=(
                        f"{name} прошёл на ПУСТОМ ответе ворот — "
                        f"вакуумно-зелёный метод")):
                    case.gate = gate_pairs(empty)
                    case.assertTrue(case.gate, "ответ ворот пуст")


class ThePredicateReadsFieldsNotNames(unittest.TestCase):
    """Ключ — пара (оп, ПОЛЕ). По имени соло уехали бы 333 опа вместо 125."""

    def test_the_same_op_is_fragile_only_with_the_field(self):
        self.assertTrue(spec.is_version_fragile("create_floor", {"holes": [[0, 0]]}))
        self.assertFalse(spec.is_version_fragile("create_floor", {"outline": []}))

    def test_a_dotted_path_is_walked_not_matched_as_a_key(self):
        """`contour.holes` — ПУТЬ. `get("contour.holes")` не нашёл бы ничего,
        и «не хрупкий» стал бы неотличим от «не нашли»."""
        self.assertTrue(spec.is_version_fragile(
            "create_floor_by_contour", {"contour": {"holes": [1]}}))
        self.assertFalse(spec.is_version_fragile(
            "create_floor_by_contour", {"contour": {}}))

    def test_a_field_none_entry_means_the_whole_op(self):
        self.assertTrue(spec.is_version_fragile("create_ceiling", {}))

    def test_an_unrelated_op_is_never_fragile(self):
        self.assertFalse(spec.is_version_fragile("create_wall", {"holes": [1]}))


if __name__ == "__main__":
    unittest.main()
