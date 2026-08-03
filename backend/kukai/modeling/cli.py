"""Minimal CLI for project lifecycle.

Usage (from backend/):
    python -m kukai.modeling.cli project init <project_id>
    python -m kukai.modeling.cli project list
"""
from __future__ import annotations
import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
import uuid

from kukai.modeling.schemas.events import EventBase, EventType
from kukai.modeling.state.event_bus import EventBus
from kukai.modeling.state.project_directory import ProjectStateDirectory


DEFAULT_PROJECTS_ROOT = Path(__file__).resolve().parents[2] / "data" / "projects"


def cmd_project_init(project_id: str, projects_root: Path) -> dict:
    """Initialize a new project directory and emit PROJECT_CREATED event."""
    project_path = projects_root / project_id
    if project_path.exists():
        raise FileExistsError(f"Project already exists: {project_path}")
    project_path.mkdir(parents=True)

    pdir = ProjectStateDirectory(project_path)
    pdir.initialize()

    bus = EventBus(pdir)
    bus.emit(EventBase(
        event_id=uuid.uuid4().hex,
        timestamp=datetime.now(timezone.utc),
        sequence=0,
        correlation_id=project_id,
        causation_id=None,
        event_type=EventType.PROJECT_CREATED,
        payload={"project_id": project_id},
    ))

    return {
        "status": "created",
        "project_id": project_id,
        "path": str(project_path),
    }


def cmd_project_list(projects_root: Path) -> dict:
    """List initialized projects (any subdir of projects_root)."""
    if not projects_root.exists():
        return {"projects": []}
    projects = sorted(
        p.name for p in projects_root.iterdir()
        if p.is_dir() and (p / "state" / "history.jsonl").exists()
    )
    return {"projects": projects}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kukai-modeling")
    parser.add_argument(
        "--projects-root",
        type=Path,
        default=DEFAULT_PROJECTS_ROOT,
        help="root directory containing projects",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    init_p = sub.add_parser("init", help="initialize a new project")
    init_p.add_argument("project_id")

    sub.add_parser("list", help="list initialized projects")

    args = parser.parse_args(argv)

    if args.cmd == "init":
        try:
            result = cmd_project_init(args.project_id, args.projects_root)
        except FileExistsError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        print(f"Created project: {result['project_id']} at {result['path']}")
        return 0

    if args.cmd == "list":
        result = cmd_project_list(args.projects_root)
        for p in result["projects"]:
            print(p)
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
