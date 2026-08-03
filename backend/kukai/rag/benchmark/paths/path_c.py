"""Path C — compiler-driven retrieval feedback.

Hypothesis: production CS-error logs show 14k+ events where the repair loop
fails on the SAME error twice. The bottleneck is not initial retrieval —
it's that the repair prompt receives only the error TEXT, not a structural
fix pattern. Path C parses the CS-error, extracts the failing API symbol,
fetches a reference snippet from the corpus that demonstrates the correct
pattern, and injects it as "see how this should look" in the repair prompt.

Retrieval is delegated to Path A — same baseline. The novelty is the
repair_hint() override, which existing paths leave as None (so the runner
falls back to the LLMClient's stock text-only repair prompt).

Coverage of CS codes mirrors what we see in live_test.log:
  - CS1061: "X does not contain definition for Y" — most common,
    triggered by FilteredElementCollector.Cast/.Where/.Any/etc., or
    ElementId.IntegerValue (Revit 2024+ uses .Value).
  - CS0117: "X does not contain Y" (static member) — usually a wrong
    BuiltInParameter or BuiltInCategory name. Fix: LookupParameter fallback.
  - CS0246: "type or namespace 'X' not found" — DisplayUnitType (2024+),
    typos. We surface a related class snippet if found.

Roslyn localizes error text by user locale; Russian backends emit the
Cyrillic phrasing "не содержит определения". The parser handles both.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from kukai.rag.benchmark.paths.base import RAGPath, RAGResult, RepairHint
from kukai.rag.benchmark.paths.path_a import PathA
from kukai.rag.revit_api_index import ApiEntry, RevitApiIndex


# CS-error parser regexes. Roslyn formats are:
#   EN: 'FilteredElementCollector' does not contain a definition for 'Cast'
#   RU: "FilteredElementCollector" не содержит определения "Cast"
# Quote characters vary: ', ", “”, «». Account for all.
_QUOTE_CHARS = r"'\"‘’“”«»"
_QUOTE_CLASS = f"[{_QUOTE_CHARS}]"
_NAME_CHARS = r"[A-Za-z_][A-Za-z0-9_<>,\.\s]*?"  # allow generics/qualifiers, lazy

# Pattern A: CS1061-style "X does not contain definition for Y"
# (CS1061 emits "definition for Y", CS0117 emits "definition Y" without "for")
_CS_PATTERN_EN = re.compile(
    rf"CS(\d{{4}})\s*[:\.]?\s*"
    rf"{_QUOTE_CLASS}({_NAME_CHARS}){_QUOTE_CLASS}"
    r"\s+(?:does not contain|did not contain)"
    r"(?:\s+a\s+definition)?"
    rf"(?:\s+(?:for|of))?\s+"
    rf"{_QUOTE_CLASS}({_NAME_CHARS}){_QUOTE_CLASS}",
    re.IGNORECASE,
)
_CS_PATTERN_RU = re.compile(
    rf"CS(\d{{4}})\s*[:\.]?\s*"
    rf"{_QUOTE_CLASS}({_NAME_CHARS}){_QUOTE_CLASS}"
    r"\s+не\s+содержит\s+(?:определения|члена|метода|свойства)?\s*"
    rf"{_QUOTE_CLASS}({_NAME_CHARS}){_QUOTE_CLASS}",
    re.IGNORECASE | re.UNICODE,
)
# CS0246-style: "type or namespace name 'X' could not be found"
_CS0246_EN = re.compile(
    rf"CS(0246)\s*[:\.]?\s*"
    r"(?:the\s+)?type\s+or\s+namespace\s+name\s+"
    rf"{_QUOTE_CLASS}({_NAME_CHARS}){_QUOTE_CLASS}",
    re.IGNORECASE,
)
_CS0246_RU = re.compile(
    rf"CS(0246)\s*[:\.]?\s*"
    r"(?:не\s+удалось\s+найти\s+)?(?:тип|имя\s+типа|пространство\s+имен)\s+(?:или\s+\S+\s+)?"
    rf"{_QUOTE_CLASS}({_NAME_CHARS}){_QUOTE_CLASS}",
    re.IGNORECASE | re.UNICODE,
)

# LINQ method names that fail on FilteredElementCollector (FEC implements
# non-generic IEnumerable, so these unbounded extension methods don't bind).
# Same list as RevitCodeFixer._FEC_LINQ_METHODS, kept in sync.
_FEC_LINQ_METHODS = frozenset({
    "Cast", "Any", "First", "FirstOrDefault", "Single", "SingleOrDefault",
    "Last", "LastOrDefault", "Where", "Select", "OrderBy",
    "OrderByDescending", "GroupBy", "Take", "Skip", "ToList", "ToArray",
    "Count", "Sum", "Min", "Max",
})

# Reference patterns we look for inside corpus examples to validate they
# demonstrate the correct fix.
_OFTYPE_RE = re.compile(r"\.OfType<\w+>\(\)")
_LOOKUP_PARAM_RE = re.compile(r"\.LookupParameter\(\s*[\"']")


def _parse_cs_error(error_msg: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Parse a Roslyn CS-error into (code, class_name, member_name).

    Handles both English and Russian Roslyn output. Returns ``(None, None, None)``
    when the message doesn't match a known pattern; partial matches return
    None for missing fields.

    Examples:
        >>> _parse_cs_error('CS1061: "FilteredElementCollector" does not contain a definition for "Cast"')
        ('CS1061', 'FilteredElementCollector', 'Cast')
        >>> _parse_cs_error('CS0117: "BuiltInParameter" does not contain "STRUCTURAL_VOLUME"')
        ('CS0117', 'BuiltInParameter', 'STRUCTURAL_VOLUME')
        >>> _parse_cs_error('CS1061: "FilteredElementCollector" не содержит определения "Cast"')
        ('CS1061', 'FilteredElementCollector', 'Cast')
    """
    if not error_msg:
        return None, None, None

    # Try the X.Y patterns first (CS0117, CS1061) — both EN and RU
    for pattern in (_CS_PATTERN_EN, _CS_PATTERN_RU):
        m = pattern.search(error_msg)
        if m:
            code = f"CS{m.group(1)}"
            class_name = m.group(2).strip() if m.group(2) else None
            member_name = m.group(3).strip() if m.group(3) else None
            return code, class_name, member_name

    # CS0246 — single-symbol "type not found"
    for pattern in (_CS0246_EN, _CS0246_RU):
        m = pattern.search(error_msg)
        if m:
            code = f"CS{m.group(1)}"
            symbol = m.group(2).strip() if m.group(2) else None
            return code, symbol, None

    # Fall back to grabbing the bare CS-code if present, no symbols
    m = re.search(r"CS(\d{4})", error_msg)
    if m:
        return f"CS{m.group(1)}", None, None

    return None, None, None


def _find_reference_pattern(
    code: Optional[str],
    class_name: Optional[str],
    member_name: Optional[str],
    index: RevitApiIndex,
) -> Optional[tuple[str, str]]:
    """Locate a corpus example that demonstrates the correct pattern.

    Returns ``(snippet, why_text)`` or None if no good reference exists.

    Strategy:
      - CS1061 + FilteredElementCollector + LINQ method → find an example
        that uses ``.OfType<T>()`` before LINQ. This is the #1 production fix.
      - CS1061 + ElementId.IntegerValue/Value → fixer alone handles this
        deterministically; surface a recipe-style hint anyway.
      - CS0117 + BuiltInParameter.X → find an example using LookupParameter
        as the safe fallback when the BuiltInParameter constant doesn't exist.
      - CS0246 + symbol → search for a class entry matching the symbol.
    """
    if not code:
        return None

    if not index.loaded:
        index.load()
    entries = index._entries  # noqa: SLF001 — internal access by design (mirrors PathA pattern)
    if not entries:
        return None

    # Case 1: FEC.LINQ — the workhorse. Find any class example using OfType<T>().
    if (
        code == "CS1061"
        and class_name
        and "FilteredElementCollector" in class_name
        and member_name
        and member_name in _FEC_LINQ_METHODS
    ):
        snippet = _scan_for_pattern(entries, _OFTYPE_RE, must_contain="FilteredElementCollector")
        if snippet:
            why = (
                "FilteredElementCollector реализует non-generic IEnumerable, "
                f"поэтому LINQ-метод .{member_name}() на нём не биндится. "
                "Вставь .OfType<T>() перед LINQ — это даёт IEnumerable<T> "
                "с которым LINQ работает корректно."
            )
            return snippet, why
        # Even without a snippet, return a synthetic minimal example so
        # the repair LLM still gets a structural pattern.
        synthetic = (
            "var elements = new FilteredElementCollector(doc)\n"
            "    .OfClass(typeof(Wall))\n"
            "    .OfType<Wall>()       // <-- bridges to IEnumerable<T>\n"
            f"    .{member_name}();    // now LINQ binds"
        )
        why = (
            "FilteredElementCollector реализует non-generic IEnumerable, "
            f"поэтому LINQ-метод .{member_name}() на нём не биндится. "
            "Вставь .OfType<T>() перед LINQ."
        )
        return synthetic, why

    # Case 2: ElementId member access (Revit version differences)
    if (
        code in ("CS1061", "CS0117")
        and class_name == "ElementId"
        and member_name in ("IntegerValue", "Value")
    ):
        if member_name == "IntegerValue":
            synthetic = (
                "// Revit 2024+: ElementId.Value (long) replaces IntegerValue (int)\n"
                "long id = element.Id.Value;"
            )
            why = (
                "В Revit 2024+ свойство ElementId.IntegerValue удалено, "
                "вместо него используется .Value (тип long, не int)."
            )
        else:
            synthetic = (
                "// Revit 2021-2023: ElementId.IntegerValue (int)\n"
                "int id = element.Id.IntegerValue;"
            )
            why = (
                "В Revit 2021-2023 у ElementId нет свойства .Value — "
                "используй .IntegerValue (тип int)."
            )
        return synthetic, why

    # Case 3: BuiltInParameter / BuiltInCategory — wrong member name
    if (
        code == "CS0117"
        and class_name
        and class_name in ("BuiltInParameter", "BuiltInCategory")
    ):
        snippet = _scan_for_pattern(entries, _LOOKUP_PARAM_RE, must_contain="LookupParameter")
        if snippet:
            why = (
                f"BuiltInParameter.{member_name} не существует в этой версии "
                "Revit API. Используй LookupParameter(\"имя\") как fallback — "
                "он находит параметр по человекочитаемому имени и работает "
                "независимо от версии."
            )
            return snippet, why
        synthetic = (
            "// Fallback when BuiltInParameter constant is missing:\n"
            "Parameter p = element.LookupParameter(\"Length\");\n"
            "double v = p?.AsDouble() ?? 0.0;"
        )
        why = (
            f"BuiltInParameter.{member_name} не существует в этой версии. "
            "Используй LookupParameter с именем параметра."
        )
        return synthetic, why

    # Case 4: CS0246 — type not found. Search corpus for the class.
    if code == "CS0246" and class_name:
        for entry in entries:
            if entry.entry_type == "class" and entry.name == class_name:
                if entry.examples:
                    return entry.examples[0], (
                        f"Тип {class_name} существует в Autodesk.Revit.DB. "
                        "Проверь using-директиву и точное написание."
                    )
        # Common cross-version pitfall
        if class_name == "DisplayUnitType":
            synthetic = (
                "// Revit 2024+: DisplayUnitType заменён на ForgeTypeId / UnitTypeId\n"
                "double mm = UnitUtils.ConvertFromInternalUnits(\n"
                "    value, UnitTypeId.Millimeters);"
            )
            return synthetic, (
                "DisplayUnitType удалён в Revit 2024+. Используй UnitTypeId / "
                "ForgeTypeId через UnitUtils.ConvertFromInternalUnits."
            )

    # No match — let the runner fall back to text-only hint.
    return None


def _scan_for_pattern(
    entries: list[ApiEntry],
    pattern_re: re.Pattern[str],
    must_contain: str = "",
    max_chars: int = 400,
) -> Optional[str]:
    """Scan all entry examples for a snippet matching ``pattern_re``.

    Returns the first matching example, optionally trimmed around the match
    so the caller gets a focused snippet (~max_chars). Skips entries whose
    examples don't contain the required substring (e.g. require the example
    to mention FilteredElementCollector for an OfType fix).
    """
    for entry in entries:
        for ex in entry.examples:
            if must_contain and must_contain not in ex:
                continue
            if not pattern_re.search(ex):
                continue
            return _trim_snippet(ex, pattern_re, max_chars=max_chars)
    return None


def _trim_snippet(snippet: str, focus_re: re.Pattern[str], max_chars: int) -> str:
    """Trim ``snippet`` around the first match of ``focus_re``, keeping
    surrounding context up to ``max_chars`` total. Preserves line boundaries.
    """
    if len(snippet) <= max_chars:
        return snippet
    m = focus_re.search(snippet)
    if not m:
        return snippet[:max_chars]
    half = max_chars // 2
    start = max(0, m.start() - half)
    end = min(len(snippet), m.end() + half)
    # Snap to newline boundaries so the snippet stays compilable-ish.
    nl_start = snippet.rfind("\n", 0, start)
    if nl_start != -1:
        start = nl_start + 1
    nl_end = snippet.find("\n", end)
    if nl_end != -1:
        end = nl_end
    chunk = snippet[start:end]
    if start > 0:
        chunk = "// ...\n" + chunk
    if end < len(snippet):
        chunk = chunk + "\n// ..."
    return chunk


class PathC(RAGPath):
    """Compiler-driven retrieval feedback.

    Retrieval = Path A (delegate). Repair = parse CS-error → fetch reference
    pattern from corpus → inject as structured hint.
    """

    name = "C_compiler_feedback"

    def __init__(self, base_path: Optional[PathA] = None) -> None:
        # Delegate retrieval entirely to Path A. We share its enricher / index
        # so we don't pay the load cost twice.
        self._base = base_path if base_path is not None else PathA()

    @property
    def _index(self) -> RevitApiIndex:
        """Access the underlying Revit API index via the delegated PathA."""
        self._base._enricher.ensure_loaded()  # noqa: SLF001
        return self._base._enricher._index   # noqa: SLF001

    def enrich(
        self,
        query: str,
        context: Optional[dict[str, Any]] = None,
    ) -> RAGResult:
        # Pure delegation. Path C's novelty is in repair_hint(), not retrieval.
        return self._base.enrich(query, context)

    def repair_hint(
        self,
        query: str,
        failed_code: str,
        compile_errors: list[dict[str, Any]],
        context: Optional[dict[str, Any]] = None,
    ) -> Optional[RepairHint]:
        """Compose a repair hint from the first parseable CS-error.

        Iterates errors in order; uses the first one we can extract a
        reference pattern for. Returning None means the caller should fall
        back to the stock text-only repair prompt.
        """
        if not compile_errors:
            return None

        index = self._index
        parsed_errors: list[tuple[str, Optional[str], Optional[str]]] = []
        for err in compile_errors:
            msg = err.get("message") or ""
            # Some callers pass "code" separately; prepend it so the parser
            # can find it even if the message text omits the code prefix.
            code_hint = err.get("code") or ""
            if code_hint and code_hint.upper() not in msg.upper():
                msg = f"{code_hint}: {msg}"
            code, class_name, member_name = _parse_cs_error(msg)
            if code is None:
                continue
            parsed_errors.append((code, class_name, member_name))

            ref = _find_reference_pattern(code, class_name, member_name, index)
            if ref is None:
                continue
            snippet, why = ref
            cls_disp = class_name or "?"
            mem_disp = member_name or "?"
            extra_context = (
                f"ОШИБКА: {code} на {cls_disp}.{mem_disp}\n"
                f"ПОЧЕМУ: {why}\n"
                "КАК ИСПРАВИТЬ — пример из корпуса:\n"
                f"```csharp\n{snippet}\n```"
            )
            return RepairHint(
                extra_context=extra_context,
                metadata={
                    "code": code,
                    "class_name": class_name,
                    "member_name": member_name,
                    "snippet_chars": len(snippet),
                    "errors_seen": len(compile_errors),
                },
            )

        # We parsed errors but found no reference patterns.
        if parsed_errors:
            return RepairHint(
                extra_context="",
                metadata={
                    "code": parsed_errors[0][0],
                    "class_name": parsed_errors[0][1],
                    "member_name": parsed_errors[0][2],
                    "no_reference": True,
                    "errors_seen": len(compile_errors),
                },
            )
        return None
