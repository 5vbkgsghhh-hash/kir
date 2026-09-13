"""Translation-validation certificate for the KIR authoring emitter (wave 2).

The emitter (`authoring.py`) already carries, per op, BOTH halves of a
refinement witness — they were just never collected into a checkable
certificate:

1. a **materializing Revit API call** in the ``create`` block
   (``Wall.Create``, ``Pipe.Create``, ``NewFamilyInstance``, ...) guarded by a
   typed ``__Refuse`` on a null / failed return (materialize-or-refuse; no
   silent wrong result), and
2. a **runtime postcondition witness** in the ``post`` block: one
   ``__post.Add("<oid>: ...")`` per invariant the op's ``OpSpec.post`` promises
   (endpoint geometry, level/host topology, parameter values, flip states,
   MEPSystem membership, ...), which ``emit_program`` gates with
   ``if (__post.Count > 0) { RollBack | report }``.

This module turns "a runtime witness exists" into a **statically checkable,
pre-Revit guarantee** that, for every promised postcondition, the witness was
actually emitted (not forgotten), and that the materializer is the specific
API that implements the op (not a stub).  It is the two-part structure of a
refinement proof: **safety** (right API or typed refusal) + **coverage
liveness** (every promised observable is checked).

The check is STATIC — no Revit, no compile — parsing the very
``(decl, create, post, readback)`` tuple the emitter returns, with the same
string/comment-stripping tokenizer the emitter scope contract already uses
(`test_emitter_scope_contract`).  Witnesses are matched by STRUCTURAL C#
markers (``.Location as LocationCurve``, ``WALL_BASE_CONSTRAINT``,
``.Mirrored != ``, ``RBS_PIPE_DIAMETER_PARAM``), never by the Russian message
text (which the tokenizer strips) — so renaming a message cannot fool the
certificate, while deleting the check itself breaks it.

Design, forks and rationale: ``TRANSLATION_VALIDATION_SPEC.md`` at the worktree
root.  Headlines:

* We prove refinement of the op's POSTCONDITIONS (its only observable
  contract, since the semantics live in Revit), not SMT-equivalence of the
  C# AST.
* ``REFINEMENT`` is the machine form of the prose ``OpSpec.post``;
  ``audit_registry_coverage`` enforces a biection so the table cannot silently
  drift from the registry (a new promised clause with no obligation is a hard
  fail).
* ``authoring.py`` is untouched — the certificate OBSERVES emission and never
  steers it.  Since 09.08.2026 it is no longer observation-only at the
  PIPELINE level: ``serving._handle_revit_ir_inner`` certifies the compiled
  write between compilation and the first effect (see
  :func:`certificate_mode`).  ``certificate_enabled()`` is still default OFF,
  so an unset flag leaves that path byte-identical.

Fail-closed: an unproven refinement or a registry/table mismatch raises a typed
:class:`CertificateError` — never a silent "proven".

09.08.2026 — ВАКУУМНЫЙ СВИДЕТЕЛЬ.  Наличие ключа обязательства доказывало, что
строка ``__post.Add`` СУЩЕСТВУЕТ, и молчало о том, ДОСТИЖИМА ли она: мутация
``if (false) __post.Add("never")`` оставляла стену `proven`.  Теперь сертификат
разбирает ОХРАНУ каждого вердикта и отказывает :class:`VacuousWitnessError`,
когда `__post.Add` доказуемо мёртв.  Анализ ЧАСТИЧЕН по построению (достижимость
неразрешима), и его границы перечислены поимённо у :func:`analyze_witness_cs` —
читать ДО того, как сослаться на него как на гарантию.
"""
from __future__ import annotations

import os
from kir import env  # noqa: E402  (a submodule with no dependencies — creates no cycle)
import re
from dataclasses import dataclass, field
from typing import Callable

from kir import spec
from kir.authoring import _EMITTERS, emit_stairs_program
from kir.emit_model import BarePost
from kir.emit_core import (program_tail_writes,
                           render_tail_adjusted_post,
                           restage_for_program_tail)


# ---------------------------------------------------------------------------
# Typed failures (fail-closed)
# ---------------------------------------------------------------------------


class CertificateError(ValueError):
    """Base for every typed translation-certificate failure."""


class UnprovenRefinementError(CertificateError):
    """An emitted op does not discharge every required refinement obligation."""


class CertificateSchemaError(CertificateError):
    """The registry promises a postcondition the obligation table cannot prove,
    or the table references a clause the registry never promises."""


class VacuousWitnessError(UnprovenRefinementError):
    """A witness whose ``__post.Add`` CANNOT execute on any run.

    A check that cannot fail is worse than none at all: from the outside it
    is indistinguishable from a real one, and it discharges the
    certificate's obligation.
    """


# ---------------------------------------------------------------------------
# Flag (inertness contract) + WHAT A FAILED CERTIFICATE DOES
# ---------------------------------------------------------------------------
#
# ONE FLAG, THREE STATES.  "Enabled" and "refuses" are different decisions,
# and folding them into a boolean would take away the operator's only safe
# way to bring the instrument onto the live path: first WATCH, then FORBID.
#
#   unset / empty / 0 / off      → OFF     certification does not run at all
#   record                       → RECORD  we count it and put it in the receipt
#   1 / true / yes / on / refuse → REFUSE  an unproven program DOES NOT WRITE
#
# WHY REFUSE IS THE DEFAULT ONCE ENABLED.  This system's green path stands
# on four legs, and one of them is the compiler's internal witness. A
# witness whose `__post.Add` is provably dead makes that leg identically
# true: the program "passed postconditions" without checking anything.
# Letting such a record execute would mean issuing `ok:true` with no
# independent confirmation — the very state that is forbidden. So an
# enabled instrument REFUSES by default, and `record` is a deliberate,
# named compromise for observation.
#
# WHAT THIS DOES NOT DO.  No mode refuses where the INSTRUMENT IS SILENT:
# an op with no `OpRefinementSpec` (the registry outran the table) and any
# internal breakage of the certifier are an absence of measurement, not a
# finding. Refusing on their account would mean turning away a correctly
# built program over our own bookkeeping — the same class of defect as
# "acceptance broke on Cyrillic", which rolled back correct rooms for
# months. Such cases are RECORDED in the receipt under their own name and
# let through (the decision lives in ``serving._certify_translation``).

CERT_MODE_OFF = "off"
CERT_MODE_RECORD = "record"
CERT_MODE_REFUSE = "refuse"

#: Values that turn on certification (any mode except off).
_CERT_RECORD_VALUES = frozenset({"record", "observe"})
_CERT_REFUSE_VALUES = frozenset({"1", "true", "yes", "on", "refuse"})


def certificate_enabled() -> bool:
    """Whether certification runs at all; default OFF.

    The flag is read HERE literally (rather than through a shared helper),
    because ``tools/capability_map.py`` finds a gate's predicate by the pair
    "``def … -> bool:`` + the environment variable's name in its body", and
    breaking that pair would return a verdict of "in storage" for the flag —
    exactly the blindness this file cures today.
    """

    return env.get("KIR_TRANSLATION_CERT", "").strip().lower() in (
        _CERT_REFUSE_VALUES | _CERT_RECORD_VALUES)


def certificate_mode() -> str:
    """``off`` | ``record`` | ``refuse`` — WHAT a failed certificate does.

    Not a second flag but the second half of one: see the block above. Any
    string outside both sets leaves the instrument OFF — and
    :func:`certificate_enabled` reads it exactly the same way, so "enabled"
    and "refuses" can never come apart on any value (pinned by the test
    ``test_enabled_and_mode_can_never_disagree``).
    """

    raw = env.get("KIR_TRANSLATION_CERT", "").strip().lower()
    if raw in _CERT_RECORD_VALUES:
        return CERT_MODE_RECORD
    if raw in _CERT_REFUSE_VALUES:
        return CERT_MODE_REFUSE
    return CERT_MODE_OFF


# ---------------------------------------------------------------------------
# C# tokenizer
# ---------------------------------------------------------------------------

def _code(text: str) -> str:
    """Strip C# strings, chars, and both comment forms; leave only code.

    A witness marker is searched in this stripped code, never inside a message
    string, so a renamed message can never fabricate (or hide) a proof.

    This must be a state machine, not two regex substitutions: C# has block
    comments, verbatim strings, escaped quotes, and comment-looking text inside
    literals.  In particular ``/* Wall.Create */`` used to satisfy the
    materializer proof even though it compiles to no call at all (F30).
    """

    out: list[str] = []
    i = 0
    size = len(text)
    line_ends = "\r\n\x85\u2028\u2029"
    while i < size:
        # Line comment (including every C# newline character).
        if text.startswith("//", i):
            i += 2
            while i < size and text[i] not in line_ends:
                i += 1
            out.append(" ")
            continue

        # Block comments are not nestable in C#.  Unterminated means the rest
        # is comment; dropping it is the certificate's fail-closed choice.
        if text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = size if end < 0 else end + 2
            out.append(" ")
            continue

        # Verbatim string prefixes: @"...", $@"...", @$"...".  Generated
        # KIR does not rely on interpolation code for proof markers, so the
        # entire literal is deliberately non-code for certification.
        prefix_len = 0
        if text.startswith('$@"', i) or text.startswith('@$"', i):
            prefix_len = 3
        elif text.startswith('@"', i):
            prefix_len = 2
        if prefix_len:
            i += prefix_len
            while i < size:
                if text[i] == '"':
                    if i + 1 < size and text[i + 1] == '"':
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            out.append('""')
            continue

        # Ordinary/interpolated strings.  Backslash escapes keep the next
        # character inside the literal.  This is sufficient for the C# 7.3
        # dialect emitted here; proof-bearing code is never inside a string.
        quote_len = 0
        if text.startswith('$"', i):
            quote_len = 2
        elif text[i] == '"':
            quote_len = 1
        if quote_len:
            i += quote_len
            while i < size:
                if text[i] == "\\" and i + 1 < size:
                    i += 2
                    continue
                char = text[i]
                i += 1
                if char == '"':
                    break
            out.append('""')
            continue

        # Character literals may contain escaped quote/comment characters.
        if text[i] == "'":
            i += 1
            while i < size:
                if text[i] == "\\" and i + 1 < size:
                    i += 2
                    continue
                char = text[i]
                i += 1
                if char == "'":
                    break
            out.append("''")
            continue

        out.append(text[i])
        i += 1
    return "".join(out)


# ---------------------------------------------------------------------------
# VACUOUS WITNESS (09.08.2026): a check that cannot fire
# ---------------------------------------------------------------------------
#
# THE HOLE CLOSED HERE.  `WitnessCheck` requires the PRESENCE of
# `__post.Add` in the verdict, and the certificate requires the PRESENCE of
# an obligation key.  Neither of the two looked at the CONDITION under
# which that `__post.Add` stands.  The audit mutation:
#
#     if (false) __post.Add("never");
#
# left `certify_op(wall, "2026").proven == True` — "a line capable of
# adding a violation exists" was taken for "the check is capable of
# detecting the violation".  This is exactly the class the whole module is
# written against: A CHECK THAT CANNOT FAIL IS WORSE THAN NONE AT ALL.
#
# ───────────────────────────────────────────────────────────────────────────
# THIS INSTRUMENT'S BOUNDARY, STATED HONESTLY — READ BEFORE CITING IT AS A
# GUARANTEE.
#
# Reachability is UNDECIDABLE in general, and it is not decided here. This
# analysis answers EXACTLY ONE question: "can I PROVE that this
# `__post.Add` is dead?" A "no" here is NOT proof that the witness is
# alive. The instrument can only ADD refusals, and never confirm
# liveness. A reader who takes it for a total guarantee will repeat the
# very defect it was written against (the house's law: an instrument
# covering PART of the range is more dangerous than none at all — see the
# memory `instrument-covering-part-of-range-2026-08-03`).
#
# WHAT IS DETECTED (every class verified by mutation in
# tests/test_witness_vacuity.py):
#
#   1. VACUITY_CONSTANT_FALSE — the guard evaluates to a constant
#      incompatible with the branch: `if (false)`, `while (false)`,
#      `if (0 == 1)`, `if (1 > 2)`, `for (...; false; ...)`,
#      `if (false && X)`, `if (!true)`, and also the `else` branch of
#      `if (true)`.
#      Boolean algebra is evaluated over &&/||/!/parentheses; numeric
#      comparisons over literals, `Math.Abs(...)`, and subtraction.
#   2. VACUITY_SELF_COMPARISON — the guard compares an expression WITH
#      ITSELF in a false direction: `x != x`, `a < a`,
#      `Math.Abs(MM(x) - MM(x)) > 5.0`.
#   3. VACUITY_UNREACHABLE — `__post.Add` sits AFTER an unconditional
#      `return`/`throw`/`break`/`continue`/`goto` in the same statement
#      list.
#
# WHAT IS PROVABLY NOT DETECTED (and this is not a to-do list for
# tomorrow, but the limit of static analysis; every point is named so the
# next reader does not mistake silence for cleanliness):
#
#   * VARIABLE VALUES.  `bool __never = false; if (__never) __post.Add(..)`
#     — constant propagation is not done at all. The same vacuum, invisible
#     to this instrument.
#   * DATA-DEPENDENT UNREACHABILITY.  A guard like `if (__count > 1000000)`
#     or `if (__el == null)` where `__el` was just checked against null:
#     the condition is syntactically alive, semantically it is not. That is
#     already verification, not text parsing.
#   * EMPTY ITERATIONS.  `foreach (var x in <empty collection>)` — the
#     number of iterations cannot be derived from the text; `foreach`
#     gives ZERO information about the guard, and the body is treated as
#     reachable.
#   * PARTIAL GUTTING BY MEANING.  A witness with two `__post.Add` calls
#     (a null guard + a tolerance check), where only the null guard is
#     left alive and the check has been weakened to `> 1e30`, passes here:
#     1e30 is a live number, and "the tolerance is too wide" is a question
#     for the tolerance's provenance (law 3 in emit_model), not for
#     reachability. THIS IS WHY the rule is deliberately strict: a finding
#     is EVERY provably dead `__post.Add`, not only the case "all of them
#     are dead" — otherwise gutting just one of two branches would pass
#     silently.
#   * SIDE EFFECTS IN THE GUARD.  The identity `x == x` is treated as an
#     identity OF VALUES by textual match of the operands. A call that
#     changes state between the two reads would refute this; in the
#     dialect emitted here the guard consists of reads and pure helpers
#     (`MM`, `U`, `P`), and operands with assignment/`++`/`--`/`new` are
#     explicitly excluded from the identity check.
#   * AN ALWAYS-TRUE guard (`if (x == x) __post.Add(..)`) is a DIFFERENT
#     defect: such a check fails ALWAYS and LOUDLY, that is, it does not
#     belong to the "silently wrong" class. It is not a finding here (but
#     the instrument will see a dead `else` branch beneath it).
#   * SELF-INSUFFICIENT TEXT.  The `create_stairs` template — a method
#     body plus class declarations, deliberately NOT balanced by brackets
#     (the frame is supplied by `wrap_user_code`). Such text is parsed IN
#     PIECES, and the fact of incompleteness travels as a separate field
#     (`OpCertificate.vacuity_partial`): "read whole" and "read in pieces"
#     are different facts, and the second must not be read as proof of
#     cleanliness.
#
# THE DIRECTION OF REFUSAL.  The instrument is a DETECTOR, not proof of
# correctness, so on unparsed text it stays silent rather than accusing:
# otherwise it would refuse the whole corpus and get turned off, which is
# worse than a narrow truth.
#
# MEASURED 09.08.2026 (corpus test_tolerance_provenance._full_instances,
# 940 op instances = all 37 writing ops of the registry × 6 Revit
# versions):
#   * vacuum findings — 0;
#   * the walk reached 3748 of 3748 `__post.Add` calls on the model path
#     (2618 witnesses), and 5 of 5 in the create_stairs template, parsed in
#     pieces.
# The second row is not decoration: without it, "zero findings" and "the
# walk silently missed it" are indistinguishable. Both numbers are held by
# the ratchet in tests/test_witness_vacuity.py (`witness_site_census`), so
# they cannot go stale unnoticed.

#: Named vacuum classes (typed diagnostics, not eyeballed strings).
VACUITY_CONSTANT_FALSE = "constant_false_guard"
VACUITY_SELF_COMPARISON = "self_comparison_guard"
VACUITY_UNREACHABLE = "unreachable_verdict"
VACUITY_KINDS = frozenset({
    VACUITY_CONSTANT_FALSE, VACUITY_SELF_COMPARISON, VACUITY_UNREACHABLE,
})

_VERDICT_CALL = "__post.Add"
_TERMINATOR_RE = re.compile(r"^(?:return|throw|break|continue|goto)\b")
_HEADER_RE = re.compile(r"^(if|while|for|foreach|switch|lock|using|fixed)\s*\(")
_NUMBER_RE = re.compile(
    r"^[+-]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?[fFdDmM]?$")
_ASSIGNMENT_RE = re.compile(r"(?<![=!<>+\-*/%&|^])=(?!=)")
_RELOPS = ("==", "!=", "<=", ">=", "<", ">")
_NOT_RELOPS = ("=>", "<<", ">>", "->")
_OPENERS = "([{"
_CLOSERS = ")]}"


@dataclass(frozen=True, slots=True)
class VacuityFinding:
    """One provably dead ``__post.Add`` — an op-bound typed finding."""

    op: str
    obligation_key: str | None
    kind: str
    guard: str
    excerpt: str

    def describe(self) -> str:
        where = (f"witness {self.obligation_key!r}"
                 if self.obligation_key is not None else "post block")
        return (
            f"{self.op}: {where} — вакуумный свидетель [{self.kind}]: "
            f"{_VERDICT_CALL} не может выполниться, охрана {self.guard!r} "
            f"(фрагмент: {self.excerpt!r}); проверка, которая не может "
            "упасть, хуже отсутствующей")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


_BRACKET_PAIRS = {")": "(", "]": "[", "}": "{"}


def _balanced_segments(code: str) -> tuple[list[str], bool]:
    """Cut ``code`` into maximal bracket-balanced pieces.

    NOT every emitted fragment is a self-contained statement list:
    ``create_stairs`` owns a whole-program TEMPLATE — a method body followed by
    nested class declarations — deliberately unbalanced at both ends, because
    ``wrap_user_code`` supplies the frame (its own docstring says so).
    Declining that blob wholesale would leave the one string-path op with ZERO
    vacuity coverage and call it "unparseable", which is the silence this
    module exists to prevent.

    So a bracket with no partner HERE ends the current piece and opens the
    next, and the body of an unclosed opener is analysed as its own top-level
    block (with NO inherited guards — the conservative direction: fewer
    findings, never invented ones).  The second return value says whether
    anything had to be cut, so "fully parsed" and "parsed in pieces" stay
    different facts.
    """

    out: list[str] = []
    trimmed = [False]
    _cut(code, out, trimmed)
    return [piece for piece in out if piece.strip()], trimmed[0]


def _cut(code: str, out: list[str], trimmed: list[bool]) -> None:
    stack: list[tuple[str, int]] = []
    start = 0
    for i, ch in enumerate(code):
        if ch in _OPENERS:
            stack.append((ch, i))
        elif ch in _CLOSERS:
            if stack and stack[-1][0] == _BRACKET_PAIRS[ch]:
                stack.pop()
            else:
                out.append(code[start:i])
                start = i + 1
                stack = []
                trimmed[0] = True
    if stack:
        trimmed[0] = True
        at = stack[0][1]
        out.append(code[start:at])
        _cut(code[at + 1:], out, trimmed)
    else:
        out.append(code[start:])


def _matching(text: str, start: int) -> int:
    """Index of the bracket matching the opener at ``start`` (-1 if none)."""

    opener = text[start]
    closer = {"(": ")", "[": "]", "{": "}"}[opener]
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return i
    return -1


def _split_top(expr: str, token: str) -> list[str]:
    """Split ``expr`` on ``token`` occurrences at bracket depth 0."""

    parts: list[str] = []
    depth = last = i = 0
    size = len(expr)
    while i < size:
        ch = expr[i]
        if ch in _OPENERS:
            depth += 1
        elif ch in _CLOSERS:
            depth -= 1
        elif depth == 0 and expr.startswith(token, i):
            parts.append(expr[last:i])
            i += len(token)
            last = i
            continue
        i += 1
    parts.append(expr[last:])
    return parts


def _word_at(text: str, index: int, word: str) -> bool:
    if not text.startswith(word, index):
        return False
    before = text[index - 1] if index else " "
    after = text[index + len(word):index + len(word) + 1] or " "
    return not (before.isalnum() or before == "_") and \
        not (after.isalnum() or after == "_")


def _next_word(text: str, index: int) -> str:
    while index < len(text) and text[index].isspace():
        index += 1
    match = re.match(r"[A-Za-z_]+", text[index:])
    return match.group(0) if match else ""


def _is_pure(text: str) -> bool:
    """An operand whose textual identity can be treated as value identity.

    The restriction is NAMED: reads and pure helpers — yes; assignment,
    increment, and construction — no.
    """

    return bool(text) and not (
        _ASSIGNMENT_RE.search(text) or "++" in text or "--" in text
        or re.search(r"\bnew\b", text))


def _split_relational(expr: str) -> tuple[str, str, str] | None:
    """First depth-0 relational operator, as (lhs, op, rhs)."""

    depth = i = 0
    size = len(expr)
    while i < size:
        ch = expr[i]
        if ch in _OPENERS:
            depth += 1
            i += 1
            continue
        if ch in _CLOSERS:
            depth -= 1
            i += 1
            continue
        if depth == 0:
            if any(expr.startswith(bad, i) for bad in _NOT_RELOPS):
                i += 2
                continue
            for op in _RELOPS:
                if expr.startswith(op, i):
                    return expr[:i], op, expr[i + len(op):]
        i += 1
    return None


def _split_additive(expr: str) -> tuple[str, str, str] | None:
    """Last depth-0 ``+``/``-`` that is a binary operator, as (lhs, op, rhs)."""

    depth = i = 0
    size = len(expr)
    found: tuple[int, str] | None = None
    while i < size:
        ch = expr[i]
        if ch in _OPENERS:
            depth += 1
        elif ch in _CLOSERS:
            depth -= 1
        elif depth == 0 and ch in "+-":
            prev = expr[:i].rstrip()
            nxt = expr[i + 1:i + 2]
            unary = not prev or prev[-1] in "(+-*/%<>=!&|,^~"
            compound = nxt in ("+", "-", "=", ">")
            exponent = bool(re.search(r"[\d.][eE]$", prev))
            if not (unary or compound or exponent):
                found = (i, ch)
        i += 1
    if found is None:
        return None
    at, op = found
    return expr[:at], op, expr[at + 1:]


def _const_num(expr: str) -> tuple[float | None, bool]:
    """Constant value of a numeric C# expression + whether SELF-IDENTITY was used.

    The second flag is what keeps the diagnostic honest: ``Math.Abs(MM(x) -
    MM(x)) > 5.0`` folds to ``0.0 > 5.0``, and calling that "a comparison of
    literals" would hide the actual defect — the witness compares a value to
    ITSELF.  The reason travels with the number.
    """

    expr = expr.strip()
    while expr.startswith("(") and _matching(expr, 0) == len(expr) - 1:
        expr = expr[1:-1].strip()
    if not expr:
        return None, False
    if _NUMBER_RE.match(expr):
        return float(expr.rstrip("fFdDmM")), False
    if expr.startswith("Math.Abs"):
        open_at = expr.find("(")
        if open_at > 0 and _matching(expr, open_at) == len(expr) - 1:
            inner, self_used = _const_num(expr[open_at + 1:-1])
            return (None if inner is None else abs(inner)), self_used
    additive = _split_additive(expr)
    if additive is not None:
        lhs, op, rhs = additive
        left, right = _norm(lhs), _norm(rhs)
        if op == "-" and left and left == right and _is_pure(left):
            return 0.0, True
        a, a_self = _const_num(lhs)
        b, b_self = _const_num(rhs)
        if a is not None and b is not None:
            return (a - b if op == "-" else a + b), (a_self or b_self)
    return None, False


def _const_bool(expr: str) -> tuple[bool | None, str]:
    """Constant value of a boolean C# expression + WHY (for the diagnostic).

    Returns ``(None, "")`` for anything not statically decidable — the honest
    default, since undecided is the overwhelming majority.
    """

    expr = expr.strip()
    while expr.startswith("(") and _matching(expr, 0) == len(expr) - 1:
        expr = expr[1:-1].strip()
    if not expr:
        return None, ""

    ors = _split_top(expr, "||")
    if len(ors) > 1:
        values = [_const_bool(part) for part in ors]
        for value, why in values:
            if value is True:
                return True, why
        if all(value is False for value, _ in values):
            return False, next((w for _, w in values if w), "literal")
        return None, ""

    ands = _split_top(expr, "&&")
    if len(ands) > 1:
        values = [_const_bool(part) for part in ands]
        for value, why in values:
            if value is False:
                return False, why
        if all(value is True for value, _ in values):
            return True, next((w for _, w in values if w), "literal")
        return None, ""

    if expr.startswith("!") and not expr.startswith("!="):
        value, why = _const_bool(expr[1:])
        return (None if value is None else (not value)), why

    if expr == "true":
        return True, "literal"
    if expr == "false":
        return False, "literal"

    relational = _split_relational(expr)
    if relational is not None:
        lhs, op, rhs = relational
        left, right = _norm(lhs), _norm(rhs)
        if left and left == right and _is_pure(left):
            return op in ("==", "<=", ">="), "self"
        a, a_self = _const_num(lhs)
        b, b_self = _const_num(rhs)
        if a is not None and b is not None:
            decided = {
                "==": a == b, "!=": a != b, "<=": a <= b,
                ">=": a >= b, "<": a < b, ">": a > b,
            }[op]
            return decided, ("self" if (a_self or b_self) else "numeric")
    return None, ""


def _guard_label(condition: str, branch: bool, keyword: str) -> str:
    """The guard as the READER will see it — the construct it really came from.

    Rendering a ``while (false)`` as ``if (false)`` would send whoever reads
    the refusal looking for an ``if`` that is not there.
    """

    shown = _norm(condition)
    if keyword == "for":
        return f"for (...; {shown}; ...)"
    if keyword == "while":
        return f"while ({shown})"
    return f"if ({shown})" if branch else f"else of if ({shown})"


def _guard_verdict(
    guards: tuple[tuple[str, bool, str], ...],
) -> tuple[str, str] | None:
    """(kind, guard-text) if some enclosing guard PROVABLY excludes this branch."""

    for condition, branch, keyword in guards:
        value, why = _const_bool(condition)
        if value is None or value == branch:
            continue
        kind = (VACUITY_SELF_COMPARISON if why == "self"
                else VACUITY_CONSTANT_FALSE)
        return kind, _guard_label(condition, branch, keyword)
    return None


def _excerpt(text: str, at: int) -> str:
    return _norm(text[at:at + 48])


def _split_else(rest: str) -> tuple[str, str | None]:
    depth_p = depth_b = i = 0
    size = len(rest)
    while i < size:
        ch = rest[i]
        if ch in "([":
            depth_p += 1
        elif ch in ")]":
            depth_p -= 1
        elif ch == "{":
            depth_b += 1
        elif ch == "}":
            depth_b -= 1
        elif depth_p == 0 and depth_b == 0 and _word_at(rest, i, "else"):
            return rest[:i], rest[i + 4:]
        i += 1
    return rest, None


def _unwrap(part: str) -> str:
    part = part.strip()
    if part.startswith("{"):
        close = _matching(part, 0)
        if close > 0:
            return part[1:close]
    return part


def _statements(block: str) -> list[str]:
    """Split a C# statement list into top-level statements.

    A brace group is opaque and belongs to the statement that opened it;
    ``else``/``catch``/``finally`` continue the statement before them rather
    than starting a new one.
    """

    out: list[str] = []
    depth_p = depth_b = start = i = 0
    size = len(block)
    while i < size:
        ch = block[i]
        if ch in "([":
            depth_p += 1
        elif ch in ")]":
            depth_p -= 1
        elif ch == "{":
            depth_b += 1
        elif ch == "}":
            depth_b -= 1
            if depth_b == 0 and depth_p == 0 and \
                    _next_word(block, i + 1) not in ("else", "catch", "finally"):
                out.append(block[start:i + 1])
                start = i + 1
        elif ch == ";" and depth_b == 0 and depth_p == 0:
            if _next_word(block, i + 1) != "else":
                out.append(block[start:i + 1])
                start = i + 1
        i += 1
    out.append(block[start:])
    return [stmt for stmt in out if stmt.strip()]


@dataclass
class _Scan:
    """Mutable accumulator of one walk.

    ``visited`` exists to GUARD THE GUARD: a walker that silently skips a
    branch would report zero findings and look exactly like a clean corpus.
    Comparing visited sites against the sites present in the text turns that
    indistinguishable pair into a measurement (`witness_site_census`).
    """

    findings: list[tuple[str, str, str]] = field(default_factory=list)
    visited: int = 0


def _scan_block(
    block: str, guards: tuple[tuple[str, bool, str], ...], scan: "_Scan",
) -> None:
    terminated_by: str | None = None
    for statement in _statements(block):
        body = statement.strip()
        if terminated_by is not None:
            for match in re.finditer(re.escape(_VERDICT_CALL), body):
                scan.visited += 1
                scan.findings.append((VACUITY_UNREACHABLE, terminated_by,
                                      _excerpt(body, match.start())))
            continue
        if _TERMINATOR_RE.match(body):
            terminated_by = _norm(body)[:60]
            continue
        header = _HEADER_RE.match(body)
        if header is not None:
            keyword = header.group(1)
            open_at = body.index("(")
            close_at = _matching(body, open_at)
            if close_at < 0:
                _scan_statement(body, guards, scan)
                continue
            condition = body[open_at + 1:close_at]
            rest = body[close_at + 1:]
            if keyword == "if":
                then_part, else_part = _split_else(rest)
                _scan_block(_unwrap(then_part),
                            guards + ((condition, True, "if"),), scan)
                if else_part is not None:
                    _scan_block(_unwrap(else_part),
                                guards + ((condition, False, "if"),), scan)
            elif keyword == "while":
                _scan_block(_unwrap(rest),
                            guards + ((condition, True, "while"),), scan)
            elif keyword == "for":
                clauses = _split_top(condition, ";")
                middle = clauses[1] if len(clauses) == 3 else ""
                inner = ((guards + ((middle, True, "for"),))
                         if middle.strip() else guards)
                _scan_block(_unwrap(rest), inner, scan)
            else:
                # foreach/switch/lock/using/fixed carry NO static guard: the
                # body is treated as reachable (named limit above).
                _scan_block(_unwrap(rest), guards, scan)
            continue
        _scan_statement(body, guards, scan)


def _scan_statement(
    body: str, guards: tuple[tuple[str, bool, str], ...], scan: "_Scan",
) -> None:
    """A statement that is not a recognised header: recurse into its brace
    groups (``try``/``catch``/bare block/``do``) and judge the rest inline."""

    plain: list[str] = []
    i = 0
    size = len(body)
    while i < size:
        if body[i] == "{":
            close = _matching(body, i)
            if close < 0:
                plain.append(body[i:])
                break
            _scan_block(body[i + 1:close], guards, scan)
            i = close + 1
            continue
        plain.append(body[i])
        i += 1
    text = "".join(plain)
    verdict = _guard_verdict(guards)
    for match in re.finditer(re.escape(_VERDICT_CALL), text):
        scan.visited += 1
        if verdict is not None:
            kind, shown = verdict
            scan.findings.append((kind, shown, _excerpt(text, match.start())))


def analyze_witness_cs(code: str) -> tuple[tuple[tuple[str, str, str], ...], bool]:
    """Provably-dead ``__post.Add`` sites in ONE witness fragment.

    Returns ``(findings, partial)``.  ``partial`` says the fragment's brackets
    did not balance on their own, so it was analysed in pieces and the
    coverage is not the whole text — a THIRD state next to "clean" and
    "found something", kept separate so a reader cannot mistake a partial
    read for a proof of cleanliness.

    ``code`` must already be comment/string-stripped by :func:`_code`.
    """

    scan, partial = _walk(code)
    return tuple(scan.findings), partial


def _walk(code: str) -> tuple[_Scan, bool]:
    pieces, partial = _balanced_segments(code)
    scan = _Scan()
    for piece in pieces:
        _scan_block(piece, (), scan)
    return scan, partial


def witness_site_census(code: str) -> tuple[int, int]:
    """(verdict sites the WALK reached, verdict sites the TEXT contains).

    A walker that silently skipped a branch would report zero findings and be
    indistinguishable from a clean corpus.  These two numbers make the
    difference measurable, and the ratchet in
    ``tests/test_witness_vacuity.py`` requires them equal over every emitted
    witness of every registered op.
    """

    scan, _partial = _walk(code)
    return scan.visited, len(re.findall(re.escape(_VERDICT_CALL), code))


def witness_vacuity(
    op_name: str, checks: "list | None", post_code: str,
) -> tuple[tuple[VacuityFinding, ...], tuple[str, ...]]:
    """Vacuity findings for an op's post block + the fragments read only in part.

    Model path: judged per :class:`WitnessCheck`, so the finding is bound to
    the obligation KEY.  String path (``create_stairs``): judged over the whole
    post blob, key ``None``.
    """

    findings: list[VacuityFinding] = []
    partial: list[str] = []
    if checks is None:
        sites, was_partial = analyze_witness_cs(post_code)
        if was_partial:
            partial.append("<post>")
        findings.extend(
            VacuityFinding(op_name, None, kind, guard, excerpt)
            for kind, guard, excerpt in sites)
        return tuple(findings), tuple(partial)
    for check in checks:
        sites, was_partial = analyze_witness_cs(_code(check.render()))
        if was_partial:
            partial.append(check.obligation_key)
        findings.extend(
            VacuityFinding(op_name, check.obligation_key, kind, guard, excerpt)
            for kind, guard, excerpt in sites)
    return tuple(findings), tuple(partial)


# ---------------------------------------------------------------------------
# Certificate data model
# ---------------------------------------------------------------------------

# Obligation kinds — the observable classes an op postcondition can promise.
KIND_MATERIALIZE = "materialize"
KIND_GEOMETRY = "geometry"
KIND_TOPOLOGY = "topology"
KIND_PARAMETER = "parameter"
KIND_SEMANTIC = "semantic"
KIND_IDENTITY = "identity"
_KINDS = frozenset({
    KIND_MATERIALIZE, KIND_GEOMETRY, KIND_TOPOLOGY, KIND_PARAMETER,
    KIND_SEMANTIC, KIND_IDENTITY,
})

# Which emitted block an obligation's witness must live in.
BLOCK_CREATE = "create"
BLOCK_POST = "post"
BLOCK_OPERATION = "operation"


@dataclass(frozen=True, slots=True)
class Obligation:
    """One proof obligation: a clause and the C# markers that discharge it."""

    clause: str                          # human-readable, aligned to OpSpec.post
    kind: str
    witness_markers: tuple[str, ...]     # ANY present in ``block`` discharges it
    block: str = BLOCK_POST
    param: str | None = None             # gating param for a conditional clause
    conditional: bool = False            # witness required ONLY when param present
    # height mismatch fix (30.07.2026): the mirror image of `conditional` —
    # witness required ONLY when `unless_param` is ABSENT.  create_wall's
    # height witness needs exactly this: WALL_USER_HEIGHT_PARAM stops being
    # authoritative (and the emitter stops witnessing it) the moment
    # top_level IS given, the opposite shape from every existing conditional
    # obligation (which all gate on their OWN param's presence).
    #
    # 10.08: CAN COEXIST with `conditional`/`param`, and then BOTH
    # conditions are required. The occasion is the tilted column
    # (`create_column` with `top_xy`): the emitter DELIBERATELY does not
    # witness its rotation, top anchor, and top offset for it, because the
    # axis sets the top entirely, and recording these parameters would
    # fight the geometry (the reason is recorded in `_emit_column`). The
    # obligations, however, were unconditional along this axis, and the
    # certificate declared UNPROVABLE something that this op variant never
    # has at all — under `KUKAI_IR_TRANSLATION_CERT=refuse` a live recording
    # of a tilted column would have refused with KIR-R001 for no reason at
    # all. The exact same defect was already fixed on 28.07 in
    # `place_family` ("placement along a level curve has none at all"), and
    # the fix back then was the same: make the obligation conditional.
    unless_param: str | None = None
    # 🔴 THIRD GATE: THE KIND OF VALUE INSIDE THE PARAMETER, NOT THE
    # PARAMETER'S PRESENCE (20.08.2026). The two gates above ask "is the
    # field present". There is an obligation whose provability is decided
    # by the field's CONTENTS: a contour's bounding box is provable as long
    # as the loop consists of lines and arcs, and UNPROVABLE the moment a
    # spline appears in it — Revit chooses the shape between the declared
    # points (measured live: a 279 mm gap against a 50 mm tolerance).
    #
    # WHY THIS IS NOT COSMETIC. Without the gate, a splined slab gets
    # `proven=False` with the reason «no witness check with key 'bbox'» —
    # that is, "we could not prove it" instead of "we deliberately make no
    # claim". That difference is exactly why named absences exist: an
    # inability and a waived claim both read as red the same way, and mean
    # different things.
    #
    # A `(parameter name, kind)` pair; there is currently one kind —
    # "spline". The next edge kind will go here too, and that is better
    # than a predicate for every case.
    unless_kind_in: tuple[str, str] | None = None
    # 🔴 MIRROR OF THE PREVIOUS FIELD (21.08.2026), AND WITHOUT IT THE
    # PROMISE WAS INEXPRESSIBLE. `unless_kind_in` can say "not required when
    # the kind is such-and-such"; there was NOTHING to say "required ONLY
    # when". The ceiling and the contour-based floor carry, in
    # `OpSpec.post`, the clause «every declared spline via-point lies ON the
    # built sketch curve», the witness is emitted — and the certificate
    # never asked it, because an obligation expressed the ordinary way would
    # have demanded a witness from a STRAIGHT contour too, where there is no
    # spline at all.
    #
    # Found by the mutation law L6 (`test_tolerance_provenance`): cutting
    # out the actual witness must drop `proven`, and here it did not. L6
    # itself stayed silent for a day — the file failed to build because of a
    # solo op with no sample, and a red for a known reason was hiding the
    # next one.
    when_kind_in: tuple[str, str] | None = None
    # 03.08: gate on a TRUTHY value, not mere key presence.  Needed for
    # requirements that arrive as a CONTAINER the grounder always writes:
    # `__slope_reqs__` is `{}` on every route without slope_min_pct, so plain
    # key-presence would demand a slope witness from every plain route.
    # Deliberately NOT the global rule for `conditional` — `mirrored=False`
    # IS a request, and the emitter witnesses it.
    param_truthy: bool = False
    # Wave A2: for ops migrated to the witness model the obligation matches a
    # WitnessCheck.obligation_key — a machine KEY, never a C# substring.  When
    # ``key`` is set the markers become optional (unused on the model path);
    # string-path ops keep requiring markers.
    key: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in _KINDS:
            raise CertificateSchemaError(f"unknown obligation kind {self.kind!r}")
        if self.block not in (BLOCK_CREATE, BLOCK_POST, BLOCK_OPERATION):
            raise CertificateSchemaError(f"unknown block {self.block!r}")
        if self.conditional and self.param is None:
            raise CertificateSchemaError(
                f"conditional obligation {self.clause!r} needs a gating param")
        if self.param_truthy and not self.conditional:
            raise CertificateSchemaError(
                f"obligation {self.clause!r}: param_truthy only refines a "
                "conditional gate")
        if (self.unless_param is not None
                and self.param is not None and not self.conditional):
            raise CertificateSchemaError(
                f"obligation {self.clause!r}: unless_param may join a "
                "CONDITIONAL gate (both must hold), never a bare param")
        if self.unless_param is not None and self.unless_param == self.param:
            raise CertificateSchemaError(
                f"obligation {self.clause!r}: unless_param equals param — "
                "the two gates would contradict and the witness could never "
                "be required")
        if not self.witness_markers and self.key is None:
            raise CertificateSchemaError(
                f"obligation {self.clause!r} has neither witness markers nor "
                "a model key")


@dataclass(frozen=True, slots=True)
class OpRefinementSpec:
    """The full refinement contract for one op, parallel to ``spec.OPS``."""

    op: str
    materializer: tuple[str, ...]        # ANY marker proves the create call
    obligations: tuple[Obligation, ...]
    refuse_on_null: bool = True
    # Wave A2: "model" = the emitter returns list[WitnessCheck]; obligations
    # discharge by obligation KEY (correctness by construction — a check
    # cannot exist without its __post.Add verdict).  "string" = legacy post
    # string: marker matching + the verdict-span rule.
    witness_source: str = "string"


@dataclass(frozen=True, slots=True)
class ClauseVerdict:
    clause: str
    kind: str
    required: bool
    discharged: bool
    matched_marker: str | None
    reason: str


@dataclass(frozen=True, slots=True)
class OpCertificate:
    op: str
    version: str
    materialized: bool
    refusal_guarded: bool
    clauses: tuple[ClauseVerdict, ...]
    #: Provably dead `__post.Add` entries of this op.  A non-empty tuple
    #: CANCELS provenness entirely — even if every obligation is "defused"
    #: by a key: a key proves the line's existence, not its reachability.
    vacuous: tuple[VacuityFinding, ...] = ()
    #: Witness keys whose text is NOT SELF-CONTAINED by bracket balance and
    #: was parsed IN PIECES (the create_stairs pattern).  Neither a finding
    #: nor cleanliness — a third state, named separately so that an
    #: incomplete parse does not read as proof of cleanliness.
    vacuity_partial: tuple[str, ...] = ()

    @property
    def proven(self) -> bool:
        return (
            self.materialized
            and self.refusal_guarded
            and not self.vacuous
            and all(v.discharged for v in self.clauses if v.required)
        )

    @property
    def gaps(self) -> tuple[str, ...]:
        holes: list[str] = []
        if not self.materialized:
            holes.append(f"{self.op}: no materializing API call emitted")
        if not self.refusal_guarded:
            holes.append(f"{self.op}: materialization not guarded by __Refuse")
        for verdict in self.clauses:
            if verdict.required and not verdict.discharged:
                holes.append(
                    f"{self.op}: unproven [{verdict.kind}] {verdict.clause} "
                    f"({verdict.reason})")
        holes.extend(finding.describe() for finding in self.vacuous)
        return tuple(holes)


@dataclass(frozen=True, slots=True)
class ProgramCertificate:
    version: str
    ops: tuple[OpCertificate, ...]

    @property
    def proven(self) -> bool:
        return all(cert.proven for cert in self.ops)

    @property
    def gaps(self) -> tuple[str, ...]:
        return tuple(gap for cert in self.ops for gap in cert.gaps)

    @property
    def vacuous(self) -> tuple[VacuityFinding, ...]:
        return tuple(f for cert in self.ops for f in cert.vacuous)


# ---------------------------------------------------------------------------
# The obligation table — machine form of every write op's OpSpec.post
# ---------------------------------------------------------------------------

# Shared witness marker groups (structural C#, NOT message text).
_ENDPOINTS = (".Location as LocationCurve",)           # _endpoint_check
_LEVEL_BIP = (
    "WALL_BASE_CONSTRAINT", "RBS_START_LEVEL_PARAM", "ROOF_BASE_LEVEL_PARAM",
    "FAMILY_BASE_LEVEL_PARAM", "FAMILY_LEVEL_PARAM", "SCHEDULE_LEVEL_PARAM",
    "LEVEL_PARAM", ".LevelId",                          # _level_check_expr / chain / room
)
_LOCATION_POINT = (".Location as LocationPoint",)
_BBOX = ("get_BoundingBox",)
_REFUSE = ("__Refuse",)


def _refinement_specs() -> dict[str, OpRefinementSpec]:
    ob = Obligation
    specs = [
        OpRefinementSpec(
            op="create_wall",
            materializer=("Wall.Create",),
            witness_source="model",
            obligations=(
                ob("wall exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("assigned type == resolved requested type at operation end (identity)",
                   KIND_IDENTITY, (), block=BLOCK_OPERATION, key="type_assignment"),
                ob("LocationCurve endpoints == p0/p1 (geometry)",
                   KIND_GEOMETRY, _ENDPOINTS, key="endpoints"),
                ob("base constraint == resolved level (topology)",
                   KIND_TOPOLOGY, ("WALL_BASE_CONSTRAINT",),
                   key="base_constraint"),
                # Measured on 29.07.2026 (two façade runs: 4 walls + 5
                # floors, then 16 walls — «height mismatch» on EVERY ONE).
                # height_mm carries the registry default (3000mm), and
                # validate() substitutes it into norm BEFORE the emitter for
                # ANY omitted wall — the emitter can no longer tell "3000
                # was explicitly requested" from "said nothing, because
                # top_level decides". WALL_USER_HEIGHT_PARAM also stops
                # being the source of truth the moment the wall's top is
                # anchored to a level (Revit derives the height itself from
                # the pair of levels). The obligation is required ONLY when
                # top_level is ABSENT — the reverse direction of the usual
                # conditional (see Obligation.unless_param).
                ob("height param == height_mm when top_level is not given "
                   "(parameter)",
                   KIND_PARAMETER, ("WALL_USER_HEIGHT_PARAM",),
                   unless_param="top_level", key="height"),
                ob("arc curve == arc dict when supplied (geometry)",
                   KIND_GEOMETRY, (".Curve is Arc", "__arc"),
                   param="arc", conditional=True, key="arc"),
                ob("base offset param == base_offset_mm when given (geometry)",
                   KIND_GEOMETRY, ("WALL_BASE_OFFSET",),
                   param="base_offset_mm", conditional=True, key="base_offset"),
                # Measured on 28.07
                # (docs/2026-07-28-location-line-measurement.md): the
                # location-line rule moves NEITHER the axis NOR the body —
                # not on creation, not afterward; it decides which plane
                # survives a thickness change. So its axis is semantic, and
                # it is read by the one thing it actually has — the
                # parameter's ordinal. The wall's geometry is covered by the
                # endpoints witness.
                ob("location line rule == location_line when given (semantic)",
                   KIND_SEMANTIC, ("WALL_KEY_REF_PARAM",),
                   param="location_line", conditional=True,
                   key="location_line"),
                ob("top constraint == resolved top_level when given (topology)",
                   KIND_TOPOLOGY, ("WALL_HEIGHT_TYPE",),
                   param="top_level", conditional=True, key="top_constraint"),
                # 🔴 Э3.1 19.08, THE SAME AS FOR THE COLUMN. The obligation
                # above reads which level WALL_HEIGHT_TYPE POINTS TO. None
                # of them reads whether the wall's BODY actually reaches
                # that elevation. The benchmark's control hand, in
                # freestanding C#, created 288 walls via the overload with a
                # NUMERIC height and got geometry that is correct today and
                # dead from the first level shift; our trouble is the
                # reverse — the anchor is there, and whether the body
                # reached it, nobody asked.
                # One-sided for the same reason: `__post` leads to RollBack.
                ob("built wall spans at least base..top elevation when "
                   "top_level is given (geometry)",
                   KIND_GEOMETRY, ("__wex",),
                   param="top_level", conditional=True, key="vertical_extent"),
                # Wall-fidelity (live A5 evidence 2026-07-21): explicit top
                # offset is a DEFINING DOF of the attach and must be witnessed.
                ob("top offset param == top_offset_mm when given (geometry)",
                   KIND_GEOMETRY, ("WALL_TOP_OFFSET",),
                   param="top_offset_mm", conditional=True, key="top_offset"),
            ),
        ),
        OpRefinementSpec(
            op="create_pipe",
            materializer=("Plumbing.Pipe.Create",),
            witness_source="model",
            obligations=(
                ob("pipe exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("LocationCurve endpoints == p0/p1 3D (geometry)",
                   KIND_GEOMETRY, _ENDPOINTS, key="endpoints"),
                ob("reference level == resolved level (topology)",
                   KIND_TOPOLOGY, ("RBS_START_LEVEL_PARAM",),
                   key="reference_level"),
                ob("diameter param == diameter_mm when given (parameter)",
                   KIND_PARAMETER, ("RBS_PIPE_DIAMETER_PARAM",),
                   param="diameter_mm", conditional=True, key="diameter"),
            ),
        ),
        OpRefinementSpec(
            op="create_grid",
            materializer=("Grid.Create",),
            witness_source="model",
            obligations=(
                ob("grid exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("curve endpoints == p0/p1 (geometry)",
                   KIND_GEOMETRY, (".Curve",), key="endpoints"),
                ob("Name == name when given (identity)",
                   KIND_IDENTITY, (".Name != ",),
                   param="name", conditional=True, key="name"),
            ),
        ),
        OpRefinementSpec(
            op="create_level",
            materializer=("Level.Create",),
            witness_source="model",
            obligations=(
                ob("level exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("Elevation == elev_mm (geometry)",
                   KIND_GEOMETRY, (".Elevation",), key="elevation"),
                ob("Name == name when given (identity)",
                   KIND_IDENTITY, (".Name != ",),
                   param="name", conditional=True, key="name"),
            ),
        ),
        OpRefinementSpec(
            # THE TRIPLE THE WITNESS CHECKS IS EXACTLY THE TRIPLE THE
            # SEPARATOR USES TO FIND A VIEW (`room_emit._view_pick_cs`):
            # GenLevel, not a template, ViewType.FloorPlan. An op that
            # creates a view failing this filter would be correct and
            # useless — so the obligations were copied from the CONSUMER'S
            # FILTER, not invented.
            op="create_floor_plan",
            materializer=("ViewPlan.Create",),
            witness_source="model",
            obligations=(
                ob("floor plan exists — created or already present "
                   "(materialize)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE,
                   key="plan_for_level"),
                ob("GenLevel is EXACTLY the resolved level (identity)",
                   KIND_IDENTITY, (".GenLevel",), key="gen_level"),
                ob("the view is not a template (semantic)",
                   KIND_SEMANTIC, (".IsTemplate",), key="not_template"),
                ob("ViewType is FloorPlan (semantic)",
                   KIND_SEMANTIC, (".ViewType",), key="view_type"),
                ob("Name == name when given (identity)",
                   KIND_IDENTITY, (".Name != ",),
                   param="name", conditional=True, key="name"),
            ),
        ),
        OpRefinementSpec(
            op="set_param",
            materializer=(".Set(",),
            witness_source="model",
            obligations=(
                ob("param resolved+writable or typed refusal (materialize)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                # THE STAGE OF THE OPERATION, not the end of the program
                # (07.09.2026, F1/C01): a second legal `set_param` of the
                # same parameter is entitled to change this value — see the
                # emitter and
                # test_the_last_legal_writer_defines_the_final_state.py
                ob("parameter holds requested value at the end of THIS "
                   "operation, before the next one (parameter)",
                   KIND_PARAMETER, (".AsString(", ".AsDouble(", ".AsInteger("),
                   block=BLOCK_OPERATION, key="value_held"),
            ),
        ),
        OpRefinementSpec(
            op="delete",
            materializer=("doc.Delete",),
            witness_source="model",
            obligations=(
                ob("target resolved or typed refusal (materialize)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("element no longer resolvable post-commit (semantic)",
                   KIND_SEMANTIC, ("doc.GetElement",), key="gone"),
            ),
        ),
        # CLASH fix (28.07): move_elements / change_type.
        OpRefinementSpec(
            op="move_elements",
            materializer=("ElementTransformUtils.MoveElements",),
            witness_source="model",
            obligations=(
                ob("targets resolved, none pinned/stale, or typed refusal "
                   "(materialize)", KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("every target's Location shifted by delta_mm exactly at "
                   "the end of THIS operation (geometry)", KIND_GEOMETRY,
                   _LOCATION_POINT + _ENDPOINTS,
                   block=BLOCK_OPERATION, key="location"),
                ob("total CONNECTED connector count over targets unchanged "
                   "(topology)", KIND_TOPOLOGY, (".ConnectorManager",),
                   key="connectors"),
                ob("LocationCurve target slope (end1.Z-end0.Z) unchanged "
                   "(semantic)", KIND_SEMANTIC, (".GetEndPoint(",),
                   key="slope"),
                # 🔴 CIRCLE OF CONSEQUENCES (22.08.2026). The three
                # obligations above speak about the TARGET ITSELF, while the
                # move's effect lives in its NEIGHBORS, and
                # `unwitnessed_axes` printed `{}` — that is, it declared full
                # coverage. This was green by construction: a neighbor's
                # axes are not in the axis list at all, so nothing counted
                # as unchecked. The witnesses are already emitted; here they
                # become REQUIRED, otherwise the certificate never asks them.
                ob("every door/window insert a moved HostObject carried is "
                   "still hosted by it after (topology)", KIND_TOPOLOGY,
                   (".FindInserts(",), key="hosted_inserts"),
                ob("every LOCKED single-segment Dimension depending on a "
                   "target is still locked after (topology)", KIND_TOPOLOGY,
                   (".IsLocked",), key="locked_dimensions"),
            ),
        ),
        OpRefinementSpec(
            op="change_type",
            materializer=(".ChangeTypeId(",),
            witness_source="model",
            obligations=(
                ob("target/type resolved or typed refusal (materialize)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("GetTypeId() == requested type after this operation's Regenerate "
                   "before subsequent operations (semantic)", KIND_SEMANTIC, (),
                   block=BLOCK_OPERATION, key="type_assignment"),
            ),
        ),
        # GEOMETRY JOIN (18.08.2026). A rare case in this table: the op's
        # promise and the witness's question are THE SAME RELATION.
        #
        # Usually the witness asks a proxy: for a floor — the bounding box
        # instead of the contour, for a beam — the level anchor instead of
        # "it stands where it was told". Here the op promises "joined", and
        # the witness calls `AreElementsJoined` — exactly the function whose
        # "yes" constitutes the promise. No tolerance, no approximation: a
        # boolean, re-read after Regenerate.
        #
        # The materialization marker is `JoinGeometryUtils.JoinGeometry(`,
        # not the short `JoinGeometry(`: the latter would also match
        # `AreElementsJoined` in the same block, and the pre-check would
        # have counted as the effect itself — that is, an op that joined
        # NOTHING would present a materialization certificate. The full name
        # distinguishes the calls by construction.
        OpRefinementSpec(
            op="join_elements",
            materializer=("JoinGeometryUtils.JoinGeometry(",),
            witness_source="model",
            obligations=(
                ob("first/second resolved and joined, or typed refusal "
                   "(materialize)", KIND_MATERIALIZE, _REFUSE,
                   block=BLOCK_CREATE),
                ob("AreElementsJoined(doc, first, second) == true post-commit "
                   "(semantic, re-read by the same relation the op promises)",
                   KIND_SEMANTIC, ("JoinGeometryUtils.AreElementsJoined(",),
                   key="elements_joined"),
            ),
        ),
        OpRefinementSpec(
            op="create_floor",
            materializer=("Floor.Create", "NewFloor"),
            witness_source="model",
            obligations=(
                ob("floor exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("assigned type == resolved requested type at operation end (identity)",
                   KIND_IDENTITY, (), block=BLOCK_OPERATION, key="type_assignment"),
                ob("level binding == resolved level (topology)",
                   KIND_TOPOLOGY, _LEVEL_BIP, key="level_binding"),
                ob("bbox XY extents == outline extents (geometry)",
                   KIND_GEOMETRY, _BBOX, key="bbox"),
                # 🔴 SKETCH SHAPE IS A SEPARATE OBLIGATION, NOT A REFINEMENT
                # OF THE BOUNDING BOX. There are two of them because they
                # judge DIFFERENT things and catch different substitutions:
                # the bounding box sees an arc replaced by a chord (the
                # endpoints are the same); the shape sees a shifted interior
                # angle, a lost notch, and a filled-in hole, none of which
                # the bounding box sees by construction — for an L-shaped
                # contour it pins down only 4 of 12 coordinates. The anchor
                # token is `GetDependentElements`, because that is exactly
                # how the witness reaches Sketch.Profile.
                ob("sketch loop count and per-loop vertex multiset == outline "
                   "plus holes on the canon grid (geometry)",
                   KIND_GEOMETRY,
                   ("GetDependentElements", "__KirCanonUnit"),
                   key="sketch_loops"),
                ob("structural flag == requested (semantic)",
                   KIND_SEMANTIC, ("FLOOR_PARAM_IS_STRUCTURAL",),
                   key="structural"),
                # P1 DOF-completeness: the floor's offset from the level.
                ob("height offset param == height_offset_mm when given "
                   "(geometry)",
                   KIND_GEOMETRY, ("FLOOR_HEIGHTABOVELEVEL_PARAM",),
                   param="height_offset_mm", conditional=True,
                   key="height_offset"),
            ),
        ),
        # wave/arch (2026-07-29).
        OpRefinementSpec(
            op="create_ceiling",
            # One single materializer: Ceiling.Create. The floor has two
            # (Floor.Create / NewFloor — a version fork); the ceiling has no
            # second one, and this is a MEASUREMENT, not a table
            # simplification: doc.Create.NewCeiling does not compile on any
            # of the six versions. For the same reason the ceiling's
            # certificate is only taken from 2022+ (`__min_ver__` on
            # arch_ceiling): on 2021 there is no emission at all — a typed
            # refusal KIR-E003 stands there, not a different emission.
            materializer=("Ceiling.Create",),
            witness_source="model",
            obligations=(
                ob("ceiling exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("level binding == resolved level (topology)",
                   KIND_TOPOLOGY, _LEVEL_BIP, key="level_binding"),
                # One witness for BOTH shape inputs (09.08): the direct
                # `outline` and the sketch `contour` differ only in the
                # NUMBER against which the bounding box is checked (vertices
                # versus lowered-edges with the arcs' cardinal extrema), and
                # in both cases what is read is get_BoundingBox of the
                # created ceiling. A second obligation here would mean that
                # one of the branches could be left without a witness and
                # the certificate would not notice.
                # SKETCH SHAPE is the SECOND geometric obligation, and it
                # too is ONE for both branches: both `outline` and the
                # contour yield rings of vertices, and in both cases what is
                # read is Sketch.Profile.
                # An arc is not an obstacle — Revit returns it as ONE curve
                # (measured on 19.08 across 67 decompiles: 10,463 rings, 331
                # `arc` entries recorded separately, not a single
                # tessellation run).
                ob("sketch loop count and per-loop vertex multiset == "
                   "authored rings on the canon grid (geometry)",
                   KIND_GEOMETRY,
                   ("GetDependentElements", "__KirCanonUnit"),
                   key="sketch_loops"),
                # 🔴 KIND-OF-VALUE GATE (20.08.2026), the same one as for the
                # contour-based floor: the bounding box is provable as long
                # as the loop consists of lines and arcs, and UNPROVABLE the
                # moment a spline appears in it. Without the gate, a ceiling
                # with a curved edge would get proven=False with the reason
                # «no witness check with key 'bbox'» — that is, "we could
                # not prove it" instead of "we deliberately make no claim".
                # The `outline` branch is untouched by the gate: there
                # `__region__` does not exist at all, and the obligation
                # remains mandatory.
                ob("bbox XY extents == outline or contour extents (geometry), "
                   "unless a ring carries a spline — then the bbox is a NAMED "
                   "ABSENCE: the curve between the declared points is chosen "
                   "by Revit",
                   KIND_GEOMETRY, _BBOX, key="bbox",
                   unless_kind_in=("contour", "spline")),
                # 🔴 THE SPLINE VIA-POINT HAS ITS OWN WITNESS, AND THE
                # CERTIFICATE WAS MISSING IT (21.08.2026). The clause was
                # present in `OpSpec.post` («every declared spline via-point
                # lies ON the built sketch curve»), the witness was emitted
                # — but there was no obligation, and cutting the witness out
                # left `proven` untouched. The neighbors are blind exactly
                # where the curve lives: `sketch_loops` reads the ENDS of
                # edges (the same for a straight line and for any curve
                # between them), and the bounding box on a spline is
                # understated by construction and is therefore itself
                # declared a named absence one line above.
                #
                # The `when_kind_in` gate mirrors the neighboring
                # `unless_kind_in` and was introduced by this same change:
                # the obligation is presented ONLY to a loop with a spline —
                # a straight contour has nothing for it to be presented to.
                ob("every declared spline via-point lies ON the built sketch "
                   "curve, within Revit's own VertexTolerance (geometry)",
                   KIND_GEOMETRY,
                   ("GetDependentElements", "VertexTolerance"),
                   key="spline_points",
                   when_kind_in=("contour", "spline")),
                ob("height offset param == height_offset_mm when given "
                   "(geometry)",
                   KIND_GEOMETRY, ("CEILING_HEIGHTABOVELEVEL_PARAM",),
                   param="height_offset_mm", conditional=True,
                   key="height_offset"),
            ),
        ),
        OpRefinementSpec(
            op="create_railing",
            # Both overloads are named Railing.Create — one marker is
            # enough for both branches.
            materializer=("Railing.Create",),
            witness_source="model",
            obligations=(
                ob("railing exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                # ONE obligation for two branches, like "footprint" in
                # create_foundation: for a freestanding railing the anchor
                # is the level, for a stair-hosted one it is the host. Either
                # of the two markers proves the anchor that actually exists
                # on that branch.
                ob("path variety: base level == resolved level OR hosted "
                   "variety: railing belongs to the requested host "
                   "(topology)",
                   KIND_TOPOLOGY,
                   ("STAIRS_RAILING_BASE_LEVEL_PARAM", "HasHost"),
                   key="anchor"),
                # 🔴 THE "bbox" OBLIGATION WAS DROPPED ON 25.08.2026, A LIVE
                # MEASUREMENT (Проект1, Revit 2026): the bounding box of the
                # BODY (balusters+handrail) against the bounds of the
                # zero-thickness path LINE is incomparable BY CONSTRUCTION —
                # not noise, but different kinds of quantities (see
                # arch_emit.py:_emit_railing_path). Only the PATH is
                # provable here — and it remains below, as the "path_points"
                # obligation, tighter than before (±1mm on the grid of edge
                # endpoints versus the former ±50mm by bounding box) and
                # WITHOUT losing the fact the dropped obligation had actually
                # proved. Dropped BY NAME, not by widening the tolerance
                # (canon: a tolerance stretched to cover a discrepancy signs
                # off on a real error too).
                #
                # PATH SHAPE sits next to the (former) bounding box, and the
                # gate is the SAME one (`path`): on the `hosted` branch the
                # author submitted no path, and requiring it would mean
                # declaring unprovable something that does not exist.
                #
                # The path is OPEN, so BOTH ends of every curve are taken:
                # one point per edge would lose the path's end.
                ob("path variety: GetPath() re-read == path by the "
                   "multiset of edge endpoints on the canon grid "
                   "(geometry)",
                   KIND_GEOMETRY, ("GetPath", "__KirCanonUnit"),
                   param="path", conditional=True,
                   key="path_points"),
            ),
        ),
        # wave/site (2026-08-09).
        OpRefinementSpec(
            op="create_topography",
            # TWO materializers, because there are two variants and they
            # are two DIFFERENT API calls, not a version fork of one:
            # surface and slab are elements of different categories.
            materializer=("TopographySurface.Create", "Toposolid.Create"),
            witness_source="model",
            obligations=(
                ob("topography exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                # ONE obligation for two branches, like "anchor" in
                # create_railing: the surface hands out points via
                # GetPoints(), the slab — via the shape editor's vertices
                # (GetPoints() does not exist for it, measured). Either of
                # the two markers proves the reading that is actually
                # possible on that branch.
                ob("described terrain points read back from the built "
                   "element (geometry)",
                   KIND_GEOMETRY, ("GetPoints", "SlabShapeVertices"),
                   key="terrain_points"),
                ob("bbox XY extents == points XY extents (geometry)",
                   KIND_GEOMETRY, _BBOX, key="bbox"),
                # Conditional: the level exists ONLY for the slab (the
                # surface has none in the API at all), and ground does not
                # put it into variety=surface — so the field-presence gate
                # is exact.
                ob("level binding == resolved level when variety=toposolid "
                   "(topology)",
                   KIND_TOPOLOGY, _LEVEL_BIP, param="level", conditional=True,
                   key="level_binding"),
            ),
        ),
        OpRefinementSpec(
            op="create_building_pad",
            materializer=("BuildingPad.Create",),
            witness_source="model",
            obligations=(
                ob("building pad exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("level binding == resolved level (topology)",
                   KIND_TOPOLOGY, _LEVEL_BIP, key="level_binding"),
                # The reader here is NOT get_BoundingBox: the pad's body
                # bounding box includes its thickness and the cut into the
                # terrain. What is read is the boundary itself, that is,
                # exactly the submitted sketch.
                ob("GetBoundary() re-read bbox == contour lowered-edges bbox "
                   "(geometry)",
                   KIND_GEOMETRY, ("GetBoundary",), key="bbox"),
                ob("AssociatedTopographySurfaceId holds a real element id "
                   "(topology)",
                   KIND_TOPOLOGY, ("AssociatedTopographySurfaceId",),
                   key="hosting_topography"),
            ),
        ),
        # wave/sweep (2026-08-09). TWO CERTIFICATES OF DIFFERENT STRENGTH,
        # and the difference is declared here, not smoothed over: the edge
        # profile has an obligation of kind GEOMETRY, the wall profile has
        # NONE AT ALL — because the wall profile's position is set by the
        # TYPE, not the call (Autodesk's remark, present in all six
        # RevitAPI.xml, quoted verbatim in `post` and exempted from checking
        # by an explicit line in _NON_WITNESSABLE_CLAUSES). Inventing a
        # geometric obligation for it would mean presenting a witness that
        # cannot fail — which, by this file's law, is worse than having
        # none.
        OpRefinementSpec(
            op="create_wall_sweep",
            materializer=("WallSweep.Create",),
            witness_source="model",
            obligations=(
                ob("wall sweep exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                # A PREFLIGHT CHECK THAT THE API ITSELF REQUIRES: «wall may
                # not host a wall sweep or reveal» is among Create's
                # ArgumentException conditions. An obligation of the
                # CREATION block, not the post: it must fire BEFORE the
                # effect, otherwise the refusal will arrive as a Revit
                # exception and be recorded as `internal`.
                ob("a wall that may not host a sweep is a typed refusal from "
                   "WallAllowsWallSweep before the call",
                   KIND_MATERIALIZE, ("WallAllowsWallSweep",),
                   block=BLOCK_CREATE),
                ob("GetHostIds() re-read contains the requested wall "
                   "(topology)",
                   KIND_TOPOLOGY, ("GetHostIds",), key="sweep_host"),
                ob("GetTypeId() re-read == resolved wall sweep type "
                   "(topology)",
                   KIND_TOPOLOGY, ("GetTypeId",), key="sweep_type"),
                ob("GetWallSweepInfo().IsVertical == requested orientation "
                   "(semantic)",
                   KIND_SEMANTIC, ("GetWallSweepInfo",),
                   key="sweep_orientation"),
            ),
        ),
        OpRefinementSpec(
            op="create_slab_edge",
            materializer=("NewSlabEdge",),
            witness_source="model",
            obligations=(
                ob("slab edge exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                # CARDINALITY IS AN OBLIGATION OF THE CREATION BLOCK, and
                # this is the only place it can be enforced: edge
                # references are selected BEFORE the call, and "the first
                # matching one" after it is already indistinguishable from
                # the correct one.
                ob("the named side resolves to exactly one face and that "
                   "face to exactly one edge loop, and any other cardinality "
                   "is a typed refusal naming the count",
                   KIND_MATERIALIZE, ("EdgeLoops",), block=BLOCK_CREATE),
                ob("every perimeter edge handed to the call is bound in the "
                   "built sweep: get_ReferenceCurve is non-null for each "
                   "(geometry)",
                   KIND_GEOMETRY, ("get_ReferenceCurve",),
                   key="slab_edge_binding"),
                ob("GetTypeId() re-read == resolved slab edge type "
                   "(topology)",
                   KIND_TOPOLOGY, ("GetTypeId",), key="sweep_type"),
            ),
        ),
        OpRefinementSpec(
            op="create_site_subregion",
            materializer=("SiteSubRegion.Create",),
            witness_source="model",
            obligations=(
                ob("site subregion exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("the created surface reports IsSiteSubRegion (semantic)",
                   KIND_SEMANTIC, ("IsSiteSubRegion",), key="is_subregion"),
                ob("GetBoundary() re-read bbox == contour lowered-edges bbox "
                   "(geometry)",
                   KIND_GEOMETRY, ("GetBoundary",), key="bbox"),
                ob("HostId holds a real element id, and equals host when "
                   "given (topology)",
                   KIND_TOPOLOGY, ("HostId",), key="host_binding"),
            ),
        ),
        OpRefinementSpec(
            op="create_directshape",
            materializer=("DirectShape.CreateElement",),
            witness_source="model",
            obligations=(
                ob("direct shape exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                # Bounding box ALONG ALL THREE AXES: for a mesh, Z is an
                # input coordinate just like X and Y, so the floors' common
                # XY witness does not fit here (a witness must sign only the
                # axis it actually read).
                ob("bbox extents == mesh vertex extents in XYZ (geometry)",
                   KIND_GEOMETRY, _BBOX, key="bbox"),
                # The face count is read FROM THE BUILT element via
                # Mesh.NumTriangles, not recomputed from our own input —
                # otherwise the obligation would confirm the call, not the
                # result.
                ob("built mesh triangle count == triangles count (geometry)",
                   KIND_GEOMETRY, ("NumTriangles",), key="triangles"),
                # THE SURFACE, NOT ITS COUNT. The face count does not see a
                # Salvage rebuild that preserved the count and shifted a
                # vertex: such an element passes silently and is
                # indistinguishable from success from the outside. The
                # obligation is discharged by a witness that builds the
                # surface's canon (`mesh_surface_payload`) from the BUILT
                # mesh and compares it to the pre-image registered before
                # the effect.
                ob("built mesh surface multiset == authored surface multiset "
                   "on the canon grid (geometry)",
                   KIND_GEOMETRY, ("__KirCanonPayload",), key="surface"),
            ),
        ),
        # wave/solid (2026-08-09): a parametric solid. Both ops carry THE
        # SAME set of obligations, and this is not a copy-paste: their
        # witnesses DIFFER in formula (prism versus solid of revolution),
        # while the obligation is about WHAT is proved, not about how. The
        # keys match precisely because the same thing is being proved.
        OpRefinementSpec(
            op="create_solid_extrusion",
            materializer=("GeometryCreationUtilities.CreateExtrusionGeometry",),
            witness_source="model",
            obligations=(
                ob("solid direct shape exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                # HOW MANY SOLIDS. One is exactly the declared shape; two
                # mean Revit split it, zero means it did not build it, and
                # both cases look like success from the outside.
                ob("built geometry holds exactly one solid (geometry)",
                   KIND_GEOMETRY, ("__nsol_",), key="solid_count"),
                # THE HEART OF THE WAVE. The volume is read from the BUILT
                # solid and checked against a number that did not exist in
                # the input in any form: profile area × height, both in
                # closed form at compile time. This is not a recomputation
                # of our own input.
                ob("solid volume == profile area * extrusion height, both "
                   "closed-form at compile time (geometry)",
                   KIND_GEOMETRY, ("Volume",), key="volume"),
                # A SECOND, INDEPENDENT AXIS. The cap area does not mix area
                # with height, so it catches what the volume does not
                # (a profile of a different shape with the same area at a
                # different height). ONLY planar faces are read — this
                # witness does not touch curved surfaces, about whose
                # understated area RevitAPI.xml warns.
                ob("planar cap area == twice the profile area (geometry)",
                   KIND_GEOMETRY, ("PlanarFace",), key="cap_area"),
                ob("bbox extents == profile bbox by base_z..base_z+height in "
                   "XYZ (geometry)",
                   KIND_GEOMETRY, _BBOX, key="bbox"),
            ),
        ),
        OpRefinementSpec(
            op="create_solid_revolve",
            materializer=("GeometryCreationUtilities.CreateRevolvedGeometry",),
            witness_source="model",
            obligations=(
                ob("revolved direct shape exists (materialized or typed "
                   "refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("built geometry holds exactly one solid (geometry)",
                   KIND_GEOMETRY, ("__nsol_",), key="solid_count"),
                # θ·∬x dA — the derivation is in emit_solid_revolve's
                # docstring (Fubini in cylindrical coordinates; Pappus's
                # first theorem is its special case at θ=2π).
                ob("solid volume == sweep radians * profile first moment about "
                   "the axis, closed-form at compile time (geometry)",
                   KIND_GEOMETRY, ("Volume",), key="volume"),
                # UNCONDITIONAL, AND THIS IS NOT AN OVERSIGHT. The first
                # revision gated the caps witness on a partial revolution —
                # "at 360° there are no caps, nothing to check". Exactly the
                # opposite: at a full revolution the expected cap area
                # equals ZERO, and that is a meaningful check that the
                # revolution CLOSED. If Revit built a wedge instead of a
                # ring, twice the profile area would sit where zero should
                # be, and a conditional witness would have left the most
                # likely 360° failure without a single reader.
                ob("planar cap area == twice the profile area for a sector "
                   "and zero for a full turn (geometry)",
                   KIND_GEOMETRY, ("PlanarFace",), key="cap_area"),
                ob("bbox extents == the swept annular sector of the profile in "
                   "XYZ (geometry)",
                   KIND_GEOMETRY, _BBOX, key="bbox"),
            ),
        ),
        # wave/boolean (2026-08-20): SUBTRACT · UNITE · INTERSECT.
        # 🔴 THE ONLY OP IN THE REGISTRY WHOSE WITNESS CHECKS NONE OF OUR OWN
        # NUMBERS. For its neighbors the volume is derived in closed form at
        # compile time and compared against Revit's measurement. Here no
        # such number EXISTS and none CAN exist: the kernel chooses the
        # result's shape. So all four quantities at each step are measured
        # by Revit, and what is checked is the RELATIONS between them — the
        # inclusion-exclusion identity. This is not a weakening but a
        # change of kind: the identity determines the result's volume
        # UNAMBIGUOUSLY.
        OpRefinementSpec(
            op="create_solid_boolean",
            materializer=("BooleanOperationsUtils.ExecuteBooleanOperation",),
            witness_source="model",
            obligations=(
                ob("boolean direct shape exists (materialized or typed "
                   "refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("built geometry holds exactly one solid (geometry)",
                   KIND_GEOMETRY, ("__nsol_",), key="solid_count"),
                # A PRECONDITION, NOT A WITNESS, and this separation was
                # bought by decompiling: the direction predicate says "no"
                # both when the operation was swapped and when it is
                # DEGENERATE (the solids do not intersect, or one is nested
                # inside the other). The two fixes are opposites — repair
                # the emission versus rewrite the program — so degeneracy
                # refuses BEFORE the effect with its own code
                # (KIR-B101/KIR-B102), rather than coloring the witness red.
                # The marker is STRUCTURAL: `Math.Min(__bva_` occurs exactly
                # in this comparison and nowhere else.
                ob("every step is non-degenerate: intersection volume is "
                   "neither zero nor the whole of the smaller body (typed "
                   "refusal KIR-B101/KIR-B102 before any effect)",
                   KIND_MATERIALIZE, ("Math.Min(__bva_",), block=BLOCK_CREATE),
                # 🔴 "BUILT BY A DIFFERENT CALL" is in the obligation's text
                # deliberately: without that qualifier, for intersection the
                # promise was fulfilled IDENTICALLY (the same kernel call on
                # both sides of the equality), and the certificate would
                # sign off on a check that cannot fail. The `__bau_` marker
                # is the structural signature of the AUXILIARY solid: it is
                # absent if the solid was not built.
                ob("every step satisfies inclusion-exclusion on volumes "
                   "measured by Revit, with the auxiliary body built by a "
                   "DIFFERENT kernel call than the result: union and "
                   "difference verify against a separately built "
                   "intersection, intersect verifies against a separately "
                   "built union (geometry)",
                   KIND_GEOMETRY, ("__bau_",), key="boolean_identity"),
                # A SECOND CARRIER. When the precondition holds, it adds
                # nothing — this was MEASURED by a FAIL control, not
                # assumed, and is recorded here precisely because a check
                # that cannot add anything reads as a strengthening and is
                # not one.
                ob("every step moves the volume in the direction its "
                   "operation names (geometry, second carrier)",
                   KIND_GEOMETRY, ("__bvr_",), key="boolean_direction"),
            ),
        ),
        # wave/mass (2026-08-10): a wall on a sloped face of a conceptual
        # mass. TWO CREATION-BLOCK OBLIGATIONS, and both must fire BEFORE
        # the effect: Revit brought its OWN preflight validators to this
        # factory, and there is nothing left to ask them after the call —
        # the refusal will arrive as an exception and land in the receipt
        # as `internal`, that is, "something broke on our end" instead of
        # "Revit does not accept this type / this face".
        # ── wave/blend (20.08.2026) ─────────────────────────────────────
        OpRefinementSpec(
            op="create_solid_blend",
            materializer=("GeometryCreationUtilities.CreateBlendGeometry",),
            witness_source="model",
            obligations=(
                ob("blend direct shape exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("built geometry holds exactly one solid (geometry)",
                   KIND_GEOMETRY, ("__nsol_",), key="solid_count"),
                # THE CAPS ARE THE PROFILES THEMSELVES, and their area is
                # closed-form. There is deliberately NO volume in this
                # list: the side surface between the profiles is chosen by
                # Revit («blending smoothly», RevitAPI.xml, the rule is
                # documented nowhere), and the prismatoid formula is exact
                # only for a ruled surface, which Revit does not promise.
                # Signing off on the volume would mean signing off on
                # someone else's choice.
                ob("planar cap area == bottom profile area plus top profile "
                   "area, both closed-form at compile time (geometry)",
                   KIND_GEOMETRY, ("PlanarFace",), key="cap_area"),
                ob("every declared profile vertex lies on the built solid "
                   "boundary within the derived tolerance (geometry)",
                   KIND_GEOMETRY, ("Project",), key="profiles_on_boundary"),
                ob("bbox extents contain the union of both profile bboxes over "
                   "base_z..base_z+height, outward-tolerant because the "
                   "lateral surface is chosen by Revit (geometry)",
                   KIND_GEOMETRY, _BBOX, key="bbox"),
            ),
        ),
        # ── wave/surface (20.08.2026) ───────────────────────────────────
        # ── wave/sweep (20.08.2026) ─────────────────────────────────────
        OpRefinementSpec(
            op="create_solid_sweep",
            # TWO materializers for one op — one per `variety`. A list, not
            # a single member: the certificate looks for ANY of the named
            # ones, and a program with `variety="frame"` need not carry the
            # second factory's name. Lying is impossible in either
            # direction here: an op with NEITHER of the two is not
            # materialized at all.
            materializer=("GeometryCreationUtilities.CreateSweptGeometry",
                          "GeometryCreationUtilities"
                          ".CreateFixedReferenceSweptGeometry"),
            witness_source="model",
            obligations=(
                ob("swept direct shape exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("built geometry holds exactly one solid (geometry)",
                   KIND_GEOMETRY, ("__nsol_",), key="solid_count"),
                # 🔴 THE MAIN ASSERTION, AND IT EXISTS PRECISELY BECAUSE THE
                # SHAPE IS DETERMINED BY THE INPUT. For blend, loft, and
                # swept blend there is no volume in this list: there Revit
                # chooses the side surface. For a sweep it chooses nothing
                # except the profile's ROTATION about the axis, and the
                # volume does not depend on that rotation — the Jacobian
                # does not see it. The precision rests on the profile's
                # centroid sitting ON the path: then the first moment is
                # zero along any direction, and the whisker correction at
                # every node vanishes to zero.
                ob("solid volume == profile area times path length, "
                   "closed-form at compile time and exact because the profile "
                   "centroid rides the path (geometry)",
                   KIND_GEOMETRY, ("__vmm_",), key="volume"),
                # ONE-SIDED, and this is stated in the obligation's own
                # text, not hidden in the code: an exact bounding box does
                # not exist for a sweep as a property of the input.
                ob("bbox extents lie inside the path bbox grown by the "
                   "profile circumradius, one-sided because the roll of the "
                   "profile is chosen by Revit for variety=frame (geometry)",
                   KIND_GEOMETRY, _BBOX, key="bbox"),
            ),
        ),
        OpRefinementSpec(
            op="create_surface",
            materializer=("BRepBuilderSurfaceGeometry.CreateNURBSSurface",),
            witness_source="model",
            obligations=(
                ob("surface direct shape exists (materialized or typed "
                   "refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                # EXACTLY ONE FACE — and this is not a formality.
                # BRepBuilder silently DROPS a face whose boundary it could
                # not close; a shell missing its one face is
                # indistinguishable from success on the outside.
                ob("built geometry holds exactly one face (geometry)",
                   KIND_GEOMETRY, ("__bf",), key="faces"),
                # 🔴 THE TEXT WAS REWRITTEN ON 20.08.2026 FROM A LIVE
                # MEASUREMENT, AND THIS IS NOT A SOFTENING BUT A FIX OF
                # KIND. The previous wording promised REPRESENTATION
                # equality («degrees and control-point counts ... equal the
                # authored ones»). Revit made no such promise: a ruled
                # saddle of degree 3×3 with a 4×4 grid read back as 1×1 with
                # four points — the same surface in its minimal exact
                # representation. The certificate meanwhile printed
                # `proven: True`, that is, it CERTIFIED a promise the
                # witness no longer checked. The promise and the check must
                # travel in one commit.
                ob("the built face is readable back as a NURBS surface "
                   "(geometry)",
                   KIND_GEOMETRY, ("GetNurbsSurfaceDataForSurface",),
                   key="nurbs_shape"),
                # THE OPERATION'S MAIN ASSERTION is geometric, invariant
                # under reparameterization: it mentions neither degree, nor
                # knots, nor point order, and therefore survives any
                # collapse.
                ob("every sampled point of the authored surface lies on the "
                   "built face within the derived tolerance (geometry)",
                   KIND_GEOMETRY, ("__sw",), key="surface_samples"),
                # A STRONG ASSERTION WHERE IT IS POSSIBLE. If Revit
                # preserved the representation, we check the grids
                # point-by-point, which is more precise than sampling. If it
                # collapsed it, we stay silent here, and the silence is
                # covered by the law above.
                ob("when Revit preserved the representation, every authored "
                   "control point equals the one read back within the derived "
                   "tolerance (geometry)",
                   KIND_GEOMETRY, ("__bw",), key="control_points"),
            ),
        ),
        # ── wave/adaptive (20.08.2026) ──────────────────────────────────
        OpRefinementSpec(
            op="create_adaptive_component",
            materializer=(
                "AdaptiveComponentInstanceUtils."
                "CreateAdaptiveComponentInstance",),
            witness_source="model",
            obligations=(
                ob("adaptive instance exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                # REVIT ITSELF CONFIRMS THE KIND, not our memory of the
                # symbol.
                ob("the built element reports itself an adaptive component "
                   "instance (semantic)",
                   KIND_SEMANTIC, ("IsAdaptiveComponentInstance",),
                   key="adaptive_kind"),
                ob("placement point count after creation equals the number the "
                   "family declares (topology)",
                   KIND_TOPOLOGY, ("GetInstancePlacementPointElementRefIds",),
                   key="placement_point_count"),
                # THE SETTER CAN DOCUMENTEDLY REFUSE («unable to move to the
                # new location»), so applying EVERY point is read back
                # rather than assumed to have taken effect.
                ob("every declared point was applied to its placement point "
                   "(geometry)",
                   KIND_GEOMETRY, ("Position",),
                   key="placement_points_applied"),
                # THE BOUNDING BOX IS THE STRONGEST OF THE FOUR: Revit
                # computes it from the family's ACTUAL geometry, which was
                # not in the input. Deliberately one-sided: the panel is
                # entitled to extend past its placement points, its shape
                # belongs to the family, not to us.
                ob("instance bbox contains every declared placement point "
                   "(geometry)",
                   KIND_GEOMETRY, _BBOX, key="bbox_contains_points"),
            ),
        ),
        OpRefinementSpec(
            op="create_face_wall",
            materializer=("FaceWall.Create",),
            witness_source="model",
            obligations=(
                ob("face wall exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("a wall type Revit refuses for a face wall is a typed "
                   "refusal from IsWallTypeValidForFaceWall before the call",
                   KIND_MATERIALIZE, ("IsWallTypeValidForFaceWall",),
                   block=BLOCK_CREATE),
                ob("a face Revit refuses as a face-wall parent is a typed "
                   "refusal from IsValidFaceReferenceForFaceWall before the "
                   "call",
                   KIND_MATERIALIZE, ("IsValidFaceReferenceForFaceWall",),
                   block=BLOCK_CREATE),
                ob("GetTypeId() re-read == resolved wall type (topology)",
                   KIND_TOPOLOGY, ("GetTypeId",), key="face_wall_type"),
                # THE WAVE'S MAIN GEOMETRIC OBLIGATION. The BUILT wall is
                # read: among its outer faces there must be exactly one
                # co-directional with the named mass face. Zero means Revit
                # attached the wall to the wrong place — and this is
                # indistinguishable from success from the outside.
                ob("the built wall has EXACTLY ONE exterior side face "
                   "codirectional with the named mass face (geometry)",
                   KIND_GEOMETRY, ("GetSideFaces",), key="face_wall_normal"),
                ob("a point of that face lies inside the host's model-space "
                   "bounding box grown by the wall's own WallType.Width plus "
                   "VertexTolerance (geometry)",
                   KIND_GEOMETRY, ("get_BoundingBox",),
                   key="face_wall_within_host"),
                # READS THE BODY, NOT THE PARAMETER: the `PlanarFace` marker
                # is exactly the difference §18.3 exists for. The previous
                # revision rested on `HOST_AREA_COMPUTED` and signed off on
                # the geometry without reading it.
                ob("the PlanarFace.Area of that same built face is strictly "
                   "positive (geometry)",
                   KIND_GEOMETRY, ("PlanarFace",),
                   key="face_wall_area_positive"),
            ),
        ),
        # wave/room (2026-08-03): the room separator.
        OpRefinementSpec(
            op="create_room_separator",
            materializer=("NewRoomBoundaryLines",),
            witness_source="model",
            obligations=(
                ob("room separator segments exist (materialized or typed "
                   "refusal)", KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                # HOW MANY. A polyline of n points must yield n-1 curves:
                # one line instead of four is not "we almost built it", it
                # is a different boundary, and from the outside it looks
                # like success.
                #
                # KIND_IDENTITY, NOT KIND_MATERIALIZE, AND THIS IS NOT A
                # MATTER OF TASTE: materialize obligations are discharged by
                # the certificate on the CREATION SIDE (a materializer's
                # presence + __Refuse) and never look at the witness at
                # all — meaning under that kind, cutting out a live witness
                # would leave PROVEN untouched. Caught by the mutation
                # oracle L6 (test_tolerance_provenance), not by reasoning.
                ob("созданных сегментов ровно на один меньше, чем точек path "
                   "(identity)",
                   KIND_IDENTITY, (".Count !=",), key="segment_count"),
                # WHAT EXACTLY. The heart of the operation: an ordinary
                # model line in the same place bounds nothing and is
                # indistinguishable from a separator on the outside —
                # exactly the substitution because of which the ceilings
                # wave refused to build a floor instead of a ceiling.
                ob("каждый созданный сегмент лежит в категории "
                   "OST_RoomSeparationLines, а не в обычных модельных линиях "
                   "(topology)",
                   KIND_TOPOLOGY, ("OST_RoomSeparationLines",),
                   key="category"),
                # WHERE. Element.LevelId — the same first link the
                # extraction side uses to read the level: one question, one
                # judge.
                ob("level binding == resolved level у каждого сегмента "
                   "(topology)", KIND_TOPOLOGY, (".LevelId",),
                   key="level_binding"),
                ob("концы каждого сегмента == соседняя пара точек path "
                   "(geometry)", KIND_GEOMETRY, (".GetEndPoint(",),
                   key="endpoints"),
            ),
        ),
        # wave/space (2026-08-10): an HVAC space.
        #
        # THE CLAUSES HERE ARE VERBATIM COPIES of `OpSpec.post`, and this is
        # not a stylistic choice: `audit_registry_coverage` checks prose by
        # SHARED WORDS, meaning a paraphrase could pass the audit on someone
        # else's words (a measured miss — the route_* slope, where "segment"
        # also occurred for the diameter). A verbatim copy removes this
        # whole class of error.
        OpRefinementSpec(
            op="create_space",
            materializer=("doc.Create.NewSpace",),
            witness_source="model",
            obligations=(
                ob("space exists and is placed (materialized or typed "
                   "refusal)", KIND_MATERIALIZE, _REFUSE,
                   block=BLOCK_CREATE),
                # WHERE — the level. The same `.LevelId` the extraction side
                # also uses to read the level.
                ob("LevelId == resolved level (topology)",
                   KIND_TOPOLOGY, (".LevelId",), key="level_binding"),
                # WHERE — the point. `Location` IS COMPUTED BY REVIT, so the
                # "(geometry)" label is valid under §18.3: the reader does
                # not reduce to `get_Parameter(...)`, which we ourselves
                # wrote.
                ob("LocationPoint == xy (±5mm) (geometry)",
                   KIND_GEOMETRY, _LOCATION_POINT, key="location"),
                # WHETHER IT IS ENCLOSED — THE QUANTITY. Area, not volume:
                # `Space.Volume` depends on the document's volume-
                # computation setting, and an obligation on it would be
                # checking the project's checkbox, not what was built.
                ob("Area > 0 — пространство замкнуто, а не создано впустую "
                   "(geometry)", KIND_GEOMETRY, (".Area",), key="area"),
                # WHETHER IT IS ENCLOSED — THE RELATION, AND THIS IS A
                # SEPARATE OBLIGATION, NOT A DUPLICATE OF THE PREVIOUS ONE.
                # The area answers "how much", the boundary loops answer
                # "bounded by what". Only the latter discharges the
                # topology axis: labeling the area reading "(topology)"
                # would mean certifying an axis the reader never touched —
                # exactly the defect test_witness_axis_honesty was written
                # for.
                ob("GetBoundarySegments даёт хотя бы одну непустую петлю "
                   "границы (topology)",
                   KIND_TOPOLOGY, ("GetBoundarySegments",), key="boundary"),
            ),
        ),
        # wave/opening (2026-08-03): an opening as a SEPARATE element.
        OpRefinementSpec(
            op="create_opening",
            # One materializer for both branches: NewOpening's overloads
            # differ by arguments, not by name.
            materializer=("doc.Create.NewOpening",),
            witness_source="model",
            obligations=(
                ob("opening exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                # HOST OWNERSHIP is a shared obligation of both branches:
                # for both the rectangular opening in a wall and the
                # profiled one in a floor, the host is read via the same
                # `Opening.Host`. The key is therefore one and
                # unconditional.
                ob("opening belongs to the host element the program asked "
                   "for (Opening.Host, topology)",
                   KIND_TOPOLOGY, (".Host",), key="host"),
                # BOUNDING BOX — the keys are DIFFERENT, because different
                # API members are read and the branches are mutually
                # exclusive. A shared key here would be a defect: an
                # optional obligation is discharged exactly by the ABSENCE
                # of its own witness (certify_op), and one key for two
                # conditional branches would declare the neighboring
                # branch's witness "superfluous".
                ob("wall_rect variety: IsRectBoundary and the BoundaryRect "
                   "corners hold the requested Z band and width along the "
                   "wall, the absolute shift staying unpinned (geometry)",
                   KIND_GEOMETRY, ("BoundaryRect",),
                   param="p0_mm", conditional=True, key="rect_extent"),
                ob("host_face variety with outline: the BoundaryCurves "
                   "extents == outline extents for a vertical cut and "
                   "contain them for a perpendicular one (geometry)",
                   KIND_GEOMETRY, ("BoundaryCurves",),
                   param="outline", conditional=True, key="bbox"),
                # THE SECOND SHAPE INPUT HAS ITS OWN KEY, by the same
                # argument as the two kinds a paragraph above: `outline` and
                # `contour` are mutually exclusive, and a conditional
                # obligation is discharged exactly by the ABSENCE of its own
                # witness. A shared key would declare the neighboring
                # input's witness "superfluous" on every program.
                #
                # The promise here is WEAKER, and deliberately so: for the
                # sketch the bounding box is checked as a BAND (vertices as
                # the lower bound, the exact bounding box with arcs as the
                # upper bound), because an arc's extremum is only reachable
                # by finite sampling via `Curve.Evaluate`, and the API makes
                # no promise about its density. The analysis is in
                # `opening_emit.py`'s header.
                ob("host_face variety with contour: the BoundaryCurves "
                   "extents cover the contour vertex extents and, for a "
                   "vertical cut, stay inside its arc-aware extents "
                   "(geometry)",
                   KIND_GEOMETRY, ("BoundaryCurves",),
                   param="contour", conditional=True, key="bbox_contour"),
            ),
        ),
        OpRefinementSpec(
            op="create_roof",
            materializer=("NewFootPrintRoof",),
            witness_source="model",
            obligations=(
                ob("roof exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("base level == resolved level (topology)",
                   KIND_TOPOLOGY, ("ROOF_BASE_LEVEL_PARAM",), key="base_level"),
                ob("bbox XY extents == outline extents (geometry)",
                   KIND_GEOMETRY, _BBOX, key="bbox"),
                # FOOTPRINT SHAPE: `NewFootPrintRoof` yields a dependent
                # Sketch exactly like a slab's, and the reader is the same.
                # The slope is witnessed separately — the footprint is
                # flat.
                ob("sketch loop vertex multiset == outline on the "
                   "canon grid (geometry)",
                   KIND_GEOMETRY,
                   ("GetDependentElements", "__KirCanonUnit"),
                   key="sketch_loops"),
            ),
        ),
        OpRefinementSpec(
            op="create_column",
            materializer=("NewFamilyInstance",),
            witness_source="model",
            obligations=(
                ob("column exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("LocationPoint == xy (geometry)",
                   KIND_GEOMETRY, _LOCATION_POINT, key="location"),
                ob("level binding == resolved level (topology)",
                   KIND_TOPOLOGY, _LEVEL_BIP, key="level_binding"),
                ob("StructuralType == requested (semantic)",
                   KIND_SEMANTIC, (".StructuralType",), key="structural_type"),
                # Rotation, top anchor, and top offset are dropped for the
                # TILTED column (`top_xy`): for it, the AXIS sets the top,
                # the emitter deliberately does not write the top
                # parameters (writing them would fight the geometry) and
                # does not witness rotation (the axis carries the
                # orientation). Demanding them back would mean declaring
                # unprovable something this op variant never has.
                # `base_offset` remains: the axis's bottom end is computed
                # FROM it, the promise is ours.
                ob("rotation == rotation_deg when given (geometry)",
                   KIND_GEOMETRY, (".Rotation",),
                   param="rotation_deg", conditional=True,
                   unless_param="top_xy", key="rotation"),
                # P1 DOF-completeness (fidelity audit 2026-07-21): the
                # column's vertical — the defining DOFs of a column's
                # attach.
                ob("base offset param == base_offset_mm when given (geometry)",
                   KIND_GEOMETRY, ("FAMILY_BASE_LEVEL_OFFSET_PARAM",),
                   param="base_offset_mm", conditional=True, key="base_offset"),
                ob("top constraint == resolved top_level when given (topology)",
                   KIND_TOPOLOGY, ("FAMILY_TOP_LEVEL_PARAM",),
                   param="top_level", conditional=True,
                   unless_param="top_xy", key="top_constraint"),
                # 🔴 Э3.1, 19.08.2026. THE VERTICAL WAS ONLY CHECKED AS A
                # REFERENCE. The three obligations above read that the
                # PARAMETER points to the right level (topology) and that
                # the offset equals what was submitted. None of them read
                # whether the GEOMETRY ACTUALLY REACHES what the reference
                # points to. A live benchmark measurement on 18.08: 420
                # columns came out at 2500 mm instead of 3600-4500,
                # surviving the witness, acceptance, and three audits —
                # because with `top_level` omitted the top-anchor obligation
                # is CONDITIONAL and simply did not run, and the height came
                # silently from the symbol's default.
                #
                # The guard is ONE-SIDED, and this is not caution but a
                # measurement: `__post` leads to `__t.RollBack()`, meaning
                # equality on a quantity that nobody here measured live
                # would roll back CORRECT buildings — exactly the mistake
                # `create_beam` had already paid for ("requiring equality
                # was rolling back CORRECTLY built ones", measured 27.07).
                # The observed defect makes the bounding box SHORTER than
                # derived (2500 against 3600, an 1100 mm shortfall); a
                # family that extends past the anchor makes it LONGER.
                # That is why only the shortfall is checked, and a 300 mm
                # margin gives a 3.6x difference from the observed miss.
                ob("built solid spans at least base..top elevation when "
                   "top_level is given (geometry)",
                   KIND_GEOMETRY, ("__vex",),
                   param="top_level", conditional=True,
                   unless_param="top_xy", key="vertical_extent"),
                # 19.08: EXPANDED. It used to be `param="top_offset_mm"` —
                # meaning that with the offset omitted, nobody read back the
                # ZERO that the emitter writes anyway (`cto_literal =
                # "0.0"`). A value written and never read back is our
                # promise without a witness; for the wall exactly this case
                # has been closed since 30.07 ("height param == height_mm
                # when top_level is not given").
                ob("top offset param == top_offset_mm or 0 when top_level "
                   "is given (geometry)",
                   KIND_GEOMETRY, ("FAMILY_TOP_LEVEL_OFFSET_PARAM",),
                   param="top_level", conditional=True,
                   unless_param="top_xy", key="top_offset"),
            ),
        ),
        OpRefinementSpec(
            op="create_window",
            materializer=("NewFamilyInstance",),
            witness_source="model",
            obligations=_hosted_obligations("window"),
        ),
        OpRefinementSpec(
            op="create_door",
            materializer=("NewFamilyInstance",),
            witness_source="model",
            obligations=_hosted_obligations("door"),
        ),
        OpRefinementSpec(
            op="create_room",
            materializer=("NewRoom",),
            witness_source="model",
            obligations=(
                ob("room exists and nonzero area (materialize / semantic)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("LevelId == resolved level (topology)",
                   KIND_TOPOLOGY, (".LevelId",), key="level_binding"),
                ob("LocationPoint == xy (geometry)",
                   KIND_GEOMETRY, _LOCATION_POINT, key="location"),
                ob("nonzero enclosed area (semantic)",
                   KIND_SEMANTIC, (".Area",), key="area"),
                ob("Name == name when given (identity)",
                   KIND_IDENTITY, (".Name != ",),
                   param="name", conditional=True, key="name"),
                # ROOM_NUMBER is an independent semantic field.  The emitter
                # rereads the built-in parameter after Set; Room.Name is a
                # display composite and cannot discharge this obligation.
                ob("Number == number when given (semantic)",
                   KIND_SEMANTIC, ("ROOM_NUMBER", ".AsString()"),
                   param="number", conditional=True, key="number"),
                # 25.08.2026: a live finding, HAB022 — `create_room` could
                # not set the room's upper limit at all (NewRoom sets it
                # from the document type's default, 2438mm, below the
                # 2500mm norm). The same technique as height_offset earlier
                # in the file (create_floor/create_ceiling): the emitter
                # reads ROOM_UPPER_OFFSET back from the BUILT room, rather
                # than confirming that Set() did not throw.
                ob("upper offset param == upper_offset_mm when given "
                   "(geometry)",
                   KIND_GEOMETRY, ("ROOM_UPPER_OFFSET",),
                   param="upper_offset_mm", conditional=True,
                   key="upper_offset"),
            ),
        ),
        OpRefinementSpec(
            op="place_family",
            materializer=("NewFamilyInstance",),
            witness_source="model",
            obligations=(
                ob("instance exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                # The op has two placement variants, and the certificate
                # must name the ONE that is actually proved. While there
                # was one obligation, the curve variant discharged it via
                # the `location` key — and the certificate wrote
                # "LocationPoint == xyz" about an instance for which
                # LocationPoint does not exist. A proved false assertion is
                # worse than an unproved one: it looks like a check.
                ob("LocationPoint == xyz (geometry)",
                   KIND_GEOMETRY, _LOCATION_POINT,
                   param="xyz", conditional=True, key="location"),
                ob("LocationCurve endpoints == p0_mm/p1_mm (geometry)",
                   KIND_GEOMETRY, _ENDPOINTS,
                   param="p0_mm", conditional=True, key="location"),
                # The level belongs to the POINT variant. For placement
                # along a curve on a host there is no level at all: Revit
                # takes it from the host, and an unconditional obligation
                # here is undischargeable in principle — the certificate
                # would declare unprovable something that is not in the op.
                # Exactly the same fix already made above for `location`.
                ob("level binding == resolved level (topology)",
                   KIND_TOPOLOGY, _LEVEL_BIP,
                   param="level", conditional=True, key="level_binding"),
                # The emitter reads the host back (`__el_.Host`), and the
                # certificate did not know about this check: a witness
                # without an obligation is a check that can be silently
                # deleted without dropping a single certificate. The same
                # hole that was closed for the diameter on 27.07.
                ob("host == resolved host (topology)",
                   KIND_TOPOLOGY, (".Host",),
                   param="host", conditional=True, key="host"),
                # ── PLACEMENT KINDS (11.08.2026) ───────────────────────
                # All of them are CONDITIONAL, like their neighbors: the
                # obligation is discharged by the ABSENCE of its own
                # witness when the operand is not named (`certify_op`), so
                # each has its own key — a shared one would declare the
                # neighboring branch's witness "superfluous".
                ob("reference direction == ref_dir when given, read back "
                   "from HandOrientation up to sense (geometry)",
                   KIND_GEOMETRY, ("HandOrientation",),
                   param="ref_dir", conditional=True,
                   key="reference_direction"),
                ob("FAMILY_TOP_LEVEL_PARAM == top_level when given "
                   "(topology)",
                   KIND_TOPOLOGY, ("FAMILY_TOP_LEVEL_PARAM",),
                   param="top_level", conditional=True,
                   key="top_level_binding"),
                # ONE `post` clause — TWO obligations, and this is not
                # inconsistency: the offsets are independent (the author is
                # entitled to name only one), and the conditionality is
                # discharged PER KEY. The coverage audit splits `post` at
                # the semicolon and looks for word overlap — both lines
                # honestly point to the same clause.
                ob("base/top offsets == the requested millimetres when given "
                   "(semantic)",
                   KIND_SEMANTIC, ("FAMILY_BASE_LEVEL_OFFSET_PARAM",),
                   param="base_offset_mm", conditional=True,
                   key="base_offset"),
                ob("base/top offsets == the requested millimetres when given "
                   "(semantic)",
                   KIND_SEMANTIC, ("FAMILY_TOP_LEVEL_OFFSET_PARAM",),
                   param="top_offset_mm", conditional=True,
                   key="top_offset"),
                ob("rotation == rotation_deg when given (geometry)",
                   KIND_GEOMETRY, (".Rotation",),
                   param="rotation_deg", conditional=True, key="rotation"),
                ob("mirrored state == requested when given (semantic)",
                   KIND_SEMANTIC, (".Mirrored != ",),
                   param="mirrored", conditional=True, key="mirrored"),
                ob("hand flip state == requested when given (semantic)",
                   KIND_SEMANTIC, (".HandFlipped != ",),
                   param="hand_flipped", conditional=True, key="hand_flipped"),
                ob("facing flip state == requested when given (semantic)",
                   KIND_SEMANTIC, (".FacingFlipped != ",),
                   param="facing_flipped", conditional=True, key="facing_flipped"),
            ),
        ),
        OpRefinementSpec(
            op="create_pipe_system",
            materializer=("Plumbing.Pipe.Create",),
            witness_source="model",
            obligations=_network_obligations("RBS_PIPE_DIAMETER_PARAM"),
        ),
        OpRefinementSpec(
            op="route_pipe_system",
            materializer=("Plumbing.Pipe.Create",),
            witness_source="model",
            obligations=_network_obligations(
                "RBS_PIPE_DIAMETER_PARAM", with_slope=True, with_level=True),
        ),
        OpRefinementSpec(
            op="route_duct_system",
            materializer=("Mechanical.Duct.Create",),
            witness_source="model",
            obligations=_network_obligations(
                "RBS_CURVE_DIAMETER_PARAM", with_slope=True, with_level=True),
        ),
        OpRefinementSpec(
            op="create_floor_by_contour",
            materializer=("Floor.Create", "NewFloor"),
            witness_source="model",
            obligations=(
                ob("floor exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("assigned type == resolved requested type at operation end (identity)",
                   KIND_IDENTITY, (), block=BLOCK_OPERATION, key="type_assignment"),
                ob("level binding == resolved level (topology)",
                   KIND_TOPOLOGY, _LEVEL_BIP, key="level_binding"),
                ob("bbox == lowered-edges extents (geometry), unless a ring "
                   "carries a spline — then the bbox is a NAMED ABSENCE: the "
                   "curve between the declared points is chosen by Revit",
                   KIND_GEOMETRY, _BBOX, key="bbox",
                   unless_kind_in=("contour", "spline")),
                # SKETCH SHAPE alongside the bounding box: the bounding box
                # catches an arc's sagitta (cardinal extrema), the vertices
                # catch a shifted corner and a lost hole. An arc is not an
                # obstacle: Sketch.Profile returns it as ONE curve (measured
                # on 19.08 across 67 decompiles, 10,463 rings, 331 `arc`
                # curves recorded separately, not a single tessellation
                # run).
                ob("sketch loop count and per-loop vertex multiset == "
                   "authored rings on the canon grid (geometry)",
                   KIND_GEOMETRY,
                   ("GetDependentElements", "__KirCanonUnit"),
                   key="sketch_loops"),
                # The same witness and the same argument as for the ceiling
                # (21.08.2026): the clause was present, the witness was
                # emitted, there was no obligation. Both places are fixed
                # by ONE wave deliberately — otherwise the fix would land
                # on one of two copies, this house's named form.
                ob("every declared spline via-point lies ON the built sketch "
                   "curve, within Revit's own VertexTolerance (geometry)",
                   KIND_GEOMETRY,
                   ("GetDependentElements", "VertexTolerance"),
                   key="spline_points",
                   when_kind_in=("contour", "spline")),
                ob("height offset param == height_offset_mm when given "
                   "(geometry)",
                   KIND_GEOMETRY, ("FLOOR_HEIGHTABOVELEVEL_PARAM",),
                   param="height_offset_mm", conditional=True,
                   key="height_offset"),
            ),
        ),
        OpRefinementSpec(
            op="create_duct",
            materializer=("Mechanical.Duct.Create",),
            witness_source="model",
            obligations=(
                ob("duct exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("LocationCurve endpoints == p0/p1 3D (geometry)",
                   KIND_GEOMETRY, _ENDPOINTS, key="endpoints"),
                ob("reference level == resolved level (topology)",
                   KIND_TOPOLOGY, ("RBS_START_LEVEL_PARAM",),
                   key="reference_level"),
                ob("diameter param == diameter_mm when given (parameter)",
                   KIND_PARAMETER, ("RBS_CURVE_DIAMETER_PARAM",),
                   param="diameter_mm", conditional=True, key="diameter"),
            ),
        ),
        OpRefinementSpec(
            op="create_cable_tray",
            materializer=("Electrical.CableTray.Create",),
            witness_source="model",
            obligations=(
                ob("cable tray exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("LocationCurve endpoints == p0/p1 3D (geometry)",
                   KIND_GEOMETRY, _ENDPOINTS, key="endpoints"),
                ob("reference level == resolved level (topology)",
                   KIND_TOPOLOGY, ("RBS_START_LEVEL_PARAM",),
                   key="reference_level"),
                ob("width param == width_mm when given (parameter)",
                   KIND_PARAMETER, ("RBS_CABLETRAY_WIDTH_PARAM",),
                   param="width_mm", conditional=True, key="width"),
                ob("height param == height_mm when given (parameter)",
                   KIND_PARAMETER, ("RBS_CABLETRAY_HEIGHT_PARAM",),
                   param="height_mm", conditional=True, key="height"),
            ),
        ),
        # wave/mep-electrical (2026-08-09). Five operations, three witness
        # genres — and none of their obligations reduces to "the setter
        # ran": for the tray and the stubs the axis is read from Revit
        # (`LocationCurve`), for the flexible ones — the whole path
        # (`Points`), and for all of them the type is taken via
        # `GetTypeId()` from the built element.
        OpRefinementSpec(
            op="create_conduit",
            materializer=("Electrical.Conduit.Create",),
            witness_source="model",
            obligations=(
                ob("conduit exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("LocationCurve endpoints == p0/p1 3D (geometry)",
                   KIND_GEOMETRY, _ENDPOINTS, key="endpoints"),
                ob("reference level == resolved level (topology)",
                   KIND_TOPOLOGY, ("RBS_START_LEVEL_PARAM",),
                   key="reference_level"),
                ob("conduit_type of the built element == resolved "
                   "conduit_type (semantic)",
                   KIND_SEMANTIC, ("GetTypeId",), key="conduit_type"),
            ),
        ),
        # wave/analysis (2026-08-09). Three loads and an evacuation route.
        # The obligations are listed in the same order analysis_emit.py
        # emits them, and each reads a PROPERTY OF THE BUILT ELEMENT: for
        # the loads — `Point`/`StartPoint`/`GetLoops`, `OrientTo`,
        # `ForceVector*`, `LoadCaseId`, `GetTypeId`; for the route —
        # `PathStart`/`PathEnd`, `GetCurves`, `OwnerViewId`.
        #
        # `OrientTo` stands here as a SEPARATE obligation, not a footnote
        # to the force: `ForceVector` is documented as «oriented according
        # to OrientTo setting», meaning that without a pinned-down
        # reference frame the vector's three numbers do not mean anything
        # definite, and the force witness relies on this fact.
        OpRefinementSpec(
            op="create_point_load",
            materializer=("Structure.PointLoad.Create",),
            witness_source="model",
            obligations=(
                ob("point load exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("Point of the built element == xyz (geometry)",
                   KIND_GEOMETRY, (".Point",), key="position"),
                ob("OrientTo of the built element == Project (semantic)",
                   KIND_SEMANTIC, (".OrientTo",), key="orientation"),
                ob("ForceVector of the built element == newtons requested "
                   "(semantic)",
                   KIND_SEMANTIC, (".ForceVector",), key="force_vector"),
                ob("MomentVector of the built element == newton-metres "
                   "requested (semantic)",
                   KIND_SEMANTIC, (".MomentVector",), key="moment_vector"),
                ob("load case of the built element == resolved load_case "
                   "(semantic)",
                   KIND_SEMANTIC, (".LoadCaseId",), key="load_case"),
                ob("load_type of the built element == resolved load_type "
                   "(semantic)",
                   KIND_SEMANTIC, ("GetTypeId",), key="load_type"),
            ),
        ),
        OpRefinementSpec(
            op="create_line_load",
            materializer=("Structure.LineLoad.Create",),
            witness_source="model",
            obligations=(
                ob("line load exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("StartPoint and EndPoint of the built element == p0_mm and "
                   "p1_mm (geometry)",
                   KIND_GEOMETRY, (".StartPoint",), key="endpoints"),
                ob("OrientTo of the built element == Project (semantic)",
                   KIND_SEMANTIC, (".OrientTo",), key="orientation"),
                ob("ForceVector1 of the built element == newtons per metre "
                   "requested (semantic)",
                   KIND_SEMANTIC, (".ForceVector1",), key="force_vector"),
                ob("IsUniform of the built element (semantic)",
                   KIND_SEMANTIC, (".IsUniform",), key="uniform"),
                ob("load case of the built element == resolved load_case "
                   "(semantic)",
                   KIND_SEMANTIC, (".LoadCaseId",), key="load_case"),
                ob("load_type of the built element == resolved load_type "
                   "(semantic)",
                   KIND_SEMANTIC, ("GetTypeId",), key="load_type"),
            ),
        ),
        OpRefinementSpec(
            op="create_area_load",
            materializer=("Structure.AreaLoad.Create",),
            witness_source="model",
            obligations=(
                ob("area load exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("GetLoops of the built element returns one loop whose "
                   "vertices are the outline at elev_mm, same count (geometry)",
                   KIND_GEOMETRY, ("GetLoops",), key="loop_vertices"),
                ob("OrientTo of the built element == Project (semantic)",
                   KIND_SEMANTIC, (".OrientTo",), key="orientation"),
                ob("ForceVector1 of the built element == newtons per square "
                   "metre requested (semantic)",
                   KIND_SEMANTIC, (".ForceVector1",), key="force_vector"),
                ob("load case of the built element == resolved load_case "
                   "(semantic)",
                   KIND_SEMANTIC, (".LoadCaseId",), key="load_case"),
                ob("load_type of the built element == resolved load_type "
                   "(semantic)",
                   KIND_SEMANTIC, ("GetTypeId",), key="load_type"),
            ),
        ),
        OpRefinementSpec(
            op="create_path_of_travel",
            materializer=("Analysis.PathOfTravel.Create",),
            witness_source="model",
            obligations=(
                ob("path of travel exists and its calculation status is "
                   "Success (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("PathStart and PathEnd of the built element == p0_mm and "
                   "p1_mm in plan, Z excluded (geometry)",
                   KIND_GEOMETRY, (".PathStart",), key="endpoints"),
                ob("the route read back is non-empty and no shorter than the "
                   "straight line between the requested points (geometry)",
                   KIND_GEOMETRY, ("GetCurves",), key="route"),
                ob("OwnerViewId of the built element == in_view (topology)",
                   KIND_TOPOLOGY, (".OwnerViewId",), key="owner_view"),
            ),
        ),
        OpRefinementSpec(
            op="create_pipe_placeholder",
            materializer=("Plumbing.Pipe.CreatePlaceholder",),
            witness_source="model",
            obligations=(
                ob("placeholder pipe exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("LocationCurve endpoints == p0/p1 3D (geometry)",
                   KIND_GEOMETRY, _ENDPOINTS, key="endpoints"),
                ob("reference level == resolved level (topology)",
                   KIND_TOPOLOGY, ("RBS_START_LEVEL_PARAM",),
                   key="reference_level"),
                ob("IsPlaceholder of the built element (semantic)",
                   KIND_SEMANTIC, ("IsPlaceholder",), key="is_placeholder"),
                ob("pipe_type of the built element == resolved pipe_type "
                   "(semantic)",
                   KIND_SEMANTIC, ("GetTypeId",), key="pipe_type"),
            ),
        ),
        OpRefinementSpec(
            op="create_duct_placeholder",
            materializer=("Mechanical.Duct.CreatePlaceholder",),
            witness_source="model",
            obligations=(
                ob("placeholder duct exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("LocationCurve endpoints == p0/p1 3D (geometry)",
                   KIND_GEOMETRY, _ENDPOINTS, key="endpoints"),
                ob("reference level == resolved level (topology)",
                   KIND_TOPOLOGY, ("RBS_START_LEVEL_PARAM",),
                   key="reference_level"),
                ob("IsPlaceholder of the built element (semantic)",
                   KIND_SEMANTIC, ("IsPlaceholder",), key="is_placeholder"),
                ob("duct_type of the built element == resolved duct_type "
                   "(semantic)",
                   KIND_SEMANTIC, ("GetTypeId",), key="duct_type"),
            ),
        ),
        OpRefinementSpec(
            op="create_flex_duct",
            materializer=("Mechanical.FlexDuct.Create",),
            witness_source="model",
            obligations=(
                ob("flex duct exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("Points read back == path, same count and same order "
                   "(geometry)",
                   KIND_GEOMETRY, (".Points",), key="path_points"),
                ob("reference level == resolved level (topology)",
                   KIND_TOPOLOGY, ("RBS_START_LEVEL_PARAM",),
                   key="reference_level"),
                ob("flex_duct_type of the built element == resolved "
                   "flex_duct_type (semantic)",
                   KIND_SEMANTIC, ("GetTypeId",), key="flex_duct_type"),
            ),
        ),
        OpRefinementSpec(
            op="create_flex_pipe",
            materializer=("Plumbing.FlexPipe.Create",),
            witness_source="model",
            obligations=(
                ob("flex pipe exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("Points read back == path, same count and same order "
                   "(geometry)",
                   KIND_GEOMETRY, (".Points",), key="path_points"),
                ob("reference level == resolved level (topology)",
                   KIND_TOPOLOGY, ("RBS_START_LEVEL_PARAM",),
                   key="reference_level"),
                ob("flex_pipe_type of the built element == resolved "
                   "flex_pipe_type (semantic)",
                   KIND_SEMANTIC, ("GetTypeId",), key="flex_pipe_type"),
            ),
        ),
        OpRefinementSpec(
            op="create_type",
            materializer=(".Duplicate(",),
            witness_source="model",
            obligations=(
                ob("new FamilySymbol exists (materialize or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("width param holds width_mm at pre-commit re-read (parameter)",
                   KIND_PARAMETER, ("__pw_",), key="width"),
                ob("depth param holds depth_mm when given (parameter)",
                   KIND_PARAMETER, ("__pd_",),
                   param="depth_mm", conditional=True, key="depth"),
                ob("material holds when given (parameter)",
                   KIND_PARAMETER, ("STRUCTURAL_MATERIAL_PARAM",),
                   param="material", conditional=True, key="material"),
            ),
        ),
        OpRefinementSpec(
            op="load_family",
            materializer=("LoadFamily", "LoadFamilySymbol"),
            witness_source="model",
            obligations=(
                ob("File.Exists checked / typed refusal (materialize)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("symbol active post-load (semantic)",
                   KIND_SEMANTIC, (".IsActive",), key="active"),
            ),
        ),
        # DOCUMENT-TO-DOCUMENT FAMILY TRANSFER (23.08.2026). The
        # materializer NAMES BOTH LINKS: `EditFamily` yields the in-memory
        # family document, `LoadFamily` brings it into the target. One
        # `LoadFamily` alone would not be enough — it also stands for the
        # neighboring `load_family`, which takes a PATH, and the
        # certificate would stop distinguishing two different mechanisms
        # under one trace.
        OpRefinementSpec(
            op="transfer_family",
            materializer=("EditFamily", "LoadFamily"),
            witness_source="model",
            obligations=(
                ob("family exists in the target document / typed refusal "
                   "(materialize)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("family name in target equals family_name (identity)",
                   KIND_IDENTITY, (".Name",), key="family_name"),
                # THE OBLIGATION'S WORDING MATCHES THE CLAUSE'S WORDING
                # DELIBERATELY: the check works by SHARED TOKENS, and the
                # English «symbol active» would not have shared a single
                # word with a Russian «FamilySymbol АКТИВЕН» — the
                # obligation would exist, but the audit would count the
                # clause as unwitnessable.
                ob("ровно один FamilySymbol АКТИВЕН post-commit, Ordinal "
                   "(semantic)",
                   KIND_SEMANTIC, (".IsActive",), key="active"),
                ob("активный символ принадлежит перенесённому семейству "
                   "(identity)",
                   KIND_IDENTITY, (".Family",), key="symbol_family"),
            ),
        ),
        # WALL TYPE WITH A LAYERED STRUCTURE (23.08.2026). The materializer
        # names BOTH links: `Duplicate` yields the element,
        # `SetCompoundStructure` puts the layer structure into it. One
        # `Duplicate` alone would not be enough — it also stands for
        # `create_type`, and the trace would stop distinguishing the two
        # mechanisms.
        OpRefinementSpec(
            op="create_wall_type",
            materializer=("Duplicate", "SetCompoundStructure"),
            witness_source="model",
            obligations=(
                # A KEY ON `materialize` — THE SECOND ONE IN THE TABLE
                # (23.08.2026), and it is backed by a witness: `type_reread`
                # reads the type back by its own Id and stays silent only
                # when it is alive. For the 72 keyless neighbors the clause
                # is still discharged by the constructor's presence; here it
                # is not.
                ob("тип стены существует / типизированный отказ "
                   "(materialize)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE,
                   key="type_reread"),
                ob("Name типа равно new_name, одноимённый не подменяется "
                   "(identity)",
                   KIND_IDENTITY, (".Name",), key="type_name"),
                ob("число слоёв равно длине layers (semantic)",
                   KIND_SEMANTIC, (".GetLayers",), key="layer_count"),
                ob("толщина и функция каждого слоя равны запрошенным "
                   "(geometry)",
                   KIND_GEOMETRY, (".Width", ".Function"), key="layers"),
                ob("материал слоя равен разрешённому по точному имени, "
                   "слой без материала несёт InvalidElementId (identity)",
                   KIND_IDENTITY, (".MaterialId",), key="layer_material"),
                ob("Width типа равен сумме толщин слоёв (geometry)",
                   KIND_GEOMETRY, (".Width",), key="total_width"),
            ),
        ),
        # MATERIAL FROM A NEIGHBORING DOCUMENT (24.08.2026). The
        # materializer is `CopyElements`, and only it is named: there is no
        # second link here, the node arrives WITH ITS DEPENDENCIES in one
        # call. The witness, THE ONLY ONE IN THE REGISTRY, reads BOTH
        # sides: the op's promise is "as in the source", not "as in the
        # program", and there are no expected values in the program at
        # all.
        OpRefinementSpec(
            op="transfer_material",
            materializer=("CopyElements",),
            witness_source="model",
            obligations=(
                ob("материал существует в целевом документе / типизированный "
                   "отказ (materialize)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE,
                   key="material_reread"),
                ob("Name равно name, одноимённый не подменяется и не "
                   "дублируется (identity)",
                   KIND_IDENTITY, (".Name",), key="material_name"),
                ob("MaterialClass и MaterialCategory равны исходным "
                   "(semantic)",
                   KIND_SEMANTIC, (".MaterialClass", ".MaterialCategory"),
                   key="material_class"),
                ob("Color равен исходному по всем трём каналам (semantic)",
                   KIND_SEMANTIC, (".Color",), key="material_color"),
                # FOR THE SAKE OF THIS CLAUSE THE OP DOES NOT ASSEMBLE THE
                # MATERIAL FROM VALUES: a correct name with a lost
                # appearance is indistinguishable from success without it,
                # and a measurement on 24.08 shows that appearance is
                # carried by 21 of the 23 transferable materials.
                ob("приложение внешнего вида присутствует ровно тогда, когда "
                   "оно есть у источника, и имена совпадают (identity)",
                   KIND_IDENTITY, (".AppearanceAssetId",),
                   key="appearance_asset"),
                ob("имена штриховок поверхности и разреза совпадают с "
                   "исходными, включая их отсутствие (identity)",
                   KIND_IDENTITY, (".SurfaceForegroundPatternId",
                                   ".CutForegroundPatternId"),
                   key="fill_patterns"),
            ),
        ),
        OpRefinementSpec(
            op="create_dimension",
            materializer=("NewDimension",),
            witness_source="model",
            # 28.07 said this op could carry no gated GEOMETRY obligation:
            # the measured VALUE depended on which face happened to resolve
            # first, and Dimension.Curve is documented ALWAYS UNBOUND (Revit
            # API Developer Guide, "Dimensions and Constraints"), so no
            # independent expectation existed. 09.08 REVERSES that half: the
            # resolver now knows which PLANE each reference names, so the
            # distance between those planes IS the independent expectation,
            # and the witness compares Revit's own Value/Segments against it.
            # The claim signed is deliberately narrow — the number matches
            # the geometry the dimension is bound to, NOT the operator's
            # intent (exterior vs interior face is unknowable here).
            # The retired "line_at reproduced (geometry)" obligation asserted
            # Dimension.Origin's offset along a FIXED View.UpDirection,
            # which stopped being meaningful once the dimension line's own
            # direction became face-normal-derived (not always
            # UpDirection-perpendicular) — see _emit_dimension docstring.
            obligations=(
                ob("dimension exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("belongs to in_view (topology)",
                   KIND_TOPOLOGY, (".OwnerViewId", ".View"), key="in_view"),
                ob("References match requested refs (topology)",
                   KIND_TOPOLOGY, (".References",), key="references"),
                ob("measured value equals the distance between the "
                   "referenced geometry (geometry)",
                   KIND_GEOMETRY, (".Value", ".Segments"), key="value"),
            ),
        ),
        OpRefinementSpec(
            op="create_angular_dimension",
            materializer=("AngularDimension.Create",),
            witness_source="model",
            # 09.08. The arc is DERIVED from the two references (vertex =
            # intersection of their planes, radius and ray choice from `at`),
            # so the sweep angle is known at creation time and the reported
            # Value has an independent expectation — gated in radians against
            # Application.AngleTolerance, read at runtime. What the offline
            # gate cannot settle is whether Revit reports the sweep of the arc
            # we passed or its supplement; the witness makes that LOUD on the
            # first live run instead of returning a plausible angle.
            obligations=(
                ob("angular dimension exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("belongs to in_view (topology)",
                   KIND_TOPOLOGY, (".OwnerViewId", ".View"), key="in_view"),
                ob("References match requested refs (topology)",
                   KIND_TOPOLOGY, (".References",), key="references"),
                ob("measured angle equals the sweep of the arc built from "
                   "those references (geometry)",
                   KIND_GEOMETRY, (".Value",), key="value"),
            ),
        ),
        OpRefinementSpec(
            op="create_tag",
            materializer=("IndependentTag.Create",),
            witness_source="model",
            obligations=(
                ob("tag exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("belongs to in_view (topology)",
                   KIND_TOPOLOGY, (".OwnerViewId", ".View"), key="in_view"),
                ob("TaggedLocalElementId == target (semantic)",
                   KIND_SEMANTIC,
                   ("TaggedLocalElementId", "GetTaggedLocalElementIds"),
                   key="target_bound"),
                ob("tag head at `at` reproduced in view-space (geometry)",
                   KIND_GEOMETRY, ("TagHeadPosition",), key="head_at"),
            ),
        ),
        # wave/detail (09.08). The witness is STRONGER than for the rest of
        # the annotation, and this is a property of the element itself: a
        # filled region has SOMETHING to read back —
        # `GetBoundaries()` returns the curves of the BUILT boundary, not an
        # echo of the argument. So the geometric obligation here is not a
        # bounding-box one: every authored edge must be found exactly once
        # by its own endpoints AND midpoint, and the number of loops and
        # edges must match.
        OpRefinementSpec(
            op="create_filled_region",
            materializer=("FilledRegion.Create",),
            witness_source="model",
            obligations=(
                ob("filled region exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("belongs to in_view (topology)",
                   KIND_TOPOLOGY, (".OwnerViewId", ".View"), key="in_view"),
                ob("GetTypeId == the resolved filled region type (semantic)",
                   KIND_SEMANTIC, (".GetTypeId",), key="region_type"),
                ob("GetBoundaries reproduces the authored loops in view space "
                   "— loop count, curve count and every edge matched by its "
                   "endpoints and mid-point (geometry)",
                   KIND_GEOMETRY, ("GetBoundaries",), key="boundary"),
            ),
        ),
        OpRefinementSpec(
            op="create_text",
            materializer=("TextNote.Create",),
            witness_source="model",
            obligations=(
                ob("text note exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("belongs to in_view (topology)",
                   KIND_TOPOLOGY, (".OwnerViewId", ".View"), key="in_view"),
                ob("content matches (semantic)",
                   KIND_SEMANTIC, (".Text",), key="content"),
                ob("at reproduced in view-space (geometry)",
                   KIND_GEOMETRY, (".Coord",), key="at"),
                ob("width_mm honored when given (geometry)",
                   KIND_GEOMETRY, (".Width",),
                   param="width_mm", conditional=True, key="width"),
                # 🔴 ONE KEY FOR TWO AXES — MEASURED 22.08.2026, AND NEITHER
                # OF THE TWO CARRIERS IS LYING. The dispute was this: the
                # obligation is declared kind `semantic`, while the
                # witness's message ends in `(geometry)`, meaning
                # `_unwitnessed_axes` counts the semantics as declared, and
                # `_axes_from_violations` colors the geometry red. It is
                # resolved not by picking a side but by READING THE EMITTED
                # CODE (`authoring._emit_text`, 5754-5771): under this ONE
                # key stand TWO independent flags and TWO independent
                # `__post.Add` calls:
                #
                #   __leaderTargetVisible -> «leader target not visible in
                #       view (semantic, VIEW-BINDING LAW)» — whether the
                #       TARGET element is visible in the view:
                #       `__ltel.get_BoundingBox(__vw) != null`;
                #   __leaderOk            -> «leader endpoint does not match
                #       target (geometry)» — whether the leader's END landed
                #       within U(10.0) of the target's bounding-box center.
                #
                # Both markers are already listed right here, one line
                # below: the record itself KNOWS there are two things, and
                # folds them into one kind, because `Obligation` has one
                # kind. Each carrier is right about ITS OWN half; what is
                # wrong is the COLLAPSE.
                #
                # A COST THAT WAS MEASURED, NOT ESTIMATED. It does not
                # affect the axis instrument: `_unwitnessed_axes(["create_
                # text"]) == {}` under either choice of kind, because the op
                # already declared the geometry via the `at`/`width` keys,
                # and the semantics via `content`. The real hole is in the
                # PROOF: discharge happens PER KEY, there is one key, so
                # cutting out just the `__leaderOk` line alone leaves the
                # certificate PROVEN — the geometric half of the promise is
                # not protected by the mutation law (L6) at all.
                #
                # FIXED AS A PAIR, NOT HERE: `authoring._emit_text` must
                # emit TWO `WitnessCheck`s (`leader_visible` with the
                # `__leaderTargetVisible` flag and `leader_endpoint` with
                # `__leaderOk`), and by the same move two obligations arise
                # here — `semantic` and `geometry`. They cannot be separated
                # alone: an obligation without its own key gives «no witness
                # check with key» on EVERY text with a leader, that is, a
                # false red on 809 operations of a real building.
                # `authoring.py` is a file foreign to this wave.
                ob("leader target visible when given (semantic); ЕГО ЖЕ ключом "
                   "разряжается геометрическая половина — конец выноски у "
                   "центра габарита цели (см. комментарий выше: свёртка двух "
                   "осей в один ключ, чинится парой с authoring._emit_text)",
                   KIND_SEMANTIC, ("__leaderTargetVisible", "__leaderOk"),
                   param="leader_to", conditional=True, key="leader"),
            ),
        ),
        OpRefinementSpec(
            op="create_beam",
            materializer=("NewFamilyInstance",),
            witness_source="model",
            obligations=(
                ob("beam exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("LocationCurve endpoints == p0/p1 3D (geometry)",
                   KIND_GEOMETRY, _ENDPOINTS, key="endpoints"),
                # It used to be «reference level == resolved level».
                # Measured on 27.07: Revit DERIVES the beam's reference
                # level from the curve's elevation (L_01 @ 0 was passed, the
                # curve at Z=3000 -> bound to L_01ДОО1_+2.500). The
                # obligation demanded something the API does not promise,
                # and it was rolling back a correct beam. The invariant that
                # actually holds: a reference level exists; which one
                # exactly is read into the witness.
                ob("опорный уровень существует; какой — читается в свидетель (topology)",
                   KIND_TOPOLOGY, ("INSTANCE_REFERENCE_LEVEL_PARAM",),
                   key="reference_level"),
                ob("StructuralType == Beam (semantic)",
                   KIND_SEMANTIC, ("StructuralType.Beam",), key="structural_type"),
            ),
        ),
        OpRefinementSpec(
            op="create_foundation",
            # variety=isolated -> NewFamilyInstance; variety=slab -> Floor.Create
            # / NewFloor.  ANY of the three proves the op materialized on its
            # branch (only one path is emitted per op instance).
            materializer=("NewFamilyInstance", "Floor.Create", "NewFloor"),
            witness_source="model",
            obligations=(
                ob("footing/slab exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                # isolated -> LocationPoint==xy; slab -> bbox extents.  ANY of
                # the two proves the geometry clause on the emitted branch.
                ob("isolated LocationPoint == xy OR slab bbox extents "
                   "== outline extents (geometry)",
                   KIND_GEOMETRY, _LOCATION_POINT + _BBOX, key="footprint"),
                # FOOTPRINT SHAPE — ONLY FOR THE `slab` BRANCH, and the
                # conditionality is expressed the SAME way as for the
                # opening variants: the branch is distinguished by the
                # parameter's PRESENCE. The slab carries `outline`, the
                # isolated footing carries `xy`, and for it the shape
                # evidence is the LocationPoint, already witnessed by the
                # clause above. An unconditional obligation here would
                # declare UNPROVABLE something the isolated branch never
                # has — and under KUKAI_IR_TRANSLATION_CERT=refuse a live
                # recording would refuse with KIR-R001 for no reason.
                ob("slab variety: sketch loop count and per-loop vertex "
                   "multiset == outline plus holes on the canon grid "
                   "(geometry)",
                   KIND_GEOMETRY,
                   ("GetDependentElements", "__KirCanonUnit"),
                   param="outline", conditional=True,
                   key="slab_loops"),
                ob("base level == resolved level (topology)",
                   KIND_TOPOLOGY, _LEVEL_BIP + _BBOX, key="level_binding"),
                ob("StructuralType==Footing (isolated) OR structural "
                   "flag forced (slab) (semantic)",
                   KIND_SEMANTIC,
                   ("StructuralType.Footing", "FLOOR_PARAM_IS_STRUCTURAL",
                    "get_BoundingBox"), key="structural_type"),
            ),
        ),
        # wave/wall-foundation (2026-08-09): a strip footing. There is no
        # version axis — WallFoundation.Create is identical across all six
        # (measured 09.08).
        OpRefinementSpec(
            op="create_wall_foundation",
            materializer=("WallFoundation.Create",),
            witness_source="model",
            obligations=(
                ob("wall foundation exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                # TOPOLOGY WITHOUT TOLERANCE. The only real obligation of
                # this operation: the element is read back from the
                # document and names its own wall. There is no number here
                # and none can exist — this is an id equality, not a
                # measurement.
                ob("WallId == host wall id (topology, exact equality)",
                   KIND_TOPOLOGY, (".WallId",), key="host_wall"),
                ob("GetTypeId == requested wall foundation type (semantic)",
                   KIND_SEMANTIC, ("GetTypeId",), key="element_type"),
            ),
        ),
        # wave/framing (2026-08-09): a beam system. There is no version
        # axis — all four BeamSystem.Create overloads are identical across
        # the six (measured 09.08).
        OpRefinementSpec(
            op="create_beam_system",
            materializer=("BeamSystem.Create",),
            witness_source="model",
            obligations=(
                ob("beam system exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                # Bounding box by VERTICES on both sides: the C# side sees
                # only the curve endpoints of the read-back profile. What
                # remains outside is named in `post` and analyzed in the
                # emitter's header.
                ob("re-read Profile vertex bbox == lowered-edge vertex bbox "
                   "(geometry)", KIND_GEOMETRY, (".Profile",),
                   key="profile_bbox"),
                # PROFILE SHAPE alongside its bounding box: the evidence
                # was already being read (walking every curve, both ends)
                # and was being discarded by collapsing it into four
                # numbers.
                ob("profile loop vertex multiset == authored profile "
                   "on the canon grid (geometry)",
                   KIND_GEOMETRY, (".Profile", "__KirCanonUnit"),
                   key="profile_loops"),
                ob("GetBeamIds is non-empty — Revit actually laid framing "
                   "(semantic)", KIND_SEMANTIC, ("GetBeamIds",),
                   key="beams_laid"),
                ob("BeamSystem.Level == resolved level (topology)",
                   KIND_TOPOLOGY, (".Level",), key="level_binding"),
                ob("BeamType == resolved symbol (semantic)",
                   KIND_SEMANTIC, (".BeamType",), key="beam_type"),
            ),
        ),
        # wave/reinforcement (2026-08-10): area reinforcement. There is no
        # version axis — both AreaReinforcement.Create overloads are
        # identical across all six (measured 10.08 on :52412). No
        # tolerance at all: every obligation of this operation is an id
        # equality and a count.
        OpRefinementSpec(
            op="create_area_reinforcement",
            materializer=("AreaReinforcement.Create",),
            witness_source="model",
            obligations=(
                ob("area reinforcement exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                # TOPOLOGY WITHOUT TOLERANCE: the element is read back from
                # the document and names its own host. There is no number
                # here and none can exist.
                ob("GetHostId == requested host id (topology, exact equality)",
                   KIND_TOPOLOGY, ("GetHostId",), key="host"),
                ob("GetTypeId == requested area reinforcement type (semantic)",
                   KIND_SEMANTIC, ("GetTypeId",), key="element_type"),
                # A CONDITIONAL obligation: Autodesk documents an empty
                # array as the CORRECT response when HostStructuralRebar is
                # off, so an unconditional "non-empty" would reject correct
                # behavior.
                ob("GetRebarInSystemIds is non-empty under "
                   "HostStructuralRebar (semantic)",
                   KIND_SEMANTIC,
                   ("GetRebarInSystemIds", "HostStructuralRebar"),
                   key="bars_laid"),
                ob("the bars' own GetTypeId == requested bar type (semantic)",
                   KIND_SEMANTIC, ("RebarInSystem", "GetTypeId"),
                   key="bar_type"),
            ),
        ),
        # wave/framing (2026-08-09): a truss. One signature for six
        # versions.
        OpRefinementSpec(
            op="create_truss",
            materializer=("Truss.Create",),
            witness_source="model",
            obligations=(
                ob("truss exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("LocationCurve endpoints == p0/p1 in plan (geometry)",
                   KIND_GEOMETRY, _ENDPOINTS, key="endpoints"),
                ob("both endpoint elevations == the level's own plane "
                   "(geometry)", KIND_GEOMETRY, _ENDPOINTS,
                   key="base_elevation"),
                ob("GetTypeId == requested truss type (semantic)",
                   KIND_SEMANTIC, ("GetTypeId",), key="element_type"),
                ob("Members is non-empty — Revit derived chords and webs "
                   "(semantic)", KIND_SEMANTIC, (".Members",),
                   key="members_derived"),
                # EXISTENCE, NOT EQUALITY — the same lesson as with
                # create_beam (measured 27.07: requiring equality was
                # rolling back correctly built beams).
                ob("reference level link is REAL (topology)",
                   KIND_TOPOLOGY, ("TRUSS_ELEMENT_REFERENCE_LEVEL_PARAM",),
                   key="reference_level"),
            ),
        ),
        OpRefinementSpec(
            # 🔴 THE THIRD OP WITH ITS OWN WHOLE-PROGRAM TEMPLATE, AND THE
            # FIRST ONE THAT WRITES NOT INTO `doc` (21.08.2026). The text is
            # parsed IN PIECES the same way as the flight of stairs and the
            # landing (`vacuity_partial`): it is deliberately unbalanced by
            # brackets, the frame is provided by `wrap_user_code`.
            #
            # WHAT IS UNUSUAL HERE FOR THE CERTIFICATE. Three of the five
            # obligations are discharged NOT via `__post.Add`, but via a
            # refusal, because they stand INSIDE THE FAMILY DOCUMENT — that
            # is, before a single element appears in the project. `__post`
            # rolls back the PROJECT's transaction; here there is nothing to
            # roll back, the refusal simply keeps the family from reaching
            # disk. The markers therefore point to the CHECK'S CODE, not to
            # the verdict line, and this is exactly the distinction
            # `Obligation` has `witness_markers` for, rather than "look for
            # __post.Add".
            op="author_family",
            materializer=("NewFamilyDocument", "FamilyCreate.NewExtrusion"),
            obligations=(
                ob("family exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                # DEPENDENCE ON THE ENVIRONMENT. The path is asked of Revit
                # rather than written as a literal, and the refusal names
                # the directory, every file name that was tried, and what
                # is actually in the directory.
                ob("template resolved from Application.FamilyTemplatePath, "
                   "and a missing template refuses naming the directory, "
                   "every candidate filename tried and the .rft files "
                   "actually present",
                   KIND_SEMANTIC, ("FamilyTemplatePath",), key="template"),
                # CLOSING THE DOCUMENT IS NOT HYGIENE, IT IS A
                # POSTCONDITION. An unclosed family document hangs in
                # Revit's memory until the end of the session (live refusal
                # #4, 21.08), meaning a program that "successfully" refused
                # would leave a trace — exactly what zero-trace forbids for
                # every other op.
                ob("the family document is closed via Close(false) in a "
                   "finally on every exit path",
                   KIND_SEMANTIC, ("Close(false)",), key="family_doc_closed"),
                # 🔴 THIS OP'S MAIN OBLIGATION, AND IT IS A MEASUREMENT, NOT
                # A FIELD READ. The marker is THE DOUBLING ARITHMETIC ITSELF
                # (`2.0 * __v1_`), and it exists ONLY in the guard. Taking
                # the API's name as the marker
                # (`AssociateElementParameterToFamilyParameter`) would mean
                # proving that the call was WRITTEN — while a measurement on
                # 21.08 showed exactly the opposite: the call can be written
                # and still fail, and that fails completely silently. The
                # same lesson `create_stairs` paid for with the `__actR`
                # marker instead of `DesiredRisersNumber`.
                ob("the body FLEXES: doubling the family parameter doubles "
                   "the extrusion volume — ratio 2.0 within a derived "
                   "tolerance, then the value is restored and the volume "
                   "re-checked; an unbound parameter rolls the whole program "
                   "back and never reaches disk",
                   KIND_GEOMETRY, ("2.0 * __v1_",), key="flex_ratio"),
                ob("loaded family name and symbol name equal what the author "
                   "asked",
                   KIND_SEMANTIC, (".Name != ",), key="authored_names"),
                # THE INSTANCE IS OPTIONAL, SO THE OBLIGATION IS
                # CONDITIONAL. Without `place_at` there MUST BE no witness:
                # the marker lives exactly in the placement branch, and its
                # appearance without the parameter is a finding.
                ob("the placed instance carries the volume measured inside "
                   "the family document",
                   KIND_GEOMETRY, ("__KirVol(__inst_",),
                   param="place_at", conditional=True,
                   key="instance_volume"),
                ob("the placed instance sits on the authored symbol",
                   KIND_TOPOLOGY, (".Symbol.Id.ToString() != ",),
                   param="place_at", conditional=True,
                   key="instance_symbol"),
            ),
        ),
        OpRefinementSpec(
            op="create_stairs",
            # TWO forms of a flight of stairs — TWO materializers, and
            # EITHER of them is enough (materializer: «ANY marker proves
            # the create call»). The form is chosen by the `spiral`
            # parameter, and exactly one of the two calls exists in the
            # emission of any single program.
            materializer=("CreateStraightRun", "CreateSpiralRun"),
            obligations=(
                ob("stairs exist (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("base/top level == resolved levels (topology)",
                   KIND_TOPOLOGY,
                   ("STAIRS_BASE_LEVEL_PARAM", "STAIRS_TOP_LEVEL_PARAM")),
                ob(">=1 run materialized (semantic)",
                   KIND_SEMANTIC, ("GetStairsRuns",)),
                ob("width_mm held when supplied (geometry)",
                   KIND_GEOMETRY, ("ActualRunWidth",),
                   param="width_mm", conditional=True),
                # 🔴 19.08: GEOMETRY AGAINST THE REFERENCE — THE THIRD AND
                # LAST OF THE MEASURED VERTICAL GAPS. The obligation above
                # reads where base/top level POINT; none of them read
                # WHETHER the flight of stairs ACTUALLY REACHES there. Nine
                # flights on 19.08 passed the witness green and overshot
                # the top by 995-1370 mm; 18.08 showed the same on the
                # benchmark — 1202 mm on 11 of 12 flights.
                #
                # WHOLE NUMBERS of risers are compared, not millimeters, so
                # there is no tolerance at all and no threshold had to be
                # invented.
                #
                # 🔴 THE MARKER IS `__actR`, NOT `DesiredRisersNumber`, AND
                # THIS WAS BOUGHT BY MUTATION: at first the API's name stood
                # as the marker — and cutting out the GUARD left the
                # certificate PROVEN, because the same name also appears in
                # the RECEIPT, and the receipt is emitted after the commit
                # and rolls nothing back. The obligation was discharged by a
                # place that checks nothing. `__actR_` lives ONLY in the
                # guard.
                ob("run reaches top_level: ActualRisersNumber does not exceed "
                   "DesiredRisersNumber (geometry)",
                   KIND_GEOMETRY, ("__actR",),
                   key="vertical_extent"),
                # The witness READS THE RESULT: the created flight's path is
                # read back via `GetStairsPath` and must contain an arc. It
                # does NOT check the center/radius/span — see the post
                # clause and its explanation in emit_stairs_program; that
                # relation is missing a MEASUREMENT, not a check.
                ob("spiral run path contains an Arc (geometry)",
                   KIND_GEOMETRY, ("GetStairsPath",),
                   param="spiral", conditional=True, key="spiral_path"),
            ),
        ),
        OpRefinementSpec(
            # THE STAIRS WAVE (10.08.2026). The second op with its OWN
            # whole-program template; the text is parsed IN PIECES the same
            # way as the flight of stairs (`vacuity_partial`), because it is
            # deliberately unbalanced by brackets — the frame is provided by
            # `wrap_user_code`.
            op="create_stairs_landing",
            materializer=("CreateSketchedLanding",),
            obligations=(
                ob("landing exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("GetStairs() == the requested stairs (topology)",
                   KIND_TOPOLOGY, (".GetStairs()",), key="owner_stairs"),
                ob("the landing appears in GetStairsLandings (topology)",
                   KIND_TOPOLOGY, ("GetStairsLandings",), key="in_landing_set"),
                ob("IsAutomaticLanding is false — the sketched factory was "
                   "asked for (semantic)",
                   KIND_SEMANTIC, ("IsAutomaticLanding",), key="sketched"),
                # The witness reads the RESULT: the boundary of the BUILT
                # landing, edge by edge, against the authored contour,
                # exported into C# as separate arrays.
                ob("GetFootprintBoundary reproduces the authored contour in "
                   "plan — curve count and every edge matched once by "
                   "endpoints and mid-point (geometry)",
                   KIND_GEOMETRY, ("GetFootprintBoundary",), key="boundary"),
                ob("fresh post-scope BaseElevation equals the normalized "
                   "integer riser multiple within the derived geometry "
                   "tolerance (geometry)",
                   KIND_GEOMETRY, ("BaseElevation",), key="elevation"),
            ),
        ),
        OpRefinementSpec(
            # THE STAIRS WAVE, THE SECOND FLIGHT (15.08.2026). The third op
            # with its OWN whole-program template; the text is parsed IN
            # PIECES the same way as the flight and the landing
            # (`vacuity_partial`), because it is deliberately unbalanced by
            # brackets — the frame is provided by `wrap_user_code`.
            op="create_stairs_run",
            materializer=("CreateStraightRun",),
            obligations=(
                ob("run exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("GetStairs() == the requested stairs (topology)",
                   KIND_TOPOLOGY, (".GetStairs()",), key="owner_stairs"),
                ob("the run appears in Stairs.GetStairsRuns (topology)",
                   KIND_TOPOLOGY, ("GetStairsRuns",), key="in_run_set"),
                # The witness reads the RESULT: the path of the BUILT
                # flight against the authored axis, in both traversal
                # directions.
                ob("GetStairsPath reproduces the authored axis endpoints in "
                   "plan within the derived tolerance (geometry)",
                   KIND_GEOMETRY, ("GetStairsPath",), key="path"),
                ob("fresh post-scope BaseElevation equals the stairs base "
                   "plus the normalized integer riser multiple within the "
                   "derived geometry tolerance (geometry)",
                   KIND_GEOMETRY, ("BaseElevation",), key="elevation"),
            ),
        ),
        OpRefinementSpec(
            # feat/native-groups: NewGroup builds the definition (guarded by
            # __Refuse on null); .Groups witnesses the placed instance count;
            # .Name witnesses the requested GroupType name.  Witnesses are
            # structural C# (NewGroup / .Groups / .Name), never message text.
            op="create_group",
            materializer=("NewGroup",),
            witness_source="model",
            obligations=(
                ob("group definition materialized (GroupType) or typed refusal",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("one placed group instance per placement offset "
                   "(PlaceGroup) (semantic)",
                   KIND_SEMANTIC, (".Groups",), key="instances"),
                ob("GroupType Name matches name when given (semantic)",
                   KIND_SEMANTIC, (".Name",),
                   param="name", conditional=True, key="name"),
                # 🔴 19.08: THE GEOMETRY AXIS OF THIS OPERATION WAS EMPTY,
                # AND THIS IS THE MOST EXPENSIVE EMPTINESS IN THE REGISTRY.
                # A rehearsal measurement across 180 live-benchmark
                # programs: 4220 declared operations unfold into 7206
                # elements, and 2986 of them are the contents of
                # `create_group.members` × `placements`. The tower's entire
                # frame (1822 beams, 2100 columns) is built via groups, and
                # under supervision there was only the COUNT of instances.
                #
                # Why the check is NOT vacuous, even though its neighbor
                # (`instances`) is almost a tautology. The positions of
                # member placements `k>0` are NOT SENT to Revit: the
                # emitter sends a single point `O0 + delta_k`, and where
                # each member ends up inside the copy is DERIVED by Revit
                # itself from the group definition. So the expected value is
                # derived from the program (the definition member's position
                # plus the offset), while the obtained value is read live —
                # the act of distinguishing is present, and the witness
                # cannot be cut out unnoticed (`test_group_positions.py`).
                ob("every member of every placement stands where the "
                   "definition member stands plus that placement's delta "
                   "(geometry) — a value Revit DERIVES, not one we send",
                   KIND_GEOMETRY, ("__gpSig",), key="member_positions"),
            ),
        ),
        OpRefinementSpec(
            # A curtain panel cell. The materializer is the ONLY call by
            # which Revit changes a cell's panel type; there is no "panel
            # created" here: the panel exists precisely because the cell
            # exists.
            #
            # The type witness reads the cell ANEW BY ITS ADDRESS after
            # Regenerate: ChangePanelType returns an element, and checking
            # against it would only prove that the call took place — exactly
            # the class of "call witness" this registry forbids.
            # A gridline is the ONLY constructor: AddGridLine.
            # The witness reads the CREATED gridline anew by its id after
            # Regenerate: membership in this grid's list of lines
            # (topology), IsUGridLine (semantic), and the distance from the
            # requested point to the FullCurve (geometry). The call's return
            # value does not count as a witness — it only proves that the
            # call took place.
            op="create_curtain_grid_line",
            materializer=("AddGridLine",),
            witness_source="model",
            obligations=(
                ob("grid line created or typed refusal (materialize)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("created line is a member of the host grid's U/V line "
                   "ids (topology)",
                   KIND_TOPOLOGY, ("__gMem",), key="grid_membership"),
                ob("IsUGridLine == requested direction (semantic)",
                   KIND_SEMANTIC, (".IsUGridLine",), key="direction"),
                ob("requested position lies on FullCurve within tolerance "
                   "(geometry)",
                   KIND_GEOMETRY, ("__gDist",), key="position_mm"),
            ),
        ),
        OpRefinementSpec(
            op="set_curtain_panel",
            materializer=("ChangePanelType",),
            witness_source="model",
            obligations=(
                ob("cell (u,v) resolved or typed refusal (materialize)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("effective panel type in cell (u,v) == panel_type, "
                   "re-read by address (semantic)",
                   KIND_SEMANTIC, ("__ccEffType",), key="panel_type"),
                ob("cell host == host (topology)",
                   KIND_TOPOLOGY, (".Host",), key="cell_host"),
            ),
        ),
        # ── the datum wave (09.08.2026) ────────────────────────────────
        OpRefinementSpec(
            op="create_multi_segment_grid",
            materializer=("MultiSegmentGrid.Create",),
            witness_source="model",
            obligations=(
                ob("chain exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                # TWO DIFFERENT OBLIGATIONS, NOT ONE. The number of grid
                # lines and their coordinates fail differently: a chain can
                # assemble from the right number of links in the wrong
                # place, and conversely, some endpoints can coincide while a
                # link is lost. One obligation for both facts would miss
                # exactly the half that broke.
                ob("one Grid per path segment: GetGridIds count == segments "
                   "(geometry)",
                   KIND_GEOMETRY, ("GetGridIds",), key="segment_count"),
                ob("every authored segment matched by a created Grid's own "
                   "Curve endpoints, each Grid used once (geometry)",
                   KIND_GEOMETRY, ("GetEndPoint",), key="endpoints"),
            ),
        ),
        OpRefinementSpec(
            op="create_extrusion_roof",
            materializer=("NewExtrusionRoof",),
            witness_source="model",
            obligations=(
                ob("extrusion roof exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                # A read-back FROM THE DOCUMENT, rather than trusting the
                # return value's static type: `NewExtrusionRoof` is declared
                # as returning ExtrusionRoof, and an obligation resting on
                # that would prove the C# signature, not the construction.
                ob("re-read from the document casts to ExtrusionRoof "
                   "(semantic)",
                   KIND_SEMANTIC, ("as ExtrusionRoof",), key="element_class"),
                ob("ROOF_BASE_LEVEL_PARAM == resolved level (topology)",
                   KIND_TOPOLOGY, ("ROOF_BASE_LEVEL_PARAM",),
                   key="base_level"),
                # The bounding box is measured ALONG THE WORK PLANE'S
                # NORMAL, not along the world axes: the normal is
                # horizontal but arbitrary, and a world-axis bbox would mix
                # the extrusion's run with the profile's span.
                ob("solid extent along the work plane normal spans "
                   "[start_mm, end_mm] from the plane (geometry)",
                   KIND_GEOMETRY, ("DotProduct",), key="extrusion_extent"),
            ),
        ),
        OpRefinementSpec(
            op="create_multistory_stairs",
            materializer=("MultistoryStairs.Create",),
            witness_source="model",
            obligations=(
                ob("multistory stairs exist (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                # ONE obligation for the whole op, and this is not poverty:
                # the op has EXACTLY ONE observable outcome — the set of
                # levels — and it is checked by EXACT equality, without
                # tolerance. Splitting it into "was created" and "was
                # connected" would mean introducing an obligation that
                # cannot fail on its own.
                ob("GetAllConnectedLevels re-read equals the resolved levels "
                   "set exactly (topology)",
                   KIND_TOPOLOGY, ("GetAllConnectedLevels",),
                   key="connected_levels"),
            ),
        ),
    ]
    return {spec_.op: spec_ for spec_ in specs}


def _hosted_obligations(noun: str) -> tuple[Obligation, ...]:
    ob = Obligation
    return (
        ob(f"{noun} exists (materialized or typed refusal)",
           KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
        ob("Host.Id == host wall id (topology)",
           KIND_TOPOLOGY, (".Host",), key="host"),
        ob("LocationPoint == offset placement at level+sill (geometry)",
           KIND_GEOMETRY, _LOCATION_POINT, key="location"),
        # audit F5: swing/mirror state — same conditional markers as
        # place_family; every emitted check carries its own __post.Add in the
        # marker span (verdict-span rule).
        ob("mirrored state == requested when given (semantic)",
           KIND_SEMANTIC, (".Mirrored != ",),
           param="mirrored", conditional=True, key="mirrored"),
        ob("hand flip state == requested when given (semantic)",
           KIND_SEMANTIC, (".HandFlipped != ",),
           param="hand_flipped", conditional=True, key="hand_flipped"),
        ob("facing flip state == requested when given (semantic)",
           KIND_SEMANTIC, (".FacingFlipped != ",),
           param="facing_flipped", conditional=True, key="facing_flipped"),
    )


def _network_obligations(diameter_bip: str,
                         with_slope: bool = False,
                         with_level: bool = False) -> tuple[Obligation, ...]:
    ob = Obligation
    # A HOLE CLOSED ON 09.08.  `level` for network ops is MANDATORY and
    # travels as the fourth argument straight into
    # `Pipe.Create`/`Duct.Create` — that is, it is an authoring degree of
    # freedom that WE hold.  At the same time, `acceptance._LEVEL_FROM_PARAM`
    # already counted all three network ops among those for which "the
    # result's level equals the resolved selector", and built a post-commit
    # census on that basis: the judge rested on an assertion no witness ever
    # read.  The standalone `create_pipe`/`create_duct` have read the SAME
    # `RBS_START_LEVEL_PARAM` since 21.07, and they carry NO "level binding"
    # violations: all 35 in the corpus belong to ops where Revit DERIVES the
    # level (create_beam 29, create_floor 5) — re-checked on 17.08.2026 on a
    # 2172-record corpus, the number did not move.
    # 🔴 The tally "3434 and 215 live builds, zero accusations" is WITHDRAWN
    # from here: an artifact of an unfixed `tally()` (the retraction is in
    # `kir/CLAUDE.md`).
    # Today the same ops read 377/1 and 43/7. This does not affect the
    # conclusion: it rests on the ATTRIBUTION of violations, not on the
    # count of builds.
    level = (
        ob("each segment's reference level == the resolved level (topology)",
           KIND_TOPOLOGY, ("RBS_START_LEVEL_PARAM",), key="reference_level"),
    ) if with_level else ()
    slope = (
        # A DRIFT CLOSED ON 03.08.  `route_*.post` promises KIR-X004
        # ("a segment with slope_min_pct holds its slope or the program
        # rolls back"), the emitter installs an ACTUAL witness
        # (route_mep.emit_slope_witness_cs), and there was no obligation in
        # the table at all: removing the witness left the certificate
        # PROVEN.  audit_registry_coverage() missed this because it checks
        # prose by SHARED WORDS — the word "segment" occurs for both the
        # diameter and the connectivity.  It is caught only by mutation (cut
        # the witness out -> `proven` must fail), and that is exactly how it
        # is now checked — tests/test_tolerance_provenance.py.
        ob("a segment carrying slope_min_pct holds it or the program rolls "
           "back (geometry, KIR-X004)",
           KIND_GEOMETRY, ("__slc",), param="__slope_reqs__",
           conditional=True, param_truthy=True, key="slope"),
    ) if with_slope else ()
    return (
        ob("segments materialized or typed refusal (materialize)",
           KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
        ob("each segment LocationCurve == node coords (geometry)",
           KIND_GEOMETRY, _ENDPOINTS, key="endpoints"),
        # Was "all segments in one MEPSystem (semantic)" until 2026-07-27.
        # Revit DERIVES system membership from the connector graph at commit
        # (measured — connect.py §A), so no in-transaction check can discharge
        # it; the emitter used to force membership with NewPipingSystem and
        # that call is what made the four graph ops unbuildable. The clause
        # the emitter really can prove before commit is connectivity — the
        # CONNECT signal the spec itself names — and it is proven by a BFS
        # over the live connector graph (`Connector.AllRefs`). System identity
        # is now READ BACK after commit and reported, never asserted here.
        ob("connector-graph BFS reaches every segment (topology)",
           KIND_TOPOLOGY, (".AllRefs",), key="connectivity"),
        # The segment's diameter: the emitter INSTALLS this check
        # (`_network_geometry_post`: «segment N diameter (semantic)»), and
        # the certificate did not know about it — the `diameter_bip`
        # argument was accepted and never used. That means removing the
        # check from the emitter left the certificate "proven": exactly the
        # hole the certificate was set up to close.
        #
        # The marker is the BuiltInParameter itself — it is also what
        # distinguishes the domains (RBS_PIPE_DIAMETER_PARAM for a pipe,
        # RBS_CURVE_DIAMETER_PARAM for a duct), so substituting one for the
        # other also stops being unnoticeable.
        ob("each declared segment diameter is read back (semantic)",
           KIND_SEMANTIC, (f"BuiltInParameter.{diameter_bip}",),
           key="diameter"),
    ) + level + slope


# Some obligation constructors are referenced before their def at class-body
# eval time; Python resolves them at call time, so define the table lazily.
REFINEMENT: dict[str, OpRefinementSpec] = {}


def _ensure_table() -> dict[str, OpRefinementSpec]:
    global REFINEMENT
    if not REFINEMENT:
        REFINEMENT = _refinement_specs()
    return REFINEMENT


# ---------------------------------------------------------------------------
# Certification
# ---------------------------------------------------------------------------


def _value_carries_kind(op, field: str, kind: str) -> bool:
    """Whether the `field` parameter's value carries the `kind`.

    Reads the LOWERED region (`__region__`), not the authored one: the
    spline's kind lives in the lowered edge's shape, and asking the authored
    record would mean introducing a SECOND carrier of the same knowledge — a
    named defect of this tree. If there is no lowering (the certificate is
    called before grounding), we answer "no": a gate must relax the
    requirement only for a PROVEN reason.
    """
    if kind != "spline":
        raise CertificateSchemaError(
            f"затвор по роду: род {kind!r} не известен сертификату")
    region = op.get("__region__") if isinstance(op, dict) else None
    if not isinstance(region, dict):
        return False
    from kir import contour as _contour
    rings = [region.get("outer") or []] + list(region.get("holes") or [])
    return any(_contour.is_spline(b)
               for ring in rings for _p0, _p1, b in (ring or []))


def _op_present(op: dict, param: str, truthy: bool = False) -> bool:
    """Whether a gating param is genuinely present on this op instance.

    Presence is by key AND (for booleans) any value: place_family always
    carries mirrored/hand/facing keys only when the IR set them, and the
    emitter keys its witness on ``has_<flag> = "<flag>" in op`` — so key
    presence is the correct, emitter-aligned test.
    """

    if param not in op or op[param] is None:
        return False
    # `truthy` distinguishes "the key is present" from "it was requested"
    # for containers — see Obligation.param_truthy.
    return bool(op[param]) if truthy else True


def _not_required_because(obligation: Obligation,
                          deleted_by: str | None = None) -> str:
    """Human-readable reason a NOT-required obligation's gate resolved that
    way — either the ordinary ``conditional``/``param`` shape (required only
    when ``param`` IS present) or the inverse ``unless_param`` shape
    (required only when ``unless_param`` is ABSENT)."""

    if deleted_by is not None and obligation.block == BLOCK_POST:
        return (f"элемент законно удалён опом {deleted_by!r} ТОЙ ЖЕ программы "
                "— финальных свидетелей у него нет, а отсутствие "
                "свидетельствует удаляющий оп (названное отсутствие)")
    if obligation.unless_kind_in is not None:
        field, kind = obligation.unless_kind_in
        return (f"параметр {field!r} несёт род {kind!r} — обязательство "
                f"НЕ ПРЕДЪЯВЛЯЕТСЯ (названное отсутствие, а не провал)")
    if obligation.when_kind_in is not None:
        field, kind = obligation.when_kind_in
        return (f"параметр {field!r} НЕ несёт рода {kind!r} — обязательство "
                f"не предъявляется, потому что предъявлять его не к чему")
    if obligation.unless_param is not None:
        return f"for present param {obligation.unless_param!r}"
    return f"for absent param {obligation.param!r}"


def certify_op(
    op: dict, version: str, *, stamp: str = "kir:cert",
    rewritten_by_tail: frozenset = frozenset(), deleted_by: str | None = None,
) -> OpCertificate:
    """Statically certify one grounded op's emission refines its OpSpec.post.

    🔴 THE PROGRAM'S TAIL ARRIVES AS A PARAMETER, IT IS NOT RECOMPUTED HERE
    (E-4, 08.09.2026). `rewritten_by_tail` is the set of this op's obligation
    keys that were legally rewritten LATER in the program by `set_param`;
    `deleted_by` is the id of the op that legally deleted this element. Both
    are computed by ONE law, `emit_core.program_tail_writes`, and it is
    called by `certify_program` — the same one `authoring.emit_program`
    calls. A second computation here would be a second opinion on the same
    fact and would silently diverge from the emission: the certificate
    checks the stage STRICTLY and would declare unprovable exactly what the
    emitter itself printed.

    The default is an empty tail, so a solo `certify_op(op, ver)` call (the
    way tests and instruments call it) behaves verbatim as before.
    """

    table = _ensure_table()
    op_name = op["op"]
    if op_name not in table:
        raise CertificateSchemaError(
            f"{op_name}: no OpRefinementSpec (registry op not certifiable)")
    ref = table[op_name]

    model_checks: "list | None" = None
    operation_code = ""
    if op_name in spec.SOLO_OPS:
        # Sole-op program with its own template (not in _EMITTERS).  Parse the
        # whole emitted program as one blob for materializer + post witnesses;
        # its postconditions are the same __post.Add pattern.  The template is
        # taken FROM THE TABLE, not by name: since 10.08.2026 there have been
        # two such ops, and `if op_name == "create_stairs"` would have
        # silently sent the landing into the shared `_EMITTERS` branch, where
        # it does not exist at all.
        from kir.authoring import _SOLO_PROGRAMS
        program = _SOLO_PROGRAMS[op_name](op, version)
        create_code = post_code = _code(program)
    else:
        decl, create, post, _readback = _EMITTERS[op_name](op, version, stamp)
        create_code = _code(create)
        if isinstance(post, BarePost):
            post = list(post.checks)
        if isinstance(post, (list, tuple)):
            # Wave A2 model post: the emitter handed over WitnessCheck objects.
            if ref.witness_source != "model":
                raise CertificateSchemaError(
                    f"{op_name}: emitter returns a model post but the "
                    "refinement spec still declares witness_source='string' "
                    "— update REFINEMENT in the same migration step")
            # THE SAME HELPER AS IN `emit_program`: what is proved is
            # exactly the text that will go to Revit — with the stage
            # lifted for a rewritten parameter, and without final witnesses
            # for a deleted element.
            model_checks = list(restage_for_program_tail(
                post, rewritten_by_tail, deleted_by))
            operation_rendered, final_rendered = render_tail_adjusted_post(
                op["id"], post, rewritten_by_tail, deleted_by)
            operation_code, post_code = _code(operation_rendered), _code(final_rendered)
        else:
            if ref.witness_source == "model":
                raise CertificateSchemaError(
                    f"{op_name}: refinement spec declares witness_source="
                    "'model' but the emitter returned a string post")
            post_code = _code(post)

    materialized = any(m in create_code for m in ref.materializer)
    refusal_guarded = (
        not ref.refuse_on_null
        or any(m in create_code for m in _REFUSE)
    )

    model_keys = (
        {check.obligation_key for check in model_checks}
        if model_checks is not None else None)

    # VACUITY (09.08): the key proves that a `__post.Add` LINE exists, not
    # that it is reachable.  The mutation `if (false) __post.Add("never")`
    # left the certificate proven — see the long comment at
    # analyze_witness_cs, including the honest list of what this analysis
    # does NOT see.
    vacuous, partial = witness_vacuity(op_name, model_checks, operation_code + post_code)
    dead_keys = {f.obligation_key for f in vacuous
                 if f.obligation_key is not None}

    verdicts: list[ClauseVerdict] = []
    for obligation in ref.obligations:
        if obligation.kind == KIND_MATERIALIZE:
            # Materialize obligations are proven by the create-side refuse
            # guard; recorded as a clause so the ledger is complete.
            #
            # 🔴 WHAT WAS MEASURED HERE ON 23.08.2026, BEFORE FIXING IT. There
            # are SEVENTY-FOUR `materialize` clauses in the table, and all
            # seventy-four were discharged by THE SAME THING — "the
            # constructor is present in the code, `__Refuse` is present next
            # to it". Not one of them asked a witness. For an emitter that
            # emits the constructor itself, this is a control that is green
            # BY CONSTRUCTION — this house's named form, already paid for six
            # times by this day.
            #
            # WHY IT WAS NOT TORN DOWN ENTIRELY. For most ops, "the element
            # exists" is checked NOT by a separate witness, but by the fact
            # that every other witness reads an object read back from the
            # model and stays silent only when it is alive. Demanding a
            # separate key from all 74 would mean rewriting the emission
            # corpus for the sake of formal uniformity.
            #
            # WHAT WAS DONE INSTEAD. A key on the `materialize` clause
            # stopped being a dead label: **declare the key — you are held to
            # it by a witness**. An op that genuinely reads its own creation
            # back from the model says so with a key, and the certificate
            # holds it to its word; for the 73 keyless neighbors, behavior
            # does NOT CHANGE by one bit.
            #
            # This was found not by reasoning but by the law L6
            # (`test_tolerance_provenance`) — and found A DAY LATER than it
            # could have been: the file failed to build because of a solo op
            # with no sample. The second time in two days. A red for a known
            # reason hides the next one.
            key = obligation.key
            key_ok = True
            key_reason = ""
            if key is not None:
                if model_keys is None:
                    raise CertificateSchemaError(
                        f"{op_name}: клауза {obligation.clause!r} объявила "
                        f"ключ {key!r}, но оп не сертифицируется по модели — "
                        "спросить свидетеля не у кого, и ключ был бы мёртвой "
                        "пометкой")
                present = key in model_keys
                dead = key in dead_keys
                key_ok = present and not dead
                key_reason = (
                    f" + свидетель {key!r} есть" if key_ok else
                    f" + свидетель {key!r} ВАКУУМЕН" if present else
                    f" + свидетеля с ключом {key!r} НЕТ")
            verdicts.append(ClauseVerdict(
                clause=obligation.clause,
                kind=obligation.kind,
                required=True,
                discharged=refusal_guarded and materialized and key_ok,
                matched_marker=(ref.materializer[0] if materialized else None),
                reason=(("materializer + __Refuse present"
                         if (materialized and refusal_guarded)
                         else "missing materializer or __Refuse") + key_reason),
            ))
            continue

        required = True
        if obligation.conditional:
            required = _op_present(
                op, obligation.param, obligation.param_truthy)
        # Not `elif`: two gates can stand on one obligation, and then the
        # witness is required only when BOTH are satisfied (see
        # `unless_param`).
        if obligation.unless_param is not None:
            required = required and not _op_present(
                op, obligation.unless_param)
        if obligation.unless_kind_in is not None:
            required = required and not _value_carries_kind(
                op, *obligation.unless_kind_in)
        if obligation.when_kind_in is not None:
            required = required and _value_carries_kind(
                op, *obligation.when_kind_in)

        if model_keys is not None and obligation.block in (BLOCK_POST, BLOCK_OPERATION):
            # Model path (A2): discharge by KEY.  A WitnessCheck cannot exist
            # without its __post.Add (unconstructible), so key-presence IS
            # verdict-presence — no span heuristics.
            if obligation.key is None:
                raise CertificateSchemaError(
                    f"{op_name}: obligation {obligation.clause!r} has no "
                    "model key but the op is model-certified")
            # 🔴 THE CONDITIONAL STAGE READS THE PROGRAM'S TAIL, RATHER THAN
            # ESTABLISHING A SECOND TRUTH ABOUT IT (E-4). A creation
            # obligation whose parameter was legally rewritten LATER is
            # proved by the OPERATION-stage witness — the same key, the same
            # predicate, the same tolerance. The check is NOT weakened: the
            # expected stage remains exactly one, it is simply now a
            # function of the program rather than of a single table row.
            if obligation.key in rewritten_by_tail:
                stage = "operation"
            else:
                stage = ("operation" if obligation.block == BLOCK_OPERATION
                         else "final")
            # An element legally deleted by THIS SAME program carries no
            # final witnesses at all: its absence is witnessed by the
            # deleting op (see `emit_core.restage_for_program_tail`).
            if deleted_by is not None and obligation.block == BLOCK_POST:
                required = False
            present = any(check.obligation_key == obligation.key and check.stage == stage
                          for check in model_checks)
            dead = obligation.key in dead_keys
            if required:
                if present and dead:
                    reason = (f"witness check {obligation.key!r} present but "
                              "VACUOUS — its __post.Add cannot execute")
                elif present:
                    reason = f"witness check {obligation.key!r} present"
                else:
                    reason = f"no witness check with key {obligation.key!r}"
                verdicts.append(ClauseVerdict(
                    clause=obligation.clause, kind=obligation.kind,
                    required=True, discharged=present and not dead,
                    matched_marker=obligation.key if present else None,
                    reason=reason))
            else:
                verdicts.append(ClauseVerdict(
                    clause=obligation.clause, kind=obligation.kind,
                    required=False, discharged=not present,
                    matched_marker=obligation.key if present else None,
                    reason=(f"свидетель законно отсутствует: "
                            f"{_not_required_because(obligation, deleted_by)}"
                            if not present else
                            f"spurious witness {obligation.key!r} "
                            f"{_not_required_because(obligation, deleted_by)}")))
            continue

        block_code = (create_code if obligation.block == BLOCK_CREATE else
                      operation_code if obligation.block == BLOCK_OPERATION else post_code)
        matched = next(
            (m for m in obligation.witness_markers if m in block_code), None)
        if not required:
            # Conditional clause whose param is absent: the witness must ALSO
            # be absent (no spurious check for a param that was not requested).
            discharged = matched is None
            reason = (f"свидетель законно отсутствует: "
                      f"{_not_required_because(obligation)}"
                      if discharged
                      else f"spurious witness {matched!r} "
                           f"{_not_required_because(obligation)}")
            verdicts.append(ClauseVerdict(
                clause=obligation.clause, kind=obligation.kind,
                required=False, discharged=discharged,
                matched_marker=matched, reason=reason))
            continue
        verdicts.append(ClauseVerdict(
            clause=obligation.clause,
            kind=obligation.kind,
            required=True,
            discharged=matched is not None,
            matched_marker=matched,
            reason=(f"witness {matched!r} present" if matched
                    else f"no witness among {obligation.witness_markers}"),
        ))

    # Wave A2: the verdict-span rule is GONE.  Every _EMITTERS op is
    # model-certified (a WitnessCheck cannot exist without its __post.Add —
    # the F3 class is unconstructible), and create_stairs, the sole string
    # blob, was always span-exempt.  Obligations discharge by KEY.

    return OpCertificate(
        op=op_name,
        version=version,
        materialized=materialized,
        refusal_guarded=refusal_guarded,
        clauses=tuple(verdicts),
        vacuous=vacuous,
        vacuity_partial=partial,
    )


def certify_program(
    grounded_ops: list[dict], version: str, *, intent: str = "",
) -> ProgramCertificate:
    """Certify every op of a grounded program (per-op; the program wrapper is
    constant, so the certificate composes from per-op certificates)."""

    tails = [program_tail_writes(grounded_ops, i)
             for i in range(len(grounded_ops))]
    return ProgramCertificate(
        version=version,
        ops=tuple(certify_op(op, version,
                             rewritten_by_tail=tail[0], deleted_by=tail[1])
                  for op, tail in zip(grounded_ops, tails)),
    )


def assert_refined(certificate: OpCertificate | ProgramCertificate) -> None:
    """Fail-closed: raise with every gap unless the certificate is proven.

    A vacuous witness raises the MORE SPECIFIC :class:`VacuousWitnessError`
    (a subclass, so existing catch sites keep working): "the check is missing"
    and "the check exists and cannot fire" are different defects and must not
    arrive under one name.
    """

    if certificate.proven:
        return
    error = (VacuousWitnessError if certificate.vacuous
             else UnprovenRefinementError)
    raise error(
        "translation certificate not proven:\n  "
        + "\n  ".join(certificate.gaps))


# ---------------------------------------------------------------------------
# Registry-coverage audit (table <-> spec.OPS biection)
# ---------------------------------------------------------------------------

# Ops handled outside the _EMITTERS table but still certifiable — the ops that
# own their transaction scope and therefore carry a WHOLE-PROGRAM template
# (`authoring._SOLO_PROGRAMS`).  The tuple is built FROM THE REGISTRY, not
# rewritten as a literal: the second such op (the landing, 10.08.2026) showed
# that a rewritten name is a second opinion on the same fact, and it drifts
# apart silently.
_EXTRA_CERTIFIABLE = frozenset(spec.SOLO_OPS)

# Some OpSpec.post clauses describe PLAN-stage / policy / emit-ordering /
# resolution behavior, NOT a post-commit runtime witness — so they cannot (and
# must not) be forced to map onto a __post.Add obligation.  Exemptions are
# EXPLICIT and carry a rationale: a clause is skipped by audit_registry_coverage
# only if it contains its op's exemption marker.  This keeps the biection honest
# (a genuinely-witnessable clause with no obligation still hard-fails) while not
# fabricating a fake witness for a non-runtime promise.  Format: op -> tuple of
# (distinguishing-substring, why-not-a-runtime-postcondition).
#
# ═══════════════════════════════════════════════════════════════════════════
# 🔴 A ROW OF THIS TABLE HAS THREE DIFFERENT ROLES, AND BEFORE 22.08.2026 THEY
# WERE ONE.
# ═══════════════════════════════════════════════════════════════════════════
# MEASURED ON 22.08.2026 WITH THE `audit_clause_notes()` INSTRUMENT. 26
# entries across 18 ops. For FIVE of them the marker did not occur in ANY
# clause of its own op — as audit exemptions they were not working (there was
# nothing to exempt), while models were still being presented via
# `named_absences`, because that one returns a string without asking whether
# the clause is alive. Analyzing each of the five gave not "a stale marker"
# but THREE DIFFERENT ROLES:
#
#   EXEMPTION (`_exempt`) — the clause EXISTS in `post`, there is no
#       obligation and there should be none. The marker MUST occur in
#       exactly one clause. A dead marker here is a defect: the audit has
#       stopped exempting anything and stays silent about it.
#       21 of the 26 entries.
#   NAMED ABSENCE (`_absence`) — the clause DOES NOT EXIST in `post` AND
#       SHOULD NOT: the op deliberately makes no promise of this thing. The
#       marker must NOT occur in any clause; its occurrence would mean a
#       promise was introduced with no witness for it.
#       2 entries (`create_building_pad`, `create_site_subregion`).
#   CAVEAT (`_caveat`) — the obligation EXISTS, is discharged by a live
#       witness, and the entry names that witness's LIMIT (a one-sided
#       guard, a kind-of-value gate). The marker must NOT occur in the
#       clause, and the named key must EXIST among the op's obligations.
#       3 entries (`create_stairs`, `create_ceiling`, `create_floor_by_contour`).
#
# WHY THE ROLE IS THE THIRD TUPLE ELEMENT, NOT A SECOND TABLE. A separate
# dictionary `(op, marker) -> role` would be a SECOND CARRIER of the marker
# string, and fixing the marker in one place would silently drift apart from
# the other — exactly the defect this wave was set up to catch. There is
# ONE carrier: `_CLAUSE_NOTES`. `_NON_WITNESSABLE_CLAUSES` is its PROJECTION
# into the former pair (clause, why), because it is read by foreign files
# (`rehearsal.rehearse`, `course/shape.declared_boundaries`), and this wave
# must not change those.
#
# 🔴 WHAT THIS SEPARATOR DOES NOT FIX. Clause addressing remains BY
# SUBSTRING. The role only says which answer to "how many clauses are hit"
# is correct (1 / 0 / 0), and so a dead entry now TURNS RED instead of
# staying silent. Checking BY SUBJECT (a clause addressed by a key, not by
# text) is separate, substantial work; its cost and the measurement that
# justifies it are recorded at `audit_registry_coverage`.
NOTE_EXEMPT = "exempt"
NOTE_ABSENCE = "absence"
NOTE_CAVEAT = "caveat"
NOTE_ROLES = (NOTE_EXEMPT, NOTE_ABSENCE, NOTE_CAVEAT)

#: How the role is explained TO THE MODEL. `named_absences` glues this label
#: onto the reason, because to the receipt's reader all three states were
#: being presented with one phrase — "nobody looked here" — and for a
#: caveat that is A LIE: someone looked, just in one direction.
_ROLE_LABEL_RU = {
    NOTE_EXEMPT: "обещано, свидетеля нет и не будет",
    NOTE_ABSENCE: "НЕ ОБЕЩАНО ВОВСЕ — сюда никто не смотрел",
    NOTE_CAVEAT: "свидетель ЕСТЬ, названа его граница",
}


def _exempt(marker: str, why: str) -> tuple[str, str, str, str | None]:
    """The `post` clause exists; there is no obligation and there should be none."""

    return (marker, why, NOTE_EXEMPT, None)


def _absence(marker: str, why: str) -> tuple[str, str, str, str | None]:
    """The `post` clause DOES NOT EXIST: the op deliberately makes no promise of this thing."""

    return (marker, why, NOTE_ABSENCE, None)


def _caveat(key: str, marker: str, why: str) -> tuple[str, str, str, str | None]:
    """The `key` obligation exists and is alive; the entry names its LIMIT.

    The key is deliberately the FIRST argument: this way the role is
    recorded in one line at the opening parenthesis, and the long reason
    below stays untouched.
    """

    return (marker, why, NOTE_CAVEAT, key)


def _absence_why_ru(why: str, role: str, key: str | None) -> str:
    """The reason, PREFIXED BY THE ROLE — because one word used to cover three.

    🔴 WHAT THIS FIXES, WITH ADDRESSES. Entries of this table reach the
    model by THREE routes, and all three used to print one header for three
    different things:

      * `serving._witness_note_ru` — «🔴 СЮДА НИКТО НЕ СМОТРЕЛ»;
      * `course/shape.declared_boundaries` — «свидетель молчит»;
      * `rehearsal.rehearse` -> `serving` — the `will_not_be_checked.named` field.

    That is true for an exemption and for a named absence. For a CAVEAT it
    is a LIE: the witness exists and is discharged, only its limit is named
    (for `create_stairs` the guard is one-sided, for the ceiling and the
    contour-based floor the bounding box is closed off by a kind-of-value
    gate). Three of the 26 entries were being read by the model as
    "unchecked" while their witness was alive.

    The headers are printed by FOREIGN files, and they are not fixed here.
    What is fixed here is what belongs to this table — THE REASON ITSELF,
    and so the label reaches all three readers at once, without touching a
    single foreign file.
    """

    label = _ROLE_LABEL_RU.get(role)
    if label is None:
        return str(why)
    if role == NOTE_CAVEAT and key:
        return f"[{label}: {key}] {why}"
    return f"[{label}] {why}"


_CLAUSE_NOTES: dict[str, tuple[tuple[str, str, str, str | None], ...]] = {
    "create_type": (
        _exempt("foreign/ambiguous names refuse",
                "Creation-phase ownership/uniqueness guards and read-only reuse "
                "are enforced by the emitter and negative runtime branch tests. "
                "This post-value certificate does not prove absence of writes "
                "to an existing shared type; matching dimensions after a write "
                "would not establish that policy."),
        _exempt("existing type is not restamped",
                "An emission non-mutation policy, tested with setter counters. "
                "An unchanged observed stamp cannot prove that Set was never "
                "called. No independent model postcondition is claimed for "
                "absence of that call."),
    ),
    # 🔴 THE CIRCLE OF CONSEQUENCES OF MUTATION — SIX NAMED ABSENCES
    # (22.08.2026).
    #
    # For all six mutating ops the receipt spoke about the TARGET ITSELF,
    # while the effect lives in the NEIGHBORS. Part of the circle was taken
    # up by obligations that same day (for the move — the host's inserts
    # and the author's locks), the rest was REJECTED FOR ITS COST, and this
    # is that cost. Without these entries, `named_absences` is empty for
    # five of the mutating ops, meaning "the neighbors were not looked at"
    # would be indistinguishable from "there was nothing to look at".
    "move_elements": (
        _absence("rooms bounded by a moved element",
                 "обратного индекса «стена -> комнаты» у Revit НЕТ. "
                 "Единственный путь — обход OST_Rooms плюс "
                 "Room.GetBoundarySegments: 1 102 комнаты MNVNK на КАЖДЫЙ оп "
                 "против ОДНОГО вызова на цель у всего взятого"),
    ),
    "change_type": (
        _absence("neighbour circle after a type change",
                 "смена типа меняет толщину -> соединения и площади, а "
                 "FindInserts тут НЕ инвариант: Autodesk называет смену стены "
                 "на витраж случаем, где элемент ПЕРЕСОЗДАЁТСЯ и вставки "
                 "уходят законно. Сторож красил бы верную работу"),
    ),
    "set_param": (
        _absence("neighbour circle of a parameter write",
                 "КАТЕГОРИЯ ЦЕЛИ КОМПИЛЯТОРУ НЕИЗВЕСТНА, и потому общего "
                 "дешёвого читателя соседей не существует: base_offset "
                 "двигает стену, высота меняет вместимость проёмов, "
                 "ссылочный параметр перепривязывает к другому уровню"),
    ),
    "join_elements": (
        _absence("geometry of both operands after the join",
                 "соединение двигает солид на ПОЛТОЛЩИНЫ (живой замер "
                 "18.08.2026), то есть меняет объёмы и площади ОБОИХ "
                 "операндов. Перечитать это дёшево нечем"),
    ),
    "set_curtain_panel": (
        _absence("panel count of the host grid",
                 "ячейка витража может стать СТЕНОЙ (в модели замера 259 из "
                 "361 — WallType), и число панелей хозяина меняется. "
                 "Кандидат назван и НЕ взят волной 22.08: "
                 "CurtainGrid.GetPanelIds().Count до/после, один вызов"),
    ),
    # 🔴 THE BOUNDARY SHAPE FOR THE `GetBoundary()` PAIR — A NAMED ABSENCE,
    # NOT A WEAK WITNESS (19.08.2026). A weak witness would sign off on the
    # axis; a named absence says "nobody looked here", and
    # `unwitnessed_axes` picks it up — that is exactly the difference
    # between decoration and honesty.
    #
    # WHAT IS ESTABLISHED. For the slab, the ceiling, the roof, and the
    # footing, the shape is read via `Sketch.Profile`, and the corpus
    # proved that an arc there is stored as ONE curve (67 decompiles,
    # 10,463 rings, 331 `arc` entries recorded separately). For a railing
    # the evidence is `GetPath()`, and it is measured the same way (1058
    # paths, 1790 lines and 303 arcs, `arc_midpoints_mm` on the record).
    #
    # WHAT IS NOT ESTABLISHED AND WHY. For a pad and a subregion the
    # boundary is read via `GetBoundary()`, while OUR OWN reader there is
    # `Curve.Tessellate()` — which is exactly why it is checked against
    # `edges_bbox` with the arcs' cardinal extrema. Whether `GetBoundary()`
    # preserves an authored arc as ONE curve, the corpus cannot answer: it
    # has not a single indexed sample for these two categories. Building a
    # vertex-based witness on an unestablished representation would mean
    # risking a FALSE RED on correct geometry, and it rolls back the entire
    # program — the cost of an error is asymmetric here.
    #
    # WHAT NEEDS TO BE MEASURED LIVE for the absence to close: build a pad
    # and a subregion with an ARCED contour and read `GetBoundary()` — how
    # many curves came back and of what kind. One arc -> the shape witness
    # is taken the same way as the roof's; a tessellation -> the absence
    # remains named.
    "create_building_pad": (
        _absence("boundary vertex multiset",
         "GetBoundary() arc representation is UNMEASURED: no corpus index "
         "covers building pads, and our own reader tessellates. A vertex "
         "witness on an unestablished representation risks a FALSE RED that "
         "rolls back the program. Needs one live probe with an arc contour"),
    ),
    "create_site_subregion": (
        _absence("boundary vertex multiset",
         "same as create_building_pad: GetBoundary() arc representation "
         "UNMEASURED, no corpus index, our reader tessellates. Named absence "
         "beats a witness that may accuse correct geometry"),
    ),
    # 🔴 THE BOUNDING BOX OF A LOOP WITH A SPLINE — MEASURED LIVE ON
    # 20.08.2026.
    # A 12×8 m slab with a wavy edge, Revit 2026: along Y, Revit gave
    # 9705.3 mm, our sample expected 9426.0 — a 279 mm gap against a 50 mm
    # tolerance. This is not an error, it is DIFFERENT CURVES: we
    # approximate the edge with Catmull-Rom at compile time, Revit builds a
    # HermiteSpline with its own tangents, and the algorithm is
    # undocumented. The extrema will not coincide at any tolerance, and a
    # tolerance stretched to 300 mm would sign off on a real error too.
    #
    # A CAVEAT THAT CANNOT BE LEFT UNSPOKEN: the table is read BY THE OP'S
    # NAME, while the absence applies only to loops WITH A SPLINE — for a
    # contour of lines and arcs the bounding box is proved as before. That
    # is, slightly more is named here than is actually absent. Overreach in
    # this direction is safe (the reader is warned about what is actually
    # checked), underreach is not.
    # The same law holds for the ceiling, and the number is the same: what
    # diverges is not the elements but TWO CURVES between the same points
    # (our sample versus the HermiteSpline), and both sides for the ceiling
    # are exactly the same as for the slab. The same caveat applies: the
    # table is read BY THE OP'S NAME, while the absence applies only to
    # loops WITH A SPLINE — for a contour of lines and arcs, and for the
    # `outline` branch, the bounding box is proved as before. Overreach in
    # this direction is safe (the reader is warned about what is actually
    # checked), underreach is not.
    "create_ceiling": (
        _caveat("bbox", "contour bbox when a ring carries a spline",
         "габарит сплайнового кольца НЕ ДОКАЗЫВАЕТСЯ: форму между объявленными "
         "точками выбирает Revit (HermiteSpline, касательные не документированы), "
         "и наша компиляционная выборка занижает её по построению — измерено "
         "живьём 20.08.2026 на соседнем опе, разъезд 279 мм при допуске 50. "
         "Доказываются ТОЧКИ, через которые кривая объявлена идти "
         "(Sketch.Profile + Curve.Distance)"),
    ),
    "create_floor_by_contour": (
        _caveat("bbox", "contour bbox when a ring carries a spline",
         "габарит сплайнового кольца НЕ ДОКАЗЫВАЕТСЯ: форму между объявленными "
         "точками выбирает Revit (HermiteSpline, касательные не документированы), "
         "и наша компиляционная выборка занижает её по построению — измерено "
         "живьём 20.08.2026, разъезд 279 мм при допуске 50. Доказываются ТОЧКИ, "
         "через которые кривая объявлена идти (Sketch.Profile + Curve.Distance). "
         "У колец без сплайна габарит доказывается как прежде"),
    ),
    "delete": (
        _exempt("allow_destructive",
         "plan/envelope policy gate (SPEC 12.2), enforced before emission"),
        # 🔴 APPENDED TO AN EXISTING KEY, NOT AS A SECOND TABLE ROW
        # (22.08.2026). The first revision introduced `"delete"` as a
        # separate key above — and it would have SILENTLY OVERWRITTEN this
        # one: in a literal dict, the last occurrence wins. Caught by the
        # AST duplicate-key guard (`test_stairs_vertical_extent`),
        # introduced precisely against this.
        _absence("collateral deletion is reported, not bounded",
                 "doc.Delete забирает всё ПОЛНОСТЬЮ ЗАВИСИМОЕ и возвращает "
                 "список — он теперь в квитанции. Но ОГРАНИЧИТЬ его нечем: "
                 "у языка нет понятия «что обязано остаться», план знает "
                 "только булев allow_destructive НА ЦЕЛЬ"),
    ),
    "create_room": (
        _exempt("placed after",
         "emitter EMIT-ORDER rule (doc.Regenerate before rooms), not a "
         "post-commit witness"),
    ),
    "create_stairs": (
        _exempt("sole op",
         "PLAN constraint (KIR-L002); emit_program raises before emission"),
        # 🔴 19.08, THE SECOND CLAUSE — AND IT ALMOST ERASED THE FIRST. The
        # guard on the flight's vertical extent is one-sided: overshoot
        # rolls back, undershoot does not. My first revision wrote this
        # into `post`, that is, into the list of PROMISES, and
        # `audit_registry_coverage()` caught it: «promised clause not
        # witnessed». The second revision introduced a SECOND
        # "create_stairs" key in this dict — Python keeps the last one, and
        # the `sole op` entry above WOULD HAVE SILENTLY DISAPPEARED along
        # with the honest KIR-L002 exemption. Exactly what the 09.08
        # comment at `create_beam_system` below warns about: "both waves
        # were appending to the end of one exemption dict, and whichever
        # side won would have erased two honestly named absences". Paid for
        # a SECOND TIME — so a guard was placed on the class that parses
        # the SOURCE with an AST: in the finished dict the duplicate key is
        # already gone, and it can only be seen in the text.
        _caveat("vertical_extent", "недобор подступенков",
         "`create_stairs` кладёт ОДИН марш, а лестница из нескольких маршей с "
         "площадками достраивается `create_stairs_landing` — до достройки "
         "ActualRisersNumber < DesiredRisersNumber есть ВЕРНОЕ промежуточное "
         "состояние, и откат сломал бы законный порядок построения. Перебор "
         "оправдать нечем и он откатывает; оба числа плюс проступь и потребная "
         "длина уезжают в расписку, поэтому недобор ВИДЕН, не будучи "
         "смертельным (19.08)"),
    ),
    # THE STAIRS WAVE (10.08.2026). THREE exemptions, each named precisely
    # so that an unwitnessable promise does not dissolve into the
    # neighboring clause over an accidental shared word.
    # THE SECOND FLIGHT (15.08.2026). TWO exemptions, both unwitnessable
    # promises, named individually so they do not dissolve into the
    # neighboring clause over an accidental shared word.
    "create_stairs_run": (
        _exempt("sole op",
         "PLAN constraint (KIR-L002); emit_program raises before emission"),
        # A NAMED ABSENCE OF AN AXIS — the same argument as for the
        # landing: Revit assigns the flight's path Z from the stair's base.
        # Signing off on an axis that was never set is exactly the defect
        # test_witness_axis_honesty was set up to forbid.
        _exempt("z is not compared",
         "Revit derives the run path Z from the stairs base itself, so that Z "
         "is Revit's number and not the op's; witnessing it would sign an "
         "axis nobody authored"),
        # A PRECONDITION, NOT A POSTCONDITION: the multiple-of-a-riser check
        # runs BEFORE the effect and refuses, so it has no witness
        # obligation.
        _exempt("base_elevation_mm must already be an integer multiple",
         "checked BEFORE any effect and refused with the adjacent multiples "
         "named; a precondition has no post-effect witness to discharge"),
    ),
    "create_stairs_landing": (
        _exempt("sole op",
         "PLAN constraint (KIR-L002); emit_program raises before emission"),
        # A NAMED ABSENCE OF AN AXIS. The clause states what the witness
        # does NOT sign off on: the Z of the read-back boundary is set by
        # Revit itself («projected on the stairs base level»), not by us.
        # Signing off on an axis that was never set is exactly the defect
        # test_witness_axis_honesty was set up to forbid.
        _exempt("the z of those curves is not compared",
         "Revit itself projects the boundary onto the stairs base level, so "
         "that Z is Revit's number and not the op's; witnessing it would sign "
         "an axis nobody authored"),
        # A PRECONDITION, NOT A POSTCONDITION. The exact lower bound of the
        # elevation (half a riser's height) is known only from a live
        # staircase, so it is checked BEFORE the call and is a typed
        # REFUSAL. It has no obligation and none can exist: after a
        # refusal there is no commit at all, and nothing to witness.
        _exempt("typed refusal naming the measured number",
         "a PRE-condition read off the live stairs (ActualRiserHeight) and "
         "refused before the create call — after a refusal nothing commits, "
         "so there is no post-commit state to witness"),
    ),
    # wave/sweep (2026-08-09). THE ONLY EXEMPTION OF THIS WAVE, and it was
    # introduced PRECISELY SO that a weaker named guarantee does not slip
    # past the audit on an accidental shared word. The clause quotes
    # Autodesk verbatim («The values set in the WallSweepInfo are ignored»)
    # and states what the operation does NOT assert; it has no obligation
    # and none can exist — the profile's position is set by the type, not
    # the call, and the operation has no field for it at all. This is NOT a
    # hole in the audit: the audit stays strict, and the unassertable thing
    # is named out loud instead of silently dissolving into the
    # neighboring clause.
    "create_wall_sweep": (
        _exempt("named weaker guarantee",
         "a documented API fact (RevitAPI.xml, all six versions: the wall "
         "sweep's profile and position come from the type, and the "
         "WallSweepInfo values are ignored), so the op exposes no distance "
         "or offset field and there is nothing to witness — stating the "
         "limit is the honest alternative to inventing a witness"),
    ),
    # wave/mass (2026-08-10). THE ONLY EXEMPTION OF THIS WAVE, and it was
    # introduced precisely so that a NAMED ABSENCE of a witness does not
    # slip past the audit on an accidental shared word. The clause states
    # what the operation does NOT assert: that the built wall's area
    # equals the named face's area. It has no obligation and none can
    # exist — whether Revit covers the face entirely is not stated in any
    # of the six RevitAPI.xml files, and asserting it on a guess would mean
    # introducing a check that rejects correct behavior. The raw pair rides
    # into the receipt, and the first live run will MEASURE the quantity
    # instead of estimating it.
    "create_face_wall": (
        _exempt("named absence",
         "whether Revit spans the whole named face is documented nowhere in "
         "any of the six RevitAPI.xml, so no witness can be honest here; the "
         "receipt carries the raw pair and the first live run measures the "
         "remainder instead of a reasoned tolerance standing in for it"),
    ),
    "load_family": (
        _exempt("already loaded",
         "idempotent-resolution semantics proven by the create-side collector "
         "search, not a post-commit witness"),
        _exempt("another family",
         "resolution correctness (family+type match) enforced in the create "
         "block's collector filter, not a post-commit witness"),
    ),
    # THE SAME FORM AS THE NEIGHBOR ABOVE, AND FOR THE SAME REASON: both
    # clauses describe PHASE A (before the transaction), where a
    # post-commit witness cannot exist by construction. The first is not
    # our obligation AT ALL: REVIT ITSELF aborts the load on conflict, and
    # this is documented (RevitAPI.xml, `LoadFamily(Document)`: «the
    # conflict caused an automatic abort of the load operation»). Promising
    # it with a witness would mean claiming someone else's guarantee.
    # The clause about the SOURCE'S KIND describes a preflight check: the
    # refusal happens BEFORE `Duplicate`, and no commit that could be
    # witnessed ever arises. A post-commit witness cannot see it by
    # construction — exactly the same shape as phase A of the family
    # transfer.
    "create_wall_type": (
        _exempt("род источника обязан быть Basic",
         "the Basic-kind check is a PRE-FLIGHT refusal: it rolls back before "
         "Duplicate ever runs, so no committed state exists for a post-commit "
         "witness to read"),
        # 24.08.2026 — THE SAME FORM, ONE KIND LOWER. For floor/roof/ceiling
        # the `Kind` property DOES NOT EXIST AT ALL (0/6 on real builds
        # 2021-2026, with two negative controls at 0/6), so the gate there
        # is the SOURCE's CompoundStructure presence. It is read before
        # `Duplicate`, that is, the refusal happens BEFORE the commit —
        # nothing to witness, exactly like the neighbor above.
        _exempt("затвора «Basic» нет и быть не может",
         "the non-wall pre-flight (source has a CompoundStructure) refuses "
         "BEFORE Duplicate, exactly like the Basic-kind check above: there is "
         "no committed state for a post-commit witness to read"),
    ),
    "transfer_family": (
        _exempt("не заменяется молча",
         "the abort-on-conflict guarantee is REVIT'S, documented on "
         "LoadFamily(Document) across all six versions; a post-commit witness "
         "cannot observe a load that never happened"),
        _exempt("штатный повтор",
         "idempotent resolution is decided in phase A by the target-side "
         "collector search, before any transaction exists to witness in"),
    ),
    # A clause that HONESTLY NAMES THE ABSENCE of a witness, rather than
    # promising one. It has no obligation and there should be none: the
    # footing's overhang past the wall and its bottom elevation are NOT
    # MEASURED (across every saved decompile on disk, zero WallFoundation
    # instances, grep 09.08), and a tolerance derived from reasoning is
    # exactly the class of defect this compiler catches
    # (create_door.sill_mm min_val=0; docspace._SHEET_LIMIT_MM). The
    # exemption is lifted by ONE live measured run, not a rewording.
    "create_wall_foundation": (
        _exempt("not witnessed on purpose",
         "the footing's projection beyond its wall and its underside "
         "elevation have never been measured — no honest expected value "
         "exists to gate on, and an invented tolerance would be the defect "
         "class this compiler exists to kill (09.08)"),
    ),
    # The clause "derived by Revit — deliberately not gated" (09.08). It
    # NAMES a limit rather than promising a check, and neither of the two
    # ops should have an obligation for it:
    #   * fittings — THIS OP ITSELF CREATES THEM (`connect.emit_fittings_cs`
    #     -> NewElbowFitting/NewTeeFitting/NewTransitionFitting at every
    #     junction of degree >= 2), but it does not name their COUNT:
    #     `classify_junction` can reduce a joint to a bare
    #     `Connector.ConnectTo` and produce no element, and which family
    #     gets substituted into the call is decided by routing preferences.
    #     Neither of these is MEASURED, so a counting witness would be
    #     gating an unmeasured quantity. Before 10.08.2026 this used to say
    #     "their count is chosen by Revit from the connector graph (2652 +
    #     152 with ZERO authored)" — the causality was wrong (the fittings
    #     are ours), and the numbers are actually a census of
    #     snowdon_plumb_v3: PF=2652, DF=152, PA=126, and "152 fittings" was
    #     the count of duct fittings — pipe fittings there number 126, and
    #     no emitter in the package creates them;
    #   * MEPSystem membership — it settles on Commit(), not on
    #     doc.Regenerate() (measured, connect.py §A), so ANY
    #     within-transaction check of "all segments are in one system" is
    #     unsatisfiable BY CONSTRUCTION. Writing one would not be caution,
    #     it would be a check that always fails — exactly as dishonest as
    #     one that can never fail. The fact is read AFTER the commit
    #     (`connect.emit_system_readback_cs` -> mep_system_ids/one_system)
    #     and is reported, not asserted.
    # The exemption can only be lifted by an architectural change (a
    # witness living after Commit), not by rewording the prose.
    "route_pipe_system": (
        _exempt("deliberately not gated",
         "the op emits the fittings itself (NewElbowFitting/NewTeeFitting/"
         "NewTransitionFitting per node of degree>=2) but declares no fitting "
         "COUNT, and neither the ConnectTo-instead-of-fitting case nor the "
         "routing-preference family choice has been measured, and "
         "MEPSystem membership merges at Commit() — an in-transaction "
         "membership check is unsatisfiable by construction, so the fact is "
         "read back after commit and reported, never asserted (09.08)"),
    ),
    "route_duct_system": (
        _exempt("deliberately not gated",
         "the op emits the fittings itself (NewElbowFitting/NewTeeFitting/"
         "NewTransitionFitting per node of degree>=2) but declares no fitting "
         "COUNT, and neither the ConnectTo-instead-of-fitting case nor the "
         "routing-preference family choice has been measured, and "
         "MEPSystem membership merges at Commit() — an in-transaction "
         "membership check is unsatisfiable by construction, so the fact is "
         "read back after commit and reported, never asserted (09.08)"),
    ),
    # Two more clauses that NAME THE ABSENCE of a witness instead of
    # staying silent. Both concern quantities that REVIT computes, not the
    # author. They arrived with the framing wave; the 09.08 merge took the
    # UNION — both waves were appending to the end of one exemption dict,
    # and whichever side "won" would have erased two honestly named
    # absences.
    "create_beam_system": (
        _exempt("deliberately not gated",
         "beam count and spacing come from LayoutRule, which no argument of "
         "BeamSystem.Create sets and no author named — demanding a number "
         "nobody asked for is exactly how the height_mm default rolled back "
         "correctly built facade walls (31.07). Direction and Elevation are "
         "Revit-normalised values with no measured comparison rule, so they "
         "ride the receipt instead: a reader sees them, a witness does not "
         "demand them"),
    ),
    "create_truss": (
        _exempt("belongs to the truss family",
         "chord shape, panel count and web layout are the family's, not the "
         "op's — the op names a base line and a type, and gating geometry it "
         "never authored would reject every correctly built truss whose "
         "family differs from our guess"),
        _exempt("rides the receipt rather than a demand",
         "which reference level Revit picks is its inference from the sketch "
         "plane, not our argument — the exact create_beam lesson measured "
         "27.07, where forcing that equality rolled correct framing back"),
    ),
    # wave/reinforcement (10.08). TWO clauses that NAME THE ABSENCE of a
    # witness instead of staying silent, and both are a measurement, not
    # caution.
    "create_area_reinforcement": (
        _exempt("ride the receipt rather than a demand",
         "Revit normalises the major direction and projects it into the "
         "host's plane, so comparing it back needs an angular tolerance "
         "nobody in this house has measured; bar count is chosen by the "
         "reinforcement type's layout, which no argument of Create sets — "
         "demanding a number nobody asked for is exactly how the height_mm "
         "default rolled back correctly built facade walls (31.07). Both "
         "values, and the HostStructuralRebar setting that explains a zero, "
         "are read back and reported, never asserted"),
        _exempt("not witnessed on purpose",
         "the boundary is computed by Revit from the host — the program "
         "authors no dimension at all — and 38 stored decompiles with a "
         "census contain zero OST_AreaRein/OST_PathRein/OST_Rebar/"
         "OST_FabricAreas elements (10.08), so no honest expected value "
         "exists to gate on and an invented tolerance would be the defect "
         "class this compiler exists to kill"),
    ),
    # `create_dimension`'s "receipt-only" exemption was DELETED by the
    # annotation wave (09.08), not lost in this merge: the resolver now knows
    # which PLANE each reference names, so an independent expected distance
    # exists and the op carries a real gated GEOMETRY obligation instead of an
    # exemption. `create_wall_foundation` above keeps its exemption because
    # nothing about it has been measured yet — the two are unrelated.
}

#: A PROJECTION, NOT A SECOND TABLE. The former (clause, why) pair for
#: foreign readers — `rehearsal.rehearse` and
#: `course/shape.declared_boundaries` reach in here by name and unpack TWO
#: elements. There is one carrier (`_CLAUSE_NOTES`), so these two have
#: nothing to drift apart from.
#:
#: THE ROLE RIDES IN THE REASON, NOT AS A SEPARATE FIELD, precisely so that
#: ALL readers get it, foreign ones included, without touching a single one
#: of their files. The pair's shape is the SAME as before: existing tests'
#: substring checks (`assertIn` on `why`) survive it, and the printout
#: becomes honest across all three routes.
_NON_WITNESSABLE_CLAUSES: dict[str, tuple[tuple[str, str], ...]] = {
    op: tuple((marker, _absence_why_ru(why, role, key))
              for marker, why, role, key in notes)
    for op, notes in _CLAUSE_NOTES.items()
}

#: Only EXEMPTIONS discharge a clause in `audit_registry_coverage`. A
#: named absence and a caveat discharge NOTHING by construction (their
#: marker must not occur in the clause at all), and previously this held
#: by coincidence, not by rule: an entry of any role would silently strike
#: out a clause if its text happened to match.
_EXEMPT_MARKERS: dict[str, tuple[str, ...]] = {
    op: tuple(marker for marker, _why, role, _key in notes
              if role == NOTE_EXEMPT)
    for op, notes in _CLAUSE_NOTES.items()
}


def audit_clause_notes() -> tuple[str, ...]:
    """Every `_CLAUSE_NOTES` entry must hold the invariant of ITS OWN ROLE.

    🔴 WHY, MEASURED ON 22.08.2026. Before this instrument the table had
    exactly one way to fail unnoticed: a marker would stop occurring in a
    clause — and the exemption would stop exempting anything, WITHOUT
    SAYING SO. Five of the 26 entries were living in that state, and
    `named_absences` kept presenting them to the model, because it returns
    a string without asking whether the clause is alive. The silence was
    two-sided: the audit did not know it had stopped exempting, and the
    model did not know it was reading something dead.

    THREE ROLES — THREE DIFFERENT CORRECT ANSWERS to "how many clauses did
    the marker hit", and that is exactly why one check cannot cover the
    whole table:

      * ``NOTE_EXEMPT``  — EXACTLY ONE. Zero means a dead marker (the audit
        no longer exempts anything); two or more means the marker has
        stopped DISTINGUISHING and is exempting the neighboring clause too
        — the other half of substring weakness, and it is checked here for
        the first time;
      * ``NOTE_ABSENCE`` — ZERO. A hit means a promise was introduced into
        `post` after all, with no witness built for it: the entry must
        become either an exemption or an obligation, and a human must
        decide which;
      * ``NOTE_CAVEAT``  — ZERO, AND THE NAMED KEY MUST EXIST among the
        op's obligations. A caveat describes the limit of a LIVE witness;
        if the witness is gone, the limit describes emptiness.

    Returns a tuple of strings; an empty tuple means the table is healthy.
    The instrument is wired into `audit_registry_coverage`, which already
    has a live consumer (`op_contract.py`), so the finding does not gain
    itself yet another silent reader.
    """

    problems: list[str] = []
    table = _ensure_table()
    for op in sorted(_CLAUSE_NOTES):
        notes = _CLAUSE_NOTES[op]
        op_spec = spec.OPS.get(op)
        if op_spec is None:
            problems.append(f"{op}: clause note for an op outside the registry")
            continue
        clauses = [c.strip() for c in (op_spec.post or "").split(";") if c.strip()]
        ref = table.get(op)
        keys = {o.key for o in ref.obligations if o.key} if ref else set()
        for marker, _why, role, key in notes:
            low = marker.lower()
            hits = [c for c in clauses if low in c.lower()]
            if role == NOTE_EXEMPT:
                if not hits:
                    problems.append(
                        f"{op}: DEAD exemption marker {marker!r} — matches no "
                        f"clause of OpSpec.post, so it exempts nothing and the "
                        f"audit has been silently toothless here. Reclassify "
                        f"(_absence / _caveat) or fix the marker")
                elif len(hits) > 1:
                    problems.append(
                        f"{op}: AMBIGUOUS exemption marker {marker!r} — matches "
                        f"{len(hits)} clauses, so it silences a neighbour too: "
                        f"{[c[:48] for c in hits]}")
            elif role == NOTE_ABSENCE:
                if hits:
                    problems.append(
                        f"{op}: named absence {marker!r} is now PROMISED in "
                        f"OpSpec.post ({hits[0][:60]!r}) — a promise without an "
                        f"obligation. Build the witness or make it _exempt")
            elif role == NOTE_CAVEAT:
                if hits:
                    problems.append(
                        f"{op}: caveat {marker!r} matches a clause of "
                        f"OpSpec.post ({hits[0][:60]!r}) — a caveat qualifies an "
                        f"obligation, it does not exempt a clause")
                if key not in keys:
                    problems.append(
                        f"{op}: caveat {marker!r} names obligation key {key!r}, "
                        f"which does not exist — the witness it bounds is gone, "
                        f"so the caveat now describes nothing (keys: "
                        f"{sorted(keys)})")
            else:
                problems.append(
                    f"{op}: clause note {marker!r} has unknown role {role!r} "
                    f"(expected one of {NOTE_ROLES})")
    return tuple(problems)


def named_absences(op_names):
    """NAMED ABSENCES OF THIS PROGRAM — the places nobody looked.

    🔴 WHY, MEASURED ON 19.08.2026. The `_NON_WITNESSABLE_CLAUSES` table
    lived with ONE consumer — the static audit `audit_registry_coverage`.
    It had NOT A SINGLE live reader, meaning the honesty existed and never
    reached the one it was built for.

    A run of the prod path (`serving._witness_for_success`) showed the
    cost of that:

        create_site_subregion   unwitnessed_axes = {}   ← CLEAN
        create_building_pad     unwitnessed_axes = {'semantic': [...]}

    The subregion has a named absence of SHAPE, and from the outside the
    op is indistinguishable from a fully checked one. Of the 16 ops with
    named absences, EIGHT were being lost entirely.

    THE CAUSE IS DIFFERENT GRANULARITY, NOT A FORGOTTEN WIRE.
    `unwitnessed_axes` judges BY AXIS ("did the op declare at least one
    obligation of this kind"), while a named absence lives ON A CLAUSE. An
    op with a bounding-box obligation and a named unwitnessable shape
    INSIDE that same axis is indistinguishable from a fully checked one to
    the axis instrument. That is why this is a SEPARATE field, not a fix to
    `unwitnessed_axes`: merging them would mean running one piece of code
    for two different outcomes — exactly what both were built against.

    THREE STATES, THE SAME AS `unwitnessed_axes`, and they must not be
    confused:

    * ``{}``   — every op in the program is covered by the table, there are
      no named absences. This is an ASSERTION, not silence;
    * a non-empty dict ``op -> ((clause, reason), ...)`` — this is what
      nobody looked at, and here is why;
    * ``None`` — there is nothing to judge: the program is empty, or the
      table failed to load. This is NOT "all is well", and the reader must
      distinguish them.

    Op names are truncated to ten, like `violations` and
    `unwitnessed_axes`: the receipt is paid for on every turn.
    """
    try:
        names = [str(n) for n in (op_names or ()) if n]
    except TypeError:
        return None
    if not names:
        return None
    try:
        table = _NON_WITNESSABLE_CLAUSES
    except Exception:                                          # noqa: BLE001
        return None
    if not isinstance(table, dict):
        return None
    out: dict = {}
    for name in dict.fromkeys(names):
        entries = table.get(name)
        if entries:
            out[name] = tuple((str(c), str(w)) for c, w in entries)[:10]
    return out


def _clause_tokens(text: str) -> frozenset[str]:
    """Normalize a prose postcondition into comparable lowercase word tokens."""

    return frozenset(re.findall(r"[a-zа-я_]+", text.lower()))


def audit_registry_coverage() -> tuple[str, ...]:
    """Return every table<->registry mismatch (empty tuple == fully covered).

    Three fail-closed invariants:
      1. Every write op (family in WRITE_FAMILIES) has an OpRefinementSpec.
      2. Every REFINEMENT op is a real registry op (no dangling entry).
      3. Every ';'-separated clause of each op's OpSpec.post is witnessed by at
         least one obligation whose clause shares a distinguishing token —
         so a newly promised clause with no obligation is a hard mismatch.

    THIS AUDIT'S LIMIT, NAMED HONESTLY (03.08).  Invariant 3 checks prose
    by SHARED WORDS, that is, it is substring matching in different
    clothes.  A case it missed was measured: the route_* slope clause
    (KIR-X004) lived WITHOUT its obligation and passed the audit, because
    the word "segment" occurs for both the diameter and the connectivity.
    The strong form is not words but MUTATION: cut the emitted witness out
    and require `proven` to fail (tests/test_tolerance_provenance.py, law
    L6).  This audit remains a cheap first line, not a proof.
    """

    table = _ensure_table()
    problems: list[str] = []

    write_ops = {
        name for name, op_spec in spec.OPS.items()
        if op_spec.family in spec.WRITE_FAMILIES
    }
    covered = set(table)

    for name in sorted(write_ops - covered):
        problems.append(f"{name}: write op has no OpRefinementSpec")
    for name in sorted(covered - write_ops - _EXTRA_CERTIFIABLE):
        problems.append(
            f"{name}: OpRefinementSpec references a non-write / unknown op")

    # Clause-level biection: each prose clause must map to an obligation.
    # Distinguishing tokens: content words minus ubiquitous filler.
    filler = _clause_tokens(
        "exists when given the a is at in of and or == !=  mm tol day "
        "post commit re read semantic geometry topology witness parameter "
        "chain bip resolved requested value type flag")
    for name, ref in sorted(table.items()):
        if name not in spec.OPS:
            continue
        op_spec = spec.OPS[name]
        obligation_tokens = frozenset().union(
            *(_clause_tokens(o.clause) for o in ref.obligations))
        # ONLY EXEMPTIONS DISCHARGE. A named absence and a caveat have no
        # right to strike out a clause: their invariant is to NOT occur in
        # it at all, and `audit_clause_notes()` below holds them to it.
        # Previously the whole table stood here, and an entry's role had no
        # effect on the outcome at all.
        exemptions = _EXEMPT_MARKERS.get(name, ())
        for raw_clause in op_spec.post.split(";"):
            clause = raw_clause.strip()
            if not clause:
                continue
            low = clause.lower()
            if any(marker.lower() in low for marker in exemptions):
                continue
            key_tokens = _clause_tokens(clause) - filler
            if not key_tokens:
                continue
            if not (key_tokens & obligation_tokens):
                problems.append(
                    f"{name}: promised clause not witnessed by any "
                    f"obligation: {clause!r}")

    # A FOURTH INVARIANT (22.08.2026): the exemption table itself must be
    # alive. The instrument is wired in HERE, rather than set up as a
    # separate entry point, because this function already has a live
    # consumer (`op_contract.py`), and a finding with no reader is exactly
    # the class of defect that uncovered the five dead markers.
    problems.extend(audit_clause_notes())

    return tuple(problems)


#: The axes a `post` clause can name ABOUT ITSELF, and the obligation kind
#: they correspond to. One dictionary for both ends — otherwise this would
#: be a second opinion on the same fact.
_CLAUSE_AXIS_WORDS = {
    "geometry": KIND_GEOMETRY,
    "topology": KIND_TOPOLOGY,
    "semantic": KIND_SEMANTIC,
    "materialize": KIND_MATERIALIZE,
}


def audit_clause_axis_credit() -> tuple[tuple[str, str, str, tuple], ...]:
    """Clauses credited to an obligation of a FOREIGN AXIS — a cheap
    check BY SUBJECT.

    🔴 WHY, AND WHY THIS IS NOT A REPEAT OF `audit_registry_coverage`.
    Invariant 3 of that audit asks "is there AT LEAST ONE obligation that
    shares a word with the clause". It does not ask whether THAT is the
    right obligation, and it names this as its own limit. A measurement on
    22.08.2026 showed the cost of the difference:

        332 clauses passed the check; 194 of them (58.4%) share a word with
        TWO OR MORE obligations at once, meaning the audit does not know
        which of them discharges the clause, and any of them gets a green.

    An example, analyzed by name (`create_dimension`, 667 operations of a
    real building). Of four clauses, only ONE matches its own obligation:

        [1] «References bound to all refs»       -> credited to `in_view` via the word «to»
        [2] «every ref visible in in_view»       -> credited to `in_view` via the word «in_view»
        [3] «measured value equals the distance» -> credited to `references` via the word «references»

    The preposition "to" survived the filler list and discharged the
    reference-binding clause with the view-membership obligation. This is
    substring weakness in its pure form.

    A FULL SUBJECT-BASED CHECK requires a clause to be addressed by a KEY,
    not by text, that is, for `OpSpec.post` to stop being a `;`-separated
    string — a change to 78 ops in foreign `ops_*.py` files. What is done
    here is its CHEAP half, which catches the same class without touching a
    single foreign file: a clause that NAMES ITS OWN AXIS in parentheses
    must be credited to an obligation of the SAME KIND. The axis in
    parentheses is a carrier already present on 205 of the 332 clauses, and
    checking it costs nothing.

    THE FIRST RUN'S CATCH — 5 of 205, and it split immediately into two
    classes:

      * NO AXIS AT ALL for `create_dimension` and
        `create_angular_dimension`: both promise «every ref visible in
        in_view (semantic)» and declare NOT A SINGLE semantic obligation.
        This is a hole, not a typo;
      * THE AXIS EXISTS, CREDITED TO THE WRONG ONE for `create_text`
        (geometry is declared via the `at`/`width` keys, and the clause
        «at ±tol» was credited to topology, because both "at" and "tol"
        are in the filler list) and for `move_elements` (topology is
        declared via the `connectors` key).

    The instrument is deliberately NOT wired into `audit_registry_coverage`:
    that one has zero findings — a live gate — and turning it red with a
    finding that is fixed in foreign files would mean halting four other
    waves. The baseline is frozen in the test.

    Returns a tuple ``(op, axis, clause, ((key, kind), ...))``.
    """

    table = _ensure_table()
    out: list[tuple[str, str, str, tuple]] = []
    filler = _clause_tokens(
        "exists when given the a is at in of and or == !=  mm tol day "
        "post commit re read semantic geometry topology witness parameter "
        "chain bip resolved requested value type flag")
    for name, ref in sorted(table.items()):
        op_spec = spec.OPS.get(name)
        if op_spec is None:
            continue
        exemptions = _EXEMPT_MARKERS.get(name, ())
        for raw_clause in (op_spec.post or "").split(";"):
            clause = raw_clause.strip()
            if not clause:
                continue
            low = clause.lower()
            if any(marker.lower() in low for marker in exemptions):
                continue
            # The axis is named in parentheses: `(geometry)` or `(semantic,
            # ...)`. Exactly ONE — a clause about two axes at once is not
            # judged by this instrument, L2 at `test_post_clause_kind` holds
            # it.
            named = {word for word in _CLAUSE_AXIS_WORDS
                     if re.search(r"\(%s[,)]" % word, low)}
            if len(named) != 1:
                continue
            axis = _CLAUSE_AXIS_WORDS[named.pop()]
            key_tokens = _clause_tokens(clause) - filler
            if not key_tokens:
                continue
            credited = [o for o in ref.obligations
                        if key_tokens & _clause_tokens(o.clause)]
            if not credited:
                continue                    # invariant 3 already hard-fails
            if any(o.kind == axis for o in credited):
                continue
            out.append((name, axis, clause,
                        tuple((o.key, o.kind) for o in credited)))
    return tuple(out)


__all__ = [
    "BLOCK_CREATE",
    "BLOCK_POST",
    "BLOCK_OPERATION",
    "CERT_MODE_OFF",
    "CERT_MODE_RECORD",
    "CERT_MODE_REFUSE",
    "CertificateError",
    "CertificateSchemaError",
    "ClauseVerdict",
    "KIND_GEOMETRY",
    "KIND_IDENTITY",
    "KIND_MATERIALIZE",
    "KIND_PARAMETER",
    "KIND_SEMANTIC",
    "KIND_TOPOLOGY",
    "NOTE_ABSENCE",
    "NOTE_CAVEAT",
    "NOTE_EXEMPT",
    "NOTE_ROLES",
    "Obligation",
    "OpCertificate",
    "OpRefinementSpec",
    "ProgramCertificate",
    "REFINEMENT",
    "UnprovenRefinementError",
    "VACUITY_CONSTANT_FALSE",
    "VACUITY_KINDS",
    "VACUITY_SELF_COMPARISON",
    "VACUITY_UNREACHABLE",
    "VacuityFinding",
    "VacuousWitnessError",
    "analyze_witness_cs",
    "assert_refined",
    "audit_clause_axis_credit",
    "audit_clause_notes",
    "audit_registry_coverage",
    "certificate_enabled",
    "certificate_mode",
    "certify_op",
    "certify_program",
    "witness_site_census",
    "witness_vacuity",
]
