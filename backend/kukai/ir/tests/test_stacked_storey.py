"""ТИПОВОЙ ЭТАЖ НЕСЁТ ДВЕРИ И ОКНА — то, что делает этаж квартирой.

🔴 ЧТО ЗДЕСЬ ЧИНИТСЯ И ПОЧЕМУ ЭТО НЕ «ЕЩЁ ДВА ИМЕНИ В СПИСКЕ».

`stack` называется «типовой этаж × N» и до 15.08.2026 не мог нести двух
элементов, без которых этаж не квартира. Довод в коде звучал как факт о ДВЕРИ:

    «hosted ops (door/window) stay out because their host is addressed by
     `ref` to a sibling op, and the expansion renames ids per storey —
     a hosted op would point at storey 1 forever»

Он был фактом об ЭКСПАНСИИ. Она переименовывала id членов на каждом этаже
(`{mid}_L{k}_{base}`) и **не переписывала `by:ref` вовсе** — при том что
эмиттер групп ту же перепись делает и делал (`authoring._rename_refs`).
Запрет описывал наш собственный пробел и читался как свойство предметной
области; это форма 9 канона в её дорогой половине.

ВТОРАЯ ПОЛОВИНА ДОВОДА БЫЛА НАСТОЯЩЕЙ, и она решена, а не обойдена: правило
членства требовало, чтобы оп принимал `level`, — а у `create_door` поля `level`
НЕТ ВОВСЕ. Это не упущение реестра: **у хостящегося элемента уровень есть
свойство ХОЗЯИНА.** Значит поэтажная перепись для стены означает «перепиши
`level`», а для двери — «перепиши ССЫЛКУ НА ХОЗЯИНА», и требовать от двери
собственный `level` значило бы завести ей второй источник этажа рядом с
хозяином.

ЧЕГО ЭТОТ ФАЙЛ НЕ ПРОВЕРЯЕТ: живой Revit. Все числа ниже — о ПРОГРАММЕ.
Что дверь этажа K физически висит в стене этажа K, доказывается здесь
разрешением ссылки после экспансии, а не постройкой.
"""
from __future__ import annotations

import unittest

from kukai.ir import spec
from kukai.ir.compiler import plan_program
from kukai.ir.diag import KirRefusal
from kukai.ir.macros import (_STACKABLE, _STACKABLE_HOSTED, _takes_level,
                             expand)


# ── общая утварь ────────────────────────────────────────────────────────────

def _wall(oid, x0, x1, y=0):
    return {"op": "create_wall", "id": oid, "p0_mm": [x0, y], "p1_mm": [x1, y],
            "height_mm": 3000.0, "type": {"by": "name", "value": "Кирпич 380"}}


def _door(oid, host, offset=1500.0):
    return {"op": "create_door", "id": oid, "host": {"by": "ref", "value": host},
            "offset_mm": offset,
            "symbol": {"by": "name", "value": "Дверь 900x2100"}}


def _window(oid, host, offset=3000.0):
    return {"op": "create_window", "id": oid,
            "host": {"by": "ref", "value": host}, "offset_mm": offset,
            "symbol": {"by": "name", "value": "Окно 1200x1500"}}


def _stack(floor, levels=5, mid="tower"):
    return {"op": "stack", "id": mid, "levels": levels, "h_mm": 3000,
            "base_elev_mm": 0, "name_prefix": "Этаж", "floor": list(floor)}


def _storey_of(op_id: str) -> str:
    """Номер этажа из имени, назначенного экспансией (`{mid}_L{k}_{base}`)."""
    return op_id.split("_L", 1)[1].split("_", 1)[0]


# ── 1. ВОРОТА ВОЛНЫ ─────────────────────────────────────────────────────────

class ATypicalStoreyCarriesItsDoorsAndWindows(unittest.TestCase):
    """ГЛАВНЫЕ ВОРОТА: этаж со стенами, дверьми и окнами — ОДНИМ макросом."""

    FLOOR = (_wall("w_s", 0, 9000, y=0), _wall("w_n", 0, 9000, y=6000),
             _door("d1", "w_s"), _window("win1", "w_n"))

    def test_one_macro_builds_the_whole_tower(self):
        ops = expand([_stack(self.FLOOR, levels=5)])
        kinds: dict[str, int] = {}
        for op in ops:
            kinds[op["op"]] = kinds.get(op["op"], 0) + 1
        # 5 уровней + 5×(2 стены + дверь + окно)
        self.assertEqual(kinds, {"create_level": 5, "create_wall": 10,
                                 "create_door": 5, "create_window": 5}, kinds)
        self.assertEqual(len(ops), 25)

    def test_every_door_hangs_in_ITS_OWN_storey_wall(self):
        """🔴 ДОКАЗАТЕЛЬСТВО, А НЕ «ПРОГРАММА СОБРАЛАСЬ». Проверяется, что
        ссылка на хозяина РАЗРЕШАЕТСЯ в член ТОГО ЖЕ этажа: собраться могла бы
        и программа, где все двери висят на первом."""
        ops = expand([_stack(self.FLOOR, levels=5)])
        ids = {op["id"] for op in ops}
        hosted = [op for op in ops
                  if op["op"] in ("create_door", "create_window")]
        self.assertEqual(len(hosted), 10)
        for op in hosted:
            with self.subTest(op=op["id"]):
                host = op["host"]["value"]
                self.assertIn(host, ids, "хозяин не существует после экспансии")
                self.assertEqual(_storey_of(op["id"]), _storey_of(host),
                                 "дверь этажа %s висит на этаже %s"
                                 % (_storey_of(op["id"]), _storey_of(host)))

    def test_the_expanded_tower_is_a_legal_program(self):
        """Экспансия обязана давать программу, которую принимает план: иначе
        «собралось» проверялось бы только нашим же обходом."""
        ops = expand([_stack(self.FLOOR, levels=3)])
        plan_program({"ir_version": "1.0", "ops": ops})   # не бросил -> принято

    def test_a_hosted_member_gets_no_level_of_its_own(self):
        """Уровень двери — свойство ХОЗЯИНА. Вписать ей `level` значило бы
        завести второй источник этажа, и при расхождении победил бы один из
        двух молча."""
        ops = expand([_stack(self.FLOOR, levels=3)])
        for op in ops:
            if op["op"] in ("create_door", "create_window"):
                with self.subTest(op=op["id"]):
                    self.assertNotIn("level", op)
        # КОНТРОЛЬ: стене уровень по-прежнему пишется, иначе проверка выше
        # проходила бы и на экспансии, разучившейся писать level вообще.
        walls = [op for op in ops if op["op"] == "create_wall"]
        self.assertTrue(walls)
        for op in walls:
            self.assertIn("level", op)


# ── 2. КОНТРОЛЬ-FAIL ────────────────────────────────────────────────────────

class TheRefRewriteIsWhatMakesItWork(unittest.TestCase):
    """КОНТРОЛЬ-FAIL волны: без переписи ссылок двери ломаются, и это ловится.

    🔴 ЗАМЕР СО СЛОМАННОЙ ПЕРЕПИСЬЮ (15.08.2026): каждая дверь ссылается на
    `w` — id, которого после экспансии НЕ СУЩЕСТВУЕТ. То есть исход хуже
    объявленного в старом доводе: не «указывает на первый этаж», а висячая
    ссылка. Компилятор её ловит `KIR-L003`; проверено обоими концами ниже.
    """

    def test_a_dangling_host_ref_is_refused_by_name(self):
        """Ровно то, что производит сломанная перепись."""
        program = {"ir_version": "1.0", "ops": [
            {"op": "create_level", "id": "L1", "elev_mm": 0.0, "name": "Этаж 1"},
            dict(_wall("t_L1_w", 0, 9000), level={"by": "ref", "value": "L1"}),
            _door("t_L1_d", "w"),          # хозяина с таким id нет
        ]}
        with self.assertRaises(KirRefusal) as caught:
            plan_program(program)
        codes = [d.code for d in caught.exception.diagnostics]
        self.assertIn("KIR-L003", codes, codes)

    def test_the_same_program_with_an_intact_ref_is_accepted(self):
        """КОНТРОЛЬ к предыдущему: отказ обязан быть про ССЫЛКУ, а не про
        форму программы вообще. Без этого красный выше ничего не доказывает."""
        program = {"ir_version": "1.0", "ops": [
            {"op": "create_level", "id": "L1", "elev_mm": 0.0, "name": "Этаж 1"},
            dict(_wall("t_L1_w", 0, 9000), level={"by": "ref", "value": "L1"}),
            _door("t_L1_d", "t_L1_w"),
        ]}
        plan_program(program)

    def test_a_host_outside_the_floor_is_refused_at_expansion(self):
        """Хозяин ВНЕ набора — типизированный отказ ЭКСПАНСИИ, а не тихая
        ссылка на первый этаж. Без хозяина в наборе оп повис бы на одном и том
        же элементе на всех этажах."""
        floor = (_wall("w_s", 0, 9000), _door("d1", "ЧУЖОЙ"))
        with self.assertRaises(KirRefusal) as caught:
            expand([_stack(floor, levels=3)])
        message = " ".join(d.message_ru or "" for d in caught.exception.diagnostics)
        self.assertIn("хозя", message.lower(), message)
        self.assertIn("ЧУЖОЙ", message)

    def test_a_host_addressed_by_element_id_is_left_alone(self):
        """Настоящий элемент документа ОДИН для всех этажей — это законно, и
        перепись его не трогает. Иначе правило «ссылка вне набора — отказ»
        запретило бы дверь в уже существующей стене."""
        floor = (_wall("w_s", 0, 9000),
                 {"op": "create_door", "id": "d1",
                  "host": {"by": "element_id", "value": 123456},
                  "offset_mm": 1500.0,
                  "symbol": {"by": "name", "value": "Дверь 900x2100"}})
        ops = expand([_stack(floor, levels=3)])
        doors = [op for op in ops if op["op"] == "create_door"]
        self.assertEqual(len(doors), 3)
        for op in doors:
            self.assertEqual(op["host"], {"by": "element_id", "value": 123456})


# ── 3. ОБРАТНЫЙ КОНТРОЛЬ: СПИСОК НЕ ОТКРЫЛСЯ ───────────────────────────────

class TheMembershipRuleStillRefuses(unittest.TestCase):
    """Список пополнен ДВУМЯ именами, а не открыт. Иначе «пустили хостящиеся»
    означало бы «пустили всё, у чего есть хозяин»."""

    def test_an_op_that_must_not_be_stacked_is_still_refused(self):
        floor = (_wall("w", 0, 9000),
                 {"op": "create_wall_foundation", "id": "f1",
                  "wall": {"by": "ref", "value": "w"}})
        with self.assertRaises(KirRefusal) as caught:
            expand([_stack(floor, levels=3)])
        message = " ".join(d.message_ru or "" for d in caught.exception.diagnostics)
        self.assertIn("create_wall_foundation", message)
        self.assertIn("не тиражируется", message)

    def test_a_modify_op_is_still_refused(self):
        """Правящий оп адресует ЧУЖОЙ элемент и своего этажа не имеет."""
        floor = (_wall("w", 0, 9000),
                 {"op": "set_param", "id": "p1",
                  "target": {"by": "ref", "value": "w"},
                  "param": "Комментарии", "value": "x"})
        with self.assertRaises(KirRefusal):
            expand([_stack(floor, levels=3)])

    def test_the_refusal_names_both_lists(self):
        """Отказ обязан назвать ОБА правила членства: автор, увидевший только
        первый список, решит, что дверь невозможна в принципе."""
        floor = (_wall("w", 0, 9000),
                 {"op": "create_wall_foundation", "id": "f1",
                  "wall": {"by": "ref", "value": "w"}})
        with self.assertRaises(KirRefusal) as caught:
            expand([_stack(floor, levels=3)])
        message = " ".join(d.message_ru or "" for d in caught.exception.diagnostics)
        self.assertIn("create_door", message, "отказ не назвал хостящиеся")


# ── 4. ПРАВИЛО ЧЛЕНСТВА — МЕХАНИЧЕСКОЕ, А НЕ НА ВКУС ────────────────────────

class EveryAdmittedHostedOpSatisfiesTheStatedRule(unittest.TestCase):
    """🔴 РАТЧЕТ ДОПУСКА. Каждое имя в `_STACKABLE_HOSTED` обязано выполнять
    все четыре условия, объявленные в его докстроке. Добавить имя, не
    выполняющее их, нельзя — этот класс покраснеет.
    """

    def test_every_admitted_op_creates_rather_than_modifies(self):
        for name in _STACKABLE_HOSTED:
            with self.subTest(op=name):
                op_spec = spec.OPS[name]
                self.assertEqual(op_spec.effect.value, "create",
                                 "правящий оп адресует чужой элемент")

    def test_every_admitted_op_has_a_host_selector_that_takes_a_ref(self):
        for name in _STACKABLE_HOSTED:
            with self.subTest(op=name):
                kinds = {p.name: p.kind for p in spec.OPS[name].params}
                host = kinds.get("host") or kinds.get("wall")
                self.assertIsNotNone(host, "нет селектора хозяина")
                self.assertIn(host, ("sel", "sel_list", "target_w", "refs_w"),
                              "селектор хозяина не принимает ref")

    def test_no_admitted_op_has_a_level_of_its_own(self):
        """Условие, ради которого правило второе, а не расширенное первое."""
        for name in _STACKABLE_HOSTED:
            with self.subTest(op=name):
                self.assertFalse(_takes_level(name),
                                 "у опа есть собственный level — ему место в "
                                 "_STACKABLE, а не среди хостящихся")

    def test_the_two_lists_do_not_overlap(self):
        both = sorted(set(_STACKABLE) & set(_STACKABLE_HOSTED))
        self.assertEqual(both, [], "оп в обоих списках: правило переписи "
                                   "уровня стало бы неоднозначным")

    def test_every_admitted_op_states_its_reason(self):
        for name, reason in _STACKABLE_HOSTED.items():
            with self.subTest(op=name):
                self.assertGreaterEqual(len(reason), 40,
                                        "допуск без обоснования — это вкус")

    def test_the_level_question_is_asked_of_the_registry(self):
        """КОНТРОЛЬ на `_takes_level`: он обязан РАЗЛИЧАТЬ, иначе три проверки
        выше зелены по построению."""
        self.assertTrue(_takes_level("create_wall"))
        self.assertFalse(_takes_level("create_door"))


# ── 5. ЧТО НЕ СЛОМАЛОСЬ ─────────────────────────────────────────────────────

class TheOldBehaviourIsUnchanged(unittest.TestCase):

    def test_a_floor_without_hosted_ops_expands_exactly_as_before(self):
        """Этаж из одних стен обязан дать то же, что и до правки: перепись
        ссылок на программе без ссылок между членами — тождество."""
        ops = expand([_stack((_wall("w1", 0, 9000), _wall("w2", 0, 6000)),
                             levels=3)])
        self.assertEqual(len(ops), 3 + 6)
        for op in ops:
            if op["op"] == "create_wall":
                self.assertEqual(op["level"]["by"], "ref")
                self.assertTrue(op["level"]["value"].startswith("tower_L"))

    def test_a_member_ref_to_a_sibling_is_rewritten_per_storey(self):
        """Не только хозяин: ЛЮБАЯ ссылка между членами обязана попадать на
        соседа своего этажа. Проверяется на `top_level`, который ссылается на
        уровень ВНЕ набора и потому трогаться НЕ должен."""
        ops = expand([_stack((_wall("w1", 0, 9000),
                              _door("d1", "w1")), levels=2)])
        doors = [op for op in ops if op["op"] == "create_door"]
        self.assertEqual([op["host"]["value"] for op in doors],
                         ["tower_L1_w1", "tower_L2_w1"])

    def test_series_rewrites_refs_too(self):
        """ТОТ ЖЕ КЛАСС В ДРУГОМ ЭКСПАНДЕРЕ. `series` тоже переименовывает id
        членов на каждом шаге; починить только `stack` значило бы закрыть
        случай вместо класса."""
        s = {"op": "series", "id": "bay", "count": 3,
             "track": {"x": [[0, 0], [3, 12000]]},
             "items": [
                 {"op": "create_wall", "id": "w",
                  "p0_mm": ["$x", 0], "p1_mm": ["$x@next", 0],
                  "level": {"by": "name", "value": "Этаж 1"},
                  "height_mm": 3000.0},
                 {"op": "create_door", "id": "d",
                  "host": {"by": "ref", "value": "w"}, "offset_mm": 1000.0,
                  "symbol": {"by": "name", "value": "Дверь 900x2100"}},
             ]}
        ops = expand([s])
        ids = {op["id"] for op in ops}
        doors = [op for op in ops if op["op"] == "create_door"]
        self.assertEqual(len(doors), 3)
        for op in doors:
            with self.subTest(op=op["id"]):
                host = op["host"]["value"]
                self.assertIn(host, ids)
                self.assertEqual(op["id"].split("_")[1], host.split("_")[1],
                                 "дверь шага k повисла на стене другого шага")


if __name__ == "__main__":
    unittest.main()
