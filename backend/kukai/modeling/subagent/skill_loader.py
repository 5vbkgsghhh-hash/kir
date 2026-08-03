"""SkillLoader — load methodology .md files from skills/ tree.

Per spec Section 5.4 + Plan 6 audit response. Skill paths use forward slashes
without `.md` suffix; loader resolves to `kukai/modeling/skills/<path>.md`.

Two modes:
- `load(path)` — strips YAML frontmatter, returns markdown body. This is what
  Subagent prompt assembly uses (frontmatter is loader metadata, not LLM input).
- `load_raw(path)` — returns full file content (frontmatter + body) for tooling.
"""
from __future__ import annotations
import pathlib


_SKILLS_ROOT = pathlib.Path(__file__).resolve().parents[1] / "skills"


class SkillNotFoundError(FileNotFoundError):
    """Raised when a skill path doesn't resolve to a file."""


class SkillLoader:
    """Loads skill markdown files by logical path (no .md suffix)."""

    def __init__(self, root: pathlib.Path | None = None):
        self._root = root or _SKILLS_ROOT

    def _resolve(self, path: str) -> pathlib.Path:
        return self._root / f"{path}.md"

    def load_raw(self, path: str) -> str:
        """Return full file content including frontmatter."""
        p = self._resolve(path)
        if not p.exists():
            raise SkillNotFoundError(f"skill not found: {path} (resolved to {p})")
        return p.read_text(encoding="utf-8")

    def load(self, path: str) -> str:
        """Return file content with YAML frontmatter stripped."""
        raw = self.load_raw(path)
        return _strip_frontmatter(raw)


def _strip_frontmatter(content: str) -> str:
    """Remove leading `---\\n...\\n---\\n` YAML frontmatter block if present."""
    if not content.startswith("---"):
        return content
    lines = content.splitlines(keepends=True)
    # First line is `---`. Find the next `---` on its own line.
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "".join(lines[i + 1 :]).lstrip("\n")
    # No closing `---` found — return as-is
    return content
