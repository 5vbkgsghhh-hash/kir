"""Tests for TemplateRegistry."""
from __future__ import annotations
import pathlib
import pytest

from kukai.modeling.templated.registry import TemplateRegistry


@pytest.fixture
def registry() -> TemplateRegistry:
    """Use the real on-disk templates directory."""
    here = pathlib.Path(__file__).resolve()
    # tests/templated/test_registry.py -> up 3 levels -> backend/kukai/modeling/
    templates_dir = here.parents[2] / "templates"
    return TemplateRegistry(templates_dir)


def test_discovers_first_template(registry: TemplateRegistry):
    names = registry.list_template_names()
    assert "structural_column_at_point" in names


def test_get_manifest(registry: TemplateRegistry):
    m = registry.get_manifest("structural_column_at_point")
    assert m.expected_category == "OST_StructuralColumns"
    assert m.expected_count == 1
    # Has the expected parameters
    param_names = {p.name for p in m.parameters}
    assert {"family_symbol_id", "x_mm", "y_mm", "z_mm", "mark", "level_id"} <= param_names


def test_get_unknown_manifest_raises(registry: TemplateRegistry):
    with pytest.raises(KeyError, match="no template named"):
        registry.get_manifest("nonexistent_template")


def test_render(registry: TemplateRegistry):
    rendered = registry.render(
        "structural_column_at_point",
        {
            "transaction_name": "Place C-2B-L1",
            "family_symbol_id": 8821,
            "level_id": 1042,
            "top_level_id": 1043,
            "x_mm": 6000.0,
            "y_mm": 6000.0,
            "z_mm": 0.0,
            "mark": "C-2B-L1",
        },
    )
    # Validate key C# patterns appear (string contains)
    assert "new ElementId(8821)" in rendered
    assert "new ElementId(1042)" in rendered
    assert "new ElementId(1043)" in rendered
    assert 'new Transaction(doc, "Place C-2B-L1")' in rendered
    assert "UnitUtils.ConvertToInternalUnits(6000.0, UnitTypeId.Millimeters)" in rendered
    assert 'col.LookupParameter("Mark")?.Set("C-2B-L1")' in rendered
    assert "__result__" in rendered


def test_render_without_top_level(registry: TemplateRegistry):
    rendered = registry.render(
        "structural_column_at_point",
        {
            "transaction_name": "Place no-top",
            "family_symbol_id": 8821,
            "level_id": 1042,
            "x_mm": 0.0,
            "y_mm": 0.0,
            "z_mm": 0.0,
            "mark": "C-X",
            # top_level_id omitted
        },
    )
    # The {% if top_level_id %} block must not produce a topLevel assignment
    assert "SCHEDULE_TOP_LEVEL_PARAM" not in rendered


def test_render_validates_args(registry: TemplateRegistry):
    from kukai.modeling.schemas.templates import ManifestValidationError
    with pytest.raises(ManifestValidationError, match="missing required parameter"):
        registry.render(
            "structural_column_at_point",
            {"transaction_name": "x"},  # missing most fields
        )
