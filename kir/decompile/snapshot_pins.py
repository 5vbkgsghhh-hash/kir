"""Which decompile snapshots are PINNED by sources and must not be deleted.

WHY THIS MODULE EXISTS (measurement of 21.08.2026). The janitor
``tools/snapshot_janitor.py`` keeps the two most recent revisions of every
document and deletes the rest. A sensible policy, never once executed until
today. A dry run on 21.08: 38 directories up for deletion, and **16 of them
are named by sources** — among them ``sob62_fas_r23_v19``, which the PROD
viewer reads (``kukai/api/viewer.py``), and ``sob62_fas_r23_v11`` / ``v13``,
which the clash and curtain-wall tests read. That is, the very first honest
``--apply`` would turn tests red and cut the legs out from under a prod
handle.

The hole is not in the threshold or the revision count: the retention
policy simply HAS NO notion of "someone references this snapshot". That is
what gets established here.

REFUSE TOWARD THE SAFE SIDE — THE SAME WAY ``check_live`` DOES. That one
treats an unread control file as a sign of a live run; this one treats a
doubtful reference as a pin. A mistaken pin costs disk space; a mistake in
the other direction costs deleted evidence that cannot be recovered.

WHY NOT GREP. Grep answers "is the string present"; the question asked is
"does the code reference it" — our own named defect, bought twice. A
snapshot's name enters the tree in two DIFFERENT ways:

* ``V11 = BACKEND / "backend" / "data" / "decompile" / "sob62_fas_r23_v11"``
  — the code assembles a path. This is a REFERENCE: delete the directory
  and a test turns red.
* ``WEIGHT IS A MEASUREMENT, NOT A PROMISE (``k2_ar_rd_v8``, an 84.3 MB
  decompile)`` — a docstring quoting WHERE the measurement was taken. This
  is a CITATION: delete the directory and nothing changes except a
  historical note.

Grep cannot tell them apart. Syntax parsing can, exactly: a citation lives
in a docstring (the first statement of a module, class, or function) or in
a ``#`` comment, neither of which exists in the decompile tree at all.
Everything else that is a string is code.

THE COST OF TELLING THEM APART WAS MEASURED, NOT TAKEN ON FAITH, AND THE
MEASUREMENT DISPROVED THE EXPECTATION. On 21.08, over the janitor's list of
38 directories, grep held 16 and syntax parsing held the SAME 16 — zero
divergence. Whoever wrote this module expected parsing to hold fewer; that
expectation was wrong, and the number stands here in its place.

The reason for the match is corpus discipline, not the instrument being
unnecessary: citations in the tree are formatted with backticks inside
comments (``k2_ar_rd_v8`` — 20 mentions, of which EXACTLY ZERO are string
literals), while references always travel as quoted strings in code. As
long as the discipline holds, the two instruments answer the same way.

Parsing is kept in place for two reasons, both checkable:

* it does not depend on formatting. Grep caught the name by its quotes; a
  citation in backticks would have slipped past it unnoticed — and the
  other way round, a docstring in plain quotes would have been pinned by
  it FOR NOTHING;
* it distinguishes a name occurring inside a string from BEING EQUAL to it.
  In ``test_version_fragile_asks_the_emitter.py`` the name sits inside an
  assertion's text — that is code, that is a literal, and it is NOT a
  reference to a directory. Parsing compares for equality and so stays
  silent; a substring search would have pinned it.

WHAT THIS MODULE CANNOT DO IS NAMED HERE, NOT LEFT UNSAID:

* a name assembled from pieces (``"sob62_fas_r23_v" + str(n)``) is not seen;
* a name arriving from an external settings file or a command-line argument
  is not seen;
* an f-string is seen only if the directory is named inside it whole, as a
  literal.

All three mean one thing: a pin is a LOWER bound on the set of needed
snapshots, not the exact set. That is why it is not the only guard either:
``check_live`` stays in place in the janitor and checks something else.
"""
from __future__ import annotations

import ast
import dataclasses
import pathlib
from typing import Iterable, Iterator, Optional

#: Where to look for references. The roots are sources, not data: a
#: snapshot named inside another snapshot is not a reference.
#:
#: 🔴 `kir` ADDED 29.08.2026, AND WITHOUT IT THE LIST WAS A MEMORY OF THE
#: PAST LAYOUT. After the split, the production sources live in `kir/`,
#: while only `kukai`/`tools` stood here — names of the HOST tree's layout.
#: Live in `/opt/kir` this always yielded ZERO pins, meaning the janitor's
#: only protection ("working code references this snapshot") could never
#: fire even once, even though references exist:
#: `kir/course/building.py:295` -> `sob62_fas_r23_v19`,
#: `kir/decompile/tests/test_curtain_blindness.py:34` ->
#: `sob62_fas_r23_v11`.
#:
#: The list carries BOTH layouts deliberately: the same instrument is run
#: both from the standalone language and from the host tree. A missing root
#: is not trouble by itself — the trouble would be a walk that read NOT ONE
#: file, and that is asked of :func:`scan_reach`, not guessed from names.
DEFAULT_SOURCE_ROOTS = ("kir", "kukai", "tools")

#: Directories we do not enter: foreign code and build junk hold no
#: references, and walking them costs more time than the whole tree.
SKIP_DIRS = frozenset({
    "__pycache__", ".git", "node_modules", "venv", ".venv", "assets",
})


@dataclasses.dataclass(frozen=True)
class Pin:
    """One reference: which snapshot, from which file, from which line."""
    snapshot: str
    file: str
    line: int


def _iter_python_files(root: pathlib.Path) -> Iterator[pathlib.Path]:
    if not root.is_dir():
        return
    for path in root.rglob("*.py"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        yield path


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """id() of the string nodes that are DOCSTRINGS.

    A docstring is the first statement of a module, class, function, or
    coroutine, and only if it is a string literal. We collect nodes, not
    texts: the same text can occur both in a docstring and in code, and in
    that case the pin must fire on the code.
    """
    out: set[int] = set()
    holders = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    for node in ast.walk(tree):
        if not isinstance(node, holders):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if (isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            out.add(id(first.value))
    return out


def _code_string_literals(path: pathlib.Path) -> Iterator[tuple[str, int]]:
    """Every string literal of a file, EXCEPT docstrings, with its line number.

    A file that fails to parse is skipped silently in only one sense: it
    yields no pins. This is not "an error swallowed" — broken syntax cannot
    be a working reference, and raising here would make the cleanup depend
    on someone else's unfinished file.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError, ValueError):
        return
    skip = _docstring_nodes(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in skip:
                continue
            yield node.value, node.lineno
        elif isinstance(node, ast.JoinedStr):
            # An f-string: the literal pieces inside it are code too.
            for part in node.values:
                if (isinstance(part, ast.Constant)
                        and isinstance(part.value, str)):
                    yield part.value, node.lineno


def find_pins(
    snapshot_names: Iterable[str],
    tree_root: pathlib.Path,
    source_roots: Iterable[str] = DEFAULT_SOURCE_ROOTS,
) -> list[Pin]:
    """All source references to the listed snapshot names.

    ``snapshot_names`` is what actually sits on disk: a pin only makes
    sense against existing directories, otherwise it turns into a wish
    list.
    """
    wanted = {name for name in snapshot_names if name}
    if not wanted:
        return []
    pins: list[Pin] = []
    for rel in source_roots:
        for path in _iter_python_files(tree_root / rel):
            for text, line in _code_string_literals(path):
                if text in wanted:
                    pins.append(Pin(
                        snapshot=text,
                        file=str(path.relative_to(tree_root)),
                        line=line,
                    ))
    return pins


def pinned_snapshots(
    snapshot_names: Iterable[str],
    tree_root: pathlib.Path,
    source_roots: Iterable[str] = DEFAULT_SOURCE_ROOTS,
) -> dict[str, Pin]:
    """Snapshot name -> the FIRST reference to it.

    The first, not all of them: the janitor needs to name the reason for
    refusal in one line, and "pinned right here" is a sufficient reason.
    The full list stays available through :func:`find_pins`.
    """
    out: dict[str, Pin] = {}
    for pin in find_pins(snapshot_names, tree_root, source_roots):
        out.setdefault(pin.snapshot, pin)
    return out


@dataclasses.dataclass(frozen=True)
class Reach:
    """What the walk WAS: which roots were read, which are absent, how many files.

    🔴 WHY A SEPARATE ENTRY POINT, NOT A CHANGED `find_pins` RESPONSE
    (29.08.2026). The same argument as `install_paths.install_root_refusal`:
    the response cannot be changed, consumer policies rest on it. Hence a
    third path — the response stays the same, and the SILENCE gets a reason
    that can be asked.

    `files == 0` is NOT "there are no references". It is "there was nothing
    to ask", and a consumer that DELETES something on the strength of such
    a zero is deleting blind. That is exactly what `snapshot_janitor` was
    doing while the roots still remembered the past layout.
    """

    roots_read: tuple[str, ...]
    roots_absent: tuple[str, ...]
    files: int

    @property
    def blind(self) -> bool:
        """The walk read not one file — any zero of its is unproven."""
        return self.files == 0

    def reason(self) -> Optional[str]:
        """WHY the walk cannot be trusted; ``None`` if it succeeded."""
        if not self.blind:
            return None
        return ("обход исходников не прочитал НИ ОДНОГО файла: корней нет "
                f"({', '.join(self.roots_absent) or '—'}). Всякий «ноль "
                "закреплений» отсюда есть факт о приборе, а не о ссылках. "
                "СЛЕДУЮЩИЙ ХОД: назвать корень исходников этого дерева "
                "(`source_roots=`) либо подать `tree_root`, содержащий пакет")


def scan_reach(
    tree_root: pathlib.Path,
    source_roots: Iterable[str] = DEFAULT_SOURCE_ROOTS,
) -> Reach:
    """Whether the walk that pins are counted by actually succeeded."""
    read: list[str] = []
    absent: list[str] = []
    files = 0
    for rel in source_roots:
        base = tree_root / rel
        if not base.is_dir():
            absent.append(rel)
            continue
        seen = sum(1 for _ in _iter_python_files(base))
        if seen:
            read.append(rel)
            files += seen
        else:
            absent.append(rel)
    return Reach(tuple(read), tuple(absent), files)


def pin_reason(pin: Optional[Pin]) -> Optional[str]:
    """A row for the janitor's report, or None if the snapshot is not pinned."""
    if pin is None:
        return None
    return f"закреплён исходниками: {pin.file}:{pin.line}"
