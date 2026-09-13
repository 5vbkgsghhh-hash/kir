"""A SNAPSHOT'S EXISTENCE IS ASKED OF THE HELPER, NOT OF THE FILE SYSTEM.

WHY THIS FILE, AND IT WAS BOUGHT DEARLY — 20.08.2026, THE SAME HOUR
COMPRESSION WAS TURNED ON. On 19.08 the class "reading a snapshot with a
bare `open`" was closed: seven spots plus a core defect. The class was
closed by the VERB OF READING, and it went unnoticed that the VERB OF
EXISTENCE has the same property.

The very first control after compressing six decompiles:

    index_from_run('…/snowdon_plumb_v4')
    -> BuildingIndexError: the decompile carries no L0.jsonl — there is
       nothing to build an index from. This is a fact about the RUN, not
       about the building

The refusal confidently names as a fact about the run what was in fact a
fact about OUR OWN reading. A census found **nine** non-test spots asking
`os.path.exists` / `.exists()` / `.is_file()` on the RAW name: the building
index, the course catalog, the clash's `resolve_run` (through it the model
gets the open document's index!), two clash guards, the grid census, and
three instruments. Compressed decompiles became invisible to all of them at
once — and not by refusal, but by SILENCE: "there is no decompile."

🔴 WHY A RATCHET, AND NOT NINE FIXES. The class had already come back with a
second verb; a third one (`stat`, `glob`, a masked `listdir`) costs exactly
as much. The list of names is taken from the AUTHORITY —
`snapshot_janitor.SNAPSHOT_FILES`, the very tuple the janitor compresses
by — so a newly compressed name falls under guard on its own, with no edit
to this file.
"""
from __future__ import annotations

import ast
import pathlib
import unittest

#: The allowed ways to ask whether a snapshot exists. `snapshot_file_exists`
#: is the prod helper; `_snapshot_exists` is its local alias in instruments
#: that do not want to pull the import to the top level.
ALLOWED = ("snapshot_file_exists", "_snapshot_exists")

#: The bare verbs, each of which answers wrong on a compressed snapshot.
#:
#: 🔴 `stat` WAS ADDED ON 20.08 BECAUSE IT WAS FOUND LIVE, NOT BY GUESSWORK.
#: This file's own docstring named `stat` as the next candidate — and an
#: hour later it turned up in `test_l0_dialect.py`: `stream.stat().st_size`
#: on the raw name of a compressed decompile raises `FileNotFoundError`.
#: Existence and reading were fixed separately, and size remained the third
#: half of the same class. The precise answer is given by
#: `snapshot_raw_size` — it reads ISIZE from the gzip trailer.
BARE_ATTRS = ("exists", "is_file", "stat")


def _snapshot_names() -> tuple[str, ...]:
    """The names are taken from the JANITOR — the one that compresses them.

    A second list here would be exactly our own named defect: a value
    declared in one place and read in another.

    🔴 A PLAIN IMPORT INSTEAD OF LOADING BY PATH — FIXED 28.08.2026. Before
    that, the janitor was loaded as a FILE:
    `parents[4] / "tools" / "snapshot_janitor.py"`. The 27.08 split
    relocated it INTO A PACKAGE (`kir/instruments/snapshot_janitor.py`),
    and the step count stayed the same and came to point at `/opt/tools/…`,
    which does not exist: four tests in this file were failing with
    `FileNotFoundError`, and the failure was about US, not about the
    subject.

    The same lesson `install_paths` was fixed with on 27.08: **count not by
    steps upward, but from where the module actually sits.** Here it is
    carried through to the end — the module became part of the package, so
    it must be IMPORTED, and then neither a path nor step counting is
    needed at all.

    Along with it, the `sys.modules` registration ritual went away too:
    that CPython defect (`dataclasses.py:749` takes
    `sys.modules.get(cls.__module__).__dict__` with no guard) concerned
    loading BY PATH, when the module is not yet in `sys.modules`. A plain
    import registers it on its own.
    """
    from kir.instruments import snapshot_janitor

    return tuple(snapshot_janitor.SNAPSHOT_FILES)


class _Finder(ast.NodeVisitor):
    """Looks for an existence check whose argument carries a snapshot file name.

    🔴 TRACKS A VARIABLE, AND THIS IS THE SECOND REVISION — THE FIRST WAS
    BLIND TO ORDINARY TIDINESS. Measured 20.08.2026, a neighboring wave on
    its own prod code:

        (run_dir / "L0.jsonl").exists()            -> the ratchet TURNS RED
        l0 = run_dir / "L0.jsonl"; l0.exists()     -> the ratchet is GREEN

    That is, a path factored out into a sensibly named variable made the
    defect invisible. The claim "the class is closed by the ratchet" was
    true for ONE of the two spellings, and this was found not by the
    guard's author, but by the one whose guard stayed silent in a prod
    module (`viewer/normcontrol.py`). Form 25: the more tidily the code is
    laid out, the blinder a guard that reads text becomes.

    The tracking is DELIBERATELY simple — assignments within the module,
    with no branching and no reassignment. This is CLOSED, BUT NOT
    COMPLETE: a variable assembled in another function or through a list is
    still invisible, and declaring otherwise would mean repeating the same
    error more broadly.
    """

    def __init__(self, names: tuple[str, ...]) -> None:
        self.names = names
        self.hits: list[tuple[int, str]] = []
        #: variable name -> the snapshot name that was put into it
        self.tainted: dict[str, str] = {}

    def visit_Assign(self, node: ast.Assign) -> None:  # noqa: N802
        name = self._mentions_snapshot(node.value, follow=False)
        if name:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.tainted[target.id] = name
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:  # noqa: N802
        if node.value is not None:
            name = self._mentions_snapshot(node.value, follow=False)
            if name and isinstance(node.target, ast.Name):
                self.tainted[node.target.id] = name
        self.generic_visit(node)

    def _mentions_snapshot(self, node: ast.AST, follow: bool = True) -> str:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                if sub.value in self.names:
                    return sub.value
            if follow and isinstance(sub, ast.Name) and sub.id in self.tainted:
                return self.tainted[sub.id]
        return ""

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        """Both forms of the same verb, and NOT via `elif`.

        🔴 THE FIRST REVISION WAS A BLUNT PROBE, AND ITS OWN FAIL CONTROL
        CAUGHT IT. `os.path.exists(p)` is also an `Attribute` with
        `attr == "exists"`, so it went into the FIRST branch, which looks
        at `func.value` (`os.path`, where the snapshot name is not), and
        the `elif` never ran: of the two planted cases the probe found
        one. We look at BOTH spots — the method's receiver and the
        function's first argument.
        """
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in BARE_ATTRS:
            # `path.exists()` / `path.is_file()` — the subject is to the left of the dot.
            name = self._mentions_snapshot(func.value)
            if not name and node.args:
                # `os.path.exists(path)` — the subject is in the argument.
                name = self._mentions_snapshot(node.args[0])
            if name:
                self.hits.append((node.lineno, name))
        self.generic_visit(node)


class СуществованиеСлепкаНеСпрашиваютУФС(unittest.TestCase):

    #: 🔴 EXEMPTION IS PER-LINE, NOT PER-FILE — AND THIS IS THE ANSWER TO A
    #: NAMED BOUNDARY. The first revision keyed by file, and a neighboring
    #: wave immediately said what was wrong with that: a new raw check
    #: added to the same file FOR A DIFFERENT REASON would pass unreviewed
    #: — the same granularity as a review lock, and it is cured just as
    #: poorly.
    #:
    #: The tag is placed ON THE LINE, or in an UNBROKEN COMMENT BLOCK above
    #: it, and it must carry a reason:
    #:
    #:     if raw.exists():   # raw on purpose: the janitor decides WHAT to compress
    #:
    #: This way the exemption stops being a property of the FILE and
    #: becomes a property of the SPOT, and the reason sits where the next
    #: person will read it.
    #:
    #: 🔴 "ONE LINE ABOVE" WAS TOO NARROW, AND THIS WAS PAID FOR
    #: (01.09.2026). The tag stood in its rightful place in
    #: `viewer/tests/test_cache.py`, and commit `3b6a68a` (30.08, F-269)
    #: inserted BETWEEN it and the guarded line seven lines of explanation
    #: about nanoseconds. The tag ended up ten lines above, the guard did
    #: not see it and turned red — at a spot that had been exempted
    #: DELIBERATELY and with a reason. Two days of red, with neither a
    #: behavior fix nor new debt: the exemption was cancelled by the
    #: GROWTH OF A NEIGHBORING COMMENT.
    #:
    #: This is the same kind as "an instrument gamed by reshaping its
    #: guard," only inside out: here the shape cancelled a LEGITIMATE
    #: exemption. The cure is not a line count (any N will drift out of
    #: sync with the next comment), but a BLOCK BOUNDARY: the tag governs
    #: an unbroken ribbon of comments directly above the line, and breaks
    #: at the very first line of code — so it cannot reach over into
    #: someone else's spot.
    MARKERS = (
        "сырой намеренно",
        "raw on purpose",
        "raw is intentional",
        "raw is deliberate",
    )

    #: 🔴 THE WALK'S SCOPE IS THE PACKAGE, AND IT IS TAKEN FROM THE PACKAGE'S
    #: LOCATION (28.08.2026).
    #:
    #: Before the split the root was `parents[4]` — the whole owner tree,
    #: together with the product. After the split the same count gives
    #: `/opt`, i.e. the directory where `/opt/kir` simply sits next to
    #: someone else's trees: the walk would be scanning not our code, but
    #: everything the operator placed in `/opt`.
    #:
    #: We count not by steps upward, but from `kir.__file__` — the same
    #: rule `install_paths` was fixed by on 27.08. And the scope is now
    #: named honestly: the KIR guard guards KIR, not whatever happened to
    #: end up next door.
    @staticmethod
    def _package_root() -> pathlib.Path:
        import kir

        return pathlib.Path(kir.__file__).resolve().parent

    @classmethod
    def _released(cls, src: list[str], line: int) -> bool:
        """Whether a line is exempted by a tag — on itself or in the block above it.

        The block breaks at the very first thing that is not a comment: a
        blank line breaks it too. So a tag cannot reach into someone else's
        spot through code, and "broader" here does not mean "weaker" — it
        means "exactly to the end of the explanation that was written for
        this line."
        """
        here = src[line - 1] if line - 1 < len(src) else ""
        if any(marker in here for marker in cls.MARKERS):
            return True
        i = line - 2
        while i >= 0:
            текст = src[i].strip()
            if not текст.startswith("#"):
                return False
            if any(marker in src[i] for marker in cls.MARKERS):
                return True
            i -= 1
        return False

    def _sweep(self):
        root = self._package_root()
        names = _snapshot_names()
        self.assertTrue(names, "авторитет имён пуст — сторожить нечего")
        seen = bad = 0
        rows: list[str] = []
        for path in sorted(root.rglob("*.py")):
            rel = path.relative_to(root).as_posix()
            if "/venv/" in "/" + rel or rel.startswith("venv/"):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (OSError, SyntaxError) as exc:
                # A FILE THAT COULD NOT BE PARSED IS A NAMED REFUSAL, NOT A
                # FOOTNOTE: a report with a non-empty list of unparsed files
                # disqualifies itself (form 26).
                self.fail("не разобран %s: %s" % (rel, exc))
            seen += 1
            finder = _Finder(names)
            finder.visit(tree)
            if not finder.hits:
                continue
            src = path.read_text(encoding="utf-8").splitlines()
            unmarked = []
            for line, name in finder.hits:
                if self._released(src, line):
                    continue
                unmarked.append(
                    "%s:%d — голая проверка существования %r" % (rel, line, name))
            if not unmarked:
                continue
            bad += 1
            rows.extend(unmarked)
        return seen, bad, rows

    def test_no_bare_existence_check_on_a_snapshot_file(self):
        seen, bad, rows = self._sweep()
        # THE DENOMINATOR IS MANDATORY: "zero findings" with no count of the
        # files examined is indistinguishable from "the instrument read
        # nothing" (form 4).
        self.assertGreater(seen, 500, "просмотрено подозрительно мало файлов")
        self.assertEqual(rows, [], "\n".join(rows))
        self.assertEqual(bad, 0)

    def test_the_sweep_can_actually_find_something(self):
        """FAIL CONTROL: the probe must be able to say YES.

        Zero findings on a clean tree means nothing until it is shown that
        on a dirty one there would have been a finding. It is the probe's
        INPUT that is mutated, not the tree.
        """
        names = _snapshot_names()
        finder = _Finder(names)
        finder.visit(ast.parse(
            "import os\n"
            "from pathlib import Path\n"
            "def f(d):\n"
            "    return (Path(d) / %r).exists() and os.path.exists(%r)\n"
            % (names[0], names[0])))
        self.assertEqual(len(finder.hits), 2, finder.hits)

    def test_the_sweep_follows_a_path_put_into_a_variable(self):
        """🔴 ORDINARY TIDINESS MUST NOT HIDE A DEFECT.

        The first revision of the probe only saw the literal INSIDE the
        call, so `l0 = run_dir / "L0.jsonl"` followed by `l0.exists()`
        passed green. This was found not by the guard's author, but by the
        one whose guard stayed silent in a prod module. Here both
        spellings are planted side by side, so that "the class is closed"
        does not mean "closed for one of the two."
        """
        names = _snapshot_names()
        finder = _Finder(names)
        finder.visit(ast.parse(
            "from pathlib import Path\n"
            "def f(run_dir):\n"
            "    l0 = run_dir / %r\n"
            "    return l0.exists()\n" % (names[0],)))
        self.assertEqual(len(finder.hits), 1, finder.hits)
        self.assertEqual(finder.hits[0][1], names[0])

    def test_the_allowed_helper_is_not_flagged(self):
        """And the control in the other direction: an allowed way does NOT turn it red.

        Without it, the guard could turn red on everything indiscriminately
        and would get thrown out.
        """
        names = _snapshot_names()
        finder = _Finder(names)
        finder.visit(ast.parse(
            "def f(d):\n"
            "    return snapshot_file_exists(d / %r)\n" % (names[0],)))
        self.assertEqual(finder.hits, [])
        self.assertTrue(set(ALLOWED))


if __name__ == "__main__":
    unittest.main()
