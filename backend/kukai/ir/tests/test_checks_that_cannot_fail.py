"""ПРОВЕРКИ, КОТОРЫЕ НЕ МОГЛИ СРАБОТАТЬ, — ОДИН РОД ДЕФЕКТА, ЧЕТЫРЕ СЛУЧАЯ.

Каждая из четырёх правок 07.08 закрывает строку, которая ЧИТАЛАСЬ проверкой,
не будучи ею. Общего у них не тема, а форма: код подписывал ось, которую никто
не прочёл, и подпись невозможно было отличить от измерения.

  A. `authoring_validation.validate` — цепочка `if/elif p.kind == ...` без
     хвоста. `ParamSpec.kind` — ОТКРЫТАЯ строка (закрытого перечня нет,
     `spec._lint_registry` про киндЫ ничего не знает), поэтому опечатка в
     новом кинде не падала нигде: параметр не проверялся НИ ОДНОЙ ветвью и,
     что хуже, не попадал в `norm` — уезжал дальше так, будто автор его не
     писал. Ловил это только `schema_gen` (`unknown param kind`), то есть
     ЧУЖОЙ проход, и только если кто-то сгенерирует схему.

  B. `acceptance.Verdict.accepted` — было ПОЛЕ, и `check_acceptance` клал в
     него `not mismatches`. При нуле проверенных групп расхождений нет по
     построению, значит вердикт объявлял успех, не проверив ничего.

  C. `serving` — `guarded_out.planned.plan_digest != out.planned.plan_digest`
     после перелоуэринга с пруфами идентичности. В отпечаток пруфы не входят
     вовсе, оба нижения идут от одного `compile_input`, — сравнение было
     тождественно ложным.

  D. `serving._witness_for_success` — тройка осей зелена целиком на успехе, с
     обоснованием «гейт доказал все постусловия до Commit». Довод верен ровно
     настолько, насколько постусловия по оси ОБЪЯВЛЕНЫ, а про это он молчит:
     у 11 опов из 64 нет обязательств по геометрии, у 15 по топологии, у 25
     по семантике.

Каждый тест ниже ПАДАЛ БЫ на коде до правки — это и есть их смысл. Там, где
старое условие можно выписать числом, оно выписано ДОСЛОВНО, чтобы читатель
видел, что именно ловится, а не верил на слово.
"""
from __future__ import annotations

import dataclasses
import os
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(),
                                   "kir_spine_honesty_queue.jsonl"))

from kukai.ir import authoring_validation as AV  # noqa: E402
from kukai.ir import serving as S  # noqa: E402
from kukai.ir import spec  # noqa: E402
from kukai.ir.acceptance import (  # noqa: E402
    VERDICT_MEASURED,
    VERDICT_MISMATCHED,
    VERDICT_NOTHING_TO_CHECK,
    Certainty,
    ExpectedRow,
    Expectation,
    Verdict,
    check_acceptance,
)
from kukai.ir.midend import PlannedProgram  # noqa: E402


def _write_ops() -> tuple[str, ...]:
    return tuple(name for name, op in spec.OPS.items()
                 if op.family in spec.WRITE_FAMILIES)


def _expectation(rows) -> Expectation:
    return Expectation(rows=tuple(rows), derived_categories=(), blind_ops=(),
                       upper_bounds_valid=True, op_count=len(tuple(rows)),
                       notes=())


def _row(count: int, certainty: Certainty) -> ExpectedRow:
    return ExpectedRow(categories=("OST_Walls",), level="L1", count=count,
                       certainty=certainty, op_ids=("w",), why="")


# ═════════════════════════════════════════════════════════════════════════
# A. ОПЕЧАТКА В `kind` БОЛЬШЕ НЕ ТИШИНА
# ═════════════════════════════════════════════════════════════════════════

class ATypoInAParamKindIsNoticed(unittest.TestCase):

    def test_an_unknown_kind_raises_instead_of_dropping_the_parameter(self):
        """РЕФУТАЦИЯ. До правки этот вызов возвращал `norm` БЕЗ параметра и
        БЕЗ единого диагноза: цепочка `if/elif` не имела хвоста, значение с
        неузнанным киндом просто не касалось ни одной ветви. Значит опечатка
        в реестре превращала обязательный параметр в отсутствующий — молча."""
        op_spec = spec.OPS["create_wall"]
        original = op_spec.params
        typo = dataclasses.replace(original[0], kind="pt_xzy")  # pt_xyz
        object.__setattr__(op_spec, "params", (typo,) + tuple(original[1:]))
        try:
            with self.assertRaises(AssertionError) as caught:
                AV.validate({"op": "create_wall", "id": "W1"},
                            "create_wall", 0, "W1", [])
            message = str(caught.exception)
            self.assertIn("pt_xzy", message)
            self.assertIn(typo.name, message)
            # Диагноз обязан НАЗВАТЬ выход: список для чужих киндов.
            self.assertIn("_KINDS_VALIDATED_ELSEWHERE", message)
        finally:
            object.__setattr__(op_spec, "params", original)

    def test_every_writing_op_of_the_registry_still_validates(self):
        """ЗАМОК НЕ СМЕЕТ ОТКАЗАТЬ ВЕРНОЙ ПРОГРАММЕ. Первая ветвь цикла несёт
        второй конъюнкт (`p.name not in ("p0_mm", "p1_mm")`): концы отрезка
        разбираются ДО цикла, целиком, потому что закон «длина ~0» смотрит на
        обе точки сразу. Наивный `else` сорвался бы на 32 таких параметрах у
        16 опов — ровно то, что дороже пропущенной находки."""
        for name in _write_ops():
            op_spec = spec.OPS[name]
            for payload in ({}, {p.name: None for p in op_spec.params}):
                op = dict(payload, op=name, id="X1")
                with self.subTest(op=name, payload=sorted(payload)):
                    AV.validate(op, name, 0, "X1", [])

    def test_the_kind_vocabulary_is_closed_and_matches_the_registry(self):
        """РЕФУТАЦИЯ ТРЕТЬЕГО СЛУЧАЯ. `schema_gen` ссылался на «registry lint
        keeps kinds closed» — на гарантию, которой не было: `_lint_registry`
        знал про клетки способности, эффекты и пулы, а про `ParamSpec.kind` не
        знал ничего. Теперь словарь закрыт, и тест держит его В ОБЕ СТОРОНЫ:
        лишнее имя в наборе — такая же ложь, как недостающее, потому что
        набор, куда можно дописать что угодно, ничего не закрывает."""
        in_use = {p.kind for op in spec.OPS.values() for p in op.params}
        self.assertEqual(spec.PARAM_KINDS, in_use)
        self.assertEqual(len(spec.PARAM_KINDS), 34)

    def test_a_typo_is_refused_at_registry_import_as_well(self):
        """ТРИ ЗАМКА, ТРИ РАЗНЫЕ ПРИЧИНЫ ПАДЕНИЯ. Реестр не импортируется с
        неназванным видом; схема не собирается; программа не разбирается.
        Здесь проверяется первый — самый ранний из трёх."""
        op_spec = spec.OPS["create_wall"]
        original = op_spec.params
        typo = dataclasses.replace(original[0], kind="pt_xzy")
        object.__setattr__(op_spec, "params", (typo,) + tuple(original[1:]))
        try:
            with self.assertRaises(AssertionError) as caught:
                spec._lint_registry()
            self.assertIn("pt_xzy", str(caught.exception))
            self.assertIn("PARAM_KINDS", str(caught.exception))
        finally:
            object.__setattr__(op_spec, "params", original)
        # Реестр обязан снова быть чистым — иначе тест отравил бы соседей.
        spec._lint_registry()

    def test_the_allowlist_holds_only_kinds_no_write_op_can_carry(self):
        """Список чужих киндов — перепись, а не склад. Каждый ключ обязан
        быть настоящим киндом реестра И не стоять ни на одном пишущем опе:
        иначе он поглотил бы опечатку вместо того, чтобы её показать."""
        in_use = {p.kind for op in spec.OPS.values() for p in op.params}
        on_writes = {p.kind for name in _write_ops()
                     for p in spec.OPS[name].params}
        self.assertTrue(AV._KINDS_VALIDATED_ELSEWHERE)
        for kind, where in AV._KINDS_VALIDATED_ELSEWHERE.items():
            with self.subTest(kind=kind):
                self.assertIn(kind, in_use)
                self.assertNotIn(kind, on_writes)
                # Адрес разбора назван, а не подразумевается.
                self.assertIn("compiler", where)


# ═════════════════════════════════════════════════════════════════════════
# B. ПУСТАЯ ПРОВЕРКА — НЕ УСПЕХ
# ═════════════════════════════════════════════════════════════════════════

class AnEmptyCheckIsNotAPass(unittest.TestCase):

    def test_an_expectation_with_nothing_to_check_is_not_accepted(self):
        """РЕФУТАЦИЯ. Строка UNKNOWN/0 пропускается `check_acceptance`, групп
        проверено ноль, расхождений ноль — и прежнее `accepted=not mismatches`
        давало ИСТИНУ. Приёмка объявляла успех, не посмотрев ни на что."""
        verdict = check_acceptance(
            _expectation([_row(0, Certainty.UNKNOWN)]), {}, {})
        self.assertEqual(verdict.checked_groups, 0)
        self.assertEqual(verdict.mismatches, ())
        # Прежняя формула, выписанная ДОСЛОВНО: она и была истинной.
        self.assertTrue(not verdict.mismatches)
        self.assertFalse(verdict.accepted)
        self.assertTrue(verdict.vacuous)
        self.assertEqual(verdict.reason, VERDICT_NOTHING_TO_CHECK)

    def test_a_measured_match_is_still_accepted(self):
        """ЗЕЛЁНОЕ НЕ СТАЛО КРАСНЫМ. Правка обязана двигать ровно один случай
        — нулевую проверку, — и не трогать настоящую сходимость."""
        verdict = check_acceptance(
            _expectation([_row(1, Certainty.EXACT)]), {},
            {("OST_Walls", "L1"): 1})
        self.assertEqual(verdict.checked_groups, 1)
        self.assertTrue(verdict.accepted)
        self.assertEqual(verdict.reason, VERDICT_MEASURED)

    def test_a_finding_is_distinguishable_from_an_emptiness(self):
        """Оба дают `accepted=False`, и это РАЗНЫЕ факты: первый чинят
        постройкой, второй — ожиданием. Голый булев их сливал."""
        missed = check_acceptance(
            _expectation([_row(1, Certainty.EXACT)]), {},
            {("OST_Walls", "L1"): 0})
        empty = check_acceptance(
            _expectation([_row(0, Certainty.UNKNOWN)]), {}, {})
        self.assertFalse(missed.accepted)
        self.assertFalse(empty.accepted)
        self.assertEqual(missed.reason, VERDICT_MISMATCHED)
        self.assertEqual(empty.reason, VERDICT_NOTHING_TO_CHECK)
        self.assertNotEqual(missed.reason, empty.reason)
        self.assertIn("reason", missed.to_dict())

    def test_the_lying_verdict_can_no_longer_be_constructed(self):
        """`accepted` больше НЕ ПОЛЕ. Пока оно было полем, любой вызывающий
        мог записать в него истину при нуле проверенных групп; теперь такого
        имени среди полей нет, и солгать нечем."""
        names = {f.name for f in dataclasses.fields(Verdict)}
        self.assertNotIn("accepted", names)
        self.assertIn("checked_groups", names)


# ═════════════════════════════════════════════════════════════════════════
# C. ОТПЕЧАТОК ПЛАНА НЕ ВИДИТ ПРУФОВ ИДЕНТИЧНОСТИ
# ═════════════════════════════════════════════════════════════════════════

class ThePlanDigestCannotSeeIdentityProofs(unittest.TestCase):

    def test_the_digest_binds_no_identity_and_the_deleted_check_knew_nothing(self):
        """ПРИЧИНА УДАЛЕНИЯ, ЗАКРЕПЛЁННАЯ ТЕСТОМ. Снятое условие сравнивало
        `plan_digest` двух нижений, различавшихся ТОЛЬКО пруфами
        идентичности. Ни одного пруфа отпечаток не связывает, значит стороны
        были равны всегда.

        Тест сторожит и обратное: если однажды пруфы В отпечаток внесут, он
        упадёт — и это будет сигналом, что снятую проверку можно (и нужно)
        вернуть, теперь уже настоящей."""
        bound = set(PlannedProgram.__dataclass_fields__)
        self.assertNotIn("expected_identities", bound)
        self.assertNotIn("identity_proofs", bound)
        for field_name in bound:
            self.assertNotIn("identit", field_name.lower())

    def test_the_surviving_arms_are_the_ones_that_can_fire(self):
        """Что осталось на месте снятого: `guarded_out is None`
        (противоречивые пруфы на один element_id) и `not guarded_out.ok`
        (перелоуэринг не скомпилировался). Обе — про исход ВТОРОЙ компиляции,
        то есть про то, что действительно могло пойти не так.

        ПРОЧТЁННАЯ СТРОКА СЛОМАЛАСЬ ОТ ЧЕСТНОЙ ПРАВКИ (11.08.2026). Здесь
        стояло `assertIn("if guarded_out is None or not guarded_out.ok:")` —
        НАПИСАНИЕ условия целиком, одной строкой. Волна приёмки дописала в то
        же условие два настоящих плеча (`grounded is None` и несовпадение
        `ground_digest` с зарегистрированным), условие переехало на пять
        строк, и тест покраснел, хотя охрана стала СТРОЖЕ. Ирония названа
        вслух: прибор, который ищет проверки, неспособные сработать, сам был
        привязан к правописанию вместо свойства.

        Теперь читается СТРУКТУРА, а не текст: `ast` находит условие,
        ветвящееся по `guarded_out`, и плечи сверяются по форме. Комментарий,
        перенос строки и переименование локальной переменной больше ничего не
        решают; вернуть мёртвое сравнение — решает.

        ГРАНИЦА ЭТОГО ТЕСТА, названная, потому что она равна силе `ast`, а не
        силе прогона. Это НЕ поведенческая проверка: `_handle_revit_ir_inner`
        — граница живой записи, её нельзя выполнить без моста, сессии приёмки
        и снимка модели, и подделка всех трёх доказывала бы работу подделки.
        Поэтому тест сторожит ровно две вещи: что снятое сравнение отпечатков
        не вернулось, и что оставшиеся плечи — про исход ВТОРОЙ компиляции.
        Что они действительно отказывают, доказывает не он, а приёмочные
        тесты записи.
        """
        import ast
        import inspect
        import textwrap

        tree = ast.parse(textwrap.dedent(
            inspect.getsource(S._handle_revit_ir_inner)))
        guards = [node for node in ast.walk(tree)
                  if isinstance(node, ast.If)
                  and "guarded_out" in ast.dump(node.test)]
        self.assertTrue(guards, "условие, ветвящееся по guarded_out, исчезло")

        arms: list[str] = []
        for node in guards:
            test = node.test
            arms.extend(
                ast.dump(value) for value in
                (test.values if isinstance(test, ast.BoolOp) else [test]))

        def has(fragment: str) -> bool:
            return any(fragment in arm for arm in arms)

        # Плечо 1: пруфы противоречивы — второй компиляции не было вовсе.
        self.assertTrue(
            has("Compare") and has("'guarded_out'") and has("Is("),
            "плечо `guarded_out is None` не найдено среди условий")
        # Плечо 2: перелоуэринг с гардами не скомпилировался.
        self.assertTrue(
            has("attr='ok'"), "плечо `not guarded_out.ok` не найдено")

        # МЁРТВОЕ СРАВНЕНИЕ НЕ ВЕРНУЛОСЬ. `plan_digest` не связывает ни одного
        # пруфа идентичности, поэтому сравнение отпечатков двух нижений было
        # тождественно истинным и не могло сработать ни разу.
        for arm in arms:
            self.assertNotIn("attr='plan_digest'", arm,
                             "мёртвое сравнение отпечатков вернулось в код")
            self.assertNotIn("attr='planned'", arm,
                             "мёртвое сравнение отпечатков вернулось в код")


# ═════════════════════════════════════════════════════════════════════════
# D. ЗЕЛЁНАЯ ОСЬ ОБЯЗАНА БЫТЬ ИЗМЕРЕННОЙ
# ═════════════════════════════════════════════════════════════════════════

class AGreenAxisMustHaveBeenMeasured(unittest.TestCase):

    def test_an_op_that_promised_nothing_on_an_axis_says_so(self):
        """РЕФУТАЦИЯ. `set_param` не объявляет НИ ОДНОГО обязательства по
        геометрии, топологии или семантике (`translation_cert.REFINEMENT`), а
        успешная запись всё равно возвращала полностью зелёную тройку. Теперь
        рядом с тройкой едет список осей, которых никто не обещал мерить."""
        witness = S._witness_for_success("write", {}, ("set_param",))
        self.assertEqual(
            witness["unwitnessed_axes"],
            {"geometry": ["set_param"], "semantic": ["set_param"],
             "topology": ["set_param"]})
        # Тройка НЕ переопределена: поле добавочное, а не подменяющее.
        self.assertTrue(witness["geometry_ok"])
        self.assertTrue(witness["semantic_ok"])
        self.assertTrue(witness["topology_ok"])

    def test_a_fully_obligated_op_reports_nothing_unwitnessed(self):
        """Обратная сторона: `create_wall` объявляет все три оси, и список
        пуст. Прибор, который кричит всегда, не лучше молчащего."""
        witness = S._witness_for_success("write", {}, ("create_wall",))
        self.assertEqual(witness["unwitnessed_axes"], {})

    def test_nothing_to_judge_is_none_and_none_is_not_green(self):
        """ТРИСТЕЙТ, тем же законом, что `Judged.proven`. Пустая программа и
        оп вне таблицы обязательств дают `None` — «сказать нечего», — а не
        пустой список, который читался бы как «всё объявлено»."""
        self.assertIsNone(S._unwitnessed_axes(()))
        self.assertIsNone(S._unwitnessed_axes(("not_a_real_op",)))
        self.assertIsNone(
            S._witness_for_success("write", {})["unwitnessed_axes"])

    def test_a_mixed_program_names_which_op_promised_nothing(self):
        """РЕФУТАЦИЯ ПРАВКИ ПО САМОРЕВЬЮ. Пока ответом был СПИСОК ОСЕЙ, эта
        пара давала `["geometry","semantic","topology"]` — байт в байт то же,
        что один голый `set_param`. Два разных мира под одним ответом:
        «не проверено ничего» и «одна операция из двух ничего не обещала».
        Теперь виновник назван, и случаи различимы."""
        self.assertEqual(S._unwitnessed_axes(("create_wall",)), {})
        mixed = S._unwitnessed_axes(("create_wall", "set_param"))
        self.assertEqual(sorted(mixed), ["geometry", "semantic", "topology"])
        for axis in mixed:
            with self.subTest(axis=axis):
                # `create_wall` объявил все три и НЕ ДОЛЖЕН быть назван.
                self.assertEqual(mixed[axis], ["set_param"])
        # СЛИЯНИЕ ДВУХ ПРОГРАММ ЗДЕСЬ — НЕ ДЕФЕКТ, И ЭТО ПРОВЕРЕНО ЗАМЕРОМ.
        # `(create_wall, set_param)` и `(set_param,)` дают ОДИН И ТОТ ЖЕ
        # словарь, и так и должно быть: виноват один и тот же оп, значит и
        # незаработанные утверждения одни и те же. Случаи различает не длина
        # ответа, а ИМЕНА: `create_wall` не назван ни разу, и по этому видно,
        # что его зелёный заработан.
        #
        # Здесь стояло `assertNotEqual(mixed, bare)` — требование, которого я
        # не продумал: оно объявляло дефектом ровно то поведение, которое
        # правильно. Замер снял его до того, как оно уехало красным тестом.
        self.assertEqual(S._unwitnessed_axes(("set_param",)), mixed)
        self.assertNotIn("create_wall", str(mixed))

    def test_the_three_booleans_are_byte_identical_to_the_old_formula(self):
        """НОВОЕ ПОЛЕ НИЧЕГО НЕ ПЕРЕОПРЕДЕЛИЛО. Старая раскладка выписана
        здесь ДОСЛОВНО и сверяется с новой на каждом наборе нарушений."""
        corpus = (
            [],
            ["bad thing (geometry)"],
            ["bad thing (topology)"],
            ["bad thing"],
            ["a (geometry)", "b (topology)", "c"],
            ["a (geometry)", "b (geometry)"],
        )
        for vio in corpus:
            with self.subTest(violations=vio):
                old = {
                    "geometry_ok": not any("(geometry)" in x for x in vio),
                    "topology_ok": not any("(topology)" in x for x in vio),
                    "semantic_ok": not any(
                        "(geometry)" not in x and "(topology)" not in x
                        for x in vio),
                }
                self.assertEqual(S._axes_from_violations(vio), old)

    def test_both_witness_paths_split_the_axes_identically(self):
        """D1: раскладка жила ДВУМЯ ДОСЛОВНЫМИ КОПИЯМИ в двух функциях. Копии
        расходятся молча, поэтому теперь она одна — и обе дороги обязаны
        давать одну тройку на одних нарушениях."""
        vio = ["a (geometry)", "b (topology)", "c"]
        success = S._witness_for_success(
            "write", {"postcondition_violations": vio}, ("create_wall",))
        failure = S._derive_witness(
            False, "write", {"code": "KIR-X004", "violations": vio})
        for axis in ("geometry_ok", "topology_ok", "semantic_ok"):
            with self.subTest(axis=axis):
                self.assertEqual(success[axis], failure[axis])

    def test_a_query_carries_no_axis_claim_at_all(self):
        """У запроса нет ни свидетеля, ни обязательств — и поля тоже нет:
        пустой список там читался бы как утверждение."""
        self.assertEqual(S._witness_for_success("query", {}), {"read_only": True})
        self.assertNotIn(
            "unwitnessed_axes",
            S._witness_for_success("query", {}, ("create_wall",)))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
