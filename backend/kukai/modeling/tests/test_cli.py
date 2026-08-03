"""Tests for modeling CLI."""
from __future__ import annotations
from pathlib import Path
import pytest

from kukai.modeling.cli import cmd_project_init, cmd_project_list


def test_project_init_creates_layout(tmp_path: Path):
    project_id = "test_t1_001"
    result = cmd_project_init(
        project_id=project_id,
        projects_root=tmp_path,
    )

    assert result["status"] == "created"
    assert result["project_id"] == project_id
    assert (tmp_path / project_id / "state").is_dir()
    assert (tmp_path / project_id / "state" / "history.jsonl").exists()


def test_project_init_rejects_duplicate(tmp_path: Path):
    project_id = "test_t1_001"
    cmd_project_init(project_id=project_id, projects_root=tmp_path)

    with pytest.raises(FileExistsError):
        cmd_project_init(project_id=project_id, projects_root=tmp_path)


def test_project_list_empty(tmp_path: Path):
    result = cmd_project_list(projects_root=tmp_path)
    assert result["projects"] == []


def test_project_list_returns_initialised(tmp_path: Path):
    cmd_project_init(project_id="proj_a", projects_root=tmp_path)
    cmd_project_init(project_id="proj_b", projects_root=tmp_path)

    result = cmd_project_list(projects_root=tmp_path)
    assert sorted(result["projects"]) == ["proj_a", "proj_b"]
