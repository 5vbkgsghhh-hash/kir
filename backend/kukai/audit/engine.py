"""AuditEngine — orchestrates rule execution and AI explanations."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from kukai.audit.constants import DEFAULT_CATEGORIES
from kukai.audit.explainer import AuditExplainer
from kukai.audit.models import (
    AuditIssue,
    AuditReport,
    AuditRule,
    AuditStatus,
    AuditSummary,
    Category,
    Severity,
)
from kukai.audit.reporter import AuditReporter
from kukai.audit.rules import load_all_rules

if TYPE_CHECKING:
    from kukai.bridge.client import BridgeClient
    from kukai.llm.client import LLMClient
    from kukai.storage.database import Database

logger = logging.getLogger(__name__)


class AuditEngine:
    """Runs audit rules against a Revit model via the bridge."""

    def __init__(
        self,
        bridge: BridgeClient,
        llm: LLMClient,
        db: Database,
    ) -> None:
        self._bridge = bridge
        self._llm = llm
        self._db = db
        self._explainer = AuditExplainer(llm)
        self._reporter = AuditReporter()
        self._rules: list[AuditRule] = []
        self._load_rules()

    def _load_rules(self, categories: list[str] | None = None) -> None:
        all_rules = load_all_rules()
        if categories:
            cat_set = set(categories)
            self._rules = [
                r for r in all_rules
                if r.enabled and r.category.value in cat_set
            ]
        else:
            self._rules = [r for r in all_rules if r.enabled]

    async def quick_check(
        self,
        model_context: dict[str, Any] | None = None,
    ) -> AuditReport:
        """Fast audit — no AI explanations."""
        start = time.monotonic()

        if model_context is None:
            model_context = await self._get_model_context()

        issues: list[AuditIssue] = []
        for rule in self._rules:
            issue = await self._execute_rule(rule)
            if issue is not None:
                issues.append(issue)

        duration = time.monotonic() - start
        total_elements = model_context.get("element_count", 0)
        categories_checked = sorted({r.category.value for r in self._rules})

        return self._build_report(
            issues=issues,
            total_elements=total_elements,
            duration=duration,
            categories_checked=categories_checked,
            total_rules=len(self._rules),
        )

    async def run(
        self,
        model_context: dict[str, Any] | None = None,
        categories: list[str] | None = None,
    ) -> AuditReport:
        """Full audit with AI explanations for errors and warnings."""
        if categories:
            self._load_rules(categories)

        report = await self.quick_check(model_context)

        # Build a rule lookup for the explainer (norm_ref, etc.)
        rule_map = {r.id: r for r in self._rules}

        for issue in report.issues:
            if issue.severity in (Severity.ERROR, Severity.WARNING):
                rule = rule_map.get(issue.rule_id)
                issue.explanation = await self._explainer.explain(issue, rule)

        return report

    def format_chat(self, report: AuditReport) -> str:
        """Format a report as Markdown for the chat UI."""
        return self._reporter.format_chat(report)

    def generate_excel(self, report: AuditReport) -> bytes:
        """Generate an Excel workbook from the report."""
        return self._reporter.generate_excel(report)

    async def _execute_rule(self, rule: AuditRule) -> AuditIssue | None:
        """Execute a single rule via the bridge and return an issue if it fails."""
        try:
            exec_result = await self._bridge.execute(rule.check_code)
        except Exception as exc:
            logger.warning("Rule %s bridge error: %s", rule.id, exc)
            return AuditIssue(
                rule_id=rule.id,
                rule_name=rule.name,
                category=rule.category,
                severity=rule.severity,
                message=f"Check execution failed: {exc}",
            )

        # ExecuteResult is a Pydantic model with .success and .output
        if not exec_result.success:
            return AuditIssue(
                rule_id=rule.id,
                rule_name=rule.name,
                category=rule.category,
                severity=rule.severity,
                message=f"Bridge execution failed: {exec_result.output}",
            )

        # Parse JSON string from C# code
        try:
            result = json.loads(exec_result.output) if isinstance(exec_result.output, str) else exec_result.output
        except (json.JSONDecodeError, TypeError):
            result = {}

        if isinstance(result, dict) and result.get("passed", False):
            return None

        element_ids = result.get("element_ids", []) if isinstance(result, dict) else []
        message = result.get("message", "") if isinstance(result, dict) else str(result)

        return AuditIssue(
            rule_id=rule.id,
            rule_name=rule.name,
            category=rule.category,
            severity=rule.severity,
            element_ids=element_ids,
            element_count=len(element_ids),
            message=message,
            details=result if isinstance(result, dict) else {},
        )

    async def _get_model_context(self) -> dict[str, Any]:
        """Retrieve model context from the bridge."""
        try:
            ctx = await self._bridge.context()
            # ContextResult → dict; derive element_count from category counts
            element_count = sum(c.count for c in ctx.categories) if ctx.categories else 0
            return {"element_count": element_count}
        except Exception as exc:
            logger.warning("Failed to get model context: %s", exc)
            return {}

    @staticmethod
    def _build_report(
        issues: list[AuditIssue],
        total_elements: int,
        duration: float,
        categories_checked: list[str],
        total_rules: int = 0,
    ) -> AuditReport:
        errors = sum(1 for i in issues if i.severity == Severity.ERROR)
        warnings = sum(1 for i in issues if i.severity == Severity.WARNING)
        infos = sum(1 for i in issues if i.severity == Severity.INFO)
        passed = total_rules - errors - warnings - infos

        if errors > 0:
            status = AuditStatus.FAILED
        elif warnings > 0:
            status = AuditStatus.PASSED_WITH_WARNINGS
        else:
            status = AuditStatus.PASSED

        return AuditReport(
            status=status,
            summary=AuditSummary(
                total_rules=errors + warnings + infos + passed,
                passed=max(passed, 0),
                errors=errors,
                warnings=warnings,
                infos=infos,
            ),
            issues=issues,
            total_elements=total_elements,
            checked_at=datetime.now(timezone.utc),
            duration_seconds=round(duration, 3),
            categories_checked=categories_checked,
        )
