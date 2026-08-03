"""ProjectStateDirectory — manages on-disk layout per spec Section 9.4."""
from __future__ import annotations
from pathlib import Path
from typing import Final


_SUBDIRS: Final = (
    "brief",
    "brief/reference_images",
    "state",
    "state/projections",
    "state/plan",
    "outputs",
    "outputs/code",
    "outputs/renders",
    "outputs/qc_reports",
    "logs",
)


class ProjectStateDirectory:
    """Manages the on-disk file layout for a single project.

    All path resolution centralized here so the rest of the engine doesn't
    sprinkle path strings throughout the codebase.
    """

    def __init__(self, root: Path):
        self.root = Path(root)

    def initialize(self) -> None:
        """Create all subdirectories. Idempotent."""
        for sub in _SUBDIRS:
            (self.root / sub).mkdir(parents=True, exist_ok=True)

    @property
    def history_path(self) -> Path:
        return self.root / "state" / "history.jsonl"

    @property
    def brief_md_path(self) -> Path:
        return self.root / "brief" / "brief.md"

    @property
    def brief_json_path(self) -> Path:
        return self.root / "brief" / "brief.json"

    def projection_path(self, name: str) -> Path:
        return self.root / "state" / "projections" / f"{name}.json"

    @property
    def active_plan_path(self) -> Path:
        return self.root / "state" / "plan" / "active_plan.json"

    def code_path(self, task_id: str) -> Path:
        return self.root / "outputs" / "code" / f"{task_id}.cs"

    def render_path(self, gate: str, view: str) -> Path:
        return self.root / "outputs" / "renders" / gate / f"{view}.png"

    @property
    def audit_log_path(self) -> Path:
        return self.root / "outputs" / "audit_log.md"

    @property
    def final_rvt_path(self) -> Path:
        return self.root / "outputs" / "model.rvt"
