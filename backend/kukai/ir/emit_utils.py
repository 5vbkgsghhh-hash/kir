"""Small, shared helpers for deterministic C# emission."""
from __future__ import annotations

import json
import re
import math


_PLAIN_ID = re.compile(r"[A-Za-z0-9_]+\Z")
_ESCAPE_PREFIX = "KIRX_"
ELEMENT_ID_MAX = (1 << 63) - 1
ELEMENT_ID_INT32_MAX = (1 << 31) - 1
_EXACT_DOUBLE_INT_MAX = 1 << 53

# C# recognises all five characters below as line terminators.  An IR id is a
# data value, not source text, and the schema deliberately permits arbitrary
# Unicode; keep that contract while making it safe to show in generated
# ``// ...`` diagnostics.  Ordinary ids remain byte-identical.
_CS_LINE_TERMINATOR_ESCAPES = str.maketrans({
    "\r": r"\r",
    "\n": r"\n",
    "\x85": r"\u0085",       # NEXT LINE
    "\u2028": r"\u2028",     # LINE SEPARATOR
    "\u2029": r"\u2029",     # PARAGRAPH SEPARATOR
})


def is_finite_number(value) -> bool:
    """Whether *value* is safe for KIR's double-based numeric boundary.

    ``math.isfinite`` converts integers to double and raises OverflowError for
    arbitrarily large JSON integers.  Values beyond double's exact integer
    range are also unsafe to splice into geometry/Parameter C# expressions:
    the IR would claim an integer that the target numeric representation
    cannot retain exactly.  Treat both cases as ordinary type failures.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    if isinstance(value, int) and abs(value) > _EXACT_DOUBLE_INT_MAX:
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, TypeError, ValueError):
        return False


def cs_identifier_fragment(value: str) -> str:
    """Return an injective, ASCII-safe C# identifier fragment.

    Common IR ids stay readable and byte-stable.  Anything outside the plain
    ASCII identifier alphabet is encoded as UTF-8 hex.  Plain ids beginning
    with the escape marker are encoded too, so no user-authored id can collide
    with an encoded one (for example ``a-b`` and ``a_b`` remain distinct).
    """
    if _PLAIN_ID.fullmatch(value) and not value.startswith(_ESCAPE_PREFIX):
        return value
    return _ESCAPE_PREFIX + value.encode("utf-8").hex()


def cs_string_literal(value: str) -> str:
    """Return *value* as one C# string literal, safe on every line terminator.

    JSON escaping covers CR/LF but leaves U+0085, U+2028 and U+2029 raw, and C#
    counts all three as line terminators: the literal ends mid-string and the
    remainder becomes source.  The compiler then reported ``ok=True`` while
    emitting C# that cannot compile.  Applying the shared table *after*
    ``json.dumps`` is what keeps that from happening — at that point CR/LF are
    already ``\\r``/``\\n`` text, so only the three raw characters are left to
    translate and ordinary literals stay byte-identical.
    """

    return json.dumps(value, ensure_ascii=False).translate(
        _CS_LINE_TERMINATOR_ESCAPES)


def cs_element_id_literal(value: int, revit_version: str) -> str:
    """Render one positive ``ElementId`` across the 2021--2026 API split.

    Revit 2021--2023 expose the 32-bit constructor; 2024+ expose the 64-bit
    constructor as well.  Keeping this dialect decision in the shared emitter
    utility prevents authoring and independent rereads from silently using
    different identity rules.
    """

    if (isinstance(value, bool) or not isinstance(value, int)
            or not 1 <= value <= ELEMENT_ID_MAX):
        raise ValueError(
            f"ElementId must be an integer within 1..{ELEMENT_ID_MAX}")
    if not isinstance(revit_version, str) or not re.fullmatch(
            r"20(?:2[1-9]|[3-9][0-9])", revit_version):
        raise ValueError("Revit version must be a four-digit year >= 2021")
    if value <= ELEMENT_ID_INT32_MAX:
        return f"new ElementId({value})"
    if revit_version >= "2024":
        return f"new ElementId({value}L)"
    raise ValueError(
        f"ElementId {value} exceeds the 32-bit Revit {revit_version} dialect")


REFUSE_ISOLATIONS = ("atomic", "per_op")


def refuse_stmt(oid: str, message_cs: str, isolation: str) -> str:
    """The refusal STATEMENT of ONE op-local guard, rendered for *isolation*.

    This is the single place in the compiler where the text of an op-local
    refusal exists.  Until 2026-07-28 the ``per_op`` form was produced by
    rewriting emitted C# — ``body.replace("__t.RollBack(); return __Refuse(",
    "throw __OpRefuse(")`` — so an emitter that spelled the phrase any other
    way (one extra space, its own rollback, a refusal inside ``catch``) kept
    WHOLE-PROGRAM semantics inside a SubTransaction: one op's refusal rolled
    its committed neighbours back.  Nothing but author discipline held the
    phrase together across the ~105 hand-typed sites of four files.

    Here the emitter never spells it — it asks for the statement and receives
    the form its isolation requires:

      * ``atomic``  -> ``__t.RollBack(); return __Refuse(<oid>, <msg>);``
        (one transaction; a guard failure is the whole program's failure);
      * ``per_op``  -> ``throw __OpRefuse(<oid>, <msg>);`` — the op-local
        sentinel this op's own SubTransaction ``catch`` absorbs, leaving the
        committed neighbours alone.

    Both forms are byte-identical to what the textual rewrite produced, so no
    golden moves (review finding №12).  Ownership stops at the STATEMENT
    (№8): the surrounding ``if``/braces stay with the emitter, which is what
    keeps byte-parity reachable on the multi-line guards.

    *message_cs* is a C# EXPRESSION, not a Python string: guards routinely
    concatenate a live Revit message (``"Delete: " + __ex_x.Message``).
    *oid* is the raw IR id — the literal is built here, once.

    There is deliberately NO default isolation: an emitter that forgot the
    argument would silently emit whole-program semantics into a per_op run —
    exactly the failure this helper exists to make unconstructible.
    """

    if isolation == "atomic":
        return (f"__t.RollBack(); return __Refuse({cs_string_literal(oid)}, "
                f"{message_cs});")
    if isolation == "per_op":
        return f"throw __OpRefuse({cs_string_literal(oid)}, {message_cs});"
    raise ValueError(
        f"isolation must be one of {REFUSE_ISOLATIONS}, got {isolation!r}")


def cs_code_only(text: str) -> str:
    """Return *text* with C# comments and string literals blanked out.

    A contract check that greps a whole emission reads DATA as code: op ids
    are arbitrary strings by schema and travel into generated ``// ...``
    diagnostics, and user content (a note's text, a parameter name) travels
    into ``"..."`` literals.  An id spelled ``__t.RollBack()`` would then fail
    the guard contract, and a note quoting ``return __Refuse(`` would too —
    review findings №3 and №4.  Only what survives here is executable C#.

    Emitted C# has neither verbatim (``@"..."``) nor char literals — every
    literal comes from ``cs_string_literal`` — so ordinary escape handling is
    exact here.
    """

    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == '"':
            i += 1
            while i < n:
                if text[i] == "\\":
                    i += 2
                    continue
                if text[i] == '"':
                    i += 1
                    break
                i += 1
            out.append('""')
            continue
        if ch == "/" and text[i + 1:i + 2] == "/":
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        if ch == "/" and text[i + 1:i + 2] == "*":
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def cs_dense_code(text: str) -> str:
    """``cs_code_only`` with every whitespace character removed.

    Whitespace between C# tokens is meaningless, so a check on dense code
    also catches the token-equivalent spellings a future emitter could reach
    for by hand — ``__t . RollBack ( )``, ``__t/*x*/.RollBack()`` — which a
    raw substring search would miss (review finding №6).
    """

    return "".join(cs_code_only(text).split())


#: Whole-program refusal tokens, as (shown, dense) pairs.  Inside a create
#: block wrapped by per_op isolation NONE of them may appear: each either
#: destroys already-committed neighbours or returns from the whole Execute
#: body — the zero allowlist of review finding №9.
PROGRAM_REFUSAL_TOKENS = (
    ("__t.RollBack()", "__t.RollBack()"),
    ("return __Refuse(", "return__Refuse("),
)


def program_refusal_tokens(cs: str) -> list[str]:
    """Which whole-program refusal tokens survive in *cs*'s executable code."""

    dense = cs_dense_code(cs)
    return [shown for shown, packed in PROGRAM_REFUSAL_TOKENS
            if packed in dense]


def cs_line_comment_fragment(value: str) -> str:
    """Return *value* safe for one generated C# ``//`` comment.

    This is intentionally not identifier validation: op ids retain their
    full Unicode/data semantics in stamps, result keys, and references.  It
    only prevents a line terminator from ending a diagnostic comment and
    turning the remainder of an id into compilable source.
    """

    return value.translate(_CS_LINE_TERMINATOR_ESCAPES)
