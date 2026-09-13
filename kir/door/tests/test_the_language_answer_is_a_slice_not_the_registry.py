"""G3 — the reference is a SLICE, pulled, and it has TWO ceilings.

S measured all three roads on 13.09.2026: a section slice gave YES on the
first attempt at 940 characters of prompt and 0 refusals; the whole registry
plus help gave YES on the second at 2 781; **without help the model scored
zero on both tasks** — it tries to invent the reference and never reaches a
program. So the slice is not economy, it is what works.
"""
from __future__ import annotations

from kir.door.read import (LANGUAGE_MAX_CHARS_SECTIONED,
                           LANGUAGE_MAX_CHARS_WHOLE, SECTION_OF_RU,
                           help_text, language_text)

#: Measured 13.09 (`spec.ops_by_discipline(writes=True)`, own + "общее"):
#: КР 513 · ОВ ~477 · ВК ~483 · ЭОМ ~450 · АР 828 characters with headings.
#: The ceiling is taken from the largest and is deliberately tight.
MEASURED_WHOLE_CHARS = 1_417


def test_a_sectioned_expert_gets_only_its_own_names():
    for ru in SECTION_OF_RU:
        text, sectioned = language_text(ru)
        assert sectioned is True, ru
        assert len(text) <= LANGUAGE_MAX_CHARS_SECTIONED, (
            f"срез {ru}: {len(text)} знаков > {LANGUAGE_MAX_CHARS_SECTIONED}")
        assert text.strip()


def test_the_whole_registry_answer_stays_under_the_ceiling():
    text, sectioned = language_text(None)
    assert sectioned is False
    assert len(text) <= LANGUAGE_MAX_CHARS_WHOLE, f"{len(text)} знаков"


def test_the_slice_comes_from_the_registry_not_a_literal():
    """Compared as SETS against the registry. A literal list here would be a
    second carrier of truth about the language and would drift on the first
    new op — silently, which is the expensive way."""
    from kir import spec

    groups = dict(spec.ops_by_discipline(writes=True))
    shared = set(groups.get("shared", ()))
    for ru, key in SECTION_OF_RU.items():
        text, _ = language_text(ru)
        got = {line for line in text.splitlines() if line in spec.OPS}
        assert got == set(groups[key]) | shared, ru


def test_the_whole_answer_is_the_whole_registry():
    from kir import spec

    text, _ = language_text(None)
    assert {ln for ln in text.splitlines() if ln} == set(spec.OPS)


def test_help_is_the_sdk_docstring_and_not_a_second_copy():
    from kir import sdk

    text = help_text("create_wall")
    assert text and text == (sdk.builders()["create_wall"].__doc__ or "").strip()
    assert help_text("invented") is None


def test_control_serving_all_names_to_a_sectioned_expert_goes_red():
    """🔴 THIS IS WHY THERE ARE TWO CEILINGS. A single ceiling of 1 500 would
    pass the full registry (measured 1 417) to a sectioned expert, and the
    gate would be decoration."""
    whole, _ = language_text(None)
    assert len(whole) == MEASURED_WHOLE_CHARS or len(whole) <= LANGUAGE_MAX_CHARS_WHOLE
    assert len(whole) > LANGUAGE_MAX_CHARS_SECTIONED
