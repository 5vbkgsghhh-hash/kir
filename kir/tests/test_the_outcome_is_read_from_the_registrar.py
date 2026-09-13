"""THE REFUSAL OUTCOME LIVES IN ONE PLACE, AND THE CONSUMER READS IT THERE.

🔴 WHY THIS WAS SET UP (02.09.2026, findings E-96 and E-85).

MEASUREMENT BEFORE, by running over 106 registered codes
(`serving._classify_refusal` was called on each one, not read by eye):

    blame      author 67 · caller 6 · environment 19 · none 1 · ours 13
    host       KIR_PROGRAM_REFUSED 78 of 106
    DEBT       14 codes arrived at the author with a blame that is NOT
               theirs; of those, 8 with blame `ours`/`environment` — "fix
               your program" for our own failure or for the state of the
               environment.

The worst was `KIR-P000`, a compiler panic: the author of a CORRECT
program was ordered to rewrite it, and with `retryable=True` on top, i.e.
an invitation to resend the same program and get the same panic.

🔴 THE PLAN TO "DERIVE ErrCode FROM BLAME" IS REFUTED BY THE RUN, AND THIS
IS THE NUMBER:

    blame author       -> outcomes 2
    blame environment  -> outcomes 5
    blame ours         -> outcomes 5
    (blame, disposition) -> 4 ambiguous pairs out of 37, 19 codes

There is no function of blame. Blame answers "WHO fixes it", the taxonomy
answers "WHAT happened to the world"; `KIR-X003` and `KIR-X007` are both
`environment`, and the difference between them is "retry" versus
"retrying is FORBIDDEN, the write may have landed."

WHAT WAS DONE INSTEAD, AND WHAT IS GUARDED HERE

1. There is ONE carrier: the outcome sits with the disposition, `serving`
   READS it. The six hand-written tables
   `_KIR_{X,W,A,K,R,B}_TO_ERRCODE` were removed, and a second table
   cannot be set up unnoticed — the `ast` walk below goes red on it.
2. Blame FORBIDS one outcome: `diag.register()` refuses at import on any
   line where the repair is not the author's, yet the outcome says "fix
   your program."
3. The default-by-letter speaks ONLY about an unregistered code — not one
   of the 107 takes its outcome from there.
4. `KIR-B016`: the capability is permitted but not installed in the
   environment — the environment's blame, not the author's (E-85).
"""
from __future__ import annotations

import ast
import dataclasses
import pathlib
import unittest

from kir import diag


class TheHostReadsTheRegistrar(unittest.TestCase):
    """FAIL CONTROL: the classifier must FOLLOW the disposition."""

    #: An ordinary author code, nothing special about it: a substitution on
    #: it proves reading, not a coincidence between tables on a special case.
    PROBE = "KIR-G101"

    def _host(self, code: str) -> str:
        from kir import serving
        errcode, _lead = serving._classify_refusal(
            {"diagnostics": [{"code": code}]})
        return errcode.name

    def test_substituting_the_outcome_moves_the_host_and_restoring_returns_it(self) -> None:
        """BOTH OUTCOMES. A guard that cannot turn red guards nothing.

        If `serving` held ITS OWN table, a substitution at the disposition
        would move nothing, and the first `assert` would go red — which is
        exactly the checked property "there is one carrier."
        """
        before = self._host(self.PROBE)
        self.assertEqual(before, diag.CODES[self.PROBE].taxonomy)

        orig = diag.CODES[self.PROBE]
        other = ("KIR_UNCONFIRMED" if orig.taxonomy != "KIR_UNCONFIRMED"
                 else "KIR_RUNTIME_REFUSED")
        diag.CODES[self.PROBE] = dataclasses.replace(orig, taxonomy=other)
        try:
            self.assertEqual(
                self._host(self.PROBE), other,
                "хозяин НЕ поехал за распорядителем — значит исход у него "
                "свой, и второй носитель вернулся")
        finally:
            diag.CODES[self.PROBE] = orig
        self.assertEqual(self._host(self.PROBE), before,
                         "возврат не восстановил исход")

    def test_every_registered_code_gets_its_outcome_from_the_registrar(self) -> None:
        """The denominator first: 107 codes, and not a single discrepancy.

        `KIR-B013` is excluded: at the disposition it carries a LOUD branch
        "reconnaissance does not reach here by construction", and calling
        it would mean testing someone else's guard.
        """
        self.assertGreaterEqual(
            len(diag.CODES), 100,
            f"заведено всего {len(diag.CODES)} кодов — сломан реестр, а не тест")
        mismatched = []
        for code, spec in sorted(diag.CODES.items()):
            if code == diag.SANDBOX_RECON:
                continue
            got = self._host(code)
            if got != spec.taxonomy:
                mismatched.append(f"{code} ({spec.name}): реестр "
                                  f"{spec.taxonomy}, хозяин {got}")
        self.assertEqual(mismatched, [], "\n  ".join(mismatched))

    def test_the_letter_fallback_speaks_only_of_unregistered_codes(self) -> None:
        """The default-by-letter is not a second table, and this is checked from both sides.

        YES: an unregistered code does take the default (otherwise the
        default is dead and "it's only for others" is empty words).
        NO: not one of the codes registered before it reaches it.
        """
        from kir import serving

        # NO: a registered code does not touch the default — I substitute
        # the entire default and require that the answers do not move.
        original = dict(serving._UNREGISTERED_LETTER_FALLBACK)
        from kir.envelope import ErrCode
        answers = {c: self._host(c) for c in sorted(diag.CODES)
                   if c != diag.SANDBOX_RECON}
        serving._UNREGISTERED_LETTER_FALLBACK.update(
            {k: ErrCode.KIR_POSTCONDITION_VIOLATED for k in original})
        try:
            moved = [c for c, was in answers.items() if self._host(c) != was]
            self.assertEqual(
                moved, [],
                "заведённые коды взяли исход у умолчания по букве — "
                "значит распорядителя не спрашивали")
        finally:
            serving._UNREGISTERED_LETTER_FALLBACK.clear()
            serving._UNREGISTERED_LETTER_FALLBACK.update(original)

        # YES: an unregistered code takes the default.
        self.assertNotIn("KIR-X777", diag.CODES)
        self.assertEqual(self._host("KIR-X777"), "KIR_RUNTIME_REFUSED")
        self.assertNotIn("KIR-B777", diag.CODES)
        self.assertEqual(self._host("KIR-B777"), "KIR_PROGRAM_REFUSED")


class NoSecondTableMapsACodeToAnOutcome(unittest.TestCase):
    """A SECOND TABLE CANNOT BE SET UP SILENTLY.

    What is asked is a PROPERTY ("no dictionary in `serving` translates a
    KIR code into an `ErrCode`"), not the shape of the removed names: a
    guard on the names `_KIR_*_TO_ERRCODE` would be defeated by a rename,
    i.e. it would guard nothing (form 54 of this tree).
    """

    def _serving_source(self) -> str:
        p = pathlib.Path(__file__).resolve().parents[1] / "serving.py"
        return p.read_text(encoding="utf-8")

    @staticmethod
    def _is_code_literal(v) -> bool:
        return (isinstance(v, str) and v.startswith("KIR-") and len(v) >= 8
                and v[4].isalpha() and v[5:].isdigit())

    def test_no_dict_in_serving_maps_a_kir_code_to_an_errcode(self) -> None:
        # The disposition's code-constant names — a key by NAME is also a table.
        code_names = {n for n, v in vars(diag).items()
                      if n.isupper() and self._is_code_literal(v)}
        offenders: list[str] = []
        tree = ast.parse(self._serving_source())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            for key, value in zip(node.keys, node.values):
                if key is None:
                    continue
                key_is_code = (
                    (isinstance(key, ast.Constant)
                     and self._is_code_literal(key.value))
                    or (isinstance(key, ast.Name) and key.id in code_names))
                value_is_errcode = (
                    isinstance(value, ast.Attribute)
                    and isinstance(value.value, ast.Name)
                    and value.value.id == "ErrCode")
                if key_is_code and value_is_errcode:
                    offenders.append(
                        f"строка {key.lineno}: код -> ErrCode.{value.attr}")
        self.assertEqual(
            offenders, [],
            "в `serving` завелась ВТОРАЯ таблица исходов — исход живёт у "
            "распорядителя (`kir/diag.py`, колонка `taxonomy`), и потребитель "
            "обязан его ЧИТАТЬ (`diag.taxonomy_of`), а не пересказывать:\n  "
            + "\n  ".join(offenders))

    def test_the_six_removed_tables_did_not_come_back(self) -> None:
        """The direct half of the same thing: no removed names exist in the module or in the text."""
        from kir import serving
        for letter in "XWAKRB":
            self.assertFalse(
                hasattr(serving, f"_KIR_{letter}_TO_ERRCODE"),
                f"_KIR_{letter}_TO_ERRCODE вернулась — исход снова живёт дважды")


class BlameForbidsBlamingTheAuthor(unittest.TestCase):
    """FAIL CONTROL AT THE DISPOSITION'S DOOR: refuse and let through."""

    def tearDown(self) -> None:
        for code, name in (("KIR-Z001", "_CONTROL_DEBT"),
                           ("KIR-Z002", "_CONTROL_OK")):
            diag.CODES.pop(code, None)
            diag._NAMES.pop(name, None)

    def test_a_row_that_blames_the_author_for_our_defect_is_refused(self) -> None:
        with self.assertRaises(AssertionError) as caught:
            diag.register("KIR-Z001", name="_CONTROL_DEBT", home="x",
                          family="x", blame=diag.BLAME_OURS,
                          taxonomy="KIR_PROGRAM_REFUSED")
        self.assertIn("правь программу", str(caught.exception))

    def test_the_same_row_with_a_truthful_outcome_passes(self) -> None:
        """The second half: the door is not shut solid, it discriminates."""
        spec = diag.register("KIR-Z002", name="_CONTROL_OK", home="x",
                             family="x", blame=diag.BLAME_OURS,
                             taxonomy="KIR_PRECONDITION_UNMET")
        self.assertEqual(spec.taxonomy, "KIR_PRECONDITION_UNMET")

    def test_the_debt_is_zero_and_the_caller_remainder_is_named(self) -> None:
        """A NUMBER, NOT A PROMISE. Zero here is a run over 107 codes.

        The `caller` remainder is NAMED and pinned: it is left untouched
        deliberately (for it `KIR_PROGRAM_REFUSED` does not lie about the
        world — there was no effect, a retry is safe), but it cannot grow
        silently.
        """
        self.assertEqual(diag.blame_taxonomy_debt(), ())
        self.assertEqual(
            diag.blame_taxonomy_debt((diag.BLAME_CALLER,)),
            ("KIR-B014", "KIR-G103", "KIR-G106", "KIR-L005",
             "KIR-P004", "KIR-S001"),
            "остаток «чинит ВЫЗЫВАЮЩИЙ, а хозяин шлёт править программу` "
            "сдвинулся — прочитай, что именно, прежде чем править ожидание")

    def test_the_eight_named_codes_no_longer_blame_the_author(self) -> None:
        """BY NAME, NOT BY SUM: eight debt codes and their new outcomes."""
        closed = {
            "KIR-P000": "INTERNAL_UNHANDLED",
            "KIR-B011": "INTERNAL_UNHANDLED",
            "KIR-E002": "KIR_PRECONDITION_UNMET",
            "KIR-E005": "KIR_PRECONDITION_UNMET",
            "KIR-G107": "KIR_PRECONDITION_UNMET",
            "KIR-G111": "KIR_PRECONDITION_UNMET",
            "KIR-G116": "KIR_PRECONDITION_UNMET",
            "KIR-L007": "KIR_PRECONDITION_UNMET",
        }
        for code, want in sorted(closed.items()):
            with self.subTest(code=code):
                self.assertEqual(diag.CODES[code].taxonomy, want)
                self.assertIn(diag.CODES[code].blame,
                              (diag.BLAME_OURS, diag.BLAME_ENVIRONMENT))


class ACapabilityAbsentIsNotTheAuthorsFault(unittest.TestCase):
    """E-85: "permitted but not installed" — a fact about the ENVIRONMENT.

    MEASUREMENT BEFORE (run with a real sandbox, a `/usr/bin/python3` child
    without shapely, the allowlist contains `shapely`):

        import shapely.geometry -> KIR-B004 blame=author  KIR_PROGRAM_REFUSED
        import shapely          -> KIR-B006 blame=author  KIR_PROGRAM_REFUSED

    The prose was already correct at this point (the 01.09 fix taught the
    refusal to listen to the warm-up flag `NOT LOADED:`) — but the
    machine-readable half, in THREE fields at once, said "the author is at
    fault", and the author of a correct program went to fix an allowlist
    they had never touched.
    """

    def test_the_code_exists_and_its_repair_is_the_environments(self) -> None:
        spec = diag.CODES[diag.SANDBOX_CAPABILITY_ABSENT]
        self.assertEqual(spec.blame, diag.BLAME_ENVIRONMENT)
        self.assertNotEqual(spec.taxonomy, "KIR_PROGRAM_REFUSED")

    def test_the_sandbox_vocabulary_translates_the_new_blame(self) -> None:
        """The sixth value of the sandbox dictionary was translated, not set up silently."""
        self.assertEqual(diag.SANDBOX_BLAME_TO_DIAG["environment"],
                         diag.BLAME_ENVIRONMENT)

    def test_import_reason_separates_absent_from_forbidden(self) -> None:
        """BOTH OUTCOMES OF ONE FUNCTION: naming the environment and naming the prohibition.

        A pure function, so it is checked directly, without spinning up a
        sandbox: the absence of substitutions is exactly the condition
        under which the number can be trusted.
        """
        import sys

        from kir import sandbox

        missing = "нетакоймодуль"
        self.assertNotIn(missing, sys.modules)
        code, reason = sandbox._import_reason(f"{missing}.sub", (missing,))
        self.assertEqual(code, diag.SANDBOX_CAPABILITY_ABSENT)
        self.assertIn("НЕ УСТАНОВЛЕНА", reason)

        code, reason = sandbox._import_reason("socket", ("math",))
        self.assertEqual(code, diag.SANDBOX_FORBIDDEN_IMPORT)

        # NOT A PACKAGE — this is already the author's own line, and the code stays the author's.
        code, _reason = sandbox._import_reason("math.foo", ("math",))
        self.assertEqual(code, diag.SANDBOX_FORBIDDEN_IMPORT)

    def test_an_absent_library_refuses_with_the_environments_code(self) -> None:
        """LIVE, WITH A REAL SANDBOX. Skipped if the environment is not the right one."""
        import os
        import subprocess

        exe = "/usr/bin/python3"
        if not os.path.exists(exe):
            self.skipTest(f"{exe} отсутствует — замер не состоится")
        probe = subprocess.run([exe, "-c", "import shapely"],
                               capture_output=True)
        if probe.returncode == 0:
            self.skipTest("shapely доступен ребёнку — нужного состояния среды нет")

        from kir.sandbox import SandboxPolicy, execute_author_script
        policy = SandboxPolicy(python_exe=exe,
                               allowed_imports=("math", "shapely"))
        for source in ("import shapely.geometry\n", "import shapely\n"):
            with self.subTest(source=source.strip()):
                res = execute_author_script(source, policy=policy)
                self.assertIsNotNone(res.refusal, "отказа нет — замер не состоялся")
                self.assertEqual(res.refusal.code, diag.SANDBOX_CAPABILITY_ABSENT)
                self.assertEqual(res.refusal.blame, "environment")


if __name__ == "__main__":       # pragma: no cover
    unittest.main()
