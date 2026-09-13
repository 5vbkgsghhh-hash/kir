"""G7 — what a role receives before it says one word.

Measured 13.09.2026 on the MCP door: `tools/list` 17 393 B plus
`instructions()` 48 088 B = 65 481 B, and before section H's правка 3 it was
123 672 B — about 41 000 tokens spent before the agent reads the task. On a
200k model that is a fifth of the context, paid again on every cold start.
"""
from __future__ import annotations

from kir.door import registry as R

#: Gate G7. Measured on this tree: lead 3 664 B, expert 4 172 B.
FIRST_TOUCH_MAX_BYTES = 8_000

#: What the MCP door cost before the door existed, kept as a number so the
#: saving is a fact and not a memory.
FIRST_TOUCH_BEFORE_BYTES = 123_672


def test_the_first_touch_stays_under_the_ratchet():
    for role in R.ROLES:
        size = R.first_touch_bytes(role)
        assert size <= FIRST_TOUCH_MAX_BYTES, f"{role}: {size} Б"


def test_the_saving_is_an_order_of_magnitude():
    """Stated as a ratio against a measured number, so a change that quietly
    gives it back is red here and not in someone's context window."""
    worst = max(R.first_touch_bytes(role) for role in R.ROLES)
    assert worst * 10 < FIRST_TOUCH_BEFORE_BYTES


def test_the_notice_is_a_notice_and_not_a_course():
    for role in R.ROLES:
        notice = R.notice(role)
        assert len(notice.encode()) <= R.NOTICE_MAX_BYTES, role
        assert notice.strip()


def test_the_notice_names_no_operation():
    """The course is dead, not moved: a notice that lists ops is the course
    again under a shorter name. Checked against all 83."""
    from kir import spec

    for role in R.ROLES:
        notice = R.notice(role)
        leaked = sorted(op for op in spec.OPS if op in notice)
        assert leaked == [], (role, leaked)


def test_the_lead_notice_tells_the_sections_and_the_gaps():
    notice = R.notice("lead")
    for section in ("АР", "КР", "ОВ", "ВК", "ЭОМ"):
        assert section in notice
    # ОТК-47: СС and ГП are absent from the registry, and the lead must be
    # able to say so to the human instead of silently failing to assign.
    assert "генплан" in notice.lower() or "слаботоч" in notice.lower()


def test_control_restoring_the_language_prose_goes_red():
    from kir.tool_doc import build_tool_description

    fat = len(build_tool_description().encode())
    assert fat > R.NOTICE_MAX_BYTES
    assert max(R.surface_bytes(r) for r in R.ROLES) + fat > FIRST_TOUCH_MAX_BYTES
