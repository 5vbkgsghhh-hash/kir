"""REFUSAL CODES HAVE ONE STEWARD — AND THIS IS ASKED AS A PROPERTY.

🔴 WHY IT WAS BUILT (01.09.2026).

Measured with an `ast` walk over the package's non-test code: **105 distinct
codes**, of which 51 are declared in `diag.py`, 40 as named constants
across fourteen foreign modules, and **15 had NO name AT ALL** — they lived
as bare literals in calls to `Diagnostic(code="KIR-…")`.

**A collision the previous guard could not see by construction.** `KIR-L004`
carried two meanings: "the ref points at an incompatible typed kind"
(`compiler.py`, as a bare literal) and `SLOPE_TOO_SHALLOW`
(`route_mep.py`). `code_collisions()` searched for "NAME = literal" pairs —
and saw EXACTLY ONE name, printing `{}` on a tree where the collision was
present. This is shape 54 of this tree: the guard pinned the FIRST case's
APPEARANCE (two NAMES, the 10.08 incident) instead of the PROPERTY ("a code
has one meaning"), and the second bite came in quieter than the first.

WHAT IS GUARDED HERE, AND WHY EXACTLY THIS

1. Every code the tree ISSUES is registered with the steward. Not "a name
   exists," but "the steward knows": a bare literal must also be entered.
2. A code has one meaning: `code_collisions()` is empty.
3. Every code has a named FAULT — whose action lifts the refusal.
4. Our own defects are not addressed to the author. A refusal that sends
   the model to fix a correct program is a defect of the apparatus, not of
   the wording.
5. The registry's taxonomy is cross-checked against the host by CALLING
   `serving._classify_refusal`, not by copying its tables: two carriers of
   the same knowledge is this tree's own named defect, and here it is
   closed by deriving one from the other.

WHAT THIS GUARD DOES NOT DO. It does not require replacing bare literals
with names: a literal in a call (`Diagnostic(code="KIR-…")`) is a lawful
form. Only one thing is required: that the code be ENTERED. And it does not
judge whether the assigned fault is correct — it keeps it NAMED and does
not let it disappear silently.
"""
from __future__ import annotations

import os
import pathlib
import tempfile
import unittest

from kir import diag


class TreeAgreesWithItsRegistrar(unittest.TestCase):
    """The tree and the steward speak of one and the same code space."""

    def setUp(self) -> None:
        self.decls, self.bare, self.unparsed = diag.codes_in_tree()
        self.in_tree = set(self.decls) | {c for c, _, _ in self.bare}

    def test_the_walk_actually_read_the_tree(self) -> None:
        """THE DENOMINATOR FIRST: an empty walk is green by construction.

        "0 unregistered out of 0 read" and "0 out of 106" print identically
        and mean the opposite. A file the instrument failed to parse
        disqualifies the report (shape 26), rather than becoming a
        footnote.
        """
        self.assertEqual(self.unparsed, [],
                         "прибор не разобрал файлы — отчёт НЕГОДЕН")
        self.assertGreaterEqual(
            len(self.in_tree), 100,
            f"обход нашёл всего {len(self.in_tree)} кодов — так не бывает, "
            f"сломан обход, а не дерево")

    def test_every_code_the_tree_emits_is_registered(self) -> None:
        """There is no second steward: every issued code is entered."""
        unknown: list[str] = []
        for code in sorted(self.in_tree - set(diag.CODES)):
            sites = sorted(
                {f"{f}:{ln}" for n, f, ln in self.decls.get(code, ())}
                | {f"{f}:{ln}" for c, f, ln in self.bare if c == code})
            unknown.append(f"{code} ({', '.join(sites)})")
        self.assertEqual(
            unknown, [],
            "коды выдаются, но у распорядителя не заведены — заведи их "
            "`kir.diag.register(...)`, назвав вину и таксономию:\n  "
            + "\n  ".join(unknown))

    def test_no_code_carries_two_meanings(self) -> None:
        self.assertEqual(diag.code_collisions(), {})

    def test_the_registry_does_not_invent_codes(self) -> None:
        """The flip side: an entered code is issued by somebody.

        Without this, the registry would quietly turn into a graveyard: the
        entry exists, the code is nowhere in the tree, and "106
        registered" would stop meaning anything.
        """
        self.assertEqual(sorted(set(diag.CODES) - self.in_tree), [])


class EveryCodeNamesItsBlame(unittest.TestCase):
    """The fault is the fix's address, and it is named for every code."""

    def test_blame_is_from_the_closed_list(self) -> None:
        for code, spec in sorted(diag.CODES.items()):
            with self.subTest(code=code):
                self.assertIn(spec.blame, diag.BLAMES)

    def test_our_own_defects_are_not_blamed_on_the_author(self) -> None:
        """A refusal that blames the author for OUR defect is a defect of
        the apparatus.

        The list is NAMED by hand, not derived: every entry is a read
        contract of the code, not a guess from its letter.
        """
        ours = {
            diag.INTERNAL_PANIC: "внутренняя ошибка компилятора",
            "KIR-E005": "внутренний контракт эмиссии, не пользовательский ввод",
            diag.SANDBOX_UNAVAILABLE: "изоляция/язык недоступны — НАШ дефект",
            diag.SANDBOX_CRASH: "процесс умер молча",
            diag.SANDBOX_UNREAD: "спрошено то, чего МЫ не прочитали",
            diag.PLAN_OP_CONTRACT: "у пишущего опа нет полного контракта низведения",
            "KIR-G116": "пробел ЗАХВАТА, а не ошибка автора",
            diag.X_RECEIPT: "квитанция исполнения не несёт обещанной личности",
            diag.CERT_UNPROVEN: "свидетеля пишет эмиттер, а не автор",
            diag.CERT_VACUOUS: "то же",
            diag.CERT_UNCERTIFIABLE: "то же",
            diag.ACCEPT_NO_EXECUTABLE_ARTEFACT: "артефакт наш",
            diag.ACCEPT_ARTEFACT_UNBOUND: "привязка наша",
        }
        for code, why in sorted(ours.items()):
            with self.subTest(code=code):
                spec = diag.CODES[code]
                self.assertNotEqual(
                    spec.blame, diag.BLAME_AUTHOR,
                    f"{code} ({spec.name}): {why} — автор не может это починить")

    def test_the_sandbox_vocabulary_is_translated_not_duplicated(self) -> None:
        """The sandbox has had its own fault dictionary since 03.08; a
        second one may not be started.

        The guard reads the LITERAL values `sandbox.py` passes, and
        requires each to have a translation. Should a sixth appear, a red
        will name it, not swallow it.
        """
        import ast

        src = pathlib.Path(__file__).resolve().parents[1] / "sandbox.py"
        tree = ast.parse(src.read_text(encoding="utf-8"))
        values: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                for kw in node.keywords:
                    if (kw.arg == "blame" and isinstance(kw.value, ast.Constant)
                            and isinstance(kw.value.value, str)):
                        values.add(kw.value.value)
            if isinstance(node, (ast.arg,)) and node.arg == "blame":
                continue
        for node in ast.walk(tree):        # defaults on signatures and fields
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for default in list(node.args.defaults) + [
                        d for d in node.args.kw_defaults if d is not None]:
                    if (isinstance(default, ast.Constant)
                            and isinstance(default.value, str)
                            and default.value in {"author", "caller", "sandbox",
                                                  "none", "unknown"}):
                        values.add(default.value)
        self.assertTrue(values, "не нашлось ни одного значения blame — сломан обход")
        self.assertEqual(
            sorted(values - set(diag.SANDBOX_BLAME_TO_DIAG)), [],
            "песочница передаёт вину, которой нет перевода в "
            "`diag.SANDBOX_BLAME_TO_DIAG`")

    def test_blame_reaches_the_diagnostic_but_not_the_wire(self) -> None:
        """The fault is available in-process and does NOT travel on the
        wire — a decision, not an oversight.

        The wire's dictionary is pinned byte for byte (`test_grounded_
        program`), and the tree sits editable in the live service's venv: a
        new field would ship to every consumer in the same second.
        """
        d = diag.Diagnostic(code=diag.SANDBOX_UNAVAILABLE, message_ru="x")
        self.assertEqual(d.blame, diag.BLAME_OURS)
        self.assertNotIn("blame", d.as_dict())
        self.assertEqual(sorted(d.as_dict()), ["code", "message_ru"])

    def test_an_unregistered_code_says_it_does_not_know(self) -> None:
        """`None` means "the code is not entered," not "nobody is at
        fault."

        Fail-open at runtime: a refusal that crashes while constructing a
        refusal would swallow the very cause it was created to carry.
        """
        d = diag.Diagnostic(code="KIR-Z999", message_ru="x")
        self.assertIsNone(d.blame)
        self.assertIsNone(diag.blame_of("KIR-Z999"))
        self.assertNotEqual(diag.blame_of("KIR-Z999"), diag.BLAME_NOBODY)


class TheTaxonomyIsDerivedFromTheHostNotCopied(unittest.TestCase):
    """The outcome at the host is asked by a CALL, not by copying its tables."""

    #: `KIR-B013` is not a refusal, but a third kind of answer, and the host
    #: has a LOUD branch on it: "reconnaissance does not reach here by
    #: construction." Calling it would mean testing someone else's guard,
    #: not our own table.
    SKIP = {"KIR-B013"}

    def test_registry_taxonomy_equals_what_the_host_decides(self) -> None:
        try:
            from kir import serving
        except Exception as exc:               # pragma: no cover
            self.skipTest(f"хозяйская дверь не импортируется здесь: {exc}")
        mismatched: list[str] = []
        for code, spec in sorted(diag.CODES.items()):
            if code in self.SKIP:
                continue
            errcode, _lead = serving._classify_refusal(
                {"diagnostics": [{"code": code}]})
            if errcode.name != spec.taxonomy:
                mismatched.append(
                    f"{code} ({spec.name}): реестр {spec.taxonomy}, "
                    f"хозяин {errcode.name}")
        self.assertEqual(
            mismatched, [],
            "таксономия реестра разошлась с `serving._classify_refusal`:\n  "
            + "\n  ".join(mismatched))

    def test_the_blame_taxonomy_debt_is_pinned(self) -> None:
        """THE DEBT IS CLOSED, AND ZERO HERE IS A MEASURED RESULT, NOT A
        PROMISE.

        There used to be EIGHT codes where the fix was addressed NOT to the
        author, yet the host answered "fix the program": `B011 E002 E005
        G107 G111 G116 L007 P000`. The host derived the outcome from the
        code's LETTER, using six handwritten tables,
        `serving._KIR_*_TO_ERRCODE`, and a letter knows nothing about fault.

        On 02.09.2026 the tables were removed, the outcome is read FROM
        HERE (`taxonomy_of`), and `register()` refuses such an entry on
        import. Details and a fail control on both sides —
        `test_the_outcome_is_read_from_the_registrar.py`.
        """
        self.assertEqual(
            diag.blame_taxonomy_debt(), (),
            "долг вина-против-таксономии ВЕРНУЛСЯ, хотя `register()` обязан "
            "был отказать такой строке на импорте — сломана дверь реестра")


class TheWalkCanSayNo(unittest.TestCase):
    """A FAIL CONTROL INSIDE THE SUITE: the walk must be able both to find
    and not to find.

    A guard that cannot turn red guards nothing; a guard that turns red on
    prose will drown in noise. Both outcomes are checked here on a
    stand-in tree, not the live one.
    """

    def _walk(self, source: str):
        with tempfile.TemporaryDirectory() as d:
            (pathlib.Path(d) / "planted.py").write_text(source, encoding="utf-8")
            return diag.codes_in_tree(d)

    def test_a_planted_bare_literal_is_found_with_its_place(self) -> None:
        decls, bare, unparsed = self._walk(
            'from kir.diag import Diagnostic\n'
            'def f():\n'
            '    return Diagnostic(code="KIR-Z999", message_ru="подсажено")\n')
        self.assertEqual(unparsed, [])
        self.assertEqual([(c, f) for c, f, _ in bare], [("KIR-Z999", "planted.py")])
        self.assertEqual(decls, {})

    def test_a_planted_declaration_is_found_with_its_name(self) -> None:
        decls, bare, _ = self._walk('PLANTED = "KIR-Z998"\n')
        self.assertEqual(list(decls), ["KIR-Z998"])
        self.assertEqual(decls["KIR-Z998"][0][0], "PLANTED")
        self.assertEqual(bare, [])

    def test_prose_is_not_an_occurrence(self) -> None:
        """A comment and a docstring are NOT an occurrence, and these are
        two different mechanisms.

        A comment is invisible to `ast` by construction; a docstring is
        visible and is excluded by name. Without this, module headers where
        codes are listed by the dozen would produce hundreds of false
        findings.
        """
        decls, bare, unparsed = self._walk(
            '"""Шапка, называющая KIR-Z997 и KIR-Z996."""\n'
            '# комментарий про KIR-Z995\n'
            'def f():\n'
            '    """Докстрока про KIR-Z994."""\n'
            '    return 1\n')
        self.assertEqual(unparsed, [])
        self.assertEqual(decls, {})
        self.assertEqual(bare, [])

    def test_a_second_name_for_one_code_is_named(self) -> None:
        """The previous shape of collision (two NAMES) is still caught."""
        decls, _bare, _ = self._walk('A = "KIR-Z993"\nB = "KIR-Z993"\n')
        self.assertEqual(sorted(n for n, _, _ in decls["KIR-Z993"]), ["A", "B"])

    def test_tests_are_not_read(self) -> None:
        """A copy of the constant in the test is not a wire declaration."""
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            (root / "tests").mkdir()
            (root / "tests" / "test_x.py").write_text(
                'COPY = "KIR-Z992"\n', encoding="utf-8")
            (root / "test_y.py").write_text('COPY2 = "KIR-Z991"\n', encoding="utf-8")
            decls, bare, _ = diag.codes_in_tree(str(root))
        self.assertEqual(decls, {})
        self.assertEqual(bare, [])


if __name__ == "__main__":       # pragma: no cover
    unittest.main()
