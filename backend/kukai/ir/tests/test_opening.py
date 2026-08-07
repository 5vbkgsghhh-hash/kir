"""wave/opening (2026-08-03): create_opening — проём КАК ОТДЕЛЬНЫЙ ЭЛЕМЕНТ.

ПОВОД — ЗАМЕР, А НЕ ИДЕЯ. Обход восьми настоящих зданий нашёл РОВНО ОДНУ
молчаливую потерю во всём конвейере, и это она. Проём в Revit делается ДВУМЯ
разными механизмами:

  * внутренней петлёй эскиза носителя — ЭТО МЫ УМЕЕМ (60 `create_floor` с
    непустым `holes` в трёх зданиях);
  * ОТДЕЛЬНЫМ элементом `Opening` — этого не было ни в одном виде: грепом по
    всем `.py`/`.cs` ноль упоминаний `OST_ShaftOpening`, `OST_SWallRectOpening`,
    `OST_FloorOpening`, `OST_RoofOpening`, `Opening`, `NewOpening`.

Перепись: 35 элементов в 3 из 6 зданий — OST_FloorOpening 10,
OST_ShaftOpening 9, OST_SWallRectOpening 9, OST_RoofOpening 7.

ПОЧЕМУ ЭТО ХУДШИЙ КЛАСС ДЕФЕКТА, А НЕ «ещё одна непокрытая категория».
Элемент не извлекается ⇒ атома НЕ ДАЁТ ⇒ в карте причин его нет. При этом
НОСИТЕЛЬ поднимается обычным `create_floor`/`create_wall` и пересобирается
СПЛОШНЫМ. Приёмка этого не поймает: `acceptance.py` говорит прямым текстом,
что ГЕОМЕТРИЮ НЕ СМОТРИТ ВООБЩЕ. То есть снаружи тихо неверный результат
неотличим от успеха — ровно та форма ошибки, ради запрета которой существует
весь этот компилятор.

ОПРОВЕРГАЮЩИЙ ТЕСТ ПЕРВЫМ. Классы ниже сначала фиксируют ОТСУТСТВИЕ (реестр
не знает операции, чтение не знает категорий), потом требуют присутствия —
чтобы «мы это починили» было проверяемым утверждением, а не рассказом.

ЗАМЕР API (индекс ловушек `data/api_traps/revit_api_traps.sqlite`, таблицы
`member`/`prose`, плюс сверка с эталонными XML шести пакетов):

    Creation.Document.NewOpening(Element, CurveArray, eRefFace)     6/6
    Creation.Document.NewOpening(Element, CurveArray, bool)         6/6
    Creation.Document.NewOpening(Level, Level, CurveArray)          6/6
    Creation.Document.NewOpening(Wall, XYZ, XYZ)                    6/6
    Opening.Host / .BoundaryRect / .IsRectBoundary / .BoundaryCurves 6/6
    Opening.SketchId                                          2022-2026 (5/6)

Замечание спеки, взятое дословно: «Slanted stacked walls do not support
rectangular openings» — то есть отказ Revit на наклонной/многослойной стене
это ЗАКОННЫЙ исход, а не наш дефект; он обязан прийти громко.
"""
import os
import random
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(),
                                   "kir_test_opening_queue.jsonl"))

from kukai.ir import spec                                          # noqa: E402
from kukai.ir.compiler import compile_program                      # noqa: E402
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT as SNAPSHOT    # noqa: E402

HOST = {"by": "element_id", "value": 8145901}

#: Прямоугольник 2x2 м — площадь заведомо выше вырожденного порога `pts`.
SQUARE = [[1000, 1000], [3000, 1000], [3000, 3000], [1000, 3000]]


def _prog(ops, intent="opening-test", **kw):
    out = {"ir_version": "1.0", "intent": intent, "ops": ops}
    out.update(kw)
    return out


def _wall_rect(oid="O1", **kw):
    op = {"op": "create_opening", "id": oid, "variety": "wall_rect",
          "host": dict(HOST),
          "p0_mm": [1000.0, 0.0, 900.0], "p1_mm": [2500.0, 0.0, 2400.0]}
    op.update(kw)
    return op


def _host_face(oid="O1", **kw):
    op = {"op": "create_opening", "id": oid, "variety": "host_face",
          "host": dict(HOST), "outline": SQUARE, "cut": "vertical"}
    op.update(kw)
    return op


def _codes(out):
    return [d.code for d in out.diagnostics]


def _messages(out):
    return " ".join(d.message_ru or "" for d in out.diagnostics)


# ── 1. ОПРОВЕРЖЕНИЕ: потеря БЫЛА молчаливой ─────────────────────────────────

class TheLossWasSilent(unittest.TestCase):
    """Форма дефекта, зафиксированная замером, — чтобы починка была
    проверяемой, а не декларативной.

    Эти утверждения ПРОВАЛИВАЛИСЬ до волны и обязаны держаться после неё."""

    def test_the_op_exists_at_all(self):
        self.assertIn(
            "create_opening", spec.OPS,
            "проём отдельным элементом не выражался НИ ОДНОЙ операцией "
            "реестра — 35 элементов на 3 зданиях уходили в никуда")

    def test_a_solid_host_is_no_longer_the_only_expressible_answer(self):
        """До волны единственным выражением проёма была петля в эскизе
        носителя (`create_floor.holes`). Проём в СУЩЕСТВУЮЩЕМ перекрытии,
        которое программа не создавала, выразить было нечем вовсе."""
        out = compile_program(_prog([_host_face()]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, _codes(out)[:3])
        self.assertIn("NewOpening", out.csharp)

    def test_the_reading_side_names_the_opening_categories(self):
        """Чтение обязано ЗНАТЬ эти категории поимённо: молчание хуже отказа.

        Проверяется не «есть лифтер», а «есть типизированный ответ»: категория
        обязана либо иметь кандидата подъёма, либо стоять в карте отказов с
        названной операцией."""
        from kukai.ir.decompile.lift import (
            _CANDIDATES, _OPS_WITHOUT_L0_INPUTS)
        known = set(_CANDIDATES) | set(_OPS_WITHOUT_L0_INPUTS)
        for category in ("OST_SWallRectOpening", "OST_FloorOpening",
                         "OST_RoofOpening"):
            with self.subTest(category=category):
                self.assertIn(
                    category, known,
                    "категория проёма обязана давать ЧЕСТНЫЙ АТОМ с "
                    "типизированной причиной, а не исчезать")


# ── 2. Реестр ───────────────────────────────────────────────────────────────

class RegistryShape(unittest.TestCase):

    def test_it_is_a_writer_of_the_authoring_family(self):
        op = spec.OPS["create_opening"]
        self.assertTrue(op.writes_model)
        self.assertEqual(op.family, "authoring")

    def test_it_grounds_nothing(self):
        """У проёма НЕТ типа: ни одна из четырёх перегрузок NewOpening типа не
        принимает. Значит и пула быть не должно — пул под операцию, которая им
        не пользуется, был бы обещанием без предъявителя."""
        self.assertEqual(spec.OPS["create_opening"].grounded, ())

    def test_the_variety_enum_is_closed_to_what_is_witnessed(self):
        variety = next(p for p in spec.OPS["create_opening"].params
                       if p.name == "variety")
        self.assertEqual(set(variety.choices), {"wall_rect", "host_face"})
        self.assertTrue(variety.required)

    def test_the_discriminator_is_named_variety_not_kind(self):
        """Слово «kind» реестр держит за словарём родов объектов Revit
        (SPEC 12.8), и test_invariants проверяет это ПО ИМЕНИ поля."""
        names = {p.name for p in spec.OPS["create_opening"].params}
        self.assertIn("variety", names)
        self.assertNotIn("kind", names)

    def test_the_promised_tolerance_lives_in_the_registry(self):
        self.assertIn("bbox_mm", spec.OPS["create_opening"].tolerances)


# ── 3. Ось версий: её нет, и это замер ──────────────────────────────────────

class VersionAxis(unittest.TestCase):
    """Все четыре перегрузки NewOpening живут на 2021-2026 (6/6). Оси версий
    у операции нет; если она когда-нибудь появится, этот тест увидит первым."""

    def test_wall_rect_builds_on_all_six(self):
        for ver in spec.REVIT_VERSIONS:
            with self.subTest(version=ver):
                out = compile_program(_prog([_wall_rect()]),
                                      revit_version=ver, snapshot=SNAPSHOT)
                self.assertTrue(out.ok, _codes(out)[:3])
                self.assertIn("NewOpening(", out.csharp)

    def test_host_face_builds_on_all_six(self):
        for ver in spec.REVIT_VERSIONS:
            with self.subTest(version=ver):
                out = compile_program(_prog([_host_face()]),
                                      revit_version=ver, snapshot=SNAPSHOT)
                self.assertTrue(out.ok, _codes(out)[:3])
                self.assertIn("NewOpening(", out.csharp)


# ── 4. Свидетель проверяет РЕЗУЛЬТАТ, а не эхо вызова ───────────────────────

class TheWitnessReadsTheResult(unittest.TestCase):
    """«Проём существует, принадлежит запрошенному хосту, габарит совпадает» —
    и каждое из трёх читается С ПОСТРОЕННОГО ЭЛЕМЕНТА."""

    def _cs(self, op, ver="2024"):
        out = compile_program(_prog([op]), revit_version=ver,
                              snapshot=SNAPSHOT)
        self.assertTrue(out.ok, _codes(out)[:3])
        return out.csharp

    def test_host_membership_is_read_from_the_created_opening(self):
        for name, op in (("wall_rect", _wall_rect()),
                         ("host_face", _host_face())):
            with self.subTest(variety=name):
                cs = self._cs(op)
                self.assertIn(".Host", cs)
                self.assertIn("__post.Add(", cs)

    def test_the_wall_rect_extent_is_read_from_boundary_rect(self):
        """Габарит прямоугольного проёма читается у САМОГО ПРОЁМА
        (Opening.BoundaryRect), а не пересчитывается из наших же аргументов."""
        cs = self._cs(_wall_rect())
        self.assertIn("BoundaryRect", cs)
        self.assertIn("IsRectBoundary", cs)

    def test_the_host_face_extent_is_read_from_the_bounding_box(self):
        cs = self._cs(_host_face())
        self.assertIn("get_BoundingBox(null)", cs)

    def test_every_tolerance_comes_from_the_registry(self):
        """ЗАКОН ПРОВЕНАНСА: число допуска попадает в C# только объектом
        emit_model.Tolerance. Тронь реестр — байты обязаны поехать."""
        from kukai.ir import spec as spec_mod
        from kukai.ir.tests.registry_variants import perturbed_tolerance
        tolerances = spec_mod.OPS["create_opening"].tolerances
        before = self._cs(_host_face())
        key = "bbox_mm"
        original = tolerances[key]
        with perturbed_tolerance(
                "create_opening", key, original * 1000.0 + 7.77):
            after = self._cs(_host_face())
        self.assertNotEqual(before, after,
                            "допуск объявлен, но эмиссия его не читает — "
                            "дефект create_type")

    def test_a_null_result_is_a_refusal_not_a_success(self):
        for name, op in (("wall_rect", _wall_rect()),
                         ("host_face", _host_face())):
            with self.subTest(variety=name):
                self.assertIn("== null", self._cs(op))

    def test_one_transaction_and_regenerate_before_the_verdict(self):
        for name, op in (("wall_rect", _wall_rect()),
                         ("host_face", _host_face())):
            with self.subTest(variety=name):
                cs = self._cs(op)
                self.assertEqual(cs.count("new Transaction("), 1)
                self.assertLess(cs.index("doc.Regenerate()"),
                                cs.index("__post.Add("))

    def test_the_creation_is_stamped(self):
        for name, op in (("wall_rect", _wall_rect()),
                         ("host_face", _host_face())):
            with self.subTest(variety=name):
                self.assertIn("__stamp", self._cs(op))


# ── 5. Отказы: названные, а не молчаливые ───────────────────────────────────

class NoSilentLoss(unittest.TestCase):

    def test_the_shaft_variety_is_refused_and_named(self):
        """ШАХТА НЕ ВЗЯТА, И ЭТО РЕШЕНИЕ, А НЕ ЗАБЫВЧИВОСТЬ: связь шахты с
        ПАРОЙ УРОВНЕЙ нечем прочитать с построенного элемента (у шахты нет
        хоста, а BuiltInParameter базового/верхнего ограничения не
        документирован ни в одном из шести пакетов). Свидетеля на «принадлежит
        запрошенному» не выходит, значит рода нет."""
        out = compile_program(_prog([_host_face(variety="shaft")]),
                              snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T001", _codes(out))

    def test_the_reason_for_every_variety_left_out_is_written_down(self):
        from kukai.ir.ops_opening import VARIETIES_NOT_TAKEN
        self.assertEqual(set(VARIETIES_NOT_TAKEN), {"shaft", "framing"})
        for variety, why in VARIETIES_NOT_TAKEN.items():
            with self.subTest(variety=variety):
                self.assertGreater(len(why), 60,
                                   "причина обязана быть причиной, а не меткой")

    def test_the_emitter_refusal_names_the_variety_and_its_reason(self):
        """«Не поддержано» БЕЗ ПРИЧИНЫ неотличимо от «забыли».

        Ремень поверх подтяжек эмиттера — единственное место, где невзятый род
        произносится вслух вместе с причиной. Проверяется, что произносится
        ИМЕННО ПРИЧИНА ИЗ ОДНОЙ ТАБЛИЦЫ, а не набранный заново текст: три
        разных формулировки одного факта расходятся, и этот дом уже платил за
        такое парностью категорий 29.07."""
        from kukai.ir.diag import KirRefusal
        from kukai.ir.opening_emit import (
            OPENING_UNSUPPORTED_VARIETY, emit_opening)
        from kukai.ir.ops_opening import VARIETIES_NOT_TAKEN
        for variety, why in VARIETIES_NOT_TAKEN.items():
            with self.subTest(variety=variety):
                with self.assertRaises(KirRefusal) as caught:
                    emit_opening({"op": "create_opening", "id": "O1",
                                  "variety": variety}, "2024", "kir:test")
                diag = caught.exception.diagnostics[0]
                self.assertEqual(diag.code, OPENING_UNSUPPORTED_VARIETY)
                self.assertIn(variety, diag.message_ru)
                self.assertIn(why, diag.message_ru)
                self.assertEqual(diag.candidates, ["wall_rect", "host_face"])

    def test_an_unknown_variety_is_typed(self):
        out = compile_program(_prog([_host_face(variety="skylight")]),
                              snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T001", _codes(out))

    def test_wall_rect_without_a_host_is_typed(self):
        op = _wall_rect()
        del op["host"]
        out = compile_program(_prog([op]), snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-P005", _codes(out))

    def test_wall_rect_without_corners_is_typed(self):
        op = _wall_rect()
        del op["p1_mm"]
        out = compile_program(_prog([op]), snapshot=SNAPSHOT)
        self.assertFalse(out.ok)

    def test_host_face_without_an_outline_is_typed(self):
        op = _host_face()
        del op["outline"]
        out = compile_program(_prog([op]), snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-P005", _codes(out))

    def test_host_face_without_a_named_cut_is_typed(self):
        """`cut` НЕ ИМЕЕТ УМОЛЧАНИЯ. Вертикальный и перпендикулярный рез
        совпадают только на плоском носителе; подставить один за автора
        значило бы на скате выдать другой проём и промолчать."""
        op = _host_face()
        del op["cut"]
        out = compile_program(_prog([op]), snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-P005", _codes(out))

    def test_the_corners_may_not_coincide(self):
        out = compile_program(
            _prog([_wall_rect(p1_mm=[1000.0, 0.0, 900.0])]), snapshot=SNAPSHOT)
        self.assertFalse(out.ok)

    def test_the_wall_rect_corners_are_three_dimensional(self):
        """Проём в стене — прямоугольник В ПЛОСКОСТИ СТЕНЫ, и его высота это
        Z. Двумерная точка молча уехала бы на отметку 0."""
        out = compile_program(_prog([_wall_rect(p0_mm=[1000.0, 0.0])]),
                              snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T001", _codes(out))

    def test_a_degenerate_outline_is_refused(self):
        out = compile_program(
            _prog([_host_face(outline=[[0, 0], [10, 0], [10, 10], [0, 10]])]),
            snapshot=SNAPSHOT)
        self.assertFalse(out.ok)

    def test_a_host_that_is_not_a_wall_is_refused_at_runtime_not_guessed(self):
        """`as Wall` + типизированный отказ: чужой id обязан упасть громко,
        а не построить проём «где-нибудь»."""
        out = compile_program(_prog([_wall_rect()]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, _codes(out)[:3])
        self.assertIn("as Wall", out.csharp)


# ── 6. Ссылка на носителя этой же программы ─────────────────────────────────

class HostMayBeEitherPinnedOrIntraProgram(unittest.TestCase):
    """Проём режут и в СУЩЕСТВУЮЩЕМ носителе («сделай проём в этой плите»), и
    в только что построенном. Оба пути обязаны работать — ровно как у
    create_railing, чей хозяин тоже бывает и чужим, и своим."""

    def test_a_ref_to_a_wall_of_the_same_program(self):
        out = compile_program(_prog([
            {"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
             "p1_mm": [6000, 0], "level": {"by": "element_id", "value": 42},
             "height_mm": 3000},
            _wall_rect(oid="O1", host={"by": "ref", "value": "W1"}),
        ]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, _codes(out)[:3])

    def test_a_ref_to_a_floor_of_the_same_program(self):
        out = compile_program(_prog([
            {"op": "create_floor", "id": "F1",
             "outline": [[0, 0], [8000, 0], [8000, 6000], [0, 6000]],
             "level": {"by": "element_id", "value": 42}},
            _host_face(oid="O1", host={"by": "ref", "value": "F1"}),
        ]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, _codes(out)[:3])

    def test_a_ref_to_something_that_was_never_created_is_refused(self):
        out = compile_program(_prog([
            _host_face(oid="O1", host={"by": "ref", "value": "NOPE"}),
        ]), snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-L003", _codes(out))


# ── 7. Приёмка знает, куда попадёт результат ────────────────────────────────

class AcceptanceKnowsTheCategory(unittest.TestCase):
    """Оп с НЕИЗВЕСТНОЙ категорией снимает верхние границы приёмки ЦЕЛИКОМ
    (acceptance.py). Проём обязан называть свою категорию, иначе одна новая
    операция ослабила бы L2 для всей программы."""

    def test_the_wall_rect_category_is_exact(self):
        from kukai.ir.acceptance import _category_of_op
        self.assertEqual(_category_of_op(_wall_rect()),
                         ("OST_SWallRectOpening",))

    def test_the_host_face_category_is_a_named_sum_not_none(self):
        from kukai.ir.acceptance import _category_of_op
        categories = _category_of_op(_host_face())
        self.assertIsNotNone(
            categories,
            "неизвестная категория снимает верхние границы всей программы")
        self.assertEqual(set(categories),
                         {"OST_FloorOpening", "OST_RoofOpening",
                          "OST_CeilingOpening"})


# ── 8. Обратный ход объявлен ────────────────────────────────────────────────

class TheReverseDirectionIsDeclared(unittest.TestCase):

    def test_the_manifest_covers_the_new_op(self):
        from kukai.ir.reverse_contract import REVERSE_CONTRACTS
        self.assertIn("create_opening", REVERSE_CONTRACTS)

    def test_it_does_not_claim_an_inverse_it_does_not_have(self):
        """L0 1.0 не несёт ни Opening.Host, ни границы проёма. Объявить DIRECT
        значило бы обещать подъём, которого нет."""
        from kukai.ir.reverse_contract import REVERSE_CONTRACTS, ReverseMode
        self.assertIs(REVERSE_CONTRACTS["create_opening"].mode,
                      ReverseMode.CAPTURE_GAP)


# ── 9. Свойство ─────────────────────────────────────────────────────────────

class OpeningPBT(unittest.TestCase):

    def test_well_typed_wall_openings_always_compile(self):
        rng = random.Random(3082026)
        for i in range(40):
            x0 = rng.randrange(-40000, 40000)
            z0 = rng.randrange(0, 2500)
            op = _wall_rect(
                oid=f"O{i}",
                p0_mm=[float(x0), 0.0, float(z0)],
                p1_mm=[float(x0 + rng.randrange(600, 4000)), 0.0,
                       float(z0 + rng.randrange(600, 2500))])
            with self.subTest(i=i):
                out = compile_program(_prog([op]), revit_version="2021",
                                      snapshot=SNAPSHOT)
                self.assertTrue(out.ok, _codes(out)[:3])

    def test_well_typed_host_face_openings_always_compile(self):
        rng = random.Random(3082027)
        for i in range(40):
            x0 = rng.randrange(-40000, 40000)
            y0 = rng.randrange(-40000, 40000)
            w = rng.randrange(500, 9000)
            h = rng.randrange(500, 9000)
            op = _host_face(
                oid=f"O{i}",
                outline=[[x0, y0], [x0 + w, y0], [x0 + w, y0 + h], [x0, y0 + h]],
                cut=rng.choice(("vertical", "perpendicular")))
            with self.subTest(i=i):
                out = compile_program(_prog([op]), revit_version="2026",
                                      snapshot=SNAPSHOT)
                self.assertTrue(out.ok, _codes(out)[:3])


if __name__ == "__main__":
    unittest.main()
