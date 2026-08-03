"""Correctness verifier — 7 deterministic checks extracted from legacy review_proposal."""
from __future__ import annotations
import re

from kukai.modeling.schemas.foreman import ReviewIssue, ReviewSeverity
from kukai.modeling.schemas.llm import CodeProposal
from kukai.modeling.schemas.tasks import TaskBrief


_PLACEHOLDER_PATTERNS = (
    re.compile(r"//\s*TODO", re.IGNORECASE),
    re.compile(r"//\s*FIXME", re.IGNORECASE),
    re.compile(r"\bplaceholder\b", re.IGNORECASE),
    re.compile(r"\bnot[_ ]?implemented\b", re.IGNORECASE),
)


def _blocking(category: str, detail: str) -> ReviewIssue:
    return ReviewIssue(
        severity=ReviewSeverity.BLOCKING, category=category, detail=detail,
        verifier_source="correctness",
    )


def _info(category: str, detail: str) -> ReviewIssue:
    return ReviewIssue(
        severity=ReviewSeverity.INFO, category=category, detail=detail,
        verifier_source="correctness",
    )


def check_correctness(proposal: CodeProposal, brief: TaskBrief) -> list[ReviewIssue]:
    issues: list[ReviewIssue] = []

    if proposal.task_id != brief.task_id:
        issues.append(_blocking(
            "task_id_mismatch",
            f"brief={brief.task_id!r} proposal={proposal.task_id!r}"))

    if proposal.revit_version != brief.revit_version:
        issues.append(_blocking(
            "version_mismatch",
            f"brief={brief.revit_version!r} proposal={proposal.revit_version!r}"))

    if proposal.expected_elements.category != brief.expected_elements.category:
        issues.append(_blocking(
            "expected_category_mismatch",
            f"brief={brief.expected_elements.category!r} "
            f"proposal={proposal.expected_elements.category!r}"))

    if proposal.expected_elements.count != brief.expected_elements.count:
        issues.append(_blocking(
            "expected_count_mismatch",
            f"brief={brief.expected_elements.count} "
            f"proposal={proposal.expected_elements.count}"))

    if not proposal.transaction_name.strip():
        issues.append(_blocking(
            "empty_transaction_name", "transaction_name is whitespace-only"))

    for pattern in _PLACEHOLDER_PATTERNS:
        if pattern.search(proposal.csharp_code):
            issues.append(_blocking(
                "placeholder_code", f"matched pattern: {pattern.pattern}"))
            break

    if proposal.questions_to_foreman:
        # Wave 6C — Fix A#5: questions_to_foreman is INFO, not blocking.
        # The persona instructs the LLM that questions are how to ask for
        # clarification when it cannot proceed unambiguously. Blocking the
        # proposal here would teach a feature and then punish its use.
        # The dispatcher detects these and appends an escalation note to
        # outcome.notes for operator follow-up, then continues normally.
        issues.append(_info(
            "questions_to_foreman",
            f"{len(proposal.questions_to_foreman)} question(s) raised"))

    return issues
