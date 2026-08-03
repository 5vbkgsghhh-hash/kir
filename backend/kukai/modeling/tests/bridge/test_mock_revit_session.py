"""Tests for MockRevitSession — passive recorder of Revit code execution.

Round 1A pivot: the session no longer parses C#. Tests that pinned regex
behavior (NewFamilyInstance match, Transaction balance, StructuralType
category mapping, unknown FamilySymbol id, grid-bounds rejection) have
been retired — those concerns now live at higher gates (invariants,
Roslyn, real Revit). What remains:

  - State plumbing (default seeding, custom seeding, reset, list/get)
  - SessionBacked query-client protocol coverage (audit N5 — unchanged)
  - Duplicate-Mark detection (state-based, defensible)
  - Mark-pairing via tiny single-token regex
  - Forced-failure injection
  - Passive-recorder behavior: any C# → success + element_id from brief
  - Idempotent execute_code_for_task
  - MockBridgeClient delegation
"""
from __future__ import annotations
import pytest

from kukai.modeling.bridge.model_query_client import GridInfo, LevelInfo
from kukai.modeling.bridge.mock_revit_session import MockRevitSession, PlacedElement
from kukai.modeling.schemas.identifiers import XYZ
from kukai.modeling.schemas.resolver import FamilySymbolCandidate
from kukai.modeling.schemas.tasks import (
    ExpectedElementsSpec, Phase, TaskBrief, Tier,
)


# ---------- helpers ----------

def _col_fam(symbol_id: int = 42) -> FamilySymbolCandidate:
    return FamilySymbolCandidate(
        family_symbol_id=symbol_id, name="C 400x400",
        family_name="Concrete-Square", category="OST_StructuralColumns")


def _make_placed(element_id: int = 9000, task_id: str | None = None) -> PlacedElement:
    return PlacedElement(
        element_id=element_id, category="OST_StructuralColumns",
        family_symbol_id=42, level_id=1, location_mm=(0.0, 0.0, 0.0),
        placed_by_task_id=task_id,
    )


def _brief(
    *,
    task_id: str = "t1_test_brief",
    placement_point: tuple[float, float, float] = (0.0, 0.0, 0.0),
    family_symbol_id: int = 42,
    level_id: int = 1,
    count: int = 1,
    category: str = "OST_StructuralColumns",
    level_name: str | None = None,
) -> TaskBrief:
    x, y, z = placement_point
    return TaskBrief(
        task_id=task_id,
        phase=Phase.STRUCTURE,
        skill_path="modeling/structure/columns/concrete-columns.md",
        element_type="structural_column",
        placement_point=XYZ(x=x, y=y, z=z),
        family_symbol_id=family_symbol_id,
        parameter_map={},
        level_id=level_id,
        top_level_id=None,
        revit_version="2026",
        expected_elements=ExpectedElementsSpec(
            category=category, count=count, level_name=level_name,
            required_parameters=[],
        ),
        constraints=[],
        tier=Tier.TIER_2,
        is_repair=False,
        repair_for_task_id=None,
        estimated_cost_usd=0.05,
    )


# ---------- session-backed query client (audit N5 — preserved) ----------

@pytest.mark.tier0
@pytest.mark.asyncio
async def test_session_backed_query_client_satisfies_protocol():
    """Audit N5: _SessionBackedModelQueryClient implements ALL ModelQueryClient methods.

    After Round 1A the Level field in query_element_properties returns the
    level NAME (resolved via session._levels), not str(level_id), so L5.5
    PropertyValidationGate comparing against brief.expected_elements.level_name
    matches without coercion.
    """
    session = MockRevitSession(
        levels=[LevelInfo(level_id=1, name="L1", elevation_mm=0.0)],
    )
    session._placed[9001] = PlacedElement(
        element_id=9001, category="OST_StructuralColumns",
        family_symbol_id=42, level_id=1, location_mm=(100.0, 200.0, 1500.0),
        parameters={"Mark": "C-01", "Comments": "structural"},
        placed_by_task_id="t1",
    )
    qc = session.get_query_client()
    required = (
        "query_families", "query_levels", "query_grids",
        "query_parameter_info", "query_element_properties",
        "query_element_geometry",
    )
    for name in required:
        assert callable(getattr(qc, name)), f"missing {name}"

    props = await qc.query_element_properties(9001)
    assert props["Mark"] == "C-01"
    assert props["Level"] == "L1"  # name, not id
    assert props["FamilySymbolId"] == "42"
    assert props["Comments"] == "structural"

    geom = await qc.query_element_geometry(9001)
    assert geom.element_id == 9001
    assert geom.centroid_mm == (100.0, 200.0, 1500.0)
    assert geom.level_id == 1
    assert geom.host_element_id is None
    assert geom.bounding_box_min_mm == (99.5, 199.5, 1499.5)
    assert geom.bounding_box_max_mm == (100.5, 200.5, 1500.5)

    with pytest.raises(ValueError, match="not in session"):
        await qc.query_element_properties(99999)
    with pytest.raises(ValueError, match="not in session"):
        await qc.query_element_geometry(99999)


@pytest.mark.tier0
async def _noop_async():
    return


@pytest.mark.tier0
def test_default_seeding_has_one_level_and_four_grids():
    session = MockRevitSession()
    assert len(session.levels) == 1 and session.levels[0].name == "L1"
    names_axes = {(g.name, g.axis) for g in session.grids}
    assert len(session.grids) == 4
    assert ("A", "horizontal") in names_axes
    assert ("1", "vertical") in names_axes


@pytest.mark.tier0
def test_custom_grids_seeding_honored():
    custom = [GridInfo(grid_id=99, name="Z", axis="horizontal", position_mm=12345.0)]
    assert MockRevitSession(grids=custom).grids == custom


@pytest.mark.tier0
def test_explicitly_empty_grids_are_honored():
    assert MockRevitSession(grids=[]).grids == []


@pytest.mark.tier0
def test_custom_levels_seeding_honored():
    custom = [
        LevelInfo(level_id=2, name="L2", elevation_mm=3000.0),
        LevelInfo(level_id=3, name="L3", elevation_mm=6000.0),
    ]
    assert MockRevitSession(levels=custom).levels == custom


@pytest.mark.tier0
def test_families_default_empty():
    assert MockRevitSession().families == []


@pytest.mark.tier0
def test_families_custom_honored():
    fam = _col_fam(42)
    assert MockRevitSession(families=[fam]).families == [fam]


@pytest.mark.tier0
def test_list_placed_elements_initially_empty():
    assert MockRevitSession().list_placed_elements() == []


@pytest.mark.tier0
def test_get_element_returns_none_for_unknown_id():
    assert MockRevitSession().get_element(99999) is None


@pytest.mark.tier0
def test_store_and_lookup_placed_element():
    session = MockRevitSession()
    el = _make_placed(task_id="t1task01")
    session._store(el)
    assert session.get_element(9000) == el
    assert session.list_placed_elements() == [el]


@pytest.mark.tier0
def test_reset_clears_placed_and_records_keeps_seed():
    session = MockRevitSession()
    session.execute_code("// noop", task_brief=_brief())
    assert len(session.list_placed_elements()) == 1
    assert len(session.execution_records()) == 1
    session.reset()
    assert session.list_placed_elements() == []
    assert session.execution_records() == []
    assert len(session.grids) == 4 and len(session.levels) == 1
    # And _next_element_id is back to 9000 (next placement uses 9000).
    second = session.execute_code("// after reset", task_brief=_brief(task_id="t2afterre"))
    assert second["element_ids"] == [9000]


@pytest.mark.tier0
@pytest.mark.asyncio
async def test_get_query_client_returns_seeded_views():
    fam = _col_fam(42)
    session = MockRevitSession(families=[fam])
    qc = session.get_query_client()
    assert (await qc.query_levels())[0].name == "L1"
    assert len(await qc.query_grids()) == 4
    assert await qc.query_families(category="OST_StructuralColumns") == [fam]
    assert await qc.query_families(category="OST_Walls") == []


# ---------- Round 1A: passive-recorder behavior ----------

@pytest.mark.tier0
def test_execute_code_returns_success_for_any_csharp():
    """The mock no longer parses C# — any string succeeds and yields an element_id."""
    session = MockRevitSession()
    result = session.execute_code(
        "// production-style C# we used to fail to parse",
        task_brief=_brief(),
    )
    assert result["success"] is True
    assert len(result["element_ids"]) == 1
    assert result["error"] is None
    placed = session.list_placed_elements()
    assert len(placed) == 1


@pytest.mark.tier0
def test_brief_data_populates_placed_element():
    """family_symbol_id, level_id, location_mm, category all come from the brief."""
    session = MockRevitSession(
        levels=[LevelInfo(level_id=8001, name="Level 1", elevation_mm=0.0)],
    )
    brief = _brief(
        family_symbol_id=9001,
        level_id=8001,
        placement_point=(15000.0, 7500.0, 0.0),
        category="OST_StructuralColumns",
    )
    result = session.execute_code(
        "// production-style code", task_brief=brief, expected_count=1,
    )
    assert result["success"] is True
    placed = session.list_placed_elements()
    assert len(placed) == 1
    el = placed[0]
    assert el.family_symbol_id == 9001
    assert el.level_id == 8001
    assert el.location_mm == (15000.0, 7500.0, 0.0)
    assert el.category == "OST_StructuralColumns"


@pytest.mark.tier0
def test_mark_regex_extraction_works():
    """The tiny single-token Mark regex captures `.LookupParameter("Mark").Set("X")` values."""
    session = MockRevitSession()
    code = (
        'var inst = doc.Create.NewFamilyInstance(...);\n'
        'inst.LookupParameter("Mark").Set("C-42");\n'
    )
    result = session.execute_code(code, task_brief=_brief())
    assert result["success"] is True
    el = session.get_element(result["element_ids"][0])
    assert el is not None
    assert el.parameters.get("Mark") == "C-42"


@pytest.mark.tier0
def test_mark_regex_extraction_handles_null_conditional():
    """`.LookupParameter("Mark")?.Set("X")` (null-conditional) also captures."""
    session = MockRevitSession()
    code = 'inst.LookupParameter("Mark")?.Set("C-NC");\n'
    result = session.execute_code(code, task_brief=_brief())
    assert result["success"] is True
    el = session.get_element(result["element_ids"][0])
    assert el.parameters.get("Mark") == "C-NC"


@pytest.mark.tier0
def test_mark_absent_auto_generated():
    """When no Mark in code, an AUTO-NN value is synthesized so L5.5 sees one."""
    session = MockRevitSession()
    result = session.execute_code("// no mark here", task_brief=_brief())
    el = session.get_element(result["element_ids"][0])
    assert el.parameters["Mark"].startswith("AUTO-")


@pytest.mark.tier0
def test_runner_current_task_register_is_used_when_kwargs_omitted():
    """set_current_task() lets a runner forward brief data without changing the bridge signature."""
    session = MockRevitSession()
    brief = _brief(family_symbol_id=777, level_id=8001, placement_point=(99.0, 0.0, 0.0))
    session.set_current_task(task_brief=brief, plan_task_id="pt_X")
    # NOTE: no explicit kwargs passed to execute_code.
    result = session.execute_code("// any code")
    assert result["success"] is True
    el = session.get_element(result["element_ids"][0])
    assert el.family_symbol_id == 777
    assert el.location_mm == (99.0, 0.0, 0.0)
    records = session.execution_records()
    assert records[0].plan_task_id == "pt_X"


@pytest.mark.tier0
def test_execution_records_capture_call_metadata():
    """Each execute_code call recorded: code, hash, brief linkage, success."""
    session = MockRevitSession()
    session.execute_code("// call one", task_brief=_brief(task_id="t1briefid"))
    session.execute_code("// call two", task_brief=_brief(task_id="t2briefid"))
    records = session.execution_records()
    assert len(records) == 2
    assert records[0].code == "// call one"
    assert records[0].task_brief_task_id == "t1briefid"
    assert records[0].success is True
    assert len(records[0].code_hash) == 16  # 16-char prefix


# ---------- duplicate-Mark detection (state-based, preserved) ----------

@pytest.mark.tier0
def test_duplicate_mark_within_session_rejected():
    session = MockRevitSession()
    code = 'inst.LookupParameter("Mark").Set("X");'
    first = session.execute_code(code, task_brief=_brief(task_id="t1_first"))
    assert first["success"] is True
    second = session.execute_code(code, task_brief=_brief(task_id="t1_second"))
    assert second["success"] is False
    assert "DuplicateMark" in second["error"]


@pytest.mark.tier0
def test_duplicate_marks_in_same_code_block_rejected():
    session = MockRevitSession()
    code = (
        'a.LookupParameter("Mark").Set("X");\n'
        'b.LookupParameter("Mark").Set("X");\n'
    )
    brief = _brief(count=2)
    result = session.execute_code(code, task_brief=brief)
    assert result["success"] is False
    assert "DuplicateMark" in result["error"]


# ---------- forced-failure injection ----------

@pytest.mark.tier0
def test_forced_failure_injection_one_shot():
    session = MockRevitSession()
    session.set_next_failure("DuplicateMarkError: simulated")
    result = session.execute_code("// any code", task_brief=_brief())
    assert result["success"] is False
    assert "DuplicateMarkError" in result["error"]
    # And the injection is one-shot.
    second = session.execute_code("// any code", task_brief=_brief(task_id="t2second"))
    assert second["success"] is True


# ---------- idempotent replay ----------

@pytest.mark.tier0
def test_idempotent_replay_with_task_id_returns_existing_ids():
    """Same task_id, second call → original element_ids, no duplicate placement."""
    session = MockRevitSession()
    brief = _brief(task_id="t1_idempot")
    first = session.execute_code_for_task(
        "// code", task_id="t1task01", expected_count=1, task_brief=brief,
    )
    assert first["success"] is True
    second = session.execute_code_for_task(
        "// code", task_id="t1task01", expected_count=1, task_brief=brief,
    )
    assert second["success"] is True
    assert second["element_ids"] == first["element_ids"]
    assert len(session.list_placed_elements()) == 1


# ---------- MockBridgeClient delegation ----------

@pytest.mark.tier0
@pytest.mark.asyncio
async def test_mock_bridge_client_delegates_to_session_when_provided():
    from kukai.modeling.bridge.mocks import MockBridgeClient
    session = MockRevitSession()
    brief = _brief()
    client = MockBridgeClient(revit_session=session)
    result = await client.execute_code(
        "mock_session", "// any code", expected_count=1, task_brief=brief,
    )
    assert result["success"] is True
    assert len(session.list_placed_elements()) == 1


@pytest.mark.tier0
@pytest.mark.asyncio
async def test_mock_bridge_client_scripted_when_session_absent():
    from kukai.modeling.bridge.mocks import MockBridgeClient
    client = MockBridgeClient()
    result = await client.execute_code("mock_session", "// no real code", expected_count=2)
    assert result["success"] is True
    assert len(result["element_ids"]) == 2
