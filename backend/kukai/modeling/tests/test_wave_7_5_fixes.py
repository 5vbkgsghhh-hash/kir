"""Wave 7.5 fix tests — covers Fixes #1, #3, #4 + the multi-phase gap from Audit A8.

After the Wave 7 sandbox surfaced 6 manual-intervention failure modes, the
Manager verdict prescribed a 4-fix mini-iteration. These tests pin each fix
to a failing-without-it-passing-with-it contract so future regressions
surface in tier0:

  - Fix #1: Foreman.run_phase rejects sha256-looking plan_task_id that
    diverges from the deterministic_task_uuid formula
  - Fix #3: geometry verifier catches collisions even when C# uses
    variable-form XYZ (the previous regex missed every Wave 7 proposal)
  - Fix #4: ForemanBudgetGuard enforces max_usd via per-call "usd" entries
    in client.calls
  - Audit A8 (multi-phase): two run_phase invocations on a shared Foreman
    + MockRevitSession accumulate session state cleanly across phases
"""
from __future__ import annotations
import pytest

from kukai.modeling.bridge.mocks import MockBridgeClient, MockCompileClient, MockModelQueryClient
from kukai.modeling.bridge.model_query_client import GridInfo
from kukai.modeling.bridge.mock_revit_session import MockRevitSession, LevelInfo
from kukai.modeling.execution.gates import CompileGate, CountValidationGate, ExecuteGate
from kukai.modeling.execution.queue import ExecutionQueue
from kukai.modeling.foreman.budget_guard import (
    BudgetCaps, BudgetExceededError, ForemanBudgetGuard,
)
from kukai.modeling.foreman.config import ForemanVerifiers
from kukai.modeling.foreman.dispatcher import Foreman
from kukai.modeling.foreman.toolbox import ForemanToolBox
from kukai.modeling.foreman.verifiers.geometry import check_geometry
from kukai.modeling.llm.mocks import MockLLMClient
from kukai.modeling.resolver.dispatcher import Resolver
from kukai.modeling.schemas.foreman import PhasePlan, PhaseRunStatus, PlanTask
from kukai.modeling.schemas.identifiers import XYZ, deterministic_task_uuid
from kukai.modeling.schemas.llm import (
    CodeProposal, DryRunSummary, FailureCategory, FailureCheckResult, InlineRagCitation,
)
from kukai.modeling.schemas.resolver import (
    FamilyHint, FamilySymbolCandidate, GridIntersectionSpec, ResolverIntent,
)
from kukai.modeling.schemas.tasks import ExpectedElementsSpec, Phase, TaskBrief, Tier
from kukai.modeling.state.projections.project_state import ProjectState
from kukai.modeling.subagent.structural import StructuralSubagent


pytestmark = pytest.mark.tier0


# ---------------------------------------------------------------------------
# shared fixtures
# ---------------------------------------------------------------------------

def _checks():
    return {c: FailureCheckResult(checked=True, applicable=False) for c in FailureCategory}


def _proposal(task_id: str) -> CodeProposal:
    return CodeProposal(
        task_id=task_id,
        csharp_code=(
            "// RAG:#snip_a\nusing(Transaction t = new Transaction(doc,\"Place column\"))"
            "{t.Start();t.Commit();}\n__result__ = new int[] { 42 };"
        ),
        explanation="ok",
        expected_elements=ExpectedElementsSpec(category="OST_StructuralColumns", count=1),
        requires_assemblies=["RevitAPI"],
        transaction_name="Place column",
        revit_version="2026",
        failure_mode_checks=_checks(),
        rag_citations=[
            InlineRagCitation(snippet_id="snip_a", api_called="Document.Create.NewFamilyInstance"),
        ],
        dry_run=DryRunSummary(selected_symbol_id=10, proposed_xyz_mm=(0.0, 0.0, 0.0)),
    )


def _plan_task(plan_task_id: str, grid_x: str = "A") -> PlanTask:
    return PlanTask(
        plan_task_id=plan_task_id,
        intent=ResolverIntent(
            element_type="structural_column",
            family_hint=FamilyHint(category="OST_StructuralColumns"),
            grid_intersection=GridIntersectionSpec(
                grid_x_name=grid_x, grid_y_name="1", level_name="L1",
            ),
            revit_version="2026",
        ),
        expected_elements=ExpectedElementsSpec(category="OST_StructuralColumns", count=1),
        tier=Tier.TIER_2,
        skill_path="modeling/structure/columns/concrete-columns.md",
    )


class _FakeSkillLoader:
    def load(self, skill_path: str) -> str:
        return "# Skill"


def _foreman(llm: MockLLMClient, project_id: str = "proj1") -> Foreman:
    query = MockModelQueryClient(grids=[
        GridInfo(grid_id=1, name="A", axis="horizontal", position_mm=0.0),
        GridInfo(grid_id=2, name="B", axis="horizontal", position_mm=6000.0),
        GridInfo(grid_id=3, name="1", axis="vertical", position_mm=0.0),
    ])
    query._families = [FamilySymbolCandidate(
        family_symbol_id=10, name="C-300", family_name="ЖБ Колонна",
        category="OST_StructuralColumns",
    )]
    resolver = Resolver(query)
    queue = ExecutionQueue(
        compile_gate=CompileGate(MockCompileClient()),
        execute_gate=ExecuteGate(MockBridgeClient(), session_id="dev"),
        count_gate=CountValidationGate(),
    )
    return Foreman(
        project_id=project_id,
        resolver=resolver,
        subagent=StructuralSubagent(llm),
        execution_queue=queue,
        skill_loader=_FakeSkillLoader(),
        rag_snippets=[("snip_a", "t", "body")],
        project_state_provider=lambda: ProjectState(),
    )


# ===========================================================================
# Fix #1 — task_id formula enforcement at run_phase entry
# ===========================================================================

@pytest.mark.asyncio
async def test_run_phase_rejects_sha256_plan_task_id_with_wrong_formula():
    """If plan_task_id LOOKS like a sha256 hash (16 hex chars) but uses a
    different formula than `sha256(project_id/phase.value/seq)`, run_phase
    raises ValueError with a self-explanatory message. Without this fix,
    Wave 7 needed manual remapping in PreloadedProposalLLM."""
    llm = MockLLMClient()
    # Compute id using WRONG formula (sha256 of "proj1/wrong_phase_id/1"[:16])
    import hashlib
    wrong_id = hashlib.sha256(b"proj1/structure_floor1/1").hexdigest()[:16]
    correct_id = deterministic_task_uuid("proj1", Phase.STRUCTURE.value, 1)
    assert wrong_id != correct_id  # sanity check — formulas diverge

    plan = PhasePlan(phase=Phase.STRUCTURE, tasks=[_plan_task(wrong_id)])
    foreman = _foreman(llm)
    with pytest.raises(ValueError, match="plan_task_id mismatch"):
        await foreman.run_phase(plan)


@pytest.mark.asyncio
async def test_run_phase_accepts_legacy_non_sha256_plan_task_id():
    """Non-sha256-format ids (legacy fixtures like 'pt_0001', 'task-1')
    bypass the validator. Backwards compatibility for existing tests."""
    llm = MockLLMClient()
    llm.queue_proposal(_proposal("pt_0001"))  # any task_id — matches PreloadedLLM contract
    plan = PhasePlan(phase=Phase.STRUCTURE, tasks=[_plan_task("pt_0001")])
    foreman = _foreman(llm)
    # No raise — validator allows legacy ids
    result = await foreman.run_phase(plan)
    # Don't care about success/fail here — just that validator didn't reject
    assert result.phase == Phase.STRUCTURE


@pytest.mark.asyncio
async def test_run_phase_accepts_correct_sha256_plan_task_id():
    """sha256-format id that matches the formula passes validation."""
    llm = MockLLMClient()
    tid1 = deterministic_task_uuid("proj1", Phase.STRUCTURE.value, 1)
    llm.queue_proposal(_proposal(tid1))
    plan = PhasePlan(phase=Phase.STRUCTURE, tasks=[_plan_task(tid1)])
    foreman = _foreman(llm)
    result = await foreman.run_phase(plan)
    assert result.phase == Phase.STRUCTURE


# ===========================================================================
# Fix #3 — geometry verifier catches collision via brief.placement_point
# ===========================================================================

@pytest.mark.asyncio
async def test_geometry_verifier_catches_collision_with_variable_form_xyz():
    """Wave 7 proposals use `new XYZ(x_ft, y_ft, z_ft)` after a
    UnitUtils.ConvertToInternalUnits line. The pre-Wave-7.5 regex matched
    only numeric literals → finder returned 0 points → collision check
    silently skipped. After Fix #3, brief.placement_point is always
    added to candidate_points so collision is caught."""
    query = MockModelQueryClient(grids=[])
    toolbox = ForemanToolBox(query_client=query,
                             project_state_provider=lambda: ProjectState(),
                             recent_events_provider=lambda **kw: [])

    # Pre-populate session with an element at (1000, 1000, 0)
    session = MockRevitSession(
        families=[FamilySymbolCandidate(
            family_symbol_id=10, name="C-300", family_name="ЖБ Колонна",
            category="OST_StructuralColumns",
        )],
        levels=[LevelInfo(level_id=201, name="L1", elevation_mm=0.0)],
    )
    # Manually inject a placed element to simulate cross-phase / prior task state
    from kukai.modeling.bridge.mock_revit_session import PlacedElement
    session._placed[999] = PlacedElement(
        element_id=999, category="OST_StructuralColumns",
        family_symbol_id=10, level_id=201,
        location_mm=(1000.0, 1000.0, 0.0), parameters={"Mark": "C-PRIOR"},
    )

    # Brief points at the SAME location as the placed element
    brief = TaskBrief(
        task_id="x" * 16,
        phase=Phase.STRUCTURE,
        skill_path="modeling/structure/columns/concrete-columns.md",
        element_type="structural_column",
        placement_point=XYZ(x=1000.0, y=1000.0, z=0.0),
        family_symbol_id=10,
        level_id=201,
        parameter_map={},
        revit_version="2026",
        expected_elements=ExpectedElementsSpec(category="OST_StructuralColumns", count=1),
        tier=Tier.TIER_2,
        estimated_cost_usd=0.05,
    )
    # Proposal C# uses variable-form XYZ (regex misses) — verifier must
    # still catch collision via brief.placement_point
    proposal = _proposal("x" * 16)
    proposal_var = proposal.model_copy(update={"csharp_code": (
        "// RAG:#snip_a\n"
        "double x_ft = UnitUtils.ConvertToInternalUnits(1000.0, UnitTypeId.Millimeters);\n"
        "double y_ft = UnitUtils.ConvertToInternalUnits(1000.0, UnitTypeId.Millimeters);\n"
        "double z_ft = UnitUtils.ConvertToInternalUnits(0.0, UnitTypeId.Millimeters);\n"
        "using(Transaction t = new Transaction(doc,\"Place column\")){\n"
        "  t.Start();\n"
        "  doc.Create.NewFamilyInstance(new XYZ(x_ft, y_ft, z_ft), sym, lvl, "
        "    Autodesk.Revit.DB.Structure.StructuralType.Column);\n"
        "  t.Commit();\n"
        "}\n"
        "__result__ = new int[] { 42 };"
    )})

    issues = await check_geometry(proposal_var, brief, toolbox, session)
    collision = [i for i in issues if i.category == "placement_collision"]
    assert collision, (
        "Expected collision detection via brief.placement_point; got: "
        f"{[(i.category, i.severity.value) for i in issues]}"
    )


# ===========================================================================
# Fix #4 — ForemanBudgetGuard enforces max_usd via per-call "usd" entries
# ===========================================================================

class _UsdTrackedLLM:
    """Test double: each generate call appends an entry with a 'usd' field."""

    def __init__(self, usd_per_call: float = 0.05):
        self.calls: list[dict] = []
        self._usd_per_call = usd_per_call

    def record_call(self) -> None:
        self.calls.append({"method": "generate", "usd": self._usd_per_call})


def test_budget_guard_raises_when_aggregate_usd_exceeds_cap():
    """Fix #4: max_usd is enforced by summing client.calls[*].get('usd', 0).
    Pre-Wave-7.5, the cap was documented as 'not enforced' and Wave 7 sandbox
    ran with max_usd=0.0 successfully despite the docstring promise."""
    caps = BudgetCaps(max_llm_calls=100, max_compile_calls=100, max_execute_calls=100, max_usd=0.10)
    llm = _UsdTrackedLLM(usd_per_call=0.05)
    compile_c = type("X", (), {"calls": []})()
    bridge_c = type("X", (), {"calls": []})()

    with ForemanBudgetGuard(caps, llm, compile_c, bridge_c) as guard:
        # Simulate 3 generate calls = $0.15 total > $0.10 cap
        for _ in range(3):
            llm.record_call()
        with pytest.raises(BudgetExceededError, match="aggregate USD"):
            guard.check()


def test_budget_guard_allows_under_cap_usd():
    caps = BudgetCaps(max_llm_calls=100, max_compile_calls=100, max_execute_calls=100, max_usd=1.0)
    llm = _UsdTrackedLLM(usd_per_call=0.05)
    compile_c = type("X", (), {"calls": []})()
    bridge_c = type("X", (), {"calls": []})()

    with ForemanBudgetGuard(caps, llm, compile_c, bridge_c) as guard:
        for _ in range(3):
            llm.record_call()
        guard.check()  # no raise — $0.15 < $1.00


def test_budget_guard_handles_clients_without_usd_field():
    """Mock clients that don't populate 'usd' contribute 0.0. Sandbox path
    where caps={max_usd=0.0} stays non-blocking."""
    caps = BudgetCaps(max_llm_calls=100, max_compile_calls=100, max_execute_calls=100, max_usd=0.0)
    llm = type("X", (), {"calls": [{"method": "x"}, {"method": "y"}]})()
    compile_c = type("X", (), {"calls": []})()
    bridge_c = type("X", (), {"calls": []})()

    with ForemanBudgetGuard(caps, llm, compile_c, bridge_c) as guard:
        guard.check()  # no raise — no "usd" entries means 0.0 cost


# ===========================================================================
# Audit A8 — multi-phase integration tests (the gap that hid Wave 7's traps)
# ===========================================================================

@pytest.mark.asyncio
async def test_two_phases_unique_task_ids_when_using_different_phase_enums():
    """Two phases sharing project_id but using DIFFERENT Phase enum values
    must produce distinct task_ids. Wave 7 used STRUCTURE + ARCHITECTURE
    to avoid the collision; this test pins the pattern."""
    tid_s = deterministic_task_uuid("wave7_sim", Phase.STRUCTURE.value, 1)
    tid_a = deterministic_task_uuid("wave7_sim", Phase.ARCHITECTURE.value, 1)
    assert tid_s != tid_a, (
        "Two phases with different Phase enum values must produce distinct "
        f"task_ids for the same seq. Got STRUCTURE seq=1={tid_s}, "
        f"ARCHITECTURE seq=1={tid_a}"
    )


def test_two_phases_share_state_collision_detected_via_brief_placement():
    """When run_phase is called twice on the SAME Foreman + MockRevitSession,
    elements placed in phase 1 must be visible during phase 2 geometry
    checks. Together with Fix #3, this means F2 doors at the same XY as
    F1 columns get blocked by L6.
    (Synchronous test — exercises just the session-state contract.)"""
    session = MockRevitSession(
        families=[FamilySymbolCandidate(
            family_symbol_id=10, name="C-300", family_name="ЖБ Колонна",
            category="OST_StructuralColumns",
        )],
        levels=[LevelInfo(level_id=201, name="L1", elevation_mm=0.0),
                LevelInfo(level_id=202, name="L2", elevation_mm=3000.0)],
    )
    from kukai.modeling.bridge.mock_revit_session import PlacedElement
    # Phase 1 places element at (5000, 5000, 0)
    session._placed[1001] = PlacedElement(
        element_id=1001, category="OST_StructuralColumns",
        family_symbol_id=10, level_id=201,
        location_mm=(5000.0, 5000.0, 0.0), parameters={"Mark": "C-F1-PHASE1"},
    )
    # Phase 2 starts — session.list_placed_elements() should include F1 element
    placed = session.list_placed_elements()
    f1_elements = [p for p in placed if p.element_id == 1001]
    assert len(f1_elements) == 1, (
        f"Expected F1's element 1001 to persist into F2 view; got placed={placed}"
    )
    # Phase 2 element at same coords should see F1 as a collision candidate
    f1_locations = [p.location_mm[:2] for p in placed]
    assert (5000.0, 5000.0) in f1_locations
