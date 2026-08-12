"""wave/placement (2026-08-11): place_family по РОДУ РАЗМЕЩЕНИЯ.

ПОВОД ЗАМЕРЕН ПО КОРПУСУ, А НЕ ВЫБРАН. `tools/coverage_matrix.py` по всему
корпусу разборов — 11 РАЗЛИЧНЫХ документов (76 каталогов это каталоги, а не
здания) — ранжирует причины атомов по ДВУМ числам сразу, и отказ лифтера
«place_family ставит только точечные размещения (OneLevelBased/
OneLevelBasedHosted)» стоит так:

    'WorkPlaneBased'    483 эл. на 7 документах из 11
    'TwoLevelsBased'   9392 эл. на 4 документах
    'ViewBased'         999 эл. на 3 документах   ← НЕ взят
    'CurveBasedDetail'  862 эл. на 3 документах   ← НЕ взят

Семь документов из одиннадцати — самый широкий разброс по зданиям среди всех
действенных строк корпуса, а по логике самой карты покрытия широкий разброс
означает, что неверно НАШЕ правило вообще, а не особенность одного проекта.

API СНЯТ С СБОРОК (11.08, рефлексия по шести `RevitAPI.dll` + живая
компиляция на :52412 отдельным прогоном на каждую версию):

    NewFamilyInstance(XYZ, FamilySymbol, XYZ refDir, Element,
                      StructuralType)                              6/6
    NewFamilyInstance(Reference, XYZ, XYZ, FamilySymbol)           6/6
    FamilyPlacementType — все 10 членов                            6/6
    FamilyInstance.HandOrientation / FacingOrientation / Host      6/6
    FAMILY_TOP_LEVEL_PARAM / FAMILY_*_LEVEL_OFFSET_PARAM           6/6

ЛОВУШКА ЧТЕНИЯ РЕФЛЕКСИИ, ЗАМЕРЕННАЯ ПОПУТНО: перегрузка
`(XYZ, FamilySymbol, Level, StructuralType)` объявлена на
`Creation.Document` в 2021-2023 и на `Creation.ItemFactoryBase` в 2024-2026.
Она НЕ ИСЧЕЗАЛА — она переехала по цепочке наследования, а дамп ОБЪЯВЛЕННЫХ
членов показывает это как пропажу на трёх версиях. Тот же капкан, что у
`SpatialElement.Name`: спрашивать надо цепочку, а не класс.
"""
import os
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(),
                                   "kir_test_placement_queue.jsonl"))

from kukai.ir import spec                                        # noqa: E402
from kukai.ir.compiler import compile_program                    # noqa: E402
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT as SNAPSHOT  # noqa: E402

OP = "place_family"
LVL = {"by": "name", "value": SNAPSHOT["levels"][0]["name"]}


def _prog(ops, intent="placement-test"):
    return {"ir_version": "1.0", "intent": intent, "ops": ops}


def _codes(out):
    return [d.code for d in out.diagnostics]


def _wall(oid="W1"):
    return {"op": "create_wall", "id": oid, "p0_mm": [0, 0],
            "p1_mm": [8000, 0], "level": LVL}


def _work_plane(**kw):
    op = {"op": OP, "id": "P1", "xyz": [4000, 0, 1200], "level": LVL,
          "host": {"by": "ref", "value": "W1"}, "ref_dir": [1, 0, 0]}
    op.update(kw)
    return [_wall(), op]


def _two_levels(**kw):
    op = {"op": OP, "id": "P1", "xyz": [1000, 2000, 0], "level": LVL,
          "top_level": {"by": "ref", "value": "LT"}}
    op.update(kw)
    return [{"op": "create_level", "id": "LT", "elev_mm": 6000,
             "name": "КИР-В"}, op]


def _checks_of(ops):
    from kukai.ir import ground as ground_mod
    from kukai.ir.authoring import _EMITTERS
    from kukai.ir.compiler import _parse_and_check
    grounded = ground_mod.ground(_parse_and_check(_prog(ops)), SNAPSHOT)
    node = [g for g in grounded if g["op"] == OP][0]
    return _EMITTERS[OP](dict(node), "2026", "kir:test")


# ── реестр ───────────────────────────────────────────────────────────────────

class RegistryShape(unittest.TestCase):

    def test_the_new_operands_exist(self):
        names = {p.name for p in spec.OPS[OP].params}
        self.assertIn("ref_dir", names)
        self.assertIn("top_level", names)
        self.assertIn("base_offset_mm", names)
        self.assertIn("top_offset_mm", names)

    def test_none_of_them_carries_a_default(self):
        """ЗАМЕР 29.07: `height_mm` нёс умолчание 3000, `_validate_op`
        подставлял его ДО эмиттера, и свидетель откатывал КАЖДУЮ верно
        построенную фасадную стену — «попросили ровно 3000» и «промолчали»
        стали неразличимы. Отсутствующий ключ обязан остаться отсутствующим:
        иначе сдвинется и байт-паритет 18 700 экземпляров демо."""
        by_name = {p.name: p for p in spec.OPS[OP].params}
        for name in ("ref_dir", "top_level", "base_offset_mm",
                     "top_offset_mm"):
            with self.subTest(param=name):
                self.assertIsNone(by_name[name].default)

    def test_the_offset_tolerances_are_named_in_the_registry(self):
        """Голый литерал в сравнении — тот род границы, который перепись
        `bounds_audit` находит только глазами. Числа те же, что у
        create_wall и create_column: одно обещание об одной величине."""
        tol = dict(spec.OPS[OP].tolerances)
        self.assertEqual(tol["base_offset_mm"], 1.0)
        self.assertEqual(tol["top_offset_mm"], 1.0)
        self.assertEqual(tol["base_offset_mm"],
                         dict(spec.OPS["create_column"].tolerances)
                         ["base_offset_mm"])

    def test_the_top_level_is_grounded_by_the_levels_pool(self):
        self.assertIn(("top_level", "levels", False), spec.OPS[OP].grounded)

    def test_a_direction_is_not_addressable_by_grid(self):
        """RELATE разрешает адрес в МОДЕЛЬНЫЕ МИЛЛИМЕТРЫ, а миллиметры в поле
        направления — не «примерно туда», а другая величина. Тот же разбор и
        та же запись, что у `create_face_wall.face_normal`."""
        from kukai.ir.relate import ADDRESS_EXCLUDED
        self.assertIn((OP, "ref_dir"), ADDRESS_EXCLUDED)


# ── опровергающие: до этой волны обе программы ОТКАЗЫВАЛИ ───────────────────

class TheRefutingPrograms(unittest.TestCase):
    """Эти две компилируются ТОЛЬКО после волны. На HEAD до неё обе давали
    KIR-P003 «неизвестное поле» — то есть инженер не мог попросить, а не
    получал плохой результат."""

    def test_a_work_plane_placement_compiles(self):
        out = compile_program(_prog(_work_plane()), revit_version="2024",
                              snapshot=SNAPSHOT, bulk=True)
        self.assertTrue(out.ok, _codes(out)[:3])
        self.assertIn("FamilyPlacementType.WorkPlaneBased", out.csharp)

    def test_a_two_levels_placement_compiles(self):
        out = compile_program(_prog(_two_levels(base_offset_mm=100,
                                                top_offset_mm=-250)),
                              revit_version="2024", snapshot=SNAPSHOT,
                              bulk=True)
        self.assertTrue(out.ok, _codes(out)[:3])
        self.assertIn("FAMILY_TOP_LEVEL_PARAM", out.csharp)


# ── байт-паритет: точечный путь не смеет сдвинуться ─────────────────────────

class TheFrozenPathDoesNotMove(unittest.TestCase):

    def test_a_program_without_the_new_operands_is_byte_identical(self):
        """Точечный путь заморожен корпусом паритета (18 700 экземпляров
        демо). Дописка обязана быть ПУСТОЙ, когда операнд не назван."""
        import io
        import pathlib
        from kukai.ir.tests.test_golden import GOLDEN_DIR, PROGRAMS
        for name in ("full_house_v1", "place_family_point_and_curve"):
            with self.subTest(golden=name):
                prog = {k: v for k, v in PROGRAMS[name].items()
                        if not k.startswith("__")}
                out = compile_program(prog, revit_version="2026",
                                      snapshot=SNAPSHOT)
                self.assertTrue(out.ok, _codes(out)[:3])
                path = pathlib.Path(GOLDEN_DIR) / ("%s.golden.cs" % name)
                self.assertEqual(
                    io.open(str(path), encoding="utf-8").read(), out.csharp,
                    "%s: точечный путь сдвинулся" % name)


# ── ось версий: её нет ──────────────────────────────────────────────────────

class VersionAxis(unittest.TestCase):

    def test_both_branches_build_on_all_six(self):
        for label, ops in (("work_plane", _work_plane()),
                           ("two_levels", _two_levels())):
            for ver in spec.REVIT_VERSIONS:
                with self.subTest(branch=label, version=ver):
                    out = compile_program(_prog(ops), revit_version=ver,
                                          snapshot=SNAPSHOT, bulk=True)
                    self.assertTrue(out.ok, _codes(out)[:3])

    def test_the_emission_does_not_branch_by_version(self):
        """Три перегрузки NewFamilyInstance живут на всех шести версиях с
        одинаковыми сигнатурами (замер 11.08), поэтому ветки по версии здесь
        быть не должно — она была бы кодом, недостижимым ни на одной цели."""
        for label, ops in (("work_plane", _work_plane()),
                           ("two_levels", _two_levels())):
            texts = {ver: compile_program(_prog(ops), revit_version=ver,
                                          snapshot=SNAPSHOT,
                                          bulk=True).csharp
                     for ver in spec.REVIT_VERSIONS}
            with self.subTest(branch=label):
                self.assertEqual(len(set(texts.values())), 1)


# ── отказы: каждый называет причину ─────────────────────────────────────────

class RefusalsNameTheCause(unittest.TestCase):

    def test_a_direction_with_a_curve_is_refused_not_swallowed(self):
        """Молча проглотить операнд хуже, чем отказать: у перегрузки по
        ссылке на носитель направления отсчёта нет вовсе, и принять `ref_dir`
        значило бы построить не то, о чём просили, и отчитаться успехом."""
        out = compile_program(_prog([
            _wall(),
            {"op": OP, "id": "P1", "p0_mm": [0, 0, 0], "p1_mm": [1000, 0, 0],
             "host": {"by": "ref", "value": "W1"}, "ref_dir": [1, 0, 0]},
        ]), revit_version="2024", snapshot=SNAPSHOT, bulk=True)
        self.assertFalse(out.ok)
        self.assertIn("KIR-P007", _codes(out))

    def test_a_work_plane_placement_without_a_host_is_refused(self):
        out = compile_program(_prog([
            {"op": OP, "id": "P1", "xyz": [1, 2, 0], "level": LVL,
             "ref_dir": [1, 0, 0]}]), revit_version="2024",
            snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertTrue(_codes(out))

    def test_the_placement_type_guard_names_the_actual_kind(self):
        """`CanFlip*=false` научил: род размещения — ФАКТ О СЕМЕЙСТВЕ, и
        Revit его не переставит. Значит типизированный ОТКАЗ (стоит свой оп
        под per_op), а не нарушение постусловия (стоило бы всю программу), и
        в тексте едет фактический род — автору есть что исправить."""
        _d, create, _c, _r = _checks_of(_work_plane())
        self.assertIn("FamilyPlacementType.WorkPlaneBased", create)
        self.assertIn("FamilyPlacementType.ToString()", create)

    def test_a_zero_length_direction_is_refused(self):
        _d, create, _c, _r = _checks_of(_work_plane())
        self.assertIn("IsZeroLength()", create)


# ── свидетели ───────────────────────────────────────────────────────────────

class WitnessesReadTheResult(unittest.TestCase):

    def test_each_branch_carries_its_own_keys(self):
        _d, _c, wp, _r = _checks_of(_work_plane())
        self.assertIn("reference_direction",
                      {k.obligation_key for k in wp})
        _d, _c, tl, _r = _checks_of(_two_levels(base_offset_mm=100,
                                                top_offset_mm=-250))
        keys = {k.obligation_key for k in tl}
        self.assertIn("top_level_binding", keys)
        self.assertIn("base_offset", keys)
        self.assertIn("top_offset", keys)

    def test_an_absent_operand_leaves_no_witness_behind(self):
        """Условное обязательство разряжается ОТСУТСТВИЕМ своего свидетеля:
        лишний витнес объявил бы доказанным то, чего никто не просил."""
        _d, _c, checks, _r = _checks_of([
            {"op": OP, "id": "P1", "xyz": [1, 2, 0], "level": LVL}])
        keys = {k.obligation_key for k in checks}
        for absent in ("reference_direction", "top_level_binding",
                       "base_offset", "top_offset"):
            self.assertNotIn(absent, keys)

    def test_the_direction_witness_reads_a_revit_computed_vector(self):
        """§18.3: проверка, подписанная «(geometry)», чей читатель состоит
        ТОЛЬКО из `get_Parameter(...)`, геометрию не разряжает. Здесь
        читается `HandOrientation` — вектор, который считает Revit."""
        _d, _c, checks, _r = _checks_of(_work_plane())
        wit = {k.obligation_key: k for k in checks}["reference_direction"]
        self.assertIn("(geometry)", wit.message)
        self.assertIn("HandOrientation", wit.reader_cs)
        self.assertNotIn("get_Parameter", wit.reader_cs)

    def test_the_offsets_sign_semantic_because_that_is_what_they_read(self):
        """Читатель — ровно `get_Parameter(...)`, то есть параметр, который
        мы же и записали. Подписать его геометрией значило бы просить
        исключение в `_ALLOWED_PARAMETER_GEOMETRY` под утверждение, которого
        никто не мерил. Семантика — то, что он ДЕЙСТВИТЕЛЬНО доказывает."""
        _d, _c, checks, _r = _checks_of(_two_levels(base_offset_mm=100))
        wit = {k.obligation_key: k for k in checks}["base_offset"]
        self.assertIn("(semantic)", wit.message)
        self.assertNotIn("(geometry)", wit.message)

    def test_every_setter_of_this_wave_is_read_back(self):
        """Сеттер без свидетеля — главный рецидивный дефект этого кода: он
        проходит все тесты и не доказывает ничего."""
        _d, create, checks, _r = _checks_of(
            _two_levels(base_offset_mm=100, top_offset_mm=-250))
        witness = "".join(c.reader_cs + c.verdict_cs for c in checks)
        for bip in ("FAMILY_TOP_LEVEL_PARAM",
                    "FAMILY_BASE_LEVEL_OFFSET_PARAM",
                    "FAMILY_TOP_LEVEL_OFFSET_PARAM"):
            with self.subTest(bip=bip):
                self.assertIn(bip, create)
                self.assertIn(bip, witness)

    def test_the_certificate_proves_both_branches_on_every_version(self):
        from kukai.ir import ground as ground_mod
        from kukai.ir.compiler import _parse_and_check
        from kukai.ir.translation_cert import certify_op
        for label, ops in (("work_plane", _work_plane()),
                           ("two_levels", _two_levels(base_offset_mm=100,
                                                      top_offset_mm=-250))):
            grounded = ground_mod.ground(_parse_and_check(_prog(ops)),
                                         SNAPSHOT)
            node = [g for g in grounded if g["op"] == OP][0]
            for ver in spec.REVIT_VERSIONS:
                with self.subTest(branch=label, version=ver):
                    cert = certify_op(dict(node), ver)
                    self.assertTrue(cert.proven, cert.gaps)
                    self.assertEqual(cert.vacuous, ())

    def test_cutting_any_new_witness_makes_the_certificate_fall(self):
        """ЗАКОН L6. И оракул имеет смысл ТОЛЬКО при зелёной базе: мутация,
        чей исходный сертификат уже красен, «проходит» вхолостую — на этой
        волне так и случилось при первом прогоне."""
        from kukai.ir import authoring, ground as ground_mod
        from kukai.ir.authoring import _EMITTERS
        from kukai.ir.compiler import _parse_and_check
        from kukai.ir.translation_cert import certify_op
        cases = {
            "reference_direction": _work_plane(),
            "top_level_binding": _two_levels(base_offset_mm=100),
            "base_offset": _two_levels(base_offset_mm=100),
        }
        original = authoring._emit_place
        try:
            for cut, ops in cases.items():
                grounded = ground_mod.ground(_parse_and_check(_prog(ops)),
                                             SNAPSHOT)
                node = [g for g in grounded if g["op"] == OP][0]
                with self.subTest(cut=cut):
                    self.assertTrue(certify_op(dict(node), "2026").proven,
                                    "база мутации обязана быть зелёной")

                    def mutated(op, ver, stamp, isolation="atomic", _c=cut):
                        d, c, checks, r = original(op, ver, stamp, isolation)
                        return d, c, [k for k in checks
                                      if k.obligation_key != _c], r
                    _EMITTERS[OP] = mutated
                    self.assertFalse(certify_op(dict(node), "2026").proven,
                                     "вырезан свидетель %s, а сертификат "
                                     "всё ещё доказан" % cut)
                    _EMITTERS[OP] = original
        finally:
            _EMITTERS[OP] = original


# ── честный остаток ─────────────────────────────────────────────────────────

class TheReverseHalfStaysClosed(unittest.TestCase):
    """Волна расширяет ПРЯМОЙ ход. Поднять такой экземпляр обратно нечем, и
    это записано в коде, а не оставлено следующему замеру как находка."""

    def test_l0_carries_one_level_and_no_work_plane_reference(self):
        from kukai.ir.decompile.schema import L0Element
        fields = set(L0Element.__dataclass_fields__)
        self.assertIn("level_id", fields)
        self.assertNotIn("top_level_id", fields)
        for name in fields:
            self.assertNotIn("work_plane", name)
            self.assertNotIn("sketch_plane", name)

    def test_the_view_owned_kinds_are_deliberately_not_taken(self):
        """`ViewBased` (999 эл./3 док.) и `CurveBasedDetail` (862/3) упираются
        в ту же стену, что размер, марка и текст: `L0Element` не несёт
        вида-владельца, и НИ ОДИН оп KIR не создаёт Вид — `_annot_view_res`
        отказывает `in_view: ref` именно на этой предпосылке. Взять их
        значило бы менять ЯЗЫК, а не реестр."""
        from kukai.ir.decompile.schema import L0Element
        fields = set(L0Element.__dataclass_fields__)
        self.assertNotIn("owner_view_id", fields)
        self.assertNotIn("view_id", fields)


if __name__ == "__main__":
    unittest.main()