"""wave/mass (2026-08-10): create_face_wall — единственная дверь из
концептуальной массы в настоящий BIM.

ПОЧЕМУ ЭТА ВОЛНА И ПОЧЕМУ У НЕЁ ОДНА ОПЕРАЦИЯ, А НЕ ВОСЕМЬ. Перепись назвала
семейство «свободные формы и массы» почти слепым (2 из 12) и оставила гипотезу
из шести форм массы, `DividedSurface` и `DividedPath`. Замер компиляцией против
шести эталонных сборок (живой :52412, 10.08) гипотезу опроверг: ВСЕ ШЕСТЬ форм
живут только на `doc.FamilyCreate`, а этот аксессор документирован дословно и
одинаково на 2021 и 2026 — «thrown when the current document is project
document». KIR пишет в проектный документ, значит шесть фабрик недостижимы ПО
ДВЕРИ, а не по условию внутри вызова. Полная таблица замера — в шапке
`ops_mass.py`; здесь повторены только выводы, которые проверяются кодом ниже.

КЛАСС `FamilyDocumentBoundary` — ГЛАВНЫЙ В ЭТОМ ФАЙЛЕ. Он держит не поведение
операции, а ГРАНИЦУ, на которой стоит вся глава: ни один эмиттер реестра не
имеет права позвать `doc.FamilyCreate`. Правка, добавляющая форму массы «как
у всех остальных», выглядит как расширение возможностей и на живом Revit
бросает всегда — то есть это ровно тот дефект, который офлайн-ворота Roslyn
увидеть НЕ МОГУТ (вызов собирается 6/6). Единственное место, где его можно
поймать до живого прогона, — здесь.
"""
import os
import re
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(),
                                   "kir_test_mass_queue.jsonl"))

from kukai.ir import spec                                        # noqa: E402
from kukai.ir.compiler import compile_program                    # noqa: E402
from kukai.ir.ops_mass import FACE_WALL_LOCATION_LINES           # noqa: E402
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT as SNAPSHOT  # noqa: E402

OP = "create_face_wall"
HOST_ID = {"by": "element_id", "value": 900001}
BRICK = {"by": "name", "value": "Кирпич 250"}


def _fw(oid="FW1", **kw):
    op = {"op": OP, "id": oid, "host": HOST_ID,
          "face_normal": [0.6, 0.0, 0.8], "location_line": "core_exterior",
          "type": BRICK}
    op.update(kw)
    return op


def _emit(ops, ver="2026", isolation="atomic", snapshot=SNAPSHOT):
    return compile_program({"ir_version": "1.0", "intent": "mass-test",
                            "ops": ops},
                           revit_version=ver, snapshot=snapshot,
                           isolation=isolation)


def _cs(ops=None, **kw):
    out = _emit(ops or [_fw()], **kw)
    assert out.ok, [d.as_dict() for d in out.diagnostics]
    return out.csharp


class RegistryShape(unittest.TestCase):
    def test_the_op_is_a_registered_writing_create(self):
        self.assertIn(OP, spec.OPS)
        o = spec.OPS[OP]
        self.assertTrue(o.writes_model)
        self.assertEqual(o.effect.value, "create")

    def test_it_grounds_the_same_wall_type_pool_as_create_wall(self):
        """ПУЛ ОБЩИЙ С `create_wall`, И ЭТО РЕШЕНИЕ, А НЕ СОВПАДЕНИЕ.

        Класс типа тот же (`WallType`), значит второй пул на те же элементы
        означал бы два ответа на один вопрос. Пригодность КОНКРЕТНОГО типа для
        стены по грани решает не пул, а сам Revit — предполётом ниже.
        """
        pools = {p: pool for p, pool, _ in spec.OPS[OP].grounded}
        self.assertEqual(pools, {"type": "wall_types"})
        wall_pools = {p: pool for p, pool, _ in spec.OPS["create_wall"].grounded}
        self.assertEqual(pools["type"], wall_pools["type"])

    def test_it_declares_no_tolerance(self):
        """НИ ОДНОГО ДОПУСКА — СЛЕДСТВИЕ, А НЕ ПРОБЕЛ.

        Единственное числовое сравнение волны (положение грани) сравнивает с
        суммой `WallType.Width` и `doc.Application.VertexTolerance` — обе
        величины Revit сообщает САМ, и обе зависят от геометрии операции,
        поэтому реестровой константой быть не могут по построению. Замок нужен
        затем, что обратная правка — вписать сюда число — выглядит как
        улучшение, а на деле это «bound authored by reasoning».
        """
        self.assertEqual(spec.OPS[OP].tolerances, {})
        self.assertNotIn("±", spec.OPS[OP].post)

    def test_location_line_is_closed_mandatory_and_undefaulted(self):
        """АРГУМЕНТ ВЫЗОВА, А НЕ НЕОБЯЗАТЕЛЬНОЕ ПОЛЕ: подставить его за автора
        значило бы молча решить, с какой стороны грани встанет тело."""
        p = {x.name: x for x in spec.OPS[OP].params}["location_line"]
        self.assertEqual(set(p.choices), set(FACE_WALL_LOCATION_LINES))
        self.assertTrue(p.required)
        self.assertIsNone(p.default)

    def test_the_six_location_lines_are_spelled_like_create_wall(self):
        """ОДНО ПОНЯТИЕ — ОДНО НАПИСАНИЕ. Два разных слова для одного и того
        же в одном реестре заставили бы автора гадать, одно ли это и то же.
        `create_wall` предъявляет три из шести (сужение объяснено ЛИФТОМ), но
        КАЖДОЕ его слово обязано найтись здесь.
        """
        from kukai.ir.ops_authoring import WALL_LOCATION_LINE_ORDINALS
        self.assertEqual(set(FACE_WALL_LOCATION_LINES),
                         set(WALL_LOCATION_LINE_ORDINALS))
        wall = {x.name: x for x in spec.OPS["create_wall"].params}["location_line"]
        for word in wall.choices:
            with self.subTest(word=word):
                self.assertIn(word, FACE_WALL_LOCATION_LINES)

    def test_face_normal_is_mandatory_and_is_not_millimetres(self):
        """РОД `pt_xyz`, НО НЕ МИЛЛИМЕТРЫ — тот же приём, что у
        `move_elements.delta_mm`, и он обязан быть НАЗВАН, а не подразумеваться.
        """
        p = {x.name: x for x in spec.OPS[OP].params}["face_normal"]
        self.assertEqual(p.kind, "pt_xyz")
        self.assertTrue(p.required)
        self.assertIn("НАПРАВЛЕНИЕ", _validation_source())

    def test_it_claims_element_not_geometry(self):
        """НАСТОЯЩИЙ ЭЛЕМЕНТ, А НЕ «ГЕОМЕТРИЯ»: у стены по грани есть тип,
        слои и площадь в спецификации — всё, чего у DirectShape нет по
        построению. Это и есть весь смысл волны, и он объявлен в клетке."""
        cap = spec.OPS[OP].capability
        self.assertIn(("create", "element"), cap)
        self.assertNotIn(("create", "geometry"), cap)
        self.assertNotIn(("create", "geometry"),
                         spec.OPS[OP].capability)


def _validation_source() -> str:
    import kukai.ir.authoring_validation as m
    with open(m.__file__, encoding="utf-8") as fh:
        return fh.read()


class FamilyDocumentBoundary(unittest.TestCase):
    """ГРАНИЦА, НА КОТОРОЙ СТОИТ ВСЯ ГЛАВА МАСС.

    `Document.FamilyCreate` документирован дословно и одинаково во всех шести
    RevitAPI.xml (перечитаны по одной, а не по двум крайним):
    *«Thrown when the current document is project document»*. Все шесть фабрик
    форм массы живут ТОЛЬКО на нём (`doc.Create.NewExtrusionForm` и остальные
    пять — CS1061 на всех шести), поэтому в проектном документе они бросают
    ГАРАНТИРОВАННО.

    И вот почему этот класс нужен: такой вызов СОБИРАЕТСЯ 6/6. Ворота Roslyn
    его пропустят, гейт останется зелёным, а живой Revit будет отказывать
    всегда. Офлайн эту границу видно ровно в одном месте — здесь.
    """

    _FORBIDDEN = (
        "FamilyCreate",
        "NewExtrusionForm", "NewRevolveForms", "NewSweptBlendForm",
        "NewLoftForm", "NewFormByThickenSingleSurface", "NewFormByCap",
        "FreeFormElement.Create",
    )

    def test_no_registry_emitter_ever_calls_the_family_only_door(self):
        import kukai.ir.authoring as authoring
        sources = []
        for mod in (authoring,):
            with open(mod.__file__, encoding="utf-8") as fh:
                sources.append(fh.read())
        for name in ("mass_emit", "solid_emit", "shape_emit"):
            mod = __import__(f"kukai.ir.{name}", fromlist=["x"])
            with open(mod.__file__, encoding="utf-8") as fh:
                sources.append(fh.read())
        blob = "\n".join(sources)
        # Строки-упоминания в КОММЕНТАРИЯХ законны и нужны — именно они
        # объясняют следующему, почему этих вызовов нет. Ищем ВЫЗОВ: имя,
        # за которым сразу открывающая скобка.
        for member in self._FORBIDDEN:
            with self.subTest(member=member):
                self.assertIsNone(
                    re.search(re.escape(member) + r"\s*\(", blob),
                    f"{member} — вызов из семейного документа; KIR пишет в "
                    f"ПРОЕКТНЫЙ, и Revit бросит на нём всегда")

    def test_the_taken_op_is_the_documented_inverse(self):
        """`FaceWall.Create` взята не «потому что осталась», а потому что у
        неё одной условие броска — ТОЧНАЯ ИНВЕРСИЯ отказа форм: «document is
        not a project document». Причина обязана стоять в тексте, который
        читает человек, а не только в голове автора волны."""
        import kukai.ir.ops_mass as m
        self.assertIn("document is not a project document", m.__doc__)
        self.assertIn("thrown when the current document is project document",
                      m.__doc__.lower())


class NamedAbsence(unittest.TestCase):
    """ВТОРОЙ ПО ВАЖНОСТИ КЛАСС: чего свидетель НЕ утверждает.

    У волны тел свидетель сверяет объём с замкнутой формой, посчитанной на
    компиляции. ЗДЕСЬ ТАКОЙ ВЕЛИЧИНЫ НЕТ и быть не может — форму задаёт грань
    чужого элемента. Соблазн дописать «площадь стены == площадь грани» силён и
    выглядит как усиление; накрывает ли Revit грань целиком, не сказано ни в
    одной из шести RevitAPI.xml, поэтому такая проверка отвергала бы исправную
    работу. Названо вслух и заперто.
    """

    def test_the_absence_is_stated_in_post(self):
        post = spec.OPS[OP].post
        self.assertIn("NAMED ABSENCE", post)
        self.assertIn("area equality", post)

    def test_the_clause_is_registered_as_non_witnessable(self):
        from kukai.ir.translation_cert import _NON_WITNESSABLE_CLAUSES
        markers = _NON_WITNESSABLE_CLAUSES[OP]
        self.assertEqual(len(markers), 1)
        marker, why = markers[0]
        self.assertIn(marker, spec.OPS[OP].post.lower())
        self.assertIn("documented nowhere", why)

    def test_the_registry_audit_is_clean(self):
        from kukai.ir.translation_cert import audit_registry_coverage
        self.assertEqual(audit_registry_coverage(), ())

    def test_the_raw_pair_rides_the_receipt_not_the_verdict(self):
        """ОБА ЧИСЛА В КВИТАНЦИИ И НИ ОДНО В ВЕРДИКТЕ — первый живой прогон
        тем самым ИЗМЕРИТ остаток, а не оценит его."""
        cs = _cs()
        # Оба числа — в блоке квитанции (`__results`), и НИ ОДНО не входит
        # ни в один вердикт (`__post.Add`): вердикт утверждает, квитанция
        # наблюдает, и смешать их значило бы утвердить величину, которой
        # никто не мерил.
        self.assertIn('__rb["named_face_area_mm2"]', cs)
        self.assertIn('__rb["built_face_area_mm2"]', cs)
        import re as _re
        for verdict in _re.findall(r"__post\.Add\((.*?)\);", cs, _re.S):
            with self.subTest(verdict=verdict[:60]):
                self.assertNotIn("area_mm2", verdict)
                self.assertNotIn("__farea_", verdict)
                self.assertNotIn("__warea_", verdict)


class VersionAxis(unittest.TestCase):
    def test_six_versions_receive_the_same_csharp(self):
        """ОСИ ВЕРСИЙ НЕТ — И ЭТО УТВЕРЖДЕНИЕ, А НЕ УМОЛЧАНИЕ. Все члены,
        которые называет эмиттер, замерены 6/6, поэтому расхождения быть не
        должно нигде. Тест ловит будущую правку, которая втихую заведёт
        версионную ветку там, где API её не требует."""
        texts = {}
        for ver in spec.REVIT_VERSIONS:
            out = _emit([_fw()], ver=ver)
            self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
            texts[ver] = out.csharp
        self.assertEqual(len(set(texts.values())), 1)


class Ground(unittest.TestCase):
    def test_named_type_is_resolved_by_name(self):
        cs = _cs()
        self.assertIn("100", cs)          # id пула «Кирпич 250»

    def test_an_ambiguous_pool_refuses_instead_of_picking(self):
        """Пул стен в снимке — ДВА типа. Пропущенный `type` обязан дать
        типизированный вопрос с кандидатами, а не `.FirstOrDefault()`: живой
        парный замер 02.08 на Snowdon показал цену выбора — плечо C# взяло
        1 тип двери из 62 МОЛЧА и построило."""
        op = _fw()
        op.pop("type")
        out = _emit([op])
        self.assertFalse(out.ok)

    def test_an_existing_mass_by_element_id_is_legal(self):
        """ГЛАВНЫЙ СЦЕНАРИЙ: стену по грани строят по массе, которая УЖЕ
        СТОИТ. Требовать `ref` значило бы запретить его."""
        self.assertTrue(_emit([_fw()]).ok)

    def test_a_mass_placed_by_the_same_program_is_legal_too(self):
        placed = {"op": "place_family", "id": "M1",
                  "symbol": {"by": "family_type", "category": "OST_Furniture",
                             "family_name": "Стол офисный",
                             "type_name": "Стол 1200"},
                  "xyz": [1000, 2000, 0],
                  "level": {"by": "name", "value": "Этаж 1"}}
        out = _emit([placed, _fw(oid="FW2", host={"by": "ref", "value": "M1"})])
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])


class Negative(unittest.TestCase):
    def test_face_normal_is_mandatory(self):
        op = _fw()
        op.pop("face_normal")
        self.assertFalse(_emit([op]).ok)

    def test_a_zero_vector_is_refused_at_parse_time(self):
        """ТОЧНЫЙ НОЛЬ — ВЫРОЖДЕННОСТЬ ПО ОПРЕДЕЛЕНИЮ, а не порог. Отказ
        стоит на разборе именно потому, что это равенство, а не сравнение с
        числом."""
        out = _emit([_fw(face_normal=[0, 0, 0])])
        self.assertFalse(out.ok)
        self.assertTrue(any("нулевой вектор" in (d.message_ru or "")
                            for d in out.diagnostics))

    def test_a_near_zero_vector_is_left_to_revit(self):
        """И РОВНО ОБРАТНОЕ: «почти нулевой» вектор компилятор НЕ трогает.
        Где проходит эта граница, знает только Revit, и он отвечает на неё
        своим `XYZ.IsZeroLength()` в рантайме. Назначить порог здесь значило
        бы завести число, которого никто не мерил, рядом с числом, которое
        Revit сообщает сам."""
        out = _emit([_fw(face_normal=[1e-12, 0, 0])])
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        self.assertIn("IsZeroLength", out.csharp)

    def test_location_line_is_mandatory(self):
        op = _fw()
        op.pop("location_line")
        self.assertFalse(_emit([op]).ok)

    def test_an_unknown_location_line_refuses(self):
        self.assertFalse(_emit([_fw(location_line="по_потолку")]).ok)

    def test_host_is_mandatory(self):
        op = _fw()
        op.pop("host")
        self.assertFalse(_emit([op]).ok)


class Emission(unittest.TestCase):
    def test_both_revit_preflights_stand_before_the_call(self):
        """ОБА ПРЕДПОЛЁТА — ДО ЭФФЕКТА. Спросить их после вызова уже нечего:
        отказ приедет исключением и ляжет в квитанцию как `internal`, то есть
        «у нас что-то сломалось» вместо «Revit не берёт такой тип/грань»."""
        cs = _cs()
        call = cs.index("FaceWall.Create(")
        for guard in ("IsWallTypeValidForFaceWall",
                      "IsValidFaceReferenceForFaceWall"):
            with self.subTest(guard=guard):
                self.assertIn(guard, cs)
                self.assertLess(cs.index(guard), call)

    def test_the_face_walk_is_facerefs_and_not_a_second_one(self):
        """ОТБОР ГРАНИ — ЧУЖИМ КОДОМ, СВОИМ ЗАКОНОМ. Помощники обхода
        приходят из `faceref`; второй отбор рядом означал бы два места, где
        закон мощности можно ослабить порознь."""
        cs = _cs()
        self.assertIn("__faceWalk_", cs)
        self.assertIn("__faceKeep_", cs)
        self.assertIn("GetSymbolGeometry()", cs)
        # Ловушка, стоившая живого отказа волне аннотаций: `GetInstanceGeometry`
        # документирован как КОПИЯ, чьи ссылки непригодны для создания новых
        # элементов. Она не должна вернуться сюда.
        self.assertNotIn("GetInstanceGeometry", cs)

    def test_cardinality_decides_and_the_refusal_names_the_count(self):
        cs = _cs()
        self.assertIn("отвечает не одна грань, а", cs)
        self.assertIn(".Count.ToString()", cs)

    def test_the_refusal_speaks_this_ops_vocabulary_not_the_selectors(self):
        """ОТКАЗ, ПОСЫЛАЮЩИЙ АВТОРА ПРАВИТЬ НЕСУЩЕСТВУЮЩЕЕ ПОЛЕ, ДОРОЖЕ
        ОТСУТСТВИЯ ОТКАЗА.

        Собственный текст `faceref` отсылает к `predicate.side` и
        `predicate.normal` — словарю ВТОРОЙ СТУПЕНИ СЕЛЕКТОРА. У этой операции
        таких полей нет вовсе: направление приходит обычным параметром
        `face_normal`, ровно как сторона у `create_slab_edge`. Помощник поэтому
        принимает СЛЕДУЮЩИЙ ХОД словами вызывающего, а не переписывается
        строковой заменой по эмитированному C# (замена — запрещённый приём,
        KIR-E005).
        """
        cs = _cs()
        self.assertNotIn("predicate.side", cs)
        self.assertNotIn("predicate.normal", cs)
        self.assertIn("face_normal", cs)
        # И правило самого Revit названо в отказе, а не оставлено на догадку.
        self.assertIn("наклонной грани массы", cs)

    def test_the_shared_helper_keeps_its_old_text_by_default(self):
        """РАСШИРЕНИЕ ПОМОЩНИКА НЕ ИМЕЕТ ПРАВА ДВИГАТЬ ТЕХ, КТО ЕГО УЖЕ ЗВАЛ.
        Умолчание обязано дать ДОСЛОВНО прежний текст — иначе одна волна тихо
        переписала бы диагностику соседней."""
        import inspect
        from kukai.ir import faceref
        src = inspect.getsource(faceref.resolve_cs)
        self.assertIn("либо назови сторону (predicate.side)", src)
        self.assertIn("рядом с predicate.side (или наоборот)", src)

    def test_the_op_never_reads_coordinates_off_the_instance_face(self):
        """ЕДИНСТВЕННОЕ МЕСТО, ГДЕ ЭТА ВОЛНА МОГЛА СОВРАТЬ ТИХО.

        Носитель — `FamilyInstance`, и грань его тела живёт в СИМВОЛЬНЫХ
        координатах. Площадь к жёсткому преобразованию инвариантна, поэтому
        читать её по этой ссылке законно; ЛЮБАЯ координата (Origin,
        FaceNormal) по ней означала бы третью систему координат в свидетеле —
        тот же род ошибки, что назначенный допуск, только тише.
        """
        cs = _cs()
        used = set(re.findall(r"__mf_[A-Za-z0-9_]*\.([A-Za-z_]+)", cs))
        self.assertEqual(used, {"Area"}, f"с грани массы прочитано лишнее: {used}")

    def test_the_documented_null_return_is_guarded(self):
        cs = _cs()
        self.assertIn("создание вернуло null", cs)

    def test_the_location_line_reaches_the_call(self):
        for word, member in FACE_WALL_LOCATION_LINES.items():
            with self.subTest(word=word):
                cs = _cs([_fw(location_line=word)])
                self.assertIn(f"WallLocationLine.{member}", cs)


class Witness(unittest.TestCase):
    def test_the_geometry_witness_reads_the_built_wall(self):
        """ЧИТАЕТСЯ ПОСТРОЕННАЯ СТЕНА, А НЕ НАШ ВЫЗОВ: у неё спрашиваются
        наружные грани, и среди них обязана быть РОВНО ОДНА, сонаправленная
        названной грани массы."""
        cs = _cs()
        self.assertIn("HostObjectUtils.GetSideFaces(__el_", cs)
        self.assertIn("ShellLayerType.Exterior", cs)
        self.assertIn("__wfn_", cs)

    def test_the_normal_test_invents_no_tolerance(self):
        """Параллельность решает РОДНОЙ тест Revit, сонаправленность — знак
        скалярного произведения. Ни одного своего числа."""
        cs = _cs()
        self.assertIn("CrossProduct", cs)
        self.assertIn("IsZeroLength()", cs)
        self.assertIn("DotProduct", cs)

    def test_the_position_bound_is_revits_own_two_numbers(self):
        cs = _cs()
        self.assertIn("__ty_FW1.Width", cs)
        self.assertIn("doc.Application.VertexTolerance", cs)
        self.assertIn("get_BoundingBox(null)", cs)

    def test_the_vacuity_floor_reads_the_SOLID_not_a_parameter(self):
        """§18.3: СВИДЕТЕЛЬ ПОДПИСЫВАЕТ ТУ ОСЬ, КОТОРУЮ ЧИТАЛ.

        Первая редакция этой волны читала здесь `HOST_AREA_COMPUTED` и всё
        равно подписывала (geometry) — то есть удостоверяла ось, на которую не
        смотрела. Поймал это страж дома, а не человек, и поймал в самом
        неочевидном месте: параметр С ИМЕНЕМ ПРО ПЛОЩАДЬ выглядит геометрией
        убедительнее многих настоящих чтений. Замок здесь стоит затем, чтобы
        обратная правка («взять готовый параметр, он же уже посчитан») не
        прошла молча.
        """
        cs = _cs()
        self.assertNotIn("HOST_AREA_COMPUTED", cs)
        self.assertIn("__warea_FW1 = __wp_FW1.Area;", cs)
        i = cs.index("площадь наружной грани построенного тела")
        self.assertIn("__warea_FW1", cs[max(0, i - 200):i])

    def test_every_verdict_signs_the_axis_it_reads(self):
        """Свидетель подписывает ту ось, которую читал: тип — (topology),
        геометрия — (geometry). Проверка, читающая габарит и подписывающая
        (topology), удостоверяет то, на что никто не смотрел."""
        cs = _cs()
        for phrase, axis in (
                ("тип построенной стены по грани", "topology"),
                ("наружных граней построенной стены", "geometry"),
                ("лежит вне габарита носителя", "geometry"),
                ("площадь наружной грани построенного тела", "geometry")):
            with self.subTest(phrase=phrase):
                i = cs.index(phrase)
                self.assertIn(axis, cs[i:i + 400])


class CommitGateInvariants(unittest.TestCase):
    def test_per_op_isolation_uses_the_op_local_refusal(self):
        """В `per_op` отказ обязан быть ОП-ЛОКАЛЬНЫМ. Уцелевший
        `__t.RollBack()` внутри обёрнутого create означал бы, что отказ одной
        операции откатывает уже зафиксированных соседей — дефект, закрытый
        28.07 и охраняемый KIR-E005."""
        cs = _cs(isolation="per_op")
        self.assertIn("__OpRefuse", cs)

    def test_the_created_element_is_stamped(self):
        self.assertIn("__el_FW1", _cs())

    def test_names_read_by_the_witness_are_declared_outside_create(self):
        """КОНТРАКТ ОБЛАСТЕЙ ВИДИМОСТИ: при `per_op` create и post попадают в
        РАЗНЫЕ области, и имя, объявленное внутри create, свидетелю не видно
        (CS0103). Гейт Roslyn это ловит, но только на шести версиях сразу —
        здесь дешевле."""
        out = _emit([_fw()], isolation="per_op")
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        # Инициализаторы РАЗНЫЕ по типу (`null` у ссылок, `0.0` у чисел,
        # `0` у счётчика, `false` у флага), поэтому проверяется САМО
        # объявление: имя, за которым стоит присваивание, а не конкретное
        # начальное значение.
        import re as _re
        for name in ("__wfn_FW1", "__inbb_FW1", "__ty_FW1", "__hsrc_FW1",
                     "__warea_FW1", "__farea_FW1", "__wwid_FW1", "__wtol_FW1"):
            with self.subTest(name=name):
                decl_head = out.csharp.split("// create_face_wall")[0]
                self.assertRegex(decl_head, r"\b" + name + r" = [^;]+;")


class ReverseAndCensus(unittest.TestCase):
    def test_the_reverse_gap_carries_a_date_and_a_deadline(self):
        """ПРОБЕЛ ЗАХВАТА БЕЗ СРОКА — ЭТО «КОГДА-НИБУДЬ», А НЕ РЕШЕНИЕ.
        Импорт `reverse_contract` отказал бы сам, но проверка стоит здесь
        затем, чтобы следующий видел ПОЧЕМУ именно capture_gap, а не
        lifter_gap: чтение не приносит ни носителя, ни нормали грани."""
        from kukai.ir.reverse_contract import (
            REVERSE_CONTRACTS, ReverseMode, ReverseGuarantee)
        rc = REVERSE_CONTRACTS[OP]
        self.assertIs(rc.mode, ReverseMode.CAPTURE_GAP)
        self.assertIs(rc.guarantee, ReverseGuarantee.NONE)
        self.assertEqual(rc.decided_on, "2026-08-10")
        self.assertEqual(rc.due, "2026-09-09")

    def test_the_census_key_is_exact_and_single(self):
        """Категория известна ТОЧНО и ровно одна: её задаёт сам вызов, а не
        селектор типа. Пары здесь не нужно — выбора между категориями у
        операции нет ни в каком поле."""
        from kukai.ir.acceptance import _category_of_op
        self.assertEqual(_category_of_op({"op": OP}), ("OST_Walls",))

    def test_clash_declares_the_blind_spot_with_a_reason(self):
        """Тело настоящее, оболочки нет, и причина ИМЕННАЯ: оболочка стены
        строится из `LocationCurve`, а `FaceWall` — не `Wall` (замерено,
        CS0029 на всех шести) и `LocationCurve` не имеет вовсе.

        СЛЕПОЕ ПЯТНО СПРАШИВАЕТСЯ У ТОГО, КТО ЕГО ДЕРЖИТ (правка 11.08.2026).
        Здесь стояло `assertIsNone(category_of({"op": OP}))` — утверждение о
        ТЕЛЕ, прочитанное через ответ о КАТЕГОРИИ. Две разные величины:
        `category_of` отвечает «куда результат попадёт в Revit»,
        `OP_NO_BODY` — «можем ли мы построить оболочку». Стена по грани массы
        ЕСТЬ стена (`OST_Walls`) и оболочки не имеет; ровно это и написано
        строкой выше в `test_the_census_key_is_exact_and_single`, которая
        требует `("OST_Walls",)` — то есть файл утверждал обе половины разом и
        противоречил сам себе, пока одна из них молчала.

        Из 69 опов реестра это ЕДИНСТВЕННЫЙ, у которого ответы расходятся, и
        потому единственный, на котором подмена одной величины другой заметна.
        Замок на 1-из-69 стоит в `test_clash_in_the_receipt`.
        """
        from kukai.ir.clash_bundle import OP_NO_BODY, category_of, op_categories
        self.assertIn(OP, OP_NO_BODY)
        self.assertIn("LocationCurve", OP_NO_BODY[OP])
        # Тела нет — и это утверждается ТЕМ, кто про тело знает.
        self.assertNotIn(OP, __import__(
            "kukai.ir.clash_bundle", fromlist=["x"]).body_making_ops())
        # Категория при этом ИЗВЕСТНА, и её знание не отменяет отсутствия тела.
        self.assertEqual(category_of({"op": OP}), "OST_Walls")
        self.assertEqual(op_categories(OP), ("OST_Walls",))


if __name__ == "__main__":
    unittest.main()
