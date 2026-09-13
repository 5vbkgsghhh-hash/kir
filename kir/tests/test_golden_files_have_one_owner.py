"""Every golden file has EXACTLY ONE declaring corpus.

WHY. On 13.08.2026 two tests owned the same two files in the shared
`golden/` directory, checking them against DIFFERENT programs:

    name                          test_families        test_golden
    families_create_type_full    259 program chars    277 chars — DIFFERENT
    families_load_family_whole   134 program chars    263 chars — DIFFERENT

One file cannot satisfy both programs. The bytes matched `test_golden`,
so `test_families` stood red — and read as "the emitter drifted from the
verified reference", even though the emitter had nothing to do with it.
Re-freezing would have turned the other test red, and so on in a circle:
**oscillation without convergence, wearing the word "drift"**.

THIS IS OUR OWN FORM 9, AND IT IS EXACTLY WHAT EXPLAINS WHY THE DEFECT
SURVIVED. The owner's docstring stated, verbatim: «Own files in the
SHARED golden/ dir (families_*.golden.cs — **no filename collision with
any other wave's programs**)». The claim was true when it was written,
and stopped being true when a later wave introduced the same two names.
**There is nothing to mutate prose with: no run will ever go red because
a comment is out of date.** So the same invariant is recorded here in
EXECUTABLE form.

THE NATURE OF THIS LIST: **COMPLETE BY CONSTRUCTION.** The makeup of the
corpora is not maintained by hand — it is obtained by walking the
`kir/**/tests/` modules and reading their declared corpora. A new corpus
set up tomorrow falls under the check on its own, without editing this
file; so the absence of a name here means "no such corpus exists", not
"we don't know about it".
"""
from __future__ import annotations

import ast
import importlib
import os
import pathlib
import pkgutil
import types
import unittest
from collections import defaultdict

GOLDEN_DIR = pathlib.Path(__file__).parent / "golden"

#: A corpus is recognized BY ITS CONTENT, not by an attribute name.
#:
#: The fourth mistake of this probe was exactly here: the list only read
#: `PROGRAMS`, while `test_annotation` declares its own corpus as
#: `ANNOTATION_PROGRAMS` — and its two goldens were never looked at at
#: all. This is canon form 7 in its pure state: a naming convention
#: holds nine times out of ten, and the tenth stays silent. So a corpus
#: is counted as ANY dict belonging to a module or its class, at least
#: one key of which names an existing file `golden/<ключ>.golden.cs`. We
#: ask the content — that is the authority.
#: IT DISTINGUISHES BY VALUE, NOT BY KEY — the fifth and last correction
#: to this probe.
#:
#: Golden keys are used by TWO different kinds of dicts: THE CORPUS,
#: which checks them (`name -> program`), and THE REGISTRY, which
#: describes them (`name -> a string with «pins / does NOT pin»`). The
#: fourth edition looked at the keys and therefore declared
#: `UNREVIEWED_GOLDENS` a second owner of everything recorded in it —
#: meaning the attestation record itself immediately produced a
#: "collision". Ownership belongs to whoever CHECKS, and only a program
#: can be checked.
def _looks_like_corpus(value: object) -> bool:
    if not isinstance(value, dict) or not value:
        return False
    named = [k for k in value
             if isinstance(k, str) and (GOLDEN_DIR / f"{k}.golden.cs").is_file()]
    if not named:
        return False
    return all(isinstance(value[k], dict) and "ops" in value[k] for k in named)


def _claims() -> dict[str, list[str]]:
    """{golden name: [who claims it]}, obtained by walking ALL test
    modules.

    THE ENVIRONMENT IS RESTORED EXPLICITLY, and this is not excess
    caution. The walk IMPORTS foreign modules, and some of them set
    `KIR_*`/`KUKAI_*` right on import; the environment guard in
    `conftest.py` caught exactly this on the very first run. The
    instrument was right, and the polluter was me: an observation has
    no right to change the state the next test runs in.
    """
    import kir.tests as tests_pkg

    before = dict(os.environ)
    try:
        return _walk(tests_pkg)
    finally:
        os.environ.clear()
        os.environ.update(before)


def _walk(tests_pkg) -> dict[str, list[str]]:
    """The owner is whoever DECLARED the corpus, not whoever imported it.

    THE FIRST EDITION OF THIS WALK WAS WRONG, and it was not a test that
    caught it but the question "show me the owners by name". It did
    `getattr(holder, "PROGRAMS")` over the whole `dir(module)`, which
    also picks up IMPORTED modules: `gate_runner` imports `PROGRAMS`
    from `test_golden`, so the owner of all 69 goldens turned out to be
    `test_gate_declares_its_ground.gate_runner`, and the actual
    declarations were never looked at at all. Both controls passed at
    the time — they were working on the same corrupted data, and the
    "at least 50" threshold was met by accident.

    Hence two rules, both recorded executably below:
    * holder modules are skipped (`ModuleType`) — import is not
      ownership;
    * corpora are distinguished by object IDENTITY. Two modules
      exposing ONE AND THE SAME dict are one owner; a collision is two
      DIFFERENT dicts claiming one name.
    """
    out: dict[str, list[str]] = defaultdict(list)
    for info in pkgutil.iter_modules(tests_pkg.__path__):
        if not info.name.startswith("test_"):
            continue
        path = pathlib.Path(tests_pkg.__path__[0]) / f"{info.name}.py"
        if not path.is_file():
            continue
        source = path.read_text(encoding="utf-8")
        # OWNERSHIP = CHECKING THE FILE, not a name coincidence. The
        # third mistake of this probe was here: `test_emitter_scope_
        # contract` declares its own `PROGRAMS` of 12 names that
        # coincide with goldens, and never touches the directory AT ALL
        # (0 mentions against 69 for `test_golden`) — it checks
        # emission scopes. A name that happens to match a file is not
        # ownership; ownership belongs to whoever READS the file.
        # 🔴 THE PREDICATE WAS REFINED ON 28.08.2026 — THE FOURTH
        # MISTAKE OF THIS SAME PROBE, AND EXACTLY THE ONE THE PARAGRAPH
        # ABOVE WARNS ABOUT.
        #
        # It used to say `"golden" not in source.lower()`, that is, a
        # WORD in the text. And `test_emitter_scope_contract` mentions
        # it EXACTLY ONCE — in a comment ("…a golden test, no new field
        # may be appended to it"), without touching the directory at
        # all. Twelve goldens were getting a second owner, and the FAIL
        # control, written exactly against this case, was going red.
        #
        # Ownership belongs to whoever READS the file — meaning what
        # must be searched for is a REFERENCE TO THE FILE: the
        # `.golden.cs` suffix or the directory name. Measured: the word
        # appears in 26 modules, a reference in 10.
        if not any(mark in source for mark in
                   ("golden.cs", "GOLDEN_DIR", "golden_dir")):
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        # THE PLACE OF DECLARATION — that is the authority. An import
        # `from … import PROGRAMS` gives the module the same attribute,
        # and `getattr` cannot tell them apart: the second edition of the
        # walk declared the owner of all 69 goldens to be the first
        # IMPORTER in alphabetical order. AST does tell them apart — an
        # assignment is a declaration.
        declared: list[str] = []
        for node in tree.body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                for target in (node.targets if isinstance(node, ast.Assign)
                               else [node.target]):
                    if isinstance(target, ast.Name):
                        declared.append(target.id)
            elif isinstance(node, ast.ClassDef):
                for sub in node.body:
                    if isinstance(sub, (ast.Assign, ast.AnnAssign)):
                        for target in (sub.targets if isinstance(sub, ast.Assign)
                                       else [sub.target]):
                            if isinstance(target, ast.Name):
                                declared.append(f"{node.name}.{target.id}")
        if not declared:
            continue
        try:
            module = importlib.import_module(f"{tests_pkg.__name__}.{info.name}")
        except Exception:  # noqa: BLE001 — a foreign broken module is not our concern
            continue
        for decl in declared:
            if "." in decl:
                holder_name, attr = decl.split(".", 1)
                holder = getattr(module, holder_name, None)
                programs = getattr(holder, attr, None) if holder else None
                owner = f"{info.name}.{holder_name}"
            else:
                programs = getattr(module, decl, None)
                owner = info.name
            if not _looks_like_corpus(programs):
                continue
            for golden in programs:
                if not isinstance(golden, str):
                    continue
                if (GOLDEN_DIR / f"{golden}.golden.cs").is_file():
                    if owner not in out[golden]:
                        out[golden].append(owner)
    return out


class EveryGoldenHasExactlyOneOwner(unittest.TestCase):

    def test_no_golden_is_claimed_twice(self):
        """Two owners of one file — oscillation without convergence."""
        claims = _claims()
        shared = {name: owners for name, owners in claims.items()
                  if len(owners) > 1}
        self.assertEqual(
            shared, {},
            "у голдена больше одного заявляющего корпуса: перезаморозка под "
            "одного немедленно красит другого, и так по кругу. Переименуй или "
            "оставь ОДНОГО владельца")

    def test_the_probe_actually_found_owners(self):
        """A PASS control: an empty walk would give green without
        checking anything.

        Exactly the vacuous green we have been catching all month: "no
        violations" and "I did not look anywhere" print identically.
        """
        claims = _claims()
        self.assertGreaterEqual(
            len(claims), 50,
            f"обход нашёл {len(claims)} заявленных голденов — прибор не дошёл "
            f"до корпусов, и зелёный выше вакуумный")

    def test_the_walk_names_the_real_owner(self):
        """A control on the WALK, not on the predicate: the owner is
        named correctly.

        The two previous editions of this walk each gave exactly one
        owner per golden — and both times the WRONG one: first
        `gate_runner`, which merely imports `PROGRAMS`, then the first
        importer alphabetically. The count "1 owner per file" was green
        in both cases. So what must be checked is the NAME.
        """
        claims = _claims()
        self.assertEqual(claims.get("auth_contour_l"), ["test_golden"])

    def test_declaring_a_corpus_is_not_owning_a_golden(self):
        """A FAIL control on the walk: a name that matches a file is not
        ownership.

        `test_emitter_scope_contract` declares its own `PROGRAMS`, 12
        names of which coincide with goldens, and never touches the
        directory. If it surfaces as an owner, the predicate is again
        judging by APPEARANCE, not by substance.
        """
        owners = {owner for owners in _claims().values() for owner in owners}
        self.assertNotIn("test_emitter_scope_contract", owners)

    def test_the_probe_can_say_no(self):
        """A FAIL control: a planted second owner must turn red.

        Without it, "zero collisions" is indistinguishable from a
        matcher that answers "no" to any question.
        """
        claims = _claims()
        self.assertTrue(claims, "нечего проверять")
        victim = sorted(claims)[0]
        forged = dict(claims)
        forged[victim] = forged[victim] + ["_подставной_владелец"]
        shared = {n: o for n, o in forged.items() if len(o) > 1}
        self.assertEqual(
            sorted(shared), [victim],
            "подставная коллизия не обнаружена — предикат не различает")


if __name__ == "__main__":
    unittest.main()
