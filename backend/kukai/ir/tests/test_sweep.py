"""wave/sweep (2026-08-09): create_wall_sweep / create_slab_edge.

ПОЧЕМУ ЭТА ВОЛНА. Семейство навесных профилей не было осмотрено НИ РАЗУ:
перепись реестра не находила ни одной операции, создающей `WallSweep`,
`SlabEdge`, `Fascia` или `Gutter`. Карнизы, пояски, русты-рустовки и капельники
по краю плиты — целый класс фасадной и кровельной отделки — не выражались
ничем.

Структура повторяет test_site.py (RegistryShape / Ground / Negative / Witness /
NamedWeakerGuarantee / CommitGateInvariants) — тот же граф инвариантов.

КАЖДЫЙ ЧЛЕН API ЗАМЕРЕН КОМПИЛЯЦИЕЙ НА :52412 (09.08.2026, шесть эталонных
сборок), а не взят из памяти и не из `data/revit_api_db.json` (эта база
доказанно неполна и `NewSlabEdge` не знает вовсе). Полная таблица — в шапке
ops_sweep.py. Здесь повторены только выводы, которые проверяются кодом ниже:

  * ОСИ ВЕРСИЙ У ЭТОЙ ВОЛНЫ НЕТ ВОВСЕ, и это замер, а не удача: все члены,
    которые называют оба эмиттера, компилируются 6/6, поэтому шесть версий
    получают ОДИН И ТОТ ЖЕ C#. Тест `VersionAxis` ниже проверяет именно это —
    отсутствие расхождения, а не его наличие;
  * `WallSweepInfo.IsVertical` — свойство ТОЛЬКО ДЛЯ ЧТЕНИЯ (CS0200 на всех
    шести). Единственный канал ориентации — аргумент конструктора, поэтому
    `orientation` обязателен и БЕЗ умолчания;
  * `WallSweep` — НЕ `HostedSweep` (CS0030), а `SlabEdge` — да. Свидетели у
    них поэтому разной силы, и `NamedWeakerGuarantee` ниже держит эту разницу
    объявленной, а не подразумеваемой;
  * `SlabEdge.SlabEdgeType`, `GetTypeId()` и базовые `Length` /
    `get_ReferenceCurve(Reference)` — все 6/6. ГЛАВНЫЙ ЗАМЕР ВОЛНЫ: прежний
    осмотр не нашёл у `SlabEdge` ни одного геттера сверх `AddSegment`, и по
    этому выводу операцию следовало бы отклонить. Он неверен — читаемых родов
    четыре, и последний из них годится в настоящие свидетели.
"""
import os
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(),
                                   "kir_test_sweep_queue.jsonl"))

from kukai.ir import spec                                        # noqa: E402
from kukai.ir.compiler import compile_program                    # noqa: E402
from kukai.ir.ops_sweep import (                                 # noqa: E402
    SWEEP_ORIENTATIONS, SLAB_EDGE_SIDES, WALL_SWEEP_NON_FIXED_ID,
)
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT as SNAPSHOT  # noqa: E402

HOST_ID = {"by": "element_id", "value": 7777}
OPS = ("create_wall_sweep", "create_slab_edge")


def _prog(ops, intent="sweep-test"):
    return {"ir_version": "1.0", "intent": intent, "ops": ops}


def _sweep(oid="S1", orientation="horizontal", **kw):
    op = {"op": "create_wall_sweep", "id": oid, "host": HOST_ID,
          "orientation": orientation}
    op.update(kw)
    return op


def _edge(oid="E1", side="top", **kw):
    op = {"op": "create_slab_edge", "id": oid, "host": HOST_ID, "side": side}
    op.update(kw)
    return op


def _emit(ops, ver="2026"):
    out = compile_program(_prog(ops), revit_version=ver, snapshot=SNAPSHOT,
                          bulk=True)
    return out


class RegistryShape(unittest.TestCase):
    def test_both_ops_are_registered_writing_creates(self):
        for name in OPS:
            with self.subTest(op=name):
                op = spec.OPS[name]
                self.assertTrue(op.writes_model)
                self.assertEqual(op.family, "authoring")
                self.assertEqual(op.effect.value, "create")

    def test_each_op_grounds_its_own_pool(self):
        """ДВА ПУЛА, А НЕ ОДИН, и это не педантизм: `NewSlabEdge` принимает
        ТОЛЬКО `SlabEdgeType`, а тип стенного профиля — вообще не класс, а
        элемент одной из двух категорий. Заземлить карниз пулом краевых
        профилей значило бы отдать эмиттеру id, который вызов заведомо
        отвергнет."""
        got = {name: dict((p, pool) for p, pool, _r in spec.OPS[name].grounded)
               for name in OPS}
        self.assertEqual(got["create_wall_sweep"]["type"], "wall_sweep_types")
        self.assertEqual(got["create_slab_edge"]["type"], "slab_edge_types")

    def test_neither_op_declares_a_tolerance(self):
        """НИ ОДНОГО ДОПУСКА — СЛЕДСТВИЕ, А НЕ ПРОБЕЛ.

        Все свидетели обеих операций ТОЧНЫЕ: принадлежность id множеству,
        равенство id, равенство булева значения, равенство двух счётчиков.
        Числа, которое имело бы смысл сравнивать с допуском, у них нет:
        у стенного профиля — потому что положение задаёт тип (см.
        NamedWeakerGuarantee), у краевого — потому что длину профиля Revit
        подрезает в ус на неизмеренную величину, и она едет в КВИТАНЦИЮ
        наблюдением, а не в вердикт.

        Замок нужен затем, что обратное изменение — добавить сюда число —
        выглядит как улучшение, а на деле это ровно тот «bound authored by
        reasoning», который этот дом называет своим классом дефекта.
        """
        for name in OPS:
            with self.subTest(op=name):
                self.assertEqual(spec.OPS[name].tolerances, {})
                self.assertNotIn("±", spec.OPS[name].post)

    def test_orientation_and_side_are_closed_and_have_no_default(self):
        o = {p.name: p for p in spec.OPS["create_wall_sweep"].params}
        self.assertEqual(o["orientation"].choices, SWEEP_ORIENTATIONS)
        self.assertTrue(o["orientation"].required)
        self.assertIsNone(o["orientation"].default)
        s = {p.name: p for p in spec.OPS["create_slab_edge"].params}
        self.assertEqual(s["side"].choices, SLAB_EDGE_SIDES)
        self.assertTrue(s["side"].required)
        self.assertIsNone(s["side"].default)

    def test_wall_sweep_claims_no_geometry_capability(self):
        """Клетка ("create", "geometry") у стенного профиля была бы
        ПЕРЕОБЕЩАНИЕМ ровно на величину названной более слабой гарантии; у
        краевого она заслужена, потому что периметр выбираем мы."""
        self.assertNotIn(("create", "geometry"),
                         spec.OPS["create_wall_sweep"].capability)
        self.assertIn(("create", "geometry"),
                      spec.OPS["create_slab_edge"].capability)


class NamedWeakerGuarantee(unittest.TestCase):
    """САМЫЙ ВАЖНЫЙ КЛАСС ЭТОГО ФАЙЛА.

    Ремарка Autodesk, дословно во всех шести RevitAPI.xml: «The wall sweep's
    profile and type are taken from the wall sweep type properties. The values
    set in the WallSweepInfo are ignored.» Из неё следует ТРИ обязательства
    этой волны, и каждое проверяется здесь, потому что каждое легко потерять
    правкой, выглядящей как улучшение.
    """

    def test_the_op_exposes_no_geometric_field_at_all(self):
        """Поля, которых у операции НЕ ДОЛЖНО БЫТЬ. Завести любое из них —
        значит принять от автора число, которое API документированно
        игнорирует, то есть построить тихо-неверный результат по построению.
        """
        names = {p.name for p in spec.OPS["create_wall_sweep"].params}
        for forbidden in ("distance_mm", "offset_mm", "wall_offset_mm",
                          "elevation_mm", "angle_deg", "profile"):
            with self.subTest(field=forbidden):
                self.assertNotIn(forbidden, names)

    def test_the_limit_is_stated_verbatim_in_post(self):
        """Ограничение НАЗВАНО, а не подразумевается: дословная цитата стоит в
        `post`, то есть в том же тексте, который читает и сертификат перевода,
        и человек."""
        post = spec.OPS["create_wall_sweep"].post
        self.assertIn("NAMED WEAKER GUARANTEE", post)
        self.assertIn("The values set in the WallSweepInfo are ignored", post)

    def test_the_clause_is_registered_as_non_witnessable(self):
        """И ГЛАВНОЕ — оно зарегистрировано ЯВНО, а не проскочило сверку на
        случайном общем слове. `audit_registry_coverage()` требует, чтобы
        каждая клаузула `post` имела обязательство; неутверждаемая обязана
        нести освобождение с причиной."""
        from kukai.ir.translation_cert import _NON_WITNESSABLE_CLAUSES
        markers = _NON_WITNESSABLE_CLAUSES["create_wall_sweep"]
        self.assertEqual(len(markers), 1)
        marker, why = markers[0]
        self.assertIn(marker, spec.OPS["create_wall_sweep"].post.lower())
        self.assertIn("witness", why)

    def test_the_registry_audit_is_clean(self):
        from kukai.ir.translation_cert import audit_registry_coverage
        self.assertEqual(audit_registry_coverage(), ())


class VersionAxis(unittest.TestCase):
    def test_six_versions_receive_the_same_csharp(self):
        """ОСИ ВЕРСИЙ НЕТ — И ЭТО УТВЕРЖДЕНИЕ, А НЕ УМОЛЧАНИЕ.

        Все члены API, которые называют оба эмиттера, замерены 6/6, поэтому
        расхождения быть не должно НИГДЕ, кроме литерала ElementId (у него
        своя, общая для всего дома, версионная идиома — и в этих программах он
        мал, значит и он не расходится). Тест ловит будущую правку, которая
        втихую заведёт версионную ветку там, где API её не требует: «отказ,
        которого API не требует, — такая же ложь, как молчание там, где он
        нужен».
        """
        for ops in ([_sweep()], [_edge()]):
            texts = {}
            for ver in spec.REVIT_VERSIONS:
                out = _emit(ops, ver)
                self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
                texts[ver] = out.csharp
            with self.subTest(op=ops[0]["op"]):
                self.assertEqual(len(set(texts.values())), 1,
                                 "версионная ветка появилась там, где API её "
                                 "не требует")


class Ground(unittest.TestCase):
    def test_omitted_type_resolves_to_the_sole_entry(self):
        out = _emit([_sweep()])
        self.assertTrue(out.ok)
        self.assertIn("new ElementId(1800)", out.csharp)
        out = _emit([_edge()])
        self.assertTrue(out.ok)
        self.assertIn("new ElementId(1801)", out.csharp)

    def test_ambiguous_pool_refuses_instead_of_picking(self):
        """Второй тип в пуле — типизированный вопрос, а не выбор за автора.
        Живой замер 02.08 назвал цену выбора: плечо C# взяло 1 тип двери из 62
        молча и построило."""
        snap = dict(SNAPSHOT)
        snap["wall_sweep_types"] = [{"id": 1800, "name": "Карниз 200x100"},
                                    {"id": 1802, "name": "Карниз 300x150"}]
        out = compile_program(_prog([_sweep()]), snapshot=snap, bulk=True)
        self.assertFalse(out.ok)
        self.assertIn("KIR-G102", [d.code for d in out.diagnostics])

    def test_named_type_is_resolved_by_name(self):
        out = _emit([_sweep(type={"by": "name", "value": "Карниз 200x100"})])
        self.assertTrue(out.ok)
        self.assertIn("new ElementId(1800)", out.csharp)


class Negative(unittest.TestCase):
    def test_orientation_is_mandatory(self):
        op = _sweep()
        del op["orientation"]
        out = _emit([op])
        self.assertFalse(out.ok)

    def test_side_is_mandatory(self):
        op = _edge()
        del op["side"]
        out = _emit([op])
        self.assertFalse(out.ok)

    def test_unknown_orientation_and_side_refuse(self):
        self.assertFalse(_emit([_sweep(orientation="diagonal")]).ok)
        self.assertFalse(_emit([_edge(side="north")]).ok)

    def test_host_is_mandatory(self):
        op = _sweep()
        del op["host"]
        self.assertFalse(_emit([op]).ok)
        op = _edge()
        del op["host"]
        self.assertFalse(_emit([op]).ok)

    def test_existing_host_by_element_id_is_legal(self):
        """ОСНОВНОЙ сценарий обеих операций: карниз вешают на стену, которая
        УЖЕ СТОИТ. Требовать `ref` значило бы запретить главный сценарий —
        ровно тот довод, по которому в тот же список внесён create_opening."""
        self.assertTrue(_emit([_sweep()]).ok)
        self.assertTrue(_emit([_edge()]).ok)


class Emission(unittest.TestCase):
    def test_wall_sweep_derives_the_kind_from_the_type_category(self):
        """РОД ПРОФИЛЯ НЕ СПРАШИВАЕТСЯ У АВТОРА. Спросить значило бы завести
        поле, которое может ПРОТИВОРЕЧИТЬ типу, — а по ремарке Autodesk
        победил бы тип, то есть ответ автору был бы молча другим."""
        cs = _emit([_sweep()]).csharp
        self.assertIn("BuiltInCategory.OST_Reveals", cs)
        self.assertIn("BuiltInCategory.OST_Cornices", cs)
        self.assertIn("WallSweepType.Reveal : WallSweepType.Sweep", cs)
        # Сравнение категорий — через ToString(): единственная идиома
        # ElementId, живая на всех шести (`.IntegerValue` мёртв на 2026,
        # `.Value` не существует до 2024).
        self.assertNotIn(".IntegerValue", cs)

    def test_wall_sweep_sets_the_non_fixed_id_the_api_demands(self):
        """«The WallSweepInfo id must be set to -1 for a non-fixed wall
        sweep» — условие ArgumentException, а не совет."""
        cs = _emit([_sweep()]).csharp
        self.assertIn(f"__wi_S1.Id = {WALL_SWEEP_NON_FIXED_ID};", cs)

    def test_wall_sweep_preflights_wall_allows_wall_sweep(self):
        """Предпроверка, которой ТРЕБУЕТ сама Create. Без неё отказ приехал бы
        исключением Revit и был бы записан конвейером как `internal` — «у нас
        что-то сломалось» вместо «эта стена не может нести профиль»."""
        cs = _emit([_sweep()]).csharp
        self.assertIn("WallSweep.WallAllowsWallSweep(__ho_S1)", cs)
        self.assertLess(cs.index("WallAllowsWallSweep"),
                        cs.index("WallSweep.Create("),
                        "предпроверка обязана стоять ДО вызова")

    def test_orientation_reaches_the_constructor_and_the_witness(self):
        for orientation, literal in (("horizontal", "false"),
                                     ("vertical", "true")):
            with self.subTest(orientation=orientation):
                cs = _emit([_sweep(orientation=orientation)]).csharp
                self.assertIn(f"WallSweepType.Sweep, {literal})", cs)
                self.assertIn(f"__ri_S1.IsVertical != {literal}", cs)

    def test_slab_edge_side_selects_the_right_host_object_call(self):
        self.assertIn("HostObjectUtils.GetTopFaces(__ho_E1)",
                      _emit([_edge(side="top")]).csharp)
        self.assertIn("HostObjectUtils.GetBottomFaces(__ho_E1)",
                      _emit([_edge(side="bottom")]).csharp)

    def test_slab_edge_never_touches_the_instance_geometry_trap(self):
        """ЛОВУШКА, УЖЕ ОПЛАЧЕННАЯ ОДИН РАЗ: `GetInstanceGeometry()` возвращает
        КОПИЮ, чьи ссылки Autodesk документирует как «not suitable for creating
        new Revit elements referencing the original element». Она компилируется
        6/6 и отказывает ЖИВЬЁМ, поэтому статический замок здесь дешевле
        второго живого прогона."""
        cs = _emit([_edge()]).csharp
        self.assertNotIn("GetInstanceGeometry", cs)

    def test_slab_edge_decides_by_cardinality_not_by_first_match(self):
        """ОБЕ ступени решаются МОЩНОСТЬЮ, и обе называют ЧИСЛО. Мощность не
        зависит от порядка перебора, поэтому недокументированный порядок
        граней и рёбер на результат не влияет вообще."""
        cs = _emit([_edge()]).csharp
        self.assertIn("if (__nf_E1 > 1)", cs)
        self.assertIn("__nf_E1.ToString()", cs)
        self.assertIn("if (__nl_E1 != 1)", cs)
        self.assertIn("__nl_E1.ToString()", cs)
        self.assertNotIn("FirstOrDefault", cs)

    def test_slab_edge_guards_the_documented_null_return(self):
        """`NewSlabEdge` документирован как ВОЗВРАЩАЮЩИЙ null при неудаче, а не
        бросающий. Без этой проверки был бы NullReferenceException, записанный
        как `internal`."""
        cs = _emit([_edge()]).csharp
        i = cs.index("doc.Create.NewSlabEdge(")
        self.assertIn("if (__el_E1 == null)", cs[i:i + 400])


class Witness(unittest.TestCase):
    def test_wall_sweep_reads_the_result_not_the_call(self):
        cs = _emit([_sweep()]).csharp
        post = cs[cs.index("// post S1"):]
        for reader in ("__el_S1.GetHostIds()", "__el_S1.GetTypeId()",
                       "__el_S1.GetWallSweepInfo()"):
            with self.subTest(reader=reader):
                self.assertIn(reader, post)

    def test_slab_edge_witness_reads_the_built_sweeps_own_curves(self):
        """САМЫЙ СИЛЬНЫЙ СВИДЕТЕЛЬ ВОЛНЫ: у ПОСТРОЕННОГО профиля
        спрашивается кривая, которую он проложил по каждой названной нами
        ссылке. Подделать это эмиттер не может ничем — он передал ссылку, а
        кривую вернул элемент."""
        cs = _emit([_edge()]).csharp
        post = cs[cs.index("// post E1"):]
        self.assertIn("__el_E1.get_ReferenceCurve(__wr_E1)", post)
        self.assertIn("__bound_E1 != __named_E1", post)

    def test_every_verdict_signs_the_axis_it_reads(self):
        """Свидетель подписывает ту ось, которую действительно читал. Здесь
        это проверяется буквально: у стенного профиля НЕТ ни одного вердикта
        `(geometry)` — читать геометрию ему нечем, — а у краевого он есть."""
        sweep_post = _emit([_sweep()]).csharp
        sweep_post = sweep_post[sweep_post.index("// post S1"):]
        self.assertNotIn("(geometry)", sweep_post)
        self.assertIn("(topology)", sweep_post)
        self.assertIn("(semantic)", sweep_post)
        edge_post = _emit([_edge()]).csharp
        edge_post = edge_post[edge_post.index("// post E1"):]
        self.assertIn("(geometry)", edge_post)

    def test_a_failed_read_is_a_violation_not_silence(self):
        """«Не смогли прочитать» не имеет права выглядеть как «сошлось».
        Ориентация — единственное, что автор сказал о форме стенного профиля,
        поэтому нечитаемый `GetWallSweepInfo()` обязан быть нарушением."""
        cs = _emit([_sweep()]).csharp
        self.assertIn("подтвердить ориентацию нечем", cs)

    def test_observations_ride_the_receipt_not_the_verdict(self):
        """Длина построенного профиля и периметр, который мы передали, — ОБА в
        квитанции и НИ ОДИН в вердикте: величину подрезки в ус никто не мерил,
        и сверять их назначенным допуском значило бы обвинять правильно
        построенный капельник."""
        cs = _emit([_edge()]).csharp
        post_start = cs.index("// post E1")
        rb_start = cs.index("// witness E1")
        self.assertIn('__rb["perimeter_mm"]', cs[rb_start:])
        self.assertIn('__rb["sweep_length_mm"]', cs[rb_start:])
        self.assertNotIn("sweep_length_mm", cs[post_start:rb_start])


class CommitGateInvariants(unittest.TestCase):
    def test_per_op_isolation_uses_the_op_local_refusal(self):
        """Отказ внутри обёрнутого create обязан быть ОП-ЛОКАЛЬНЫМ: иначе
        отказ одного опа откатил бы уже закоммиченных соседей."""
        from kukai.ir.emit_utils import program_refusal_tokens
        for ops in ([_sweep()], [_edge()]):
            out = compile_program(_prog(ops), snapshot=SNAPSHOT, bulk=True,
                                  isolation="per_op")
            self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
            create = out.csharp
            with self.subTest(op=ops[0]["op"]):
                self.assertIn("__OpRefuse(", create)
                self.assertNotIn("__t.RollBack(); return __Refuse(",
                                 create[create.index("// create_"):
                                        create.index("// post")])

    def test_both_ops_stamp_the_element_they_created(self):
        for ops, var in (([_sweep()], "__el_S1"), ([_edge()], "__el_E1")):
            with self.subTest(op=ops[0]["op"]):
                cs = _emit(ops).csharp
                self.assertIn(
                    f"{var}.get_Parameter(BuiltInParameter."
                    f"ALL_MODEL_INSTANCE_COMMENTS)", cs)

    def test_variables_read_after_the_post_block_are_declared_outside_it(self):
        """РЕГРЕССИЯ, ПОЙМАННАЯ ВОРОТАМИ 09.08.

        `__hs_`/`__named_`/`__bound_` объявлялись в ЧИТАТЕЛЕ свидетеля, а
        читаются КВИТАНЦИЕЙ — то есть в следующей области видимости. Блок
        постусловий несёт свои скобки, поэтому имя умирало на закрывающей, и
        все шесть версий в обеих изоляциях отвечали CS0103 (48 живых ячеек
        Roslyn, 48 отказов). Тест держит объявления снаружи блока.
        """
        for ops, names in (([_sweep()], ("__hs_S1",)),
                           ([_edge()], ("__named_E1", "__bound_E1"))):
            cs = _emit(ops).csharp
            head = cs[:cs.index("// create_")]
            for name in names:
                with self.subTest(var=name):
                    self.assertIn(f"{name} = ", head,
                                  "переменная, которую читает квитанция, "
                                  "обязана быть объявлена в decl")


if __name__ == "__main__":
    unittest.main()
