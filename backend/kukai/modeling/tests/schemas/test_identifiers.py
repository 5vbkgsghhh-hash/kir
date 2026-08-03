"""Tests for identifier value types."""
from __future__ import annotations
import pytest
from pydantic import ValidationError

from kukai.modeling.schemas.identifiers import XYZ, deterministic_task_uuid


class TestXYZ:
    def test_creates_with_floats(self):
        p = XYZ(x=1.0, y=2.0, z=3.0)
        assert p.x == 1.0
        assert p.y == 2.0
        assert p.z == 3.0

    def test_rejects_non_numeric(self):
        with pytest.raises(ValidationError):
            XYZ(x="hello", y=2.0, z=3.0)  # type: ignore

    def test_serializes_to_dict(self):
        p = XYZ(x=1.5, y=2.5, z=3.5)
        assert p.model_dump() == {"x": 1.5, "y": 2.5, "z": 3.5}

    def test_immutable(self):
        p = XYZ(x=1.0, y=2.0, z=3.0)
        with pytest.raises(ValidationError):
            p.x = 99.0  # type: ignore


class TestDeterministicTaskUuid:
    def test_deterministic_for_same_inputs(self):
        u1 = deterministic_task_uuid("proj_1", "structure", 7)
        u2 = deterministic_task_uuid("proj_1", "structure", 7)
        assert u1 == u2

    def test_different_for_different_inputs(self):
        u1 = deterministic_task_uuid("proj_1", "structure", 7)
        u2 = deterministic_task_uuid("proj_1", "structure", 8)
        u3 = deterministic_task_uuid("proj_2", "structure", 7)
        assert len({u1, u2, u3}) == 3

    def test_uuid_format(self):
        u = deterministic_task_uuid("proj_1", "structure", 7)
        assert isinstance(u, str)
        assert len(u) == 16  # hex prefix per spec section 3.5
        assert all(c in "0123456789abcdef" for c in u)
