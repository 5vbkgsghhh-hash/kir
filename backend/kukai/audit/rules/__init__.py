"""Audit rule definitions.

Each submodule in this package exports a list of AuditRule instances.
"""

from __future__ import annotations

from kukai.audit.models import AuditRule


def load_all_rules() -> list[AuditRule]:
    """Load all audit rules from submodules."""
    from kukai.audit.rules.geometry import get_rules as geometry_rules
    from kukai.audit.rules.ifc_ready import get_rules as ifc_ready_rules
    from kukai.audit.rules.levels import get_rules as levels_rules
    from kukai.audit.rules.naming import get_rules as naming_rules
    from kukai.audit.rules.parameters import get_rules as parameters_rules
    from kukai.audit.rules.warnings import get_rules as warnings_rules

    rules: list[AuditRule] = []
    rules.extend(naming_rules())
    rules.extend(parameters_rules())
    rules.extend(geometry_rules())
    rules.extend(levels_rules())
    rules.extend(warnings_rules())
    rules.extend(ifc_ready_rules())
    return rules
