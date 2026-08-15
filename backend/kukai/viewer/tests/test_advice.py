"""ЧТО ДЕЛАТЬ: предложения разведения на экране.

ЗАМЕР 11.08.2026, два здания, два противоположных профиля:

| | `sob62_fas_r23_v19` | `snowdon_plumb_v4` |
|---|---|---|
| перекрытий | 19 239 | 35 633 |
| цена ОДНОЙ пары | 29.1 мс | 372.4 мс |
| полное здание | 9.3 минуты | **3.7 часа** |
| рекомендации | `review` 286, `assembly_relation` 114 | `move` 300 |
| минимальность | `minimal_over_searched_directions` 100 % | `separating_only` 100 % |

Вторая строка минимальности — причина, по которой она едет с КАЖДЫМ
предложением: на инженерном здании ход не объявлен наименьшим НИ РАЗУ, и
показать «сдвиньте трубу на 7.9 мм» без оговорки значит выдать оценку за
оптимум на 100 % предложений.
"""

import unittest

from kukai.viewer import advice as A


class TheFourPartsAllReachTheScreen(unittest.TestCase):
    """Число, рекомендация, минимальность, сертифицированность. Ни одна не
    сводится к другой, и выбросить нельзя ни одну."""

    def test_a_proposal_carries_the_number(self):
        payload = _one_proposal()
        for field in ("distance_mm", "direction", "vector_mm", "element_id"):
            self.assertIn(field, payload["chosen"])

    def test_a_proposal_carries_the_recommendation_and_its_meaning(self):
        """Четыре РАЗНЫХ действия. Подменить их одним словом значит сказать
        «подвиньте» там, где ответ «это узел, а не конфликт»."""
        payload = _one_proposal()
        self.assertIn(payload["recommendation"],
                      {"move", "review", "verify_duplicate",
                       "assembly_relation"})
        self.assertTrue(payload["recommendation_note"])

    def test_a_proposal_carries_minimality_with_its_denominator(self):
        """`minimal_over_searched_directions` без числа направлений — слово
        без числа."""
        chosen = _one_proposal()["chosen"]
        self.assertIn(chosen["minimality"],
                      {"minimal_over_searched_directions", "separating_only"})
        self.assertTrue(chosen["minimality_note"])
        self.assertGreater(chosen["directions_searched"], 0)
        self.assertTrue(chosen["direction_basis"])

    def test_a_proposal_says_whether_it_was_verified(self):
        """Инженер, которому предлагают подвинуть колонну, вправе знать,
        проверяли ли предложение переносом."""
        self.assertIn("certified", _one_proposal()["chosen"])

    def test_minimality_is_a_separate_axis_from_certification(self):
        """«Перенос разводит» и «перенос наименьший» — разные утверждения.
        Склеить их в одно поле значило бы повторить снятый дефект."""
        from kukai.clash import resolve as RS
        self.assertEqual(set(RS.MINIMALITY),
                         {"minimal_over_searched_directions",
                          "separating_only"})
        for value in RS.MINIMALITY:
            self.assertTrue(RS.MINIMALITY_NOTE[value])


class RefusalsAreTwoDifferentThings(unittest.TestCase):
    """`not_overlapping` — двигать НЕ НАДО, это ответ.
    `no_certified_direction` — пара пересекается, а хода мы не нашли; это
    НАШЕ бессилие. Первое зелёное, второе красное."""

    def test_both_refusals_are_named_in_russian(self):
        for reason in ("not_overlapping", "no_certified_direction"):
            self.assertTrue(A.REFUSAL_RU[reason].strip())

    def test_only_the_first_is_benign(self):
        self.assertIn("not_overlapping", A.BENIGN_REFUSALS)
        self.assertNotIn("no_certified_direction", A.BENIGN_REFUSALS)

    def test_the_benign_set_is_a_closed_subset_of_the_named_reasons(self):
        """Новый отказ, не отнесённый ни к одной стороне, обязан быть замечен
        тестом, а не уехать на экран нейтральным серым."""
        self.assertTrue(A.BENIGN_REFUSALS <= set(A.REFUSAL_RU))


class TheCostForcesAScope(unittest.TestCase):
    """19 239 × 29.1 мс = 9.3 минуты; 35 633 × 372.4 мс = 3.7 часа. Это
    дорого не для кадра — дорого для одного нажатия."""

    def test_the_ceiling_is_computed_from_the_worst_price_not_the_average(self):
        """ОПРОВЕРГАЮЩИЙ ТЕСТ СВОЕГО ЖЕ ПОТОЛКА. Первый вариант считал его от
        средней цены (372.4 мс) и разрешал 200 пар. Но область берётся ПО
        ГЛУБИНЕ, а глубокие пары дороже: отсортированная выборка дала
        977.1 мс — то есть 200 пар заняли бы 195 с, а не 75."""
        self.assertLessEqual(A.DEFAULT_LIMIT, A.MAX_LIMIT)
        self.assertLessEqual(A.MAX_LIMIT * A.WORST_PAIR_MS / 1000.0,
                             A.PRESS_BUDGET_S + 1.0)
        self.assertGreaterEqual(A.WORST_PAIR_MS,
                                max(A.COST_PER_PAIR_MS.values()))

    def test_the_measured_price_is_published_not_remembered(self):
        self.assertIn("sob62_fas_r23_v19", A.COST_PER_PAIR_MS)
        self.assertIn("snowdon_plumb_v4", A.COST_PER_PAIR_MS)

    def test_truncation_is_named_by_number(self):
        """Список из пятидесяти предложений и список, где их пятьдесят из
        девятнадцати тысяч, — разные вещи, и вторая без этой строки читается
        как первая."""
        advice = A.Advice(overlaps_total=19239, considered=50, truncated=19189)
        payload = advice.to_dict()
        self.assertEqual(payload["truncated"], 19189)
        self.assertIn("19189", payload["truncated_ru"])

    def test_nothing_truncated_says_nothing(self):
        payload = A.Advice(overlaps_total=3, considered=3).to_dict()
        self.assertEqual(payload["truncated_ru"], "")

    def test_the_scene_admits_it_did_not_compute_them(self):
        """Молчание сцены читалось бы как «разводить нечего»."""
        import inspect
        from kukai.viewer import scene as S
        source = inspect.getsource(S.scene_from_decompile)
        self.assertIn('"advice"', source)

    def test_advice_is_never_called_from_a_scene_path(self):
        import inspect
        from kukai.viewer import live_scene as L
        from kukai.viewer import scene as S
        for module in (S, L):
            self.assertNotIn("advise_run", inspect.getsource(module))


class ItDoesNotRewriteTheOwnersWords(unittest.TestCase):

    def test_the_human_sentence_comes_from_resolve(self):
        """Своя формулировка разошлась бы с `to_russian` на первом же
        уточнении глагола, и разошлась бы молча."""
        import inspect
        self.assertIn("RS.to_russian", inspect.getsource(A.advise_run))

    def test_the_deepest_overlaps_are_taken_first(self):
        """Если считать можно только часть, считать надо самое глубокое.
        Порядок адресов выбрал бы область по алфавиту, то есть ни по чему."""
        import inspect
        self.assertIn("hull_overlap_depth_mm", inspect.getsource(A.advise_run))


class TheUnavailableShapeIsComplete(unittest.TestCase):

    def test_it_publishes_every_key_a_consumer_reads(self):
        note = A.unavailable("нипочему")
        for key in ("available", "reason", "proposals", "considered",
                    "truncated"):
            self.assertIn(key, note)
        self.assertFalse(note["available"])


def _one_proposal():
    """Одно настоящее предложение с настоящего здания, самое глубокое.

    ДВА ПРОПУСКА, А НЕ ОДИН, И ЭТО СУТЬ. «Корпус недостижим» и «корпус на
    месте, предложений не построилось» — РАЗНЫЕ факты, и до 11.08.2026
    первый приезжал сюда `FileNotFoundError`-ом из `advice.py:204`, то есть
    отсутствие машинно-локальных данных читалось как поломка продукта. Всё
    семейство было красным в каждом worktree, кроме прода, и первый
    обошедший это подложил приватный симлинк.
    """
    from kukai.viewer.scene import corpus_unreachable_reason
    why = corpus_unreachable_reason()
    if why:
        raise unittest.SkipTest(why)
    advice = A.advise_run("sob62_fas_r23_v19", limit=1)
    payload = advice.to_dict()
    if not payload["proposals"]:
        raise unittest.SkipTest("на этом корпусе предложений не построилось")
    return payload["proposals"][0]
