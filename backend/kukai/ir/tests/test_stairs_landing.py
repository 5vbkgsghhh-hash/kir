"""ПЛОЩАДКА ЛЕСТНИЦЫ ПО ЭСКИЗУ: законы, каждый из которых опровергающий.

ЧТО ЭТО ЗА ПРОБЕЛ.  До 10.08.2026 компилятор умел ровно ОДИН марш на
лестницу, то есть лестницу на один марш; промежуточной площадки — того, без
чего не строится ни одна настоящая многоэтажка, — на языке не было СКАЗАТЬ
НЕЧЕМ.  Перепись способностей нашла всё семейство площадок ни разу не
рассматривавшимся.

ПЯТЬ ЗАКОНОВ, КОТОРЫЕ ДЕРЖИТ ЭТОТ ФАЙЛ:

  1. ЗАКОН СОЛО-ОПА НЕ ОСЛАБЛЕН, А ОБОБЩЁН.  Площадке нужна ТА ЖЕ область
     правки, что маршу (RevitAPI.xml: «not in an active StairsEditScope»),
     поэтому она сама соло-оп — и цена площадки это ОТДЕЛЬНАЯ ПРОГРАММА, а не
     послабление правила.  Здесь же стоит страж на регрессию, которая уже
     была написана в первой редакции: отказ называл `create_stairs`
     ЛИТЕРАЛОМ, то есть обвинял чужую операцию.
  2. ЭСКИЗ — ЭТО CONTOUR, И ВТОРОГО СПОСОБА НЕТ.  Профиль идёт тем же родом
     `region`, что у перекрытия по контуру, заливки и балочной системы;
     дырка — типизированный отказ, потому что второго кольца в подписи нет.
  3. ДОПУСК ВЫВЕДЕН, А НЕ НАЗНАЧЕН.  Геометрический допуск —
     `VertexTolerance` самого документа плюс квант нашей эмиссии. Высота
     подступенка задаёт СЕТКУ допустимых отметок, а не широкий допуск:
     отклонение на один подступенок обязано провалить свидетель.
  4. СВИДЕТЕЛЬ ЧИТАЕТ РЕЗУЛЬТАТ И ПОДПИСЫВАЕТ ТОЛЬКО ПРОЧИТАННУЮ ОСЬ.
     Граница сверяется по ПЛАНУ; Z у прочитанных кривых ставит сам Revit
     («projected on the stairs base level»), и подписывать его мы не вправе.
  5. СВИДЕТЕЛЬ ОБЯЗАН УМЕТЬ ПРОВАЛИТЬСЯ.  Оракул — мутация: вырезание любого
     эмитируемого `__post.Add` обязано уронить `proven` сертификата.  Плюс
     рантайм-запрет вакуумности: допуск, съедающий половину самого короткого
     ребра, — названный отказ, а не подпись.

Прогон: venv/bin/python3.12 -m pytest kukai/ir/tests/test_stairs_landing.py -q
"""
from __future__ import annotations

import os
import re
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(),
                                   "kir_landing_queue.jsonl"))

from kukai.ir import authoring, contour as C, spec  # noqa: E402
from kukai.ir import reverse_contract as RC  # noqa: E402
from kukai.ir import translation_cert as TC  # noqa: E402
from kukai.ir import diag as D  # noqa: E402
from kukai.ir import stairs_landing_emit as SLE  # noqa: E402
from kukai.ir.acceptance import _OP_CATEGORIES, _OP_DERIVED  # noqa: E402
from kukai.ir.compiler import compile_program, plan_program  # noqa: E402
from kukai.ir.contracts import ElementIdentityProof  # noqa: E402
from kukai.ir.diag import KirRefusal  # noqa: E402
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT as SNAPSHOT  # noqa: E402

VERSIONS = ("2021", "2022", "2023", "2024", "2025", "2026")
OP = "create_stairs_landing"
STAIRS = {"by": "element_id", "value": 4242}
RECT = {"outer": {"shape": "rect", "origin": [5000.0, 0.0],
                  "size_mm": [2400.0, 1200.0]}}


def _op(**extra) -> dict:
    op = {"op": OP, "id": "LG1", "stairs": STAIRS, "contour": RECT,
          "elevation_mm": 1500.0}
    op.update(extra)
    return op


def _prog(*ops, intent: str = "площадка") -> dict:
    return {"ir_version": "1.0", "intent": intent, "ops": list(ops)}


def _compile(program: dict, ver: str = "2023", **kw):
    return compile_program(program, snapshot=SNAPSHOT, revit_version=ver,
                           bulk=True, **kw)


def _codes(out) -> list[str]:
    return [d.code for d in out.diagnostics]


def _cs(ver: str = "2023", **extra) -> str:
    out = _compile(_prog(_op(**extra)), ver)
    assert out.ok, _codes(out)
    return out.csharp


# ══════════════════════════════ 1. СОЛО-ОП: ЗАКОН ОБОБЩЁН, А НЕ ОСЛАБЛЕН

class TheSoloLawIsGeneralNotOneName(unittest.TestCase):

    def test_the_landing_is_declared_solo_in_the_registry(self) -> None:
        self.assertIn(OP, spec.SOLO_OPS)

    def test_a_neighbour_is_refused_at_PLAN_not_only_at_emit(self) -> None:
        """Живой Revit для этого правила не нужен: оно о ФОРМЕ программы, и
        обязано быть видно в песочнице, а не на устройстве."""
        with self.assertRaises(KirRefusal) as got:
            plan_program(_prog(
                _op(),
                {"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
                 "p1_mm": [6000, 0], "height_mm": 3000}))
        self.assertIn("KIR-L002", [d.code for d in got.exception.diagnostics])

    def test_the_refusal_names_the_op_that_is_actually_solo(self) -> None:
        """РЕГРЕССИЯ ПЕРВОЙ РЕДАКЦИИ.  Текст отказа `emit_program` называл
        `create_stairs` литералом; со вторым соло-опом он обвинял бы чужую
        операцию — прибор, врущий ровно на новой половине диапазона."""
        out = _compile(_prog(
            _op(),
            {"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
             "p1_mm": [6000, 0], "height_mm": 3000}))
        self.assertFalse(out.ok)
        text = " ".join(d.message_ru for d in out.diagnostics)
        self.assertIn(OP, text)

    def test_the_dsl_hint_offers_a_move_this_slot_actually_has(self) -> None:
        """ЗАМЕР 04.08 завёл этот помощник ровно потому, что КОРРЕКТНЫЙ отказ
        может вести в яму.  Совет «сошлись ПО ИМЕНИ» верен для уровня марша
        (`sel`), но у `stairs` род `target_w`, у которого формы `name` нет и
        быть не может — прежний текст посылал бы автора во второй отказ
        подряд."""
        from kukai.ir import dsl

        p = {q.name: q for q in spec.OPS[OP].params}["stairs"]
        stairs_spec = spec.OPS["create_stairs"]
        handle = dsl.Handle(id="S1", op="create_stairs", spec_=stairs_spec)
        move = dsl._by_name_next_move(spec.OPS[OP], p, handle)
        self.assertIn("element_id", move)
        self.assertNotIn('stairs="Этаж 1"', move)
        # ...и прежний совет остаётся дословно там, где он верен.
        lvl = {q.name: q for q in stairs_spec.params}["base_level"]
        self.assertIn('base_level="Этаж 1"',
                      dsl._by_name_next_move(stairs_spec, lvl, handle))

    def test_every_solo_op_has_its_own_whole_program_template(self) -> None:
        """Расхождение таблицы с реестром означало бы, что новый соло-оп
        МОЛЧА уезжает в чужой шаблон и получает чужую эмиссию."""
        self.assertEqual(set(authoring._SOLO_PROGRAMS), set(spec.SOLO_OPS))

    def test_the_certificate_reads_the_same_table(self) -> None:
        self.assertEqual(set(TC._EXTRA_CERTIFIABLE), set(spec.SOLO_OPS))

    def test_an_intra_program_ref_is_refused_at_parse(self) -> None:
        """У соло-опа предшественника нет ни одного, значит `by: ref`
        неразрешим ПО ПОСТРОЕНИЮ — и отказ обязан прийти на разборе."""
        out = _compile(_prog(_op(stairs={"by": "ref", "value": "S1"})))
        self.assertFalse(out.ok)
        text = " ".join(d.message_ru for d in out.diagnostics)
        self.assertIn("ref", text)


# ══════════════════════════════ 2. ЭСКИЗ — ЭТО CONTOUR

class TheSketchIsContourAndOnlyContour(unittest.TestCase):

    def test_the_profile_param_is_of_kind_region(self) -> None:
        kinds = {p.name: p.kind for p in spec.OPS[OP].params}
        self.assertEqual(kinds["contour"], "region")

    def test_holes_are_a_typed_refusal_not_a_silent_drop(self) -> None:
        """Молчаливое отбрасывание построило бы СПЛОШНУЮ площадку там, где
        просили с вырезом."""
        holed = {"outer": RECT["outer"],
                 "holes": [{"shape": "rect", "origin": [5600.0, 300.0],
                            "size_mm": [600.0, 600.0]}]}
        out = _compile(_prog(_op(contour=holed)))
        self.assertFalse(out.ok)
        self.assertIn(D.EMIT_CONTOUR_HOLES, _codes(out))

    def test_an_arc_edge_lowers_to_three_literal_points(self) -> None:
        """Канон CONTOUR, пункт 1: вся тригонометрия на КОМПИЛЯЦИИ, наружу
        уходят три литеральные точки на дугу."""
        arced = {"outer": {"shape": "poly",
                           "points_mm": [[5000.0, 0.0], [7400.0, 0.0],
                                         [7400.0, 1200.0], [5000.0, 1200.0]],
                           "arcs": [{"edge": 1, "bulge": 0.3}]}}
        cs = _cs(contour=arced)
        self.assertIn("Arc.Create(", cs)
        loop = cs.split("CurveLoop __ol_LG1", 1)[1].split(
            "CreateSketchedLanding", 1)[0]
        self.assertNotIn("Math.", loop)

    def test_the_loop_sits_on_the_stairs_base_elevation_not_zero(self) -> None:
        """Петля, оставленная на мировом нуле под лестницей на +3.000, либо
        отвергается, либо строит площадку не там — тот же шов, что у
        балочной системы."""
        cs = _cs()
        self.assertIn("double __sbz_LG1 = MM(__st_LG1.BaseElevation);", cs)
        loop = cs.split("CurveLoop __ol_LG1")[1].split("try")[0]
        self.assertIn("__sbz_LG1", loop)
        self.assertNotIn(", 0)", loop)


# ══════════════════════════════ 3. ДОПУСК ВЫВЕДЕН, А НЕ НАЗНАЧЕН

class EveryToleranceIsDerivedFromRevitsOwnNumbers(unittest.TestCase):

    def test_the_registry_declares_no_tolerance_at_all(self) -> None:
        """Оба допуска зависят от ЖИВОЙ модели и потому не могут быть
        реестровыми константами по построению."""
        self.assertEqual(spec.OPS[OP].tolerances, {})

    def test_the_boundary_tolerance_is_vertex_tolerance_plus_the_quantum(self) -> None:
        cs = _cs()
        self.assertIn(
            f"double __dt_LG1 = MM(doc.Application.VertexTolerance) + "
            f"{C.EMIT_COORD_QUANTUM_MM!r};", cs)

    def test_no_bare_literal_stands_in_the_boundary_comparison(self) -> None:
        """Голый литерал в сравнении — та самая треть границ, которую
        `bounds_audit` не может найти поиском констант."""
        block = _cs().split("foreach (Curve __bc_LG1")[1].split(
            "if (!__bRead_LG1)")[0]
        for cmp_line in re.findall(r"Math\.Abs\([^)]*\)\s*<=\s*([^\s&|);]+)",
                                   block):
            self.assertEqual(cmp_line, "__dt_LG1")
        self.assertTrue(
            re.search(r"Math\.Abs\([^)]*\)\s*<=\s*__dt_LG1", block))

    def test_elevation_is_normalized_before_the_call_and_witnessed_strictly(self) -> None:
        """Скрытую сторону Revit-округления не угадываем: автор обязан назвать
        уже кратное значение, фабрика получает вычисленное кратное, а
        свидетель использует малый геометрический допуск."""
        cs = _cs()
        self.assertIn("double __rh_LG1 = MM(__st_LG1.ActualRiserHeight);", cs)
        self.assertIn("double __elevNorm_LG1 = __elevK_LG1 * __rh_LG1;", cs)
        self.assertIn("Math.Abs(1500.0 - __elevNorm_LG1) > __dt_LG1", cs)
        self.assertIn("U(__elevNorm_LG1)", cs)
        self.assertIn(
            "Math.Abs(__gotE_LG1 - __elevNorm_LG1) > __dt_LG1", cs)
        self.assertNotIn("> __rh_LG1 + __dt_LG1", cs)

    def test_a_plus_or_minus_one_riser_mutation_fails_the_witness(self) -> None:
        """Мутационный оракул на старый дефект: прежний допуск в целый riser
        принимал оба этих неверных результата."""
        expected, riser, tolerance = 1500.0, 175.0, 0.02
        self.assertLess(tolerance, riser)
        for built in (expected - riser, expected + riser):
            with self.subTest(built=built):
                self.assertGreater(abs(built - expected), tolerance)
        self.assertIn(
            "Math.Abs(__gotE_LG1 - __elevNorm_LG1) > __dt_LG1", _cs())

    def test_non_multiple_refusal_names_both_adjacent_candidates(self) -> None:
        cs = _cs()
        self.assertIn("__elevLower_LG1", cs)
        self.assertIn("__elevUpper_LG1", cs)
        self.assertIn("ближайшие кандидаты", cs)

    def test_the_registry_upper_bound_is_autodesks_own_number(self) -> None:
        """«no more than 30000 feet in absolute value» — внешнее число; наше
        в нём только перевод единиц."""
        p = {q.name: q for q in spec.OPS[OP].params}["elevation_mm"]
        self.assertEqual(p.max_val, 30_000 * 304.8)

    def test_the_exact_lower_bound_is_a_runtime_refusal_naming_the_number(self) -> None:
        """Реестровая граница (0) СЛАБАЯ намеренно: точную («half of the
        riser height») знает только живая лестница.  Слабая граница не
        отвергает ни одного законного значения; точную ставит рантайм и
        НАЗЫВАЕТ измеренное число, а не отсылает к документации."""
        p = {q.name: q for q in spec.OPS[OP].params}["elevation_mm"]
        self.assertEqual(p.min_val, 0.0)
        cs = _cs()
        self.assertIn("if (1500.0 < __rh_LG1 / 2.0)", cs)
        self.assertIn("Math.Round(__rh_LG1 / 2.0, 1)", cs)


# ══════════════════════════════ 4. СВИДЕТЕЛЬ ЧИТАЕТ РЕЗУЛЬТАТ И ТУ ЖЕ ОСЬ

class TheWitnessReadsTheResultAndSignsOnlyTheAxisItRead(unittest.TestCase):

    def test_the_boundary_is_re_read_from_the_built_landing(self) -> None:
        """Не из того, что мы сами передали в вызов: сверять вызов с самим
        собой — определение свидетеля, который не может провалиться."""
        cs = _cs()
        self.assertIn("__landing_LG1.GetFootprintBoundary()", cs)
        block = cs.split("foreach (Curve __bc_LG1")[1].split(
            "if (!__bRead_LG1)")[0]
        self.assertNotIn("__ol_LG1", block)

    def test_the_boundary_witness_compares_plan_only(self) -> None:
        """Z прочитанных кривых ставит сам Revit («projected on the stairs
        base level»); подписать ось, которую мы не задавали, запрещает
        test_witness_axis_honesty."""
        block = _cs().split("foreach (Curve __bc_LG1")[1].split(
            "if (!__bRead_LG1)")[0]
        self.assertNotIn(".Z", block)
        self.assertIn(".X", block)
        self.assertIn(".Y", block)

    def test_each_authored_edge_must_be_matched_exactly_once(self) -> None:
        """Счётчик попаданий, а не «нашлось хоть что-то»: без него две
        прочитанные кривые могли бы сесть на одно авторское ребро, а второе
        осталось бы недоказанным."""
        cs = _cs()
        self.assertIn("__bHit_LG1[__bk_LG1]++", cs)
        self.assertIn("if (__bHit_LG1[__bj_LG1] != 1) __bExact_LG1 = false;", cs)

    def test_the_arc_bulge_travels_with_its_midpoint(self) -> None:
        """По одним концам прямая и дуга между теми же концами неразличимы —
        стрелка дуги осталась бы недоказанной."""
        cs = _cs()
        self.assertIn("__bxm_LG1", cs)
        self.assertIn("Evaluate(0.5, true)", cs)

    def test_the_sketched_factory_is_witnessed_as_sketched(self) -> None:
        """Автоматическая площадка — ДРУГОЙ элемент; `IsAutomaticLanding ==
        true` означал бы, что Revit построил не то, что просили."""
        self.assertIn("__landing_LG1.IsAutomaticLanding", _cs())

    def test_ownership_is_witnessed_from_both_ends(self) -> None:
        cs = _cs()
        self.assertIn("__landing_LG1.GetStairs()", cs)
        self.assertIn("__stairs_LG1.GetStairsLandings()", cs)

    def test_requested_normalized_and_built_elevations_ride_the_receipt(self) -> None:
        cs = _cs()
        for key in ("elevation_requested_mm", "elevation_normalized_mm",
                    "elevation_built_mm", "elevation_lower_candidate_mm",
                    "elevation_upper_candidate_mm", "riser_height_mm",
                    "boundary_tolerance_mm"):
            self.assertIn(key, cs)


# ══════════════════════════════ 5. СВИДЕТЕЛЬ ОБЯЗАН УМЕТЬ ПРОВАЛИТЬСЯ

class AWitnessThatCannotFailIsWorseThanNone(unittest.TestCase):

    def test_a_tolerance_that_could_swallow_an_edge_is_a_refusal(self) -> None:
        """«Допуск >= величины» и есть определение вакуумности; здесь на неё
        стоит НАЗВАННЫЙ отказ, а не подпись."""
        cs = _cs()
        self.assertIn("if (2.0 * __dt_LG1 >= 1200.0)", cs)

    def test_the_vacuity_guard_uses_this_contours_own_shortest_edge(self) -> None:
        narrow = {"outer": {"shape": "rect", "origin": [5000.0, 0.0],
                            "size_mm": [2400.0, 300.0]}}
        self.assertIn("if (2.0 * __dt_LG1 >= 300.0)", _cs(contour=narrow))

    def test_the_certificate_finds_no_dead_verdict(self) -> None:
        for ver in VERSIONS:
            with self.subTest(version=ver):
                cert = TC.certify_op(_grounded(ver), ver)
                self.assertTrue(cert.proven)
                self.assertEqual(cert.vacuous, ())

    #: Маркер каждого обязательства -> вердикт, который на нём стоит.
    #: Пара ЯВНАЯ и держится здесь, а не выводится: см. второй тест ниже.
    _WITNESS_PAIRS = (
        (".GetStairs()", "площадка принадлежит не той лестнице (topology)"),
        ("GetStairsLandings", "площадки нет в GetStairsLandings своей "
                              "лестницы (topology)"),
        ("IsAutomaticLanding", "построена автоматическая площадка вместо "
                               "эскизной (semantic)"),
        ("GetFootprintBoundary", "граница площадки не совпала с заданным "
                                 "контуром в плане (geometry)"),
        ("BaseElevation", "отметка площадки не равна нормализованному "
                          "кратному подступенка (geometry)"),
    )

    def test_excising_a_witness_flips_the_certificate(self) -> None:
        """ОРАКУЛ ФАЛЬСИФИЦИРУЕМОСТИ, форма — мутация (дисциплина C5 этого
        репозитория): вырезание настоящего свидетеля ОБЯЗАНО уронить
        `proven`.  У опа со СВОИМ шаблоном программы вырезается ВЕСЬ блок
        свидетеля — и чтение, и вердикт, — потому что именно так выглядит
        неосторожная правка; свидетель, которого сертификат не проверяет, это
        подпись под непрочитанным."""
        real = authoring._SOLO_PROGRAMS[OP]
        survivors = []
        for marker, verdict in self._WITNESS_PAIRS:
            def excised(o, v, intent="", *, _m=marker, _t=verdict, **kw):
                program = real(o, v, intent, **kw)
                return (program.replace(_m, "__CUT__")
                               .replace(f'__post.Add("LG1: {_t}");', "{ }"))
            authoring._SOLO_PROGRAMS[OP] = excised
            try:
                still = TC.certify_op(_grounded("2023"), "2023").proven
            finally:
                authoring._SOLO_PROGRAMS[OP] = real
            if still:
                survivors.append(marker)
        self.assertEqual(
            [], survivors,
            "\nсвидетели, чьё удаление оставляет сертификат PROVEN:\n  "
            + "\n  ".join(survivors))

    def test_a_verdict_deleted_alone_is_caught_HERE_because_the_cert_cannot(self) -> None:
        """ЗАМЕР 10.08.2026, И ЭТО НАСТОЯЩАЯ ГРАНИЦА ПРИБОРА, А НЕ ПРИДИРКА.

        Оп со своим шаблоном программы идёт СТРОКОВЫМ путём сертификата, где
        обязательство разряжается МАРКЕРОМ — структурной подстрокой C#
        (`GetFootprintBoundary`, `BaseElevation`, …).  Маркер живёт в ЧТЕНИИ.
        Значит удаление одного лишь `__post.Add` оставляет маркер на месте, и
        `certify_op` по-прежнему говорит PROVEN — проверено вырезанием всех
        пяти вердиктов по одному: сертификат не уронил НИ ОДНОГО.

        Это не дефект этой волны — тем же путём идёт `create_stairs`, — но
        молчать о нём нельзя: «ключ доказывает, что строка ЕСТЬ, а не что она
        может СРАБОТАТЬ» записано в каноне про вакуумность, а здесь тот же
        разрыв на уровень выше.  Пока модельный путь (`WitnessCheck`) шаблонам
        целой программы недоступен, ПАРУ «маркер + его вердикт» держит ЭТОТ
        тест, и он — единственное, что стоит между удалённым вердиктом и
        зелёными воротами."""
        real = authoring._SOLO_PROGRAMS[OP]
        program = real(_grounded("2023"), "2023")
        for marker, verdict in self._WITNESS_PAIRS:
            with self.subTest(marker=marker):
                self.assertIn(marker, program)
                self.assertIn(f'__post.Add("LG1: {verdict}");', program)
        # И обратная сторона той же пары: прибор действительно слеп, поэтому
        # оракул выше вырезает блок целиком.  Если сертификат когда-нибудь
        # научится ловить одинокий вердикт, ЭТА строка упадёт и позовёт
        # упростить оракул — храповик в обе стороны.
        marker, verdict = self._WITNESS_PAIRS[0]

        def verdict_only(o, v, intent="", **kw):
            return real(o, v, intent, **kw).replace(
                f'__post.Add("LG1: {verdict}");', "{ }")
        authoring._SOLO_PROGRAMS[OP] = verdict_only
        try:
            still = TC.certify_op(_grounded("2023"), "2023").proven
        finally:
            authoring._SOLO_PROGRAMS[OP] = real
        self.assertTrue(
            still,
            "сертификат СТАЛ ловить одинокий вердикт — упростите оракул "
            "мутации выше до вырезания одного `__post.Add`")


# ══════════════════════════════ 6. ОБВЯЗКА: ОБРАТНЫЙ ХОД, ПРИЁМКА, ОТКАЗ UI

class TheOpIsWiredIntoEverySpineThatCounts(unittest.TestCase):

    def test_the_reverse_contract_is_a_dated_capture_gap(self) -> None:
        """`capture_gap` без дня, в который кто-то обязан ответить, — это
        «когда-нибудь», а не решение (`record_ratchet` отказал бы импорту)."""
        rc = RC.contract_for(OP) if hasattr(RC, "contract_for") \
            else RC._CONTRACTS[OP]
        self.assertIs(rc.mode, RC.ReverseMode.CAPTURE_GAP)
        self.assertIs(rc.guarantee, RC.ReverseGuarantee.NONE)
        self.assertTrue(rc.decided_on and rc.due)
        self.assertLess(rc.decided_on, rc.due)

    def test_the_census_counts_a_landing_not_a_stairs(self) -> None:
        """Вторая ячейка означала бы «эта программа построила лестницу», и
        честный успех читался бы как незаказанный чужой create."""
        self.assertEqual(_OP_CATEGORIES[OP], ("OST_StairsLandings",))
        self.assertNotIn(OP, _OP_DERIVED)

    def test_the_modal_dialog_discipline_is_kept_on_both_points(self) -> None:
        """Инцидент 27.07: модальное окно заморозило UI-поток Revit и убило
        мост на шести вызовах подряд.  Предобработчик обязан стоять И на
        транзакции, И на `StairsEditScope.Commit` — предупреждение может
        подняться уже вне транзакции."""
        cs = _cs()
        self.assertIn("__fho.SetFailuresPreprocessor(new __KirStairsFailures());",
                      cs)
        self.assertIn("__ess.Commit(new __KirStairsFailures());", cs)
        self.assertIn("__fa.DeleteWarning(__f);", cs)

    def test_the_edit_scope_is_opened_on_the_existing_stairs(self) -> None:
        """ЗАМЕР, А НЕ ДОГАДКА: одноаргументный `Start(ElementId)` есть на
        всех шести версиях, и ровно он делает площадку отдельной программой
        вместо соседа марша."""
        cs = _cs()
        self.assertIn("if (!__ess.IsPermitted)", cs)
        self.assertIn("__ess.Start(__stairsId_LG1);", cs)
        self.assertLess(cs.index("if (!__ess.IsPermitted)"),
                        cs.index("__ess.Start(__stairsId_LG1)"))
        self.assertIn(
            "__sid_LG1.ToString() != __stairsId_LG1.ToString()", cs)
        self.assertNotIn("StairsRun.Create", cs)

    def test_scope_permission_comes_from_the_scope_contract_not_the_stairs(self) -> None:
        cs = _cs()
        self.assertIn("__ess.IsPermitted", cs)
        self.assertNotIn("__st_LG1.IsInEditMode()", cs)

    def test_soft_refusals_after_start_require_proven_rollback_and_cancel(self) -> None:
        cs = _cs()
        self.assertIn(
            "__rollbackStatus_LG1 = __transaction_LG1.RollBack();", cs)
        self.assertIn(
            "__rollbackStatus_LG1 != TransactionStatus.RolledBack", cs)
        self.assertIn("__scope_LG1.Cancel();", cs)
        self.assertIn("return !__scope_LG1.IsActive;", cs)
        self.assertNotIn("__t.RollBack(); __ess.Cancel();", cs)
        after_start = cs.split("__sid_LG1 = __ess.Start", 1)[1]
        self.assertEqual(after_start.count("return __Refuse"), 2)
        for block in re.findall(
                r"if \(!__rollbackCancel_LG1\(__t, __ess\)\).*?"
                r"return __Refuse", after_start, flags=re.S):
            self.assertIn("throw new InvalidOperationException", block)
        self.assertEqual(len(re.findall(
            r"if \(!__rollbackCancel_LG1\(__t, __ess\)\).*?return __Refuse",
            after_start, flags=re.S)), 2)

    def test_final_witness_reloads_both_elements_after_scope_commit(self) -> None:
        cs = _cs()
        commit = cs.index("__ess.Commit(new __KirStairsFailures());")
        fresh_st = cs.index("doc.GetElement(__stairsId_LG1) as", commit)
        fresh_lg = cs.index("doc.GetElement(__landingId_LG1) as", commit)
        final_check = cs.index("__check_LG1(__freshLg_LG1, __freshSt_LG1)",
                               commit)
        self.assertLess(commit, fresh_st)
        self.assertLess(fresh_st, fresh_lg)
        self.assertLess(fresh_lg, final_check)
        self.assertIn('__results["postcondition_violations"]', cs)

    def test_a5_pre_and_transaction_identity_guards_have_distinct_symbols(self) -> None:
        """A5 проверяет identity до scope и ещё раз внутри transaction. C# не
        разрешает вложенному блоку повторно объявлять local внешнего блока;
        одинаковый prefix делал защищённую программу CS0136 на 6/6."""
        proof = ElementIdentityProof(
            element_id=4242, unique_id="stairs-4242",
            version_guid="0" * 32)
        out = compile_program(
            _prog(_op()), snapshot=SNAPSHOT, revit_version="2023", bulk=True,
            expected_document={
                "title": "A5", "path_name": r"C:\models\a5.rvt",
                "project_uid": "project-a5"},
            expected_identities=(proof,))
        self.assertTrue(out.ok, _codes(out))
        self.assertIn("Element __kirBinding_0", out.csharp)
        self.assertIn("Element __kirLandingTxnBinding_0", out.csharp)
        self.assertIn(
            "if (!__rollbackCancel_LG1(__t, __ess))", out.csharp)

    def test_it_compiles_offline_on_all_six_versions(self) -> None:
        for ver in VERSIONS:
            with self.subTest(version=ver):
                out = _compile(_prog(_op()), ver)
                self.assertTrue(out.ok, _codes(out))
                self.assertIn("CreateSketchedLanding", out.csharp)

    def test_the_four_refused_factories_are_named_with_a_reason(self) -> None:
        """Перепись отдельно считает корзину «названо без причины»; каждая
        строка модульной докстроки держит её маленькой."""
        doc = SLE.__doc__ or ""
        refusals = doc.split("ОТКАЗАНО ПОИМЁННО", 1)
        self.assertEqual(len(refusals), 2, "секция отказов исчезла из шапки")
        section = refusals[1]
        for member in ("CreateAutomaticLanding",
                       "CreateSketchedLandingWithSlopeData",
                       "CreateSketchedRun",
                       "CreateSketchedRunWithSlopeData",
                       "SetSketchedLandingBoundaryAndPath"):
            with self.subTest(member=member):
                self.assertIn(member, section)
                # ПРИЧИНА, А НЕ ТОЛЬКО ИМЯ: перепись считает «названо без
                # причины» отдельной корзиной, и за ночь 09.08 она схлопнулась
                # с 30 до 4 — каждая строка здесь держит её маленькой.
                after = section.split(member, 1)[1][:600]
                self.assertIn("ОТКАЗАНО", after)
                self.assertRegex(after, r"(?s)ОТКАЗАНО.{40,}")


def _grounded(ver: str) -> dict:
    out = _compile(_prog(_op()), ver)
    assert out.ok, _codes(out)
    return out.grounded_ops[0]


if __name__ == "__main__":
    unittest.main(verbosity=2)
