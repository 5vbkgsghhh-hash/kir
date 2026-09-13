"""THE COURSE ON `program_py` — INTROSPECTION IN THE SANDBOX, NOT TEXT IN
THE PROMPT.

WHY THIS MODULE EXISTS. A measurement that explains everything:
`create_group` was called ZERO times out of 51,574 raised operations and
does not appear even once among the 25 ops in 1,453 live refusals. The
instrument is senior-level, and it is used like a junior's — because no one
ever showed how. The gap is not in the tools but in the method, and a
method is not transmitted by documentation but by decompiled working
examples.

WHY NOT IN THE PROMPT. The tool's description sits at the 30,000-character
threshold (`test_tool_doc.test_description_stays_small_next_to_the_schema`)
— on 09.08 it reached 29,976, that is, TWENTY-FOUR characters of headroom —
and it is paid for on EVERY request. The course would not fit there and
should not: three quarters of its text are not needed by three quarters of
the tasks. Here it lives IN THE SANDBOX, the model calls up exactly the
piece it needs FROM ITS OWN SCRIPT, and the answer arrives in the receipt's
`stdout` on THAT SAME TURN — no separate round trip, no standing cost. Only
the name pointer (`POINTER`) hangs around permanently, and it is kept under
700 characters by a TEST, not a promise.

    course()               table of contents
    course("витраж")       the whole lesson
    recipe()               list of working scripts with measured numbers
    recipe("витраж")       the script itself
    unit(name, placements) context: what is written inside becomes ONE group
    phase(name)            context: what is written inside is ONE plan step
    score()                three numbers for your program against a baseline
    preview()              the program's PLAN as text: what got drawn and what didn't
    design_check()         a VERDICT on the design's fitness — without Revit
    spec("create_wall")    an op's CONTRACT FROM THE REGISTRY; spec() is the whole registry

THE LAST ONE IS NOT ABOUT METHOD BUT ABOUT THE LANGUAGE, and it was added by
the same arithmetic as the whole module, only from the other side. The
tool's description on 09.08 was 29,976 characters against a 30,000 ceiling:
TWENTY-FOUR characters of headroom, three agents in one day ran into that
wall, and each one displaced someone else's prose to fit in a single op.
Meanwhile every op's contract is already assembled from the registry and
already sits in its function's docstring — 41,519 characters for 41 ops,
2,176 of them for `create_wall` alone with its postcondition and
tolerances — and this material does not fit into the prompt in any word
order. `spec` moves its cost from standing to one-off: a name in the
pointer, the contract on call. It carries not one character of its own
text — it prints the registry's docstring.

THE LAST TWO ARE NOT ABOUT THE LANGUAGE BUT ABOUT THE BUILDING, and they
were added following a measurement on 03.08: the loop "the model writes
Python -> a program -> a plan -> a verdict -> a fix" never once closed. The
plan was built and sent off over a websocket to a HUMAN's panel ("the
stream LEAVES FROM HERE AND DOES NOT COME BACK," `serving.py`), while the
verdict (`design_check.py`, 112 KB) had NOT ONE importer anywhere in the
tree besides its own test. The model wrote the building's next version
blind — not because sight had not been built, but because there was no
door from it into its language.

FOUR RULES THAT KEEP THE COURSE HONEST (checked by `test_course.py`):

1. EVERY NUMBER IS RECOMPUTED. All measurements sit in `corpus.py` next to
   the function that fetches them fresh from disk; a test checks the
   recorded value against the recomputed one. A stale measurement in the
   course is indistinguishable from a fabrication.
2. EVERY EXAMPLE EXECUTES. The `recipes.py` scripts are run through the
   REAL sandbox and compiled against six Revit versions. The `ops`/`elements`
   numbers are a measurement of a run, not the author's estimate.
3. NOT ONE OVERLAP WITH `skill.py`. That course is about the `program`
   field and macros; this one is about `program_py`. The separation is
   mechanical, held by `test_course.test_the_two_courses_do_not_overlap`.
4. THE POINTER AND REACHABILITY ARE ONE WHOLE. The pointer in the tool
   description promises names; a test requires that what is promised be
   REACHABLE from the sandbox, and fails on half the seam. Advertising the
   unreachable costs the model a round.

THE SEAM HAS BEEN BUILT — and these lines are being fixed on 04.08 for the
very reason that they used to claim the opposite. The sandbox places the
names of ONE module into the script's namespace (`policy.dsl_module`), and
its DEFAULT is already `kir.course.language` (`sandbox.SandboxPolicy`),
meaning the second way out of `SEAM` has been BUILT, not merely described.
`SEAM` is kept as a record of the two ways this could have been done; the
one chosen is the second.

WHAT THIS STALE SENTENCE COST: reading "neither has been built," the next
reader starts designing something already written — exactly what has
already happened four times in this repository. Prose about
unreachability is more dangerous than its absence, for the same reason an
instrument covering only part of the range is more dangerous than no
instrument at all.
"""
from __future__ import annotations

import difflib
import sys
import textwrap
import weakref
from collections.abc import Mapping
from typing import Any, Iterable

from kir.course import corpus, lessons, recipes
from kir.course.rhino import RHINO_NAMES

# WARMUP, NOT CONVENIENCE. Everything the course calls INSIDE the sandbox
# must already be in `sys.modules` BEFORE the child installs the import
# guard: the guard (`sandbox._MetaGuard`) raises `_ForbiddenImport` on any
# root outside the whitelist, and it is consulted only on a cache miss. A
# lazy import inside a course function therefore fails with KIR-B004
# «импорт запрещён» carrying the MODEL's line number — measured on the
# very first run of the recipes.
#
# `dsl` is deliberately NOT on this list: its import stays lazy, otherwise
# the seam of "two lines appended to the end of dsl.py" would become a
# cycle. By the time the script executes it is always loaded already — it
# is the very language module that the sandbox imports first.
from kir import spec as _spec                             # noqa: E402
from kir.acceptance import _OPS_WITHOUT_ELEMENTS          # noqa: E402
from kir.diag import PARSE_UNKNOWN_OP                     # noqa: E402

#: THE AUTHOR'S BUDGET — belongs to the compiler, not to a literal here.
#: Under this design it measures the PHASE: the phase is exactly the
#: program that one transaction will execute.
from kir.compiler import MAX_OPS_PER_PROGRAM              # noqa: E402
from kir.diag import (                                    # noqa: E402
    Diagnostic, PLAN_LIMIT, PLAN_PHASE_SHAPE, PLAN_SOLO_OP,
    # `TYPE_BAD_ENUM` / `TYPE_BAD_TYPE` — refusals of a unit of intent
    # (`unit()`): an unknown reading name and entries without a group. Both
    # are raised FROM THE BODY of the script, so that the refusal carries
    # the author's line number.
    TYPE_BAD_ENUM, TYPE_BAD_TYPE,
)

#: The channel ceiling belongs to the sandbox, not to a literal here: a
#: number typed by hand drifts from the source at the very first policy
#: edit. `SCRIPT_FILENAME` comes from the same place: it is used to pick
#: out the AUTHOR's frame, so that a phase refusal arrives with the line
#: number of the script, not of our file.
from kir.sandbox import MAX_STDOUT_CHARS, SCRIPT_FILENAME  # noqa: E402
# THE SHAPE CONSTRUCTOR — neither a course nor a building, but a MISSING
# WORD OF THE LANGUAGE. It stands here for the same reason as `spec` and
# `preview`: the SEAM decides the name's location, not kinship. There is
# one implementation and it lives in `mesh.py`, next to the law of shape
# it must satisfy — there is no second carrier.
from kir.mesh import extrude, sweep                     # noqa: E402
from kir.contour import region                          # noqa: E402
from kir.curveops import offset, thicken                # noqa: E402

# ─────────────────────────────────────────────────────────────── pointer

#: WHAT HANGS IN THE PROMPT PERMANENTLY. Everything else is on request.
#:
#: The cost is counted in the report. It must replace the line about
#: `tools/design/examples/*`: it points at scripts that use numpy and
#: shapely, which are not present in the sandbox — the model can neither
#: run them nor read them. A pointer to the unreachable is worse than no
#: pointer at all.
#: DISPLACEMENT, NOT GROWTH (09.08). The pointer gained a seventh name —
#: `spec` — and had to stay within its limit (700 characters,
#: `test_course.test_the_pointer_is_small_enough_to_hang_permanently`).
#: Room for it was taken FROM ITSELF, taken where the text repeated
#: itself: «отдельный раунд не нужен» is a retelling of «квитанции ЭТОГО
#: ЖЕ хода», «(`create_group`)» next to `unit` is the op name that `unit`
#: itself already prints, and now it also prints `spec("create_group")`.
#: No MEASUREMENT was touched: «семи разобранных зданий» and the channel
#: ceiling number stand verbatim. The rule by which the cuts were chosen
#: is below: a line carries a NAME AND A KIND, not a retelling of the
#: output.
#: THE EIGHTH NAME — `phase` — WENT IN BY DISPLACEMENT TOO, JUST LIKE THE
#: SEVENTH (09.08н). Room was taken from the same place the last wave took
#: it from — the retelling of its own output: «а не здесь», «целиком»,
#: «программы», «а не россыпью элементов» carry neither a name nor a
#: kind. `unit` and `phase` are folded into ONE line not to save space,
#: but because they share a kind, named in the module itself: a phase is
#: CONTEXT, `unit()`'s sibling; one gathers what is written inward into a
#: single GROUP, the other into a single PROGRAM. No MEASUREMENT was
#: touched: «семи разобранных зданий» and the channel ceiling number
#: stand verbatim. The margin left after the edit is 2 characters against
#: a 700 limit (measured, `test_course`), and the next name will again
#: have to displace something — that is exactly the working fuse.
POINTER: tuple[str, ...] = (
    "  КУРС И РЕЕСТР ЛЕЖАТ В ПЕСОЧНИЦЕ: зови их ИЗ СВОЕГО ЖЕ "
    "СКРИПТА, ответ придёт в `stdout` квитанции ЭТОГО ЖЕ хода.",
    "    course() — оглавление, course(\"витраж\") — урок; recipe(\"витраж\") "
    "— скрипт; score() — три числа против базовой "
    "линии семи разобранных зданий.",
    "    unit(name, placements) / phase(\"каркас\") — КОНТЕКСТЫ: внутрь пишут "
    "ОДНУ группу Revit / ОДНУ фазу плана. Бюджет и транзакция — на ФАЗУ, не "
    "на скрипт: здание за один ход.",
    # The line is paid for by EVERY request, so here there is only the
    # name and the kind of each assertion: exactly what each one prints
    # is visible from its own output, and retelling that as permanent
    # text would mean paying twice.
    "    preview() — план текстом; design_check() — вердикт о "
    "пригодности замысла без Revit. Обе — САМОПРОВЕРКА, зови ДО отправки.",
    # WHY THIS LINE STAYS PERMANENT. A capability the model cannot learn
    # about is dark BY CONSTRUCTION — the same way `sdk.py` lay excellent
    # and unreachable for five weeks. Op contracts — 41,519 characters
    # across 41 ops — do not fit in the prompt and should not; one line
    # fits, and it names the DOOR to them.
    "    spec(\"create_wall\") — КОНТРАКТ операции из реестра; spec() — весь "
    "реестр.",
    # The number comes from a sandbox constant, not from memory: a digit
    # typed by hand will drift from the policy at its very first edit and
    # will lie confidently.
    f"  Одна справка за скрипт: печать обрезается на {MAX_STDOUT_CHARS} "
    f"символах.",
)

#: TWO WAYS TO MAKE THE SEAM. Each is exactly one edit; the choice
#: belongs to the lead.
#:
#: MEASURED 12.08.2026: THE SECOND IS ALREADY IN EFFECT, and not by an
#: edit but by default. `SandboxPolicy.dsl_module` defaults to
#: `kir.course.language`, and `serving._sandbox_policy()` does not set
#: this parameter — meaning it takes the default. Verified not by
#: reading, but through the door: `execute_author_script('spec
#: ("create_level")')` prints the contract under exactly the prod policy.
#: The list below is kept as a record of the choice; reading it as "the
#: seam was never made" is a mistake, and it would cost the conclusion
#: "the model cannot reach `spec`" — that is, exactly the opposite of the
#: truth.
SEAM: tuple[tuple[str, str], ...] = (
    ("kir/dsl.py, две строки в конец файла",
     "from kir.course import SANDBOX_NAMES  # noqa: E402\n"
     "globals().update(SANDBOX_NAMES); __all__ += sorted(SANDBOX_NAMES)"),
    ("kir/serving.py, `_sandbox_policy()`",
     'SandboxPolicy(..., dsl_module="kir.course.language")'),
)


# ─────────────────────────────────────────────────────── printing into the sandbox

#: THE LESSON CEILING — not a round number, but a deduction from the
#: channel ceiling.
#:
#: The sandbox's `stdout` is truncated at `MAX_STDOUT_CHARS`, and that is
#: the script's ONLY feedback channel. A course that ate it whole would
#: take away exactly what the channel was built for: the model's own
#: printing — the approximation gap, the budget, the element count. The
#: reserve is 700 characters: `score()`'s output is measured at 364, the
#: rest for a couple of lines of the author's own printing. The test
#: holds both ends.
LESSON_RESERVE = 700
LESSON_CAP = MAX_STDOUT_CHARS - LESSON_RESERVE


# ────────────────────── READING LEDGER: what the course GAVE the author for this run
#
# 🔴 WHY IT WAS SET UP. Measured 22.08.2026: `kir_witness.jsonl` (5372
# lines) and `kir_programs.jsonl` (488) carry `author_digest` — a
# signature of the SOURCE — and not a single field in either corpus
# answers the question "did the author read the course." 16 lessons at
# 42,264 characters, 8 recipes, a registry on demand: all of it built,
# shipped, and NEVER measured by CONSUMPTION. Until the instrument
# exists, any answer about the course's usefulness is an opinion, not a
# number, and stacking a second layer of text on top of it would mean
# doubling down on the unverifiable.
#
# WHAT GETS RECORDED. An EVENT, not text: the call name, the topic, how
# many characters the course GAVE. Characters are counted BEFORE the
# printing channel's ceiling: it is the sandbox's `stdout` that
# truncates, not the course, and recording the truncated value here
# would mean attributing someone else's boundary to the course.
#
# WHAT IS NOT HERE AND WILL NOT BE. The script's source — it is already
# signed by `author_digest`, and a second copy of it in the telemetry
# would be a surface with no consumer (the exact same argument applies,
# word for word, to `coverage_feed.record_author_refusal`). Nor the text
# of the lessons themselves: it already lives on disk, and all the
# ledger needs from it is a length.
#
# WHY THE COUNTER LIVES IN MEMORY AND DOES NOT WRITE TO A FILE ITSELF.
# The course runs INSIDE the sandbox: the child has had its network,
# filesystem, and spare descriptors taken away — it has nowhere to
# write, BY CONSTRUCTION. The ledger travels out through the same
# result channel as the program itself (`sandbox` places it in
# `SandboxResult.course_reads`), and it is the parent that puts it into
# the sink.
#
# WHAT THE LEDGER DOES NOT PROVE. That what was read had any INFLUENCE.
# It answers the first question ("was anything given at all"), which
# today has no answer whatsoever; the second question is settled by a
# paired run, not by this counter.

#: The ledger's ceiling. Not a round number for its own sake: 16 lessons
#: + 8 recipes + one per call per op in a turn is already more than the
#: author manages to read, and listing beyond that does not distinguish
#: turns, it only lengthens them.
MAX_READS = 64

_READS: list[dict] = []
#: How many reads did NOT make it into the ledger because of the
#: ceiling. As a separate number, because "read 64 times" and "read
#: more, we counted up to 64" are different facts.
_READS_DROPPED = 0
#: Where `_emit` attributes the characters to: the line of the LAST open
#: call. A list of one element, not a stack: none of the six printing
#: functions calls another (checked across all 17 `_emit` call sites),
#: so a stack here would be an apparatus with nothing to apply it to.
_CURRENT: list[dict] = []


def _note_read(call: str, topic: Any = None) -> dict:
    """Record an access to the course. `_emit` will fill in the characters.

    The line is created BEFORE the call has finished — deliberately. An
    access that ends in a refusal (`spec("стенка")` → `_resolve` raises)
    stays in the ledger with `chars: 0`: the author ASKED, and a question
    without an answer is evidence of reading just as much as an answer
    is.
    """
    global _READS_DROPPED
    row: dict = {"call": call, "chars": 0}
    if topic is not None:
        row["topic"] = str(topic)[:48]
    if len(_READS) < MAX_READS:
        _READS.append(row)
    else:
        _READS_DROPPED += 1
    _CURRENT[:] = [row]
    return row


def reads_ledger() -> list[dict]:
    """This run's reading ledger — what travels outward.

    A LIST, not a summary: "called `spec` eight times" and "called
    `spec` across eight different ops" are different turns, and a
    summary by call name does not distinguish them.
    """
    out = [dict(row) for row in _READS]
    if _READS_DROPPED:
        # The truncation is NAMED, not implied: otherwise a ledger
        # sitting exactly at the ceiling would read as "that's all
        # there was".
        out.append({"call": "…", "dropped": _READS_DROPPED})
    return out


def reset_reads() -> None:
    """Reset the ledger. Called by the test rig, which needs several runs
    in one process; the sandbox gets a fresh process and has no need of
    this."""
    global _READS_DROPPED
    _READS.clear()
    _CURRENT.clear()
    _READS_DROPPED = 0


def _emit(text: str) -> None:
    if _CURRENT:
        _CURRENT[-1]["chars"] += len(text or "")
    print(text)


def _промах_чтения(строка: dict, текст: str, код: str | None = None) -> None:
    """A reading call missed on the NAME: print the miss and return.

    🔴 WHY THIS EXISTS. Before 25.08.2026, a name miss in
    `course`/`recipe`/`spec` raised an exception, and an exception drops
    the ENTIRE turn: the program built up to that line never made it
    out. Measured by a run: a script builds three walls, and on its
    last line asks for help with one wrong letter — `ok=False`, zero
    operations. At a `program_py` budget of 300 operations, the price of
    a typo in a question TO THE DOCUMENTATION is the whole turn's
    program.

    The argument was written by the author and never carried through:
    the docstring of `_op_spec_of` says «ронять ход на вопросе о справке
    из-за ФОРМЫ АРГУМЕНТА — плохой размен» and it accepts three forms.
    The exact same trade applies to the NAME too, only worse: a typo is
    more likely than a wrong form.

    WHY THIS IS NOT A RELAXATION. All three calls PRINT and return
    `None` — that is how they are meant to work. So further down the
    script there is no VALUE that could turn out wrong: a successful
    read and a miss hand back the same thing. Exactly one thing changes
    — whether the program makes it through. A constructing call does
    have a value, and its error still drops the turn.

    THE MISS STAYS LOUD. The text travels in full, with the list of
    names; the name is not guessed at; and `refused` in the ledger gives
    STRUCTURAL DISTINGUISHABILITY — a printed answer and a printed
    refusal are otherwise indistinguishable by machine, and the receipt
    is not read only by an eye.

    🔴 AND THE AUTHOR'S LINE NUMBER MUST SURVIVE. The former typed
    refusal carried it for free: the sandbox saw the `<kir-script>`
    frame and put the line into the refusal. Printing does not do that
    — so the address must be taken by hand (`_author_line`), otherwise
    in a three-hundred-line script with several `spec()` calls the
    model would learn THAT it missed and not WHERE. That would be a
    price paid for the fix, and there is no need to pay it: the
    mechanism lives in this same file.
    """
    строка["refused"] = True
    номер = _author_line()
    if номер is not None:
        строка["line"] = номер
    if код:
        строка["code"] = код
    адрес = f", строка {номер}" if номер is not None else ""
    клеймо = f" [{код}]" if код else ""
    _emit(f"СПРАВКА НЕ НАЙДЕНА{адрес}{клеймо}. ПРОГРАММА ЦЕЛА — ход "
          f"продолжается, написанное выше не потеряно.\n{текст}")


def _текст_промаха(промах: BaseException) -> str:
    """The miss text from the exception — WITHOUT the `KeyError('…')`
    wrapper.

    `str(KeyError("x"))` gives `"'x'"` with quotes: the model would get
    our Python-internal seam instead of a sentence in its own language.
    """
    return промах.args[0] if промах.args else str(промах)


# ───────────────────────────────────────────────────────────────── course

def course(topic: str | None = None) -> None:
    """The course's table of contents, or one whole lesson.

        from kir.course import course     # OUTSIDE the sandbox — only this way
        course("дом")

    🔴 THE IMPORT IS WRITTEN HERE BECAUSE IT DID NOT EXIST ANYWHERE
    (29.08.2026). A stranger's onboarding gate caught the very first
    step of learning: `from kir import course` gives a PACKAGE, not a
    function, and `course("дом")` drops with `TypeError: 'module' object
    is not callable`. In the author's own script the name is injected by
    the sandbox and needs no import — which is why this form had never
    once been written down in the whole history of the course.

    IT PRINTS, and does not return: the channel through which the text
    reaches the model is the receipt's `stdout`, and a returned string
    that nobody printed would simply be lost. Hence
    `print(course("дом"))` would additionally print `None` — there is no
    need to print its result.
    """
    строка = _note_read("course", topic)
    if topic is None:
        _emit(lessons.index())
        return
    try:
        текст = lessons.lesson(topic)
    except KeyError as промах:
        _промах_чтения(строка, _текст_промаха(промах))
        return
    _emit(текст)


def recipe(name: str | None = None) -> None:
    """The list of working scripts with measured numbers, or the script
    itself."""
    строка = _note_read("recipe", name)
    if name is None:
        _emit(_recipe_index())
        return
    try:
        ключ = _resolve(name, recipes.RECIPES, "рецепт")
    except KeyError as промах:
        _промах_чтения(строка, _текст_промаха(промах))
        return
    item = recipes.RECIPES[ключ]
    head = (f"РЕЦЕПТ «{item.name}» — {item.title}\n"
            f"замер прогона: {item.ops} операций, {item.elements} элементов, "
            f"{item.lines} строк; покрывает {item.covers}.")
    if item.versus:
        head += f"\nсравни с recipe(\"{item.versus}\"): {item.contrast}"
    _emit(head + "\n" + item.source.strip())


def _recipe_index() -> str:
    rows = ["РАБОЧИЕ СКРИПТЫ (числа — ЗАМЕР ПРОГОНА, не оценка автора):"]
    for name in recipes.ORDER:
        item = recipes.RECIPES[name]
        rows.append(f"  {name:<17} опов {item.ops:>3} -> элементов "
                    f"{item.elements:>3}, строк {item.lines:>3} — "
                    f"{item.title} ({item.covers})")
    rows.append("Пары «джуниор — сеньор» дают ОДИН результат разной формой; "
                "расходятся они ценой правки, а не числом элементов.")
    return "\n".join(rows)


def _resolve(name: str, table: dict, noun: str) -> str:
    """The name of a topic/recipe, or a refusal WITH A LIST of names.

    A refusal without a list is a second round: the model will not guess
    the spelling, it will try a synonym.
    """
    key = (name or "").strip().lower().replace("ё", "е")
    for candidate in table:
        if candidate.lower().replace("ё", "е") == key:
            return candidate
    raise KeyError(f"{noun} «{name}» не существует. Есть: "
                   + ", ".join(sorted(table)))


# ────────────────────────────────── OPERATION CONTRACT — ON REQUEST, NOT IN THE PROMPT

#: THE ARITHMETIC THIS FUNCTION FOLLOWS FROM (measured 09.08, this box).
#:
#: The language's docstrings are assembled from the registry
#: (`dsl._docstring`) and weigh 41,519 characters across 41 ops; one
#: `create_wall` alone is 2,176 together with its postcondition and five
#: tolerances. The tool description on the same day is 29,976 characters
#: against a 30,000 ceiling, i.e. 24 characters of margin, and the
#: registry is heading from 41 ops toward ~120. Contracts CANNOT be
#: carried in the prompt BY THE ARITHMETIC ALONE: not even a tenth of
#: them fits.
#:
#: And they do NOT need to be carried. In one turn the model writes two
#: or three unfamiliar ops, not forty; the other thirty-eight contracts
#: are the price paid for not being read. So the cost moves from a
#: CONSTANT one to a ONE-OFF one: the name sits in the pointer (one
#: line), the contract arrives on call — in the `stdout` of the receipt
#: of THAT SAME turn, with no second round.
#:
#: A SECOND DOOR, NOT A SECOND COPY. What is printed is EXACTLY the line
#: that `print(create_wall.__doc__)` gives
#: (`dsl.OP_FUNCTIONS[...].__doc__`), plus the call form from
#: `dsl._call_head` — the same one the `_bind_refusal` refusal prints.
#: There is not one character of our own text here: a document living
#: next to the code drifts from the code, and this has been measured in
#: this repository more than once.


def _spec_index() -> str:
    """Table of contents of the registry: names by kind of object. CHEAP
    ON PURPOSE.

    Not contracts, and not even one-line descriptions: the model chooses
    an op by SECTION and kind of object («мне нужна стена»), and takes
    the details from `spec(name)`. The listing is drawn from the
    registry (`spec.ops_by_discipline`) — the same one that prints the
    tool description, precisely so that the registry's contents in the
    prompt and in the receipt can never drift apart.
    """
    writing = _spec.ops_by_discipline(writes=True)
    undecided = _spec.ops_without_discipline(writes=True)
    written = sum(1 for o in _spec.OPS.values() if o.writes_model)
    reading = sorted(n for n, o in _spec.OPS.items() if not o.writes_model)
    rows = [f"РЕЕСТР KIR, опов всего {len(_spec.OPS)}. Контракт ОДНОГО: "
            f"spec(\"create_wall\") — форма вызова, виды и границы слотов, "
            f"формы селекторов, пул заземления, постусловие, допуски.",
            f"ПИШУЩИЕ ({written}), по разделам проекта:"]
    rows += [f"  {_spec.DISCIPLINE_RU[d]}: " + ", ".join(names)
             for d, names in writing]
    if undecided:
        rows.append("  РАЗДЕЛ НЕ ВЫВЕДЕН (оп от этого не хуже): "
                    + ", ".join(name for name, _why in undecided))
    rows.append(f"ЧИТАЮЩИЕ ({len(reading)}): " + ", ".join(reading))
    return "\n".join(rows)


def _spec_parts(ospec: Any) -> tuple[str, str]:
    """The contract of one op in two pieces: OUR heading and the
    REGISTRY's docstring.

    Kept apart, not as one string, because the truncation needs to know
    where `__doc__` begins in the result: only then can the advice
    «возьми хвост» name an INDEX INTO THE DOCSTRING, rather than into
    our own text.
    """
    from kir import dsl
    head = (f"КОНТРАКТ «{ospec.name}» — из реестра; то же даёт "
            f"print({ospec.name}.__doc__)\n"
            f"    {dsl._call_head(ospec)}\n\n")
    return head, dsl.OP_FUNCTIONS[ospec.name].__doc__ or ""


#: WHAT HAPPENS WHEN THE HELP TEXT DOES NOT FIT THE CHANNEL.
#:
#: The sandbox silently cuts `stdout` at `MAX_STDOUT_CHARS` —
#: `_CappedWriter` appends «[обрезано ещё N символов]» and that is all.
#: That is enough for a LESSON (the text is continuous prose, the tail
#: just loses a thought). It is NOT enough for a CONTRACT: tolerances
#: and the postcondition sit AT THE END, and a truncated contract is
#: indistinguishable from a contract with no tolerances — that is, from
#: an instrument that covers only part of the range, and such an
#: instrument has already cost this repository a missed defect.
#:
#: So WE do the truncating, and NAME it: how many characters did not
#: make it through, and HOW to fetch the rest, as a verbatim line that
#: can be copied into the next script.
#:
#: THERE WAS A FORECAST HERE, AND IT DID NOT COME TRUE — THAT MATTERS
#: MORE THAN THE NUMBER ITSELF. It read: "the longest contract prints at
#: 2,392 against a 3,300 ceiling (measured 09.08 across 41 ops), the
#: branch is on standby for the future; at ~120 ops it will stop being
#: on standby." REMEASURED 12.08 across all 69 ops: median 1,278, p90
#: 2,082, and TWO contracts already do NOT fit — `route_duct_system` at
#: 3,967 and `route_pipe_system` at 3,904. The branch fired at 69 ops,
#: not at 120: what grew was not the ops, it was ONE contract, and a
#: guess based on op count does not catch that kind of growth. Hence the
#: rule: the lifespan of a note like this is measured by an INSTRUMENT
#: (`course._spec_parts` across the whole registry), not by a guess.
#:
#: AND ABOVE ALL: truncating the TAIL is wrong in substance for a
#: contract, because the tail is exactly where the PARAMETERS AND
#: TOLERANCES sit. A live measurement on 12.08 through the very same
#: door the model uses (`execute_author_script`, under the prod policy):
#: `spec("route_pipe_system")` returned 3,300 characters, and the word
#: «Допуски» was NOT among them. Now the contract is truncated
#: SECTION-AWARE — see `_contract_within_channel` — and this function
#: remains only for LESSONS, where the text is continuous prose and the
#: tail loses nothing but a thought. The test runs it with a reduced
#: ceiling — otherwise it would only be checked by reasoning.
_CUT_FMT = ("\n[ОБРЕЗАНО {cut} символов из {full}: канал печати {cap}. "
            "ОБРЕЗАННЫЙ КОНТРАКТ — НЕ КОНТРАКТ: допуски и постусловие стоят В "
            "КОНЦЕ. Остаток: {rest}]")


def _within_channel(text: str, rest_of, cap: int = 0) -> str:
    """Text that arrives IN FULL — or honestly truncated with a named
    tail.

    The ceiling comes from the sandbox via `LESSON_CAP` (the channel
    ceiling minus a reserve for the model's own printing), not typed as a
    number here; the `cap` parameter exists for the truncation test — a
    branch that no op in today's registry reaches, otherwise it would be
    checked by reasoning, not by a run.

    `rest_of(keep)` builds the advice from the ACTUAL length of the kept
    chunk.
    """
    cap = cap or LESSON_CAP
    if len(text) <= cap:
        return text
    # The skeleton is sized for the WORST case of BOTH numbers (the whole
    # text truncated, the tail offset at its maximum): the real one is
    # shorter, so the result is guaranteed to fit the ceiling, not
    # "roughly fits".
    skeleton = _CUT_FMT.format(cut=len(text), full=len(text), cap=cap,
                               rest=rest_of(len(text)))
    keep = max(0, cap - len(skeleton))
    return text[:keep] + _CUT_FMT.format(
        cut=len(text) - keep, full=len(text), cap=cap, rest=rest_of(keep))


#: WHAT IS CUT FROM THE POSTCONDITION. Deliberately separate text from
#: `_CUT_FMT`: that one reports "there is nothing more"; this one reports
#: "there is more, and it arrived".
_POST_CUT_FMT = (
    "\n    […ПРОЗА ПОСТУСЛОВИЯ СОКРАЩЕНА на {cut} символов из {full}: канал "
    "печати {cap}. РАЗДЕЛЫ КОНТРАКТА НИЖЕ ПРИЕХАЛИ ЦЕЛИКОМ — параметры, "
    "допуски свидетеля, форма вызова. Вырезанное: {rest}]\n")

#: THE THIRD OUTCOME, AND IT IS BETTER THAN THE SECOND. When only a
#: scrap of a phrase would be left of the prose, it is more honest to cut
#: it OUT ENTIRELY than to hand over fourteen characters that read like
#: an unfinished sentence. The sections all get through regardless — and
#: they are exactly what carries the parameter boundaries the model would
#: miss without seeing them.
_POST_GONE_FMT = (
    "\n    […ПРОЗА ПОСТУСЛОВИЯ ВЫРЕЗАНА ЦЕЛИКОМ — {full} символов, канал "
    "печати {cap}. РАЗДЕЛЫ КОНТРАКТА НИЖЕ ПРИЕХАЛИ ЦЕЛИКОМ — параметры, "
    "допуски свидетеля, форма вызова. Вырезанное: {rest}]\n")


def _contract_within_channel(ospec: Any, text: str, rest_of, cap: int = 0) -> str:
    """A contract whose ALL SECTIONS get through, and only the prose is
    shortened.

    MEASURED 12.08.2026, AND IT SETTLED THE QUESTION "IS THIS THE RIG OR
    THE MODEL". The prod sandbox policy (`serving._sandbox_policy`) leaves
    `dsl_module` at its default, and the default is `kir.course.language`.
    A run of `execute_author_script('spec("route_pipe_system")')` under
    exactly this policy returned 3,300 characters, and the word
    «Допуски» is NOT among them. That is, the model authoring the graph
    op never saw the tolerances of its own witness — that is the actual
    channel, not the rig's printing.

    WHY THE FIX IS NOT THE CEILING. The ceiling is the sandbox channel
    minus the reserve for the model's own printing; raising it would take
    away from the author exactly what the channel exists for. What needs
    fixing is the link between the guarantee and the truncation: the
    contract's guarantee is "all of its sections are in place", while
    tail truncation was removing the LAST sections, because it cut by
    length, knowing nothing about structure. Hence the rule: it is always
    the POSTCONDITION PROSE that overflows, so that is what must be
    shortened, from the inside, naming what was cut.

    🔴 THE CENSUS HERE WENT STALE AND COST A BRANCH. The 12.08.2026
    measurement read: "69 ops, median 1,278, p90 2,082, TWO do not fit —
    `route_duct_system` at 3,967 and `route_pipe_system` at 3,904."
    REMEASURED 25.08.2026 — THREE overflow, and the third behaved
    differently:

        op                    text  prose  keep  outcome
        create_solid_blend     3541    477     14  went to TAIL TRUNCATION
        route_duct_system      3967   2850   1960  prose compression
        route_pipe_system      3904   2786   1959  prose compression

    🔴 REMEASURED 07.09.2026: still THREE overflowing, texts now
    3538 / 3899 / 3962 (were 3541 / 3904 / 3967) — the shift came from
    edits to the registry docstrings themselves, neither the channel nor
    the op count moved. The same day a quantity that had never been
    measured here was measured — CHANNEL HEADROOM: how many more
    characters a contract can still hold without losing its tail. For
    `create_solid_blend` that is 18, for `route_duct_system` 1,967 — the
    order is the REVERSE of the `LESSON_CAP - text` estimate, because
    what decides it is the length WITHOUT THE PROSE. It is measured by
    `tests/test_an_overflowing_contract_keeps_its_tail.py` via a binary
    search over THIS function; the same test, on 07.09, had a `continue`
    removed that had been dropping an op that went to tail truncation out
    of the census.

    Both of the old ops have huge prose (2,786–2,850) and `keep` is
    predictably large, so the `200` threshold NEVER fired on them — the
    fallback branch was written and never once executed. The very first
    op with SHORT prose (477) fell into it and lost its tail: the
    `height_mm 1..500000` bounds, the six `category` values, `name
    str<=64`.

    The ratchet for this is
    `tests/test_an_overflowing_contract_keeps_its_tail.py`: the census
    runs across the whole registry, so a fourth such op turns it red by
    itself, on the day it is introduced, not two weeks later.

    THE PROSE BOUNDARIES ARE TAKEN FROM THE AUTHORITY, NOT GUESSED FROM
    THE HEADING'S SHAPE: the value of `ospec.post` is searched for
    VERBATIM. If not found (the docstring was restructured), we honestly
    fall back to tail truncation rather than cutting at a guessed
    boundary.
    """
    cap = cap or LESSON_CAP
    if len(text) <= cap:
        return text
    post = getattr(ospec, "post", "") or ""
    start = text.find(post) if post else -1
    if start < 0 or len(post) < 200:
        return _within_channel(text, rest_of, cap)
    # The worst case of BOTH numbers, as in `_within_channel`: the real
    # text is shorter, so the result is guaranteed to fit, not "roughly".
    rest_hint = (f"print({ospec.name}.__doc__[{len(text)}:{len(text)}])")
    skeleton = _POST_CUT_FMT.format(cut=len(post), full=len(post), cap=cap,
                                    rest=rest_hint)
    без_прозы = len(text) - len(post)
    keep = cap - без_прозы - len(skeleton)
    fmt = _POST_CUT_FMT
    if keep < 200:
        # 🔴 THIS USED TO FALL BACK TO TAIL TRUNCATION, AND THAT CONFLATED
        # TWO QUESTIONS. The threshold of 200 answered both "do the
        # sections not fit even with EMPTY prose" (a real impossibility)
        # and "would little prose be left" (a quality question) at once,
        # and the fallback resolved them the same way — by losing the
        # tail.
        #
        # MEASURED 25.08.2026 across the whole registry: THREE ops
        # overflow the channel, and for `create_solid_blend` (text 3541,
        # prose 477, keep 14) without the prose it would come to 3064 —
        # it FITS. That is, the sections would have fit, but the model
        # was getting a contract without them: without the `height_mm
        # 1..500000` bounds, without the six `category` values, without
        # `name str<=64`. Exactly the numbers it would later be rejected
        # on.
        #
        # The census in the docstring above ("TWO do not fit") was taken
        # 12.08.2026 — the third op appeared later and fell into a branch
        # written for a case that did not exist at the time. The branch
        # could not have turned red: it hands back plausible-looking text
        # with an honest truncation notice.
        gone = _POST_GONE_FMT.format(full=len(post), cap=cap, rest=rest_hint)
        if без_прозы + len(gone) > cap:
            # NOW the impossibility is real: the sections do not fit even
            # with empty prose. The old behavior is the honest one — say
            # that EVERYTHING after the break point failed to arrive.
            return _within_channel(text, rest_of, cap)
        keep, skeleton, fmt = 0, gone, _POST_GONE_FMT
    # The offsets are IN THE DOCSTRING, not in our own text: the advice
    # must work for whoever calls `print(op.__doc__[...])`, and that
    # caller knows nothing about our heading.
    head_len = len(_spec_parts(ospec)[0])
    cut_from = start - head_len + keep
    cut_to = start - head_len + len(post)
    подсказка = f"print({ospec.name}.__doc__[{cut_from}:{cut_to}])"
    вырезка = (fmt.format(full=len(post), cap=cap, rest=подсказка)
               if fmt is _POST_GONE_FMT else
               fmt.format(cut=len(post) - keep, full=len(post), cap=cap,
                          rest=подсказка))
    return text[:start + keep] + вырезка + text[start + len(post):]


def _op_spec_of(name: Any) -> Any:
    """Name (or handle, or the op function itself) -> `OpSpec`, or a
    TYPED refusal with a list of the nearest matches.

    THREE FORMS ARE ACCEPTED, AND THIS IS NOT A RELAXATION. `spec
    (create_wall)` and `spec(w)` (a handle) are unambiguous: an op
    function carries its own `op_spec`, and a handle carries the name of
    its own op — there is nothing to guess. And the cost of a refusal
    here is HIGH: `spec` raises a refusal, a refusal drops the whole
    turn, and the program built up to that line does not make it out
    (`sandbox`: a refusal zeroes out the turn). Dropping the turn over a
    help question because of the argument's form is a bad trade.

    WHAT IS NOT HERE: guessing at a name. A miss does not silently turn
    into "a similar op" — that is exactly the silently-wrong result the
    language must make inexpressible. A miss REFUSES and names the
    candidates.
    """
    from kir import dsl

    if isinstance(name, dsl.Handle):
        return name.op_spec
    ospec = getattr(name, "op_spec", None)
    if ospec is not None and getattr(ospec, "name", None) in _spec.OPS:
        return ospec                              # the language function itself
    key = name.strip() if isinstance(name, str) else None
    if key in _spec.OPS:
        return _spec.OPS[key]
    # RESOLUTION IS EXACT; THE NEAREST-MATCH SEARCH RUNS ON A FOLDED
    # REGISTRY. Accepting «CREATE_WALL» as a name would teach that case
    # does not matter — and `CREATE_WALL(...)` is never called in a
    # script anyway. But the candidate LIST must be useful in exactly
    # this case: without case-folding it produced `set_param, query_list,
    # create_tag` — five useless lines for a miss fixed by one letter.
    near = difflib.get_close_matches((key or str(name)).lower(),
                                     sorted(_spec.OPS), n=5, cutoff=0.0)
    raise dsl.DslRefusal([dsl.Diagnostic(
        code=PARSE_UNKNOWN_OP, field_name="op_name",
        expected="имя операции реестра, строкой", got=repr(name),
        candidates=near,
        message_ru=(
            f"операции «{name}» в реестре KIR нет — а реестр закрыт: имени, "
            f"которого в нём нет, не существует ни в одной форме входа.\n"
            f"БЛИЖАЙШИЕ ПО НАПИСАНИЮ: {', '.join(near)}.\n"
            f"СЛЕДУЮЩИЙ ХОД: возьми имя из списка выше, либо позови spec() БЕЗ "
            f"аргумента — она напечатает ВЕСЬ реестр по роду объекта в "
            f"квитанцию этого же хода. Принимается имя строкой "
            f"(spec(\"create_wall\")), сама функция опа (spec(create_wall)) "
            f"или ручка вызова (spec(w))."))])


def _macro_names() -> tuple[str, ...]:
    """Macro names — ASKED OF `macros`, not listed here."""
    from kir.macros import MACRO_OPS
    return tuple(MACRO_OPS)


def _macro_contract(name: str) -> str:
    """A MACRO's contract, assembled from its own registries.

    A macro is not an op: it has no `OpSpec`, no postcondition and no
    grounding pool — it EXPANDS into ordinary ops before any checking
    happens. So its contract has a different shape, and the one thing
    that matters in it is: WHAT CAN BE PUT INSIDE IT.
    """
    from kir import macros

    lines = ["МАКРОС %s — раскрывается в обычные опы ДО проверки; форма поля "
             "`program`, в скрипте (`program_py`) макросов нет: там повтор "
             "пишет сам питон циклом." % name]
    if name == "stack":
        lines += [
            "  stack(levels, h_mm, base_elev_mm, name_prefix, floor[, transform])",
            "  Создаёт уровни и повторяет `floor` на каждом. `level` членам "
            "проставляет САМА экспансия — задавать его внутри нельзя.",
            "  ЧЛЕНЫ, БЕРУЩИЕ level: " + ", ".join(macros._STACKABLE) + ".",
            "  ЧЛЕНЫ ХОСТЯЩИЕСЯ (уровень берут у ХОЗЯИНА, а не своим полем):",
        ]
        for op_name, why in sorted(macros._STACKABLE_HOSTED.items()):
            lines.append("    %s — %s" % (op_name, why))
        lines += [
            "  Хозяин обязан быть ЧЛЕНОМ того же этажа: ссылка переезжает по "
            "этажам вместе с ним. Хозяин вне набора — типизированный отказ "
            "(иначе дверь каждого этажа повисла бы на стене первого).",
            "  Хозяин по `element_id` — законно: это настоящий элемент "
            "документа, один для всех этажей.",
        ]
    elif name == "series":
        lines += [
            "  series(count, track, items) — повтор вдоль ТРЕКА; уровней не "
            "создаёт и `level` не переписывает.",
            "  ЧЛЕНЫ: " + ", ".join(macros._SERIES_ABLE) + ".",
            "  Хостящиеся члены переезжают со своим хозяином так же, как в "
            "stack.",
        ]
    elif name == "grid_array":
        lines += [
            "  grid_array(nx, ny, dx_mm, dy_mm[, origin_mm, margin_mm, "
            "prefix_x, prefix_y]) — сетка ОСЕЙ. Членов не принимает: "
            "порождает только `create_grid`.",
        ]
    return "\n".join(lines)


def spec(op_name: Any = None) -> None:
    """The CONTRACT of one operation from the registry — or the full
    table of contents of the registry.

        spec()                  all ops by kind of object
        spec("create_wall")     call form, slots with kinds and bounds,
                                the form of each selector, the grounding
                                pool, the postcondition and the witness's
                                tolerances

    IT PRINTS, and does not return: the channel to the model is the
    receipt's `stdout`, and a returned string that nobody printed would
    simply be lost.

    THERE IS ONE SOURCE — THE REGISTRY. Not one line of the contract is
    written here by hand: the op's docstring is assembled by
    `dsl._docstring` from `spec.OPS` at import time, and the call form by
    `dsl._call_head`. A second copy of the contract (a document sitting
    next to the code) would drift from the registry at the very first
    boundary edit, and it would drift silently.

    AN UNKNOWN NAME IS A TYPED REFUSAL (KIR-P002) with a list of the
    nearest matches, not a `NameError`: a bare «name is not defined» says
    neither that the registry is closed nor what the thing being looked
    for was called.

    PRINTING IS BOUNDED BY THE sandbox's CHANNEL (`MAX_STDOUT_CHARS`
    minus the reserve for your own printing). Help text that does not
    fit is truncated BY US, and names the remainder as a verbatim line —
    a silently truncated contract is indistinguishable from a contract
    with no tolerances.

    A SCRIPT THAT IS PURE RECON IS NOT A REFUSAL. This is a THIRD KIND OF
    ANSWER, `KIR-B013`: there is no program, but the script ANSWERED. The
    help text travels in the receipt (`stdout`), and the turn is not
    recorded as a failure.

    🔴 THIS LINE SAID THE OPPOSITE UNTIL 18.08.2026, AND IT SAID IT
    WRONG. The earlier wording taught: "a script that is pure recon is a
    refusal, and correctly so — `spec()` with no operation gives
    KIR-B007." That day's measurement across 627 scripts from the live
    rig: of the 365 calls that landed in the `KIR-B007` bucket, **357
    (97.8 %) printed an answer**, and all 8 that stayed silent were
    deliberately scrubbed drafts. The real author failures in that
    bucket number **zero**. In other words, a third of all calls to that
    door were being recorded as failures for the sole crime of the
    author asking a question.

    THE DISCRIMINATOR IS PRINTING, AND ONLY PRINTING (`sandbox._answered`).
    Whitespace-only printing does not count as an answer. The signal
    "the script touched `model`/`spec`" fails by measurement:
    `model.levels()` with no catalog supplied raises and goes to
    `KIR-B006` even BEFORE the program is assembled. What we observe is
    "it answered", not "it asked" — and that is also the only thing that
    gives the MODEL anything: an answer nobody printed does not exist for
    the next turn.

    WHAT REMAINS A REFUSAL: a script that assembled no program AND said
    nothing is still `KIR-B007` — emptiness proves nothing.

    And `ok` on a recon run stays a LIE: green here is earned by
    producing evidence of a record, and a recon run has none and can have
    none. "Not a refusal" and "success" are different things, and they
    must not be confused.

    It is still cheaper to call `spec` inside the same script that writes
    the program — that is one turn instead of two.
    """
    строка = _note_read("spec", op_name)
    if op_name is None:
        _emit(_within_channel(_spec_index(),
                              lambda _keep: "имена целиком — op_names()"))
        return
    # 🔴 A MACRO HAS A CONTRACT TOO, AND UNTIL 15.08.2026 NO DOOR HANDED
    # IT OUT. `spec("stack")` used to answer "the operation is not in the
    # registry" — formally correct (a macro is not an op) and practically
    # wrong: the author was asking about a capability that exists and was
    # told it does not. Exactly the outcome this whole package was
    # written to forbid, only in the currency of text.
    #
    # Assembled FROM THE MACRO'S OWN REGISTRIES, not one line by hand: the
    # member list is `_STACKABLE`, the hosted ones are `_STACKABLE_HOSTED`
    # together with their justifications. A second copy would drift at
    # the very first new member.
    if isinstance(op_name, str) and op_name in _macro_names():
        _emit(_within_channel(_macro_contract(op_name),
                              lambda _keep: "остальные макросы — spec()"))
        return
    from kir.dsl import DslRefusal
    try:
        ospec = _op_spec_of(op_name)
    except DslRefusal as промах:
        # THE CODE TRAVELS WITH THE TEXT. Without it a typed refusal
        # would degrade into prose: `KIR-P002` is the miss's machine
        # identity, and the receipt is not read only by an eye. `course`/
        # `recipe` still have no code today (they used to raise a bare
        # KeyError); `refused` in the ledger is what gives them
        # distinguishability.
        диаг = промах.diagnostics[0]
        _промах_чтения(строка, диаг.message_ru, код=диаг.code)
        return
    head, doc = _spec_parts(ospec)
    # The tail offset is an INDEX INTO THE DOCSTRING, not into the
    # printed text: the slice is taken from `__doc__`, and advice that
    # counted together with the heading would miss by exactly its length.
    _emit(_contract_within_channel(
        ospec, head + doc,
        lambda keep: (f"print({ospec.name}.__doc__"
                      f"[{max(0, keep - len(head))}:])")))


# ─────────────────────────────────────────── UNIT: assembly as one group

#: The nesting depth of `unit()`. Read by `phase()` — see there for why.
_UNIT_DEPTH = 0


class Unit:
    """What is left of `with unit(...)`: members, the reading, and the
    group's handle."""

    __slots__ = ("name", "placements", "members", "handle",
                 "index", "unit_id", "reads_as", "as_group", "op_ids", "line")

    def __init__(self, name: str | None, placements: list, *,
                 index: int = 0, reads_as: str | None = None,
                 as_group: bool = True, line: int | None = None) -> None:
        self.name = name
        self.placements = placements
        self.members: list[dict] = []
        self.handle: Any = None
        self.index = index
        #: The unit's address. Deterministic and independent of the name:
        #: the author's name can repeat or be absent, while an
        #: observation must always be addressable, unambiguously.
        self.unit_id = "u%d" % index
        self.reads_as = reads_as
        self.as_group = as_group
        #: ids of the ops IN THE OUTER program that represent the unit
        #: there: one group op (`as_group=True`) or all members (`False`).
        self.op_ids: list[str] = []
        self.line = line

    def __repr__(self) -> str:
        return (f"Unit({self.name!r}, членов {len(self.members)}, "
                f"вхождений {len(self.placements) + 1})")

    def member_ids(self) -> list[str]:
        return [str(m.get("id")) for m in self.members if m.get("id") is not None]

    def as_dict(self) -> dict:
        """A row of the envelope's `units` table — exactly what travels
        out to JSON.

        `reads_as` always travels, `None` included: the absence of a
        reading is the author's decision "do not check the reading", and
        it must be visible, not look like a lost field.
        """
        return {"index": self.index, "unit_id": self.unit_id,
                "name": self.name, "reads_as": self.reads_as,
                "as_group": self.as_group,
                "op_ids": list(self.op_ids),
                "member_ids": self.member_ids()}

    def at(self) -> str:
        """The unit's address, for a REFUSAL."""
        label = f"«{self.name}»" if self.name else "без имени"
        return f"{label} ({self.unit_id}" + (
            f", строка {self.line})" if self.line else ")")


class _UnitLedger:
    """The units of ONE program. Lives alongside the program, like the
    phase book."""

    __slots__ = ("units",)

    def __init__(self) -> None:
        self.units: list[Unit] = []


#: The unit book LIVES ALONGSIDE THE PROGRAM — for exactly the same weak
#: keys and exactly the same reason as the phase book: a module-level
#: book would survive `dsl.reset()` and attribute the previous script's
#: units to the next one.
_UNIT_LEDGERS: "weakref.WeakKeyDictionary[Any, _UnitLedger]" = \
    weakref.WeakKeyDictionary()


class _UnitContext:
    """A context that gathers what is written inward into ONE
    `create_group`.

    WHAT THIS DOES NOT DO. It does not check semantics: the truth about
    whether members are correct belongs to the compiler, and it already
    states it precisely — `ground._ground_members` reattributes a
    member's refusal onto the group op itself and names the member by
    ITS OWN id, while `authoring_validation` refuses `by:ref` inside a
    member with a separate diagnosis. A second set of rules here would
    drift from the first at the very first registry edit.

    WHAT THIS DOES. It always records the unit — as a slice and a row in
    the envelope's `units` table, following the pattern of `phase()`. In
    addition, when `as_group=True` (the default), it opens a temporary
    program (`dsl.program()`), takes what accumulated, and places ONE
    `create_group` op into the outer program. The group has not a single
    field of its own: `members`/`placements`/`name` are all registry
    names.

    REFERENCES INSIDE A GROUP — fixed 15.08.2026, the earlier text here
    LIED. There has been no blanket ban on `{"by": "ref"}` inside a
    member since 12.08.2026. The living rule sits in
    `authoring_validation` and consists of two refusals and one
    permission: OUT of the member set is a refusal, FORWARD (to a member
    below) is a refusal, to a neighbor ABOVE is legal — member order is
    creation order.
    """

    __slots__ = ("_unit", "_inner", "_outer", "_start", "_reads_as", "_as_group")

    def __init__(self, name: str | None, placements: Iterable, *,
                 reads_as: str | None = None, as_group: bool = True) -> None:
        self._reads_as = reads_as
        self._as_group = as_group
        self._unit = Unit(name, [list(p) for p in (placements or ())],
                          reads_as=reads_as, as_group=as_group)
        self._inner = None
        self._outer = None
        self._start = 0

    def __enter__(self) -> Unit:
        from kir import dsl
        global _UNIT_DEPTH
        # THE READING IS CHECKED ON THE WAY IN, NOT ON THE WAY OUT: a
        # refusal raised inside the block carries the author's LINE
        # NUMBER (the sandbox sees the `<kir-script>` frame), while one
        # raised at the drain no longer does. The same argument that
        # shapes the phase.
        if self._reads_as is not None:
            from kir.assembly_view import UNIT_READS, UNIT_READS_RU
            if self._reads_as not in UNIT_READS:
                known = ", ".join(
                    "%s — %s" % (n, UNIT_READS_RU.get(n, "")) for n in
                    sorted(UNIT_READS))
                raise _refuse_phase(
                    TYPE_BAD_ENUM, field_name="reads_as", got=self._reads_as,
                    expected=sorted(UNIT_READS),
                    message=(
                        f"прочтение {self._reads_as!r} не объявлено. Реестр "
                        f"прочтений ОТКРЫТ на дополнение, но имя обязано в нём "
                        f"быть: непроверяемое прочтение — это обещание "
                        f"проверки, которой нет. Известны: {known}. "
                        f"СЛЕДУЮЩИЙ ХОД: возьми одно из них либо не указывай "
                        f"`reads_as` вовсе — единица запишется и без него"))
        if self._as_group is False and self._unit.placements:
            raise _refuse_phase(
                TYPE_BAD_TYPE, field_name="placements",
                got=len(self._unit.placements),
                message=(
                    "placements заданы при as_group=False. Вхождения — "
                    "свойство ГРУППЫ Ревита: без группы повторять нечего, и "
                    "тихо их проглотить значило бы потерять написанное "
                    "автором. СЛЕДУЮЩИЙ ХОД: либо as_group=True, либо убери "
                    "placements и напиши повторения сам"))
        self._unit.line = _author_line()
        self._outer = dsl.current()
        self._start = len(self._outer.ops) if self._outer is not None else 0
        self._inner = dsl.program() if self._as_group else None
        # A COUNTER, NOT A FLAG: units nest inside one another legally,
        # and `phase()` must tell "inside a unit" from "outside" at any
        # depth. What this guards is in `_PhaseContext.__enter__`.
        _UNIT_DEPTH += 1
        return self._unit

    def __exit__(self, exc_type, exc, tb) -> bool:
        from kir import dsl
        global _UNIT_DEPTH
        _UNIT_DEPTH = max(0, _UNIT_DEPTH - 1)
        inner, self._inner = self._inner, None
        if inner is not None:
            collected = [dict(op) for op in inner.ops]
            inner.__exit__(exc_type, exc, tb)  # the current program back in place
        else:
            outer = self._outer
            collected = ([dict(op) for op in outer.ops[self._start:]]
                         if outer is not None else [])
        if exc_type is not None:
            return False                      # the author's exception travels outward
        self._unit.members = collected
        if not collected:
            raise dsl.DslRefusal([dsl.Diagnostic(
                code=dsl.TYPE_BAD_TYPE, field_name="members",
                expected="1..200 опов", got=0,
                message_ru=("unit() не собрал ни одной операции: единица без "
                            "членов не описывает ничего. Пиши опы ВНУТРИ "
                            "блока with"))])
        if self._as_group:
            kwargs: dict[str, Any] = {"members": collected,
                                      "placements": self._unit.placements}
            if self._unit.name is not None:
                kwargs["name"] = self._unit.name
            self._unit.handle = dsl.OP_FUNCTIONS["create_group"](**kwargs)
            handle_id = getattr(self._unit.handle, "id", None)
            self._unit.op_ids = [str(handle_id)] if handle_id is not None else []
            # THE MEMBERS' PROVENANCE TRAVELS WITH THEM.
            #
            # `__enter__` opens a SEPARATE program, and `_append`
            # honestly records each member's address in its own
            # `_lineage`. Only the ops themselves were taken from there —
            # the inner program's sidecar died along with it, and every
            # member inherited the GROUP's address, that is, the line of
            # the `with` itself.
            #
            # 🔴 THIS WAS NOT "NO ADDRESS", IT WAS A WRONG ADDRESS.
            # Measured 27.08.2026: three walls in a loop, an error in the
            # second one (line 7) — the refusal printed "line 3", the
            # `with` line. A plausible value is more dangerous than a
            # missing one: nobody argues with it (form 44), and the
            # author would go off to fix a line that has no error in it.
            #
            # THE KEY WAS NOT INVENTED HERE, IT WAS TAKEN FROM THE
            # REFUSAL. `compiler._group_member_diagnostic` already
            # addresses a member as `members[<id>]`, and this form
            # RESOLVES THE COLLISION: the inner program has its own
            # `_ids` counter, so `create_wall` outside and inside the
            # unit are both called `wall1`. A flat merge would have given
            # the member the line of someone else's wall. Introducing a
            # second address form here would have let it drift from the
            # refusal at the very first edit.
            #
            # THE GROUP KEY REMAINS: it addresses the `with` itself, and
            # that is a separate, legitimate fact — carried by
            # `Unit.line`.
            if inner._lineage:
                target = dsl.current()
                if target is not None:
                    for member_oid, frames in inner._lineage.items():
                        target._lineage[f"members[{member_oid}]"] = frames
        else:
            # A SLICE, LIKE THE PHASE'S: the ops stay in the program
            # byte-for-byte, unchanged.
            self._unit.op_ids = self._unit.member_ids()

        # ═══ THE UNIT IS ALWAYS RECORDED — AND THAT IS THE MAIN POINT OF THIS BLOCK ═══
        #
        # Before 15.08.2026 `unit()` meant EXACTLY "make a Revit group":
        # the members collapsed into one `create_group`, and everything
        # the author had said about their intent — the name, the bounds
        # of the set — stopped existing the instant it was expanded. An
        # observation then had to address it element by element, meaning
        # the model wrote as a composite and read element by element.
        #
        # Now recording the unit is ORTHOGONAL to whether a group gets
        # made: the `units` table travels in the envelope on the pattern
        # of `phases`, and `as_group` decides only the form of the record
        # in Revit. The ops themselves do not change by a single byte in
        # the process — their digest signs the program, and a tag written
        # into the op would have shifted the signature of a building that
        # never changed.
        outer = self._outer if self._outer is not None else dsl.current()
        if outer is not None:
            ledger = _UNIT_LEDGERS.get(outer)
            if ledger is None:
                ledger = _UnitLedger()
                _UNIT_LEDGERS[outer] = ledger
            self._unit.index = len(ledger.units)
            self._unit.unit_id = "u%d" % self._unit.index
            ledger.units.append(self._unit)
        return False


def unit(name: str | None = None, *, reads_as: str | None = None,
         as_group: bool = True, placements: Iterable = ()) -> _UnitContext:
    """A UNIT OF INTENT: a set of elements that can be spoken of as one.

        with unit("фасадная лента, оси 1–5, этажи 2–3", reads_as="continuous"):
            for lvl in levels[1:3]:
                for a, b in spans:
                    create_wall(p0_mm=a, p1_mm=b, level=lvl, type="Витраж 200")

    WHY. This compiler's checkability works at arity 1: op -> element ->
    postcondition. Intent lives at arity N — "these walls are one strip"
    — and the postcondition cannot say that: it stands on one op and
    knows nothing of its neighbor. A striped wall (three walls built end
    to end, declared as one strip but of different types) passes all
    three of the witness's checks, because each wall on its own is
    flawless. The unit is the place where a set becomes an object of
    judgment.

    `reads_as` — HOW TO READ this set. The registry of readings is OPEN
    to extension (`assembly_view.UNIT_READS`), and it is not a dictionary
    of composites: there are unboundedly many buildings, but the ways of
    reading them number only a handful (continuous, coaxial, coplanar,
    tiered, closing). The composite remains a function the author writes
    themselves; all they bring here is the reading. Without `reads_as`
    the unit is still recorded — it remains an ADDRESS by which an
    observation can name the intent — but it is not judged.

    `as_group` — THE FORM OF THE RECORD IN REVIT, and it is orthogonal to
    intent. `True` (the default, today's behavior byte for byte): members
    collapse into one `create_group`, and the group is edited in Revit as
    a single whole. `False`: the ops stay in the program as they are, and
    the unit lives only as a row in the envelope's table. The default is
    deliberately not changed in this wave: five consumers recognize
    `create_group` (`course.measure`, `sdk`, `acceptance`,
    `design.coherence`, `clash_bundle`), and changing the default is a
    separate decision with a separate cost.

    `placements` — the offsets [dx, dy(, dz)] of additional occurrences
    of the group; occurrence 0 is the members themselves at absolute
    coordinates. Only with `as_group=True`: with no group there is
    nothing to repeat, and that is a typed refusal, not a silent
    no-op.

    REFERENCES INSIDE A GROUP (fixed 15.08.2026 — the earlier text here
    LIED). There has been no blanket ban on `{"by": "ref"}` inside a
    member since 12.08.2026. There is one living rule and it sits in
    `authoring_validation` (`:1671-1716`): a reference OUT of the member
    set is a refusal; a reference FORWARD, to a member declared below, is
    a refusal; a reference to a neighbor ABOVE in the list is LEGAL —
    member order is creation order.
    """
    return _UnitContext(name, placements, reads_as=reads_as,
                        as_group=as_group)


# ══════════════════════════════════════════════════════════════════════════
# PHASE: ONE LINK OF THE CONSTRUCTION PLAN
# ══════════════════════════════════════════════════════════════════════════
#
# WHY THIS IS HERE AND NOT A SEPARATE TOOL. The plan draft
# (KIR_PROGRAM_OF_PROGRAMS_DRAFT, 17.07) proposed a SECOND DOOR —
# `plan_build`, which calls `revit_ir` phase by phase. It was written
# before `program_py` existed, and today a second door would repeat the
# story of `sdk.py`: 493 lines, five weeks, unreachable, because there
# was no door to it. Phases already have a door — the very same author's
# script in which the model already writes the building. So a phase is
# not a tool but a CONTEXT, `unit()`'s sibling: one gathers what is
# written inward into one GROUP, the other into one PROGRAM (one
# transaction, one checkpoint).
#
# WHAT THIS FILE DOES AND DOES NOT DO. It does: marks out boundaries,
# checks them BEFORE any effect, and turns a reference that crossed a
# boundary into a tag that can be substituted in. It does NOT: it does
# not execute phase by phase and does not cut the program — that is STEP
# 2, and it was done 09.08н elsewhere, because execution does not belong
# to the language. Cutting a plan into a batch is done by
# `compiler.split_phases`, substituting a tag by
# `compiler.substitute_phase_results`, and running the links one at a
# time by `serving._run_plan`. Execution never moves in here: the
# sandbox executes the script TWICE (`replay_check`), and a record
# living inside it would happen twice.
#
# THE LAST LINE OF DEFENSE STAYS FAIL-CLOSED. A program with `phases`,
# handed to `plan_program` in one piece, still refuses (KIR-P003) — and
# that is not a leftover from yesterday but a law: `plan_program`
# executes ONE transaction, while a phase promises a checkpoint between
# them. Silently gluing phases together would mean declaring a
# checkpoint that does not exist. Only the refusal text changed: it now
# names the plan and says how to cut it, instead of "unknown envelope
# field".

#: WHAT A REFERENCE THAT CROSSED A PHASE BOUNDARY LOOKS LIKE. Step 2 rests
#: on this name: it substitutes, in place of the tag, `{"by":
#: "element_id", "value": <id from the WITNESS of the producing phase>}`
#: — and that is the only thing it needs to know from here.
#:
#:     {"by": "phase_result", "value": "<producing op's id>", "phase": <N>}
#:
#: WHY NOT `by=ref`. `{"by": "ref"}` addresses an op of THIS SAME
#: program and is resolved by the compiler before emission. By the time
#: the next phase executes, the producing element has already been
#: committed by a SEPARATE transaction, and a reference to it inside the
#: program no longer exists at all. The system already states this same
#: fact elsewhere: `design_check._merge_bundle` refuses a cross-program
#: `by=ref` with the words «соседняя программа — отдельная транзакция, и
#: к её исполнению id уже не существует». The tag is the same fact
#: BEFORE the refusal: a form that can be substituted in, instead of a
#: form that is left only to be forbidden.
#:
#: `value` is the id of the PRODUCING op, not the element's name: the
#: witness addresses ops by id (`op_outcomes`), so step 2's substitution
#: is a lookup by key, not a guess by name. `phase` is the number of the
#: producing phase; the phase's name lives in the envelope table, and
#: repeating it in every tag would mean setting up a second source of
#: truth about the name.
#:
#: THE NAME MOVED TO THE REGISTRY (`spec.CROSS_PHASE_BY`), and what is
#: left here is an alias. The reason is that step 2 is done: the tag is
#: substituted by `compiler.substitute_phase_results`, and the compiler
#: has no right to import the course (the course imports it for the
#: budget — that would be a cycle). A literal kept in two places would
#: have drifted apart silently, the way `SOLO_OPS` already drifted apart
#: in two places out of three.
CROSS_PHASE_BY = _spec.CROSS_PHASE_BY


class Phase:
    """What is left of `with phase(...)`: the name, the number, and the
    addresses of the phase's ops."""

    __slots__ = ("name", "index", "op_ids", "line")

    def __init__(self, name: str, index: int, line: int | None) -> None:
        self.name = name
        self.index = index
        #: the script line on which the phase was opened. Does NOT travel
        #: into the program: execution does not need it, but a refusal
        #: does, and that is what uses it.
        self.line = line
        self.op_ids: list[str] = []

    def __repr__(self) -> str:
        return (f"Phase({self.index}, {self.name!r}, "
                f"опов {len(self.op_ids)})")

    def as_dict(self) -> dict:
        """A row of the envelope's `phases` table — exactly what travels
        out to JSON."""
        return {"index": self.index, "name": self.name,
                "op_ids": list(self.op_ids)}

    def at(self) -> str:
        """The phase's address, for a REFUSAL: the name, the number, and
        the line on which it was opened."""
        return f"«{self.name}» (№{self.index}" + (
            f", строка {self.line})" if self.line else ")")


class _PhaseLedger:
    """The phases of ONE program: their order, whose op belongs to whom,
    how far everything has been sorted out."""

    __slots__ = ("phases", "owner", "watermark", "open_name")

    def __init__(self) -> None:
        self.phases: list[Phase] = []
        #: op id -> the number of its phase. CLOSED phases only: while a
        #: phase is still open, its ops are deliberately absent here —
        #: this is what the rule "a reference inside a phase stays
        #: `by=ref`" rests on (see `_mark_cross_phase`).
        self.owner: dict[str, int] = {}
        #: how many of the program's ops have already been sorted into
        #: phases. The gap against `len(program.ops)` is exactly "an op
        #: written outside any phase".
        self.watermark = 0
        self.open_name: str | None = None


#: The phase book LIVES ALONGSIDE THE PROGRAM, not in the module. A
#: module-level book would survive `dsl.reset()` and would attribute the
#: previous script's phases to the next one — invisible in the sandbox
#: (the interpreter is fresh for every script), but visible right away in
#: one process (tests, the rig). Weak keys: the book dies together with
#: its program, and there is no one who needs to, or should, reset it by
#: hand.
_LEDGERS: "weakref.WeakKeyDictionary[Any, _PhaseLedger]" = \
    weakref.WeakKeyDictionary()


def _author_line() -> int | None:
    """The AUTHOR's line number, if we are inside script execution.

    Frames of our own pipeline are skipped: the model needs to fix ITS
    OWN code, and that is the same filter the sandbox applies
    (`script_frames`)."""
    frame: Any = sys._getframe(1)
    while frame is not None:
        if frame.f_code.co_filename == SCRIPT_FILENAME:
            return frame.f_lineno
        frame = frame.f_back
    return None


def _refuse_phase(code: str, message: str, **fields: Any) -> Exception:
    """A typed phase refusal — IN THE COMPILER'S DICTIONARY, not as text.

    Raised FROM THE BODY OF THE SCRIPT deliberately: only there does the
    sandbox see the `<kir-script>` frame and place the LINE NUMBER and
    the line itself into the refusal (KIR-B006 wraps the `DslRefusal`
    text). A refusal raised AFTER the script — at the program's drain —
    no longer gets a line; so everything that can be checked inside the
    `with` block is checked inside it, and outside the block exactly one
    check remains (the tail, `_refuse_tail`) that the block could not
    reach.
    """
    from kir import dsl
    return dsl.DslRefusal([Diagnostic(code=code, message_ru=message, **fields)])


def _ref_targets(value: Any) -> list[str]:
    """Every target of `{"by": "ref"}` inside a value, nested however
    deep.

    The traversal is GENERIC, not by field name: the owner is called
    `host` on an opening, `target` on a tag, and `members` on a group,
    and a list of names would have drifted from the schema at the very
    first new operation.

    WHY OUR OWN, AND NOT `design_check._ref_targets`. That one lives in
    the verdict module, which pulls in shapely/numpy/networkx: measured
    03.08 at +536 ms and +43 MB per run, and the sandbox executes the
    script TWICE (`replay_check`). Importing all that for twelve lines of
    traversal would cost this to EVERY script with phases, including
    ones that never call the verdict at all (which is exactly why the
    warm-up in `language.py` is conditional). The traversal is
    structural, not semantic: there is nothing for it to drift from.
    """
    if isinstance(value, Mapping):
        if value.get("by") == "ref":
            return [str(value.get("value"))]
        out: list[str] = []
        for item in value.values():
            out.extend(_ref_targets(item))
        return out
    if isinstance(value, (list, tuple)):
        out = []
        for item in value:
            out.extend(_ref_targets(item))
        return out
    return []


def _mark_cross_phase(value: Any, owner: Mapping[str, int]) -> Any:
    """`{"by": "ref"}` onto an op of a CLOSED phase -> a `CROSS_PHASE_BY`
    tag.

    `owner` carries only closed phases, so a reference to a neighbor IN
    THE SAME phase never lands in it and stays `by=ref` untouched — just
    as it does today. A reference to an unknown id also stays untouched:
    a dangling reference is a parse-time fact about the program
    (KIR-L003 on the plan), not a fact about phases, and swapping one
    diagnosis for the other would lead the fix astray.
    """
    if isinstance(value, Mapping):
        if value.get("by") == "ref":
            producer = owner.get(str(value.get("value")))
            if producer is None:
                return dict(value)
            return {"by": CROSS_PHASE_BY, "value": str(value.get("value")),
                    "phase": producer}
        return {key: _mark_cross_phase(item, owner)
                for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_mark_cross_phase(item, owner) for item in value]
    return value


def _census(ops: Iterable[Mapping]) -> str:
    """What kind of ops, by discipline. A line for a REFUSAL: it is what
    the model will cut by."""
    tally: dict[str, int] = {}
    for op in ops:
        name = str(op.get("op", "?"))
        tally[name] = tally.get(name, 0) + 1
    return ", ".join(f"{name} {count}" for name, count
                     in sorted(tally.items(), key=lambda kv: (-kv[1], kv[0])))


class _PhaseContext:
    """A context that declares what is written inward as ONE link of the
    plan.

    WHAT THIS DOES NOT DO. It does not execute, does not cut the program
    into pieces, and does not touch a single op except references that
    crossed a boundary. The program that comes out is THE SAME ONE, plus
    a `phases` table in the envelope.

    WHAT THIS DOES. It remembers the position in the program at which the
    phase was opened, takes the chunk written since then, and checks four
    things about it, ALL BEFORE ANY EFFECT: the phase is not empty; the
    phase fits the author's budget; there is exactly one solo op in the
    phase; references leading into another phase are named as a tag,
    while ones leading FORWARD are a refusal.
    """

    __slots__ = ("_name", "_program", "_ledger", "_start", "_phase")

    def __init__(self, name: Any) -> None:
        if not isinstance(name, str) or not (1 <= len(name.strip()) <= 64):
            raise _refuse_phase(
                PLAN_PHASE_SHAPE, field_name="name",
                expected="строка 1..64 символа", got=repr(name),
                message=("у фазы обязано быть ИМЯ: отказ и отчёт называют "
                         "фазу, на которой план встал, и безымянное звено "
                         "нечем назвать. phase(\"каркас первого этажа\")"))
        self._name = name.strip()
        self._program: Any = None
        self._ledger: _PhaseLedger | None = None
        self._start = 0
        self._phase: Phase | None = None

    def __enter__(self) -> Phase:
        from kir import dsl
        if _UNIT_DEPTH:
            raise _refuse_phase(
                PLAN_PHASE_SHAPE, field_name="phase",
                message=("фаза внутри unit(): члены группы — это ОДИН оп "
                         "(`create_group`) внешней программы, и своей "
                         "транзакции у них нет. Значит и своей фазы быть не "
                         "может. СЛЕДУЮЩИЙ ХОД: открой фазу СНАРУЖИ блока "
                         "unit(), а единицу пиши внутри фазы"))
        program = dsl.current()
        ledger = _LEDGERS.get(program)
        if ledger is None:
            ledger = _PhaseLedger()
            _LEDGERS[program] = ledger
        if ledger.open_name is not None:
            raise _refuse_phase(
                PLAN_PHASE_SHAPE, field_name="phase", got=self._name,
                message=(f"фаза «{self._name}» открыта внутри фазы "
                         f"«{ledger.open_name}». Фазы — ПОСЛЕДОВАТЕЛЬНОСТЬ, а "
                         f"не дерево: каждая исполняется своей транзакцией, и "
                         f"вложенной транзакции у плана нет. СЛЕДУЮЩИЙ ХОД: "
                         f"закрой одну фазу и открой следующую рядом"))
        twin = next((p for p in ledger.phases if p.name == self._name), None)
        if twin is not None:
            raise _refuse_phase(
                PLAN_PHASE_SHAPE, field_name="name", got=self._name,
                candidates=[p.name for p in ledger.phases],
                message=(f"фаза {twin.at()} уже была: имя фазы — её АДРЕС в "
                         f"плане и в отчёте, и второе такое же имя делает "
                         f"адрес неоднозначным. Дописать опы в уже закрытую "
                         f"фазу тоже нельзя: порядок исполнения перестал бы "
                         f"совпадать с порядком в скрипте, и это была бы "
                         f"граница, которую ты не рисовал. СЛЕДУЮЩИЙ ХОД: "
                         f"назови новую фазу иначе"))
        stray = len(program.ops) - ledger.watermark
        if stray:
            loose = list(program.ops[ledger.watermark:])
            where = (f"после фазы {ledger.phases[-1].at()}"
                     if ledger.phases else "до первой фазы")
            raise _refuse_phase(
                PLAN_PHASE_SHAPE, field_name="ops", got=stray,
                message=(
                    f"{stray} операций написано ВНЕ фазы ({where}): "
                    f"{_census(loose)}. Скрипт, нарисовавший хоть одну "
                    f"границу, обязан разнести по фазам ВСЁ: неразмеченный оп "
                    f"пришлось бы либо приписать к соседней фазе, либо завести "
                    f"ему фазу — и то и другое было бы границей, которую автор "
                    f"не рисовал, то есть транзакцией, о которой он не знает. "
                    f"СЛЕДУЮЩИЙ ХОД: оберни эти операции в свою фазу — либо "
                    f"убери phase() из скрипта вовсе (программа без фаз "
                    f"остаётся ровно тем, чем была)"))
        self._program = program
        self._ledger = ledger
        self._start = len(program.ops)
        self._phase = Phase(self._name, len(ledger.phases), _author_line())
        ledger.open_name = self._name
        return self._phase

    def __exit__(self, exc_type, exc, tb) -> bool:
        from kir import dsl
        ledger, self._ledger = self._ledger, None
        if ledger is None or self._phase is None:
            # Closing without opening: the context was called by hand. A
            # bare `AssertionError` has no business here — only typed
            # refusals travel outward, and this one names exactly what
            # did not add up.
            raise _refuse_phase(
                PLAN_PHASE_SHAPE, field_name="phase", got=self._name,
                message=(f"фаза «{self._name}» закрывается, не будучи "
                         f"открытой. Фаза — это блок `with phase(...)`; "
                         f"звать её __enter__/__exit__ руками нельзя"))
        ledger.open_name = None               # always close, even on a refusal
        if exc_type is not None:
            return False                      # the author's exception travels outward
        program = self._program
        if dsl.current() is not program:
            raise _refuse_phase(
                PLAN_PHASE_SHAPE, field_name="phase", got=self._name,
                message=(f"фаза «{self._name}» открыта на одной программе, а "
                         f"закрывается на другой: внутри блока осталась "
                         f"незакрытая program(). Фаза — кусок ОДНОЙ программы, "
                         f"и кусок двух программ сразу не существует"))
        ops = list(program.ops[self._start:])
        phase = self._phase
        if not ops:
            raise _refuse_phase(
                PLAN_PHASE_SHAPE, field_name="ops", got=0,
                message=(f"фаза {phase.at()} не собрала ни одной операции. "
                         f"Пустая фаза — это пустая транзакция и лишний "
                         f"чекпойнт: строить в ней нечего. Пиши опы ВНУТРИ "
                         f"блока with"))
        if len(ops) > MAX_OPS_PER_PROGRAM:
            raise _refuse_phase(
                PLAN_LIMIT, field_name="ops",
                expected=f"<={MAX_OPS_PER_PROGRAM}", got=len(ops),
                message=(
                    f"фаза {phase.at()} — {len(ops)} операций при авторском "
                    f"бюджете {MAX_OPS_PER_PROGRAM}. Под этим замыслом бюджет "
                    f"меряет ФАЗУ, а не скрипт: фаза и есть та программа, "
                    f"которую исполнит одна транзакция, и её размер — это "
                    f"размер того, что откатится целиком при первой же "
                    f"неудаче. СОБРАНО В ФАЗЕ: {_census(ops)}. СЛЕДУЮЩИЙ ХОД: "
                    f"режь эту фазу на две по этим числам — фаз в скрипте "
                    f"столько, сколько нужно"))
        # A SOLO OP IS A RULE OF THE PHASE, NOT OF THE SCRIPT, AND THAT IS
        # EXACTLY WHAT MAKES A MULTI-STORY BUILDING EXPRESSIBLE AS ONE
        # SCRIPT. Before phases, a solo op meant a SEPARATE PROGRAM, that
        # is, a separate model turn: a building with a staircase could
        # not be written as one script at all (measured 04.08 — a
        # staircase must be the only op, so a multi-story building is
        # unfit for a single program BY CONSTRUCTION). Now it is its own
        # phase inside the same script, and the plan builds the whole
        # building.
        #
        # THE FACT ITSELF ("which ops are solo and why") IS NOT REPEATED
        # HERE: it lives in `spec.SOLO_OPS`, and spec.py:56-65 warns
        # outright that before 04.08 it was written in three places and
        # had drifted apart in two of them.
        solo = [op for op in ops if op.get("op") in _spec.SOLO_OPS]
        if solo and len(ops) > 1:
            raise _refuse_phase(
                PLAN_SOLO_OP, field_name="ops", op_id=str(solo[0].get("id")),
                got=len(ops),
                message=(
                    f"фаза {phase.at()}: `{solo[0].get('op')}` обязан быть "
                    f"ЕДИНСТВЕННЫМ опом своей программы, а фаза — это и есть "
                    f"одна программа, и в ней {len(ops)} операций "
                    f"({_census(ops)}). СЛЕДУЮЩИЙ ХОД: заведи ему СВОЮ фазу — "
                    f"соседние опы уедут в фазу до или после, и здание "
                    f"останется одним скриптом"))
        # References are tagged BEFORE this phase's ops land in `owner`:
        # a neighbor in the same phase must stay `by=ref`.
        for op in program.ops[self._start:]:
            for key in [k for k in op if k not in ("op", "id")]:
                op[key] = _mark_cross_phase(op[key], ledger.owner)
        phase.op_ids = [str(op.get("id")) for op in ops]
        for oid in phase.op_ids:
            ledger.owner[oid] = phase.index
        ledger.phases.append(phase)
        ledger.watermark = len(program.ops)
        _refuse_use_before_produce(program, ledger, phase, self._start)
        return False


def _refuse_use_before_produce(program: Any, ledger: _PhaseLedger,
                               phase: Phase, start: int) -> None:
    """THE LAW OF ORDER, RAISED TO THE LEVEL OF PHASES (the same KIR-L003
    that applies inside a program).

    Inside a program a reference must point to an EARLIER op. Between
    phases it is the same rule for the same reason, only stricter: phase
    N is executed by a separate transaction, and an id from phase N+1's
    witness cannot be substituted into it — it does not exist yet. The
    check sits at the CLOSE of the producing phase, because before that
    point the fact is unknowable: until an op is written, a reference to
    it is indistinguishable from a dangling one.

    A handle (`Handle`) cannot miss this way — a handle exists only after
    its own op. The miss happens through the EXPLICIT form: `by_ref
    ("level1")` or a ready-made dict `{"by": "ref", "value": "level1"}`,
    where the id is guessed from the deterministic naming scheme
    (`Program._next_id`). The form is legal, and today it is the only way
    to refer backward by the text of the script.
    """
    produced = set(phase.op_ids)
    for op in program.ops[:start]:
        wrong = [target for target in _ref_targets(op) if target in produced]
        if not wrong:
            continue
        user = ledger.phases[ledger.owner[str(op.get("id"))]]
        raise _refuse_phase(
            "KIR-L003", field_name="by=ref", op_id=str(op.get("id")),
            got=wrong[0], candidates=sorted(produced),
            message=(
                f"оп `{op.get('id')}` из фазы {user.at()} ссылается на "
                f"`{wrong[0]}`, а тот производится ПОЗЖЕ — в фазе "
                f"{phase.at()}. Фазы исполняются по порядку, каждая своей "
                f"транзакцией: к моменту фазы {user.index} элемента "
                f"`{wrong[0]}` в модели ещё нет, и подставить его настоящий id "
                f"неоткуда — свидетеля фазы {phase.index} ещё не существует. "
                f"СЛЕДУЮЩИЙ ХОД: поменяй фазы местами — производитель обязан "
                f"стоять в плане РАНЬШЕ потребителя"))


def _refuse_tail(program: Any, ledger: _PhaseLedger) -> None:
    """Ops written AFTER the last phase. The one check outside the block.

    It alone got no `with`: a tail only becomes a tail once the script
    has ended — so this refusal has no line number. Instead it names the
    ops themselves and the last phase: that is enough to find the spot by
    eye, while guessing the line from the op count would point to the
    WRONG one.
    """
    stray = len(program.ops) - ledger.watermark
    if not stray:
        return
    loose = list(program.ops[ledger.watermark:])
    raise _refuse_phase(
        PLAN_PHASE_SHAPE, field_name="ops", got=stray,
        candidates=[str(op.get("id")) for op in loose][:12],
        message=(
            f"{stray} операций написано ПОСЛЕ последней фазы "
            f"{ledger.phases[-1].at()}: {_census(loose)} (id: "
            f"{', '.join(str(op.get('id')) for op in loose[:6])}). Скрипт, "
            f"нарисовавший хоть одну границу, обязан разнести по фазам ВСЁ — "
            f"иначе этим опам пришлось бы выдумать фазу, которой автор не "
            f"писал. СЛЕДУЮЩИЙ ХОД: оберни хвост в свою фазу"))


def phase(name: str) -> _PhaseContext:
    """One link of the PLAN: what is written inside it is built as ONE
    transaction.

        with phase("уровни и каркас"):
            lvl = create_level(elev_mm=0, name="Этаж 1")
            create_wall(p0_mm=(0, 0), p1_mm=(6000, 0), level=lvl,
                        height_mm=3000)

        with phase("лестница"):
            create_stairs(base_level="Этаж 1", top_level="Этаж 2", ...)

    A PLAN is a sequence of phases, not one big program. The transaction
    is per PHASE, not per plan: every phase is atomic, there is a
    checkpoint between phases, and there is no moment at which the
    building is half-built. If a phase fails, the plan stops, the PHASES
    ALREADY BUILT REMAIN, and the next turn continues from the first one
    not yet passed.

    WHAT THIS CHANGES FOR THE AUTHOR:
      * the author's budget (of operations) measures the PHASE, not the
        script — a building has stopped running into the ceiling of a
        single program;
      * a solo op (`create_stairs`) is the only one in ITS OWN PHASE, not
        in the script: a multi-story building has become expressible as
        one script;
      * a reference to an element from a PAST phase is legal and tags
        itself automatically (the executor substitutes it from that
        phase's witness); a reference to an element from a FUTURE phase
        is a typed refusal;
      * ALL operations in the script must lie inside some phase: draw one
        boundary and you must mark out all of it. A boundary the author
        never drew is not invented for them.

    A script that never calls `phase()` does not change by a SINGLE
    BYTE: the program and its digest are the same as they were
    (`test_phases`: "absence remains absence").
    """
    return _PhaseContext(name)


def take_ops() -> dict | None:
    """THE SANDBOX'S DOOR. Take the program — together with its phases,
    if it has any.

    The sandbox polls the language under the name `take_ops` first
    (`_DRAIN_CANDIDATES`), and the carrier of that name in the shim
    (`language.py`) is THIS function, not `dsl.take_ops`. There is
    exactly one reason, and it is about placement, not convenience:
    `dsl.py` does not know the word "phase" and must not know it — a
    phase lives in the course, next to `unit()`. The drain remains, word
    for word, the language's own drain: `dsl.take_ops()` assembles and
    zeroes out the program, and here only the table gets attached to it.

    THE `phases` TABLE TRAVELS IN THE ENVELOPE, NOT IN THE OPS. The ops
    stay byte-for-byte the same — and that is a requirement, not a
    preference: their digest signs the program, and a phase number
    written into every op would have shifted the signature of a building
    that had not changed. The table says the same thing exactly once:

        [{"index": 0, "name": "каркас", "op_ids": ["level1", "wall1"]}, …]

    No phases — no key: absence remains absence.
    """
    from kir import dsl
    program = dsl.current()
    ledger = _LEDGERS.get(program)
    table = None
    if ledger is not None and ledger.phases:
        _refuse_tail(program, ledger)
        table = [p.as_dict() for p in ledger.phases]
    # THE UNIT TABLE — EXACTLY THE SAME WAY AND FOR EXACTLY THE SAME
    # REASON as the phase table: the ops stay byte-for-byte the same, and
    # membership travels once, alongside. No units — no key: absence
    # remains absence.
    units = _UNIT_LEDGERS.get(program)
    unit_table = ([u.as_dict() for u in units.units]
                  if units is not None and units.units else None)
    out = dsl.take_ops()
    if out is not None and table is not None:
        out["phases"] = table
    if out is not None and unit_table is not None:
        out["units"] = unit_table
    return out


# ───────────────────────────────────────────────── ADOPTION METRIC

#: THE BASELINE — what a REAL building looks like. Not a target and not
#: a threshold: the numeric target is already closed by one operation
#: (`skill.GOOD_VS_BAD`). This answers the question "does what was built
#: look like a house" — and a building with 12,000 solitary columns and
#: zero groups looks like none of the seven parsed ones.
BASELINE: dict[str, tuple[float, str]] = {
    "элементов на тип": (
        round(corpus.value("k2.elements") / corpus.value("k2.types"), 1),
        "K2: 115 880 элементов на 638 типов; демо-дом 550, ЭОМ Сколково 411"),
    "копий на определение группы": (
        round(corpus.value("k2.group_places") / corpus.value("k2.group_defs"), 1),
        "K2: 2 846 постановок на 367 определений; ВК Snowdon 110 на 14 — два "
        "независимых здания сошлись на 7.8"),
    "элементов внутри групп, %": (
        corpus.value("k2.grouped_share"),
        "K2, НИЖНЯЯ граница: члены из неснятых категорий в знаменатель не "
        "попали"),
}


def _element_count(op: dict) -> int:
    """How many elements an operation DECLARES.

    Derivatives (mullions, panels, fittings, flights of stairs) are NOT
    counted: how many of them Revit will spawn cannot be seen from the
    program, and a guess here would be exactly the silent number
    acceptance was built to forbid. The list of "ops with no elements" is
    taken from acceptance, not set up a second time.
    """
    name = op.get("op")
    ospec = _spec.OPS.get(name)
    if ospec is None or not ospec.writes_model:
        return 0
    if name in _OPS_WITHOUT_ELEMENTS or name == "delete":
        return 0
    if name == "create_group":
        members = op.get("members") or []
        return len(members) * (1 + len(op.get("placements") or []))
    return 1


def measure(ops: list[dict] | None = None) -> dict:
    """The program's three numbers. A pure function — called by both the
    tests and the rig."""
    if ops is None:
        from kir import dsl
        ops = [dict(op) for op in dsl.current().ops]
    written = len(ops)
    elements = sum(_element_count(op) for op in ops)
    groups = [op for op in ops if op.get("op") == "create_group"]
    in_groups = sum(_element_count(op) for op in groups)
    places = sum(1 + len(op.get("placements") or []) for op in groups)
    return {
        "операций написано": written,
        "элементов объявлено": elements,
        "элементов на операцию": round(elements / written, 2) if written else 0.0,
        "определений групп": len(groups),
        "постановок групп": places,
        "копий на определение": (round(places / len(groups), 2)
                                 if groups else 0.0),
        "элементов внутри групп, %": (round(100.0 * in_groups / elements, 1)
                                      if elements else 0.0),
    }


def _current_program() -> dict:
    """The program accumulated in the language up to this line. Does NOT
    take it.

    It specifically does NOT take it, and that is the one decision in
    this function. `take_ops()` is THE SANDBOX'S DOOR
    (`sandbox._DRAIN_CANDIDATES`): called from here, it would leave the
    script without a program and the turn without a result, and there
    would be nothing to notice it by, because both the plan and the
    verdict would still print correctly in that case. `build()` hands
    back a COPY, together with the envelope.
    """
    from kir import dsl
    return dsl.current().build()


def _as_authored(value: Any) -> Any:
    """A phase tag — back to `by=ref`, AND ONLY FOR SELF-CHECKING.

    The plan and the verdict judge INTENT, not transactions: both doors
    already glue a BATCH of programs into one building, because the
    building is what that batch is, not a single link (`preview` — "the
    batch is glued into ONE sheet"; `design_check` — "the unit to judge
    is the one the building actually is"). A `phase_result` tag addresses
    an op of THAT SAME script, and for both the drawing and the graph it
    is exactly the same thing as `by=ref`.

    THE MEASUREMENT of 09.08 this function exists for: on a two-phase
    script (a level + four walls + a room), the plan printed «рассмотрено
    6, нарисовано 0» with the reason «селектор уровня не сведён к плану»
    for EVERY wall. That is, phase tagging was blinding self-checking on
    exactly the buildings phases were built for — an instrument covering
    only part of the range.

    THIS IS NOT WHAT TRAVELS OUTWARD. In the program the tag stays a tag
    and must be substituted from the producing phase's witness; the
    reverse conversion lives here, and only for these two printing
    functions.
    """
    if isinstance(value, Mapping):
        if value.get("by") == CROSS_PHASE_BY:
            return {"by": "ref", "value": value.get("value")}
        return {key: _as_authored(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_as_authored(item) for item in value]
    return value


def _program_for(ops: list[dict] | None) -> dict | None:
    """What to look at: what was passed in, or what accumulated. `None`
    means there is nothing to look at."""
    program = {"ops": [dict(op) for op in ops]} if ops is not None \
        else _current_program()
    return _as_authored(program) if program.get("ops") else None


def _ids(examples) -> str:
    return ", ".join(str(x) for x in examples[:4]) if examples else "—"


def preview(ops: list[dict] | None = None, *, level: str | None = None) -> None:
    """THE PLAN of the program you are writing — AS TEXT, in this same
    turn.

    BEFORE 03.08 THE PLAN NEVER REACHED THE MODEL AT ALL. It was built
    (`plan_stream.py`) and went out over a websocket to a human's panel:
    "the stream LEAVES FROM HERE AND DOES NOT COME BACK" (`serving.py`).
    Nothing made it into the receipt, and the model wrote the next
    version of the building blind.

    THE PARAMETER ORDER WAS FIXED ON 04.08, AND IT WAS A DEFECT, NOT A
    MATTER OF TASTE. The signature used to be `preview(level=None, *,
    ops=None)` — while its twin, `design_check(ops=None)`, takes the
    PROGRAM first. Measured: `preview(ops_list)` handed the list to
    `level`, `ops` stayed `None`, and the function printed «программа
    пуста — ни одной операции. Рисовать нечего» while three operations
    sat right there. There was no refusal. The model read "empty" and
    went off to add what it had already written. Two functions the model
    calls back to back with the same hand must be called the same way;
    the level filter remains, but by the parameter's NAME:
    `preview(level="Этаж 1")`.

    IT ACCEPTS A BATCH TOO, like `design_check`. The difference between
    them is that the judge judges links SEPARATELY and by law
    (`create_stairs` has no right to stand next to walls), while the
    drafter GLUES them together: one sheet. That is already the law of
    the stream — `plan_stream._slice_for` glues the batch together for
    exactly this. Refusing here would mean blinding the model on the very
    unit the building actually is.

    The strength of the statement is SELF-CHECKING: what gets drawn is
    what is DECLARED. No selector is resolved against the real document,
    so wall thicknesses, opening widths, and room boundaries are UNKNOWN
    here — and every such gap of knowledge sits in the census as a third
    column, rather than being replaced with a plausible-looking number.
    """
    _note_read("preview", level)
    head: list[str] = []
    if ops is not None and not isinstance(ops, (list, tuple)):
        # THE INPUT SHAPE IS NAMED, NOT GUESSED AT. Accepting a string as
        # a level name would be a guess in favor of yesterday's
        # signature; the fix is one word, and it sits right in the
        # refusal.
        _emit(f"ПЛАН ОТКАЗ: первым аргументом идёт ПРОГРАММА — список операций "
              f"(как у design_check), а пришло {type(ops).__name__}. Фильтр по "
              f"этажу задаётся именем параметра: preview(level=…).")
        return
    if _is_bundle(ops):
        merged: list[dict] = []
        for program in ops:
            merged.extend(dict(op) for op in program.get("ops") or ())
        head.append(f"ПАЧКА из {len(ops)} программ склеена в ОДИН лист "
                    f"(так же, как её склеивает живой поток): вердикт судит "
                    f"звенья порознь, план — вместе")
        shared = _shared_ids(ops)
        if shared:
            # NAMED, not silently allowed: `id` is unique WITHIN a
            # program, and a collision BETWEEN programs is LEGAL. The
            # verdict keeps them apart as `p1/wall1`/`p2/wall1`; the plan
            # does NOT, and on the sheet they will merge into one.
            head.append(f"  ВНИМАНИЕ: {len(shared)} идентификаторов заняты "
                        f"более чем одной программой ({_ids(shared)}) — на "
                        f"ЛИСТЕ они сольются (вердикт их различает, план нет)")
        ops = merged
    try:
        program = _program_for(ops)
    except Exception as exc:  # noqa: BLE001 — the shape of the input, not of the program
        _emit(f"ПЛАН ОТКАЗ: программа не читается как список операций "
              f"({type(exc).__name__}: {exc}).")
        return
    if program is None:
        _emit("ПЛАН: программа пуста — ни одной операции. Рисовать нечего.")
        return
    from kir.preview import BLIND_SPOTS, build_program_preview, census_lines

    building = build_program_preview(program)
    census = building.census
    rows = [f"ПЛАН ПРОГРАММЫ — САМОПРОВЕРКА: нарисовано ЗАЯВЛЕННОЕ, "
            f"ни один селектор не разрешён по документу", *head,
            f"листов {len(building.plans)} из {building.levels_total} уровней; "
            f"операций рассмотрено {census.considered}, нарисовано "
            f"{census.drawn} ({census.coverage_pct:.0f}%)"]
    if census.considered and not census.drawn:
        # MEASURED 04.08: on the program's envelope and node L1 the plan
        # printed «рассмотрено 1, нарисовано 0 (0%)» and NOT A WORD about
        # the reason — while the reason sat right in its hands. A zero
        # with no reason is indistinguishable from «здесь нечего
        # рисовать», and those are different fixes: one is fixed by
        # drawing, the other by a call.
        rows.append(f"НЕ НАРИСОВАНО НИЧЕГО: ни одна из {census.considered} "
                    f"операций не попала на лист. Причины:")
        for line in census_lines(census):
            if line["kind"] != "omitted":
                continue
            rows.append(f"      {line['count']}: {line['ru']}"
                        + (f" ({line['category']})" if line["category"] else "")
                        + (f" — {_ids(line['examples'])}"
                           if line["examples"] else ""))
        rows.append("      Проверь ФОРМУ входа: план рисует ОПЕРАЦИИ KIR "
                    "(`{\"op\": …}`) или ПАЧКУ программ (`[{\"ops\": […]}, …]`).")
        _emit("\n".join(rows + ["план НЕ показывает: " + "; ".join(BLIND_SPOTS)]))
        return
    plans = building.plans
    if level is not None:
        plans = tuple(p for p in plans if p.level_name == level)
        if not plans:
            _emit("ПЛАН: уровня «%s» в программе нет. Есть: %s" % (
                level, ", ".join(f"«{p.level_name}»" for p in building.plans)))
            return
    for plan in plans:
        frame = plan.extents_mm()
        size = (f"поле {(frame[2] - frame[0]) / 1000:.1f} x "
                f"{(frame[3] - frame[1]) / 1000:.1f} м" if frame else "поля нет")
        rows.append(f"  «{plan.level_name}» отм. {plan.level_elevation_mm} мм, "
                    f"{size} — нарисовано {plan.census.drawn} из "
                    f"{plan.census.considered}")
        for group in plan.census.omitted:
            rows.append(f"      не нарисовано {group.count}: "
                        f"{group.reason.value} ({group.category}) — "
                        f"{_ids(group.examples)}")
        for group in plan.census.approx:
            rows.append(f"      приближено {group.count}: {group.reason.value}")
        for group in plan.census.anomalies:
            # WHAT THE SCREEN IS FOR. Not a verdict and not acceptance:
            # "look here".
            rows.append(f"      ПОСМОТРИ СЮДА {group.count}: "
                        f"{group.reason.value} — {_ids(group.examples)}")
    # THE BLIND-SPOT LIST PRINTS IN FULL, EVERY TIME. A silent preview
    # reads as "everything is fine", and a truncated blind-spot list
    # reads as "there are few blind spots".
    rows.append("план НЕ показывает: " + "; ".join(BLIND_SPOTS))
    _emit("\n".join(rows))


def _shared_ids(bundle) -> list[str]:
    """Identifiers claimed by more than one program in the batch."""
    seen: dict[str, int] = {}
    for program in bundle:
        for oid in {str(op.get("id", "")) for op in program.get("ops") or ()
                    if isinstance(op, Mapping) and op.get("id")}:
            seen[oid] = seen.get(oid, 0) + 1
    return sorted(oid for oid, count in seen.items() if count > 1)


def _is_bundle(value: Any) -> bool:
    """Whether this is a batch — by the element KEYS, not by length and
    not by hope.

    A batch is a non-empty list every element of which carries its own
    `ops`. A list of operations cannot look like that: an operation has
    `op`, and no `ops`. The rule is "every", not "the first": mixing a
    program with an operation is an author's error, and it must reach the
    verdict's door, which will name it (KIR-V001), rather than being
    guessed here in someone's favor.
    """
    return (isinstance(value, (list, tuple)) and bool(value)
            and all(isinstance(item, Mapping)
                    and isinstance(item.get("ops"), (list, tuple))
                    for item in value))


def design_check(ops: list[dict] | None = None) -> None:
    """THE VERDICT on the fitness of the intent — without Revit, in this
    same turn.

    It reads the NUMBERS the program already contains (wall endpoints,
    outlines, opening setbacks) and runs them through the rules of
    dwelling fitness: connectivity, a second exit, areas, heights, the
    presence of a window. It simulates nothing: everything Revit would
    add on its own is declared out of scope by name and is not modeled
    even approximately.

    IT ACCEPTS A BATCH TOO: `design_check([body, staircase])`, where each
    element is a program (`{"ops": [...]}`). This is not a convenience,
    it is the only way to get the TRUTH here about a multi-story
    building: by Revit's own law `create_stairs` must be the only op of
    its program (KIR-L002), so a building judged as one program is
    necessarily without a staircase. What must be judged is the unit the
    building actually is — the BATCH.

    ⛔ A PROMISE THAT STOOD HERE UNTIL 23.08.2026 HAS BEEN WITHDRAWN BY
    MEASUREMENT. The text used to say that without a staircase `HAB010`
    "will block every occupied floor above grade." It blocks NOT ONCE.
    A run on an apartment with two occupied floors: the rule stays
    UNEVALUATED, and the reason shifts as it is fed inputs — first
    «нет входа ground_level_known», then «нет входа
    stair_landings_complete: лестниц в представлении НЕТ НИ ОДНОЙ». With
    no staircase the rule has nothing to fire on: it STAYS SILENT, it
    does not block.

    The judge itself is honest here — it prints «ОБЯЗАТЕЛЬНЫЕ НЕ
    ОЦЕНЕНЫ: HAB001, HAB010». It was the text that lied, and it lied in
    the direction of "we are stricter than we are" — the worst direction
    to lie in: the reader relies on a protection that does not exist.
    Exactly the trap the "verdict" lesson warns about: a silent rule
    looks clean.

    WHAT A BATCH ACTUALLY GIVES, measured the same day on one subject:

        body alone      10 of 20 evaluated   OVERALL NOT EVALUATED
        stairs alone     0 of 20 evaluated   NOT FIT (HAB000: no rooms)
        BATCH           11 of 20 evaluated   FIT UNDER 11 OF 20 RULES

    The sum of the parts is 10, the batch is 11 — but what changes is not
    the number of rules, it is the KIND OF VERDICT: HAB001 and HAB010
    move from "mandatory not evaluated" to "waived by stage profile",
    while HAB012 gets an input. The staircase gives the judge something
    the body has under no data at all.

    THIS IS SELF-CHECKING. What is judged is what the program DECLARES,
    not what was built; a verdict on a program is not evidence about a
    building.
    """
    строка = _note_read("design_check")
    bundle = _is_bundle(ops)
    try:
        program = _as_authored(ops) if bundle else _program_for(ops)
    except Exception as exc:  # noqa: BLE001 — the shape of the INPUT, not of the program
        # The input's shape breaks the door BEFORE the judge: `_program_for`
        # does `dict(op)` over every member, and an op that is not a dict
        # used to produce a raw `ValueError: dictionary update sequence
        # element #0 has length 1; 2 is required` — text about a
        # "sequence" that names neither the operation nor the next turn.
        # The refusal's form is taken from its twin (`preview` closed
        # this same spot earlier).
        строка["refused"] = True
        _emit(f"ВЕРДИКТ ОТКАЗ: программа не читается как список операций "
              f"({type(exc).__name__}: {exc}).\n"
              f"   СЛЕДУЮЩИЙ ХОД: судья принимает ОПЕРАЦИИ KIR "
              f"(`[{{\"op\": …}}, …]`) либо ПАЧКУ программ "
              f"(`[{{\"ops\": […]}}, …]`).")
        return
    if program is None:
        _emit("ВЕРДИКТ: программа пуста — ни одной операции. Судить нечего.")
        return
    try:
        from kir import design_check as _verdict
    except ImportError as exc:                    # pragma: no cover — см. warm_for_source
        _emit(f"ВЕРДИКТ НЕДОСТУПЕН: модуль вердикта не прогрет в этом запуске "
              f"({exc}). Напиши имя `design_check` в скрипте прямо — по нему "
              f"песочница и решает, что грузить.")
        return
    try:
        verdict = (_verdict.check_bundle(program, building_id="пачка этого хода")
                   if bundle else
                   _verdict.check_ops(program, building_id="программа этого хода"))
    except _verdict.VerdictInputError as exc:
        # The base class, not `ProgramShapeError`: the verdict's door now
        # has two kinds of refusal (KIR-V001 shape, KIR-V002 batch
        # contract), and catching by the subclass would have let the
        # second one out as a raw trace instead of a named cause.
        _emit(exc.render())
        return
    except _verdict.DesignCheckUnavailable as exc:
        # A refusal, not a silent fallback to v1: the v1 path has neither
        # a three-way verdict nor coverage, and there would be nothing to
        # tell it apart from the real thing.
        _emit(f"ВЕРДИКТ НЕДОСТУПЕН: {exc}")
        return
    except Exception as exc:  # noqa: BLE001 — см. `_why_the_judge_stumbled`
        строка["refused"] = True
        _emit(_why_the_judge_stumbled(program, bundle, exc))
        return
    text = _verdict.render_verdict_brief(verdict)
    _emit(text + _hab000_names_the_real_cause(text, program, bundle)
          + _geometry_the_judge_did_not_see(program, bundle))


def _why_the_judge_stumbled(program, bundle: bool, exc: BaseException) -> str:
    """The judge stumbled — ASK THE TYPE CHECKER and hand back ITS typed
    refusal.

    🔴 MEASURED 04.09.2026, nine program shapes through this door: FIVE
    came out as a raw stack trace, and not one named the operation or the
    next turn.

        create_room(xy_mm=…)          KeyError: 'xy'
        create_room(point_mm=…)       KeyError: 'xy'      (the «план» lesson's program)
        create_room without xy        KeyError: 'xy'
        create_level without elev_mm  KeyError: 'elev_mm'
        an op that is not a dict      ValueError: dictionary update sequence…

    `KeyError: 'xy'` is the worst kind of refusal this tree can produce:
    it names the SLOT NAME that is missing from the program and reads as
    "you wrote xy wrong", when the author never wrote it at all. The
    correct name, meanwhile, LIVES IN THE REGISTRY, and the type checker
    prints it together with the op's whole contract and the next turn
    (`KIR-P003`, `KIR-T001`).

    WHY THIS IS AN EXPLAINER, AND NOT A GATE. The temptation was to put
    `plan_program` BEFORE the judge and block anything past it — and that
    is wrong: the judge and the plan have different laws (the judge
    judges `create_stairs` inside a batch, while `plan_program` rejects
    that very batch under `KIR-L002`), so a gate would have taken the
    verdict away from programs that legitimately get one today. Here the
    type checker is asked ONLY once the judge has already fallen — that
    is, exactly where there was no answer at all.

    IF THE TYPE CHECKER STAYS SILENT — THAT IS SAID OUTRIGHT. A program
    it accepts but the judge drops is a defect OF THE JUDGE, and blaming
    its author would be exactly that same "an instrument that is right
    about a different subject." In that case the exception's name is
    printed along with a direct request to show the program, not advice
    to fix it.
    """
    from kir.compiler import KirRefusal, plan_program

    звенья = list(program) if bundle else [program]
    диагностики: list = []
    for номер, звено in enumerate(звенья, 1):
        try:
            plan_program(звено)
        except KirRefusal as отказ:
            for d in отказ.diagnostics:
                диагностики.append((номер if bundle else None, d))
        except Exception:  # noqa: BLE001 — the type checker fell on its own; it stays silent the same way
            continue

    if not диагностики:
        return (f"ВЕРДИКТ ОТКАЗ: судья упал на этой программе "
                f"({type(exc).__name__}: {exc}), а типизатор её ПРИНИМАЕТ — "
                f"значит это дефект судьи, а не твоей программы.\n"
                f"   СЛЕДУЮЩИЙ ХОД: программу править не надо; покажи её "
                f"вместе с этой строкой — чинить здесь нечего.")

    строки = [f"ВЕРДИКТ НЕ ВЫНЕСЕН: программа не проходит типизацию, и судья "
              f"на ней спотыкается ({type(exc).__name__}: {exc}). "
              f"Отказов {len(диагностики)} — каждый называет свой следующий "
              f"ход:"]
    for звено, d in диагностики:
        адрес = ", ".join(part for part in (
            f"программа {звено}" if звено is not None else "",
            f"оп #{d.op_index}" if d.op_index is not None else "",
            f"id {d.op_id}" if d.op_id else "") if part)
        строки.append(f"\n  {d.code}" + (f" ({адрес})" if адрес else ""))
        строки.append(textwrap.indent(d.message_ru or "", "  "))
    return "\n".join(строки)


def _geometry_the_judge_did_not_see(program, bundle: bool) -> str:
    """NAME THE BODIES THE JUDGE CANNOT SEE, AND SAY WHAT THEY WOULD HAVE
    BECOME.

    🔴 THE NUMBER THIS BLOCK EXISTS FOR (measured 02.09.2026). A room made
    of four strips and a slab, written with the shape macro, arrives at
    the judge as `walls 0`: it reads OPERATION KINDS, and
    `create_solid_blend` is not a wall. The author meanwhile sees a
    verdict that looks clean — the wall rules STAY SILENT, and a rule's
    silence is indistinguishable from its assent. Exactly the trap
    already paid for in this same file with the prefix added to
    `HAB000`.

    Checkability only changes the decision when the environment speaks
    AT THE POINT OF NEED. Here it says: there are this many bodies, this
    is what they would have become, and if not — here is why. The
    parsing is taken from dry-run promotion (`promote.classify`), so the
    block's promise and `promote()`'s behavior are one branch of code,
    not two texts kept in sync by hand.

    The block stays silent when there is no geometry in the program: then
    it would only be noise.
    """
    try:
        from kir import promote as _promote
    except ImportError as exc:            # pragma: no cover — warm-up by name
        return (f"\n(о свободной геометрии сказать нечем: модуль продвижения "
                f"не прогрет в этом запуске — {exc})")
    programs = program if bundle else [program]
    записи: list[dict] = []
    for one in programs:
        try:
            записи.extend(_promote.unpromoted((one or {}).get("ops", [])))
        except Exception as exc:          # noqa: BLE001
            # SELF-CHECKING HAS NO RIGHT TO DROP THE TURN. The verdict has
            # already been computed and printed; our refusal travels as a
            # line next to it, not as a trace in its place. Tree form 44:
            # a plausible-looking zero is worse than a refusal.
            return (f"\n(тела свободной геометрии не прочитаны: "
                    f"{type(exc).__name__}: {exc})")
    if not записи:
        return ""
    родов = [z for z in записи if z["role"]]
    # The number comes FIRST, not inflected: "4 bodies" and "5 bodies" are
    # different forms, and a printer that confuses them reads as broken.
    строки = [f"\n\nСУДЬЯ НЕ ВИДИТ СВОБОДНОЙ ГЕОМЕТРИИ: тел {len(записи)}. Он "
              f"читает РОДА ОПЕРАЦИЙ, и правила про них НЕ ПРИМЕНЯЛИСЬ:"]
    for z in записи:
        имя = z["id"] or z["op"]
        if z["role"]:
            м = z["measured"] or {}
            хвост = ", ".join(
                f"{k} {v:g} {ед}" for k, v, ед in (
                    ("толщина", м.get("толщина_мм"), "мм"),
                    ("длина", м.get("длина_мм"), "мм"),
                    ("уклон", м.get("уклон_град"), "град"))
                if v is not None)
            строки.append(f"  {имя} -> стало бы {z['role']}"
                          + (f" ({хвост})" if хвост else ""))
        else:
            строки.append(f"  {имя} -> родом не стало: "
                          + (z["reason"] or z["unreadable"] or "причина не названа"))
    if родов:
        строки.append("Дать им род: `promote(форма)` — уровень среда возьмёт "
                      "тот, что объявлен в программе, ближайший снизу; и те "
                      "же правила заработают на этих телах.")
    return "\n".join(строки)


#: Ops that declare a room. A list, not a substring: `create_room_separator`
#: does NOT declare a room, and a match on "room" would have named the
#: cause wrong.
_ROOM_OPS = ("create_room",)


def _hab000_names_the_real_cause(text: str, program, bundle: bool) -> str:
    """Say IN THE VERDICT what today is written only in the lesson.

    🔴 MEASURED 23.08.2026, paired run Ш5. A real program of 714
    operations — 204 `create_room`, 192 `create_wall`, 96 windows, 96
    doors — got back from the judge:

        read: doors 0, levels 0, rooms 0, stairs 0, walls 0, windows 0
        BLOCKING 1: HAB000 — model has no rooms; nothing was verified and
        the building must NOT read as valid.

    The judge is right by its own contract: it takes level marks ONLY
    from `create_level` in this same program, while here every reference
    pointed at the levels of an already-open model, by name («ГЕЛИКОН
    01»). But the text said nothing about that, and the author read a
    verdict on their building where in fact stood the boundary of the
    INSTRUMENT.

    This is exactly the form already closed today for `KIR-P002` and
    `KIR-P006`: the knowledge exists, it sits in the field or in the
    lesson, but it is not in the text. The "verdict" lesson describes
    this exact boundary verbatim and names the remedy — "cured by one
    `create_level` operation in the same program." Across eight paired
    runs the course was never called once (consumption ledger: 0 of 8).
    So this must be said here, at the point of need, not somewhere no one
    visits.

    THE PREFIX IS ADDED ONLY WHEN BOTH CONDITIONS HOLD: the judge said
    HAB000 AND the program declares rooms. If the program declares no
    rooms at all, HAB000 is the plain truth, and the prefix would be
    noise.
    """
    if "HAB000" not in text:
        return ""
    programs = program if bundle else [program]
    rooms = levels = 0

    def _счесть(ops) -> None:
        """🔴 DESCENT INTO GROUP MEMBERS, ADDED 25.08.2026.

        The traversal counted operations only at the TOP level, and the
        prefix went dark for exactly the form this same module teaches:
        the unit of intent is a GROUP, and in a real building 82.6% of
        operations live inside them. Running one program in two forms:
        flat — 583 characters of explanation; grouped — EMPTY. The author
        read "model has no rooms" as a verdict on the building, when it
        was actually the boundary of SELF-CHECKING.

        Recursive, not one level deep: groups nest, and a traversal one
        step deep would have returned the same defect one floor down.
        This same shape has already been closed three times in this tree
        in these same 24 hours — `compiler._apply_defaults_with_trace`,
        `ground.compiler_choices`, `spec.group_member_yields_one`.
        """
        nonlocal rooms, levels
        for op in ops or []:
            if not isinstance(op, dict):
                continue
            name = op.get("op")
            if name in _ROOM_OPS:
                rooms += 1
            elif name == "create_level":
                levels += 1
            elif name == "create_group":
                _счесть(op.get("members"))

    for one in programs:
        _счесть((one or {}).get("ops", []))
    if not rooms or levels:
        return ""
    return (
        f"\n\n🔴 ПОЧЕМУ ПРОЧИТАНО НОЛЬ, ХОТЯ ПОМЕЩЕНИЯ ОБЪЯВЛЕНЫ. В программе "
        f"{rooms} операций `create_room` и НИ ОДНОЙ `create_level`. Отметки "
        f"судья берёт только из САМОЙ программы: ссылка на уровень открытой "
        f"модели — и по имени, и по id — у него не разрешается ничем, поэтому "
        f"вместе с уровнем выброшены все стоящие на нём элементы.\n"
        f"Это граница САМОПРОВЕРКИ, а не приговор зданию: стройке чужой "
        f"уровень по-прежнему годен.\n"
        f"СЛЕДУЮЩИЙ ХОД: объяви уровни этой же программой — "
        f"`create_level(name=…, elev_mm=…)` — и позови `design_check()` "
        f"снова; подробности и остальные границы судьи: `course(\"вердикт\")`.")


def score(ops: list[dict] | None = None) -> None:
    """Print the current program's numbers next to the corpus baseline."""
    _note_read("score")
    got = measure(ops)
    rows = [
        f"ПРОГРАММА: {got['операций написано']} операций -> "
        f"{got['элементов объявлено']} элементов "
        f"({got['элементов на операцию']} на операцию)",
        f"  групп: {got['определений групп']} определений, "
        f"{got['постановок групп']} постановок, "
        f"{got['копий на определение']} копий на определение; "
        f"{got['элементов внутри групп, %']}% элементов внутри групп",
        f"  базовая линия настоящих зданий: "
        f"{BASELINE['копий на определение группы'][0]} копий на определение, "
        f"{BASELINE['элементов внутри групп, %'][0]:.0f}% элементов в группах "
        f"(K2, нижняя граница)",
        "  производные элементы (импосты, панели, фитинги) НЕ посчитаны: "
        "сколько их родит Revit, из программы не видно",
    ]
    _emit("\n".join(rows))


# ─────────────────────────────────────────────────── what goes into the sandbox

#: EXACTLY WHAT the seam puts into the script's namespace. Not one
#: module: the sandbox deliberately does not inject them, and a
#: module name here would silently vanish.
SANDBOX_NAMES: dict[str, Any] = {
    "course": course,
    "recipe": recipe,
    "unit": unit,
    # THE PHASE BOUNDARY IS THE UNIT'S SIBLING, AND LIVES IN THE SAME
    # PLACE. It was deliberately absent from `POINTER`: the pointer is
    # paid for by every request and may only promise what is reachable
    # END TO END, and phase-by-phase execution did not exist yet (step
    # 2) — a program with phases reached the compiler and honestly
    # refused. STEP 2 WAS DONE 09.08н: `serving._run_plan` cuts the plan
    # into a batch (`compiler.split_phases`), runs the links one at a
    # time through the same body, and substitutes the ElementId from the
    # previous phase's witness. The path is reachable end to end, so the
    # name went into the pointer — and went in BY DISPLACEMENT, see there
    # for that.
    "phase": phase,
    "score": score,
    # FEEDBACK ABOUT THE BUILDING ITSELF, not about the language. Measured
    # 03.08 on the live loop: neither the plan nor the verdict ever once
    # reached the model — the plan went out over a websocket to a human,
    # the verdict had not a single importer anywhere in the tree. Both
    # are NARROW FUNCTIONS, not modules: the sandbox does not inject
    # modules (`_child_main`: `isinstance(value, types.ModuleType) ->
    # continue`), and a module name here would silently vanish, while
    # also opening the whole of someone else's namespace to the script.
    "preview": preview,
    "design_check": design_check,
    # THE LANGUAGE'S REFERENCE, not the course and not the building. It
    # sits here, not in `dsl.py`, for exactly the same reason the course
    # sits here: the location of a name is decided by the seam, not by
    # kinship — the sandbox puts the public names of ONE module into the
    # script, and this dictionary is that very seam. The name `spec`
    # does not collide with the registry module: the sandbox does not
    # inject modules at all, and here it is imported as `_spec`.
    "spec": spec,
    # THE SHAPE THE AUTHOR USED TO SPELL OUT VERTEX BY VERTEX. Measured
    # 19.08: a box — 8 vertices and 12 index triples by hand, with no way
    # to check yourself before the flight; `extrude` gives the same mesh
    # and CANNOT hand back a mesh the compiler would reject (it calls
    # `validate_mesh` internally).
    "extrude": extrude,
    # THE SECOND SHAPE CONSTRUCTOR, AND IT CLOSES A NAMED DEBT (19.08).
    # Before it, anything running ALONG A PATH — a handrail along a
    # flight of stairs, a cornice along a bent facade, a duct along a
    # route — the author could express only by a hand-built mesh:
    # `extrude` carries a profile strictly vertically. A joint is mitered
    # (the bisector), so segments meet with no gap; a sharp turn, where
    # the solid would overlap itself, is a NAMED refusal, not a silent
    # approximation.
    "sweep": sweep,
    # `extrude`'S PARTNER, AND THE PAIRING IS NOT AN ACCIDENT: a mesh
    # gives GEOMETRY WITH NO BIM MEANING, while `region` carries that
    # same computed shape into a REAL floor/ceiling/pad — with a type, a
    # thickness, and a row in the schedule. Without this second half, an
    # author who thought a floor plan was a boolean could only build
    # "geometry".
    "region": region,
    # FLAT OPERATIONS ON A CONTOUR — the third and fourth doors to the
    # same kind of value as `region`, and they had been PROMISED but
    # never delivered (audit finding F-293, 29.08.2026). `kir/curveops.py`
    # declares itself, in its very first lines, a set of constructors for
    # the AUTHOR's python and cites the prod sandbox as precedent — yet
    # no names had been put into the script's namespace, and there was no
    # workaround: `import kir` is forbidden to a script. The module's
    # host tests were green (20 passed) and COULD NOT have caught this:
    # they import `kir.curveops` directly, meaning they checked the
    # arithmetic, to which the author has no door. The same way `sdk.py`
    # lay excellent and unreachable.
    #
    # The order was not indifferent: before `F-290`/`F-291` these doors
    # would have handed the author a strip 70.71 wide instead of 100 at
    # every kink, and would have accepted a polyline in place of a
    # contour. Both fixes landed earlier (73ca962).
    "offset": offset,
    "thicken": thicken,
    # FREEFORM GEOMETRY — FIFTEEN NAMES, ONE DICTIONARY (01.09.2026). The
    # owner's word: "an LLM does a far better job in three.js than in
    # Revit; I want a tool that, like Rhino and three.js, can build
    # beautiful objects, only BIM-oriented." The size of the gap is
    # measured, not assumed: of the registry's 82 operations, 47 require
    # a catalog from a snapshot, 32 a level, 12 a host; the language's
    # help text costs 43,030 tokens against 519 for raw C#; in the live
    # corpus, 121 turns went into RECON instead of building.
    #
    # The dictionary sets up not one new operation and not one new kind
    # of value — it gathers existing ones (`create_solid_*`, `region`,
    # `mesh`, `plane`) into a shape the model already owns from training.
    # So the cost of the permanent text is negative: the pointer goes
    # 326 -> 319 characters, the tool description 29,951 -> 29,944
    # against a 29,970 ceiling; the substance moved into
    # `course("геометрия")`, that is, into the ON-DEMAND channel.
    #
    # The names are written in by UNPACKING, not one at a time: a second
    # list of the same fifteen names would drift from the first at the
    # very first edit — that is a naming defect of this tree. The sole
    # carrier is `rhino.RHINO_NAMES`.
    **RHINO_NAMES,
}


__all__ = [
    "BASELINE", "CROSS_PHASE_BY", "LESSON_CAP", "LESSON_RESERVE", "MAX_READS",
    "POINTER",
    "SANDBOX_NAMES", "SEAM", "Phase", "Unit", "corpus", "course",
    "design_check", "extrude", "lessons", "measure", "phase", "preview",
    "offset", "reads_ledger", "recipe", "region", "reset_reads", "sweep",
    "thicken",
    "recipes", "score", "spec", "take_ops", "unit",
]
