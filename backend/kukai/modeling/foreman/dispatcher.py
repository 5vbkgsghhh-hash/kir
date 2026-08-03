"""Foreman — phase planner, dispatcher, reviewer, interpreter.

Per spec Section 5.2. This is a deterministic Python orchestrator, NOT an LLM.
The only LLM hop Foreman drives directly is StructuralSubagent.generate_code().

Public surface (this plan):
  - dispatch_task(plan_task, phase, task_seq) -> DispatchOutcome
  - run_phase(plan)                            -> PhaseRunResult   (Task 6)
  - interpret_result(execution_result)         -> InterpretedResult (Task 6)

Not yet implemented (deferred to later plans):
  - plan_phase(brief) -> PhasePlan (Foreman has no Building Brief schema yet;
    planning today is done by the caller passing a hand-built PhasePlan)
  - LLM-based review (Plan 9+)
  - Reflexion repair loop (Plan 10+)
"""
from __future__ import annotations
from typing import Callable, Protocol

from pydantic import BaseModel, ConfigDict, Field

from kukai.modeling.execution.queue import ExecutionQueue
from kukai.modeling.foreman.budget_guard import (
    BudgetCaps, ForemanBudgetGuard, BudgetExceededError,
)
from kukai.modeling.foreman.config import (
    ForemanRepair, ForemanRouting, ForemanSampling, ForemanVerifiers,
)
from kukai.modeling.foreman.repair_loop import repair_loop
from kukai.modeling.foreman.replan import (
    VFViolation, evaluate_verification_function, replan_single_task,
)
from kukai.modeling.foreman.reviewer import review_proposal, review_proposal_multi
from kukai.modeling.foreman.tier_selector import select_tier
from kukai.modeling.llm.router import ModelChoice
from kukai.modeling.resolver.dispatcher import Resolver
from kukai.modeling.schemas.execution import ExecutionResult, ExecutionTask
from kukai.modeling.schemas.foreman import (
    PhasePlan, PhaseRunResult, PhaseRunStatus,
    PlanTask, ReviewIssue, ReviewSeverity, ReviewVerdict,
)
from kukai.modeling.schemas.identifiers import deterministic_task_uuid
from kukai.modeling.schemas.llm import CodeProposal
from kukai.modeling.schemas.resolver import (
    FamilyResolutionStatus, ResolverOutput,
)
from kukai.modeling.schemas.tasks import (
    ParameterRef, Phase, TaskBrief,
)
from kukai.modeling.state.projections.project_state import ProjectState
from kukai.modeling.subagent.sampling import (
    SampledStructuralSubagent, _resolve_default_n)
from kukai.modeling.subagent.structural import StructuralSubagent
from kukai.modeling.execution.invariants import check_proposal_invariants


# ---- Public output types ----


class DispatchOutcome(BaseModel):
    """Result of dispatching a single PlanTask through resolve → subagent → review → execute."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    plan_task_id: str
    task_brief: TaskBrief
    resolver_output: ResolverOutput
    code_proposal: CodeProposal | None
    review_verdict: ReviewVerdict
    executed: bool
    execution_result: ExecutionResult | None
    notes: list[str] = Field(default_factory=list)
    vf_violations: list[VFViolation] = Field(default_factory=list)
    vf_replanned: bool = False
    vf_violations_after_replan: list[VFViolation] = Field(default_factory=list)
    vf_check_skipped: list[str] = Field(default_factory=list)


# ---- Skill loader protocol (kept narrow) ----


class SkillLoaderLike(Protocol):
    def load(self, skill_path: str) -> str: ...


# ---- The Foreman ----


class Foreman:
    """Deterministic orchestrator. Owns dispatch + review + execute call sequence."""

    def __init__(
        self,
        *,
        project_id: str,
        resolver: Resolver,
        subagent: StructuralSubagent,
        execution_queue: ExecutionQueue,
        skill_loader: SkillLoaderLike,
        rag_snippets: list[tuple[str, str, str]],
        project_state_provider: Callable[[], ProjectState],
        repair: ForemanRepair | None = None,
        verifiers: ForemanVerifiers | None = None,
        sampling: ForemanSampling | None = None,
        routing: ForemanRouting | None = None,
        replan_on_vf_violation: bool = True,
        budget_caps: BudgetCaps | None = None,
        llm_client_for_budget: object | None = None,
        compile_client_for_budget: object | None = None,
        bridge_client_for_budget: object | None = None,
    ):
        """Wave 5 R1 — `repair`, `verifiers`, `sampling`, `routing` are typed
        frozen sub-configs (kukai.modeling.foreman.config) that group the
        legacy ~9 optional kwargs by capability. Cross-config invariants
        (e.g. "sampling.n > 1 needs repair.judge") are validated here.
        """
        self._project_id = project_id
        self._resolver = resolver
        self._queue = execution_queue
        self._skills = skill_loader
        self._rag = rag_snippets
        self._project_state = project_state_provider

        # Unpack repair sub-config (Phase 2 — Reflexion). All-or-nothing
        # enforced inside ForemanRepair's pydantic schema.
        self._judge = repair.judge if repair is not None else None
        self._compile_for_repair = (
            repair.compile_client_for_repair if repair is not None else None)
        self._reflect_llm = repair.reflect_llm if repair is not None else None

        # Unpack verifiers sub-config (Phase 3 Task 2).
        self._toolbox = verifiers.toolbox if verifiers is not None else None
        self._mock_revit_session = (
            verifiers.mock_revit_session if verifiers is not None else None)

        self._replan_on_vf_violation = replan_on_vf_violation

        # Unpack routing sub-config (Phase 4 Task 2 — Cascade routing).
        # If pro_subagent is None the dispatcher falls back to single-subagent
        # path (Flash for everything). When provided, complex tasks
        # (ModelChoice.PRO from tier_selector) route there.
        self._pro_subagent = routing.pro_subagent if routing is not None else None

        # Audit N1 — ForemanBudgetGuard wiring. If caps + clients supplied,
        # run_phase wraps dispatch loop in the guard and checks after each
        # task. Defaults preserve backward compat (no guard).
        self._budget_caps = budget_caps
        self._budget_llm = llm_client_for_budget
        self._budget_compile = compile_client_for_budget
        self._budget_bridge = bridge_client_for_budget

        # Sampling wiring + cross-config validation. sub-configs only see their
        # own fields, so the "sampling > 1 requires Judge" rule is enforced
        # here, not on ForemanSampling itself.
        if sampling is not None:
            n = sampling.n
            roslyn_check_fn = sampling.roslyn_check_fn
        else:
            n = _resolve_default_n()
            roslyn_check_fn = None
        if n > 1:
            if self._judge is None:
                raise ValueError(
                    "sampling.n > 1 requires a ForemanRepair (or its judge). "
                    "Pass repair=ForemanRepair(judge=..., compile_client_for_repair=..., reflect_llm=...)"
                )
            self._subagent = SampledStructuralSubagent(
                underlying=subagent,
                invariants_check_fn=check_proposal_invariants,
                roslyn_check_fn=roslyn_check_fn, judge=self._judge, n=n,
            )
        else:
            self._subagent = subagent

    async def dispatch_task(
        self,
        plan_task: PlanTask,
        *,
        phase: Phase,
        task_seq: int,
    ) -> DispatchOutcome:
        """Resolve → load skill → ask subagent → review → (maybe) execute.

        Pure orchestration. Emits no events itself; caller (run_phase) wraps
        this with EventLog writes once integrated in Task 6.
        """
        notes: list[str] = []

        # 1. Resolve intent → IDs/coords
        resolver_output = await self._resolver.resolve(plan_task.intent)
        if resolver_output.family_resolution != FamilyResolutionStatus.RESOLVED:
            notes.append(
                f"family resolution={resolver_output.family_resolution.value}; "
                "halting before subagent"
            )
            brief = self._build_task_brief(
                plan_task=plan_task, phase=phase, task_seq=task_seq,
                resolver_output=resolver_output,
                fallback_symbol_id=-1,
            )
            verdict = ReviewVerdict(
                passed=False,
                issues=[ReviewIssue(
                    severity=ReviewSeverity.BLOCKING,
                    category="family_not_resolved",
                    detail=resolver_output.family_resolution.value,
                )],
                summary="resolver did not produce a single family symbol",
            )
            return DispatchOutcome(
                plan_task_id=plan_task.plan_task_id,
                task_brief=brief,
                resolver_output=resolver_output,
                code_proposal=None,
                review_verdict=verdict,
                executed=False,
                execution_result=None,
                notes=notes,
            )

        # 2. Build TaskBrief for the Subagent
        brief = self._build_task_brief(
            plan_task=plan_task, phase=phase, task_seq=task_seq,
            resolver_output=resolver_output,
            fallback_symbol_id=resolver_output.family_symbol_id or -1,
        )

        # 3. Choose Tier + Model (Phase 4 Task 2 — cascade routing)
        chosen_tier, chosen_model = select_tier(plan_task)
        if chosen_tier != plan_task.tier:
            notes.append(f"tier overridden by selector: {plan_task.tier.value} -> {chosen_tier.value}")
        notes.append(f"router selected model: {chosen_model.value}")

        # 4. Subagent generates a CodeProposal (with optional repair loop)
        skill_content = self._skills.load(plan_task.skill_path)
        if chosen_model is ModelChoice.PRO:
            if self._pro_subagent is None:
                raise ValueError(
                    "Cascade router selected PRO but pro_subagent not configured; "
                    "pass pro_subagent= to Foreman or disable the router"
                )
            active_subagent = self._pro_subagent
        else:
            active_subagent = self._subagent
        if (self._judge is not None and self._compile_for_repair is not None
                and self._reflect_llm is not None):
            proposal, repair_history = await repair_loop(
                subagent=active_subagent, judge=self._judge,
                compile_client=self._compile_for_repair,
                brief=brief, skill=skill_content, rag=self._rag,
                reflect_llm=self._reflect_llm, max_attempts=3,
            )
            if proposal is None:
                verdict = ReviewVerdict(
                    passed=False,
                    issues=[ReviewIssue(
                        severity=ReviewSeverity.BLOCKING,
                        category="repair_loop_gave_up",
                        detail=f"{len(repair_history)} attempt(s) exhausted",
                    )],
                    summary="repair_loop gave up after exhausting attempts",
                )
                return DispatchOutcome(
                    plan_task_id=plan_task.plan_task_id,
                    task_brief=brief,
                    resolver_output=resolver_output,
                    code_proposal=None,
                    review_verdict=verdict,
                    executed=False,
                    execution_result=None,
                    notes=notes + [f"repair attempts={len(repair_history)}"],
                )
            if repair_history:
                notes.append(f"repair attempts={len(repair_history)}")
        else:
            proposal = await active_subagent.generate_code(
                task_brief=brief, skill_content=skill_content, rag_snippets=self._rag,
            )

        # 5. Foreman reviews. With toolbox: multi-verifier. Without: legacy.
        if self._toolbox is not None:
            verdict = await review_proposal_multi(
                proposal, brief, self._toolbox, self._mock_revit_session)
        else:
            verdict = review_proposal(proposal, brief)
        # Wave 6C — Fix A#5: surface INFO-severity questions_to_foreman as
        # an operator-facing escalation note. The verifier records them as
        # non-blocking (was BLOCKING before Wave 6C), so dispatch continues.
        # If the subagent later returns more questions on a successor task,
        # each call will append its own line — counts are per-dispatch.
        q_count = sum(
            1 for i in verdict.issues
            if i.category == "questions_to_foreman"
            and i.severity != ReviewSeverity.BLOCKING
        )
        if q_count:
            notes.append(
                f"escalation: {q_count} question(s) raised by subagent — "
                f"operator follow-up suggested"
            )
        if not verdict.passed:
            return DispatchOutcome(
                plan_task_id=plan_task.plan_task_id,
                task_brief=brief,
                resolver_output=resolver_output,
                code_proposal=proposal,
                review_verdict=verdict,
                executed=False,
                execution_result=None,
                notes=notes,
            )

        # 6. Execute
        exec_task = ExecutionTask(
            task_id=brief.task_id,
            csharp_code=proposal.csharp_code,
            expected_elements=brief.expected_elements,
            revit_version=brief.revit_version,
            transaction_name=proposal.transaction_name,
            max_compile_attempts=1,
            max_execute_attempts=1,
        )
        exec_result = await self._queue.submit(exec_task, brief=brief, proposal=proposal)

        # 7. VF evaluation (Phase 4 Task 1 — VeriMAP)
        vf_violations: list[VFViolation] = []
        vf_violations_after_replan: list[VFViolation] = []
        vf_check_skipped: list[str] = []
        vf_replanned = False
        # Short-circuit: skip VF if no declaration (declared_outputs=None) — no verification possible.
        # Fix G: Optional[DeclaredOutputs] disambiguates "not declared" (None) from "declared empty"
        # (DeclaredOutputs with count=0). Phase 5 can enforce non-None via persona contract.
        if (
            exec_result.success
            and plan_task.verification_function is not None
            and proposal.declared_outputs is not None
        ):
            actual_count = len(exec_result.element_ids)
            ac, ap, aln, afn = self._collect_actuals(exec_result, brief)
            evaluation = evaluate_verification_function(
                plan_task=plan_task,
                declared_outputs=proposal.declared_outputs,
                actual_count=actual_count, actual_category=ac,
                actual_parameters=ap,
                actual_level_name=aln, actual_family_name=afn,
            )
            vf_violations = list(evaluation.violations)
            vf_check_skipped = list(evaluation.skipped)
            if vf_check_skipped:
                notes.append(f"vf_check_skipped: {','.join(vf_check_skipped)}")
            if vf_violations:
                notes.append("VF violation(s): " + "; ".join(
                    f"{v.field_name}={v.declared}->{v.actual}" for v in vf_violations))
                if self._replan_on_vf_violation:
                    proposal, _ = await replan_single_task(
                        plan_task=plan_task, brief=brief, violations=vf_violations,
                        regenerate=self._make_regenerator(plan_task),
                    )
                    vf_replanned = True
                    notes.append("replan: regenerated proposal after VF violation")
                    exec_task_2 = ExecutionTask(
                        task_id=brief.task_id + "-replan",
                        csharp_code=proposal.csharp_code,
                        expected_elements=brief.expected_elements,
                        revit_version=brief.revit_version,
                        transaction_name=proposal.transaction_name,
                        max_compile_attempts=1, max_execute_attempts=1,
                    )
                    exec_result = await self._queue.submit(
                        exec_task_2, brief=brief, proposal=proposal,
                    )
                    # Fix C: re-evaluate VF on the regenerated proposal so the
                    # outcome reflects post-replan state. Original violations
                    # remain in `vf_violations` for audit trail.
                    if exec_result.success and proposal.declared_outputs is not None:
                        actual_count_2 = len(exec_result.element_ids)
                        ac2, ap2, aln2, afn2 = self._collect_actuals(exec_result, brief)
                        evaluation_2 = evaluate_verification_function(
                            plan_task=plan_task,
                            declared_outputs=proposal.declared_outputs,
                            actual_count=actual_count_2, actual_category=ac2,
                            actual_parameters=ap2,
                            actual_level_name=aln2, actual_family_name=afn2,
                        )
                        vf_violations_after_replan = list(evaluation_2.violations)
                        # Merge skipped fields from replan eval (deduped, order preserved).
                        for s in evaluation_2.skipped:
                            if s not in vf_check_skipped:
                                vf_check_skipped.append(s)
                        if vf_violations_after_replan:
                            notes.append(
                                "replan did not fix VF violations: " + "; ".join(
                                    f"{v.field_name}={v.declared}->{v.actual}"
                                    for v in vf_violations_after_replan))

        return DispatchOutcome(
            plan_task_id=plan_task.plan_task_id,
            task_brief=brief,
            resolver_output=resolver_output,
            code_proposal=proposal,
            review_verdict=verdict,
            executed=True,
            execution_result=exec_result,
            notes=notes,
            vf_violations=vf_violations,
            vf_replanned=vf_replanned,
            vf_violations_after_replan=vf_violations_after_replan,
            vf_check_skipped=vf_check_skipped,
        )

    async def run_phase(self, plan: PhasePlan) -> PhaseRunResult:
        """Run every PlanTask in `plan` in order.

        Halt early ONLY if user_intervention is currently required when about
        to dispatch the next task. A failing task does NOT halt the phase —
        we want PARTIAL outcomes visible so the operator can repair.

        Wave 7.5 Fix #1 (Audit A1/A5/B1 — convergent critical finding):
        Validate plan_task_id matches the deterministic formula upfront when
        it LOOKS like a sha256-style id (16 lowercase hex chars). Any Planner
        LLM that produces sha256 ids using a different formula (e.g. with
        `phase_id` instead of `phase.value`) will fail loud HERE instead of
        silently producing task_id mismatches deep in `dispatch_task` →
        `subagent.structural._validate`. Legacy/test fixture ids (e.g.
        "pt_0001", "ptask-1") bypass validation — they're not bound by the
        formula contract.
        """
        import re as _re
        _SHA256_LIKE = _re.compile(r'^[a-f0-9]{16}$')
        for seq, plan_task in enumerate(plan.tasks, start=1):
            if not _SHA256_LIKE.match(plan_task.plan_task_id):
                continue  # legacy/test fixture id — formula not enforced
            expected_id = deterministic_task_uuid(self._project_id, plan.phase.value, seq)
            if plan_task.plan_task_id != expected_id:
                raise ValueError(
                    f"PhasePlan plan_task_id mismatch at task[{seq - 1}]: "
                    f"got {plan_task.plan_task_id!r}, "
                    f"expected {expected_id!r} "
                    f"(formula: sha256(f'{self._project_id}/{plan.phase.value}/{seq}')[:16]). "
                    f"Use deterministic_task_uuid(project_id, phase.value, seq) "
                    f"when constructing PhasePlan tasks — see "
                    f"kukai.modeling.schemas.identifiers.deterministic_task_uuid."
                )

        succeeded: list[str] = []
        failed: list[str] = []
        notes: list[str] = []

        # Audit N1 — install ForemanBudgetGuard if caps + clients provided.
        guard: ForemanBudgetGuard | None = None
        if self._budget_caps is not None:
            guard = ForemanBudgetGuard(
                self._budget_caps,
                self._budget_llm,
                self._budget_compile,
                self._budget_bridge,
            )
            guard.__enter__()

        try:
            for seq, plan_task in enumerate(plan.tasks, start=1):
                state = self._project_state()
                if state.user_intervention_required:
                    reason = state.user_intervention_reason
                    notes.append(f"user_intervention_required ({reason!r}); aborting phase")
                    return PhaseRunResult(
                        phase=plan.phase,
                        status=PhaseRunStatus.ABORTED,
                        plan_task_ids=[t.plan_task_id for t in plan.tasks],
                        succeeded_plan_task_ids=succeeded,
                        failed_plan_task_ids=failed,
                        notes=notes,
                    )

                try:
                    outcome = await self.dispatch_task(plan_task, phase=plan.phase, task_seq=seq)
                except BudgetExceededError as e:
                    notes.append(f"budget exceeded mid-dispatch: {e}; aborting phase")
                    return PhaseRunResult(
                        phase=plan.phase,
                        status=PhaseRunStatus.ABORTED,
                        plan_task_ids=[t.plan_task_id for t in plan.tasks],
                        succeeded_plan_task_ids=succeeded,
                        failed_plan_task_ids=failed + [plan_task.plan_task_id],
                        notes=notes,
                    )
                except Exception as e:  # Wave 6A B#1 — never let a single task crash the phase
                    # A subagent / resolver / queue / verifier raising ANY uncaught
                    # exception (RuntimeError, ValidationError, httpx errors, …)
                    # used to propagate out of run_phase and destroy the entire
                    # PhaseRunResult. Now we record the failure and continue with
                    # the next task so partial progress is preserved.
                    # NOTE: deliberately catch Exception (not BaseException) so
                    # KeyboardInterrupt / SystemExit still abort the phase.
                    failed.append(plan_task.plan_task_id)
                    notes.append(
                        f"{plan_task.plan_task_id}: dispatch crashed: "
                        f"{type(e).__name__}: {str(e)[:200]}"
                    )
                    continue
                # Propagate per-task notes (e.g. "repair attempts=N") so the caller
                # sees observability signals from the dispatch path.
                for n in outcome.notes:
                    notes.append(f"{plan_task.plan_task_id}: {n}")
                if outcome.executed and outcome.execution_result and outcome.execution_result.success:
                    succeeded.append(plan_task.plan_task_id)
                else:
                    failed.append(plan_task.plan_task_id)
                    notes.append(
                        f"{plan_task.plan_task_id}: {outcome.review_verdict.summary}"
                        if not outcome.executed
                        else f"{plan_task.plan_task_id}: execution failed "
                             f"({outcome.execution_result.failure_stage if outcome.execution_result else 'unknown'})"
                    )

                # Audit N1 — check budget after each dispatched task.
                if guard is not None:
                    try:
                        guard.check()
                    except BudgetExceededError as e:
                        notes.append(f"budget exceeded after task: {e}; aborting phase")
                        return PhaseRunResult(
                            phase=plan.phase,
                            status=PhaseRunStatus.ABORTED,
                            plan_task_ids=[t.plan_task_id for t in plan.tasks],
                            succeeded_plan_task_ids=succeeded,
                            failed_plan_task_ids=failed,
                            notes=notes,
                        )
        finally:
            if guard is not None:
                guard.__exit__(None, None, None)

        all_ids = [t.plan_task_id for t in plan.tasks]
        if not failed:
            status = PhaseRunStatus.COMPLETED
        elif not succeeded:
            status = PhaseRunStatus.FAILED
        else:
            status = PhaseRunStatus.PARTIAL

        return PhaseRunResult(
            phase=plan.phase,
            status=status,
            plan_task_ids=all_ids,
            succeeded_plan_task_ids=succeeded,
            failed_plan_task_ids=failed,
            notes=notes,
        )

    # ---- helpers ----

    def _build_task_brief(
        self,
        *,
        plan_task: PlanTask,
        phase: Phase,
        task_seq: int,
        resolver_output: ResolverOutput,
        fallback_symbol_id: int,
    ) -> TaskBrief:
        task_id = deterministic_task_uuid(self._project_id, phase.value, task_seq)
        # Convert resolver_output.parameter_map (name -> (alias, scope))
        # into TaskBrief.parameter_map (name -> ParameterRef)
        param_map: dict[str, ParameterRef] = {}
        for canonical, (alias, scope) in resolver_output.parameter_map.items():
            param_map[canonical] = ParameterRef(name=alias, scope=scope.value)

        return TaskBrief(
            task_id=task_id,
            phase=phase,
            skill_path=plan_task.skill_path,
            element_type=plan_task.intent.element_type,
            placement_point=resolver_output.placement_point,
            family_symbol_id=resolver_output.family_symbol_id or fallback_symbol_id,
            parameter_map=param_map,
            level_id=resolver_output.level_id,
            top_level_id=resolver_output.top_level_id,
            revit_version=resolver_output.revit_version,
            expected_elements=plan_task.expected_elements,
            constraints=[],
            tier=plan_task.tier,
            is_repair=plan_task.is_repair,
            repair_for_task_id=plan_task.repair_for_plan_task_id,
            estimated_cost_usd=plan_task.estimated_cost_usd,
        )

    def _collect_actuals(self, exec_result, brief):
        """Best-effort actual-property snapshot. Phase 5 will deepen this."""
        # TODO Phase 5 (Audit A#1): wire to ModelQueryClient.query_element_properties
        # post-L4 execute. Today this returns stub data, which is why Wave 2 fix B+C
        # made VF skip unobservable fields. Until real wiring lands, VF can only
        # verify count + category, not level/family/parameter values.
        actual_category = brief.expected_elements.category  # gate-passed = matched
        return actual_category, {}, None, None

    def _make_regenerator(self, plan_task):
        async def regen(brief, viols):
            skill_content = self._skills.load(plan_task.skill_path)
            v_summary = "\n".join(
                f"- {v.field_name}: declared={v.declared}, actual={v.actual}"
                for v in viols)
            extra = ("vf_violations", "Prior VF violations to correct", v_summary)
            # Replans always go through pro if available (repair is +30 score).
            sub = self._pro_subagent or self._subagent
            return await sub.generate_code(
                task_brief=brief, skill_content=skill_content,
                rag_snippets=self._rag + [extra],
            )
        return regen


class InterpretedResult(BaseModel):
    """Foreman's human-readable decoding of an ExecutionResult."""
    model_config = ConfigDict(frozen=True)

    kind: str  # "success" | "compile_failed" | "execute_failed" | "count_mismatch" | "unknown_failure"
    human_summary: str
    element_count: int = 0


def interpret_result(execution_result: ExecutionResult) -> InterpretedResult:
    """Turn an ExecutionResult into a verdict the Foreman (or a human) can act on."""
    if execution_result.success:
        return InterpretedResult(
            kind="success",
            human_summary=f"placed {len(execution_result.element_ids)} element(s)",
            element_count=len(execution_result.element_ids),
        )
    stage = execution_result.failure_stage
    err = execution_result.error_message or "no error message"
    if stage == "compile":
        return InterpretedResult(kind="compile_failed", human_summary=f"compile failed: {err}")
    if stage == "execute":
        return InterpretedResult(kind="execute_failed", human_summary=f"execute failed: {err}")
    if stage == "count_mismatch":
        return InterpretedResult(kind="count_mismatch", human_summary=f"count mismatch: {err}")
    return InterpretedResult(kind="unknown_failure", human_summary=f"unknown failure: {err}")
