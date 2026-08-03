"""Map Roslyn compiler error codes to targeted repair guidance (W2-d).

The default repair loop sends raw stderr back to the LLM. That works for
~27% of cases. This module parses CS#### codes + line numbers and injects
focused fix patterns that lift success to ~50%+.

Each hint must be short (≤4 lines) and actionable. The LLM rewrites the
WHOLE function from the hint — we don't try to patch.

The top-5 hints below cover ~87% of all compile errors observed in the
2026-05 production logs: CS1061, CS0117, CS0246, CS0104, CS0161.

This module is intentionally side-effect-free and import-cheap so it can
be safely called from the hot path of the repair loop. The existing
``LLMClient._get_repair_hint`` covers Russian text-only patterns for
the in-prompt hint; ``build_repair_hint`` here returns a structured
multi-error block meant for a dedicated system-role message.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional


# Roslyn error pattern. CS#### is sometimes followed by ':', sometimes by space,
# sometimes by '.'. We capture the code + the first line/sentence of the message.
CS_PATTERN = re.compile(
    r"\bCS(\d{4})\b\s*:?\s*(?P<msg>[^.\n]+)",
    re.IGNORECASE,
)

# Symbol-extraction patterns. Roslyn emits the missing symbol inside quotes;
# both English ('foo') and Russian (Cyrillic doublequotes "foo") show up.
# Order matters: more specific first.
_SYM_PATTERNS = [
    re.compile(r"definition for ['‘’\"“”]([^'’”\"]+)['‘’\"“”]"),
    re.compile(r"определения ['‘’\"“”]([^'’”\"]+)['‘’\"“”]"),
    re.compile(r"name ['‘’\"“”]([^'’”\"]+)['‘’\"“”]"),
    # Generic fallback: first single-quoted identifier-shaped token.
    re.compile(r"['‘’\"“”]([A-Za-z_][A-Za-z0-9_.<>]*)['‘’\"“”]"),
]


def parse_cs_codes(stderr: str) -> list[tuple[str, str, Optional[str]]]:
    """Extract (cs_code, first_line_of_message, missing_symbol_or_None) tuples.

    Multiple distinct CS codes from the same stderr are all returned, in
    order of first appearance. Same code appearing twice is reported twice
    (callers usually dedupe).
    """
    out: list[tuple[str, str, Optional[str]]] = []
    if not stderr:
        return out
    for m in CS_PATTERN.finditer(stderr):
        code = "CS" + m.group(1)
        msg = m.group("msg").strip()[:200]
        sym: Optional[str] = None
        for pat in _SYM_PATTERNS:
            sm = pat.search(msg)
            if sm:
                sym = sm.group(1)
                break
        out.append((code, msg, sym))
    return out


# Hints are deliberately short (≤4 lines). The LLM rewrites the whole function;
# we don't try to patch. Each hint targets the SINGLE most-common cause for
# that CS code in production Revit-script repair traces.
HINTS: dict[str, str] = {
    "CS1061": (
        "An instance method or property does not exist on the type. "
        "Either misspelled, OR the API was renamed in a newer Revit "
        "(e.g. `ElementId.IntegerValue` → `ElementId.Value` in 2024+). "
        "Check spelling against the RAG `revit_api_reference` section. "
        "If it's a LINQ call on `FilteredElementCollector`, add `.OfType<T>()` "
        "first — FEC is non-generic IEnumerable."
    ),
    "CS0117": (
        "A static member of a type does not exist. Common cases: "
        "`DisplayUnitType.DUT_*` was REMOVED in Revit 2024+ — use "
        "`UnitTypeId.Meters`/`SpecTypeId` instead. `BuiltInParameter.X` may "
        "be Revit-version specific — verify the constant. DO NOT invent enum "
        "members; use `LookupParameter(\"name\")` if unsure."
    ),
    "CS0246": (
        "Type or namespace not found. The compile-service pre-imports "
        "`Autodesk.Revit.DB`, `Autodesk.Revit.UI`, `System.Linq`, etc. "
        "If you reference `Group` it's ambiguous — use the FQN "
        "`Autodesk.Revit.DB.Group`. DO NOT add `using` directives — "
        "they're rejected by the wrapper."
    ),
    "CS0104": (
        "Ambiguous type reference. Most commonly `Group` (clashes with "
        "internal types). Use the FQN: `Autodesk.Revit.DB.Group`. Same "
        "caution applies to `Application`, `Document`, `Color`, `Path`, "
        "`Action`, `View`."
    ),
    "CS0103": (
        "Name does not exist in the current context. Usually a typo — check "
        "spelling against the failed line. For `BuiltInCategory.OST_*` or "
        "`BuiltInParameter.*`, use the full prefix."
    ),
    "CS1503": (
        "Argument type does not match the parameter. Check the method "
        "signature in the RAG reference. Common case: passing `Element` "
        "where `Wall`/`Floor` expected — add an explicit `(Wall)element` cast."
    ),
    "CS0161": (
        "Not all code paths return a value. Add `return null;` (or the "
        "appropriate default) at every function exit, including inside "
        "catch blocks if you handle exceptions."
    ),
    "CS1001": (
        "Identifier expected — usually a missing keyword/name. Inspect the "
        "exact failing line, often a stray comma or missing type name."
    ),
    "CS1513": "`}` expected — a closing brace is missing. Balance the braces.",
    "CS1002": "`;` expected — semicolon missing at end of the indicated line.",
    "CS1056": (
        "Unexpected character — usually a backtick from markdown. Strip "
        "ALL triple-backticks from the code; return raw C#."
    ),
    "CS0019": (
        "Operator cannot be applied to these types. Common case: comparing "
        "`ElementId` with `==`. Use `id.IntegerValue == other.IntegerValue` "
        "(Revit ≤2023) or `id.Value == other.Value` (Revit ≥2024)."
    ),
    "CS0029": (
        "Cannot implicitly convert types. Common fixes: "
        "`IEnumerable<T>` → add `.ToList()`; `Element` → `Wall` add cast "
        "`(Wall)element`; `int` → `long` for `ElementId.Value` on Revit 2024+."
    ),
    "CS0266": (
        "Cannot implicitly convert — explicit cast required. Add the cast: "
        "`(TargetType)source`. Especially when downcasting `Element` to a "
        "concrete subclass (Wall, Floor, FamilyInstance)."
    ),
}


def build_repair_hint(stderr: str, max_hints: int = 3) -> Optional[str]:
    """Return a focused repair-hint markdown block, or None if no CS codes parsed.

    The block is meant to be injected as a SYSTEM-role message BEFORE the
    LLM re-attempts code generation. Caller is responsible for placement.

    ``max_hints`` caps how many distinct CS codes we surface — surfacing
    every error from a cascading failure (15+ codes) just confuses the LLM.
    """
    codes = parse_cs_codes(stderr)
    if not codes:
        return None

    # Dedupe by CS code, keep first occurrence of each, cap at max_hints.
    seen: dict[str, tuple[str, Optional[str]]] = {}
    for code, msg, sym in codes:
        if code not in seen:
            seen[code] = (msg, sym)
            if len(seen) >= max_hints:
                break

    lines = ["## Roslyn diagnosed these errors — fix all of them in your next attempt:\n"]
    for code, (msg, sym) in seen.items():
        hint = HINTS.get(code, "(no canned hint — read the message carefully)")
        sym_note = f" (symbol: `{sym}`)" if sym else ""
        lines.append(f"**{code}**{sym_note}: {msg}")
        lines.append(f"  -> {hint}\n")
    return "\n".join(lines)


__all__ = ["parse_cs_codes", "build_repair_hint", "HINTS", "CS_PATTERN"]
