"""ВИНТОВОЙ МАРШ: вторая форма `create_stairs`, и ни одного тихого исхода.

ЧТО ЭТО ЗА ПРОБЕЛ. До 09.08.2026 `create_stairs` умел РОВНО ОДИН прямой марш
(`StairsRun.CreateStraightRun`), и это записано в измерении покрытия
дословно — «18 элементов: create_stairs воспроизводит ровно один прямой
марш». Ломаной винт невыразим ВООБЩЕ: прямой марш даёт ДРУГУЮ форму, а не
приближение, — тот же класс, что «ломаная вместо закруглённого края» у
потолка. `StairsRun.CreateSpiralRun` есть и БАЙТ-В-БАЙТ одинаков на всех
шести поставляемых версиях (проверено по эталонным сборкам И живым Roslyn на
:52412), поэтому пробел был наш, а не Revit'а.

ТРИ ЗАКОНА, КОТОРЫЕ ЭТОТ ФАЙЛ ДЕРЖИТ, И КАЖДЫЙ — ОПРОВЕРГАЮЩИЙ:

  1. РОВНО ОДНА ФОРМА. «Оба сразу» так же неоднозначны, как «ни одного», и
     оба обязаны быть ТИПИЗИРОВАННЫМ отказом (KIR-P007), а не догадкой:
     угадать за автора — значит построить другую лестницу молча.
  2. ОТСУТСТВУЮЩЕЕ ОСТАЁТСЯ ОТСУТСТВУЮЩИМ. Программа без `spiral`
     эмитируется БАЙТ В БАЙТ так же, как до правки — храповиком стоит
     `golden/authoring_stairs_straight.golden.cs`, снятый эмиттером ДО неё.
  3. СВИДЕТЕЛЬ ЧИТАЕТ РЕЗУЛЬТАТ И ПОДПИСЫВАЕТ ТОЛЬКО ТО, ЧТО ПРОЧЁЛ. Путь
     созданного марша перечитывается (`GetStairsPath`) и обязан содержать
     ДУГУ. Центр, радиус, размах и направление НЕ проверяются, и здесь на
     это стоит СТРАЖ: отношение между запрошенным центром и тем, что
     возвращает `GetStairsPath` (смещение на полуширину, юстировка), НЕ
     ИЗМЕРЕНО, а допуск, придуманный ради зелёного свидетеля, откатил бы
     ВЕРНО построенную лестницу. Числа уезжают в расписку замером.

Прогон: venv/bin/python3.12 -m pytest kukai/ir/tests/test_stairs_spiral.py -q
"""
from __future__ import annotations

import math
import os
import random
import re
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_spiral_queue.jsonl"))

from kukai.ir import spec  # noqa: E402
from kukai.ir.authoring_validation import (  # noqa: E402
    _SPIRAL_MAX_INCLUDED_DEG, _SPIRAL_RADIUS_MAX_MM,
)
from kukai.ir.compiler import compile_program  # noqa: E402
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT as SNAPSHOT  # noqa: E402

VERSIONS = ("2021", "2022", "2023", "2024", "2025", "2026")

BASE = {"by": "name", "value": "Этаж 1"}
TOP = {"by": "name", "value": "Этаж 2"}

SPIRAL = {"center_mm": [3000.0, 3000.0], "radius_mm": 1500.0,
          "start_angle_deg": 0.0, "included_angle_deg": 270.0,
          "clockwise": False}


def _prog(op_extra: dict, *, intent: str = "лестница") -> dict:
    op = {"op": "create_stairs", "id": "S1",
          "base_level": BASE, "top_level": TOP}
    op.update(op_extra)
    return {"ir_version": "1.0", "intent": intent, "ops": [op]}


def _compile(op_extra: dict, ver: str = "2023"):
    return compile_program(_prog(op_extra), snapshot=SNAPSHOT,
                           revit_version=ver)


def _codes(out) -> list[str]:
    return [d.code for d in out.diagnostics]


# ═════════════════════════════════════════════ 1. ВИНТ СТРОИТСЯ, И НА ШЕСТИ

class ASpiralRunIsEmittedOnEveryShippedVersion(unittest.TestCase):
    """Ось версий — вопрос к эталонным сборкам, а не к памяти; здесь
    держится наш вывод из них: у винта та же ось, что у прямого марша, и
    версионной развилки в эмиссии нет ВООБЩЕ."""

    def test_it_compiles_on_all_six(self) -> None:
        for ver in VERSIONS:
            with self.subTest(version=ver):
                out = _compile({"spiral": SPIRAL, "width_mm": 1200}, ver)
                self.assertTrue(out.ok, _codes(out))
                self.assertIn("StairsRun.CreateSpiralRun", out.csharp)
                self.assertNotIn("CreateStraightRun", out.csharp)

    def test_the_emission_does_not_branch_on_version(self) -> None:
        """Один текст на шесть версий — это ФАКТ, и он обязан быть предъявлен:
        если завтра у винта появится версионный шов, тест обязан покраснеть,
        а не промолчать."""
        texts = {ver: _compile({"spiral": SPIRAL}, ver).csharp
                 for ver in VERSIONS}
        self.assertEqual(len(set(texts.values())), 1)

    def test_the_whole_stairs_skeleton_survives(self) -> None:
        """Ветка расходится ТОЛЬКО в создании марша: StairsEditScope,
        транзакция, статусы, предобработчик отказов и отмена области — всё
        общее с прямым маршем."""
        cs = _compile({"spiral": SPIRAL, "width_mm": 1200}).csharp
        for token in ("new StairsEditScope(", "__ess.Start(",
                      "var __startStatus = __t.Start()",
                      "__startStatus != TransactionStatus.Started",
                      "__fho.SetFailuresPreprocessor(new __KirStairsFailures())",
                      "var __commitStatus = __t.Commit()",
                      "__ess.Commit(new __KirStairsFailures())",
                      "__ess.Cancel()"):
            self.assertIn(token, cs)

    def test_the_solo_rule_still_covers_the_spiral_form(self) -> None:
        """Правило `create_stairs` — солист (KIR-L002) — о СОСТАВЕ программы,
        а не о форме марша. Новая форма не должна была открыть ему обход."""
        wall = {"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
                "p1_mm": [5000, 0], "level": BASE, "height_mm": 3000}
        prog = _prog({"spiral": SPIRAL})
        prog["ops"].append(wall)
        out = compile_program(prog, snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-L002", _codes(out))


# ═════════════════════════════════════════ 2. РОВНО ОДНА ФОРМА (KIR-P007)

class ExactlyOneShapeOfRun(unittest.TestCase):

    def test_both_at_once_is_a_typed_refusal_naming_both(self) -> None:
        out = _compile({"p0_mm": [0, 0], "p1_mm": [5000, 0],
                        "spiral": SPIRAL})
        self.assertFalse(out.ok)
        self.assertIn("KIR-P007", _codes(out))
        text = " ".join(d.message_ru for d in out.diagnostics
                        if d.code == "KIR-P007")
        self.assertIn("p0_mm", text)
        self.assertIn("p1_mm", text)
        self.assertIn("spiral", text)

    def test_neither_is_a_typed_refusal_naming_both(self) -> None:
        out = _compile({"width_mm": 1200})
        self.assertFalse(out.ok)
        self.assertIn("KIR-P007", _codes(out))
        text = " ".join(d.message_ru for d in out.diagnostics
                        if d.code == "KIR-P007")
        self.assertIn("p0_mm", text)
        self.assertIn("spiral", text)

    def test_half_a_straight_run_is_not_a_run(self) -> None:
        """Одна точка отрезка кривую не задаёт. До 09.08 это ловила
        обязательность СХЕМЫ; она стала взаимной, и правило обязано было
        переехать целиком, а не наполовину."""
        for present, missing in (("p0_mm", "p1_mm"), ("p1_mm", "p0_mm")):
            with self.subTest(present=present):
                out = _compile({present: [0, 0]})
                self.assertFalse(out.ok)
                self.assertIn("KIR-P007", _codes(out))
                text = " ".join(d.message_ru for d in out.diagnostics)
                self.assertIn(missing, text)

    def test_the_rule_is_read_from_the_registry_not_from_an_op_name(self) -> None:
        """ОДИН ФАКТ — ОДНО МЕСТО. Правило адресуется РОДАМИ параметров
        (`pt_xy` против `spiral`) у одной операции, поэтому следующий оп с
        винтом получит проверку ВМЕСТЕ С ПОЛЕМ, а не отдельным коммитом «мы
        забыли». Здесь это предъявлено реестром, а не чтением кода."""
        ospec = spec.OPS["create_stairs"]
        kinds = {p.name: p.kind for p in ospec.params}
        self.assertEqual(kinds.get("spiral"), "spiral")
        self.assertEqual(kinds.get("p0_mm"), "pt_xy")
        self.assertEqual(kinds.get("p1_mm"), "pt_xy")
        # Взаимная обязательность НЕ выражается схемой — значит ни одно из
        # трёх полей не имеет права быть required, иначе вторая форма стала
        # бы недостижимой по построению.
        for name in ("p0_mm", "p1_mm", "spiral"):
            self.assertFalse(
                next(p for p in ospec.params if p.name == name).required,
                f"{name}: required убил бы взаимную обязательность")


# ═══════════════════════════════════ 3. ГРАНИЦЫ: ОТКАЗ, А НЕ ИСКЛЮЧЕНИЕ REVIT

class BoundsRefuseBeforeTheDevice(unittest.TestCase):
    """Каждая граница здесь либо ДОКУМЕНТИРОВАНА самим API, либо ВЫВЕДЕНА из
    юстировки. Придуманных чисел в этом классе нет — см. комментарии у
    `_SPIRAL_RADIUS_MAX_MM` / `_SPIRAL_MAX_INCLUDED_DEG`."""

    def _refused(self, spiral: dict, extra: dict | None = None):
        out = _compile({"spiral": spiral, **(extra or {})})
        self.assertFalse(out.ok, "принято то, что Revit отвергнет")
        return out

    def test_non_positive_radius(self) -> None:
        for radius in (0.0, -1500.0):
            with self.subTest(radius=radius):
                out = self._refused(dict(SPIRAL, radius_mm=radius))
                self.assertIn("KIR-T002", _codes(out))

    def test_radius_beyond_the_api_ceiling(self) -> None:
        out = self._refused(
            dict(SPIRAL, radius_mm=_SPIRAL_RADIUS_MAX_MM + 1.0))
        self.assertIn("KIR-T002", _codes(out))
        # Потолок — ДОКУМЕНТИРОВАННЫЕ 30000 футов, ровно.
        self.assertEqual(_SPIRAL_RADIUS_MAX_MM, 30_000 * 304.8)

    def test_the_api_ceiling_itself_is_accepted(self) -> None:
        """Граница, отвергающая собственное значение, — это другая граница."""
        out = _compile({"spiral": dict(SPIRAL,
                                       radius_mm=_SPIRAL_RADIUS_MAX_MM)})
        self.assertTrue(out.ok, _codes(out))

    def test_non_positive_included_angle(self) -> None:
        for angle in (0.0, -90.0):
            with self.subTest(angle=angle):
                out = self._refused(dict(SPIRAL, included_angle_deg=angle))
                self.assertIn("KIR-T002", _codes(out))

    def test_more_than_a_full_turn(self) -> None:
        out = self._refused(
            dict(SPIRAL, included_angle_deg=_SPIRAL_MAX_INCLUDED_DEG + 0.5))
        self.assertIn("KIR-T002", _codes(out))

    def test_a_full_turn_exactly_is_accepted(self) -> None:
        out = _compile({"spiral": dict(SPIRAL, included_angle_deg=360.0)})
        self.assertTrue(out.ok, _codes(out))

    def test_radius_not_greater_than_half_the_width(self) -> None:
        """ВЫВЕДЕННАЯ проверка, а не назначенная: марш строится по СЕРЕДИНЕ
        (`StairsRunJustification.Center`), поэтому внутренняя кромка лежит на
        `radius - width/2`. При `radius <= width/2` внутреннего края нет
        вовсе — ровно это API называет «radius is too small ... at the given
        justification»."""
        out = self._refused(dict(SPIRAL, radius_mm=600.0),
                            {"width_mm": 1200})
        self.assertIn("KIR-T002", _codes(out))
        text = " ".join(d.message_ru for d in out.diagnostics)
        self.assertIn("середине", text)
        # Тот же радиус БЕЗ ширины законен: ширину тогда назначает тип, и
        # сравнивать компилятору не с чем — выдумывать он не станет.
        self.assertTrue(_compile({"spiral": dict(SPIRAL,
                                                 radius_mm=600.0)}).ok)

    def test_a_missing_or_extra_key_is_a_typed_refusal(self) -> None:
        for broken in (
                {k: v for k, v in SPIRAL.items() if k != "clockwise"},
                dict(SPIRAL, unexpected=1),
                dict(SPIRAL, center_mm=[3000.0]),
                dict(SPIRAL, center_mm=[3000.0, 3000.0, 0.0]),
                dict(SPIRAL, clockwise="да"),
                dict(SPIRAL, radius_mm="1500"),
                dict(SPIRAL, start_angle_deg=float("inf")),
        ):
            with self.subTest(broken=sorted(broken)):
                out = _compile({"spiral": broken})
                self.assertFalse(out.ok)
                self.assertTrue(
                    {"KIR-T001", "KIR-T002"} & set(_codes(out)),
                    _codes(out))

    def test_clockwise_has_no_default(self) -> None:
        """Направление закрутки видно в модели с первого взгляда. Молча
        выбранное за автора «против часовой» — это ровно тот тихо другой
        результат, ради запрета которого существует компилятор."""
        out = _compile({"spiral": {k: v for k, v in SPIRAL.items()
                                   if k != "clockwise"}})
        self.assertFalse(out.ok)


# ═══════════════════════════════════════════ 4. ОТСУТСТВУЮЩЕЕ — ОТСУТСТВУЕТ

class AbsentStaysAbsent(unittest.TestCase):

    def test_a_straight_program_carries_no_trace_of_the_spiral(self) -> None:
        cs = _compile({"p0_mm": [0, 0], "p1_mm": [5000, 0],
                       "width_mm": 1200}).csharp
        for token in ("CreateSpiralRun", "GetStairsPath", "path_center_mm",
                      "path_radius_mm", "spiralArc"):
            self.assertNotIn(token, cs)

    def test_the_straight_emission_is_the_pre_change_bytes(self) -> None:
        """Байтовый храповик. Эталон снят ЭМИТТЕРОМ ДО правки (`git stash` на
        15d5b206, тот же снапшот, та же программа): пока файл совпадает,
        «отсутствующий параметр ничего не двигает» — сверка, а не обещание.
        Тот же файл проверяет и `test_golden`; здесь он назван ЯВНО, чтобы
        связь с винтом была видна в этом файле, а не только в общем корпусе."""
        import pathlib

        from kukai.ir.tests.test_golden import PROGRAMS as GOLDEN

        golden = (pathlib.Path(__file__).parent / "golden"
                  / "authoring_stairs_straight.golden.cs")
        out = compile_program(GOLDEN["authoring_stairs_straight"],
                              snapshot=SNAPSHOT)
        self.assertTrue(out.ok, _codes(out))
        self.assertEqual(golden.read_text(encoding="utf-8"), out.csharp)


# ═════════════════════════════════ 5. СВИДЕТЕЛЬ: ЧТО ПОДПИСАН И ЧТО НЕ ПОДПИСАН

class TheWitnessSignsOnlyWhatItRead(unittest.TestCase):

    def test_the_path_is_re_read_and_must_carry_an_arc(self) -> None:
        cs = _compile({"spiral": SPIRAL}).csharp
        self.assertIn("__run_S1.GetStairsPath()", cs)
        self.assertIn("is Arc", cs)
        self.assertIn("S1: spiral run path has no Arc (geometry)", cs)
        # Нечитаемый путь — тоже нарушение, а не тихий пропуск.
        self.assertIn("S1: spiral run path unreadable (geometry)", cs)

    def test_the_violation_rolls_the_whole_thing_back(self) -> None:
        """Свидетель, чьё нарушение ничего не откатывает, — это отчёт, а не
        свидетель. Проверка обязана стоять ДО `__post.Count > 0`, а тот — до
        коммита."""
        cs = _compile({"spiral": SPIRAL}).csharp
        i_witness = cs.index("spiral run path has no Arc")
        i_gate = cs.index("__post.Count > 0")
        i_commit = cs.index("var __commitStatus = __t.Commit()")
        self.assertLess(i_witness, i_gate)
        self.assertLess(i_gate, i_commit)
        self.assertIn("__t.RollBack(); __ess.Cancel();", cs)

    def test_it_signs_geometry_because_it_read_geometry(self) -> None:
        """Ось подписи — по прочитанному. Путь марша это геометрия кривой, а
        не параметр, который мы сами же записали."""
        cs = _compile({"spiral": SPIRAL}).csharp
        witness = cs[cs.index("bool __spiralArc_S1"):
                     cs.index("spiral run path unreadable")]
        self.assertNotIn("get_Parameter", witness)

    def test_no_invented_tolerance_gates_the_centre_or_the_radius(self) -> None:
        """СТРАЖ, А НЕ УКРАШЕНИЕ.

        Отношение между ЗАПРОШЕННЫМИ центром/радиусом и тем, что возвращает
        `GetStairsPath` (смещение на полуширину марша, юстировка, положение
        линии пути), НЕ ИЗМЕРЕНО. Сравнение с допуском, выбранным «на глаз»,
        откатило бы ВЕРНО построенную лестницу — и это хуже отсутствующей
        проверки. Если завтра такое сравнение появится, оно обязано прийти
        ВМЕСТЕ С ЗАМЕРОМ и переписать этот тест осознанно.
        """
        cs = _compile({"spiral": SPIRAL}).csharp
        witness = cs[cs.index("bool __spiralArc_S1"):
                     cs.index("spiral run path unreadable")]
        for token in ("Math.Abs", ".Center", ".Radius", "3000", "1500"):
            self.assertNotIn(token, witness)

    def test_the_unmeasured_relation_is_recorded_instead(self) -> None:
        """«Не измерено» обязано стать ИЗМЕРИМЫМ на первом же живом прогоне:
        центр и радиус пути уезжают в расписку замером, ничего не гатируя."""
        cs = _compile({"spiral": SPIRAL}).csharp
        self.assertIn('__rb_S1["path_center_mm"]', cs)
        self.assertIn('__rb_S1["path_radius_mm"]', cs)
        # Расписка живёт ПОСЛЕ области редактирования, то есть читает
        # зафиксированный результат, а не промежуточное состояние.
        self.assertLess(cs.index("__ess.Commit(new __KirStairsFailures())"),
                        cs.index('__rb_S1["path_center_mm"]'))

    def test_the_registry_promise_names_the_gap_out_loud(self) -> None:
        post = spec.OPS["create_stairs"].post
        self.assertIn("spiral run path contains an Arc", post)
        self.assertIn("UNMEASURED", post)

    def test_the_certificate_discharges_the_new_clause(self) -> None:
        from kukai.ir import ground as ground_mod
        from kukai.ir.compiler import _parse_and_check
        from kukai.ir.translation_cert import assert_refined, certify_op

        for extra in ({"spiral": SPIRAL, "width_mm": 1200},
                      {"p0_mm": [0, 0], "p1_mm": [5000, 0]}):
            with self.subTest(shape=sorted(extra)):
                grounded = ground_mod.ground(
                    _parse_and_check(_prog(extra)), SNAPSHOT)
                for ver in VERSIONS:
                    assert_refined(certify_op(grounded[0], ver))


# ═══════════════════════════════════════ 6. СВОЙСТВА НА ПРОСТРАНСТВЕ УГЛОВ

_CALL_RE = re.compile(
    r"StairsRun\.CreateSpiralRun\(doc, __sid_S1,\s*"
    r"new XYZ\(U\(([-0-9.e+]+)\), U\(([-0-9.e+]+)\), __base_S1\.Elevation\),\s*"
    r"U\(([-0-9.e+]+)\), ([-0-9.e+]+), ([-0-9.e+]+), (true|false),\s*"
    r"StairsRunJustification\.Center\);")


class TheAngleAndRadiusSpaceHoldsItsProperties(unittest.TestCase):
    """Свойства на СЕМЕНОВАННОМ PRNG (hypothesis в прод-venv нет — тот же
    приём, что в `test_pbt`). Границы берутся из тех же констант, что и у
    компилятора: корпус, знающий СВОИ числа, разъезжается с реестром."""

    SEED = 20260809
    N = 120

    def _space(self):
        rng = random.Random(self.SEED)
        for _ in range(self.N):
            width = rng.choice([None, rng.uniform(600.0, 5_000.0)])
            floor_r = 1.0 if width is None else width / 2.0
            yield {
                "center_mm": [rng.uniform(-50_000.0, 50_000.0),
                              rng.uniform(-50_000.0, 50_000.0)],
                # строго больше половины ширины и не выше потолка API
                "radius_mm": rng.uniform(floor_r + 1e-6, 40_000.0),
                "start_angle_deg": rng.uniform(-720.0, 720.0),
                "included_angle_deg": rng.uniform(1e-6,
                                                  _SPIRAL_MAX_INCLUDED_DEG),
                "clockwise": rng.random() < 0.5,
            }, width

    def test_every_legal_point_compiles_and_carries_its_own_numbers(self) -> None:
        seen = 0
        for spiral, width in self._space():
            extra = {"spiral": spiral}
            if width is not None:
                extra["width_mm"] = width
            out = _compile(extra)
            self.assertTrue(out.ok, (spiral, width, _codes(out)))
            match = _CALL_RE.search(out.csharp)
            self.assertIsNotNone(match, out.csharp[:400])
            cx, cy, radius, start, included, cw = match.groups()
            # ЧИСЛО, ДОЕХАВШЕЕ ДО C#, — ЭТО ЧИСЛО, КОТОРОЕ ПРОСИЛИ. Градусы
            # переводит питон на компиляции, поэтому обратный перевод обязан
            # совпасть с точностью double, а не «примерно».
            self.assertEqual(float(cx), spiral["center_mm"][0])
            self.assertEqual(float(cy), spiral["center_mm"][1])
            self.assertEqual(float(radius), spiral["radius_mm"])
            self.assertAlmostEqual(math.degrees(float(start)),
                                   spiral["start_angle_deg"], places=9)
            self.assertAlmostEqual(math.degrees(float(included)),
                                   spiral["included_angle_deg"], places=9)
            self.assertEqual(cw, "true" if spiral["clockwise"] else "false")
            # Направление задаёт ФЛАГ, а не знак угла: отрицательного размаха
            # в эмиссии быть не может ни при каком входе.
            self.assertGreater(float(included), 0.0)
            # Скобки сходятся, и программа по-прежнему одна.
            self.assertEqual(out.csharp.count("{"), out.csharp.count("}"))
            seen += 1
        self.assertEqual(seen, self.N)

    def test_just_outside_the_box_it_always_refuses_and_never_raises(self) -> None:
        rng = random.Random(self.SEED + 1)
        for _ in range(self.N):
            broken = dict(SPIRAL)
            which = rng.randrange(4)
            if which == 0:
                broken["radius_mm"] = -rng.uniform(0.0, 10_000.0)
            elif which == 1:
                broken["radius_mm"] = _SPIRAL_RADIUS_MAX_MM + rng.uniform(
                    1.0, 1e6)
            elif which == 2:
                broken["included_angle_deg"] = -rng.uniform(0.0, 720.0)
            else:
                broken["included_angle_deg"] = (
                    _SPIRAL_MAX_INCLUDED_DEG + rng.uniform(1e-6, 3_600.0))
            out = _compile({"spiral": broken})
            self.assertFalse(out.ok, broken)
            self.assertIn("KIR-T002", _codes(out))
            # Отказ — это ОТСУТСТВИЕ эмиссии, а не C# «на всякий случай».
            self.assertFalse(out.csharp)


if __name__ == "__main__":
    unittest.main()
