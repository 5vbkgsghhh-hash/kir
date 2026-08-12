"""ВАКУУМНЫЙ СВИДЕТЕЛЬ: проверка, которая НЕ МОЖЕТ упасть, — не проверка.

ДЕФЕКТ, ИЗ КОТОРОГО ВЫРОС ЭТОТ ФАЙЛ (аудит 09.08.2026).  Свидетель стены был
заменён на

    if (false) __post.Add("never");

и ``certify_op(wall, "2026").proven`` остался ``True``.  Причина —
двухслойная, и оба слоя проверяли ОДНО И ТО ЖЕ:

  * ``emit_model.WitnessCheck`` требует НАЛИЧИЯ ``__post.Add`` в вердикте;
  * ``translation_cert.certify_op`` требует НАЛИЧИЯ ключа обязательства.

Ни один не смотрел на УСЛОВИЕ, под которым эта строка стоит.  «Существует
строка, способная добавить нарушение» принималось за «проверка способна
нарушение обнаружить» — и разряжало обязательство сертификата.

ФОРМА ПРОВЕРКИ — МУТАЦИЯ, а не утверждение (дисциплина C5 этого репозитория):
каждый класс вакуума ВСАЖИВАЕТСЯ в свидетеля НАСТОЯЩЕГО опа, и сертификат
ОБЯЗАН отказать типизированной, привязанной к опу диагностикой.

ЧЕСТНАЯ ГРАНИЦА, ЗАКРЕПЛЁННАЯ МАШИННО.  Достижимость неразрешима, и
``NotDetected`` ниже — это НЕ список задач, а предъявленный предел: формы
вакуума, которые прибор НЕ ВИДИТ и про которые обязан молчать, а не врать.
Класс дефекта, с которым борется этот дом, — прибор, покрывающий ЧАСТЬ
диапазона и выдающий себя за полный; поэтому пределы здесь тестируются
наравне с находками.
"""
from __future__ import annotations

import os
import tempfile
import unittest

os.environ.setdefault(
    "KIR_REJECTIONS_PATH",
    os.path.join(tempfile.gettempdir(), "kir_vacuity_queue.jsonl"))

from kukai.ir import authoring                                  # noqa: E402
from kukai.ir import translation_cert as tc                     # noqa: E402
from kukai.ir import spec                                       # noqa: E402
from kukai.ir.authoring import _SOLO_PROGRAMS                   # noqa: E402
from kukai.ir.emit_model import BarePost, WitnessCheck          # noqa: E402
from kukai.ir.tests.test_emitter_scope_contract import VERSIONS  # noqa: E402
from kukai.ir.tests.test_tolerance_provenance import (          # noqa: E402
    _full_instances,
    WRITE_OPS,
)

WALL = {"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
        "p1_mm": [6000, 0], "height_mm": 3000.0,
        "level": {"__grounded__": {"id": 42, "name": "L1",
                                   "via": "element_id"}},
        "type": {"__grounded__": {"id": 901, "name": "T",
                                  "via": "element_id"}}}


def _grounded(op_name: str) -> dict:
    """Настоящий заземлённый оп из корпуса — не выдуманный вручную словарь."""

    for name, op, _ver in _full_instances():
        if name == op_name:
            return op
    raise AssertionError(f"корпус не строит {op_name}")


#: (имя формы, C# вердикта, ожидаемый класс вакуума).  Каждая строка —
#: САЖЕНЕЦ: она вставляется вместо настоящего вердикта живого свидетеля.
PLANTS: tuple[tuple[str, str, str], ...] = (
    ("if (false)",
     '    if (false) __post.Add("never");\n',
     tc.VACUITY_CONSTANT_FALSE),
    ("if (0 == 1)",
     '    if (0 == 1) __post.Add("never");\n',
     tc.VACUITY_CONSTANT_FALSE),
    ("if (1 > 2)",
     '    if (1 > 2) __post.Add("never");\n',
     tc.VACUITY_CONSTANT_FALSE),
    ("if (!true)",
     '    if (!true) __post.Add("never");\n',
     tc.VACUITY_CONSTANT_FALSE),
    ("if (false && live)",
     '    if (false && __el_W1 == null) __post.Add("never");\n',
     tc.VACUITY_CONSTANT_FALSE),
    ("if (false || 1 > 2)",
     '    if (false || 1 > 2) __post.Add("never");\n',
     tc.VACUITY_CONSTANT_FALSE),
    ("if ((false))",
     '    if ((false)) { __post.Add("never"); }\n',
     tc.VACUITY_CONSTANT_FALSE),
    ("while (false)",
     '    while (false) { __post.Add("never"); }\n',
     tc.VACUITY_CONSTANT_FALSE),
    ("for (;false;)",
     '    for (int __i = 0; false; __i++) { __post.Add("never"); }\n',
     tc.VACUITY_CONSTANT_FALSE),
    ("else of if (true)",
     '    if (true) { } else { __post.Add("never"); }\n',
     tc.VACUITY_CONSTANT_FALSE),
    ("nested under if (false)",
     '    if (false) { if (__el_W1 == null) { __post.Add("never"); } }\n',
     tc.VACUITY_CONSTANT_FALSE),
    ("self-comparison !=",
     '    if (__el_W1 != __el_W1) __post.Add("never");\n',
     tc.VACUITY_SELF_COMPARISON),
    ("self-comparison <",
     '    if (__el_W1.Id < __el_W1.Id) __post.Add("never");\n',
     tc.VACUITY_SELF_COMPARISON),
    ("self-comparison through a tolerance",
     '    if (Math.Abs(MM(__el_W1.Width) - MM(__el_W1.Width)) > 5.0)\n'
     '        __post.Add("never");\n',
     tc.VACUITY_SELF_COMPARISON),
    ("unreachable after return",
     '    return;\n    __post.Add("never");\n',
     tc.VACUITY_UNREACHABLE),
    ("unreachable after throw inside a LIVE guard",
     '    if (__el_W1 == null) { throw new Exception();'
     ' __post.Add("never"); }\n',
     tc.VACUITY_UNREACHABLE),
    ("unreachable after continue in a loop",
     '    foreach (var __x in __els) { continue; __post.Add("never"); }\n',
     tc.VACUITY_UNREACHABLE),
)

#: Формы, которые прибор ДОКАЗУЕМО не видит.  Каждая — вакуум, и каждая здесь
#: закреплена как ПРЕДЕЛ: если однажды она станет находкой, тест упадёт и
#: границу перепишут ЯВНО, а не тихо.
NOT_DETECTED: tuple[tuple[str, str], ...] = (
    ("константа в переменной (нет распространения констант)",
     '    bool __never = false;\n    if (__never) __post.Add("never");\n'),
    ("пустая коллекция (число итераций из текста не выводится)",
     '    foreach (var __x in __definitelyEmpty) __post.Add("never");\n'),
    ("недостижимость через данные (null уже исключён выше)",
     '    if (__el_W1 == null) __post.Add("never");\n'),
    ("допуск шире любого расхождения — живое число, не вакуум",
     '    if (Math.Abs(MM(__a) - MM(__b)) > 1e30) __post.Add("never");\n'),
)


def _plant(op_name: str, key: str, verdict_cs: str):
    """Заменить вердикт свидетеля ``key`` опа ``op_name`` на саженец."""

    original = authoring._EMITTERS[op_name]

    def broken(op, ver, stamp, isolation="atomic", _o=original):
        decl, create, post, readback = _o(op, ver, stamp, isolation)
        bare = isinstance(post, BarePost)
        checks = list(post.checks) if bare else list(post)
        out = []
        for check in checks:
            if check.obligation_key != key:
                out.append(check)
                continue
            out.append(WitnessCheck(
                obligation_key=check.obligation_key,
                reader_cs="",
                verdict_cs=verdict_cs,
                message=check.message,
                tol=None,
                style="plain"))
        return decl, create, (BarePost(tuple(out)) if bare else out), readback

    authoring._EMITTERS[op_name] = broken
    return original


class MutationPlantsMustBeRefused(unittest.TestCase):
    """Каждый класс вакуума, всаженный в живого свидетеля, роняет сертификат."""

    def test_baseline_wall_is_proven(self) -> None:
        # Опора всей мутации: без саженца стена доказана. Иначе тесты ниже
        # проходили бы по неверной причине.
        self.assertTrue(tc.certify_op(WALL, "2026").proven)

    def test_every_plant_is_refused_with_a_typed_named_diagnostic(self) -> None:
        for label, verdict_cs, expected_kind in PLANTS:
            with self.subTest(plant=label):
                original = _plant("create_wall", "endpoints", verdict_cs)
                try:
                    cert = tc.certify_op(WALL, "2026")
                finally:
                    authoring._EMITTERS["create_wall"] = original

                self.assertFalse(
                    cert.proven,
                    f"саженец {label!r} оставил сертификат доказанным")
                self.assertTrue(cert.vacuous, f"{label}: находки нет")
                kinds = {f.kind for f in cert.vacuous}
                self.assertIn(expected_kind, kinds, f"{label}: класс {kinds}")
                for finding in cert.vacuous:
                    self.assertEqual(finding.op, "create_wall")
                    self.assertEqual(finding.obligation_key, "endpoints")
                    self.assertIn(finding.kind, tc.VACUITY_KINDS)
                # Обязательство обязано стать НЕ разряженным: сертификат
                # называет КЛАУЗУЛУ, а не только строку C#.
                gaps = "\n".join(cert.gaps)
                self.assertIn("LocationCurve endpoints", gaps)
                self.assertIn("VACUOUS", gaps)

    def test_the_plant_is_refused_in_a_second_op_too(self) -> None:
        # Не свойство create_wall: тот же саженец в трубе.
        pipe = _grounded("create_pipe")
        self.assertTrue(tc.certify_op(pipe, "2026").proven)
        original = _plant("create_pipe", "endpoints",
                          '    if (false) __post.Add("never");\n')
        try:
            cert = tc.certify_op(pipe, "2026")
        finally:
            authoring._EMITTERS["create_pipe"] = original
        self.assertFalse(cert.proven)
        self.assertEqual({f.op for f in cert.vacuous}, {"create_pipe"})
        self.assertEqual({f.obligation_key for f in cert.vacuous}, {"endpoints"})

    def test_assert_refined_raises_the_specific_typed_error(self) -> None:
        original = _plant("create_wall", "endpoints",
                          '    if (false) __post.Add("never");\n')
        try:
            cert = tc.certify_op(WALL, "2026")
        finally:
            authoring._EMITTERS["create_wall"] = original
        # «Проверки нет» и «проверка есть и не может сработать» — разные
        # дефекты и обязаны приходить под разными именами.
        with self.assertRaises(tc.VacuousWitnessError):
            tc.assert_refined(cert)
        # ...оставаясь ловимыми старыми обработчиками.
        self.assertTrue(issubclass(tc.VacuousWitnessError,
                                   tc.UnprovenRefinementError))

    def test_a_missing_check_still_raises_the_general_error(self) -> None:
        # Не ослабили существующее: удаление свидетеля по-прежнему отказ, и
        # НЕ вакуумный (класс дефекта другой).
        original = authoring._EMITTERS["create_wall"]

        def broken(op, ver, stamp, isolation="atomic"):
            d, c, p, r = original(op, ver, stamp, isolation)
            return d, c, [x for x in p if x.obligation_key != "endpoints"], r

        authoring._EMITTERS["create_wall"] = broken
        try:
            cert = tc.certify_op(WALL, "2026")
        finally:
            authoring._EMITTERS["create_wall"] = original
        self.assertFalse(cert.proven)
        self.assertEqual(cert.vacuous, ())
        with self.assertRaises(tc.UnprovenRefinementError) as ctx:
            tc.assert_refined(cert)
        self.assertNotIsInstance(ctx.exception, tc.VacuousWitnessError)

    def test_plants_removed_the_wall_is_proven_again(self) -> None:
        # Саженцы сняты — сертификат ТОТ ЖЕ, что до всей волны.
        self.assertTrue(tc.certify_op(WALL, "2026").proven)
        self.assertEqual(tc.certify_op(WALL, "2026").vacuous, ())


class TheDetectorItself(unittest.TestCase):
    """Guard the guard: без этого весь набор выше мог бы проходить вхолостую."""

    def test_it_recognises_the_archetype(self) -> None:
        findings, partial = tc.analyze_witness_cs(
            'if (false) __post.Add("");')
        self.assertFalse(partial)
        self.assertEqual([f[0] for f in findings], [tc.VACUITY_CONSTANT_FALSE])

    def test_it_stays_silent_on_a_live_witness(self) -> None:
        live = (
            'var __lc = __el_W1.Location as LocationCurve;\n'
            'if (__lc == null) __post.Add("");\n'
            'else\n'
            '{\n'
            '    var __c = __lc.Curve;\n'
            '    if (Math.Abs(MM(__c.GetEndPoint(0).X) - 0) > 1.0)\n'
            '        __post.Add("");\n'
            '}\n')
        findings, partial = tc.analyze_witness_cs(live)
        self.assertEqual(findings, ())
        self.assertFalse(partial)

    def test_a_live_verdict_beside_a_dead_one_is_still_reported(self) -> None:
        # Правило намеренно строгое: находкой является КАЖДЫЙ мёртвый
        # __post.Add, а не только «мертвы все» — иначе выхолащивание одной из
        # двух веток свидетеля проходило бы молча.
        mixed = ('if (__lc == null) __post.Add("");\n'
                 'if (false) __post.Add("");\n')
        findings, _ = tc.analyze_witness_cs(mixed)
        self.assertEqual(len(findings), 1)

    def test_the_named_limits_are_really_limits(self) -> None:
        for label, code in NOT_DETECTED:
            with self.subTest(limit=label):
                findings, _ = tc.analyze_witness_cs(code)
                self.assertEqual(
                    findings, (),
                    f"{label}: прибор внезапно ЭТО видит — граница в "
                    "docstring translation_cert устарела, перепишите её ЯВНО")

    def test_an_always_true_guard_is_not_a_vacuity_finding(self) -> None:
        # Всегда-истинная охрана — другой дефект: она падает ВСЕГДА и ГРОМКО,
        # то есть не относится к классу «молча-неверно».
        findings, _ = tc.analyze_witness_cs('if (true) __post.Add("");')
        self.assertEqual(findings, ())

    def test_a_fragment_that_is_not_self_contained_is_flagged_partial(self) -> None:
        findings, partial = tc.analyze_witness_cs(
            'if (false) __post.Add(""); }\nprivate class X { }')
        self.assertTrue(partial)
        # ...и всё же разобран: неполнота не означает слепоту.
        self.assertEqual([f[0] for f in findings], [tc.VACUITY_CONSTANT_FALSE])

    def test_constant_folding_corners(self) -> None:
        for expr, expected in (
                ("false", False), ("true", True), ("!false", True),
                ("0 == 1", False), ("1 != 1", False), ("2 <= 1", False),
                ("1.0 > 2.0", False), ("(false)", False),
                ("false && __x", False), ("__x && false", False),
                ("true || __x", True), ("false || false", False),
                ("__x == __x", True), ("__x != __x", False),
                ("Math.Abs(MM(__a) - MM(__a)) > 5.0", False),
                ("__a == __b", None), ("__a > 5.0", None),
                ("__lc == null", None), ("", None)):
            with self.subTest(expr=expr):
                self.assertEqual(tc._const_bool(expr)[0], expected)


class TheWholeCorpusIsClean(unittest.TestCase):
    """Ratchet: ни один зарегистрированный оп не эмитирует мёртвый вердикт."""

    def test_no_registered_op_emits_a_dead_verdict(self) -> None:
        offenders = set()
        for name, op, ver in _full_instances():
            for finding in tc.certify_op(op, ver).vacuous:
                offenders.add(
                    f"{name}.{finding.obligation_key} [{finding.kind}] "
                    f"{finding.guard}")
        self.assertEqual(
            sorted(offenders), [],
            "эти свидетели не могут сработать:\n  " + "\n  ".join(sorted(offenders)))

    def test_only_whole_program_templates_are_read_in_pieces(self) -> None:
        # Несамодостаточны по скобкам ровно те тексты, у которых свой шаблон
        # ЦЕЛОЙ программы (тело метода + объявления классов, рамку даёт
        # wrap_user_code), то есть в точности `spec.SOLO_OPS`. Появление
        # третьего такого текста — факт, который обязан быть замечен, и с
        # 10.08.2026 множество сверяется с РЕЕСТРОМ, а не с одним именем:
        # площадка приехала вторым жильцом, и жёсткий литерал объявил бы
        # исправную работу регрессией.
        partial = {name for name, op, ver in _full_instances()
                   if tc.certify_op(op, ver).vacuity_partial}
        self.assertEqual(partial, set(spec.SOLO_OPS))

        # ...и «по кускам» здесь всё же означает ЦЕЛИКОМ: каждый вердикт
        # шаблона обходом достигнут. Неполный разбор — риск, а не факт; тут он
        # измерен и оказался нулевым — у ОБОИХ шаблонов.
        for name in sorted(spec.SOLO_OPS):
            with self.subTest(op=name):
                solo = next(op for got, op, _v in _full_instances()
                            if got == name)
                reached, present = tc.witness_site_census(
                    tc._code(_SOLO_PROGRAMS[name](solo, "2026")))
                self.assertGreater(present, 0)
                self.assertEqual(reached, present)

    def test_the_walk_reaches_every_verdict_site_in_the_corpus(self) -> None:
        # БЕЗ ЭТОГО «ноль находок» и «обход молча прошёл мимо» неразличимы —
        # ровно та подмена, которой этот файл посвящён. Считаем достигнутые
        # обходом __post.Add против присутствующих в тексте.
        missed = []
        reached = total = 0
        for name, op, ver in _full_instances():
            emitter = authoring._EMITTERS.get(name)
            if emitter is None:      # соло-оп: свой шаблон целой программы
                continue
            _d, _c, post, _r = emitter(op, ver, "kir:census")
            checks = list(post.checks) if isinstance(post, BarePost) else list(post)
            for check in checks:
                got, want = tc.witness_site_census(tc._code(check.render()))
                reached += got
                total += want
                if got != want:
                    missed.append(f"{name}.{check.obligation_key}: {got}/{want}")
        self.assertGreater(total, 0, "корпус не дал ни одного вердикта")
        self.assertEqual(
            sorted(missed), [],
            "обход не дошёл до этих вердиктов — «чисто» было бы ложью:\n  "
            + "\n  ".join(sorted(missed)))

    def test_every_write_op_is_actually_exercised(self) -> None:
        # Пустой корпус дал бы зелёный рычаг выше вхолостую.
        seen = {name for name, _op, _ver in _full_instances()}
        self.assertEqual(sorted(set(WRITE_OPS) - seen), [])
        self.assertGreaterEqual(len(VERSIONS), 6)


if __name__ == "__main__":
    unittest.main(verbosity=2)
