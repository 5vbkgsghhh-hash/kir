"""End-to-end integration: Resolver -> TemplatedExecutor -> ExecutionQueue.

No LLM, no Revit. All via Plan 1/2/3 mock infrastructure. Proves the Tier 1
path works through the entire deterministic substrate.
"""
from __future__ import annotations
import pathlib
import pytest

from kukai.modeling.bridge.mocks import (
    MockBridgeClient,
    MockCompileClient,
    MockModelQueryClient,
)
from kukai.modeling.bridge.model_query_client import GridInfo, LevelInfo
from kukai.modeling.execution.gates import (
    CompileGate, CountValidationGate, ExecuteGate
)
from kukai.modeling.execution.queue import ExecutionQueue
from kukai.modeling.resolver.dispatcher import Resolver
from kukai.modeling.schemas.resolver import (
    FamilyHint,
    FamilySymbolCandidate,
    GridIntersectionSpec,
    ResolverIntent,
)
from kukai.modeling.templated.executor import TemplatedExecutor
from kukai.modeling.templated.registry import TemplateRegistry


def _templates_dir() -> pathlib.Path:
    here = pathlib.Path(__file__).resolve()
    return here.parents[2] / "templates"


@pytest.fixture
def stocked_query_client() -> MockModelQueryClient:
    return MockModelQueryClient(
        families=[
            FamilySymbolCandidate(
                family_symbol_id=8821,
                name="400 x 400mm",
                family_name="M_Concrete-Rectangular-Column",
                category="OST_StructuralColumns",
                dimensions_mm={"width": 400, "height": 400},
            ),
        ],
        levels=[
            LevelInfo(level_id=1042, name="Level 1", elevation_mm=0.0),
            LevelInfo(level_id=1043, name="Level 2", elevation_mm=3300.0),
        ],
        grids=[
            GridInfo(grid_id=2002, name="2", axis="horizontal", position_mm=6000.0),
            GridInfo(grid_id=2004, name="B", axis="vertical", position_mm=6000.0),
        ],
        parameter_info={
            8821: {"mark": ("ALL_MODEL_MARK", "built_in")},
        },
    )


@pytest.mark.asyncio
async def test_place_one_column_end_to_end(stocked_query_client):
    """Foreman-style intent -> Resolver -> TemplatedExecutor -> element placed."""
    resolver = Resolver(stocked_query_client)
    registry = TemplateRegistry(_templates_dir())
    queue = ExecutionQueue(
        compile_gate=CompileGate(MockCompileClient()),
        execute_gate=ExecuteGate(MockBridgeClient(), session_id="dev"),
        count_gate=CountValidationGate(),
    )
    executor = TemplatedExecutor(registry, queue)

    # Foreman: "place RC 400x400 column at grid 2B level +0.000"
    intent = ResolverIntent(
        element_type="structural_column",
        family_hint=FamilyHint(
            category="OST_StructuralColumns",
            dimensions_mm={"width": 400, "height": 400},
        ),
        grid_intersection=GridIntersectionSpec(
            grid_x_name="2", grid_y_name="B", level_name="Level 1",
        ),
        top_level_name="Level 2",
        revit_version="2026",
    )
    resolver_output = await resolver.resolve(intent)
    assert resolver_output.family_symbol_id == 8821
    assert resolver_output.placement_point.x == 6000.0
    assert resolver_output.placement_point.y == 6000.0
    assert resolver_output.level_id == 1042
    assert resolver_output.top_level_id == 1043

    result = await executor.place_element(
        template_name="structural_column_at_point",
        resolver_output=resolver_output,
        task_id="end_to_end_test_001",
        mark="C-2B-L1",
        extra_args={},
    )
    assert result.success is True
    assert result.l3_compile_passed
    assert result.l4_execute_passed
    assert result.l5_count_passed
    assert len(result.element_ids) == 1
