"""Синтетические поля компилятора: ОДНА власть, пятеро читателей.

ЧТО ЭТО ЗА ПОЛЕ И ПОЧЕМУ ТЕСТ. `__host_wall__` — форма хоста, снятая планом
с настоящей стены той же программы и переданная эмиттеру. Автор его написать
не может: у языка нет такого слота. До 12.08.2026 имя жило ЛИТЕРАЛОМ в
четырёх местах — писатель `compiler.hosted_offset_check` и трое читателей
(`midend`, `effects`, `authoring`), — и ничто не заставляло их совпадать.

**ЦЕНА ПРОБЕЛА БЫЛА НЕ КОСМЕТИЧЕСКОЙ.** Пятое место, где поле обязаны были
знать, литерала не имело вовсе — разбор опа (`compiler._validate_op`).
Члены группы проходят план ДВАЖДЫ (второй раз из `ground._ground_members`),
первый проход поле приделывал, второй отказывал ему KIR-P003 «неизвестное
поле». Итог: **этаж со стенами И дверьми не собирался в группу ВООБЩЕ** —
`KIR-T001`, — при том что 41.1% элементов настоящей башни живут в группах.

РОД СПИСКА: `SYNTHETIC_FIELDS` — **ЗАКРЫТЫЙ, НЕ ПОЛНЫЙ ПО ПОСТРОЕНИЮ.**
Вычислить его не у кого: синтетическое поле появляется тогда, когда кто-то
пишет присваивание в опе, а не когда его объявляют. Поэтому полноту держит
не вывод, а `test_no_second_authority_hides_in_the_tree`: литерал такого
имени в не-тестовом дереве разрешён РОВНО ОДИН, и он в самой власти.
Заведёт кто-то второе синтетическое поле литералом — тест покраснеет.
"""
from __future__ import annotations

import pathlib
import re
import unittest

from kukai.ir import compiler, sandbox, spec
from kukai.ir.tests.test_course import GROUND_SNAPSHOT, POLICY, _program

IR_ROOT = pathlib.Path(__file__).resolve().parents[1]

LVL = {"by": "name", "value": "Этаж 1"}
WALL = {"op": "create_wall", "id": "w1", "p0_mm": [0, 0], "p1_mm": [5000, 0],
        "level": LVL, "height_mm": 3000}
#: Подделка НАМЕРЕННО далеко от настоящей стены: если она хоть раз доедет до
#: эмиттера, координата 999000 встанет в C# и её ни с чем не спутать.
FORGED = {"p0_mm": [999000, 999000], "p1_mm": [999000, 1000000]}


def _program_json(ops):
    return {"ir_version": spec.IR_VERSION, "intent": "контроль", "ops": ops}


class TheAuthorityIsSingle(unittest.TestCase):
    def test_every_owner_is_a_real_op(self):
        for field, owners in spec.SYNTHETIC_FIELDS.items():
            self.assertTrue(owners, f"{field}: владельцев ноль — запись мёртвая")
            for op in owners:
                self.assertIn(op, spec.OPS,
                              f"{field}: владелец {op!r} не оп реестра")

    def test_no_synthetic_name_collides_with_a_registry_slot(self):
        """Синтетическое имя не должно пересекаться с авторским слотом.

        Иначе снятие на разборе съело бы поле, которое автор ВПРАВЕ подать,
        и это был бы молча-неверный исход вместо отказа.
        """
        slots = {p.name for op in spec.OPS.values() for p in op.params}
        for field in spec.SYNTHETIC_FIELDS:
            self.assertNotIn(field, slots,
                             f"{field} совпал с параметром реестра")

    def test_no_second_authority_hides_in_the_tree(self):
        """Литерал имени разрешён РОВНО ОДИН — в самой власти.

        КОНТРОЛЬ-FAIL этого теста: верните литерал в любой из пяти площадок
        (`midend`, `effects`, `authoring`, `compiler` × 2) — счёт станет 2.
        """
        for field in spec.SYNTHETIC_FIELDS:
            needle = f'"{field}"'
            hits = []
            for path in IR_ROOT.rglob("*.py"):
                if "tests" in path.parts:
                    continue
                text = path.read_text(encoding="utf-8")
                if needle in text:
                    hits.append(
                        f"{path.relative_to(IR_ROOT)}:{text.count(needle)}")
            self.assertEqual(
                hits, [f"registry_base.py:1"],
                f"{field}: литерал имени обязан быть ровно один и в власти; "
                f"нашлось: {hits}")


class TheFieldCannotBeSuppliedFromOutside(unittest.TestCase):
    """Разбор поле СНИМАЕТ, а план выводит его заново из настоящей стены.

    🔴 ГРАНИЦА ПЕРВОГО ТЕСТА, НАЗВАННАЯ ЧЕСТНО, ПОТОМУ ЧТО ИМЯ ОБЕЩАЕТ ШИРЕ.
    Он показывает, что подделка НЕ доезжает до эмиттера. Он НЕ показывает,
    что этим мы обязаны снятию: мутация «принимать поле вместо снятия»
    оставила все шесть тестов зелёными — на этом пути `hosted_offset_check`
    всё равно перезаписывает значение настоящей стеной, поэтому accept и
    strip тут НЕРАЗЛИЧИМЫ. Проверено прямой мутацией, а не рассуждением.

    Значит выбор снятия обоснован не этим тестом, а порядком лекарств
    (`registry_base.SYNTHETIC_FIELDS`): перевывод происходит на двух
    площадках, и обе с условием, а путь вне обоих условий не построен и в
    недостижимости не доказан. Тест держит СЛЕДСТВИЕ, и это тоже работа —
    но пусть никто не читает его как доказательство необходимости снятия.
    """

    def test_a_forged_host_shape_never_reaches_the_emitter(self):
        door = {"op": "create_door", "id": "d1",
                "host": {"by": "ref", "value": "w1"}, "offset_mm": 1500,
                spec.SYNTHETIC_HOST_WALL: FORGED}
        res = compiler.compile_program(
            _program_json([WALL, door]), revit_version="2024",
            snapshot=GROUND_SNAPSHOT, bulk=True)
        self.assertTrue(res.ok, [d.message_ru for d in (res.diagnostics or [])])
        cs = res.csharp or ""
        self.assertNotIn("999000", cs, "подделка доехала до эмиттера")
        self.assertIn("5000", cs, "настоящая стена не доехала — зонд слеп")

    def test_the_field_on_a_non_owner_op_is_still_refused(self):
        """КОНТРОЛЬ-FAIL к снятию: снимаем ТОЛЬКО у владельцев.

        `__host_wall__` на `create_wall` не принадлежит никому, и KIR-P003
        обязан остаться — иначе снятие превратилось бы в глушилку отказов.
        """
        bad = dict(WALL)
        bad[spec.SYNTHETIC_HOST_WALL] = FORGED
        res = compiler.compile_program(
            _program_json([bad]), revit_version="2024",
            snapshot=GROUND_SNAPSHOT, bulk=True)
        self.assertFalse(res.ok)
        codes = {d.code for d in (res.diagnostics or [])}
        self.assertIn("KIR-P003", codes)


class AFloorWithDoorsIsOneGroup(unittest.TestCase):
    """ЗАКРЫВАЮЩЕЕ ЧИСЛО `KIR-T001`.

    Дверь адресует свою стену только через `ref`; пока член группы не мог
    сослаться на соседа, этаж со стенами И дверьми был негруппируем ПО
    ПОСТРОЕНИЮ, и оставалось перечисление, упирающееся в потолок 300.
    """

    SCRIPT = ('LVL = {"by": "name", "value": "Этаж 1"}\n'
              'with unit("Блок", placements=[(3000, 0), (6000, 0)]):\n'
              '    w = create_wall(p0_mm=(0, 0), p1_mm=(5000, 0), '
              'level=LVL, height_mm=3000)\n'
              '    create_door(host=w, offset_mm=1500)\n'
              '    create_window(host=w, offset_mm=3500, sill_mm=900)\n')

    def test_it_compiles_on_every_version(self):
        result = sandbox.execute_author_script(self.SCRIPT, policy=POLICY)
        self.assertTrue(result.ok,
                        result.refusal and result.refusal.render())
        program = _program(result)
        for version in spec.REVIT_VERSIONS:
            with self.subTest(version=version):
                res = compiler.compile_program(
                    program, revit_version=version,
                    snapshot=GROUND_SNAPSHOT, bulk=True)
                self.assertTrue(
                    res.ok,
                    [d.message_ru for d in (res.diagnostics or [])])
                names = set(re.findall(r"__el_[A-Za-z0-9_]+", res.csharp or ""))
                # Три члена, каждый в пространстве имён своей группы.
                self.assertEqual(
                    len({n for n in names if "__m__" in n}), 3, sorted(names))


if __name__ == "__main__":
    unittest.main()
