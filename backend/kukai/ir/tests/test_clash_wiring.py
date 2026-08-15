"""ОПРОВЕРГАЮЩИЕ ТЕСТЫ ВОЛНЫ «клеш видит дверь пересборки» (10.08.2026).

КАЖДЫЙ ТЕСТ ЗДЕСЬ ПАДАЛ ДО ПРАВКИ, И ПАДАЛ ДОСЛОВНО НА ТОМ, ЧТО НАЗЫВАЕТ. Это
не проверки «работает ли»: каждый воспроизводит ЗАМЕРЕННЫЙ дефект и умирает
вместе с ним.

ЧЕГО ЗДЕСЬ НЕТ. Живого Revit, моста и сети. Всё, что проверяется, — чистые
функции и один `asyncio.run` над штампом квитанции.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import unittest

from kukai.ir import clash_bundle
from kukai.ir import clash_judgement as J
from kukai.live import journal as live_journal
from kukai.live import verdict as live_verdict


def _sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True,
                                     default=str).encode("utf-8")).hexdigest()


class _FlagOff:
    """Контекст «флага нет» — то самое состояние прода (замер 10.08: в
    окружении живого процесса `KUKAI_IR_CLASH` отсутствует)."""

    def __enter__(self):
        self._saved = os.environ.pop("KUKAI_IR_CLASH", None)
        return self

    def __exit__(self, *exc):
        if self._saved is not None:
            os.environ["KUKAI_IR_CLASH"] = self._saved
        else:
            os.environ.pop("KUKAI_IR_CLASH", None)
        return False


class _FlagOn:
    def __enter__(self):
        self._saved = os.environ.get("KUKAI_IR_CLASH")
        os.environ["KUKAI_IR_CLASH"] = "1"
        clash_bundle._CACHE.clear()
        return self

    def __exit__(self, *exc):
        if self._saved is None:
            os.environ.pop("KUKAI_IR_CLASH", None)
        else:
            os.environ["KUKAI_IR_CLASH"] = self._saved
        clash_bundle._CACHE.clear()
        return False


# ─────────────────────────────────────────────────────────────────────────
# 1. ХОЗЯИН — РЕБРО, А НЕ ПАРА ЯРЛЫКОВ
# ─────────────────────────────────────────────────────────────────────────

def _finding(a_id, b_id, a_label="door", b_label="wall", *,
             relation="overlap", grade="conservative", depth=120.0,
             a_src="profile", b_src="profile", pair_kind="physical"):
    return {
        "finding_id": f"{a_id}~{b_id}",
        "a": {"source_element_id": a_id, "label": a_label,
              "category": "OST_Doors", "hull_source": a_src,
              "hull_grade": grade},
        "b": {"source_element_id": b_id, "label": b_label,
              "category": "OST_Walls", "hull_source": b_src,
              "hull_grade": grade},
        "hull_relation": relation,
        "hull_grade": grade,
        "verdict": "confirmed" if grade == "exact" else "possible",
        "hull_overlap_depth_mm": depth,
        "ranking_tol_mm": 1.0,
        "pair_kind": pair_kind,
    }


class HostIsAnEdgeNotALabelPair(unittest.TestCase):
    """ЗАМЕР, РАДИ КОТОРОГО ЭТО НАПИСАНО (`/tmp/wiring/m_baseline.py`,
    10.08.2026, разбор `sob62_r23_v5`): догадка по паре ярлыков
    (`clash.resolve.ASSEMBLY_PAIRS`) срабатывает на 497 находках из 3 759, и
    `L0Element.host_id` подтверждает её только на 184 — **313 пар (63.0%)
    снимались бы вопреки данным**, худшие классы `door~wall` 181 и
    `wall~window` 58. На `sob62_fas_r23_v19`: 8 815 срабатываний, подтверждено
    1 453, **не подтверждено 7 362 (83.5%)**.

    Образец из корпуса дословно: дверь `10324348` объявляет хозяином стену
    `9857641`, а перекрывается со стеной `13109052`.
    """

    def test_declared_host_confirms_and_removes_the_pair(self):
        hosted = {"10324348": {"host_element_id": "9857641",
                               "host_class": "Wall", "source": "l0_host_id"}}
        out = J.judge([_finding("10324348", "9857641")], hosted=hosted)
        row = out.judged[0]
        self.assertEqual(row.host_state, "confirms")
        self.assertEqual(row.rule_id, "host_declared")
        self.assertEqual(row.rung, "note")

    def test_host_elsewhere_does_NOT_acquit(self):
        """СЕРДЦЕВИНА ВОЛНЫ. Дверь перекрывает стену, в которой НЕ живёт.
        Догадка по ярлыкам сказала бы «узел, не смотри»; данные говорят, что
        это находка, и она обязана остаться."""
        hosted = {"10324348": {"host_element_id": "9857641",
                               "host_class": "Wall", "source": "l0_host_id"}}
        out = J.judge([_finding("10324348", "13109052")], hosted=hosted)
        row = out.judged[0]
        self.assertEqual(row.host_state, "contradicts")
        self.assertNotEqual(row.rule_id, "host_declared")
        self.assertEqual(row.declared_host_id, "9857641")
        self.assertEqual(row.host_source, "l0_host_id")
        # адрес НАСТОЯЩЕГО хозяина обязан доехать до читателя словами:
        # без него строка «это не тот хозяин» непроверяема
        self.assertIn("9857641", row.text_ru)

    def test_absent_host_is_not_a_confirmation(self):
        """ОТСУТСТВИЕ НЕ ОПРАВДЫВАЕТ. Индекс есть, у этой пары хозяина нет —
        и это НЕ «значит узел»."""
        out = J.judge([_finding("1", "2")], hosted={})
        self.assertEqual(out.judged[0].host_state, "absent")
        self.assertNotEqual(out.judged[0].rule_id, "host_declared")

    def test_absent_index_and_empty_index_are_DIFFERENT_facts(self):
        """`None` («не спрашивали») и `{}` («спросили, хозяев нет») обязаны
        быть разными значениями — тем же законом, каким `journal.sections`
        различает `None` и `{}`, а `hulls_coincide` — «нет» и «нечего
        сказать»."""
        empty = J.judge([_finding("1", "2")], hosted={})
        none = J.judge([_finding("1", "2")], hosted=None)
        self.assertEqual(empty.judged[0].host_state, "absent")
        self.assertEqual(none.judged[0].host_state, "unknown")
        self.assertNotEqual(empty.judged[0].host_state,
                            none.judged[0].host_state)

    def test_every_state_is_counted_even_when_it_removes_nothing(self):
        """`contradicts` и `absent` не снимают ни одной пары, поэтому в
        `filtered_by_rule` они не появились бы ВОВСЕ — то есть самый дорогой
        факт остался бы без знаменателя. Для них заведён свой счётчик."""
        hosted = {"a": {"host_element_id": "zzz", "source": "l0_host_id"}}
        out = J.judge([_finding("a", "b"), _finding("c", "d")], hosted=hosted)
        self.assertEqual(out.by_host_state, {"absent": 1, "contradicts": 1})
        self.assertEqual(sum(out.by_host_state.values()), len(out.judged))
        for state in out.by_host_state:
            self.assertIn(state, J.HOST_STATES)


class HostRefIsQualifiedByProgram(unittest.TestCase):
    """ССЫЛКА НА ХОЗЯИНА РАЗРЕШАЕТСЯ ТОЛЬКО ВНУТРИ СВОЕЙ ПРОГРАММЫ.

    Прежний `_host_declared` сравнивал `host.value` с ГОЛЫМ `id` соседа, а
    `id` уникален лишь внутри программы — между программами совпадение
    ЗАКОННО, и ровно поэтому `clash_bundle.bundle_oid` квалифицирует адрес
    ВСЕГДА (`p1/wall1`). Значит дверь из программы 7, объявившая хозяином
    `wall1` СВОЕЙ программы, снимала находку с одноимённой стеной программы 1
    — оправдание через границу программы, которую `KIR-V002` запрещает.
    """

    def test_same_id_in_another_program_is_not_a_host(self):
        ops = {
            "p1/wall1": {"op": "create_wall", "id": "wall1"},
            "p7/wall1": {"op": "create_wall", "id": "wall1"},
            "p7/door1": {"op": "create_door", "id": "door1",
                         "host": {"by": "ref", "value": "wall1"}},
        }
        hosted = J.hosted_from_ops(ops)
        self.assertEqual(hosted["p7/door1"]["host_element_id"], "p7/wall1")
        # своя программа — снимаем
        self.assertEqual(
            J.host_relation("p7/door1", "p7/wall1", hosted)[0], "confirms")
        # ЧУЖАЯ программа — НЕ снимаем: это и есть дефект
        self.assertEqual(
            J.host_relation("p7/door1", "p1/wall1", hosted)[0], "contradicts")

    def test_unresolvable_host_ref_is_named_not_swallowed(self):
        """Автор НАЗВАЛ хозяина, которого в пачке нет. Это факт о заявлении и
        чинится автором; молчание прочиталось бы как «хозяина не объявляли»."""
        ops = {"p1/d": {"op": "create_door", "id": "d",
                        "host": {"by": "ref", "value": "нет-такого"}}}
        hosted = J.hosted_from_ops(ops)
        self.assertIsNone(hosted["p1/d"]["host_element_id"])
        state, host_id, _src = J.host_relation("p1/d", "p1/w", hosted)
        self.assertEqual(state, "contradicts")
        self.assertEqual(host_id, "нет-такого")

    def test_graph_segment_bodies_share_their_op_host(self):
        """Тело ребра графа адресуется `p1/g#3`, а хозяина объявляет ОПЕРАЦИЯ
        `p1/g`. Отношение обязано находиться по обоим адресам."""
        ops = {"p1/w": {"op": "create_wall", "id": "w"},
               "p1/g": {"op": "route_duct_system", "id": "g",
                        "host": {"by": "ref", "value": "w"}}}
        hosted = J.hosted_from_ops(ops)
        self.assertEqual(J.host_relation("p1/g#3", "p1/w", hosted)[0],
                         "confirms")


class OpsStillProduceTheEdge(unittest.TestCase):
    """Прежние вызывающие передают `ops`, а не `hosted`. Ни один из них не
    имеет права потерять отношение хозяина этой волной."""

    def test_ops_only_call_still_finds_the_host(self):
        ops = {"p1/w": {"op": "create_wall", "id": "w"},
               "p1/d": {"op": "create_door", "id": "d",
                        "host": {"by": "ref", "value": "w"}}}
        out = J.judge([_finding("p1/d", "p1/w")], ops=ops)
        self.assertEqual(out.judged[0].rule_id, "host_declared")
        self.assertEqual(out.judged[0].host_source, "program_host_ref")


class PenetrationNeedsBodyEvidence(unittest.TestCase):
    """Semantic rule «трасса через ограждение — узел» не доказывает,
    что трасса и ограждение вообще пересеклись. Для хода `agree`
    нужна точная геометрия, а не outer-only overlap."""

    def test_outer_only_penetration_stays_possible_and_non_executable(self):
        finding = _finding("p1/pipe", "p1/w", a_label="pipe", b_label="wall")
        out = J.judge([finding], hosted={})
        row = out.judged[0]
        self.assertEqual(row.kind, "penetration")
        self.assertIs(row.proven, False)
        self.assertEqual(row.rung, "look")
        self.assertNotIn("create_opening", row.next_move_ru)

    def test_confirmed_word_without_inner_chain_cannot_reach_agree(self):
        finding = _finding("p1/pipe", "p1/w", a_label="pipe", b_label="wall",
                           a_src="prism", b_src="prism", grade="exact")
        row = J.judge([finding], hosted={}).judged[0]
        self.assertIsNone(row.proven)
        self.assertEqual(row.rung, "look")
        self.assertNotIn("create_opening", row.next_move_ru)

    def test_bbox_penetration_drops_to_look(self):
        finding = _finding("p1/pipe", "p1/w", a_label="pipe", b_label="wall",
                           a_src="bbox", b_src="bbox", grade="coarse")
        row = J.judge([finding], hosted={}).judged[0]
        self.assertIsNone(row.proven)
        self.assertEqual(row.rung, "look")


# ─────────────────────────────────────────────────────────────────────────
# 2. ПОТОЛОК, ПОДПИСАННЫЙ ОДНОЙ ОСЬЮ И ЧИТАЮЩИЙ ДРУГУЮ
# ─────────────────────────────────────────────────────────────────────────

class TheBodyCapMustReadBodies(unittest.TestCase):
    """ЗАМЕР (`/tmp/wiring/m_cap.py`, живая пересборка `snowdon_plumb_v4`):
    потолок с именем «число ТЕЛ» и обоснованием «снапшот 3 000 ТЕЛ — 91 мс»
    сравнивался с `len(elements)`. На чанке 24 это 3 081 элемент при **171
    теле** — отказ «не смотрели» при 5.7% собственного бюджета; на полном
    здании 16 257 элементов при **905 телах**, а работа, от которой
    отказывались, стоит 174 мс + 11 мс.

    Пачка ниже — СТЕНЫ БЕЗ СНАПШОТА: элемент есть у каждой, оболочки нет ни у
    одной (толщина живёт в типе, а типов никто не спрашивал). Это ровно то
    соотношение, что на настоящей пересборке, и `create_room` тут не годится:
    он `OP_NO_BODY` и в `elements` не попадает вовсе — то есть прежний потолок
    им не воспроизводится.
    """

    def _pack(self, walls):
        return [{"ops": [{"op": "create_wall", "id": f"w{i}",
                          "p0_mm": [i * 5_000.0, 0.0, 0.0],
                          "p1_mm": [i * 5_000.0 + 4_000.0, 0.0, 0.0]}
                         for i in range(walls)]}]

    def test_five_thousand_bodiless_elements_do_not_trip_the_body_cap(self):
        with _FlagOn():
            block = clash_bundle.bundle_clash_report(self._pack(5_000))
        self.assertEqual(block["status"], "ok", block.get("message_ru"))
        self.assertEqual(block["bodies"], 0)
        # и знаменатель на месте: 5 000 элементов, которых НЕ ВИДЕЛИ
        self.assertEqual(block["without_body"], 5_000)

    def test_element_ceiling_is_its_own_named_axis(self):
        self.assertNotEqual(clash_bundle._max_elements(),
                            clash_bundle._max_bodies())
        with _FlagOn():
            os.environ["KUKAI_IR_CLASH_MAX_ELEMENTS"] = "16"
            try:
                clash_bundle._CACHE.clear()
                block = clash_bundle.bundle_clash_report(self._pack(64))
            finally:
                os.environ.pop("KUKAI_IR_CLASH_MAX_ELEMENTS", None)
        self.assertEqual(block["status"], "over_cap")
        # ОТКАЗ НАЗЫВАЕТ СВОЮ ОСЬ. «Не смотрели» без предмета неотличимо от
        # «смотрели и не нашли».
        self.assertIn("элементов", block["message_ru"])
        self.assertNotIn("тел", block["message_ru"].split("элементов")[0])


# ─────────────────────────────────────────────────────────────────────────
# 3. КЛЕШ ОТВЯЗАН ОТ ВЕРДИКТА
# ─────────────────────────────────────────────────────────────────────────

def _seed(key, programs, ops_each=4):
    live_journal.reset(key)
    for p in range(programs):
        live_journal.append(key, {"ops": [
            {"op": "create_room", "id": f"p{p}r{i}"} for i in range(ops_each)]},
            source="bulk")


def _seed_walls(key, programs, walls_each):
    """Стены без снапшота: элементы есть, тел нет. Нужны там, где проверяется
    ПОТОЛОК ПО ЭЛЕМЕНТАМ, — `create_room` в `elements` не попадает вовсе."""
    live_journal.reset(key)
    for p in range(programs):
        live_journal.append(key, {"ops": [
            {"op": "create_wall", "id": f"p{p}w{i}",
             "p0_mm": [i * 5_000.0, p * 9_000.0, 0.0],
             "p1_mm": [i * 5_000.0 + 4_000.0, p * 9_000.0, 0.0]}
            for i in range(walls_each)]}, source="bulk")


class ClashSurvivesTheVerdictCeiling(unittest.TestCase):
    """ЗАМЕРЕННЫЙ ДЕФЕКТ. `judge` возвращался по `_over_cap` РАНЬШЕ строки
    `clash = _clash_block(...)`, поэтому потолок вердикта (1 200 операций,
    выбранный под цену `check_bundle`) отключал ЗАОДНО и проверку на
    коллизии — у которой три СВОИХ потолка и своя цена. Пересборка Snowdon
    Towers (6 335 операций) не получала о коллизиях ни слова, и молчание это
    читается как «коллизий нет».

    Комментарий строкой ниже при этом утверждал обратное: «Коллизии
    считаются НЕЗАВИСИМО от вердикта о пригодности».
    """

    KEY = ("test-clash-over-cap", "")

    def tearDown(self):
        live_journal.reset(self.KEY)

    def test_over_the_verdict_ceiling_clash_still_speaks(self):
        os.environ["KUKAI_KIR_BUILDING_VERDICT_OPS"] = "20"
        try:
            _seed(self.KEY, programs=40, ops_each=4)     # 160 операций > 20
            with _FlagOn():
                block = live_verdict.judge(self.KEY)
        finally:
            os.environ.pop("KUKAI_KIR_BUILDING_VERDICT_OPS", None)
        self.assertIsNotNone(block)
        self.assertIn("НЕ СЧИТАЛСЯ", block["message_ru"])   # вердикт отказал
        self.assertIn("clash", block)                        # клеш — нет
        self.assertIn("КОЛЛИЗИИ", block["message_ru"])


class ClashDoesNotRideTheVerdictSwITCH(unittest.TestCase):
    """ТРЕТЬЕ МЕСТО, ГДЕ КЛЕШ НАСЛЕДОВАЛ ЧУЖОЙ ВЫКЛЮЧАТЕЛЬ, и самое молчаливое.

    `judge` начинался строкой `if not enabled(): return None`, а `enabled()`
    читает `KUKAI_KIR_BUILDING_VERDICT` — флаг ВЕРДИКТА. Два выключателя
    стояли на одном проводе: погасив обратную связь модели, оператор гасил и
    АУДИТ ЗДАНИЯ, у которого свой флаг `KUKAI_IR_CLASH`.

    ЧТО ИМЕННО СТАНОВИЛОСЬ НЕОТЛИЧИМЫМ. `judge` возвращает `None`, штамп
    делает `if block:` и не кладёт ничего — квитанция уезжает БЕЗ единого
    слова о коллизиях. Ровно так же она выглядит, когда коллизий нет. То есть
    «прибор был выключен чужим тумблером» и «пересечений не найдено» давали
    ОДИН И ТОТ ЖЕ байт-в-байт ответ, и отличить их читателю было нечем.
    """

    KEY = ("test-clash-verdict-switch", "")

    def tearDown(self):
        live_journal.reset(self.KEY)
        os.environ.pop("KUKAI_KIR_BUILDING_VERDICT", None)

    def test_verdict_switch_does_not_silence_the_audit(self):
        _seed(self.KEY, programs=3)
        os.environ["KUKAI_KIR_BUILDING_VERDICT"] = "0"
        with _FlagOn():
            block = live_verdict.judge(self.KEY)
        self.assertIsNotNone(block, "вердикт выключен — аудит замолчал вместе с ним")
        self.assertIn("clash", block)
        self.assertEqual(block["verdict"], "")      # вердикта нет и не должно
        self.assertIn("КОЛЛИЗИИ", block["message_ru"])

    def test_both_switches_off_is_still_byte_identical(self):
        """Прод: `KUKAI_IR_CLASH` отсутствует. Тогда и при выключенном
        вердикте ответ обязан остаться прежним — `None`."""
        _seed(self.KEY, programs=3)
        os.environ["KUKAI_KIR_BUILDING_VERDICT"] = "0"
        with _FlagOff():
            self.assertIsNone(live_verdict.judge(self.KEY))


class ClashObservesTheBulkDoor(unittest.TestCase):
    """ПРОДУКТОВЫЙ БЛОКЕР. `_stamp_building_verdict` зовётся ровно двумя
    строками, обе на пути `bulk=False`; `handle_revit_ir_bulk` не звал его
    никогда. То есть единственный маршрут, которым собираются ЦЕЛЫЕ здания,
    — тот самый, которого проверка на коллизии не видела.
    """

    KEY = ("test-clash-bulk-door", "")

    def tearDown(self):
        live_journal.reset(self.KEY)

    def test_clash_only_reads_the_whole_journal_not_one_chunk(self):
        """ШОВ — ПАЧКА ЖУРНАЛА, А НЕ ЧАНК. Клеш есть отношение ДВУХ
        элементов, а чанк режется по 250 операций: труба из чанка 7 и стена
        из чанка 3 в одной программе не встретятся никогда."""
        _seed(self.KEY, programs=26, ops_each=10)
        with _FlagOn():
            block = live_verdict.clash_only(self.KEY)
        self.assertIsNotNone(block)
        # 26 программ журнала, а не одна: пачка — единица здания
        self.assertEqual(len(live_journal.get(self.KEY).records), 26)

    def test_clash_only_builds_no_verdict(self):
        """Исключение админской двери из ВЕРДИКТА остаётся: там автор —
        материализатор, и учить некого. Клеш этого довода не наследует."""
        _seed(self.KEY, programs=3)
        with _FlagOn():
            block = live_verdict.clash_only(self.KEY)
        self.assertIsNotNone(block)
        for forbidden in ("verdict", "blocking", "rules_evaluated",
                          "rules_suspended"):
            self.assertNotIn(forbidden, block)

    def test_a_silent_instrument_is_distinguishable_from_a_clean_result(self):
        """«ПРИБОР НЕ РАБОТАЛ» И «ПЕРЕСЕЧЕНИЙ НЕТ» — РАЗНЫЕ ОТВЕТЫ.

        При включённом флаге молчание НЕВОЗМОЖНО по построению: каждый исход
        несёт `status` и текст. Чистый результат обязан нести ЗНАМЕНАТЕЛЬ —
        сколько тел вообще участвовало и скольких не видели, — иначе «находок
        0» есть утверждение ни о чём."""
        _seed(self.KEY, programs=2, ops_each=3)      # create_room: тел нет
        with _FlagOn():
            block = live_verdict.clash_only(self.KEY)
        self.assertEqual(block["status"], "ok")
        self.assertEqual(block["total_findings"], 0)
        # знаменатель на месте, и он говорит, что смотреть было НЕ НА ЧТО
        self.assertEqual(block["bodies"], 0)
        self.assertIn("НИ ОДНОГО ТЕЛА", block["message_ru"])
        self.assertIn("Это НЕ «коллизий нет»", block["message_ru"])
        self.assertIn("search_complete", block)

    def test_a_refusal_names_its_phase_instead_of_reporting_zero(self):
        os.environ["KUKAI_IR_CLASH_MAX_ELEMENTS"] = "16"
        try:
            _seed_walls(self.KEY, programs=4, walls_each=20)
            with _FlagOn():
                block = live_verdict.clash_only(self.KEY)
        finally:
            os.environ.pop("KUKAI_IR_CLASH_MAX_ELEMENTS", None)
        self.assertEqual(block["status"], "over_cap")
        self.assertIn("phase", block)
        self.assertNotIn("total_findings", block)   # числа находок НЕТ вовсе
        self.assertIn("не смотрели", block["message_ru"])

    def test_bulk_door_stamps_clash_under_its_own_key(self):
        """Блок едет под именем `clash`, а НЕ внутрь `building`: ключ
        `building` на двери без вердикта прочитался бы как «здание судили»."""
        _seed(self.KEY, programs=3)
        receipt = {"ok": True, "message_ru": "построено"}
        from kukai.ir import serving
        with _FlagOn():
            asyncio.run(serving._stamp_building_clash(receipt, (self.KEY, 0)))
        self.assertIn("clash", receipt)
        self.assertNotIn("building", receipt)

    def test_reading_turn_stamps_nothing(self):
        """Читающий ход зданию не принадлежит (замер 29.07: 176 чтений на 5
        записей). Журнал не вырос — сказать нечего."""
        _seed(self.KEY, programs=3)
        grown = live_verdict.programs_seen(self.KEY)
        receipt = {"ok": True}
        from kukai.ir import serving
        with _FlagOn():
            asyncio.run(serving._stamp_building_clash(receipt, (self.KEY, grown)))
        self.assertEqual(receipt, {"ok": True})

    def test_clash_never_refuses_the_write(self):
        """ЛОЖНЫЙ ОТКАЗ ВЕРНОЙ ПОСТРОЙКЕ СТОИТ ДОРОЖЕ ПРОПУЩЕННОЙ НАХОДКИ.
        Сломанный аудит не имеет права стоить хода, в котором Revit уже
        пишет: ни `ok`, ни `err` штамп не трогает даже когда падает."""
        _seed(self.KEY, programs=3)
        receipt = {"ok": True, "message_ru": "построено"}
        before = _sha(receipt)
        from kukai.ir import serving
        broken = live_verdict.clash_only

        def explode(_key):
            raise RuntimeError("аудит сломан")

        live_verdict.clash_only = explode
        try:
            with _FlagOn():
                out = asyncio.run(
                    serving._stamp_building_clash(receipt, (self.KEY, 0)))
        finally:
            live_verdict.clash_only = broken
        self.assertIs(out, receipt)
        self.assertEqual(_sha(receipt), before)
        self.assertTrue(receipt["ok"])


class FlagOffChangesNotOneByte(unittest.TestCase):
    """ЗАМЕР 10.08.2026 (`/tmp/wiring/m_flagoff.py`), два настоящих здания,
    материализованных из разбора, при ОТСУТСТВУЮЩЕМ `KUKAI_IR_CLASH` — то
    есть в состоянии прода:

        sob62_r23_v5     (9 программ, 1 043 операции)
            до правки sha(verdict.judge) = 7bcd555a…b51e, message_ru 353 симв.
            после                        = 7bcd555a…b51e, message_ru 353 симв.
        snowdon_plumb_v4 (30 чанков, 7 500 операций — ВЫШЕ потолка вердикта)
            до правки sha = dbde8fa6…15e0, message_ru 359 симв.
            после         = dbde8fa6…15e0, message_ru 359 симв.
    """

    KEY = ("test-clash-flag-off", "")

    def tearDown(self):
        live_journal.reset(self.KEY)

    def test_clash_only_is_silent(self):
        _seed(self.KEY, programs=5)
        with _FlagOff():
            self.assertIsNone(live_verdict.clash_only(self.KEY))

    def test_bulk_stamp_adds_no_key_and_no_byte(self):
        _seed(self.KEY, programs=5)
        receipt = {"ok": True, "message_ru": "построено", "kir": True}
        before = _sha(receipt)
        from kukai.ir import serving
        with _FlagOff():
            asyncio.run(serving._stamp_building_clash(receipt, (self.KEY, 0)))
        self.assertEqual(_sha(receipt), before)
        self.assertNotIn("clash", receipt)

    def test_verdict_receipt_is_unchanged_over_the_ceiling_too(self):
        """Перестановка `_clash_block` перед потолком вердикта не имеет права
        менять ни байта при выключенном флаге — включая ветку самого
        потолка, где приклеивание теперь появилось."""
        os.environ["KUKAI_KIR_BUILDING_VERDICT_OPS"] = "20"
        try:
            _seed(self.KEY, programs=40, ops_each=4)
            with _FlagOff():
                block = live_verdict.judge(self.KEY)
        finally:
            os.environ.pop("KUKAI_KIR_BUILDING_VERDICT_OPS", None)
        self.assertNotIn("clash", block)
        self.assertIn("НЕ СЧИТАЛСЯ", block["message_ru"])


class TheSeparatorsAreOneFact(unittest.TestCase):
    """Адрес находки о коллизии и адрес, который разрешает ссылку на хозяина,
    обязаны вести в одну строку скрипта. Два литерала `"/"` в двух модулях
    разошлись бы молча — и разошлись бы на самой адресации."""

    def test_bundle_separator_is_the_same_in_both_modules(self):
        self.assertEqual(J._BUNDLE_SEP, clash_bundle._BUNDLE_SEP)

    def test_segment_separator_is_the_same_in_both_modules(self):
        self.assertEqual(J._SEGMENT_SEP, clash_bundle._SEGMENT_SEP)


class TheHostIndexRidesTheBundle(unittest.TestCase):
    """Ребро хозяина строит тот, кто разложил пачку, — второй разрешатель
    ссылок рядом с судьёй разошёлся бы с `bundle_oid` на первой правке."""

    def test_bundle_elements_publishes_the_edge(self):
        pack = [{"ops": [
            {"op": "create_wall", "id": "w1", "p0_mm": [0, 0, 0],
             "p1_mm": [1000, 0, 0]},
            {"op": "create_door", "id": "d1",
             "host": {"by": "ref", "value": "w1"}},
        ]}]
        geo = clash_bundle.bundle_elements(pack)
        self.assertIn("p1/d1", geo.hosted)
        self.assertEqual(geo.hosted["p1/d1"]["host_element_id"], "p1/w1")
        self.assertEqual(geo.hosted["p1/d1"]["host_class"], "create_wall")

    def test_empty_bundle_gives_an_EMPTY_index_not_a_missing_one(self):
        """«Спросили, хозяев не объявлено» и «не спрашивали» — разные факты, и
        на этом пути второго не бывает никогда."""
        geo = clash_bundle.bundle_elements([{"ops": [
            {"op": "create_wall", "id": "w1"}]}])
        self.assertEqual(geo.hosted, {})
        self.assertIsNotNone(geo.hosted)


if __name__ == "__main__":
    unittest.main()
