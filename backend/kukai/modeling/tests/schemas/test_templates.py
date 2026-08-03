"""Tests for template manifest schemas."""
from __future__ import annotations
import pytest
from pydantic import ValidationError

from kukai.modeling.schemas.templates import (
    ManifestParameter,
    ManifestSpec,
    ManifestValidationError,
)


class TestManifestParameter:
    def test_int_with_bounds(self):
        p = ManifestParameter(name="x_mm", type="float", min=-100000, max=100000, required=True)
        assert p.type == "float"

    def test_string_required(self):
        p = ManifestParameter(name="mark", type="string", required=True)
        assert p.required is True

    def test_int_id_default(self):
        p = ManifestParameter(name="level_id", type="int", required=True)
        assert p.min is None and p.max is None

    def test_invalid_type_rejected(self):
        with pytest.raises(ValidationError):
            ManifestParameter(name="x", type="bogus")  # type: ignore


class TestManifestSpec:
    def test_creates_with_required_fields(self):
        m = ManifestSpec(
            template="structural_column_at_point.cs.j2",
            parameters=[
                ManifestParameter(name="name", type="string", required=True),
                ManifestParameter(name="x_mm", type="float", required=True, min=-100000, max=100000),
            ],
            expected_category="OST_StructuralColumns",
            expected_count=1,
        )
        assert m.template.endswith(".cs.j2")
        assert len(m.parameters) == 2

    def test_validate_args_happy(self):
        m = ManifestSpec(
            template="x.cs.j2",
            parameters=[
                ManifestParameter(name="x_mm", type="float", required=True, min=0, max=1000),
                ManifestParameter(name="name", type="string", required=True),
            ],
            expected_category="OST_StructuralColumns",
            expected_count=1,
        )
        # Returns the validated args dict on success
        out = m.validate_args({"x_mm": 500.0, "name": "C-1A-L1"})
        assert out == {"x_mm": 500.0, "name": "C-1A-L1"}

    def test_validate_args_missing_required(self):
        m = ManifestSpec(
            template="x.cs.j2",
            parameters=[ManifestParameter(name="x_mm", type="float", required=True)],
            expected_category="OST_StructuralColumns",
            expected_count=1,
        )
        with pytest.raises(ManifestValidationError, match="missing required parameter 'x_mm'"):
            m.validate_args({})

    def test_validate_args_type_mismatch(self):
        m = ManifestSpec(
            template="x.cs.j2",
            parameters=[ManifestParameter(name="x_mm", type="float", required=True)],
            expected_category="OST_StructuralColumns",
            expected_count=1,
        )
        with pytest.raises(ManifestValidationError, match="type mismatch"):
            m.validate_args({"x_mm": "not_a_number"})

    def test_validate_args_out_of_bounds(self):
        m = ManifestSpec(
            template="x.cs.j2",
            parameters=[ManifestParameter(name="x_mm", type="float", required=True, min=0, max=1000)],
            expected_category="OST_StructuralColumns",
            expected_count=1,
        )
        with pytest.raises(ManifestValidationError, match="out of range"):
            m.validate_args({"x_mm": -50.0})

    def test_validate_args_extra_args_rejected(self):
        m = ManifestSpec(
            template="x.cs.j2",
            parameters=[ManifestParameter(name="x_mm", type="float", required=True)],
            expected_category="OST_StructuralColumns",
            expected_count=1,
        )
        with pytest.raises(ManifestValidationError, match="unexpected parameter 'rogue'"):
            m.validate_args({"x_mm": 5.0, "rogue": "x"})

    def test_validate_args_coerces_int_to_float(self):
        """Ints are valid where floats expected."""
        m = ManifestSpec(
            template="x.cs.j2",
            parameters=[ManifestParameter(name="x_mm", type="float", required=True)],
            expected_category="OST_StructuralColumns",
            expected_count=1,
        )
        out = m.validate_args({"x_mm": 5})
        assert out["x_mm"] == 5
