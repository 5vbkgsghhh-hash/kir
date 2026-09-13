"""THE PACKAGE'S DOOR: `kir` and `python -m kir`.

    kir demo                build a house and show what came out
    kir ops [NAME]           the operation registry; with a name — one contract
    kir skill               techniques, walkthroughs, refusal analysis
    kir course [TOPIC]       lessons on `program_py`
    kir doctor              what is available in THIS environment
    kir build FILE.json     an authored program -> C# or a typed refusal
    kir project inspect FILE.json   read a saved project without executing it
    kir project export FILE.json    project -> a checked KIR program
    kir project merge BASE OURS THEIRS   is the delta safe to build into this document
    kir project rebuild BASE TARGET      the delta that turns one building into the other
    kir project clash-report STORE.db    the bodies of a saved project -> findings
    kir connector list --directory DIR   session advertisements, not a liveness check
    kir connector context ...     read-only context of an explicitly chosen session
    kir capture read|propose|apply ...  offline edit of a saved
                            building; exactly `python -m kir.decompile.capture_api`

🔴 WHY THIS FILE WAS CREATED (04.09.2026). An honestly taken measurement of the entry point:

    [project.scripts] in pyproject.toml     EMPTY — not a single command
    kir/__main__.py                        DID NOT EXIST
    public names in kir/__init__.py       9

And meanwhile the tree already held, generated from the registry, and
working: `skill.build_skill_text()` — 14,774 characters of techniques and
walkthroughs; `tool_doc.build_tool_description()` — 29,942 characters of
reference; a course made of lessons; the operation registry with contracts;
a compiler for six Revit versions. An outside person ran
`pip install kir-building` and could read NONE of this without writing
Python. The owner's measure, "an outside person installs and builds," was
not moving not because there was nothing to show, but because there was
NOTHING TO SHOW IT WITH.

🔴 THERE IS NOT A SINGLE NEW CAPABILITY HERE, AND THIS IS THE LAW OF THIS
FILE. Every subcommand is an OUTPUT OF SOMETHING THAT ALREADY EXISTS: the
reference is assembled by the registry (`kir.spec` + `kir.dsl`), the lesson
by the course, the verdict by the judge, the C# by the compiler. A second
copy of any of these texts would silently diverge from the source, and the
package would start lying about itself. The only things of its own here are
the WIRING and the demonstration program below — the one value that has no
other home.

THE RETURN CODE IS SPLIT BY MEANING, not by "succeeded / did not succeed."
The shape is taken from `kir.selftest`, where it already stands and is
already explained: collapsing "did not happen" into "happened and was
refused" would mean saying "the program was rejected" where it was never
even read.

    0   ANSWERED
    1   REFUSED ON THE MERITS — the program was read, the compiler rejected it
    2   DID NOT HAPPEN — no such file, broken JSON, name not in the registry
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any

#: Outcomes named by a word, not by a number at the return site (`kir.selftest`).
ANSWERED = 0
REFUSED = 1
NOT_DONE = 2

# THE DEMONSTRATION HOUSE. The only value in this file that has no other
# home in the tree.
#
# 🔴 IT IS WRITTEN THROUGH `kir.dsl`, NOT DICTIONARIES, AND THIS IS SETTLED
# BY MEASUREMENT (04.09.2026, an outsider's road in a clean venv on the
# package FROM THE NETWORK):
#
#     via `kir.sdk` — what the README advises      17 turns, a hint needed 3 times
#     via `kir.dsl` — documented nowhere            6 turns, ZERO refusals
#
# The difference comes down to ONE slot. The DSL fills `level` ITSELF —
# `{"by": "ref", "value": "level1"}` — while on the raw path a human guesses
# it THREE TIMES and gets refused three times: `element_id` gives KIR-T001,
# `name` and `default` give KIR-G103. The only working shape is the one the
# refusal text does not print as JSON. A demonstration written with
# dictionaries would teach the 17-turn road.
#
# 🔴 AND NOT VIA `course.lessons.PLAN_DEMO_OPS` either: that program DOES NOT
# COMPILE. Measured the same day, `compile_program({"ops":
# list(PLAN_DEMO_OPS)})`:
#
#     KIR-P003  неизвестное поле 'point_mm' у create_room
#     KIR-T001  xy — точка [x,y] мм
#
# The registry calls the slot `xy`, the lesson writes `point_mm`. This does
# not bother the lesson — it builds a PLAN from it (`preview` reads what is
# declared and tolerates the extra field) — and it never once reached the
# compiler.
#
# 🔴 NOT A SINGLE SLOT REQUIRES A DOCUMENT SNAPSHOT. The door and window
# ground `symbol` from a model snapshot, and without one the program refuses
# with KIR-G103 — legitimately (a snapshot exists only with a live Revit) and
# out of place here: the loop
# `kir demo --json > дом.kir.json && kir build дом.kir.json` is required to
# pass WITHOUT a single extra argument.
#
# The cost of this choice is NAMED, not left unsaid: without a window the
# judge declares the design UNFIT under HAB030. This is not the demo
# breaking — this IS the demonstration: the language judged the design
# BEFORE Revit was ever launched.
#
# THE BODY OF THIS FUNCTION IS PRINTED TO THE HUMAN VERBATIM
# (`_author_source`), so the numbers in it stand as literals, and the
# explanations live here, outside: the printed piece is required to work in
# someone else's file by copy-paste, without a single name from here.
def author_demo() -> dict[str, Any]:
    from kir.dsl import (build, create_floor, create_level, create_room,
                         create_wall, envelope, reset)
    reset()
    envelope(intent="одна комната: уровень, плита, четыре стены, помещение")
    уровень = create_level(elev_mm=0, name="Этаж 1")
    контур = [(0, 0), (6000, 0), (6000, 4000), (0, 4000)]
    create_floor(outline=контур, level=уровень)
    for начало, конец in zip(контур, контур[1:] + контур[:1]):
        create_wall(p0_mm=начало, p1_mm=конец, level=уровень, height_mm=3000)
    create_room(xy=(3000, 2000), name="Гостиная", level=уровень)
    программа = build()
    return программа


def _author_source() -> str:
    """The body of `author_demo` verbatim — ONE carrier for what is shown and what is done.

    Copying the same nine lines here as text would mean starting a second
    copy of the program: it would diverge from the executed one on the very
    first edit, and it would diverge silently, and the human would copy
    something non-working into their own file.

    EXACTLY TWO mechanical lines are stripped — the `def` header and
    `return` — and both are checked, not assumed: the printed piece is
    required to be executable IN SOMEONE ELSE'S FILE, and a `return` outside
    a function is a syntax error.
    """
    import inspect
    import textwrap

    строки = inspect.getsource(author_demo).splitlines()
    if not строки[0].lstrip().startswith("def "):    # pragma: no cover
        raise AssertionError("первая строка исходника — не заголовок функции")
    if not строки[-1].lstrip().startswith("return "):  # pragma: no cover
        raise AssertionError("последняя строка исходника — не `return`")
    return textwrap.dedent("\n".join(строки[1:-1])).strip()


def demo_program() -> dict[str, Any]:
    """The demo program — the result of an authored run, not a literal."""
    return author_demo()


# ─────────────────────────────────────────────────────────────── printing

def _out(text: str = "") -> None:
    print(text)


def _note(text: str = "") -> None:
    """A summary for the HUMAN — on `stderr`, so `stdout` stays the subject matter.

    `kir build дом.kir.json > дом.cs` is required to give a C# file, not a C#
    file with a summary in its header; and the human is nonetheless required
    to see the summary. This is separated by streams, not a flag: a flag
    would have to be remembered.

    🔴 `stdout` IS FLUSHED BEFORE EVERY LINE OF THE SUMMARY, AND THIS IS NOT
    HYGIENE. Measured 04.09.2026: `kir demo | head` printed the "NEXT" block
    FIRST. The cause is not call order but buffers: in a pipe `stdout` is
    block-buffered, `stderr` is not, and the summary outran the subject. The
    reader saw the advice before what it advises about — correct text in the
    wrong place.
    """
    sys.stdout.flush()
    print(text, file=sys.stderr)


def _refusal(что: str, следующий_ход: str) -> None:
    """A REFUSAL NAMES THE NEXT MOVE. The strongest trait of this tree, and
    the door is required to hold it: "no such file" without a line that can
    be typed sends the reader off to guess."""
    _note(f"🔴 ОТКАЗ: {что}")
    _note(f"   СЛЕДУЮЩИЙ ХОД: {следующий_ход}")


# ─────────────────────────────────────────────────────────────── demo

def _compile_all_versions(program: dict) -> tuple[Any, dict[str, int], float]:
    """A program -> (outcome on the default, C# size by version, SECONDS).

    Versions are taken from `revit_version.supported()`, not enumerated here:
    a hand-typed list would fall behind the compiler on the very first new
    version.

    🔴 TIME IS RETURNED AS A MEASUREMENT, NOT PRINTED AS A NUMBER IN TEXT. The
    demo's tail used to have "in 0.1 s" as a literal — that is, a promise
    about SOMEONE ELSE'S machine, made on ours. An instrument naming a number
    it did not measure is a form of lying that reads as a fact.
    """
    import time

    from kir import compile_program
    from kir import revit_version

    начало = time.monotonic()
    sizes: dict[str, int] = {}
    default_out = None
    for version in revit_version.supported():
        out = compile_program(program, revit_version=version)
        if out.ok:
            sizes[version] = len(out.csharp or "")
        if version == revit_version.DEFAULT_VERSION:
            default_out = out
    прошло = time.monotonic() - начало
    if default_out is None:                       # pragma: no cover — safeguard
        default_out = compile_program(program)
    return default_out, sizes, прошло


def cmd_demo(args: argparse.Namespace) -> int:
    """Build the demonstration house and show what came out."""
    program = demo_program()

    if args.json:
        _out(json.dumps(program, ensure_ascii=False, indent=2))
        _note("программа напечатана в stdout. Дальше:")
        _note("   kir demo --json > дом.kir.json && kir build дом.kir.json")
        return ANSWERED

    from kir import revit_version
    from kir.preview import build_program_preview, census_lines

    ops = program["ops"]
    _out("KIR: ЗДАНИЕ — ЭТО ПРОГРАММА. Вот весь исходник этого дома:")
    _out()
    for строка in _author_source().splitlines():
        _out("    " + строка)
    _out()
    _out(f"ВЫШЛО {len(ops)} операций — слоты, которых ты не назвал, "
         f"язык заполнил САМ:")
    for i, op in enumerate(ops):
        уровень = op.get("level")
        _out(f"  {i:>2}  {op['op']:<14} id «{op.get('id', '')}»"
             + (f", level {json.dumps(уровень, ensure_ascii=False)}"
                if уровень else ""))
    _out()

    out, sizes, секунды = _compile_all_versions(program)
    if not out.ok:
        # A demonstration that was refused is NOT "empty output": it is
        # required to present the reason through the same means as anyone
        # else's program.
        _out("🔴 ДЕМОНСТРАЦИЯ ОТКАЗАЛА — и вот чем именно:")
        _out(_render_diagnostics(out))
        return REFUSED

    versions = revit_version.supported()
    _out(f"КОМПИЛЯЦИЯ, {len(sizes)}/{len(versions)} версий Revit, "
         f"без Revit и без сети:")
    for version in versions:
        размер = sizes.get(version)
        _out(f"  {version}   " + (f"{размер:>7} знаков C#" if размер
                                  else "  ОТКАЗ"))
    _out()

    if out.grounding_report:
        _out(f"КВИТАНЦИЯ НАЗВАННОГО УМОЛЧАНИЯ, записей "
             f"{len(out.grounding_report)}: выборы, которые сделал КОМПИЛЯТОР, "
             f"а не автор.")
        for row in out.grounding_report[:3]:
            _out("  " + _grounding_line(row))
        if len(out.grounding_report) > 3:
            _out(f"  … и ещё {len(out.grounding_report) - 3}")
        _out()

    census = build_program_preview(ops).census
    _out(f"ПЛАН ДО ТРАНЗАКЦИИ: рассмотрено {census.considered}, "
         f"нарисовано {census.drawn}. Перепись ЗАМЫКАЕТСЯ — "
         f"молча пропасть не может ничто:")
    for row in census_lines(census):
        _out(f"  {row['kind']:<8} {row['ru']}")
    _out()

    _out(_verdict_text(program))
    _out()
    _out("ЧТО ЗДЕСЬ ПРОИЗОШЛО: программа рассуждена и осуждена ДО Revit. "
         "HAB030 — не поломка\nдемонстрации, а её предмет: комната без окна "
         f"непригодна. Все {len(sizes)} компиляций заняли\n"
         f"{секунды:.2f} с на этой машине — без Revit, без сети и без единой "
         "лицензии.")
    _out()
    _note("ДАЛЬШЕ:")
    _note("   kir demo --json > дом.kir.json    программа файлом")
    _note("   kir build дом.kir.json            свой дом -> C#")
    _note("   kir ops create_window             как добавить окно")
    _note("   kir doctor                        что доступно в этой среде")
    return ANSWERED


def _grounding_line(row: dict) -> str:
    """One entry of the default receipt — as a line, not a raw dict.

    `chosen` can be either an id+name pair (a choice was MADE here), or a
    deferred read from Revit (`resolved_at: revit`). The difference matters:
    in the first case the compiler CHOSE, in the second it named WHERE the
    choice will happen — and printing both as one dict would mean hiding it.
    """
    chosen = row.get("chosen") or {}
    if chosen.get("name") or chosen.get("id") is not None:
        что = f"{chosen.get('name') or '?'} (id {chosen.get('id')})"
    elif chosen.get("resolved_at"):
        что = (f"решит {chosen['resolved_at']}, прочтётся обратно из "
               f"{chosen.get('read_from')}")
    else:
        что = str(chosen)
    return (f"{row.get('op_id')}.{row.get('param')} — "
            f"правило «{row.get('rule')}»: {что}")


def _verdict_text(program: dict) -> str:
    """The judge's verdict — printed by the judge's own printer, not our retelling."""
    from kir import design_check
    verdict = design_check.check_ops(program, building_id="демонстрация KIR")
    return design_check.render_verdict_brief(verdict)


# ─────────────────────────────────────────────────────────────── ops

def cmd_ops(args: argparse.Namespace) -> int:
    """The operation reference. LIVE: assembled by the registry at call time.

    A reference file would go stale on the very first new operation, and it
    would go stale SILENTLY — exactly the outcome this whole package is
    written to forbid.
    """
    from kir import spec

    if args.name is None:
        writing = spec.ops_by_discipline(writes=True)
        undecided = spec.ops_without_discipline(writes=True)
        written = sum(1 for o in spec.OPS.values() if o.writes_model)
        reading = sorted(n for n, o in spec.OPS.items() if not o.writes_model)
        _out(f"РЕЕСТР KIR: операций {len(spec.OPS)}, версия языка "
             f"{spec.IR_VERSION}.")
        _out(f"ПИШУЩИЕ ({written}), по разделам проекта:")
        for discipline, names in writing:
            _out(f"  {spec.DISCIPLINE_RU[discipline]}: " + ", ".join(names))
        if undecided:
            _out("  РАЗДЕЛ НЕ ВЫВЕДЕН (оп от этого не хуже): "
                 + ", ".join(name for name, _why in undecided))
        _out(f"ЧИТАЮЩИЕ ({len(reading)}): " + ", ".join(reading))
        _out()
        _note("контракт одной операции: kir ops create_wall")
        return ANSWERED

    # THE SINGLE CARRIER OF THE CONTRACT IS THE REGISTRY. `course._spec_parts`
    # assembles the call shape (`dsl._call_head`) and the docstring generated
    # from `spec.OPS`; not one line of the contract is written here by hand.
    #
    # 🔴 AND IT IS PRINTED IN FULL, UNLIKE `course.spec()`. There the text is
    # cut at `LESSON_CAP` (3,300) — the ceiling of the SANDBOX CHANNEL where
    # the model lives. The terminal has no such channel, and a cut contract
    # is not a contract: the tolerances and the postcondition stand AT THE
    # END (that is `course._CUT_FMT`'s own argument). Applying someone else's
    # ceiling here would mean handing the human an instrument covering only
    # part of the range.
    from kir import course
    from kir.dsl import DslRefusal

    try:
        ospec = course._op_spec_of(args.name)
    except DslRefusal as отказ:
        for diagnostic in отказ.diagnostics:
            _note(f"🔴 ОТКАЗ {diagnostic.code}: {diagnostic.message_ru}")
        # The registry's refusal names a move at ITS OWN door — `spec()` in
        # the sandbox. Here the door is different, and the translation costs
        # one line.
        _note("   ТО ЖЕ В ТЕРМИНАЛЕ: kir ops — весь реестр; "
              "kir ops <имя> — контракт одной")
        return NOT_DONE

    head, doc = course._spec_parts(ospec)
    _out(head + doc)

    # 🔴 WHAT AN OP CANNOT DO IS PRINTED RIGHT HERE (07.09.2026). The contract
    # answered what an op MEANS, and stayed silent about what the surrounding
    # tree can do with it: whether it is drawn on the plan, whether it reads
    # back, whether it gives a body to clash search. Silence read as "can do
    # everything" — the same class of defect as a clash blind spot with no
    # named cause (`clash_bundle.OP_NO_BODY`, header).
    #
    # There is ONE carrier of the answer — `kir.capability.limits`, a
    # projection of five live axes — so the terminal, MCP, and the course
    # cannot diverge in their answer, and not one op name is typed here by
    # hand.
    from kir import capability

    cannot = capability.limits(args.name)
    if cannot:
        _out()
        _out("ЧЕГО ЭТОТ ОП НЕ УМЕЕТ:")
        for axis in capability.AXES:
            why = cannot.get(axis)
            if why:
                _out(f"  {axis}: {why}")
    return ANSWERED


# ─────────────────────────────────────────────────────────────── skill

def cmd_skill(_args: argparse.Namespace) -> int:
    """Techniques, placement tricks, refusal analysis, a dictionary of shapes."""
    from kir import skill
    _out(skill.build_skill_text())
    return ANSWERED


# ─────────────────────────────────────────────────────────────── course

def cmd_course(args: argparse.Namespace) -> int:
    """Lessons. Their numbers are RECOMPUTED by a run, not written into the text."""
    from kir.course import lessons

    if args.topic is None:
        # THE CAVEAT STANDS AS THE FIRST LINE, because the table of contents
        # is addressed to the MODEL IN THE SANDBOX and calls topics through
        # Python (`course("витраж")`), while `recipe()`/`score()` are not
        # reachable at all from the terminal. Rewriting the table of contents
        # in our own words would mean starting a second copy of the topic
        # list; naming the difference is one move and zero divergence.
        _out("ОГЛАВЛЕНИЕ КУРСА. Текст ниже обращён к модели в песочнице; "
             "в терминале\nтема набирается «kir course <тема>», а "
             "recipe() и score() живут только\nв песочнице "
             "(`from kir.course import recipe, score`).")
        _out()
        _out(lessons.index())
        _out()
        _note("урок целиком: kir course вердикт")
        return ANSWERED
    try:
        _out(lessons.lesson(args.topic))
    except KeyError as промах:
        # The course writes the miss text itself, together with the topic
        # list; our retelling would diverge from ORDER on the very first new
        # lesson.
        _refusal(str(промах.args[0] if промах.args else промах),
                 "kir course — оглавление")
        return NOT_DONE
    return ANSWERED


# ─────────────────────────────────────────────────────────────── doctor

def cmd_doctor(_args: argparse.Namespace) -> int:
    """WHAT IS AVAILABLE IN THIS ENVIRONMENT — by measurement, not by assertion.

    Every line below is either computed right now, or named unavailable.
    Lying toward "we have it" is the most expensive thing here: the reader
    relies on a capability that does not exist.
    """
    import importlib.util
    import platform

    if getattr(_args, "env", False):
        from kir import env
        _out("KIR — ИМЕНА И ИСТОЧНИКИ НАСТРОЕК")
        _out("Известные алиасы и присутствующие KIR_*; значения не выводятся.")
        _out("Это не полный реестр: незаданные новые настройки и умолчания не перечислены.")
        for row in env.describe():
            former = row["former_name"] or "—"
            note = "алиас" if row["scope"] == "known_alias" else "присутствует; использование не проверено"
            _out(f"  {row['name']} | {former} | {row['source']} | {row['value_state']} | {note}")
        return ANSWERED

    import kir
    from kir import ports, revit_version, spec

    _out("KIR — ЧТО ДОСТУПНО В ЭТОЙ СРЕДЕ")
    _out()
    _out("ПАКЕТ")
    _out(f"  версия            {kir.__version__}   (дистрибутив kir-building)")
    _out(f"  откуда            {kir.__file__}")
    _out(f"  питон             {platform.python_version()}  "
         f"({sys.executable})")
    _out(f"  платформа         {platform.system()} {platform.machine()}")
    _out()

    _out("ЯЗЫК — БЕЗ СРЕДЫ И БЕЗ СЕТИ")
    _out(f"  операций          {len(spec.OPS)} "
         f"(пишущих {sum(1 for o in spec.OPS.values() if o.writes_model)})")
    _out(f"  версии Revit      {', '.join(revit_version.supported())} "
         f"(умолчание {revit_version.DEFAULT_VERSION})")
    try:
        _out(f"  компиляция        {_measure_offline_compile()}")
    except Exception as exc:                                    # noqa: BLE001
        # A measurement that fails inside the doctor is a FACT ABOUT THE
        # ENVIRONMENT, not a reason to stay silent.
        _out(f"  компиляция        🔴 НЕ СОСТОЯЛАСЬ: "
             f"{type(exc).__name__}: {exc}")
    _out()

    supplied = ports.supplied()
    missing = ports.missing()
    _out(f"ПОРТЫ — ЧТО ЭТА СРЕДА ПОСТАВИЛА ЯЗЫКУ ({len(supplied)} из "
         f"{len(supplied) + len(missing)})")
    if supplied:
        for name in supplied:
            _out(f"  поставлено        {name}")
    else:
        _out("  НИ ОДНОГО — и это НЕ ПОЛОМКА, А ОПРЕДЕЛЕНИЕ: порт есть шов,")
        _out("  которым язык просит у хоста недостающее. Голый язык ничего от")
        _out("  среды не получил, и всё, что напечатано выше, работает без")
        _out("  единого порта. Порты регистрирует ХОЗЯИН (плагин, бэкенд),")
        _out("  а не пакет: `kir.ports.register(имя, фабрика)`.")
    _out()

    _out("ЧЕГО ЗДЕСЬ НЕТ И ЧТО ЭТО ЗНАЧИТ")
    execution = ports.EXECUTION in supplied
    _out(f"  запись в Revit    {'ДА' if execution else 'НЕТ'} — нужен порт "
         f"«{ports.EXECUTION}»,")
    _out("                    живой Revit 2021–2026, мост и служба Roslyn. "
         "Ни одного\n"
         "                    из них в пакете нет и быть не должно: язык "
         "среда-агностичен.")
    # 🔴 A MISSING EXTRA IS NAMED IN ADVANCE, BECAUSE AFTERWARD NO ONE WILL
    # NAME IT. Measured 04.09.2026 on a base install: `python -m kir.mcp`
    # printed two INFO lines that looked like a successful start, then a RAW
    # `ModuleNotFoundError: No module named 'mcp'` — and NOWHERE did it say
    # `pip install "kir-building[mcp]"`. A refusal that names someone else's
    # library instead of its own extra sends the human to install the wrong
    # thing.
    #
    # 🔴 AND IT WENT STALE IMMEDIATELY, ON THE SAME DAY (04.09.2026). The door
    # was fixed an hour later: now it prints a NAMED refusal and code 2, not
    # a stack trace. The line below used to promise the human a stack trace —
    # that is, an instrument about YESTERDAY'S subject, exactly the kind this
    # tree exists to clean out. The text has been brought in line with what
    # the door does TODAY; checked by a run in a clean venv from the wheel
    # WITHOUT the extra.
    for модуль, что, зачем, ход in (
        ("mcp", "MCP-сервер", "python -m kir.mcp — дверь для модели",
         'python -m kir.mcp откажет с кодом 2 и назовёт это. Ставится: '
         'pip install "kir-building[mcp]"'),
        ("pytest", "набор ворот",
         "python -m kir.selftest — «KIR стоит без продукта», "
         "проверяемо тем, кто поставил",
         'python -m kir.selftest скажет «гонять нечем». Ставится: '
         'pip install "kir-building[dev]"'),
        ("fastapi", "стенд моста", "kir.bridge.mock_server — Revit понарошку",
         'pip install "kir-building[bridge]"'),
    ):
        есть = importlib.util.find_spec(модуль) is not None
        _out(f"  {что:<17} {'ДА' if есть else 'НЕТ'} — "
             + (зачем if есть else ход))
    _out()

    # 🔴 WHAT TO WRITE WITH IS NAMED HERE, BECAUSE THERE IS NOWHERE ELSE.
    # `kir.__doc__` declares a "Public surface" of four compiler names and
    # names NOT ONE module that a program is WRITTEN with. An outsider's road
    # measured 04.09.2026: via `kir.sdk` (what the README advises) — 17 turns
    # and three hints; via `kir.dsl`, documented nowhere — six turns and zero
    # refusals. The whole difference is whether you know the module's name.
    _out("ЧЕМ ПИСАТЬ (короткая дорога — первой)")
    _out("  kir.dsl           слоты заполняются сами; ей написан «kir demo»")
    _out("  kir.sdk           то же явными объектами: p = sdk.program(); "
         "p.compile()")
    _out("  kir.preview       план до транзакции: build_program_preview(ops)")
    _out("  kir.design_check  вердикт о замысле: check_ops(программа)")
    from kir import spec as _spec
    _out(f"  kir.spec          реестр: {len(_spec.OPS)} операции с контрактами (kir ops)")
    _out()
    _note("первая команда: kir demo")
    return ANSWERED


def _measure_offline_compile() -> str:
    """Compilation is MEASURED, not declared: a doctor that reports a
    capability on the author's word is a promise, not an instrument."""
    import time
    from kir import compile_program

    program = demo_program()
    начало = time.monotonic()
    out = compile_program(program)
    прошло = time.monotonic() - начало
    if not out.ok:
        коды = ", ".join(sorted({d.code for d in out.diagnostics})) or "без кодов"
        return f"🔴 ОТКАЗ на демонстрационной программе ({коды})"
    return (f"ДА — {len(program['ops'])} опов дали "
            f"{len(out.csharp):,} знаков C# за {прошло:.2f} с".replace(",", " "))


# ─────────────────────────────────────────────────────────────── build

def _render_diagnostics(out: Any) -> str:
    """A typed refusal for the HUMAN.

    The text of the cause and the next move is carried by the diagnostic
    ITSELF (`message_ru`) — they are not rewritten here. Our job is the
    address: the code, the operation number, the slot.
    """
    from kir import diag

    строки: list[str] = []
    for d in out.diagnostics:
        адрес = []
        if d.op_index is not None:
            адрес.append(f"оп #{d.op_index}")
        if d.op_id:
            адрес.append(f"id «{d.op_id}»")
        if d.field_name:
            адрес.append(f"слот «{d.field_name}»")
        имя = diag.spec_of(d.code)
        заголовок = f"  {d.code}"
        if имя is not None:
            заголовок += f" ({имя.name})"
        if адрес:
            заголовок += " — " + ", ".join(адрес)
        строки.append(заголовок)
        for строка in (d.message_ru or "").splitlines():
            строки.append(f"      {строка}")
        if d.expected is not None or d.got is not None:
            строки.append(f"      ждали: {d.expected!r}; пришло: {d.got!r}")
        if d.candidates:
            строки.append(f"      ближайшие: {', '.join(map(str, d.candidates))}")
        if d.suggested_replacement is not None:
            строки.append(f"      замена: {d.suggested_replacement!r} "
                          f"({d.applicability})")
        строки.append("")
    if out.handoff:
        строки.append(f"  ВНЕ ПОКРЫТИЯ, маршрут дальше: {out.handoff}")
    return "\n".join(строки).rstrip()


def _read_json(path: str, что: str) -> tuple[Any, int]:
    """File -> object, or DID NOT HAPPEN with a named next move."""
    if path == "-":
        try:
            return json.loads(sys.stdin.read()), ANSWERED
        except json.JSONDecodeError as exc:
            _refusal(f"{что} со stdin — не JSON: {exc}",
                     "проверь, что в трубу уехал именно JSON")
            return None, NOT_DONE
    файл = pathlib.Path(path)
    if not файл.exists():
        _refusal(f"файла «{path}» нет.",
                 "kir demo --json > дом.kir.json — рабочий образец такого файла")
        return None, NOT_DONE
    try:
        текст = файл.read_text(encoding="utf-8")
    except OSError as exc:
        _refusal(f"файл «{path}» не читается: {exc}",
                 "проверь права и кодировку (ждём UTF-8)")
        return None, NOT_DONE
    try:
        return json.loads(текст), ANSWERED
    except json.JSONDecodeError as exc:
        _refusal(f"{что} «{path}» — не JSON: строка {exc.lineno}, "
                 f"знак {exc.colno}: {exc.msg}",
                 "kir demo --json — образец правильной формы")
        return None, NOT_DONE


def cmd_build(args: argparse.Namespace) -> int:
    """An authored program -> C# or a typed refusal."""
    from kir import compile_program, revit_version

    program, код = _read_json(args.file, "программа")
    if код != ANSWERED:
        return код

    snapshot = None
    if args.snapshot:
        snapshot, код = _read_json(args.snapshot, "снимок")
        if код != ANSWERED:
            return код

    if args.revit not in revit_version.supported():
        _refusal(f"версии Revit «{args.revit}» этот компилятор не держит.",
                 "--revit " + " | ".join(revit_version.supported()))
        return NOT_DONE

    out = compile_program(program, revit_version=args.revit, snapshot=snapshot)
    if not out.ok:
        _note(f"🔴 ПРОГРАММА ОТВЕРГНУТА, диагностик {len(out.diagnostics)}:")
        _note(_render_diagnostics(out))
        return REFUSED

    _out(out.csharp)
    ops = program.get("ops", []) if isinstance(program, dict) else program
    _note(f"ПРИНЯТО: операций {len(ops)} -> {len(out.csharp)} знаков C# "
          f"для Revit {args.revit}.")
    if out.grounding_report:
        _note(f"НАЗВАННЫХ УМОЛЧАНИЙ {len(out.grounding_report)} — выборы "
              f"компилятора, а не автора:")
        for row in out.grounding_report:
            _note("   " + _grounding_line(row))
    _note("C# уехал в stdout. Вердикт о замысле: kir demo (образец) · "
          "судья зовётся из питона\n   "
          "`from kir import design_check; design_check.check_ops(программа)`")
    return ANSWERED


# ─────────────────────────────────────────────────────────────── project

def _read_authoring_project(filename: str):
    from kir.project import ProjectRevision

    source = (sys.stdin.read() if filename == "-" else
              pathlib.Path(filename).read_text(encoding="utf-8"))
    return ProjectRevision.loads(source)


def cmd_project(args: argparse.Namespace) -> int:
    """Read an inert project; export uses the existing semantic planner."""
    from kir.diag import KirRefusal
    from kir.project import ProjectError

    try:
        project = _read_authoring_project(args.file)
    except (OSError, UnicodeError, ProjectError) as exc:
        _refusal(f"проект не прочитан: {exc}",
                 "нужен UTF-8 JSON, сохранённый ProjectRevision.dumps(); "
                 "код рецептов при чтении не исполняется")
        return NOT_DONE

    if args.project_action == "inspect":
        summary = {
            "project_id": project.project_id,
            "revision_id": project.revision_id,
            "modules": len(project.modules),
            "instances": len(project.instances),
            "outputs": sum(len(instance.outputs)
                           for instance in project.instances),
            "integrity": "consistent",
            "semantic_validation": "not_run",
            "execution": "not_run",
        }
        _out(json.dumps(summary, ensure_ascii=False, indent=2))
        return ANSWERED

    try:
        # Match the existing `kir build` CLI policy; a successful export must
        # not silently rely on a larger operation budget than its consumer.
        project.plan(bulk=False)
        # 🔴 ONE traversal, not two: `plan` already built the envelope, and a
        # second `to_program()` outside the guard is exactly how AB-F3 leaked
        # a traceback (audit `FINAL_AUDIT_RU.md` §4.2).
        program = project.to_program()
    except KirRefusal as exc:
        _note("ПРОЕКТ ПРОЧИТАН, ПРОГРАММА ОТВЕРГНУТА:")
        for diagnostic in exc.diagnostics:
            _note(f"  {diagnostic.code}: {diagnostic.message_ru}")
        return REFUSED
    except ProjectError as exc:
        # A body-owned project (a recipe result with real geometry) has no
        # compiled program until the geometry is materialized. That is a
        # PROJECT STATE, not a broken file, and the door owes the reader the
        # next move — never a Python traceback.
        code = getattr(exc, "code", "project_error")
        detail = str(exc)
        detail = detail[len(code) + 2:] if detail.startswith(f"{code}: ") else detail
        _refusal(f"проект не экспортируется: {code}: {detail}",
                 "у проекта есть выходы с телами; сначала "
                 "`kir.geometry_materialization.materialize_project`, затем экспорт. "
                 "Состав проекта виден без экспорта: "
                 "`kir project inspect ФАЙЛ.json`")
        return REFUSED
    _out(json.dumps(program, ensure_ascii=False, indent=2, allow_nan=False))
    _note(f"Проект {project.project_id}, ревизия {project.revision_id}: "
          "структура программы проверена. Grounding и исполнение в Revit "
          "не выполнялись.")
    return ANSWERED


def cmd_project_diff(args: argparse.Namespace) -> int:
    """Compare authored revisions; never claim an executable native patch."""
    from kir.project import ProjectError
    from kir.project_diff import diff_projects

    if args.before == args.after == "-":
        _refusal("две ревизии нельзя прочитать из одного stdin",
                 "передай хотя бы одну ревизию отдельным файлом")
        return NOT_DONE
    try:
        before = _read_authoring_project(args.before)
        after = _read_authoring_project(args.after)
    except (OSError, UnicodeError, ProjectError) as exc:
        _refusal(f"ревизия не прочитана: {exc}", "нужны два JSON проекта")
        return NOT_DONE
    try:
        result = diff_projects(before, after)
    except ProjectError as exc:
        _refusal(f"сравнение отвергнуто: {exc}",
                 "сравниваются авторские ревизии одного проекта")
        return REFUSED
    _out(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, allow_nan=False))
    _note("Сравнение авторских ревизий; это не исполнимый patch Revit "
          "и не доказательство сохранения native-геометрии.")
    return ANSWERED


# 🔴 TWO FINISHED SUBSYSTEMS THAT HAD NO DOOR. `merge3` (the 3-way semantic
# merge) and `rebuild` (the A→B delta) were reachable from `kir/serving.py`
# and the standalone app ONLY: `grep -n "merge3\|rebuild" kir/__main__.py`
# gave comments and nothing else. A capability an outside person cannot name
# on the command line does not exist for them — the law this file was made
# under. The clash analysis got its door earlier and separately
# (`kir project clash-report`, `kir/project_clash_cli.py`); it is NOT
# duplicated here — a second door to one subsystem is the defect, not the fix.
#
# 🔴 NOT ONE LINE OF NEW SEMANTICS. Each verb calls the SAME function its
# existing caller calls: `merge_guard.guard_report` and
# `rebuild_plan.delta_rebuild_plan` + `plan_report` — the ones `serving.py`
# uses. A second computation of either verdict would drift from the
# product's, silently.
#
# 🔴 THE FLAGS (`KIR_MERGE3`, `KIR_REBUILD`) ARE NOT SET HERE, AND THAT IS A
# MEASUREMENT. `merge_enabled()`/`rebuild_enabled()` are read in exactly one
# place, `kir/serving.py` — the product's turn. Neither entry point called
# below consults its flag, so setting one would enable nothing; and the only
# write door (`env.set_default`) writes for the WHOLE process, which is
# exactly the "globally" that must not happen. The deliberate turn-on is the
# verb itself.
#
# Rebased into this tree 13.09.2026 from the stopped executor of plan 015
# (`.work/consolidation-20260913/worker-dirty/agent-a61d2ccd62dd310f8.patch`,
# made on the foreign base 5addc53). Its MCP tools were NOT taken: the owner's
# decision of 10.09 is "new tools are for Astra only, MCP rejected".

def _read_tree(path: str, что: str) -> tuple[Any, int]:
    """A folded building (`tree.json`) -> object, or DID NOT HAPPEN.

    The shape is `decompile.fold.TreeNode` — the very file a decompile run
    leaves on disk next to its snapshot, and the same one `serving.py` reads
    for the delta guard. It is read as plain JSON on purpose: `TreeNode` is a
    `TypedDict`, so the file IS the object, and validating it a second time
    here would be a second carrier of the fold's contract.
    """
    return _read_json(path, что)


def cmd_project_merge(args: argparse.Namespace) -> int:
    """Three folded buildings -> the merge guard's verdict. Nothing is touched."""
    from kir.decompile.merge_guard import VERDICT_CONFLICTING, guard_report

    пути = [args.base, args.ours, args.theirs]
    if пути.count("-") > 1:
        _refusal("две ревизии нельзя прочитать из одного stdin",
                 "передай хотя бы две ревизии отдельными файлами")
        return NOT_DONE
    деревья = []
    for путь, что in ((args.base, "база"), (args.ours, "наша ревизия"),
                      (args.theirs, "их ревизия")):
        дерево, код = _read_tree(путь, что)
        if код != ANSWERED:
            return код
        деревья.append(дерево)

    отчёт = guard_report(*деревья, base_label=args.base,
                         current_label=args.ours, target_label=args.theirs)
    if not отчёт["ok"]:
        _refusal(f"слияние не состоялось: {отчёт['error']['type']}: "
                 f"{отчёт['error']['message']}",
                 "нужны три файла tree.json одного здания "
                 "(их пишет разбор: kir capture / decompile)")
        return NOT_DONE
    _out(json.dumps(отчёт, ensure_ascii=False, indent=2, allow_nan=False))
    _note(отчёт["message_ru"])
    _note(f"ВЕРДИКТ {отчёт['verdict']}: конфликтов "
          f"{отчёт['conflicts_total']}, слито само {отчёт['auto_merged']}.")
    # "Read and refused on the merits" is CODE 1, and "there was nothing to
    # read" is 2 — this file's law, pinned by
    # `tests/test_the_package_has_a_door.py::ExitCodesAreSeparatedByMeaning`.
    # A conflicting merge was computed in full and reports every conflict; it
    # is a refusal on the merits, not an absence.
    return REFUSED if отчёт["verdict"] == VERDICT_CONFLICTING else ANSWERED


def cmd_project_rebuild(args: argparse.Namespace) -> int:
    """Two folded buildings -> the ordered delta that turns the first into the second."""
    import dataclasses

    from kir.decompile.rebuild import RebuildError
    from kir.decompile.rebuild_plan import delta_rebuild_plan, plan_refusal, plan_report

    if args.base == args.target == "-":
        _refusal("два здания нельзя прочитать из одного stdin",
                 "передай хотя бы одно здание отдельным файлом")
        return NOT_DONE
    деревья = []
    for путь, что in ((args.base, "база"), (args.target, "цель")):
        дерево, код = _read_tree(путь, что)
        if код != ANSWERED:
            return код
        деревья.append(дерево)

    try:
        план = delta_rebuild_plan(деревья[0], деревья[1],
                                  label_a=args.base, label_b=args.target)
    except (RebuildError, KeyError, TypeError, ValueError) as exc:
        отказ = plan_refusal(exc)
        _refusal(f"дельта не состоялась: {отказ['error']['type']}: "
                 f"{отказ['error']['message']}",
                 "нужны два файла tree.json одного здания; дельта отвергается, "
                 "если она не переводит состояние базы в состояние цели")
        return NOT_DONE

    отчёт = plan_report(план)
    if args.program:
        # The ordered program itself, not only its counts: `retire →
        # relocate → emit`, exactly as `apply_delta` walks it.
        отчёт["ops"] = [dataclasses.asdict(op) for op in план.program.ops]
    _out(json.dumps(отчёт, ensure_ascii=False, indent=2, allow_nan=False))
    _note(f"ЛИСТЬЕВ база {отчёт['leaves_a']} -> цель {отчёт['leaves_b']}; "
          f"дельта строит {отчёт['delta_leaves']} "
          f"(названо {отчёт['delta_named']}, замыкание по ссылкам "
          f"{отчёт['delta_ref_closure']}), снимает {отчёт['retire_leaves']}.")
    _note("Дельта верна, только если в документе уже стоит здание базы; "
          "офлайн это не проверяется — сравни базу со свежим разбором: "
          "kir project merge.")
    return ANSWERED


def cmd_project_store(args: argparse.Namespace) -> int:
    """Explicit local project persistence; only init/commit can write."""
    from kir.project import ProjectError
    from kir.project_store import (
        ProjectStore, ProjectStoreError, StoreConflict, StoreExists,
    )

    action = args.project_action
    try:
        if action == "init":
            initial = _read_authoring_project(args.file)
            store = ProjectStore.create(args.database, initial)
            result = {"project_id": store.project_id,
                      "revision_id": initial.revision_id,
                      "head_revision": store.head().revision_id,
                      "inserted": True, "scope": "authoring_only",
                      "native_published": False}
        else:
            store = ProjectStore.open(args.database, readonly=action != "commit")
            if action == "commit":
                proposed = _read_authoring_project(args.file)
                committed = store.commit(proposed, expected_revision=args.expected)
                result = {"project_id": store.project_id,
                          "revision_id": committed.revision_id,
                          "head_revision": committed.head_revision,
                          "inserted": committed.inserted, "scope": "authoring_only",
                          "native_published": False}
            elif action in ("head", "checkout"):
                project = (store.head() if action == "head" else
                           store.get(args.revision))
                _out(project.dumps())
                return ANSWERED
            elif action == "status":
                result = store.status(limit=args.limit, after_stream=args.after_stream)
            else:  # history: summaries, not duplicated full operation bodies.
                result = {"project_id": store.project_id,
                          "revisions": [{"revision_id": project.revision_id,
                                         "parent_revision": project.parent_revision,
                                         "intent": project.intent,
                                         "instances": len(project.instances),
                                         "outputs": sum(len(item.outputs)
                                                        for item in project.instances)}
                                        for project in store.history()]}
    except (StoreConflict, StoreExists) as exc:
        _refusal(f"сохранение отвергнуто: {exc}",
                 "прочитай текущую ревизию; конфликт не перезаписывает чужую работу")
        return REFUSED
    except (OSError, UnicodeError, ProjectError, ProjectStoreError) as exc:
        _refusal(f"хранилище проекта: {exc}",
                 "чтение не создаёт базу; init требует новый путь и корневую ревизию")
        return NOT_DONE
    _out(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    if action == "status" and not result["native"]["returned_scopes_readable"]:
        return NOT_DONE
    return ANSWERED


def _read_task_input(filename, max_bytes):
    """Bound input before parsing; stdin is data, never executable Python."""
    if filename == "-":
        stream = getattr(sys.stdin, "buffer", sys.stdin)
        value = stream.read(max_bytes + 1)
    else:
        with pathlib.Path(filename).open("rb") as stream:
            value = stream.read(max_bytes + 1)
    raw = value.encode("utf-8") if isinstance(value, str) else value
    if len(raw) > max_bytes:
        raise ValueError("input exceeds byte budget")
    return raw.decode("utf-8")


def _read_proposal_assets(filenames, *, max_bytes=None):
    from kir.occt_geometry import GeometryBundle, MAX_BUNDLE_BYTES
    assets, remaining = [], max_bytes
    for filename in filenames:
        if filename == "-":
            raise ValueError("assets require explicit files, not stdin")
        source = (pathlib.Path(filename).read_text(encoding="utf-8") if remaining is None
                  else _read_task_input(filename, min(remaining, MAX_BUNDLE_BYTES)))
        if remaining is not None:
            remaining -= len(source.encode("utf-8"))
        assets.append(GeometryBundle.loads(source))
    return assets


def cmd_project_task(args: argparse.Namespace) -> int:
    """Explicit durable authoring events; only evaluate invokes sandbox Python."""
    from kir.project import ProjectError
    from kir.project_merge import ChangeProposal, ProposalScope
    from kir.project_store import ProjectStore, ProjectStoreError, StoreConflict, TASK_STORE_SCHEMA
    from kir import project_tasks as tasks

    action = args.project_action.removeprefix("task-")
    try:
        store = ProjectStore.open(args.database, readonly=action in ("read", "list", "history"))
        if action == "upgrade":
            changed = store.upgrade_schema(TASK_STORE_SCHEMA, expected_revision=args.expected)
            result = {"schema": TASK_STORE_SCHEMA, "upgraded": changed, "store_id": store.store_id,
                      "project_id": store.project_id, "native_published": False}
        elif action == "create":
            scope = ProposalScope(instances=args.allow_instance, modules=args.allow_module,
                                  project_fields=args.allow_field)
            budgets = {key: getattr(args, key) for key in ("max_tokens", "max_tool_calls")
                       if getattr(args, key) is not None}
            result = tasks.create_task(store, task_id=args.task_id, base_revision=args.base,
                actor=args.actor, objective=args.objective, scope=scope, tools=args.tool, budgets=budgets)
        elif action == "read":
            result = tasks.read_task(store, args.task_id)
        elif action == "list":
            result = tasks.list_tasks(store, limit=args.limit, after_task=args.after_task)
        elif action == "history":
            result = {"events": tasks.task_history(store, args.task_id)}
        else:
            options = dict(request_id=args.request_id, expected_version=args.expected_task_version,
                           generation=args.generation, actor=args.actor)
            if action == "checkpoint":
                def unique_object(pairs):
                    result = {}
                    for key, value in pairs:
                        if key in result:
                            raise ValueError("duplicate checkpoint key")
                        result[key] = value
                    return result
                notes = json.loads(_read_task_input(args.file, tasks.MAX_CHECKPOINT_BYTES),
                                   object_pairs_hook=unique_object)
                result = tasks.checkpoint_task(store, args.task_id, notes=notes, **options)
            elif action == "submit":
                proposal = ChangeProposal.loads(_read_task_input(args.file, tasks.MAX_EVENT_BYTES))
                assets = _read_proposal_assets(args.asset, max_bytes=tasks.MAX_TASK_BYTES)
                result = tasks.submit_task(store, args.task_id, proposal, assets=assets, **options)
            elif action == "evaluate":
                from kir.task_recipe_runner import evaluate_task_recipe, RECIPE_POLICY
                if args.file == args.parameters == "-":
                    raise ValueError("source and parameters cannot both consume stdin")
                source = _read_task_input(args.file, RECIPE_POLICY.max_source_bytes)
                if args.parameters is None:
                    parameters = None
                else:
                    def unique_parameters(pairs):
                        values = {}
                        for key, value in pairs:
                            if key in values:
                                raise ValueError("duplicate parameter key")
                            values[key] = value
                        return values
                    parameters = json.loads(_read_task_input(args.parameters, tasks.MAX_CHECKPOINT_BYTES),
                                            object_pairs_hook=unique_parameters)
                    if type(parameters) is not dict:
                        raise ValueError("parameters file must contain a JSON object")
                result = evaluate_task_recipe(store, args.task_id, source=source,
                    instance_key=args.instance, module_key=args.module, output_keys=args.output,
                    parameters=parameters, reason=args.reason, **options)
            elif action == "submit-evaluation":
                from kir.task_recipe_runner import submit_evaluated_recipe
                result = submit_evaluated_recipe(store, args.task_id, tool_request_id=args.tool_request_id,
                                                 **options)
            elif action == "abandon-tool":
                result = tasks.abandon_task_tool(store, args.task_id, tool_request_id=args.tool_request_id,
                                                 reason=args.reason, **options)
            elif action == "reassign":
                result = tasks.reassign_task(store, args.task_id, new_actor=args.new_actor,
                                             reason=args.reason, **options)
            elif action == "revoke":
                result = tasks.revoke_task(store, args.task_id, reason=args.reason, **options)
            else:
                result = tasks.decide_task(store, args.task_id, proposal_id=args.proposal_id,
                                           expected_revision=args.expected, **options)
    except StoreConflict as exc:
        _refusal(f"конфликт задания: {exc}", "прочитай актуальные task version, generation и authored head")
        return REFUSED
    except (OSError, UnicodeError, ValueError, TypeError, RecursionError, ProjectError, ProjectStoreError) as exc:
        _refusal(f"операция задания не завершена: {exc}",
                 "нужны существующая база /5 и явные входы; LLM и Revit не запускаются")
        return NOT_DONE
    _out(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    _note("Actor — метка, не аутентификация. Только authoring; LLM/Revit не запускаются. "
          "Только task-evaluate явно вызывает sandbox Python; повтор reservation не запускает его заново.")
    if action == "evaluate":
        call = result["call"]
        if (result.get("recorded") is False or call["state"] != "recorded"
                or call["output"].get("proposal") is None):
            return NOT_DONE
    if action == "decide" and result["event"]["result"]["merge"]["status"] == "conflict":
        return REFUSED
    return ANSWERED


def cmd_project_proposal(args: argparse.Namespace) -> int:
    """Thin CLI over inert proposal parsing and the existing stored merge/CAS.

    Grants come from the accepting command, never from the proposed scope.
    This does not persist a branch inbox/decision log or publish native BIM.
    """
    from kir.project import ProjectError
    from kir.project_merge import ChangeProposal, ProposalScope, accept_proposal
    from kir.project_store import ProjectStore, ProjectStoreError, StoreConflict

    try:
        source = (sys.stdin.read() if args.file == "-" else
                  pathlib.Path(args.file).read_text(encoding="utf-8"))
        proposal = ChangeProposal.loads(source)
    except (OSError, UnicodeError, ProjectError) as exc:
        _refusal(f"предложение не прочитано: {exc}", "нужен JSON ChangeProposal.dumps(); source не исполняется")
        return NOT_DONE
    if args.project_action == "proposal-inspect":
        _out(json.dumps({"proposal_id": proposal.proposal_id, "project_id": proposal.base.project_id,
            "base_revision": proposal.base.revision_id, "candidate_revision": proposal.candidate.revision_id,
            "declared_scope": proposal.scope.to_dict(), "author": proposal.author, "reason": proposal.reason,
            "integrity": "consistent", "author_authenticated": False,
            "semantic_validation": "not_run", "native_published": False}, ensure_ascii=False, indent=2))
        return ANSWERED
    try:
        grant = ProposalScope(instances=args.allow_instance, modules=args.allow_module,
                              project_fields=args.allow_field)
        assets = _read_proposal_assets(args.asset) if args.asset else []
        store = ProjectStore.open(args.database, readonly=False)
        accepted = accept_proposal(store, proposal, expected_revision=args.expected,
                                   authorized_scope=grant, assets=assets)
    except (StoreConflict, ProjectError) as exc:
        _refusal(f"предложение отвергнуто: {exc}", "проверь текущий head и grant координатора; чужие изменения не перезаписываются")
        return REFUSED
    except (OSError, UnicodeError, ValueError, ProjectStoreError) as exc:
        _refusal(f"приём предложения не завершён: {exc}", "проверь существующее хранилище и явно переданные assets")
        return NOT_DONE
    committed = accepted.commit
    _out(json.dumps({"merge": accepted.merge.to_dict(), "commit": None if committed is None else {
        "revision_id": committed.revision_id, "head_revision": committed.head_revision, "inserted": committed.inserted},
        "native_published": False, "proposal_log_persisted": False}, ensure_ascii=False, indent=2, allow_nan=False))
    _note("Авторский merge; не публикация в Revit. Proposal/reason/report отдельно в базе не сохраняются.")
    return ANSWERED if accepted.merge.clean else REFUSED


# ─────────────────────────────────────────────────────────────── connector

def _connector_output(action: str, **fields) -> None:
    # This is an output whitelist, not a second protocol validator. In
    # particular, never serialize credentials, raw requests/responses or an
    # entire dataclass. Escape model text for a terminal-safe JSON document.
    _out(json.dumps({"schema": "kir-connector-cli/1", "action": action,
                     "read_only": True, "write_permission": False,
                     "may_retry": False, **fields}, ensure_ascii=True,
                    indent=2, allow_nan=False))


def cmd_connector(args: argparse.Namespace) -> int:
    """Read-only routing over the existing discovery/context/transport owners."""
    from datetime import datetime, timezone
    from uuid import uuid4

    from kir.connector_result import assess_connector_context_response
    from kir.revit_connector import ConnectorPreparationError, RuntimeTarget
    from kir.revit_discovery import DiscoveryError, scan_discovery
    from kir.revit_transport import ConnectorTransportError, exchange

    action = args.connector_action
    if action == "context" and (
        (args.precondition and (args.bind_view is None or args.bind_selection is None))
        or (not args.precondition and (args.bind_view is not None or args.bind_selection is not None))
    ):
        _connector_output(action, status="refused", diagnostic_code="explicit_binding_choices_required")
        return REFUSED

    try:
        target = (RuntimeTarget(args.journal_id, args.instance_id, args.revit_version)
                  if action == "context" else None)
        catalog = scan_discovery(args.directory)
        # Malformed filenames and contents are not ordinary diagnostics. The
        # scanner owns their validation; only its named issue codes leave here.
        issues = [{"code": issue.code} for issue in catalog.issues]
        now = datetime.now(timezone.utc)
        if action == "list":
            _connector_output(action, status="listed", catalog_complete=not issues,
                issues=issues, liveness="not_probed",
                advertisements=[record.summary(now=now) for record in catalog.advertisements])
            return ANSWERED

        selected = catalog.select(target=target, session_id=args.session_id, now=now)
        request_id = str(uuid4())
        request = selected.credentials.context_request(request_id=request_id, timeout_ms=args.timeout_ms)
        raw = json.dumps(request, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        response = exchange(selected, raw, client_path=args.client, timeout_ms=args.timeout_ms)
        assessment = assess_connector_context_response(response, credentials=selected.credentials, request_id=request_id)
        snapshot = assessment.snapshot
        result = {
            "status": "context" if assessment.read_complete else "refused",
            "target": target.to_dict(), "session_id": selected.credentials.session_id,
            "request_id": request_id, "catalog_complete": not issues, "issues": issues,
            "binding_matches": assessment.binding_matches, "read_complete": assessment.read_complete,
            "diagnostic_code": assessment.diagnostic_code,
            "snapshot": None if snapshot is None else {key: snapshot[key] for key in (
                "has_document", "document_key", "document_title", "revit_version", "revision",
                "active_view_id", "selection_digest", "selection_count", "is_family_document",
                "is_read_only", "is_modifiable", "complete")},
            "precondition": None, "precondition_requested": args.precondition,
            "authority": "context_observation_not_document_lease",
        }
        if args.precondition:
            result["binding_choices"] = {"bind_view": args.bind_view == "yes", "bind_selection": args.bind_selection == "yes"}
            try:
                result["precondition"] = assessment.require_precondition(**result["binding_choices"]).to_dict()
            except ConnectorPreparationError as exc:
                result.update(status="refused", diagnostic_code=exc.code)
                _connector_output(action, **result)
                return REFUSED
        _connector_output(action, **result)
        return ANSWERED if assessment.read_complete else REFUSED
    except ConnectorTransportError as exc:
        _connector_output(action, status="not_done", diagnostic_code=exc.code,
                          phase=exc.phase, delivery=exc.delivery)
        return NOT_DONE
    except DiscoveryError as exc:
        unavailable = exc.code in ("discovery_unavailable", "invalid_discovery_directory", "scan_budget_exceeded")
        _connector_output(action, status="not_done" if unavailable else "refused",
                          diagnostic_code=exc.code, catalog_complete=False)
        return NOT_DONE if unavailable else REFUSED
    except ConnectorPreparationError as exc:
        _connector_output(action, status="refused", diagnostic_code=exc.code)
        return REFUSED
    except (OSError, UnicodeError):
        # No exception text: filenames, credentials and native errors may be
        # untrusted. Lower-level owners supply named errors where available.
        _connector_output(action, status="not_done", diagnostic_code="connector_read_unavailable")
        return NOT_DONE


# ─────────────────────────────────────────────────────────────── capture

def cmd_capture(argv: list[str]) -> int:
    """`kir capture …` — the SAME door as `kir.decompile.capture_api`, not a second one.

    🔴 THE argv TAIL IS PASSED THROUGH HERE, AND NOT ONE FLAG IS DECLARED
    AGAIN. A second parser for the same
    `--capture/--element/--patch/--edit/--before/--binding/--profiles/--out`
    would silently diverge from the first — on a new flag, a change in
    `choices`, a `required` — and the human would get "unknown argument" from
    a door that has that very argument. The law of this file ("not a single
    new capability") requires exactly this: wiring, not a copy.

    THE RETURN CODES ARE ALSO SOMEONE ELSE'S. `capture_api` splits them under
    its own names (`EXIT_OK=0`, `EXIT_REFUSED=2`), and a refusal on the
    merits — a stale `before`, a patch from someone else's capture — gives 2.
    Remapping them onto the local ANSWERED/REFUSED would mean saying a
    different number about the seam's refusal than the seam itself says.
    `SystemExit` from parsing (`--help`, an unknown argument) is not caught
    for the same reason: a direct call gets the same one.

    🔴 AND WHY THIS IS NOT `sub.add_parser("capture")`. A subcommand declared
    to the parser is required to also declare ITS OWN arguments;
    `argparse.REMAINDER` is meanwhile known for swallowing a `--flag` before
    the subcommand. Intercepting the tail in `main()` hands `capture_api` an
    argv BYTE FOR BYTE the same as a direct call would receive — exactly the
    property checked by the two-process run
    (`kir/tests/test_the_package_door_opens_a_capture.py`).
    """
    from kir.decompile import capture_api
    return capture_api.main(argv)


# ─────────────────────────────────────────────────────────────── parsing

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kir",
        description="KIR — типизированный компилятор ЗДАНИЙ. "
                    "Здание — это программа.",
        epilog="первая команда: kir demo",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # 🔴 THE VERSION IS ASKED FROM THE PACKAGE, not typed here: two carriers
    # of one value would silently diverge (the same argument as in
    # `kir/__init__.py`).
    import kir
    parser.add_argument("--version", action="version",
                        version=f"kir-building {kir.__version__}")
    sub = parser.add_subparsers(dest="команда", metavar="КОМАНДА")

    p = sub.add_parser("demo", help="построить дом и показать, что получилось")
    p.add_argument("--json", action="store_true",
                   help="напечатать саму программу (в stdout), а не отчёт")
    p.set_defaults(func=cmd_demo)

    p = sub.add_parser("ops", help="реестр операций; с именем — контракт одной")
    p.add_argument("name", nargs="?", help="имя операции, например create_wall")
    p.set_defaults(func=cmd_ops)

    p = sub.add_parser("skill", help="техники, разборы, разбор отказов")
    p.set_defaults(func=cmd_skill)

    p = sub.add_parser("course", help="уроки по program_py")
    p.add_argument("topic", nargs="?", help="тема урока, например вердикт")
    p.set_defaults(func=cmd_course)

    p = sub.add_parser("doctor", help="что доступно в ЭТОЙ среде")
    p.add_argument("--env", action="store_true",
                   help="имена и источники настроек без вывода значений; не полный реестр")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("build", help="программа автора -> C# либо отказ")
    p.add_argument("file", help="файл программы (JSON); «-» — со stdin")
    p.add_argument("--revit", default="2026", metavar="ГОД",
                   help="версия Revit (умолчание 2026)")
    p.add_argument("--snapshot", metavar="ФАЙЛ",
                   help="снимок документа (JSON) для слотов, "
                        "заземляемых по имени или умолчанию")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("project", help="проект: история, изменения и экспорт")
    project_sub = p.add_subparsers(dest="project_action", required=True)
    from kir.project_publication_cli import register as register_publication
    register_publication(project_sub)
    from kir.project_clash_cli import register as register_clash
    register_clash(project_sub)
    for action, help_text in (
        ("inspect", "сводка проекта без исполнения рецептов"),
        ("export", "проверить план и напечатать программу KIR"),
    ):
        action_parser = project_sub.add_parser(action, help=help_text)
        action_parser.add_argument("file", help="JSON проекта; «-» — со stdin")
        action_parser.set_defaults(func=cmd_project)

    action_parser = project_sub.add_parser("diff", help="адресные изменения двух ревизий")
    action_parser.add_argument("before", help="JSON исходной ревизии; «-» — stdin")
    action_parser.add_argument("after", help="JSON следующей ревизии; «-» — stdin")
    action_parser.set_defaults(func=cmd_project_diff)

    action_parser = project_sub.add_parser(
        "merge", help="трёхсторонним слиянием судить, безопасна ли дельта")
    action_parser.add_argument("base", help="tree.json общего предка; «-» — stdin")
    action_parser.add_argument("ours", help="tree.json нашей стороны; «-» — stdin")
    action_parser.add_argument("theirs", help="tree.json их стороны; «-» — stdin")
    action_parser.set_defaults(func=cmd_project_merge)

    action_parser = project_sub.add_parser(
        "rebuild", help="дельта-программа, переводящая одно здание в другое")
    action_parser.add_argument("base", help="tree.json базы; «-» — stdin")
    action_parser.add_argument("target", help="tree.json цели; «-» — stdin")
    action_parser.add_argument("--program", action="store_true",
                               help="напечатать саму дельта-программу, а не только счёт")
    action_parser.set_defaults(func=cmd_project_rebuild)

    for action, help_text in (
        ("init", "создать новое локальное хранилище проекта"),
        ("head", "прочитать текущую сохранённую ревизию"),
        ("history", "сводка сохранённой истории"),
        ("status", "авторская ревизия, scoped checkpoints и pending без обращения к Revit"),
        ("checkout", "прочитать ревизию по её ID без изменения head"),
        ("commit", "сохранить ревизию, проверив ожидаемый head"),
    ):
        action_parser = project_sub.add_parser(action, help=help_text)
        action_parser.add_argument("database", help="путь локальной базы проекта SQLite")
        if action in ("init", "commit"):
            action_parser.add_argument("file", help="JSON проекта; «-» — stdin")
        if action == "commit":
            action_parser.add_argument("--expected", required=True, metavar="REVISION",
                                       help="ID ревизии, на основе которой сделано изменение")
        if action == "checkout":
            action_parser.add_argument("revision", help="ID сохранённой ревизии")
        if action == "status":
            action_parser.add_argument("--limit", type=int, default=20, help="число native scopes на странице (1–100)")
            action_parser.add_argument("--after-stream", metavar="SHA256", help="курсор следующей страницы; каждый вызов читает новый snapshot")
        action_parser.set_defaults(func=cmd_project_store)

    action_parser = project_sub.add_parser("proposal-inspect", help="прочитать предложение агента без сохранения/исполнения")
    action_parser.add_argument("file", help="JSON ChangeProposal; «-» — stdin")
    action_parser.set_defaults(func=cmd_project_proposal)
    action_parser = project_sub.add_parser("proposal-accept", help="authoring merge и CAS с отдельным grant координатора")
    action_parser.add_argument("database", help="существующая база проекта SQLite")
    action_parser.add_argument("file", help="JSON ChangeProposal; «-» — stdin")
    action_parser.add_argument("--expected", required=True, metavar="REVISION", help="ожидаемый текущий head")
    action_parser.add_argument("--allow-instance", action="append", default=[], metavar="KEY",
                               help="grant координатора на целый instance; можно повторять")
    action_parser.add_argument("--allow-module", action="append", default=[], metavar="KEY",
                               help="grant на целое определение модуля; можно повторять")
    action_parser.add_argument("--allow-field", action="append", default=[], metavar="FIELD",
                               choices=("intent", "metadata", "module_order", "instance_order"),
                               help="grant на поле проекта; отсутствие всех allow-флагов даёт пустой grant")
    action_parser.add_argument("--asset", action="append", default=[], metavar="FILE", help="явный GeometryBundle JSON; можно повторять")
    action_parser.set_defaults(func=cmd_project_proposal)

    for action in ("upgrade", "create", "read", "list", "history", "checkpoint", "submit", "reassign", "revoke", "decide",
                   "evaluate", "submit-evaluation", "abandon-tool"):
        coordinator = action in ("upgrade", "create", "reassign", "revoke", "decide", "abandon-tool")
        action_parser = project_sub.add_parser("task-" + action,
            help=("координатор: " if coordinator else "") + action + " сохранённого authoring task; без запуска LLM/Revit")
        action_parser.add_argument("database", help="существующая SQLite база; upgrade /5 только явно")
        if action not in ("upgrade", "list"):
            action_parser.add_argument("task_id")
        if action in ("upgrade", "decide"):
            action_parser.add_argument("--expected", required=True, metavar="REVISION", help="ожидаемый authored head")
        if action == "create":
            action_parser.add_argument("--base", required=True, metavar="REVISION")
            action_parser.add_argument("--actor", required=True, help="назначенный worker; метка, не аутентификация")
            action_parser.add_argument("--objective", required=True)
            action_parser.add_argument("--allow-instance", action="append", default=[])
            action_parser.add_argument("--allow-module", action="append", default=[])
            action_parser.add_argument("--allow-field", action="append", default=[],
                choices=("intent", "metadata", "module_order", "instance_order"))
            action_parser.add_argument("--tool", action="append", default=[], help="allowlist доверенных tool adapters; не запуск инструмента")
            action_parser.add_argument("--max-tokens", type=int, help="декларируемый бюджет; enforcement не установлен")
            action_parser.add_argument("--max-tool-calls", type=int, help="предел сохраняемых tool reservations; не общая квота внешних процессов")
        elif action == "list":
            action_parser.add_argument("--limit", type=int, default=20)
            action_parser.add_argument("--after-task")
        elif action in ("checkpoint", "submit", "reassign", "revoke", "decide", "evaluate", "submit-evaluation", "abandon-tool"):
            action_parser.add_argument("--expected-task-version", required=True, metavar="SHA256")
            action_parser.add_argument("--generation", required=True, type=int)
            action_parser.add_argument("--actor", required=True, help="метка автора команды; не аутентификация")
            action_parser.add_argument("--request-id", required=True)
            if action in ("checkpoint", "submit", "evaluate"):
                action_parser.add_argument("file", help="notes/proposal JSON или Python recipe для evaluate; «-» — stdin")
            if action == "evaluate":
                action_parser.add_argument("--instance", required=True)
                action_parser.add_argument("--module", required=True)
                action_parser.add_argument("--output", action="append", required=True, help="упорядоченные output keys; повторяемый флаг")
                action_parser.add_argument("--parameters", metavar="JSON_FILE", help="явный JSON object файл параметров; «-» — stdin")
                action_parser.add_argument("--reason", default="Explicit recipe evaluation")
            if action in ("submit-evaluation", "abandon-tool"):
                action_parser.add_argument("--tool-request-id", required=True)
            if action == "submit":
                action_parser.add_argument("--asset", action="append", default=[], help="явный GeometryBundle JSON")
            if action in ("reassign", "revoke", "abandon-tool"):
                action_parser.add_argument("--reason", required=True)
            if action == "reassign":
                action_parser.add_argument("--new-actor", required=True)
            if action == "decide":
                action_parser.add_argument("--proposal-id", required=True, metavar="SHA256")
        action_parser.set_defaults(func=cmd_project_task)

    p = sub.add_parser("connector", help="read-only discovery и контекст выбранной сессии")
    connector_sub = p.add_subparsers(dest="connector_action", required=True)
    action_parser = connector_sub.add_parser("list", help="объявления сессий; не проверка живых процессов")
    action_parser.add_argument("--directory", required=True, help="явный каталог v4/discovery; не создаётся")
    action_parser.set_defaults(func=cmd_connector)
    action_parser = connector_sub.add_parser("context", help="один read-only запрос точной target/session")
    action_parser.add_argument("--directory", required=True, help="явный каталог v4/discovery")
    action_parser.add_argument("--journal-id", required=True, metavar="UUID")
    action_parser.add_argument("--instance-id", required=True, metavar="UUID")
    action_parser.add_argument("--revit-version", required=True, metavar="YEAR", help="год явно выбранного runtime")
    action_parser.add_argument("--session-id", required=True, metavar="UUID")
    action_parser.add_argument("--client", required=True, metavar="ABSOLUTE_PATH", help="явный доверенный Kir.Revit.PipeClient executable")
    action_parser.add_argument("--timeout-ms", type=int, default=30000, help="deadline одного обмена, 1000–300000 мс")
    action_parser.add_argument("--precondition", action="store_true", help="вывести observed precondition; не разрешение писать")
    action_parser.add_argument("--bind-view", choices=("yes", "no"), help="обязателен только с --precondition")
    action_parser.add_argument("--bind-selection", choices=("yes", "no"), help="обязателен только с --precondition")
    action_parser.set_defaults(func=cmd_connector)

    # 🔴 A DOOR THAT IS NOT IN THE PARSER DOES NOT EXIST FOR SOMEONE LOOKING
    # FOR IT. Measured 07.09.2026: intercepting `capture` before argparse
    # worked (codes and output byte-for-byte like `capture_api`), but
    # `python -m kir --help` never named it — `grep -c capture` = 0. The
    # table-completeness guard (`test_the_package_has_a_door.py`) is set up
    # against exactly this and had already caught the same trouble with
    # `connector` on 06.09.2026.
    #
    # Parsing REMAINS someone else's: the tail is declared `REMAINDER` and
    # goes into `capture_api` untouched, and it is decided by the same
    # interception in `main()` — BEFORE argparse, so that `--help` and an
    # unknown argument answer with `capture_api`'s codes, not this file's.
    # This subcommand is declared here so the door is NAMED, not so it gets
    # parsed by a second law.
    p = sub.add_parser("capture", add_help=False,
                       help="офлайн-правка сохранённого здания "
                            "(= python -m kir.decompile.capture_api)")
    p.add_argument("остальное", nargs=argparse.REMAINDER,
                   help="довод целиком уходит в kir.decompile.capture_api")
    p.set_defaults(func=lambda args: cmd_capture(list(args.остальное)))
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    effective_argv = sys.argv[1:] if argv is None else argv
    if effective_argv and effective_argv[0] == "capture":
        # The tail goes into someone else's parsing UNTOUCHED: see `cmd_capture`.
        return cmd_capture(effective_argv[1:])
    publication_command = (len(effective_argv) > 1 and effective_argv[0] == "project"
                           and effective_argv[1].startswith("create-"))
    if effective_argv and (effective_argv[0] == "connector" or publication_command):
        # argparse echoes invalid values/unknown arguments to stderr. A user
        # may accidentally pass a credential there; keep this read-only CLI's
        # error channel as strict as its runtime diagnostics. Other commands
        # retain their existing parser behavior.
        from contextlib import redirect_stderr
        import io
        with redirect_stderr(io.StringIO()):
            try:
                args = parser.parse_args(effective_argv)
            except SystemExit as error:
                if error.code == 0:
                    return ANSWERED  # normal --help output contains no values
                if publication_command:
                    from kir.project_publication_cli import ACTIONS, output
                    action = effective_argv[1] if effective_argv[1] in ACTIONS else "parse"
                    output(action, status="not_done", diagnostic_code="invalid_publication_arguments")
                    return NOT_DONE
                action = effective_argv[1] if len(effective_argv) > 1 and effective_argv[1] in {"list", "context"} else "parse"
                _connector_output(action, status="not_done", diagnostic_code="invalid_connector_arguments")
                return NOT_DONE
    else:
        args = parser.parse_args(effective_argv)
    if getattr(args, "func", None) is None:
        # A BARE `kir` is NOT A REFUSAL, it is a question with no topic: we
        # print help and return zero. A nonzero code here would trip up
        # someone else's scripts on `kir || echo …` exactly where nothing
        # broke.
        parser.print_help()
        return ANSWERED
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
