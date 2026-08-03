"""Data models for the KUKAI Audit Engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Severity(Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class Category(Enum):
    NAMING = "naming"
    PARAMETERS = "parameters"
    GEOMETRY = "geometry"
    LEVELS = "levels"
    WARNINGS = "warnings"
    IFC_READY = "ifc_ready"


class AuditStatus(Enum):
    PASSED = "passed"
    PASSED_WITH_WARNINGS = "passed_with_warnings"
    FAILED = "failed"


@dataclass
class AuditRule:
    id: str
    name: str
    category: Category
    severity: Severity
    description: str
    check_code: str
    norm_ref: str | None = None
    enabled: bool = True


@dataclass
class AuditIssue:
    rule_id: str
    rule_name: str
    category: Category
    severity: Severity
    element_ids: list[int] = field(default_factory=list)
    element_count: int = 0
    message: str = ""
    details: dict = field(default_factory=dict)
    explanation: str | None = None


@dataclass
class AuditSummary:
    total_rules: int
    passed: int
    errors: int
    warnings: int
    infos: int


@dataclass
class AuditReport:
    status: AuditStatus
    summary: AuditSummary
    issues: list[AuditIssue]
    total_elements: int
    checked_at: datetime
    duration_seconds: float
    categories_checked: list[str]
