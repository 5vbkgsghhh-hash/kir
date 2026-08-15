"""МЕЖПОЛЕВОЕ ПРАВИЛО ОБЪЯВЛЕНО АВТОРУ — И ОБЪЯВЛЕНИЕ СВЕРЕНО С ПОВЕДЕНИЕМ.

ЗАЧЕМ ЭТОТ ФАЙЛ. Реестр выражает обязательность ОДНОГО поля
(`ParamSpec.required`). Правила вида «`xyz` ЛИБО `p0_mm`/`p1_mm`, и от выбора
зависит, нужен ли `level` или `host`» он выразить не умеет: у `OpSpec`
одиннадцать полей, и ни одно не описывает отношения между параметрами
(замерено 13.08.2026, аудит оси языка). Такие правила живут рукописными
ветвями `compiler._parse_and_check_internal`.

ЧТО БЫЛО ДО. Правило не доезжало до автора НИ ОДНИМ каналом:

    схема (носится каждый ход)   `place_family` → required: ['op']
    описание инструмента          слово `xyz` — 0 раз на 28 218 символов
    `course.spec("place_family")` все 14 параметров как «необязательный»

Третья строка — не пробел, а ЛОЖНОЕ УТВЕРЖДЕНИЕ в тексте, который мы сами
зовём контрактом: он говорил ОБРАТНОЕ правилу. Автор (а главный автор здесь —
ЛЛМ) узнавал правило только отказом, круговым рейсом на каждое.

ЧТО ЗАКРЕПЛЕНО ЗДЕСЬ. Проза правила переехала в `tool_doc.OP_NOTES`, откуда её
печатает `spec(<оп>)` под заголовком «ЛОВУШКА ЭТОГО ОПА». Проза — ВТОРОЙ
экземпляр правила, живущего в компиляторе, и держать её честной обязан не
человек, а этот файл: **каждое правило обязано ОТКАЗЫВАТЬ названным кодом на
нарушающей программе И ПРОПУСКАТЬ законную.** Первое доказывает, что правило
живо; второе — что зонд способен быть зелёным не по построению (форма 8
канона: у каждого зонда обе половины).

ГРАНИЦА, СЛОВАМИ. Файл проверяет ПЛАН (`compiler.plan_program`) — то есть
стадию, на которой эти правила и стоят. Он не проверяет ни заземление, ни
эмиссию, ни поведение Ревита. И он не утверждает, что межполевых правил ровно
шесть: шесть — те, что сняты прогоном 13.08 и потому объявлены. Верхняя оценка
того же дня — 23 опа и 47 шаблонов отказа; между ними разрыв, и он назван.

ЧЕГО ЗДЕСЬ НЕТ НАМЕРЕННО. `create_opening`: программа с `variety="host_face"`
и БЕЗ формы вовсе план ПРОХОДИТ (замерено 13.08). Пока отказа нет, писать про
него прозу значило бы записать заметку по памяти вместо выписки из кода.
"""

from __future__ import annotations

import unittest

from kukai.ir import compiler, spec
from kukai.ir.dsl import OP_FUNCTIONS
from kukai.ir.tool_doc import OP_NOTES

_LVL = {"by": "element_id", "value": 100}
_LVL2 = {"by": "element_id", "value": 101}
_SYM = {"by": "element_id", "value": 200}
_WALL = {"op": "create_wall", "id": "W1", "p0_mm": [0, 0], "p1_mm": [5000, 0],
         "height_mm": 3000, "level": _LVL}

#: (оп, ярлык нарушения, код отказа, нарушающие опы, законные опы).
#:
#: Коды и тексты СНЯТЫ ПРОГОНОМ 13.08.2026, а не выписаны из памяти: каждая
#: строка ниже сначала была запущена, и только потом про неё написана проза в
#: `OP_NOTES`. Порядок именно такой, потому что обратный уже стоил этому дому
#: нескольких «замеров», оказавшихся пересказом.
_RULES: tuple[tuple[str, str, str, list, list], ...] = (
    ("place_family", "положение не задано", "KIR-P007",
     [{"op": "place_family", "id": "P1", "symbol": _SYM}],
     [{"op": "place_family", "id": "P1", "symbol": _SYM,
       "xyz": [0, 0, 0], "level": _LVL}]),
    ("place_family", "положение задано дважды", "KIR-P007",
     [{"op": "place_family", "id": "P1", "symbol": _SYM, "xyz": [0, 0, 0],
       "p0_mm": [0, 0, 0], "p1_mm": [1000, 0, 0]}],
     [{"op": "place_family", "id": "P1", "symbol": _SYM,
       "xyz": [0, 0, 0], "level": _LVL}]),
    ("place_family", "точка без уровня", "KIR-P005",
     [{"op": "place_family", "id": "P1", "symbol": _SYM, "xyz": [0, 0, 0]}],
     [{"op": "place_family", "id": "P1", "symbol": _SYM,
       "xyz": [0, 0, 0], "level": _LVL}]),
    ("place_family", "кривая без хозяина", "KIR-P005",
     [{"op": "place_family", "id": "P1", "symbol": _SYM,
       "p0_mm": [0, 0, 0], "p1_mm": [1000, 0, 0], "level": _LVL}],
     [_WALL, {"op": "place_family", "id": "P1", "symbol": _SYM,
              "p0_mm": [0, 0, 0], "p1_mm": [1000, 0, 0],
              "host": {"by": "ref", "value": "W1"}}]),
    ("create_ceiling", "форма не задана", "KIR-P007",
     [{"op": "create_ceiling", "id": "CE1", "level": _LVL}],
     [{"op": "create_ceiling", "id": "CE1", "level": _LVL,
       "outline": [[0, 0], [5000, 0], [5000, 5000], [0, 5000]]}]),
    ("create_ceiling", "форма задана дважды", "KIR-P007",
     [{"op": "create_ceiling", "id": "CE1", "level": _LVL,
       "outline": [[0, 0], [5000, 0], [5000, 5000], [0, 5000]],
       "contour": {"of": [{"kind": "rect", "p0_mm": [0, 0],
                           "p1_mm": [5000, 5000]}]}}],
     [{"op": "create_ceiling", "id": "CE1", "level": _LVL,
       "outline": [[0, 0], [5000, 0], [5000, 5000], [0, 5000]]}]),
    ("create_column", "top_xy без top_level", "KIR-T002",
     [{"op": "create_column", "id": "C1", "xy": [0, 0], "level": _LVL,
       "top_xy": [500, 500]}],
     [{"op": "create_column", "id": "C1", "xy": [0, 0], "level": _LVL,
       "top_xy": [500, 500], "top_level": _LVL2}]),
    ("create_stairs", "марш не задан", "KIR-P007",
     [{"op": "create_stairs", "id": "S1", "base_level": _LVL,
       "top_level": _LVL2, "width_mm": 1200}],
     [{"op": "create_stairs", "id": "S1", "base_level": _LVL,
       "top_level": _LVL2, "width_mm": 1200,
       "p0_mm": [0, 0], "p1_mm": [3000, 0]}]),
    ("create_stairs", "марш задан дважды", "KIR-P007",
     [{"op": "create_stairs", "id": "S1", "base_level": _LVL,
       "top_level": _LVL2, "width_mm": 1200,
       "p0_mm": [0, 0], "p1_mm": [3000, 0],
       "spiral": {"center_mm": [0, 0], "radius_mm": 1500,
                  "start_angle_deg": 0, "included_angle_deg": 180,
                  "clockwise": True}}],
     [{"op": "create_stairs", "id": "S1", "base_level": _LVL,
       "top_level": _LVL2, "width_mm": 1200,
       "p0_mm": [0, 0], "p1_mm": [3000, 0]}]),
    ("create_window", "смещение за краем стены", "KIR-T002",
     [_WALL, {"op": "create_window", "id": "WD1", "symbol": _SYM,
              "host": {"by": "ref", "value": "W1"}, "offset_mm": 99000}],
     [_WALL, {"op": "create_window", "id": "WD1", "symbol": _SYM,
              "host": {"by": "ref", "value": "W1"}, "offset_mm": 2500}]),
    ("create_door", "смещение за краем стены", "KIR-T002",
     [_WALL, {"op": "create_door", "id": "D1", "symbol": _SYM,
              "host": {"by": "ref", "value": "W1"}, "offset_mm": 99000}],
     [_WALL, {"op": "create_door", "id": "D1", "symbol": _SYM,
              "host": {"by": "ref", "value": "W1"}, "offset_mm": 2500}]),
)


def _plan(ops: list) -> tuple[bool, tuple[str, ...]]:
    """(прошло?, коды отказа).

    УСПЕХ `plan_program` возвращает `PlannedProgram`, У КОТОРОГО НЕТ
    `.diagnostics`. Первая редакция этого раннера читала возникший
    `AttributeError` как отказ и печатала ДВА ПРИНЯТЫХ случая отвергнутыми —
    ровно то, из-за чего `create_opening` чуть не получил прозу про правило,
    которого на этой стадии нет.
    """
    try:
        compiler.plan_program({"ir_version": "1.0", "ops": ops})
    except Exception as exc:  # noqa: BLE001 — предмет проверки, а не помеха
        diags = getattr(exc, "diagnostics", None) or ()
        return False, tuple(d.code for d in diags)
    return True, ()


class EveryDeclaredRuleStillRefuses(unittest.TestCase):
    """Проза правила сверена с ПОВЕДЕНИЕМ, а не с чьей-то памятью."""

    def test_the_violating_program_is_refused_with_the_named_code(self) -> None:
        for op_name, label, code, bad, _good in _RULES:
            with self.subTest(f"{op_name}: {label}"):
                ok, codes = _plan(bad)
                self.assertFalse(ok, f"{op_name} ({label}): план ПРИНЯЛ "
                                     f"программу, нарушающую объявленное "
                                     f"правило — проза разошлась с кодом")
                self.assertIn(code, codes, f"{op_name} ({label}): отказ есть, "
                                           f"но код другой: {codes}")

    def test_the_lawful_program_passes(self) -> None:
        """Контроль-PASS. Без него зелёный цвет выше не сообщает ничего:
        правило, отвергающее ВСЁ, тоже отвергнет нарушителя."""
        for op_name, label, _code, _bad, good in _RULES:
            with self.subTest(f"{op_name}: {label}"):
                ok, codes = _plan(good)
                self.assertTrue(ok, f"{op_name} ({label}): законная программа "
                                    f"отвергнута {codes} — проверять нечем")


class TheRuleReachesTheAuthor(unittest.TestCase):
    """Правило, до которого автор не может дойти, не существует."""

    def test_every_op_with_a_rule_carries_it_in_its_own_contract(self) -> None:
        for op_name in sorted({r[0] for r in _RULES}):
            with self.subTest(op_name):
                self.assertIn(op_name, OP_NOTES,
                              f"{op_name}: правило проверяется прогоном, но "
                              f"автору не объявлено ничем")
                doc = OP_FUNCTIONS[op_name].__doc__ or ""
                for note in OP_NOTES[op_name]:
                    self.assertIn(note, doc,
                                  f"{op_name}: ловушка не доехала в докстроку")

    def test_an_op_with_no_required_param_says_so_instead_of_implying_freedom(
            self) -> None:
        """Вывод, а не имя: условие проверяется у КАЖДОГО опа реестра.

        Замерено 13.08: таких опов ровно один из 69 (`place_family`). Но
        закреплено СВОЙСТВО, а не имя — следующий такой оп получит строку сам.
        """
        marker = "РЕЕСТР НЕ ОБЪЯВЛЯЕТ У ЭТОГО ОПА НИ ОДНОГО ОБЯЗАТЕЛЬНОГО"
        without_required = {
            name for name, ospec in spec.OPS.items()
            if ospec.params and not any(p.required for p in ospec.params)}
        self.assertTrue(without_required,
                        "ни одного такого опа — проверка выродилась, и её "
                        "зелёный цвет ничего не значит")
        for name, ospec in sorted(spec.OPS.items()):
            with self.subTest(name):
                doc = OP_FUNCTIONS[name].__doc__ or ""
                if name in without_required:
                    self.assertIn(marker, doc)
                else:
                    # КОНТРОЛЬ-FAIL той же строкой: у опа с обязательным
                    # параметром эта фраза была бы неправдой.
                    self.assertNotIn(marker, doc)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
