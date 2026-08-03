"""TemplatedExecutor — Tier 1 path: render template + dispatch to ExecutionQueue.

Per spec Section 7.2. Inputs: template name + ResolverOutput + task identity.
Outputs: ExecutionResult from the queue. No LLM involvement — pure
deterministic rendering + execution.
"""
from __future__ import annotations
from typing import Any

from kukai.modeling.execution.queue import ExecutionQueue
from kukai.modeling.schemas.execution import ExecutionResult, ExecutionTask
from kukai.modeling.schemas.resolver import FamilyResolutionStatus, ResolverOutput
from kukai.modeling.schemas.tasks import ExpectedElementsSpec
from kukai.modeling.templated.registry import TemplateRegistry


class TemplatedExecutor:
    """Combines TemplateRegistry + ExecutionQueue into the Tier 1 path."""

    def __init__(self, registry: TemplateRegistry, queue: ExecutionQueue):
        self._registry = registry
        self._queue = queue

    async def place_element(
        self,
        *,
        template_name: str,
        resolver_output: ResolverOutput,
        task_id: str,
        mark: str,
        extra_args: dict[str, Any] | None = None,
    ) -> ExecutionResult:
        """Render the template against resolver output and submit to the queue.

        `mark` is broken out as a required argument because every BIM element
        gets a Mark and it's the human-readable identity used in logs.
        `extra_args` overrides or supplements template params (e.g. for setting
        a custom transaction_name or supplying optional template variables).
        """
        if resolver_output.family_resolution != FamilyResolutionStatus.RESOLVED:
            raise ValueError(
                f"family not resolved: status={resolver_output.family_resolution.value}; "
                f"cannot dispatch Tier 1 template — escalate to Foreman"
            )
        if resolver_output.family_symbol_id is None:
            raise ValueError("family_symbol_id is None despite RESOLVED status")

        manifest = self._registry.get_manifest(template_name)
        extra = dict(extra_args or {})

        # Default transaction_name uses mark if not supplied
        default_tx_name = extra.pop("transaction_name", None) or f"Place {mark}"

        args: dict[str, Any] = {
            "transaction_name": default_tx_name,
            "family_symbol_id": resolver_output.family_symbol_id,
            "level_id": resolver_output.level_id,
            "x_mm": resolver_output.placement_point.x,
            "y_mm": resolver_output.placement_point.y,
            "z_mm": resolver_output.placement_point.z,
            "mark": mark,
        }
        if resolver_output.top_level_id is not None:
            args["top_level_id"] = resolver_output.top_level_id
        args.update(extra)

        csharp_code = self._registry.render(template_name, args)

        task = ExecutionTask(
            task_id=task_id,
            csharp_code=csharp_code,
            expected_elements=ExpectedElementsSpec(
                category=manifest.expected_category,
                count=manifest.expected_count,
            ),
            revit_version=resolver_output.revit_version,
            transaction_name=default_tx_name,
            max_compile_attempts=3,
            max_execute_attempts=3,
        )
        return await self._queue.submit(task)
