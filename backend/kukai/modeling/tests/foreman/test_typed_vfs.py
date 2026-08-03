"""Phase 4 Task 1 — typed VerificationFunction evaluation & targeted replan."""
from __future__ import annotations
import pytest

from kukai.modeling.foreman.replan import (
    VFViolation, evaluate_verification_function, replan_single_task,
)
from kukai.modeling.schemas.foreman import PlanTask, VerificationFunction
from kukai.modeling.schemas.identifiers import XYZ, deterministic_task_uuid
from kukai.modeling.schemas.llm import (
    CodeProposal, DeclaredOutputs, DryRunSummary, FailureCategory,
    FailureCheckResult, InlineRagCitation,
)
from kukai.modeling.schemas.resolver import (
    FamilyHint, GridIntersectionSpec, ResolverIntent,
)
from kukai.modeling.schemas.tasks import ExpectedElementsSpec, Phase, Tier, TaskBrief


def _intent() -> ResolverIntent:
    return ResolverIntent(
        element_type="structural_column",
        family_hint=FamilyHint(category="OST_StructuralColumns"),
        grid_intersection=GridIntersectionSpec(grid_x_name="A", grid_y_name="1", level_name="L1"),
        revit_version="2026",
    )


def _plan_task(vf=None) -> PlanTask:
    return PlanTask(
        plan_task_id="ptask-1", intent=_intent(),
        expected_elements=ExpectedElementsSpec(category="OST_StructuralColumns", count=1),
        tier=Tier.TIER_2, skill_path="modeling/structure/columns",
        verification_function=vf,
    )


def _declared(**kw) -> DeclaredOutputs:
    return DeclaredOutputs(
        expected_element_count=kw.get("count", 1),
        expected_category=kw.get("category", "OST_StructuralColumns"),
        expected_parameter_values=kw.get("params", {}) or {},
        expected_level_name=kw.get("level_name"),
        expected_family_name=kw.get("family_name"),
    )


def _do_eval(vf=None, *, declared=None, actual_count=1, actual_category="OST_StructuralColumns",
             actual_parameters=None, actual_level_name="L1", actual_family_name=None):
    """Returns the .violations list for back-compat with existing tests.

    Fix B+C: evaluate_verification_function now returns VFEvaluation
    (violations + skipped). Tests checking *violations only* use this shim;
    tests checking the new skipped behavior import VFEvaluation directly.
    """
    return evaluate_verification_function(
        plan_task=_plan_task(vf=vf),
        declared_outputs=declared or _declared(),
        actual_count=actual_count, actual_category=actual_category,
        actual_parameters=actual_parameters or {},
        actual_level_name=actual_level_name, actual_family_name=actual_family_name,
    ).violations


def test_no_vf_yields_no_violations():
    assert _do_eval(vf=None) == []


def test_count_mismatch_yields_violation():
    vf = VerificationFunction(description="single column",
                              must_hold_outputs=["expected_element_count"])
    out = _do_eval(vf, declared=_declared(count=1), actual_count=0)
    assert len(out) == 1 and out[0].field_name == "expected_element_count"
    assert out[0].declared == "1" and out[0].actual == "0"


def test_category_mismatch_yields_violation():
    vf = VerificationFunction(description="must be column",
                              must_hold_outputs=["expected_category"])
    out = _do_eval(vf, actual_category="OST_Walls")
    assert len(out) == 1 and out[0].field_name == "expected_category"


def test_parameter_value_mismatch_yields_violation():
    vf = VerificationFunction(description="width = 200",
                              must_hold_outputs=["expected_parameter_values"])
    out = _do_eval(vf, declared=_declared(params={"Width": "200"}),
                   actual_parameters={"Width": "300"})
    assert len(out) == 1 and "Width" in out[0].field_name


def test_level_name_mismatch_yields_violation():
    vf = VerificationFunction(description="on L1",
                              must_hold_outputs=["expected_level_name"])
    out = _do_eval(vf, declared=_declared(level_name="L1"), actual_level_name="L2")
    assert len(out) == 1 and out[0].field_name == "expected_level_name"


def test_python_assertion_pass():
    vf = VerificationFunction(
        description="custom",
        python_assertions=["actual_count == 1 and 'Width' in actual_parameters"],
        must_hold_outputs=["expected_element_count"],
    )
    assert _do_eval(vf, actual_parameters={"Width": "200"}) == []


def test_python_assertion_fail():
    vf = VerificationFunction(description="custom",
                              python_assertions=["actual_count > 5"],
                              must_hold_outputs=["expected_element_count"])
    out = _do_eval(vf)
    assert len(out) == 1 and out[0].field_name == "<python_assertion>"
    assert out[0].assertion_text == "actual_count > 5"


def test_python_assertion_unsafe_name_caught():
    """Wave 5 R2 — hostile expressions are now rejected at VF construction,
    not at evaluation time. This used to be caught as a runtime NameError;
    the AST whitelist promotes it to a construction-time ValueError so
    Foreman never gets a chance to evaluate it."""
    import pytest as _pytest
    from pydantic import ValidationError
    hostile_expr = "__import__('os')"
    with _pytest.raises(ValidationError):
        VerificationFunction(description="hostile",
                             python_assertions=[hostile_expr],
                             must_hold_outputs=["expected_element_count"])


def test_verification_function_rejects_unknown_field():
    """Audit N9: unknown must_hold_outputs is now a construction-time error,
    not a silent runtime <unknown field> violation. Catches typos early."""
    import pytest as _pytest
    from pydantic import ValidationError
    with _pytest.raises(ValidationError, match="unknown must_hold_outputs"):
        VerificationFunction(description="bad planner",
                             must_hold_outputs=["expected_squareness"])


# ---- Fix B: VF skips unobservable fields rather than false-positive replan ----


def test_vf_skips_unobservable_level_name():
    """Fix B: declared expected_level_name with actual=None (stub _collect_actuals)
    must SKIP, not violate. Otherwise every declared level/family/param triggers
    a false-positive replan and burns money."""
    vf = VerificationFunction(description="on L1",
                              must_hold_outputs=["expected_level_name"])
    evaluation = evaluate_verification_function(
        plan_task=_plan_task(vf=vf),
        declared_outputs=_declared(level_name="L1"),
        actual_count=1, actual_category="OST_StructuralColumns",
        actual_parameters={}, actual_level_name=None, actual_family_name=None,
    )
    assert evaluation.violations == []
    assert "expected_level_name" in evaluation.skipped


def test_vf_skips_unobservable_family_name():
    vf = VerificationFunction(description="ColF",
                              must_hold_outputs=["expected_family_name"])
    evaluation = evaluate_verification_function(
        plan_task=_plan_task(vf=vf),
        declared_outputs=_declared(family_name="ColF"),
        actual_count=1, actual_category="OST_StructuralColumns",
        actual_parameters={}, actual_level_name="L1", actual_family_name=None,
    )
    assert evaluation.violations == []
    assert "expected_family_name" in evaluation.skipped


def test_vf_skips_unobservable_parameter_values():
    vf = VerificationFunction(description="width=200",
                              must_hold_outputs=["expected_parameter_values"])
    evaluation = evaluate_verification_function(
        plan_task=_plan_task(vf=vf),
        declared_outputs=_declared(params={"Width": "200"}),
        actual_count=1, actual_category="OST_StructuralColumns",
        actual_parameters={}, actual_level_name="L1", actual_family_name=None,
    )
    assert evaluation.violations == []
    assert "expected_parameter_values" in evaluation.skipped


def test_vf_count_branch_still_fires_when_others_skipped():
    """Count actuals are always observable — must still violate. Only the
    unobservable fields skip."""
    vf = VerificationFunction(
        description="multi-field",
        must_hold_outputs=["expected_element_count", "expected_level_name"])
    evaluation = evaluate_verification_function(
        plan_task=_plan_task(vf=vf),
        declared_outputs=_declared(count=5, level_name="L1"),
        actual_count=3, actual_category="OST_StructuralColumns",
        actual_parameters={}, actual_level_name=None, actual_family_name=None,
    )
    assert len(evaluation.violations) == 1
    assert evaluation.violations[0].field_name == "expected_element_count"
    assert "expected_level_name" in evaluation.skipped


# ---- replan_single_task ----


def _full_checks():
    return {c: FailureCheckResult(checked=True, applicable=False) for c in FailureCategory}


def _brief() -> TaskBrief:
    return TaskBrief(
        task_id="t1task01", phase=Phase.STRUCTURE,
        skill_path="modeling/structure/columns", element_type="structural_column",
        placement_point=XYZ(x=0, y=0, z=0), family_symbol_id=10,
        parameter_map={}, level_id=1, revit_version="2026",
        expected_elements=ExpectedElementsSpec(category="OST_StructuralColumns", count=1),
        constraints=[], tier=Tier.TIER_2, estimated_cost_usd=0.0,
    )


@pytest.mark.asyncio
async def test_replan_single_task_invokes_regenerate():
    seen: list[tuple[TaskBrief, list[VFViolation]]] = []

    async def fake_regen(brief, viols):
        seen.append((brief, viols))
        return CodeProposal(
            task_id=brief.task_id, csharp_code="// replanned", explanation="r",
            expected_elements=brief.expected_elements, requires_assemblies=["RevitAPI"],
            transaction_name="Place column", revit_version=brief.revit_version,
            failure_mode_checks=_full_checks(),
            rag_citations=[InlineRagCitation(snippet_id="s", api_called="X")],
            dry_run=DryRunSummary(selected_symbol_id=10, proposed_xyz_mm=(0.0, 0.0, 0.0)),
            declared_outputs=DeclaredOutputs(
                expected_element_count=1,
                expected_category=brief.expected_elements.category,
            ),
        )

    violations = [VFViolation(plan_task_id="ptask-1", vf_description="x",
                              field_name="expected_element_count",
                              declared="1", actual="0")]
    proposal, verdict = await replan_single_task(
        plan_task=_plan_task(), brief=_brief(),
        violations=violations, regenerate=fake_regen,
    )
    assert len(seen) == 1
    assert "replanned" in proposal.csharp_code
    assert verdict.passed
    assert any(i.category == "vf_replan" for i in verdict.issues)


# ---- Foreman integration test ----


@pytest.mark.asyncio
async def test_foreman_dispatch_records_vf_violation_and_replans():
    from kukai.modeling.foreman.dispatcher import Foreman
    from kukai.modeling.subagent.structural import StructuralSubagent
    from kukai.modeling.resolver.dispatcher import Resolver
    from kukai.modeling.bridge.mocks import (
        MockBridgeClient, MockCompileClient, MockModelQueryClient,
    )
    from kukai.modeling.execution.gates import (
        CompileGate, CountValidationGate, ExecuteGate,
    )
    from kukai.modeling.execution.queue import ExecutionQueue
    from kukai.modeling.state.projections.project_state import ProjectState
    from kukai.modeling.llm.mocks import MockLLMClient
    from kukai.modeling.schemas.resolver import FamilySymbolCandidate

    expected_task_id = deterministic_task_uuid("proj-1", Phase.STRUCTURE.value, 1)
    base = {
        "task_id": expected_task_id,
        "csharp_code": (
            "// RAG:#s1\nusing(Transaction t = new Transaction(doc,\"Place column\"))"
            "{t.Start();t.Commit();}\n__result__ = new int[] { 1 };"
        ),
        "explanation": "x",
        "expected_elements": {"category": "OST_StructuralColumns", "count": 1},
        "requires_assemblies": ["RevitAPI"],
        "transaction_name": "Place column", "revit_version": "2026",
        "failure_mode_checks": {c.value: {"checked": True, "applicable": False, "note": None}
                                for c in FailureCategory},
        "rag_citations": [{"snippet_id": "s1", "api_called": "NewFamilyInstance"}],
        "dry_run": {"selected_symbol_id": 10, "proposed_xyz_mm": [0.0, 0.0, 0.0],
                    "params_to_set": {}},
        "questions_to_foreman": [],
    }
    wrong = {**base, "declared_outputs": {
        "expected_element_count": 2, "expected_category": "OST_StructuralColumns",
        "expected_parameter_values": {},
        "expected_level_name": None, "expected_family_name": None}}
    right = {**base, "declared_outputs": {
        "expected_element_count": 1, "expected_category": "OST_StructuralColumns",
        "expected_parameter_values": {},
        "expected_level_name": None, "expected_family_name": None}}

    mock_llm = MockLLMClient()
    mock_llm.queue_proposal(CodeProposal.model_validate(wrong))
    mock_llm.queue_proposal(CodeProposal.model_validate(right))
    sub = StructuralSubagent(mock_llm)
    from kukai.modeling.bridge.model_query_client import GridInfo
    query = MockModelQueryClient(
        families=[FamilySymbolCandidate(family_symbol_id=10, name="Col",
                                        family_name="ColF", category="OST_StructuralColumns")],
        grids=[
            GridInfo(grid_id=1, name="A", axis="horizontal", position_mm=0.0),
            GridInfo(grid_id=2, name="1", axis="vertical", position_mm=0.0),
        ])
    queue = ExecutionQueue(
        compile_gate=CompileGate(MockCompileClient()),
        execute_gate=ExecuteGate(MockBridgeClient(), session_id="mock"),
        count_gate=CountValidationGate(),
    )
    resolver = Resolver(query)

    class _SL:
        def load(self, p): return "skill"

    foreman = Foreman(
        project_id="proj-1", resolver=resolver, subagent=sub,
        execution_queue=queue, skill_loader=_SL(),
        rag_snippets=[("s1", "snip", "body")],
        project_state_provider=lambda: ProjectState(),
    )
    plan_task = PlanTask(
        plan_task_id="ptask-1", intent=_intent(),
        expected_elements=ExpectedElementsSpec(category="OST_StructuralColumns", count=1),
        tier=Tier.TIER_2, skill_path="modeling/structure/columns",
        verification_function=VerificationFunction(
            description="exactly one column",
            must_hold_outputs=["expected_element_count"]),
    )
    outcome = await foreman.dispatch_task(plan_task, phase=Phase.STRUCTURE, task_seq=1)
    assert outcome.executed and outcome.vf_replanned
    assert outcome.vf_violations[0].field_name == "expected_element_count"


# ---- Wave-2 fixes: Foreman-level VF skip/replan/re-eval integration tests ----


def _foreman_test_kit(*, proposals, plan_task, pro_subagent=None):
    """Build a fully-mocked Foreman + dispatch a single plan_task. Returns outcome.

    Reused by the Wave-2 integration tests below to avoid copy-pasting the
    same scaffolding 5 times.
    """
    from kukai.modeling.foreman.dispatcher import Foreman
    from kukai.modeling.subagent.structural import StructuralSubagent
    from kukai.modeling.resolver.dispatcher import Resolver
    from kukai.modeling.bridge.mocks import (
        MockBridgeClient, MockCompileClient, MockModelQueryClient,
    )
    from kukai.modeling.bridge.model_query_client import GridInfo
    from kukai.modeling.execution.gates import (
        CompileGate, CountValidationGate, ExecuteGate,
    )
    from kukai.modeling.execution.queue import ExecutionQueue
    from kukai.modeling.state.projections.project_state import ProjectState
    from kukai.modeling.llm.mocks import MockLLMClient
    from kukai.modeling.schemas.resolver import FamilySymbolCandidate

    mock_llm = MockLLMClient()
    for p in proposals:
        mock_llm.queue_proposal(p)
    sub = StructuralSubagent(mock_llm)
    query = MockModelQueryClient(
        families=[FamilySymbolCandidate(family_symbol_id=10, name="Col",
                                        family_name="ColF", category="OST_StructuralColumns")],
        grids=[GridInfo(grid_id=1, name="A", axis="horizontal", position_mm=0.0),
               GridInfo(grid_id=2, name="1", axis="vertical", position_mm=0.0)])
    queue = ExecutionQueue(
        compile_gate=CompileGate(MockCompileClient()),
        execute_gate=ExecuteGate(MockBridgeClient(), session_id="mock"),
        count_gate=CountValidationGate(),
    )
    resolver = Resolver(query)

    class _SL:
        def load(self, p): return "skill"

    from kukai.modeling.foreman.config import ForemanRouting
    foreman = Foreman(
        project_id="proj-1", resolver=resolver, subagent=sub,
        execution_queue=queue, skill_loader=_SL(),
        rag_snippets=[("s1", "snip", "body")],
        project_state_provider=lambda: ProjectState(),
        routing=ForemanRouting(pro_subagent=pro_subagent),
    )
    return foreman, plan_task


def _make_proposal(task_id: str, *, count: int, category: str = "OST_StructuralColumns",
                   level_name=None, family_name=None, params=None,
                   declared_outputs: object = "default"):
    """Build a CodeProposal dict ready for model_validate. If `declared_outputs`
    is the sentinel "default", it's populated from the kwargs; otherwise the
    explicit value (dict or None) is used."""
    base = {
        "task_id": task_id,
        "csharp_code": (
            "// RAG:#s1\nusing(Transaction t = new Transaction(doc,\"Place column\"))"
            "{t.Start();t.Commit();}\n__result__ = new int[] {" +
            ",".join(str(i) for i in range(1, count + 1)) + " };"
        ),
        "explanation": "x",
        "expected_elements": {"category": category, "count": count},
        "requires_assemblies": ["RevitAPI"],
        "transaction_name": "Place column", "revit_version": "2026",
        "failure_mode_checks": {c.value: {"checked": True, "applicable": False, "note": None}
                                for c in FailureCategory},
        "rag_citations": [{"snippet_id": "s1", "api_called": "NewFamilyInstance"}],
        "dry_run": {"selected_symbol_id": 10, "proposed_xyz_mm": [0.0, 0.0, 0.0],
                    "params_to_set": {}},
        "questions_to_foreman": [],
    }
    if declared_outputs == "default":
        base["declared_outputs"] = {
            "expected_element_count": count,
            "expected_category": category,
            "expected_parameter_values": params or {},
            "expected_level_name": level_name,
            "expected_family_name": family_name,
        }
    elif declared_outputs is None:
        # Fix G: omitting `declared_outputs` makes CodeProposal.declared_outputs
        # default to None (Optional[DeclaredOutputs]) — VF block short-circuits.
        pass
    else:
        base["declared_outputs"] = declared_outputs
    return CodeProposal.model_validate(base)


@pytest.mark.asyncio
async def test_vf_skips_unobservable_fields_at_dispatch():
    """Fix B: a proposal declaring expected_level_name='L1' (unobservable today)
    must NOT trigger a VF violation/replan. notes carry vf_check_skipped."""
    expected_task_id = deterministic_task_uuid("proj-1", Phase.STRUCTURE.value, 1)
    proposal = _make_proposal(expected_task_id, count=1, level_name="L1")
    plan_task = PlanTask(
        plan_task_id="ptask-1", intent=_intent(),
        expected_elements=ExpectedElementsSpec(category="OST_StructuralColumns", count=1),
        tier=Tier.TIER_2, skill_path="modeling/structure/columns",
        verification_function=VerificationFunction(
            description="on L1", must_hold_outputs=["expected_level_name"]),
    )
    foreman, pt = _foreman_test_kit(proposals=[proposal], plan_task=plan_task)
    outcome = await foreman.dispatch_task(pt, phase=Phase.STRUCTURE, task_seq=1)
    assert outcome.executed
    assert outcome.vf_replanned is False
    assert outcome.vf_violations == []
    assert "expected_level_name" in outcome.vf_check_skipped
    assert any("vf_check_skipped: expected_level_name" in n for n in outcome.notes)


@pytest.mark.asyncio
async def test_vf_count_branch_still_fires_at_dispatch():
    """Fix B: count VF still fires (count IS observable)."""
    expected_task_id = deterministic_task_uuid("proj-1", Phase.STRUCTURE.value, 1)
    # 1st proposal: declared count=5, actual count=1 — violates.
    # 2nd proposal: corrected.
    wrong = _make_proposal(expected_task_id, count=1, declared_outputs={
        "expected_element_count": 5, "expected_category": "OST_StructuralColumns",
        "expected_parameter_values": {}, "expected_level_name": None, "expected_family_name": None})
    right = _make_proposal(expected_task_id, count=1)
    plan_task = PlanTask(
        plan_task_id="ptask-1", intent=_intent(),
        expected_elements=ExpectedElementsSpec(category="OST_StructuralColumns", count=1),
        tier=Tier.TIER_2, skill_path="modeling/structure/columns",
        verification_function=VerificationFunction(
            description="count=5", must_hold_outputs=["expected_element_count"]),
    )
    foreman, pt = _foreman_test_kit(proposals=[wrong, right], plan_task=plan_task)
    outcome = await foreman.dispatch_task(pt, phase=Phase.STRUCTURE, task_seq=1)
    assert outcome.vf_replanned is True
    assert any(v.field_name == "expected_element_count" for v in outcome.vf_violations)


# ---- Fix F: PRO routing raises if pro_subagent is None ----


@pytest.mark.asyncio
async def test_pro_routing_without_pro_subagent_raises():
    """Fix F: cascade router selecting PRO with no pro_subagent must raise
    ValueError, not silently downgrade to Flash and lie in notes."""
    expected_task_id = deterministic_task_uuid("proj-1", Phase.STRUCTURE.value, 1)
    proposal = _make_proposal(expected_task_id, count=1)
    # TIER_3 with empty dims => router score=60 => PRO.
    pt = PlanTask(
        plan_task_id="ptask-pro", intent=ResolverIntent(
            element_type="structural_column",
            family_hint=FamilyHint(category="OST_StructuralColumns", dimensions_mm={}),
            grid_intersection=GridIntersectionSpec(grid_x_name="A", grid_y_name="1",
                                                    level_name="L1"),
            revit_version="2026",
        ),
        expected_elements=ExpectedElementsSpec(category="OST_StructuralColumns", count=1),
        tier=Tier.TIER_3, skill_path="modeling/structure/columns",
    )
    foreman, pt = _foreman_test_kit(proposals=[proposal], plan_task=pt,
                                     pro_subagent=None)
    with pytest.raises(ValueError, match="pro_subagent not configured"):
        await foreman.dispatch_task(pt, phase=Phase.STRUCTURE, task_seq=1)


@pytest.mark.asyncio
async def test_vf_reevaluated_after_replan_records_post_violations():
    """Fix C: replan must re-evaluate VF. If still violating, outcome.notes
    contains 'replan did not fix VF violations' and vf_violations_after_replan
    is populated. Original vf_violations preserved for audit trail.

    First proposal: declared=5, actual=1 (violation triggers replan).
    Second proposal (regenerator): also declared=5, actual=1 (still violating).
    """
    expected_task_id = deterministic_task_uuid("proj-1", Phase.STRUCTURE.value, 1)
    bad_decl = {
        "expected_element_count": 5, "expected_category": "OST_StructuralColumns",
        "expected_parameter_values": {}, "expected_level_name": None, "expected_family_name": None}
    wrong1 = _make_proposal(expected_task_id, count=1, declared_outputs=bad_decl)
    wrong2 = _make_proposal(expected_task_id, count=1, declared_outputs=bad_decl)
    plan_task = PlanTask(
        plan_task_id="ptask-1", intent=_intent(),
        expected_elements=ExpectedElementsSpec(category="OST_StructuralColumns", count=1),
        tier=Tier.TIER_2, skill_path="modeling/structure/columns",
        verification_function=VerificationFunction(
            description="count=5", must_hold_outputs=["expected_element_count"]),
    )
    foreman, pt = _foreman_test_kit(proposals=[wrong1, wrong2], plan_task=plan_task)
    outcome = await foreman.dispatch_task(pt, phase=Phase.STRUCTURE, task_seq=1)
    assert outcome.vf_replanned is True
    assert len(outcome.vf_violations) == 1  # original audit-trail violation
    assert len(outcome.vf_violations_after_replan) == 1  # still violating
    assert outcome.vf_violations_after_replan[0].field_name == "expected_element_count"
    assert any("replan did not fix VF violations" in n for n in outcome.notes)


# ---- Fix G: Optional[DeclaredOutputs] tests ----


@pytest.mark.asyncio
async def test_proposal_without_declared_outputs_skips_vf():
    """Fix G: CodeProposal with declared_outputs=None bypasses VF entirely.
    The previous sentinel pattern (DeclaredOutputs.empty()) conflated 'not
    declared' with 'intentional empty result'."""
    expected_task_id = deterministic_task_uuid("proj-1", Phase.STRUCTURE.value, 1)
    proposal = _make_proposal(expected_task_id, count=1, declared_outputs=None)
    plan_task = PlanTask(
        plan_task_id="ptask-1", intent=_intent(),
        expected_elements=ExpectedElementsSpec(category="OST_StructuralColumns", count=1),
        tier=Tier.TIER_2, skill_path="modeling/structure/columns",
        verification_function=VerificationFunction(
            description="count=5", must_hold_outputs=["expected_element_count"]),
    )
    foreman, pt = _foreman_test_kit(proposals=[proposal], plan_task=plan_task)
    outcome = await foreman.dispatch_task(pt, phase=Phase.STRUCTURE, task_seq=1)
    assert outcome.executed
    assert outcome.vf_replanned is False
    assert outcome.vf_violations == []
    assert outcome.vf_check_skipped == []
    assert outcome.code_proposal is not None
    assert outcome.code_proposal.declared_outputs is None


def test_declared_outputs_explicit_zero_count_constructible():
    """Fix G: explicit count=0 is now a legitimate declaration (no longer a
    'sentinel'). expected_category must be non-empty."""
    d = DeclaredOutputs(expected_element_count=0, expected_category="OST_Walls")
    assert d.expected_element_count == 0
    assert d.expected_category == "OST_Walls"


@pytest.mark.asyncio
async def test_proposal_with_explicit_zero_count_runs_vf():
    """Fix G: declared count=0 + actual=0 = VF passes (no violation), but VF
    DID run (proves count=0 is no longer a 'skip VF' sentinel)."""
    expected_task_id = deterministic_task_uuid("proj-1", Phase.STRUCTURE.value, 1)
    # Build a custom proposal that says "I will create 0 elements" but
    # still validates (count=1 in expected_elements is required by mock
    # bridge — but we want declared=0 vs actual=0).
    # Use mock bridge to actually return 0 elements: scripted response.
    from kukai.modeling.foreman.dispatcher import Foreman
    from kukai.modeling.subagent.structural import StructuralSubagent
    from kukai.modeling.resolver.dispatcher import Resolver
    from kukai.modeling.bridge.mocks import (
        MockBridgeClient, MockCompileClient, MockModelQueryClient,
    )
    from kukai.modeling.bridge.model_query_client import GridInfo
    from kukai.modeling.execution.gates import (
        CompileGate, CountValidationGate, ExecuteGate,
    )
    from kukai.modeling.execution.queue import ExecutionQueue
    from kukai.modeling.state.projections.project_state import ProjectState
    from kukai.modeling.llm.mocks import MockLLMClient
    from kukai.modeling.schemas.resolver import FamilySymbolCandidate

    proposal = _make_proposal(expected_task_id, count=1,
        # declared count=0, actual will also be 0 (scripted bridge)
        declared_outputs={
            "expected_element_count": 0,
            "expected_category": "OST_StructuralColumns",
            "expected_parameter_values": {},
            "expected_level_name": None, "expected_family_name": None})
    # CountValidationGate fails on count mismatch, so we need expected_elements
    # in the brief to match actuals. Use a plan_task with count=0 and a
    # scripted bridge response of 0 elements.
    pt = PlanTask(
        plan_task_id="ptask-1", intent=_intent(),
        expected_elements=ExpectedElementsSpec(category="OST_StructuralColumns", count=0),
        tier=Tier.TIER_2, skill_path="modeling/structure/columns",
        verification_function=VerificationFunction(
            description="zero count", must_hold_outputs=["expected_element_count"]),
    )
    # Rebuild proposal to align expected_elements with plan_task (count=0).
    proposal = _make_proposal(expected_task_id, count=0,
        declared_outputs={
            "expected_element_count": 0,
            "expected_category": "OST_StructuralColumns",
            "expected_parameter_values": {},
            "expected_level_name": None, "expected_family_name": None})

    mock_llm = MockLLMClient()
    mock_llm.queue_proposal(proposal)
    sub = StructuralSubagent(mock_llm)
    query = MockModelQueryClient(
        families=[FamilySymbolCandidate(family_symbol_id=10, name="Col",
                                        family_name="ColF", category="OST_StructuralColumns")],
        grids=[GridInfo(grid_id=1, name="A", axis="horizontal", position_mm=0.0),
               GridInfo(grid_id=2, name="1", axis="vertical", position_mm=0.0)])
    # Scripted bridge: return 0 elements explicitly.
    bridge = MockBridgeClient(responses=[
        {"success": True, "element_ids": [], "duration_ms": 10, "error": None}])
    queue = ExecutionQueue(
        compile_gate=CompileGate(MockCompileClient()),
        execute_gate=ExecuteGate(bridge, session_id="mock"),
        count_gate=CountValidationGate(),
    )
    resolver = Resolver(query)

    class _SL:
        def load(self, p): return "skill"

    foreman = Foreman(
        project_id="proj-1", resolver=resolver, subagent=sub,
        execution_queue=queue, skill_loader=_SL(),
        rag_snippets=[("s1", "snip", "body")],
        project_state_provider=lambda: ProjectState(),
    )
    outcome = await foreman.dispatch_task(pt, phase=Phase.STRUCTURE, task_seq=1)
    assert outcome.executed
    assert outcome.vf_replanned is False
    assert outcome.vf_violations == []  # declared=0 matches actual=0, VF passes
