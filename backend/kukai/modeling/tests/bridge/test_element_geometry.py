"""Phase 4 Task 3 — ElementGeometry schema + ModelQueryClient extension."""
from __future__ import annotations
import pytest
from pydantic import ValidationError

from kukai.modeling.bridge.model_query_client import ElementGeometry


def test_element_geometry_minimal():
    g = ElementGeometry(
        element_id=9001,
        bounding_box_min_mm=(0.0, 0.0, 0.0),
        bounding_box_max_mm=(400.0, 400.0, 3000.0),
        centroid_mm=(200.0, 200.0, 1500.0),
        host_element_id=None,
        level_id=1,
    )
    assert g.element_id == 9001
    assert g.bounding_box_min_mm == (0.0, 0.0, 0.0)
    assert g.centroid_mm == (200.0, 200.0, 1500.0)
    assert g.host_element_id is None
    assert g.level_id == 1


def test_element_geometry_frozen():
    g = ElementGeometry(
        element_id=9001,
        bounding_box_min_mm=(0.0, 0.0, 0.0),
        bounding_box_max_mm=(1.0, 1.0, 1.0),
        centroid_mm=(0.5, 0.5, 0.5),
        host_element_id=None,
        level_id=None,
    )
    with pytest.raises(ValidationError):
        g.element_id = 1234  # type: ignore[misc]
