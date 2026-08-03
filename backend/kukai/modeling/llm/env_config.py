"""Environment variable loading for LLM clients.

KUKAI keeps Vertex AI credentials in `backend/.env` (main repo, not worktree).
This module loads them via python-dotenv if available, then exposes a typed
config object. Designed to work both from the main repo and from worktrees.
"""
from __future__ import annotations
import os
import pathlib
from dataclasses import dataclass


@dataclass(frozen=True)
class VertexAIConfig:
    api_key: str
    project: str
    location: str

    @property
    def available(self) -> bool:
        return bool(self.api_key and self.project and self.location)


def _candidate_env_paths() -> list[pathlib.Path]:
    """Return possible .env locations in priority order.

    Order:
    1. KUKAI_ENV_PATH env var (explicit override)
    2. backend/.env relative to this file's grand-grand-grand-parent (worktree)
    3. ../../../../backend/.env (worktree -> main repo backend)
    4. C:/kukai-rebuild1/backend/.env (absolute fallback for known main repo)
    """
    paths: list[pathlib.Path] = []
    explicit = os.environ.get("KUKAI_ENV_PATH")
    if explicit:
        paths.append(pathlib.Path(explicit))

    here = pathlib.Path(__file__).resolve()
    # backend/kukai/modeling/llm/env_config.py
    # parents[3] = backend
    candidate_in_repo = here.parents[3] / ".env"
    paths.append(candidate_in_repo)

    # If running from a git worktree under .claude/worktrees/<name>/backend/...
    # the main repo backend/.env is at: parents[3].parents[2] / "backend" / ".env"
    # (worktrees/<name>/backend -> worktrees/<name> -> .claude -> repo_root, then /backend/.env)
    # We try this only if the in-repo candidate is missing.
    if not candidate_in_repo.exists():
        wt_main = here.parents[3].parents[2] / "backend" / ".env"
        paths.append(wt_main)

    # Last resort absolute (works on the developer's known machine)
    paths.append(pathlib.Path("C:/kukai-rebuild1/backend/.env"))

    return paths


def _load_dotenv_if_present() -> None:
    """Best-effort .env load. No-op if python-dotenv missing or no file found."""
    try:
        from dotenv import load_dotenv  # type: ignore
    except ImportError:
        return
    for p in _candidate_env_paths():
        if p.exists():
            load_dotenv(p, override=False)
            return


def get_vertex_config() -> VertexAIConfig:
    """Return VertexAIConfig from env. Missing vars become empty strings."""
    _load_dotenv_if_present()
    return VertexAIConfig(
        api_key=os.environ.get("KUKAI_VERTEX_AI_API_KEY", ""),
        project=os.environ.get("KUKAI_VERTEX_AI_PROJECT", ""),
        location=os.environ.get("KUKAI_VERTEX_AI_LOCATION", ""),
    )
