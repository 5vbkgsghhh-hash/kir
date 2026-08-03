"""Shared pytest fixtures for modeling engine tests."""
from __future__ import annotations
import pytest
import tempfile
from pathlib import Path

from kukai.modeling.schemas.llm import DeclaredOutputs


@pytest.fixture
def tmp_project_dir(tmp_path: Path) -> Path:
    """Temporary directory for a single project. Auto-cleaned after test."""
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    return project_dir


def default_declared_outputs(
    *, expected_element_count: int = 1,
    expected_category: str = "OST_StructuralColumns",
) -> DeclaredOutputs:
    """Helper for tests that want to exercise the VF path with a declaration.

    Phase 4 Task 1 (VeriMAP). declared_outputs is Optional[DeclaredOutputs] on
    CodeProposal (default None means "skip VF").
    """
    return DeclaredOutputs(
        expected_element_count=expected_element_count,
        expected_category=expected_category,
    )
