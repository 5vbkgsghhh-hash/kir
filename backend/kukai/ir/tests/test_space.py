"""wave/space (2026-08-10): create_space — пространство ОВК (OST_MEPSpaces).

ПОЧЕМУ ЭТА ВОЛНА — ЗАМЕР ПО КОРПУСУ, А НЕ ЖЕЛАНИЕ. 10.08 по 76 сохранённым
разборам (`backend/data/decompile/*/L0.jsonl`, записи `category_status` и
`document.census`):

    разборов, где извлечение вообще смотрело OST_MEPSpaces      44 из 76
    разборов с ненулевым числом пространств                      6
    зданий                                                       2
      Snowdon Towers Sample Electrical (snowdon_elec_v1)        80
      Snowdon Towers Sample Plumbing      (plumb_v1..v4)        43
      Snowdon Towers Sample Architectural (plumb_v5)            46
                                                             ----
                                                              169

    ПОПРАВКА 11.08 К ЗАМЕРУ ЭТОЙ ЖЕ ВОЛНЫ: здесь стояло «126 / 2
    здания». Каталог `snowdon_plumb_v5` несёт в заголовке L0
    `doc_name: "Snowdon Towers Sample Architectural"` — ТРЕТИЙ
    документ, а не пятая ревизия сантехники. Имя каталога было
    принято за имя документа; документ называет только `doc_name`.
    у всех шести: expected_count == extracted_count, state=complete

То есть ЧТЕНИЕ пространства умеет и умело всё это время, а лифтер — нет:
таблица кандидатов `lift.py` знает "OST_Rooms" и не знает "OST_MEPSpaces",
поэтому все 126 элементов уходили в атомы «операции не существует». Это была
правда; с этой волной перестало быть.

API СНЯТ С СБОРОК, А НЕ С ДОКУМЕНТАЦИИ. Два независимых прибора, 10.08:
рефлексия по шести `RevitAPI.dll` (`data/api_surface/api_signatures_*.json`)
и живая компиляция на :52412 ОТДЕЛЬНЫМ прогоном на каждую версию.

    doc.Create.NewSpace(Level, UV)        -> Space               6/6
    doc.Create.NewSpace(Level, Phase, UV) -> Space               6/6
    doc.Create.NewSpace(Phase)            -> Space               6/6
    безаргументной перегрузки НЕТ                        CS1501, 0/6
    возвращаемый тип доказан CS0029 («Cannot implicitly convert type
        'Autodesk.Revit.DB.Mechanical.Space' to 'int'») на всех шести
    Space.Location/.Area/.Volume/.Number/.Name/.LevelId/.Level   6/6
    SpatialElement.GetBoundarySegments(...)                      6/6
    BuiltInCategory.OST_MEPSpaces                                6/6
    Space.Unplace()                                      CS1061, 0/6
        при том что Room.Unplace() есть                          6/6

Структура повторяет test_room.py (Registry / VersionAxis / Signature /
TwoBadOutcomes / Witnesses / Acceptance / Reverse / PBT).
"""
import os
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(),
                                   "kir_test_space_queue.jsonl"))

from kukai.ir import spec                                        # noqa: E402
from kukai.ir.compiler import compile_program                    # noqa: E402
from kukai.ir.registry_base import IdentityCardinality           # noqa: E402
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT as SNAPSHOT  # noqa: E402

OP = "create_space"
LVL = {"by": "element_id", "value": 42}
LVL_BY_NAME = {"by": "name", "value": SNAPSHOT["levels"][0]["name"]}


def _prog(ops, intent="space-test"):
    return {"ir_version": "1.0", "intent": intent, "ops": ops}


def _space(oid="SP1", **kw):
    op = {"op": OP, "id": oid, "xy": [4000, 3000], "level": LVL}
    op.update(kw)
    return op


def _codes(out):
    return [d.code for d in out.diagnostics]


def _checks(ver="2024", op=None):
    """Свидетели опа как ОБЪЕКТЫ — не текстом, чтобы не мерить прозу."""
    from kukai.ir import ground as ground_mod
    from kukai.ir.authoring import _EMITTERS
    from kukai.ir.compiler import _parse_and_check
    grounded = ground_mod.ground(
        _parse_and_check(_prog([op or _space()])), SNAPSHOT)
    _d, create, checks, readback = _EMITTERS[OP](
        dict(grounded[0]), ver, "kir:test")
    return create, checks, readback


# ── реестр ───────────────────────────────────────────────────────────────────

class RegistryShape(unittest.TestCase):

    def test_the_op_is_registered(self):
        self.assertIn(OP, spec.OPS)

    def test_it_declares_itself_a_writer(self):
        self.assertTrue(spec.OPS[OP].writes_model)
        self.assertEqual(spec.OPS[OP].family, "authoring")

    def test_it_lives_in_the_room_family_module(self):
        """Пространство — родня разделителю (оба SpatialElement, оба про
        границу объёма), а ops_authoring.py, где живёт create_room, — самый
        занятый файл реестра, куда одновременно пишут все волны."""
        from kukai.ir import ops_room
        self.assertIn(OP, [op.name for op in ops_room.OPS])

    def test_the_result_is_one_identity_and_it_is_referenceable(self):
        """В отличие от разделителя (МНОГО личностей): NewSpace возвращает
        ровно один Space, значит следующий оп вправе на него сослаться."""
        result = spec.OPS[OP].result
        self.assertIs(result.identity_cardinality, IdentityCardinality.ONE)
        self.assertEqual(result.identity_field, "id")
        self.assertTrue(result.referenceable)

    def test_it_grounds_only_the_level(self):
        self.assertEqual(
            {p: pool for p, pool, _ in spec.OPS[OP].grounded},
            {"level": "levels"})


# ── сигнатура: узкая НАМЕРЕННО, и компилятор это держит ──────────────────────

class SignatureIsDeliberatelyNarrow(unittest.TestCase):
    """v1 — ровно точка и уровень. Каждое отсутствие оплачено замером."""

    def test_the_op_takes_exactly_xy_and_level(self):
        self.assertEqual({p.name for p in spec.OPS[OP].params},
                         {"xy", "level"})

    def test_a_name_is_refused_by_the_compiler_not_merely_ignored(self):
        """ЗАМЕР 04.08 (живой Revit 2026), записанный в эмиттере create_room:
        сеттер `Room.Name` кладёт ТОЛЬКО имя, а геттер отдаёт «имя И НОМЕР»
        (`"KIR_GAP_ROOM_1 1"`), из-за чего свидетель откатывал КАЖДУЮ верно
        построенную комнату.

        Ведёт ли `Space` себя так же, офлайн не решается — но рефлексия по
        шести сборкам сужает вопрос: `Name` объявлен РОВНО ОДИН РАЗ, на
        `SpatialElement`, и ни Room, ни Space его не переопределяют. То есть
        склейка — свойство ТОГО ЖЕ члена. Ставки несимметричны: ошибка в эту
        сторону валит ВЕРНУЮ постройку, отсутствие параметра — ничего."""
        out = compile_program(_prog([_space(name="Венткамера")]),
                              revit_version="2024", snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-P003", _codes(out))

    def test_a_number_is_refused_the_same_way(self):
        out = compile_program(_prog([_space(number="1")]),
                              revit_version="2024", snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-P003", _codes(out))

    def test_a_type_is_refused_because_the_api_has_no_type_argument(self):
        """У `NewSpace` аргумента типа нет вовсе, и у всех 169 пространств
        корпуса `type_id`/`type_name` пусты. Пул типа обещал бы то, чего API
        не исполняет."""
        out = compile_program(
            _prog([_space(type={"by": "name", "value": "Пространство"})]),
            revit_version="2024", snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-P003", _codes(out))

    def test_the_point_is_two_dimensional(self):
        """Z у пространственного элемента задаёт УРОВЕНЬ: `SpatialElement.
        Location` документирован как «Z ... not changeable»."""
        out = compile_program(_prog([_space(xy=[1000, 2000, 3000])]),
                              revit_version="2024", snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T001", _codes(out))

    def test_the_level_is_mandatory(self):
        op = {"op": OP, "id": "SP1", "xy": [4000, 3000]}
        out = compile_program(_prog([op]), revit_version="2024",
                              snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-P005", _codes(out))


# ── ось версий: её НЕТ, и это замер ──────────────────────────────────────────

class VersionAxis(unittest.TestCase):

    def test_it_builds_on_all_six(self):
        for ver in spec.REVIT_VERSIONS:
            with self.subTest(version=ver):
                out = compile_program(_prog([_space()]), revit_version=ver,
                                      snapshot=SNAPSHOT)
                self.assertTrue(out.ok, _codes(out)[:3])
                self.assertIn("doc.Create.NewSpace(", out.csharp)

    def test_the_emitted_csharp_is_byte_identical_across_the_six(self):
        """ОСИ ВЕРСИЙ НЕТ — и это проверяемое утверждение, а не надежда.
        Три перегрузки NewSpace существуют на всех шести версиях с
        одинаковыми сигнатурами (замер 10.08), поэтому эмиттер не ветвится.
        Ветка, появившаяся здесь без замера РАЗНИЦЫ, — это код, недостижимый
        ни на одной цели; этот тест увидит её первым."""
        texts = {ver: compile_program(_prog([_space()]), revit_version=ver,
                                      snapshot=SNAPSHOT).csharp
                 for ver in spec.REVIT_VERSIONS}
        self.assertEqual(len(set(texts.values())), 1,
                         "эмиссия разошлась по версиям: %s"
                         % sorted(texts))

    def test_it_never_reads_a_member_absent_on_some_version(self):
        """`ElementId.IntegerValue` снят в 2026, `Category.BuiltInCategory`
        появился только в 2023 — ни того, ни другого в эмиссии быть не
        должно, как и `Space.Unplace()`, которого нет НИ НА ОДНОЙ (CS1061)."""
        for ver in spec.REVIT_VERSIONS:
            with self.subTest(version=ver):
                cs = compile_program(_prog([_space()]), revit_version=ver,
                                     snapshot=SNAPSHOT).csharp
                self.assertNotIn("IntegerValue", cs)
                self.assertNotIn(".BuiltInCategory", cs)
                self.assertNotIn("Unplace", cs)


# ── ДВА ПЛОХИХ ИСХОДА, КОТОРЫЕ НЕЛЬЗЯ ПУТАТЬ ────────────────────────────────

class TwoBadOutcomesAreNotOne(unittest.TestCase):
    """«Не размещено» и «не замкнуто» лечатся разным, поэтому и отвечает на
    них компилятор по-разному. `create_room` их НЕ различает: неразмещённая
    комната попадает у него в проверку `__loc == null || …` с сообщением
    «room placement mismatch (geometry)», то есть читается как «промахнулись
    мимо точки»."""

    def test_an_unplaced_space_is_a_typed_refusal_in_the_create_block(self):
        create, _checks_, _rb = _checks()
        self.assertIn("Location as LocationPoint) == null", create)
        self.assertIn("НЕ РАЗМЕЩЕНО", create)

    def test_the_unplaced_refusal_names_a_cause_and_a_next_move(self):
        """Молчащий откат неотличим от поломки: причина обязана быть в
        тексте, а не в голове автора."""
        create, _c, _rb = _checks()
        self.assertIn("не попала ни в одну область", create)
        self.assertIn("проверьте xy и level", create)

    def test_no_witness_ever_signs_an_unplaced_space_green(self):
        """Отказ стоит В БЛОКЕ СОЗДАНИЯ, то есть до постусловий: свидетелю
        неразмещённое пространство не достаётся вовсе."""
        out = compile_program(_prog([_space()]), revit_version="2024",
                              snapshot=SNAPSHOT)
        code = out.csharp
        self.assertLess(code.find("НЕ РАЗМЕЩЕНО"), code.find("// post SP1"))

    def test_an_unenclosed_space_is_a_postcondition_violation_not_a_refusal(self):
        """Операция сделала ровно то, что просили — пространство стоит в
        заданной точке на заданном уровне. Не сошлось ОБЕЩАНИЕ, и виновата
        МОДЕЛЬ, а не вызов. Та же развилка и тот же ответ, что у
        create_room."""
        _create, checks, _rb = _checks()
        keys = {c.obligation_key for c in checks}
        self.assertIn("area", keys)
        self.assertIn("boundary", keys)
        create, _c, _rb2 = _checks()
        self.assertNotIn("не замкнуто", create)


# ── свидетели ────────────────────────────────────────────────────────────────

class WitnessesReadTheResult(unittest.TestCase):

    def setUp(self):
        self.create, self.checks, self.readback = _checks()
        self.by_key = {c.obligation_key: c for c in self.checks}

    def test_every_promise_clause_has_an_obligation(self):
        # ЧЕРЕЗ АКСЕССОР, А НЕ ПО ГОЛОМУ ИМЕНИ. `REFINEMENT` — модульный
        # словарь, ПУСТОЙ до первого `_ensure_table()`: на свежем
        # интерпретаторе `REFINEMENT["create_wall"]` даёт KeyError.
        # Прежняя редакция читала имя напрямую и проходила или падала в
        # зависимости от того, вызвал ли кто-то раньше `certify_op`, —
        # а порядок тестов здесь ПЕРЕМЕШИВАЕТСЯ намеренно
        # (pytest-randomly). Замер 11.08, аудит класса «величина
        # утверждается в одном месте, читается в другом».
        from kukai.ir import translation_cert as tc
        ref = tc._ensure_table()[OP]
        self.assertEqual(
            len([c for c in spec.OPS[OP].post.split(";") if c.strip()]),
            len(ref.obligations))

    def test_the_certificate_proves_the_op_on_every_version(self):
        from kukai.ir import ground as ground_mod
        from kukai.ir.compiler import _parse_and_check
        from kukai.ir.translation_cert import certify_op
        grounded = ground_mod.ground(
            _parse_and_check(_prog([_space()])), SNAPSHOT)
        for ver in spec.REVIT_VERSIONS:
            with self.subTest(version=ver):
                cert = certify_op(dict(grounded[0]), ver)
                self.assertTrue(cert.proven, cert.gaps)
                self.assertEqual(cert.vacuous, ())

    def test_cutting_any_witness_makes_the_certificate_fall(self):
        """ЗАКОН L6: сильная форма честности — не слова, а МУТАЦИЯ. Аудит
        сверяет прозу по общим словам и потому пропускает подмену; вырезание
        живого свидетеля обязано ронять `proven`."""
        from kukai.ir import ground as ground_mod, room_emit
        from kukai.ir.authoring import _EMITTERS
        from kukai.ir.compiler import _parse_and_check
        from kukai.ir.translation_cert import certify_op
        grounded = ground_mod.ground(
            _parse_and_check(_prog([_space()])), SNAPSHOT)
        original = room_emit.emit_space
        try:
            for cut in ("level_binding", "location", "area", "boundary"):
                with self.subTest(cut=cut):
                    def mutated(op, ver, stamp, isolation="atomic", _c=cut):
                        d, c, checks, r = original(op, ver, stamp, isolation)
                        return d, c, [k for k in checks
                                      if k.obligation_key != _c], r
                    _EMITTERS[OP] = mutated
                    cert = certify_op(dict(grounded[0]), "2024")
                    self.assertFalse(cert.proven,
                                     "вырезан свидетель %s, а сертификат всё "
                                     "ещё доказан" % cut)
        finally:
            from kukai.ir import authoring
            _EMITTERS[OP] = authoring._emit_space

    def test_the_topology_axis_is_discharged_by_reading_boundaries(self):
        """ПОДПИСЫВАТЬ НАДО ТУ ОСЬ, КОТОРУЮ ЧИТАЕШЬ. Площадь отвечает
        «сколько», петли границы — «чем ограничено»; подпись «(topology)» под
        чтением площади сертифицировала бы отношение, которого никто не
        читал."""
        boundary = self.by_key["boundary"]
        self.assertIn("(topology)", boundary.message)
        self.assertIn("GetBoundarySegments",
                      boundary.reader_cs + boundary.verdict_cs)

    def test_the_area_witness_signs_geometry_and_reads_area(self):
        area = self.by_key["area"]
        self.assertIn("(geometry)", area.message)
        self.assertIn(".Area", area.verdict_cs)
        self.assertNotIn("(topology)", area.verdict_cs)

    def test_the_location_witness_reads_a_revit_computed_property(self):
        """§18.3: проверка, подписанная «(geometry)», чей читатель состоит
        ТОЛЬКО из `get_Parameter(...)`, геометрию не разряжает. Здесь
        читается `Location`, которую считает Revit."""
        location = self.by_key["location"]
        self.assertIn("(geometry)", location.message)
        self.assertIn("Location as LocationPoint", location.reader_cs)
        self.assertNotIn("get_Parameter", location.reader_cs)

    def test_no_witness_reads_back_a_parameter_this_op_wrote(self):
        """Оп не пишет НИ ОДНОГО параметра, значит и читать назад нечего:
        свидетель, подтверждающий собственный сеттер, — главный рецидивный
        дефект этого кода."""
        witness = "".join(c.reader_cs + c.verdict_cs for c in self.checks)
        self.assertNotIn("get_Parameter", witness)

    def test_the_volume_is_reported_but_never_witnessed(self):
        """`Space.Volume` существует 6/6, но его значение зависит от НАСТРОЙКИ
        документа (расчёт объёмов), а не от построенного элемента. В
        квитанции он честен, обязательством был бы ложью."""
        witness = "".join(c.reader_cs + c.verdict_cs for c in self.checks)
        self.assertNotIn(".Volume", witness)
        self.assertIn(".Volume", self.readback)

    def test_the_category_is_not_witnessed_and_that_is_a_decision(self):
        """`NewSpace` возвращает `Space` (тип доказан CS0029 на всех шести), а
        соответствие класса категории — инвариант самого Revit. Проверка,
        которая не может не сойтись, — `plate_z_doubling` в другой одежде.
        Категорию сверяет ПРИЁМКА по переписи, то есть независимый судья."""
        witness = "".join(c.reader_cs + c.verdict_cs for c in self.checks)
        self.assertNotIn("OST_MEPSpaces", witness)
        self.assertEqual(spec.op_result_categories({"op": OP}),
                         ("OST_MEPSpaces",))

    def test_the_receipt_never_offers_the_name_as_comparable(self):
        """`Space.Name` у Room замерен как СКЛЕЙКА имени с номером, поэтому
        ключ назван `name_and_number`: человеку полезно, сверять нельзя."""
        self.assertIn("name_and_number", self.readback)
        self.assertNotIn('__rb["name"]', self.readback)

    def test_the_tolerance_comes_from_the_registry(self):
        self.assertEqual(spec.OPS[OP].tolerances["location_mm"], 5.0)
        _c, checks, _rb = _checks()
        location = {c.obligation_key: c for c in checks}["location"]
        self.assertEqual(location.tol, 5.0)


# ── шов транзакции и областей видимости ──────────────────────────────────────

class CommitGateInvariants(unittest.TestCase):

    def setUp(self):
        self.code = compile_program(_prog([_space()]), revit_version="2024",
                                    snapshot=SNAPSHOT).csharp

    def test_one_transaction(self):
        self.assertEqual(self.code.count("new Transaction(doc"), 1)

    def test_regenerate_precedes_postconditions(self):
        self.assertLess(self.code.find("doc.Regenerate();"),
                        self.code.find("// post SP1"))

    def test_the_creation_is_stamped(self):
        self.assertIn("ALL_MODEL_INSTANCE_COMMENTS", self.code)

    def test_a_null_result_is_a_refusal_not_a_success(self):
        self.assertIn("NewSpace вернул null", self.code)

    def test_it_survives_per_op_isolation(self):
        """Живые грабли волны ограждений: переменная, объявленная внутри
        create, свидетелю в per_op не видна (CS0103 на шести прогонах)."""
        for ver in spec.REVIT_VERSIONS:
            with self.subTest(version=ver):
                out = compile_program(
                    _prog([_space("SP1"), _space("SP2", xy=[9000, 9000])]),
                    revit_version=ver, snapshot=SNAPSHOT, bulk=True,
                    isolation="per_op")
                self.assertTrue(out.ok, _codes(out)[:3])

    def test_walls_before_a_space_force_a_regenerate(self):
        """v0-правило create_room распространено на пространство: NewSpace
        разрешает объемлющую область В МОМЕНТ СОЗДАНИЯ, поэтому пространство,
        созданное сразу после своих стен, прочитало бы Area == 0 и откатило
        бы ВЕРНУЮ программу."""
        out = compile_program(_prog([
            {"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
             "p1_mm": [8000, 0], "level": LVL_BY_NAME},
            _space("SP1", level=LVL_BY_NAME),
        ]), revit_version="2024", snapshot=SNAPSHOT, bulk=True)
        self.assertTrue(out.ok, _codes(out)[:3])
        regen = out.csharp.find("finalize wall enclosures")
        self.assertGreater(regen, 0)
        self.assertLess(regen, out.csharp.find("// create_space"))


# ── приёмка ──────────────────────────────────────────────────────────────────

class AcceptanceKnowsTheOp(unittest.TestCase):
    """Оп, чью категорию приёмка не знает, ОТКЛОНЯЕТ честную постройку
    (`category_shortfall`). Слепота обязана быть замером, а не осторожностью
    — здесь замер есть: 169 пространств корпуса прочитаны извлечением ИМЕННО
    как OST_MEPSpaces, `expected == extracted`, `state: complete`."""

    def test_the_result_category_is_named_exactly(self):
        self.assertEqual(spec.op_result_categories({"op": OP}),
                         ("OST_MEPSpaces",))

    def test_the_op_is_not_blind_and_not_element_free(self):
        from kukai.ir import acceptance
        self.assertNotIn(OP, acceptance._OPS_BLIND)
        self.assertNotIn(OP, acceptance._OPS_WITHOUT_ELEMENTS)

    def test_the_expectation_is_one_exact_row_at_the_resolved_level(self):
        from kukai.ir.acceptance import Certainty, derive_expectation
        program = _prog([_space("SP1", level=LVL_BY_NAME),
                         _space("SP2", xy=[9000, 9000], level=LVL_BY_NAME)])
        self.assertTrue(compile_program(program, revit_version="2024",
                                        snapshot=SNAPSHOT, bulk=True).ok)
        rows = [r for r in derive_expectation(program).rows
                if r.categories == ("OST_MEPSpaces",)]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].count, 2)
        self.assertEqual(rows[0].level, SNAPSHOT["levels"][0]["name"])
        self.assertIs(rows[0].certainty, Certainty.EXACT)

    def test_the_level_is_taken_from_the_selector_by_construction(self):
        """Уровень уезжает В САМ ВЫЗОВ `NewSpace(Level, UV)`, то есть равен
        разрешённому селектору по построению, а не по совпадению."""
        from kukai.ir import acceptance
        self.assertIn(OP, acceptance._LEVEL_FROM_PARAM)


# ── обратный ход и долг живого прогона ───────────────────────────────────────

class ReverseAndDebt(unittest.TestCase):

    def test_the_reverse_contract_names_the_lifter_not_the_capture(self):
        """LIFTER_GAP, а не CAPTURE_GAP: «пробел захвата» послал бы
        следующего чинить чтение, которое уже работает (44 разбора из 76
        смотрели категорию, 6 нашли элементы, все с state=complete)."""
        from kukai.ir.reverse_contract import (
            REVERSE_CONTRACTS, ReverseGuarantee, ReverseMode)
        contract = REVERSE_CONTRACTS[OP]
        self.assertIs(contract.mode, ReverseMode.LIFTER_GAP)
        self.assertIs(contract.guarantee, ReverseGuarantee.NONE)
        self.assertIn("L0:OST_MEPSpaces", contract.sources)

    def test_the_op_is_named_in_the_unproven_ledger(self):
        """Корпус свидетелей закрыт 04.08, оп заведён 10.08 — живых строк нет
        ПО ПОСТРОЕНИЮ. Молчащее множество обязано остаться пустым: модели
        никогда не говорят, что непроверенный оп проверен."""
        from kukai.ir.tool_doc import UNPROVEN
        self.assertIn(OP, UNPROVEN)
        self.assertTrue(UNPROVEN.reason(OP).strip())


# ── свойство ─────────────────────────────────────────────────────────────────

class SpacePBT(unittest.TestCase):

    def test_well_typed_spaces_always_compile_on_every_version(self):
        import random
        rng = random.Random(20260810)
        for i in range(12):
            xy = [rng.randint(-50_000, 50_000), rng.randint(-50_000, 50_000)]
            for ver in spec.REVIT_VERSIONS:
                with self.subTest(i=i, version=ver):
                    out = compile_program(_prog([_space(xy=xy)]),
                                          revit_version=ver,
                                          snapshot=SNAPSHOT)
                    self.assertTrue(out.ok, _codes(out)[:3])


if __name__ == "__main__":
    unittest.main()