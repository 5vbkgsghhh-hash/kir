"""СПИСОК КАНДИДАТОВ ОБЯЗАН НАЗВАТЬ СВОЙ ОСТАТОК — ИЗ НЕГО ДЕЛАЕТСЯ ВЫБОР.

ПОВОД — ЗАМЕР 12.08.2026 ПО 69 ПРОФИЛЯМ КОРПУСА. Отказ заземления везёт ПЯТЬ
кандидатов и предлагает «уточни через element_id из candidates». Пул при этом
бывает сильно больше пяти:

    больше пяти           524 наблюдения из 1203  (43.6%)
    family_symbols        69 профилей из 69, максимум 741
    levels                69 из 69, максимум 122
    wall_types            59 из 69, максимум 185
    door_symbols          53 из 69, максимум 113

До этого теста модель не могла отличить «пять из пяти» от «пять из семисот
сорока одного» — и выбирала тип из усечённого множества, считая его полным.

ЭТО ТРЕТЬЯ ВАЛЮТА ОДНОГО ПРИЁМА ЗА ОДИН ДЕНЬ. Печать контракта резалась по
длине и теряла ДОПУСКИ; перепись `TOP_N = 8` сохраняла ЧИСЛА и теряла ИМЕНА
категорий; здесь терялось и то и другое. Общее у всех трёх: **срез по
величине, не связанной с вопросом** (длина текста, размер категории, порядок
ElementId), а диагностически интересен почти всегда АНОМАЛЬНЫЙ член, и быть
аномальным чаще всего значит быть МАЛЫМ. И все три свёртки арифметически
честны — ревьюер, проверяющий «не потерялось ли», отвечает «нет» и прав.
**Теряется не величина, а ПРИГОДНОСТЬ.**

ЛЕЧЕНИЙ ДВА, И ЗДЕСЬ ПРИМЕНИМО ВТОРОЕ. Резать по РЕЛЕВАНТНОСТИ — так уже
делает `_nearest()` в этом же файле (`difflib`), но там ЕСТЬ имя, по которому
мерить близость. На ветке `by=default` имени нет по построению, поэтому
остаётся второе: НАЗВАТЬ ОСТАТОК И ДАТЬ СПОСОБ ЕГО ПРОЧЕСТЬ. Число говорит,
сколько ты не видишь; следующий ход говорит, что делать.
"""
import os
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(),
                                   "kir_test_candidates.jsonl"))

from kukai.ir import ground  # noqa: E402


def _pool(n: int, name: str = "тип") -> list[dict]:
    return [{"id": 1000 + i, "name": f"{name} {i}"} for i in range(n)]


class TheCandidateListSaysHowMuchIsHidden(unittest.TestCase):

    def test_control_a_pool_that_fits_pays_nothing(self):
        """КОНТРОЛЬ-PASS. Приписка обязана появляться ТОЛЬКО когда есть чему
        не влезть: отказ платится токенами каждого хода, и приписка «показаны
        5 из 5» была бы шумом в каждом отказе."""
        self.assertEqual(ground._shown_of(_pool(5), "wall_types"), "")
        self.assertEqual(ground._shown_of([], "wall_types"), "")

    def test_a_pool_that_does_not_fit_names_the_total(self):
        text = ground._shown_of(_pool(185), "wall_types")
        self.assertIn("185", text)
        self.assertIn("5", text)

    def test_it_names_the_next_move_and_not_only_the_number(self):
        """Отказ, называющий величину без следующего хода, перекладывает
        работу на читателя — тот же дефект, что код без маршрута."""
        text = ground._shown_of(_pool(741), "family_symbols")
        self.assertIn("query_types", text)
        self.assertIn("family_symbols", text)

    def test_the_shown_count_matches_what_is_actually_shown(self):
        """Две величины об одном факте обязаны сойтись: приписка говорит
        «показаны N», список отдаёт ровно N строк. Разойдясь, они дали бы
        ровно тот дефект, ради которого приписка и заведена."""
        pool = _pool(200)
        rows = ground._candidate_rows(pool)
        self.assertEqual(len(rows), ground._CANDIDATES_SHOWN)
        self.assertIn(f"ПОКАЗАНЫ {len(rows)} ИЗ 200",
                      ground._shown_of(pool, "wall_types"))

    def test_every_row_carries_an_id_because_the_next_move_needs_it(self):
        """Совет «уточни через element_id из candidates» невыполним, если у
        строки нет id."""
        for row in ground._candidate_rows(_pool(9)):
            self.assertIsInstance(row["id"], int)
            self.assertTrue(row["name"])


class TheAmbiguousRefusalsCarryIt(unittest.TestCase):
    """Приписка обязана доехать ДО СООБЩЕНИЯ, а не остаться в функции.

    Проверяется через публичный путь заземления: тест, читающий только
    `_shown_of`, доказывал бы, что строка составляется, и ничего — о том, что
    она доезжает до того, кто выбирает.
    """

    def _diags(self, pool_size: int) -> list:
        diags: list = []
        ground._resolve_one(
            {"by": "default"}, "wall_types", _pool(pool_size),
            0, "W1", "type", "create_beam", diags)
        return diags

    def test_a_big_pool_refusal_states_the_remainder(self):
        diags = self._diags(185)
        self.assertTrue(diags, "отказа нет — заземление что-то разрешило само")
        message = str(diags[0].message_ru)
        self.assertIn("185", message)
        self.assertIn("query_types", message)

    def test_control_a_small_pool_refusal_stays_silent_about_it(self):
        """КОНТРОЛЬ-FAIL для приписки: на маленьком пуле её быть НЕ должно,
        иначе тест выше проходил бы и при безусловной вставке."""
        diags = self._diags(3)
        self.assertTrue(diags)
        self.assertNotIn("ПОКАЗАНЫ", str(diags[0].message_ru))

    def test_the_count_is_in_the_message_even_for_small_pools(self):
        """Ветка `by=default` не называла ЧИСЛА вариантов вовсе — говорила
        «несколько». Это худший случай: усечение без величины и без имени."""
        diags = self._diags(3)
        self.assertIn("3 вариант", str(diags[0].message_ru))


if __name__ == "__main__":
    unittest.main()
