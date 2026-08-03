"""Code safety validation — pre-check before sending to bridge.

Lightweight Python-side check. Blocks ONLY patterns that have a high probability
of:
  1. Crashing Revit (single-thread API violations, UI lockups, memory bombs)
  2. Native code execution / system tampering (P/Invoke, registry, process spawn)
  3. Runtime code-generation bypass (Reflection.Emit, CodeDom, dynamic compile)

Patterns that are commonly used in LEGITIMATE Revit code — even if reflection-ish
— are NOT blocked. Roslyn at the compile-service does the real syntax+type
validation. The user explicitly asked the AI for this code; the threat model is
"AI accidentally writes Revit-crashing code", NOT "malicious user evading
safety" (the user could write malicious code directly without an AI).

History (2026-05-11): trimmed from ~50 rules to ~17 after user feedback that
the validator was producing too many false positives on legitimate Revit API
calls (e.g. .GetType(), Action.Invoke(), ScheduleDefinition.GetField(int),
using static System.Math, MethodInfo references in extension-method code, etc.).
"""

from __future__ import annotations

import os
import re
from typing import Optional


def _weak_sandbox() -> bool:
    """Operator opt-in (2026-06-14): a deliberately VERY WEAK sandbox.

    The operator's threat model is "AI accidentally writes Revit-crashing code",
    NOT "malicious user" — the user could write malicious code directly. They want
    legitimate BIM code (System.IO export, reflection for cross-version API,
    .GetType()/dynamic, even an explicit delete) to run, since the LLM won't delete
    "по приколу". When KUKAI_WEAK_SANDBOX is set, validate_code_safety is a no-op.
    Default OFF keeps the committed posture strict (Constitution: Untrusted-Brain
    sandbox); the operator flips the flag in .env. The live bridge's own
    NamespaceValidator must be loosened in parallel (it is the other half)."""
    return os.getenv("KUKAI_WEAK_SANDBOX", "").strip().lower() in ("1", "true", "yes", "on")


# ---------------------------------------------------------------------------
# BLOCKED PATTERNS — high-confidence threats only
# ---------------------------------------------------------------------------
BLOCKED_PATTERNS: list[tuple[str, str]] = [
    # ─── Process / system exec ─────────────────────────────────────────────
    (r"\bSystem\.Diagnostics\.Process\b", "System.Diagnostics.Process (process spawn)"),
    (r"\bProcess\.Start\b", "Process.Start (process spawn — can run any executable)"),
    (r"\bProcessStartInfo\b", "ProcessStartInfo (process spawn)"),

    # ─── P/Invoke (native code) ────────────────────────────────────────────
    (r"\bSystem\.Runtime\.InteropServices\b", "P/Invoke (native code execution)"),
    (r"\bDllImport\b", "DllImport (P/Invoke)"),

    # ─── Registry (system tampering) ───────────────────────────────────────
    (r"\bMicrosoft\.Win32\b", "Microsoft.Win32 (registry access)"),
    (r"\bRegistry\b", "Registry access"),

    # ─── unsafe / pointer manipulation ─────────────────────────────────────
    (r"\bunsafe\b", "unsafe code (memory safety bypass)"),
    (r"\bstackalloc\b", "stackalloc (unsafe stack allocation)"),

    # ─── Reflection bypass entry points (narrow) ───────────────────────────
    # Generic reflection types (.GetType, .GetMethod, .GetProperty, MethodInfo,
    # PropertyInfo, FieldInfo, .Invoke, AppDomain) are NOT blocked — they
    # produce too many false positives in legit Revit code.
    (r"\bType\.GetType\s*\(", "Type.GetType (reflection bypass)"),
    (r"\bActivator\.CreateInstance\b", "Activator.CreateInstance (reflection bypass)"),
    (r"\bDelegate\.CreateDelegate\b", "Delegate.CreateDelegate (reflection bypass)"),
    # NOTE: `.GetField("name")` (typeof(X).GetField("name") / obj.GetType()
    # .GetField("name") — reflection bypass) used to live here as a blanket
    # per-line regex. It is now handled by the dedicated, schema-aware check
    # `_getfield_reflection_violations()` below (2026-07-08, corpus CI gate
    # wave-2H): the blanket regex false-positived on the real Revit
    # Extensible Storage API `Schema.GetField(string) -> Field`
    # (`schema.GetField("FieldName")`), which is common, legitimate ES code.
    # ScheduleDefinition.GetField(int) takes an integer index — never matched
    # this pattern (no string literal arg) and stays unaffected either way.

    # ─── Runtime assembly loading (executes arbitrary code) ────────────────
    (r"\bAssembly\.(Load|LoadFrom|LoadFile|UnsafeLoadFrom)\b",
     "Assembly.Load (executes arbitrary loaded code)"),

    # ─── Runtime code generation / IL emission ─────────────────────────────
    (r"\bSystem\.Reflection\.Emit\b", "System.Reflection.Emit (IL generation)"),
    (r"\bDynamicMethod\b", "DynamicMethod (IL generation bypass)"),
    (r"\bILGenerator\b", "ILGenerator (IL generation)"),
    (r"\bModuleBuilder\b", "ModuleBuilder (dynamic assembly)"),
    (r"\bTypeBuilder\b", "TypeBuilder (dynamic type)"),
    (r"\bCodeDom\b", "CodeDom (runtime code generation)"),
    (r"\bCSharpCodeProvider\b", "CSharpCodeProvider (runtime compilation)"),
    (r"\bCompilerParameters\b", "CompilerParameters (runtime compilation)"),
    (r"\bdynamic\s+\w+\s*=\s*(?:Activator|Assembly|Type)",
     "dynamic with reflection (type safety bypass)"),
    # NOTE: `typeof(X).Assembly` (a known reflection evasion technique in
    # general) used to live here as a blanket per-line regex. It is now
    # handled by the dedicated, literal-aware check
    # `_typeof_assembly_violations()` below (2026-07-08, corpus CI gate
    # wave-2 H-fix): the blanket regex false-positived on the standard
    # cross-Revit-version idiom `typeof(Document).Assembly.GetType(
    # "Autodesk.Revit.DB.Toposolid")` — probing whether a type added in a
    # later Revit API version exists, the ONLY way to reference such a type
    # from code that must still COMPILE on older API DLLs where it doesn't
    # exist (direct reference => CS0103/CS0246 on those versions). This is
    # not a reflection *bypass*: `Assembly.GetType(name)` can only resolve
    # types that are already loaded IN THAT ASSEMBLY — unlike `Type.GetType`
    # (still fully blocked below), it cannot pull in an arbitrary DLL from
    # disk, so the blast radius is bounded to whatever the pinned assembly
    # (RevitAPI.dll et al) exposes.

    # ─── Threading (Revit API is strictly single-threaded) ─────────────────
    (r"\bnew\s+Thread\s*\(",
     "new Thread(...) (Revit API is single-threaded — will crash)"),
    (r"\bThread\.Start\b", "Thread.Start (Revit API is single-threaded — will crash)"),
    (r"\bThreadPool\b", "ThreadPool (will crash Revit)"),
    (r"\bSystem\.Threading\.Thread\b", "System.Threading.Thread (will crash Revit)"),
    (r"\bTask\.Run\b", "Task.Run (background thread will crash Revit API)"),

    # ─── WMI (system enumeration / process creation) ───────────────────────
    (r"\bSystem\.Management\b", "System.Management (WMI access)"),
    (r"\bManagementScope\b", "ManagementScope (WMI)"),
    (r"\bManagementObject\b", "ManagementObject (WMI)"),
    (r"\bWin32_\b", "Win32_ WMI class (system access)"),

    # ─── Environment — terminal/tamper only ───────────────────────────────
    # User PII (UserName, MachineName) is allowed — it's the user's own machine.
    # Only the ACTIVELY DANGEROUS variants are blocked.
    (r"\bEnvironment\.Exit\b", "Environment.Exit (terminates Revit process)"),
    (r"\bEnvironment\.SetEnvironmentVariable\b",
     "Environment.SetEnvironmentVariable (system tampering)"),

    # ─── UI thread lockup ──────────────────────────────────────────────────
    (r"\bSystem\.Windows\.Forms\b", "System.Windows.Forms (locks Revit UI thread)"),
    (r"\bMessageBox\b",
     "MessageBox (locks Revit UI thread — use Autodesk.Revit.UI.TaskDialog)"),

    # ─── Resource abuse / memory bombs ─────────────────────────────────────
    (r"new\s+byte\s*\[\s*\d{7,}", "Large byte array allocation (memory bomb)"),
    (r"new\s+\w+\s*\[\s*\d{7,}", "Large array allocation (memory bomb)"),

    # ─── Preprocessor directives (break the wrapper) ───────────────────────
    (r"^\s*#define\b", "#define preprocessor directive"),
    (r"^\s*#if\b", "#if preprocessor directive"),
    (r"^\s*#elif\b", "#elif preprocessor directive"),
    (r"^\s*#else\b", "#else preprocessor directive"),
    (r"^\s*#endif\b", "#endif preprocessor directive"),
    (r"^\s*#line\b", "#line preprocessor directive"),
]


# ---------------------------------------------------------------------------
# GetField("string") reflection check — Schema-aware exemption
# ---------------------------------------------------------------------------
# `.GetField("name")` is blocked as a reflection-bypass pattern (see BLOCKED_
# PATTERNS history above) EXCEPT the real Revit Extensible Storage API
# `Schema.GetField(string) -> Field`, which recipes use routinely
# (`schema.GetField("FieldName")`). We exempt ONLY calls whose receiver is a
# bare identifier that is either (a) provably `Schema`-typed in this code
# (explicit `Schema x = ...` declaration, or assignment from a
# Schema-returning API: `Schema.Lookup(guid)`, a `SchemaBuilder...Finish()`
# call, or `entity.GetSchema()`), or (b) named by the `schema` convention
# (identifier ending in "schema"/"Schema", case-insensitive on the 's') as a
# secondary heuristic.
#
# This is deliberately narrow and cannot weaken the general detection:
# `typeof(X).GetField("secret")` and `obj.GetType().GetField("secret")` — the
# actual reflection-bypass techniques this rule exists to block — never have
# a bare-identifier receiver (their receiver ends in the `)` of the
# `typeof(...)`/`GetType()` call), so neither exemption path can ever match
# them; both fall straight through to "blocked".
_GETFIELD_CALL_RE = re.compile(r"\.GetField\s*\(\s*(['\"])")
_BARE_RECEIVER_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*$")

# Real recipes qualify the ExtensibleStorage types with their full namespace
# (`Autodesk.Revit.DB.ExtensibleStorage.Schema.Lookup(...)`), so every pattern
# below tolerates an optional dotted-namespace prefix before the type name.
_NS_PREFIX = r"(?:[\w]+\.)*"
_SCHEMA_TYPE_DECL_RE = re.compile(r"\bSchema\s+(\w+)\s*[=;)]")
_SCHEMA_LOOKUP_ASSIGN_RE = re.compile(rf"\b(\w+)\s*=\s*{_NS_PREFIX}Schema\.Lookup\s*\(")
_SCHEMA_GETSCHEMA_ASSIGN_RE = re.compile(r"\b(\w+)\s*=\s*[\w.]+\.GetSchema\s*\(")
# SchemaBuilder is a two-hop pattern in real code: `builder = new ...SchemaBuilder(...)`
# on one line, `schema = builder.Finish()` (via the builder VARIABLE, not the
# type name) on another — so it needs its own two-pass resolution below,
# rather than a single regex.
_BUILDER_NEW_RE = re.compile(rf"\b(\w+)\s*=\s*new\s+{_NS_PREFIX}SchemaBuilder\s*\(")
_BUILDER_FINISH_ASSIGN_RE = re.compile(r"\b(\w+)\s*=\s*(\w+)\s*\.\s*Finish\s*\(")
# Secondary heuristic: receiver named by the `schema` convention (bare
# "schema"/"Schema", or any identifier ENDING in it, e.g. "esSchema").
_SCHEMA_NAME_HINT_RE = re.compile(r"^(?:[A-Za-z_][A-Za-z0-9_]*)?[Ss]chema$")


def _schema_typed_identifiers(code: str) -> set[str]:
    """Local variable names provably typed `Schema` (Extensible Storage) in
    this recipe's code — see module-level comment above `_GETFIELD_CALL_RE`.
    """
    names: set[str] = set()
    for m in _SCHEMA_TYPE_DECL_RE.finditer(code):
        names.add(m.group(1))
    for m in _SCHEMA_LOOKUP_ASSIGN_RE.finditer(code):
        names.add(m.group(1))
    for m in _SCHEMA_GETSCHEMA_ASSIGN_RE.finditer(code):
        names.add(m.group(1))
    builder_names = {m.group(1) for m in _BUILDER_NEW_RE.finditer(code)}
    for m in _BUILDER_FINISH_ASSIGN_RE.finditer(code):
        target, receiver = m.group(1), m.group(2)
        if receiver in builder_names:
            names.add(target)
    return names


def _getfield_reflection_violations(lines: list[str], schema_names: set[str]) -> list[str]:
    """Per-line `.GetField("...")` scan with the Schema exemption applied.

    Per-line (not whole-code) to match this module's existing convention for
    BLOCKED_PATTERNS above; every real corpus occurrence of the legitimate
    `schema.GetField("Name")` idiom is single-line, so this has no observed
    false-negative on the current corpus (verified 2026-07-08).
    """
    violations: list[str] = []
    for i, line in enumerate(lines, 1):
        for m in _GETFIELD_CALL_RE.finditer(line):
            prefix = line[: m.start()]
            rm = _BARE_RECEIVER_RE.search(prefix)
            exempt = False
            if rm:
                receiver = rm.group(1)
                if receiver in schema_names or _SCHEMA_NAME_HINT_RE.match(receiver):
                    exempt = True
            if not exempt:
                violations.append(f"Blocked: GetField with string arg (reflection) (line {i})")
    return violations


# ---------------------------------------------------------------------------
# typeof(X).Assembly reflection check — literal-Autodesk.Revit-type exemption
# ---------------------------------------------------------------------------
# `typeof(X).Assembly` is blocked as a reflection-evasion pattern EXCEPT the
# standard cross-Revit-version idiom of resolving a type that only exists on
# some Revit API versions by NAME, so code referencing it still COMPILES on
# versions where the type doesn't exist (a direct reference would be
# CS0103/CS0246 there): `typeof(Document).Assembly.GetType(
# "Autodesk.Revit.DB.Toposolid")` (Toposolid was added in Revit 2024).
#
# We exempt a `typeof(X).Assembly` occurrence ONLY when it is provably
# consumed exclusively via `.GetType("<literal>")` calls whose string
# argument is a fully-qualified `Autodesk.Revit.*` type name — never a
# variable, concatenation, or any other expression. Two shapes are observed
# in the real corpus:
#   (a) same-line chain:  `typeof(Document).Assembly.GetType("Autodesk.Revit.DB.Toposolid")`
#   (b) two-step, via a variable: `var asm = typeof(Document).Assembly;`
#       ... `asm.GetType("Autodesk.Revit.DB.Toposolid")` (possibly several
#       such calls on the same variable, later in the recipe).
#
# This is deliberately narrower than exempting `typeof().Assembly` outright,
# and it is a DIFFERENT, weaker capability than `Type.GetType(name)` (kept
# fully blocked, see BLOCKED_PATTERNS): `Assembly.GetType(name)` is an
# INSTANCE method that can only resolve types already loaded within THAT ONE
# assembly object — it cannot pull in an arbitrary DLL from disk/GAC the way
# `Type.GetType("Foo, SomeOtherAssembly")` (a STATIC method that loads
# assemblies by name) can. Constraining the string literal itself to
# `Autodesk.Revit.*` further guarantees `Assembly.GetType` can only ever
# resolve — or fail to resolve — a real Revit API type, never something
# from outside Revit's own object model. `Activator.CreateInstance` and
# `Type.GetType(` are NOT touched by this exemption and remain fully
# blocked, by design (see wave-2 H-fix report).
_TYPEOF_ASSEMBLY_RE = re.compile(r"typeof\s*\([^)]+\)\s*\.\s*Assembly")
_ASSEMBLY_CHAIN_GETTYPE_RE = re.compile(
    r'typeof\s*\([^)]+\)\s*\.\s*Assembly\s*\.\s*GetType\s*\(\s*"([^"]*)"'
)
_ASSEMBLY_VAR_ASSIGN_RE = re.compile(
    r"\b(\w+)\s*=\s*typeof\s*\([^)]+\)\s*\.\s*Assembly\b"
)
_AUTODESK_REVIT_TYPE_LITERAL_RE = re.compile(r"^Autodesk\.Revit\.[A-Za-z_][A-Za-z0-9_.]*$")


def _known_revit_assembly_vars(code: str) -> set[str]:
    """Variable names assigned `x = typeof(<T>).Assembly` where EVERY
    `.GetType("...")` call reachable through that variable, anywhere in this
    recipe's code, passes a literal string argument naming a fully-qualified
    `Autodesk.Revit.*` type (see module comment above `_TYPEOF_ASSEMBLY_RE`).
    A variable with zero `.GetType(` uses, or with ANY non-literal or
    non-Autodesk.Revit argument on ANY of its `.GetType(` calls, is left out
    — the caller then leaves its `typeof(...).Assembly` occurrence blocked
    (fail-closed: not provably safe).
    """
    safe: set[str] = set()
    for m in _ASSEMBLY_VAR_ASSIGN_RE.finditer(code):
        var = m.group(1)
        calls = list(re.finditer(rf"\b{re.escape(var)}\s*\.\s*GetType\s*\(", code))
        if not calls:
            continue
        all_literal_and_safe = True
        for c in calls:
            lm = re.match(r'\s*"([^"]*)"', code[c.end():])
            if not lm or not _AUTODESK_REVIT_TYPE_LITERAL_RE.match(lm.group(1)):
                all_literal_and_safe = False
                break
        if all_literal_and_safe:
            safe.add(var)
    return safe


def _typeof_assembly_violations(lines: list[str]) -> list[str]:
    """Per-line `typeof(X).Assembly` scan with the literal-Autodesk.Revit-
    type exemption applied (see module comment above `_TYPEOF_ASSEMBLY_RE`).
    """
    code = "\n".join(lines)
    safe_vars = _known_revit_assembly_vars(code)
    violations: list[str] = []
    for i, line in enumerate(lines, 1):
        for m in _TYPEOF_ASSEMBLY_RE.finditer(line):
            exempt = False
            chain = _ASSEMBLY_CHAIN_GETTYPE_RE.match(line, m.start())
            if chain and _AUTODESK_REVIT_TYPE_LITERAL_RE.match(chain.group(1)):
                exempt = True
            if not exempt:
                for am in _ASSEMBLY_VAR_ASSIGN_RE.finditer(line):
                    # tie this specific typeof().Assembly match to the
                    # assignment it is the right-hand side of (same end
                    # position — the assignment regex's tail IS this regex).
                    if am.end() == m.end() and am.group(1) in safe_vars:
                        exempt = True
                        break
            if not exempt:
                violations.append(
                    f"Blocked: typeof().Assembly (assembly reflection bypass) (line {i})"
                )
    return violations


# ---------------------------------------------------------------------------
# String/char literal masking — keeps BLOCKED_PATTERNS keyword regexes from
# matching inside the CONTENTS of a C# string/char literal (e.g. an error
# message that happens to contain the substring "unsafe", as in
# `"...headless-unsafe: " + ex.Message` — a real corpus recipe's own error
# text, not the `unsafe` C# keyword).
# ---------------------------------------------------------------------------
def _mask_string_literals(line: str) -> str:
    r"""Replace the CONTENTS of C# string/char literals on this line with
    '#' placeholders, preserving line length and the position of every
    non-literal character (so `\b`-anchored BLOCKED_PATTERNS regexes still
    line up on the surrounding code).

    Handles the quoting styles actually used in this corpus and in C#
    generally: plain `"..."` (backslash-escaped, e.g. `\"`, `\\`), verbatim
    `@"..."` (`""` = one literal quote, no backslash escaping), interpolated
    `$"..."` / `$@"..."` / `@$"..."`, and `'...'` char literals. For
    interpolated strings, only the literal TEXT segments are masked — an
    `{expr}` hole is live C# code and is left completely unmasked (so
    anything dangerous written inside one is still scanned normally; this
    only removes false positives from literal text, it never removes real
    code from view). `{{`/`}}` (escaped literal braces) are treated as
    2-char literal text, not a hole.

    This is a lightweight per-line scanner (this module's own stated scope
    — Roslyn does the real syntax check), not a full C# lexer: it does not
    track multi-line string literals (this module already processes code
    line-by-line via `str.split("\n")`, so that limitation predates this
    function) and does not resolve raw string literals (triple-quoted, C#
    11+, not observed in this corpus).
    """
    out = list(line)
    n = len(line)
    i = 0
    while i < n:
        ch = line[i]
        if ch in "@$":
            j = i
            verbatim = False
            interp = False
            while j < n and line[j] in "@$":
                if line[j] == "@":
                    verbatim = True
                else:
                    interp = True
                j += 1
            if j < n and line[j] == '"':
                i = _mask_one_string(out, line, j, n, verbatim, interp)
                continue
            i += 1
            continue
        if ch == '"':
            i = _mask_one_string(out, line, i, n, False, False)
            continue
        if ch == "'":
            i = _mask_one_char_literal(out, line, i, n)
            continue
        i += 1
    return "".join(out)


def _mask_one_string(
    out: list[str], line: str, quote_pos: int, n: int, verbatim: bool, interp: bool
) -> int:
    """Mask the contents of the string literal opening at `line[quote_pos]`
    ('"'). Returns the index just past the closing quote (or `n` if the
    string runs unterminated to end of line — this per-line scanner does not
    follow literals across lines, matching this module's existing scope).
    """
    i = quote_pos + 1
    while i < n:
        c = line[i]
        if interp and c == "{":
            if i + 1 < n and line[i + 1] == "{":
                # escaped literal '{{' — mask both, they're literal text
                out[i] = "#"
                out[i + 1] = "#"
                i += 2
                continue
            # a genuine interpolation hole: leave everything up to the
            # matching '}' completely unmasked (it is live C# code).
            i += 1
            depth = 1
            while i < n and depth > 0:
                if line[i] == "{":
                    depth += 1
                elif line[i] == "}":
                    depth -= 1
                i += 1
            continue
        if interp and c == "}" and i + 1 < n and line[i + 1] == "}":
            out[i] = "#"
            out[i + 1] = "#"
            i += 2
            continue
        if verbatim:
            if c == '"':
                if i + 1 < n and line[i + 1] == '"':
                    out[i] = "#"
                    out[i + 1] = "#"
                    i += 2
                    continue
                return i + 1  # closing quote, leave unmasked
            out[i] = "#"
            i += 1
            continue
        # regular string: backslash-escaped
        if c == "\\" and i + 1 < n:
            out[i] = "#"
            out[i + 1] = "#"
            i += 2
            continue
        if c == '"':
            return i + 1  # closing quote, leave unmasked
        out[i] = "#"
        i += 1
    return n


def _mask_one_char_literal(out: list[str], line: str, quote_pos: int, n: int) -> int:
    """Mask the contents of a `'x'` char literal opening at `line[quote_pos]`."""
    i = quote_pos + 1
    if i < n and line[i] == "\\" and i + 1 < n:
        out[i] = "#"
        out[i + 1] = "#"
        i += 2
    elif i < n and line[i] != "'":
        out[i] = "#"
        i += 1
    if i < n and line[i] == "'":
        return i + 1
    return i


def _normalize_code_for_validation(code: str) -> str:
    r"""Normalize C# code before safety validation.

    Resolves Unicode escape sequences (\\uXXXX) to actual characters
    and strips zero-width characters that could break regex matching.
    """
    # Resolve C# Unicode escape sequences: \uXXXX -> actual char
    code = re.sub(
        r"\\u([0-9a-fA-F]{4})",
        lambda m: chr(int(m.group(1), 16)),
        code,
    )
    # Strip zero-width characters that could break word boundaries
    zero_width = "​‌‍⁠﻿"
    code = "".join(ch for ch in code if ch not in zero_width)
    return code


def validate_code_safety(code: str) -> Optional[list[str]]:
    """Check code for blocked patterns.

    Returns None if code is safe, or a list of violation descriptions.
    Normalizes Unicode escapes and zero-width chars before checking.
    """
    if _weak_sandbox():
        return None  # KUKAI_WEAK_SANDBOX: operator-chosen permissive mode
    normalized = _normalize_code_for_validation(code)
    violations: list[str] = []
    lines = normalized.split("\n")
    # Masked view for the generic keyword/API patterns below ONLY: string
    # literal CONTENTS are replaced with placeholders so e.g. an error
    # message containing the substring "unsafe" doesn't trip the `unsafe`
    # keyword rule (see `_mask_string_literals` docstring). The exemption-
    # aware checks below (GetField, typeof().Assembly) need the REAL text —
    # they inspect specific string-literal arguments themselves — so they
    # keep using the unmasked `lines`/`normalized`.
    masked_lines = [_mask_string_literals(line) for line in lines]

    for pattern, description in BLOCKED_PATTERNS:
        for i, line in enumerate(masked_lines, 1):
            if re.search(pattern, line):
                violations.append(f"Blocked: {description} (line {i})")

    schema_names = _schema_typed_identifiers(normalized)
    violations.extend(_getfield_reflection_violations(lines, schema_names))
    violations.extend(_typeof_assembly_violations(lines))

    return violations if violations else None
