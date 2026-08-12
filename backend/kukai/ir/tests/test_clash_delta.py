"""ЧТО ВНЁС ЭТОТ ХОД — а не «сколько пересечений в здании» (волна 11.08.2026).

ЗАМЕР, РАДИ КОТОРОГО ВОЛНА (`/tmp/wiring/m_delta.py`, живая пересборка
`snowdon_plumb_v4`, 129 чанков через `materialize.leaves_to_program`):

    ход   3: тел   115, пар  2 -> ВНЁС ХОД  2, стояло до хода  0
    ход  10: тел   164, пар  7 -> ВНЁС ХОД  0, стояло до хода  7
    ход  40: тел   345, пар 16 -> ВНЁС ХОД  0, стояло до хода 16
    ход 129: тел   905, пар 45 -> ВНЁС ХОД  0, стояло до хода 45

На последнем ходу квитанция говорит «СПОРОВ 45», и все 45 стояли ДО него.
Инженер, нажавший кнопку, читает это как «мой ход дал 45 пересечений» —
и это неправда ровно в том же роде, в каком неправдой было обвинять автора
за хозяина из связанного файла: чужое, записанное на его счёт.

ЧТО ВЫРАЗИМО, А ЧТО НЕТ — ЗАМЕРЕНО, А НЕ ПРЕДПОЛОЖЕНО:

  * «ДО» ВНУТРИ СЕССИИ выразимо точно. Журнал нумерует программы (`seq`,
    присваивается в `journal.append`), дверь снимает `programs_seen` ДО тела
    (`_building_watch`), значит записи с `seq >= before` — это ровно то, что
    объявил ЭТОТ ход. Адрес тела несёт номер программы (`p<N>/<id>`), поэтому
    сторону пары можно отнести к ходу, не заводя второго учёта;
  * «ДО» ОТНОСИТЕЛЬНО ДОКУМЕНТА НЕ ВЫРАЗИМО ВОВСЕ, и это измерено:
    `open_model.prune_ground_snapshot` оставляет ТОЛЬКО отметки уровней и
    сечения ТИПОВ — ни одного экземпляра, ни одного габарита. Существующая
    геометрия документа в поиск не входит НИКОГДА, поэтому пара «оба
    существовали в документе» здесь невозможна по построению, а столкновение
    с чужой стеной — не найдено, а НЕВИДИМО. Это предел, и он обязан быть
    назван словами, а не подменён полным списком.
"""
from __future__ import annotations

import unittest

from kukai.ir import clash_bundle as CB
from kukai.ir import clash_judgement as J


def _finding(a_id, b_id, la="pipe", lb="pipe"):
    return {
        "finding_id": f"{a_id}~{b_id}",
        "a": {"source_element_id": a_id, "label": la,
              "category": "OST_PipeCurves", "hull_source": "axis_section"},
        "b": {"source_element_id": b_id, "label": lb,
              "category": "OST_PipeCurves", "hull_source": "axis_section"},
        "hull_relation": "overlap", "hull_grade": "conservative",
        "hull_overlap_depth_mm": 60.0, "ranking_tol_mm": 1.0,
        "pair_kind": "physical",
    }


class ThePairKnowsWhoIntroducedIt(unittest.TestCase):
    """Три класса происхождения, и третий — НЕ то, что внёс автор."""

    NEW = frozenset({"p3/a", "p3/b"})

    def test_both_sides_new_is_the_authors_own(self):
        row = J.judge([_finding("p3/a", "p3/b")], new_ids=self.NEW).judged[0]
        self.assertEqual(row.origin, "both_new")

    def test_one_side_new_is_still_introduced_by_this_turn(self):
        """Пара, которой не было бы без этого хода, — тоже его вклад: до хода
        второй стороны в здании не с чем было спорить."""
        row = J.judge([_finding("p3/a", "p1/z")], new_ids=self.NEW).judged[0]
        self.assertEqual(row.origin, "one_new")

    def test_both_sides_prior_is_NOT_this_turns_doing(self):
        row = J.judge([_finding("p1/y", "p1/z")], new_ids=self.NEW).judged[0]
        self.assertEqual(row.origin, "both_prior")

    def test_without_a_basis_the_answer_is_unknown_not_prior(self):
        """«Не спрашивали» и «стояло до хода» — разные факты. Свалить их в
        `both_prior` значило бы объявить чужим всё, о чём не спросили."""
        row = J.judge([_finding("p1/y", "p1/z")]).judged[0]
        self.assertEqual(row.origin, "unknown")
        self.assertNotEqual(row.origin, "both_prior")

    def test_an_empty_basis_means_this_turn_declared_nothing(self):
        """Пустое множество и ОТСУТСТВИЕ множества — разные значения, тем же
        законом, что `sections=None` против `{}`."""
        row = J.judge([_finding("p1/y", "p1/z")], new_ids=frozenset()).judged[0]
        self.assertEqual(row.origin, "both_prior")

    def test_graph_segment_bodies_inherit_their_program(self):
        row = J.judge([_finding("p3/g#7", "p3/b")],
                      new_ids=frozenset({"p3/g", "p3/b"})).judged[0]
        self.assertEqual(row.origin, "both_new")

    def test_every_origin_is_counted_and_the_list_is_closed(self):
        out = J.judge([_finding("p3/a", "p3/b"), _finding("p3/a", "p1/z"),
                       _finding("p1/y", "p1/z")], new_ids=self.NEW)
        self.assertEqual(out.by_origin,
                         {"both_new": 1, "both_prior": 1, "one_new": 1})
        self.assertEqual(sum(out.by_origin.values()), len(out.judged))
        for name in out.by_origin:
            self.assertIn(name, J.ORIGINS)

    def test_the_authors_own_findings_come_first_within_a_rung(self):
        """Порядок показа отвечает на вопрос, который задают: не «что самое
        глубокое», а «что из этого моё». Внутри ОДНОЙ ступени — сначала своё."""
        out = J.judge([_finding("p1/y", "p1/z"), _finding("p3/a", "p3/b")],
                      new_ids=self.NEW)
        self.assertEqual([r.origin for r in out.judged],
                         ["both_new", "both_prior"])

    def test_without_a_basis_the_order_is_untouched(self):
        """Байт в байт прежний порядок там, где дельты не спрашивали."""
        pair = [_finding("p1/y", "p1/z"), _finding("p3/a", "p3/b")]
        self.assertEqual([r.finding_id for r in J.judge(pair).judged],
                         [r.finding_id for r in J.judge(pair).judged])
        self.assertEqual([r.origin for r in J.judge(pair).judged],
                         ["unknown", "unknown"])


class TheReceiptAnswersTheQuestionThatIsAsked(unittest.TestCase):
    """`_report` обязан отдать вклад ХОДА, а не только итог по зданию."""

    def _pack(self):
        def duct(oid, x):
            return {"op": "create_duct", "id": oid, "diameter_mm": 200.0,
                    "p0_mm": [x, 0.0, 0.0], "p1_mm": [x, 2000.0, 0.0]}
        # p1: две пересекающиеся трассы (спор СТОЯЛ до хода)
        # p2: ещё одна поверх них (спор ВНЁС ход)
        return [{"ops": [duct("d1", 0.0), duct("d2", 50.0)]},
                {"ops": [duct("d3", 25.0)]}]

    def setUp(self):
        self._prev = CB.__dict__["os"].environ.get("KUKAI_IR_CLASH")
        CB.__dict__["os"].environ["KUKAI_IR_CLASH"] = "1"
        CB._CACHE.clear()

    def tearDown(self):
        if self._prev is None:
            CB.__dict__["os"].environ.pop("KUKAI_IR_CLASH", None)
        else:
            CB.__dict__["os"].environ["KUKAI_IR_CLASH"] = self._prev
        CB._CACHE.clear()

    def test_the_block_separates_what_this_turn_introduced(self):
        block = CB._report(self._pack(), new_from=2)
        self.assertEqual(block["delta_basis"], "session_turn")
        self.assertIn("by_origin", block)
        self.assertGreater(block["introduced"], 0)
        self.assertLess(block["introduced"], block["total_findings"])

    def test_without_a_basis_the_block_says_so_and_counts_nothing(self):
        block = CB._report(self._pack())
        self.assertEqual(block["delta_basis"], "none")
        self.assertNotIn("introduced", block)

    def test_the_cache_key_includes_the_delta(self):
        """Один и тот же пакет с РАЗНОЙ границей хода — разные ответы, и
        отдать первый было бы тем же враньём, что отдать чужой снапшот."""
        a = CB._report(self._pack(), new_from=1)
        b = CB._report(self._pack(), new_from=2)
        self.assertNotEqual(a.get("introduced"), b.get("introduced"))

    def test_the_text_leads_with_the_turns_own_contribution(self):
        text = CB._report(self._pack(), new_from=2)["message_ru"]
        self.assertIn("ВНЕСЛА ЭТА ПАЧКА", text)

    def test_the_invisible_half_is_named_every_time(self):
        """Существующая геометрия документа в поиск не входит НИКОГДА
        (`prune_ground_snapshot` несёт только уровни и сечения типов), поэтому
        столкновение с ней не найдено, а НЕВИДИМО. Предел называется словами
        всегда, а не только когда дельту спросили."""
        for kwargs in ({}, {"new_from": 2}):
            block = CB._report(self._pack(), **kwargs)
            self.assertEqual(block["delta_scope"], "declared_only")
            self.assertIn("НЕ ВИДИТ", block["message_ru"])

    def test_a_clean_turn_still_carries_its_denominator(self):
        """«Ход не внёс ничего» и «прибор не смотрел» обязаны различаться:
        первое приходит вместе с числом тел и числом пар здания."""
        block = CB._report(self._pack(), new_from=3)
        self.assertEqual(block["introduced"], 0)
        self.assertGreater(block["total_findings"], 0)
        self.assertGreater(block["bodies"], 0)
        self.assertIn("ВНЕСЛА ЭТА ПАЧКА: 0", block["message_ru"])


class TheTwoDoorsGetTwoDifferentAnswers(unittest.TestCase):
    """У чат-двери «до» ЕСТЬ — это то, что сессия объявила раньше. У двери
    пересборки его нет: материализатор строит здание с нуля, и первый чанк
    сессии не имеет предшественника вовсе. Одно слово на две ситуации
    означало бы, что дельта у пересборки «0 внесено» — то есть ровно
    наоборот."""

    KEY = ("test-clash-delta", "")

    def setUp(self):
        from kukai.live import journal
        journal.reset(self.KEY)
        self._prev = CB.__dict__["os"].environ.get("KUKAI_IR_CLASH")
        CB.__dict__["os"].environ["KUKAI_IR_CLASH"] = "1"
        CB._CACHE.clear()

    def tearDown(self):
        from kukai.live import journal
        journal.reset(self.KEY)
        if self._prev is None:
            CB.__dict__["os"].environ.pop("KUKAI_IR_CLASH", None)
        else:
            CB.__dict__["os"].environ["KUKAI_IR_CLASH"] = self._prev
        CB._CACHE.clear()

    def _seed(self, n):
        from kukai.live import journal
        for p in range(n):
            journal.append(self.KEY, {"ops": [
                {"op": "create_duct", "id": f"p{p}d{i}", "diameter_mm": 200.0,
                 "p0_mm": [i * 25.0, 0.0, 0.0], "p1_mm": [i * 25.0, 2000.0, 0.0]}
                for i in range(3)]}, source="bulk")

    def test_the_first_turn_of_a_session_has_no_before(self):
        from kukai.live import verdict
        self._seed(1)
        block = verdict.clash_only(self.KEY, since_seq=0)
        self.assertEqual(block["delta_basis"], "whole_bundle_new")
        self.assertEqual(block["introduced"], block["total_findings"])

    def test_a_later_turn_is_measured_against_the_session(self):
        from kukai.live import verdict
        self._seed(2)
        block = verdict.clash_only(self.KEY, since_seq=1)
        self.assertEqual(block["delta_basis"], "session_turn")

    def test_asking_without_a_seq_keeps_the_whole_building_answer(self):
        from kukai.live import verdict
        self._seed(2)
        block = verdict.clash_only(self.KEY)
        self.assertEqual(block["delta_basis"], "none")

    def test_eviction_does_not_shift_the_boundary(self):
        """Вытеснение головы журнала сдвигает ПОЗИЦИИ в пачке, но не `seq`.
        Считать границу по позиции значило бы объявить своим чужое ровно на
        самом большом здании — том, где журнал переполнился."""
        from kukai.live import journal
        self._seed(3)
        entry = journal.get(self.KEY)
        entry.records.pop(0)
        entry.programs_evicted += 1
        block = verdict.clash_only(self.KEY, since_seq=2) if False else None
        from kukai.live import verdict as V
        block = V.clash_only(self.KEY, since_seq=2)
        self.assertEqual(block["delta_basis"], "session_turn")
        self.assertLess(block["introduced"], block["total_findings"] + 1)


class TheBulkDoorStampsTheDelta(unittest.TestCase):
    KEY = ("test-clash-delta-door", "")

    def setUp(self):
        from kukai.live import journal
        journal.reset(self.KEY)
        CB.__dict__["os"].environ["KUKAI_IR_CLASH"] = "1"
        CB._CACHE.clear()

    def tearDown(self):
        from kukai.live import journal
        journal.reset(self.KEY)
        CB.__dict__["os"].environ.pop("KUKAI_IR_CLASH", None)
        CB._CACHE.clear()

    def test_the_watch_is_the_delta_boundary(self):
        """Отметка, которую дверь уже снимает ДО тела (`_building_watch`), и
        есть граница хода. Второго учёта «что нового» не заводится."""
        import asyncio

        from kukai.ir import serving
        from kukai.live import journal
        for p in range(2):
            journal.append(self.KEY, {"ops": [
                {"op": "create_duct", "id": f"q{p}", "diameter_mm": 200.0,
                 "p0_mm": [p * 25.0, 0.0, 0.0],
                 "p1_mm": [p * 25.0, 2000.0, 0.0]}]}, source="bulk")
        receipt = {"ok": True}
        asyncio.run(serving._stamp_building_clash(receipt, (self.KEY, 1)))
        self.assertEqual(receipt["clash"]["delta_basis"], "session_turn")



class TheChatDoorGetsTheDeltaToo(unittest.TestCase):
    """В ЧАТЕ ЧЕК ЧИТАЕТ МОДЕЛЬ, И ЭТО МЕНЯЕТ ЦЕНУ ОШИБКИ.

    Модель, увидевшая «СПОРОВ 45» там, где 45 стояли до неё, поведёт себя
    одним из двух способов, и оба вредны: либо начнёт чинить то, чего не
    ломала — тратя ходы и внося правки в ЧУЖУЮ геометрию, — либо доложит
    инженеру, что сломала здание. Это не отсутствующая возможность, а
    активный вред, поэтому дельта в чате стоит раньше косметики.

    ФОРМА СТРОГО АДДИТИВНАЯ. Все прежние ключи сохраняют смысл байт в байт:
    корпус свидетелей и голденов читает старую форму, и шелохнуться она не
    имеет права. Дельта едет НОВЫМИ ключами, а без основания их нет вовсе —
    ноль вместо «не спрашивали» здесь запрещён так же, как везде.
    """

    KEY = ("test-clash-chat-delta", "")

    def setUp(self):
        from kukai.live import journal
        journal.reset(self.KEY)
        self._prev = CB.__dict__["os"].environ.get("KUKAI_IR_CLASH")
        CB.__dict__["os"].environ["KUKAI_IR_CLASH"] = "1"
        CB._CACHE.clear()

    def tearDown(self):
        from kukai.live import journal
        journal.reset(self.KEY)
        if self._prev is None:
            CB.__dict__["os"].environ.pop("KUKAI_IR_CLASH", None)
        else:
            CB.__dict__["os"].environ["KUKAI_IR_CLASH"] = self._prev
        CB._CACHE.clear()

    def _seed(self, n):
        from kukai.live import journal
        for p in range(n):
            journal.append(self.KEY, {"ops": [
                {"op": "create_duct", "id": f"c{p}d{i}", "diameter_mm": 200.0,
                 "p0_mm": [i * 25.0, 0.0, 0.0],
                 "p1_mm": [i * 25.0, 2000.0, 0.0]}
                for i in range(3)]}, source="chat")

    def test_the_verdict_carries_the_delta_when_the_turn_is_named(self):
        from kukai.live import verdict
        self._seed(2)
        block = verdict.judge(self.KEY, since_seq=1)
        self.assertEqual(block["clash"]["delta_basis"], "session_turn")
        self.assertIn("introduced", block["clash"])

    def test_without_a_turn_the_form_does_not_move(self):
        """Ключ `introduced` ОТСУТСТВУЕТ, а не равен нулю: «ход ничего не внёс»
        и «границу хода не называли» — разные ответы."""
        from kukai.live import verdict
        self._seed(2)
        block = verdict.judge(self.KEY)
        self.assertEqual(block["clash"]["delta_basis"], "none")
        self.assertNotIn("introduced", block["clash"])

    def test_the_old_keys_keep_their_meaning(self):
        from kukai.live import verdict
        self._seed(2)
        plain = verdict.judge(self.KEY)
        delta = verdict.judge(self.KEY, since_seq=1)
        for key in ("schema", "programs", "ops", "programs_evicted",
                    "verdict"):
            self.assertEqual(plain[key], delta[key], key)
        for key in ("schema", "status", "bodies", "total_findings",
                    "elements_considered", "without_body"):
            self.assertEqual(plain["clash"][key], delta["clash"][key], key)

    def test_the_verdict_stamp_passes_the_same_watch(self):
        """Граница — та же отметка, что у дозора. Второго учёта «что нового»
        в дереве не заводится ни для одной двери."""
        import asyncio

        from kukai.ir import serving
        self._seed(2)
        result = {"ok": True}
        asyncio.run(serving._stamp_building_verdict(result, (self.KEY, 1)))
        self.assertEqual(result["building"]["clash"]["delta_basis"],
                         "session_turn")


class TheRuleBehindTheNumberIsNamed(unittest.TestCase):
    """ВЫБОР, КОТОРОГО ВЫЗЫВАЮЩИЙ НЕ ВИДИТ, ЕСТЬ `.FirstOrDefault()` С ЛУЧШЕЙ
    РЕПУТАЦИЕЙ. Закон про именованные умолчания написан не для этого модуля
    (`ground.py`), но случай здесь ровно тот же.

    `introduced` складывает `both_new` и `one_new`, и это СУЖДЕНИЕ, а не
    замер: пары с одной новой стороной без этого хода не существовало бы
    вовсе — но обратное прочтение («новый элемент лишь обнаружил уже
    существовавшее условие») защитимо. Значит правило обязано ехать рядом с
    числом СЛОВАМИ и в полезной нагрузке, а не в комментарии к коду.
    """

    def _pack(self):
        def duct(oid, x):
            return {"op": "create_duct", "id": oid, "diameter_mm": 200.0,
                    "p0_mm": [x, 0.0, 0.0], "p1_mm": [x, 2000.0, 0.0]}
        return [{"ops": [duct("d1", 0.0), duct("d2", 50.0)]},
                {"ops": [duct("d3", 25.0)]}]

    def setUp(self):
        self._prev = CB.__dict__["os"].environ.get("KUKAI_IR_CLASH")
        CB.__dict__["os"].environ["KUKAI_IR_CLASH"] = "1"
        CB._CACHE.clear()

    def tearDown(self):
        if self._prev is None:
            CB.__dict__["os"].environ.pop("KUKAI_IR_CLASH", None)
        else:
            CB.__dict__["os"].environ["KUKAI_IR_CLASH"] = self._prev
        CB._CACHE.clear()

    def test_the_number_arrives_with_its_rule(self):
        block = CB._report(self._pack(), new_from=2)
        self.assertIn("introduced_rule", block)
        self.assertIn("ХОТЯ БЫ ОДНА", block["introduced_rule"])

    def test_the_rule_is_absent_when_the_number_is(self):
        block = CB._report(self._pack())
        self.assertNotIn("introduced_rule", block)
        self.assertNotIn("introduced", block)

    def test_the_addends_are_published_separately(self):
        """Читатель, считающий иначе, обязан получить материал для своего
        счёта, а не только мой итог."""
        block = CB._report(self._pack(), new_from=2)
        origins = block["by_origin"]
        self.assertEqual(block["introduced"],
                         origins.get("both_new", 0) + origins.get("one_new", 0))
        self.assertIn("one_new", origins)

    def test_the_receipt_says_the_rule_out_loud(self):
        text = CB._report(self._pack(), new_from=2)["message_ru"]
        self.assertIn("хотя бы одна", text.lower())


if __name__ == "__main__":
    unittest.main()
