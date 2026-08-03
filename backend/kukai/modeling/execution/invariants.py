"""Property invariants — cheap deterministic prechecks on CodeProposal.csharp_code
BEFORE the Roslyn compile gate (L3). Each rule has a stable ID (INV001-INV012)
so violations are stable across grep/log analysis.

Rules:
  INV001 — __result__ token present
  INV002 — exactly one `new Transaction(doc, "...")` block (no nesting, no sequential)
  INV003 — no banned APIs (TaskDialog, MessageBox.Show, Process.Start, File.Delete)
  INV004 — only allowed `using` namespaces (Autodesk.Revit, System, Microsoft, using static)
  INV005 — `RevitAPI` listed in requires_assemblies
  INV006 — csharp_code ≤ 300 lines
  INV007 — no hardcoded filesystem paths
  INV008 — every doc.GetElement(...) followed by null guard or `?.` chain
  INV009 — UnitTypeId.Millimeters used (never Feet in ConvertToInternalUnits)
  INV010 — t.Start() count == t.Commit() + t.RollBack() count (balanced)
  INV011 — no Thread.Sleep, async/await
  INV012 — CodeProposal.transaction_name exactly matches a `new Transaction(doc, "X")` string
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Literal

from kukai.modeling.schemas.llm import CodeProposal


InvariantSeverity = Literal["BLOCKING", "WARNING"]


@dataclass(frozen=True)
class InvariantViolation:
    rule_id: str                          # e.g. "INV001"
    message: str
    # Audit N12: typed Literal instead of plain str. Catches typos like
    # "blockign"/"BLOCKING " at mypy/pyright time, and downstream gate code
    # that reads .severity can rely on the closed set.
    severity: InvariantSeverity           # "BLOCKING" | "WARNING"


_BANNED_API_RE = re.compile(r"\b(TaskDialog|MessageBox\.Show|Process\.Start|File\.Delete)\b")
_ALLOWED_USING_PREFIXES = ("Autodesk.Revit.", "System.", "System;", "Microsoft.", "static ")
_PATH_LITERAL_RE = re.compile(r"""[\"@]?[A-Za-z]:[\\/]|/home/|\\\\""")
_GET_ELEMENT_RE = re.compile(r"\.GetElement\s*\([^)]*\)")
_TRANSACTION_OPEN_RE = re.compile(r"new\s+Transaction\s*\(\s*doc\s*,\s*\"([^\"]*)\"")
_T_START_RE = re.compile(r"\b\w+\s*\.\s*Start\s*\(\s*\)")
_T_COMMIT_RE = re.compile(r"\b\w+\s*\.\s*Commit\s*\(\s*\)")
_T_ROLLBACK_RE = re.compile(r"\b\w+\s*\.\s*RollBack\s*\(\s*\)")
_THREAD_SLEEP_RE = re.compile(r"\bThread\.Sleep\b")
_ASYNC_AWAIT_RE = re.compile(r"\b(async|await)\b")
_USING_LINE_RE = re.compile(r"^\s*using\s+([^;()=]+);", re.MULTILINE)


def _v(rule_id: str, message: str) -> InvariantViolation:
    return InvariantViolation(rule_id=rule_id, message=message, severity="BLOCKING")


def _strip_comments_only(code: str) -> str:
    """Remove line and block comments only. Preserves string contents verbatim
    (intentional — INV007 needs to see paths inside strings, since real-world
    dangerous paths only appear in string literals).

    Newlines inside block comments are preserved so line counts stay correct.
    """
    out: list[str] = []
    i = 0
    n = len(code)
    while i < n:
        ch = code[i]
        # Line comment // ... \n
        if ch == "/" and i + 1 < n and code[i + 1] == "/":
            j = code.find("\n", i)
            if j == -1:
                break
            i = j
            continue
        # Block comment /* ... */
        if ch == "/" and i + 1 < n and code[i + 1] == "*":
            j = code.find("*/", i + 2)
            if j == -1:
                break
            chunk = code[i + 2:j]
            out.append("\n" * chunk.count("\n"))
            i = j + 2
            continue
        # Otherwise (including string literal bodies): copy char verbatim
        out.append(ch)
        i += 1
    return "".join(out)


def _strip_comments_and_strings(code: str) -> str:
    """Replace C# comments and string literal contents with empty/whitespace
    so regex rules don't false-positive on patterns appearing inside docs
    or strings. Preserves newlines so INV006 line counting stays correct.

    State-machine handles:
    - // line comments        → replaced with empty (newline preserved)
    - /* block comments */    → replaced with newlines only
    - "regular strings"       → replaced with `""`
    - @"verbatim strings"     → replaced with `@""` (newlines preserved inside)
    - 'char literals'         → replaced with `''`
    """
    out: list[str] = []
    i = 0
    n = len(code)
    while i < n:
        ch = code[i]
        # Line comment // ... \n
        if ch == "/" and i + 1 < n and code[i + 1] == "/":
            # skip to newline (don't consume the newline itself)
            j = code.find("\n", i)
            if j == -1:
                break
            i = j
            continue
        # Block comment /* ... */
        if ch == "/" and i + 1 < n and code[i + 1] == "*":
            j = code.find("*/", i + 2)
            if j == -1:
                # unterminated — drop rest
                break
            # preserve newlines inside the comment so INV006 line count unaffected
            chunk = code[i + 2:j]
            out.append("\n" * chunk.count("\n"))
            i = j + 2
            continue
        # Verbatim string @"..."
        if ch == "@" and i + 1 < n and code[i + 1] == '"':
            j = i + 2
            while j < n:
                if code[j] == '"':
                    if j + 1 < n and code[j + 1] == '"':
                        j += 2  # escaped quote ""
                        continue
                    break
                j += 1
            # preserve as @"" and newlines inside
            inner = code[i + 2:j]
            out.append('@"' + "\n" * inner.count("\n") + '"')
            i = j + 1 if j < n else n
            continue
        # Regular string "..."
        if ch == '"':
            j = i + 1
            while j < n:
                if code[j] == "\\" and j + 1 < n:
                    j += 2
                    continue
                if code[j] == '"':
                    break
                if code[j] == "\n":
                    # unterminated single-line string — bail
                    break
                j += 1
            out.append('""')
            i = j + 1 if j < n else n
            continue
        # Char literal '...' (treat like string)
        if ch == "'":
            j = i + 1
            while j < n:
                if code[j] == "\\" and j + 1 < n:
                    j += 2
                    continue
                if code[j] == "'" or code[j] == "\n":
                    break
                j += 1
            out.append("''")
            i = j + 1 if j < n else n
            continue
        # Default: copy char
        out.append(ch)
        i += 1
    return "".join(out)


def check_proposal_invariants(proposal: CodeProposal) -> list[InvariantViolation]:
    raw_code = proposal.csharp_code
    code = _strip_comments_and_strings(raw_code)          # default for most rules
    code_comments_only = _strip_comments_only(raw_code)   # for INV007 (paths-in-strings)
    violations: list[InvariantViolation] = []

    # INV001 — __result__ output token (use stripped: __result__ in a comment is not executable)
    if "__result__" not in code:
        violations.append(_v("INV001", "csharp_code missing required __result__ output token"))

    # INV002 — count `new Transaction(...)` constructors. >1 == multiple transactions.
    tx_constructors_stripped = _TRANSACTION_OPEN_RE.findall(code)
    if len(tx_constructors_stripped) > 1:
        violations.append(_v("INV002",
            f"more than one Transaction constructor detected ({len(tx_constructors_stripped)}). "
            "Proposals must use a single Transaction (no nesting, no sequential transactions)."))

    # INV003 — banned APIs
    m = _BANNED_API_RE.search(code)
    if m:
        violations.append(_v("INV003", f"banned API call: {m.group(0)}"))

    # INV004 — every `using X;` import must start with allowed prefix
    for using_match in _USING_LINE_RE.finditer(code):
        clause = using_match.group(1).strip()
        if not any(clause.startswith(p.rstrip(";")) or clause == p.rstrip(";")
                   for p in _ALLOWED_USING_PREFIXES):
            violations.append(_v("INV004", f"disallowed using namespace: {clause!r}"))
            break

    # INV005 — RevitAPI declared
    if "RevitAPI" not in proposal.requires_assemblies:
        violations.append(_v("INV005", "RevitAPI missing from requires_assemblies"))

    # INV006 — length cap (stripped code preserves newlines)
    line_count = len(code.splitlines()) or 1
    if line_count > 300:
        violations.append(_v("INV006", f"csharp_code too long ({line_count} lines, max 300)"))

    # INV007 — no path literals. Uses comments-only stripped view because
    # real-world dangerous paths LIVE inside string literals (e.g.
    # `File.WriteAllText(@"C:\evil\backdoor.dll", payload)`). Stripping
    # strings would neuter this rule. Comments are still stripped to avoid
    # false-positives on URLs in `// see https://...` comments.
    if _PATH_LITERAL_RE.search(code_comments_only):
        violations.append(_v("INV007", "hardcoded filesystem path literal detected"))

    # INV008 — every `doc.GetElement(...)` must be followed (within 300 chars) by
    # a null check, `?.`, or `is null`/`is not null` pattern.
    for m in _GET_ELEMENT_RE.finditer(code):
        tail = code[m.end():m.end() + 300]
        guarded = any(s in tail for s in (
            "== null", "!= null", "?.", "!= null)", "is null", "is not null",
        ))
        if not guarded:
            violations.append(_v("INV008", "GetElement() result not null-guarded within 300 chars"))
            break

    # INV009 — UnitTypeId.Feet in a ConvertToInternalUnits call (wrong-unit smell)
    if "UnitTypeId.Feet" in code and "ConvertToInternalUnits" in code:
        violations.append(_v("INV009",
            "UnitTypeId.Feet used in ConvertToInternalUnits — coords must be Millimeters"))

    # INV010 — every opened Transaction must have a reachable terminator, and no
    # terminator may appear without an opening Start.
    #
    # NOT raw count-equality: defensive guard-clause RollBacks (e.g. rolling back
    # before `throw` in each null-check, plus a catch-all rollback) are GOOD
    # practice — they legitimately produce MORE terminators than Starts on a code
    # path where only one ever executes at runtime. The genuine defects are:
    #   * leak: a Start() with no reachable Commit/RollBack (Start count exceeds
    #     terminator count) — the transaction can be left open;
    #   * orphan: a Commit/RollBack with no Start() (copy-paste / wrong variable).
    starts = len(_T_START_RE.findall(code))
    commits = len(_T_COMMIT_RE.findall(code))
    rollbacks = len(_T_ROLLBACK_RE.findall(code))
    terminators = commits + rollbacks
    if starts > terminators:
        violations.append(_v("INV010",
            f"unterminated Transaction: Start={starts} exceeds Commit+RollBack={terminators} "
            "(a started transaction has no reachable Commit/RollBack)"))
    elif starts == 0 and terminators > 0:
        violations.append(_v("INV010",
            f"orphan Transaction terminator: Commit+RollBack={terminators} with no Start()"))

    # INV011 — no async/await/Thread.Sleep
    if _THREAD_SLEEP_RE.search(code) or _ASYNC_AWAIT_RE.search(code):
        violations.append(_v("INV011", "async/await/Thread.Sleep not permitted in bridge-executed code"))

    # INV012 — declared transaction_name must exactly match a Transaction constructor string.
    # Uses raw_code so the actual string contents are visible (stripping replaces them with "").
    tx_constructors_raw = _TRANSACTION_OPEN_RE.findall(raw_code)
    tx_names_in_code = set(tx_constructors_raw)
    if proposal.transaction_name not in tx_names_in_code:
        violations.append(_v("INV012",
            f"CodeProposal.transaction_name={proposal.transaction_name!r} "
            f"not found in any `new Transaction(doc, \"...\")` call "
            f"(found: {sorted(tx_names_in_code) or '<none>'})"))

    return violations
