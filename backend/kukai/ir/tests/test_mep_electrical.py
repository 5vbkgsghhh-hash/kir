"""wave/mep-electrical: короб ЭОМ, две заготовки, два гибких участка — и один
ИМЕНОВАННЫЙ ОТКАЗ (`create_wire`).

До этой волны вся электрика ниже лотка и вся «мягкая» инженерия были слепы:
`registry_base.KINDS` уже умел СЧИТАТЬ короба, гибкие воздуховоды и гибкие
трубы, а построить хоть один — нет. Пять операций закрывают ровно этот разрыв.

Чеклист ворот нового опа (KIR_CONNECT_SPEC.md, тот же, что у волны mep):
  (a) property — `PropertyFlexPath` ниже: любая корректная ломаная строится;
  (b) golden ×6 версий — `test_golden.mep_conduit_and_placeholders` /
      `mep_flex_runs`, плюс живой gate_runner (обе изоляции);
  (d) negative — `NegativeShared`: нет снапшота, неоднозначный пул, пустой
      пул, вырожденное звено, двумерная точка в трёхмерном пути, ломаная из
      одной точки, длиннее 64 точек;
  (e) invariant — одна транзакция, guard-на-null у каждого создания;
  (f) witness — `WitnessReadsTheResult`: КАЖДАЯ проверка читает построенный
      элемент (`LocationCurve` / `IsPlaceholder` / `Points` / `GetTypeId`), и
      ни одна не подтверждает, что сеттер отработал.

ОТДЕЛЬНО СТОИТ `WireIsDeliberatelyAbsent`. `Wire.Create` компилируется на всех
шести версиях вместе с двумя `null`-коннекторами — то есть отгрузить операцию
БЫЛО можно, и именно поэтому решение не отгружать нужно закрепить тестом:
иначе следующая сессия увидит зелёный компилятор, не увидит причины и добавит
вакуумную проверку. Причина целиком — в шапке `ops_mep.py`.
"""
import os
import random
import tempfile
import unittest

os.environ.setdefault(
    "KIR_REJECTIONS_PATH",
    os.path.join(tempfile.gettempdir(), "kir_test_mep_electrical_queue.jsonl"))

from kukai.ir import spec                                        # noqa: E402
from kukai.ir.compiler import compile_program                    # noqa: E402
from kukai.ir.schema_gen import program_schema                   # noqa: E402
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT              # noqa: E402

LVL = {"by": "element_id", "value": 42}

#: (имя опа, тело без id/level) — корпус, по которому идут общие законы.
LINEAR_OPS = (
    ("create_conduit", {"p0_mm": [0, 0, 3000], "p1_mm": [6000, 0, 3000]}),
    ("create_pipe_placeholder",
     {"p0_mm": [0, 1000, 2800], "p1_mm": [6000, 1000, 2800]}),
    ("create_duct_placeholder",
     {"p0_mm": [0, 2000, 3200], "p1_mm": [6000, 2000, 3200]}),
)

FLEX_OPS = (
    ("create_flex_duct", {"path": [[0, 3000, 3000], [1500, 3000, 2800],
                                   [3000, 3200, 2600]]}),
    ("create_flex_pipe", {"path": [[0, 4000, 3000], [1500, 4000, 2700]]}),
)

ALL_OPS = LINEAR_OPS + FLEX_OPS


def _prog(op_name: str, body: dict, oid: str = "X1", **kw) -> dict:
    op = {"op": op_name, "id": oid, "level": LVL}
    op.update(body)
    op.update(kw)
    return {"ir_version": "1.0", "intent": f"{op_name}-test", "ops": [op]}


def _cs(op_name: str, body: dict, snapshot=GROUND_SNAPSHOT, **kw) -> str:
    out = compile_program(_prog(op_name, body, **kw), snapshot=snapshot)
    assert out.ok, [d.as_dict() for d in out.diagnostics][:3]
    return out.csharp


class CableTraySectionOperands(unittest.TestCase):
    BODY = {"p0_mm": [0, 0, 3000], "p1_mm": [6000, 0, 3000]}

    def test_positive_section_has_no_invented_upper_bound(self):
        params = {p.name: p for p in spec.OPS["create_cable_tray"].params}
        for name in ("width_mm", "height_mm"):
            self.assertEqual(params[name].min_val, 1)
            self.assertIsNone(params[name].max_val)

        out = compile_program(
            _prog("create_cable_tray", self.BODY,
                  width_mm=5000, height_mm=4000),
            snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])

    def test_zero_section_is_still_a_typed_refusal(self):
        out = compile_program(
            _prog("create_cable_tray", self.BODY,
                  width_mm=0, height_mm=100),
            snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T002", [d.code for d in out.diagnostics])

    def test_emitter_sets_and_reads_each_declared_dimension(self):
        cs = _cs("create_cable_tray", self.BODY,
                 width_mm=300, height_mm=100)
        self.assertEqual(cs.count("RBS_CABLETRAY_WIDTH_PARAM"), 2)
        self.assertEqual(cs.count("RBS_CABLETRAY_HEIGHT_PARAM"), 2)
        self.assertIn(".Set(U(300.0))", cs)
        self.assertIn(".Set(U(100.0))", cs)
        self.assertIn("width mismatch", cs)
        self.assertIn("height mismatch", cs)

        absent = _cs("create_cable_tray", self.BODY)
        self.assertNotIn("RBS_CABLETRAY_WIDTH_PARAM", absent)
        self.assertNotIn("RBS_CABLETRAY_HEIGHT_PARAM", absent)

    def test_live_gate_corpus_reaches_sized_section_branch(self):
        from kukai.ir.gate_runner import (
            SIZED_CABLE_TRAY_GATE_NAME,
            register_sized_cable_tray_gate,
            sized_cable_tray_branch_reached,
        )

        programs = {}
        register_sized_cable_tray_gate(programs)
        self.assertEqual(set(programs), {SIZED_CABLE_TRAY_GATE_NAME})
        program = programs[SIZED_CABLE_TRAY_GATE_NAME]
        self.assertEqual(program["ops"][0]["id"], "CT2")

        for isolation in ("atomic", "per_op"):
            with self.subTest(isolation=isolation):
                out = compile_program(
                    program,
                    revit_version="2026",
                    snapshot=GROUND_SNAPSHOT,
                    isolation=isolation,
                )
                self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
                self.assertTrue(sized_cable_tray_branch_reached(out.csharp))


class TheApiCallIsTheMeasuredOne(unittest.TestCase):
    """Подпись каждой операции снята с эталонных сборок и скомпилирована на
    шести версиях ДО написания эмиттера. Здесь заморожена ФОРМА вызова —
    прежде всего порядок аргументов, который у короба ДРУГОЙ, чем у трубы."""

    def test_conduit_takes_the_level_last_like_a_cable_tray(self):
        cs = _cs(*LINEAR_OPS[0])
        self.assertIn("Autodesk.Revit.DB.Electrical.Conduit.Create(doc, "
                      "new ElementId(1400), P(0, 0, 3000), P(6000, 0, 3000), "
                      "__lv_X1.Id)", cs)

    def test_placeholders_take_the_level_before_the_points(self):
        cs_pipe = _cs(*LINEAR_OPS[1])
        self.assertIn("Autodesk.Revit.DB.Plumbing.Pipe.CreatePlaceholder(doc, "
                      "new ElementId(300), new ElementId(200), __lv_X1.Id, "
                      "P(0, 1000, 2800), P(6000, 1000, 2800))", cs_pipe)
        cs_duct = _cs(*LINEAR_OPS[2])
        self.assertIn("Autodesk.Revit.DB.Mechanical.Duct.CreatePlaceholder("
                      "doc, new ElementId(1001), new ElementId(1000), "
                      "__lv_X1.Id, P(0, 2000, 3200), P(6000, 2000, 3200))",
                      cs_duct)

    def test_flex_passes_an_ilist_of_points_not_two_endpoints(self):
        cs = _cs(*FLEX_OPS[0])
        self.assertIn("var __pts_X1 = new List<XYZ>();", cs)
        self.assertEqual(cs.count("__pts_X1.Add(P("), 3)
        self.assertIn("Autodesk.Revit.DB.Mechanical.FlexDuct.Create(doc, "
                      "new ElementId(1001), new ElementId(1401), __lv_X1.Id, "
                      "__pts_X1)", cs)
        self.assertIn("Autodesk.Revit.DB.Plumbing.FlexPipe.Create(doc, ",
                      _cs(*FLEX_OPS[1]))

    def test_the_tangent_overload_is_not_used(self):
        """Перегрузка с касательными существует на всех шести версиях и НЕ
        используется: нейтрального значения у касательной нет (нулевой вектор
        игнорируется), значит подставить её нечем, кроме выдумки."""
        for name, body in FLEX_OPS:
            with self.subTest(op=name):
                cs = _cs(name, body)
                self.assertNotIn("StartTangent", cs)
                self.assertNotIn("EndTangent", cs)

    def test_no_version_split_and_no_forbidden_element_id_idiom(self):
        """Ни одна из пяти не расходится по версиям — и ни одна не трогает
        `.IntegerValue`/`.Value` (у ElementId нет идиомы на все шесть)."""
        for name, body in ALL_OPS:
            with self.subTest(op=name):
                bodies = {}
                for ver in spec.REVIT_VERSIONS:
                    out = compile_program(_prog(name, body), snapshot=GROUND_SNAPSHOT,
                                          revit_version=ver)
                    self.assertTrue(out.ok, f"{ver}: {[d.as_dict() for d in out.diagnostics][:2]}")
                    self.assertNotIn(".IntegerValue", out.csharp)
                    bodies[ver] = out.csharp
                self.assertEqual(len(set(bodies.values())), 1,
                                 f"{name}: эмиссия разошлась по версиям")


class WitnessReadsTheResult(unittest.TestCase):
    """ГЛАВНЫЙ закон дома: свидетель читает РЕЗУЛЬТАТ, а не вызов. У каждой
    из пяти операций проверяется, что в post стоит чтение построенного
    элемента, и что ось подписи совпадает с тем, что прочитано."""

    def test_linear_ops_read_the_location_curve_revit_returns(self):
        for name, body in LINEAR_OPS:
            with self.subTest(op=name):
                cs = _cs(name, body)
                self.assertIn("var __lc = __el_X1.Location as LocationCurve;", cs)
                self.assertIn("__lc.Curve.GetEndPoint(0)", cs)
                self.assertIn("X1: endpoints mismatch (geometry)", cs)

    def test_every_op_reads_the_reference_level_back(self):
        for name, body in ALL_OPS:
            with self.subTest(op=name):
                cs = _cs(name, body)
                self.assertIn("BuiltInParameter.RBS_START_LEVEL_PARAM", cs)
                self.assertIn("X1: level binding mismatch (topology)", cs)

    def test_every_op_reads_its_type_back_off_the_built_element(self):
        expected = {
            "create_conduit": "conduit type",
            "create_pipe_placeholder": "pipe type",
            "create_duct_placeholder": "duct type",
            "create_flex_duct": "flex duct type",
            "create_flex_pipe": "flex pipe type",
        }
        for name, body in ALL_OPS:
            with self.subTest(op=name):
                cs = _cs(name, body)
                self.assertIn("var __ty = __el_X1.GetTypeId();", cs)
                self.assertIn(f"X1: {expected[name]} mismatch (semantic)", cs)

    def test_a_placeholder_proves_it_is_a_placeholder(self):
        """Единственный бит, отличающий заготовку от обычного участка. Без
        него операция была бы переименованной трубой, а слово «заготовка» —
        записью в журнале, а не фактом в модели."""
        for name, body in LINEAR_OPS[1:]:
            with self.subTest(op=name):
                cs = _cs(name, body)
                self.assertIn("if (!__el_X1.IsPlaceholder)", cs)
                self.assertIn("X1: созданный элемент не заготовка (semantic)", cs)

    def test_conduit_makes_no_placeholder_claim(self):
        self.assertNotIn("IsPlaceholder", _cs(*LINEAR_OPS[0]))

    def test_flex_witness_walks_the_whole_path_not_just_the_ends(self):
        """Проверка концов пропустила бы ВЫБРОШЕННУЮ СЕРЕДИНУ: трасса поехала
        бы при зелёном вердикте. Поэтому сверяются все точки и их число."""
        cs = _cs(*FLEX_OPS[0])
        self.assertIn("var __pp = __el_X1.Points;", cs)
        self.assertIn("__pp.Count != 3", cs)
        self.assertIn("double[] __ex = new double[] { 0.0, 3000.0, 3000.0, "
                      "1500.0, 3000.0, 2800.0, 3000.0, 3200.0, 2600.0 };", cs)
        self.assertIn("for (int __i = 0; __i < 3; __i++)", cs)
        self.assertIn("X1: flex path points mismatch (geometry)", cs)
        # Два ДИАГНОЗА врозь: «другое число точек» и «точка не там» — разные
        # причины, и одно слово на оба назвало бы следствие вместо причины.
        self.assertIn("flex path point count mismatch", cs)

    def test_flex_does_not_lean_on_location_curve(self):
        """У гибкого элемента `Location` — сплайн Эрмита, и его концы
        ПРОИЗВОДНЫ от точек. Первичное здесь — `Points`."""
        for name, body in FLEX_OPS:
            with self.subTest(op=name):
                cs = _cs(name, body)
                self.assertNotIn("var __lc = __el_X1.Location as LocationCurve;", cs)

    def test_flex_receipt_carries_the_whole_path(self):
        cs = _cs(*FLEX_OPS[0])
        self.assertIn('__rb["path_mm"]', cs)
        self.assertNotIn('__rb["start_mm"]', cs)

    def test_every_geometry_verdict_is_within_the_registry_tolerance(self):
        """Закон допусков: число сравнения приходит ИЗ РЕЕСТРА. Тронь его —
        байты обязаны поехать (сильная форма живёт в
        test_tolerance_provenance.py; здесь — что число вообще то самое)."""
        self.assertEqual(spec.OPS["create_conduit"].tolerances,
                         {"endpoint_mm": 5.0})
        self.assertEqual(spec.OPS["create_flex_duct"].tolerances,
                         {"point_mm": 5.0})
        for name, body in ALL_OPS:
            with self.subTest(op=name):
                self.assertIn("> 5.0", _cs(name, body))


class InvariantsShared(unittest.TestCase):
    def test_one_transaction_and_a_null_guard_per_creation(self):
        for name, body in ALL_OPS:
            with self.subTest(op=name):
                cs = _cs(name, body)
                self.assertEqual(cs.count("new Transaction"), 1)
                self.assertIn("вернул null", cs)
                self.assertGreaterEqual(cs.count("__t.RollBack()"), 1)

    def test_the_refusal_statement_has_one_owner_in_per_op_too(self):
        """`emit_utils.refuse_stmt` — единственный владелец текста отказа;
        в изоляции per_op он обязан стать `throw __OpRefuse(`, а не остаться
        откатом всей программы (иначе отказ одного опа сносит уже
        закоммиченных соседей)."""
        for name, body in ALL_OPS:
            with self.subTest(op=name):
                out = compile_program(_prog(name, body), snapshot=GROUND_SNAPSHOT,
                                      bulk=True, isolation="per_op")
                self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:2])
                self.assertIn("throw __OpRefuse(", out.csharp)

    def test_stamp_and_result_row(self):
        for name, body in ALL_OPS:
            with self.subTest(op=name):
                cs = _cs(name, body)
                self.assertIn("ALL_MODEL_INSTANCE_COMMENTS", cs)
                self.assertIn('__results["X1"]', cs)


class NegativeShared(unittest.TestCase):
    def test_no_snapshot_refused(self):
        for name, body in ALL_OPS:
            with self.subTest(op=name):
                out = compile_program(_prog(name, body), snapshot=None)
                self.assertFalse(out.ok)
                self.assertIn("KIR-G103", [d.code for d in out.diagnostics])

    def test_ambiguous_pool_refuses_with_candidates(self):
        """Два типа в пуле и опущенный селектор — НЕ «возьми первый».
        Кандидаты едут на самом отказе, чтобы следующий ход был по id."""
        cases = (("create_conduit", LINEAR_OPS[0][1], "conduit_types",
                  {"id": 1310, "name": "Короб гибкий"}),
                 ("create_flex_duct", FLEX_OPS[0][1], "flex_duct_types",
                  {"id": 1311, "name": "Гибкий воздуховод овальный"}))
        for name, body, pool, extra in cases:
            with self.subTest(op=name):
                snap = dict(GROUND_SNAPSHOT)
                snap[pool] = list(GROUND_SNAPSHOT[pool]) + [extra]
                out = compile_program(_prog(name, body), snapshot=snap)
                self.assertFalse(out.ok)
                diag = [d for d in out.diagnostics if d.code == "KIR-G102"][0]
                self.assertTrue(diag.as_dict().get("candidates"))

    def test_empty_pool_refuses_rather_than_inventing_a_default(self):
        snap = dict(GROUND_SNAPSHOT)
        snap["conduit_types"] = []
        out = compile_program(_prog(*LINEAR_OPS[0]), snapshot=snap)
        self.assertFalse(out.ok)
        self.assertIn("KIR-G104", [d.code for d in out.diagnostics])

    def test_zero_length_linear_run_refused(self):
        out = compile_program(
            _prog("create_conduit", {"p0_mm": [0, 0, 3000],
                                     "p1_mm": [0, 0, 3000]}),
            snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T002", [d.code for d in out.diagnostics])

    def test_flex_path_with_coincident_points_refused_before_emission(self):
        """Autodesk пишет про Flex*.Create дословно: «duplicate points don't
        take into account». Значит Revit построил бы трассу С ДРУГИМ ЧИСЛОМ
        ТОЧЕК, чем просили, — то есть другую трассу. Отказ здесь называет
        ПРИЧИНУ; свидетель пути назвал бы только следствие."""
        out = compile_program(
            _prog("create_flex_pipe",
                  {"path": [[0, 0, 3000], [0, 0, 3000], [1000, 0, 3000]]}),
            snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T002", [d.code for d in out.diagnostics])
        self.assertIn("выбрасывает",
                      " ".join(d.message_ru or "" for d in out.diagnostics))

    def test_flex_path_must_be_three_dimensional(self):
        """Двумерная точка НЕ дополняется нулём молча: гибкая подводка почти
        всегда идёт с этажа к потолку, и подставленный Z=0 положил бы трассу
        на абсолютный ноль — ровно тот класс, из-за которого create_beam
        потребовал pt_xyz."""
        out = compile_program(
            _prog("create_flex_duct", {"path": [[0, 0], [1000, 0]]}),
            snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T001", [d.code for d in out.diagnostics])

    def test_flex_path_bounds(self):
        for bad in ([[0, 0, 3000]],
                    [[float(k) * 100.0, 0.0, 3000.0] for k in range(65)]):
            with self.subTest(n=len(bad)):
                out = compile_program(
                    _prog("create_flex_pipe", {"path": bad}),
                    snapshot=GROUND_SNAPSHOT)
                self.assertFalse(out.ok)
                self.assertIn("KIR-T001", [d.code for d in out.diagnostics])

    def test_missing_required_path_is_typed(self):
        """Отсутствующий обязательный `path` — KIR-T001, ровно как
        отсутствующий обязательный `outline` у перекрытия: ветка рода
        параметра видит `None` и называет ТИП, а не отдельный код «нет
        поля». Замораживается фактическое поведение, а не желаемое."""
        out = compile_program(
            {"ir_version": "1.0", "intent": "без пути",
             "ops": [{"op": "create_flex_duct", "id": "X1", "level": LVL}]},
            snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T001", [d.code for d in out.diagnostics])


class PropertyFlexPath(unittest.TestCase):
    """Ворота (a): любая корректная по построению ломаная строится, и число
    точек в свидетеле всегда равно числу заказанных."""

    N = 40
    SEED = 20260809

    def test_random_wellformed_paths_compile(self):
        rng = random.Random(self.SEED)
        for case in range(self.N):
            n = rng.randint(2, 12)
            x = 0.0
            path = []
            for _ in range(n):
                x += rng.randint(500, 4000)
                path.append([x, float(rng.randint(-4000, 4000)),
                             float(rng.randint(2000, 4000))])
            op = rng.choice(["create_flex_duct", "create_flex_pipe"])
            with self.subTest(case=case, n=n, op=op):
                out = compile_program(_prog(op, {"path": path}),
                                      snapshot=GROUND_SNAPSHOT)
                self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:2])
                self.assertEqual(out.csharp.count("__pts_X1.Add(P("), n)
                self.assertIn(f"__pp.Count != {n}", out.csharp)
                self.assertIn(f"for (int __i = 0; __i < {n}; __i++)", out.csharp)


class GroundingPoolsAreCollectedTheSameWay(unittest.TestCase):
    """Новый пул обязан собираться ТЕМ ЖЕ путём, что и старые, и попадать в
    снимок — иначе заземление обещает каталог, которого никто не читает."""

    def test_the_three_new_pools_reach_the_snapshot_and_the_profile(self):
        from kukai.ir.open_model import (GROUND_SNAPSHOT_CS,
                                         required_grounding_pools)
        pools = required_grounding_pools()
        for pool in ("conduit_types", "flex_duct_types", "flex_pipe_types"):
            with self.subTest(pool=pool):
                self.assertIn(pool, pools)
                self.assertIn(f'__AddPool("{pool}"', GROUND_SNAPSHOT_CS)
                self.assertIn(f'"{pool}"', GROUND_SNAPSHOT_CS)

    def test_query_types_can_ask_for_them(self):
        choices = [p for p in spec.OPS["query_types"].params
                   if p.name == "pool"][0].choices
        for pool in ("conduit_types", "flex_duct_types", "flex_pipe_types"):
            with self.subTest(pool=pool):
                self.assertIn(pool, choices)
                out = compile_program(
                    {"ir_version": "1.0", "intent": "каталог",
                     "ops": [{"op": "query_types", "id": "q", "pool": pool}]})
                self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:2])

    def test_the_collector_tables_do_not_drift(self):
        from kukai.ir.compiler import _TYPE_POOL_COLLECTOR_CS
        from kukai.ir.open_model import GROUND_SNAPSHOT_CS
        for pool in ("conduit_types", "flex_duct_types", "flex_pipe_types"):
            with self.subTest(pool=pool):
                chain = _TYPE_POOL_COLLECTOR_CS[pool]
                self.assertIn(chain, GROUND_SNAPSHOT_CS)


class SchemaAndVocabulary(unittest.TestCase):
    def test_path3_is_declared_three_dimensional_in_the_schema(self):
        schema = program_schema()
        variants = schema["properties"]["ops"]["items"]["oneOf"]
        flex = next(v for v in variants
                    if v["properties"]["op"].get("const") == "create_flex_duct")
        path = flex["properties"]["path"]
        # Схема может быть поднята дедупликатором в $defs — тогда здесь $ref.
        if "$ref" in path:
            ref = path["$ref"].split("/")[-1]
            path = schema["$defs"][ref]
        self.assertEqual(path["items"]["minItems"], 3)
        self.assertEqual(path["items"]["maxItems"], 3)
        self.assertEqual(path["minItems"], 2)
        self.assertEqual(path["maxItems"], 64)

    def test_conduit_takes_no_diameter(self):
        """ИМЕНОВАННОЕ ОТСУТСТВИЕ, а не забывчивость: номинал короба — торговый
        размер из таблицы типа, а не длина из континуума. Свидетель на
        произвольное мм-значение падал бы на КОРРЕКТНО построенном коробе, а
        отказать на компиляции нечем — таблицы размеров в снимке нет."""
        params = {p.name for p in spec.OPS["create_conduit"].params}
        self.assertNotIn("diameter_mm", params)
        self.assertNotIn("RBS_CONDUIT_DIAMETER_PARAM", _cs(*LINEAR_OPS[0]))

    def test_flex_ops_are_not_stackable_but_the_linear_ones_are(self):
        """Макрос `stack` переносит Z у ОПОВ С ПАРОЙ КОНЦОВ. У гибкого участка
        концов нет — есть путь, и переноса для него никто не мерил."""
        from kukai.ir import macros
        for name in ("create_conduit", "create_pipe_placeholder",
                     "create_duct_placeholder"):
            self.assertIn(name, macros._STACKABLE)
            self.assertIn(name, macros._Z_SHIFTED)
        for name in ("create_flex_duct", "create_flex_pipe"):
            self.assertNotIn(name, macros._STACKABLE)
            self.assertNotIn(name, macros._Z_SHIFTED)


class WireIsDeliberatelyAbsent(unittest.TestCase):
    """`Electrical.Wire.Create` компилируется на шести версиях ВМЕСТЕ с двумя
    `null`-коннекторами — то есть операцию можно было отгрузить. Не отгружена,
    и решение закреплено здесь, чтобы следующая сессия увидела не только
    зелёный компилятор, но и причину.

    Коротко (полностью — в шапке ops_mep.py): `Connector` не `Element`, у него
    нет `ElementId`, и замороженный диалект ссылок KIR назвать его не может
    ВООБЩЕ; провод без цепи строится, рисуется на плане и пуст в
    `GetMEPSystems()` — снаружи неотличим от выполненного раздела ЭОМ;
    вершины проецируются на плоскость вида, поэтому трёхмерного пути у
    провода нет по построению.
    """

    def test_no_wire_op_exists(self):
        self.assertNotIn("create_wire", spec.OPS)

    def test_an_attempt_to_use_it_is_a_typed_refusal_not_a_crash(self):
        out = compile_program(
            {"ir_version": "1.0", "intent": "провод",
             "ops": [{"op": "create_wire", "id": "W1", "level": LVL,
                      "path": [[0, 0, 3000], [1000, 0, 3000]]}]},
            snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertTrue(out.diagnostics)

    def test_no_dead_wire_pool_was_left_behind(self):
        """Пул типов провода НЕ заведён: пул без опа — это каталог, который
        никто не спрашивает, и он же — первый шаг к тому, чтобы оп появился
        «раз уж пул есть»."""
        from kukai.ir.open_model import GROUND_SNAPSHOT_CS
        self.assertNotIn("wire_types", GROUND_SNAPSHOT_CS)
        self.assertNotIn("WireType", GROUND_SNAPSHOT_CS)


class ReverseSideIsDeclaredHonestly(unittest.TestCase):
    """Манифест обратного хода исчерпывающ по пишущим опам, значит про каждую
    из пяти он что-то УТВЕРЖДАЕТ. Здесь проверяется, что утверждает он ровно
    то, что есть в коде, — а не то, что было бы приятно."""

    def test_conduit_is_a_real_direct_inverse(self):
        from kukai.ir.decompile import lift
        from kukai.ir.reverse_contract import REVERSE_CONTRACTS, ReverseMode
        contract = REVERSE_CONTRACTS["create_conduit"]
        self.assertIs(contract.mode, ReverseMode.DIRECT)
        self.assertEqual(lift._CANDIDATES["OST_Conduit"].op, "create_conduit")
        self.assertIn("_lift_conduit", lift._LIFTERS)

    def test_placeholders_and_flex_are_named_capture_gaps(self):
        from kukai.ir.reverse_contract import REVERSE_CONTRACTS, ReverseMode
        for name in ("create_pipe_placeholder", "create_duct_placeholder",
                     "create_flex_duct", "create_flex_pipe"):
            with self.subTest(op=name):
                contract = REVERSE_CONTRACTS[name]
                self.assertIs(contract.mode, ReverseMode.CAPTURE_GAP)
                self.assertFalse(contract.direct_same_op_lift)
                self.assertTrue(contract.limitation)

    def test_a_conduit_row_lifts_to_the_op(self):
        from kukai.ir.decompile.lift import lift_document_detailed
        from kukai.ir.decompile.tests.test_lift import _document, make_element
        result = lift_document_detailed(
            _document([make_element("OST_Conduit", 9900, ordinal=0)]))
        self.assertEqual([n["op_name"] for n in result.nodes], ["create_conduit"])
        self.assertIn("conduit_type", result.nodes[0]["params"])
        self.assertNotIn("diameter_mm", result.nodes[0]["params"])


class CertificateCoversTheWave(unittest.TestCase):
    def test_every_new_op_is_certified_and_the_registry_audit_is_clean(self):
        from kukai.ir import ground as ground_mod
        from kukai.ir.compiler import _parse_and_check
        from kukai.ir.translation_cert import audit_registry_coverage, certify_op
        self.assertEqual(audit_registry_coverage(), ())
        for name, body in ALL_OPS:
            with self.subTest(op=name):
                grounded = ground_mod.ground(
                    _parse_and_check(_prog(name, body)), GROUND_SNAPSHOT)
                cert = certify_op(grounded[0], "2024")
                self.assertTrue(cert.proven, cert.gaps)


if __name__ == "__main__":
    unittest.main()
