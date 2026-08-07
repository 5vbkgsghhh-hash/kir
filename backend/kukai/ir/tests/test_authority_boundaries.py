"""Architecture ratchets for the KIR authority-boundary split."""
from __future__ import annotations

import ast
import unittest
from pathlib import Path


IR_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = IR_ROOT.parents[1]


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


def _module_name(path: Path) -> str:
    rel = path.relative_to(BACKEND_ROOT).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _resolve_import_base(module: str, level: int, imported: str | None) -> str:
    if not level:
        return imported or ""
    package = module.rpartition(".")[0].split(".")
    keep = len(package) - (level - 1)
    base = package[:max(keep, 0)]
    if imported:
        base.extend(imported.split("."))
    return ".".join(base)


def _compiler_import_graph() -> dict[str, set[str]]:
    paths = [
        path for path in IR_ROOT.rglob("*.py")
        if "tests" not in path.parts
    ]
    by_module = {_module_name(path): path for path in paths}
    # Package facades intentionally re-export their children.  Counting those
    # convenience edges collapses the whole package into one artificial SCC;
    # the layer gate measures implementation modules instead.
    facades = {"kukai.ir", "kukai.ir.decompile", "kukai.ir.course"}
    nodes = set(by_module) - facades
    graph = {name: set() for name in nodes}
    for name in sorted(nodes):
        for node in ast.walk(_tree(by_module[name])):
            candidates: set[str] = set()
            if isinstance(node, ast.Import):
                candidates.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                base = _resolve_import_base(name, node.level, node.module)
                candidates.add(base)
                candidates.update(
                    f"{base}.{alias.name}" for alias in node.names
                    if alias.name != "*"
                )
            graph[name].update(candidate for candidate in candidates
                               if candidate in nodes)
    return graph


def _strong_components(
    graph: dict[str, set[str]],
) -> set[frozenset[str]]:
    """Tarjan SCCs with more than one implementation module."""
    next_index = 0
    indexes: dict[str, int] = {}
    lows: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: set[frozenset[str]] = set()

    def visit(node: str) -> None:
        nonlocal next_index
        indexes[node] = lows[node] = next_index
        next_index += 1
        stack.append(node)
        on_stack.add(node)
        for target in sorted(graph[node]):
            if target not in indexes:
                visit(target)
                lows[node] = min(lows[node], lows[target])
            elif target in on_stack:
                lows[node] = min(lows[node], indexes[target])
        if lows[node] != indexes[node]:
            return
        component: set[str] = set()
        while stack:
            target = stack.pop()
            on_stack.remove(target)
            component.add(target)
            if target == node:
                break
        if len(component) > 1:
            components.add(frozenset(component))

    for node in sorted(graph):
        if node not in indexes:
            visit(node)
    return components


class AuthorityBoundaryTests(unittest.TestCase):
    def test_compiler_cycles_cannot_grow(self) -> None:
        """The KIR implementation-module graph must remain acyclic."""
        self.assertEqual(_strong_components(_compiler_import_graph()), set())

    def test_foundational_modules_do_not_import_orchestrators(self) -> None:
        forbidden_by_module = {
            "authoring_validation.py": {
                "kukai.ir.authoring",
                "kukai.ir.serving",
                "kir_idempotence",
            },
            "hosted_geometry.py": {
                "kukai.ir.authoring",
                "kukai.ir.compiler",
                "kukai.ir.ground",
                "kukai.ir.serving",
            },
            "authoring_emit_support.py": {
                "kukai.ir.arch_emit",
                "kukai.ir.authoring",
                "kukai.ir.compiler",
                "kukai.ir.opening_emit",
                "kukai.ir.room_emit",
                "kukai.ir.serving",
                "kukai.ir.shape_emit",
                "kukai.ir.struct_emit",
            },
            "idempotence_contract.py": {
                "kukai.ir.serving",
                "kukai.ir.a5_live",
                "kir_idempotence",
                "kukai.main",
            },
            "idempotence_report.py": {
                "kukai.ir.serving",
                "kukai.ir.a5_live",
                "kir_idempotence",
                "kukai.main",
            },
            "a5_contract.py": {
                "kukai.ir.serving",
                "kir_idempotence",
                "kukai.main",
            },
            "a5_live.py": {
                "kukai.ir.serving",
                "kukai.main",
                "kukai.llm",
            },
            "document_guard.py": {
                "kukai.ir.serving",
                "kukai.ir.a5_live",
                "kukai.ir.acceptance_runtime",
            },
            "revit_read_helpers.py": {
                "kukai.ir.serving",
                "kukai.ir.decompile.extract",
                "kukai.ir.acceptance_live",
            },
            "acceptance_live.py": {
                "kukai.ir.serving",
                "kukai.ir.acceptance_runtime",
                "kukai.ir.acceptance_journal",
            },
            "acceptance_mutation.py": {
                "kukai.ir.serving",
                "kukai.ir.acceptance_runtime",
                "kukai.ir.acceptance_evidence",
                "kukai.ir.acceptance_journal",
                "kukai.ir.acceptance_probe",
            },
            "acceptance_probe.py": {
                "kukai.ir.serving",
                "kukai.ir.acceptance_runtime",
                "kukai.ir.acceptance_evidence",
                "kukai.ir.acceptance_journal",
            },
            "acceptance_evidence.py": {
                "kukai.ir.serving",
                "kukai.ir.acceptance_runtime",
                "kukai.ir.acceptance_journal",
            },
            "acceptance_journal.py": {
                "kukai.ir.serving",
                "kukai.ir.acceptance_runtime",
            },
            "acceptance_runtime.py": {
                "kukai.ir.serving",
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
        self.assertFalse({
            "_cs",
            "_eid",
            "_level_expr",
            "_readback_block",
            "_stamp_block",
            "_symbol_res",
            "endpoint_witness",
            "level_chain_witness",
        } & authoring_defs)

        idempotence_defs = _top_level_definitions(
            BACKEND_ROOT / "kir_idempotence.py")
        self.assertFalse({
            "SafetyContext",
            "IdempotenceError",
            "IdempotenceReport",
            "KindComparison",
        } & idempotence_defs)

    def test_authoring_reexports_the_shared_emission_authority(self) -> None:
        from kukai.ir import authoring
        from kukai.ir import authoring_emit_support as support

        names = (
            "EMIT_ID_RANGE",
            "EMIT_UNSUPPORTED",
            "IN_EMIT_DEFAULT",
            "_cs",
            "_eid",
            "_level_expr",
            "_readback_block",
            "_stamp_block",
            "_symbol_res",
            "bbox_extents_witness",
            "endpoint_witness",
            "level_chain_witness",
        )
        for name in names:
            with self.subTest(name=name):
                self.assertIs(getattr(authoring, name), getattr(support, name))

    def test_historical_import_contracts_are_reexported(self) -> None:
        import kir_idempotence as legacy_idempotence
        from kukai.ir import (
            a5_contract,
            a5_live,
            authoring,
            authoring_validation,
            idempotence_contract,
            idempotence_report,
            serving,
        )
        from kukai.ir import document_guard

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
        for path in [BACKEND_ROOT / "kir_idempotence.py",
                     *sorted(IR_ROOT.rglob("*.py"))]:
            if not path.exists() or "tests" in path.parts:
                continue
            tree = _tree(path)
            module_names: set[str] = set()
            for node in tree.body:          # только верхний уровень модуля
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
        for path in sorted(IR_ROOT.rglob("*.py")):
            if "tests" in path.parts:
                continue
            tree = _tree(path)
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
        self.assertEqual(
            offenders, [],
            "absolute deployment path in executable code: "
            + ", ".join(offenders))

    def test_level_and_document_identity_have_one_shared_authority(self) -> None:
        extract_imports = _direct_imports(
            IR_ROOT / "decompile" / "extract.py")
        acceptance_imports = _direct_imports(IR_ROOT / "acceptance_live.py")
        self.assertIn("kukai.ir.revit_read_helpers", extract_imports)
        self.assertIn("kukai.ir.revit_read_helpers", acceptance_imports)
        self.assertIn("kukai.ir.document_guard", acceptance_imports)


if __name__ == "__main__":
    unittest.main()
