"""wave/arch (2026-07-29): create_ceiling / create_railing.

ПОЧЕМУ ЭТА ВОЛНА. Полный слепок настоящей рабочей документации
(13A-RD-AR-K2_v33, башня 59 этажей, 55 293 элемента) показал, что часть модели
не выражается компилятором не потому, что лифтер кривой, а потому, что
ОПЕРАЦИИ НЕТ ВООБЩЕ: в реестре 32 писателя, и среди них не было ни потолков,
ни ограждений — содержимого, которое есть в КАЖДОМ архитектурном проекте.
Причина 611 в карте причин лифта (коммит 9c63cc4e) называет их поимённо:
StairsRailing 203 и Ceilings 81 на K2.

Структура повторяет test_struct.py 1:1 (Ground / VersionAxis / Negative /
CommitGateInvariants / PBT) — тот же граф инвариантов, что доказан для
create_beam/create_foundation.

ОСЬ ВЕРСИЙ ЗАМЕРЕНА КОМПИЛЯЦИЕЙ, А НЕ ПАМЯТЬЮ (дом: extract.py про
_CATEGORY_SPECS — «в RevitAPI.xml членов BuiltInCategory нет вовсе, поэтому
единственный честный способ проверки — компайл-сервис»). Замер 29.07 по
шести версиям через :52412:

    Ceiling.Create(doc, IList<CurveLoop>, typeId, levelId)   2022-2026 (5/6)
        2021: CS0117 'Ceiling' does not contain a definition for 'Create'
    doc.Create.NewCeiling(...)                               НИ ОДНОЙ (0/6)
        CS1061 'Document' does not contain a definition for 'NewCeiling'
    Railing.Create(doc, CurveLoop, typeId, levelId)          2021-2026 (6/6)
    Railing.Create(doc, hostId, typeId, RailingPlacementPosition)  6/6
    RailingPlacementPosition.Treads / .Stringer              6/6
        .Left/.Right/.Landing/.Run/.None/.Center             НИ ОДНОЙ (0/6)
    ElementTypeGroup.CeilingType                             6/6
    ElementTypeGroup.RailingType                             НИ ОДНОЙ (0/6)
    BuiltInParameter.CEILING_HEIGHTABOVELEVEL_PARAM          6/6
    BuiltInParameter.STAIRS_RAILING_BASE_LEVEL_PARAM         6/6

Из этого замера следуют ДВА структурных вывода, а не один:

1. У потолка на 2021 нет НИКАКОГО пути создания — не «другой перегрузки», а
   вообще никакого. Значит единственный честный ответ на 2021 — типизированный
   отказ KIR-E003, ровно как у create_floor с отверстиями.
2. У ограждения, в отличие от перекрытия, НЕТ типа по умолчанию в документе
   (ElementTypeGroup.RailingType не существует ни на одной версии). Значит
   create_railing НЕ вправе подставлять «умолчание»: пропущенный type идёт по
   общему правилу ground.py — единственный в пуле или типизированный отказ.
   Это и есть §18.1 «тихая потеря запрещена» на практике.
"""
import os
import random
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(),
                                   "kir_test_arch_queue.jsonl"))

from kukai.ir import spec                                    # noqa: E402
from kukai.ir.compiler import compile_program                # noqa: E402
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT as SNAPSHOT  # noqa: E402

LVL = {"by": "element_id", "value": 42}

#: Прямоугольник 2.5x2.5 м — площадь заведомо больше вырожденного порога.
SQUARE = [[0, 0], [2500, 0], [2500, 2500], [0, 2500]]


def _prog(ops, intent="arch-test"):
    return {"ir_version": "1.0", "intent": intent, "ops": ops}


def _ceiling(oid="C1", **kw):
    op = {"op": "create_ceiling", "id": oid, "outline": SQUARE, "level": LVL}
    op.update(kw)
    return op


def _railing_path(oid="R1", **kw):
    op = {"op": "create_railing", "id": oid, "variety": "path",
          "path": [[0, 0], [3000, 0]], "level": LVL}
    op.update(kw)
    return op


def _railing_hosted(oid="R1", **kw):
    op = {"op": "create_railing", "id": oid, "variety": "hosted",
          "host": {"by": "element_id", "value": 777}, "position": "treads"}
    op.update(kw)
    return op


def _codes(out):
    return [d.code for d in out.diagnostics]


# ── реестр ───────────────────────────────────────────────────────────────────

class RegistryShape(unittest.TestCase):

    def test_both_ops_are_registered(self):
        self.assertIn("create_ceiling", spec.OPS)
        self.assertIn("create_railing", spec.OPS)

    def test_they_declare_themselves_as_writers(self):
        for name in ("create_ceiling", "create_railing"):
            with self.subTest(op=name):
                self.assertTrue(spec.OPS[name].writes_model)
                self.assertEqual(spec.OPS[name].family, "authoring")

    def test_the_type_pools_are_their_own(self):
        """Потолок НЕ грунтуется по floor_types, ограждение — по своему пулу.
        Чужой пул дал бы правдоподобный, но неверный тип: это ровно та тихая
        подстановка, которую §18.1 запрещает."""
        ceiling = {p: pool for p, pool, _ in spec.OPS["create_ceiling"].grounded}
        railing = {p: pool for p, pool, _ in spec.OPS["create_railing"].grounded}
        self.assertEqual(ceiling["type"], "ceiling_types")
        self.assertEqual(railing["type"], "railing_types")


# ── ось версий: потолок ──────────────────────────────────────────────────────

class CeilingVersionAxis(unittest.TestCase):

    def test_it_builds_on_2022_and_later(self):
        for ver in ("2022", "2023", "2024", "2025", "2026"):
            with self.subTest(version=ver):
                out = compile_program(_prog([_ceiling()]),
                                      revit_version=ver, snapshot=SNAPSHOT)
                self.assertTrue(out.ok, _codes(out)[:3])
                self.assertIn("Ceiling.Create(", out.csharp)

    def test_2021_is_a_typed_refusal_not_a_silent_substitute(self):
        """На 2021 у потолка нет НИ ОДНОГО пути создания (замер: Ceiling.Create
        отсутствует, doc.Create.NewCeiling не существует ни на одной версии).
        Молча построить вместо потолка перекрытие было бы худшим из возможных
        исходов — «сделал что-то другое» читается как успех."""
        out = compile_program(_prog([_ceiling()]),
                              revit_version="2021", snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-E003", _codes(out))

    def test_the_2021_refusal_says_why(self):
        out = compile_program(_prog([_ceiling()]),
                              revit_version="2021", snapshot=SNAPSHOT)
        message = " ".join(d.message_ru or "" for d in out.diagnostics)
        self.assertIn("2021", message)
        self.assertIn("Ceiling.Create", message)

    def test_2021_never_emits_a_floor_instead(self):
        out = compile_program(_prog([_ceiling()]),
                              revit_version="2021", snapshot=SNAPSHOT)
        self.assertNotIn("NewFloor", out.csharp or "")
        self.assertNotIn("Floor.Create", out.csharp or "")


# ── ось версий: ограждение ───────────────────────────────────────────────────

class RailingVersionAxis(unittest.TestCase):

    def test_the_path_variety_builds_on_all_six(self):
        """У ограждения оси версий НЕТ — замерено 6/6. Если когда-нибудь
        появится, этот тест увидит это первым."""
        for ver in spec.REVIT_VERSIONS:
            with self.subTest(version=ver):
                out = compile_program(_prog([_railing_path()]),
                                      revit_version=ver, snapshot=SNAPSHOT)
                self.assertTrue(out.ok, _codes(out)[:3])
                self.assertIn("Railing.Create(", out.csharp)

    def test_the_hosted_variety_builds_on_all_six(self):
        for ver in spec.REVIT_VERSIONS:
            with self.subTest(version=ver):
                out = compile_program(_prog([_railing_hosted()]),
                                      revit_version=ver, snapshot=SNAPSHOT)
                self.assertTrue(out.ok, _codes(out)[:3])
                self.assertIn("RailingPlacementPosition.Treads", out.csharp)


# ── геометрия пути ───────────────────────────────────────────────────────────

class RailingPathIsNotARing(unittest.TestCase):
    """Путь ограждения — ОТКРЫТАЯ ломаная, а не замкнутый контур.

    Именно поэтому у него свой род параметра `path`, а не `pts`: `pts`
    требует >=3 точек И ненулевой ПЛОЩАДИ (authoring.py, ветка "pts"), то есть
    по построению описывает кольцо. Прямое ограждение вдоль лестничного марша
    — две точки и нулевая площадь; под `pts` оно было бы отвергнуто как
    «вырожденный контур», а замкнутое под `pts` ограждение вернулось бы в
    модель лишним замыкающим сегментом, которого в источнике нет."""

    def test_two_points_are_a_legal_railing(self):
        out = compile_program(_prog([_railing_path()]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, _codes(out)[:3])

    def test_a_single_point_is_refused(self):
        out = compile_program(_prog([_railing_path(path=[[0, 0]])]),
                              snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T001", _codes(out))

    def test_the_path_is_not_closed_behind_our_back(self):
        """Три точки буквой Г: сегментов обязано быть ДВА, не три."""
        out = compile_program(
            _prog([_railing_path(path=[[0, 0], [3000, 0], [3000, 3000]])]),
            snapshot=SNAPSHOT)
        self.assertTrue(out.ok, _codes(out)[:3])
        self.assertEqual(out.csharp.count("Line.CreateBound"), 2)

    def test_a_zero_length_segment_is_refused(self):
        out = compile_program(
            _prog([_railing_path(path=[[0, 0], [0, 0]])]), snapshot=SNAPSHOT)
        self.assertFalse(out.ok)


# ── отказ вместо тихой подстановки ───────────────────────────────────────────

class NoSilentLoss(unittest.TestCase):
    """§18.1. Прошлый счёт этой ошибки известен: «0 градусов вместо
    отсутствия угла» стоил 96% групп."""

    def test_a_missing_path_on_the_path_variety_is_typed(self):
        op = _railing_path()
        del op["path"]
        out = compile_program(_prog([op]), snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-P005", _codes(out))

    def test_a_missing_host_on_the_hosted_variety_is_typed(self):
        op = _railing_hosted()
        del op["host"]
        out = compile_program(_prog([op]), snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-P005", _codes(out))

    def test_an_unknown_variety_is_typed(self):
        """KIR-T001: значение вне `choices` в этом доме — TYPE_BAD_TYPE
        (authoring.py, ветка "enum"), а не отдельный код перечисления."""
        out = compile_program(_prog([_railing_path(variety="ramp_side")]),
                              snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T001", _codes(out))

    def test_an_unknown_position_is_typed(self):
        """«Левое/правое» — первое, что напишет человек по памяти, и в API
        этого нет: RailingPlacementPosition.Left не компилируется ни на одной
        из шести версий. Закрытый список бережёт от такой догадки на входе."""
        out = compile_program(_prog([_railing_hosted(position="left")]),
                              snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T001", _codes(out))

    def test_an_ambiguous_railing_type_never_picks_the_first(self):
        """У ограждения нет типа по умолчанию в документе (замер:
        ElementTypeGroup.RailingType не существует). Два типа в пуле и
        пропущенный `type` обязаны дать вопрос, а не выбор за пользователя."""
        snapshot = dict(SNAPSHOT)
        snapshot["railing_types"] = [{"id": 1200, "name": "Перила 900"},
                                     {"id": 1201, "name": "Перила 1200"}]
        out = compile_program(_prog([_railing_path()]), snapshot=snapshot)
        self.assertFalse(out.ok)

    def test_the_ceiling_height_offset_is_carried_when_given(self):
        out = compile_program(_prog([_ceiling(height_offset_mm=-250)]),
                              revit_version="2024", snapshot=SNAPSHOT)
        self.assertTrue(out.ok, _codes(out)[:3])
        self.assertIn("CEILING_HEIGHTABOVELEVEL_PARAM", out.csharp)

    def test_an_absent_ceiling_offset_stays_absent(self):
        """Отсутствие смещения — не ноль. Байтовая стабильность: без
        параметра в C# не должно быть ни установки, ни свидетеля."""
        out = compile_program(_prog([_ceiling()]),
                              revit_version="2024", snapshot=SNAPSHOT)
        self.assertTrue(out.ok, _codes(out)[:3])
        self.assertNotIn("CEILING_HEIGHTABOVELEVEL_PARAM", out.csharp)


# ── инварианты исполнения ────────────────────────────────────────────────────

class CommitGateInvariants(unittest.TestCase):

    def _csharp(self, op, ver="2024"):
        out = compile_program(_prog([op]), revit_version=ver, snapshot=SNAPSHOT)
        self.assertTrue(out.ok, _codes(out)[:3])
        return out.csharp

    def test_one_transaction_each(self):
        for name, op in (("ceiling", _ceiling()),
                         ("railing_path", _railing_path()),
                         ("railing_hosted", _railing_hosted())):
            with self.subTest(op=name):
                self.assertEqual(self._csharp(op).count("new Transaction("), 1)

    def test_regenerate_precedes_postconditions(self):
        for name, op in (("ceiling", _ceiling()),
                         ("railing_path", _railing_path())):
            with self.subTest(op=name):
                cs = self._csharp(op)
                self.assertIn("doc.Regenerate()", cs)
                self.assertLess(cs.index("doc.Regenerate()"),
                                cs.index("__post.Add("))

    def test_every_creation_is_stamped(self):
        for name, op in (("ceiling", _ceiling()),
                         ("railing_path", _railing_path()),
                         ("railing_hosted", _railing_hosted())):
            with self.subTest(op=name):
                self.assertIn("__stamp", self._csharp(op))

    def test_a_null_result_is_a_refusal_not_a_success(self):
        for name, op in (("ceiling", _ceiling()),
                         ("railing_path", _railing_path()),
                         ("railing_hosted", _railing_hosted())):
            with self.subTest(op=name):
                self.assertIn("== null", self._csharp(op))


# ── свойство ─────────────────────────────────────────────────────────────────

class ArchPBT(unittest.TestCase):

    def test_well_typed_ceilings_always_compile_on_2026(self):
        rng = random.Random(29072026)
        for i in range(40):
            w = rng.randrange(1000, 20000)
            h = rng.randrange(1000, 20000)
            x0 = rng.randrange(-50000, 50000)
            y0 = rng.randrange(-50000, 50000)
            outline = [[x0, y0], [x0 + w, y0], [x0 + w, y0 + h], [x0, y0 + h]]
            op = _ceiling(oid=f"C{i}", outline=outline)
            if rng.random() < 0.5:
                op["height_offset_mm"] = rng.randrange(-3000, 3000)
            with self.subTest(i=i):
                out = compile_program(_prog([op]), revit_version="2026",
                                      snapshot=SNAPSHOT)
                self.assertTrue(out.ok, _codes(out)[:3])

    def test_well_typed_railings_always_compile_on_2021(self):
        rng = random.Random(29072027)
        for i in range(40):
            n = rng.randrange(2, 8)
            path = []
            x, y = rng.randrange(-20000, 20000), rng.randrange(-20000, 20000)
            for _ in range(n):
                path.append([x, y])
                x += rng.choice([-1, 1]) * rng.randrange(500, 5000)
                y += rng.choice([-1, 1]) * rng.randrange(500, 5000)
            with self.subTest(i=i):
                out = compile_program(_prog([_railing_path(oid=f"R{i}",
                                                           path=path)]),
                                      revit_version="2021", snapshot=SNAPSHOT)
                self.assertTrue(out.ok, _codes(out)[:3])


if __name__ == "__main__":
    unittest.main()
