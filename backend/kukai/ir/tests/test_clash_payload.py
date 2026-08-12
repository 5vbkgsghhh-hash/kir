"""НАГРУЗКА ТОЖЕ СТОИТ КОНТЕКСТА, А НОРМИРОВАН БЫЛ ТОЛЬКО ТЕКСТ.

ЗАМЕР 11.08.2026 (`/tmp/wiring/m_payload.py`, живая пересборка через
`materialize.leaves_to_program`, сериализация без пробелов):

    snowdon_plumb_v4   БЛОК 9 931 симв.;  message_ru 2 586 (26%),
                       findings 5 586 (56%)
    sob62_r23_v5       БЛОК 4 405 симв.;  message_ru 1 362 (31%),
                       findings 1 120 (25%)

То есть тщательно нормированный текст в 2 700 символов ехал внутри
НЕНОРМИРОВАННОЙ нагрузки, которая больше него вдвое. Бюджет стерёг не ту
величину — тот же класс, что потолок, меряющий не свою ось.

ИЗ ЧЕГО СОСТОИТ `findings` (5 строк, snowdon):

    why          975  (195 на строку)   <- ОДНА строка на ПРАВИЛО
    text         865  (173 на строку)
    action_ru    815  (163 на строку)   <- ОДНА строка на СТУПЕНЬ
    next_move    605  (121 на строку)

`why` и `action_ru` — не содержимое находки, а КОНСТАНТЫ своего класса,
размноженные по строкам. Замер повторения: пять строк `why`, РАЗНЫХ среди них
ОДНА, повторено 772 символа из 975. При этом тот же текст уже лежит в блоке
ОДИН раз — в `rules` (213 симв.).

И это не новое правило, а НАРУШЕННОЕ СТАРОЕ: `clash_judgement.Judged.why_ru`
дословно объявляет его для текста — «обоснование одно на правило, а находок по
нему бывает восемьдесят: печатать его в каждой строке значит утопить в нём и
находки». Текст этому следовал; нагрузка — нет.

ЧТО ЗДЕСЬ НЕ ДЕЛАЕТСЯ. Не назначается потолок нагрузке. Сколько модель РЕАЛЬНО
платит за эти символы, никто не мерил, и назначить число вместо замера здесь
запрещено ровно так же, как было запрещено поднять `_TEXT_CAP`. Запирается
СТРУКТУРНЫЙ инвариант, которому число не нужно: ни одна строка находки не
повторяет то, что уже лежит в блоке таблицей.
"""
from __future__ import annotations

import json
import os
import unittest

from kukai.ir import clash_bundle as CB
from kukai.ir import clash_judgement as J


def _ducts(n, step=100.0):
    return [{"op": "create_duct", "id": f"d{i}", "diameter_mm": 400.0,
             "p0_mm": [i * step, 0.0, 0.0], "p1_mm": [i * step, 6000.0, 0.0]}
            for i in range(n)]


class _Flag:
    def __enter__(self):
        self._prev = os.environ.get("KUKAI_IR_CLASH")
        os.environ["KUKAI_IR_CLASH"] = "1"
        CB._CACHE.clear()
        return self

    def __exit__(self, *exc):
        if self._prev is None:
            os.environ.pop("KUKAI_IR_CLASH", None)
        else:
            os.environ["KUKAI_IR_CLASH"] = self._prev
        CB._CACHE.clear()
        return False


class NoRowRepeatsWhatTheBlockAlreadyCarries(unittest.TestCase):
    """СТРУКТУРНЫЙ ЗАМОК, КОТОРОМУ НЕ НУЖНО ЧИСЛО."""

    def _block(self):
        with _Flag():
            return CB._report([{"ops": _ducts(6)}])

    def test_the_justification_is_not_copied_into_every_row(self):
        block = self._block()
        rows = block["findings"]
        self.assertGreater(len(rows), 1, "нужно несколько находок одного рода")
        for row in rows:
            self.assertNotIn(row["why"], block["rules"].values(),
                             "обоснование скопировано в строку целиком")

    def test_the_row_points_at_where_the_text_lives(self):
        """МОЛЧАЛИВОЕ ИСЧЕЗНОВЕНИЕ ЗАПРЕЩЕНО. Поле остаётся на месте и ведёт
        читателя туда, где текст лежит один раз, — а не пропадает и не
        становится пустым."""
        block = self._block()
        for row in block["findings"]:
            self.assertTrue(row["why"], row)
            self.assertIn(row["rule_id"], row["why"])
            self.assertIn("rules", row["why"])

    def test_the_action_of_a_rung_is_a_table_not_a_copy(self):
        block = self._block()
        self.assertIn("rung_actions", block)
        for row in block["findings"]:
            self.assertIn(row["rung"], block["rung_actions"])
            self.assertNotIn(row["action_ru"],
                             block["rung_actions"].values())
            self.assertTrue(row["action_ru"], row)

    def test_the_tables_carry_only_what_fired(self):
        """Таблица, печатающая ВСЕ ступени и ВСЕ правила, вернула бы ту же
        плату с другой стороны: `rules` уже так и устроен."""
        block = self._block()
        used = {row["rung"] for row in block["findings"]}
        self.assertTrue(set(block["rung_actions"]).issubset(
            {r.rung for r in J.judge([]).judged} | used | set(block["by_rung"])))

    def test_a_direct_caller_of_judge_still_gets_the_full_text(self):
        """`Judged.as_dict()` — ПУБЛИЧНАЯ форма чистой функции, и укорачивать
        её нельзя: сжатие есть забота КВИТАНЦИИ, а не судьи пары. Читатель,
        зовущий `judge` напрямую, обязан получить обоснование целиком."""
        finding = {
            "finding_id": "a~b",
            "a": {"source_element_id": "a", "label": "duct",
                  "category": "OST_DuctCurves", "hull_source": "axis_section"},
            "b": {"source_element_id": "b", "label": "duct",
                  "category": "OST_DuctCurves", "hull_source": "axis_section"},
            "hull_relation": "overlap", "hull_grade": "conservative",
            "hull_overlap_depth_mm": 60.0, "ranking_tol_mm": 1.0,
            "pair_kind": "physical"}
        row = J.judge([finding]).judged[0].as_dict()
        self.assertGreater(len(row["why"]), 80)
        self.assertNotIn("rules", row["why"])


class TheBillIsVisibleInEveryAnswer(unittest.TestCase):
    """Как и с текстом: величина, которую никто не видит, растёт молча.
    Число едет в ответе, чтобы дрейф был виден на ПРОДЕ, а не только в тесте —
    регекспом реальность не догнать, данными можно."""

    def test_the_payload_size_rides_in_the_block(self):
        with _Flag():
            block = CB._report([{"ops": _ducts(6)}])
        self.assertIn("payload_chars", block["text_budget"])
        self.assertGreater(block["text_budget"]["payload_chars"], 0)

    def test_the_number_counts_the_whole_block_including_itself(self):
        """Число, считающее себя не полностью, — это замер соседа."""
        with _Flag():
            block = CB._report([{"ops": _ducts(6)}])
        actual = len(json.dumps(block, ensure_ascii=False,
                                separators=(",", ":"), default=str))
        reported = block["text_budget"]["payload_chars"]
        self.assertLessEqual(abs(actual - reported), 40,
                             f"замер {reported} против настоящих {actual}")

    def test_dedupe_actually_shrinks_the_bill(self):
        """Замер до/после на одной и той же пачке: экономия обязана быть
        ЧИСЛОМ, а не намерением."""
        with _Flag():
            block = CB._report([{"ops": _ducts(6)}])
        rows = block["findings"]
        saved = sum(len(block["rules"].get(r["rule_id"], "")) - len(r["why"])
                    for r in rows)
        self.assertGreater(saved, 0, "дедупликация не сэкономила ничего")


class TheOldGuaranteesStillHold(unittest.TestCase):
    """Правки нагрузки не имеют права стоить того, что уже держится."""

    def test_flag_off_still_adds_nothing(self):
        prev = os.environ.pop("KUKAI_IR_CLASH", None)
        try:
            CB._CACHE.clear()
            self.assertIsNone(CB.bundle_clash_report([{"ops": _ducts(3)}]))
        finally:
            if prev is not None:
                os.environ["KUKAI_IR_CLASH"] = prev
            CB._CACHE.clear()

    def test_silence_and_clean_are_still_different(self):
        with _Flag():
            clean = CB._report([{"ops": [{"op": "create_room", "id": "r"}]}])
        self.assertEqual(clean["status"], "ok")
        self.assertEqual(clean["total_findings"], 0)
        self.assertIn("bodies", clean)

    def test_introduced_still_arrives_with_its_rule(self):
        with _Flag():
            block = CB._report([{"ops": _ducts(3)}, {"ops": _ducts(1, 250.0)}],
                               new_from=2)
        self.assertIn("introduced", block)
        self.assertIn("introduced_rule", block)



class TheRuleIsTheRuleAndNotItsDefence(unittest.TestCase):
    """`introduced_rule` вёз ПРАВИЛО ВМЕСТЕ С ЕГО ЗАЩИТОЙ — 362 символа в
    КАЖДОМ ответе, 4.2% блока на `snowdon_plumb_v4` и 8.4% на `sob62_r23_v5`
    (замер 11.08.2026).

    ЧЕМ ЭТОТ СЛУЧАЙ ОТЛИЧАЕТСЯ ОТ `why` И `action_ru`, и почему указатель
    здесь был бы НЕ ТЕМ решением. Те повторялись ВНУТРИ одного ответа — пять
    строк одного значения, — и указатель на таблицу того же ответа снимал
    повтор, ничего не пряча. `introduced_rule` едет ОДИН раз на ответ;
    указатель наружу снял бы не повтор, а саму видимость, ради которой поле и
    заводилось, — то есть вернул бы правило в комментарий, туда, где
    вызывающий его не видит.

    Поэтому режется не поле, а его СОДЕРЖИМОЕ: читателю нужно ПРАВИЛО одной
    фразой; ЗАЩИТА выбора — почему «хотя бы одна сторона», а не «новый
    элемент лишь обнаружил существовавшее условие» — лежит один раз и
    указывается по имени.
    """

    def _block(self):
        with _Flag():
            return CB._report([{"ops": _ducts(3)},
                               {"ops": _ducts(1, 250.0)}], new_from=2)

    def test_the_rule_still_states_itself_in_the_payload(self):
        rule = self._block()["introduced_rule"]
        self.assertIn("ХОТЯ БЫ ОДНА", rule)
        self.assertIn("внесённой", rule.lower())

    def test_the_rule_is_a_sentence_not_an_essay(self):
        rule = self._block()["introduced_rule"]
        self.assertLessEqual(
            len(rule), CB.INTRODUCED_RULE_CAP,
            f"правило {len(rule)} симв. при потолке {CB.INTRODUCED_RULE_CAP}: "
            f"это снова правило вместе с защитой")

    def test_the_defence_is_reachable_by_name_not_deleted(self):
        """Защита не исчезает: она названа и её можно прочитать. Иначе выбор
        снова стал бы невидимым — тем самым `.FirstOrDefault()` с лучшей
        репутацией."""
        rule = self._block()["introduced_rule"]
        self.assertIn("INTRODUCED_RULE_WHY", rule)
        self.assertTrue(CB.INTRODUCED_RULE_WHY)
        self.assertIn("обнаружил", CB.INTRODUCED_RULE_WHY)

    def test_the_addends_still_let_a_reader_count_otherwise(self):
        """Сокращение защиты не имеет права забрать МАТЕРИАЛ: читатель,
        считающий иначе, по-прежнему видит оба слагаемых раздельно."""
        block = self._block()
        self.assertIn("both_new", block["by_origin"] | {"both_new": 0})
        self.assertEqual(
            block["introduced"],
            block["by_origin"].get("both_new", 0)
            + block["by_origin"].get("one_new", 0))

if __name__ == "__main__":
    unittest.main()
