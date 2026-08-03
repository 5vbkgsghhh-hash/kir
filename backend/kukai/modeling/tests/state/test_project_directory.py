"""Tests for ProjectStateDirectory."""
from __future__ import annotations
from pathlib import Path
import pytest

from kukai.modeling.state.project_directory import ProjectStateDirectory


class TestProjectStateDirectory:
    def test_init_creates_layout(self, tmp_project_dir: Path):
        d = ProjectStateDirectory(tmp_project_dir)
        d.initialize()

        # Per spec Section 9.4
        assert (tmp_project_dir / "brief").is_dir()
        assert (tmp_project_dir / "brief" / "reference_images").is_dir()
        assert (tmp_project_dir / "state").is_dir()
        assert (tmp_project_dir / "state" / "projections").is_dir()
        assert (tmp_project_dir / "state" / "plan").is_dir()
        assert (tmp_project_dir / "outputs").is_dir()
        assert (tmp_project_dir / "outputs" / "code").is_dir()
        assert (tmp_project_dir / "outputs" / "renders").is_dir()
        assert (tmp_project_dir / "outputs" / "qc_reports").is_dir()
        assert (tmp_project_dir / "logs").is_dir()

    def test_history_path(self, tmp_project_dir: Path):
        d = ProjectStateDirectory(tmp_project_dir)
        assert d.history_path == tmp_project_dir / "state" / "history.jsonl"

    def test_projection_path(self, tmp_project_dir: Path):
        d = ProjectStateDirectory(tmp_project_dir)
        assert d.projection_path("model_state") == (
            tmp_project_dir / "state" / "projections" / "model_state.json"
        )

    def test_brief_paths(self, tmp_project_dir: Path):
        d = ProjectStateDirectory(tmp_project_dir)
        assert d.brief_md_path == tmp_project_dir / "brief" / "brief.md"
        assert d.brief_json_path == tmp_project_dir / "brief" / "brief.json"

    def test_idempotent_initialize(self, tmp_project_dir: Path):
        d = ProjectStateDirectory(tmp_project_dir)
        d.initialize()
        d.initialize()  # should not raise
        assert (tmp_project_dir / "state").is_dir()
