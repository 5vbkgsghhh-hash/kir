"""wave/room (2026-08-03): create_room_separator — разделитель помещений.

ПОЧЕМУ ЭТА ВОЛНА. Офлайн-вердикт пригодности построен и работает, но на
настоящем здании МОЛЧИТ: программа замыкает стенами лишь часть помещений.
Замер по k2_ar_rd_v9 (независимо воспроизведён прибором, а не вспомнен):

    помещений всего                              2 442
    ограничены ТОЛЬКО стенами                      936
    среди ограничителей есть разделитель          1 091
    стены + структурные колонны                     126
    ни одного ограничителя (не размещены)          289

    OST_RoomSeparationLines в L0                 2 313
    из них ограничивают РОВНО ДВЕ комнаты          749   ← готовые рёбра графа
    ограничивают одну                            1 358
    ограничивают три                                34
    ни одной                                       172

То есть 1 091 помещение из 2 442 нельзя замкнуть НИ ОДНОЙ программой KIR,
пока разделителя нет в языке, а 749 линий — это рёбра смежности, которые
_semantic_fold сегодня выбрасывает. Операции не было; лифтер отправлял все
2 313 элементов в атомы с причиной `no_lifter` («операции нет вовсе»).

ИМЯ API ПРОВЕРЕНО ИНДЕКСОМ ЛОВУШЕК И КОМПИЛЯЦИЕЙ, А НЕ ПАМЯТЬЮ
(data/api_traps/revit_api_traps.sqlite, 35 516 членов × 6 версий):

    Autodesk.Revit.Creation.Document.NewRoomBoundaryLines(
        SketchPlane, CurveArray, View) -> ModelCurveArray     2021-2026 (6/6)
    SketchPlane.Create(Document, ElementId)                   6/6
        summary: «Creates a sketch plane from a grid, reference plane,
                  or LEVEL» — то есть плоскость берётся У САМОГО УРОВНЯ
    ViewPlan.GenLevel / IsTemplate / ViewType.FloorPlan       6/6
    Element.LevelId                                           6/6
    new ElementId(BuiltInCategory.…)                          6/6
    Category.BuiltInCategory                          ТОЛЬКО 2023-2026 (4/6)
    ElementId.IntegerValue                            НЕТ на 2026 (5/6)

Последние две строки — не сноска, а причина формы свидетеля: категорию
сегмента приходится сверять через `Category.Id` и `new ElementId(BIC)`, а
не через удобное `Category.BuiltInCategory` и не через `IntegerValue`.

Структура повторяет test_arch.py (Registry / VersionAxis / Geometry /
NoSilentLoss / CommitGateInvariants / PBT).
"""
import os
import random
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(),
                                   "kir_test_room_queue.jsonl"))

from kukai.ir import spec                                        # noqa: E402
from kukai.ir.compiler import compile_program                    # noqa: E402
from kukai.ir.registry_base import IdentityCardinality           # noqa: E402
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT as SNAPSHOT  # noqa: E402

LVL = {"by": "element_id", "value": 42}

OP = "create_room_separator"


def _prog(ops, intent="room-test"):
    return {"ir_version": "1.0", "intent": intent, "ops": ops}


def _sep(oid="S1", **kw):
    op = {"op": OP, "id": oid, "path": [[0, 0], [3000, 0]], "level": LVL}
    op.update(kw)
    return op


def _codes(out):
    return [d.code for d in out.diagnostics]


# ── реестр ───────────────────────────────────────────────────────────────────

class RegistryShape(unittest.TestCase):

    def test_the_op_is_registered(self):
        self.assertIn(OP, spec.OPS)

    def test_it_declares_itself_a_writer(self):
        self.assertTrue(spec.OPS[OP].writes_model)
        self.assertEqual(spec.OPS[OP].family, "authoring")

    def test_it_lives_in_its_own_registry_module(self):
        """Волны добавляют опы ПАРАЛЛЕЛЬНО, не трогая чужой ops_*.py."""
        from kukai.ir import ops_room
        self.assertEqual([op.name for op in ops_room.OPS], [OP])

    def test_the_result_carries_many_identities_not_one(self):
        """Ломаная из n точек создаёт n-1 ModelCurve. Объявить ОДНУ личность
        значило бы соврать про всё, кроме прямого отрезка, — и спрятать
        созданные элементы, которых квитанция не назвала."""
        result = spec.OPS[OP].result
        self.assertIs(result.identity_cardinality, IdentityCardinality.MANY)
        self.assertEqual(result.identity_field, "segment_ids")
        self.assertFalse(result.referenceable)

    def test_it_grounds_only_the_level(self):
        """У NewRoomBoundaryLines НЕТ аргумента типа/стиля, поэтому у опа нет
        параметра `type`: грунтовать нечего, и выдуманный пул был бы
        обещанием, которого API не выполняет."""
        self.assertEqual(
            {p: pool for p, pool, _ in spec.OPS[OP].grounded},
            {"level": "levels"})
        self.assertNotIn("type", {p.name for p in spec.OPS[OP].params})

    def test_the_path_is_its_own_param_kind(self):
        """`path`, а не `pts`: `pts` требует >=3 точек и НЕНУЛЕВОЙ ПЛОЩАДИ,
        то есть по построению кольцо. Разделитель чаще всего — один отрезок
        между двумя стенами (замер K2: 2 313 элементов, КАЖДЫЙ — один
        сегмент), и под `pts` он был бы отвергнут как вырожденный контур."""
        kinds = {p.name: p.kind for p in spec.OPS[OP].params}
        self.assertEqual(kinds["path"], "path")


# ── ось версий ───────────────────────────────────────────────────────────────

class VersionAxis(unittest.TestCase):

    def test_it_builds_on_all_six(self):
        """Оси версий у этого опа НЕТ — замерено 6/6 индексом ловушек и
        компиляцией. Если она когда-нибудь появится, этот тест увидит её
        первым."""
        for ver in spec.REVIT_VERSIONS:
            with self.subTest(version=ver):
                out = compile_program(_prog([_sep()]),
                                      revit_version=ver, snapshot=SNAPSHOT)
                self.assertTrue(out.ok, _codes(out)[:3])
                self.assertIn("NewRoomBoundaryLines(", out.csharp)

    def test_it_never_reads_a_member_absent_on_2026(self):
        """ElementId.IntegerValue снят в 2026 (замер компиляцией: CS1061), а
        Category.BuiltInCategory появился лишь в 2023. Ни того, ни другого в
        эмиссии быть не должно ни на одной версии."""
        for ver in spec.REVIT_VERSIONS:
            with self.subTest(version=ver):
                cs = compile_program(_prog([_sep()]), revit_version=ver,
                                     snapshot=SNAPSHOT).csharp
                self.assertNotIn("IntegerValue", cs)
                self.assertNotIn(".BuiltInCategory", cs)


# ── геометрия: ломаная, а не кольцо ──────────────────────────────────────────

class PathIsNotARing(unittest.TestCase):

    def test_two_points_are_one_segment(self):
        out = compile_program(_prog([_sep()]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, _codes(out)[:3])
        self.assertEqual(out.csharp.count("Line.CreateBound"), 1)

    def test_three_points_are_two_segments_not_three(self):
        """Замыкающего сегмента не подразумевается: линия, которой нет в
        источнике, отрезала бы от помещения кусок, которого никто не просил."""
        out = compile_program(
            _prog([_sep(path=[[0, 0], [3000, 0], [3000, 3000]])]),
            snapshot=SNAPSHOT)
        self.assertTrue(out.ok, _codes(out)[:3])
        self.assertEqual(out.csharp.count("Line.CreateBound"), 2)

    def test_a_closed_ring_is_expressible_by_repeating_the_first_point(self):
        """Помещение, замкнутое ОДНИМИ разделителями, выражается ломаной,
        последняя точка которой совпадает с первой: 5 точек → 4 сегмента."""
        ring = [[0, 0], [3000, 0], [3000, 3000], [0, 3000], [0, 0]]
        out = compile_program(_prog([_sep(path=ring)]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, _codes(out)[:3])
        self.assertEqual(out.csharp.count("Line.CreateBound"), 4)

    def test_a_single_point_is_refused(self):
        out = compile_program(_prog([_sep(path=[[0, 0]])]), snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T001", _codes(out))

    def test_a_zero_length_segment_is_refused(self):
        """Порог 1 мм — общий для рода `path`: Revit такую кривую не строит
        (ArgumentsInconsistentException «curve length is too small», индекс
        ловушек)."""
        out = compile_program(_prog([_sep(path=[[0, 0], [0, 0.5]])]),
                              snapshot=SNAPSHOT)
        self.assertFalse(out.ok)


# ── плоскость берётся у уровня, а не считается нами ──────────────────────────

class PlaneComesFromTheLevel(unittest.TestCase):

    def test_the_sketch_plane_is_built_from_the_level_itself(self):
        """SketchPlane.Create(doc, ElementId) документирован как «плоскость
        из оси, опорной плоскости ИЛИ УРОВНЯ» (summary в индексе ловушек).
        Считать отметку самим — значит завести второго судью о том, где
        находится уровень."""
        cs = compile_program(_prog([_sep()]), snapshot=SNAPSHOT).csharp
        self.assertIn("SketchPlane.Create(doc, __lv_S1.Id)", cs)
        self.assertNotIn("Plane.CreateByNormalAndOrigin", cs)

    def test_the_curve_elevation_is_read_live_from_the_level(self):
        """Отметка кривой — MM(__lv.Elevation), прочитанная В РАНТАЙМЕ:
        компилятор не знает отметки уровня, адресованного именем или ссылкой,
        и подставить своё число значило бы построить разделитель не там."""
        cs = compile_program(_prog([_sep()]), snapshot=SNAPSHOT).csharp
        self.assertIn("MM(__lv_S1.Elevation)", cs)


# ── вид плана: выбор НАЗВАН, а не сделан молча ───────────────────────────────

class ViewChoiceIsNamed(unittest.TestCase):

    def test_the_view_is_derived_from_the_level_not_from_the_active_view(self):
        """doc.ActiveView — ровно тот молчаливый выбор, ради запрета которого
        написано НАЗВАННОЕ УМОЛЧАНИЕ: результат зависел бы от того, на что
        пользователь смотрит."""
        cs = compile_program(_prog([_sep()]), snapshot=SNAPSHOT).csharp
        self.assertNotIn("ActiveView", cs)
        self.assertIn("GenLevel", cs)
        self.assertIn("ViewType.FloorPlan", cs)

    def test_a_template_view_is_never_chosen(self):
        cs = compile_program(_prog([_sep()]), snapshot=SNAPSHOT).csharp
        self.assertIn("IsTemplate", cs)

    def test_the_absence_of_a_plan_view_is_a_refusal_not_a_guess(self):
        cs = compile_program(_prog([_sep()]), snapshot=SNAPSHOT).csharp
        self.assertIn("stale_or_failed", cs)

    def test_the_chosen_view_reaches_the_receipt(self):
        """Умолчание НАЗВАНО ровно тогда, когда его видно снаружи."""
        cs = compile_program(_prog([_sep()]), snapshot=SNAPSHOT).csharp
        for key in ('"view_id"', '"view_name"', '"view_candidates"'):
            with self.subTest(key=key):
                self.assertIn(key, cs)


# ── свидетели ────────────────────────────────────────────────────────────────

class WitnessesCoverThePromise(unittest.TestCase):

    def _cs(self):
        out = compile_program(_prog([_sep(path=[[0, 0], [3000, 0],
                                               [3000, 3000]])]),
                              snapshot=SNAPSHOT)
        self.assertTrue(out.ok, _codes(out)[:3])
        return out.csharp

    def test_the_number_of_created_segments_is_witnessed(self):
        """Ломаная из 3 точек обязана дать РОВНО 2 кривые. Меньше — потеря,
        больше — мусор; и то и другое снаружи выглядит успехом."""
        self.assertIn("__segs_S1.Count != 2", self._cs())

    def test_the_category_of_every_segment_is_witnessed(self):
        """Это сердце опа: доказать, что мы построили РАЗДЕЛИТЕЛЬ, а не
        обычную модельную линию. Линия «на том же месте» ничего не
        ограничивает и снаружи неотличима."""
        cs = self._cs()
        self.assertIn("OST_RoomSeparationLines", cs)

    def test_the_level_of_every_segment_is_witnessed(self):
        self.assertIn("LevelId", self._cs())

    def test_the_endpoints_are_witnessed_against_the_path(self):
        self.assertIn("GetEndPoint(", self._cs())

    def test_every_promise_clause_has_a_witness(self):
        """Сертификат перевода бьёт `post` по точке с запятой и требует
        свидетеля на КАЖДЫЙ кусок."""
        from kukai.ir.translation_cert import audit_registry_coverage
        problems = [p for p in audit_registry_coverage() if OP in p]
        self.assertEqual(problems, [])

    def test_the_tolerance_comes_from_the_registry(self):
        """ЗАКОН ПРОВЕНАНСА: число допуска попадает в C# только объектом,
        отчеканенным реестром. Тронь число в реестре — байты обязаны поехать."""
        self.assertIn("endpoint_mm", spec.OPS[OP].tolerances)
        cs = self._cs()
        self.assertIn(str(spec.OPS[OP].tolerances["endpoint_mm"]), cs)


# ── инварианты исполнения ────────────────────────────────────────────────────

class CommitGateInvariants(unittest.TestCase):

    def _csharp(self, op, ver="2024"):
        out = compile_program(_prog([op]), revit_version=ver, snapshot=SNAPSHOT)
        self.assertTrue(out.ok, _codes(out)[:3])
        return out.csharp

    def test_one_transaction(self):
        self.assertEqual(self._csharp(_sep()).count("new Transaction("), 1)

    def test_regenerate_precedes_postconditions(self):
        cs = self._csharp(_sep())
        self.assertIn("doc.Regenerate()", cs)
        self.assertLess(cs.index("doc.Regenerate()"), cs.index("__post.Add("))

    def test_every_creation_is_stamped(self):
        self.assertIn("__stamp", self._csharp(_sep()))

    def test_a_null_result_is_a_refusal_not_a_success(self):
        self.assertIn("== null", self._csharp(_sep()))

    def test_it_survives_per_op_isolation(self):
        """Переменные, которые читает блок постусловий, обязаны быть объявлены
        во ВНЕШНЕЙ области: при isolation="per_op" create и post попадают в
        разные области видимости (живые грабли волны ограждений, CS0103)."""
        from kukai.ir.compiler import compile_program as cp
        out = cp(_prog([_sep()]), snapshot=SNAPSHOT, isolation="per_op")
        self.assertTrue(out.ok, _codes(out)[:3])
        self.assertIn("SubTransaction", out.csharp)


# ── обратный ход ─────────────────────────────────────────────────────────────

class ReverseContract(unittest.TestCase):

    def test_the_manifest_declares_a_direct_inverse(self):
        from kukai.ir.reverse_contract import REVERSE_CONTRACTS, ReverseMode
        contract = REVERSE_CONTRACTS[OP]
        self.assertIs(contract.mode, ReverseMode.DIRECT)
        self.assertIn("_lift_room_separator", contract.entrypoints)

    def test_the_category_is_in_the_lifter_table(self):
        from kukai.ir.decompile.lift import LIFTER_TABLE
        self.assertEqual(LIFTER_TABLE["OST_RoomSeparationLines"][1], OP)


# ── приёмка ──────────────────────────────────────────────────────────────────

class AcceptanceKnowsTheOp(unittest.TestCase):

    def test_the_expected_count_is_segments_not_one(self):
        """Приёмка обязана ждать n-1 элементов, а не один: иначе программа,
        построившая 1 линию вместо 4, прошла бы её."""
        from kukai.ir.acceptance import derive_expectation
        expectation = derive_expectation(_prog([
            _sep(path=[[0, 0], [3000, 0], [3000, 3000], [0, 3000]])]))
        rows = [r for r in expectation.rows
                if "OST_RoomSeparationLines" in r.categories]
        self.assertEqual([r.count for r in rows], [3])

    def test_the_op_is_not_blind(self):
        from kukai.ir.acceptance import derive_expectation
        expectation = derive_expectation(_prog([_sep()]))
        self.assertEqual(expectation.blind_ops, ())


# ── свойство ─────────────────────────────────────────────────────────────────

class RoomPBT(unittest.TestCase):

    def test_well_typed_separators_always_compile_on_every_version(self):
        rng = random.Random(3082026)
        for i in range(40):
            n = rng.randrange(2, 12)
            path = []
            x, y = rng.randrange(-20000, 20000), rng.randrange(-20000, 20000)
            for _ in range(n):
                path.append([x, y])
                if rng.random() < 0.5:
                    x += rng.choice([-1, 1]) * rng.randrange(500, 5000)
                else:
                    y += rng.choice([-1, 1]) * rng.randrange(500, 5000)
            ver = rng.choice(spec.REVIT_VERSIONS)
            with self.subTest(i=i, version=ver):
                out = compile_program(_prog([_sep(oid=f"S{i}", path=path)]),
                                      revit_version=ver, snapshot=SNAPSHOT)
                self.assertTrue(out.ok, _codes(out)[:3])


if __name__ == "__main__":
    unittest.main()
