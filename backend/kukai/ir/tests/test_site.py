"""wave/site (2026-08-09): create_topography / create_building_pad /
create_site_subregion.

ПОЧЕМУ ЭТА ВОЛНА. Семейство площадки было пустым ЦЕЛИКОМ — ноль операций из
пяти точек входа API. Здание стояло в пустоте: «посади дом на рельеф», самая
обычная фраза заказчика, не выражалась ничем, а «площадка» и «подобласть» не
имели даже имени в языке.

Структура повторяет test_arch.py 1:1 (RegistryShape / VersionAxis / Ground /
Negative / Witness / CommitGateInvariants) — тот же граф инвариантов, что
доказан для create_ceiling/create_railing.

ОСЬ ВЕРСИЙ И КАЖДЫЙ ЧЛЕН API ЗАМЕРЕНЫ КОМПИЛЯЦИЕЙ НА :52412 (09.08.2026, шесть
эталонных сборок), а не взяты из памяти и не из `data/revit_api_db.json` —
таблица замера в шапке ops_site.py. Здесь повторены только выводы, которые
проверяются кодом ниже:

  * `TopographySurface.Create` и `GetPoints` — 6/6, и это САМЫЙ СИЛЬНЫЙ
    свидетель волны: элемент отдаёт обратно точки, которые ему дали;
  * класса `Toposolid` нет до 2024 (CS0246 на 2021/2022/2023), поэтому
    variety="toposolid" ниже — типизированный отказ KIR-E003, НАЗЫВАЮЩИЙ
    следующий ход, а не тихая замена на поверхность (это элемент ДРУГОЙ
    категории);
  * `Toposolid.GetPoints()` не существует НИ НА ОДНОЙ версии (CS1061 там, где
    есть сам тип), поэтому у толщи поточечное чтение идёт через
    `GetSlabShapeEditor()`, а уверенный предикат — габарит;
  * `SiteSubRegion` — НЕ `Element` (CS0029/CS1061 на всех шести): у него нет
    ни `.Id`, ни `get_Parameter`. Элемент подобласти — её `.TopographySurface`,
    и штампуется, читается в квитанцию и свидетельствуется именно он.
"""
import os
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(),
                                   "kir_test_site_queue.jsonl"))

from kukai.ir import spec                                        # noqa: E402
from kukai.ir.compiler import compile_program                    # noqa: E402
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT as SNAPSHOT  # noqa: E402

LVL = {"by": "element_id", "value": 42}

#: Пять съёмочных точек: четыре угла и одна в середине. Ни одна пара не
#: совпадает в плане и не лежит на одной прямой — то есть облако законно по
#: всем трём законам geom.validate_points_xyz.
PTS = [[0, 0, 0], [24000, 0, 800], [24000, 18000, 1500],
       [0, 18000, 400], [12000, 9000, 1100]]

RECT_REGION = {"outer": {"shape": "rect", "origin": [2000, 2000],
                         "size_mm": [12000, 9000]}}


def _prog(ops, intent="site-test"):
    return {"ir_version": "1.0", "intent": intent, "ops": ops}


def _surface(oid="T1", **kw):
    op = {"op": "create_topography", "id": oid, "variety": "surface",
          "points_mm": PTS}
    op.update(kw)
    return op


def _toposolid(oid="T1", **kw):
    op = {"op": "create_topography", "id": oid, "variety": "toposolid",
          "points_mm": PTS, "level": LVL}
    op.update(kw)
    return op


def _pad(oid="P1", **kw):
    op = {"op": "create_building_pad", "id": oid, "contour": RECT_REGION,
          "level": LVL}
    op.update(kw)
    return op


def _subregion(oid="R1", **kw):
    op = {"op": "create_site_subregion", "id": oid, "contour": RECT_REGION}
    op.update(kw)
    return op


def _codes(out):
    return [d.code for d in out.diagnostics]


def _cs(op, ver="2026"):
    out = compile_program(_prog([op]), revit_version=ver, snapshot=SNAPSHOT)
    assert out.ok, _codes(out)
    return out.csharp


# ── реестр ───────────────────────────────────────────────────────────────────

class RegistryShape(unittest.TestCase):

    OPS = ("create_topography", "create_building_pad",
           "create_site_subregion")

    def test_all_three_ops_are_registered_as_writers(self):
        for name in self.OPS:
            with self.subTest(op=name):
                self.assertIn(name, spec.OPS)
                self.assertTrue(spec.OPS[name].writes_model)
                self.assertEqual(spec.OPS[name].family, "authoring")

    def test_the_type_pools_are_their_own(self):
        """Толща НЕ грунтуется по floor_types, площадка — по своему пулу.

        Чужой пул дал бы ПРАВДОПОДОБНЫЙ, но неверный тип, а подмена типа
        снаружи неотличима от успеха — ровно то, что §18.1 запрещает."""
        topo = {p: pool for p, pool, _ in spec.OPS["create_topography"].grounded}
        pad = {p: pool for p, pool, _ in
               spec.OPS["create_building_pad"].grounded}
        self.assertEqual(topo["type"], "toposolid_types")
        self.assertEqual(pad["type"], "building_pad_types")

    def test_the_subregion_grounds_nothing(self):
        """У подобласти нет ни уровня, ни типа — их нет и в подписи API.

        Пула топоповерхностей в снапшоте не существует, поэтому `host`
        адресуется id или ссылкой; заводить пул ради `by:name` значило бы
        обещать разрешение по имени там, где имя поверхности её адресом не
        является (тот же шов, что у create_railing.host)."""
        self.assertEqual(spec.OPS["create_site_subregion"].grounded, ())

    def test_the_terrain_point_is_three_dimensional(self):
        """Плоский род обнулил бы рельеф в плоскость МОЛЧА: у поверхности
        уровня нет вовсе, и отметка живёт в Z каждой точки."""
        kinds = {p.name: p.kind for p in spec.OPS["create_topography"].params}
        self.assertEqual(kinds["points_mm"], "pts_xyz")

    def test_variety_is_required_and_has_no_default(self):
        """Подставить разновидность за автора значит выбрать за него элемент
        ДРУГОЙ категории."""
        variety = next(p for p in spec.OPS["create_topography"].params
                       if p.name == "variety")
        self.assertTrue(variety.required)
        self.assertIsNone(variety.default)
        self.assertEqual(set(variety.choices), {"surface", "toposolid"})


# ── ось версий ───────────────────────────────────────────────────────────────

class VersionAxis(unittest.TestCase):

    def test_the_surface_builds_on_every_shipped_version(self):
        for ver in spec.REVIT_VERSIONS:
            with self.subTest(version=ver):
                out = compile_program(_prog([_surface()]), revit_version=ver,
                                      snapshot=SNAPSHOT)
                self.assertTrue(out.ok, _codes(out))
                self.assertIn("TopographySurface.Create(doc,", out.csharp)

    def test_the_toposolid_refuses_below_2024_and_names_the_next_move(self):
        """Отказ, а не подмена. Свернуть на поверхность молча нельзя: у неё
        ДРУГАЯ категория (OST_Topography против OST_Toposolid), другая
        привязка и другой свидетель, то есть это был бы другой элемент,
        выданный за запрошенный."""
        for ver in ("2021", "2022", "2023"):
            with self.subTest(version=ver):
                out = compile_program(_prog([_toposolid()]), revit_version=ver,
                                      snapshot=SNAPSHOT)
                self.assertFalse(out.ok)
                self.assertIn("KIR-E003", _codes(out))
                text = " ".join(d.message_ru or "" for d in out.diagnostics)
                self.assertIn("surface", text,
                              "отказ обязан НАЗВАТЬ следующий ход")

    def test_the_toposolid_builds_on_2024_and_later(self):
        for ver in ("2024", "2025", "2026"):
            with self.subTest(version=ver):
                out = compile_program(_prog([_toposolid()]), revit_version=ver,
                                      snapshot=SNAPSHOT)
                self.assertTrue(out.ok, _codes(out))
                self.assertIn("Toposolid.Create(doc,", out.csharp)

    def test_pad_and_subregion_build_on_every_shipped_version(self):
        for ver in spec.REVIT_VERSIONS:
            for op in (_pad(), _subregion()):
                with self.subTest(version=ver, op=op["op"]):
                    out = compile_program(_prog([op]), revit_version=ver,
                                          snapshot=SNAPSHOT)
                    self.assertTrue(out.ok, _codes(out))

    def test_the_host_probe_names_toposolid_only_where_it_exists(self):
        """ВЕТКА ЭМИССИИ, А НЕ УКРАШЕНИЕ: на 2021-2023 упоминание `Toposolid`
        в счётчике кандидатов было бы CS0246, то есть площадка перестала бы
        компилироваться на половине флота."""
        for ver in ("2021", "2022", "2023"):
            with self.subTest(version=ver):
                self.assertNotIn("Toposolid", _cs(_pad(), ver))
        for ver in ("2024", "2025", "2026"):
            with self.subTest(version=ver):
                self.assertIn("typeof(Toposolid)", _cs(_pad(), ver))


# ── grounding ────────────────────────────────────────────────────────────────

class Ground(unittest.TestCase):

    def test_the_surface_gets_no_level_and_no_type(self):
        """У TopographySurface.Create уровня НЕТ в подписи вовсе. Общее
        правило «единственный в пуле» подставило бы поверхности привязку к
        этажу, которой у неё быть не может, и свидетель начал бы проверять
        выдуманное."""
        cs = _cs(_surface())
        self.assertNotIn("Level __lv_", cs)
        self.assertNotIn("__ty_", cs)

    def test_the_toposolid_resolves_the_sole_pool_type(self):
        # 1700, а не 1300: блок 1300-1301 занял ленточный фундамент, и
        # id площадки уехали на следующую свободную сотню при слиянии 09.08.
        cs = _cs(_toposolid())
        self.assertIn("ToposolidType __ty_T1 = doc.GetElement("
                      "new ElementId(1700))", cs)

    def test_the_pad_never_substitutes_a_document_default_type(self):
        """У площадки тип по умолчанию в API ЕСТЬ
        (ElementTypeGroup.BuildingPadType, 6/6 — замерено), и он сознательно
        НЕ используется: «площадка по умолчанию» на чужом здании почти
        никогда не та, а подмена типа снаружи неотличима от успеха. Ветка
        doc_default в первой редакции эмиттера была МЁРТВОЙ (ground выдаёт
        `in_emit=default` четырём опам, площадки среди них нет) — этот тест
        держит решение явным, чтобы мёртвая ветка не вернулась."""
        cs = _cs(_pad())
        self.assertNotIn("GetDefaultElementTypeId", cs)
        self.assertIn("BuildingPadType __ty_P1 = doc.GetElement("
                      "new ElementId(1701))", cs)

    def test_an_ambiguous_pad_type_is_a_typed_question_not_a_guess(self):
        snap = dict(SNAPSHOT)
        snap["building_pad_types"] = [{"id": 1701, "name": "Площадка 200"},
                                      {"id": 1702, "name": "Площадка 400"}]
        out = compile_program(_prog([_pad()]), snapshot=snap)
        self.assertFalse(out.ok)
        self.assertIn("KIR-G102", _codes(out))


# ── типизированные отказы ────────────────────────────────────────────────────

class Negative(unittest.TestCase):

    def test_a_toposolid_without_a_level_is_a_typed_refusal(self):
        """Уровень у толщи требует сама подпись Toposolid.Create. Пул уровней
        фикстуры несёт ДВА уровня, поэтому общее правило «единственный в
        пуле» здесь не сработает и вопрос дойдёт до автора."""
        op = _toposolid()
        op.pop("level")
        out = compile_program(_prog([op]), snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-G102", _codes(out))

    def test_two_points_over_one_plan_spot_are_refused(self):
        """У рельефа в одной точке плана ровно ОДНА земля. Принять обе значит
        позволить Revit молча выбрать одну — то есть построить не тот рельеф,
        и снаружи это неотличимо от успеха."""
        pts = PTS + [[24000, 0, 5000]]      # тот же план, что у точки 1
        out = compile_program(_prog([_surface(points_mm=pts)]),
                              snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T004", _codes(out))

    def test_a_collinear_point_cloud_is_refused(self):
        """Диагональная цепочка точек: у габаритной рамки оба размера
        ненулевые, а поверхности всё равно не будет. Прибор, который видит
        только осевое вырождение, опаснее отсутствующего."""
        pts = [[0, 0, 0], [1000, 1000, 100], [2000, 2000, 200],
               [3000, 3000, 300]]
        out = compile_program(_prog([_surface(points_mm=pts)]),
                              snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T004", _codes(out))

    def test_a_flat_two_dimensional_point_is_refused(self):
        """Именно ради этого заведён отдельный род: [x,y] обнулил бы отметку
        земли, а рельеф на нулевой отметке — это ДРУГОЙ рельеф."""
        out = compile_program(
            _prog([_surface(points_mm=[[0, 0], [1000, 0], [0, 1000]])]),
            snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T002", _codes(out))

    def test_fewer_than_three_points_is_refused(self):
        out = compile_program(
            _prog([_surface(points_mm=[[0, 0, 0], [1000, 0, 0]])]),
            snapshot=SNAPSHOT)
        self.assertFalse(out.ok)

    def test_an_unknown_variety_never_reaches_the_emitter(self):
        out = compile_program(_prog([_surface(variety="mountain")]),
                              snapshot=SNAPSHOT)
        self.assertFalse(out.ok)


# ── свидетели: читаем РЕЗУЛЬТАТ, а не вызов ──────────────────────────────────

class Witness(unittest.TestCase):

    def test_the_surface_rereads_its_own_points(self):
        """САМЫЙ СИЛЬНЫЙ свидетель волны: сравнивается не «мы вызвали
        Create», а множество точек, которое отдал ПОСТРОЕННЫЙ элемент."""
        cs = _cs(_surface())
        self.assertIn("__el_T1.GetPoints()", cs)
        self.assertIn("DistanceTo", cs)
        self.assertIn("описанных точек рельефа нет в GetPoints() (geometry)", cs)

    def test_the_point_witness_can_actually_fail(self):
        """Проверка, которая не может провалиться, хуже отсутствующей.
        Здесь провал выражен явно: счётчик ненайденных точек и вердикт по
        нему."""
        cs = _cs(_surface())
        self.assertIn("if (__miss_T1 > 0)", cs)
        self.assertIn("__post.Add", cs.split("if (__miss_T1 > 0)")[1][:400])

    def test_the_toposolid_reads_vertices_and_reports_unreadability(self):
        """У толщи GetPoints() НЕ СУЩЕСТВУЕТ, поэтому точки читаются из
        редактора формы. Прочитается ли он у толщи, построенной ПО ТОЧКАМ, —
        факт ЖИВОГО Revit, офлайн непроверяемый; поэтому недоступный редактор
        здесь не вердикт, а число в квитанции: «не прочитали» не должно
        выглядеть как «сошлось»."""
        cs = _cs(_toposolid())
        self.assertIn("GetSlabShapeEditor()", cs)
        self.assertIn("SlabShapeVertices", cs)
        self.assertIn('__rb["slab_shape_vertices"] = __vcnt_T1;', cs)
        self.assertIn("if (__vcnt_T1 > 0)", cs)

    def test_the_pad_rereads_its_boundary_not_its_bounding_box(self):
        """Габарит ТЕЛА площадки включает её толщину и вырез в рельефе;
        читается сама граница — то есть ровно переданный эскиз."""
        cs = _cs(_pad())
        self.assertIn("__el_P1.GetBoundary()", cs)
        self.assertIn("Tessellate()", cs)
        self.assertIn("boundary bbox mismatch (geometry)", cs)

    def test_the_pad_reads_the_host_revit_chose_itself(self):
        """Настоящее чтение результата, а не эхо аргумента: хозяина мы не
        передавали — у BuildingPad.Create его нет в подписи вовсе."""
        cs = _cs(_pad())
        self.assertIn("AssociatedTopographySurfaceId", cs)
        self.assertIn("площадка не привязана к топоповерхности (topology)", cs)

    def test_a_pad_with_no_host_refuses_before_creating_anything(self):
        """Типизированный отказ С НАЗВАННЫМ СЛЕДУЮЩИМ ХОДОМ вместо
        InvalidOperationException, который конвейер записал бы как «у нас
        что-то сломалось». Проверка НЕОБХОДИМАЯ, а не достаточная, и стоит
        ДО вызова."""
        cs = _cs(_pad())
        probe = cs.index("__hosts_P1 =")
        self.assertLess(probe, cs.index("BuildingPad.Create"))
        self.assertIn("create_topography", cs)

    def test_the_subregion_witnesses_a_boolean_it_never_wrote(self):
        cs = _cs(_subregion())
        self.assertIn("__el_R1.IsSiteSubRegion", cs)
        self.assertIn("не помечена как подобласть (semantic)", cs)

    def test_the_subregion_owns_the_surface_not_the_wrapper(self):
        """SiteSubRegion — НЕ Element (CS0029/CS1061 на всех шести): у него
        нет ни `.Id`, ни `get_Parameter`. Штамп и квитанция обязаны стоять на
        её TopographySurface, иначе владение теряется — A5 сверяет его именно
        по квитанции."""
        cs = _cs(_subregion())
        self.assertIn("__el_R1 = __sr_R1.TopographySurface;", cs)
        self.assertNotIn("__sr_R1.Id", cs)
        self.assertIn('__rb["id"] = __el_R1.Id.ToString();', cs)

    def test_the_subregion_checks_the_named_host_only_when_named(self):
        with_host = _cs(_subregion(host={"by": "element_id", "value": 7777}))
        self.assertIn("принадлежит не запрошенной топоповерхности", with_host)
        without = _cs(_subregion())
        self.assertIn("не принадлежит ни одной топоповерхности", without)
        self.assertNotIn("принадлежит не запрошенной", without)

    def test_every_verdict_signs_the_axis_it_read(self):
        """Свидетель подписывает ту ось, которую действительно читал: точки и
        граница — (geometry), привязки — (topology), флаг подобласти —
        (semantic)."""
        for op, expected in ((_surface(), "(geometry)"),
                             (_pad(), "(topology)"),
                             (_subregion(), "(semantic)")):
            with self.subTest(op=op["op"], axis=expected):
                self.assertIn(expected, _cs(op))


# ── инварианты дома ──────────────────────────────────────────────────────────

class CommitGateInvariants(unittest.TestCase):

    def test_no_emitter_hand_types_the_refusal_statement(self):
        """`emit_utils.refuse_stmt` — ЕДИНСТВЕННЫЙ владелец текста отказа.
        В per_op отказ, набранный руками, откатил бы уже закоммиченных
        соседей."""
        import pathlib
        src = (pathlib.Path(__file__).resolve().parents[1]
               / "site_emit.py").read_text(encoding="utf-8")
        self.assertNotIn("__t.RollBack(); return __Refuse(", src)

    def test_per_op_isolation_never_carries_whole_program_refusals(self):
        for op in (_surface(), _toposolid(), _pad(), _subregion()):
            with self.subTest(op=op["op"], variety=op.get("variety")):
                out = compile_program(_prog([op]), revit_version="2026",
                                      snapshot=SNAPSHOT, isolation="per_op")
                self.assertTrue(out.ok, _codes(out))
                self.assertIn("throw __OpRefuse(", out.csharp)

    def test_the_registry_tolerances_are_the_ones_emitted(self):
        """Число живёт в реестре, а не в эмитируемой C# (закон провенанса)."""
        self.assertEqual(spec.OPS["create_topography"].tolerances,
                         {"point_mm": 1.0, "bbox_mm": 50.0})
        cs = _cs(_surface())
        self.assertIn("<= U(1.0)", cs)
        self.assertIn("> 50.0", cs)

    def test_the_reverse_direction_is_declared_a_capture_gap(self):
        """Обещание подъёма, которого нет, протухает молча — манифест
        существует ровно затем, чтобы этого не случилось."""
        from kukai.ir.reverse_contract import REVERSE_CONTRACTS
        for name in ("create_topography", "create_building_pad",
                     "create_site_subregion"):
            with self.subTest(op=name):
                self.assertFalse(
                    REVERSE_CONTRACTS[name].direct_same_op_lift)

    def test_the_translation_certificate_proves_every_branch(self):
        """Сертификат снимается с КАЖДОЙ ветви, а не с одной: ветка, которой
        корпус не строит, заверена только в отрицании."""
        from kukai.ir import ground as ground_mod
        from kukai.ir.compiler import _parse_and_check
        from kukai.ir.translation_cert import certify_program
        for op, ver in ((_surface(), "2021"), (_surface(), "2026"),
                        (_toposolid(), "2026"), (_pad(), "2021"),
                        (_pad(), "2026"), (_subregion(), "2026"),
                        (_subregion(host={"by": "element_id", "value": 7777}),
                         "2026")):
            with self.subTest(op=op["op"], variety=op.get("variety"), ver=ver):
                grounded = ground_mod.ground(_parse_and_check(_prog([op])),
                                             SNAPSHOT)
                cert = certify_program(grounded, ver)
                self.assertTrue(cert.proven, cert.gaps)


if __name__ == "__main__":
    unittest.main()
