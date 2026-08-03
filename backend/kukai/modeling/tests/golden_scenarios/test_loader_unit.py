"""Unit tests for the scenario YAML loader (does not run Foreman)."""
from __future__ import annotations
from pathlib import Path
import pytest

from kukai.modeling.tests.golden_scenarios._loader import load_scenario, Scenario

_HERE = Path(__file__).parent


def test_loader_parses_t1_single_column():
    sc = load_scenario(_HERE / "t1_single_column_success.yaml")
    assert isinstance(sc, Scenario)
    assert sc.name == "t1_single_column_success"
    assert sc.phase_plan.phase.value == "structure"
    assert len(sc.phase_plan.tasks) == 1
    assert sc.expected["phase_status"] == "completed"


def test_loader_rejects_missing_required_field(tmp_path: Path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("name: x\n", encoding="utf-8")
    with pytest.raises((KeyError, ValueError)):
        load_scenario(bad)


@pytest.mark.tier0
def test_scenario_rejects_typo_in_key(tmp_path: Path):
    """Audit N14: extra keys (typos) raise at load time, not silently dropped."""
    # Build a scenario YAML that's otherwise valid but has a top-level typo.
    bad = tmp_path / "typo.yaml"
    bad.write_text(
        """
name: typo_test
project_id: proj_typo
phase_plan:
  phase: structure
  tasks:
    - plan_task_id: pt_0001
      intent:
        element_type: structural_column
        family_hint: {category: OST_StructuralColumns}
        grid_intersection: {grid_x_name: A, grid_y_name: "1", level_name: L1}
        revit_version: "2026"
      expected_elements: {category: OST_StructuralColumns, count: 1}
      tier: subagent_per_element
      skill_path: modeling/structure/columns/concrete-columns.md
# typo: 'scriptd_llm_responses' missing 'e'
scriptd_llm_responses: []
expected:
  phase_status: completed
  succeeded_count: 1
  failed_count: 0
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="(?i)(extra|forbid|scriptd_llm)"):
        load_scenario(bad)


@pytest.mark.tier0
def test_scenario_rejects_typo_in_expected_key(tmp_path: Path):
    """Audit N14: typo inside `expected:` block is caught too."""
    bad = tmp_path / "expected_typo.yaml"
    bad.write_text(
        """
name: expected_typo_test
project_id: proj_typo
phase_plan:
  phase: structure
  tasks:
    - plan_task_id: pt_0001
      intent:
        element_type: structural_column
        family_hint: {category: OST_StructuralColumns}
        grid_intersection: {grid_x_name: A, grid_y_name: "1", level_name: L1}
        revit_version: "2026"
      expected_elements: {category: OST_StructuralColumns, count: 1}
      tier: subagent_per_element
      skill_path: modeling/structure/columns/concrete-columns.md
expected:
  phase_status: completed
  succeded_count: 1   # typo
  failed_count: 0
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="(?i)(extra|forbid|succeded)"):
        load_scenario(bad)
