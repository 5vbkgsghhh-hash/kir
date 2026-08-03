"""Tests for the multi-verifier review (Phase 3 Task 3.2)."""
from __future__ import annotations
import pytest

from kukai.modeling.bridge.mock_revit_session import MockRevitSession
from kukai.modeling.bridge.mocks import MockModelQueryClient
from kukai.modeling.foreman.toolbox import ForemanToolBox
from kukai.modeling.foreman.verifiers.correctness import check_correctness
from kukai.modeling.foreman.verifiers.geometry import check_geometry
from kukai.modeling.foreman.verifiers.safety import check_safety
from kukai.modeling.foreman.reviewer import review_proposal_multi
from kukai.modeling.schemas.foreman import ReviewSeverity
from kukai.modeling.schemas.identifiers import XYZ
from kukai.modeling.schemas.llm import (
    CodeProposal, DryRunSummary, FailureCategory, FailureCheckResult, InlineRagCitation,
)
from kukai.modeling.schemas.resolver import FamilySymbolCandidate
from kukai.modeling.schemas.tasks import (
    ExpectedElementsSpec, ParameterRef, Phase, TaskBrief, Tier,
)
from kukai.modeling.state.projections.project_state import ProjectState


def _brief(task_id: str = "t1task01") -> TaskBrief:
    return TaskBrief(
        task_id=task_id, phase=Phase.STRUCTURE,
        skill_path="modeling/structure/columns/concrete-columns.md",
        element_type="structural_column",
        placement_point=XYZ(x=0, y=0, z=0),
        family_symbol_id=10,
        parameter_map={"width": ParameterRef(name="b", scope="instance")},
        level_id=20, revit_version="2026",
        expected_elements=ExpectedElementsSpec(category="OST_StructuralColumns", count=1),
        tier=Tier.TIER_2, estimated_cost_usd=0.05,
    )


def _full_failure_checks() -> dict[FailureCategory, FailureCheckResult]:
    return {c: FailureCheckResult(checked=True, applicable=False) for c in FailureCategory}


_GOOD_CODE = (
    '// RAG:#snip_a\n'
    'using (var tx = new Transaction(doc, "Place column"))\n'
    '{\n  try { tx.Start();\n'
    '    doc.Create.NewFamilyInstance(\n'
    '      new XYZ(0.0, 0.0, 0.0),\n'
    '      doc.GetElement(new ElementId(10)) as FamilySymbol,\n'
    '      doc.GetElement(new ElementId(20)) as Level,\n'
    '      StructuralType.Column);\n'
    '    tx.Commit();\n'
    '  } catch { tx.RollBack(); throw; }\n}\n'
)


def _good_proposal(**overrides) -> CodeProposal:
    base = dict(
        task_id="t1task01", csharp_code=_GOOD_CODE,
        explanation="places a column",
        expected_elements=ExpectedElementsSpec(category="OST_StructuralColumns", count=1),
        requires_assemblies=["RevitAPI"],
        transaction_name="Place column", revit_version="2026",
        failure_mode_checks=_full_failure_checks(),
        rag_citations=[InlineRagCitation(
            snippet_id="snip_a", api_called="Document.Create.NewFamilyInstance")],
        dry_run=DryRunSummary(selected_symbol_id=10, proposed_xyz_mm=(0.0, 0.0, 0.0)),
    )
    base.update(overrides)
    return CodeProposal(**base)


# ---- check_correctness ----

@pytest.mark.tier0
def test_correctness_passes_when_consistent():
    assert check_correctness(_good_proposal(), _brief()) == []


@pytest.mark.tier0
def test_correctness_blocks_task_id_mismatch():
    issues = check_correctness(_good_proposal(task_id="WRONG_ID_LONG_ENOUGH"), _brief())
    assert any(i.category == "task_id_mismatch"
               and i.severity == ReviewSeverity.BLOCKING for i in issues)


@pytest.mark.tier0
def test_correctness_blocks_count_mismatch():
    bad = ExpectedElementsSpec(category="OST_StructuralColumns", count=5)
    issues = check_correctness(_good_proposal(expected_elements=bad), _brief())
    assert any(i.category == "expected_count_mismatch" for i in issues)


# ---- Wave 6C Fix A#5: questions_to_foreman is INFO, not BLOCKING ----

@pytest.mark.tier0
def test_questions_to_foreman_is_info_not_blocking():
    """A proposal with non-empty questions_to_foreman should produce an
    INFO-severity issue, not a blocking one. Persona teaches LLM that
    questions are how to escalate ambiguity — blocking the use of the
    documented mechanism is incoherent (Wave 6C — Fix A#5)."""
    proposal = _good_proposal(
        questions_to_foreman=["What's the level naming convention?"])
    issues = check_correctness(proposal, _brief())
    q_issues = [i for i in issues if i.category == "questions_to_foreman"]
    assert len(q_issues) == 1
    assert q_issues[0].severity == ReviewSeverity.INFO
    assert q_issues[0].severity != ReviewSeverity.BLOCKING
    assert q_issues[0].verifier_source == "correctness"


@pytest.mark.tier0
@pytest.mark.asyncio
async def test_review_multi_passes_when_only_info_issues_present():
    """Multi-verifier aggregator must treat INFO as non-blocking — the
    aggregate verdict.passed should be True with only a question-INFO."""
    from kukai.modeling.foreman.reviewer import review_proposal_multi
    proposal = _good_proposal(questions_to_foreman=["clarify column rebar"])
    tb = _toolbox_with_grids()
    verdict = await review_proposal_multi(proposal, _brief(), tb)
    assert verdict.passed is True
    assert any(i.category == "questions_to_foreman"
               and i.severity == ReviewSeverity.INFO for i in verdict.issues)


# ---- check_geometry ----

def _toolbox_with_grids() -> ForemanToolBox:
    return ForemanToolBox(
        query_client=MockModelQueryClient(),
        project_state_provider=lambda: ProjectState.initial(project_id="p1"),
        recent_events_provider=lambda limit=50: [],
    )


@pytest.mark.tier0
@pytest.mark.asyncio
async def test_geometry_passes_when_point_inside_bounds():
    # Default MockModelQueryClient grids: pos 0 on each axis. (0,0,0) is in-bounds.
    issues = await check_geometry(_good_proposal(), _brief(), _toolbox_with_grids())
    assert [i for i in issues if i.severity == ReviewSeverity.BLOCKING] == []


def _placement_code(*, x, y, z=0.0, sym=10, lvl=20, tx_name="X") -> str:
    """Minimal NewFamilyInstance code block — used in geometry tests."""
    return (
        f'using (var tx = new Transaction(doc, "{tx_name}"))\n'
        f'{{\n  tx.Start();\n'
        f'  doc.Create.NewFamilyInstance(\n'
        f'    new XYZ({x}, {y}, {z}),\n'
        f'    doc.GetElement(new ElementId({sym})) as FamilySymbol,\n'
        f'    doc.GetElement(new ElementId({lvl})) as Level,\n'
        f'    StructuralType.Column);\n'
        f'  tx.Commit();\n}}\n'
    )


@pytest.mark.tier0
@pytest.mark.asyncio
async def test_geometry_blocks_when_point_outside_bounds():
    code = _placement_code(x=99999.0, y=99999.0)
    issues = await check_geometry(
        _good_proposal(csharp_code=code), _brief(), _toolbox_with_grids())
    assert any(
        i.category == "geometry_out_of_grid_bounds"
        and i.severity == ReviewSeverity.BLOCKING for i in issues)


@pytest.mark.tier0
@pytest.mark.asyncio
async def test_geometry_collision_detected_when_session_has_overlap():
    # Seed a session with one column at (0,0,0); then ask the verifier about
    # _good_proposal which also places at (0,0,0).
    fam = FamilySymbolCandidate(
        family_symbol_id=10, name="C", family_name="C",
        category="OST_StructuralColumns")
    session = MockRevitSession(families=[fam])
    session.execute_code(_placement_code(x=0.0, y=0.0, sym=10, lvl=1, tx_name="Seed"))
    issues = await check_geometry(
        _good_proposal(), _brief(), _toolbox_with_grids(), session)
    assert any(
        i.category == "placement_collision"
        and i.severity == ReviewSeverity.BLOCKING for i in issues)


# ---- check_safety ----

@pytest.mark.tier0
def test_safety_passes_on_well_formed_transaction():
    # _good_proposal has try/catch + RollBack already
    issues = check_safety(_good_proposal())
    assert not any(i.severity == ReviewSeverity.BLOCKING for i in issues)
    assert "missing_transaction_rollback" not in {i.category for i in issues}
    # Audit T7 — pin: every issue check_safety ever emits must be WARNING.
    # Safety findings are non-blocking by design (advisory rollback patterns).
    assert all(i.severity == ReviewSeverity.WARNING for i in issues), (
        f"check_safety emitted a non-WARNING severity: "
        f"{[(i.category, i.severity) for i in issues]}"
    )


@pytest.mark.tier0
def test_safety_warns_on_commit_without_rollback():
    # Bare commit, no try/catch — relies on _placement_code from earlier test block.
    issues = check_safety(_good_proposal(csharp_code=_placement_code(x=0.0, y=0.0)))
    assert any(i.category == "missing_transaction_rollback" for i in issues)
    # Audit T7 — pin: this finding is WARNING, never BLOCKING.
    assert all(i.severity == ReviewSeverity.WARNING for i in issues), (
        f"check_safety emitted a non-WARNING severity: "
        f"{[(i.category, i.severity) for i in issues]}"
    )


@pytest.mark.tier0
def test_safety_warns_on_post_commit_lookup_parameter():
    # LookupParameter call placed AFTER tx.Commit() — stale element reference.
    code = (
        'using (var tx = new Transaction(doc, "Stale"))\n'
        '{\n  try {\n    tx.Start();\n'
        '    var col = doc.Create.NewFamilyInstance(\n'
        '      new XYZ(0.0, 0.0, 0.0),\n'
        '      doc.GetElement(new ElementId(10)) as FamilySymbol,\n'
        '      doc.GetElement(new ElementId(20)) as Level,\n'
        '      StructuralType.Column);\n'
        '    tx.Commit();\n'
        '    col.LookupParameter("Mark").Set("X");\n'
        '  } catch { tx.RollBack(); throw; }\n}\n'
    )
    issues = check_safety(_good_proposal(csharp_code=code))
    assert any(i.category == "post_commit_parameter_access" for i in issues)
    # Audit T7 — pin: post-commit access is WARNING, never BLOCKING.
    assert all(i.severity == ReviewSeverity.WARNING for i in issues), (
        f"check_safety emitted a non-WARNING severity: "
        f"{[(i.category, i.severity) for i in issues]}"
    )


# ---- review_proposal_multi aggregator ----

@pytest.mark.tier0
@pytest.mark.asyncio
async def test_aggregator_passes_when_all_verifiers_clean():
    verdict = await review_proposal_multi(_good_proposal(), _brief(), _toolbox_with_grids())
    assert verdict.passed is True
    assert all(i.severity != ReviewSeverity.BLOCKING for i in verdict.issues)


@pytest.mark.tier0
@pytest.mark.asyncio
async def test_aggregator_blocks_on_any_blocking_issue():
    verdict = await review_proposal_multi(
        _good_proposal(task_id="WRONG_ID_LONG_ENOUGH"), _brief(), _toolbox_with_grids(),
    )
    assert verdict.passed is False
    assert any(i.severity == ReviewSeverity.BLOCKING for i in verdict.issues)


@pytest.mark.tier0
@pytest.mark.asyncio
async def test_aggregator_includes_warnings_without_blocking():
    # Code missing try/catch — safety warns but doesn't block (RAG comment preserved).
    code = "// RAG:#snip_a\n" + _placement_code(x=0.0, y=0.0)
    verdict = await review_proposal_multi(
        _good_proposal(csharp_code=code), _brief(), _toolbox_with_grids())
    assert verdict.passed is True  # warnings don't block
    cats = {i.category for i in verdict.issues}
    assert "missing_transaction_rollback" in cats


# ---- Foreman.dispatch_task integration ----

def _build_dispatch_fixtures():
    """Returns (queue, plan_task, resolver, subagent, loader)."""
    from kukai.modeling.execution.gates import (
        CompileGate, CountValidationGate, ExecuteGate)
    from kukai.modeling.execution.queue import ExecutionQueue
    from kukai.modeling.bridge.mocks import MockBridgeClient, MockCompileClient
    from kukai.modeling.schemas.foreman import PlanTask
    from kukai.modeling.schemas.resolver import (
        FamilyHint, FamilyResolutionStatus, GridIntersectionSpec,
        ResolverIntent, ResolverOutput)

    queue = ExecutionQueue(
        compile_gate=CompileGate(MockCompileClient()),
        execute_gate=ExecuteGate(MockBridgeClient(), session_id="mock_session"),
        count_gate=CountValidationGate())
    intent = ResolverIntent(
        element_type="structural_column",
        family_hint=FamilyHint(category="OST_StructuralColumns"),
        grid_intersection=GridIntersectionSpec(
            grid_x_name="A", grid_y_name="1", level_name="L1"),
        revit_version="2026")
    plan_task = PlanTask(
        plan_task_id="pt1", intent=intent,
        expected_elements=ExpectedElementsSpec(category="OST_StructuralColumns", count=1),
        tier=Tier.TIER_2,
        skill_path="modeling/structure/columns/concrete-columns.md")

    class _Resolver:
        async def resolve(self, _intent):
            return ResolverOutput(
                family_resolution=FamilyResolutionStatus.RESOLVED,
                family_symbol_id=10, placement_point=XYZ(x=0, y=0, z=0),
                level_id=20, revit_version="2026")
    class _Subagent:
        async def generate_code(self, *, task_brief, skill_content, rag_snippets,
                                repair_context=None):
            return _good_proposal(task_id=task_brief.task_id)
    class _Loader:
        def load(self, p): return ""
    return queue, plan_task, _Resolver(), _Subagent(), _Loader()


def _make_foreman(queue, resolver, subagent, loader, *, toolbox=None):
    from kukai.modeling.foreman.dispatcher import Foreman
    from kukai.modeling.foreman.config import ForemanVerifiers
    verifiers = ForemanVerifiers(toolbox=toolbox) if toolbox is not None else None
    return Foreman(
        project_id="p1", resolver=resolver, subagent=subagent,
        execution_queue=queue, skill_loader=loader,
        rag_snippets=[("snip_a", "t", "b")],
        project_state_provider=lambda: ProjectState.initial(project_id="p1"),
        verifiers=verifiers,
    )


@pytest.mark.tier0
def test_foreman_init_accepts_toolbox_and_session():
    """Foreman.__init__ accepts the new optional kwargs."""
    from kukai.modeling.foreman.dispatcher import Foreman
    from kukai.modeling.foreman.config import ForemanVerifiers
    queue, _, resolver, subagent, loader = _build_dispatch_fixtures()
    tb, session = _toolbox_with_grids(), MockRevitSession()
    f = Foreman(
        project_id="p1", resolver=resolver, subagent=subagent,
        execution_queue=queue, skill_loader=loader, rag_snippets=[],
        project_state_provider=lambda: ProjectState.initial(project_id="p1"),
        verifiers=ForemanVerifiers(toolbox=tb, mock_revit_session=session))
    assert f._toolbox is tb and f._mock_revit_session is session


@pytest.mark.tier0
@pytest.mark.asyncio
async def test_dispatch_task_uses_multi_verifier_when_toolbox_present(monkeypatch):
    """When toolbox is supplied, review_proposal_multi is invoked."""
    import kukai.modeling.foreman.dispatcher as dispatcher_mod

    called: list[str] = []
    original = dispatcher_mod.review_proposal_multi
    async def _spy(*a, **kw):
        called.append("multi")
        return await original(*a, **kw)
    monkeypatch.setattr(dispatcher_mod, "review_proposal_multi", _spy)

    queue, plan_task, resolver, subagent, loader = _build_dispatch_fixtures()
    f = _make_foreman(queue, resolver, subagent, loader,
                      toolbox=_toolbox_with_grids())
    outcome = await f.dispatch_task(plan_task, phase=Phase.STRUCTURE, task_seq=1)
    assert called == ["multi"]
    assert outcome.review_verdict.passed is True


@pytest.mark.tier0
@pytest.mark.asyncio
async def test_dispatch_task_falls_back_to_legacy_when_no_toolbox(monkeypatch):
    """When no toolbox is supplied, legacy review_proposal is used."""
    import kukai.modeling.foreman.dispatcher as dispatcher_mod

    called: list[str] = []
    original = dispatcher_mod.review_proposal
    def _spy(*a, **kw):
        called.append("legacy")
        return original(*a, **kw)
    monkeypatch.setattr(dispatcher_mod, "review_proposal", _spy)

    queue, plan_task, resolver, subagent, loader = _build_dispatch_fixtures()
    f = _make_foreman(queue, resolver, subagent, loader)  # no toolbox
    outcome = await f.dispatch_task(plan_task, phase=Phase.STRUCTURE, task_seq=1)
    assert called == ["legacy"]
    assert outcome.review_verdict.passed is True


# ---- Wave 5 R3 — verifier_source telemetry ----

@pytest.mark.tier0
@pytest.mark.asyncio
async def test_review_issue_carries_verifier_source():
    """Wave 5 R3 — every issue emitted by check_correctness / check_geometry /
    check_safety must record its source so review_proposal_multi can do per-
    verifier disable + telemetry attribution downstream."""
    # correctness — task_id mismatch is BLOCKING from correctness.
    correctness_issues = check_correctness(
        _good_proposal(task_id="WRONG_TASK_ID_HERE"), _brief())
    assert correctness_issues, "fixture must produce at least one correctness issue"
    assert all(i.verifier_source == "correctness" for i in correctness_issues), (
        f"correctness verifier source missing: "
        f"{[(i.category, i.verifier_source) for i in correctness_issues]}"
    )

    # geometry — out-of-bounds is BLOCKING from geometry.
    code_oob = _placement_code(x=99999.0, y=99999.0)
    geometry_issues = await check_geometry(
        _good_proposal(csharp_code=code_oob), _brief(), _toolbox_with_grids())
    assert geometry_issues, "fixture must produce at least one geometry issue"
    assert all(i.verifier_source == "geometry" for i in geometry_issues), (
        f"geometry verifier source missing: "
        f"{[(i.category, i.verifier_source) for i in geometry_issues]}"
    )

    # safety — commit without try/catch is WARNING from safety.
    code_bare_commit = "// RAG:#snip_a\n" + _placement_code(x=0.0, y=0.0)
    safety_issues = check_safety(_good_proposal(csharp_code=code_bare_commit))
    assert safety_issues, "fixture must produce at least one safety issue"
    assert all(i.verifier_source == "safety" for i in safety_issues), (
        f"safety verifier source missing: "
        f"{[(i.category, i.verifier_source) for i in safety_issues]}"
    )


@pytest.mark.tier0
def test_review_issue_verifier_source_optional_for_back_compat():
    """Wave 5 R3 — `verifier_source` defaults to None so legacy code paths
    that build ReviewIssue directly (e.g. Foreman.dispatch_task's resolver-
    failed / repair-loop-gave-up cases) keep constructing valid objects."""
    from kukai.modeling.schemas.foreman import ReviewIssue, ReviewSeverity
    issue = ReviewIssue(
        severity=ReviewSeverity.BLOCKING,
        category="family_not_resolved",
        detail="family resolution did not converge",
    )
    assert issue.verifier_source is None
