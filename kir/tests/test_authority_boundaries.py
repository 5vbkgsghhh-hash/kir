"""Architecture ratchets for the KIR authority-boundary split."""
from __future__ import annotations

import ast
import unittest
from pathlib import Path


IR_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = IR_ROOT.parents[1]

#: THE DENOMINATOR FOR BOTH SOURCE WALKS. How many non-test modules of
#: the package they must read for their «no offenders» to mean anything.
#:
#: 🔴 WHY A NUMBER, AND NOT `offenders == []` (measured 02.09.2026). Both
#: walks below are one-sided: they can say "found something bad" but
#: cannot say "I went blind." A walk whose mask, root, or filter has
#: drifted from the tree finds zero offenders and prints the exact same
#: green as a clean tree. This is exactly how the emitter guard stayed
#: GREEN on 02.09 while seeing only 35 names out of 72: the bodies had
#: moved, and `assert names` only catches emptiness.
#:
#: Measured 02.09.2026: the package has **967** `*.py` files, of which
#: **300** are outside `tests`. The floor is set with margin for
#: directory cleanup, but at three times the value below which a walk
#: should be considered blind.
_ИСХОДНИКОВ_ВНЕ_ТЕСТОВ_НЕ_МЕНЬШЕ = 250


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _direct_imports(path: Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def _top_level_definitions(path: Path) -> set[str]:
    return {
        node.name
        for node in _tree(path).body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }


class AuthorityBoundaryTests(unittest.TestCase):
    def test_foundational_modules_do_not_import_orchestrators(self) -> None:
        forbidden_by_module = {
            "authoring_validation.py": {
                "kir.authoring",
                "kir.serving",
                "kir.idempotence",
            },
            "idempotence_contract.py": {
                "kir.serving",
                "kir.a5_live",
                "kir.idempotence",
                "kukai.main",
            },
            "idempotence_report.py": {
                "kir.serving",
                "kir.a5_live",
                "kir.idempotence",
                "kukai.main",
            },
            "a5_contract.py": {
                "kir.serving",
                "kir.idempotence",
                "kukai.main",
            },
            "a5_live.py": {
                "kir.serving",
                "kukai.main",
                "kukai.llm",
            },
            "document_guard.py": {
                "kir.serving",
                "kir.a5_live",
                "kir.acceptance_runtime",
            },
            "revit_read_helpers.py": {
                "kir.serving",
                "kir.decompile.extract",
                "kir.acceptance_live",
                # 25.08: the QUERY door kept ITS OWN level-reading chain
                # at four BuiltInParameters against seven for the
                # authority. The copy silently returned an empty level
                # for beams (measured 03.08: 2367 beams, 116 stairs, 21
                # railings with level_id=null), and a
                # `where level_name=…` query dropped all of them.
                "kir.compiler",
            },
            "acceptance_live.py": {
                "kir.serving",
                "kir.acceptance_runtime",
                "kir.acceptance_journal",
            },
            "acceptance_mutation.py": {
                "kir.serving",
                "kir.acceptance_runtime",
                "kir.acceptance_evidence",
                "kir.acceptance_journal",
                "kir.acceptance_probe",
            },
            "acceptance_probe.py": {
                "kir.serving",
                "kir.acceptance_runtime",
                "kir.acceptance_evidence",
                "kir.acceptance_journal",
            },
            "acceptance_evidence.py": {
                "kir.serving",
                "kir.acceptance_runtime",
                "kir.acceptance_journal",
            },
            "acceptance_journal.py": {
                "kir.serving",
                "kir.acceptance_runtime",
            },
            "acceptance_runtime.py": {
                "kir.serving",
            },
        }
        for filename, forbidden in forbidden_by_module.items():
            with self.subTest(module=filename):
                imported = _direct_imports(IR_ROOT / filename)
                self.assertFalse(
                    imported & forbidden,
                    f"{filename} crossed its authority boundary: "
                    f"{sorted(imported & forbidden)}",
                )

    def test_orchestrators_no_longer_define_extracted_authorities(self) -> None:
        serving_defs = _top_level_definitions(IR_ROOT / "serving.py")
        self.assertFalse({
            "_A5Recovery",
            "_a5_request_hash",
            "_scope_leaves",
            "_orphan_sweep_cs",
        } & serving_defs)
        self.assertFalse({
            "build_scope_census_cs",
            "parse_scope_census",
            "parse_mutation_observation",
            "parse_acceptance_observation",
            "assess_acceptance",
            "prepare_acceptance",
        } & serving_defs)

        authoring_defs = _top_level_definitions(IR_ROOT / "authoring.py")
        self.assertNotIn("validate", authoring_defs)

        idempotence_defs = _top_level_definitions(
            IR_ROOT / "idempotence.py")
        self.assertFalse({
            "SafetyContext",
            "IdempotenceError",
            "IdempotenceReport",
            "KindComparison",
        } & idempotence_defs)

    def test_historical_import_contracts_are_reexported(self) -> None:
        from kir import idempotence as legacy_idempotence
        from kir import (
            a5_contract,
            a5_live,
            authoring,
            authoring_validation,
            idempotence_contract,
            idempotence_report,
            serving,
        )
        from kir import document_guard

        self.assertIs(authoring.validate, authoring_validation.validate)
        self.assertIs(serving._A5Recovery, a5_live._A5Recovery)
        self.assertIs(serving._a5_request_hash, a5_contract._a5_request_hash)
        self.assertIs(serving._scope_leaves, a5_contract._scope_leaves)
        self.assertIs(
            serving._bind_read_to_document,
            document_guard.bind_read_to_document,
        )
        self.assertIs(
            legacy_idempotence.SafetyContext,
            idempotence_contract.SafetyContext,
        )
        self.assertIs(
            legacy_idempotence.IdempotenceReport,
            idempotence_report.IdempotenceReport,
        )

    def test_no_function_local_import_shadows_a_module_import(self) -> None:
        """A repeated in-function ``import`` makes the name local to the WHOLE
        function, so any earlier use of it raises ``UnboundLocalError``.

        Measured live 2026-08-02 on the 59-storey tower: ``run_idempotence``
        imported ``json`` again inside a debug branch near the end, and the
        refusal handler 460 lines ABOVE it — the one that reports which
        materialized chunks failed the typed plan — died with
        ``UnboundLocalError`` instead. The crash replaced the diagnosis: the
        operator saw ``materialize_failed`` and not the list of refused chunks.

        The dangerous shape is specifically *shadowing*: a local import of a
        name the module already imports. A local import of something new is a
        legitimate cycle-breaker and is not flagged.
        """

        offenders: list[str] = []
        прочитано = 0
        for path in [IR_ROOT / "idempotence.py",
                     *sorted(IR_ROOT.rglob("*.py"))]:
            if not path.exists() or "tests" in path.parts:
                continue
            tree = _tree(path)
            прочитано += 1
            module_names: set[str] = set()
            for node in tree.body:          # only the module's top level
                if isinstance(node, ast.Import):
                    module_names.update(
                        (a.asname or a.name.split(".")[0]) for a in node.names)
                elif isinstance(node, ast.ImportFrom):
                    module_names.update((a.asname or a.name) for a in node.names)
            for fn in ast.walk(tree):
                if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for node in ast.walk(fn):
                    names: list[str] = []
                    if isinstance(node, ast.Import):
                        names = [(a.asname or a.name.split(".")[0])
                                 for a in node.names]
                    elif isinstance(node, ast.ImportFrom):
                        names = [(a.asname or a.name) for a in node.names]
                    for name in names:
                        if name in module_names:
                            offenders.append(
                                f"{path.name}::{fn.name}:{node.lineno} "
                                f"shadows module import {name!r}")
        # THE DENOMINATOR FIRST: a walk that lost the tree also gives an
        # empty list — and reads as "no shadows."
        self.assertGreaterEqual(
            прочитано, _ИСХОДНИКОВ_ВНЕ_ТЕСТОВ_НЕ_МЕНЬШЕ,
            f"обход прочёл {прочитано} модулей при поле "
            f"{_ИСХОДНИКОВ_ВНЕ_ТЕСТОВ_НЕ_МЕНЬШЕ} (замер 02.09.2026 — 300 вне "
            f"`tests` из 967). Это заявление о ХОДОКЕ, а не о дереве: пустой "
            f"список ниже НИЧЕГО не означает")
        self.assertEqual(
            offenders, [],
            "function-local import shadows a module-level one: "
            + "; ".join(offenders))

    def test_no_absolute_deployment_path_is_executable(self) -> None:
        """A deployment path in RUNNING code makes KIR box-only.

        Four modules once carried ``/opt/kukai-rebuild1`` as a literal, each
        guarded by ``isdir()`` — which asks whether the path exists ON THIS
        MACHINE, not whether the code was imported FROM it.  Measured
        2026-08-02: a process started in a worktree resolved its telemetry to
        the PRODUCTION corpora, and the open-source cut refused every write with
        ``KIR-A005``.  ``install_paths`` is the single authority now.

        Prose keeps the history on purpose, so this reads STRING CONSTANTS via
        the AST and exempts docstrings — a regex over these files would flag the
        very comments that explain the rule.
        """

        offenders: list[str] = []
        прочитано = 0
        for path in sorted(IR_ROOT.rglob("*.py")):
            if "tests" in path.parts:
                continue
            tree = _tree(path)
            прочитано += 1
            docstrings = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.Module, ast.ClassDef,
                                     ast.FunctionDef, ast.AsyncFunctionDef)):
                    first = node.body[0] if node.body else None
                    if (isinstance(first, ast.Expr)
                            and isinstance(first.value, ast.Constant)
                            and isinstance(first.value.value, str)):
                        docstrings.add(id(first.value))
            for node in ast.walk(tree):
                if (isinstance(node, ast.Constant)
                        and isinstance(node.value, str)
                        and "/opt/kukai-rebuild1" in node.value
                        and id(node) not in docstrings):
                    offenders.append(
                        f"{path.relative_to(IR_ROOT)}:{node.lineno}")
        # THE DENOMINATOR FIRST: see the argument at
        # `_ИСХОДНИКОВ_ВНЕ_ТЕСТОВ_НЕ_МЕНЬШЕ`.
        self.assertGreaterEqual(
            прочитано, _ИСХОДНИКОВ_ВНЕ_ТЕСТОВ_НЕ_МЕНЬШЕ,
            f"обход прочёл {прочитано} модулей при поле "
            f"{_ИСХОДНИКОВ_ВНЕ_ТЕСТОВ_НЕ_МЕНЬШЕ} (замер 02.09.2026 — 300). "
            f"Это заявление о ХОДОКЕ, а не о дереве")
        self.assertEqual(
            offenders, [],
            "absolute deployment path in executable code: "
            + ", ".join(offenders))

    def test_level_and_document_identity_have_one_shared_authority(self) -> None:
        extract_imports = _direct_imports(
            IR_ROOT / "decompile" / "extract.py")
        acceptance_imports = _direct_imports(IR_ROOT / "acceptance_live.py")
        self.assertIn("kir.revit_read_helpers", extract_imports)
        self.assertIn("kir.revit_read_helpers", acceptance_imports)
        self.assertIn("kir.document_guard", acceptance_imports)
        # The third reader of the level is the query door. Before 25.08
        # it carried a copy, and the copy was three links poorer than the
        # authority.
        compiler_imports = _direct_imports(IR_ROOT / "compiler.py")
        self.assertIn("kir.revit_read_helpers", compiler_imports)


if __name__ == "__main__":
    unittest.main()
