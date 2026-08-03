"""Property invariant rules INV001-INV012 — cheap deterministic prechecks
on CodeProposal.csharp_code BEFORE the Roslyn compile gate. All rules
return a list[InvariantViolation]; empty list means proposal passes.
"""
from __future__ import annotations
import pytest

from kukai.modeling.execution.invariants import (
    InvariantViolation, check_proposal_invariants,
)
from kukai.modeling.schemas.identifiers import XYZ
from kukai.modeling.schemas.llm import (
    CodeProposal, DryRunSummary, FailureCategory, FailureCheckResult,
    InlineRagCitation,
)
from kukai.modeling.schemas.tasks import ExpectedElementsSpec


def _checks():
    return {c: FailureCheckResult(checked=True, applicable=False) for c in FailureCategory}


def _proposal(csharp_code: str, *, transaction_name: str = "Place column") -> CodeProposal:
    return CodeProposal(
        task_id="t1task01",
        csharp_code=csharp_code,
        explanation="x",
        expected_elements=ExpectedElementsSpec(category="OST_StructuralColumns", count=1),
        requires_assemblies=["RevitAPI"],
        transaction_name=transaction_name,
        revit_version="2026",
        failure_mode_checks=_checks(),
        rag_citations=[InlineRagCitation(snippet_id="s", api_called="X")],
        dry_run=DryRunSummary(selected_symbol_id=10, proposed_xyz_mm=(0.0, 0.0, 0.0)),
    )


# Happy path: realistic well-formed column placement code.
_GOOD_CODE = """// RAG:#snip_a
using (var t = new Transaction(doc, "Place column")) {
  t.Start();
  var sym = doc.GetElement(new ElementId(10)) as FamilySymbol;
  if (sym == null) throw new InvalidOperationException();
  if (!sym.IsActive) sym.Activate();
  doc.Regenerate();
  var lvl = doc.GetElement(new ElementId(20)) as Level;
  if (lvl == null) throw new InvalidOperationException();
  var p = new XYZ(
    UnitUtils.ConvertToInternalUnits(0.0, UnitTypeId.Millimeters),
    UnitUtils.ConvertToInternalUnits(0.0, UnitTypeId.Millimeters),
    UnitUtils.ConvertToInternalUnits(0.0, UnitTypeId.Millimeters));
  var inst = doc.Create.NewFamilyInstance(p, sym, lvl, StructuralType.Column);
  __result__ = new int[] { inst.Id.IntegerValue };
  t.Commit();
}
"""


_NESTED_TX = (
    "using (var t1 = new Transaction(doc, \"Outer\")) {\n  t1.Start();\n"
    "  using (var t2 = new Transaction(doc, \"Inner\")) {\n    t2.Start();\n"
    "    __result__ = new int[] { 1 };\n    t2.Commit();\n  }\n  t1.Commit();\n}\n"
)

_UNBALANCED_TX = (
    "using (var t = new Transaction(doc, \"Place column\")) {\n  t.Start();\n  t.Start();\n"
    "  __result__ = new int[] { };\n  t.Commit();\n}\n"
)

_UNGUARDED_GET_ELEMENT = (
    "using (var t = new Transaction(doc, \"Place column\")) {\n  t.Start();\n"
    "  var sym = doc.GetElement(new ElementId(10));\n  var inst = sym.Name;\n"
    "  __result__ = new int[] { };\n  t.Commit();\n}\n"
)


# Defensive guard-clause style: ONE Start, ONE Commit on the happy path, and
# several RollBacks (one per null-check + a catch-all). This is GOOD practice and
# must NOT trip INV010 even though terminators (5) outnumber Starts (1).
_DEFENSIVE_TX = """using (var t = new Transaction(doc, "Place column")) {
  t.Start();
  try {
    var sym = doc.GetElement(new ElementId(10)) as FamilySymbol;
    if (sym == null) { t.RollBack(); throw new InvalidOperationException(); }
    if (!sym.IsActive) { sym.Activate(); doc.Regenerate(); }
    var lvl = doc.GetElement(new ElementId(20)) as Level;
    if (lvl == null) { t.RollBack(); throw new InvalidOperationException(); }
    var p = new XYZ(0, 0, 0);
    var inst = doc.Create.NewFamilyInstance(p, sym, lvl, StructuralType.Column);
    if (inst == null) { t.RollBack(); throw new InvalidOperationException(); }
    t.Commit();
    __result__ = new int[] { inst.Id.Value };
  } catch {
    if (t.HasStarted() && !t.HasEnded()) t.RollBack();
    throw;
  }
}
"""

# Orphan terminator: a Commit() with no Start() (wrong variable / copy-paste).
_ORPHAN_TX = (
    "using (var t = new Transaction(doc, \"Place column\")) {\n"
    "  __result__ = new int[] { 1 };\n  t.Commit();\n}\n"
)


def test_good_code_passes_all_invariants():
    violations = check_proposal_invariants(_proposal(_GOOD_CODE))
    assert violations == [], f"unexpected violations: {[v.rule_id for v in violations]}"


def test_defensive_rollbacks_pass_inv010():
    """Guard-clause RollBacks (terminators > Starts) are valid — INV010 must not fire."""
    violations = check_proposal_invariants(_proposal(_DEFENSIVE_TX))
    assert not any(v.rule_id == "INV010" for v in violations), (
        f"INV010 false-positive on defensive code: {[(v.rule_id, v.message) for v in violations]}"
    )


def test_orphan_terminator_trips_inv010():
    """A Commit/RollBack with no Start() is a real defect — INV010 must fire."""
    violations = check_proposal_invariants(_proposal(_ORPHAN_TX))
    assert any(v.rule_id == "INV010" for v in violations)


@pytest.mark.parametrize("rule_id, build_proposal", [
    ("INV001", lambda: _proposal(_GOOD_CODE.replace("__result__", "var result"))),
    ("INV002", lambda: _proposal(_NESTED_TX)),
    ("INV003", lambda: _proposal(_GOOD_CODE.replace("doc.Regenerate();", "TaskDialog.Show(\"hi\", \"x\");"))),
    ("INV004", lambda: _proposal("using SneakyMalware;\n" + _GOOD_CODE)),
    ("INV005", lambda: _proposal(_GOOD_CODE).model_copy(update={"requires_assemblies": ["System"]})),
    ("INV006", lambda: _proposal(_GOOD_CODE + "\n".join(f"// line {i}" for i in range(400)))),
    # INV007 fires on filesystem paths inside string literals — the realistic
    # dangerous-path scenario (e.g. File.WriteAllText(@"C:\evil\backdoor.dll", ...)).
    # The comment-strip pass preserves string contents so this signal survives.
    ("INV007", lambda: _proposal(_GOOD_CODE.replace("doc.Regenerate();", "var p = @\"C:\\Temp\\evil.dll\";"))),
    ("INV008", lambda: _proposal(_UNGUARDED_GET_ELEMENT)),
    ("INV009", lambda: _proposal(_GOOD_CODE.replace("UnitTypeId.Millimeters", "UnitTypeId.Feet"))),
    ("INV010", lambda: _proposal(_UNBALANCED_TX)),
    ("INV011", lambda: _proposal(_GOOD_CODE.replace("doc.Regenerate();", "Thread.Sleep(1000);"))),
    ("INV012", lambda: _proposal(_GOOD_CODE, transaction_name="Wrong Name")),
])
def test_invariant_violation(rule_id, build_proposal):
    """Each rule INV001-INV012 must flag its specific failing pattern."""
    violations = check_proposal_invariants(build_proposal())
    assert any(v.rule_id == rule_id for v in violations), (
        f"expected {rule_id} in violations, got {[v.rule_id for v in violations]}"
    )


@pytest.mark.asyncio
async def test_compile_gate_short_circuits_on_invariant_violation():
    """End-to-end: a proposal missing __result__ should fail at L3 without hitting Roslyn."""
    from kukai.modeling.bridge.mocks import MockCompileClient
    from kukai.modeling.execution.gates import CompileGate
    from kukai.modeling.schemas.execution import ExecutionTask
    from kukai.modeling.schemas.tasks import ExpectedElementsSpec

    bad_code = "var x = 1;"  # missing __result__, missing Transaction
    proposal = _proposal(bad_code)
    task = ExecutionTask(
        task_id="t1task01",
        csharp_code=bad_code,
        expected_elements=ExpectedElementsSpec(category="OST_StructuralColumns", count=1),
        revit_version="2026",
        transaction_name="Place column",
        max_compile_attempts=1,
        max_execute_attempts=1,
    )
    mock = MockCompileClient()
    gate = CompileGate(mock)
    outcome, result = await gate.run(task, proposal=proposal)
    assert outcome.passed is False
    assert "invariant_violation: INV001" in (outcome.error or "")
    assert mock.calls == [], "Roslyn must NOT be invoked when invariants block"


def test_strip_comments_does_not_false_positive_inv011_on_comment():
    """A comment mentioning 'async' should not fire INV011."""
    code = _GOOD_CODE.replace("doc.Regenerate();", "// don't use async here\n  doc.Regenerate();")
    violations = check_proposal_invariants(_proposal(code))
    rule_ids = [v.rule_id for v in violations]
    assert "INV011" not in rule_ids, f"INV011 false-positive on comment: {rule_ids}"


def test_inv007_does_not_false_positive_on_url_in_comment():
    """A comment containing a URL (matches path regex via 'http://') should not fire INV007."""
    code = _GOOD_CODE.replace(
        "doc.Regenerate();",
        "// see https://docs.autodesk.com/revit/2026/api/\n  doc.Regenerate();",
    )
    violations = check_proposal_invariants(_proposal(code))
    rule_ids = [v.rule_id for v in violations]
    assert "INV007" not in rule_ids, f"INV007 false-positive on URL in comment: {rule_ids}"


def test_inv007_fires_on_path_inside_verbatim_string():
    """The whole point of INV007: a verbatim string containing a real path MUST fire."""
    code = _GOOD_CODE.replace(
        "doc.Regenerate();",
        'var p = @"C:\\Temp\\evil.dll";\n  doc.Regenerate();',
    )
    violations = check_proposal_invariants(_proposal(code))
    rule_ids = [v.rule_id for v in violations]
    assert "INV007" in rule_ids, f"INV007 should fire on in-string path, got: {rule_ids}"


def test_inv012_still_works_after_string_stripping():
    """INV012 must still detect transaction_name mismatch (works against raw_code)."""
    violations = check_proposal_invariants(_proposal(_GOOD_CODE, transaction_name="Wrong Name"))
    assert any(v.rule_id == "INV012" for v in violations)
