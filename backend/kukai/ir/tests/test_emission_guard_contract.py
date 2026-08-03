"""Контракт гарда эмиссии: отказ ОДНОГО опа больше не набирается фразой.

До 28.07.2026 форму отказа выбирала ПОСТ-ОБРАБОТКА эмиссии::

    body = create.replace("__t.RollBack(); return __Refuse(",
                          "throw __OpRefuse(")

то есть вера в дословность фразы, набранной руками в 105 местах четырёх
файлов.  Эмиттер, написавший гард иначе — лишний пробел, свой порядок
вызовов, отказ внутри ``catch`` — молча сохранял семантику ЦЕЛОЙ ПРОГРАММЫ
внутри SubTransaction: отказ одного опа откатывал уже закоммиченных соседей.
Замерено на этой же ветке до правок (все четыре мутации проходили молча).

Теперь форму выбирает единственный владелец фразы —
``emit_utils.refuse_stmt(oid, message_cs, isolation)`` — а
``_wrap_create_per_op`` не переписывает C# вовсе и ОТКАЗЫВАЕТ (KIR-E005),
если в теле операции уцелел хоть один общепрограммный откат.

Этот файл держит контракт с четырёх сторон:

  1. владение фразой (статически: рукописной последовательности в исходниках
     эмиттеров нет);
  2. эквивалентность снятому механизму (per_op-тело каждой операции
     байт-в-байт равно тому, что давал ``replace`` — эталон миграции);
  3. мутационные стражи (эмиттер, набравший фразу рукой, обязан быть пойман —
     включая токенно-эквивалентные написания);
  4. данные ≠ код (id операции и пользовательский текст, дословно
     совпадающие с фразой, НЕ обязаны валить эмиссию).

Плюс отдельно: sentinel-тип отказа (управляемый отказ отличим от поломки
Revit API) и позитивные контракты каркаса и лестницы — они в контракт
op-локального гарда не входят и обязаны продолжать откатывать транзакцию.
"""
from __future__ import annotations

import ast
import os
import pathlib
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_guard_queue.jsonl"))

from kukai.ir import authoring  # noqa: E402
from kukai.ir import ground as ground_mod  # noqa: E402
from kukai.ir.authoring import (  # noqa: E402
    _EMITTERS, _program_stamp, emit_program,
)
from kukai.ir.compiler import _parse_and_check, compile_program  # noqa: E402
from kukai.ir.diag import KirRefusal  # noqa: E402
from kukai.ir.emit_model import post_to_string  # noqa: E402
from kukai.ir.emit_utils import (  # noqa: E402
    cs_code_only, cs_dense_code, program_refusal_tokens, refuse_stmt,
)
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT  # noqa: E402

VERSIONS = ("2021", "2022", "2023", "2024", "2025", "2026")
GUARD_CONTRACT_CODE = "KIR-E005"
#: фраза, которую снятая пост-обработка искала и переписывала
LEGACY_PHRASE = "__t.RollBack(); return __Refuse("
LEGACY_THROW = "throw __OpRefuse("

_LVL = {"by": "name", "value": "Этаж 1"}
_LVL_ID = {"by": "element_id", "value": 42}
_G_LVL = {"__grounded__": {"id": 42, "name": None, "via": "element_id"}}
_G_LVL2 = {"__grounded__": {"id": 43, "name": None, "via": "element_id"}}
_G_DEF = {"__grounded__": {"id": None, "name": None, "via": "doc_default",
                           "in_emit": "__doc_default__"}}


def _g(pid, name):
    return {"__grounded__": {"id": pid, "name": name, "via": "element_id"}}


# ── корпус, построенный ОТ ИНВЕНТАРЯ guard-site (ревью №10) ─────────────────
#
# Замерено трассировкой строк по всем эмиттерам: замороженный корпус паритета
# (голдены + scope-фикстуры + ворота + PBT, шесть версий, обе изоляции) не
# доходил до 11 guard-site из 105 — ветки типа «по имени», вертикаль колонны,
# in_view по ссылке, прямой стык труб, тип по умолчанию у плиты фундамента.
# Тест, не доходящий до guard-site, не может ничего о нём утверждать, поэтому
# корпус достроен до 104 из 105 программой (последний — «in_view по ссылке» —
# был программой недостижим, см. GuardSitesUnreachableThroughAProgram).
# ЗАКРЫТО (28.07): этот guard-site больше не существует вовсе — in_view: ref
# теперь ТИПИЗИРОВАННЫЙ отказ до эмиссии (authoring._annot_view_res), не
# refuse_stmt; инвентарь сузился со 105 до 104, и весь он программой
# достижим. create_group собран из ЧЛЕНОВ РАЗНЫХ ТИПОВ: он вкладывает тела
# чужих эмиттеров, и какие guard-site внутри него существуют — решает тип
# участника, а не сам оп группы.
PROGRAMS: dict[str, dict] = {
    "floor_typed": {
        "ir_version": "1.0", "intent": "плита с типом и смещением", "ops": [
            {"op": "create_floor", "id": "FT1",
             "outline": [[0, 0], [8000, 0], [8000, 6000], [0, 6000]],
             "level": _LVL, "type": {"by": "name", "value": "Монолит 200"},
             "height_offset_mm": 150.0},
        ]},
    "column_vertical": {
        "ir_version": "1.0", "intent": "колонна с вертикалью", "ops": [
            {"op": "create_column", "id": "CV1", "xy": [4000, 3000],
             "level": _LVL_ID, "base_offset_mm": -300.0,
             "top_level": {"by": "element_id", "value": 43},
             "top_offset_mm": 250.0},
        ]},
    "roof_typed": {
        "ir_version": "1.0", "intent": "кровля с типом", "ops": [
            {"op": "create_roof", "id": "RT1",
             "outline": [[0, 0], [8000, 0], [8000, 6000], [0, 6000]],
             "level": _LVL, "type": {"by": "element_id", "value": 1234}},
        ]},
    "contour_typed": {
        "ir_version": "1.0", "intent": "плита по контуру с типом", "ops": [
            {"op": "create_floor_by_contour", "id": "FC9",
             "contour": {"outer": {"shape": "rect", "origin": [0, 0],
                                   "size_mm": [8000, 6000]}},
             "level": _LVL, "type": {"by": "name", "value": "Монолит 200"}},
        ]},
    "pipe_straight_same_diameter": {
        "ir_version": "1.0", "intent": "прямой стык одного диаметра", "ops": [
            {"op": "create_pipe_system", "id": "SS1", "level": _LVL,
             "nodes": [{"id": "N1", "xyz_mm": [0, 0, 3000]},
                       {"id": "N2", "xyz_mm": [3000, 0, 3000]},
                       {"id": "N3", "xyz_mm": [6000, 0, 3000]}],
             "segments": [{"from": "N1", "to": "N2", "diameter_mm": 100},
                          {"from": "N2", "to": "N3", "diameter_mm": 100}]},
        ]},
    "pipe_straight_reducer": {
        "ir_version": "1.0", "intent": "переход диаметра на прямом стыке",
        "ops": [
            {"op": "route_pipe_system", "id": "SR1", "level": _LVL_ID,
             "nodes": [{"id": "N1", "xyz_mm": [0, 0, 3000]},
                       {"id": "N2", "xyz_mm": [3000, 0, 3000]},
                       {"id": "N3", "xyz_mm": [6000, 0, 3000]}],
             "segments": [{"from": "N1", "to": "N2", "diameter_mm": 100},
                          {"from": "N2", "to": "N3", "diameter_mm": 50}]},
        ]},
    "duct_straight": {
        "ir_version": "1.0", "intent": "воздуховод прямой", "ops": [
            {"op": "route_duct_system", "id": "SD1", "level": _LVL_ID,
             "diameter_mm": 250,
             "nodes": [{"id": "N1", "xyz_mm": [0, 0, 3000]},
                       {"id": "N2", "xyz_mm": [3000, 0, 3000]},
                       {"id": "N3", "xyz_mm": [6000, 0, 3000]}],
             "segments": [{"from": "N1", "to": "N2"},
                          {"from": "N2", "to": "N3"}]},
        ]},
    "group_mixed_members": {
        "ir_version": "1.0", "intent": "группа из членов разных типов",
        "ops": [{
            "op": "create_group", "id": "GRPX", "name": "Смешанная",
            "members": [
                {"op": "create_wall", "id": "MW", "p0_mm": [0, 0],
                 "p1_mm": [6000, 0], "level": _G_LVL, "height_mm": 3000.0,
                 "type": _G_DEF},
                {"op": "create_floor", "id": "MF",
                 "outline": [[0, 0], [6000, 0], [6000, 4000], [0, 4000]],
                 "level": _G_LVL, "type": _G_DEF, "height_offset_mm": 100.0},
                {"op": "create_foundation", "id": "MFS", "variety": "slab",
                 "outline": [[0, 0], [6000, 0], [6000, 4000], [0, 4000]],
                 "level": _G_LVL, "type": _G_DEF},
                {"op": "create_foundation", "id": "MFI", "variety": "isolated",
                 "xy": [3000, 2000], "level": _G_LVL,
                 "symbol": _g(1101, "Фундамент 1500x1500")},
                {"op": "create_roof", "id": "MR",
                 "outline": [[0, 0], [6000, 0], [6000, 4000], [0, 4000]],
                 "level": _G_LVL, "type": _G_DEF},
                {"op": "create_column", "id": "MC", "xy": [1000, 1000],
                 "level": _G_LVL, "symbol": _g(500, "К 300x300"),
                 "base_offset_mm": -200.0, "top_level": _G_LVL2},
                {"op": "create_beam", "id": "MB", "p0_mm": [0, 0, 3000],
                 "p1_mm": [6000, 0, 3000], "level": _G_LVL,
                 "symbol": _g(1100, "Балка 200x400")},
                {"op": "create_pipe", "id": "MP", "p0_mm": [0, 0, 2700],
                 "p1_mm": [3000, 0, 2700], "level": _G_LVL,
                 "diameter_mm": 50, "system_type": _g(300, "ХВС"),
                 "pipe_type": _g(200, "Стандарт")},
                {"op": "create_duct", "id": "MD", "p0_mm": [0, 500, 3000],
                 "p1_mm": [6000, 500, 3000], "level": _G_LVL,
                 "system_type": _g(1001, "Приточная"),
                 "duct_type": _g(1000, "Прямоугольный стандарт")},
                {"op": "create_cable_tray", "id": "MT", "p0_mm": [0, 900, 3000],
                 "p1_mm": [6000, 900, 3000], "level": _G_LVL,
                 "tray_type": _g(1002, "Лоток стандарт")},
                {"op": "place_family", "id": "MPF", "xyz": [2000, 2000, 0],
                 "level": _G_LVL, "symbol": _g(800, "Стол 1200"),
                 "rotation_deg": 45.0},
            ],
            "placements": [[0, 0, 3300]]}]},
}

#: эмиттеры, чьи op-локальные гарды переехали на refuse_stmt
GUARD_MODULES = ("authoring.py", "struct_emit.py", "connect.py",
                 "route_mep.py", "contour.py")
_IR_DIR = pathlib.Path(authoring.__file__).parent


def _corpus_emissions():
    """(имя, версия, op, atomic-эмиссия, per_op-эмиссия) по всему корпусу.

    Корпус этого файла ПЛЮС замороженный корпус паритета: op-локальный гард
    живёт в эмиттере, а не в программе, поэтому чем шире вход, тем больше
    guard-site он проходит.  Версионно-запрещённая операция (отверстия в
    плите до 2022) — сама часть контракта: обе изоляции обязаны отказать
    ОДИНАКОВО, иначе изоляция начала бы решать, что вообще выразимо.
    """

    from kukai.ir.tests.emit_parity_fixtures.generate_fixtures import (
        build_corpus, _min_ver, _strip)

    corpus = build_corpus()
    corpus.update({f"guard:{k}": v for k, v in PROGRAMS.items()})
    for name in sorted(corpus):
        raw = corpus[name]
        prog = _strip(raw)
        for ver in VERSIONS:
            if ver < _min_ver(raw):
                continue
            try:
                grounded = ground_mod.ground(_parse_and_check(prog),
                                             GROUND_SNAPSHOT)
            except KirRefusal:
                continue
            stamp = _program_stamp(grounded, "")
            for op in grounded:
                if op["op"] not in _EMITTERS:
                    continue
                emitter = _EMITTERS[op["op"]]
                try:
                    atomic = emitter(op, ver, stamp, "atomic")
                except KirRefusal as refused:
                    codes = sorted(d.code for d in refused.diagnostics)
                    try:
                        emitter(op, ver, stamp, "per_op")
                    except KirRefusal as also:
                        assert sorted(d.code for d in also.diagnostics) == codes
                        continue
                    raise AssertionError(
                        f"{name}|{ver}|{op['op']}: atomic отказал {codes}, "
                        f"per_op — нет")
                yield name, ver, op, atomic, emitter(op, ver, stamp, "per_op")


def _source_without_docstrings(path: pathlib.Path) -> str:
    """Исходник без докстрингов: документировать снятый механизм — можно."""

    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    spans = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef,
                                 ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if (isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            spans.append((first.lineno, first.end_lineno))
    drop = {ln for a, b in spans for ln in range(a, b + 1)}
    return "\n".join(line for i, line in enumerate(text.splitlines(), 1)
                     if i not in drop)


class TheRefusalPhraseHasExactlyOneOwner(unittest.TestCase):
    """Ступень 1: рукописной последовательности в эмиттерах не осталось."""

    def test_no_emitter_source_spells_the_program_refusal(self) -> None:
        # Ревью №5: мутационный страж НЕ доказывает единственность владельца —
        # точная рукописная копия фразы проходила бы его насквозь.  Это
        # доказывает исходный текст: последовательности нет ни в одном
        # эмиттере (докстринги, где снятый механизм ОПИСАН, не в счёт).
        for name in GUARD_MODULES:
            with self.subTest(module=name):
                code = _source_without_docstrings(_IR_DIR / name)
                self.assertNotIn(LEGACY_PHRASE, code)

    def test_refuse_stmt_renders_both_forms_and_nothing_else(self) -> None:
        self.assertEqual(
            refuse_stmt("W1", '"боком"', "atomic"),
            '__t.RollBack(); return __Refuse("W1", "боком");')
        self.assertEqual(
            refuse_stmt("W1", '"боком"', "per_op"),
            'throw __OpRefuse("W1", "боком");')
        with self.assertRaises(ValueError):
            refuse_stmt("W1", '"боком"', "нечто")

    def test_isolation_has_no_default(self) -> None:
        """Забытый аргумент — это тихая общепрограммная семантика в per_op."""

        with self.assertRaises(TypeError):
            refuse_stmt("W1", '"боком"')  # type: ignore[call-arg]


class PerOpBodiesCarryNoWholeProgramRefusal(unittest.TestCase):
    """Ступень 2 (ревью №9): нулевой allowlist остатков — и НЕ вхолостую."""

    def test_every_corpus_op_body_is_clean(self) -> None:
        seen = 0
        for name, ver, op, _atomic, per_op in _corpus_emissions():
            leftovers = program_refusal_tokens(per_op[1])
            if leftovers:
                self.fail(f"{name}|{ver}|{op['op']}|{op['id']}: {leftovers}")
            seen += 1
        self.assertGreater(seen, 500, "корпус не дошёл до эмиттеров")

    def test_the_corpus_actually_reaches_a_guard_in_every_kind(self) -> None:
        """Анти-Гудхарт: чистое тело ничего не значит, если гардов там нет."""

        with_guards: dict[str, int] = {}
        for _name, _ver, op, atomic, _per_op in _corpus_emissions():
            with_guards[op["op"]] = max(with_guards.get(op["op"], 0),
                                        atomic[1].count(LEGACY_PHRASE))
        self.assertEqual(len(with_guards), len(_EMITTERS),
                         "корпус покрывает не все виды операций")
        empty = sorted(k for k, n in with_guards.items() if n == 0)
        self.assertEqual(empty, [], "у этих видов корпус не дошёл ни до одного "
                                    "гарда — их чистота ничего не доказывает")

    def test_a_whole_program_emission_wraps_every_op(self) -> None:
        for name, prog in PROGRAMS.items():
            with self.subTest(program=name):
                grounded = ground_mod.ground(_parse_and_check(prog),
                                             GROUND_SNAPSHOT)
                cs = emit_program(grounded, "2026", isolation="per_op")
                self.assertIn(LEGACY_THROW, cs)


class GuardSitesUnreachableThroughAProgram(unittest.TestCase):
    """Ветки, до которых целая программа дойти не может — но гард в них есть.

    CLOSED (28.07 follow-up): ``in_view: {by: ref}`` USED TO resolve as
    ``__el_<ref> as View``, and no op in the registry creates a View — on any
    reachable ref (wall, floor) Roslyn gave CS0039 «Cannot convert Wall to
    View» BEFORE any guard could fire; this class existed to cover that one
    permanently-unreachable-through-a-program guard-site by calling the
    emitter directly, since nothing about it could otherwise be asserted at
    all.  The CS0039 itself is now fixed at the SOURCE
    (authoring._annot_view_res raises KirRefusal for ``ref``, isolation-
    independent, before any C# exists) — there is no longer a guard-site to
    cover here: ``raise`` is not an emitted ``refuse_stmt``.  Kept as a
    regression pin (the branch must stay gone, not silently return) plus the
    one surviving, still-emitting branch (element_id).
    """

    def test_the_in_view_ref_branch_is_refused_before_any_c_is_emitted(
            self) -> None:
        op = {"in_view": {"by": "ref", "value": "W1"}}
        for isolation in ("atomic", "per_op"):
            with self.subTest(isolation=isolation):
                with self.assertRaises(KirRefusal) as ctx:
                    authoring._annot_view_res(op, "D1", "2026", "D1",
                                              isolation)
                diag = ctx.exception.diagnostics[0]
                self.assertEqual(diag.code, "KIR-G002")
                self.assertEqual(diag.field_name, "in_view")

    def test_the_pinned_in_view_branch_obeys_it_too(self) -> None:
        op = {"in_view": {"by": "element_id", "value": 900}}
        atomic = authoring._annot_view_res(op, "D1", "2026", "D1", "atomic")
        per_op = authoring._annot_view_res(op, "D1", "2026", "D1", "per_op")
        self.assertEqual(per_op, atomic.replace(LEGACY_PHRASE, LEGACY_THROW))
        self.assertEqual(program_refusal_tokens(per_op), [])


class PerOpBodiesEqualTheRetiredRewrite(unittest.TestCase):
    """Эталон миграции: per_op-тело — ровно то, что давал снятый replace.

    Снимок «до правок» здесь не заморожен числом, а выражен ЗАКОНОМ: замена
    фразы была чистой текстовой операцией над атомарным телом, значит новое
    per_op-тело обязано совпадать с ``atomic.replace(...)`` посимвольно.  Так
    эталон не устаревает при появлении нового опа и не требует ручного
    перевыпуска — в отличие от списка хешей.

    ОДНО поимённое, документированное исключение (28.07): load_family с
    type_name — та самая ветка LoadFamilySymbol — раньше держала СВОЙ
    локальный `bool __ok_<s>` под тем же именем, что per_op-обвязка
    (emit_program) заводит СНАРУЖИ для КАЖДОГО опа (`__ok_<s> = false;`,
    единственный сентинел на весь оп) — вложенная область с тем же именем,
    Roslyn CS0136, живьём, на всех шести версиях (test_families.
    LoadFamilyPerOpIsolation держит это как отдельный, полный пин). Починка
    переименовывает ТОЛЬКО per_op-локальную переменную (`__symOk_<s>`);
    atomic не движется вовсе (та же переменная, тот же голден). Это ровно
    ВТОРАЯ переменная per_op-тела, отличная от рефьюз-фразы, — закон для
    остального корпуса остаётся без исключений.
    """

    def test_create_block_is_byte_identical_to_the_old_rewrite(self) -> None:
        checked = 0
        for name, ver, op, atomic, per_op in _corpus_emissions():
            expected = atomic[1].replace(LEGACY_PHRASE, LEGACY_THROW)
            if op["op"] == "load_family" and op.get("type_name") is not None:
                s = authoring._safe(op["id"])
                expected = expected.replace(f"__ok_{s}", f"__symOk_{s}")
            if per_op[1] != expected:
                self.fail(f"{name}|{ver}|{op['op']}|{op['id']}: create разошёлся")
            checked += 1
        self.assertGreater(checked, 500)

    def test_isolation_moves_nothing_but_the_refusal(self) -> None:
        """decl/post/readback от изоляции не зависят вовсе."""

        for name, ver, op, atomic, per_op in _corpus_emissions():
            for i, slot in ((0, "decl"), (3, "readback")):
                if atomic[i] != per_op[i]:
                    self.fail(f"{name}|{ver}|{op['op']}: {slot} сдвинулся")
            if (post_to_string(op["id"], atomic[2])
                    != post_to_string(op["id"], per_op[2])):
                self.fail(f"{name}|{ver}|{op['op']}: post сдвинулся")


class AHandWrittenGuardIsCaught(unittest.TestCase):
    """Ступень 3 (ревью №6/№10): мутации, включая токенно-эквивалентные."""

    PROG = {"ir_version": "1.0", "intent": "две стены", "ops": [
        {"op": "create_wall", "id": "W1", "p0_mm": [0, 0], "p1_mm": [6000, 0],
         "level": _LVL_ID},
        {"op": "create_wall", "id": "W2", "p0_mm": [0, 4000],
         "p1_mm": [6000, 4000], "level": _LVL_ID},
    ]}

    MUTATIONS = {
        "каноническая фраза":
            'if (__el_W1 == null) { __t.RollBack(); return __Refuse("W1", "рукой"); }\n',
        "лишний пробел":
            'if (__el_W1 == null) { __t.RollBack();  return __Refuse("W1", "рукой"); }\n',
        "пробелы между токенами":
            'if (__el_W1 == null) { __t . RollBack ( ); return __Refuse("W1", "рукой"); }\n',
        "комментарий внутри вызова":
            'if (__el_W1 == null) { __t/*x*/.RollBack(); return __Refuse("W1", "рукой"); }\n',
        "откат без отказа":
            'if (__el_W1 == null) { __t.RollBack(); }\n',
        "отказ без отката":
            'if (__el_W1 == null) { return __Refuse("W1", "рукой"); }\n',
    }

    def _emit_with(self, injected: str):
        grounded = ground_mod.ground(_parse_and_check(self.PROG),
                                     GROUND_SNAPSHOT)
        real = _EMITTERS["create_wall"]

        def broken(op, ver, stamp, *a, **kw):
            d, c, p, r = real(op, ver, stamp, *a, **kw)
            return d, (c + "\n" + injected if op["id"] == "W1" else c), p, r

        _EMITTERS["create_wall"] = broken
        try:
            return emit_program(grounded, "2026", isolation="per_op")
        finally:
            _EMITTERS["create_wall"] = real

    def test_every_mutation_refuses_loudly(self) -> None:
        for label, injected in self.MUTATIONS.items():
            with self.subTest(mutation=label):
                with self.assertRaises(KirRefusal) as caught:
                    self._emit_with(injected)
                diag = caught.exception.diagnostics[0]
                self.assertEqual(diag.code, GUARD_CONTRACT_CODE)

    def test_the_refusal_names_op_id_and_the_emitter_source(self) -> None:
        # Ревью №11: без вида опа, его id и функции-источника такой отказ
        # нечего чинить — он сообщает о поломке, не показывая где.
        with self.assertRaises(KirRefusal) as caught:
            self._emit_with(self.MUTATIONS["лишний пробел"])
        diag = caught.exception.diagnostics[0]
        self.assertEqual(diag.op_id, "W1")
        self.assertEqual(diag.field_name, "create_wall")
        self.assertIn("create_wall", diag.message_ru)
        self.assertIn("W1", diag.message_ru)
        self.assertIn("Источник:", diag.message_ru)
        self.assertIn("refuse_stmt", diag.message_ru)

    def test_the_source_names_the_registered_emitter(self) -> None:
        self.assertEqual(authoring._emitter_source("create_wall"),
                         "kukai.ir.authoring._emit_wall")
        self.assertEqual(authoring._emitter_source("create_foundation"),
                         "kukai.ir.authoring._emit_foundation_struct")
        self.assertEqual(authoring._emitter_source("нет такого"),
                         "<неизвестный эмиттер>")

    def test_atomic_isolation_is_not_policed(self) -> None:
        """В одной транзакции откат программы — это и есть контракт."""

        grounded = ground_mod.ground(_parse_and_check(self.PROG),
                                     GROUND_SNAPSHOT)
        cs = emit_program(grounded, "2026", isolation="atomic")
        self.assertIn(LEGACY_PHRASE, cs)
        self.assertNotIn(LEGACY_THROW, cs)


class UserDataIsNotCode(unittest.TestCase):
    """Ревью №3/№4: id и текст пользователя, дословно равные фразе."""

    def test_an_op_id_spelling_the_phrase_does_not_trip_the_contract(self) -> None:
        oid = '__t.RollBack(); return __Refuse('
        prog = {"ir_version": "1.0", "intent": "id-диверсия", "ops": [
            {"op": "create_wall", "id": oid, "p0_mm": [0, 0],
             "p1_mm": [6000, 0], "level": _LVL_ID}]}
        grounded = ground_mod.ground(_parse_and_check(prog), GROUND_SNAPSHOT)
        cs = emit_program(grounded, "2026", isolation="per_op")
        self.assertIn(LEGACY_THROW, cs)

    def test_a_note_quoting_the_phrase_does_not_trip_the_contract(self) -> None:
        prog = {"ir_version": "1.0", "intent": "заметка-диверсия", "ops": [
            {"op": "create_text", "id": "TXT",
             "in_view": {"by": "element_id", "value": 900},
             "at": [0, 0],
             "content": '__t.RollBack(); return __Refuse("x", "y");'}]}
        grounded = ground_mod.ground(_parse_and_check(prog), GROUND_SNAPSHOT)
        cs = emit_program(grounded, "2026", isolation="per_op")
        self.assertIn(LEGACY_THROW, cs)

    def test_the_scanner_reads_code_only(self) -> None:
        self.assertEqual(program_refusal_tokens(
            '// __t.RollBack(); return __Refuse(\n'
            'var __c = "__t.RollBack(); return __Refuse(";\n'
            '/* __t.RollBack(); */\n'), [])
        self.assertEqual(cs_dense_code('a( "x (  ) y" ); // z\n'), 'a("");')
        self.assertEqual(cs_code_only('x = "a\\"b"; // c'), 'x = ""; ')


class TheRefusalSentinelIsAType(unittest.TestCase):
    """Ревью №13: управляемый отказ отличим от поломки Revit API."""

    PROG = {"ir_version": "1.0", "intent": "стена", "ops": [
        {"op": "create_wall", "id": "W1", "p0_mm": [0, 0], "p1_mm": [6000, 0],
         "level": _LVL_ID}]}

    def _cs(self, isolation: str) -> str:
        grounded = ground_mod.ground(_parse_and_check(self.PROG),
                                     GROUND_SNAPSHOT)
        return emit_program(grounded, "2026", isolation=isolation)

    def test_per_op_declares_the_sentinel_type(self) -> None:
        cs = self._cs("per_op")
        self.assertIn("private class __KirOpRefusal : Exception", cs)
        self.assertIn("new __KirOpRefusal(__oid, __msg);", cs)
        self.assertNotIn("new InvalidOperationException(__msg);", cs)

    def test_the_sentinel_has_its_own_catch_carrying_the_op_id(self) -> None:
        cs = self._cs("per_op")
        self.assertIn("catch (__KirOpRefusal __orf_W1)", cs)
        self.assertIn('__rf_W1["refused_op_id"] = __orf_W1.Oid;', cs)

    def test_an_unexpected_exception_is_refused_but_labelled_internal(self) -> None:
        cs = self._cs("per_op")
        self.assertIn("catch (Exception __oex_W1)", cs)
        self.assertIn('__rf_W1["internal"] = true;', cs)
        # порядок обязателен: сначала sentinel, потом всё остальное
        self.assertLess(cs.index("catch (__KirOpRefusal __orf_W1)"),
                        cs.index("catch (Exception __oex_W1)"))

    def test_atomic_carries_none_of_it(self) -> None:
        cs = self._cs("atomic")
        for token in ("__KirOpRefusal", "__OpRefuse", "__orf_"):
            self.assertNotIn(token, cs)


class TheScaffoldAndStairsStayOutsideTheContract(unittest.TestCase):
    """Ревью №1/№2: наружные откаты законны и обязаны сохраниться."""

    def test_the_outer_transaction_still_rolls_back_on_a_bad_commit(self) -> None:
        prog = {"ir_version": "1.0", "intent": "стена", "ops": [
            {"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
             "p1_mm": [6000, 0], "level": _LVL_ID}]}
        grounded = ground_mod.ground(_parse_and_check(prog), GROUND_SNAPSHOT)
        for isolation in ("atomic", "per_op"):
            with self.subTest(isolation=isolation):
                cs = emit_program(grounded, "2026", isolation=isolation)
                self.assertIn(
                    "try { if (__t.HasStarted() && !__t.HasEnded()) "
                    "__t.RollBack(); } catch { }", cs)
                self.assertIn(
                    "if (__t.HasStarted() && !__t.HasEnded()) __t.RollBack();",
                    cs)

    def test_the_stairs_template_keeps_rollback_plus_edit_scope_cancel(self) -> None:
        prog = {"ir_version": "1.0", "intent": "лестница", "ops": [
            {"op": "create_stairs", "id": "S1", "p0_mm": [0, 0],
             "p1_mm": [5000, 0], "base_level": {"by": "element_id", "value": 42},
             "top_level": {"by": "element_id", "value": 43},
             "width_mm": 1200}]}
        out = compile_program(prog, revit_version="2026",
                              snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.code for d in out.diagnostics])
        self.assertIn("__t.RollBack(); __ess.Cancel(); return __Refuse(",
                      out.csharp)
        # лестница — solo-программа: per_op её не касается вовсе
        self.assertNotIn(LEGACY_THROW, out.csharp)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
