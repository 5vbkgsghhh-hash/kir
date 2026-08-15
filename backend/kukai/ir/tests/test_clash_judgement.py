"""СЛОЙ СУЖДЕНИЯ: пара становится тем, что проектировщик примет.

ЧТО ЗАМЕРЕНО ПЕРЕД ПРАВКОЙ (09.08, `snowdon_plumb_v5`, 11 069 элементов, 122
тела). Область `all_physical_diagnostic` дала 99 пар, и слой `clash/review.py`
поставил **66 из них на верхнюю ступень** («критично»). Все 66 — плиты ОДНОГО
этажа. Разбор против настоящей геометрии показал, что дело не в области поиска
и не в пороге, а в двух огрублениях, которые внёс сам компилятор:

  * 62 пары из 76 «перекрытие~перекрытие» имеют НЕПЕРЕСЕКАЮЩИЕСЯ объявленные
    контуры — пересекаются только их ВЫПУКЛЫЕ оболочки (`hulls.build_hull`
    овыпукляет подошву и засыпает отверстия). Огрубление объясняет 61 из
    них: 62-я выпукла с обеих сторон, и объяснять там нечем;
  * размах плиты по Z огрублён ВДВОЕ самим `clash_bundle._slab_geometry`.

Отчёт, две трети которого проектировщик выбрасывает, хуже отсутствующего.

Прогон:
    venv/bin/python -m pytest kukai/ir/tests/test_clash_judgement.py -q
"""
from __future__ import annotations

import copy
import math
import unittest

from kukai.clash import detect as D
from kukai.clash import geom as G
from kukai.clash import hulls as H
from kukai.ir import clash_judgement as J
from kukai.ir.decompile.extract import _SPEC_BY_NAME


# ═════════════════════════════════════════════════════════════════════════
# Материал: находка детектора собирается РУКАМИ ровно той формы, что отдаёт
# `detect.Finding.as_dict()` — иначе тест проверял бы свою фантазию.
# ═════════════════════════════════════════════════════════════════════════

def side(element_id: str, category: str, label: str, *,
         hull_source: str = "axis_section") -> dict:
    return {"source_element_id": element_id, "category": category,
            "label": label, "hull_grade": "conservative",
            "hull_source": hull_source, "level_id": "lvl", "type_name": None,
            "section_source": "diameter", "section_radius_mm": 100.0}


def finding(a: dict, b: dict, *, relation: str = "overlap",
            depth: float = 80.0, grade: str = "conservative",
            pair_kind: str = "interference",
            translation: list[float] | None = None,
            verdict: str | None = None) -> dict:
    return {
        "finding_id": f"{a['source_element_id']}~{b['source_element_id']}",
        "a": a, "b": b,
        "pair_class": "~".join(sorted((a["label"], b["label"]))),
        "signed_distance_mm": -depth, "hull_overlap_depth_mm": depth,
        "clearance_mm": 0.0, "clearance_deficit_mm": depth,
        "ranking_tol_mm": H.TOL_GRADE_MM[grade], "ranking_significant": True,
        "hull_grade": grade, "pair_kind": pair_kind,
        "hull_relation": relation,
        "verdict": verdict or ("confirmed" if grade == "exact" else "possible"),
        "certified_separating_translation_mm": translation,
        "translation_unavailable_reason": None,
    }


PIPE = side("p1/pipe1", "OST_PipeCurves", "pipe")
DUCT = side("p2/duct1", "OST_DuctCurves", "duct")
DUCT2 = side("p2/duct2", "OST_DuctCurves", "duct")
WALL = side("p3/w1", "OST_Walls", "wall", hull_source="bbox")
FLOOR = side("p3/f1", "OST_Floors", "floor", hull_source="profile")
BEAM = side("p4/b1", "OST_StructuralFraming", "beam", hull_source="bbox")
COLUMN = side("p4/c1", "OST_Columns", "column", hull_source="bbox")
EQUIP = side("p5/eq1", "OST_MechanicalEquipment", "equipment",
             hull_source="bbox")


def exact(s: dict) -> dict:
    """Точная сторона для позитивного контракта будущей геометрии."""
    return {**s, "hull_grade": "exact"}


def one(*args, **kwargs) -> J.Judged:
    return J.judge([finding(*args, **kwargs)]).judged[0]


def sealed_exact_duplicate() -> dict:
    """Future exact producer fixture issued through the real detector.

    Production currently emits no ``grade=exact`` body.  The positive branch
    still needs an executable contract, otherwise a permanently-false safety
    predicate could look safe while silently disabling the feature forever.
    """

    def record(source_id: str) -> H.HullRecord:
        hull = G.Prism(
            ((0.0, 0.0), (1000.0, 0.0),
             (1000.0, 100.0), (0.0, 100.0)),
            0.0, 100.0)
        inner = H.certify_analytic_inner_for_test(
            inner=hull,
            body=hull,
            outer=hull,
            subject_source_id=source_id,
            body_source_digest=H.analytic_hull_digest(hull),
            body_source_revision=f"fixture:{source_id}:body-r1",
        )
        return H.HullRecord(
            source_id=source_id,
            category="OST_PipeCurves",
            label="pipe",
            mvp_side="mep",
            hull=hull,
            grade="exact",
            hull_source="future_exact_body",
            inner=inner,
        )

    detected = D.evaluate(record("p1/exact-a"), record("p1/exact-b"))
    assert detected is not None
    return detected.as_dict()


# ═════════════════════════════════════════════════════════════════════════
# 1. СЛОВАРИ ЧУЖИЕ, И ЭТО ДЕРЖИТСЯ ТЕСТОМ
# ═════════════════════════════════════════════════════════════════════════

class TheDictionariesAreNotOurs(unittest.TestCase):

    def test_the_discipline_comes_from_the_extractor_table_and_nowhere_else(self):
        """ВТОРОЙ СЛОВАРЬ РАЗДЕЛОВ ЗДЕСЬ УЖЕ УБИВАЛИ (fold, 28.07): свой знал
        17 категорий из 47 и весь ЭОМ читал как «не знаем, что это»."""
        for category, spec in _SPEC_BY_NAME.items():
            self.assertEqual(J.discipline_of(category), spec.discipline,
                             category)

    def test_a_category_the_extractor_does_not_know_reads_as_unknown(self):
        """Пустота видна, догадка — нет. Замер 09.08: пять категорий
        `hulls.KIND_TABLE` таблице экстрактора неизвестны."""
        absent = [c for c in H.KIND_TABLE if c not in _SPEC_BY_NAME]
        self.assertTrue(absent, "выборка пуста — тест стал бы вакуумным")
        for category in absent:
            self.assertEqual(J.discipline_of(category), "unknown", category)
        self.assertEqual(J.discipline_of("OST_NoSuchThing"), "unknown")

    def test_every_label_of_the_closed_hull_table_has_a_role(self):
        """Закрытая таблица ролей: новая метка обязана быть ЗАМЕЧЕНА, а не
        отнесена к чему попало молча."""
        for category, rule in H.KIND_TABLE.items():
            self.assertIn(rule.label, J.ROLE_BY_LABEL,
                          f"{category}: метка {rule.label!r} без роли")

    def test_a_physical_element_never_carries_the_not_a_body_role(self):
        """Роль `not_a_body` и пригодность к поиску — одно и то же утверждение,
        и разойтись они не имеют права."""
        for category, rule in H.KIND_TABLE.items():
            if not rule.eligible:
                continue
            self.assertNotEqual(J.role_of(rule.label), "not_a_body", category)

    def test_the_role_table_names_no_label_that_does_not_exist(self):
        known = {rule.label for rule in H.KIND_TABLE.values()}
        self.assertEqual(sorted(set(J.ROLE_BY_LABEL) - known), [],
                         "роль назначена метке, которой в KIND_TABLE нет")


# ═════════════════════════════════════════════════════════════════════════
# 2. ТАБЛИЦА ПРАВИЛ — КАЖДОЕ СРАБАТЫВАЕТ, И КАЖДОЕ ОБОСНОВАНО
#
# ЗАЧЕМ СИНТЕТИКА. Оба настоящих здания, на которых мерялась эта волна, НЕ
# кладут в поиск ни одного тела инженерной сети: `snowdon_plumb_v5` вовсе не
# содержит труб и воздуховодов (замер по L0: 0 из 11 069), а у `sklnk_eom_r26_v10`
# все 77 лотков остаются без сечения. Половина таблицы на них ВАКУУМНА по
# построению, и признать это честнее, чем объявить её проверенной.
# ═════════════════════════════════════════════════════════════════════════

class TheRulesAreFacts(unittest.TestCase):

    def test_two_runs_in_one_volume_are_a_collision(self):
        """Два тела трассы не могут занимать один объём."""
        item = one(DUCT, DUCT2)
        self.assertEqual((item.kind, item.rule_id),
                         ("collision", "run_meets_run"))

    def test_a_pipe_through_a_wall_is_a_penetration_not_a_collision(self):
        """Сеть ОБЯЗАНА переходить между помещениями: это гильза, а не ошибка."""
        item = one(PIPE, WALL)
        self.assertEqual((item.kind, item.rule_id),
                         ("penetration", "run_through_envelope"))
        self.assertNotIn("create_opening", item.next_move_ru)
        self.assertIn("менять или удалять", item.next_move_ru)

    def test_a_duct_through_a_beam_is_a_collision(self):
        """Отверстие в балке — расчёт и согласование, а не типовой узел."""
        item = one(DUCT, BEAM)
        self.assertEqual((item.kind, item.rule_id),
                         ("collision", "run_through_bearing"))

    def test_a_run_inside_equipment_is_a_collision(self):
        item = one(PIPE, EQUIP)
        self.assertEqual((item.kind, item.rule_id),
                         ("collision", "run_meets_equipment"))

    def test_a_floor_meeting_a_wall_is_adjacency(self):
        """Плита опирается на стену — так здание и собрано."""
        item = one(FLOOR, WALL, relation="contact", depth=0.0)
        self.assertEqual((item.kind, item.rule_id),
                         ("adjacency", "structure_contact"))
        self.assertEqual(item.rung, "note")

    def test_the_author_declared_host_is_never_a_clash(self):
        """Факт о ЗАЯВЛЕНИИ, а не о строительстве: дверь внутри своей стены."""
        door = side("p3/d1", "OST_Doors", "door", hull_source="bbox")
        ops = {"p3/d1": {"op": "create_door", "id": "d1",
                         "host": {"by": "ref", "value": "w1"}},
               "p3/w1": {"op": "create_wall", "id": "w1"}}
        item = J.judge([finding(door, WALL, depth=200.0)], ops=ops).judged[0]
        self.assertEqual((item.kind, item.rule_id),
                         ("adjacency", "host_declared"))

    def test_a_declared_host_of_someone_else_does_not_excuse_the_pair(self):
        """Хозяин сверяется с `id` ВТОРОЙ стороны, а не с фактом наличия поля."""
        door = side("p3/d1", "OST_Doors", "door", hull_source="bbox")
        ops = {"p3/d1": {"op": "create_door", "id": "d1",
                         "host": {"by": "ref", "value": "СОВСЕМ ДРУГАЯ"}},
               "p3/w1": {"op": "create_wall", "id": "w1"}}
        item = J.judge([finding(door, WALL, depth=200.0)], ops=ops).judged[0]
        self.assertNotEqual(item.rule_id, "host_declared")

    def test_every_rule_that_the_table_declares_can_be_reached(self):
        """Правило, которое не может сработать, — украшение, а не контракт."""
        reached = {
            J.judge([finding(*args, **kw)]).judged[0].rule_id
            for args, kw in (
                ((DUCT, DUCT2), {}),
                ((PIPE, WALL), {}),
                ((DUCT, BEAM), {}),
                ((PIPE, EQUIP), {}),
                ((FLOOR, WALL), {"relation": "contact", "depth": 0.0}),
                ((DUCT, DUCT2), {"pair_kind": "coincident_duplicate"}),
                ((side("p9/x", "OST_Furniture", "furniture",
                       hull_source="bbox"),
                  side("p9/y", "OST_StairsRailing", "railing",
                       hull_source="bbox")), {}),
            )}
        declared = {rule.rule_id for rule in J.RULES} - {"host_declared",
                                                         "hull_over_approximation"}
        self.assertEqual(declared - reached, set(),
                         f"недостижимые правила: {sorted(declared - reached)}")


# ═════════════════════════════════════════════════════════════════════════
# 3. ОТКАЗАННЫЕ ПРАВИЛА — ЧАСТЬ КОНТРАКТА
# ═════════════════════════════════════════════════════════════════════════

class TheRefusalsAreLoud(unittest.TestCase):

    def test_two_structures_interpenetrating_get_no_rule_and_say_why(self):
        """Различает монолит и металл МАТЕРИАЛ, а его программа не выражает."""
        item = one(FLOOR, COLUMN, depth=295.0, grade="coarse")
        self.assertEqual(item.kind, "unclassified")
        self.assertEqual(item.rule_id, "structure_meets_structure_overlap")
        self.assertIn("МАТЕРИАЛ", item.why_ru)

    def test_two_runs_merely_touching_are_not_ruled_on(self):
        """Нормируемый зазор между трассами программой не выражен."""
        item = one(DUCT, DUCT2, relation="contact", depth=0.0)
        self.assertEqual(item.rule_id, "run_meets_run_clearance")
        self.assertEqual(item.kind, "unclassified")

    def test_every_refused_rule_carries_its_own_justification(self):
        for name, why in J.REFUSED_RULES.items():
            self.assertGreater(len(why), 80, name)

    def test_a_refusal_is_counted_apart_from_a_rule_that_filtered(self):
        """«Правило сняло пару» и «правила нет» — разные факты и разные счётчики."""
        verdict = J.judge([finding(FLOOR, COLUMN, depth=295.0, grade="coarse"),
                           finding(FLOOR, WALL, relation="contact", depth=0.0)])
        self.assertEqual(verdict.refused_by_rule,
                         {"structure_meets_structure_overlap": 1})
        self.assertEqual(verdict.filtered_by_rule, {"structure_contact": 1})


# ═════════════════════════════════════════════════════════════════════════
# 4. СТУПЕНЬ = ДОКАЗАТЕЛЬНОСТЬ × РОД × ГЛУБИНА
# ═════════════════════════════════════════════════════════════════════════

class TheRungIsAContract(unittest.TestCase):

    def test_a_bounding_box_never_reaches_the_repair_rung(self):
        """ГЛАВНЫЙ ЗАКОН СТУПЕНЕЙ. По габаритному боксу тело не доказано, и
        обещать проектировщику больше доказанного нельзя."""
        item = one(DUCT, BEAM, depth=900.0, grade="coarse")
        self.assertEqual(item.kind, "collision")
        self.assertEqual(item.rung, "look")
        self.assertIsNone(item.proven)

    def test_an_exact_outer_word_without_inner_proof_does_not_reach_repair(self):
        item = one(exact(DUCT), exact(DUCT2), depth=900.0, grade="exact")
        self.assertEqual(item.rung, "look")
        self.assertIsNone(item.proven)

    def test_rectangular_duct_outer_capsules_do_not_become_a_proven_clash(self):
        """РЕГРЕССИЯ proof-firebreak.

        У двух воздуховодов 100×100 мм зазор между телами 20 мм. Сечение
        сейчас поднимается капсулой радиуса полудиагонали; капсулы
        перекрываются на 21.421 мм, хотя прямоугольные тела разделены.
        Детектор честно говорит `possible`; judgement прежде повышал это до
        `proven=True`, `rung=fix` и предлагал исполнимый перенос.
        """
        radius = math.hypot(50.0, 50.0)

        def duct_record(element_id: str, y: float) -> H.HullRecord:
            return H.HullRecord(
                source_id=element_id,
                category="OST_DuctCurves", label="duct", mvp_side="run",
                hull=G.Capsule(((0.0, y, 0.0), (1000.0, y, 0.0)), radius),
                grade="conservative", hull_source="axis_section",
                section_radius_mm=radius, section_round=False,
                section_source="width+height")

        raw = D.evaluate(duct_record("p1/a", 0.0),
                         duct_record("p1/b", 120.0))
        self.assertIsNotNone(raw)
        self.assertEqual(raw.verdict, "possible")
        self.assertAlmostEqual(raw.hull_overlap_depth_mm, 21.421356, places=5)

        item = J.judge([raw.as_dict()]).judged[0]
        self.assertEqual(item.geometry_verdict, "possible")
        self.assertIs(item.proven, False)
        self.assertEqual(item.rung, "look")
        self.assertNotIn("сдвинуть", item.next_move_ru)
        self.assertIn("менять или удалять", item.next_move_ru)

    def test_an_overlap_inside_the_grades_own_tolerance_is_not_a_repair(self):
        """Единственный порог глубины здесь — ЧУЖОЙ: допуск собственного
        грейда оболочки (`hulls.TOL_GRADE_MM`). Своих 100 и 10 мм тут нет."""
        item = one(DUCT, DUCT2, depth=H.TOL_GRADE_MM["conservative"] / 2)
        self.assertEqual(item.rung, "look")

    def test_the_module_invents_no_depth_threshold_of_its_own(self):
        """Структурная защита: числа-пороги глубины в модуле не заводятся.
        Порог, написанный рассуждением, — класс дефекта этого кодекса."""
        import pathlib
        import re
        source = pathlib.Path(J.__file__).read_text(encoding="utf-8")
        code = "\n".join(line.split("#", 1)[0] for line in source.splitlines())
        code = re.sub(r'"""[\s\S]*?"""', "", code)
        for number in re.findall(r"\b\d+\.\d+\b", code):
            self.assertIn(number, {"0.0", "1e-6"},
                          f"число {number} в коде: порог с потолка?")

    def test_the_ladder_ends_where_there_is_nothing_to_do(self):
        keys = [key for key, _, _ in J.RUNGS]
        self.assertEqual(keys[-1], "note")
        self.assertEqual(keys[0], "fix")
        for _, _, action in J.RUNGS:
            self.assertGreater(len(action), 40, "ступень не назвала действие")


# ═════════════════════════════════════════════════════════════════════════
# 5. РАЗРУШАЮЩЕЕ УКАЗАНИЕ — ТОЛЬКО ПО ДОКАЗАННОМУ
# ═════════════════════════════════════════════════════════════════════════

class TheDestructiveInstructionIsGated(unittest.TestCase):

    def test_real_sealed_exact_equality_still_requires_semantic_review(self):
        item = J.judge([sealed_exact_duplicate()]).judged[0]
        self.assertEqual(item.kind, "duplicate")
        self.assertIs(item.proven, True)
        self.assertEqual(item.rung, "look")
        self.assertNotIn("удалить ОДИН", item.next_move_ru)
        self.assertIn("автоматически удалять нельзя", item.next_move_ru)

    def test_tampered_exact_equality_cannot_keep_the_delete_capability(self):
        forged = copy.deepcopy(sealed_exact_duplicate())
        forged["exact_body_equality_proof"]["a"]["hull_source"] = "bbox"
        item = J.judge([forged]).judged[0]
        # Physical overlap remains independently proven; only the equality
        # capability is revoked.  Conflating the axes would hide this exact
        # class of proof tamper.
        self.assertIs(item.proven, True)
        self.assertNotIn("удалить ОДИН", item.next_move_ru)
        self.assertIn("удалять по такой находке нельзя", item.next_move_ru)

    def test_a_duplicate_seen_through_two_bounding_boxes_never_orders_deletion(self):
        """ДЕФЕКТ, ПОЧИНЕННЫЙ НА СОСЕДНЕЙ ВЕТКЕ (`c9d21573`): у двух диагоналей
        квадрата ОДИН габарит, и совет «удалить одну из них» стирал живой
        элемент. На этой ветке `detect.pair_kind_of` всё ещё судит по боксам —
        значит указание обязано быть заперто здесь."""
        a = side("p1/x", "OST_Walls", "wall", hull_source="bbox")
        b = side("p1/y", "OST_Walls", "wall", hull_source="bbox")
        item = one(a, b, pair_kind="coincident_duplicate", grade="coarse")
        self.assertEqual(item.kind, "duplicate")
        self.assertNotIn("удалить", item.next_move_ru)
        self.assertIn("сверить", item.next_move_ru)

    def test_an_exact_outer_word_alone_never_orders_deletion(self):
        item = one(exact(DUCT), exact(DUCT2),
                   pair_kind="coincident_duplicate", grade="exact")
        self.assertNotIn("удалить ОДИН", item.next_move_ru)

    def test_two_outer_axes_never_order_deletion(self):
        item = one(DUCT, DUCT2, pair_kind="coincident_duplicate")
        self.assertNotIn("удалить ОДИН", item.next_move_ru)

    def test_the_box_is_refused_by_its_own_name_not_only_by_the_grade(self):
        """ЗАЩИТА В ГЛУБИНУ. Сегодня `hulls.py` выдаёт `bbox` только с грейдом
        `coarse` (строка 816), то есть грейд ловит этот случай сам. Запрет
        держится и по ИМЕНИ источника: связь «бокс ⇒ coarse» — свойство чужого
        модуля, и день, когда она разойдётся, не должен разрешить удаление."""
        a = side("p1/x", "OST_Walls", "wall", hull_source="bbox")
        b = side("p1/y", "OST_Walls", "wall", hull_source="bbox")
        item = one(a, b, pair_kind="coincident_duplicate", grade="conservative")
        self.assertNotIn("удалить", item.next_move_ru)

    def test_two_hulls_built_by_different_means_never_prove_coincidence(self):
        """Ось, сравненная с подошвой, совпадения тел не доказывает: сравнивать
        можно только однородное."""
        a = side("p1/x", "OST_Floors", "floor", hull_source="profile")
        b = side("p1/y", "OST_Floors", "floor", hull_source="axis_section")
        item = one(a, b, pair_kind="coincident_duplicate")
        self.assertNotIn("удалить", item.next_move_ru)

    def test_proven_is_three_valued_and_none_is_not_no(self):
        """Тот же закон, что у `detect.hulls_coincide`: `None` значит «сказать
        нечего», и путать его с `False` нельзя ни в одну сторону."""
        self.assertIsNone(one(DUCT, BEAM, grade="coarse").proven)
        self.assertIs(one(DUCT, DUCT2).proven, False)
        self.assertIsNone(one(exact(DUCT), exact(DUCT2), grade="exact").proven)


# ═════════════════════════════════════════════════════════════════════════
# 6. ОГРУБЛЕНИЕ, КОТОРОЕ ВНЕСЛИ МЫ САМИ
# ═════════════════════════════════════════════════════════════════════════

class Prism:
    """Минимальная призма формы `geom.Prism` — нужен только `bounds()`."""

    def __init__(self, z0: float, z1: float) -> None:
        self.z0, self.z1 = z0, z1

    def bounds(self):
        return (0.0, 0.0, self.z0), (1000.0, 1000.0, self.z1)


class Record:
    def __init__(self, source_id: str, hull) -> None:
        self.source_id, self.hull = source_id, hull


def plate_slack(t: float, *, z_ref: float = 0.0,
                grow_class: str | None = "create_floor") -> dict:
    """Запись огрубления РОВНО той формы, что кладёт `clash_bundle` в
    `BundleGeometry.slack`: полутолщина, отметка и КЛАСС соглашения о росте.
    `grow_class=None` — снапшот, где соглашение не названо."""
    rec: dict = {"z_mm": t, "z_ref_mm": z_ref, "why": "plate_z_doubling"}
    if grow_class is not None:
        rec["grow_class"] = grow_class
    return rec


class TheSlackWeAddedIsNotEvidence(unittest.TestCase):

    def test_two_plates_on_one_level_are_not_excused_by_z_doubling(self):
        """ЭТОТ ТЕСТ ПОМЕНЯЛ СТОРОНУ, И ВОТ ПОЧЕМУ. Прежде он утверждал
        обратное — что такая пара `unproven`, — и тем закреплял КОНТРАКТОМ
        сертификат, который не мог не сработать: прежнее условие сводилось к
        `2·min(tₐ,t_b) − tₐ − t_b = −|tₐ − t_b| ≤ 0`, истинному при любых
        толщинах и ни разу не спросившему план (см. `_plate_can_miss`).

        Две плиты ОДНОГО класса на одной отметке, объявленные контуры которых
        по-настоящему пересекаются в плане, делят объём — и это находка.
        Честный сосед `profile_convexified` здесь молчит ПО ДЕЛУ: контуры
        пересекаются, опровергать ему нечем. Замер 09.08 (66 «критично» из 99
        на `snowdon_plumb_v5`) снимают не такие пары, а те 62 из 76, у
        которых объявленные контуры НЕ пересекаются: работу делает контур, а
        не размах по Z."""
        a = side("p1/f1", "OST_Floors", "floor", hull_source="profile")
        b = side("p1/f2", "OST_Floors", "floor", hull_source="profile")
        el = [[0, 0], [2000, 0], [2000, 1000], [1000, 1000],
              [1000, 2000], [0, 2000]]
        crossing = [[500, 500], [1500, 500], [1500, 1500], [500, 1500]]
        # Контуры пересекаются ПО-НАСТОЯЩЕМУ — иначе тест прошёл бы не по той
        # причине: сняла бы подошва, а про Z он не сказал бы ничего.
        self.assertIs(J.loops_overlap(el, crossing), True)
        hulls = {"p1/f1": Record("p1/f1", Prism(-152.4, 152.4)),
                 "p1/f2": Record("p1/f2", Prism(-152.4, 152.4))}
        profiles = {"p1/f1": {"exterior_loop": el},
                    "p1/f2": {"exterior_loop": crossing}}
        slack = {"p1/f1": plate_slack(152.4), "p1/f2": plate_slack(152.4)}
        item = J.judge([finding(a, b, depth=304.8)], hulls=hulls,
                       profiles=profiles, slack=slack).judged[0]
        self.assertEqual(item.slack, ())
        self.assertNotEqual(item.kind, "unproven")
        self.assertIs(item.proven, False)
        self.assertEqual(item.rule_id, "structure_meets_structure_overlap")

    # ── ∃ ходит по ДИАГОНАЛИ прочтений, а не по их квадрату ───────────────

    def test_two_floors_on_one_level_are_never_refuted_by_z_doubling(self):
        """РЕГРЕССИЯ, КОТОРУЮ БЫЛО НЕЧЕМ ПОЙМАТЬ. Прежний сертификат считал
        `2·min(tₐ,t_b) − tₐ − t_b = −|tₐ − t_b| ≤ 0` — ТОЖДЕСТВЕННО истинно
        при любых положительных толщинах, без единой ссылки на план. Ниже он
        срабатывает на 25 парах из 25; сертификат, который не может не
        сработать, читается доказательством, не будучи им.

        Диагональ прочтений держит обе плиты ОДНОГО класса читаемыми
        одинаково, и при любом из двух прочтений они перекрываются на
        min(tₐ,t_b) > 0 — ∃ честно не находится ни на одной паре."""
        thicknesses = (100.0, 150.0, 200.0, 250.0, 300.0)
        fired_old = fired_new = 0
        for ta in thicknesses:
            for tb in thicknesses:
                a = side("p1/f1", "OST_Floors", "floor",
                         hull_source="profile")
                b = side("p1/f2", "OST_Floors", "floor",
                         hull_source="profile")
                hulls = {"p1/f1": Record("p1/f1", Prism(-ta, ta)),
                         "p1/f2": Record("p1/f2", Prism(-tb, tb))}
                slack = {"p1/f1": plate_slack(ta), "p1/f2": plate_slack(tb)}
                # Прежнее условие выписано здесь ДОСЛОВНО: тест обязан
                # показывать, что именно он ловит, а не ссылаться на память.
                overlap_z = min(ta, tb) - max(-ta, -tb)
                if overlap_z - ta - tb <= 0.0:
                    fired_old += 1
                item = J.judge([finding(a, b, depth=2.0 * min(ta, tb))],
                               hulls=hulls, slack=slack).judged[0]
                if "plate_z_doubling" in item.slack:
                    fired_new += 1
                self.assertNotIn("plate_z_doubling", item.slack,
                                 msg=f"ta={ta} tb={tb}")
        self.assertEqual(fired_old, len(thicknesses) ** 2)
        self.assertEqual(fired_new, 0)

    def test_a_floor_and_a_ceiling_on_one_level_may_still_be_refuted(self):
        """СЕРТИФИКАТ ВЫЖИВАЕТ ТАМ, ГДЕ ОН ЧЕСТЕН. Перекрытие и потолок — две
        РАЗНЫЕ операции, и соглашения о росте у них разные; значит прочтение
        «пол вниз, потолок вверх» законно, и при нём срезы расходятся по свою
        сторону отметки. Сужение множества прочтений — не запрет сертификата,
        а требование к нему иметь основание."""
        a = side("p1/f1", "OST_Floors", "floor", hull_source="profile")
        b = side("p1/c1", "OST_Ceilings", "ceiling", hull_source="profile")
        hulls = {"p1/f1": Record("p1/f1", Prism(-152.4, 152.4)),
                 "p1/c1": Record("p1/c1", Prism(-152.4, 152.4))}
        slack = {"p1/f1": plate_slack(152.4, grow_class="create_floor"),
                 "p1/c1": plate_slack(152.4, grow_class="create_ceiling")}
        item = J.judge([finding(a, b, depth=304.8)],
                       hulls=hulls, slack=slack).judged[0]
        self.assertIn("plate_z_doubling", item.slack)
        self.assertEqual(item.kind, "unproven")
        self.assertIs(item.proven, False)

    def test_absent_grow_class_is_not_a_refutation(self):
        """МОЛЧАНИЕ — НЕ ДОКАЗАТЕЛЬСТВО. Та же пара, что снимается при разных
        классах, без классов остаётся находкой: не назвав соглашения, снапшот
        ничего не опроверг, и молча выдавать это за опровержение нельзя."""
        a = side("p1/f1", "OST_Floors", "floor", hull_source="profile")
        b = side("p1/c1", "OST_Ceilings", "ceiling", hull_source="profile")
        hulls = {"p1/f1": Record("p1/f1", Prism(-152.4, 152.4)),
                 "p1/c1": Record("p1/c1", Prism(-152.4, 152.4))}
        slack = {"p1/f1": plate_slack(152.4, grow_class=None),
                 "p1/c1": plate_slack(152.4, grow_class=None)}
        item = J.judge([finding(a, b, depth=304.8)],
                       hulls=hulls, slack=slack).judged[0]
        self.assertNotIn("plate_z_doubling", item.slack)

    def test_a_plate_pierced_deeper_than_the_slack_stays_a_finding(self):
        """Огрубление снимает РОВНО столько, сколько внесло, и ни миллиметром
        больше: колонна, ушедшая в плиту глубже, чем на толщину, остаётся."""
        a = side("p1/f1", "OST_Floors", "floor", hull_source="profile")
        b = side("p1/c1", "OST_Columns", "column", hull_source="bbox")
        hulls = {"p1/f1": Record("p1/f1", Prism(-100.0, 100.0)),
                 "p1/c1": Record("p1/c1", Prism(-3000.0, 100.0))}
        slack = {"p1/f1": {"z_mm": 100.0}}
        item = J.judge([finding(a, b, depth=200.0, grade="coarse")],
                       hulls=hulls, slack=slack).judged[0]
        self.assertEqual(item.slack, ())
        self.assertEqual(item.rule_id, "structure_meets_structure_overlap")

    def test_tiling_plates_do_not_overlap_though_their_convex_hulls_do(self):
        """ЗАМЕР 09.08: 62 пары из 76 на `snowdon_plumb_v5` — именно такие
        (огрубление объясняет 61: 62-я выпукла с обеих сторон).
        Г-образная плита и её сосед делят РЕБРО, а выпуклые оболочки — площадь."""
        el = [[0, 0], [2000, 0], [2000, 1000], [1000, 1000],
              [1000, 2000], [0, 2000]]
        neighbour = [[1000, 1000], [2000, 1000], [2000, 2000], [1000, 2000]]
        self.assertFalse(J.loop_is_convex(el))
        self.assertIs(J.loops_overlap(el, neighbour), False)

    def test_a_polygon_swallowed_by_another_is_an_overlap(self):
        outer = [[0, 0], [3000, 0], [3000, 3000], [0, 3000]]
        inner = [[1000, 1000], [2000, 1000], [2000, 2000], [1000, 2000]]
        self.assertIs(J.loops_overlap(outer, inner), True)

    def test_a_degenerate_loop_answers_nothing_rather_than_no(self):
        self.assertIsNone(J.loops_overlap([[0, 0], [1, 1]],
                                          [[0, 0], [1, 0], [0, 1]]))

    def test_two_non_convex_plates_that_really_overlap_are_not_excused(self):
        """ОПРОВЕРЖЕНИЕ РАБОТАЕТ В ОБЕ СТОРОНЫ. Невыпуклость сама по себе
        ничего не снимает: снимает НЕПЕРЕСЕЧЕНИЕ объявленных контуров, и когда
        контуры пересекаются по-настоящему, находка остаётся находкой."""
        a = side("p1/f1", "OST_Floors", "floor", hull_source="profile")
        b = side("p1/f2", "OST_Floors", "floor", hull_source="profile")
        el = [[0, 0], [2000, 0], [2000, 1000], [1000, 1000],
              [1000, 2000], [0, 2000]]
        crossing = [[500, 500], [1500, 500], [1500, 1500], [500, 1500]]
        self.assertFalse(J.loop_is_convex(el))
        self.assertIs(J.loops_overlap(el, crossing), True)
        profiles = {"p1/f1": {"exterior_loop": el},
                    "p1/f2": {"exterior_loop": crossing}}
        item = J.judge([finding(a, b, depth=50.0)],
                       profiles=profiles).judged[0]
        self.assertNotIn("profile_convexified", item.slack)

    def test_the_convexified_footprint_only_excuses_a_non_convex_contour(self):
        """Выпуклый контур равен своей оболочке — объяснять ею нечего."""
        a = side("p1/f1", "OST_Floors", "floor", hull_source="profile")
        b = side("p1/f2", "OST_Floors", "floor", hull_source="profile")
        square = [[0, 0], [1000, 0], [1000, 1000], [0, 1000]]
        far = [[5000, 5000], [6000, 5000], [6000, 6000], [5000, 6000]]
        profiles = {"p1/f1": {"exterior_loop": square},
                    "p1/f2": {"exterior_loop": far}}
        item = J.judge([finding(a, b, depth=50.0)],
                       profiles=profiles).judged[0]
        self.assertNotIn("profile_convexified", item.slack)


# ═════════════════════════════════════════════════════════════════════════
# 7. НИЧЕГО МОЛЧА
# ═════════════════════════════════════════════════════════════════════════

class NothingIsSilent(unittest.TestCase):

    def test_every_judged_pair_names_a_rule_that_exists(self):
        known = {rule.rule_id for rule in J.RULES} | set(J.REFUSED_RULES)
        pairs = [finding(DUCT, DUCT2), finding(PIPE, WALL),
                 finding(FLOOR, COLUMN, grade="coarse"),
                 finding(FLOOR, WALL, relation="contact", depth=0.0),
                 finding(DUCT, DUCT2, pair_kind="coincident_duplicate")]
        for item in J.judge(pairs).judged:
            self.assertIn(item.rule_id, known, item)
            self.assertIn(item.kind, J.KINDS, item)
            self.assertTrue(item.why_ru, item)
            self.assertTrue(item.next_move_ru, item)

    def test_the_three_counts_add_up_to_every_pair_and_none_is_lost(self):
        """Спор, снятое правилом и «правила нет» — три разных факта, и вместе
        они обязаны покрывать КАЖДУЮ пару: потерянная пара читается как
        отсутствие пары."""
        pairs = [finding(DUCT, DUCT2), finding(PIPE, WALL),
                 finding(FLOOR, COLUMN, grade="coarse"),
                 finding(FLOOR, WALL, relation="contact", depth=0.0)]
        verdict = J.judge(pairs)
        total = (len(verdict.actionable)
                 + sum(verdict.filtered_by_rule.values())
                 + sum(verdict.refused_by_rule.values()))
        self.assertEqual(total, len(pairs))
        self.assertEqual(sum(verdict.by_kind.values()), len(pairs))
        self.assertEqual(sum(verdict.by_rung.values()), len(pairs))

    def test_a_rule_that_fired_publishes_its_justification(self):
        verdict = J.judge([finding(PIPE, WALL),
                           finding(FLOOR, COLUMN, grade="coarse")])
        self.assertEqual(sorted(verdict.justifications),
                         ["run_through_envelope",
                          "structure_meets_structure_overlap"])

    def test_the_next_move_names_the_op_the_author_can_edit(self):
        """Программа не правится по outer-only находке."""
        ops = {"p1/pipe1": {"op": "create_pipe", "id": "pipe1",
                            "diameter_mm": 110},
               "p3/w1": {"op": "create_wall", "id": "w1"}}
        item = J.judge([finding(PIPE, WALL)], ops=ops).judged[0]
        self.assertNotIn("create_opening", item.next_move_ru)
        self.assertIn("менять или удалять", item.next_move_ru)

    def test_an_outer_translation_without_inner_proof_is_not_executable(self):
        item = one(exact(DUCT), exact(DUCT2), grade="exact",
                   translation=[0.0, 0.0, -84.0])
        self.assertNotIn("-84", item.next_move_ru)
        self.assertIn("менять или удалять", item.next_move_ru)

    def test_judging_nothing_says_nothing_rather_than_all_clear(self):
        verdict = J.judge([])
        self.assertEqual(verdict.judged, ())
        self.assertEqual(verdict.by_kind, {})


if __name__ == "__main__":
    unittest.main()
