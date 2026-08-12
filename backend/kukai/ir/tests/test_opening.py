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

from kukai.ir import contour as contour_mod                        # noqa: E402
from kukai.ir import spec                                          # noqa: E402
from kukai.ir.compiler import compile_program                      # noqa: E402
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT as SNAPSHOT    # noqa: E402

HOST = {"by": "element_id", "value": 8145901}

#: Прямоугольник 2x2 м — площадь заведомо выше вырожденного порога `pts`.
SQUARE = [[1000, 1000], [3000, 1000], [3000, 3000], [1000, 3000]]

#: Тот же прямоугольник, сказанный на языке эскиза.
SQUARE_REGION = {"outer": {"shape": "rect", "origin": [1000, 1000],
                           "size_mm": [2000, 2000]}}

#: И он же с ОДНОЙ закруглённой стороной — ровно то, чего ломаная сказать не
#: может вовсе: под `outline` дуга становится хордой, то есть ДРУГИМ проёмом.
ARC_REGION = {"outer": {"shape": "poly", "points_mm": SQUARE,
                        "arcs": [{"edge": 1, "bulge": 0.4}]}}


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


def _sketch(oid="O1", contour=None, **kw):
    """Проём ВТОРЫМ входом формы: эскиз вместо ломаной.

    Отдельный конструктор, а не `_host_face(contour=...)`, и это не стиль: у
    `_host_face` ломаная зашита, а два входа сразу — типизированный отказ
    KIR-P007. Фикстура, дающая оба поля, проверяла бы отказ, думая, что
    проверяет постройку."""
    op = {"op": "create_opening", "id": oid, "variety": "host_face",
          "host": dict(HOST),
          "contour": SQUARE_REGION if contour is None else contour,
          "cut": "vertical"}
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
        tolerances = spec_mod.OPS["create_opening"].tolerances
        before = self._cs(_host_face())
        key = "bbox_mm"
        original = tolerances[key]
        tolerances[key] = original * 1000.0 + 7.77
        try:
            after = self._cs(_host_face())
        finally:
            tolerances[key] = original
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


# ── 4b. Проём по эскизу CONTOUR (09.08.2026) ────────────────────────────────

class OpeningContour(unittest.TestCase):
    """У `variety="host_face"` появился ВТОРОЙ вход профиля — `contour`.

    Почему параллельный, а не замена: прямые точки — это то, чем говорит
    materialize, и отнимать их у обратной стороны нельзя даже пока она у
    проёма молчит (`CAPTURE_GAP`). Почему вообще: круглый вырез под стояк и
    закруглённый край ломаной невыразимы — она даёт ДРУГУЮ форму, а не
    приближение (в карте отказов это 27 элементов, «polygon ops cannot
    represent an arc profile»).
    """

    def _cs(self, op, ver="2024"):
        out = compile_program(_prog([op]), revit_version=ver,
                              snapshot=SNAPSHOT)
        self.assertTrue(out.ok, _codes(out)[:3])
        return out.csharp

    def test_a_sketch_opening_builds_on_all_six(self):
        """ОСИ ВЕРСИЙ У ЭСКИЗА НЕТ, и это ЗАМЕР по эталонным сборкам, а не
        память: NewOpening(Element, CurveArray, bool), Arc.Create(XYZ,XYZ,XYZ),
        Line.CreateBound, CurveArray.Append, Curve.Evaluate, Curve.GetEndPoint,
        Curve.IsBound — все 6/6. Отказ по версии, которого API не требует, —
        такая же ложь, как молчание там, где отказ нужен."""
        for ver in spec.REVIT_VERSIONS:
            with self.subTest(version=ver):
                cs = self._cs(_sketch(contour=ARC_REGION), ver)
                self.assertIn("NewOpening(", cs)
                self.assertIn("Arc.Create", cs)

    def test_the_straight_outline_could_not_say_this_at_all(self):
        """ОПРОВЕРЖЕНИЕ ПЕРВЫМ: до этой волны закруглённую сторону проёма
        выразить было НЕЧЕМ, и «приближением ломаной» это не было.

        Автор, написавший те же четыре точки в `outline`, получал ЧЕТЫРЕ
        отрезка и молчание — то есть другой проём, неотличимый снаружи от
        запрошенного. Здесь это зафиксировано как ФАКТ ОБ ЭМИССИИ: у прямой
        ветки ни одной дуги нет и не появляется."""
        straight = self._cs(_host_face(outline=SQUARE))
        self.assertNotIn("Arc.Create", straight)
        self.assertEqual(straight.count("__ca_O1.Append("), 4)
        curved = self._cs(_sketch(contour=ARC_REGION))
        self.assertIn("Arc.Create", curved)
        # И габарит у них РАЗНЫЙ — то есть это две разные формы, а не одна с
        # погрешностью: стрелка дуги выносит границу за вершины на 400 мм при
        # допуске 50 мм.
        edges = contour_mod.validate_region(
            ARC_REGION, [], "O1", "contour", [])["outer"]
        bulged = contour_mod.edges_bbox(edges)[2] - max(p[0] for p in SQUARE)
        self.assertGreater(bulged,
                           spec.OPS["create_opening"].tolerances["bbox_mm"])

    def test_an_arc_edge_becomes_an_arc_not_a_chord(self):
        """Повод волны: под `outline` дуга схлопывается в хорду. Дуга обязана
        доехать до C# как Arc.Create с ТРЕМЯ литеральными точками — вся
        тригонометрия посчитана в питоне на стадии ground."""
        cs = self._cs(_sketch(contour=ARC_REGION))
        self.assertEqual(cs.count("Arc.Create"), 1)
        self.assertEqual(cs.count("__ca_O1.Append(Line.CreateBound"), 3)

    def test_the_profile_still_sits_on_the_host_plane_not_at_zero(self):
        """Отметку профиля даёт НОСИТЕЛЬ, а не ноль.

        ЕДИНИЦЫ ПОМЕНЯЛИСЬ ПРИ СЛИЯНИИ 09.08.2026, инвариант — нет. До него
        отметка ехала во ВНУТРЕННИХ единицах и точка собиралась
        `new XYZ(U(x), U(y), __z_O1)` в обход `P`. Теперь обе ветки этого опа
        сидят на общем сборщике рёбер `contour._edge_curve_cs`, у которого
        конвенция ОДНА и миллиметровая, как во всём языке, — поэтому `MM(...)`
        стоит у источника, а точка снова обычная `P(x, y, z)`.

        Утверждение осталось ДВУСТОРОННИМ нарочно: ноль в отметке — это тихая
        неправда (профиль 17-го этажа не пересёк бы носителя), а `MM` без
        `U` или `U` без `MM` дали бы промах примерно в 304.8 раза, который
        компилируется одинаково на всех шести версиях и виден только живьём.
        """
        cs = self._cs(_sketch())
        self.assertIn(
            "double __z_O1 = MM((__hbb_O1.Min.Z + __hbb_O1.Max.Z) / 2.0)", cs)
        self.assertIn("P(1000.0, 1000.0, __z_O1)", cs)
        self.assertNotIn("__ca_O1.Append(Line.CreateBound(new XYZ(", cs)
        self.assertNotIn("double __z_O1 = (__hbb_O1", cs)

    def test_the_witness_knows_where_the_arc_bulges(self):
        """СВИДЕТЕЛЬ ЧИТАЕТ РЕЗУЛЬТАТ, И ВЕРХНЮЮ ГРАНИЦУ ОБЯЗАН ЗНАТЬ ПО
        ДУГЕ. У дуги крайняя точка почти никогда не вершина: стрелка выходит
        за габарит ломаной, и сверять по вершинам значило бы обвинять
        правильно построенный проём ровно на ту дугу, ради которой эскиз и
        взят."""
        edges = contour_mod.validate_region(
            ARC_REGION, [], "O1", "contour", [])["outer"]
        x0, y0, x1, y1 = contour_mod.edges_bbox(edges)
        self.assertGreater(x1, 3000.0)          # дуга ВЫШЛА за вершины
        cs = self._cs(_sketch(contour=ARC_REGION))
        self.assertIn(f"__ox1_O1 > {round(x1, 1)} + ", cs)

    def test_the_lower_bound_is_the_vertices_because_they_are_read_exactly(self):
        """НИЖНЯЯ граница полосы — ВЕРШИНЫ, и это не осторожность, а предел
        того, что API обещает: конец кривой `GetEndPoint` отдаёт точно, а
        экстремум дуги достаётся только конечной выборкой по `Evaluate`,
        плотности которой документация не обещает. Потребовать снизу
        `edges_bbox` значило бы назначить допуск на плотность выборки — то
        есть выдумать число."""
        edges = contour_mod.validate_region(
            ARC_REGION, [], "O1", "contour", [])["outer"]
        vx1 = contour_mod.edges_vertex_bbox(edges)[2]
        ex1 = contour_mod.edges_bbox(edges)[2]
        self.assertLess(vx1, ex1)               # полоса непуста именно тут
        cs = self._cs(_sketch(contour=ARC_REGION))
        self.assertIn(f"__ox1_O1 < {round(vx1, 1)} - ", cs)

    def test_a_straight_sketch_collapses_the_band_into_equality(self):
        """У профиля БЕЗ ДУГ обе границы полосы совпадают, то есть контурная
        ветка не «слабее» прямой — она обобщает её и совпадает с ней там, где
        прямая права."""
        edges = contour_mod.validate_region(
            SQUARE_REGION, [], "O1", "contour", [])["outer"]
        self.assertEqual(contour_mod.edges_bbox(edges),
                         contour_mod.edges_vertex_bbox(edges))

    def test_the_boundary_is_sampled_only_when_there_is_an_arc(self):
        """Выборка эмитируется РОВНО там, где добавляет факт. У прямых звеньев
        концы и есть экстремумы, лишние точки не сказали бы ничего — зато
        развели бы эмиссию двух эквивалентных профилей."""
        straight = self._cs(_sketch())
        curved = self._cs(_sketch(contour=ARC_REGION))
        self.assertNotIn("Evaluate", straight)
        self.assertIn("__c_O1.GetEndPoint(__k_O1)", straight)
        self.assertIn("__c_O1.Evaluate(__k_O1 / 8.0, true)", curved)
        self.assertIn("if (!__c_O1.IsBound) continue;", curved)

    def test_the_sampling_density_is_the_canon_one_not_a_new_number(self):
        """«Во сколько точек мы смотрим на дугу» обязан быть ОДИН ответ на
        весь компилятор: то же число, которым канон разворачивает дугу в
        своих статических законах."""
        cs = self._cs(_sketch(contour=ARC_REGION))
        self.assertIn(f"__k_O1 <= {contour_mod.ARC_SAMPLES};", cs)

    def test_the_tolerance_is_the_registered_one_not_a_new_number(self):
        """Новое число здесь было бы границей, назначенной рассуждением, —
        классом дефекта этого дома. Обе ветки формы читают ОДИН ключ."""
        tol = spec.OPS["create_opening"].tolerances["bbox_mm"]
        self.assertIn(f"> {tol}", self._cs(_host_face()))
        self.assertIn(f"+ {tol}", self._cs(_sketch(contour=ARC_REGION)))

    def test_a_grid_anchored_profile_resolves_through_relate(self):
        """CONTOUR — потребитель адресной грамматики RELATE, и проёму она
        достаётся вместе с полем, а не отдельной работой."""
        cs = self._cs(_sketch(contour={"outer": {
            "shape": "rect",
            "origin": {"at_grid": ["1", "А"], "offset_mm": [200, 200]},
            "size_mm": [1800, 1600]}}))
        # Написание точки поменялось при слиянии 09.08 (см. соседний тест про
        # плоскость носителя): общая конвенция сборщика рёбер — миллиметры,
        # поэтому снова `P`, а не `new XYZ(U(...), ...)`. Разрешённый адрес
        # от осей это не затрагивает — он и был в миллиметрах.
        self.assertIn("P(200.0, 200.0, __z_O1)", cs)

    def test_the_perpendicular_cut_keeps_only_the_lower_bound(self):
        """На скате план перпендикулярного реза ЗАКОННО шире профиля, поэтому
        верхней границы у него нет — её отсутствие названо, а не забыто."""
        cs = self._cs(_sketch(contour=ARC_REGION, cut="perpendicular"))
        self.assertIn("opening extents do not cover the contour (geometry)",
                      cs)
        self.assertNotIn("leave the contour band", cs)


class TheCutWitnessPromisesOnlyWhatItCanRead(unittest.TestCase):
    """ЧТО СВИДЕТЕЛЬ РЕЗА МОЖЕТ И ЧЕГО НЕ МОЖЕТ — названо, а не умолчано.

    Проём это ПУСТОТА: у него нет тела, `get_BoundingBox` документация ему не
    обещает, и потому свидетель здесь СЛАБЕЕ, чем у потолка или плиты, где
    сверяется габарит самого элемента. Обещать больше, чем API отдаёт, —
    ровно тот дефект, из-за которого откатывались верные балки."""

    def test_the_promise_names_both_shape_inputs(self):
        post = spec.OPS["create_opening"].post
        self.assertIn("with outline", post)
        self.assertIn("with contour", post)

    def test_the_promise_names_what_is_deliberately_unwitnessed(self):
        """Названный остаток — часть обещания, а не примечание: стрелка дуги
        внутри полосы и глубина реза не проверяются НИЧЕМ."""
        post = spec.OPS["create_opening"].post
        self.assertIn("unwitnessed", post)
        self.assertIn("sagitta", post)
        self.assertIn("depth of the cut", post)

    def test_no_witness_claims_the_host_was_actually_cut(self):
        """«Материал убран» офлайн не утверждается вовсе: подтвердить это
        можно только объёмом тела носителя до и после, то есть живым Revit.
        Здесь проверяется, что такого обещания в C# НЕТ."""
        out = compile_program(_prog([_sketch()]), revit_version="2024",
                              snapshot=SNAPSHOT)
        self.assertTrue(out.ok, _codes(out)[:3])
        self.assertNotIn("__el_O1.get_BoundingBox", out.csharp)
        self.assertNotIn("Volume", out.csharp)

    def test_the_certificate_proves_the_sketch_branch_on_all_six(self):
        from kukai.ir import ground as ground_mod
        from kukai.ir.compiler import _parse_and_check
        from kukai.ir.translation_cert import certify_op
        grounded = ground_mod.ground(
            _parse_and_check(_prog([_sketch(contour=ARC_REGION)])),
            SNAPSHOT)[0]
        for ver in spec.REVIT_VERSIONS:
            with self.subTest(version=ver):
                self.assertTrue(certify_op(grounded, ver).proven)

    def test_the_two_shape_inputs_carry_different_obligation_keys(self):
        """Условное обязательство разряжается ровно ОТСУТСТВИЕМ своего
        свидетеля, поэтому общий ключ на две взаимоисключающие ветви объявил
        бы витнес соседней ветви «лишним» на каждой программе."""
        from kukai.ir.opening_emit import emit_opening
        straight = emit_opening(_host_face(), "2024", "kir:test")[2]
        sketch_op = _sketch()
        sketch_op["__region__"] = contour_mod.validate_region(
            SQUARE_REGION, [], "O1", "contour", [])
        sketch = emit_opening(sketch_op, "2024", "kir:test")[2]
        self.assertIn("bbox", [c.obligation_key for c in straight])
        self.assertIn("bbox_contour", [c.obligation_key for c in sketch])


class OpeningShapeIsSaidExactlyOnce(unittest.TestCase):
    """ВЗАИМНАЯ ОБЯЗАТЕЛЬНОСТЬ, ровно как у place_family (xyz vs p0_mm/p1_mm),
    но у операции с развилкой `variety` она РАСЩЕПЛЕНА, и это решение:

      * «оба сразу» неоднозначны ВСЕГДА -> отказывает план (KIR-P007);
      * «ни одного» знает только РОД: у wall_rect формы нет вообще, он
        задаётся двумя углами, поэтому общий отказ «форма не задана» обвинял
        бы верную программу. Нижняя половина живёт в ветке рода (KIR-P005).
    """

    def test_both_shapes_at_once_are_refused_naming_both_fields(self):
        out = compile_program(_prog([_host_face(contour=SQUARE_REGION)]),
                              snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-P007", _codes(out))
        self.assertIn("outline", _messages(out))
        self.assertIn("contour", _messages(out))

    def test_no_shape_at_all_is_refused_naming_both_fields(self):
        op = _host_face()
        del op["outline"]
        out = compile_program(_prog([op]), snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-P005", _codes(out))
        self.assertIn("outline", _messages(out))
        self.assertIn("contour", _messages(out))

    def test_the_wall_rect_variety_is_not_accused_of_a_missing_shape(self):
        """ОПРОВЕРГАЮЩИЙ ТЕСТ ЗА ОБОБЩЁННОЕ ПРАВИЛО: у прямоугольного проёма
        в стене нет ни `outline`, ни `contour`, и это ПРАВИЛЬНАЯ программа.
        Правило «ровно одно из двух», написанное без оглядки на развилку
        рода, завернуло бы её."""
        out = compile_program(_prog([_wall_rect()]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, _codes(out)[:3])

    def test_a_sketch_is_refused_on_the_variety_that_cannot_use_it(self):
        """Молча выбросить эскиз нельзя: `NewOpening(Wall, XYZ, XYZ)` профиля
        не принимает вовсе, и принять поле, на которое никто не посмотрит,
        значило бы построить прямоугольник там, где автор написал дугу."""
        out = compile_program(_prog([_wall_rect(contour=SQUARE_REGION)]),
                              snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-P007", _codes(out))
        self.assertIn("host_face", _messages(out))

    def test_a_broken_sketch_is_not_re_told_as_a_missing_shape(self):
        """Поле, о котором уже сказано конкретнее, не пересказывается вторым,
        более общим голосом."""
        out = compile_program(
            _prog([_sketch(contour={"outer": {"shape": "rect",
                                              "origin": [0, 0],
                                              "size_mm": [1, 1]}})]),
            snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertNotIn("KIR-P005", _codes(out))

    def test_the_straight_outline_branch_is_untouched(self):
        """Байтовая стабильность прежних программ: без `contour` эмиссия та
        же ломаная и тот же обход концов, что и была (настоящий страж этого
        утверждения — golden/opening_host_face_*.golden.cs)."""
        out = compile_program(_prog([_host_face()]), revit_version="2024",
                              snapshot=SNAPSHOT)
        self.assertTrue(out.ok, _codes(out)[:3])
        self.assertNotIn("Arc.Create", out.csharp)
        self.assertNotIn("Evaluate", out.csharp)
        self.assertEqual(out.csharp.count("__ca_O1.Append(Line.CreateBound"), 4)


class AHoleInsideAnOpeningIsRefusedNotDropped(unittest.TestCase):
    """У эскиза отверстий до 8, а у проёма профиль РОВНО ОДИН.

    `NewOpening(Element, CurveArray, bool)` принимает один `CurveArray`
    («Profile of the opening», единственное число), а не список петель, как
    `Floor.Create`/`Ceiling.Create`. Дописать вторую петлю в тот же массив —
    самопересекающийся профиль; молча выбросить — потеря написанного."""

    HOLED = {"outer": {"shape": "rect", "origin": [1000, 1000],
                       "size_mm": [4000, 4000]},
             "holes": [{"shape": "rect", "origin": [2000, 2000],
                        "size_mm": [1000, 1000]}]}

    def test_it_is_a_typed_refusal(self):
        out = compile_program(_prog([_sketch(contour=self.HOLED)]),
                              snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        from kukai.ir.diag import EMIT_CONTOUR_HOLES
        self.assertIn(EMIT_CONTOUR_HOLES, _codes(out))

    def test_the_reason_comes_from_the_one_table_not_retyped(self):
        """Три отдельно набранных текста одного факта разъезжаются — этот дом
        уже платил за такое парностью категорий 29.07."""
        from kukai.ir.ops_opening import CONTOUR_HOLES_NOT_EXPRESSIBLE
        out = compile_program(_prog([_sketch(contour=self.HOLED)]),
                              snapshot=SNAPSHOT)
        self.assertIn(CONTOUR_HOLES_NOT_EXPRESSIBLE, _messages(out))

    def test_it_is_not_confused_with_an_unsupported_variety(self):
        """«Нет такого рода проёма» и «у взятого рода нет такой формы» —
        разные ремонты, значит разные коды."""
        from kukai.ir.diag import (
            EMIT_CONTOUR_HOLES, EMIT_UNSUPPORTED_ENUM)
        self.assertNotEqual(EMIT_CONTOUR_HOLES, EMIT_UNSUPPORTED_ENUM)

    def test_a_region_without_holes_is_untouched(self):
        out = compile_program(_prog([_sketch()]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, _codes(out)[:3])


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
        for variety, entry in VARIETIES_NOT_TAKEN.items():
            with self.subTest(variety=variety):
                self.assertGreater(len(entry.reason), 60,
                                   "причина обязана быть причиной, а не меткой")

    def test_the_emitter_refusal_names_the_variety_and_its_reason(self):
        """«Не поддержано» БЕЗ ПРИЧИНЫ неотличимо от «забыли».

        Ремень поверх подтяжек эмиттера — единственное место, где невзятый род
        произносится вслух вместе с причиной. Проверяется, что произносится
        ИМЕННО ПРИЧИНА ИЗ ОДНОЙ ТАБЛИЦЫ, а не набранный заново текст: три
        разных формулировки одного факта расходятся, и этот дом уже платил за
        такое парностью категорий 29.07."""
        from kukai.ir.diag import KirRefusal
        from kukai.ir.diag import EMIT_UNSUPPORTED_ENUM
        from kukai.ir.opening_emit import emit_opening
        from kukai.ir.ops_opening import VARIETIES_NOT_TAKEN
        for variety, entry in VARIETIES_NOT_TAKEN.items():
            why = entry.reason
            with self.subTest(variety=variety):
                with self.assertRaises(KirRefusal) as caught:
                    emit_opening({"op": "create_opening", "id": "O1",
                                  "variety": variety}, "2024", "kir:test")
                diag = caught.exception.diagnostics[0]
                self.assertEqual(diag.code, EMIT_UNSUPPORTED_ENUM)
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

    def test_well_typed_sketch_openings_always_compile(self):
        """Тот же закон для второго входа формы: хорошо типизированный эскиз
        обязан доезжать до C# всегда, включая дуговые рёбра, и на 2021 тоже —
        оси версий у эскиза нет."""
        rng = random.Random(9082028)
        for i in range(40):
            x0 = rng.randrange(-40000, 40000)
            y0 = rng.randrange(-40000, 40000)
            w = rng.randrange(500, 9000)
            h = rng.randrange(500, 9000)
            points = [[x0, y0], [x0 + w, y0], [x0 + w, y0 + h], [x0, y0 + h]]
            region = {"outer": {"shape": "poly", "points_mm": points}}
            if rng.random() < 0.5:
                # Дуга НАРУЖУ по короткому ребру: outward-стрелка не может
                # пересечь противоположную сторону, поэтому программа
                # остаётся хорошо типизированной по построению.
                edge, bulge = (0, -0.3) if w <= h else (1, 0.3)
                region["outer"]["arcs"] = [{"edge": edge, "bulge": bulge}]
            op = _sketch(oid=f"O{i}", contour=region,
                         cut=rng.choice(("vertical", "perpendicular")))
            with self.subTest(i=i):
                out = compile_program(_prog([op]),
                                      revit_version=rng.choice(
                                          list(spec.REVIT_VERSIONS)),
                                      snapshot=SNAPSHOT)
                self.assertTrue(out.ok, _codes(out)[:3])


if __name__ == "__main__":
    unittest.main()
