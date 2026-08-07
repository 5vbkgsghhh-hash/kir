"""Our emitted C# read against Autodesk's documented refusals.

api_trap_index.py records what Autodesk says.  This tool is the other half:
it walks the C# WE emit, resolves the API members we touch, and asks the index
what each of them is documented to refuse.  Where a documented condition meets
code that does not handle it, that is a group-shaped bug waiting for the model
that triggers it.

The group bug was not a missing feature.  The C# was there, the try/catch was
there, and the catch was `catch (Exception)` writing one line into a receipt.
Nothing crashed; 96.77% of the groups simply were not in the output, and the
run reported success.  So "is it wrapped in a try?" is the wrong question, and
this tool does not ask it.  It sorts call sites into three states:

    unguarded  — the documented exception escapes.  Loud, and therefore the
                 kind we find quickly.
    blanket    — caught by `catch { }` or `catch (Exception)`.  Nothing
                 crashes and the data is gone.  This is the group shape, and
                 it is the state worth being afraid of.
    specific   — the catch names the documented exception type.  Someone knew.

Ranking is by blast radius, not by count: a property read once per element of
every model outranks a method called by one op that runs when a user asks for
it.  The formula is printed with the report, because a ranking whose rule is
hidden is a ranking nobody can argue with.

The ranking's sharpest term comes out of the index rather than out of our code.
"A non-optional argument was null" is documented on 3 800 members; it is a
house style, not a warning, and 285 of our calls sit under it.  "The rotation
property is not supported for the Element related to this LocationPoint" is
documented on exactly one.  So each condition is weighted by how many members
share its wording: a sentence Autodesk wrote once was written about something
in particular, and that is the sentence that costs 2 846 groups.

Everything in this tool is OUR INFERENCE and is labelled as such in the output.
Resolving `__lp.Rotation` to `P:Autodesk.Revit.DB.LocationPoint.Rotation` means
reading a variable's type out of the surrounding text, and text is not a
compiler.  Every finding carries the confidence it was reached with, and the
verbatim Autodesk quote next to our file and line, so a human can settle it in
seconds instead of trusting the score.

    python tools/api_trap_audit.py
    python tools/api_trap_audit.py --top 10
    python tools/api_trap_audit.py --member Rotation
    python tools/api_trap_audit.py --json /tmp/audit.json
"""

from __future__ import annotations

import argparse
import ast
import collections
import json
import pathlib
import re
import sys

_TOOLS = pathlib.Path(__file__).resolve().parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from api_trap_index import (  # noqa: E402
    DEFAULT_DB, VERSIONS, conditions_of, open_db, span)

BACKEND = _TOOLS.parent

# Where our C# lives.  The read path (decompile/query) and the write path
# (authoring/emitters) are scanned together because a trap does not care which
# of our two worlds it is in.
SCAN_ROOTS = ("kukai/ir", "kukai/query", "kukai/write", "kukai/audit",
              "kukai/modeling", "kukai/llm/tool_handlers", "kukai/norm_control.py",
              "kukai/qa_checks.py")

# Files whose C# runs over EVERY element of EVERY model that is decompiled, as
# opposed to running when one op is used.  This is the multiplier that made the
# group bug cost 2 846 rows instead of one: not the severity of the trap, the
# number of elements walked past it.
WHOLE_MODEL = re.compile(
    r"kukai/(ir/decompile|query)/|kukai/ir/(open_model|serving)\.py")

# A line of C#, as opposed to a line of Python that happens to contain a dot.
# Cheap on purpose: everything it lets through is checked against the index,
# and a name the API never documented simply finds nothing.
_CSHARPY = re.compile(
    r"(?:\bvar\b|\bnew\b|;|\{|\}|=>|\bif\s*\(|\bforeach\b|\breturn\b)")

# recv.Member — the receiver and the member, with the member PascalCase as
# every documented API member is, and our own `__`-prefixed locals excluded
# from being mistaken for types.
_ACCESS = re.compile(r"([A-Za-z_][\w.]*?)\s*\.\s*([A-Z]\w*)")
_NEW = re.compile(r"\bnew\s+([A-Z]\w*)\s*\(")

# How our emitted C# names the type of a local.  Four shapes cover the corpus:
# `x as T`, `T x =`, `foreach (T x in`, `(T)x`.
_AS_CAST = re.compile(r"\b(\w+)\s*=\s*[^;]*?\bas\s+([A-Z][\w.]*)")
_DECL = re.compile(r"\b([A-Z][\w.]*)\s+(__?\w+)\s*=")
_FOREACH = re.compile(r"\bforeach\s*\(\s*([A-Z][\w.]*)\s+(\w+)\s+in\b")
_HARD_CAST = re.compile(r"\(\s*([A-Z][\w.]*)\s*\)\s*(\w+)")

# Receiver names our codebase uses with one fixed meaning everywhere.  This is
# a convention of ours, not a fact of the API, so it is kept short and stated.
HOUSE_RECEIVERS = {"doc": "Autodesk.Revit.DB.Document"}

# A C# string literal in our emitted code is text, not a call.  Without this,
# `__grStep = "Group.Location/LocationPoint.Point";` -- a progress label -- is
# read as touching LocationPoint.Point.
_CS_STRING = re.compile(r'"(?:[^"\\]|\\.)*"')

# `x.Member =` is a write; everything else is a read.  It matters because a
# condition that begins "Setting this property..." says nothing about reading
# it, and LocationPoint.Point is exactly that case: the setter is documented
# to refuse, the getter is the one we call, and conflating them would put a
# non-bug at the top of the report next to the real one.
_ASSIGNED = re.compile(r"^\s*=(?!=)")

# Autodesk marks a setter-only condition in three ways, and only the first is
# obvious.  Missing the other two put "When setting this property: sheetNumber
# is an empty string" at the top of a report about code that only ever READS
# SheetNumber -- a false alarm dressed as a verbatim quote.
_SETTER_ONLY = re.compile(r"^setting\b|when setting\b|\bis set\b", re.I)

# `try {` and a bare `try` with the brace on the next line are both ours, and
# reading only the first form reported geometry_store's guarded read as
# unguarded -- a false alarm, which is the one output this report cannot
# afford if anyone is to trust the rest of it.
_TRY = re.compile(r"\btry\b\s*(?:\{|$)")
_CATCH = re.compile(r"\bcatch\s*\(\s*([\w.]+)")
_BARE_CATCH = re.compile(r"\bcatch\s*\{")
_LOOPY = re.compile(r"\bforeach\s*\(|\bfor\s*\(|\bwhile\s*\(")
_LAMBDA_LOOP = re.compile(r"\.(?:Select|Where|ForEach|Any|All|Sum)\s*\(")

# try/catch is not the only way our C# declines to walk into a documented
# condition, and reading only try/catch is why BOTH FailuresAccessor.
# DeleteWarning sites were reported UNGUARDED at rank 11 on 2026-07-29 -- while
# each one is reached only through `if (… GetSeverity() == FailureSeverity.
# Warning)`, which is Autodesk's condition ("Severity of failure is not
# FailureSeverity::Warning") tested by hand, one line up.
#
# A test is not proof that it tests THIS condition, so a checked site is
# DEMOTED, never discharged: exposure drops from 2 to 1 and the site prints as
# CHECKED, which is an invitation to settle it against the quote rather than an
# answer.  Silently zeroing it would repeat the mistake this tool exists to
# catch, one level up.
_IF_TEST = re.compile(r"\bif\s*\(")

# Receivers that are C# or BCL, not Revit.  Without this, `long.Parse(...)`
# resolves to ElementId.Parse purely because `Parse` happens to be unique
# inside the Revit API -- a confident answer to a question about a different
# language's standard library.
NOT_REVIT = {
    "long", "int", "uint", "short", "byte", "double", "float", "decimal",
    "bool", "char", "string", "object", "var", "Math", "Convert", "String",
    "Int32", "Int64", "Double", "Boolean", "Guid", "DateTime", "TimeSpan",
    "Array", "Enum", "Encoding", "File", "Path", "Directory", "Console",
    "Environment", "Regex", "StringBuilder", "Task", "Thread", "Type",
    "Exception", "Nullable", "Tuple", "Activator", "Assembly", "Uri",
    "JsonConvert", "JsonSerializer", "Enumerable", "Queryable", "Buffer",
    "BitConverter", "Stopwatch", "Debug", "Trace", "Process", "Culture",
    "CultureInfo", "Attribute", "Marshal", "GC", "Random", "Version",
}


# --------------------------------------------------------------------------
# conditions whose truth is not decided by the model
# --------------------------------------------------------------------------
# This tool ranks FUTURE BUGS: a documented condition that some model, some
# day, will satisfy.  A condition whose truth is already fixed before the run
# is a different animal, and mixing the two put three non-bugs -- 64 call sites
# -- into the top eleven on 2026-07-29 and pushed the one real finding (KIR
# authoring reaching project-only API from a family document) down to rank 19.
#
#   static  the condition is about an argument our source passes as a
#           compile-time literal.  `OfClass(typeof(Wall))` either always throws
#           or never does, identically in every model; the Roslyn gate and the
#           emission corpus decide it long before a user does.
#   house   the condition is about a value this codebase binds in exactly one
#           place, stated here rather than inferred (the same standing as
#           HOUSE_RECEIVERS above).
#
# Neither is deleted.  Both are printed in their own section with the reason
# and the sites, because a finding that disappears is how the group bug lived
# for a year.  And each rule is a PREDICATE OVER THE SITE TEXT, never a member
# on a suppression list: it holds only while the property that makes it safe is
# still visible.  Turn `typeof(Wall)` into a runtime `Type` variable, or pass
# something other than `doc` to a Transaction, and the finding returns by
# itself.
_TYPEOF_ARG = re.compile(r"\.OfClass\(\s*typeof\(\s*[A-Za-z_][\w.]*\s*\)\s*\)")
_TXN_ON_HOUSE_DOC = re.compile(r"\bnew\s+Transaction\(\s*doc\s*[,)]")

DISCHARGES: tuple[tuple[str, str, str, re.Pattern, str], ...] = (
    (
        "static",
        "FilteredElementCollector.OfClass",
        "input type is not a subclass of Element",
        _TYPEOF_ARG,
        "the argument is a compile-time typeof() literal, so this cannot "
        "become true for one model and not another",
    ),
    (
        "house",
        "Transaction.#ctor",
        "Document is a linked file",
        _TXN_ON_HOUSE_DOC,
        "`doc` is bound once, by the bridge, to app.ActiveUIDocument.Document "
        "(src/Kukai.Revit.Bridge/Execution/RevitExternalEventHandler.cs:119). "
        "A linked document is reachable only through RevitLinkInstance."
        "GetLinkDocument(), and every one of ours is a read (element counts, "
        "bounding boxes) that opens no transaction",
    ),
)


def discharge_of(member_key: str, condition_text: str,
                 uses: list[dict]) -> tuple[str, str] | None:
    """(kind, reason) when no site leaves this condition to the model."""
    for kind, member_mark, condition_mark, pattern, reason in DISCHARGES:
        if member_mark not in member_key:
            continue
        if condition_mark.lower() not in condition_text.lower():
            continue
        # One site that does not carry the property is enough to keep the
        # whole condition live: the discharge describes our code, and our
        # code has to actually be that way everywhere.
        if all(pattern.search(use["text"]) for use in uses):
            return kind, reason
    return None


# --------------------------------------------------------------------------
# getting at the C#
# --------------------------------------------------------------------------

class Chunk:
    """A run of C# text and the file line each of its lines came from."""

    def __init__(self, path: pathlib.Path, lines: list[tuple[int, str]]):
        self.path = path
        self.lines = lines


def chunks_from_cs(path: pathlib.Path) -> list[Chunk]:
    text = path.read_text(encoding="utf-8", errors="replace")
    return [Chunk(path, list(enumerate(text.splitlines(), 1)))]


def chunks_from_python(path: pathlib.Path) -> list[Chunk]:
    """Every string literal in the module that looks like C#, with real lines.

    Going through the AST rather than grepping means an f-string fragment is
    seen as one piece of C# with its interpolations marked, instead of as a
    Python line with braces in it.  Interpolated values become a placeholder:
    what they contain never changes WHICH API member is being touched, which is
    the only thing this scan is after.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return []
    # Docstrings are the one kind of string that reliably TALKS ABOUT C#
    # without being any.  Ours are Russian prose full of API names, and left
    # in they produce findings pointing at a comment.
    skip = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if (isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                skip.add(id(first.value))
        # ast.walk yields an f-string AND each literal piece inside it, so the
        # same emitted line arrives twice and every count downstream doubles.
        if isinstance(node, ast.JoinedStr):
            for part in node.values:
                if isinstance(part, ast.Constant):
                    skip.add(id(part))
    chunks: list[Chunk] = []
    for node in ast.walk(tree):
        if id(node) in skip:
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            text, start = node.value, node.lineno
            # A triple-quoted template's lineno points at its opening quote,
            # so the body starts on the next line.
            if "\n" in text:
                start += 1
        elif isinstance(node, ast.JoinedStr):
            pieces = []
            for part in node.values:
                if isinstance(part, ast.Constant) and isinstance(
                        part.value, str):
                    pieces.append(part.value)
                else:
                    pieces.append("«x»")
            text, start = "".join(pieces), node.lineno
        else:
            continue
        if not _CSHARPY.search(text) or "." not in text:
            continue
        lines = [(start + offset, line)
                 for offset, line in enumerate(text.splitlines())]
        if lines:
            chunks.append(Chunk(path, lines))
    return chunks


def scan_files(backend: pathlib.Path,
               include_tests: bool = False) -> list[pathlib.Path]:
    """Shipped emitters by default.

    Golden .cs files are the same C# a second time, already counted at the
    emitter that produced it, and a finding pointing at a golden names a line
    nobody would edit to fix anything.
    """
    found: list[pathlib.Path] = []
    for root in SCAN_ROOTS:
        target = backend / root
        if target.is_file():
            found.append(target)
            continue
        if not target.is_dir():
            continue
        for path in sorted(target.rglob("*")):
            if path.suffix not in (".py", ".cs") and not path.name.endswith(
                    ".cs.j2"):
                continue
            if "__pycache__" in path.parts:
                continue
            is_test = ("tests" in path.parts or "golden" in path.parts
                       or path.name.startswith("test_"))
            if is_test and not include_tests:
                continue
            found.append(path)
    return found


# --------------------------------------------------------------------------
# what the C# says
# --------------------------------------------------------------------------

def local_types(chunk: Chunk) -> dict[str, str]:
    """Variable -> type name, as far as the surrounding text admits."""
    types = dict(HOUSE_RECEIVERS)
    for _, line in chunk.lines:
        for variable, type_name in _AS_CAST.findall(line):
            types[variable] = type_name
        for type_name, variable in _DECL.findall(line):
            if type_name not in ("var", "Func", "Action", "Dictionary",
                                 "List", "String"):
                types[variable] = type_name
        for type_name, variable in _FOREACH.findall(line):
            types[variable] = type_name
        for type_name, variable in _HARD_CAST.findall(line):
            types.setdefault(variable, type_name)
    return types


def _blocks(chunk: Chunk, opener: re.Pattern) -> list[tuple[int, int, int]]:
    """(first line, last line, index of the opening line) for each block.

    Brace counting over emitted C# is not a parser and does not need to be.
    Our two guard shapes -- the one-liner `try { … } catch { }` and a `try {`
    block a few lines long -- are both within reach of counting braces from
    the line that opened them.  A block whose braces never balance (an
    f-string fragment holding only the opening half) simply runs to the end of
    its own chunk, which is the honest reading of a fragment.
    """
    found = []
    for index, (number, line) in enumerate(chunk.lines):
        if not opener.search(line):
            continue
        depth = 0
        started = False
        for offset in range(index, len(chunk.lines)):
            text = chunk.lines[offset][1]
            depth += text.count("{") - text.count("}")
            started = started or "{" in text
            if started and depth <= 0:
                found.append((number, chunk.lines[offset][0], offset))
                break
        else:
            found.append((number, chunk.lines[-1][0], len(chunk.lines) - 1))
    return found


def guard_state(chunk: Chunk) -> dict[int, str]:
    """Per line: which exception type, if any, a surrounding catch names.

    The catch is read from where it actually is -- after the try block closes,
    which is usually a different line than the call being guarded.  Reading it
    only from the current line was reporting "catch ?" for the majority of our
    guards and grading them all as blanket.
    """
    state: dict[int, str] = {}
    for first, last, index in _blocks(chunk, _TRY):
        caught = None
        for offset in range(index, min(index + 3, len(chunk.lines))):
            tail = chunk.lines[offset][1]
            named = _CATCH.search(tail)
            if named:
                caught = named.group(1)
                break
            if _BARE_CATCH.search(tail):
                caught = "«bare»"
                break
        if caught is None:
            continue  # a try whose catch we cannot see: claim nothing
        for number, _ in chunk.lines:
            if first <= number <= last:
                state[number] = caught
    return state


def loop_state(chunk: Chunk) -> set[int]:
    """Lines that sit inside a loop, rather than lines in a chunk with a loop.

    Chunk-wide loop detection made `Transaction.Start` look like it runs once
    per element because the same template also iterates a collector further
    down, which inflates the reach of everything in a long template.
    """
    inside: set[int] = set()
    for first, last, _ in _blocks(chunk, _LOOPY):
        for number, _ in chunk.lines:
            if first <= number <= last:
                inside.add(number)
    for number, line in chunk.lines:
        if _LAMBDA_LOOP.search(line):
            inside.add(number)
    return inside


def conditional_columns(chunk: Chunk) -> dict[int, int]:
    """Per line: the column past which a statement runs only if a test passed.

    Two shapes cover our emitted C#, and the FailuresAccessor pair needs both:
    the test and the call on one line (`if (__sev == FailureSeverity.Warning)
    { __fa.DeleteWarning(__f); … }`), and a braceless `if (…)` whose body is
    the next line.  A multi-line body marks only its first line, which
    UNDER-reports -- the safe direction for a report whose whole value is that
    it does not cry wolf.
    """
    governed: dict[int, int] = {}
    lines = chunk.lines
    for index, (number, line) in enumerate(lines):
        match = _IF_TEST.search(line)
        if not match:
            continue
        depth, end = 0, None
        for pos in range(match.end() - 1, len(line)):
            if line[pos] == "(":
                depth += 1
            elif line[pos] == ")":
                depth -= 1
                if depth == 0:
                    end = pos + 1
                    break
        if end is None:
            continue
        governed[number] = min(governed.get(number, end), end)
        if not line[end:].strip().lstrip("{").strip():
            for offset in range(index + 1, len(lines)):
                if lines[offset][1].strip():
                    governed[lines[offset][0]] = 0
                    break
    return governed


def accesses(chunk: Chunk) -> list[dict]:
    """Every `receiver.Member` and `new Type(` the chunk contains."""
    types = local_types(chunk)
    guards = guard_state(chunk)
    loops = loop_state(chunk)
    tested = conditional_columns(chunk)
    out = []
    for number, line in chunk.lines:
        stripped = line.strip()
        if stripped.startswith("//") or stripped.startswith("#"):
            continue
        # A statement, not a sentence that happens to name a class.
        if not any(token in stripped for token in ";({="):
            continue
        caught = guards.get(number)
        governed_from = tested.get(number)

        def state(column: int) -> tuple[str, str]:
            if caught:
                return "guarded", caught
            if governed_from is not None and column >= governed_from:
                return "checked", ""
            return "none", ""

        common = {"line": number, "text": stripped[:200], "in_loop": number in loops}
        code = _CS_STRING.sub('""', line)
        for match in _ACCESS.finditer(code):
            receiver, member = match.group(1), match.group(2)
            name = receiver.split(".")[-1]
            if name in NOT_REVIT:
                continue
            guard, caught_name = state(match.start())
            out.append({**common, "guard": guard, "caught": caught_name,
                        "receiver": name, "member": member,
                        "static_hint": types.get(name),
                        "writes": bool(_ASSIGNED.match(code[match.end():]))})
        for match in _NEW.finditer(code):
            type_name = match.group(1)
            if type_name in NOT_REVIT:
                continue
            guard, caught_name = state(match.start())
            out.append({**common, "guard": guard, "caught": caught_name,
                        "receiver": type_name, "member": "#ctor",
                        "static_hint": type_name, "writes": True})
    return out


# --------------------------------------------------------------------------
# joining our text to Autodesk's facts
# --------------------------------------------------------------------------

class Resolver:
    """Names in our C# -> documented member keys, with our confidence in it."""

    def __init__(self, db):
        self.db = db
        self.by_simple: dict[str, list[str]] = collections.defaultdict(list)
        self.types: set[str] = set()
        self.overloads: dict[tuple[str, str], int] = collections.Counter()
        # Overloads are resolved by presence, not by arrival order.  Our C# is
        # untyped text, so which overload a call binds to is not knowable here
        # -- but picking whichever came first out of the table made
        # UnitUtils.ConvertToInternalUnits report "[2021]", the version span of
        # the DisplayUnitType overload Revit dropped in 2022, for a call that
        # compiles against all six.  The widest-lived overload is the honest
        # default, and the count is carried so the reader knows a choice was
        # made.
        widest: dict[tuple[str, str], tuple[int, str]] = {}
        for key, owner, simple, kind, versions in db.execute(
                "SELECT key, owner, simple, kind, versions FROM member "
                "WHERE owner LIKE 'Autodesk.Revit.%'"):
            if kind == "T":
                self.types.add(simple)
                continue
            self.by_simple[simple].append(key)
            slot = (owner.rsplit(".", 1)[-1], simple)
            self.overloads[slot] += 1
            rank = (len(versions.split(",")), -len(key))
            if slot not in widest or rank > widest[slot][0]:
                widest[slot] = (rank, key)
        self.by_type_member = {slot: key for slot, (_, key) in widest.items()}

    def resolve(self, receiver: str, member: str, hint: str | None
                ) -> tuple[str | None, str]:
        """(member key, confidence) — 'typed', 'static', 'unique', 'ambiguous'."""
        if member == "#ctor":
            key = self.by_type_member.get((receiver, "#ctor"))
            return key, "static" if key else "unresolved"
        # A PascalCase receiver that is itself a documented type is a static
        # call, and those need no inference at all.
        if receiver in self.types:
            key = self.by_type_member.get((receiver, member))
            if key:
                return key, "static"
        for candidate in (hint, ):
            if candidate:
                key = self.by_type_member.get((candidate.rsplit(".", 1)[-1],
                                               member))
                if key:
                    return key, "typed"
        keys = self.by_simple.get(member, [])
        if len(keys) == 1:
            return keys[0], "unique"
        if keys:
            return None, f"ambiguous:{len(keys)}"
        return None, "unresolved"


def condition_reach(db) -> dict[str, int]:
    """How many members share each condition's wording.

    This is the difference between a warning and a house style, and it is a
    fact of the index rather than a judgement of ours: Autodesk repeats the
    boilerplate and writes the specific sentence once.
    """
    return {mark: count for mark, count in db.execute(
        "SELECT fingerprint, COUNT(DISTINCT key) FROM trap "
        "GROUP BY fingerprint")}


def rarity_weight(shared_by: int) -> float:
    if shared_by <= 1:
        return 3.0
    if shared_by <= 5:
        return 2.0
    if shared_by <= 25:
        return 1.0
    if shared_by <= 200:
        return 0.4
    return 0.15


def collect(db, backend: pathlib.Path, top: int, member_filter: str | None,
            include_tests: bool = False) -> dict:
    resolver = Resolver(db)
    shared = condition_reach(db)
    sites: dict[str, list[dict]] = collections.defaultdict(list)
    files_scanned = 0
    chunk_count = 0

    for path in scan_files(backend, include_tests):
        chunks = (chunks_from_cs(path) if path.suffix == ".cs"
                  or path.name.endswith(".cs.j2")
                  else chunks_from_python(path))
        if not chunks:
            continue
        files_scanned += 1
        relative = str(path.relative_to(backend))
        whole_model = bool(WHOLE_MODEL.search(relative))
        for chunk in chunks:
            chunk_count += 1
            for use in accesses(chunk):
                key, confidence = resolver.resolve(
                    use["receiver"], use["member"], use["static_hint"])
                if key is None:
                    continue
                use.update({"file": relative, "confidence": confidence,
                            "whole_model": whole_model})
                sites[key].append(use)

    findings = []
    for key, uses in sites.items():
        entries = conditions_of(db, key)
        if not entries:
            continue
        if member_filter and member_filter.lower() not in key.lower():
            continue
        finding = _finding(db, key, entries, uses, shared)
        if finding is not None:
            findings.append(finding)
    # A member every one of whose conditions is settled before the run is not
    # a finding, and is not deleted either: it moves to its own section, with
    # the reason, where it can be argued with.
    live = sorted([f for f in findings if f["conditions"]],
                  key=lambda f: -f["score"])
    settled = sorted([f for f in findings if not f["conditions"]],
                     key=lambda f: f["member"])
    return {
        "files_scanned": files_scanned,
        "chunks": chunk_count,
        "members_touched": len(sites),
        "members_touched_with_traps": len(
            [k for k in sites if conditions_of(db, k)]),
        "call_sites": sum(len(v) for v in sites.values()),
        "findings": live[:top] if top else live,
        "all_findings": len(live),
        "discharged_members": settled,
    }


def _finding(db, key: str, entries: list[dict], uses: list[dict],
             shared: dict[str, int]) -> dict:
    row = db.execute("SELECT versions, drift FROM member WHERE key=?",
                     (key,)).fetchone()
    seen = set()
    unique_uses = []
    for use in uses:
        mark = (use["file"], use["line"])
        if mark in seen:
            continue
        seen.add(mark)
        unique_uses.append(use)
    uses = unique_uses
    unguarded = [u for u in uses if u["guard"] == "none"]
    # Reached only through a hand-written test.  Not a catch, and not proof
    # that the test is about THIS condition -- so it demotes and prints, it
    # does not settle.
    checked = [u for u in uses if u["guard"] == "checked"]
    # A catch that names Exception is not a guard against a documented
    # condition, it is a guard against noticing one.  That is the group shape.
    blanket = [u for u in uses if u["guard"] == "guarded"
               and u["caught"] in ("«bare»", "Exception", "System.Exception")]
    specific = [u for u in uses if u["guard"] == "guarded"
                and u["caught"] not in ("«bare»", "Exception",
                                        "System.Exception")]
    whole_model = [u for u in uses if u["whole_model"]]
    looped = [u for u in uses if u["in_loop"]]

    # Blast radius, stated so it can be argued with:
    #   reach     3 whole-model read path walked per element
    #             2 per-element loop anywhere else
    #             1 one call, one op
    #   exposure  2 the documented condition escapes or is swallowed silently
    #             0 the catch names the exception
    #   rarity    3 Autodesk wrote this sentence about one member only
    #             … 0.15 boilerplate repeated across the whole API
    from api_trap_index import fingerprint  # local: keeps the import list flat
    writes_anywhere = any(u.get("writes") for u in uses)
    conditions = []
    discharged: list[dict] = []
    setter_only = 0
    for e in entries:
        # "Setting this property is not supported..." is a fact about the
        # setter.  We read LocationPoint.Point and never assign it, so
        # counting that condition against us would rank a non-bug beside the
        # one that actually cost 2 846 groups.
        if not writes_anywhere and _SETTER_ONLY.search(e["text"]):
            setter_only += 1
            continue
        record = {"exception": e["exception"], "text": e["text"],
                  "versions": e["versions"], "tag": e["tag"],
                  "shared_by": shared.get(fingerprint(e["text"]), 1)}
        settled = discharge_of(key, e["text"], uses)
        if settled:
            record["discharged_as"], record["reason"] = settled
            discharged.append(record)
            continue
        conditions.append(record)
    if not conditions and not discharged:
        return None
    reach = 3 if (whole_model and looped) else 2 if looped else 1
    exposure = 2 if (unguarded or blanket) else 1 if checked else 0
    if conditions:
        rarity = max(rarity_weight(c["shared_by"]) for c in conditions)
        score = reach * exposure * rarity * (1 + min(len(uses), 10) / 10)
    else:
        # Every documented condition is settled before the run.  The member
        # stays in the report, in its own section, at zero.
        score = 0.0
    conditions.sort(key=lambda c: c["shared_by"])
    discharged.sort(key=lambda c: c["shared_by"])

    return {
        "member": key,
        "versions": row["versions"] if row else "",
        "drift": row["drift"] if row else "",
        "conditions": conditions,
        "discharged": discharged,
        "setter_only_conditions": setter_only,
        "sites": len(uses),
        "unguarded": len(unguarded),
        "checked": len(checked),
        "blanket": len(blanket),
        "specific": len(specific),
        "whole_model": bool(whole_model),
        "per_element": bool(looped),
        "score": round(score, 2),
        "confidence": sorted({u["confidence"] for u in uses}),
        "where": [{"file": u["file"], "line": u["line"], "guard": u["guard"],
                   "caught": u["caught"], "text": u["text"]}
                  for u in sorted(uses, key=lambda u: (u["file"], u["line"]))],
    }


def report(result: dict, show: int) -> None:
    print("OUR INFERENCE — every line below is this tool reading our text, "
          "not a fact of the API.")
    print("Autodesk's words are the quoted sentences, and only those.\n")
    print(f"  files scanned                 {result['files_scanned']}")
    print(f"  C# chunks                     {result['chunks']}")
    print(f"  distinct API members touched  {result['members_touched']}")
    print(f"  ... of them documented to refuse "
          f"{result['members_touched_with_traps']}")
    print(f"  call sites                    {result['call_sites']}")
    print(f"  members with an unhandled documented condition "
          f"{result['all_findings']}")
    print("\n  score = reach × exposure × rarity × volume")
    print("    reach     3 whole-model read path, walked per element")
    print("              2 per-element loop elsewhere · 1 single call")
    print("    exposure  2 condition escapes, or is swallowed by a blanket "
          "catch")
    print("              1 reached only through a hand-written test "
          "· 0 named catch")
    print("    rarity    3 Autodesk documents this sentence on ONE member")
    print("              2 ≤5 members · 1 ≤25 · 0.4 ≤200 · 0.15 boilerplate")
    print("    volume    1 + min(sites,10)/10\n")

    for index, finding in enumerate(result["findings"][:show], 1):
        print(f"\n{'=' * 74}")
        print(f"{index}. {finding['member']}   [{span(finding['versions'])}]"
              f"   score {finding['score']}")
        if finding["drift"]:
            print(f"   version drift: {finding['drift']}")
        for condition in finding["conditions"]:
            shared = condition["shared_by"]
            note = ("written about this member alone" if shared == 1
                    else f"also documented on {shared - 1} other members")
            print(f"   Autodesk, {condition['exception']} "
                  f"[{span(condition['versions'])}] — {note}:")
            print(f"     “{condition['text']}”")
        for condition in finding.get("discharged", ()):
            print(f"   settled before the run ({condition['discharged_as']}), "
                  f"NOT counted — {condition['reason']}:")
            print(f"     “{condition['text']}”")
        print(f"   our sites: {finding['sites']}  "
              f"(unguarded {finding['unguarded']}, "
              f"tested-by-hand {finding.get('checked', 0)}, "
              f"blanket-catch {finding['blanket']}, "
              f"named-catch {finding['specific']})"
              f"   per-element: {finding['per_element']}"
              f"   whole-model: {finding['whole_model']}")
        print(f"   resolved by: {', '.join(finding['confidence'])}")
        for where in finding["where"][:6]:
            mark = ("UNGUARDED" if where["guard"] == "none"
                    else "CHECKED" if where["guard"] == "checked"
                    else f"catch {where['caught']}")
            print(f"     {where['file']}:{where['line']}  [{mark}]")
            print(f"       {where['text']}")
        if len(finding["where"]) > 6:
            print(f"     … {len(finding['where']) - 6} more sites")

    settled = result.get("discharged_members") or []
    if settled:
        print(f"\n\n{'=' * 74}")
        print("SETTLED BEFORE THE RUN — every documented condition on these "
              "members is\nfixed by our own source or by a binding this "
              "codebase makes once, so no\nmodel can turn one of them on.  "
              "Listed, not deleted: if the code stops\nhaving the property, "
              "the member returns to the ranking by itself.\n")
        for finding in settled:
            print(f"  {finding['member']}   sites {finding['sites']}")
            for condition in finding["discharged"]:
                print(f"    ({condition['discharged_as']}) "
                      f"“{condition['text'][:100]}”")
                print(f"      — {condition['reason']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=pathlib.Path, default=DEFAULT_DB)
    parser.add_argument("--top", type=int, default=40)
    parser.add_argument("--show", type=int, default=10)
    parser.add_argument("--member", help="only members whose key matches")
    parser.add_argument("--backend", type=pathlib.Path, default=BACKEND,
                        help="repository root holding kukai/")
    parser.add_argument("--include-tests", action="store_true",
                        help="also scan tests and golden .cs artifacts")
    parser.add_argument("--json", type=pathlib.Path)
    args = parser.parse_args(argv)

    db = open_db(args.db)
    result = collect(db, args.backend, args.top, args.member,
                     args.include_tests)
    report(result, args.show)
    if args.json:
        args.json.write_text(json.dumps(result, indent=2, ensure_ascii=False),
                             encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
