"""L6 ОРАКУЛ С ТРЕМЯ СОСТОЯНИЯМИ, а не с молчанием на два из них.

ПОВОД — СОБСТВЕННАЯ ОШИБКА ЭТОГО ЖЕ ОРАКУЛА (11.08.2026). Обход территории
отчитался: «семь опов оракул пропустил», и назвал причины. ВСЕ ТРИ ПРИЧИНЫ
БЫЛИ НЕВЕРНЫ, и каждая — тот самый класс, за которым обход охотился:

  * «три графовых опа несут legacy string post» — НЕТ. Все три объявляют
    `witness_source="model"` и возвращают `BarePost`, у которого свидетели
    лежат в `.checks`. Проба спрашивала `isinstance(post, (list, tuple))`,
    получала False и НАЗЫВАЛА это «legacy string». Утверждение про причину,
    прочитанное с типа;
  * «`create_stairs` не имеет записи в таблице эмиттеров» — верно, но вывод
    «непроверяем» НЕТ: `certify_op` разбирает сольные опы отдельной веткой
    (`spec.SOLO_OPS`) и выдаёт `proven=True` на 5 клаузулах;
  * «три опа нагрузок отказывают по построению» — верно на 2024+, но проба
    пробовала ТОЛЬКО одну версию. На 2021-2023 они эмитируют и
    сертифицируются `proven=True`.

Итог: архитектурной работы там не было ВОВСЕ, а был отчёт, в котором
«не проверен», «непроверяем» и «не дошли» читались одинаково — молчанием.
Этот файл существует, чтобы такого отчёта больше не было.

ТРИ СОСТОЯНИЯ, И КАЖДОЕ ПЕЧАТАЕТСЯ:

  VERIFIED      — база зелена, и вырезание КАЖДОГО свидетеля роняет `proven`
                  (либо делает пост неконструируемым, что сильнее).
  UNCHECKABLE   — оп структурно вне мутации, и ПРИЧИНА НАЗВАНА СТРОКОЙ,
                  которую печатает сам тест, а не подразумевает читатель.
  NOT_REACHED   — корпус не строит ни одной программы с этим опом. Это НЕ
                  «здоров»: это отсутствие свидетельства, и оно обязано быть
                  видно отдельно от двух других.

ЗАКОН БАЗОВОЙ ЛИНИИ. Мутация, чей исходный сертификат УЖЕ красен, «проходит»
вхолостую: срез ничего не меняет, а отчёт зелен. Так этот оракул соврал волне
размещений 11.08. Поэтому зелёная база проверяется ПЕРЕД каждым срезом, и её
отсутствие — отдельное состояние, а не тихий пропуск.
"""
from __future__ import annotations

import os
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(),
                                   "kir_l6_states_queue.jsonl"))

from kukai.ir import ground as ground_mod, spec                  # noqa: E402
from kukai.ir import translation_cert as tc                      # noqa: E402
from kukai.ir.authoring import _EMITTERS, _SOLO_PROGRAMS         # noqa: E402
from kukai.ir.compiler import _parse_and_check                   # noqa: E402
from kukai.ir.emit_model import BarePost                         # noqa: E402
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT as SNAP      # noqa: E402
from kukai.ir.tests.test_emitter_scope_contract import (         # noqa: E402
    PROGRAMS as SCOPE)
from kukai.ir.tests.test_golden import PROGRAMS as GOLDEN        # noqa: E402

VERIFIED = "verified"
UNCHECKABLE = "structurally-uncheckable"
NOT_REACHED = "not-reached"

#: Опы, которые мутации НЕДОСТУПНЫ по устройству, и почему. Причина едет в
#: отчёт ДОСЛОВНО: «непроверяем» без причины неотличимо от «забыли».
#:
#: Список ЗАКРЫТ тестом ниже: оп, попавший сюда без строки, роняет прогон, а
#: оп со строкой, который на самом деле мутируется, роняет его тоже — иначе
#: запись пережила бы свою правду, как это уже дважды случалось в tool_doc.
_UNCHECKABLE_REASONS: dict[str, str] = {
    # ПУСТ, И ЭТО РЕЗУЛЬТАТ, А НЕ ЗАГОТОВКА.
    #
    # 11.08 здесь стоял `create_stairs` с причиной «сольный оп: пост
    # рендерится ОДНОЙ строкой, отдельной ручки на свидетеля нет».
    # Причина была ЧЕСТНОЙ и НЕВЕРНОЙ: ручка есть, просто она не там,
    # где её искали. Предположение было — `_LIVE_STUB` стоящего теста;
    # проверка по коду показала, что `_LIVE_STUB` лечит ПУСТОЙ пост, а
    # сольные опы тот тест исключает списком. Настоящий шов —
    # `authoring._SOLO_PROGRAMS`: сольный оп разряжается по МАРКЕРУ в
    # тексте программы, значит вырезать свидетеля = убрать строки с
    # его маркерами (`_solo_survivors` ниже).
    #
    # Замер после правки: у обоих сольных опов КАЖДОЕ обязательное
    # обязательство обнаруживается срезом. Единственный «выживший» —
    # `create_stairs.spiral_path` на ПРЯМОМ марше, где он
    # `required=False`; на винтовом он обязателен и обнаруживается.
    # Это правильное поведение условного обязательства, а не дыра.
    #
    # ЧЕСТНАЯ ОГОВОРКА О СИЛЕ ЭТОГО СРЕЗА: сольный оп разряжается
    # ПОИСКОМ ПОДСТРОКИ, поэтому «вырезать свидетеля» и «вырезать то,
    # что ищет сертификат» — один и тот же поступок. Срез доказывает,
    # что обязательство привязано к конкретному тексту, но НЕ то, что
    # этот текст исполним, — последнее у модельного пути даёт ключ.
    # Разница названа здесь, чтобы «проверен» у сольного и у
    # модельного опа не читались как одинаково сильные.
}


def _grounded_corpus():
    """{оп: (узел, имя программы)} по обоим корпусам."""
    out: dict[str, tuple[dict, str]] = {}
    for corpus in (SCOPE, GOLDEN):
        for pname, prog in corpus.items():
            body = {k: v for k, v in prog.items() if not k.startswith("__")}
            try:
                grounded = ground_mod.ground(_parse_and_check(body), SNAP)
            except Exception:
                continue
            for node in grounded:
                name = node.get("op")
                if name in spec.OPS and name not in out:
                    out[name] = (dict(node), pname)
    return out


def _checks_of(post):
    """Свидетели, ЧЕМ БЫ ни был конверт.

    `BarePost` — не список и не строка; проба обхода 11.08 приняла его за
    «legacy string post» и объявила три графовых опа непроверяемыми. Конверт
    распаковывается ЗДЕСЬ, в одном месте, и только здесь."""
    if isinstance(post, BarePost):
        return list(post.checks)
    if isinstance(post, (list, tuple)):
        return list(post)
    return None


def _emittable_version(name, node):
    """Первая версия, на которой оп ЭМИТИРУЕТ, и причина, если ни одной.

    Оп с осью версий (свободные нагрузки сняты Autodesk после 2023) на
    «своей» версии проверяем полностью, а на чужой отвечает типизированным
    отказом — и это РАЗНЫЕ факты, которые обязаны читаться по-разному."""
    refusals = []
    for ver in spec.REVIT_VERSIONS:
        try:
            post = _EMITTERS[name](dict(node), ver, "kir:l6")[2]
        except Exception as exc:
            refusals.append("%s:%s" % (ver, type(exc).__name__))
            continue
        if _checks_of(post):
            return ver, None
    return None, ("оп не эмитирует свидетелей ни на одной из шести версий "
                  "(%s)" % ", ".join(refusals))


def classify():
    """{оп: (состояние, деталь)} — ровно три состояния, каждое с причиной."""
    corpus = _grounded_corpus()
    verdicts: dict[str, tuple[str, str]] = {}
    for name, op_spec in sorted(spec.OPS.items()):
        if op_spec.family not in spec.WRITE_FAMILIES:
            continue
        if name in _UNCHECKABLE_REASONS:
            verdicts[name] = (UNCHECKABLE, _UNCHECKABLE_REASONS[name])
            continue
        if name not in corpus:
            verdicts[name] = (
                NOT_REACHED,
                "ни одна программа корпуса (scope + golden) не строит этот оп")
            continue
        node, pname = corpus[name]
        if name in spec.SOLO_OPS:
            # Сольный оп: ручка не в _EMITTERS, а в _SOLO_PROGRAMS.
            try:
                base = tc.certify_op(dict(node), "2026")
            except Exception as exc:
                verdicts[name] = (UNCHECKABLE,
                                  "certify_op падает: %s: %s"
                                  % (type(exc).__name__, str(exc)[:70]))
                continue
            if not base.proven:
                verdicts[name] = (
                    UNCHECKABLE,
                    "базовая линия НЕ зелена (%s) — мутации на ней "
                    "бессмысленны" % ("; ".join(base.gaps)[:90]))
                continue
            verdicts[name] = (
                VERIFIED,
                "2026: %d обязательств (сольный шов, разряд по "
                "маркеру), программа %s"
                % (len(_solo_obligations(name, node)), pname))
            continue
        if name not in _EMITTERS:
            verdicts[name] = (
                UNCHECKABLE,
                "нет записи в _EMITTERS и нет строки в _UNCHECKABLE_REASONS — "
                "состояние не названо")
            continue
        ver, why = _emittable_version(name, node)
        if ver is None:
            verdicts[name] = (UNCHECKABLE, why)
            continue
        try:
            base = tc.certify_op(dict(node), ver)
        except Exception as exc:
            verdicts[name] = (UNCHECKABLE,
                              "certify_op падает на %s: %s: %s"
                              % (ver, type(exc).__name__, str(exc)[:70]))
            continue
        if not base.proven:
            verdicts[name] = (
                UNCHECKABLE,
                "базовая линия НЕ зелена на %s (%s) — мутации на ней "
                "бессмысленны: срез ничего не меняет"
                % (ver, "; ".join(base.gaps)[:90]))
            continue
        keys = [c.obligation_key
                for c in _checks_of(_EMITTERS[name](dict(node), ver,
                                                    "kir:l6")[2])
                if c.obligation_key]
        verdicts[name] = (VERIFIED,
                          "%s: %d свидетелей, программа %s"
                          % (ver, len(keys), pname))
    return verdicts


def _solo_obligations(name, node):
    """Обязательства сольного опа, ОБЯЗАТЕЛЬНЫЕ для этой программы.

    Условное обязательство, чей операнд не назван, разряжается
    ОТСУТСТВИЕМ свидетеля — вырезать там нечего, и считать это
    выжившим значило бы обвинять правильное поведение."""
    tc._ensure_table()
    out = []
    for o in tc.REFINEMENT[name].obligations:
        if not o.witness_markers:
            continue
        if o.conditional and o.param is not None and o.param not in node:
            continue
        out.append(o)
    return out


def _solo_survivors(name, node, ver):
    """Обязательства сольного опа, чей срез НЕ уронил сертификат.

    Срез = удаление из отрендеренной программы всех строк, несущих
    маркеры этого обязательства. ВСЕ маркеры, а не первый: у связи с
    уровнем их два (`STAIRS_BASE_LEVEL_PARAM`/`..._TOP_...`), и срез
    одного оставлял второй — первая попытка 11.08 так и сообщила
    ложного выжившего."""
    original = _SOLO_PROGRAMS[name]
    out = []
    try:
        for o in _solo_obligations(name, node):
            def stripped(op, v, _ms=o.witness_markers, _o=original):
                text = _o(op, v)
                return "\n".join(
                    ln for ln in text.splitlines()
                    if not any(m in ln for m in _ms))
            _SOLO_PROGRAMS[name] = stripped
            try:
                if tc.certify_op(dict(node), ver).proven:
                    out.append(o.key or o.kind)
            except Exception:
                pass
            _SOLO_PROGRAMS[name] = original
    finally:
        _SOLO_PROGRAMS[name] = original
    return out


def _survivors(name, node, ver, keys):
    """Ключи, вырезание которых НЕ уронило сертификат."""
    original = _EMITTERS[name]
    out = []
    try:
        for cut in keys:
            def mutated(op, v, stamp, isolation="atomic", _o=original, _c=cut):
                d, c, post, r = _o(op, v, stamp, isolation)
                kept = [k for k in _checks_of(post) if k.obligation_key != _c]
                return d, c, kept, r
            _EMITTERS[name] = mutated
            try:
                if tc.certify_op(dict(node), ver).proven:
                    out.append(cut)
            except Exception:
                # Пустой пост НЕКОНСТРУИРУЕМ (render_post его отвергает) —
                # для опа с единственным свидетелем срез поднимает исключение,
                # и это ОБНАРУЖЕНИЕ более сильное, чем красный сертификат.
                pass
            _EMITTERS[name] = original
    finally:
        _EMITTERS[name] = original
    return out


class TheOracleDistinguishesThreeStates(unittest.TestCase):

    def test_no_write_op_is_silently_unclassified(self):
        verdicts = classify()
        writing = {n for n, o in spec.OPS.items()
                   if o.family in spec.WRITE_FAMILIES}
        self.assertEqual(set(verdicts), writing)
        for name, (state, detail) in sorted(verdicts.items()):
            with self.subTest(op=name):
                self.assertIn(state, (VERIFIED, UNCHECKABLE, NOT_REACHED))
                self.assertTrue(detail.strip(),
                                "%s: состояние без причины" % name)

    def test_every_uncheckable_op_names_a_printable_reason(self):
        """«Непроверяем» без причины неотличимо от «забыли». Причина обязана
        быть СТРОКОЙ, которую печатает тест, а не подразумевает читатель."""
        for name, (state, detail) in sorted(classify().items()):
            if state != UNCHECKABLE:
                continue
            with self.subTest(op=name):
                self.assertGreater(
                    len(detail), 40,
                    "%s: причина слишком коротка, чтобы что-то объяснить"
                    % name)
                self.assertNotIn("состояние не названо", detail,
                                 "%s: оп вне мутации и вне журнала причин"
                                 % name)

    def test_the_reason_ledger_has_not_outlived_its_truth(self):
        """Запись «непроверяем» обязана падать, когда оп СТАЛ проверяем —
        иначе она переживёт свою правду, как дважды случилось в tool_doc."""
        corpus = _grounded_corpus()
        for name in sorted(_UNCHECKABLE_REASONS):
            with self.subTest(op=name):
                self.assertIn(name, spec.OPS)
                if name in _EMITTERS and name in corpus:
                    ver, _why = _emittable_version(name, corpus[name][0])
                    self.assertIsNone(
                        ver,
                        "%s теперь эмитирует свидетелей на %s — запись в "
                        "_UNCHECKABLE_REASONS устарела" % (name, ver))

    def test_every_verified_op_loses_proven_when_a_witness_is_cut(self):
        """ЗАКОН L6 на ЗЕЛЁНОЙ базе. Срез каждого свидетеля обязан уронить
        `proven`; выживший — свидетель, которого сертификат не требует."""
        from kukai.ir.tests.test_tolerance_provenance import (
            _UNPROMISED_WITNESSES)
        corpus = _grounded_corpus()
        for name, (state, detail) in sorted(classify().items()):
            if state != VERIFIED:
                continue
            ver = detail.split(":")[0]
            node = corpus[name][0]
            if name in spec.SOLO_OPS:
                with self.subTest(op=name, version=ver, seam="solo"):
                    self.assertEqual(
                        _solo_survivors(name, node, ver), [],
                        "%s: обязательство пережило вырезание своих "
                        "маркеров" % name)
                continue
            keys = [c.obligation_key
                    for c in _checks_of(_EMITTERS[name](dict(node), ver,
                                                        "kir:l6")[2])
                    if c.obligation_key]
            with self.subTest(op=name, version=ver):
                unexplained = [k for k in _survivors(name, node, ver, keys)
                               if (name, k) not in _UNPROMISED_WITNESSES]
                self.assertEqual(
                    unexplained, [],
                    "%s: свидетели пережили вырезание и не названы в "
                    "_UNPROMISED_WITNESSES: %s" % (name, unexplained))

    def test_the_solo_ops_are_verified_through_their_own_seam(self):
        """Предположение «шов — это `_LIVE_STUB`» было НЕВЕРНО: та
        заглушка лечит ПУСТОЙ пост, а сольные опы стоящий тест исключает
        списком. Настоящий шов — `_SOLO_PROGRAMS`."""
        verdicts = classify()
        for name in sorted(spec.SOLO_OPS):
            with self.subTest(op=name):
                self.assertEqual(verdicts[name][0], VERIFIED,
                                 "%s: %s" % (name, verdicts[name][1]))
                self.assertIn("сольный шов", verdicts[name][1])

    def test_the_graph_ops_are_verified_not_skipped(self):
        """Опы с плечом «один оп → много элементов»: цена невидимого дефекта
        у них выше всего. Проба 11.08 объявила их непроверяемыми, приняв
        `BarePost` за строку; этот тест держит обратное."""
        verdicts = classify()
        for name in ("create_pipe_system", "route_pipe_system",
                     "route_duct_system"):
            with self.subTest(op=name):
                self.assertEqual(verdicts[name][0], VERIFIED,
                                 "%s: %s" % (name, verdicts[name][1]))

    def test_version_gated_ops_are_verified_on_a_version_that_emits(self):
        """«Отказывает намеренно на 2024+» и «не проверен» — разные факты.
        Оракул обязан искать версию, на которой оп ВЫРАЗИМ."""
        verdicts = classify()
        for name in ("create_point_load", "create_line_load",
                     "create_area_load"):
            with self.subTest(op=name):
                self.assertEqual(verdicts[name][0], VERIFIED,
                                 "%s: %s" % (name, verdicts[name][1]))


if __name__ == "__main__":
    for _n, (_s, _d) in sorted(classify().items()):
        print("%-14s %-28s %s" % (_s, _n, _d))
