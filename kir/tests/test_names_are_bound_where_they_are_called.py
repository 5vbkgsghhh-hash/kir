"""A NAME IS CALLED WHERE IT IS NOT BOUND — a ratchet on the class, not on
the instance.

WHAT THIS FILE HOLDS. On 20.08.2026 a live receipt said: «ПРОВЕРКА НА
КОЛЛИЗИИ НЕ ВЫПОЛНЕНА: NameError: name 'snapshot_file_exists' is not
defined». The clash check silently did not run on the LIVE path — and "did
not look" reads as "clean."

The cause was six hours old and one character wide: the 12:51 edit
(4145d511) replaced the call `l0.exists()` with `snapshot_file_exists(l0)`
in `clash/existing.py:load`, while the import of that name was LOCAL, inside
the neighboring function `resolve_run` (4404a1f2, 12:19). Python binds a
function-local import ONLY within its own function and stays silent until
the call.

🔴 WHY NOBODY CAUGHT THIS. Three circumstances lined up, and each is harmless
on its own:

* the exception was swallowed fail-open (`bundle_clash_report` has no right
  to cost a turn) — and that is CORRECT, but then the only carrier of the
  cause is the text;
* the only carrier of the traceback was `logger.debug`, while the service
  runs with `--log-level info`, so the traceback was written NOWHERE;
* `existing.load` was called by NOT A SINGLE test with an existing decompile
  directory. Coverage was zero exactly on the function that reads an
  already-standing building — that is, on half the meaning of the entire
  clash check.

🔴 AND A FOURTH, THE MOST IMPORTANT: GREP IS POWERLESS HERE BY CONSTRUCTION.
The name IS WRITTEN in the file — to grep the file looks like it is
importing it. Two homemade instruments, written the same day, gave zero for
the same reason: collecting the module's bindings, they walked `ast.walk`
and descended into nested functions, crediting their local imports to the
whole module. The only way to tell the difference is a real scope
resolution — which is exactly what `tools/scope_audit.py` does.

WHY A RATCHET, AND NOT "ZERO FINDINGS." The corpus holds ONE known open
finding (`chat_ws.py:3034`), and it is named below by name. Silencing it by
tuning the instrument would repeat exactly the defect this file exists to
catch.
"""
from __future__ import annotations

import pathlib
import sys
import unittest

from kir.instruments import scope_audit  # noqa: E402


#: 🔴 THE WALK'S SCOPE IS OUR PACKAGE (28.08.2026). `_BACKEND = parents[3]`
#: used to stand here, and the walk went through `_BACKEND / "kukai"` — over
#: the PRODUCT's tree. After the 27.08 split, the same arithmetic gives
#: `/opt`, there is no `kukai` directory there, and the walk returned empty:
#: the guard was green, having looked nowhere. The `scope_audit` instrument
#: moved INTO THE PACKAGE with the split and is imported as a module — there
#: is no longer any need to mix `tools` into `sys.path`.
_PACKAGE = pathlib.Path(__file__).resolve().parents[1]



#: KNOWN OPEN findings, each with a reason why it is not closed here.
#:
#: 🔴 IDENTIFICATION SWITCHED FROM LINE TO FUNCTION ON 21.08.2026. The key
#: used to be `(file, LINE, name)`, and the ratchet turned red `3034 -> 3039`:
#: the code above the finding shifted by five lines, while the finding
#: itself did NOT CHANGE one bit. A line number is a property of the file,
#: not of the defect, and a ratchet keyed on it turns red from any unrelated
#: edit higher up in the file. Such a red hides the next one: as long as it
#: is lit for a known reason, a REAL new finding is indistinguishable from
#: it.
#:
#: The strength is NOT lost in the process, and that matters more than
#: convenience: a check on the NUMBER of findings stands right next to it. A
#: second unbound variable in the same function would give two hits on one
#: key and would turn the ratchet red — that is, exactly what the line
#: number used to protect is now protected by the count.
#:
#: `chat_ws.py` — `ws_bridge_callback` is defined in `prepare_turn`
#: (1674-2369), and is called in `_to_bridge` inside `finalize_turn`
#: (2958-3456). These are DIFFERENT top-level functions, there is no closure
#: between them: the call is guaranteed to raise NameError. Opened on 13.08
#: (a7d9c34c, "Skill markers move to the BRIDGE"), a week in the journal
#: with NOT A SINGLE trigger — meaning the branch is dormant and will wake on
#: the first skill marker that needs the bridge. Deliberately not fixed
#: here: the correct wiring (a parameter? a context field?
#: `ctx.ws_bridge_callback`, which sits right there and is ALREADY threaded
#: through) is a decision for the owner of the chat door, and a guessed
#: wiring is worse than a named hole.
#: 🔴 THE ENTRY FOR `kukai/api/chat_ws.py` WAS REMOVED ON 28.08.2026: this
#: file lives with the OWNER and no longer falls within the walk's scope.
#: KIR's exceptions ledger has no right to hold an entry about someone
#: else's file — it would be guarding something that is not here, and it
#: would look like protection. Empty, and this is a MEASUREMENT, not an
#: omission.
KNOWN_OPEN: set[tuple[str, str]] = set()


def _relative(path: str) -> str:
    """The path is FROM THE PACKAGE ROOT. It used to be cut on «/backend/» — the owner's layout."""
    try:
        return str(pathlib.Path(path).resolve().relative_to(_PACKAGE.parent))
    except ValueError:                                       # pragma: no cover
        return str(path)


class TheCorpusHasNoNewUnboundNames(unittest.TestCase):

    def test_no_name_is_called_outside_the_scope_that_binds_it(self) -> None:
        hits, _skipped = scope_audit.audit(_PACKAGE)
        fresh = [(p, ln, n) for p, ln, n in hits
                 if (_relative(p), n) not in KNOWN_OPEN]
        self.assertEqual(
            [], fresh,
            "новое имя зовётся там, где не связано — это NameError, который\n"
            "покажется только на исполнении, и, если он в fail-open ветке,\n"
            "не покажется вовсе:\n  "
            + "\n  ".join(f"{_relative(p)}:{ln}  {n}"
                           for p, ln, n in sorted(fresh)))
        # 🔴 THE COUNT IS THE SECOND HALF, AND WITHOUT IT A KEY BY FUNCTION
        # WOULD BE A WEAKENING: a second unbound variable in the same
        # function would give a second hit on the same key and would pass
        # silently.
        self.assertEqual(
            len(hits), len(KNOWN_OPEN),
            f"находок {len(hits)} при {len(KNOWN_OPEN)} известных открытых — "
            f"в известной функции появилось ВТОРОЕ несвязанное имя:\n  "
            + "\n  ".join(f"{_relative(p)}:{ln}  {n}"
                           for p, ln, n in sorted(hits)))

    def test_the_known_open_one_is_still_there(self) -> None:
        """A ratchet has no right to stay silent about what it SKIPS.

        Once fixed, the list must shrink deliberately, not just dissolve.
        """
        # 🔴 THE LIST HAS BEEN EMPTY SINCE 28.08.2026, AND THIS MUST BE SAID,
        # NOT PASSED OVER IN SILENCE. The only known open lead was in the
        # OWNER's file, which after the split no longer falls within the
        # walk's scope. An empty list makes this check green BY
        # CONSTRUCTION — and green by construction is indistinguishable from
        # green on the merits, which is exactly what this tree catches in
        # itself most often.
        if not KNOWN_OPEN:
            self.skipTest(
                "KNOWN_OPEN пуст: единственная известная открытая жила у "
                "хозяина и вышла из области обхода при разрезе. Сторожить "
                "нечего, и проверка честно об этом молчит, а не зеленеет")
        hits, _ = scope_audit.audit(_PACKAGE)
        found = {(_relative(p), name) for p, _line, name in hits}
        gone = KNOWN_OPEN - found
        if gone:
            self.fail(
                "известная открытая находка исчезла — если починена, убери её\n"
                f"из KNOWN_OPEN тем же коммитом: {sorted(gone)}")


class TheInstrumentItselfCanFail(unittest.TestCase):
    """FAIL CONTROL. An instrument that never turns red does not hold a ratchet."""

    def test_it_reddens_on_the_exact_shape_that_bit_us(self) -> None:
        source = (
            "def resolve():\n"
            "    from os.path import exists\n"
            "    return exists('/tmp')\n"
            "\n"
            "def load():\n"
            "    return exists('/tmp')\n"        # <- defect: a foreign scope
        )
        self.assertEqual(scope_audit.unbound_names(source),
                         [(6, "exists")])

    def test_a_closure_is_NOT_a_finding(self) -> None:
        """Without this control the instrument would flag half the tree red."""
        source = (
            "def outer():\n"
            "    from os.path import exists\n"
            "    def inner():\n"
            "        return exists('/tmp')\n"
            "    return inner\n"
        )
        self.assertEqual(scope_audit.unbound_names(source), [])

    def test_a_closure_TWO_levels_deep_is_NOT_a_finding(self) -> None:
        """The instrument's first version descended with `ast.walk` and lost
        the middle of the chain — three false findings on the live corpus."""
        source = (
            "def outer():\n"
            "    from os.path import exists\n"
            "    def middle():\n"
            "        def inner():\n"
            "            return exists('/tmp')\n"
            "        return inner\n"
            "    return middle\n"
        )
        self.assertEqual(scope_audit.unbound_names(source), [])

    def test_a_postponed_annotation_is_NOT_a_finding(self) -> None:
        """PEP 563: an annotation is a string, its name is never evaluated."""
        source = (
            "from __future__ import annotations\n"
            "def f(x: Unknown) -> Other:\n"
            "    return x\n"
        )
        self.assertEqual(scope_audit.unbound_names(source), [])

    def test_an_annotation_WITHOUT_the_future_import_IS_a_finding(self) -> None:
        """Narrowness control: without PEP 563 the annotation is evaluated, and this is a NameError."""
        source = "def f(x: Unknown):\n    return x\n"
        self.assertEqual(scope_audit.unbound_names(source), [(1, "Unknown")])

    def test_a_star_import_file_is_REFUSED_not_silently_passed(self) -> None:
        """An opaque scope must be NAMED by the instrument, not declared clean."""
        with self.assertRaises(scope_audit._StarImport):
            scope_audit.unbound_names("from os.path import *\ndef f():\n"
                                      "    return exists('/tmp')\n")


class TheClassBodyIsNotAnEnclosingScope(unittest.TestCase):
    """A CLASS BODY DOES NOT CLOSE OVER ITS METHODS, AND THE INSTRUMENT MUST
    KNOW THIS.

    🔴 BOUGHT ON 29.08.2026. The walk's comment promised exactly this — "the
    CLASS scope is deliberately excluded from the chain for nested scopes" —
    while the code merged the chain WHOLE. The distinguishing case was
    reproduced by EXECUTION, not by reasoning:

        class C:
            token = 1
            def f(self): return token

        unbound_names -> []                        the instrument was silent
        C().f()       -> NameError: 'token'        python was not silent

    This is the most common form of the defect the instrument was built
    against: referencing a class attribute without `self.` inside a method.
    On the live corpus, after the fix, findings are zero — that is, the fix
    uncovered nothing and closed the hole; stated plainly so the next person
    does not go looking for a finding in this commit.
    """

    def _flagged(self, source: str):
        return scope_audit.unbound_names(source)

    def test_a_method_reading_a_class_local_IS_a_finding(self) -> None:
        self.assertEqual(
            self._flagged("class C:\n    token = 1\n"
                          "    def f(self):\n        return token\n"),
            [(4, "token")])

    def test_the_class_body_DOES_see_its_own_bindings(self) -> None:
        """Narrowness control: the class body itself does see its own names."""
        self.assertEqual(self._flagged("class C:\n    a = 1\n    b = a + 1\n"), [])

    def test_the_same_name_through_self_is_NOT_a_finding(self) -> None:
        self.assertEqual(
            self._flagged("class C:\n    token = 1\n"
                          "    def f(self):\n        return self.token\n"), [])

    def test_a_class_inside_a_function_still_sees_the_function(self) -> None:
        self.assertEqual(
            self._flagged("def o():\n    x = 1\n    class C:\n"
                          "        y = x\n    return C\n"), [])

    def test_a_method_inside_a_function_keeps_its_closure(self) -> None:
        """The subtlest case: a class in the middle of the chain has no right
        to break a method's CLOSURE over the enclosing function."""
        self.assertEqual(
            self._flagged("def o():\n    x = 1\n    class C:\n        z = 2\n"
                          "        def f(self):\n            return x\n"
                          "    return C\n"), [])

    def test_a_method_inside_a_function_does_NOT_see_the_class(self) -> None:
        """And the flip side of the same thing: the method cannot see the class body's `z`."""
        self.assertEqual(
            self._flagged("def o():\n    class C:\n        z = 2\n"
                          "        def f(self):\n            return z\n"
                          "    return C\n"), [(5, "z")])


class TheDefectItselfIsGone(unittest.TestCase):
    """That very call which was not in a single test."""

    def test_existing_load_reads_a_run_directory_without_raising(self) -> None:
        import tempfile
        from kir.clash import existing as _existing

        run = pathlib.Path(tempfile.mkdtemp())
        (run / "L0.jsonl").write_text(
            '{"record":"element","element":{"element_id":"1"}}\n',
            encoding="utf-8")
        region = _existing.Region.around([])
        got = _existing.load(run, region)
        # An empty scope is a NAMED refusal, not a crash. Exactly one thing
        # matters here: line 532 passed and `snapshot_file_exists` was
        # found.
        self.assertFalse(got.present)
        self.assertIn("область пуста", got.reason)


if __name__ == "__main__":
    unittest.main()
