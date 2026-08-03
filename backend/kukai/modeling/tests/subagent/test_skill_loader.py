"""Tests for SkillLoader."""
from __future__ import annotations
import pytest

from kukai.modeling.subagent.skill_loader import SkillLoader, SkillNotFoundError


def test_loads_existing_skill():
    loader = SkillLoader()
    content = loader.load("modeling/structure/columns/concrete-columns")
    assert "Concrete Columns Placement Methodology" in content
    assert len(content) > 1000


def test_raises_for_missing_skill():
    loader = SkillLoader()
    with pytest.raises(SkillNotFoundError, match="does/not/exist"):
        loader.load("does/not/exist")


def test_strips_frontmatter():
    """frontmatter (between --- markers) is stripped from returned content."""
    loader = SkillLoader()
    content = loader.load("modeling/structure/columns/concrete-columns")
    # Frontmatter starts with `name:` etc. — should not appear in stripped output
    assert not content.startswith("---")
    assert "Purpose" in content


def test_full_content_with_frontmatter():
    loader = SkillLoader()
    raw = loader.load_raw("modeling/structure/columns/concrete-columns")
    assert raw.startswith("---")
    assert "name: structural-concrete-columns" in raw
