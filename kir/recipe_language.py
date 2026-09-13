"""Existing author-script language plus one pure Project output-ID function.

Selected explicitly by the trusted runner's SandboxPolicy. This does not widen
the sandbox's import/builtin policy or execute a saved Project/RecipePin.
"""
from kir.course import language as _language
from kir.course.language import *  # noqa: F401,F403 — preserve the existing language objects
from kir.course.language import take_ops, warm_for_source  # noqa: F401 — sandbox hooks, not author commands
from kir.project import output_id as _output_id


def project_output_id(project_id: str, instance_key: str, output_key: str) -> str:
    """Compute the existing canonical Project namespace; no lookup or rewrite."""
    return _output_id(project_id, instance_key, output_key)


__all__ = sorted(set(_language.__all__) | {"project_output_id"})
