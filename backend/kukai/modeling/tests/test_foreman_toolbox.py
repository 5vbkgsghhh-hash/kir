"""ForemanToolBox composes ModelQueryClient + ProjectState + EventLog reads."""
from __future__ import annotations
import pytest

from kukai.modeling.bridge.mocks import MockModelQueryClient
from kukai.modeling.foreman.toolbox import ForemanToolBox
from kukai.modeling.schemas.events import EventBase, EventType
from kukai.modeling.schemas.resolver import FamilySymbolCandidate
from kukai.modeling.schemas.tasks import Phase
from kukai.modeling.state.projections.project_state import ProjectState


def _make_toolbox(
    families: list[FamilySymbolCandidate] | None = None,
    project_state: ProjectState | None = None,
    recent_events: list[EventBase] | None = None,
):
    mock_query = MockModelQueryClient()
    if families:
        mock_query._families = list(families)  # NOTE: field is _families per current mock
    return ForemanToolBox(
        query_client=mock_query,
        project_state_provider=lambda: project_state or ProjectState(),
        recent_events_provider=lambda limit=50: (recent_events or [])[-limit:],
    )


@pytest.mark.asyncio
async def test_list_families_passthrough():
    fam = FamilySymbolCandidate(
        family_symbol_id=10,
        name="К300",
        family_name="ЖБ Колонна",
        category="OST_StructuralColumns",
    )
    tb = _make_toolbox(families=[fam])
    out = await tb.list_families(category="OST_StructuralColumns")
    assert [f.family_symbol_id for f in out] == [10]


@pytest.mark.asyncio
async def test_list_families_filters_by_category():
    a = FamilySymbolCandidate(family_symbol_id=10, name="К300", family_name="ЖБ", category="OST_StructuralColumns")
    b = FamilySymbolCandidate(family_symbol_id=20, name="Дверь", family_name="ДВ", category="OST_Doors")
    tb = _make_toolbox(families=[a, b])
    out = await tb.list_families(category="OST_Doors")
    assert [f.family_symbol_id for f in out] == [20]


@pytest.mark.asyncio
async def test_list_levels_returns_known_levels():
    tb = _make_toolbox()
    levels = await tb.list_levels()
    # MockModelQueryClient seeds at least one level
    assert len(levels) >= 1
    assert all(hasattr(lvl, "elevation_mm") for lvl in levels)


def test_current_phase_reads_from_projection():
    state = ProjectState(current_phase=Phase.STRUCTURE)
    tb = _make_toolbox(project_state=state)
    assert tb.current_phase() == Phase.STRUCTURE


def test_phase_counts_returns_placed_and_failed():
    state = ProjectState(
        current_phase=Phase.STRUCTURE,
        elements_placed=12,
        elements_failed=2,
    )
    tb = _make_toolbox(project_state=state)
    placed, failed = tb.phase_counts()
    assert placed == 12 and failed == 2


def test_recent_events_default_limit():
    events = [
        EventBase(
            event_id=f"e{i}",
            timestamp="2026-05-17T00:00:00Z",
            sequence=i,
            correlation_id="c",
            event_type=EventType.ELEMENT_CREATED,
        )
        for i in range(10)
    ]
    tb = _make_toolbox(recent_events=events)
    out = tb.recent_events(limit=3)
    assert len(out) == 3
    assert out[-1].sequence == 9


def test_user_intervention_state_reflects_projection():
    state = ProjectState(
        user_intervention_required=True,
        user_intervention_reason="ambiguous family",
    )
    tb = _make_toolbox(project_state=state)
    required, reason = tb.user_intervention_state()
    assert required is True
    assert reason == "ambiguous family"


def test_user_intervention_state_default_false():
    tb = _make_toolbox()
    required, reason = tb.user_intervention_state()
    assert required is False and reason is None
