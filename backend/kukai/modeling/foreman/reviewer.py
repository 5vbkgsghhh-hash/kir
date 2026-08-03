"""Deterministic Foreman review of a Subagent's CodeProposal.

Per spec Section 5.2 + Section 18.3 reversal R5. This is NOT an LLM call —
it's a fixed checklist that runs in microseconds. Its job is to refuse to
push a proposal into the ExecutionQueue when it disagrees with the TaskBrief
on identity, count, version, or shows obvious red-flag content.

Why deterministic and not an LLM reviewer here:
  * Plan 8 scope only — we don't want LLM-on-LLM cost yet
  * These specific checks have no ambiguity; an LLM would be noise
  * Future Plans may add an LLM Reviewer as a SECOND gate, not a replacement
"""
from __future__ import annotations
import re

from kukai.modeling.bridge.mock_revit_session import MockRevitSession
from kukai.modeling.foreman.toolbox import ForemanToolBox
from kukai.modeling.foreman.verifiers.correctness import check_correctness
from kukai.modeling.foreman.verifiers.geometry import check_geometry
from kukai.modeling.foreman.verifiers.safety import check_safety
from kukai.modeling.schemas.foreman import ReviewIssue, ReviewSeverity, ReviewVerdict
from kukai.modeling.schemas.llm import CodeProposal
from kukai.modeling.schemas.tasks import TaskBrief


_PLACEHOLDER_PATTERNS = (
    re.compile(r"//\s*TODO", re.IGNORECASE),
    re.compile(r"//\s*FIXME", re.IGNORECASE),
    re.compile(r"\bplaceholder\b", re.IGNORECASE),
    re.compile(r"\bnot[_ ]?implemented\b", re.IGNORECASE),
)


def review_proposal(proposal: CodeProposal, brief: TaskBrief) -> ReviewVerdict:
    """Run the full deterministic checklist. Returns a ReviewVerdict."""
    issues: list[ReviewIssue] = []

    # 1. Identity
    if proposal.task_id != brief.task_id:
        issues.append(ReviewIssue(
            severity=ReviewSeverity.BLOCKING,
            category="task_id_mismatch",
            detail=f"brief={brief.task_id!r} proposal={proposal.task_id!r}",
        ))

    # 2. Revit version
    if proposal.revit_version != brief.revit_version:
        issues.append(ReviewIssue(
            severity=ReviewSeverity.BLOCKING,
            category="version_mismatch",
            detail=f"brief={brief.revit_version!r} proposal={proposal.revit_version!r}",
        ))

    # 3. Expected elements — category
    if proposal.expected_elements.category != brief.expected_elements.category:
        issues.append(ReviewIssue(
            severity=ReviewSeverity.BLOCKING,
            category="expected_category_mismatch",
            detail=(
                f"brief={brief.expected_elements.category!r} "
                f"proposal={proposal.expected_elements.category!r}"
            ),
        ))

    # 4. Expected elements — count
    if proposal.expected_elements.count != brief.expected_elements.count:
        issues.append(ReviewIssue(
            severity=ReviewSeverity.BLOCKING,
            category="expected_count_mismatch",
            detail=(
                f"brief={brief.expected_elements.count} "
                f"proposal={proposal.expected_elements.count}"
            ),
        ))

    # 5. Transaction name not whitespace-only
    if not proposal.transaction_name.strip():
        issues.append(ReviewIssue(
            severity=ReviewSeverity.BLOCKING,
            category="empty_transaction_name",
            detail="transaction_name is whitespace-only",
        ))

    # 6. Placeholder markers in code
    for pattern in _PLACEHOLDER_PATTERNS:
        if pattern.search(proposal.csharp_code):
            issues.append(ReviewIssue(
                severity=ReviewSeverity.BLOCKING,
                category="placeholder_code",
                detail=f"matched pattern: {pattern.pattern}",
            ))
            break  # one match is enough

    # 7. Subagent is asking — Wave 6C Fix A#5: INFO, not blocking.
    # Persona teaches LLM to use questions_to_foreman as the escape hatch
    # for ambiguity (rule 8 in STRUCTURAL_SUBAGENT_PERSONA). The dispatcher
    # appends an escalation note for operator follow-up but does not block.
    if proposal.questions_to_foreman:
        issues.append(ReviewIssue(
            severity=ReviewSeverity.INFO,
            category="questions_to_foreman",
            detail=f"{len(proposal.questions_to_foreman)} question(s) raised",
        ))

    passed = not any(i.severity == ReviewSeverity.BLOCKING for i in issues)
    summary = (
        "review passed" if passed
        else f"review blocked by {sum(1 for i in issues if i.severity == ReviewSeverity.BLOCKING)} issue(s)"
    )

    return ReviewVerdict(passed=passed, issues=issues, summary=summary)


async def review_proposal_multi(
    proposal: CodeProposal,
    brief: TaskBrief,
    toolbox: ForemanToolBox,
    session: MockRevitSession | None = None,
) -> ReviewVerdict:
    """Run all three verifiers and aggregate. Sequential (verifiers are cheap)."""
    issues: list[ReviewIssue] = []
    issues.extend(check_correctness(proposal, brief))
    issues.extend(await check_geometry(proposal, brief, toolbox, session))
    issues.extend(check_safety(proposal))

    blocking = sum(1 for i in issues if i.severity == ReviewSeverity.BLOCKING)
    warning = sum(1 for i in issues if i.severity == ReviewSeverity.WARNING)
    passed = blocking == 0
    if passed and not issues:
        summary = "multi-verifier passed (0 issues)"
    elif passed:
        summary = f"multi-verifier passed with {warning} warning(s)"
    else:
        summary = f"multi-verifier blocked by {blocking} issue(s) ({warning} additional warnings)"
    return ReviewVerdict(passed=passed, issues=issues, summary=summary)
