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


# ── THE SINGLE CANON FOR HANDLING REVIT FAILURES ─────────────────────────
#
# Until 2026-08-20 this rule existed as FOUR copies of the same text —
# `authoring.py:7850` and `:8327`, `stairs_run_emit.py:434`,
# `stairs_landing_emit.py:587` — and nothing forced them to stay in sync.
# Three of the four did not accumulate the ERROR at all, i.e. a stair refusal
# arrived mute; all four erased the WARNING without letting it reach the receipt.
#
# The second point is the violation of the cardinal invariant, and it is the
# subtler of the two. Removing the warning is the CORRECT decision and stays:
# there is nobody to click the modal dialog, and Revit parks on the UI thread
# (the stairs incident). But "dismiss the dialog" and "forget what Revit said"
# are two different actions, and the `continue` before `Seen.Add` turned the
# first into the second. Revit says "I discarded your lock" (`DimensionUnlocked`,
# `UndeletedConstraints` — 58 `DimensionFailures` + 4 `ConstraintFailures` per
# `data/api_surface/`, zero drift across six versions), the program commits
# GREEN, and the building lacks a declared relationship.
#
# A warning's identity is the definition's GUID, NOT its text: the text is
# localized (the owner's Revit is Russian), and judging by it would mean
# comparing translations. `FailureDefinitionId.Guid` is the same across all
# six versions.
def failure_preprocessor_cs(class_name: str) -> str:
    """The text of the Revit failures preprocessor — ONE for all emitters.

    *class_name* stays a parameter: the names (`__KirMainFailures`,
    `__KirStairsFailures`) distinguish the scope — the main transaction versus
    `StairsEditScope` — while their body must be one and the same.

    🔴 WHY THE ERROR IS NO LONGER HANDED BACK TO REVIT. Before 2026-08-24 this
    said "a genuine ERROR is still handed back to Revit" and returned
    `Continue`. That looked like caution, but it was the ONLY cause of the
    modal dialog: `RevitAPI.xml` describes `Continue` verbatim — *"In the
    absence of any other available handlers, this means that the Revit user
    interface will display any errors to the user for resolution"*.

    A live measurement on 08-23 (transferring the MNVNK K3 building into
    "Project1"): three programs out of four rolled back with
    `transaction commit status: Pending`, while the owner spent that time
    closing an endless "keep elements joined or unjoin them" window. The
    window was not a consequence of the rollback but ITS CAUSE: while nobody
    answers, the commit hangs `Pending`.

    The correct sequence is documented at `ResolveFailure`: *"To
    prevent failure from being delivered to the user, failures (pre)processor
    should return ProceedWithCommit"*.

    🔴 AND THE SAME PLACE NAMES THE TRAP THE OWNER WALKED INTO WITH THEIR OWN
    HANDS: *"If attempt to resolve failure was not successful, and the same
    failure is present on repetitive calls ... the preprocessor code should
    take care to attempt a different resolution the next time the failure
    appears, to avoid an infinite loop"*. Their "you click Unjoin — the window
    pops up again, endlessly" is the very same loop, only played out by a
    human. Which is why there is EXACTLY ONE attempt here per kind of
    failure, and a repeat goes into rollback.

    THE "ERROR / WARNING" BOUNDARY STAYED, BUT IT NOW RUNS THROUGH A DIFFERENT
    PLACE. It used to be "remove the warning, hand the error to the human".
    Now it is "REMOVE the warning, RESOLVE the error ONCE AND NAME IT, and
    for one that cannot be resolved — ROLL BACK SILENTLY". Nothing is handed
    to the human: the bridge is headless by construction, and any question
    put to it is a hung commit.

    WHAT THIS DOES NOT MEAN. Resolving does NOT MUTE the fact: every resolved
    error travels into the receipt under a separate key `revit_errors_resolved`
    with the text, the elements, and the caption of the applied resolution.
    Revit decides on our behalf — which means the reader must see WHAT exactly
    it decided. A silent "resolved and forgotten" would be worse than the
    modal window: the window is at least visible.
    """

    return (
        f"private class {class_name} : IFailuresPreprocessor\n"
        f"{{\n"
        f"    // Ошибки КОПЯТСЯ, а не гасятся: программа, откатившаяся на\n"
        f"    // Commit, обязана назвать причину.\n"
        f"    public static List<string> Seen = new List<string>();\n"
        f"    // Предупреждения СНИМАЮТСЯ (иначе модальный диалог паркует\n"
        f"    // Revit) и ЗАПИСЫВАЮТСЯ (иначе программа зеленеет молча).\n"
        f"    public static List<object> Warned = new List<object>();\n"
        f"    // РАЗРЕШЁННЫЕ ОШИБКИ — третье ведро, и оно не сливается с двумя\n"
        f"    // первыми: «Revit решил за нас» это не предупреждение и не наш\n"
        f"    // отказ, а отдельный факт о модели.\n"
        f"    public static List<object> Resolved = new List<object>();\n"
        f"    // Счётчик попыток по роду отказа. RevitAPI.xml: ResolveFailure\n"
        f"    // БРОСАЕТ, если один и тот же отказ разрешают дважды тем же\n"
        f"    // типом, и требует «avoid an infinite loop».\n"
        f"    public static Dictionary<string, int> Attempts = new Dictionary<string, int>();\n"
        f"    public FailureProcessingResult PreprocessFailures(FailuresAccessor __fa)\n"
        f"    {{\n"
        f"        bool __resolvedAny = false;\n"
        f"        bool __unresolvable = false;\n"
        f"        foreach (var __f in __fa.GetFailureMessages())\n"
        f"        {{\n"
        f"            var __sev = __f.GetSeverity();\n"
        f"            var __ids = new List<string>();\n"
        f"            try {{ foreach (var __id in __f.GetFailingElementIds()) __ids.Add(__id.ToString()); }} catch {{ }}\n"
        f"            string __guid = \"?\";\n"
        f"            try {{ __guid = __f.GetFailureDefinitionId().Guid.ToString(); }} catch {{ }}\n"
        f"            string __text = \"\";\n"
        f"            try {{ __text = __f.GetDescriptionText(); }} catch {{ }}\n"
        f"            if (__sev == FailureSeverity.Warning)\n"
        f"            {{\n"
        f"                try {{\n"
        f"                    var __w = new Dictionary<string, object>();\n"
        f"                    __w[\"guid\"] = __guid; __w[\"text\"] = __text; __w[\"elements\"] = __ids;\n"
        f"                    Warned.Add(__w);\n"
        f"                }} catch {{ }}\n"
        f"                try {{ __fa.DeleteWarning(__f); }} catch {{ }}\n"
        f"                continue;\n"
        f"            }}\n"
        f"            // ОШИБКА. Записываем ВСЕГДА — до всякой попытки.\n"
        f"            try {{\n"
        f"                Seen.Add(__sev.ToString() + \": \" + __text\n"
        f"                    + (__ids.Count > 0 ? \" [элементы: \" + String.Join(\",\", __ids) + \"]\" : \"\"));\n"
        f"            }} catch {{ }}\n"
        f"            int __tried = 0;\n"
        f"            try {{ if (Attempts.ContainsKey(__guid)) __tried = Attempts[__guid]; }} catch {{ }}\n"
        f"            bool __has = false;\n"
        f"            try {{ __has = __f.HasResolutions(); }} catch {{ }}\n"
        f"            if (!__has || __tried >= 1)\n"
        f"            {{\n"
        f"                // Неразрешимая ИЛИ уже пробованная: второй заход тем\n"
        f"                // же типом Revit запрещает, а другого у нас нет.\n"
        f"                __unresolvable = true;\n"
        f"                continue;\n"
        f"            }}\n"
        f"            try {{\n"
        f"                Attempts[__guid] = __tried + 1;\n"
        f"                string __cap = \"\";\n"
        f"                try {{ __cap = __f.GetDefaultResolutionCaption(); }} catch {{ }}\n"
        f"                __fa.ResolveFailure(__f);\n"
        f"                __resolvedAny = true;\n"
        f"                var __r = new Dictionary<string, object>();\n"
        f"                __r[\"guid\"] = __guid; __r[\"text\"] = __text;\n"
        f"                __r[\"elements\"] = __ids; __r[\"resolution\"] = __cap;\n"
        f"                Resolved.Add(__r);\n"
        f"            }}\n"
        f"            catch {{ __unresolvable = true; }}\n"
        f"        }}\n"
        f"        // ПОРЯДОК ИСХОДОВ ЗНАЧИМ.\n"
        f"        // `Continue` не возвращается НИКОГДА при ошибке: он и есть\n"
        f"        // модальное окно (RevitAPI.xml, дословно).\n"
        f"        if (__unresolvable) return FailureProcessingResult.ProceedWithRollBack;\n"
        f"        if (__resolvedAny) return FailureProcessingResult.ProceedWithCommit;\n"
        f"        return FailureProcessingResult.Continue;\n"
        f"    }}\n"
        f"}}\n"
    )


def failure_channel_reset_cs(class_name: str, indent: str = "") -> str:
    """Reset of ALL buckets before a transaction. All of them, and always together.

    🔴 `Attempts` is reset on equal footing with the rest, and this is not
    housekeeping. The attempt counter is static, and within one Revit session
    programs run one after another: without zeroing it, the second program
    would see "this kind of failure was already tried" left by the FIRST one
    and would go straight to rollback without a single attempt of its own. The
    building-transfer measurement on 08-23 — 55 programs in a row in one
    process — means the cost of this bug would have been 54 false rollbacks.
    """

    return (f"{indent}{class_name}.Seen.Clear();\n"
            f"{indent}{class_name}.Warned.Clear();\n"
            f"{indent}{class_name}.Resolved.Clear();\n"
            f"{indent}{class_name}.Attempts.Clear();\n")


def failure_warnings_into_results_cs(class_name: str, indent: str = "") -> str:
    """Warnings go into the result, but ONLY when there were any.

    An empty key and a missing key are different facts: missing means "Revit
    stayed silent", an empty list would read as "we asked and got zero". We
    ask ALWAYS, so a missing key here is the honest zero.
    """

    return (f"{indent}if ({class_name}.Warned.Count > 0)\n"
            f"{indent}    __results[\"revit_warnings\"] = {class_name}.Warned;\n"
            # A RESOLVED ERROR IS A SEPARATE KEY, NOT A LINE AMONG THE WARNINGS.
            # Revit decided on our behalf (unjoined walls, for example), and the
            # reader must see EXACTLY THIS, not "there was some remark". Merging
            # them into one list would make Revit's decision indistinguishable
            # from our own observation.
            f"{indent}if ({class_name}.Resolved.Count > 0)\n"
            f"{indent}    __results[\"revit_errors_resolved\"] = {class_name}.Resolved;\n")
