"""THE SECOND HALF OF THE SEAM: the KIR language plus the course, as one
module for the sandbox.

The sandbox places into the script's namespace the public names of EXACTLY
ONE module (`SandboxPolicy.dsl_module`) and also hands it out under the
alias `kir`. The DEFAULT of this field is THIS module, meaning the seam is
laid, not merely planned: `preview` and `design_check` sit in the
namespace of every authoring script in prod. The second of the two
approaches was chosen (`course.SEAM`) — it does not touch `dsl.py` at all.

WHAT IS HERE AND WHAT IS NOT.

* `from kir.dsl import *` — the whole registry surface, the SAME function
  objects. A script written for `dsl` works here without a single edit.
* `take_ops` is imported BY NAME, because it is deliberately absent from
  `dsl.__all__`: the sandbox looks for it on the module
  (`_DRAIN_CANDIDATES`), not in the script's namespace. Without this line
  the program would still build, but zero operations would come out — the
  quietest possible defect.
  THE CARRIER OF THE NAME IS THE COURSE, NOT `dsl`: `course.take_ops`
  calls `dsl.take_ops` verbatim and attaches a phase table to the envelope
  if the author drew them. `dsl.py` does not know the word "phase" and
  should not — a phase lives next to `unit()`, of which it is a structural
  twin. Choosing the carrier is, as before, not semantics: this file
  decides nothing, it only glues.
* The course's `SANDBOX_NAMES` — 10 functions (`phase` and `spec` arrived
  in two waves of the same day; `extrude` and `region` — in the
  expressiveness wave of 19.08, and these are the FIRST injected names
  that need not our module but an external library: the warm-up line for
  them also names the submodules). Not a single module: the sandbox does
  not inject those, and a module name here would silently vanish.
  The number here is not a literal for its own sake — `test_course` checks
  the dictionary's composition by name, so a discrepancy of this line
  against it will be noticed, not inherited.
* THE NAME `spec` DOES NOT SHADOW THE REGISTRY. `from kir.dsl import *`
  goes by `dsl.__all__`, where `spec` is absent (the registry there is a
  module import, not an export), while `globals().update(SANDBOX_NAMES)`
  places the course's FUNCTION here. The script sees the reference; it
  does not see the registry module at all — the sandbox does not inject
  modules.
* `warm_for_source` — the ONLY thing this file decides on its own, and it
  decides a question of cost, not of meaning (see below).
* It has NO semantics of its own, NOT ONE. This file decides nothing; it
  only glues two namespaces together, and there its duties end.

WHY THE WARM-UP IS CONDITIONAL, NOT UNCONDITIONAL. `preview` and
`design_check` call modules that pull in shapely, numpy, and networkx: the
03.08 MEASUREMENT on the prod box — +536 ms and +43 MB at startup. The
sandbox executes the script TWICE (`replay_check`), meaning an
unconditional warm-up would cost +1.1 s on EVERY turn, including those the
plan and the verdict do not call at all — against today's happy path of
121 ms. So the SOURCE decides: a name the model did not write, it cannot
call (`globals`, `eval`, `exec`, and `__import__` are closed to the
script), and the substring search here is not a heuristic but an exact
condition.

WHY THE TESTS ARE RUN THROUGH IT SPECIFICALLY. A seam nobody has walked
end to end is a promise. All the course's recipes execute through the real
sandbox with `dsl_module="kir.course.language"`, i.e. exactly the set of
names the model will get after the switch.
"""
from __future__ import annotations

from kir import dsl
from kir.dsl import *                        # noqa: F401,F403
from kir.course import SANDBOX_NAMES, take_ops  # noqa: F401

globals().update(SANDBOX_NAMES)

#: Course name -> modules without which it will not work IN THE SANDBOX.
#:
#: "Will not work" is literal here: the child sets up the import guard
#: (`sandbox._MetaGuard`) before executing the script, and any module not
#: yet in `sys.modules` at that point raises KIR-B004 «импорт запрещён» —
#: with the MODEL's line number and an instruction to fix its otherwise
#: sound script.
_WARM_BY_NAME: dict[str, tuple[str, ...]] = {
    # 🔴 THE FIFTH OCCURRENCE OF THE SAME DEFECT, AND THE MOST EXPENSIVE
    # (22.08.2026). `course("дом")` and `course("квартира")` failed with
    # KIR-B004 «импорт kir.course.building запрещён» — TWO lessons out of
    # sixteen, and precisely the ones that carry the MEASURED NUMBERS OF THE
    # BUILDING: floor height, room area, grid spacing, wall thickness. The
    # `building.py` module was written on 16.08 against the measurement
    # "the agent builds primitive buildings" — and from that day the author
    # could not read it EVEN ONCE. Built and not connected.
    #
    # WHY THE RATCHET WAS GREEN. It scans the BODY of the injected name, and
    # `course` contains no import of its own: the topic is pulled by
    # `lessons.LESSONS`, where the module is fetched with `__import__` one
    # floor down. Exactly the same blind spot recorded below about `sweep`
    # ("it contains not a single import — its helpers one floor down pull
    # them, and the body scan came back empty"). The pattern was caught
    # twice, and both times ONE of its carriers was fixed.
    #
    # HOW IT WAS FOUND. By the course consumption ledger set up the same
    # day: the shoulder of a paired run called `course("дом")`, and the
    # ledger recorded the line `chars: 0` — the call happened, no text was
    # returned. One number, `0`, was enough; without the ledger the failure
    # would have looked like the model's own script's fault.
    #
    # CHECKED ACROSS ALL TOPICS AT ONCE:
    # `test_every_lesson_renders_in_the_sandbox` runs `course(topic)` through
    # the REAL sandbox for each of the sixteen.
    "course": ("kir.course.building", "kir.skill"),
    "preview": ("kir.preview",),
    "design_check": ("kir.design_check",),
    # `spec()` prints a table of contents BY PROJECT SECTION (09.08), and
    # an op's section is DERIVED, not set by hand: op -> census category
    # (the acceptance judge, `kir.acceptance`) -> section (carried by the
    # `registry_base.DISCIPLINES` dictionary, the second of them — the
    # extraction table in `kir.decompile.extract`). Both modules are lazy
    # in `spec.py` on purpose: everything pulls them in, and their import
    # chain is heavy and would loop back onto the registry.
    # THE MEASUREMENT THAT FORCED THIS LINE: without the warm-up, `spec()`
    # in the sandbox failed with KIR-B004 «импорт kir.decompile запрещён» —
    # meaning a perfectly sound reference would have looked like the
    # model's own script's fault.
    "spec": ("kir.acceptance", "kir.decompile.extract"),
    # A UNIT OF INTENT WITH A PREDICATE (15.08). `unit(reads_as=…)` asks
    # `assembly_view` for the reading registry via a lazy import — and
    # WITHOUT this line it failed with KIR-B004 «импорт kir.assembly_view
    # запрещён» on a live run, with `blame: author`, meaning the predicate
    # blamed the author for an import the author did not write. The THIRD
    # occurrence of the same defect in this very table: the line above
    # records the same thing for `spec()`. The ratchet was set up so there
    # would be no fourth
    # (`tests/test_sandbox_warm_covers_lazy_imports.py`).
    "reads_as": ("kir.assembly_view",),
    # THE FOURTH OCCURRENCE OF THE SAME DEFECT WOULD BE HERE, IF NOT FOR
    # THIS LINE (19.08). `extrude` lazily imports `shapely` — and this is
    # the FIRST injected name that needs NOT our module but an external
    # library. Warming externals (`sandbox._warm_allowed_third_party`)
    # goes by THE ROOT NAME MENTIONED IN THE SOURCE, and the author writes
    # `extrude(...)` and does not write the word "shapely" at all — meaning
    # without this line a live call would have failed with KIR-B004
    # «импорт shapely запрещён» and BLAMED THE AUTHOR for our own import.
    # 🔴 "The ratchet was extended to this kind in the same pass" — THAT IS
    # WHAT STOOD HERE, AND IT WAS UNTRUE from 19.08 until that evening. The
    # guard knew exactly one axis — a lazy import of OUR module; the word
    # `shapely` never once appeared in it, and the external kind was held
    # up by a MANUAL workaround. Prose was wider than the code, our own
    # named class. Caught on `sweep`: it contains not a single `import`
    # (its helpers one floor down pull them in), the body scan came back
    # empty, no requirement arose — and the ratchet was GREEN with the line
    # missing. The cost was measured by editing the file: a live run
    # returns `KIR-B006 No module named 'shapely'` with blame=author. The
    # second axis was set up that same evening and is derived from the
    # MODULE where the function is defined:
    # `test_every_injected_name_warms_its_third_party_too`.
    # THE SUBMODULE IS NAMED SEPARATELY: `import shapely` does NOT pull in
    # `shapely.validation` (measured: 35 submodules in sys.modules, it is
    # not among them), and the constructor's FAILURE path calls
    # `explain_validity`.
    # THE SUBMODULES ARE NAMED BY NAME, ALL THREE. `shapely.geometry.polygon`
    # (where `orient` lives) worked BY COINCIDENCE — it is pulled in by
    # `shapely.geometry` — and it was found not by a failure but by an
    # exhaustive sweep of the lazy imports of every carrier of injected
    # names. House rule: having caught a pattern, look for its second
    # carrier in the same pass.
    "extrude": ("shapely", "shapely.geometry", "shapely.geometry.polygon",
                "shapely.validation"),
    # THE SAME LIST, AND THIS IS NOT COPY-PASTE, IT IS A FACT: `sweep`
    # parses the profile with the same `_polygon_from_contour` and
    # triangulates with the same `_triangulate`, so it pulls in EXACTLY the
    # same four submodules, including the failure path
    # (`shapely.validation` for the sake of `explain_validity`). The list
    # cannot be shorter here: the fifth carrier of a lazy import, found by
    # the 19.08 sweep, showed that "works by coincidence" and "is named"
    # are different states.
    "sweep": ("shapely", "shapely.geometry", "shapely.geometry.polygon",
              "shapely.validation"),
    # `region` accepts a shapely Polygon, but is NOT required to receive
    # one: it parses a list of points without the library at all. The
    # warm-up here is for the first form, and it is CHEAP precisely because
    # it is conditional.
    "region": ("shapely", "shapely.geometry"),
}


def _course_topics(source: str) -> tuple[frozenset[str], str, bool]:
    """Course topics, the REASON FOR NOT KNOWING, and whether a call to
    `course` was parsed at all.

    🔴 A DICTIONARY OF CALL FORMS USED TO STAND HERE, AND IT DID NOT WORK
    (F-359, 29.08.2026). Four exact substrings (`course("дом")` and three
    variants of it) decided whether to strip the text of expensive lessons
    BEFORE isolation. Measured against eight LEGITIMATE records of the same
    call: only THREE got the warm-up. Missed were a space before the
    parenthesis, the topic via a variable, a call split across two lines, a
    keyword argument, a function alias. The author got «УРОК «ДОМ»
    НЕДОСТУПЕН: корпуса разборов нет на этой машине» while the corpus was
    INSTALLED — the failure blamed the machine for our own grammar.

    A fifth line in the list would not have helped: the next one would
    have been a sixth. The owner's word on 28.08: a dictionary is not a
    mechanism, you cannot enumerate all the forms, and trying to enumerate
    them produces garbage in the code. So there is no list here, only ONE
    checkable property: the topic is known only if it is WRITTEN AS A
    LITERAL.

    Everything else — a computed argument, syntactically broken source —
    is NOT KNOWING, and it must BE HEARD, rather than silently turning into
    "no warm-up needed". A port to whoever knows more already exists: the
    receipt's `warmed` field, which the author reads.
    """
    import ast

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return frozenset(), "исходник не разобран", True
    topics: set[str] = set()
    blind = ""
    seen_call = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if (getattr(fn, "id", None) or getattr(fn, "attr", None)) != "course":
            continue
        seen_call = True
        args = list(node.args) + [kw.value for kw in node.keywords]
        if not args:
            continue          # `course()` — a table of contents, it does not need the corpus
        first = args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            topics.add(first.value)
        else:
            blind = "аргумент course() вычисляется, тема неизвестна до запуска"
    # 🔴 THE THIRD ELEMENT — A NAMED LIMIT OF PARSING, NOT SILENCE. The word
    # `course` is present in the source, but parsing found no call
    # `course(...)`: this happens with an ALIAS (`c = course; c("дом")`) and
    # with the word appearing in a comment. Resolving an alias would mean
    # building a data-flow analysis — a decision about the language, not a
    # defect fix. So there is NO warm-up here (it costs 10.1 s and would be
    # paid for by every comment), but there is no silence either: the
    # author will see the reason in `warmed` and will write the topic as a
    # literal.
    return frozenset(topics), blind, seen_call


def warm_for_source(source: str) -> tuple[str, ...]:
    """Load in advance what THIS PARTICULAR source will need. Return what
    was loaded.

    Called by the sandbox BEFORE isolation (`_child_main`, the "warm-up"
    step), while imports are still allowed and the root is not yet empty.
    The sandbox does not know the language grammar and should not — so the
    decision of "what to load" is made here, not there.

    DOES NOT RAISE, BUT DOES NOT STAY SILENT EITHER (edit of 29.08.2026,
    finding E-18). The argument for "do not raise" is correct and left as
    it was: an exception from here would bring down the ENTIRE turn,
    including a program that would already have assembled without any
    verdict at all. What was wrong was something else — that a failure
    landed NOWHERE: the returned list rides into the receipt as the
    `warmed` field, meaning the channel existed, there was just nothing to
    put into it. From there, "the library is not present in this
    environment" came out as "import forbidden" (E-17). Now a failed
    warm-up names itself with the `НЕ ЗАГРУЖЕН:` label.
    """
    import importlib

    loaded: list[str] = []
    # 🔴 TWO LESSONS ARE FETCHED AS TEXT, NOT JUST AS AN IMPORT. «дом» and
    # «квартира» read the DECOMPILE CORPUS by a relative path, and the
    # sandbox child sits in an empty root: after isolation there is no
    # corpus, and the lesson honestly fails. We fetch the text here, while
    # the filesystem is still our own.
    #
    # THE CONDITION IS A CALL TO EXACTLY THESE TOPICS, not the word
    # `course` in the source: the 22.08 cost measurement — `lesson()` reads
    # the corpus in 10.1 s, `lesson_flat()` in 1.9 s, and paying this on
    # every turn where the word occurred would mean trading ten seconds of
    # every author's time for two lessons they never asked for.
    #
    # The cheap SUBSTRING screen remains, and it is legitimate here: the
    # author is REQUIRED to write the name `course` to call the function.
    # It can fire an extra time (the cost is one AST parse) and cannot fail
    # to fire — unlike the retired dictionary of forms, where the substring
    # also checked the ARGUMENT (F-359).
    if "course" in source:
        asked, blind, seen_call = _course_topics(source)
        _building = None
        primable: set[str] = set()
        try:
            from kir.course import building as _building
            primable = set(_building.PRIMABLE_TOPICS)
        except Exception as exc:                  # we do not tear the turn, but we speak up
            loaded.append(f"НЕ ЗАГРУЖЕН:урок ({type(exc).__name__})")
        if not seen_call:
            loaded.append(
                "НЕ ПРОГРЕТ:слово course есть, вызов course(<тема>) не "
                "разобран — напиши тему литералом")
        if _building is not None and (blind or (asked & primable)):
            try:
                loaded.extend(f"урок:{t}" for t in _building.prime())
            except Exception as exc:              # we do not tear the turn, but we speak up
                loaded.append(f"НЕ ЗАГРУЖЕН:урок ({type(exc).__name__})")
            if blind:
                # 🔴 THE NOT-UNDERSTOOD SPEAKS UP. The author sees in the
                # receipt that they paid for a blind warm-up, and why. A
                # silent "warmed up just in case" would be the same silent
                # value, only more expensive.
                loaded.append(f"ПРОГРЕТ ВСЛЕПУЮ:{blind}")
    for name, modules in _WARM_BY_NAME.items():
        if name not in source:
            continue
        for module in modules:
            try:
                importlib.import_module(module)
            except Exception as exc:              # we do not tear the turn, but we speak up
                loaded.append(f"НЕ ЗАГРУЖЕН:{module} ({type(exc).__name__})")
                continue
            loaded.append(module)
    return tuple(loaded)


__all__ = sorted(set(dsl.__all__) | set(SANDBOX_NAMES))
