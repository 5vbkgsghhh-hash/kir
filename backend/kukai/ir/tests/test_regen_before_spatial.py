"""Регенерация перед пространственным опом: правило ВЫВОДИТСЯ, а не ведётся.

═══ ЧТО БЫЛО СЛОМАНО, И КАК ЭТО ЗАМЕРЕНО ═══

Правило вооружал ТОЛЬКО `create_wall`, а потребляли его `create_room` и
`create_space`. Значит программа, которая замыкает контур РАЗДЕЛИТЕЛЕМ и
ставит в него комнату, регенерации не получала. Замер по эмиссии (11.08,
маркеры опов, версия 2026):

    разделитель RS1 на позиции 2645, комната R1 на 5534,
    `doc.Regenerate()` между ними ОТСУТСТВУЕТ
    (контроль: стена W1 на 2570, комната R1 на 3717, регенерация на 3647)

═══ ПОЧЕМУ ЭТО НЕ СПИСОК ОГРАНИЧИВАЮЩИХ ОПОВ ═══

Соблазн был спросить реестр: чей результат ограничивает комнату. Замер по
шести сборкам эту дорогу закрывает — ЕДИНСТВЕННЫЙ `BuiltInParameter`,
называющий ограничение комнаты, это `WALL_ATTR_ROOM_BOUNDING` (6/6). Ни у
разделителя, ни у перекрытия, ни у потолка, ни у кровли такого параметра
нет: они ограничивают по своей природе. Спросить элемент «ограничиваешь ли
ты» НЕЧЕМ, значит список пришлось бы вести руками — и он протух бы на первом
же новом опе, причём МОЛЧА.

Правило поэтому опирается на факт, который провенанс (a63d5c13) уже замерил
и который к ограничению комнат отношения не имеет: «свежая стена без граней
ДО регенерации», то есть только что созданный элемент не реализован в
документе целиком, пока не позвали `doc.Regenerate()`. `NewRoom`/`NewSpace`
разрешают объемлющую область В МОМЕНТ ВЫЗОВА. Значит вооружает правило ЛЮБОЕ
создание с прошлой регенерации.

═══ ЧЕГО ЭТОТ ТЕСТ НЕ ДОКАЗЫВАЕТ ═══

Он доказывает, что КОМПИЛЯТОР ставит регенерацию там, где раньше не ставил.
Он НЕ доказывает, что Revit без неё построил бы комнату неверно: живого
Revit у этой волны не было, а провенанс замерен на ДРУГОМ опе (грани стены
для размера). Правило выбрано по НЕСИММЕТРИИ ЦЕНЫ — лишняя регенерация стоит
времени, пропущенная стоит ОТКАТА ВЕРНОЙ ПРОГРАММЫ (комната прочитает
Area == 0 и свидетель уронит всё), — а не по доказанному отказу.
"""
from __future__ import annotations

import os
import re
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(),
                                   "kir_regen_queue.jsonl"))

from kukai.ir import authoring, ops_room, spec                   # noqa: E402
from kukai.ir.compiler import compile_program                    # noqa: E402
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT as SNAPSHOT  # noqa: E402

LVL = {"by": "name", "value": SNAPSHOT["levels"][0]["name"]}
RING = [[0, 0], [4000, 0], [4000, 3000], [0, 3000], [0, 0]]
REGEN = "doc.Regenerate();  // finalize"


def _emit(ops, ver="2026"):
    out = compile_program({"ir_version": "1.0", "intent": "regen", "ops": ops},
                          revit_version=ver, snapshot=SNAPSHOT, bulk=True)
    assert out.ok, [d.code for d in out.diagnostics]
    return out.csharp


def _at(cs, op_id):
    """Позиция блока опа. ЦЕЛЫМ ТОКЕНОМ, а не подстрокой: `// create_room`
    находится ВНУТРИ `// create_room_separator`, и первая версия этой пробы
    сравнила подстроку с её же префиксом, получив «оба на 2649»."""
    m = re.search(r"^\s*// \S+ " + re.escape(op_id) + r"\s*$", cs, re.M)
    return m.start() if m else -1


class TheGapThatWasOpen(unittest.TestCase):
    """Опровергающие: до правки первый падал, второй проходил."""

    def test_a_separator_now_arms_the_rule(self):
        cs = _emit([
            {"op": "create_room_separator", "id": "RS1", "path": RING,
             "level": LVL},
            {"op": "create_room", "id": "R1", "xy": [2000, 1500],
             "level": LVL}])
        sep, room, regen = _at(cs, "RS1"), _at(cs, "R1"), cs.find(REGEN)
        self.assertGreater(regen, sep,
                           "регенерация обязана стоять ПОСЛЕ разделителя")
        self.assertLess(regen, room,
                        "регенерация обязана стоять ДО комнаты")

    def test_a_wall_still_arms_it_exactly_as_before(self):
        cs = _emit([
            {"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
             "p1_mm": [4000, 0], "level": LVL},
            {"op": "create_room", "id": "R1", "xy": [2000, 1500],
             "level": LVL}])
        self.assertLess(_at(cs, "W1"), cs.find(REGEN))
        self.assertLess(cs.find(REGEN), _at(cs, "R1"))

    def test_a_space_gets_the_same_treatment_as_a_room(self):
        cs = _emit([
            {"op": "create_room_separator", "id": "RS1", "path": RING,
             "level": LVL},
            {"op": "create_space", "id": "SP1", "xy": [2000, 1500],
             "level": LVL}])
        self.assertLess(_at(cs, "RS1"), cs.find(REGEN))
        self.assertLess(cs.find(REGEN), _at(cs, "SP1"))

    def test_a_spatial_op_with_nothing_before_it_gets_no_regen(self):
        """Регенерация без причины — лишняя работа в транзакции, и её
        отсутствие здесь держит правило от превращения в «всегда»."""
        cs = _emit([{"op": "create_room", "id": "R1", "xy": [2000, 1500],
                     "level": LVL}])
        self.assertEqual(cs.find(REGEN), -1)


class TheRuleIsDerivedNotListed(unittest.TestCase):
    """Обе стороны правила выводятся из реестра, поэтому новый оп попадает
    под него САМ — либо роняет прогон, если решение о нём не принято."""

    def test_the_consumer_side_comes_from_result_categories(self):
        derived = {name for name, cats in spec.OP_RESULT_CATEGORIES.items()
                   if set(cats) & set(ops_room.SPATIAL_ENCLOSURE_CATEGORIES)}
        self.assertEqual(authoring._SPATIAL_ENCLOSURE_OPS, derived)
        self.assertEqual(derived, {"create_room", "create_space"})

    def test_every_spatial_category_op_is_in_the_consumer_set(self):
        """ЗАКРЫТИЕ СПИСКА. Оп, чей результат — пространственный элемент, но
        которого нет в правиле, строил бы помещение по НЕРЕГЕНЕРИРОВАННОЙ
        модели, и увидеть это можно было бы только откатом верной
        программы."""
        for name, cats in sorted(spec.OP_RESULT_CATEGORIES.items()):
            if set(cats) & set(ops_room.SPATIAL_ENCLOSURE_CATEGORIES):
                with self.subTest(op=name):
                    self.assertIn(name, authoring._SPATIAL_ENCLOSURE_OPS)

    def test_the_arming_side_is_every_model_writing_op(self):
        """Вооружать обязано ЛЮБОЕ создание, а не только стена: провенанс
        правила — «свежий элемент не реализован до регенерации», и это факт
        не про стены."""
        armers = []
        for name, op_spec in sorted(spec.OPS.items()):
            if not op_spec.writes_model or name in authoring._SPATIAL_ENCLOSURE_OPS:
                continue
            armers.append(name)
        self.assertGreater(len(armers), 50,
                           "вооружающих опов должно быть много — правило "
                           "перестало быть про стену")

    def test_the_eight_bounding_ops_the_old_rule_missed(self):
        """Замер 11.08: восемь родов реестра строят ограничивающие комнату
        элементы, а вооружал правило ровно один. Список — СЛЕДСТВИЕ замера, и
        держится тестом, чтобы «починили одно» не читалось как «починили»."""
        BOUNDING = {"OST_RoomSeparationLines", "OST_Floors", "OST_Ceilings",
                    "OST_Roofs", "OST_Columns", "OST_StructuralColumns",
                    "OST_BuildingPad"}
        missed = {name for name, cats in spec.OP_RESULT_CATEGORIES.items()
                  if set(cats) & BOUNDING and name != "create_wall"}
        self.assertGreaterEqual(len(missed), 8, sorted(missed))
        for name in sorted(missed):
            with self.subTest(op=name):
                self.assertTrue(spec.OPS[name].writes_model)

    def test_room_bounding_is_not_readable_from_the_api(self):
        """ПОЧЕМУ ПРАВИЛО НЕ СПРАШИВАЕТ МОДЕЛЬ. Замер по шести сборкам:
        единственный BuiltInParameter про ограничение комнаты —
        WALL_ATTR_ROOM_BOUNDING. Если однажды появится общий, это правило
        можно будет заменить вопросом К МОДЕЛИ, и вот тогда список исчезнет
        совсем. Тест держит основание решения, а не само решение."""
        self.assertEqual(ops_room.SPATIAL_ENCLOSURE_CATEGORIES,
                         ("OST_Rooms", "OST_MEPSpaces"))


class TheStoredCorpusCoversTheGap(unittest.TestCase):

    def test_a_golden_program_exercises_the_separator_path(self):
        """До 11.08 НИ ОДИН эталон не строил комнату без стены, поэтому
        правка правила прошла без сдвига байтов у всех 52 эталонов — то есть
        корпус дыру не покрывал вовсе."""
        from kukai.ir.tests.test_golden import PROGRAMS
        self.assertIn("room_separator_then_room", PROGRAMS)
        ops = [o["op"] for o in PROGRAMS["room_separator_then_room"]["ops"]]
        self.assertEqual(ops, ["create_room_separator", "create_room"])
        self.assertNotIn("create_wall", ops)


if __name__ == "__main__":
    unittest.main()