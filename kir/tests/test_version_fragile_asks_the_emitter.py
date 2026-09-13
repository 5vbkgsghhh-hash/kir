"""VERSION FRAGILITY IS ASKED OF THE EMITTER, NOT OF A SINGLE RUN.

WHAT HAPPENED (2026-08-13). ``VERSION_FRAGILE`` and the gate's cached answer
(`version_fragile_gate_answer.json`) were assembled from a SINGLE run —
`k2_ar_rd_v7`. The run is honest, the instrument is sound, the answer is
correct. And yet the list is incomplete: it is missing the pair
``("create_tag", "tag_type")``, even though the emitter refuses on it
explicitly and unconditionally.

    authoring.py:4620   if g_tagtype is not None:
                            if ver <= "2021": raise KirRefusal([Diagnostic(
                                code=EMIT_UNSUPPORTED, field_name="tag_type", …

Why it went unseen was measured, not guessed:

    trees in the corpus                                 52
    of them carrying `create_tag`                        1   (`k2_ar_rd_v8`)
    `create_tag` in it                                 851
    of those with `tag_type`                           851   (the lift always
                                                             writes it, lift.py:2612)
    `create_tag` in `k2_ar_rd_v7` — the one the cache was taken from  0

**Zero in the sample against an unconditional branch in the definition.**
This is exactly "an instrument on part of the range": the range was chosen
not by the list's author but by whichever building happened to be at hand.
Canon's first remedy — ASK THE AUTHORITY: a version-based refusal has a
place of definition, and it is enumerable.

WHAT THIS FILE DOES. It walks `authoring.py` by its SYNTAX TREE (not with a
regex: the canon explicitly names guessing Python syntax with regexes as the
source of four false verdicts), collects every place where a refusal depends
on the version, and requires that EACH ONE be a named decision — either in
``VERSION_FRAGILE`` or in the registry of conscious exceptions below.

THE RATCHET HAS ONE SIDE, AND THIS IS DELIBERATE. ``VERSION_FRAGILE`` is
allowed to be WIDER than what was found: ``("create_ceiling", None)`` is
fragile as a whole and has no refusal site in the emitter at all
(`Ceiling.Create` appeared in 2022, there is no workaround on any of the
six). It is not allowed to be NARROWER: every refusal site must be resolved
out loud.
"""

from __future__ import annotations

import ast
import inspect
import unittest

from kir import authoring, spec

#: (op, field) -> why the pair is NOT in ``VERSION_FRAGILE``, even though the
#: emitter refuses on it. The list is CLOSED BUT NOT COMPLETE in the canon's
#: terms: only what already has a found workaround below lands here, and a
#: missing entry means "we don't know," not "there is no such thing." Every
#: line must carry a NUMBER or state outright that there is none.
DELIBERATELY_OUTSIDE: dict[tuple[str, str | None], str] = {
    ("create_tag", "tag_type"): (
        "ОТКРЫТОЕ РЕШЕНИЕ, 13.08.2026, не пропуск. Предикат соло-нарезки "
        "ВЕРСИЙ НЕ ЗНАЕТ (`materialize` вызывает `is_version_fragile` без "
        "версии), а хрупкость здесь ровно одной версии — 2021. Включение "
        "пары нарежет соло 851 марку `k2_ar_rd_v8` на ВСЕХ ШЕСТИ версиях "
        "ради защиты одной, и на 2021 они всё равно не соберутся — тот же "
        "случай, что 81 потолок в оговорке над `VERSION_FRAGILE`. "
        "ЧЕМ ЗАКРЫВАЕТСЯ: прогоном `tools/compile_gate_offline.py` по "
        "`k2_ar_rd_v8` с парой и без неё — числа программ и потерянных опов, "
        "как для трёх прежних пар (2 745 -> 125 потеряно, 2 620 возвращено). "
        "Пока числа нет, молчаливое включение было бы догадкой о стоимости."),
}


def _refusal_sites_in_tree(tree: ast.AST) -> dict[str, list[tuple[str | None, int]]]:
    """A traversal of one syntax tree: function -> version-based refusal sites.

    Factored out of ``version_dependent_refusal_sites`` without changing
    behavior, so that the SAME traversal applies to both ``authoring`` and
    the satellites. A second instance of the traversal would be exactly the
    defect this file guards against.
    """
    by_function: dict[str, list[tuple[str | None, int]]] = {}

    class Walk(ast.NodeVisitor):
        def __init__(self) -> None:
            self.stack: list[str] = []

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

        def visit_Call(self, node: ast.Call) -> None:
            func = node.func
            if isinstance(func, ast.Name) and func.id == "Diagnostic":
                keywords = {k.arg: k.value for k in node.keywords}
                code = keywords.get("code")
                if isinstance(code, ast.Name) and code.id == "EMIT_UNSUPPORTED":
                    raw = keywords.get("field_name")
                    if raw is None:
                        field: str | None = None
                    elif isinstance(raw, ast.Constant):
                        field = raw.value
                    else:
                        raise AssertionError(
                            "field_name не литерал в месте отказа по версии, "
                            f"строка {node.lineno}: обход не может назвать поле")
                    enclosing = self.stack[-1] if self.stack else "<модуль>"
                    by_function.setdefault(enclosing, []).append(
                        (field, node.lineno))
            self.generic_visit(node)

    Walk().visit(tree)
    return by_function


def dispatch_tables() -> dict[str, object]:
    """op -> emission function, from BOTH dispatch tables.

    🔴 WHY A SECOND TABLE (2026-08-29). The traversal took only
    ``authoring._EMITTERS`` — and that was a denominator silently missing
    FIVE ops. Measured, not guessed:

        _EMITTERS                                   72 ops
        _SOLO_PROGRAMS                                5 ops
        intersection                                  0  ← NOT ONE

    That is, the solo programs were not merely "partially" covered — they
    lay OUTSIDE the traversal ENTIRELY, along with their four satellites
    (``family_author_emit``, ``family_transfer_emit``, ``stairs_landing_emit``,
    ``stairs_run_emit``). A live distinguisher: a planted version-refusal
    site in ``stairs_landing_emit`` gave 7 passed, the same in ``room_emit``
    gave 1 failed. The ratchet, set up precisely against "a version refusal
    must be a named decision," could not see a fifth of the emission.

    The count of refusal sites in these four satellites is zero TODAY, and
    the edit changes not a single number. It closes a CLASS: the next
    version-refusal site planted in a family or stairs branch must now be
    resolved out loud, not slip through silently.
    """
    out: dict[str, object] = dict(authoring._EMITTERS)
    out.update(authoring._SOLO_PROGRAMS)
    return out


def emitter_delegations() -> dict[str, tuple[str, str]]:
    """op -> (satellite module, entry function), asked of THE WRAPPER ITSELF.

    32 emitters out of 63 are four-line wrappers of the form
    ``return struct_emit.emit_foundation(op, ver, stamp, isolation)``. The
    satellite's name is taken from the wrapper's body, not from a suffix on
    the function's name: ``_emit_foundation_struct`` looks like a convention,
    and a convention is not an authority (form 7).

    The source of ops is :func:`dispatch_tables`, i.e. BOTH tables.

    🔴 TWO SOURCES, AND THE FIRST IS AN OBJECT, NOT TEXT (edit of
    2026-09-02). The layers wave (`ab040a0`…`fe41ab8`) removed 29 wrappers
    out of 41: satellites now declare their own `EMITTERS`, and the hub
    ASSEMBLES the registry. After that the dispatch table points to the
    satellite's function DIRECTLY, and parsing the wrapper's body found
    nothing: measured on 09.02 — **4** wrappers left, **37** direct entries.
    The traversal returned 4 sites instead of six, and the whole ratchet
    fell on its own denominator — that is, the guard caught the blindness of
    ITS OWN method, exactly as its denominator promises.

    So THE FUNCTION ITSELF is asked first (`__module__`/`__name__`): if it
    is defined in the satellite, that alone is delegation, and there is no
    need to read the text at all. Body-parsing remains the SECOND source —
    for the four surviving wrappers whose `__module__` is still
    `kir.authoring`.
    """
    import inspect
    import textwrap

    out: dict[str, tuple[str, str]] = {}
    for op_name, function in dispatch_tables().items():
        модуль = (getattr(function, "__module__", "") or "").split(".")[-1]
        имя = getattr(function, "__name__", "")
        if модуль.endswith("_emit") and имя:
            out[op_name] = (модуль, имя)
            continue
        try:
            source = textwrap.dedent(inspect.getsource(function))
        except (OSError, TypeError):
            continue
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.Return):
                continue
            call = node.value
            if not isinstance(call, ast.Call):
                continue
            target = call.func
            if (isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id.endswith("_emit")):
                out[op_name] = (target.value.id, target.attr)
    return out


def _calls_within(tree: ast.AST) -> dict[str, set[str]]:
    """function -> names of functions of THIS SAME module that it calls."""
    defined = {n.name for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    graph: dict[str, set[str]] = {}

    class Walk(ast.NodeVisitor):
        def __init__(self) -> None:
            self.stack: list[str] = []

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self.stack.append(node.name)
            graph.setdefault(node.name, set())
            self.generic_visit(node)
            self.stack.pop()

        visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

        def visit_Call(self, node: ast.Call) -> None:
            if self.stack and isinstance(node.func, ast.Name) \
                    and node.func.id in defined:
                graph[self.stack[-1]].add(node.func.id)
            self.generic_visit(node)

    Walk().visit(tree)
    return graph


def _reachable_from(graph: dict[str, set[str]], start: str) -> set[str]:
    seen, stack = {start}, [start]
    while stack:
        for nxt in graph.get(stack.pop(), ()):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


def satellite_refusal_sites() -> set[tuple[str, str | None, str]]:
    """Version-based refusal sites in the ``*_emit.py`` SATELLITES, tied to an op.

    🔴 WHY THIS EXISTS (measured 2026-08-15). The ratchet above traversed
    EXACTLY ``authoring.py``, while the bodies of 32 of 63 emitters had
    moved into twelve satellites, leaving four-line wrappers in
    ``authoring``. The method was correct — ask the authority — but coverage
    became 6% of the new code: **four version-refusal sites turned out to be
    invisible, three of them unnamed anywhere**:

        struct_emit.py:227    _emit_foundation_slab   field=holes    UNNAMED
        datum_emit.py:511     emit_multistory_stairs  field=levels   UNNAMED
        analysis_emit.py:126  _version_guard          field=None     UNNAMED
        arch_emit.py:115      emit_ceiling            field=None     covered
                                                      (create_ceiling, None)

    The cost is not theoretical: an emission refusal drops the WHOLE
    PROGRAM, and a materializer chunk is 250 ops. One foundation with an
    opening on Revit 2021 takes down up to 249 compatible neighbors with it.

    TYING TO AN OP — BY THE CALL CHAIN, NOT BY MODULE. Two of the four sites
    lie in PRIVATE helpers (`_emit_foundation_slab`, `_version_guard`), not
    in the entry function, and the module serves several ops at once
    (`struct_emit` — six). Attributing the site to the whole module would
    mean declaring five unrelated ops fragile. Hence: the entry is taken
    from the wrapper, a call graph is built inside the satellite, and a site
    belongs to an op if and only if its function is REACHABLE from that op's
    entry.

    The tuple's third element is a `file:line` address, not a bare string:
    the ratchet's message must lead to the place, otherwise it cannot be
    used.
    """
    import importlib
    import pathlib

    delegations = emitter_delegations()
    cache: dict[str, tuple[ast.AST, dict[str, set[str]],
                           dict[str, list[tuple[str | None, int]]]]] = {}
    sites: set[tuple[str, str | None, str]] = set()

    for op_name, (module_name, entry) in sorted(delegations.items()):
        if module_name not in cache:
            module = importlib.import_module("kir.%s" % module_name)
            source = pathlib.Path(module.__file__).read_text(encoding="utf-8")
            tree = ast.parse(source)
            cache[module_name] = (tree, _calls_within(tree),
                                  _refusal_sites_in_tree(tree))
        _tree, graph, by_function = cache[module_name]
        if not by_function:
            continue
        reachable = _reachable_from(graph, entry)
        for function_name, entries in by_function.items():
            if function_name not in reachable:
                continue
            for field, line in entries:
                sites.add((op_name, field, "%s.py:%d" % (module_name, line)))
    return sites


def version_dependent_refusal_sites() -> set[tuple[str, str | None, int]]:
    """Every place in the emitter where a refusal depends on the Revit version.

    The authority is the DEFINITION SITE: the ``Diagnostic(code=EMIT_UNSUPPORTED,
    …)`` node. The op's name is taken not from the function's name
    (a convention is not an authority, form 7), but from the dispatch table
    ``authoring._EMITTERS``.

    Answers only for ``authoring.py``. Satellites belong to
    ``satellite_refusal_sites``; the ratchet below unites them.
    """

    tree = ast.parse(inspect.getsource(authoring))
    by_function = _refusal_sites_in_tree(tree)

    ops_by_emitter: dict[str, list[str]] = {}
    for op_name, function in dispatch_tables().items():
        ops_by_emitter.setdefault(getattr(function, "__name__", ""), []) \
            .append(op_name)

    sites: set[tuple[str, str | None, int]] = set()
    for function_name, entries in by_function.items():
        op_names = ops_by_emitter.get(function_name)
        if not op_names:
            # It cannot be silently dropped: a refusal site without an op is
            # either a new form of dispatch or our own blindness, and both
            # need eyes on them.
            raise AssertionError(
                f"место отказа по версии в {function_name}, которого нет ни в "
                "authoring._EMITTERS, ни в authoring._SOLO_PROGRAMS — "
                "сопоставление оп<-функция сломалось")
        for field, line in entries:
            for op_name in op_names:
                sites.add((op_name, field, line))
    return sites


class EveryVersionRefusalIsANamedDecision(unittest.TestCase):
    """The ratchet: a refusal site must be resolved — by inclusion or by refusal."""

    def setUp(self) -> None:
        # BOTH TRAVERSALS, AND THIS IS THE POINT OF THE 2026-08-15 EDIT:
        # `authoring.py` plus the twelve `*_emit.py` satellites that the
        # bodies of 32 emitters moved into.
        self.sites = {(op, field, "authoring.py:%d" % line)
                      for op, field, line in version_dependent_refusal_sites()}
        self.satellite_sites = satellite_refusal_sites()
        self.sites |= self.satellite_sites
        # THE DENOMINATOR FIRST. An empty traversal would pass every check
        # below vacuously, and "0 uncovered out of 0" reads as "everything
        # is covered."
        self.assertGreaterEqual(
            len(self.sites), 3,
            "обход нашёл меньше трёх мест отказа по версии — это заявление "
            "о ХОДОКЕ, а не о реестре (три известны поимённо: holes, "
            "contour.holes, tag_type)")
        # THE SECOND DENOMINATOR — SEPARATELY, because the first does not
        # guard it: the satellite traversal could return empty (wrappers
        # stopped being recognized, a satellite got renamed), and the union
        # would stay above three on the strength of `authoring` alone. Then
        # the five pairs below would read as "wider than what was found,"
        # that is, legitimate — and the blindness would return silently.
        self.assertGreaterEqual(
            len(self.satellite_sites), 6,
            "обход спутников нашёл меньше шести мест — замер 15.08 дал ровно "
            "шесть (foundation.holes, multistory_stairs.levels, три нагрузки "
            "и ceiling). Меньше — сломан обход, а не починены спутники")
        # THE THIRD DENOMINATOR, AND IT IS ABOUT THE TRAVERSAL, NOT THE
        # FINDINGS. Solo satellites give ZERO refusal sites today, and
        # demanding a number of findings from them would be a lie: the floor
        # would have to be set to zero on findings, that is, to nothing.
        # What is guarded is that they were LOOKED AT AT ALL — otherwise the
        # traversal reverting to a single table would again pass silently,
        # and the two floors above would stay green on `_EMITTERS` alone.
        solo = {op: d for op, d in emitter_delegations().items()
                if op in authoring._SOLO_PROGRAMS}
        self.assertGreaterEqual(
            len(solo), 4,
            f"обход не дошёл до соло-программ: делегаций {len(solo)} при "
            f"четырёх известных (create_stairs_landing, create_stairs_run, "
            f"author_family, transfer_family). Знаменатель сузился, и "
            f"хрупкость семейной и лестничной веток снова невидима")
        self.assertEqual(
            set(authoring._EMITTERS) & set(authoring._SOLO_PROGRAMS), set(),
            "таблицы диспетчеризации пересеклись — место отказа получило бы "
            "два хозяина, и один из них молча")

    def test_every_site_is_covered_or_deliberately_outside(self) -> None:
        undecided = [
            (op, field, where) for op, field, where in sorted(self.sites)
            if (op, field) not in spec.VERSION_FRAGILE
            and (op, field) not in DELIBERATELY_OUTSIDE
        ]
        self.assertEqual(
            undecided, [],
            "эмиттер отказывает по версии, а нарезка об этом не знает и "
            "решения не записано: " + ", ".join(
                f"{op}.{field} ({where})" for op, field, where in undecided))

    def test_the_register_of_exemptions_holds_no_ghosts(self) -> None:
        # An exception the emitter no longer produces is a dead line, and it
        # makes the registry less truthful with every passing day.
        live = {(op, field) for op, field, _ in self.sites}
        ghosts = sorted(set(DELIBERATELY_OUTSIDE) - live)
        self.assertEqual(
            ghosts, [],
            f"регистр исключений называет пары, которых в эмиттере нет: {ghosts}")

    def test_no_pair_is_both_covered_and_exempted(self) -> None:
        both = sorted(set(DELIBERATELY_OUTSIDE) & set(spec.VERSION_FRAGILE))
        self.assertEqual(both, [], f"пара и включена, и исключена: {both}")

    def test_every_exemption_states_a_number_or_says_it_has_none(self) -> None:
        for pair, reason in DELIBERATELY_OUTSIDE.items():
            with self.subTest(pair=pair):
                self.assertIn(
                    "ЧЕМ ЗАКРЫВАЕТСЯ", reason,
                    "исключение без условия закрытия превращается в архив")
                self.assertTrue(
                    any(ch.isdigit() for ch in reason),
                    "исключение без единого числа — мнение, а не решение")


class TheWalkCanActuallyFindAndActuallyMiss(unittest.TestCase):
    """A CONTROL on the traversal itself: it must be able to find AND to
    fail to find."""

    def test_the_three_known_sites_are_found_by_name(self) -> None:
        found = {(op, field) for op, field, _ in
                 version_dependent_refusal_sites()}
        for pair in (("create_floor", "holes"),
                     ("create_floor_by_contour", "contour.holes"),
                     ("create_tag", "tag_type")):
            with self.subTest(pair=pair):
                self.assertIn(pair, found)

    def test_a_planted_site_is_found(self) -> None:
        # Control-PASS of the traversal on SYNTHETIC input: if it matched by
        # function name or by string, a new branch would be invisible to it.
        source = (
            "def _emit_nonesuch(op, ver):\n"
            "    if ver <= '2021':\n"
            "        raise KirRefusal([Diagnostic(\n"
            "            code=EMIT_UNSUPPORTED, op_id=oid,\n"
            "            field_name='planted', message_ru='x')])\n")
        hits = _sites_in_source(source)
        self.assertEqual(hits, {("_emit_nonesuch", "planted")})

    def test_a_different_code_is_not_mistaken_for_this_one(self) -> None:
        # Control-FAIL: the traversal must be ABLE to return empty.
        # Otherwise "found three" says nothing — it would find three on
        # someone else's code too.
        source = (
            "def _emit_nonesuch(op, ver):\n"
            "    raise KirRefusal([Diagnostic(\n"
            "        code=EMIT_TYPE_MISMATCH, op_id=oid,\n"
            "        field_name='planted', message_ru='x')])\n")
        self.assertEqual(_sites_in_source(source), set())


def _sites_in_source(source: str) -> set[tuple[str, str | None]]:
    """The same traversal, but over arbitrary text — for the controls above."""

    found: set[tuple[str, str | None]] = set()

    class Walk(ast.NodeVisitor):
        def __init__(self) -> None:
            self.stack: list[str] = []

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        def visit_Call(self, node: ast.Call) -> None:
            func = node.func
            if isinstance(func, ast.Name) and func.id == "Diagnostic":
                keywords = {k.arg: k.value for k in node.keywords}
                code = keywords.get("code")
                if isinstance(code, ast.Name) and code.id == "EMIT_UNSUPPORTED":
                    raw = keywords.get("field_name")
                    field = raw.value if isinstance(raw, ast.Constant) else None
                    found.add((self.stack[-1] if self.stack else "<модуль>",
                               field))
            self.generic_visit(node)

    Walk().visit(ast.parse(source))
    return found


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
