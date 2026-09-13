"""THE AGREEMENT REGISTRY: "THESE TWO EXPRESSIONS MUST MATCH", CHECKED BY A MACHINE.

WHY. In a single day, 21.08.2026, the defect "two carriers of one fact"
occurred NINE times, even though the canon has named it for years and all
nine were found and fixed. Knowledge did not help, and here is why: **the
defect is invisible from either side**. Grep finds text and does not know
whether it runs. An import finds structure and does not know whether it is
about that. "These two places must agree" finds NOTHING — there is no one
to ask such a question of.

    __RouteSkips declared by one of two collectors      the judge was silent for 49 commits
    MIN_EXTENT copied into the harvester                held 55 shapes
    classify_bridge vs. classify_execution               "your code ran" about the unstarted
    snapshot_file_exists vs. bare open                   5 readers of the course
    a refusal's text vs. its own number                  "<0.01 m²" at a 100 mm² threshold

The project had a CULTURE of one carrier and no MECHANISM. This file is the
mechanism.

🔴 THE POINT OF THE REGISTRY IS NOT THE CHECK BUT THE PROOF OF
NON-VACUOUSNESS. An agreement that cannot fail is a green light meaning
nothing, and this is a form of defect we have on record ("a control on a
degenerate input is green by construction", 12.08). That is why every
agreement has a third part, `break_it`: it breaks the GATHERED MATERIAL
(not the tree!), and the judge MUST fail on it. The non-vacuousness check
runs in the same pass as the check itself — not in tests that can go
unrun.

THE SHAPE OF AN AGREEMENT — THREE PARTS, DELIBERATELY SEPARATED:

    gather()      gather material from the LIVE tree (where possible, by
                  EXECUTING the code, not reading its text)
    judge(m)      None — it matches; a string — exactly what diverged, in
                  Russian
    break_it(m)   return material on which judge MUST fail

The separation gives what a monolithic check cannot: the judge can be set
on forged material without touching the tree.

WHAT THIS FILE DOES NOT DO. It does not go looking for agreements itself.
Every agreement here was BOUGHT by an incident, and the `why` field states
exactly which one. An agreement with no incident is a guess about the
future, and we already have enough of those.
"""
from __future__ import annotations

import ast
import copy
import pathlib
import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping

import kir as _kir_pkg   # the package anchor: the package's location, not the module's depth

# ─────────────────────────────────────────────────────────────────────────────
# THE ENGINE
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Agreement:
    """A single claim: "these two expressions must match"."""

    name: str
    #: The incident that bought this agreement. Without one, agreements are not created.
    why: str
    #: What exactly is being reconciled — in one line, for a human.
    claim: str
    gather: Callable[[], Any]
    #: An empty list — it matches. Non-empty — what diverged, one line per
    #: discrepancy. 🔴 A LIST, SPECIFICALLY: the first version joined
    #: discrepancies with "; ", and the bridge's own prose contains that
    #: same separator («durable receipt was not written; outcome is
    #: unknown») — the instrument was cutting the evidence in the middle of
    #: a sentence.
    judge: Callable[[Any], list[str]]
    break_it: Callable[[Any], Any]


@dataclass(frozen=True)
class Verdict:
    name: str
    claim: str
    why: str
    #: The agreement holds on the live tree.
    holds: bool
    #: The judge failed on broken material, meaning the check is NOT vacuous.
    provable: bool
    detail: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.holds and self.provable


def check(agreement: Agreement) -> Verdict:
    """Ask one agreement: does it hold, and can it fail at all."""
    try:
        material = agreement.gather()
    except Exception as exc:      # noqa: BLE001
        return Verdict(agreement.name, agreement.claim, agreement.why,
                       holds=False, provable=False,
                       detail=(f"материал не собрался: "
                               f"{type(exc).__name__}: {exc}",))
    try:
        divergence = list(agreement.judge(material))
    except Exception as exc:      # noqa: BLE001
        return Verdict(agreement.name, agreement.claim, agreement.why,
                       holds=False, provable=False,
                       detail=(f"судья упал: {type(exc).__name__}: {exc}",))

    # NON-VACUOUSNESS. The judge must fail on deliberately broken material.
    try:
        broken = agreement.break_it(copy.deepcopy(material))
        provable = bool(agreement.judge(broken))
    except Exception as exc:      # noqa: BLE001
        provable = False
        divergence = divergence + [
            f"непустота не доказана: {type(exc).__name__}: {exc}"]

    return Verdict(agreement.name, agreement.claim, agreement.why,
                   holds=not divergence, provable=provable,
                   detail=tuple(divergence))


def check_all(only: str | None = None) -> list[Verdict]:
    """Ask the whole registry — and, before that, the path by which it was gathered.

    🔴 The traversal goes over `_registry_roster()`, not over `AGREEMENTS`
    (E-49, 30.08.2026). A traversal over the tuple answers "what is
    DECLARED", and so an agreement removed from the tuple turned red
    nowhere: the list simply got shorter, and the traversal was trivially
    green. The path guard comes first, so that the loss is named before
    the reader trusts the shortened list.
    """
    return [check(a) for a in _registry_roster()
            if only is None or only in a.name]


# ─────────────────────────────────────────────────────────────────────────────
# SHARED: WHERE THE TREE LIVES
# ─────────────────────────────────────────────────────────────────────────────

#: 🔴 IT USED TO BE `pathlib.Path(__file__).resolve().parents[2]`, AND THIS
#: BLINDED TWO AGREEMENTS OUT OF THREE. Counting steps upward gave `/opt`
#: after the split, so `_py_files("kir/decompile")` traversed the
#: nonexistent `/opt/kir/decompile` and returned EMPTY — the agreement
#: about reverse-path entry points reported "no findings" without reading
#: a single file. Exactly form 4: a zero taken from an unreachable corpus
#: is indistinguishable from an honest zero.
#:
#: The anchor is taken from where the PACKAGE ITSELF lives (`kir.__file__`)
#: — the layout changes, this does not (fixed in `f518b05`, also in
#: `install_paths`).
_BACKEND = pathlib.Path(_kir_pkg.__file__).resolve().parent.parent

#: Roots that do not exist in this tree BY CONSTRUCTION. The package is
#: published separately, and the product is never beside it: a zero for
#: `kukai` is a legitimate answer, not blindness. Named as a list so the
#: reader can tell one from the other, and so a new empty root does not
#: slip into the same silence unnoticed.
_FOREIGN_ROOTS = frozenset({"kukai"})


def py_files_blind_spots(*rel: str) -> tuple[str, ...]:
    """Roots that do NOT exist and that are not declared foreign either.

    An empty tuple — the traversal was fully reachable. A non-empty one —
    the agreement built on these roots is reporting on the UNREAD.
    """
    missing = []
    for r in rel:
        if r.split("/")[0] in _FOREIGN_ROOTS:
            continue
        if not (_BACKEND / r).exists():
            missing.append(r)
    return tuple(missing)


class BlindWalk(RuntimeError):
    """The traversal went over a root that does not exist — and this is NOT "no findings".

    Introduced together with wiring in `py_files_blind_spots` (E-4,
    30.08.2026). A dedicated type, not a bare `RuntimeError`: `check()`
    catches any exception from the gatherer and prints "material did not
    gather", and the reader needs to tell "the instrument crashed" apart
    from "the instrument had NOTHING TO READ" — the next move differs
    between them.
    """


def _py_files(*rel: str) -> list[pathlib.Path]:
    # 🔴 THE TRAVERSAL'S BLINDNESS IS ASKED ABOUT HERE, NOT ASSUMED (E-4,
    # 30.08.2026). `py_files_blind_spots` was written exactly for this
    # question and was CALLED FROM NO PLACE in the tree — its only
    # occurrence was its own definition. The same defect as E-7: the
    # instrument exists, and no one asks it, so it guards nothing.
    #
    # The cost of the silence is recorded one line above in this file and
    # was bought by an incident: after the split,
    # `_py_files("kir/decompile")` traversed the nonexistent
    # `/opt/kir/decompile` and returned EMPTY — the agreement reported "no
    # findings" without reading a single file. A zero taken from an
    # unreachable root is indistinguishable from an honest zero, and only
    # this question can tell them apart.
    #
    # A REFUSAL, NOT AN EMPTY LIST: an empty list goes to the judge, and it
    # says "it matches". `check()` will catch the exception and return
    # `holds=False, provable=False` with a named reason — that is, the
    # agreement will say "I DID NOT CHECK", not "all is well".
    #
    # The fix is INERT on today's tree, and this is measured: both roots
    # that `_py_files` is called with (`kir`, `kir/decompile`) exist, while
    # `kukai` is declared foreign and skipped by construction. Inertness is
    # a reason to put the guard in place NOW, rather than after it is
    # needed.
    blind = py_files_blind_spots(*rel)
    if blind:
        raise BlindWalk(
            "обходить было нечего: корней нет — " + ", ".join(blind)
            + f". Это факт О МАШИНЕ, а не о дереве: согласие, построенное на "
              f"этих корнях, отчиталось бы о НЕПРОЧИТАННОМ. СЛЕДУЮЩИЙ ХОД: "
              f"проверь раскладку либо объяви корень чужим в _FOREIGN_ROOTS")
    out: list[pathlib.Path] = []
    for r in rel:
        base = _BACKEND / r
        if base.is_file():
            out.append(base)
            continue
        for p in sorted(base.rglob("*.py")):
            if "__pycache__" in p.parts:
                continue
            out.append(p)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# AGREEMENT 1. A REFUSAL CARRIES ITS OWN THRESHOLD
# ─────────────────────────────────────────────────────────────────────────────
#
# Bought 21.08: the `MIN_RING_AREA_MM2` threshold was lowered from 10,000
# to 100 mm², the refusal text in `contour.py` was fixed in the same
# commit, and the SECOND carrier of the same phrase in
# `authoring_validation.py` kept saying "area < 0.01 m²" — that is, 10,000
# mm². The author was told a threshold inflated A HUNDREDFOLD, and every
# receipt was green all the while: the refusal did, after all, happen.
#
# The measure is general and not about the contour: EVERY QUANTITY NAMED IN
# A REFUSAL'S TEXT TOGETHER WITH A UNIT MUST MATCH THE THRESHOLD THAT
# REFUSAL IS ABOUT. Numbers without a unit (an edge number, "of 3..256
# points") are not touched: they do not claim to be a threshold.

#: Unit → how many base threshold units it contains.
_AREA_UNITS = {"мм²": 1.0, "мм2": 1.0, "кв.мм": 1.0,
               "м²": 1e6, "м2": 1e6, "кв.м": 1e6}
_LEN_UNITS = {"мм": 1.0, "м": 1000.0, "см": 10.0}

_NUM_UNIT_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(мм²|мм2|кв\.мм|м²|м2|кв\.м|мм|см|м)(?![а-яё])",
    re.IGNORECASE)


def _quantities(text: str, ladder: dict[str, float]) -> list[tuple[float, str]]:
    """Pairs of (value in base units, as written) extracted from the text."""
    out = []
    for num, unit in _NUM_UNIT_RE.findall(text):
        factor = ladder.get(unit.lower())
        if factor is None:
            continue
        out.append((float(num.replace(",", ".")) * factor, f"{num} {unit}"))
    return out


def _gather_refusals() -> list[dict]:
    """Run the LIVE refusal paths and collect what they told the author.

    🔴 RUN THEM, SPECIFICALLY. A grep over the source would answer "the
    line exists", but the question is "what will the author hear", and
    these are different questions: the text could sit in a branch that is
    never entered.
    """
    from kir import geom
    from kir.authoring_validation import validate

    out: list[dict] = []

    # (a) a degenerate contour via the `pts` kind — the authoring_validation route
    diags: list = []
    validate({"op": "create_floor", "id": "F1", "level": "Уровень 1",
              "outline": [[0, 0], [2, 0], [2, 2]],
              "floor_type": "Перекрытие"},
             "create_floor", 0, "F1", diags)
    for d in diags:
        msg = getattr(d, "message_ru", "") or ""
        if "вырожденный контур" in msg:
            out.append({"site": "authoring_validation:pts", "text": msg,
                        "threshold": geom.MIN_RING_AREA_MM2,
                        "ladder": "area"})

    # (b) the same refusal via the canonical contour route
    from kir import contour as _c
    diags2: list = []
    ring = _c._validate_shape({"loop": [[0, 0], [2, 0], [2, 2]]},
                              [], "F1", "profile", diags2)
    del ring
    for d in diags2:
        msg = getattr(d, "message_ru", "") or ""
        if "вырожденный контур" in msg:
            out.append({"site": "contour:_validate_shape", "text": msg,
                        "threshold": geom.MIN_RING_AREA_MM2,
                        "ladder": "area"})
    return out


def _judge_refusals(material: list[dict]) -> list[str]:
    if not material:
        return ["ни один маршрут отказа не сработал — материал пуст, "
                "проверять нечего (это отказ, а не согласие)"]
    bad: list[str] = []
    for row in material:
        ladder = _AREA_UNITS if row["ladder"] == "area" else _LEN_UNITS
        qs = _quantities(row["text"], ladder)
        if not qs:
            bad.append(f"{row['site']}: текст не называет порога ВОВСЕ "
                       f"— «{row['text']}»")
            continue
        for value, written in qs:
            if abs(value - row["threshold"]) > 1e-9 * max(1.0, row["threshold"]):
                bad.append(
                    f"{row['site']}: сказано «{written}» = {value:g}, "
                    f"а порог {row['threshold']:g} — расхождение "
                    f"в {value / row['threshold']:g} раз")
    return bad


def _break_refusals(material: list[dict]) -> list[dict]:
    if material:
        material[0]["text"] = "профиль: вырожденный контур (площадь < 0.01 м²)"
    else:
        material.append({"site": "подделка", "text": "площадь < 0.01 м²",
                         "threshold": 100.0, "ladder": "area"})
    return material


# ─────────────────────────────────────────────────────────────────────────────
# AGREEMENT 2. THE BODY DECLARES EVERY HELPER IT CALLS
# ─────────────────────────────────────────────────────────────────────────────
#
# Bought 20–21.08 at the cost of forty-nine commits. The routing wave
# introduced calls to `__RouteSkips` into the SHARED helpers
# `_ELEMENT_HELPERS_CS`, while placing the declaration in the preamble that
# only the full extractor emits. The second consumer of the same helpers —
# `build_reextract_cs` — stopped compiling that very minute, and the JUDGE
# OF THE BUILT died along with it: every live build got "the built was NOT
# RE-READ".
#
# The gate catches this by compiling on six versions — five minutes and a
# live service. Here the same thing is caught in a second and without a
# service, because the question "is the called helper declared" is decided
# by TEXT.
#
# 🔴🔴 AND THIS VERY GUARD MISSED A SECOND BITE OF THE SAME CLASS
# (25.08.2026). `a91ac7fe` moved the frozen `extract` helpers from `doc` to
# `__src` — and `build_reextract_cs`/`build_room_reextract_cs`, the second
# consumers of the same helpers, again stopped compiling. The JUDGE OF THE
# BUILT died again, again for a full day, again with a loud refusal in
# EVERY live receipt.
#
# The guard was not silent by oversight, but BY CONSTRUCTION: the call rule
# read `(__[A-Z]\w*)\s*\(` — that is, only a HELPER FUNCTION, and only with
# a CAPITAL letter. `__src` is a DOCUMENT VARIABLE, read via a dot
# (`__src.GetElement`) and written with a lowercase letter. The first case
# (`__RouteSkips(`) was a call with a capital letter, and the guard was
# written to its SHAPE, not its property. Our form 52 in pure form: a
# DEFECT was pinned, not a PROPERTY — and a green result from such a guard
# reads as "the class is closed".
#
# So now what is asked about is READING ANY `__*` NAME: both the call
# `__Имя(` and the dotted access `__имя.`. A declaration is counted as any
# of the forms by which C# introduces a name into scope — they are listed
# below.
#
# 🔴 THE KIND OF THE LIST: CLOSED, BUT NOT COMPLETE. The declaration forms
# are listed by hand, and a new one (say, tuple deconstruction) will
# produce a FALSE ALARM, not a miss. This is chosen deliberately, and in
# the opposite direction from agreement 3: there a false alarm costs more
# than a miss, because SOMEONE ELSE'S live code is being judged; here the
# material is our OWN generated C#, a false alarm is fixed by adding a
# form in a minute, while a miss has already cost the judge of the built
# TWICE.

_CS_DECL_RE = re.compile(
    r"^\s*(?:Func|Action)\s*<[^;]*?>\s*(__[A-Za-z][A-Za-z0-9]*)\s*=",
    re.MULTILINE)

#: The forms by which C# introduces a `__*` name into scope. Listed one per
#: line deliberately: the list is read by eye and extended one entry at a
#: time.
_CS_BINDING_RES = (
    # `Document __src = doc;` · `var __x = …` · `int __n = 0;` · `out ElementId __id`
    re.compile(r"\b(?:var|out|ref)\s+(__[A-Za-z][A-Za-z0-9]*)\b"),
    re.compile(r"\b[A-Za-z_][\w.<>,\[\]?]*\s+(__[A-Za-z][A-Za-z0-9]*)\s*(?:=[^=]|;)"),
    # `foreach (Element __e in …)`
    re.compile(r"foreach\s*\(\s*[\w.<>,\[\]?]+\s+(__[A-Za-z][A-Za-z0-9]*)\s+in\b"),
    # lambda parameters: `(__value) =>` and `(__a, __b) =>`
    re.compile(r"\(\s*(__[A-Za-z][A-Za-z0-9]*)\s*(?:,[^)]*)?\)\s*=>"),
    # a lambda WITHOUT parentheses: `__x => __x.Foo` — the form behind all
    # six of the first false alarms from the widened rule
    # (`.Select(__x => …)`, `.OrderBy(__item => …)`)
    re.compile(r"(?<![\w.])(__[A-Za-z][A-Za-z0-9]*)\s*=>"),
    re.compile(r"\(\s*[^)]*?,\s*(__[A-Za-z][A-Za-z0-9]*)\s*\)\s*=>"),
    # `catch (Exception __ex)` · method parameters
    re.compile(r"\(\s*[\w.<>,\[\]?]+\s+(__[A-Za-z][A-Za-z0-9]*)\s*[),]"),
)

#: READING a name via a dot — the form `__src` got through by.
_CS_READ_RE = re.compile(r"(__[A-Za-z][A-Za-z0-9]*)\s*\.")
_CS_CALL_RE = re.compile(r"(__[A-Z][A-Za-z0-9]*)\s*\(")


#: Markers for NOT-A-BODY in agreement 2's material. A key with such a
#: marker carries not C# but the NAME OF AN ABSENCE: the judge must fail on
#: it, rather than parse an empty string as a body that declared every
#: helper.
_CS_UNCOVERED = "!НЕПОКРЫТ:"
_CS_UNDELIVERED = "!НЕ ДОЕХАЛ:"

#: 🔴 THE AGREEMENT ASKS ABOUT ONE VERSION, THE GATE ABOUT SIX, AND THIS IS
#: STATED, NOT IMPLIED. The agreement's subject is "does the body declare
#: the helpers it calls", and it does not depend on the version; the
#: gate's subject is "does the body compile", and it does
#: (`build_tag_extract_cs` with no version takes the 2022+ branch). Reading
#: this agreement's green as "the bodies compile on all six" is the very
#: same swap of subject the whole registry was built against.
_CS_BODY_VERSION = "2024"


def _gather_cs_bodies() -> dict[str, str]:
    """Bodies that were gathered PLUS the names of those declared and NOT
    RETRIEVED.

    🔴 BOUGHT BY THE AUDIT OF 30.08.2026 (E-50): THE COLLECTOR WAS SILENTLY
    SWALLOWING FAILURES. `build_all` carries `except Exception: continue`
    and a second silent skip — `if revit_version is None: continue` for a
    versioned body. Both DROP the name from the result, while the judge
    parsed ONLY WHAT ARRIVED and never once checked against the declared
    ledger `READ_BODY_ARGS`. So a body that stopped compiling fell out of
    BOTH halves of the question at once, and the agreement matched —
    honestly, about what was left.

    The same root named at the end of the shift: a law matches on its OWN
    subject and is therefore blind to the neighboring one, and a zero looks
    measured.

    🔴 THE SAME ROAD WAS GUARDED BY TWO, AND ONLY ONE OF THEM IS HONEST.
    `gate_runner` calls EVERY collector by name and prints "FAIL read_body
    … build failed"; the agreement called `build_all` and trusted the
    result. One registry, two roads, one guarded — and the one silent was
    exactly the cheaper one to run.

    Measurement 30.08.2026, by execution:
        collectors found by traversal    20   (19 distinct objects: E-38,
                                                build_profile_extract_cs is
                                                the same object as sketch)
        READ_BODY_ARGS                   18
        READ_BODY_FRAGMENTS               2   source_binding_cs, tag_target_block_cs
        build_all(2021…2026)        18 of 18  on each of the six
        build_all() with no version 17 of 18  build_tag_extract_cs drops SILENTLY
    That is, on the agreement's path the debt today is ZERO, while the
    silent skip exists and is caught by the neighboring call. The guard is
    put in place at zero deliberately: setting it up on the day the number
    turns nonzero would mean learning about it from someone else.
    """
    from kir.decompile.read_bodies import (
        READ_BODY_ARGS, build_all, uncovered_read_bodies)

    bodies = build_all(revit_version=_CS_BODY_VERSION)
    for missing in uncovered_read_bodies():
        bodies[f"{_CS_UNCOVERED}{missing}"] = ""
    # THE LEDGER AGAINST WHAT ARRIVED. `READ_BODY_ARGS` is a declaration:
    # "these bodies compile meaningfully". The difference from what
    # arrived is exactly what `build_all` swallowed, and naming it is the
    # asker's job: the collector itself says plainly in its docstring that
    # it leaves that decision to the caller.
    for name in sorted(set(READ_BODY_ARGS) - set(bodies)):
        bodies[f"{_CS_UNDELIVERED}{name}"] = ""
    return bodies


def _judge_cs_bodies(bodies: dict[str, str]) -> list[str]:
    """Whether the body calls something it did not declare.

    🔴 WHAT THIS JUDGE CANNOT DO IS STATED AS A MEASUREMENT, NOT A PROMISE
    (F-104, 30.08.2026). It pools ALL declarations and ALL references OVER
    THE WHOLE BODY and DOES NOT MODEL SCOPE. So a name declared only
    inside lambda `__A` counts as a reference from the SIBLING lambda
    `__B`, where it is in fact undefined and C# would not compile.

    The gap is REAL, and I am not fixing it — I measured it and I explain
    why I am not fixing it. I built a crude scope model (matched curly
    braces: a name is visible only inside its own block and nested ones)
    and ran it over all 18 bodies, 372,575 characters of C#:

        bodies with references OUTSIDE their declaration's scope: 2
        total such references:                                   7
        build_geometry_extract_cs 6 · build_group_extract_cs 1

    I traced every one: all seven are CLOSURE CAPTURE. `var __errors =
    new List<object>();` is declared in the method body and is legitimately
    read from nested lambdas; that is how C# works. So the brace-based
    model gives SEVEN ALARMS and ZERO findings.

    This file's header says plainly: an agreement that shouts at correct
    code gets switched off within a week. So the judge stays FLAT, and its
    boundary is recorded here: it answers "is the name declared SOMEWHERE
    in the body", NOT "would this body compile". Reading it as the latter
    is the same swap of subject the whole registry was built against.

    What would truly close the gap: parsing C# with a real parser, not
    regular expressions. That is separate work and a separate decision for
    the owner.
    """
    if not bodies:
        return ["ни одно читающее тело не собралось — материал пуст"]
    bad: list[str] = []
    for name, body in sorted(bodies.items()):
        if name.startswith(_CS_UNCOVERED):
            bad.append(f"{name.split(':', 1)[1]}: сборщик найден обходом "
                       f"пакета и не назван в READ_BODY_ARGS")
            continue
        if name.startswith(_CS_UNDELIVERED):
            # A SEPARATE kind, with its own next move: "not named" is fixed
            # by an entry in the ledger, "did not arrive" by diagnosing the
            # collector's failure.
            bad.append(f"{name.split(':', 1)[1]}: объявлен в READ_BODY_ARGS и "
                       f"НЕ ДОЕХАЛ до материала — build_all проглотил падение "
                       f"или пропустил тело по версии; спроси сборщика "
                       f"поимённо, как это делает gate_runner")
            continue
        declared = set(_CS_DECL_RE.findall(body))
        for _rx in _CS_BINDING_RES:
            declared |= set(_rx.findall(body))
        # READ covers both a helper call (`__Имя(`) and member access
        # (`__имя.`). The second was added 25.08: `__src` got through by
        # exactly this form.
        used = set(_CS_CALL_RE.findall(body)) | set(_CS_READ_RE.findall(body))
        missing = sorted(used - declared)
        if missing:
            bad.append(f"{name}: зовёт и НЕ объявляет {', '.join(missing)}")
    return bad


def _break_cs_bodies(bodies: dict[str, str]) -> dict[str, str]:
    # 🔴 A REAL BODY IS BROKEN, NOT THE NAME OF AN ABSENCE. Keys with the
    # marker carry an empty string and fail ON THEIR OWN; picking one would
    # make non-vacuousness get proved by a DIFFERENT branch of the judge —
    # a control run honestly and still empty.
    real = sorted(n for n in bodies
                  if not n.startswith((_CS_UNCOVERED, _CS_UNDELIVERED)))
    if real:
        first = real[0]
        # 🔴 LATIN LETTERS, AND THIS IS NOT A TRIFLE. The first version
        # broke the material with the Cyrillic `__НетТакогоПомощника` — it
        # did not fall under the call rule (`__[A-Z]…`), the judge stayed
        # silent, and the agreement came out EMPTY. The instrument said so
        # itself, on the very first run: "non-vacuousness not proved".
        # Exactly the benefit the third part was set up for.
        bodies[first] = bodies[first] + "\n__NoSuchHelperAtAll(__x);\n"
    else:
        bodies["подделка"] = "__NoSuchHelperAtAll(__x);"
    return bodies


# ─────────────────────────────────────────────────────────────────────────────
# AGREEMENT 3. WHOEVER ASKS ABOUT COMPRESSION MUST ALSO READ THROUGH IT
# ─────────────────────────────────────────────────────────────────────────────
#
# Bought 19–21.08, twice. The parse corpus started being compressed, and
# two shelves appeared, each covering for the other's defects:
# `snapshot_file_exists` knows about `.gz`, while the read goes through a
# bare `open`. The check says "the file exists", the read fails with
# `FileNotFoundError`. While the corpus was uncompressed, both halves lied
# in agreement and stayed silent. A morning fork converted 65 calls and
# declared the census complete — by evening, compression uncovered FIVE
# more, all in `kir/course/`.

_SNAPSHOT_ASK = "snapshot_file_exists"
_SNAPSHOT_READ = "open_snapshot"


def _gather_snapshot_readers() -> list[dict]:
    """Functions that ask about compression, and WHAT exactly they then open.

    🔴 THE EXPRESSION IS COMPARED, NOT THE FACT OF A CALL, and this is half
    the rule's value. The first version shouted at every function where
    `snapshot_file_exists` and a bare `open` stood side by side, and on the
    very first run it slandered `program_source.floor_source`: it reads
    the snapshot CORRECTLY, via `open_snapshot`, and takes `passport.md` —
    a file that is never compressed — with the bare `open`. A crude rule
    would have called correct code a defect, and that kind of thing gets
    switched off within a week.

    THE BOUNDARY IS STATED: the TEXT of the expression is compared.
    `snapshot_file_exists(p)` followed by `open(str(p))` the instrument
    will let through. This is a deliberate shortfall toward silence: a
    false alarm costs more than a miss, because it kills trust in the whole
    registry.
    """
    out: list[dict] = []
    # 🔴 THE TRAVERSAL WENT OVER THE `kukai` ROOT, WHICH THIS SAME FILE
    # DECLARES ABSENT (fixed 29.08.2026, found by audit F-105 and
    # independent pass X-6).
    #
    # The coupling turned out ideally harmful. `_FOREIGN_ROOTS`, twenty
    # lines above, names `kukai` a root that does not exist in this tree
    # BY CONSTRUCTION — and that is correct. Traversing it returned EMPTY.
    # And the judge below treats empty material as a FAILURE — and that
    # too is correct, because "no agreements violated" over an unread
    # corpus is exactly the lie the whole registry exists against. Two
    # correct halves produced a third: an agreement that CAN NEVER PASS
    # and, at the same time, EXAMINES NOT ONE reader of snapshots. The 6/6
    # gate printed "MISMATCH" for it on every run, and what had mismatched
    # was the instrument, not the corpus.
    #
    # This escaped notice because `_BACKEND` is the PACKAGE's parent
    # (`/opt/kir`), so `_BACKEND/"kukai"` does not exist even in the
    # product's tree: the traversal was dead EVERYWHERE from the moment of
    # the split, not only here.
    #
    # THE SUBJECT OF THIS AGREEMENT IS READERS OF SNAPSHOTS, AND THEY LIVE
    # IN `kir`. Measurement of the fix: 31 functions ask about compression,
    # 11 read via `open_snapshot`, NOT ONE reads that same path with a bare
    # `open`. The neighboring agreements in this same file have walked
    # `kir` since the split.
    #
    # This traversal does not see, and must not see, the OWNER's readers:
    # the product's name cannot appear in the published package. Should
    # the owner want to check their own half, they will name it themselves,
    # as a port, not through our grep over their root.
    for path in _py_files("kir"):
        if "tests" in path.parts or path.name.startswith("test_"):
            continue
        try:
            src = path.read_text(encoding="utf-8")
        except Exception:      # noqa: BLE001
            continue
        if _SNAPSHOT_ASK not in src:
            continue
        out.extend(analyse_snapshot_source(
            src, str(path.relative_to(_BACKEND))))
    return out


def analyse_snapshot_source(src: str, label: str) -> list[dict]:
    """Parsing of ONE source file. Factored out so it can be checked.

    An instrument that only knows how to work on the live tree cannot be
    set on a forgery — meaning it cannot be proven to catch the defect it
    was set up for. We have this on record as a form: "a control on a
    degenerate input is green by construction".
    """
    out: list[dict] = []
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return out
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        asked: set[str] = set()
        opened_bare: set[str] = set()
        opened_shim: set[str] = set()
        for call in ast.walk(node):
            if not isinstance(call, ast.Call) or not call.args:
                continue
            fn = call.func
            name = fn.id if isinstance(fn, ast.Name) else None
            if name is None:
                continue
            arg = ast.unparse(call.args[0])
            if name == _SNAPSHOT_ASK:
                asked.add(arg)
            elif name == "open":
                opened_bare.add(arg)
            elif name == _SNAPSHOT_READ:
                opened_shim.add(arg)
        if not asked:
            continue
        out.append({
            "where": f"{label}:{node.lineno}",
            "func": node.name,
            "asked": sorted(asked),
            "collision": sorted(asked & opened_bare),
            "via_shim": sorted(asked & opened_shim),
        })
    return out


def _judge_snapshot_readers(material: list[dict]) -> list[str]:
    if not material:
        return ["ни одна функция не спрашивает snapshot_file_exists — "
                "материал пуст"]
    return [f"{r['where']} {r['func']}: спрашивает про сжатие у "
            f"{', '.join(r['collision'])} и читает ТО ЖЕ голым open"
            for r in material if r["collision"]]


def _break_snapshot_readers(material: list[dict]) -> list[dict]:
    if material:
        material[0]["collision"] = ["подделанный_путь"]
    else:
        material.append({"where": "подделка", "func": "f", "asked": ["p"],
                         "collision": ["p"], "via_shim": []})
    return material


# ─────────────────────────────────────────────────────────────────────────────
# AGREEMENT 4. TWO CLASSIFIERS OF THE SAME PROSE ANSWER THE SAME
# ─────────────────────────────────────────────────────────────────────────────
#
# Bought 21.08: `classify_bridge_error` and `classify_execution_error` judge
# THE SAME bridge prose, through different ladders of conditions. As long
# as they diverge, the same Revit response gets two different codes, and
# the author can be told "your code ran" about code that never started.
#
# The prose corpus is REAL: these are phrases the bridge actually sent
# live.

def _gather_classifiers() -> list[dict]:
    """Run BOTH classifiers over the corpus living beside them.

    🔴 THE CORPUS IS NOT MADE UP HERE, AND THIS WAS BOUGHT. The first
    version of this agreement invented its own eleven phrases — and
    declared four LEGITIMATE discrepancies to be defects: «not connected»
    and «ExternalEvent: Pending» are transport states BEFORE dispatch, and
    the execution path never gets such results at all. A guard for this
    very pair had already stood since 21.08 and had already worked out the
    boundary by name; I did not read it and set up a second carrier of the
    very knowledge I am writing this registry for. A second time within
    one file.
    """
    from kir.envelope import (DIVERGENT_BRIDGE_PROSE,
                                   SHARED_BRIDGE_PROSE,
                                   classify_bridge_error,
                                   classify_execution_error)
    out = []
    for prose, expected in SHARED_BRIDGE_PROSE:
        out.append({
            "prose": prose,
            "shared": True,
            "expected": str(expected),
            "bridge": str(classify_bridge_error(prose)),
            "execution": str(classify_execution_error(
                {"message": prose, "error": True})),
        })
    for prose, expected, why in DIVERGENT_BRIDGE_PROSE:
        out.append({
            "prose": prose,
            "shared": False,
            "expected": str(expected),
            "why": why,
            "bridge": str(classify_bridge_error(prose)),
            "execution": str(classify_execution_error(
                {"message": prose, "error": True})),
        })
    return out


def _judge_classifiers(material: list[dict]) -> list[str]:
    if not material:
        return ["корпус прозы пуст"]
    bad = []
    for row in material:
        if row["shared"]:
            if row["bridge"] != row["execution"]:
                bad.append(f"«{row['prose'][:60]}»: мост говорит "
                           f"{row['bridge']}, исполнение — {row['execution']}")
            elif row["bridge"] != row["expected"]:
                bad.append(f"«{row['prose'][:60]}»: оба говорят "
                           f"{row['bridge']}, а обещано {row['expected']}")
        else:
            # The discrepancy is LEGITIMIZED — but the bridge must know its
            # own case, otherwise the argument for the discrepancy stops
            # being valid and becomes an excuse.
            if row["bridge"] != row["expected"]:
                bad.append(f"«{row['prose'][:60]}»: расхождение узаконено "
                           f"доводом «{row.get('why','')[:40]}», а мост "
                           f"говорит {row['bridge']} вместо {row['expected']}")
    return bad


def _break_classifiers(material: list[dict]) -> list[dict]:
    if material:
        material[0]["execution"] = "подделка.другой_код"
    else:
        material.append({"prose": "подделка", "shared": True, "expected": "a",
                         "bridge": "a", "execution": "b"})
    return material


# ─────────────────────────────────────────────────────────────────────────────
# AGREEMENT 5. A COMPILER TWIN CARRIES ITS DISPOSITION
# ─────────────────────────────────────────────────────────────────────────────
#
# Bought 21.08, twice: `MIN_EXTENT_MM` was copied into the harvester and
# held 55 shapes; `ParamSpec.default` is dead for the `str` kind and lives
# on as a copy in emission.
#
# 🔴 WHY NOT "ONE NAME — ONE VALUE". Measurement across the whole tree: 489
# top-level numeric constants, 22 twins, 12 diverge in value — and MOST of
# the divergences are legitimate. `_FT` is 304.8 in one place and 0.3048 in
# another — that is foot→mm and foot→m, DIFFERENT quantities under one
# name. A blind rule would produce twelve alarms, of which two or three are
# real, and it would be switched off within a week. Hence:
#
#   * scope — only `kir` (the compiler, where all nine incidents happened);
#   * every twin must carry a DISPOSITION: either "one quantity, the
#     values must match", or "namesakes, different quantities";
#   * a NEW twin with no disposition is a refusal. This is a ratchet: it
#     does not require fixing the old, but it does not let a new one be
#     set up silently.

_TwinKey = str


@dataclass(frozen=True)
class TwinDisposition:
    same_quantity: bool
    why: str


#: The `kir` twins, worked out by name on 21.08.2026.
TWIN_DISPOSITIONS: dict[_TwinKey, TwinDisposition] = {
    "NOT_DONE": TwinDisposition(
        True, "код 2 означает, что действие не состоялось: общий внешний "
              "контракт главного CLI и MCP door (`kir/mcp/server.py` несёт "
              "свою копию, потому что дверь не импортирует `__main__`)"),
    "OPENING_JOIN_TOL_MM": TwinDisposition(
        True, "допуск примыкания проёма к стене, 300 мм. Одна величина: "
              "второй носитель (`decompile/graph_adjacency.py`) сам называет "
              "первый в комментарии — «Тот же допуск, что у "
              "`design_check.OPENING_JOIN_TOL_MM`». Найден 30.08.2026 вместе "
              "с формой `AnnAssign`, которой реестр не видел вовсе (F-106); "
              "значения сегодня СОВПАДАЮТ, и диспозиция заводится затем, "
              "чтобы разойтись они больше не могли молча"),
    "MIN_EXTENT_MM": TwinDisposition(
        True, "минимальный габарит тела: ops_solid — исходный носитель, "
              "surface повторяет его для поверхности. Одна величина"),
    "_COORD_LIMIT_MM": TwinDisposition(
        True, "предел координаты Ревита (±16 км в футах). Одна величина, "
              "и она физическая"),
    "_COORD_MAX_MM": TwinDisposition(
        True, "предел координаты кривой/меша. Одна величина"),
    "_EDGE_TOL": TwinDisposition(
        True, "ShortCurveTolerance Ревита, 1 мм. Одна величина в трёх местах"),
    "_FT_TO_MM": TwinDisposition(
        True, "фут в миллиметрах, 304.8. Одна величина, физическая константа"),
    "_MM2_PER_M2": TwinDisposition(
        True, "квадратных миллиметров в квадратном метре. Физическая"),
    "_CACHE_MAX": TwinDisposition(
        False, "однофамильцы: 8 связок клеша против 2 схем транспорта — "
               "разные кэши разных размеров, сводить нечего"),
    "_ORTHO_TOL": TwinDisposition(
        False, "однофамильцы: 1e-6 у съёма кривой (в футах, из Ревита) "
               "против 1e-8 у рекомпиляции (в долях единичного вектора). "
               "🔴 РАЗБОР СЛАБЫЙ: если обе про единичный вектор — это один "
               "дефект, и его надо мерить, а не объявлять"),
    "N_PBT": TwinDisposition(
        False, "однофамильцы: число прогонов ворот против числа фикстур "
               "генератора. Совпадение значения случайно"),
    "_APPLICATION_ID": TwinDisposition(
        False, "однофамильцы: разные SQLite-форматы KIRP ProjectStore и "
               "KIRS SavedExecution обязаны иметь разные application_id"),
    "_EPS": TwinDisposition(
        False, "однофамильцы: допуск времени schedule (секунды) против "
               "численного/геометрического допуска construction site (мм и углы)"),
    "_FEET_MM": TwinDisposition(
        True, "физическая константа фут→мм, 304.8, в shape emitter и "
              "transaction-unit emitter; значения обязаны совпадать"),
}


def _gather_twins() -> dict[str, dict[str, Any]]:
    vals: dict[str, dict[str, Any]] = {}
    for path in _py_files("kir"):
        if "tests" in path.parts or path.name.startswith("test_"):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except Exception:      # noqa: BLE001
            continue
        for node in tree.body:
            # 🔴 TWO DECLARATION FORMS, NOT ONE (F-106, 30.08.2026). Only
            # `ast.Assign` was taken here, and a constant with a TYPE
            # ANNOTATION (`X: float = 300.0`) never entered the twin
            # registry at all — silently. The registry promises "every
            # twin must carry a disposition", and the promise went unmet
            # for a whole form of writing it: what vanished was not a
            # registry row but a way to SET UP a twin around the ratchet.
            #
            # Measurement: `OPENING_JOIN_TOL_MM = 300.0` in
            # `design_check.py:406` (Assign) and `OPENING_JOIN_TOL_MM:
            # float = 300.0` in `decompile/graph_adjacency.py:91`
            # (AnnAssign) — the same tolerance, and the second carrier's
            # own comment says "The same tolerance as
            # design_check.OPENING_JOIN_TOL_MM". The registry did not see
            # them: there were 6 twins, now there are 7.
            #
            # An `AnnAssign` with no value (`X: float` — a type declaration
            # only) is not taken: there is no carrier of a value there,
            # nothing to compare.
            if isinstance(node, ast.Assign):
                value, targets = node.value, node.targets
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                value, targets = node.value, [node.target]
            else:
                continue
            if not isinstance(value, ast.Constant):
                continue
            v = value.value
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                continue
            for t in targets:
                if isinstance(t, ast.Name) and t.id.upper() == t.id:
                    vals.setdefault(t.id, {})[
                        str(path.relative_to(_BACKEND))] = v
    return {k: v for k, v in vals.items() if len(v) > 1}


def _judge_twins(twins: dict[str, dict[str, Any]]) -> list[str]:
    bad: list[str] = []
    for name, places in sorted(twins.items()):
        disp = TWIN_DISPOSITIONS.get(name)
        if disp is None:
            bad.append(
                f"{name}: НОВЫЙ близнец в {len(places)} местах "
                f"({', '.join(sorted(places))}) — заведи диспозицию в "
                f"TWIN_DISPOSITIONS: одна это величина или однофамильцы")
            continue
        if disp.same_quantity and len(set(places.values())) > 1:
            bad.append(
                f"{name}: объявлен ОДНОЙ величиной, а носители разошлись — "
                + ", ".join(f"{p}={v!r}" for p, v in sorted(places.items())))
    # A disposition whose twin has disappeared is clutter, not a refusal:
    # it will become a refusal if someone sets up the same name with a
    # different meaning.
    return bad


def _break_twins(twins: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    twins["_ПОДДЕЛЬНЫЙ_БЛИЗНЕЦ"] = {"a.py": 1, "b.py": 2}
    return twins


# ─────────────────────────────────────────────────────────────────────────────
# AGREEMENT 6. A CONSTANT CARRIES ITS OWN POPULATION
# ─────────────────────────────────────────────────────────────────────────────
#
# Bought 21.08 by FOUR of nine limits, and all share one shape: **a rule
# valid for one population is applied to another.**
#
#     MIN_RING_AREA=10,000  measured on 709 BUILDING rings -> applied to FAMILY profiles
#     MIN_EXTENT=100        from a PROFILE side             -> applied to HEIGHT
#     PLANE_ORIGIN=500 m    from a SIZE limit                -> applied to POSITION
#     tolerance=0.002·r     from a fraction of the radius    -> applied to a constant
#
# The docstring honestly states the NUMBER and the ARGUMENT and does not
# state WHAT IT WAS MEASURED ON — and, more importantly, does not say what
# the constant governs NOW. The latter changes on its own: it is enough for
# someone to set `min_val=THE_SAME_CONSTANT` on a new parameter, and the
# limit silently gains authority over a quantity it was never asked about.
#
# 🔴 WHY A RATCHET, NOT A BAN. Sorting out the old cases here is
# unnecessary and harmful: for three of the four constants, the extension
# turned out to be LEGITIMATE and backed by measurement. What is needed is
# different — that a NEW extension cannot be set up SILENTLY.


@dataclass(frozen=True)
class ConstantScope:
    """What the constant governs, and what it was measured on."""

    measured_on: str
    #: The registry parameters it legitimately sets a bound on. A pair
    #: (parameter name, side) — `min_val` and `max_val` are different
    #: authorities.
    governs: frozenset


#: Worked out by name on 21.08.2026 by traversing `ops_*.py`.
CONSTANT_SCOPE: dict[str, ConstantScope] = {
    "MIN_EXTENT_MM": ConstantScope(
        measured_on=(
            "живой замер 20.08.2026: опущен 100 -> 1 мм. Сторона ПРОФИЛЯ "
            "осталась 100 (contour.SHAPE_SIDE_MIN_MM) намеренно — плоская "
            "фигура шириной в миллиметр почти всегда описка. Высота — "
            "ДРУГАЯ величина, и решение о ней принято отдельно"),
        governs=frozenset({("height_mm", "min_val")})),
    "MAX_EXTENT_MM": ConstantScope(
        measured_on=(
            "предел РАЗМЕРА тела, 500 м. Он же стоит границей у `base_z_mm`, "
            "а это ПОЛОЖЕНИЕ, не размер, — та самая форма, которой 21.08 "
            "держался PLANE_ORIGIN. ЗАМЕРЕНО 21.08.2026 по ВСЕМУ корпусу "
            "разборов: 2 250 282 координаты Z, 76 зданий, диапазон "
            "−139.7 .. +324.0 м; за предел не выходит НИ ОДНО. Значит "
            "сегодня расширение законно, и это ЗАМЕР, а не объявление. "
            "🔴 ЗАПАС ВСЕГО 1.5x: 324 из 500 м. Лахта (462 м) и Бурдж "
            "(828 м) отметкой верха уже за пределом — первое же настоящее "
            "высотное здание потребует поднять число, и поднимать его надо "
            "будет ПО ЭТОЙ ЖЕ ОСИ (положение), а не по размеру тела"),
        governs=frozenset({("height_mm", "max_val"),
                           ("base_z_mm", "min_val"),
                           ("base_z_mm", "max_val")})),
    "MAX_RING_POINTS": ConstantScope(
        measured_on=(
            "число точек кольца контура. 64 -> 256 замером 02.09.2026: предел "
            "держал не ЦЕНУ, а НЕВИДИМОСТЬ квадратичной проверки "
            "самопересечения (при 64 точках пар 1 952). Обход всеми парами "
            "заменён заметанием по x — 256 точек: 44.5 мс -> 0.36 мс, — и "
            "вред замерен на настоящих семействах: внешние кольца отвергали "
            "67 из 652, отверстия 82 из 183; после подъёма 0 и 0. "
            "🔴 РАСПОРЯЖАЕТСЯ ВТОРЫМ ПАРАМЕТРОМ, И ЭТО ВЫВОД, А НЕ СОВПАДЕНИЕ: "
            "`direction_edge` у `create_beam_system` — ИНДЕКС РЕБРА опущенного "
            "контура, а рёбер у кольца ровно столько же, сколько точек, "
            "поэтому наибольший законный индекс на единицу меньше. До 02.09 "
            "там стояло `max_val=63` ЧИСЛОМ, и после подъёма кольца контур из "
            "100 точек был законен, а ребро 70 в нём назвать было нельзя — "
            "выведенная величина, записанная числом, перестаёт быть выводом"),
        governs=frozenset({("direction_edge", "max_val")})),
    "LIST_LIMIT_MAX": ConstantScope(
        measured_on=(
            "потолок длины ответа выборки — величина ТРАНСПОРТА, не "
            "геометрии; совокупность у неё одна и не растёт"),
        governs=frozenset({("limit", "max_val")})),
    "_FORCE_LIMIT": ConstantScope(
        measured_on=(
            "предел величины нагрузки. Распоряжается двенадцатью параметрами "
            "ОДНОГО опа (силы и моменты по трём осям, три погонности) — это "
            "одна совокупность, названная двенадцатью именами"),
        governs=frozenset(
            (n, side)
            for n in ("fx_n", "fy_n", "fz_n", "fx_n_per_m", "fy_n_per_m",
                      "fz_n_per_m", "fx_n_per_m2", "fy_n_per_m2",
                      "fz_n_per_m2", "mx_nm", "my_nm", "mz_nm")
            for side in ("min_val", "max_val"))),
}


def governed_bounds() -> dict[str, set[tuple[str, str]]]:
    """Who governs what RIGHT NOW — by traversing the syntax of `ops_*.py`.

    Only bounds named BY IDENTIFIER are taken: `min_val=MIN_EXTENT_MM`. A
    literal (`min_val=100`) is deliberately excluded — it has no name,
    meaning there is no population one could ask it about either. This is
    a stated boundary of the instrument, not a forgotten case.
    """
    out: dict[str, set[tuple[str, str]]] = {}
    for path in _py_files("kir"):
        if not path.name.startswith("ops_"):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except Exception:      # noqa: BLE001
            continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "ParamSpec"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)):
                continue
            pname = str(node.args[0].value)
            for kw in node.keywords:
                if kw.arg not in ("min_val", "max_val"):
                    continue
                for sub in ast.walk(kw.value):
                    if isinstance(sub, ast.Name) and sub.id.upper() == sub.id:
                        out.setdefault(sub.id, set()).add((pname, kw.arg))
    return out


def _judge_scope(actual: dict[str, set[tuple[str, str]]]) -> list[str]:
    bad: list[str] = []
    for name, pairs in sorted(actual.items()):
        scope = CONSTANT_SCOPE.get(name)
        if scope is None:
            bad.append(
                f"{name}: константа ставит границу "
                + ", ".join(f"{p}.{side}" for p, side in sorted(pairs))
                + " и НЕ РАЗОБРАНА — заведи запись в CONSTANT_SCOPE: на чём "
                  "она мерена и чем ей позволено распоряжаться")
            continue
        new = sorted(pairs - scope.governs)
        if new:
            bad.append(
                f"{name}: получила власть над "
                + ", ".join(f"{p}.{side}" for p, side in new)
                + f" — совокупности, о которой её не спрашивали. Мерено на: "
                f"{scope.measured_on[:120]}")
    return bad


def _break_scope(actual: dict[str, set[tuple[str, str]]]
                 ) -> dict[str, set[tuple[str, str]]]:
    actual.setdefault("MIN_EXTENT_MM", set()).add(("новая_величина_мм",
                                                   "min_val"))
    return actual


# ─────────────────────────────────────────────────────────────────────────────
# AGREEMENT 7. A NEW KIND GETS A ROW IN EVERY CENSUS THAT PROMISED COMPLETENESS
# ─────────────────────────────────────────────────────────────────────────────
#
# Bought 21.08.2026 by FOUR waves in a row, and only the last of them is
# mine:
#
#     kind         introduced  form census   expressibility  plurality
#     surface      20.08       yes           yes             🔴 NO
#     solid_parts  20.08       🔴 NO         🔴 NO           🔴 NO
#     plane        21.08       🔴 NO         yes             🔴 NO
#     dir_xyz      21.08       🔴 NO         🔴 NO           🔴 NO
#
# `solid_parts` stood without a row for TWO FULL DAYS in three registries
# at once.
#
# 🔴 WHY THIS WENT UNNOTICED, EVEN THOUGH EVERY REGISTRY HONESTLY TURNED
# RED. It turned red in ITS OWN test, that is, AFTER the wave and only on
# the full suite — and the full suite in this box halts against its own
# memory ceiling. On top of that, three of the five files did not compile
# at all (a solo op with no sample). A red that no one sees is silence.
#
# Here the same question takes 0.1 seconds and rides along with the other
# six.
#
# THE BOUNDARY, STATED HONESTLY: ONLY the registries that THEMSELVES
# promised completeness in their own docstring are asked.
# `program_source.MM_KINDS` does not promise completeness and should not:
# `bool`, `enum`, or `str` have no millimeters at all (18 kinds out of 38
# are covered by construction). Demanding a row from it too would mean
# setting up an instrument that shouts twenty times at a correct tree — and
# that kind of thing gets switched off within a week.


def _gather_kind_rows() -> dict[str, dict]:
    """Three censuses that PROMISED completeness, and what they actually have."""
    from kir import spec
    from kir.course import expressiveness as _ex
    from kir.course import shape as _sh

    kinds = set(spec.PARAM_KINDS)
    plural = set(getattr(spec, "PLURAL_KINDS", ()) or ())
    try:
        from kir.tests import test_unpinned_plural_witnesses as _pl
        plural = set(_pl.PLURAL_KINDS) | set(_pl.SCALAR_KINDS)
    except Exception:      # noqa: BLE001 — the test might have failed to build; say so
        plural = None

    return {
        "перепись форм (course/shape)": {
            "missing": sorted(_sh.unclassified_kinds()),
            "stray": sorted(_sh.stray_kinds()),
        },
        "перепись выразимости (course/expressiveness)": {
            "missing": sorted(kinds - set(_ex.CENSUS)),
            "stray": sorted(set(_ex.CENSUS) - kinds),
        },
        "плюральность/скалярность": (
            {"missing": sorted(kinds - plural), "stray": sorted(plural - kinds)}
            if plural is not None
            else {"unreadable": "реестр не поднялся — судить нечем"}),
    }


def _judge_kind_rows(rows: dict[str, dict]) -> list[str]:
    bad: list[str] = []
    for name, state in sorted(rows.items()):
        if "unreadable" in state:
            bad.append(f"{name}: {state['unreadable']}")
            continue
        if state["missing"]:
            bad.append(f"{name}: рода реестра БЕЗ строки — "
                       + ", ".join(state["missing"]))
        if state["stray"]:
            bad.append(f"{name}: строки о родах, которых в реестре НЕТ — "
                       + ", ".join(state["stray"]))
    return bad


def _break_kind_rows(rows: dict[str, dict]) -> dict[str, dict]:
    first = sorted(rows)[0]
    rows[first] = {"missing": ["поддельный_род"], "stray": []}
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# AGREEMENT 8. THE CONTRACT DOES NOT LIE ABOUT READING
# ─────────────────────────────────────────────────────────────────────────────
#
# Bought by THREE incidents over five days, and the third one was found by
# this instrument, not a human:
#
#     author_family    21.08  «отношения в рецепте НЕТ ВОВСЕ»
#                             GetAssociatedFamilyParameter — family_recipe:1987
#     join_elements    22.08  «nothing in decompile/ reads it yet:
#                             measured 2026-08-17, zero occurrences»
#                             GetJoinedElements — join_extract:823
#     create_stairs_run       «GetStairsRuns() is called nowhere in decompile/»
#                             GetStairsRuns — sketch_extract:2047
#
# 🔴 THE LIFETIME OF THE LIE WAS MEASURED FROM THE JOURNAL, NOT ESTIMATED. For
# the join: `39ebd521` at 18.08 07:03 introduces the read, `518325f3` at
# 18.08 07:19 writes «ноль вхождений» — SIXTEEN MINUTES, one session, one
# hand. For the stair flight it is worse: the read has been in place since
# 18.07 20:27, the text was written on 15.08 — the record was BORN STALE by
# 28 days and stood for another seven.
#
# WHY NO ONE CAUGHT THIS, EVEN THOUGH THERE ARE TWO GUARDS. I checked both
# before adding a third one (lesson from 21.08: added an agreement without
# asking whether a guard already existed, and bought a fixable defect):
#
#   * `record_ratchet` holds the FORM of the record and its DEADLINE — and
#     SAYS ITSELF that it cannot check «что причина всё ещё ПРАВДА»; for all
#     three cases the deadline had not passed, the ratchet stayed silent
#     LEGITIMATELY;
#   * `test_reverse_entrypoints_exist` asks whether the named entry point is
#     REACHABLE. This is about `entrypoints`, not about `reason`, and about
#     our code, not about the Revit API.
#
# Nobody asked "does the thing the record says doesn't happen actually
# happen".
#
# WHAT EXACTLY IS CHECKED, AND THE BOUNDARY IS NAMED, NOT LEFT UNSAID. The
# API member named in the contract text is searched for in the EMITTED C# of
# the capture — as a CALL on the receiver of our emission (`__что-то.Член(`)
# or on the full name `Autodesk.…`. This is a convention of the tree itself,
# held by agreement 2 as well. The instrument:
#
#   * does NOT see a PROPERTY read (`Opening.Host`, `FlexDuct.Points`): a
#     property has no parentheses, and there is nothing to tell it apart
#     from prose. An undercount TOWARD SILENCE, and it is named;
#   * does NOT read prose for "is this a negation". The first version tried
#     it — and it slandered `create_extrusion_roof`, whose text ITSELF says
#     «the profile IS captured». So polarity is not guessed, it is DECLARED:
#     the called member is required to carry the disposition. Exactly the
#     form of agreements 5 and 6, and for the same reason — an instrument
#     that screams at correct code survives a week.
#
# MEASURING THE RULE ON THE LIVE TREE (22.08.2026): 73 contracts, 29 API
# members named, TWO turned out to be calls in the C#. The rule "a member
# appears as a substring" would have given 12 alerts, of which two are
# correct; the rule "a `Класс.Член`-shaped string" gives 8. The numbers are
# measured, not estimated, and they are what chose the edition.


#: API members that the CAPTURE ACTUALLY CALLS, itemized by name.
#: The key is `(оп, Класс.Член)`, the value is what STILL remains unread.
#: A newly called member without an entry here is a refusal. This is a
#: ratchet: it does not require fixing the old ones, but it does not let a
#: new lie about reading be added silently.
#:
#: 🔴 AN ENTRY HERE DOES NOT MEAN "THE CONTRACT LIED". It means "the member
#: is called, and it is itemized what remains at that point". For
#: `join_elements` the contract tells the truth ITSELF — the entries still
#: stand, because the ratchet holds the FACT of the call, not an evaluation
#: of the prose: relying on the next person writing the member without
#: `Класс.` and slipping past the rule would mean guarding SPELLING.
CALLED_MEMBER_DISPOSITIONS: dict[tuple[str, str], str] = {
    ("join_elements", "JoinGeometryUtils.GetJoinedElements"): (
        "род `joined_to` ЧИТАЕТСЯ (join_extract.py:823) и ПОДНИМАЕТСЯ "
        "(lift.py:lift_joins). Не прочитан ПОРЯДОК РЕЗА — SwitchJoinOrder / "
        "IsCuttingElementInJoin, вызовов ноль во всём decompile/"),
    ("join_elements", "WallUtils.IsWallJoinAllowedAtEnd"): (
        "род `join_allowed_at_end` ЧИТАЕТСЯ (join_extract.py:849/851) и НЕ "
        "поднимается: опа под свойство одного конца в реестре нет вовсе. Это "
        "граница ЯЗЫКА, а не пробел захвата"),
    ("join_elements", "LocationCurve.get_ElementsAtJoin"): (
        "род `elements_at_end_join` ЧИТАЕТСЯ (join_extract.py:885) и НЕ "
        "поднимается: опа под стык концами нет. Подменять его `join_elements` "
        "нельзя — на одной паре стен отношения бывают противоположны"),
    ("create_extrusion_roof", "ExtrusionRoof.GetProfile"): (
        "профиль ЧИТАЕТСЯ, и контракт это говорит сам («the profile IS "
        "captured»). Рабочая плоскость тоже — с 22.08.2026 (`extract.py` "
        "берёт OST_CLines через .OfClass(typeof(ReferencePlane))). Остался "
        "ДИАПАЗОН выдавливания: EXTRUSION_START_PARAM / EXTRUSION_END_PARAM "
        "не встречаются в decompile/ ни разу, проверено 22.08"),
    ("create_stairs_run", "Stairs.GetStairsRuns"): (
        "марши ЧИТАЮТСЯ с 18.07.2026 и путь каждого лежит в боковом индексе "
        "эскизов (замер 22.08: 173/173, 48/48, 26/26, 9/9 маршей с путём). "
        "Не прочитаны Stairs.BaseElevation и justification — два из пяти "
        "обязательных входов опа. Текст контракта исправлен 22.08"),
    ("create_stairs_run", "StairsRun.GetStairsPath"): (
        "путь марша ЧИТАЕТСЯ (sketch_extract.py:2067) и хранится "
        "типизированным. Тот же пробел, что строкой выше: отметка базы и "
        "justification"),
}

#: The receiver of the emitted C# in this tree is either our local variable
#: `__что-то`, or the full name `Autodesk.Revit.DB.…`. Prose (`"GetProfile
#: failed: "`, `FlexDuct.Points (IList<XYZ>`) does not fit this, and this is
#: MEASURED: without a constraint on the receiver, the rule gave two false
#: alarms out of four.
#:
#: 🔴 WHAT THIS MATCHER DOES NOT SEE, NAMED AFTER THE 22.08.2026 MISS. It
#: looks for the pair `Класс.Член` in the contract text and a call
#: `приёмник.Член(` in the capture. It does not extract a BARE TYPE NAME at
#: all, and the type is assembled not by a member call but by
#: `.OfClass(typeof(Имя))` inside the emitted C# string. On that same day the
#: `create_extrusion_roof` contract claimed «ReferencePlane appear nowhere in
#: decompile/», while `extract.py:686` was already collecting planes — and
#: the agreement stayed GREEN.
#:
#: WHY IT WAS NOT FIXED RIGHT THERE, but named instead: a candidate rule
#: ("a bare type name in the contract + typeof(Имя) in the capture") was
#: calibrated and REJECTED — 11 alerts across the registry, of which ONE is
#: correct: the rest are a plain mention of the type in the contract's
#: prose, not a claim of its absence. A narrower rule ("a name inside an
#: EXPLICIT claim of absence"; 5 out of 73 contracts have such claims) gave 3
#: matches, of which ONE is CORRECT: the other two are prose of the CAPTURE
#: ITSELF, naming its own absence (`join_extract.py:100`, `lift.py:4613`).
#: That is, the matcher would have to tell code apart from prose inside
#: multi-line literals, and that is already parsing, not grep.
#:
#: An instrument that gives two false alarms out of three is worse than
#: none: it trains people to work around it. So a NAMED GAP stands here,
#: rather than a raw rule.
_CS_RECEIVER = r"(?:__\w+|Autodesk(?:\.\w+)+)"

#: `Класс.Член` in the contract text. The member is also matched in the form
#: `get_Свойство` — that is how Revit names indexed properties, and
#: `get_ElementsAtJoin` is exactly that.
_API_MEMBER_RE = re.compile(
    r"\b([A-Z][A-Za-z0-9]{2,})\.((?:get_)?[A-Za-z][A-Za-z0-9]{2,})\b")


def capture_call_sites(member: str, sources: Mapping[str, str]) -> list[str]:
    """Where the CAPTURE calls this member — `файл:строка`, from the capture's source.

    Broken out as a separate name so the instrument can be pointed at a
    FORGED source. A function that can only work on the live tree cannot
    prove that it catches the very defect it was written for — this is our
    recorded form ("a control green by construction on a degenerate input",
    12.08).
    """
    pattern = re.compile(rf"{_CS_RECEIVER}\.{re.escape(member)}\s*\(")
    out: list[str] = []
    for label, text in sorted(sources.items()):
        for match in pattern.finditer(text):
            out.append(f"{label}:{text[:match.start()].count(chr(10)) + 1}")
    return out


def _capture_sources() -> dict[str, str]:
    """The CAPTURE's sources are production `decompile/` only.

    Tests are excluded on purpose: a test that names a member does not make
    the read happen, and counting it would mean confirming the WRITING of a
    name instead of the event — exactly the defect that
    `test_reverse_entrypoints_exist` addresses.
    """
    out: dict[str, str] = {}
    for path in _py_files("kir/decompile"):
        if "tests" in path.parts or path.name.startswith("test_"):
            continue
        try:
            out[str(path.relative_to(_BACKEND))] = path.read_text(
                encoding="utf-8")
        except Exception:      # noqa: BLE001
            continue
    return out


def _gather_capture_claims() -> list[dict]:
    """Every API member named by the contract, and whether the capture CALLS it."""
    from kir.reverse_contract import REVERSE_CONTRACTS

    sources = _capture_sources()
    rows: list[dict] = []
    for op_name, contract in sorted(REVERSE_CONTRACTS.items()):
        text = " ".join((contract.reason, contract.limitation,
                         " ".join(contract.sources)))
        for cls, member in sorted(set(_API_MEMBER_RE.findall(text))):
            rows.append({
                "op": op_name,
                "mode": contract.mode.value,
                "member": f"{cls}.{member}",
                "call_sites": capture_call_sites(member, sources),
            })
    return rows


def _judge_capture_claims(rows: list[dict]) -> list[str]:
    if not rows:
        return ["ни один контракт не называет члена API — материал пуст, "
                "проверять нечего (это отказ, а не согласие)"]
    bad: list[str] = []
    for row in rows:
        if not row["call_sites"]:
            continue
        key = (row["op"], row["member"])
        if key in CALLED_MEMBER_DISPOSITIONS:
            continue
        bad.append(
            f"{row['op']} [{row['mode']}]: называет {row['member']}, а захват "
            f"ЗОВЁТ его — {', '.join(row['call_sites'][:3])}. Либо текст "
            f"контракта врёт про чтение, либо заведи строку в "
            f"CALLED_MEMBER_DISPOSITIONS: что при этом ВСЁ ЕЩЁ не "
            f"прочитано")
    return bad


def _break_capture_claims(rows: list[dict]) -> list[dict]:
    # 🔴 THE FORGERY TAKES A NONEXISTENT OP, NOT THE FIRST LINE. Breaking the
    # first one would mean hitting an op that ALREADY HAS a disposition —
    # the judge would legitimately stay silent, and the agreement would come
    # out EMPTY. The same trap was bought by agreement 2, with Cyrillic in a
    # helper's name.
    rows.append({
        "op": "поддельный_оп", "mode": "capture_gap",
        "member": "ПоддельныйКласс.ПоддельныйЧлен",
        "call_sites": ["kir/decompile/подделка.py:1"],
    })
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# REGISTRY
# ─────────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
# AGREEMENT 9. A COMPRESSIBLE NAME OPENS ONLY THROUGH THE SEAM
# ─────────────────────────────────────────────────────────────────────────────
#
# Bought by the 29–30.08.2026 audit (E-26). The agreement "whoever asks
# about compression reads through it too" asks: "did whoever ASKED about
# compression read through compression?" It is correct and catches its own
# kind. But the defect has a SECOND entry point, and it is wider: NOT ASKING
# AT ALL. A function that simply opens a snapshot with a bare `open` does
# not exist for its neighbor — it is filtered out by two filters,
# `_SNAPSHOT_ASK not in src` (the whole FILE) and `if not asked` (the whole
# FUNCTION).
#
# Three numbers, taken in ONE run on 30.08.2026 on a cooled-down decompile
# of `clash_final`, contradict each other, and that is the finding:
#     L0JSONLReader (through the seam)  -> 77 category receipts
#     the same file, bare .open()       -> FileNotFoundError
#     the neighboring agreement         -> «расхождений нет»
# This cannot be a coincidence: the neighbor is looking at the wrong
# subject.
#
# THE SUBJECT IS THE NAMES THAT THE JANITOR COMPRESSES, and the list is
# taken FROM IT, not compiled here: two lists that are required to match are
# this tree's named defect. The janitor compresses files, and it is the
# authority.

_BARE_ACCESS = ("exists", "is_file", "read_text", "read_bytes", "open", "stat")
_SHIM_NAMES = ("snapshot_file_exists", "open_snapshot", "read_snapshot_text",
               "gz_path", "snapshot_raw_size")

#: 🔴 PLACES THAT ARE KNOWN AND NOT YET FIXED — A CLOSED LIST WITH AN OWNER.
#:
#: Set up by the same convention as `MUTE_SOURCES` on the muteness ratchet,
#: and for the same reason: an agreement started RED gets switched off in a
#: week, while an agreement started silent about a live violation guards
#: nothing. The third way is to name the violation HERE, by name, with an
#: owner and a cost.
#:
#: The list has the right only to SHRINK: a line whose place has been fixed
#: must be struck out by the SAME COMMIT that fixes the place (guarded by
#: `_judge_bare_snapshot_access`, the "ghosts" branch). The rule is written
#: in the muteness ratchet's docstring and applied here literally: whoever
#: fixed the place moves their own line.
#:
#: The value is (file owner, cost of the violation in words).
#: 🔴 EMPTY SINCE 30.08.2026, AND THIS IS NOT "NOTHING TO GUARD". The only
#: entry — `kir/a5_contract.py::_load_a5_snapshot_manifest` — was STRUCK OUT
#: by the same commit that fixed the place: the read was switched to go
#: through the seam. The list moves in one direction only, and letting a
#: fixed place stand makes the agreement less truthful with every passing
#: day.
BARE_ACCESS_OPEN: dict[tuple[str, str], tuple[str, str]] = {}


def analyse_bare_snapshot_access(src: str, label: str) -> list[dict]:
    """Places where a compressible NAME is opened bypassing the seam. Takes TEXT.

    The same argument as for `analyse_snapshot_source`: an instrument that
    can only work on the live tree cannot be pointed at a forgery, and
    therefore cannot prove that it catches the deliberate defect.

    🔴 THE BOUNDARY IS NAMED, NOT HIDDEN. The name must stand as a LITERAL
    IN THE SAME EXPRESSION that opens it: a name right inside the call's
    parentheses is visible, but `p = root / name; p.open()` is not. This is
    a deliberate undercount toward silence, exactly as with the neighboring
    agreement: a false alarm costs more than a miss, because an agreement
    that screams at correct code gets switched off within a week. Measuring
    the fix: a crude rule ("the name is mentioned SOMEWHERE in the
    function") gives 5 places, of which 3 are false and all three look
    convincing (`corpus_catalog.load_catalog` does name `L0.jsonl`, but
    opens `passport.md`); the precise rule gives exactly the real ones.
    """
    from kir.instruments.snapshot_janitor import SNAPSHOT_FILES

    out: list[dict] = []
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return out
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        uses_shim = False
        bare: list[tuple[int, str, str]] = []
        for call in ast.walk(node):
            if not isinstance(call, ast.Call):
                continue
            fn = call.func
            name = (getattr(fn, "id", None) if isinstance(fn, ast.Name)
                    else getattr(fn, "attr", None))
            if name in _SHIM_NAMES:
                uses_shim = True
                continue
            if name == "open" and isinstance(fn, ast.Name):
                expr = ast.unparse(call.args[0]) if call.args else ""
            elif name in _BARE_ACCESS and isinstance(fn, ast.Attribute):
                expr = ast.unparse(fn.value)
            else:
                continue
            hit = [s for s in SNAPSHOT_FILES
                   if f"'{s}'" in expr or f'"{s}"' in expr]
            if hit:
                bare.append((call.lineno, hit[0], expr))
        if bare:
            out.append({"where": label, "func": node.name,
                        "uses_shim": uses_shim,
                        "bare": [{"line": ln, "name": nm, "expr": ex}
                                 for ln, nm, ex in sorted(bare)]})
    return out


def _gather_bare_snapshot_access() -> dict:
    """Material AND DENOMINATOR in one piece.

    🔴 THE DENOMINATOR HERE IS NOT "THE MATERIAL IS NONEMPTY", AND THIS WAS
    CAUGHT BY MEASUREMENT, NOT FORESEEN. The package proposed treating empty
    material as a walk failure — the reasoning being that `snapshot_io`
    itself opens these names with a bare `open` and would always land in the
    findings. The 30.08.2026 run: it does NOT land there, the names there
    arrive as a VARIABLE, and the precise rule only sees a literal. Across
    the whole tree there is EXACTLY ONE function with material — the very
    violation itself. So "material is nonempty" would be satisfied by the
    violation ITSELF, and after it is fixed the agreement would become RED
    FOREVER. A check that is always red guards nothing.

    That is why the denominator is the NUMBER OF FILES WALKED: it answers
    "did the walk happen", while the material answers "was anything found".
    These are different questions, and here they are kept apart.
    """
    material: list[dict] = []
    walked = 0
    for path in _py_files("kir"):
        if "tests" in path.parts or path.name.startswith("test_"):
            continue
        try:
            src = path.read_text(encoding="utf-8")
        except Exception:      # noqa: BLE001
            continue
        walked += 1
        material.extend(analyse_bare_snapshot_access(
            src, str(path.relative_to(_BACKEND))))
    return {"walked": walked, "sites": material}


def _judge_bare_snapshot_access(material: dict) -> list[str]:
    walked = material.get("walked", 0)
    sites = material.get("sites", [])
    if walked < 200:
        return [f"обход прошёл всего {walked} файлов — это заявление О ХОДОКЕ, "
                f"а не о дереве; согласие ничего не проверило"]
    out: list[str] = []
    live: set = set()
    for r in sites:
        if r["uses_shim"]:
            continue
        key = (r["where"], r["func"])
        live.add(key)
        if key in BARE_ACCESS_OPEN:
            continue
        for b in r["bare"]:
            out.append(f"{r['where']}:{b['line']} {r['func']}: открывает "
                       f"{b['name']} мимо шва (`{b['expr']}`), и шва в этой "
                       f"функции нет")
    # 🔴 THE LIST MOVES IN ONE DIRECTION ONLY. Letting a fixed place stand
    # makes the agreement less truthful with every passing day — the same
    # ratchet as `MUTE_SOURCES`, and the same cost: the SAME commit that
    # fixes the place moves the line.
    for key in sorted(set(BARE_ACCESS_OPEN) - live):
        out.append(f"{key[0]}::{key[1]} больше не открывает сжимаемое имя мимо "
                   f"шва — вычеркни строку из BARE_ACCESS_OPEN тем же "
                   f"коммитом, что починил место")
    return out


def _break_bare_snapshot_access(material: dict) -> dict:
    material["sites"] = list(material.get("sites", ())) + [
        {"where": "подделка", "func": "f", "uses_shim": False,
         "bare": [{"line": 1, "name": "L0.jsonl", "expr": "root / 'L0.jsonl'"}]}]
    return material



# ─────────────────────────────────────────────────────────────────────────────
# AGREEMENT 10. THE FEED HANDED TO THE LIFT IS COMPLETE BY COUNT, NOT BY ATTENTION
# ─────────────────────────────────────────────────────────────────────────────
#
# Bought by the 30.08.2026 audit (F-304), and the cost is measured in
# BUILDINGS. The set of side indexes fed to the lift was HANDWRITTEN in
# three places and diverged: `orchestrator.decompile` fed ten,
# `relift_offline` fed eight, the compile gate fed seven. The gate's
# comment, meanwhile, claimed «ВСЕ семь боковых индексов, ровно как их
# передаёт `relift_offline.relift` и живой конвейер», and itself named the
# cost of a miss: «индекс, забытый здесь, не роняет гейт, а ТИХО опускает
# его на деградированное представление».
#
# Coverage taken on the live corpus on 30.08.2026 (81 decompiles with L0):
#     group.index.json      present in 67 decompiles   <- almost the whole corpus
#     dimension.index.json  present in 10
#     join.index.json       present in  7
# A direct measurement of the lift on `k2v33_join2`: the same input, the
# same document, a set of seven against a set of ten — 40 631 ops against
# 50 074, and the whole difference is of one kind: +9 443 `create_dimension`.
# Nine thousand operations the gate never saw are not a line in a report,
# but a WHOLE KIND, absent entirely.
#
# Adding the three names to the gate would mean starting a FOURTH
# handwritten list that will fall behind again tomorrow. So the set lives in
# ONE function (`relift_offline.side_indexes_for`), and completeness is held
# by COUNT: the authority is the SIGNATURE OF `lift_document_detailed`
# ITSELF.

#: Lift parameters that the offline feed does NOT supply ON PURPOSE. Empty
#: today — and it must stay empty until someone writes a reason here. An
#: entry without a reason is forbidden by the check below: otherwise an
#: exception would become a way to work around the instrument, not to name a
#: decision.
LIFT_FEED_EXCEPTIONS: dict[str, str] = {}


def _gather_lift_feed() -> dict:
    import inspect

    from kir.decompile import lift
    from kir.instruments import relift_offline

    accepted = set(inspect.signature(
        lift.lift_document_detailed).parameters) - {"document"}
    supplied = {name for name, _file, _env
                in relift_offline._SIDE_INDEX_FEED}
    return {"accepted": sorted(accepted), "supplied": sorted(supplied)}


def _judge_lift_feed(material: dict) -> list[str]:
    accepted = set(material.get("accepted", ()))
    supplied = set(material.get("supplied", ()))
    # 🔴 THE DENOMINATOR ON ITS OWN LINE. An empty signature would give
    # "nothing was missed" — green by construction, exactly the form
    # because of which a neighboring agreement once printed a verdict about
    # an unread corpus.
    if len(accepted) < 5:
        return [f"лифт принимает всего {len(accepted)} индексов — это "
                f"заявление О ЗОНДЕ, а не о лифте; согласие ничего не "
                f"проверило"]
    out = [f"{name}: лифт его принимает, офлайн-состав не подаёт и в "
           f"исключения не внесён"
           for name in sorted(accepted - supplied - set(LIFT_FEED_EXCEPTIONS))]
    # An exception without a reason is a way to work around the instrument, not a decision.
    out += [f"{name}: внесён в LIFT_FEED_EXCEPTIONS без довода"
            for name, why in sorted(LIFT_FEED_EXCEPTIONS.items())
            if len(str(why).strip()) < 30]
    # Letting a fixed place stand moves in one direction only — as
    # everywhere in this tree: an exception for a name the lift no longer
    # accepts is a lie.
    out += [f"{name}: в LIFT_FEED_EXCEPTIONS, но лифт такого параметра не "
            f"принимает — вычеркни"
            for name in sorted(set(LIFT_FEED_EXCEPTIONS) - accepted)]
    return out


def _break_lift_feed(material: dict) -> dict:
    material["supplied"] = [n for n in material.get("supplied", ())][1:]
    return material


# ─────────────────────────────────────────────────────────────────────────────
# THE ROAD FROM A BUILT BODY TO THE REGISTRY
# ─────────────────────────────────────────────────────────────────────────────
#
# Bought by the 30.08.2026 audit (E-49), and bought FROM THE REGISTRY ITSELF.
#
# All three registry checks WALK the `AGREEMENTS` tuple. So an agreement
# REMOVED FROM THE TUPLE turns red nowhere: the list got shorter, and the
# walks are trivially green. Proved by a mutation on the live tree — the
# entry `состав_подачи_лифту_полон` was cut out, its three bodies
# (`_gather_lift_feed`, `_judge_lift_feed`, `_break_lift_feed`) were left IN
# PLACE:
#
#     agreements in the registry 9 · all hold: True · 31 passed, EXIT=0
#     the only trace — 43 subtests became 40, and no one is watching for that number
#
# 🔴 An instrument that is written and not wired in is `E-7`, and a registry
# set up to catch EXACTLY THAT did not catch it IN ITSELF. Any agreement
# could be switched off with a single line, silently.
#
# THIS IS THE TENTH FORM OF AN UNFIT CONTROL: the control guards the SET,
# while the defect lives on the ROAD. All three walks honestly answer "what
# is DECLARED in the tuple" and none of them answers "what was built and
# ARRIVED". It is fixed by the same thing that catches it: the denominator
# is taken from the BUILT BODIES (live objects of the module, not the
# file's text), and the tuple becomes the side under check, not the source
# of truth.
#
# 🔴 THE BOUNDARY IS NAMED. This guard answers "does a built body arrive"
# and does NOT answer "was the agreement deleted along with its bodies":
# there, FUNCTION NAMES disappear, and a different instrument stands over
# that — the additive-edit gate (`/opt/kir-audit/additive_gate.py`), which
# counts functions BEFORE and AFTER. Two instruments close the road from two
# ends; neither closes it alone.

#: Agreement bodies deliberately NOT wired into the registry. Empty today —
#: and it must stay empty until someone writes a reason here. An entry
#: without a reason is forbidden by the check below: otherwise an exception
#: would become a way to work around the instrument, not to name a decision.
#: The same convention as `LIFT_FEED_EXCEPTIONS` and `BARE_ACCESS_OPEN`, and
#: the same cost: the SAME commit that wires a body into the registry
#: strikes out the line.
BODIES_OFF_THE_REGISTRY: dict[str, str] = {}

#: How many bodies the walk is required to SEE for its answer to be about the
#: tree, not about itself. Eight agreements are sixteen bodies; today there
#: are 22. The denominator is on its own line for the same reason as in
#: `_judge_lift_feed`: an empty walk would give "nothing was lost" — green by
#: construction.
_ROAD_FLOOR = 16


def _registry_roster() -> tuple[Agreement, ...]:
    """Everything the run asks about: the road guard PLUS the registry itself.

    The road guard lives as a SEPARATE constant, not a line in `AGREEMENTS`:
    an agreement guarding the tuple from inside the tuple is switched off by
    the very same move it was set up against.
    """
    return (REGISTRY_ROAD,) + AGREEMENTS


def _gather_registry_road() -> dict:
    """The material is taken by EXECUTION: live objects of the module, not its text.

    A text-based probe here would be the fifth form of an unfit control — it
    breaks from someone else's fix (a neighboring commit switched the gate
    to `**feed`, and the text probe showed growing debt where the debt was
    actually closed).
    """
    here = globals()
    built = sorted(
        name for name, obj in here.items()
        if (name.startswith("_judge_") or name.startswith("_break_"))
        and callable(obj)
        and getattr(obj, "__module__", None) == __name__)
    wired = set()
    for a in _registry_roster():
        wired.add(getattr(a.judge, "__name__", "<без имени>"))
        wired.add(getattr(a.break_it, "__name__", "<без имени>"))
    return {"built": built, "wired": sorted(wired)}


def _judge_registry_road(material: dict) -> list[str]:
    built = list(material.get("built", ()))
    wired = set(material.get("wired", ()))
    if len(built) < _ROAD_FLOOR:
        return [f"обход нашёл всего {len(built)} тел согласий при пороге "
                f"{_ROAD_FLOOR} — это заявление О ЗОНДЕ, а не о реестре; "
                f"сторож ничего не проверил"]
    out = [f"{name}: тело построено, но НЕ ДОЕЗЖАЕТ до AGREEMENTS — "
           f"согласие выключено одной строкой и молча (E-49)"
           for name in built
           if name not in wired and name not in BODIES_OFF_THE_REGISTRY]
    # An exception without a reason is a way to work around the instrument, not a decision.
    out += [f"{name}: внесён в BODIES_OFF_THE_REGISTRY без довода"
            for name, why in sorted(BODIES_OFF_THE_REGISTRY.items())
            if len(str(why).strip()) < 30]
    # Letting a fixed place stand moves in one direction only: an exception
    # for a body that has already arrived, or no longer exists, is a lie.
    out += [f"{name}: в BODIES_OFF_THE_REGISTRY, но тело либо доехало до "
            f"реестра, либо его больше нет — вычеркни"
            for name in sorted(BODIES_OFF_THE_REGISTRY)
            if name in wired or name not in built]
    return out


def _break_registry_road(material: dict) -> dict:
    """The mutation drops the name ON THE ROAD, leaving the body built.

    🔴 Exactly the defect that was bought: the bodies are in place, the
    entry left the tuple. The mutation is matched TO THE SUBJECT and must
    change what the judge READS: the name dropped is one known to be among
    the built ones and not covered by an exception. Otherwise it would be
    the fourth form — an identity mutation.
    """
    built = list(material.get("built", ()))
    dropped = next((n for n in built if n not in BODIES_OFF_THE_REGISTRY), None)
    material["wired"] = [n for n in material.get("wired", ()) if n != dropped]
    return material


AGREEMENTS: tuple[Agreement, ...] = (
    Agreement(
        name="состав_подачи_лифту_полон",
        claim="всякий боковой индекс, который принимает lift_document_detailed, "
              "подаётся общим офлайн-составом либо назван исключением с доводом",
        why="F-304 (30.08.2026): состав был рукописным в трёх местах и "
            "разошёлся — 10 у orchestrator, 8 у relift_offline, 7 у ворот. "
            "group.index.json лежит у 67 разборов из 81; прямой замер лифта на "
            "k2v33_join2 дал +9443 create_dimension от трёх недостающих имён",
        gather=_gather_lift_feed,
        judge=_judge_lift_feed,
        break_it=_break_lift_feed,
    ),
    Agreement(
        name="сжимаемое_имя_открывается_только_швом",
        claim="сжимаемое имя из SNAPSHOT_FILES открывается только через "
              "snapshot_io; функция без шва не имеет права его называть",
        why="E-26 (29–30.08.2026): соседнее согласие ловит «спросил и прочёл "
            "сырым» и слепо к «не спросил вовсе». Живьём мимо него читали L0 "
            "голым open живой путь A5 и ворота вложенности клеша (вторые "
            "починены 631a453); у 37 разборов из 81 L0 лежит только сжатым",
        gather=_gather_bare_snapshot_access,
        judge=_judge_bare_snapshot_access,
        break_it=_break_bare_snapshot_access,
    ),
    Agreement(
        name="отказ_несёт_свой_порог",
        claim="всякая величина с единицей в тексте отказа = порогу отказа",
        why="21.08: порог опущен 10000→100 мм², текст починен у одного "
            "носителя из двух; второй сто раз завышал порог автору",
        gather=_gather_refusals,
        judge=_judge_refusals,
        break_it=_break_refusals,
    ),
    Agreement(
        name="тело_объявляет_помощников",
        claim="C#-тело объявляет каждого __Помощника, которого зовёт, ГДЕ-ЛИБО "
              "в теле; область видимости НЕ моделируется (F-104, замер в "
              "докстроке судьи) — это не утверждение о сборке тела",
        why="20.08: __RouteSkips объявлен одним сборщиком из двух — судья "
            "построенного молчал 49 коммитов",
        gather=_gather_cs_bodies,
        judge=_judge_cs_bodies,
        break_it=_break_cs_bodies,
    ),
    Agreement(
        name="кто_спрашивает_про_сжатие_тот_через_него_и_читает",
        claim="функция, зовящая snapshot_file_exists, не читает ТОТ ЖЕ путь голым open",
        why="19–21.08: две полки прикрывали дефекты друг друга; на сыром "
            "корпусе обе половины врали согласованно и молчали",
        gather=_gather_snapshot_readers,
        judge=_judge_snapshot_readers,
        break_it=_break_snapshot_readers,
    ),
    Agreement(
        name="два_классификатора_одной_прозы",
        claim="classify_bridge_error и classify_execution_error дают один код",
        why="21.08: расхождение позволяло сказать «твой код выполнился» о "
            "коде, который не начинался",
        gather=_gather_classifiers,
        judge=_judge_classifiers,
        break_it=_break_classifiers,
    ),
    Agreement(
        name="близнец_компилятора_несёт_диспозицию",
        claim="константа-близнец в kir разобрана: одна величина или "
              "однофамильцы; «одна величина» обязана совпадать значением",
        why="21.08: MIN_EXTENT_MM скопирован в съёмщик и держал 55 форм",
        gather=_gather_twins,
        judge=_judge_twins,
        break_it=_break_twins,
    ),
    Agreement(
        name="константа_несёт_свою_совокупность",
        claim="константа, ставящая границу параметру реестра, разобрана: на "
              "чём мерена и чем ей позволено распоряжаться",
        why="21.08: четыре «предела языка» из девяти оказались правилом одной "
            "совокупности, приложенным к другой",
        gather=governed_bounds,
        judge=_judge_scope,
        break_it=_break_scope,
    ),
    Agreement(
        name="новый_род_получает_строку_во_всех_переписях",
        claim="всякий род spec.PARAM_KINDS имеет строку в каждой переписи, "
              "обещавшей полноту (формы · выразимость · плюральность)",
        why="21.08: четыре волны подряд заводили род и не заполняли переписи; "
            "solid_parts (20.08) простоял без строки двое суток в ТРЁХ сразу",
        gather=_gather_kind_rows,
        judge=_judge_kind_rows,
        break_it=_break_kind_rows,
    ),
    Agreement(
        name="контракт_не_врёт_про_чтение",
        claim="член API, названный обратным контрактом, не может ВЫЗЫВАТЬСЯ "
              "захватом без разобранной строки: иначе запись врёт про чтение",
        why="21–22.08: три записи подряд объявляли непрочитанным то, что "
            "читается. join_elements — через 16 минут после ввода чтения, той "
            "же сессией; create_stairs_run родился протухшим на 28 суток",
        gather=_gather_capture_claims,
        judge=_judge_capture_claims,
        break_it=_break_capture_claims,
    ),
)


#: 🔴 THE ROAD GUARD IS A SEPARATE CONSTANT, NOT A LINE IN `AGREEMENTS`. An
#: agreement guarding the tuple from inside the tuple is switched off by the
#: very same move it was set up against. Here the name stands in EXECUTABLE
#: code (`_registry_roster`), and its disappearance is seen by the
#: additive-edit gate.
REGISTRY_ROAD: Agreement = Agreement(
    name="построенное_тело_доезжает_до_реестра",
    claim="всякое тело согласия, построенное в этом модуле, стоит в реестре "
          "либо названо исключением с доводом",
    why="E-49 (30.08.2026): все три проверки реестра ОБХОДЯТ кортеж, поэтому "
        "согласие, изъятое из кортежа, не краснело нигде. Доказано мутацией "
        "на живом дереве: вырезана запись состав_подачи_лифту_полон, три её "
        "тела оставлены на месте — «согласий 9 · держатся все: True · "
        "31 passed, EXIT=0». Десятая форма: контроль сторожит СОСТАВ, а "
        "дефект живёт на ДОРОГЕ",
    gather=_gather_registry_road,
    judge=_judge_registry_road,
    break_it=_break_registry_road,
)


#: Agreements that are NAMED AND NOT WIRED IN. An empty cell in the registry
#: means "nobody is guarding this", and staying silent about it is worse
#: than admitting it.
NAMED_BUT_NOT_BUILT: tuple[tuple[str, str], ...] = (
    ("фикстура_против_эмиттера",
     "фикстуры паритета эмиссии обязаны пересобираться из живого эмиттера; "
     "21.08 они разошлись форматом и держали 3 красных двое суток. Не "
     "заведено: генератор фикстур ходит в службу, материал не собрать "
     "без Ревита"),
    ("починка_у_оригинала_а_не_у_копий",
     "правка, сделанная у N копий приёма, обязана быть у оригинала; 21.08 "
     "префикс create_stairs починен у копий и не у оригинала. Не заведено: "
     "«копия приёма» механически не опознаётся — нужна мера подобия тел, "
     "а не текста"),
    ("род_параметра_живёт_в_одном_месте",
     "ParamSpec.default рода str мёртв в валидации и живёт копией в "
     "эмиссии. Не заведено: сверка требует прогнать ВСЮ эмиссию, а она "
     "просит службу; правильный ход — убить копию, а не сторожить обе"),
)
