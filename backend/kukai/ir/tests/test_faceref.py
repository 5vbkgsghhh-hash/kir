"""ВТОРАЯ СТУПЕНЬ СЕЛЕКТОРА: программа НАЗЫВАЕТ грань (`kukai/ir/faceref.py`).

Что здесь доказывается, по разделам:

  FlagOffIsAbsentTests        выключенный флаг НЕОТЛИЧИМ от отсутствия формы
  GrammarTests                форма и её отказы — каждый называет СВОЮ причину
  NoSilentPickTests           ноль и «несколько» — отказы, а не выбор
  CoherenceWithFrozenDialectTests   вложенный `by=ref` виден ВСЕМ обходам
  WitnessTests                свидетель читает РЕЗУЛЬТАТ и не вакуумен
  InstrumentTests             флаг ВИДЕН прибору (иначе он на складе)

ЧЕГО ЗДЕСЬ НЕТ И ПОЧЕМУ. Живого Revit. Отказы «нет кандидата» и «кандидатов
несколько» — РАНТАЙМНЫЕ: их принимает C# внутри Revit, и офлайн проверяется
ровно то, что проверяемо офлайн, — что отказ ЭМИТИРОВАН, типизирован, привязан
к опу и отрендерен в форме своей изоляции. Утверждать здесь, что они сработали,
значило бы подписывать ось, которую никто не читал.
"""
from __future__ import annotations

import os
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_test_queue.jsonl"))

from kukai.ir import faceref                                  # noqa: E402
from kukai.ir.compiler import compile_program                 # noqa: E402
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT as SNAP   # noqa: E402




IN_VIEW = {"by": "element_id", "value": 900}
REF_W1 = {"by": "ref", "value": "W1"}
REF_W2 = {"by": "ref", "value": "W2"}
PINNED = {"by": "element_id", "value": 12345}


def wall(oid="W1", **kw):
    op = {"op": "create_wall", "id": oid, "p0_mm": [0, 0], "p1_mm": [6000, 0],
          "level": {"by": "name", "value": "Этаж 1"}}
    op.update(kw)
    return op


def face(of, **pred):
    return {"by": "face", "of": of, "predicate": pred}


def dim(refs, oid="D1"):
    return {"op": "create_dimension", "id": oid, "in_view": IN_VIEW,
            "refs": refs, "line_at": [3000, 500]}


def prog(ops):
    return {"ir_version": "1.0", "intent": "face-test", "ops": ops}


def build(ops, ver="2023", isolation="atomic"):
    return compile_program(prog(ops), revit_version=ver, snapshot=SNAP,
                           bulk=True, isolation=isolation)


class _FlagOn:
    """Флаг оператора ВКЛ на время теста — и снят после, чем бы ни кончилось."""

    def __enter__(self):
        self._old = os.environ.get(faceref.FACE_REF_FLAG)
        os.environ[faceref.FACE_REF_FLAG] = "1"
        return self

    def __exit__(self, *exc):
        if self._old is None:
            os.environ.pop(faceref.FACE_REF_FLAG, None)
        else:
            os.environ[faceref.FACE_REF_FLAG] = self._old
        return False


TWO_WALLS = [wall("W1"), wall("W2", p0_mm=[0, 4000], p1_mm=[6000, 4000])]
NAMED = TWO_WALLS + [dim([face(REF_W1, side="exterior"),
                          face(REF_W2, side="exterior")])]
PLAIN = TWO_WALLS + [dim([REF_W1, REF_W2])]


class FlagOffIsAbsentTests(unittest.TestCase):
    """ЗАКОН: отсутствующее остаётся отсутствующим.

    Флаг по умолчанию ВЫКЛ, и выключенным он обязан быть неотличим от того,
    что формы нет вовсе, — иначе «выключено» означает «включено чуть-чуть»."""

    def test_flag_is_off_by_default(self):
        os.environ.pop(faceref.FACE_REF_FLAG, None)
        self.assertFalse(faceref.face_ref_enabled())

    def test_program_without_faces_is_byte_identical(self):
        os.environ.pop(faceref.FACE_REF_FLAG, None)
        off = build(PLAIN)
        with _FlagOn():
            on = build(PLAIN)
        self.assertTrue(off.ok and on.ok)
        # ПОБАЙТОВО, а не «эквивалентно»: любая разница в тексте — это разница
        # в program_digest, то есть другая программа под той же подписью.
        self.assertEqual(off.csharp, on.csharp)

    def test_named_face_refused_while_flag_is_off(self):
        os.environ.pop(faceref.FACE_REF_FLAG, None)
        out = build(NAMED)
        self.assertFalse(out.ok)
        codes = {d.code for d in out.diagnostics}
        self.assertIn("KIR-G002", codes)
        # Отказ обязан НАЗВАТЬ флаг: «форма не принята» без имени калитки
        # отправляет читать исходники.
        self.assertTrue(any(faceref.FACE_REF_FLAG in d.message_ru
                            for d in out.diagnostics))

    def test_helpers_absent_from_emission_without_named_face(self):
        with _FlagOn():
            out = build(PLAIN)
        self.assertTrue(out.ok)
        for token in ("__faceWalk_", "__faceKeep_", "__fbWant_"):
            self.assertNotIn(token, out.csharp)

    def test_decode_schema_is_byte_identical_while_flag_is_off(self):
        # Схема ограниченного декода fail-closed: пока варианта в ней нет,
        # модель физически не может выдать селектор грани.
        import json
        from kukai.ir import schema_gen, spec

        def rendered() -> str:
            return json.dumps(schema_gen._op_schema(
                spec.OPS["create_dimension"]), sort_keys=True)

        os.environ.pop(faceref.FACE_REF_FLAG, None)
        off = rendered()
        with _FlagOn():
            on = rendered()
        self.assertNotIn(faceref.BY_FACE, off)
        self.assertIn(faceref.BY_FACE, on)
        os.environ.pop(faceref.FACE_REF_FLAG, None)
        self.assertEqual(off, rendered())


class GrammarTests(unittest.TestCase):
    """Форма второй ступени и её отказы. Каждый отказ называет СВОЮ причину."""

    def _refuse(self, refs):
        with _FlagOn():
            out = build(TWO_WALLS + [dim(refs)])
        self.assertFalse(out.ok, "форма должна была быть отвергнута")
        return " | ".join(d.message_ru for d in out.diagnostics)

    def test_accepts_the_whole_form(self):
        with _FlagOn():
            out = build(NAMED)
        self.assertTrue(out.ok, [d.message_ru for d in out.diagnostics])

    def test_of_carries_a_whole_selector_not_a_bare_op_id(self):
        # Это и есть главное решение файла: `of` — СЕЛЕКТОР, а не строка.
        msg = self._refuse([{"by": "face", "of": "W1",
                             "predicate": {"side": "exterior"}}, REF_W2])
        self.assertIn(".of", msg)

    def test_unknown_key_in_selector(self):
        msg = self._refuse([{"by": "face", "of": REF_W1,
                             "predicate": {"side": "exterior"},
                             "index": 0}, REF_W2])
        self.assertIn("index", msg)

    def test_predicate_is_required(self):
        msg = self._refuse([{"by": "face", "of": REF_W1}, REF_W2])
        self.assertIn("predicate", msg)

    def test_empty_predicate_is_refused(self):
        # Описание, которому отвечает КАЖДАЯ грань, — не имя грани.
        msg = self._refuse([face(REF_W1), REF_W2])
        self.assertIn("predicate", msg)

    def test_unknown_predicate_key(self):
        msg = self._refuse([face(REF_W1, largest=True), REF_W2])
        self.assertIn("largest", msg)

    def test_side_is_a_closed_enum_named_by_revit(self):
        msg = self._refuse([face(REF_W1, side="outside"), REF_W2])
        for name in faceref.SIDES:
            self.assertIn(name, msg)

    def test_normal_must_be_three_numbers(self):
        for bad in ([0, 0], [0, 0, "z"], "up", [0, 0, True]):
            with self.subTest(bad=bad):
                msg = self._refuse([face(REF_W1, normal=bad), REF_W2])
                self.assertIn("normal", msg)

    def test_two_identical_face_selectors_are_a_zero_size_dimension(self):
        msg = self._refuse([face(REF_W1, side="exterior"),
                            face(REF_W1, side="exterior")])
        self.assertIn("повтор", msg.lower())

    def test_two_different_faces_of_one_element_are_legal(self):
        # Ключ тождества включает ПРЕДИКАТ, иначе две разные грани одной
        # стены читались бы как повтор — и осмысленный размер был бы отвергнут.
        with _FlagOn():
            out = build([wall("W1"),
                         dim([face(REF_W1, side="exterior"),
                              face(REF_W1, side="interior")])])
        self.assertTrue(out.ok, [d.message_ru for d in out.diagnostics])

    def test_carrier_is_a_named_list_not_the_param_kind(self):
        # `move_elements.targets` — тот же род `refs_w`, но «подвинуть грань»
        # не значит ничего. Форма разрешена поимённо, а не по роду.
        with _FlagOn():
            out = build([wall("W1"),
                         {"op": "move_elements", "id": "M1",
                          "targets": [face(REF_W1, side="exterior")],
                          "delta_mm": [100, 0, 0]}])
        self.assertFalse(out.ok)
        self.assertTrue(any("create_dimension.refs" in d.message_ru
                            for d in out.diagnostics),
                        [d.message_ru for d in out.diagnostics])


class NoSilentPickTests(unittest.TestCase):
    """ЗАКОН: описание ФИЛЬТРУЕТ, решает МОЩНОСТЬ. Ноль и «несколько» — отказы.

    Живой замер 02.08 (Snowdon, парный опыт): плечо C# взяло `.FirstOrDefault()`
    — 1 тип двери из 62 — и построило МОЛЧА. Эти тесты держат обе границы."""

    def _cs(self, isolation="atomic"):
        with _FlagOn():
            out = build(NAMED, isolation=isolation)
        self.assertTrue(out.ok, [d.message_ru for d in out.diagnostics])
        return out.csharp

    def test_no_candidate_is_a_typed_op_bound_refusal(self):
        cs = self._cs()
        self.assertIn("Count == 0", cs)
        self.assertIn("нет грани, отвечающей описанию", cs)
        # Отказ повторяет ОПИСАНИЕ: «грань не найдена» без него отправляет
        # автора перечитывать собственную программу.
        self.assertIn("сторона «exterior»", cs)

    def test_ambiguity_is_a_refusal_that_names_the_count(self):
        cs = self._cs()
        self.assertIn("Count > 1", cs)
        self.assertIn("Count.ToString()", cs)
        self.assertIn("Компилятор НЕ выбирает за автора", cs)
        # НАЗВАННЫЙ СЛЕДУЮЩИЙ ХОД, а не только диагноз.
        self.assertIn("СЛЕДУЮЩИЙ ХОД", cs)

    def test_both_refusals_render_in_the_form_their_isolation_needs(self):
        # У отказа ОДИН владелец (`emit_utils.refuse_stmt`). Напечатанный
        # руками, он в `per_op` откатил бы соседей — дефект, закрытый 28.07.
        atomic = self._cs("atomic")
        per_op = self._cs("per_op")
        self.assertIn("__t.RollBack(); return __Refuse(", atomic)
        self.assertNotIn("throw __OpRefuse(", atomic)
        self.assertIn("throw __OpRefuse(", per_op)

    def test_the_walk_counts_and_never_stops_at_the_first_hit(self):
        # Ранний выход превратил бы «их две» в «взял первую»: у `Solid.Faces`
        # порядок НЕ документирован, поэтому «первая подходящая» — число без
        # смысла. Мощность множества от порядка перебора не зависит.
        cs = self._cs()
        walk = cs[cs.index("void __faceWalk_"):]
        walk = walk[:walk.index("void __faceKeep_")] if "void __faceKeep_" in walk else walk
        self.assertNotIn("FirstOrDefault", cs)
        self.assertNotIn("break;", walk)

    def test_no_invented_tolerance_anywhere_in_the_emitted_comparison(self):
        # Параллельность — РОДНЫМ тестом Revit. Ни одного числа своего.
        cs = self._cs()
        self.assertIn("IsZeroLength()", cs)
        self.assertIn("CrossProduct", cs)
        walk = cs[cs.index("void __faceKeep_"):cs.index("void __faceWalk_")]
        for invented in ("1e-", "0.0001", "0.001", "Math.Abs("):
            self.assertNotIn(invented, walk)

    def test_symbol_geometry_not_instance_geometry(self):
        # Ловушка ветки аннотаций (`9c5c7492`): `GetInstanceGeometry()`
        # компилируется 6/6 и отказывает ЖИВЬЁМ — это документированная КОПИЯ,
        # чьи ссылки непригодны для создания элементов.
        cs = self._cs()
        self.assertIn("GetSymbolGeometry()", cs)
        self.assertNotIn("GetInstanceGeometry", cs)
        # Координаты возвращаются в модель трансформацией экземпляра.
        self.assertIn(".Multiply(__fwGi.Transform)", cs)


class CoherenceWithFrozenDialectTests(unittest.TestCase):
    """Вложенный `{"by": "ref"}` обязан быть виден ВСЕМ обходам ссылок.

    Ради этого `of` и несёт целый селектор вместо голого id опа. Родовые
    обходы (`design_check._ref_targets`, `course._mark_cross_phase`) спускаются
    в любой вложенный словарь; обход графа компилятора — НЕ родовой, и его
    пришлось научить. Здесь проверены обе стороны."""

    FACE_SEL = face(REF_W1, side="exterior")

    def test_generic_ref_walk_finds_the_nested_ref(self):
        from kukai.ir.design_check import _ref_targets
        self.assertEqual(_ref_targets(self.FACE_SEL), ["W1"])
        self.assertIn("W1", _ref_targets(dim([self.FACE_SEL, REF_W2])))

    def test_dag_sees_the_edge_dangling_ref_is_refused(self):
        with _FlagOn():
            out = build([wall("W1"),
                         dim([face({"by": "ref", "value": "NOPE"},
                                   side="exterior"), REF_W1])])
        self.assertFalse(out.ok)
        self.assertIn("KIR-L003", {d.code for d in out.diagnostics})

    def test_dag_sees_the_edge_forward_ref_is_refused(self):
        # Ссылка ВПЕРЁД: оп-производитель стоит ПОЗЖЕ. Без ребра графа это
        # прошло бы молча, а C# сослался бы на ещё не объявленную переменную.
        with _FlagOn():
            out = build([dim([face(REF_W1, side="exterior"), PINNED]),
                         wall("W1")])
        self.assertFalse(out.ok)
        self.assertIn("KIR-L003", {d.code for d in out.diagnostics})

    def test_bundle_contract_refuses_a_cross_program_face_ref(self):
        # Тот же закон, что и для ступени 1, и БЕЗ ЕДИНОЙ ПРАВКИ в
        # `design_check`: соседняя программа пачки — отдельная транзакция, и к
        # её исполнению id уже не существует. Голая строка в `of` прошла бы
        # здесь молча — и висячая ссылка уехала бы в исполнение.
        from kukai.ir.design_check import _merge_bundle, BundleContractError
        with self.assertRaises(BundleContractError) as caught:
            _merge_bundle([[wall("W1")], [dim([self.FACE_SEL, PINNED])]])
        self.assertIn("W1", str(caught.exception))

    def test_inner_ref_is_normalised_like_a_grade_one_selector(self):
        # Пробелы вокруг id обрезает ступень 1; необрезанная ступень 2 дала бы
        # KIR-L003 на ссылке, которая указывает верно.
        with _FlagOn():
            out = build([wall("W1"),
                         dim([face({"by": "ref", "value": "  W1  "},
                                   side="exterior"),
                              face({"by": "ref", "value": "W1"},
                                   side="interior")])])
        self.assertTrue(out.ok, [d.message_ru for d in out.diagnostics])

    def test_selection_closure_keeps_the_producing_op(self):
        from kukai.live.transfer import refs_of
        edges = refs_of(dim([self.FACE_SEL, REF_W2]))
        self.assertIn(("refs[0].of", "W1"), edges)
        self.assertIn(("refs[1]", "W2"), edges)

    def test_ground_never_sees_the_second_grade(self):
        # `refs` не входит в `ospec.grounded` — вторая ступень живёт целиком в
        # полосе целей записи, куда ground не заглядывает. Если это перестанет
        # быть правдой, тест упадёт здесь, а не живьём.
        from kukai.ir import spec
        grounded = {p for p, _pool, _req in spec.OPS["create_dimension"].grounded}
        self.assertNotIn("refs", grounded)


class WitnessTests(unittest.TestCase):
    """Что свидетель МОЖЕТ и чего НЕ МОЖЕТ сказать о названной грани."""

    def test_named_face_adds_a_check_that_reads_the_result(self):
        with _FlagOn():
            out = build(NAMED)
        cs = out.csharp
        # Читается ПОСТРОЕННЫЙ размер, а не то, что вызов состоялся.
        self.assertIn("__el_D1.References", cs)
        self.assertIn("ConvertToStableRepresentation(doc)", cs)
        self.assertIn("named face is not among the built dimension References", cs)

    def test_the_check_is_absent_when_it_would_be_vacuous(self):
        # Проверка, которая не может провалиться, хуже отсутствующей. Без
        # названной грани список ожидаемых подписей был бы ПУСТ, и проверка
        # была бы зелена всегда — поэтому её просто нет.
        with _FlagOn():
            out = build(PLAIN)
        self.assertNotIn("named face is not among", out.csharp)
        self.assertNotIn("__fbWant_", out.csharp)

    def test_unreadable_signature_fails_the_witness_not_passes_it(self):
        # `catch` СНИМАЕТ ФЛАГ, а не глотает: проглоченное чтение сделало бы
        # проверку непроваливаемой.
        with _FlagOn():
            cs = build(NAMED).csharp
        self.assertIn("catch { __fbOk_D1 = false; }", cs)
        self.assertIn("!__fbRead_D1 ||", cs)

    def test_owner_level_witness_alone_cannot_speak_about_a_face(self):
        # Соседняя проверка читает `Reference.ElementId` — ВЛАДЕЛЬЦА ссылки.
        # Она одинаково зелена, к какой бы грани того же элемента размер ни
        # привязался; именно поэтому названной грани нужна своя.
        with _FlagOn():
            named = build(NAMED).csharp
            plain = build(PLAIN).csharp
        for cs in (named, plain):
            self.assertIn("References do not match requested refs", cs)


class InstrumentTests(unittest.TestCase):
    """Флаг, которого прибор не видит, лежит на складе ПО ПОСТРОЕНИЮ."""

    def test_flag_name_constant_matches_the_literal_in_the_gate(self):
        # `tools/capability_map.py` ищет флаги регуляркой по ТЕКСТУ
        # `os.getenv("ИМЯ")`; вызов через константу инвентарь не увидит.
        # Поэтому имя написано дважды, и что копии не разъехались — держит
        # этот тест, а не договорённость.
        import inspect
        src = inspect.getsource(faceref.face_ref_enabled)
        self.assertIn(f'os.getenv("{faceref.FACE_REF_FLAG}"', src)

    def test_gate_is_a_zero_arg_bool_predicate(self):
        # Вторая половина той же регулярки: `def имя() -> bool:`.
        import inspect
        sig = inspect.signature(faceref.face_ref_enabled)
        self.assertEqual(len(sig.parameters), 0)
        # `from __future__ import annotations` -> аннотация приезжает СТРОКОЙ,
        # и регулярка прибора читает ровно её.
        self.assertIn(sig.return_annotation, (bool, "bool"))


if __name__ == "__main__":
    unittest.main()
