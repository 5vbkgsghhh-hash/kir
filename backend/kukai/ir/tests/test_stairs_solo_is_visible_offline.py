"""ПРАВИЛО, ДОСТИЖИМОЕ ТОЛЬКО НА ЖИВОМ УСТРОЙСТВЕ, — ЭТО ПОЛОВИНА ПРАВИЛА.

`create_stairs` обязан быть единственным опом своей программы: его
`StairsEditScope` владеет собственными транзакциями и не вкладывается в общую
транзакцию программы. Это ФАКТ REVIT API, а не наша прихоть, и запрет верен.

ДЕФЕКТ, ЗАМЕРЕННЫЙ 04.08 — не в запрете, а в том, ГДЕ он жил. Ровно в одном
месте: `authoring.emit_program`, то есть ПОСЛЕ заземления. Значит песочница
программу собирала, `plan_program` принимал её МОЛЧА, и о стене модель узнавала
только на живом устройстве, где круглый рейс стоит дороже всего:

    plan_program({"ops": [create_stairs, create_wall]})  ->  ПРИНЯЛ

Правило это о ФОРМЕ ПРОГРАММЫ, а не о документе: чтобы его проверить, Revit не
нужен вовсе. Теперь оно стоит и на плане (`compiler.plan_program`, читая
`spec.SOLO_OPS`), а отказ эмиттера ОСТАЁТСЯ дословно там, где был, — последним
рубежом, а не дублем.

ВТОРАЯ ПОЛОВИНА ЗАКОНА — в `test_verdict_takes_kir_ops.py`: раз лестница
обязана быть отдельной программой, то и судить надо ПАЧКУ программ, иначе
многоэтажное здание непригодно по построению.

Прогон: KUKAI_CHECKER_V2=1 venv/bin/python3.12 -m pytest \
        kukai/ir/tests/test_stairs_solo_is_visible_offline.py -q
"""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("KUKAI_CHECKER_V2", "1")

from kukai.ir import authoring, spec  # noqa: E402
from kukai.ir.compiler import compile_program  # noqa: E402
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT as SNAPSHOT  # noqa: E402

STAIRS = {"op": "create_stairs", "id": "S1",
          "p0_mm": [0, 0], "p1_mm": [0, 3000],
          "base_level": {"by": "name", "value": "Этаж 1"},
          "top_level": {"by": "name", "value": "Этаж 2"},
          "width_mm": 1200}
WALL = {"op": "create_wall", "id": "W1", "p0_mm": [0, 0], "p1_mm": [5000, 0],
        "level": {"by": "name", "value": "Этаж 1"}, "height_mm": 3000}


def _prog(ops):
    return {"ir_version": "1.0", "intent": "тест", "ops": ops}


class SoloOpVisibleOffline(unittest.TestCase):

    def test_a_neighbour_is_refused_at_plan_time(self):
        """Собственно починка: отказ БЕЗ живого Revit."""
        out = compile_program(_prog([STAIRS, WALL]), snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-L002", [d.code for d in out.diagnostics])

    def test_it_does_not_matter_which_side_the_neighbour_is_on(self):
        """Порядок опов не должен решать: правило о СОСТАВЕ программы."""
        out = compile_program(_prog([WALL, STAIRS]), snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-L002", [d.code for d in out.diagnostics])

    def test_even_a_level_is_a_neighbour(self):
        """Уровень рядом с лестницей — самое естественное, что напишет модель,
        и именно оно молча проходило план. Уровень принадлежит программе ТЕЛА,
        а лестница адресует его по имени."""
        level = {"op": "create_level", "id": "L1", "elev_mm": 0,
                 "name": "Этаж 1"}
        out = compile_program(_prog([level, STAIRS]), snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-L002", [d.code for d in out.diagnostics])

    def test_the_refusal_says_where_to_put_the_rest(self):
        """Запрет без выхода — тупик. В замере 03.08 сильная модель согласилась
        с правилом, написала это в своём же скрипте — и слепила лестницу из 15
        `create_floor`, потому что не знала, КУДА деть остальное. Отказ обязан
        назвать ПАЧКУ и способ адресовать уровень через её границу."""
        out = compile_program(_prog([STAIRS, WALL]), snapshot=SNAPSHOT)
        text = " ".join(d.message_ru for d in out.diagnostics
                        if d.code == "KIR-L002")
        self.assertIn("ПАЧКА", text)
        self.assertIn("ИМЕНИ", text)

    def test_the_solo_program_itself_still_compiles(self):
        """Запрет обязан быть УСЛОВНЫМ: правило, отказывающее всегда, — это
        удалённая способность, а не правило."""
        out = compile_program(_prog([STAIRS]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.code for d in out.diagnostics])

    def test_an_ordinary_program_is_untouched(self):
        """И соседство само по себе законно — солист тут ни при чём."""
        out = compile_program(_prog([WALL, dict(WALL, id="W2")]),
                              snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.code for d in out.diagnostics])

    def test_the_emitter_keeps_its_own_last_line_of_defence(self):
        """Дубль НАМЕРЕННЫЙ. `emit_program` — публичная функция: она обязана
        отказывать сама, а не полагаться на то, что до неё дошли через план."""
        grounded = [
            dict(STAIRS, base_level={"via": "element_id", "id": 1},
                 top_level={"via": "element_id", "id": 2}),
            dict(WALL, level={"via": "element_id", "id": 1}),
        ]
        with self.assertRaises(Exception) as caught:
            authoring.emit_program(grounded, "2023")
        codes = [d.code for d in getattr(caught.exception, "diagnostics", ())]
        self.assertIn("KIR-L002", codes)

    def test_the_rule_reads_the_registry_not_a_hardcoded_name(self):
        """ОДИН ФАКТ — ОДНО МЕСТО. До 04.08 «create_stairs солист» было
        написано трижды: хардкод в эмиттере, приватный `_SOLO_OPS` в
        `decompile/materialize.py` и проза. Факт, сказанный в трёх местах,
        расходится в двух из них."""
        self.assertIn("create_stairs", spec.SOLO_OPS)
        for name in spec.SOLO_OPS:
            self.assertIn(name, spec.OPS,
                          "правило о несуществующем опе никто не применяет")
        from kukai.ir.decompile import materialize
        self.assertIs(materialize._SOLO_OPS, spec.SOLO_OPS)


if __name__ == "__main__":
    unittest.main()
