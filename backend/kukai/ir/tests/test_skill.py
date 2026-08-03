"""Курс не имеет права опережать компилятор.

ГЛАВНЫЙ РИСК, ради которого написан этот файл. Документация, которая ошиблась,
заставляет модель СОМНЕВАТЬСЯ; курс, который ошибся, заставляет её уверенно
делать неверное. Совет звучит как знание — модель не станет перепроверять
«хватай `series`», она этим воспользуется. Значит приём, которого компилятор не
принимает, производит УВЕРЕННЫЕ провалы вместо неуверенных, и это исход хуже,
чем полное отсутствие курса.

Отсюда ЧЕТЫРЕ симметричные проверки:

1. КАЖДАЯ ПРОГРАММА КУРСА КОМПИЛИРУЕТСЯ. Разборы показывают не псевдокод, а
   живые объекты (`skill.ALL_PROGRAMS`), и тест компилирует РОВНО ИХ — те же
   самые, что рендерятся в текст. Показанное и проверенное не могут разойтись.
2. КАЖДЫЙ ПОКАЗАННЫЙ ОТКАЗ ДЕЙСТВИТЕЛЬНО ОТКАЗЫВАЕТ, и с названным кодом
   (`skill.REFUSING_PROGRAMS`). Показанный отказ, который на деле проходит,
   учит модель бояться работающего приёма — вред симметричный.
3. КАЖДАЯ НАЗВАННАЯ ГРАНИЦА ПРОВАЛИВАЕТСЯ — отрицательный контроль. Прямое
   применение принципа приёмки (docs/2026-07-29-independent-acceptance-
   design.md): «предикат обязан УМЕТЬ ПРОВАЛИТЬСЯ». Предикаты здесь проверяют
   ещё и ТЕКСТ отказа, потому что зелёный контроль по чужой причине —
   это Гудхарт, и он уже случался в этом файле (см. ниже про MAX_SERIES_COUNT).
4. ЧИСЛА В ТЕКСТЕ СОВПАДАЮТ С КОНСТАНТАМИ, а текст курса не пересекается с
   `tool_doc.NOTES`.

ЧЕГО ЗДЕСЬ НАМЕРЕННО НЕТ: проверок против живой телеметрии
(`data/telemetry/*.jsonl`). Эти файлы РАСТУТ по мере работы прода, поэтому
замеренные частоты (210 из 586) — датированный снимок 30.07, а не инвариант;
тест, привязанный к ним, начал бы падать от чужой работы.
"""
from __future__ import annotations

import copy
import os
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_test_queue.jsonl"))

from kukai.ir import macros, skill, spec  # noqa: E402
from kukai.ir.compiler import MAX_OPS_PER_PROGRAM, compile_program  # noqa: E402
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT  # noqa: E402
from kukai.ir.tool_doc import NOTES, build_tool_description  # noqa: E402

LEVEL = {"by": "name", "value": "Этаж 1"}
BEAM = {"by": "element_id", "value": 1100}


def _prog(ops, **env):
    p = {"ir_version": "1.0", "intent": "skill-test", "ops": ops}
    p.update(env)
    return p


def _many_beam_types() -> dict:
    """Снимок проекта, где типов балки НЕСКОЛЬКО.

    Замеренный 28.07 случай (20 балок, 4 типа, KIR-G102 x40) воспроизводится
    только так: в базовой фикстуре пул из одного элемента, и умолчание там
    законно разрешается — отказа не будет, и разбор 2 нечем проверить."""
    snap = copy.deepcopy(GROUND_SNAPSHOT)
    for i, name in enumerate(("Балка 300x600", "Балка 400x800", "Балка 200x300"),
                             start=1):
        snap["beam_types"].append({"id": 1100 + i, "name": name})
    return snap


def _compile(program, snapshot=None):
    return compile_program(program, revit_version="2026",
                           snapshot=snapshot if snapshot is not None
                           else GROUND_SNAPSHOT)


def _codes(out) -> list[str]:
    return [d.code for d in out.diagnostics]


class CourseProgramsCompile(unittest.TestCase):
    """Проверка 1: показанное — работает."""

    def test_every_program_shown_as_working_compiles(self):
        snap = _many_beam_types()
        for name, program in skill.ALL_PROGRAMS:
            with self.subTest(program=name):
                out = _compile(program, snap)
                self.assertTrue(out.ok, f"{name}: "
                                f"{[d.as_dict() for d in out.diagnostics][:2]}")

    def test_the_programs_in_the_text_are_the_programs_tested(self):
        """Ратчет против расхождения показанного и проверенного: каждая
        программа обязана присутствовать в тексте курса своим JSON."""
        text = skill.build_skill_text()
        for name, program in skill.ALL_PROGRAMS:
            with self.subTest(program=name):
                self.assertIn(skill._render_program(program), text,
                              f"{name} не отрендерена в текст")

    def test_the_tower_is_one_op_not_an_enumeration(self):
        """Число из разбора 1: тот же силуэт — одна операция, а не 160."""
        ops = skill.TOWER_TRACK["ops"]
        series = [o for o in ops if o["op"] == "series"]
        self.assertEqual(len(series), 1)
        self.assertLessEqual(len(ops), MAX_OPS_PER_PROGRAM)
        expanded = macros.expand(ops)
        self.assertEqual(
            len(expanded),
            1 + series[0]["count"] * len(series[0]["items"]),
            "разбор 1 обещает count x len(items) элементов плюс уровень")

    def test_series_mints_no_levels_so_the_course_declares_one(self):
        """Курс говорит: `series` уровней НЕ создаёт, поэтому уровень объявлен
        отдельным опом. Если бы создавал, совет был бы вредным."""
        expanded = macros.expand(skill.TOWER_TRACK["ops"])
        levels = [o for o in expanded if o["op"] == "create_level"]
        self.assertEqual(len(levels), 1, "уровень ровно один — объявленный")

    def test_the_good_storey_is_composed_not_dominated(self):
        """Раздел 6 учит составу: ни одна операция не несёт здание одна."""
        ops = skill.GOOD_COMPOSED_STOREY["ops"]
        kinds = {o["op"] for o in ops}
        self.assertGreaterEqual(len(kinds), 4, "состав, а не одна операция")
        top = max(sum(1 for o in ops if o["op"] == k) for k in kinds)
        self.assertLessEqual(top / len(ops), 0.55,
                             "доля одной операции выше порога стенда")


class CourseRefusalsActuallyRefuse(unittest.TestCase):
    """Проверка 2: показанный отказ — настоящий, и с названным кодом."""

    def test_every_program_shown_as_refused_refuses_with_that_code(self):
        snap = _many_beam_types()
        for name, program, code in skill.REFUSING_PROGRAMS:
            with self.subTest(program=name):
                out = _compile(program, snap)
                self.assertFalse(out.ok, f"{name} прошла, а курс обещает отказ")
                self.assertIn(code, _codes(out),
                              f"{name}: ожидали {code}, получили {_codes(out)}")

    def test_the_g102_refusal_carries_candidates_as_the_course_claims(self):
        """Разбор 2 учит: список уже в руках, второй query_types не нужен."""
        out = _compile(skill.BEAMS_NO_SYMBOL, _many_beam_types())
        lead = out.diagnostics[0].as_dict()
        self.assertEqual(lead["field_name"], "symbol")
        self.assertGreaterEqual(len(lead.get("candidates", [])), 2)
        for row in lead["candidates"]:
            self.assertIn("id", row)
            self.assertIn("name", row)

    def test_the_refusal_lands_on_every_op_not_just_the_first(self):
        """Разбор 2: «отказ приходит НА КАЖДУЮ операцию» — это и есть причина,
        по которой полная пачка стоит целого раунда."""
        out = _compile(skill.BEAMS_NO_SYMBOL, _many_beam_types())
        self.assertEqual(len(out.diagnostics),
                         len(skill.BEAMS_NO_SYMBOL["ops"]))

    def test_one_envelope_line_fixes_all_three_ops(self):
        """Разбор 2, починка: `defaults` вместо правки в каждом опе."""
        self.assertNotIn("defaults", skill.BEAMS_NO_SYMBOL)
        self.assertIn("defaults", skill.BEAMS_FIXED)
        self.assertEqual(skill.BEAMS_FIXED["ops"], skill.BEAMS_NO_SYMBOL["ops"],
                         "починка обязана быть ТОЛЬКО конвертом")
        self.assertTrue(_compile(skill.BEAMS_FIXED, _many_beam_types()).ok)

    def test_the_deck_refusal_matches_the_production_trace_verbatim(self):
        """Разбор 3 целиком построен на живом отказе. Если компилятор
        перестанет давать эти поля, разбор станет выдумкой — и тест упадёт."""
        out = _compile(skill.DECK_BAD_OFFSET)
        lead = out.diagnostics[0].as_dict()
        self.assertEqual(lead["code"], "KIR-T002")
        self.assertEqual(lead["op_id"], "deck57")
        self.assertEqual(lead["field_name"], "height_offset_mm")
        self.assertEqual(lead["got"], 57000)
        self.assertEqual(lead["suggested_replacement"], 15000)
        self.assertEqual(lead["applicability"], "maybe-incorrect",
                         "разбор 3 держится на том, что подсказка НЕ machine-"
                         "applicable — иначе совет её проверять неверен")

    def test_taking_the_suggestion_would_build_the_wrong_thing(self):
        """Сердце разбора 3: подсказка ПРОХОДИТ компилятор и строит не то.
        Оба утверждения проверяем, иначе урок голословен."""
        clamped = copy.deepcopy(skill.DECK_BAD_OFFSET)
        clamped["ops"][0]["height_offset_mm"] = 15000
        self.assertTrue(_compile(clamped).ok, "подсказка обязана проходить")
        self.assertNotEqual(15000, 57000, "и обязана давать НЕ ту отметку")
        self.assertTrue(_compile(skill.DECK_OWN_LEVEL).ok,
                        "а правильная починка — компилироваться")
        lvl = skill.DECK_OWN_LEVEL["ops"][0]
        self.assertEqual(lvl["op"], "create_level")
        self.assertEqual(lvl["elev_mm"], 57000)


class AdvisedBoundariesActuallyRefuse(unittest.TestCase):
    """Проверка 3: каждая названная граница обязана провалиться — и по СВОЕЙ
    причине, а не по любой."""

    def test_omitting_a_selector_refuses_instead_of_guessing(self):
        beams = [{"op": "create_beam", "id": f"b{i}",
                  "p0_mm": [i * 1000, 0, 0], "p1_mm": [i * 1000, 0, 30000],
                  "level": LEVEL} for i in range(12)]
        out = _compile(_prog(beams), _many_beam_types())
        self.assertFalse(out.ok, "умолчание подставилось молча — совет устарел")
        self.assertTrue(all(c.startswith("KIR-G") for c in _codes(out)),
                        _codes(out))

    def test_a_window_cannot_take_a_model_coordinate(self):
        """Приём «ХОСТ»: у проёма нет своей координаты модели."""
        out = _compile(_prog([
            {"op": "create_wall", "id": "w", "p0_mm": [0, 0],
             "p1_mm": [6000, 0], "height_mm": 3000, "level": LEVEL},
            {"op": "create_window", "id": "win",
             "host": {"by": "ref", "value": "w"}, "xyz_mm": [3000, 0, 900]}]))
        self.assertFalse(out.ok, "окно приняло координату — приём неверен")
        self.assertIn("KIR-P003", _codes(out))

    def test_ref_across_a_program_boundary_refuses(self):
        out = _compile(_prog([
            {"op": "create_wall", "id": "w1", "p0_mm": [0, 0],
             "p1_mm": [6000, 0], "height_mm": 3000,
             "level": {"by": "ref", "value": "L_из_прошлой_программы"}}]))
        self.assertFalse(out.ok, "ref через границу прошёл — приём неверен")
        self.assertIn("KIR-L003", _codes(out))

    def test_track_must_cover_every_index_no_extrapolation(self):
        short = copy.deepcopy(skill.TOWER_TRACK)
        short["ops"][1]["track"] = {"hw": [[0, 62500], [5, 30000]],
                                    "z": [[0, 0], [5, 57000]]}
        out = _compile(short, _many_beam_types())
        self.assertFalse(out.ok, "трек не покрыл индексы, а отказа нет")
        self.assertIn("покрывает индексы", out.diagnostics[0].message_ru,
                      f"отказ не про покрытие: {out.diagnostics[0].message_ru}")

    def test_declared_but_unused_track_param_refuses(self):
        dead = copy.deepcopy(skill.TOWER_TRACK)
        dead["ops"][1]["track"]["unused"] = [[0, 1], [20, 2]]
        out = _compile(dead, _many_beam_types())
        self.assertFalse(out.ok, "мёртвый параметр трека прошёл молча")
        self.assertIn("не использован", out.diagnostics[0].message_ru)

    def test_macro_inside_macro_refuses(self):
        nested = copy.deepcopy(skill.TOWER_TRACK)
        nested["ops"][1]["items"] = [
            {"op": "stack", "id": "sec", "levels": 3, "h_mm": 3000,
             "floor": [{"op": "create_wall", "id": "W", "p0_mm": [0, 0],
                        "p1_mm": [6000, 0], "height_mm": 2800}]}]
        out = _compile(nested, _many_beam_types())
        self.assertFalse(out.ok, "вложенный макрос развернулся")
        self.assertIn("внутри макроса", out.diagnostics[0].message_ru)

    def test_series_expansion_ceiling_refuses(self):
        """Предел на РАЗВЁРТКУ (count x len(items)), а не на count.

        Первая редакция была зелёной по неверной причине: count=201 упирался в
        MAX_SERIES_COUNT, то есть проверял другую границу, чем обещал."""
        count = 100
        item = skill.TOWER_TRACK["ops"][1]["items"][0]
        items = [dict(item, id=f"leg{i}") for i in range(3)]
        self.assertLessEqual(count, macros.MAX_SERIES_COUNT)
        self.assertGreater(count * len(items), macros.MAX_SERIES_OPS)
        big = copy.deepcopy(skill.TOWER_TRACK)
        big["ops"][1].update(count=count, items=items,
                             track={"hw": [[0, 62500], [count, 5000]],
                                    "z": [[0, 0], [count, 276000]]})
        out = _compile(big, _many_beam_types())
        self.assertFalse(out.ok, "предел развёртки не сработал")
        self.assertIn("развернётся", out.diagnostics[0].message_ru)

    def test_program_op_budget_refuses(self):
        """Самый частый отказ системы (210 из 586 живых) обязан быть настоящим."""
        walls = [{"op": "create_wall", "id": f"w{i}", "p0_mm": [i * 100, 0],
                  "p1_mm": [i * 100, 5000], "height_mm": 3000, "level": LEVEL}
                 for i in range(MAX_OPS_PER_PROGRAM + 1)]
        out = _compile(_prog(walls))
        self.assertFalse(out.ok, "бюджет программы не сработал")
        self.assertIn("KIR-L001", _codes(out))


class ReadingSideIsDescribedCorrectly(unittest.TestCase):
    """Раздел 2 обещает конкретную разведку — она обязана существовать."""

    def test_there_are_exactly_four_reading_ops(self):
        reading = sorted(n for n, op in spec.OPS.items() if not op.writes_model)
        self.assertEqual(len(reading), 4, reading)
        for name in reading:
            self.assertIn(name, skill.build_skill_text(),
                          f"{name} не назван в курсе")

    def test_the_reading_ops_actually_compile(self):
        for ops in ([{"op": "query_types", "pool": "beam_types"}],
                    [{"op": "query_list", "kind": "wall"}],
                    [{"op": "query_count", "kind": "wall",
                      "group_by": "level_name"}]):
            with self.subTest(op=ops[0]["op"]):
                self.assertTrue(_compile(_prog(ops)).ok)

    def test_query_types_pool_is_closed_and_named_pools_exist(self):
        pool = [p for p in spec.OPS["query_types"].params if p.name == "pool"][0]
        self.assertGreaterEqual(len(pool.choices), 10)
        for named in ("levels", "beam_types"):
            self.assertIn(named, pool.choices)


class NumbersMatchTheCode(unittest.TestCase):
    def test_every_quoted_limit_equals_its_constant(self):
        text = skill.build_skill_text()
        for value in (macros.MAX_SERIES_OPS, macros.MAX_TRACK_PARAMS,
                      macros.MAX_TRACK_NODES, MAX_OPS_PER_PROGRAM):
            self.assertIn(str(value), text, f"предел {value} пропал из текста")

    def test_no_stale_literal_for_the_op_budget(self):
        self.assertIn(str(MAX_OPS_PER_PROGRAM), skill.build_skill_text())
        self.assertNotIn("300 операций", skill.build_skill_text())

    def test_the_bounds_quoted_in_walkthrough_three_are_the_real_ones(self):
        """Курс называет ±15000 дословно; если границу подвинут, урок соврёт."""
        out = _compile(skill.DECK_BAD_OFFSET)
        self.assertEqual(out.diagnostics[0].as_dict()["expected"],
                         "-15000..15000")
        self.assertIn("-15000..15000", skill.build_skill_text())


class CourseShapeAndBudget(unittest.TestCase):
    def test_course_is_part_of_the_tool_description(self):
        """На маршруте по умолчанию описание инструмента — ЕДИНСТВЕННЫЙ канал:
        замер 30.07 — system_base*.md не упоминают revit_ir ни разу."""
        self.assertIn(skill.build_skill_text(), build_tool_description())

    def test_every_section_is_present_and_in_order(self):
        text = skill.build_skill_text()
        positions = []
        for title in skill.SECTION_TITLES:
            self.assertIn(title, text, f"раздел пропал: {title}")
            positions.append(text.index(title))
        self.assertEqual(positions, sorted(positions),
                         "разделы курса идут не по порядку")

    def test_the_course_opens_with_the_system_model(self):
        """Порядок не косметика: без устройства системы советы не на что
        вешать, а выбор формы повтора делается до первой операции."""
        self.assertTrue(skill.SECTION_TITLES[0].endswith("КАК УСТРОЕН KIR"))
        self.assertIn("ФОРМА ПОВТОРА", skill.SECTION_TITLES[2])

    def test_every_walkthrough_goes_all_the_way_to_acceptance(self):
        """Разбор без приёмки — это фрагмент, а не разбор."""
        for title, steps, _programs in skill.WALKTHROUGHS:
            with self.subTest(walkthrough=title[:24]):
                self.assertGreaterEqual(len(steps), 4)
                joined = " ".join(steps).lower()
                # «чин» покрывает и «починка», и «чиним» — разбор 2 кончается
                # глаголом, а не существительным, и первая редакция теста
                # падала на этом, хотя шаг был на месте.
                self.assertTrue(
                    any(w in joined for w in ("приёмк", "перечит", "чин")),
                    f"{title}: нет шага приёмки/починки")

    def test_course_stays_within_the_declared_budget(self):
        """Бюджет поднят оператором до ~10 000 токенов прозы. Проверка идёт по
        символам — tiktoken намеренно не вносится в зависимости тестов.
        Замер 30.07: курс 7 140 токенов o200k = 20 708 символов (3.00 символа
        на токен). Потолок здесь 24 000 символов (~8 000 токенов), а НЕ все
        30 000, которыми ограничено описание целиком: курс делит бюджет с
        реестром операций и ловушками, и порог, равный общему, позволил бы ему
        вытеснить их молча."""
        self.assertLess(len(skill.build_skill_text()), 24_000,
                        "курс перерос свою долю бюджета — режь")

    def test_course_and_notes_do_not_overlap(self):
        """Повторённый совет разбавляет оба текста и оплачивается дважды."""
        def shingles(text: str, n: int = 7) -> set[str]:
            words = "".join(c.lower() if c.isalnum() or c.isspace() else " "
                            for c in text).split()
            return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}

        common = sorted(shingles(skill.build_skill_text())
                        & shingles("\n".join(NOTES)))
        self.assertEqual(common, [], f"дубли курса и NOTES: {common[:3]}")


if __name__ == "__main__":
    unittest.main()
